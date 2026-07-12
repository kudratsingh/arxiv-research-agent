"""Async workflow runner used by the API layer.

Bridges the sync LangGraph workflow into asyncio: `run_job` invokes
the workflow inside `asyncio.to_thread`, streams intermediate
`(node, state_delta)` events into the job's event queue via
`app.astream`, records final costs + metrics, and applies the
per-job timeout.

The runner is a plain module function (not a class) because it owns
no state — every input comes from the `Job` and the injected
workflow factory. That makes it trivial to swap for a Redis-backed
worker in Sprint 4 PR 3+.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

from src.api.jobs import Job, JobStatus, JobStore
from src.config import settings
from src.graph.state import ResearchState
from src.observability import (
    bind_run_id,
    get_logger,
    reset_run_id,
    start_cost_tracking,
)

log = get_logger(__name__)

WorkflowFactory = Callable[[], Any]
"""Zero-arg callable that returns a compiled LangGraph app.

Injectable so tests can hand in a stub without patching module state.
"""


class HitlTimeoutError(Exception):
    """Job sat in `pending_review` past `api_hitl_timeout_sec`."""


class HitlCancelledError(Exception):
    """Client sent `action=cancel` from the review endpoint."""


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
    """Push an event into the job queue without blocking the runner.

    If the queue is full (SSE consumer is slow or has disconnected),
    drop the oldest event to keep the workflow moving. Terminal
    events must never be dropped, so callers should use
    `_put_terminal_event` for those.
    """
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
    """Blocking put — terminal events are the SSE close signal and
    dropping them would leave the client hanging until heartbeat
    timeout. Slow consumers apply backpressure here.
    """
    await job.event_queue.put({"event": event, "data": data})


def _extract_final_metrics(state: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields that end up in the `JobDetail` response."""
    return {
        "iterations": state.get("iteration"),
        "quality_score": state.get("quality_score"),
    }


async def _invoke_streaming(
    build_workflow: WorkflowFactory,
    initial_state: ResearchState,
    run_id: str,
    on_node: Callable[[str, dict[str, Any]], Awaitable[None]],
    *,
    job: Job | None = None,
    store: JobStore | None = None,
) -> dict[str, Any]:
    """Run the workflow, honoring the HITL breakpoint if present.

    `astream` yields `{node_name: state_update}` after each node. When
    `settings.enable_hitl` is on, the compiled workflow interrupts
    after the planner (ADR 0030); we detect that via
    `app.get_state(config).next`, transition the job to
    `pending_review`, emit `plan_ready`, and wait on
    `job.resume_event`. On resume, optionally apply edits via
    `app.update_state`, then run a second `astream` to completion.

    `job` + `store` are required for the HITL path but optional so
    the eval runner (which calls this without an API layer) still
    works. Bypassing HITL when the workflow is compiled with an
    interrupt: the runner just resumes immediately without waiting.
    """
    app = build_workflow()
    config = {"configurable": {"thread_id": run_id}}

    # First pass: runs until interrupt or completion.
    async for chunk in app.astream(initial_state, config=config):
        for node_name, state_update in chunk.items():
            await on_node(node_name, state_update)

    # Did the workflow interrupt?
    workflow_state = await asyncio.to_thread(app.get_state, config)
    interrupted = bool(getattr(workflow_state, "next", ()))

    if interrupted:
        await _handle_hitl_pause(app, config, workflow_state, job, store)

        # Resume from checkpoint — pass `None` as the input.
        async for chunk in app.astream(None, config=config):
            for node_name, state_update in chunk.items():
                await on_node(node_name, state_update)

    # Settled state via `invoke` on a completed thread — the
    # checkpointer makes this cheap (no re-execution, returns the
    # final values).
    final_state = await asyncio.to_thread(
        app.invoke,
        None if interrupted else initial_state,
        config=config,
    )
    return dict(final_state)


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

    try:
        await asyncio.wait_for(
            job.resume_event.wait(),
            timeout=settings.api_hitl_timeout_sec,
        )
    except TimeoutError as exc:
        raise HitlTimeoutError(
            f"pending_review exceeded {settings.api_hitl_timeout_sec}s"
        ) from exc

    if job.resume_action == "cancel":
        raise HitlCancelledError("client cancelled during plan review")

    if job.resume_action == "revise" and job.resume_plan:
        await asyncio.to_thread(app.update_state, config, job.resume_plan)
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


