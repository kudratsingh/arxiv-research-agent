"""Unit tests for the completeness metric.

The prompt builder and the aggregator are pure — tested directly. The
full `measure_completeness` path is exercised once with `call_llm_json`
monkeypatched (no real Claude call, no network).
"""

from typing import Any

import pytest

from src.config import Settings
from src.eval import metrics as metrics_module
from src.eval import provenance as provenance_module
from src.eval.metrics import (
    NO_EXPECTED_TOPICS,
    CompletenessResult,
    TopicCoverage,
    _aggregate_coverage,
    _build_completeness_prompt,
    measure_completeness,
)

pytestmark = pytest.mark.unit


class TestBuildCompletenessPrompt:
    """What the prompt carries, and in what order."""

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
    """How coverage aggregates, including every malformed judge reply."""

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

    def test_no_requested_topics_scores_none_with_a_reason(self) -> None:
        # ADR 0100: an empty denominator is not a perfect score. This
        # used to return 1.0, which is the one answer indistinguishable
        # from "this run covered everything it was asked to".
        result = _aggregate_coverage({"coverage": []}, [])
        assert result["score"] is None
        assert result["reason"] == NO_EXPECTED_TOPICS
        assert result["total_topics"] == 0
        assert result["coverage"] == []

    def test_a_scored_result_carries_no_reason(self) -> None:
        result = _aggregate_coverage(
            {"coverage": [{"topic": "a", "covered": True, "reason": "ok"}]}, ["a"]
        )
        assert result["score"] == 1.0
        assert result["reason"] is None

    def test_a_tuple_coverage_field_is_read_like_a_list(self) -> None:
        # What `model_dump()` returns on the structured-output path. A
        # list-only check would have read every structured response as
        # an empty one and scored 0.0 across the board.
        parsed: dict[str, Any] = {
            "coverage": ({"topic": "a", "covered": True, "reason": "ok"},)
        }
        assert _aggregate_coverage(parsed, ["a"])["score"] == 1.0


class TestMeasureCompleteness:
    """The whole path, and the short circuit that skips the judge."""

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
        assert result["score"] is None
        assert result["reason"] == NO_EXPECTED_TOPICS
        assert result["total_topics"] == 0
        assert result["judge"] is None
        assert called["count"] == 0

    def test_end_to_end_with_stubbed_judge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_judge(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
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

    def test_the_judge_call_carries_its_schema_and_its_own_temperature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EL-11: judges stop sampling at the workflow's temperature."""
        seen: dict[str, Any] = {}

        def fake_judge(**kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return {"coverage": [{"topic": "a", "covered": True, "reason": "ok"}]}

        monkeypatch.setattr(metrics_module, "call_llm_json", fake_judge)
        monkeypatch.setattr(
            metrics_module,
            "settings",
            Settings(llm_temperature=0.7, eval_judge_temperature=0.0),
        )

        result = measure_completeness("report", ["a"])

        assert seen["schema"] is metrics_module.CompletenessJudgeOutput
        assert seen["temperature"] == 0.0
        assert result["judge"] is not None
        assert result["judge"]["schema"] == "CompletenessJudgeOutput"


class TestReturnedTypeShape:
    """The result's keys are exactly the ones its type declares."""

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


class TestTheJudgeIsPinned:
    """ADR 0070: the judge must not follow the product model.

    Before this, `measure_completeness` passed no `model_name`, so
    `src/llm.py` fell through to `settings.anthropic_model` — upgrading
    the product silently changed the grader.
    """

    def test_the_judge_call_names_the_pinned_eval_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def fake_judge(**kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return {"coverage": [{"topic": "alpha", "covered": True, "reason": "ok"}]}

        monkeypatch.setattr(metrics_module, "call_llm_json", fake_judge)
        monkeypatch.setattr(
            provenance_module,
            "settings",
            Settings(anthropic_model="product-v2", eval_judge_model="judge-v1"),
        )

        measure_completeness("report", ["alpha"])

        assert seen["model_name"] == "judge-v1"
        assert seen["model_name"] != "product-v2"

    def test_the_judge_model_is_read_per_call_not_at_import(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        def fake_judge(**kwargs: Any) -> dict[str, Any]:
            seen.append(str(kwargs["model_name"]))
            return {"coverage": [{"topic": "alpha", "covered": True, "reason": "ok"}]}

        monkeypatch.setattr(metrics_module, "call_llm_json", fake_judge)
        for model in ("judge-a", "judge-b"):
            monkeypatch.setattr(
                provenance_module, "settings", Settings(eval_judge_model=model)
            )
            measure_completeness("report", ["alpha"])
        assert seen == ["judge-a", "judge-b"]
