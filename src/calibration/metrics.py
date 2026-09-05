"""Calibration metrics, and the gate that decides if a judge may gate.

AE-004's exit criterion is one sentence: *judge performance is reported
by slice, and unsupported confidence is not used as a release gate*.
This module is both halves — the report, and the refusal.

## The reporting form was fixed before the measurement existed

``docs/eval.md`` §"Judge–human calibration remains unmeasured" wrote down
what this report must contain, and it is not negotiable here:

- **φ / MCC with both positive rates.** For binary verdicts Pearson,
  Spearman, Kendall, φ and MCC are the same statistic, and κ = q·φ is
  uninterpretable without the two positive rates. So :func:`agreement`
  computes φ and carries both rates beside it.
- **Never quote raw agreement.** It overstates chance-corrected
  agreement by 33–41 points: in a 21-judge study, 85% exact match was a
  κ of about 0.48. Raw agreement is computed — a reader wants it — and
  :func:`report_lines` will not print it without φ and both rates on the
  same page. A test asserts that.
- **State how abstentions were counted.** The choice swings measured
  accuracy by 10–34 points on identical verdicts, so
  :class:`AbstentionPolicy` is a required field of every report and
  :func:`agreement_under_each_policy` exists to make the swing visible
  rather than arguable.

## The gate mirrors ADR 0072's

:func:`decide` has the same shape as ``src/eval/safety_suite.decide``,
deliberately, and a test asserts the two :class:`GateDecision` types have
identical fields. Three states, evaluated in a fixed order:

1. **The integrity veto, first and unconditionally.** A model verdict
   counted as ground truth, a blinding breach, an unadjudicated dispute
   counted as agreement, a slice reported with no items in it: these are
   gated at absolute zero. No interval is computed, and ``advisory`` does
   not soften them, because none of them is a statistical claim.
2. **Comparability.** A judge whose rubric version has moved since the
   calibration set was labelled, or a set with fewer resolved items than
   its plan requires: HOLD. A calibration of a different instrument is
   not a calibration of this one.
3. **The measurement**, as Wilson intervals against declared
   thresholds. A bound that clears → PROMOTE; a bound that fails →
   ROLLBACK; an interval straddling its threshold → HOLD.

HOLD is the common answer and the useful one. "This judge's numbers are
diagnostics, not a gate" is a decision a campaign can act on; a
green light computed from eleven items is not.

Pure throughout: no clock, no filesystem, no network, no model. Every
interval comes from :mod:`src.eval.stats` (ADR 0071) rather than a
second implementation of the same formula.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from math import sqrt
from typing import Annotated, Final, Literal, NamedTuple

from pydantic import Field, StringConstraints, model_validator

from src.calibration.labels import (
    JudgeVerdict,
    LabelledItem,
    LabelType,
    PairwisePreferenceDecision,
    resolved_pairs,
)
from src.calibration.sampling import SliceObservation
from src.contracts.kernel import SemVer, StrictContractModel
from src.eval.stats import Interval, small_sample_caveat, wilson_interval


class AbstentionPolicy(StrEnum):
    """How a non-decision is counted in the confusion table.

    ``docs/eval.md``: the choice swings measured accuracy by 10–34 points
    on identical verdicts. It is therefore a declared input, never a
    default buried in an implementation, and every report carries the
    value it used.

    ``EXCLUDED`` is this protocol's recommendation and not its
    assumption: an abstention is the judge declining to assert, and
    counting a decline as a failure punishes the behaviour 07 §7 asks
    for — abstained claims stay visible and do not become passes.
    """

    EXCLUDED = "excluded"
    COUNTED_AS_FAIL = "counted_as_fail"
    COUNTED_AS_PASS = "counted_as_pass"


class ConfusionCounts(NamedTuple):
    """A 2×2 table plus everything the 2×2 could not hold.

    Attributes:
        true_pass: Reference says pass, judge says pass.
        false_pass: Reference says fail, judge says pass. The cell this
            whole work order is about: a judge that passes unsupported
            work is a gate that ships it.
        true_fail: Reference says fail, judge says fail.
        false_fail: Reference says pass, judge says fail. Cheaper than a
            false pass and not free — it is the cell that makes a
            verify-and-repair arm look worse than it is.
        judge_abstained: Judge asserted nothing on an item the reference
            decided.
        reference_unresolved: The reference has no decision — a single
            unreviewed label, an unadjudicated dispute, or an escalated
            item. Never silently dropped: RFC 11 §9.2's disagreement is
            data, and 12 §3.11 keeps null-scored items in denominators.
        unmatched: Items only one side decided at all.
    """

    true_pass: int
    false_pass: int
    true_fail: int
    false_fail: int
    judge_abstained: int
    reference_unresolved: int
    unmatched: int

    @property
    def decided(self) -> int:
        """Items both sides decided — the 2×2's denominator."""
        return self.true_pass + self.false_pass + self.true_fail + self.false_fail

    @property
    def total(self) -> int:
        """Every item seen, decided or not. The published denominator."""
        return (
            self.decided + self.judge_abstained + self.reference_unresolved + self.unmatched
        )


