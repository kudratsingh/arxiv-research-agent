"""Offline metrics for guided-read sessions (WO-W09).

The two model-backed metrics in this module use one batched JSON call each and
return an explicit ``metric=None`` plus ``metrics_error`` when a judge fails or
returns an invalid shape.  A bad judge response must never become a plausible
score.  The pure checks and calibration agreement functions make no model or
network calls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypedDict

from src.eval.learning_benchmark import (
    BenchmarkPaper,
    LearningScenario,
    get_paper,
    get_scenario,
)
from src.eval.learning_fixtures import SessionPlanFixture
from src.llm import call_llm_json


class CriterionScore(TypedDict):
    """One named part of the session-plan rubric."""

    score: float
    reason: str


class SessionPlanCoherenceResult(TypedDict):
    """Validated output from the plan-coherence judge."""

    score: float
    section_ordering: CriterionScore
    time_budget: CriterionScore
    check_placement: CriterionScore
    downscope_honesty: CriterionScore
    summary: str


class ExplainBackGap(TypedDict):
    """A specific gap grounded in the learner's own words."""

    gap_id: str
    evidence_quote: str
    explanation: str


class ExplainBackResult(TypedDict):
    """Validated output from the explain-back judge."""

    gaps: list[ExplainBackGap]
    summary: str


class MetricEnvelope(TypedDict):
    """Failure-isolated metric result shared by both learning judges."""

    metric: dict[str, Any] | None
    metrics_error: str | None


class CalibrationAgreement(TypedDict):
    """Deterministic set agreement over all labeled calibration cases."""

    cases: int
    exact_matches: int
    exact_match_rate: float
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float


class ShameFinding(TypedDict):
    """Forbidden language found in tutor-facing copy."""

    phrase: str
    text_index: int
    excerpt: str


PLAN_SYSTEM_PROMPT = """\
You are a strict evaluator of a guided paper-reading session plan. Score only
the supplied plan against the supplied learner time budget and paper guidance.
Do not reward verbosity. A plan that schedules more minutes than the learner
declared, omits an explain-back check, or silently drops work must lose points.
Return JSON only with: score (0..1), section_ordering, time_budget,
check_placement, downscope_honesty (each an object with score 0..1 and reason),
and summary. Do not add keys.
"""

EXPLAIN_BACK_SYSTEM_PROMPT = """\
You are a strict evaluator of a learner's explain-back. Identify only gaps
supported by the learner's own words. Never infer mastery, intent, or a gap
from the tutor's wording. Return JSON only with gaps (a list of objects with
gap_id, evidence_quote copied from the learner, and explanation) and summary.
Use an empty gaps list when no grounded gap is present. Do not add keys.
"""

# Small, explicit vocabulary from the learning-agent honesty rule.  Matching
# is case-insensitive and phrase-bounded; callers get findings rather than an
# exception so CI can show every offending string in one run.
SHAME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (phrase, re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE))
    for phrase in (
        "you are behind",
        "you've fallen behind",
        "you have fallen behind",
        "you failed",
        "you are lazy",
        "you should have finished",
        "you only managed",
        "disappointing progress",
    )
)

CALIBRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "learning"
    / "explain_back_calibration.json"
)


def _float_01(value: Any, where: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{where} must be a number")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{where} must be between 0 and 1")
    return number


