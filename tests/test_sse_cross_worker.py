"""Cross-worker SSE fan-out via Redis pub/sub (ADR 0035).

The audit and ADR 0027 flagged that SSE streaming required sticky
routing: the runner put events on an `asyncio.Queue` living on its
own worker, so a stream endpoint landing on a different worker got
an empty queue.

ADR 0035 mirrors the ADR-0034 HITL fix: `RedisJobStore.publish_event`
puts frames on `events:{job_id}`; `subscribe_events` reads them.
The runner's `_put_event` uses pub/sub whenever the store advertises
it, so the local queue no longer matters under RedisJobStore.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import fakeredis.aioredis
import pytest

from src.api.redis_store import RedisJobStore, _events_channel

pytestmark = pytest.mark.integration


@pytest.fixture
async def shared_backend() -> fakeredis.aioredis.FakeRedis:
    """One fakeredis client; both `RedisJobStore` instances share it
    to simulate two workers pointing at the same Redis."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_events_publish_reaches_subscriber_on_other_worker(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    """Runner on 'worker A' publishes; stream on 'worker B' receives.

    The full sequence: `job_started` → two `node_completed` frames →
    `job_completed`. The subscriber terminates on the terminal
    frame — same semantics as `drain_events` for `InMemoryJobStore`.
    """
    runner_store = RedisJobStore(shared_backend, retention_sec=60)
    stream_store = RedisJobStore(shared_backend, retention_sec=60)

    received: list[dict] = []

    async def stream_consumer() -> None:
        async for frame in stream_store.subscribe_events("job-xyz"):
            received.append(frame)

    consumer = asyncio.create_task(stream_consumer())
    # Give the subscribe a beat to attach — publishing before the
    # subscriber connects loses the message under pub/sub semantics.
    await asyncio.sleep(0.05)

    await runner_store.publish_event(
        "job-xyz", "job_started", {"query": "hi"}
    )
    await runner_store.publish_event(
        "job-xyz", "node_completed", {"node": "planner"}
    )
    await runner_store.publish_event(
        "job-xyz", "node_completed", {"node": "search"}
    )
    await runner_store.publish_event(
        "job-xyz", "job_completed", {"cost_usd": 0.05}
    )

    await asyncio.wait_for(consumer, timeout=1.5)

    events = [f["event"] for f in received]
    assert events == [
        "job_started",
        "node_completed",
        "node_completed",
        "job_completed",
    ]
    assert received[0]["data"] == {"query": "hi"}
    assert received[-1]["data"] == {"cost_usd": 0.05}


@pytest.mark.asyncio
async def test_subscribe_terminates_on_job_failed(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    """`job_failed` closes the stream just like `job_completed`."""
    runner_store = RedisJobStore(shared_backend, retention_sec=60)
    stream_store = RedisJobStore(shared_backend, retention_sec=60)

    received: list[dict] = []

    async def stream_consumer() -> None:
        async for frame in stream_store.subscribe_events("job-fail"):
            received.append(frame)

    consumer = asyncio.create_task(stream_consumer())
    await asyncio.sleep(0.05)
    await runner_store.publish_event(
        "job-fail", "job_failed", {"error": "boom"}
    )
    await asyncio.wait_for(consumer, timeout=1.5)
    assert [f["event"] for f in received] == ["job_failed"]


@pytest.mark.asyncio
async def test_subscribe_terminates_on_job_cancelled(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    runner_store = RedisJobStore(shared_backend, retention_sec=60)
    stream_store = RedisJobStore(shared_backend, retention_sec=60)

    received: list[dict] = []

    async def stream_consumer() -> None:
        async for frame in stream_store.subscribe_events("job-cancel"):
            received.append(frame)

    consumer = asyncio.create_task(stream_consumer())
    await asyncio.sleep(0.05)
    await runner_store.publish_event(
        "job-cancel", "job_cancelled", {"reason": "user"}
    )
    await asyncio.wait_for(consumer, timeout=1.5)
    assert [f["event"] for f in received] == ["job_cancelled"]


@pytest.mark.asyncio
async def test_subscribe_skips_malformed_payload(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    """A rogue publisher on the same channel with garbage payload
    doesn't crash the subscriber — the frame is logged and skipped,
    and the next valid message is delivered normally."""
    store = RedisJobStore(shared_backend, retention_sec=60)

    received: list[dict] = []

    async def stream_consumer() -> None:
        async for frame in store.subscribe_events("job-junk"):
            received.append(frame)

    consumer = asyncio.create_task(stream_consumer())
    await asyncio.sleep(0.05)

    channel = _events_channel("job-junk")
    await shared_backend.publish(channel, b"this-is-not-json")
    await shared_backend.publish(channel, b"[1,2,3]")  # valid JSON, wrong shape
    await asyncio.sleep(0.05)
    await store.publish_event("job-junk", "job_completed", {"ok": True})

    await asyncio.wait_for(consumer, timeout=1.5)
    assert [f["event"] for f in received] == ["job_completed"]


@pytest.mark.asyncio
async def test_subscription_cancellation_cleans_up_pubsub(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    """Client disconnect: `aclose()` on the generator triggers the
    `finally` unsubscribe/release path. No message ever arrives; the
    important thing is that we don't leak the pubsub connection."""
    store = RedisJobStore(shared_backend, retention_sec=60)

    async def stream_consumer() -> None:
        drainer = store.subscribe_events("job-idle")
        try:
            async for _frame in drainer:
                pass
        finally:
            await drainer.aclose()

    consumer = asyncio.create_task(stream_consumer())
    await asyncio.sleep(0.05)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer


