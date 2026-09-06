"""The branch tier is reachable, and off it changes nothing (ADR 0086).

Two halves, and the first one is the deliverable. CAP-04 baselined a
rule table, a reason vocabulary and a two-graph compile; CAP-03 extends
all three and must be able to prove that a deployment which has not
turned the branch tier on sees none of it. "Golden off" is asserted here
four ways — the table's own rules, a battery of decisions, the compiled
graph set, and the settings refusals — because each could regress
independently.

The second half is that the tier actually works when asked for: the T2
rules fire on the queries `02-target-architecture.md` §4 describes as
"ambiguous or evidence-sparse", the controller compiles a graph for the
tier it can now name, and the shape it compiles is the orchestrated one.
"""

from __future__ import annotations

from typing import Any

import pytest

import src.graph.workflow as workflow_module
from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts.research_binding import (
    ARM_REQUIRED_CAPABILITIES,
    ORCHESTRATED_WORKERS_POLICY_ID,
    ResearchBindingError,
    arm_capability_gap,
    classify_from_graph_shape,
    policy_snapshot,
    read_graph_shape,
)
from src.policies.compute import (
    BRANCH_REASON_CODES,
    BRANCH_TIER,
    BRANCH_TIER_LIMITS,
    BRANCH_TIER_RULES,
    COMPUTE_TIERS,
    DEFAULT_REASON,
    MAX_DECIDABLE_TIER,
    REASON_CODES,
    TIER_LIMITS,
    TIER_RULES,
    _branch_plan_breadth,
    _rules_for,
    decide_tier,
    eligible_tiers,
    extract_features,
)

pytestmark = pytest.mark.unit

#: Query -> (tier, reasons) under the **default** ceiling. Written out
#: rather than derived, because the claim is that these answers did not
#: move: a derivation from the table would agree with the table however
#: the table changed.
BASELINE_DECISIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("what is attention?", "T0", (DEFAULT_REASON,)),
    ("compare RAG and CoVe", "T1", ("comparative_cue", "multi_entity")),
    ("the latest work on hallucination", "T1", ("freshness_cue",)),
    (
        "compare RAG, CoVe and Self-RAG for hallucination mitigation",
        "T1",
        ("comparative_cue", "multi_entity"),
    ),
)

#: The same queries under a raised ceiling. Only the three-way
#: comparison moves, which is the whole point of the added rule: the
#: two-entity comparison is still a T1 question.
BRANCH_DECISIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("what is attention?", "T0", (DEFAULT_REASON,)),
    ("compare RAG and CoVe", "T1", ("comparative_cue", "multi_entity")),
    ("the latest work on hallucination", "T1", ("freshness_cue",)),
    (
        "compare RAG, CoVe and Self-RAG for hallucination mitigation",
        "T2",
        ("comparative_cue", "multi_entity", "branch_multi_entity_comparison"),
    ),
)


def config(**overrides: Any) -> Settings:
    patched = shipped_settings.model_copy(
        update={
            "enable_checkpointing": False,
            "enable_tracing": False,
            "enable_metrics": False,
            **overrides,
        }
    )
    assert isinstance(patched, Settings)
    return patched


def compile_with(**overrides: Any) -> Any:
    """Compile the workflow under `overrides`, restoring the binding after."""
    original = workflow_module.settings
    workflow_module.settings = config(**overrides)  # type: ignore[misc]
    try:
        return workflow_module.build_workflow(enable_hitl=False)
    finally:
        workflow_module.settings = original  # type: ignore[misc]


def nodes_of(app: Any) -> set[str]:
    return {
        str(name)
        for name in app.get_graph().nodes
        if name not in {"__start__", "__end__"}
    }


