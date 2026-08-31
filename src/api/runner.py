"""Async workflow runner used by the API layer.

Drives the compiled LangGraph app through its async surface —
`astream` / `aget_state` / `aupdate_state` / `Command(resume=...)` — streaming intermediate
`(node, state_delta)` events to SSE consumers, recording final costs
+ metrics, and applying the per-job timeout. The compiled app MUST be
built with `build_workflow(async_checkpointer=True)`: the sync savers
raise `NotImplementedError` from every async method, which is exactly
how the pre-ADR-0040 wiring killed every API job before its first
node ran.

The runner is a plain module function (not a class) because it owns
no state — every input comes from the `Job` and the injected
workflow factory. That keeps it store-agnostic: the same function
serves `InMemoryJobStore` and `RedisJobStore` deployments (ADR 0027).

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

ADR 0049 hangs the job outcome metrics — `research_jobs_total` and
`research_job_duration_seconds` — off `_persist_terminal`, the one
place every terminal transition below passes through.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, cast

from langgraph.types import Command

from src.api.jobs import JOB_KINDS, Job, JobKind, JobStatus, JobStore
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
from src.observability.costs import CostBudgetExceeded
from src.observability.costs import enforce_cost_cap as _enforce_cost_cap
from src.observability.metrics import record_job_terminal

# ADR 0051 moved `CostBudgetExceeded` and the cap helper out of this
# module and into `observability.costs`, so `src.llm` can raise the same
# exception this runner catches without the LLM layer importing the API
# layer. Both are re-bound above under the names this module has always
# exported: `CostBudgetExceeded` is part of the runner's public surface
# (routes and tests import it from here) and `_enforce_cost_cap` is
# imported by `tests/test_runner_cost_cap.py`.

log = get_logger(__name__)

# ADR 0035: `_put_event` / `_put_terminal_event` need to reach the
# JobStore to fan out via pub/sub without threading the store
# argument through every call site. Same pattern as
# `_current_costs` in observability.costs. `run_job` sets it on
# entry; the helpers read it.
_current_store: ContextVar[JobStore | None] = ContextVar("current_store", default=None)

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


class SessionTurnTimeoutError(Exception):
    """A `session` job sat in `awaiting_learner` past its turn timeout.

    Deliberately a sibling of `HitlTimeoutError` rather than a subclass
    of a shared base: `run_job` catches both by name and writes a
    different `error_type` for each, and `web/tests/copy/errorTypeDrift.test.ts`
    derives the frontend's error vocabulary by matching `class X(Exception)`
    in `src/`. A base class would hide both from that check.
    """


ParkFrameEmitter = Callable[[Job, dict[str, Any]], Awaitable[None]]
"""Publishes the SSE frame that tells a client the job has parked.

