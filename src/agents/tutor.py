"""Nodes for the Phase W guided-read coach.

The real-model path is deliberately small and parse-defended; the recorded
fixture path runs under ``use_mock_data=true`` without constructing an
Anthropic client. Learner-authored prose is isolation-wrapped before it enters
a prompt and is never copied into a control field.

**Learner-facing copy states, it does not deny (WO-W03b).** The surface renders
these strings unedited (RC-16/H11), so WO-W14's pedagogy vocabulary binds this
module too — *including in a sentence written to reject it*, because a denial
plants the frame it rejects. The system prompts below are the exception: they
address the model, not the learner. See `docs/agents/tutor.md`.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from src.agents.assessment import assessment_judge
from src.config import settings
from src.graph.session_state import SessionState
from src.learning.memory import generate_session_memory
from src.learning.progress_store import new_event
from src.llm import call_llm_json
from src.observability import get_logger
from src.security.prompt_isolation import (
    LEARNER_TEXT_ISOLATION_INSTRUCTION,
    wrap_untrusted_learner_text,
)

log = get_logger(__name__)

TARGET_TUTOR_TURNS = 3

CHECK_IN_SYSTEM_PROMPT = f"""\
You are planning one short guided reading session for an ML paper.
Use only the supplied paper metadata, briefing-companion guidance, learner
profile, and time available. Downscope explicitly when time is short. Never
claim the learner knows something merely because a profile inference says so.
{LEARNER_TEXT_ISOLATION_INSTRUCTION}
Respond with JSON only:
{{
  "downscoped": true,
  "downscope_reason": "...",
  "sections": [{{"name": "...", "mode": "close" | "skim"}}],
  "checks": ["..."]
}}
"""

TUTOR_SYSTEM_PROMPT = f"""\
You are a careful guided-reading tutor. Give brief feedback on the learner's
last response, then ask exactly one question grounded in the supplied paper
and session plan. Do not invent a paper claim. Do not shame, grade, or report
mastery. {LEARNER_TEXT_ISOLATION_INSTRUCTION}
Respond with JSON only:
{{"feedback": "...", "prompt": "..."}}
"""


def _string(value: Any, *, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()[:limit]


def _available_minutes(state: SessionState) -> int:
    spec = state.get("session_spec", {})
    tier1 = state.get("tier1", {})
    requested = spec.get("available_minutes")
    structured = tier1.get("structured_profile", {})
    profile_budget = (
        structured.get("time_budget_min_per_day")
        if isinstance(structured, dict)
        else tier1.get("time_budget_min_per_day")
    )
    values = [
        value
        for value in (requested, profile_budget)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    return min(values) if values else 20


def _guidance(state: SessionState) -> list[dict[str, str]]:
    raw = state.get("session_spec", {}).get("reading_guidance")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _string(item.get("name"), limit=80)
        mode = item.get("mode")
        if name and mode in {"close", "skim"}:
            result.append({"name": name, "mode": str(mode)})
    return result


def _fallback_plan(state: SessionState, *, parse_failed: bool = False) -> dict[str, Any]:
    """A bounded plan based only on validated structural inputs."""
    minutes = _available_minutes(state)
    max_sections = 1 if minutes <= 10 else 2 if minutes <= 20 else 3
    sections = _guidance(state)[:max_sections]
    if not sections:
        sections = [{"name": "paper overview", "mode": "skim"}]
    downscoped = minutes <= 10 or len(_guidance(state)) > len(sections)
    reason = ""
    if parse_failed:
        reason = "The model response was unusable, so this safe minimal plan was used."
    elif downscoped:
        reason = f"The session was reduced to fit the declared {minutes}-minute window."
    return {
        "available_minutes": minutes,
        "downscoped": downscoped,
        "downscope_reason": reason,
        "sections": sections,
        "checks": ["one guided question", "one explain-back"],
    }


def _coerce_plan(raw: Any, state: SessionState) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    allowed = _guidance(state)
    allowed_names = {item["name"] for item in allowed}
    sections_raw = raw.get("sections")
    if not isinstance(sections_raw, list):
        return None
    sections: list[dict[str, str]] = []
    for item in sections_raw:
        if not isinstance(item, dict):
            continue
        name = _string(item.get("name"), limit=80)
        mode = item.get("mode")
        # A model cannot create a section that the briefing did not name.
        if name and mode in {"close", "skim"} and (not allowed_names or name in allowed_names):
            sections.append({"name": name, "mode": str(mode)})
    minutes = _available_minutes(state)
    max_sections = 1 if minutes <= 10 else 2 if minutes <= 20 else 3
    sections = sections[:max_sections]
    if not sections:
        return None
    checks_raw = raw.get("checks")
    checks = (
        [_string(value, limit=120) for value in checks_raw if _string(value, limit=120)]
        if isinstance(checks_raw, list)
        else []
    )
    return {
        "available_minutes": minutes,
        "downscoped": bool(raw.get("downscoped")) or minutes <= 10,
        "downscope_reason": _string(raw.get("downscope_reason"), limit=240),
        "sections": sections,
        "checks": checks[:4] or ["one guided question", "one explain-back"],
    }


def check_in_agent(state: SessionState) -> dict[str, Any]:
    """Plan the day honestly, with a deterministic zero-cost mock path."""
    plan: dict[str, Any] | None
    if settings.use_mock_data:
        plan = _fallback_plan(state)
    else:
        tier1_json = json.dumps(state.get("tier1", {}), sort_keys=True)
        tier1_block = (
            wrap_untrusted_learner_text(tier1_json)
            if settings.enable_prompt_isolation
            else tier1_json
        )
        prompt = json.dumps(
            {
                "tier1": tier1_block,
                "paper": state.get("session_spec", {}),
                "available_minutes": _available_minutes(state),
            },
            sort_keys=True,
        )
        try:
            parsed = call_llm_json(
                prompt=prompt,
                system_prompt=CHECK_IN_SYSTEM_PROMPT,
                model_name=settings.tutor_model or None,
                max_tokens=900,
                cache_system=settings.enable_prompt_caching,
                agent="tutor",
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            log.warning("session_check_in_unparseable", extra={"error": str(exc)})
            parsed = None
        plan = _coerce_plan(parsed, state)
        if plan is None:
            log.warning("session_check_in_safe_fallback")
            plan = _fallback_plan(state, parse_failed=True)
    assert plan is not None
    return {
        "session_plan": plan,
        "messages": [
            AIMessage(
                content=(
                    f"Planned {len(plan['sections'])} section(s) for "
                    f"{plan['available_minutes']} minutes."
                ),
                name="check_in",
            )
        ],
    }


def passage_agent(state: SessionState) -> dict[str, Any]:
    """Open the first learner turn without making a knowledge claim."""
    title = _string(state.get("session_spec", {}).get("title"), limit=160)
    prompt = (
        f"Before we read {title or 'this paper'}, what do you expect it to help "
        "you understand? A sentence or two is enough."
    )
    activity = {"kind": "reflection", "instructions": prompt}
    return {
        "activity": activity,
        "turn": {
            "turn_number": 1,
            "phase": "passage",
            "kind": "reflection",
            "prompt": prompt,
            "feedback": "",
            "activity": activity,
        },
        "awaiting_assessment": False,
    }


def learner_input_agent(state: SessionState) -> dict[str, Any]:
    """Suspend durably and accept exactly one learner-authored reply.

    Nothing with a side effect happens before ``interrupt``, so process
    reattachment can re-enter this node without duplicating a model call or
    progress write.
    """
    resumed = interrupt(state.get("turn", {}))
    if not isinstance(resumed, dict):
        return {"learner_reply": "", "end_requested": True}
    reply = resumed.get("learner_reply")
    return {
        "learner_reply": reply if isinstance(reply, str) else "",
        "end_requested": bool(resumed.get("end_requested")),
    }


def _tutor_prompts(state: SessionState, reply: str) -> tuple[str, str]:
    """Return feedback and one next question, safely."""
    processed = _processed_turn(state)
    if settings.use_mock_data:
        feedback = "Thanks — I recorded that as your own observation."
        prompt = (
            "Which connection in the section feels least obvious, and what "
            "would you check in the paper to resolve it?"
        )
        return feedback, prompt

    wrapped_reply = (
        wrap_untrusted_learner_text(reply) if settings.enable_prompt_isolation else reply
    )
    prompt_body = json.dumps(
        {
            "session_plan": state.get("session_plan", {}),
            "paper": state.get("session_spec", {}),
            "turn_number": processed,
            "learner_reply": wrapped_reply,
        },
        sort_keys=True,
    )
    try:
        parsed = call_llm_json(
            prompt=prompt_body,
            system_prompt=TUTOR_SYSTEM_PROMPT,
            model_name=settings.tutor_model or None,
            max_tokens=650,
            cache_system=settings.enable_prompt_caching,
            agent="tutor",
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("session_tutor_unparseable", extra={"error": str(exc)})
        parsed = None
    if isinstance(parsed, dict):
        feedback = _string(parsed.get("feedback"), limit=500)
        prompt = _string(parsed.get("prompt"), limit=500)
        if feedback and prompt:
            return feedback, prompt
    log.warning("session_tutor_safe_reask")
    return (
        "I could not safely interpret the tutoring response, so I am not "
        "drawing a conclusion from it.",
        "Please restate the point you want to examine in your own words.",
    )


def _processed_turn(state: SessionState) -> int:
    """Return the monotonic count after processing the parked reply.

    LangGraph checkpoints both the internal processed count and the public
    learner-facing turn payload. A resume update can be attributed to the
    interrupted node, so older checkpoints may expose the public counter one
    step ahead of the scalar. Taking both makes replay monotonic without using
    wall-clock or process-local state.
    """
    internal = state.get("turn_number", 0)
    public = state.get("turn", {}).get("turn_number", 0)
    internal_count = internal if isinstance(internal, int) else 0
    public_count = public if isinstance(public, int) else 0
    return max(internal_count + 1, public_count)


def tutor_agent(state: SessionState) -> dict[str, Any]:
    """Process one learner reply and produce the next bounded turn."""
    reply = _string(state.get("learner_reply"), limit=4_000)
    feedback, prompt = _tutor_prompts(state, reply)
    processed = _processed_turn(state)
    explain_back = processed >= TARGET_TUTOR_TURNS
    log.info(
        "session_tutor_turn_prepared",
        extra={
            "processed_turns": processed,
            "previous_public_turn": state.get("turn", {}).get("turn_number"),
        },
    )
    if explain_back:
        prompt = (
            "Explain the paper's central move back in your own words. Include "
            "one point you are unsure about; uncertainty is useful evidence."
        )
    kind: Literal["guided_question", "explain_back"] = (
        "explain_back" if explain_back else "guided_question"
    )
    activity = {"kind": kind, "instructions": prompt}
    return {
        "learner_reply": "",
        "turn_number": processed,
        "awaiting_assessment": explain_back,
        "activity": activity,
        "turn": {
            "turn_number": processed + 1,
            "phase": "tutor",
            "kind": kind,
            "prompt": prompt,
            "feedback": feedback,
            "activity": activity,
        },
        "messages": [
            HumanMessage(content=reply, name="learner"),
            AIMessage(content=f"{feedback}\n\n{prompt}", name="tutor"),
        ],
    }


def assess_agent(state: SessionState) -> dict[str, Any]:
    """Use the default-off judge or preserve W03's informal baseline."""
    if settings.enable_assessment_judge:
        return assessment_judge(state)
    reply = _string(state.get("learner_reply"), limit=4_000)
    quote = reply[:240]
    assessment = {
        "status": "recorded_ungraded",
        "guidance_only": True,
        "evidence_quote": quote,
        "gap_findings": [],
        "note": "The explain-back is recorded; WO-W04 supplies the calibrated judge.",
    }
    return {
        "assessment": assessment,
        "learner_reply": "",
        "awaiting_assessment": False,
        "messages": [
            HumanMessage(content=reply, name="learner_explain_back"),
            AIMessage(
                content=(
                    "Thanks — I recorded your explain-back in your own words. "
                    "The assessment judge is off, so I am not drawing a gap or "
                    "strength conclusion from it."
                ),
                name="tutor",
            ),
        ],
    }


