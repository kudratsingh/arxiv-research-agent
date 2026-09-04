"""Statistics for the eval gate — ADR 0071.

The regression gate used to compare two numbers against a flat ±0.10
band that ADR 0044 itself calls "priors, not statistics". This module is
the other half of that sentence: the estimators a gate needs before it
may claim a move is real, sized for the N this repository actually has.

**Pairing is the headline.** Detecting a 5-point gain against an 80%
baseline needs roughly **906 items per arm unpaired** and roughly **77
paired** — `unpaired_required_per_arm` and `mcnemar_required_pairs`
below reproduce both figures from their published formulae, so the
claim is checkable rather than quoted. At 20 benchmark queries and 15
learning scenarios that ratio is not an optimisation; it is the
difference between a gate that can measure something and one that
cannot. Everything here therefore scores the baseline and the candidate
**on the same items**.

**And it is still not enough.** Even paired, 20 queries is far below
the few hundred datapoints at which the central-limit approximation
starts telling the truth — below that it materially *underestimates*
uncertainty, so a normal-approximation interval printed on N=20 is too
narrow. `small_sample_caveat` exists so the report says that in words
instead of printing a falsely confident number. An honest gate that
says "cannot distinguish" is worth more than a confident one that
cannot.

Design constraints, all load-bearing:

- **Pure.** Nothing here touches the network, the filesystem, a model,
  or the clock. `src/eval/regression_diff.py` is a gate, and a model
  call inside a gate is an attack surface rather than a control.
- **Seeded.** The one randomised procedure, `paired_bootstrap_delta`,
  takes a `seed` and uses its own `random.Random` instance, so it
  neither reads nor perturbs the campaign's global generator.
- **Stdlib only.** `statistics.NormalDist` supplies the normal
  quantiles and `math.comb` the exact binomial tail. scipy is in the
  lockfile, but a gate with fewer moving parts is a gate that keeps
  working.
- **Exact where N is small.** `mcnemar` defaults to the exact binomial
  test rather than the χ² approximation, because at this repository's
  scale the discordant count is single digits and χ² is not valid
  there.

Every function is unit-tested against a value computed by hand in
`tests/test_eval_stats.py`, including the bootstrap: a bootstrap
checked only against itself is not checked.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from math import ceil, comb, sqrt
from statistics import NormalDist, fmean
from typing import Final, Literal, NamedTuple

#: Two-sided confidence used everywhere a level is not given. 95% is
#: the convention every figure this module reproduces was computed at.
DEFAULT_CONFIDENCE: Final[float] = 0.95

#: Bootstrap resamples. 10,000 puts the Monte-Carlo error on a 95%
#: percentile bound below a thousandth for the sample sizes here, which
#: is an order of magnitude finer than any band the gate compares
#: against, and costs milliseconds on 20 tasks.
DEFAULT_RESAMPLES: Final[int] = 10_000

#: Discordant-pair count above which `mcnemar` switches from the exact
#: binomial test to the continuity-corrected χ². The exact test is
#: `O(b + c)` big-integer work, so the cutoff is about not doing 10,000
#: `comb` calls on a table where the approximation is already sound —
#: not about the approximation being better. At this repository's N the
#: exact branch is the only one that ever runs.
MCNEMAR_EXACT_MAX_DISCORDANT: Final[int] = 100

#: Below this many paired datapoints the report must state that its
#: interval is approximate. Deliberately a round number standing in for
#: `02-STANDARDS.md` §2.3's "a few hundred": the guidance to use ≥1,000
#: questions for 3-point resolution assumes the CLT holds, and below a
#: few hundred it does not — it underestimates the spread. There is no
#: sharp threshold to discover, so the constant is a declared line
#: rather than a derived one, and the caveat it triggers says what it
#: means instead of implying a cliff.
CLT_MIN_DATAPOINTS: Final[int] = 200


class Interval(NamedTuple):
    """A two-sided interval estimate.

    Attributes:
        low: Lower bound.
        high: Upper bound.
    """

    low: float
    high: float

    @property
    def width(self) -> float:
        """`high - low`. Zero means every resample agreed exactly."""
        return self.high - self.low

    def excludes_zero(self) -> bool:
        """Whether the whole interval sits on one side of zero.

        The question a gate asks of a delta's interval: an interval that
        contains zero is a move the data cannot distinguish from no move
        at all.
        """
        return self.low > 0.0 or self.high < 0.0

    def __str__(self) -> str:
        return f"[{self.low:+.3f}, {self.high:+.3f}]"


def _two_sided_z(confidence: float) -> float:
    """`z` for a two-sided interval at `confidence` (0.95 -> 1.959964)."""
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    return NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)


def _one_sided_z(probability: float) -> float:
    """`z` such that `Phi(z) == probability` (0.80 -> 0.841621)."""
    if not 0.0 < probability < 1.0:
        raise ValueError(f"probability must be in (0, 1), got {probability}")
    return NormalDist().inv_cdf(probability)


def _normal_upper_tail(z: float) -> float:
    """`P(Z > z)` for a standard normal."""
    return 1.0 - NormalDist().cdf(z)


# ---------------------------------------------------------------------------
# Binary rates
# ---------------------------------------------------------------------------


def wilson_interval(
    successes: int,
    trials: int,
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    z: float | None = None,
) -> Interval:
    """Wilson score interval for a binomial proportion.

    Wilson rather than the Wald (`p ± z·sqrt(pq/n)`) interval because
    Wald's coverage collapses exactly where this repository lives —
    small `n`, proportions near 0 or 1 — and it happily returns bounds
    outside `[0, 1]`. Wilson stays inside the unit interval, keeps
    roughly nominal coverage at n=20, and does not degenerate to
    zero width when every trial succeeded.

    **This is the only implementation.** ADR 0072's safety suite carried
    its own copy of the formula, because this module did not exist on
    that branch and a safety gate that cannot run until another work
    order lands is a safety gate that does not run.
    `safety_suite.wilson_interval` now delegates here while keeping its
    own contract — a pinned `z` and `(0.0, 0.0)` at zero trials — which
    is why `z` exists as an escape hatch below. Before the two were
    joined they were checked against the formula computed by hand over
    every `(successes, trials)` with `trials <= 200`, 20,300 pairs, and
    agreed to 3.4e-16: a difference of operation order, not of method.

    Args:
        successes: Number of successes, `0 <= successes <= trials`.
        trials: Number of trials, at least 1.
        confidence: Two-sided confidence level. Ignored when `z` is
            given.
        z: The standard-normal quantile to use, bypassing `confidence`.
            Exists so a caller that pins its own `z` constant — the
            safety suite does, because every interval it prints has to
            be the same one for its difference interval to mean anything
            — gets bit-identical arithmetic rather than a value
            round-tripped through `confidence`. Prefer `confidence`
            unless you have that reason.

    Returns:
        The interval, clamped to `[0, 1]`.

    Raises:
        ValueError: `trials` is not positive, `successes` is out of
            range, or `confidence` is outside `(0, 1)`.
    """
    if trials <= 0:
        raise ValueError(f"trials must be positive, got {trials}")
    if not 0 <= successes <= trials:
        raise ValueError(f"successes {successes} out of range for {trials} trials")

    quantile = _two_sided_z(confidence) if z is None else z
    # Written in exactly the association ADR 0072's copy used —
    # `z * sqrt(...) / denominator`, not `(z / denominator) * sqrt(...)`
    # — so that the safety suite delegating here reproduces its previous
    # output bit for bit rather than to within 1e-16. The two orders are
    # equal in real arithmetic and not in floating point, and the gate
    # whose baseline is already recorded is the one that should not
    # move.
    proportion = successes / trials
    denominator = 1.0 + quantile * quantile / trials
    centre = (proportion + quantile * quantile / (2 * trials)) / denominator
    spread = (
        quantile
        * sqrt(
            proportion * (1 - proportion) / trials
            + quantile * quantile / (4 * trials * trials)
        )
        / denominator
    )
    return Interval(max(0.0, centre - spread), min(1.0, centre + spread))


def rule_of_three(trials: int) -> float:
    """The `3/n` upper bound on a rate after zero observed failures.

    A clean suite is not evidence of zero risk; it is evidence that the
    failure rate is probably below `3/n`. Twenty green queries bound the
    failure rate at roughly 15%, which is the honest reading of a green
    nightly on a benchmark this size, and is why the gate reports it
    rather than printing "0.000".

    `zero_failure_upper_bound` is the exact version; this is the rule of
    thumb `02-STANDARDS.md` §2.3 names, kept because it is the number
    people recognise and it is conservative (larger) at every n.

    Args:
        trials: Number of trials, all of which succeeded. Must be
            positive.

    Returns:
        The upper bound, e.g. `0.15` at n=20.

    Raises:
        ValueError: `trials` is not positive.
    """
    if trials <= 0:
        raise ValueError(f"trials must be positive, got {trials}")
    return 3.0 / trials


def zero_failure_upper_bound(
    trials: int, *, confidence: float = DEFAULT_CONFIDENCE
) -> float:
    """Exact one-sided upper bound on a rate after zero failures.

    `1 - (1 - confidence) ** (1 / n)`: the largest failure rate that
    would still have produced `n` clean trials with probability at least
    `1 - confidence`. At n=20 it is 0.1391 against `rule_of_three`'s
    0.15 — the approximation is the conservative one, which is the right
    direction for a bound quoted in a gate.

    Args:
        trials: Number of trials, all of which succeeded.
        confidence: One-sided confidence level.

    Returns:
        The upper bound.

    Raises:
        ValueError: `trials` is not positive, or `confidence` is not in
            `(0, 1)`.
    """
    if trials <= 0:
        raise ValueError(f"trials must be positive, got {trials}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    return 1.0 - float((1.0 - confidence) ** (1.0 / trials))


def pass_hat_k(successes: int, trials: int, k: int) -> float:
    """`pass^k` — the probability that *all* `k` attempts succeed.

    `02-STANDARDS.md` §2.1: `pass^k` has displaced `pass@1` as the
    honest reliability statistic, because a user of a repeated workflow
    experiences the run where it failed, not the mean. The published gap
    is not academic — a model near 61% at `pass^1` can fall to about 25%
    at `pass^8`.

    Estimated without replacement, `C(successes, k) / C(trials, k)`,
    which is the unbiased estimate of "draw `k` of this task's `n`
    observed attempts; all `k` succeeded". Assuming independence and
    reporting `(successes / trials) ** k` instead would be optimistic
    whenever a task's failures cluster, which is precisely when the
    statistic matters.

    Args:
        successes: Attempts that succeeded.
        trials: Attempts made, at least `k`.
        k: Attempts that must all succeed, at least 1.

    Returns:
        The estimate in `[0, 1]`. Zero when `successes < k` — fewer
        successes than draws means no clean draw exists.

    Raises:
        ValueError: `k` is not positive, exceeds `trials`, or
            `successes` is out of range.
    """
    if k < 1:
        raise ValueError(f"k must be positive, got {k}")
    if trials < k:
        raise ValueError(f"trials {trials} is fewer than k {k}")
    if not 0 <= successes <= trials:
        raise ValueError(f"successes {successes} out of range for {trials} trials")
    return comb(successes, k) / comb(trials, k)


# ---------------------------------------------------------------------------
# Paired binary outcomes — McNemar
# ---------------------------------------------------------------------------


class McNemarResult(NamedTuple):
    """One McNemar test over paired binary outcomes.

    Attributes:
        baseline_only: Pairs the baseline got right and the candidate
            got wrong — the `b` cell, losses.
        candidate_only: Pairs the candidate got right and the baseline
            got wrong — the `c` cell, gains.
        concordant: Pairs where both arms agreed. Carried because the
            test ignores them and a reader should be able to see how
            much of the sample the test never looked at.
        statistic: Edwards' continuity-corrected χ², descriptive on
            both branches so two results are comparable at a glance.
        p_value: Two-sided p-value from `method`.
        method: `"exact"` (binomial) or `"chi2"`.
    """

    baseline_only: int
    candidate_only: int
    concordant: int
    statistic: float
    p_value: float
    method: Literal["exact", "chi2"]

    @property
    def discordant(self) -> int:
        """`b + c` — the pairs the test is actually computed on."""
        return self.baseline_only + self.candidate_only

    @property
    def pairs(self) -> int:
        """Every pair fed to the test, discordant or not."""
        return self.discordant + self.concordant


class PairedBinaryOutcomes(NamedTuple):
    """Two arms' per-item binary outcomes, matched by item id.

    Attributes:
        pairs: `(baseline_outcome, candidate_outcome)` for every id both
            arms decided. This is what `mcnemar` is run on.
        unmatched_baseline: Ids only the baseline arm decided.
        unmatched_candidate: Ids only the candidate arm decided.
    """

    pairs: tuple[tuple[bool, bool], ...]
    unmatched_baseline: tuple[str, ...]
    unmatched_candidate: tuple[str, ...]

    @property
    def matched(self) -> int:
        """Items both arms decided — the test's denominator."""
        return len(self.pairs)

    @property
    def unmatched(self) -> int:
        """Items exactly one arm decided, excluded from the test."""
        return len(self.unmatched_baseline) + len(self.unmatched_candidate)