One per parking flavour, and each one spells its event name as a
string literal at a real `_put_event` call. That is deliberate:
`tests/test_contract_sse_events.py` scrapes those literals out of this
module's source to prove no name escapes the pinned contract, and a
name routed through a constant or a dataclass field would slip past
the scraper.
"""


@dataclass(frozen=True)
class ParkingSpec:
    """One flavour of runner pause: where a job parks and how it wakes.

    The runner has exactly one sanctioned way to stop mid-graph and
    wait for a human — park the job in a *non-terminal* status,
    publish a frame naming what the human has to decide, and block on
    `job.resume_event` until the review endpoint sets it locally or a
    peer worker's pub/sub message does (ADR 0034). ADR 0030 built that
    for plan review; this record is the shape of it, so a second graph
    can inherit the same lifecycle instead of growing a second copy.

    `timeout_setting` is an attribute *name*, not a value, on purpose:
    the runner reads module-level `settings` at call time so a test can
    `monkeypatch.setattr(runner_module, "settings", ...)` (see
    `tests/test_api_hitl.py::_app_with`), and a value captured at
    import would ignore the patch.

    Attributes:
        status: Non-terminal status the job sits in while parked.
        emit: Publishes the park frame. Never a terminal or
            stream-closing event — the stream stays open across the
            pause, exactly as it does for `plan_ready`.
        timeout_setting: Name of the `settings` field bounding the wait.
        timeout_error: Raised with the timeout message when nobody
            resumes in time; `run_job` maps it to a terminal outcome.
        log_event: Structured log event name emitted on the park.
    """

    status: JobStatus
    emit: ParkFrameEmitter
    timeout_setting: str
    timeout_error: type[Exception]
    log_event: str

    def timeout_sec(self) -> int:
        """The current bound on the parked wait, read fresh from settings.

        Annotated rather than `int(...)`-cast: the cast satisfied mypy at
        the price of truncating whatever it was handed, and a test that
        patches a fractional timeout in through `model_copy` (which
        bypasses Pydantic's validation, as `tests/test_api_hitl.py` does)
        would silently get a different wait — and a different message in
        the timeout error — than it asked for.
        """
        value: int = getattr(settings, self.timeout_setting)
        return value


async def _emit_plan_ready(job: Job, plan: dict[str, Any]) -> None:
    """Publish the plan-review frame (ADR 0030).

    `routes.py::_plan_ready_data` reproduces this payload byte for byte
    for the ADR 0053 attach-time replay, so the two are edited
    together or a reconnecting reviewer gets a different plan shape
    than a connected one.
    """
    await _put_event(job, "plan_ready", {"job_id": job.job_id, "plan": plan})


async def _emit_turn_ready(job: Job, turn: dict[str, Any]) -> None:
    """Publish the learner-turn frame (ADR 0057).

    `turn_ready` is a pause frame, not an outcome: like `plan_ready` it
    is deliberately absent from `TERMINAL_EVENT_NAMES` and
    `STREAM_CLOSING_EVENT_NAMES` in `src.api.streaming`, so the SSE
    connection stays open across the whole session rather than being
    torn down and re-established once per turn.
    """
    await _put_event(job, "turn_ready", {"job_id": job.job_id, "turn": turn})


HITL_PARKING = ParkingSpec(
    status=JobStatus.pending_review,
    emit=_emit_plan_ready,
    timeout_setting="api_hitl_timeout_sec",
    timeout_error=HitlTimeoutError,
    log_event="api_job_pending_review",
)
"""Plan review — the original parking, and the one that proves the shape."""

SESSION_TURN_PARKING = ParkingSpec(
    status=JobStatus.awaiting_learner,
    emit=_emit_turn_ready,
    timeout_setting="session_turn_timeout_sec",
    timeout_error=SessionTurnTimeoutError,
    log_event="api_job_awaiting_learner",
)
"""A guided-read session waiting for the learner's next turn (ADR 0057)."""

SESSION_TURN_STATE_KEY = "turn"
"""Where the session graph leaves the payload for the turn it parked on.

The runner reads this key off the checkpoint at the interrupt and
publishes whatever `dict` it finds. Keeping the shape opaque here is
the point: WO-W03 owns what a turn contains, and SR-04 wants the
activity payload to grow a research-task variant in Phase L without a
runner change or a state migration. A session that parks without
setting it still gets a well-formed (empty) frame rather than a
`KeyError` mid-run.
"""


@dataclass(frozen=True)
class PauseContext:
    """Everything a pause handler needs at one graph interrupt.

    Bundled rather than passed as seven positional arguments because
    the handler is a pluggable policy (`_invoke_streaming`'s
    `on_pause`), and a policy's signature is a contract other modules
    implement against.

    Attributes:
        app: The compiled graph, for checkpoint reads and HITL edits.
        config: LangGraph config carrying `thread_id`.
        run_id: The thread id, lifted out of `config` for logging.
        workflow_state: The `aget_state` snapshot at the interrupt.
        job: Job being driven, or None for programmatic/eval callers
            that must never pause.
        store: Job store, or None for the same callers.
        pause_number: 1-based count of interrupts seen on this run.
    """

    app: Any
    config: dict[str, Any]
    run_id: str
    workflow_state: Any
    job: Job | None
    store: JobStore | None
    pause_number: int


PauseHandler = Callable[[PauseContext], Awaitable[Any]]
"""What to do when the compiled graph stops at an interrupt.

Returning means "resume the graph"; raising ends the run. The handler
owns the decision of whether *this* interrupt is a park at all — the
research graph reviews only its first pause (ADR 0030's
one-review-per-query intent) and auto-resumes the rest.
"""


def _initial_state(query: str, run_id: str, *, prior_context: str = "") -> ResearchState:
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


def _extract_final_metrics(state: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields that end up in the `JobDetail` response."""
    return {
        "iterations": state.get("iteration"),
        "quality_score": state.get("quality_score"),
    }


async def _invoke_streaming(
    workflow: Any,
    initial_state: ResearchState | dict[str, Any],
    run_id: str,
    on_node: Callable[[str, dict[str, Any]], Awaitable[None]],
    *,
    job: Job | None = None,
    store: JobStore | None = None,
    on_pause: PauseHandler | None = None,
    max_pauses: int | None = None,
) -> dict[str, Any]:
    """Run the pre-compiled workflow, honoring the HITL breakpoint.

    `astream` yields `{node_name: state_update}` after each node. When
    `settings.enable_hitl` is on, the compiled workflow interrupts
    after the planner (ADR 0030); we detect that via
    `workflow.aget_state(config).next`, transition the job to
    `pending_review`, emit `plan_ready`, and wait on
    `job.resume_event`. On resume, optionally apply edits via
    `workflow.aupdate_state` or a dynamic-interrupt `Command`, then stream on
    from the checkpoint.

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

    `on_pause` is the pause *policy*, defaulting to plan review. It is
    a parameter rather than a hard-coded call so a second graph with a
    different pause meaning can reuse this loop unchanged; the loop
    itself only knows that an interrupt happened, never why.

    The workflow is pre-compiled at app startup and shared across
    jobs (ADR 0034) — previously we re-compiled per job, which
    opened a fresh checkpointer connection every time and never
    cleaned it up until process exit.
    """
    app = workflow
    config: dict[str, Any] = {"configurable": {"thread_id": run_id}}
    handle_pause = on_pause if on_pause is not None else _handle_hitl_pause

    # Fallback final state for checkpointing-disabled runs, where
    # `aget_state` has nothing to answer from. Plain dict-merge is
    # accurate for every field the runner reads (scalars +
    # draft_report); reducer-managed fields like `messages` are not
    # consumed from here.
    merged: dict[str, Any] = dict(initial_state)

    pause_ceiling = max_pauses if max_pauses is not None else _research_max_pauses()
    pauses = 0
    stream_input: Any = initial_state
    while True:
        try:
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
        except CostBudgetExceeded as exc:
            # `merged` is updated BEFORE `on_node` runs, so whatever the
            # graph had produced by the time the ceiling hit is in hand
            # right here — including a `draft_report` from a run whose
            # last node pushed it over. Hand it to the runner rather
            # than letting the money already spent evaporate (ADR 0051).
            # Reading the checkpoint instead would be an extra async
            # round trip for state this frame already holds, and would
            # return nothing at all with checkpointing disabled.
            exc.partial_report = str(merged.get("draft_report") or "")
            raise

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
        if pauses > pause_ceiling:
            raise RuntimeError(
                f"workflow still interrupted after {pause_ceiling} resumes "
                f"(thread_id={run_id}); refusing to report a paused "
                "graph as a finished job"
            )
        resume_input = await handle_pause(
            PauseContext(
                app=app,
                config=config,
                run_id=run_id,
                workflow_state=workflow_state,
                job=job,
                store=store,
                pause_number=pauses,
            )
        )
        # Research HITL returns ``None`` after optionally updating the
        # checkpoint. Session turns return ``Command(resume=...)`` for their
        # dynamic learner-input interrupt. Neither form restarts from START.
        stream_input = resume_input


async def _park_until_resumed(
    job: Job,
    store: JobStore | None,
    spec: ParkingSpec,
    *,
    payload: dict[str, Any],
    log_extra: dict[str, Any] | None = None,
) -> None:
    """Park `job` per `spec` and block until something resumes it.

    The three steps of a pause, in the order the rest of the system
    depends on: the store row moves to the parked status *first* (a
    client that polls `GET /research/{id}` the instant the frame lands
    must not still read `running`), then the frame goes out, then the
    runner waits.

    ADR 0034: when the store advertises a `watch_for_remote_resume`
    method (`RedisJobStore` does), spawn a subscription task alongside
    the local `resume_event` await. That's what lets a resume
    submitted to worker B wake the runner sitting on worker A.
    Single-worker deployments and in-memory stores skip the
    subscription and just await the local event. The channel is the
    same one for every parking flavour — it is keyed by job id, not by
    what the job is waiting for.

    Args:
        job: The job to park. Mutated in place.
        store: Job store, or None for programmatic callers.
        spec: Which parking this is — status, frame, timeout, error.
        payload: Parking-specific body handed to `spec.emit`.
        log_extra: Extra structured-log fields for the park record.
            `job_id` is always included.

    Raises:
        Exception: `spec.timeout_error`, when nobody resumed within
            the spec's timeout. The caller turns that into a terminal
            job outcome.
    """
    job.status = spec.status
    if store is not None:
        await store.update(job)

    subscription: asyncio.Task[None] | None = None
    watch = getattr(store, "watch_for_remote_resume", None) if store else None
    if callable(watch):
        # W03 closes ADR 0057's subscribe-after-publish window. Redis
        # signals readiness only after SUBSCRIBE has completed, so a
        # learner cannot see a turn frame before another worker is ready
        # to receive its reply.
        subscribed = asyncio.Event()
        subscription = asyncio.create_task(watch(job, subscribed), name=f"hitl-resume-{job.job_id}")
        try:
            await asyncio.wait_for(subscribed.wait(), timeout=5.0)
        except BaseException:
            subscription.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await subscription
            raise

    await spec.emit(job, payload)
    log.info(
        spec.log_event,
        extra={"job_id": job.job_id, **(log_extra or {})},
    )

    timeout_sec = spec.timeout_sec()
    try:
        try:
            await asyncio.wait_for(
                job.resume_event.wait(),
                timeout=timeout_sec,
            )
        except TimeoutError as exc:
            raise spec.timeout_error(f"{spec.status.value} exceeded {timeout_sec}s") from exc
    finally:
        if subscription is not None:
            subscription.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await subscription


async def _unpark(job: Job, store: JobStore | None) -> None:
    """Put a resumed job back to `running` and re-arm its resume event.

    The event has to be cleared or the *next* park on the same job
    returns instantly — which for a turn-shaped graph would drive the
    whole session without ever waiting for the learner.
    """
    job.status = JobStatus.running
    job.resume_event.clear()
    if store is not None:
        await store.update(job)


async def _handle_hitl_pause(ctx: PauseContext) -> None:
    """Bridge the pause: populate `job.plan`, emit `plan_ready`, wait
    on the resume signal, optionally apply edits.

    Only the FIRST interrupt of a run is a human review (ADR 0030's
    one-review-per-query intent); `interrupt_after=["planner"]`
    re-arms on every planner execution, so a critic-driven re-plan
    parks the graph again and those pauses auto-resume silently.

    No-op when `ctx.job` is None (called from eval / programmatic
    paths that shouldn't pause). When `job.hitl_bypass` is True the
    runner resumes immediately without emitting a review event.
    """
    if ctx.pause_number != 1:
        log.info(
            "api_job_interrupt_auto_resumed",
            extra={
                "thread_id": ctx.run_id,
                "pause_number": ctx.pause_number,
            },
        )
        return

    job = ctx.job
    if job is None:
        return None
    if job.hitl_bypass:
        # Compiled interrupt is unconditional; caller opted out.
        return

    values = ctx.workflow_state.values
    plan_values = {
        "sub_questions": list(values.get("sub_questions", [])),
        "search_queries": list(values.get("search_queries", [])),
    }
    job.plan = plan_values
    await _park_until_resumed(
        job,
        ctx.store,
        HITL_PARKING,
        payload=plan_values,
        log_extra=_plan_shape(plan_values),
    )

    if job.resume_action == "cancel":
        raise HitlCancelledError("client cancelled during plan review")

    if job.resume_action == "revise" and job.resume_plan:
        await ctx.app.aupdate_state(ctx.config, job.resume_plan)
        log.info(
            "api_job_plan_revised",
            extra={"job_id": job.job_id, **_plan_shape(job.resume_plan)},
        )

    # Back to running for the resume path.
    job.plan = None
    await _unpark(job, ctx.store)


async def _handle_session_turn_pause(ctx: PauseContext) -> Command[Any] | None:
    """Park a `session` job on *every* interrupt (ADR 0057).

    The one structural difference from plan review, and the reason the
    pause policy is a parameter at all: a research run interrupts
    incidentally (the planner re-arms `interrupt_after` on every
    re-plan) and only its first pause is a human decision, whereas a
    tutoring session interrupts *because* it is the learner's turn.
    Auto-resuming any of them would run the whole session against
    itself with nobody in the chair.

    No-op when `ctx.job` is None, matching `_handle_hitl_pause`:
    programmatic drivers of a session graph — the recorded-fixture
    capture in WO-W08, for one — must not block on a human.
    """
    job = ctx.job
    if job is None:
        return None

    values = ctx.workflow_state.values
    turn = dict(values.get(SESSION_TURN_STATE_KEY) or {})
    # On the row before the frame goes out, so a client that attaches
    # between the two gets the ADR 0053 replay rather than silence.
    job.turn = turn
    resume_command: Command[Any] | None = None
    try:
        await _park_until_resumed(
            job,
            ctx.store,
            SESSION_TURN_PARKING,
            payload=turn,
            # No turn *content* in the log line: the payload is model
            # output about a paper the learner is reading, and the
            # observability rules keep user text out of records
            # (ADR 0019). The count is what an operator needs.
            log_extra={
                "pause_number": ctx.pause_number,
                "turn_number": turn.get("turn_number"),
                "state_turn_number": values.get("turn_number"),
            },
        )

        # Take the reply before awaiting anything. `job` is shared with
        # whatever hydrated the resume — the pub/sub watcher or the turn
        # endpoint. Reading the field once prevents a later reply from being
        # nulled while the current Command is constructed.
        reply = job.resume_payload
        job.resume_payload = None
        if reply:
            resume_command = Command(resume=reply)
    finally:
        # Cleared on every exit, not just the resumed one. A job that
        # times out or raises here goes terminal through `run_job`, and
        # a terminal row still advertising the turn it was waiting on
        # is a row that claims a question is open when it is not.
        job.turn = None

    await _unpark(job, ctx.store)
    return resume_command


def _research_initial_state(job: Job, prior_context: str) -> dict[str, Any]:
    """Adapter putting `_initial_state` behind the kind-runtime signature.

    `_initial_state` keeps its `(query, run_id)` shape because
    `tests/test_cli_run_recovery.py` compares it field-for-field
    against the canonical `initial_research_state`.
    """
    return dict(_initial_state(job.query, job.job_id, prior_context=prior_context))


def _session_initial_state(job: Job, prior_context: str) -> dict[str, Any]:
    """Build W03's total ``SessionState`` from the persisted job input.

    ``prior_context`` is accepted for signature symmetry and unused:
    ADR 0032's retrieval is for conversations of research reports; the
    session's bounded Tier-1 block is already in ``job.input_payload``.
    """
    from src.graph.session_state import initial_session_state

    return dict(initial_session_state(job.input_payload, job.job_id, job.query))


def _research_max_pauses() -> int:
    """ADR 0030 intends one human review per query; every extra planner
    run re-arms the interrupt and is auto-resumed. `+ 2` margin: the
    initial planner run plus one defensive slot beyond the critic's own
    `max_iterations` force-approve."""
    return settings.max_iterations + 2


def _session_max_pauses() -> int:
    """Every session interrupt is a real learner turn, so the bound is
    a turn count rather than a re-plan count."""
    return settings.session_max_turns


def _research_outer_timeout(job: Job, base_sec: float) -> float:
    """Workflow budget plus headroom for one review cycle.

    The per-job timeout caps the workflow's own wall-clock, never the
    human's decision time — `api_hitl_timeout_sec` does that, inside
    the parking. Without the headroom the outer `wait_for` would fire
    mid-review and fail a job whose reviewer was still reading.
    """
    if settings.enable_hitl and not job.hitl_bypass:
        return base_sec + settings.api_hitl_timeout_sec
    return base_sec


def _session_outer_timeout(job: Job, base_sec: float) -> float:
    """Same reasoning, once per turn instead of once per run.

    Deliberately generous: this is the backstop that stops a wedged
    session pinning a worker forever, not the mechanism that ends an
    abandoned one. `session_turn_timeout_sec` does that, per turn, and
    fails the job with a `session_turn_timeout` that says why.
    """
    return base_sec + settings.session_turn_timeout_sec * settings.session_max_turns


@dataclass(frozen=True)
class JobKindRuntime:
    """Everything `run_job` does differently for one job kind (ADR 0057).

    The kinds share the whole lifecycle — the lease, the semaphore, the
    cancel token, the cost accumulator, the terminal persistence and
    metrics, every error path. What they do not share is four
    decisions, and this record is the exhaustive list of them, so
    "what changes when a third kind arrives" has an answer that is not
    "read `run_job` and hope".

    Every field is a callable rather than a value because all four read
    `settings` (or the job) at call time; a value captured at import
    would freeze the first `Settings` this module ever saw.

    Attributes:
        initial_state: Builds the graph input from the job and the
            retrieved prior context.
        on_pause: What an interrupt means for this kind.
        max_pauses: How many interrupts are structurally plausible
            before the runner concludes the graph and the runner
            disagree and fails the job loudly.
        outer_timeout: The job's wall-clock ceiling, given the base
            `api_job_timeout_sec` budget. Must leave room for the
            parked waits, which are bounded separately.
    """

    initial_state: Callable[[Job, str], dict[str, Any]]
    on_pause: PauseHandler
    max_pauses: Callable[[], int]
    outer_timeout: Callable[[Job, float], float]


RESEARCH_RUNTIME = JobKindRuntime(
    initial_state=_research_initial_state,
    on_pause=_handle_hitl_pause,
    max_pauses=_research_max_pauses,
    outer_timeout=_research_outer_timeout,
)

SESSION_RUNTIME = JobKindRuntime(
    initial_state=_session_initial_state,
    on_pause=_handle_session_turn_pause,
    max_pauses=_session_max_pauses,
    outer_timeout=_session_outer_timeout,
)

JOB_KIND_RUNTIMES: dict[JobKind, JobKindRuntime] = {
    "research": RESEARCH_RUNTIME,
    "session": SESSION_RUNTIME,
}


def runtime_for(kind: str) -> JobKindRuntime:
    """The runtime for a job kind, defaulting to research.

    Takes `str` rather than `JobKind` on purpose: the value can come
    off a Redis row written by a worker with a wider vocabulary than
    this build's. Falling back to the research runtime keeps such a
    job running rather than crashing the worker, and the WARNING is
    how an operator finds out a job is being driven by the wrong
    policy — the alternative, a silent default, is how a session gets
    auto-resumed past every one of its turns.

    Total by construction, including for inputs the annotation says
    cannot happen. `run_job` calls this before its containment `try`
    and promises never to raise, so a bare `kind not in JOB_KINDS`
    would turn an unhashable value into a `TypeError` that escapes
    `run_job` entirely and wedges the job non-terminal with its SSE
    clients hanging — the exact failure the containment block exists
    to prevent.
    """
    if not isinstance(kind, str) or kind not in JOB_KINDS:
        log.warning("api_job_unknown_kind", extra={"job_kind": kind})
        return RESEARCH_RUNTIME
    return JOB_KIND_RUNTIMES[cast(JobKind, kind)]


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

    Being the one place every terminal transition passes through also
    makes this the right place to record the job outcome metrics
    (ADR 0049) — the alternative was the same two lines duplicated
    across all seven terminal branches, where the next branch added
    would silently not be counted. The record happens *before* the
    write and outside the retry loop on purpose: the job reached its
    terminal state whether or not the store accepted the row, and a
    failing store must not also make the fleet look idle.
    """
    record_job_terminal(
        status=job.status.value,
        error_type=job.error_type,
        duration_sec=job.elapsed_sec(),
    )
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


def _log_lease_failure(event: str, *, job_id: str, worker_id: str, consecutive: int) -> None:
    """Log one lease-keeper failure at a volume an outage survives.

    Every other `except` in this module carries `exc_info` (ADR 0051
    closed the gap where the lease sites did not), but the keeper's
    failures are *timer-driven*: a Redis outage produces one per job per
    `job_lease_refresh_sec` tick, so an unconditional stack trace turns
    a dependency blip into a log flood that buries the events an
    operator is actually looking for.

    The first failure of a streak therefore carries the traceback at
    WARNING and every repeat is DEBUG with a running count — the same
    information, paid for once. The counter resets on the next success,
    so a *second* outage warns again rather than hiding behind the
    first.

    Args:
        event: Structured event name (`job_lease_refresh_error` or
            `job_lease_acquire_error`).
        job_id: Job whose lease failed to refresh or acquire.
        worker_id: This process's lease-owner id.
        consecutive: How many failures of this kind have happened
            back to back, this one included. `1` is the streak head.
    """
    extra = {
        "job_id": job_id,
        "worker_id": worker_id,
        "consecutive": consecutive,
    }
    if consecutive == 1:
        log.warning(event, extra=extra, exc_info=True)
    else:
        log.debug(event, extra=extra, exc_info=True)


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

    # ADR 0051: bind the run_id HERE, not in the caller. `run_job`
    # binds it inside the `async with _job_lease(...)` body, i.e. after
    # `__aenter__` has already created this task — and
    # `asyncio.create_task` snapshots the context at creation, so every
    # line the keeper emitted formatted with the `-` default and could
    # not be joined to its job by run_id. A task's context is its own
    # copy, so setting it in here cannot leak back into `run_job`.
    run_scope = bind_run_id(job_id)
    try:
        await _refresh_lease_loop(
            refresh,
            job_id,
            worker_id,
            acquire=acquire,
            ttl_sec=ttl_sec,
            interval=interval,
        )
    finally:
        reset_run_id(run_scope)


async def _refresh_lease_loop(
    refresh: Callable[[str, str, int], Awaitable[bool]],
    job_id: str,
    worker_id: str,
    *,
    acquire: Callable[[str, str, int], Awaitable[bool]] | None,
    ttl_sec: int,
    interval: int,
) -> None:
    """The keeper's actual loop, split out so the run_id bind above
    reads as a single `try/finally` rather than wrapping 40 lines.

    Args:
        refresh: The store's owner-checked `refresh_lease`.
        job_id: Job whose lease this task owns.
        worker_id: This process's id, checked against the stored owner.
        acquire: The store's `acquire_lease` when we are running
            leaseless and must keep retrying the claim; `None` on the
            normal path.
        ttl_sec: Lease TTL to re-arm on every tick.
        interval: Seconds between ticks.
    """
    # Set when we entered leaseless after a failed acquire; cleared
    # the moment a retry lands.
    pending_acquire = acquire
    # Consecutive failures of each kind, for `_log_lease_failure`'s
    # first-warns-then-debugs volume control.
    refresh_failures = 0
    acquire_failures = 0

    while True:
        await asyncio.sleep(interval)
        if pending_acquire is not None:
            # Still leaseless. Retry the claim rather than refreshing
            # a key we do not hold.
            try:
                if bool(await pending_acquire(job_id, worker_id, ttl_sec)):
                    pending_acquire = None
                    acquire_failures = 0
                    log.info(
                        "job_lease_acquired_late",
                        extra={"job_id": job_id, "worker_id": worker_id},
                    )
            except Exception:
                acquire_failures += 1
                _log_lease_failure(
                    "job_lease_acquire_error",
                    job_id=job_id,
                    worker_id=worker_id,
                    consecutive=acquire_failures,
                )
            continue
        try:
            still_ours = bool(await refresh(job_id, worker_id, ttl_sec))
        except Exception:
            refresh_failures += 1
            _log_lease_failure(
                "job_lease_refresh_error",
                job_id=job_id,
                worker_id=worker_id,
                consecutive=refresh_failures,
            )
            continue
        refresh_failures = 0
        if not still_ours:
            log.warning(
                "job_lease_lost",
                extra={"job_id": job_id, "worker_id": worker_id},
            )
            return


@contextlib.asynccontextmanager
async def _job_lease(store: JobStore, job_id: str, worker_id: str) -> AsyncIterator[None]:
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
    acquire_failed = False
    # ADR 0051: `run_job` binds the run_id inside this context
    # manager's body, so both warnings below used to format with the
    # `-` default. Bind it for the acquire, and drop it again before
    # yielding so the caller's own bind stays the one that owns the
    # scope.
    lease_scope = bind_run_id(job_id)
    try:
        # The two ways to end up leaseless are worth separating in the
        # logs: a contended key means a second worker claims the same
        # job id, a raised acquire means Redis is unhealthy. Both
        # proceed unleased, but they call for different investigations.
        try:
            holding = bool(await acquire(job_id, worker_id, ttl_sec))
        except Exception:
            # Redis blipped. Proceeding leaseless for the whole run
            # would leave this job reapable by any peer's sweep for as
            # long as it takes — so still start the keeper, which
            # re-attempts the acquire on every tick and closes the
            # window as soon as Redis comes back.
            acquire_failed = True
            log.warning(
                "job_lease_acquire_error",
                extra={"job_id": job_id, "worker_id": worker_id},
                # ADR 0051: "the acquire raised" without saying what it
                # raised cannot distinguish a connection refusal from a
                # WRONGTYPE on the lease key, and this is the signal the
                # redriver's orphan decision hangs off.
                exc_info=True,
            )
        if not (holding or acquire_failed):
            # A second worker claims this job id. That is a
            # double-submit, not a reason to refuse to run, and
            # unlike the error above it will not resolve by
            # retrying — do not fight the rightful owner for the key.
            log.warning(
                "job_lease_contended",
                extra={"job_id": job_id, "worker_id": worker_id},
            )
    finally:
        reset_run_id(lease_scope)

    if not (holding or acquire_failed):
        # Contended: no lease and no keeper, because retrying would
        # only fight the rightful owner.
        yield
        return

    task = asyncio.create_task(
        _refresh_lease_forever(refresh, job_id, worker_id, acquire=None if holding else acquire),
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
    progress_event_store: Any = None,
    progress_event_decoder: Callable[[dict[str, Any]], Any] | None = None,
    worker_id: str | None = None,
) -> None:
    """Execute one job to completion, updating the store as it goes.

    Enforces the concurrency semaphore, the per-job timeout, and
    error containment: this function never raises — every failure
    ends up on the `Job` record.

    One driver serves every job kind (ADR 0057). `job.kind` selects a
    `JobKindRuntime` — the graph input, what an interrupt means, how
    many interrupts are plausible, and the wall-clock ceiling — and
    nothing else in here branches on it. That is the whole point of
    the kind field: a session job gets the lease, the cancel token,
    the cost accumulator, the terminal persistence and the outcome
    metrics that took the research path fifty ADRs to get right,
    rather than a second driver that would have to earn them again.

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
        progress_event_store: Append-only ledger used by session jobs.
            Graph nodes produce validated event descriptors; the runner
            persists them before declaring the job successful.
        progress_event_decoder: Store-layer decoder for one serialized
            event. Kept injected so the generic job path does not import
            learner-only exception classes into its error vocabulary.
        worker_id: Id stamped on the job lease. Defaults to this
            process's `WORKER_ID`; injectable for tests.
    """
    timeout = timeout_sec if timeout_sec is not None else settings.api_job_timeout_sec
    # ADR 0057: the four decisions that differ per job kind, resolved
    # once, up front. Everything below this line is shared lifecycle.
    runtime = runtime_for(job.kind)

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
            #
            # ADR 0051 keeps this check even though `src.llm.call_llm`
            # now checks the same accumulator before every call. The two
            # are not redundant: the per-call check is what bounds
            # *intra-node* overshoot (the reader fans out up to
            # `max_papers` calls inside one node, so this callback alone
            # let a run pass the ceiling by a whole node's spend), while
            # this one still catches a node that spent without going
            # through `call_llm` at all. Both raise the same exception
            # from the same accumulator, so whichever fires first is the
            # one `run_job` handles — there is no double-fire.
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

                    conversation = await conversation_store.get(job.conversation_id)
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

            initial = runtime.initial_state(job, prior_context)

            # The overall timeout wraps only the workflow execution
            # itself — not the parked waits, which have their own
            # per-parking timeouts inside `_park_until_resumed`. The
            # kind runtime sizes the headroom: one review cycle for
            # research, one per turn for a session.
            outer_timeout = runtime.outer_timeout(job, float(timeout))

            final_state = await asyncio.wait_for(
                _invoke_streaming(
                    workflow,
                    initial,
                    job.job_id,
                    on_node,
                    job=job,
                    store=store,
                    on_pause=runtime.on_pause,
                    max_pauses=runtime.max_pauses(),
                ),
                timeout=outer_timeout,
            )
            if (
                job.kind == "session"
                and progress_event_store is not None
                and progress_event_decoder is not None
            ):
                raw_events = final_state.get("progress_events", [])
                if not isinstance(raw_events, list):
                    raise ValueError("session progress_events must be a list")
                for raw in raw_events:
                    if not isinstance(raw, dict):
                        raise ValueError("session progress event must be an object")
                    event = progress_event_decoder(raw)
                    if event.principal_key_id != job.principal_key_id:
                        raise ValueError(
                            "session progress event principal does not match job owner"
                        )
                    await progress_event_store.append(event)
        except SessionTurnTimeoutError as exc:
            # The learner stopped answering. Terminal, and named so the
            # Ledger can tell an abandoned session apart from a broken
            # one (WO-W07/W14) without parsing a message.
            job.status = JobStatus.failed
            job.error = str(exc)
            job.error_type = "session_turn_timeout"
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
                "api_job_session_turn_timeout",
                extra={
                    "job_id": job.job_id,
                    "session_turn_timeout_sec": settings.session_turn_timeout_sec,
                    **snapshot,
                },
            )
            return
        except HitlTimeoutError:
            job.status = JobStatus.failed
            job.error = f"pending_review exceeded {settings.api_hitl_timeout_sec}s"
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
            # ADR 0051: keep the draft the run had already paid for.
            # The job is still `failed` — the report is partial and the
            # caller must know it — but `GET /research/{id}` now returns
            # the artifact instead of a bill with nothing attached. This
            # matters most for the run whose *last* node crossed the
            # cap: its report was complete, and it used to be discarded.
            job.result = exc.partial_report or None
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
                    # Whether the spend bought a retrievable artifact is
                    # the first question asked about a capped job.
                    "partial_report_chars": len(job.result or ""),
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
            abandoned = await _drain_node_threads(cancel_token, job, reason="job_timeout")
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
            log.exception("api_job_failed", extra={"job_id": job.job_id, **snapshot})
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
        conversation: Conversation | None = await conversation_store.get(job.conversation_id)
        if conversation is not None and conversation.title == "New conversation":
            # ADR 0048 added `update_title` to the ConversationStore
            # Protocol precisely for this call site: under the
            # Postgres store, mutating the fetched dataclass changed
            # nothing durable, so the auto-title silently vanished on
            # the next read from another worker.
            await conversation_store.update_title(job.conversation_id, title_from_query(job.query))
