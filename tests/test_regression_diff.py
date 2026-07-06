"""Unit tests for the regression diff.

Pure logic — no network, no file IO except via `tmp_path`. Covers
JSONL loading (including missing-file graceful fallback), per-query
status classification, aggregate rollups, and the markdown renderer.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from src.eval.regression_diff import (
    DEFAULT_THRESHOLD,
    QueryDiff,
    RegressionReport,
    diff_summaries,
    format_report,
    load_summary,
    main,
)


def _line(
    query_id: str,
    *,
    citation_accuracy: float | None = None,
    completeness: float | None = None,
    faithfulness: float | None = None,
    critic_score: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "citation_accuracy": citation_accuracy,
        "completeness": completeness,
        "faithfulness": faithfulness,
        "critic_score": critic_score,
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
