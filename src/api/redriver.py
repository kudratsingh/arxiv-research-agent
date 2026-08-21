"""Startup reconciliation for jobs orphaned by a dead worker (ADR 0038).

Under `job_store=redis` a non-terminal job row carries no TTL — the
retention TTL is only applied once the job goes terminal. That is the
right call (a stuck job is a diagnostic signal, not garbage) but it
left a hole: when the worker running a job dies — deploy, crash, OOM,
scale-in — nothing ever reconciles its row. `GET /research/{id}`
keeps answering `running` forever, and `GET /research/{id}/stream`
subscribes to `events:{job_id}` and hangs until the client gives up,
because the terminal frame will never be published.

`JobRedriver.sweep()` runs once per worker at startup and closes that
hole. The hard part is telling "orphaned" apart from "running on a
worker that is still alive" — a rolling restart of worker 3 must not
reap the jobs on workers 1 and 2. The `joblease:{job_id}` key added
in `src.api.redis_store` is what makes that decidable: the runner
holds and refreshes a lease for as long as it owns a job, so a
non-terminal job with no lease is one whose owner is gone.

Reclaiming means marking the job `failed` with `error_type=orphaned`
*and* publishing the terminal frame on `events:{job_id}`. The publish
is not an afterthought — it is the half that unhangs the SSE clients
that are still waiting.

Both halves are gated on a compare-and-set (ADR 0048): the reclaim
write only lands while the row still holds the non-terminal status
the sweep re-read under its claim. Without that, a job that finishes
in the gap between the re-read and the write has its `succeeded` row
— report and all — overwritten with `failed/orphaned`, and every
connected client is then told the opposite of the truth.

Nothing here applies to `InMemoryJobStore`: its jobs die with the
process, so there is never anything to reconcile. The sweep detects
that by duck-typing `scan_jobs`, matching how `routes.py` detects
`subscribe_events`.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Final
from uuid import uuid4

from src.api.jobs import Job, JobStatus
from src.config import settings
from src.observability import get_logger

log = get_logger(__name__)

WORKER_ID: Final[str] = uuid4().hex
"""Process-unique worker id, generated once at import.

Both the lease a runner holds and the redrive lock are stamped with
this, so log lines and Redis values point at a specific process. It
lives here rather than on `app.state` because `src.api.runner` needs
the same value without threading it through `run_job`'s call site in
`routes.py`; `create_app` copies it onto `app.state.worker_id` for
request handlers.
"""

# The redrive lock only has to outlive one sweep, which
# `job_redrive_max_scan` already bounds. The TTL exists so a worker
# that dies mid-sweep releases it eventually instead of wedging every
# future deploy; it is not an operator-tuned knob, so it stays a
# constant rather than another settings field.
#
# 30s, down from 120s (ADR 0048). The failure it was making worse: a
# worker killed mid-sweep — which on a deploy is the *likely* way a
# sweep ends — held the lock for two minutes, and its own restart
# then hit `job_redriver_skipped_locked` and skipped reconciliation
# entirely, so nothing got reclaimed until some later boot. The
# obvious alternative (recognise the dead holder and take the lock
# from it) is unavailable: `WORKER_ID` is regenerated per process, so
# a restarted worker cannot identify its own previous incarnation.
#
# Shrinking is safe because the lock is a de-duplication
# optimization, not the safety mechanism. Mutual exclusion on an
# individual job comes from `acquire_lease`'s SET NX plus the re-read
# under that claim; two overlapping sweeps duplicate work but cannot
# double-reclaim. And a sweep is bounded work — at most
# `job_redrive_max_scan` keys, now with the terminal rows filtered
# before their bodies are fetched (ADR 0048) — so 30s is ample for a
# healthy Redis and the cost of being wrong is a redundant scan.
#
# `create_app` reuses this as the `asyncio.wait_for` bound on the
# sweep, so it doubles as the worst-case boot delay against an
# unreachable Redis: also better at 30s.
REDRIVE_LOCK_TTL_SEC: Final[int] = 30

ORPHANED_ERROR_TYPE: Final[str] = "orphaned"


class OrphanOutcome(StrEnum):
    """What the sweep actually managed to do with one orphan.

    `skipped_live` is the ADR 0048 addition: the reclaim's write is a
    compare-and-set, and losing it means the job finished under us
    between the re-read and the write. That is not a failure to
    reclaim — it is proof the job was never an orphan — so it counts
    with the other jobs left alone rather than as a reclaim.
    """

    requeued = "requeued"
    failed = "failed"
    skipped_live = "skipped_live"

ResubmitCallback = Callable[[Job], Awaitable[None]]
"""Hands a reset-to-`pending` job back to the execution path.

