"""Unit tests for `src/calibration/labels.py` — P0-WO10.

The schema half of the work order's acceptance criteria: every schema
validates locally, digests are stable across key order, model outputs are
never ground truth, and human labels preserve individual decisions and
adjudication lineage.

The rules under test are refusals, so most of these assert that something
*cannot* be expressed. A schema that merely documents "do not do this" is
a comment; the tests below are what make it a boundary.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.calibration.labels import (
    GROUND_TRUTH_ANNOTATOR_KINDS,
    HUMAN_ANNOTATOR_KINDS,
    AdjudicationRecord,
    AdjudicationRule,
    Annotator,
    AnnotatorKind,
    CalibrationLabel,
    Confidence,
    JudgeVerdict,
    LabelledItem,
    LabelType,
    binary_outcome,
    campaign_eligible,
    decision_vocabulary,
    human_annotator_ids,
    registry_label_records,
    resolved_pairs,
)
from src.contracts.kernel import ImmutableObjectRef, sha256_digest

pytestmark = pytest.mark.unit

AT = "2026-09-05T00:00:00Z"
ITEM = "itm-0123456789ab"

RATIONALE = ImmutableObjectRef(
    kind="calibration_rationale",
    id="r1",
    revision="1.0.0",
    digest=sha256_digest({"text": "because the source is silent"}),
)
GUIDELINE = ImmutableObjectRef(
    kind="calibration_guideline",
    id="guide",
    revision="1.0.0",
    digest=sha256_digest({"guide": "v1"}),
)
GRADER = ImmutableObjectRef(
    kind="grader_profile",
    id="judge-under-calibration",
    revision="1.0.0",
    digest=sha256_digest({"profile": "v1"}),
)
TARGET = ImmutableObjectRef(
    kind="task_case",
    id="polish-scaling-emergent",
    revision="1.0.0",
    digest=sha256_digest({"case": "v1"}),
)


def annotator(
    suffix: str, kind: AnnotatorKind = AnnotatorKind.HUMAN_EXPERT
) -> Annotator:
    return Annotator(
        annotator_id=f"ann-{suffix}", kind=kind, guideline_revision="1.0.0"
    )


def label(
    label_id: str,
    decision: str,
    *,
    who: Annotator | None = None,
    label_type: LabelType = LabelType.CLAIM_SUPPORT,
    item: str = ITEM,
    seconds: int | None = 90,
) -> CalibrationLabel:
    return CalibrationLabel(
        label_id=label_id,
        blinded_item_id=item,
        label_type=label_type,
        decision=decision,
        confidence=Confidence.HIGH,
        rationale_ref=RATIONALE,
        annotator=who or annotator("a1f4"),
        labeled_at=AT,
        guideline_ref=GUIDELINE,
        time_spent_seconds=seconds,
    )


class TestAModelCannotProduceALabel:
    """The work order's sharpest rule, in the place it cannot be skipped."""

    def test_the_label_schema_refuses_an_annotator_of_kind_model(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            label("l1", "supported", who=annotator("m0de", AnnotatorKind.MODEL))

        assert "instrument reading" in str(excinfo.value)

    def test_model_is_in_the_vocabulary_so_it_can_be_named_and_refused(self) -> None:
        # A vocabulary that omitted `model` would leave "a model wrote
        # this" expressible as a human kind with a machine behind it.
        assert AnnotatorKind.MODEL not in GROUND_TRUTH_ANNOTATOR_KINDS
        assert AnnotatorKind.MODEL not in HUMAN_ANNOTATOR_KINDS
        assert AnnotatorKind("model") is AnnotatorKind.MODEL

    def test_a_judge_verdict_carries_an_instrument_not_an_annotator(self) -> None:
        verdict = JudgeVerdict(
            verdict_id="v1",
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            decision="supported",
            grader_profile_ref=GRADER,
            rubric_name="faithfulness",
            rubric_version="1.0.0",
            observed_at=AT,
        )

        assert "annotator" not in verdict.model_dump()
        assert verdict.basis == "hypothesis"

    def test_a_synthetic_construction_fact_is_ground_truth_but_not_a_person(self) -> None:
        who = annotator("w10author", AnnotatorKind.SYNTHETIC_CONSTRUCTION)

        assert who.is_synthetic
        assert not who.is_human
        assert label("l1", "supported", who=who).annotator.kind is (
            AnnotatorKind.SYNTHETIC_CONSTRUCTION
        )

    def test_a_synthetic_item_is_disqualified_from_the_campaign_set(self) -> None:
        synthetic = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(
                label(
                    "l1",
                    "supported",
                    who=annotator("w10author", AnnotatorKind.SYNTHETIC_CONSTRUCTION),
                ),
            ),
        )

        assert campaign_eligible([synthetic]) == (ITEM,)


