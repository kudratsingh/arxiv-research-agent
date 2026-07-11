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
"""

import hashlib
import re
from pathlib import Path

import fitz
import requests

from src.observability import get_logger
from src.tools.http_session import build_retrying_session
from src.tools.paper_cache import DEFAULT_CACHE_DIR, PaperCache, get_paper_cache

DOWNLOAD_TIMEOUT_SEC = 60

log = get_logger(__name__)


def _cache_key(pdf_url: str) -> str:
    """Derive a stable filesystem-safe key for a PDF URL.

    Prefers the arXiv ID embedded in the URL (e.g. "2311.09000" or
    "2311.09000v2"); falls back to a short SHA1 for non-arXiv URLs.
    """
    match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", pdf_url)
    if match:
        return match.group(1)
    return hashlib.sha1(pdf_url.encode("utf-8")).hexdigest()[:16]


def _download_pdf(pdf_url: str, dest: Path) -> bool:
    """Download a PDF to `dest`. Returns True on success.

    Uses a retrying session so transient 429s from arXiv's PDF host
    don't drop us into abstract-only mode. A hard failure (bad URL,
    non-PDF body, extraction throw) still returns False and the reader
    falls back gracefully.
    """
    session = build_retrying_session()
    try:
        resp = session.get(
            pdf_url, timeout=DOWNLOAD_TIMEOUT_SEC, allow_redirects=True
        )
    except (requests.RequestException, OSError) as exc:
        log.warning(
            "pdf_download_failed",
            extra={"pdf_url": pdf_url, "error": str(exc)},
        )
        return False

    if resp.status_code != 200:
        log.warning(
            "pdf_download_http_error",
            extra={"pdf_url": pdf_url, "status": resp.status_code},
        )
        return False

    if not resp.content.startswith(b"%PDF-"):
        log.warning(
            "pdf_download_not_a_pdf",
            extra={"pdf_url": pdf_url},
        )
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return True


def _extract_text(pdf_path: Path) -> str:
    """Extract concatenated page text from a local PDF file."""
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc)


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

    cached_text = cache.get_text(key)
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
