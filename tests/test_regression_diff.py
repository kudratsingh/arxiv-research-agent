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
    LEARNING_LANE,
    LEARNING_RESOURCE_THRESHOLDS,
    METRIC_DIRECTIONS,
    METRIC_FIELDS,
    RESEARCH_LANE,
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


class TestTruncatedBatch:
    """A query that vanished from the current run is a regression.

    ADR 0050. The whole class is a mutation check: before it,
    `has_regressions` only looked at `regressed` / `errored`, so a
    batch that died at query 15 of 20 shipped green — and the
    aggregate row above it re-averaged over the fifteen survivors, so
    nothing in the report said the denominator had moved.
    """

    def _full(self) -> dict[str, dict[str, Any]]:
        return {
            "q1": _line("q1", citation_accuracy=0.8),
            "q2": _line("q2", citation_accuracy=0.8),
            "q3": _line("q3", citation_accuracy=0.8),
        }

    def test_missing_query_classified_as_removed(self) -> None:
        baseline = self._full()
        current = {"q1": baseline["q1"], "q2": baseline["q2"]}
        report = diff_summaries(baseline, current)
        statuses = {d["query_id"]: d["status"] for d in report["diffs"]}
        assert statuses["q3"] == "removed"

    def test_missing_query_fails_the_gate(self) -> None:
        baseline = self._full()
        current = {"q1": baseline["q1"], "q2": baseline["q2"]}
        report = diff_summaries(baseline, current)
        assert report["has_regressions"] is True

    def test_truncated_batch_with_otherwise_perfect_scores_still_fails(
        self,
    ) -> None:
        baseline = self._full()
        current = {"q1": _line("q1", citation_accuracy=1.0)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "improved"
        assert report["has_regressions"] is True

    def test_allow_removed_opts_a_subset_run_out(self) -> None:
        baseline = self._full()
        current = {"q1": baseline["q1"]}
        report = diff_summaries(baseline, current, allow_removed=True)
        assert report["has_regressions"] is False
        assert report["allow_removed"] is True

    def test_allow_removed_does_not_excuse_a_real_regression(self) -> None:
        baseline = self._full()
        current = {"q1": _line("q1", citation_accuracy=0.2)}
        report = diff_summaries(baseline, current, allow_removed=True)
        assert report["has_regressions"] is True

    def test_new_query_is_not_a_regression(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=0.8)}
        current = {
            "q1": baseline["q1"],
            "q2": _line("q2", citation_accuracy=0.8),
        }
        report = diff_summaries(baseline, current)
        assert report["has_regressions"] is False

    def test_report_states_the_shrunken_denominator(self) -> None:
        baseline = self._full()
        current = {"q1": baseline["q1"], "q2": baseline["q2"]}
        md = format_report(diff_summaries(baseline, current))
        assert "2 compared, 1 missing from the current run, 0 new" in md
        assert "over the 2 of 3 baseline queries present in both runs" in md

    def test_report_marks_removals_as_ungated_under_allow_removed(self) -> None:
        baseline = self._full()
        current = {"q1": baseline["q1"], "q2": baseline["q2"]}
        md = format_report(
            diff_summaries(baseline, current, allow_removed=True)
        )
        assert "1 (not gated: --allow-removed)" in md


