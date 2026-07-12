"""Job model and storage abstraction for API-triggered workflow runs.

`Job` captures a single workflow invocation's lifecycle: the request,
the terminal state, timing, cost, and error (if any). `JobStore` is
the storage protocol so this PR's `InMemoryJobStore` can be swapped
for a Redis/Postgres implementation in Sprint 4 PR 3+ without
touching the routes or the runner.

Design in ADR 0025.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class JobStatus(StrEnum):
    """Terminal + non-terminal states a job can be in.

    `pending`        — accepted, not yet started (queued behind the semaphore).
    `running`        — actively invoking the workflow.
    `pending_review` — paused at the HITL breakpoint after the planner (ADR
                       0030). Waiting for a human to review + resume via
                       `POST /research/{id}/review`.
    `succeeded`      — workflow returned; `result` populated.
    `failed`         — workflow raised or timed out; `error` populated.
    `cancelled`      — client called cancel or app is shutting down.
    """

    pending = "pending"
    running = "running"
    pending_review = "pending_review"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_STATUSES: frozenset[JobStatus] = frozenset(
    {JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled}
)


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
    the client's decision.
    """

    job_id: str
    query: str
    status: JobStatus = JobStatus.pending
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    result: str | None = None
    error: str | None = None
    error_type: str | None = None
    cost_usd: float | None = None
    llm_calls: int | None = None
    iterations: int | None = None
    quality_score: float | None = None
    hitl_bypass: bool = False
    conversation_id: str | None = None
    plan: dict[str, Any] | None = None
    resume_action: str | None = None
    resume_plan: dict[str, Any] | None = None
    event_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=1024)
    )
    resume_event: asyncio.Event = field(default_factory=asyncio.Event)

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def is_awaiting_review(self) -> bool:
        return self.status == JobStatus.pending_review

    def elapsed_sec(self) -> float | None:
        """Wall-clock duration of the job, or None if not yet started."""
        if self.started_at is None:
            return None
        end = self.completed_at if self.completed_at is not None else time.time()
        return round(end - self.started_at, 3)


class JobStore(Protocol):
    """Storage surface for the API. Implementations must be safe to
    call from concurrent asyncio tasks.

    The Sprint 4 PR 2 implementation is `InMemoryJobStore`; PR 3+
    swaps this for Redis so job state survives process restarts and
    supports horizontal scaling of API workers.
    """

    async def create(self, job: Job) -> None: ...

    async def get(self, job_id: str) -> Job | None: ...

    async def update(self, job: Job) -> None: ...

    async def evict_older_than(self, retention_sec: int) -> int: ...


class InMemoryJobStore:
    """Single-process job store. Jobs live in a dict, guarded by a lock.

    Suitable for one uvicorn worker. When the process dies, jobs die
    with it — that's fine because the eval / research use cases here
    are short-lived (single-digit minutes), and the Redis-backed
    store in PR 3 gives durability + horizontal scaling.
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
