"""HTTP route handlers.

Kept module-level (not class-based) so FastAPI's `Depends` injection
does the wiring and tests can drive the app via `httpx.AsyncClient`
without setup ceremony.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse

from src.api.auth import ApiKeyPrincipal, enforce_rate_limit, require_principal
from src.api.conversations import (
    Conversation,
    new_conversation_id,
)
from src.api.exporters import EXPORTERS
from src.api.jobs import (
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
    format_sse,
    sse_event_stream,
)
from src.config import settings
from src.observability import get_logger

log = get_logger(__name__)

router = APIRouter()


def _check_ownership(
    resource_principal_key_id: str | None,
    caller: ApiKeyPrincipal | None,
    *,
    detail: str,
) -> None:
    """Enforce per-principal ownership on a resource (ADR 0036).

    - Auth off (`caller is None`): access allowed regardless of
      what's on the resource. Legacy demo behavior.
    - Auth on: caller's `key_id` must equal the resource's
      `principal_key_id`. Legacy rows with `principal_key_id=None`
      are invisible under auth-on.

    Mismatch raises 404 (not 403): leaking "this exists but you
    can't touch it" is an info-disclosure vector. From the client's
    perspective, resources owned by other principals simply don't
    exist.
    """
    if caller is None:
        return
    if resource_principal_key_id == caller.key_id:
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=detail
    )


def _principal_key_id(caller: ApiKeyPrincipal | None) -> str | None:
    """`principal.key_id` when auth is on, `None` otherwise.

    Convenience so route handlers can stamp `principal_key_id` on
    new rows without repeating the `if principal else None` guard.
    """
    return caller.key_id if caller is not None else None


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
async def submit_research(
    body: ResearchRequest,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> ResearchAccepted:
    """Accept a query and kick off a background workflow.

    Returns 202 with `job_id`, `status_url`, `stream_url`. The
    workflow runs behind a semaphore so requests over the concurrent
    ceiling queue as `pending` and start when a slot frees.

    When `conversation_id` is set, the runner retrieves prior-report
    chunks from that conversation before invoking the workflow, and
    appends the completed job to the conversation on succeed. See
    ADR 0032.

    Under `settings.enable_api_auth`, `X-API-Key` is required — see
    ADR 0033 — and the caller is subject to
    `settings.api_key_hourly_limit`.
    """
    # ADR 0033 + ADR 0037: rate-limit the submit route only.
    # Read/status routes don't cost LLM dollars so they don't need
    # per-key throttling. Async now — the Redis backend awaits
    # pipeline execution.
    await enforce_rate_limit(request, principal)
    state = _get_state(request)

    # Fast-fail on a missing conversation before the workflow starts.
    if body.conversation_id is not None:
        conversation_store = state["conversation_store"]
        conversation = await conversation_store.get(body.conversation_id)
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="conversation_not_found",
            )
        # ADR 0036: a caller can't piggyback on another principal's
        # conversation. `_check_ownership` returns 404 (not 403) so
        # this reads identically to "the id doesn't exist" from the
        # caller's perspective.
        _check_ownership(
            conversation.principal_key_id,
            principal,
            detail="conversation_not_found",
        )

    job = Job(
        job_id=_new_job_id(),
        query=body.query,
        hitl_bypass=body.hitl_bypass,
        conversation_id=body.conversation_id,
        principal_key_id=_principal_key_id(principal),
    )
    await state["store"].create(job)

    task = asyncio.create_task(
        run_job(
            job,
            workflow=state["workflow"],
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
async def get_research(
    job_id: str,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> JobDetail:
    state = _get_state(request)
    job = await state["store"].get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found"
        )
    _check_ownership(job.principal_key_id, principal, detail="job_not_found")
    return _job_to_detail(job)


@router.post(
    "/research/{job_id}/review",
    response_model=ReviewResponse,
    summary="Resolve a `pending_review` job — approve, revise, or cancel.",
)
async def review_plan(
    job_id: str,
    body: ReviewRequest,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
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
    _check_ownership(job.principal_key_id, principal, detail="job_not_found")
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

    # ADR 0034: publish to `hitl:resume:{job_id}` so a runner sitting
    # on a different worker wakes up. Same-worker resumes still take
    # the local Event fast-path below. `publish_remote_resume` is
    # optional on the store Protocol — in-memory stores skip it.
    #
    # ADR 0042: a failed publish must be LOUD. Under multi-worker
    # uvicorn this publish is the only mechanism that wakes a runner
    # parked on another worker; when it's lost, the review still
    # returns 200 but the job dies ~30 minutes later on
    # `hitl_timeout` with nothing connecting the two events. We keep
    # the 200 (the same-worker path already resumed via the local
    # Event below, and the decision is durably persisted on the job
    # row) but log at ERROR with the job_id so the incident timeline
    # has the dropped publish in it.
    publish = getattr(state["store"], "publish_remote_resume", None)
    if callable(publish):
        try:
            await publish(job.job_id, body.action, job.resume_plan)
        except Exception:
            log.error(
                "hitl_resume_publish_failed",
                exc_info=True,
                extra={"job_id": job.job_id, "action": body.action},
            )

    # Same-worker wake-up. The runner is `await`ing on this Event
    # inside `_handle_hitl_pause`. When the review lands on the same
    # worker as the runner, this fires first and the pub/sub
    # subscription is cancelled without ever seeing a message.
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
    principal: ApiKeyPrincipal | None = Depends(require_principal),
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
    _check_ownership(job.principal_key_id, principal, detail="job_not_found")
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
async def stream_research(
    job_id: str,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> StreamingResponse:
    """Stream this job's workflow events as Server-Sent Events.

    Terminal jobs replay a single frame and close, which is what
    makes reconnects idempotent. Live jobs are handed to
    `sse_event_stream` (ADR 0038), which owns the read/heartbeat/
    deadline loop and the drainer's cleanup.

    Args:
        job_id: Job to stream.
        request: Incoming request; supplies app state and the
            disconnect probe.
        principal: Authenticated caller, or None when auth is off.

    Returns:
        A `text/event-stream` response.

    Raises:
        HTTPException: 404 when the job is unknown or owned by
            another principal (ADR 0036).
    """
    state = _get_state(request)
    store = state["store"]
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found"
        )
    _check_ownership(job.principal_key_id, principal, detail="job_not_found")

    async def event_source() -> AsyncIterator[bytes]:
        # Terminal jobs replay a single frame and close — no
        # streaming to do. This is what makes reconnects idempotent.
        if job.is_terminal():
            yield format_sse(
                _terminal_event_name(job),
                _terminal_event_data(job),
            )
            return

        # ADR 0035: prefer the store's cross-worker event stream
        # (RedisJobStore pub/sub on `events:{job_id}`) when the
        # store advertises it. Falls back to draining
        # `job.event_queue` for `InMemoryJobStore`. This is what
        # lets the stream endpoint work when it lands on a
        # different worker than the runner.
        subscribe_events = getattr(store, "subscribe_events", None)
        drainer: AsyncIterator[dict[str, Any]]
        if callable(subscribe_events):
            drainer = subscribe_events(job_id)
        else:
            drainer = drain_events(job)

        try:
            # ADR 0038: the loop lives in `src/api/streaming.py` so it
            # can be tested without FastAPI, Redis or real sleeping.
            #
            # `aclosing` is load-bearing, not tidiness. StreamingResponse
            # abandons its body iterator when the socket goes away — it
            # never calls `aclose()` on it — so the GeneratorExit that
            # eventually lands on *this* generator arrives at `yield
            # chunk`, outside the inner `__anext__`. A bare `async for`
            # would let `sse_event_stream` fall out of scope unclosed and
            # leave its `finally` (unsubscribe + release the Redis
            # connection) to whenever the async-generator finalizer runs.
            # That is one leaked pubsub connection per disconnected
            # client, which is the exact failure ADR 0035 closed.
            async with contextlib.aclosing(
                sse_event_stream(
                    drainer,
                    is_disconnected=request.is_disconnected,
                    heartbeat_sec=settings.api_sse_heartbeat_sec,
                    max_duration_sec=float(settings.api_sse_max_duration_sec),
                    job_id=job_id,
                )
            ) as stream:
                async for chunk in stream:
                    yield chunk
        except asyncio.CancelledError:
            # Client disconnect mid-wait — quiet exit. `sse_event_stream`
            # has already closed the drainer in its own `finally`.
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
    body: ConversationCreateRequest,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> ConversationDetail:
    """Create an empty conversation. `title` is optional — when
    omitted the first job's query auto-populates it. See ADR 0032.

    Under `settings.enable_api_auth` the conversation is owned by
    the presenting API key; other principals see 404 on
    read/delete. See ADR 0036.
    """
    state = _get_state(request)
    conversation = Conversation(
        conversation_id=new_conversation_id(),
        title=body.title or "New conversation",
        principal_key_id=_principal_key_id(principal),
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
async def list_conversations(
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> list[ConversationListItem]:
    state = _get_state(request)
    # ADR 0036: scope the list to the caller's principal. Auth-off
    # passes `None` and gets everything (legacy behavior).
    conversations = await state["conversation_store"].list(
        principal_key_id=_principal_key_id(principal),
    )
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
    conversation_id: str,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> ConversationDetail:
    state = _get_state(request)
    conversation = await state["conversation_store"].get(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation_not_found"
        )
    _check_ownership(
        conversation.principal_key_id,
        principal,
        detail="conversation_not_found",
    )
    return _conversation_to_detail(conversation)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation + all its jobs.",
)
async def delete_conversation(
    conversation_id: str,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> Response:
    state = _get_state(request)
    # ADR 0036: fetch first so we can verify ownership before the
    # destructive call. Skipping the fetch would need a
    # `delete_owned` primitive on every store; the extra round-trip
    # is cheap and localizes the policy in the route layer.
    conversation = await state["conversation_store"].get(conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation_not_found"
        )
    _check_ownership(
        conversation.principal_key_id,
        principal,
        detail="conversation_not_found",
    )
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


# Dependency pings must be fast — /healthz is polled every 15s by
# the compose healthcheck and must never wedge the probe behind a
# slow backend. 2s leaves headroom inside the probe's 3s timeout.
_HEALTHZ_PING_TIMEOUT_SEC = 2.0


async def _redis_status(store: Any) -> str | None:
    """Ping the store's Redis client, if it has one.

    Duck-typed on `_client` — the same coupling `create_app` uses to
    share the client with the rate limiter (ADR 0037 follow-up will
    make it a public property). Returns `None` for stores with no
    Redis behind them (in-memory), so the dependency simply doesn't
    appear in the health payload.
    """
    client = getattr(store, "_client", None)
    ping = getattr(client, "ping", None)
    if not callable(ping):
        return None
    try:
        await asyncio.wait_for(ping(), timeout=_HEALTHZ_PING_TIMEOUT_SEC)
        return "ok"
    except Exception as exc:  # noqa: BLE001 - report, never raise
        return f"error: {type(exc).__name__}"


async def _postgres_status() -> str:
    """`SELECT 1` through the shared pool, bounded.

    Runs in a thread because the psycopg pool is sync (ADR 0028).
    `wait_for` abandons (not cancels) a stuck thread — acceptable:
    the probe stays bounded and the thread dies with its connection
    timeout.
    """

    def _ping() -> None:
        from src.tools import postgres_pool

        with postgres_pool.get_pool().connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")

    try:
        await asyncio.wait_for(
            asyncio.to_thread(_ping), timeout=_HEALTHZ_PING_TIMEOUT_SEC
        )
        return "ok"
    except Exception as exc:  # noqa: BLE001 - report, never raise
        return f"error: {type(exc).__name__}"


@router.get(
    "/healthz",
    response_model=HealthResponse,
    summary="Liveness + dependency status + per-worker concurrency.",
)
async def healthz(request: Request) -> HealthResponse:
    """Process liveness plus an honest dependency report (ADR 0042).

    Deliberately auth-exempt (orchestrator probes can't send keys)
    and always HTTP 200: this endpoint answers "is THIS process
    alive", and restarting the process does not fix a dead Redis —
    a probe that 503s on dependency failure turns a backend blip
    into a rolling-restart storm. Dependency state is reported in
    the body (`status: degraded` + per-dependency breakdown) so
    operators and smarter probes can see it.

    `active_jobs` counts this worker's in-flight job tasks (queued +
    running) — store-independent, so it no longer reports a constant
    0 under the shipped Redis store.
    """
    state = _get_state(request)
    dependencies: dict[str, str] = {}

    redis_status = await _redis_status(state["store"])
    if redis_status is not None:
        dependencies["redis"] = redis_status
    # Only ping Postgres when the deployment configures it — the
    # in-memory demo path has no pool to check.
    if settings.postgres_url:
        dependencies["postgres"] = await _postgres_status()

    degraded = any(v != "ok" for v in dependencies.values())
    return HealthResponse(
        status="degraded" if degraded else "ok",
        active_jobs=len(state["tasks"]),
        max_concurrent_jobs=state["max_concurrent_jobs"],
        dependencies=dependencies,
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
        "workflow": request.app.state.workflow,
        "semaphore": request.app.state.semaphore,
        "max_concurrent_jobs": request.app.state.max_concurrent_jobs,
        "tasks": request.app.state.tasks,
        "conversation_store": request.app.state.conversation_store,
    }
