"""Unit tests for `src/calibration/suite.py` and the registry tree.

The registry half of 12 §16's acceptance criteria: the calibration suite
resolves through W02's resolver in the evaluator role, its labels are
invisible to the candidate role, and the checked-in tree is exactly what
the fixtures build.

Also, in `TestW06sTreeIsUntouched`, the reason this suite has its own
root: W06's tree is guarded by tests that make it exactly what its own
builder produces, so a second suite cannot live there without weakening
them. This file asserts that neither tree can see the other.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.calibration.blinding import HIDDEN_FROM_JUDGE, Presentation
from src.calibration.fixtures import load_cases, load_pairwise
from src.calibration.labels import LabelType, decision_vocabulary
from src.calibration.suite import (
    CALIBRATION_REGISTRY_ROOT,
    GRADER_PROFILE_ID,
    LABEL_SET_ID,
    SUITE_ID,
    BlindingPlanContent,
    CalibrationContentEnvelope,
    CalibrationContentStore,
    ExpectedLabelValue,
    JudgeProbeLock,
    SyntheticGenerationRecord,
    build_bundle,
    locator,
    main,
    read_tree,
    suite_ref,
    tree_mismatches,
    write_tree,
)
from src.contracts.kernel import sha256_digest
from src.contracts.registry import (
    BenchmarkSuite,
    Exposure,
    GraderProfile,
    IntendedUse,
    LabelSet,
    LifecycleStatus,
    LocalRegistry,
    ObjectVisibility,
    RegistryAccessError,
    RegistryResolutionError,
    RegistryRole,
    RubricSet,
    SplitAssignment,
    TaskCase,
    TaskSet,
    project_for_role,
    validate_registry_safety,
)
from src.eval.metrics import RESEARCH_RUBRICS

pytestmark = pytest.mark.unit

EVALUATOR = {"role": RegistryRole.EVALUATOR, "intended_use": IntendedUse.CALIBRATION}


@pytest.fixture(scope="module")
def registry() -> LocalRegistry:
    return LocalRegistry(CALIBRATION_REGISTRY_ROOT)


@pytest.fixture(scope="module")
def suite(registry: LocalRegistry) -> BenchmarkSuite:
    envelope = registry.resolve(suite_ref(), **EVALUATOR)
    assert isinstance(envelope.payload, BenchmarkSuite)
    return envelope.payload


class TestTheCheckedInTreeIsWhatTheFixturesBuild:
    def test_parity_is_clean(self) -> None:
        assert tree_mismatches() == ()

    def test_the_writer_regenerates_a_byte_identical_tree(self, tmp_path: Path) -> None:
        root = tmp_path / "eval_registry_calibration"
        write_tree(build_bundle(), root)

        written = sorted(path.relative_to(root) for path in root.rglob("*.json"))
        committed = sorted(
            path.relative_to(CALIBRATION_REGISTRY_ROOT)
            for path in CALIBRATION_REGISTRY_ROOT.rglob("*.json")
        )

        assert written == committed
        for relative in written:
            assert (root / relative).read_bytes() == (
                CALIBRATION_REGISTRY_ROOT / relative
            ).read_bytes()

    def test_an_edited_object_is_reported_rather_than_raised(self, tmp_path: Path) -> None:
        root = tmp_path / "eval_registry_calibration"
        write_tree(build_bundle(), root)
        target = root / "content" / "calibration_item" / "polish-scaling-emergent" / "1.0.0.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["payload"]["report_excerpt"] = "something else entirely"
        target.write_text(json.dumps(payload), encoding="utf-8")

        mismatches = tree_mismatches(root)

        assert any("polish-scaling-emergent" in line for line in mismatches)

    def test_an_extra_file_is_reported(self, tmp_path: Path) -> None:
        root = tmp_path / "eval_registry_calibration"
        write_tree(build_bundle(), root)
        extra = root / "task_case" / "invented" / "1.0.0.json"
        extra.parent.mkdir(parents=True)
        extra.write_text("{}", encoding="utf-8")

        assert any(
            "the fixtures do not build" in line for line in tree_mismatches(root)
        )

    def test_a_missing_tree_is_reported_rather_than_crashing(self, tmp_path: Path) -> None:
        assert tree_mismatches(tmp_path / "nothing-here") == (
            "nothing-here: the registry tree does not exist",
        )

    def test_read_tree_verifies_every_digest_and_locator(self) -> None:
        objects, contents = read_tree()

        assert len(objects) == 37
        assert len(contents) == 83
        for envelope in objects:
            assert locator(envelope.object_ref(), content=False)
        for content in contents:
            assert content.integrity.payload_digest == sha256_digest(content.payload)

    def test_a_mislocated_object_is_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "eval_registry_calibration"
        write_tree(build_bundle(), root)
        source = root / "retention_policy" / "calibration-repository-history" / "1.0.0.json"
        moved = root / "retention_policy" / "somewhere-else" / "1.0.0.json"
        moved.parent.mkdir(parents=True)
        moved.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

        with pytest.raises(RegistryResolutionError, match="mislocated"):
            read_tree(root)

    def test_every_object_passes_the_registry_safety_scan(self) -> None:
        objects, _ = read_tree()

        for envelope in objects:
            validate_registry_safety(envelope)

    def test_the_parity_cli_exits_zero_on_the_committed_tree(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["parity"]) == 0
        assert "parity clean" in capsys.readouterr().out

    def test_the_parity_cli_exits_nonzero_on_a_mismatch(self, tmp_path: Path) -> None:
        assert main(["parity", "--root", str(tmp_path / "nothing")]) == 1

    def test_the_write_cli_reports_what_it_wrote(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["write", "--root", str(tmp_path / "tree")]) == 0
        assert "wrote 120 objects" in capsys.readouterr().out


class TestTheSuiteResolvesForAnEvaluator:
    def test_the_suite_resolves_in_the_evaluator_role_for_calibration(
        self, suite: BenchmarkSuite
    ) -> None:
        assert suite.suite_id == SUITE_ID
        assert suite.status is LifecycleStatus.ACTIVE
        assert suite.intended_uses == (IntendedUse.CALIBRATION,)

    def test_every_referenced_object_resolves_too(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        for ref in (
            suite.task_set_ref,
            suite.rubric_set_ref,
            suite.split_assignment_ref,
            *suite.label_set_refs,
            *suite.grader_profile_refs,
        ):
            assert registry.resolve(ref, **EVALUATOR).object_ref() == ref

    def test_every_task_case_resolves_and_carries_its_slice_tags(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        task_set = registry.resolve(suite.task_set_ref, **EVALUATOR).payload
        assert isinstance(task_set, TaskSet)

        assert len(task_set.case_refs) == 30
        for ref in task_set.case_refs:
            case = registry.resolve(ref, **EVALUATOR).payload
            assert isinstance(case, TaskCase)
            assert case.slice_tags
            assert case.evaluator_refs

    def test_the_case_ids_are_exactly_the_authored_fixture_ids(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        task_set = registry.resolve(suite.task_set_ref, **EVALUATOR).payload
        assert isinstance(task_set, TaskSet)
        registered = {ref.id for ref in task_set.case_refs}
        authored = {case.case_id for case in load_cases()} | {
            case.case_id for case in load_pairwise()
        }

        assert registered == authored

    def test_a_use_the_suite_does_not_declare_is_refused(
        self, registry: LocalRegistry
    ) -> None:
        for use in (IntendedUse.DEVELOPMENT, IntendedUse.REGRESSION, IntendedUse.PROMOTION):
            with pytest.raises(RegistryResolutionError, match="does not declare"):
                registry.resolve(suite_ref(), role=RegistryRole.EVALUATOR, intended_use=use)

    def test_promotion_is_prohibited_not_merely_undeclared(
        self, suite: BenchmarkSuite
    ) -> None:
        """A publicly exposed set cannot be sealed promotion evidence."""
        assert IntendedUse.PROMOTION in suite.prohibited_uses
        assert suite.contamination.exposure is Exposure.PUBLIC_REPOSITORY


class TestTheLabelsAreInvisibleToACandidate:
    def test_a_candidate_cannot_resolve_the_label_set(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        with pytest.raises(RegistryAccessError, match="cannot resolve label_set"):
            registry.resolve(
                suite.label_set_refs[0],
                role=RegistryRole.CANDIDATE,
                intended_use=IntendedUse.CALIBRATION,
            )

    def test_a_candidate_cannot_resolve_a_task_case_either(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        """There is no candidate role for a judge probe.

        Kind-based denial covers the suite, task set, label set, split and
        grader profile; task cases are denied by visibility, which is why
        every one of them is evaluator-only rather than candidate-visible.
        """
        task_set = registry.resolve(suite.task_set_ref, **EVALUATOR).payload
        assert isinstance(task_set, TaskSet)

        with pytest.raises(RegistryAccessError, match="evaluator or owner material"):
            registry.resolve(
                task_set.case_refs[0],
                role=RegistryRole.CANDIDATE,
                intended_use=IntendedUse.CALIBRATION,
            )

    def test_a_candidate_projection_of_a_task_case_is_denied(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        task_set = registry.resolve(suite.task_set_ref, **EVALUATOR).payload
        assert isinstance(task_set, TaskSet)
        envelope = registry.resolve(task_set.case_refs[0], **EVALUATOR)

        with pytest.raises(RegistryAccessError, match="hidden material"):
            project_for_role(envelope, RegistryRole.CANDIDATE)

    def test_no_task_case_carries_a_candidate_visible_ref(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        task_set = registry.resolve(suite.task_set_ref, **EVALUATOR).payload
        assert isinstance(task_set, TaskSet)

        for ref in task_set.case_refs:
            case = registry.resolve(ref, **EVALUATOR).payload
            assert isinstance(case, TaskCase)
            assert case.candidate_visible_refs == ()

    def test_a_candidate_cannot_resolve_the_answer_key_content(self) -> None:
        store = CalibrationContentStore(CALIBRATION_REGISTRY_ROOT)
        _, contents = read_tree()
        expected_label = next(
            content
            for content in contents
            if isinstance(content.payload, ExpectedLabelValue)
        )

        with pytest.raises(RegistryAccessError, match="candidate cannot resolve"):
            store.resolve(expected_label.object_ref(), role=RegistryRole.CANDIDATE)

    def test_the_evaluator_can_resolve_it(self) -> None:
        store = CalibrationContentStore(CALIBRATION_REGISTRY_ROOT)
        _, contents = read_tree()
        expected_label = next(
            content
            for content in contents
            if isinstance(content.payload, ExpectedLabelValue)
        )

        resolved = store.resolve(expected_label.object_ref(), role=RegistryRole.EVALUATOR)

        assert resolved.object_ref() == expected_label.object_ref()

    def test_every_rubric_item_is_evaluator_only(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        rubric = registry.resolve(suite.rubric_set_ref, **EVALUATOR).payload
        assert isinstance(rubric, RubricSet)

        assert {item.visibility for item in rubric.items} == {ObjectVisibility.EVALUATOR}

    def test_a_content_locator_cannot_escape_its_root(self) -> None:
        from src.contracts.kernel import ImmutableObjectRef

        store = CalibrationContentStore(CALIBRATION_REGISTRY_ROOT)
        escaping = ImmutableObjectRef(
            kind="expected_label",
            id="x",
            revision="1.0.0",
            digest=sha256_digest({"x": 1}),
        )

        with pytest.raises(RegistryResolutionError, match="unavailable"):
            store.resolve(escaping, role=RegistryRole.EVALUATOR)


class TestTheLabelSetAndTheGraderProfile:
    def test_every_case_has_exactly_one_label_bound_by_value_ref(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        label_set = registry.resolve(suite.label_set_refs[0], **EVALUATOR).payload
        assert isinstance(label_set, LabelSet)

        assert label_set.label_set_id == LABEL_SET_ID
        assert len(label_set.labels) == 30
        for record in label_set.labels:
            assert record.value_ref.kind == "expected_label"
            assert record.target_ref.kind == "task_case"
            assert record.evidence_refs

    def test_a_construction_fact_is_unreviewed_rather_than_agreed(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        """One decision is not a consensus, and calling it one would be
        the overwrite RFC 11 §9.2 forbids wearing a default's clothes."""
        label_set = registry.resolve(suite.label_set_refs[0], **EVALUATOR).payload
        assert isinstance(label_set, LabelSet)

        assert {record.agreement_state for record in label_set.labels} == {"unreviewed"}

    def test_the_label_type_names_the_annotator_kind(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        label_set = registry.resolve(suite.label_set_refs[0], **EVALUATOR).payload
        assert isinstance(label_set, LabelSet)

        assert all(
            record.label_type.endswith(".synthetic_construction")
            for record in label_set.labels
        )

    def test_every_decision_in_every_vocabulary_has_a_value_object(self) -> None:
        _, contents = read_tree()
        values = {
            (content.payload.label_type, content.payload.decision)
            for content in contents
            if isinstance(content.payload, ExpectedLabelValue)
        }

        for label_type in LabelType:
            for decision in decision_vocabulary(label_type):
                assert (label_type.value, decision) in values

    def test_the_grader_profile_pins_no_model(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        """RFC 11 §9.3: selecting a model grader is invalid without a
        recorded cost approval, and there is none."""
        grader = registry.resolve(suite.grader_profile_refs[0], **EVALUATOR).payload
        assert isinstance(grader, GraderProfile)

        assert grader.grader_profile_id == GRADER_PROFILE_ID
        assert grader.model_judge_ref is None
        assert grader.prompt_ref is None
        assert grader.calibration_ref == suite.label_set_refs[0]

    def test_the_probe_lock_records_the_live_rubric_versions(self) -> None:
        _, contents = read_tree()
        lock = next(
            content.payload
            for content in contents
            if isinstance(content.payload, JudgeProbeLock)
        )

        assert lock.judge_model_pinned is False
        assert {(entry.name, entry.version) for entry in lock.entries} == {
            (rubric.name, rubric.version) for rubric in RESEARCH_RUBRICS
        }
        assert {entry.prompt_digest for entry in lock.entries} == {
            f"sha256:{rubric.digest}" for rubric in RESEARCH_RUBRICS
        }


class TestTheGovernanceRecords:
    def test_the_split_is_development_because_sealed_would_fail_closed(
        self, registry: LocalRegistry, suite: BenchmarkSuite
    ) -> None:
        split = registry.resolve(suite.split_assignment_ref, **EVALUATOR).payload
        assert isinstance(split, SplitAssignment)

        assert split.split.value == "development"
        assert split.membership_visible_to_candidate is False

    def test_the_synthetic_generation_record_names_its_generator_and_no_source(self) -> None:
        _, contents = read_tree()
        record = next(
            content.payload
            for content in contents
            if isinstance(content.payload, SyntheticGenerationRecord)
        )

        assert record.source_inputs == ()
        assert record.generated_by_model is False
        assert record.identifiers_are_invented is True
        assert "P0-WO10" in record.generator

    def test_the_blinding_plan_hides_every_required_field_and_swaps(self) -> None:
        _, contents = read_tree()
        content = next(
            item.payload
            for item in contents
            if isinstance(item.payload, BlindingPlanContent)
        )

        assert set(content.plan.hidden_fields) >= HIDDEN_FROM_JUDGE
        assert content.plan.presentation is Presentation.PAIRWISE
        assert content.plan.both_orders is True
        assert content.plan.judge_sees_reference is False
        assert "synthetic" in content.salt_is_public_because

    def test_training_use_is_prohibited_on_every_object(self) -> None:
        objects, _ = read_tree()

        assert {envelope.payload.data_policy.training_use.value for envelope in objects} == {
            "prohibited"
        }

    def test_every_object_names_the_protocol_document_as_its_review_record(self) -> None:
        objects, _ = read_tree()

        assert {envelope.payload.provenance.review_record for envelope in objects} == {
            "docs/agent-engineering/14-judge-calibration-protocol.md"
        }


class TestW06sTreeIsUntouched:
    def test_the_calibration_tree_is_a_sibling_of_the_benchmark_tree(self) -> None:
        from src.contracts.benchmark_adapters import REGISTRY_ROOT

        assert CALIBRATION_REGISTRY_ROOT != REGISTRY_ROOT
        assert not CALIBRATION_REGISTRY_ROOT.is_relative_to(REGISTRY_ROOT)
        assert CALIBRATION_REGISTRY_ROOT.parent == REGISTRY_ROOT.parent

    def test_w06s_tree_carries_no_calibration_object(self) -> None:
        from src.contracts.benchmark_adapters import REGISTRY_ROOT

        names = {path.parent.name for path in REGISTRY_ROOT.rglob("*.json")}

        assert SUITE_ID not in names
        assert LABEL_SET_ID not in names

    def test_the_calibration_tree_carries_no_benchmark_object(self) -> None:
        objects, _ = read_tree()
        ids = {envelope.object_ref().id for envelope in objects}

        assert "research-policy-v1" not in ids
        assert "guided-learning-v1" not in ids

    def test_the_layout_is_the_same_one_w02s_resolver_reads(self) -> None:
        """`<kind>/<id>/<revision>.json`, content under `content/` — the
        locator LocalRegistry derives, so no adapter is needed."""
        for path in CALIBRATION_REGISTRY_ROOT.rglob("*.json"):
            relative = path.relative_to(CALIBRATION_REGISTRY_ROOT).parts
            assert path.name.endswith(".json")
            assert len(relative) in (3, 4)
            if len(relative) == 4:
                assert relative[0] == "content"


class TestTheContentEnvelope:
    def test_an_envelope_whose_id_disagrees_with_its_payload_is_refused(self) -> None:
        _, contents = read_tree()
        payload = json.loads(
            next(
                content
                for content in contents
                if isinstance(content.payload, ExpectedLabelValue)
            ).model_dump_json()
        )
        payload["content_id"] = "something-else"

        with pytest.raises(ValueError, match="does not match payload id"):
            CalibrationContentEnvelope.model_validate_json(json.dumps(payload))

    def test_a_tampered_payload_fails_its_own_digest(self) -> None:
        _, contents = read_tree()
        payload = json.loads(
            next(
                content
                for content in contents
                if isinstance(content.payload, ExpectedLabelValue)
            ).model_dump_json()
        )
        payload["payload"]["is_abstention"] = not payload["payload"]["is_abstention"]

        with pytest.raises(ValueError, match="digest mismatch"):
            CalibrationContentEnvelope.model_validate_json(json.dumps(payload))

    def test_content_digests_survive_key_order(self) -> None:
        _, contents = read_tree()
        content = contents[0]
        payload = json.loads(content.model_dump_json())
        shuffled = {"payload": payload["payload"], **payload}

        round_tripped = CalibrationContentEnvelope.model_validate_json(json.dumps(shuffled))

        assert round_tripped.integrity.payload_digest == content.integrity.payload_digest


class TestTheRemainingSuiteRefusals:
    def test_a_blinding_content_whose_ids_disagree_is_refused(self) -> None:
        _, contents = read_tree()
        payload = json.loads(
            next(
                content
                for content in contents
                if isinstance(content.payload, BlindingPlanContent)
            ).model_dump_json()
        )
        payload["payload"]["plan"]["plan_id"] = "some-other-plan"

        with pytest.raises(ValueError, match="nested plan id must agree"):
            CalibrationContentEnvelope.model_validate_json(json.dumps(payload))

    def test_an_envelope_whose_kind_disagrees_with_its_payload_is_refused(self) -> None:
        _, contents = read_tree()
        payload = json.loads(
            next(
                content
                for content in contents
                if isinstance(content.payload, ExpectedLabelValue)
            ).model_dump_json()
        )
        payload["schema_kind"] = "calibration_rationale"

        with pytest.raises(ValueError, match="does not match payload"):
            CalibrationContentEnvelope.model_validate_json(json.dumps(payload))

    def test_a_content_locator_that_escapes_its_root_is_refused(self) -> None:
        from src.contracts.kernel import ImmutableObjectRef

        store = CalibrationContentStore(CALIBRATION_REGISTRY_ROOT)
        escaping = ImmutableObjectRef(
            kind="expected_label",
            id="x",
            revision="1.0.0",
            digest=sha256_digest({"x": 1}),
        )
        # `..` is not expressible in an id, so the escape is forced by
        # pointing the store at a root the resolved path cannot be under.
        store.root = (CALIBRATION_REGISTRY_ROOT / "content" / "nowhere" / "deeper").resolve()

        with pytest.raises(RegistryResolutionError, match="unavailable"):
            store.resolve(escaping, role=RegistryRole.EVALUATOR)

    def test_an_invalid_content_file_is_reported_as_such(self, tmp_path: Path) -> None:

        root = tmp_path / "eval_registry_calibration"
        write_tree(build_bundle(), root)
        _, contents = read_tree()
        target = next(
            content
            for content in contents
            if isinstance(content.payload, ExpectedLabelValue)
        )
        ref = target.object_ref()
        (root / "content" / ref.kind / ref.id / f"{ref.revision}.json").write_text(
            "{}", encoding="utf-8"
        )

        with pytest.raises(RegistryResolutionError, match="invalid content envelope"):
            CalibrationContentStore(root).resolve(ref, role=RegistryRole.EVALUATOR)

    def test_a_content_ref_whose_digest_does_not_match_is_refused(
        self, tmp_path: Path
    ) -> None:
        from src.contracts.kernel import ImmutableObjectRef

        _, contents = read_tree()
        target = next(
            content
            for content in contents
            if isinstance(content.payload, ExpectedLabelValue)
        )
        ref = target.object_ref()
        wrong = ImmutableObjectRef(
            kind=ref.kind,
            id=ref.id,
            revision=ref.revision,
            digest=sha256_digest({"not": "the payload"}),
        )

        with pytest.raises(RegistryResolutionError, match="does not match the exact reference"):
            CalibrationContentStore(CALIBRATION_REGISTRY_ROOT).resolve(
                wrong, role=RegistryRole.EVALUATOR
            )

    def test_an_owner_only_content_object_is_denied_to_an_evaluator(self) -> None:
        from src.calibration.suite import RationaleText, seal_content

        owner_only = seal_content(
            RationaleText(rationale_id="owner-note", text="owner eyes only"),
            visibility=ObjectVisibility.OWNER,
            source_module="tests/test_calibration_suite.py",
        )
        store = CalibrationContentStore(CALIBRATION_REGISTRY_ROOT)
        ref = owner_only.object_ref()
        path = (
            CALIBRATION_REGISTRY_ROOT
            / "content"
            / ref.kind
            / ref.id
            / f"{ref.revision}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(owner_only.model_dump_json(), encoding="utf-8")
        try:
            with pytest.raises(RegistryAccessError, match="owner-only content"):
                store.resolve(ref, role=RegistryRole.EVALUATOR)
        finally:
            path.unlink()
            path.parent.rmdir()

    def test_the_content_safety_scan_refuses_a_secret_shaped_value(self) -> None:
        from src.calibration.suite import RationaleText, seal_content, validate_content_safety

        envelope = seal_content(
            RationaleText(
                rationale_id="leaky", text="the annotator used api_key=sk-not-a-real-key"
            ),
            visibility=ObjectVisibility.EVALUATOR,
            source_module="tests/test_calibration_suite.py",
        )

        with pytest.raises(RegistryAccessError, match="secret-shaped value"):
            validate_content_safety(envelope)

    def test_a_missing_suite_file_is_reported(self, tmp_path: Path) -> None:
        with pytest.raises(RegistryResolutionError, match="has no suite"):
            suite_ref(tmp_path)

    def test_an_unparseable_registry_file_is_reported_by_read_tree(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "eval_registry_calibration"
        write_tree(build_bundle(), root)
        (root / "retention_policy" / "calibration-repository-history" / "1.0.0.json").write_text(
            "{}", encoding="utf-8"
        )

        with pytest.raises(RegistryResolutionError, match="invalid registry object"):
            read_tree(root)

    def test_a_missing_file_is_reported_as_a_mismatch(self, tmp_path: Path) -> None:
        root = tmp_path / "eval_registry_calibration"
        write_tree(build_bundle(), root)
        (root / "retention_policy" / "calibration-repository-history" / "1.0.0.json").unlink()

        assert any("the tree has no file" in line for line in tree_mismatches(root))

    def test_the_content_safety_scan_refuses_a_private_absolute_path(self) -> None:
        from src.calibration.suite import RationaleText, seal_content, validate_content_safety

        envelope = seal_content(
            RationaleText(
                rationale_id="local-path",
                text="the annotator worked from /Users/someone/notes/calibration.md",
            ),
            visibility=ObjectVisibility.EVALUATOR,
            source_module="tests/test_calibration_suite.py",
        )

        with pytest.raises(RegistryAccessError, match="private absolute path"):
            validate_content_safety(envelope)
