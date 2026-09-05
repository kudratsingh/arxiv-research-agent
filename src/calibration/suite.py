"""The `judge-calibration-v1` registry suite, built from the fixtures.

W06 registered the two benchmarks this repository already evaluates. This
module registers the calibration probe: 30 synthetic task cases, an
evaluator-only label set carrying the reference decision for each, a
grader profile pinning the instrument under test, and a contamination
record saying the material is generated rather than collected.

**It lives in its own root, and that is a finding rather than a
preference.** W06's tree at ``eval_registry/`` is guarded by three tests
that make it *exactly* what ``src/contracts/benchmark_adapters.py``
builds: the file set is compared byte for byte, the task-case ids are
compared against the two benchmark modules, and the parity report calls
any other object ``unregistered_object``. Those are the right guarantees
for a migration whose whole claim is "nothing changed", and they mean a
second suite cannot be added to that root without weakening them.
``ContentEnvelope``'s ``ContentKind`` enum is closed as well, so this
suite's content kinds could not be filed under ``eval_registry/content/``
without editing W06's schema module. So the calibration suite gets
:data:`CALIBRATION_REGISTRY_ROOT`, in W06's exact layout
(``<kind>/<id>/<revision>.json``, content under ``content/``), resolved
by W02's own :class:`src.contracts.registry.LocalRegistry` — which takes
a root parameter precisely because more than one tree can exist. Nothing
about W06's tree changes, and nothing about this one is special-cased.

Everything is built from the checked-in fixtures, so the tree is a
derived view: ``python -m src.calibration.suite parity`` proves the files
on disk are what the fixtures produce, exactly as W06's parity CLI does
for its own.

No judge is configured. :attr:`GraderProfile.model_judge_ref` is ``None``
on purpose — a profile that named a model would be one approval away
from a chargeable run, and RFC 11 §9.3 is explicit that selecting a model
grader is invalid without a recorded cost approval. The instrument the
set is *authored against* is recorded instead, as a lock of the four
rubric names, versions and prompt digests this repository ships today.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, Literal, TypeAlias

from pydantic import StringConstraints, model_validator

from src.calibration.blinding import HIDDEN_FROM_JUDGE, BlindingPlan, Presentation
from src.calibration.fixtures import (
    ADVERSARIAL_PATH,
    FIXTURE_SALT,
    PAIRWISE_PATH,
    CalibrationCase,
    PairwiseCase,
    load_case_file,
)
from src.calibration.labels import LabelType, decision_vocabulary
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
from src.contracts.registry import (
    BenchmarkSuite,
    Contamination,
    DataPolicy,
    EvaluationLane,
    Exposure,
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
    seal_registry_object,
    validate_registry_safety,
)
from src.eval.metrics import RESEARCH_RUBRICS

#: Repository root, three parents up from ``src/calibration/suite.py``.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The calibration suite's registry root. A sibling of W06's
#: ``eval_registry/`` rather than a directory inside it — see the module
#: docstring for why that is a finding and not a style choice.
CALIBRATION_REGISTRY_ROOT: Final[Path] = REPO_ROOT / "eval_registry_calibration"

#: Content objects live under one subdirectory of the same root, exactly
#: as they do in W06's tree, so a registry reference never resolves to
#: content and vice versa.
CONTENT_DIRNAME: Final[str] = "content"

SUITE_ID: Final[str] = "judge-calibration-v1"
TASK_SET_ID: Final[str] = "judge-calibration-tasks"
RUBRIC_SET_ID: Final[str] = "judge-calibration-rubric"
LABEL_SET_ID: Final[str] = "judge-calibration-expected-labels"
GRADER_PROFILE_ID: Final[str] = "judge-under-calibration"
SPLIT_ID: Final[str] = "judge-calibration-splits"
RETENTION_POLICY_ID: Final[str] = "calibration-repository-history"
GUIDELINE_ID: Final[str] = "judge-calibration-annotation-guide"
PROBE_LOCK_ID: Final[str] = "instrument-under-calibration"
GENERATION_RECORD_ID: Final[str] = "synthetic-generation-record"
BLINDING_PLAN_ID: Final[str] = "judge-calibration-blinding"
DELIVERABLE_ID: Final[str] = "calibration-verdict"

OBJECT_REVISION: Final[str] = "1.0.0"

#: Registration timestamp, a constant so digests do not move with the
#: clock. Same discipline as W06.
REGISTERED_AT: Final[str] = "2026-09-05T00:00:00Z"

REVIEW_RECORD: Final[str] = "docs/agent-engineering/14-judge-calibration-protocol.md"
OWNERS: Final[tuple[str, ...]] = ("maintainer",)

#: Calibration and nothing else. ``development`` and ``regression`` are
#: not declared, so W02's resolver refuses them; ``promotion`` is refused
#: outright, because a set that measures the instrument must never become
#: evidence about the thing the instrument measures.
INTENDED_USES: Final[tuple[IntendedUse, ...]] = (IntendedUse.CALIBRATION,)
PROHIBITED_USES: Final[tuple[IntendedUse, ...]] = (IntendedUse.PROMOTION,)

#: The one task kind this suite declares. A judge probe is not a research
#: task: the candidate here is a grader, and the deliverable is a verdict.
TASK_KIND: Final[str] = "calibration.judge_probe"


class CalibrationContentKind(StrEnum):
    """Content payloads this suite stores outside the governance envelope.

    RFC 11 §10 keeps large or verbatim material content-addressed and
    referenced rather than embedded in a suite manifest, and W02's
    registry has no inline payload field. These are this suite's
    equivalents of W06's content kinds, in this suite's own namespace.
    """

    RETENTION_TERMS = "retention_terms"
    DELIVERABLE_CONTRACT = "deliverable_contract"
    CALIBRATION_GUIDELINE = "calibration_guideline"
    CALIBRATION_ITEM = "calibration_item"
    CALIBRATION_RATIONALE = "calibration_rationale"
    EXPECTED_LABEL = "expected_label"
    JUDGE_PROBE_LOCK = "judge_probe_lock"
    SYNTHETIC_GENERATION = "synthetic_generation"
    BLINDING_PLAN = "blinding_plan"


ContentId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")]


class RetentionTerms(StrictContractModel):
    """Bootstrap terms the root retention policy is retained under.

    The root policy cannot reference itself — its digest would depend on
    its own digest — so it references these, exactly as W06's does.
    """

    terms_id: ContentId
    duration_days: int | None
    deletion_mode: Literal["delete_content_keep_tombstone", "repository_history"]
    description: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class DeliverableContract(StrictContractModel):
    """What a compiled calibration case must return.

    A judge probe's deliverable is a decision plus a rationale reference,
    not a report: the point of the probe is that the grader's *verdict* is
    the artifact under measurement.
    """

    contract_id: ContentId
    task_kind: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.]+$")]
    decision_vocabularies: tuple[tuple[str, tuple[str, ...]], ...]
    requires_rationale: bool
    description: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class GuidelineText(StrictContractModel):
    """The annotation-guide revision the reference decisions were made under."""

    guideline_id: ContentId
    revision: SemVer
    summary: Annotated[str, StringConstraints(min_length=1, max_length=3000)]
    document: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class CalibrationItemContent(StrictContractModel):
    """The verbatim material of one case, evaluator-only.

    Carries the *judge-visible* half and nothing else: the report
    excerpt, the cited identifier, the source excerpt and the rubric
    item. The reference decision lives in the label set, so a role that
    can read the item cannot read the answer by reading further down the
    same object.
    """

    case_id: ContentId
    family: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    label_type: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    report_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    cited_source: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    source_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=4000)] | None = None
    rubric_item: Annotated[str, StringConstraints(min_length=1, max_length=400)] | None = None
    second_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=4000)] | None = None
    blinded_item_id: Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]


class RationaleText(StrictContractModel):
    """Why a case's reference decision is what it is."""

    rationale_id: ContentId
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class ExpectedLabelValue(StrictContractModel):
    """One reference decision value, as a content object.

    W06's finding, applied here: a `LabelRecord` binds its value by
    ``value_ref`` digest to a content object rather than carrying the
    value inline. So each distinct ``(label_type, decision)`` pair gets
    one small object, and every label pointing at that decision shares
    its digest — which is also what makes "how many items were called
    unsupported" answerable by counting refs.
    """

    value_id: ContentId
    label_type: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    decision: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    is_abstention: bool