class TestTheDecisionVocabulary:
    @pytest.mark.parametrize(
        ("label_type", "expected"),
        [
            (
                LabelType.CLAIM_SUPPORT,
                ("supported", "unsupported", "contradicted", "not_verifiable", "abstain"),
            ),
            (
                LabelType.CITATION_CORRECTNESS,
                ("correct", "wrong_source", "unresolvable", "abstain"),
            ),
            (LabelType.RUBRIC_COVERAGE, ("covered", "partial", "not_covered", "abstain")),
            (LabelType.PAIRWISE_PREFERENCE, ("first", "second", "tie", "abstain")),
        ],
    )
    def test_each_type_declares_its_own_values(
        self, label_type: LabelType, expected: tuple[str, ...]
    ) -> None:
        assert decision_vocabulary(label_type) == expected

    def test_a_decision_from_another_type_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="is not a rubric_coverage decision"):
            label("l1", "supported", label_type=LabelType.RUBRIC_COVERAGE)

    @pytest.mark.parametrize(
        ("decision", "outcome"),
        [
            ("supported", True),
            ("covered", True),
            ("correct", True),
            ("unsupported", False),
            ("contradicted", False),
            ("wrong_source", False),
            ("partial", False),
            # The three that assert nothing. 07 §7: abstained and
            # unverifiable claims stay visible and never become passes.
            ("abstain", None),
            ("not_verifiable", None),
            ("tie", None),
            # A position is not a success.
            ("first", None),
            ("second", None),
        ],
    )
    def test_the_binary_projection_keeps_three_answers(
        self, decision: str, outcome: bool | None
    ) -> None:
        assert binary_outcome(decision) is outcome

    def test_an_unknown_value_raises_rather_than_projecting_to_none(self) -> None:
        with pytest.raises(ValueError, match="unknown decision value"):
            binary_outcome("probably")