def route_after_assessment(state: SessionState) -> str:
    """Offer at most one grounded follow-up probe, never a revision loop."""
    assessment = state.get("assessment", {})
    gaps = assessment.get("gaps")
    probe = _string(assessment.get("follow_up_probe"), limit=400)
    if assessment.get("status") == "assessed" and isinstance(gaps, list) and gaps and probe:
        return "probe"
    return "progress_update"


def assessment_probe_agent(state: SessionState) -> dict[str, Any]:
    """Turn the judge's grounded gap advice into one learner-facing question."""
    probe = _string(state.get("assessment", {}).get("follow_up_probe"), limit=400)
    activity = {"kind": "follow_up_probe", "instructions": probe}
    return {
        "activity": activity,
        "turn": {
            "turn_number": state.get("turn_number", 0) + 2,
            "phase": "tutor",
            "kind": "follow_up_probe",
            "prompt": probe,
            "feedback": (
                "I found one point worth checking, based on the words in your "
                "explain-back. Your answer is recorded with the rest of the session."
            ),
            "activity": activity,
        },
        "messages": [
            AIMessage(
                content=f"One follow-up question: {probe}",
                name="tutor",
            )
        ],
    }


def record_assessment_probe_agent(state: SessionState) -> dict[str, Any]:
    """Attach the one follow-up reply as evidence without judging it again."""
    reply = _string(state.get("learner_reply"), limit=4_000)
    assessment = dict(state.get("assessment", {}))
    assessment["follow_up_response_quote"] = reply[:240]
    return {
        "assessment": assessment,
        "learner_reply": "",
        "messages": [HumanMessage(content=reply, name="learner_follow_up")],
    }