def pair_binary_outcomes(
    baseline: Mapping[str, bool], candidate: Mapping[str, bool]
) -> PairedBinaryOutcomes:
    """Match two arms' `{item_id: outcome}` maps into McNemar pairs.

    Written for `src/eval/groundedness.paired_outcomes`, which returns
    exactly this shape keyed by a content-derived `claim_id` that is
    stable across arms and runs. It takes plain mappings rather than
    importing that module, so this one stays free of every `src` import.

    **The decision this function encodes**, which WO-A16 deliberately
    left to the module that owns the test: an id present in one arm and
    absent from the other is **neither concordant nor discordant**. It is
    counted, returned, and excluded from the statistic.

    Two arms make different claims. A candidate that stops asserting
    something has not failed to support it, and scoring the absence as a
    loss would punish an arm for being appropriately conservative —
    exactly the behaviour a groundedness metric should reward. Scoring it
    as concordant would be worse: it would dilute the discordant cells
    with items the arms never disagreed about because one never spoke.

    Silently intersecting was the third option and is rejected for the
    reason the caller must not lose: a candidate that stops making a
    claim it used to support *is* a movement worth seeing, and an
    intersection hides it inside a shrinking denominator. Returning the
    unmatched ids makes "n=14 comparable, 6 unmatched" reportable, which
    is the same shape WO-A16 chose for its own undecidable quotes — an
    explicit `excluded` count beside the rate rather than a rate quietly
    computed over less.

    The cost is stated rather than hidden: a large unmatched count means
    the two arms wrote about different things, and a McNemar p-value over
    the remainder is a statement about a subset the caller has to read
    the counts to size.

    Args:
        baseline: The baseline arm's decided outcomes.
        candidate: The candidate arm's decided outcomes, over the same
            source item.

    Returns:
        The matched pairs and both unmatched id lists, each sorted so two
        runs over the same data produce identical output.
    """
    shared = sorted(set(baseline) & set(candidate))
    return PairedBinaryOutcomes(
        pairs=tuple((baseline[item_id], candidate[item_id]) for item_id in shared),
        unmatched_baseline=tuple(sorted(set(baseline) - set(candidate))),
        unmatched_candidate=tuple(sorted(set(candidate) - set(baseline))),
    )


