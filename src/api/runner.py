"""Async workflow runner used by the API layer.

Drives the compiled LangGraph app through its async surface —
`astream` / `aget_state` / `aupdate_state` — streaming intermediate
`(node, state_delta)` events to SSE consumers, recording final costs
+ metrics, and applying the per-job timeout. The compiled app MUST be
built with `build_workflow(async_checkpointer=True)`: the sync savers
raise `NotImplementedError` from every async method, which is exactly
how the pre-ADR-0040 wiring killed every API job before its first
node ran.

The runner is a plain module function (not a class) because it owns
no state — every input comes from the `Job` and the injected
workflow factory. That makes it trivial to swap for a Redis-backed
worker in Sprint 4 PR 3+.

ADR 0038 adds one piece of bookkeeping on top: for as long as
`run_job` owns a job it holds a lease key on the store and refreshes
it in the background. The lease expiring is how the startup redriver
learns that the worker running a job is gone, without mistaking a
healthy job on another worker for an orphan during a rolling restart.

ADR 0047 adds the other half of the timeout story. Graph nodes are
synchronous, so they run on a thread pool; `asyncio.wait_for` can only
cancel the coroutine waiting on one. The runner therefore carries a
per-job `CancelToken`, sets it on timeout / shutdown, and then holds
the job's semaphore permit until the node thread actually returns.
Only if that bounded drain expires does the permit go back — and the
abandoned thread stays counted in `/healthz`'s `active_jobs` until it
finishes, so the concurrency numbers never claim capacity the process
does not have.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from src.api.jobs import Job, JobStatus, JobStore
from src.api.redriver import WORKER_ID
from src.cancellation import CancelToken, bind_cancel_token, reset_cancel_token
from src.config import settings
from src.graph.state import ResearchState
from src.observability import (
    bind_run_id,
    get_logger,
    reset_run_id,
    start_cost_tracking,
)
from src.observability.costs import RunCosts

log = get_logger(__name__)

# ADR 0035: `_put_event` / `_put_terminal_event` need to reach the
# JobStore to fan out via pub/sub without threading the store
# argument through every call site. Same pattern as
# `_current_costs` in observability.costs. `run_job` sets it on
# entry; the helpers read it.
_current_store: ContextVar[JobStore | None] = ContextVar(
    "current_store", default=None
)

# The terminal frame is every SSE client's close signal and the store
# write on a terminal transition is the job's outcome of record — both
# get a few attempts before the failure is escalated to an ERROR log
# (never an exception: `run_job` promises not to raise).
_TERMINAL_PUBLISH_ATTEMPTS = 3
_TERMINAL_PERSIST_ATTEMPTS = 3

# Ceiling on the SHUTDOWN-path node drain, independent of the
# (larger) `api_job_drain_timeout_sec` the timeout path gets. On
# timeout the permit is the thing being protected, so waiting is
# worth it; at SIGTERM the whole process is going away and the wait
# competes with uvicorn's own graceful drain inside the container's
# `stop_grace_period` (ADR 0042 sizes that chain). A cooperating node
# unwinds at its next LLM call in milliseconds; one already inside an
# Anthropic request would not make it back inside 30s either, so the
# extra patience buys nothing here. See ADR 0047.
SHUTDOWN_DRAIN_SEC = 5.0

WorkflowFactory = Callable[[], Any]
"""Zero-arg callable that returns a compiled LangGraph app.

