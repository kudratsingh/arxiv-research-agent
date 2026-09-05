"""The deterministic compute controller: difficulty features and T0/T1.

`docs/agent-engineering/02-target-architecture.md` §4 asks the compute
controller to "allocate a bounded strategy, not a raw token budget", and
`07-first-policy-experiment.md`'s arm E needs the features that led to a
compute decision recorded *before* the decision, not reconstructed from
the run afterwards. This module is that decision, and nothing else: a
feature extractor over what is knowable before the graph starts, a rule
table, and the two tiers this repository can actually execute.

**Deterministic on purpose.** No model call, no settings read, no clock,
no I/O — the same query always produces the same tier, on any worker, in
any process. That is what lets the same decision be re-derived from the
trajectory during analysis, and it is why `02-target-architecture.md`
§4's learned router is explicitly *later* work: a learned router cannot
be attributed until a deterministic one has been measured.

## The rule table

Rules are evaluated in the order below. The two `requested_depth` rules
are **decisive** — an explicit request from the caller short-circuits the
table, in both directions — and every other rule is an *escalation*: any
one of them selects T1, and a run that matches none stays at T0.

| # | Rule | Fires when | Tier | Why |
|---|---|---|---|---|
| 1 | `depth_quick` | `requested_depth == "quick"` | T0 | a caller who asked for cheap gets cheap, whatever the cues say |
| 2 | `depth_deep` | `requested_depth == "deep"` | T1 | the same authority in the other direction |
| 3 | `comparative_cue` | a comparison word is in the query | T1 | comparative claims are the ones a verifier catches |
| 4 | `freshness_cue` | a recency word is in the query | T1 | "latest" claims go stale between retrieval and synthesis |
| 5 | `multi_entity` | `entity_count >= 2` | T1 | two named systems means cross-entity claims |
| 6 | `long_query` | `query_tokens >= 24` | T1 | a long ask carries more independent claims per report |
| 7 | `plan_breadth` | `sub_question_count >= 4` or `search_query_count >= 6` | T1 | plan-time breadth, for callers that decide after planning |
| 8 | `default_t0` | nothing above fired | T0 | the cheap path is the default, and stays the control arm |

Thresholds are constants below rather than settings: a threshold an
operator can move is a threshold no evaluation can attribute a result to.
Moving one is an ADR and a re-baseline (ADR 0085, ADR 0070).

## The tiers, and what they are allowed to spend

T2 (branching) and T3 are **not** decided here. T2 arrives with CAP-03's
orchestrator-workers; T3 is reserved and the trajectory contract refuses
it outright (`src/contracts/trajectory.py`). `MAX_DECIDABLE_TIER` is the
hard ceiling on this controller's authority, and `decide_tier` cannot
return anything above it by construction.

Each tier declares limits that the *compiled graph* already enforces, so
the limits are a description of a structural guarantee rather than a
second budget nobody checks:

| Tier | Graph | Verifications | Repairs |
|---|---|---|---|
| T0 | the fixed pipeline (`research_fixed_evidence` with the evidence store on) | 0 — there is no verify node | 0 |
| T1 | arm C's verify-and-repair graph (`research_fixed_verify_repair`) | at most 2 | at most 1, capped by `route_after_verification` |

## Features that no request carries yet

`requested_depth`, `task_kind` and the two plan-time counts are optional
and are `None` on every path this repository ships today: `POST /research`
has no depth field, `compile_research_intake` compiles exactly one
research `task_kind`, and the tier has to be chosen before the planner
runs because it selects the graph. They are parameters rather than
absences because the rule table has to be complete before a caller
exists — CAP-03's T2 decision is made *after* planning and reads the
plan-time counts, and ADR 0085 records the seam so that work order adds a
row rather than a signature.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Final, Literal

ComputeTier = Literal["T0", "T1"]
"""Every tier this controller may select. See `MAX_DECIDABLE_TIER`."""

COMPUTE_TIERS: Final[tuple[ComputeTier, ...]] = ("T0", "T1")
"""The same set as a value, for callers that enumerate rather than type."""

MAX_DECIDABLE_TIER: Final[ComputeTier] = "T1"
"""The ceiling on this controller's authority.

