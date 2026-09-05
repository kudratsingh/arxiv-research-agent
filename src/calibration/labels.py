"""Human calibration labels, and the lineage that keeps disagreement.

RFC 11 §9.2 fixes the shape: labels record their target, type, value,
evidence, pseudonymous annotator, timestamp, guideline revision,
agreement state, confidence and supersession lineage; *disagreement is
retained*, and adjudication creates a new record rather than deleting
the originals. W02 landed that as
:class:`src.contracts.registry.LabelRecord`, a deliberately generic
container: one opaque ``label_type`` string, one ``value_ref`` to a
content object, one ``annotator_id``. It is the right registry primitive
and it is not a calibration vocabulary — nothing in it says what a
claim-support decision may be, who is allowed to make one, or what
happens when two annotators disagree.

This module is that vocabulary. It sits *above* W02 rather than beside
it: every type here projects into `LabelRecord` through
:func:`registry_label_records`, so the registry stays the one place an
immutable label lives and this package stays the one place the
calibration rules are written down.

Three decisions carry the module.

**A model verdict cannot be spelled as a label.**
:class:`AnnotatorKind` names ``model`` so the schema can refuse it, and
:class:`CalibrationLabel` raises when it sees one. A judge's answer is a
:class:`JudgeVerdict` — a different type, with a grader profile and a
rubric version instead of an annotator, because what produced it is an
instrument configuration rather than a person. RFC 11 §9.2 allows model
output to become a *weak-label* dataset later under a separate approved
process; the point of the split is that such a promotion has to be
written, not typed by accident.

**An unresolved disagreement has no value.**
:class:`LabelledItem` returns ``None`` from
:attr:`~LabelledItem.resolved_decision` when its annotators disagree and
no adjudication exists. The obvious alternative — majority, or first
label wins — is the exact failure RFC 11 §9.2 and 12 §16 name: a
consensus that silently overwrites the decisions it came from. An item
in that state is reported as `disputed` and stays out of every
denominator until a human resolves it.

**Confidence is a category, not a number.** 03 §4 is explicit that
"confident writing is not confidence data" and that calibration is only
required where it can be measured. Three ordered buckets can be
adjudicated and audited; a 0–1 float invites an average nobody can
defend.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Final, Literal, TypeAlias

from pydantic import Field, StringConstraints, model_validator

from src.contracts.kernel import (
    ImmutableObjectRef,
    Rfc3339Utc,
    SemVer,
    StrictContractModel,
)
from src.contracts.registry import LabelRecord

#: Blinded item identity. Twelve hex characters of a salted digest: long
#: enough that the mapping is not guessable from the corpus, short
#: enough to read aloud in an adjudication meeting. The salt lives in an
#: evaluator-only content object, never in a label — see
#: :mod:`src.calibration.blinding`.
BlindedItemId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]

#: Opaque annotator pseudonym. RFC 11 §9.2 and 13 §3.1 both require the
#: id in a label to be pseudonymous: the mapping from ``ann-7f2c`` to a
#: person is a separate, key-erasable record owned by the
#: human-evaluation steward, and deleting a person means deleting that
#: mapping without destroying the label lineage.
AnnotatorId: TypeAlias = Annotated[str, StringConstraints(pattern=r"^ann-[a-z0-9]{4,32}$")]

#: Identifier for one label, adjudication or verdict inside a set.
MemberId: TypeAlias = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
]

#: Slice tag, matching the registry's member-id shape so a tag can be
#: carried on a `TaskCase` unchanged.
SliceTag: TypeAlias = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]

#: W02's `LabelRecord.agreement_state` vocabulary, aliased so this
#: module's derivation and the registry's field cannot drift apart.
AgreementState: TypeAlias = Literal["unreviewed", "agreed", "disputed", "adjudicated"]


class LabelType(StrEnum):
    """The four label types AE-004 needs.

    Two of them score a *claim*, one scores a *rubric item*, and one
    scores a *pair of reports*. They are separate types rather than one
    "quality" label because 03 §7 asks for rubric-level and claim-level
    judgments in place of a holistic score, and because their
    denominators differ: claim support is per checked claim, coverage is
    per rubric item, preference is per pair.
    """

    CLAIM_SUPPORT = "claim_support"
    CITATION_CORRECTNESS = "citation_correctness"
    RUBRIC_COVERAGE = "rubric_coverage"
    PAIRWISE_PREFERENCE = "pairwise_preference"


class AnnotatorKind(StrEnum):
    """Who or what produced a decision.

    ``MODEL`` exists to be refused. A vocabulary that simply omitted it
    would leave "a model wrote this label" expressible as a human kind
    with a machine behind it; naming the kind lets
    :class:`CalibrationLabel` reject it by name and lets a report say
    which rows were excluded and why.
    """

    HUMAN_EXPERT = "human_expert"
    HUMAN_REVIEWER = "human_reviewer"
    DETERMINISTIC_CHECK = "deterministic_check"
    SYNTHETIC_CONSTRUCTION = "synthetic_construction"
    MODEL = "model"


#: Kinds that are people. The distinction from
#: :data:`GROUND_TRUTH_ANNOTATOR_KINDS` matters for the *expert time*
#: budget in the cost estimate: a deterministic check costs nothing, a
#: synthetic construction fact cost the fixture author minutes that are
#: already spent, and an expert hour is the scarcest input in AE-004.
HUMAN_ANNOTATOR_KINDS: Final[frozenset[AnnotatorKind]] = frozenset(
    {AnnotatorKind.HUMAN_EXPERT, AnnotatorKind.HUMAN_REVIEWER}
)

#: Kinds whose decisions may serve as reference truth.
#:
#: A deterministic check qualifies because it is reproducible and its
#: definition is versioned (ADR 0074). ``SYNTHETIC_CONSTRUCTION``
#: qualifies for a narrower reason: on an item this repository *authored*,
#: the reference is a fact about the construction — the source excerpt
#: was written not to contain the claim — so it is true by the same
#: mechanism that makes a unit-test expectation true. It is emphatically
#: **not** an expert judgement about a real report, which is why
#: :func:`campaign_eligible` refuses a set built from these and why the
#: protocol counts zero of them toward AE-004.
#:
#: A model qualifies at no temperature.
GROUND_TRUTH_ANNOTATOR_KINDS: Final[frozenset[AnnotatorKind]] = HUMAN_ANNOTATOR_KINDS | {
    AnnotatorKind.DETERMINISTIC_CHECK,
    AnnotatorKind.SYNTHETIC_CONSTRUCTION,
}


class Confidence(StrEnum):
    """Ordered confidence category attached to one decision.

    Used for routing, not for weighting. 03 §7.8 asks that low-confidence
    and high-disagreement items go to human adjudication; averaging these
    buckets into a number would be the "confident writing" mistake 03 §4
    warns about.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ClaimSupportDecision(StrEnum):
    """Does the cited source support this claim?

    ``CONTRADICTED`` is separate from ``UNSUPPORTED`` because 03 §4 asks
    for contradiction recall as its own measure: a source that says the
    opposite is a different failure from a source that is merely silent,
    and collapsing them hides the one that matters more.
    ``NOT_VERIFIABLE`` is a property of the item — no admissible evidence
    exists — while ``ABSTAIN`` is a property of the annotator.
    """

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    NOT_VERIFIABLE = "not_verifiable"
    ABSTAIN = "abstain"


