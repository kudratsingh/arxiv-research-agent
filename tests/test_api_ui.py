"""Tests for the demo UI mount (ADR 0029).

Verifies that:
  - `GET /` serves the HTML page.
  - Static assets are reachable under `/static/`.
  - The API routes and OpenAPI docs are not shadowed by the mount.

Deliberately shallow — the UI logic itself is JavaScript, exercised
by a human loading `/` in a browser. What CI needs to know is that
the mount doesn't regress the API surface.
"""

from __future__ import annotations

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.api import create_app


class _StubWorkflow:
    """Minimal build_workflow stub — the UI tests don't need a real
    graph, but `create_app` still constructs one on startup."""

    async def astream(self, state, config=None):  # pragma: no cover
        yield {"planner": {"iteration": 0}}

    def invoke(self, state, config=None):  # pragma: no cover
        return {**state, "draft_report": ""}


def _app():
    return create_app(build_workflow=lambda: _StubWorkflow())


class TestIndexRoute:
    async def test_root_serves_html_page(self) -> None:
        app = _app()
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/")
        assert resp.status_code == 200
        ctype = resp.headers.get("content-type", "")
        assert ctype.startswith("text/html")
        assert "<title>arxiv-research-agent</title>" in resp.text
        # Wired to the mounted static bundle — regression guard against
        # accidental path renames.
        assert '/static/app.js' in resp.text
        assert '/static/style.css' in resp.text


class TestStaticAssets:
    async def test_app_js_served(self) -> None:
        app = _app()
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/static/app.js")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/javascript")
        # A basic content check — the API endpoints the client calls.
        assert "/research" in resp.text
        assert "EventSource" in resp.text

    async def test_style_css_served(self) -> None:
        app = _app()
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/static/style.css")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/css")

    async def test_missing_static_returns_404(self) -> None:
        app = _app()
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/static/does-not-exist.js")
        assert resp.status_code == 404


class TestApiRoutesNotShadowed:
    """The UI mount must not swallow API routes or the OpenAPI surface."""

    @pytest.mark.parametrize(
        "path,expected_status",
        [
            ("/healthz", 200),
            ("/openapi.json", 200),
            ("/docs", 200),
            ("/research/nonexistent-id", 404),  # real API 404, not a static miss
        ],
    )
    async def test_route_not_shadowed(
        self, path: str, expected_status: int
    ) -> None:
        app = _app()
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(path)
        assert resp.status_code == expected_status

    async def test_research_post_still_works(self) -> None:
        # Regression: mounting `/static` shouldn't affect POST /research.
        app = _app()
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/research", json={"query": "x"})
        assert resp.status_code == 202
        body = resp.json()
        assert body["status_url"].startswith("/research/")
