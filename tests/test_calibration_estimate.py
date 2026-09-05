"""Unit tests for `src/calibration/estimate.py` — P0-WO10.

12 §16 asks for a cost/time estimate template with stop conditions, and
12 §18 lists what a funded request must present. These tests hold the
template to both, and to the constraint that outranks them: nothing here
can be turned into an approval, and no call has been made.

Every test supplies its own `today`. The module reads no clock, because
an estimate whose staleness warning depends on when it is rendered is not
a document anyone can review twice.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.calibration.estimate import (
    CALIBRATION_STOP_CONDITIONS,
    PRICE_FRESHNESS_DAYS,
    CostEstimate,
    ExpertTimeLine,
    JudgeCallLine,
    StopCondition,
    current_price_table,
    default_example,
    price_staleness,
    render,
    total_lines,
    worked_example,
)

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 5)


def _revalidate(estimate: CostEstimate, **overrides: object) -> CostEstimate:
    """Round-trip an estimate through JSON with fields replaced.

    Through JSON rather than `model_validate` on a dict, because
    `StrictContractModel` is strict: a Python list is not a tuple, and a
    JSON array is the tuple's wire form.
    """
    payload = {**estimate.model_dump(mode="json"), **overrides}
    return CostEstimate.model_validate_json(json.dumps(payload))


@pytest.fixture(scope="module")
def prices() -> dict[str, dict[str, float]]:
    table, _ = current_price_table()
    return table


@pytest.fixture(scope="module")
def example() -> CostEstimate:
    return default_example(items=141, pairwise_items=40, priced_on="2026-09-05")


class TestThePriceTableIsReadNotCopied:
    def test_the_table_is_the_products_own(self, prices: dict[str, dict[str, float]]) -> None:
        from src.observability.costs import PRICES_USD_PER_MILLION

        assert prices == {
            model: dict(row) for model, row in PRICES_USD_PER_MILLION.items()
        }

    def test_the_verification_date_comes_with_it(self) -> None:
        from src.observability.costs import PRICES_LAST_VERIFIED

        _, verified = current_price_table()

        assert verified == PRICES_LAST_VERIFIED

    def test_a_model_outside_the_table_is_refused_rather_than_falling_back(
        self, prices: dict[str, dict[str, float]]
    ) -> None:
        """`costs.py` falls back to Sonnet at runtime so a live call is
        never unpriced. An estimate built on that fallback would
        under-report by up to 3.3x with nothing in the number to say so."""
        with pytest.raises(KeyError, match="under-report"):
            worked_example(
                items=10,
                pairwise_items=2,
                prices=prices,
                prices_last_verified="2026-08-20",
                priced_on="2026-09-05",
                judge_model="some-model-nobody-priced",
            )

    def test_a_line_priced_at_a_missing_model_raises(self) -> None:
        line = JudgeCallLine(
            label="x",
            model_id="not-in-the-table",
            calls=1,
            input_tokens_per_call=1000,
            output_tokens_per_call=100,
            note="n",
        )

        with pytest.raises(KeyError):
            line.cost_usd({"claude-sonnet-5": {"input": 3.0, "output": 15.0}})


class TestTheArithmetic:
    def test_one_line_costs_what_the_table_says(self) -> None:
        line = JudgeCallLine(
            label="single-item verdicts",
            model_id="claude-sonnet-5",
            calls=100,
            input_tokens_per_call=2000,
            output_tokens_per_call=200,
            note="n",
        )
        # 100 * 2000 = 200,000 input tokens at $3/M = $0.60
        # 100 *  200 =  20,000 output tokens at $15/M = $0.30
        assert line.cost_usd(
            {"claude-sonnet-5": {"input": 3.0, "output": 15.0}}
        ) == Decimal("0.900000")

    def test_zero_calls_cost_nothing(self) -> None:
        line = JudgeCallLine(
            label="x",
            model_id="claude-sonnet-5",
            calls=0,
            input_tokens_per_call=2000,
            output_tokens_per_call=200,
            note="n",
        )

        assert line.cost_usd({"claude-sonnet-5": {"input": 3.0, "output": 15.0}}) == Decimal(
            "0.000000"
        )

    def test_expert_hours_multiply_items_minutes_and_annotators(self) -> None:
        line = ExpertTimeLine(
            label="x",
            role="annotator",
            items=120,
            minutes_per_item=6.0,
            annotators_per_item=2,
            note="n",
        )

        assert line.minutes == pytest.approx(1440.0)
        assert line.hours == pytest.approx(24.0)

    def test_the_worked_example_totals_are_reproducible(
        self, example: CostEstimate, prices: dict[str, dict[str, float]]
    ) -> None:
        # 141 + 141 single-item calls at 2200/200 tokens plus 80 pairwise
        # calls at 3600/200, all on the same model.
        assert example.model_cost_usd(prices) == sum(
            line.cost_usd(prices) for line in example.judge_lines
        )
        assert example.expert_hours == pytest.approx(
            sum(line.hours for line in example.expert_lines)
        )

    def test_expert_time_is_the_binding_constraint_not_the_dollars(
        self, example: CostEstimate, prices: dict[str, dict[str, float]]
    ) -> None:
        """The finding the template exists to make visible: at these item
        counts the model spend is a rounding error against a week of
        expert time, so an estimate reporting only dollars would answer
        the easy question."""
        assert example.model_cost_usd(prices) < Decimal("10")
        assert example.expert_hours > 40


class TestStaleness:
    def test_a_fresh_table_produces_no_note(self) -> None:
        assert price_staleness("2026-09-01", today=TODAY) is None

    def test_the_boundary_is_inclusive(self) -> None:
        verified = date(2026, 8, 20)
        assert price_staleness("2026-08-20", today=verified) is None
        # Exactly PRICE_FRESHNESS_DAYS later is still fresh; one more is not.
        assert PRICE_FRESHNESS_DAYS == 30
        assert price_staleness("2026-08-20", today=date(2026, 9, 19)) is None
        assert price_staleness("2026-08-20", today=date(2026, 9, 20)) is not None

    def test_an_old_table_produces_a_note_naming_the_gap(self) -> None:
        note = price_staleness("2026-06-01", today=TODAY)

        assert note is not None
        assert "2026-06-01" in note
        assert "96 days" in note
        assert "re-derived" in note

    def test_a_malformed_date_is_refused(self) -> None:
        with pytest.raises(ValueError):
            price_staleness("last Tuesday", today=TODAY)

    def test_the_staleness_note_reaches_the_rendered_estimate(
        self, example: CostEstimate
    ) -> None:
        rendered = render(example, today=date(2027, 1, 1))

        assert "STALE PRICES" in rendered


class TestNothingHereIsAnApproval:
    def test_the_estimate_always_requires_repricing(self, example: CostEstimate) -> None:
        assert example.requires_repricing is True

        with pytest.raises(ValidationError):
            _revalidate(example, requires_repricing=False)

    def test_the_estimate_always_says_the_campaign_has_not_started(
        self, example: CostEstimate
    ) -> None:
        assert example.campaign_started is False

        with pytest.raises(ValidationError):
            _revalidate(example, campaign_started=True)

    def test_there_is_no_approved_field_to_set(self, example: CostEstimate) -> None:
        assert "approved" not in example.model_dump()
        assert "approved_by" not in example.model_dump()

    def test_the_rendered_estimate_says_so_first_and_last(
        self, example: CostEstimate
    ) -> None:
        lines = render(example, today=TODAY).splitlines()

        assert lines[0].startswith("ESTIMATE ONLY — NOT AN APPROVAL")
        assert "NOTHING IN THIS ESTIMATE HAS BEEN RUN" in lines[-1]
        assert "D9" in lines[-1]


class TestStopConditions:
    def test_an_estimate_without_stop_conditions_is_refused(
        self, example: CostEstimate
    ) -> None:
        with pytest.raises(ValidationError, match="a budget, not a plan"):
            _revalidate(example, stop_conditions=[])

    def test_a_per_episode_cap_above_the_campaign_cap_is_refused(
        self, example: CostEstimate
    ) -> None:
        with pytest.raises(ValidationError, match="cannot exceed the campaign cap"):
            _revalidate(example, per_episode_cap_usd="500.000000")

    def test_duplicate_condition_ids_are_refused(self, example: CostEstimate) -> None:
        first = example.model_dump(mode="json")["stop_conditions"][0]

        with pytest.raises(ValidationError, match="ids must be unique"):
            _revalidate(example, stop_conditions=[first, first])

    def test_every_condition_names_an_action_rather_than_investigate(self) -> None:
        for condition in CALIBRATION_STOP_CONDITIONS:
            assert condition.on_trigger
            assert "investigate" not in condition.on_trigger.lower()

    def test_the_conditions_cover_money_time_instrument_and_integrity(self) -> None:
        ids = {condition.condition_id for condition in CALIBRATION_STOP_CONDITIONS}

        assert {
            "campaign-cap-reached",
            "episode-cap-reached",
            "expert-budget-reached",
            "instrument-moved",
            "blinding-breach",
            "annotator-disagreement-collapse",
            "labels-would-be-edited",
        } <= ids

    def test_a_stopped_campaign_publishes_rather_than_restarting(self) -> None:
        """07 §9: stopping is an experiment outcome."""
        cap = next(
            condition
            for condition in CALIBRATION_STOP_CONDITIONS
            if condition.condition_id == "campaign-cap-reached"
        )

        assert "publish" in cap.on_trigger
        assert "outcome" in cap.on_trigger

    def test_the_label_editing_condition_refuses_rather_than_escalating(self) -> None:
        rule = next(
            condition
            for condition in CALIBRATION_STOP_CONDITIONS
            if condition.condition_id == "labels-would-be-edited"
        )

        assert rule.on_trigger.startswith("Refuse")
        assert "superseding record" in rule.on_trigger


class TestTheRenderedPacket:
    def test_it_names_the_exact_model_it_was_costed_on(self, example: CostEstimate) -> None:
        rendered = render(example, today=TODAY)

        assert "claude-sonnet-5" in rendered

    def test_it_states_the_overshoot_behaviour(self, example: CostEstimate) -> None:
        rendered = render(example, today=TODAY)

        assert "overshoot" in rendered
        assert "concurrency unit" in rendered

    def test_it_reports_both_caps(self, example: CostEstimate) -> None:
        rendered = render(example, today=TODAY)

        assert "per episode" in rendered
        assert "per campaign" in rendered

    def test_it_reports_expert_time_beside_the_dollars(self, example: CostEstimate) -> None:
        rendered = render(example, today=TODAY)

        assert "total model spend" in rendered
        assert "total expert time" in rendered

    def test_several_estimates_are_rendered_without_being_summed(
        self, example: CostEstimate
    ) -> None:
        """Two estimates with different caps and stop rules do not add up
        to one campaign, and a combined total is the number an approval
        would get read from."""
        lines = total_lines([example, example], today=TODAY)

        assert lines.count("ESTIMATE ONLY — NOT AN APPROVAL (judge-calibration-pilot@1.0.0)") == 2
        assert not any("grand total" in line.lower() for line in lines)

    def test_the_estimate_exceeds_cap_check_uses_the_declared_ceiling(
        self, example: CostEstimate, prices: dict[str, dict[str, float]]
    ) -> None:
        assert example.exceeds_cap(prices) is False

        tightened = _revalidate(
            example, per_episode_cap_usd="0.010000", campaign_cap_usd="1.000000"
        )

        assert tightened.exceeds_cap(prices) is True


class TestTheTemplateIsUsableWithoutTheProductsTable:
    def test_a_caller_may_supply_its_own_prices(self) -> None:
        estimate = worked_example(
            items=10,
            pairwise_items=2,
            prices={"claude-sonnet-5": {"input": 1.0, "output": 2.0}},
            prices_last_verified="2026-09-01",
            priced_on="2026-09-05",
        )

        assert estimate.model_cost_usd(
            {"claude-sonnet-5": {"input": 1.0, "output": 2.0}}
        ) > Decimal("0")

    def test_a_stop_condition_is_its_own_reviewable_object(self) -> None:
        condition = StopCondition(
            condition_id="a-new-rule",
            trigger="Something observable happens.",
            on_trigger="Something specific is done about it.",
        )

        assert condition.condition_id == "a-new-rule"
