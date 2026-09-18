"""Variance views preserve query difficulty and query-first resampling."""

from types import SimpleNamespace

import pytest

from src.campaign.report import _variance_intervals, _variance_rows

pytestmark = pytest.mark.unit


def _record(query: str, score: float, repeat: int) -> SimpleNamespace:
    return SimpleNamespace(
        case_id=query,
        arm_id="A",
        scores={"metrics": {"completeness": {"score": score}}},
        repeat_index=repeat,
    )


def test_query_first_interval_exposes_between_query_spread_and_is_seeded() -> None:
    records = [
        *[_record("easy", 0.0, repeat) for repeat in range(4)],
        *[_record("hard", 1.0, repeat) for repeat in range(4)],
    ]
    rows = _variance_rows(records)
    completeness = [row for row in rows if row.metric_id == "completeness"]
    assert sum(row.episodes_scored for row in completeness) == 8
    assert {row.mean for row in completeness} == {0.0, 1.0}

    first = _variance_intervals(records, seed=17, resamples=500)
    second = _variance_intervals(records, seed=17, resamples=500)
    assert first == second
    interval = next(row for row in first if row.metric_id == "completeness")
    assert interval.interval_low < interval.point < interval.interval_high


def test_explicit_null_judge_score_is_not_zero() -> None:
    record = _record("unscored", 0.0, 0)
    record.scores = {"metrics": {"completeness": {"score": None, "reason": "judge_timeout"}}}
    assert _variance_rows([record]) == ()