class CitationCorrectnessDecision(StrEnum):
    """Does this citation point at a source that carries the claim?

    Validity (the identifier resolves) is already decidable without a
    person — ``src/eval/groundedness.py`` does it — so this label starts
    where the deterministic check stops: the identifier resolved, and the
    question is whether the resolved source is the *right* one.
    """

    CORRECT = "correct"
    WRONG_SOURCE = "wrong_source"
    UNRESOLVABLE = "unresolvable"
    ABSTAIN = "abstain"


class RubricCoverageDecision(StrEnum):
    """Is this rubric item satisfied, with admissible evidence?

    ``PARTIAL`` exists because reports usually half-answer things, and a
    forced binary would push every half-answer into whichever bucket the
    annotator felt like. It projects to *not satisfied* on the binary
    axis (see :func:`binary_outcome`) because 07 §7 defines task-rubric
    success as items satisfied *with admissible evidence*.
    """

    COVERED = "covered"
    PARTIAL = "partial"
    NOT_COVERED = "not_covered"
    ABSTAIN = "abstain"


class PairwisePreferenceDecision(StrEnum):
    """Which of two reports is better?

    ``FIRST`` and ``SECOND`` are *positions*, not candidates. That is the
    whole point: the same pair is shown in both orders, and a judge that
    prefers the first position regardless of content is what
    :func:`src.calibration.metrics.position_bias` measures.
    """

    FIRST = "first"
    SECOND = "second"
    TIE = "tie"
    ABSTAIN = "abstain"


