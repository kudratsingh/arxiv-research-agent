"""Unit tests for `src/eval/stats.py` — ADR 0071.

Every estimator here is checked against a value computed by hand in the
test, from the published formula, rather than against the module's own
output. That rule is what the work order means by "a bootstrap that is
only tested against itself is not tested": a snapshot of what the code
currently returns proves the code has not changed, which is a different
claim from the code being right.

Three of the checks are the headline numbers the whole design rests on
— 77 paired items, 155 at 80% power, 906 unpaired — and they are here so
`02-STANDARDS.md` §2.3's finding is reproducible from this repository
rather than only quoted in it.
"""

from __future__ import annotations

import math
import random

import pytest

from src.eval import runner as runner_module
from src.eval import simulate_learner as sim
from src.eval.stats import (
    CLT_MIN_DATAPOINTS,
    DEFAULT_RESAMPLES,
    MCNEMAR_EXACT_MAX_DISCORDANT,
    Interval,
    PairedSample,
    mcnemar,
    mcnemar_required_pairs,
    pair_binary_outcomes,
    paired_bootstrap_delta,
    pass_hat_k,
    power_statement,
    rule_of_three,
    small_sample_caveat,
    unpaired_required_per_arm,
    wilson_interval,
    zero_failure_upper_bound,
)

pytestmark = pytest.mark.unit


class TestInterval:
    def test_width_and_string_form(self) -> None:
        interval = Interval(-0.125, 0.25)
        assert interval.width == pytest.approx(0.375)
        assert str(interval) == "[-0.125, +0.250]"

    def test_excludes_zero_only_when_wholly_one_side(self) -> None:
        assert Interval(0.01, 0.2).excludes_zero() is True
        assert Interval(-0.2, -0.01).excludes_zero() is True
        assert Interval(-0.1, 0.1).excludes_zero() is False
        # A bound sitting exactly on zero does not exclude it.
        assert Interval(0.0, 0.2).excludes_zero() is False


class TestWilsonInterval:
    def test_matches_the_hand_computed_interval_at_16_of_20(self) -> None:
        # p = 0.8, n = 20, z = 1.959964.
        #   centre = (0.8 + z^2/40) / (1 + z^2/20)
        #          = 0.89604 / 1.19208            = 0.7516625
        #   half   = (z / 1.19208) * sqrt(0.16/20 + z^2/1600)
        #          = 1.6441818 * 0.1019854        = 0.1676799
        # Tolerance is 1e-5 because the reference values above were
        # computed by hand to seven figures, not because the estimator
        # is imprecise.
        interval = wilson_interval(16, 20)
        assert interval.low == pytest.approx(0.5839826, abs=1e-5)
        assert interval.high == pytest.approx(0.9193423, abs=1e-5)

    def test_a_clean_sweep_does_not_collapse_to_zero_width(self) -> None:
        # The reason Wilson is used instead of Wald: at 20/20 the Wald
        # interval is [1.0, 1.0], which asserts certainty from 20
        # observations.
        interval = wilson_interval(20, 20)
        assert interval.high == pytest.approx(1.0)
        assert interval.low < 0.85
        assert interval.width > 0.15

    def test_bounds_stay_inside_the_unit_interval_at_zero_successes(self) -> None:
        interval = wilson_interval(0, 20)
        assert interval.low == pytest.approx(0.0)
        assert 0.0 < interval.high < 1.0

    def test_a_wider_confidence_level_gives_a_wider_interval(self) -> None:
        assert wilson_interval(16, 20, confidence=0.99).width > wilson_interval(
            16, 20, confidence=0.95
        ).width

    @pytest.mark.parametrize(
        ("successes", "trials", "confidence"),
        [(1, 0, 0.95), (5, 4, 0.95), (-1, 10, 0.95), (5, 10, 1.0), (5, 10, 0.0)],
    )
    def test_invalid_input_raises(
        self, successes: int, trials: int, confidence: float
    ) -> None:
        with pytest.raises(ValueError, match="trials|successes|confidence"):
            wilson_interval(successes, trials, confidence=confidence)


