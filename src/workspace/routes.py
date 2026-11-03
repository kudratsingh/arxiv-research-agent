"""Authenticated personal workspace API. Generation remains unavailable without approval."""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from src.api.auth import ApiKeyPrincipal, enforce_rate_limit, require_principal
from src.config import settings
from src.tools.postgres_pool import get_pool
from src.workspace import scheduler
from src.workspace.executor import FakeExecutor, FakeJob, FakeRequestPreview
from src.workspace.intake import SOURCES, fetch_source, normalize_manual
from src.workspace.interests import coverage as interest_coverage
from src.workspace.materials_repository import WorkspaceMaterials
from src.workspace.ranking import TOPIC_TERMS, rank_items, select_edition
from src.workspace.reviews import WorkspaceReviews
from src.workspace.schemas import (
    Edition,
    EntryRevision,
    EntryWrite,
    FakePreviewRequest,
    FakeSubmitRequest,
    FeedbackWrite,
    GenerationRequest,
    ImportApply,
    ImportPreview,
    ImportRequest,
    ItemPage,
    ManualRequest,
    MaterialDocument,
    MaterialInfo,
    ProfileRevision,
    ProfileWrite,
    ReadingRevision,
    ReadingWrite,
    RefreshRequest,
    ReviewIndex,
    ReviewPacket,
    ReviewPrepare,
    ScheduleRevision,
    ScheduleWrite,
    UsefulnessFeedback,
    WorkItem,
    WorkspaceState,
)
from src.workspace.store import ConflictError, WorkspaceStore, digest, utc_now

router = APIRouter(prefix="/workspace", tags=["workspace"])
_store: WorkspaceStore | None = None


async def owner(request: Request, response: Response, principal: Annotated[ApiKeyPrincipal | None, Depends(require_principal)]) -> str:
    if not settings.enable_workspace:
        raise HTTPException(404, "workspace_disabled")
    if principal is None or not principal.key_id:
        raise HTTPException(403, "workspace_requires_named_authenticated_principal")
    response.headers["Cache-Control"] = "private, no-store"
    if request.method != "GET":
        await enforce_rate_limit(request, principal)
    return principal.key_id


def repository() -> WorkspaceStore:
    global _store
    if not settings.postgres_url:
        raise HTTPException(503, "workspace_postgres_required")
    if _store is None:
        _store = WorkspaceStore(get_pool())
    return _store


