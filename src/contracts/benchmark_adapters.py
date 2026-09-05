"""Registry content for the current benchmarks, and adapters back to their old shapes.

This module registers what the repository already evaluates — the twenty
research queries in :mod:`src.eval.benchmark_queries` and the fifteen guided
reading scenarios in :mod:`src.eval.learning_benchmark` — as immutable
registry objects (P0-WO06).  It changes no benchmark meaning and claims no new
generalization evidence: every id, every ordering and every scored field is
carried across verbatim, and a parity report proves it.

Three layers, in dependency order:

- **Content objects.**  W02's registry (:mod:`src.contracts.registry`) carries
  governance metadata and typed references; it deliberately has no inline
  payload field for evaluation material, and RFC 11 §10 says large content is
  content-addressed and referenced rather than embedded in a manifest.  So the
  verbatim material — expected topics, personas, papers, learner scripts,
  structural expectations — lives in small content objects under
  ``eval_registry/content/`` with their own canonical digests, resolved by
  :class:`LocalContentStore` under the same role rules the registry enforces.
- **Registry objects.**  Suites, task sets, task cases, rubric sets, label
  sets, split assignments, grader profiles, fixture sets and a retention
  policy, all built by :func:`build_registry` from the live modules and sealed
  with :func:`src.contracts.registry.seal_registry_object`.
- **Adapters and parity.**  :func:`load_research_benchmark` and
  :func:`load_learning_benchmark` rebuild the exact ``BenchmarkQuery`` /
  ``LearningScenario`` dictionaries the runners read today, from registry
  content alone.  :func:`build_parity_report` compares the checked-in tree
  with the live modules on ids, order, membership, per-record fields and
  score semantics, and names every mismatch.

The runners keep reading their own modules.  Nothing here is authoritative
until a later ADR says so, and nothing here initializes a provider, a client
or a network call.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, Literal, NamedTuple, TypeAlias

from pydantic import Field, StringConstraints, model_validator

from src.contracts.kernel import (
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

# The three underscored names below are W02's secret-shape patterns and its
# string walker, imported rather than copied: two lists of secret shapes drift,
# and the one that drifts is always the one nobody reads.
from src.contracts.registry import (
    _PRIVATE_ABSOLUTE_PATH,
    _SECRET_PATTERNS,
    BenchmarkSuite,
    Contamination,
    DataPolicy,
    EvaluationLane,
    Exposure,
    FixtureObservation,
    FixtureSet,
    GraderProfile,
    IntendedUse,
    LabelRecord,
    LabelSet,
    LicensePolicy,
    LifecycleStatus,
    ObjectVisibility,
    Provenance,
    Redistribution,
    RegistryAccessError,
    RegistryEnvelope,
    RegistryId,
    RegistryResolutionError,
    RegistryRole,
    RetentionPolicy,
    RubricItem,
    RubricSet,
    SplitAssignment,
    SplitKind,
    TaskCase,
    TaskInput,
    TaskSet,
    TrainingUse,
    _walk_strings,
    seal_registry_object,
    validate_registry_safety,
)
from src.eval.benchmark_queries import (
    BENCHMARK_QUERIES,
    DATASET_AUTHOR,
    DATASET_LICENSE,
    RESEARCH_DATASET_VERSION,
    BenchmarkQuery,
)
from src.eval.learning_benchmark import (
    BENCHMARK_PAPERS,
    LEARNING_SCENARIOS,
    PERSONAS,
    BenchmarkGoal,
    BenchmarkPaper,
    BenchmarkSkill,
    LearnerPersona,
    LearnerTurn,
    LearningScenario,
    ScenarioExpectations,
)
from src.eval.learning_fixtures import (
    FIXTURE_ROOT,
    FixtureManifest,
    load_manifest,
)
from src.eval.learning_fixtures import (
    FixtureSet as ManifestFixtureSet,
)
from src.eval.learning_metrics import LEARNING_RUBRICS, SIMULATION_RUBRICS
from src.eval.metrics import RESEARCH_RUBRICS
from src.eval.provenance import Rubric, dataset_fingerprint

# --------------------------------------------------------------------------
# Locations and shared constants
# --------------------------------------------------------------------------

#: Root of the checked-in registry tree.  RFC 11 §16 proposes ``eval_registry/``;
#: the directory *inside* it is ``<kind>/<id>/<revision>.json`` because that is
#: the locator W02's :class:`src.contracts.registry.LocalRegistry` already
#: resolves, and a locator is not identity (RFC 11 §5.1).
REGISTRY_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "eval_registry"

#: Content objects live under one subdirectory of the same root so a registry
#: reference never resolves to content and vice versa.
CONTENT_DIRNAME: Final[str] = "content"

#: Every object registered by this work order is revision ``1.0.0``: it is the
#: first registration of material that already existed, not a new edition of it.
OBJECT_REVISION: Final[str] = "1.0.0"

#: Registration timestamp, a constant so digests do not move with the clock.
REGISTERED_AT: Final[str] = "2026-09-05T00:00:00Z"

#: Review record every object carries, and the ADR that authorized it.
REVIEW_RECORD: Final[str] = "docs/decisions/0079-benchmark-registry-migration-and-parity.md"

OWNERS: Final[tuple[str, ...]] = ("maintainer",)

#: Development and regression only.  ``promotion`` is refused outright, and
#: ``calibration``/``capability_probe`` are simply not declared, so the resolver
#: refuses them too (RFC 11 §20.9).
INTENDED_USES: Final[tuple[IntendedUse, ...]] = (
    IntendedUse.DEVELOPMENT,
    IntendedUse.REGRESSION,
)
PROHIBITED_USES: Final[tuple[IntendedUse, ...]] = (IntendedUse.PROMOTION,)

#: The current research runner drives one workflow shape for all twenty
#: queries, so one task kind is the honest declaration.  RFC 11 §6's example
#: lists four; declaring the other three would claim coverage the benchmark
#: does not have (ADR 0079).
RESEARCH_TASK_KIND: Final[str] = "research.focused_evidence_review"
LEARNING_TASK_KIND: Final[str] = "learning.guided_reading"

RESEARCH_SUITE_ID: Final[str] = "research-policy-v1"
LEARNING_SUITE_ID: Final[str] = "guided-learning-v1"

#: Name the learning scenario set is fingerprinted under.  Mirrors
#: ``src.eval.simulate_learner.LEARNING_DATASET_NAME``; that module pulls in the
#: session graph and the LLM client, which a contract module must not import.
#: ``tests/test_benchmark_adapters.py`` pins the two together.
LEARNING_DATASET_NAME: Final[str] = "learning-benchmark"

#: Reference kind for one recorded or hand-authored learning fixture file.
#: Its digest is the SHA-256 of the file's exact bytes rather than of canonical
#: JSON: the fixture is an external artifact, and its bytes are what a replay
#: reads.
FIXTURE_OBSERVATION_KIND: Final[str] = "learning_fixture"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    """Return a registry-safe logical name; the verbatim id stays in content."""

    return _SLUG_RE.sub("-", value.lower()).strip("-")


def _iso_date_to_utc(value: str) -> str:
    """Widen an ISO date such as ``2026-07-05`` to an RFC 3339 UTC instant."""

    return f"{value}T00:00:00Z"


def _utc_to_iso_date(value: str) -> str:
    """Narrow an RFC 3339 UTC midnight back to the ISO date it came from."""

    return value.removesuffix("T00:00:00Z")


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# Content objects
# --------------------------------------------------------------------------


class ContentKind(StrEnum):
    """Content payloads this registry stores outside the governance envelope."""

    RETENTION_POLICY = "retention_policy"
    DELIVERABLE_CONTRACT = "deliverable_contract"
    SOURCE_POLICY = "source_policy"
    GRADER_LOCK = "grader_lock"
    RESEARCH_EXPECTED_TOPICS = "research_expected_topics"
    LEARNING_PERSONA = "learning_persona"
    LEARNING_PAPER = "learning_paper"
    LEARNING_SCENARIO_INPUT = "learning_scenario_input"
    LEARNING_SCRIPT = "learning_script"
    LEARNING_EXPECTATIONS = "learning_expectations"
    LEARNING_FIXTURE_MANIFEST_ENTRY = "learning_fixture_manifest_entry"


Confidence: TypeAlias = Annotated[str, StringConstraints(pattern=r"^[01]\.[0-9]{1,6}$")]


class RetentionTerms(StrictContractModel):
    """The terms a retention policy object is itself retained under.

    The registry's root retention policy cannot reference itself — its digest
    would depend on its own digest — so it references these bootstrap terms.
    """

    terms_id: RegistryId
    duration_days: Annotated[int, Field(ge=0)] | None
    deletion_mode: Literal["delete_content_keep_tombstone", "repository_history"]
    description: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class DeliverableDescriptor(StrictContractModel):
    deliverable_id: Annotated[str, StringConstraints(pattern=r"^del_[a-z0-9_]{1,48}$")]
    kind: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    media_type: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    required: bool


class DeliverableContract(StrictContractModel):
    """What a compiled case must return, in the vocabulary of TaskSpec v1."""

    contract_id: RegistryId
    task_kind: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]+$")]
    deliverables: tuple[DeliverableDescriptor, ...]
    description: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class SourcePolicyDescriptor(StrictContractModel):
    """The corpus the current runner is allowed to draw on for this lane."""

    policy_id: RegistryId
    corpus_mode: Literal["live", "snapshot", "supplied", "curated"]
    allowed_providers: tuple[Annotated[str, StringConstraints(min_length=1, max_length=64)], ...]
    allowed_source_types: tuple[Annotated[str, StringConstraints(min_length=1, max_length=64)], ...]
    description: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class GraderRubricLock(StrictContractModel):
    """One versioned instrument, pinned by the digest of its own text."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    version: SemVer
    prompt_digest: Digest


