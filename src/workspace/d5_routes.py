"""Read-only quarantine API. No dispatch, approval, replay or cancel endpoint."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.workspace.d5_results import QualificationResults
from src.workspace.routes import call, owner, repository

router = APIRouter(prefix="/workspace/qualification", tags=["workspace-qualification-results"])


@router.get("/results")
async def results(principal: Annotated[str, Depends(owner)], work_id: str, version_id: str) -> Any:
    return await asyncio.to_thread(
        call, QualificationResults(repository()).jobs, principal, work_id, version_id
    )


@router.get("/results/{job_id}")
async def result(job_id: str, principal: Annotated[str, Depends(owner)]) -> Any:
    return await asyncio.to_thread(
        call, QualificationResults(repository()).snapshot, principal, job_id
    )
