"""Multi-format export for completed research jobs (ADR 0031).

Turns a completed `Job` (with its markdown report body) into a
downloadable file in Markdown, PDF, or DOCX. Called by
`GET /research/{job_id}/export?format=...`.

Public API:

    from src.api.exporters import EXPORTERS, ExportFormat

    ExportFormat literals: "md" | "pdf" | "docx"
    EXPORTERS[fmt] -> (media_type, filename_ext, render_fn)
    render_fn(job) -> bytes (utf-8 for md; raw file bytes for pdf/docx)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from src.api.exporters.docx import render_docx
from src.api.exporters.markdown import render_markdown
from src.api.exporters.pdf import render_pdf
from src.api.jobs import Job

ExportFormat = Literal["md", "pdf", "docx"]

MEDIA_TYPES: dict[str, str] = {
    "md": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
    "docx": (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    ),
}

FILENAME_EXTS: dict[str, str] = {
    "md": "md",
    "pdf": "pdf",
    "docx": "docx",
}

RENDERERS: dict[str, Callable[[Job], bytes]] = {
    "md": render_markdown,
    "pdf": render_pdf,
    "docx": render_docx,
}

EXPORTERS: dict[str, tuple[str, str, Callable[[Job], bytes]]] = {
    fmt: (MEDIA_TYPES[fmt], FILENAME_EXTS[fmt], RENDERERS[fmt])
    for fmt in ("md", "pdf", "docx")
}

__all__ = [
    "EXPORTERS",
    "FILENAME_EXTS",
    "MEDIA_TYPES",
    "RENDERERS",
    "ExportFormat",
]
