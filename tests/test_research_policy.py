"""Arm C is a structural policy, and this file is where that is proved.

`docs/agent-engineering/07-first-policy-experiment.md` §3 records the
defect this work order closes: arm C — the fixed evidence path with an
explicit verification stage and one bounded repair — "is not present",
and `ENABLE_VERIFIER=true` under the fixed graph does not create it,
because that flag only widens the *supervisor's* action enum. An
experiment that ran arm C by setting it would report results for the
fixed pipeline under arm C's name.

Three claims are asserted here, in the order they have to hold:

1. **The selector refuses to lie.** `research_policy=fixed_verify_repair`
   with any other companion-flag combination fails at settings load, so
   a manifest cannot record arm C for a run that was not arm C.
2. **The compiled graph is a different graph.** The new policy compiles
   nodes and edges the legacy dispatch has no way to produce — and the
   impostor case (`ENABLE_VERIFIER=true`, `research_policy=legacy`,
   supervisor off) compiles to the plain fixed pipeline, with no
   verification node anywhere in it. That is the acceptance criterion
   `docs/agent-engineering/12-p0-work-orders.md` §11 sets for W05.
3. **The repair decision is a table, not a model call.**
   `src/policies/repair.py` is a pure function over state; every row of
   ADR 0076's table gets a test, including the two approved repairs this
   work order deliberately does not implement.

Nothing here runs a model: the decision function never had one, and the
graph tests compile a graph without executing it. The trajectories that
need canned agent output live in `tests/e2e/test_verify_repair.py`.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest
from pydantic import ValidationError

import src.graph.workflow as workflow_module
from src.config import Settings, settings
from src.policies.repair import (
    REPAIR_ACTIONS,
    RepairDecision,
    decide_repair,
)

pytestmark = pytest.mark.unit


#: The one companion-flag combination arm C accepts, as ADR 0076 fixes
#: it: fixed graph, evidence path on, the supervisor's verify action off.
ARM_C_FLAGS: dict[str, bool] = {
    "enable_supervisor": False,
    "enable_evidence_store": True,
    "enable_verifier": False,
}

#: Every other combination of the same three flags. Enumerated rather
#: than sampled — there are seven, and "every invalid combination is
#: refused" is not a claim a sample can support.
INVALID_FLAG_COMBINATIONS: list[dict[str, bool]] = [
    combination
    for combination in (
        dict(
            zip(
                ("enable_supervisor", "enable_evidence_store", "enable_verifier"),
                values,
                strict=True,
            )
        )
        for values in itertools.product((False, True), repeat=3)
    )
    if combination != ARM_C_FLAGS
]


def _state(**overrides: Any) -> dict[str, Any]:
    """The slice of `ResearchState` the repair decision reads.

    A plain dict rather than a full state literal: `decide_repair` takes
    a `ResearchState` and reads five keys off it with defaults, and a
    test that spelled out all thirty would be asserting the constructor
    instead of the decision.
    """
    base: dict[str, Any] = {
        "verification_verdict": "fail",
        "missing_evidence": [],
        "unsupported_claims": [],
        "verifier_recommendation": "",
        "tried_search_queries": [],
        "search_queries": [],
    }
    base.update(overrides)
    return base


def _compile_listing(**overrides: Any) -> tuple[set[str], set[str]]:
    """Node names and `source -> target` edges the settings compile to."""
    patched = settings.model_copy(
        update={"enable_checkpointing": False, **overrides}
    )
    original = workflow_module.settings
    workflow_module.settings = patched  # type: ignore[misc]
    try:
        app = workflow_module.build_workflow(enable_hitl=False)
    finally:
        workflow_module.settings = original  # type: ignore[misc]
    try:
        graph = app.get_graph()
    finally:
        app._checkpointer_exit_stack.close()
    return (
        set(graph.nodes),
        {f"{edge.source} -> {edge.target}" for edge in graph.edges},
    )


# ---------------------------------------------------------------------------
# 1. The selector refuses to lie
# ---------------------------------------------------------------------------


class TestTheSelectorRefusesAnImpossibleArm:
    def test_the_default_is_legacy_and_changes_nothing(self) -> None:
        assert Settings().research_policy == "legacy"

    def test_arm_c_loads_with_the_combination_it_declares(self) -> None:
        loaded = Settings(research_policy="fixed_verify_repair", **ARM_C_FLAGS)
        assert loaded.research_policy == "fixed_verify_repair"

    @pytest.mark.parametrize("flags", INVALID_FLAG_COMBINATIONS)
    def test_every_other_combination_is_refused_at_load(
        self, flags: dict[str, bool]
    ) -> None:
        """Seven combinations, seven refusals, at load rather than at use.

        The failure this prevents is not a crash. It is a campaign that
        completes, records `research_policy=fixed_verify_repair` on every
        manifest row, and compared something else to arm B.
        """
        with pytest.raises(ValidationError) as exc_info:
            Settings(research_policy="fixed_verify_repair", **flags)
        assert "research_policy=fixed_verify_repair" in str(exc_info.value)

    def test_the_message_names_every_offending_flag_not_only_the_first(
        self,
    ) -> None:
        """One boot attempt should be enough to fix the whole env file."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                research_policy="fixed_verify_repair",
                enable_supervisor=True,
                enable_evidence_store=False,
                enable_verifier=True,
            )
        message = str(exc_info.value)
        assert "enable_supervisor" in message
        assert "enable_evidence_store" in message
        assert "enable_verifier" in message

    @pytest.mark.parametrize("flags", [ARM_C_FLAGS, *INVALID_FLAG_COMBINATIONS])
    def test_legacy_accepts_every_combination_it_accepted_before(
        self, flags: dict[str, bool]
    ) -> None:
        """The refusal is scoped to the new value, not to the flags.

        Arms A, B and D keep being expressed exactly as they are today;
        a validator that started refusing one of their combinations would
        be a behaviour change wearing a default-off flag's clothes.
        """
        assert Settings(research_policy="legacy", **flags).research_policy == (
            "legacy"
        )

    def test_an_undeclared_policy_dies_at_load(self) -> None:
        with pytest.raises(ValidationError):
            Settings(research_policy="fixed_verify_repare")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. The compiled graph is a different graph
