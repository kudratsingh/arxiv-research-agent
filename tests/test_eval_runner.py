"""Unit tests for the eval runner.

Pure helpers are tested directly. `_run_and_score` is exercised with
`build_workflow` monkeypatched (fake compiled app returns a canned
state), and metric functions monkeypatched to canned results — so no
LLM, no arXiv, no PyMuPDF, no model loading. `main()` is exercised with
`_run_and_score` itself monkeypatched, so the campaign-level behaviour
(incremental persistence, resume, budget stop, exit codes, interrupt
flush) is tested without any workflow at all.

Mutation checks are called out inline: each one is a test that passes
only because of the ADR 0050 change and fails against the pre-ADR code.
"""

import json
import signal
from pathlib import Path
from typing import Any

import pytest

from src.eval import runner as runner_module
from src.eval.benchmark_queries import BENCHMARK_QUERIES, RESEARCH_DATASET_VERSION
from src.eval.provenance import check_provenance
from src.eval.runner import (
    EXIT_ALL_FAILED,
    EXIT_BUDGET_STOP,
    EXIT_CONFIG,
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_PARTIAL_FAILURE,
    EXIT_USAGE,
    EvalInterrupted,
    _benchmark_order,
    _check_output_dir,
    _claim_outcomes,
    _compute_metrics,
    _cost_delta,
    _exit_code,
    _fmt,
    _fmt_cell_text,
    _get_count,
    _get_score,
    _initial_state,
    _install_interrupt_handler,
    _mean,
    _record_total_cost,
    _run_and_score,
    _select_queries,
    _serialize_state,
    _summary_line,
    _summary_markdown,
    load_records,
    persist_record,
    rebuild_summaries,
)
from src.graph.state import ResearchState
from src.observability.logging import current_run_id

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# State + record helpers
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_returns_all_researchstate_keys(self) -> None:
        state = _initial_state("what is X?", "run-a")
        expected = {
            "run_id",
            "query",
            "sub_questions",
            "search_queries",
            "papers",
            "paper_analyses",
            "draft_report",
            "citations",
            "critique",
            "quality_score",
            "revision_needed",
            "revision_target",
            "iteration",
            "next_action",
            "loop_iterations",
            "stop_reason",
            "verified",
            "unsupported_claims",
            "missing_evidence",
            "verifier_recommendation",
            "evidence",
            "tried_search_queries",
            "reader_analysis_complete",
            "reader_missing_context",
            "reader_requested_sections",
            "prior_context",
            "messages",
        }
        assert set(state.keys()) == expected

    def test_query_is_stored(self) -> None:
        assert _initial_state("hallucination?", "r")["query"] == "hallucination?"

    def test_run_id_is_stored(self) -> None:
        assert _initial_state("q", "rid-123")["run_id"] == "rid-123"

    def test_iteration_starts_at_zero(self) -> None:
        assert _initial_state("x", "r")["iteration"] == 0


class TestSerializeState:
    def test_drops_messages(self) -> None:
        state: ResearchState = _initial_state("q", "r")
        state["messages"] = ["not-serializable-marker"]  # type: ignore[typeddict-item]
        result = _serialize_state(state)
        assert "messages" not in result

    def test_keeps_everything_else(self) -> None:
        state = _initial_state("q", "r")
        result = _serialize_state(state)
        for key in state:
            if key == "messages":
                continue
            assert key in result


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------


class TestGetScore:
    def test_extracts_score_from_metric_dict(self) -> None:
        metrics = {"citation_accuracy": {"score": 0.75, "resolved": 3}}
        assert _get_score(metrics, "citation_accuracy") == 0.75

    def test_missing_metric_returns_none(self) -> None:
        assert _get_score({}, "citation_accuracy") is None

    def test_metric_without_score_returns_none(self) -> None:
        assert _get_score({"citation_accuracy": {}}, "citation_accuracy") is None

    def test_int_score_coerced_to_float(self) -> None:
        assert _get_score({"m": {"score": 1}}, "m") == 1.0

    def test_non_dict_metrics_returns_none(self) -> None:
        assert _get_score(None, "citation_accuracy") is None
        assert _get_score("bad", "citation_accuracy") is None

    def test_failed_metric_none_reads_as_no_score(self) -> None:
        # `_compute_metrics` stores `None` for a judge that blew up.
        assert _get_score({"faithfulness": None}, "faithfulness") is None


class TestGetCount:
    def test_extracts_integer_counter(self) -> None:
        metrics = {"citation_accuracy": {"score": 1.0, "total_citations": 0}}
        assert _get_count(metrics, "citation_accuracy", "total_citations") == 0

    def test_bool_is_not_a_count(self) -> None:
        assert _get_count({"m": {"n": True}}, "m", "n") is None

    def test_missing_returns_none(self) -> None:
        assert _get_count({}, "citation_accuracy", "total_citations") is None
        assert _get_count(None, "m", "n") is None


class TestFmt:
    def test_none_dashes(self) -> None:
        assert _fmt(None) == "-"

    def test_float_two_decimals(self) -> None:
        assert _fmt(0.4245) == "0.42"

    def test_int_stringified(self) -> None:
        assert _fmt(3) == "3"

    def test_str_passthrough(self) -> None:
        assert _fmt("hello") == "hello"


class TestFmtCellText:
    """Exception text must not be able to corrupt the markdown table."""

    def test_none_and_empty_dash(self) -> None:
        assert _fmt_cell_text(None) == "-"
        assert _fmt_cell_text("") == "-"

    def test_pipe_escaped(self) -> None:
        # Mutation check: without the escape the row gains a column.
        assert _fmt_cell_text("a | b") == "a \\| b"

    def test_newlines_collapsed(self) -> None:
        # Mutation check: a raw newline ends the table row early.
        assert "\n" not in _fmt_cell_text("Traceback:\n  File x\n  boom")
        assert _fmt_cell_text("a\nb") == "a b"

    def test_long_text_truncated_with_ellipsis(self) -> None:
        out = _fmt_cell_text("x" * 500)
        assert len(out) == runner_module._ERROR_CELL_MAX
        assert out.endswith("…")

    def test_short_text_untouched(self) -> None:
        assert _fmt_cell_text("APIError: overloaded") == "APIError: overloaded"


class TestMean:
    def test_computes_mean_ignoring_nones(self) -> None:
        rows = [
            {"score": 1.0},
            {"score": 0.5},
            {"score": None},
        ]
        assert _mean(rows, "score") == "0.750"

    def test_all_none_returns_dash(self) -> None:
        rows = [{"score": None}, {"score": None}]
        assert _mean(rows, "score") == "-"

    def test_empty_returns_dash(self) -> None:
        assert _mean([], "score") == "-"


class TestCostDelta:
    def test_differences_scalar_totals(self) -> None:
        before = {"total_cost_usd": 1.0, "call_count": 3, "total_input_tokens": 10}
        after = {"total_cost_usd": 1.75, "call_count": 5, "total_input_tokens": 40}
        delta = _cost_delta(after, before)
        assert delta["total_cost_usd"] == pytest.approx(0.75)
        assert delta["call_count"] == 2
        assert delta["total_input_tokens"] == 30

    def test_missing_fields_treated_as_zero(self) -> None:
        assert _cost_delta({}, {})["total_cost_usd"] == 0
        assert _cost_delta({"call_count": 4}, {})["call_count"] == 4

    def test_per_model_not_differenced(self) -> None:
        delta = _cost_delta({"per_model": {"a": {}}}, {"per_model": {}})
        assert "per_model" not in delta


