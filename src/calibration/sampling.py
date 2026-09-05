"""How many labelled items each slice needs, and what 20 queries buy.

This module answers the sizing question twice, because AE-004 and the
first policy experiment ask different ones and conflating them is how a
calibration set ends up either unaffordable or meaningless.

**The judge question is precision.** "Can this judge gate a release?"
is a question about *bounds*: is the false-pass rate below the ceiling,
and how wide is the interval around it. That is
:func:`items_for_precision` and :func:`items_to_bound_below`, both
searching :func:`src.eval.stats.wilson_interval` rather than quoting a
normal-approximation formula that is wrong at exactly this n.

**The campaign question is separation.** "Is arm B better than arm A?"
is a question about *differences*, and 07 §8 fixes the method: paired
over queries, repeats nested inside. That is
:func:`src.eval.stats.mcnemar_required_pairs` and
:func:`~src.eval.stats.unpaired_required_per_arm`, called here rather
than reimplemented, so the numbers in the protocol document are
reproduced by a test instead of asserted by a paragraph.

**And the answer to both, at this repository's N, is "not with twenty
queries".** :func:`noise_floor` computes it rather than claiming it: on
20 paired items the smallest difference reaching significance at all is
20 points, and the smallest detectable at 80% power is 35. A
five-point move needs 77 pairs to be significant and 155 to be detected;
906 items per arm without pairing. Those four numbers are the honest
frame for every slice target below — a per-slice gate on a 20-query
benchmark is not a strict gate, it is a coin flip with a threshold
printed next to it.

Nothing here reads a clock, a file or a network. Every function is a
pure computation over the estimators ADR 0071 already owns.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import Annotated, Final, NamedTuple

from pydantic import Field, StringConstraints, model_validator

from src.calibration.labels import LabelledItem
from src.contracts.kernel import StrictContractModel
from src.eval.stats import (
    DEFAULT_CONFIDENCE,
    mcnemar_required_pairs,
    unpaired_required_per_arm,
    wilson_interval,
)

#: Largest sample size the two search helpers will consider before
#: giving up. A cap rather than an unbounded loop: an impossible request
#: — a half-width of 0.001 on a rate near 0.5 — should return a refusal
#: a caller can print, not spin.
MAX_SEARCH_N: Final[int] = 20_000

#: The benchmark that exists today: 20 research queries (07 §5).
#: Everything this module says about a noise floor is said about this
#: number, and it is a constant here so the claim moves when the
#: benchmark does.
CURRENT_BENCHMARK_QUERIES: Final[int] = 20


class SliceAxis(StrEnum):
    """The five task-slice axes 07 §8 requires a campaign to report."""

    RETRIEVAL_VS_SYNTHESIS = "retrieval_vs_synthesis"
    STRAIGHTFORWARD_VS_AMBIGUOUS = "straightforward_vs_ambiguous"
    EVIDENCE_DENSITY = "evidence_density"
    CONTRADICTION_PRESENT = "contradiction_present"
    BASELINE_DIFFICULTY = "baseline_difficulty"


class SliceSpec(StrictContractModel):
    """One reportable slice, and the rule that assigns items to it.

    Attributes:
        slice_id: Stable tag, carried on a `TaskCase` and on a
            :class:`~src.calibration.labels.LabelledItem`.
        axis: Which of 07 §8's axes this is a level of.
        level: The level's short name.
        definition: What the slice means, in one sentence.
        assignment_rule: How an item is assigned to it. 07 §8 requires
            assignment "without looking at candidate outcomes", so the
            rule names the input it reads — the case, the source set,
            the rubric — and never a score.
        assigned_from_candidate_outcomes: Fixed ``False``. A field
            rather than a comment so the guarantee appears in the
            serialized plan a reviewer reads.
    """

    slice_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
    axis: SliceAxis
    level: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    definition: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    assignment_rule: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    assigned_from_candidate_outcomes: bool = False

    @model_validator(mode="after")
    def assignment_never_reads_an_outcome(self) -> SliceSpec:
        if self.assigned_from_candidate_outcomes:
            raise ValueError(
                "slice membership assigned from candidate outcomes is not a slice, "
                "it is a result (07 §8)"
            )
        return self


#: The ten task slices — five axes, two levels each — that 07 §8 names as
#: the minimum a campaign reports. Two levels rather than three on every
#: axis is a sizing decision: at the item counts below, a third level
#: buys a third interval too wide to read.
TASK_SLICES: Final[tuple[SliceSpec, ...]] = (
    SliceSpec(
        slice_id="retrieval-heavy",
        axis=SliceAxis.RETRIEVAL_VS_SYNTHESIS,
        level="retrieval_heavy",
        definition="The work is mostly finding the right sources; once found, the answer is short.",
        assignment_rule="Assigned from the case objective and its expected-topic breadth, before any run.",
    ),
    SliceSpec(
        slice_id="synthesis-heavy",
        axis=SliceAxis.RETRIEVAL_VS_SYNTHESIS,
        level="synthesis_heavy",
        definition="The sources are easy to find; the work is reconciling and organising them.",
        assignment_rule="Assigned from the case objective and its expected-topic breadth, before any run.",
    ),
    SliceSpec(
        slice_id="straightforward",
        axis=SliceAxis.STRAIGHTFORWARD_VS_AMBIGUOUS,
        level="straightforward",
        definition="The question has one reading and one shape of answer.",
        assignment_rule="Assigned by two annotators from the case text alone; disagreement escalates.",
    ),
    SliceSpec(
        slice_id="ambiguous-comparative",
        axis=SliceAxis.STRAIGHTFORWARD_VS_AMBIGUOUS,
        level="ambiguous",
        definition="The question is comparative or under-specified and needs a stated interpretation.",
        assignment_rule="Assigned by two annotators from the case text alone; disagreement escalates.",
    ),
    SliceSpec(
        slice_id="evidence-rich",
        axis=SliceAxis.EVIDENCE_DENSITY,
        level="evidence_rich",
        definition="The frozen source snapshot contains ample admissible evidence for the rubric.",
        assignment_rule="Assigned by counting admissible passages in the source snapshot, before any run.",
    ),
    SliceSpec(
        slice_id="evidence-sparse",
        axis=SliceAxis.EVIDENCE_DENSITY,
        level="evidence_sparse",
        definition="The snapshot supports part of the rubric; an honest answer must abstain somewhere.",
        assignment_rule="Assigned by counting admissible passages in the source snapshot, before any run.",
    ),
    SliceSpec(
        slice_id="contradiction-present",
        axis=SliceAxis.CONTRADICTION_PRESENT,
        level="present",
        definition="The sources disagree with each other on a claim the rubric asks about.",
        assignment_rule="Assigned by an annotator reading the snapshot pair, before any run.",
    ),
    SliceSpec(
        slice_id="contradiction-absent",
        axis=SliceAxis.CONTRADICTION_PRESENT,
        level="absent",
        definition="The sources agree, or do not overlap on any rubric claim.",
        assignment_rule="Assigned by an annotator reading the snapshot pair, before any run.",
    ),
    SliceSpec(
        slice_id="baseline-easy",
        axis=SliceAxis.BASELINE_DIFFICULTY,
        level="easy",
        definition="The frozen control arm's observed rubric success on this case is above the median.",
        assignment_rule="Assigned from the *baseline* arm's recorded results only, and frozen before any candidate runs (07 §8).",
    ),
    SliceSpec(
        slice_id="baseline-hard",
        axis=SliceAxis.BASELINE_DIFFICULTY,
        level="hard",
        definition="The frozen control arm's observed rubric success on this case is at or below the median.",
        assignment_rule="Assigned from the *baseline* arm's recorded results only, and frozen before any candidate runs (07 §8).",
    ),
)

#: 03 §8's failure taxonomy, verbatim in meaning and slugged for use as
#: a tag. These are a **stratification for reporting**, not a sizing
#: axis: ten task slices times thirteen classes is 130 cells, and a
#: calibration set that powered every cell would need tens of thousands
#: of expert judgements. The protocol document says which of the two
#: each number is.
FAILURE_CLASSES: Final[tuple[str, ...]] = (
    "task-understanding",
    "planning-decomposition",
    "retrieval-miss",
    "source-quality-freshness-miss",
    "parsing-chunking-ranking",
    "evidence-to-claim-reasoning",
    "synthesis-organisation",
    "citation-provenance",
    "verification-false-pass-or-false-fail",
    "tool-runtime-failure",
    "budget-timeout-premature-stop",
    "safety-policy-refusal",
    "human-interface-failure",
)


def items_for_precision(
    *,
    expected_rate: float,
    half_width: float,
    confidence: float = DEFAULT_CONFIDENCE,
) -> int:
    """Smallest n whose Wilson half-width at `expected_rate` is ≤ target.

    Found by search rather than by the textbook `n = z²p(1-p)/w²`,
    because that formula is the Wald interval's, and the Wald interval is
    the one ADR 0071 refuses: its coverage collapses near 0 and 1, which
    is exactly where a false-pass rate lives. Searching the estimator the
    report will actually print keeps the sizing and the reporting on the
    same instrument.

    The successes at each n are `round(expected_rate * n)`, so the
    returned n is the smallest at which a rate *near* the expectation is
    that precise. A campaign that observes a different rate gets a
    different width; that is a property of the data, and
    :func:`items_to_bound_below` is the version to use when the question
    is a ceiling rather than a width.

    Args:
        expected_rate: The rate the campaign expects to observe, in
            [0, 1]. A planning input, never a result.
        half_width: Target half-width of the two-sided interval.
        confidence: Two-sided confidence level.

    Returns:
        Items required.

    Raises:
        ValueError: An input is out of range, or no n at or below
            :data:`MAX_SEARCH_N` reaches the target.
    """
    if not 0.0 <= expected_rate <= 1.0:
        raise ValueError(f"expected_rate must be in [0, 1], got {expected_rate}")
    if not 0.0 < half_width < 1.0:
        raise ValueError(f"half_width must be in (0, 1), got {half_width}")
    for n in range(2, MAX_SEARCH_N + 1):
        interval = wilson_interval(round(expected_rate * n), n, confidence=confidence)
        if interval.width / 2.0 <= half_width:
            return n
    raise ValueError(
        f"no sample size at or below {MAX_SEARCH_N} reaches a half-width of "
        f"{half_width} at a rate of {expected_rate}"
    )


def items_to_bound_below(
    *,
    observed_rate: float,
    ceiling: float,
    confidence: float = DEFAULT_CONFIDENCE,
) -> int:
    """Smallest n whose Wilson upper bound at `observed_rate` is ≤ ceiling.

    The gate's own sizing question. :func:`src.calibration.metrics.decide`
    compares the *upper* bound of the false-pass interval against a
    declared ceiling, so "how many items do we need" means "how many
    before an observation this good can clear that ceiling" — which is a
    one-sided question, and a half-width answer to it is off by the
    distance between a width and a bound.

    At ``observed_rate=0.0`` this reproduces the rule of three:
    :func:`src.eval.stats.rule_of_three` puts the 95% upper bound after
    zero failures at ``3/n``, so a 10% ceiling needs about 30 clean
    items, and the exact Wilson answer here is 35.

    Args:
        observed_rate: The rate the campaign expects to observe.
        ceiling: The declared maximum the upper bound must clear.
        confidence: Two-sided confidence level.

    Returns:
        Items required.

    Raises:
        ValueError: An input is out of range, the observed rate is not
            below the ceiling, or no n at or below :data:`MAX_SEARCH_N`
            reaches it.
    """
    if not 0.0 <= observed_rate <= 1.0:
        raise ValueError(f"observed_rate must be in [0, 1], got {observed_rate}")
    if not 0.0 < ceiling < 1.0:
        raise ValueError(f"ceiling must be in (0, 1), got {ceiling}")
    if observed_rate >= ceiling:
        raise ValueError(
            f"an observed rate of {observed_rate} never bounds below {ceiling}; "
            "no sample size fixes a rate that is already over the ceiling"
        )
    for n in range(2, MAX_SEARCH_N + 1):
        if wilson_interval(round(observed_rate * n), n, confidence=confidence).high <= ceiling:
            return n
    raise ValueError(
        f"no sample size at or below {MAX_SEARCH_N} bounds {observed_rate} below {ceiling}"
    )


class NoiseFloor(NamedTuple):
    """What a paired comparison of `pairs` items can and cannot resolve.

    Attributes:
        pairs: Paired items available.
        smallest_significant_delta: Smallest difference that reaches
            significance at all — McNemar at 50% power, the α-only
            figure. Below this, no result is a result.
        smallest_detectable_delta: Smallest difference detectable at 80%
            power. Between the two figures a real effect is more likely
            to be missed than found.
        pairs_for_five_points: Pairs needed for a 5-point move to reach
            significance.
        powered_pairs_for_five_points: Pairs needed for a 5-point move at
            80% power.
        unpaired_for_five_points: Items **per arm** for the same move
            without pairing. The ratio against the previous field is the
            argument for scoring both arms on the same items.
    """

    pairs: int
    smallest_significant_delta: float
    smallest_detectable_delta: float
    pairs_for_five_points: int
    powered_pairs_for_five_points: int
    unpaired_for_five_points: int

    def statement(self) -> str:
        """One paragraph a report can print unchanged."""
        return (
            f"**Noise floor at {self.pairs} paired items.** The smallest difference "
            f"that reaches significance at all is "
            f"{self.smallest_significant_delta:.0%}; the smallest detectable at 80% "
            f"power is {self.smallest_detectable_delta:.0%}. A 5-point move needs "
            f"{self.pairs_for_five_points} pairs to be significant, "
            f"{self.powered_pairs_for_five_points} to be detected, and about "
            f"{self.unpaired_for_five_points} items per arm without pairing. A "
            f"per-slice gate on {self.pairs} items is therefore a threshold printed "
            f"beside a coin flip, and every slice number below is a diagnostic."
        )


def noise_floor(
    pairs: int = CURRENT_BENCHMARK_QUERIES, *, baseline_rate: float = 0.80
) -> NoiseFloor:
    """Compute what a paired comparison of `pairs` items can resolve.

    The two "smallest delta" figures are found by scanning percentage
    points from 1 to 100 and taking the first whose required-pairs count
    fits in the sample. A percentage point is the resolution a report
    prints at, so a finer search would return a number with digits the
    reader is entitled to ignore.

    Discordance is set equal to the delta at each step — the lowest
    discordance that can produce a difference that size, which is the
    same convention :func:`src.eval.stats.power_statement` uses and the
    one that reproduces 02-STANDARDS §2.3's published 77.

    Args:
        pairs: Paired items available.
        baseline_rate: The rate the unpaired comparison is measured
            against.

    Returns:
        The floor.

    Raises:
        ValueError: `pairs` is not positive.
    """
    if pairs <= 0:
        raise ValueError(f"pairs must be positive, got {pairs}")

    def smallest(power: float) -> float:
        for percent in range(1, 101):
            delta = percent / 100.0
            if mcnemar_required_pairs(delta=delta, discordance=delta, power=power) <= pairs:
                return delta
        return 1.0

    return NoiseFloor(
        pairs=pairs,
        smallest_significant_delta=smallest(0.5),
        smallest_detectable_delta=smallest(0.8),
        pairs_for_five_points=mcnemar_required_pairs(delta=0.05, discordance=0.05, power=0.5),
        powered_pairs_for_five_points=mcnemar_required_pairs(
            delta=0.05, discordance=0.05, power=0.8
        ),
        unpaired_for_five_points=unpaired_required_per_arm(
            baseline_rate=baseline_rate, delta=0.05
        ),
    )


class SliceRequirement(NamedTuple):
    """What one slice needs, under both sizing questions.

    Attributes:
        slice_id: The slice.
        precision_items: Labelled items for a per-slice false-pass
            interval of the requested half-width — the judge question.
        bound_items: Labelled items for the per-slice upper bound to
            clear the ceiling — the gate question.
        significance_pairs: Paired episodes for a 5-point arm difference
            to reach significance on this slice — the campaign question.
        powered_pairs: The same at 80% power.
        unpaired_per_arm: The same without pairing.
    """

    slice_id: str
    precision_items: int
    bound_items: int
    significance_pairs: int
    powered_pairs: int
    unpaired_per_arm: int


def slice_requirements(
    slices: Sequence[SliceSpec] = TASK_SLICES,
    *,
    expected_false_pass: float = 0.10,
    half_width: float = 0.10,
    ceiling: float = 0.10,
    bound_from_rate: float = 0.02,
    delta: float = 0.05,
    baseline_rate: float = 0.80,
) -> tuple[SliceRequirement, ...]:
    """Derive each slice's item counts from `src/eval/stats.py`.

    Every slice gets the same numbers because the sizing inputs are the
    same for all of them — this is deliberate. Allocating more items to
    a slice because it "looks harder" is allocating from a prior, and 07
    §8 requires slice membership to be fixed before outcomes are seen;
    the same rule applied to slice *size* keeps the design honest. A
    campaign that later observes a much higher rate on one slice may
    re-size it, and that is a new plan revision with a recorded reason.

    Args:
        slices: The slices to size.
        expected_false_pass: The false-pass rate the plan expects.
        half_width: Target half-width for a per-slice interval.
        ceiling: The declared false-pass ceiling the gate compares
            against.
        bound_from_rate: The observed rate the bound sizing assumes.
        delta: The arm difference the campaign wants to detect.
        baseline_rate: The control arm's assumed success rate.

    Returns:
        One requirement per slice, in the order given.
    """
    precision = items_for_precision(expected_rate=expected_false_pass, half_width=half_width)
    bound = items_to_bound_below(observed_rate=bound_from_rate, ceiling=ceiling)
    significance = mcnemar_required_pairs(delta=delta, discordance=delta, power=0.5)
    powered = mcnemar_required_pairs(delta=delta, discordance=delta, power=0.8)
    unpaired = unpaired_required_per_arm(baseline_rate=baseline_rate, delta=delta)
    return tuple(
        SliceRequirement(
            slice_id=spec.slice_id,
            precision_items=precision,
            bound_items=bound,
            significance_pairs=significance,
            powered_pairs=powered,
            unpaired_per_arm=unpaired,
        )
        for spec in slices
    )


class SamplingPlan(StrictContractModel):
    """A sized, sliced calibration set, with its own honesty attached.

    Attributes:
        plan_id: Stable id.
        revision: Semantic revision.
        slices: The slices items are drawn across.
        failure_classes: The reporting stratification (03 §8). Not a
            sizing axis; see the module docstring.
        items_per_slice: Target labelled items in each slice.
        whole_set_items: Target for the whole set. Normally smaller than
            ``len(slices) * items_per_slice`` when slices overlap — one
            case is retrieval-heavy *and* evidence-sparse *and*
            baseline-hard — which is why both numbers are recorded and
            neither is derived from the other.
        expected_false_pass: The planning rate the sizes came from.
        half_width: The per-slice interval half-width the sizes buy.
        ceiling: The declared false-pass ceiling.
        pilot_items: Items in the zero-cost synthetic pilot that exists
            today. Recorded so the plan states its own distance from
            being run.
    """

    plan_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
    revision: str
    slices: tuple[SliceSpec, ...]
    failure_classes: tuple[str, ...]
    items_per_slice: Annotated[int, Field(ge=1)]
    whole_set_items: Annotated[int, Field(ge=1)]
    expected_false_pass: Annotated[float, Field(ge=0.0, le=1.0)]
    half_width: Annotated[float, Field(gt=0.0, lt=1.0)]
    ceiling: Annotated[float, Field(gt=0.0, lt=1.0)]
    pilot_items: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def slices_are_unique_and_the_pilot_is_smaller(self) -> SamplingPlan:
        ids = [spec.slice_id for spec in self.slices]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("slice ids must be non-empty and unique")
        if len(set(self.failure_classes)) != len(self.failure_classes):
            raise ValueError("failure classes must be unique")
        if self.pilot_items >= self.whole_set_items:
            raise ValueError(
                "the synthetic pilot must be smaller than the labelled set it is a "
                "pilot for; a pilot the size of the campaign is the campaign"
            )
        return self

    @property
    def upper_bound_items(self) -> int:
        """Items if no case belonged to two slices — the pessimistic total."""
        return len(self.slices) * self.items_per_slice


def standard_plan(
    *,
    plan_id: str = "judge-calibration-sampling-v1",
    revision: str = "1.0.0",
    expected_false_pass: float = 0.10,
    half_width: float = 0.10,
    ceiling: float = 0.10,
    pilot_items: int,
) -> SamplingPlan:
    """Build the plan the protocol document publishes.

    Sizes come from :func:`items_for_precision` and
    :func:`items_to_bound_below` rather than from constants, so editing a
    planning input moves the document and the tests together.

    Args:
        plan_id: Stable id.
        revision: Semantic revision.
        expected_false_pass: Planning rate for the per-slice interval.
        half_width: Target per-slice half-width.
        ceiling: Declared false-pass ceiling.
        pilot_items: Items in the synthetic pilot that exists today.

    Returns:
        The plan.
    """
    per_slice = items_for_precision(expected_rate=expected_false_pass, half_width=half_width)
    whole = items_for_precision(expected_rate=expected_false_pass, half_width=half_width / 2.0)
    return SamplingPlan(
        plan_id=plan_id,
        revision=revision,
        slices=TASK_SLICES,
        failure_classes=FAILURE_CLASSES,
        items_per_slice=per_slice,
        whole_set_items=whole,
        expected_false_pass=expected_false_pass,
        half_width=half_width,
        ceiling=ceiling,
        pilot_items=pilot_items,
    )


class SliceObservation(NamedTuple):
    """Observed coverage of one slice.

    Attributes:
        slice_id: The slice.
        labelled: Items with at least one label.
        resolved: Items with a reference decision — agreed or
            adjudicated. The denominator every metric actually uses, and
            normally smaller than `labelled`.
        target: The plan's target.
        shortfall: `target - resolved`, floored at zero.
    """

    slice_id: str
    labelled: int
    resolved: int
    target: int
    shortfall: int

    @property
    def unmeasured(self) -> bool:
        """Whether this slice has no resolved item at all.

        The state that must never be reported as a covered slice: a rate
        over zero items is not a small sample, it is no sample, and 03
        §7.4 asks for false-pass and abstention *by task slice*.
        """
        return self.resolved == 0


def observe_coverage(
    plan: SamplingPlan, items: Iterable[LabelledItem]
) -> tuple[SliceObservation, ...]:
    """Count what each planned slice actually has.

    Items carrying a tag the plan does not declare are ignored here and
    reported by :func:`untracked_tags`; silently folding them into a
    total would let an unplanned slice pad a planned one's count.

    Args:
        plan: The sampling plan.
        items: Labelled items, each tagged with its slices.

    Returns:
        One observation per planned slice, in plan order.
    """
    materialized = list(items)
    return tuple(
        SliceObservation(
            slice_id=spec.slice_id,
            labelled=sum(1 for item in materialized if spec.slice_id in item.slice_tags),
            resolved=(
                resolved := sum(
                    1
                    for item in materialized
                    if spec.slice_id in item.slice_tags and item.resolved_decision is not None
                )
            ),
            target=plan.items_per_slice,
            shortfall=max(0, plan.items_per_slice - resolved),
        )
        for spec in plan.slices
    )


def untracked_tags(plan: SamplingPlan, items: Iterable[LabelledItem]) -> tuple[str, ...]:
    """Slice tags the items carry that the plan does not declare."""
    declared = {spec.slice_id for spec in plan.slices} | set(plan.failure_classes)
    return tuple(sorted({tag for item in items for tag in item.slice_tags} - declared))
