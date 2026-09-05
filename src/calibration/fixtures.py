"""Deterministic synthetic fixtures for the six adversarial families.

03 §7.5 lists the cases a judge validation must include: plausible
unsupported prose, citation swaps, verbosity, stylistic polish, and
injected instructions in source text. 12 §16 adds contradiction and
honest abstention. This module is the loader and the validator for those
six families, authored as JSON under ``tests/fixtures/calibration/``.

**A stress set is not a calibration set, and the difference is the whole
reason this module refuses to conflate them.** Every case here was
written to trip a judge, so the rates it produces describe *the corpus*.
Pooled with a representative sample they would drag every number down;
reported alone they say "the judge fails 11 of 24 cases we designed to
make it fail", which is a sentence about the fixture author. So each
file declares a :class:`Stratum`, :func:`load_cases` refuses a file that
mixes two, and the protocol document reports the two strata separately
and never averages them.

**Every expected verdict is a hypothesis.** The ``expected_judge_verdict``
of each case is a *prediction* about a failure mode, written before any
judge ran, and :func:`load_cases` refuses a case that claims otherwise.
That refusal is the mechanical form of this work order's central
constraint: no judge has been called, and a fixture asserting a measured
verdict would be the first place that stopped being true.

**The expected outcome cannot lie.** ``expected_outcome`` is checked
against :func:`classify_outcome` on load, so a case cannot claim to be a
false pass while describing a true one. The field is still written out —
a reader of the JSON should see what the case is *for* without running
the classifier in their head.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from src.calibration.blinding import blind_item_id
from src.calibration.labels import (
    Annotator,
    AnnotatorKind,
    CalibrationLabel,
    Confidence,
    JudgeVerdict,
    LabelledItem,
    LabelType,
    binary_outcome,
    decision_vocabulary,
)
from src.calibration.sampling import FAILURE_CLASSES, TASK_SLICES
from src.contracts.kernel import ImmutableObjectRef, StrictContractModel, sha256_digest

#: Repository root, three parents up from ``src/calibration/fixtures.py``.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: Where the authored corpus lives. Under ``tests/`` rather than ``src/``
#: for the reason ADR 0072's safety corpus is: these are fixtures, not
#: shipped data, and nothing in the running product may import them.
FIXTURE_ROOT: Final[Path] = REPO_ROOT / "tests" / "fixtures" / "calibration"

ADVERSARIAL_PATH: Final[Path] = FIXTURE_ROOT / "adversarial_cases.json"
PAIRWISE_PATH: Final[Path] = FIXTURE_ROOT / "pairwise_cases.json"
LABELLED_SET_PATH: Final[Path] = FIXTURE_ROOT / "labelled_set.json"

#: Salt used to blind the fixture corpus. Checked in, and that is fine
#: precisely because it is the *fixture* salt: the corpus it blinds is
#: synthetic and public, so there is nothing to protect. A real campaign
#: draws its own salt and keeps it in an evaluator-only object — see
#: :class:`src.calibration.blinding.BlindingPlan`. Having a visible salt
#: here means the blinded ids in the fixtures are reproducible by anyone
#: reading the tests, which is what a fixture is for.
FIXTURE_SALT: Final[str] = "p0-wo10-fixture-salt"

#: The fixture author, as a pseudonymous annotator of kind
#: ``synthetic_construction``. Not an expert label: see
#: :data:`src.calibration.labels.GROUND_TRUTH_ANNOTATOR_KINDS`.
FIXTURE_ANNOTATOR: Final[Annotator] = Annotator(
    annotator_id="ann-w10author",
    kind=AnnotatorKind.SYNTHETIC_CONSTRUCTION,
    guideline_revision="1.0.0",
)


class Family(StrEnum):
    """The six adversarial families 03 §7.5 and 12 §16 require."""

    UNSUPPORTED_POLISH = "unsupported_polish"
    VERBOSITY = "verbosity"
    CITATION_SWAP = "citation_swap"
    INJECTED_SOURCE_INSTRUCTIONS = "injected_source_instructions"
    CONTRADICTION = "contradiction"
    HONEST_ABSTENTION = "honest_abstention"


class Stratum(StrEnum):
    """Which population a fixture file's cases belong to.

    ``ADVERSARIAL_STRESS`` cases are selected to fail. ``REPRESENTATIVE``
    cases are drawn to look like the benchmark. A rate is only comparable
    within one stratum, and only the representative stratum can size a
    gate.
    """

    ADVERSARIAL_STRESS = "adversarial_stress"
    REPRESENTATIVE = "representative"


class Outcome(StrEnum):
    """What one (reference, judge) pair contributes to the report."""

    TRUE_PASS = "true_pass"
    FALSE_PASS = "false_pass"
    TRUE_FAIL = "true_fail"
    FALSE_FAIL = "false_fail"
    JUDGE_ABSTAINED = "judge_abstained"
    REFERENCE_UNRESOLVED = "reference_unresolved"


def classify_outcome(reference_decision: str, judge_decision: str) -> Outcome:
    """Classify one reference/judge decision pair.

    The single place the four cells and the two non-cells are decided, so
    a fixture, a report and a test cannot disagree about what a false
    pass is.

    Args:
        reference_decision: The reference decision value.
        judge_decision: The judge's decision value.

    Returns:
        The outcome.

    Raises:
        ValueError: Either value belongs to no vocabulary.
    """
    reference = binary_outcome(reference_decision)
    judged = binary_outcome(judge_decision)
    if reference is None:
        return Outcome.REFERENCE_UNRESOLVED
    if judged is None:
        return Outcome.JUDGE_ABSTAINED
    if reference and judged:
        return Outcome.TRUE_PASS
    if reference and not judged:
        return Outcome.FALSE_FAIL
    if not reference and judged:
        return Outcome.FALSE_PASS
    return Outcome.TRUE_FAIL


class CaseMaterial(StrictContractModel):
    """The verbatim text one case shows an annotator and a judge.

    Attributes:
        report_excerpt: What the candidate wrote.
        cited_source: The identifier the excerpt cites, or ``None`` for
            a coverage case that cites nothing.
        source_excerpt: What the cited source actually says. Authored so
            the reference decision is a fact about this text, not an
            opinion about it.
        rubric_item: The rubric item under test, for coverage cases.
    """

    report_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    cited_source: Annotated[str, StringConstraints(min_length=1, max_length=200)] | None = None
    source_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=4000)] | None = None
    rubric_item: Annotated[str, StringConstraints(min_length=1, max_length=400)] | None = None


class CalibrationCase(StrictContractModel):
    """One synthetic adversarial case with its expected results.

    Attributes:
        case_id: Stable id, unique in its file.
        family: Which failure mode it probes.
        label_type: Which question is asked about it.
        slice_tags: Task slices and failure classes it belongs to.
        material: The text.
        expected_reference_decision: What the construction makes true.
        expected_judge_verdict: What a judge is *predicted* to say.
        verdict_basis: Always ``hypothesis`` in this repository.
        expected_outcome: The cell this case is designed to land in,
            checked against :func:`classify_outcome` on load.
        why: One paragraph: what the case is doing and why the predicted
            verdict is the plausible failure rather than a strawman.
    """

    case_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
    family: Family
    label_type: LabelType
    slice_tags: tuple[Annotated[str, StringConstraints(min_length=1, max_length=64)], ...]
    material: CaseMaterial
    expected_reference_decision: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    expected_judge_verdict: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    verdict_basis: Literal["hypothesis"] = "hypothesis"
    expected_outcome: Outcome
    why: Annotated[str, StringConstraints(min_length=1, max_length=1200)]

    @model_validator(mode="after")
    def decisions_are_valid_and_the_outcome_is_derived(self) -> CalibrationCase:
        vocabulary = decision_vocabulary(self.label_type)
        for field, value in (
            ("expected_reference_decision", self.expected_reference_decision),
            ("expected_judge_verdict", self.expected_judge_verdict),
        ):
            if value not in vocabulary:
                raise ValueError(
                    f"{field} {value!r} is not a {self.label_type.value} decision; "
                    f"expected one of {vocabulary}"
                )
        derived = classify_outcome(self.expected_reference_decision, self.expected_judge_verdict)
        if derived is not self.expected_outcome:
            raise ValueError(
                f"{self.case_id}: expected_outcome {self.expected_outcome.value!r} but "
                f"({self.expected_reference_decision!r}, {self.expected_judge_verdict!r}) "
                f"classifies as {derived.value!r}"
            )
        if self.label_type is LabelType.PAIRWISE_PREFERENCE:
            raise ValueError(
                "a pairwise case is presented in two orders and belongs in the "
                "pairwise fixture file"
            )
        unknown = sorted(set(self.slice_tags) - _KNOWN_TAGS)
        if unknown:
            raise ValueError(f"{self.case_id}: undeclared slice tags {unknown}")
        if len(set(self.slice_tags)) != len(self.slice_tags):
            raise ValueError(f"{self.case_id}: slice tags must be unique")
        return self

    @property
    def blinded_item_id(self) -> str:
        """The blinded id this case is addressed by."""
        return blind_item_id(FIXTURE_SALT, self.case_id)


class PairwiseCase(StrictContractModel):
    """One pairwise case, with a predicted verdict in **both** orders.

    Attributes:
        case_id: Stable id.
        slice_tags: Slices it belongs to.
        first_excerpt: The report shown first under ``ab``.
        second_excerpt: The report shown second under ``ab``. Under
            ``ba`` the two are swapped; the judge sees no letters.
        expected_reference_preference: Which *report* an expert is
            predicted to prefer — ``first_excerpt``, ``second_excerpt``
            or ``tie``, named by content rather than by position.
        expected_ab_verdict: Predicted preference by *position* under the
            ``ab`` presentation.
        expected_ba_verdict: The same under ``ba``.
        verdict_basis: Always ``hypothesis``.
        why: What the pair probes.
    """

    case_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
    slice_tags: tuple[Annotated[str, StringConstraints(min_length=1, max_length=64)], ...]
    first_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    second_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    expected_reference_preference: Literal["first_excerpt", "second_excerpt", "tie"]
    expected_ab_verdict: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    expected_ba_verdict: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    verdict_basis: Literal["hypothesis"] = "hypothesis"
    why: Annotated[str, StringConstraints(min_length=1, max_length=1200)]

    @model_validator(mode="after")
    def verdicts_are_positions_in_the_vocabulary(self) -> PairwiseCase:
        vocabulary = decision_vocabulary(LabelType.PAIRWISE_PREFERENCE)
        for field, value in (
            ("expected_ab_verdict", self.expected_ab_verdict),
            ("expected_ba_verdict", self.expected_ba_verdict),
        ):
            if value not in vocabulary:
                raise ValueError(f"{field} {value!r} is not a pairwise decision")
        unknown = sorted(set(self.slice_tags) - _KNOWN_TAGS)
        if unknown:
            raise ValueError(f"{self.case_id}: undeclared slice tags {unknown}")
        return self

    @property
    def blinded_item_id(self) -> str:
        """The blinded id this pair is addressed by."""
        return blind_item_id(FIXTURE_SALT, self.case_id)

    @property
    def position_consistent(self) -> bool:
        """Whether the two orders name the same *report*.

        ``ab``→first and ``ba``→second both name ``first_excerpt``; two
        readings of "first" name two different reports and are the
        signature of a position preference.
        """
        pairs = {(self.expected_ab_verdict, self.expected_ba_verdict)}
        return pairs <= {("first", "second"), ("second", "first"), ("tie", "tie")}


class CaseFile(StrictContractModel):
    """One authored fixture file.

    Attributes:
        schema_version: Fixed.
        stratum: Which population these cases belong to. A file carries
            one; a report never pools two.
        readme: The file's own explanation, carried into the model so it
            cannot be dropped by a reformat.
        cases: The single-item cases.
        pairwise: The pairwise cases.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    stratum: Stratum
    readme: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    cases: tuple[CalibrationCase, ...] = ()
    pairwise: tuple[PairwiseCase, ...] = ()

    @model_validator(mode="after")
    def ids_are_unique_and_the_file_is_not_empty(self) -> CaseFile:
        ids = [case.case_id for case in self.cases] + [case.case_id for case in self.pairwise]
        if not ids:
            raise ValueError("a fixture file carries at least one case")
        if len(set(ids)) != len(ids):
            raise ValueError("case ids must be unique within a file")
        return self


