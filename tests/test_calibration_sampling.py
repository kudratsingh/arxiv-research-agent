"""Unit tests for `src/calibration/sampling.py` — P0-WO10.

The arithmetic in the protocol document is reproduced here from
``src/eval/stats.py`` rather than quoted, so a reader can check the plan
without trusting the prose — the same discipline ADR 0071 applied to
02-STANDARDS §2.3's published 77 and 906.

The headline is the refusal: at twenty paired queries the smallest
difference that reaches significance at all is twenty points, and the
smallest detectable at 80% power is thirty-five. Every per-slice number
below is a diagnostic sitting under that ceiling.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.calibration.fixtures import ADVERSARIAL_PATH, PAIRWISE_PATH, load_case_file
from src.calibration.labels import (
    Annotator,
    AnnotatorKind,
    CalibrationLabel,
    Confidence,
    LabelledItem,
    LabelType,
)
from src.calibration.sampling import (
    CURRENT_BENCHMARK_QUERIES,
    FAILURE_CLASSES,
    TASK_SLICES,
    SamplingPlan,
    SliceAxis,
    SliceSpec,
    items_for_precision,
    items_to_bound_below,
    noise_floor,
    observe_coverage,
    slice_requirements,
    standard_plan,
    untracked_tags,
)
from src.contracts.kernel import ImmutableObjectRef, sha256_digest
from src.eval.stats import mcnemar_required_pairs, unpaired_required_per_arm, wilson_interval

pytestmark = pytest.mark.unit

def _revalidate(plan: SamplingPlan, **overrides: object) -> SamplingPlan:
    """Round-trip a plan through JSON with fields replaced.

    Through JSON because `StrictContractModel` is strict: a Python list
    is not a tuple, and a JSON array is the tuple's wire form.
    """
    payload = {**plan.model_dump(mode="json"), **overrides}
    return SamplingPlan.model_validate_json(json.dumps(payload))


REF = ImmutableObjectRef(
    kind="calibration_rationale",
    id="r1",
    revision="1.0.0",
    digest=sha256_digest({"text": "x"}),
)


def _item(item_id: str, tags: tuple[str, ...], *, resolved: bool) -> LabelledItem:
    def label(label_id: str, decision: str, who: str) -> CalibrationLabel:
        return CalibrationLabel(
            label_id=label_id,
            blinded_item_id=item_id,
            label_type=LabelType.CLAIM_SUPPORT,
            decision=decision,
            confidence=Confidence.HIGH,
            rationale_ref=REF,
            annotator=Annotator(
                annotator_id=who,
                kind=AnnotatorKind.HUMAN_EXPERT,
                guideline_revision="1.0.0",
            ),
            labeled_at="2026-09-05T00:00:00Z",
            guideline_ref=REF,
        )

    second = "supported" if resolved else "unsupported"
    return LabelledItem(
        blinded_item_id=item_id,
        label_type=LabelType.CLAIM_SUPPORT,
        slice_tags=tags,
        labels=(label("l1", "supported", "ann-a1f4"), label("l2", second, "ann-b2c7")),
    )


class TestTheSlicesAre07Section8s:
    def test_five_axes_with_two_levels_each(self) -> None:
        assert len(TASK_SLICES) == 10
        assert {spec.axis for spec in TASK_SLICES} == set(SliceAxis)
        for axis in SliceAxis:
            assert sum(1 for spec in TASK_SLICES if spec.axis is axis) == 2

    def test_slice_ids_are_unique(self) -> None:
        ids = [spec.slice_id for spec in TASK_SLICES]

        assert len(set(ids)) == len(ids)

    def test_a_slice_assigned_from_candidate_outcomes_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="it is a result"):
            SliceSpec(
                slice_id="looked-bad",
                axis=SliceAxis.BASELINE_DIFFICULTY,
                level="hard",
                definition="Cases the candidate did badly on.",
                assignment_rule="Read the candidate's scores and take the bottom half.",
                assigned_from_candidate_outcomes=True,
            )

    def test_the_difficulty_slice_names_the_baseline_arm_not_the_candidate(self) -> None:
        hard = next(spec for spec in TASK_SLICES if spec.slice_id == "baseline-hard")

        assert "baseline" in hard.assignment_rule
        assert hard.assigned_from_candidate_outcomes is False

    def test_the_failure_taxonomy_is_03_section_8s_thirteen_classes(self) -> None:
        assert len(FAILURE_CLASSES) == 13
        assert "verification-false-pass-or-false-fail" in FAILURE_CLASSES
        assert len(set(FAILURE_CLASSES)) == 13


class TestPrecisionSizing:
    @pytest.mark.parametrize(
        ("rate", "half_width", "expected"),
        [
            (0.10, 0.05, 141),
            (0.10, 0.10, 34),
            (0.20, 0.05, 245),
            (0.05, 0.05, 82),
        ],
    )
    def test_the_published_item_counts_reproduce(
        self, rate: float, half_width: float, expected: int
    ) -> None:
        assert items_for_precision(expected_rate=rate, half_width=half_width) == expected

    def test_the_returned_n_actually_reaches_the_target_width(self) -> None:
        n = items_for_precision(expected_rate=0.10, half_width=0.10)
        interval = wilson_interval(round(0.10 * n), n)

        assert interval.width / 2.0 <= 0.10
        # And one fewer does not, which is what makes it the smallest.
        smaller = wilson_interval(round(0.10 * (n - 1)), n - 1)
        assert smaller.width / 2.0 > 0.10

    @pytest.mark.parametrize(
        ("observed", "ceiling", "expected"),
        [(0.0, 0.10, 35), (0.02, 0.10, 53), (0.05, 0.10, 127), (0.0, 0.05, 73)],
    )
    def test_the_published_bound_counts_reproduce(
        self, observed: float, ceiling: float, expected: int
    ) -> None:
        assert items_to_bound_below(observed_rate=observed, ceiling=ceiling) == expected

    def test_bounding_a_zero_rate_below_ten_percent_agrees_with_the_rule_of_three(
        self,
    ) -> None:
        """3/n <= 0.10 gives n >= 30; Wilson's exact answer is 35."""
        from src.eval.stats import rule_of_three

        n = items_to_bound_below(observed_rate=0.0, ceiling=0.10)

        assert n == 35
        assert rule_of_three(30) == pytest.approx(0.10)
        assert wilson_interval(0, n).high <= 0.10

    def test_a_rate_already_over_the_ceiling_is_refused_rather_than_searched(self) -> None:
        with pytest.raises(ValueError, match="already over the ceiling"):
            items_to_bound_below(observed_rate=0.2, ceiling=0.1)

    def test_out_of_range_inputs_are_refused(self) -> None:
        with pytest.raises(ValueError, match="expected_rate"):
            items_for_precision(expected_rate=1.5, half_width=0.1)
        with pytest.raises(ValueError, match="half_width"):
            items_for_precision(expected_rate=0.1, half_width=0.0)
        with pytest.raises(ValueError, match="observed_rate"):
            items_to_bound_below(observed_rate=-0.1, ceiling=0.1)
        with pytest.raises(ValueError, match="ceiling"):
            items_to_bound_below(observed_rate=0.01, ceiling=1.0)


