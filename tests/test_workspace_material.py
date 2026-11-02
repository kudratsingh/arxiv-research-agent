"""Real bounded local extraction: synthetic PDF pages, exact spans and failures."""

from __future__ import annotations

import base64
import io
import json
import subprocess
from dataclasses import FrozenInstanceError, asdict
from typing import Any
from unittest.mock import MagicMock

import pytest
from reportlab.pdfgen import canvas

from src.workspace import material as m

pytestmark = pytest.mark.integration


def sample_pdf(*, blank: bool = False) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, invariant=True)
    if not blank:
        pdf.drawString(72, 720, "A synthetic scientific methods page.")
        pdf.drawString(72, 700, "Equation warning: x = y; y = z; z = x.")
    pdf.showPage()
    if not blank:
        pdf.drawString(72, 720, "The second page records a falsifiable experiment.")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def test_real_two_page_pdf_keeps_page_local_offsets_and_immutable_versions() -> None:
    original = sample_pdf()
    result = m.extract_pdf(original, work_id="local:permitted-sample", version_id="sample:v1")
    assert result.page_count == 2 and result.complete
    assert result.scope == "full_text" and result.quality == "text_extracted"
    assert "methods page" in result.pages[0]
    assert "second page" in result.pages[1]
    assert {span.page for span in result.spans} == {1, 2}
    for span in result.spans:
        assert span.page is not None
        assert span.text == result.pages[span.page - 1][span.start : span.end]
        assert span.work_id == result.work_id and span.version_id == "sample:v1"
        assert span.source_hash == result.source_hash and span.section is None
    assert any("equations" in warning for warning in result.warnings)
    assert "pymupdf-" in result.parser_revision
    assert "Unicode" in result.offset_basis
    assert result == m.extract_pdf(
        original, work_id="local:permitted-sample", version_id="sample:v1"
    )
    changed_version = m.extract_pdf(
        original, work_id="local:permitted-sample", version_id="sample:v2"
    )
    assert changed_version.source_hash == result.source_hash
    assert changed_version.material_id != result.material_id
    assert changed_version.spans[0].span_id != result.spans[0].span_id
    with pytest.raises(FrozenInstanceError):
        result.scope = "abstract"  # type: ignore[misc]
    assert json.loads(json.dumps(asdict(result)))["version_id"] == "sample:v1"


def test_page_and_character_caps_create_excerpt_not_full_text() -> None:
    first = m.extract_pdf(sample_pdf(), work_id="w", version_id="v", max_pages=1)
    assert not first.complete and first.scope == "excerpt" and first.quality == "partial"
    assert first.page_count == 2 and len(first.pages) == 1
    short = m.extract_pdf(sample_pdf(), work_id="w", version_id="v", max_chars=10)
    assert short.pages == ("A syntheti",)
    assert short.spans[0].end == 10
    assert short.scope == "excerpt" and not short.complete


def test_blank_pdf_preserves_empty_state_without_promising_ocr() -> None:
    result = m.extract_pdf(sample_pdf(blank=True), work_id="w", version_id="v")
    assert result.quality == "empty" and not result.spans
    assert any("scanned, blank" in warning for warning in result.warnings)
    assert any("no OCR" in warning for warning in result.warnings)


def test_abstract_is_retained_without_model_or_policy_evidence_flags() -> None:
    item = {
        "work_id": "arxiv:2611.00001",
        "version_id": "arxiv:2611.00001:v1",
        "abstract": "A real abstract.\nA second line.",
        "source_scope": "abstract",
        "enable_evidence_store": False,
    }
    result = m.extract_abstract(item)
    assert result.scope == "abstract" and result.pages == (item["abstract"],)
    assert result.spans[0].section == "abstract" and result.spans[0].page is None
    assert result.spans[0].text == item["abstract"]
    blog = m.extract_abstract({**item, "source_scope": "excerpt"})
    assert blog.scope == "excerpt" and blog.material_id != result.material_id
    link = m.extract_abstract({**item, "abstract": "", "source_scope": "metadata"})
    assert link.quality == "empty" and link.scope == "metadata" and not link.spans


