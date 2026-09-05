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
    EXIT_INCOMPARABLE,
    EXIT_INVALID,
    EXIT_OK,
    EXIT_REGRESSION,
    LEARNING_LANE,
    LEARNING_RESOURCE_THRESHOLDS,
    METRIC_DIRECTIONS,
    METRIC_FIELDS,
    QUANTUM_TOLERANCE,
    RESEARCH_LANE,
    RESOURCE_THRESHOLDS,
    SCORE_QUANTA,
    Comparability,
    Decision,
    QueryDiff,
    RegressionReport,
    aggregate_repeats,
    check_comparability,
    diff_summaries,
    format_report,
    load_rows,
    load_summary,
    main,
    score_epsilon,
)

pytestmark = pytest.mark.unit


def _line(
    query_id: str,
    *,
    citation_resolution_rate: float | None = None,
    citation_accuracy: float | None = None,
    completeness: float | None = None,
    faithfulness: float | None = None,
    critic_score: float | None = None,
    iterations: float | None = None,
    llm_calls: float | None = None,
    cost_usd: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """One research summary row.

    `citation_resolution_rate` is the gated citation metric since ADR
    0074; `citation_accuracy` rides beside it as a diagnostic, which is
    why it is a separate argument rather than the same one renamed.
    """
    return {
        "query_id": query_id,
        "citation_resolution_rate": citation_resolution_rate,
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
            json.dumps({"query_id": "q1", "citation_resolution_rate": 0.9}) + "\n"
            + json.dumps({"query_id": "q2", "citation_resolution_rate": 0.7}) + "\n"
        )
        result = load_summary(path)
        assert set(result) == {"q1", "q2"}
        assert result["q1"]["citation_resolution_rate"] == 0.9

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
        path.write_text(json.dumps({"citation_resolution_rate": 0.9}) + "\n")
        with pytest.raises(ValueError, match="query_id"):
            load_summary(path)


class TestDiffSummariesClassification:
    def test_unchanged_when_scores_within_threshold(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=0.80, completeness=0.75, faithfulness=0.70)}
        current = {"q1": _line("q1", citation_resolution_rate=0.82, completeness=0.73, faithfulness=0.72)}
        report = diff_summaries(baseline, current, threshold=0.1)
        assert report["diffs"][0]["status"] == "unchanged"
        assert report["has_regressions"] is False

    def test_regression_when_metric_drops_beyond_threshold(self) -> None:
        # `faithfulness` has no declared quantum, so it is judged on the
        # flat epsilon. `completeness` is the quantised case and has its
        # own tests below.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.9, completeness=0.8, faithfulness=0.8)}
        current = {"q1": _line("q1", citation_resolution_rate=0.9, completeness=0.8, faithfulness=0.5)}
        report = diff_summaries(baseline, current, threshold=0.1)
        assert report["diffs"][0]["status"] == "regressed"
        assert report["has_regressions"] is True

    def test_improvement_when_metric_rises_beyond_threshold(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=0.5, completeness=0.5, faithfulness=0.5)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, completeness=0.5, faithfulness=0.5)}
        report = diff_summaries(baseline, current, threshold=0.1)
        assert report["diffs"][0]["status"] == "improved"
        assert report["has_regressions"] is False

    # Direction-aware: cost / iterations / llm_calls are `lower_better`
    # and judged by their RESOURCE_THRESHOLDS bands (absolute floor AND
    # relative fraction), never by `--threshold` (ADR 0044).
    def test_cost_rising_beyond_band_is_regression(self) -> None:
        # +$0.40 on $0.10: clears the $0.10 floor and the 25% band.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=0.10)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=0.50)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"
        assert report["has_regressions"] is True

    def test_cost_dropping_beyond_band_is_improvement(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=0.50)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=0.10)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "improved"
        assert report["has_regressions"] is False

    def test_iteration_runaway_is_regression(self) -> None:
        # loop-induced iteration runaway must show up as a regression.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, iterations=1)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, iterations=5)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_llm_call_runaway_is_regression(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=30)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=90)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_cost_below_absolute_floor_is_unchanged(self) -> None:
        # +$0.05 is under the $0.10 floor even though it's +50% relative.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=0.10)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=0.15)}
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
            "q1": _line("q1", citation_resolution_rate=0.8),
            "q2": _line("q2", citation_resolution_rate=0.8),
            "q3": _line("q3", citation_resolution_rate=0.8),
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
        current = {"q1": _line("q1", citation_resolution_rate=1.0)}
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
        current = {"q1": _line("q1", citation_resolution_rate=0.2)}
        report = diff_summaries(baseline, current, allow_removed=True)
        assert report["has_regressions"] is True

    def test_new_query_is_not_a_regression(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8)}
        current = {
            "q1": baseline["q1"],
            "q2": _line("q2", citation_resolution_rate=0.8),
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
            baseline[qid] = _line(qid, citation_resolution_rate=0.8, faithfulness=0.95)
            current[qid] = _line(
                qid,
                citation_resolution_rate=0.8,
                faithfulness=None if i < unscored else 0.95,
            )
        return baseline, current

    def test_counts_metrics_the_current_run_stopped_scoring(self) -> None:
        baseline, current = self._pair(unscored=18)
        report = diff_summaries(baseline, current)
        assert report["unscored"]["faithfulness"] == 18
        assert report["unscored"]["citation_resolution_rate"] == 0

    def test_absent_field_on_both_sides_is_not_lost_signal(self) -> None:
        # `llm_calls` is None in both runs here — a summary that never
        # carried the field, not a judge that failed.
        baseline, current = self._pair(unscored=0)
        report = diff_summaries(baseline, current)
        assert report["unscored"]["llm_calls"] == 0

    def test_a_new_metric_the_baseline_never_had_is_not_lost_signal(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=None)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8)}
        report = diff_summaries(baseline, current)
        assert report["unscored"]["citation_resolution_rate"] == 0

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
        assert "| citation_resolution_rate | 0.800 | 0.800 | +0.000 | 20 / 20 |" in md

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
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=42)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=43)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"
        assert report["has_regressions"] is False

    def test_one_extra_critic_revision_is_not_regression(self) -> None:
        # iterations 1 -> 2 is ordinary critic nondeterminism.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, iterations=1)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, iterations=2)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"

    def test_two_extra_iterations_regress(self) -> None:
        # +2 clears the floor of 1 and is +200% relative.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, iterations=1)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, iterations=3)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_llm_calls_over_floor_but_proportionally_small_is_unchanged(
        self,
    ) -> None:
        # +6 calls clears the floor of 4 but is only +6% on a baseline
        # of 100 — the relative leg absorbs drift on large baselines.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=100)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=106)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"

    def test_llm_calls_clearing_both_legs_regress(self) -> None:
        # +5 on 12: over the floor of 4 and +42% relative.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=12)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=17)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_llm_calls_dropping_beyond_band_is_improvement(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=17)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=12)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "improved"

    def test_cost_over_floor_but_proportionally_small_is_unchanged(self) -> None:
        # +$0.15 on a $1.00 baseline clears the floor but is only +15%.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=1.00)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=1.15)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"

    def test_cost_clearing_both_legs_regresses(self) -> None:
        # +$0.14 on $0.31: over the $0.10 floor and +45% relative.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=0.31)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=0.45)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_zero_baseline_falls_back_to_absolute_floor(self) -> None:
        # No meaningful denominator — the floor alone decides.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=0.0)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, cost_usd=0.50)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_score_threshold_does_not_gate_resource_metrics(self) -> None:
        # A permissive --threshold must not mute a genuine call runaway.
        baseline = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=12)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8, llm_calls=30)}
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
        current = {"q1": _line("q1", citation_resolution_rate=0.9)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "new"
        assert report["has_regressions"] is False

    def test_removed_query_in_baseline(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=0.9)}
        current: dict[str, dict[str, Any]] = {}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "removed"

    def test_errored_status_when_current_has_new_error(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=0.9)}
        current = {"q1": _line("q1", error="RuntimeError: bad")}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "errored"
        assert report["has_regressions"] is True

    def test_recovered_status_when_baseline_had_error(self) -> None:
        baseline = {"q1": _line("q1", error="prior error")}
        current = {"q1": _line("q1", citation_resolution_rate=0.9)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "recovered"
        assert report["has_regressions"] is False


class TestDiffSummariesDeltas:
    def test_per_metric_deltas_computed(self) -> None:
        baseline = {
            "q1": _line(
                "q1",
                citation_resolution_rate=0.8,
                completeness=0.6,
                faithfulness=0.7,
                critic_score=0.75,
            )
        }
        current = {
            "q1": _line(
                "q1",
                citation_resolution_rate=0.9,
                completeness=0.5,
                faithfulness=0.7,
                critic_score=0.80,
            )
        }
        report = diff_summaries(baseline, current, threshold=0.05)
        deltas = report["diffs"][0]["deltas"]
        assert deltas["citation_resolution_rate"] == pytest.approx(0.1)
        assert deltas["completeness"] == pytest.approx(-0.1)
        assert deltas["faithfulness"] == pytest.approx(0.0)
        assert deltas["critic_score"] == pytest.approx(0.05)

    def test_delta_is_none_when_either_side_missing(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=None, completeness=0.5)}
        current = {"q1": _line("q1", citation_resolution_rate=0.9, completeness=0.5)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["deltas"]["citation_resolution_rate"] is None
        assert report["diffs"][0]["deltas"]["completeness"] == pytest.approx(0.0)

    def test_query_ids_sorted_in_output(self) -> None:
        baseline = {
            "z-query": _line("z-query", citation_resolution_rate=0.5),
            "a-query": _line("a-query", citation_resolution_rate=0.5),
        }
        current = baseline
        report = diff_summaries(baseline, current)
        assert [d["query_id"] for d in report["diffs"]] == ["a-query", "z-query"]


class TestAggregate:
    def test_aggregate_over_queries_present_in_both(self) -> None:
        baseline = {
            "shared": _line("shared", citation_resolution_rate=0.8, completeness=0.6, faithfulness=0.7),
            "baseline-only": _line("baseline-only", citation_resolution_rate=0.99),
        }
        current = {
            "shared": _line("shared", citation_resolution_rate=0.9, completeness=0.5, faithfulness=0.8),
            "current-only": _line("current-only", citation_resolution_rate=0.01),
        }
        report = diff_summaries(baseline, current, threshold=0.5)  # avoid regression trip

        # Aggregates should only include the shared query.
        assert report["aggregate_baseline"]["citation_resolution_rate"] == pytest.approx(0.8)
        assert report["aggregate_current"]["citation_resolution_rate"] == pytest.approx(0.9)
        assert report["aggregate_deltas"]["citation_resolution_rate"] == pytest.approx(0.1)

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
                ("citation_resolution_rate", "completeness", "faithfulness"), 0
            ),
            diffs=[
                QueryDiff(
                    query_id="q1",
                    status="regressed" if has_regressions else "unchanged",
                    baseline_error=None,
                    current_error=None,
                    deltas={
                        "citation_resolution_rate": -0.2 if has_regressions else 0.01,
                        "completeness": 0.0,
                        "faithfulness": 0.0,
                        "critic_score": 0.0,
                    },
                )
            ],
            has_regressions=has_regressions,
            threshold=0.10,
            aggregate_baseline={
                "citation_resolution_rate": 0.8,
                "completeness": 0.7,
                "faithfulness": 0.6,
                "critic_score": 0.75,
            },
            aggregate_current={
                "citation_resolution_rate": 0.6 if has_regressions else 0.81,
                "completeness": 0.7,
                "faithfulness": 0.6,
                "critic_score": 0.75,
            },
            aggregate_deltas={
                "citation_resolution_rate": -0.2 if has_regressions else 0.01,
                "completeness": 0.0,
                "faithfulness": 0.0,
                "critic_score": 0.0,
            },
            # ADR 0071's additions. Hand-built here rather than derived,
            # because these tests are about the renderer: a report the
            # differ never produced still has to render.
            comparability=Comparability(comparable=True, conflicts=(), notes=()),
            statistics={},
            reliability=[],
            decision=Decision(
                verdict="ROLLBACK" if has_regressions else "HOLD",
                reasons=("fixture",),
            ),
            paired_tasks=1,
            repeats=1,
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
        self._write(current, [_line("q1", citation_resolution_rate=0.9, completeness=0.8, faithfulness=0.7)])
        exit_code = main([str(tmp_path / "missing.jsonl"), str(current)])
        assert exit_code == 0
        assert "Eval regression diff" in capsys.readouterr().out

    def test_regression_exits_1(
        self, tmp_path: Path
    ) -> None:
        baseline = tmp_path / "baseline.jsonl"
        current = tmp_path / "current.jsonl"
        self._write(baseline, [_line("q1", citation_resolution_rate=0.9)])
        self._write(current, [_line("q1", citation_resolution_rate=0.5)])
        assert main([str(baseline), str(current), "--threshold", "0.1"]) == 1

    def test_truncated_current_run_exits_1(self, tmp_path: Path) -> None:
        # The nightly's real failure mode: the batch died partway, so
        # summary.jsonl is short. Exit 1 is what turns that red.
        baseline = tmp_path / "baseline.jsonl"
        current = tmp_path / "current.jsonl"
        self._write(
            baseline,
            [
                _line("q1", citation_resolution_rate=0.9),
                _line("q2", citation_resolution_rate=0.9),
            ],
        )
        self._write(current, [_line("q1", citation_resolution_rate=0.9)])
        assert main([str(baseline), str(current)]) == 1

    def test_allow_removed_flag_exits_0(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline.jsonl"
        current = tmp_path / "current.jsonl"
        self._write(
            baseline,
            [
                _line("q1", citation_resolution_rate=0.9),
                _line("q2", citation_resolution_rate=0.9),
            ],
        )
        self._write(current, [_line("q1", citation_resolution_rate=0.9)])
        assert main([str(baseline), str(current), "--allow-removed"]) == 0

    def test_output_file_written(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline.jsonl"
        current = tmp_path / "current.jsonl"
        output = tmp_path / "report.md"
        self._write(baseline, [_line("q1", citation_resolution_rate=0.9)])
        self._write(current, [_line("q1", citation_resolution_rate=0.9)])
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
        baseline = {"q1": _line("q1", citation_resolution_rate=0.9)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8)}  # drop of 0.10
        # Threshold 0.10 means drop MORE THAN 0.10 counts; equal is ok.
        report = diff_summaries(baseline, current, threshold=0.10)
        assert report["diffs"][0]["status"] == "unchanged"

    def test_drop_just_over_threshold_regresses(self) -> None:
        baseline = {"q1": _line("q1", citation_resolution_rate=0.9)}
        current = {"q1": _line("q1", citation_resolution_rate=0.79)}  # drop of 0.11
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
    pedagogy_clean: bool | None = True,
    pedagogy_violations: int | None = 0,
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
        "pedagogy_clean": pedagogy_clean,
        "pedagogy_violations": pedagogy_violations,
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
        path.write_text(json.dumps(_line("q1", citation_resolution_rate=0.9)))
        with pytest.raises(ValueError, match="record_id"):
            load_summary(path, lane=LEARNING_LANE)


class TestLearningLaneEveryGatedField:
    """Every gated field, both directions. The card's criterion 1."""

    ADVERSE: dict[str, tuple[Any, Any]] = {
        # field: (baseline value, worse value)
        "shame_free": (True, False),
        "shame_free_score": (0.90, 0.70),
        # ADR 0072's pedagogy scan. Zero tolerance on the count, for the
        # same reason `expectation_failures` has it: a banned pedagogy
        # scalar in learner-facing copy is not run-to-run variance.
        "pedagogy_clean": (True, False),
        "pedagogy_violations": (0, 1),
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

    def test_a_row_predating_the_pedagogy_scan_does_not_gate(self) -> None:
        # `simulate_learner` writes `None` rather than `0` when a record
        # predates ADR 0072 — "never scanned" and "scanned and clean" are
        # different claims. A missing field must therefore read as an
        # absent comparison, not as a clean one and not as a regression.
        before = _session("s.r1")
        del before["pedagogy_clean"]
        del before["pedagogy_violations"]
        after = _session("s.r1", pedagogy_clean=True, pedagogy_violations=0)
        report = _learning_diff({"s.r1": before}, {"s.r1": after})
        assert report["diffs"][0]["deltas"]["pedagogy_clean"] is None
        assert report["diffs"][0]["status"] == "unchanged"
        assert report["has_regressions"] is False

    def test_an_explicit_null_pedagogy_scan_does_not_gate_either(self) -> None:
        baseline = {"s.r1": _session("s.r1", pedagogy_clean=None, pedagogy_violations=None)}
        current = {"s.r1": _session("s.r1", pedagogy_clean=True, pedagogy_violations=0)}
        report = _learning_diff(baseline, current)
        assert report["diffs"][0]["deltas"]["pedagogy_violations"] is None
        assert report["has_regressions"] is False

    def test_one_extra_pedagogy_hit_fires_at_zero_tolerance(self) -> None:
        baseline = {"s.r1": _session("s.r1", pedagogy_clean=False, pedagogy_violations=1)}
        current = {"s.r1": _session("s.r1", pedagogy_clean=False, pedagogy_violations=2)}
        report = _learning_diff(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

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
        # ADR 0071 demoted `critic_score` to a diagnostic and ADR 0074
        # demoted `citation_accuracy`; the lane's informational set is
        # where a demoted metric lands. Neither was deleted — ADR 0070
        # forbids removing a row field, and both are still printed.
        assert RESEARCH_LANE.informational_fields == (
            "citation_accuracy",
            "critic_score",
        )
        assert RESEARCH_LANE.cost_reference is None

    def test_a_learning_field_never_enters_the_research_field_set(self) -> None:
        # The two summaries share `cost_usd` and `llm_calls` by design;
        # nothing else may cross.
        shared = set(METRIC_FIELDS) & set(LEARNING_LANE.tabulated_fields)
        assert shared == {"cost_usd", "llm_calls"}

    def test_cli_defaults_to_the_research_lane(self, tmp_path: Path) -> None:
        baseline = tmp_path / "b.jsonl"
        current = tmp_path / "c.jsonl"
        baseline.write_text(json.dumps(_line("q1", citation_resolution_rate=0.9)))
        current.write_text(json.dumps(_line("q1", citation_resolution_rate=0.9)))
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


# ---------------------------------------------------------------------------
# ADR 0071 — repeats, quanta, comparability, statistics and the decision
# ---------------------------------------------------------------------------


def _rows(*lines: dict[str, Any]) -> list[dict[str, Any]]:
    """A campaign's raw summary rows, as `load_rows` would return them."""
    return list(lines)


def _repeat(query_id: str, repeat: int, **scores: Any) -> dict[str, Any]:
    """One research row for `query_id`'s `repeat`-th run."""
    row = _line(query_id, **scores)
    row["record_id"] = query_id if repeat == 1 else f"{query_id}.r{repeat}"
    row["repeat"] = repeat
    return row


def _provenanced(row: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """A row carrying a complete-enough provenance block."""
    block = {
        "harness_version": "1.0.0",
        "judge_model": "judge-a",
        "product_model": "product-a",
        "rubric_versions": {"completeness": "1.0"},
        "code_commit": "c0ffee",
        "code_dirty": False,
        "dataset_version": "research-benchmark@20:abc",
        "tier": "research",
        "seed": 0,
        "mock_mode": False,
        "captured_at": "2026-09-04T00:00:00+00:00",
    }
    block.update(overrides)
    return {**row, "provenance": block}


class TestRepeatAggregation:
    def test_repeats_of_one_query_become_one_task(self) -> None:
        rows = _rows(
            _repeat("q1", 1, faithfulness=0.6),
            _repeat("q1", 2, faithfulness=0.8),
            _repeat("q1", 3, faithfulness=0.7),
        )
        aggregated = aggregate_repeats(rows, lane=RESEARCH_LANE)
        assert set(aggregated) == {"q1"}
        assert aggregated["q1"]["faithfulness"] == pytest.approx(0.7)
        assert aggregated["q1"]["_repeats"] == 3

    def test_a_single_repeat_campaign_is_unchanged_by_aggregation(self) -> None:
        # Every campaign written before ADR 0071 must read exactly as it
        # did: the mean of one value is that value.
        row = _line("q1", faithfulness=0.61, cost_usd=0.5)
        aggregated = aggregate_repeats(_rows(row), lane=RESEARCH_LANE)
        assert aggregated["q1"]["faithfulness"] == pytest.approx(0.61)
        assert aggregated["q1"]["cost_usd"] == pytest.approx(0.5)
        assert aggregated["q1"]["_repeats"] == 1

    def test_nulls_shrink_the_mean_s_denominator_not_the_task(self) -> None:
        rows = _rows(
            _repeat("q1", 1, faithfulness=0.6),
            _repeat("q1", 2, faithfulness=None),
        )
        aggregated = aggregate_repeats(rows, lane=RESEARCH_LANE)
        assert aggregated["q1"]["faithfulness"] == pytest.approx(0.6)
        assert aggregated["q1"]["_repeat_values"]["faithfulness"] == (0.6,)

    def test_a_task_survives_one_errored_repeat(self) -> None:
        rows = _rows(
            _repeat("q1", 1, faithfulness=0.6),
            _repeat("q1", 2, error="boom"),
        )
        aggregated = aggregate_repeats(rows, lane=RESEARCH_LANE)
        # Two good runs and one failure is a measurement of the good
        # ones, and the failure count says so rather than the mean
        # absorbing it.
        assert aggregated["q1"]["error"] is None
        assert aggregated["q1"]["_errored_repeats"] == 1

    def test_a_task_whose_every_repeat_errored_is_an_errored_task(self) -> None:
        rows = _rows(
            _repeat("q1", 1, error="boom"),
            _repeat("q1", 2, error="boom again"),
        )
        aggregated = aggregate_repeats(rows, lane=RESEARCH_LANE)
        assert aggregated["q1"]["error"] == "boom"
        assert aggregated["q1"]["_errored_repeats"] == 2

    def test_the_learning_lane_groups_on_scenario_id(self) -> None:
        rows = _rows(
            {**_session("s1.r1", shame_free=True), "scenario_id": "s1"},
            {**_session("s1.r2", shame_free=False), "scenario_id": "s1"},
            {**_session("s2.r1", shame_free=True), "scenario_id": "s2"},
        )
        aggregated = aggregate_repeats(rows, lane=LEARNING_LANE)
        assert set(aggregated) == {"s1", "s2"}
        assert aggregated["s1"]["shame_free"] == pytest.approx(0.5)

    def test_a_row_with_no_task_column_falls_back_to_its_record_id(self) -> None:
        # Safe direction: such a campaign aggregates nothing rather than
        # collapsing unrelated records together.
        rows = _rows(_session("s1.r1"), _session("s1.r2"))
        aggregated = aggregate_repeats(rows, lane=LEARNING_LANE)
        assert set(aggregated) == {"s1.r1", "s1.r2"}

    def test_load_summary_aggregates_a_repeated_campaign_from_disk(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "summary.jsonl"
        path.write_text(
            "\n".join(
                json.dumps(row)
                for row in (
                    _repeat("q1", 1, faithfulness=0.4),
                    _repeat("q1", 2, faithfulness=0.6),
                )
            )
        )
        assert len(load_rows(path)) == 2
        aggregated = load_summary(path)
        assert set(aggregated) == {"q1"}
        assert aggregated["q1"]["faithfulness"] == pytest.approx(0.5)

    def test_three_identical_repeats_give_a_zero_width_interval(self) -> None:
        # ADR 0071's acceptance criterion. Three repeats of identical
        # rows must produce no regression and an interval of zero width:
        # nothing moved, and no resample can move it.
        rows = _rows(
            *(_repeat(
                qid,
                r,
                faithfulness=0.8,
                completeness=0.75,
                citation_resolution_rate=1.0,
            )
              for qid in ("q1", "q2", "q3")
              for r in (1, 2, 3))
        )
        aggregated = aggregate_repeats(rows, lane=RESEARCH_LANE)
        report = diff_summaries(dict(aggregated), dict(aggregated))
        assert report["has_regressions"] is False
        assert report["repeats"] == 3
        interval = report["statistics"]["citation_resolution_rate"].bootstrap.interval
        assert interval.width == pytest.approx(0.0)
        assert report["decision"].verdict == "HOLD"


class TestQuantisedEpsilon:
    def test_the_declared_quanta_match_the_benchmark_denominator(self) -> None:
        # `completeness` and `retrieval_recall` are both
        # `matched / len(expected_topics)`, and the coarsest topic list
        # in the benchmark decides the band a query can take in one step.
        from src.eval.benchmark_queries import BENCHMARK_QUERIES

        coarsest = max(1.0 / len(q["expected_topics"]) for q in BENCHMARK_QUERIES)
        assert set(SCORE_QUANTA) == {"completeness", "retrieval_recall"}
        for quantum in SCORE_QUANTA.values():
            assert quantum == pytest.approx(coarsest)

    def test_a_quantised_metric_gets_a_wider_band_than_the_flat_epsilon(self) -> None:
        assert score_epsilon("completeness", 0.10) == pytest.approx(
            QUANTUM_TOLERANCE * SCORE_QUANTA["completeness"]
        )
        assert score_epsilon("faithfulness", 0.10) == pytest.approx(0.10)

    def test_a_coarse_metric_never_gets_a_narrower_band_than_judge_noise(self) -> None:
        # A very large `--threshold` still wins: the quantum widens the
        # band, it does not cap it.
        assert score_epsilon("completeness", 0.90) == pytest.approx(0.90)

    def test_one_flipped_topic_decision_no_longer_trips_the_gate(self) -> None:
        # ADR 0071's acceptance criterion, and the defect ADR 0044 left
        # open: `completeness` moves in steps of 0.25, so under a flat
        # 0.10 band a single borderline topic decision flipping was a
        # guaranteed red.
        baseline = {"q1": _line("q1", completeness=0.75, faithfulness=0.8)}
        current = {"q1": _line("q1", completeness=0.50, faithfulness=0.8)}
        report = diff_summaries(baseline, current, threshold=0.10)
        assert report["diffs"][0]["status"] == "unchanged"
        assert report["has_regressions"] is False

    def test_two_flipped_topic_decisions_still_do(self) -> None:
        baseline = {"q1": _line("q1", completeness=0.75, faithfulness=0.8)}
        current = {"q1": _line("q1", completeness=0.25, faithfulness=0.8)}
        report = diff_summaries(baseline, current, threshold=0.10)
        assert report["diffs"][0]["status"] == "regressed"
        assert report["has_regressions"] is True

    def test_the_quantised_band_is_symmetric_for_improvements(self) -> None:
        baseline = {"q1": _line("q1", completeness=0.25, faithfulness=0.8)}
        one_step = {"q1": _line("q1", completeness=0.50, faithfulness=0.8)}
        two_steps = {"q1": _line("q1", completeness=0.75, faithfulness=0.8)}
        assert diff_summaries(baseline, one_step)["diffs"][0]["status"] == "unchanged"
        assert diff_summaries(baseline, two_steps)["diffs"][0]["status"] == "improved"

    def test_the_report_states_the_derived_bands(self) -> None:
        md = format_report(
            diff_summaries(
                {"q1": _line("q1", completeness=0.75)},
                {"q1": _line("q1", completeness=0.75)},
            )
        )
        assert "quantum" in md
        assert "`completeness` > 0.38" in md


class TestCriticScoreIsADiagnostic:
    def test_a_critic_collapse_alone_does_not_fail_the_gate(self) -> None:
        # `critic.py` coerces an unparseable judge response to 0.0, which
        # arrives here as a full-scale quality collapse indistinguishable
        # from a real one — and it is the product grading its own output.
        baseline = {"q1": _line("q1", critic_score=0.9, faithfulness=0.8)}
        current = {"q1": _line("q1", critic_score=0.0, faithfulness=0.8)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"
        assert report["has_regressions"] is False

    def test_it_is_still_diffed_and_still_printed(self) -> None:
        baseline = {"q1": _line("q1", critic_score=0.9, faithfulness=0.8)}
        current = {"q1": _line("q1", critic_score=0.0, faithfulness=0.8)}
        report = diff_summaries(baseline, current)
        assert report["aggregate_deltas"]["critic_score"] == pytest.approx(-0.9)
        md = format_report(report)
        assert "critic_score *(not gated)*" in md

    def test_critic_score_is_absent_from_the_gated_field_set(self) -> None:
        assert "critic_score" not in METRIC_FIELDS
        assert "critic_score" in RESEARCH_LANE.tabulated_fields


class TestComparability:
    def test_matching_provenance_compares(self) -> None:
        baseline = {"q1": _provenanced(_line("q1", faithfulness=0.8))}
        current = {"q1": _provenanced(_line("q1", faithfulness=0.8))}
        verdict = check_comparability(baseline, current)
        assert verdict.comparable is True
        assert verdict.conflicts == ()

    def test_a_moved_judge_refuses_the_comparison(self) -> None:
        baseline = {"q1": _provenanced(_line("q1", faithfulness=0.8))}
        current = {
            "q1": _provenanced(_line("q1", faithfulness=0.3), judge_model="judge-b")
        }
        verdict = check_comparability(baseline, current)
        assert verdict.comparable is False
        assert any("judge_model" in conflict for conflict in verdict.conflicts)

    @pytest.mark.parametrize(
        "field",
        ["judge_model", "dataset_version", "tier", "mock_mode"],
    )
    def test_every_instrument_field_refuses(self, field: str) -> None:
        baseline = {"q1": _provenanced(_line("q1"))}
        current = {"q1": _provenanced(_line("q1"), **{field: "moved"})}
        assert check_comparability(baseline, current).comparable is False

    def test_a_bumped_rubric_version_refuses(self) -> None:
        baseline = {"q1": _provenanced(_line("q1"))}
        current = {
            "q1": _provenanced(_line("q1"), rubric_versions={"completeness": "2.0"})
        }
        verdict = check_comparability(baseline, current)
        assert verdict.comparable is False
        assert any("rubric_versions" in c for c in verdict.conflicts)

    def test_rubric_key_order_is_not_a_conflict(self) -> None:
        baseline = {"q1": _provenanced(_line("q1"), rubric_versions={"a": "1", "b": "2"})}
        current = {"q1": _provenanced(_line("q1"), rubric_versions={"b": "2", "a": "1"})}
        assert check_comparability(baseline, current).comparable is True

    def test_a_block_missing_a_field_contributes_no_value_for_it(self) -> None:
        # A block written by an older harness can lack a field this
        # check reads. Absence contributes nothing rather than an
        # empty-string value that would look like a disagreement.
        thin = dict(_provenanced(_line("q1")))
        del thin["provenance"]["tier"]
        verdict = check_comparability({"q1": thin}, {"q1": _provenanced(_line("q1"))})
        assert verdict.comparable is True

    def test_a_moved_product_model_is_a_note_not_a_refusal(self) -> None:
        # It is usually the *subject* of the comparison.
        baseline = {"q1": _provenanced(_line("q1"))}
        current = {"q1": _provenanced(_line("q1"), product_model="product-b")}
        verdict = check_comparability(baseline, current)
        assert verdict.comparable is True
        assert any("product model differs" in note for note in verdict.notes)

    def test_a_dirty_tree_is_a_note(self) -> None:
        baseline = {"q1": _provenanced(_line("q1"), code_dirty=True)}
        current = {"q1": _provenanced(_line("q1"))}
        verdict = check_comparability(baseline, current)
        assert verdict.comparable is True
        assert any("dirty working tree" in note for note in verdict.notes)

    def test_a_campaign_that_disagrees_with_itself_refuses(self) -> None:
        # `--resume` can re-enter a campaign under a different judge.
        rows = _rows(
            _provenanced(_repeat("q1", 1, faithfulness=0.8)),
            _provenanced(_repeat("q1", 2, faithfulness=0.8), judge_model="judge-b"),
        )
        aggregated = aggregate_repeats(rows, lane=RESEARCH_LANE)
        verdict = check_comparability(aggregated, aggregated)
        assert verdict.comparable is False
        assert any("disagrees with itself" in c for c in verdict.conflicts)

    def test_absent_provenance_is_unknown_not_incomparable(self) -> None:
        # Refusing here would turn every pre-ADR-0070 baseline into a
        # permanent red.
        baseline = {"q1": _line("q1", faithfulness=0.8)}
        current = {"q1": _provenanced(_line("q1", faithfulness=0.8))}
        verdict = check_comparability(baseline, current)
        assert verdict.comparable is True
        assert any("carries a provenance block" in note for note in verdict.notes)

    def test_an_incomparable_run_reaches_no_verdict(self) -> None:
        baseline = {"q1": _provenanced(_line("q1", faithfulness=0.9))}
        current = {
            "q1": _provenanced(_line("q1", faithfulness=0.1), judge_model="judge-b")
        }
        report = diff_summaries(baseline, current)
        assert report["decision"].verdict == "HOLD"
        assert "not produced by the same instrument" in report["decision"].reasons[0]
        md = format_report(report)
        assert "refused to compare them" in md

    def test_the_cli_exits_three_when_the_runs_are_incomparable(
        self, tmp_path: Path
    ) -> None:
        baseline = tmp_path / "b.jsonl"
        current = tmp_path / "c.jsonl"
        baseline.write_text(json.dumps(_provenanced(_line("q1", faithfulness=0.9))))
        current.write_text(
            json.dumps(
                _provenanced(_line("q1", faithfulness=0.1), judge_model="judge-b")
            )
        )
        assert main([str(baseline), str(current)]) == EXIT_INCOMPARABLE


class TestTheCitationMetricSwapRebaselines:
    """ADR 0074's cost, landed rather than hidden.

    Replacing `citation_accuracy` with `citation_resolution_rate`
    invalidates every baseline scored with the old one — the two are
    different measurements of different things, and a delta across the
    swap is a measurement of the swap. The mechanism that says so is
    ADR 0070's: the deterministic check versions itself into
    `provenance.rubric_versions`, which is a comparability field, so a
    pre-swap row and a post-swap row are refused rather than diffed.
    """

    @staticmethod
    def _post_swap() -> dict[str, str]:
        from src.eval.metrics import RESEARCH_RUBRICS
        from src.eval.provenance import rubric_versions

        return rubric_versions(RESEARCH_RUBRICS)

    @classmethod
    def _pre_swap(cls) -> dict[str, str]:
        versions = cls._post_swap()
        # What a row written before this work order carried: the three
        # judges, and no entry for the deterministic check.
        del versions["groundedness"]
        return versions

    def test_the_live_registry_names_the_deterministic_check(self) -> None:
        assert "groundedness" in self._post_swap()

    def test_a_pre_swap_row_is_not_comparable_to_a_post_swap_one(self) -> None:
        baseline = {
            "q1": _provenanced(
                _line("q1", citation_accuracy=0.9), rubric_versions=self._pre_swap()
            )
        }
        current = {
            "q1": _provenanced(
                _line("q1", citation_resolution_rate=0.5),
                rubric_versions=self._post_swap(),
            )
        }
        verdict = check_comparability(baseline, current)
        assert verdict.comparable is False
        assert any("rubric_versions" in conflict for conflict in verdict.conflicts)

    def test_the_cli_exits_three_across_the_swap_rather_than_diffing(
        self, tmp_path: Path
    ) -> None:
        # The whole point: without this, the differ would read the old
        # campaign's missing `citation_resolution_rate` as "unscored"
        # and publish a green diff over a metric change.
        baseline = tmp_path / "b.jsonl"
        current = tmp_path / "c.jsonl"
        baseline.write_text(
            json.dumps(
                _provenanced(
                    _line("q1", citation_accuracy=1.0),
                    rubric_versions=self._pre_swap(),
                )
            )
        )
        current.write_text(
            json.dumps(
                _provenanced(
                    _line("q1", citation_resolution_rate=0.0),
                    rubric_versions=self._post_swap(),
                )
            )
        )
        assert main([str(baseline), str(current)]) == EXIT_INCOMPARABLE

    def test_two_post_swap_runs_still_compare(self) -> None:
        rows = {
            "q1": _provenanced(
                _line("q1", citation_resolution_rate=0.5),
                rubric_versions=self._post_swap(),
            )
        }
        assert check_comparability(dict(rows), dict(rows)).comparable is True


class TestCitationAccuracyIsNowADiagnostic:
    def test_a_citation_accuracy_collapse_alone_does_not_fail_the_gate(self) -> None:
        # It returns 1.0 for a report with zero citations and resolves
        # `[Author, Year]` tags against the list the synthesizer itself
        # wrote. A metric that cannot fail on a fabrication must not be
        # able to fail a build either (ADR 0074).
        baseline = {"q1": _line("q1", citation_accuracy=1.0, faithfulness=0.8)}
        current = {"q1": _line("q1", citation_accuracy=0.0, faithfulness=0.8)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"
        assert report["has_regressions"] is False

    def test_it_is_still_diffed_and_still_printed(self) -> None:
        # ADR 0070 forbids removing a row field, and the published
        # README block still averages it.
        baseline = {"q1": _line("q1", citation_accuracy=1.0, faithfulness=0.8)}
        current = {"q1": _line("q1", citation_accuracy=0.0, faithfulness=0.8)}
        report = diff_summaries(baseline, current)
        assert report["aggregate_deltas"]["citation_accuracy"] == pytest.approx(-1.0)
        assert "citation_accuracy *(not gated)*" in format_report(report)

    def test_the_gated_citation_field_is_the_deterministic_one(self) -> None:
        assert "citation_accuracy" not in METRIC_FIELDS
        assert "citation_resolution_rate" in METRIC_FIELDS
        assert "citation_accuracy" in RESEARCH_LANE.tabulated_fields

    def test_the_gate_gets_a_band_from_the_flat_threshold_not_a_quantum(self) -> None:
        # Its quantum is `1 / denominator`, and the denominator is the
        # report's own citation count — 1 on this repository's e2e
        # fixture. Declaring that as the quantum would hand the metric a
        # band of 1.5 and a gate that can never fire.
        assert "citation_resolution_rate" not in SCORE_QUANTA
        assert score_epsilon("citation_resolution_rate", 0.10) == pytest.approx(0.10)
        assert score_epsilon(
            "citation_resolution_rate", DEFAULT_THRESHOLD
        ) == pytest.approx(DEFAULT_THRESHOLD)

    def test_one_unresolved_citation_of_five_clears_that_band(self) -> None:
        # What 0.10 means for this metric, asserted rather than assumed:
        # a single fabricated citation on a report citing five moves the
        # score 0.20 and fires.
        baseline = {"q1": _line("q1", citation_resolution_rate=1.0)}
        current = {"q1": _line("q1", citation_resolution_rate=0.8)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "regressed"

    def test_one_unresolved_citation_in_one_of_three_repeats_does_not(self) -> None:
        # And the other end of the same rule: aggregated over three
        # repeats, one unresolved citation of fifteen is 0.067, which
        # the band absorbs.
        baseline = {"q1": _line("q1", citation_resolution_rate=1.0)}
        current = {"q1": _line("q1", citation_resolution_rate=1.0 - 1 / 15)}
        report = diff_summaries(baseline, current)
        assert report["diffs"][0]["status"] == "unchanged"


class TestStatisticsAndDecision:
    def test_an_unchanged_small_campaign_holds_rather_than_promoting(self) -> None:
        rows = {
            f"q{i}": _line(f"q{i}", faithfulness=0.8, citation_resolution_rate=1.0)
            for i in range(20)
        }
        report = diff_summaries(dict(rows), dict(rows))
        assert report["decision"].verdict == "HOLD"
        assert "cannot detect" in report["decision"].reasons[0]

    def test_a_large_enough_clean_comparison_promotes(self) -> None:
        rows = {
            f"q{i}": _line(f"q{i}", faithfulness=0.8, citation_resolution_rate=1.0)
            for i in range(200)
        }
        report = diff_summaries(dict(rows), dict(rows))
        assert report["decision"].verdict == "PROMOTE"

    def test_a_campaign_that_never_scored_the_primary_metric_reaches_no_verdict(
        self,
    ) -> None:
        # ADR 0074 made the research lane's primary a metric that can
        # honestly report nothing: a campaign whose reports cited no
        # identifiers has no `citation_resolution_rate` anywhere.
        # Promoting on the strength of the secondary metrics would be
        # answering a question nobody asked.
        rows = {f"q{i}": _line(f"q{i}", faithfulness=0.8) for i in range(200)}
        report = diff_summaries(dict(rows), dict(rows))
        assert report["decision"].verdict == "HOLD"
        assert "citation_resolution_rate" in report["decision"].reasons[0]
        assert "never measured" in report["decision"].reasons[0]

    def test_a_regression_rolls_back_and_names_the_query(self) -> None:
        baseline = {"q1": _line("q1", faithfulness=0.9)}
        current = {"q1": _line("q1", faithfulness=0.5)}
        report = diff_summaries(baseline, current)
        assert report["decision"].verdict == "ROLLBACK"
        assert "q1" in report["decision"].reasons[0]
        assert main_code(report) == EXIT_REGRESSION

    def test_a_missing_baseline_holds(self) -> None:
        report = diff_summaries({}, {"q1": _line("q1", faithfulness=0.8)})
        assert report["decision"].verdict == "HOLD"
        assert "nothing was compared" in report["decision"].reasons[0]

    def test_a_sub_band_move_whose_interval_excludes_zero_holds(self) -> None:
        # Every query moved down by the same 0.05 — below the 0.10 band,
        # so nothing gates, but no resample can put zero in the interval.
        # Promoting on that would be the gate saying "fine" about a
        # movement it can see.
        baseline = {
            f"q{i}": _line(f"q{i}", faithfulness=0.8, citation_resolution_rate=0.80)
            for i in range(200)
        }
        current = {
            f"q{i}": _line(f"q{i}", faithfulness=0.8, citation_resolution_rate=0.75)
            for i in range(200)
        }
        report = diff_summaries(baseline, current)
        assert report["has_regressions"] is False
        assert report["decision"].verdict == "HOLD"
        assert "excludes zero" in report["decision"].reasons[0]

    def test_the_primary_metric_always_gets_an_interval(self) -> None:
        rows = {"q1": _line("q1", faithfulness=0.8, citation_resolution_rate=0.9)}
        report = diff_summaries(dict(rows), dict(rows))
        assert set(report["statistics"]) == {"citation_resolution_rate"}
        assert report["statistics"]["citation_resolution_rate"].primary is True

    def test_a_metric_that_moved_down_gets_a_diagnostic_interval(self) -> None:
        baseline = {"q1": _line("q1", faithfulness=0.85, citation_resolution_rate=0.9)}
        current = {"q1": _line("q1", faithfulness=0.80, citation_resolution_rate=0.9)}
        report = diff_summaries(baseline, current)
        assert set(report["statistics"]) == {"citation_resolution_rate", "faithfulness"}
        assert report["statistics"]["faithfulness"].primary is False

    def test_a_metric_that_improved_gets_no_interval(self) -> None:
        # Twenty simultaneous per-metric tests on twenty queries
        # manufacture false alarms by arithmetic, so slices are only
        # analysed where a reader is about to ask "is that real?".
        baseline = {"q1": _line("q1", faithfulness=0.5, citation_resolution_rate=0.9)}
        current = {"q1": _line("q1", faithfulness=0.8, citation_resolution_rate=0.9)}
        report = diff_summaries(baseline, current)
        assert "faithfulness" not in report["statistics"]

    def test_mcnemar_appears_for_a_binary_metric_and_not_a_ratio(self) -> None:
        binary = {
            f"s{i}": {**_session(f"s{i}.r1", shame_free=i % 2 == 0), "scenario_id": f"s{i}"}
            for i in range(6)
        }
        moved = {
            f"s{i}": {**_session(f"s{i}.r1", shame_free=True), "scenario_id": f"s{i}"}
            for i in range(6)
        }
        report = diff_summaries(binary, moved, lane=LEARNING_LANE)
        test = report["statistics"]["shame_free"].mcnemar
        assert test is not None
        assert test.candidate_only == 3
        assert test.baseline_only == 0

        ratio = {"q1": _line("q1", citation_resolution_rate=0.83)}
        stats = diff_summaries(ratio, ratio)["statistics"]
        assert stats["citation_resolution_rate"].mcnemar is None

    def test_the_seed_makes_the_interval_reproducible(self) -> None:
        baseline = {
            f"q{i}": _line(f"q{i}", citation_resolution_rate=0.5 + i / 40)
            for i in range(10)
        }
        current = {
            f"q{i}": _line(f"q{i}", citation_resolution_rate=0.6 + i / 40)
            for i in range(10)
        }
        first = diff_summaries(baseline, current, seed=42)
        second = diff_summaries(baseline, current, seed=42)
        assert (
            first["statistics"]["citation_resolution_rate"].bootstrap.interval
            == second["statistics"]["citation_resolution_rate"].bootstrap.interval
        )

    def test_the_report_carries_the_decision_power_and_caveat(self) -> None:
        rows = {
            f"q{i}": _line(f"q{i}", faithfulness=0.8, citation_resolution_rate=1.0)
            for i in range(20)
        }
        md = format_report(diff_summaries(dict(rows), dict(rows)))
        assert "## Decision" in md
        assert "### HOLD" in md
        assert "**Power.**" in md
        assert "77 pairs" in md
        assert "906" in md
        assert "approximate at n=20" in md

    def test_the_report_states_the_rule_of_three_on_a_clean_sweep(self) -> None:
        rows = {
            f"q{i}": _line(f"q{i}", faithfulness=0.8, citation_resolution_rate=1.0)
            for i in range(20)
        }
        md = format_report(diff_summaries(dict(rows), dict(rows)))
        assert "Zero failures in 20 runs" in md
        assert "15.0%" in md

    def test_pass_k_is_reported_beside_a_success_rate(self) -> None:
        rows = aggregate_repeats(
            _rows(
                *(
                    {
                        **_session(f"s{i}.r{r}", shame_free=not (i == 0 and r == 1)),
                        "scenario_id": f"s{i}",
                    }
                    for i in range(4)
                    for r in (1, 2, 3)
                )
            ),
            lane=LEARNING_LANE,
        )
        report = diff_summaries(dict(rows), dict(rows), lane=LEARNING_LANE)
        shame = next(r for r in report["reliability"] if r.label == "`shame_free`")
        assert shame.repeats == 3
        # Three scenarios are clean (pass^3 = 1) and one had a failure,
        # so its pass^3 is C(2,3)/C(3,3) = 0 — mean 0.75.
        assert shame.pass_k == pytest.approx(0.75)
        assert "pass^k" in format_report(report)

    def test_a_resource_metric_is_never_read_as_a_success_rate(self) -> None:
        # The scripted tier spends $0.00 on every session; calling that a
        # 0% success rate would be arithmetic dressed as a finding.
        rows = {
            f"s{i}": {**_session(f"s{i}.r1", cost_usd=0.0), "scenario_id": f"s{i}"}
            for i in range(4)
        }
        report = diff_summaries(dict(rows), dict(rows), lane=LEARNING_LANE)
        labels = [rate.label for rate in report["reliability"]]
        assert "`cost_usd`" not in labels
        assert "`expectation_failures`" not in labels
        assert "`shame_free`" in labels


class TestTheGateMakesNoModelCall:
    def test_the_whole_diff_runs_with_every_llm_entry_point_broken(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ADR 0071 and 02-STANDARDS.md §3.4: content-preserving wrappers
        # flip 57-100% of LLM-judge verdicts, so a judge inside a gate is
        # an attack surface rather than a control. This is that rule as
        # an assertion instead of an intention.
        import src.llm as llm_module

        def _explode(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("the regression gate called a model")

        monkeypatch.setattr(llm_module, "call_llm", _explode)
        monkeypatch.setattr(llm_module, "call_llm_json", _explode)
        monkeypatch.setattr(llm_module, "_get_client", _explode)

        baseline = {f"q{i}": _line(f"q{i}", faithfulness=0.8) for i in range(5)}
        current = {f"q{i}": _line(f"q{i}", faithfulness=0.4) for i in range(5)}
        report = diff_summaries(baseline, current)
        assert report["decision"].verdict == "ROLLBACK"
        assert format_report(report)

    def test_stats_imports_nothing_from_the_product(self) -> None:
        # A gate whose statistics module can reach the graph is a gate
        # that can be made to run one.
        source = (
            Path(__file__).resolve().parents[1] / "src" / "eval" / "stats.py"
        ).read_text()
        assert "import src." not in source
        assert "from src." not in source


def main_code(report: RegressionReport) -> int:
    """The exit status `main` would return for `report`."""
    if not report["comparability"].comparable:
        return EXIT_INCOMPARABLE
    return EXIT_REGRESSION if report["decision"].verdict == "ROLLBACK" else EXIT_OK


class TestCliStatuses:
    def test_a_clean_run_exits_zero(self, tmp_path: Path) -> None:
        baseline = tmp_path / "b.jsonl"
        current = tmp_path / "c.jsonl"
        baseline.write_text(json.dumps(_line("q1", faithfulness=0.8)))
        current.write_text(json.dumps(_line("q1", faithfulness=0.8)))
        assert main([str(baseline), str(current)]) == EXIT_OK

    def test_a_missing_current_file_exits_invalid(self, tmp_path: Path) -> None:
        assert main([str(tmp_path / "b.jsonl"), str(tmp_path / "nope.jsonl")]) == (
            EXIT_INVALID
        )

    def test_malformed_jsonl_exits_invalid(self, tmp_path: Path) -> None:
        baseline = tmp_path / "b.jsonl"
        current = tmp_path / "c.jsonl"
        baseline.write_text("{not json")
        current.write_text(json.dumps(_line("q1", faithfulness=0.8)))
        assert main([str(baseline), str(current)]) == EXIT_INVALID

    def test_the_seed_flag_is_accepted(self, tmp_path: Path) -> None:
        baseline = tmp_path / "b.jsonl"
        current = tmp_path / "c.jsonl"
        baseline.write_text(json.dumps(_line("q1", faithfulness=0.8)))
        current.write_text(json.dumps(_line("q1", faithfulness=0.8)))
        assert main([str(baseline), str(current), "--seed", "7"]) == EXIT_OK
