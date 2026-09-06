"""Listwise candidate selection for the branch tier (CAP-09, ADR 0091).

`docs/agent-engineering/02-target-architecture.md` §4 asks tier T2 for
three things — "diverse search branches or candidate outlines, listwise
selection, verification". CAP-03 built the branches (ADR 0086) and left
the middle one open in as many words: "the second half — comparing
candidate outlines and *selecting* one — is CAP-09". This module is that
half.

## What a candidate is here

A succeeded branch's **evidence table**. That is not a convenience: it
is the object `ResearchRuntimeBridge.branch_candidate` already records
as RFC 10 §6.4's sibling `candidate.created`, content-addressed on the
claims themselves, so the thing this module ranks and the thing the
trajectory already names are one object rather than two that have to be
joined afterwards. A branch that produced no evidence is not a
candidate; there is nothing to compare.

## Listwise, and why that word is load-bearing

One call over the whole list (RFC 10 §6.4: "listwise model selection
links its request, observation, usage, and score artifact"). Not
pairwise, and the difference is not stylistic:

- pairwise over N candidates is O(N²) calls where this is one, and the
  branch tier's whole cost argument is that orchestration adds no model
  calls of its own beyond the branches themselves; and
- pairwise comparisons are not guaranteed transitive, so the ranking a
  run recorded could depend on the comparison order, which is exactly
  the non-determinism ADR 0086 refused a thread pool over.

## Two selectors, one record

**Deterministic** (`listwise_deterministic`) — the ranking is
`(evidence_count desc, analysis_count desc, plan order)`. It runs under
`USE_MOCK_DATA`, and it runs whenever the model path fails. Under mock
every branch reads the same fixture corpus, so the counts tie and the
ranking *is* fixture order — zero model calls, zero spend, byte-stable
across runs, which is what lets the campaign's full matrix exercise arm
E for nothing (ADR 0088's discipline).

**Model** (`listwise_model`) — one `call_llm_json` with a schema, so the
answer arrives as JSON the API constrained rather than as free text this
module has to parse hopefully. When `enable_structured_outputs` is on
and the routed model's row allows it, `src/llm.py` sends the schema as
`output_config.format` through `anthropic.transform_schema`; when it is
not, the same schema still drives validation on the way back. A response
that does not name exactly the eligible candidates is *not* repaired
into one — it degrades to the deterministic ranking and says so, because
a selector that quietly re-ranked a malformed answer would put a number
in the record that nothing produced.

Both paths write the same `SelectionRecord`, so a reader of the state or
the trajectory never has to know which one ran except by reading
`selector_kind`.

## What selection actually does

The selected candidates are the ones `merge_branches` unions. Rejection
is a decision with an effect, not a note — but it is bounded on both
sides: the top-ranked candidate is always selected (an empty evidence
table would let a fluent, sourceless briefing ship, ADR 0041), and a
rejected branch keeps its record, its status and its `candidate.created`
event (RFC 10 §6.4: "rejection or non-selection never deletes a
candidate").
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict, Field

from src.config import settings
from src.graph.state import (
    CandidateScore,
    ResearchState,
    SelectionRecord,
    WorkerBranch,
)
from src.observability import get_logger
from src.policies.orchestration import STATUS_SUCCEEDED

log = get_logger(__name__)

#: The two selectors, named on every record so a reader never has to
#: infer which one ran. `listwise_model` is claimed only when a model
#: actually answered and its answer covered exactly the eligible set.
SELECTOR_DETERMINISTIC: Final[str] = "listwise_deterministic"
SELECTOR_MODEL: Final[str] = "listwise_model"

#: Reason codes the deterministic ranking writes. Typed rather than
#: prose for the reason `src/errors.py`'s registry is typed: a reason an
#: evaluation groups by has to be countable.
REASON_SELECTED: Final[str] = "ranked_within_selection_ceiling"
REASON_REJECTED: Final[str] = "ranked_below_selection_ceiling"

#: Claims shown to the model per candidate. A bound rather than a
#: preference: the branch cap is `orchestration_max_papers_per_branch`
#: papers and a reader can emit several claims per paper, so an
#: unbounded list would make the selection prompt grow with the corpus
#: and put the one call this module makes at the mercy of a wide branch.
MAX_CLAIMS_SHOWN: Final[int] = 6

#: Characters of one claim shown to the model.
MAX_CLAIM_CHARS: Final[int] = 240

SYSTEM_PROMPT: Final[str] = (
    "You rank candidate evidence tables produced by parallel research "
    "branches. Each candidate is one branch's evidence for one "
    "sub-question of the same research question.\n\n"
    "Rank every candidate exactly once, best first. Judge each on how "
    "much of the research question its evidence actually answers, how "
    "well its claims are grounded in the papers cited, and how much it "
    "adds that the other candidates do not. Do not reward length.\n\n"
    "Return JSON only:\n"
    '{"ranking": [{"branch_id": "...", "rank": 0, "score": 0.0, '
    '"reason": "one short sentence"}]}\n\n'
    "rank is 0-based and contiguous. score is 0.0-1.0, higher is "
    "better. Include every branch_id you were given and no others."
)


def _hide_docstring_from_the_model(schema: dict[str, Any]) -> None:
    """Drop the class docstring from the generated JSON schema.

    `src/agents/schemas.py`'s rule, applied here for the same reason: a
    docstring that talks about ADR numbers is a note for a reader of
    this file, and shipping it as `output_config.format` would add
    prompt text under a work order whose discipline is that prompt
    wording does not move (ADR 0070).
    """
    schema.pop("description", None)


class RankedCandidate(BaseModel):
    """One candidate's place in the model's ranking."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra=_hide_docstring_from_the_model
    )

    branch_id: str = Field(description="The candidate's branch id.")
    rank: int = Field(description="0-based position, 0 is best.")
    score: float = Field(description="0.0-1.0, higher is better.")
    reason: str = Field(description="One short sentence.")


