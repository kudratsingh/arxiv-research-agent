"""Immutable retained material and spans, independent of generation/policy flags.

PDF acquisition is deliberately absent: callers supply small permitted local
bytes, after rights/source/version checks. This uses the same PyMuPDF engine as
``src.tools.pdf_parser`` but preserves pages and exact extracted-text offsets.
Unlike that download/cache wrapper it opens no URL and imports no HTTP client.

PDF parsing runs in a child with a wall/CPU limit. The Linux child also has an
address-space ceiling; macOS output/byte/page bounds are not a memory sandbox.
Offsets address the retained extracted text, not original PDF bytes, equation
semantics or a guaranteed reading order. PDF sections remain unknown.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_PAGES = 12
MAX_CHARS = 120_000
MAX_SPAN_CHARS = 2000
PDF_WALL_SECONDS = 20
TEXT_PARSER_REVISION = "workspace-plain-text-v1"
Scope = Literal["metadata", "abstract", "excerpt", "full_text"]


class MaterialError(ValueError):
    """Stable extraction refusal, never a successful empty reading record."""


@dataclass(frozen=True)
class SourceSpan:
    span_id: str
    work_id: str
    version_id: str
    material_id: str
    source_hash: str
    scope: Scope
    parser_revision: str
    page: int | None
    section: str | None
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class SourceMaterial:
    material_id: str
    work_id: str
    version_id: str
    source_hash: str
    content_hash: str
    scope: Scope
    parser_revision: str
    quality: str
    warnings: tuple[str, ...]
    complete: bool
    page_count: int | None
    pages: tuple[str, ...]
    spans: tuple[SourceSpan, ...]
    offset_basis: str = "page-local Unicode code points; end exclusive"


def _hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _identity(work_id: str, version_id: str) -> None:
    if not work_id.strip() or not version_id.strip() or len(work_id) > 300 or len(version_id) > 300:
        raise MaterialError("source_version_required")


def _build(
    *,
    work_id: str,
    version_id: str,
    source_hash: str,
    scope: Scope,
    parser_revision: str,
    pages: list[str],
    page_count: int | None,
    quality: str,
    warnings: list[str],
    complete: bool,
    section: str | None = None,
) -> SourceMaterial:
    content_hash = _hash(json.dumps(pages, ensure_ascii=False, separators=(",", ":")).encode())
    material_id = (
        "mat-"
        + _hash(
            json.dumps(
                [work_id, version_id, source_hash, content_hash, scope, parser_revision],
                separators=(",", ":"),
            ).encode()
        )[7:39]
    )
    spans: list[SourceSpan] = []
    for page_index, text in enumerate(pages):
        for start in range(0, len(text), MAX_SPAN_CHARS):
            end = min(start + MAX_SPAN_CHARS, len(text))
            page = page_index + 1 if page_count is not None else None
            span_id = "span-" + _hash(f"{material_id}:{page}:{start}:{end}".encode())[7:39]
            spans.append(
                SourceSpan(
                    span_id,
                    work_id,
                    version_id,
                    material_id,
                    source_hash,
                    scope,
                    parser_revision,
                    page,
                    section,
                    start,
                    end,
                    text[start:end],
                )
            )
    return SourceMaterial(
        material_id,
        work_id,
        version_id,
        source_hash,
        content_hash,
        scope,
        parser_revision,
        quality,
        tuple(warnings),
        complete,
        page_count,
        tuple(pages),
        tuple(spans),
    )


def extract_text(
    text: str,
    *,
    work_id: str,
    version_id: str,
    scope: Scope = "excerpt",
    section: str | None = None,
    max_chars: int = MAX_CHARS,
) -> SourceMaterial:
    """Retain exact supplied text and offsets; no markup execution or enrichment.

    Callers render strings as text, never HTML. Text must already have an honest
    acquisition scope; supplying an abstract does not turn it into full text.
    """
    _identity(work_id, version_id)
    if (
        scope not in {"metadata", "abstract", "excerpt", "full_text"}
        or not 1 <= max_chars <= MAX_CHARS
    ):
        raise MaterialError("invalid_material_bounds")
    if len(text.encode()) > MAX_PDF_BYTES:
        raise MaterialError("material_too_large")
    truncated = len(text) > max_chars
    retained = text[:max_chars]
    warnings = (
        ["Character limit reached; this retained material is an excerpt."] if truncated else []
    )
    quality = "partial" if truncated else "text_extracted" if retained.strip() else "empty"
    if quality == "empty":
        warnings.append("No source text was supplied.")
    return _build(
        work_id=work_id,
        version_id=version_id,
        source_hash=_hash(text.encode()),
        scope="excerpt" if truncated else scope,
        parser_revision=TEXT_PARSER_REVISION,
        pages=[retained],
        page_count=None,
        quality=quality,
        warnings=warnings,
        complete=not truncated,
        section=section,
    )


def extract_abstract(item: dict[str, Any]) -> SourceMaterial:
    """Capture the actual item's material at its recorded version and scope.

    Blog feed descriptions remain excerpts. Link-only records stay metadata with
    no fabricated source text. Nothing depends on evidence-store/model flags.
    """
    scope: Scope = item.get("source_scope") or item.get("access_state") or "metadata"
    return extract_text(
        str(item.get("abstract") or ""),
        work_id=str(item.get("work_id") or ""),
        version_id=str(item.get("version_id") or ""),
        scope=scope,
        section="abstract" if scope == "abstract" else None,
    )


def _pdf_worker(pdf: bytes, max_pages: int, max_chars: int) -> dict[str, Any]:
    # Import the existing parser engine only inside the isolated PDF process.
    import fitz

    try:
        with fitz.open(stream=pdf, filetype="pdf") as document:
            if document.needs_pass:
                raise MaterialError("encrypted_pdf")
            total = len(document)
            pages: list[str] = []
            remaining = max_chars
            truncated = total > max_pages
            for index in range(min(total, max_pages)):
                text = document[index].get_text("text", sort=True)
                if len(text) > remaining:
                    truncated = True
                pages.append(text[:remaining])
                remaining -= len(pages[-1])
                if remaining == 0:
                    truncated = truncated or index + 1 < total
                    break
            return {
                "pages": pages,
                "page_count": total,
                "truncated": truncated,
                "parser_revision": f"workspace-pymupdf-{fitz.VersionBind}-text-sort-v1",
            }
    except MaterialError:
        raise
    except (RuntimeError, ValueError, OSError) as exc:
        raise MaterialError("invalid_pdf") from exc


def extract_pdf(
    pdf: bytes,
    *,
    work_id: str,
    version_id: str,
    max_bytes: int = MAX_PDF_BYTES,
    max_pages: int = MAX_PAGES,
    max_chars: int = MAX_CHARS,
) -> SourceMaterial:
    """Extract a permitted local PDF sample with bounded process lifetime.

    This helper is not a crawler, an OCR service or a rights grant. Embedded
    scripts/links/attachments are never executed or followed. A cap creates an
    explicit excerpt; it is never labelled complete full text.
    """
    _identity(work_id, version_id)
    if (
        not 1 <= max_bytes <= MAX_PDF_BYTES
        or not 1 <= max_pages <= MAX_PAGES
        or not 1 <= max_chars <= MAX_CHARS
    ):
        raise MaterialError("invalid_material_bounds")
    if len(pdf) > max_bytes:
        raise MaterialError("material_too_large")
    if not pdf.startswith(b"%PDF-"):
        raise MaterialError("invalid_pdf")
    request = json.dumps(
        {
            "pdf": base64.b64encode(pdf).decode("ascii"),
            "max_pages": max_pages,
            "max_chars": max_chars,
        }
    ).encode()
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "src.workspace.material", "--worker"],
            input=request,
            capture_output=True,
            timeout=PDF_WALL_SECONDS,
            check=False,
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "ANTHROPIC_API_KEY": "local-preview-disabled"},
        )
    except subprocess.TimeoutExpired as exc:
        raise MaterialError("extraction_timed_out") from exc
    except OSError as exc:
        raise MaterialError("extraction_worker_unavailable") from exc
    if completed.returncode:
        raise MaterialError("extraction_failed")
    try:
        result = json.loads(completed.stdout)
        if "error" in result:
            raise MaterialError(str(result["error"]))
        pages = result["pages"]
        total = result["page_count"]
        truncated = result["truncated"]
        parser_revision = result["parser_revision"]
        if (
            not isinstance(pages, list)
            or len(pages) > max_pages
            or any(not isinstance(page, str) for page in pages)
            or sum(len(page) for page in pages) > max_chars
            or not isinstance(total, int)
            or total < len(pages)
            or not isinstance(truncated, bool)
            or not isinstance(parser_revision, str)
        ):
            raise ValueError("invalid extraction result")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, MaterialError):
            raise
        raise MaterialError("invalid_extraction_result") from exc
    warnings = [
        "PDF reading order, equations and tables require source review; no OCR was performed."
    ]
    text = "".join(pages)
    if not text.strip():
        quality = "empty"
        warnings.append(
            "No extractable text; document may be scanned, blank or use unsupported fonts."
        )
    elif truncated:
        quality = "partial"
        warnings.append("Page/character limit reached; retained material is an excerpt.")
    else:
        quality = "text_extracted"
    if (
        any(symbol in text for symbol in ("\ufffd", "\u222b", "\u2211", "\u2202", "\u221a"))
        or text.count("=") >= 3
    ):
        warnings.append(
            "Mathematical or replacement glyphs detected; check equations against the original PDF."
        )
    return _build(
        work_id=work_id,
        version_id=version_id,
        source_hash=_hash(pdf),
        scope="excerpt" if truncated else "full_text",
        parser_revision=parser_revision,
        pages=pages,
        page_count=total,
        quality=quality,
        warnings=warnings,
        complete=not truncated,
    )


def _worker_main() -> None:
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (PDF_WALL_SECONDS, PDF_WALL_SECONDS))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    try:
        raw = sys.stdin.buffer.read(MAX_PDF_BYTES * 2 + 1)
        if len(raw) > MAX_PDF_BYTES * 2:
            raise MaterialError("material_too_large")
        request = json.loads(raw)
        pdf = base64.b64decode(request["pdf"], validate=True)
        if len(pdf) > MAX_PDF_BYTES:
            raise MaterialError("material_too_large")
        pages = int(request["max_pages"])
        chars = int(request["max_chars"])
        if not 1 <= pages <= MAX_PAGES or not 1 <= chars <= MAX_CHARS:
            raise MaterialError("invalid_material_bounds")
        result = _pdf_worker(pdf, pages, chars)
    except (ValueError, KeyError, TypeError) as exc:
        result = {
            "error": str(exc) if isinstance(exc, MaterialError) else "invalid_extraction_request"
        }
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        _worker_main()
    else:
        raise SystemExit("Internal PDF worker only; use the supplied-byte library API.")
