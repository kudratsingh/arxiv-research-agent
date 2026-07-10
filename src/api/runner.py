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


def _initial_state(query: str, run_id: str) -> ResearchState:
    """Fresh `ResearchState` — same shape used by the eval runner.

    Kept inline (rather than reusing `src.eval.runner._initial_state`)
    so the API layer doesn't import the eval module; those two paths
    should not couple.
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
) -> dict[str, Any]:
    """Run the workflow in a thread, streaming node updates to `on_node`.

    `astream` yields `{node_name: state_update}` after each node. We
    push a `node_completed` event per key. The final state is the
    accumulation of all updates against the initial state, but
    LangGraph tracks that internally — for the terminal frame we
    fall back to `ainvoke` on a fresh app to guarantee we have the
    settled state (the last `astream` chunk is just the last update).
    """
    app = build_workflow()
    config = {"configurable": {"thread_id": run_id}}

    # Streaming pass — hands the client per-node events as they land.
    async for chunk in app.astream(initial_state, config=config):
        for node_name, state_update in chunk.items():
            await on_node(node_name, state_update)

    # Second pass to get the settled full state. LangGraph's checkpointer
    # (SqliteSaver, on by default) makes this cheap — the second call
    # resumes from the completed checkpoint rather than re-running.
    final_state = await asyncio.to_thread(app.invoke, initial_state, config=config)
    return dict(final_state)


async def run_job(
    job: Job,
    build_workflow: WorkflowFactory,
    store: JobStore,
    semaphore: asyncio.Semaphore,
    *,
    timeout_sec: int | None = None,
) -> None:
    """Execute one job to completion, updating the store as it goes.

    Enforces the concurrency semaphore, the per-job timeout, and
    error containment: this function never raises — every failure
    ends up on the `Job` record.
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

        initial = _initial_state(job.query, job.job_id)

        try:
            final_state = await asyncio.wait_for(
                _invoke_streaming(build_workflow, initial, job.job_id, on_node),
                timeout=timeout,
            )
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
