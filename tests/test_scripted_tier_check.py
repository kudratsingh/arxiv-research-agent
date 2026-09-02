"""Unit tests for the per-PR scripted-tier assertion.

The check itself is what CI trusts, so it needs its own mutation tests:
each case breaks exactly one property of a clean campaign and asserts
the check notices. Pure logic — no graph, no network, no spend.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.eval import scripted_tier_check as check
from src.eval.learning_benchmark import LEARNING_SCENARIOS

pytestmark = pytest.mark.unit


def _row(record_id: str = "s.r1", **overrides: Any) -> dict[str, Any]:
    """A clean scripted-tier summary row."""
    row: dict[str, Any] = {
        "record_id": record_id,
        "scenario_id": record_id.split(".")[0],
        "tier": "scripted",
        "error": None,
        "metrics_error": None,
        "expectation_failures": 0,
        "cost_usd": 0,
        "llm_calls": 0,
        "learner_cost_usd": 0.0,
        "learner_llm_calls": 0,
        "judge_cost_usd": None,
        "judge_llm_calls": None,
        "total_cost_usd": 0.0,
    }
    row.update(overrides)
    return row


def _clean(count: int = 3) -> list[dict[str, Any]]:
    return [_row(f"s{i}.r1") for i in range(count)]


class TestCleanCampaign:
    def test_a_clean_campaign_has_no_problems(self) -> None:
        assert check.check_rows(_clean(), expected_sessions=3) == []

    def test_null_cost_columns_are_treated_as_zero(self) -> None:
        # The judges do not run in the scripted tier, so their columns
        # are `null` rather than `0` — that is absence, not spend.
        rows = [_row(judge_cost_usd=None, judge_llm_calls=None)]
        assert check.check_rows(rows, expected_sessions=1) == []

    def test_total_spend_sums_the_rows(self) -> None:
        rows = [_row("a.r1", total_cost_usd=0.5), _row("b.r1", total_cost_usd=0.25)]
        assert check.total_spend(rows) == 0.75


class TestMutations:
    def test_a_short_campaign_fails(self) -> None:
        problems = check.check_rows(_clean(12), expected_sessions=15)
        assert any("did not run the whole benchmark" in p for p in problems)

    def test_an_errored_session_fails(self) -> None:
        rows = _clean(1)
        rows[0]["error"] = "RuntimeError: boom"
        problems = check.check_rows(rows, expected_sessions=1)
        assert any("errored" in p for p in problems)

    def test_a_scoring_failure_fails(self) -> None:
        rows = _clean(1)
        rows[0]["metrics_error"] = "judge timed out"
        problems = check.check_rows(rows, expected_sessions=1)
        assert any("scoring failed" in p for p in problems)

    def test_the_funded_tier_is_not_accepted_here(self) -> None:
        rows = _clean(1)
        rows[0]["tier"] = "funded"
        problems = check.check_rows(rows, expected_sessions=1)
        assert any("not 'scripted'" in p for p in problems)

    @pytest.mark.parametrize("field", check.COST_FIELDS)
    def test_any_non_zero_cost_column_fails(self, field: str) -> None:
        rows = _clean(1)
        rows[0][field] = 0.02
        problems = check.check_rows(rows, expected_sessions=1)
        assert any(field in p for p in problems)

    @pytest.mark.parametrize("field", check.CALL_FIELDS)
    def test_any_non_zero_call_count_fails(self, field: str) -> None:
        rows = _clean(1)
        rows[0][field] = 1
        problems = check.check_rows(rows, expected_sessions=1)
        assert any("something reached a model" in p for p in problems)

    def test_a_sub_cent_spend_still_fails_on_the_call_count(self) -> None:
        # A dollar figure can round to $0.0000; a call count cannot.
        rows = _clean(1)
        rows[0]["llm_calls"] = 2
        rows[0]["cost_usd"] = 0.00001
        problems = check.check_rows(rows, expected_sessions=1)
        assert any("llm_calls" in p for p in problems)

    def test_an_unmet_expectation_fails(self) -> None:
        rows = _clean(1)
        rows[0]["expectation_failures"] = 1
        problems = check.check_rows(rows, expected_sessions=1)
        assert any("unmet structural expectation" in p for p in problems)

    def test_all_problems_are_reported_not_just_the_first(self) -> None:
        rows = _clean(1)
        rows[0]["error"] = "boom"
        rows[0]["cost_usd"] = 1.0
        rows[0]["expectation_failures"] = 2
        assert len(check.check_rows(rows, expected_sessions=1)) >= 3


class TestCLI:
    def _write(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )

    def test_clean_summary_exits_0(self, tmp_path: Path, capsys: Any) -> None:
        path = tmp_path / "summary.jsonl"
        self._write(path, _clean(2))
        assert check.main([str(path), "--expected-sessions", "2"]) == 0
        assert "$0.0000 spent" in capsys.readouterr().out

    def test_dirty_summary_exits_1(self, tmp_path: Path, capsys: Any) -> None:
        path = tmp_path / "summary.jsonl"
        rows = _clean(1)
        rows[0]["cost_usd"] = 0.5
        self._write(path, rows)
        assert check.main([str(path), "--expected-sessions", "1"]) == 1
        assert "FAILED" in capsys.readouterr().err

    def test_missing_summary_exits_2(self, tmp_path: Path, capsys: Any) -> None:
        assert check.main([str(tmp_path / "nope.jsonl")]) == 2
        assert "not found" in capsys.readouterr().err

    def test_malformed_summary_exits_2(self, tmp_path: Path) -> None:
        path = tmp_path / "summary.jsonl"
        path.write_text("not json\n", encoding="utf-8")
        assert check.main([str(path)]) == 2

    def test_the_default_session_count_is_the_benchmark_size(
        self, tmp_path: Path
    ) -> None:
        # The CI step passes no --expected-sessions, so the default has
        # to track the benchmark rather than a hard-coded 15.
        path = tmp_path / "summary.jsonl"
        self._write(path, _clean(len(LEARNING_SCENARIOS)))
        assert check.main([str(path)]) == 0
