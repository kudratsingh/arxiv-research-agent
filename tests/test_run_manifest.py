"""No-cost qualification for immutable run manifests and admission."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import ValidationError

import src.contracts.run_manifest as run_manifest_module
from src.contracts.kernel import DataClass, ImmutableObjectRef, RetentionPolicyRef, sha256_digest
from src.contracts.run_manifest import (
    AdmissionPlan,
    ApprovalRecord,
    ApprovalScope,
    ApprovalSnapshot,
    ApprovalStatus,
    AttemptReceipt,
    BudgetSnapshot,
    CampaignBudget,
    CheckpointCompatibility,
    CodeSnapshot,
    CompilationSnapshot,
    CompletionReceipt,
    CompletionStatus,
    CredentialBinding,
    DeterminismClass,
    EnvironmentSnapshot,
    EpisodeBudget,
    EvaluationBudget,
    EvaluationSnapshot,
    FakeLocalApprovalBackend,
    InvocationSnapshot,
    LlmProviderSnapshot,
    ManifestFileStore,
    OutputSnapshot,
    PolicyCapabilities,
    PolicyConfig,
    PolicyProviderProjection,
    PolicyRuntimeProjectionPayload,
    PolicyRuntimeProjectionRef,
    PolicySnapshot,
    PricingSnapshot,
    PrivacySnapshot,
    PromptSnapshot,
    ProviderSnapshot,
    RandomnessSnapshot,
    RegistryResolution,
    RetrySnapshot,
    RunIdentity,
    RunLineage,
    RunManifestError,
    RunManifestPayload,
    RunManifestV1,
    RunReason,
    RuntimeConfigSnapshot,
    RuntimeFlags,
    SamplingSnapshot,
    SourceSnapshot,
    ToolSnapshot,
    build_policy_runtime_projection,
    derive_episode_key,
    derive_replicate_group_id,
    import_legacy_eval,
    manifest_compatibility,
    new_attempt_id,
    new_run_id,
    resolve_admission,
    run_artifact_json_schemas,
    run_manifest_json_schema,
    seal_manifest,
    validate_arm_matrix,
    validate_manifest_safe_content,
    validate_resume,
)
from src.contracts.task_spec import (
    AutonomyPolicy,
    AutonomyTier,
    CorpusMode,
    ExecutionLimits,
    FreshnessMode,
    FreshnessRequirement,
    HumanCheckpoint,
    PlatformPolicyCeiling,
    ResearchCompilerInput,
    SourceScope,
    TaskDataPolicy,
    TaskPolicyBundle,
    ToolPolicy,
    WorkflowCostBoundary,
    agent_safe_task_projection,
    build_task_spec_ref,
    compile_research_request,
)

NOW = "2026-09-05T08:00:00Z"
LATER = "2026-09-06T08:00:00Z"
VALID_DIGEST = "sha256:" + "a" * 64


def ref(kind: str, object_id: str, digit: str = "a") -> ImmutableObjectRef:
    return ImmutableObjectRef(
        kind=kind,
        id=object_id,
        revision="1.0.0",
        digest="sha256:" + digit * 64,
    )


def retention_ref() -> RetentionPolicyRef:
    return RetentionPolicyRef(
        kind="retention_policy",
        id="eval-default",
        revision="1.0.0",
        digest="sha256:" + "9" * 64,
    )


def policy_bundle(
    *,
    chargeable: bool = False,
    cost: str = "0.000000",
    tools: tuple[str, ...] = ("arxiv_search", "pdf_reader"),
) -> TaskPolicyBundle:
    return TaskPolicyBundle(
        source_scope=SourceScope(
            policy_ref=ref("source_policy", "controlled-research", "1"),
            corpus_mode=CorpusMode.SNAPSHOT,
            allowed_providers=(),
            allowed_source_types=("paper", "paper_metadata"),
            snapshot_ref=ref("source_snapshot", "controlled-corpus", "2"),
            minimum_distinct_sources=2,
        ),
        freshness=FreshnessRequirement(mode=FreshnessMode.AS_OF, as_of=NOW),
        tool_policy=ToolPolicy(
            policy_ref=ref("tool_policy", "bounded-research", "3"),
            allowed_agent_tools=tools,
            denied_action_ids=("repository_write", "deploy", "send_message"),
            network_access="none",
        ),
        execution_limits=ExecutionLimits(
            hard_timeout_seconds=600,
            max_tool_calls=50,
            max_model_calls=40,
            workflow_cost=WorkflowCostBoundary(
                chargeable_work=(
                    "requires_external_approval" if chargeable else "forbidden"
                ),
                workflow_spend_ceiling_usd=cost,
            ),
        ),
        autonomy=AutonomyPolicy(maximum_tier=AutonomyTier.A1_BOUNDED_TOOLS),
        data_policy=TaskDataPolicy(
            policy_ref=ref("data_policy", "no-training", "4"),
            data_class=DataClass.INTERNAL,
            processing_purposes=("product_operation",),
            retention_policy_ref=retention_ref(),
        ),
    )


def platform_policy(*, chargeable: bool = False, cost: str = "0.000000") -> PlatformPolicyCeiling:
    return PlatformPolicyCeiling(
        allowed_corpus_modes=(CorpusMode.SNAPSHOT,),
        allowed_providers=(),
        allowed_source_types=("paper", "paper_metadata"),
        allowed_agent_tools=("arxiv_search", "pdf_reader"),
        denied_action_ids=("external_publish", "deploy", "send_message"),
        network_access="none",
        maximum_autonomy_tier=AutonomyTier.A1_BOUNDED_TOOLS,
        hard_timeout_seconds=600,
        max_tool_calls=50,
        max_model_calls=40,
        chargeable_work=(
            "requires_external_approval" if chargeable else "forbidden"
        ),
        workflow_spend_ceiling_usd=cost,
        minimum_data_class=DataClass.INTERNAL,
        allowed_processing_purposes=("product_operation",),
    )


def task_spec() -> Any:
    policy = policy_bundle()
    return compile_research_request(
        ResearchCompilerInput(
            task_id="research-policy-v1:manifest-test",
            query="Compare verification policies using only the controlled corpus.",
            hitl_plan_review=False,
        ),
        requested_policy=policy,
        platform_policy=platform_policy(),
        compiler_ref=ref("task_compiler", "research-api-v1", "5"),
        compiled_at=NOW,
    )


def episode_budget(
    *, workflow: str = "0.000000", judge: str = "0.000000", total: str = "0.000000"
) -> EpisodeBudget:
    return EpisodeBudget(
        workflow_cost_usd_max=workflow,
        judge_cost_usd_max=judge,
        total_cost_usd_max=total,
        wall_time_seconds_max=600,
        workflow_model_calls_max=40,
        judge_model_calls_max=4,
        tool_calls_max=50,
    )


def arm(arm_id: Literal["A", "B", "C", "D", "E"]) -> PolicySnapshot:
    selector = {
        "A": "fixed",
        "B": "fixed_evidence",
        "C": "fixed_verify_repair",
        "D": "supervisor_verified",
        "E": "adaptive_verified",
    }[arm_id]
    supervisor = arm_id in {"D", "E"}
    evidence = arm_id in {"B", "C", "D", "E"}
    verifier = arm_id in {"D", "E"}
    return PolicySnapshot(
        arm_id=arm_id,
        selector=selector,  # type: ignore[arg-type]
        policy_version="1.0.0-experimental",
        graph_digest="sha256:" + str("ABCDE".index(arm_id) + 1) * 64,
        graph_capabilities=(
            ("fixed_post_synthesis_verifier",)
            if arm_id == "C"
            else (
                ("adaptive_compute_router", "candidate_branching", "marginal_stop")
                if arm_id == "E"
                else ()
            )
        ),
        config_schema=f"{selector}/1.0.0",
        runtime_flags=RuntimeFlags(
            enable_supervisor=supervisor,
            enable_evidence_store=evidence,
            enable_verifier=verifier,
        ),
        config=PolicyConfig(
            allowed_tiers=("T0", "T1", "T2") if arm_id == "E" else (),
            default_tier="T1" if arm_id == "E" else None,
            difficulty_features_version="1.0.0" if arm_id == "E" else None,
            max_targeted_repairs=1 if arm_id in {"C", "E"} else 0,
            max_branches=3 if arm_id == "E" else None,
            selection="listwise" if arm_id == "E" else None,
            marginal_stop_policy_version="1.0.0" if arm_id == "E" else None,
            allowed_repairs=("replace_or_qualify_claim",) if arm_id == "C" else (),
            reverify_repaired_subject=arm_id == "C",
        ),
        capabilities=PolicyCapabilities(
            supervisor=supervisor,
            evidence_store=evidence,
            fixed_post_synthesis_verifier=arm_id == "C",
            adaptive_compute=arm_id == "E",
        ),
    )


@dataclass(frozen=True)
class ManifestFixture:
    task: Any
    manifest: RunManifestV1


def manifest_fixture() -> ManifestFixture:
    task = task_spec()
    task_ref = build_task_spec_ref(
        task,
        artifact_locator=f"cas://sha256/{sha256_digest(task).removeprefix('sha256:')}",
    )
    policy = arm("A")
    runtime_values = {
        "enable_supervisor": False,
        "enable_evidence_store": False,
        "use_mock_data": True,
        "max_papers": 10,
    }
    runtime = RuntimeConfigSnapshot(
        settings_schema_digest=ref("settings_schema", "runtime-v1", "6").digest,
        effective_values=runtime_values,
        effective_values_digest=sha256_digest(runtime_values),
    )
    invocation = InvocationSnapshot(
        enable_hitl=False,
        hitl_bypass=True,
        hitl_bypass_reason="unattended-evaluation",
        checkpoint_mode="persistent",
    )
    provider = LlmProviderSnapshot(
        provider="local_mock",
        api_protocol_version="fixture-v1",
        model_resolution="exact-id-required",
        routes={"default": "deterministic-fixture-v1"},
        sampling=SamplingSnapshot(
            temperature="0.000000", maximum_output_tokens=2048
        ),
        retry=RetrySnapshot(timeout_seconds=30, max_retries=0),
        prompt_cache="disabled",
        credential=CredentialBinding(present=False),
        metered=False,
    )
    prompts = PromptSnapshot(
        bundle_ref=ref("prompt_bundle", "research-prompts", "7"),
        renderer_digest=ref("renderer", "prompt-renderer", "8").digest,
    )
    tools = ToolSnapshot(
        registry_ref=ref("tool_registry", "research-tools", "9"),
        implementation_refs=(ref("tool_implementation", "arxiv-search", "a"),),
        agent_invocable=("arxiv_search", "pdf_reader"),
        internal_components=("pdf_parser", "chunk_ranker"),
        denied=("general_shell", "repository_write", "deploy"),
        network_policy="none",
        filesystem_policy="read-only",
        tool_result_capture="content-addressed-redacted",
    )
    source_ref = task.source_scope.snapshot_ref
    assert source_ref is not None
    sources = SourceSnapshot(
        input_corpus_mode=CorpusMode.SNAPSHOT,
        observation_capture_mode="recorded",
        source_policy_ref=task.source_scope.policy_ref,
        source_snapshot_ref=source_ref,
        live_access_allowed=False,
    )
    budget = episode_budget()
    decision = resolve_admission(
        AdmissionPlan(
            campaign_id="camp_manifest-test",
            stage="stage-0",
            provider="local_mock",
            task_policy=policy_bundle(),
            effective_policy=policy_bundle(),
            platform_workflow_cost_usd="0.000000",
            campaign_workflow_allocation_usd="0.000000",
            provider_workflow_cost_usd="0.000000",
            episode_budget=budget,
            provider_metered=False,
        ),
        verified_at=NOW,
        approval_backend=FakeLocalApprovalBackend(),
    )
    group_id = derive_replicate_group_id(
        "camp_manifest-test", task_ref, sha256_digest(policy)
    )
    identity = RunIdentity(
        campaign_id="camp_manifest-test",
        episode_key=derive_episode_key(group_id, 0),
        replicate_group_id=group_id,
        run_id=new_run_id(entropy=uuid.UUID(int=1)),
        repeat_index=0,
        created_at=NOW,
        created_by="eval-orchestrator/1.0.0",
    )
    randomness = RandomnessSnapshot(
        repeat_index=0,
        root_seed=731245,
        component_seeds_ref=ref("seed_map", "episode-seeds", "b"),
        determinism_class=DeterminismClass.DETERMINISTIC_LOCAL,
    )
    projection_payload = PolicyRuntimeProjectionPayload(
        identity={
            "campaign_id": identity.campaign_id,
            "run_id": identity.run_id,
            "repeat_index": identity.repeat_index,
        },
        task=agent_safe_task_projection(task),
        policy=policy,
        runtime_config=runtime,
        invocation=invocation,
        workflow_provider=PolicyProviderProjection(
            provider=provider.provider,
            api_protocol_version=provider.api_protocol_version,
            model_resolution=provider.model_resolution,
            routes=provider.routes,
            sampling=provider.sampling,
            retry=provider.retry,
            prompt_cache=provider.prompt_cache,
        ),
        prompts=prompts,
        tools=tools,
        sources=sources,
        limits=decision.resolution.resolved_limits,
    )
    projection_digest = sha256_digest(projection_payload)
    payload = RunManifestPayload(
        identity=identity,
        lineage=None,
        compilation=CompilationSnapshot(
            receipt_ref=ref("compilation_receipt", "task-compilation", "c"),
            receipt_locator="cas://sha256/" + "c" * 64,
        ),
        task=task_ref,
        campaign_lock_ref=ref("campaign_lock", "manifest-campaign-lock", "d"),
        campaign_lock_locator="cas://sha256/" + "d" * 64,
        registry_resolution=RegistryResolution(
            suite_ref=ref("benchmark_suite", "research-policy-v1", "e"),
            task_set_ref=ref("task_set", "research-policy-tasks", "f"),
            task_case_ref=ref("task_case", "manifest-test", "1"),
            split_assignment_ref=ref("split_assignment", "development-split", "2"),
            rubric_set_refs=(ref("rubric_set", "research-rubric", "3"),),
            grader_profile_refs=(ref("grader_profile", "research-metrics", "4"),),
            label_set_refs=(ref("label_set", "expected-topics", "5"),),
            source_snapshot_ref=source_ref,
            validation_receipt_ref=ref(
                "registry_validation_receipt", "manifest-registry-check", "6"
            ),
        ),
        policy=policy,
        runtime_config=runtime,
        invocation=invocation,
        providers=ProviderSnapshot(
            llm=provider,
            pricing=PricingSnapshot(
                table_ref=ref("pricing_table", "local-zero-cost", "7"),
                prices_last_verified="2026-09-05",
            ),
        ),
        prompts=prompts,
        tools=tools,
        sources=sources,
        evaluation=EvaluationSnapshot(
            grader_profile_refs=(ref("grader_profile", "research-metrics", "4"),),
            judge_routes={"citation_accuracy": "deterministic-metric-v1"},
            judge_prompt_bundle_ref=ref("prompt_bundle", "eval-prompts", "8"),
            calibration_ref=ref("calibration_set", "judge-calibration", "9"),
            blinding_policy="arm-and-candidate-identity-masked",
            ordering_policy="campaign-predeclared",
            sampling=SamplingSnapshot(
                temperature="0.000000", maximum_output_tokens=1024
            ),
            retry=RetrySnapshot(timeout_seconds=30, max_retries=0),
            null_score_policy="retain-and-report-denominator",
            budget=EvaluationBudget(cost_usd_max="0.000000", model_calls_max=0),
        ),
        randomness=randomness,
        admission_resolution=decision.resolution,
        budgets=BudgetSnapshot(
            episode=budget,
            campaign=CampaignBudget(
                total_cost_usd_max="0.000000",
                enforcement="between-episodes-with-in-flight-overshoot-risk",
            ),
        ),
        approval=decision.approval,
        code=CodeSnapshot(
            repository="kudratsingh/arxiv-research-agent",
            commit_sha="1" * 40,
            worktree_state="clean",
            policy_subtree_digest=ref("code_tree", "policy-code", "a").digest,
            prompt_subtree_digest=ref("code_tree", "prompt-code", "b").digest,
            tool_subtree_digest=ref("code_tree", "tool-code", "c").digest,
            promotion_eligible=True,
        ),
        environment=EnvironmentSnapshot(
            execution_class="local-test",
            python_version="3.11.13",
            platform="darwin-arm64",
            dependency_lock_ref=ref("dependency_lock", "requirements-lock", "d"),
            locale="en-US",
            timezone="UTC",
        ),
        outputs=OutputSnapshot(
            root="episodes/manifest-test/0/A",
            artifact_schema_version="1.0.0",
            trajectory_schema_version="1.0.0",
            verification_schema_version="1.0.0",
        ),
        privacy=PrivacySnapshot(
            task_data_class=DataClass.INTERNAL,
            registry_object_classification=DataClass.INTERNAL,
            retention_policy_ref=retention_ref(),
            redaction_policy_version="1.0.0",
        ),
        policy_runtime_projection=PolicyRuntimeProjectionRef(
            artifact_ref=ImmutableObjectRef(
                kind="policy_runtime_projection",
                id="manifest-runtime-projection",
                revision="1.0.0",
                digest=projection_digest,
            ),
            artifact_locator=(
                "cas://sha256/" + projection_digest.removeprefix("sha256:")
            ),
            excluded_classes=(
                "sealed-case-and-split-identity",
                "evaluator-and-label-refs",
                "approval-metadata",
                "private-object-locators",
                "hidden-rubric-content",
            ),
        ),
    )
    return ManifestFixture(task=task, manifest=seal_manifest(payload))


@pytest.mark.unit
def test_manifest_and_candidate_projection_are_integrity_checked_and_isolated() -> None:
    fixture = manifest_fixture()
    manifest = fixture.manifest
    assert manifest.integrity.payload_sha256 == sha256_digest(manifest.payload)

    projection = build_policy_runtime_projection(manifest, fixture.task)
    candidate = projection.model_dump(mode="json")
    encoded = json.dumps(candidate, sort_keys=True)
    assert projection.integrity.payload_sha256 == (
        manifest.payload.policy_runtime_projection.artifact_ref.digest
    )
    for forbidden in (
        "registry_resolution",
        "label_set_refs",
        "grader_profile_refs",
        "approval_id",
        "campaign_lock_locator",
        "pricing",
        "credential",
        "credential-binding",
    ):
        assert forbidden not in encoded


@pytest.mark.unit
def test_manifest_tamper_and_behavior_change_are_detected() -> None:
    manifest = manifest_fixture().manifest
    raw = manifest.model_dump(mode="python")
    raw["payload"]["identity"]["created_by"] = "tampered"
    with pytest.raises((ValidationError, ValueError), match="digest mismatch"):
        RunManifestV1.model_validate(raw)

    changed_payload = manifest.payload.model_copy(
        update={
            "invocation": InvocationSnapshot(
                enable_hitl=False,
                hitl_bypass=True,
                hitl_bypass_reason="different-no-cost-mode",
                checkpoint_mode="persistent",
            )
        }
    )
    assert seal_manifest(changed_payload).integrity.payload_sha256 != (
        manifest.integrity.payload_sha256
    )


@pytest.mark.unit
def test_manifest_store_is_create_once_atomic_and_fail_closed(tmp_path: Path) -> None:
    manifest = manifest_fixture().manifest
    store = ManifestFileStore()
    target, sidecar = store.seal(tmp_path / "run", manifest)
    assert target.is_file() and sidecar.is_file()
    assert store.load(tmp_path / "run") == manifest
    with pytest.raises(RunManifestError, match="overwrite"):
        store.seal(tmp_path / "run", manifest)

    failed = tmp_path / "fault"
    with pytest.raises(RuntimeError, match="injected"):
        store.seal(
            failed,
            manifest,
            before_publish=lambda: (_ for _ in ()).throw(RuntimeError("injected")),
        )
    assert list(failed.iterdir()) == []

    sidecar.unlink()
    with pytest.raises(RunManifestError, match="both exist"):
        store.load(tmp_path / "run")


def approval_record(
    *,
    status: ApprovalStatus = ApprovalStatus.APPROVED,
    campaign_id: str = "camp_paid-test",
    provider: str = "anthropic",
    stage: str = "calibration-smoke",
) -> ApprovalRecord:
    scope = ApprovalScope(
        campaign_id=campaign_id,
        providers=(provider,),
        stages=(stage,),
        resources=("provider_call",),
        total_cost_usd_max="10.000000",
        episode_allocation_usd_max="2.000000",
        workflow_allocation_usd_max="1.500000",
        judge_allocation_usd_max="0.500000",
    )
    return ApprovalRecord(
        approval_id="approval_paid-test",
        status=status,
        scope=scope,
        approved_by="owner",
        approved_at=NOW,
        expires_at="2026-09-07T08:00:00Z",
        record_digest=sha256_digest({"scope": scope, "status": status}),
    )


def paid_plan(*, approval_id: str | None = "approval_paid-test") -> AdmissionPlan:
    policy = policy_bundle(chargeable=True, cost="2.000000")
    effective = policy_bundle(chargeable=True, cost="1.500000")
    return AdmissionPlan(
        campaign_id="camp_paid-test",
        stage="calibration-smoke",
        provider="anthropic",
        resources=("provider_call",),
        task_policy=policy,
        effective_policy=effective,
        platform_workflow_cost_usd="2.000000",
        campaign_workflow_allocation_usd="1.500000",
        provider_workflow_cost_usd="2.000000",
        episode_budget=episode_budget(
            workflow="1.500000", judge="0.500000", total="2.000000"
        ),
        provider_metered=True,
        approval_id=approval_id,
    )


@pytest.mark.unit
def test_chargeable_admission_verifies_scope_before_credential_lookup() -> None:
    calls: list[str] = []
    backend = FakeLocalApprovalBackend((approval_record(),))
    decision = resolve_admission(
        paid_plan(),
        verified_at=LATER,
        approval_backend=backend,
        credential_probe=lambda: calls.append("credential"),
    )
    assert decision.chargeable
    assert decision.approval.status_at_seal is ApprovalStatus.APPROVED
    assert decision.resolution.resolved_workflow_cost_usd == "1.500000"
    assert calls == ["credential"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "record,plan,error",
    [
        (None, paid_plan(approval_id=None), "explicit external approval"),
        (approval_record(status=ApprovalStatus.PENDING), paid_plan(), "pending"),
        (approval_record(campaign_id="camp_wrong"), paid_plan(), "campaign"),
        (approval_record(provider="other_provider"), paid_plan(), "provider"),
        (approval_record(stage="other-stage"), paid_plan(), "stage"),
    ],
)
def test_invalid_approval_fails_before_credentials(
    record: ApprovalRecord | None, plan: AdmissionPlan, error: str
) -> None:
    calls: list[str] = []
    backend = FakeLocalApprovalBackend(() if record is None else (record,))
    with pytest.raises(RunManifestError, match=error):
        resolve_admission(
            plan,
            verified_at=LATER,
            approval_backend=backend,
            credential_probe=lambda: calls.append("credential"),
        )
    assert calls == []


@pytest.mark.unit
def test_api_key_presence_is_not_approval_and_no_cost_path_never_probes() -> None:
    calls: list[str] = []
    with pytest.raises(RunManifestError, match="explicit external approval"):
        resolve_admission(
            paid_plan(approval_id=None),
            verified_at=LATER,
            approval_backend=FakeLocalApprovalBackend(),
            credential_probe=lambda: calls.append("credential"),
        )
    assert calls == []

    no_cost = manifest_fixture().manifest
    assert no_cost.payload.approval == ApprovalSnapshot(
        required=False,
        status_at_seal=ApprovalStatus.NOT_REQUIRED,
        not_required_reason="mocked-local-stage-0",
        authoritative_source="local-no-cost",
    )


@pytest.mark.unit
def test_effective_policy_cannot_broaden_task_permissions() -> None:
    plan = paid_plan().model_copy(
        update={
            "effective_policy": policy_bundle(
                chargeable=True,
                cost="1.500000",
                tools=("arxiv_search", "pdf_reader", "general_shell"),
            )
        }
    )
    with pytest.raises(RunManifestError, match="tools broaden"):
        resolve_admission(
            plan,
            verified_at=LATER,
            approval_backend=FakeLocalApprovalBackend((approval_record(),)),
        )


@pytest.mark.unit
def test_repeat_rerun_resume_and_attempt_identities_are_distinct() -> None:
    fixture = manifest_fixture()
    identity = fixture.manifest.payload.identity
    task_ref = fixture.manifest.payload.task
    arm_digest = sha256_digest(fixture.manifest.payload.policy)
    assert derive_replicate_group_id(identity.campaign_id, task_ref, arm_digest) == (
        identity.replicate_group_id
    )
    assert derive_episode_key(identity.replicate_group_id, 0) == identity.episode_key
    assert derive_episode_key(identity.replicate_group_id, 1) != identity.episode_key
    assert new_run_id(entropy=uuid.UUID(int=2)) != identity.run_id
    assert new_attempt_id(entropy=uuid.UUID(int=2)).startswith("att_")

    checkpoint = manifest_compatibility(fixture.manifest)
    attempt_id = validate_resume(
        fixture.manifest,
        checkpoint,
        completion=None,
        approval_receipt=None,
        accumulated_workflow_cost_usd="0.000000",
        accumulated_judge_cost_usd="0.000000",
    )
    assert attempt_id.startswith("att_")


@pytest.mark.unit
def test_resume_fails_closed_on_mismatch_terminal_or_unsafe_boundary() -> None:
    manifest = manifest_fixture().manifest
    expected = manifest_compatibility(manifest)
    mismatch = CheckpointCompatibility(
        **{
            **expected.model_dump(mode="python"),
            "prompt_digest": "sha256:" + "0" * 64,
        }
    )
    with pytest.raises(RunManifestError, match="prompt_digest"):
        validate_resume(
            manifest,
            mismatch,
            completion=None,
            approval_receipt=None,
            accumulated_workflow_cost_usd="0.000000",
            accumulated_judge_cost_usd="0.000000",
        )

    completion = CompletionReceipt(
        run_id=manifest.payload.identity.run_id,
        manifest_digest=manifest.integrity.payload_sha256,
        status=CompletionStatus.SUCCEEDED,
        completed_at=LATER,
        accumulated_workflow_cost_usd="0.000000",
        accumulated_judge_cost_usd="0.000000",
    )
    with pytest.raises(RunManifestError, match="terminal"):
        validate_resume(
            manifest,
            expected,
            completion=completion,
            approval_receipt=None,
            accumulated_workflow_cost_usd="0.000000",
            accumulated_judge_cost_usd="0.000000",
        )
    with pytest.raises(ValidationError, match="reconciliation"):
        CheckpointCompatibility(
            **{
                **expected.model_dump(mode="python"),
                "idempotent_boundary": False,
            }
        )


@pytest.mark.unit
def test_attempt_and_completion_receipts_preserve_typed_outcomes() -> None:
    manifest = manifest_fixture().manifest
    attempt = AttemptReceipt(
        run_id=manifest.payload.identity.run_id,
        attempt_id=new_attempt_id(entropy=uuid.UUID(int=3)),
        manifest_digest=manifest.integrity.payload_sha256,
        started_at=NOW,
        ended_at=LATER,
        outcome="interrupted",
        reason=RunReason.INFRASTRUCTURE_LOST,
        accumulated_workflow_cost_usd="0.000000",
        accumulated_judge_cost_usd="0.000000",
    )
    assert attempt.reason is RunReason.INFRASTRUCTURE_LOST
    with pytest.raises(ValidationError, match="requires a reason"):
        CompletionReceipt(
            run_id=manifest.payload.identity.run_id,
            manifest_digest=manifest.integrity.payload_sha256,
            status=CompletionStatus.CANCELLED,
            completed_at=LATER,
            accumulated_workflow_cost_usd="0.000000",
            accumulated_judge_cost_usd="0.000000",
        )


@pytest.mark.unit
def test_all_five_arms_are_distinct_and_structural_impostors_fail() -> None:
    arm_ids: tuple[Literal["A", "B", "C", "D", "E"], ...] = (
        "A",
        "B",
        "C",
        "D",
        "E",
    )
    arms = validate_arm_matrix(tuple(arm(item) for item in arm_ids))
    assert len({sha256_digest(item) for item in arms}) == 5
    with pytest.raises(ValidationError, match="structural verifier"):
        PolicySnapshot(
            **{
                **arm("C").model_dump(mode="python"),
                "runtime_flags": RuntimeFlags(
                    enable_supervisor=False,
                    enable_evidence_store=True,
                    enable_verifier=True,
                ),
            }
        )
    with pytest.raises(ValidationError, match="router"):
        PolicySnapshot(
            **{
                **arm("E").model_dump(mode="python"),
                "config": PolicyConfig(
                    allowed_tiers=("T0", "T1", "T2"),
                    default_tier="T1",
                ),
            }
        )


@pytest.mark.unit
def test_dirty_worktree_is_explicit_and_not_promotion_eligible() -> None:
    clean = manifest_fixture().manifest.payload.code
    with pytest.raises(ValidationError, match="not promotable"):
        CodeSnapshot(
            **{
                **clean.model_dump(mode="python"),
                "worktree_state": "dirty",
                "patch_digest": VALID_DIGEST,
                "promotion_eligible": True,
            }
        )
    dirty = CodeSnapshot(
        **{
            **clean.model_dump(mode="python"),
            "worktree_state": "dirty",
            "patch_digest": VALID_DIGEST,
            "promotion_eligible": False,
        }
    )
    assert dirty.patch_digest == VALID_DIGEST


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        {"anthropic_api_key": "redacted"},
        {"credential_fingerprint": "sha256:abc"},
        {"notes": "Authorization: Bearer abcdefghijklmnop"},
        {"path": "/Users/example/private.txt"},
        {"chain_of_thought": "hidden reasoning"},
    ],
)
def test_secret_private_path_and_hidden_reasoning_are_rejected(value: dict[str, str]) -> None:
    with pytest.raises(RunManifestError):
        validate_manifest_safe_content(value)


@pytest.mark.unit
def test_legacy_import_marks_unknown_provenance_and_rejects_secret_diagnostics() -> None:
    legacy = import_legacy_eval(
        {
            "run_id": "legacy-run",
            "query_id": "q-1",
            "domain": "ml",
            "elapsed_seconds": 12,
            "workflow_cost_usd": "0.100000",
            "query": "not copied into the wrapper",
        }
    )
    assert legacy.provenance_completeness == "partial"
    assert not legacy.promotion_eligible
    assert legacy.policy == legacy.approval == legacy.environment == "unknown"
    assert "query" not in legacy.known_metadata
    with pytest.raises(RunManifestError, match="secret-shaped"):
        import_legacy_eval({"error": "api_key=super-secret-value"})


@pytest.mark.unit
def test_schema_is_closed_versioned_and_contains_required_sections() -> None:
    schema = run_manifest_json_schema()
    assert schema["$id"].endswith("/run-manifest/1.0.0")
    payload_required = set(schema["$defs"]["RunManifestPayload"]["required"])
    assert {"identity", "task", "evaluation", "approval", "privacy"} <= payload_required
    raw = manifest_fixture().manifest.model_dump(mode="python")
    raw["schema_version"] = "2.0.0"
    with pytest.raises(ValidationError):
        RunManifestV1.model_validate(raw)


@pytest.mark.unit
def test_nested_manifest_sections_reject_incoherent_values() -> None:
    fixture = manifest_fixture()
    payload = fixture.manifest.payload

    with pytest.raises(ValidationError, match="migration lineage"):
        RunLineage(kind="migration", reason="old schema")
    with pytest.raises(ValidationError, match="parent run"):
        RunLineage(kind="rerun", reason="retry terminal run")
    assert RunLineage(
        kind="migration",
        migrated_from_manifest_digest=VALID_DIGEST,
        reason="old schema",
    ).kind == "migration"
    assert RunLineage(
        kind="rerun",
        parent_run_id=new_run_id(entropy=uuid.UUID(int=9)),
        reason="new independent sample",
    ).kind == "rerun"

    with pytest.raises(ValidationError, match="compilation receipt"):
        CompilationSnapshot(
            receipt_ref=ref("artifact", "wrong-kind"),
            receipt_locator="cas://sha256/" + "a" * 64,
        )

    registry = payload.registry_resolution
    registry_raw = registry.model_dump(mode="python")
    invalid_registry_updates: tuple[tuple[dict[str, Any], str], ...] = (
        ({"suite_ref": ref("task_set", "wrong-suite")}, "expected benchmark_suite"),
        ({"rubric_set_refs": (ref("label_set", "wrong-rubric"),)}, "non-rubric_set"),
        (
            {"rubric_set_refs": (registry.rubric_set_refs[0], registry.rubric_set_refs[0])},
            "must be unique",
        ),
        ({"rubric_set_refs": ()}, "requires rubric"),
        ({"source_snapshot_ref": ref("artifact", "wrong-source")}, "wrong kind"),
    )
    for updates, message in invalid_registry_updates:
        with pytest.raises(ValidationError, match=message):
            RegistryResolution(**{**registry_raw, **updates})

    with pytest.raises(ValidationError, match="bypass requires"):
        InvocationSnapshot(
            enable_hitl=False,
            hitl_bypass=True,
            checkpoint_mode="persistent",
        )
    with pytest.raises(ValidationError, match="presence"):
        CredentialBinding(present=True)
    provider_raw = payload.providers.llm.model_dump(mode="python")
    with pytest.raises(ValidationError, match="model route"):
        LlmProviderSnapshot(**{**provider_raw, "routes": {}})

    tools_raw = payload.tools.model_dump(mode="python")
    with pytest.raises(ValidationError, match="must be unique"):
        ToolSnapshot(
            **{
                **tools_raw,
                "agent_invocable": ("arxiv_search", "arxiv_search"),
            }
        )
    with pytest.raises(ValidationError, match="both allowed and denied"):
        ToolSnapshot(
            **{
                **tools_raw,
                "denied": (*payload.tools.denied, "arxiv_search"),
            }
        )

    source_raw = payload.sources.model_dump(mode="python")
    source_cases: tuple[tuple[dict[str, Any], str], ...] = (
        ({"source_policy_ref": ref("artifact", "wrong-policy")}, "wrong kind"),
        ({"source_snapshot_ref": None}, "requires a source_snapshot"),
        ({"live_access_allowed": True}, "cannot allow live"),
        (
            {
                "input_corpus_mode": CorpusMode.CURATED,
                "live_access_allowed": False,
            },
            "only snapshot",
        ),
        (
            {
                "input_corpus_mode": CorpusMode.LIVE,
                "source_snapshot_ref": None,
                "live_access_allowed": False,
            },
            "must permit live",
        ),
    )
    for updates, message in source_cases:
        with pytest.raises(ValidationError, match=message):
            SourceSnapshot(**{**source_raw, **updates})

    with pytest.raises(ValidationError, match="lower than component"):
        episode_budget(workflow="1.000000", judge="1.000000", total="1.000000")

    no_cost = payload.approval
    with pytest.raises(ValidationError, match="must be approved"):
        ApprovalSnapshot(
            required=True,
            status_at_seal=ApprovalStatus.PENDING,
            authoritative_source="external-approval-record",
        )
    with pytest.raises(ValidationError, match="not-required reason"):
        ApprovalSnapshot(
            **{
                **resolve_admission(
                    paid_plan(),
                    verified_at=LATER,
                    approval_backend=FakeLocalApprovalBackend((approval_record(),)),
                ).approval.model_dump(mode="python"),
                "not_required_reason": "incorrect",
            }
        )
    with pytest.raises(ValidationError, match="use not_required"):
        ApprovalSnapshot(
            required=False,
            status_at_seal=ApprovalStatus.PENDING,
            not_required_reason="local",
            authoritative_source="local-no-cost",
        )
    with pytest.raises(ValidationError, match="only its reason"):
        ApprovalSnapshot(
            **{
                **no_cost.model_dump(mode="python"),
                "approval_id": "approval_should-not-exist",
            }
        )

    with pytest.raises(ValidationError, match="clean worktrees"):
        CodeSnapshot(
            **{
                **payload.code.model_dump(mode="python"),
                "patch_digest": VALID_DIGEST,
            }
        )
    projection_ref_raw = payload.policy_runtime_projection.model_dump(mode="python")
    with pytest.raises(ValidationError, match="every excluded"):
        PolicyRuntimeProjectionRef(
            **{**projection_ref_raw, "excluded_classes": ("approval-metadata",)}
        )
    with pytest.raises(ValidationError, match="wrong kind"):
        PolicyRuntimeProjectionRef(
            **{
                **projection_ref_raw,
                "artifact_ref": ref("artifact", "wrong-projection"),
            }
        )
    with pytest.raises(ValidationError, match="digest mismatch"):
        RuntimeConfigSnapshot(
            settings_schema_digest=VALID_DIGEST,
            effective_values={"mode": "changed"},
            effective_values_digest=VALID_DIGEST,
        )
    with pytest.raises(RunManifestError, match="non-negative"):
        derive_episode_key(VALID_DIGEST, -1)


@pytest.mark.unit
def test_every_policy_arm_rejects_structural_impostors() -> None:
    cases: tuple[tuple[dict[str, Any], str], ...] = (
        (
            {**arm("A").model_dump(mode="python"), "selector": "fixed_evidence"},
            "selector",
        ),
        (
            {
                **arm("A").model_dump(mode="python"),
                "runtime_flags": RuntimeFlags(
                    enable_supervisor=False,
                    enable_evidence_store=True,
                    enable_verifier=False,
                ),
            },
            "Arm A",
        ),
        (
            {
                **arm("B").model_dump(mode="python"),
                "runtime_flags": RuntimeFlags(
                    enable_supervisor=False,
                    enable_evidence_store=False,
                    enable_verifier=False,
                ),
            },
            "Arm B",
        ),
        (
            {**arm("C").model_dump(mode="python"), "graph_capabilities": ()},
            "lacks fixed",
        ),
        (
            {
                **arm("C").model_dump(mode="python"),
                "config": PolicyConfig(max_targeted_repairs=0),
            },
            "one targeted repair",
        ),
        (
            {
                **arm("D").model_dump(mode="python"),
                "runtime_flags": RuntimeFlags(
                    enable_supervisor=True,
                    enable_evidence_store=True,
                    enable_verifier=False,
                ),
            },
            "Arm D",
        ),
        (
            {
                **arm("E").model_dump(mode="python"),
                "runtime_flags": RuntimeFlags(
                    enable_supervisor=True,
                    enable_evidence_store=True,
                    enable_verifier=False,
                ),
            },
            "Arm E",
        ),
        (
            {
                **arm("E").model_dump(mode="python"),
                "capabilities": PolicyCapabilities(
                    supervisor=True,
                    evidence_store=True,
                    fixed_post_synthesis_verifier=False,
                    adaptive_compute=False,
                ),
            },
            "adaptive compute",
        ),
        (
            {
                **arm("E").model_dump(mode="python"),
                "config": PolicyConfig(
                    allowed_tiers=("T0", "T1"),
                    default_tier="T1",
                    difficulty_features_version="1.0.0",
                    max_branches=2,
                    selection="listwise",
                    marginal_stop_policy_version="1.0.0",
                ),
            },
            "T0-T2",
        ),
    )
    for raw, message in cases:
        with pytest.raises(ValidationError, match=message):
            PolicySnapshot(**raw)


@pytest.mark.unit
def test_manifest_cross_section_consistency_is_fail_closed() -> None:
    payload = manifest_fixture().manifest.payload
    raw = payload.model_dump(mode="python")
    cases: tuple[tuple[dict[str, Any], str], ...] = (
        ({"campaign_lock_ref": ref("artifact", "wrong-lock")}, "campaign lock"),
        (
            {
                "randomness": payload.randomness.model_copy(
                    update={"repeat_index": 1}
                )
            },
            "repeat indexes",
        ),
        (
            {
                "privacy": payload.privacy.model_copy(
                    update={"task_data_class": DataClass.PUBLIC}
                )
            },
            "data classes",
        ),
        (
            {
                "registry_resolution": payload.registry_resolution.model_copy(
                    update={
                        "source_snapshot_ref": ref(
                            "source_snapshot", "different-corpus", "8"
                        )
                    }
                )
            },
            "source snapshots",
        ),
        (
            {
                "providers": payload.providers.model_copy(
                    update={"llm": payload.providers.llm.model_copy(update={"metered": True})}
                )
            },
            "approval requirement",
        ),
        (
            {
                "admission_resolution": payload.admission_resolution.model_copy(
                    update={
                        "input_workflow_ceilings": (
                            payload.admission_resolution.input_workflow_ceilings.model_copy(
                                update={
                                    "task_workflow_cost_usd": "1.000000",
                                    "platform_workflow_cost_usd": "1.000000",
                                    "campaign_workflow_allocation_usd": "1.000000",
                                    "provider_workflow_cost_usd": "1.000000",
                                    "approval_workflow_allocation_usd": "1.000000",
                                }
                            )
                        ),
                        "resolved_workflow_cost_usd": "1.000000",
                    }
                )
            },
            "workflow caps",
        ),
        (
            {
                "policy": payload.policy.model_copy(
                    update={
                        "capabilities": payload.policy.capabilities.model_copy(
                            update={"supervisor": True}
                        )
                    }
                )
            },
            "supervisor flag",
        ),
        (
            {
                "policy": payload.policy.model_copy(
                    update={
                        "capabilities": payload.policy.capabilities.model_copy(
                            update={"evidence_store": True}
                        )
                    }
                )
            },
            "evidence flag",
        ),
    )
    for updates, message in cases:
        with pytest.raises(ValidationError, match=message):
            RunManifestPayload(**{**raw, **updates})


@pytest.mark.unit
def test_candidate_projection_refuses_task_and_projection_substitution() -> None:
    fixture = manifest_fixture()
    manifest = fixture.manifest

    different_task = fixture.task.model_copy(update={"task_spec_id": "tsp_" + "1" * 20})
    with pytest.raises(RunManifestError, match="TaskSpec id"):
        build_policy_runtime_projection(manifest, different_task)

    wrong_ref = manifest.payload.task.model_copy(update={"full_digest": VALID_DIGEST})
    wrong_payload = manifest.payload.model_copy(update={"task": wrong_ref})
    wrong_manifest = manifest.model_copy(update={"payload": wrong_payload})
    with pytest.raises(RunManifestError, match="TaskSpec digest"):
        build_policy_runtime_projection(wrong_manifest, fixture.task)

    wrong_sources = manifest.payload.sources.model_copy(
        update={"input_corpus_mode": CorpusMode.CURATED}
    )
    wrong_manifest = manifest.model_copy(
        update={"payload": manifest.payload.model_copy(update={"sources": wrong_sources})}
    )
    with pytest.raises(RunManifestError, match="source mode"):
        build_policy_runtime_projection(wrong_manifest, fixture.task)

    broad_tools = manifest.payload.tools.model_copy(
        update={"agent_invocable": (*manifest.payload.tools.agent_invocable, "general_shell")}
    )
    wrong_manifest = manifest.model_copy(
        update={"payload": manifest.payload.model_copy(update={"tools": broad_tools})}
    )
    with pytest.raises(RunManifestError, match="broaden"):
        build_policy_runtime_projection(wrong_manifest, fixture.task)

    wrong_projection_ref = manifest.payload.policy_runtime_projection.model_copy(
        update={
            "artifact_ref": manifest.payload.policy_runtime_projection.artifact_ref.model_copy(
                update={"digest": VALID_DIGEST}
            )
        }
    )
    wrong_manifest = manifest.model_copy(
        update={
            "payload": manifest.payload.model_copy(
                update={"policy_runtime_projection": wrong_projection_ref}
            )
        }
    )
    with pytest.raises(RunManifestError, match="projection digest"):
        build_policy_runtime_projection(wrong_manifest, fixture.task)


@pytest.mark.unit
def test_admission_rejects_every_permission_broadening() -> None:
    base = paid_plan()
    requested = base.task_policy
    effective = base.effective_policy

    def changed(**updates: Any) -> AdmissionPlan:
        return base.model_copy(
            update={"effective_policy": effective.model_copy(update=updates)}
        )

    source = effective.source_scope
    tool = effective.tool_policy
    limits = effective.execution_limits
    data = effective.data_policy
    autonomy = effective.autonomy
    broadened: tuple[tuple[AdmissionPlan, str], ...] = (
        (
            changed(source_scope=source.model_copy(update={"corpus_mode": CorpusMode.LIVE})),
            "corpus mode",
        ),
        (
            changed(source_scope=source.model_copy(update={"allowed_providers": ("other",)})),
            "source providers",
        ),
        (
            changed(source_scope=source.model_copy(update={"allowed_source_types": ("web",)})),
            "source types",
        ),
        (
            changed(tool_policy=tool.model_copy(update={"denied_action_ids": ()})),
            "removes",
        ),
        (
            changed(tool_policy=tool.model_copy(update={"network_access": "allowlisted"})),
            "network",
        ),
        (
            changed(
                source_scope=source.model_copy(
                    update={"snapshot_ref": ref("source_snapshot", "substituted")}
                )
            ),
            "source snapshot",
        ),
        (
            changed(
                source_scope=source.model_copy(
                    update={"supplied_corpus_refs": (ref("artifact", "extra"),)}
                )
            ),
            "supplied corpus",
        ),
        (
            changed(
                autonomy=autonomy.model_copy(
                    update={"maximum_tier": AutonomyTier.A2_SANDBOXED_PLAN}
                )
            ),
            "autonomy",
        ),
        (
            changed(
                execution_limits=limits.model_copy(
                    update={"hard_timeout_seconds": 601}
                )
            ),
            "timeout",
        ),
        (
            changed(
                execution_limits=limits.model_copy(update={"max_model_calls": 41})
            ),
            "model calls",
        ),
        (
            changed(
                execution_limits=limits.model_copy(update={"max_tool_calls": 51})
            ),
            "tool calls",
        ),
        (
            changed(
                execution_limits=limits.model_copy(
                    update={
                        "workflow_cost": WorkflowCostBoundary(
                            chargeable_work="requires_external_approval",
                            workflow_spend_ceiling_usd="3.000000",
                        )
                    }
                )
            ),
            "workflow spend",
        ),
        (
            changed(
                data_policy=data.model_copy(update={"data_class": DataClass.PUBLIC})
            ),
            "data class",
        ),
        (
            changed(
                data_policy=data.model_copy(
                    update={"processing_purposes": ("product_operation", "support")}
                )
            ),
            "processing purposes",
        ),
        (
            changed(
                data_policy=data.model_copy(
                    update={
                        "retention_policy_ref": RetentionPolicyRef(
                            kind="retention_policy",
                            id="different-retention",
                            revision="1.0.0",
                            digest=VALID_DIGEST,
                        )
                    }
                )
            ),
            "retention policy",
        ),
    )
    for plan, message in broadened:
        with pytest.raises(RunManifestError, match=message):
            resolve_admission(
                plan,
                verified_at=LATER,
                approval_backend=FakeLocalApprovalBackend((approval_record(),)),
            )

    requested_with_checkpoint = requested.model_copy(
        update={
            "autonomy": requested.autonomy.model_copy(
                update={
                    "human_checkpoints": (
                        HumanCheckpoint(
                            checkpoint_id="hcp_spend",
                            kind="spend_approval",
                            trigger="always",
                        ),
                    )
                }
            )
        }
    )
    checkpoint_plan = base.model_copy(update={"task_policy": requested_with_checkpoint})
    with pytest.raises(RunManifestError, match="human checkpoint"):
        resolve_admission(
            checkpoint_plan,
            verified_at=LATER,
            approval_backend=FakeLocalApprovalBackend((approval_record(),)),
        )

    forbidden = policy_bundle()
    chargeable_mode = forbidden.execution_limits.workflow_cost.model_copy(
        update={"chargeable_work": "requires_external_approval"}
    )
    forbidden_effective = forbidden.model_copy(
        update={
            "execution_limits": forbidden.execution_limits.model_copy(
                update={"workflow_cost": chargeable_mode}
            )
        }
    )
    forbidden_plan = base.model_copy(
        update={
            "task_policy": forbidden,
            "effective_policy": forbidden_effective,
        }
    )
    with pytest.raises(RunManifestError, match="chargeable-work"):
        resolve_admission(
            forbidden_plan,
            verified_at=LATER,
            approval_backend=FakeLocalApprovalBackend((approval_record(),)),
        )


@pytest.mark.unit
def test_approval_backend_rejects_missing_expired_resources_and_caps() -> None:
    missing_backend = FakeLocalApprovalBackend()
    with pytest.raises(RunManifestError, match="missing"):
        resolve_admission(
            paid_plan(), verified_at=LATER, approval_backend=missing_backend
        )

    expired = approval_record().model_copy(
        update={"expires_at": "2026-09-06T00:00:00Z"}
    )
    with pytest.raises(RunManifestError, match="expired"):
        resolve_admission(
            paid_plan(),
            verified_at=LATER,
            approval_backend=FakeLocalApprovalBackend((expired,)),
        )

    no_resources = approval_record().model_copy(
        update={"scope": approval_record().scope.model_copy(update={"resources": ()})}
    )
    with pytest.raises(RunManifestError, match="resources"):
        resolve_admission(
            paid_plan(),
            verified_at=LATER,
            approval_backend=FakeLocalApprovalBackend((no_resources,)),
        )

    small_cap = approval_record().model_copy(
        update={
            "scope": approval_record().scope.model_copy(
                update={"workflow_allocation_usd_max": "1.000000"}
            )
        }
    )
    with pytest.raises(RunManifestError, match="workflow cap"):
        resolve_admission(
            paid_plan(),
            verified_at=LATER,
            approval_backend=FakeLocalApprovalBackend((small_cap,)),
        )

    no_cost_with_approval = manifest_fixture().manifest
    no_cost_plan = AdmissionPlan(
        campaign_id="camp_manifest-test",
        stage="stage-0",
        provider="local_mock",
        task_policy=policy_bundle(),
        effective_policy=policy_bundle(),
        platform_workflow_cost_usd="0.000000",
        campaign_workflow_allocation_usd="0.000000",
        provider_workflow_cost_usd="0.000000",
        episode_budget=no_cost_with_approval.payload.budgets.episode,
        provider_metered=False,
        approval_id="approval_paid-test",
    )
    with pytest.raises(RunManifestError, match="masquerade"):
        resolve_admission(
            no_cost_plan,
            verified_at=LATER,
            approval_backend=FakeLocalApprovalBackend((approval_record(),)),
        )


@pytest.mark.unit
def test_store_detects_invalid_envelope_and_sidecar_tampering(tmp_path: Path) -> None:
    store = ManifestFileStore()
    run_dir = tmp_path / "tamper"
    store.seal(run_dir, manifest_fixture().manifest)
    (run_dir / store.sidecar_filename).write_text(
        VALID_DIGEST + "  run-manifest.json\n", encoding="utf-8"
    )
    with pytest.raises(RunManifestError, match="sidecar mismatch"):
        store.load(run_dir)

    invalid_dir = tmp_path / "invalid"
    invalid_dir.mkdir()
    (invalid_dir / store.filename).write_text("{not json", encoding="utf-8")
    (invalid_dir / store.sidecar_filename).write_text(
        VALID_DIGEST + "  run-manifest.json\n", encoding="utf-8"
    )
    with pytest.raises(RunManifestError, match="envelope is invalid"):
        store.load(invalid_dir)


@pytest.mark.unit
def test_receipt_and_resume_failure_edges() -> None:
    manifest = manifest_fixture().manifest
    expected = manifest_compatibility(manifest)
    with pytest.raises(ValidationError, match="running attempts"):
        AttemptReceipt(
            run_id=manifest.payload.identity.run_id,
            attempt_id=new_attempt_id(entropy=uuid.UUID(int=11)),
            manifest_digest=manifest.integrity.payload_sha256,
            started_at=NOW,
            ended_at=LATER,
            outcome="running",
            accumulated_workflow_cost_usd="0.000000",
            accumulated_judge_cost_usd="0.000000",
        )
    with pytest.raises(ValidationError, match="closed attempts"):
        AttemptReceipt(
            run_id=manifest.payload.identity.run_id,
            attempt_id=new_attempt_id(entropy=uuid.UUID(int=12)),
            manifest_digest=manifest.integrity.payload_sha256,
            started_at=NOW,
            outcome="failed",
            accumulated_workflow_cost_usd="0.000000",
            accumulated_judge_cost_usd="0.000000",
        )
    with pytest.raises(ValidationError, match="successful completion"):
        CompletionReceipt(
            run_id=manifest.payload.identity.run_id,
            manifest_digest=manifest.integrity.payload_sha256,
            status=CompletionStatus.SUCCEEDED,
            reason=RunReason.UNKNOWN,
            completed_at=LATER,
            accumulated_workflow_cost_usd="0.000000",
            accumulated_judge_cost_usd="0.000000",
        )
    with pytest.raises(RunManifestError, match="privacy or integrity"):
        validate_resume(
            manifest,
            expected,
            completion=None,
            approval_receipt=None,
            accumulated_workflow_cost_usd="0.000000",
            accumulated_judge_cost_usd="0.000000",
            stopped_for_integrity_or_privacy=True,
        )

    capped_episode = episode_budget(
        workflow="1.000000", judge="1.000000", total="2.000000"
    )
    capped_payload = manifest.payload.model_copy(
        update={
            "budgets": manifest.payload.budgets.model_copy(
                update={
                    "episode": capped_episode,
                    "campaign": CampaignBudget(
                        total_cost_usd_max="3.000000",
                        enforcement="between-episodes-with-in-flight-overshoot-risk",
                    ),
                }
            )
        }
    )
    capped = manifest.model_copy(update={"payload": capped_payload})
    for kwargs, message in (
        ({"accumulated_workflow_cost_usd": "1.000000"}, "workflow budget"),
        ({"accumulated_judge_cost_usd": "1.000000"}, "judge budget"),
        ({"accumulated_campaign_cost_usd": "3.000000"}, "campaign budget"),
    ):
        costs = {
            "accumulated_workflow_cost_usd": "0.000000",
            "accumulated_judge_cost_usd": "0.000000",
            "accumulated_campaign_cost_usd": "0.000000",
            **kwargs,
        }
        with pytest.raises(RunManifestError, match=message):
            validate_resume(
                capped,
                manifest_compatibility(capped),
                completion=None,
                approval_receipt=None,
                **costs,  # type: ignore[arg-type]
            )


@pytest.mark.unit
def test_legacy_source_bytes_arm_matrix_errors_and_schema_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = import_legacy_eval(
        {"elapsed_seconds": 1.25, "workflow_cost_usd": 0.5},
        source_bytes=b"original legacy bytes",
    )
    assert legacy.known_metadata["elapsed_seconds"] == "1.250000"
    assert legacy.source_file_digest == (
        "sha256:7889fbd09e975684914df4c6efdbb5c8219a7832bf6289acd5459532b78b933d"
    )
    with pytest.raises(RunManifestError, match="A-E"):
        validate_arm_matrix((arm("A"), arm("B")))
    monkeypatch.setattr(
        run_manifest_module,
        "sha256_digest",
        lambda _value: VALID_DIGEST,
    )
    with pytest.raises(RunManifestError, match="distinct digest"):
        validate_arm_matrix((arm("A"), arm("B"), arm("C"), arm("D"), arm("E")))
    schemas = run_artifact_json_schemas()
    assert set(schemas) == {
        "run-manifest",
        "policy-runtime-projection",
        "attempt-receipt",
        "completion-receipt",
        "legacy-import",
    }
    assert all(schema["type"] == "object" for schema in schemas.values())