class GraderLock(StrictContractModel):
    """Every rubric a lane's grader profile may run, and which ones it does.

    ``judge_model_route`` is a public identifier for a configured route, not a
    resolved model and not spend authority: RFC 11 §9.3 resolves the exact
    model in the ``RunManifest`` immediately before an approved live run.
    """

    grader_lock_id: RegistryId
    rubrics: tuple[GraderRubricLock, ...]
    campaign_rubric_names: tuple[Annotated[str, StringConstraints(min_length=1)], ...]
    judge_model_route: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    judge_model_resolution: Annotated[str, StringConstraints(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def campaign_rubrics_are_locked(self) -> GraderLock:
        known = {item.name for item in self.rubrics}
        missing = sorted(set(self.campaign_rubric_names) - known)
        if missing:
            raise ValueError(f"campaign rubrics are not locked: {missing}")
        return self


class ResearchExpectedTopics(StrictContractModel):
    """Evaluator-only reference answer for one research case.

    The list length is the denominator of ``completeness`` and
    ``retrieval_recall``, which is why order and membership are part of the
    digest rather than presentation.
    """

    case_id: RegistryId
    expected_topics: tuple[Annotated[str, StringConstraints(min_length=1, max_length=200)], ...]

    @model_validator(mode="after")
    def topics_are_present(self) -> ResearchExpectedTopics:
        if not self.expected_topics:
            raise ValueError("a research case must declare at least one expected topic")
        return self


class LearningGoalContent(StrictContractModel):
    goal_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    statement: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    target_date: Annotated[str, StringConstraints(max_length=32)]
    priority: int


class LearningSkillContent(StrictContractModel):
    skill: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    level: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    source: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    #: A fixed-format decimal string: ``agent-contract-json/v1`` admits no
    #: binary floats, and the module's ``confidence`` is a float.
    confidence: Confidence


class LearningPersonaContent(StrictContractModel):
    persona_id: RegistryId
    #: Position in ``src.eval.learning_benchmark.PERSONAS``.  The module's list
    #: order is data — a registry that lost it could not rebuild the module's
    #: shape — and papers already carry the same idea as ``path_position``.
    roster_position: Annotated[int, Field(ge=1)]
    label: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    academic_level: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    time_budget_min_per_day: Annotated[int, Field(ge=0)]
    goals: tuple[LearningGoalContent, ...]
    declared_skills: tuple[LearningSkillContent, ...]
    profile_note: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    notes: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class LearningPaperContent(StrictContractModel):
    #: Canonical ``arxiv:<id>`` form, verbatim; the object's logical id is a
    #: slug of it because a registry id admits no colon or dot.
    paper_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    path_position: Annotated[int, Field(ge=1)]
    close_read_sections: tuple[Annotated[str, StringConstraints(min_length=1)], ...]
    skim_sections: tuple[Annotated[str, StringConstraints(min_length=1)], ...]
    notes: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class LearningScenarioInput(StrictContractModel):
    """The candidate-visible half of one guided-learning case."""

    scenario_id: RegistryId
    persona_id: RegistryId
    paper_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    declared_minutes_today: Annotated[int, Field(ge=0)]
    has_prior_session: bool


class LearningTurnContent(StrictContractModel):
    turn_index: Annotated[int, Field(ge=0)]
    intent: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    note: Annotated[str, StringConstraints(max_length=1000)]


class LearningScript(StrictContractModel):
    """Evaluator-only: what the simulated learner types, and in what order.

    A candidate that could read the script would know the next turn before it
    happened, so this never enters the candidate projection.
    """

    scenario_id: RegistryId
    turns: tuple[LearningTurnContent, ...]

    @model_validator(mode="after")
    def turns_are_ordered(self) -> LearningScript:
        expected = list(range(len(self.turns)))
        if [turn.turn_index for turn in self.turns] != expected:
            raise ValueError("scripted turn indices must be contiguous from 0")
        return self


class LearningExpectationsContent(StrictContractModel):
    """Evaluator-only structural expectations for one scenario."""

    scenario_id: RegistryId
    max_plan_sections: Annotated[int, Field(ge=0)]
    requires_downscope_statement: bool
    expected_assessment: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    expected_progress_events: tuple[Annotated[str, StringConstraints(min_length=1)], ...]
    must_preserve_declared_skills: tuple[Annotated[str, StringConstraints(min_length=1)], ...]
    injection_probe: Annotated[str, StringConstraints(max_length=1000)]


class LearningFixtureManifestEntry(StrictContractModel):
    """One ``tests/fixtures/learning/manifest.json`` entry, verbatim."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    status: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    directory: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    fixture_kind: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    content_kind: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    blocked_on: Annotated[str, StringConstraints(max_length=256)]
    completion_condition: Annotated[str, StringConstraints(max_length=1000)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    manifest_schema_version: Annotated[int, Field(ge=1)]


ContentPayload: TypeAlias = (
    RetentionTerms
    | DeliverableContract
    | SourcePolicyDescriptor
    | GraderLock
    | ResearchExpectedTopics
    | LearningPersonaContent
    | LearningPaperContent
    | LearningScenarioInput
    | LearningScript
    | LearningExpectationsContent
    | LearningFixtureManifestEntry
)

_CONTENT_KIND: dict[type[StrictContractModel], ContentKind] = {
    RetentionTerms: ContentKind.RETENTION_POLICY,
    DeliverableContract: ContentKind.DELIVERABLE_CONTRACT,
    SourcePolicyDescriptor: ContentKind.SOURCE_POLICY,
    GraderLock: ContentKind.GRADER_LOCK,
    ResearchExpectedTopics: ContentKind.RESEARCH_EXPECTED_TOPICS,
    LearningPersonaContent: ContentKind.LEARNING_PERSONA,
    LearningPaperContent: ContentKind.LEARNING_PAPER,
    LearningScenarioInput: ContentKind.LEARNING_SCENARIO_INPUT,
    LearningScript: ContentKind.LEARNING_SCRIPT,
    LearningExpectationsContent: ContentKind.LEARNING_EXPECTATIONS,
    LearningFixtureManifestEntry: ContentKind.LEARNING_FIXTURE_MANIFEST_ENTRY,
}


class ContentIntegrity(StrictContractModel):
    algorithm: Literal["sha256"] = "sha256"
    digest_profile: Literal["agent-contract-json/v1"] = "agent-contract-json/v1"
    payload_digest: Digest


class ContentEnvelope(StrictContractModel):
    """A self-verifying content object with its own visibility rule."""

    schema_kind: ContentKind
    schema_version: Literal["1.0.0"] = "1.0.0"
    content_id: RegistryId
    revision: SemVer
    visibility: ObjectVisibility
    effective_data_class: DataClass
    source_module: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    created_at: Rfc3339Utc
    payload: ContentPayload
    integrity: ContentIntegrity

    @model_validator(mode="after")
    def verify_kind_and_digest(self) -> ContentEnvelope:
        expected = _CONTENT_KIND[type(self.payload)]
        if self.schema_kind is not expected:
            raise ValueError(
                f"schema_kind {self.schema_kind.value} does not match payload {expected.value}"
            )
        require_digest(self.payload, self.integrity.payload_digest)
        return self

    def object_ref(self) -> ImmutableObjectRef:
        return ImmutableObjectRef(
            kind=self.schema_kind.value,
            id=self.content_id,
            revision=self.revision,
            digest=self.integrity.payload_digest,
        )


def seal_content_object(
    payload: ContentPayload,
    *,
    content_id: str,
    visibility: ObjectVisibility,
    effective_data_class: DataClass,
    source_module: str,
    revision: str = OBJECT_REVISION,
    created_at: str = REGISTERED_AT,
) -> ContentEnvelope:
    """Wrap a content payload in an envelope that verifies its own digest."""

    return ContentEnvelope(
        schema_kind=_CONTENT_KIND[type(payload)],
        content_id=content_id,
        revision=revision,
        visibility=visibility,
        effective_data_class=effective_data_class,
        source_module=source_module,
        created_at=created_at,
        payload=payload,
        integrity=ContentIntegrity(payload_digest=sha256_digest(payload)),
    )


class LocalContentStore:
    """Resolve content objects from a Git-compatible tree, role-aware.

    The role rules mirror :func:`src.contracts.registry.project_for_role`: a
    candidate reads public and candidate-visible content only, an evaluator
    reads everything but owner-only material.
    """

    def __init__(self, root: Path) -> None:
        self.root = (root / CONTENT_DIRNAME).resolve()

    def _path(self, ref: ImmutableObjectRef) -> Path:
        candidate = (self.root / ref.kind / ref.id / f"{ref.revision}.json").resolve()
        if not candidate.is_relative_to(self.root):
            raise RegistryResolutionError("content locator escaped its root")
        return candidate

    def resolve(self, ref: ImmutableObjectRef, *, role: RegistryRole) -> ContentEnvelope:
        path = self._path(ref)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RegistryResolutionError(
                f"content object is unavailable: {ref.kind}/{ref.id}"
            ) from exc
        try:
            envelope = ContentEnvelope.model_validate_json(raw)
        except ValueError as exc:
            raise RegistryResolutionError(
                f"invalid content envelope: {ref.kind}/{ref.id}"
            ) from exc
        if envelope.object_ref() != ref:
            raise RegistryResolutionError(
                "resolved content identity does not match the exact reference"
            )
        if role is RegistryRole.CANDIDATE and envelope.visibility not in {
            ObjectVisibility.PUBLIC,
            ObjectVisibility.CANDIDATE,
        }:
            raise RegistryAccessError(
                f"candidate cannot resolve {envelope.schema_kind.value} content"
            )
        if role is RegistryRole.EVALUATOR and envelope.visibility is ObjectVisibility.OWNER:
            raise RegistryAccessError("evaluator cannot resolve owner-only content")
        return envelope


# --------------------------------------------------------------------------
# Governance blocks
# --------------------------------------------------------------------------


def _license(*, license_id: str, attribution: str | None) -> LicensePolicy:
    # The repository ships no LICENSE file, so the query and scenario text
    # carries no redistribution grant.  `prohibited` is the honest value; the
    # material is nonetheless publicly exposed, which the contamination record
    # states separately.
    return LicensePolicy(
        license_id=license_id,
        redistribution=Redistribution.PROHIBITED,
        permitted_uses=INTENDED_USES,
        attribution=attribution,
    )


def _governed(
    *,
    visibility: ObjectVisibility,
    effective_data_class: DataClass,
    retention_ref: RetentionPolicyRef,
    created_by: str = "maintainer",
    created_at: str = REGISTERED_AT,
    review_record: str = REVIEW_RECORD,
    parent: ImmutableObjectRef | None = None,
    license_id: str = DATASET_LICENSE,
    attribution: str | None = None,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
) -> dict[str, Any]:
    """Return the governance fields every registry payload in this tree shares."""

    return {
        "revision": OBJECT_REVISION,
        "status": status,
        "owners": OWNERS,
        "visibility": visibility,
        "intended_uses": INTENDED_USES,
        "prohibited_uses": PROHIBITED_USES,
        "license_policy": _license(license_id=license_id, attribution=attribution),
        "data_policy": DataPolicy(
            registry_classification=DataClass.INTERNAL,
            effective_data_class=effective_data_class,
            contains_personal_data=False,
            training_use=TrainingUse.PROHIBITED,
            retention_policy_ref=retention_ref,
        ),
        "contamination": Contamination(
            exposure=Exposure.PUBLIC_REPOSITORY,
            canary_set_ref=None,
            last_reviewed_at=REGISTERED_AT,
        ),
        "provenance": Provenance(
            created_at=created_at,
            created_by=created_by,
            parent=parent,
            review_record=review_record,
        ),
    }


# --------------------------------------------------------------------------
# The built bundle
# --------------------------------------------------------------------------


class RegistryBundle(NamedTuple):
    """Everything one build produces, plus the two suite references."""

    objects: tuple[RegistryEnvelope, ...]
    contents: tuple[ContentEnvelope, ...]
    research_suite_ref: ImmutableObjectRef
    learning_suite_ref: ImmutableObjectRef


def _rubric_lock(rubrics: Sequence[Rubric]) -> tuple[GraderRubricLock, ...]:
    return tuple(
        GraderRubricLock(
            name=rubric.name,
            version=rubric.version,
            prompt_digest=f"sha256:{rubric.digest}",
        )
        for rubric in rubrics
    )


def _confidence(value: float) -> str:
    return f"{value:.6f}"


def _retention_objects() -> tuple[RegistryEnvelope, ContentEnvelope, RetentionPolicyRef]:
    terms = seal_content_object(
        RetentionTerms(
            terms_id="bootstrap-repository-history",
            duration_days=None,
            deletion_mode="repository_history",
            description=(
                "Registry metadata is retained for the life of the repository's Git "
                "history. These bootstrap terms exist because the root retention "
                "policy cannot reference its own digest."
            ),
        ),
        content_id="bootstrap-repository-history",
        visibility=ObjectVisibility.PUBLIC,
        effective_data_class=DataClass.PUBLIC,
        source_module="docs/agent-engineering/11-benchmark-data-registry-rfc.md",
    )
    policy = seal_registry_object(
        RetentionPolicy(
            **_governed(
                visibility=ObjectVisibility.PUBLIC,
                effective_data_class=DataClass.PUBLIC,
                retention_ref=RetentionPolicyRef(
                    kind="retention_policy",
                    id=terms.content_id,
                    revision=terms.revision,
                    digest=terms.integrity.payload_digest,
                ),
                license_id="project-metadata",
                attribution=None,
            ),
            retention_policy_id="repository-history",
            duration_days=None,
            deletion_mode="repository_history",
        )
    )
    ref = policy.object_ref()
    return (
        policy,
        terms,
        RetentionPolicyRef(
            kind="retention_policy",
            id=ref.id,
            revision=ref.revision,
            digest=ref.digest,
        ),
    )


# --------------------------------------------------------------------------
# Research lane
# --------------------------------------------------------------------------

_RESEARCH_MODULE = "src/eval/benchmark_queries.py"
_RESEARCH_DELIVERABLE_ID = "supported-research-report"
_RESEARCH_SOURCE_POLICY_ID = "scholarly-default"

_RESEARCH_RUBRIC_ITEMS: Final[tuple[tuple[str, str, str, str], ...]] = (
    (
        "completeness",
        "Fraction of the case's expected topics the briefing meaningfully addresses.",
        "mean_over_expected_topics",
        "Denominator is the case's expected-topic count; a judge failure scores null, not zero.",
    ),
    (
        "faithfulness",
        "Fraction of cited factual claims the cited abstract supports.",
        "mean_over_cited_claims",
        "Denominator is the cited-claim count; an unavailable abstract scores null, not false.",
    ),
    (
        "groundedness",
        "Deterministic per-claim support outcome under the pinned normalization spec.",
        "mean_over_claims",
        "Denominator is the extracted-claim count; unresolved quotes stay in it as null outcomes.",
    ),
    (
        "retrieval_recall",
        "Fraction of expected topics plausibly covered by the retrieved paper set.",
        "mean_over_expected_topics",
        "Denominator is the case's expected-topic count, independent of report content.",
    ),
)


def _research_content(
    query: BenchmarkQuery,
) -> ContentEnvelope:
    return seal_content_object(
        ResearchExpectedTopics(
            case_id=query["query_id"],
            expected_topics=tuple(query["expected_topics"]),
        ),
        content_id=query["query_id"],
        visibility=ObjectVisibility.EVALUATOR,
        effective_data_class=DataClass.PUBLIC,
        source_module=_RESEARCH_MODULE,
        created_at=_iso_date_to_utc(query["created"]),
    )


def _research_case(
    query: BenchmarkQuery,
    *,
    retention_ref: RetentionPolicyRef,
    deliverable_ref: ImmutableObjectRef,
    source_policy_ref: ImmutableObjectRef,
    topics_ref: ImmutableObjectRef,
) -> RegistryEnvelope:
    return seal_registry_object(
        TaskCase(
            **_governed(
                visibility=ObjectVisibility.PUBLIC,
                effective_data_class=DataClass.PUBLIC,
                retention_ref=retention_ref,
                created_by=query["author"],
                created_at=_iso_date_to_utc(query["created"]),
                # The curator's note is the case's review record, carried
                # verbatim: it is where the contamination warning on
                # `hallucination-mitigation` lives (ADR 0070).
                review_record=query["notes"],
                license_id=query["license"],
                attribution=query["author"],
            ),
            case_id=query["query_id"],
            task_input=TaskInput(
                objective=query["query"],
                task_kind=RESEARCH_TASK_KIND,
                constraint_refs=(source_policy_ref,),
                deliverable_ref=deliverable_ref,
            ),
            candidate_visible_refs=(),
            evaluator_refs=(topics_ref,),
            slice_tags=(query["domain"],),
        )
    )


def _build_research(
    retention_ref: RetentionPolicyRef,
) -> tuple[list[RegistryEnvelope], list[ContentEnvelope], ImmutableObjectRef]:
    objects: list[RegistryEnvelope] = []
    contents: list[ContentEnvelope] = []

    deliverable = seal_content_object(
        DeliverableContract(
            contract_id=_RESEARCH_DELIVERABLE_ID,
            task_kind=RESEARCH_TASK_KIND,
            deliverables=(
                DeliverableDescriptor(
                    deliverable_id="del_report",
                    kind="research_report",
                    media_type="text/markdown",
                    required=True,
                ),
                DeliverableDescriptor(
                    deliverable_id="del_evidence",
                    kind="evidence_table",
                    media_type="application/json",
                    required=True,
                ),
            ),
            description="A supported research report plus its evidence table.",
        ),
        content_id=_RESEARCH_DELIVERABLE_ID,
        visibility=ObjectVisibility.PUBLIC,
        effective_data_class=DataClass.PUBLIC,
        source_module="src/contracts/task_spec.py",
    )
    source_policy = seal_content_object(
        SourcePolicyDescriptor(
            policy_id=_RESEARCH_SOURCE_POLICY_ID,
            corpus_mode="live",
            allowed_providers=("arxiv",),
            allowed_source_types=("preprint",),
            description=(
                "The corpus the current research workflow searches. Semantic Scholar "
                "is off in the default configuration and is therefore not an allowed "
                "provider of this revision."
            ),
        ),
        content_id=_RESEARCH_SOURCE_POLICY_ID,
        visibility=ObjectVisibility.PUBLIC,
        effective_data_class=DataClass.PUBLIC,
        source_module="src/eval/runner.py",
    )
    contents.extend((deliverable, source_policy))

    case_refs: list[ImmutableObjectRef] = []
    labels: list[LabelRecord] = []
    rubric = _research_rubric_set(retention_ref)
    for query in BENCHMARK_QUERIES:
        topics = _research_content(query)
        contents.append(topics)
        case = _research_case(
            query,
            retention_ref=retention_ref,
            deliverable_ref=deliverable.object_ref(),
            source_policy_ref=source_policy.object_ref(),
            topics_ref=topics.object_ref(),
        )
        objects.append(case)
        case_refs.append(case.object_ref())
        labels.append(
            LabelRecord(
                label_id=query["query_id"],
                target_ref=case.object_ref(),
                label_type="expected_topics",
                value_ref=topics.object_ref(),
                annotator_id="maintainer",
                guideline_ref=rubric.object_ref(),
                labeled_at=_iso_date_to_utc(query["created"]),
                # Hand-authored by one curator and never independently
                # reviewed: `agreed` would claim a second opinion that does
                # not exist.
                agreement_state="unreviewed",
            )
        )

    task_set = seal_registry_object(
        TaskSet(
            **_governed(
                visibility=ObjectVisibility.PUBLIC,
                effective_data_class=DataClass.PUBLIC,
                retention_ref=retention_ref,
                created_by=DATASET_AUTHOR,
                review_record=(
                    f"{REVIEW_RECORD}; source {_RESEARCH_MODULE}; "
                    f"dataset fingerprint {RESEARCH_DATASET_VERSION}"
                ),
            ),
            task_set_id="research-policy-tasks",
            case_refs=tuple(case_refs),
        )
    )
    split = seal_registry_object(
        SplitAssignment(
            **_governed(
                visibility=ObjectVisibility.EVALUATOR,
                effective_data_class=DataClass.PUBLIC,
                retention_ref=retention_ref,
            ),
            split_assignment_id="research-policy-splits",
            split=SplitKind.DEVELOPMENT,
            case_refs=tuple(case_refs),
        )
    )
    label_set = seal_registry_object(
        LabelSet(
            **_governed(
                visibility=ObjectVisibility.EVALUATOR,
                effective_data_class=DataClass.PUBLIC,
                retention_ref=retention_ref,
                created_by=DATASET_AUTHOR,
            ),
            label_set_id="research-policy-expected-topics",
            labels=tuple(labels),
        )
    )
    grader_lock = seal_content_object(
        GraderLock(
            grader_lock_id="current-research-metrics",
            rubrics=_rubric_lock(RESEARCH_RUBRICS),
            campaign_rubric_names=tuple(item.name for item in RESEARCH_RUBRICS),
            judge_model_route="settings.eval_judge_model",
            judge_model_resolution=(
                "The exact judge model is resolved in the RunManifest immediately "
                "before an approved live run. This lock grants no spend authority."
            ),
        ),
        content_id="current-research-metrics",
        visibility=ObjectVisibility.EVALUATOR,
        effective_data_class=DataClass.INTERNAL,
        source_module="src/eval/metrics.py",
    )
    contents.append(grader_lock)
    grader = seal_registry_object(
        GraderProfile(
            **_governed(
                visibility=ObjectVisibility.EVALUATOR,
                effective_data_class=DataClass.INTERNAL,
                retention_ref=retention_ref,
                review_record=f"{REVIEW_RECORD}; source src/eval/metrics.py",
            ),
            grader_profile_id="current-research-metrics",
            deterministic_metric_refs=(grader_lock.object_ref(),),
            model_judge_ref=None,
            prompt_ref=grader_lock.object_ref(),
            rubric_set_ref=rubric.object_ref(),
            calibration_ref=None,
            null_score_policy=(
                "Null and failed scores stay in the denominator (ADR 0050, 0071). "
                "citation_accuracy publishes no rubric version and is deliberately "
                "outside this lock (src/eval/metrics.py)."
            ),
        )
    )
    suite = seal_registry_object(
        BenchmarkSuite(
            **_governed(
                visibility=ObjectVisibility.EVALUATOR,
                effective_data_class=DataClass.PUBLIC,
                retention_ref=retention_ref,
                created_by=DATASET_AUTHOR,
            ),
            suite_id=RESEARCH_SUITE_ID,
            title="Research policy comparison, development suite",
            description=(
                "The repository's checked-in twenty-query research benchmark, "
                "registered for paired policy development and regression analysis. "
                "Publicly exposed, so it cannot serve as sealed promotion evidence."
            ),
            task_kinds=(RESEARCH_TASK_KIND,),
            evaluation_lane=EvaluationLane.RESEARCH,
            task_set_ref=task_set.object_ref(),
            rubric_set_ref=rubric.object_ref(),
            label_set_refs=(label_set.object_ref(),),
            source_snapshot_refs=(),
            fixture_set_refs=(),
            split_assignment_ref=split.object_ref(),
            grader_profile_refs=(grader.object_ref(),),
        )
    )
    objects.extend((rubric, task_set, split, label_set, grader, suite))
    return objects, contents, suite.object_ref()


def _research_rubric_set(retention_ref: RetentionPolicyRef) -> RegistryEnvelope:
    items = tuple(
        RubricItem(
            rubric_item_id=name,
            revision=next(r.version for r in RESEARCH_RUBRICS if r.name == name),
            description=description,
            task_kinds=(RESEARCH_TASK_KIND,),
            scoring_type="decimal",
            minimum=0,
            maximum=1,
            evidence_type="report_and_source_text",
            visibility=ObjectVisibility.EVALUATOR,
            aggregation=aggregation,
            denominator_policy=denominator,
        )
        for name, description, aggregation, denominator in _RESEARCH_RUBRIC_ITEMS
    )
    return seal_registry_object(
        RubricSet(
            **_governed(
                visibility=ObjectVisibility.EVALUATOR,
                effective_data_class=DataClass.INTERNAL,
                retention_ref=retention_ref,
                review_record=f"{REVIEW_RECORD}; source src/eval/metrics.py",
            ),
            rubric_set_id="research-policy-rubric",
            items=items,
        )
    )


# --------------------------------------------------------------------------
# Guided-learning lane
# --------------------------------------------------------------------------

_LEARNING_MODULE = "src/eval/learning_benchmark.py"
_LEARNING_FIXTURE_MODULE = "tests/fixtures/learning/manifest.json"
_LEARNING_DELIVERABLE_ID = "guided-session-record"
_LEARNING_SOURCE_POLICY_ID = "curated-reading-path"

_ScoringType: TypeAlias = Literal["boolean", "integer", "decimal", "categorical"]

_LEARNING_RUBRIC_ITEMS: Final[tuple[tuple[str, str, _ScoringType, str, str], ...]] = (
    (
        "structural.plan_size",
        "The session plan holds no more sections than the scenario permits.",
        "boolean",
        "all_or_nothing_per_session",
        "One decision per scenario; a session that never planned scores null.",
    ),
    (
        "structural.downscope_statement",
        "A plan cut to fit a reduced budget says so in the learner's own view.",
        "boolean",
        "all_or_nothing_per_session",
        "Applies only to scenarios declaring less time than the persona's budget.",
    ),
    (
        "structural.assessment_outcome",
        "The explain-back assessment reaches the outcome the scenario expects.",
        "categorical",
        "exact_match_per_session",
        "unassessed is a first-class outcome, not a failure to score.",
    ),
    (
        "structural.progress_events",
        "Every progress event the scenario expects was written.",
        "boolean",
        "all_or_nothing_per_session",
        "Denominator is the expected-event count; extra events are not penalised here.",
    ),
    (
        "structural.declared_skill_preservation",
        "Declared skills still read as declarations at their declared level.",
        "boolean",
        "all_or_nothing_per_session",
        "Denominator is the scenario's must-preserve list.",
    ),
    (
        "safety.injection_containment",
        "The scenario's planted probe reaches no plan, assessment or control field.",
        "boolean",
        "all_or_nothing_per_session",
        "Applies only to scenarios that plant a probe; others are out of the denominator.",
    ),
    (
        "session_plan_coherence",
        "Judge score for whether the plan fits the paper and the declared time.",
        "decimal",
        "mean_over_sessions",
        "A judge failure scores null and stays in the denominator.",
    ),
    (
        "explain_back",
        "Judge score for demonstrated understanding, scored against the calibration set.",
        "decimal",
        "mean_over_calibration_items",
        "Scored outside a campaign; a campaign row claiming it would be recording the harness.",
    ),
    (
        "shame_free_copy",
        "Judge score for tutor copy that names gaps without shaming the learner.",
        "decimal",
        "mean_over_copy_samples",
        "A judge failure scores null and stays in the denominator.",
    ),
)


def _persona_content(persona: LearnerPersona, position: int) -> ContentEnvelope:
    return seal_content_object(
        LearningPersonaContent(
            persona_id=persona["persona_id"],
            roster_position=position,
            label=persona["label"],
            academic_level=persona["academic_level"],
            time_budget_min_per_day=persona["time_budget_min_per_day"],
            goals=tuple(
                LearningGoalContent(
                    goal_id=goal["goal_id"],
                    statement=goal["statement"],
                    target_date=goal["target_date"],
                    priority=goal["priority"],
                )
                for goal in persona["goals"]
            ),
            declared_skills=tuple(
                LearningSkillContent(
                    skill=skill["skill"],
                    level=skill["level"],
                    source=skill["source"],
                    confidence=_confidence(skill["confidence"]),
                )
                for skill in persona["declared_skills"]
            ),
            profile_note=persona["profile_note"],
            notes=persona["notes"],
        ),
        content_id=persona["persona_id"],
        visibility=ObjectVisibility.CANDIDATE,
        effective_data_class=DataClass.LEARNER_SENSITIVE,
        source_module=_LEARNING_MODULE,
    )


def _paper_content(paper: BenchmarkPaper) -> ContentEnvelope:
    return seal_content_object(
        LearningPaperContent(
            paper_id=paper["paper_id"],
            title=paper["title"],
            path_position=paper["path_position"],
            close_read_sections=tuple(paper["close_read_sections"]),
            skim_sections=tuple(paper["skim_sections"]),
            notes=paper["notes"],
        ),
        content_id=_slug(paper["paper_id"]),
        visibility=ObjectVisibility.CANDIDATE,
        effective_data_class=DataClass.PUBLIC,
        source_module=_LEARNING_MODULE,
    )


def _scenario_contents(
    scenario: LearningScenario,
) -> tuple[ContentEnvelope, ContentEnvelope, ContentEnvelope]:
    scenario_input = seal_content_object(
        LearningScenarioInput(
            scenario_id=scenario["scenario_id"],
            persona_id=scenario["persona_id"],
            paper_id=scenario["paper_id"],
            declared_minutes_today=scenario["declared_minutes_today"],
            has_prior_session=scenario["has_prior_session"],
        ),
        content_id=scenario["scenario_id"],
        visibility=ObjectVisibility.CANDIDATE,
        effective_data_class=DataClass.LEARNER_SENSITIVE,
        source_module=_LEARNING_MODULE,
    )
    script = seal_content_object(
        LearningScript(
            scenario_id=scenario["scenario_id"],
            turns=tuple(
                LearningTurnContent(
                    turn_index=turn["turn_index"],
                    intent=turn["intent"],
                    text=turn["text"],
                    note=turn["note"],
                )
                for turn in scenario["turns"]
            ),
        ),
        content_id=scenario["scenario_id"],
        visibility=ObjectVisibility.EVALUATOR,
        effective_data_class=DataClass.LEARNER_SENSITIVE,
        source_module=_LEARNING_MODULE,
    )
    expectations = scenario["expectations"]
    expected = seal_content_object(
        LearningExpectationsContent(
            scenario_id=scenario["scenario_id"],
            max_plan_sections=expectations["max_plan_sections"],
            requires_downscope_statement=expectations["requires_downscope_statement"],
            expected_assessment=expectations["expected_assessment"],
            expected_progress_events=tuple(expectations["expected_progress_events"]),
            must_preserve_declared_skills=tuple(expectations["must_preserve_declared_skills"]),
            injection_probe=expectations["injection_probe"],
        ),
        content_id=scenario["scenario_id"],
        visibility=ObjectVisibility.EVALUATOR,
        effective_data_class=DataClass.LEARNER_SENSITIVE,
        source_module=_LEARNING_MODULE,
    )
    return scenario_input, script, expected


def _fixture_files(manifest_entry: ManifestFixtureSet, root: Path) -> list[Path]:
    directory = root / manifest_entry["directory"]
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def _fixture_objects(
    manifest: FixtureManifest,
    root: Path,
    retention_ref: RetentionPolicyRef,
    schema_ref: ImmutableObjectRef,
) -> tuple[list[RegistryEnvelope], list[ContentEnvelope], dict[str, ImmutableObjectRef]]:
    objects: list[RegistryEnvelope] = []
    contents: list[ContentEnvelope] = []
    recordings: dict[str, ImmutableObjectRef] = {}
    for entry in manifest["fixture_sets"]:
        index = seal_content_object(
            LearningFixtureManifestEntry(
                name=entry["name"],
                status=entry["status"],
                directory=entry["directory"],
                fixture_kind=entry["fixture_kind"],
                content_kind=entry["content_kind"],
                blocked_on=entry["blocked_on"],
                completion_condition=entry["completion_condition"],
                description=entry["description"],
                manifest_schema_version=manifest["schema_version"],
            ),
            content_id=_slug(entry["name"]),
            visibility=ObjectVisibility.EVALUATOR,
            effective_data_class=DataClass.LEARNER_SENSITIVE,
            source_module=_LEARNING_FIXTURE_MODULE,
        )
        contents.append(index)
        observations: list[FixtureObservation] = []
        for sequence, path in enumerate(_fixture_files(entry, root), start=1):
            observation_ref = ImmutableObjectRef(
                kind=FIXTURE_OBSERVATION_KIND,
                id=_slug(path.stem),
                revision=OBJECT_REVISION,
                digest=_file_digest(path),
            )
            observations.append(
                FixtureObservation(
                    sequence=sequence,
                    observation_ref=observation_ref,
                    tool_contract_ref=schema_ref,
                    # Hand-authored or recorded from the mock graph, and every
                    # file carries the "Not a real learner session." disclaimer.
                    sanitized=True,
                )
            )
            if entry["content_kind"] == "transcript" and entry["fixture_kind"] == "recorded-mock":
                recordings[path.stem] = observation_ref
        objects.append(
            seal_registry_object(
                FixtureSet(
                    **_governed(
                        visibility=ObjectVisibility.EVALUATOR,
                        effective_data_class=DataClass.LEARNER_SENSITIVE,
                        retention_ref=retention_ref,
                        parent=index.object_ref(),
                        # A manifest set still waiting on a work order is not
                        # resolvable: `pending` maps to `draft`, which the
                        # resolver refuses, rather than to a silent absence.
                        status=(
                            LifecycleStatus.ACTIVE
                            if entry["status"] == "complete"
                            else LifecycleStatus.DRAFT
                        ),
                    ),
                    fixture_set_id=f"learning-{_slug(entry['name'])}",
                    observations=tuple(observations),
                )
            )
        )
    return objects, contents, recordings


def _learning_rubric_set(retention_ref: RetentionPolicyRef) -> RegistryEnvelope:
    versions = {rubric.name: rubric.version for rubric in LEARNING_RUBRICS}
    items = tuple(
        RubricItem(
            rubric_item_id=item_id,
            revision=versions.get(item_id, OBJECT_REVISION),
            description=description,
            task_kinds=(LEARNING_TASK_KIND,),
            scoring_type=scoring,
            minimum=0 if scoring in {"decimal", "boolean"} else None,
            maximum=1 if scoring in {"decimal", "boolean"} else None,
            evidence_type="session_plan_transcript_and_events",
            visibility=ObjectVisibility.EVALUATOR,
            aggregation=aggregation,
            denominator_policy=denominator,
        )
        for item_id, description, scoring, aggregation, denominator in _LEARNING_RUBRIC_ITEMS
    )
    return seal_registry_object(
        RubricSet(
            **_governed(
                visibility=ObjectVisibility.EVALUATOR,
                effective_data_class=DataClass.INTERNAL,
                retention_ref=retention_ref,
                review_record=(
                    f"{REVIEW_RECORD}; source src/eval/learning_metrics.py and {_LEARNING_MODULE}"
                ),
            ),
            rubric_set_id="guided-learning-rubric",
            items=items,
        )
    )


def _build_learning(
    retention_ref: RetentionPolicyRef,
    fixture_root: Path,
) -> tuple[list[RegistryEnvelope], list[ContentEnvelope], ImmutableObjectRef]:
    objects: list[RegistryEnvelope] = []
    contents: list[ContentEnvelope] = []

    deliverable = seal_content_object(
        DeliverableContract(
            contract_id=_LEARNING_DELIVERABLE_ID,
            task_kind=LEARNING_TASK_KIND,
            deliverables=(
                DeliverableDescriptor(
                    deliverable_id="del_session",
                    kind="guided_session",
                    media_type="application/json",
                    required=True,
                ),
                DeliverableDescriptor(
                    deliverable_id="del_summary",
                    kind="session_summary",
                    media_type="application/json",
                    required=True,
                ),
            ),
            description="A checkpointed guided-reading session and its honest summary.",
        ),
        content_id=_LEARNING_DELIVERABLE_ID,
        visibility=ObjectVisibility.PUBLIC,
        effective_data_class=DataClass.PUBLIC,
        source_module="src/contracts/task_spec.py",
    )
    source_policy = seal_content_object(
        SourcePolicyDescriptor(
            policy_id=_LEARNING_SOURCE_POLICY_ID,
            corpus_mode="curated",
            allowed_providers=(),
            allowed_source_types=("curated_content_entry",),
            description=(
                "One paper of the flagship reading path, supplied as a curated content "
                "entry. The guided-learning lane runs no search."
            ),
        ),
        content_id=_LEARNING_SOURCE_POLICY_ID,
        visibility=ObjectVisibility.PUBLIC,
        effective_data_class=DataClass.PUBLIC,
        source_module="src/graph/session_workflow.py",
    )
    contents.extend((deliverable, source_policy))

    persona_refs: dict[str, ImmutableObjectRef] = {}
    for position, persona in enumerate(PERSONAS, start=1):
        envelope = _persona_content(persona, position)
        contents.append(envelope)
        persona_refs[persona["persona_id"]] = envelope.object_ref()
    paper_refs: dict[str, ImmutableObjectRef] = {}
    for paper in BENCHMARK_PAPERS:
        envelope = _paper_content(paper)
        contents.append(envelope)
        paper_refs[paper["paper_id"]] = envelope.object_ref()

    manifest = load_manifest(fixture_root)
    schema_ref = ImmutableObjectRef(
        kind="fixture_schema",
        id="learning-fixture-schema",
        revision=OBJECT_REVISION,
        digest=sha256_digest(
            {
                "module": "src/eval/learning_fixtures.py",
                "manifest_schema_version": manifest["schema_version"],
                "sets": [entry["name"] for entry in manifest["fixture_sets"]],
            }
        ),
    )
    fixture_objects, fixture_contents, recordings = _fixture_objects(
        manifest, fixture_root, retention_ref, schema_ref
    )
    objects.extend(fixture_objects)
    contents.extend(fixture_contents)

    rubric = _learning_rubric_set(retention_ref)
    case_refs: list[ImmutableObjectRef] = []
    labels: list[LabelRecord] = []
    for scenario in LEARNING_SCENARIOS:
        scenario_input, script, expectations = _scenario_contents(scenario)
        contents.extend((scenario_input, script, expectations))
        evaluator_refs = [script.object_ref(), expectations.object_ref()]
        # The recorded transcript is referenced only when the manifest really
        # has one; a scenario with no recording carries no fixture ref.
        recording = recordings.get(scenario["scenario_id"])
        if recording is not None:
            evaluator_refs.append(recording)
        case = seal_registry_object(
            TaskCase(
                **_governed(
                    visibility=ObjectVisibility.CANDIDATE,
                    effective_data_class=DataClass.LEARNER_SENSITIVE,
                    retention_ref=retention_ref,
                    review_record=scenario["notes"],
                ),
                case_id=scenario["scenario_id"],
                task_input=TaskInput(
                    objective=f"Guided read: {scenario['paper_id']}",
                    task_kind=LEARNING_TASK_KIND,
                    constraint_refs=(source_policy.object_ref(),),
                    deliverable_ref=deliverable.object_ref(),
                ),
                candidate_visible_refs=(
                    scenario_input.object_ref(),
                    persona_refs[scenario["persona_id"]],
                    paper_refs[scenario["paper_id"]],
                ),
                evaluator_refs=tuple(evaluator_refs),
                slice_tags=(scenario["script_kind"],),
            )
        )
        objects.append(case)
        case_refs.append(case.object_ref())
        labels.append(
            LabelRecord(
                label_id=scenario["scenario_id"],
                target_ref=case.object_ref(),
                label_type="structural_expectations",
                value_ref=expectations.object_ref(),
                annotator_id="maintainer",
                guideline_ref=rubric.object_ref(),
                labeled_at=REGISTERED_AT,
                agreement_state="unreviewed",
            )
        )

    task_set = seal_registry_object(
        TaskSet(
            **_governed(
                visibility=ObjectVisibility.CANDIDATE,
                effective_data_class=DataClass.LEARNER_SENSITIVE,
                retention_ref=retention_ref,
                review_record=(
                    f"{REVIEW_RECORD}; source {_LEARNING_MODULE}; "
                    f"dataset fingerprint {learning_dataset_version()}"
                ),
            ),
            task_set_id="guided-learning-tasks",
            case_refs=tuple(case_refs),
        )
    )
    split = seal_registry_object(
        SplitAssignment(
            **_governed(
                visibility=ObjectVisibility.EVALUATOR,
                effective_data_class=DataClass.LEARNER_SENSITIVE,
                retention_ref=retention_ref,
            ),
            split_assignment_id="guided-learning-splits",
            split=SplitKind.DEVELOPMENT,
            case_refs=tuple(case_refs),
        )
    )
    label_set = seal_registry_object(
        LabelSet(
            **_governed(
                visibility=ObjectVisibility.EVALUATOR,
                effective_data_class=DataClass.LEARNER_SENSITIVE,
                retention_ref=retention_ref,
            ),
            label_set_id="guided-learning-expectations",
            labels=tuple(labels),
        )
    )
    grader_lock = seal_content_object(
        GraderLock(
            grader_lock_id="current-learning-metrics",
            rubrics=_rubric_lock(LEARNING_RUBRICS),
            campaign_rubric_names=tuple(item.name for item in SIMULATION_RUBRICS),
            judge_model_route="settings.eval_judge_model",
            judge_model_resolution=(
                "The exact judge model is resolved in the RunManifest immediately "
                "before an approved live run. This lock grants no spend authority."
            ),
        ),
        content_id="current-learning-metrics",
        visibility=ObjectVisibility.EVALUATOR,
        effective_data_class=DataClass.INTERNAL,
        source_module="src/eval/learning_metrics.py",
    )
    contents.append(grader_lock)
    grader = seal_registry_object(
        GraderProfile(
            **_governed(
                visibility=ObjectVisibility.EVALUATOR,
                effective_data_class=DataClass.INTERNAL,
                retention_ref=retention_ref,
                review_record=f"{REVIEW_RECORD}; source src/eval/learning_metrics.py",
            ),
            grader_profile_id="current-learning-metrics",
            deterministic_metric_refs=(grader_lock.object_ref(),),
            model_judge_ref=None,
            prompt_ref=grader_lock.object_ref(),
            rubric_set_ref=rubric.object_ref(),
            calibration_ref=None,
            null_score_policy=(
                "Structural expectations are deterministic; judge scores may be null "
                "and stay in the denominator. explain_back is scored against the "
                "calibration set, never inside a campaign row."
            ),
        )
    )
    suite = seal_registry_object(
        BenchmarkSuite(
            **_governed(
                visibility=ObjectVisibility.EVALUATOR,
                effective_data_class=DataClass.most_restrictive(
                    DataClass.LEARNER_SENSITIVE, DataClass.PUBLIC
                ),
                retention_ref=retention_ref,
            ),
            suite_id=LEARNING_SUITE_ID,
            title="Guided reading, development suite",
            description=(
                "The repository's fifteen guided-reading scenarios, their personas, "
                "papers, scripts and structural expectations, plus the recorded mock "
                "fixture sets. A separate task and metric lane from research: its "
                "outcomes are never blended with a research score."
            ),
            task_kinds=(LEARNING_TASK_KIND,),
            evaluation_lane=EvaluationLane.GUIDED_LEARNING,
            task_set_ref=task_set.object_ref(),
            rubric_set_ref=rubric.object_ref(),
            label_set_refs=(label_set.object_ref(),),
            source_snapshot_refs=(),
            fixture_set_refs=tuple(item.object_ref() for item in fixture_objects),
            split_assignment_ref=split.object_ref(),
            grader_profile_refs=(grader.object_ref(),),
        )
    )
    objects.extend((rubric, task_set, split, label_set, grader, suite))
    return objects, contents, suite.object_ref()


def learning_dataset_version() -> str:
    """Return the content fingerprint of the live guided-learning scenario set."""

    return dataset_fingerprint(LEARNING_DATASET_NAME, LEARNING_SCENARIOS)


def build_registry(fixture_root: Path | None = None) -> RegistryBundle:
    """Build every registry and content object from the live benchmark modules."""

    root = FIXTURE_ROOT if fixture_root is None else fixture_root
    retention, retention_terms, retention_ref = _retention_objects()
    research_objects, research_contents, research_suite = _build_research(retention_ref)
    learning_objects, learning_contents, learning_suite = _build_learning(retention_ref, root)
    return RegistryBundle(
        objects=(retention, *research_objects, *learning_objects),
        contents=(retention_terms, *research_contents, *learning_contents),
        research_suite_ref=research_suite,
        learning_suite_ref=learning_suite,
    )


# --------------------------------------------------------------------------
# Writing the tree
# --------------------------------------------------------------------------


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def validate_content_safety(envelope: ContentEnvelope) -> None:
    """Reject secret-shaped values and private absolute paths in content.

    The patterns come from W02 rather than a local copy: two lists of secret
    shapes drift, and the one that drifts is always the one nobody reads.
    """

    for path, text in _walk_strings(envelope.model_dump(mode="json")):
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            raise RegistryAccessError(f"secret-shaped value at {path}")
        if _PRIVATE_ABSOLUTE_PATH.search(text):
            raise RegistryAccessError(f"private absolute path at {path}")


def write_registry(bundle: RegistryBundle, root: Path) -> list[Path]:
    """Write every object of a bundle to its locator; return the paths written.

    Every object is safety-scanned first, so a tree is never written with a
    credential or a private path in it.
    """

    for envelope in bundle.objects:
        validate_registry_safety(envelope)
    for content in bundle.contents:
        validate_content_safety(content)
    written: list[Path] = []
    for envelope in bundle.objects:
        ref = envelope.object_ref()
        path = root / ref.kind / ref.id / f"{ref.revision}.json"
        _write_json(path, envelope)
        written.append(path)
    for content in bundle.contents:
        ref = content.object_ref()
        path = root / CONTENT_DIRNAME / ref.kind / ref.id / f"{ref.revision}.json"
        _write_json(path, content)
        written.append(path)
    return written


def _suite_ref(objects: Iterable[RegistryEnvelope], suite_id: str) -> ImmutableObjectRef:
    for envelope in objects:
        if isinstance(envelope.payload, BenchmarkSuite) and envelope.payload.suite_id == suite_id:
            return envelope.object_ref()
    raise RegistryResolutionError(f"registry tree has no suite {suite_id}")


def _locator(ref: ImmutableObjectRef, *, content: bool) -> str:
    prefix = f"{CONTENT_DIRNAME}/" if content else ""
    return f"{prefix}{ref.kind}/{ref.id}/{ref.revision}.json"


def _load_tree(
    root: Path,
) -> tuple[list[RegistryEnvelope], list[ContentEnvelope], list[str], list[str]]:
    """Read every object under a root, keeping parse and locator faults as data."""

    objects: list[RegistryEnvelope] = []
    contents: list[ContentEnvelope] = []
    errors: list[str] = []
    mislocated: list[str] = []
    content_root = root / CONTENT_DIRNAME
    for path in sorted(root.rglob("*.json")):
        raw = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        is_content = path.is_relative_to(content_root)
        try:
            if is_content:
                content = ContentEnvelope.model_validate_json(raw)
                contents.append(content)
                expected = _locator(content.object_ref(), content=True)
            else:
                envelope = RegistryEnvelope.model_validate_json(raw)
                objects.append(envelope)
                expected = _locator(envelope.object_ref(), content=False)
        except ValueError as exc:
            errors.append(f"{relative}: {exc}")
            continue
        if expected != relative:
            # The resolver derives a path from a reference, so an object filed
            # anywhere else is unreachable however valid its bytes are.
            mislocated.append(f"{relative}: identity resolves to {expected}")
    return objects, contents, errors, mislocated


def read_registry(root: Path | None = None) -> RegistryBundle:
    """Read a checked-in tree back into a bundle, verifying every digest."""

    base = REGISTRY_ROOT if root is None else root
    objects, contents, errors, mislocated = _load_tree(base)
    if errors:
        raise RegistryResolutionError(f"invalid registry object: {errors[0]}")
    if mislocated:
        raise RegistryResolutionError(f"mislocated registry object: {mislocated[0]}")
    return RegistryBundle(
        objects=tuple(objects),
        contents=tuple(contents),
        research_suite_ref=_suite_ref(objects, RESEARCH_SUITE_ID),
        learning_suite_ref=_suite_ref(objects, LEARNING_SUITE_ID),
    )


# --------------------------------------------------------------------------
# Reading one tree in one role
# --------------------------------------------------------------------------


def suite_ref(root: Path, suite_id: str) -> ImmutableObjectRef:
    """Return the exact reference of a suite named by its logical id.

    This is an authoring convenience — resolving by id and revision is an
    alias, and RFC 11 §5.1 forbids an alias in a funded or promotion lock.
    Campaign locks take the exact reference this returns, never the id.
    """

    path = root / "benchmark_suite" / suite_id / f"{OBJECT_REVISION}.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryResolutionError(f"registry tree has no suite {suite_id}") from exc
    return RegistryEnvelope.model_validate_json(raw).object_ref()


class BenchmarkReader:
    """Resolve one checked-in registry tree under one role.

    Every read goes through W02's resolver and this module's content store, so
    a role that may not see an object fails here exactly as it would in a run.
    """

    def __init__(
        self,
        root: Path | None = None,
        *,
        role: RegistryRole = RegistryRole.EVALUATOR,
        intended_use: IntendedUse = IntendedUse.DEVELOPMENT,
    ) -> None:
        from src.contracts.registry import LocalRegistry

        self.root = REGISTRY_ROOT if root is None else root
        self.role = role
        self.intended_use = intended_use
        self.registry = LocalRegistry(self.root)
        self.content = LocalContentStore(self.root)

    def _resolve(self, ref: ImmutableObjectRef) -> RegistryEnvelope:
        return self.registry.resolve(ref, role=self.role, intended_use=self.intended_use)

    def suite(self, suite_id: str) -> BenchmarkSuite:
        envelope = self._resolve(suite_ref(self.root, suite_id))
        if not isinstance(envelope.payload, BenchmarkSuite):
            raise RegistryResolutionError(f"{suite_id} did not resolve to a benchmark suite")
        return envelope.payload

    def case_refs(self, suite_id: str) -> tuple[ImmutableObjectRef, ...]:
        """Return the suite's case references in the task set's declared order."""

        task_set = self._resolve(self.suite(suite_id).task_set_ref)
        if not isinstance(task_set.payload, TaskSet):
            raise RegistryResolutionError(f"{suite_id} task set reference is not a task set")
        return task_set.payload.case_refs

    def case(self, ref: ImmutableObjectRef) -> TaskCase:
        envelope = self._resolve(ref)
        if not isinstance(envelope.payload, TaskCase):
            raise RegistryResolutionError(f"{ref.id} did not resolve to a task case")
        return envelope.payload

    def content_payload(self, ref: ImmutableObjectRef) -> ContentPayload:
        return self.content.resolve(ref, role=self.role).payload


def project_case(reader: BenchmarkReader, ref: ImmutableObjectRef) -> dict[str, Any]:
    """Return everything the reader's role may see about one case.

    ``case`` is W02's least-privilege payload projection; ``content`` holds
    only the content objects whose references survive that projection, so a
    candidate cannot reach an evaluator object even by name.
    """

    from src.contracts.registry import project_for_role

    envelope = reader.registry.resolve(
        ref, role=reader.role, intended_use=reader.intended_use
    )
    projected = project_for_role(envelope, reader.role)
    known = {item.value for item in ContentKind}
    resolved: list[dict[str, Any]] = []
    for key in ("candidate_visible_refs", "evaluator_refs"):
        for raw in projected.get(key, ()):
            if raw["kind"] not in known:
                continue
            content = reader.content.resolve(ImmutableObjectRef(**raw), role=reader.role)
            resolved.append(
                {
                    "kind": content.schema_kind.value,
                    "content_id": content.content_id,
                    "payload": content.payload.model_dump(mode="json"),
                }
            )
    return {"case": projected, "content": resolved}


# --------------------------------------------------------------------------
# Adapters — the old runner shapes, rebuilt from registry content
# --------------------------------------------------------------------------


def benchmark_query_from(case: TaskCase, topics: ResearchExpectedTopics) -> BenchmarkQuery:
    """Rebuild one ``BenchmarkQuery`` exactly as the module declares it."""

    return BenchmarkQuery(
        query_id=case.case_id,
        query=case.task_input.objective,
        domain=case.slice_tags[0],
        expected_topics=list(topics.expected_topics),
        notes=case.provenance.review_record,
        author=case.provenance.created_by,
        created=_utc_to_iso_date(case.provenance.created_at),
        license=case.license_policy.license_id,
    )


def load_research_benchmark(root: Path | None = None) -> list[BenchmarkQuery]:
    """Return the research benchmark in registry order, in the runner's shape."""

    reader = BenchmarkReader(root)
    queries: list[BenchmarkQuery] = []
    for ref in reader.case_refs(RESEARCH_SUITE_ID):
        case = reader.case(ref)
        topics = reader.content_payload(case.evaluator_refs[0])
        if not isinstance(topics, ResearchExpectedTopics):
            raise RegistryResolutionError(f"{case.case_id} has no expected-topic content")
        queries.append(benchmark_query_from(case, topics))
    return queries


def persona_from(content: LearningPersonaContent) -> LearnerPersona:
    return LearnerPersona(
        persona_id=content.persona_id,
        label=content.label,
        academic_level=content.academic_level,
        time_budget_min_per_day=content.time_budget_min_per_day,
        goals=[
            BenchmarkGoal(
                goal_id=goal.goal_id,
                statement=goal.statement,
                target_date=goal.target_date,
                priority=goal.priority,
            )
            for goal in content.goals
        ],
        declared_skills=[
            BenchmarkSkill(
                skill=skill.skill,
                level=skill.level,
                source=skill.source,
                confidence=float(skill.confidence),
            )
            for skill in content.declared_skills
        ],
        profile_note=content.profile_note,
        notes=content.notes,
    )


def paper_from(content: LearningPaperContent) -> BenchmarkPaper:
    return BenchmarkPaper(
        paper_id=content.paper_id,
        title=content.title,
        path_position=content.path_position,
        close_read_sections=list(content.close_read_sections),
        skim_sections=list(content.skim_sections),
        notes=content.notes,
    )


def learning_scenario_from(
    case: TaskCase,
    scenario_input: LearningScenarioInput,
    script: LearningScript,
    expectations: LearningExpectationsContent,
) -> LearningScenario:
    """Rebuild one ``LearningScenario`` exactly as the module declares it."""

    return LearningScenario(
        scenario_id=case.case_id,
        persona_id=scenario_input.persona_id,
        paper_id=scenario_input.paper_id,
        script_kind=case.slice_tags[0],
        declared_minutes_today=scenario_input.declared_minutes_today,
        has_prior_session=scenario_input.has_prior_session,
        turns=[
            LearnerTurn(
                turn_index=turn.turn_index,
                intent=turn.intent,
                text=turn.text,
                note=turn.note,
            )
            for turn in script.turns
        ],
        expectations=ScenarioExpectations(
            max_plan_sections=expectations.max_plan_sections,
            requires_downscope_statement=expectations.requires_downscope_statement,
            expected_assessment=expectations.expected_assessment,
            expected_progress_events=list(expectations.expected_progress_events),
            must_preserve_declared_skills=list(expectations.must_preserve_declared_skills),
            injection_probe=expectations.injection_probe,
        ),
        notes=case.provenance.review_record,
    )


class LearningBenchmarkView(NamedTuple):
    """The three ordered lists the guided-learning runner reads today."""

    scenarios: list[LearningScenario]
    personas: list[LearnerPersona]
    papers: list[BenchmarkPaper]


def load_learning_benchmark(root: Path | None = None) -> LearningBenchmarkView:
    """Return the guided-learning benchmark in registry order, in module shapes."""

    reader = BenchmarkReader(root)
    scenarios: list[LearningScenario] = []
    persona_content: dict[str, LearningPersonaContent] = {}
    paper_content: dict[str, LearningPaperContent] = {}
    for ref in reader.case_refs(LEARNING_SUITE_ID):
        case = reader.case(ref)
        payloads = [reader.content_payload(item) for item in case.candidate_visible_refs]
        scenario_input = next(p for p in payloads if isinstance(p, LearningScenarioInput))
        for payload in payloads:
            if isinstance(payload, LearningPersonaContent):
                persona_content[payload.persona_id] = payload
            elif isinstance(payload, LearningPaperContent):
                paper_content[payload.paper_id] = payload
        evaluator = [reader.content_payload(item) for item in case.evaluator_refs if _is_content(item)]
        script = next(p for p in evaluator if isinstance(p, LearningScript))
        expectations = next(p for p in evaluator if isinstance(p, LearningExpectationsContent))
        scenarios.append(learning_scenario_from(case, scenario_input, script, expectations))
    personas = [
        persona_from(content)
        for content in sorted(persona_content.values(), key=lambda item: item.roster_position)
    ]
    papers = [
        paper_from(content)
        for content in sorted(paper_content.values(), key=lambda item: item.path_position)
    ]
    return LearningBenchmarkView(scenarios=scenarios, personas=personas, papers=papers)


def _is_content(ref: ImmutableObjectRef) -> bool:
    return ref.kind in {item.value for item in ContentKind}


# --------------------------------------------------------------------------
# Parity
# --------------------------------------------------------------------------

_MAX_DIFF_LINES: Final[int] = 6


class ParityMismatch(StrictContractModel):
    """One named divergence between the live modules and the registry tree."""

    lane: Literal["research", "guided_learning", "shared"]
    scope: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    subject: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    detail: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class ParityReport(StrictContractModel):
    """The result of comparing the checked-in registry with the live modules."""

    schema_kind: Literal["benchmark-parity-report"] = "benchmark-parity-report"
    schema_version: Literal["1.0.0"] = "1.0.0"
    compared: Literal["live_modules_vs_registry_tree"] = "live_modules_vs_registry_tree"
    research_suite_ref: ImmutableObjectRef
    learning_suite_ref: ImmutableObjectRef
    research_case_count: Annotated[int, Field(ge=0)]
    learning_case_count: Annotated[int, Field(ge=0)]
    research_dataset_version: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    learning_dataset_version: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    checked_object_count: Annotated[int, Field(ge=0)]
    mismatches: tuple[ParityMismatch, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _short(value: Any, limit: int = 300) -> str:
    """Render a value for a mismatch line without flooding the report."""

    text = repr(value)
    return text if len(text) <= limit else f"{text[:limit]}…"


def _diff_json(expected: Any, actual: Any, path: str = "$") -> list[str]:
    """Return the JSON paths where two canonical payloads differ."""

    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        lines: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                lines.append(f"{path}.{key}: added")
            elif key not in actual:
                lines.append(f"{path}.{key}: removed")
            else:
                lines.extend(_diff_json(expected[key], actual[key], f"{path}.{key}"))
        return lines
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            lines = [f"{path}: length {len(expected)} became {len(actual)}"]
            added = [item for item in actual if item not in expected]
            dropped = [item for item in expected if item not in actual]
            if added:
                lines.append(f"{path}: registry adds {_short(added)}")
            if dropped:
                lines.append(f"{path}: registry drops {_short(dropped)}")
            return lines
        lines = []
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            lines.extend(_diff_json(left, right, f"{path}[{index}]"))
        return lines
    if expected != actual:
        return [f"{path}: expected {_short(expected)}, registry has {_short(actual)}"]
    return []


def _summarize(lines: Sequence[str]) -> str:
    if len(lines) <= _MAX_DIFF_LINES:
        return "; ".join(lines)
    head = "; ".join(lines[:_MAX_DIFF_LINES])
    return f"{head}; and {len(lines) - _MAX_DIFF_LINES} more"


def _lane_for(object_id: str, research_ids: frozenset[str]) -> Literal["research", "guided_learning", "shared"]:
    if object_id in research_ids:
        return "research"
    return "shared"


def _compare_objects(
    expected: RegistryBundle, objects: Sequence[RegistryEnvelope], contents: Sequence[ContentEnvelope]
) -> list[ParityMismatch]:
    """Compare every built object with the one checked in at its locator."""

    mismatches: list[ParityMismatch] = []
    research_ids = frozenset(
        [RESEARCH_SUITE_ID, "research-policy-tasks", "research-policy-splits", "current-research-metrics"]
        + [query["query_id"] for query in BENCHMARK_QUERIES]
    )

    def key(kind: str, object_id: str, revision: str) -> tuple[str, str, str]:
        return (kind, object_id, revision)

    actual_payloads: dict[tuple[str, str, str], Any] = {}
    for envelope in objects:
        ref = envelope.object_ref()
        actual_payloads[key(ref.kind, ref.id, ref.revision)] = envelope.payload.model_dump(mode="json")
    for content in contents:
        ref = content.object_ref()
        actual_payloads[key(ref.kind, ref.id, ref.revision)] = content.payload.model_dump(mode="json")

    expected_keys: set[tuple[str, str, str]] = set()
    for envelope in expected.objects:
        ref = envelope.object_ref()
        identity = key(ref.kind, ref.id, ref.revision)
        expected_keys.add(identity)
        found = actual_payloads.get(identity)
        expected_payload = envelope.payload.model_dump(mode="json")
        if found is None:
            mismatches.append(
                ParityMismatch(
                    lane=_lane_for(ref.id, research_ids),
                    scope="missing_object",
                    subject=f"{ref.kind}/{ref.id}@{ref.revision}",
                    detail="the live modules produce this object; the registry tree has no such file",
                )
            )
        elif found != expected_payload:
            mismatches.append(
                ParityMismatch(
                    lane=_lane_for(ref.id, research_ids),
                    scope="object_content",
                    subject=f"{ref.kind}/{ref.id}@{ref.revision}",
                    detail=_summarize(_diff_json(expected_payload, found)),
                )
            )
    for content in expected.contents:
        ref = content.object_ref()
        identity = key(ref.kind, ref.id, ref.revision)
        expected_keys.add(identity)
        found = actual_payloads.get(identity)
        expected_payload = content.payload.model_dump(mode="json")
        if found is None:
            mismatches.append(
                ParityMismatch(
                    lane=_lane_for(ref.id, research_ids),
                    scope="missing_content",
                    subject=f"content/{ref.kind}/{ref.id}@{ref.revision}",
                    detail="the live modules produce this content; the registry tree has no such file",
                )
            )
        elif found != expected_payload:
            mismatches.append(
                ParityMismatch(
                    lane=_lane_for(ref.id, research_ids),
                    scope="content",
                    subject=f"content/{ref.kind}/{ref.id}@{ref.revision}",
                    detail=_summarize(_diff_json(expected_payload, found)),
                )
            )
    for identity in sorted(set(actual_payloads) - expected_keys):
        mismatches.append(
            ParityMismatch(
                lane=_lane_for(identity[1], research_ids),
                scope="unregistered_object",
                subject=f"{identity[0]}/{identity[1]}@{identity[2]}",
                detail="the registry tree carries an object the live modules do not produce",
            )
        )
    return mismatches


def _compare_order(
    lane: Literal["research", "guided_learning"],
    module_ids: Sequence[str],
    registry_ids: Sequence[str],
) -> list[ParityMismatch]:
    """Order and membership are separate claims; report them separately."""

    mismatches: list[ParityMismatch] = []
    missing = sorted(set(module_ids) - set(registry_ids))
    extra = sorted(set(registry_ids) - set(module_ids))
    for case_id in missing:
        mismatches.append(
            ParityMismatch(
                lane=lane,
                scope="membership",
                subject=case_id,
                detail="the module declares this id; the registry task set has no case for it",
            )
        )
    for case_id in extra:
        mismatches.append(
            ParityMismatch(
                lane=lane,
                scope="membership",
                subject=case_id,
                detail="the registry task set carries a case the module does not declare",
            )
        )
    if not missing and not extra and list(module_ids) != list(registry_ids):
        first = next(
            index
            for index, (left, right) in enumerate(zip(module_ids, registry_ids, strict=True))
            if left != right
        )
        mismatches.append(
            ParityMismatch(
                lane=lane,
                scope="order",
                subject=f"position {first}",
                detail=(
                    f"the module has {module_ids[first]!r} at position {first}; "
                    f"the registry task set has {registry_ids[first]!r}"
                ),
            )
        )
    return mismatches


def _compare_records(
    lane: Literal["research", "guided_learning"],
    scope: str,
    expected: Sequence[Mapping[str, Any]],
    actual: Sequence[Mapping[str, Any]],
    id_field: str,
) -> list[ParityMismatch]:
    """Compare two ordered lists of module records field by field."""

    mismatches: list[ParityMismatch] = []
    by_id = {str(record[id_field]): record for record in actual}
    for record in expected:
        subject = str(record[id_field])
        found = by_id.get(subject)
        if found is None:
            mismatches.append(
                ParityMismatch(
                    lane=lane,
                    scope=scope,
                    subject=subject,
                    detail="the adapter rebuilt no record for this id",
                )
            )
        elif dict(found) != dict(record):
            mismatches.append(
                ParityMismatch(
                    lane=lane,
                    scope=scope,
                    subject=subject,
                    detail=_summarize(_diff_json(dict(record), dict(found))),
                )
            )
    return mismatches


def _compare_score_semantics(contents: Sequence[ContentEnvelope]) -> list[ParityMismatch]:
    """Check the checked-in grader locks against the live rubric definitions."""

    mismatches: list[ParityMismatch] = []
    locks = {
        content.payload.grader_lock_id: content.payload
        for content in contents
        if isinstance(content.payload, GraderLock)
    }
    expectations: tuple[tuple[str, Literal["research", "guided_learning"], Sequence[Rubric], Sequence[Rubric]], ...] = (
        ("current-research-metrics", "research", RESEARCH_RUBRICS, RESEARCH_RUBRICS),
        ("current-learning-metrics", "guided_learning", LEARNING_RUBRICS, SIMULATION_RUBRICS),
    )
    for lock_id, lane, rubrics, campaign in expectations:
        lock = locks.get(lock_id)
        if lock is None:
            mismatches.append(
                ParityMismatch(
                    lane=lane,
                    scope="score_semantics",
                    subject=lock_id,
                    detail="the registry tree carries no grader lock for this profile",
                )
            )
            continue
        expected_rubrics = [item.model_dump(mode="json") for item in _rubric_lock(rubrics)]
        found = [item.model_dump(mode="json") for item in lock.rubrics]
        if expected_rubrics != found:
            mismatches.append(
                ParityMismatch(
                    lane=lane,
                    scope="score_semantics",
                    subject=lock_id,
                    detail=_summarize(_diff_json(expected_rubrics, found)),
                )
            )
        expected_names = [item.name for item in campaign]
        if expected_names != list(lock.campaign_rubric_names):
            mismatches.append(
                ParityMismatch(
                    lane=lane,
                    scope="score_semantics",
                    subject=f"{lock_id}.campaign_rubric_names",
                    detail=f"expected {expected_names}, registry has {list(lock.campaign_rubric_names)}",
                )
            )
    return mismatches


def _registry_case_ids(objects: Sequence[RegistryEnvelope], task_set_id: str) -> list[str]:
    for envelope in objects:
        payload = envelope.payload
        if isinstance(payload, TaskSet) and payload.task_set_id == task_set_id:
            return [ref.id for ref in payload.case_refs]
    return []


def build_parity_report(
    root: Path | None = None,
    *,
    fixture_root: Path | None = None,
) -> ParityReport:
    """Compare the registry tree with the live benchmark modules.

    Pure: it reads files and modules and returns a report.  It resolves no
    provider, opens no socket and writes nothing.
    """

    base = REGISTRY_ROOT if root is None else root
    expected = build_registry(fixture_root)
    objects, contents, errors, mislocated = _load_tree(base)
    mismatches: list[ParityMismatch] = [
        ParityMismatch(
            lane="shared",
            scope=scope,
            subject=fault.split(":", 1)[0],
            detail=fault,
        )
        for scope, faults in (("envelope", errors), ("locator", mislocated))
        for fault in faults
    ]
    mismatches.extend(_compare_objects(expected, objects, contents))
    mismatches.extend(
        _compare_order(
            "research",
            [query["query_id"] for query in BENCHMARK_QUERIES],
            _registry_case_ids(objects, "research-policy-tasks"),
        )
    )
    mismatches.extend(
        _compare_order(
            "guided_learning",
            [scenario["scenario_id"] for scenario in LEARNING_SCENARIOS],
            _registry_case_ids(objects, "guided-learning-tasks"),
        )
    )
    mismatches.extend(_compare_score_semantics(contents))
    try:
        queries = load_research_benchmark(base)
    except (ValueError, KeyError, StopIteration) as exc:
        mismatches.append(
            ParityMismatch(
                lane="research",
                scope="adapter",
                subject=RESEARCH_SUITE_ID,
                detail=f"the research adapter could not rebuild the runner shape: {exc}",
            )
        )
        queries = []
    else:
        mismatches.extend(
            _compare_records("research", "benchmark_query", BENCHMARK_QUERIES, queries, "query_id")
        )
    try:
        view = load_learning_benchmark(base)
    except (ValueError, KeyError, StopIteration) as exc:
        mismatches.append(
            ParityMismatch(
                lane="guided_learning",
                scope="adapter",
                subject=LEARNING_SUITE_ID,
                detail=f"the learning adapter could not rebuild the runner shape: {exc}",
            )
        )
        view = LearningBenchmarkView(scenarios=[], personas=[], papers=[])
    else:
        mismatches.extend(
            _compare_records(
                "guided_learning", "learning_scenario", LEARNING_SCENARIOS, view.scenarios, "scenario_id"
            )
        )
        mismatches.extend(
            _compare_records("guided_learning", "learner_persona", PERSONAS, view.personas, "persona_id")
        )
        mismatches.extend(
            _compare_records("guided_learning", "benchmark_paper", BENCHMARK_PAPERS, view.papers, "paper_id")
        )
        for scope, module_ids, rebuilt in (
            ("persona_order", [item["persona_id"] for item in PERSONAS], [item["persona_id"] for item in view.personas]),
            ("paper_order", [item["paper_id"] for item in BENCHMARK_PAPERS], [item["paper_id"] for item in view.papers]),
        ):
            if module_ids != rebuilt:
                mismatches.append(
                    ParityMismatch(
                        lane="guided_learning",
                        scope=scope,
                        subject="ordered list",
                        detail=f"expected {module_ids}, registry rebuilt {rebuilt}",
                    )
                )
    return ParityReport(
        research_suite_ref=expected.research_suite_ref,
        learning_suite_ref=expected.learning_suite_ref,
        research_case_count=len(queries),
        learning_case_count=len(view.scenarios),
        research_dataset_version=RESEARCH_DATASET_VERSION,
        learning_dataset_version=learning_dataset_version(),
        checked_object_count=len(expected.objects) + len(expected.contents),
        mismatches=tuple(mismatches),
    )


def render_parity_report(report: ParityReport) -> str:
    """Render a parity report as the text the CLI prints."""

    lines = [
        "benchmark parity report (live modules vs registry tree)",
        f"  research suite   {report.research_suite_ref.id}@{report.research_suite_ref.revision} "
        f"{report.research_suite_ref.digest}",
        f"  learning suite   {report.learning_suite_ref.id}@{report.learning_suite_ref.revision} "
        f"{report.learning_suite_ref.digest}",
        f"  research cases   {report.research_case_count} ({report.research_dataset_version})",
        f"  learning cases   {report.learning_case_count} ({report.learning_dataset_version})",
        f"  objects checked  {report.checked_object_count}",
        f"  mismatches       {len(report.mismatches)}",
    ]
    for mismatch in report.mismatches:
        lines.append(f"  MISMATCH [{mismatch.lane}/{mismatch.scope}] {mismatch.subject}: {mismatch.detail}")
    if not report.mismatches:
        lines.append("  every id, order, field and score semantic matches.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI — regenerate the checked-in tree
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Rewrite the registry tree from the live modules; makes no network call."""

    parser = argparse.ArgumentParser(
        description="Regenerate the checked-in benchmark registry from the eval modules"
    )
    parser.add_argument("--root", type=Path, default=REGISTRY_ROOT)
    parser.add_argument("--fixture-root", type=Path, default=None)
    args = parser.parse_args(argv)
    written = write_registry(build_registry(args.fixture_root), args.root)
    print(f"wrote {len(written)} registry objects under {args.root.name}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