class TestTheDefaultTableDidNotMove:
    def test_the_default_ceiling_evaluates_exactly_the_baselined_rules(
        self,
    ) -> None:
        """Identity and order, not just membership.

        A filter that happened to return the same rules in a different
        order would change which reason code leads a decision, and the
        reason tuple is part of the record an evaluation groups by.
        """
        assert _rules_for(MAX_DECIDABLE_TIER) == TIER_RULES

    @pytest.mark.parametrize(("query", "tier", "reasons"), BASELINE_DECISIONS)
    def test_the_shipped_controller_decides_what_it_always_decided(
        self, query: str, tier: str, reasons: tuple[str, ...]
    ) -> None:
        decision = decide_tier(extract_features(query))

        assert decision.tier == tier
        assert decision.reasons == reasons
        assert decision.eligible == ("T0", "T1")
        assert decision.limits is TIER_LIMITS[tier]

    def test_the_published_vocabulary_is_unextended(self) -> None:
        """CAP-04's three published constants, still CAP-04's.

        `src/config.py` validates `tier_effort_overrides` against
        `COMPUTE_TIERS` and `TIER_LIMITS` is keyed by it, so widening
        either would change what a *flag-off* deployment accepts at
        load. The branch tier's own vocabulary lives beside them, and it
        is the half CAP-04b widened: two rules were added to the branch
        table (ADR 0087) and none to CAP-04's, so `REASON_CODES` — the
        vocabulary a flag-off deployment can emit — is unchanged and the
        two sets stay disjoint.
        """
        assert COMPUTE_TIERS == ("T0", "T1")
        assert set(TIER_LIMITS) == {"T0", "T1"}
        assert REASON_CODES == (
            "depth_quick",
            "depth_deep",
            "comparative_cue",
            "freshness_cue",
            "multi_entity",
            "long_query",
            "plan_breadth",
            "default_t0",
        )
        assert set(REASON_CODES).isdisjoint(BRANCH_REASON_CODES)
        assert BRANCH_REASON_CODES == (
            "branch_multi_entity_comparison",
            "branch_paired_comparison",
            "branch_open_enumeration",
            "branch_plan_breadth",
        )

    def test_the_default_controller_compiles_the_two_graphs_it_always_did(
        self,
    ) -> None:
        app = compile_with(compute_controller="deterministic")
        try:
            graphs = workflow_module.compute_tier_graphs(app)
            assert graphs is not None
            assert set(graphs) == {"T0", "T1"}
            assert graphs["T0"] is app
        finally:
            app._checkpointer_exit_stack.close()

    def test_orchestration_on_without_the_controller_compiles_nothing_extra(
        self,
    ) -> None:
        """The switch is consulted by the controller and by nothing else."""
        app = compile_with(orchestration="on")
        try:
            assert workflow_module.compute_tier_graphs(app) is None
            assert nodes_of(app) == {
                "planner",
                "search",
                "reader",
                "synthesizer",
                "critic",
            }
        finally:
            app._checkpointer_exit_stack.close()