Consumed by `create_app` at startup — see ADR 0034. Kept as a
public type alias for tests and callers that inject a stub factory
via `create_app(build_workflow=...)`. The runner itself now takes a
pre-compiled `workflow` rather than the factory.
"""


class HitlTimeoutError(Exception):
    """Job sat in `pending_review` past `api_hitl_timeout_sec`."""


class HitlCancelledError(Exception):
    """Client sent `action=cancel` from the review endpoint."""


class CostBudgetExceeded(Exception):
    """Run's accumulated LLM spend crossed ``settings.max_cost_usd``.

    Raised from the runner's ``on_node`` callback between graph nodes
    so the workflow aborts before the next agent invocation. See
    ADR 0033: the supervisor also has its own budget check, but the
    fixed-DAG path has no supervisor — this is the only enforcement
    point that catches both shapes.
    """

    def __init__(self, spent_usd: float, cap_usd: float) -> None:
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
        super().__init__(
            f"per-run cost ${spent_usd:.4f} exceeded cap ${cap_usd:.2f}"
        )


def _initial_state(
    query: str, run_id: str, *, prior_context: str = ""
) -> ResearchState:
    """Fresh `ResearchState` — same shape used by the eval runner.

    Kept inline (rather than reusing `src.eval.runner._initial_state`)
    so the API layer doesn't import the eval module; those two paths
    should not couple.

    `prior_context` is the ADR-0032 conversation-follow-up
    hook — retrieved chunks land here before the planner runs.
    """
    return {
        "run_id": run_id,
        "query": query,
        "sub_questions": [],
        "search_queries": [],
        "papers": [],
        "paper_analyses": [],
        "draft_report": "",
        "citations": [],
        "critique": "",
        "quality_score": 0.0,
        "revision_needed": False,
        "revision_target": "",
        "iteration": 0,
        "next_action": "",
        "loop_iterations": 0,
        "stop_reason": "",
        "verified": False,
        "unsupported_claims": [],
        "missing_evidence": [],
        "verifier_recommendation": "",
        "evidence": [],
        "tried_search_queries": [],
        "reader_analysis_complete": True,
        "reader_missing_context": "",
        "reader_requested_sections": [],
        "prior_context": prior_context,
        "messages": [],
    }


async def _put_event(job: Job, event: str, data: dict[str, Any]) -> None:
    """Emit an event to whichever SSE delivery mechanism is active.

    Two paths, selected by the store on the current context:

    - **Store advertises `publish_event`** (RedisJobStore under
      ADR 0035): fan out to `events:{job_id}` pub/sub. The local
      queue is bypassed — under multi-worker uvicorn the runner's
      queue has no consumer, and filling it to `maxsize=1024`
      then hitting the blocking `_put_terminal_event` would
      deadlock the runner.
    - **No pub/sub method** (InMemoryJobStore): fall back to the
      original queue-based fan-out with drop-oldest on QueueFull
      so a slow SSE consumer can't stall the runner.
    """
    store = _current_store.get()
    publish = getattr(store, "publish_event", None) if store else None
    if callable(publish):
        try:
            await publish(job.job_id, event, data)
        except Exception:
            # A dropped intermediate frame degrades the stream but not
            # the job; it must be visible in logs, not silent — every
            # other error path in this codebase logs (audit P3).
            log.warning(
                "sse_publish_failed",
                extra={"job_id": job.job_id, "event": event},
                exc_info=True,
            )
        return

    try:
        job.event_queue.put_nowait({"event": event, "data": data})
    except asyncio.QueueFull:
        with contextlib.suppress(asyncio.QueueEmpty):
            job.event_queue.get_nowait()
        try:
            job.event_queue.put_nowait({"event": event, "data": data})
        except asyncio.QueueFull:
            log.warning("event_queue_full_dropped", extra={"job_id": job.job_id})


async def _put_terminal_event(job: Job, event: str, data: dict[str, Any]) -> None:
    """Emit a terminal frame — the SSE close signal.

    Under the pub/sub path the subscriber terminates on the
    terminal event name, so the fan-out is enough — and because a
    dropped terminal frame leaves every connected SSE client hanging
    with no close signal, the publish is retried a few times and the
    final give-up is an ERROR, not silence (audit P3). Under the
    queue-based path we do a blocking `put()` because the terminal
    frame must not be dropped: the SSE consumer keeps the
    connection open until it arrives.
    """
    store = _current_store.get()
    publish = getattr(store, "publish_event", None) if store else None
    if callable(publish):
        for attempt in range(1, _TERMINAL_PUBLISH_ATTEMPTS + 1):
            try:
                await publish(job.job_id, event, data)
                return
            except Exception:
                log.warning(
                    "sse_terminal_publish_failed",
                    extra={
                        "job_id": job.job_id,
                        "event": event,
                        "attempt": attempt,
                    },
                    exc_info=True,
                )
                if attempt < _TERMINAL_PUBLISH_ATTEMPTS:
                    await asyncio.sleep(0.1 * attempt)
        log.error(
            "sse_terminal_publish_gave_up",
            extra={"job_id": job.job_id, "event": event},
        )
        return

    await job.event_queue.put({"event": event, "data": data})


def _enforce_cost_cap(costs: RunCosts, cap_usd: float) -> None:
    """Raise `CostBudgetExceeded` when the run's spend crosses the cap.

    Called between graph nodes from the runner's `on_node` callback.
    The cap comes from `settings.max_cost_usd`; passing it in
    explicitly (rather than reading `settings` here) keeps this
    helper unit-testable without env-var gymnastics.
    """
    spent = costs.total_cost_usd
    if spent >= cap_usd:
        raise CostBudgetExceeded(spent_usd=spent, cap_usd=cap_usd)


def _extract_final_metrics(state: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields that end up in the `JobDetail` response."""
    return {
        "iterations": state.get("iteration"),
        "quality_score": state.get("quality_score"),
    }


