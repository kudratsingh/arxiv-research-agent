"""Two pinned public PDFs: deterministic tests use supplied synthetic bytes only."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
import urllib3

from src.workspace import fulltext as f
from src.workspace.material import MAX_PDF_BYTES, MaterialError
from tests.test_workspace_material import sample_pdf

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 2, 16, tzinfo=UTC)


def transport(url: str) -> f.PdfResponse:
    return f.PdfResponse(200, {"Content-Type": "application/pdf"}, sample_pdf(), url)


def test_registered_versions_rights_and_envelope_are_explicit() -> None:
    assert set(f.SAMPLES) == {"2210.03629v3", "2310.11511v1"}
    assert f.MAX_BATCH_BYTES == 16 * 1024 * 1024
    react = f.sample_spec("arxiv:2210.03629:v3")
    assert react.pdf_url == "https://arxiv.org/pdf/2210.03629v3"
    assert react.license_url == "https://creativecommons.org/licenses/by/4.0/"
    with pytest.raises(MaterialError, match="fulltext_sample_not_allowed"):
        f.acquire_sample("2005.11401v4", transport=transport)
    with pytest.raises(MaterialError, match="fulltext_url_not_allowed"):
        f._fetch("https://arxiv.org/pdf/2210.03629")


def test_real_parser_keeps_exact_source_version_hash_and_quality_exclusions() -> None:
    result = f.acquire_sample("2210.03629v3", transport=transport, now=NOW)
    assert result.material is not None and result.raw_pdf == sample_pdf()
    assert result.material.version_id == "arxiv:2210.03629:v3"
    assert result.material.source_hash == result.receipt["source_hash"]
    assert result.receipt["status"] == "extracted" and result.receipt["request_count"] == 1
    assert result.receipt["fetched_at"] == "2026-11-02T16:00:00+00:00"
    assert result.receipt["retained_pages"] == [1, 2]
    assert result.receipt["visual_review"].startswith("pending")
    assert "table_cell_structure" in result.receipt["quality_exclusions"]
    assert "equation_semantics" in result.receipt["quality_exclusions"]


def test_selected_original_pages_are_reported_without_relabelling_scope() -> None:
    result = f.acquire_sample("2310.11511v1", transport=transport, now=NOW, page_numbers=[2])
    assert result.material is not None
    assert result.material.page_numbers == (2,) and result.material.spans[0].page == 2
    assert result.receipt["requested_pages"] == [2] and result.receipt["retained_pages"] == [2]
    assert result.receipt["source_scope"] == "excerpt" and not result.receipt["complete"]
    assert "unretained_pages" in result.receipt["quality_exclusions"]


def test_batch_is_two_distinct_sequential_gets_and_never_follows_links() -> None:
    calls: list[str] = []

    def get(url: str) -> f.PdfResponse:
        calls.append(url)
        return transport(url)

    results = f.acquire_samples(list(f.SAMPLES), transport=get, now=NOW)
    assert calls == [spec.pdf_url for spec in f.SAMPLES.values()]
    assert sum(result.receipt["request_count"] for result in results) == 2
    assert sum(result.receipt["bytes"] for result in results) <= f.MAX_BATCH_BYTES
    for versions in ([], ["2210.03629v3"] * 2, ["2210.03629v3"] * 3):
        with pytest.raises(MaterialError, match="invalid_fulltext_batch"):
            f.acquire_samples(versions, transport=get)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "status,error", [(302, "pdf_redirect_refused"), (429, "pdf_http_429"), (503, "pdf_http_503")]
)
def test_http_failure_records_retry_instruction_and_retains_abstract_fallback(
    status: int, error: str
) -> None:
    result = f.acquire_sample(
        "2210.03629v3",
        transport=lambda url: f.PdfResponse(status, {"Retry-After": "604800"}, b"", url),
        now=NOW,
    )
    assert result.material is None and result.raw_pdf is None
    assert result.receipt["status"] == "unavailable" and result.receipt["error"] == error
    assert result.receipt["request_count"] == 1 and result.receipt["retry_after"] == "604800"
    assert any("fallback" in value for value in result.receipt["limitations"])


@pytest.mark.parametrize(
    "response,error",
    [
        (
            f.PdfResponse(
                200, {"content-type": "text/html"}, b"not PDF", f.SAMPLES["2210.03629v3"].pdf_url
            ),
            "unexpected_pdf_content_type",
        ),
        (
            f.PdfResponse(
                200,
                {"content-type": "application/pdf"},
                b"not PDF",
                f.SAMPLES["2210.03629v3"].pdf_url,
            ),
            "invalid_pdf",
        ),
        (
            f.PdfResponse(
                200,
                {"content-type": "application/pdf"},
                b"x" * (MAX_PDF_BYTES + 1),
                f.SAMPLES["2210.03629v3"].pdf_url,
            ),
            "pdf_too_large",
        ),
        (
            f.PdfResponse(
                200,
                {"content-type": "application/pdf"},
                b"%PDF-",
                "https://arxiv.org/pdf/2210.03629v2",
            ),
            "fulltext_source_version_drift",
        ),
    ],
)
def test_mislabeled_oversized_or_wrong_version_responses_cannot_replace_material(
    response: f.PdfResponse, error: str
) -> None:
    result = f.acquire_sample("2210.03629v3", transport=lambda url: response, now=NOW)
    assert result.material is None and result.receipt["error"] == error


def test_parser_failure_retains_bytes_and_acquisition_receipt_but_no_fake_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(f, "extract_pdf", MagicMock(side_effect=MaterialError("extraction_failed")))
    result = f.acquire_sample("2210.03629v3", transport=transport, now=NOW)
    assert result.raw_pdf == sample_pdf() and result.receipt["bytes"] == len(sample_pdf())
    assert result.material is None and result.receipt["error"] == "extraction_failed"


def test_invalid_page_selection_and_naive_time_refuse_before_get() -> None:
    get = MagicMock()
    result = f.acquire_sample("2210.03629v3", page_numbers=[2, 1], transport=get, now=NOW)
    assert (
        result.receipt["error"] == "invalid_page_selection" and result.receipt["request_count"] == 0
    )
    with pytest.raises(MaterialError, match="timezone_required"):
        f.acquire_sample("2210.03629v3", transport=get, now=datetime(2026, 11, 2))
    get.assert_not_called()


def test_network_failure_is_safe_and_does_not_retry() -> None:
    get = MagicMock(side_effect=OSError("private system diagnostic"))
    result = f.acquire_sample("2210.03629v3", transport=get, now=NOW)
    assert result.receipt["error"] == "pdf_source_unavailable"
    assert result.material is None
    get.assert_called_once()


def fake_pool(monkeypatch: pytest.MonkeyPatch, response: MagicMock) -> MagicMock:
    monkeypatch.setattr(f, "_public_addresses", lambda host: ["93.184.216.34"])
    monkeypatch.setattr(f, "_rate_slot", lambda host: contextlib.nullcontext())
    pool = MagicMock()
    pool.urlopen.return_value = response

    def create(address: str, **kwargs: Any) -> MagicMock:
        assert address == "93.184.216.34" and kwargs["assert_hostname"] == "arxiv.org"
        assert kwargs["server_hostname"] == "arxiv.org" and kwargs["cert_reqs"] == "CERT_REQUIRED"
        return pool

    monkeypatch.setattr(f.urllib3, "HTTPSConnectionPool", create)
    return pool


def response(
    *, status: int = 200, headers: dict[str, str] | None = None, body: bytes = b"%PDF-synthetic"
) -> MagicMock:
    result = MagicMock(status=status, headers=headers or {})
    result.read.side_effect = [body, b""]
    return result


def test_transport_pins_tls_disables_redirects_retries_and_decompression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = response()
    pool = fake_pool(monkeypatch, reply)
    result = f._fetch(f.SAMPLES["2210.03629v3"].pdf_url)
    assert result.body == b"%PDF-synthetic"
    kwargs = pool.urlopen.call_args.kwargs
    assert kwargs["redirect"] is False and kwargs["retries"] is False
    assert kwargs["headers"]["Host"] == "arxiv.org"
    assert kwargs["headers"]["Accept-Encoding"] == "identity"
    pool.close.assert_called_once()
    reply.close.assert_called_once()


def test_transport_returns_failed_status_without_reading_body_or_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = response(status=302, headers={"Location": "http://127.0.0.1/"})
    pool = fake_pool(monkeypatch, reply)
    result = f._fetch(f.SAMPLES["2210.03629v3"].pdf_url)
    assert result.status == 302 and result.body == b""
    reply.read.assert_not_called()
    pool.urlopen.assert_called_once()


@pytest.mark.parametrize(
    "headers,body,error",
    [
        ({"content-encoding": "gzip"}, b"", "unsupported_content_encoding"),
        ({"content-length": str(MAX_PDF_BYTES + 1)}, b"", "pdf_too_large"),
        ({"content-length": "9" * 50}, b"", "pdf_too_large"),
        ({"content-length": "bad"}, b"", "pdf_too_large"),
        ({}, b"x" * (MAX_PDF_BYTES + 1), "pdf_too_large"),
    ],
)
def test_transport_bounds_and_cleanup(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], body: bytes, error: str
) -> None:
    reply = response(headers=headers, body=body)
    pool = fake_pool(monkeypatch, reply)
    with pytest.raises(MaterialError, match=error):
        f._fetch(f.SAMPLES["2210.03629v3"].pdf_url)
    pool.close.assert_called_once()
    reply.close.assert_called_once()


def test_transport_deadline_and_read_failure_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = response()
    fake_pool(monkeypatch, reply)
    ticks = iter([0, 31])
    monkeypatch.setattr(f.time, "monotonic", lambda: next(ticks))
    with pytest.raises(MaterialError, match="pdf_fetch_deadline"):
        f._fetch(f.SAMPLES["2210.03629v3"].pdf_url)
    monkeypatch.setattr(f.time, "monotonic", lambda: 0)
    reply = response()
    reply.read.side_effect = urllib3.exceptions.ReadTimeoutError(None, "/", "timed out")
    pool = fake_pool(monkeypatch, reply)
    result = f.acquire_sample("2210.03629v3", now=NOW)
    assert result.receipt["error"] == "pdf_source_unavailable"
    pool.close.assert_called_once()
    reply.close.assert_called_once()