class TestRecordTotalCost:
    def test_sums_workflow_and_judge(self) -> None:
        record = {
            "costs": {"total_cost_usd": 0.30},
            "judge_costs": {"total_cost_usd": 0.05},
        }
        assert _record_total_cost(record) == pytest.approx(0.35)

    def test_missing_judge_costs_is_zero(self) -> None:
        assert _record_total_cost({"costs": {"total_cost_usd": 0.3}}) == pytest.approx(
            0.3
        )

    def test_empty_record_is_zero(self) -> None:
        assert _record_total_cost({}) == 0.0


class TestSummaryLine:
    def test_extracts_scores_state_and_split_cost_fields(self) -> None:
        record = {
            "query_id": "q1",
            "elapsed_sec": 12.5,
            "scoring_sec": 3.0,
            "error": None,
            "metrics_error": None,
            "metrics": {
                "citation_resolution_rate": {
                    "score": 0.5,
                    "total_citations": 2,
                    "reason": None,
                },
                "citation_accuracy": {"score": 0.8, "total_citations": 4},
                "completeness": {"score": 0.6},
                "faithfulness": {"score": 0.7},
                "retrieval_recall": {"score": 0.85},
            },
            "state": {"quality_score": 0.75, "iteration": 2},
            "costs": {"total_cost_usd": 0.0421, "call_count": 33},
            "judge_costs": {"total_cost_usd": 0.0079, "call_count": 3},
            "provenance": {"judge_model": "judge-x"},
        }
        line = _summary_line(record)
        assert line == {
            # ADR 0071: `record_id` names the run and `query_id` the
            # query. They are the same string at one repeat, which is
            # what keeps every campaign written before `--repeats`
            # readable and resumable.
            "record_id": "q1",
            "query_id": "q1",
            "repeat": 1,
            "elapsed_sec": 12.5,
            "scoring_sec": 3.0,
            "error": None,
            "metrics_error": None,
            # ADR 0074: the gated citation metric, its denominator, and
            # the reason it would be `None`. Added beside
            # `citation_accuracy` rather than replacing it, because ADR
            # 0070 forbids removing a row field.
            "citation_resolution_rate": 0.5,
            "citations_checked": 2,
            "citation_resolution_reason": None,
            "citation_accuracy": 0.8,
            "completeness": 0.6,
            "faithfulness": 0.7,
            "retrieval_recall": 0.85,
            "total_citations": 4,
            "critic_score": 0.75,
            "iterations": 2,
            "cost_usd": 0.0421,
            "llm_calls": 33,
            "judge_cost_usd": 0.0079,
            "judge_llm_calls": 3,
            "total_cost_usd": 0.05,
            "loop_iterations": None,
            "stop_reason": None,
            # WO-C1: the per-claim outcomes `regression_diff` pairs on.
            # `None` here rather than `{}` because this record carries no
            # `groundedness` block at all — "not computed" and "computed
            # and empty" are different facts about a run, and a row that
            # collapsed them would put an empty McNemar arm beside a
            # populated one.
            "paired_outcomes": None,
            "claims_decided": None,
            "provenance": {"judge_model": "judge-x"},
        }

    def test_the_claim_outcomes_ride_on_the_row_when_the_record_carries_them(
        self,
    ) -> None:
        """A record with a groundedness block publishes it and its count."""
        line = _summary_line(
            {
                "query_id": "q1",
                "groundedness": {"citation:aaaa": True, "citation:bbbb": False},
            }
        )
        assert line["paired_outcomes"] == {
            "citation:aaaa": True,
            "citation:bbbb": False,
        }
        assert line["claims_decided"] == 2

    def test_cost_usd_excludes_judge_spend(self) -> None:
        # Mutation check for ADR 0050's accounting split: before it,
        # `cost_usd` was the single accumulator total and folded the
        # judges' own calls into the product's figure.
        record = {
            "query_id": "q1",
            "costs": {"total_cost_usd": 1.0, "call_count": 10},
            "judge_costs": {"total_cost_usd": 0.25, "call_count": 3},
        }
        line = _summary_line(record)
        assert line["cost_usd"] == pytest.approx(1.0)
        assert line["llm_calls"] == 10
        assert line["judge_cost_usd"] == pytest.approx(0.25)
        assert line["judge_llm_calls"] == 3
        assert line["total_cost_usd"] == pytest.approx(1.25)

    def test_total_cost_none_when_both_sides_unknown(self) -> None:
        line = _summary_line({"query_id": "q1"})
        assert line["total_cost_usd"] is None

    def test_error_record_has_none_metrics(self) -> None:
        record = {
            "query_id": "q1",
            "elapsed_sec": 0.1,
            "error": "boom",
            "metrics": None,
            "state": None,
        }
        line = _summary_line(record)
        assert line["error"] == "boom"
        assert line["citation_accuracy"] is None
        assert line["critic_score"] is None


class TestTheHonestCitationMetricReachesTheRow:
    """ADR 0074: a `null` rate is only honest with its reason beside it."""

    def test_a_report_that_cited_nothing_carries_a_reason_not_a_score(self) -> None:
        record = {
            "query_id": "q1",
            "metrics": {
                "citation_resolution_rate": {
                    "score": None,
                    "total_citations": 0,
                    "reason": "no_citations",
                },
                # The legacy metric awards its free 1.0 on the same run.
                # Both land on the row; only one of them gates.
                "citation_accuracy": {"score": 1.0, "total_citations": 0},
            },
        }
        line = _summary_line(record)
        assert line["citation_resolution_rate"] is None
        assert line["citations_checked"] == 0
        assert line["citation_resolution_reason"] == "no_citations"
        assert line["citation_accuracy"] == 1.0

    def test_a_failed_metric_leaves_no_reason_behind(self) -> None:
        # A judge/scorer exception lands as `None` in the metrics dict.
        # "The metric could not run" must not be dressed up as a reason
        # code the check emitted.
        line = _summary_line({"query_id": "q1", "metrics": {
            "citation_resolution_rate": None,
        }})
        assert line["citation_resolution_rate"] is None
        assert line["citations_checked"] is None
        assert line["citation_resolution_reason"] is None

    def test_the_markdown_prints_the_rate_beside_its_denominator(self) -> None:
        records = [
            {
                "query_id": "q1",
                "costs": {"total_cost_usd": 0.0, "call_count": 0},
                "metrics": {
                    "citation_resolution_rate": {
                        "score": None,
                        "total_citations": 0,
                        "reason": "no_citations",
                    },
                    "citation_accuracy": {"score": 1.0, "total_citations": 0},
                },
            },
            {
                "query_id": "q2",
                "costs": {"total_cost_usd": 0.0, "call_count": 0},
                "metrics": {
                    "citation_resolution_rate": {
                        "score": 0.5,
                        "total_citations": 4,
                        "reason": None,
                    },
                    "citation_accuracy": {"score": 1.0, "total_citations": 2},
                },
            },
        ]
        md = runner_module._summary_markdown(records, "run-1")
        assert "| Run | Cit.Res. | Cited |" in md
        # A `-` under the rate with a 0 beside it is a finding, not a
        # missing measurement.
        assert "| q1 | - | 0 |" in md
        assert "| q2 | 0.50 | 4 |" in md
        # And the aggregate says how many runs it actually covered.
        assert "Mean citation resolution: 0.500 (1 of 2 runs cited anything)" in md
        assert "Mean citation accuracy *(not gated)*: 1.000" in md