def call(method: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return method(*args, **kwargs)
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(422, str(exc)) from exc


def snapshot(principal: str) -> dict[str, Any]:
    store = repository()
    cutoff = store.cutoff()
    profile = store.profile(principal)
    all_works = store.works(principal, as_of=cutoff)
    ranked = {item["work_id"]: item for item in rank_items(all_works, profile["data"], include_hidden=True)}
    # Library/Reader must retain dismissed and excluded sources and their notes.
    works = [ranked.get(item["work_id"], item) for item in all_works]
    sources = store.sources()
    activity = store.activity(principal, as_of=cutoff)
    pinned = profile["data"].get("pinned_entry_id")
    pinned_activity = store.activity(principal, as_of=cutoff, entry_id=pinned, limit=1) if pinned else []
    thread_events = pinned_activity or activity
    latest = thread_events[0] if thread_events else None
    since = datetime.fromisoformat(cutoff) - timedelta(days=7)
    candidates = rank_items([item for item in all_works if item["source_id"] in SOURCES and datetime.fromisoformat(item["fetched_at"]) >= since], profile["data"], now=datetime.fromisoformat(cutoff))
    previews = [select_edition(candidates, minutes, exploration=profile["data"].get("exploration", 0.15))[1] for minutes in (5, 15, 45)]
    return {"principal_key_id": principal, "profile": profile, "works": works, "sources": sources, "editions": store.editions(principal), "schedule": scheduler.schedule(store, principal), "tasks": scheduler.tasks(store, principal), "generation": "approval_required", "as_of": cutoff,
            "activity": activity, "latest_activity": latest,
            "interest_coverage": interest_coverage(profile["data"], sources, TOPIC_TERMS, now=datetime.fromisoformat(cutoff)), "allocation_previews": previews}


@router.get("/state", response_model=WorkspaceState)
async def get_state(principal: Annotated[str, Depends(owner)]) -> Any:
    """Read the owner's private profile, reading records and current public candidates."""
    return await asyncio.to_thread(snapshot, principal)


@router.post("/profile", response_model=ProfileRevision)
async def save_profile(write: ProfileWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    """Create an interest revision with optimistic concurrency and retry identity."""
    return await asyncio.to_thread(call, repository().write_profile, principal, write)


@router.post("/reading", response_model=ReadingRevision)
async def save_reading(write: ReadingWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    """Save read state and a source-version anchor without moving existing notes."""
    return await asyncio.to_thread(call, repository().write_reading, principal, write)


@router.post("/entries", response_model=EntryRevision)
async def save_entry(write: EntryWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    """Save an authored note, question or next action against an immutable version."""
    return await asyncio.to_thread(call, repository().write_entry, principal, write)


@router.get("/review", response_model=ReviewIndex)
async def get_review(principal: Annotated[str, Depends(owner)], packet_id: str = Query("", max_length=80)) -> Any:
    """Read an existing private ten-item review; a GET never creates judgments or packets."""
    try:
        return await asyncio.to_thread(WorkspaceReviews(repository()).index, principal, packet_id or None)
    except KeyError as exc:
        raise HTTPException(404, "review_packet_not_found") from exc


@router.post("/review/prepare", response_model=ReviewPacket)
async def prepare_review(write: ReviewPrepare, principal: Annotated[str, Depends(owner)]) -> Any:
    """Freeze up to ten actual candidates with blank personal judgments, safely retried."""
    return await asyncio.to_thread(call, WorkspaceReviews(repository()).prepare, principal, write)


@router.post("/review/feedback", response_model=UsefulnessFeedback)
async def save_usefulness(write: FeedbackWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    """Record an explicit owner judgment against the frozen candidate/version."""
    return await asyncio.to_thread(call, WorkspaceReviews(repository()).save_feedback, principal, write)


def fake_call(method: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return call(method, *args, **kwargs)
    except HTTPException as exc:
        if exc.status_code == 422 and exc.detail == "fake_job_not_found":
            raise HTTPException(404, "fake_job_not_found") from exc
        if exc.status_code == 422 and exc.detail == "fake_lane_requires_disabled_key_sentinel":
            raise HTTPException(403, "fake_lane_requires_disabled_key_sentinel") from exc
        raise


@router.post("/generation/preview", response_model=FakeRequestPreview)
async def preview_fake_request(write: FakePreviewRequest, principal: Annotated[str, Depends(owner)]) -> Any:
    """Disclose exact retained source/context for the local synthetic pipeline; no provider exists."""
    executor = FakeExecutor(repository())
    return await asyncio.to_thread(fake_call, executor.preview, principal, write.kind, write.material_ids, span_ids=write.span_ids, question=write.question)


@router.post("/generation/jobs", response_model=FakeJob)
async def submit_fake_job(write: FakeSubmitRequest, principal: Annotated[str, Depends(owner)]) -> Any:
    """Reserve a separate zero-dollar fake job after exact request digest confirmation."""
    executor = FakeExecutor(repository())
    return await asyncio.to_thread(fake_call, executor.submit, principal, write.request_id, write.kind, write.material_ids, expected_digest=write.expected_digest, span_ids=write.span_ids, question=write.question)


@router.get("/generation/jobs", response_model=list[FakeJob])
async def list_fake_jobs(principal: Annotated[str, Depends(owner)]) -> Any:
    """Read this account's explicitly synthetic jobs and usage, independently of paid admission."""
    return await asyncio.to_thread(fake_call, FakeExecutor(repository()).list, principal)


@router.get("/generation/jobs/{job_id}", response_model=FakeJob)
async def get_fake_job(job_id: str, principal: Annotated[str, Depends(owner)]) -> Any:
    """Read a durable synthetic pipeline checkpoint without advancing it."""
    return await asyncio.to_thread(fake_call, FakeExecutor(repository()).get, principal, job_id)


@router.post("/generation/jobs/{job_id}/advance", response_model=FakeJob)
async def advance_fake_job(job_id: str, principal: Annotated[str, Depends(owner)]) -> Any:
    """Execute one bounded local fake step; SDK/provider construction is inaccessible."""
    return await asyncio.to_thread(fake_call, FakeExecutor(repository()).advance, principal, job_id)


@router.post("/generation/jobs/{job_id}/cancel", response_model=FakeJob)
async def cancel_fake_job(job_id: str, principal: Annotated[str, Depends(owner)]) -> Any:
    """Request cooperative cancellation and preserve incurred simulated usage."""
    return await asyncio.to_thread(fake_call, FakeExecutor(repository()).cancel, principal, job_id)


@router.post("/generation/jobs/{job_id}/recover", response_model=FakeJob)
async def recover_fake_job(job_id: str, principal: Annotated[str, Depends(owner)]) -> Any:
    """Fence interrupted local work without silently replaying an uncertain step."""
    return await asyncio.to_thread(fake_call, FakeExecutor(repository()).recover, principal, job_id)


@router.get("/materials", response_model=list[MaterialInfo])
async def list_materials(principal: Annotated[str, Depends(owner)], work_id: str = Query(..., min_length=1, max_length=300), version_id: str = Query(..., min_length=1, max_length=300)) -> Any:
    """List actual retained material for an exact source version, with scope/quality limits."""
    return await asyncio.to_thread(call, WorkspaceMaterials(repository()).list, principal, work_id, version_id)


@router.get("/materials/{material_id}", response_model=MaterialDocument)
async def get_material(material_id: str, principal: Annotated[str, Depends(owner)]) -> Any:
    """Read safe retained text and original-page offsets, never fetch a remote URL."""
    material = await asyncio.to_thread(call, WorkspaceMaterials(repository()).get, principal, material_id)
    if material is None:
        raise HTTPException(404, "retained_material_not_found")
    return material


def prepare_edition(store: WorkspaceStore, principal: str, *, persist: bool = True) -> dict[str, Any]:
    profile = store.profile(principal)
    cutoff = store.cutoff()
    since = datetime.fromisoformat(cutoff) - timedelta(days=7)
    candidates = [item for item in store.works(principal, as_of=cutoff) if item["source_id"] in SOURCES and datetime.fromisoformat(item["fetched_at"]) >= since]
    items = rank_items(candidates, profile["data"], now=datetime.fromisoformat(cutoff))
    selected, allocation = select_edition(items, profile["data"]["minutes"], exploration=profile["data"]["exploration"])
    return store.edition(principal, [item["work_id"] for item in selected], minutes=profile["data"]["minutes"], revision=profile["revision"], persist=persist, work_versions={item["work_id"]: item["version_id"] for item in selected}, as_of=cutoff, allocation=allocation)


def refresh(principal: str, source_ids: list[str], *, persist_edition: bool = True) -> dict[str, Any]:
    store = repository()
    requested = list(dict.fromkeys(source_ids or list(SOURCES)))
    if any(source_id not in SOURCES for source_id in requested):
        raise ValueError("source is not enabled in this bounded batch")
    previous = {source["source_id"]: source for source in store.sources()}
    for source_id in requested:
        retry_at = previous[source_id].get("receipt", {}).get("retry_after")
        if retry_at and datetime.fromisoformat(retry_at) > datetime.now(UTC):
            continue  # Stored Retry-After is binding across API/worker restarts.
        result = fetch_source(source_id, validators=store.validators(source_id))
        store.ingest(source_id, result.items, result.receipt, result.validators)
    return prepare_edition(store, principal, persist=persist_edition)


@router.post("/refresh", response_model=WorkspaceState)
async def refresh_sources(request: RefreshRequest, principal: Annotated[str, Depends(owner)]) -> Any:
    """Fetch at most one bounded page per approved connector; no model work occurs."""
    await asyncio.to_thread(call, refresh, principal, request.source_ids)
    return await asyncio.to_thread(snapshot, principal)


@router.post("/edition", response_model=Edition)
async def build_edition(principal: Annotated[str, Depends(owner)]) -> Any:
    """Freeze a finite metadata edition using the current profile and stored receipts."""
    return await asyncio.to_thread(prepare_edition, repository(), principal)


@router.get("/items", response_model=ItemPage)
async def list_items(
    principal: Annotated[str, Depends(owner)], q: str = Query("", max_length=500),
    source_id: str = "", access_state: str = "", status: str = "",
    days: int = Query(7, ge=0, le=365), cursor: str = Query("", max_length=2048), as_of: str = Query("", max_length=80),
    limit: int = Query(20, ge=1, le=50),
) -> Any:
    """Filter a stable observation cutoff with a cursor bound to the actual filters."""
    store = repository()
    cutoff = as_of or store.cutoff()
    query = {"q": q, "source_id": source_id, "access_state": access_state, "status": status, "days": days}
    offset = 0
    query_hash = digest(query)
    snapshot_id = ""
    if cursor:
        try:
            payload = json.loads(base64.urlsafe_b64decode(cursor))
            snapshot_id, offset = payload["snapshot_id"], payload["offset"]
            if payload["query"] != query_hash or not isinstance(snapshot_id, str) or type(offset) is not int or not 0 <= offset <= 2000:
                raise ValueError("cursor mismatch")
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, "invalid_cursor_for_filters") from exc
        cutoff, frozen = await asyncio.to_thread(call, store.frozen_page, principal, snapshot_id, query_hash)
        if as_of and as_of != cutoff:
            raise HTTPException(422, "cursor_cutoff_mismatch")
        next_cursor = base64.urlsafe_b64encode(json.dumps({"snapshot_id": snapshot_id, "offset": offset + limit, "query": query_hash}).encode()).decode() if offset + limit < len(frozen) else None
        return {"items": frozen[offset:offset + limit], "next_cursor": next_cursor, "as_of": cutoff}
    try:
        parsed_cutoff = datetime.fromisoformat(cutoff)
        if parsed_cutoff.tzinfo is None:
            raise ValueError("cutoff requires timezone")
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "invalid_as_of") from exc
    items = await asyncio.to_thread(store.works, principal, as_of=cutoff)
    filtered = []
    for item in items:
        date = item.get("updated_at") or item.get("announced_at") or item.get("published_at") or item.get("first_seen_at")
        if source_id and item["source_id"] != source_id:
            continue
        if access_state and access_state not in item.get("available_scopes", [item.get("access_state")]):
            continue
        if status and item.get("reading", {}).get("status", "unread") != status:
            continue
        if q.casefold() not in (item["title"] + " " + item.get("abstract", "")).casefold():
            continue
        if days and date and datetime.fromisoformat(date) < parsed_cutoff - timedelta(days=days):
            continue
        filtered.append(item)
    filtered.sort(key=lambda item: (item["first_seen_at"], item["work_id"]), reverse=True)
    next_cursor = None
    if limit < len(filtered):
        snapshot_id = await asyncio.to_thread(call, store.freeze_page, principal, query_hash, cutoff, filtered)
        next_cursor = base64.urlsafe_b64encode(json.dumps({"snapshot_id": snapshot_id, "offset": limit, "query": query_hash}).encode()).decode()
    return {"items": filtered[:limit], "next_cursor": next_cursor, "as_of": cutoff}


@router.post("/manual", response_model=WorkItem)
async def manual_save(request: ManualRequest, principal: Annotated[str, Depends(owner)]) -> Any:
    """Save a controlled identifier as honest metadata/link-only; no arbitrary URL fetch."""
    item = call(normalize_manual, request.value)
    requested_version = item["version_id"] if item["version_label"].startswith("v") else None
    store = repository()
    existing = next((work for work in await asyncio.to_thread(store.works, principal) if work["work_id"] == item["work_id"]), None)
    if existing and requested_version and not any(version["version_id"] == requested_version for version in existing["versions"]):
        existing = None  # A link to an unacquired version stays visibly link-only.
    # Manual imports are private; URL/title similarity never merges private records.
    if existing:
        item = existing
    else:
        item["work_id"] = "manual:" + digest([principal, item["work_id"]])[:40]
        item["version_id"] = item["work_id"] + ":" + (item["version_label"] if requested_version else "link-" + item["content_hash"][:16])
        item["source_record_id"] = item["work_id"] + ":" + item["content_hash"][:16]
        item["visibility_owner"] = principal
        await asyncio.to_thread(store.ingest, "manual", [item], {"status": "success", "fetched_at": utc_now(), "limitation": "link-only; no document acquired"}, {})
        existing = next(work for work in await asyncio.to_thread(store.works, principal) if work["work_id"] == item["work_id"])
    from src.workspace.schemas import ReadingData
    current = existing["reading"]
    selected_version = requested_version if requested_version and any(version["version_id"] == requested_version for version in existing["versions"]) else item["version_id"]
    if current["status"] != "saved" or current["version_id"] != selected_version:
        write = ReadingWrite(work_id=item["work_id"], revision=current["revision"], request_id="manual:" + digest([item["work_id"], current["revision"], selected_version]), data=ReadingData(status="saved", version_id=selected_version, anchor=current["anchor"]))
        await asyncio.to_thread(call, store.write_reading, principal, write)
    return next(work for work in await asyncio.to_thread(store.works, principal) if work["work_id"] == item["work_id"])


@router.post("/import/preview", response_model=ImportPreview)
async def preview_import(request: ImportRequest, principal: Annotated[str, Depends(owner)]) -> Any:
    """Show an explicit import diff without modifying either browser or server records."""
    return await asyncio.to_thread(call, repository().import_preview, principal, request)


@router.post("/import/apply", response_model=ImportPreview)
async def apply_import(request: ImportApply, principal: Annotated[str, Depends(owner)]) -> Any:
    """Apply the reviewed import once; conflicting private notes remain untouched."""
    return await asyncio.to_thread(call, repository().import_apply, principal, ImportRequest(**request.model_dump(exclude={"digest"})), request.digest)


@router.post("/schedule", response_model=ScheduleRevision)
async def save_schedule(write: ScheduleWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    """Persist local scheduling preferences; activation requires separate owner confirmation."""
    return await asyncio.to_thread(call, scheduler.write_schedule, repository(), principal, write, approved=settings.workspace_schedule_approved)


@router.get("/export", response_class=PlainTextResponse)
async def export_notes(principal: Annotated[str, Depends(owner)]) -> str:
    """Export authored text with the exact work/version/anchor context and source URL."""
    store = repository()
    profile = await asyncio.to_thread(store.profile, principal)
    works = await asyncio.to_thread(store.works, principal)
    lines = ["# Personal research workspace", "", profile["data"]["research_question"], ""]
    for work in works:
        if work["entries"] or work["reading"].get("status") == "saved":
            lines.extend(["## " + work["title"], "", work["url"], "Work: " + work["work_id"], ""])
            for entry in work["entries"]:
                lines.extend(["### " + entry["kind"], "Version: " + entry["version_id"] + " · anchor: " + entry["anchor"], "", entry["body"], ""])
    return "\n".join(lines)


@router.post("/generate", status_code=403)
async def request_generation(request: GenerationRequest, principal: Annotated[str, Depends(owner)]) -> Any:
    """Refuse before importing or constructing any provider; a key is never approval."""
    raise HTTPException(403, "generation_approval_required: model, source scope, per-job/day/month ceilings and a specific owner GO are required")