class TestAdjudicationPreservesLineage:
    def test_every_individual_decision_survives_in_the_record(self) -> None:
        decisions = (
            label("l1", "unsupported", who=annotator("a1f4")),
            label("l2", "unsupported", who=annotator("b2c7", AnnotatorKind.HUMAN_REVIEWER)),
            label("l3", "supported", who=annotator("c3d9", AnnotatorKind.HUMAN_REVIEWER)),
        )
        record = AdjudicationRecord(
            adjudication_id="adj1",
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            decisions=decisions,
            adjudicated_decision="unsupported",
            rule=AdjudicationRule.MAJORITY,
            adjudicator=annotator("d4e2"),
            adjudicated_at=AT,
        )

        assert [entry.decision for entry in record.decisions] == [
            "unsupported",
            "unsupported",
            "supported",
        ]
        assert record.adjudicated_decision == "unsupported"
        assert not record.unanimous

    def test_a_majority_that_is_not_a_majority_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="not a strict majority"):
            AdjudicationRecord(
                adjudication_id="adj1",
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                decisions=(
                    label("l1", "supported", who=annotator("a1f4")),
                    label("l2", "unsupported", who=annotator("b2c7")),
                ),
                adjudicated_decision="supported",
                rule=AdjudicationRule.MAJORITY,
                adjudicator=annotator("d4e2"),
                adjudicated_at=AT,
            )

    def test_a_unanimous_outcome_must_be_the_value_everyone_chose(self) -> None:
        with pytest.raises(ValidationError, match="value everyone chose"):
            AdjudicationRecord(
                adjudication_id="adj1",
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                decisions=(
                    label("l1", "supported", who=annotator("a1f4")),
                    label("l2", "supported", who=annotator("b2c7")),
                ),
                adjudicated_decision="unsupported",
                rule=AdjudicationRule.UNANIMOUS,
                adjudicator=annotator("d4e2"),
                adjudicated_at=AT,
            )

    def test_an_override_may_leave_the_observed_values_but_needs_an_expert_and_a_reason(
        self,
    ) -> None:
        decisions = (
            label("l1", "supported", who=annotator("a1f4")),
            label("l2", "unsupported", who=annotator("b2c7")),
        )
        record = AdjudicationRecord(
            adjudication_id="adj1",
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            decisions=decisions,
            adjudicated_decision="contradicted",
            rule=AdjudicationRule.EXPERT_OVERRIDE,
            adjudicator=annotator("d4e2"),
            adjudicated_at=AT,
            rationale_ref=RATIONALE,
        )

        assert record.adjudicated_decision == "contradicted"

        with pytest.raises(ValidationError, match="requires a written rationale"):
            AdjudicationRecord(
                adjudication_id="adj1",
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                decisions=decisions,
                adjudicated_decision="contradicted",
                rule=AdjudicationRule.EXPERT_OVERRIDE,
                adjudicator=annotator("d4e2"),
                adjudicated_at=AT,
                rationale_ref=None,
            )

    def test_only_a_person_may_adjudicate(self) -> None:
        with pytest.raises(ValidationError, match="only a person may adjudicate"):
            AdjudicationRecord(
                adjudication_id="adj1",
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                decisions=(
                    label("l1", "supported", who=annotator("a1f4")),
                    label("l2", "unsupported", who=annotator("b2c7")),
                ),
                adjudicated_decision="supported",
                rule=AdjudicationRule.MAJORITY,
                adjudicator=annotator("c3d9", AnnotatorKind.DETERMINISTIC_CHECK),
                adjudicated_at=AT,
            )

    def test_an_unresolved_escalation_carries_no_outcome(self) -> None:
        record = AdjudicationRecord(
            adjudication_id="adj1",
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            decisions=(
                label("l1", "supported", who=annotator("a1f4")),
                label("l2", "unsupported", who=annotator("b2c7")),
            ),
            adjudicated_decision=None,
            rule=AdjudicationRule.UNRESOLVED,
            adjudicator=annotator("d4e2"),
            adjudicated_at=AT,
            rationale_ref=RATIONALE,
        )

        assert record.adjudicated_decision is None

    def test_one_annotator_contributes_at_most_one_decision(self) -> None:
        same = annotator("a1f4")
        with pytest.raises(ValidationError, match="at most one decision"):
            AdjudicationRecord(
                adjudication_id="adj1",
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                decisions=(
                    label("l1", "supported", who=same),
                    label("l2", "unsupported", who=same),
                ),
                adjudicated_decision="supported",
                rule=AdjudicationRule.EXPERT_OVERRIDE,
                adjudicator=annotator("d4e2"),
                adjudicated_at=AT,
                rationale_ref=RATIONALE,
            )

    def test_a_single_decision_is_not_a_disagreement(self) -> None:
        with pytest.raises(ValidationError, match="not a disagreement"):
            AdjudicationRecord(
                adjudication_id="adj1",
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                decisions=(label("l1", "supported"),),
                adjudicated_decision="supported",
                rule=AdjudicationRule.UNANIMOUS,
                adjudicator=annotator("d4e2"),
                adjudicated_at=AT,
            )


