"""Development benchmark registry with fail-closed restricted-data boundaries.

The resolver in this module is intentionally local and side-effect free.  It
validates immutable objects and produces campaign locks, but never initializes
an agent, provider, credential, or network client.
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
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
    RetentionPolicyRef,
    Rfc3339Utc,
    SemVer,
    StrictContractModel,
    canonical_json,
    require_digest,
    sha256_digest,
)

RegistryId: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")
]
MemberId: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
]


class RegistryKind(StrEnum):
    """The object kinds this registry can seal, address, and resolve."""

    BENCHMARK_SUITE = "benchmark_suite"
    TASK_SET = "task_set"
    TASK_CASE = "task_case"
    RUBRIC_SET = "rubric_set"
    LABEL_SET = "label_set"
    SOURCE_SNAPSHOT = "source_snapshot"
    FIXTURE_SET = "fixture_set"
    SPLIT_ASSIGNMENT = "split_assignment"
    GRADER_PROFILE = "grader_profile"
    RETENTION_POLICY = "retention_policy"
    EXTERNAL_ADAPTER = "external_adapter"


class LifecycleStatus(StrEnum):
    """Publication state of an object; only ``active`` resolves."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"


class RegistryRole(StrEnum):
    """Who is asking, which is the axis every access decision turns on."""

    CANDIDATE = "candidate"
    EVALUATOR = "evaluator"
    OWNER = "owner"


class ObjectVisibility(StrEnum):
    """The least-privileged role allowed to see an object's full payload."""

    PUBLIC = "public"
    CANDIDATE = "candidate"
    EVALUATOR = "evaluator"
    OWNER = "owner"


class IntendedUse(StrEnum):
    """Declared purpose of a resolution, checked against object and license."""

    DEVELOPMENT = "development"
    REGRESSION = "regression"
    CALIBRATION = "calibration"
    PROMOTION = "promotion"
    CAPABILITY_PROBE = "capability_probe"


class EvaluationLane(StrEnum):
    """The product lane a benchmark suite scores."""

    RESEARCH = "research"
    GUIDED_LEARNING = "guided_learning"
    LONG_HORIZON = "long_horizon"


class SourceMode(StrEnum):
    """Whether a campaign reads frozen snapshots or the live world."""

    SNAPSHOT = "snapshot"
    LIVE = "live"


class SplitKind(StrEnum):
    """The split an assignment governs; only ``development`` resolves locally."""

    DEVELOPMENT = "development"
    VALIDATION = "validation"
    SEALED = "sealed"
    CANARY = "canary"


class Exposure(StrEnum):
    """How widely the underlying content has been published."""

    PRIVATE_UNEXPOSED = "private_unexposed"
    LIMITED_ACCESS = "limited_access"
    PUBLIC_REPOSITORY = "public_repository"
    PUBLISHED_EXTERNAL = "published_external"
    UNKNOWN = "exposure_unknown"


class Redistribution(StrEnum):
    """What the license permits when content leaves this repository."""

    PERMITTED = "permitted"
    METADATA_ONLY = "metadata_only"
    PROHIBITED = "prohibited"


class TrainingUse(StrEnum):
    """Whether content may be used to train a model."""

    PROHIBITED = "prohibited"
    CONSENT_REQUIRED = "consent_required"
    PERMITTED = "permitted"


class LicensePolicy(StrictContractModel):
    """License terms that gate redistribution and permitted use."""

    license_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    redistribution: Redistribution
    permitted_uses: tuple[IntendedUse, ...]
    attribution: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None
    expires_at: Rfc3339Utc | None = None

    @model_validator(mode="after")
    def require_attribution_when_redistributable(self) -> LicensePolicy:
        """Reject redistributable content with no attribution, and duplicate uses."""

        if self.redistribution is Redistribution.PERMITTED and self.attribution is None:
            raise ValueError("redistributable content requires attribution")
        if len(set(self.permitted_uses)) != len(self.permitted_uses):
            raise ValueError("permitted_uses must be unique")
        return self


class DataPolicy(StrictContractModel):
    """Sensitivity, personal-data, retention and deletion terms of one object."""

    registry_classification: DataClass
    effective_data_class: DataClass
    contains_personal_data: bool
    training_use: TrainingUse = TrainingUse.PROHIBITED
    retention_policy_ref: RetentionPolicyRef
    deleted_at: Rfc3339Utc | None = None


class Contamination(StrictContractModel):
    """Recorded exposure of the content, with the canary set that detects it."""

    exposure: Exposure
    canary_set_ref: ImmutableObjectRef | None = None
    last_reviewed_at: Rfc3339Utc