class TestResearchProvenance:
    """ADR 0070: a research row must be able to name what produced it."""

    def test_a_run_record_carries_a_complete_provenance_block(self) -> None:
        block = runner_module.research_provenance()
        assert check_provenance(dict(block)) == []

    def test_the_block_names_the_research_lane_and_its_dataset(self) -> None:
        block = runner_module.research_provenance()
        assert block["tier"] == runner_module.RESEARCH_TIER
        assert block["dataset_version"] == RESEARCH_DATASET_VERSION

    def test_the_block_records_every_rubric_the_lane_runs(self) -> None:
        block = runner_module.research_provenance()
        assert set(block["rubric_versions"]) == {
            "completeness",
            "faithfulness",
            # The deterministic groundedness check versions itself too
            # (ADR 0074) — it is what makes a pre-swap row and a
            # post-swap one refuse to be compared.
            "groundedness",
            "retrieval_recall",
        }

    def test_the_summary_row_copies_the_records_block_rather_than_recapturing(
        self,
    ) -> None:
        # A resumed campaign rebuilds `summary.jsonl` from records that
        # may be days old; recapturing at render time would describe the
        # rebuild instead of the run.
        record = {"query_id": "q1", "provenance": {"judge_model": "recorded-at-run"}}
        assert _summary_line(record)["provenance"] == {"judge_model": "recorded-at-run"}

    def test_a_record_written_before_adr_0070_yields_an_unusable_block(self) -> None:
        line = _summary_line({"query_id": "q1"})
        assert line["provenance"] == {}
        assert check_provenance(line["provenance"])

    def test_the_summary_markdown_names_the_judge_and_the_commit(self) -> None:
        record = {
            "query_id": "q1",
            "costs": {"total_cost_usd": 0.1, "call_count": 3},
            "provenance": dict(runner_module.research_provenance()),
        }
        markdown = _summary_markdown([record], "run-1")
        assert "## Provenance" in markdown
        assert "judge_model" in markdown
        assert "code_commit" in markdown


class TestSummaryMarkdown:
    def test_header_and_counts_present(self) -> None:
        records = [
            {
                "query_id": "q1",
                "elapsed_sec": 1.0,
                "metrics": {
                    "citation_accuracy": {"score": 1.0},
                    "completeness": {"score": 1.0},
                    "faithfulness": {"score": 1.0},
                },
                "state": {"quality_score": 0.9, "iteration": 1},
            }
        ]
        md = _summary_markdown(records, "run-abc")
        assert "run-abc" in md
        assert "**Queries**: 1" in md
        assert "**Errors**: 0" in md
        assert "| q1 |" in md
        assert "Aggregates" in md

    def test_error_count_reflects_errored_records(self) -> None:
        records = [
            {"query_id": "q1", "error": "boom", "metrics": None, "state": None},
            {
                "query_id": "q2",
                "elapsed_sec": 1.0,
                "metrics": {
                    "citation_accuracy": {"score": 0.5},
                    "completeness": {"score": 0.5},
                    "faithfulness": {"score": 0.5},
                },
                "state": {"quality_score": 0.5, "iteration": 1},
            },
        ]
        md = _summary_markdown(records, "run-x")
        assert "**Errors**: 1" in md
        assert "| q1 |" in md
        assert "| q2 |" in md

    def test_no_aggregates_section_when_all_errored(self) -> None:
        records = [
            {"query_id": "q1", "error": "boom", "metrics": None, "state": None}
        ]
        md = _summary_markdown(records, "run-x")
        assert "Aggregates" not in md

    def test_partial_score_count_reported(self) -> None:
        records = [
            {
                "query_id": "q1",
                "elapsed_sec": 1.0,
                "metrics": {"citation_accuracy": {"score": 0.5}},
                "metrics_error": "faithfulness: APIError: overloaded",
                "state": {"quality_score": 0.5},
            }
        ]
        md = _summary_markdown(records, "run-x")
        assert "**Errors**: 0" in md
        assert "**Partial scores** (judge failed, run kept): 1" in md

    def test_cost_split_reported_separately(self) -> None:
        records = [
            {
                "query_id": "q1",
                "elapsed_sec": 1.0,
                "metrics": {"citation_accuracy": {"score": 1.0}},
                "state": {},
                "costs": {"total_cost_usd": 0.20, "call_count": 12},
                "judge_costs": {"total_cost_usd": 0.05, "call_count": 3},
            }
        ]
        md = _summary_markdown(records, "run-x")
        assert "**Workflow cost**: $0.2000" in md
        assert "**Judge cost**: $0.0500" in md
        assert "**Total cost**: $0.2500" in md

    def test_table_survives_pipes_in_error_text(self) -> None:
        # Mutation check for `_fmt_cell_text`: a raw `|` in the error
        # would add a column and shift every later cell.
        records = [
            {
                "query_id": "q1",
                "error": "APIError: bad | request\nsecond line",
                "metrics": None,
                "state": None,
            }
        ]
        md = _summary_markdown(records, "run-x")
        header = next(
            line for line in md.splitlines() if line.startswith("| Run |")
        )
        row = next(line for line in md.splitlines() if line.startswith("| q1 |"))
        # Only *unescaped* pipes are cell separators; the row must have
        # exactly as many as the header, and stay on one line.
        assert row.replace("\\|", "").count("|") == header.count("|")
        assert "bad \\| request second line" in row


# ---------------------------------------------------------------------------
# Query selection
# ---------------------------------------------------------------------------


class TestSelectQueries:
    def test_none_returns_all(self) -> None:
        result = _select_queries(None)
        assert len(result) == len(BENCHMARK_QUERIES)

    def test_empty_list_returns_all(self) -> None:
        assert _select_queries([]) == list(BENCHMARK_QUERIES)

    def test_filter_preserves_requested_order(self) -> None:
        # Second listed query first
        ids = ["rag-multi-hop", "hallucination-mitigation"]
        result = _select_queries(ids)
        assert [q["query_id"] for q in result] == ids

    def test_unknown_id_raises_system_exit(self) -> None:
        with pytest.raises(SystemExit):
            _select_queries(["hallucination-mitigation", "does-not-exist"])


class TestBenchmarkOrder:
    def test_known_ids_sort_in_benchmark_order(self) -> None:
        ids = [q["query_id"] for q in BENCHMARK_QUERIES]
        shuffled = list(reversed(ids))
        assert sorted(shuffled, key=_benchmark_order) == ids

    def test_unknown_ids_sort_last_alphabetically(self) -> None:
        first = BENCHMARK_QUERIES[0]["query_id"]
        ordered = sorted([first, "zz-retired", "aa-retired"], key=_benchmark_order)
        assert ordered == [first, "aa-retired", "zz-retired"]