_KNOWN_TAGS: Final[frozenset[str]] = frozenset(
    {spec.slice_id for spec in TASK_SLICES} | set(FAILURE_CLASSES)
)


def _read(path: Path) -> str:
    """Read a fixture file as text.

    Validation goes through ``model_validate_json`` rather than
    ``json.loads`` plus ``model_validate``: these models inherit
    :class:`src.contracts.kernel.StrictContractModel`, whose strict mode
    refuses a Python ``list`` where a ``tuple`` is declared. In JSON
    validation mode a JSON array is the tuple's wire form, which is the
    same route W02's :class:`src.contracts.registry.RegistryEnvelope`
    takes for the same reason.
    """
    return path.read_text(encoding="utf-8")


def load_case_file(path: Path = ADVERSARIAL_PATH) -> CaseFile:
    """Read and validate one authored fixture file.

    Args:
        path: The file.

    Returns:
        The validated file.

    Raises:
        ValueError: The file is invalid, or a case claims a measured
            verdict. Every checked-in verdict is a prediction: see the
            module docstring.
    """
    return CaseFile.model_validate_json(_read(path))


def load_cases(path: Path = ADVERSARIAL_PATH) -> tuple[CalibrationCase, ...]:
    """Read the single-item cases from one fixture file."""
    return load_case_file(path).cases