Only consulted when `job_redrive_requeue_pending` is on. Supplied by
the caller because the redriver has no access to the workflow, the
semaphore, or the task set that `routes.py` owns.
"""


@dataclass(frozen=True, slots=True)
class RedriveReport:
    """Outcome of one sweep, for logging and for tests to assert on.

    `scanned` counts the non-terminal job rows the store's scan
    returned, not keys examined — terminal rows are filtered inside
    `scan_jobs` (ADR 0048) and never reach the reconcile. `orphaned`
    is the subset that had no live lease and was actually reclaimed,
    so `orphaned == failed + requeued`. `skipped_live` counts jobs
    left alone — because another worker still holds their lease,
    because the re-read under the claim showed them terminal, or
    because the reclaim's compare-and-set lost to the owner finishing
    mid-write. It is the number that proves a rolling restart is not
    reaping healthy work.

    `scan_capped` True means the sweep saw only part of the keyspace
    and its counts must not be read as "everything was reconciled".
    """

    scanned: int = 0
    orphaned: int = 0
    failed: int = 0
    requeued: int = 0
    skipped_live: int = 0
    scan_capped: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Flat mapping for structured log `extra=`."""
        return asdict(self)


def _terminal_event_data(job: Job) -> dict[str, Any]:
    """Terminal SSE frame payload for a reclaimed job.

    Kept field-for-field in sync with `_terminal_event_data` in
    `src/api/routes.py`: a client that reconnects to a reclaimed job
    gets the replayed frame from that function, and a client still
    subscribed gets this one. They have to be the same shape or the
    two paths disagree about what a terminal frame looks like.

    Args:
        job: The reclaimed job, already mutated into its failed state.

    Returns:
        The `data` object for the `job_failed` event.
    """
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "elapsed_sec": job.elapsed_sec(),
        "error": job.error,
        "error_type": job.error_type,
        "iterations": job.iterations,
        "quality_score": job.quality_score,
        "cost_usd": job.cost_usd,
    }