def mcnemar(
    pairs: Sequence[tuple[bool, bool]], *, exact: bool | None = None
) -> McNemarResult:
    """McNemar's test for a paired binary outcome.

    The estimator pairing buys. Each element is one *item* scored twice
    — `(baseline_succeeded, candidate_succeeded)` — and the test looks
    only at the items where the two arms disagreed. Everything the two
    runs agree on carries no information about which is better, which is
    exactly why pairing is worth an order of magnitude of sample size
    (`mcnemar_required_pairs` versus `unpaired_required_per_arm`).

    The default is the **exact** binomial test on the discordant pairs,
    not χ². With 20 queries the discordant count is single digits, where
    the χ² approximation is not valid and reports p-values that are too
    small — the failure mode this module exists to avoid.

    Args:
        pairs: `(baseline_outcome, candidate_outcome)` per item, both
            arms scored on the **same** item.
        exact: Force the exact binomial test (`True`) or the
            continuity-corrected χ² (`False`). `None` picks exact up to
            `MCNEMAR_EXACT_MAX_DISCORDANT` discordant pairs.

    Returns:
        The counts, the statistic and a two-sided p-value.

    Raises:
        ValueError: `pairs` is empty. A test on no data has no answer,
            and returning `p = 1.0` would read as "no difference".
    """
    if not pairs:
        raise ValueError("mcnemar needs at least one pair")

    baseline_only = sum(1 for base, cand in pairs if base and not cand)
    candidate_only = sum(1 for base, cand in pairs if cand and not base)
    concordant = len(pairs) - baseline_only - candidate_only
    discordant = baseline_only + candidate_only

    # Edwards' correction, floored at zero. The textbook form is
    # `(|b - c| - 1)**2 / (b + c)`, which reports a positive statistic
    # for a perfectly tied table — the floor keeps "the two arms
    # disagreed equally often" reading as no evidence, which is what it
    # is.
    excess = max(0.0, abs(baseline_only - candidate_only) - 1.0)
    statistic = 0.0 if discordant == 0 else excess * excess / discordant

    use_exact = discordant <= MCNEMAR_EXACT_MAX_DISCORDANT if exact is None else exact

    if discordant == 0:
        # Every pair agreed. There is no evidence of a difference, and
        # saying so is different from having no data: `pairs` was not
        # empty, the arms simply never diverged.
        return McNemarResult(
            baseline_only=0,
            candidate_only=0,
            concordant=concordant,
            statistic=0.0,
            p_value=1.0,
            method="exact" if use_exact else "chi2",
        )

    if use_exact:
        # Under the null the discordant pairs are fair coin flips, so
        # the two-sided p is twice the smaller tail of Binomial(n_d, ½),
        # capped at 1 (the cap bites when b == c).
        smaller = min(baseline_only, candidate_only)
        tail = sum(comb(discordant, i) for i in range(smaller + 1))
        p_value = min(1.0, 2.0 * tail / (2.0**discordant))
        return McNemarResult(
            baseline_only=baseline_only,
            candidate_only=candidate_only,
            concordant=concordant,
            statistic=statistic,
            p_value=p_value,
            method="exact",
        )

    # χ² with one degree of freedom is Z², so its upper tail is twice a
    # standard-normal upper tail at sqrt(statistic).
    p_value = min(1.0, 2.0 * _normal_upper_tail(sqrt(statistic)))
    return McNemarResult(
        baseline_only=baseline_only,
        candidate_only=candidate_only,
        concordant=concordant,
        statistic=statistic,
        p_value=p_value,
        method="chi2",
    )


