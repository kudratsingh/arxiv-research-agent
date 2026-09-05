"""Canonical append-only trajectory events and a no-cost in-memory adapter.

The adapter is an executable contract test bed, not production persistence.
It deliberately has no provider, network, runtime-settings, database, or user
content integration.  Producers propose bounded facts; the store owns order,
commit timestamps, idempotency, lineage checks, and the per-run hash chain.
"""

from __future__ import annotations

import hashlib
import re
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, TypeAlias

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
    StrictContractModel,
    canonical_json,
    canonical_json_bytes,
    sha256_digest,
)
from src.contracts.run_manifest import AttemptId, RunId
from src.contracts.task_spec import TaskSpecId
from src.errors import ERROR_CODES

EventId: TypeAlias = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
BranchId: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^branch_[a-z0-9][a-z0-9_-]{0,63}$")
]
CandidateId: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^cand_[a-z0-9][a-z0-9_-]{0,95}$")
]
ActionAttemptId: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^aatt_[a-z0-9][a-z0-9_-]{0,95}$")
]
EventTypeName: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
]
ReasonCode: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,95}$")
]
PolicyId: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")
]

MAX_EVENT_BYTES = 32 * 1024
HASH_DOMAIN = b"trajectory-event-v1\n"

_PRIVATE_PATH_RE = re.compile(r"(?:/Users/|/home/|/private/|[A-Za-z]:\\Users\\)")
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|token)\s*[:=]\s*\S+"),
)
_FORBIDDEN_KEYS = re.compile(
    r"(?i)(?:^|_)(?:api_?key|password|passwd|auth(?:orization)?|cookie|token|"
    r"private_?key|request_?headers?|environment_?dump|env_?dump|\.env|"
    r"chain_?of_?thought|scratchpad|hidden_?reasoning|hidden_?labels?|raw_?(?:prompt|"
    r"document|report|response|user_?text|learner_?text|stdout|stderr))(?:$|_)"
)
_CONTROL_CANARY = re.compile(r"(?i)(?:ignore previous instructions|system prompt:|developer message:)")


class TrajectoryError(ContractError):
    def __init__(
        self,
        detail: str,
        *,
        code: ContractErrorCode = ContractErrorCode.SCHEMA_INVALID,
    ) -> None:
        super().__init__(code, detail)


class IdempotencyConflict(TrajectoryError):
    pass


class IntegrityError(TrajectoryError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail, code=ContractErrorCode.DIGEST_INVALID)


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