Not a preference: T2 needs a branch executor that does not exist until
CAP-03, and T3 is refused by the trajectory contract. A controller that
could name a tier it cannot execute would put an unrunnable decision in
the record.
"""

RequestedDepth = Literal["quick", "standard", "deep"]
"""What a caller may ask for directly, when a surface carries it."""

#: A query at or above this many whitespace tokens escalates. 24 is
#: roughly two sentences: below it a question names one thing, above it
#: it usually names several and the report carries more independent
#: claims than one synthesis pass reliably supports.
LONG_QUERY_TOKENS: Final[int] = 24

#: Two named entities is the smallest query that can carry a
#: cross-entity claim, which is the claim class verification catches.
MULTI_ENTITY_THRESHOLD: Final[int] = 2

#: Plan-time breadth, sized against the planner's own instruction: it
#: is asked for "2-4 focused sub-questions" and "1-2 targeted queries"
#: each, so four sub-questions is the top of its range and six queries
#: is the upper half of the 2-8 that range implies.
PLAN_SUB_QUESTION_THRESHOLD: Final[int] = 4
PLAN_SEARCH_QUERY_THRESHOLD: Final[int] = 6

#: Comparison cues, normalised the way `_normalise` normalises a query
#: (lowercase, every non-alphanumeric run collapsed to one space), so
#: "trade-off", "trade off" and "Trade-Off" are one entry.
COMPARATIVE_CUES: Final[tuple[str, ...]] = (
    "compare",
    "compared",
    "comparing",
    "comparison",
    "differ",
    "difference",
    "differences",
    "pros and cons",
    "trade off",
    "trade offs",
    "tradeoff",
    "tradeoffs",
    "versus",
    "vs",
    "which is better",
)

#: Recency cues. Deliberately phrase-only: a bare year is not a
#: freshness signal ("the 1998 LSTM paper" is the opposite of one), and
#: a rule that treated it as one would escalate historical queries.
FRESHNESS_CUES: Final[tuple[str, ...]] = (
    "current",
    "latest",
    "newest",
    "recent",
    "recently",
    "so far this year",
    "sota",
    "state of the art",
    "this year",
    "up to date",
)

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

#: Punctuation an entity token may be wrapped in and still be one.
_TRIM = "\"'“”‘’()[]{}<>,.;:!?…"


def _normalise(text: str) -> str:
    """Lowercase, collapse non-alphanumerics, and pad with one space.

    Padded so a cue can be matched as `f" {cue} "` and `"vs"` does not
    fire on "versatile" — a substring match on an unpadded string is the
    classic way a cue table starts lying.
    """
    return f" {_NON_ALPHANUMERIC.sub(' ', text.lower()).strip()} "


def _is_entity_token(raw: str) -> bool:
    """Whether one whitespace token reads as a named system or model.

    Three shapes count, and a plain capitalised word deliberately does
    not: "What" and "Compare" open half the queries in the corpus, so a
    sentence-initial capital would make `entity_count` a proxy for
    "the query is a sentence".

    - an all-caps token of two or more characters (`RAG`, `LLM`);
    - an internal capital (`GPT`, `ResNet`, `arXiv` — the capital is not
      at position 0, so it cannot be sentence case);
    - a digit beside a letter (`4-bit`, `llama3`, `GPT-4`).
    """
    token = raw.strip(_TRIM)
    if len(token) < 2 or not any(character.isalpha() for character in token):
        return False
    if token.isupper():
        return True
    if any(character.isupper() for character in token[1:]):
        return True
    return any(character.isdigit() for character in token)


@dataclass(frozen=True)
class ComputeFeatures:
    """What was knowable about a run before its compute was allocated.

    Frozen and JSON-shaped: the snapshot is hashed into the trajectory's
    `feature_snapshot_ref`, so a feature that could be edited after the
    decision would make the digest describe something other than the
    input the decision saw.

    None of these fields carries user text. `query_tokens` and
    `entity_count` are counts and the cues are booleans, which is what
    lets the snapshot ride on a `product_operation_only` run without
    D8's retained-content question being reopened (ADR 0083).

    Attributes:
        query_tokens: Whitespace token count of the query.
        entity_count: Distinct `_is_entity_token` tokens, case-folded.
        comparative_cue: A `COMPARATIVE_CUES` phrase is present.
        freshness_cue: A `FRESHNESS_CUES` phrase is present.
        requested_depth: What the caller asked for, when a surface
            carries it. `None` on every path shipped today.
        task_kind: The sealed `TaskSpec`'s kind, for callers that hold
            one. `None` on the API path, where the tier is chosen before
            the binding compiles a spec.
        sub_question_count: Plan-time breadth, or `None` before planning.
        search_query_count: Plan-time breadth, or `None` before planning.
    """

    query_tokens: int
    entity_count: int
    comparative_cue: bool
    freshness_cue: bool
    requested_depth: RequestedDepth | None = None
    task_kind: str | None = None
    sub_question_count: int | None = None
    search_query_count: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """The snapshot, in the field order the digest is taken over."""
        return {
            "query_tokens": self.query_tokens,
            "entity_count": self.entity_count,
            "comparative_cue": self.comparative_cue,
            "freshness_cue": self.freshness_cue,
            "requested_depth": self.requested_depth,
            "task_kind": self.task_kind,
            "sub_question_count": self.sub_question_count,
            "search_query_count": self.search_query_count,
        }

    def digest(self) -> str:
        """`sha256:<hex>` over the canonical snapshot.

        A digest rather than the snapshot itself is what the trajectory
        can carry: `compute.tier_selected`'s payload is closed to five
        registered fields and `feature_snapshot_ref` is one of them, so
        the honest reference to a snapshot nobody stored is its hash.
        Two runs that saw the same features carry the same ref, which is
        the property an analysis of arm E actually needs.
        """
        encoded = json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def extract_features(
    query: str,
    *,
    requested_depth: RequestedDepth | None = None,
    task_kind: str | None = None,
    sub_question_count: int | None = None,
    search_query_count: int | None = None,
) -> ComputeFeatures:
    """Read the difficulty features off a query and whatever else is known.

    Total: every input shape produces a feature vector, including the
    empty string. A feature extractor that could raise would turn a
    diagnostic into a failed job at the one moment the run has produced
    nothing yet.

    Args:
        query: The research question, exactly as submitted.
        requested_depth: An explicit caller request, when a surface
            carries one.
        task_kind: The sealed `TaskSpec`'s kind, when the binding has
            compiled one.
        sub_question_count: Sub-questions in the plan, after planning.
        search_query_count: Search queries in the plan, after planning.

    Returns:
        The frozen snapshot the decision is taken over.
    """
    tokens = query.split()
    normalised = _normalise(query)
    entities = {
        token.strip(_TRIM).casefold() for token in tokens if _is_entity_token(token)
    }
    return ComputeFeatures(
        query_tokens=len(tokens),
        entity_count=len(entities),
        comparative_cue=any(f" {cue} " in normalised for cue in COMPARATIVE_CUES),
        freshness_cue=any(f" {cue} " in normalised for cue in FRESHNESS_CUES),
        requested_depth=requested_depth,
        task_kind=task_kind,
        sub_question_count=sub_question_count,
        search_query_count=search_query_count,
    )


@dataclass(frozen=True)
class TierLimits:
    """What the graph a tier selects is structurally allowed to spend.

    These are *not* a second budget enforced by a new check. Each number
    is a property of the compiled graph — T0 has no verify node, and
    `src/graph/workflow.py::route_after_verification` is the only place
    the one-repair cap is enforced — written down so a decision record
    says what it authorised and `tests/test_compute_controller.py` can
    assert the graph and the record agree.

    Attributes:
        policy_id: The policy id W05's binding records for the graph
            this tier selects, when the evidence store is on. Derived
            from the compiled graph at runtime, never from this field;
            the field is here so a decision is readable without one.
        max_verifications: Verify-node executions the graph can reach.
        max_repairs: Repair-node executions the graph can reach.
    """

    policy_id: str
    max_verifications: int
    max_repairs: int


TIER_LIMITS: Final[Mapping[ComputeTier, TierLimits]] = {
    "T0": TierLimits(
        policy_id="research_fixed_evidence", max_verifications=0, max_repairs=0
    ),
    "T1": TierLimits(
        policy_id="research_fixed_verify_repair", max_verifications=2, max_repairs=1
    ),
}


@dataclass(frozen=True)
class ComputeDecision:
    """The tier a run was allocated, with the reasons and the input.

    Attributes:
        tier: `T0` or `T1`, never higher (`MAX_DECIDABLE_TIER`).
        reasons: Every rule that fired, in table order. Never empty —
            a T0 run that matched nothing carries `("default_t0",)`, so
            "no reason" and "the default" stay distinguishable in the
            record.
        features: The snapshot the rules were evaluated over.
        limits: What the selected tier's graph may spend.
    """

    tier: ComputeTier
    reasons: tuple[str, ...]
    features: ComputeFeatures
    limits: TierLimits


@dataclass(frozen=True)
class TierRule:
    """One row of the table in this module's docstring.

    `decisive` is the difference between an explicit request and an
    inferred cue: a decisive rule returns its tier immediately, and the
    rest accumulate.
    """

    rule_id: str
    tier: ComputeTier
    decisive: bool
    predicate: Callable[[ComputeFeatures], bool]


def _plan_breadth(features: ComputeFeatures) -> bool:
    """Whether a *known* plan is broad. Unknown counts never fire."""
    sub_questions = features.sub_question_count
    queries = features.search_query_count
    if sub_questions is not None and sub_questions >= PLAN_SUB_QUESTION_THRESHOLD:
        return True
    return queries is not None and queries >= PLAN_SEARCH_QUERY_THRESHOLD


TIER_RULES: Final[tuple[TierRule, ...]] = (
    TierRule(
        rule_id="depth_quick",
        tier="T0",
        decisive=True,
        predicate=lambda f: f.requested_depth == "quick",
    ),
    TierRule(
        rule_id="depth_deep",
        tier="T1",
        decisive=True,
        predicate=lambda f: f.requested_depth == "deep",
    ),
    TierRule(
        rule_id="comparative_cue",
        tier="T1",
        decisive=False,
        predicate=lambda f: f.comparative_cue,
    ),
    TierRule(
        rule_id="freshness_cue",
        tier="T1",
        decisive=False,
        predicate=lambda f: f.freshness_cue,
    ),
    TierRule(
        rule_id="multi_entity",
        tier="T1",
        decisive=False,
        predicate=lambda f: f.entity_count >= MULTI_ENTITY_THRESHOLD,
    ),
    TierRule(
        rule_id="long_query",
        tier="T1",
        decisive=False,
        predicate=lambda f: f.query_tokens >= LONG_QUERY_TOKENS,
    ),
    TierRule(
        rule_id="plan_breadth",
        tier="T1",
        decisive=False,
        predicate=_plan_breadth,
    ),
)

#: The reason a T0 run carries when no rule fired at all.
DEFAULT_REASON: Final[str] = "default_t0"

#: Every reason code this module can emit, for a consumer that groups by
#: them without having to enumerate the table itself.
REASON_CODES: Final[tuple[str, ...]] = tuple(
    [rule.rule_id for rule in TIER_RULES] + [DEFAULT_REASON]
)


def decide_tier(features: ComputeFeatures) -> ComputeDecision:
    """Allocate a compute tier from the features, by the table above.

    Pure and total. The first decisive rule that matches wins outright;
    otherwise every matching escalation is collected and any one of them
    selects T1; a run that matched nothing is T0 for `DEFAULT_REASON`.

    Args:
        features: The snapshot from `extract_features`.

    Returns:
        The decision, carrying its reasons, its input and its limits.
    """
    escalations: list[str] = []
    for rule in TIER_RULES:
        if not rule.predicate(features):
            continue
        if rule.decisive:
            return ComputeDecision(
                tier=rule.tier,
                reasons=(rule.rule_id,),
                features=features,
                limits=TIER_LIMITS[rule.tier],
            )
        escalations.append(rule.rule_id)

    tier: ComputeTier = "T1" if escalations else "T0"
    return ComputeDecision(
        tier=tier,
        reasons=tuple(escalations) if escalations else (DEFAULT_REASON,),
        features=features,
        limits=TIER_LIMITS[tier],
    )


# ---------------------------------------------------------------------------
# The active tier, bound for the length of one run
# ---------------------------------------------------------------------------
#
# Same shape and the same reason as `src.cancellation`'s token and
# `src.observability.costs`'s cost cap: the tier has to reach
# `Settings.effort_for` inside a graph node running on the executor pool,
# and threading it through `_invoke_streaming` -> LangGraph -> agent ->
# `call_llm_json` would put a compute concern in five signatures that
# have nothing to do with compute. A ContextVar is copied into the node
# thread by `src/graph/workflow.py`'s explicit `copy_context()`, which
# already exists for exactly these three values.
#
# Nothing binds this unless the controller is on, so with the shipped
# default the getter returns `None` and `effort_for` is the function it
# was before this work order.

_active_tier: ContextVar[ComputeTier | None] = ContextVar(
    "compute_tier", default=None
)


def bind_compute_tier(tier: ComputeTier) -> Token[ComputeTier | None]:
    """Bind the tier for every call in this context. Returns the token."""
    return _active_tier.set(tier)


def reset_compute_tier(token: Token[ComputeTier | None]) -> None:
    """Unbind the tier when the run leaves its task context."""
    _active_tier.reset(token)


def active_compute_tier() -> ComputeTier | None:
    """The tier the current run was allocated, or `None` when unbound."""
    return _active_tier.get()
