"""Job model and storage abstraction for API-triggered workflow runs.

`Job` captures a single workflow invocation's lifecycle: the request,
the terminal state, timing, cost, and error (if any). `JobStore` is
the storage protocol the routes and the runner depend on; two
implementations exist — `InMemoryJobStore` below (single worker, the
default) and the Redis-backed `RedisJobStore` in `src.api.redis_store`
(ADR 0027) — selected by `settings.job_store`.

Design in ADR 0025; the second job kind and its parked status in
ADR 0057.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol, get_args

JobKind = Literal["research", "session"]
"""What a job is driving (ADR 0057).

`research` — the arXiv research graph: state in, nodes run, terminal
state out. The only kind that existed before Phase W, and the default
so every pre-existing row and every existing caller keeps meaning what
it meant.

`session` — a guided-read tutoring session (WO-W03): turn-shaped, so
it parks in `awaiting_learner` between turns instead of driving to
termination in one pass.

Deliberately not a `StrEnum` like `JobStatus`: this value crosses the
API boundary as a plain string on `JobDetail.kind`, is stored as one
in Redis, and has no behaviour of its own — the per-kind behaviour
lives in `src.api.runner`'s kind runtimes. `Literal` gets that checked
by mypy at every call site without a wrapper type in between.
"""

JOB_KINDS: frozenset[str] = frozenset(get_args(JobKind))
"""The `JobKind` values, for validating strings off the wire.

Derived from the type rather than restated, so the two cannot drift.
"""

DEFAULT_JOB_KIND: JobKind = "research"
"""What a job is when nothing says otherwise — including rows written
by a worker built before job kinds existed."""


class JobStatus(StrEnum):
    """Terminal + non-terminal states a job can be in.

    `pending`          — accepted, not yet started (queued behind the
                         semaphore).
    `running`          — actively invoking the workflow.
    `pending_review`   — paused at the HITL breakpoint after the planner
                         (ADR 0030). Waiting for a human to review +
                         resume via `POST /research/{id}/review`.
    `awaiting_learner` — a `session` job paused between turns (ADR
                         0057), waiting for the learner's reply. The
                         same parking machinery as `pending_review`,
                         a different human and a different question.
    `succeeded`        — workflow returned; `result` populated.
    `failed`           — workflow raised or timed out; `error` populated.
    `cancelled`        — client called cancel or app is shutting down.
    """

    pending = "pending"
    running = "running"
    pending_review = "pending_review"
    awaiting_learner = "awaiting_learner"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled}
)

PARKED_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.pending_review, JobStatus.awaiting_learner}
)
"""Non-terminal statuses in which a live runner is blocked on a human.

