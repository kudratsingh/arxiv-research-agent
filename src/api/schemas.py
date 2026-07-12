"""Pydantic request/response schemas for the HTTP API.

Small, deliberate — the API is a thin surface over the workflow, so
schemas do input validation and response serialization but no
business logic.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# Bounded query length so a malformed client can't hand the workflow
# a novel. 8k is comfortably above realistic research questions
# (which are usually one or two sentences) and cheap to validate.
MAX_QUERY_LEN = 8_000


class ResearchRequest(BaseModel):
    """Body for `POST /research`."""

    query: str = Field(
        min_length=1,
        max_length=MAX_QUERY_LEN,
        description="Natural-language research question",
    )
    hitl_bypass: bool = Field(
        default=False,
        description=(
            "Skip the HITL plan-review pause even when `enable_hitl` is on. "
            "The eval runner + other programmatic callers use this so they "
            "don't stall waiting for a human. See ADR 0030."
        ),
    )


class ResearchAccepted(BaseModel):
    """`POST /research` response — 202 Accepted, work now in flight."""

    job_id: str
    status: str
    status_url: str
    stream_url: str


class Plan(BaseModel):
    """The planner's output, exposed for HITL review (ADR 0030)."""

    sub_questions: list[str] = Field(
        default_factory=list,
        description="Planner-decomposed sub-questions",
    )
    search_queries: list[str] = Field(
        default_factory=list,
        description="Planner-generated arXiv search queries",
    )


class JobDetail(BaseModel):
    """`GET /research/{job_id}` — full lifecycle snapshot."""

    job_id: str
    status: str
    query: str
    created_at: float
    started_at: float | None = None
    completed_at: float | None = None
    elapsed_sec: float | None = None
    result: str | None = None
    error: str | None = None
    error_type: str | None = None
    cost_usd: float | None = None
    llm_calls: int | None = None
    iterations: int | None = None
    quality_score: float | None = None
    plan: Plan | None = Field(
        default=None,
        description=(
            "Populated when `status=pending_review`. See ADR 0030."
        ),
    )


class ReviewRequest(BaseModel):
    """Body for `POST /research/{job_id}/review` (ADR 0030)."""

    action: str = Field(
        pattern="^(approve|revise|cancel)$",
        description="`approve` = resume as-is; `revise` = apply `plan` "
        "and resume; `cancel` = abandon the run.",
    )
    plan: Plan | None = Field(
        default=None,
        description="Required when `action=revise`. Ignored otherwise.",
    )


class ReviewResponse(BaseModel):
    """Response for `POST /research/{job_id}/review`."""

    job_id: str
    status: str
    action: str


class HealthResponse(BaseModel):
    status: str
    active_jobs: int
    max_concurrent_jobs: int


class ErrorBody(BaseModel):
    """Uniform error body — `detail` per FastAPI convention plus a
    machine-readable `code` so clients can branch without regexing
    English text."""

    detail: str
    code: str


def make_error(status: int, code: str, detail: str) -> dict[str, Any]:
    """Envelope for `HTTPException(status, detail=...)` payloads."""
    return {"detail": detail, "code": code, "status": status}