class ProbeLockEntry(StrictContractModel):
    """One instrument the calibration set was authored against."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    version: SemVer
    prompt_digest: Digest


class JudgeProbeLock(StrictContractModel):
    """The instruments in force when the reference decisions were written.

    The comparability key. 03 §7.7 requires recalibration when the judge,
    the prompt, the rubric or the source representation changes, and
    :func:`src.calibration.metrics.decide` returns HOLD when the measured
    version differs from the calibrated one. This object is where the
    calibrated version comes from.
    """

    lock_id: ContentId
    entries: tuple[ProbeLockEntry, ...]
    judge_model_pinned: Literal[False] = False
    note: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class SyntheticGenerationRecord(StrictContractModel):
    """RFC 11 §11's record for a generated benchmark expansion.

    §11 requires a generated expansion to record its generator and source
    inputs and to be human-reviewed before activation. ``source_inputs``
    is empty because every excerpt was written for this work order — no
    paper text was copied and no model generated a case — and the review
    record is the pull request that activates the suite.
    """

    record_id: ContentId
    generator: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    source_inputs: tuple[str, ...]
    generated_by_model: Literal[False] = False
    identifiers_are_invented: Literal[True] = True
    human_review_record: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    note: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class BlindingPlanContent(StrictContractModel):
    """The suite's blinding plan, plus the fixture salt it uses.

    ``plan_id`` is duplicated at the top level rather than read out of
    the nested plan so that :func:`seal_content` finds every content
    object's id in the same place, whatever its payload shape.

    The salt is in the open here, and only here, because the corpus it
    blinds is synthetic and public: there is nothing to protect and a
    reproducible blinded id is what makes the fixtures checkable. A real
    campaign's plan references a salt object the candidate cannot read;
    this object records that difference in words so a later reader does
    not copy the wrong half.
    """

    plan_id: ContentId
    plan: BlindingPlan
    salt: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    salt_is_public_because: Annotated[str, StringConstraints(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def ids_agree(self) -> BlindingPlanContent:
        if self.plan.plan_id != self.plan_id:
            raise ValueError("the content id and the nested plan id must agree")
        return self


ContentPayload: TypeAlias = (
    RetentionTerms
    | DeliverableContract
    | GuidelineText
    | CalibrationItemContent
    | RationaleText
    | ExpectedLabelValue
    | JudgeProbeLock
    | SyntheticGenerationRecord
    | BlindingPlanContent
)

_CONTENT_KIND: Final[dict[type[StrictContractModel], CalibrationContentKind]] = {
    RetentionTerms: CalibrationContentKind.RETENTION_TERMS,
    DeliverableContract: CalibrationContentKind.DELIVERABLE_CONTRACT,
    GuidelineText: CalibrationContentKind.CALIBRATION_GUIDELINE,
    CalibrationItemContent: CalibrationContentKind.CALIBRATION_ITEM,
    RationaleText: CalibrationContentKind.CALIBRATION_RATIONALE,
    ExpectedLabelValue: CalibrationContentKind.EXPECTED_LABEL,
    JudgeProbeLock: CalibrationContentKind.JUDGE_PROBE_LOCK,
    SyntheticGenerationRecord: CalibrationContentKind.SYNTHETIC_GENERATION,
    BlindingPlanContent: CalibrationContentKind.BLINDING_PLAN,
}

_CONTENT_ID_FIELD: Final[dict[CalibrationContentKind, str]] = {
    CalibrationContentKind.RETENTION_TERMS: "terms_id",
    CalibrationContentKind.DELIVERABLE_CONTRACT: "contract_id",
    CalibrationContentKind.CALIBRATION_GUIDELINE: "guideline_id",
    CalibrationContentKind.CALIBRATION_ITEM: "case_id",
    CalibrationContentKind.CALIBRATION_RATIONALE: "rationale_id",
    CalibrationContentKind.EXPECTED_LABEL: "value_id",
    CalibrationContentKind.JUDGE_PROBE_LOCK: "lock_id",
    CalibrationContentKind.SYNTHETIC_GENERATION: "record_id",
    CalibrationContentKind.BLINDING_PLAN: "plan_id",
}


class ContentIntegrity(StrictContractModel):
    algorithm: Literal["sha256"] = "sha256"
    digest_profile: Literal["agent-contract-json/v1"] = "agent-contract-json/v1"
    payload_digest: Digest


class CalibrationContentEnvelope(StrictContractModel):
    """A self-verifying content object with its own visibility rule."""

    schema_kind: CalibrationContentKind
    schema_version: Literal["1.0.0"] = "1.0.0"
    content_id: ContentId
    revision: SemVer
    visibility: ObjectVisibility
    effective_data_class: DataClass
    source_module: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    created_at: Rfc3339Utc
    payload: ContentPayload
    integrity: ContentIntegrity

    @model_validator(mode="after")
    def verify_kind_and_digest(self) -> CalibrationContentEnvelope:
        expected = _CONTENT_KIND[type(self.payload)]
        if self.schema_kind is not expected:
            raise ValueError(
                f"schema_kind {self.schema_kind.value} does not match payload {expected.value}"
            )
        declared = getattr(self.payload, _CONTENT_ID_FIELD[self.schema_kind])
        if declared != self.content_id:
            raise ValueError(
                f"content_id {self.content_id!r} does not match payload id {declared!r}"
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


def seal_content(
    payload: ContentPayload,
    *,
    visibility: ObjectVisibility,
    source_module: str,
    effective_data_class: DataClass = DataClass.PUBLIC,
    revision: str = OBJECT_REVISION,
    created_at: str = REGISTERED_AT,
) -> CalibrationContentEnvelope:
    """Wrap a content payload in an envelope that verifies its own digest."""
    kind = _CONTENT_KIND[type(payload)]
    return CalibrationContentEnvelope(
        schema_kind=kind,
        content_id=str(getattr(payload, _CONTENT_ID_FIELD[kind])),
        revision=revision,
        visibility=visibility,
        effective_data_class=effective_data_class,
        source_module=source_module,
        created_at=created_at,
        payload=payload,
        integrity=ContentIntegrity(payload_digest=sha256_digest(payload)),
    )


class CalibrationContentStore:
    """Resolve calibration content from a tree, under W02's role rules."""

    def __init__(self, root: Path) -> None:
        self.root = (root / CONTENT_DIRNAME).resolve()

    def _path(self, ref: ImmutableObjectRef) -> Path:
        candidate = (self.root / ref.kind / ref.id / f"{ref.revision}.json").resolve()
        if not candidate.is_relative_to(self.root):
            raise RegistryResolutionError("content locator escaped its root")
        return candidate

    def resolve(
        self, ref: ImmutableObjectRef, *, role: RegistryRole
    ) -> CalibrationContentEnvelope:
        """Read one content object, refusing what the role may not see."""
        path = self._path(ref)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RegistryResolutionError(
                f"content object is unavailable: {ref.kind}/{ref.id}"
            ) from exc
        try:
            envelope = CalibrationContentEnvelope.model_validate_json(raw)
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


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


