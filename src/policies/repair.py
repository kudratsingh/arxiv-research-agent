"""The repair decision for the fixed verify-and-repair policy (ADR 0076).

One failed verification, one bounded repair, chosen by a table rather
than by a model. `docs/agent-engineering/07-first-policy-experiment.md`
§3 approves five repairs for arm C; this module implements the two the
current agents can execute without new prompt text, and records the
other two by name so an evaluation can count how often the missing
repair was the indicated one instead of seeing an undifferentiated
"nothing happened".

| Verifier output | Action | What the graph does next |
|---|---|---|
| `missing_evidence` non-empty | `retrieve_missing_evidence` | search with the named gaps as queries -> reader -> synthesizer |
| `unsupported_claims` non-empty, no missing evidence | `qualify_or_remove_claims` | synthesizer, with the claims listed in a bounded repair block |
| verdict `pass` or `abstain` | `none` | straight to the critic |

Three properties are load-bearing and each is asserted in
`tests/test_research_policy.py`:

- **Deterministic.** No model call, no settings read, no I/O. The same
  state always produces the same decision, which is what lets the graph
  route on `decide_repair` and the node re-derive it without the two
  disagreeing.
- **Bounded.** At most `MAX_REPAIR_QUERIES` new searches, and the node
  increments `repair_count` whether or not the decision found something
  to do, so "one repair per run" holds even for a repair that turns out
  to be a no-op.
- **Deduplicated.** Gap queries are compared against
  `tried_search_queries` using the query refiner's own normalisation, so
  the repair cannot spend the run's one recovery re-running a search
  that already happened — ADR 0018's thrash, arrived at from the other
  direction. The refiner itself stays off; only its rule is reused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from langchain_core.messages import AIMessage

# `_normalize` is the query refiner's dedup rule (lowercase + strip),
# imported rather than re-derived for the reason `src/agents/synthesizer.py`
# imports `src.llm._retry_envelope`: two copies of a normalisation agree
# right up until someone changes one of them, and the seam is private to
# discourage callers rather than to hide a fact. Importing the function
# does not enable the refiner — `enable_query_refiner` still gates the
# node, and this module never calls `query_refiner_agent`.
from src.agents.query_refiner import _normalize
from src.graph.state import ResearchState

RepairAction = Literal[
    "retrieve_missing_evidence",
    "qualify_or_remove_claims",
    "none",
]
"""Every repair this policy can select. Published by ADR 0076 for W05."""

REPAIR_ACTIONS: Final[tuple[RepairAction, ...]] = (
    "retrieve_missing_evidence",
    "qualify_or_remove_claims",
    "none",
)
"""The same set as a value, for callers that enumerate rather than type."""

#: Cap on searches one repair may drive. The planner's own plan is
#: bounded and `search_agent` caps a run at
#: `MAX_SEARCH_QUERIES_PER_RUN=12`; this is tighter because a repair is
#: meant to close *named* gaps, and a verifier that lists twenty of them
#: has produced a re-plan, not a repair.
MAX_REPAIR_QUERIES: Final = 5


@dataclass(frozen=True, slots=True)
class RepairDecision:
    """What the repair node will do, and the reason code that says why.

    Frozen because the router and the node each derive it from the same
    state and must agree; a decision something downstream could edit
    would make "the graph routed to repair" and "the repair that ran"
    two different facts.

    Attributes:
        action: The selected repair, or `"none"`.
        reason: A stable snake_case code. Reason codes are part of the
            published surface (ADR 0076) — they reach the state as
            `repair_action`'s companion and an evaluation groups by
            them, so they are renamed only with the ADR.
        queries: Search queries for `retrieve_missing_evidence`, already
            deduplicated and capped. Empty for every other action.
    """

    action: RepairAction
    reason: str
    queries: tuple[str, ...] = ()


def _clean_list(value: Any) -> list[str]:
    """Non-empty stripped strings out of a state list field, safely."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _fresh_gap_queries(gaps: list[str], state: ResearchState) -> tuple[str, ...]:
    """Gap phrases that have not already been searched, capped.

    Deduplicates within the batch as well as against history, because a
    verifier that names the same gap twice (once per sub-question it
    blocks) is ordinary output, not malformed output.
    """
    forbidden = {
        _normalize(query)
        for query in _clean_list(state.get("tried_search_queries", []))
        + _clean_list(state.get("search_queries", []))
    }
    seen: set[str] = set()
    fresh: list[str] = []
    for gap in gaps:
        key = _normalize(gap)
        if key in forbidden or key in seen:
            continue
        seen.add(key)
        fresh.append(gap)
        if len(fresh) == MAX_REPAIR_QUERIES:
            break
    return tuple(fresh)


