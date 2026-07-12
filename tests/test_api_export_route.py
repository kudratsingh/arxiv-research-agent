"""Integration tests for `GET /research/{id}/export?format=...`."""

from __future__ import annotations

import asyncio
import io
import zipfile
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.api import create_app


class _StubWorkflow:
    """Bypass-friendly stub that yields a single planner node and
    lands in a settled state with a small markdown report."""

    _DEFAULT_REPORT = "# Report\n\nBody paragraph.\n"

    def __init__(self, *, report: str | None = None) -> None:
        # `report is None` picks the default; `report=""` sticks so
        # tests can exercise the "no report" 409 path.
        self.report = self._DEFAULT_REPORT if report is None else report

    async def astream(
        self, state: dict[str, Any] | None, config: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        if state is not None:
            yield {"planner": {"iteration": 0}}

    def get_state(self, config: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(next=(), values={"draft_report": self.report})

    def invoke(
        self, state: dict[str, Any] | None, config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {"draft_report": self.report, "iteration": 1, "quality_score": 0.9}


async def _run_until_terminal(client: AsyncClient, job_id: str) -> dict[str, Any]:
    for _ in range(50):
        resp = await client.get(f"/research/{job_id}")
        body = resp.json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        await asyncio.sleep(0.02)
    raise TimeoutError(f"job {job_id} did not settle")


async def _submit_and_wait(client: AsyncClient) -> str:
    resp = await client.post(
        "/research", json={"query": "hallucination", "hitl_bypass": True}
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    await _run_until_terminal(client, job_id)
    return job_id


class TestExportSuccessPath:
    @pytest.mark.parametrize(
        "fmt,expected_mime,expected_ext",
        [
            ("md", "text/markdown", "md"),
            ("pdf", "application/pdf", "pdf"),
            (
                "docx",
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document",
                "docx",
            ),
        ],
    )
    async def test_returns_200_with_correct_headers(
        self, fmt: str, expected_mime: str, expected_ext: str
    ) -> None:
        app = create_app(build_workflow=lambda: _StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            job_id = await _submit_and_wait(client)

            resp = await client.get(f"/research/{job_id}/export?format={fmt}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith(expected_mime)
        disp = resp.headers["content-disposition"]
        assert "attachment" in disp
        assert f'filename="research-{job_id}.{expected_ext}"' in disp
        # No caching — the payload is per-user and unauthenticated.
        assert resp.headers.get("cache-control") == "no-store"

    async def test_pdf_body_starts_with_magic(self) -> None:
        app = create_app(build_workflow=lambda: _StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            job_id = await _submit_and_wait(client)
            resp = await client.get(f"/research/{job_id}/export?format=pdf")
        assert resp.content.startswith(b"%PDF-")

    async def test_docx_body_is_valid_zip(self) -> None:
        app = create_app(build_workflow=lambda: _StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            job_id = await _submit_and_wait(client)
            resp = await client.get(f"/research/{job_id}/export?format=docx")
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            assert "word/document.xml" in z.namelist()

    async def test_markdown_body_carries_report(self) -> None:
        app = create_app(build_workflow=lambda: _StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            job_id = await _submit_and_wait(client)
            resp = await client.get(f"/research/{job_id}/export?format=md")
        text = resp.content.decode()
        assert "Body paragraph." in text
        assert job_id in text

    async def test_default_format_is_markdown(self) -> None:
        # Route default: no format query param -> md.
        app = create_app(build_workflow=lambda: _StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            job_id = await _submit_and_wait(client)
            resp = await client.get(f"/research/{job_id}/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")


class TestExportGuards:
    async def test_missing_job_is_404(self) -> None:
        app = create_app(build_workflow=lambda: _StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/research/nonexistent/export?format=md")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "job_not_found"

    async def test_job_without_report_is_409(self) -> None:
        # Stub returns an empty report; the route rejects the export.
        app = create_app(build_workflow=lambda: _StubWorkflow(report=""))
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            job_id = await _submit_and_wait(client)
            resp = await client.get(f"/research/{job_id}/export?format=md")
        assert resp.status_code == 409
        assert "job_has_no_report" in resp.json()["detail"]

    @pytest.mark.parametrize("bad", ["exe", "html", "", "MD", "pdf.zip"])
    async def test_invalid_format_is_422(self, bad: str) -> None:
        app = create_app(build_workflow=lambda: _StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            job_id = await _submit_and_wait(client)
            resp = await client.get(
                f"/research/{job_id}/export?format={bad}"
            )
        assert resp.status_code == 422
