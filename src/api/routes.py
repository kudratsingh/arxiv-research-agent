"""HTTP route handlers.

Kept module-level (not class-based) so FastAPI's `Depends` injection
does the wiring and tests can drive the app via `httpx.AsyncClient`
without setup ceremony.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse

from src.api.conversations import (
    Conversation,
    new_conversation_id,
)
from src.api.exporters import EXPORTERS
from src.api.jobs import (
    InMemoryJobStore,
    Job,
    JobStatus,
    drain_events,
)
from src.api.runner import run_job
from src.api.schemas import (
    ConversationCreateRequest,
    ConversationDetail,
    ConversationJobSummary,
    ConversationListItem,
    HealthResponse,
    JobDetail,
    Plan,
    ResearchAccepted,
    ResearchRequest,
    ReviewRequest,
    ReviewResponse,
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
    plan = None
    if job.plan is not None:
        plan = Plan(
            sub_questions=list(job.plan.get("sub_questions", [])),
            search_queries=list(job.plan.get("search_queries", [])),
        )
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
        plan=plan,
        conversation_id=job.conversation_id,
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

    When `conversation_id` is set, the runner retrieves prior-report
    chunks from that conversation before invoking the workflow, and
    appends the completed job to the conversation on succeed. See
    ADR 0032.
    """
    state = _get_state(request)

    # Fast-fail on a missing conversation before the workflow starts.
    if body.conversation_id is not None:
        conversation_store = state["conversation_store"]
        if await conversation_store.get(body.conversation_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="conversation_not_found",
            )

    job = Job(
        job_id=_new_job_id(),
        query=body.query,
        hitl_bypass=body.hitl_bypass,
        conversation_id=body.conversation_id,
    )
    await state["store"].create(job)

    task = asyncio.create_task(
        run_job(
            job,
            build_workflow=state["build_workflow"],
            store=state["store"],
            semaphore=state["semaphore"],
            conversation_store=state["conversation_store"],
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


@router.post(
    "/research/{job_id}/review",
    response_model=ReviewResponse,
    summary="Resolve a `pending_review` job — approve, revise, or cancel.",
)
async def review_plan(
    job_id: str, body: ReviewRequest, request: Request
) -> ReviewResponse:
    """Signal the paused runner with the client's decision (ADR 0030).

    - `approve` — resume as-is.
    - `revise`  — apply `plan` (sub_questions + search_queries) then
                  resume. Both fields required.
    - `cancel`  — abandon the run; job transitions to `cancelled`.
    """
    state = _get_state(request)
    job = await state["store"].get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found"
        )
    if not job.is_awaiting_review():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"job_not_awaiting_review (status={job.status.value})",
        )
    if body.action == "revise" and body.plan is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="revise_requires_plan",
        )

    job.resume_action = body.action
    if body.action == "revise" and body.plan is not None:
        job.resume_plan = {
            "sub_questions": list(body.plan.sub_questions),
            "search_queries": list(body.plan.search_queries),
        }
    await state["store"].update(job)
    # Wake the runner. The runner is `await`ing on this Event inside
    # `_handle_hitl_pause`.
    job.resume_event.set()

    log.info(
        "api_job_review_submitted",
        extra={
            "job_id": job.job_id,
            "action": body.action,
            "has_plan": body.plan is not None,
        },
    )
    return ReviewResponse(
        job_id=job.job_id,
        status=job.status.value,
        action=body.action,
    )


@router.get(
    "/research/{job_id}/export",
    summary="Download the report in the requested format.",
    responses={
        200: {
            "content": {
                "text/markdown": {},
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},  # noqa: E501
            },
        },
    },
)
async def export_research(
    job_id: str,
    request: Request,
    format: str = Query(
        "md",
        pattern="^(md|pdf|docx)$",
        description="`md`, `pdf`, or `docx`",
    ),
) -> Response:
    """Serve the job's report in the requested format (ADR 0031).

    - 404 when the job doesn't exist.
    - 409 when the job hasn't produced a report yet
      (still `pending` / `running` / `pending_review` / `failed`
      without a body / `cancelled` before completion).
    - Content-Disposition: attachment so browsers download rather
      than inline-render, matching the demo UI's export buttons.
    """
    state = _get_state(request)
    job = await state["store"].get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found"
        )
    if not job.result:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"job_has_no_report (status={job.status.value})",
        )

    media_type, ext, render = EXPORTERS[format]
    payload = render(job)
    filename = f"research-{job.job_id}.{ext}"
    log.info(
        "api_job_exported",
        extra={
            "job_id": job.job_id,
            "format": format,
            "bytes": len(payload),
        },
    )
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Report content is per-user and unauthenticated — never
            # cache. Also blocks intermediaries from returning stale
            # copies to a different session.
            "Cache-Control": "no-store",
        },
    )


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


@router.post(
    "/conversations",
    response_model=ConversationDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new conversation.",
)
async def create_conversation(
    body: ConversationCreateRequest, request: Request
) -> ConversationDetail:
    """Create an empty conversation. `title` is optional — when
    omitted the first job's query auto-populates it. See ADR 0032.
    """
    state = _get_state(request)
    conversation = Conversation(
        conversation_id=new_conversation_id(),
        title=body.title or "New conversation",
    )
    await state["conversation_store"].create(conversation)
    log.info(
        "api_conversation_created",
        extra={"conversation_id": conversation.conversation_id},
    )
    return _conversation_to_detail(conversation)


@router.get(
    "/conversations",
    response_model=list[ConversationListItem],
    summary="List conversations, newest first (no job bodies).",
)
async def list_conversations(request: Request) -> list[ConversationListItem]:
    state = _get_state(request)
    conversations = await state["conversation_store"].list()
    return [
        ConversationListItem(
            conversation_id=c.conversation_id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in conversations
    ]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    summary="Full conversation thread including every job's report body.",
)
async def get_conversation(
    conversation_id: str, request: Request
) -> ConversationDetail:
    state = _get_state(request)
    conversation = await state["conversation_store"].get(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation_not_found"
        )
    return _conversation_to_detail(conversation)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation + all its jobs.",
)
async def delete_conversation(
    conversation_id: str, request: Request
) -> Response:
    state = _get_state(request)
    deleted = await state["conversation_store"].delete(conversation_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation_not_found"
        )
    log.info(
        "api_conversation_deleted",
        extra={"conversation_id": conversation_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _conversation_to_detail(conversation: Conversation) -> ConversationDetail:
    return ConversationDetail(
        conversation_id=conversation.conversation_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        jobs=[
            ConversationJobSummary(
                job_id=j.job_id,
                ordinal=j.ordinal,
                query=j.query,
                report=j.report,
                created_at=j.created_at,
            )
            for j in conversation.jobs
        ],
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
        "conversation_store": request.app.state.conversation_store,
    }