def mcnemar_required_pairs(
    *,
    delta: float,
    discordance: float,
    alpha: float = 1.0 - DEFAULT_CONFIDENCE,
    power: float = 0.5,
) -> int:
    """Paired items needed to detect `delta` under McNemar (Connor 1987).

    `n = (z_{α/2}·sqrt(π_d) + z_β·sqrt(π_d - δ²))² / δ²`, where `π_d` is
    the total discordance and `δ` the difference in proportions.

    The default `power=0.5` is deliberate and is what makes this
    reproduce the **77** in `02-STANDARDS.md` §2.3: at
    `delta=discordance=0.05` — a 5-point gain with the lowest
    discordance that can produce it — the `z_β` term vanishes and `n`
    is 76.8, i.e. the smallest sample at which such a move would be
    *significant at all*. Ask for `power=0.8` and the same move needs
    155 pairs. Both numbers are an order of magnitude below
    `unpaired_required_per_arm`'s 906, which is the finding that matters;
    quoting 77 without saying it is the α-only figure would not be.

    Args:
        delta: Difference in proportions to detect, e.g. `0.05`.
            Non-zero; sign is ignored.
        discordance: `π_01 + π_10`, the fraction of items on which the
            two arms are expected to disagree. Cannot be smaller than
            `|delta|` — a 5-point difference requires at least 5 points
            of disagreement.
        alpha: Two-sided significance level.
        power: Probability of detecting the effect. `0.5` asks only for
            significance.

    Returns:
        Pairs required, rounded up.

    Raises:
        ValueError: `delta` is zero, or `discordance` is below `|delta|`
            or above 1.
    """
    magnitude = abs(delta)
    if magnitude == 0.0:
        raise ValueError("delta must be non-zero")
    if not magnitude <= discordance <= 1.0:
        raise ValueError(
            f"discordance {discordance} must lie in [|delta|={magnitude}, 1]"
        )

    z_alpha = _two_sided_z(1.0 - alpha)
    z_beta = 0.0 if power == 0.5 else _one_sided_z(power)
    numerator = z_alpha * sqrt(discordance) + z_beta * sqrt(
        discordance - magnitude * magnitude
    )
    return ceil(numerator * numerator / (magnitude * magnitude))