def load_pairwise(path: Path = PAIRWISE_PATH) -> tuple[PairwiseCase, ...]:
    """Read the pairwise cases from one fixture file."""
    return load_case_file(path).pairwise


def missing_families(cases: Iterable[CalibrationCase]) -> tuple[str, ...]:
    """Families 12 §16 requires that the corpus does not cover."""
    present = {case.family for case in cases}
    return tuple(sorted(family.value for family in Family if family not in present))


def as_labelled_items(
    cases: Sequence[CalibrationCase],
    *,
    rationale_ref: ImmutableObjectRef,
    guideline_ref: ImmutableObjectRef,
    labeled_at: str,
) -> tuple[LabelledItem, ...]:
    """Turn authored cases into labelled items the metrics can read.

    One label per case, from :data:`FIXTURE_ANNOTATOR`, and no
    adjudication: a construction fact has nobody to disagree with. That
    is exactly why :func:`src.calibration.labels.campaign_eligible`
    disqualifies every item this function produces — a set with no
    possible disagreement has no adjudication lineage to inspect, and
    AE-004 is largely about the lineage.

    Args:
        cases: The authored cases.
        rationale_ref: Content object holding the ``why`` text.
        guideline_ref: The annotation guide revision.
        labeled_at: RFC 3339 UTC authoring timestamp, supplied by the
            caller so this module never reads a clock.

    Returns:
        One labelled item per case, in order.
    """
    return tuple(
        LabelledItem(
            blinded_item_id=case.blinded_item_id,
            label_type=case.label_type,
            slice_tags=case.slice_tags,
            labels=(
                CalibrationLabel(
                    label_id=case.case_id,
                    blinded_item_id=case.blinded_item_id,
                    label_type=case.label_type,
                    decision=case.expected_reference_decision,
                    confidence=Confidence.HIGH,
                    rationale_ref=rationale_ref,
                    annotator=FIXTURE_ANNOTATOR,
                    labeled_at=labeled_at,
                    guideline_ref=guideline_ref,
                ),
            ),
            adjudication=None,
        )
        for case in cases
    )


