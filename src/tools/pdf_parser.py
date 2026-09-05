"""PDF download and full-text extraction using PyMuPDF.

Downloads a PDF from a URL, extracts its text, and caches the
extracted text via the pluggable `PaperCache` from
`src.tools.paper_cache` so repeated calls don't re-download or
re-parse. Returns "" on any failure — callers should treat that as
a graceful signal to fall back (e.g. to the abstract).

The raw PDF is written to `<cache_dir>/<key>.pdf` on the local
filesystem regardless of `PaperCache` backend so a future re-parse
with an updated PyMuPDF doesn't need a re-download. The extracted
text goes through the cache (disk or Postgres per `settings`).

Two ADR-0033 hardenings live here:

- Downloads stream with a `settings.pdf_max_bytes` ceiling so a
  500MB adversarial PDF can't OOM the process.
- `_cache_key` only extracts an arXiv ID when the URL's host is
  under `arxiv.org`; other hosts hash the full URL. Otherwise
  `https://evil.com/2311.09000/attack.pdf` collides with the real
  cache slot for that arXiv ID.

ADR 0041 adds destination validation (SSRF guard): PDF URLs from
non-arXiv hosts — reachable through Semantic Scholar's
attacker-influenceable `openAccessPdf.url` — must be https and must
not resolve to a private, loopback, link-local, or otherwise
non-public address. Redirects are never followed blindly; each hop is
re-validated. arXiv URLs get their scheme upgraded to https before
fetching.

ADR 0068 finally puts the download inside the retry clamp: the
per-attempt timeout is `settings.pdf_download_timeout_sec` rather than
a module constant, and it is declared to `build_retrying_session` as
well as passed to `get`, so `(retries + 1) * timeout` is trimmed
against this dependency's share of the job budget. Note the shape the
clamp does *not* cover: each redirect hop opens its own call chain, so
a chain of redirects still multiplies by `_MAX_REDIRECTS + 1` — which
is why that constant is small and every hop is validated.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import fitz
import requests

from src.config import settings
from src.observability import (
    DEGRADATION_RUNG_CACHE_STALE,
    get_logger,
    record_degradation_rung,
)
from src.observability.semconv import TOOL_PDF_PARSE, TOOL_TYPE_EXTENSION
from src.observability.tracing import traced_tool
from src.tools.http_session import build_retrying_session
from src.tools.paper_cache import DEFAULT_CACHE_DIR, PaperCache, get_paper_cache

# Read-chunk size for the streaming download. 64 KiB matches urllib3's
# default and keeps the size check tight without thrashing on many
# small reads.
_STREAM_CHUNK_BYTES = 64 * 1024

_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5}(?:v\d+)?)")

# Redirect statuses walked manually so every hop's destination gets
# validated — `allow_redirects=True` would happily follow a public
# host's 302 into the cloud metadata endpoint.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5

log = get_logger(__name__)


def _is_arxiv_host(host: str) -> bool:
    """Whether `host` is arxiv.org or a subdomain of it."""
    host = host.lower()
    return host == "arxiv.org" or host.endswith(".arxiv.org")


def _upgrade_arxiv_scheme(pdf_url: str) -> str:
    """Rewrite `http://` to `https://` for arXiv-hosted URLs.

    Both the Atom feed and the Semantic Scholar fallback historically
    emitted plaintext `http://arxiv.org/pdf/...` URLs; fetching those
    over http would let an in-path attacker substitute the PDF body
    that ends up in Claude's prompt (ADR 0033's threat model). arXiv
    serves everything over https, so the upgrade is always safe.
    """
    parsed = urlparse(pdf_url)
    if parsed.scheme == "http" and _is_arxiv_host(parsed.hostname or ""):
        return pdf_url.replace("http://", "https://", 1)
    return pdf_url


def _is_fetchable(url: str) -> bool:
    """SSRF guard: whether `url` is a safe PDF download destination.

    Requires an https scheme for every host. arXiv hosts are trusted
    without a DNS pre-flight (their URLs come from arXiv's own
    TLS-served Atom feed, and skipping the resolve keeps unit tests
    offline). Any other host — reachable via Semantic Scholar's
    attacker-influenceable `openAccessPdf.url` — must resolve, and
    every resolved address must be globally routable: private,
    loopback, link-local, reserved, multicast, and unspecified
    addresses are all rejected, as is a DNS failure.

    A pre-flight resolve is not airtight against DNS rebinding (the
    fetch re-resolves); the residual risk is recorded in ADR 0041.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host:
        log.warning(
            "pdf_url_rejected_scheme",
            extra={"pdf_url": url},
        )
        return False
    if _is_arxiv_host(host):
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        log.warning(
            "pdf_url_rejected_dns",
            extra={"pdf_url": url, "error": str(exc)},
        )
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            log.warning(
                "pdf_url_rejected_bad_address",
                extra={"pdf_url": url, "address": str(info[4][0])},
            )
            return False
        if not addr.is_global:
            log.warning(
                "pdf_url_rejected_non_public",
                extra={"pdf_url": url, "address": str(addr)},
            )
            return False
    return True