def _governed(
    *,
    visibility: ObjectVisibility,
    retention_ref: RetentionPolicyRef,
    effective_data_class: DataClass = DataClass.PUBLIC,
) -> dict[str, Any]:
    """The governance fields every registry payload in this tree shares."""
    return {
        "revision": OBJECT_REVISION,
        "status": LifecycleStatus.ACTIVE,
        "owners": OWNERS,
        "visibility": visibility,
        "intended_uses": INTENDED_USES,
        "prohibited_uses": PROHIBITED_USES,
        "license_policy": LicensePolicy(
            license_id="UNLICENSED",
            redistribution=Redistribution.PROHIBITED,
            permitted_uses=INTENDED_USES,
            attribution=None,
        ),
        "data_policy": DataPolicy(
            registry_classification=DataClass.INTERNAL,
            effective_data_class=effective_data_class,
            contains_personal_data=False,
            training_use=TrainingUse.PROHIBITED,
            retention_policy_ref=retention_ref,
        ),
        # Publicly exposed, because it is checked into a public
        # repository the moment this PR merges. `private_unexposed` would
        # be the flattering answer and a false one; RFC 11 §11 wants the
        # exposure of the artifact, not the intent of its author. That
        # the material is *synthetic* is a separate fact, recorded in
        # `synthetic-generation-record` rather than smuggled into this
        # enum, which has no value for it.
        "contamination": Contamination(
            exposure=Exposure.PUBLIC_REPOSITORY,
            canary_set_ref=None,
            last_reviewed_at=REGISTERED_AT,
        ),
        "provenance": Provenance(
            created_at=REGISTERED_AT,
            created_by="maintainer",
            parent=None,
            review_record=REVIEW_RECORD,
        ),
    }


