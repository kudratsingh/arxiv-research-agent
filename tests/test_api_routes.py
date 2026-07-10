"""Integration-style tests for the FastAPI routes.

Uses `httpx.AsyncClient` against the app in-process (no network) and
injects a stub workflow so tests are deterministic and fast. Every
test manages its own lifespan via `asgi_lifespan.LifespanManager` so
one test cannot leak background jobs into another.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.api import create_app


class StubWorkflow:
    """Minimal stand-in for a compiled LangGraph app.

    Exposes `astream` + `invoke` — the only surface the runner uses.
    Deterministic per-call: emits the configured sequence of state
    updates, then returns a settled state.
    """

    def __init__(
        self,
        *,
        node_updates: list[tuple[str, dict[str, Any]]] | None = None,
        final_state: dict[str, Any] | None = None,
        raise_after: int | None = None,
        sleep_per_node_sec: float = 0.0,
    ) -> None:
        self.node_updates = node_updates or [
            ("planner", {"iteration": 0}),
            ("search", {"iteration": 0}),
            ("reader", {"iteration": 0}),
            ("synthesizer", {"iteration": 0}),
            ("critic", {"iteration": 1, "quality_score": 0.9}),
        ]
        self.final_state = final_state or {
            "draft_report": "# Stub Report\n\nDone.",
            "iteration": 1,
            "quality_score": 0.9,
            "citations": [],
        }
        self.raise_after = raise_after
        self.sleep_per_node_sec = sleep_per_node_sec

    async def astream(
        self, state: dict[str, Any], config: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        for i, (node, update) in enumerate(self.node_updates):
            if self.raise_after is not None and i >= self.raise_after:
                raise RuntimeError("stub workflow injected failure")
            if self.sleep_per_node_sec > 0:
                await asyncio.sleep(self.sleep_per_node_sec)
            yield {node: update}

    def invoke(
        self, state: dict[str, Any], config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        # Runner calls this via asyncio.to_thread after astream, so
        # sync is correct here. Returns the settled state that would
        # have accumulated from all the astream chunks.
        return {**state, **self.final_state}


def _make_app_with_stub(
    stub: StubWorkflow, *, max_concurrent_jobs: int = 10
) -> Any:
    return create_app(
        build_workflow=lambda: stub,
        max_concurrent_jobs=max_concurrent_jobs,
    )


async def _wait_for_terminal(
    client: AsyncClient, job_id: str, *, timeout_sec: float = 5.0
) -> dict[str, Any]:
    """Poll `/research/{job_id}` until it hits a terminal status.

    Better than `sleep` — deterministic timing, and if the workflow
    hangs the test fails with a clean timeout.
    """
    deadline = asyncio.get_event_loop().time() + timeout_sec
    while True:
        resp = await client.get(f"/research/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"job {job_id} did not settle in {timeout_sec}s")
        await asyncio.sleep(0.02)


class TestHealthz:
    async def test_healthz_returns_ok_and_concurrency_headroom(self) -> None:
        app = _make_app_with_stub(StubWorkflow(), max_concurrent_jobs=5)
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/healthz")
            assert resp.status_code == 200
            assert resp.json() == {
                "status": "ok",
                "active_jobs": 0,
                "max_concurrent_jobs": 5,
            }


class TestSubmitAndPoll:
    async def test_submit_returns_202_with_status_and_stream_urls(self) -> None:
        app = _make_app_with_stub(StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/research", json={"query": "q"})
            assert resp.status_code == 202
            body = resp.json()
            assert set(body.keys()) == {
                "job_id",
                "status",
                "status_url",
                "stream_url",
            }
            assert body["status"] == "pending"
            assert body["status_url"] == f"/research/{body['job_id']}"
            assert body["stream_url"] == f"/research/{body['job_id']}/stream"

    async def test_missing_job_returns_404(self) -> None:
        app = _make_app_with_stub(StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/research/nonexistent")
            assert resp.status_code == 404
            assert resp.json() == {"detail": "job_not_found"}

    async def test_full_lifecycle_reaches_succeeded(self) -> None:
        app = _make_app_with_stub(StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            submit = (await client.post("/research", json={"query": "q"})).json()
            final = await _wait_for_terminal(client, submit["job_id"])
            assert final["status"] == "succeeded"
            assert final["result"] == "# Stub Report\n\nDone."
            assert final["iterations"] == 1
            assert final["quality_score"] == 0.9
            assert final["elapsed_sec"] is not None and final["elapsed_sec"] >= 0

    async def test_workflow_error_marks_failed(self) -> None:
        # The stub raises after 2 nodes; the runner should catch and
        # mark failed without crashing the app.
        app = _make_app_with_stub(StubWorkflow(raise_after=2))
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            submit = (await client.post("/research", json={"query": "q"})).json()
            final = await _wait_for_terminal(client, submit["job_id"])
            assert final["status"] == "failed"
            assert final["error_type"] == "RuntimeError"
            assert "stub workflow injected failure" in final["error"]
            assert final["result"] is None


class TestQueryValidation:
    async def test_empty_query_rejected(self) -> None:
        app = _make_app_with_stub(StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/research", json={"query": ""})
            assert resp.status_code == 422

    async def test_missing_query_rejected(self) -> None:
        app = _make_app_with_stub(StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/research", json={})
            assert resp.status_code == 422

    async def test_overlong_query_rejected(self) -> None:
        app = _make_app_with_stub(StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/research", json={"query": "x" * 8001}
            )
            assert resp.status_code == 422


def _parse_sse_stream(text: str) -> list[dict[str, Any]]:
    """Parse an SSE payload into `[{event, data}, ...]` frames.

    Ignores comment lines (heartbeats) so tests can assert on the
    real event stream.
    """
    frames: list[dict[str, Any]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            if current:
                frames.append(
                    {
                        "event": current.get("event", ""),
                        "data": json.loads(current["data"])
                        if "data" in current
                        else None,
                    }
                )
                current = {}
            continue
        if line.startswith(":"):
            continue  # heartbeat comment
        key, _, value = line.partition(": ")
        current[key] = value
    if current:
        frames.append(
            {
                "event": current.get("event", ""),
                "data": json.loads(current["data"]) if "data" in current else None,
            }
        )
    return frames


class TestStreaming:
    async def test_stream_emits_node_events_and_terminal_frame(self) -> None:
        stub = StubWorkflow(sleep_per_node_sec=0.01)
        app = _make_app_with_stub(stub)
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            submit = (
                await client.post("/research", json={"query": "q"})
            ).json()
            # Fetch the stream — httpx buffers into `text` on
            # completion; StreamingResponse under ASGITransport
            # closes when the generator returns.
            resp = await client.get(
                f"/research/{submit['job_id']}/stream"
            )
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith(
                "text/event-stream"
            )
            frames = _parse_sse_stream(resp.text)
            event_names = [f["event"] for f in frames]

            # First frame is job_started; last frame is
            # job_completed. In between, at least one
            # node_completed per node in the stub.
            assert event_names[0] == "job_started"
            assert event_names[-1] == "job_completed"
            node_completed_count = event_names.count("node_completed")
            assert node_completed_count == len(stub.node_updates)

    async def test_stream_of_terminal_job_replays_final_frame(self) -> None:
        app = _make_app_with_stub(StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            submit = (
                await client.post("/research", json={"query": "q"})
            ).json()
            await _wait_for_terminal(client, submit["job_id"])

            # Reconnect after terminal — should yield exactly one
            # frame with the terminal event and close cleanly.
            resp = await client.get(
                f"/research/{submit['job_id']}/stream"
            )
            assert resp.status_code == 200
            frames = _parse_sse_stream(resp.text)
            assert len(frames) == 1
            assert frames[0]["event"] == "job_completed"
            assert frames[0]["data"]["status"] == "succeeded"

    async def test_stream_missing_job_returns_404(self) -> None:
        app = _make_app_with_stub(StubWorkflow())
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/research/nonexistent/stream")
            assert resp.status_code == 404


class TestConcurrencyLimit:
    async def test_semaphore_serializes_jobs_beyond_ceiling(self) -> None:
        # Two-slot semaphore, three jobs, each sleeps ~0.1s. The
        # third job must wait for one of the first two to release a
        # slot before it starts.
        started_at: dict[str, float] = {}
        original_astream = StubWorkflow.astream

        async def tracking_astream(
            self: StubWorkflow, state: dict[str, Any], config: dict[str, Any] | None = None
        ) -> AsyncIterator[dict[str, Any]]:
            started_at[state["run_id"]] = asyncio.get_event_loop().time()
            async for chunk in original_astream(self, state, config):
                yield chunk

        stub = StubWorkflow(sleep_per_node_sec=0.02)
        # 5 nodes * 0.02 = 0.10s per job.
        app = _make_app_with_stub(stub, max_concurrent_jobs=2)
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Monkeypatch on the stub instance rather than the
            # class so this test doesn't leak into others.
            stub.astream = tracking_astream.__get__(stub, StubWorkflow)  # type: ignore[method-assign]

            jobs = []
            for _ in range(3):
                resp = await client.post("/research", json={"query": "q"})
                jobs.append(resp.json()["job_id"])

            for job_id in jobs:
                await _wait_for_terminal(client, job_id, timeout_sec=10.0)

            # Third job must have started at least ~0.05s after
            # the first two — the semaphore forces the wait.
            times = sorted(started_at.values())
            assert times[2] - times[0] >= 0.05