def unpaired_required_per_arm(
    *,
    baseline_rate: float,
    delta: float,
    alpha: float = 1.0 - DEFAULT_CONFIDENCE,
    power: float = 0.8,
) -> int:
    """Items **per arm** needed to detect `delta` without pairing.

    The standard two-proportion sample size,
    `n = (z_{α/2}·sqrt(2·p̄·q̄) + z_β·sqrt(p₁q₁ + p₂q₂))² / δ²`. At
    `baseline_rate=0.80, delta=0.05` it returns **906**, the figure
    `02-STANDARDS.md` §2.3 puts against McNemar's 77.

    This function exists to be *called*, in the gate's own report,
    beside the paired figure — a ratio a reader can see beats a ratio a
    document asserts.

    Args:
        baseline_rate: The control arm's success rate.
        delta: Absolute improvement to detect. Non-zero; sign ignored.
        alpha: Two-sided significance level.
        power: Probability of detecting the effect.

    Returns:
        Items required in each arm, rounded up.

    Raises:
        ValueError: `baseline_rate` or `baseline_rate + |delta|` falls
            outside `[0, 1]`, or `delta` is zero.
    """
    magnitude = abs(delta)
    if magnitude == 0.0:
        raise ValueError("delta must be non-zero")
    candidate_rate = baseline_rate + magnitude
    if not 0.0 <= baseline_rate <= 1.0 or not 0.0 <= candidate_rate <= 1.0:
        raise ValueError(
            f"rates {baseline_rate} and {candidate_rate} must lie in [0, 1]"
        )

    pooled = (baseline_rate + candidate_rate) / 2.0
    z_alpha = _two_sided_z(1.0 - alpha)
    z_beta = _one_sided_z(power)
    numerator = z_alpha * sqrt(2.0 * pooled * (1.0 - pooled)) + z_beta * sqrt(
        baseline_rate * (1.0 - baseline_rate)
        + candidate_rate * (1.0 - candidate_rate)
    )
    return ceil(numerator * numerator / (magnitude * magnitude))