class TestAnUnresolvedDisagreementHasNoValue:
    """The refusal that stops a consensus overwriting its own inputs."""

    def test_two_disagreeing_labels_with_no_adjudication_resolve_to_nothing(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(
                label("l1", "supported", who=annotator("a1f4")),
                label("l2", "unsupported", who=annotator("b2c7")),
            ),
        )

        assert item.agreement_state == "disputed"
        assert item.resolved_decision is None
        assert item.resolved_outcome is None

    def test_two_agreeing_labels_resolve_without_an_adjudicator(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(
                label("l1", "supported", who=annotator("a1f4")),
                label("l2", "supported", who=annotator("b2c7")),
            ),
        )

        assert item.agreement_state == "agreed"
        assert item.resolved_decision == "supported"

    def test_one_label_is_unreviewed_rather_than_agreed(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(label("l1", "supported"),),
        )

        assert item.agreement_state == "unreviewed"
        assert item.resolved_decision is None

    def test_an_adjudication_must_preserve_exactly_this_item_s_decisions(self) -> None:
        kept = label("l1", "supported", who=annotator("a1f4"))
        dropped = label("l2", "unsupported", who=annotator("b2c7"))
        record = AdjudicationRecord(
            adjudication_id="adj1",
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            decisions=(kept, dropped),
            adjudicated_decision="supported",
            rule=AdjudicationRule.EXPERT_OVERRIDE,
            adjudicator=annotator("d4e2"),
            adjudicated_at=AT,
            rationale_ref=RATIONALE,
        )

        with pytest.raises(ValidationError, match="preserve exactly this item"):
            LabelledItem(
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                labels=(kept,),
                adjudication=record,
            )

    def test_human_seconds_is_none_when_any_label_did_not_measure_it(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(
                label("l1", "supported", who=annotator("a1f4"), seconds=60),
                label("l2", "supported", who=annotator("b2c7"), seconds=None),
            ),
        )

        assert item.human_seconds is None

    def test_human_seconds_sums_when_every_label_measured_it(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(
                label("l1", "supported", who=annotator("a1f4"), seconds=60),
                label("l2", "supported", who=annotator("b2c7"), seconds=45),
            ),
        )

        assert item.human_seconds == 105


class TestProjectionIntoTheRegistry:
    def test_every_decision_becomes_its_own_registry_record_plus_the_outcome(self) -> None:
        decisions = (
            label("l1", "unsupported", who=annotator("a1f4")),
            label("l2", "unsupported", who=annotator("b2c7", AnnotatorKind.HUMAN_REVIEWER)),
            label("l3", "supported", who=annotator("c3d9", AnnotatorKind.HUMAN_REVIEWER)),
        )
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=decisions,
            adjudication=AdjudicationRecord(
                adjudication_id="adj1",
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                decisions=decisions,
                adjudicated_decision="unsupported",
                rule=AdjudicationRule.MAJORITY,
                adjudicator=annotator("d4e2"),
                adjudicated_at=AT,
            ),
        )
        values = {
            decision: ImmutableObjectRef(
                kind="expected_label",
                id=f"claim-support-{decision.replace('_', '-')}",
                revision="1.0.0",
                digest=sha256_digest({"decision": decision}),
            )
            for decision in ("supported", "unsupported")
        }

        records = registry_label_records(
            item, target_ref=TARGET, value_refs=values, guideline_ref=GUIDELINE
        )

        assert [record.label_id for record in records] == ["l1", "l2", "l3", "adj1"]
        # The adjudicated record adds; it does not supersede. Pointing
        # supersession at the decisions would encode the overwrite RFC 11
        # §9.2 forbids.
        assert all(record.supersedes_ref is None for record in records)
        assert records[-1].agreement_state == "adjudicated"
        assert records[-1].value_ref == values["unsupported"]
        assert records[2].value_ref == values["supported"]

    def test_the_annotator_kind_survives_into_the_registry_label_type(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(label("l1", "supported"),),
        )
        values = {
            "supported": ImmutableObjectRef(
                kind="expected_label",
                id="claim-support-supported",
                revision="1.0.0",
                digest=sha256_digest({"decision": "supported"}),
            )
        }

        records = registry_label_records(
            item, target_ref=TARGET, value_refs=values, guideline_ref=GUIDELINE
        )

        assert records[0].label_type == "claim_support.human_expert"
        assert records[0].agreement_state == "unreviewed"