Both are held open by a worker that is very much alive — it is sitting
in `asyncio.wait_for(job.resume_event.wait(), ...)` and refreshing the
job's lease the whole time. The redriver therefore treats a parked job
with a live lease exactly as it treats a `running` one (left alone),
and a parked job whose lease has expired exactly as an orphaned
`running` one (failed, never requeued: the spend already happened).
"""


def _submission_trace_context() -> dict[str, str]:
    """The W3C trace context this job is being submitted under (ADR 0066).

    The default for `Job.trace_context`, and the reason a job's spans
    join the request that asked for it instead of starting N new roots.
    It is a `default_factory` rather than a line in each submit handler
    on purpose: there are several places a `Job` is constructed and one
    of them forgetting would break trace continuity silently, in
    exactly the way that is hardest to notice — the trace would still
    look complete, just smaller.

    The import is deferred because this module is deliberately
    dependency-free: `src.api.jobs` imports nothing from `src/` at
    module scope, and pulling the OTel SDK in at import time to serve a
    field default would undo that for every light consumer. The cost is
    one cached module lookup on the first `Job` in a process.

    Returns:
        A carrier holding `traceparent` (and `tracestate` when a vendor
        set one), or an empty dict when nothing is sampled — which is
        the common case in tests and CLI runs, and which every consumer
        reads as "no parent".
    """
    from src.observability.tracing import inject_trace_context

    return inject_trace_context()


@dataclass
class Job:
    """A single research workflow invocation, tracked over its lifetime.

    `event_queue` is the async fan-out channel the runner writes
    workflow events into and the SSE endpoint reads from. It's an
    `asyncio.Queue` rather than a list so a slow SSE consumer applies
    backpressure to the runner instead of being silently dropped.

    HITL fields (ADR 0030) are transient — `plan` is populated when
    the workflow interrupts after the planner and cleared once
    resumed. `hitl_bypass` mirrors the request field and lets the
    runner skip the pause without checking global settings. The
    `resume_event` is the intra-process signal the review endpoint
    sets to wake the runner; `resume_action` + `resume_plan` carry
    the client's decision, and `resume_payload` carries it for a
    parking whose payload is not a plan (ADR 0057).
    """

    job_id: str
    query: str
    status: JobStatus = JobStatus.pending
    # ADR 0057: which graph this job drives. Defaults to `research`,
    # so every row written before this field existed — and every
    # caller that never mentions it — keeps the behaviour it had.
    kind: JobKind = DEFAULT_JOB_KIND
    # Structured, bounded input for non-research job kinds. W03 stores the
    # selected paper/session spec and Tier-1 learner snapshot here so a
    # session can be redriven on another worker without smuggling JSON into
    # ``query`` or depending on process-local request state. Redis derives
    # its persistent field list from this dataclass, so the payload round-
    # trips automatically and old rows default to an empty mapping.
    input_payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    result: str | None = None
    error: str | None = None
    error_type: str | None = None
    # WO-W06: explicit session-only product outcome. Empty means the cap
    # never bound (and remains the default for every legacy Redis row).
    cost_cap_status: Literal["", "refused", "degraded_close"] = ""
    cost_cap_message: str | None = None
    cost_usd: float | None = None
    llm_calls: int | None = None
    iterations: int | None = None
    quality_score: float | None = None
    hitl_bypass: bool = False
    conversation_id: str | None = None
    plan: dict[str, Any] | None = None
    # ADR 0057: `plan`'s counterpart for a parked session — the turn
    # the learner is being asked to take. Transient in the same way:
    # populated when the session graph interrupts, cleared on resume.
    # It is on the row rather than only in the frame because ADR
    # 0053's attach-time replay needs something to replay from, and a
    # session surviving a page reload is the whole reason the session
    # runs on the job model at all (SR-01).
    turn: dict[str, Any] | None = None
    resume_action: str | None = None
    resume_plan: dict[str, Any] | None = None
    # ADR 0057: the resume body for parkings that are not plan review.
    # `resume_plan` is plan-shaped by name and by the `Plan` schema
    # validating it; a session turn carries the learner's reply, which
    # is neither. Kept as a separate field rather than widening
    # `resume_plan` so the HITL contract stays exactly what it says.
    resume_payload: dict[str, Any] | None = None
    # ADR 0036: owner of the resource under `enable_api_auth`. `None`
    # under auth-off deployments (all callers share one namespace)
    # and on rows written by pre-ADR-0036 code. Ownership checks in
    # `src/api/routes.py` treat `None`-owner rows as invisible when
    # auth is on so legacy data doesn't leak across principals.
    principal_key_id: str | None = None
    # ADR 0066: the trace the job was submitted under, as a W3C
    # carrier. Persisted with the rest of the row — `redis_store`
    # derives its field list from this dataclass — because the worker
    # that runs a job is often not the process that accepted it: a
    # redriven job is picked up by whichever worker swept it (ADR
    # 0038), so a ContextVar could never have carried this. `run_job`
    # attaches it before opening the run's `invoke_workflow` span,
    # which is what makes submit -> node -> model call one trace.
    #
    # A row written before this field existed reconstructs with the
    # factory, which returns an empty carrier in the redriver's own
    # context — an unparented run rather than one wrongly parented on
    # the sweep that found it.
    trace_context: dict[str, str] = field(
        default_factory=_submission_trace_context
    )
    event_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=1024)
    )
    resume_event: asyncio.Event = field(default_factory=asyncio.Event)

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def is_awaiting_review(self) -> bool:
        """True only for plan review — never for a session turn.

        `POST /research/{id}/review` guards on this, and it must stay
        narrow: a session parked in `awaiting_learner` is waiting for
        a learner's answer, not for a plan decision, and resuming it
        through the review endpoint would push an approve/revise/cancel
        action into a graph that has no idea what to do with one.
        """
        return self.status == JobStatus.pending_review

    def is_parked(self) -> bool:
        """True while a live runner is blocked on a human's reply.

        The union of the parked statuses — see `PARKED_STATUSES` for
        why the two belong together everywhere except the review
        endpoint's guard.
        """
        return self.status in PARKED_STATUSES

    def elapsed_sec(self) -> float | None:
        """Wall-clock duration of the job, or None if not yet started."""
        if self.started_at is None:
            return None
        end = self.completed_at if self.completed_at is not None else time.time()
        return round(end - self.started_at, 3)


class JobStore(Protocol):
    """Storage surface for the API. Implementations must be safe to
    call from concurrent asyncio tasks.

    `InMemoryJobStore` (below) is the single-worker default.
    `RedisJobStore` (`src.api.redis_store`, ADR 0027) persists job
    state across process restarts and supports horizontal scaling of
    API workers; it also layers duck-typed extras beyond this Protocol
    — cross-worker HITL resume, event pub/sub, and worker leases
    (ADRs 0034/0035/0038).
    """

    async def create(self, job: Job) -> None: ...

    async def get(self, job_id: str) -> Job | None: ...

    async def update(self, job: Job) -> None: ...

    async def evict_older_than(self, retention_sec: int) -> int: ...


class InMemoryJobStore:
    """Single-process job store. Jobs live in a dict, guarded by a lock.

    Suitable for one uvicorn worker. When the process dies, jobs die
    with it — acceptable for local dev and eval runs (single-digit
    minutes); deployments that need durability + horizontal scaling
    set `job_store=redis` for `RedisJobStore` (ADR 0027).
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create(self, job: Job) -> None:
        async with self._lock:
            self._jobs[job.job_id] = job

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def update(self, job: Job) -> None:
        async with self._lock:
            self._jobs[job.job_id] = job

    async def evict_older_than(self, retention_sec: int) -> int:
        """Drop terminal jobs older than `retention_sec` seconds.

        Returns the number of jobs evicted. Non-terminal jobs are
        never evicted regardless of age — a stuck job is a diagnostic
        signal, not garbage.
        """
        cutoff = time.time() - retention_sec
        async with self._lock:
            to_evict = [
                job_id
                for job_id, job in self._jobs.items()
                if job.is_terminal()
                and (job.completed_at is not None and job.completed_at < cutoff)
            ]
            for job_id in to_evict:
                del self._jobs[job_id]
            return len(to_evict)

    async def all_jobs(self) -> list[Job]:
        """Snapshot of every job — testing hook, not part of the Protocol."""
        async with self._lock:
            return list(self._jobs.values())


async def drain_events(job: Job) -> AsyncIterator[dict[str, Any]]:
    """Yield events from `job.event_queue` until the job is terminal.

    Terminating on `is_terminal()` after draining pending events
    means the SSE consumer sees every event the runner produced,
    then the terminal frame, then a clean close.
    """
    while True:
        try:
            event = await asyncio.wait_for(job.event_queue.get(), timeout=0.5)
        except TimeoutError:
            if job.is_terminal():
                # Drain anything still in the queue after the writer
                # finished, then exit.
                while not job.event_queue.empty():
                    yield job.event_queue.get_nowait()
                return
            continue
        yield event