async def _invoke_streaming(
    workflow: Any,
    initial_state: ResearchState,
    run_id: str,
    on_node: Callable[[str, dict[str, Any]], Awaitable[None]],
    *,
    job: Job | None = None,
    store: JobStore | None = None,
) -> dict[str, Any]:
    """Run the pre-compiled workflow, honoring the HITL breakpoint.

    `astream` yields `{node_name: state_update}` after each node. When
    `settings.enable_hitl` is on, the compiled workflow interrupts
    after the planner (ADR 0030); we detect that via
    `workflow.aget_state(config).next`, transition the job to
    `pending_review`, emit `plan_ready`, and wait on
    `job.resume_event`. On resume, optionally apply edits via
    `workflow.aupdate_state`, then stream on from the checkpoint.

    Resume runs in a LOOP, not a single second pass: LangGraph re-arms
    `interrupt_after=["planner"]` on *every* planner execution, so a
    critic-driven re-plan parks the graph at a fresh interrupt. Only
    the FIRST pause is a human review (ADR 0030's one-review-per-query
    intent); later pauses auto-resume with no `plan_ready`. Without
    the loop, a twice-re-planned job would end at an unresumed
    interrupt and ship the rejected draft as `succeeded` — the exact
    truncation the audit demonstrated. The loop is bounded by the
    critic's own `max_iterations` cap plus margin; overrunning it
    means the graph and runner disagree structurally, which must fail
    the job loudly rather than truncate it silently.

    The final state is read from the checkpoint (`aget_state.values`),
    never from a trailing `invoke` — invoking with a non-None input on
    an existing thread re-executes the whole graph from START, which
    silently doubled every LLM call on the no-interrupt path. With
    checkpointing disabled there is no state to read back, so the
    node updates are folded together as the fallback.

    `job` + `store` are required for the HITL path but optional so
    programmatic callers still work. Bypassing HITL when the workflow
    is compiled with an interrupt: the runner just resumes immediately
    without waiting.

    The workflow is pre-compiled at app startup and shared across
    jobs (ADR 0034) — previously we re-compiled per job, which
    opened a fresh checkpointer connection every time and never
    cleaned it up until process exit.
    """
    app = workflow
    config = {"configurable": {"thread_id": run_id}}

    # Fallback final state for checkpointing-disabled runs, where
    # `aget_state` has nothing to answer from. Plain dict-merge is
    # accurate for every field the runner reads (scalars +
    # draft_report); reducer-managed fields like `messages` are not
    # consumed from here.
    merged: dict[str, Any] = dict(initial_state)

    # ADR 0030 intends one human review per query; every extra planner
    # run re-arms the interrupt and is auto-resumed. `+ 2` margin: the
    # initial planner run plus one defensive slot beyond the critic's
    # own `max_iterations` force-approve.
    max_pauses = settings.max_iterations + 2
    pauses = 0
    stream_input: Any = initial_state
    while True:
        async for chunk in app.astream(stream_input, config=config):
            for node_name, state_update in chunk.items():
                if node_name == "__interrupt__":
                    # LangGraph's interrupt sentinel — its payload is
                    # a tuple of `Interrupt` objects, not a state
                    # update. The pause itself is detected below via
                    # `aget_state(config).next`.
                    continue
                merged.update(state_update)
                await on_node(node_name, state_update)

        try:
            workflow_state = await app.aget_state(config)
        except ValueError as exc:
            # LangGraph's "No checkpointer set" — nothing can
            # interrupt, and the merged updates are the only final
            # state there is. Match the sentinel narrowly: any OTHER
            # ValueError from a real checkpointer read (e.g. corrupt
            # checkpoint deserialization) must fail the job, not get
            # silently reported as a success built from partial state.
            if "no checkpointer" not in str(exc).lower():
                raise
            return merged

        if not getattr(workflow_state, "next", ()):
            return dict(workflow_state.values)

        pauses += 1
        if pauses > max_pauses:
            raise RuntimeError(
                f"workflow still interrupted after {max_pauses} resumes "
                f"(thread_id={run_id}); refusing to report a paused "
                "graph as a finished job"
            )
        if pauses == 1:
            await _handle_hitl_pause(app, config, workflow_state, job, store)
        else:
            log.info(
                "api_job_interrupt_auto_resumed",
                extra={"thread_id": run_id, "pause_number": pauses},
            )
        # Resume from checkpoint — `None` input means "continue from
        # where we paused"; anything else would restart the graph.
        stream_input = None


async def _handle_hitl_pause(
    app: Any,
    config: dict[str, Any],
    workflow_state: Any,
    job: Job | None,
    store: JobStore | None,
) -> None:
    """Bridge the pause: populate `job.plan`, emit `plan_ready`, wait
    on the resume signal, optionally apply edits.

    No-op when `job` is None (called from eval / programmatic
    paths that shouldn't pause). When `job.hitl_bypass` is True the
    runner resumes immediately without emitting a review event.

    ADR 0034: when the store advertises a `watch_for_remote_resume`
    method (`RedisJobStore` does), spawn a subscription task
    alongside the local `resume_event` await. That's what lets a
    review submitted to worker B wake the runner sitting on
    worker A. Single-worker deployments and in-memory stores skip
    the subscription and just await the local event.
    """
    if job is None:
        return
    if job.hitl_bypass:
        # Compiled interrupt is unconditional; caller opted out.
        return

    plan_values = {
        "sub_questions": list(workflow_state.values.get("sub_questions", [])),
        "search_queries": list(workflow_state.values.get("search_queries", [])),
    }
    job.plan = plan_values
    job.status = JobStatus.pending_review
    if store is not None:
        await store.update(job)
    await _put_event(
        job,
        "plan_ready",
        {"job_id": job.job_id, "plan": plan_values},
    )
    log.info(
        "api_job_pending_review",
        extra={"job_id": job.job_id, **_plan_shape(plan_values)},
    )

    subscription: asyncio.Task[None] | None = None
    watch = getattr(store, "watch_for_remote_resume", None) if store else None
    if callable(watch):
        subscription = asyncio.create_task(
            watch(job), name=f"hitl-resume-{job.job_id}"
        )

    try:
        try:
            await asyncio.wait_for(
                job.resume_event.wait(),
                timeout=settings.api_hitl_timeout_sec,
            )
        except TimeoutError as exc:
            raise HitlTimeoutError(
                f"pending_review exceeded {settings.api_hitl_timeout_sec}s"
            ) from exc
    finally:
        if subscription is not None:
            subscription.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await subscription

    if job.resume_action == "cancel":
        raise HitlCancelledError("client cancelled during plan review")

    if job.resume_action == "revise" and job.resume_plan:
        await app.aupdate_state(config, job.resume_plan)
        log.info(
            "api_job_plan_revised",
            extra={"job_id": job.job_id, **_plan_shape(job.resume_plan)},
        )

    # Back to running for the resume path.
    job.status = JobStatus.running
    job.plan = None
    job.resume_event.clear()
    if store is not None:
        await store.update(job)