def _cache_key(pdf_url: str) -> str:
    """Derive a stable filesystem-safe key for a PDF URL.

    Uses the arXiv ID only when the URL's host is arxiv.org (or a
    subdomain); otherwise falls back to a short SHA1 of the full URL.
    Otherwise a URL like ``https://evil.com/2311.09000/attack.pdf``
    would collide with the real cache slot for that arXiv ID.
    """
    host = (urlparse(pdf_url).hostname or "").lower()
    if host == "arxiv.org" or host.endswith(".arxiv.org"):
        match = _ARXIV_ID.search(pdf_url)
        if match:
            return match.group(1)
    return hashlib.sha1(pdf_url.encode("utf-8")).hexdigest()[:16]


def _download_pdf(pdf_url: str, dest: Path) -> bool:
    """Download a PDF to `dest`. Returns True on success.

    Streams the response body with a ``settings.pdf_max_bytes`` cap
    so a large adversarial PDF can't exhaust memory. Uses a retrying
    session so transient 429s don't drop us into abstract-only mode.
    A hard failure (bad URL, unsafe destination, non-PDF body,
    oversize, extraction throw) returns False and the reader falls
    back gracefully.

    Redirects are walked manually with every hop re-validated through
    `_is_fetchable` — following them blindly would let a public host
    302 the fetcher into an internal address (ADR 0041's SSRF guard).
    """
    # Declared to the session builder as well as passed to `get`, the
    # way `arxiv_search` does it (ADR 0068): urllib3 applies the timeout
    # *per attempt*, so the retry count can only be trimmed by something
    # that knows what one attempt costs. Without the declaration this
    # download was the one remaining call chain with no bound at all —
    # 4 attempts x 60s, per redirect hop, inside a 600s job.
    timeout_sec = settings.pdf_download_timeout_sec
    session = build_retrying_session(timeout_sec=timeout_sec)
    max_bytes = settings.pdf_max_bytes
    url = _upgrade_arxiv_scheme(pdf_url)

    resp: requests.Response | None = None
    for _hop in range(_MAX_REDIRECTS + 1):
        if not _is_fetchable(url):
            return False
        try:
            resp = session.get(
                url,
                timeout=timeout_sec,
                allow_redirects=False,
                stream=True,
            )
        except (requests.RequestException, OSError) as exc:
            log.warning(
                "pdf_download_failed",
                extra={"pdf_url": url, "error": str(exc)},
            )
            return False
        if resp.status_code not in _REDIRECT_STATUSES:
            break
        location = resp.headers.get("Location", "")
        resp.close()
        resp = None
        if not location:
            log.warning(
                "pdf_download_redirect_without_location",
                extra={"pdf_url": url},
            )
            return False
        # Relative Locations resolve against the current hop. The next
        # loop iteration re-validates the destination before fetching.
        url = _upgrade_arxiv_scheme(urljoin(url, location))
    if resp is None:
        log.warning(
            "pdf_download_too_many_redirects",
            extra={"pdf_url": pdf_url, "max_redirects": _MAX_REDIRECTS},
        )
        return False

    with resp:
        if resp.status_code != 200:
            log.warning(
                "pdf_download_http_error",
                extra={"pdf_url": url, "status": resp.status_code},
            )
            return False

        # A well-behaved server sends Content-Length; if it exceeds
        # the cap we can reject before pulling any bytes.
        declared = resp.headers.get("Content-Length")
        if declared is not None:
            try:
                if int(declared) > max_bytes:
                    log.warning(
                        "pdf_download_oversize_declared",
                        extra={
                            "pdf_url": pdf_url,
                            "content_length": int(declared),
                            "max_bytes": max_bytes,
                        },
                    )
                    return False
            except ValueError:
                pass  # Non-integer header — fall through to streaming cap.

        buf = bytearray()
        for chunk in resp.iter_content(chunk_size=_STREAM_CHUNK_BYTES):
            if not chunk:
                continue
            buf.extend(chunk)
            if len(buf) > max_bytes:
                log.warning(
                    "pdf_download_oversize_streamed",
                    extra={
                        "pdf_url": pdf_url,
                        "read_bytes": len(buf),
                        "max_bytes": max_bytes,
                    },
                )
                return False

    if not bytes(buf[:5]).startswith(b"%PDF-"):
        log.warning(
            "pdf_download_not_a_pdf",
            extra={"pdf_url": pdf_url},
        )
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(buf))
    return True