_VOCABULARY: Final[dict[LabelType, type[StrEnum]]] = {
    LabelType.CLAIM_SUPPORT: ClaimSupportDecision,
    LabelType.CITATION_CORRECTNESS: CitationCorrectnessDecision,
    LabelType.RUBRIC_COVERAGE: RubricCoverageDecision,
    LabelType.PAIRWISE_PREFERENCE: PairwisePreferenceDecision,
}

#: Decisions that assert the positive outcome of their label type.
_POSITIVE: Final[frozenset[str]] = frozenset(
    {
        ClaimSupportDecision.SUPPORTED.value,
        CitationCorrectnessDecision.CORRECT.value,
        RubricCoverageDecision.COVERED.value,
    }
)

#: Decisions that assert the negative outcome of their label type.
_NEGATIVE: Final[frozenset[str]] = frozenset(
    {
        ClaimSupportDecision.UNSUPPORTED.value,
        ClaimSupportDecision.CONTRADICTED.value,
        CitationCorrectnessDecision.WRONG_SOURCE.value,
        CitationCorrectnessDecision.UNRESOLVABLE.value,
        RubricCoverageDecision.PARTIAL.value,
        RubricCoverageDecision.NOT_COVERED.value,
    }
)

#: Decisions that assert nothing on the binary axis. 07 §7 requires that
#: these stay visible and never become passes; :func:`binary_outcome`
#: returns ``None`` for them so a caller has to say what it did with
#: them rather than inheriting a silent default.
NON_DECISIONS: Final[frozenset[str]] = frozenset(
    {
        ClaimSupportDecision.NOT_VERIFIABLE.value,
        ClaimSupportDecision.ABSTAIN.value,
        CitationCorrectnessDecision.ABSTAIN.value,
        RubricCoverageDecision.ABSTAIN.value,
        PairwisePreferenceDecision.TIE.value,
        PairwisePreferenceDecision.ABSTAIN.value,
    }
)


def decision_vocabulary(label_type: LabelType) -> tuple[str, ...]:
    """Return the decisions a label of `label_type` may carry.

    Args:
        label_type: The label type.

    Returns:
        Every permitted decision value, in declaration order.
    """
    return tuple(member.value for member in _VOCABULARY[label_type])


def binary_outcome(decision: str) -> bool | None:
    """Project one decision onto the pass/fail axis the metrics use.

    ``None`` is the third answer and it is load-bearing: an abstention, a
    tie, and an unverifiable claim are not failures, and a metric that
    turned them into failures would report a worse judge (or a worse
    report) than the evidence supports. ``docs/eval.md`` measures the
    cost of getting this wrong: how abstentions are counted swings
    measured accuracy by 10–34 points on identical verdicts, which is why
    :class:`src.calibration.metrics.AbstentionPolicy` makes the choice an
    explicit, reported field rather than a default hidden here.

    Pairwise preferences have no pass/fail axis at all — ``first`` is a
    position, not a success — so every pairwise decision returns
    ``None``. Position bias is measured by
    :func:`src.calibration.metrics.position_bias`, not by this
    projection.

    Args:
        decision: A decision value from any label type's vocabulary.

    Returns:
        ``True`` for a positive decision, ``False`` for a negative one,
        ``None`` when the decision asserts nothing on this axis.

    Raises:
        ValueError: The value belongs to no label type's vocabulary.
    """
    if decision in _POSITIVE:
        return True
    if decision in _NEGATIVE:
        return False
    if decision in NON_DECISIONS or decision in {
        PairwisePreferenceDecision.FIRST.value,
        PairwisePreferenceDecision.SECOND.value,
    }:
        return None
    raise ValueError(f"unknown decision value {decision!r}")