async def run_job(
    job: Job,
    build_workflow: WorkflowFactory,
    store: JobStore,
    semaphore: asyncio.Semaphore,
    *,
    timeout_sec: int | None = None,
    conversation_store: Any = None,
) -> None:
    """Execute one job to completion, updating the store as it goes.

    Enforces the concurrency semaphore, the per-job timeout, and
    error containment: this function never raises — every failure
    ends up on the `Job` record.

    When `job.conversation_id` is set and `conversation_store` is
    provided, the runner retrieves top-K chunks from prior jobs in
    that conversation before invoking the workflow, and appends the
    completed job to the conversation on success (ADR 0032).
    """
    timeout = timeout_sec if timeout_sec is not None else settings.api_job_timeout_sec

    async with semaphore:
        job.status = JobStatus.running
        job.started_at = time.time()
        await store.update(job)
        await _put_event(
            job,
            "job_started",
            {"job_id": job.job_id, "query": job.query},
        )

        token = bind_run_id(job.job_id)
        costs = start_cost_tracking()

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

        prior_context = ""
        if job.conversation_id and conversation_store is not None:
            # Retrieve top-K chunks from the conversation's prior jobs.
            # Encoding happens in a thread — MiniLM inference is CPU-
            # bound and doesn't need the async event loop.
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

        initial = _initial_state(
            job.query, job.job_id, prior_context=prior_context
        )

        try:
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
                    build_workflow,
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
            reset_run_id(token)
            await store.update(job)
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
        except HitlCancelledError:
            job.status = JobStatus.cancelled
            job.completed_at = time.time()
            snapshot = costs.as_dict()
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            reset_run_id(token)
            await store.update(job)
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
            job.status = JobStatus.failed
            job.error = f"Workflow exceeded {timeout}s timeout"
            job.error_type = "timeout"
            job.completed_at = time.time()
            snapshot = costs.as_dict()
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            reset_run_id(token)
            await store.update(job)
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
                "api_job_timeout",
                extra={"job_id": job.job_id, "timeout_sec": timeout, **snapshot},
            )
            return
        except asyncio.CancelledError:
            job.status = JobStatus.cancelled
            job.completed_at = time.time()
            snapshot = costs.as_dict()
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            reset_run_id(token)
            await store.update(job)
            await _put_terminal_event(
                job,
                "job_cancelled",
                {"job_id": job.job_id, "elapsed_sec": job.elapsed_sec()},
            )
            log.info("api_job_cancelled", extra={"job_id": job.job_id, **snapshot})
            raise
        except Exception as exc:
            job.status = JobStatus.failed
            job.error = f"{type(exc).__name__}: {exc}"
            job.error_type = type(exc).__name__
            job.completed_at = time.time()
            snapshot = costs.as_dict()
            job.cost_usd = snapshot.get("total_cost_usd")
            job.llm_calls = snapshot.get("call_count")
            reset_run_id(token)
            await store.update(job)
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

        metrics = _extract_final_metrics(final_state)
        snapshot = costs.as_dict()

        job.status = JobStatus.succeeded
        job.result = final_state.get("draft_report", "")
        job.iterations = metrics["iterations"]
        job.quality_score = metrics["quality_score"]
        job.cost_usd = snapshot.get("total_cost_usd")
        job.llm_calls = snapshot.get("call_count")
        job.completed_at = time.time()
        reset_run_id(token)

        await store.update(job)

        # ADR 0032: append succeeded jobs to their conversation, so
        # follow-up queries retrieve this report as prior context.
        # Auto-title the conversation from the first job's query when
        # the client seeded it without a title.
        if job.conversation_id and conversation_store is not None:
            with contextlib.suppress(Exception):
                await _append_to_conversation(conversation_store, job)

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
            conversation.title = title_from_query(job.query)
            # In-memory store: mutation is enough; Postgres store: no
            # `update_title` method today. We could add one but the
            # "New conversation" case is rare in practice (clients
            # typically set a title).
