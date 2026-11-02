"""Bounded, read-only metadata adapters for the personal workspace.

These feeds are observations, not a complete archive. RSS cannot substantiate a
seven-day coverage window: receipts record the requested window separately from
what the returned feed actually contained. Persistence owns the commit/watermark;
no adapter changes a cursor or stores a note. No article, PDF or model is fetched.

Provider rules rechecked 2026-11-02:
https://info.arxiv.org/help/api/tou.html (one connection, >=3s between requests)
https://info.arxiv.org/help/rss_specifications.html (pubDate is announcement date)
https://huggingface.co/robots.txt and the publisher-provided feed endpoints.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import ipaddress
import json
import re
import socket
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree.ElementTree import Element, ParseError

import urllib3
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 25
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 15.0
ADAPTER_VERSION = "workspace-feed-v2"
USER_AGENT = "PersonalResearchWorkspace/0.1 (bounded metadata reader; local use)"
ARXIV_ID = re.compile(
    r"(?<![\w.])(?P<id>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}))(?P<version>v\d+)?(?![\w.])",
    re.I,
)
DOI = re.compile(r"^10\.\d{4,9}/\S+$", re.I)


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    kind: str
    tags: tuple[str, ...]


SOURCES = {
    "arxiv-cs-lg": Source(
        "arxiv-cs-lg",
        "arXiv Machine Learning",
        "https://rss.arxiv.org/rss/cs.LG",
        "paper",
        ("machine learning",),
    ),
    "arxiv-cs-ai": Source(
        "arxiv-cs-ai",
        "arXiv Artificial Intelligence",
        "https://rss.arxiv.org/rss/cs.AI",
        "paper",
        ("artificial intelligence",),
    ),
    "arxiv-cs-cl": Source(
        "arxiv-cs-cl",
        "arXiv Computation and Language",
        "https://rss.arxiv.org/rss/cs.CL",
        "paper",
        ("language models", "natural language processing"),
    ),
    "hugging-face-blog": Source(
        "hugging-face-blog",
        "Hugging Face Blog",
        "https://huggingface.co/blog/feed.xml",
        "official_blog",
        ("models", "datasets", "tooling"),
    ),
    "google-research": Source(
        "google-research",
        "Google Research Blog",
        "https://research.google/blog/rss/",
        "official_blog",
        ("machine learning", "science", "systems"),
    ),
}
ALLOWED_FETCH_HOSTS = frozenset(urlsplit(s.url).hostname for s in SOURCES.values())


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str
    request_count: int = 1


@dataclass(frozen=True)
class FetchResult:
    items: list[dict[str, Any]]
    receipt: dict[str, Any]
    validators: dict[str, str]


Transport = Callable[[str, dict[str, str]], HttpResponse]


class IntakeError(ValueError):
    """Stable safe refusal; callers record the reason without private payloads."""

    def __init__(self, reason: str, *, request_count: int | None = None) -> None:
        super().__init__(reason)
        self.request_count = request_count


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "iframe", "object"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "iframe", "object"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def plain_text(raw: str, limit: int = 24000) -> str:
    """Discard markup and active element contents; render as text, never HTML."""
    parser = _PlainText()
    parser.feed(raw[:100000])
    return " ".join("".join(parser.parts).split())[:limit]


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _aware_now(now: datetime | None) -> datetime:
    result = now or datetime.now(UTC)
    if result.tzinfo is None:
        raise IntakeError("timezone_required")
    return result.astimezone(UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_url(value: str) -> str:
    """Canonical link identity; unsafe schemes, credentials and local hosts fail."""
    if len(value) > 4096 or any(ord(c) < 32 for c in value) or "\\" in value:
        raise IntakeError("unsafe_url")
    try:
        parts = urlsplit(value.strip())
        host = (parts.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parts.port
    except (ValueError, UnicodeError) as exc:
        raise IntakeError("unsafe_url") from exc
    if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
        raise IntakeError("unsafe_url")
    if (
        port not in {None, 80, 443}
        or host in {"localhost", "localhost.localdomain"}
        or "." not in host
        or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
    ):
        raise IntakeError("unsafe_url")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise IntakeError("unsafe_address")
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
        )
    )
    # Scheme upgrades are limited to known TLS endpoints, rather than pretending
    # an arbitrary HTTP-only site serves HTTPS.
    scheme = "https" if host in {"arxiv.org", "www.arxiv.org", "doi.org"} else parts.scheme
    default_port = 443 if scheme == "https" else 80
    netloc = host if port in {None, default_port} else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", query, ""))


def _public_addresses(host: str) -> list[str]:
    addresses = sorted(
        {str(info[4][0]) for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    )
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise IntakeError("unsafe_dns_address")
    return addresses


def validate_fetch_url(value: str) -> tuple[str, str]:
    url = normalize_url(value)
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or parts.port not in {None, 443} or host not in ALLOWED_FETCH_HOSTS:
        raise IntakeError("source_not_allowed")
    return url, host


@contextlib.contextmanager
def _rate_slot(host: str) -> Iterator[None]:
    """Cross-process local governor, held through the response to serialize arXiv.

    The same local file covers all three arXiv feeds. It is intentionally not a
    DB row lock; network calls never hold a workspace transaction. The existing
    research tool's independent API path is not invoked by this metadata worker.
    """
    group = "arxiv" if host.endswith("arxiv.org") else host
    path = Path(tempfile.gettempdir()) / f"arxiv-workspace-rate-{group}.lock"
    with path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            lock.seek(0)
            raw = lock.read().strip()
            previous = float(raw) if raw else 0.0
            interval = 3.1 if group == "arxiv" else 1.0
            time.sleep(max(0.0, min(interval, previous + interval - time.time())))
            lock.seek(0)
            lock.truncate()
            lock.write(str(time.time()))
            lock.flush()
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _request(url: str, headers: dict[str, str]) -> HttpResponse:
    """Pinned-public-IP TLS fetch; validate every redirect and reject rebinding.

    urllib3 connects to the vetted IP with the original SNI/certificate hostname
    and Host header. No environment proxy or second DNS resolution bypasses the
    policy. Automatic redirect/retry/decompression are disabled and counted.
    """
    started = time.monotonic()
    origin_host = urlsplit(url).hostname
    for hop in range(MAX_REDIRECTS + 1):
        try:
            url, host = validate_fetch_url(url)
            if host != origin_host:
                raise IntakeError("source_redirect_host_mismatch")
            address = _public_addresses(host)[0]
        except (IntakeError, OSError) as exc:
            reason = str(exc) if isinstance(exc, IntakeError) else "source_unavailable"
            raise IntakeError(reason, request_count=hop) from exc
        pool = urllib3.HTTPSConnectionPool(
            address,
            port=443,
            server_hostname=host,
            assert_hostname=host,
            cert_reqs="CERT_REQUIRED",
            timeout=urllib3.Timeout(connect=5.0, read=TIMEOUT_SECONDS),
            maxsize=1,
        )
        parts = urlsplit(url)
        target = urlunsplit(("", "", parts.path, parts.query, ""))
        try:
            with _rate_slot(host):
                response = pool.urlopen(
                    "GET",
                    target,
                    headers={**headers, "Host": host, "Accept-Encoding": "identity"},
                    redirect=False,
                    retries=False,
                    preload_content=False,
                    timeout=urllib3.Timeout(connect=5.0, read=TIMEOUT_SECONDS),
                )
                try:
                    response_headers = {k.lower(): v for k, v in response.headers.items()}
                    if response.status in {301, 302, 303, 307, 308}:
                        if hop == MAX_REDIRECTS:
                            raise IntakeError("redirect_limit")
                        url = urljoin(url, response_headers.get("location", ""))
                        if not response_headers.get("location"):
                            raise IntakeError("redirect_missing_location")
                        continue
                    if response_headers.get("content-encoding", "identity").lower() not in {
                        "identity",
                        "",
                    }:
                        raise IntakeError("unsupported_content_encoding")
                    length = response_headers.get("content-length")
                    if length is not None and (not length.isdigit() or int(length) > MAX_BYTES):
                        raise IntakeError("response_too_large")
                    chunks: list[bytes] = []
                    size = 0
                    while True:
                        if time.monotonic() - started > 30:
                            raise IntakeError("response_deadline")
                        chunk = response.read(
                            min(65536, MAX_BYTES + 1 - size), decode_content=False
                        )
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise IntakeError("response_too_large")
                        chunks.append(chunk)
                    return HttpResponse(
                        response.status, response_headers, b"".join(chunks), url, hop + 1
                    )
                finally:
                    response.close()
        except (IntakeError, OSError, urllib3.exceptions.HTTPError) as exc:
            reason = str(exc) if isinstance(exc, IntakeError) else "source_unavailable"
            raise IntakeError(reason, request_count=hop + 1) from exc
        finally:
            pool.close()
    raise IntakeError("redirect_limit")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(element: Element, *names: str) -> str:
    for child in element:
        if _local(child.tag) in names:
            return "".join(child.itertext()).strip()
    return ""


def _date(raw: str) -> tuple[str | None, str | None]:
    if not raw:
        return None, None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        precision = "date" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else "second"
        # RSS RFC-822 timestamps carry an explicit timezone. Date-only values
        # are a date at UTC midnight with precision=date, never a known instant.
        if value.tzinfo is None:
            if precision != "date":
                return None, None
            value = value.replace(tzinfo=UTC)
    except ValueError:
        try:
            value = parsedate_to_datetime(raw)
            precision = "second"
            if value.tzinfo is None:
                return None, None
        except (ValueError, TypeError, OverflowError):
            return None, None
    return _stamp(value), precision


def _identity(url: str, raw_id: str = "", description: str = "") -> tuple[str, str, str]:
    if urlsplit(url).hostname in {"arxiv.org", "www.arxiv.org"}:
        match = ARXIV_ID.search(raw_id) or ARXIV_ID.search(description) or ARXIV_ID.search(url)
        if not match:
            raise IntakeError("missing_arxiv_identifier")
        base = match.group("id").lower()
        version = (match.group("version") or "").lower()
        work = f"arxiv:{base}"
        return work, version or "unversioned", f"https://arxiv.org/abs/{base}{version or ''}"
    if urlsplit(url).hostname in {"doi.org", "dx.doi.org"}:
        doi = urlsplit(url).path.lstrip("/").lower()
        if DOI.fullmatch(doi):
            return f"doi:{doi}", "unversioned", f"https://doi.org/{doi}"
    return f"url:{_hash(url)[:32]}", "observed", url


def _entry(element: Element, source: Source, now: datetime) -> dict[str, Any] | None:
    title = plain_text(_child(element, "title"), 500)
    url = _child(element, "link")
    if not url:
        for child in element:
            if _local(child.tag) == "link" and child.get("rel", "alternate") == "alternate":
                url = child.get("href", "")
                break
    if not title or not url:
        return None
    try:
        url = normalize_url(urljoin(source.url, url))
    except IntakeError:
        return None
    host = urlsplit(url).hostname
    expected = (
        {"arxiv.org", "www.arxiv.org"}
        if source.id.startswith("arxiv-")
        else {urlsplit(source.url).hostname}
    )
    if host not in expected:
        return None
    raw_id = _child(element, "guid", "id") or url
    description = plain_text(_child(element, "description", "summary", "encoded"))
    try:
        work, version, url = _identity(url, raw_id, description)
    except IntakeError:
        return None
    abstract = description
    announce = _child(element, "announce_type")
    if source.id.startswith("arxiv-"):
        if not announce:
            announced_match = re.search(r"Announce Type:\s*([\w-]+)", description)
            announce = announced_match.group(1) if announced_match else ""
        abstract = re.sub(r"^.*?\bAbstract:\s*", "", description, count=1)
    published_raw = _child(element, "published")
    rss_date = _child(element, "pubdate", "date")
    # arXiv RSS pubDate is the update announcement, not original publication.
    published, published_precision = _date(
        published_raw
        or (rss_date if not source.id.startswith("arxiv-") else "")
    )
    updated, updated_precision = _date(_child(element, "updated"))
    announced, _ = _date(rss_date) if source.id.startswith("arxiv-") else (None, None)
    authors: list[str] = []
    categories: list[str] = []
    aliases: list[str] = []
    for child in element:
        tag = _local(child.tag)
        if tag in {"creator", "author"}:
            author = _child(child, "name") or "".join(child.itertext())
            authors.extend(a.strip() for a in plain_text(author, 2000).split(",") if a.strip())
        elif tag == "category":
            category = plain_text(child.get("term", "") or (child.text or ""), 200)
            if category:
                categories.append(category)
        elif tag == "doi" and child.text and DOI.fullmatch(child.text.strip()):
            aliases.append(f"doi:{child.text.strip().lower()}")
    material = {
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "published_at": published,
        "updated_at": updated,
    }
    digest = _hash(json.dumps(material, sort_keys=True))
    # Unversioned feeds are observed revisions; do not relabel them v1. arXiv's
    # explicit vN is immutable; same-version metadata correction remains visible
    # in observations without silently moving annotations to another version.
    version_id = (
        f"{work}:{version}" if version.startswith("v") else f"{work}:observed-{digest[:16]}"
    )
    return {
        "work_id": work,
        "version_id": version_id,
        "source_id": source.id,
        "source_record_id": raw_id[:4096],
        "title": title,
        "url": url,
        "authors": authors[:100],
        "abstract": abstract[:24000],
        "access_state": "abstract"
        if source.kind == "paper" and abstract
        else "excerpt"
        if abstract
        else "metadata",
        "categories": categories[:50],
        "published_at": published,
        "updated_at": updated,
        "published_precision": published_precision or "unknown",
        "updated_precision": updated_precision or "unknown",
        "announced_at": announced,
        "announce_type": announce or None,
        "first_seen_at": _stamp(now),
        "fetched_at": _stamp(now),
        "content_hash": digest,
        "version_label": version if version.startswith("v") else f"observed {digest[:8]}",
        "kind": source.kind,
        "aliases": aliases,
        "adapter_version": ADAPTER_VERSION,
        "source_scope": "abstract"
        if source.kind == "paper" and abstract
        else "excerpt"
        if abstract
        else "metadata",
    }


def parse_feed(data: bytes, source_id: str, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Parse a bounded RSS/Atom document, preserving unknown dates and versions."""
    source = SOURCES[source_id]
    observed = _aware_now(now)
    if len(data) > MAX_BYTES:
        raise IntakeError("response_too_large")
    try:
        root = ET.fromstring(data)
    except (ParseError, DefusedXmlException) as exc:
        raise IntakeError("invalid_feed") from exc
    if _local(root.tag) not in {"rss", "rdf", "feed"}:
        raise IntakeError("invalid_feed_root")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in root.iter():
        if _local(element.tag) not in {"item", "entry"}:
            continue
        item = _entry(element, source, observed)
        if item and item["version_id"] not in seen:
            seen.add(item["version_id"])
            result.append(item)
    return result


