"""HTTP route handlers.

Kept module-level (not class-based) so FastAPI's `Depends` injection
does the wiring and tests can drive the app via `httpx.AsyncClient`
without setup ceremony.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from src.api.jobs import (
    InMemoryJobStore,
    Job,
    JobStatus,
    drain_events,
)
from src.api.runner import run_job
from src.api.schemas import (
    HealthResponse,
    JobDetail,
    ResearchAccepted,
    ResearchRequest,
)
from src.api.streaming import (
    HEARTBEAT_INTERVAL_SEC,
    format_heartbeat,
    format_sse,
)
from src.observability import get_logger

log = get_logger(__name__)

router = APIRouter()


def _job_to_detail(job: Job) -> JobDetail:
    return JobDetail(
        job_id=job.job_id,
        status=job.status.value,
        query=job.query,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        elapsed_sec=job.elapsed_sec(),
        result=job.result,
        error=job.error,
        error_type=job.error_type,
        cost_usd=job.cost_usd,
        llm_calls=job.llm_calls,
        iterations=job.iterations,
        quality_score=job.quality_score,
    )


def _new_job_id() -> str:
    return uuid.uuid4().hex[:16]


@router.post(
    "/research",
    response_model=ResearchAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a research query — returns immediately with a job_id.",
)
async def submit_research(body: ResearchRequest, request: Request) -> ResearchAccepted:
    """Accept a query and kick off a background workflow.

    Returns 202 with `job_id`, `status_url`, `stream_url`. The
    workflow runs behind a semaphore so requests over the concurrent
    ceiling queue as `pending` and start when a slot frees.
    """
    state = _get_state(request)
    job = Job(job_id=_new_job_id(), query=body.query)
    await state["store"].create(job)

    task = asyncio.create_task(
        run_job(
            job,
            build_workflow=state["build_workflow"],
            store=state["store"],
            semaphore=state["semaphore"],
        ),
        name=f"job-{job.job_id}",
    )
    # Registering the task lets the lifespan cancel outstanding jobs
    # on shutdown. Discard when the task finishes so the set doesn't
    # grow unbounded.
    state["tasks"].add(task)
    task.add_done_callback(state["tasks"].discard)

    log.info(
        "api_job_submitted", extra={"job_id": job.job_id, "query": body.query}
    )
    return ResearchAccepted(
        job_id=job.job_id,
        status=job.status.value,
        status_url=f"/research/{job.job_id}",
        stream_url=f"/research/{job.job_id}/stream",
    )


@router.get(
    "/research/{job_id}",
    response_model=JobDetail,
    summary="Get the current status + result of a job.",
)
async def get_research(job_id: str, request: Request) -> JobDetail:
    state = _get_state(request)
    job = await state["store"].get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found"
        )
    return _job_to_detail(job)


@router.get(
    "/research/{job_id}/stream",
    summary="Server-Sent Events stream of workflow events.",
)
async def stream_research(job_id: str, request: Request) -> StreamingResponse:
    state = _get_state(request)
    job = await state["store"].get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found"
        )

    async def event_source() -> Any:
        # Terminal jobs replay a single frame and close — no
        # streaming to do. This is what makes reconnects idempotent.
        if job.is_terminal():
            yield format_sse(
                _terminal_event_name(job),
                _terminal_event_data(job),
            )
            return

        try:
            # Heartbeat + event interleaving via `asyncio.wait`: pull
            # the next event OR fire a heartbeat, whichever wins.
            # `_next_event` wraps the async-generator `__anext__` in a
            # proper coroutine so `create_task` accepts it (mypy is
            # right that `__anext__` returns an Awaitable, not a
            # Coroutine).
            drainer = drain_events(job)

            async def _next_event() -> dict[str, Any]:
                return await drainer.__anext__()

            while True:
                if await request.is_disconnected():
                    log.info("sse_client_disconnected", extra={"job_id": job_id})
                    return
                get_task: asyncio.Task[dict[str, Any]] = asyncio.create_task(
                    _next_event()
                )
                heartbeat_task: asyncio.Task[None] = asyncio.create_task(
                    asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
                )
                done, pending = await asyncio.wait(
                    {get_task, heartbeat_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for p in pending:
                    p.cancel()
                if get_task in done:
                    try:
                        frame = get_task.result()
                    except StopAsyncIteration:
                        return
                    yield format_sse(frame["event"], frame["data"])
                    if frame["event"] in ("job_completed", "job_failed", "job_cancelled"):
                        return
                else:
                    yield format_heartbeat()
        except asyncio.CancelledError:
            # Client disconnect during a `wait` — quiet exit.
            return

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            # Nginx + friends buffer streams by default; disabling
            # buffering makes SSE actually stream through a reverse
            # proxy without waiting for the connection to close.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="Liveness + concurrency headroom.",
)
async def healthz(request: Request) -> HealthResponse:
    state = _get_state(request)
    store = state["store"]
    # Best-effort — the InMemoryJobStore exposes `all_jobs`; a Redis
    # store may not, so we tolerate the shape.
    active = 0
    if isinstance(store, InMemoryJobStore):
        jobs = await store.all_jobs()
        active = sum(
            1 for j in jobs if j.status in (JobStatus.pending, JobStatus.running)
        )
    return HealthResponse(
        status="ok",
        active_jobs=active,
        max_concurrent_jobs=state["max_concurrent_jobs"],
    )


def _terminal_event_name(job: Job) -> str:
    if job.status == JobStatus.succeeded:
        return "job_completed"
    if job.status == JobStatus.cancelled:
        return "job_cancelled"
    return "job_failed"


def _terminal_event_data(job: Job) -> dict[str, Any]:
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


def _get_state(request: Request) -> dict[str, Any]:
    """Access the app's lifespan-owned state, typed for the route.

    Kept as one lookup so refactors happen in one place — routes
    should not touch `request.app.state.*` directly.
    """
    return {
        "store": request.app.state.store,
        "build_workflow": request.app.state.build_workflow,
        "semaphore": request.app.state.semaphore,
        "max_concurrent_jobs": request.app.state.max_concurrent_jobs,
        "tasks": request.app.state.tasks,
    }
