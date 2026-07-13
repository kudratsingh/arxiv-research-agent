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