def _retry_after(raw: str | None, now: datetime) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if re.fullmatch(r"[0-9]+", raw):
        # Recording a delay does not sleep a worker, so a valid provider delay
        # must never be shortened. Compare decimal strings before converting:
        # an absurd upstream integer can exceed Python's int parsing limit or
        # datetime's horizon, and neither may turn into an early retry.
        seconds = raw.lstrip("0") or "0"
        remaining = datetime.max.replace(tzinfo=UTC) - now
        maximum = str(remaining.days * 86400 + remaining.seconds)
        if len(seconds) > len(maximum) or (len(seconds) == len(maximum) and seconds > maximum):
            raise IntakeError("retry_after_unrepresentable")
        return _stamp(now + timedelta(seconds=int(seconds)))
    date, _ = _date(raw)
    return date


def fetch_source(
    source_id: str,
    validators: Mapping[str, str] | None = None,
    *,
    now: datetime | None = None,
    max_items: int = MAX_ITEMS,
    lookback_days: int = 7,
    transport: Transport | None = None,
) -> FetchResult:
    """One bounded feed check; no retries or watermark advancement on failure.

    Conditional validators are returned only after a fully parsed response. The
    caller commits returned observations and validators atomically. A truncated
    result withholds validators so a retry cannot skip the uncommitted remainder.
    RSS is a current-feed view: successful_window is the observed date extent,
    never an unsupported claim that all requested days were fetched.
    """
    source = SOURCES[source_id]
    observed = _aware_now(now)
    if not 1 <= max_items <= MAX_ITEMS or not 1 <= lookback_days <= 31:
        raise IntakeError("invalid_fetch_bounds")
    start = observed - timedelta(days=lookback_days)
    prior = dict(validators or {})
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
    }
    for key, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
        value = prior.get(key)
        if value:
            if len(value) > 1024 or "\r" in value or "\n" in value:
                raise IntakeError("invalid_validator")
            headers[header] = value
    receipt: dict[str, Any] = {
        "source_id": source_id,
        "adapter_version": ADAPTER_VERSION,
        "endpoint": source.url,
        "fetched_at": _stamp(observed),
        "requested_window": {"start": _stamp(start), "end": _stamp(observed)},
        "successful_window": None,
        "status": "failed",
        "request_count": 0,
        "item_count": 0,
        "truncated": False,
        "retry_after": None,
        "limitations": [
            "Current feed only; not a complete archive or guaranteed seven-day coverage.",
            "At most 25 items; no article body or PDF fetch; publication dates may be unknown.",
            "Late arrivals are reconsidered within the bounded lookback on each check; no backfill cursor is asserted.",
        ],
    }
    try:
        receipt["request_count"] = 1
        response = (transport or _request)(source.url, headers)
        receipt.update(
            http_status=response.status,
            resolved_url=response.url,
            request_count=response.request_count,
        )
        _, resolved_host = validate_fetch_url(response.url)
        if resolved_host != urlsplit(source.url).hostname:
            raise IntakeError("source_redirect_host_mismatch")
        lower_headers = {k.lower(): v for k, v in response.headers.items()}
        receipt["retry_after"] = _retry_after(lower_headers.get("retry-after"), observed)
        if response.status == 304:
            if not prior:
                raise IntakeError("unexpected_not_modified")
            receipt["status"] = "not_modified"
            receipt["limitations"].append(
                "304 confirms unchanged feed bytes, not a historical coverage window."
            )
            return FetchResult([], receipt, prior)
        if response.status == 429:
            receipt["status"] = "rate_limited"
            receipt["error"] = "source_rate_limited"
            return FetchResult([], receipt, prior)
        if response.status != 200:
            raise IntakeError(f"http_{response.status}")
        content_type = lower_headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and content_type not in {
            "application/rss+xml",
            "application/atom+xml",
            "application/xml",
            "text/xml",
            "text/plain",
        }:
            raise IntakeError("unexpected_content_type")
        items = parse_feed(response.body, source_id, now=observed)
        # Unknown event dates stay inspectable. For delayed indexing, consider
        # last update/announcement before publication; first-seen is never
        # substituted for the event date or used to silently drop an old item.
        candidates = [
            item
            for item in items
            if (item["updated_at"] or item["announced_at"] or item["published_at"]) is None
            or (item["updated_at"] or item["announced_at"] or item["published_at"]) >= _stamp(start)
        ]
        truncated = len(candidates) > max_items
        selected = candidates[:max_items]
        dates = sorted(
            item["updated_at"] or item["announced_at"] or item["published_at"]
            for item in selected
            if item["updated_at"] or item["announced_at"] or item["published_at"]
        )
        receipt.update(
            status="partial" if truncated else "success",
            item_count=len(selected),
            parsed_count=len(items),
            eligible_count=len(candidates),
            truncated=truncated,
            source_record_ids=[item["source_record_id"] for item in selected],
            bytes_read=len(response.body),
            response_hash=hashlib.sha256(response.body).hexdigest(),
        )
        if dates and not truncated:
            receipt["successful_window"] = {
                "start": dates[0],
                "end": dates[-1],
                "basis": "returned_item_dates_only",
            }
        next_validators = (
            prior
            if truncated
            else {
                k: lower_headers[h]
                for k, h in (("etag", "etag"), ("last_modified", "last-modified"))
                if lower_headers.get(h)
            }
        )
        return FetchResult(selected, receipt, next_validators)
    except (IntakeError, OSError, urllib3.exceptions.HTTPError) as exc:
        receipt["error"] = str(exc) if isinstance(exc, IntakeError) else "source_unavailable"
        if receipt["error"] == "retry_after_unrepresentable":
            # No representable retry instant exists. Keep this connector off
            # the automatic path until an operator reviews it; substituting a
            # smaller delta or ignoring the header would retry too early.
            receipt["status"] = "quarantined"
            receipt["quarantined"] = True
            receipt["retry_after"] = _stamp(datetime.max.replace(tzinfo=UTC))
            receipt["limitations"].append(
                "Retry-After exceeds the supported clock horizon; connector quarantined pending operator review."
            )
        if isinstance(exc, IntakeError) and exc.request_count is not None:
            receipt["request_count"] = exc.request_count
        return FetchResult([], receipt, prior)


