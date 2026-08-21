"""Attach-time `plan_ready` replay on the SSE route (ADR 0053).

`plan_ready` is published exactly once, by the runner, at the moment
it parks the job. Neither transport keeps a backlog — Redis pub/sub
drops messages with no live subscriber, and the in-memory queue is
single-consumer — so a client that reconnects during the pause used
to see nothing but heartbeats until `api_hitl_timeout_sec` failed the
job half an hour later. The route now replays the plan from the job
row on attach, the same way it already replayed the terminal frame.

These drive `stream_research` directly with a stub store, in the
idiom of `tests/test_sse_stream.py`: no FastAPI, no Redis, no waiting.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.requests import Request

from src.api.jobs import Job, JobStatus
from src.api.routes import stream_research

pytestmark = pytest.mark.unit


PLAN = {
    "sub_questions": ["does replay help?", "what breaks without it?"],
    "search_queries": ["sse reconnect replay"],
}


class _ParkedDrainer:
    """A subscription that never yields — the pause, faithfully.

    The whole point of the bug is that nothing arrives on the wire
    while the job sits in `pending_review`, so the drainer used here
    must produce nothing at all. Anything the stream emits therefore
    came from the replay.
    """

    def __init__(self) -> None:
        self.aclose_calls = 0

    def __aiter__(self) -> _ParkedDrainer:
        return self

    async def __anext__(self) -> dict[str, Any]:
        await asyncio.Event().wait()  # parks forever
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        self.aclose_calls += 1


class _StubStore:
    """Just the surface `stream_research` touches."""

    def __init__(self, job: Job, drainer: _ParkedDrainer) -> None:
        self._job = job
        self._drainer = drainer

    async def get(self, job_id: str) -> Job:
        return self._job

    def subscribe_events(self, job_id: str) -> _ParkedDrainer:
        return self._drainer


def _request(store: _StubStore) -> Request:
    """Minimal ASGI request carrying the lifespan state the route reads."""

    async def receive() -> dict[str, Any]:  # pragma: no cover - never polled
        return {"type": "http.request"}

    app = SimpleNamespace(
        state=SimpleNamespace(
            store=store,
            workflow=None,
            semaphore=None,
            max_concurrent_jobs=1,
            tasks=set(),
            conversation_store=None,
        )
    )
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/research/j1/stream",
        "headers": [],
        "query_string": b"",
        "app": app,
    }
    return Request(scope, receive)


def _parse(frame: bytes) -> tuple[str, dict[str, Any]]:
    """Split one SSE frame into (event name, decoded data)."""
    lines = frame.decode().splitlines()
    name = next(ln[len("event: ") :] for ln in lines if ln.startswith("event: "))
    data = next(ln[len("data: ") :] for ln in lines if ln.startswith("data: "))
    return name, cast(dict[str, Any], json.loads(data))


async def _attach(job: Job, drainer: _ParkedDrainer) -> AsyncIterator[bytes]:
    response = await stream_research(
        job.job_id, _request(_StubStore(job, drainer)), principal=None
    )
    return cast(AsyncGenerator[bytes, None], response.body_iterator)


class TestPendingReviewReplay:
    async def test_first_frame_is_plan_ready(self) -> None:
        job = Job(
            job_id="j1",
            query="q",
            status=JobStatus.pending_review,
            plan=dict(PLAN),
        )
        drainer = _ParkedDrainer()
        body = await _attach(job, drainer)

        # No heartbeat first, no waiting: the reviewer's client gets
        # the plan on the very first frame of the reconnect.
        name, data = _parse(
            await asyncio.wait_for(body.__anext__(), timeout=1.0)
        )
        await body.aclose()

        assert name == "plan_ready"
        assert data == {"job_id": "j1", "plan": PLAN}

    async def test_payload_matches_the_runner_frame(self) -> None:
        # The runner publishes {"job_id", "plan": {two lists}}
        # (src/api/runner.py `_handle_hitl_pause`). A replay with a
        # different shape would make clients handle one event name two
        # ways, so this pins the contract rather than just the keys.
        job = Job(
            job_id="j1",
            query="q",
            status=JobStatus.pending_review,
            # As rehydrated from JSON: a plain dict, extra keys and all.
            plan={**PLAN, "unexpected": "ignored"},
        )
        body = await _attach(job, _ParkedDrainer())

        _, data = _parse(await asyncio.wait_for(body.__anext__(), timeout=1.0))
        await body.aclose()

        assert set(data) == {"job_id", "plan"}
        assert set(data["plan"]) == {"sub_questions", "search_queries"}
        assert data["plan"] == PLAN

    async def test_stream_stays_open_after_the_replay(self) -> None:
        # Unlike the terminal replay, this one must not close: the
        # review is still to come, and the frames after it (the
        # resumed run, then the terminal frame) travel on this same
        # connection.
        job = Job(
            job_id="j1",
            query="q",
            status=JobStatus.pending_review,
            plan=dict(PLAN),
        )
        drainer = _ParkedDrainer()
        body = await _attach(job, drainer)

        assert _parse(await asyncio.wait_for(body.__anext__(), timeout=1.0))[
            0
        ] == "plan_ready"
        # Next comes a heartbeat from the live loop, i.e. the route
        # subscribed and is streaming rather than having returned.
        assert await asyncio.wait_for(body.__anext__(), timeout=2.0) == (
            b": heartbeat\n\n"
        )
        await body.aclose()
        assert drainer.aclose_calls == 1

    async def test_no_replay_without_a_plan_snapshot(self) -> None:
        # `pending_review` with no plan is a torn write, not a review:
        # replaying `plan_ready` with empty lists would show the
        # reviewer an empty plan and invite them to approve it.
        job = Job(job_id="j1", query="q", status=JobStatus.pending_review)
        body = await _attach(job, _ParkedDrainer())

        first = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        await body.aclose()
        assert first == b": heartbeat\n\n"

    @pytest.mark.parametrize(
        "status", [JobStatus.pending, JobStatus.running]
    )
    async def test_no_replay_for_a_job_not_parked(
        self, status: JobStatus
    ) -> None:
        # A stale plan on a running job belongs to a review that was
        # already resolved (the runner clears it on resume, but a
        # crash between the two leaves the field set). Replaying it
        # would re-open a settled review.
        job = Job(job_id="j1", query="q", status=status, plan=dict(PLAN))
        body = await _attach(job, _ParkedDrainer())

        first = await asyncio.wait_for(body.__anext__(), timeout=2.0)
        await body.aclose()
        assert first == b": heartbeat\n\n"

    async def test_terminal_replay_still_wins(self) -> None:
        # A job that failed on the HITL timeout is terminal *and* may
        # still carry its plan. It must replay one terminal frame and
        # close, exactly as before ADR 0053.
        job = Job(
            job_id="j1",
            query="q",
            status=JobStatus.failed,
            error="review not answered in time",
            error_type="HitlTimeoutError",
            plan=dict(PLAN),
        )
        drainer = _ParkedDrainer()
        body = await _attach(job, drainer)

        name, _ = _parse(await asyncio.wait_for(body.__anext__(), timeout=1.0))
        assert name == "job_failed"
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(body.__anext__(), timeout=1.0)
        # Never subscribed — the terminal path does not touch the
        # drainer at all.
        assert drainer.aclose_calls == 0
