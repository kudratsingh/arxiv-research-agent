"""No-cost contract tests for the development evaluation registry."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src.contracts.kernel import DataClass, ImmutableObjectRef, RetentionPolicyRef, canonical_json
from src.contracts.registry import (
    BenchmarkSuite,
    CampaignLock,
    Contamination,
    DataPolicy,
    EvaluationLane,
    Exposure,
    FixtureObservation,
    FixtureSet,
    GovernedPayload,
    GraderProfile,
    InMemoryRegistry,
    IntendedUse,
    LabelSet,
    LicensePolicy,
    LifecycleStatus,
    LocalRegistry,
    ObjectVisibility,
    Provenance,
    Redistribution,
    RegistryAccessError,
    RegistryEnvelope,
    RegistryIntegrity,
    RegistryKind,
    RegistryResolutionError,
    RegistryRole,
    RestrictedRegistryUnavailable,
    RubricItem,
    RubricSet,
    SourceMode,
    SourceSnapshot,
    SplitAssignment,
    SplitKind,
    TaskCase,
    TaskInput,
    TaskSet,
    TrainingUse,
    generate_campaign_lock,
    main,
    project_for_role,
    registry_json_schema,
    seal_registry_object,
    validate_lock,
    validate_split_disjointness,
)

NOW_TEXT = "2026-09-04T16:00:00Z"
NOW = datetime(2026, 9, 4, 16, tzinfo=UTC)
VALIDATOR_REF = ImmutableObjectRef(
    kind="registry_validator",
    id="local-v1",
    revision="1.0.0",
    digest="sha256:" + "f" * 64,
)


def ref(kind: str, object_id: str, digest: str | None = None, revision: str = "1.0.0") -> ImmutableObjectRef:
    return ImmutableObjectRef(
        kind=kind,
        id=object_id,
        revision=revision,
        digest=digest or "sha256:" + "a" * 64,
    )


def governed(
    *,
    visibility: ObjectVisibility = ObjectVisibility.PUBLIC,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    intended_uses: tuple[IntendedUse, ...] = (IntendedUse.DEVELOPMENT,),
    prohibited_uses: tuple[IntendedUse, ...] = (IntendedUse.PROMOTION,),
    expires_at: str | None = None,
    deleted_at: str | None = None,
    revision: str = "1.0.0",
) -> dict[str, Any]:
    return {
        "revision": revision,
        "status": status,
        "owners": ("maintainer",),
        "visibility": visibility,
        "intended_uses": intended_uses,
        "prohibited_uses": prohibited_uses,
        "license_policy": LicensePolicy(
            license_id="project-license",
            redistribution=Redistribution.PERMITTED,
            permitted_uses=intended_uses,
            attribution="Maintainer-authored test fixture",
            expires_at=expires_at,
        ),
        "data_policy": DataPolicy(
            registry_classification=DataClass.INTERNAL,
            effective_data_class=DataClass.PUBLIC,
            contains_personal_data=False,
            training_use=TrainingUse.PROHIBITED,
            retention_policy_ref=RetentionPolicyRef(
                kind="retention_policy",
                id="repository-history",
                revision="1.0.0",
                digest="sha256:" + "b" * 64,
            ),
            deleted_at=deleted_at,
        ),
        "contamination": Contamination(
            exposure=Exposure.PUBLIC_REPOSITORY,
            last_reviewed_at=NOW_TEXT,
        ),
        "provenance": Provenance(
            created_at=NOW_TEXT,
            created_by="maintainer",
            review_record="local-test-review",
        ),
    }


def task_case(case_id: str, *, objective: str | None = None, revision: str = "1.0.0", **gov: Any) -> RegistryEnvelope:
    payload = TaskCase(
        **governed(revision=revision, **gov),
        case_id=case_id,
        task_input=TaskInput(
            objective=objective or f"Research objective for {case_id}",
            task_kind="research.focused_evidence_review",
            deliverable_ref=ref("deliverable_contract", "supported-report"),
        ),
        evaluator_refs=(ref("label_set", "hidden-sentinel"),),
        slice_tags=("retrieval",),
    )
    return seal_registry_object(payload)


def rubric() -> RegistryEnvelope:
    return seal_registry_object(
        RubricSet(
            **governed(visibility=ObjectVisibility.CANDIDATE),
            rubric_set_id="research-rubric",
            items=(
                RubricItem(
                    rubric_item_id="claims.supported",
                    revision="1.0.0",
                    description="Claims have cited support",
                    task_kinds=("research.focused_evidence_review",),
                    scoring_type="boolean",
                    evidence_type="citation",
                    visibility=ObjectVisibility.CANDIDATE,
                    aggregation="mean",
                    denominator_policy="all selected cases including failures",
                ),
                RubricItem(
                    rubric_item_id="hidden.expected",
                    revision="1.0.0",
                    description="Evaluator-only reference expectation",
                    task_kinds=("research.focused_evidence_review",),
                    scoring_type="boolean",
                    evidence_type="reference_label",
                    visibility=ObjectVisibility.EVALUATOR,
                    aggregation="mean",
                    denominator_policy="all selected cases including failures",
                ),
            ),
        )
    )


def registry_graph(
    *,
    split_kind: SplitKind = SplitKind.DEVELOPMENT,
    split_case_count: int = 2,
) -> dict[str, RegistryEnvelope]:
    case_a = task_case("case-a")
    case_b = task_case("case-b")
    case_refs = (case_a.object_ref(), case_b.object_ref())
    task_set = seal_registry_object(
        TaskSet(
            **governed(),
            task_set_id="research-tasks",
            case_refs=case_refs,
        )
    )
    rubric_set = rubric()
    labels = seal_registry_object(
        LabelSet(
            **governed(visibility=ObjectVisibility.EVALUATOR),
            label_set_id="research-labels",
            labels=(),
        )
    )
    split = seal_registry_object(
        SplitAssignment(
            **governed(visibility=ObjectVisibility.EVALUATOR),
            split_assignment_id="research-split",
            split=split_kind,
            case_refs=case_refs[:split_case_count],
        )
    )
    grader = seal_registry_object(
        GraderProfile(
            **governed(visibility=ObjectVisibility.EVALUATOR),
            grader_profile_id="research-grader",
            rubric_set_ref=rubric_set.object_ref(),
            null_score_policy="retain null in the expected denominator",
        )
    )
    suite = seal_registry_object(
        BenchmarkSuite(
            **governed(),
            suite_id="research-policy-v1",
            title="Research development suite",
            description="Synthetic local suite for registry qualification",
            task_kinds=("research.focused_evidence_review",),
            evaluation_lane=EvaluationLane.RESEARCH,
            task_set_ref=task_set.object_ref(),
            rubric_set_ref=rubric_set.object_ref(),
            label_set_refs=(labels.object_ref(),),
            split_assignment_ref=split.object_ref(),
            grader_profile_refs=(grader.object_ref(),),
        )
    )
    return {
        "case_a": case_a,
        "case_b": case_b,
        "task_set": task_set,
        "rubric": rubric_set,
        "labels": labels,
        "split": split,
        "grader": grader,
        "suite": suite,
    }


def memory_registry(graph: dict[str, RegistryEnvelope]) -> InMemoryRegistry:
    return InMemoryRegistry(graph.values())


def write_graph(root: Path, graph: dict[str, RegistryEnvelope]) -> None:
    for envelope in graph.values():
        object_ref = envelope.object_ref()
        path = root / object_ref.kind / object_ref.id / f"{object_ref.revision}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")


@pytest.mark.unit
def test_envelopes_round_trip_and_verify_payload_digest() -> None:
    envelope = task_case("stable-case")
    reparsed = RegistryEnvelope.model_validate_json(envelope.model_dump_json())
    assert reparsed == envelope
    assert reparsed.object_ref().digest == envelope.integrity.payload_digest

    document = json.loads(envelope.model_dump_json())
    document["payload"]["task_input"]["objective"] = "changed"
    with pytest.raises((ValidationError, RegistryResolutionError, ValueError), match="digest"):
        RegistryEnvelope.model_validate_json(json.dumps(document))


@pytest.mark.unit
def test_kind_and_child_reference_mismatches_fail() -> None:
    case = task_case("typed-case")
    with pytest.raises(ValidationError, match="does not match payload"):
        RegistryEnvelope(
            schema_kind=RegistryKind.LABEL_SET,
            payload=case.payload,
            integrity=RegistryIntegrity(payload_digest=case.integrity.payload_digest),
        )
    with pytest.raises(ValidationError, match="task_case"):
        TaskSet(
            **governed(),
            task_set_id="bad-task-set",
            case_refs=(ref("label_set", "not-a-case"),),
        )


@pytest.mark.unit
def test_exact_refs_resolve_and_history_is_retained() -> None:
    first = task_case("versioned", revision="1.0.0")
    second = task_case("versioned", objective="new meaning", revision="2.0.0")
    registry = InMemoryRegistry((first, second))
    assert registry.resolve(
        first.object_ref(), role=RegistryRole.EVALUATOR, intended_use=IntendedUse.DEVELOPMENT, now=NOW
    ) == first
    assert registry.resolve(
        second.object_ref(), role=RegistryRole.EVALUATOR, intended_use=IntendedUse.DEVELOPMENT, now=NOW
    ) == second

    wrong = first.object_ref().model_copy(update={"digest": "sha256:" + "0" * 64})
    with pytest.raises(RegistryResolutionError, match="digest mismatch"):
        registry.resolve(
            wrong, role=RegistryRole.EVALUATOR, intended_use=IntendedUse.DEVELOPMENT, now=NOW
        )


@pytest.mark.unit
def test_immutable_revision_cannot_be_replaced() -> None:
    first = task_case("same-revision")
    changed = task_case("same-revision", objective="changed bytes")
    registry = InMemoryRegistry((first,))
    with pytest.raises(RegistryResolutionError, match="cannot be overwritten"):
        registry.add(changed)


@pytest.mark.unit
@pytest.mark.parametrize("status", [LifecycleStatus.DRAFT, LifecycleStatus.REVOKED])
def test_inactive_lifecycle_stops_resolution(status: LifecycleStatus) -> None:
    envelope = task_case("inactive", status=status)
    with pytest.raises(RegistryResolutionError, match="lifecycle"):
        InMemoryRegistry((envelope,)).resolve(
            envelope.object_ref(),
            role=RegistryRole.EVALUATOR,
            intended_use=IntendedUse.DEVELOPMENT,
            now=NOW,
        )


@pytest.mark.unit
def test_expired_deleted_and_prohibited_objects_stop_resolution() -> None:
    expired = task_case("expired", expires_at="2026-09-04T15:59:59Z")
    deleted = task_case("deleted", deleted_at="2026-09-04T15:00:00Z")
    for envelope, message in ((expired, "expired"), (deleted, "deleted")):
        with pytest.raises(RegistryResolutionError, match=message):
            InMemoryRegistry((envelope,)).resolve(
                envelope.object_ref(),
                role=RegistryRole.EVALUATOR,
                intended_use=IntendedUse.DEVELOPMENT,
                now=NOW,
            )
    active = task_case("development-only")
    with pytest.raises(RegistryResolutionError, match="does not declare promotion"):
        InMemoryRegistry((active,)).resolve(
            active.object_ref(),
            role=RegistryRole.EVALUATOR,
            intended_use=IntendedUse.PROMOTION,
            now=NOW,
        )


@pytest.mark.unit
def test_restricted_splits_fail_closed_without_a_broker() -> None:
    graph = registry_graph(split_kind=SplitKind.VALIDATION)
    split = graph["split"]
    with pytest.raises(RestrictedRegistryUnavailable, match="requires a configured access broker"):
        memory_registry(graph).resolve(
            split.object_ref(),
            role=RegistryRole.EVALUATOR,
            intended_use=IntendedUse.DEVELOPMENT,
            now=NOW,
        )


@pytest.mark.unit
def test_candidate_cannot_resolve_labels_or_receive_evaluator_overlay() -> None:
    graph = registry_graph()
    registry = memory_registry(graph)
    case = registry.resolve(
        graph["case_a"].object_ref(),
        role=RegistryRole.CANDIDATE,
        intended_use=IntendedUse.DEVELOPMENT,
        now=NOW,
    )
    projection = project_for_role(case, RegistryRole.CANDIDATE)
    encoded = canonical_json(projection)
    assert "hidden-sentinel" not in encoded
    assert "evaluator_refs" not in encoded
    assert "contamination" not in encoded
    with pytest.raises(RegistryAccessError, match="candidate cannot resolve label_set"):
        registry.resolve(
            graph["labels"].object_ref(),
            role=RegistryRole.CANDIDATE,
            intended_use=IntendedUse.DEVELOPMENT,
            now=NOW,
        )


@pytest.mark.unit
def test_candidate_rubric_projection_filters_hidden_items() -> None:
    envelope = rubric()
    resolved = InMemoryRegistry((envelope,)).resolve(
        envelope.object_ref(),
        role=RegistryRole.CANDIDATE,
        intended_use=IntendedUse.DEVELOPMENT,
        now=NOW,
    )
    projected = project_for_role(resolved, RegistryRole.CANDIDATE)
    assert [item["rubric_item_id"] for item in projected["items"]] == ["claims.supported"]


@pytest.mark.unit
def test_unavailable_source_and_unsanitized_candidate_fixture_fail_closed() -> None:
    unavailable_source = seal_registry_object(
        SourceSnapshot(
            **governed(),
            snapshot_id="missing-source",
            source_ref=ref("source", "paper-feed"),
            accessed_at=NOW_TEXT,
            availability="retracted",
        )
    )
    with pytest.raises(RegistryResolutionError, match="not available: retracted"):
        InMemoryRegistry((unavailable_source,)).resolve(
            unavailable_source.object_ref(),
            role=RegistryRole.EVALUATOR,
            intended_use=IntendedUse.DEVELOPMENT,
            now=NOW,
        )

    unsanitized_fixture = seal_registry_object(
        FixtureSet(
            **governed(visibility=ObjectVisibility.CANDIDATE),
            fixture_set_id="unsafe-replay",
            observations=(
                FixtureObservation(
                    sequence=1,
                    observation_ref=ref("artifact", "raw-observation"),
                    tool_contract_ref=ref("tool_contract", "search-v1"),
                    sanitized=False,
                ),
            ),
        )
    )
    with pytest.raises(RegistryAccessError, match="unsanitized fixture"):
        InMemoryRegistry((unsanitized_fixture,)).resolve(
            unsanitized_fixture.object_ref(),
            role=RegistryRole.CANDIDATE,
            intended_use=IntendedUse.DEVELOPMENT,
            now=NOW,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "objective,message",
    [
        ("api_key=supersecretvalue", "secret-shaped"),
        ("Read /Users/example/private/eval.json", "private absolute path"),
    ],
)
def test_registry_safety_scan_precedes_resolution(objective: str, message: str) -> None:
    envelope = task_case("unsafe", objective=objective)
    with pytest.raises(RegistryAccessError, match=message):
        InMemoryRegistry((envelope,)).resolve(
            envelope.object_ref(),
            role=RegistryRole.EVALUATOR,
            intended_use=IntendedUse.DEVELOPMENT,
            now=NOW,
        )


@pytest.mark.unit
def test_split_disjointness_is_enforced() -> None:
    case_ref = task_case("shared").object_ref()
    development = SplitAssignment(
        **governed(visibility=ObjectVisibility.EVALUATOR),
        split_assignment_id="dev",
        split=SplitKind.DEVELOPMENT,
        case_refs=(case_ref,),
    )
    validation = development.model_copy(
        update={"split_assignment_id": "validation", "split": SplitKind.VALIDATION}
    )
    with pytest.raises(RegistryResolutionError, match="belongs to development and validation"):
        validate_split_disjointness((development, validation))


@pytest.mark.unit
def test_campaign_lock_is_deterministic_ordered_and_has_denominator() -> None:
    graph = registry_graph()
    registry = memory_registry(graph)
    first = generate_campaign_lock(
        registry,
        graph["suite"].object_ref(),
        case_ids=("case-b", "case-a"),
        repeats=3,
        intended_use=IntendedUse.DEVELOPMENT,
        source_mode=SourceMode.SNAPSHOT,
        now=NOW,
    )
    second = generate_campaign_lock(
        registry,
        graph["suite"].object_ref(),
        case_ids=("case-b", "case-a"),
        repeats=3,
        intended_use=IntendedUse.DEVELOPMENT,
        source_mode=SourceMode.SNAPSHOT,
        now=NOW,
    )
    assert first == second
    assert [item.id for item in first.case_refs] == ["case-b", "case-a"]
    assert first.expected_denominator == 6
    assert first.source_mode is SourceMode.SNAPSHOT
    assert first.exclusions == ()
    assert len(first.resolved_refs) == len(
        {(item.kind, item.id, item.revision) for item in first.resolved_refs}
    )
    receipt = validate_lock(first, validated_at=NOW_TEXT, validator_ref=VALIDATOR_REF)
    assert receipt.lock_digest.startswith("sha256:")
    assert receipt.resolved_object_count == len(first.resolved_refs)

    partial = generate_campaign_lock(
        registry,
        graph["suite"].object_ref(),
        case_ids=("case-a",),
        repeats=3,
        intended_use=IntendedUse.DEVELOPMENT,
        source_mode=SourceMode.SNAPSHOT,
        now=NOW,
    )
    live = partial.model_copy(update={"source_mode": SourceMode.LIVE})
    assert partial.exclusions == ("case-b",)
    assert validate_lock(
        live, validated_at=NOW_TEXT, validator_ref=VALIDATOR_REF
    ).lock_digest != validate_lock(
        partial, validated_at=NOW_TEXT, validator_ref=VALIDATOR_REF
    ).lock_digest


@pytest.mark.unit
def test_lock_rejects_selection_and_split_membership_errors() -> None:
    graph = registry_graph()
    registry = memory_registry(graph)
    with pytest.raises(RegistryResolutionError, match="absent from task set"):
        generate_campaign_lock(
            registry,
            graph["suite"].object_ref(),
            case_ids=("missing",),
            repeats=1,
            intended_use=IntendedUse.DEVELOPMENT,
            source_mode=SourceMode.SNAPSHOT,
            now=NOW,
        )
    mismatched = registry_graph(split_case_count=1)
    with pytest.raises(RegistryResolutionError, match="membership differ"):
        generate_campaign_lock(
            memory_registry(mismatched),
            mismatched["suite"].object_ref(),
            case_ids=("case-a",),
            repeats=1,
            intended_use=IntendedUse.DEVELOPMENT,
            source_mode=SourceMode.SNAPSHOT,
            now=NOW,
        )


@pytest.mark.unit
def test_local_resolver_uses_exact_content_addressed_path(tmp_path: Path) -> None:
    envelope = task_case("local-case")
    write_graph(tmp_path, {"case": envelope})
    resolved = LocalRegistry(tmp_path).resolve(
        envelope.object_ref(),
        role=RegistryRole.EVALUATOR,
        intended_use=IntendedUse.DEVELOPMENT,
        now=NOW,
    )
    assert resolved == envelope
    with pytest.raises(RegistryResolutionError, match="unavailable"):
        LocalRegistry(tmp_path).resolve(
            ref("task_case", "missing"),
            role=RegistryRole.EVALUATOR,
            intended_use=IntendedUse.DEVELOPMENT,
            now=NOW,
        )


@pytest.mark.unit
def test_read_only_cli_validate_resolve_and_lock(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    graph = registry_graph()
    write_graph(tmp_path, graph)
    case = graph["case_a"]
    case_ref = case.object_ref()
    case_path = tmp_path / case_ref.kind / case_ref.id / f"{case_ref.revision}.json"
    assert main(["validate", str(case_path)]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "case-a"

    assert main(
        [
            "resolve",
            str(tmp_path),
            *case_ref.model_dump(mode="json").values(),
            "--use",
            "development",
            "--role",
            "candidate",
        ]
    ) == 0
    resolved_output = capsys.readouterr().out
    assert "hidden-sentinel" not in resolved_output

    suite_ref = graph["suite"].object_ref()
    assert main(
        [
            "lock",
            str(tmp_path),
            *suite_ref.model_dump(mode="json").values(),
            "--use",
            "development",
            "--case",
            "case-a",
            "--repeats",
            "2",
            "--source-mode",
            "snapshot",
        ]
    ) == 0
    lock = CampaignLock.model_validate_json(capsys.readouterr().out)
    assert lock.expected_denominator == 2


@pytest.mark.unit
def test_schema_export_covers_every_registry_payload() -> None:
    schema = registry_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["$id"].endswith("/eval-registry/v1/envelope")
    for name in (
        "BenchmarkSuite",
        "TaskSet",
        "TaskCase",
        "RubricSet",
        "LabelSet",
        "SourceSnapshot",
        "FixtureSet",
        "SplitAssignment",
        "GraderProfile",
        "RetentionPolicy",
        "ExternalAdapter",
    ):
        assert name in schema["$defs"]


@pytest.mark.unit
def test_governance_requires_owner_and_noncontradictory_uses() -> None:
    payload = governed()
    payload["owners"] = ()
    with pytest.raises(ValidationError, match="owner"):
        GovernedPayload(**payload)
    payload = governed()
    payload["intended_uses"] = (IntendedUse.DEVELOPMENT,)
    payload["prohibited_uses"] = (IntendedUse.DEVELOPMENT,)
    with pytest.raises(ValidationError, match="cannot also be prohibited"):
        GovernedPayload(**payload)
