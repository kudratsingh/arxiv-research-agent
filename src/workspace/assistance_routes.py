"""Offline-only D5 endpoints; previews never submit or advance a job."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.workspace.assistance import AssistanceService, PreviewWrite, SubmitWrite
from src.workspace.routes import call, owner, repository

router = APIRouter(prefix="/workspace/assistance", tags=["workspace-assistance"])


@router.get("/catalog")
async def catalog(
    principal: Annotated[str, Depends(owner)],
    work_id: str,
    version_id: str,
    project: str | None = None,
) -> Any:
    return await asyncio.to_thread(
        call, AssistanceService(repository()).catalog, principal, work_id, version_id, project
    )


@router.post("/preview")
async def preview(write: PreviewWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(
        call, AssistanceService(repository()).preview, principal, write.input
    )


@router.post("/jobs")
async def submit(write: SubmitWrite, principal: Annotated[str, Depends(owner)]) -> Any:
    def submit_and_read() -> Any:
        service = AssistanceService(repository())
        created = service.submit(principal, write)
        return service.get(principal, created.id)

    return await asyncio.to_thread(call, submit_and_read)


@router.get("/jobs")
async def jobs(principal: Annotated[str, Depends(owner)], work_id: str, version_id: str) -> Any:
    return await asyncio.to_thread(
        call, AssistanceService(repository()).jobs, principal, work_id, version_id
    )


@router.get("/jobs/{job_id}")
async def job(job_id: str, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(call, AssistanceService(repository()).get, principal, job_id)


@router.post("/jobs/{job_id}/{action}")
async def action(job_id: str, action: str, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(
        call, AssistanceService(repository()).action, principal, job_id, action
    )