class TestTheNoiseFloorOfTwentyQueries:
    def test_twenty_queries_cannot_resolve_less_than_twenty_points(self) -> None:
        floor = noise_floor()

        assert floor.pairs == CURRENT_BENCHMARK_QUERIES == 20
        assert floor.smallest_significant_delta == pytest.approx(0.20)
        assert floor.smallest_detectable_delta == pytest.approx(0.35)

    def test_the_five_point_figures_are_adr_0071s(self) -> None:
        floor = noise_floor()

        assert floor.pairs_for_five_points == 77
        assert floor.powered_pairs_for_five_points == 155
        assert floor.unpaired_for_five_points == 906
        # And they come from the shared estimators rather than a copy.
        assert floor.pairs_for_five_points == mcnemar_required_pairs(
            delta=0.05, discordance=0.05, power=0.5
        )
        assert floor.unpaired_for_five_points == unpaired_required_per_arm(
            baseline_rate=0.80, delta=0.05
        )

    def test_the_smallest_deltas_are_the_smallest(self) -> None:
        floor = noise_floor()

        assert (
            mcnemar_required_pairs(
                delta=floor.smallest_significant_delta,
                discordance=floor.smallest_significant_delta,
                power=0.5,
            )
            <= 20
        )
        assert (
            mcnemar_required_pairs(delta=0.19, discordance=0.19, power=0.5) > 20
        )

    def test_the_statement_is_printable_and_names_its_own_ceiling(self) -> None:
        statement = noise_floor().statement()

        assert "20 paired items" in statement
        assert "20%" in statement
        assert "35%" in statement
        assert "coin flip" in statement

    def test_a_larger_sample_resolves_more(self) -> None:
        assert noise_floor(200).smallest_detectable_delta < noise_floor(20).smallest_detectable_delta

    def test_zero_pairs_is_refused(self) -> None:
        with pytest.raises(ValueError, match="pairs must be positive"):
            noise_floor(0)


class TestSliceRequirements:
    def test_every_slice_gets_the_same_sizing_inputs(self) -> None:
        requirements = slice_requirements()

        assert len(requirements) == len(TASK_SLICES)
        assert len({req.precision_items for req in requirements}) == 1
        assert requirements[0].precision_items == 34
        assert requirements[0].bound_items == 53
        assert requirements[0].significance_pairs == 77
        assert requirements[0].powered_pairs == 155
        assert requirements[0].unpaired_per_arm == 906

    def test_the_requirement_ids_follow_the_slices_given(self) -> None:
        subset = TASK_SLICES[:3]

        assert [req.slice_id for req in slice_requirements(subset)] == [
            spec.slice_id for spec in subset
        ]