class TestPairingAndDigests:
    def test_an_item_only_one_side_decided_is_counted_not_intersected_away(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(
                label("l1", "supported", who=annotator("a1f4")),
                label("l2", "supported", who=annotator("b2c7")),
            ),
        )
        other = "itm-ffffffffffff"
        verdict = JudgeVerdict(
            verdict_id="v1",
            blinded_item_id=other,
            label_type=LabelType.CLAIM_SUPPORT,
            decision="supported",
            grader_profile_ref=GRADER,
            rubric_name="faithfulness",
            rubric_version="1.0.0",
            observed_at=AT,
        )

        assert resolved_pairs([item], [verdict]) == (
            (ITEM, True, None),
            (other, None, True),
        )

    def test_a_pairwise_verdict_is_excluded_from_the_pass_fail_pairing(self) -> None:
        verdict = JudgeVerdict(
            verdict_id="v1",
            blinded_item_id=ITEM,
            label_type=LabelType.PAIRWISE_PREFERENCE,
            decision="first",
            grader_profile_ref=GRADER,
            rubric_name="faithfulness",
            rubric_version="1.0.0",
            presentation_order="ab",
            observed_at=AT,
        )

        assert resolved_pairs([], [verdict]) == ()

    def test_a_pairwise_verdict_without_an_order_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="order it was shown in"):
            JudgeVerdict(
                verdict_id="v1",
                blinded_item_id=ITEM,
                label_type=LabelType.PAIRWISE_PREFERENCE,
                decision="first",
                grader_profile_ref=GRADER,
                rubric_name="faithfulness",
                rubric_version="1.0.0",
                observed_at=AT,
            )

    def test_two_labelled_items_for_one_blinded_id_is_an_error(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(label("l1", "supported"),),
        )

        with pytest.raises(ValueError, match="two labelled items"):
            resolved_pairs([item, item], [])

    def test_a_label_digest_does_not_move_with_key_order(self) -> None:
        """RFC 8785 canonicalisation, exercised on this package's models.

        The property the whole registry rests on: two byte-different JSON
        documents that mean the same thing hash the same.
        """
        one = label("l1", "supported")
        payload = one.model_dump(mode="json")
        shuffled = dict(reversed(list(payload.items())))
        round_tripped = CalibrationLabel.model_validate_json(json.dumps(shuffled))

        assert list(payload) != list(shuffled)
        assert sha256_digest(one) == sha256_digest(round_tripped)

    def test_human_annotator_ids_exclude_synthetic_and_deterministic_kinds(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=(
                label("l1", "supported", who=annotator("a1f4")),
                label(
                    "l2",
                    "supported",
                    who=annotator("z9z9", AnnotatorKind.DETERMINISTIC_CHECK),
                ),
            ),
        )

        assert human_annotator_ids([item]) == ("ann-a1f4",)