class Bundle(StrictContractModel):
    """Everything one build produces, plus the suite reference."""

    objects: tuple[RegistryEnvelope, ...]
    contents: tuple[CalibrationContentEnvelope, ...]
    suite_ref: ImmutableObjectRef


def _retention() -> tuple[RegistryEnvelope, CalibrationContentEnvelope, RetentionPolicyRef]:
    terms = seal_content(
        RetentionTerms(
            terms_id="calibration-bootstrap-terms",
            duration_days=None,
            deletion_mode="repository_history",
            description=(
                "Calibration registry metadata is retained for the life of the "
                "repository's Git history. These bootstrap terms exist because the "
                "root retention policy cannot reference its own digest. A real "
                "human-label campaign does not inherit these terms: 13 §5 gives human "
                "labels their own retention decision, still an open owner item."
            ),
        ),
        visibility=ObjectVisibility.PUBLIC,
        source_module="docs/agent-engineering/14-judge-calibration-protocol.md",
    )
    terms_ref = terms.object_ref()
    policy = seal_registry_object(
        RetentionPolicy(
            **_governed(
                visibility=ObjectVisibility.PUBLIC,
                retention_ref=RetentionPolicyRef(
                    kind="retention_policy",
                    id=terms_ref.id,
                    revision=terms_ref.revision,
                    digest=terms_ref.digest,
                ),
            ),
            retention_policy_id=RETENTION_POLICY_ID,
            duration_days=None,
            deletion_mode="repository_history",
        )
    )
    ref = policy.object_ref()
    return (
        policy,
        terms,
        RetentionPolicyRef(
            kind="retention_policy", id=ref.id, revision=ref.revision, digest=ref.digest
        ),
    )


_RUBRIC_ITEMS: Final[tuple[tuple[str, str, str, str], ...]] = (
    (
        "claim_support_agreement",
        "Does the judge's claim-support verdict match the adjudicated reference decision?",
        "confusion_table_over_resolved_items",
        "Denominator is items both the reference and the judge decided; abstentions are "
        "reported under the declared abstention policy and never silently dropped.",
    ),
    (
        "citation_correctness_agreement",
        "Does the judge's citation verdict match the adjudicated reference decision?",
        "confusion_table_over_resolved_items",
        "Denominator is items both sides decided; an unresolvable identifier is a "
        "decision, not a null.",
    ),
    (
        "rubric_coverage_agreement",
        "Does the judge's coverage verdict match the adjudicated reference decision?",
        "confusion_table_over_resolved_items",
        "Denominator is items both sides decided; an honest evidence-gap statement is "
        "a covered item, not an absent one.",
    ),
    (
        "pairwise_position_bias",
        "Across both presentation orders, how often does the judge prefer the first position?",
        "first_position_share_over_both_order_readings",
        "Denominator is two readings per pair presented in both orders; a pair seen in "
        "one order contributes nothing and is reported as unmeasured.",
    ),
)


def _rubric_set(retention_ref: RetentionPolicyRef) -> RegistryEnvelope:
    return seal_registry_object(
        RubricSet(
            **_governed(visibility=ObjectVisibility.EVALUATOR, retention_ref=retention_ref),
            rubric_set_id=RUBRIC_SET_ID,
            items=tuple(
                RubricItem(
                    rubric_item_id=item_id,
                    revision=OBJECT_REVISION,
                    description=description,
                    task_kinds=(TASK_KIND,),
                    scoring_type="categorical",
                    evidence_type="adjudicated_reference_decision",
                    # Evaluator-only, every one of them. RFC 11 §9.1 hides
                    # reference answers by default, and here the rubric
                    # item *is* "does the verdict match the reference" —
                    # an item a candidate could read would hand over the
                    # shape of the answer key.
                    visibility=ObjectVisibility.EVALUATOR,
                    aggregation=aggregation,
                    denominator_policy=denominator,
                )
                for item_id, description, aggregation, denominator in _RUBRIC_ITEMS
            ),
        )
    )


