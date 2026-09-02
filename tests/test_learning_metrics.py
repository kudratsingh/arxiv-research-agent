"""Learning metrics (WO-W09, plus WO-W10's shame-free copy judge).

Every model call is replaced with canned JSON.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.eval import learning_metrics as metrics
from src.eval.learning_fixtures import load_session_plans


def _criterion(score: float, reason: str = "fixture reason") -> dict[str, Any]:
    return {"score": score, "reason": reason}


def _plan_response(score: float) -> dict[str, Any]:
    return {
        "score": score,
        "section_ordering": _criterion(score),
        "time_budget": _criterion(score),
        "check_placement": _criterion(score),
        "downscope_honesty": _criterion(score),
        "summary": "Canned judge response.",
    }


def _shame_free_response(quotes: list[str] | None = None) -> dict[str, Any]:
    return {
        "score": 0.95,
        "respects_effort": _criterion(1.0, "No blame."),
        "avoids_deficit_framing": _criterion(0.9, "Describes the plan."),
        "offers_a_next_step": _criterion(1.0, "Names one question."),
        "offending_quotes": quotes or [],
        "summary": "Copy is descriptive rather than evaluative.",
    }


def _plans_by_variant() -> dict[str, dict[str, Any]]:
    return {plan["variant"]: plan for plan in load_session_plans()}


class TestSessionPlanCoherence:
    def test_honest_downscope_passes_and_budget_ignoring_plan_is_penalized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plans = _plans_by_variant()
        responses = iter([_plan_response(0.94), _plan_response(0.18)])
        prompts: list[str] = []

        def fake_call(**kwargs: Any) -> dict[str, Any]:
            prompts.append(str(kwargs["prompt"]))
            return next(responses)

        monkeypatch.setattr(metrics, "call_llm_json", fake_call)
        honest = metrics.measure_session_plan_coherence(plans["honest_downscope"])
        dishonest = metrics.measure_session_plan_coherence(plans["budget_ignoring"])

        assert honest["metrics_error"] is None
        assert dishonest["metrics_error"] is None
        assert honest["metric"] is not None
        assert dishonest["metric"] is not None
        assert honest["metric"]["score"] > dishonest["metric"]["score"]
        assert '"declared_minutes_today": 10' in prompts[0]
        dishonest_prompt = json.loads(prompts[1])
        assert sum(section["minutes"] for section in dishonest_prompt["plan"]["sections"]) == 30

    @pytest.mark.parametrize(
        "bad_response",
        [
            ["not", "an", "object"],
            {"score": 0.8},
            {
                **_plan_response(0.8),
                "score": 1.2,
            },
            {
                **_plan_response(0.8),
                "unexpected": True,
            },
        ],
    )
    def test_invalid_judge_shape_is_none_metric_with_error(
        self, monkeypatch: pytest.MonkeyPatch, bad_response: Any
    ) -> None:
        monkeypatch.setattr(metrics, "call_llm_json", lambda **_: bad_response)
        plan = _plans_by_variant()["honest_downscope"]
        outcome = metrics.measure_session_plan_coherence(plan)
        assert outcome["metric"] is None
        assert outcome["metrics_error"] is not None
        assert "session_plan_coherence" in outcome["metrics_error"]

    def test_call_failure_is_isolated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fail(**_: Any) -> dict[str, Any]:
            raise RuntimeError("canned timeout")

        monkeypatch.setattr(metrics, "call_llm_json", fail)
        outcome = metrics.measure_session_plan_coherence(_plans_by_variant()["honest_downscope"])
        assert outcome["metric"] is None
        assert outcome["metrics_error"] is not None
        assert "RuntimeError: canned timeout" in outcome["metrics_error"]


class TestExplainBackJudge:
    def test_grounded_gap_parses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answer = "The mask only hides padding tokens."
        response = {
            "gaps": [
                {
                    "gap_id": "mask-type-confusion",
                    "evidence_quote": "only hides padding tokens",
                    "explanation": "Confuses causal and padding masks.",
                }
            ],
            "summary": "One grounded gap.",
        }
        monkeypatch.setattr(metrics, "call_llm_json", lambda **_: response)
        outcome = metrics.measure_explain_back(answer)
        assert outcome["metrics_error"] is None
        assert outcome["metric"] is not None
        assert outcome["metric"]["gaps"][0]["gap_id"] == "mask-type-confusion"

    @pytest.mark.parametrize(
        "response,error_fragment",
        [
            ({"gaps": "none", "summary": "bad"}, "must be a list"),
            (
                {
                    "gaps": [
                        {
                            "gap_id": "invented",
                            "evidence_quote": "words learner never said",
                            "explanation": "Ungrounded.",
                        }
                    ],
                    "summary": "bad",
                },
                "not learner-authored text",
            ),
            (
                {
                    "gaps": [
                        {
                            "gap_id": "same",
                            "evidence_quote": "mask",
                            "explanation": "one",
                        },
                        {
                            "gap_id": "same",
                            "evidence_quote": "padding",
                            "explanation": "two",
                        },
                    ],
                    "summary": "bad",
                },
                "duplicates",
            ),
        ],
    )
    def test_parse_defense_never_fabricates_a_score(
        self,
        monkeypatch: pytest.MonkeyPatch,
        response: Any,
        error_fragment: str,
    ) -> None:
        monkeypatch.setattr(metrics, "call_llm_json", lambda **_: response)
        outcome = metrics.measure_explain_back("The mask hides padding.")
        assert outcome["metric"] is None
        assert outcome["metrics_error"] is not None
        assert error_fragment in outcome["metrics_error"]

    def test_empty_explain_back_is_a_failed_metric_not_a_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        def should_not_call(**_: Any) -> dict[str, Any]:
            nonlocal called
            called = True
            return {}

        monkeypatch.setattr(metrics, "call_llm_json", should_not_call)
        outcome = metrics.measure_explain_back("  ")
        assert outcome["metric"] is None
        assert "learner_explain_back" in str(outcome["metrics_error"])
        assert not called


class TestShameFreeCopyJudge:
    def test_a_valid_response_scores(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            metrics, "call_llm_json", lambda **_: _shame_free_response()
        )
        envelope = metrics.measure_shame_free_copy(["Planned 1 section."])
        assert envelope["metrics_error"] is None
        assert envelope["metric"] is not None
        assert envelope["metric"]["score"] == 0.95

    def test_a_fabricated_quote_fails_the_whole_metric(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The evidence rule: a complaint about text the copy does not
        # contain is how a rubric judge manufactures a regression.
        monkeypatch.setattr(
            metrics,
            "call_llm_json",
            lambda **_: _shame_free_response(["you have fallen behind"]),
        )
        envelope = metrics.measure_shame_free_copy(["Planned 1 section."])
        assert envelope["metric"] is None
        assert "not verbatim" in str(envelope["metrics_error"])

    def test_an_extra_key_is_refused_rather_than_scored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _shame_free_response()
        payload["confidence"] = 0.4
        monkeypatch.setattr(metrics, "call_llm_json", lambda **_: payload)
        envelope = metrics.measure_shame_free_copy(["Planned 1 section."])
        assert envelope["metric"] is None
        assert envelope["metrics_error"] is not None

    def test_a_raising_judge_becomes_a_named_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**_: Any) -> dict[str, Any]:
            raise RuntimeError("529 overloaded")

        monkeypatch.setattr(metrics, "call_llm_json", _boom)
        envelope = metrics.measure_shame_free_copy(["Planned 1 section."])
        assert envelope["metric"] is None
        assert "shame_free_copy: RuntimeError" in str(envelope["metrics_error"])

    def test_empty_copy_is_an_error_not_a_perfect_score(self) -> None:
        envelope = metrics.measure_shame_free_copy(["", "   "])
        assert envelope["metric"] is None


class TestCalibrationAgreement:
    def test_checked_in_set_has_honest_provenance_and_required_size(self) -> None:
        calibration = metrics.load_explain_back_calibration()
        assert len(calibration["cases"]) == 20
        provenance = calibration["provenance"]
        assert provenance["labeled_by"]
        assert provenance["labeled_at"] == "2026-09-01"
        assert provenance["owner_ratified"] is False
        assert provenance["ratified_by"] == ""
        assert "not real learner sessions" in provenance["source_kind"]
        assert "cannot clear Gate W1" in provenance["limitations"]

    def test_perfect_agreement_is_deterministic(self) -> None:
        calibration = metrics.load_explain_back_calibration()
        outputs = {
            case["calibration_id"]: case["expected_gap_ids"] for case in calibration["cases"]
        }
        result = metrics.compute_explain_back_agreement(calibration, outputs)
        assert result == {
            "cases": 20,
            "exact_matches": 20,
            "exact_match_rate": 1.0,
            "true_positives": 15,
            "false_positives": 0,
            "false_negatives": 0,
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
        }

    def test_partial_agreement_counts_false_positive_and_negative(self) -> None:
        calibration = metrics.load_explain_back_calibration()
        outputs = {
            case["calibration_id"]: list(case["expected_gap_ids"]) for case in calibration["cases"]
        }
        outputs["cal-002"] = []
        outputs["cal-003"] = ["invented-gap"]
        result = metrics.compute_explain_back_agreement(calibration, outputs)
        assert result["cases"] == 20
        assert result["exact_matches"] == 18
        assert result["false_negatives"] == 1
        assert result["false_positives"] == 1
        assert result["true_positives"] == 14
        assert result["f1"] == pytest.approx(14 / 15)

    def test_missing_judge_output_is_rejected(self) -> None:
        calibration = metrics.load_explain_back_calibration()
        with pytest.raises(ValueError, match="missing=.*cal-020"):
            metrics.compute_explain_back_agreement(
                calibration,
                {
                    case["calibration_id"]: case["expected_gap_ids"]
                    for case in calibration["cases"][:-1]
                },
            )


class TestDeterministicChecks:
    def test_evidence_link_check_names_every_bad_event(self) -> None:
        events = [
            {"kind": "assessment", "evidence_ref": "session:s1#turn-4"},
            {"kind": "artifact_produced", "evidence_ref": ""},
            {"kind": "session_completed"},
            {"kind": "session_completed", "evidence_ref": "  "},
        ]
        assert metrics.find_unlinked_progress_events(events) == [1, 2, 3]

    def test_shame_scan_is_case_insensitive_and_phrase_bounded(self) -> None:
        findings = metrics.find_shaming_language(
            [
                "Ten minutes is enough; we can continue tomorrow.",
                "YOU'VE FALLEN BEHIND, so you should have finished this already.",
                "The paper describes a disappointing progression in loss.",
            ]
        )
        assert [(item["text_index"], item["phrase"]) for item in findings] == [
            (1, "you've fallen behind"),
            (1, "you should have finished"),
        ]

    def test_pure_checks_and_agreement_make_no_model_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def should_not_call(**_: Any) -> dict[str, Any]:
            raise AssertionError("deterministic checks called the model")

        monkeypatch.setattr(metrics, "call_llm_json", should_not_call)
        assert metrics.find_unlinked_progress_events([]) == []
        assert metrics.find_shaming_language(["You can pick this up tomorrow."]) == []
        calibration = metrics.load_explain_back_calibration()
        outputs = {
            case["calibration_id"]: case["expected_gap_ids"] for case in calibration["cases"]
        }
        assert metrics.compute_explain_back_agreement(calibration, outputs)["f1"] == 1.0
