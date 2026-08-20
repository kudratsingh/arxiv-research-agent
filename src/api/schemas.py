"""Pydantic request/response schemas for the HTTP API.

Small, deliberate — the API is a thin surface over the workflow, so
schemas do input validation and response serialization but no
business logic.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

# Bounded query length so a malformed client can't hand the workflow
# a novel. 8k is comfortably above realistic research questions
# (which are usually one or two sentences) and cheap to validate.
MAX_QUERY_LEN = 8_000

# Bounds on the HITL plan lists (ADR 0042). The planner emits 2-6
# sub-questions and 2-6 search queries, each a short sentence — 20
# items of 500 chars each is generous headroom over anything the
# workflow produces. Without a cap, `POST /research/{id}/review`
# with `action=revise` would accept an arbitrarily large plan that
# the search node walks one arXiv call + `time.sleep(3)` at a time
# on an executor thread the job timeout cannot cancel.
MAX_PLAN_ITEMS = 20
MAX_PLAN_ITEM_LEN = 500

# One plan entry: a single sub-question or arXiv search query.
PlanItem = Annotated[str, Field(max_length=MAX_PLAN_ITEM_LEN)]


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
    conversation_id: str | None = Field(
        default=None,
        description=(
            "Run this query as a follow-up in an existing conversation. "
            "Prior-report chunks from the same conversation are retrieved "
            "and prepended to the planner's system prompt. See ADR 0032."
        ),
    )


class ResearchAccepted(BaseModel):
    """`POST /research` response — 202 Accepted, work now in flight."""

    job_id: str
    status: str
    status_url: str
    stream_url: str


class Plan(BaseModel):
    """The planner's output, exposed for HITL review (ADR 0030).

    Both lists are bounded (ADR 0042): each search query costs one
    arXiv HTTP call plus a hard 3s politeness sleep on an executor
    thread, so an unbounded revised plan is a resource-exhaustion
    vector, not just bad input.
    """

    sub_questions: list[PlanItem] = Field(
        default_factory=list,
        max_length=MAX_PLAN_ITEMS,
        description=(
            "Planner-decomposed sub-questions. The planner emits 2-6; "
            f"the cap of {MAX_PLAN_ITEMS} items x {MAX_PLAN_ITEM_LEN} "
            "chars is generous headroom (ADR 0042)."
        ),
    )
    search_queries: list[PlanItem] = Field(
        default_factory=list,
        max_length=MAX_PLAN_ITEMS,
        description=(
            "Planner-generated arXiv search queries. The planner emits "
            f"2-6; the cap of {MAX_PLAN_ITEMS} items x "
            f"{MAX_PLAN_ITEM_LEN} chars is generous headroom "
            "(ADR 0042)."
        ),
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
    conversation_id: str | None = Field(
        default=None,
        description="If the job runs in a conversation, its id. See ADR 0032.",
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
    """Response for `POST /research/{job_id}/review`.

    `status` is the job's status *at the moment the review was
    accepted* — always `pending_review` — not the post-resume state.
    The resume is asynchronous: the runner applies the action after
    this response is written, so clients should poll `status_url`
    (or watch the SSE stream) for the settled outcome rather than
    asserting on this snapshot.
    """

    job_id: str
    status: str = Field(
        description=(
            "Snapshot of the job's status when the review was "
            "accepted (always `pending_review`). The action is "
            "applied asynchronously — poll the job for the settled "
            "state."
        ),
    )
    action: str


# ---------------------------------------------------------------------------
# Conversation schemas (Sprint 5 PR 4, ADR 0032).
# ---------------------------------------------------------------------------

MAX_TITLE_LEN = 80


class ConversationCreateRequest(BaseModel):
    """Body for `POST /conversations`. Both fields optional — a
    conversation can be seeded blank (title auto-derives from the
    first job's query) or with an explicit title."""

    title: str | None = Field(
        default=None,
        max_length=MAX_TITLE_LEN,
        description="Optional display title. Auto-derived from first "
        "job's query when omitted.",
    )


class ConversationJobSummary(BaseModel):
    """Trimmed view of a conversation's job — sidebar-friendly."""

    job_id: str
    ordinal: int
    query: str
    report: str
    created_at: float


class ConversationDetail(BaseModel):
    """`GET /conversations/{id}` — full thread."""

    conversation_id: str
    title: str
    created_at: float
    updated_at: float
    jobs: list[ConversationJobSummary] = Field(default_factory=list)


class ConversationListItem(BaseModel):
    """`GET /conversations` — sidebar entry, no job bodies."""

    conversation_id: str
    title: str
    created_at: float
    updated_at: float


class HealthResponse(BaseModel):
    """`GET /healthz` — process liveness + dependency visibility (ADR 0042).

    `status` is `ok` when every checked dependency answered its ping,
    `degraded` otherwise. The endpoint always returns 200 — it
    reports liveness of *this process*, and restarting the process
    does not fix a dead Redis. Orchestrators that want to gate
    traffic on dependencies should parse `status` / `dependencies`.
    """

    status: str = Field(
        description="`ok` when all checked dependencies ping; `degraded` "
        "otherwise. The HTTP status stays 200 either way — see ADR 0042."
    )
    active_jobs: int = Field(
        description="In-flight job tasks on THIS worker (queued + "
        "running). Store-independent, so it is honest under the Redis "
        "store too; a cluster-wide count would need its own endpoint."
    )
    max_concurrent_jobs: int
    dependencies: dict[str, str] = Field(
        default_factory=dict,
        description="Per-dependency ping result (`ok` or `error: "
        "<ExceptionName>`), keyed by dependency name. Only backends "
        "the deployment actually configures appear here.",
    )