def _plan_shape(plan: dict[str, Any]) -> dict[str, Any]:
    """Compact plan summary for logs — just counts, no user text."""
    return {
        "n_sub_questions": len(plan.get("sub_questions", []) or []),
        "n_search_queries": len(plan.get("search_queries", []) or []),
    }


async def _drain_node_threads(
    cancel_token: CancelToken,
    job: Job,
    *,
    reason: str,
    max_budget_sec: float | None = None,
) -> list[str]:
    """Wait for this job's in-flight node threads to return (ADR 0047).

    Called from the timeout and shutdown handlers, *inside* the
    semaphore block, and that placement is the whole point:
    `asyncio.wait_for` only cancels the awaiting coroutine, so the
    synchronous graph node — an LLM call, a PDF parse — keeps running
    on the node pool. Releasing the permit at that moment would leave
    `api_max_concurrent_jobs` bounding coroutines while the real
    thread count climbs, which is the accounting lie this closes.

    The caller must have set `cancel_token` first; nothing here stops a
    thread that never checks it.

    Args:
        cancel_token: This job's token, already cancelled.
        job: Job being drained; only used for log attribution.
        reason: Why we are draining (`job_timeout` / `shutdown`), for
            the log line.
        max_budget_sec: Optional ceiling applied on top of
            `settings.api_job_drain_timeout_sec`. The shutdown path
            passes `SHUTDOWN_DRAIN_SEC` so a generous runtime budget
            cannot overrun the container's SIGTERM grace period.

    Returns:
        Names of the nodes still running when the budget expired — the
        zombies this worker gave up on, already registered in the
        process-wide abandoned count. Empty on the happy path.
    """
    running = cancel_token.running_nodes()
    if not running:
        # Nothing was executing off-loop (the common case: the graph
        # was between nodes, or waiting on the HITL event). Read the
        # settings budget only past this point so a store-level stub
        # without the field can't turn a clean timeout into a raise.
        return []

    budget = float(settings.api_job_drain_timeout_sec)
    if max_budget_sec is not None:
        budget = min(budget, max_budget_sec)
    started = time.monotonic()
    still_running = await cancel_token.drain(budget)
    abandoned = cancel_token.abandon() if still_running else []
    drain_sec = round(time.monotonic() - started, 3)

    if not abandoned:
        log.info(
            "api_job_node_drain_completed",
            extra={
                "job_id": job.job_id,
                "reason": reason,
                "nodes": running,
                "drain_sec": drain_sec,
            },
        )
        return []

    # The permit is about to be released with work still running. Name
    # the zombie: this is the line on-call needs when a worker's
    # thread count and its `active_jobs` disagree.
    log.warning(
        "api_job_node_drain_expired",
        extra={
            "job_id": job.job_id,
            "reason": reason,
            "nodes": abandoned,
            "drain_budget_sec": budget,
        },
    )
    return abandoned


async def _persist_terminal(store: JobStore, job: Job) -> None:
    """Write a terminal `Job` state, absorbing store failures.

    Every terminal transition in `run_job` goes through here rather
    than a bare `store.update`: a Redis blip on the *last* write used
    to either lose the finished report (success path, exception
    escaping `run_job` entirely) or leave the job wedged non-terminal
    with its SSE clients hanging (failure paths). The write is retried
    a few times; on final failure the job's outcome is logged in full
    as `api_job_terminal_persist_failed` so the result is recoverable
    from logs, and the terminal SSE frame still goes out.
    """
    for attempt in range(1, _TERMINAL_PERSIST_ATTEMPTS + 1):
        try:
            await store.update(job)
            return
        except Exception:
            log.warning(
                "api_job_terminal_persist_retry",
                extra={
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "attempt": attempt,
                },
                exc_info=True,
            )
            if attempt < _TERMINAL_PERSIST_ATTEMPTS:
                await asyncio.sleep(0.1 * attempt)
    log.error(
        "api_job_terminal_persist_failed",
        extra={
            "job_id": job.job_id,
            "status": job.status.value,
            "error": job.error,
            "error_type": job.error_type,
            # The full report so a lost success write is recoverable.
            "result": job.result,
        },
    )