class JobRedriver:
    """Reclaims jobs whose owning worker died, once per startup.

    Safe to construct against any store — `sweep()` no-ops when the
    store cannot enumerate its keyspace, which is the `InMemoryJobStore`
    case.
    """

    def __init__(
        self,
        store: Any,
        worker_id: str = WORKER_ID,
        *,
        max_scan: int | None = None,
        requeue_pending: bool | None = None,
        lock_ttl_sec: int = REDRIVE_LOCK_TTL_SEC,
        resubmit: ResubmitCallback | None = None,
    ) -> None:
        """Wire the redriver to a store and its policy knobs.

        Args:
            store: JobStore instance. Only the Redis variant exposes
                the `scan_jobs` / lease / lock surface the sweep
                needs; anything else makes `sweep()` a no-op.
            worker_id: Id stamped on the redrive lock and log lines.
            max_scan: Key cap for one sweep. Defaults to
                `settings.job_redrive_max_scan`.
            requeue_pending: Whether orphaned `pending` jobs are
                resubmitted rather than failed. Defaults to
                `settings.job_redrive_requeue_pending`.
            lock_ttl_sec: TTL on the cluster-wide redrive lock.
            resubmit: Callback that puts a requeued job back in flight.
                Required for requeue to do anything; without it the
                sweep falls back to failing, never to dropping.
        """
        self._store = store
        self._worker_id = worker_id
        # The claim the sweep puts on an individual job has to be
        # distinguishable from the lease `run_job` takes, even though
        # both originate in this process and would otherwise carry the
        # same `WORKER_ID`. Without the prefix the owner-checked
        # release below could delete a lease a runner on this very
        # worker had just acquired for a requeued job.
        self._claim_token = f"redrive:{worker_id}"
        self._max_scan = (
            max_scan if max_scan is not None else settings.job_redrive_max_scan
        )
        self._requeue_pending = (
            requeue_pending
            if requeue_pending is not None
            else settings.job_redrive_requeue_pending
        )
        self._lock_ttl_sec = lock_ttl_sec
        self._resubmit = resubmit

    async def sweep(self) -> RedriveReport:
        """Reconcile every non-terminal job left behind by a dead worker.

        Returns:
            Counts for the sweep. A zeroed report means either that
            there was nothing to do, that the store does not support
            reconciliation, or that another worker holds the redrive
            lock — the log line distinguishes them.
        """
        scan_jobs = getattr(self._store, "scan_jobs", None)
        claim = getattr(self._store, "acquire_lease", None)
        if not (callable(scan_jobs) and callable(claim)):
            # InMemoryJobStore: nothing survives the restart that just
            # happened, so there is nothing to reconcile. Both halves
            # are checked because the sweep needs to enumerate the
            # keyspace *and* claim a lease per job before touching it.
            log.info(
                "job_redriver_store_unsupported",
                extra={"store": type(self._store).__name__},
            )
            return RedriveReport()

        if not await self._store.try_acquire_redrive_lock(
            self._lock_ttl_sec, token=self._worker_id
        ):
            # Every worker boots at once after a deploy; the loser
            # here would otherwise race the winner to reclaim the same
            # jobs and publish duplicate terminal frames.
            log.info(
                "job_redriver_skipped_locked",
                extra={"worker_id": self._worker_id},
            )
            return RedriveReport()

        try:
            jobs, capped = await scan_jobs(max_scan=self._max_scan)
            report = await self._reconcile(jobs, scan_capped=capped)
        finally:
            await self._store.release_redrive_lock(self._worker_id)

        if report.scan_capped:
            # A truncated sweep must never read as a clean bill of
            # health: jobs past the cap are still stuck.
            log.warning(
                "job_redriver_scan_capped",
                extra={"worker_id": self._worker_id, "max_scan": self._max_scan},
            )
        log.info(
            "job_redriver_swept",
            extra={"worker_id": self._worker_id, **report.as_dict()},
        )
        return report

    async def _reconcile(
        self, jobs: list[Job], *, scan_capped: bool
    ) -> RedriveReport:
        """Apply the reclaim policy to one scanned batch.

        Args:
            jobs: Deserialized job rows from the store's scan.
            scan_capped: Whether the scan stopped at the cap.

        Returns:
            The populated report; not logged here, the caller does that.
        """
        orphaned = failed = requeued = skipped_live = 0

        for job in jobs:
            if job.is_terminal():
                # `scan_jobs` already filters these out (ADR 0048);
                # kept because the store surface is duck-typed and a
                # scan that does hand one over must not be reclaimed.
                # Already reconciled, by its own runner or an earlier
                # sweep — the retention TTL handles it from here.
                continue
            # Claim the job's own lease rather than merely testing it
            # with `has_lease`. A read-then-write leaves a window in
            # which the rightful owner starts up between the check and
            # our `update`, and we would then overwrite a live job's
            # row with `failed` and publish a terminal frame for work
            # that is still running. `acquire_lease` is SET NX, so
            # losing the claim *is* the "someone else owns it" answer.
            if not await self._store.acquire_lease(
                job.job_id, self._claim_token, self._lock_ttl_sec
            ):
                # A live worker holds and refreshes this lease. This is
                # the branch that keeps a rolling restart of one worker
                # from reaping the other workers' queued and running
                # jobs.
                skipped_live += 1
                continue

            # Holding the claim is still not enough to act on `job`:
            # it came out of `scan_jobs`, and the batch is a snapshot.
            # A job that finished normally between the scan and here
            # released its lease on the way out, so our SET NX
            # *succeeds* — and writing the stale snapshot back would
            # overwrite a `succeeded` row with `failed` and destroy
            # `job.result`. Re-read under the claim and act on that.
            fresh = await self._store.get(job.job_id)
            if fresh is None or fresh.is_terminal():
                await self._store.release_lease(
                    job.job_id, self._claim_token
                )
                skipped_live += 1
                continue

            try:
                outcome = await self._handle_orphan(fresh)
                if outcome is OrphanOutcome.requeued:
                    orphaned += 1
                    requeued += 1
                elif outcome is OrphanOutcome.failed:
                    orphaned += 1
                    failed += 1
                else:
                    # The reclaim's CAS lost: the job went terminal
                    # under us between the re-read and the write, so
                    # it was never an orphan. Nothing was written and
                    # nothing was published.
                    skipped_live += 1
            finally:
                # The job is terminal (or handed back to the execution
                # path) by now, so holding its lease any longer would
                # only make the next sweep skip a genuine orphan for a
                # full TTL.
                await self._store.release_lease(job.job_id, self._claim_token)

        return RedriveReport(
            scanned=len(jobs),
            orphaned=orphaned,
            failed=failed,
            requeued=requeued,
            skipped_live=skipped_live,
            scan_capped=scan_capped,
        )

    async def _handle_orphan(self, job: Job) -> OrphanOutcome:
        """Requeue or fail one orphaned job.

        Only `pending` is eligible for requeue, and only when the
        operator opted in. `running` and `pending_review` are always
        failed: they already made LLM calls, so restarting them would
        bill the operator a second time for work that was partly done
        and is no longer recoverable (the intermediate state lived in
        the dead worker's process).

        Args:
            job: A non-terminal job with no live lease.

        Returns:
            What happened — requeued, failed, or `skipped_live` when
            the reclaim's compare-and-set found the job had finished
            after all.
        """
        wants_requeue = (
            job.status == JobStatus.pending and self._requeue_pending
        )
        resubmit = self._resubmit
        if wants_requeue and resubmit is None:
            # Requeue was asked for but no callback was wired. Failing
            # is the honest outcome; silently dropping the job would
            # recreate the exact hang this module exists to close.
            log.warning(
                "job_redriver_requeue_unavailable",
                extra={"job_id": job.job_id, "worker_id": self._worker_id},
            )
        elif wants_requeue and resubmit is not None:
            try:
                await self._requeue(job, resubmit)
            except Exception:
                # A resubmit that blew up leaves the row `pending` with
                # nothing driving it — worse than a clean failure.
                log.exception(
                    "job_redriver_requeue_failed", extra={"job_id": job.job_id}
                )
            else:
                log.info(
                    "job_redriver_requeued",
                    extra={"job_id": job.job_id, "worker_id": self._worker_id},
                )
                return OrphanOutcome.requeued

        if await self._fail_orphan(job):
            return OrphanOutcome.failed
        return OrphanOutcome.skipped_live

    async def _requeue(self, job: Job, resubmit: ResubmitCallback) -> None:
        """Reset a `pending` job to a clean submit state and hand it on.

        The store write happens before the callback so a crash in
        between leaves a resubmittable `pending` row rather than a row
        that claims to be running.

        The sweep's claim on the job is dropped before the hand-off:
        the fresh `run_job` takes the lease with SET NX, so leaving
        our claim in place would push it onto the leaseless path and
        make the next sweep treat the requeued job as an orphan.

        Args:
            job: Orphaned `pending` job.
            resubmit: Callback that puts the job back in flight.

        Raises:
            Exception: whatever the resubmit callback raises; the
                caller turns that into a failure.
        """
        job.status = JobStatus.pending
        job.started_at = None
        job.completed_at = None
        job.error = None
        job.error_type = None
        await self._store.update(job)
        await self._store.release_lease(job.job_id, self._claim_token)
        await resubmit(job)

    async def _write_reclaim(self, job: Job, *, expected: JobStatus) -> bool:
        """Persist the reclaim, but only if the row has not moved on.

        ADR 0048. The claim + re-read pair narrowed the race but did
        not close it: the owning worker can finish between
        `store.get` and this write, and a plain `update` would then
        replace a `succeeded` row (report and all) with
        `failed/orphaned`. `update`'s own guard does not help — it
        only refuses terminal → *different* terminal, and at the
        instant it reads, the row may still be `running`.

        `update_if_status` folds the comparison and the write into one
        WATCH/MULTI/EXEC so there is no instant in between. Stores
        that do not offer it (test doubles, any future backend) fall
        back to the plain write, which is what the code did before.

        Args:
            job: The mutated job to persist.
            expected: The status the sweep re-read under its claim.

        Returns:
            True if the reclaim landed and the caller may publish.
        """
        cas = getattr(self._store, "update_if_status", None)
        if callable(cas):
            landed: bool = bool(await cas(job, expected=expected))
            return landed
        await self._store.update(job)
        return True

    async def _fail_orphan(self, job: Job) -> bool:
        """Mark a job failed and unhang whoever is streaming it.

        The write applies the terminal retention TTL, so the row stops
        living forever. The `job_failed` publish is the other half and
        the more important one: an SSE client subscribed to
        `events:{job_id}` is blocked until a terminal frame arrives,
        and without this it never would.

        Both halves are conditional on the compare-and-set landing
        (ADR 0048). Publishing a `job_failed` for a job that actually
        succeeded would be the worse bug of the two: the row would be
        correct and every connected client would be told the opposite.

        Args:
            job: Orphaned job to reclaim.

        Returns:
            True if the job was reclaimed; False if the CAS showed it
            had already left the status the sweep acted on.
        """
        previous = job.status
        job.status = JobStatus.failed
        job.completed_at = time.time()
        job.error_type = ORPHANED_ERROR_TYPE
        job.error = (
            f"Job was reclaimed while in `{previous.value}`: the worker "
            f"running it exited without publishing a terminal state. "
            f"Reclaimed by worker {self._worker_id}. Resubmit the query "
            f"to retry."
        )
        if not await self._write_reclaim(job, expected=previous):
            log.info(
                "job_redriver_reclaim_lost_race",
                extra={
                    "job_id": job.job_id,
                    "observed_status": previous.value,
                    "worker_id": self._worker_id,
                },
            )
            return False

        publish = getattr(self._store, "publish_event", None)
        if callable(publish):
            try:
                await publish(job.job_id, "job_failed", _terminal_event_data(job))
            except Exception:
                # Don't let one failed publish abort the rest of the
                # sweep — the row is already reconciled, only the live
                # stream misses its close.
                log.warning(
                    "job_redriver_publish_failed", extra={"job_id": job.job_id}
                )

        log.warning(
            "job_redriver_reclaimed",
            extra={
                "job_id": job.job_id,
                "previous_status": previous.value,
                "worker_id": self._worker_id,
            },
        )
        return True
