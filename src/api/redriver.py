"""Startup reconciliation for jobs orphaned by a dead worker (ADR 0038).

Under `job_store=redis` a non-terminal job row carries no TTL — the
retention TTL is only applied once the job goes terminal. That is the
right call (a stuck job is a diagnostic signal, not garbage) but it
left a hole: when the worker running a job dies — deploy, crash, OOM,
scale-in — nothing ever reconciles its row. `GET /research/{id}`
keeps answering `running` forever, and `GET /research/{id}/stream`
subscribes to `events:{job_id}` and hangs until the client gives up,
because the terminal frame will never be published.

`JobRedriver.sweep()` closes that hole. `create_app` runs it once per
worker at startup and then keeps sweeping every
`settings.job_redrive_interval_sec` (ADR 0053) — the startup sweep
alone cannot see a lease that outlives the container it belonged to.
The hard part is telling "orphaned" apart from "running on a
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

import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Final
from uuid import uuid4

from src.api.jobs import Job, JobStatus
from src.config import settings
from src.observability import get_logger
from src.observability.metrics import record_job_terminal

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

DEAD_LETTER_ERROR_TYPE: Final[str] = "internal_dead_letter"
"""Terminal give-up: the job used its whole requeue allowance and never ran.

Its own code rather than a reuse of `orphaned`, because the two tell an
operator opposite things. `orphaned` means "a worker died under this
job; resubmitting is expected to work" — which is exactly what the
reclaim message advises. A dead-lettered job has *already* been
resubmitted `job_redrive_max_attempts` times, so repeating that advice
would be a lie, and a dashboard that could not separate the two would
render a poison-message loop as a healthy reclaim rate. ADR 0068;
`02-STANDARDS.md` §5.3 is the rule it follows.
"""


class OrphanOutcome(StrEnum):
    """What the sweep actually managed to do with one orphan.

    `skipped_live` is the ADR 0048 addition: the reclaim's write is a
    compare-and-set, and losing it means the job finished under us
    between the re-read and the write. That is not a failure to
    reclaim — it is proof the job was never an orphan — so it counts
    with the other jobs left alone rather than as a reclaim.

    `dead_lettered` is ADR 0068's: the job was eligible for requeue and
    was refused one, because it has already had its allowance. Counted
    apart from `failed` for the reason above — two different
    operational events wearing the same terminal status.
    """

    requeued = "requeued"
    failed = "failed"
    dead_lettered = "dead_lettered"
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
    so `orphaned == failed + requeued + dead_lettered`. `dead_lettered`
    is the ADR 0068 subset of the reclaims: jobs refused a requeue
    because they had already used their allowance. It is a subset of
    the reclaims and *not* of `failed`, so a sweep that dead-letters
    one job reports `orphaned=1, dead_lettered=1, failed=0` — the row
    is `failed` either way, but the two counters answer different
    questions and merging them would hide a poison-message loop inside
    a normal-looking failure count. `skipped_live` counts jobs
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
    dead_lettered: int = 0
    skipped_live: int = 0
    scan_capped: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Flat mapping for structured log `extra=`."""
        return asdict(self)


def _terminal_event_data(job: Job) -> dict[str, Any]:
    """Terminal SSE frame payload for a reclaimed job.

    A one-line delegate to `src.api.runner.terminal_event_data`, which
    is the single builder every terminal frame in the process now goes
    through (WO-B3).

    It used to be a hand-maintained copy, and its docstring said it was
    "kept field-for-field in sync with `_terminal_event_data` in
    `src/api/routes.py`". Both halves of that sentence had stopped being
    true. `routes.py`'s function had itself become a one-line delegate
    when WO-A10 moved the builder here, so the named authority was a
    forwarder; and the copy was three fields short of it —
    `cost_cap_status`, `cost_cap_message` and `llm_calls` were missing.
    So a client that reconnected to a reclaimed job got a twelve-key
    frame and one that was still subscribed got an eight-key one, for
    the same event on the same job. That is the WO-A10 defect exactly,
    surviving in the one path A10 did not read.

    **Why the import is inside the function.** `src/api/runner.py`
    imports `WORKER_ID` from this module at line 51, so a module-level
    import back would be a cycle. Three ways out were available:
    module-level import in the other direction (would have meant moving
    `WORKER_ID`, a symbol this module owns and the redrive protocol is
    named for), moving `terminal_event_data` to `src/api/jobs.py` beside
    the `Job` it reads (the architecturally cleanest, and it is where
    this belongs once somebody owns that file — it would have to move
    `routes.py`'s import and the two contract tests that name
    `runner.py` as the builder's home), or a deferred import. The
    deferred import is the one that converges the shapes today without
    touching a file this work order does not own, and Python caches the
    module after the first sweep.

    Args:
        job: The reclaimed job, already mutated into its failed state.

    Returns:
        The `data` object for the `job_failed` event.
    """
    from src.api.runner import terminal_event_data

    return terminal_event_data(job)


