"""Unit tests for the eval runner.

Pure helpers are tested directly. `_run_and_score` is exercised with
`build_workflow` monkeypatched (fake compiled app returns a canned
state), and metric functions monkeypatched to canned results — so no
LLM, no arXiv, no PyMuPDF, no model loading.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from src.eval import runner as runner_module
from src.eval.benchmark_queries import BENCHMARK_QUERIES
from src.eval.runner import (
    _fmt,
    _get_score,
    _initial_state,
    _mean,
    _run_and_score,
    _select_queries,
    _serialize_state,
    _summary_line,
    _summary_markdown,
    _write_output,
)
from src.graph.state import ResearchState


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


class TestFmt:
    def test_none_dashes(self) -> None:
        assert _fmt(None) == "-"

    def test_float_two_decimals(self) -> None:
        assert _fmt(0.4245) == "0.42"

    def test_int_stringified(self) -> None:
        assert _fmt(3) == "3"

    def test_str_passthrough(self) -> None:
        assert _fmt("hello") == "hello"


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


class TestSummaryLine:
    def test_extracts_scores_state_and_cost_fields(self) -> None:
        record = {
            "query_id": "q1",
            "elapsed_sec": 12.5,
            "error": None,
            "metrics": {
                "citation_accuracy": {"score": 0.8},
                "completeness": {"score": 0.6},
                "faithfulness": {"score": 0.7},
                "retrieval_recall": {"score": 0.85},
            },
            "state": {"quality_score": 0.75, "iteration": 2},
            "costs": {"total_cost_usd": 0.0421, "call_count": 33},
        }
        line = _summary_line(record)
        assert line == {
            "query_id": "q1",
            "elapsed_sec": 12.5,
            "error": None,
            "citation_accuracy": 0.8,
            "completeness": 0.6,
            "faithfulness": 0.7,
            "retrieval_recall": 0.85,
            "critic_score": 0.75,
            "iterations": 2,
            "cost_usd": 0.0421,
            "llm_calls": 33,
        }

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


# ---------------------------------------------------------------------------
# _run_and_score integration (with mocked workflow + metrics)
# ---------------------------------------------------------------------------


class _FakeApp:
    """Stand-in for the compiled LangGraph app used in tests."""

    def __init__(self, state: ResearchState) -> None:
        self._state = state

    def invoke(self, _initial: ResearchState, config: Any = None) -> ResearchState:
        return self._state


def _finished_state() -> ResearchState:
    """A state that looks like a completed workflow run."""
    return {
        "query": "seed",
        "sub_questions": ["sq1"],
        "search_queries": ["sq1 kw"],
        "papers": [],
        "paper_analyses": [],
        "draft_report": "A report body [Smith, 2023].",
        "citations": [],
        "critique": "ok",
        "quality_score": 0.8,
        "revision_needed": False,
        "revision_target": "",
        "iteration": 1,
        "messages": [],
    }


class TestRunAndScoreSuccess:
    def test_populates_record_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module, "build_workflow", lambda: _FakeApp(_finished_state())
        )
        # Stub metric functions so we don't invoke the LLM.
        monkeypatch.setattr(
            runner_module,
            "measure_citation_accuracy",
            lambda *_: {"score": 0.9, "total_citations": 1, "resolved": 1, "unresolved": []},
        )
        monkeypatch.setattr(
            runner_module,
            "measure_completeness",
            lambda *_: {"score": 0.6, "total_topics": 2, "covered_topics": 1, "coverage": []},
        )
        monkeypatch.setattr(
            runner_module,
            "measure_faithfulness",
            lambda *_: {
                "score": 0.7,
                "total_claims": 3,
                "supported": 2,
                "unsupported": 1,
                "source_unavailable": 0,
                "claims": [],
            },
        )
        monkeypatch.setattr(
            runner_module,
            "measure_retrieval_recall",
            lambda *_: {
                "score": 0.85,
                "total_topics": 2,
                "covered_topics": 2,
                "coverage": [],
            },
        )

        record = _run_and_score(BENCHMARK_QUERIES[0])

        assert record["error"] is None
        assert record["query_id"] == BENCHMARK_QUERIES[0]["query_id"]
        assert record["elapsed_sec"] >= 0
        assert record["state"]["draft_report"].startswith("A report body")
        # messages field stripped by _serialize_state
        assert "messages" not in record["state"]
        assert record["metrics"]["citation_accuracy"]["score"] == 0.9
        assert record["metrics"]["completeness"]["score"] == 0.6
        assert record["metrics"]["faithfulness"]["score"] == 0.7
        assert record["metrics"]["retrieval_recall"]["score"] == 0.85


class TestRunAndScoreError:
    def test_workflow_exception_captured_on_record(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom() -> None:
            raise RuntimeError("no connectivity")

        monkeypatch.setattr(runner_module, "build_workflow", _boom)

        record = _run_and_score(BENCHMARK_QUERIES[0])

        assert record["error"] is not None
        assert "RuntimeError" in record["error"]
        assert "no connectivity" in record["error"]
        assert record["state"] is None
        assert record["metrics"] is None
        assert "traceback" in record


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


class TestWriteOutput:
    def _fake_record(self, qid: str, err: str | None = None) -> dict[str, Any]:
        if err:
            return {
                "query_id": qid,
                "query": "q",
                "domain": "d",
                "elapsed_sec": 0.1,
                "state": None,
                "metrics": None,
                "error": err,
            }
        return {
            "query_id": qid,
            "query": "q",
            "domain": "d",
            "elapsed_sec": 1.5,
            "state": {"quality_score": 0.7, "iteration": 1},
            "metrics": {
                "citation_accuracy": {"score": 1.0},
                "completeness": {"score": 0.5},
                "faithfulness": {"score": 0.8},
            },
            "error": None,
        }

    def test_writes_per_query_json_summary_jsonl_and_markdown(
        self, tmp_path: Path
    ) -> None:
        records = [self._fake_record("q1"), self._fake_record("q2", err="boom")]

        _write_output(tmp_path, records, "run-x")

        # Per-query JSON files
        q1_path = tmp_path / "queries" / "q1.json"
        q2_path = tmp_path / "queries" / "q2.json"
        assert q1_path.is_file()
        assert q2_path.is_file()
        assert json.loads(q1_path.read_text())["query_id"] == "q1"
        assert json.loads(q2_path.read_text())["error"] == "boom"

        # summary.jsonl — one line per query
        summary_jsonl = (tmp_path / "summary.jsonl").read_text()
        lines = [line for line in summary_jsonl.splitlines() if line]
        assert len(lines) == 2
        parsed = [json.loads(line) for line in lines]
        assert {p["query_id"] for p in parsed} == {"q1", "q2"}

        # summary.md — contains the run id + both rows
        md = (tmp_path / "summary.md").read_text()
        assert "run-x" in md
        assert "| q1 |" in md
        assert "| q2 |" in md

    def test_empty_records_produces_empty_summary_files(
        self, tmp_path: Path
    ) -> None:
        _write_output(tmp_path, [], "run-empty")
        assert (tmp_path / "summary.jsonl").read_text() == ""
        # Markdown still has a header, but no query rows.
        md = (tmp_path / "summary.md").read_text()
        assert "run-empty" in md
        assert "**Queries**: 0" in md