# ---------------------------------------------------------------------------


class TestTheCompiledShapeIsStructural:
    def test_arm_c_compiles_the_nodes_and_edges_the_adr_publishes(self) -> None:
        nodes, edges = _compile_listing(
            research_policy="fixed_verify_repair", **ARM_C_FLAGS
        )

        assert nodes == {
            "__start__",
            "__end__",
            "planner",
            "search",
            "reader",
            "synthesizer",
            "verify",
            "repair",
            "critic",
        }
        assert edges == {
            "__start__ -> planner",
            "planner -> search",
            "search -> reader",
            "reader -> synthesizer",
            "synthesizer -> verify",
            # `route_after_verification`
            "verify -> repair",
            "verify -> critic",
            # `route_after_repair` — one edge per repair that re-enters
            # the graph, plus the total router's fallback to the critic.
            "repair -> search",
            "repair -> synthesizer",
            "repair -> critic",
            # `route_after_critique`, unchanged from the fixed pipeline.
            "critic -> planner",
            "critic -> search",
            "critic -> synthesizer",
            "critic -> __end__",
        }

    def test_the_impostor_case_compiles_to_the_plain_fixed_pipeline(self) -> None:
        """W05's acceptance criterion, as a test.

        `ENABLE_VERIFIER=true` with the supervisor off and the policy at
        its default is the configuration a reader of the settings table
        would reach for to "turn on verification" in the fixed graph. It
        does nothing at all, and it must keep doing nothing: the moment
        it grew a verify node, arm C would be reachable by a flag
        combination and the manifest could no longer tell C from B.
        """
        nodes, edges = _compile_listing(
            research_policy="legacy",
            enable_supervisor=False,
            enable_evidence_store=True,
            enable_verifier=True,
        )

        assert "verify" not in nodes
        assert "repair" not in nodes
        assert "verifier" not in nodes
        assert "synthesizer -> critic" in edges

    def test_no_legacy_flag_combination_produces_the_verify_node(self) -> None:
        """The stronger form of the same claim, over all eight.

        This is the sentence in the ADR — "arm C cannot be produced by
        any combination of the three legacy flags" — asserted rather
        than asserted-about.
        """
        for flags in (ARM_C_FLAGS, *INVALID_FLAG_COMBINATIONS):
            nodes, _ = _compile_listing(research_policy="legacy", **flags)
            assert "verify" not in nodes, flags
            assert "repair" not in nodes, flags


# ---------------------------------------------------------------------------
# 3. The repair decision is a table, not a model call
# ---------------------------------------------------------------------------