def decide_repair(state: ResearchState) -> RepairDecision:
    """Pick the one repair this run may attempt, from the table above.

    Reads `verification_verdict`, `missing_evidence`,
    `unsupported_claims`, `verifier_recommendation`,
    `tried_search_queries` and `search_queries`, each with a default, so
    the function is total over a state that has never been verified.

    Precedence between the two implemented repairs is deliberate:
    retrieval can make an unsupported claim supportable, while rewriting
    a claim cannot make a missing source appear. With one repair to
    spend, the run spends it on the action that can still change the
    evidence.

    Args:
        state: The graph state as the verify node left it.

    Returns:
        The decision. `action="none"` carries a reason code that
        distinguishes "there was nothing to repair" (`verdict_pass`,
        `verdict_abstain`) from "the indicated repair is not built yet"
        (`reread_sections_not_implemented`,
        `rewrite_section_not_implemented`) — a distinction an evaluation
        needs and a boolean would lose.
    """
    verdict = str(state.get("verification_verdict", "") or "")
    if verdict != "fail":
        return RepairDecision("none", f"verdict_{verdict or 'unset'}")

    missing = _clean_list(state.get("missing_evidence", []))
    if missing:
        queries = _fresh_gap_queries(missing, state)
        if queries:
            return RepairDecision(
                "retrieve_missing_evidence", "missing_evidence", queries
            )
        # Every named gap is a search this run already ran. Retrieving
        # again would return the same papers, so the repair is spent
        # here rather than on a round trip that cannot change anything.
        return RepairDecision("none", "missing_evidence_all_tried")

    if _clean_list(state.get("unsupported_claims", [])):
        return RepairDecision("qualify_or_remove_claims", "unsupported_claims")

    # Neither list is populated, so the verifier failed the report on its
    # overall diagnosis alone. Two of the five repairs 07 §3 approves
    # live here and neither is implemented yet; naming them is what makes
    # the gap countable.
    recommendation = str(state.get("verifier_recommendation", "") or "")
    if recommendation == "read_more":
        return RepairDecision("none", "reread_sections_not_implemented")
    if recommendation == "revise_report":
        return RepairDecision("none", "rewrite_section_not_implemented")
    return RepairDecision("none", "no_actionable_repair")


def repair_node(state: ResearchState) -> dict[str, Any]:
    """Graph node: record the decision and set up the node that executes it.

    The node itself never calls a model. It writes `repair_action` and
    `repair_count`, and for `retrieve_missing_evidence` it also rewrites
    `search_queries` to the gap phrases and moves the queries that were
    in flight into `tried_search_queries` — the same bookkeeping the
    query refiner does, so a later dedup sees this round.

    `repair_count` increments even when the decision is `none`. The count
    is the run's "a repair was attempted" record, not a success counter,
    and incrementing unconditionally is what makes the one-repair cap
    hold under a state the router did not anticipate.

    Args:
        state: Graph state after a failed verification.

    Returns:
        Partial state update. `route_after_repair` reads `repair_action`
        off it to pick the node that carries the repair out.
    """
    decision = decide_repair(state)
    attempted = int(state.get("repair_count", 0) or 0) + 1

    update: dict[str, Any] = {
        "repair_action": decision.action,
        "repair_count": attempted,
    }
    if decision.action == "retrieve_missing_evidence":
        in_flight = _clean_list(state.get("search_queries", []))
        tried = _clean_list(state.get("tried_search_queries", []))
        update["search_queries"] = list(decision.queries)
        update["tried_search_queries"] = tried + in_flight
        summary = (
            f"{decision.action} ({decision.reason}): "
            f"{len(decision.queries)} gap queries"
        )
    else:
        summary = f"{decision.action} ({decision.reason})"

    update["messages"] = [
        AIMessage(content=f"repair -> {summary}", name="repair")
    ]
    return update
