"""Startup reconciliation of jobs orphaned by a dead worker (ADR 0038).

The bug being closed: under `job_store=redis` a non-terminal job row
carries no TTL, so a worker that dies mid-job leaves it `running`
forever. `GET /research/{id}` keeps answering `running` and the SSE
stream hangs waiting for a terminal frame nobody will ever publish.

Two `RedisJobStore` instances share one `fakeredis` client to stand
in for two workers pointing at the same Redis — the same fixture
idiom as `tests/test_sse_cross_worker.py`. The load-bearing case is
`test_running_job_with_live_lease_is_left_alone`: without the lease
check, a rolling restart of one worker would reap the healthy jobs
running on all the others.

Marked `integration` because it exercises the real redis-py client
against an in-process Redis emulator.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

import fakeredis.aioredis
import pytest

from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.redis_store import (
    REDRIVE_LOCK_KEY,
    RedisJobStore,
    _lease_key,
)
from src.api.redriver import JobRedriver, RedriveReport

pytestmark = pytest.mark.integration

WORKER_A = "worker-a"
WORKER_B = "worker-b"


@pytest.fixture
async def shared_backend() -> fakeredis.aioredis.FakeRedis:
    """One fakeredis client; both `RedisJobStore` instances share it
    to simulate two workers pointing at the same Redis."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