class TestUnscoredMetrics:
    """A metric the current run stopped scoring must not read as unchanged.

    ADR 0050's judge isolation is the cause: a judge that fails leaves
    its metric `null` on the record instead of aborting the campaign,
    so the delta goes `None` and the query classifies `unchanged`. The
    gate deliberately stays green — a flaky judge is a harness fault,
    not a product regression — but the report has to say so, or a night
    where 18 of 20 faithfulness judges failed is byte-identical to a
    clean one. Every test here is a mutation check on `_unscored_counts`
    and its rendering.
    """

    def _pair(self, unscored: int, total: int = 20) -> tuple[
        dict[str, dict[str, Any]], dict[str, dict[str, Any]]
    ]:
        baseline: dict[str, dict[str, Any]] = {}
        current: dict[str, dict[str, Any]] = {}
        for i in range(total):
            qid = f"q{i:02d}"
            baseline[qid] = _line(qid, citation_accuracy=0.8, faithfulness=0.95)
            current[qid] = _line(
                qid,
                citation_accuracy=0.8,
                faithfulness=None if i < unscored else 0.95,
            )
        return baseline, current

    def test_counts_metrics_the_current_run_stopped_scoring(self) -> None:
        baseline, current = self._pair(unscored=18)
        report = diff_summaries(baseline, current)
        assert report["unscored"]["faithfulness"] == 18
        assert report["unscored"]["citation_accuracy"] == 0

    def test_absent_field_on_both_sides_is_not_lost_signal(self) -> None:
        # `llm_calls` is None in both runs here — a summary that never
        # carried the field, not a judge that failed.
        baseline, current = self._pair(unscored=0)
        report = diff_summaries(baseline, current)
        assert report["unscored"]["llm_calls"] == 0

    def test_a_new_metric_the_baseline_never_had_is_not_lost_signal(self) -> None:
        baseline = {"q1": _line("q1", citation_accuracy=None)}
        current = {"q1": _line("q1", citation_accuracy=0.8)}
        report = diff_summaries(baseline, current)
        assert report["unscored"]["citation_accuracy"] == 0

    def test_unscored_queries_still_read_unchanged_and_stay_green(self) -> None:
        baseline, current = self._pair(unscored=18)
        report = diff_summaries(baseline, current)
        assert report["has_regressions"] is False
        assert {d["status"] for d in report["diffs"]} == {"unchanged"}

    def test_report_names_the_metric_and_its_count(self) -> None:
        baseline, current = self._pair(unscored=18)
        md = format_report(diff_summaries(baseline, current))
        assert "Unscored in the current run" in md
        assert "`faithfulness` on 18 of 20" in md

    def test_aggregate_row_carries_its_own_denominator(self) -> None:
        baseline, current = self._pair(unscored=18)
        md = format_report(diff_summaries(baseline, current))
        # The faithfulness mean is over two queries inside a section
        # headed "over the 20 of 20 baseline queries".
        assert "| faithfulness | 0.950 | 0.950 | +0.000 | 2 / 20 |" in md
        assert "| citation_accuracy | 0.800 | 0.800 | +0.000 | 20 / 20 |" in md

    def test_clean_run_says_nothing_about_unscored_metrics(self) -> None:
        baseline, current = self._pair(unscored=0)
        md = format_report(diff_summaries(baseline, current))
        assert "Unscored in the current run" not in md


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
        self, has_regressions: bool = False, *, allow_removed: bool = False
    ) -> RegressionReport:
        return RegressionReport(
            allow_removed=allow_removed,
            lane=RESEARCH_LANE,
            unscored=dict.fromkeys(
                ("citation_accuracy", "completeness", "faithfulness"), 0
            ),
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

    def test_truncated_current_run_exits_1(self, tmp_path: Path) -> None:
        # The nightly's real failure mode: the batch died partway, so
        # summary.jsonl is short. Exit 1 is what turns that red.
        baseline = tmp_path / "baseline.jsonl"
        current = tmp_path / "current.jsonl"
        self._write(
            baseline,
            [
                _line("q1", citation_accuracy=0.9),
                _line("q2", citation_accuracy=0.9),
            ],
        )
        self._write(current, [_line("q1", citation_accuracy=0.9)])
        assert main([str(baseline), str(current)]) == 1

    def test_allow_removed_flag_exits_0(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline.jsonl"
        current = tmp_path / "current.jsonl"
        self._write(
            baseline,
            [
                _line("q1", citation_accuracy=0.9),
                _line("q2", citation_accuracy=0.9),
            ],
        )
        self._write(current, [_line("q1", citation_accuracy=0.9)])
        assert main([str(baseline), str(current), "--allow-removed"]) == 0

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


# ---------------------------------------------------------------------------
# The learning lane (WO-W11)
#
# `src/eval/simulate_learner.py` writes a different summary shape than
# `runner.py` does: keyed by `record_id`, scored on rubric judges plus
# deterministic outcome booleans, with three cost columns instead of
# one. These tests cover every field the lane gates on, in both
# directions, plus the missing-session rule and the two-lane isolation
# the card requires.
# ---------------------------------------------------------------------------


def _session(
    record_id: str,
    *,
    shame_free: bool | None = True,
    shame_free_score: float | None = None,
    downscope_honest: bool | None = None,
    plan_coherence: float | None = None,
    progress_events_evidence_linked: bool | None = True,
    injection_contained: bool | None = None,
    expectation_failures: int | None = 0,
    llm_calls: int | None = None,
    cost_usd: float | None = None,
    learner_cost_usd: float | None = None,
    judge_cost_usd: float | None = None,
    total_cost_usd: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """One `simulate_learner.summary_line`-shaped row."""
    return {
        "record_id": record_id,
        "shame_free": shame_free,
        "shame_free_score": shame_free_score,
        "downscope_honest": downscope_honest,
        "plan_coherence": plan_coherence,
        "progress_events_evidence_linked": progress_events_evidence_linked,
        "injection_contained": injection_contained,
        "expectation_failures": expectation_failures,
        "llm_calls": llm_calls,
        "cost_usd": cost_usd,
        "learner_cost_usd": learner_cost_usd,
        "judge_cost_usd": judge_cost_usd,
        "total_cost_usd": total_cost_usd,
        "error": error,
    }


def _learning_diff(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    **kwargs: Any,
) -> RegressionReport:
    return diff_summaries(baseline, current, lane=LEARNING_LANE, **kwargs)


class TestLearningLaneLoading:
    def test_indexes_by_record_id(self, tmp_path: Path) -> None:
        path = tmp_path / "summary.jsonl"
        path.write_text(
            "\n".join(
                json.dumps(r)
                for r in (_session("a.r1"), _session("b.r1"))
            )
        )
        loaded = load_summary(path, lane=LEARNING_LANE)
        assert set(loaded) == {"a.r1", "b.r1"}

    def test_a_line_without_a_record_id_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "summary.jsonl"
        path.write_text(json.dumps({"scenario_id": "x"}))
        with pytest.raises(ValueError, match="record_id"):
            load_summary(path, lane=LEARNING_LANE)

    def test_a_research_summary_is_not_silently_readable_as_learning(
        self, tmp_path: Path
    ) -> None:
        # The two lanes must not be confusable: a research summary fed
        # to the learning lane fails loudly rather than producing an
        # empty diff that reads green.
        path = tmp_path / "summary.jsonl"
        path.write_text(json.dumps(_line("q1", citation_accuracy=0.9)))
        with pytest.raises(ValueError, match="record_id"):
            load_summary(path, lane=LEARNING_LANE)


class TestLearningLaneEveryGatedField:
    """Every gated field, both directions. The card's criterion 1."""

    ADVERSE: dict[str, tuple[Any, Any]] = {
        # field: (baseline value, worse value)
        "shame_free": (True, False),
        "shame_free_score": (0.90, 0.70),
        "downscope_honest": (True, False),
        "plan_coherence": (0.85, 0.60),
        "progress_events_evidence_linked": (True, False),
        "injection_contained": (True, False),
        "expectation_failures": (0, 1),
        "llm_calls": (8, 20),
        "cost_usd": (0.12, 0.40),
    }

    def test_every_gated_field_is_covered_by_this_class(self) -> None:
        # Guards the guard: a field added to the lane without a case
        # here would otherwise be silently untested.
        assert set(self.ADVERSE) == set(LEARNING_LANE.metric_fields)

    @pytest.mark.parametrize("field", sorted(ADVERSE))
    def test_adverse_move_regresses(self, field: str) -> None:
        good, bad = self.ADVERSE[field]
        baseline = {"s.r1": _session("s.r1", **{field: good})}
        current = {"s.r1": _session("s.r1", **{field: bad})}
        report = _learning_diff(baseline, current)
        assert report["diffs"][0]["status"] == "regressed", field
        assert report["has_regressions"] is True

    @pytest.mark.parametrize("field", sorted(ADVERSE))
    def test_favorable_move_improves(self, field: str) -> None:
        good, bad = self.ADVERSE[field]
        baseline = {"s.r1": _session("s.r1", **{field: bad})}
        current = {"s.r1": _session("s.r1", **{field: good})}
        report = _learning_diff(baseline, current)
        assert report["diffs"][0]["status"] == "improved", field
        assert report["has_regressions"] is False

    def test_deterministic_outcome_booleans_aggregate_as_rates(self) -> None:
        # `_score` reads a bool as 1.0/0.0, so the aggregate of a
        # per-session boolean is the campaign's rate for that outcome.
        baseline = {
            f"s{i}.r1": _session(f"s{i}.r1", injection_contained=True)
            for i in range(4)
        }
        current = dict(baseline)
        current["s0.r1"] = _session("s0.r1", injection_contained=False)
        report = _learning_diff(baseline, current)
        assert report["aggregate_baseline"]["injection_contained"] == 1.0
        assert report["aggregate_current"]["injection_contained"] == 0.75


class TestLearningLaneResourceBands:
    def test_one_extra_unmet_expectation_regresses(self) -> None:
        # Zero tolerance by design: a structural expectation that
        # stopped being met is a regression at +1.
        baseline = {"s.r1": _session("s.r1", expectation_failures=0)}
        current = {"s.r1": _session("s.r1", expectation_failures=1)}
        assert _learning_diff(baseline, current)["diffs"][0]["status"] == "regressed"

    def test_a_penny_of_cost_drift_is_not_a_regression(self) -> None:
        baseline = {"s.r1": _session("s.r1", cost_usd=0.12)}
        current = {"s.r1": _session("s.r1", cost_usd=0.15)}
        assert _learning_diff(baseline, current)["diffs"][0]["status"] == "unchanged"

    def test_a_cost_move_clearing_only_the_relative_leg_is_unchanged(self) -> None:
        # +33% but only +$0.04 — under the $0.05 floor.
        baseline = {"s.r1": _session("s.r1", cost_usd=0.12)}
        current = {"s.r1": _session("s.r1", cost_usd=0.16)}
        assert _learning_diff(baseline, current)["diffs"][0]["status"] == "unchanged"

    def test_a_cost_move_clearing_only_the_absolute_leg_is_unchanged(self) -> None:
        # +$0.20 on a $2.00 baseline is 10% — under the relative leg.
        baseline = {"s.r1": _session("s.r1", cost_usd=2.00)}
        current = {"s.r1": _session("s.r1", cost_usd=2.20)}
        assert _learning_diff(baseline, current)["diffs"][0]["status"] == "unchanged"

    def test_one_extra_tutor_call_is_not_a_regression(self) -> None:
        baseline = {"s.r1": _session("s.r1", llm_calls=8)}
        current = {"s.r1": _session("s.r1", llm_calls=10)}
        assert _learning_diff(baseline, current)["diffs"][0]["status"] == "unchanged"

    def test_every_lower_better_field_has_an_explicit_band(self) -> None:
        # The ADR 0044 invariant, per lane: a `lower_better` metric with
        # no band would silently fall back to the score epsilon.
        lower_better = {
            field
            for field, direction in LEARNING_LANE.directions.items()
            if direction == "lower_better"
        }
        assert lower_better == set(LEARNING_RESOURCE_THRESHOLDS)

    def test_the_lane_declares_a_direction_for_every_gated_field(self) -> None:
        assert set(LEARNING_LANE.metric_fields) <= set(LEARNING_LANE.directions)


class TestLearningLaneHarnessCostIsNotGated:
    """ADR 0050's product-vs-harness line, enforced by the lane."""

    def test_judge_cost_doubling_does_not_fail_the_run(self) -> None:
        baseline = {"s.r1": _session("s.r1", judge_cost_usd=0.05)}
        current = {"s.r1": _session("s.r1", judge_cost_usd=5.00)}
        report = _learning_diff(baseline, current)
        assert report["has_regressions"] is False
        assert report["diffs"][0]["status"] == "unchanged"

    def test_harness_cost_is_still_tabulated(self) -> None:
        baseline = {"s.r1": _session("s.r1", judge_cost_usd=0.05)}
        current = {"s.r1": _session("s.r1", judge_cost_usd=0.09)}
        report = _learning_diff(baseline, current)
        assert report["aggregate_current"]["judge_cost_usd"] == 0.09
        md = format_report(report)
        assert "judge_cost_usd *(not gated)*" in md

    def test_informational_fields_are_disjoint_from_gated_ones(self) -> None:
        assert not set(LEARNING_LANE.informational_fields) & set(
            LEARNING_LANE.metric_fields
        )


class TestLearningLaneMissingSession:
    """A baseline session absent from the current run is a regression."""

    def test_missing_session_is_removed_and_fails_the_gate(self) -> None:
        baseline = {
            "a.r1": _session("a.r1"),
            "b.r1": _session("b.r1"),
        }
        current = {"a.r1": _session("a.r1")}
        report = _learning_diff(baseline, current)
        statuses = {d["query_id"]: d["status"] for d in report["diffs"]}
        assert statuses["b.r1"] == "removed"
        assert report["has_regressions"] is True

    def test_a_truncated_campaign_with_perfect_scores_still_fails(self) -> None:
        baseline = {f"s{i}.r1": _session(f"s{i}.r1") for i in range(15)}
        current = {f"s{i}.r1": _session(f"s{i}.r1") for i in range(9)}
        report = _learning_diff(baseline, current)
        assert report["has_regressions"] is True
        md = format_report(report)
        assert "9 of 15 baseline sessions present in both runs" in md

    def test_allow_removed_opts_a_subset_run_out(self) -> None:
        baseline = {"a.r1": _session("a.r1"), "b.r1": _session("b.r1")}
        current = {"a.r1": _session("a.r1")}
        report = _learning_diff(baseline, current, allow_removed=True)
        assert report["has_regressions"] is False

    def test_allow_removed_does_not_excuse_a_real_regression(self) -> None:
        baseline = {"a.r1": _session("a.r1", shame_free=True), "b.r1": _session("b.r1")}
        current = {"a.r1": _session("a.r1", shame_free=False)}
        report = _learning_diff(baseline, current, allow_removed=True)
        assert report["has_regressions"] is True

    def test_a_new_session_is_not_a_regression(self) -> None:
        baseline = {"a.r1": _session("a.r1")}
        current = {"a.r1": _session("a.r1"), "b.r1": _session("b.r1")}
        report = _learning_diff(baseline, current)
        statuses = {d["query_id"]: d["status"] for d in report["diffs"]}
        assert statuses["b.r1"] == "new"
        assert report["has_regressions"] is False


class TestLearningLaneReport:
    def test_report_uses_session_vocabulary(self) -> None:
        md = format_report(_learning_diff({}, {"s.r1": _session("s.r1")}))
        assert md.startswith("# Learning-eval regression diff")
        assert "## Per-session" in md
        assert "**Sessions**:" in md

    def test_report_carries_the_plan_cost_reference_row(self) -> None:
        report = _learning_diff(
            {"s.r1": _session("s.r1", cost_usd=0.11)},
            {"s.r1": _session("s.r1", cost_usd=0.12)},
        )
        md = format_report(report)
        assert "## Cost per session vs the plan's estimate" in md
        assert "0.07 – 0.17" in md
        # The row must say what it is, in the row.
        assert "Plan estimate — **not a measurement**" in md
        assert "01-LEARNING-AGENT.md §6.1" in md

    def test_research_report_has_no_cost_reference_section(self) -> None:
        md = format_report(diff_summaries({}, {"q1": _line("q1", cost_usd=0.5)}))
        assert "Plan estimate" not in md
        assert "## Per-query" in md

    def test_every_lane_column_names_a_tabulated_field(self) -> None:
        for lane in (RESEARCH_LANE, LEARNING_LANE):
            for _, field in lane.columns:
                assert field in lane.tabulated_fields, (lane.name, field)


class TestLaneIsolation:
    """The research lane's semantics are untouched by the new one."""

    def test_the_research_lane_is_the_default_everywhere(self) -> None:
        report = diff_summaries({}, {})
        assert report["lane"] is RESEARCH_LANE
        assert load_summary(Path("/nonexistent.jsonl")) == {}

    def test_the_research_lane_still_uses_the_module_constants(self) -> None:
        assert RESEARCH_LANE.metric_fields is METRIC_FIELDS
        assert RESEARCH_LANE.resource_thresholds is RESOURCE_THRESHOLDS
        assert RESEARCH_LANE.directions is METRIC_DIRECTIONS
        assert RESEARCH_LANE.informational_fields == ()
        assert RESEARCH_LANE.cost_reference is None

    def test_a_learning_field_never_enters_the_research_field_set(self) -> None:
        # The two summaries share `cost_usd` and `llm_calls` by design;
        # nothing else may cross.
        shared = set(METRIC_FIELDS) & set(LEARNING_LANE.tabulated_fields)
        assert shared == {"cost_usd", "llm_calls"}

    def test_cli_defaults_to_the_research_lane(self, tmp_path: Path) -> None:
        baseline = tmp_path / "b.jsonl"
        current = tmp_path / "c.jsonl"
        baseline.write_text(json.dumps(_line("q1", citation_accuracy=0.9)))
        current.write_text(json.dumps(_line("q1", citation_accuracy=0.9)))
        output = tmp_path / "diff.md"
        assert main([str(baseline), str(current), "--output", str(output)]) == 0
        assert output.read_text().startswith("# Eval regression diff")

    def test_cli_lane_learning_reads_record_ids(self, tmp_path: Path) -> None:
        baseline = tmp_path / "b.jsonl"
        current = tmp_path / "c.jsonl"
        baseline.write_text(json.dumps(_session("s.r1", shame_free=True)))
        current.write_text(json.dumps(_session("s.r1", shame_free=False)))
        output = tmp_path / "diff.md"
        code = main(
            [
                str(baseline),
                str(current),
                "--lane",
                "learning",
                "--output",
                str(output),
            ]
        )
        assert code == 1
        assert "# Learning-eval regression diff" in output.read_text()