def validate_event_safe_content(value: Any) -> None:
    """Reject sensitive bodies and instruction-shaped control canaries."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    for path, child in _walk(value):
        key = path.rsplit(".", 1)[-1]
        if "[" not in key and _FORBIDDEN_KEYS.search(key):
            raise TrajectoryError(f"forbidden trajectory field at {path}")
        if not isinstance(child, str):
            continue
        if len(child.encode("utf-8")) > 2048:
            raise TrajectoryError(f"unbounded inline string at {path}; use an artifact")
        if any(pattern.search(child) for pattern in _SECRET_PATTERNS):
            raise TrajectoryError(f"secret-shaped trajectory value at {path}")
        if _PRIVATE_PATH_RE.search(child):
            raise TrajectoryError(f"private absolute path at {path}")
        if _CONTROL_CANARY.search(child) and any(
            token in path
            for token in ("payload.tool_id", "payload.chosen_action", "payload.executor_kind")
        ):
            raise TrajectoryError(f"untrusted instruction entered a control field at {path}")


class EventStatus(StrEnum):
    REQUESTED = "requested"
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABSTAINED = "abstained"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    BUDGET_STOPPED = "budget_stopped"
    REJECTED = "rejected"


class ActorKind(StrEnum):
    SYSTEM = "system"
    POLICY = "policy"
    AGENT = "agent"
    TOOL = "tool"
    MODEL = "model"
    HUMAN = "human"


class ContentClass(StrEnum):
    NONE = "none"
    METADATA = "metadata"
    USER_INPUT_SUMMARY = "user_input_summary"
    SOURCE_SUMMARY = "source_summary"
    DERIVED_SUMMARY = "derived_summary"
    ARTIFACT_REFERENCE = "artifact_reference"
    SYNTHETIC = "synthetic"


class ConsentScope(StrEnum):
    PRODUCT_OPERATION_ONLY = "product_operation_only"
    SUPPORT_ONLY = "support_only"
    AGGREGATE_ANALYTICS = "aggregate_analytics"
    HUMAN_EVALUATION = "human_evaluation"
    EVALUATION_ONLY = "evaluation_only"
    PUBLIC_SOURCE_EVALUATION = "public_source_evaluation"
    SYNTHETIC_TEST = "synthetic_test"


class RedactionStatus(StrEnum):
    PASSED = "passed"
    NOT_APPLICABLE = "not_applicable"


class ReplayOrigin(StrEnum):
    LIVE = "live"
    FIXTURE = "fixture"
    OBSERVATIONAL_REPLAY = "observational_replay"
    DECISION_REPLAY = "decision_replay"
    SIMULATION = "simulation"


class ObservationStatus(StrEnum):
    OBSERVED = "observed"
    RECORDED = "recorded"
    HELD_CONSTANT_AFTER_DIVERGENCE = "held_constant_after_divergence"
    SIMULATED = "simulated"
    NOT_APPLICABLE = "not_applicable"


class TrustClass(StrEnum):
    SYSTEM_GENERATED = "system_generated"
    AUTHENTICATED_HUMAN = "authenticated_human"
    UNTRUSTED_USER = "untrusted_user"
    UNTRUSTED_SOURCE = "untrusted_source"
    TOOL_GENERATED = "tool_generated"
    EVALUATOR_GENERATED = "evaluator_generated"


class ArtifactRole(StrEnum):
    PLAN = "plan"
    TOOL_INPUT = "tool_input"
    TOOL_OUTPUT = "tool_output"
    SOURCE_DOCUMENT = "source_document"
    SOURCE_SPAN = "source_span"
    EVIDENCE_RECORD = "evidence_record"
    CLAIM_SET = "claim_set"
    CANDIDATE_OUTLINE = "candidate_outline"
    CANDIDATE_REPORT = "candidate_report"
    VERIFICATION_REPORT = "verification_report"
    REPAIR_PATCH = "repair_patch"
    CHECKPOINT_SNAPSHOT = "checkpoint_snapshot"
    HUMAN_INPUT = "human_input"
    FINAL_REPORT = "final_report"
    FAILURE_DETAIL = "failure_detail"
    RUNTIME_SCORE_RECORD = "runtime_score_record"
    ADMISSION_RECEIPT = "admission_receipt"
    APPROVAL_REVALIDATION_RECEIPT = "approval_revalidation_receipt"


class Actor(StrictContractModel):
    kind: ActorKind
    name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
    instance_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    version_ref: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class PolicyRef(StrictContractModel):
    policy_id: PolicyId
    policy_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    policy_digest: Digest


class TraceRef(StrictContractModel):
    trace_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16,64}$")]
    span_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]


class ArtifactRef(StrictContractModel):
    artifact_id: Annotated[
        str, StringConstraints(pattern=r"^artifact:sha256:[0-9a-f]{64}$")
    ]
    role: ArtifactRole
    digest: Digest
    media_type: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    byte_length: Annotated[int, Field(ge=0, le=1_000_000_000)]
    schema_ref: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    storage_uri: Annotated[
        str, StringConstraints(pattern=r"^cas://sha256/[0-9a-f]{64}$")
    ]
    trust_class: TrustClass
    data_class: DataClass
    retention_policy_ref: RetentionPolicyRef
    compression: Literal["none", "gzip", "zstd"] = "none"
    created_by_event_id: EventId | None = None
    source_artifact_ids: tuple[
        Annotated[str, StringConstraints(pattern=r"^artifact:sha256:[0-9a-f]{64}$")], ...
    ] = ()

    @model_validator(mode="after")
    def identity_matches_digest(self) -> ArtifactRef:
        suffix = self.digest.removeprefix("sha256:")
        if self.artifact_id != f"artifact:{self.digest}":
            raise ValueError("artifact id must contain its digest")
        if self.storage_uri != f"cas://sha256/{suffix}":
            raise ValueError("artifact storage URI must contain its digest")
        if len(self.source_artifact_ids) != len(set(self.source_artifact_ids)):
            raise ValueError("source artifact ids must be unique")
        return self


class UsageDelta(StrictContractModel):
    provider: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
    model_id: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    input_tokens: Annotated[int, Field(ge=0)] = 0
    output_tokens: Annotated[int, Field(ge=0)] = 0
    cache_read_input_tokens: Annotated[int, Field(ge=0)] = 0
    cache_creation_input_tokens: Annotated[int, Field(ge=0)] = 0
    llm_calls: Annotated[int, Field(ge=0)] = 0
    tool_calls: Annotated[int, Field(ge=0)] = 0
    retries: Annotated[int, Field(ge=0)] = 0
    estimated_cost_usd: MoneyUsd = "0.000000"
    price_table_ref: ImmutableObjectRef | None = None
    cost_scope: Literal["product"] = "product"
    meter_deltas: Mapping[
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")],
        Annotated[int, Field(ge=0)],
    ] = {}

    @model_validator(mode="after")
    def priced_usage_has_table(self) -> UsageDelta:
        if Decimal(self.estimated_cost_usd) > 0 and self.price_table_ref is None:
            raise ValueError("non-zero cost requires an immutable price table ref")
        if not any(
            (
                self.input_tokens,
                self.output_tokens,
                self.cache_read_input_tokens,
                self.cache_creation_input_tokens,
                self.llm_calls,
                self.tool_calls,
                self.retries,
                Decimal(self.estimated_cost_usd),
                *self.meter_deltas.values(),
            )
        ):
            raise ValueError("usage delta must contain completed work")
        return self


class DataGovernance(StrictContractModel):
    content_class: ContentClass
    effective_data_class: DataClass
    consent_scope: ConsentScope
    redaction_status: RedactionStatus
    contains_user_content: bool
    training_eligible: Literal[False] = False


class ReplayMetadata(StrictContractModel):
    origin: ReplayOrigin
    source_run_id: RunId | None = None
    observation_status: ObservationStatus
    diverged_at_event_id: EventId | None = None
    counterfactual_depth: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def replay_labels_are_honest(self) -> ReplayMetadata:
        counterfactual = self.observation_status in {
            ObservationStatus.HELD_CONSTANT_AFTER_DIVERGENCE,
            ObservationStatus.SIMULATED,
        }
        if counterfactual and (
            self.origin not in {ReplayOrigin.DECISION_REPLAY, ReplayOrigin.SIMULATION}
            or self.source_run_id is None
            or self.diverged_at_event_id is None
            or self.counterfactual_depth < 1
        ):
            raise ValueError("counterfactual observations require source and divergence lineage")
        if self.origin is ReplayOrigin.LIVE and self.observation_status not in {
            ObservationStatus.OBSERVED,
            ObservationStatus.NOT_APPLICABLE,
        }:
            raise ValueError("live events cannot claim replayed observations")
        if self.origin is ReplayOrigin.FIXTURE and self.observation_status not in {
            ObservationStatus.RECORDED,
            ObservationStatus.NOT_APPLICABLE,
        }:
            raise ValueError("fixture events must be recorded or not applicable")
        return self


_TRAJECTORY_OUTCOME_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "historical_import",
        "incomplete_source_surface",
        "insufficient_source_span",
        "verification_abstained",
        "user_requested",
        "settled_after_cancel",
        "operator_interrupt",
        "infrastructure_lost",
        "episode_budget_exhausted",
        "campaign_budget_exhausted",
        "approval_missing",
        "approval_expired",
        "approval_revoked",
        "manifest_mismatch",
        "checkpoint_incompatible",
        "integrity_failure",
        "privacy_or_security_stop",
        "benchmark_contamination",
        "no_report_produced",
        "judge_partial_failure",
        "completed",
        "failed",
        "cancelled",
        "budget_exhausted",
        "marginal_gain_below_threshold",
        "unknown",
    }
)

# Runtime failures use ADR 0064's canonical AppError registry.  This contract
# adds only trajectory outcomes that are not errors; it deliberately does not
# create a second error-code vocabulary.
REGISTERED_REASON_CODES: Final[frozenset[str]] = (
    ERROR_CODES | _TRAJECTORY_OUTCOME_REASON_CODES
)


class EventTypeDefinition(StrictContractModel):
    event_type: EventTypeName
    event_type_version: Literal["1.0.0"] = "1.0.0"
    owner: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    allowed_statuses: tuple[EventStatus, ...]
    required_payload_fields: tuple[
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")], ...
    ]
    optional_payload_fields: tuple[
        Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")], ...
    ] = ()
    allowed_artifact_roles: tuple[ArtifactRole, ...] = ()
    requires_attempt: bool = True
    requires_candidate: bool = False
    requires_action_attempt: bool = False
    allowed_after_terminal: bool = False

    @model_validator(mode="after")
    def definition_is_closed(self) -> EventTypeDefinition:
        if not self.allowed_statuses:
            raise ValueError("event type needs a legal status")
        if len(set(self.allowed_statuses)) != len(self.allowed_statuses):
            raise ValueError("event statuses must be unique")
        if set(self.required_payload_fields) & set(self.optional_payload_fields):
            raise ValueError("payload fields cannot be required and optional")
        for values in (
            self.required_payload_fields,
            self.optional_payload_fields,
            self.allowed_artifact_roles,
        ):
            if len(values) != len(set(values)):
                raise ValueError("event definition fields and roles must be unique")
        return self


def _definition(
    event_type: str,
    status: EventStatus | tuple[EventStatus, ...],
    required: Sequence[str],
    *,
    optional: Sequence[str] = (),
    roles: Sequence[ArtifactRole] = (),
    attempt: bool = True,
    candidate: bool = False,
    action_attempt: bool = False,
    post_terminal: bool = False,
) -> EventTypeDefinition:
    statuses = status if isinstance(status, tuple) else (status,)
    return EventTypeDefinition(
        event_type=event_type,
        owner="agent-platform",
        allowed_statuses=statuses,
        required_payload_fields=tuple(required),
        optional_payload_fields=tuple(optional),
        allowed_artifact_roles=tuple(roles),
        requires_attempt=attempt,
        requires_candidate=candidate,
        requires_action_attempt=action_attempt,
        allowed_after_terminal=post_terminal,
    )


def _build_event_registry() -> tuple[EventTypeDefinition, ...]:
    requested = EventStatus.REQUESTED
    started = EventStatus.STARTED
    succeeded = EventStatus.SUCCEEDED
    failed = EventStatus.FAILED
    return (
        _definition("run.admitted", succeeded, ("admission_receipt_ref", "admission_receipt_digest", "environment_class", "product_lane"), roles=(ArtifactRole.ADMISSION_RECEIPT,), attempt=False),
        _definition("approval.revalidated", (succeeded, failed), ("proposed_attempt_id", "receipt_ref", "receipt_digest", "result", "reason_codes"), roles=(ArtifactRole.APPROVAL_REVALIDATION_RECEIPT,), attempt=False),
        _definition("attempt.started", started, ("entrypoint", "main_branch_id", "effective_budget_ref", "resume_checkpoint_id")),
        _definition("attempt.completed", succeeded, ("attempt_id", "last_committed_event_id")),
        _definition("attempt.interrupted", EventStatus.INTERRUPTED, ("attempt_id", "interruption_class", "last_checkpoint_id", "side_effect_reconciliation_required")),
        _definition("attempt.failed", failed, ("attempt_id", "failure_class", "last_checkpoint_id", "safe_resume_possible")),
        _definition("policy.decision", succeeded, ("decision_kind", "eligible_actions", "chosen_action", "reason_codes", "feature_snapshot_ref")),
        _definition("run.completed", succeeded, ("final_candidate_id", "final_artifact_id", "stop_reason_code"), candidate=True, roles=(ArtifactRole.FINAL_REPORT,)),
        _definition("run.failed", failed, ("failure_class", "failure_stage", "last_good_artifact_id"), optional=("diagnostic_ref",), roles=(ArtifactRole.FAILURE_DETAIL,)),
        _definition("run.cancel_requested", requested, ("requested_by_kind", "reason_code")),
        _definition("run.cancelled", EventStatus.CANCELLED, ("acknowledged_at_stage", "last_good_artifact_id", "in_flight_action_attempt_ids"), optional=("cost_reconciliation_pending",)),
        _definition("run.budget_stopped", EventStatus.BUDGET_STOPPED, ("budget_id", "last_good_artifact_id", "partial_candidate_id", "stop_reason_code"), optional=("partial",)),
        _definition("plan.created", succeeded, ("plan_artifact_id", "objective_count", "action_count", "plan_kind"), roles=(ArtifactRole.PLAN,)),
        _definition("plan.revised", succeeded, ("plan_artifact_id", "parent_plan_artifact_id", "change_scope", "reason_codes"), roles=(ArtifactRole.PLAN,)),
        _definition("plan.approved", succeeded, ("plan_artifact_id", "approval_source", "constraints_changed"), roles=(ArtifactRole.PLAN,)),
        _definition("action.requested", requested, ("action_id", "action_kind", "bounded_input_summary", "allowed_tool_ids"), roles=(ArtifactRole.TOOL_INPUT,)),
        _definition("action.started", started, ("action_id", "executor_kind"), action_attempt=True),
        _definition("action.completed", succeeded, ("action_id", "observation_event_ids", "output_artifact_ids"), action_attempt=True, roles=(ArtifactRole.TOOL_OUTPUT,)),
        _definition("action.failed", failed, ("action_id", "error_class", "retryable", "attempt_number"), action_attempt=True, roles=(ArtifactRole.FAILURE_DETAIL,)),
        _definition("action.skipped", EventStatus.SKIPPED, ("action_id", "reason_code")),
        _definition("observation.recorded", succeeded, ("observation_kind", "source_kind", "completeness", "freshness_at"), roles=(ArtifactRole.TOOL_OUTPUT, ArtifactRole.SOURCE_DOCUMENT, ArtifactRole.SOURCE_SPAN)),
        _definition("tool.requested", requested, ("tool_call_id", "tool_id", "tool_version", "argument_schema_ref", "side_effect_class", "network_scope"), roles=(ArtifactRole.TOOL_INPUT,)),
        _definition("tool.started", started, ("tool_call_id", "sandbox_ref"), action_attempt=True),
        _definition("tool.completed", succeeded, ("tool_call_id", "result_kind", "result_count", "exit_status", "cache_status"), roles=(ArtifactRole.TOOL_OUTPUT,), action_attempt=True),
        _definition("tool.failed", failed, ("tool_call_id", "error_class", "retryable", "provider_status_class"), roles=(ArtifactRole.FAILURE_DETAIL,), action_attempt=True),
        _definition("source.discovered", succeeded, ("source_id", "source_kind", "canonical_locator_hash", "published_at", "accessed_at"), roles=(ArtifactRole.SOURCE_DOCUMENT,)),
        _definition("source.accepted", succeeded, ("source_id", "admissibility_codes", "quality_signals")),
        _definition("source.rejected", EventStatus.REJECTED, ("source_id", "rejection_codes")),
        _definition("evidence.extracted", succeeded, ("evidence_id", "source_id", "source_span_artifact_id", "extraction_method", "supports_task_item_ids"), roles=(ArtifactRole.SOURCE_SPAN, ArtifactRole.EVIDENCE_RECORD)),
        _definition("claim.created", succeeded, ("claim_id", "claim_artifact_id", "candidate_id", "claim_kind", "report_location_ref"), roles=(ArtifactRole.CLAIM_SET,), candidate=True),
        _definition("claim.evidence_linked", succeeded, ("claim_id", "evidence_id", "relationship", "link_method")),
        _definition("claim.evidence_unlinked", succeeded, ("claim_id", "prior_evidence_id", "reason_code", "replacement_link_event_id")),
        _definition("evidence.coverage_assessed", succeeded, ("task_item_ids", "covered_item_ids", "missing_item_ids", "coverage_method"), roles=(ArtifactRole.EVIDENCE_RECORD,)),
        _definition("verification.requested", requested, ("check_id", "check_kind", "subject_ref", "verifier_ref", "acceptance_rule_ref"), candidate=True, action_attempt=True),
        _definition("verification.completed", (succeeded, failed, EventStatus.ABSTAINED), ("check_id", "verdict", "confidence", "failure_codes", "suggested_repair_kind"), optional=("claim_outcomes",), candidate=True, action_attempt=True, roles=(ArtifactRole.VERIFICATION_REPORT,)),
        _definition("verification.malformed", failed, ("check_id", "error_class", "fallback_action"), candidate=True, action_attempt=True, roles=(ArtifactRole.FAILURE_DETAIL,)),
        _definition("repair.requested", requested, ("repair_id", "repair_kind", "subject_candidate_id", "target_refs", "repair_budget_ref"), candidate=True),
        _definition("repair.completed", succeeded, ("repair_id", "result_candidate_id", "changed_scope", "verification_required"), candidate=True, roles=(ArtifactRole.REPAIR_PATCH, ArtifactRole.CANDIDATE_REPORT)),
        _definition("repair.failed", failed, ("repair_id", "error_class", "candidate_unchanged"), candidate=True, roles=(ArtifactRole.FAILURE_DETAIL,)),
        _definition("repair.exhausted", failed, ("subject_candidate_id", "attempted_repair_ids", "stop_reason_code"), candidate=True),
        _definition("compute.tier_selected", succeeded, ("tier", "eligible_tiers", "feature_snapshot_ref", "tier_budget_ref", "reason_codes")),
        _definition("branch.created", succeeded, ("new_branch_id", "parent_branch_id", "fork_event_id", "diversity_dimension")),
        _definition("branch.completed", succeeded, ("branch_id", "candidate_ids", "stop_reason_code")),
        _definition("branch.failed", failed, ("branch_id", "failure_class", "last_good_candidate_id")),
        _definition("branch.cancelled", EventStatus.CANCELLED, ("branch_id", "reason_code")),
        _definition("candidate.created", succeeded, ("candidate_id", "candidate_kind", "artifact_id", "generation_method"), candidate=True, roles=(ArtifactRole.CANDIDATE_OUTLINE, ArtifactRole.CANDIDATE_REPORT)),
        _definition("candidate.revised", succeeded, ("candidate_id", "parent_candidate_id", "artifact_id", "change_scope"), candidate=True, roles=(ArtifactRole.CANDIDATE_OUTLINE, ArtifactRole.CANDIDATE_REPORT)),
        _definition("candidate.scored", succeeded, ("candidate_id", "score_artifact_id", "runtime_scorer_ref", "score_scope"), candidate=True, roles=(ArtifactRole.RUNTIME_SCORE_RECORD,)),
        _definition("candidate.selected", succeeded, ("eligible_candidate_ids", "selected_candidate_id", "selector_kind", "selection_artifact_id"), candidate=True, roles=(ArtifactRole.RUNTIME_SCORE_RECORD,)),
        _definition("compute.stop_decided", succeeded, ("considered_action", "expected_gain_method", "marginal_gain", "incremental_cost_estimate", "reason_code")),
        _definition("budget.established", succeeded, ("budget_id", "currency", "episode_cap", "campaign_cap_ref", "limit_dimensions")),
        _definition("budget.reserved", succeeded, ("reservation_id", "action_id", "maximum_cost", "expires_at")),
        _definition("budget.reservation_released", succeeded, ("reservation_id", "actual_cost", "release_reason")),
        _definition("budget.usage_recorded", succeeded, ("reservation_id", "usage_event_ids", "cost_delta"), post_terminal=True),
        _definition("budget.threshold_reached", succeeded, ("threshold", "spent", "reserved", "remaining")),
        _definition("budget.exhausted", failed, ("spent", "reserved", "attempt_blocked", "partial_candidate_id")),
        _definition("budget.reconciled", (succeeded, failed), ("summed_event_cost", "run_cost_snapshot", "difference", "result"), post_terminal=True),
        _definition("checkpoint.saved", succeeded, ("checkpoint_id", "checkpoint_artifact_id", "graph_position", "resumable", "state_schema_ref"), roles=(ArtifactRole.CHECKPOINT_SNAPSHOT,)),
        _definition("checkpoint.resumed", succeeded, ("checkpoint_id", "resume_reason", "resuming_worker_id")),
        _definition("checkpoint.invalid", EventStatus.REJECTED, ("checkpoint_id", "failure_codes", "fallback")),
        _definition("hitl.requested", requested, ("request_id", "request_kind", "subject_ref", "allowed_responses", "deadline_at")),
        _definition("hitl.responded", succeeded, ("request_id", "response_kind", "response_artifact_id", "responder_principal_ref"), roles=(ArtifactRole.HUMAN_INPUT,)),
        _definition("hitl.timed_out", EventStatus.TIMED_OUT, ("request_id", "timeout_policy")),
        _definition("hitl.cancelled", EventStatus.CANCELLED, ("request_id", "reason_code")),
        _definition("final.candidate_selected", succeeded, ("candidate_id", "selection_basis", "verification_event_ids", "unresolved_issue_codes"), candidate=True),
        _definition("final.artifact_produced", succeeded, ("candidate_id", "artifact_id", "deliverable_kind", "partial"), candidate=True, roles=(ArtifactRole.FINAL_REPORT,)),
        _definition("failure.recorded", failed, ("failure_id", "failure_class", "stage", "retryable", "safe_message"), roles=(ArtifactRole.FAILURE_DETAIL,), post_terminal=True),
    )


EVENT_TYPE_DEFINITIONS = _build_event_registry()
EVENT_TYPE_REGISTRY = {definition.event_type: definition for definition in EVENT_TYPE_DEFINITIONS}
EVENT_REGISTRY_DIGEST = sha256_digest(EVENT_TYPE_DEFINITIONS)


class ProposedTrajectoryEvent(StrictContractModel):
    schema_kind: Literal["trajectory-event"] = "trajectory-event"
    schema_version: Literal["1.0.0"] = "1.0.0"
    event_type: EventTypeName
    event_type_version: Literal["1.0.0"] = "1.0.0"
    event_id: EventId
    idempotency_key: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    run_id: RunId
    attempt_id: AttemptId | None = None
    task_spec_id: TaskSpecId
    task_revision: Annotated[int, Field(ge=1)]
    task_spec_full_digest: Digest
    manifest_digest: Digest
    principal_key_id: Annotated[
        str, StringConstraints(pattern=r"^(?:pk_[a-z0-9]{8,64}|synthetic:[a-z0-9][a-z0-9_.:-]{0,127})$")
    ]
    occurred_at: Rfc3339Utc
    duration_ms: Annotated[int | None, Field(ge=0)] = None
    actor: Actor
    policy_ref: PolicyRef
    parent_event_id: EventId | None = None
    caused_by_event_id: EventId | None = None
    trace_ref: TraceRef | None = None
    branch_id: BranchId = "branch_main"
    candidate_id: CandidateId | None = None
    action_attempt_id: ActionAttemptId | None = None
    status: EventStatus
    reason_codes: Annotated[tuple[ReasonCode, ...], Field(max_length=32)] = ()
    payload: Mapping[str, Any]
    artifact_refs: Annotated[tuple[ArtifactRef, ...], Field(max_length=64)] = ()
    usage_delta: UsageDelta | None = None
    data_governance: DataGovernance
    replay: ReplayMetadata

    @model_validator(mode="after")
    def validate_registered_event(self) -> ProposedTrajectoryEvent:
        try:
            definition = EVENT_TYPE_REGISTRY[self.event_type]
        except KeyError as exc:
            raise ValueError(f"unregistered event type {self.event_type}") from exc
        if self.status not in definition.allowed_statuses:
            raise ValueError(f"status {self.status.value} is illegal for {self.event_type}")
        if definition.requires_attempt != (self.attempt_id is not None):
            expectation = "requires" if definition.requires_attempt else "forbids"
            raise ValueError(f"{self.event_type} {expectation} attempt_id")
        if definition.requires_candidate and self.candidate_id is None:
            raise ValueError(f"{self.event_type} requires candidate_id")
        if definition.requires_action_attempt and self.action_attempt_id is None:
            raise ValueError(f"{self.event_type} requires action_attempt_id")
        keys = set(self.payload)
        required = set(definition.required_payload_fields)
        allowed = required | set(definition.optional_payload_fields)
        if not required <= keys:
            raise ValueError(f"{self.event_type} payload is missing {sorted(required - keys)}")
        if not keys <= allowed:
            raise ValueError(f"{self.event_type} payload has unknown fields {sorted(keys - allowed)}")
        roles = {artifact.role for artifact in self.artifact_refs}
        if not roles <= set(definition.allowed_artifact_roles):
            raise ValueError(f"{self.event_type} carries a disallowed artifact role")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("reason codes must be unique")
        unknown_reasons = set(self.reason_codes) - REGISTERED_REASON_CODES
        if unknown_reasons:
            raise ValueError(f"unregistered reason codes: {sorted(unknown_reasons)}")
        if len(self.idempotency_key.encode("utf-8")) > 256:
            raise ValueError("idempotency key exceeds 256 UTF-8 bytes")
        if self.event_type == "compute.tier_selected" and self.payload.get("tier") == "T3":
            raise ValueError("T3 is reserved and forbidden in trajectory v1")
        if self.event_type == "verification.completed" and self.payload.get("verdict") not in {
            "pass",
            "fail",
            "abstain",
        }:
            raise ValueError("verification verdict must be pass, fail, or abstain")
        if self.event_type == "verification.completed":
            expected_status = {
                "pass": EventStatus.SUCCEEDED,
                "fail": EventStatus.FAILED,
                "abstain": EventStatus.ABSTAINED,
            }[str(self.payload["verdict"])]
            if self.status is not expected_status:
                raise ValueError("verification verdict and event status disagree")
            claim_outcomes = self.payload.get("claim_outcomes")
            if claim_outcomes is not None:
                if not isinstance(claim_outcomes, Mapping):
                    raise ValueError("claim outcomes must be a mapping")
                for claim_id, grounded in claim_outcomes.items():
                    if not isinstance(claim_id, str) or re.fullmatch(
                        r"(?:citation|quote):[0-9a-f]{16}", claim_id
                    ) is None:
                        raise ValueError("claim outcomes require groundedness claim ids")
                    if type(grounded) is not bool:
                        raise ValueError("claim outcomes must contain binary verdicts")
        for failure_field in ("error_class", "failure_class"):
            failure_code = self.payload.get(failure_field)
            if failure_code is not None and failure_code not in ERROR_CODES:
                raise ValueError(
                    f"{failure_field} must use the canonical AppError code registry"
                )
        validate_event_safe_content(self.model_dump(mode="json"))
        if len(canonical_json_bytes(self)) > MAX_EVENT_BYTES:
            raise ValueError("trajectory event exceeds the 32 KiB inline limit")
        return self


class StoredTrajectoryEvent(ProposedTrajectoryEvent):
    run_seq: Annotated[int, Field(ge=1)]
    recorded_at: Rfc3339Utc
    prev_event_hash: Digest | None
    event_hash: Digest


class RunScope(StrictContractModel):
    run_id: RunId
    task_spec_id: TaskSpecId
    task_revision: Annotated[int, Field(ge=1)]
    task_spec_full_digest: Digest
    manifest_digest: Digest
    principal_key_id: str
    policy_ref: PolicyRef
    task_data_class: DataClass
    retention_policy_ref: RetentionPolicyRef
    experiment_arm: Literal["A", "B", "C", "D", "E"] | None = None


def new_event_id(*, entropy: uuid.UUID | None = None) -> str:
    source = entropy or uuid.uuid4()
    return str(source)


def proposed_semantic_digest(event: ProposedTrajectoryEvent) -> str:
    return sha256_digest(event.model_dump(mode="json", exclude={"event_id"}))


def compute_event_hash(
    event_without_hashes: Mapping[str, Any],
    previous_event_hash: Digest | None,
) -> str:
    previous = (
        bytes.fromhex(previous_event_hash.removeprefix("sha256:"))
        if previous_event_hash is not None
        else b""
    )
    digest = hashlib.sha256(
        HASH_DOMAIN + previous + canonical_json_bytes(event_without_hashes)
    ).hexdigest()
    return f"sha256:{digest}"


def _event_body_for_hash(event: StoredTrajectoryEvent) -> dict[str, Any]:
    return event.model_dump(
        mode="json", exclude={"prev_event_hash", "event_hash"}
    )


class _RunLedger:
    def __init__(self, scope: RunScope) -> None:
        self.scope = scope
        self.events: list[StoredTrajectoryEvent] = []
        self.idempotency: dict[str, tuple[str, StoredTrajectoryEvent]] = {}
        self.by_id: dict[str, StoredTrajectoryEvent] = {}
        self.active_attempt_id: str | None = None
        self.branches: set[str] = {"branch_main"}
        self.closed_branches: set[str] = set()
        self.candidate_parents: dict[str, str | None] = {}
        self.action_attempts: set[str] = set()
        self.closed_action_attempts: set[str] = set()
        self.tool_attempts: set[str] = set()
        self.closed_tool_attempts: set[str] = set()
        self.verification_checks: dict[str, tuple[str, str]] = {}
        self.closed_verification_checks: set[str] = set()
        self.repair_requests: dict[str, str] = {}
        self.closed_repairs: set[str] = set()
        self.terminal_event_id: str | None = None


class InMemoryTrajectoryStore:
    """Thread-safe reference adapter for ordering and validation semantics."""

    def __init__(self, *, clock: Callable[[], Rfc3339Utc]) -> None:
        self._clock = clock
        self._runs: dict[str, _RunLedger] = {}
        self._global_event_ids: dict[str, tuple[str, str]] = {}
        self._lock = threading.RLock()

    def register_run(self, scope: RunScope) -> None:
        with self._lock:
            existing = self._runs.get(scope.run_id)
            if existing is not None:
                if existing.scope != scope:
                    raise TrajectoryError("run id is already bound to a different immutable scope")
                return
            self._runs[scope.run_id] = _RunLedger(scope)

    def append(self, event: ProposedTrajectoryEvent) -> StoredTrajectoryEvent:
        with self._lock:
            return self._append_locked(event)

    def append_batch(
        self,
        events: Sequence[ProposedTrajectoryEvent],
    ) -> tuple[StoredTrajectoryEvent, ...]:
        if not events:
            return ()
        run_ids = {event.run_id for event in events}
        if len(run_ids) != 1:
            raise TrajectoryError("an append batch must contain exactly one run")
        with self._lock:
            run_id = events[0].run_id
            ledger_before = deepcopy(self._require_run(run_id))
            global_before = dict(self._global_event_ids)
            try:
                return tuple(self._append_locked(event) for event in events)
            except BaseException:
                self._runs[run_id] = ledger_before
                self._global_event_ids = global_before
                raise

    def _require_run(self, run_id: str) -> _RunLedger:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise TrajectoryError("run must be registered before append") from exc

    def _append_locked(self, event: ProposedTrajectoryEvent) -> StoredTrajectoryEvent:
        ledger = self._require_run(event.run_id)
        self._validate_scope(ledger.scope, event)
        semantic_digest = proposed_semantic_digest(event)
        previous_idempotent = ledger.idempotency.get(event.idempotency_key)
        if previous_idempotent is not None:
            previous_digest, stored = previous_idempotent
            if previous_digest != semantic_digest:
                raise IdempotencyConflict("same idempotency key has different semantic content")
            return stored
        event_identity = self._global_event_ids.get(event.event_id)
        if event_identity is not None:
            raise IdempotencyConflict("event id was already used by another producer intent")

        definition = EVENT_TYPE_REGISTRY[event.event_type]
        if ledger.terminal_event_id is not None and not definition.allowed_after_terminal:
            raise TrajectoryError("terminal run rejects new policy or lifecycle events")
        if not ledger.events and event.event_type != "run.admitted":
            raise TrajectoryError("run.admitted must be the first event")
        if ledger.events and event.event_type == "run.admitted":
            raise TrajectoryError("run.admitted may be appended only once")
        self._validate_attempt(ledger, event)
        self._validate_references(ledger, event)
        self._validate_governance(ledger.scope, event)
        self._validate_branch_and_candidate(ledger, event)
        self._validate_action_attempt(ledger, event)
        self._validate_verification_and_repair(ledger, event)

        run_seq = (ledger.events[-1].run_seq + 1) if ledger.events else 1
        previous_hash = ledger.events[-1].event_hash if ledger.events else None
        body = {
            **event.model_dump(mode="json"),
            "run_seq": run_seq,
            "recorded_at": self._clock(),
        }
        event_hash = compute_event_hash(body, previous_hash)
        stored = StoredTrajectoryEvent(
            **event.model_dump(mode="python"),
            run_seq=run_seq,
            recorded_at=body["recorded_at"],
            prev_event_hash=previous_hash,
            event_hash=event_hash,
        )
        ledger.events.append(stored)
        ledger.idempotency[event.idempotency_key] = (semantic_digest, stored)
        ledger.by_id[event.event_id] = stored
        self._global_event_ids[event.event_id] = (event.run_id, event.idempotency_key)
        self._apply_state(ledger, stored)
        return stored

    @staticmethod
    def _validate_scope(scope: RunScope, event: ProposedTrajectoryEvent) -> None:
        expected = {
            "run_id": scope.run_id,
            "task_spec_id": scope.task_spec_id,
            "task_revision": scope.task_revision,
            "task_spec_full_digest": scope.task_spec_full_digest,
            "manifest_digest": scope.manifest_digest,
            "principal_key_id": scope.principal_key_id,
            "policy_ref": scope.policy_ref,
        }
        for field, value in expected.items():
            if getattr(event, field) != value:
                raise TrajectoryError(f"event {field} does not match immutable run scope")

    @staticmethod
    def _validate_attempt(ledger: _RunLedger, event: ProposedTrajectoryEvent) -> None:
        if event.event_type == "attempt.started":
            if ledger.active_attempt_id is not None:
                raise TrajectoryError("a process attempt is already active")
            return
        if event.attempt_id is not None and ledger.active_attempt_id != event.attempt_id:
            raise TrajectoryError("event attempt_id does not match the active process lease")

    @staticmethod
    def _validate_references(ledger: _RunLedger, event: ProposedTrajectoryEvent) -> None:
        for field in ("parent_event_id", "caused_by_event_id"):
            reference = getattr(event, field)
            if reference is not None and reference not in ledger.by_id:
                raise TrajectoryError(f"{field} must target an earlier event in the same run")
        single_payload_refs = {
            "attempt.completed": ("last_committed_event_id",),
            "branch.created": ("fork_event_id",),
            "claim.evidence_unlinked": ("replacement_link_event_id",),
        }
        repeated_payload_refs = {
            "action.completed": ("observation_event_ids",),
            "budget.usage_recorded": ("usage_event_ids",),
            "final.candidate_selected": ("verification_event_ids",),
        }
        for field in single_payload_refs.get(event.event_type, ()):
            reference = event.payload[field]
            if reference is not None and reference not in ledger.by_id:
                raise TrajectoryError(f"payload {field} must target an earlier run event")
        for field in repeated_payload_refs.get(event.event_type, ()):
            references = event.payload[field]
            if not isinstance(references, list | tuple) or any(
                reference not in ledger.by_id for reference in references
            ):
                raise TrajectoryError(f"payload {field} must contain earlier run events")

    @staticmethod
    def _validate_governance(scope: RunScope, event: ProposedTrajectoryEvent) -> None:
        inherited = DataClass.most_restrictive(
            scope.task_data_class,
            *(artifact.data_class for artifact in event.artifact_refs),
        )
        if event.data_governance.effective_data_class < inherited:
            raise TrajectoryError("event data classification downgrades inherited content")
        for artifact in event.artifact_refs:
            if artifact.retention_policy_ref != scope.retention_policy_ref:
                raise TrajectoryError("artifact retention policy differs from run scope")

    @staticmethod
    def _validate_branch_and_candidate(
        ledger: _RunLedger,
        event: ProposedTrajectoryEvent,
    ) -> None:
        if event.event_type == "branch.created":
            new_branch = event.payload["new_branch_id"]
            parent_branch = event.payload["parent_branch_id"]
            if not isinstance(new_branch, str) or new_branch in ledger.branches:
                raise TrajectoryError("branch.created requires a new unique branch id")
            if parent_branch not in ledger.branches or parent_branch in ledger.closed_branches:
                raise TrajectoryError("branch parent must be an open branch")
            if event.branch_id != parent_branch:
                raise TrajectoryError("branch.created must be emitted on its parent branch")
        elif event.branch_id not in ledger.branches:
            raise TrajectoryError("event branch_id has not been created")
        if event.branch_id in ledger.closed_branches:
            raise TrajectoryError("closed branch rejects new work")
        if (
            event.event_type in {"branch.completed", "branch.failed", "branch.cancelled"}
            and event.payload["branch_id"] != event.branch_id
        ):
            raise TrajectoryError("branch lifecycle payload must match envelope branch_id")

        if event.event_type == "candidate.created":
            if event.candidate_id in ledger.candidate_parents:
                raise TrajectoryError("candidate id already exists")
            if event.payload["candidate_id"] != event.candidate_id:
                raise TrajectoryError("candidate payload must match envelope candidate_id")
        elif event.event_type == "candidate.revised":
            parent = event.payload["parent_candidate_id"]
            if parent not in ledger.candidate_parents:
                raise TrajectoryError("revised candidate parent does not exist")
            if event.candidate_id in ledger.candidate_parents:
                raise TrajectoryError("revised candidate must receive a new id")
            if event.payload["candidate_id"] != event.candidate_id:
                raise TrajectoryError("revised candidate payload must match envelope candidate_id")
        elif (
            event.candidate_id is not None
            and event.candidate_id not in ledger.candidate_parents
        ):
            raise TrajectoryError("candidate event references an unknown candidate")
        if event.event_type == "candidate.selected":
            eligible = event.payload["eligible_candidate_ids"]
            selected = event.payload["selected_candidate_id"]
            if not isinstance(eligible, list | tuple) or selected not in eligible:
                raise TrajectoryError("selected candidate must be in the eligible set")
            if any(candidate not in ledger.candidate_parents for candidate in eligible):
                raise TrajectoryError("candidate selection references an unknown candidate")
            if selected != event.candidate_id:
                raise TrajectoryError("selected candidate must match envelope candidate_id")
        candidate_payload_fields = {
            "run.completed": "final_candidate_id",
            "final.candidate_selected": "candidate_id",
            "final.artifact_produced": "candidate_id",
        }
        candidate_field = candidate_payload_fields.get(event.event_type)
        if candidate_field is not None and event.payload[candidate_field] != event.candidate_id:
            raise TrajectoryError(
                f"payload {candidate_field} must match envelope candidate_id"
            )

    @staticmethod
    def _validate_action_attempt(
        ledger: _RunLedger,
        event: ProposedTrajectoryEvent,
    ) -> None:
        attempt_id = event.action_attempt_id
        if event.event_type == "action.started":
            assert attempt_id is not None
            if attempt_id in ledger.action_attempts:
                raise TrajectoryError("action attempt id is already in use")
        elif event.event_type in {"action.completed", "action.failed"}:
            assert attempt_id is not None
            if attempt_id not in ledger.action_attempts:
                raise TrajectoryError("action outcome requires an earlier action.started")
            if attempt_id in ledger.closed_action_attempts:
                raise TrajectoryError("action attempt already has an outcome")
        if event.event_type == "tool.started":
            assert attempt_id is not None
            if attempt_id in ledger.tool_attempts:
                raise TrajectoryError("tool attempt id is already in use")
        elif event.event_type in {"tool.completed", "tool.failed"}:
            assert attempt_id is not None
            if attempt_id not in ledger.tool_attempts:
                raise TrajectoryError("tool outcome requires an earlier tool.started")
            if attempt_id in ledger.closed_tool_attempts:
                raise TrajectoryError("tool attempt already has an outcome")

    @staticmethod
    def _validate_verification_and_repair(
        ledger: _RunLedger,
        event: ProposedTrajectoryEvent,
    ) -> None:
        if event.event_type == "verification.requested":
            check_id = event.payload["check_id"]
            if not isinstance(check_id, str) or check_id in ledger.verification_checks:
                raise TrajectoryError("verification check id must be new")
        elif event.event_type in {"verification.completed", "verification.malformed"}:
            check_id = event.payload["check_id"]
            requested = ledger.verification_checks.get(str(check_id))
            if requested is None:
                raise TrajectoryError("verification outcome requires an earlier request")
            if check_id in ledger.closed_verification_checks:
                raise TrajectoryError("verification check already has an outcome")
            if requested != (event.candidate_id, event.action_attempt_id):
                raise TrajectoryError("verification outcome changed candidate or action attempt")
        if event.event_type == "repair.requested":
            repair_id = event.payload["repair_id"]
            subject = event.payload["subject_candidate_id"]
            if not isinstance(repair_id, str) or repair_id in ledger.repair_requests:
                raise TrajectoryError("repair id must be new")
            if subject != event.candidate_id:
                raise TrajectoryError("repair subject must match envelope candidate_id")
        elif event.event_type in {"repair.completed", "repair.failed"}:
            repair_id = str(event.payload["repair_id"])
            subject = ledger.repair_requests.get(repair_id)
            if subject is None:
                raise TrajectoryError("repair outcome requires an earlier request")
            if repair_id in ledger.closed_repairs:
                raise TrajectoryError("repair already has an outcome")
            if subject != event.candidate_id:
                raise TrajectoryError("repair outcome changed its subject candidate")
            if event.event_type == "repair.completed":
                result = event.payload["result_candidate_id"]
                if ledger.candidate_parents.get(str(result)) != subject:
                    raise TrajectoryError("repair result must be a new child candidate")
        elif event.event_type == "repair.exhausted":
            subject = event.payload["subject_candidate_id"]
            attempted = event.payload["attempted_repair_ids"]
            if subject != event.candidate_id:
                raise TrajectoryError("repair exhaustion changed its subject candidate")
            if not isinstance(attempted, list | tuple) or not attempted or any(
                repair_id not in ledger.repair_requests for repair_id in attempted
            ):
                raise TrajectoryError("repair exhaustion must name requested repairs")

    @staticmethod
    def _apply_state(ledger: _RunLedger, event: StoredTrajectoryEvent) -> None:
        if event.event_type == "attempt.started":
            ledger.active_attempt_id = event.attempt_id
            main_branch = event.payload["main_branch_id"]
            if isinstance(main_branch, str):
                ledger.branches.add(main_branch)
        elif event.event_type in {"attempt.completed", "attempt.interrupted", "attempt.failed"}:
            ledger.active_attempt_id = None
        if event.event_type == "action.started":
            assert event.action_attempt_id is not None
            ledger.action_attempts.add(event.action_attempt_id)
        elif event.event_type in {"action.completed", "action.failed"}:
            assert event.action_attempt_id is not None
            ledger.closed_action_attempts.add(event.action_attempt_id)
        if event.event_type == "tool.started":
            assert event.action_attempt_id is not None
            ledger.tool_attempts.add(event.action_attempt_id)
        elif event.event_type in {"tool.completed", "tool.failed"}:
            assert event.action_attempt_id is not None
            ledger.closed_tool_attempts.add(event.action_attempt_id)
        if event.event_type == "branch.created":
            ledger.branches.add(str(event.payload["new_branch_id"]))
        elif event.event_type in {"branch.completed", "branch.failed", "branch.cancelled"}:
            ledger.closed_branches.add(str(event.payload["branch_id"]))
        if event.event_type == "candidate.created":
            assert event.candidate_id is not None
            ledger.candidate_parents[event.candidate_id] = None
        elif event.event_type == "candidate.revised":
            assert event.candidate_id is not None
            ledger.candidate_parents[event.candidate_id] = str(
                event.payload["parent_candidate_id"]
            )
        if event.event_type == "verification.requested":
            ledger.verification_checks[str(event.payload["check_id"])] = (
                str(event.candidate_id),
                str(event.action_attempt_id),
            )
        elif event.event_type in {"verification.completed", "verification.malformed"}:
            ledger.closed_verification_checks.add(str(event.payload["check_id"]))
        if event.event_type == "repair.requested":
            ledger.repair_requests[str(event.payload["repair_id"])] = str(
                event.candidate_id
            )
        elif event.event_type in {"repair.completed", "repair.failed"}:
            ledger.closed_repairs.add(str(event.payload["repair_id"]))
        if event.event_type in {
            "run.completed",
            "run.failed",
            "run.cancelled",
            "run.budget_stopped",
        }:
            ledger.terminal_event_id = event.event_id

    def events(self, run_id: str) -> tuple[StoredTrajectoryEvent, ...]:
        with self._lock:
            return tuple(self._require_run(run_id).events)

    def export_jsonl(self, run_id: str) -> str:
        return "".join(f"{canonical_json(event)}\n" for event in self.events(run_id))


def verify_trajectory(
    events: Sequence[StoredTrajectoryEvent],
    *,
    expected_scope: RunScope | None = None,
) -> None:
    if not events:
        raise IntegrityError("trajectory is empty")
    if events[0].event_type != "run.admitted" or events[0].run_seq != 1:
        raise IntegrityError("trajectory must begin with run.admitted at sequence 1")
    previous_seq = 0
    previous_hash: str | None = None
    seen_ids: set[str] = set()
    seen_idempotency: set[str] = set()
    for event in events:
        if event.run_seq <= previous_seq:
            raise IntegrityError("run sequence is not strictly increasing")
        if event.event_id in seen_ids or event.idempotency_key in seen_idempotency:
            raise IntegrityError("trajectory contains duplicate identity")
        if event.prev_event_hash != previous_hash:
            raise IntegrityError("trajectory previous-event hash is discontinuous")
        expected_hash = compute_event_hash(_event_body_for_hash(event), previous_hash)
        if event.event_hash != expected_hash:
            raise IntegrityError("trajectory event hash mismatch")
        if expected_scope is not None:
            InMemoryTrajectoryStore._validate_scope(expected_scope, event)
        previous_seq = event.run_seq
        previous_hash = event.event_hash
        seen_ids.add(event.event_id)
        seen_idempotency.add(event.idempotency_key)


def import_jsonl(text: str, *, expected_scope: RunScope | None = None) -> tuple[StoredTrajectoryEvent, ...]:
    try:
        events = tuple(
            StoredTrajectoryEvent.model_validate_json(line)
            for line in text.splitlines()
            if line.strip()
        )
    except ValueError as exc:
        raise IntegrityError("trajectory JSONL contains an invalid event") from exc
    verify_trajectory(events, expected_scope=expected_scope)
    return events


class CandidateEdge(StrictContractModel):
    candidate_id: CandidateId
    parent_candidate_id: CandidateId | None
    created_at_seq: Annotated[int, Field(ge=1)]
    branch_id: BranchId


class ClaimEvidenceEdge(StrictContractModel):
    claim_id: str
    evidence_id: str
    relationship: Literal["supports", "contradicts", "qualifies", "background"]
    active: bool
    linked_at_seq: Annotated[int, Field(ge=1)]


class TrajectoryFold(StrictContractModel):
    schema_kind: Literal["trajectory-fold"] = "trajectory-fold"
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: RunId
    event_count: Annotated[int, Field(ge=1)]
    head_event_hash: Digest
    terminal_event_type: EventTypeName | None
    total_input_tokens: Annotated[int, Field(ge=0)]
    total_output_tokens: Annotated[int, Field(ge=0)]
    total_llm_calls: Annotated[int, Field(ge=0)]
    total_tool_calls: Annotated[int, Field(ge=0)]
    total_estimated_cost_usd: MoneyUsd
    candidates: tuple[CandidateEdge, ...]
    claim_evidence: tuple[ClaimEvidenceEdge, ...]
    repair_event_ids: tuple[EventId, ...]


def fold_trajectory(events: Sequence[StoredTrajectoryEvent]) -> TrajectoryFold:
    verify_trajectory(events)
    candidate_edges: list[CandidateEdge] = []
    claim_edges: dict[tuple[str, str], ClaimEvidenceEdge] = {}
    repairs: list[str] = []
    input_tokens = output_tokens = llm_calls = tool_calls = 0
    cost = Decimal("0")
    terminal: str | None = None
    for event in events:
        if event.usage_delta is not None:
            input_tokens += event.usage_delta.input_tokens
            output_tokens += event.usage_delta.output_tokens
            llm_calls += event.usage_delta.llm_calls
            tool_calls += event.usage_delta.tool_calls
            cost += Decimal(event.usage_delta.estimated_cost_usd)
        if event.event_type in {"candidate.created", "candidate.revised"}:
            assert event.candidate_id is not None
            parent = (
                str(event.payload["parent_candidate_id"])
                if event.event_type == "candidate.revised"
                else None
            )
            candidate_edges.append(
                CandidateEdge(
                    candidate_id=event.candidate_id,
                    parent_candidate_id=parent,
                    created_at_seq=event.run_seq,
                    branch_id=event.branch_id,
                )
            )
        elif event.event_type == "claim.evidence_linked":
            key = (str(event.payload["claim_id"]), str(event.payload["evidence_id"]))
            claim_edges[key] = ClaimEvidenceEdge(
                claim_id=key[0],
                evidence_id=key[1],
                relationship=event.payload["relationship"],
                active=True,
                linked_at_seq=event.run_seq,
            )
        elif event.event_type == "claim.evidence_unlinked":
            key = (str(event.payload["claim_id"]), str(event.payload["prior_evidence_id"]))
            prior = claim_edges.get(key)
            if prior is not None:
                claim_edges[key] = prior.model_copy(update={"active": False})
        if event.event_type.startswith("repair."):
            repairs.append(event.event_id)
        if event.event_type in {
            "run.completed",
            "run.failed",
            "run.cancelled",
            "run.budget_stopped",
        }:
            terminal = event.event_type
    return TrajectoryFold(
        run_id=events[0].run_id,
        event_count=len(events),
        head_event_hash=events[-1].event_hash,
        terminal_event_type=terminal,
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        total_llm_calls=llm_calls,
        total_tool_calls=tool_calls,
        total_estimated_cost_usd=f"{cost:.6f}",
        candidates=tuple(candidate_edges),
        claim_evidence=tuple(claim_edges.values()),
        repair_event_ids=tuple(repairs),
    )


class ReplayEventView(StrictContractModel):
    schema_kind: Literal["trajectory-replay-event-view"] = (
        "trajectory-replay-event-view"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    source_event_id: EventId
    source_run_seq: Annotated[int, Field(ge=1)]
    observation_status: ObservationStatus
    counterfactual_depth: Annotated[int, Field(ge=0)]


def decision_replay_view(
    events: Sequence[StoredTrajectoryEvent],
    *,
    diverged_at_run_seq: int | None,
) -> tuple[ReplayEventView, ...]:
    verify_trajectory(events)
    if diverged_at_run_seq is not None and diverged_at_run_seq < 1:
        raise TrajectoryError("divergence sequence must be positive")
    views: list[ReplayEventView] = []
    depth = 0
    observation_types = {
        "observation.recorded",
        "tool.completed",
        "source.discovered",
    }
    for event in events:
        if diverged_at_run_seq is not None and event.run_seq >= diverged_at_run_seq:
            depth += 1
        after = diverged_at_run_seq is not None and event.run_seq > diverged_at_run_seq
        status = (
            ObservationStatus.HELD_CONSTANT_AFTER_DIVERGENCE
            if after and event.event_type in observation_types
            else ObservationStatus.RECORDED
            if event.event_type in observation_types
            else ObservationStatus.NOT_APPLICABLE
        )
        views.append(
            ReplayEventView(
                source_event_id=event.event_id,
                source_run_seq=event.run_seq,
                observation_status=status,
                counterfactual_depth=depth if after else 0,
            )
        )
    return tuple(views)


def trajectory_json_schema() -> dict[str, Any]:
    schema = StoredTrajectoryEvent.model_json_schema(mode="validation")
    schema["$id"] = "https://arxiv-research-agent.dev/schemas/trajectory-event/1.0.0"
    schema["title"] = "Stored TrajectoryEvent v1"
    return schema
