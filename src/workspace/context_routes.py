"""Authenticated, model-free two-mode context and discovery endpoints."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.types.json import Jsonb

from src.workspace.context_schemas import (
    ContextEntryRevision,
    ContextEntryWrite,
    ContextIndex,
    ContextPreferences,
    ContextPreferencesWrite,
    ContextReadingRevision,
    ContextReadingWrite,
    ContextWorkPage,
    ContextWorkspaceState,
    LearningThread,
    LearningThreadWrite,
    ProductMode,
    ProjectArtifactWrite,
    ProjectDetail,
    ProjectEntryWrite,
    ProjectSourceWrite,
    ProjectUnlink,
    ProjectWrite,
)
from src.workspace.context_store import WorkspaceContext
from src.workspace.mode_ranking import MODE_POLICY_VERSION, rank_mode_items, select_mode_edition
from src.workspace.routes import call, owner, repository, snapshot
from src.workspace.store import digest

router = APIRouter(prefix="/workspace/context", tags=["workspace-context"])


def context_call(method: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return call(method, *args, **kwargs)
    except HTTPException as exc:
        if exc.status_code == 422 and exc.detail in {"project_unavailable", "learning_thread_unavailable"}:
            raise HTTPException(404, "context_unavailable") from exc
        raise


def context_repository() -> WorkspaceContext:
    return WorkspaceContext(repository())


def resolve(principal: str, mode: ProductMode | None, project: str, thread: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    store = context_repository()
    index = store.index(principal)
    resolved_mode = mode or index["preferences"]["data"]["default_mode"]
    selected = next((value for value in index["projects"] if value["id"] == project), None)
    selected_thread = next((value for value in index["threads"] if value["id"] == thread), None)
    unavailable = None
    if project and selected is None:
        unavailable = "project_unavailable"
    elif thread and selected_thread is None:
        unavailable = "learning_thread_unavailable"
    elif selected and selected_thread and selected_thread["data"]["origin"]["project_id"] != selected["id"]:
        unavailable = "learning_thread_project_context_mismatch"
    elif resolved_mode == "research" and selected is None:
        unavailable = "select_or_create_project"
    elif resolved_mode == "research" and selected and selected["data"]["status"] == "archived":
        unavailable = "project_archived"
    context = {"mode": resolved_mode, "project_id": project or None, "thread_id": thread or None, "project_revision": selected["revision"] if selected else None, "policy_version": MODE_POLICY_VERSION, "unavailable_reason": unavailable}
    return context, index, selected


def context_state(principal: str, mode: ProductMode | None, project: str, thread: str) -> dict[str, Any]:
    context, index, selected = resolve(principal, mode, project, thread)
    state = snapshot(principal)
    store = repository()
    all_works = context_repository().decorate(principal, state["works"])
    ranked = [] if context["unavailable_reason"] else rank_mode_items(all_works, state["profile"]["data"], product_mode=context["mode"], project=selected["data"] if selected else None, now=datetime.fromisoformat(state["as_of"]))
    by_id = {item["work_id"]: item for item in ranked}
    state["works"] = [by_id.get(work["work_id"], {**work, "reasons": [], "mode_relevance": {}}) for work in all_works]
    state["context"], state["active_edition"] = context, None
    if context["unavailable_reason"]:
        return state
    profile, preferences = state["profile"], index["preferences"]
    candidates_digest = digest(sorted((work["work_id"], work["version_id"], work.get("content_hash", "")) for work in all_works))
    key = digest({"context": context, "profile_revision": profile["revision"], "preferences_revision": preferences["revision"], "candidates": candidates_digest, "date": state["as_of"][:10]})
    with store.pool.connection() as conn:
        row = conn.execute("SELECT data FROM workspace_mode_editions WHERE owner=%s AND context_key=%s", (principal, key)).fetchone()
        if row:
            state["active_edition"] = row[0]
        else:
            chosen, allocation = select_mode_edition(ranked, profile["data"]["minutes"], product_mode=context["mode"], exploration=profile["data"]["exploration"])
            edition = {"id": "mode-edition-" + key[:32], "created_at": state["as_of"], "profile_revision": profile["revision"], "context_preferences_revision": preferences["revision"], "minutes": profile["data"]["minutes"], "work_ids": [work["work_id"] for work in chosen], "work_versions": {work["work_id"]: work["version_id"] for work in chosen}, "coverage": state["sources"], "status": "partial" if any(value.get("status") not in {"success", "ok", "empty", "not_modified"} for value in state["sources"]) else "ready", "allocation": allocation, "context": context, "candidate_digest": candidates_digest}
            conn.execute("INSERT INTO workspace_mode_editions(owner,context_key,data) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (principal, key, Jsonb(edition)))
            # A concurrent GET may have frozen the same context first.
            frozen = conn.execute("SELECT data FROM workspace_mode_editions WHERE owner=%s AND context_key=%s", (principal, key)).fetchone()
            if frozen is None:
                raise RuntimeError("mode edition freeze was not acknowledged")
            state["active_edition"] = frozen[0]
    return state


@router.get("", response_model=ContextIndex)
async def get_index(principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_repository().index, principal)


@router.post("/preferences", response_model=ContextPreferences)
async def save_preferences(write: ContextPreferencesWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().preferences, principal, write)


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def get_project(project_id: str, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().project, principal, project_id)


@router.post("/projects", response_model=ProjectDetail)
async def save_project(write: ProjectWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().write_project, principal, write)


@router.post("/projects/{project_id}/sources", response_model=ProjectDetail)
async def save_source(project_id: str, write: ProjectSourceWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().source, principal, project_id, write)


@router.post("/projects/{project_id}/unlink", response_model=ProjectDetail)
async def unlink_source(project_id: str, write: ProjectUnlink, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().unlink, principal, project_id, write)


@router.post("/projects/{project_id}/entries", response_model=ProjectDetail)
async def link_entry(project_id: str, write: ProjectEntryWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().entry, principal, project_id, write)


@router.post("/projects/{project_id}/artifacts", response_model=ProjectDetail)
async def save_artifact(project_id: str, write: ProjectArtifactWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().artifact, principal, project_id, write)


@router.get("/threads/{thread_id}", response_model=LearningThread)
async def get_thread(thread_id: str, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().thread, principal, thread_id)


@router.post("/threads", response_model=LearningThread)
async def save_thread(write: LearningThreadWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().write_thread, principal, write)


@router.post("/entries", response_model=ContextEntryRevision)
async def save_entry(write: ContextEntryWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().write_entry, principal, write)


@router.post("/reading", response_model=ContextReadingRevision)
async def save_reading(write: ContextReadingWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(context_call, context_repository().write_reading, principal, write)


@router.get("/state", response_model=ContextWorkspaceState)
async def get_state(principal: Annotated[str, Depends(owner)], mode: ProductMode | None = None, project: str = Query("", max_length=80), thread: str = Query("", max_length=80)) -> Any:
    return await asyncio.to_thread(context_state, principal, mode, project, thread)


@router.get("/items", response_model=ContextWorkPage)
async def get_items(
    principal: Annotated[str, Depends(owner)], mode: ProductMode | None = None,
    project: str = Query("", max_length=80), thread: str = Query("", max_length=80), q: str = Query("", max_length=500),
    source_id: str = Query("", max_length=120), access_state: str = Query("", max_length=30), status: str = Query("", max_length=30),
    days: int = Query(0, ge=0, le=365), cursor: str = Query("", max_length=2048), as_of: str = Query("", max_length=80), limit: int = Query(20, ge=1, le=50),
) -> Any:
    context, index, selected = await asyncio.to_thread(resolve, principal, mode, project, thread)
    if context["unavailable_reason"]:
        raise HTTPException(422, context["unavailable_reason"])
    store = repository()
    profile = await asyncio.to_thread(store.profile, principal)
    query_hash = digest({"context": context, "profile": profile, "preferences_revision": index["preferences"]["revision"], "q": q, "source_id": source_id, "access_state": access_state, "status": status, "days": days})
    offset, page_id = 0, ""
    cutoff = as_of or await asyncio.to_thread(store.cutoff)
    if cursor:
        try:
            payload = json.loads(base64.urlsafe_b64decode(cursor))
            page_id, offset = payload["snapshot_id"], payload["offset"]
            if payload["query"] != query_hash or not isinstance(page_id, str) or type(offset) is not int or not 0 <= offset <= 2000:
                raise ValueError("cursor_mismatch")
        except (ValueError, TypeError, KeyError, binascii.Error) as exc:
            raise HTTPException(422, "invalid_cursor_for_context_or_filters") from exc
        cutoff, ranked = await asyncio.to_thread(call, store.frozen_page, principal, page_id, query_hash)
        if as_of and as_of != cutoff:
            raise HTTPException(422, "cursor_cutoff_mismatch")
    else:
        try:
            clock = datetime.fromisoformat(cutoff)
            if clock.tzinfo is None:
                raise ValueError("timezone_required")
        except ValueError as exc:
            raise HTTPException(422, "invalid_as_of") from exc
        works = await asyncio.to_thread(store.works, principal, as_of=cutoff)
        works = await asyncio.to_thread(context_repository().decorate, principal, works)
        filtered = []
        for item in works:
            if source_id and item["source_id"] != source_id:
                continue
            if access_state and access_state not in item.get("available_scopes", [item.get("access_state")]):
                continue
            if status and item["reading"]["status"] != status:
                continue
            if q.casefold() not in (item["title"] + " " + item.get("abstract", "")).casefold():
                continue
            # Never use acquisition/identifier dates to claim known freshness.
            raw_date = item.get("updated_at") or item.get("published_at")
            if days:
                try:
                    known = datetime.fromisoformat(raw_date.replace("Z", "+00:00")) if raw_date else None
                    if known is None or known.tzinfo is None or known < clock - timedelta(days=days):
                        continue
                except (ValueError, AttributeError):
                    continue
            filtered.append(item)
        ranked = rank_mode_items(filtered, profile["data"], product_mode=context["mode"], project=selected["data"] if selected else None, now=clock)
        if len(ranked) > limit:
            page_id = await asyncio.to_thread(call, store.freeze_page, principal, query_hash, cutoff, ranked)
    next_cursor = base64.urlsafe_b64encode(json.dumps({"snapshot_id": page_id, "offset": offset + limit, "query": query_hash}).encode()).decode() if offset + limit < len(ranked) else None
    return {"items": ranked[offset:offset + limit], "next_cursor": next_cursor, "as_of": cutoff, "context": context}