def _value_id(label_type: str, decision: str) -> str:
    return f"{label_type}-{decision}".replace("_", "-")


def _expected_label_values() -> tuple[CalibrationContentEnvelope, ...]:
    """One content object per (label type, decision) in the vocabulary.

    Every value, not only the ones the fixtures use: the label set is the
    answer key's vocabulary as well as its contents, and a value that
    appears only when a case happens to need it makes "which decisions
    exist" a question about the corpus rather than about the protocol.
    """
    values: list[CalibrationContentEnvelope] = []
    for label_type in LabelType:
        for decision in decision_vocabulary(label_type):
            values.append(
                seal_content(
                    ExpectedLabelValue(
                        value_id=_value_id(label_type.value, decision),
                        label_type=label_type.value,
                        decision=decision,
                        is_abstention=decision in {"abstain", "not_verifiable", "tie"},
                    ),
                    visibility=ObjectVisibility.EVALUATOR,
                    source_module="src/calibration/labels.py",
                )
            )
    return tuple(values)


def _guideline() -> CalibrationContentEnvelope:
    return seal_content(
        GuidelineText(
            guideline_id=GUIDELINE_ID,
            revision=OBJECT_REVISION,
            summary=(
                "Claim support: supported only when the cited source states or entails "
                "the claim without a further assumption; contradicted when the source "
                "states the reverse; not_verifiable when no admissible source could "
                "settle it; abstain when the annotator cannot decide from the material "
                "shown. Citation correctness: the identifier already resolved, so the "
                "question is whether the resolved source carries the claim. Rubric "
                "coverage: covered when the item is satisfied with admissible evidence, "
                "and a report that names a genuine evidence gap satisfies the gap item. "
                "Pairwise: judge the reports, and record the position you chose, not "
                "the report you think it was. Never reward fluency, length or "
                "confidence, and never resolve a disagreement by averaging."
            ),
            document=REVIEW_RECORD,
        ),
        visibility=ObjectVisibility.EVALUATOR,
        source_module=REVIEW_RECORD,
    )


def _probe_lock() -> CalibrationContentEnvelope:
    return seal_content(
        JudgeProbeLock(
            lock_id=PROBE_LOCK_ID,
            entries=tuple(
                ProbeLockEntry(
                    name=rubric.name,
                    version=rubric.version,
                    prompt_digest=f"sha256:{rubric.digest}",
                )
                for rubric in RESEARCH_RUBRICS
            ),
            note=(
                "The instruments this calibration set was authored against, read from "
                "src/eval/metrics.RESEARCH_RUBRICS. No judge has been run against the "
                "set and no model is pinned: a grader profile that named a model would "
                "be one approval away from a chargeable run, and RFC 11 §9.3 makes "
                "selecting a model grader invalid without a recorded cost approval. "
                "When a judge is eventually measured, a version here that no longer "
                "matches the live rubric is what makes the gate answer HOLD."
            ),
        ),
        visibility=ObjectVisibility.EVALUATOR,
        source_module="src/eval/metrics.py",
    )


def _generation_record() -> CalibrationContentEnvelope:
    return seal_content(
        SyntheticGenerationRecord(
            record_id=GENERATION_RECORD_ID,
            generator="P0-WO10, hand-authored in tests/fixtures/calibration/",
            source_inputs=(),
            human_review_record=REVIEW_RECORD,
            note=(
                "RFC 11 §11 requires a generated benchmark expansion to record its "
                "generator and source inputs and to be human-reviewed before "
                "activation. source_inputs is empty because every excerpt was written "
                "for this work order: no paper text is copied, no model generated a "
                "case, and every arXiv-shaped identifier is invented so that nothing "
                "here resolves to a real record. The suite is publicly exposed the "
                "moment it merges, so it can never serve as sealed promotion evidence "
                "— which is why promotion is a prohibited use on every object."
            ),
        ),
        visibility=ObjectVisibility.PUBLIC,
        source_module="src/calibration/suite.py",
    )


def _blinding_plan(salt_ref: ImmutableObjectRef) -> BlindingPlan:
    return BlindingPlan(
        plan_id=BLINDING_PLAN_ID,
        revision=OBJECT_REVISION,
        salt_ref=salt_ref,
        hidden_fields=tuple(sorted(HIDDEN_FROM_JUDGE)),
        seed=20260905,
        presentation=Presentation.PAIRWISE,
        both_orders=True,
        created_at=REGISTERED_AT,
    )


def _blinding_content() -> CalibrationContentEnvelope:
    # The plan references its own content object, so the ref is built
    # from a placeholder digest of the salt string rather than of the
    # enclosing object: a salt reference that depended on the plan's
    # digest could not exist inside the plan.
    salt_ref = ImmutableObjectRef(
        kind="blinding_plan",
        id=BLINDING_PLAN_ID,
        revision=OBJECT_REVISION,
        digest=sha256_digest({"salt": FIXTURE_SALT}),
    )
    return seal_content(
        BlindingPlanContent(
            plan_id=BLINDING_PLAN_ID,
            plan=_blinding_plan(salt_ref),
            salt=FIXTURE_SALT,
            salt_is_public_because=(
                "The corpus this salt blinds is synthetic and checked into a public "
                "repository, so there is nothing for the salt to protect and a "
                "reproducible blinded id is what makes the fixtures checkable. A real "
                "campaign draws its own salt into an evaluator-only object and "
                "references it by digest; copying this object's shape without that "
                "change would blind nobody."
            ),
        ),
        visibility=ObjectVisibility.EVALUATOR,
        source_module="src/calibration/blinding.py",
    )


