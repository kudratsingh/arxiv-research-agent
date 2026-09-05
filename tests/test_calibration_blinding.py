"""Unit tests for `src/calibration/blinding.py` — P0-WO10.

03 §7 asks for three things: blind the judge to candidate identity and
arm, randomise pairwise ordering, and test for position bias. These tests
hold the module to all three, and to the two refusals that make them
enforceable — a plan cannot hide less than the required field set, and a
pairwise plan cannot present one order.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.calibration.blinding import (
    HIDDEN_FROM_JUDGE,
    BlindingPlan,
    PairOrder,
    Presentation,
    PresentationAssignment,
    assign_presentations,
    blind_item_id,
    leaked_identity_terms,
)
from src.contracts.kernel import ImmutableObjectRef, sha256_digest

pytestmark = pytest.mark.unit

SALT_REF = ImmutableObjectRef(
    kind="blinding_plan",
    id="judge-calibration-blinding",
    revision="1.0.0",
    digest=sha256_digest({"salt": "fixture"}),
)


def plan(
    *,
    presentation: Presentation = Presentation.SINGLE,
    seed: int = 7,
    hidden: tuple[str, ...] | None = None,
    both_orders: bool = True,
) -> BlindingPlan:
    return BlindingPlan(
        plan_id="p1",
        revision="1.0.0",
        salt_ref=SALT_REF,
        hidden_fields=hidden if hidden is not None else tuple(sorted(HIDDEN_FROM_JUDGE)),
        seed=seed,
        presentation=presentation,
        both_orders=both_orders,
        created_at="2026-09-05T00:00:00Z",
    )


class TestBlindedIds:
    def test_the_same_salt_and_id_always_give_the_same_blinded_id(self) -> None:
        assert blind_item_id("s", "case-1") == blind_item_id("s", "case-1")

    def test_a_different_salt_gives_a_different_id(self) -> None:
        assert blind_item_id("s1", "case-1") != blind_item_id("s2", "case-1")

    def test_the_nul_separator_keeps_split_points_distinct(self) -> None:
        """Without it ("ab", "cd") and ("a", "bcd") would collide.

        A campaign that salts per slice would then get two slices sharing
        a blinded id, which reads as one item labelled twice.
        """
        assert blind_item_id("ab", "cd") != blind_item_id("a", "bcd")

    def test_the_shape_is_the_one_the_label_schema_accepts(self) -> None:
        blinded = blind_item_id("s", "case-1")

        assert blinded.startswith("itm-")
        assert len(blinded) == len("itm-") + 12
        assert all(character in "0123456789abcdef" for character in blinded[4:])

    def test_an_empty_salt_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unsalted digest is reversible"):
            blind_item_id("", "case-1")


class TestThePlanCannotHideLessThanRequired:
    def test_the_required_field_set_names_arm_and_candidate_and_their_proxies(self) -> None:
        assert {"arm_id", "candidate_id"} <= HIDDEN_FROM_JUDGE
        # The fields that reconstruct them. A report tagged with its
        # policy, model, run id or cost is not blinded.
        assert {"policy_id", "model_id", "run_id", "cost_usd"} <= HIDDEN_FROM_JUDGE
        # And the evaluator-only material 12 §3.6 keeps away from a
        # candidate, kept away from the judge for the same reason.
        assert {"reference_answer", "expected_label", "split_membership"} <= HIDDEN_FROM_JUDGE

    def test_a_plan_that_omits_one_required_field_is_refused(self) -> None:
        short = tuple(sorted(HIDDEN_FROM_JUDGE - {"arm_id"}))

        with pytest.raises(ValidationError, match="missing \\['arm_id'\\]"):
            plan(hidden=short)

    def test_a_plan_may_hide_more(self) -> None:
        extra = (*sorted(HIDDEN_FROM_JUDGE), "annotator_id")

        assert "annotator_id" in plan(hidden=extra).hidden_fields

    def test_duplicate_hidden_fields_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="must be unique"):
            plan(hidden=(*sorted(HIDDEN_FROM_JUDGE), "arm_id"))

    def test_a_judge_that_sees_the_reference_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="not being calibrated against it"):
            BlindingPlan(
                plan_id="p1",
                revision="1.0.0",
                salt_ref=SALT_REF,
                hidden_fields=tuple(sorted(HIDDEN_FROM_JUDGE)),
                seed=1,
                presentation=Presentation.SINGLE,
                judge_sees_reference=True,
                created_at="2026-09-05T00:00:00Z",
            )

    def test_a_pairwise_plan_must_swap(self) -> None:
        with pytest.raises(ValidationError, match="cannot separate a preference"):
            plan(presentation=Presentation.PAIRWISE, both_orders=False)


class TestThePresentationSchedule:
    def test_a_single_plan_gives_one_assignment_per_item(self) -> None:
        ids = [f"itm-{index:012x}" for index in range(5)]

        schedule = assign_presentations(ids, plan=plan())

        assert len(schedule) == 5
        assert {entry.blinded_item_id for entry in schedule} == set(ids)
        assert all(entry.order is None for entry in schedule)

    def test_a_pairwise_plan_gives_both_orders_for_every_pair(self) -> None:
        ids = [f"itm-{index:012x}" for index in range(4)]

        schedule = assign_presentations(ids, plan=plan(presentation=Presentation.PAIRWISE))

        assert len(schedule) == 8
        for item_id in ids:
            orders = {
                entry.order for entry in schedule if entry.blinded_item_id == item_id
            }
            assert orders == {PairOrder.AB, PairOrder.BA}

    def test_the_sequence_is_contiguous_from_one(self) -> None:
        ids = [f"itm-{index:012x}" for index in range(6)]

        schedule = assign_presentations(ids, plan=plan(presentation=Presentation.PAIRWISE))

        assert [entry.sequence for entry in schedule] == list(range(1, 13))

    def test_the_same_seed_gives_the_same_schedule(self) -> None:
        ids = [f"itm-{index:012x}" for index in range(12)]

        first = assign_presentations(ids, plan=plan(seed=99))
        second = assign_presentations(ids, plan=plan(seed=99))

        assert first == second

    def test_a_different_seed_gives_a_different_schedule(self) -> None:
        ids = [f"itm-{index:012x}" for index in range(12)]

        first = assign_presentations(ids, plan=plan(seed=1))
        second = assign_presentations(ids, plan=plan(seed=2))

        assert first != second

    def test_the_schedule_depends_on_the_set_not_on_the_input_order(self) -> None:
        ids = [f"itm-{index:012x}" for index in range(8)]

        assert assign_presentations(ids, plan=plan()) == assign_presentations(
            list(reversed(ids)), plan=plan()
        )

    def test_the_module_does_not_perturb_the_global_generator(self) -> None:
        import random

        random.seed(1234)
        expected = random.random()

        random.seed(1234)
        assign_presentations([f"itm-{i:012x}" for i in range(20)], plan=plan(seed=5))

        assert random.random() == expected

    def test_duplicate_ids_are_refused(self) -> None:
        with pytest.raises(ValueError, match="must be distinct"):
            assign_presentations(["itm-00000000000a", "itm-00000000000a"], plan=plan())

    def test_an_unblinded_id_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not a blinded item id"):
            assign_presentations(["polish-scaling-emergent"], plan=plan())

    def test_an_assignment_without_an_order_cannot_claim_to_be_pairwise(self) -> None:
        with pytest.raises(ValidationError, match="a pairwise assignment has an order"):
            PresentationAssignment(
                sequence=1,
                blinded_item_id="itm-00000000000a",
                presentation=Presentation.PAIRWISE,
                order=None,
            )


class TestTheLeakScan:
    def test_a_forbidden_term_in_the_rendered_input_is_found(self) -> None:
        rendered = "The verify-and-repair pass in arm-c produced the following report."

        assert leaked_identity_terms(rendered, ["arm-c", "arm-a"]) == ("arm-c",)

    def test_matching_is_case_insensitive(self) -> None:
        assert leaked_identity_terms("Produced by Claude-Opus-5.", ["claude-opus-5"]) == (
            "claude-opus-5",
        )

    def test_a_term_inside_a_longer_word_is_not_a_leak(self) -> None:
        assert leaked_identity_terms("the harm-caused analysis", ["arm-c"]) == ()

    def test_a_clean_input_returns_nothing(self) -> None:
        assert leaked_identity_terms("A report about scaling laws.", ["arm-c", "arm-e"]) == ()

    def test_findings_are_sorted_and_deduplicated(self) -> None:
        rendered = "arm-e then arm-c then arm-e again"

        assert leaked_identity_terms(rendered, ["arm-e", "arm-c", "arm-e"]) == (
            "arm-c",
            "arm-e",
        )

    def test_a_regex_shaped_term_is_matched_literally(self) -> None:
        """A blinding check is not the place to run a pattern somebody typed."""
        assert leaked_identity_terms("the report", ["."]) == ()
        assert leaked_identity_terms("policy(a|b)", ["policy(a|b)"]) == ("policy(a|b)",)

    def test_an_empty_term_is_ignored_rather_than_matching_everything(self) -> None:
        assert leaked_identity_terms("anything at all", ["", "arm-c"]) == ()