def _extract_text(pdf_path: Path) -> str:
    """Extract concatenated page text from a local PDF file."""
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc)


@traced_tool(TOOL_PDF_PARSE, tool_type=TOOL_TYPE_EXTENSION)
def parse_pdf(
    pdf_url: str,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
    cache: PaperCache | None = None,
) -> str:
    """Fetch, cache, and extract text from a PDF at `pdf_url`.

    Extracted text is stored in the `PaperCache` from
    `settings.paper_cache` (`disk` = `<cache_dir>/<key>.txt`,
    `postgres` = `paper_cache` table). The raw PDF is always
    written to `<cache_dir>/<key>.pdf` so a re-parse with an updated
    PyMuPDF doesn't need a re-download.

    Args:
        pdf_url: HTTP(S) URL of the PDF to fetch.
        cache_dir: Filesystem directory for the raw PDF bytes.
        cache: Injectable `PaperCache` for tests. Defaults to
            `get_paper_cache()` — the settings-driven singleton.

    Returns:
        The extracted text, or "" if download or extraction failed.
    """
    if not pdf_url:
        return ""

    cache = cache if cache is not None else get_paper_cache()
    cache_dir = Path(cache_dir)
    key = _cache_key(pdf_url)
    pdf_path = cache_dir / f"{key}.pdf"

    # The cache is an optimization, never a dependency: a read failure
    # (pool timeout, Postgres restart) is treated as a miss and logged,
    # mirroring the write-path guard below. Otherwise an optional cache
    # becomes a hard job-killer, contradicting ADR 0028's degrade-to-
    # recompute consequence (ADR 0041).
    cached_text: str | None = None
    try:
        cached_text = cache.get_text(key)
    except Exception as exc:
        log.warning(
            "paper_cache_get_failed",
            extra={"paper_key": key, "error": str(exc)},
        )
        # Rung 1 of the degradation ladder. The job survives — that is
        # the whole point of the guard above — and it is exactly that
        # survival which used to make this invisible: nothing failed, so
        # nothing counted, while every paper on the fleet was being
        # refetched and re-extracted (docs/reliability.md §5, ADR 0081).
        record_degradation_rung(
            rung=DEGRADATION_RUNG_CACHE_STALE, component="paper_cache"
        )
    if cached_text is not None:
        return cached_text

    if not pdf_path.exists() and not _download_pdf(pdf_url, pdf_path):
        return ""

    try:
        text = _extract_text(pdf_path)
    except (RuntimeError, OSError, ValueError) as exc:
        log.warning(
            "pdf_extraction_failed",
            extra={"pdf_path": str(pdf_path), "error": str(exc)},
        )
        return ""

    try:
        cache.put_text(key, pdf_url, text)
    except Exception as exc:
        # Cache write failures should not lose an extracted document —
        # callers get the text back and the next hit re-extracts.
        log.warning(
            "paper_cache_put_failed",
            extra={"paper_key": key, "error": str(exc)},
        )
    return text