def _deliverable() -> CalibrationContentEnvelope:
    return seal_content(
        DeliverableContract(
            contract_id=DELIVERABLE_ID,
            task_kind=TASK_KIND,
            decision_vocabularies=tuple(
                (label_type.value, decision_vocabulary(label_type)) for label_type in LabelType
            ),
            requires_rationale=True,
            description=(
                "A judge probe returns one decision from the vocabulary for its label "
                "type plus a rationale. A rationale is required because 03 §7.8 routes "
                "low-confidence and high-disagreement items to human adjudication, and "
                "an adjudicator cannot review a verdict that gives no reason."
            ),
        ),
        visibility=ObjectVisibility.PUBLIC,
        source_module="src/calibration/suite.py",
    )


def _case_content(case: CalibrationCase) -> tuple[CalibrationContentEnvelope, ...]:
    item = seal_content(
        CalibrationItemContent(
            case_id=case.case_id,
            family=case.family.value,
            label_type=case.label_type.value,
            report_excerpt=case.material.report_excerpt,
            cited_source=case.material.cited_source,
            source_excerpt=case.material.source_excerpt,
            rubric_item=case.material.rubric_item,
            blinded_item_id=case.blinded_item_id,
        ),
        visibility=ObjectVisibility.EVALUATOR,
        source_module="tests/fixtures/calibration/adversarial_cases.json",
    )
    rationale = seal_content(
        RationaleText(rationale_id=case.case_id, text=case.why),
        visibility=ObjectVisibility.EVALUATOR,
        source_module="tests/fixtures/calibration/adversarial_cases.json",
    )
    return (item, rationale)


def _pairwise_content(case: PairwiseCase) -> tuple[CalibrationContentEnvelope, ...]:
    item = seal_content(
        CalibrationItemContent(
            case_id=case.case_id,
            family="pairwise_preference",
            label_type=LabelType.PAIRWISE_PREFERENCE.value,
            report_excerpt=case.first_excerpt,
            second_excerpt=case.second_excerpt,
            blinded_item_id=case.blinded_item_id,
        ),
        visibility=ObjectVisibility.EVALUATOR,
        source_module="tests/fixtures/calibration/pairwise_cases.json",
    )
    rationale = seal_content(
        RationaleText(rationale_id=case.case_id, text=case.why),
        visibility=ObjectVisibility.EVALUATOR,
        source_module="tests/fixtures/calibration/pairwise_cases.json",
    )
    return (item, rationale)


def _task_case(
    *,
    case_id: str,
    slice_tags: Sequence[str],
    objective: str,
    retention_ref: RetentionPolicyRef,
    deliverable_ref: ImmutableObjectRef,
    item_ref: ImmutableObjectRef,
    rationale_ref: ImmutableObjectRef,
) -> RegistryEnvelope:
    return seal_registry_object(
        TaskCase(
            **_governed(visibility=ObjectVisibility.EVALUATOR, retention_ref=retention_ref),
            case_id=case_id,
            task_input=TaskInput(
                objective=objective,
                task_kind=TASK_KIND,
                constraint_refs=(),
                deliverable_ref=deliverable_ref,
            ),
            # Empty. Every reference in a judge probe is evaluator
            # material: there is no candidate role for this suite, and a
            # candidate-visible ref would be the first thing an answer
            # key leaked through.
            candidate_visible_refs=(),
            evaluator_refs=(item_ref, rationale_ref),
            slice_tags=tuple(slice_tags),
        )
    )


