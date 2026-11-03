"""Two explicitly selected public PDF samples, never a general full-text crawler.

Primary metadata/license checks: 2026-11-02 official arXiv abstract pages for
2210.03629v3 (ReAct) and 2310.11511v1 (Self-RAG), both linked CC BY 4.0.
A retrieval issues one GET only: redirects/retries are refused, so qualifying
both registered samples requires at most two PDF GETs and sixteen MiB.

Metadata feeds/abstracts remain independent. Failure yields no replacement
material; the caller retains the original abstract and records this receipt.
Parser output is not proof of equation/table fidelity or an exhaustive read.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import urllib3

from src.workspace.intake import IntakeError, _public_addresses, _rate_slot
from src.workspace.material import MAX_PDF_BYTES, MaterialError, SourceMaterial, extract_pdf


@dataclass(frozen=True)
class PdfSpec:
    arxiv_version: str
    title: str
    authors: tuple[str, ...]
    work_id: str
    version_id: str
    abs_url: str
    pdf_url: str
    license_url: str = "https://creativecommons.org/licenses/by/4.0/"
    rights_basis: str = (
        "CC BY 4.0 linked from the official arXiv abstract page; local attributed source retention"
    )


SAMPLES = {
    "2210.03629v3": PdfSpec(
        "2210.03629v3",
        "ReAct: Synergizing Reasoning and Acting in Language Models",
        (
            "Shunyu Yao",
            "Jeffrey Zhao",
            "Dian Yu",
            "Nan Du",
            "Izhak Shafran",
            "Karthik Narasimhan",
            "Yuan Cao",
        ),
        "arxiv:2210.03629",
        "arxiv:2210.03629:v3",
        "https://arxiv.org/abs/2210.03629v3",
        "https://arxiv.org/pdf/2210.03629v3",
    ),
    "2310.11511v1": PdfSpec(
        "2310.11511v1",
        "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
        ("Akari Asai", "Zeqiu Wu", "Yizhong Wang", "Avirup Sil", "Hannaneh Hajishirzi"),
        "arxiv:2310.11511",
        "arxiv:2310.11511:v1",
        "https://arxiv.org/abs/2310.11511v1",
        "https://arxiv.org/pdf/2310.11511v1",
    ),
}
MAX_BATCH_BYTES = 2 * MAX_PDF_BYTES


@dataclass(frozen=True)
class PdfResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str


@dataclass(frozen=True)
class FulltextResult:
    material: SourceMaterial | None
    receipt: dict[str, Any]
    raw_pdf: bytes | None = None


PdfTransport = Callable[[str], PdfResponse]


def sample_spec(version: str) -> PdfSpec:
    for spec in SAMPLES.values():
        if version in {spec.arxiv_version, spec.version_id}:
            return spec
    raise MaterialError("fulltext_sample_not_allowed")


def _fetch(url: str) -> PdfResponse:
    if url not in {spec.pdf_url for spec in SAMPLES.values()}:
        raise MaterialError("fulltext_url_not_allowed")
    host = "arxiv.org"
    address = _public_addresses(host)[0]
    pool = urllib3.HTTPSConnectionPool(
        address,
        port=443,
        server_hostname=host,
        assert_hostname=host,
        cert_reqs="CERT_REQUIRED",
        maxsize=1,
        timeout=urllib3.Timeout(connect=5, read=15),
    )
    started = time.monotonic()
    try:
        with _rate_slot(host):
            response = pool.urlopen(
                "GET",
                urlsplit(url).path,
                headers={
                    "Host": host,
                    "Accept": "application/pdf",
                    "Accept-Encoding": "identity",
                    "User-Agent": "PersonalResearchWorkspace/0.1 (two selected public PDF samples)",
                },
                redirect=False,
                retries=False,
                preload_content=False,
            )
            try:
                headers = {key.lower(): value for key, value in response.headers.items()}
                if response.status != 200:
                    return PdfResponse(response.status, headers, b"", url)
                if headers.get("content-encoding", "identity").lower() not in {"identity", ""}:
                    raise MaterialError("unsupported_content_encoding")
                length = headers.get("content-length")
                if length is not None and (
                    not length.isdigit() or len(length) > 10 or int(length) > MAX_PDF_BYTES
                ):
                    raise MaterialError("pdf_too_large")
                parts: list[bytes] = []
                size = 0
                while True:
                    if time.monotonic() - started > 30:
                        raise MaterialError("pdf_fetch_deadline")
                    chunk = response.read(
                        min(65536, MAX_PDF_BYTES + 1 - size), decode_content=False
                    )
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_PDF_BYTES:
                        raise MaterialError("pdf_too_large")
                    parts.append(chunk)
                return PdfResponse(response.status, headers, b"".join(parts), url)
            finally:
                response.close()
    finally:
        pool.close()


def acquire_sample(
    version: str,
    *,
    page_numbers: Sequence[int] | None = None,
    transport: PdfTransport | None = None,
    now: datetime | None = None,
) -> FulltextResult:
    """Fetch one pinned sample and retain bounded original-page text, without LLMs.

    Do not call again automatically after a failed/429 check; this deliberately
    has no retry chain. ``receipt`` preserves Retry-After verbatim for the
    operator. Only an explicit bounded sample acquisition invokes this helper.
    """
    spec = sample_spec(version)
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        raise MaterialError("timezone_required")
    receipt: dict[str, Any] = {
        "status": "unavailable",
        "sample": asdict(spec),
        "requested_url": spec.pdf_url,
        "fetched_at": observed.astimezone(UTC).isoformat(),
        "request_count": 0,
        "bytes": 0,
        "requested_pages": list(page_numbers) if page_numbers is not None else None,
        "max_bytes": MAX_PDF_BYTES,
        "max_pages": 12,
        "max_chars": 120000,
        "limitations": [
            "Two registered PDF samples only; no crawl, retries, redirects, scripts, code or model execution.",
            "Equations/tables/reading order require visual review; no OCR.",
            "Abstract fallback is retained independently; this result never replaces it on failure.",
        ],
    }
    raw_pdf: bytes | None = None
    try:
        # Reject an invalid selection before opening a network transport.
        if page_numbers is not None and (
            not 1 <= len(page_numbers) <= 12
            or any(type(page) is not int or page < 1 for page in page_numbers)
            or list(page_numbers) != sorted(set(page_numbers))
        ):
            raise MaterialError("invalid_page_selection")
        receipt["request_count"] = 1
        response = (transport or _fetch)(spec.pdf_url)
        receipt.update(http_status=response.status, resolved_url=response.url)
        headers = {key.lower(): value for key, value in response.headers.items()}
        receipt["retry_after"] = headers.get("retry-after")
        if response.url != spec.pdf_url:
            raise MaterialError("fulltext_source_version_drift")
        if response.status != 200:
            raise MaterialError(
                "pdf_redirect_refused"
                if 300 <= response.status < 400
                else f"pdf_http_{response.status}"
            )
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/pdf":
            raise MaterialError("unexpected_pdf_content_type")
        if len(response.body) > MAX_PDF_BYTES:
            raise MaterialError("pdf_too_large")
        if not response.body.startswith(b"%PDF-"):
            raise MaterialError("invalid_pdf")
        raw_pdf = response.body
        receipt.update(
            bytes=len(raw_pdf), source_hash="sha256:" + hashlib.sha256(raw_pdf).hexdigest()
        )
        material = extract_pdf(
            raw_pdf, work_id=spec.work_id, version_id=spec.version_id, page_numbers=page_numbers
        )
        receipt.update(
            status="extracted",
            material_id=material.material_id,
            parser_revision=material.parser_revision,
            source_scope=material.scope,
            quality=material.quality,
            complete=material.complete,
            page_count=material.page_count,
            retained_pages=list(material.page_numbers)
            if material.page_numbers is not None
            else list(range(1, len(material.pages) + 1)),
            retained_characters=sum(len(page) for page in material.pages),
            warnings=list(material.warnings),
            quality_exclusions=[
                "equation_semantics",
                "table_cell_structure",
                "diagram_content",
                "unretained_pages" if not material.complete else "unreviewed_layout",
            ],
            visual_review="pending; extraction length is not layout qualification",
        )
        return FulltextResult(material, receipt, raw_pdf)
    except (MaterialError, IntakeError, OSError, urllib3.exceptions.HTTPError) as exc:
        receipt["error"] = (
            str(exc) if isinstance(exc, MaterialError | IntakeError) else "pdf_source_unavailable"
        )
        return FulltextResult(None, receipt, raw_pdf)


def acquire_samples(
    versions: Sequence[str], *, transport: PdfTransport | None = None, now: datetime | None = None
) -> list[FulltextResult]:
    """One bounded qualification batch, max two distinct pinned PDF GETs."""
    specs = [sample_spec(version) for version in versions]
    if not 1 <= len(specs) <= 2 or len({spec.version_id for spec in specs}) != len(specs):
        raise MaterialError("invalid_fulltext_batch")
    return [acquire_sample(spec.arxiv_version, transport=transport, now=now) for spec in specs]