class Annotator(StrictContractModel):
    """Who made a decision, pseudonymously, and under which guideline.

    Attributes:
        annotator_id: Opaque pseudonym. Never a name, an email or a
            provider account id; the mapping is a separate record under
            13 §3.1's human-evaluation steward.
        kind: What produced the decision.
        guideline_revision: Which revision of the annotation guide this
            annotator was working from. Carried on the annotator rather
            than only on the set because a campaign that re-trains its
            annotators mid-flight produces two populations, and a report
            that cannot see the split will average them.
    """

    annotator_id: AnnotatorId
    kind: AnnotatorKind
    guideline_revision: SemVer

    @property
    def is_human(self) -> bool:
        """Whether this annotator is a person, for the time budget."""
        return self.kind in HUMAN_ANNOTATOR_KINDS

    @property
    def is_synthetic(self) -> bool:
        """Whether this decision is a construction fact about a fixture."""
        return self.kind is AnnotatorKind.SYNTHETIC_CONSTRUCTION


class CalibrationLabel(StrictContractModel):
    """One reference decision about one blinded item.

    This is the human (or deterministic) side of calibration. A model
    cannot produce one: the validator below refuses
    :attr:`AnnotatorKind.MODEL` by name, and a judge's answer is a
    :class:`JudgeVerdict` instead.

    Attributes:
        label_id: Stable id within its set.
        blinded_item_id: What was labelled, in blinded form. The label
            never carries the real case id, the arm, or the candidate —
            an annotator who can see which arm produced a report is not
            blind, and a label that records the arm makes every later
            reader un-blind too.
        label_type: Which of the four questions was asked.
        decision: A value from that type's vocabulary.
        confidence: The annotator's own category.
        rationale_ref: Reference to the written justification. A ref
            rather than inline prose so a label stays small, so the
            rationale can carry a stricter data class than the label,
            and so deleting a rationale does not destroy the lineage.
        annotator: Who decided, pseudonymously.
        labeled_at: When, RFC 3339 UTC.
        guideline_ref: The exact guideline revision object in force.
        time_spent_seconds: Optional wall-clock the annotator spent.
            Feeds :mod:`src.calibration.estimate`; ``None`` when it was
            not measured, never zero as a stand-in.
    """

    label_id: MemberId
    blinded_item_id: BlindedItemId
    label_type: LabelType
    decision: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    confidence: Confidence
    rationale_ref: ImmutableObjectRef
    annotator: Annotator
    labeled_at: Rfc3339Utc
    guideline_ref: ImmutableObjectRef
    time_spent_seconds: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def decision_is_in_vocabulary_and_annotator_is_not_a_model(self) -> CalibrationLabel:
        if self.decision not in decision_vocabulary(self.label_type):
            raise ValueError(
                f"{self.decision!r} is not a {self.label_type.value} decision; "
                f"expected one of {decision_vocabulary(self.label_type)}"
            )
        if self.annotator.kind not in GROUND_TRUTH_ANNOTATOR_KINDS:
            raise ValueError(
                f"annotator kind {self.annotator.kind.value!r} cannot produce a "
                "calibration label: a model verdict is an instrument reading, not "
                "ground truth (RFC 11 §9.2). Record it as a JudgeVerdict instead."
            )
        return self

    @property
    def outcome(self) -> bool | None:
        """This label's projection onto the pass/fail axis."""
        return binary_outcome(self.decision)