# ---------------------------------------------------------------------------
# Metric isolation (_compute_metrics)
# ---------------------------------------------------------------------------


def _stub_metrics(
    monkeypatch: pytest.MonkeyPatch,
    *,
    faithfulness_raises: BaseException | None = None,
    calls: list[str] | None = None,
) -> None:
    """Replace all five metric functions with cheap deterministic stubs."""

    def _make(name: str, payload: dict[str, Any]) -> Any:
        def _fn(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            if calls is not None:
                calls.append(name)
            if name == "faithfulness" and faithfulness_raises is not None:
                raise faithfulness_raises
            return payload

        return _fn

    monkeypatch.setattr(
        runner_module,
        "measure_citation_accuracy",
        _make(
            "citation_accuracy",
            {"score": 0.9, "total_citations": 2, "resolved": 2, "unresolved": []},
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "measure_citation_resolution",
        _make(
            "citation_resolution_rate",
            {
                "score": 0.5,
                "total_citations": 2,
                "resolved": 1,
                "excluded": 0,
                "reason": None,
                "unresolved": ["arxiv:2311.05232 [citation_not_retrieved]"],
                "check_version": "1.0.0",
                "spec_digest": "deadbeef",
            },
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "measure_completeness",
        _make(
            "completeness",
            {"score": 0.6, "total_topics": 2, "covered_topics": 1, "coverage": []},
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "measure_faithfulness",
        _make(
            "faithfulness",
            {
                "score": 0.7,
                "total_claims": 3,
                "supported": 2,
                "unsupported": 1,
                "source_unavailable": 0,
                "claims": [],
            },
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "measure_retrieval_recall",
        _make(
            "retrieval_recall",
            {"score": 0.85, "total_topics": 2, "covered_topics": 2, "coverage": []},
        ),
    )


class TestComputeMetrics:
    def test_all_five_scored_and_no_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_metrics(monkeypatch)
        metrics, error = _compute_metrics(_finished_state(), BENCHMARK_QUERIES[0])
        assert error is None
        assert set(metrics) == {
            "citation_resolution_rate",
            "citation_accuracy",
            "completeness",
            "faithfulness",
            "retrieval_recall",
        }
        assert metrics["faithfulness"]["score"] == 0.7

    def test_one_failing_judge_does_not_stop_the_others(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # THE P0 mutation check. Before ADR 0050 `_compute_metrics` had
        # no guard, so this RuntimeError walked out of `_run_and_score`
        # and out of `main()`'s loop, discarding a paid workflow run and
        # every query after it. Delete the try/except and this fails.
        _stub_metrics(
            monkeypatch, faithfulness_raises=RuntimeError("judge 529'd out")
        )
        metrics, error = _compute_metrics(_finished_state(), BENCHMARK_QUERIES[0])
        assert metrics["faithfulness"] is None
        assert metrics["citation_accuracy"]["score"] == 0.9
        assert metrics["completeness"]["score"] == 0.6
        assert metrics["retrieval_recall"]["score"] == 0.85
        assert error is not None
        assert "faithfulness" in error
        assert "RuntimeError" in error
        assert "judge 529'd out" in error

    def test_keyboard_interrupt_is_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The guard is `except Exception`, deliberately: a Ctrl-C or a
        # SIGTERM must still unwind rather than being logged as a
        # metric failure.
        _stub_metrics(monkeypatch, faithfulness_raises=KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            _compute_metrics(_finished_state(), BENCHMARK_QUERIES[0])


# ---------------------------------------------------------------------------
# _run_and_score integration (with mocked workflow + metrics)
# ---------------------------------------------------------------------------


class _FakeApp:
    """Stand-in for the compiled LangGraph app used in tests."""

    def __init__(self, state: ResearchState) -> None:
        self._state = state

    def invoke(self, _initial: ResearchState, config: Any = None) -> ResearchState:
        return self._state


class _ClosingStack:
    """Minimal `ExitStack` stand-in that records whether it was closed."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _finished_state(report: str = "A report body [Smith, 2023].") -> ResearchState:
    """A state that looks like a completed workflow run."""
    return {
        "query": "seed",
        "sub_questions": ["sq1"],
        "search_queries": ["sq1 kw"],
        "papers": [],
        "paper_analyses": [],
        "draft_report": report,
        "citations": [],
        "critique": "ok",
        "quality_score": 0.8,
        "revision_needed": False,
        "revision_target": "",
        "iteration": 1,
        "stop_reason": "",
        "messages": [],
    }


class TestRunAndScoreSuccess:
    def test_populates_record_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module,
            "build_workflow",
            lambda **_kw: _FakeApp(_finished_state()),
        )
        _stub_metrics(monkeypatch)

        record = _run_and_score(BENCHMARK_QUERIES[0])

        assert record["error"] is None
        assert record["metrics_error"] is None
        assert record["query_id"] == BENCHMARK_QUERIES[0]["query_id"]
        assert record["elapsed_sec"] >= 0
        assert record["scoring_sec"] is not None
        assert record["state"]["draft_report"].startswith("A report body")
        # messages field stripped by _serialize_state
        assert "messages" not in record["state"]
        assert record["metrics"]["citation_accuracy"]["score"] == 0.9
        assert record["metrics"]["completeness"]["score"] == 0.6
        assert record["metrics"]["faithfulness"]["score"] == 0.7
        assert record["metrics"]["retrieval_recall"]["score"] == 0.85
        assert record["judge_costs"] is not None

    def test_judge_spend_is_split_out_of_workflow_cost(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # THE P1 mutation check for the accounting split. The fake
        # workflow bills $1.00 during `invoke`; the fake judges bill
        # $0.10 each afterwards. Before ADR 0050 the record's single
        # `costs` snapshot was taken after scoring, so the workflow was
        # charged $1.40.
        from src.observability.costs import current_costs

        def _bill(model: str, cost: float) -> None:
            accumulator = current_costs()
            assert accumulator is not None
            accumulator.record(model, 100, 100, cost)

        class _BillingApp(_FakeApp):
            def invoke(
                self, _initial: ResearchState, config: Any = None
            ) -> ResearchState:
                _bill("workflow-model", 1.0)
                return self._state

        monkeypatch.setattr(
            runner_module,
            "build_workflow",
            lambda **_kw: _BillingApp(_finished_state()),
        )

        def _judge(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            _bill("judge-model", 0.10)
            return {"score": 1.0, "total_citations": 1}

        for name in (
            "measure_citation_accuracy",
            "measure_completeness",
            "measure_faithfulness",
            "measure_retrieval_recall",
        ):
            monkeypatch.setattr(runner_module, name, _judge)

        record = _run_and_score(BENCHMARK_QUERIES[0])

        assert record["costs"]["total_cost_usd"] == pytest.approx(1.0)
        assert record["costs"]["call_count"] == 1
        assert record["judge_costs"]["total_cost_usd"] == pytest.approx(0.4)
        assert record["judge_costs"]["call_count"] == 4
        assert _record_total_cost(record) == pytest.approx(1.4)

    def test_run_id_binding_is_released(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module,
            "build_workflow",
            lambda **_kw: _FakeApp(_finished_state()),
        )
        _stub_metrics(monkeypatch)
        before = current_run_id()
        _run_and_score(BENCHMARK_QUERIES[0])
        assert current_run_id() == before

    def test_checkpointer_exit_stack_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # P3 fd leak: one compiled graph per query means one leaked
        # checkpointer connection per query without this close.
        app = _FakeApp(_finished_state())
        stack = _ClosingStack()
        app._checkpointer_exit_stack = stack  # type: ignore[attr-defined]
        monkeypatch.setattr(runner_module, "build_workflow", lambda **_kw: app)
        _stub_metrics(monkeypatch)

        _run_and_score(BENCHMARK_QUERIES[0])

        assert stack.closed is True


class TestRunAndScoreError:
    def test_workflow_exception_captured_on_record(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**_kw: Any) -> None:
            raise RuntimeError("no connectivity")

        monkeypatch.setattr(runner_module, "build_workflow", _boom)

        record = _run_and_score(BENCHMARK_QUERIES[0])

        assert record["error"] is not None
        assert "RuntimeError" in record["error"]
        assert "no connectivity" in record["error"]
        assert record["state"] is None
        assert record["metrics"] is None
        assert "traceback" in record

    def test_run_id_released_after_workflow_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The pre-ADR-0050 code called `reset_run_id` only on the happy
        # path, so a failed query leaked its run_id into every later
        # query's log lines.
        def _boom(**_kw: Any) -> None:
            raise RuntimeError("no connectivity")

        monkeypatch.setattr(runner_module, "build_workflow", _boom)
        before = current_run_id()
        _run_and_score(BENCHMARK_QUERIES[0])
        assert current_run_id() == before

    def test_judge_failure_keeps_the_paid_workflow_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # THE P0 end-to-end check: the expensive artifact (state,
        # costs, elapsed) survives a judge blowing up, and the record
        # is returned rather than raised.
        monkeypatch.setattr(
            runner_module,
            "build_workflow",
            lambda **_kw: _FakeApp(_finished_state()),
        )
        _stub_metrics(
            monkeypatch, faithfulness_raises=RuntimeError("judge 529'd out")
        )

        record = _run_and_score(BENCHMARK_QUERIES[0])

        assert record["error"] is None  # the *run* did not fail
        assert record["state"]["draft_report"].startswith("A report body")
        assert record["costs"] is not None
        assert record["elapsed_sec"] >= 0
        assert record["metrics"]["faithfulness"] is None
        assert record["metrics"]["citation_accuracy"]["score"] == 0.9
        assert "RuntimeError" in record["metrics_error"]

    def test_empty_report_is_an_error_and_skips_all_judges(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # P2 mutation check: an empty report used to score
        # citation_accuracy=1.0 / faithfulness=1.0 by short-circuit and
        # publish as a perfect run, at the price of two wasted judge
        # calls.
        state = _finished_state(report="   \n  ")
        state["stop_reason"] = "max_loops"
        monkeypatch.setattr(
            runner_module, "build_workflow", lambda **_kw: _FakeApp(state)
        )
        calls: list[str] = []
        _stub_metrics(monkeypatch, calls=calls)

        record = _run_and_score(BENCHMARK_QUERIES[0])

        assert record["error"] == "NoReportProduced: stop_reason=max_loops"
        assert record["metrics"] is None
        assert calls == []
        # The workflow's spend and state are still recorded.
        assert record["state"] is not None
        assert record["costs"] is not None

    def test_interrupt_carries_the_partial_record_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # P0/P1 mutation check: the in-flight query's spend used to be
        # dropped on the floor by Ctrl-C.
        class _InterruptingApp(_FakeApp):
            def invoke(
                self, _initial: ResearchState, config: Any = None
            ) -> ResearchState:
                raise KeyboardInterrupt("signal 15")

        monkeypatch.setattr(
            runner_module,
            "build_workflow",
            lambda **_kw: _InterruptingApp(_finished_state()),
        )

        with pytest.raises(EvalInterrupted) as excinfo:
            _run_and_score(BENCHMARK_QUERIES[0])

        record = excinfo.value.record
        assert record["query_id"] == BENCHMARK_QUERIES[0]["query_id"]
        assert "Interrupted" in record["error"]
        assert record["elapsed_sec"] >= 0

    def test_interrupt_still_releases_run_id_and_closes_stack(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _FakeApp(_finished_state())
        stack = _ClosingStack()
        app._checkpointer_exit_stack = stack  # type: ignore[attr-defined]

        def _build(**_kw: Any) -> Any:
            return app

        def _invoke(*_args: Any, **_kwargs: Any) -> ResearchState:
            raise KeyboardInterrupt("signal 15")

        app.invoke = _invoke  # type: ignore[method-assign]
        monkeypatch.setattr(runner_module, "build_workflow", _build)

        before = current_run_id()
        with pytest.raises(EvalInterrupted):
            _run_and_score(BENCHMARK_QUERIES[0])
        assert current_run_id() == before
        assert stack.closed is True


# ---------------------------------------------------------------------------
# Incremental persistence
# ---------------------------------------------------------------------------


def _record(qid: str, err: str | None = None, cost: float = 0.0) -> dict[str, Any]:
    """A record shaped like `_run_and_score`'s output."""
    if err:
        return {
            "query_id": qid,
            "query": "q",
            "domain": "d",
            "elapsed_sec": 0.1,
            "state": None,
            "metrics": None,
            "metrics_error": None,
            "costs": {"total_cost_usd": cost, "call_count": 1},
            "judge_costs": None,
            "error": err,
        }
    return {
        "query_id": qid,
        "query": "q",
        "domain": "d",
        "elapsed_sec": 1.5,
        "scoring_sec": 0.5,
        "state": {"quality_score": 0.7, "iteration": 1},
        "metrics": {
            "citation_accuracy": {"score": 1.0, "total_citations": 3},
            "completeness": {"score": 0.5},
            "faithfulness": {"score": 0.8},
        },
        "metrics_error": None,
        "costs": {"total_cost_usd": cost, "call_count": 10},
        "judge_costs": {"total_cost_usd": 0.0, "call_count": 3},
        "error": None,
    }


class TestPersistRecord:
    def test_writes_per_query_json_and_appends_summary_line(
        self, tmp_path: Path
    ) -> None:
        # THE P0/P1 mutation check for incremental persistence: the
        # pre-ADR-0050 runner wrote everything once, at the end, so a
        # kill at query 15 lost fourteen paid records.
        persist_record(tmp_path, _record("q1"))
        assert (tmp_path / "queries" / "q1.json").is_file()
        assert len((tmp_path / "summary.jsonl").read_text().splitlines()) == 1

        persist_record(tmp_path, _record("q2", err="boom"))
        assert json.loads((tmp_path / "queries" / "q2.json").read_text())[
            "error"
        ] == "boom"
        lines = (tmp_path / "summary.jsonl").read_text().splitlines()
        assert len(lines) == 2
        assert [json.loads(line)["query_id"] for line in lines] == ["q1", "q2"]

    def test_creates_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested"
        persist_record(target, _record("q1"))
        assert (target / "queries" / "q1.json").is_file()

    def test_non_serializable_values_do_not_raise(self, tmp_path: Path) -> None:
        record = _record("q1")
        record["state"] = {"weird": object()}
        persist_record(tmp_path, record)
        assert (tmp_path / "queries" / "q1.json").is_file()


class TestLoadRecords:
    def test_reads_back_persisted_records(self, tmp_path: Path) -> None:
        persist_record(tmp_path, _record("q1"))
        persist_record(tmp_path, _record("q2"))
        loaded = load_records(tmp_path)
        assert set(loaded) == {"q1", "q2"}
        assert loaded["q1"]["elapsed_sec"] == 1.5

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        assert load_records(tmp_path / "nope") == {}

    def test_corrupt_record_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        # One truncated file (killed mid-write) must not cost us the
        # other nineteen records.
        persist_record(tmp_path, _record("q1"))
        (tmp_path / "queries" / "broken.json").write_text("{not json")
        loaded = load_records(tmp_path)
        assert set(loaded) == {"q1"}

    def test_record_without_query_id_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "queries").mkdir()
        (tmp_path / "queries" / "x.json").write_text('{"no": "id"}')
        assert load_records(tmp_path) == {}


class TestRebuildSummaries:
    def test_rebuilds_from_disk_in_benchmark_order(self, tmp_path: Path) -> None:
        ids = [q["query_id"] for q in BENCHMARK_QUERIES[:3]]
        for qid in reversed(ids):
            persist_record(tmp_path, _record(qid))

        records = rebuild_summaries(tmp_path, "run-x")

        assert [r["query_id"] for r in records] == ids
        lines = (tmp_path / "summary.jsonl").read_text().splitlines()
        assert [json.loads(line)["query_id"] for line in lines] == ids
        md = (tmp_path / "summary.md").read_text()
        assert "run-x" in md
        for qid in ids:
            assert f"| {qid} |" in md

    def test_rewrite_deduplicates_appended_lines(self, tmp_path: Path) -> None:
        # A resumed campaign appends fresh lines beside the ones the
        # first attempt already wrote; the end-of-run rebuild is what
        # makes summary.jsonl exactly one line per query again.
        persist_record(tmp_path, _record("q1"))
        persist_record(tmp_path, _record("q1"))
        assert len((tmp_path / "summary.jsonl").read_text().splitlines()) == 2

        rebuild_summaries(tmp_path, "run-x")

        assert len((tmp_path / "summary.jsonl").read_text().splitlines()) == 1

    def test_empty_directory_produces_empty_summary_files(
        self, tmp_path: Path
    ) -> None:
        rebuild_summaries(tmp_path, "run-empty")
        assert (tmp_path / "summary.jsonl").read_text() == ""
        md = (tmp_path / "summary.md").read_text()
        assert "run-empty" in md
        assert "**Queries**: 0" in md


class TestCheckOutputDir:
    def test_missing_directory_is_fine(self, tmp_path: Path) -> None:
        assert _check_output_dir(tmp_path / "new", resume=False) is None

    def test_empty_directory_is_fine(self, tmp_path: Path) -> None:
        assert _check_output_dir(tmp_path, resume=False) is None

    def test_populated_directory_is_refused(self, tmp_path: Path) -> None:
        # P2 mutation check: without this, a repair run truncates a
        # previous campaign's summary.jsonl and overwrites its records.
        persist_record(tmp_path, _record("q1"))
        problem = _check_output_dir(tmp_path, resume=False)
        assert problem is not None
        assert "--resume" in problem

    def test_resume_bypasses_the_refusal(self, tmp_path: Path) -> None:
        persist_record(tmp_path, _record("q1"))
        assert _check_output_dir(tmp_path, resume=True) is None

    def test_non_directory_path_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "file"
        path.write_text("x")
        problem = _check_output_dir(path, resume=False)
        assert problem is not None
        assert "not a directory" in problem


# ---------------------------------------------------------------------------
# Exit codes + signal handling
# ---------------------------------------------------------------------------


class TestExitCode:
    def test_all_succeeded(self) -> None:
        assert (
            _exit_code(
                attempted=3, errored=0, interrupted=False, budget_stopped=False
            )
            == EXIT_OK
        )

    def test_partial_failure(self) -> None:
        # P2 mutation check: `make eval` used to return 0 here.
        assert (
            _exit_code(
                attempted=3, errored=1, interrupted=False, budget_stopped=False
            )
            == EXIT_PARTIAL_FAILURE
        )

    def test_all_failed_gets_its_own_code(self) -> None:
        assert (
            _exit_code(
                attempted=3, errored=3, interrupted=False, budget_stopped=False
            )
            == EXIT_ALL_FAILED
        )

    def test_budget_stop_outranks_query_outcome(self) -> None:
        assert (
            _exit_code(
                attempted=2, errored=0, interrupted=False, budget_stopped=True
            )
            == EXIT_BUDGET_STOP
        )

    def test_interrupt_outranks_everything(self) -> None:
        assert (
            _exit_code(
                attempted=2, errored=2, interrupted=True, budget_stopped=True
            )
            == EXIT_INTERRUPTED
        )

    def test_nothing_attempted_is_ok(self) -> None:
        assert (
            _exit_code(
                attempted=0, errored=0, interrupted=False, budget_stopped=False
            )
            == EXIT_OK
        )

    def test_codes_are_distinct(self) -> None:
        codes = [
            EXIT_OK,
            EXIT_CONFIG,
            EXIT_USAGE,
            EXIT_PARTIAL_FAILURE,
            EXIT_ALL_FAILED,
            EXIT_BUDGET_STOP,
            EXIT_INTERRUPTED,
        ]
        assert len(set(codes)) == len(codes)


class TestInterruptHandler:
    def test_sigterm_raises_keyboard_interrupt_and_restores(self) -> None:
        # P0/P1 mutation check: SIGTERM's default disposition kills the
        # process without unwinding, so no `finally` runs and nothing
        # is flushed. `docker stop` and an Actions cancellation both
        # send it.
        original = signal.getsignal(signal.SIGTERM)
        restore = _install_interrupt_handler()
        try:
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            with pytest.raises(KeyboardInterrupt):
                handler(signal.SIGTERM, None)
        finally:
            restore()
        assert signal.getsignal(signal.SIGTERM) is original


# ---------------------------------------------------------------------------
# main() — campaign behaviour
# ---------------------------------------------------------------------------


@pytest.fixture
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def _three_ids() -> list[str]:
    return [q["query_id"] for q in BENCHMARK_QUERIES[:3]]


def _fake_runs(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: dict[str, dict[str, Any]],
    *,
    seen: list[str] | None = None,
) -> None:
    """Replace `_run_and_score` with a canned per-query outcome table."""

    def _fake(benchmark_query: Any, *, repeat: int = 1) -> dict[str, Any]:
        qid = benchmark_query["query_id"]
        if seen is not None:
            seen.append(qid)
        # ADR 0071: the runner asks for a repeat index and keys the
        # record on it, so the double answers in the same shape.
        record = dict(outcomes[qid])
        record.setdefault("record_id", runner_module.research_record_id(qid, repeat))
        record.setdefault("repeat", repeat)
        return record

    monkeypatch.setattr(runner_module, "_run_and_score", _fake)


class TestMain:
    def test_missing_api_key_exits_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert main_with([], tmp_path) == EXIT_CONFIG

    @pytest.mark.usefixtures("_api_key")
    def test_all_succeed_exits_zero_and_writes_everything(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ids = _three_ids()
        _fake_runs(monkeypatch, {qid: _record(qid, cost=0.1) for qid in ids})

        code = main_with(["--queries", ",".join(ids)], tmp_path)

        assert code == EXIT_OK
        assert set(load_records(tmp_path)) == set(ids)
        assert (tmp_path / "summary.md").is_file()

    @pytest.mark.usefixtures("_api_key")
    def test_one_error_exits_partial_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ids = _three_ids()
        outcomes = {qid: _record(qid) for qid in ids}
        outcomes[ids[1]] = _record(ids[1], err="APIError: overloaded")
        _fake_runs(monkeypatch, outcomes)

        code = main_with(["--queries", ",".join(ids)], tmp_path)

        assert code == EXIT_PARTIAL_FAILURE
        out = capsys.readouterr().out
        assert "2/3 succeeded, 1 errored" in out

    @pytest.mark.usefixtures("_api_key")
    def test_closing_line_names_partially_scored_queries(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # A judge failure keeps the run and the clean exit code, so the
        # closing line is the only place the operator learns the night
        # has a hole in it without opening summary.md.
        ids = _three_ids()
        outcomes = {qid: _record(qid) for qid in ids}
        outcomes[ids[1]]["metrics_error"] = "faithfulness: RuntimeError: 529"
        _fake_runs(monkeypatch, outcomes)

        code = main_with(["--queries", ",".join(ids)], tmp_path)

        assert code == EXIT_OK
        assert "3/3 succeeded, 0 errored, 1 partially scored" in capsys.readouterr().out

    @pytest.mark.usefixtures("_api_key")
    def test_all_error_exits_all_failed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ids = _three_ids()
        _fake_runs(
            monkeypatch, {qid: _record(qid, err="boom") for qid in ids}
        )
        assert main_with(["--queries", ",".join(ids)], tmp_path) == EXIT_ALL_FAILED

    @pytest.mark.usefixtures("_api_key")
    def test_records_survive_a_mid_batch_kill(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # THE P0/P1 crash-safety check. Query 2 raises `EvalInterrupted`
        # (what a SIGTERM becomes); query 1's completed record and query
        # 2's partial record must both be on disk, and query 3 must not
        # have been attempted.
        ids = _three_ids()
        seen: list[str] = []
        partial = _record(ids[1], err="Interrupted: KeyboardInterrupt", cost=0.4)

        def _fake(benchmark_query: Any, *, repeat: int = 1) -> dict[str, Any]:
            qid = benchmark_query["query_id"]
            seen.append(qid)
            if qid == ids[1]:
                raise EvalInterrupted(partial)
            return _record(qid, cost=0.2)

        monkeypatch.setattr(runner_module, "_run_and_score", _fake)

        code = main_with(["--queries", ",".join(ids)], tmp_path)

        assert code == EXIT_INTERRUPTED
        assert seen == ids[:2]
        on_disk = load_records(tmp_path)
        assert set(on_disk) == {ids[0], ids[1]}
        assert on_disk[ids[1]]["error"].startswith("Interrupted")
        # The end-of-run rebuild still ran, from the `finally`.
        assert (tmp_path / "summary.md").is_file()

    @pytest.mark.usefixtures("_api_key")
    def test_bare_keyboard_interrupt_still_flushes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ids = _three_ids()

        def _fake(benchmark_query: Any, *, repeat: int = 1) -> dict[str, Any]:
            if benchmark_query["query_id"] == ids[1]:
                raise KeyboardInterrupt("signal 15")
            return _record(benchmark_query["query_id"])

        monkeypatch.setattr(runner_module, "_run_and_score", _fake)

        code = main_with(["--queries", ",".join(ids)], tmp_path)

        assert code == EXIT_INTERRUPTED
        assert set(load_records(tmp_path)) == {ids[0]}

    @pytest.mark.usefixtures("_api_key")
    def test_resume_skips_completed_queries(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # P0/P1 mutation check for `--resume`: without it a re-entered
        # campaign re-pays for every query it already ran.
        ids = _three_ids()
        persist_record(tmp_path, _record(ids[0], cost=0.3))
        seen: list[str] = []
        _fake_runs(
            monkeypatch,
            {qid: _record(qid, cost=0.1) for qid in ids},
            seen=seen,
        )

        code = main_with(["--queries", ",".join(ids), "--resume"], tmp_path)

        assert code == EXIT_OK
        assert seen == ids[1:]
        # The final summary covers the whole set, reused record included.
        assert set(load_records(tmp_path)) == set(ids)
        lines = (tmp_path / "summary.jsonl").read_text().splitlines()
        assert len(lines) == 3

    @pytest.mark.usefixtures("_api_key")
    def test_non_empty_output_dir_without_resume_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # P2 mutation check: this used to truncate summary.jsonl and
        # leave the previous campaign's other records stranded.
        ids = _three_ids()
        persist_record(tmp_path, _record(ids[0]))
        before = (tmp_path / "summary.jsonl").read_text()
        seen: list[str] = []
        _fake_runs(monkeypatch, {qid: _record(qid) for qid in ids}, seen=seen)

        code = main_with(["--queries", ",".join(ids)], tmp_path)

        assert code == EXIT_USAGE
        assert seen == []  # not a single dollar spent
        assert (tmp_path / "summary.jsonl").read_text() == before
        assert "--resume" in capsys.readouterr().err

    @pytest.mark.usefixtures("_api_key")
    def test_budget_ceiling_stops_the_campaign(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # The batch budget: two queries at $0.60 trip a $1.00 ceiling,
        # the third is never run, and the exit code says why.
        ids = _three_ids()
        seen: list[str] = []
        _fake_runs(
            monkeypatch,
            {qid: _record(qid, cost=0.6) for qid in ids},
            seen=seen,
        )

        code = main_with(
            ["--queries", ",".join(ids), "--max-budget-usd", "1.0"], tmp_path
        )

        assert code == EXIT_BUDGET_STOP
        assert seen == ids[:2]
        out = capsys.readouterr().out
        assert "Budget ceiling $1.00 reached" in out
        # "runs", not "queries": the campaign's unit became (query,
        # repeat) with ADR 0071's `--repeats`.
        assert "1 runs not made" in out
        assert set(load_records(tmp_path)) == set(ids[:2])

    @pytest.mark.usefixtures("_api_key")
    def test_budget_counts_spend_reused_from_a_resumed_campaign(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The ceiling is a campaign ceiling, not a per-attempt one: a
        # resumed run that already burned $0.90 gets one more query.
        ids = _three_ids()
        persist_record(tmp_path, _record(ids[0], cost=0.9))
        seen: list[str] = []
        _fake_runs(
            monkeypatch,
            {qid: _record(qid, cost=0.2) for qid in ids},
            seen=seen,
        )

        code = main_with(
            ["--queries", ",".join(ids), "--resume", "--max-budget-usd", "1.0"],
            tmp_path,
        )

        assert code == EXIT_BUDGET_STOP
        assert seen == [ids[1]]

    @pytest.mark.usefixtures("_api_key")
    def test_no_budget_flag_runs_everything(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ids = _three_ids()
        seen: list[str] = []
        _fake_runs(
            monkeypatch,
            {qid: _record(qid, cost=99.0) for qid in ids},
            seen=seen,
        )
        assert main_with(["--queries", ",".join(ids)], tmp_path) == EXIT_OK
        assert seen == ids


class TestRepeats:
    """ADR 0071: the research lane gained `--repeats`.

    `REPEATS_FOR_CONFIDENCE = 3` was advertised in code while this lane
    had no way to run a repeat at all, so three repeats of a query cost
    triple on the learning lane and were impossible here.
    """

    def test_the_first_repeat_keeps_the_bare_query_id(self) -> None:
        # Zero churn at the default: filenames, summary rows and resume
        # keys are what they were before the flag existed.
        assert runner_module.research_record_id("q1", 1) == "q1"
        assert runner_module.research_record_id("q1", 2) == "q1.r2"

    def test_the_split_is_the_inverse(self) -> None:
        assert runner_module._split_research_record_id("q1") == ("q1", 1)
        assert runner_module._split_research_record_id("q1.r3") == ("q1", 3)
        # An id that does not parse is repeat 1 rather than an error: a
        # rebuild must not fail on a record it did not write.
        assert runner_module._split_research_record_id("odd.rx") == ("odd.rx", 1)

    def test_records_sort_in_benchmark_then_repeat_order(self) -> None:
        first, second = (q["query_id"] for q in BENCHMARK_QUERIES[:2])
        ordered = sorted(
            [f"{second}.r2", first, f"{first}.r10", f"{first}.r2", second],
            key=_benchmark_order,
        )
        assert ordered == [first, f"{first}.r2", f"{first}.r10", second, f"{second}.r2"]

    @pytest.mark.usefixtures("_api_key")
    def test_three_repeats_write_three_records_per_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ids = _three_ids()[:2]
        _fake_runs(monkeypatch, {qid: _record(qid, cost=0.01) for qid in ids})

        code = main_with(["--queries", ",".join(ids), "--repeats", "3"], tmp_path)

        assert code == EXIT_OK
        on_disk = load_records(tmp_path)
        assert set(on_disk) == {
            runner_module.research_record_id(qid, repeat)
            for qid in ids
            for repeat in (1, 2, 3)
        }
        # Every record still names its *query*, which is what the
        # regression differ groups on to aggregate repeats.
        assert {r["query_id"] for r in on_disk.values()} == set(ids)
        assert sorted(r["repeat"] for r in on_disk.values()) == [1, 1, 2, 2, 3, 3]

    @pytest.mark.usefixtures("_api_key")
    def test_repeats_run_query_major_so_a_stopped_campaign_covers_the_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # A truncated campaign that covered the whole benchmark once is
        # worth far more than one that ran three repeats of the first
        # third.
        ids = _three_ids()
        seen: list[str] = []
        _fake_runs(
            monkeypatch, {qid: _record(qid, cost=0.01) for qid in ids}, seen=seen
        )
        main_with(["--queries", ",".join(ids), "--repeats", "2"], tmp_path)
        assert seen == ids + ids

    @pytest.mark.usefixtures("_api_key")
    def test_resume_skips_a_completed_repeat_not_the_whole_query(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ids = _three_ids()[:1]
        qid = ids[0]
        done = _record(qid, cost=0.01)
        done["record_id"] = runner_module.research_record_id(qid, 2)
        done["repeat"] = 2
        persist_record(tmp_path, done)

        seen: list[str] = []
        _fake_runs(
            monkeypatch, {qid: _record(qid, cost=0.01) for qid in ids}, seen=seen
        )
        code = main_with(
            ["--queries", qid, "--repeats", "3", "--resume"], tmp_path
        )

        assert code == EXIT_OK
        assert seen == [qid, qid]  # repeats 1 and 3; repeat 2 was reused
        assert set(load_records(tmp_path)) == {qid, f"{qid}.r2", f"{qid}.r3"}

    def test_a_record_with_no_id_at_all_is_refused(self, tmp_path: Path) -> None:
        # The fallback is for a record that predates `record_id`, not
        # for one that names nothing.
        with pytest.raises(KeyError, match="record_id"):
            persist_record(tmp_path, {"query": "no id here"})

    @pytest.mark.usefixtures("_api_key")
    def test_zero_repeats_is_a_usage_error(self, tmp_path: Path) -> None:
        assert main_with(["--repeats", "0"], tmp_path) == EXIT_USAGE

    @pytest.mark.usefixtures("_api_key")
    def test_the_campaign_prints_the_three_repeat_warning_below_the_bar(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ids = _three_ids()[:1]
        _fake_runs(monkeypatch, {qid: _record(qid) for qid in ids})
        main_with(["--queries", ids[0]], tmp_path)
        out = capsys.readouterr().out
        assert "1 repeat(s) per query" in out
        # And it lands in the artifact, not only on the terminal.
        assert "repeat(s) per query" in (tmp_path / "summary.md").read_text()

    @pytest.mark.usefixtures("_api_key")
    def test_a_legacy_record_without_a_record_id_still_resumes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The reason `CampaignShape` carries `legacy_id_field`: a
        # campaign started before ADR 0071 must not be re-paid for.
        ids = _three_ids()[:1]
        legacy = _record(ids[0], cost=0.01)
        legacy.pop("record_id", None)
        legacy.pop("repeat", None)
        persist_record(tmp_path, legacy)
        assert (tmp_path / "queries" / f"{ids[0]}.json").is_file()

        seen: list[str] = []
        _fake_runs(
            monkeypatch, {qid: _record(qid) for qid in ids}, seen=seen
        )
        assert main_with(["--queries", ids[0], "--resume"], tmp_path) == EXIT_OK
        assert seen == []


def main_with(argv: list[str], output_dir: Path) -> int:
    """`main()` with `--output-dir` appended — a readability shim."""
    return runner_module.main([*argv, "--output-dir", str(output_dir)])


class TestClaimOutcomes:
    """`runner._claim_outcomes` — WO-C1's addition to the funded lane.

    The deterministic groundedness check is run a second time here
    rather than read off `_compute_metrics`, because that path projects
    the result down to a rate and drops the claim list. The second call
    costs microseconds, makes no network or model call, and leaves every
    published *score* byte-identical — which matters, since changing one
    would rebaseline every campaign ever run.
    """

    def test_it_projects_the_decided_claims(self) -> None:
        state: Any = {
            "draft_report": "A briefing citing arXiv:2311.09000.",
            "papers": [
                {
                    "id": "http://arxiv.org/abs/2311.09000",
                    "title": "A Survey",
                    "authors": ["Ziwei Ji"],
                    "abstract": "x",
                    "url": "http://arxiv.org/abs/2311.09000",
                    "pdf_url": "",
                }
            ],
            "citations": [],
        }
        outcomes = _claim_outcomes(state)
        assert outcomes == {
            claim_id: True for claim_id in (outcomes or {})
        }
        assert len(outcomes or {}) == 1

    def test_a_scorer_failure_reports_none_rather_than_an_empty_map(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """"Not computed" and "computed and empty" are different facts,
        and a paired comparison must not read the first as the second."""
        import src.eval.runner as runner_module

        def _boom(*_a: Any, **_k: Any) -> Any:
            raise ValueError("scorer broke")

        monkeypatch.setattr(runner_module, "measure_groundedness", _boom)
        assert _claim_outcomes({}) is None  # type: ignore[arg-type]