# ---------------------------------------------------------------------------
# Paired bootstrap
# ---------------------------------------------------------------------------


class PairedSample(NamedTuple):
    """One task scored under both arms.

    Attributes:
        task_id: What was scored — a benchmark query, a scenario. Not
            used by the arithmetic; carried so a caller can say which
            task an outlier came from.
        baseline: The baseline run's values for this task. More than one
            when the campaign ran repeats.
        candidate: The candidate run's values for the **same** task.
    """

    task_id: str
    baseline: tuple[float, ...]
    candidate: tuple[float, ...]

    @property
    def delta(self) -> float:
        """Mean candidate value minus mean baseline value, for this task."""
        return fmean(self.candidate) - fmean(self.baseline)


class BootstrapResult(NamedTuple):
    """A paired bootstrap over tasks.

    Attributes:
        point: The observed mean paired delta — computed directly, not
            from the resamples, so it is exactly the number the
            aggregate table prints.
        interval: Percentile confidence interval for that delta.
        tasks: Number of paired tasks resampled.
        resamples: Bootstrap replicates drawn.
        hierarchical: True when at least one task carried more than one
            repeat, so repeats were resampled within tasks as well.
        seed: The seed used, recorded so a report can be reproduced.
    """

    point: float
    interval: Interval
    tasks: int
    resamples: int
    hierarchical: bool
    seed: int