async def store(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> RedisJobStore:
    """The store as seen by the worker that is booting and sweeping."""
    return RedisJobStore(shared_backend, retention_sec=3600)


@pytest.fixture
async def peer_store(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> RedisJobStore:
    """A second worker's view of the same Redis."""
    return RedisJobStore(shared_backend, retention_sec=3600)


async def _seed(
    store: RedisJobStore,
    job_id: str,
    status: JobStatus,
    **overrides: Any,
) -> Job:
    """Write a job row straight to Redis, bypassing the local cache.

    The local instance cache would otherwise hand the sweep the same
    `Job` object the test holds, hiding serialization bugs. A restart
    only ever sees what is actually in Redis, so the tests should too.
    """
    kwargs: dict[str, Any] = {
        "job_id": job_id,
        "query": "does redriver reclaim me",
        "status": status,
        "started_at": time.time() - 60,
    }
    kwargs.update(overrides)
    job = Job(**kwargs)
    await store.update(job)
    # `update` only touches the local cache for jobs this instance
    # created, so nothing to evict — but be explicit: the sweep must
    # read Redis, not a live object the test still holds.
    store._local.pop(job_id, None)
    return job


@pytest.mark.asyncio
async def test_orphaned_running_job_is_reclaimed(store: RedisJobStore) -> None:
    """A `running` row with no lease is the crashed-worker signature."""
    await _seed(store, "job-orphan", JobStatus.running)

    report = await JobRedriver(store, WORKER_A).sweep()

    assert report.orphaned == 1
    assert report.failed == 1
    assert report.requeued == 0

    reclaimed = await store.get("job-orphan")
    assert reclaimed is not None
    assert reclaimed.status == JobStatus.failed
    assert reclaimed.error_type == "orphaned"
    assert reclaimed.completed_at is not None
    assert reclaimed.error is not None
    assert "running" in reclaimed.error


@pytest.mark.asyncio
async def test_running_job_with_live_lease_is_left_alone(
    store: RedisJobStore, peer_store: RedisJobStore
) -> None:
    """Rolling restart: worker B's sweep must not reap worker A's job.

    This is the whole reason leases exist. Worker A is mid-job and
    holding `joblease:{job_id}`; worker B boots and sweeps. Without
    the lease check every healthy job in the fleet would be failed on
    every deploy.
    """
    await _seed(store, "job-live", JobStatus.running)
    assert await peer_store.acquire_lease("job-live", WORKER_A, 60)

    report = await JobRedriver(store, WORKER_B).sweep()

    assert report.skipped_live == 1
    assert report.orphaned == 0
    assert report.failed == 0

    untouched = await store.get("job-live")
    assert untouched is not None
    assert untouched.status == JobStatus.running
    assert untouched.error_type is None


@pytest.mark.asyncio
async def test_queued_pending_job_on_a_live_worker_is_left_alone(
    store: RedisJobStore, peer_store: RedisJobStore
) -> None:
    """A job queued behind a full semaphore is owned, not orphaned.

    `pending` is the status of everything waiting behind
    `api_max_concurrent_jobs`, and that queue is deep exactly when the
    fleet is busy. If `run_job` only took its lease after the
    semaphore, every queued row on every live worker would be
    leaseless — and a peer's startup sweep would fail all of them
    (`job_redrive_requeue_pending` is off by default). The lease has
    to cover the wait, not just the run.
    """
    from src.api.runner import run_job

    job = Job(job_id="job-queued", query="waiting for a slot")
    await store.create(job)

    # A semaphore with no capacity left: `run_job` reaches the wait
    # and stops there, exactly like a job queued under load.
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()

    task = asyncio.create_task(
        run_job(
            job,
            workflow=None,
            store=store,
            semaphore=semaphore,
            worker_id=WORKER_A,
        )
    )
    try:
        for _ in range(100):
            if await peer_store.has_lease("job-queued"):
                break
            await asyncio.sleep(0.01)
        assert await peer_store.has_lease("job-queued")

        report = await JobRedriver(peer_store, WORKER_B).sweep()

        assert report.skipped_live == 1
        assert report.failed == 0
        queued = await peer_store.get("job-queued")
        assert queued is not None
        assert queued.status == JobStatus.pending
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # Cancellation on shutdown must drop the lease, or the row stays
    # unreclaimable for a full TTL after the process is gone.
    assert not await peer_store.has_lease("job-queued")


@pytest.mark.asyncio
async def test_reclaim_holds_the_job_lease_while_it_writes(
    store: RedisJobStore,
) -> None:
    """The reclaim is a claim, not a check.

    Reading `has_lease` and then writing leaves a window: the rightful
    owner can acquire the lease and flip the job to `running` between
    the two, and the sweep's blind `update` then overwrites a live row
    with `failed` and publishes a terminal frame for work still in
    flight. Claiming the lease with SET NX collapses that into one
    atomic step, so the sweep can only write a row it demonstrably
    owns — which is what this asserts, at the moment of the write.
    """
    await _seed(store, "job-claimed", JobStatus.running)

    held_at_write: list[bool] = []
    original_update = store.update

    async def spy_update(job: Job) -> None:
        held_at_write.append(await store.has_lease(job.job_id))
        await original_update(job)

    store.update = spy_update  # type: ignore[method-assign]

    report = await JobRedriver(store, WORKER_B).sweep()

    assert report.failed == 1
    assert held_at_write == [True]
    # And the claim is handed back, so the key is not left blocking a
    # future sweep for the whole lock TTL.
    assert not await store.has_lease("job-claimed")


@pytest.mark.asyncio
async def test_reclaim_publishes_terminal_frame_to_subscriber(
    store: RedisJobStore, peer_store: RedisJobStore
) -> None:
    """The publish is the half that unhangs a still-connected client.

    Subscribe first (pub/sub drops messages with no subscriber), then
    sweep, and assert the subscriber terminates on `job_failed` rather
    than blocking forever.
    """
    await _seed(store, "job-streamed", JobStatus.running)

    received: list[dict[str, Any]] = []

    async def stream_consumer() -> None:
        async for frame in peer_store.subscribe_events("job-streamed"):
            received.append(frame)

    consumer = asyncio.create_task(stream_consumer())
    await asyncio.sleep(0.05)

    await JobRedriver(store, WORKER_B).sweep()
    await asyncio.wait_for(consumer, timeout=1.5)

    assert [f["event"] for f in received] == ["job_failed"]
    data = received[0]["data"]
    assert data["job_id"] == "job-streamed"
    assert data["status"] == "failed"
    assert data["error_type"] == "orphaned"


@pytest.mark.asyncio
async def test_terminal_jobs_are_ignored(store: RedisJobStore) -> None:
    """Already-reconciled rows are none of the redriver's business."""
    await _seed(store, "job-done", JobStatus.succeeded, result="report")
    await _seed(store, "job-dead", JobStatus.failed, error="boom")
    await _seed(store, "job-gone", JobStatus.cancelled)

    report = await JobRedriver(store, WORKER_A).sweep()

    assert report.scanned == 3
    assert report.orphaned == 0
    assert report.failed == 0
    assert report.skipped_live == 0

    done = await store.get("job-done")
    assert done is not None
    assert done.status == JobStatus.succeeded
    assert done.error_type is None


@pytest.mark.asyncio
async def test_pending_job_is_requeued_when_enabled(
    store: RedisJobStore,
) -> None:
    """`pending` did no work and spent nothing, so it can be retried."""
    await _seed(store, "job-queued", JobStatus.pending, started_at=None)

    resubmitted: list[str] = []

    async def resubmit(job: Job) -> None:
        resubmitted.append(job.job_id)

    report = await JobRedriver(
        store, WORKER_A, requeue_pending=True, resubmit=resubmit
    ).sweep()

    assert report.orphaned == 1
    assert report.requeued == 1
    assert report.failed == 0
    assert resubmitted == ["job-queued"]

    requeued = await store.get("job-queued")
    assert requeued is not None
    assert requeued.status == JobStatus.pending
    assert requeued.error_type is None


@pytest.mark.asyncio
async def test_running_job_is_failed_even_when_requeue_enabled(
    store: RedisJobStore,
) -> None:
    """`running` already made LLM calls — restarting double-charges."""
    await _seed(store, "job-mid", JobStatus.running)
    await _seed(store, "job-review", JobStatus.pending_review)

    async def resubmit(job: Job) -> None:  # pragma: no cover - must not run
        raise AssertionError("running/pending_review must never be requeued")

    report = await JobRedriver(
        store, WORKER_A, requeue_pending=True, resubmit=resubmit
    ).sweep()

    assert report.failed == 2
    assert report.requeued == 0
    for job_id in ("job-mid", "job-review"):
        reclaimed = await store.get(job_id)
        assert reclaimed is not None
        assert reclaimed.status == JobStatus.failed
        assert reclaimed.error_type == "orphaned"


@pytest.mark.asyncio
async def test_requeue_without_callback_falls_back_to_failed(
    store: RedisJobStore,
) -> None:
    """No resubmit wired: fail it. Silently dropping recreates the hang."""
    await _seed(store, "job-nocb", JobStatus.pending, started_at=None)

    report = await JobRedriver(
        store, WORKER_A, requeue_pending=True, resubmit=None
    ).sweep()

    assert report.orphaned == 1
    assert report.requeued == 0
    assert report.failed == 1

    reclaimed = await store.get("job-nocb")
    assert reclaimed is not None
    assert reclaimed.status == JobStatus.failed
    assert reclaimed.error_type == "orphaned"


@pytest.mark.asyncio
async def test_redrive_lock_serialises_concurrent_sweeps(
    store: RedisJobStore, peer_store: RedisJobStore
) -> None:
    """Every worker boots at once; only one of them may reclaim.

    Without the lock both sweeps reclaim the same job and publish two
    terminal frames for it. Worker A holding the lock stands in for
    "A is mid-sweep right now".
    """
    await _seed(store, "job-raced", JobStatus.running)
    assert await store.try_acquire_redrive_lock(60, token=WORKER_A)

    blocked = await JobRedriver(peer_store, WORKER_B).sweep()
    assert blocked == RedriveReport()

    untouched = await peer_store.get("job-raced")
    assert untouched is not None
    assert untouched.status == JobStatus.running

    # Once A is done, B's next sweep proceeds normally.
    await store.release_redrive_lock(WORKER_A)
    second = await JobRedriver(peer_store, WORKER_B).sweep()
    assert second.failed == 1


@pytest.mark.asyncio
async def test_redrive_lock_is_released_after_sweep(
    store: RedisJobStore, shared_backend: fakeredis.aioredis.FakeRedis
) -> None:
    """A finished sweep must not wedge the lock for the next worker."""
    await JobRedriver(store, WORKER_A).sweep()
    assert not await shared_backend.exists(REDRIVE_LOCK_KEY)


@pytest.mark.asyncio
async def test_refresh_lease_returns_false_once_stolen(
    store: RedisJobStore,
    peer_store: RedisJobStore,
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    """Owner-checked refresh: the loser learns it lost, atomically.

    A plain GET-then-EXPIRE would extend the thief's lease instead.
    """
    assert await store.acquire_lease("job-lease", WORKER_A, 60)
    assert await store.refresh_lease("job-lease", WORKER_A, 60)

    # Worker A's lease expired and worker B took it over.
    await shared_backend.set(_lease_key("job-lease"), WORKER_B, ex=60)

    assert not await store.refresh_lease("job-lease", WORKER_A, 60)
    assert await peer_store.refresh_lease("job-lease", WORKER_B, 60)

    # A stale owner must not delete the successor's claim either.
    await store.release_lease("job-lease", WORKER_A)
    assert await store.has_lease("job-lease")

    await peer_store.release_lease("job-lease", WORKER_B)
    assert not await store.has_lease("job-lease")


@pytest.mark.asyncio
async def test_in_memory_store_sweep_is_a_no_op() -> None:
    """Nothing survives an `InMemoryJobStore` restart, so nothing to do.

    Detected by duck-typing `scan_jobs`, matching how `routes.py`
    detects `subscribe_events`.
    """
    memory_store = InMemoryJobStore()
    await memory_store.create(Job(job_id="job-mem", query="q"))

    report = await JobRedriver(memory_store, WORKER_A).sweep()

    assert report == RedriveReport()
    still_there = await memory_store.get("job-mem")
    assert still_there is not None
    assert still_there.status == JobStatus.pending


@pytest.mark.asyncio
async def test_startup_lifespan_runs_the_sweep(store: RedisJobStore) -> None:
    """The redriver has to be wired into the lifespan, not just exist.

    Everything else here calls `JobRedriver` directly, which would
    still pass if `create_app` never invoked it — and the hole this
    ADR closes would stay open in production.
    """
    from unittest.mock import MagicMock

    from asgi_lifespan import LifespanManager

    from src.api.app import create_app

    await _seed(store, "job-boot", JobStatus.running)

    app = create_app(build_workflow=MagicMock(), store=store)
    async with LifespanManager(app):
        # Assert inside the lifespan: shutdown closes the shared
        # client, and the store is unusable afterwards.
        assert app.state.worker_id
        reclaimed = await store.get("job-boot")
        assert reclaimed is not None
        assert reclaimed.status == JobStatus.failed
        assert reclaimed.error_type == "orphaned"


@pytest.mark.asyncio
async def test_scan_cap_is_honoured_and_reported(
    store: RedisJobStore,
) -> None:
    """A truncated sweep must not read as a complete reconciliation."""
    for i in range(12):
        await _seed(store, f"job-bulk-{i}", JobStatus.running)

    report = await JobRedriver(store, WORKER_A, max_scan=5).sweep()

    assert report.scan_capped is True
    assert report.scanned == 5
    assert report.failed == 5

    # The rest are still stuck — that is exactly why the cap is
    # surfaced rather than swallowed.
    remaining = [
        job
        for job in [await store.get(f"job-bulk-{i}") for i in range(12)]
        if job is not None and job.status == JobStatus.running
    ]
    assert len(remaining) == 7


@pytest.mark.asyncio
async def test_scan_skips_undeserializable_payload(
    store: RedisJobStore, shared_backend: fakeredis.aioredis.FakeRedis
) -> None:
    """One corrupt row must not abort reconciliation of the rest."""
    await _seed(store, "job-ok", JobStatus.running)
    await shared_backend.set("job:job-corrupt", b"{not json")

    report = await JobRedriver(store, WORKER_A).sweep()

    assert report.scanned == 1
    assert report.failed == 1
    reclaimed = await store.get("job-ok")
    assert reclaimed is not None
    assert reclaimed.status == JobStatus.failed


@pytest.mark.asyncio
async def test_lease_keys_are_not_mistaken_for_job_rows(
    store: RedisJobStore,
) -> None:
    """`joblease:` must stay outside the `job:*` SCAN pattern."""
    await _seed(store, "job-scan", JobStatus.running)
    assert await store.acquire_lease("job-scan", WORKER_A, 60)

    jobs, capped = await store.scan_jobs(max_scan=100)

    assert capped is False
    assert [job.job_id for job in jobs] == ["job-scan"]


class TestRunnerLeaseUpkeep:
    """`run_job`'s lease guard (ADR 0038 part c).

    The guard has to be invisible to stores without a lease surface,
    and has to release on the way out so a finished job is not held
    against a future sweep.
    """

    @pytest.mark.asyncio
    async def test_lease_held_during_run_and_released_after(
        self, store: RedisJobStore
    ) -> None:
        from src.api.runner import _job_lease

        async with _job_lease(store, "job-guard", WORKER_A):
            assert await store.has_lease("job-guard")

        assert not await store.has_lease("job-guard")

    @pytest.mark.asyncio
    async def test_lease_released_on_cancellation(
        self, store: RedisJobStore
    ) -> None:
        """Shutdown cancels in-flight jobs; the lease must not survive."""
        from src.api.runner import _job_lease

        started = asyncio.Event()

        async def body() -> None:
            async with _job_lease(store, "job-cancelled", WORKER_A):
                started.set()
                await asyncio.sleep(30)

        task = asyncio.create_task(body())
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert await store.has_lease("job-cancelled")

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not await store.has_lease("job-cancelled")

    @pytest.mark.asyncio
    async def test_lease_guard_is_a_no_op_without_lease_support(self) -> None:
        from src.api.runner import _job_lease

        async with _job_lease(InMemoryJobStore(), "job-mem", WORKER_A):
            pass  # no store surface to touch; the guard must not raise

    @pytest.mark.asyncio
    async def test_refresh_loop_stops_when_lease_is_lost(
        self,
        store: RedisJobStore,
        shared_backend: fakeredis.aioredis.FakeRedis,
    ) -> None:
        """Losing the lease is logged and stops the loop, not the job."""
        import src.api.runner as runner_module
        from src.api.runner import _refresh_lease_forever

        class _FastSettings:
            job_lease_ttl_sec = 60
            job_lease_refresh_sec = 0

        original = runner_module.settings
        runner_module.settings = _FastSettings()  # type: ignore[assignment]
        try:
            assert await store.acquire_lease("job-steal", WORKER_A, 60)
            await shared_backend.set(_lease_key("job-steal"), WORKER_B)

            await asyncio.wait_for(
                _refresh_lease_forever(
                    store.refresh_lease, "job-steal", WORKER_A
                ),
                timeout=1.0,
            )
        finally:
            runner_module.settings = original


# ---- Store namespacing (ADR 0038) ---------------------------------


@pytest.mark.asyncio
async def test_custom_key_prefix_namespaces_leases_and_the_lock(
    shared_backend: fakeredis.aioredis.FakeRedis,
) -> None:
    """Co-tenant deployments on one Redis must not collide.

    `key_prefix` already namespaced job rows. Leases and the
    cluster-wide redrive lock have to follow it: without that, tenant
    A's sweep takes the single global `redrive:lock` and silences
    tenant B's reconciliation entirely, and either tenant's lease
    would satisfy the other's liveness check for the same job id.
    """
    tenant_a = RedisJobStore(shared_backend, key_prefix="job:")
    tenant_b = RedisJobStore(shared_backend, key_prefix="tenantb:")

    # Same job id in both namespaces — both claims must succeed.
    assert await tenant_a.acquire_lease("shared-id", WORKER_A, 60)
    assert await tenant_b.acquire_lease("shared-id", WORKER_B, 60)

    # And neither tenant's release may drop the other's claim.
    await tenant_a.release_lease("shared-id", WORKER_A)
    assert not await tenant_a.has_lease("shared-id")
    assert await tenant_b.has_lease("shared-id")

    # The redrive lock is per-namespace for the same reason.
    assert await tenant_a.try_acquire_redrive_lock(60, token=WORKER_A)
    assert await tenant_b.try_acquire_redrive_lock(60, token=WORKER_B)

    # The default prefix keeps the historic key names byte-identical,
    # so an in-place upgrade doesn't strand leases under a new name.
    assert tenant_a._lease_key("x") == _lease_key("x")
    assert tenant_a._redrive_lock_key == REDRIVE_LOCK_KEY
    assert tenant_b._redrive_lock_key != REDRIVE_LOCK_KEY


# ---- Requeue wiring (ADR 0038) ------------------------------------


@pytest.mark.asyncio
async def test_app_startup_requeues_an_orphaned_pending_job(
    shared_backend: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`job_redrive_requeue_pending=True` actually puts work back in flight.

    The redriver takes a `resubmit` callback, but a redriver
    constructed without one degrades to failing every orphaned
    `pending` job. That made the setting inert: on by default it
    would have looked like a working feature while quietly destroying
    exactly the jobs it promised to save. This asserts the callback
    `create_app` supplies reaches `run_job` with the reclaimed job.
    """
    from unittest.mock import MagicMock

    from asgi_lifespan import LifespanManager

    from src.api import app as app_module
    from src.api import redriver as redriver_module
    from src.config import Settings

    # A previous generation of workers accepted this job and died
    # before starting it: `pending`, no lease, no partial work.
    seeder = RedisJobStore(shared_backend)
    orphan = Job(job_id="job-requeue", query="what is attention")
    await seeder.update(orphan)

    monkeypatch.setattr(
        redriver_module,
        "settings",
        Settings(job_redrive_requeue_pending=True),
    )
    monkeypatch.setattr(
        app_module, "settings", Settings(enable_job_redriver=True)
    )

    resubmitted: list[Job] = []

    async def _recording_run_job(job: Job, **kwargs: Any) -> None:
        resubmitted.append(job)

    monkeypatch.setattr(app_module, "run_job", _recording_run_job)

    api = app_module.create_app(
        build_workflow=lambda: MagicMock(name="compiled_workflow"),
        store=RedisJobStore(shared_backend),
    )
    async with LifespanManager(api):
        # The sweep spawns the resubmit as a task; let it run.
        for _ in range(5):
            await asyncio.sleep(0)

    assert [j.job_id for j in resubmitted] == ["job-requeue"]
    assert resubmitted[0].status == JobStatus.pending
    # Requeued, not reaped — the row must not have been failed.
    assert resubmitted[0].error_type is None


# ---- Audit follow-ups (ADR 0038) ----------------------------------


@pytest.mark.asyncio
async def test_completed_job_is_not_overwritten_by_a_stale_snapshot(
    store: RedisJobStore,
    shared_backend: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scan batch is a snapshot; the reclaim must re-read.

    A job that finishes normally between the scan and the reconcile
    releases its lease on the way out, so the sweep's `SET NX` claim
    *succeeds* — the claim alone does not prove the owner is gone.
    Writing the snapshot back would replace a `succeeded` row with
    `failed` and destroy the report the user is about to fetch.
    """
    done = Job(job_id="job-raced-done", query="q")
    done.status = JobStatus.succeeded
    done.result = "# The finished report"
    done.completed_at = time.time()
    await store.update(done)

    # What the sweep saw a moment earlier: still running, no result.
    stale = Job(job_id="job-raced-done", query="q")
    stale.status = JobStatus.running

    async def _stale_scan(*, max_scan: int) -> tuple[list[Job], bool]:
        return [stale], False

    monkeypatch.setattr(store, "scan_jobs", _stale_scan)

    report = await JobRedriver(store, WORKER_A).sweep()

    assert report.failed == 0
    assert report.orphaned == 0
    assert report.skipped_live == 1

    after = await store.get("job-raced-done")
    assert after is not None
    assert after.status == JobStatus.succeeded
    assert after.result == "# The finished report"


@pytest.mark.asyncio
async def test_leaseless_run_reacquires_once_redis_recovers() -> None:
    """A Redis blip at acquire must not leave the job reapable for its run.

    The keeper starts even when the initial acquire raised, retrying
    the claim each tick instead of refreshing a key it does not hold.
    """
    from src.api import runner as runner_module

    calls: list[str] = []
    fail_once = {"n": 1}

    async def acquire(job_id: str, worker_id: str, ttl: int) -> bool:
        calls.append("acquire")
        if fail_once["n"]:
            fail_once["n"] = 0
            raise ConnectionError("redis blip")
        return True

    async def refresh(job_id: str, worker_id: str, ttl: int) -> bool:
        calls.append("refresh")
        return True

    async def release(job_id: str, worker_id: str) -> None:
        calls.append("release")

    class _LeaseStore:
        acquire_lease = staticmethod(acquire)
        refresh_lease = staticmethod(refresh)
        release_lease = staticmethod(release)

    monkeypatch_interval = 0.01
    monkeypatch = pytest.MonkeyPatch()
    fake = type("S", (), {
        "job_lease_ttl_sec": 90,
        "job_lease_refresh_sec": monkeypatch_interval,
    })()
    monkeypatch.setattr(runner_module, "settings", fake)
    try:
        async with runner_module._job_lease(
            _LeaseStore(), "job-blip", WORKER_A  # type: ignore[arg-type]
        ):
            # Long enough for the keeper to tick and re-acquire.
            await asyncio.sleep(0.05)
    finally:
        monkeypatch.undo()

    # First acquire raised, a later one landed — not left leaseless.
    assert calls.count("acquire") >= 2
    assert "release" in calls