class TestWilsonSharedReferenceValues:
    """The values this estimator must reproduce, for both its callers.

    ADR 0072's safety suite carried its own copy of this formula until
    `stats.py` existed. It now delegates here, keeping its own contract
    in a thin wrapper — a pinned `z` and `(0.0, 0.0)` at zero trials.
    These are the anchors: hand-computed numbers, not a comparison
    against the other implementation, so a regression in the shared
    arithmetic cannot hide by moving both.
    """

    def test_the_standards_document_s_n_100_figure(self) -> None:
        # 02-STANDARDS.md §3.2: "at n=100 an observed 3% carries a
        # Wilson interval of roughly 1.0-8.5%", which is why an absolute
        # "ASR < 5%" gate flips on noise.
        low, high = wilson_interval(3, 100)
        assert low == pytest.approx(0.0103, abs=5e-5)
        assert high == pytest.approx(0.0845, abs=5e-5)

    def test_the_safety_suite_s_own_headline(self) -> None:
        # ADR 0072's authored corpus scores 3/42 = 7.14%, reported with
        # a Wilson interval of 2.46%-19.01%. Same formula, same numbers.
        low, high = wilson_interval(3, 42)
        assert low == pytest.approx(0.0246, abs=5e-5)
        assert high == pytest.approx(0.1901, abs=5e-5)

    def test_an_empty_sample_is_refused_here_and_answered_there(self) -> None:
        # The one contract that differs, and the reason the safety suite
        # wraps this function instead of re-exporting it. A statistics
        # library asked for an interval over no observations says that
        # is not a question; a safety gate scoring an empty corpus must
        # return a verdict rather than a traceback.
        from src.eval.safety_suite import wilson_interval as safety_wilson

        with pytest.raises(ValueError, match="trials must be positive"):
            wilson_interval(0, 0)
        assert safety_wilson(0, 0) == (0.0, 0.0)

    def test_the_safety_suite_delegates_here_bit_for_bit(self) -> None:
        # The consolidation, asserted rather than assumed. The safety
        # gate's recorded baseline must not move because its arithmetic
        # was rehomed, so the wrapper passes its own pinned `Z_95`
        # through the `z` escape hatch instead of round-tripping it
        # through a confidence level -- the two differ in the last two
        # digits, and every interval that gate prints has to use the
        # same one for its difference interval to mean anything.
        from src.eval.safety_suite import Z_95
        from src.eval.safety_suite import wilson_interval as safety_wilson

        for trials in (1, 2, 7, 35, 42, 100, 199):
            for successes in (0, 1, trials // 2, trials):
                assert safety_wilson(successes, trials) == tuple(
                    wilson_interval(successes, trials, z=Z_95)
                )

    def test_the_z_escape_hatch_overrides_the_confidence_level(self) -> None:
        # A wide `z` must widen the interval even though `confidence`
        # still holds its default, or the hatch is decorative.
        default = wilson_interval(16, 20)
        wide = wilson_interval(16, 20, z=2.5758293035489004)  # two-sided 99%
        assert wide.width > default.width
        equivalent = wilson_interval(16, 20, confidence=0.99)
        assert wide.low == pytest.approx(equivalent.low, abs=1e-12)
        assert wide.high == pytest.approx(equivalent.high, abs=1e-12)


class TestRuleOfThree:
    def test_three_over_n(self) -> None:
        assert rule_of_three(20) == pytest.approx(0.15)
        assert rule_of_three(15) == pytest.approx(0.2)

    def test_the_exact_bound_is_tighter_than_the_rule_of_thumb(self) -> None:
        # 1 - 0.05 ** (1/20) = 1 - exp(ln 0.05 / 20) = 0.1391083...
        exact = zero_failure_upper_bound(20)
        assert exact == pytest.approx(1.0 - math.exp(math.log(0.05) / 20))
        assert exact == pytest.approx(0.1391083, abs=1e-6)
        # The approximation is the conservative one, which is the right
        # direction for a bound quoted in a gate.
        assert rule_of_three(20) > exact

    @pytest.mark.parametrize("trials", [0, -1])
    def test_non_positive_trials_raise(self, trials: int) -> None:
        with pytest.raises(ValueError, match="trials"):
            rule_of_three(trials)
        with pytest.raises(ValueError, match="trials"):
            zero_failure_upper_bound(trials)

    def test_an_impossible_confidence_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            zero_failure_upper_bound(20, confidence=1.0)


class TestPassHatK:
    def test_matches_the_hypergeometric_ratio_by_hand(self) -> None:
        # C(2,2)/C(3,2) = 1/3: two of three attempts succeeded, so one
        # of the three ways to draw two attempts is clean.
        assert pass_hat_k(2, 3, 2) == pytest.approx(1 / 3)
        # C(4,2)/C(5,2) = 6/10.
        assert pass_hat_k(4, 5, 2) == pytest.approx(0.6)

    def test_a_perfect_task_is_one_and_a_short_one_is_zero(self) -> None:
        assert pass_hat_k(3, 3, 3) == pytest.approx(1.0)
        assert pass_hat_k(1, 3, 2) == pytest.approx(0.0)

    def test_pass_k_falls_below_the_naive_rate_as_k_grows(self) -> None:
        # The whole point of the statistic: 4/5 reads as 0.8 at k=1 and
        # as 0.4 at k=3, because a user of a repeated workflow meets the
        # run that failed.
        assert pass_hat_k(4, 5, 1) == pytest.approx(0.8)
        assert pass_hat_k(4, 5, 3) == pytest.approx(0.4)

    @pytest.mark.parametrize(
        ("successes", "trials", "k"), [(3, 3, 0), (3, 3, 4), (4, 3, 2), (-1, 3, 2)]
    )
    def test_invalid_input_raises(self, successes: int, trials: int, k: int) -> None:
        with pytest.raises(ValueError, match="k|trials|successes"):
            pass_hat_k(successes, trials, k)


class TestMcNemar:
    def test_exact_p_value_matches_the_binomial_tail_by_hand(self) -> None:
        # b = 10, c = 2, n_d = 12. Two-sided exact p is twice the lower
        # tail of Binomial(12, 1/2) at 2:
        #   2 * (C(12,0) + C(12,1) + C(12,2)) / 2^12
        # = 2 * (1 + 12 + 66) / 4096 = 158 / 4096 = 0.03857421875
        result = mcnemar([(True, False)] * 10 + [(False, True)] * 2)
        assert result.baseline_only == 10
        assert result.candidate_only == 2
        assert result.discordant == 12
        assert result.method == "exact"
        assert result.p_value == pytest.approx(158 / 4096)

    def test_the_continuity_corrected_statistic_matches_by_hand(self) -> None:
        # Edwards: (|10 - 2| - 1)^2 / 12 = 49 / 12 = 4.0833...
        result = mcnemar([(True, False)] * 10 + [(False, True)] * 2)
        assert result.statistic == pytest.approx(49 / 12)

    def test_concordant_pairs_are_counted_but_not_tested(self) -> None:
        # McNemar ignores agreement, which is exactly why pairing pays:
        # adding 50 pairs the two arms agree on changes nothing.
        discordant = [(True, False)] * 10 + [(False, True)] * 2
        with_agreement = mcnemar(discordant + [(True, True)] * 50)
        assert with_agreement.concordant == 50
        assert with_agreement.pairs == 62
        assert with_agreement.p_value == pytest.approx(mcnemar(discordant).p_value)

    def test_a_table_with_no_disagreement_is_p_one(self) -> None:
        result = mcnemar([(True, True)] * 8 + [(False, False)] * 4)
        assert result.discordant == 0
        assert result.statistic == 0.0
        assert result.p_value == pytest.approx(1.0)

    def test_an_evenly_split_table_reports_no_evidence(self) -> None:
        # b == c, so Edwards' correction would give (0 - 1)^2 / 8 without
        # the floor. A table where the arms disagreed equally often is no
        # evidence, and the statistic says so.
        result = mcnemar([(True, False)] * 4 + [(False, True)] * 4)
        assert result.statistic == 0.0
        assert result.p_value == pytest.approx(1.0)

    def test_chi_square_branch_matches_the_normal_tail_by_hand(self) -> None:
        # b = 30, c = 10: statistic = (20 - 1)^2 / 40 = 9.025, and
        # chi-square with one degree of freedom is Z squared, so
        # P(chi2_1 > 9.025) = 2 * P(Z > 3.0041638) = 0.0026631...
        result = mcnemar([(True, False)] * 30 + [(False, True)] * 10, exact=False)
        assert result.method == "chi2"
        assert result.statistic == pytest.approx(9.025)
        assert result.p_value == pytest.approx(0.0026631, abs=1e-6)

    def test_the_method_is_chosen_by_the_discordant_count(self) -> None:
        small = mcnemar([(True, False)] * 3 + [(False, True)] * 1)
        assert small.method == "exact"
        big = mcnemar(
            [(True, False)] * (MCNEMAR_EXACT_MAX_DISCORDANT + 1)
            + [(False, True)] * 10
        )
        assert big.method == "chi2"

    def test_no_pairs_raises_rather_than_reporting_no_difference(self) -> None:
        with pytest.raises(ValueError, match="at least one pair"):
            mcnemar([])


class TestPairingBinaryOutcomes:
    """ADR 0071's answer to the question WO-A16 left open.

    `groundedness.paired_outcomes` returns `{claim_id: grounded}` keyed
    by a content-derived id that is stable across arms. Whether a claim
    present in one arm and absent from the other is discordant, or out of
    scope, moves the p-value directly — McNemar's discordant cells *are*
    the test — so it is a statistical decision and it is made here.
    """

    def test_shared_ids_become_pairs_in_id_order(self) -> None:
        pairs = pair_binary_outcomes(
            {"citation:b": True, "citation:a": False},
            {"citation:a": True, "citation:b": False},
        )
        # Sorted by id so two runs over the same data are identical.
        assert pairs.pairs == ((False, True), (True, False))
        assert pairs.matched == 2
        assert pairs.unmatched == 0

    def test_an_unmatched_claim_is_neither_concordant_nor_discordant(self) -> None:
        pairs = pair_binary_outcomes(
            {"quote:kept": True, "quote:dropped": True},
            {"quote:kept": True, "quote:added": False},
        )
        assert pairs.pairs == ((True, True),)
        assert pairs.unmatched_baseline == ("quote:dropped",)
        assert pairs.unmatched_candidate == ("quote:added",)
        # And the test statistic never sees them.
        result = mcnemar(pairs.pairs)
        assert result.pairs == 1
        assert result.discordant == 0

    def test_dropping_a_claim_does_not_score_as_a_loss(self) -> None:
        # The rejected reading: "did not make the claim" is not "failed
        # to support the claim". Scoring it as discordant would punish an
        # arm for being appropriately conservative, which is the exact
        # behaviour a groundedness metric should reward.
        conservative = pair_binary_outcomes(
            {"quote:a": True, "quote:b": True, "quote:c": True},
            {"quote:a": True},
        )
        assert mcnemar(conservative.pairs).baseline_only == 0
        assert conservative.unmatched_baseline == ("quote:b", "quote:c")

    def test_the_unmatched_count_is_reportable_rather_than_absorbed(self) -> None:
        # The reason a silent intersection was rejected: an arm that
        # stopped making claims it used to support is a movement worth
        # seeing, and it must not vanish into a shrinking denominator.
        pairs = pair_binary_outcomes(
            {f"quote:{i}": True for i in range(20)},
            {f"quote:{i}": True for i in range(14)},
        )
        assert pairs.matched == 14
        assert pairs.unmatched == 6

    def test_disjoint_arms_produce_no_pairs_at_all(self) -> None:
        pairs = pair_binary_outcomes({"quote:a": True}, {"quote:b": True})
        assert pairs.pairs == ()
        assert pairs.matched == 0
        assert pairs.unmatched == 2
        # And `mcnemar` refuses rather than reporting "no difference" —
        # two arms that share no claim have not been compared.
        with pytest.raises(ValueError, match="at least one pair"):
            mcnemar(pairs.pairs)

    def test_it_consumes_the_shape_groundedness_actually_returns(self) -> None:
        # The contract, exercised against the real projection rather than
        # against a hand-built dict that assumes it.
        from src.eval.groundedness import ClaimOutcome, GroundednessResult

        def result(*claims: ClaimOutcome) -> GroundednessResult:
            built = dict.fromkeys(GroundednessResult.__annotations__, None)
            built["claims"] = list(claims)
            return built  # type: ignore[return-value]

        def claim(claim_id: str, grounded: bool | None) -> ClaimOutcome:
            return ClaimOutcome(
                claim_id=claim_id,
                kind="citation",
                subject=claim_id,
                locator="report@0",
                grounded=grounded,
                reason="citation_resolved",
                detail="",
            )

        from src.eval.groundedness import paired_outcomes

        baseline = paired_outcomes(
            result(claim("citation:1", True), claim("citation:2", None))
        )
        candidate = paired_outcomes(
            result(claim("citation:1", False), claim("citation:3", True))
        )
        # An undecided claim is already dropped by A16, so it can never
        # reach the test as either a pair or an unmatched id.
        assert "citation:2" not in baseline
        pairs = pair_binary_outcomes(baseline, candidate)
        assert pairs.pairs == ((True, False),)
        assert pairs.unmatched_candidate == ("citation:3",)


class TestSampleSize:
    def test_reproduces_the_seventy_seven_paired_items(self) -> None:
        # 02-STANDARDS.md §2.3's headline. Connor's formula at the
        # lowest discordance a 5-point difference can have, with the
        # power term switched off: n = z^2 * pi_d / delta^2
        #                            = 3.841459 * 0.05 / 0.0025 = 76.83.
        assert mcnemar_required_pairs(delta=0.05, discordance=0.05) == 77

    def test_the_same_move_at_eighty_percent_power_needs_155(self) -> None:
        assert (
            mcnemar_required_pairs(delta=0.05, discordance=0.05, power=0.8) == 155
        )

    def test_reproduces_the_906_unpaired_items_per_arm(self) -> None:
        # Two-proportion sample size, 0.80 vs 0.85, alpha 0.05 two-sided,
        # power 0.80.
        assert unpaired_required_per_arm(baseline_rate=0.80, delta=0.05) == 906

    def test_pairing_is_worth_an_order_of_magnitude(self) -> None:
        # The finding the whole gate is designed around, asserted rather
        # than quoted — and asserted at *matched* power, so the claim
        # does not rest on comparing an alpha-only figure with a powered
        # one.
        paired = mcnemar_required_pairs(delta=0.05, discordance=0.05, power=0.8)
        unpaired = unpaired_required_per_arm(baseline_rate=0.80, delta=0.05)
        assert unpaired / paired > 5

    def test_more_disagreement_needs_more_pairs(self) -> None:
        assert mcnemar_required_pairs(
            delta=0.05, discordance=0.20
        ) > mcnemar_required_pairs(delta=0.05, discordance=0.05)

    def test_discordance_below_the_effect_is_impossible(self) -> None:
        # A 5-point difference in proportions requires at least 5 points
        # of disagreement; asking for less is a contradiction, not a
        # smaller sample.
        with pytest.raises(ValueError, match="discordance"):
            mcnemar_required_pairs(delta=0.05, discordance=0.01)

    @pytest.mark.parametrize("delta", [0.0, -0.0])
    def test_a_zero_effect_raises(self, delta: float) -> None:
        with pytest.raises(ValueError, match="delta"):
            mcnemar_required_pairs(delta=delta, discordance=0.05)
        with pytest.raises(ValueError, match="delta"):
            unpaired_required_per_arm(baseline_rate=0.8, delta=delta)

    def test_an_impossible_power_raises(self) -> None:
        # Power is a probability; 0 and 1 are not sample sizes, they are
        # a request for certainty or for nothing.
        with pytest.raises(ValueError, match="probability"):
            mcnemar_required_pairs(delta=0.05, discordance=0.05, power=0.0)
        with pytest.raises(ValueError, match="probability"):
            unpaired_required_per_arm(baseline_rate=0.8, delta=0.05, power=1.0)

    def test_a_rate_outside_the_unit_interval_raises(self) -> None:
        with pytest.raises(ValueError, match="rates"):
            unpaired_required_per_arm(baseline_rate=0.98, delta=0.05)


class TestPairedBootstrap:
    def test_identical_arms_give_a_zero_width_interval(self) -> None:
        # ADR 0071's acceptance criterion, in its purest form: nothing
        # moved, so no resample can move it.
        samples = [
            PairedSample(f"t{i}", (0.5, 0.5, 0.5), (0.5, 0.5, 0.5)) for i in range(5)
        ]
        result = paired_bootstrap_delta(samples, seed=1, resamples=500)
        assert result.point == pytest.approx(0.0)
        assert result.interval.width == pytest.approx(0.0)
        assert result.hierarchical is True

    def test_the_point_estimate_is_the_exact_mean_paired_delta(self) -> None:
        # Computed directly rather than from the replicates, so the
        # number the report prints is the number the data says.
        samples = [
            PairedSample("a", (0.4,), (0.6,)),
            PairedSample("b", (0.8, 0.6), (0.5, 0.5)),
        ]
        # a: +0.2; b: mean(0.5, 0.5) - mean(0.8, 0.6) = 0.5 - 0.7 = -0.2
        result = paired_bootstrap_delta(samples, seed=0, resamples=200)
        assert result.point == pytest.approx(0.0)

    def test_a_single_task_cannot_disagree_with_itself(self) -> None:
        result = paired_bootstrap_delta(
            [PairedSample("only", (0.2,), (0.7,))], seed=3, resamples=200
        )
        assert result.point == pytest.approx(0.5)
        assert result.interval.low == pytest.approx(0.5)
        assert result.interval.high == pytest.approx(0.5)
        assert result.interval.width == pytest.approx(0.0)
        assert result.hierarchical is False

    def test_the_two_task_distribution_matches_the_binomial_by_hand(self) -> None:
        # Two tasks with deltas 0.0 and 0.4. Resampling two tasks with
        # replacement can only produce means 0.0, 0.2 or 0.4, with
        # probabilities 1/4, 1/2 and 1/4 — a Binomial(2, 1/2) in
        # disguise. So the 2.5th percentile must be 0.0 and the 97.5th
        # must be 0.4, and the middle mass must be near a half.
        samples = [
            PairedSample("a", (0.0,), (0.0,)),
            PairedSample("b", (0.0,), (0.4,)),
        ]
        result = paired_bootstrap_delta(samples, seed=7, resamples=DEFAULT_RESAMPLES)
        assert result.point == pytest.approx(0.2)
        assert result.interval.low == pytest.approx(0.0)
        assert result.interval.high == pytest.approx(0.4)

        # And the replicate distribution itself, recomputed here rather
        # than trusted: the same draws, done independently.
        rng = random.Random(7)
        deltas = [0.0, 0.4]
        counts = {0.0: 0, 0.2: 0, 0.4: 0}
        for _ in range(DEFAULT_RESAMPLES):
            counts[round(sum(rng.choices(deltas, k=2)) / 2, 1)] += 1
        assert counts[0.2] / DEFAULT_RESAMPLES == pytest.approx(0.5, abs=0.02)
        assert counts[0.0] / DEFAULT_RESAMPLES == pytest.approx(0.25, abs=0.02)

    def test_repeats_widen_the_interval_rather_than_narrowing_it(self) -> None:
        # The failure the hierarchical level exists to prevent. Treating
        # three repeats of one task as three independent tasks would
        # report an interval about sqrt(3) too narrow; resampling within
        # the task keeps the extra variance visible.
        spread = [
            PairedSample("a", (0.5, 0.5, 0.5), (0.9, 0.5, 0.1)),
            PairedSample("b", (0.5, 0.5, 0.5), (0.9, 0.5, 0.1)),
        ]
        tight = [
            PairedSample("a", (0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
            PairedSample("b", (0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
        ]
        assert (
            paired_bootstrap_delta(spread, seed=5, resamples=2000).interval.width
            > paired_bootstrap_delta(tight, seed=5, resamples=2000).interval.width
        )

    def test_the_same_seed_gives_the_same_interval(self) -> None:
        samples = [
            PairedSample("a", (0.1,), (0.4,)),
            PairedSample("b", (0.2,), (0.2,)),
            PairedSample("c", (0.9,), (0.3,)),
        ]
        first = paired_bootstrap_delta(samples, seed=11, resamples=1000)
        second = paired_bootstrap_delta(samples, seed=11, resamples=1000)
        assert first.interval == second.interval

    def test_the_call_does_not_disturb_the_global_generator(self) -> None:
        # `seed_campaign` pins `random` for the whole campaign; a gate
        # that consumed from it would make the campaign's own draws
        # depend on whether a report was rendered.
        random.seed(1234)
        expected = [random.random() for _ in range(3)]
        random.seed(1234)
        paired_bootstrap_delta(
            [PairedSample("a", (0.1,), (0.4,)), PairedSample("b", (0.2,), (0.3,))],
            seed=99,
            resamples=100,
        )
        assert [random.random() for _ in range(3)] == expected

    def test_no_samples_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one paired task"):
            paired_bootstrap_delta([])

    def test_a_task_missing_an_arm_raises(self) -> None:
        with pytest.raises(ValueError, match="no values in one arm"):
            paired_bootstrap_delta([PairedSample("a", (), (0.5,))])

    @pytest.mark.parametrize(
        ("resamples", "confidence", "match"),
        [(0, 0.95, "resamples"), (10, 1.0, "confidence")],
    )
    def test_invalid_parameters_raise(
        self, resamples: int, confidence: float, match: str
    ) -> None:
        with pytest.raises(ValueError, match=match):
            paired_bootstrap_delta(
                [PairedSample("a", (0.1,), (0.2,))],
                resamples=resamples,
                confidence=confidence,
            )


class TestHonestyAboutN:
    def test_the_caveat_fires_in_this_repository_s_regime(self) -> None:
        caveat = small_sample_caveat(20)
        assert caveat is not None
        assert "n=20" in caveat
        assert "underestimates" in caveat

    def test_the_caveat_is_silent_where_it_does_not_apply(self) -> None:
        assert small_sample_caveat(CLT_MIN_DATAPOINTS) is None
        assert small_sample_caveat(CLT_MIN_DATAPOINTS + 1) is None
        assert small_sample_caveat(CLT_MIN_DATAPOINTS - 1) is not None

    def test_the_power_statement_names_all_three_numbers(self) -> None:
        statement = power_statement(20)
        assert "20 paired items" in statement
        assert "77 pairs" in statement
        assert "155" in statement
        assert "906" in statement
        assert "cannot separate" in statement

    def test_the_power_statement_flips_once_the_sample_is_large_enough(self) -> None:
        statement = power_statement(500)
        assert "cannot separate" not in statement
        assert "can support a claim" in statement

    def test_one_pair_reads_as_singular(self) -> None:
        assert "1 paired item." in power_statement(1)


class TestRepeatPolicyIsShared:
    def test_both_lanes_quote_the_same_repeat_bar(self) -> None:
        # The constant is declared twice — `simulate_learner` imports
        # `runner`, so a shared home would have to be `runner` and that
        # is a change ADR 0071 did not need to make. This is the test
        # that stops the two copies from drifting.
        assert runner_module.REPEATS_FOR_CONFIDENCE == sim.REPEATS_FOR_CONFIDENCE == 3

    def test_the_research_lane_warns_below_the_bar_and_is_silent_at_it(self) -> None:
        warning = runner_module.repeat_warning(1)
        assert warning is not None
        assert "1 repeat(s) per query" in warning
        assert runner_module.repeat_warning(3) is None
        assert runner_module.repeat_warning(5) is None