async def _refresh_lease_forever(
    refresh: Callable[[str, str, int], Awaitable[bool]],
    job_id: str,
    worker_id: str,
    *,
    acquire: Callable[[str, str, int], Awaitable[bool]] | None = None,
) -> None:
    """Re-expire this worker's job lease until cancelled (ADR 0038).

    Runs as a background task for the lifetime of `run_job`. Losing
    the lease means a redriver already decided this job was orphaned
    and reclaimed it. We log that and stop refreshing, but we do not
    kill the run: aborting a job that is genuinely still making
    progress trades one bad outcome for a strictly worse one, and the
    reclaim already published a terminal frame either way.

    A transient Redis error is not a lost lease, so those keep
    looping — the TTL has room for several missed refreshes.

    Args:
        refresh: The store's owner-checked `refresh_lease`.
        job_id: Job whose lease this task owns.
        worker_id: This process's id, checked against the stored owner.
        acquire: Set when the initial acquire raised, meaning we are
            running *without* a lease and are reapable by any peer's
            sweep. The keeper then retries the acquire each tick until
            it lands, at which point it reverts to refreshing. Left
            `None` on the normal path, where the lease is already held.
    """
    ttl_sec = settings.job_lease_ttl_sec
    interval = settings.job_lease_refresh_sec

    # Set when we entered leaseless after a failed acquire; cleared
    # the moment a retry lands.
    pending_acquire = acquire

    while True:
        await asyncio.sleep(interval)
        if pending_acquire is not None:
            # Still leaseless. Retry the claim rather than refreshing
            # a key we do not hold.
            try:
                if bool(await pending_acquire(job_id, worker_id, ttl_sec)):
                    pending_acquire = None
                    log.info(
                        "job_lease_acquired_late",
                        extra={"job_id": job_id, "worker_id": worker_id},
                    )
            except Exception:
                log.warning(
                    "job_lease_acquire_error",
                    extra={"job_id": job_id, "worker_id": worker_id},
                )
            continue
        try:
            still_ours = bool(await refresh(job_id, worker_id, ttl_sec))
        except Exception:
            log.warning(
                "job_lease_refresh_error",
                extra={"job_id": job_id, "worker_id": worker_id},
            )
            continue
        if not still_ours:
            log.warning(
                "job_lease_lost",
                extra={"job_id": job_id, "worker_id": worker_id},
            )
            return


@contextlib.asynccontextmanager
async def _job_lease(
    store: JobStore, job_id: str, worker_id: str
) -> AsyncIterator[None]:
    """Hold `joblease:{job_id}` for as long as this worker runs the job.

    The lease is the liveness proof `src.api.redriver` checks before
    reclaiming a non-terminal job, so a rolling restart of one worker
    does not reap the jobs still running on the others (ADR 0038).

    A no-op when the store has no lease surface — `InMemoryJobStore`
    jobs die with the process, so there is nothing for a redriver to
    reconcile. Detected by duck-typing, matching how `_put_event`
    detects `publish_event`.

    Failing to acquire means another live worker claims this job id.
    That is a double-submit, not a reason to refuse to run: we log it
    and proceed leaseless rather than dropping work on the floor.

    Args:
        store: The job store, which may or may not support leases.
        job_id: Job to hold the lease for.
        worker_id: This process's id, stored as the lease value.

    Yields:
        None, for the duration of the job.
    """
    acquire = getattr(store, "acquire_lease", None)
    refresh = getattr(store, "refresh_lease", None)
    release = getattr(store, "release_lease", None)
    if not (callable(acquire) and callable(refresh) and callable(release)):
        yield
        return

    ttl_sec = settings.job_lease_ttl_sec
    holding = False
    # The two ways to end up leaseless are worth separating in the
    # logs: a contended key means a second worker claims the same job
    # id, a raised acquire means Redis is unhealthy. Both proceed
    # unleased, but they call for different investigations.
    try:
        holding = bool(await acquire(job_id, worker_id, ttl_sec))
    except Exception:
        # Redis blipped. Proceeding leaseless for the whole run would
        # leave this job reapable by any peer's sweep for as long as
        # it takes — so still start the keeper, which re-attempts the
        # acquire on every tick and closes the window as soon as
        # Redis comes back.
        log.warning(
            "job_lease_acquire_error",
            extra={"job_id": job_id, "worker_id": worker_id},
        )
    else:
        if not holding:
            # A second worker claims this job id. That is a
            # double-submit, not a reason to refuse to run, and
            # unlike the error above it will not resolve by
            # retrying — do not fight the rightful owner for the key.
            log.warning(
                "job_lease_contended",
                extra={"job_id": job_id, "worker_id": worker_id},
            )
            yield
            return

    task = asyncio.create_task(
        _refresh_lease_forever(
            refresh, job_id, worker_id, acquire=None if holding else acquire
        ),
        name=f"job-lease-{job_id}",
    )
    try:
        yield
    finally:
        # Runs on the cancellation path too — shutdown cancels the
        # job task, and the lease must not outlive the run.
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        with contextlib.suppress(Exception):
            await release(job_id, worker_id)