def build_bundle(
    *, adversarial: Path = ADVERSARIAL_PATH, pairwise: Path = PAIRWISE_PATH
) -> Bundle:
    """Build every registry and content object from the checked-in fixtures.

    Args:
        adversarial: The single-item fixture file.
        pairwise: The pairwise fixture file.

    Returns:
        The bundle.
    """
    cases = load_case_file(adversarial).cases
    pairs = load_case_file(pairwise).pairwise

    policy, terms, retention_ref = _retention()
    objects: list[RegistryEnvelope] = [policy]
    contents: list[CalibrationContentEnvelope] = [terms]

    deliverable = _deliverable()
    guideline = _guideline()
    probe_lock = _probe_lock()
    generation = _generation_record()
    blinding = _blinding_content()
    contents.extend([deliverable, guideline, probe_lock, generation, blinding])

    values = _expected_label_values()
    contents.extend(values)
    value_refs = {
        (content.payload.label_type, content.payload.decision): content.object_ref()
        for content in values
        if isinstance(content.payload, ExpectedLabelValue)
    }

    rubric = _rubric_set(retention_ref)
    objects.append(rubric)

    case_envelopes: list[RegistryEnvelope] = []
    labels: list[LabelRecord] = []
    for case in cases:
        item, rationale = _case_content(case)
        contents.extend([item, rationale])
        envelope = _task_case(
            case_id=case.case_id,
            slice_tags=case.slice_tags,
            objective=(
                f"Judge the {case.label_type.value.replace('_', ' ')} of one blinded "
                f"report excerpt against its cited source."
            ),
            retention_ref=retention_ref,
            deliverable_ref=deliverable.object_ref(),
            item_ref=item.object_ref(),
            rationale_ref=rationale.object_ref(),
        )
        case_envelopes.append(envelope)
        labels.append(
            LabelRecord(
                label_id=case.case_id,
                target_ref=envelope.object_ref(),
                label_type=f"{case.label_type.value}.synthetic_construction",
                value_ref=value_refs[
                    (case.label_type.value, case.expected_reference_decision)
                ],
                evidence_refs=(rationale.object_ref(),),
                annotator_id="ann-w10author",
                guideline_ref=guideline.object_ref(),
                labeled_at=REGISTERED_AT,
                # `unreviewed`, not `agreed`. One construction fact is not
                # a consensus, and calling it one would be the overwrite
                # RFC 11 §9.2 forbids, dressed as a default.
                agreement_state="unreviewed",
                supersedes_ref=None,
            )
        )
    for pair in pairs:
        item, rationale = _pairwise_content(pair)
        contents.extend([item, rationale])
        envelope = _task_case(
            case_id=pair.case_id,
            slice_tags=pair.slice_tags,
            objective=(
                "Choose the better of two blinded report excerpts, presented in both "
                "orders, and record the position chosen."
            ),
            retention_ref=retention_ref,
            deliverable_ref=deliverable.object_ref(),
            item_ref=item.object_ref(),
            rationale_ref=rationale.object_ref(),
        )
        case_envelopes.append(envelope)
        labels.append(
            LabelRecord(
                label_id=pair.case_id,
                target_ref=envelope.object_ref(),
                label_type="pairwise_preference.synthetic_construction",
                value_ref=value_refs[
                    (
                        LabelType.PAIRWISE_PREFERENCE.value,
                        "first" if pair.expected_reference_preference == "first_excerpt" else (
                            "second" if pair.expected_reference_preference == "second_excerpt"
                            else "tie"
                        ),
                    )
                ],
                evidence_refs=(rationale.object_ref(),),
                annotator_id="ann-w10author",
                guideline_ref=guideline.object_ref(),
                labeled_at=REGISTERED_AT,
                agreement_state="unreviewed",
                supersedes_ref=None,
            )
        )
    objects.extend(case_envelopes)

    case_refs = tuple(envelope.object_ref() for envelope in case_envelopes)
    task_set = seal_registry_object(
        TaskSet(
            **_governed(visibility=ObjectVisibility.EVALUATOR, retention_ref=retention_ref),
            task_set_id=TASK_SET_ID,
            case_refs=case_refs,
        )
    )
    label_set = seal_registry_object(
        LabelSet(
            **_governed(visibility=ObjectVisibility.EVALUATOR, retention_ref=retention_ref),
            label_set_id=LABEL_SET_ID,
            labels=tuple(labels),
        )
    )
    split = seal_registry_object(
        SplitAssignment(
            **_governed(visibility=ObjectVisibility.EVALUATOR, retention_ref=retention_ref),
            split_assignment_id=SPLIT_ID,
            # Development. A validation or sealed split would fail closed
            # in W02's resolver without a real access broker, which is
            # the correct behaviour and would make this suite
            # unresolvable. 13 §8 keeps the broker an open owner item;
            # the protocol document says what changes when it exists.
            split=SplitKind.DEVELOPMENT,
            case_refs=case_refs,
        )
    )
    grader = seal_registry_object(
        GraderProfile(
            **_governed(visibility=ObjectVisibility.EVALUATOR, retention_ref=retention_ref),
            grader_profile_id=GRADER_PROFILE_ID,
            deterministic_metric_refs=(probe_lock.object_ref(),),
            model_judge_ref=None,
            prompt_ref=None,
            rubric_set_ref=rubric.object_ref(),
            calibration_ref=label_set.object_ref(),
            null_score_policy=(
                "A judge failure or an unparseable verdict scores null and stays in the "
                "denominator; an abstention is a decision and is counted under the "
                "report's declared abstention policy, never dropped."
            ),
        )
    )
    objects.extend([task_set, label_set, split, grader])

    suite = seal_registry_object(
        BenchmarkSuite(
            **_governed(visibility=ObjectVisibility.EVALUATOR, retention_ref=retention_ref),
            suite_id=SUITE_ID,
            title="Judge calibration probe, synthetic development suite",
            description=(
                "Thirty synthetic judge probes across the six adversarial families 03 "
                "§7.5 and 12 §16 require, with an evaluator-only reference decision for "
                "each. This is a stress set, not a calibration set: every case was "
                "authored to trip a judge, so its rates describe the corpus and are "
                "never pooled with a representative sample. No judge has been run "
                "against it and no model grader is pinned."
            ),
            task_kinds=(TASK_KIND,),
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
    objects.append(suite)

    return Bundle(
        objects=tuple(objects), contents=tuple(contents), suite_ref=suite.object_ref()
    )


# ---------------------------------------------------------------------------
# Writing, reading and parity
# ---------------------------------------------------------------------------


def validate_content_safety(envelope: CalibrationContentEnvelope) -> None:
    """Reject secret-shaped values and private absolute paths in content.

    Delegates to W02's patterns through the registry's own scanner by
    re-using its compiled expressions rather than copying them: two
    lists of secret shapes drift, and the one that drifts is always the
    one nobody reads. (W06 made the same call for the same reason.)
    """
    from src.contracts.registry import (  # noqa: PLC0415
        _PRIVATE_ABSOLUTE_PATH,
        _SECRET_PATTERNS,
        _walk_strings,
    )

    for path, text in _walk_strings(envelope.model_dump(mode="json")):
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            raise RegistryAccessError(f"secret-shaped value at {path}")
        if _PRIVATE_ABSOLUTE_PATH.search(text):
            raise RegistryAccessError(f"private absolute path at {path}")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def write_tree(bundle: Bundle, root: Path) -> list[Path]:
    """Write every object of a bundle to its locator; return the paths.

    Every object is safety-scanned first, so a tree is never written with
    a credential or a private path in it.
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


def locator(ref: ImmutableObjectRef, *, content: bool) -> str:
    """The path, relative to a root, that a reference resolves to."""
    prefix = f"{CONTENT_DIRNAME}/" if content else ""
    return f"{prefix}{ref.kind}/{ref.id}/{ref.revision}.json"


def tree_mismatches(
    root: Path = CALIBRATION_REGISTRY_ROOT,
    *,
    adversarial: Path = ADVERSARIAL_PATH,
    pairwise: Path = PAIRWISE_PATH,
) -> tuple[str, ...]:
    """Name every way the checked-in tree differs from the built bundle.

    Faults are returned as data rather than raised, so one run reports
    everything wrong with a tree instead of the first thing — the shape
    W06's parity report uses, for the same reason.

    Args:
        root: The tree to check.
        adversarial: The single-item fixture file.
        pairwise: The pairwise fixture file.

    Returns:
        One line per mismatch, sorted. Empty when the tree is exactly
        what the fixtures build.
    """
    bundle = build_bundle(adversarial=adversarial, pairwise=pairwise)
    expected: dict[str, str] = {}
    for envelope in bundle.objects:
        expected[locator(envelope.object_ref(), content=False)] = canonical_json(envelope)
    for content in bundle.contents:
        expected[locator(content.object_ref(), content=True)] = canonical_json(content)

    if not root.is_dir():
        return (f"{root.name}: the registry tree does not exist",)

    found = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8").rstrip("\n")
        for path in root.rglob("*.json")
    }
    mismatches: list[str] = []
    for relative in sorted(set(expected) - set(found)):
        mismatches.append(f"{relative}: the fixtures build this object; the tree has no file")
    for relative in sorted(set(found) - set(expected)):
        mismatches.append(f"{relative}: the tree carries a file the fixtures do not build")
    for relative in sorted(set(expected) & set(found)):
        if expected[relative] != found[relative]:
            mismatches.append(f"{relative}: on-disk bytes differ from the built object")
    return tuple(mismatches)


def read_tree(root: Path = CALIBRATION_REGISTRY_ROOT) -> tuple[
    tuple[RegistryEnvelope, ...], tuple[CalibrationContentEnvelope, ...]
]:
    """Read a checked-in tree back, verifying every digest and locator.

    Args:
        root: The tree.

    Returns:
        The registry objects and the content objects.

    Raises:
        RegistryResolutionError: A file is invalid or filed at a locator
            its own identity does not resolve to.
    """
    objects: list[RegistryEnvelope] = []
    contents: list[CalibrationContentEnvelope] = []
    content_root = root / CONTENT_DIRNAME
    for path in sorted(root.rglob("*.json")):
        raw = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        try:
            if path.is_relative_to(content_root):
                content = CalibrationContentEnvelope.model_validate_json(raw)
                contents.append(content)
                expected = locator(content.object_ref(), content=True)
            else:
                envelope = RegistryEnvelope.model_validate_json(raw)
                objects.append(envelope)
                expected = locator(envelope.object_ref(), content=False)
        except ValueError as exc:
            raise RegistryResolutionError(f"invalid registry object: {relative}: {exc}") from exc
        if expected != relative:
            raise RegistryResolutionError(
                f"mislocated registry object: {relative} resolves to {expected}"
            )
    return tuple(objects), tuple(contents)


def suite_ref(root: Path = CALIBRATION_REGISTRY_ROOT) -> ImmutableObjectRef:
    """Return the exact reference of the calibration suite on disk."""
    path = root / "benchmark_suite" / SUITE_ID / f"{OBJECT_REVISION}.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryResolutionError(f"registry tree has no suite {SUITE_ID}") from exc
    return RegistryEnvelope.model_validate_json(raw).object_ref()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.calibration.suite",
        description="Build, write or verify the judge-calibration registry tree.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write", help="write the tree from the checked-in fixtures")
    write.add_argument("--root", type=Path, default=CALIBRATION_REGISTRY_ROOT)
    parity = sub.add_parser("parity", help="verify the tree matches the fixtures")
    parity.add_argument("--root", type=Path, default=CALIBRATION_REGISTRY_ROOT)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entry point. Returns 0 when the tree is what the fixtures build."""
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "write":
        paths = write_tree(build_bundle(), args.root)
        print(f"wrote {len(paths)} objects under {args.root}")
        return 0
    mismatches = tree_mismatches(args.root)
    if mismatches:
        for line in mismatches:
            print(f"MISMATCH {line}", file=sys.stderr)
        print(f"{len(mismatches)} mismatches", file=sys.stderr)
        return 1
    print(f"calibration registry parity clean at {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
