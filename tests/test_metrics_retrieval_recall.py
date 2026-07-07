"""Unit tests for the retrieval recall metric.

Pure logic tests + one end-to-end test with `call_llm_json`
monkeypatched. No network, no model load.
"""

from typing import Any

import pytest

from src.eval import metrics as metrics_module
from src.eval.metrics import (
    RetrievalRecallResult,
    TopicRetrieval,
    _aggregate_retrieval,
    _build_retrieval_recall_prompt,
    measure_retrieval_recall,
)
from src.graph.state import PaperMetadata


def _mk_paper(
    paper_id: str, title: str, abstract: str = "abstract"
) -> PaperMetadata:
    return PaperMetadata(
        id=paper_id,
        title=title,
        authors=["A"],
        abstract=abstract,
        url=paper_id,
        pdf_url=paper_id,
    )


class TestBuildPrompt:
    def test_papers_numbered_from_zero(self) -> None:
        papers = [
            _mk_paper("p1", "Alpha paper", "alpha abstract"),
            _mk_paper("p2", "Beta paper", "beta abstract"),
        ]
        prompt = _build_retrieval_recall_prompt(papers, ["topic-x"])
        assert "[0] Alpha paper" in prompt
        assert "[1] Beta paper" in prompt
        assert "alpha abstract" in prompt

    def test_topics_bulletized(self) -> None:
        papers = [_mk_paper("p1", "t")]
        prompt = _build_retrieval_recall_prompt(papers, ["alpha", "beta"])
        assert "- alpha" in prompt
        assert "- beta" in prompt


class TestAggregateRetrieval:
    def test_all_covered(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": True, "paper_ids": [0, 1], "reason": ""},
                {"topic": "b", "covered": True, "paper_ids": [2], "reason": ""},
            ]
        }
        result = _aggregate_retrieval(parsed, ["a", "b"], n_papers=3)
        assert result["score"] == 1.0
        assert result["covered_topics"] == 2

    def test_partial_coverage(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": True, "paper_ids": [0], "reason": ""},
                {"topic": "b", "covered": False, "paper_ids": [], "reason": ""},
            ]
        }
        result = _aggregate_retrieval(parsed, ["a", "b"], n_papers=3)
        assert result["score"] == 0.5

    def test_missing_topic_from_judge_treated_as_uncovered(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": True, "paper_ids": [0], "reason": ""},
            ]
        }
        result = _aggregate_retrieval(parsed, ["a", "b"], n_papers=1)
        assert result["covered_topics"] == 1
        assert result["coverage"][1]["covered"] is False
        assert "did not return" in result["coverage"][1]["reason"]

    def test_out_of_range_paper_ids_are_dropped(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": True, "paper_ids": [0, 99, -1], "reason": ""},
            ]
        }
        result = _aggregate_retrieval(parsed, ["a"], n_papers=3)
        assert result["coverage"][0]["paper_ids"] == [0]

    def test_non_int_paper_ids_are_dropped(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": True, "paper_ids": [0, "bad", None], "reason": ""},
            ]
        }
        result = _aggregate_retrieval(parsed, ["a"], n_papers=3)
        assert result["coverage"][0]["paper_ids"] == [0]

    def test_malformed_coverage_field_treated_as_all_uncovered(self) -> None:
        parsed: dict[str, Any] = {"coverage": "not a list"}
        result = _aggregate_retrieval(parsed, ["a", "b"], n_papers=1)
        assert result["score"] == 0.0
        assert all(c["covered"] is False for c in result["coverage"])

    def test_zero_topics_yields_score_1(self) -> None:
        result = _aggregate_retrieval({"coverage": []}, [], n_papers=1)
        assert result["score"] == 1.0
        assert result["total_topics"] == 0


class TestMeasureRetrievalRecall:
    def test_no_topics_short_circuits_no_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def _no(**_: Any) -> dict[str, Any]:
            calls["n"] += 1
            return {}

        monkeypatch.setattr(metrics_module, "call_llm_json", _no)
        result = measure_retrieval_recall([_mk_paper("p1", "t")], [])
        assert result["score"] == 1.0
        assert calls["n"] == 0

    def test_no_papers_returns_zero_no_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def _no(**_: Any) -> dict[str, Any]:
            calls["n"] += 1
            return {}

        monkeypatch.setattr(metrics_module, "call_llm_json", _no)
        result = measure_retrieval_recall([], ["topic-x", "topic-y"])
        assert result["score"] == 0.0
        assert result["total_topics"] == 2
        assert result["covered_topics"] == 0
        assert calls["n"] == 0
        for entry in result["coverage"]:
            assert entry["covered"] is False
            assert "No papers retrieved" in entry["reason"]

    def test_end_to_end_with_stubbed_judge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_judge(
            *, prompt: str, system_prompt: str, max_tokens: int
        ) -> dict[str, Any]:
            captured["prompt"] = prompt
            return {
                "coverage": [
                    {"topic": "alpha", "covered": True, "paper_ids": [0], "reason": "yes"},
                    {"topic": "beta", "covered": False, "paper_ids": [], "reason": "no"},
                ]
            }

        monkeypatch.setattr(metrics_module, "call_llm_json", fake_judge)

        result = measure_retrieval_recall(
            [_mk_paper("p1", "Paper A", "about alpha")],
            ["alpha", "beta"],
        )

        assert result["score"] == 0.5
        assert result["covered_topics"] == 1
        assert result["total_topics"] == 2
        assert "[0] Paper A" in captured["prompt"]


class TestReturnedTypes:
    def test_result_shape(self) -> None:
        result = measure_retrieval_recall([], [])
        assert set(RetrievalRecallResult.__required_keys__) == set(result.keys())

    def test_topic_shape(self) -> None:
        result = _aggregate_retrieval(
            {"coverage": [{"topic": "a", "covered": True, "paper_ids": [0], "reason": ""}]},
            ["a"],
            n_papers=1,
        )
        assert set(TopicRetrieval.__required_keys__) == set(result["coverage"][0].keys())
