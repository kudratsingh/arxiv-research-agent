"""Tests for `RedisJobStore` against a `fakeredis` client.

Marked `integration` because they exercise the real redis-py client
against an in-process Redis emulator. Fast enough to run on every
PR alongside the unit tier.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import fakeredis.aioredis
import pytest

from src.api.jobs import Job, JobStatus
from src.api.redis_store import (
    JOB_KEY_PREFIX,
    RedisJobStore,
    _job_from_json,
    _job_to_json,
    _lease_key,
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


# ---------------------------------------------------------------------------
# WATCH-abort instrumentation (ADR 0048, correcting ADR 0038)
# ---------------------------------------------------------------------------
#
# ADR 0038 recorded the `WatchError` branch of the store's optimistic
# locking as uncoverable because "fakeredis resolves without true
# concurrency". Re-checked against fakeredis 2.36.2: it is coverable.
# fakeredis marks a watched key dirty on *any* write that lands after
# the WATCH, and redis-py's pipeline holds a connection of its own, so
# a write issued through the ordinary client while the pipeline is
# mid-transaction aborts the EXEC exactly as a real Redis would.
#
# The interloper below drives that deterministically: both
# `_compare_and_apply` and `update_if_status` read the watched key
# inside the WATCH and only then decide what to write, so firing the
# foreign write on that read reproduces the precise window optimistic
# locking exists to lose.


class _InterlopingPipeline:
    """Pipeline wrapper that fires one foreign write after the WATCH."""

    def __init__(
        self,
        pipe: Any,
        interlope: Callable[[], Awaitable[None]],
        watched_key: str | None,
    ) -> None:
        self._pipe = pipe
        self._interlope = interlope
        self._watched_key = watched_key
        self.fired = False

    async def __aenter__(self) -> _InterlopingPipeline:
        await self._pipe.__aenter__()
        return self

    async def __aexit__(self, *exc_info: Any) -> Any:
        return await self._pipe.__aexit__(*exc_info)

    async def get(self, key: Any) -> Any:
        value = await self._pipe.get(key)
        name = key.decode() if isinstance(key, bytes) else str(key)
        if not self.fired and name == self._watched_key:
            self.fired = True
            await self._interlope()
        return value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pipe, name)


class InterlopingClient:
    """Redis client whose WATCH blocks on `watched_key` lose the race.

    Everything except `pipeline()` is the real client; a pipeline that
    reads `watched_key` under a WATCH gets `interlope()` run against
    the same Redis before it reaches EXEC.
    """

    def __init__(
        self,
        client: fakeredis.aioredis.FakeRedis,
        interlope: Callable[[], Awaitable[None]],
        *,
        watched_key: str,
    ) -> None:
        self._client = client
        self._interlope = interlope
        self._watched_key = watched_key
        self.pipelines: list[_InterlopingPipeline] = []

    def pipeline(self, *args: Any, **kwargs: Any) -> _InterlopingPipeline:
        wrapped = _InterlopingPipeline(
            self._client.pipeline(*args, **kwargs),
            self._interlope,
            self._watched_key,
        )
        self.pipelines.append(wrapped)
        return wrapped

    @property
    def fired(self) -> bool:
        """Whether the foreign write actually ran — guards against a
        test that passes because the instrumentation never triggered."""
        return any(p.fired for p in self.pipelines)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


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


class TestLocalCacheDuringOutage:
    """ADR 0048: `_local` must shrink even when Redis will not take
    the terminal write."""

    async def test_local_entry_dropped_when_the_terminal_write_raises(
        self, store: RedisJobStore, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        job = Job(job_id="j1", query="q")
        await store.create(job)
        assert "j1" in store._local

        async def boom(*args: Any, **kwargs: Any) -> None:
            raise ConnectionError("redis is down")

        job.status = JobStatus.succeeded
        job.completed_at = time.time()
        job.result = "# Report"
        redis_client.set = boom  # type: ignore[method-assign]

        with pytest.raises(ConnectionError):
            await store.update(job)

        # The write failed, but the entry is gone: the runner's retry
        # loop is what recovers the row, and until then this worker
        # must not pin the report + Queue + Event forever.
        assert "j1" not in store._local

    async def test_sustained_outage_does_not_grow_the_local_cache(
        self, store: RedisJobStore, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # The failure mode: every terminal persist attempt fails for
        # the duration of an outage, and before ADR 0048 each one left
        # its job behind. Worker memory then grew monotonically for as
        # long as Redis stayed down — an OOM that takes the live jobs
        # with it.
        for i in range(50):
            await store.create(Job(job_id=f"j{i}", query="q"))
        assert len(store._local) == 50

        async def boom(*args: Any, **kwargs: Any) -> None:
            raise ConnectionError("redis is down")

        redis_client.set = boom  # type: ignore[method-assign]
        # `update`'s refusal guard reads before it writes; a downed
        # Redis fails that read too, which must not skip the eviction.
        redis_client.get = boom  # type: ignore[method-assign]

        for i in range(50):
            job = Job(
                job_id=f"j{i}",
                query="q",
                status=JobStatus.failed,
                completed_at=time.time(),
            )
            with pytest.raises(ConnectionError):
                await store.update(job)

        assert store._local == {}


class TestCompareAndSetWrite:
    """`update_if_status` — the redriver's atomic reclaim (ADR 0048)."""

    async def test_write_lands_while_the_status_still_matches(
        self, store: RedisJobStore
    ) -> None:
        job = Job(job_id="j1", query="q", status=JobStatus.running)
        await store.update(job)
        store._local.pop("j1", None)

        job.status = JobStatus.failed
        job.error_type = "orphaned"
        job.completed_at = time.time()
        assert await store.update_if_status(job, expected=JobStatus.running)

        got = await store.get("j1")
        assert got is not None
        assert got.status == JobStatus.failed
        assert got.error_type == "orphaned"

    async def test_write_refused_when_the_row_moved_on(
        self, store: RedisJobStore
    ) -> None:
        # The window `update`'s own guard cannot close: it only
        # refuses terminal -> *different* terminal, so a
        # running -> succeeded transition that happens after the
        # redriver decided to write sails straight through it.
        done = Job(
            job_id="j1",
            query="q",
            status=JobStatus.succeeded,
            result="# The finished report",
            completed_at=time.time(),
        )
        await store.update(done)

        reclaim = Job(
            job_id="j1",
            query="q",
            status=JobStatus.failed,
            error_type="orphaned",
            completed_at=time.time(),
        )
        assert not await store.update_if_status(
            reclaim, expected=JobStatus.running
        )

        got = await store.get("j1")
        assert got is not None
        assert got.status == JobStatus.succeeded
        assert got.result == "# The finished report"

    async def test_write_refused_when_the_row_is_gone(
        self, store: RedisJobStore
    ) -> None:
        # Retention TTL fired or an operator deleted the row. There is
        # nothing to reclaim and re-creating it would resurrect a job
        # the operator removed.
        job = Job(job_id="ghost", query="q", status=JobStatus.failed)
        assert not await store.update_if_status(job, expected=JobStatus.running)
        assert await store.get("ghost") is None

    async def test_write_refused_on_a_corrupt_row(
        self, store: RedisJobStore, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # Unlike `update`'s guard, which lets a corrupt row be
        # overwritten so a job can still be finalized, the CAS refuses:
        # the redriver is acting on a snapshot it can no longer
        # confirm, and its write destroys data.
        await redis_client.set(f"{JOB_KEY_PREFIX}j1", b"{not json")
        job = Job(job_id="j1", query="q", status=JobStatus.failed)
        assert not await store.update_if_status(job, expected=JobStatus.running)

    async def test_terminal_cas_applies_the_retention_ttl(
        self, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # The reclaim path must not leave a terminal row without the
        # TTL — that is the leak the redriver exists to stop.
        store = RedisJobStore(redis_client, retention_sec=600)
        job = Job(job_id="j1", query="q", status=JobStatus.running)
        await store.update(job)
        assert await redis_client.ttl(f"{JOB_KEY_PREFIX}j1") == -1

        job.status = JobStatus.failed
        job.completed_at = time.time()
        assert await store.update_if_status(job, expected=JobStatus.running)
        assert 0 < await redis_client.ttl(f"{JOB_KEY_PREFIX}j1") <= 600

    async def test_terminal_cas_drops_the_local_entry(
        self, store: RedisJobStore
    ) -> None:
        job = Job(job_id="j1", query="q", status=JobStatus.running)
        await store.create(job)
        assert "j1" in store._local

        job.status = JobStatus.failed
        job.completed_at = time.time()
        assert await store.update_if_status(job, expected=JobStatus.running)
        assert "j1" not in store._local

    async def test_concurrent_write_aborts_the_exec(
        self, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # The ADR 0038 "untestable" branch, now covered: the status
        # matched when we read it under the WATCH, and the owning
        # worker finished in the window before the EXEC. Redis aborts,
        # and the reclaim must report that it lost rather than
        # retrying blindly.
        seeder = RedisJobStore(redis_client, retention_sec=3600)
        running = Job(job_id="j1", query="q", status=JobStatus.running)
        await seeder.update(running)

        async def finish_the_job() -> None:
            done = Job(
                job_id="j1",
                query="q",
                status=JobStatus.succeeded,
                result="# Finished in the window",
                completed_at=time.time(),
            )
            await redis_client.set(f"{JOB_KEY_PREFIX}j1", _job_to_json(done))

        client = InterlopingClient(
            redis_client, finish_the_job, watched_key=f"{JOB_KEY_PREFIX}j1"
        )
        store = RedisJobStore(client, retention_sec=3600)  # type: ignore[arg-type]

        reclaim = Job(
            job_id="j1",
            query="q",
            status=JobStatus.failed,
            error_type="orphaned",
            completed_at=time.time(),
        )
        assert not await store.update_if_status(
            reclaim, expected=JobStatus.running
        )
        assert client.fired  # the instrumentation really did run

        got = await seeder.get("j1")
        assert got is not None
        assert got.status == JobStatus.succeeded
        assert got.result == "# Finished in the window"


class TestLeaseCasAbort:
    """The same abort branch on `_compare_and_apply` (ADR 0048)."""

    async def test_refresh_loses_to_a_concurrent_lease_write(
        self, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # A plain GET-then-EXPIRE would read our own token, then
        # extend the *successor's* lease — pinning a job to a worker
        # that no longer owns it. The WATCH is what turns that into a
        # clean False.
        key = _lease_key("job-lease")

        async def steal_the_lease() -> None:
            await redis_client.set(key, "worker-b", ex=60)

        client = InterlopingClient(
            redis_client, steal_the_lease, watched_key=key
        )
        store = RedisJobStore(client)  # type: ignore[arg-type]
        assert await store.acquire_lease("job-lease", "worker-a", 60)

        assert not await store.refresh_lease("job-lease", "worker-a", 5)
        assert client.fired
        # The successor's claim is intact, and untouched by our EXPIRE.
        assert await redis_client.get(key) == b"worker-b"
        assert await redis_client.ttl(key) > 5

    async def test_release_loses_to_a_concurrent_lease_write(
        self, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        key = _lease_key("job-lease")

        async def steal_the_lease() -> None:
            await redis_client.set(key, "worker-b", ex=60)

        client = InterlopingClient(
            redis_client, steal_the_lease, watched_key=key
        )
        store = RedisJobStore(client)  # type: ignore[arg-type]
        assert await store.acquire_lease("job-lease", "worker-a", 60)

        await store.release_lease("job-lease", "worker-a")
        assert client.fired
        # The DELETE must not have landed on the successor's claim.
        assert await redis_client.get(key) == b"worker-b"


class TestTerminalFrameSuppression:
    """ADR 0048: a terminal frame may not contradict the stored row.

    `update` refuses a terminal -> different-terminal overwrite, but
    the caller that lost that race went on to publish its own terminal
    frame regardless, so a client could watch `job_completed` arrive
    after `job_failed` for a job whose stored outcome is `failed` and
    whose result it can never fetch.
    """

    @staticmethod
    def _spy_publishes(
        redis_client: fakeredis.aioredis.FakeRedis,
    ) -> list[tuple[str, str]]:
        published: list[tuple[str, str]] = []
        original = redis_client.publish

        async def spy(channel: Any, message: Any) -> Any:
            name = (
                channel.decode() if isinstance(channel, bytes) else str(channel)
            )
            text = (
                message.decode() if isinstance(message, bytes) else str(message)
            )
            published.append((name, text))
            return await original(channel, message)

        redis_client.publish = spy  # type: ignore[method-assign]
        return published

    async def test_disagreeing_terminal_frame_is_dropped(
        self, store: RedisJobStore, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        reclaimed = Job(
            job_id="j1",
            query="q",
            status=JobStatus.failed,
            error_type="orphaned",
            completed_at=time.time(),
        )
        await store.update(reclaimed)
        published = self._spy_publishes(redis_client)

        await store.publish_event(
            "j1", "job_completed", {"job_id": "j1", "status": "succeeded"}
        )

        assert published == []

    async def test_agreeing_terminal_frame_is_published(
        self, store: RedisJobStore, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        done = Job(
            job_id="j1",
            query="q",
            status=JobStatus.succeeded,
            completed_at=time.time(),
        )
        await store.update(done)
        published = self._spy_publishes(redis_client)

        await store.publish_event("j1", "job_completed", {"job_id": "j1"})

        assert [c for c, _ in published] == ["events:j1"]

    async def test_frame_still_published_when_the_row_is_gone(
        self, store: RedisJobStore, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # Retention TTL fired mid-stream. A subscriber blocked on a
        # close signal is strictly worse off without the frame, so
        # "no opinion" means publish.
        published = self._spy_publishes(redis_client)
        await store.publish_event("vanished", "job_failed", {"error": "boom"})
        assert [c for c, _ in published] == ["events:vanished"]

    async def test_frame_still_published_when_the_row_is_not_terminal(
        self, store: RedisJobStore, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # The terminal persist failed outright, so Redis still says
        # `running`. Suppressing here would hang every live client.
        await store.update(Job(job_id="j1", query="q", status=JobStatus.running))
        published = self._spy_publishes(redis_client)
        await store.publish_event("j1", "job_failed", {"error": "boom"})
        assert [c for c, _ in published] == ["events:j1"]

    async def test_non_terminal_frames_are_never_suppressed(
        self, store: RedisJobStore, redis_client: fakeredis.aioredis.FakeRedis
    ) -> None:
        # A late `node_completed` for an already-failed job is noise,
        # not a contradiction — and the check must not add a GET to
        # the per-node hot path.
        await store.update(
            Job(
                job_id="j1",
                query="q",
                status=JobStatus.failed,
                completed_at=time.time(),
            )
        )
        published = self._spy_publishes(redis_client)
        await store.publish_event("j1", "node_completed", {"node": "planner"})
        assert [c for c, _ in published] == ["events:j1"]


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