class TestTheRepairDecisionTable:
    def test_missing_evidence_retrieves_it(self) -> None:
        decision = decide_repair(
            _state(missing_evidence=["quantisation error rates"])  # type: ignore[arg-type]
        )
        assert decision.action == "retrieve_missing_evidence"
        assert decision.queries == ("quantisation error rates",)
        assert decision.reason == "missing_evidence"

    def test_unsupported_claims_are_qualified_or_removed(self) -> None:
        decision = decide_repair(
            _state(unsupported_claims=["LLMs never hallucinate"])  # type: ignore[arg-type]
        )
        assert decision.action == "qualify_or_remove_claims"
        assert decision.queries == ()
        assert decision.reason == "unsupported_claims"

    def test_missing_evidence_wins_when_both_are_reported(self) -> None:
        """The table's precedence, and why it is that way round.

        Retrieval can make an unsupported claim supportable; rewriting
        the claim cannot make a missing source appear. When both are
        flagged the run has one repair to spend, so it spends it on the
        one that can still change the evidence.
        """
        decision = decide_repair(
            _state(  # type: ignore[arg-type]
                missing_evidence=["a benchmark nobody cited"],
                unsupported_claims=["an over-claim"],
            )
        )
        assert decision.action == "retrieve_missing_evidence"

    @pytest.mark.parametrize("verdict", ["pass", "abstain"])
    def test_a_pass_or_an_abstain_repairs_nothing(self, verdict: str) -> None:
        """Abstain is not a failure, and must never be repaired as one.

        A verifier that could not judge (no draft, no citations, an
        upstream error) has said "I do not know". Acting on that as if it
        were "this is wrong" would spend the run's one repair on a
        diagnosis nobody made.
        """
        decision = decide_repair(
            _state(  # type: ignore[arg-type]
                verification_verdict=verdict,
                missing_evidence=["ignored while not failing"],
                unsupported_claims=["also ignored"],
            )
        )
        assert decision.action == "none"
        assert decision.reason == f"verdict_{verdict}"

    def test_a_failure_with_no_lists_records_the_unimplemented_reread(
        self,
    ) -> None:
        """ADR 0076's `not_implemented` row, half one.

        `read_more` is the verifier's way of saying "the source probably
        does support this, the reader missed it" — one of the five
        repairs 07 §3 approves, and one this work order does not build.
        The decision records that by name instead of silently falling
        through to "none", so the eval can count how often the missing
        repair was the indicated one.
        """
        decision = decide_repair(
            _state(verifier_recommendation="read_more")  # type: ignore[arg-type]
        )
        assert decision.action == "none"
        assert decision.reason == "reread_sections_not_implemented"

    def test_a_failure_recommending_a_revision_records_the_other_one(
        self,
    ) -> None:
        """ADR 0076's `not_implemented` row, half two."""
        decision = decide_repair(
            _state(verifier_recommendation="revise_report")  # type: ignore[arg-type]
        )
        assert decision.action == "none"
        assert decision.reason == "rewrite_section_not_implemented"

    def test_a_failure_with_nothing_to_act_on_says_so(self) -> None:
        decision = decide_repair(_state())  # type: ignore[arg-type]
        assert decision.action == "none"
        assert decision.reason == "no_actionable_repair"

    def test_gap_queries_are_deduplicated_against_what_was_already_tried(
        self,
    ) -> None:
        """The refiner's dedup rule, reused without enabling the refiner.

        Re-searching a query the run has already issued is the thrash ADR
        0018 exists to prevent; a repair that did it would spend the
        run's one repair on the result set it already has.
        """
        decision = decide_repair(
            _state(  # type: ignore[arg-type]
                missing_evidence=[
                    "  Quantisation Error Rates ",
                    "sparse attention benchmarks",
                    "quantisation error rates",
                ],
                tried_search_queries=["quantisation error rates"],
                search_queries=["sparse attention benchmarks"],
            )
        )
        # Case, surrounding space and a repeat within the batch are all
        # the same query; both distinct gaps are already in history.
        assert decision.action == "none"
        assert decision.queries == ()
        assert decision.reason == "missing_evidence_all_tried"

    def test_a_gap_that_has_not_been_searched_still_drives_the_repair(
        self,
    ) -> None:
        """The other half: dedup narrows the repair, it does not cancel it."""
        decision = decide_repair(
            _state(  # type: ignore[arg-type]
                missing_evidence=[
                    "quantisation error rates",
                    "sparse attention benchmarks",
                ],
                tried_search_queries=["Quantisation error rates"],
            )
        )
        assert decision.action == "retrieve_missing_evidence"
        assert decision.queries == ("sparse attention benchmarks",)

    def test_the_gap_query_list_is_bounded(self) -> None:
        """A verifier that lists thirty gaps must not drive thirty searches."""
        decision = decide_repair(
            _state(missing_evidence=[f"gap {i}" for i in range(30)])  # type: ignore[arg-type]
        )
        assert 0 < len(decision.queries) <= 5

    def test_every_declared_action_is_reachable_from_some_state(self) -> None:
        """The enum and the table are the same set.

        A value in `REPAIR_ACTIONS` that no state produces is a name in
        the ADR that the code cannot emit, which is exactly the kind of
        drift the run manifest would publish as capability.
        """
        produced = {
            decide_repair(_state(missing_evidence=["gap"])).action,  # type: ignore[arg-type]
            decide_repair(_state(unsupported_claims=["claim"])).action,  # type: ignore[arg-type]
            decide_repair(_state(verification_verdict="pass")).action,  # type: ignore[arg-type]
        }
        assert produced == set(REPAIR_ACTIONS)

    def test_the_decision_is_frozen(self) -> None:
        """Nothing downstream may edit the decision it was handed."""
        decision = decide_repair(_state(missing_evidence=["gap"]))  # type: ignore[arg-type]
        assert isinstance(decision, RepairDecision)
        with pytest.raises(AttributeError):
            decision.action = "none"  # type: ignore[misc]