class TestTheStandardPlan:
    def test_the_plan_sizes_itself_from_the_estimators(self) -> None:
        plan = standard_plan(pilot_items=30)

        assert plan.items_per_slice == items_for_precision(expected_rate=0.10, half_width=0.10)
        assert plan.whole_set_items == items_for_precision(
            expected_rate=0.10, half_width=0.05
        )
        assert plan.items_per_slice == 34
        assert plan.whole_set_items == 141

    def test_the_pessimistic_total_is_reported_beside_the_whole_set_target(self) -> None:
        plan = standard_plan(pilot_items=30)

        # Ten slices at 34 items each if no case ever belonged to two.
        assert plan.upper_bound_items == 340
        assert plan.whole_set_items < plan.upper_bound_items

    def test_a_pilot_the_size_of_the_campaign_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="a pilot the size of the campaign"):
            standard_plan(pilot_items=500)

    def test_the_synthetic_corpus_is_the_pilot_and_is_far_smaller(self) -> None:
        cases = load_case_file(ADVERSARIAL_PATH).cases
        pairs = load_case_file(PAIRWISE_PATH).pairwise
        plan = standard_plan(pilot_items=len(cases) + len(pairs))

        assert plan.pilot_items == 30
        assert plan.pilot_items < plan.whole_set_items


class TestCoverage:
    def test_only_resolved_items_count_toward_a_slice_target(self) -> None:
        plan = standard_plan(pilot_items=30)
        items = [
            _item("itm-00000000000a", ("evidence-rich",), resolved=True),
            _item("itm-00000000000b", ("evidence-rich",), resolved=False),
        ]

        observations = {obs.slice_id: obs for obs in observe_coverage(plan, items)}
        rich = observations["evidence-rich"]

        assert rich.labelled == 2
        assert rich.resolved == 1
        assert rich.shortfall == plan.items_per_slice - 1
        assert not rich.unmeasured

    def test_a_slice_with_no_resolved_item_reports_unmeasured(self) -> None:
        plan = standard_plan(pilot_items=30)
        items = [_item("itm-00000000000a", ("evidence-rich",), resolved=False)]

        observations = {obs.slice_id: obs for obs in observe_coverage(plan, items)}

        assert observations["evidence-rich"].unmeasured
        assert observations["evidence-sparse"].unmeasured

    def test_an_undeclared_tag_is_reported_rather_than_folded_into_a_total(self) -> None:
        plan = standard_plan(pilot_items=30)
        items = [_item("itm-00000000000a", ("evidence-rich", "made-up-slice"), resolved=True)]

        assert untracked_tags(plan, items) == ("made-up-slice",)
        observations = {obs.slice_id: obs for obs in observe_coverage(plan, items)}
        assert observations["evidence-rich"].resolved == 1

    def test_a_failure_class_is_a_declared_tag_not_an_untracked_one(self) -> None:
        plan = standard_plan(pilot_items=30)
        items = [
            _item("itm-00000000000a", ("evidence-rich", "retrieval-miss"), resolved=True)
        ]

        assert untracked_tags(plan, items) == ()


class TestTheRemainingRefusals:
    def test_an_impossible_precision_request_is_refused_rather_than_spinning(self) -> None:
        with pytest.raises(ValueError, match="no sample size at or below"):
            items_for_precision(expected_rate=0.5, half_width=0.00001)

    def test_an_impossible_bound_request_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no sample size at or below"):
            items_to_bound_below(observed_rate=0.09999, ceiling=0.1)

    def test_a_single_pair_reports_a_floor_of_one_hundred_percent(self) -> None:
        """The honest answer when nothing is resolvable: the search finds
        no delta small enough, so it reports the whole range."""
        floor = noise_floor(1)

        assert floor.smallest_significant_delta == pytest.approx(1.0)
        assert floor.smallest_detectable_delta == pytest.approx(1.0)

    def test_a_plan_with_no_slices_is_refused(self) -> None:
        plan = standard_plan(pilot_items=30)

        with pytest.raises(ValidationError, match="non-empty and unique"):
            _revalidate(plan, slices=[])

    def test_a_plan_with_duplicate_slices_is_refused(self) -> None:
        plan = standard_plan(pilot_items=30)
        first = plan.model_dump(mode="json")["slices"][0]

        with pytest.raises(ValidationError, match="non-empty and unique"):
            _revalidate(plan, slices=[first, first])

    def test_a_plan_with_duplicate_failure_classes_is_refused(self) -> None:
        plan = standard_plan(pilot_items=30)

        with pytest.raises(ValidationError, match="failure classes must be unique"):
            _revalidate(plan, failure_classes=["retrieval-miss", "retrieval-miss"])

    def test_untracked_tags_are_reported_for_an_empty_corpus_as_nothing(self) -> None:
        assert untracked_tags(standard_plan(pilot_items=30), []) == ()
