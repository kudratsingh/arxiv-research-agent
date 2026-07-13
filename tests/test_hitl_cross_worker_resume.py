"""Cross-worker HITL resume via Redis pub/sub (ADR 0034).

Audit finding: `resume_event` is a per-worker `asyncio.Event`;
`event_queue` and `resume_event` are excluded from the Redis
serialization. Under multi-worker uvicorn + `job_store=redis`, a
`POST /research/{id}/review` submitted to worker B fetched a
reconstructed `Job` (with a fresh, unset event) and set the event
on that copy — worker A's runner never woke.

Fix: `RedisJobStore.publish_remote_resume` publishes on
`hitl:resume:{job_id}`; the runner on worker A spawns
`watch_for_remote_resume` alongside its local await. This test
simulates the split by running the runner's subscriber against
one `RedisJobStore` instance and the publisher against another,
both wired to the same fakeredis backend.
"""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from src.api.jobs import Job
from src.api.redis_store import RedisJobStore

pytestmark = pytest.mark.integration


@pytest.fixture
async def shared_backend() -> fakeredis.aioredis.FakeRedis:
    """One fakeredis server — two clients simulate two workers.

    `FakeRedis` uses a process-global backing store by default when
    you construct multiple clients without a `server=` kwarg. That's
    what makes the "two workers, one Redis" story reproducible.
    """
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_cross_worker_resume_wakes_runner(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    """Worker A (runner) subscribes; worker B (review endpoint)
    publishes; runner wakes with the correct action + plan."""
    # Both "workers" share the fakeredis client so the pub/sub
    # channel actually connects them. In production these are two
    # `RedisJobStore` instances in two uvicorn processes talking to
    # the same Redis server — the store lets us model that with two
    # `RedisJobStore` wrappers around the same fake client.
    worker_a_store = RedisJobStore(shared_backend, retention_sec=60)
    worker_b_store = RedisJobStore(shared_backend, retention_sec=60)

    job = Job(job_id="abc123", query="q")

    # Runner-side: start the subscription. It should sit waiting.
    watch_task = asyncio.create_task(
        worker_a_store.watch_for_remote_resume(job)
    )

    # Give the subscribe a beat to actually attach to the channel
    # before we publish — otherwise the publish can race ahead and
    # the subscriber misses the message.
    await asyncio.sleep(0.05)

    # Reviewer-side: publish the decision.
    await worker_b_store.publish_remote_resume(
        job_id="abc123",
        action="revise",
        plan={
            "sub_questions": ["reworked q1", "reworked q2"],
            "search_queries": ["new query"],
        },
    )

    # The runner's Event should now be set within a short window.
    await asyncio.wait_for(job.resume_event.wait(), timeout=1.0)
    # `watch_for_remote_resume` returns on the first message; the
    # task should finish naturally within a beat.
    await asyncio.wait_for(watch_task, timeout=1.0)

    assert job.resume_action == "revise"
    assert job.resume_plan == {
        "sub_questions": ["reworked q1", "reworked q2"],
        "search_queries": ["new query"],
    }


@pytest.mark.asyncio
async def test_cancellation_before_message_cleans_up_pubsub(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    """When the runner cancels the subscription (same-worker resume
    took the fast path), the pubsub connection unsubscribes cleanly.
    """
    store = RedisJobStore(shared_backend, retention_sec=60)
    job = Job(job_id="fast-path", query="q")

    watch_task = asyncio.create_task(store.watch_for_remote_resume(job))
    await asyncio.sleep(0.05)  # let subscribe complete
    watch_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await watch_task
    # No message was ever published; job.resume_event should still
    # be unset. The important invariant is that the cancellation
    # didn't crash — the pubsub cleanup ran in `finally`.
    assert not job.resume_event.is_set()


@pytest.mark.asyncio
async def test_bad_payload_is_logged_and_skipped(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    """Malformed JSON on the channel doesn't crash the subscriber
    — just logs a warning and keeps listening for the next message.
    """
    from src.api.redis_store import _hitl_resume_channel

    store = RedisJobStore(shared_backend, retention_sec=60)
    job = Job(job_id="junk", query="q")

    watch_task = asyncio.create_task(store.watch_for_remote_resume(job))
    await asyncio.sleep(0.05)

    # Send garbage first, then a valid message.
    await shared_backend.publish(_hitl_resume_channel("junk"), b"not-json")
    await asyncio.sleep(0.05)
    await shared_backend.publish(
        _hitl_resume_channel("junk"),
        b'{"action":"approve","plan":null}',
    )

    await asyncio.wait_for(job.resume_event.wait(), timeout=1.0)
    await asyncio.wait_for(watch_task, timeout=1.0)
    assert job.resume_action == "approve"
    assert job.resume_plan is None