class TestTheBranchTierIsReachableWhenAskedFor:
    def test_the_rules_are_only_evaluated_under_a_raised_ceiling(self) -> None:
        assert _rules_for(BRANCH_TIER) == (*TIER_RULES, *BRANCH_TIER_RULES)

    @pytest.mark.parametrize(("query", "tier", "reasons"), BRANCH_DECISIONS)
    def test_a_raised_ceiling_escalates_only_the_branch_shaped_query(
        self, query: str, tier: str, reasons: tuple[str, ...]
    ) -> None:
        """The highest tier any matching escalation named wins.

        The three-way comparison matches `comparative_cue`,
        `multi_entity` *and* the branch rule; the decision is T2 and
        every reason is on the record, so an analysis can see that the
        run would have been T1 under the old ceiling.
        """
        decision = decide_tier(extract_features(query), max_tier=BRANCH_TIER)

        assert decision.tier == tier
        assert decision.reasons == reasons
        assert decision.eligible == ("T0", "T1", "T2")

    def test_a_decisive_request_still_short_circuits_the_branch_rules(
        self,
    ) -> None:
        """`quick` means cheap, whatever the cues say — in both tables."""
        features = extract_features(
            "compare RAG, CoVe and Self-RAG", requested_depth="quick"
        )

        assert decide_tier(features, max_tier=BRANCH_TIER).tier == "T0"

    def test_a_plan_broader_than_the_planners_range_branches(self) -> None:
        """The post-plan rule, for a caller that decides after planning."""
        features = extract_features("survey the field", sub_question_count=5)

        assert decide_tier(features, max_tier=BRANCH_TIER).tier == "T2"
        assert decide_tier(features).tier == "T1", "unchanged under the default"

    def test_a_query_only_feature_vector_can_never_reach_that_rule(self) -> None:
        """Rule 12's known gap, pinned so it stays known (ADR 0087).

        Every shipped caller hands `extract_features` a query and nothing
        else, because the tier selects the *graph* and so cannot wait for
        the planner. `sub_question_count` is `None` on all of those
        paths, `_branch_plan_breadth` treats `None` as unanswered, and
        the rule therefore fires nowhere — which is why CAP-04b put the
        breadth signal in a query-time rule instead of tuning this one.
        """
        features = extract_features("survey the field")

        assert features.sub_question_count is None
        assert features.search_query_count is None
        assert not _branch_plan_breadth(features)

    #: Query -> (paired_comparison, open_enumeration), the two features
    #: ADR 0087 added. Both negatives are the load-bearing rows: a bare
    #: coordinating "and" joins two *properties* as readily as two
    #: systems, and a "how" question's plural noun modifies the one thing
    #: it asks about rather than naming a set to enumerate.
    NEW_FEATURES: tuple[tuple[str, bool, bool], ...] = (
        ("What are the tradeoffs between LoRA and full fine-tuning?", True, False),
        ("How do MoE models compare to dense models?", True, False),
        ("Is A better than B, or B versus C?", True, False),
        ("How do quantization methods trade off cost and quality?", False, False),
        ("compare RAG and CoVe", False, False),
        ("What is the relationship between attention and memory?", True, False),
        ("What approaches exist for reducing hallucination?", False, True),
        ("Which techniques speed up long-context inference?", False, True),
        ("How do speculative decoding methods reduce latency?", False, False),
        ("What role does synthetic data play in training?", False, False),
        ("What benchmarks capture reasoning ability?", False, False),
        ("what is attention?", False, False),
        ("", False, False),
    )

    @pytest.mark.parametrize(("query", "paired", "enumerative"), NEW_FEATURES)
    def test_the_two_added_features_read_the_shape_they_claim_to(
        self, query: str, paired: bool, enumerative: bool
    ) -> None:
        features = extract_features(query)

        assert features.paired_comparison is paired
        assert features.open_enumeration is enumerative

    def test_a_two_operand_comparison_branches_but_a_two_property_one_does_not(
        self,
    ) -> None:
        """Rule 10's whole claim, as the pair that separates it.

        Both queries carry a comparison word. Only one names two operands
        a corpus has to cover evenly; the other compares two properties
        of a single method class, which one ranked corpus serves — so it
        stays the T1 question ADR 0085 made it.
        """
        operands = extract_features(
            "What are the tradeoffs between LoRA and full fine-tuning?"
        )
        properties = extract_features(
            "How do quantization methods trade off cost and quality?"
        )
        assert operands.comparative_cue and properties.comparative_cue

        assert decide_tier(operands, max_tier=BRANCH_TIER).tier == "T2"
        assert decide_tier(properties, max_tier=BRANCH_TIER).tier == "T1"
        assert decide_tier(operands).tier == "T1", "unchanged under the default"

    def test_a_connective_without_a_comparison_word_does_not_branch(self) -> None:
        """`between X and Y` binds two operands and compares nothing."""
        features = extract_features(
            "What is the relationship between attention and memory?"
        )

        assert features.paired_comparison is True
        assert features.comparative_cue is False
        assert decide_tier(features, max_tier=BRANCH_TIER).tier == "T0"

    def test_an_open_enumeration_branches_and_a_named_family_does_not(self) -> None:
        """Rule 11's claim: the unnamed set is the one that costs N corpora."""
        enumerative = extract_features("What approaches exist for reducing drift?")
        named = extract_features("How do speculative decoding methods cut latency?")

        assert decide_tier(enumerative, max_tier=BRANCH_TIER).tier == "T2"
        assert decide_tier(named, max_tier=BRANCH_TIER).tier == "T0"
        assert decide_tier(enumerative).tier == "T0", "unchanged under the default"

    def test_lowering_the_entity_threshold_would_not_have_helped(self) -> None:
        """The counterfactual ADR 0087 rests on, measured rather than argued.

        ADR 0091 rejected moving `BRANCH_ENTITY_THRESHOLD` on ADR 0070's
        grounds, and this is the second, independent reason it was right
        to: `_is_entity_token` cannot see a lowercase multiword operand
        at all, so "LoRA and full fine-tuning" counts one entity and
        "mixture-of-experts models compare to dense models" counts zero.
        A threshold of two would have fired on neither.
        """
        for query in (
            "What are the tradeoffs between LoRA and full fine-tuning?",
            "How do mixture-of-experts models compare to dense models?",
        ):
            features = extract_features(query)
            assert features.comparative_cue is True
            assert features.entity_count < 2
            assert features.paired_comparison is True

    def test_the_branch_tier_reports_arm_cs_verification_limits(self) -> None:
        """T2 is the branch tier *plus* arm C, so it spends arm C's budget."""
        assert BRANCH_TIER_LIMITS.policy_id == ORCHESTRATED_WORKERS_POLICY_ID
        assert (
            BRANCH_TIER_LIMITS.max_verifications,
            BRANCH_TIER_LIMITS.max_repairs,
        ) == (TIER_LIMITS["T1"].max_verifications, TIER_LIMITS["T1"].max_repairs)

    def test_eligible_tiers_never_names_a_tier_above_the_ceiling(self) -> None:
        assert eligible_tiers() == ("T0", "T1")
        assert eligible_tiers("T0") == ("T0",)
        assert eligible_tiers(BRANCH_TIER) == ("T0", "T1", "T2")

    def test_the_controller_compiles_a_graph_for_the_tier_it_can_name(
        self,
    ) -> None:
        """One setting decides both, so the router can never miss a graph."""
        app = compile_with(compute_controller="deterministic", orchestration="on")
        try:
            graphs = workflow_module.compute_tier_graphs(app)
            assert graphs is not None
            assert set(graphs) == {"T0", "T1", "T2"}
            assert nodes_of(graphs["T2"]) == {
                "planner",
                "lead",
                "workers",
                "merge",
                "synthesizer",
                "verify",
                "repair",
                "critic",
            }
        finally:
            app._checkpointer_exit_stack.close()