def test_plain_unicode_text_spans_preserve_exact_context_without_markup_execution() -> None:
    text = "α source text\n" * 400 + "<script>untrusted data, not executed</script>"
    result = m.extract_text(text, work_id="w", version_id="v", section="provided section")
    assert "".join(span.text for span in result.spans) == text
    assert all(
        span.text == text[span.start : span.end] and span.page is None for span in result.spans
    )
    assert all(span.section == "provided section" for span in result.spans)
    short = m.extract_text(text, work_id="w", version_id="v", scope="full_text", max_chars=30)
    assert short.scope == "excerpt" and not short.complete and short.quality == "partial"
    assert short.pages[0] == text[:30]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_bytes": 0},
        {"max_bytes": m.MAX_PDF_BYTES + 1},
        {"max_pages": 0},
        {"max_pages": 13},
        {"max_chars": 0},
        {"max_chars": m.MAX_CHARS + 1},
    ],
)
def test_pdf_bounds_refused_before_process_construction(
    kwargs: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    process = MagicMock()
    monkeypatch.setattr(m.subprocess, "run", process)
    with pytest.raises(m.MaterialError, match="invalid_material_bounds"):
        m.extract_pdf(sample_pdf(), work_id="w", version_id="v", **kwargs)
    process.assert_not_called()


def test_missing_identity_oversized_and_invalid_input_refused() -> None:
    for work, version in (("", "v"), ("w", ""), ("x" * 301, "v")):
        with pytest.raises(m.MaterialError, match="source_version_required"):
            m.extract_pdf(sample_pdf(), work_id=work, version_id=version)
    with pytest.raises(m.MaterialError, match="material_too_large"):
        m.extract_pdf(sample_pdf(), work_id="w", version_id="v", max_bytes=10)
    with pytest.raises(m.MaterialError, match="invalid_pdf"):
        m.extract_pdf(b"not PDF", work_id="w", version_id="v")
    with pytest.raises(m.MaterialError, match="invalid_pdf"):
        m.extract_pdf(b"%PDF-corrupt", work_id="w", version_id="v")
    with pytest.raises(m.MaterialError, match="material_too_large"):
        m.extract_text("x" * (m.MAX_PDF_BYTES + 1), work_id="w", version_id="v")
    with pytest.raises(m.MaterialError, match="invalid_material_bounds"):
        m.extract_text("x", work_id="w", version_id="v", max_chars=0)


@pytest.mark.parametrize(
    "failure,reason",
    [
        (subprocess.TimeoutExpired("worker", 20), "extraction_timed_out"),
        (OSError("missing interpreter"), "extraction_worker_unavailable"),
    ],
)
def test_worker_lifecycle_failure_is_not_success(
    failure: Exception, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(m.subprocess, "run", MagicMock(side_effect=failure))
    with pytest.raises(m.MaterialError, match=reason):
        m.extract_pdf(sample_pdf(), work_id="w", version_id="v")


@pytest.mark.parametrize(
    "returncode,stdout,reason",
    [
        (1, b"", "extraction_failed"),
        (0, b"not JSON", "invalid_extraction_result"),
        (0, b"{}", "invalid_extraction_result"),
        (0, b'{"error":"encrypted_pdf"}', "encrypted_pdf"),
        (
            0,
            b'{"pages":[],"page_count":"two","truncated":false,"parser_revision":"bad"}',
            "invalid_extraction_result",
        ),
    ],
)
def test_worker_failure_and_malformed_reply_do_not_create_material(
    returncode: int, stdout: bytes, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        m.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=b""),
    )
    with pytest.raises(m.MaterialError, match=reason):
        m.extract_pdf(sample_pdf(), work_id="w", version_id="v")


def test_worker_process_is_sentinel_closed_and_input_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = sample_pdf()

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert command[-1] == "--worker"
        assert kwargs["env"]["ANTHROPIC_API_KEY"] == "local-preview-disabled"
        assert kwargs["timeout"] == 20 and kwargs["capture_output"]
        request = json.loads(kwargs["input"])
        assert base64.b64decode(request["pdf"]) == original
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b'{"pages":["source"],"page_count":1,"truncated":false,"parser_revision":"fixture-worker"}',
            stderr=b"",
        )

    monkeypatch.setattr(m.subprocess, "run", run)
    assert m.extract_pdf(original, work_id="w", version_id="v").pages == ("source",)


