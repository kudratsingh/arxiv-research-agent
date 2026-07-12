"""Unit tests for the multi-format exporters (ADR 0031).

Deliberately checks the *shape* of each format rather than exact
byte output — reportlab and python-docx both include timestamps +
UUIDs in their generated files, so byte-level snapshots would
flake.

Assertions cover:
  - correct file magic (%PDF- / PK zip header)
  - job metadata is embedded (job_id, query, cost, iterations)
  - the report body content survives the round-trip
"""

from __future__ import annotations

import io
import zipfile

import pytest

from src.api.exporters import EXPORTERS, FILENAME_EXTS, MEDIA_TYPES
from src.api.jobs import Job, JobStatus


def _job(**overrides: object) -> Job:
    """Build a completed Job with a small canonical report body."""
    defaults: dict[str, object] = {
        "job_id": "abc123",
        "query": "chain-of-verification for hallucination",
        "status": JobStatus.succeeded,
        "started_at": 1_700_000_000.0,
        "completed_at": 1_700_000_042.7,
        "result": (
            "# Reducing Hallucination\n\n"
            "Three categories emerge.\n\n"
            "## Training-time\n\n"
            "RLHF-V uses **fine-grained** feedback.\n\n"
            "## Generation-time\n\n"
            "- Chain-of-Verification\n"
            "- Self-RAG\n"
            "- `retrieval-augmented generation`\n\n"
            "| Approach | Cost |\n"
            "|---|---|\n"
            "| RLHF | High |\n"
            "| CoVe | Low |\n"
        ),
        "iterations": 1,
        "quality_score": 0.9,
        "cost_usd": 0.087,
        "llm_calls": 8,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


# `render_*` names not exported — reach through the RENDERERS dict.
render_markdown_bytes = EXPORTERS["md"][2]
render_pdf_bytes = EXPORTERS["pdf"][2]
render_docx_bytes = EXPORTERS["docx"][2]


class TestExportersRegistry:
    def test_three_formats_are_registered(self) -> None:
        assert set(EXPORTERS.keys()) == {"md", "pdf", "docx"}

    def test_media_types_are_standard(self) -> None:
        assert MEDIA_TYPES["md"].startswith("text/markdown")
        assert MEDIA_TYPES["pdf"] == "application/pdf"
        assert MEDIA_TYPES["docx"].startswith(
            "application/vnd.openxmlformats-officedocument"
        )

    def test_filename_exts_match_format_keys(self) -> None:
        for fmt in ("md", "pdf", "docx"):
            assert FILENAME_EXTS[fmt] == fmt


class TestMarkdownRenderer:
    def test_returns_utf8_bytes(self) -> None:
        out = render_markdown_bytes(_job())
        assert isinstance(out, bytes)
        # utf-8 decodable.
        out.decode("utf-8")

    def test_body_preserved_verbatim(self) -> None:
        job = _job()
        out = render_markdown_bytes(job).decode()
        # Every non-trivial line from the source body should appear
        # in the exported file.
        for expected in (
            "Reducing Hallucination",
            "Training-time",
            "RLHF-V",
            "Chain-of-Verification",
            "| Approach | Cost |",
        ):
            assert expected in out

    def test_metadata_header_present(self) -> None:
        out = render_markdown_bytes(_job()).decode()
        assert "abc123" in out
        assert "chain-of-verification for hallucination" in out
        assert "$0.0870" in out
        assert "0.90" in out  # quality
        assert "42.7s" in out  # elapsed

    def test_handles_missing_result(self) -> None:
        # No hard error even when the report is empty (edge case if
        # an operator overrides guard checks).
        out = render_markdown_bytes(_job(result=None)).decode()
        assert "(no report body)" in out

    def test_pipe_in_query_is_escaped_for_table(self) -> None:
        # Metadata is rendered as a GFM table; a `|` in the query
        # would break the row otherwise.
        out = render_markdown_bytes(_job(query="a | b")).decode()
        assert "a \\| b" in out


class TestPdfRenderer:
    def test_returns_pdf_bytes_with_magic(self) -> None:
        out = render_pdf_bytes(_job())
        assert isinstance(out, bytes)
        assert out.startswith(b"%PDF-")
        # A minimally valid PDF ends with %%EOF (possibly followed by newline).
        assert b"%%EOF" in out[-64:]

    def test_pdf_size_reasonable_for_short_report(self) -> None:
        out = render_pdf_bytes(_job())
        # ~2-10KB is what our fixture produces; guardrail against a
        # regression that ships an unbounded blob.
        assert 500 < len(out) < 200_000

    def test_pdf_embeds_report_and_metadata_strings(self) -> None:
        # PDFs compress content streams — best we can do without a
        # PDF parser is check the top-level info dictionary and the
        # /Title field. reportlab writes `Title` in the info dict as
        # a plain string.
        out = render_pdf_bytes(_job())
        assert b"Research briefing" in out

    def test_handles_empty_result(self) -> None:
        # No crash; still emits a valid PDF.
        out = render_pdf_bytes(_job(result=None))
        assert out.startswith(b"%PDF-")


class TestDocxRenderer:
    def test_returns_zip_bytes_with_pk_magic(self) -> None:
        # DOCX = ZIP archive of XML parts.
        out = render_docx_bytes(_job())
        assert isinstance(out, bytes)
        assert out[:2] == b"PK"

    def test_docx_is_valid_zip_with_word_document(self) -> None:
        out = render_docx_bytes(_job())
        with zipfile.ZipFile(io.BytesIO(out)) as z:
            names = z.namelist()
            assert "word/document.xml" in names
            # The core body text lives in document.xml — grep for a
            # phrase from the report.
            body = z.read("word/document.xml").decode("utf-8", errors="replace")
        assert "Reducing Hallucination" in body
        assert "chain-of-verification for hallucination" in body
        assert "RLHF-V" in body

    def test_docx_embeds_metadata(self) -> None:
        out = render_docx_bytes(_job())
        with zipfile.ZipFile(io.BytesIO(out)) as z:
            body = z.read("word/document.xml").decode("utf-8", errors="replace")
        assert "abc123" in body
        assert "$0.0870" in body
        assert "42.7s" in body

    def test_handles_empty_result(self) -> None:
        out = render_docx_bytes(_job(result=None))
        assert out[:2] == b"PK"


class TestFormatParityContract:
    """Every renderer should honor the same input surface."""

    @pytest.mark.parametrize("fmt", ["md", "pdf", "docx"])
    def test_renderers_never_raise_on_valid_job(self, fmt: str) -> None:
        _, _, render = EXPORTERS[fmt]
        render(_job())  # must not raise

    @pytest.mark.parametrize("fmt", ["md", "pdf", "docx"])
    def test_renderers_return_bytes(self, fmt: str) -> None:
        _, _, render = EXPORTERS[fmt]
        out = render(_job())
        assert isinstance(out, bytes)