def _string(value: Any, where: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{where} must be a non-empty string")
    return value


def _exact_keys(payload: Mapping[str, Any], expected: set[str], where: str) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(f"{where} keys must be {sorted(expected)}; got {sorted(actual)}")


def _criterion(value: Any, where: str) -> CriterionScore:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be an object")
    _exact_keys(value, {"score", "reason"}, where)
    return CriterionScore(
        score=_float_01(value["score"], f"{where}.score"),
        reason=_string(value["reason"], f"{where}.reason"),
    )


def _parse_plan_result(value: Any) -> SessionPlanCoherenceResult:
    if not isinstance(value, Mapping):
        raise ValueError("plan judge response must be an object")
    keys = {
        "score",
        "section_ordering",
        "time_budget",
        "check_placement",
        "downscope_honesty",
        "summary",
    }
    _exact_keys(value, keys, "plan judge response")
    return SessionPlanCoherenceResult(
        score=_float_01(value["score"], "plan judge response.score"),
        section_ordering=_criterion(
            value["section_ordering"], "plan judge response.section_ordering"
        ),
        time_budget=_criterion(value["time_budget"], "plan judge response.time_budget"),
        check_placement=_criterion(value["check_placement"], "plan judge response.check_placement"),
        downscope_honesty=_criterion(
            value["downscope_honesty"], "plan judge response.downscope_honesty"
        ),
        summary=_string(value["summary"], "plan judge response.summary"),
    )


def _parse_explain_back_result(value: Any) -> ExplainBackResult:
    if not isinstance(value, Mapping):
        raise ValueError("explain-back judge response must be an object")
    _exact_keys(value, {"gaps", "summary"}, "explain-back judge response")
    raw_gaps = value["gaps"]
    if not isinstance(raw_gaps, list):
        raise ValueError("explain-back judge response.gaps must be a list")
    gaps: list[ExplainBackGap] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_gaps):
        where = f"explain-back judge response.gaps[{index}]"
        if not isinstance(raw, Mapping):
            raise ValueError(f"{where} must be an object")
        _exact_keys(raw, {"gap_id", "evidence_quote", "explanation"}, where)
        gap_id = _string(raw["gap_id"], f"{where}.gap_id")
        if gap_id in seen:
            raise ValueError(f"{where}.gap_id duplicates {gap_id!r}")
        seen.add(gap_id)
        gaps.append(
            ExplainBackGap(
                gap_id=gap_id,
                evidence_quote=_string(raw["evidence_quote"], f"{where}.evidence_quote"),
                explanation=_string(raw["explanation"], f"{where}.explanation"),
            )
        )
    return ExplainBackResult(
        gaps=gaps,
        summary=_string(value["summary"], "explain-back judge response.summary"),
    )


def _failure(metric_name: str, exc: Exception) -> MetricEnvelope:
    return MetricEnvelope(
        metric=None,
        metrics_error=f"{metric_name}: {type(exc).__name__}: {exc}",
    )


def _plan_prompt(
    plan: SessionPlanFixture,
    scenario: LearningScenario,
    paper: BenchmarkPaper,
) -> str:
    return json.dumps(
        {
            "declared_minutes_today": scenario["declared_minutes_today"],
            "paper_guidance": {
                "close_read_sections": paper["close_read_sections"],
                "skim_sections": paper["skim_sections"],
            },
            "plan": {
                "downscope_statement": plan["downscope_statement"],
                "sections": plan["sections"],
            },
        },
        sort_keys=True,
    )


def measure_session_plan_coherence(plan: SessionPlanFixture) -> MetricEnvelope:
    """Judge one session plan, isolating call and parse failures."""
    try:
        scenario = get_scenario(plan["scenario_id"])
        if scenario is None:
            raise ValueError(f"unknown scenario {plan['scenario_id']!r}")
        paper = get_paper(scenario["paper_id"])
        if paper is None:
            raise ValueError(f"unknown paper {scenario['paper_id']!r}")
        parsed = call_llm_json(
            prompt=_plan_prompt(plan, scenario, paper),
            system_prompt=PLAN_SYSTEM_PROMPT,
            max_tokens=1400,
        )
        result = _parse_plan_result(parsed)
        return MetricEnvelope(metric=dict(result), metrics_error=None)
    except Exception as exc:  # noqa: BLE001 - metric isolation is the contract
        return _failure("session_plan_coherence", exc)


def measure_explain_back(learner_explain_back: str, *, context: str = "") -> MetricEnvelope:
    """Judge a learner explain-back, isolating call and parse failures."""
    try:
        explain_back = _string(learner_explain_back, "learner_explain_back")
        parsed = call_llm_json(
            prompt=json.dumps(
                {"context": context, "learner_explain_back": explain_back},
                sort_keys=True,
            ),
            system_prompt=EXPLAIN_BACK_SYSTEM_PROMPT,
            max_tokens=1400,
        )
        result = _parse_explain_back_result(parsed)
        for gap in result["gaps"]:
            if gap["evidence_quote"] not in explain_back:
                raise ValueError(
                    f"gap {gap['gap_id']!r} evidence_quote is not learner-authored text"
                )
        return MetricEnvelope(metric=dict(result), metrics_error=None)
    except Exception as exc:  # noqa: BLE001 - metric isolation is the contract
        return _failure("explain_back", exc)