def confusion(
    pairs: Iterable[tuple[str, bool | None, bool | None]],
    *,
    policy: AbstentionPolicy = AbstentionPolicy.EXCLUDED,
) -> ConfusionCounts:
    """Build the confusion table under one declared abstention policy.

    Args:
        pairs: ``(item_id, reference_outcome, judge_outcome)`` triples,
            as :func:`src.calibration.labels.resolved_pairs` returns.
            ``None`` on either side means "asserted nothing".
        policy: How a judge abstention is counted. The reference side is
            never coerced: an item nobody resolved has no truth to
            compare against, so no policy can turn it into a cell.

    Returns:
        The counts.
    """
    true_pass = false_pass = true_fail = false_fail = 0
    abstained = unresolved = unmatched = 0
    for _, reference, judged in pairs:
        if reference is None and judged is None:
            unmatched += 1
            continue
        if reference is None:
            unresolved += 1
            continue
        decision = judged
        if decision is None:
            if policy is AbstentionPolicy.EXCLUDED:
                abstained += 1
                continue
            decision = policy is AbstentionPolicy.COUNTED_AS_PASS
        if reference and decision:
            true_pass += 1
        elif reference and not decision:
            false_fail += 1
        elif not reference and decision:
            false_pass += 1
        else:
            true_fail += 1
    return ConfusionCounts(
        true_pass=true_pass,
        false_pass=false_pass,
        true_fail=true_fail,
        false_fail=false_fail,
        judge_abstained=abstained,
        reference_unresolved=unresolved,
        unmatched=unmatched,
    )


def phi_coefficient(counts: ConfusionCounts) -> float | None:
    """φ (equivalently MCC) for the 2×2 table, or ``None`` if undefined.

    ``(TP·TN − FP·FN) / sqrt((TP+FP)(TP+FN)(TN+FP)(TN+FN))``.

    ``None`` when any margin is zero, which is a real and common state —
    a judge that passed everything, or a slice where the reference never
    said "fail" — and reporting ``0.0`` there would be a claim of "no
    association" the data does not support. A degenerate margin means
    *this table cannot distinguish agreement from a constant answer*, and
    the report must say so rather than print a number.

    Args:
        counts: The confusion table.

    Returns:
        φ in [-1, 1], or ``None``.
    """
    tp, fp, tn, fn = counts.true_pass, counts.false_pass, counts.true_fail, counts.false_fail
    denominator_terms = ((tp + fp), (tp + fn), (tn + fp), (tn + fn))
    if any(term == 0 for term in denominator_terms):
        return None
    numerator = float(tp * tn - fp * fn)
    denominator = sqrt(float(denominator_terms[0]))
    for term in denominator_terms[1:]:
        denominator *= sqrt(float(term))
    return numerator / denominator


class AgreementReport(NamedTuple):
    """Judge–reference agreement, in the only form docs/eval.md allows.

    Attributes:
        counts: The confusion table.
        policy: The abstention policy the table was built under.
        raw_agreement: ``(TP + TN) / decided``, or ``None`` at zero
            decided items. Present because a reader wants it, and never
            printed alone.
        phi: φ / MCC, or ``None`` at a degenerate margin.
        judge_positive_rate: The judge's rate of saying "pass".
        reference_positive_rate: The reference's rate of saying "pass".
            κ = q·φ is uninterpretable without both of these, which is
            why neither is optional.
        judge_positive_interval: Wilson interval on the judge's rate.
        reference_positive_interval: Wilson interval on the reference's.
        raw_agreement_interval: Wilson interval on raw agreement.
        caveat: :func:`src.eval.stats.small_sample_caveat` for the
            decided count, or ``None`` above the line.
    """

    counts: ConfusionCounts
    policy: AbstentionPolicy
    raw_agreement: float | None
    phi: float | None
    judge_positive_rate: float | None
    reference_positive_rate: float | None
    judge_positive_interval: Interval | None
    reference_positive_interval: Interval | None
    raw_agreement_interval: Interval | None
    caveat: str | None


def agreement(
    pairs: Iterable[tuple[str, bool | None, bool | None]],
    *,
    policy: AbstentionPolicy = AbstentionPolicy.EXCLUDED,
    confidence: float = 0.95,
) -> AgreementReport:
    """Compute agreement in the required reporting form.

    Args:
        pairs: ``(item_id, reference_outcome, judge_outcome)`` triples.
        policy: How judge abstentions are counted.
        confidence: Two-sided confidence for every interval.

    Returns:
        The report. Every rate is ``None`` at a zero denominator rather
        than 0.0 — a rate over nothing is not zero, it is absent, and
        ``src/eval/metrics.py`` already established that a metric which
        cannot report a score it did not earn returns ``None``.
    """
    counts = confusion(pairs, policy=policy)
    decided = counts.decided
    if decided == 0:
        return AgreementReport(
            counts=counts,
            policy=policy,
            raw_agreement=None,
            phi=None,
            judge_positive_rate=None,
            reference_positive_rate=None,
            judge_positive_interval=None,
            reference_positive_interval=None,
            raw_agreement_interval=None,
            caveat=small_sample_caveat(0),
        )
    concordant = counts.true_pass + counts.true_fail
    judge_positive = counts.true_pass + counts.false_pass
    reference_positive = counts.true_pass + counts.false_fail
    return AgreementReport(
        counts=counts,
        policy=policy,
        raw_agreement=concordant / decided,
        phi=phi_coefficient(counts),
        judge_positive_rate=judge_positive / decided,
        reference_positive_rate=reference_positive / decided,
        judge_positive_interval=wilson_interval(judge_positive, decided, confidence=confidence),
        reference_positive_interval=wilson_interval(
            reference_positive, decided, confidence=confidence
        ),
        raw_agreement_interval=wilson_interval(concordant, decided, confidence=confidence),
        caveat=small_sample_caveat(decided),
    )


