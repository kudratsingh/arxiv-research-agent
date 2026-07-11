"""Tests for `RedisJobStore` against a `fakeredis` client.

Marked `integration` because they exercise the real redis-py client
against an in-process Redis emulator. Fast enough to run on every
PR alongside the unit tier.
"""

from __future__ import annotations

import asyncio
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