class TestTheShapeIsClassifiedAsItself:
    def test_the_branch_graph_is_not_recorded_as_arm_c(self) -> None:
        """It carries verify and repair, and is still not arm C.

        A classifier that asked about `verify`/`repair` first would file
        every branch run under `research_fixed_verify_repair` and the
        branching would be invisible in the record — which is the exact
        mislabelling `classify_policy_shape` exists to prevent, one
        shape later.
        """
        cfg = config(
            research_policy="orchestrated_workers", enable_evidence_store=True
        )
        app = compile_with(
            research_policy="orchestrated_workers", enable_evidence_store=True
        )
        try:
            shape = classify_from_graph_shape(cfg, read_graph_shape(app))
        finally:
            app._checkpointer_exit_stack.close()

        assert shape.policy_id == ORCHESTRATED_WORKERS_POLICY_ID
        assert shape.arm_id is None
        assert shape.representable is False
        assert shape.declared_research_policy == "orchestrated_workers"

    def test_arm_e_still_names_the_selector_and_the_stop_rule_as_missing(
        self,
    ) -> None:
        """Half of arm E, recorded as half. CAP-09 closes the rest.

        `candidate_branching` is earned — there are branches, with
        lineage — and the other three are not: the compute router is a
        setting rather than a node, and neither the listwise selector
        nor the marginal-stop rule exists.
        """
        cfg = config(
            research_policy="orchestrated_workers", enable_evidence_store=True
        )
        app = compile_with(
            research_policy="orchestrated_workers", enable_evidence_store=True
        )
        try:
            shape = classify_from_graph_shape(cfg, read_graph_shape(app))
        finally:
            app._checkpointer_exit_stack.close()

        assert "candidate_branching" in shape.graph_capabilities
        assert arm_capability_gap("E", shape) == (
            "adaptive_compute_router",
            "marginal_stop",
            "candidate_lineage_selector",
        )
        assert shape.missing_capabilities == arm_capability_gap("E", shape)

    def test_the_branch_shape_seals_a_manifest_as_a_non_arm_policy(self) -> None:
        """ADR 0086's principal known gap, now closed by ADR 0089.

        This test used to assert the opposite and said why: `arm_id` was
        a required `A`-`E`, arm E's validator demanded a supervisor and a
        selection config, and a branch run therefore declined the seal
        exactly as a `capability_missing` configuration does — losing its
        lineage from the run record for a reason that was about the
        contract rather than about the run. It was written so the gap
        would close loudly, and this is that closure.

        The shape now seals as `research_shape`: its own policy id, its
        own node set, and no arm id at all. `representable` is still
        False, because "is this one of the five arms?" still answers no.
        """
        cfg = config(
            research_policy="orchestrated_workers", enable_evidence_store=True
        )
        app = compile_with(
            research_policy="orchestrated_workers", enable_evidence_store=True
        )
        try:
            shape = classify_from_graph_shape(cfg, read_graph_shape(app))
        finally:
            app._checkpointer_exit_stack.close()

        snapshot = policy_snapshot(shape)
        assert snapshot.policy_kind == "research_shape"
        assert snapshot.arm_id is None
        assert snapshot.selector is None
        assert snapshot.policy_id == ORCHESTRATED_WORKERS_POLICY_ID
        assert {"lead", "workers", "merge"} <= set(snapshot.shape_nodes)
        assert snapshot.graph_digest == shape.graph.digest
        # Still not arm E, and the shape still says exactly what is missing.
        assert shape.representable is False
        assert "candidate_lineage_selector" in shape.missing_capabilities

    def test_a_configuration_nobody_designed_still_declines_the_seal(self) -> None:
        """The refusal ADR 0089 deliberately kept.

        A non-arm *kind* is not a licence to name anything: a shape with
        no designed policy behind it has no honest id for a manifest to
        carry, so it refuses exactly as it always did.
        """
        cfg = config(enable_supervisor=True, enable_verifier=False)
        app = compile_with(enable_supervisor=True, enable_verifier=False)
        try:
            shape = classify_from_graph_shape(cfg, read_graph_shape(app))
        finally:
            app._checkpointer_exit_stack.close()

        assert shape.policy_kind is None
        with pytest.raises(
            ResearchBindingError, match="not a representable arm"
        ):
            policy_snapshot(shape)

    def test_the_fixed_shapes_earn_no_branching_capability(self) -> None:
        """The capability is earned by nodes, never by a policy name."""
        cfg = config(enable_evidence_store=True)
        app = compile_with(enable_evidence_store=True)
        try:
            shape = classify_from_graph_shape(cfg, read_graph_shape(app))
        finally:
            app._checkpointer_exit_stack.close()

        assert "candidate_branching" not in shape.graph_capabilities
        assert arm_capability_gap("E", shape) == ARM_REQUIRED_CAPABILITIES["E"]
        assert shape.arm_id == "B"