class CompletingStub:
    """Fake compiled workflow that runs two nodes and succeeds.

    Just enough surface for `run_job`'s `_invoke_streaming`: an
    `astream` that yields node updates, a `get_state` reporting no
    interrupt, and an `invoke` returning the settled final state.
    """

    async def astream(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"planner": {"iteration": 0}}
        yield {"synthesizer": {"iteration": 1, "quality_score": 0.9}}

    def get_state(self, config: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(next=(), values={})

    def invoke(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "draft_report": "# Report",
            "iteration": 1,
            "quality_score": 0.9,
        }


@pytest.mark.asyncio
async def test_runner_publishes_terminal_frame_to_other_worker(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    """The end-to-end pin the audit asked for: a REAL `run_job`
    against a RedisJobStore-backed store must publish its terminal
    frame over pub/sub, and a subscriber on a second store instance
    (simulating the stream endpoint on another worker) must receive
    it with the documented payload and terminate.

    The earlier tests in this module drive `publish_event` directly —
    they'd stay green even if the runner never called it. This one
    fails if `run_job` stops publishing the terminal frame, publishes
    it to the local queue instead, or changes the payload shape.
    """
    from src.api.jobs import Job, JobStatus
    from src.api.runner import run_job

    runner_store = RedisJobStore(shared_backend, retention_sec=60)
    stream_store = RedisJobStore(shared_backend, retention_sec=60)

    job = Job(job_id="job-e2e", query="q", hitl_bypass=True)
    await runner_store.create(job)

    received: list[dict] = []

    async def stream_consumer() -> None:
        async for frame in stream_store.subscribe_events("job-e2e"):
            received.append(frame)

    consumer = asyncio.create_task(stream_consumer())
    await asyncio.sleep(0.05)  # let the subscriber attach

    await run_job(
        job,
        CompletingStub(),
        runner_store,
        asyncio.Semaphore(1),
    )
    # The subscriber must terminate on its own — that only happens
    # when the runner's terminal frame actually arrives.
    await asyncio.wait_for(consumer, timeout=2.0)

    assert job.status == JobStatus.succeeded
    events = [f["event"] for f in received]
    assert events == [
        "job_started",
        "node_completed",
        "node_completed",
        "job_completed",
    ]
    terminal = received[-1]["data"]
    assert set(terminal) == {
        "job_id",
        "iterations",
        "quality_score",
        "cost_usd",
        "llm_calls",
        "elapsed_sec",
    }
    assert terminal["job_id"] == "job-e2e"
    assert terminal["iterations"] == 1
    assert terminal["quality_score"] == 0.9

    # Under RedisJobStore, pub/sub is the ONLY delivery path — the
    # local queue must stay untouched or a multi-worker runner would
    # eventually deadlock on the blocking terminal put.
    assert job.event_queue.qsize() == 0


class TestRunnerPubsubBypass:
    """`_put_event` on the runner side: when the current context's
    store advertises `publish_event`, the local `job.event_queue` is
    NOT populated. Otherwise a multi-worker deployment would fill an
    unread queue on the runner's worker until the blocking terminal
    `put()` deadlocks.
    """

    @pytest.mark.asyncio
    async def test_pub_sub_store_skips_local_queue(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        from src.api.jobs import Job
        from src.api.runner import _current_store, _put_event

        store = RedisJobStore(shared_backend, retention_sec=60)
        _current_store.set(store)

        job = Job(job_id="local-empty", query="q")
        await _put_event(job, "node_completed", {"node": "planner"})

        # Under RedisJobStore the local queue stays empty — the
        # pub/sub is the delivery path.
        assert job.event_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_in_memory_store_uses_local_queue(self) -> None:
        """Backward compat: `InMemoryJobStore` still queues events
        into `job.event_queue`, so `drain_events` on the stream
        endpoint sees them."""
        from src.api.jobs import InMemoryJobStore, Job
        from src.api.runner import _current_store, _put_event

        _current_store.set(InMemoryJobStore())

        job = Job(job_id="local-full", query="q")
        await _put_event(job, "node_completed", {"node": "planner"})
        assert job.event_queue.qsize() == 1
        frame = job.event_queue.get_nowait()
        assert frame["event"] == "node_completed"
        assert frame["data"] == {"node": "planner"}
