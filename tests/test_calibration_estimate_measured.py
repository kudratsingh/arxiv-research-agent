"""Coverage for measured-token re-estimation and its validation boundaries."""
from __future__ import annotations

import pytest

from src.calibration.estimate import MeasuredRoleTokens, reestimate_from_measurements

pytestmark = pytest.mark.unit

ROLES = ("planner", "reader", "synthesizer", "critic", "completeness", "faithfulness", "retrieval_recall")
PRICES = {"claude-sonnet-4-6": {"input": 1.0, "output": 2.0}}


def _compact() -> dict[str, dict[str, dict[str, int]]]:
    row = {"min": {"input": 10, "output": 2}, "median": {"input": 20, "output": 4}, "max": {"input": 30, "output": 6}}
    return {role: row for role in ROLES}


def test_full_measured_table_rederives_cost_and_caps() -> None:
    roles = _compact()
    roles["planner"] = MeasuredRoleTokens(input_min=10, input_median=20, input_max=30, output_min=2, output_median=4, output_max=6)
    result = reestimate_from_measurements(roles, revision_count=2, episodes=2, max_papers=3, prices=PRICES, prices_last_verified="2026-09-05")
    assert len(result.judge_lines) == 7
    assert result.campaign_cap_usd == "0.000700"
    assert result.per_episode_cap_usd == "0.000350"
    assert result.requires_repricing is True


def test_missing_role_refuses_with_key_error() -> None:
    roles = _compact(); roles.pop("critic")
    with pytest.raises(KeyError):
        reestimate_from_measurements(roles, revision_count=1, prices=PRICES, prices_last_verified="2026-09-05")


def test_zero_revisions_omits_critic_and_changes_worst_case_multiplier() -> None:
    roles = _compact()
    zero = reestimate_from_measurements(roles, revision_count=0, episodes=2, max_papers=3, prices=PRICES, prices_last_verified="2026-09-05")
    worst = reestimate_from_measurements(roles, revision_count=2, episodes=2, max_papers=3, prices=PRICES, prices_last_verified="2026-09-05")
    assert {line.label for line in zero.judge_lines} == {"planner", "reader", "synthesizer", "completeness", "faithfulness", "retrieval_recall"}
    assert float(worst.campaign_cap_usd) > float(zero.campaign_cap_usd)


def test_stale_price_date_remains_estimate() -> None:
    result = reestimate_from_measurements(_compact(), revision_count=0, prices=PRICES, prices_last_verified="2020-01-01")
    assert result.requires_repricing is True
    assert "ESTIMATE" in result.note
    assert result.prices_last_verified == "2020-01-01"


def test_bad_shape_and_counts_are_rejected() -> None:
    with pytest.raises(ValueError, match="revision_count"):
        reestimate_from_measurements(_compact(), revision_count=-1, prices=PRICES, prices_last_verified="2026-09-05")
    with pytest.raises(ValueError, match="min <= median"):
        MeasuredRoleTokens(input_min=3, input_median=2, input_max=4, output_min=1, output_median=1, output_max=1)
    malformed = _compact(); malformed["planner"] = {"input_min": 1, "input_max": 3, "output_min": 1, "output_max": 3}
    with pytest.raises((KeyError, ValueError)):
        reestimate_from_measurements(malformed, revision_count=1, prices=PRICES, prices_last_verified="2026-09-05")