class Provenance(StrictContractModel):
    """Who created this revision, from which parent, under which review record."""

    created_at: Rfc3339Utc
    created_by: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    parent: ImmutableObjectRef | None = None
    review_record: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class GovernedPayload(StrictContractModel):
    """The governance every registry object carries, whatever its kind.

    Subclasses add identity and content; these fields are what the resolver
    authorizes against, so no kind can opt out of them.
    """

    revision: SemVer
    status: LifecycleStatus
    owners: tuple[Annotated[str, StringConstraints(min_length=1, max_length=128)], ...]
    visibility: ObjectVisibility
    intended_uses: tuple[IntendedUse, ...]
    prohibited_uses: tuple[IntendedUse, ...] = ()
    license_policy: LicensePolicy
    data_policy: DataPolicy
    contamination: Contamination
    provenance: Provenance

    @model_validator(mode="after")
    def validate_governance(self) -> GovernedPayload:
        """Require owners, and refuse a use that is both intended and prohibited."""

        if not self.owners:
            raise ValueError("at least one owner is required")
        if len(set(self.owners)) != len(self.owners):
            raise ValueError("owners must be unique")
        if len(set(self.intended_uses)) != len(self.intended_uses):
            raise ValueError("intended_uses must be unique")
        if set(self.intended_uses) & set(self.prohibited_uses):
            raise ValueError("an intended use cannot also be prohibited")
        return self


class BenchmarkSuite(GovernedPayload):
    """A complete, self-describing evaluation suite.

    The suite is a campaign's entry point: every other registry object it needs
    is named by an exact reference, and the kind of each reference is part of
    the suite's own validity.
    """

    suite_id: RegistryId
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    task_kinds: tuple[Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]+$")], ...]
    evaluation_lane: EvaluationLane
    task_set_ref: ImmutableObjectRef
    rubric_set_ref: ImmutableObjectRef
    label_set_refs: tuple[ImmutableObjectRef, ...] = ()
    source_snapshot_refs: tuple[ImmutableObjectRef, ...] = ()
    fixture_set_refs: tuple[ImmutableObjectRef, ...] = ()
    split_assignment_ref: ImmutableObjectRef
    grader_profile_refs: tuple[ImmutableObjectRef, ...]

    @model_validator(mode="after")
    def references_have_declared_kinds(self) -> BenchmarkSuite:
        """Check every reference's kind, and require unique task kinds and graders."""

        expected = (
            (self.task_set_ref, RegistryKind.TASK_SET),
            (self.rubric_set_ref, RegistryKind.RUBRIC_SET),
            (self.split_assignment_ref, RegistryKind.SPLIT_ASSIGNMENT),
            *((ref, RegistryKind.LABEL_SET) for ref in self.label_set_refs),
            *((ref, RegistryKind.SOURCE_SNAPSHOT) for ref in self.source_snapshot_refs),
            *((ref, RegistryKind.FIXTURE_SET) for ref in self.fixture_set_refs),
            *((ref, RegistryKind.GRADER_PROFILE) for ref in self.grader_profile_refs),
        )
        for ref, kind in expected:
            if ref.kind != kind.value:
                raise ValueError(f"{kind.value} reference has kind {ref.kind}")
        if not self.task_kinds or not self.grader_profile_refs:
            raise ValueError("suite requires task kinds and grader profiles")
        if len(set(self.task_kinds)) != len(self.task_kinds):
            raise ValueError("suite task kinds must be unique")
        grader_keys = [(ref.id, ref.revision) for ref in self.grader_profile_refs]
        if len(set(grader_keys)) != len(grader_keys):
            raise ValueError("suite grader profiles must be unique")
        return self


class TaskSet(GovernedPayload):
    """The set of task cases a suite scores."""

    task_set_id: RegistryId
    case_refs: tuple[ImmutableObjectRef, ...]

    @model_validator(mode="after")
    def cases_are_unique(self) -> TaskSet:
        """Require a non-empty, unique set of references, all of them task cases."""

        keys = [(ref.id, ref.revision) for ref in self.case_refs]
        if not self.case_refs or len(set(keys)) != len(keys):
            raise ValueError("case_refs must be non-empty and unique")
        if any(ref.kind != RegistryKind.TASK_CASE.value for ref in self.case_refs):
            raise ValueError("task set may reference only task_case objects")
        return self


class TaskInput(StrictContractModel):
    """The candidate-visible half of a task case."""

    objective: Annotated[str, StringConstraints(min_length=1, max_length=8000)]
    task_kind: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]+$")]
    constraint_refs: tuple[ImmutableObjectRef, ...] = ()
    deliverable_ref: ImmutableObjectRef


class TaskCase(GovernedPayload):
    """One scored task: its input, what the candidate sees, evaluator material."""

    case_id: RegistryId
    task_input: TaskInput
    candidate_visible_refs: tuple[ImmutableObjectRef, ...] = ()
    evaluator_refs: tuple[ImmutableObjectRef, ...] = ()
    slice_tags: tuple[MemberId, ...] = ()


