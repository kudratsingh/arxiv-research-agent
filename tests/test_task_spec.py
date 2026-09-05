"""No-cost qualification tests for TaskSpec v1 and shadow compilers."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from src.api.jobs import Job
from src.api.redis_store import _job_from_json, _job_to_json
from src.contracts.kernel import DataClass, ImmutableObjectRef, RetentionPolicyRef
from src.contracts.task_spec import (
    AcceptanceCheck,
    AutonomyPolicy,
    AutonomyTier,
    BenchmarkOrigin,
    ContextRef,
    CorpusMode,
    ExecutionLimits,
    FreshnessMode,
    FreshnessRequirement,
    GuidedSessionCompilerInput,
    HumanCheckpoint,
    InMemoryTaskSpecStore,
    PlatformPolicyCeiling,
    ProductSurface,
    ResearchCompilerInput,
    SourceScope,
    TaskDataPolicy,
    TaskKind,
    TaskPolicyBundle,
    TaskProvenance,
    TaskSpecError,
    TaskSpecRef,
    TaskSpecV1,
    ToolPolicy,
    WorkflowCostBoundary,
    agent_safe_task_projection,
    compile_benchmark_case,
    compile_guided_session,
    compile_research_request,
    control_plane_task_projection,
    full_task_digest,
    intersect_with_platform,
    persist_compiled_task,
    semantic_task_digest,
    shadow_job_compatibility,
    shadow_research_state_compatibility,
    shadow_session_state_compatibility,
    task_spec_json_schema,
)

NOW = "2026-09-05T08:00:00Z"
OTHER_TIME = "2026-09-05T09:00:00Z"


def ref(kind: str, object_id: str, *, digit: str = "a") -> ImmutableObjectRef:
    return ImmutableObjectRef(
        kind=kind,
        id=object_id,
        revision="1.0.0",
        digest="sha256:" + digit * 64,
    )


def retention_ref() -> RetentionPolicyRef:
    return RetentionPolicyRef(
        kind="retention_policy",
        id="task-artifacts",
        revision="1.0.0",
        digest="sha256:" + "9" * 64,
    )


def policy_bundle(
    *,
    corpus_mode: CorpusMode = CorpusMode.LIVE,
    data_class: DataClass = DataClass.PUBLIC,
    cost: str = "2.000000",
    hard_timeout: int = 900,
    max_tools: int = 50,
    max_models: int = 40,
) -> TaskPolicyBundle:
    snapshot_ref = (
        ref("source_snapshot", "frozen-corpus", digit="1")
        if corpus_mode is CorpusMode.SNAPSHOT
        else None
    )
    return TaskPolicyBundle(
        source_scope=SourceScope(
            policy_ref=ref("source_policy", "research-readonly", digit="2"),
            corpus_mode=corpus_mode,
            allowed_providers=("arxiv", "semantic_scholar")
            if corpus_mode is CorpusMode.LIVE
            else (),
            allowed_source_types=("paper", "paper_metadata"),
            snapshot_ref=snapshot_ref,
            minimum_distinct_sources=2,
        ),
        freshness=(
            FreshnessRequirement(mode=FreshnessMode.LATEST_AVAILABLE)
            if corpus_mode is CorpusMode.LIVE
            else FreshnessRequirement(mode=FreshnessMode.AS_OF, as_of=NOW)
        ),
        tool_policy=ToolPolicy(
            policy_ref=ref("tool_policy", "research-readonly", digit="3"),
            allowed_agent_tools=("arxiv_search", "pdf_reader", "semantic_scholar"),
            denied_action_ids=("repository_write", "deploy"),
            network_access="allowlisted" if corpus_mode is CorpusMode.LIVE else "none",
        ),
        execution_limits=ExecutionLimits(
            target_latency_seconds=600,
            hard_timeout_seconds=hard_timeout,
            max_tool_calls=max_tools,
            max_model_calls=max_models,
            workflow_cost=WorkflowCostBoundary(
                chargeable_work="requires_external_approval",
                workflow_spend_ceiling_usd=cost,
            ),
        ),
        autonomy=AutonomyPolicy(maximum_tier=AutonomyTier.A1_BOUNDED_TOOLS),
        data_policy=TaskDataPolicy(
            policy_ref=ref("data_policy", "product-no-training", digit="4"),
            data_class=data_class,
            processing_purposes=("product_operation", "aggregate_analytics"),
            retention_policy_ref=retention_ref(),
        ),
    )


def platform_policy(
    *,
    corpus_modes: tuple[CorpusMode, ...] = (
        CorpusMode.LIVE,
        CorpusMode.SNAPSHOT,
        CorpusMode.CURATED,
    ),
    minimum_data_class: DataClass = DataClass.INTERNAL,
    chargeable_work: Literal["forbidden", "requires_external_approval"] = (
        "requires_external_approval"
    ),
    cost: str = "1.250000",
) -> PlatformPolicyCeiling:
    return PlatformPolicyCeiling(
        allowed_corpus_modes=corpus_modes,
        allowed_providers=("arxiv",),
        allowed_source_types=("paper", "paper_metadata"),
        allowed_agent_tools=("arxiv_search", "pdf_reader"),
        denied_action_ids=("external_publish", "deploy"),
        network_access="allowlisted",
        maximum_autonomy_tier=AutonomyTier.A1_BOUNDED_TOOLS,
        hard_timeout_seconds=700,
        max_tool_calls=30,
        max_model_calls=20,
        chargeable_work=chargeable_work,
        workflow_spend_ceiling_usd=cost,
        minimum_data_class=minimum_data_class,
        allowed_processing_purposes=("product_operation",),
    )


def compiler_ref() -> ImmutableObjectRef:
    return ref("task_compiler", "deterministic-v1", digit="5")


def research_spec(
    *,
    compiled_at: str = NOW,
    conversation_ref: ImmutableObjectRef | None = None,
    task_revision: int = 1,
    supersedes: str | None = None,
) -> TaskSpecV1:
    return compile_research_request(
        ResearchCompilerInput(
            task_id="research:job-123",
            query="  Compare retrieval techniques exactly as written.  ",
            conversation_summary_ref=conversation_ref,
            hitl_plan_review=True,
            task_revision=task_revision,
            supersedes_task_spec_id=supersedes,
        ),
        requested_policy=policy_bundle(),
        platform_policy=platform_policy(),
        compiler_ref=compiler_ref(),
        compiled_at=compiled_at,
    )


@pytest.mark.unit
def test_research_compiler_is_deterministic_and_preserves_intent() -> None:
    conversation = ref("conversation_summary", "conversation-42", digit="6")
    first = research_spec(conversation_ref=conversation)
    second = research_spec(compiled_at=OTHER_TIME, conversation_ref=conversation)

    # Pydantic's shared strip policy trims transport whitespace; no model or
    # classifier rewrites the validated objective.
    assert first.objective == "Compare retrieval techniques exactly as written."
    assert first.task_kind is TaskKind.RESEARCH_FOCUSED_EVIDENCE_REVIEW
    assert first.task_spec_id != second.task_spec_id
    assert semantic_task_digest(first) == semantic_task_digest(second)
    assert full_task_digest(first) != full_task_digest(second)
    assert [context.object_ref for context in first.context_refs] == [conversation]
    assert first.execution_limits.hard_timeout_seconds == 700
    assert first.execution_limits.max_tool_calls == 30
    assert first.execution_limits.max_model_calls == 20
    assert first.execution_limits.workflow_cost.workflow_spend_ceiling_usd == "1.250000"
    assert first.data_policy.data_class is DataClass.INTERNAL
    assert first.data_policy.processing_purposes == ("product_operation",)
    assert first.tool_policy.allowed_agent_tools == ("arxiv_search", "pdf_reader")
    assert set(first.tool_policy.denied_action_ids) == {
        "repository_write",
        "deploy",
        "external_publish",
    }


@pytest.mark.unit
def test_research_hitl_bypass_and_principal_stay_outside_task() -> None:
    spec = research_spec()
    encoded = json.dumps(spec.model_dump(mode="json"), sort_keys=True)
    assert "hitl_bypass" not in encoded
    assert "principal_key_id" not in encoded
    assert [item.kind for item in spec.autonomy.human_checkpoints] == ["plan_review"]


@pytest.mark.unit
def test_guided_compiler_uses_refs_not_profile_or_content_prose() -> None:
    request = GuidedSessionCompilerInput(
        task_id="session:abc123",
        path_id="foundations",
        resource_id="attention-paper",
        title="Attention Is All You Need",
        available_minutes=10,
        content_entry_ref=ref("content_entry", "attention-paper", digit="6"),
        learner_profile_snapshot_ref=ref("learner_profile_snapshot", "profile-abc", digit="7"),
        prior_session_summary_ref=ref("prior_session_summary", "prior-session", digit="8"),
    )
    requested = policy_bundle(corpus_mode=CorpusMode.CURATED)
    spec = compile_guided_session(
        request,
        requested_policy=requested,
        platform_policy=platform_policy(minimum_data_class=DataClass.PUBLIC),
        compiler_ref=compiler_ref(),
        compiled_at=NOW,
    )
    encoded = json.dumps(spec.model_dump(mode="json"), sort_keys=True)
    assert spec.task_kind is TaskKind.LEARNING_GUIDED_READING
    assert spec.data_policy.data_class is DataClass.LEARNER_SENSITIVE
    assert spec.execution_limits.target_latency_seconds == 600
    assert [context.kind for context in spec.context_refs] == [
        "content_entry",
        "learner_profile_snapshot",
        "prior_session_summary",
    ]
    assert "profile note" not in encoded
    assert "principal-key-123" not in encoded
    assert {check.metric_key for check in spec.acceptance_checks}.isdisjoint(
        {"task_rubric_success", "supported_claim_precision", "citation_validity"}
    )


@pytest.mark.unit
def test_platform_intersection_never_broadens_permissions() -> None:
    requested = policy_bundle()
    effective = intersect_with_platform(requested, platform_policy())
    assert set(effective.source_scope.allowed_providers) <= set(
        requested.source_scope.allowed_providers
    )
    assert set(effective.tool_policy.allowed_agent_tools) <= set(
        requested.tool_policy.allowed_agent_tools
    )
    assert effective.autonomy.maximum_tier.rank <= requested.autonomy.maximum_tier.rank
    assert (
        effective.execution_limits.hard_timeout_seconds
        <= requested.execution_limits.hard_timeout_seconds
    )
    assert effective.execution_limits.max_tool_calls <= requested.execution_limits.max_tool_calls
    assert effective.execution_limits.max_model_calls <= requested.execution_limits.max_model_calls
    assert Decimal(effective.execution_limits.workflow_cost.workflow_spend_ceiling_usd) <= Decimal(
        requested.execution_limits.workflow_cost.workflow_spend_ceiling_usd
    )
    assert effective.data_policy.data_class >= requested.data_policy.data_class
    assert set(effective.data_policy.processing_purposes) <= set(
        requested.data_policy.processing_purposes
    )


@pytest.mark.unit
def test_forbidden_platform_cost_forces_zero_and_no_chargeable_authority() -> None:
    effective = intersect_with_platform(
        policy_bundle(),
        platform_policy(chargeable_work="forbidden", cost="0.000000"),
    )
    assert effective.execution_limits.workflow_cost.chargeable_work == "forbidden"
    assert effective.execution_limits.workflow_cost.workflow_spend_ceiling_usd == "0.000000"


@pytest.mark.unit
def test_empty_or_disallowed_policy_intersections_fail_closed() -> None:
    with pytest.raises(TaskSpecError, match="corpus mode"):
        intersect_with_platform(
            policy_bundle(),
            platform_policy(corpus_modes=(CorpusMode.SNAPSHOT,)),
        )
    platform = platform_policy().model_copy(update={"allowed_providers": ("other",)})
    with pytest.raises(TaskSpecError, match="provider intersection"):
        intersect_with_platform(policy_bundle(), platform)


@pytest.mark.unit
def test_benchmark_compiler_reuses_one_identity_and_accepts_no_evaluator_overlay() -> None:
    origin = BenchmarkOrigin(
        suite_ref=ref("benchmark_suite", "research-policy-v1", digit="6"),
        task_set_ref=ref("task_set", "research-tasks", digit="7"),
        task_case_ref=ref("task_case", "case-a", digit="8"),
    )

    def compile_once() -> TaskSpecV1:
        return compile_benchmark_case(
            task_id="research-policy-v1:case-a",
            task_kind=TaskKind.RESEARCH_METHOD_COMPARISON,
            objective="Compare two methods.",
            candidate_visible_refs=(ref("source_snapshot", "public-case", digit="1"),),
            origin=origin,
            product_surface=ProductSurface.RESEARCH_EVAL,
            requested_policy=policy_bundle(corpus_mode=CorpusMode.SNAPSHOT),
            platform_policy=platform_policy(),
            compiler_ref=compiler_ref(),
            compiled_at=NOW,
        )

    first = compile_once()
    second = compile_once()
    assert first == second
    assert first.benchmark_origin == origin
    assert {item.kind.value for item in first.deliverables} == {
        "research_report",
        "comparison_matrix",
    }
    runtime = json.dumps(agent_safe_task_projection(first), sort_keys=True)
    assert "benchmark_origin" not in runtime
    assert "grader" not in runtime
    assert "label" not in runtime
    assert "evaluator" not in runtime


@pytest.mark.unit
def test_runtime_and_control_plane_projections_have_distinct_boundaries() -> None:
    spec = research_spec(conversation_ref=ref("conversation_summary", "conversation-42"))
    runtime = agent_safe_task_projection(spec)
    control = control_plane_task_projection(spec)
    assert "provenance" not in runtime
    assert "benchmark_origin" not in runtime
    assert all("locator" not in context for context in runtime["context_refs"])
    assert control["task_spec"]["provenance"]["source_id"] == "research:job-123"
    assert control["full_digest"] == full_task_digest(spec)
    assert control["semantic_digest"] == semantic_task_digest(spec)


@pytest.mark.unit
def test_immutable_store_and_compilation_receipt() -> None:
    store = InMemoryTaskSpecStore()
    spec = research_spec()
    receipt = persist_compiled_task(spec, store)
    assert store.get(spec.task_spec_id) == spec
    assert receipt.task_spec_ref.full_digest == full_task_digest(spec)
    assert receipt.task_spec_ref.semantic_digest == semantic_task_digest(spec)
    assert receipt.task_spec_ref.effective_data_class is DataClass.INTERNAL
    assert receipt.task_spec_ref.artifact_ref.digest == receipt.task_spec_ref.full_digest
    persist_compiled_task(spec, store)

    tampered = spec.model_copy(update={"objective": "Different objective"})
    with pytest.raises(TaskSpecError, match="cannot be overwritten"):
        store.put(tampered)


@pytest.mark.unit
def test_revision_requires_and_resolves_exact_supersession() -> None:
    store = InMemoryTaskSpecStore()
    first = research_spec()
    store.put(first)
    second = research_spec(task_revision=2, supersedes=first.task_spec_id)
    assert second.task_spec_id != first.task_spec_id
    assert semantic_task_digest(second) == semantic_task_digest(first)
    store.put(second)
    assert store.get(second.task_spec_id) == second

    wrong = research_spec(task_revision=3, supersedes=first.task_spec_id)
    with pytest.raises(TaskSpecError, match="stored prior revision"):
        store.put(wrong)


@pytest.mark.unit
@pytest.mark.parametrize(
    "update,message",
    [
        ({"task_kind": TaskKind.RESEARCH_LONG_HORIZON}, "not executable"),
        (
            {
                "benchmark_origin": BenchmarkOrigin(
                    suite_ref=ref("benchmark_suite", "suite"),
                    task_set_ref=ref("task_set", "tasks"),
                    task_case_ref=ref("task_case", "case"),
                )
            },
            "cannot claim benchmark origin",
        ),
    ],
)
def test_task_semantics_reject_reserved_or_cross_boundary_fields(
    update: dict[str, Any], message: str
) -> None:
    payload = research_spec().model_dump(mode="python")
    payload.update(update)
    with pytest.raises(ValidationError, match=message):
        TaskSpecV1.model_validate(payload)


@pytest.mark.unit
def test_semantics_reject_missing_deliverables_checks_and_zero_call_execution() -> None:
    spec = research_spec()
    missing_deliverable = spec.model_dump(mode="python")
    missing_deliverable["deliverables"] = (spec.deliverables[0],)
    missing_deliverable["acceptance_checks"] = tuple(
        item.model_copy(update={"subject_deliverable_ids": ("del_report",)})
        for item in spec.acceptance_checks
    )
    with pytest.raises(ValidationError, match="missing required deliverables"):
        TaskSpecV1.model_validate(missing_deliverable)

    missing_non_regression = spec.model_dump(mode="python")
    missing_non_regression["acceptance_checks"] = tuple(
        item for item in spec.acceptance_checks if item.metric_key != "budget_adherence"
    )
    with pytest.raises(ValidationError, match="missing product non-regression"):
        TaskSpecV1.model_validate(missing_non_regression)

    zero_calls = spec.model_dump(mode="python")
    zero_calls["execution_limits"] = spec.execution_limits.model_copy(
        update={"max_tool_calls": 0, "max_model_calls": 0}
    )
    with pytest.raises(ValidationError, match="at least one model or tool call"):
        TaskSpecV1.model_validate(zero_calls)


@pytest.mark.unit
def test_source_freshness_and_cost_combinations_are_closed() -> None:
    with pytest.raises(ValidationError, match="snapshot mode requires"):
        SourceScope(
            policy_ref=ref("source_policy", "policy"),
            corpus_mode=CorpusMode.SNAPSHOT,
            allowed_providers=(),
            allowed_source_types=("paper",),
        )
    with pytest.raises(ValidationError, match="supplied mode requires"):
        SourceScope(
            policy_ref=ref("source_policy", "policy"),
            corpus_mode=CorpusMode.SUPPLIED,
            allowed_providers=(),
            allowed_source_types=("paper",),
        )
    with pytest.raises(ValidationError, match="as_of freshness"):
        FreshnessRequirement(mode=FreshnessMode.AS_OF)
    with pytest.raises(ValidationError, match="must not follow"):
        SourceScope(
            policy_ref=ref("source_policy", "policy"),
            corpus_mode=CorpusMode.LIVE,
            allowed_providers=("arxiv",),
            allowed_source_types=("paper",),
            publication_not_before=date(2026, 9, 5),
            publication_not_after=date(2026, 9, 4),
        )
    with pytest.raises(ValidationError, match="zero spend ceiling"):
        WorkflowCostBoundary(
            chargeable_work="forbidden",
            workflow_spend_ceiling_usd="1.000000",
        )


@pytest.mark.unit
def test_unknown_fields_duplicate_ids_and_missing_subjects_fail() -> None:
    payload = research_spec().model_dump(mode="python")
    payload["unknown"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        TaskSpecV1.model_validate(payload)

    spec = research_spec()
    duplicate = spec.model_dump(mode="python")
    duplicate["acceptance_checks"] = (*spec.acceptance_checks, spec.acceptance_checks[0])
    with pytest.raises(ValidationError, match="check ids must be unique"):
        TaskSpecV1.model_validate(duplicate)

    bad_subject = spec.model_dump(mode="python")
    original = spec.acceptance_checks[0]
    bad_subject["acceptance_checks"] = (
        AcceptanceCheck(
            **{
                **original.model_dump(mode="python"),
                "subject_deliverable_ids": ("del_missing",),
            }
        ),
        *spec.acceptance_checks[1:],
    )
    with pytest.raises(ValidationError, match="missing deliverables"):
        TaskSpecV1.model_validate(bad_subject)


@pytest.mark.unit
def test_shadow_adapters_map_intake_and_exclude_runtime_or_private_state() -> None:
    spec = research_spec()
    legacy = Job(job_id="legacy-job", query=spec.objective)
    legacy_binding = shadow_job_compatibility(legacy)
    assert legacy_binding.task_spec_id is None
    assert "hitl_bypass" in legacy_binding.excluded_fields
    assert "principal_key_id" in legacy_binding.excluded_fields

    receipt = persist_compiled_task(spec, InMemoryTaskSpecStore())
    bound = shadow_job_compatibility(legacy, receipt.task_spec_ref)
    assert bound.task_spec_id == spec.task_spec_id
    research_state = shadow_research_state_compatibility(
        spec, {"query": spec.objective, "prior_context": "runtime-only raw text"}
    )
    assert "papers" in research_state.excluded_fields
    assert "prior_context_ref" in research_state.mapped_fields

    guided_request = GuidedSessionCompilerInput(
        task_id="session:abc123",
        path_id="foundations",
        resource_id="paper",
        title="A Paper",
        available_minutes=10,
        content_entry_ref=ref("content_entry", "paper"),
        learner_profile_snapshot_ref=ref("learner_profile_snapshot", "profile"),
    )
    guided = compile_guided_session(
        guided_request,
        requested_policy=policy_bundle(corpus_mode=CorpusMode.CURATED),
        platform_policy=platform_policy(minimum_data_class=DataClass.PUBLIC),
        compiler_ref=compiler_ref(),
        compiled_at=NOW,
    )
    session = shadow_session_state_compatibility(guided, {"query": guided.objective})
    assert "tier1_raw" in session.excluded_fields
    assert "learner_reply" in session.excluded_fields
    with pytest.raises(TaskSpecError, match="diverges"):
        shadow_research_state_compatibility(spec, {"query": "changed"})


@pytest.mark.unit
def test_job_task_ref_is_additive_and_legacy_redis_rows_read_as_null() -> None:
    spec = research_spec()
    task_ref = persist_compiled_task(spec, InMemoryTaskSpecStore()).task_spec_ref
    job = Job(
        job_id="new-job",
        query=spec.objective,
        task_spec_ref=task_ref.model_dump(mode="json"),
    )
    assert _job_from_json(_job_to_json(job)).task_spec_ref == job.task_spec_ref

    legacy_payload = json.loads(_job_to_json(Job(job_id="legacy", query="old")))
    legacy_payload.pop("task_spec_ref")
    rebuilt = _job_from_json(json.dumps(legacy_payload))
    assert rebuilt.task_spec_ref is None


@pytest.mark.unit
def test_schema_export_is_strict_and_complete() -> None:
    schema = task_spec_json_schema()
    assert schema["$id"].endswith("/task-spec/v1")
    assert schema["additionalProperties"] is False
    assert {
        "AcceptanceCheck",
        "AutonomyPolicy",
        "BenchmarkOrigin",
        "ExecutionLimits",
        "SourceScope",
        "TaskDataPolicy",
        "TaskProvenance",
        "ToolPolicy",
    } <= set(schema["$defs"])


@pytest.mark.unit
def test_compile_path_has_no_model_network_or_environment_inputs() -> None:
    spec = research_spec()
    encoded = json.dumps(spec.model_dump(mode="json"), sort_keys=True)
    assert "api_key" not in encoded
    assert "approval_token" not in encoded
    assert "sk-secret-value" not in encoded
    assert spec.execution_limits.workflow_cost.chargeable_work == "requires_external_approval"
    assert not hasattr(spec, "model_route")
    assert not hasattr(spec, "agent_policy")
    assert not hasattr(spec, "seed")


@pytest.mark.unit
@pytest.mark.parametrize(
    "query,message",
    [
        ("Investigate api_key=supersecretvalue", "secret-shaped"),
        ("Read /Users/example/private/source.pdf", "private absolute path"),
    ],
)
def test_compiler_rejects_secret_material_and_private_paths(query: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        compile_research_request(
            ResearchCompilerInput(
                task_id="research:unsafe",
                query=query,
                hitl_plan_review=False,
            ),
            requested_policy=policy_bundle(),
            platform_policy=platform_policy(),
            compiler_ref=compiler_ref(),
            compiled_at=NOW,
        )


@pytest.mark.unit
def test_nested_contract_validators_reject_ambiguous_shapes() -> None:
    check = research_spec().acceptance_checks[0]
    with pytest.raises(ValidationError, match="at least one subject"):
        AcceptanceCheck(**{**check.model_dump(mode="python"), "subject_deliverable_ids": ()})
    with pytest.raises(ValidationError, match="subjects must be unique"):
        AcceptanceCheck(
            **{
                **check.model_dump(mode="python"),
                "subject_deliverable_ids": ("del_report", "del_report"),
            }
        )
    with pytest.raises(ValidationError, match="rubric_item kind"):
        AcceptanceCheck(
            **{
                **check.model_dump(mode="python"),
                "rubric_item_ref": ref("label_set", "hidden-labels"),
            }
        )

    live = policy_bundle().source_scope
    for source_update, message in (
        ({"policy_ref": ref("tool_policy", "wrong")}, "source_policy kind"),
        ({"allowed_providers": ("arxiv", "arxiv")}, "providers must be unique"),
        ({"allowed_source_types": ("paper", "paper")}, "types must be unique"),
        ({"allowed_providers": ()}, "requires an allowed provider"),
        ({"snapshot_ref": ref("source_snapshot", "unexpected")}, "cannot carry frozen"),
    ):
        with pytest.raises(ValidationError, match=message):
            SourceScope.model_validate({**live.model_dump(mode="python"), **source_update})

    snapshot = policy_bundle(corpus_mode=CorpusMode.SNAPSHOT).source_scope
    with pytest.raises(ValidationError, match="source_snapshot kind"):
        SourceScope.model_validate(
            {
                **snapshot.model_dump(mode="python"),
                "snapshot_ref": ref("artifact", "not-a-snapshot"),
            }
        )
    supplied = SourceScope(
        policy_ref=ref("source_policy", "supplied"),
        corpus_mode=CorpusMode.SUPPLIED,
        allowed_providers=(),
        allowed_source_types=("paper",),
        supplied_corpus_refs=(ref("artifact", "paper"),),
    )
    with pytest.raises(ValidationError, match="must be unique"):
        SourceScope.model_validate(
            {
                **supplied.model_dump(mode="python"),
                "supplied_corpus_refs": (*supplied.supplied_corpus_refs,) * 2,
            }
        )

    with pytest.raises(ValidationError, match="max_age_days freshness"):
        FreshnessRequirement(mode=FreshnessMode.MAX_AGE_DAYS)
    with pytest.raises(ValidationError, match="accepts no parameter"):
        FreshnessRequirement(mode=FreshnessMode.NO_REQUIREMENT, as_of=NOW)


@pytest.mark.unit
def test_tool_checkpoint_data_and_provenance_validators_fail_closed() -> None:
    tool = policy_bundle().tool_policy
    for tool_update, message in (
        ({"policy_ref": ref("source_policy", "wrong")}, "tool_policy kind"),
        ({"allowed_agent_tools": ("pdf_reader", "pdf_reader")}, "tools must be unique"),
        ({"denied_action_ids": ("deploy", "deploy")}, "actions must be unique"),
        (
            {
                "allowed_agent_tools": ("pdf_reader",),
                "denied_action_ids": ("pdf_reader",),
            },
            "both allowed and denied",
        ),
    ):
        with pytest.raises(ValidationError, match=message):
            ToolPolicy.model_validate({**tool.model_dump(mode="python"), **tool_update})

    with pytest.raises(ValidationError, match="target latency"):
        ExecutionLimits(
            target_latency_seconds=11,
            hard_timeout_seconds=10,
            max_tool_calls=1,
            max_model_calls=1,
            workflow_cost=WorkflowCostBoundary(
                chargeable_work="forbidden",
                workflow_spend_ceiling_usd="0.000000",
            ),
        )
    with pytest.raises(ValidationError, match="requires condition_code"):
        HumanCheckpoint(
            checkpoint_id="hcp_conditional",
            kind="clarification",
            trigger="on_condition",
        )
    with pytest.raises(ValidationError, match="cannot carry condition_code"):
        HumanCheckpoint(
            checkpoint_id="hcp_always",
            kind="clarification",
            trigger="always",
            condition_code="unexpected",
        )
    checkpoint = HumanCheckpoint(
        checkpoint_id="hcp_duplicate", kind="clarification", trigger="always"
    )
    with pytest.raises(ValidationError, match="checkpoint ids must be unique"):
        AutonomyPolicy(
            maximum_tier=AutonomyTier.A1_BOUNDED_TOOLS,
            human_checkpoints=(checkpoint, checkpoint),
        )

    with pytest.raises(ValidationError, match="incompatible"):
        ContextRef(
            object_ref=ref("label_set", "labels"),
            kind="conversation_summary",
            purpose="Wrong type.",
        )
    data_policy = policy_bundle().data_policy
    for data_update, message in (
        ({"policy_ref": ref("source_policy", "wrong")}, "data_policy kind"),
        ({"processing_purposes": ()}, "at least one processing purpose"),
        (
            {"processing_purposes": ("product_operation", "product_operation")},
            "purposes must be unique",
        ),
    ):
        with pytest.raises(ValidationError, match=message):
            TaskDataPolicy.model_validate({**data_policy.model_dump(mode="python"), **data_update})
    with pytest.raises(ValidationError, match="task_compiler kind"):
        TaskProvenance(
            compiler_ref=ref("tool_policy", "wrong"),
            source_kind="api_request",
            source_id="request",
            compiled_at=NOW,
        )


@pytest.mark.unit
def test_task_level_revision_lane_and_authority_invariants() -> None:
    spec = research_spec()

    def rejected(update: dict[str, Any], message: str) -> None:
        with pytest.raises(ValidationError, match=message):
            TaskSpecV1.model_validate({**spec.model_dump(mode="python"), **update})

    other_id = "tsp_" + "b" * 20
    rejected({"supersedes_task_spec_id": other_id}, "revision 1 cannot supersede")
    rejected({"task_revision": 2}, "must identify the superseded")
    rejected(
        {"task_revision": 2, "supersedes_task_spec_id": spec.task_spec_id},
        "cannot supersede itself",
    )
    rejected(
        {"deliverables": (*spec.deliverables, spec.deliverables[0])},
        "deliverable ids must be unique",
    )
    rejected(
        {
            "acceptance_checks": tuple(
                check.model_copy(update={"check_class": "diagnostic"})
                for check in spec.acceptance_checks
            )
        },
        "primary outcome",
    )
    rejected(
        {"product_surface": ProductSurface.GUIDED_LEARNING_API},
        "different product lanes",
    )
    context = ContextRef(
        object_ref=ref("conversation_summary", "same-context"),
        kind="conversation_summary",
        purpose="Prior report summary.",
    )
    rejected({"context_refs": (context, context)}, "context ids must be unique")
    rejected(
        {"autonomy": AutonomyPolicy(maximum_tier=AutonomyTier.A0_DRAFT)},
        "A0 tasks cannot allow tool calls",
    )
    rejected(
        {"tool_policy": spec.tool_policy.model_copy(update={"network_access": "none"})},
        "live sources require",
    )
    rejected(
        {"product_surface": ProductSurface.RESEARCH_EVAL},
        "evaluation tasks require",
    )


@pytest.mark.unit
def test_platform_and_reference_contract_edges() -> None:
    platform = platform_policy()
    with pytest.raises(ValidationError, match="collections must be unique"):
        PlatformPolicyCeiling.model_validate(
            {
                **platform.model_dump(mode="python"),
                "allowed_agent_tools": ("pdf_reader", "pdf_reader"),
            }
        )
    with pytest.raises(ValidationError, match="zero ceiling"):
        PlatformPolicyCeiling.model_validate(
            {
                **platform.model_dump(mode="python"),
                "chargeable_work": "forbidden",
            }
        )

    with pytest.raises(TaskSpecError, match="source type intersection"):
        intersect_with_platform(
            policy_bundle(),
            platform.model_copy(update={"allowed_source_types": ("dataset",)}),
        )
    with pytest.raises(TaskSpecError, match="processing-purpose intersection"):
        intersect_with_platform(
            policy_bundle(),
            platform.model_copy(update={"allowed_processing_purposes": ("support",)}),
        )
    a0 = intersect_with_platform(
        policy_bundle(),
        platform.model_copy(update={"maximum_autonomy_tier": AutonomyTier.A0_DRAFT}),
    )
    assert a0.autonomy.maximum_tier is AutonomyTier.A0_DRAFT
    assert a0.tool_policy.allowed_agent_tools == ()
    assert a0.execution_limits.max_tool_calls == 0
    assert AutonomyTier.most_restrictive(AutonomyTier.A3_PROPOSE_SIDE_EFFECT) is (
        AutonomyTier.A3_PROPOSE_SIDE_EFFECT
    )
    with pytest.raises(ValueError, match="at least one autonomy"):
        AutonomyTier.most_restrictive()

    task_ref = persist_compiled_task(research_spec(), InMemoryTaskSpecStore()).task_spec_ref
    with pytest.raises(ValidationError, match="task_spec kind"):
        TaskSpecRef.model_validate(
            {
                **task_ref.model_dump(mode="python"),
                "artifact_ref": ref("artifact", "wrong"),
            }
        )
    with pytest.raises(ValidationError, match="private absolute paths"):
        TaskSpecRef.model_validate(
            {
                **task_ref.model_dump(mode="python"),
                "artifact_locator": "/Users/example/private/task.json",
            }
        )


@pytest.mark.unit
def test_all_executable_benchmark_shapes_and_shadow_lane_guards() -> None:
    origin = BenchmarkOrigin(
        suite_ref=ref("benchmark_suite", "suite"),
        task_set_ref=ref("task_set", "tasks"),
        task_case_ref=ref("task_case", "case"),
    )
    quick = compile_benchmark_case(
        task_id="suite:quick",
        task_kind=TaskKind.RESEARCH_QUICK_ANSWER,
        objective="Answer briefly.",
        candidate_visible_refs=(),
        origin=origin,
        product_surface=ProductSurface.RESEARCH_EVAL,
        requested_policy=policy_bundle(corpus_mode=CorpusMode.SNAPSHOT),
        platform_policy=platform_policy(),
        compiler_ref=compiler_ref(),
        compiled_at=NOW,
    )
    assert [item.kind.value for item in quick.deliverables] == ["answer"]

    learning = compile_benchmark_case(
        task_id="suite:learning",
        task_kind=TaskKind.LEARNING_GUIDED_READING,
        objective="Guide the learner.",
        candidate_visible_refs=(),
        origin=origin,
        product_surface=ProductSurface.LEARNING_EVAL,
        requested_policy=policy_bundle(corpus_mode=CorpusMode.CURATED),
        platform_policy=platform_policy(minimum_data_class=DataClass.PUBLIC),
        compiler_ref=compiler_ref(),
        compiled_at=NOW,
    )
    assert [item.kind.value for item in learning.deliverables] == [
        "guided_session",
        "session_summary",
    ]
    with pytest.raises(TaskSpecError, match="does not match"):
        compile_benchmark_case(
            task_id="suite:mismatch",
            task_kind=TaskKind.LEARNING_GUIDED_READING,
            objective="Wrong lane.",
            candidate_visible_refs=(),
            origin=origin,
            product_surface=ProductSurface.RESEARCH_EVAL,
            requested_policy=policy_bundle(corpus_mode=CorpusMode.CURATED),
            platform_policy=platform_policy(),
            compiler_ref=compiler_ref(),
            compiled_at=NOW,
        )

    assert (
        "input_payload.session_spec"
        in shadow_job_compatibility(
            Job(job_id="session", query=learning.objective, kind="session")
        ).mapped_fields
    )
    with pytest.raises(TaskSpecError, match="research state"):
        shadow_research_state_compatibility(learning, {"query": learning.objective})
    with pytest.raises(TaskSpecError, match="session state"):
        shadow_session_state_compatibility(quick, {"query": quick.objective})
    with pytest.raises(TaskSpecError, match="diverges"):
        shadow_session_state_compatibility(learning, {"query": "changed"})


@pytest.mark.unit
def test_store_refuses_two_specs_for_one_logical_revision() -> None:
    store = InMemoryTaskSpecStore()
    original = research_spec()
    store.put(original)
    competing = original.model_copy(update={"task_spec_id": "tsp_" + "c" * 20})
    with pytest.raises(TaskSpecError, match="logical task revision"):
        store.put(competing)