class JudgeVerdict(StrictContractModel):
    """One model judge's reading of one blinded item.

    Deliberately *not* a :class:`CalibrationLabel`. It has no annotator,
    because nobody decided anything; it has a grader profile, a rubric
    name and a rubric version, because what produced it is an instrument
    configuration, and two verdicts from different configurations are
    not comparable (ADR 0070's rule, applied to the judge being
    measured rather than to the campaign measuring it).

    Attributes:
        verdict_id: Stable id within its set.
        blinded_item_id: The same blinded id the reference label carries,
            which is what lets the two be paired without either side
            seeing the case.
        label_type: Which question the judge was asked.
        decision: A value from that type's vocabulary.
        grader_profile_ref: The pinned grader profile.
        rubric_name: Which instrument produced it — ``completeness``,
            ``faithfulness``, ``groundedness``, ``retrieval_recall``.
        rubric_version: That instrument's version, so a recalibration
            trigger (03 §7.7) is detectable from the data.
        presentation_order: For pairwise items, which order the pair was
            shown in. ``None`` for single-item verdicts.
        observed_at: When the verdict was produced.
        basis: ``measured`` for a verdict a real run produced;
            ``hypothesis`` for one a fixture predicts. Every verdict
            checked into this repository today is a hypothesis, and
            :mod:`src.calibration.fixtures` refuses a fixture that
            claims otherwise — no judge has been run.
    """

    verdict_id: MemberId
    blinded_item_id: BlindedItemId
    label_type: LabelType
    decision: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    grader_profile_ref: ImmutableObjectRef
    rubric_name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    rubric_version: SemVer
    presentation_order: Annotated[str, StringConstraints(pattern=r"^(ab|ba)$")] | None = None
    observed_at: Rfc3339Utc
    basis: Annotated[str, StringConstraints(pattern=r"^(measured|hypothesis)$")] = "hypothesis"

    @model_validator(mode="after")
    def decision_is_in_vocabulary(self) -> JudgeVerdict:
        if self.decision not in decision_vocabulary(self.label_type):
            raise ValueError(
                f"{self.decision!r} is not a {self.label_type.value} decision; "
                f"expected one of {decision_vocabulary(self.label_type)}"
            )
        if self.label_type is LabelType.PAIRWISE_PREFERENCE and self.presentation_order is None:
            raise ValueError(
                "a pairwise verdict must record the order it was shown in, or "
                "position bias cannot be measured from it"
            )
        return self

    @property
    def outcome(self) -> bool | None:
        """This verdict's projection onto the pass/fail axis."""
        return binary_outcome(self.decision)


class AdjudicationRule(StrEnum):
    """How an adjudicated outcome was reached.

    The rule is recorded because the outcomes are not interchangeable: a
    unanimous item and an item one expert overrode two reviewers on are
    both "adjudicated", and a report that cannot tell them apart cannot
    tell a clear task from a contested one.
    """

    UNANIMOUS = "unanimous"
    MAJORITY = "majority"
    EXPERT_OVERRIDE = "expert_override"
    GUIDELINE_RULE = "guideline_rule"
    UNRESOLVED = "unresolved"


