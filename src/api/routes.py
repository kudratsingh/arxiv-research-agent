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
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
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
    GoalClaim,
    HealthResponse,
    JobDetail,
    LearnerProfileResponse,
    LearnerProgressSummary,
    Plan,
    ProfileUpdateRequest,
    ProgressDailySessions,
    ProgressEvidence,
    ProgressResourceObservation,
    ProgressSchedule,
    ResearchAccepted,
    ResearchRequest,
    ReviewRequest,
    ReviewResponse,
    SkillClaim,
)
from src.api.streaming import (
    format_sse,
    sse_event_stream,
)
from src.cancellation import abandoned_node_count
from src.config import settings
from src.learning.profile_store import (
    DECLARED_CONFIDENCE,
    LearnerGoal,
    LearnerProfile,
    SkillEntry,
    new_goal_id,
    utc_now_iso,
)
from src.learning.progress_store import (
    DEFAULT_EVENT_LIMIT,
    MAX_EVENT_LIMIT,
    EvidenceRecord,
    InMemoryProgressEventStore,
    ProgressEventStore,
    ProgressSummary,
    summarize,
)
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
        kind=job.kind,
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
    makes reconnects idempotent. A job parked in `pending_review`
    replays its `plan_ready` frame first and then keeps streaming
    (ADR 0053). Live jobs are handed to `sse_event_stream`
    (ADR 0038), which owns the read/heartbeat/deadline loop and the
    drainer's cleanup.

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

        # ADR 0053: same replay idiom, one status earlier. `plan_ready`
        # is published exactly once, when the runner parks the job, and
        # neither transport keeps a backlog: Redis pub/sub drops
        # messages nobody is subscribed for, and the in-memory queue is
        # single-consumer. So a client that reconnects after the pause
        # — the browser's own EventSource retry after a wifi blip, or
        # after the server closed at `api_sse_max_duration_sec` — used
        # to get nothing but heartbeats until `api_hitl_timeout_sec`
        # killed the job 30 minutes later. Replaying the snapshot makes
        # the reconnect self-sufficient: the reviewer sees the plan and
        # can resolve it.
        #
        # The plan may legitimately arrive twice on the in-memory path
        # (this snapshot, then the queued frame the drainer below is
        # about to hand over, if no earlier client consumed it). That is
        # deliberate: the frame carries the whole plan, so a client
        # applying it twice lands in the same state, and dropping the
        # replay to avoid the duplicate would reopen the silence this
        # closes.
        if job.status == JobStatus.pending_review and job.plan is not None:
            yield format_sse("plan_ready", _plan_ready_data(job))

        # ADR 0057: the same replay for the same reason, one parking
        # over. A learner reloading the page mid-session is not an
        # edge case the way a reviewer's wifi blip is — it is the
        # expected shape of a daily habit (SR-01), and it happens once
        # per turn rather than once per run, so the silence this
        # closes would be the common case rather than the rare one.
        if job.status == JobStatus.awaiting_learner and job.turn is not None:
            yield format_sse("turn_ready", _turn_ready_data(job))

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
    # ADR 0043: conversations are durable writes, so they draw from
    # the same per-key hourly budget as `/research` submits. Without
    # this, a leaked key could accrete unbounded rows on the shared
    # Postgres with the limiter never firing. No-op under auth-off.
    await enforce_rate_limit(request, principal)
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
    summary="List conversations, newest first (no job bodies), paginated.",
)
async def list_conversations(
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
    limit: int = Query(
        DEFAULT_LIST_LIMIT,
        ge=1,
        le=MAX_LIST_LIMIT,
        description="Page size — at most this many conversations come back.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Rows to skip, counted within the caller's own "
        "conversations, newest first.",
    ),
) -> list[ConversationListItem]:
    state = _get_state(request)
    # ADR 0036: scope the list to the caller's principal. Auth-off
    # passes `None` and gets everything (legacy behavior). ADR 0043:
    # limit/offset ride into the store so Postgres applies
    # LIMIT/OFFSET in SQL instead of dragging the full table per
    # sidebar load.
    conversations = await state["conversation_store"].list(
        principal_key_id=_principal_key_id(principal),
        limit=limit,
        offset=offset,
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
    # ADR 0043 (closes the ADR 0036 follow-up): ownership is inline
    # in the store's DELETE — one statement instead of the old
    # fetch + delete pair, so there's no window where the row
    # changes hands between the check and the destructive call.
    # `False` covers both "missing" and "not yours"; both map to
    # the same 404 so the response never confirms the id exists
    # (ADR 0036's 404-not-403 rule).
    deleted = await state["conversation_store"].delete(
        conversation_id,
        principal_key_id=_principal_key_id(principal),
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="conversation_not_found"
        )
    log.info(
        "api_conversation_deleted",
        extra={"conversation_id": conversation_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Learner profile (Phase W, WO-W02, ADR 0058).
#
# There is no id in any of these paths. The profile is addressed by the
# caller's own authenticated principal and nothing else, so a client
# cannot name another principal's record — ADR 0036's scoping holds by
# the shape of the route rather than by a `_check_ownership` call that
# a future handler could forget to make. The tests assert it anyway.
# ---------------------------------------------------------------------------


def _profile_store(request: Request) -> Any:
    """Return the mounted profile store, or 404 when it is off.

    `enable_learner_profile=false` is not an error condition — the
    capability simply is not mounted, so the resource does not exist.
    404 rather than 503 because 503 promises "try again later", which
    would be a lie about a flag. The routes themselves always exist
    (SR-07: gating is backend-only), so the contract snapshot is
    stable in both flag positions.
    """
    if not settings.enable_learner_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="learner_profile_disabled",
        )
    # Read straight off `app.state` rather than through `_get_state`:
    # that helper resolves every key eagerly, so adding a required
    # attribute to it would break the hand-built partial states several
    # stream tests pass. Its own docstring says so.
    store = getattr(request.app.state, "profile_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="learner_profile_disabled",
        )
    return store


def _learner_key_id(caller: ApiKeyPrincipal | None) -> str:
    """The caller's principal key id, or refuse the request.

    Belt and braces behind the config validator: `settings` already
    refuses `enable_learner_profile` without `enable_api_auth`, so
    `caller` should never be `None` here. If some future wiring makes
    it possible, the profile still refuses the anonymous principal
    (01 §1.3) instead of writing a record everyone shares.
    """
    if caller is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="learner_profile_requires_auth",
        )
    return caller.key_id


def _profile_to_response(profile: LearnerProfile) -> LearnerProfileResponse:
    return LearnerProfileResponse(
        academic_level=profile.academic_level,
        time_budget_min_per_day=profile.time_budget_min_per_day,
        goals=[
            GoalClaim(
                goal_id=goal.goal_id,
                statement=goal.statement,
                target_date=goal.target_date,
                status=goal.status,
                priority=goal.priority,
            )
            for goal in profile.goals
        ],
        skills=[
            SkillClaim(
                skill=entry.skill,
                level=entry.level,
                source=entry.source,
                evidence_ref=entry.evidence_ref,
                confidence=entry.confidence,
                updated_at=entry.updated_at,
            )
            for entry in profile.skills
        ],
        profile_note=profile.profile_note,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get(
    "/learn/profile",
    response_model=LearnerProfileResponse,
    summary="The calling principal's learner profile.",
)
async def get_learner_profile(
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> LearnerProfileResponse:
    """Read the profile belonging to the presented API key.

    A learner who has never written one has none: the response is 404,
    which the client renders as the empty state. Inventing a blank row
    on read would make "the learner has told us nothing" and "the
    learner told us they are a beginner" indistinguishable.

    Every returned skill claim carries its `source`; there is no
    nullable provenance in the response schema. See ADR 0058.
    """
    store = _profile_store(request)
    profile = await store.get(_learner_key_id(principal))
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="learner_profile_not_found",
        )
    return _profile_to_response(profile)


@router.put(
    "/learn/profile",
    response_model=LearnerProfileResponse,
    summary="Replace what the learner has declared about themselves.",
)
async def put_learner_profile(
    body: ProfileUpdateRequest,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> LearnerProfileResponse:
    """Write the learner's own declarations.

    Everything this endpoint writes is `declared` by construction: the
    request schema has no provenance field, and the store's
    `replace_declared_skills` refuses a non-declared claim from this
    path. Inferred and assessed claims already on the profile survive
    the write untouched — the learner edits what they said, and the
    system's observations stand on their evidence (01 §1.2).

    Durable per-principal writes draw on the same per-key hourly
    budget as `POST /research`, so a leaked key cannot accrete rows on
    the shared Postgres with the limiter never firing (ADR 0043).
    """
    store = _profile_store(request)
    key_id = _learner_key_id(principal)
    await enforce_rate_limit(request, principal)

    now = utc_now_iso()
    try:
        profile = LearnerProfile(
            principal_key_id=key_id,
            academic_level=body.academic_level,
            time_budget_min_per_day=body.time_budget_min_per_day,
            goals=tuple(
                LearnerGoal(
                    goal_id=goal.goal_id or new_goal_id(),
                    statement=goal.statement,
                    target_date=goal.target_date,
                    status=goal.status,
                    priority=goal.priority,
                )
                for goal in body.goals
            ),
            skills=tuple(
                SkillEntry(
                    skill=skill.skill,
                    level=skill.level,
                    # Fixed, not read from the body. The wire format
                    # cannot express any other value.
                    source="declared",
                    evidence_ref="",
                    confidence=DECLARED_CONFIDENCE,
                    updated_at=now,
                )
                for skill in body.skills
            ),
            profile_note=body.profile_note,
        )
    except ValueError as exc:
        # Pydantic caught shape; this catches the domain rules the
        # schema cannot express (duplicate skills after normalisation,
        # a skill name that is not vocabulary-shaped, a bad ISO date).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    stored = await store.put(profile)
    log.info(
        "api_learner_profile_written",
        extra={
            "declared_skills": len(profile.skills),
            "goals": len(profile.goals),
        },
    )
    return _profile_to_response(stored)


@router.delete(
    "/learn/profile",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the calling principal's learner profile.",
)
async def delete_learner_profile(
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> Response:
    """Erase the profile — the first-class deletion 01 §1.4 promises.

    Removes the whole `learner_profiles` row: declarations, goals,
    inferred and assessed claims, and the free-text note. 204 whether
    or not a row existed, so the response never confirms whether a
    given principal had a profile.

    **What the promise does not cover**: the shared paper and
    embedding caches (`paper_cache`, `embedding_cache`) hold public
    arXiv text, are not per-user, and are untouched by this call — the
    caveat MT-01 §7.3 states and 01 §1.4 carries over. Progress events
    (WO-W07) join this promise when that table exists; the account-
    level deletion is this operation.
    """
    store = _profile_store(request)
    key_id = _learner_key_id(principal)
    deleted = await store.delete(key_id)
    log.info(
        "api_learner_profile_deleted", extra={"existed": deleted}
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/learn/progress",
    response_model=LearnerProgressSummary,
    summary="The learner's progress ledger, folded from its event log.",
)
async def get_learn_progress(
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
    limit: int = Query(
        DEFAULT_EVENT_LIMIT,
        ge=1,
        le=MAX_EVENT_LIMIT,
        description="How many events to fold into this summary, oldest first.",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Events to skip, counted within the caller's own ledger.",
    ),
) -> LearnerProgressSummary:
    """Read this principal's progress events and fold them into a view.

    There is no stored summary: the route reads the raw append-only log
    and hands it to `summarize`, a pure function. Every number that
    comes back carries the `event_ids` behind it, so a surface can
    expand any claim into the events that produced it — 01 §4.4's "no
    displayed claim without an event behind it".

    What this endpoint deliberately cannot return is a mastery or
    knowledge percentage (01 §4.1). `schedule_progress` is arithmetic
    about sessions and is named so the client cannot mistake it for
    knowledge.

    Gated on `settings.enable_learner_profile` (404 when off — the
    surface does not exist in that deployment) and scoped to the
    caller's principal (ADR 0036). With the flag on and
    `enable_api_auth` off there is no principal to scope to, and the
    ledger has no anonymous rows, so the route refuses with 503 rather
    than serving someone else's record.
    """
    if not settings.enable_learner_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="learner_profile_disabled",
        )
    key_id = _principal_key_id(principal)
    if key_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="learner_progress_requires_auth",
        )

    events = await _progress_event_store(request).list_events(
        key_id, limit=limit, offset=offset
    )
    return _summary_to_response(summarize(key_id, events))


def _progress_event_store(request: Request) -> ProgressEventStore:
    """The app's ledger, read lazily.

    Deliberately *not* part of `_get_state` — for the same reason
    `_degraded_dependencies` is not: that helper reads every key
    eagerly for every route, so a new required attribute there breaks
    apps assembled without the full lifespan (several SSE and health
    tests build exactly that). Only this route needs the ledger, so
    only this route reaches for it, and an app without one falls back
    to an empty in-process store rather than raising.
    """
    store: ProgressEventStore | None = getattr(
        request.app.state, "progress_event_store", None
    )
    if store is None:  # pragma: no cover - lifespan always sets it
        store = InMemoryProgressEventStore()
        request.app.state.progress_event_store = store
    return store


def _summary_to_response(summary: ProgressSummary) -> LearnerProgressSummary:
    """Serialize the store's view. A rename, not a computation.

    Kept mechanical on purpose: if the API layer were allowed to derive
    anything, the recomputability property would hold for the store and
    not for what the client actually sees.
    """
    return LearnerProgressSummary(
        principal_key_id=summary.principal_key_id,
        event_count=summary.event_count,
        sessions_per_day=[
            ProgressDailySessions(
                day=d.day, sessions=d.sessions, event_ids=list(d.event_ids)
            )
            for d in summary.sessions_per_day
        ],
        schedule_progress=[
            ProgressSchedule(
                path_id=p.path_id,
                sessions_completed=p.sessions_completed,
                sessions_planned=p.sessions_planned,
                schedule_label=p.schedule_label,
                assessments_recorded=p.assessments_recorded,
                event_ids=list(p.event_ids),
            )
            for p in summary.schedule_progress
        ],
        resource_observations=[
            ProgressResourceObservation(
                path_id=observation.path_id,
                resource_id=observation.resource_id,
                sessions_completed=observation.sessions_completed,
                last_observed_at=observation.last_observed_at,
                event_ids=list(observation.event_ids),
            )
            for observation in summary.resource_observations
        ],
        assessments=[_evidence_to_response(e) for e in summary.assessments],
        artifacts=[_evidence_to_response(e) for e in summary.artifacts],
    )


def _evidence_to_response(record: EvidenceRecord) -> ProgressEvidence:
    return ProgressEvidence(
        event_id=record.event_id,
        ts=record.ts,
        kind=record.kind,
        evidence_ref=record.evidence_ref,
        path_id=record.path_id,
    )


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


def _log_health_transitions(
    dependencies: dict[str, str], known_degraded: set[str]
) -> None:
    """Log dependency health *edges*, never the steady state (ADR 0053).

    `/healthz` reported a dead Redis in its response body and wrote
    nothing to the log, so an outage left no trace in the stream an
    operator greps after the fact — the evidence lived only in
    whatever scraped the endpoint. Logging every probe instead would
    be worse: the compose healthcheck polls every 15s, so a
    weekend-long outage would bury the timeline in ~17k identical
    lines.

    So this logs one WARNING when a dependency goes bad and one INFO
    when it comes back, naming the dependency both times. Only the
    exception *type* is carried, matching what the probe helpers
    return — ADR 0042 drops the message on purpose, because a
    connection error's text tends to contain the URL, and
    `redis_url` / `postgres_url` carry credentials inline.

    `known_degraded` is mutated in place; it is the app-lifetime set
    the caller owns. Concurrent probes could in principle both see the
    same edge and log it twice — the compose probe is one caller every
    15s, and a duplicate line is a far cheaper failure than a missed
    edge or a lock on the health path.

    Args:
        dependencies: This probe's per-dependency status strings, as
            they appear in the response body (`"ok"` or `"error: X"`).
        known_degraded: Names that were already degraded before this
            probe. Updated to match `dependencies` on return.
    """
    for name, dep_status in dependencies.items():
        if dep_status != "ok" and name not in known_degraded:
            known_degraded.add(name)
            log.warning(
                "api_health_dependency_degraded",
                extra={"dependency": name, "dependency_status": dep_status},
            )
        elif dep_status == "ok" and name in known_degraded:
            known_degraded.discard(name)
            log.info(
                "api_health_dependency_recovered",
                extra={"dependency": name},
            )
    # A dependency that stops being probed at all (Postgres after
    # `postgres_url` is cleared) must not stay latched as degraded, or
    # its eventual return would log a recovery for an edge nobody saw.
    known_degraded.intersection_update(dependencies)


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
    0 under the shipped Redis store — *plus* any node threads the
    runner gave up waiting on after a timeout drain expired (ADR
    0047). Those threads still hold a pool slot and still spend, so
    leaving them out would report free capacity this worker does not
    have; `abandoned_node_threads` breaks them out separately.
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

    # ADR 0053: the body already told the caller; the log stream did
    # not. Edges only — see `_log_health_transitions`.
    _log_health_transitions(dependencies, _degraded_dependencies(request))

    degraded = any(v != "ok" for v in dependencies.values())
    abandoned = abandoned_node_count()
    return HealthResponse(
        status="degraded" if degraded else "ok",
        active_jobs=len(state["tasks"]) + abandoned,
        abandoned_node_threads=abandoned,
        max_concurrent_jobs=state["max_concurrent_jobs"],
        dependencies=dependencies,
    )


def _terminal_event_name(job: Job) -> str:
    if job.status == JobStatus.succeeded:
        return "job_completed"
    if job.status == JobStatus.cancelled:
        return "job_cancelled"
    return "job_failed"


def _plan_ready_data(job: Job) -> dict[str, Any]:
    """The `plan_ready` payload, byte-identical to the runner's.

    `_handle_hitl_pause` publishes `{"job_id", "plan"}` with the plan
    normalized to two lists; the attach-time replay (ADR 0053) has to
    match, or a client would have to handle two shapes for one event
    name. Reads through `.get` because `job.plan` is a plain dict
    rehydrated from JSON, not a validated model.
    """
    plan = job.plan or {}
    return {
        "job_id": job.job_id,
        "plan": {
            "sub_questions": list(plan.get("sub_questions", [])),
            "search_queries": list(plan.get("search_queries", [])),
        },
    }


def _turn_ready_data(job: Job) -> dict[str, Any]:
    """The `turn_ready` payload, byte-identical to the runner's.

    Same contract as `_plan_ready_data`: one event name, one shape,
    whether the client was connected when the job parked or attached
    afterwards. The turn body itself is passed through unexamined —
    the session graph owns what a turn contains (WO-W03), and a route
    that normalized it would be a second, drifting definition of a
    shape it does not own.
    """
    return {"job_id": job.job_id, "turn": dict(job.turn or {})}


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


def _degraded_dependencies(request: Request) -> set[str]:
    """The app-lifetime set of dependencies currently known to be down.

    Deliberately *not* part of `_get_state`: that helper reads every
    key eagerly for every route, so a new required attribute there
    breaks any caller holding a partial app state — including the
    hand-built stubs several stream tests pass. This is read by
    `/healthz` alone (ADR 0053), so it stays a separate lookup and
    creates the set on first use for an app assembled without our
    lifespan (`TestClient` without a lifespan context, an ASGI mount
    in someone else's app). The set is stored back on `app.state`, so
    every later probe in that process sees the same edges.

    Args:
        request: The live request, for its app state.

    Returns:
        The mutable set the health handler latches edges in.
    """
    state = request.app.state
    known: set[str] | None = getattr(state, "degraded_dependencies", None)
    if known is None:
        known = set()
        state.degraded_dependencies = known
    return known