def test_parser_engine_encrypted_and_corrupt_pdf_refusals_are_real() -> None:
    import fitz

    original = sample_pdf()
    parsed = m._pdf_worker(original, 12, 120000)
    assert parsed["page_count"] == 2 and len(parsed["pages"]) == 2
    assert parsed["pages"][1].startswith("The second page")
    with fitz.open(stream=original, filetype="pdf") as document:
        encrypted = document.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner-fixture", user_pw="reader-fixture"
        )
    with pytest.raises(m.MaterialError, match="encrypted_pdf"):
        m._pdf_worker(encrypted, 12, 120000)
    with pytest.raises(m.MaterialError, match="encrypted_pdf"):
        m.extract_pdf(encrypted, work_id="w", version_id="v")
    with pytest.raises(m.MaterialError, match="invalid_pdf"):
        m._pdf_worker(b"%PDF-corrupt", 12, 120000)
    assert m._pdf_worker(original, 1, 5)["truncated"] is True


def _run_worker_main(
    raw: bytes, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], list[tuple[int, tuple[int, int]]]]:
    import resource
    from types import SimpleNamespace

    output = io.StringIO()
    limits: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(resource, "setrlimit", lambda kind, bounds: limits.append((kind, bounds)))
    monkeypatch.setattr(m.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    monkeypatch.setattr(m.sys, "stdout", output)
    m._worker_main()
    return json.loads(output.getvalue()), limits


def test_child_protocol_applies_linux_resource_limits_before_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import resource

    monkeypatch.setattr(m.sys, "platform", "linux")
    raw = json.dumps(
        {"pdf": base64.b64encode(sample_pdf()).decode(), "max_pages": 1, "max_chars": 10}
    ).encode()
    result, limits = _run_worker_main(raw, monkeypatch)
    assert result["pages"] == ["A syntheti"] and result["truncated"]
    assert limits == [
        (resource.RLIMIT_CPU, (20, 20)),
        (resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024)),
    ]


@pytest.mark.parametrize(
    "raw,reason",
    [
        (b"not JSON", "invalid_extraction_request"),
        (b"{}", "invalid_extraction_request"),
        (b'{"pdf":"!bad"}', "invalid_extraction_request"),
        (
            json.dumps(
                {"pdf": base64.b64encode(b"%PDF-corrupt").decode(), "max_pages": 0, "max_chars": 10}
            ).encode(),
            "invalid_material_bounds",
        ),
    ],
)
def test_child_protocol_refuses_malformed_requests(
    raw: bytes, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, _ = _run_worker_main(raw, monkeypatch)
    assert result == {"error": reason}


def test_child_protocol_bounds_encoded_and_decoded_input(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = _run_worker_main(b"x" * (m.MAX_PDF_BYTES * 2 + 1), monkeypatch)
    assert result == {"error": "material_too_large"}
    decoded = b"x" * (m.MAX_PDF_BYTES + 1)
    raw = json.dumps(
        {"pdf": base64.b64encode(decoded).decode(), "max_pages": 1, "max_chars": 10}
    ).encode()
    result, _ = _run_worker_main(raw, monkeypatch)
    assert result == {"error": "material_too_large"}
