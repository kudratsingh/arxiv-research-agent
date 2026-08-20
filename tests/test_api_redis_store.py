"""Tests for `RedisJobStore` against a `fakeredis` client.

Marked `integration` because they exercise the real redis-py client
against an in-process Redis emulator. Fast enough to run on every
PR alongside the unit tier.
"""

from __future__ import annotations

import asyncio
import json
import time

import fakeredis.aioredis
import pytest

from src.api.jobs import Job, JobStatus
from src.api.redis_store import (
    JOB_KEY_PREFIX,
    RedisJobStore,
    _job_from_json,
    _job_to_json,
    _persistent_fields,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def redis_client() -> fakeredis.aioredis.FakeRedis:
    """Fresh fakeredis per test — no state leaks."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
async def store(redis_client: fakeredis.aioredis.FakeRedis) -> RedisJobStore:
    return RedisJobStore(redis_client, retention_sec=3600)


class TestSerialization:
    def test_persistent_fields_excludes_event_queue(self) -> None:
        # event_queue is asyncio.Queue — not serializable, and lives
        # only on the worker running the job.
        fields = _persistent_fields()
        assert "event_queue" not in fields
        # Sanity: the core lifecycle fields are all present.
        for expected in (
            "job_id",
            "query",
            "status",
            "created_at",
            "result",
            "error",
            "cost_usd",
        ):
            assert expected in fields

    def test_roundtrip_preserves_fields(self) -> None:
        original = Job(
            job_id="j1",
            query="hallucination",
            status=JobStatus.succeeded,
            created_at=1_700_000_000.0,
            started_at=1_700_000_001.0,
            completed_at=1_700_000_042.5,
            result="# Report\n\nDone.",
            error=None,
            error_type=None,
            cost_usd=0.087,
            llm_calls=8,
            iterations=1,
            quality_score=0.9,
        )
        rebuilt = _job_from_json(_job_to_json(original))
        assert rebuilt.job_id == original.job_id
        assert rebuilt.query == original.query
        assert rebuilt.status == JobStatus.succeeded
        assert rebuilt.created_at == original.created_at
        assert rebuilt.started_at == original.started_at
        assert rebuilt.completed_at == original.completed_at
        assert rebuilt.result == original.result
        assert rebuilt.cost_usd == original.cost_usd
        assert rebuilt.llm_calls == original.llm_calls
        assert rebuilt.iterations == original.iterations
        assert rebuilt.quality_score == original.quality_score

    def test_roundtrip_gives_fresh_event_queue(self) -> None:
        original = Job(job_id="j", query="q")
        rebuilt = _job_from_json(_job_to_json(original))
        assert rebuilt.event_queue.empty()
        # Fresh Queue instance — not the original.
        assert rebuilt.event_queue is not original.event_queue

    async def test_serialize_with_live_resume_event_waiter(self) -> None:
        # ADR 0040 regression: the old `asdict`-based serializer
        # deep-copied `resume_event` BEFORE filtering it out. While
        # the runner awaits `resume_event.wait()` the Event's waiter
        # deque holds a live Future that deepcopy cannot reproduce,
        # so serialization raised TypeError — and the HITL review
        # endpoint 500'd on exactly that call.
        job = Job(job_id="j-paused", query="q")
        waiter = asyncio.ensure_future(job.resume_event.wait())
        await asyncio.sleep(0)  # let the waiter register
        try:
            payload = _job_to_json(job)
        finally:
            waiter.cancel()
        assert '"job_id":"j-paused"' in payload

    def test_from_json_ignores_unknown_keys(self) -> None:
        # Forward compatibility: a payload written by a newer worker
        # with an extra field must not crash this build's read path.
        original = Job(job_id="j1", query="q")
        payload = json.loads(_job_to_json(original))
        payload["some_future_field"] = "whatever"
        rebuilt = _job_from_json(json.dumps(payload))
        assert rebuilt.job_id == "j1"
        assert not hasattr(rebuilt, "some_future_field")

    def test_json_keys_match_persistent_fields(self) -> None:
        # The write path derives its keys from `_persistent_fields()`;
        # the read path must accept exactly the same set, so a field
        # added to `Job` round-trips without touching either function.
        payload = json.loads(_job_to_json(Job(job_id="j1", query="q")))
        assert set(payload) == _persistent_fields()


class TestCreateAndGet:
    async def test_create_stores_and_get_returns(
        self, store: RedisJobStore
    ) -> None:
        job = Job(job_id="j1", query="q")
        await store.create(job)
        got = await store.get("j1")
        assert got is not None
        assert got.job_id == "j1"
        assert got.query == "q"

    async def test_get_returns_local_instance_when_available(
        self, store: RedisJobStore
    ) -> None:
        # The local cache is what makes streaming work on the same
        # worker — the fetched Job must be the same instance that
        # owns the live event_queue.
        job = Job(job_id="j1", query="q")
        await store.create(job)
        got = await store.get("j1")
        assert got is job  # same object, not a rehydrated copy

    async def test_get_missing_returns_none(self, store: RedisJobStore) -> None:
        assert await store.get("nope") is None

    async def test_get_across_workers_returns_rehydrated_snapshot(
        self, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # Worker A creates the job (has it in its local cache).
        # Worker B (a second store instance sharing Redis) does not
        # have it locally, so must reconstruct from Redis.
        store_a = RedisJobStore(redis_client)
        store_b = RedisJobStore(redis_client)

        job = Job(
            job_id="j1",
            query="q",
            status=JobStatus.running,
            started_at=1234.0,
        )
        await store_a.create(job)

        got = await store_b.get("j1")
        assert got is not None
        assert got.job_id == "j1"
        assert got.status == JobStatus.running
        # New instance, not the original (which lives on worker A).
        assert got is not job


class TestUpdate:
    async def test_update_replaces_persistent_state(
        self, store: RedisJobStore
    ) -> None:
        job = Job(job_id="j1", query="q")
        await store.create(job)

        job.status = JobStatus.running
        job.started_at = time.time()
        await store.update(job)

        got = await store.get("j1")
        assert got is not None
        assert got.status == JobStatus.running
        assert got.started_at == job.started_at

    async def test_update_sets_ttl_on_terminal_status(
        self, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # Terminal jobs get a TTL so Redis handles retention without
        # an explicit sweeper (matches ADR 0027's design).
        store = RedisJobStore(redis_client, retention_sec=600)
        job = Job(job_id="j1", query="q")
        await store.create(job)

        # Non-terminal: no TTL.
        pre_ttl = await redis_client.ttl(f"{JOB_KEY_PREFIX}j1")
        assert pre_ttl == -1  # -1 = key exists, no TTL

        job.status = JobStatus.succeeded
        job.completed_at = time.time()
        await store.update(job)

        post_ttl = await redis_client.ttl(f"{JOB_KEY_PREFIX}j1")
        assert 0 < post_ttl <= 600

    async def test_retention_zero_disables_ttl(
        self, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # Some operators want jobs to persist forever; retention=0
        # short-circuits the TTL branch.
        store = RedisJobStore(redis_client, retention_sec=0)
        job = Job(
            job_id="j1",
            query="q",
            status=JobStatus.succeeded,
            completed_at=time.time(),
        )
        await store.create(job)
        await store.update(job)
        assert await redis_client.ttl(f"{JOB_KEY_PREFIX}j1") == -1

    async def test_update_preserves_local_cache_instance(
        self, store: RedisJobStore
    ) -> None:
        # After update, get() should still return the same in-memory
        # instance (with its live event_queue), not a rehydrated copy.
        job = Job(job_id="j1", query="q")
        await store.create(job)
        job.status = JobStatus.running
        await store.update(job)
        got = await store.get("j1")
        assert got is job


class TestUpdateDuringHitlPause:
    async def test_update_with_live_resume_waiter_does_not_raise(
        self, store: RedisJobStore
    ) -> None:
        # The review-endpoint path (ADR 0040 P0): while the runner is
        # parked in `await job.resume_event.wait()`, the SAME in-
        # process Job object is written back through `store.update`.
        # With the old asdict serializer this raised TypeError and the
        # review returned 500 with the job wedged in pending_review.
        job = Job(job_id="j1", query="q", status=JobStatus.pending_review)
        await store.create(job)
        waiter = asyncio.ensure_future(job.resume_event.wait())
        await asyncio.sleep(0)  # runner is now "waiting"
        try:
            job.resume_action = "approve"
            await store.update(job)  # must not raise
        finally:
            waiter.cancel()
        got = await store.get("j1")
        assert got is not None
        assert got.resume_action == "approve"


class TestLocalCacheEviction:
    async def test_terminal_update_evicts_local_and_reads_from_redis(
        self, store: RedisJobStore
    ) -> None:
        # ADR 0040: `_local` must not outlive the job. Once terminal,
        # reads come from Redis (rehydrated copy, not the original
        # instance), so the retention TTL and operator deletes are
        # authoritative on the originating worker too.
        job = Job(job_id="j1", query="q")
        await store.create(job)
        job.status = JobStatus.succeeded
        job.completed_at = time.time()
        job.result = "# Report"
        await store.update(job)

        got = await store.get("j1")
        assert got is not None
        assert got is not job  # rehydrated from Redis, not cached
        assert got.status == JobStatus.succeeded
        assert got.result == "# Report"

    async def test_get_returns_none_once_redis_row_is_gone(
        self, store: RedisJobStore, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # Simulates the retention TTL firing (or an operator DEL):
        # the originating worker must 404 like every other worker,
        # not serve a phantom from `_local` forever.
        job = Job(job_id="j1", query="q")
        await store.create(job)
        job.status = JobStatus.failed
        job.completed_at = time.time()
        await store.update(job)
        await redis_client.delete(f"{JOB_KEY_PREFIX}j1")

        assert await store.get("j1") is None

    async def test_running_job_stays_locally_cached(
        self, store: RedisJobStore
    ) -> None:
        # Non-terminal jobs keep the live instance — the event_queue /
        # resume_event must stay reachable while the job runs.
        job = Job(job_id="j1", query="q", status=JobStatus.running)
        await store.create(job)
        await store.update(job)
        assert await store.get("j1") is job


class TestTerminalTransitionGuard:
    async def test_succeeded_cannot_overwrite_failed(
        self, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # ADR 0040 (ADR 0038 follow-up): a redriver that reclaimed a
        # live job wrote `failed/orphaned`; the still-running worker
        # must not resurrect the row as `succeeded` after every SSE
        # client already saw the terminal `job_failed`.
        store_a = RedisJobStore(redis_client, retention_sec=3600)
        store_b = RedisJobStore(redis_client, retention_sec=3600)

        job = Job(job_id="j1", query="q", status=JobStatus.running)
        await store_a.create(job)

        # Peer worker (redriver) marks it failed/orphaned.
        reclaimed = await store_b.get("j1")
        assert reclaimed is not None
        reclaimed.status = JobStatus.failed
        reclaimed.error_type = "orphaned"
        reclaimed.completed_at = time.time()
        await store_b.update(reclaimed)

        # Original worker finishes and tries to write succeeded.
        job.status = JobStatus.succeeded
        job.completed_at = time.time()
        await store_a.update(job)  # refused, absorbed

        got = await store_b.get("j1")
        assert got is not None
        assert got.status == JobStatus.failed
        assert got.error_type == "orphaned"

    async def test_same_terminal_status_rewrite_is_allowed(
        self, store: RedisJobStore
    ) -> None:
        # Idempotent re-persist (e.g. the runner's terminal-write
        # retry) must go through.
        job = Job(job_id="j1", query="q")
        await store.create(job)
        job.status = JobStatus.succeeded
        job.completed_at = time.time()
        await store.update(job)
        job.result = "# Report v2"
        await store.update(job)
        got = await store.get("j1")
        assert got is not None
        assert got.result == "# Report v2"


class TestEvict:
    async def test_evict_is_no_op(self, store: RedisJobStore) -> None:
        # Redis TTL handles retention; the Protocol method exists
        # only for cross-implementation compatibility.
        job = Job(
            job_id="j1",
            query="q",
            status=JobStatus.succeeded,
            completed_at=time.time() - 10_000,
        )
        await store.create(job)
        await store.update(job)
        evicted = await store.evict_older_than(retention_sec=1)
        assert evicted == 0


class TestConcurrency:
    async def test_concurrent_creates_isolated(
        self, store: RedisJobStore
    ) -> None:
        # Redis operations are atomic; parallel create calls should
        # all land without dropping any.
        async def create_one(i: int) -> None:
            await store.create(Job(job_id=f"j{i}", query="q"))

        await asyncio.gather(*(create_one(i) for i in range(50)))
        for i in range(50):
            got = await store.get(f"j{i}")
            assert got is not None
            assert got.job_id == f"j{i}"


class TestClose:
    async def test_close_returns_cleanly(self) -> None:
        # The lifespan calls close() on shutdown; it must not raise
        # even when the client has no pending operations. (Testing
        # "operations after close fail" is really testing the driver;
        # we only own the close-was-invoked contract.)
        store = RedisJobStore(fakeredis.aioredis.FakeRedis())
        await store.close()  # must not raise