def progress_update_agent(state: SessionState) -> dict[str, Any]:
    """Produce idempotent append-only ledger records for the runner to persist."""
    run_id = state["run_id"]
    principal = state["principal_key_id"]
    spec = state.get("session_spec", {})
    path_id = _string(spec.get("path_id"), limit=128)
    resource_id = _string(spec.get("resource_id"), limit=128)
    common = {"path_id": path_id, "resource_id": resource_id}

    memory_update = generate_session_memory(state)
    events = []
    assessment = state.get("assessment", {})
    if assessment:
        status = _string(assessment.get("status"), limit=40) or "recorded_ungraded"
        gaps = assessment.get("gaps")
        strengths = assessment.get("strengths")
        events.append(
            new_event(
                principal_key_id=principal,
                kind="assessment",
                evidence_ref=f"session:{run_id}#explain-back",
                event_id=f"{run_id}:assessment",
                payload={
                    **common,
                    "result": status,
                    "evidence_quote": _string(assessment.get("evidence_quote"), limit=240),
                    "gaps": gaps if isinstance(gaps, list) else [],
                    "strengths": strengths if isinstance(strengths, list) else [],
                    "follow_up_response_quote": _string(
                        assessment.get("follow_up_response_quote"), limit=240
                    ),
                    "note": _string(assessment.get("note"), limit=400),
                },
            ).to_json_dict()
        )
    planned = spec.get("path_entry_count")
    payload: dict[str, Any] = dict(common)
    if isinstance(planned, int) and not isinstance(planned, bool) and planned > 0:
        payload["sessions_planned"] = planned
    payload["ended_early"] = bool(state.get("end_requested"))
    payload["session_summary"] = memory_update.summary
    events.append(
        new_event(
            principal_key_id=principal,
            kind="session_completed",
            evidence_ref=f"session:{run_id}",
            event_id=f"{run_id}:completed",
            payload=payload,
        ).to_json_dict()
    )

    title = _string(spec.get("title"), limit=160) or "Guided reading"
    result = (
        f"# Session complete: {title}\n\n"
        f"- Guided turns completed: {state.get('turn_number', 0)}\n"
        f"- Explain-back recorded: {'yes' if assessment else 'no'}\n"
        f"- Ended early by learner: {'yes' if state.get('end_requested') else 'no'}\n"
        "\nThe lines above are this session's activity record, drawn from the "
        "events it wrote."
    )
    return {
        "progress_events": events,
        "session_summary": memory_update.summary,
        "inference_batch": [entry.to_mapping() for entry in memory_update.inference_batch],
        "draft_report": result,
        "quality_score": None,
        "iteration": state.get("turn_number", 0),
        "turn": {},
    }


def route_after_turn(state: SessionState) -> str:
    """Choose the next node after a learner-facing interrupt resumes."""
    if state.get("end_requested"):
        return "progress_update"
    if state.get("awaiting_assessment"):
        return "assess"
    return "tutor"