def _percentile(sorted_values: Sequence[float], quantile: float) -> float:
    """Nearest-rank percentile of an already-sorted sequence.

    Nearest-rank rather than an interpolating definition: the bootstrap
    distribution here is discrete (10,000 draws from a handful of
    tasks), interpolation would invent values that no resample
    produced, and the rank rule is the one a reader can check by hand.
    """
    count = len(sorted_values)
    index = min(count - 1, max(0, ceil(quantile * count) - 1))
    return sorted_values[index]


def _resample_mean(values: tuple[float, ...], rng: random.Random) -> float:
    """Mean of a bootstrap resample of `values`.

    A single value is returned as-is rather than "resampled": with one
    observation there is no within-task variance to propagate, and
    drawing from a one-element population would only burn RNG state and
    make a single-repeat campaign's results depend on how many tasks
    preceded it.
    """
    if len(values) == 1:
        return values[0]
    return fmean(values[rng.randrange(len(values))] for _ in range(len(values)))


def paired_bootstrap_delta(
    samples: Sequence[PairedSample],
    *,
    seed: int = 0,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
) -> BootstrapResult:
    """Percentile confidence interval for the mean paired delta.

    Resamples **tasks** with replacement — the unit of independence is
    the benchmark query, not the score — and, when a task carries
    repeats, resamples those repeats within the drawn task too. That
    second level is what stops three repeats of one query from being
    counted as three independent observations, which would report an
    interval roughly `sqrt(3)` too narrow.

    Bootstrap rather than a t-interval because the per-task deltas of a
    quantised judge metric are lumpy and discrete, and because
    resampling makes no distributional claim the data cannot support.
    It does not repeal `CLT_MIN_DATAPOINTS`: the percentile bootstrap is
    itself an asymptotic procedure, and at 20 tasks its coverage is
    approximate. `small_sample_caveat` is what says so.

    Args:
        samples: Paired tasks. Must be non-empty, and every task must
            carry at least one value in each arm.
        seed: Seed for this call's own generator. The global `random`
            module is neither read nor disturbed.
        resamples: Bootstrap replicates.
        confidence: Two-sided confidence level.

    Returns:
        The observed delta and its interval.

    Raises:
        ValueError: `samples` is empty, `resamples` is not positive, or
            a task is missing values in an arm.
    """
    if not samples:
        raise ValueError("paired_bootstrap_delta needs at least one paired task")
    if resamples <= 0:
        raise ValueError(f"resamples must be positive, got {resamples}")
    for sample in samples:
        if not sample.baseline or not sample.candidate:
            raise ValueError(
                f"task {sample.task_id!r} has no values in one arm; a paired "
                "comparison needs both"
            )
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")

    rng = random.Random(seed)
    count = len(samples)
    point = fmean(sample.delta for sample in samples)
    hierarchical = any(
        len(sample.baseline) > 1 or len(sample.candidate) > 1 for sample in samples
    )

    replicates: list[float] = []
    if hierarchical:
        for _ in range(resamples):
            total = 0.0
            for _ in range(count):
                drawn = samples[rng.randrange(count)]
                total += _resample_mean(drawn.candidate, rng) - _resample_mean(
                    drawn.baseline, rng
                )
            replicates.append(total / count)
    else:
        # With one observation per arm per task the inner level has
        # nothing to resample, so each task contributes a fixed delta
        # and the replicate is a plain draw from those. Precomputing
        # them turns the common case into one `choices` call per
        # replicate instead of `count` interpreter round-trips — same
        # distribution, and it keeps a 20-task campaign's report inside
        # a tenth of a second.
        task_deltas = [sample.delta for sample in samples]
        for _ in range(resamples):
            replicates.append(fmean(rng.choices(task_deltas, k=count)))
    replicates.sort()

    tail = (1.0 - confidence) / 2.0
    return BootstrapResult(
        point=point,
        interval=Interval(
            _percentile(replicates, tail), _percentile(replicates, 1.0 - tail)
        ),
        tasks=count,
        resamples=resamples,
        hierarchical=hierarchical,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Honesty about N
# ---------------------------------------------------------------------------


def small_sample_caveat(datapoints: int) -> str | None:
    """The sentence a report owes its reader below `CLT_MIN_DATAPOINTS`.

    `None` above the line — the caveat is not decoration, and printing
    it on a sample that does not need it would train readers to skip it.

    Args:
        datapoints: Paired items the interval was computed from.

    Returns:
        A sentence for the report, or `None`.
    """
    if datapoints >= CLT_MIN_DATAPOINTS:
        return None
    return (
        f"**The interval above is approximate at n={datapoints}.** Below "
        f"roughly {CLT_MIN_DATAPOINTS} datapoints the central-limit "
        "approximation every interval here rests on *underestimates* "
        "uncertainty, so the true interval is wider than the one printed "
        "— not narrower. Read a bound that just excludes zero as "
        "undecided, and read this section as a floor on how uncertain "
        "the comparison is (02-STANDARDS.md §2.3)."
    )


def power_statement(
    pairs: int, *, delta: float = 0.05, baseline_rate: float = 0.80
) -> str:
    """One paragraph on what a comparison of `pairs` items can detect.

    Written to be printed unconditionally: the gate's most valuable
    output at this repository's N is the sentence saying it cannot
    separate a small move from noise, and a sentence that only appears
    on bad nights is a sentence nobody has read before the bad night.

    Args:
        pairs: Paired items available.
        delta: The effect the statement is about, e.g. a 5-point gain.
        baseline_rate: The rate that effect is measured against.

    Returns:
        Markdown, one paragraph.
    """
    needed = mcnemar_required_pairs(delta=delta, discordance=delta, power=0.5)
    powered = mcnemar_required_pairs(delta=delta, discordance=delta, power=0.8)
    unpaired = unpaired_required_per_arm(baseline_rate=baseline_rate, delta=delta)
    verdict = (
        "This comparison can support a claim about a move that size."
        if pairs >= powered
        else (
            "**This comparison cannot separate a move that size from noise.** "
            "Treat a single metric moving by one step as unexplained, not as "
            "a regression."
        )
    )
    return (
        f"**Power.** {pairs} paired {'item' if pairs == 1 else 'items'}. "
        f"Detecting a {delta:.0%} move against a baseline of {baseline_rate:.0%} "
        f"needs about **{needed} pairs** to reach significance at all, "
        f"**{powered}** at 80% power — and about **{unpaired} items per arm "
        f"unpaired**. Pairing is worth an order of magnitude, which is why "
        f"the baseline and the candidate are scored on the same items. "
        f"{verdict}"
    )


__all__ = [
    "CLT_MIN_DATAPOINTS",
    "DEFAULT_CONFIDENCE",
    "DEFAULT_RESAMPLES",
    "MCNEMAR_EXACT_MAX_DISCORDANT",
    "BootstrapResult",
    "Interval",
    "McNemarResult",
    "PairedBinaryOutcomes",
    "PairedSample",
    "mcnemar",
    "mcnemar_required_pairs",
    "pair_binary_outcomes",
    "paired_bootstrap_delta",
    "pass_hat_k",
    "power_statement",
    "rule_of_three",
    "small_sample_caveat",
    "unpaired_required_per_arm",
    "wilson_interval",
    "zero_failure_upper_bound",
]