def normalize_manual(value: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Validate an identifier/link without fetching arbitrary remote content.

    Unsupported hosts remain a link-only item. DOI identity is case-normalized;
    no title similarity merge or paywall/full-text request is attempted.
    """
    observed = _aware_now(now)
    raw = value.strip()
    if raw.lower().startswith("arxiv:"):
        raw = raw[6:]
    match = ARXIV_ID.fullmatch(raw)
    if match:
        raw = f"https://arxiv.org/abs/{raw}"
    elif DOI.fullmatch(raw):
        raw = f"https://doi.org/{raw}"
    url = normalize_url(raw)
    work, version, url = _identity(url)
    digest = _hash(url)
    return {
        "work_id": work,
        "version_id": f"{work}:{version}"
        if version.startswith("v")
        else f"{work}:link-{digest[:16]}",
        "source_id": "manual",
        "source_record_id": url,
        "title": url,
        "url": url,
        "authors": [],
        "abstract": "",
        "access_state": "metadata",
        "source_scope": "metadata",
        "categories": [],
        "published_at": None,
        "updated_at": None,
        "published_precision": "unknown",
        "updated_precision": "unknown",
        "first_seen_at": _stamp(observed),
        "fetched_at": _stamp(observed),
        "content_hash": digest,
        "version_label": version,
        "kind": "link",
        "aliases": [],
        "adapter_version": ADAPTER_VERSION,
        "limitations": ["Link-only manual import; no remote content or metadata fetched."],
    }