class AdjudicationRecord(StrictContractModel):
    """Every individual decision, plus the outcome and the rule.

    RFC 11 §9.2 and 12 §16 both name the failure this type exists to
    prevent: a consensus value written over the labels it came from. So
    the decisions are *inside* the record, the record is additive, and
    the validators refuse the shapes that would let a value appear from
    nowhere — a majority that is not a majority, an override without an
    expert, an unresolved item with an answer anyway.

    Attributes:
        adjudication_id: Stable id within its set.
        blinded_item_id: The item every decision is about.
        label_type: The question every decision answers.
        decisions: Every individual label, preserved verbatim.
        adjudicated_decision: The outcome, or ``None`` when the rule is
            ``unresolved``. An unresolved item is reportable and stays
            out of every denominator; it is not a failure to record.
        rule: How the outcome was reached.
        adjudicator: Who adjudicated. Must be a person: a deterministic
            check can produce a label but cannot settle a dispute
            between two people about what a source says.
        adjudicated_at: When.
        rationale_ref: Written justification. Required whenever the
            outcome is not mechanically implied by the decisions —
            override and guideline-rule — because that is exactly the
            case where a reader cannot reconstruct the reasoning.
    """

    adjudication_id: MemberId
    blinded_item_id: BlindedItemId
    label_type: LabelType
    decisions: tuple[CalibrationLabel, ...]
    adjudicated_decision: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None
    rule: AdjudicationRule
    adjudicator: Annotator
    adjudicated_at: Rfc3339Utc
    rationale_ref: ImmutableObjectRef | None = None

    @model_validator(mode="after")
    def lineage_is_complete_and_the_rule_holds(self) -> AdjudicationRecord:
        if len(self.decisions) < 2:
            raise ValueError(
                "an adjudication preserves the decisions it settles; fewer than two "
                "is not a disagreement"
            )
        if any(label.blinded_item_id != self.blinded_item_id for label in self.decisions):
            raise ValueError("every preserved decision must be about this item")
        if any(label.label_type is not self.label_type for label in self.decisions):
            raise ValueError("every preserved decision must answer this label type")
        label_ids = [label.label_id for label in self.decisions]
        if len(set(label_ids)) != len(label_ids):
            raise ValueError("preserved decisions must be distinct labels")
        annotators = [label.annotator.annotator_id for label in self.decisions]
        if len(set(annotators)) != len(annotators):
            raise ValueError("one annotator contributes at most one decision per item")
        if self.adjudicator.kind not in HUMAN_ANNOTATOR_KINDS:
            raise ValueError("only a person may adjudicate a disagreement")

        values = [label.decision for label in self.decisions]
        if self.rule is AdjudicationRule.UNRESOLVED:
            if self.adjudicated_decision is not None:
                raise ValueError("an unresolved adjudication has no outcome")
            return self
        if self.adjudicated_decision is None:
            raise ValueError(f"rule {self.rule.value!r} requires an outcome")
        if self.adjudicated_decision not in decision_vocabulary(self.label_type):
            raise ValueError(
                f"{self.adjudicated_decision!r} is not a {self.label_type.value} decision"
            )
        if self.rule is AdjudicationRule.UNANIMOUS:
            if len(set(values)) != 1 or self.adjudicated_decision != values[0]:
                raise ValueError("a unanimous outcome must be the value everyone chose")
        elif self.rule is AdjudicationRule.MAJORITY:
            count = values.count(self.adjudicated_decision)
            if count * 2 <= len(values):
                raise ValueError(
                    f"{self.adjudicated_decision!r} has {count} of {len(values)} "
                    "decisions, which is not a strict majority"
                )
        elif self.rule is AdjudicationRule.EXPERT_OVERRIDE:
            if self.adjudicator.kind is not AnnotatorKind.HUMAN_EXPERT:
                raise ValueError("an expert override requires an expert adjudicator")
            if self.rationale_ref is None:
                raise ValueError("an expert override requires a written rationale")
        elif self.rule is AdjudicationRule.GUIDELINE_RULE and self.rationale_ref is None:
            raise ValueError(
                "a guideline-rule outcome must name the clause it applied"
            )
        return self

    @property
    def unanimous(self) -> bool:
        """Whether every preserved decision agreed."""
        return len({label.decision for label in self.decisions}) == 1


