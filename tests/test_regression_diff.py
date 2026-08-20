"""Unit tests for the regression diff.

Pure logic — no network, no file IO except via `tmp_path`. Covers
JSONL loading (including missing-file graceful fallback), per-query
status classification, aggregate rollups, and the markdown renderer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.eval.regression_diff import (
    DEFAULT_THRESHOLD,
    RESOURCE_THRESHOLDS,
    QueryDiff,
    RegressionReport,
    diff_summaries,
    format_report,
    load_summary,
    main,
)

pytestmark = pytest.mark.unit


def _line(
    query_id: str,
    *,
    citation_accuracy: float | None = None,
    completeness: float | None = None,
    faithfulness: float | None = None,
    critic_score: float | None = None,
    iterations: float | None = None,
    llm_calls: float | None = None,
    cost_usd: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "citation_accuracy": citation_accuracy,
        "completeness": completeness,
        "faithfulness": faithfulness,
        "critic_score": critic_score,
        "iterations": iterations,
        "llm_calls": llm_calls,
        "cost_usd": cost_usd,
        "error": error,
    }


class TestLoadSummary:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_summary(tmp_path / "nope.jsonl") == {}

    def test_reads_jsonl_indexed_by_query_id(self, tmp_path: Path) -> None:
        path = tmp_path / "summary.jsonl"
        path.write_text(
            json.dumps({"query_id": "q1", "citation_accuracy": 0.9}) + "\n"
            + json.dumps({"query_id": "q2", "citation_accuracy": 0.7}) + "\n"
        )
        result = load_summary(path)
        assert set(result) == {"q1", "q2"}
        assert result["q1"]["citation_accuracy"] == 0.9

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "summary.jsonl"
        path.write_text(
            json.dumps({"query_id": "q1"}) + "\n"
            + "\n"
            + json.dumps({"query_id": "q2"}) + "\n"
        )
        assert set(load_summary(path)) == {"q1", "q2"}

    def test_malformed_json_raises_valueerror(self, tmp_path: Path) -> None:
        path = tmp_path / "summary.jsonl"
        path.write_text("not json\n")
        with pytest.raises(ValueError, match="line 1"):
            load_summary(path)

    def test_missing_query_id_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "summary.jsonl"
        path.write_text(json.dumps({"citation_accuracy": 0.9}) + "\n")
        with pytest.raises(ValueError, match="query_id"):
            load_summary(path)


class TestDiffSummariesClassification:
    def test_unchanged_when_scores_within_threshold(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.80, completeness=0.75, faithfulness=0.70)}
        current = {"q1": _line("q1", citation_accuracy=0.82, completeness=0.73, faithfulness=0.72)}
        report = diff_summaries(baseline, current, threshold=0.1)
        assert report["diffs"][0]["status"] == "unchanged"
        assert report["has_regressions"] is False

    def test_regression_when_metric_drops_beyond_threshold(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.9, completeness=0.8, faithfulness=0.8)}
        current = {"q1": _line("q1", citation_accuracy=0.9, completeness=0.5, faithfulness=0.8)}
        report = diff_summaries(baseline, current, threshold=0.1)
        assert report["diffs"][0]["status"] == "regressed"
        assert report["has_regressions"] is True

    def test_improvement_when_metric_rises_beyond_threshold(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.5, completeness=0.5, faithfulness=0.5)}
        current = {"q1": _line("q1", citation_accuracy=0.8, completeness=0.5, faithfulness=0.5)}
        report = diff_summaries(baseline, current, threshold=0.1)
        assert report["diffs"][0]["status"] == "improved"
        assert report["has_regressions"] is False

    # Direction-aware: cost / iterations / llm_calls are `lower_better`
    # and judged by their RESOURCE_THRESHOLDS bands (absolute floor AND
    # relative fraction), never by `--threshold` (ADR 0044).
    def test_cost_rising_beyond_band_is_regression(self) -> None:
        # +$0.40 on $0.10: clears the $0.10 floor and the 25% band.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=0.10)}
        current = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=0.50)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"
        assert report["has_regressions"] is True

    def test_cost_dropping_beyond_band_is_improvement(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=0.50)}
        current = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=0.10)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "improved"
        assert report["has_regressions"] is False

    def test_iteration_runaway_is_regression(self) -> None:
        # loop-induced iteration runaway must show up as a regression.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, iterations=1)}
        current = {"q1": _line("q1", citation_accuracy=0.8, iterations=5)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_llm_call_runaway_is_regression(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=30)}
        current = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=90)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_cost_below_absolute_floor_is_unchanged(self) -> None:
        # +$0.05 is under the $0.10 floor even though it's +50% relative.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=0.10)}
        current = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=0.15)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"


class TestResourceBands:
    """Every classification branch of the ADR 0044 two-leg band model.

    The single-extra-call / single-extra-iteration / proportional-rise
    cases are the mutation checks for this change: each one classified
    as `regressed` under the pre-ADR-0044 code (any rise > 0.10 fired)
    and must classify as `unchanged` now.
    """

    def test_one_extra_llm_call_is_not_regression(self) -> None:
        # The audit's canonical false alarm: arXiv returns one more
        # rankable paper, the reader makes one more call.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=42)}
        current = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=43)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"
        assert report["has_regressions"] is False

    def test_one_extra_critic_revision_is_not_regression(self) -> None:
        # iterations 1 -> 2 is ordinary critic nondeterminism.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, iterations=1)}
        current = {"q1": _line("q1", citation_accuracy=0.8, iterations=2)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"

    def test_two_extra_iterations_regress(self) -> None:
        # +2 clears the floor of 1 and is +200% relative.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, iterations=1)}
        current = {"q1": _line("q1", citation_accuracy=0.8, iterations=3)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_llm_calls_over_floor_but_proportionally_small_is_unchanged(
        self,
    ) -> None:
        # +6 calls clears the floor of 4 but is only +6% on a baseline
        # of 100 — the relative leg absorbs drift on large baselines.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=100)}
        current = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=106)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"

    def test_llm_calls_clearing_both_legs_regress(self) -> None:
        # +5 on 12: over the floor of 4 and +42% relative.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=12)}
        current = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=17)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_llm_calls_dropping_beyond_band_is_improvement(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=17)}
        current = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=12)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "improved"

    def test_cost_over_floor_but_proportionally_small_is_unchanged(self) -> None:
        # +$0.15 on a $1.00 baseline clears the floor but is only +15%.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=1.00)}
        current = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=1.15)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"

    def test_cost_clearing_both_legs_regresses(self) -> None:
        # +$0.14 on $0.31: over the $0.10 floor and +45% relative.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=0.31)}
        current = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=0.45)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_zero_baseline_falls_back_to_absolute_floor(self) -> None:
        # No meaningful denominator — the floor alone decides.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=0.0)}
        current = {"q1": _line("q1", citation_accuracy=0.8, cost_usd=0.50)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_score_threshold_does_not_gate_resource_metrics(self) -> None:
        # A permissive --threshold must not mute a genuine call runaway.
        baseline = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=12)}
        current = {"q1": _line("q1", citation_accuracy=0.8, llm_calls=30)}
        report = diff_summaries(baseline, current, threshold=5.0)
        assert report["diffs"][0]["status"] == "regressed"

    def test_resource_bands_cover_all_lower_better_metrics(self) -> None:
        # Any metric declared lower_better without a band would silently
        # fall back to the score epsilon — the exact bug ADR 0044 fixes.
        from src.eval.regression_diff import METRIC_DIRECTIONS

        lower_better = {
            field
            for field, direction in METRIC_DIRECTIONS.items()
            if direction == "lower_better"
        }
        assert lower_better == set(RESOURCE_THRESHOLDS)

    def test_new_query_in_current(self) -> None:
        baseline: dict[str, dict[str, Any]] = {}
        current = {"q1": _line("q1", citation_accuracy=0.9)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "new"
        assert report["has_regressions"] is False

    def test_removed_query_in_baseline(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.9)}
        current: dict[str, dict[str, Any]] = {}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "removed"

    def test_errored_status_when_current_has_new_error(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.9)}
        current = {"q1": _line("q1", error="RuntimeError: bad")}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "errored"
        assert report["has_regressions"] is True

    def test_recovered_status_when_baseline_had_error(self) -> None:
        baseline = {"q1": _line("q1", error="prior error")}
        current = {"q1": _line("q1", citation_accuracy=0.9)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "recovered"
        assert report["has_regressions"] is False


class TestDiffSummariesDeltas:
    def test_per_metric_deltas_computed(self) -> None:
        baseline = {
            "q1": _line(
                "q1",
                citation_accuracy=0.8,
                completeness=0.6,
                faithfulness=0.7,
                critic_score=0.75,
            )
        }
        current = {
            "q1": _line(
                "q1",
                citation_accuracy=0.9,
                completeness=0.5,
                faithfulness=0.7,
                critic_score=0.80,
            )
        }
        report = diff_summaries(baseline, current, threshold=0.05)
        deltas = report["diffs"][0]["deltas"]
        assert deltas["citation_accuracy"] == pytest.approx(0.1)
        assert deltas["completeness"] == pytest.approx(-0.1)
        assert deltas["faithfulness"] == pytest.approx(0.0)
        assert deltas["critic_score"] == pytest.approx(0.05)

    def test_delta_is_none_when_either_side_missing(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=None, completeness=0.5)}
        current = {"q1": _line("q1", citation_accuracy=0.9, completeness=0.5)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["deltas"]["citation_accuracy"] is None
        assert report["diffs"][0]["deltas"]["completeness"] == pytest.approx(0.0)

    def test_query_ids_sorted_in_output(self) -> None:
        baseline = {
            "z-query": _line("z-query", citation_accuracy=0.5),
            "a-query": _line("a-query", citation_accuracy=0.5),
        }
        current = baseline
        report = diff_summaries(baseline, current)
        assert [d["query_id"] for d in report["diffs"]] == ["a-query", "z-query"]


class TestAggregate:
    def test_aggregate_over_queries_present_in_both(self) -> None:
        baseline = {
            "shared": _line("shared", citation_accuracy=0.8, completeness=0.6, faithfulness=0.7),
            "baseline-only": _line("baseline-only", citation_accuracy=0.99),
        }
        current = {
            "shared": _line("shared", citation_accuracy=0.9, completeness=0.5, faithfulness=0.8),
            "current-only": _line("current-only", citation_accuracy=0.01),
        }
        report = diff_summaries(baseline, current, threshold=0.5)  # avoid regression trip

        # Aggregates should only include the shared query.
        assert report["aggregate_baseline"]["citation_accuracy"] == pytest.approx(0.8)
        assert report["aggregate_current"]["citation_accuracy"] == pytest.approx(0.9)
        assert report["aggregate_deltas"]["citation_accuracy"] == pytest.approx(0.1)

    def test_aggregate_is_none_when_no_shared_scores(self) -> None:
        baseline: dict[str, dict[str, Any]] = {"only-in-baseline": _line("only-in-baseline")}
        current: dict[str, dict[str, Any]] = {"only-in-current": _line("only-in-current")}
        report = diff_summaries(baseline, current)
        for field, value in report["aggregate_baseline"].items():
            assert value is None, field
        for field, value in report["aggregate_current"].items():
            assert value is None, field


class TestFormatReport:
    def _minimal_report(
        self, has_regressions: bool = False
    ) -> RegressionReport:
        return RegressionReport(
            diffs=[
                QueryDiff(
                    query_id="q1",
                    status="regressed" if has_regressions else "unchanged",
                    baseline_error=None,
                    current_error=None,
                    deltas={
                        "citation_accuracy": -0.2 if has_regressions else 0.01,
                        "completeness": 0.0,
                        "faithfulness": 0.0,
                        "critic_score": 0.0,
                    },
                )
            ],
            has_regressions=has_regressions,
            threshold=0.10,
            aggregate_baseline={
                "citation_accuracy": 0.8,
                "completeness": 0.7,
                "faithfulness": 0.6,
                "critic_score": 0.75,
            },
            aggregate_current={
                "citation_accuracy": 0.6 if has_regressions else 0.81,
                "completeness": 0.7,
                "faithfulness": 0.6,
                "critic_score": 0.75,
            },
            aggregate_deltas={
                "citation_accuracy": -0.2 if has_regressions else 0.01,
                "completeness": 0.0,
                "faithfulness": 0.0,
                "critic_score": 0.0,
            },
        )

    def test_no_regressions_flag_reflected(self) -> None:
        md = format_report(self._minimal_report(has_regressions=False))
        assert "Regressions detected**: no" in md

    def test_regressions_flag_reflected(self) -> None:
        md = format_report(self._minimal_report(has_regressions=True))
        assert "Regressions detected**: yes" in md

    def test_threshold_shown(self) -> None:
        md = format_report(self._minimal_report())
        assert "`0.10`" in md

    def test_resource_bands_shown(self) -> None:
        # The report must state the resource rules it applied, so a
        # maintainer reading a red nightly can see why a row fired.
        md = format_report(self._minimal_report())
        assert "Resource bands" in md
        for field in RESOURCE_THRESHOLDS:
            assert f"`{field}`" in md

    def test_per_query_row_present(self) -> None:
        md = format_report(self._minimal_report())
        assert "| q1 |" in md

    def test_new_errors_section_only_when_errored(self) -> None:
        report = self._minimal_report()
        report["diffs"][0]["status"] = "errored"
        report["diffs"][0]["current_error"] = "boom"
        md = format_report(report)
        assert "## New errors" in md
        assert "`q1`: boom" in md

    def test_no_new_errors_section_when_none_errored(self) -> None:
        md = format_report(self._minimal_report())
        assert "## New errors" not in md


class TestCLI:
    def _write(self, path: Path, records: list[dict[str, Any]]) -> None:
        path.write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
        )

    def test_current_missing_exits_2(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline.jsonl"
        current = tmp_path / "does-not-exist.jsonl"
        assert main([str(baseline), str(current)]) == 2

    def test_no_baseline_no_regressions_exits_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        current = tmp_path / "current.jsonl"
        self._write(current, [_line("q1", citation_accuracy=0.9, completeness=0.8, faithfulness=0.7)])
        exit_code = main([str(tmp_path / "missing.jsonl"), str(current)])
        assert exit_code == 0
        assert "Eval regression diff" in capsys.readouterr().out

    def test_regression_exits_1(
        self, tmp_path: Path
    ) -> None:
        baseline = tmp_path / "baseline.jsonl"
        current = tmp_path / "current.jsonl"
        self._write(baseline, [_line("q1", citation_accuracy=0.9)])
        self._write(current, [_line("q1", citation_accuracy=0.5)])
        assert main([str(baseline), str(current), "--threshold", "0.1"]) == 1

    def test_output_file_written(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline.jsonl"
        current = tmp_path / "current.jsonl"
        output = tmp_path / "report.md"
        self._write(baseline, [_line("q1", citation_accuracy=0.9)])
        self._write(current, [_line("q1", citation_accuracy=0.9)])
        main([str(baseline), str(current), "--output", str(output)])
        assert output.is_file()
        assert "Eval regression diff" in output.read_text()


class TestReturnedTypes:
    def test_report_shape(self) -> None:
        report = diff_summaries({}, {})
        assert set(RegressionReport.__required_keys__) == set(report.keys())

    def test_diff_shape(self) -> None:
        report = diff_summaries({"q1": _line("q1")}, {})
        assert set(QueryDiff.__required_keys__) == set(report["diffs"][0].keys())


class TestThresholdBoundary:
    def test_drop_exactly_at_threshold_is_not_regression(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.9)}
        current = {"q1": _line("q1", citation_accuracy=0.8)}  # drop of 0.10
        # Threshold 0.10 means drop MORE THAN 0.10 counts; equal is ok.
        report = diff_summaries(baseline, current, threshold=0.10)
        assert report["diffs"][0]["status"] == "unchanged"

    def test_drop_just_over_threshold_regresses(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.9)}
        current = {"q1": _line("q1", citation_accuracy=0.79)}  # drop of 0.11
        report = diff_summaries(baseline, current, threshold=0.10)
        assert report["diffs"][0]["status"] == "regressed"


class TestDefaultThreshold:
    def test_default_threshold_exposed(self) -> None:
        assert 0.0 < DEFAULT_THRESHOLD < 1.0