def agreement_under_each_policy(
    pairs: Sequence[tuple[str, bool | None, bool | None]], *, confidence: float = 0.95
) -> dict[AbstentionPolicy, AgreementReport]:
    """Compute the same agreement under all three abstention policies.

    The swing between them is the number ``docs/eval.md`` puts at 10–34
    points. Printing all three turns a choice a reader has to trust into
    a range they can see, and makes an argument about the policy an
    argument about a visible difference.

    Args:
        pairs: ``(item_id, reference_outcome, judge_outcome)`` triples.
        confidence: Two-sided confidence for every interval.

    Returns:
        One report per policy.
    """
    return {
        policy: agreement(pairs, policy=policy, confidence=confidence)
        for policy in AbstentionPolicy
    }


class RateWithInterval(NamedTuple):
    """One rate, its two counts, and its interval.

    Attributes:
        numerator: Events observed.
        denominator: Items the rate is over. Always published: 12 §3.11
            and ADR 0072 both settle that a rate without a denominator is
            not a measurement.
        rate: ``numerator / denominator``, or ``None`` at zero.
        interval: Wilson interval, or ``None`` at zero.
    """

    numerator: int
    denominator: int
    rate: float | None
    interval: Interval | None


def rate_with_interval(
    numerator: int, denominator: int, *, confidence: float = 0.95
) -> RateWithInterval:
    """Wrap one count pair in a rate and a Wilson interval.

    Zero denominator returns a ``None`` rate and a ``None`` interval
    rather than 0.0: a rate over nothing is absent, not zero, and
    ``src/eval/metrics.py`` already settled that a metric which cannot
    report a score it did not earn returns ``None``.

    Args:
        numerator: Events observed.
        denominator: Items the rate is over.
        confidence: Two-sided confidence level.

    Returns:
        The rate with its counts and interval.
    """
    if denominator == 0:
        return RateWithInterval(numerator, denominator, None, None)
    return RateWithInterval(
        numerator,
        denominator,
        numerator / denominator,
        wilson_interval(numerator, denominator, confidence=confidence),
    )


class ErrorRates(NamedTuple):
    """False pass, false fail and abstention, each over its own base.

    The three denominators differ and that is the point. False pass is
    over the items the reference called *fail* — it answers "when the
    work was bad, how often did the judge wave it through". Dividing it
    by all items instead would make a judge look better simply by being
    given more good work.

    Attributes:
        false_pass: Over reference-fail items.
        false_fail: Over reference-pass items.
        abstention: Over every item with a resolved reference decision.
        unresolved_reference: Over every item seen. Reported because an
            unresolved reference is a cost of the labelling campaign, not
            a property of the judge, and a set with many of them is a
            set that needs more adjudication before it gates anything.
    """

    false_pass: RateWithInterval
    false_fail: RateWithInterval
    abstention: RateWithInterval
    unresolved_reference: RateWithInterval


def error_rates(
    pairs: Sequence[tuple[str, bool | None, bool | None]],
    *,
    policy: AbstentionPolicy = AbstentionPolicy.EXCLUDED,
    confidence: float = 0.95,
) -> ErrorRates:
    """Compute the three judge error rates plus the reference gap.

    Args:
        pairs: ``(item_id, reference_outcome, judge_outcome)`` triples.
        policy: How judge abstentions are counted in the 2×2. The
            abstention *rate* itself is always computed from the raw
            triples, so the policy cannot make abstentions disappear
            from the report that measures them.
        confidence: Two-sided confidence for every interval.

    Returns:
        The rates.
    """
    counts = confusion(pairs, policy=policy)
    resolved = [triple for triple in pairs if triple[1] is not None]
    abstentions = sum(1 for triple in resolved if triple[2] is None)
    return ErrorRates(
        false_pass=rate_with_interval(
            counts.false_pass, counts.false_pass + counts.true_fail, confidence=confidence
        ),
        false_fail=rate_with_interval(
            counts.false_fail, counts.false_fail + counts.true_pass, confidence=confidence
        ),
        abstention=rate_with_interval(abstentions, len(resolved), confidence=confidence),
        unresolved_reference=rate_with_interval(
            sum(1 for triple in pairs if triple[1] is None), len(pairs), confidence=confidence
        ),
    )


class PositionBias(NamedTuple):
    """How often the judge preferred the position rather than the report.

    Measured only on pairs presented in **both** orders, which is why
    :class:`src.calibration.blinding.BlindingPlan` requires both. The
    single-order alternative gives a preference rate with a position
    confound inside it and no way to separate them afterwards.

    Attributes:
        both_orders: Pairs seen in both orders — the denominator.
        first_position_wins: Times the first-presented report won, out
            of ``2 * both_orders`` readings.
        readings: ``2 * both_orders``.
        first_position_rate: Share of readings won by position one, or
            ``None`` at zero.
        interval: Wilson interval on that share.
        bias: ``first_position_rate - 0.5``, or ``None``. Zero is the
            unbiased value, so this is the quantity a threshold applies
            to.
        consistent: Pairs where both orders chose the same report.
        consistency_rate: ``consistent / both_orders``, or ``None``.
        ties: Readings the judge called a tie or abstained on. Excluded
            from the position count and reported, because a judge that
            ties everything has no measurable position bias and that is
            a fact about the judge, not a clean bill of health.
    """

    both_orders: int
    first_position_wins: int
    readings: int
    first_position_rate: float | None
    interval: Interval | None
    bias: float | None
    consistent: int
    consistency_rate: float | None
    ties: int