class JobRedriver:
    """Reclaims jobs whose owning worker died — swept at startup and
    then every `job_redrive_interval_sec` (ADR 0053).

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
        max_attempts: int | None = None,
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
            max_attempts: Requeues one job may receive before it is
                dead-lettered. Defaults to
                `settings.job_redrive_max_attempts`.
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
        self._max_attempts = (
            max_attempts
            if max_attempts is not None
            else settings.job_redrive_max_attempts
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
        orphaned = failed = requeued = dead_lettered = skipped_live = 0

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
                elif outcome is OrphanOutcome.dead_lettered:
                    orphaned += 1
                    dead_lettered += 1
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
            dead_lettered=dead_lettered,
            skipped_live=skipped_live,
            scan_capped=scan_capped,
        )

    async def _handle_orphan(self, job: Job) -> OrphanOutcome:
        """Requeue or fail one orphaned job.

        Only `pending` is eligible for requeue, and only when the
        operator opted in. `running` and the parked statuses
        (`pending_review`, `awaiting_learner`) are always failed: they
        already made LLM calls, so restarting them would bill the
        operator a second time for work that was partly done and is no
        longer recoverable (the intermediate state lived in the dead
        worker's process).

        Note what this method never has to decide (ADR 0057): whether
        a *parked* job is an orphan at all. A live runner sitting in
        `awaiting_learner` is refreshing the job's lease the entire
        time it waits, so `_reconcile`'s `acquire_lease` fails and the
        job is counted `skipped_live` before it ever reaches here — a
        learner taking ten minutes over a passage looks exactly like a
        reviewer taking ten minutes over a plan, which is to say like
        a healthy job. Only a parking whose *worker* died gets this
        far.

        Args:
            job: A non-terminal job with no live lease.

        Returns:
            What happened — requeued, dead-lettered, failed, or
            `skipped_live` when the reclaim's compare-and-set found the
            job had finished after all.
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
            # ADR 0068. The counter is read *before* the resubmit, not
            # after: a job whose resubmit reliably kills its worker
            # never gets to an "after". This is the poison-message
            # bound, and without it `job_redrive_requeue_pending` is an
            # unbounded loop — every sweep finds the same leaseless
            # `pending` row and puts it back.
            attempts = await self._count_requeue(job)
            if attempts is not None and attempts > self._max_attempts:
                return await self._dead_letter(job, attempts)
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

    async def _count_requeue(self, job: Job) -> int | None:
        """Record that this job is about to be requeued, and count it.

        Duck-typed on the store for the same reason `sweep` duck-types
        `scan_jobs`: the counter lives in Redis, and a store that
        cannot hold one — `InMemoryJobStore`, a test double — keeps the
        behaviour it had. That is safe because the loop this bounds is
        only reachable under the Redis store: jobs do not survive the
        restart that produces an orphan anywhere else.

        Args:
            job: Job about to go back in flight.

        Returns:
            Requeues this job has now had, including the one being
            considered, or None when the store cannot count. None means
            "no bound available", and the caller requeues as before —
            an unbounded loop is bad, but refusing to reconcile at all
            because a test double is in play would be worse.
        """
        bump = getattr(self._store, "bump_redrive_attempts", None)
        if not callable(bump):
            return None
        try:
            return int(await bump(job.job_id))
        except Exception:
            # The counter is a guard, not the reconcile. A Redis blip
            # while reading it must not turn a reclaimable job into an
            # exception in the middle of a sweep.
            log.warning(
                "job_redriver_attempt_count_failed",
                extra={"job_id": job.job_id, "worker_id": self._worker_id},
            )
            return None

    async def _dead_letter(self, job: Job, attempts: int) -> OrphanOutcome:
        """Refuse a further requeue and fail the job terminally.

        The classic poison-message shape: a job that reliably kills the
        worker running it is, to every sweep, an orphaned `pending` row
        that deserves another chance. Bounding the chances is the only
        thing that ends it, and the bound has to produce a *distinct*
        terminal state — a job that quietly reports `orphaned` for the
        fourth time is indistinguishable from three unlucky deploys.

        Args:
            job: The job being given up on.
            attempts: Requeues it has now accumulated.

        Returns:
            `dead_lettered` when the write landed, `skipped_live` when
            the compare-and-set showed the job finished after all.
        """
        log.warning(
            "job_redriver_dead_lettered",
            extra={
                "job_id": job.job_id,
                "worker_id": self._worker_id,
                "attempt": attempts,
                "cap": self._max_attempts,
            },
        )
        landed = await self._write_dead_letter(job)
        # Forget the count either way. If the reclaim landed the job is
        # terminal and the counter has nothing left to bound; if it lost
        # the race the job finished on its own, which is the same thing.
        await self._forget_requeue_count(job)
        return OrphanOutcome.dead_lettered if landed else OrphanOutcome.skipped_live

    async def _forget_requeue_count(self, job: Job) -> None:
        """Drop a job's requeue counter, best effort."""
        clear = getattr(self._store, "clear_redrive_attempts", None)
        if not callable(clear):
            return
        with contextlib.suppress(Exception):
            await clear(job.job_id)

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
        return await self._commit_reclaim(job, previous=previous)

    async def _write_dead_letter(self, job: Job) -> bool:
        """Mark a job dead-lettered — the same write, a different name.

        Deliberately not a parameter on `_fail_orphan`. Both this
        assignment and that one are read *structurally*:
        `tests/test_errors.py::TestTheJobVocabulary` parses this module
        for `job.error_type = <constant>` to prove `JOB_ERROR_TYPES` is
        the whole set a run can carry, and
        `web/tests/copy/errorTypeDrift.test.ts` reads the same file to
        prove the frontend has a sentence for each. A code that reached
        the row through a default argument would be invisible to both,
        and the first thing anyone would learn about it is that the
        product renders "The run failed." forever.

        Args:
            job: The job being given up on.

        Returns:
            True if the write landed; False if the CAS showed the job
            had already left the status the sweep acted on.
        """
        previous = job.status
        job.status = JobStatus.failed
        job.completed_at = time.time()
        job.error_type = DEAD_LETTER_ERROR_TYPE
        job.error = (
            f"Job was requeued {self._max_attempts} times without ever "
            f"reaching a terminal state, so it will not be requeued "
            f"again. Something about this job stops the worker running "
            f"it; resubmitting the same query unchanged is expected to "
            f"fail the same way."
        )
        return await self._commit_reclaim(job, previous=previous)

    async def _commit_reclaim(self, job: Job, *, previous: JobStatus) -> bool:
        """Persist a reclaim, count it, and unhang its SSE subscribers.

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
            job: The job, already mutated into its terminal state.
            previous: The status the sweep re-read under its claim,
                which the compare-and-set is against.

        Returns:
            True if the reclaim landed.
        """
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

        # ADR 0049: `_persist_terminal` covers every terminal transition
        # `run_job` makes, but not this one — the worker that owned this
        # job died without reaching any of those branches. Leaving the
        # reclaim uncounted would blind `research_jobs_total` to exactly
        # the failure mode the counter exists for: a crash-looping
        # worker would show as falling throughput and nothing else.
        # Recorded only after the CAS lands, unlike `_persist_terminal`
        # — there the job *is* terminal whether or not the store agrees,
        # here the CAS losing means the real owner finished it and will
        # count it itself.
        #
        # No duration: `completed_at - started_at` on a reclaim spans
        # however long the row sat orphaned before a sweep noticed,
        # which measures the scan interval rather than the work, and
        # would drag the p95 the histogram exists to report.
        record_job_terminal(
            status=job.status.value,
            error_type=job.error_type,
            duration_sec=None,
        )

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