def as_predicted_verdicts(
    cases: Sequence[CalibrationCase],
    *,
    grader_profile_ref: ImmutableObjectRef,
    rubric_name: str,
    rubric_version: str,
    observed_at: str,
) -> tuple[JudgeVerdict, ...]:
    """Turn each case's predicted judge verdict into a `JudgeVerdict`.

    Every verdict carries ``basis="hypothesis"``. Calling this function
    produces a report that :func:`src.calibration.metrics.decide` will
    never PROMOTE, which is the intended and only correct behaviour
    until a judge is actually run.

    Args:
        cases: The authored cases.
        grader_profile_ref: The pinned grader profile.
        rubric_name: The instrument the prediction is about.
        rubric_version: Its version.
        observed_at: RFC 3339 UTC timestamp, supplied by the caller.

    Returns:
        One verdict per case, in order.
    """
    return tuple(
        JudgeVerdict(
            verdict_id=f"{case.case_id}.predicted",
            blinded_item_id=case.blinded_item_id,
            label_type=case.label_type,
            decision=case.expected_judge_verdict,
            grader_profile_ref=grader_profile_ref,
            rubric_name=rubric_name,
            rubric_version=rubric_version,
            observed_at=observed_at,
            basis="hypothesis",
        )
        for case in cases
    )