class RubricItem(StrictContractModel):
    """One scored criterion, with its scale, evidence type and aggregation rule."""

    rubric_item_id: MemberId
    revision: SemVer
    description: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    task_kinds: tuple[str, ...]
    scoring_type: Literal["boolean", "integer", "decimal", "categorical"]
    minimum: int | None = None
    maximum: int | None = None
    evidence_type: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    visibility: ObjectVisibility
    aggregation: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    denominator_policy: Annotated[str, StringConstraints(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def range_is_valid(self) -> RubricItem:
        """Require a minimum and maximum together, and in order."""

        if (self.minimum is None) != (self.maximum is None):
            raise ValueError("minimum and maximum must be supplied together")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("rubric minimum cannot exceed maximum")
        return self


class RubricSet(GovernedPayload):
    """The rubric items a grader profile applies, unique by item id."""

    rubric_set_id: RegistryId
    items: tuple[RubricItem, ...]

    @model_validator(mode="after")
    def items_are_unique(self) -> RubricSet:
        ids = [item.rubric_item_id for item in self.items]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("rubric items must be non-empty and unique")
        return self


class LabelRecord(StrictContractModel):
    """One judgement about a target object, with its annotator and guideline."""

    label_id: MemberId
    target_ref: ImmutableObjectRef
    label_type: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    value_ref: ImmutableObjectRef
    evidence_refs: tuple[ImmutableObjectRef, ...] = ()
    annotator_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    guideline_ref: ImmutableObjectRef
    labeled_at: Rfc3339Utc
    agreement_state: Literal["unreviewed", "agreed", "disputed", "adjudicated"]
    supersedes_ref: ImmutableObjectRef | None = None


class LabelSet(GovernedPayload):
    """A revision-stable collection of labels with unique ids."""

    label_set_id: RegistryId
    labels: tuple[LabelRecord, ...]

    @model_validator(mode="after")
    def labels_are_unique(self) -> LabelSet:
        ids = [label.label_id for label in self.labels]
        if len(set(ids)) != len(ids):
            raise ValueError("label ids must be unique")
        return self


class SourceSnapshot(GovernedPayload):
    """A frozen acquisition of external content, with its current availability."""

    snapshot_id: RegistryId
    source_ref: ImmutableObjectRef
    accessed_at: Rfc3339Utc
    published_at: Rfc3339Utc | None = None
    request_ref: ImmutableObjectRef | None = None
    content_ref: ImmutableObjectRef | None = None
    locator: Annotated[str, StringConstraints(min_length=1, max_length=500)] | None = None
    parser_ref: ImmutableObjectRef | None = None
    availability: Literal["available", "missing", "retracted", "corrected", "access_denied"]


class FixtureObservation(StrictContractModel):
    """One recorded tool observation inside a replayable fixture."""

    sequence: Annotated[int, Field(ge=1)]
    observation_ref: ImmutableObjectRef
    tool_contract_ref: ImmutableObjectRef
    sanitized: bool


class FixtureSet(GovernedPayload):
    """An ordered replay of tool observations, numbered contiguously from 1."""

    fixture_set_id: RegistryId
    observations: tuple[FixtureObservation, ...]

    @model_validator(mode="after")
    def observations_are_ordered(self) -> FixtureSet:
        """Require the observation sequence to be contiguous and start at 1."""

        expected = list(range(1, len(self.observations) + 1))
        if [item.sequence for item in self.observations] != expected:
            raise ValueError("fixture observation sequence must be contiguous from 1")
        return self


class SplitAssignment(GovernedPayload):
    """Which cases belong to a split; membership is never candidate-visible."""

    split_assignment_id: RegistryId
    split: SplitKind
    case_refs: tuple[ImmutableObjectRef, ...]
    membership_visible_to_candidate: Literal[False] = False

    @model_validator(mode="after")
    def case_refs_are_valid(self) -> SplitAssignment:
        """Require unique references, and nothing but task cases, in a split."""

        identities = [(ref.id, ref.revision) for ref in self.case_refs]
        if len(set(identities)) != len(identities):
            raise ValueError("split membership must be unique")
        if any(ref.kind != RegistryKind.TASK_CASE.value for ref in self.case_refs):
            raise ValueError("split may contain only task_case refs")
        return self


class GraderProfile(GovernedPayload):
    """How a suite is scored: metrics, optional judge, rubric and calibration."""

    grader_profile_id: RegistryId
    deterministic_metric_refs: tuple[ImmutableObjectRef, ...] = ()
    model_judge_ref: ImmutableObjectRef | None = None
    prompt_ref: ImmutableObjectRef | None = None
    rubric_set_ref: ImmutableObjectRef
    calibration_ref: ImmutableObjectRef | None = None
    null_score_policy: Annotated[str, StringConstraints(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def rubric_kind_is_valid(self) -> GraderProfile:
        if self.rubric_set_ref.kind != RegistryKind.RUBRIC_SET.value:
            raise ValueError("grader rubric_set_ref must have rubric_set kind")
        return self


class RetentionPolicy(GovernedPayload):
    """How long content is kept and what its deletion leaves behind."""

    retention_policy_id: RegistryId
    duration_days: Annotated[int, Field(ge=0)] | None
    deletion_mode: Literal["delete_content_keep_tombstone", "repository_history"]


class ExternalAdapter(GovernedPayload):
    """Attribution and conversion record for content acquired upstream."""

    adapter_id: RegistryId
    upstream_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    upstream_version: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    canonical_url: Annotated[str, StringConstraints(pattern=r"^https://")]
    citation: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    acquisition_ref: ImmutableObjectRef
    conversion_ref: ImmutableObjectRef
    redistribution_forbidden: bool


RegistryPayload: TypeAlias = (
    BenchmarkSuite
    | TaskSet
    | TaskCase
    | RubricSet
    | LabelSet
    | SourceSnapshot
    | FixtureSet
    | SplitAssignment
    | GraderProfile
    | RetentionPolicy
    | ExternalAdapter
)

_PAYLOAD_KIND: dict[type[GovernedPayload], RegistryKind] = {
    BenchmarkSuite: RegistryKind.BENCHMARK_SUITE,
    TaskSet: RegistryKind.TASK_SET,
    TaskCase: RegistryKind.TASK_CASE,
    RubricSet: RegistryKind.RUBRIC_SET,
    LabelSet: RegistryKind.LABEL_SET,
    SourceSnapshot: RegistryKind.SOURCE_SNAPSHOT,
    FixtureSet: RegistryKind.FIXTURE_SET,
    SplitAssignment: RegistryKind.SPLIT_ASSIGNMENT,
    GraderProfile: RegistryKind.GRADER_PROFILE,
    RetentionPolicy: RegistryKind.RETENTION_POLICY,
    ExternalAdapter: RegistryKind.EXTERNAL_ADAPTER,
}

_ID_FIELD: dict[RegistryKind, str] = {
    RegistryKind.BENCHMARK_SUITE: "suite_id",
    RegistryKind.TASK_SET: "task_set_id",
    RegistryKind.TASK_CASE: "case_id",
    RegistryKind.RUBRIC_SET: "rubric_set_id",
    RegistryKind.LABEL_SET: "label_set_id",
    RegistryKind.SOURCE_SNAPSHOT: "snapshot_id",
    RegistryKind.FIXTURE_SET: "fixture_set_id",
    RegistryKind.SPLIT_ASSIGNMENT: "split_assignment_id",
    RegistryKind.GRADER_PROFILE: "grader_profile_id",
    RegistryKind.RETENTION_POLICY: "retention_policy_id",
    RegistryKind.EXTERNAL_ADAPTER: "adapter_id",
}


class RegistryIntegrity(StrictContractModel):
    """The payload digest, and the profile under which it was computed."""

    algorithm: Literal["sha256"] = "sha256"
    digest_profile: Literal["agent-contract-json/v1"] = "agent-contract-json/v1"
    payload_digest: Digest


class RegistryEnvelope(StrictContractModel):
    """A sealed registry object: its kind, its payload, and a matching digest.

    Validation is the seal.  An envelope cannot exist whose declared kind
    disagrees with its payload type, or whose digest disagrees with its content.
    """

    schema_kind: RegistryKind
    schema_version: Literal["1.0.0"] = "1.0.0"
    payload: RegistryPayload
    integrity: RegistryIntegrity

    @model_validator(mode="after")
    def verify_kind_and_digest(self) -> RegistryEnvelope:
        """Refuse a mislabelled envelope or one whose digest is not its content."""

        expected_kind = _PAYLOAD_KIND[type(self.payload)]
        if self.schema_kind is not expected_kind:
            raise ValueError(
                f"schema_kind {self.schema_kind.value} does not match payload {expected_kind.value}"
            )
        require_digest(self.payload, self.integrity.payload_digest)
        return self

    @property
    def object_id(self) -> str:
        return str(getattr(self.payload, _ID_FIELD[self.schema_kind]))

    def object_ref(self) -> ImmutableObjectRef:
        """Return the exact immutable reference that addresses this envelope."""

        return ImmutableObjectRef(
            kind=self.schema_kind.value,
            id=self.object_id,
            revision=self.payload.revision,
            digest=self.integrity.payload_digest,
        )


def seal_registry_object(payload: RegistryPayload) -> RegistryEnvelope:
    """Wrap a validated payload in a self-verifying immutable envelope."""

    kind = _PAYLOAD_KIND[type(payload)]
    return RegistryEnvelope(
        schema_kind=kind,
        payload=payload,
        integrity=RegistryIntegrity(payload_digest=sha256_digest(payload)),
    )


class RegistryAccessError(ContractError):
    """The caller's role is not permitted to see the object it asked for."""

    def __init__(self, detail: str) -> None:
        super().__init__(ContractErrorCode.REDACTION_REQUIRED, detail)


class RegistryResolutionError(ContractError):
    """The reference did not resolve, or resolved to something unusable."""

    def __init__(self, detail: str) -> None:
        super().__init__(ContractErrorCode.REF_INVALID, detail)


class RestrictedRegistryUnavailable(RegistryAccessError):
    """A real restricted-data broker is required for this operation."""


class RegistryResolver(Protocol):
    """Resolve one exact reference for a named role and a declared use."""

    def resolve(
        self,
        ref: ImmutableObjectRef,
        *,
        role: RegistryRole,
        intended_use: IntendedUse,
        now: datetime | None = None,
    ) -> RegistryEnvelope: ...


_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|token)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_PRIVATE_ABSOLUTE_PATH = re.compile(r"(?:/Users/|/home/|/private/|[A-Za-z]:\\Users\\)")
_CANDIDATE_DENIED_KINDS = {
    RegistryKind.BENCHMARK_SUITE,
    RegistryKind.TASK_SET,
    RegistryKind.LABEL_SET,
    RegistryKind.SPLIT_ASSIGNMENT,
    RegistryKind.GRADER_PROFILE,
    RegistryKind.RETENTION_POLICY,
    RegistryKind.EXTERNAL_ADAPTER,
}


def _walk_strings(value: Any) -> Iterable[tuple[str, str]]:
    """Yield ``(json_path, text)`` for every string reachable inside a payload."""

    if isinstance(value, str):
        yield "$", value
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            for path, text in _walk_strings(child):
                yield f"$.{key}{path[1:]}", text
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            for path, text in _walk_strings(child):
                yield f"$[{index}]{path[1:]}", text


def validate_registry_safety(envelope: RegistryEnvelope) -> None:
    """Reject secret-shaped values and private absolute paths."""

    for path, text in _walk_strings(envelope.model_dump(mode="json")):
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            raise RegistryAccessError(f"secret-shaped value at {path}")
        if _PRIVATE_ABSOLUTE_PATH.search(text):
            raise RegistryAccessError(f"private absolute path at {path}")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00")


def _authorize(
    envelope: RegistryEnvelope,
    *,
    role: RegistryRole,
    intended_use: IntendedUse,
    now: datetime,
) -> None:
    """Refuse a resolution that lifecycle, license, use or role forbids.

    The order matters: an object that is not resolvable at all fails before any
    role check, and a split this local resolver may not serve raises
    ``RestrictedRegistryUnavailable`` rather than a flat denial.
    """

    payload = envelope.payload
    validate_registry_safety(envelope)
    if payload.status is not LifecycleStatus.ACTIVE:
        raise RegistryResolutionError(f"object lifecycle is {payload.status.value}, not active")
    if payload.data_policy.deleted_at is not None:
        raise RegistryResolutionError("object content has been deleted")
    if (
        payload.license_policy.expires_at is not None
        and now >= _parse_utc(payload.license_policy.expires_at)
    ):
        raise RegistryResolutionError("object license or availability has expired")
    if intended_use not in payload.intended_uses:
        raise RegistryResolutionError(f"object does not declare {intended_use.value} use")
    if intended_use in payload.prohibited_uses:
        raise RegistryResolutionError(f"object prohibits {intended_use.value} use")
    if intended_use not in payload.license_policy.permitted_uses:
        raise RegistryResolutionError(f"license does not permit {intended_use.value} use")
    if isinstance(payload, SourceSnapshot) and payload.availability != "available":
        raise RegistryResolutionError(
            f"source snapshot is not available: {payload.availability}"
        )
    if isinstance(payload, SplitAssignment) and payload.split is not SplitKind.DEVELOPMENT:
        raise RestrictedRegistryUnavailable(
            f"{payload.split.value} split requires a configured access broker"
        )
    if role is RegistryRole.CANDIDATE:
        if envelope.schema_kind in _CANDIDATE_DENIED_KINDS:
            raise RegistryAccessError(f"candidate cannot resolve {envelope.schema_kind.value}")
        if payload.visibility not in {ObjectVisibility.PUBLIC, ObjectVisibility.CANDIDATE}:
            raise RegistryAccessError("candidate cannot resolve evaluator or owner material")
        if isinstance(payload, FixtureSet) and any(
            not observation.sanitized for observation in payload.observations
        ):
            raise RegistryAccessError("candidate cannot resolve an unsanitized fixture")
    elif role is RegistryRole.EVALUATOR and payload.visibility is ObjectVisibility.OWNER:
        raise RegistryAccessError("evaluator cannot resolve owner-only material")


class InMemoryRegistry:
    """Immutable in-memory adapter for deterministic tests and dry runs."""

    def __init__(self, objects: Iterable[RegistryEnvelope] = ()) -> None:
        self._objects: dict[tuple[str, str, str], RegistryEnvelope] = {}
        for envelope in objects:
            self.add(envelope)

    def add(self, envelope: RegistryEnvelope) -> None:
        """Store one envelope, refusing to give a sealed revision new content."""

        key = (envelope.schema_kind.value, envelope.object_id, envelope.payload.revision)
        current = self._objects.get(key)
        if current is not None and current.integrity.payload_digest != envelope.integrity.payload_digest:
            raise RegistryResolutionError("immutable object revision cannot be overwritten")
        self._objects[key] = envelope

    def resolve(
        self,
        ref: ImmutableObjectRef,
        *,
        role: RegistryRole,
        intended_use: IntendedUse,
        now: datetime | None = None,
    ) -> RegistryEnvelope:
        """Resolve an exact reference, checking its digest before authorizing."""

        key = (ref.kind, ref.id, ref.revision)
        envelope = self._objects.get(key)
        if envelope is None:
            raise RegistryResolutionError(f"registry object not found: {key!r}")
        if envelope.integrity.payload_digest != ref.digest:
            raise RegistryResolutionError("registry reference digest mismatch")
        _authorize(
            envelope,
            role=role,
            intended_use=intended_use,
            now=now or datetime.now(UTC),
        )
        return envelope


class LocalRegistry:
    """Read exact public/development objects from a Git-compatible tree."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, ref: ImmutableObjectRef) -> Path:
        """Map a reference onto its file, refusing a locator that escapes the root."""

        candidate = (self.root / ref.kind / ref.id / f"{ref.revision}.json").resolve()
        if not candidate.is_relative_to(self.root):
            raise RegistryResolutionError("registry locator escaped its root")
        return candidate

    def resolve(
        self,
        ref: ImmutableObjectRef,
        *,
        role: RegistryRole,
        intended_use: IntendedUse,
        now: datetime | None = None,
    ) -> RegistryEnvelope:
        """Load, re-seal and authorize the object an exact reference names."""

        path = self._path(ref)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RegistryResolutionError(f"registry object is unavailable: {ref.kind}/{ref.id}") from exc
        try:
            envelope = RegistryEnvelope.model_validate_json(raw)
        except ValueError as exc:
            raise RegistryResolutionError(f"invalid registry envelope: {ref.kind}/{ref.id}") from exc
        if envelope.object_ref() != ref:
            raise RegistryResolutionError("resolved registry identity does not match the exact reference")
        _authorize(
            envelope,
            role=role,
            intended_use=intended_use,
            now=now or datetime.now(UTC),
        )
        return envelope


def project_for_role(envelope: RegistryEnvelope, role: RegistryRole) -> dict[str, Any]:
    """Return the least-privilege payload projection for an authorized role."""

    payload = envelope.payload.model_dump(mode="json")
    if role is not RegistryRole.CANDIDATE:
        if role is RegistryRole.EVALUATOR and envelope.payload.visibility is ObjectVisibility.OWNER:
            raise RegistryAccessError("evaluator projection denied for owner-only material")
        return payload
    if envelope.schema_kind in _CANDIDATE_DENIED_KINDS:
        raise RegistryAccessError(f"candidate projection denied for {envelope.schema_kind.value}")
    if envelope.payload.visibility not in {
        ObjectVisibility.PUBLIC,
        ObjectVisibility.CANDIDATE,
    }:
        raise RegistryAccessError("candidate projection denied for hidden material")
    if isinstance(envelope.payload, TaskCase):
        return {
            "case_id": payload["case_id"],
            "revision": payload["revision"],
            "task_input": payload["task_input"],
            "candidate_visible_refs": payload["candidate_visible_refs"],
            "effective_data_class": payload["data_policy"]["effective_data_class"],
        }
    elif isinstance(envelope.payload, RubricSet):
        return {
            "rubric_set_id": payload["rubric_set_id"],
            "revision": payload["revision"],
            "items": [
                item
                for item in payload["items"]
                if item["visibility"]
                in {ObjectVisibility.PUBLIC.value, ObjectVisibility.CANDIDATE.value}
            ],
        }
    elif isinstance(envelope.payload, SourceSnapshot):
        return {
            key: payload[key]
            for key in (
                "snapshot_id",
                "revision",
                "source_ref",
                "accessed_at",
                "published_at",
                "content_ref",
                "availability",
            )
        }
    elif isinstance(envelope.payload, FixtureSet):
        return {
            "fixture_set_id": payload["fixture_set_id"],
            "revision": payload["revision"],
            "observations": payload["observations"],
        }
    return payload


def validate_split_disjointness(assignments: Iterable[SplitAssignment]) -> None:
    """Prove no immutable case revision belongs to more than one split."""

    membership: dict[tuple[str, str], SplitKind] = {}
    for assignment in assignments:
        for ref in assignment.case_refs:
            key = (ref.id, ref.revision)
            previous = membership.get(key)
            if previous is not None and previous is not assignment.split:
                raise RegistryResolutionError(
                    f"case {ref.id}@{ref.revision} belongs to {previous.value} and "
                    f"{assignment.split.value}"
                )
            membership[key] = assignment.split


class CampaignLock(StrictContractModel):
    """The fully resolved selection a campaign will run, frozen.

    Every reference is exact and every case left out is named, so a rerun that
    resolves the same lock scores the same denominator.
    """

    schema_kind: Literal["registry-lock"] = "registry-lock"
    schema_version: Literal["1.0.0"] = "1.0.0"
    suite_ref: ImmutableObjectRef
    split: Literal["development"] = "development"
    intended_use: IntendedUse
    source_mode: SourceMode
    selection_rule: Literal["explicit_case_ids"] = "explicit_case_ids"
    case_refs: tuple[ImmutableObjectRef, ...]
    resolved_refs: tuple[ImmutableObjectRef, ...]
    repeats: Annotated[int, Field(ge=1)]
    expected_denominator: Annotated[int, Field(ge=1)]
    exclusions: tuple[RegistryId, ...] = ()


class RegistryValidationReceipt(StrictContractModel):
    """Proof that one lock digest was validated, by whom and when."""

    schema_kind: Literal["registry-validation-receipt"] = "registry-validation-receipt"
    schema_version: Literal["1.0.0"] = "1.0.0"
    lock_digest: Digest
    resolved_object_count: Annotated[int, Field(ge=1)]
    validated_at: Rfc3339Utc
    validator_ref: ImmutableObjectRef


def _suite_refs(suite: BenchmarkSuite) -> tuple[ImmutableObjectRef, ...]:
    """Return every registry reference a suite depends on, in a stable order."""

    return (
        suite.task_set_ref,
        suite.rubric_set_ref,
        *suite.label_set_refs,
        *suite.source_snapshot_refs,
        *suite.fixture_set_refs,
        suite.split_assignment_ref,
        *suite.grader_profile_refs,
    )


def generate_campaign_lock(
    resolver: RegistryResolver,
    suite_ref: ImmutableObjectRef,
    *,
    case_ids: tuple[str, ...],
    repeats: int,
    intended_use: IntendedUse,
    source_mode: SourceMode,
    now: datetime | None = None,
) -> CampaignLock:
    """Resolve an exact development suite into a deterministic immutable lock."""

    if repeats < 1:
        raise RegistryResolutionError("repeats must be positive")
    if not case_ids or len(set(case_ids)) != len(case_ids):
        raise RegistryResolutionError("explicit case ids must be non-empty and unique")
    effective_now = now or datetime.now(UTC)
    suite_envelope = resolver.resolve(
        suite_ref, role=RegistryRole.EVALUATOR, intended_use=intended_use, now=effective_now
    )
    if not isinstance(suite_envelope.payload, BenchmarkSuite):
        raise RegistryResolutionError("suite_ref did not resolve to a benchmark suite")
    suite = suite_envelope.payload
    task_set_envelope = resolver.resolve(
        suite.task_set_ref,
        role=RegistryRole.EVALUATOR,
        intended_use=intended_use,
        now=effective_now,
    )
    if not isinstance(task_set_envelope.payload, TaskSet):
        raise RegistryResolutionError("task_set_ref did not resolve to a task set")
    task_set = task_set_envelope.payload
    by_id = {ref.id: ref for ref in task_set.case_refs}
    try:
        selected = tuple(by_id[case_id] for case_id in case_ids)
    except KeyError as exc:
        raise RegistryResolutionError(f"selected case is absent from task set: {exc.args[0]}") from exc

    resolved: list[ImmutableObjectRef] = [suite_ref]
    seen = {(suite_ref.kind, suite_ref.id, suite_ref.revision)}
    split: SplitAssignment | None = None
    for ref in _suite_refs(suite):
        envelope = resolver.resolve(
            ref, role=RegistryRole.EVALUATOR, intended_use=intended_use, now=effective_now
        )
        if ref == suite.split_assignment_ref:
            if not isinstance(envelope.payload, SplitAssignment):
                raise RegistryResolutionError("split ref did not resolve to split assignment")
            split = envelope.payload
        key = (ref.kind, ref.id, ref.revision)
        if key not in seen:
            resolved.append(envelope.object_ref())
            seen.add(key)
    if split is None or split.split is not SplitKind.DEVELOPMENT:
        raise RestrictedRegistryUnavailable("P0 local locks support development splits only")
    task_membership = {(ref.id, ref.revision, ref.digest) for ref in task_set.case_refs}
    split_membership = {(ref.id, ref.revision, ref.digest) for ref in split.case_refs}
    if task_membership != split_membership:
        raise RegistryResolutionError("task set and development split membership differ")
    if any((ref.id, ref.revision, ref.digest) not in split_membership for ref in selected):
        raise RegistryResolutionError("selected case is outside the authorized development split")
    for ref in selected:
        envelope = resolver.resolve(
            ref, role=RegistryRole.EVALUATOR, intended_use=intended_use, now=effective_now
        )
        key = (ref.kind, ref.id, ref.revision)
        if key not in seen:
            resolved.append(envelope.object_ref())
            seen.add(key)
    return CampaignLock(
        suite_ref=suite_ref,
        intended_use=intended_use,
        source_mode=source_mode,
        case_refs=selected,
        resolved_refs=tuple(resolved),
        repeats=repeats,
        expected_denominator=len(selected) * repeats,
        exclusions=tuple(ref.id for ref in task_set.case_refs if ref.id not in set(case_ids)),
    )


def validate_lock(
    lock: CampaignLock,
    *,
    validated_at: str,
    validator_ref: ImmutableObjectRef,
) -> RegistryValidationReceipt:
    """Return a receipt binding a lock's digest to its validator and time."""

    return RegistryValidationReceipt(
        lock_digest=sha256_digest(lock),
        resolved_object_count=len(lock.resolved_refs),
        validated_at=validated_at,
        validator_ref=validator_ref,
    )


def registry_json_schema() -> dict[str, Any]:
    """Export the full registry-envelope JSON Schema."""

    schema = RegistryEnvelope.model_json_schema(mode="validation")
    schema["$id"] = "https://arxiv-research-agent.dev/schemas/eval-registry/v1/envelope"
    schema["title"] = "Evaluation registry envelope v1"
    return schema


def _parse_ref(args: argparse.Namespace) -> ImmutableObjectRef:
    return ImmutableObjectRef(
        kind=args.kind,
        id=args.id,
        revision=args.revision,
        digest=args.digest,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and resolve development registry data")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate one registry envelope")
    validate.add_argument("path", type=Path)
    parity = subparsers.add_parser(
        "parity",
        help="compare a registry tree with the live benchmark modules",
    )
    parity.add_argument("root", type=Path, nargs="?", default=None)
    for name in ("resolve", "lock"):
        command = subparsers.add_parser(name)
        command.add_argument("root", type=Path)
        command.add_argument("kind")
        command.add_argument("id")
        command.add_argument("revision")
        command.add_argument("digest")
        command.add_argument("--use", choices=[item.value for item in IntendedUse], required=True)
        if name == "resolve":
            command.add_argument("--role", choices=[item.value for item in RegistryRole], required=True)
        else:
            command.add_argument("--case", action="append", required=True)
            command.add_argument("--repeats", type=int, default=1)
            command.add_argument(
                "--source-mode",
                choices=[item.value for item in SourceMode],
                required=True,
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Read-only CLI; successful commands print canonical JSON to stdout."""

    args = _build_parser().parse_args(argv)
    if args.command == "validate":
        envelope = RegistryEnvelope.model_validate_json(args.path.read_text(encoding="utf-8"))
        validate_registry_safety(envelope)
        print(canonical_json(envelope.object_ref()))
        return 0
    if args.command == "parity":
        # Imported here because the adapters import this module: the registry
        # core stays free of any dependency on the benchmark modules it
        # registers, and only this one command pays for them.
        from src.contracts.benchmark_adapters import build_parity_report, render_parity_report

        report = build_parity_report(args.root)
        print(render_parity_report(report))
        return 0 if report.ok else 1
    resolver = LocalRegistry(args.root)
    ref = _parse_ref(args)
    intended_use = IntendedUse(args.use)
    if args.command == "resolve":
        envelope = resolver.resolve(
            ref, role=RegistryRole(args.role), intended_use=intended_use
        )
        print(canonical_json(project_for_role(envelope, RegistryRole(args.role))))
        return 0
    lock = generate_campaign_lock(
        resolver,
        ref,
        case_ids=tuple(args.case),
        repeats=args.repeats,
        intended_use=intended_use,
        source_mode=SourceMode(args.source_mode),
    )
    print(canonical_json(lock))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