def position_bias(
    verdicts: Iterable[JudgeVerdict], *, confidence: float = 0.95
) -> PositionBias:
    """Measure position bias from pairwise verdicts in both orders.

    An ``ab`` reading of "first" and a ``ba`` reading of "first" name
    *different* reports, so a judge with no position preference splits
    them; a judge that always says "first" produces two first-position
    wins on the same pair and is exactly what the rate catches.

    Consistency is the complementary view: the share of pairs where the
    two orders picked the same report. A high position rate and a low
    consistency rate are the same finding seen twice, and reporting both
    means a reader does not have to take the arithmetic on trust.

    Args:
        verdicts: Judge verdicts. Non-pairwise verdicts are ignored.
        confidence: Two-sided confidence for the interval.

    Returns:
        The measurement. All-zero counts when nothing was presented in
        both orders — a state that :func:`decide` treats as "cannot
        measure", never as "no bias".

    Raises:
        ValueError: One pair carries two verdicts in the same order.
    """
    by_item: dict[str, dict[str, str]] = {}
    for verdict in verdicts:
        if verdict.label_type is not LabelType.PAIRWISE_PREFERENCE:
            continue
        order = verdict.presentation_order
        assert order is not None  # the model validator guarantees it
        orders = by_item.setdefault(verdict.blinded_item_id, {})
        if order in orders:
            raise ValueError(
                f"{verdict.blinded_item_id} has two {order!r} verdicts; a repeated "
                "reading is a repeat, not a second order"
            )
        orders[order] = verdict.decision

    first = PairwisePreferenceDecision.FIRST.value
    second = PairwisePreferenceDecision.SECOND.value
    both = {
        item_id: orders for item_id, orders in by_item.items() if {"ab", "ba"} <= set(orders)
    }
    readings = 2 * len(both)
    wins = sum(
        1 for orders in both.values() for order in ("ab", "ba") if orders[order] == first
    )
    ties = sum(
        1
        for orders in both.values()
        for order in ("ab", "ba")
        if orders[order] not in {first, second}
    )
    consistent = sum(
        1
        for orders in both.values()
        if {orders["ab"], orders["ba"]} == {first, second}
        or (orders["ab"] == orders["ba"] and orders["ab"] not in {first, second})
    )
    rate = wins / readings if readings else None
    return PositionBias(
        both_orders=len(both),
        first_position_wins=wins,
        readings=readings,
        first_position_rate=rate,
        interval=wilson_interval(wins, readings, confidence=confidence) if readings else None,
        bias=None if rate is None else rate - 0.5,
        consistent=consistent,
        consistency_rate=consistent / len(both) if both else None,
        ties=ties,
    )


class SliceCoverage(NamedTuple):
    """Per-slice observation plus the per-slice false-pass rate.

    Attributes:
        observation: Counts against the sampling plan's target.
        false_pass: The slice's false-pass rate and interval, or a
            zero-denominator entry when the slice has no reference-fail
            item. Diagnostic only — 03 §8 is explicit that multiple
            slices are diagnostic unless a correction and a gate were
            declared in advance, and this protocol declares neither.
    """

    observation: SliceObservation
    false_pass: RateWithInterval


def slice_coverage(
    observations: Sequence[SliceObservation],
    pairs_by_slice: Mapping[str, Sequence[tuple[str, bool | None, bool | None]]],
    *,
    policy: AbstentionPolicy = AbstentionPolicy.EXCLUDED,
    confidence: float = 0.95,
) -> tuple[SliceCoverage, ...]:
    """Attach a per-slice false-pass rate to each coverage observation.

    Args:
        observations: One per planned slice, from
            :func:`src.calibration.sampling.observe_coverage`.
        pairs_by_slice: Slice id to that slice's outcome triples. A slice
            missing from the mapping is reported with a zero denominator
            rather than skipped: an absent slice and a slice with no
            failures look identical in a summary and are not the same.
        policy: How judge abstentions are counted.
        confidence: Two-sided confidence for the intervals.

    Returns:
        One entry per observation, in order.
    """
    coverage: list[SliceCoverage] = []
    for observation in observations:
        counts = confusion(pairs_by_slice.get(observation.slice_id, ()), policy=policy)
        coverage.append(
            SliceCoverage(
                observation=observation,
                false_pass=rate_with_interval(
                    counts.false_pass,
                    counts.false_pass + counts.true_fail,
                    confidence=confidence,
                ),
            )
        )
    return tuple(coverage)


#: Integrity classes gated at absolute zero. Named for the same reason
#: ADR 0072 names its hard-violation classes: these are not rates with
#: acceptable levels, and a baseline cannot make one of them tolerable.
INTEGRITY_VIOLATION_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "model_verdict_as_ground_truth",
        "blinding_breach",
        "unadjudicated_dispute_counted",
        "slice_reported_without_items",
        "reference_answer_visible_to_judge",
    }
)