class TestTheRemainingRefusals:
    """One test per validator branch the earlier classes did not reach.

    Grouped rather than scattered because each is the same kind of claim:
    a shape that would let a label, an adjudication or an item mean two
    things at once is refused at construction, not caught downstream.
    """

    def test_a_label_projects_itself_onto_the_pass_fail_axis(self) -> None:
        assert label("l1", "supported").outcome is True
        assert label("l1", "contradicted").outcome is False
        assert label("l1", "abstain").outcome is None

    def test_a_verdict_projects_itself_too(self) -> None:
        verdict = JudgeVerdict(
            verdict_id="v1",
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            decision="unsupported",
            grader_profile_ref=GRADER,
            rubric_name="faithfulness",
            rubric_version="1.0.0",
            observed_at=AT,
        )

        assert verdict.outcome is False

    def test_a_verdict_decision_outside_its_vocabulary_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="is not a claim_support decision"):
            JudgeVerdict(
                verdict_id="v1",
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                decision="covered",
                grader_profile_ref=GRADER,
                rubric_name="faithfulness",
                rubric_version="1.0.0",
                observed_at=AT,
            )

    def _decisions(self) -> tuple[CalibrationLabel, CalibrationLabel]:
        return (
            label("l1", "supported", who=annotator("a1f4")),
            label("l2", "unsupported", who=annotator("b2c7")),
        )

    def _adjudication(self, **overrides: object) -> AdjudicationRecord:
        base: dict[str, object] = {
            "adjudication_id": "adj1",
            "blinded_item_id": ITEM,
            "label_type": LabelType.CLAIM_SUPPORT,
            "decisions": self._decisions(),
            "adjudicated_decision": "supported",
            "rule": AdjudicationRule.EXPERT_OVERRIDE,
            "adjudicator": annotator("d4e2"),
            "adjudicated_at": AT,
            "rationale_ref": RATIONALE,
        }
        base.update(overrides)
        return AdjudicationRecord(**base)  # type: ignore[arg-type]

    def test_a_preserved_decision_about_another_item_is_refused(self) -> None:
        other = (
            label("l1", "supported", who=annotator("a1f4"), item="itm-ffffffffffff"),
            label("l2", "unsupported", who=annotator("b2c7"), item="itm-ffffffffffff"),
        )

        with pytest.raises(ValidationError, match="must be about this item"):
            self._adjudication(decisions=other)

    def test_a_preserved_decision_of_another_type_is_refused(self) -> None:
        mixed = (
            label("l1", "supported", who=annotator("a1f4")),
            label(
                "l2",
                "covered",
                who=annotator("b2c7"),
                label_type=LabelType.RUBRIC_COVERAGE,
            ),
        )

        with pytest.raises(ValidationError, match="must answer this label type"):
            self._adjudication(decisions=mixed)

    def test_two_decisions_sharing_a_label_id_are_refused(self) -> None:
        duplicated = (
            label("l1", "supported", who=annotator("a1f4")),
            label("l1", "unsupported", who=annotator("b2c7")),
        )

        with pytest.raises(ValidationError, match="must be distinct labels"):
            self._adjudication(decisions=duplicated)

    def test_an_unresolved_record_that_carries_an_outcome_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="has no outcome"):
            self._adjudication(rule=AdjudicationRule.UNRESOLVED)

    def test_a_resolved_rule_without_an_outcome_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="requires an outcome"):
            self._adjudication(adjudicated_decision=None)

    def test_an_outcome_outside_the_vocabulary_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="is not a claim_support decision"):
            self._adjudication(adjudicated_decision="covered")

    def test_a_guideline_rule_without_the_clause_it_applied_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="name the clause it applied"):
            self._adjudication(
                rule=AdjudicationRule.GUIDELINE_RULE,
                adjudicated_decision="unsupported",
                rationale_ref=None,
            )

    def test_a_guideline_rule_with_a_clause_is_accepted(self) -> None:
        record = self._adjudication(
            rule=AdjudicationRule.GUIDELINE_RULE, adjudicated_decision="unsupported"
        )

        assert record.rule is AdjudicationRule.GUIDELINE_RULE

    def test_an_override_by_a_reviewer_rather_than_an_expert_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="requires an expert adjudicator"):
            self._adjudication(
                adjudicator=annotator("e5f6", AnnotatorKind.HUMAN_REVIEWER)
            )

    def test_an_item_with_no_label_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="at least one decision"):
            LabelledItem(
                blinded_item_id=ITEM, label_type=LabelType.CLAIM_SUPPORT, labels=()
            )

    def test_a_label_about_another_item_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="every label must be about this item"):
            LabelledItem(
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                labels=(label("l1", "supported", item="itm-ffffffffffff"),),
            )

    def test_a_label_of_another_type_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="must answer this item's label type"):
            LabelledItem(
                blinded_item_id=ITEM,
                label_type=LabelType.RUBRIC_COVERAGE,
                labels=(label("l1", "supported"),),
            )

    def test_duplicate_label_ids_within_an_item_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="unique within an item"):
            LabelledItem(
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                labels=(
                    label("l1", "supported", who=annotator("a1f4")),
                    label("l1", "unsupported", who=annotator("b2c7")),
                ),
            )

    def test_duplicate_slice_tags_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="slice tags must be unique"):
            LabelledItem(
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                slice_tags=("evidence-rich", "evidence-rich"),
                labels=(label("l1", "supported"),),
            )

    def test_an_adjudication_about_another_item_is_refused(self) -> None:
        elsewhere = AdjudicationRecord(
            adjudication_id="adj1",
            blinded_item_id="itm-ffffffffffff",
            label_type=LabelType.CLAIM_SUPPORT,
            decisions=(
                label("l1", "supported", who=annotator("a1f4"), item="itm-ffffffffffff"),
                label("l2", "unsupported", who=annotator("b2c7"), item="itm-ffffffffffff"),
            ),
            adjudicated_decision="supported",
            rule=AdjudicationRule.EXPERT_OVERRIDE,
            adjudicator=annotator("d4e2"),
            adjudicated_at=AT,
            rationale_ref=RATIONALE,
        )

        with pytest.raises(ValidationError, match="adjudication must be about this item"):
            LabelledItem(
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                labels=self._decisions(),
                adjudication=elsewhere,
            )

    def test_an_adjudication_of_another_type_is_refused(self) -> None:
        coverage_labels = (
            label(
                "l1",
                "covered",
                who=annotator("a1f4"),
                label_type=LabelType.RUBRIC_COVERAGE,
            ),
            label(
                "l2",
                "not_covered",
                who=annotator("b2c7"),
                label_type=LabelType.RUBRIC_COVERAGE,
            ),
        )
        record = AdjudicationRecord(
            adjudication_id="adj1",
            blinded_item_id=ITEM,
            label_type=LabelType.RUBRIC_COVERAGE,
            decisions=coverage_labels,
            adjudicated_decision="covered",
            rule=AdjudicationRule.EXPERT_OVERRIDE,
            adjudicator=annotator("d4e2"),
            adjudicated_at=AT,
            rationale_ref=RATIONALE,
        )

        with pytest.raises(ValidationError, match="must answer this label type"):
            LabelledItem(
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                labels=self._decisions(),
                adjudication=record,
            )

    def test_an_escalated_item_reports_adjudicated_and_resolves_to_nothing(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=self._decisions(),
            adjudication=self._adjudication(
                rule=AdjudicationRule.UNRESOLVED, adjudicated_decision=None
            ),
        )

        assert item.agreement_state == "adjudicated"
        assert item.resolved_decision is None

    def test_an_escalated_item_produces_no_adjudicated_registry_record(self) -> None:
        item = LabelledItem(
            blinded_item_id=ITEM,
            label_type=LabelType.CLAIM_SUPPORT,
            labels=self._decisions(),
            adjudication=self._adjudication(
                rule=AdjudicationRule.UNRESOLVED, adjudicated_decision=None
            ),
        )
        values = {
            decision: ImmutableObjectRef(
                kind="expected_label",
                id=f"claim-support-{decision}",
                revision="1.0.0",
                digest=sha256_digest({"decision": decision}),
            )
            for decision in ("supported", "unsupported")
        }

        records = registry_label_records(
            item, target_ref=TARGET, value_refs=values, guideline_ref=GUIDELINE
        )

        # Two individual decisions, and no outcome record: there is no
        # outcome, and inventing one is the whole failure mode.
        assert [record.label_id for record in records] == ["l1", "l2"]
        assert {record.agreement_state for record in records} == {"adjudicated"}

    def test_two_judge_verdicts_for_one_blinded_id_is_an_error(self) -> None:
        verdicts = [
            JudgeVerdict(
                verdict_id=f"v{index}",
                blinded_item_id=ITEM,
                label_type=LabelType.CLAIM_SUPPORT,
                decision="supported",
                grader_profile_ref=GRADER,
                rubric_name="faithfulness",
                rubric_version="1.0.0",
                observed_at=AT,
            )
            for index in (1, 2)
        ]

        with pytest.raises(ValueError, match="two judge verdicts"):
            resolved_pairs([], verdicts)