class LabelledItem(StrictContractModel):
    """One blinded item, its individual labels, and its adjudication.

    The unit the metrics are computed over. Its most important behaviour
    is a refusal: when annotators disagree and nobody has adjudicated,
    :attr:`resolved_decision` is ``None``. Two labels and a majority
    function would produce a number, and that number would be the
    consensus overwrite RFC 11 §9.2 forbids wearing a different hat.

    Attributes:
        blinded_item_id: The item.
        label_type: The question.
        slice_tags: Which task and failure slices this item belongs to,
            assigned before any candidate outcome was seen (07 §8).
        labels: Every individual decision.
        adjudication: The adjudication, when one exists.
    """

    blinded_item_id: BlindedItemId
    label_type: LabelType
    slice_tags: tuple[SliceTag, ...] = ()
    labels: tuple[CalibrationLabel, ...]
    adjudication: AdjudicationRecord | None = None

    @model_validator(mode="after")
    def labels_and_adjudication_describe_the_same_item(self) -> LabelledItem:
        if not self.labels:
            raise ValueError("a labelled item carries at least one decision")
        if any(label.blinded_item_id != self.blinded_item_id for label in self.labels):
            raise ValueError("every label must be about this item")
        if any(label.label_type is not self.label_type for label in self.labels):
            raise ValueError("every label must answer this item's label type")
        ids = [label.label_id for label in self.labels]
        if len(set(ids)) != len(ids):
            raise ValueError("label ids must be unique within an item")
        if len(set(self.slice_tags)) != len(self.slice_tags):
            raise ValueError("slice tags must be unique")
        if self.adjudication is not None:
            if self.adjudication.blinded_item_id != self.blinded_item_id:
                raise ValueError("the adjudication must be about this item")
            if self.adjudication.label_type is not self.label_type:
                raise ValueError("the adjudication must answer this label type")
            preserved = {label.label_id for label in self.adjudication.decisions}
            if preserved != set(ids):
                raise ValueError(
                    "an adjudication must preserve exactly this item's decisions; "
                    f"missing {sorted(set(ids) - preserved)}, "
                    f"unexpected {sorted(preserved - set(ids))}"
                )
        return self

    @property
    def agreement_state(self) -> AgreementState:
        """W02's agreement vocabulary, derived rather than stored.

        Returns one of ``unreviewed``, ``agreed``, ``disputed`` or
        ``adjudicated``. Derived because a stored state can disagree with
        the labels beneath it, and the labels are the evidence.
        """
        if self.adjudication is not None:
            return "adjudicated"
        if len(self.labels) == 1:
            return "unreviewed"
        if len({label.decision for label in self.labels}) == 1:
            return "agreed"
        return "disputed"

    @property
    def resolved_decision(self) -> str | None:
        """The reference decision, or ``None`` when there is not one.

        ``None`` in three cases, and each is a real state rather than a
        missing value: a single unreviewed label (nobody has confirmed
        it), a disagreement with no adjudication (nobody has settled it),
        and an adjudication whose rule is ``unresolved`` (somebody
        looked and escalated it).
        """
        if self.adjudication is not None:
            return self.adjudication.adjudicated_decision
        if len(self.labels) == 1:
            return None
        decisions = {label.decision for label in self.labels}
        return decisions.pop() if len(decisions) == 1 else None

    @property
    def resolved_outcome(self) -> bool | None:
        """The reference decision projected onto the pass/fail axis."""
        decision = self.resolved_decision
        return None if decision is None else binary_outcome(decision)

    @property
    def human_seconds(self) -> int | None:
        """Total measured annotator time, or ``None`` if unmeasured.

        ``None`` rather than a partial sum: adding the two labels that
        recorded a duration and ignoring the third produces a number that
        looks like a measurement and is not one.
        """
        durations = [label.time_spent_seconds for label in self.labels]
        if any(value is None for value in durations):
            return None
        return sum(value for value in durations if value is not None)


def registry_label_records(
    item: LabelledItem,
    *,
    target_ref: ImmutableObjectRef,
    value_refs: Mapping[str, ImmutableObjectRef],
    guideline_ref: ImmutableObjectRef,
) -> tuple[LabelRecord, ...]:
    """Project one labelled item into W02 `LabelRecord` objects.

    One record per individual decision, plus one for the adjudicated
    outcome when there is one. The adjudicated record does **not** set
    ``supersedes_ref``: adjudication adds a record, it does not replace
    the ones it settled, and pointing supersession at them would encode
    exactly the overwrite RFC 11 §9.2 forbids. Supersession stays
    reserved for a corrected label — a different event, with a different
    meaning.

    Args:
        item: The labelled item.
        target_ref: The registry object the labels are about, normally
            the calibration `task_case`.
        value_refs: Decision value to the content object that holds it.
            The registry stores label *values* by reference (RFC 11
            §9.2, and W06's finding that a reference answer is bound by
            ``value_ref`` digest), so every decision this item uses must
            appear here.
        guideline_ref: The annotation guide revision in force.

    Returns:
        The records, individual decisions first in label-id order, the
        adjudicated outcome last.

    Raises:
        KeyError: A decision has no content object in `value_refs`.
    """
    individual_state: AgreementState = item.agreement_state
    records = [
        LabelRecord(
            label_id=label.label_id,
            target_ref=target_ref,
            label_type=f"{label.label_type.value}.{label.annotator.kind.value}",
            value_ref=value_refs[label.decision],
            evidence_refs=(label.rationale_ref,),
            annotator_id=label.annotator.annotator_id,
            guideline_ref=guideline_ref,
            labeled_at=label.labeled_at,
            agreement_state=individual_state,
            supersedes_ref=None,
        )
        for label in sorted(item.labels, key=lambda label: label.label_id)
    ]
    adjudication = item.adjudication
    if adjudication is not None and adjudication.adjudicated_decision is not None:
        records.append(
            LabelRecord(
                label_id=adjudication.adjudication_id,
                target_ref=target_ref,
                label_type=f"{adjudication.label_type.value}.adjudicated",
                value_ref=value_refs[adjudication.adjudicated_decision],
                evidence_refs=(
                    () if adjudication.rationale_ref is None else (adjudication.rationale_ref,)
                ),
                annotator_id=adjudication.adjudicator.annotator_id,
                guideline_ref=guideline_ref,
                labeled_at=adjudication.adjudicated_at,
                agreement_state="adjudicated",
                supersedes_ref=None,
            )
        )
    return tuple(records)