def load_explain_back_calibration(
    path: Path = CALIBRATION_PATH,
) -> dict[str, Any]:
    """Load the checked-in calibration set; structural validation is strict."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("calibration root must be an object")
    _exact_keys(raw, {"schema_version", "provenance", "cases"}, "calibration")
    if raw["schema_version"] != 1:
        raise ValueError("calibration.schema_version must be 1")
    provenance = raw["provenance"]
    if not isinstance(provenance, Mapping):
        raise ValueError("calibration.provenance must be an object")
    required_provenance = {
        "labeled_by",
        "labeled_at",
        "source_kind",
        "owner_ratified",
        "ratified_by",
        "limitations",
    }
    _exact_keys(provenance, required_provenance, "calibration.provenance")
    for key in required_provenance - {"owner_ratified"}:
        _string(provenance[key], f"calibration.provenance.{key}", allow_empty=True)
    if not isinstance(provenance["owner_ratified"], bool):
        raise ValueError("calibration.provenance.owner_ratified must be boolean")
    cases = raw["cases"]
    if not isinstance(cases, list) or not 20 <= len(cases) <= 30:
        raise ValueError("calibration.cases must contain 20 to 30 cases")
    seen: set[str] = set()
    for index, case in enumerate(cases):
        where = f"calibration.cases[{index}]"
        if not isinstance(case, Mapping):
            raise ValueError(f"{where} must be an object")
        _exact_keys(
            case,
            {"calibration_id", "paper_context", "learner_explain_back", "expected_gap_ids"},
            where,
        )
        case_id = _string(case["calibration_id"], f"{where}.calibration_id")
        if case_id in seen:
            raise ValueError(f"duplicate calibration_id {case_id!r}")
        seen.add(case_id)
        _string(case["paper_context"], f"{where}.paper_context")
        _string(case["learner_explain_back"], f"{where}.learner_explain_back")
        gaps = case["expected_gap_ids"]
        if not isinstance(gaps, list) or any(
            not isinstance(gap, str) or not gap.strip() for gap in gaps
        ):
            raise ValueError(f"{where}.expected_gap_ids must be strings")
        if len(set(gaps)) != len(gaps):
            raise ValueError(f"{where}.expected_gap_ids contains duplicates")
    return raw


def compute_explain_back_agreement(
    calibration: Mapping[str, Any],
    judge_outputs: Mapping[str, Sequence[str]],
) -> CalibrationAgreement:
    """Compute exact-set agreement and micro F1 without any LLM calls."""
    cases = calibration.get("cases")
    if not isinstance(cases, list):
        raise ValueError("calibration.cases must be a list")
    expected_by_id: dict[str, set[str]] = {}
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("calibration case must be an object")
        case_id = case.get("calibration_id")
        expected = case.get("expected_gap_ids")
        if not isinstance(case_id, str) or not isinstance(expected, list):
            raise ValueError("calibration case is malformed")
        expected_by_id[case_id] = set(expected)
    if set(judge_outputs) != set(expected_by_id):
        missing = sorted(set(expected_by_id) - set(judge_outputs))
        extra = sorted(set(judge_outputs) - set(expected_by_id))
        raise ValueError(f"judge outputs mismatch calibration: missing={missing}, extra={extra}")

    exact = tp = fp = fn = 0
    for case_id, expected in expected_by_id.items():
        predicted_values = judge_outputs[case_id]
        if isinstance(predicted_values, str) or any(
            not isinstance(value, str) for value in predicted_values
        ):
            raise ValueError(f"judge output {case_id!r} must be a string sequence")
        predicted = set(predicted_values)
        exact += predicted == expected
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total = len(expected_by_id)
    return CalibrationAgreement(
        cases=total,
        exact_matches=exact,
        exact_match_rate=exact / total if total else 1.0,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def find_unlinked_progress_events(
    events: Sequence[Mapping[str, Any]],
) -> list[int]:
    """Return indexes of progress events lacking a non-blank evidence link."""
    return [
        index
        for index, event in enumerate(events)
        if not isinstance(event.get("evidence_ref"), str) or not str(event["evidence_ref"]).strip()
    ]


def find_shaming_language(texts: Sequence[str]) -> list[ShameFinding]:
    """Return every forbidden phrase found in learner-facing copy."""
    findings: list[ShameFinding] = []
    for index, text in enumerate(texts):
        for phrase, pattern in SHAME_PATTERNS:
            match = pattern.search(text)
            if match is None:
                continue
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            findings.append(ShameFinding(phrase=phrase, text_index=index, excerpt=text[start:end]))
    return findings


__all__ = [
    "CALIBRATION_PATH",
    "CalibrationAgreement",
    "MetricEnvelope",
    "compute_explain_back_agreement",
    "find_shaming_language",
    "find_unlinked_progress_events",
    "load_explain_back_calibration",
    "measure_explain_back",
    "measure_session_plan_coherence",
]