async def run_job(
    job: Job,
    workflow: Any,
    store: JobStore,
    semaphore: asyncio.Semaphore,
    *,
    timeout_sec: int | None = None,
    conversation_store: Any = None,
    worker_id: str | None = None,
) -> None:
    """Execute one job to completion, updating the store as it goes.

    Enforces the concurrency semaphore, the per-job timeout, and
    error containment: this function never raises — every failure
    ends up on the `Job` record.

    When `job.conversation_id` is set and `conversation_store` is
    provided, the runner retrieves top-K chunks from prior jobs in
    that conversation before invoking the workflow, and appends the
    completed job to the conversation on success (ADR 0032).

    ``workflow`` is the pre-compiled LangGraph app; the caller
    (`create_app` lifespan) builds it once — with
    `async_checkpointer=True`, per ADR 0040 — and hands the same
    instance to every job. See ADR 0034.

    On timeout or shutdown the runner sets the job's cancel token and
    keeps its semaphore permit until the in-flight node thread returns,
    bounded by `settings.api_job_drain_timeout_sec` (the shutdown path
    clamps that further at `SHUTDOWN_DRAIN_SEC`). See ADR 0047. The job
    reaches its terminal state and emits its terminal frame *before*
    that wait, so a client is never held behind a zombie thread.

    For the whole time this worker owns the job — from entry, so the
    wait behind the semaphore is covered too — it holds a lease on
    the store (ADR 0038). That is what lets the startup redriver tell
    "orphaned by a dead worker" apart from "queued or running
    elsewhere"; the lease is released in the `finally` of
    `_job_lease`, including on the shutdown-cancellation path.

    Args:
        job: The job record to execute and update in place.
        workflow: Pre-compiled LangGraph app shared across jobs.
        store: Persistence layer; every status transition is written
            through it.
        semaphore: Global concurrency limiter.
        timeout_sec: Per-job wall-clock cap. Defaults to
            `settings.api_job_timeout_sec`.
        conversation_store: Conversation persistence for the ADR-0032
            follow-up path. None disables prior-context retrieval.
        worker_id: Id stamped on the job lease. Defaults to this
            process's `WORKER_ID`; injectable for tests.
    """
    timeout = timeout_sec if timeout_sec is not None else settings.api_job_timeout_sec

    # ADR 0038: take the lease *before* the semaphore, not after. A
    # job sits in `pending` for as long as the queue behind
    # `api_max_concurrent_jobs` is deep, and this worker already owns
    # it the moment `run_job` starts. Acquiring after the semaphore
    # would leave every queued row leaseless, and a peer worker's
    # startup sweep reads a leaseless non-terminal row as orphaned —
    # it would fail live, queued work on every rolling restart.
    async with _job_lease(store, job.job_id, worker_id or WORKER_ID), semaphore:
        # ADR 0035: bind the store so `_put_event` /
        # `_put_terminal_event` can reach it for pub/sub fan-out.
        # ContextVar is asyncio-Task-scoped: sets inside a Task
        # don't leak back to the caller, and `run_job` runs as the
        # top-level coroutine of the job's Task, so we don't need
        # to reset on exit.
        _current_store.set(store)

        token = bind_run_id(job.job_id)
        # ADR 0047: one cancel token per job, bound to this task's
        # context so the graph's node wrapper, `src.llm.call_llm` and
        # the reader's per-paper fan-out can all reach it without the
        # runner threading a handle through `_invoke_streaming` ->
        # LangGraph -> agent. Same ContextVar shape as `_current_costs`.
        cancel_token = CancelToken(job.job_id)
        cancel_scope = bind_cancel_token(cancel_token)
        costs = start_cost_tracking()
        cap_usd = settings.max_cost_usd

        async def on_node(node_name: str, state_update: dict[str, Any]) -> None:
            # Only publish scalar fields — the papers/citations lists
            # can be large and readers can fetch the full result via
            # `GET /research/{job_id}`. Keeps SSE frames compact.
            slim = {
                k: v
                for k, v in state_update.items()
                if isinstance(v, (str, int, float, bool)) and k != "messages"
            }
            await _put_event(
                job,
                "node_completed",
                {"node": node_name, "state_delta": slim},
            )
            # ADR 0033: enforce the per-run cost cap between nodes so
            # the fixed-DAG path (no supervisor) can't overspend on
            # adversarial inputs. Supervisor loop has its own check
            # but firing here first is harmless — both point at the
            # same accumulator.
            _enforce_cost_cap(costs, cap_usd)

        # Containment starts BEFORE the first store write, not after
        # the setup block: the audit showed a raise between the
        # `running` persist and the old `try` (a store blip, a
        # conversation-store read, an embedding-model load) escaped
        # `run_job` entirely and wedged the job in `running` with its
        # SSE clients hanging forever.
        try:
            job.status = JobStatus.running
            job.started_at = time.time()
            await store.update(job)

            await _put_event(
                job,
                "job_started",
                {"job_id": job.job_id, "query": job.query},
            )

            prior_context = ""
            if job.conversation_id and conversation_store is not None:
                # Retrieve top-K chunks from the conversation's prior
                # jobs. Encoding happens in a thread — MiniLM inference
                # is CPU-bound and doesn't need the async event loop.
                # A failure here degrades to a context-free answer
                # rather than failing the job: prior context is an
                # enrichment (ADR 0032), not a prerequisite.
                try:
                    from src.api.retriever import (
                        format_context_for_planner,
                        retrieve_prior_context,
                    )

                    conversation = await conversation_store.get(
                        job.conversation_id
                    )
                    if conversation is not None and conversation.jobs:
                        chunks = await asyncio.to_thread(
                            retrieve_prior_context,
                            conversation,
                            job.query,
                            settings.conversation_context_top_k,
                        )
                        prior_context = format_context_for_planner(chunks)
                except Exception:
                    log.warning(
                        "api_prior_context_failed",
                        extra={
                            "job_id": job.job_id,
                            "conversation_id": job.conversation_id,
                        },
                        exc_info=True,
                    )

            initial = _initial_state(
                job.query, job.job_id, prior_context=prior_context
            )

            # The overall timeout wraps only the workflow execution
            # itself — not the HITL wait, which has its own
            # `api_hitl_timeout_sec` inside `_handle_hitl_pause`.
            # Compute a HITL-aware outer timeout: if HITL is enabled,
            # allow enough headroom for one review cycle plus the
            # workflow's own budget.
            outer_timeout = timeout
            if settings.enable_hitl and not job.hitl_bypass:
                outer_timeout = timeout + settings.api_hitl_timeout_sec

            final_state = await asyncio.wait_for(
                _invoke_streaming(
                    workflow,
                    initial,
                    job.job_id,
                    on_node,
                    job=job,
                    store=store,
                ),
                timeout=outer_timeout,
            )
        except HitlTimeoutError:
            job.status = JobStatus.failed
            job.error = (
                f"pending_review exceeded {settings.api_hitl_timeout_sec}s"
            )
            job.error_type = "hitl_timeout"
            job.completed_at = time.time()
            snapshot = costs.as_dict()
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            await _persist_terminal(store, job)
            await _put_terminal_event(
                job,
                "job_failed",
                {
                    "job_id": job.job_id,
                    "error": job.error,
                    "error_type": job.error_type,
                    "elapsed_sec": job.elapsed_sec(),
                },
            )
            log.warning(
                "api_job_hitl_timeout",
                extra={
                    "job_id": job.job_id,
                    "hitl_timeout_sec": settings.api_hitl_timeout_sec,
                    **snapshot,
                },
            )
            return
        except CostBudgetExceeded as exc:
            job.status = JobStatus.failed
            job.error = str(exc)
            job.error_type = "cost_budget_exceeded"
            job.completed_at = time.time()
            snapshot = costs.as_dict()
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            await _persist_terminal(store, job)
            await _put_terminal_event(
                job,
                "job_failed",
                {
                    "job_id": job.job_id,
                    "error": job.error,
                    "error_type": job.error_type,
                    "elapsed_sec": job.elapsed_sec(),
                },
            )
            log.warning(
                "api_job_cost_budget_exceeded",
                extra={
                    "job_id": job.job_id,
                    "cap_usd": exc.cap_usd,
                    "spent_usd": exc.spent_usd,
                    **snapshot,
                },
            )
            return
        except HitlCancelledError:
            job.status = JobStatus.cancelled
            job.completed_at = time.time()
            snapshot = costs.as_dict()
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            await _persist_terminal(store, job)
            await _put_terminal_event(
                job,
                "job_cancelled",
                {
                    "job_id": job.job_id,
                    "elapsed_sec": job.elapsed_sec(),
                    "reason": "hitl_cancelled",
                },
            )
            log.info(
                "api_job_hitl_cancelled",
                extra={"job_id": job.job_id, **snapshot},
            )
            return
        except TimeoutError:
            # ADR 0047: `wait_for` cancelled the coroutine, not the node
            # thread. Signal first — every LLM call and every paper in
            # the reader's fan-out checks this token — so the spend
            # stops while we write the outcome.
            cancel_token.cancel("job_timeout")
            job.status = JobStatus.failed
            job.error = f"Workflow exceeded {timeout}s timeout"
            job.error_type = "timeout"
            job.completed_at = time.time()
            snapshot = costs.as_dict()
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            await _persist_terminal(store, job)
            await _put_terminal_event(
                job,
                "job_failed",
                {
                    "job_id": job.job_id,
                    "error": job.error,
                    "error_type": job.error_type,
                    "elapsed_sec": job.elapsed_sec(),
                },
            )
            # Client is already released by the terminal frame above;
            # the semaphore permit is not. It stays held until the node
            # thread returns (or the drain budget expires), so the
            # concurrency ceiling keeps meaning what it says.
            abandoned = await _drain_node_threads(
                cancel_token, job, reason="job_timeout"
            )
            log.warning(
                "api_job_timeout",
                extra={
                    "job_id": job.job_id,
                    "timeout_sec": timeout,
                    "abandoned_nodes": abandoned,
                    **snapshot,
                },
            )
            return
        except asyncio.CancelledError:
            # Shutdown cancelled this task. Same asymmetry as the
            # timeout path (ADR 0047): the coroutine dies immediately,
            # the node thread does not. Draining here is also what
            # makes the lifespan's executor join meaningful — by the
            # time it runs, cooperating nodes have already unwound.
            cancel_token.cancel("shutdown")
            job.status = JobStatus.cancelled
            job.completed_at = time.time()
            snapshot = costs.as_dict()
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            await _persist_terminal(store, job)
            await _put_terminal_event(
                job,
                "job_cancelled",
                {"job_id": job.job_id, "elapsed_sec": job.elapsed_sec()},
            )
            abandoned = await _drain_node_threads(
                cancel_token,
                job,
                reason="shutdown",
                max_budget_sec=SHUTDOWN_DRAIN_SEC,
            )
            log.info(
                "api_job_cancelled",
                extra={
                    "job_id": job.job_id,
                    "abandoned_nodes": abandoned,
                    **snapshot,
                },
            )
            raise
        except Exception as exc:
            job.status = JobStatus.failed
            job.error = f"{type(exc).__name__}: {exc}"
            job.error_type = type(exc).__name__
            job.completed_at = time.time()
            snapshot = costs.as_dict()
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            await _persist_terminal(store, job)
            await _put_terminal_event(
                job,
                "job_failed",
                {
                    "job_id": job.job_id,
                    "error": job.error,
                    "error_type": job.error_type,
                    "elapsed_sec": job.elapsed_sec(),
                },
            )
            log.exception(
                "api_job_failed", extra={"job_id": job.job_id, **snapshot}
            )
            return
        else:
            metrics = _extract_final_metrics(final_state)
            snapshot = costs.as_dict()

            job.status = JobStatus.succeeded
            job.result = final_state.get("draft_report", "")
            job.iterations = metrics["iterations"]
            job.quality_score = metrics["quality_score"]
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            job.completed_at = time.time()

            # Success persistence goes through the same absorbing
            # helper as the failure paths — this used to be a bare
            # `store.update` OUTSIDE the try, so one Redis blip on the
            # last write lost the finished report and broke run_job's
            # "never raises" contract (audit P2).
            await _persist_terminal(store, job)

            # ADR 0032: append succeeded jobs to their conversation,
            # so follow-up queries retrieve this report as prior
            # context. Auto-title the conversation from the first
            # job's query when the client seeded it without a title.
            # The job stays `succeeded` when this fails, but the gap
            # must be observable (audit P3) — a silent miss here means
            # every follow-up quietly loses its context.
            if job.conversation_id and conversation_store is not None:
                try:
                    await _append_to_conversation(conversation_store, job)
                except Exception:
                    log.error(
                        "conversation_append_failed",
                        extra={
                            "job_id": job.job_id,
                            "conversation_id": job.conversation_id,
                        },
                        exc_info=True,
                    )

            await _put_terminal_event(
                job,
                "job_completed",
                {
                    "job_id": job.job_id,
                    "iterations": job.iterations,
                    "quality_score": job.quality_score,
                    "cost_usd": job.cost_usd,
                    "llm_calls": job.llm_calls,
                    "elapsed_sec": job.elapsed_sec(),
                },
            )
            log.info(
                "api_job_completed",
                extra={
                    "job_id": job.job_id,
                    "elapsed_sec": job.elapsed_sec(),
                    **snapshot,
                },
            )
        finally:
            # After every terminal emission, so the outcome records —
            # `api_job_completed` / `api_job_failed` / the terminal
            # frame — carry the run_id instead of "-" (audit P3).
            reset_run_id(token)
            # ADR 0047: unbind the token too. `run_job` normally owns
            # its Task's context, but programmatic callers await it
            # inline — leaving a *cancelled* token bound there would
            # abort the next unrelated LLM call in the same context.
            reset_cancel_token(cancel_scope)


async def _append_to_conversation(conversation_store: Any, job: Job) -> None:
    """Append a succeeded job to its conversation. Auto-titles the
    conversation from the first job's query when the current title
    is the default placeholder."""
    from src.api.conversations import Conversation, title_from_query

    added = await conversation_store.append_job(
        conversation_id=job.conversation_id,
        job_id=job.job_id,
        query=job.query,
        report=job.result or "",
    )
    if added is None:
        return
    # First-job auto-title. Only overwrites the default placeholder;
    # a client-set title stays intact.
    if added.ordinal == 1:
        conversation: Conversation | None = await conversation_store.get(
            job.conversation_id
        )
        if conversation is not None and conversation.title == "New conversation":
            # ADR 0048 added `update_title` to the ConversationStore
            # Protocol precisely for this call site: under the
            # Postgres store, mutating the fetched dataclass changed
            # nothing durable, so the auto-title silently vanished on
            # the next read from another worker.
            await conversation_store.update_title(
                job.conversation_id, title_from_query(job.query)
            )