class TestTheSettingsRefuseAContradiction:
    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"enable_supervisor": True}, "enable_supervisor must be false"),
            ({"enable_evidence_store": False}, "enable_evidence_store must be true"),
            ({"enable_verifier": True}, "enable_verifier must be false"),
        ],
    )
    def test_the_branch_policy_needs_the_evidence_path_and_no_supervisor(
        self, overrides: dict[str, Any], message: str
    ) -> None:
        base = {
            "research_policy": "orchestrated_workers",
            "enable_supervisor": False,
            "enable_evidence_store": True,
            "enable_verifier": False,
        }
        with pytest.raises(ValueError, match=message):
            Settings(**{**base, **overrides})

    def test_the_controller_still_refuses_a_policy_that_fixed_the_shape(
        self,
    ) -> None:
        """Two claimants on one shape is one too many, third value included."""
        with pytest.raises(ValueError, match="research_policy must be legacy"):
            Settings(
                compute_controller="deterministic",
                research_policy="orchestrated_workers",
                enable_evidence_store=True,
            )

    def test_arm_cs_refusal_message_is_byte_identical_to_the_one_it_published(
        self,
    ) -> None:
        """A second policy must not have edited the first one's contract."""
        with pytest.raises(ValueError) as caught:
            Settings(research_policy="fixed_verify_repair", enable_supervisor=True)

        assert "research_policy=fixed_verify_repair requires a specific flag" in str(
            caught.value
        )
        assert "arm C is a fixed policy" in str(caught.value)
        assert "See ADR 0076." in str(caught.value)

    def test_the_switch_and_the_caps_are_off_and_bounded_by_default(self) -> None:
        fresh = Settings()

        assert fresh.orchestration == "off"
        assert fresh.orchestration_max_branches == 4
        assert fresh.orchestration_max_papers_per_branch == 4
        assert fresh.orchestration_branch_cost_share == 0.4

    @pytest.mark.parametrize(
        "overrides",
        [
            {"orchestration_max_branches": 0},
            {"orchestration_max_branches": 99},
            {"orchestration_max_papers_per_branch": 0},
            {"orchestration_branch_cost_share": 0.0},
            {"orchestration_branch_cost_share": 1.5},
        ],
    )
    def test_a_cap_outside_its_range_is_refused_at_load(
        self, overrides: dict[str, Any]
    ) -> None:
        """A cap that cannot bind is a cap nobody should be able to set."""
        with pytest.raises(ValueError):
            Settings(**overrides)
