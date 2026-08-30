"""Pydantic request/response schemas for the HTTP API.

Small, deliberate — the API is a thin surface over the workflow, so
schemas do input validation and response serialization but no
business logic.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from src.learning.profile_store import (
    MAX_GOAL_ID_LEN,
    MAX_GOAL_STATEMENT_LEN,
    MAX_GOALS,
    MAX_PROFILE_NOTE_LEN,
    MAX_SKILL_ENTRIES,
    MAX_SKILL_NAME_LEN,
    MAX_TIME_BUDGET_MIN_PER_DAY,
    AcademicLevel,
    GoalStatus,
    SkillLevel,
    SkillSource,
)

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
        "running) plus `abandoned_node_threads`. Store-independent, so "
        "it is honest under the Redis store too; a cluster-wide count "
        "would need its own endpoint."
    )
    abandoned_node_threads: int = Field(
        default=0,
        description="Graph-node threads still running after their job "
        "was already failed and its concurrency permit released — the "
        "drain budget expired before the thread returned (ADR 0047). "
        "Sustained non-zero means nodes are ignoring the cancel token, "
        "or `api_job_drain_timeout_sec` is too tight.",
    )
    max_concurrent_jobs: int
    dependencies: dict[str, str] = Field(
        default_factory=dict,
        description="Per-dependency ping result (`ok` or `error: "
        "<ExceptionName>`), keyed by dependency name. Only backends "
        "the deployment actually configures appear here.",
    )


# ---------------------------------------------------------------------------
# Learner profile schemas (Phase W, WO-W02, ADR 0058).
#
# The wire contract carries the same honesty rules the store does. Two
# shapes, deliberately asymmetric:
#
# - The **request** shape has no `source`, `confidence`, or
#   `evidence_ref` field anywhere. A client cannot state provenance,
#   so a client cannot forge it: everything `PUT /learn/profile` writes
#   is `declared` by construction, and inference / assessment reach the
#   store through their own API with an evidence id attached.
# - The **response** shape makes `source` a required enum on every
#   claim, so no consumer can render a skill without knowing where it
#   came from. There is no nullable provenance to fall back on.
# ---------------------------------------------------------------------------


class SkillDeclaration(BaseModel):
    """One skill the learner says they have.

    No provenance field by design — see the section comment above.
    """

    skill: str = Field(
        min_length=1,
        max_length=MAX_SKILL_NAME_LEN,
        description="Controlled-vocabulary skill name, e.g. `backprop`. "
        "Normalised to lowercase; letters, digits and + . / - only.",
    )
    level: SkillLevel = Field(
        description="What the learner claims: none / aware / working / solid."
    )


class GoalDeclaration(BaseModel):
    """One goal the learner set for themselves."""

    goal_id: str | None = Field(
        default=None,
        max_length=MAX_GOAL_ID_LEN,
        description="Existing goal to update. Omit to create a new one.",
    )
    statement: str = Field(
        min_length=1,
        max_length=MAX_GOAL_STATEMENT_LEN,
        description="Learner-authored, e.g. `read modern RLHF papers "
        "critically`. Treated as untrusted text everywhere it reaches a "
        "prompt (ADR 0058).",
    )
    target_date: str = Field(
        default="",
        max_length=10,
        description="ISO date (`YYYY-MM-DD`), or empty for open-ended.",
    )
    status: GoalStatus = Field(default="active")
    priority: int = Field(default=3, ge=1, le=5)


class ProfileUpdateRequest(BaseModel):
    """Body for `PUT /learn/profile` — a full replacement of what the
    learner has declared.

    Claims the system inferred or assessed are *not* addressable here:
    they survive the write untouched, because the learner edits what
    they said about themselves and the system's own observations stand
    or fall on their evidence.
    """

    academic_level: AcademicLevel = Field(default="")
    time_budget_min_per_day: int = Field(
        default=0,
        ge=0,
        le=MAX_TIME_BUDGET_MIN_PER_DAY,
        description="Minutes per day the learner says they have.",
    )
    goals: list[GoalDeclaration] = Field(
        default_factory=list, max_length=MAX_GOALS
    )
    skills: list[SkillDeclaration] = Field(
        default_factory=list, max_length=MAX_SKILL_ENTRIES
    )
    profile_note: str = Field(
        default="",
        max_length=MAX_PROFILE_NOTE_LEN,
        description="Free text the learner wrote about themselves. "
        "Untrusted input — isolation-wrapped before it reaches any "
        "prompt (ADR 0058).",
    )


class SkillClaim(BaseModel):
    """One skill claim as the API returns it — provenance mandatory."""

    skill: str
    level: SkillLevel
    source: SkillSource = Field(
        description="Where the claim came from. `declared` = the "
        "learner said so. `inferred` = a guess from behaviour, capped "
        "at confidence 0.6 and never to be shown as fact. `assessed` = "
        "backed by the assessment event named in `evidence_ref`."
    )
    evidence_ref: str = Field(
        description="Session / assessment / artifact id behind the "
        "claim. Empty only for `declared`, which cites itself."
    )
    confidence: float = Field(
        description="1.0 exactly for `declared` and reserved to it; "
        "at most 0.6 for `inferred`; strictly between for `assessed`."
    )
    updated_at: str = Field(description="ISO-8601 UTC timestamp.")


class GoalClaim(BaseModel):
    """One goal as the API returns it."""

    goal_id: str
    statement: str
    target_date: str
    status: GoalStatus
    priority: int


class LearnerProfileResponse(BaseModel):
    """`GET`/`PUT /learn/profile` — the whole per-principal record.

    Deliberately smaller than the design sketch: no `style_signals`
    and no `preferred_days`. Every field here is a field the deletion
    promise has to cover.
    """

    academic_level: AcademicLevel
    time_budget_min_per_day: int
    goals: list[GoalClaim] = Field(default_factory=list)
    skills: list[SkillClaim] = Field(default_factory=list)
    profile_note: str
    created_at: float
    updated_at: float