class IntegrityFinding(StrictContractModel):
    """One integrity violation, named and located.

    Attributes:
        violation_class: One of :data:`INTEGRITY_VIOLATION_CLASSES`.
        subject: What tripped it — an item id, a slice id, an annotator.
        detail: One sentence a CI log can print.
    """

    violation_class: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    subject: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    detail: Annotated[str, StringConstraints(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def class_is_known(self) -> IntegrityFinding:
        if self.violation_class not in INTEGRITY_VIOLATION_CLASSES:
            raise ValueError(
                f"{self.violation_class!r} is not an integrity class; "
                f"expected one of {sorted(INTEGRITY_VIOLATION_CLASSES)}"
            )
        return self


def find_integrity_violations(
    items: Sequence[LabelledItem],
    coverage: Sequence[SliceCoverage],
    *,
    blinding_leaks: Mapping[str, Sequence[str]] = {},
) -> tuple[IntegrityFinding, ...]:
    """Scan a calibration set for the things no interval can excuse.

    Note what is *not* scanned for: a model-authored label. It cannot
    exist — :class:`src.calibration.labels.CalibrationLabel` refuses one
    at construction — so the check belongs in the schema, where it is
    unbypassable, rather than here where a caller could skip it. The
    class stays in :data:`INTEGRITY_VIOLATION_CLASSES` because a future
    ingest path that reads labels from somewhere else will need to raise
    it, and a violation class invented at the moment it is first needed
    is a violation class nobody wrote a response to.

    Args:
        items: The labelled items.
        coverage: Per-slice coverage, already computed.
        blinding_leaks: Item id to the forbidden terms found in its
            rendered judge input, from
            :func:`src.calibration.blinding.leaked_identity_terms`.

    Returns:
        Every finding, sorted by class then subject.
    """
    findings: list[IntegrityFinding] = []
    for item in items:
        if item.agreement_state == "disputed":
            findings.append(
                IntegrityFinding(
                    violation_class="unadjudicated_dispute_counted",
                    subject=item.blinded_item_id,
                    detail=(
                        "annotators disagreed and no adjudication exists; the item has "
                        "no reference decision and must not enter a denominator"
                    ),
                )
            )
    for item_id, terms in sorted(blinding_leaks.items()):
        if terms:
            findings.append(
                IntegrityFinding(
                    violation_class="blinding_breach",
                    subject=item_id,
                    detail=f"the rendered judge input names {', '.join(sorted(terms))}",
                )
            )
    for entry in coverage:
        if entry.observation.unmeasured and entry.false_pass.denominator > 0:
            findings.append(
                IntegrityFinding(
                    violation_class="slice_reported_without_items",
                    subject=entry.observation.slice_id,
                    detail=(
                        "a rate is reported for a slice with no resolved reference "
                        "decision in it"
                    ),
                )
            )
    return tuple(
        sorted(findings, key=lambda finding: (finding.violation_class, finding.subject))
    )


class UsabilityThresholds(StrictContractModel):
    """The declared bars a judge must clear to gate a release.

    **Proposed, not approved.** 07 §7 requires the non-inferiority margin
    to be set from the repeated baseline and human calibration *before*
    candidate results are unblinded, and neither exists. These values are
    a starting point for that conversation, and
    :attr:`approved_by_owner` is ``False`` until an owner sets them.

    Attributes:
        false_pass_ceiling: The false-pass rate's Wilson **upper** bound
            must sit at or below this. An upper bound rather than a point
            estimate because a point estimate of 0/12 is 0.0 and its
            upper bound is 0.24.
        phi_floor: φ must sit at or above this. A floor on the point
            estimate *and* on the interval is not available — φ has no
            Wilson interval — so this protocol gates on the point
            estimate and requires the minimum item count to make it
            meaningful.
        position_bias_tolerance: ``|bias|``'s interval must contain a
            value inside this band. Zero would be unachievable at any
            finite n.
        minimum_resolved_items: Below this many resolved items the gate
            answers HOLD regardless of what the rates say.
        approved_by_owner: Fixed ``False``. A threshold set is not a
            decision until somebody makes it one.
    """

    false_pass_ceiling: Annotated[float, Field(gt=0.0, lt=1.0)]
    phi_floor: Annotated[float, Field(ge=-1.0, le=1.0)]
    position_bias_tolerance: Annotated[float, Field(ge=0.0, lt=0.5)]
    minimum_resolved_items: Annotated[int, Field(ge=1)]
    approved_by_owner: bool = False

    @model_validator(mode="after")
    def thresholds_are_not_an_approval(self) -> UsabilityThresholds:
        if self.approved_by_owner:
            raise ValueError(
                "an owner approval is recorded in the approval ledger, not typed into "
                "a threshold object (07 §12)"
            )
        return self


#: The proposed starting thresholds. A 10% false-pass ceiling because a
#: judge that waves through one bad report in ten cannot gate a release
#: whose primary outcome is supported-claim precision; φ ≥ 0.6 because
#: below it the judge and the reference are barely related; a 5-point
#: position-bias band because ``docs/eval.md`` records position bias as
#: the one presentation bias that has *not* collapsed; and 127 resolved
#: items because that is what
#: :func:`src.calibration.sampling.items_to_bound_below` says a 5%
#: observed rate needs before its upper bound clears 10%.
DEFAULT_THRESHOLDS: Final[UsabilityThresholds] = UsabilityThresholds(
    false_pass_ceiling=0.10,
    phi_floor=0.60,
    position_bias_tolerance=0.05,
    minimum_resolved_items=127,
)


class CalibrationReport(StrictContractModel):
    """One calibration run, in the shape a decision is made from.

    Attributes:
        schema_kind: Fixed discriminator.
        set_id: Which calibration set produced it.
        set_revision: That set's revision.
        judge_rubric_name: The instrument measured.
        judge_rubric_version: Its version *at measurement time*.
        calibration_rubric_version: The version the set was authored
            against. When the two differ the judge has moved and the
            calibration does not describe it (03 §7.7).
        abstention_policy: How abstentions were counted.
        resolved_items: Items with a reference decision.
        raw_agreement / phi / positive rates: the required reporting
            form, flattened so a report serializes without a nested
            estimator type.
        false_pass_upper / false_fail_upper: the Wilson upper bounds the
            gate compares.
        position_bias / position_bias_interval: from
            :func:`position_bias`.
        integrity: Every violation found.
        unmeasured_slices: Planned slices with no resolved item.
        basis: ``measured`` or ``hypothesis``. Every report this
            repository can produce today is a hypothesis: no judge has
            been run.
    """

    schema_kind: Literal["judge-calibration-report"] = "judge-calibration-report"
    schema_version: Literal["1.0.0"] = "1.0.0"
    set_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
    set_revision: SemVer
    judge_rubric_name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    judge_rubric_version: SemVer
    calibration_rubric_version: SemVer
    abstention_policy: AbstentionPolicy
    resolved_items: Annotated[int, Field(ge=0)]
    decided_items: Annotated[int, Field(ge=0)]
    raw_agreement: float | None
    phi: float | None
    judge_positive_rate: float | None
    reference_positive_rate: float | None
    false_pass_numerator: Annotated[int, Field(ge=0)]
    false_pass_denominator: Annotated[int, Field(ge=0)]
    false_pass_upper: float | None
    false_fail_numerator: Annotated[int, Field(ge=0)]
    false_fail_denominator: Annotated[int, Field(ge=0)]
    false_fail_upper: float | None
    abstention_numerator: Annotated[int, Field(ge=0)]
    abstention_denominator: Annotated[int, Field(ge=0)]
    position_bias: float | None
    position_bias_interval: tuple[float, float] | None
    position_bias_pairs: Annotated[int, Field(ge=0)]
    integrity: tuple[IntegrityFinding, ...] = ()
    unmeasured_slices: tuple[str, ...] = ()
    small_sample_caveat: Annotated[str, StringConstraints(min_length=1)] | None = None
    basis: Literal["measured", "hypothesis"] = "hypothesis"


def build_report(
    *,
    set_id: str,
    set_revision: str,
    judge_rubric_name: str,
    judge_rubric_version: str,
    calibration_rubric_version: str,
    items: Sequence[LabelledItem],
    verdicts: Sequence[JudgeVerdict],
    coverage: Sequence[SliceCoverage] = (),
    policy: AbstentionPolicy = AbstentionPolicy.EXCLUDED,
    blinding_leaks: Mapping[str, Sequence[str]] = {},
    confidence: float = 0.95,
    basis: Literal["measured", "hypothesis"] = "hypothesis",
) -> CalibrationReport:
    """Assemble one calibration report from labels and verdicts.

    Args:
        set_id: The calibration set's id.
        set_revision: Its revision.
        judge_rubric_name: The instrument being measured.
        judge_rubric_version: Its version at measurement time.
        calibration_rubric_version: The version the set was authored
            against.
        items: Labelled items.
        verdicts: Judge verdicts, single and pairwise.
        coverage: Per-slice coverage, already computed.
        policy: How abstentions are counted.
        blinding_leaks: Item id to forbidden terms found in its rendered
            input.
        confidence: Two-sided confidence for every interval.
        basis: Whether the verdicts were measured or predicted.

    Returns:
        The report.
    """
    pairs = resolved_pairs(items, verdicts)
    summary = agreement(pairs, policy=policy, confidence=confidence)
    rates = error_rates(pairs, policy=policy, confidence=confidence)
    bias = position_bias(verdicts, confidence=confidence)
    findings = find_integrity_violations(items, coverage, blinding_leaks=blinding_leaks)
    return CalibrationReport(
        set_id=set_id,
        set_revision=set_revision,
        judge_rubric_name=judge_rubric_name,
        judge_rubric_version=judge_rubric_version,
        calibration_rubric_version=calibration_rubric_version,
        abstention_policy=policy,
        resolved_items=sum(1 for item in items if item.resolved_decision is not None),
        decided_items=summary.counts.decided,
        raw_agreement=summary.raw_agreement,
        phi=summary.phi,
        judge_positive_rate=summary.judge_positive_rate,
        reference_positive_rate=summary.reference_positive_rate,
        false_pass_numerator=rates.false_pass.numerator,
        false_pass_denominator=rates.false_pass.denominator,
        false_pass_upper=None if rates.false_pass.interval is None else rates.false_pass.interval.high,
        false_fail_numerator=rates.false_fail.numerator,
        false_fail_denominator=rates.false_fail.denominator,
        false_fail_upper=None if rates.false_fail.interval is None else rates.false_fail.interval.high,
        abstention_numerator=rates.abstention.numerator,
        abstention_denominator=rates.abstention.denominator,
        position_bias=bias.bias,
        position_bias_interval=(
            None if bias.interval is None else (bias.interval.low, bias.interval.high)
        ),
        position_bias_pairs=bias.both_orders,
        integrity=findings,
        unmeasured_slices=tuple(
            entry.observation.slice_id for entry in coverage if entry.observation.unmeasured
        ),
        small_sample_caveat=summary.caveat,
        basis=basis,
    )


GateState = Literal["PROMOTE", "HOLD", "ROLLBACK"]


class GateDecision(NamedTuple):
    """The three-state verdict, plus why.

    Field-for-field the shape of ``src/eval/safety_suite.GateDecision``
    (ADR 0072), and a test asserts that rather than trusting this
    sentence. Two gates in one repository that answer in different
    vocabularies is two things a reader has to learn.

    Attributes:
        state: PROMOTE, HOLD or ROLLBACK. Here they mean: this judge may
            gate a release; its numbers are diagnostics only; it must not
            gate a release.
        reasons: Every reason, in evaluation order. The integrity veto's
            reason is always first when it fires.
        advisory: Whether the measured half of this decision is binding.
        blocking: Whether a caller should refuse to ship. Distinct from
            `state`: in advisory mode a measurement-driven ROLLBACK is
            reported and not enforced, while an integrity violation
            blocks either way.
    """

    state: GateState
    reasons: tuple[str, ...]
    advisory: bool
    blocking: bool

    @property
    def exit_code(self) -> int:
        """0 when nothing blocks, 1 when something does."""
        return 1 if self.blocking else 0


def decide(
    report: CalibrationReport,
    thresholds: UsabilityThresholds = DEFAULT_THRESHOLDS,
    *,
    advisory: bool = True,
) -> GateDecision:
    """Answer: may this judge be used as a release gate?

    Order is the design, not an implementation detail — the same order
    ADR 0072's safety gate uses, for the same reason:

    1. **The integrity veto.** Any finding in
       :data:`INTEGRITY_VIOLATION_CLASSES` is a ROLLBACK. No interval is
       consulted and `advisory` does not soften it. A calibration set
       with a blinding breach in it is not a weaker measurement, it is a
       measurement of something else.
    2. **Comparability and sufficiency.** A judge whose rubric version
       has moved since the set was labelled, a report with no measured
       verdicts, or fewer resolved items than
       :attr:`UsabilityThresholds.minimum_resolved_items`: HOLD.
    3. **The measurement.** The false-pass upper bound against the
       ceiling, φ against its floor, and the position-bias interval
       against its band. A bound that fails is a ROLLBACK; an interval
       that straddles its threshold is a HOLD; all clear is a PROMOTE.

    A report whose ``basis`` is ``hypothesis`` can never reach PROMOTE:
    predicted verdicts are a design artefact, and this function will not
    convert one into permission.

    Args:
        report: The calibration report.
        thresholds: The declared bars.
        advisory: When True (the default until a set has been through a
            campaign), a measurement-driven verdict is reported without
            blocking. The integrity veto still blocks.

    Returns:
        The decision, with every reason it reached it.
    """
    reasons: list[str] = []
    if report.integrity:
        tripped = sorted({finding.violation_class for finding in report.integrity})
        reasons.append(
            "INTEGRITY VETO: "
            + ", ".join(
                f"{name}×{sum(1 for f in report.integrity if f.violation_class == name)}"
                for name in tripped
            )
            + " — these classes are gated at absolute zero and no threshold or "
            "advisory flag applies to them"
        )
        reasons.extend(
            f"  {finding.violation_class} at {finding.subject}: {finding.detail}"
            for finding in report.integrity
        )
        return GateDecision("ROLLBACK", tuple(reasons), advisory, blocking=True)

    reasons.append("integrity veto clear: 0 violations")

    if report.basis != "measured":
        reasons.append(
            "the verdicts in this report are predicted, not measured; no judge has "
            "been run against this set"
        )
        return GateDecision("HOLD", tuple(reasons), advisory, blocking=not advisory)
    if report.judge_rubric_version != report.calibration_rubric_version:
        reasons.append(
            f"the judge moved: calibrated against {report.judge_rubric_name} "
            f"{report.calibration_rubric_version}, measured at "
            f"{report.judge_rubric_version}; a calibration of one instrument does not "
            "describe another (03 §7.7)"
        )
        return GateDecision("HOLD", tuple(reasons), advisory, blocking=not advisory)
    if report.resolved_items < thresholds.minimum_resolved_items:
        reasons.append(
            f"{report.resolved_items} resolved items, below the declared minimum of "
            f"{thresholds.minimum_resolved_items}; the intervals below are too wide "
            "to gate on"
        )
        return GateDecision("HOLD", tuple(reasons), advisory, blocking=not advisory)
    if report.unmeasured_slices:
        reasons.append(
            "no resolved item in "
            + ", ".join(report.unmeasured_slices)
            + "; a judge is usable per slice or not at all (03 §7.4)"
        )
        return GateDecision("HOLD", tuple(reasons), advisory, blocking=not advisory)

    failures: list[str] = []
    holds: list[str] = []

    if report.false_pass_denominator == 0 or report.false_pass_upper is None:
        holds.append(
            "no reference-fail item, so the false-pass rate has no denominator; a "
            "judge cannot be shown safe on work nobody called bad"
        )
    else:
        rate = report.false_pass_numerator / report.false_pass_denominator
        reasons.append(
            f"false pass {report.false_pass_numerator}/{report.false_pass_denominator} "
            f"= {rate:.2%} (95% upper {report.false_pass_upper:.2%}, ceiling "
            f"{thresholds.false_pass_ceiling:.2%})"
        )
        if rate > thresholds.false_pass_ceiling:
            failures.append(
                f"the observed false-pass rate {rate:.2%} is already above the "
                f"{thresholds.false_pass_ceiling:.2%} ceiling"
            )
        elif report.false_pass_upper > thresholds.false_pass_ceiling:
            holds.append(
                f"the false-pass interval reaches {report.false_pass_upper:.2%}, above "
                f"the {thresholds.false_pass_ceiling:.2%} ceiling; more items or a "
                "lower rate, not a rounder number"
            )

    if report.phi is None:
        holds.append(
            "φ is undefined: one margin of the table is zero, so agreement cannot be "
            "distinguished from a constant answer"
        )
    else:
        reasons.append(
            f"φ {report.phi:+.3f} (floor {thresholds.phi_floor:+.3f}); judge positive "
            f"rate {_percent(report.judge_positive_rate)}, reference positive rate "
            f"{_percent(report.reference_positive_rate)}"
        )
        if report.phi < thresholds.phi_floor:
            failures.append(
                f"φ {report.phi:+.3f} is below the declared floor "
                f"{thresholds.phi_floor:+.3f}"
            )

    if report.position_bias is None or report.position_bias_interval is None:
        holds.append(
            "no pair was presented in both orders, so position bias is unmeasured; "
            "unmeasured is not zero"
        )
    else:
        low, high = report.position_bias_interval
        reasons.append(
            f"position bias {report.position_bias:+.3f} over "
            f"{report.position_bias_pairs} pairs (95% first-position share "
            f"{low:.3f}..{high:.3f}, tolerance ±{thresholds.position_bias_tolerance:.3f})"
        )
        band = thresholds.position_bias_tolerance
        if low - 0.5 > band or high - 0.5 < -band:
            failures.append(
                f"the position-bias interval sits entirely outside ±{band:.3f}; the "
                "judge prefers a position, not a report"
            )
        elif abs(report.position_bias) > band:
            holds.append(
                f"the observed position bias {report.position_bias:+.3f} exceeds "
                f"±{band:.3f} but its interval does not exclude the band"
            )

    if failures:
        reasons.extend(failures)
        reasons.append("this judge must not be used as a release gate")
        return GateDecision("ROLLBACK", tuple(reasons), advisory, blocking=not advisory)
    if holds:
        reasons.extend(holds)
        reasons.append("report these numbers as diagnostics, not as a gate")
        return GateDecision("HOLD", tuple(reasons), advisory, blocking=not advisory)
    reasons.append("every declared bar is cleared by its interval, not only by its point")
    return GateDecision("PROMOTE", tuple(reasons), advisory, blocking=False)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def report_lines(report: CalibrationReport, decision: GateDecision) -> list[str]:
    """Render a report and its decision as plain lines for a CI log.

    The rendering enforces ``docs/eval.md``'s rule mechanically: raw
    agreement is printed on the *same* line as φ and both positive
    rates, so there is no way to quote it alone by copying one line out
    of the log. A test asserts that property rather than trusting this
    docstring.

    Args:
        report: The report.
        decision: Its decision.

    Returns:
        Lines, no trailing newlines.
    """
    lines = [
        "Judge calibration (P0-WO10)",
        f"  set               {report.set_id}@{report.set_revision}",
        f"  instrument        {report.judge_rubric_name} {report.judge_rubric_version}"
        f" (calibrated against {report.calibration_rubric_version})",
        f"  basis             {report.basis}",
        f"  abstentions       {report.abstention_policy.value}"
        f" ({report.abstention_numerator}/{report.abstention_denominator} abstained)",
        f"  resolved items    {report.resolved_items} ({report.decided_items} decided by both)",
        "  agreement         "
        f"φ {_signed(report.phi)}"
        f" | judge positive {_percent(report.judge_positive_rate)}"
        f" | reference positive {_percent(report.reference_positive_rate)}"
        f" | raw agreement {_percent(report.raw_agreement)}"
        " (raw agreement overstates chance-corrected agreement; read φ)",
        f"  false pass        {report.false_pass_numerator}/{report.false_pass_denominator}"
        f" (95% upper {_percent(report.false_pass_upper)})",
        f"  false fail        {report.false_fail_numerator}/{report.false_fail_denominator}"
        f" (95% upper {_percent(report.false_fail_upper)})",
        f"  position bias     {_signed(report.position_bias)} over"
        f" {report.position_bias_pairs} both-order pairs",
    ]
    if report.unmeasured_slices:
        lines.append(f"  unmeasured slices {', '.join(report.unmeasured_slices)}")
    if report.small_sample_caveat:
        lines.append(f"  caveat            {report.small_sample_caveat}")
    lines.append(f"  decision          {decision.state}")
    lines.extend(f"    - {reason}" for reason in decision.reasons)
    return lines


def _signed(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.3f}"
