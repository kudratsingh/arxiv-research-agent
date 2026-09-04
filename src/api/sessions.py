"""HTTP contract for starting and resuming guided-read sessions (WO-W03)."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.api.auth import (
    ApiKeyPrincipal,
    enforce_rate_limit,
    require_principal,
)
from src.api.jobs import Job, JobStatus
from src.api.runner import run_job
from src.config import settings
from src.content.loader import LoadedPath, loaded_paths
from src.content.schema import ContentValidationError, Entry
from src.errors import (
    BriefingCompanionRequired,
    LearnContentInvalid,
    LearnerProfileRequired,
    LearnPathNotFound,
    LearnResourceNotFound,
    SessionLoopDisabled,
    SessionLoopRequiresAuth,
    SessionNotAwaitingLearner,
    SessionNotFound,
    state_conflict_message,
)
from src.learning.memory import build_tier1_memory, latest_session_summary
from src.learning.profile_store import skill_entry_from_mapping
from src.learning.progress_store import ProgressEvent
from src.observability import get_logger

log = get_logger(__name__)
router = APIRouter()

# ADR 0064 moved these five strings into `src/errors.py` as codes on
# `AppError` subclasses. They stay bound here under their old names
# because they are part of this module's public surface — several tests
# import them to assert a response body — and because the code IS the
# detail, so the two can no longer drift.
DISABLED_DETAIL = SessionLoopDisabled.code
PROFILE_REQUIRED_DETAIL = LearnerProfileRequired.code
CONTENT_INVALID_DETAIL = LearnContentInvalid.code
PATH_NOT_FOUND_DETAIL = LearnPathNotFound.code
RESOURCE_NOT_FOUND_DETAIL = LearnResourceNotFound.code


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SessionCreateRequest(_Strict):
    path_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9-]+$")
    resource_id: str = Field(min_length=1, max_length=128)
    available_minutes: int | None = Field(default=None, ge=5, le=180)


class SessionAccepted(_Strict):
    session_id: str
    status: str
    status_url: str
    stream_url: str


class SessionTurnRequest(_Strict):
    message: str = Field(default="", max_length=4_000)
    end_session: bool = False

    @model_validator(mode="after")
    def _reply_or_end(self) -> SessionTurnRequest:
        if not self.end_session and not self.message.strip():
            raise ValueError("message is required unless end_session=true")
        return self


class SessionTurnAccepted(_Strict):
    session_id: str
    status: str
    accepted: bool


class SessionTranscriptEntry(_Strict):
    role: Literal["learner", "tutor"]
    text: str


class SessionDetail(_Strict):
    session_id: str
    status: str
    kind: Literal["session"]
    path_id: str
    resource_id: str
    title: str
    created_at: float
    started_at: float | None
    completed_at: float | None
    elapsed_sec: float | None
    turn: dict[str, Any] | None
    transcript: list[SessionTranscriptEntry]
    transcript_status: Literal["available", "unavailable"]
    assessment_status: Literal["", "recorded_ungraded", "unassessed", "assessed"]
    result: str | None
    error: str | None
    error_type: str | None
    cost_cap_status: Literal["", "refused", "degraded_close"]
    cost_cap_message: str | None
    cost_usd: float | None
    llm_calls: int | None


def _require_session_enabled() -> None:
    if not settings.enable_session_loop:
        raise SessionLoopDisabled()


def _principal_id(principal: ApiKeyPrincipal | None) -> str:
    if principal is None:
        # Config validation already makes this impossible for a correctly
        # configured session deployment. Keep the data boundary defensive.
        raise SessionLoopRequiresAuth(
            log_detail="enable_session_loop is on without an authenticated principal"
        )
    return principal.key_id


def _owned_session(job: Job | None, principal: ApiKeyPrincipal | None) -> Job:
    if job is None or job.kind != "session":
        raise SessionNotFound()
    if settings.enable_api_auth and (principal is None or job.principal_key_id != principal.key_id):
        # Same 404-not-403 rule as `routes._check_ownership`: another
        # principal's session must read as "does not exist".
        raise SessionNotFound()
    return job


async def _content_entry(path_id: str, resource_id: str) -> tuple[LoadedPath, Entry]:
    try:
        paths = await asyncio.to_thread(loaded_paths)
    except ContentValidationError as exc:
        log.error("learn_content_invalid", extra={"rule": exc.rule, "error": str(exc)})
        raise LearnContentInvalid(log_detail=f"{exc.rule}: {exc}") from exc
    path = paths.get(path_id)
    if path is None or path.manifest.status != "published":
        raise LearnPathNotFound()
    entry = next(
        (
            candidate
            for candidate in path.manifest.servable_entries
            if candidate.resource_id == resource_id
        ),
        None,
    )
    if entry is None:
        raise LearnResourceNotFound()
    if path.servable_briefing(entry) is None:
        raise BriefingCompanionRequired()
    return path, entry


def _reading_guidance(path: LoadedPath, entry: Entry) -> list[dict[str, str]]:
    """Extract bounded close/skim guidance from the validated companion."""
    briefing = path.servable_briefing(entry)
    body = briefing.body if briefing is not None else ""
    guidance: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$", body, re.MULTILINE):
        name = " ".join(match.group(1).split()).strip()
        instruction = " ".join(match.group(2).split()).strip().lower()
        if not name or name.lower() in {"section", "placeholder section"}:
            continue
        mode = "skim" if "skim" in instruction else "close"
        key = name.lower()
        if key not in seen:
            seen.add(key)
            guidance.append({"name": name[:80], "mode": mode})
    if guidance:
        return guidance[:8]

    # The fixture companion names these detected chunker sections in prose.
    # Only include names actually present; this is extraction, not invention.
    for section in ("Introduction", "Method", "Results", "Discussion", "Conclusion"):
        if re.search(rf"\b{section}\b", body, re.IGNORECASE):
            guidance.append({"name": section, "mode": "close" if not guidance else "skim"})
    return guidance[:8] or [{"name": "paper overview", "mode": "skim"}]


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts).strip()


def _transcript(values: dict[str, Any]) -> list[SessionTranscriptEntry]:
    messages = values.get("messages")
    if not isinstance(messages, list):
        return []
    entries: list[SessionTranscriptEntry] = []
    for message in messages:
        name = getattr(message, "name", None)
        message_type = getattr(message, "type", None)
        # The check-in message is an internal plan receipt ("Planned N
        # sections"), not something the tutor presented to the learner.
        if name == "check_in":
            continue
        learner = message_type == "human" or (
            isinstance(name, str) and name.startswith("learner")
        )
        tutor = message_type == "ai" or name in {"check_in", "tutor"}
        if not learner and not tutor:
            continue
        text = _message_text(message)
        if not text:
            continue
        entries.append(
            SessionTranscriptEntry(
                role="learner" if learner else "tutor",
                text=text,
            )
        )
    return entries


def _assessment_status(
    values: dict[str, Any],
) -> Literal["", "recorded_ungraded", "unassessed", "assessed"]:
    assessment = values.get("assessment")
    if not isinstance(assessment, dict):
        return ""
    status_value = assessment.get("status")
    if status_value == "recorded_ungraded":
        return "recorded_ungraded"
    if status_value == "unassessed":
        return "unassessed"
    if status_value in {"assessed", "recorded"}:
        return "assessed"
    return ""


async def _checkpoint_values(request: Request, job: Job) -> tuple[dict[str, Any], bool]:
    workflow = getattr(request.app.state, "session_workflow", None)
    read_state = getattr(workflow, "aget_state", None)
    if not callable(read_state):
        return {}, False
    try:
        snapshot = await read_state({"configurable": {"thread_id": job.job_id}})
    except Exception:  # noqa: BLE001 - snapshot loss must not hide the job row
        log.warning(
            "api_session_transcript_unavailable",
            extra={"job_id": job.job_id},
            exc_info=True,
        )
        return {}, False
    values = getattr(snapshot, "values", None)
    return (dict(values), True) if isinstance(values, Mapping) else ({}, False)


def _session_detail(
    job: Job,
    checkpoint_values: dict[str, Any] | None = None,
    *,
    transcript_available: bool = True,
) -> SessionDetail:
    spec = job.input_payload.get("session_spec", {})
    values = checkpoint_values or {}
    return SessionDetail(
        session_id=job.job_id,
        status=job.status.value,
        kind="session",
        path_id=str(spec.get("path_id") or ""),
        resource_id=str(spec.get("resource_id") or ""),
        title=str(spec.get("title") or ""),
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        elapsed_sec=job.elapsed_sec(),
        turn=job.turn,
        transcript=_transcript(values),
        transcript_status="available" if transcript_available else "unavailable",
        assessment_status=_assessment_status(values),
        result=job.result,
        error=job.error,
        error_type=job.error_type,
        cost_cap_status=job.cost_cap_status,
        cost_cap_message=job.cost_cap_message,
        cost_usd=job.cost_usd,
        llm_calls=job.llm_calls,
    )


@router.post(
    "/learn/sessions",
    response_model=SessionAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start one checkpointed guided-read session.",
)
async def create_session(
    body: SessionCreateRequest,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> SessionAccepted:
    _require_session_enabled()
    principal_id = _principal_id(principal)
    await enforce_rate_limit(request, principal)

    profile_store = getattr(request.app.state, "profile_store", None)
    if profile_store is None:
        raise LearnerProfileRequired()
    profile = await profile_store.get(principal_id)
    if profile is None:
        raise LearnerProfileRequired()
    path, entry = await _content_entry(body.path_id, body.resource_id)
    briefing = path.servable_briefing(entry)

    session_id = uuid.uuid4().hex[:16]
    minutes = body.available_minutes or profile.time_budget_min_per_day or 20
    session_spec = {
        "path_id": path.path_id,
        "resource_id": entry.resource_id,
        "title": entry.title,
        "canonical_url": entry.canonical_url,
        "briefing_companion": entry.briefing_file,
        "briefing_label": (briefing.header.label if briefing is not None else ""),
        "reading_guidance": _reading_guidance(path, entry),
        "available_minutes": minutes,
        "path_position": entry.position,
        "path_entry_count": len(path.manifest.servable_entries),
    }
    progress_store = request.app.state.progress_event_store
    prior_events = await progress_store.list_events(principal_id, limit=2_000)
    tier1 = build_tier1_memory(
        profile,
        active_path_position={
            "path_id": path.path_id,
            "resource_id": entry.resource_id,
            "position": entry.position,
            "entry_count": len(path.manifest.servable_entries),
        },
        session_spec=session_spec,
        last_session_summary=latest_session_summary(prior_events),
    )
    job = Job(
        job_id=session_id,
        query=f"Guided read: {entry.title}",
        kind="session",
        principal_key_id=principal_id,
        input_payload={
            "principal_key_id": principal_id,
            "tier1": tier1,
            "session_spec": session_spec,
        },
    )
    store = request.app.state.store
    await store.create(job)
    task = asyncio.create_task(
        run_job(
            job,
            workflow=request.app.state.session_workflow,
            store=store,
            semaphore=request.app.state.semaphore,
            progress_event_store=request.app.state.progress_event_store,
            progress_event_decoder=ProgressEvent.from_json_dict,
            profile_store=profile_store,
            profile_skill_decoder=skill_entry_from_mapping,
        ),
        name=f"session-{job.job_id}",
    )
    request.app.state.tasks.add(task)
    task.add_done_callback(request.app.state.tasks.discard)
    log.info(
        "api_session_submitted",
        extra={"job_id": job.job_id, "path_id": path.path_id, "resource_id": entry.resource_id},
    )
    return SessionAccepted(
        session_id=job.job_id,
        status=job.status.value,
        status_url=f"/learn/sessions/{job.job_id}",
        # W03 deliberately reuses the hardened SSE transport. W13 consumes it.
        stream_url=f"/research/{job.job_id}/stream",
    )


@router.get(
    "/learn/sessions/{session_id}",
    response_model=SessionDetail,
    summary="Read one guided session and its currently parked turn.",
)
async def get_session(
    session_id: str,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> SessionDetail:
    _require_session_enabled()
    job = _owned_session(await request.app.state.store.get(session_id), principal)
    values, available = await _checkpoint_values(request, job)
    return _session_detail(job, values, transcript_available=available)


@router.post(
    "/learn/sessions/{session_id}/turn",
    response_model=SessionTurnAccepted,
    summary="Resume a parked guided session with the learner's reply.",
)
async def submit_turn(
    session_id: str,
    body: SessionTurnRequest,
    request: Request,
    principal: ApiKeyPrincipal | None = Depends(require_principal),
) -> SessionTurnAccepted:
    _require_session_enabled()
    await enforce_rate_limit(request, principal)
    store = request.app.state.store
    job = _owned_session(await store.get(session_id), principal)
    if job.status != JobStatus.awaiting_learner:
        # The second of the two `detail` strings that keep a
        # `(status=...)` suffix — see `routes._state_conflict_message`
        # and ADR 0064.
        raise SessionNotAwaitingLearner(
            public_message=state_conflict_message(
                "send a turn", job.status.value
            ),
            wire_detail=f"{SessionNotAwaitingLearner.code} (status={job.status.value})",
        )
    job.resume_payload = {
        "learner_reply": body.message.strip(),
        "end_requested": body.end_session,
    }
    await store.update(job)

    publish = getattr(store, "publish_remote_resume", None)
    if callable(publish):
        try:
            await publish(job.job_id, "turn", None, job.resume_payload)
        except Exception:
            log.error(
                "session_resume_publish_failed",
                exc_info=True,
                extra={"job_id": job.job_id},
            )
    job.resume_event.set()
    log.info(
        "api_session_turn_submitted",
        extra={"job_id": job.job_id, "end_session": body.end_session},
    )
    return SessionTurnAccepted(
        session_id=job.job_id,
        status=job.status.value,
        accepted=True,
    )