class ListwiseRanking(BaseModel):
    """The whole ranking, in one answer."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra=_hide_docstring_from_the_model
    )

    ranking: list[RankedCandidate] = Field(
        description="Every candidate, exactly once."
    )


def eligible_candidates(branches: Sequence[WorkerBranch]) -> list[WorkerBranch]:
    """The branches this pass may choose between, in plan order.

    Succeeded, and still carrying evidence. The second condition does
    the work that would otherwise need a second state key: the merge
    releases a branch's bulk output once it has been unioned (ADR 0086),
    so a branch whose evidence list is empty here is either a branch
    that found nothing or a branch an earlier pass already merged —
    and in both cases there is nothing left for this pass to select.
    """
    return [
        branch
        for branch in branches
        if branch["status"] == STATUS_SUCCEEDED and branch["evidence"]
    ]


def deterministic_ranking(
    candidates: Sequence[WorkerBranch],
) -> list[tuple[str, float, str]]:
    """Rank by what the branch records already measure. Pure and total.

    `(evidence_count desc, analysis_count desc, plan order)`. Every term
    is a number the run already counted, so the ranking needs no model,
    no clock and no I/O, and two runs over the same branches produce the
    same order — which is what makes this the mock path *and* the
    fallback rather than two different rules.

    The score is normalised against the best candidate's evidence count
    so it reads on the same 0.0-1.0 scale the model path uses. A record
    whose scores meant different things depending on `selector_kind`
    would be a column an evaluation could not aggregate.
    """
    ordered = sorted(
        candidates,
        key=lambda branch: (
            -branch["evidence_count"],
            -branch["analysis_count"],
            branch["index"],
        ),
    )
    best = max((branch["evidence_count"] for branch in ordered), default=0)
    return [
        (
            branch["branch_id"],
            round(branch["evidence_count"] / best, 6) if best else 0.0,
            f"{branch['evidence_count']} claim(s) from "
            f"{branch['analysis_count']} paper(s)",
        )
        for branch in ordered
    ]


def _candidate_block(branch: WorkerBranch) -> str:
    """One candidate as the model sees it. Bounded on both axes."""
    claims = []
    for claim in branch["evidence"][:MAX_CLAIMS_SHOWN]:
        text = str(claim.get("claim", "")).strip()[:MAX_CLAIM_CHARS]
        if text:
            claims.append(f"  - {text}")
    body = "\n".join(claims) or "  - (no claim text)"
    return (
        f"branch_id: {branch['branch_id']}\n"
        f"sub_question: {branch['sub_question']}\n"
        f"papers: {branch['analysis_count']}, claims: {branch['evidence_count']}\n"
        f"claims:\n{body}"
    )


def model_ranking(
    query: str, candidates: Sequence[WorkerBranch]
) -> list[tuple[str, float, str]] | None:
    """One listwise call, or `None` when the answer cannot be trusted.

    `None` rather than a partial ranking, and rather than an exception:
    a selector is a policy stage on the critical path of a run that has
    already paid for its branches, so a provider failure or a malformed
    answer has to degrade to the deterministic ranking rather than fail
    the run. What it must not do is *repair* the answer — a ranking that
    named four of five candidates is not a ranking with one omission, it
    is evidence that the model did not do the task, and filling the gap
    in would put a number in the record nothing produced.

    Args:
        query: The run's research question, for context.
        candidates: Every eligible candidate, in plan order.

    Returns:
        `(branch_id, score, reason)` best first, or `None`.
    """
    from src.llm import call_llm_json

    blocks = "\n\n".join(_candidate_block(branch) for branch in candidates)
    prompt = (
        f"Research question: {query}\n\n"
        f"Candidates ({len(candidates)}):\n\n{blocks}"
    )
    try:
        parsed = call_llm_json(prompt, SYSTEM_PROMPT, schema=ListwiseRanking)
        ranking = ListwiseRanking.model_validate(parsed)
    except Exception as exc:  # noqa: BLE001 — see the docstring
        log.warning(
            "candidate_selection_degraded",
            extra={"reason": type(exc).__name__, "count": len(candidates)},
        )
        return None

    wanted = {branch["branch_id"] for branch in candidates}
    named = [row.branch_id for row in ranking.ranking]
    if sorted(named) != sorted(wanted):
        log.warning(
            "candidate_selection_degraded",
            extra={"reason": "ranking_did_not_cover_candidates", "count": len(wanted)},
        )
        return None
    rows = sorted(ranking.ranking, key=lambda row: row.rank)
    return [
        (row.branch_id, round(float(row.score), 6), row.reason.strip()[:200])
        for row in rows
    ]


def select_candidates(
    state: ResearchState, branches: Sequence[WorkerBranch]
) -> SelectionRecord | None:
    """Rank this pass's candidates and say which reach the merge.

    `None` when there is nothing to select between — no eligible
    candidate at all. That is not the same as "select nothing": a record
    naming an empty eligible set would claim a decision the selector
    never made, and `merge_node` reads the record's selected set
    literally, so an empty one would discard the run's evidence.

    Args:
        state: The graph state the workers node left.
        branches: Every branch record, settled.

    Returns:
        The selection record, or `None` when no candidate was eligible.
    """
    candidates = eligible_candidates(branches)
    if not candidates:
        return None

    ranked: list[tuple[str, float, str]] | None = None
    calls = 0
    kind = SELECTOR_DETERMINISTIC
    if not settings.use_mock_data and len(candidates) > 1:
        # One candidate is not a list, and a listwise call over it would
        # spend a model call to learn that the only candidate ranks
        # first. Mock mode never calls at all (ADR 0080).
        ranked = model_ranking(str(state.get("query", "") or ""), candidates)
        if ranked is not None:
            kind, calls = SELECTOR_MODEL, 1
    if ranked is None:
        ranked = deterministic_ranking(candidates)

    ceiling = max(1, int(settings.selection_max_candidates))
    scores: list[CandidateScore] = []
    selected: list[str] = []
    rejected: list[str] = []
    for position, (branch_id, score, reason) in enumerate(ranked):
        keeps = position < ceiling
        (selected if keeps else rejected).append(branch_id)
        scores.append(
            CandidateScore(
                branch_id=branch_id,
                rank=position,
                score=score,
                selected=keeps,
                reason=reason or (REASON_SELECTED if keeps else REASON_REJECTED),
            )
        )
    return SelectionRecord(
        selector_kind=kind,
        eligible_branch_ids=[branch["branch_id"] for branch in candidates],
        selected_branch_ids=selected,
        rejected_branch_ids=rejected,
        scores=scores,
        max_candidates=ceiling,
        llm_calls=calls,
    )


def select_node(state: ResearchState) -> dict[str, Any]:
    """Graph node: rank the branch candidates and record the choice.

    Compiled between `workers` and `merge` only when
    `settings.candidate_selection` is `listwise` (ADR 0091), so a
    deployment that has not asked for a selector runs CAP-03's graph
    edge for edge and its trajectory carries no selection event.

    Returns:
        Partial state update carrying the selection record, or only a
        message when no candidate was eligible to be selected.
    """
    branches = list(state.get("worker_branches", []) or [])
    record = select_candidates(state, branches)
    if record is None:
        return {
            "messages": [
                AIMessage(
                    content="No branch candidate was eligible for selection.",
                    name="select",
                )
            ]
        }
    summary = (
        f"Selected {len(record['selected_branch_ids'])} of "
        f"{len(record['eligible_branch_ids'])} branch candidate(s) by "
        f"{record['selector_kind']}: "
        + ", ".join(
            f"{row['branch_id']}#{row['rank']}"
            f"{'' if row['selected'] else ' (rejected)'}"
            for row in record["scores"]
        )
        + "."
    )
    return {
        "candidate_selection": record,
        "messages": [AIMessage(content=summary, name="select")],
    }