def as_predicted_pairwise_verdicts(
    cases: Sequence[PairwiseCase],
    *,
    grader_profile_ref: ImmutableObjectRef,
    rubric_name: str,
    rubric_version: str,
    observed_at: str,
) -> tuple[JudgeVerdict, ...]:
    """Turn each pairwise case's two predicted readings into verdicts.

    Two verdicts per case, ``ab`` and ``ba``, which is what
    :func:`src.calibration.metrics.position_bias` needs and what a
    single-order design can never produce.

    Args:
        cases: The authored pairs.
        grader_profile_ref: The pinned grader profile.
        rubric_name: The instrument.
        rubric_version: Its version.
        observed_at: RFC 3339 UTC timestamp.

    Returns:
        Two verdicts per case, ``ab`` first.
    """
    verdicts: list[JudgeVerdict] = []
    for case in cases:
        for order, decision in (("ab", case.expected_ab_verdict), ("ba", case.expected_ba_verdict)):
            verdicts.append(
                JudgeVerdict(
                    verdict_id=f"{case.case_id}.{order}",
                    blinded_item_id=case.blinded_item_id,
                    label_type=LabelType.PAIRWISE_PREFERENCE,
                    decision=decision,
                    grader_profile_ref=grader_profile_ref,
                    rubric_name=rubric_name,
                    rubric_version=rubric_version,
                    presentation_order=order,
                    observed_at=observed_at,
                    basis="hypothesis",
                )
            )
    return tuple(verdicts)


