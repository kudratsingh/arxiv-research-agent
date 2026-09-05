"""Unit tests for `src/calibration/metrics.py` — P0-WO10.

Every estimator here is checked against a value computed by hand in the
test, from the published formula, on the twelve-item worked set in
``tests/fixtures/calibration/labelled_set.json``. That is ADR 0071's
rule applied to this module: a metric checked only against its own output
proves the code has not changed, which is a different claim from the code
being right.

The gate's three states are constructed rather than sampled, so PROMOTE,
HOLD and ROLLBACK each have a test that reaches it deliberately.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from src.calibration.fixtures import (
    load_labelled_set,
    load_pairwise,
)
from src.calibration.labels import (
    Annotator,
    AnnotatorKind,
    CalibrationLabel,
    Confidence,
    JudgeVerdict,
    LabelledItem,
    LabelType,
    resolved_pairs,
)
from src.calibration.metrics import (
    DEFAULT_THRESHOLDS,
    INTEGRITY_VIOLATION_CLASSES,
    AbstentionPolicy,
    CalibrationReport,
    GateDecision,
    IntegrityFinding,
    SliceCoverage,
    UsabilityThresholds,
    agreement,
    agreement_under_each_policy,
    build_report,
    confusion,
    decide,
    error_rates,
    find_integrity_violations,
    phi_coefficient,
    position_bias,
    rate_with_interval,
    report_lines,
    slice_coverage,
)
from src.calibration.sampling import SliceObservation
from src.contracts.kernel import ImmutableObjectRef, sha256_digest
from src.eval import safety_suite

pytestmark = pytest.mark.unit

AT = "2026-09-05T00:00:00Z"
GRADER = ImmutableObjectRef(
    kind="grader_profile",
    id="judge-under-calibration",
    revision="1.0.0",
    digest=sha256_digest({"profile": "v1"}),
)
RATIONALE = ImmutableObjectRef(
    kind="calibration_rationale",
    id="r1",
    revision="1.0.0",
    digest=sha256_digest({"text": "x"}),
)
GUIDELINE = ImmutableObjectRef(
    kind="calibration_guideline",
    id="guide",
    revision="1.0.0",
    digest=sha256_digest({"guide": "v1"}),
)


@pytest.fixture(scope="module")
def worked_pairs() -> tuple[tuple[str, bool | None, bool | None], ...]:
    """The twelve-item worked set, paired by blinded id."""
    worked = load_labelled_set()
    return resolved_pairs(worked.items, worked.judge_verdicts)


class TestTheConfusionTableIsHandComputed:
    """The worked set was authored to land four items in each corner.

    4 true passes, 2 false passes, 3 true fails, 1 false fail, plus one
    item the judge abstained on and one the annotators never resolved.
    Twelve items; ten in the 2x2.
    """

    def test_the_table_matches_the_authored_counts(
        self, worked_pairs: tuple[tuple[str, bool | None, bool | None], ...]
    ) -> None:
        counts = confusion(worked_pairs)

        assert (counts.true_pass, counts.false_pass) == (4, 2)
        assert (counts.true_fail, counts.false_fail) == (3, 1)
        assert counts.judge_abstained == 1
        assert counts.reference_unresolved == 1
        assert counts.unmatched == 0
        assert counts.decided == 10
        assert counts.total == 12

    def test_raw_agreement_is_seven_of_ten(
        self, worked_pairs: tuple[tuple[str, bool | None, bool | None], ...]
    ) -> None:
        # (TP + TN) / decided = (4 + 3) / 10.
        assert agreement(worked_pairs).raw_agreement == pytest.approx(0.7)

    def test_phi_is_ten_over_root_six_hundred(
        self, worked_pairs: tuple[tuple[str, bool | None, bool | None], ...]
    ) -> None:
        # (TP*TN - FP*FN) / sqrt((TP+FP)(TP+FN)(TN+FP)(TN+FN))
        # = (4*3 - 2*1) / sqrt(6 * 5 * 5 * 4) = 10 / sqrt(600).
        expected = 10.0 / math.sqrt(600.0)

        assert agreement(worked_pairs).phi == pytest.approx(expected)
        assert expected == pytest.approx(0.408248, abs=1e-6)

    def test_both_positive_rates_are_reported_beside_phi(
        self, worked_pairs: tuple[tuple[str, bool | None, bool | None], ...]
    ) -> None:
        # docs/eval.md: kappa = q*phi is uninterpretable without both.
        summary = agreement(worked_pairs)

        assert summary.judge_positive_rate == pytest.approx(0.6)  # (4 + 2) / 10
        assert summary.reference_positive_rate == pytest.approx(0.5)  # (4 + 1) / 10

    def test_the_error_rates_use_three_different_denominators(
        self, worked_pairs: tuple[tuple[str, bool | None, bool | None], ...]
    ) -> None:
        rates = error_rates(worked_pairs)

        assert (rates.false_pass.numerator, rates.false_pass.denominator) == (2, 5)
        assert rates.false_pass.rate == pytest.approx(0.4)
        assert (rates.false_fail.numerator, rates.false_fail.denominator) == (1, 5)
        assert rates.false_fail.rate == pytest.approx(0.2)
        # Abstention is over items with a resolved reference: 11 of 12.
        assert (rates.abstention.numerator, rates.abstention.denominator) == (1, 11)
        assert (
            rates.unresolved_reference.numerator,
            rates.unresolved_reference.denominator,
        ) == (1, 12)

    def test_every_interval_comes_from_the_shared_estimator(
        self, worked_pairs: tuple[tuple[str, bool | None, bool | None], ...]
    ) -> None:
        from src.eval.stats import wilson_interval

        rates = error_rates(worked_pairs)

        assert rates.false_pass.interval == wilson_interval(2, 5)

    def test_the_small_sample_caveat_fires_at_ten_decided_items(
        self, worked_pairs: tuple[tuple[str, bool | None, bool | None], ...]
    ) -> None:
        caveat = agreement(worked_pairs).caveat

        assert caveat is not None
        assert "approximate at n=10" in caveat


class TestTheAbstentionPolicyIsDeclaredAndItsSwingIsVisible:
    def test_the_three_policies_give_three_different_tables(
        self, worked_pairs: tuple[tuple[str, bool | None, bool | None], ...]
    ) -> None:
        reports = agreement_under_each_policy(list(worked_pairs))

        excluded = reports[AbstentionPolicy.EXCLUDED]
        as_fail = reports[AbstentionPolicy.COUNTED_AS_FAIL]
        as_pass = reports[AbstentionPolicy.COUNTED_AS_PASS]

        # The one abstained item has a reference decision of "supported",
        # so counting it as a fail makes it a false fail and counting it
        # as a pass makes it a true pass.
        assert excluded.counts.decided == 10
        assert as_fail.counts.false_fail == 2
        assert as_pass.counts.true_pass == 5
        assert as_fail.raw_agreement != as_pass.raw_agreement

    def test_the_abstention_rate_survives_every_policy(
        self, worked_pairs: tuple[tuple[str, bool | None, bool | None], ...]
    ) -> None:
        """A policy may move an abstention into a cell; it may not hide it."""
        for policy in AbstentionPolicy:
            rates = error_rates(worked_pairs, policy=policy)

            assert rates.abstention.numerator == 1
            assert rates.abstention.denominator == 11

    def test_every_report_carries_the_policy_it_used(
        self, worked_pairs: tuple[tuple[str, bool | None, bool | None], ...]
    ) -> None:
        assert agreement(worked_pairs).policy is AbstentionPolicy.EXCLUDED
        assert (
            agreement(worked_pairs, policy=AbstentionPolicy.COUNTED_AS_FAIL).policy
            is AbstentionPolicy.COUNTED_AS_FAIL
        )


class TestPhiRefusesToInventAnAssociation:
    def test_a_degenerate_margin_gives_none_rather_than_zero(self) -> None:
        # A judge that passed everything: TN = FN = 0, two margins zero.
        pairs = [("itm-00000000000a", True, True), ("itm-00000000000b", False, True)]

        assert phi_coefficient(confusion(pairs)) is None

    def test_an_empty_table_reports_nothing_rather_than_zero(self) -> None:
        summary = agreement([])

        assert summary.raw_agreement is None
        assert summary.phi is None
        assert summary.judge_positive_rate is None
        assert summary.raw_agreement_interval is None

    def test_perfect_agreement_gives_phi_of_one(self) -> None:
        pairs = [
            ("itm-00000000000a", True, True),
            ("itm-00000000000b", False, False),
        ]

        assert phi_coefficient(confusion(pairs)) == pytest.approx(1.0)

    def test_perfect_disagreement_gives_phi_of_minus_one(self) -> None:
        pairs = [
            ("itm-00000000000a", True, False),
            ("itm-00000000000b", False, True),
        ]

        assert phi_coefficient(confusion(pairs)) == pytest.approx(-1.0)


class TestPositionBiasNeedsBothOrders:
    def test_the_fixture_pairs_give_eight_first_position_wins_of_twelve(self) -> None:
        """Hand-counted from tests/fixtures/calibration/pairwise_cases.json.

        ab/ba readings per pair: (first, first), (first, first),
        (first, second), (second, first), (first, first),
        (second, second) — 2 + 2 + 1 + 1 + 2 + 0 = 8 of 12 readings.
        """
        cases = load_pairwise()
        verdicts = [
            JudgeVerdict(
                verdict_id=f"{case.case_id}.{order}",
                blinded_item_id=case.blinded_item_id,
                label_type=LabelType.PAIRWISE_PREFERENCE,
                decision=decision,
                grader_profile_ref=GRADER,
                rubric_name="pairwise",
                rubric_version="1.0.0",
                presentation_order=order,
                observed_at=AT,
            )
            for case in cases
            for order, decision in (
                ("ab", case.expected_ab_verdict),
                ("ba", case.expected_ba_verdict),
            )
        ]

        bias = position_bias(verdicts)

        assert (bias.both_orders, bias.readings) == (6, 12)
        assert bias.first_position_wins == 8
        assert bias.first_position_rate == pytest.approx(8 / 12)
        assert bias.bias == pytest.approx(8 / 12 - 0.5)
        # Consistent pairs are those whose two readings name the same
        # report: (first, second) and (second, first). Two of six.
        assert bias.consistent == 2
        assert bias.consistency_rate == pytest.approx(2 / 6)
        assert bias.ties == 0

    def test_a_pair_seen_in_one_order_contributes_nothing(self) -> None:
        verdict = JudgeVerdict(
            verdict_id="v1",
            blinded_item_id="itm-00000000000a",
            label_type=LabelType.PAIRWISE_PREFERENCE,
            decision="first",
            grader_profile_ref=GRADER,
            rubric_name="pairwise",
            rubric_version="1.0.0",
            presentation_order="ab",
            observed_at=AT,
        )

        bias = position_bias([verdict])

        assert bias.both_orders == 0
        # Unmeasured, not unbiased.
        assert bias.bias is None
        assert bias.interval is None

    def test_two_readings_in_the_same_order_are_refused(self) -> None:
        verdicts = [
            JudgeVerdict(
                verdict_id=f"v{index}",
                blinded_item_id="itm-00000000000a",
                label_type=LabelType.PAIRWISE_PREFERENCE,
                decision="first",
                grader_profile_ref=GRADER,
                rubric_name="pairwise",
                rubric_version="1.0.0",
                presentation_order="ab",
                observed_at=AT,
            )
            for index in (1, 2)
        ]

        with pytest.raises(ValueError, match="a repeat, not a second order"):
            position_bias(verdicts)

    def test_ties_are_counted_and_excluded_from_the_position_share(self) -> None:
        verdicts = [
            JudgeVerdict(
                verdict_id=f"v.{order}",
                blinded_item_id="itm-00000000000a",
                label_type=LabelType.PAIRWISE_PREFERENCE,
                decision="tie",
                grader_profile_ref=GRADER,
                rubric_name="pairwise",
                rubric_version="1.0.0",
                presentation_order=order,
                observed_at=AT,
            )
            for order in ("ab", "ba")
        ]

        bias = position_bias(verdicts)

        assert bias.ties == 2
        assert bias.first_position_wins == 0
        # A judge that ties everything has no measurable position bias,
        # which is a fact about the judge and not a clean bill of health.
        assert bias.first_position_rate == pytest.approx(0.0)


class TestIntegrityViolations:
    def test_an_unadjudicated_dispute_is_a_violation(self) -> None:
        def label(label_id: str, decision: str, who: str) -> CalibrationLabel:
            return CalibrationLabel(
                label_id=label_id,
                blinded_item_id="itm-00000000000a",
                label_type=LabelType.CLAIM_SUPPORT,
                decision=decision,
                confidence=Confidence.HIGH,
                rationale_ref=RATIONALE,
                annotator=Annotator(
                    annotator_id=who,
                    kind=AnnotatorKind.HUMAN_EXPERT,
                    guideline_revision="1.0.0",
                ),
                labeled_at=AT,
                guideline_ref=GUIDELINE,
            )

        item = LabelledItem(
            blinded_item_id="itm-00000000000a",
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(label("l1", "supported", "ann-a1f4"), label("l2", "unsupported", "ann-b2c7")),
        )

        findings = find_integrity_violations([item], ())

        assert [finding.violation_class for finding in findings] == [
            "unadjudicated_dispute_counted"
        ]

    def test_a_blinding_leak_is_a_violation_naming_the_terms(self) -> None:
        findings = find_integrity_violations(
            [], (), blinding_leaks={"itm-00000000000a": ["arm-c", "claude-opus-5"]}
        )

        assert findings[0].violation_class == "blinding_breach"
        assert "arm-c" in findings[0].detail

    def test_a_rate_reported_for_an_empty_slice_is_a_violation(self) -> None:
        coverage = (
            SliceCoverage(
                observation=SliceObservation(
                    slice_id="evidence-sparse", labelled=3, resolved=0, target=34, shortfall=34
                ),
                false_pass=rate_with_interval(1, 4),
            ),
        )

        findings = find_integrity_violations([], coverage)

        assert findings[0].violation_class == "slice_reported_without_items"

    def test_an_unknown_violation_class_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="is not an integrity class"):
            IntegrityFinding(
                violation_class="looked_a_bit_off", subject="x", detail="y"
            )

    def test_the_model_label_class_stays_in_the_vocabulary(self) -> None:
        """It cannot be produced today, and must stay nameable.

        `CalibrationLabel` refuses a model annotator at construction, so
        no scan can find one. The class remains declared because a future
        ingest path that reads labels from elsewhere will need to raise
        it, and a violation class invented at the moment it is first
        needed is one nobody wrote a response to.
        """
        assert "model_verdict_as_ground_truth" in INTEGRITY_VIOLATION_CLASSES


class TestSliceCoverage:
    def test_a_slice_with_no_resolved_item_is_unmeasured(self) -> None:
        observation = SliceObservation(
            slice_id="contradiction-present", labelled=2, resolved=0, target=34, shortfall=34
        )

        coverage = slice_coverage([observation], {})

        assert coverage[0].observation.unmeasured
        assert coverage[0].false_pass.denominator == 0
        assert coverage[0].false_pass.rate is None

    def test_a_slice_missing_from_the_mapping_is_reported_not_skipped(self) -> None:
        observations = [
            SliceObservation(
                slice_id="evidence-rich", labelled=5, resolved=5, target=34, shortfall=29
            ),
            SliceObservation(
                slice_id="evidence-sparse", labelled=0, resolved=0, target=34, shortfall=34
            ),
        ]

        coverage = slice_coverage(
            observations, {"evidence-rich": [("itm-00000000000a", False, True)]}
        )

        assert [entry.observation.slice_id for entry in coverage] == [
            "evidence-rich",
            "evidence-sparse",
        ]
        assert coverage[0].false_pass.numerator == 1
        assert coverage[1].false_pass.denominator == 0


def _report(**overrides: object) -> CalibrationReport:
    """A clean, measured report that PROMOTEs, before overrides."""
    base: dict[str, object] = {
        "set_id": "judge-calibration-v1",
        "set_revision": "1.0.0",
        "judge_rubric_name": "faithfulness",
        "judge_rubric_version": "1.0.0",
        "calibration_rubric_version": "1.0.0",
        "abstention_policy": AbstentionPolicy.EXCLUDED,
        "resolved_items": 400,
        "decided_items": 400,
        "raw_agreement": 0.93,
        "phi": 0.85,
        "judge_positive_rate": 0.51,
        "reference_positive_rate": 0.50,
        "false_pass_numerator": 2,
        "false_pass_denominator": 200,
        "false_pass_upper": 0.036,
        "false_fail_numerator": 4,
        "false_fail_denominator": 200,
        "false_fail_upper": 0.05,
        "abstention_numerator": 3,
        "abstention_denominator": 400,
        "position_bias": 0.01,
        "position_bias_interval": (0.48, 0.54),
        "position_bias_pairs": 120,
        "integrity": (),
        "unmeasured_slices": (),
        "small_sample_caveat": None,
        "basis": "measured",
    }
    base.update(overrides)
    return CalibrationReport(**base)  # type: ignore[arg-type]


class TestTheGateReachesAllThreeStates:
    def test_a_clean_measured_report_promotes(self) -> None:
        decision = decide(_report())

        assert decision.state == "PROMOTE"
        assert decision.blocking is False
        assert decision.exit_code == 0

    def test_an_integrity_violation_rolls_back_and_blocks_even_in_advisory_mode(self) -> None:
        decision = decide(
            _report(
                integrity=(
                    IntegrityFinding(
                        violation_class="blinding_breach",
                        subject="itm-00000000000a",
                        detail="the rendered judge input names arm-c",
                    ),
                )
            ),
            advisory=True,
        )

        assert decision.state == "ROLLBACK"
        assert decision.blocking is True
        assert decision.reasons[0].startswith("INTEGRITY VETO")

    def test_a_false_pass_rate_over_the_ceiling_rolls_back(self) -> None:
        decision = decide(
            _report(false_pass_numerator=40, false_pass_denominator=200, false_pass_upper=0.26)
        )

        assert decision.state == "ROLLBACK"
        assert any("above the" in reason for reason in decision.reasons)
        # Advisory by default, so the measured half reports without blocking.
        assert decision.blocking is False

    def test_a_measured_rollback_blocks_once_advisory_is_off(self) -> None:
        decision = decide(
            _report(false_pass_numerator=40, false_pass_denominator=200, false_pass_upper=0.26),
            advisory=False,
        )

        assert decision.state == "ROLLBACK"
        assert decision.blocking is True

    def test_phi_below_the_floor_rolls_back(self) -> None:
        decision = decide(_report(phi=0.2))

        assert decision.state == "ROLLBACK"
        assert any("below the declared floor" in reason for reason in decision.reasons)

    def test_a_position_bias_interval_entirely_outside_the_band_rolls_back(self) -> None:
        decision = decide(_report(position_bias=0.25, position_bias_interval=(0.68, 0.82)))

        assert decision.state == "ROLLBACK"
        assert any("prefers a position" in reason for reason in decision.reasons)

    def test_a_predicted_report_can_never_promote(self) -> None:
        decision = decide(_report(basis="hypothesis"))

        assert decision.state == "HOLD"
        assert any("predicted, not measured" in reason for reason in decision.reasons)

    def test_a_moved_rubric_version_holds(self) -> None:
        decision = decide(_report(judge_rubric_version="1.1.0"))

        assert decision.state == "HOLD"
        assert any("the judge moved" in reason for reason in decision.reasons)

    def test_too_few_resolved_items_holds(self) -> None:
        decision = decide(_report(resolved_items=40))

        assert decision.state == "HOLD"
        assert any("below the declared minimum" in reason for reason in decision.reasons)

    def test_an_unmeasured_slice_holds(self) -> None:
        decision = decide(_report(unmeasured_slices=("contradiction-present",)))

        assert decision.state == "HOLD"
        assert any("contradiction-present" in reason for reason in decision.reasons)

    def test_a_wide_false_pass_interval_holds_rather_than_promoting(self) -> None:
        decision = decide(_report(false_pass_upper=0.19))

        assert decision.state == "HOLD"
        assert any("more items or a lower rate" in reason for reason in decision.reasons)

    def test_an_undefined_phi_holds(self) -> None:
        decision = decide(_report(phi=None))

        assert decision.state == "HOLD"
        assert any("φ is undefined" in reason for reason in decision.reasons)

    def test_unmeasured_position_bias_holds_rather_than_reading_as_zero(self) -> None:
        decision = decide(_report(position_bias=None, position_bias_interval=None))

        assert decision.state == "HOLD"
        assert any("unmeasured is not zero" in reason for reason in decision.reasons)

    def test_no_reference_fail_item_holds(self) -> None:
        decision = decide(
            _report(false_pass_numerator=0, false_pass_denominator=0, false_pass_upper=None)
        )

        assert decision.state == "HOLD"
        assert any("no reference-fail item" in reason for reason in decision.reasons)


class TestTheGateMirrorsAdr0072:
    def test_the_decision_type_has_the_same_fields_as_the_safety_gate(self) -> None:
        """Two gates in one repository should answer in one vocabulary."""
        assert GateDecision._fields == safety_suite.GateDecision._fields

    def test_the_three_states_are_the_same_three(self) -> None:
        assert {"PROMOTE", "HOLD", "ROLLBACK"} == {
            decide(_report()).state,
            decide(_report(basis="hypothesis")).state,
            decide(_report(phi=0.2)).state,
        }

    def test_the_thresholds_are_not_an_approval(self) -> None:
        assert DEFAULT_THRESHOLDS.approved_by_owner is False

        with pytest.raises(ValidationError, match="approval ledger"):
            UsabilityThresholds(
                false_pass_ceiling=0.1,
                phi_floor=0.6,
                position_bias_tolerance=0.05,
                minimum_resolved_items=127,
                approved_by_owner=True,
            )


class TestTheRenderedReportCannotQuoteRawAgreementAlone:
    def test_raw_agreement_shares_a_line_with_phi_and_both_positive_rates(self) -> None:
        """docs/eval.md's rule, enforced by the renderer's line breaks.

        Raw agreement overstates chance-corrected agreement by 33-41
        points, so there is no line in this output a reader can copy that
        carries it without the numbers that qualify it.
        """
        lines = report_lines(_report(), decide(_report()))
        carrying = [line for line in lines if "raw agreement" in line]

        assert len(carrying) == 1
        line = carrying[0]
        assert "φ" in line
        assert "judge positive" in line
        assert "reference positive" in line

    def test_the_rendered_report_names_its_abstention_policy(self) -> None:
        lines = report_lines(_report(), decide(_report()))

        assert any("abstentions" in line and "excluded" in line for line in lines)

    def test_every_rate_is_rendered_with_its_denominator(self) -> None:
        lines = report_lines(_report(), decide(_report()))

        assert any("false pass        2/200" in line for line in lines)
        assert any("false fail        4/200" in line for line in lines)


class TestBuildReportOnTheWorkedSet:
    def test_the_worked_set_builds_a_report_that_holds(self) -> None:
        worked = load_labelled_set()

        report = build_report(
            set_id="worked-example",
            set_revision="1.0.0",
            judge_rubric_name="faithfulness",
            judge_rubric_version="1.0.0",
            calibration_rubric_version="1.0.0",
            items=worked.items,
            verdicts=worked.judge_verdicts,
        )

        assert report.decided_items == 10
        assert report.false_pass_numerator == 2
        assert report.basis == "hypothesis"
        assert decide(report).state == "HOLD"

    def test_the_report_carries_no_integrity_violation_on_a_clean_set(self) -> None:
        worked = load_labelled_set()

        report = build_report(
            set_id="worked-example",
            set_revision="1.0.0",
            judge_rubric_name="faithfulness",
            judge_rubric_version="1.0.0",
            calibration_rubric_version="1.0.0",
            items=worked.items,
            verdicts=worked.judge_verdicts,
        )

        assert report.integrity == ()
        assert report.resolved_items == 11


class TestTheRemainingMetricPaths:
    def test_an_item_neither_side_decided_is_counted_as_unmatched(self) -> None:
        counts = confusion([("itm-00000000000a", None, None)])

        assert counts.unmatched == 1
        assert counts.total == 1
        assert counts.decided == 0

    def test_the_rate_helper_reports_absence_rather_than_zero(self) -> None:
        empty = rate_with_interval(0, 0)

        assert empty.rate is None
        assert empty.interval is None

    def test_an_empty_calibration_report_renders_without_crashing(self) -> None:
        report = build_report(
            set_id="empty",
            set_revision="1.0.0",
            judge_rubric_name="faithfulness",
            judge_rubric_version="1.0.0",
            calibration_rubric_version="1.0.0",
            items=(),
            verdicts=(),
        )
        lines = report_lines(report, decide(report))

        assert any("n/a" in line for line in lines)

    def test_an_unmeasured_slice_reaches_the_rendered_report(self) -> None:
        report = _report(
            unmeasured_slices=("contradiction-present",), basis="hypothesis"
        )
        lines = report_lines(report, decide(report))

        assert any("unmeasured slices contradiction-present" in line for line in lines)

    def test_the_caveat_reaches_the_rendered_report(self) -> None:
        report = _report(small_sample_caveat="approximate at n=10")
        lines = report_lines(report, decide(report))

        assert any("approximate at n=10" in line for line in lines)

    def test_an_observed_bias_over_the_band_with_a_straddling_interval_holds(self) -> None:
        decision = decide(_report(position_bias=0.08, position_bias_interval=(0.52, 0.64)))

        assert decision.state == "HOLD"
        assert any("does not exclude the band" in reason for reason in decision.reasons)

    def test_a_second_position_preference_is_caught_by_the_same_statistic(self) -> None:
        decision = decide(_report(position_bias=-0.25, position_bias_interval=(0.18, 0.32)))

        assert decision.state == "ROLLBACK"
        assert any("prefers a position" in reason for reason in decision.reasons)

    def test_the_integrity_veto_lists_every_finding_it_found(self) -> None:
        findings = (
            IntegrityFinding(
                violation_class="blinding_breach",
                subject="itm-00000000000a",
                detail="names arm-c",
            ),
            IntegrityFinding(
                violation_class="unadjudicated_dispute_counted",
                subject="itm-00000000000b",
                detail="disputed and counted",
            ),
        )

        decision = decide(_report(integrity=findings))

        assert decision.state == "ROLLBACK"
        assert any("itm-00000000000a" in reason for reason in decision.reasons)
        assert any("itm-00000000000b" in reason for reason in decision.reasons)

    def test_a_clean_set_with_no_leaks_reports_no_findings(self) -> None:
        assert find_integrity_violations([], (), blinding_leaks={"itm-00000000000a": []}) == ()

    def test_slice_coverage_over_an_empty_observation_list_is_empty(self) -> None:
        assert slice_coverage([], {}) == ()
