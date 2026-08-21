"""The redrive sweep keeps running after boot (ADR 0053).

ADR 0038 swept once, at startup. That misses the failure leases exist
for: a container SIGKILLed and restarted by `restart: unless-stopped`
inside `job_lease_ttl_sec` comes back to find its own dead lease still
live in Redis. The boot sweep correctly refuses to touch the job — a
live lease is indistinguishable from a healthy peer mid-run — and no
later sweep ever happened, so the row stayed `running` forever and
both `GET /research/{id}` and the SSE stream waited on a terminal
frame nobody would publish.

The loop tests inject `sleep`, so cadence is asserted rather than
waited out. The reclaim test drives the real `RedisJobStore` against
fakeredis and expires the lease *between* two sweeps, which is the
restart timeline in miniature.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

import fakeredis.aioredis
import pytest
from asgi_lifespan import LifespanManager

from src.api import app as app_module
from src.api.app import REDRIVE_JITTER_RATIO, _redrive_forever
from src.api.jobs import Job, JobStatus
from src.api.redis_store import RedisJobStore
from src.api.redriver import JobRedriver, RedriveReport
from src.config import Settings

pytestmark = pytest.mark.integration

INTERVAL = 300.0


class _GatedSleep:
    """A `sleep` the test releases one call at a time.

    Nothing here waits on wall-clock time: the loop parks in `sleep`
    until the test says go, so "one interval elapsed" is a statement
    the test makes rather than a race it hopes to win. `calls` records
    the durations the loop asked for, which is how cadence is checked.
    """

    def __init__(self) -> None:
        self.calls: list[float] = []
        self._entered = asyncio.Event()
        self._resume = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self._entered.set()
        await self._resume.wait()
        self._resume.clear()

    async def wait_until_sleeping(self) -> None:
        """Block until the loop has reached its next `sleep`.

        Everything the loop does between two sleeps — one sweep — is
        therefore complete when this returns.
        """
        await asyncio.wait_for(self._entered.wait(), timeout=5.0)
        self._entered.clear()

    async def advance(self) -> None:
        """Let one interval elapse and wait for the sweep to finish."""
        self._resume.set()
        await self.wait_until_sleeping()


class _RecordingRedriver:
    """Stands in for `JobRedriver`, counting sweeps."""

    def __init__(self, *, raises: BaseException | None = None) -> None:
        self.sweeps = 0
        self._raises = raises
        self.report = RedriveReport()

    async def sweep(self) -> RedriveReport:
        self.sweeps += 1
        if self._raises is not None:
            raise self._raises
        return self.report


async def _start(
    redriver: Any, sleeper: _GatedSleep, interval: float = INTERVAL
) -> asyncio.Task[None]:
    """Start the loop and hand it back parked in its jitter sleep."""
    task = asyncio.create_task(
        _redrive_forever(redriver, interval, sleep=sleeper)
    )
    await sleeper.wait_until_sleeping()
    return task


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


class TestCadence:
    async def test_first_wait_is_a_jittered_fraction_of_the_interval(
        self,
    ) -> None:
        # Every worker in a fleet boots on the same `docker compose
        # up`; an unjittered timer would put every sweep on the same
        # second, so all but one would find the redrive lock taken.
        sleeper = _GatedSleep()
        task = await _start(_RecordingRedriver(), sleeper)
        await sleeper.advance()
        await _cancel(task)

        jitter = sleeper.calls[0]
        assert 0.0 <= jitter <= INTERVAL * REDRIVE_JITTER_RATIO
        # And the phase offset is *extra* — it does not eat into the
        # interval that follows it.
        assert sleeper.calls[1] == INTERVAL

    async def test_sweeps_once_per_interval(self) -> None:
        redriver = _RecordingRedriver()
        sleeper = _GatedSleep()
        task = await _start(redriver, sleeper)

        await sleeper.advance()  # jitter elapses; no sweep yet
        assert redriver.sweeps == 0
        for expected in (1, 2, 3):
            await sleeper.advance()
            assert redriver.sweeps == expected
        await _cancel(task)

        assert sleeper.calls[1:] == [INTERVAL, INTERVAL, INTERVAL, INTERVAL]

    async def test_never_sweeps_before_the_first_interval(self) -> None:
        # The startup sweep has already run by the time this task
        # exists; sweeping immediately would only re-take the lock for
        # a keyspace just examined.
        redriver = _RecordingRedriver()
        sleeper = _GatedSleep()
        task = await _start(redriver, sleeper)

        await sleeper.advance()
        assert redriver.sweeps == 0
        assert sleeper.calls[1] == INTERVAL
        await _cancel(task)


class TestFailuresDoNotStopTheLoop:
    async def test_a_failing_sweep_is_retried_next_interval(self) -> None:
        # Reconciliation is best-effort housekeeping; a redriver bug
        # (or a Redis blip) must not silently end the sweep for the
        # remaining life of the worker.
        redriver = _RecordingRedriver(raises=RuntimeError("redis down"))
        sleeper = _GatedSleep()
        task = await _start(redriver, sleeper)

        await sleeper.advance()
        await sleeper.advance()
        assert redriver.sweeps == 1
        await sleeper.advance()
        assert redriver.sweeps == 2
        assert not task.done()
        await _cancel(task)

    async def test_a_hung_sweep_is_bounded_and_the_loop_continues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A sweep that never returns would otherwise hold the loop for
        # good: no timeout means no sweep after it, ever.
        monkeypatch.setattr(app_module, "REDRIVE_LOCK_TTL_SEC", 0.01)

        class _HangingRedriver(_RecordingRedriver):
            async def sweep(self) -> RedriveReport:
                self.sweeps += 1
                if self.sweeps == 1:
                    await asyncio.Event().wait()
                return RedriveReport()

        redriver = _HangingRedriver()
        sleeper = _GatedSleep()
        task = await _start(redriver, sleeper)

        await sleeper.advance()
        # The hung sweep: `advance` returns only once the loop is back
        # at its next sleep, which can only happen via the timeout.
        await sleeper.advance()
        assert redriver.sweeps == 1
        await sleeper.advance()
        assert redriver.sweeps == 2
        assert not task.done()
        await _cancel(task)

    async def test_cancellation_is_prompt(self) -> None:
        # Shutdown cancels this task; swallowing `CancelledError` in
        # the "failures never break the loop" handler would turn the
        # loop into an unkillable one and hang the shutdown.
        sleeper = _GatedSleep()
        task = await _start(_RecordingRedriver(), sleeper)
        await sleeper.advance()
        await _cancel(task)
        assert task.cancelled()


class TestReclaimAfterBoot:
    async def test_lease_that_expires_after_boot_is_reclaimed(self) -> None:
        """The restart timeline, compressed into two sweeps.

        Sweep 1 stands in for the boot sweep: the dead container's own
        lease is still live, so the job is correctly left alone. The
        lease then expires, and the sweep an interval later reclaims
        it. Before ADR 0053 there was no second sweep and the row
        stayed `running` for good.
        """
        client = fakeredis.aioredis.FakeRedis()
        try:
            store = RedisJobStore(client, retention_sec=3600)
            job = Job(
                job_id="job-restart",
                query="q",
                status=JobStatus.running,
                started_at=time.time() - 60,
            )
            await store.update(job)
            store._local.pop("job-restart", None)
            # The lease the killed container took before it died.
            assert await store.acquire_lease("job-restart", "dead-worker", 60)

            sleeper = _GatedSleep()
            task = await _start(JobRedriver(store, "worker-a"), sleeper)

            await sleeper.advance()  # jitter
            await sleeper.advance()  # sweep 1: the lease is still live
            still_running = await store.get("job-restart")
            assert still_running is not None
            assert still_running.status == JobStatus.running

            # The dead container's lease finally hits its TTL.
            await store.release_lease("job-restart", "dead-worker")

            await sleeper.advance()  # sweep 2: reclaim
            await _cancel(task)

            reclaimed = await store.get("job-restart")
            assert reclaimed is not None
            assert reclaimed.status == JobStatus.failed
            assert reclaimed.error_type == "orphaned"
        finally:
            await client.aclose()


class TestLifespanWiring:
    async def _app(self, store: Any) -> Any:
        return app_module.create_app(
            build_workflow=lambda: MagicMock(name="compiled_workflow"),
            store=store,
        )

    @staticmethod
    def _sweep_tasks() -> list[asyncio.Task[Any]]:
        return [
            t
            for t in asyncio.all_tasks()
            if t.get_name() == "job-redrive-sweep"
        ]

    async def test_task_runs_while_serving_and_is_cancelled_on_shutdown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            app_module,
            "settings",
            Settings(enable_job_redriver=True, job_redrive_interval_sec=300),
        )
        client = fakeredis.aioredis.FakeRedis()
        try:
            api = await self._app(RedisJobStore(client))
            async with LifespanManager(api):
                tasks = self._sweep_tasks()
                assert len(tasks) == 1
                task = tasks[0]
                assert not task.done()
            # Shutdown must not leave it running: an orphaned sweep
            # would keep a store handle alive past teardown.
            assert task.done()
            assert not self._sweep_tasks()
        finally:
            await client.aclose()

    async def test_no_task_when_the_redriver_is_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            app_module, "settings", Settings(enable_job_redriver=False)
        )
        client = fakeredis.aioredis.FakeRedis()
        try:
            api = await self._app(RedisJobStore(client))
            async with LifespanManager(api):
                assert not self._sweep_tasks()
        finally:
            await client.aclose()

    async def test_no_task_for_a_store_that_cannot_be_swept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `InMemoryJobStore` loses everything on restart, so a
        # recurring sweep would burn a task to log
        # `job_redriver_store_unsupported` every few minutes forever.
        from src.api.jobs import InMemoryJobStore

        monkeypatch.setattr(
            app_module, "settings", Settings(enable_job_redriver=True)
        )
        api = await self._app(InMemoryJobStore())
        async with LifespanManager(api):
            assert not self._sweep_tasks()

    async def test_interval_comes_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pins the wiring, not the loop: an app that hard-coded a
        # cadence would make the setting inert.
        seen: list[float] = []

        async def _capture(
            redriver: Any, interval_sec: float, **kwargs: Any
        ) -> None:
            seen.append(interval_sec)
            await asyncio.Event().wait()

        monkeypatch.setattr(app_module, "_redrive_forever", _capture)
        monkeypatch.setattr(
            app_module,
            "settings",
            Settings(enable_job_redriver=True, job_redrive_interval_sec=97),
        )
        client = fakeredis.aioredis.FakeRedis()
        try:
            api = await self._app(RedisJobStore(client))
            async with LifespanManager(api):
                pass
        finally:
            await client.aclose()

        assert seen == [97.0]
