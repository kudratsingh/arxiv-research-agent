"""Immutable run manifests, admission, and reproducibility primitives.

This module is deliberately control-plane-only.  It imports no runtime
settings, provider SDK, credential loader, agent graph, or network client.
Callers supply already-resolved, immutable snapshots and an approval backend;
the functions here validate, intersect, hash, and persist those values before
any execution side effect is permitted.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import uuid
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, TypeAlias

from pydantic import Field, StringConstraints, model_validator

from src.contracts.kernel import (
    ContractError,
    ContractErrorCode,
    DataClass,
    Digest,
    ImmutableObjectRef,
    MoneyUsd,
    RetentionPolicyRef,
    Rfc3339Utc,
    SemVer,
    StrictContractModel,
    canonical_json,
    require_digest,
    sha256_digest,
)
from src.contracts.task_spec import (
    AutonomyTier,
    CorpusMode,
    TaskPolicyBundle,
    TaskSpecRef,
    TaskSpecV1,
    agent_safe_task_projection,
)

RunId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^run_[a-f0-9]{32}$")]
AttemptId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^att_[a-f0-9]{32}$")]
CampaignId: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^camp_[A-Za-z0-9][A-Za-z0-9_.-]{0,126}$")
]
PolicyMember: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
]
SafeLabel: TypeAlias = Annotated[str, StringConstraints(min_length=1, max_length=256)]
FixedDecimal: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{6}$")
]

_PRIVATE_PATH_RE = re.compile(r"(?:/Users/|/home/|/private/|[A-Za-z]:\\Users\\)")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|token)\s*[:=]\s*\S+"),
)
_FORBIDDEN_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:api_?key|password|passwd|token|cookie|authorization|"
    r"private_?key|request_?headers?|environment_?map|env_?dump|\.env|"
    r"chain_?of_?thought|hidden_?labels?|credential_?(?:hash|fingerprint)|"
    r"secret_?hash)(?:$|_)"
)
_SAFE_SECURITY_KEYS = {
    "raw_secrets_allowed",
    "secret_material_recorded",
    "chain_of_thought_allowed",
}


class RunManifestError(ContractError):
    """Stable failure raised by manifest and admission boundaries."""

    def __init__(
        self,
        detail: str,
        *,
        code: ContractErrorCode = ContractErrorCode.SCHEMA_INVALID,
    ) -> None:
        super().__init__(code, detail)


def _walk(value: Any, *, path: str = "$") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, child
            yield from _walk(child, path=child_path)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, child
            yield from _walk(child, path=child_path)


def validate_manifest_safe_content(value: Any) -> None:
    """Reject secrets, raw evaluator content, and private host paths.

    Hashing a credential is intentionally not an escape hatch.  The contract
    permits only an opaque external credential binding identifier.
    """

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    for path, child in _walk(value):
        key = path.rsplit(".", 1)[-1]
        if "[" not in key and key not in _SAFE_SECURITY_KEYS and _FORBIDDEN_KEY_RE.search(key):
            raise RunManifestError(f"forbidden manifest field at {path}")
        if not isinstance(child, str):
            continue
        if any(pattern.search(child) for pattern in _SECRET_VALUE_PATTERNS):
            raise RunManifestError(f"secret-shaped value at {path}")
        if _PRIVATE_PATH_RE.search(child):
            raise RunManifestError(f"private absolute path at {path}")


class ManifestIntegrity(StrictContractModel):
    algorithm: Literal["sha256"] = "sha256"
    digest_profile: Literal["agent-contract-json/v1"] = "agent-contract-json/v1"
    canonicalization: Literal["RFC8785"] = "RFC8785"
    payload_sha256: Digest


class RunIdentity(StrictContractModel):
    campaign_id: CampaignId
    episode_key: Digest
    replicate_group_id: Digest
    run_id: RunId
    repeat_index: Annotated[int, Field(ge=0)]
    created_at: Rfc3339Utc
    created_by: SafeLabel


class RunLineage(StrictContractModel):
    kind: Literal["rerun", "fork", "migration"]
    parent_run_id: RunId | None = None
    migrated_from_manifest_digest: Digest | None = None
    reason: Annotated[str, StringConstraints(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def parent_matches_kind(self) -> RunLineage:
        if self.kind == "migration":
            if self.migrated_from_manifest_digest is None:
                raise ValueError("migration lineage requires a source manifest digest")
        elif self.parent_run_id is None:
            raise ValueError("rerun and fork lineage require a parent run")
        return self


class CompilationSnapshot(StrictContractModel):
    receipt_ref: ImmutableObjectRef
    receipt_locator: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    occurred_before_run_events: Literal[True] = True

    @model_validator(mode="after")
    def receipt_kind(self) -> CompilationSnapshot:
        if self.receipt_ref.kind != "compilation_receipt":
            raise ValueError("compilation receipt ref has the wrong kind")
        return self


class RegistryVisibility(StrictContractModel):
    split_assignment: Literal["control-plane-only"] = "control-plane-only"
    rubric_set: Literal["mixed-projected"] = "mixed-projected"
    grader_profile: Literal["evaluator-only"] = "evaluator-only"
    label_set: Literal["evaluator-only"] = "evaluator-only"
    source_snapshot: Literal["task-authorized-content-only"] = (
        "task-authorized-content-only"
    )


class RegistryResolution(StrictContractModel):
    suite_ref: ImmutableObjectRef
    task_set_ref: ImmutableObjectRef
    task_case_ref: ImmutableObjectRef
    split_assignment_ref: ImmutableObjectRef
    rubric_set_refs: tuple[ImmutableObjectRef, ...]
    grader_profile_refs: tuple[ImmutableObjectRef, ...]
    label_set_refs: tuple[ImmutableObjectRef, ...] = ()
    source_snapshot_ref: ImmutableObjectRef | None = None
    visibility: RegistryVisibility = RegistryVisibility()
    validation_receipt_ref: ImmutableObjectRef

    @model_validator(mode="after")
    def references_have_expected_kinds(self) -> RegistryResolution:
        singular = (
            (self.suite_ref, "benchmark_suite"),
            (self.task_set_ref, "task_set"),
            (self.task_case_ref, "task_case"),
            (self.split_assignment_ref, "split_assignment"),
            (self.validation_receipt_ref, "registry_validation_receipt"),
        )
        for ref, expected in singular:
            if ref.kind != expected:
                raise ValueError(f"registry resolution expected {expected}, got {ref.kind}")
        groups = (
            (self.rubric_set_refs, "rubric_set"),
            (self.grader_profile_refs, "grader_profile"),
            (self.label_set_refs, "label_set"),
        )
        for refs, expected in groups:
            if any(ref.kind != expected for ref in refs):
                raise ValueError(f"registry resolution contains a non-{expected} ref")
            keys = [(ref.id, ref.revision, ref.digest) for ref in refs]
            if len(keys) != len(set(keys)):
                raise ValueError(f"registry {expected} refs must be unique")
        if not self.rubric_set_refs or not self.grader_profile_refs:
            raise ValueError("registry resolution requires rubric and grader refs")
        if self.source_snapshot_ref is not None and self.source_snapshot_ref.kind != "source_snapshot":
            raise ValueError("source snapshot ref has the wrong kind")
        return self


class PolicyCapabilities(StrictContractModel):
    supervisor: bool
    evidence_store: bool
    fixed_post_synthesis_verifier: bool
    adaptive_compute: bool


class RuntimeFlags(StrictContractModel):
    enable_supervisor: bool
    enable_evidence_store: bool
    enable_verifier: bool
    enable_query_refiner: bool = False
    enable_reader_recovery: bool = False


class PolicyConfig(StrictContractModel):
    allowed_tiers: tuple[Literal["T0", "T1", "T2"], ...] = ()
    default_tier: Literal["T0", "T1", "T2"] | None = None
    difficulty_features_version: SemVer | None = None
    max_targeted_repairs: Annotated[int, Field(ge=0, le=10)] = 0
    max_branches: Annotated[int | None, Field(ge=1, le=16)] = None
    selection: Literal["listwise"] | None = None
    marginal_stop_policy_version: SemVer | None = None
    allowed_repairs: tuple[PolicyMember, ...] = ()
    reverify_repaired_subject: bool = False


class PolicySnapshot(StrictContractModel):
    arm_id: Literal["A", "B", "C", "D", "E"]
    selector: Literal[
        "fixed",
        "fixed_evidence",
        "fixed_verify_repair",
        "supervisor_verified",
        "adaptive_verified",
    ]
    policy_version: SafeLabel
    graph_digest: Digest
    graph_capabilities: tuple[PolicyMember, ...]
    config_schema: SafeLabel
    runtime_flags: RuntimeFlags
    config: PolicyConfig
    capabilities: PolicyCapabilities

    @model_validator(mode="after")
    def validate_arm_structure(self) -> PolicySnapshot:
        expected_selector = {
            "A": "fixed",
            "B": "fixed_evidence",
            "C": "fixed_verify_repair",
            "D": "supervisor_verified",
            "E": "adaptive_verified",
        }[self.arm_id]
        if self.selector != expected_selector:
            raise ValueError("arm id and selector do not match")
        flags = self.runtime_flags
        if self.arm_id == "A" and (flags.enable_supervisor or flags.enable_evidence_store or flags.enable_verifier):
            raise ValueError("Arm A must disable supervisor, evidence, and verifier")
        if self.arm_id == "B" and (flags.enable_supervisor or not flags.enable_evidence_store or flags.enable_verifier):
            raise ValueError("Arm B requires evidence only")
        if self.arm_id == "C":
            if flags.enable_supervisor or not flags.enable_evidence_store or flags.enable_verifier:
                raise ValueError("Arm C is a fixed graph with evidence and a structural verifier")
            if "fixed_post_synthesis_verifier" not in self.graph_capabilities:
                raise ValueError("Arm C graph lacks fixed_post_synthesis_verifier")
            if not self.capabilities.fixed_post_synthesis_verifier:
                raise ValueError("Arm C must declare its fixed verifier capability")
            if self.config.max_targeted_repairs != 1 or not self.config.reverify_repaired_subject:
                raise ValueError("Arm C requires one targeted repair and re-verification")
        if self.arm_id == "D" and not (
            flags.enable_supervisor and flags.enable_evidence_store and flags.enable_verifier
        ):
            raise ValueError("Arm D requires supervisor, evidence, and verifier")
        if self.arm_id == "E":
            if not (flags.enable_supervisor and flags.enable_evidence_store and flags.enable_verifier):
                raise ValueError("Arm E requires supervisor, evidence, and verifier")
            if not self.capabilities.adaptive_compute:
                raise ValueError("Arm E must declare adaptive compute")
            required_graph_capabilities = {
                "adaptive_compute_router",
                "candidate_branching",
                "marginal_stop",
            }
            if not required_graph_capabilities <= set(self.graph_capabilities):
                raise ValueError("Arm E graph lacks adaptive routing capabilities")
            required_tiers = ("T0", "T1", "T2")
            if self.config.allowed_tiers != required_tiers or self.config.default_tier is None:
                raise ValueError("Arm E requires ordered T0-T2 compute tiers and a default")
            if any(
                item is None
                for item in (
                    self.config.difficulty_features_version,
                    self.config.max_branches,
                    self.config.selection,
                    self.config.marginal_stop_policy_version,
                )
            ):
                raise ValueError("Arm E requires router, branch, selection, and stop configuration")
        return self


class RuntimeConfigSnapshot(StrictContractModel):
    settings_schema_digest: Digest
    effective_values: Mapping[str, str | int | bool | None]
    effective_values_digest: Digest

    @model_validator(mode="after")
    def values_match_digest(self) -> RuntimeConfigSnapshot:
        require_digest(dict(self.effective_values), self.effective_values_digest)
        return self


class InvocationSnapshot(StrictContractModel):
    enable_hitl: bool
    hitl_bypass: bool
    hitl_bypass_reason: SafeLabel | None = None
    checkpoint_mode: Literal["disabled", "memory", "persistent"]

    @model_validator(mode="after")
    def bypass_is_explained(self) -> InvocationSnapshot:
        if self.hitl_bypass and self.hitl_bypass_reason is None:
            raise ValueError("HITL bypass requires a reason")
        return self


class SamplingSnapshot(StrictContractModel):
    temperature: FixedDecimal
    top_p: FixedDecimal | None = None
    top_k: Annotated[int | None, Field(ge=1)] = None
    maximum_output_tokens: Annotated[int, Field(ge=1)]
    provider_seed: int | None = None


class CredentialBinding(StrictContractModel):
    present: bool
    binding_ref: Annotated[
        str, StringConstraints(pattern=r"^credential-binding://[A-Za-z0-9._/-]+$")
    ] | None = None
    value_recorded: Literal[False] = False
    fingerprint_recorded: Literal[False] = False

    @model_validator(mode="after")
    def configured_binding_has_ref(self) -> CredentialBinding:
        if self.present != (self.binding_ref is not None):
            raise ValueError("credential presence and opaque binding ref disagree")
        return self


class RetrySnapshot(StrictContractModel):
    timeout_seconds: Annotated[int, Field(ge=1, le=86_400)]
    max_retries: Annotated[int, Field(ge=0, le=20)]
    fallback: Literal["none", "declared-routes-only"] = "none"


class LlmProviderSnapshot(StrictContractModel):
    provider: PolicyMember
    api_protocol_version: SafeLabel
    model_resolution: Literal["exact-id-required", "alias"]
    routes: Mapping[PolicyMember, SafeLabel]
    sampling: SamplingSnapshot
    retry: RetrySnapshot
    prompt_cache: Literal["disabled", "enabled"]
    credential: CredentialBinding
    metered: bool

    @model_validator(mode="after")
    def routes_are_present(self) -> LlmProviderSnapshot:
        if not self.routes:
            raise ValueError("provider snapshot requires at least one model route")
        return self


class PricingSnapshot(StrictContractModel):
    currency: Literal["USD"] = "USD"
    table_ref: ImmutableObjectRef
    prices_last_verified: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]


class ProviderSnapshot(StrictContractModel):
    llm: LlmProviderSnapshot
    pricing: PricingSnapshot


class PolicyProviderProjection(StrictContractModel):
    """Workflow routing safe for candidate code; no credential or pricing data."""

    provider: PolicyMember
    api_protocol_version: SafeLabel
    model_resolution: Literal["exact-id-required", "alias"]
    routes: Mapping[PolicyMember, SafeLabel]
    sampling: SamplingSnapshot
    retry: RetrySnapshot
    prompt_cache: Literal["disabled", "enabled"]


class PromptSnapshot(StrictContractModel):
    bundle_ref: ImmutableObjectRef
    renderer_digest: Digest
    prompt_isolation: Literal["enabled"] = "enabled"
    raw_rendered_prompts_in_manifest: Literal[False] = False


class ToolSnapshot(StrictContractModel):
    registry_ref: ImmutableObjectRef
    implementation_refs: tuple[ImmutableObjectRef, ...]
    agent_invocable: tuple[PolicyMember, ...]
    internal_components: tuple[PolicyMember, ...]
    denied: tuple[PolicyMember, ...]
    network_policy: Literal["none", "allowlisted"]
    filesystem_policy: Literal["none", "read-only", "sandbox"]
    tool_result_capture: Literal["none", "content-addressed-redacted"]

    @model_validator(mode="after")
    def tool_sets_are_coherent(self) -> ToolSnapshot:
        for values in (self.agent_invocable, self.internal_components, self.denied):
            if len(values) != len(set(values)):
                raise ValueError("tool snapshot collections must be unique")
        if set(self.agent_invocable) & set(self.denied):
            raise ValueError("an agent tool cannot be both allowed and denied")
        return self


class SourceSnapshot(StrictContractModel):
    input_corpus_mode: CorpusMode
    observation_capture_mode: Literal["none", "recorded"]
    source_policy_ref: ImmutableObjectRef
    source_snapshot_ref: ImmutableObjectRef | None = None
    live_access_allowed: bool

    @model_validator(mode="after")
    def source_mode_is_consistent(self) -> SourceSnapshot:
        if self.source_policy_ref.kind != "source_policy":
            raise ValueError("source_policy_ref has the wrong kind")
        if self.input_corpus_mode is CorpusMode.SNAPSHOT:
            if self.source_snapshot_ref is None or self.source_snapshot_ref.kind != "source_snapshot":
                raise ValueError("snapshot corpus mode requires a source_snapshot ref")
            if self.live_access_allowed:
                raise ValueError("snapshot corpus mode cannot allow live access")
        elif self.source_snapshot_ref is not None:
            raise ValueError("only snapshot corpus mode carries source_snapshot_ref")
        if self.input_corpus_mode is CorpusMode.LIVE and not self.live_access_allowed:
            raise ValueError("live corpus mode must permit live access")
        return self


class EvaluationBudget(StrictContractModel):
    currency: Literal["USD"] = "USD"
    cost_usd_max: MoneyUsd
    model_calls_max: Annotated[int, Field(ge=0)]


class EvaluationSnapshot(StrictContractModel):
    candidate_visibility: Literal["control-plane-only"] = "control-plane-only"
    grader_profile_refs: tuple[ImmutableObjectRef, ...]
    judge_routes: Mapping[PolicyMember, SafeLabel]
    judge_prompt_bundle_ref: ImmutableObjectRef
    calibration_ref: ImmutableObjectRef | None = None
    blinding_policy: SafeLabel
    ordering_policy: SafeLabel
    sampling: SamplingSnapshot
    retry: RetrySnapshot
    null_score_policy: SafeLabel
    budget: EvaluationBudget


class DeterminismClass(StrEnum):
    DETERMINISTIC_LOCAL = "deterministic-local"
    SNAPSHOT_INPUT_SEEDED_MODEL = "snapshot-input-seeded-model"
    RECORDED_OBSERVATIONS_STOCHASTIC_MODEL = "recorded-observations-stochastic-model"
    LIVE_INPUT_STOCHASTIC_MODEL = "live-input-stochastic-model"


class RandomnessSnapshot(StrictContractModel):
    repeat_index: Annotated[int, Field(ge=0)]
    root_seed: int
    derivation: Literal["hmac-sha256(root_seed, component-name)"] = (
        "hmac-sha256(root_seed, component-name)"
    )
    component_seeds_ref: ImmutableObjectRef
    provider_seed: int | None = None
    determinism_class: DeterminismClass


class AdmissionCeilings(StrictContractModel):
    task_workflow_cost_usd: MoneyUsd
    platform_workflow_cost_usd: MoneyUsd
    campaign_workflow_allocation_usd: MoneyUsd
    provider_workflow_cost_usd: MoneyUsd
    approval_workflow_allocation_usd: MoneyUsd


class ResolvedLimits(StrictContractModel):
    hard_timeout_seconds: Annotated[int, Field(ge=1)]
    model_calls_max: Annotated[int, Field(ge=0)]
    tool_calls_max: Annotated[int, Field(ge=0)]
    autonomy_tier_max: AutonomyTier
    external_side_effects: Literal["none"] = "none"
    allowed_agent_tools: tuple[PolicyMember, ...]
    allowed_source_providers: tuple[PolicyMember, ...]


class AdmissionResolution(StrictContractModel):
    resolver_version: Literal["admission-controller/1.0.0"] = "admission-controller/1.0.0"
    input_workflow_ceilings: AdmissionCeilings
    resolved_workflow_cost_usd: MoneyUsd
    cost_derivation: Literal["minimum-of-all-input-ceilings"] = (
        "minimum-of-all-input-ceilings"
    )
    resolved_limits: ResolvedLimits
    task_permissions_narrowed_or_equal: Literal[True] = True
    receipt_ref: ImmutableObjectRef

    @model_validator(mode="after")
    def cost_is_the_minimum(self) -> AdmissionResolution:
        values = self.input_workflow_ceilings.model_dump(mode="json").values()
        expected = f"{min(Decimal(value) for value in values):.6f}"
        if self.resolved_workflow_cost_usd != expected:
            raise ValueError("resolved workflow cost is not the minimum ceiling")
        if self.receipt_ref.kind != "admission_receipt":
            raise ValueError("admission receipt ref has the wrong kind")
        return self


class EpisodeBudget(StrictContractModel):
    currency: Literal["USD"] = "USD"
    workflow_cost_usd_max: MoneyUsd
    judge_cost_usd_max: MoneyUsd
    paid_tool_cost_usd_max: MoneyUsd = "0.000000"
    infrastructure_cost_usd_max: MoneyUsd = "0.000000"
    total_cost_usd_max: MoneyUsd
    wall_time_seconds_max: Annotated[int, Field(ge=1)]
    workflow_model_calls_max: Annotated[int, Field(ge=0)]
    judge_model_calls_max: Annotated[int, Field(ge=0)]
    tool_calls_max: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def total_covers_components(self) -> EpisodeBudget:
        component_total = sum(
            Decimal(value)
            for value in (
                self.workflow_cost_usd_max,
                self.judge_cost_usd_max,
                self.paid_tool_cost_usd_max,
                self.infrastructure_cost_usd_max,
            )
        )
        if Decimal(self.total_cost_usd_max) < component_total:
            raise ValueError("episode total cost cap is lower than component caps")
        return self


class CampaignBudget(StrictContractModel):
    currency: Literal["USD"] = "USD"
    total_cost_usd_max: MoneyUsd
    enforcement: Literal[
        "between-episodes-with-in-flight-overshoot-risk",
        "pre-call-reservation",
    ]


class BudgetSnapshot(StrictContractModel):
    episode: EpisodeBudget
    campaign: CampaignBudget


class ApprovalScope(StrictContractModel):
    campaign_id: CampaignId
    providers: tuple[PolicyMember, ...]
    stages: tuple[PolicyMember, ...]
    resources: tuple[PolicyMember, ...] = ()
    total_cost_usd_max: MoneyUsd
    episode_allocation_usd_max: MoneyUsd
    workflow_allocation_usd_max: MoneyUsd
    judge_allocation_usd_max: MoneyUsd

    @model_validator(mode="after")
    def scope_is_bounded(self) -> ApprovalScope:
        if not self.providers or not self.stages:
            raise ValueError("approval scope requires providers and stages")
        if any(
            len(values) != len(set(values))
            for values in (self.providers, self.stages, self.resources)
        ):
            raise ValueError("approval scope collections must be unique")
        if Decimal(self.workflow_allocation_usd_max) + Decimal(
            self.judge_allocation_usd_max
        ) > Decimal(self.episode_allocation_usd_max):
            raise ValueError("approval component allocations exceed episode allocation")
        if Decimal(self.episode_allocation_usd_max) > Decimal(self.total_cost_usd_max):
            raise ValueError("approval episode allocation exceeds total cap")
        return self


class ApprovalStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    APPROVED = "approved"
    PENDING = "pending"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ApprovalRecord(StrictContractModel):
    approval_id: Annotated[str, StringConstraints(pattern=r"^approval_[a-z0-9-]{8,64}$")]
    status: ApprovalStatus
    scope: ApprovalScope
    approved_by: SafeLabel
    approved_at: Rfc3339Utc
    expires_at: Rfc3339Utc
    record_digest: Digest

    @model_validator(mode="after")
    def validity_window_is_forward(self) -> ApprovalRecord:
        if self.approved_at >= self.expires_at:
            raise ValueError("approval expiry must follow approval time")
        return self


class ApprovalVerificationReceipt(StrictContractModel):
    schema_kind: Literal["approval-verification-receipt"] = (
        "approval-verification-receipt"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    approval_id: str
    campaign_id: CampaignId
    stage: PolicyMember
    verified_at: Rfc3339Utc
    record_digest: Digest
    remaining_cost_usd: MoneyUsd
    valid: Literal[True] = True


class ApprovalSnapshot(StrictContractModel):
    required: bool
    status_at_seal: ApprovalStatus
    not_required_reason: SafeLabel | None = None
    approval_id: str | None = None
    record_ref: Annotated[str, StringConstraints(pattern=r"^approval-record://[A-Za-z0-9._/-]+$")] | None = None
    record_digest: Digest | None = None
    authoritative_source: Literal["external-approval-record", "local-no-cost"]
    scope: ApprovalScope | None = None
    approved_by: SafeLabel | None = None
    approved_at: Rfc3339Utc | None = None
    expires_at: Rfc3339Utc | None = None
    admission_verification_receipt_ref: ImmutableObjectRef | None = None
    resume_requires_fresh_verification_receipt: Literal[True] = True
    secret_material_recorded: Literal[False] = False

    @model_validator(mode="after")
    def state_is_coherent(self) -> ApprovalSnapshot:
        approved_fields = (
            self.approval_id,
            self.record_ref,
            self.record_digest,
            self.scope,
            self.approved_by,
            self.approved_at,
            self.expires_at,
            self.admission_verification_receipt_ref,
        )
        if self.required:
            if self.status_at_seal is not ApprovalStatus.APPROVED or any(
                value is None for value in approved_fields
            ):
                raise ValueError("required approval must be approved and fully referenced")
            if self.not_required_reason is not None:
                raise ValueError("required approval cannot have a not-required reason")
        else:
            if self.status_at_seal is not ApprovalStatus.NOT_REQUIRED:
                raise ValueError("unrequired approval must use not_required status")
            if self.not_required_reason is None or any(value is not None for value in approved_fields):
                raise ValueError("no-cost approval snapshot must contain only its reason")
        return self


class CodeSnapshot(StrictContractModel):
    repository: SafeLabel
    commit_sha: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    worktree_state: Literal["clean", "dirty"]
    patch_digest: Digest | None = None
    policy_subtree_digest: Digest
    prompt_subtree_digest: Digest
    tool_subtree_digest: Digest
    promotion_eligible: bool

    @model_validator(mode="after")
    def dirty_state_is_honest(self) -> CodeSnapshot:
        if self.worktree_state == "dirty":
            if self.patch_digest is None or self.promotion_eligible:
                raise ValueError("dirty worktrees require a patch digest and are not promotable")
        elif self.patch_digest is not None:
            raise ValueError("clean worktrees cannot carry a patch digest")
        return self


class EnvironmentSnapshot(StrictContractModel):
    execution_class: Literal["local-test", "local-eval", "ci", "production"]
    python_version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    platform: SafeLabel
    dependency_lock_ref: ImmutableObjectRef
    container_image_digest: Digest | None = None
    locale: SafeLabel
    timezone: SafeLabel


class OutputSnapshot(StrictContractModel):
    root: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")]
    artifact_schema_version: SemVer
    trajectory_schema_version: SemVer
    verification_schema_version: SemVer


class PrivacySnapshot(StrictContractModel):
    task_data_class: DataClass
    registry_object_classification: DataClass
    retention_policy_ref: RetentionPolicyRef
    redaction_policy_version: SemVer
    raw_secrets_allowed: Literal[False] = False
    raw_environment_allowed: Literal[False] = False
    chain_of_thought_allowed: Literal[False] = False


class PolicyRuntimeProjectionRef(StrictContractModel):
    schema_kind: Literal["policy-runtime-projection"] = "policy-runtime-projection"
    schema_version: Literal["1.0.0"] = "1.0.0"
    artifact_ref: ImmutableObjectRef
    artifact_locator: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    excluded_classes: tuple[
        Literal[
            "sealed-case-and-split-identity",
            "evaluator-and-label-refs",
            "approval-metadata",
            "private-object-locators",
            "hidden-rubric-content",
        ],
        ...,
    ]

    @model_validator(mode="after")
    def complete_exclusion_set(self) -> PolicyRuntimeProjectionRef:
        required = {
            "sealed-case-and-split-identity",
            "evaluator-and-label-refs",
            "approval-metadata",
            "private-object-locators",
            "hidden-rubric-content",
        }
        if set(self.excluded_classes) != required:
            raise ValueError("runtime projection must declare every excluded control-plane class")
        if self.artifact_ref.kind != "policy_runtime_projection":
            raise ValueError("runtime projection artifact ref has the wrong kind")
        return self


class RunManifestPayload(StrictContractModel):
    identity: RunIdentity
    lineage: RunLineage | None
    compilation: CompilationSnapshot
    task: TaskSpecRef
    campaign_lock_ref: ImmutableObjectRef
    campaign_lock_locator: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    registry_resolution: RegistryResolution
    policy: PolicySnapshot
    runtime_config: RuntimeConfigSnapshot
    invocation: InvocationSnapshot
    providers: ProviderSnapshot
    prompts: PromptSnapshot
    tools: ToolSnapshot
    sources: SourceSnapshot
    evaluation: EvaluationSnapshot
    randomness: RandomnessSnapshot
    admission_resolution: AdmissionResolution
    budgets: BudgetSnapshot
    approval: ApprovalSnapshot
    code: CodeSnapshot
    environment: EnvironmentSnapshot
    outputs: OutputSnapshot
    privacy: PrivacySnapshot
    policy_runtime_projection: PolicyRuntimeProjectionRef

    @model_validator(mode="after")
    def cross_section_invariants(self) -> RunManifestPayload:
        if self.campaign_lock_ref.kind != "campaign_lock":
            raise ValueError("campaign lock ref has the wrong kind")
        if self.identity.repeat_index != self.randomness.repeat_index:
            raise ValueError("identity and randomness repeat indexes differ")
        if self.task.effective_data_class != self.privacy.task_data_class:
            raise ValueError("TaskSpec and privacy data classes differ")
        if self.sources.source_snapshot_ref != self.registry_resolution.source_snapshot_ref:
            raise ValueError("registry and source snapshots differ")
        external = any(
            Decimal(value) > 0
            for value in (
                self.budgets.episode.workflow_cost_usd_max,
                self.budgets.episode.judge_cost_usd_max,
                self.budgets.episode.paid_tool_cost_usd_max,
                self.budgets.episode.infrastructure_cost_usd_max,
            )
        )
        if self.approval.required != (self.providers.llm.metered or external):
            raise ValueError("approval requirement does not match chargeable resources")
        if self.admission_resolution.resolved_workflow_cost_usd != self.budgets.episode.workflow_cost_usd_max:
            raise ValueError("admission and episode workflow caps differ")
        if self.policy.runtime_flags.enable_supervisor != self.policy.capabilities.supervisor:
            raise ValueError("supervisor flag and capability disagree")
        if self.policy.runtime_flags.enable_evidence_store != self.policy.capabilities.evidence_store:
            raise ValueError("evidence flag and capability disagree")
        validate_manifest_safe_content(self.model_dump(mode="json"))
        return self

class RunManifestV1(StrictContractModel):
    schema_kind: Literal["run-manifest"] = "run-manifest"
    schema_version: Literal["1.0.0"] = "1.0.0"
    object_revision: Literal[1] = 1
    payload: RunManifestPayload
    integrity: ManifestIntegrity

    @model_validator(mode="after")
    def verify_integrity(self) -> RunManifestV1:
        require_digest(self.payload, self.integrity.payload_sha256)
        return self


class PolicyRuntimeProjectionPayload(StrictContractModel):
    identity: Mapping[str, str | int]
    task: Mapping[str, Any]
    policy: PolicySnapshot
    runtime_config: RuntimeConfigSnapshot
    invocation: InvocationSnapshot
    workflow_provider: PolicyProviderProjection
    prompts: PromptSnapshot
    tools: ToolSnapshot
    sources: SourceSnapshot
    limits: ResolvedLimits

    @model_validator(mode="after")
    def candidate_payload_is_safe(self) -> PolicyRuntimeProjectionPayload:
        validate_manifest_safe_content(self.model_dump(mode="json"))
        return self


class PolicyRuntimeProjection(StrictContractModel):
    schema_kind: Literal["policy-runtime-projection"] = "policy-runtime-projection"
    schema_version: Literal["1.0.0"] = "1.0.0"
    payload: PolicyRuntimeProjectionPayload
    integrity: ManifestIntegrity

    @model_validator(mode="after")
    def verify_integrity(self) -> PolicyRuntimeProjection:
        require_digest(self.payload, self.integrity.payload_sha256)
        return self


def seal_manifest(payload: RunManifestPayload) -> RunManifestV1:
    """Hash an already validated payload into an immutable envelope."""

    # Revalidate the serialized value so an unchecked ``model_copy(update=...)``
    # cannot smuggle an invalid nested model across the sealing boundary.
    payload = RunManifestPayload.model_validate(payload.model_dump(mode="python"))
    validate_manifest_safe_content(payload)
    return RunManifestV1(
        payload=payload,
        integrity=ManifestIntegrity(payload_sha256=sha256_digest(payload)),
    )


def build_policy_runtime_projection(
    manifest: RunManifestV1,
    task_spec: TaskSpecV1,
) -> PolicyRuntimeProjection:
    """Derive the only manifest projection candidate policy code may receive."""

    if manifest.payload.task.task_spec_id != task_spec.task_spec_id:
        raise RunManifestError("projection TaskSpec id does not match manifest")
    if manifest.payload.task.full_digest != sha256_digest(task_spec):
        # TaskSpec full digests use the same profile; this refuses substitution.
        raise RunManifestError("projection TaskSpec digest does not match manifest")
    if manifest.payload.sources.input_corpus_mode is not task_spec.source_scope.corpus_mode:
        raise RunManifestError("projection source mode does not match TaskSpec")
    if not set(manifest.payload.tools.agent_invocable) <= set(
        task_spec.tool_policy.allowed_agent_tools
    ):
        raise RunManifestError("projection tools broaden TaskSpec")
    payload = PolicyRuntimeProjectionPayload(
        identity={
            "campaign_id": manifest.payload.identity.campaign_id,
            "run_id": manifest.payload.identity.run_id,
            "repeat_index": manifest.payload.identity.repeat_index,
        },
        task=agent_safe_task_projection(task_spec),
        policy=manifest.payload.policy,
        runtime_config=manifest.payload.runtime_config,
        invocation=manifest.payload.invocation,
        workflow_provider=PolicyProviderProjection(
            provider=manifest.payload.providers.llm.provider,
            api_protocol_version=manifest.payload.providers.llm.api_protocol_version,
            model_resolution=manifest.payload.providers.llm.model_resolution,
            routes=manifest.payload.providers.llm.routes,
            sampling=manifest.payload.providers.llm.sampling,
            retry=manifest.payload.providers.llm.retry,
            prompt_cache=manifest.payload.providers.llm.prompt_cache,
        ),
        prompts=manifest.payload.prompts,
        tools=manifest.payload.tools,
        sources=manifest.payload.sources,
        limits=manifest.payload.admission_resolution.resolved_limits,
    )
    projection = PolicyRuntimeProjection(
        payload=payload,
        integrity=ManifestIntegrity(payload_sha256=sha256_digest(payload)),
    )
    if (
        projection.integrity.payload_sha256
        != manifest.payload.policy_runtime_projection.artifact_ref.digest
    ):
        raise RunManifestError("runtime projection digest does not match manifest ref")
    return projection


def derive_replicate_group_id(
    campaign_id: str,
    task: TaskSpecRef,
    arm_digest: Digest,
) -> str:
    return sha256_digest(
        {
            "campaign_id": campaign_id,
            "task_spec_id": task.task_spec_id,
            "task_revision": task.task_revision,
            "task_semantic_digest": task.semantic_digest,
            "arm_digest": arm_digest,
        }
    )


def derive_episode_key(replicate_group_id: Digest, repeat_index: int) -> str:
    if repeat_index < 0:
        raise RunManifestError("repeat index must be non-negative")
    return sha256_digest(
        {"replicate_group_id": replicate_group_id, "repeat_index": repeat_index}
    )


def new_run_id(*, entropy: uuid.UUID | None = None) -> str:
    return f"run_{(entropy or uuid.uuid4()).hex}"


def new_attempt_id(*, entropy: uuid.UUID | None = None) -> str:
    return f"att_{(entropy or uuid.uuid4()).hex}"


class ApprovalBackend(Protocol):
    def verify(
        self,
        approval_id: str,
        *,
        campaign_id: str,
        stage: str,
        provider: str,
        resources: tuple[str, ...],
        required_total_usd: MoneyUsd,
        required_episode_usd: MoneyUsd,
        required_workflow_usd: MoneyUsd,
        required_judge_usd: MoneyUsd,
        verified_at: Rfc3339Utc,
    ) -> tuple[ApprovalRecord, ApprovalVerificationReceipt]: ...


class FakeLocalApprovalBackend:
    """Deterministic in-memory approval verifier for tests and Stage 0."""

    def __init__(self, records: Iterable[ApprovalRecord] = ()) -> None:
        self._records = {record.approval_id: record for record in records}
        self.calls = 0

    def verify(
        self,
        approval_id: str,
        *,
        campaign_id: str,
        stage: str,
        provider: str,
        resources: tuple[str, ...],
        required_total_usd: MoneyUsd,
        required_episode_usd: MoneyUsd,
        required_workflow_usd: MoneyUsd,
        required_judge_usd: MoneyUsd,
        verified_at: Rfc3339Utc,
    ) -> tuple[ApprovalRecord, ApprovalVerificationReceipt]:
        self.calls += 1
        try:
            record = self._records[approval_id]
        except KeyError as exc:
            raise RunManifestError("approval is missing") from exc
        if record.status is not ApprovalStatus.APPROVED:
            raise RunManifestError(f"approval status is {record.status.value}")
        if record.expires_at <= verified_at:
            raise RunManifestError("approval is expired")
        scope = record.scope
        if scope.campaign_id != campaign_id:
            raise RunManifestError("approval campaign does not match")
        if provider not in scope.providers:
            raise RunManifestError("approval provider does not match")
        if stage not in scope.stages:
            raise RunManifestError("approval stage does not match")
        if not set(resources) <= set(scope.resources):
            raise RunManifestError("approval resources do not cover the plan")
        required_caps = (
            (required_total_usd, scope.total_cost_usd_max, "total"),
            (required_episode_usd, scope.episode_allocation_usd_max, "episode"),
            (required_workflow_usd, scope.workflow_allocation_usd_max, "workflow"),
            (required_judge_usd, scope.judge_allocation_usd_max, "judge"),
        )
        for required, allowed, name in required_caps:
            if Decimal(required) > Decimal(allowed):
                raise RunManifestError(f"approval {name} cap is insufficient")
        remaining = f"{Decimal(scope.total_cost_usd_max) - Decimal(required_total_usd):.6f}"
        receipt = ApprovalVerificationReceipt(
            approval_id=approval_id,
            campaign_id=campaign_id,
            stage=stage,
            verified_at=verified_at,
            record_digest=record.record_digest,
            remaining_cost_usd=remaining,
        )
        return record, receipt


class AdmissionPlan(StrictContractModel):
    campaign_id: CampaignId
    stage: PolicyMember
    provider: PolicyMember
    resources: tuple[PolicyMember, ...] = ()
    task_policy: TaskPolicyBundle
    effective_policy: TaskPolicyBundle
    platform_workflow_cost_usd: MoneyUsd
    campaign_workflow_allocation_usd: MoneyUsd
    provider_workflow_cost_usd: MoneyUsd
    episode_budget: EpisodeBudget
    provider_metered: bool
    approval_id: str | None = None


class AdmissionDecision(StrictContractModel):
    resolution: AdmissionResolution
    approval: ApprovalSnapshot
    approval_receipt: ApprovalVerificationReceipt | None
    chargeable: bool


def _is_subset(left: tuple[Any, ...], right: tuple[Any, ...]) -> bool:
    return set(left) <= set(right)


def _validate_policy_narrowing(plan: AdmissionPlan) -> None:
    requested = plan.task_policy
    effective = plan.effective_policy
    if effective.source_scope.corpus_mode is not requested.source_scope.corpus_mode:
        raise RunManifestError("effective corpus mode changed the task boundary")
    if not _is_subset(effective.source_scope.allowed_providers, requested.source_scope.allowed_providers):
        raise RunManifestError("effective source providers broaden TaskSpec")
    if not _is_subset(effective.source_scope.allowed_source_types, requested.source_scope.allowed_source_types):
        raise RunManifestError("effective source types broaden TaskSpec")
    if not _is_subset(effective.tool_policy.allowed_agent_tools, requested.tool_policy.allowed_agent_tools):
        raise RunManifestError("effective tools broaden TaskSpec")
    if not set(requested.tool_policy.denied_action_ids) <= set(effective.tool_policy.denied_action_ids):
        raise RunManifestError("effective policy removes a TaskSpec denial")
    if (
        requested.tool_policy.network_access == "none"
        and effective.tool_policy.network_access != "none"
    ):
        raise RunManifestError("effective network access broadens TaskSpec")
    if effective.source_scope.snapshot_ref != requested.source_scope.snapshot_ref:
        raise RunManifestError("effective source snapshot changes TaskSpec")
    if effective.source_scope.supplied_corpus_refs != requested.source_scope.supplied_corpus_refs:
        raise RunManifestError("effective supplied corpus changes TaskSpec")
    if effective.autonomy.maximum_tier.rank > requested.autonomy.maximum_tier.rank:
        raise RunManifestError("effective autonomy broadens TaskSpec")
    requested_checkpoints = {
        checkpoint.checkpoint_id for checkpoint in requested.autonomy.human_checkpoints
    }
    effective_checkpoints = {
        checkpoint.checkpoint_id for checkpoint in effective.autonomy.human_checkpoints
    }
    if not requested_checkpoints <= effective_checkpoints:
        raise RunManifestError("effective policy removes a TaskSpec human checkpoint")
    if effective.execution_limits.hard_timeout_seconds > requested.execution_limits.hard_timeout_seconds:
        raise RunManifestError("effective timeout broadens TaskSpec")
    if effective.execution_limits.max_model_calls > requested.execution_limits.max_model_calls:
        raise RunManifestError("effective model calls broaden TaskSpec")
    if effective.execution_limits.max_tool_calls > requested.execution_limits.max_tool_calls:
        raise RunManifestError("effective tool calls broaden TaskSpec")
    if Decimal(effective.execution_limits.workflow_cost.workflow_spend_ceiling_usd) > Decimal(
        requested.execution_limits.workflow_cost.workflow_spend_ceiling_usd
    ):
        raise RunManifestError("effective workflow spend broadens TaskSpec")
    if (
        requested.execution_limits.workflow_cost.chargeable_work == "forbidden"
        and effective.execution_limits.workflow_cost.chargeable_work != "forbidden"
    ):
        raise RunManifestError("effective chargeable-work policy broadens TaskSpec")
    if effective.data_policy.data_class < requested.data_policy.data_class:
        raise RunManifestError("effective data class weakens TaskSpec")
    if not set(effective.data_policy.processing_purposes) <= set(
        requested.data_policy.processing_purposes
    ):
        raise RunManifestError("effective processing purposes broaden TaskSpec")
    if effective.data_policy.retention_policy_ref != requested.data_policy.retention_policy_ref:
        raise RunManifestError("effective retention policy changes TaskSpec")


def resolve_admission(
    plan: AdmissionPlan,
    *,
    verified_at: Rfc3339Utc,
    approval_backend: ApprovalBackend,
    credential_probe: Callable[[], None] | None = None,
) -> AdmissionDecision:
    """Resolve authority before credential lookup or any execution side effect."""

    _validate_policy_narrowing(plan)
    task_cost = plan.task_policy.execution_limits.workflow_cost.workflow_spend_ceiling_usd
    approval_cost = (
        plan.episode_budget.workflow_cost_usd_max
        if plan.approval_id is not None
        else "0.000000"
    )
    ceilings = AdmissionCeilings(
        task_workflow_cost_usd=task_cost,
        platform_workflow_cost_usd=plan.platform_workflow_cost_usd,
        campaign_workflow_allocation_usd=plan.campaign_workflow_allocation_usd,
        provider_workflow_cost_usd=plan.provider_workflow_cost_usd,
        approval_workflow_allocation_usd=approval_cost,
    )
    resolved_cost = f"{min(Decimal(value) for value in ceilings.model_dump().values()):.6f}"
    chargeable = plan.provider_metered or any(
        Decimal(value) > 0
        for value in (
            plan.episode_budget.workflow_cost_usd_max,
            plan.episode_budget.judge_cost_usd_max,
            plan.episode_budget.paid_tool_cost_usd_max,
            plan.episode_budget.infrastructure_cost_usd_max,
        )
    )
    if chargeable and plan.task_policy.execution_limits.workflow_cost.chargeable_work == (
        "forbidden"
    ):
        # The gap W07 found and could not reach across. `_validate_policy_
        # narrowing` compares the *effective* policy against the task's, so
        # it catches a run that widens a forbidden boundary — but it never
        # asks whether a task that forbids chargeable work is being admitted
        # onto a chargeable plan at all. It was not: a spec compiled with
        # `chargeable_work="forbidden"` and a zero ceiling, running on a
        # metered provider, admitted the moment an approval id was present,
        # because the approval branch below reads only the *budget*. The
        # ceiling stayed zero and the decision still came back
        # `chargeable=True`, which is the fail-open shape of invariant 10:
        # an approval covering an amount is not authority over a task that
        # declares no chargeable work may happen for it.
        raise RunManifestError(
            "task policy forbids chargeable work; a metered provider or a "
            "positive budget cannot be admitted against it"
        )
    record: ApprovalRecord | None = None
    receipt: ApprovalVerificationReceipt | None = None
    if chargeable:
        if plan.approval_id is None:
            raise RunManifestError("chargeable plan requires explicit external approval")
        record, receipt = approval_backend.verify(
            plan.approval_id,
            campaign_id=plan.campaign_id,
            stage=plan.stage,
            provider=plan.provider,
            resources=plan.resources,
            required_total_usd=plan.episode_budget.total_cost_usd_max,
            required_episode_usd=plan.episode_budget.total_cost_usd_max,
            required_workflow_usd=plan.episode_budget.workflow_cost_usd_max,
            required_judge_usd=plan.episode_budget.judge_cost_usd_max,
            verified_at=verified_at,
        )
        if credential_probe is not None:
            credential_probe()
        approval = ApprovalSnapshot(
            required=True,
            status_at_seal=ApprovalStatus.APPROVED,
            approval_id=record.approval_id,
            record_ref=f"approval-record://{record.approval_id}",
            record_digest=record.record_digest,
            authoritative_source="external-approval-record",
            scope=record.scope,
            approved_by=record.approved_by,
            approved_at=record.approved_at,
            expires_at=record.expires_at,
            admission_verification_receipt_ref=ImmutableObjectRef(
                kind="approval_verification_receipt",
                id=f"verify-{record.approval_id.removeprefix('approval_')}",
                revision="1.0.0",
                digest=sha256_digest(receipt),
            ),
        )
    else:
        if plan.approval_id is not None:
            raise RunManifestError("no-cost plan cannot masquerade as approval-backed")
        approval = ApprovalSnapshot(
            required=False,
            status_at_seal=ApprovalStatus.NOT_REQUIRED,
            not_required_reason="mocked-local-stage-0",
            authoritative_source="local-no-cost",
        )
    effective = plan.effective_policy
    receipt_material = {
        "campaign_id": plan.campaign_id,
        "stage": plan.stage,
        "ceilings": ceilings,
        "resolved_cost": resolved_cost,
        "limits": effective.execution_limits,
        "tools": effective.tool_policy.allowed_agent_tools,
        "source_providers": effective.source_scope.allowed_providers,
    }
    receipt_digest = sha256_digest(receipt_material)
    resolution = AdmissionResolution(
        input_workflow_ceilings=ceilings,
        resolved_workflow_cost_usd=resolved_cost,
        resolved_limits=ResolvedLimits(
            hard_timeout_seconds=effective.execution_limits.hard_timeout_seconds,
            model_calls_max=effective.execution_limits.max_model_calls,
            tool_calls_max=effective.execution_limits.max_tool_calls,
            autonomy_tier_max=effective.autonomy.maximum_tier,
            allowed_agent_tools=effective.tool_policy.allowed_agent_tools,
            allowed_source_providers=effective.source_scope.allowed_providers,
        ),
        receipt_ref=ImmutableObjectRef(
            kind="admission_receipt",
            id=f"admission-{receipt_digest.removeprefix('sha256:')[:32]}",
            revision="1.0.0",
            digest=receipt_digest,
        ),
    )
    return AdmissionDecision(
        resolution=resolution,
        approval=approval,
        approval_receipt=receipt,
        chargeable=chargeable,
    )


class ManifestFileStore:
    """Create-once filesystem store with digest sidecar verification."""

    filename = "run-manifest.json"
    sidecar_filename = "run-manifest.sha256"

    def seal(
        self,
        directory: Path,
        manifest: RunManifestV1,
        *,
        before_publish: Callable[[], None] | None = None,
    ) -> tuple[Path, Path]:
        target = directory / self.filename
        sidecar = directory / self.sidecar_filename
        directory.mkdir(parents=True, exist_ok=True)
        if target.exists() or sidecar.exists():
            raise RunManifestError("refusing to overwrite a sealed manifest")
        encoded = canonical_json(manifest) + "\n"
        sidecar_text = f"{manifest.integrity.payload_sha256}  {self.filename}\n"
        manifest_tmp: Path | None = None
        sidecar_tmp: Path | None = None
        try:
            manifest_fd, manifest_name = tempfile.mkstemp(prefix=".run-manifest.", dir=directory)
            manifest_tmp = Path(manifest_name)
            with os.fdopen(manifest_fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            sidecar_fd, sidecar_name = tempfile.mkstemp(prefix=".run-manifest-sha.", dir=directory)
            sidecar_tmp = Path(sidecar_name)
            with os.fdopen(sidecar_fd, "w", encoding="utf-8") as handle:
                handle.write(sidecar_text)
                handle.flush()
                os.fsync(handle.fileno())
            if before_publish is not None:
                before_publish()
            os.link(manifest_tmp, target)
            try:
                os.link(sidecar_tmp, sidecar)
            except BaseException:
                # A lone manifest is deliberately untrusted by ``load``.
                raise
            return target, sidecar
        except FileExistsError as exc:
            raise RunManifestError("refusing to overwrite a sealed manifest") from exc
        finally:
            for path in (manifest_tmp, sidecar_tmp):
                if path is not None:
                    path.unlink(missing_ok=True)

    def load(self, directory: Path) -> RunManifestV1:
        target = directory / self.filename
        sidecar = directory / self.sidecar_filename
        if not target.is_file() or not sidecar.is_file():
            raise RunManifestError("manifest and digest sidecar must both exist")
        try:
            manifest = RunManifestV1.model_validate_json(
                target.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise RunManifestError("manifest envelope is invalid") from exc
        parts = sidecar.read_text(encoding="utf-8").strip().split()
        if parts != [manifest.integrity.payload_sha256, self.filename]:
            raise RunManifestError(
                "manifest digest sidecar mismatch",
                code=ContractErrorCode.DIGEST_INVALID,
            )
        return manifest


class CompletionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_STOPPED = "budget_stopped"


class RunReason(StrEnum):
    PROVIDER_ERROR = "provider_error"
    TOOL_ERROR = "tool_error"
    SCHEMA_ERROR = "schema_error"
    POLICY_ERROR = "policy_error"
    TIMEOUT = "timeout"
    OPERATOR_INTERRUPT = "operator_interrupt"
    INFRASTRUCTURE_LOST = "infrastructure_lost"
    EPISODE_BUDGET_EXHAUSTED = "episode_budget_exhausted"
    CAMPAIGN_BUDGET_EXHAUSTED = "campaign_budget_exhausted"
    APPROVAL_MISSING = "approval_missing"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_REVOKED = "approval_revoked"
    MANIFEST_MISMATCH = "manifest_mismatch"
    CHECKPOINT_INCOMPATIBLE = "checkpoint_incompatible"
    INTEGRITY_FAILURE = "integrity_failure"
    PRIVACY_OR_SECURITY_STOP = "privacy_or_security_stop"
    BENCHMARK_CONTAMINATION = "benchmark_contamination"
    NO_REPORT_PRODUCED = "no_report_produced"
    JUDGE_PARTIAL_FAILURE = "judge_partial_failure"
    UNKNOWN = "unknown"


class AttemptReceipt(StrictContractModel):
    schema_kind: Literal["attempt-receipt"] = "attempt-receipt"
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: RunId
    attempt_id: AttemptId
    manifest_digest: Digest
    started_at: Rfc3339Utc
    ended_at: Rfc3339Utc | None = None
    outcome: Literal["running", "interrupted", "failed"]
    reason: RunReason | None = None
    approval_verification_receipt_ref: ImmutableObjectRef | None = None
    accumulated_workflow_cost_usd: MoneyUsd
    accumulated_judge_cost_usd: MoneyUsd

    @model_validator(mode="after")
    def outcome_fields_match(self) -> AttemptReceipt:
        if self.outcome == "running" and (self.ended_at is not None or self.reason is not None):
            raise ValueError("running attempts cannot have terminal fields")
        if self.outcome != "running" and (self.ended_at is None or self.reason is None):
            raise ValueError("closed attempts require time and reason")
        return self


class CompletionReceipt(StrictContractModel):
    schema_kind: Literal["completion-receipt"] = "completion-receipt"
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: RunId
    manifest_digest: Digest
    status: CompletionStatus
    reason: RunReason | None = None
    completed_at: Rfc3339Utc
    final_artifact_refs: tuple[ImmutableObjectRef, ...] = ()
    accumulated_workflow_cost_usd: MoneyUsd
    accumulated_judge_cost_usd: MoneyUsd

    @model_validator(mode="after")
    def failure_has_reason(self) -> CompletionReceipt:
        if self.status is CompletionStatus.SUCCEEDED and self.reason is not None:
            raise ValueError("successful completion cannot have a failure reason")
        if self.status is not CompletionStatus.SUCCEEDED and self.reason is None:
            raise ValueError("non-success completion requires a reason")
        return self


class CheckpointCompatibility(StrictContractModel):
    run_id: RunId
    episode_key: Digest
    manifest_digest: Digest
    task_digest: Digest
    policy_digest: Digest
    config_digest: Digest
    prompt_digest: Digest
    model_digest: Digest
    tool_digest: Digest
    source_digest: Digest
    code_digest: Digest
    idempotent_boundary: bool
    reconciliation_action: SafeLabel | None = None

    @model_validator(mode="after")
    def ambiguous_side_effects_are_reconciled(self) -> CheckpointCompatibility:
        if not self.idempotent_boundary and self.reconciliation_action is None:
            raise ValueError("non-idempotent checkpoints require reconciliation")
        return self


def manifest_compatibility(manifest: RunManifestV1) -> CheckpointCompatibility:
    payload = manifest.payload
    return CheckpointCompatibility(
        run_id=payload.identity.run_id,
        episode_key=payload.identity.episode_key,
        manifest_digest=manifest.integrity.payload_sha256,
        task_digest=payload.task.full_digest,
        policy_digest=sha256_digest(payload.policy),
        config_digest=payload.runtime_config.effective_values_digest,
        prompt_digest=sha256_digest(payload.prompts),
        model_digest=sha256_digest(payload.providers.llm),
        tool_digest=sha256_digest(payload.tools),
        source_digest=sha256_digest(payload.sources),
        code_digest=sha256_digest(payload.code),
        idempotent_boundary=True,
    )


def validate_resume(
    manifest: RunManifestV1,
    checkpoint: CheckpointCompatibility,
    *,
    completion: CompletionReceipt | None,
    approval_receipt: ApprovalVerificationReceipt | None,
    accumulated_workflow_cost_usd: MoneyUsd,
    accumulated_judge_cost_usd: MoneyUsd,
    accumulated_campaign_cost_usd: MoneyUsd = "0.000000",
    stopped_for_integrity_or_privacy: bool = False,
) -> AttemptId:
    """Fail closed unless the interrupted run can safely append a new attempt."""

    if completion is not None:
        raise RunManifestError("terminal completion blocks resume")
    expected = manifest_compatibility(manifest)
    for name in (
        "run_id",
        "episode_key",
        "manifest_digest",
        "task_digest",
        "policy_digest",
        "config_digest",
        "prompt_digest",
        "model_digest",
        "tool_digest",
        "source_digest",
        "code_digest",
    ):
        if getattr(checkpoint, name) != getattr(expected, name):
            raise RunManifestError(f"checkpoint {name} is incompatible")
    if stopped_for_integrity_or_privacy:
        raise RunManifestError("privacy or integrity stop blocks resume")
    if manifest.payload.approval.required and (
        approval_receipt is None
        or approval_receipt.approval_id != manifest.payload.approval.approval_id
        or approval_receipt.campaign_id != manifest.payload.identity.campaign_id
        or approval_receipt.record_digest != manifest.payload.approval.record_digest
    ):
        raise RunManifestError("fresh matching approval receipt is required for resume")
    episode = manifest.payload.budgets.episode
    workflow_cap = Decimal(episode.workflow_cost_usd_max)
    judge_cap = Decimal(episode.judge_cost_usd_max)
    if workflow_cap > 0 and Decimal(accumulated_workflow_cost_usd) >= workflow_cap:
        raise RunManifestError("workflow budget has no resume headroom")
    if judge_cap > 0 and Decimal(accumulated_judge_cost_usd) >= judge_cap:
        raise RunManifestError("judge budget has no resume headroom")
    campaign_cap = Decimal(manifest.payload.budgets.campaign.total_cost_usd_max)
    if campaign_cap > 0 and Decimal(accumulated_campaign_cost_usd) >= campaign_cap:
        raise RunManifestError("campaign budget has no resume headroom")
    return new_attempt_id()


class LegacyImport(StrictContractModel):
    schema_kind: Literal["legacy-import"] = "legacy-import"
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_file_digest: Digest
    known_metadata: Mapping[str, str | int | bool | None]
    policy: Literal["unknown"] = "unknown"
    runtime_config: Literal["unknown"] = "unknown"
    model_routes: Literal["unknown"] = "unknown"
    prompts: Literal["unknown"] = "unknown"
    tools: Literal["unknown"] = "unknown"
    approval: Literal["unknown"] = "unknown"
    code: Literal["unknown"] = "unknown"
    environment: Literal["unknown"] = "unknown"
    provenance_completeness: Literal["partial"] = "partial"
    promotion_eligible: Literal[False] = False


def import_legacy_eval(
    record: Mapping[str, Any],
    *,
    source_bytes: bytes | None = None,
) -> LegacyImport:
    """Wrap allowlisted legacy facts without inventing missing provenance."""

    allowed = (
        "run_id",
        "query_id",
        "domain",
        "elapsed_seconds",
        "error",
        "workflow_cost_usd",
        "judge_cost_usd",
    )
    known: dict[str, str | int | bool | None] = {}
    for key in allowed:
        value = record.get(key)
        if value is None or isinstance(value, (str, int, bool)):
            known[key] = value
        elif isinstance(value, float) and math.isfinite(value):
            known[key] = f"{value:.6f}"
    validate_manifest_safe_content(known)
    if source_bytes is None:
        source_bytes = json.dumps(
            dict(record),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    source_digest = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    return LegacyImport(source_file_digest=source_digest, known_metadata=known)


def validate_arm_matrix(arms: Iterable[PolicySnapshot]) -> tuple[PolicySnapshot, ...]:
    materialized = tuple(arms)
    if tuple(arm.arm_id for arm in materialized) != ("A", "B", "C", "D", "E"):
        raise RunManifestError("arm matrix must contain A-E exactly once in order")
    digests = tuple(sha256_digest(arm) for arm in materialized)
    if len(set(digests)) != len(digests):
        raise RunManifestError("every arm snapshot must have a distinct digest")
    return materialized


def run_manifest_json_schema() -> dict[str, Any]:
    schema = RunManifestV1.model_json_schema(mode="validation")
    schema["$id"] = "https://arxiv-research-agent.dev/schemas/run-manifest/1.0.0"
    schema["title"] = "RunManifest v1"
    return schema


def run_artifact_json_schemas() -> dict[str, dict[str, Any]]:
    """Export every immutable manifest-adjacent artifact schema."""

    models: dict[str, type[StrictContractModel]] = {
        "run-manifest": RunManifestV1,
        "policy-runtime-projection": PolicyRuntimeProjection,
        "attempt-receipt": AttemptReceipt,
        "completion-receipt": CompletionReceipt,
        "legacy-import": LegacyImport,
    }
    return {
        name: model.model_json_schema(mode="validation")
        for name, model in models.items()
    }