class RationaleContent(StrictContractModel):
    """The written justification one label or adjudication rests on.

    Kept as its own object rather than as a string field on the label for
    the reason RFC 11 §9.2 keeps label values by reference: a rationale
    can carry a stricter data class than the label that points at it (an
    annotator's prose about a learner transcript is learner-sensitive;
    the decision "not covered" is not), and deleting one under 13 §6
    must not destroy the lineage.

    Attributes:
        rationale_id: Stable id.
        text: The justification.
    """

    rationale_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")]
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class GuidelineContent(StrictContractModel):
    """The annotation-guide revision a set of labels was produced under.

    Attributes:
        guideline_id: Stable id.
        revision: Semantic revision. A change here makes labels from
            before and after two populations, which is why
            :class:`src.calibration.labels.Annotator` also carries it.
        summary: What the revision says, in one paragraph. The full guide
            is the protocol document; this is the excerpt an annotator
            worked from.
    """

    guideline_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")]
    revision: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
    summary: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class LabelledSetFile(StrictContractModel):
    """A tiny worked labelled set, with lineage a real campaign produces.

    Unlike the adversarial corpus this file has multiple annotators per
    item, real disagreement, and adjudications — one under each rule,
    including an escalation that resolves to nothing. It exists so the
    metrics have something with lineage to be tested against, and so the
    annotation guide has a worked example of every rule it names.

    Its refs are not decoration. The validator below resolves every
    ``rationale_ref`` and ``guideline_ref`` against the content carried
    in the same file and checks the digest, so a rationale cannot be
    edited without the label that cites it noticing — the same property
    a campaign gets from the registry, demonstrated at fixture scale.

    Attributes:
        schema_version: Fixed.
        readme: The file's explanation.
        guideline: The annotation-guide revision in force.
        rationales: Every rationale the labels cite.
        grader_profile_ref: The profile every verdict in this file
            declares.
        items: The labelled items.
        judge_verdicts: The predicted judge verdicts over the same
            blinded ids.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    readme: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    guideline: GuidelineContent
    rationales: tuple[RationaleContent, ...] = Field(min_length=1)
    grader_profile_ref: ImmutableObjectRef
    items: tuple[LabelledItem, ...] = Field(min_length=1)
    judge_verdicts: tuple[JudgeVerdict, ...] = ()

    @model_validator(mode="after")
    def every_ref_resolves_inside_this_file(self) -> LabelledSetFile:
        known = {item.blinded_item_id for item in self.items}
        unknown = sorted({verdict.blinded_item_id for verdict in self.judge_verdicts} - known)
        if unknown:
            raise ValueError(f"verdicts for items that carry no label: {unknown}")
        ids = [item.blinded_item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("one labelled item per blinded id")

        guideline_ref = ImmutableObjectRef(
            kind="calibration_guideline",
            id=self.guideline.guideline_id,
            revision=self.guideline.revision,
            digest=sha256_digest(self.guideline),
        )
        by_rationale = {
            content.rationale_id: ImmutableObjectRef(
                kind="calibration_rationale",
                id=content.rationale_id,
                revision="1.0.0",
                digest=sha256_digest(content),
            )
            for content in self.rationales
        }
        if len(by_rationale) != len(self.rationales):
            raise ValueError("rationale ids must be unique")

        def check(ref: ImmutableObjectRef, subject: str) -> None:
            expected = by_rationale.get(ref.id)
            if expected is None:
                raise ValueError(f"{subject}: no rationale {ref.id!r} in this file")
            if ref != expected:
                raise ValueError(
                    f"{subject}: rationale {ref.id!r} does not match its content; "
                    f"expected digest {expected.digest}, ref carries {ref.digest}"
                )

        for item in self.items:
            for label in item.labels:
                check(label.rationale_ref, label.label_id)
                if label.guideline_ref != guideline_ref:
                    raise ValueError(
                        f"{label.label_id}: guideline_ref does not match this file's guide"
                    )
            if item.adjudication is not None and item.adjudication.rationale_ref is not None:
                check(item.adjudication.rationale_ref, item.adjudication.adjudication_id)
        for verdict in self.judge_verdicts:
            if verdict.grader_profile_ref != self.grader_profile_ref:
                raise ValueError(
                    f"{verdict.verdict_id}: verdicts must all name this file's grader profile"
                )
        return self


def load_labelled_set(path: Path = LABELLED_SET_PATH) -> LabelledSetFile:
    """Read and validate the worked labelled set."""
    return LabelledSetFile.model_validate_json(_read(path))