def resolved_pairs(
    items: Iterable[LabelledItem], verdicts: Iterable[JudgeVerdict]
) -> tuple[tuple[str, bool | None, bool | None], ...]:
    """Match reference outcomes with judge outcomes by blinded id.

    The same decision `src.eval.stats.pair_binary_outcomes` makes for two
    arms, made once for the two *sides* of calibration: an item only one
    side decided is neither agreement nor disagreement. It is returned
    with a ``None`` on the missing side so the caller counts it rather
    than losing it in an intersection.

    Args:
        items: Labelled items, at most one per blinded id.
        verdicts: Judge verdicts, at most one per blinded id. Pairwise
            verdicts are excluded — a pairwise reading has two orders and
            no pass/fail axis, and belongs to
            :func:`src.calibration.metrics.position_bias`.

    Returns:
        ``(blinded_item_id, reference_outcome, judge_outcome)`` sorted by
        id, over the union of both sides.

    Raises:
        ValueError: Either side has two entries for one blinded id.
    """
    reference: dict[str, bool | None] = {}
    for item in items:
        if item.blinded_item_id in reference:
            raise ValueError(f"two labelled items for {item.blinded_item_id}")
        reference[item.blinded_item_id] = item.resolved_outcome
    judged: dict[str, bool | None] = {}
    for verdict in verdicts:
        if verdict.label_type is LabelType.PAIRWISE_PREFERENCE:
            continue
        if verdict.blinded_item_id in judged:
            raise ValueError(f"two judge verdicts for {verdict.blinded_item_id}")
        judged[verdict.blinded_item_id] = verdict.outcome
    return tuple(
        (item_id, reference.get(item_id), judged.get(item_id))
        for item_id in sorted(set(reference) | set(judged))
    )


def campaign_eligible(items: Sequence[LabelledItem]) -> tuple[str, ...]:
    """Return the items that may **not** count toward AE-004's set.

    AE-004 asks for "a small expert-adjudicated set of claims, citations,
    coverage decisions, and paired reports". A synthetic item whose
    reference is a construction fact is none of those things: it proves
    the pipeline runs and it proves a specific failure mode is
    expressible, and it says nothing about whether a judge agrees with an
    expert on a real report.

    The function returns the *disqualified* ids rather than the eligible
    ones on purpose. A caller that wants a count gets it either way; a
    caller that wants to print what is wrong gets the list, and an empty
    return reads as "nothing is disqualified" rather than as an
    accidental empty filter.

    Args:
        items: The labelled items.

    Returns:
        Blinded ids whose reference decision rests on a synthetic
        construction fact or a deterministic check, sorted.
    """
    return tuple(
        sorted(
            item.blinded_item_id
            for item in items
            if any(not label.annotator.is_human for label in item.labels)
        )
    )


def human_annotator_ids(items: Sequence[LabelledItem]) -> tuple[str, ...]:
    """Every distinct human annotator that contributed, sorted."""
    return tuple(
        sorted(
            {
                label.annotator.annotator_id
                for item in items
                for label in item.labels
                if label.annotator.is_human
            }
        )
    )
