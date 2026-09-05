"""Unit tests for `src/calibration/fixtures.py` and the authored corpus.

12 §16's acceptance criteria, in the place they can be checked: all
schemas and synthetic fixtures validate locally, model outputs are never
called ground truth, and no real judge call has started.

The last one is the interesting test. "No judge has been run" is a claim
about the world, and the only mechanical form of it available inside a
repository is: every checked-in verdict declares itself a prediction, and
the loader refuses one that does not.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.calibration.fixtures import (
    ADVERSARIAL_PATH,
    FIXTURE_ANNOTATOR,
    FIXTURE_ROOT,
    LABELLED_SET_PATH,
    PAIRWISE_PATH,
    CalibrationCase,
    Family,
    Outcome,
    Stratum,
    as_labelled_items,
    as_predicted_pairwise_verdicts,
    as_predicted_verdicts,
    classify_outcome,
    load_case_file,
    load_cases,
    load_labelled_set,
    load_pairwise,
    missing_families,
)
from src.calibration.labels import (
    AnnotatorKind,
    LabelType,
    campaign_eligible,
    human_annotator_ids,
)
from src.calibration.sampling import FAILURE_CLASSES, TASK_SLICES
from src.contracts.kernel import ImmutableObjectRef, sha256_digest

pytestmark = pytest.mark.unit

REF = ImmutableObjectRef(
    kind="calibration_rationale",
    id="r1",
    revision="1.0.0",
    digest=sha256_digest({"text": "x"}),
)
GRADER = ImmutableObjectRef(
    kind="grader_profile",
    id="judge-under-calibration",
    revision="1.0.0",
    digest=sha256_digest({"profile": "v1"}),
)
AT = "2026-09-05T00:00:00Z"


class TestTheCorpusCoversWhatTheWorkOrderAsksFor:
    def test_every_required_family_is_present(self) -> None:
        cases = load_cases()

        assert missing_families(cases) == ()
        assert {case.family for case in cases} == set(Family)

    def test_the_six_families_are_03_section_7_5s_plus_12_section_16s(self) -> None:
        assert {family.value for family in Family} == {
            "unsupported_polish",
            "verbosity",
            "citation_swap",
            "injected_source_instructions",
            "contradiction",
            "honest_abstention",
        }

    def test_the_corpus_reaches_all_four_confusion_cells(self) -> None:
        """A corpus of only false passes cannot tell a bad judge from a
        judge that says 'unsupported' to everything."""
        counts = Counter(case.expected_outcome for case in load_cases())

        assert counts[Outcome.TRUE_PASS] > 0
        assert counts[Outcome.FALSE_PASS] > 0
        assert counts[Outcome.TRUE_FAIL] > 0
        assert counts[Outcome.FALSE_FAIL] > 0

    def test_three_label_types_are_exercised(self) -> None:
        types = {case.label_type for case in load_cases()}

        assert types == {
            LabelType.CLAIM_SUPPORT,
            LabelType.CITATION_CORRECTNESS,
            LabelType.RUBRIC_COVERAGE,
        }

    def test_the_pairwise_file_carries_both_orders_for_every_pair(self) -> None:
        pairs = load_pairwise()

        assert len(pairs) == 6
        for pair in pairs:
            assert pair.expected_ab_verdict
            assert pair.expected_ba_verdict

    def test_the_pairwise_corpus_contains_both_consistent_and_inconsistent_pairs(
        self,
    ) -> None:
        """A corpus where the predicted judge is unbiased could not tell a
        working position-bias test from one that always returns zero."""
        pairs = load_pairwise()
        consistent = [pair for pair in pairs if pair.position_consistent]

        assert consistent
        assert len(consistent) < len(pairs)


class TestNoJudgeHasBeenRun:
    def test_every_single_item_verdict_declares_itself_a_prediction(self) -> None:
        assert all(case.verdict_basis == "hypothesis" for case in load_cases())

    def test_every_pairwise_verdict_declares_itself_a_prediction(self) -> None:
        assert all(case.verdict_basis == "hypothesis" for case in load_pairwise())

    def test_a_case_claiming_a_measured_verdict_is_refused(self, tmp_path: Path) -> None:
        payload = json.loads(ADVERSARIAL_PATH.read_text(encoding="utf-8"))
        payload["cases"][0]["verdict_basis"] = "measured"
        edited = tmp_path / "adversarial_cases.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError):
            load_case_file(edited)

    def test_the_worked_set_verdicts_are_predictions_too(self) -> None:
        worked = load_labelled_set()

        assert all(verdict.basis == "hypothesis" for verdict in worked.judge_verdicts)

    def test_the_predicted_verdicts_this_module_builds_carry_the_hypothesis_basis(
        self,
    ) -> None:
        verdicts = as_predicted_verdicts(
            load_cases()[:2],
            grader_profile_ref=GRADER,
            rubric_name="faithfulness",
            rubric_version="1.0.0",
            observed_at=AT,
        )

        assert [verdict.basis for verdict in verdicts] == ["hypothesis", "hypothesis"]


class TestTheExpectedOutcomeCannotLie:
    def test_every_case_s_outcome_is_derived_from_its_two_decisions(self) -> None:
        for case in load_cases():
            assert case.expected_outcome is classify_outcome(
                case.expected_reference_decision, case.expected_judge_verdict
            )

    def test_a_case_claiming_the_wrong_cell_is_refused(self, tmp_path: Path) -> None:
        payload = json.loads(ADVERSARIAL_PATH.read_text(encoding="utf-8"))
        target = next(
            case for case in payload["cases"] if case["expected_outcome"] == "false_pass"
        )
        target["expected_outcome"] = "true_pass"
        edited = tmp_path / "adversarial_cases.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="classifies as"):
            load_case_file(edited)

    @pytest.mark.parametrize(
        ("reference", "judged", "expected"),
        [
            ("supported", "supported", Outcome.TRUE_PASS),
            ("unsupported", "supported", Outcome.FALSE_PASS),
            ("contradicted", "unsupported", Outcome.TRUE_FAIL),
            ("supported", "unsupported", Outcome.FALSE_FAIL),
            ("supported", "abstain", Outcome.JUDGE_ABSTAINED),
            ("not_verifiable", "supported", Outcome.REFERENCE_UNRESOLVED),
            ("covered", "not_covered", Outcome.FALSE_FAIL),
            ("wrong_source", "correct", Outcome.FALSE_PASS),
        ],
    )
    def test_the_classifier_covers_every_cell_and_both_non_cells(
        self, reference: str, judged: str, expected: Outcome
    ) -> None:
        assert classify_outcome(reference, judged) is expected


class TestSchemaRefusals:
    def test_a_decision_outside_the_label_type_s_vocabulary_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="is not a claim_support decision"):
            CalibrationCase(
                case_id="bad-case",
                family=Family.VERBOSITY,
                label_type=LabelType.CLAIM_SUPPORT,
                slice_tags=("evidence-rich",),
                material={"report_excerpt": "x"},  # type: ignore[arg-type]
                expected_reference_decision="covered",
                expected_judge_verdict="supported",
                expected_outcome=Outcome.TRUE_PASS,
                why="y",
            )

    def test_an_undeclared_slice_tag_is_refused(self, tmp_path: Path) -> None:
        payload = json.loads(ADVERSARIAL_PATH.read_text(encoding="utf-8"))
        payload["cases"][0]["slice_tags"].append("a-slice-nobody-declared")
        edited = tmp_path / "adversarial_cases.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="undeclared slice tags"):
            load_case_file(edited)

    def test_every_tag_in_the_corpus_is_a_declared_slice_or_failure_class(self) -> None:
        declared = {spec.slice_id for spec in TASK_SLICES} | set(FAILURE_CLASSES)
        used = {tag for case in load_cases() for tag in case.slice_tags}

        assert used <= declared

    def test_a_pairwise_case_in_the_single_item_file_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="belongs in the pairwise fixture file"):
            CalibrationCase(
                case_id="bad-case",
                family=Family.VERBOSITY,
                label_type=LabelType.PAIRWISE_PREFERENCE,
                slice_tags=(),
                material={"report_excerpt": "x"},  # type: ignore[arg-type]
                expected_reference_decision="first",
                expected_judge_verdict="first",
                expected_outcome=Outcome.REFERENCE_UNRESOLVED,
                why="y",
            )

    def test_duplicate_case_ids_are_refused(self, tmp_path: Path) -> None:
        payload = json.loads(ADVERSARIAL_PATH.read_text(encoding="utf-8"))
        payload["cases"].append(payload["cases"][0])
        edited = tmp_path / "adversarial_cases.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="case ids must be unique"):
            load_case_file(edited)


class TestTheStressSetIsNotACalibrationSet:
    def test_both_authored_files_declare_the_adversarial_stratum(self) -> None:
        assert load_case_file(ADVERSARIAL_PATH).stratum is Stratum.ADVERSARIAL_STRESS
        assert load_case_file(PAIRWISE_PATH).stratum is Stratum.ADVERSARIAL_STRESS

    def test_the_stress_corpus_is_adversarial_by_construction(self) -> None:
        """Eleven of twenty-four cases are designed false passes.

        The rate this produces describes the corpus, which is exactly why
        the protocol reports the two strata separately and never pools
        them.
        """
        counts = Counter(case.expected_outcome for case in load_cases())

        assert counts[Outcome.FALSE_PASS] == 11
        assert sum(counts.values()) == 24

    def test_no_fixture_item_counts_toward_the_campaign_set(self) -> None:
        items = as_labelled_items(
            load_cases(), rationale_ref=REF, guideline_ref=REF, labeled_at=AT
        )

        assert len(campaign_eligible(items)) == len(items)
        assert human_annotator_ids(items) == ()

    def test_the_fixture_annotator_is_a_construction_fact_not_an_expert(self) -> None:
        assert FIXTURE_ANNOTATOR.kind is AnnotatorKind.SYNTHETIC_CONSTRUCTION
        assert FIXTURE_ANNOTATOR.is_synthetic
        assert not FIXTURE_ANNOTATOR.is_human

    def test_a_fixture_item_has_one_label_and_therefore_no_reference_decision(self) -> None:
        """A construction fact has nobody to disagree with, which is why
        these items have no adjudication lineage to inspect."""
        items = as_labelled_items(
            load_cases()[:1], rationale_ref=REF, guideline_ref=REF, labeled_at=AT
        )

        assert items[0].agreement_state == "unreviewed"
        assert items[0].resolved_decision is None


class TestTheWorkedSet:
    def test_it_carries_multiple_annotators_and_real_disagreement(self) -> None:
        worked = load_labelled_set()
        states = {item.agreement_state for item in worked.items}

        assert "adjudicated" in states
        assert "agreed" in states
        assert len(human_annotator_ids(worked.items)) >= 3

    def test_every_adjudication_rule_the_protocol_names_has_a_worked_example(self) -> None:
        worked = load_labelled_set()
        rules = {
            item.adjudication.rule.value
            for item in worked.items
            if item.adjudication is not None
        }

        assert rules == {
            "unanimous",
            "majority",
            "expert_override",
            "guideline_rule",
            "unresolved",
        }

    def test_the_escalated_item_carries_no_reference_decision(self) -> None:
        worked = load_labelled_set()
        escalated = [
            item
            for item in worked.items
            if item.adjudication is not None and item.adjudication.rule.value == "unresolved"
        ]

        assert len(escalated) == 1
        assert escalated[0].resolved_decision is None
        # And its individual decisions survive.
        assert len(escalated[0].adjudication.decisions) == 3  # type: ignore[union-attr]

    def test_every_worked_item_is_campaign_eligible(self) -> None:
        worked = load_labelled_set()

        assert campaign_eligible(worked.items) == ()

    def test_editing_a_rationale_without_re_deriving_its_digest_fails_the_load(
        self, tmp_path: Path
    ) -> None:
        payload = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
        payload["rationales"][0]["text"] = "a different reason entirely"
        edited = tmp_path / "labelled_set.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="does not match its content"):
            load_labelled_set(edited)

    def test_a_verdict_naming_another_grader_profile_is_refused(
        self, tmp_path: Path
    ) -> None:
        payload = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
        payload["judge_verdicts"][0]["grader_profile_ref"]["id"] = "some-other-profile"
        edited = tmp_path / "labelled_set.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="this file's grader profile"):
            load_labelled_set(edited)

    def test_a_verdict_for_an_unlabelled_item_is_refused(self, tmp_path: Path) -> None:
        payload = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
        payload["judge_verdicts"][0]["blinded_item_id"] = "itm-ffffffffffff"
        edited = tmp_path / "labelled_set.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="carry no label"):
            load_labelled_set(edited)


class TestConversionIntoTheMetricsVocabulary:
    def test_a_case_blinds_to_the_id_the_fixture_salt_produces(self) -> None:
        from src.calibration.blinding import blind_item_id
        from src.calibration.fixtures import FIXTURE_SALT

        case = load_cases()[0]

        assert case.blinded_item_id == blind_item_id(FIXTURE_SALT, case.case_id)

    def test_pairwise_conversion_produces_two_verdicts_per_pair(self) -> None:
        verdicts = as_predicted_pairwise_verdicts(
            load_pairwise(),
            grader_profile_ref=GRADER,
            rubric_name="pairwise",
            rubric_version="1.0.0",
            observed_at=AT,
        )

        assert len(verdicts) == 12
        assert {verdict.presentation_order for verdict in verdicts} == {"ab", "ba"}

    def test_the_corpus_round_trips_through_the_report_builder(self) -> None:
        from src.calibration.metrics import build_report, decide

        cases = load_cases()
        report = build_report(
            set_id="judge-calibration-v1",
            set_revision="1.0.0",
            judge_rubric_name="faithfulness",
            judge_rubric_version="1.0.0",
            calibration_rubric_version="1.0.0",
            items=as_labelled_items(
                cases, rationale_ref=REF, guideline_ref=REF, labeled_at=AT
            ),
            verdicts=as_predicted_verdicts(
                cases,
                grader_profile_ref=GRADER,
                rubric_name="faithfulness",
                rubric_version="1.0.0",
                observed_at=AT,
            ),
        )

        # Single-label items resolve to nothing, so the stress corpus
        # produces no confusion table at all. That is the correct answer:
        # a construction fact with no second reader is not a reference
        # decision, and the gate says so rather than scoring it.
        assert report.decided_items == 0
        assert decide(report).state == "HOLD"


class TestTheFixtureFilesThemselves:
    def test_the_three_authored_files_are_the_whole_corpus(self) -> None:
        assert sorted(path.name for path in FIXTURE_ROOT.glob("*.json")) == [
            "adversarial_cases.json",
            "labelled_set.json",
            "pairwise_cases.json",
        ]

    def test_each_file_carries_its_own_readme(self) -> None:
        for path in (ADVERSARIAL_PATH, PAIRWISE_PATH):
            assert len(load_case_file(path).readme) > 200
        assert len(load_labelled_set().readme) > 200

    def test_no_case_cites_a_real_arxiv_identifier_shape_that_could_resolve(self) -> None:
        """Every invented identifier has a sequence number below 1000.

        Real arXiv sequence numbers run to five digits within days of a
        month opening, so the low band is effectively unoccupied. The
        corpus states in its readme that its identifiers are invented;
        this is the cheap mechanical half of that claim, so an excerpt
        pasted in from a real paper would have to change the identifier
        before it could land.
        """
        cited = {
            case.material.cited_source
            for case in load_cases()
            if case.material.cited_source is not None
        }

        assert cited
        for identifier in cited:
            assert identifier.startswith("arxiv:")
            yymm, _, sequence = identifier.removeprefix("arxiv:").partition(".")
            assert len(yymm) == 4 and yymm.isdigit()
            assert len(sequence) == 5 and int(sequence) < 1000


class TestTheRemainingFixtureRefusals:
    def test_a_judge_verdict_outside_the_vocabulary_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="is not a claim_support decision"):
            CalibrationCase(
                case_id="bad-case",
                family=Family.VERBOSITY,
                label_type=LabelType.CLAIM_SUPPORT,
                slice_tags=("evidence-rich",),
                material={"report_excerpt": "x"},  # type: ignore[arg-type]
                expected_reference_decision="supported",
                expected_judge_verdict="covered",
                expected_outcome=Outcome.TRUE_PASS,
                why="y",
            )

    def test_duplicate_slice_tags_on_one_case_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="slice tags must be unique"):
            CalibrationCase(
                case_id="bad-case",
                family=Family.VERBOSITY,
                label_type=LabelType.CLAIM_SUPPORT,
                slice_tags=("evidence-rich", "evidence-rich"),
                material={"report_excerpt": "x"},  # type: ignore[arg-type]
                expected_reference_decision="supported",
                expected_judge_verdict="supported",
                expected_outcome=Outcome.TRUE_PASS,
                why="y",
            )

    def test_a_pairwise_verdict_outside_the_vocabulary_is_refused(
        self, tmp_path: Path
    ) -> None:
        payload = json.loads(PAIRWISE_PATH.read_text(encoding="utf-8"))
        payload["pairwise"][0]["expected_ab_verdict"] = "supported"
        edited = tmp_path / "pairwise_cases.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="is not a pairwise decision"):
            load_case_file(edited)

    def test_an_undeclared_tag_on_a_pairwise_case_is_refused(self, tmp_path: Path) -> None:
        payload = json.loads(PAIRWISE_PATH.read_text(encoding="utf-8"))
        payload["pairwise"][0]["slice_tags"].append("a-slice-nobody-declared")
        edited = tmp_path / "pairwise_cases.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="undeclared slice tags"):
            load_case_file(edited)

    def test_an_empty_fixture_file_is_refused(self, tmp_path: Path) -> None:
        edited = tmp_path / "empty.json"
        edited.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "stratum": "representative",
                    "readme": "nothing here",
                    "cases": [],
                    "pairwise": [],
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValidationError, match="at least one case"):
            load_case_file(edited)

    def test_two_labelled_items_for_one_blinded_id_are_refused(
        self, tmp_path: Path
    ) -> None:
        payload = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
        payload["items"].append(payload["items"][0])
        edited = tmp_path / "labelled_set.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="one labelled item per blinded id"):
            load_labelled_set(edited)

    def test_duplicate_rationale_ids_are_refused(self, tmp_path: Path) -> None:
        payload = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
        payload["rationales"].append(payload["rationales"][0])
        edited = tmp_path / "labelled_set.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="rationale ids must be unique"):
            load_labelled_set(edited)

    def test_a_label_citing_a_rationale_that_is_not_in_the_file_is_refused(
        self, tmp_path: Path
    ) -> None:
        payload = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
        payload["items"][0]["labels"][0]["rationale_ref"]["id"] = "no-such-rationale"
        edited = tmp_path / "labelled_set.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="no rationale"):
            load_labelled_set(edited)

    def test_a_label_citing_another_guideline_revision_is_refused(
        self, tmp_path: Path
    ) -> None:
        payload = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
        payload["items"][0]["labels"][0]["guideline_ref"]["revision"] = "2.0.0"
        edited = tmp_path / "labelled_set.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="does not match this file's guide"):
            load_labelled_set(edited)

    def test_an_adjudication_rationale_is_checked_too(self, tmp_path: Path) -> None:
        payload = json.loads(LABELLED_SET_PATH.read_text(encoding="utf-8"))
        adjudicated = next(
            item
            for item in payload["items"]
            if item["adjudication"] is not None
            and item["adjudication"]["rationale_ref"] is not None
        )
        adjudicated["adjudication"]["rationale_ref"]["id"] = "no-such-rationale"
        edited = tmp_path / "labelled_set.json"
        edited.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValidationError, match="no rationale"):
            load_labelled_set(edited)

    def test_the_fixture_root_is_under_tests_not_src(self) -> None:
        """ADR 0072's rule: fixtures are not shipped data, and nothing in
        the running product may import them."""
        assert FIXTURE_ROOT.parts[-2:] == ("fixtures", "calibration")
        assert "tests" in FIXTURE_ROOT.parts
