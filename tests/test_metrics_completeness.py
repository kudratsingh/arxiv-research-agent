"""Unit tests for the completeness metric.

The prompt builder and the aggregator are pure — tested directly. The
full `measure_completeness` path is exercised once with `call_llm_json`
monkeypatched (no real Claude call, no network).
"""

from typing import Any

import pytest

from src.eval import metrics as metrics_module
from src.eval.metrics import (
    CompletenessResult,
    TopicCoverage,
    _aggregate_coverage,
    _build_completeness_prompt,
    measure_completeness,
)


class TestBuildCompletenessPrompt:
    def test_includes_report_verbatim(self) -> None:
        prompt = _build_completeness_prompt("REPORT BODY", ["t1"])
        assert "REPORT BODY" in prompt

    def test_lists_topics_as_bullets_in_order(self) -> None:
        prompt = _build_completeness_prompt("r", ["alpha", "beta", "gamma"])
        idx_alpha = prompt.index("- alpha")
        idx_beta = prompt.index("- beta")
        idx_gamma = prompt.index("- gamma")
        assert idx_alpha < idx_beta < idx_gamma

    def test_report_precedes_topics(self) -> None:
        prompt = _build_completeness_prompt("body", ["topic-x"])
        assert prompt.index("body") < prompt.index("topic-x")


class TestAggregateCoverage:
    def test_all_covered_scores_1(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": True, "reason": "clear"},
                {"topic": "b", "covered": True, "reason": "clear"},
            ]
        }
        result = _aggregate_coverage(parsed, ["a", "b"])
        assert result["score"] == 1.0
        assert result["covered_topics"] == 2
        assert result["total_topics"] == 2

    def test_none_covered_scores_0(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": False, "reason": "missing"},
                {"topic": "b", "covered": False, "reason": "missing"},
            ]
        }
        result = _aggregate_coverage(parsed, ["a", "b"])
        assert result["score"] == 0.0
        assert result["covered_topics"] == 0

    def test_partial_coverage_correct_ratio(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": True, "reason": ""},
                {"topic": "b", "covered": False, "reason": ""},
                {"topic": "c", "covered": True, "reason": ""},
                {"topic": "d", "covered": False, "reason": ""},
            ]
        }
        result = _aggregate_coverage(parsed, ["a", "b", "c", "d"])
        assert result["score"] == 0.5
        assert result["covered_topics"] == 2
        assert result["total_topics"] == 4

    def test_missing_topic_from_judge_becomes_uncovered(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": True, "reason": "yes"},
                # topic "b" omitted by the judge
            ]
        }
        result = _aggregate_coverage(parsed, ["a", "b"])
        assert result["covered_topics"] == 1
        # Preserve request order.
        assert [c["topic"] for c in result["coverage"]] == ["a", "b"]
        assert result["coverage"][1]["covered"] is False
        assert "did not return" in result["coverage"][1]["reason"]

    def test_extra_topics_from_judge_are_ignored(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": True, "reason": ""},
                {"topic": "hallucinated-topic", "covered": True, "reason": ""},
            ]
        }
        result = _aggregate_coverage(parsed, ["a"])
        assert result["total_topics"] == 1
        assert result["covered_topics"] == 1
        assert [c["topic"] for c in result["coverage"]] == ["a"]

    def test_duplicate_topic_in_judge_response_keeps_first(self) -> None:
        parsed = {
            "coverage": [
                {"topic": "a", "covered": True, "reason": "first"},
                {"topic": "a", "covered": False, "reason": "second"},
            ]
        }
        result = _aggregate_coverage(parsed, ["a"])
        assert result["coverage"][0]["reason"] == "first"
        assert result["coverage"][0]["covered"] is True

    def test_malformed_coverage_field_treated_as_all_uncovered(self) -> None:
        parsed: dict[str, Any] = {"coverage": "not a list"}
        result = _aggregate_coverage(parsed, ["a", "b"])
        assert result["score"] == 0.0
        assert all(c["covered"] is False for c in result["coverage"])

    def test_missing_coverage_field_treated_as_all_uncovered(self) -> None:
        result = _aggregate_coverage({}, ["a", "b"])
        assert result["score"] == 0.0
        assert result["total_topics"] == 2

    def test_score_of_1_when_no_topics_requested(self) -> None:
        result = _aggregate_coverage({"coverage": []}, [])
        assert result["score"] == 1.0
        assert result["total_topics"] == 0
        assert result["coverage"] == []


class TestMeasureCompleteness:
    def test_empty_topics_short_circuits_without_llm_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = {"count": 0}

        def _should_not_be_called(**_: Any) -> dict[str, Any]:
            called["count"] += 1
            return {}

        monkeypatch.setattr(
            metrics_module, "call_llm_json", _should_not_be_called
        )

        result = measure_completeness("report body", [])
        assert result["score"] == 1.0
        assert result["total_topics"] == 0
        assert called["count"] == 0

    def test_end_to_end_with_stubbed_judge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_judge(
            *, prompt: str, system_prompt: str, max_tokens: int
        ) -> dict[str, Any]:
            captured["prompt"] = prompt
            captured["system_prompt"] = system_prompt
            captured["max_tokens"] = max_tokens
            return {
                "coverage": [
                    {"topic": "alpha", "covered": True, "reason": "ok"},
                    {"topic": "beta", "covered": False, "reason": "missing"},
                ]
            }

        monkeypatch.setattr(metrics_module, "call_llm_json", fake_judge)

        result = measure_completeness(
            "some report body", ["alpha", "beta"]
        )

        assert result["score"] == 0.5
        assert result["covered_topics"] == 1
        assert result["total_topics"] == 2
        # Sanity-check the prompt contains what we expect.
        assert "some report body" in captured["prompt"]
        assert "- alpha" in captured["prompt"]
        assert "- beta" in captured["prompt"]
        assert "strict" in captured["system_prompt"].lower()


class TestReturnedTypeShape:
    def test_completeness_result_keys(self) -> None:
        result = measure_completeness("", [])
        assert set(CompletenessResult.__required_keys__) == set(result.keys())

    def test_topic_coverage_keys(self) -> None:
        # Instantiate via _aggregate_coverage since it's the boundary that
        # produces TopicCoverage dicts.
        result = _aggregate_coverage(
            {"coverage": [{"topic": "a", "covered": True, "reason": "ok"}]},
            ["a"],
        )
        entry = result["coverage"][0]
        assert set(TopicCoverage.__required_keys__) == set(entry.keys())
