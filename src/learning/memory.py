"""Bounded Tier-1 context and lossy session-close memory (WO-W05).

Tier 1 is the only learning memory guaranteed to enter every tutor prompt, so
its size and honesty rules are executable constraints:

* structured learner facts win over prose summaries;
* the complete prompt block stays below a 2,500-token estimate;
* a session summary is visibly lossy and can never evidence a skill claim;
* inferred claims are emitted as one close-time batch, each citing the session.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Final

from langchain_core.messages import BaseMessage, HumanMessage

from src.cancellation import JobCancelledError
from src.config import settings
from src.graph.session_state import SessionState
from src.learning.profile_serializer import render_profile_for_prompt
from src.learning.profile_store import LearnerProfile, SkillEntry
from src.llm import call_llm_json
from src.observability import get_logger
from src.observability.costs import CostBudgetExceeded
from src.security.prompt_isolation import (
    LEARNER_TEXT_ISOLATION_INSTRUCTION,
    wrap_untrusted_learner_text,
)

log = get_logger(__name__)

TIER1_TOKEN_CEILING: Final = 2_500
"""Tokenizer-free prompt budget; tests enforce ``chars / 4`` below it."""

TIER1_CHAR_CEILING: Final = TIER1_TOKEN_CEILING * 4
SESSION_SUMMARY_MAX_CHARS: Final = 600
MAX_INFERENCE_BATCH: Final = 8
SUMMARY_EVIDENCE_PREFIX: Final = "summary:"

SUMMARY_SYSTEM_PROMPT: Final = f"""\
You close one guided paper-reading session. Return a short, explicitly lossy
memory for the next check-in and optional low-confidence skill impressions.
Use only the supplied structured session data and learner-authored transcript.
Never grade, diagnose, infer personality, or report mastery.
{LEARNER_TEXT_ISOLATION_INSTRUCTION}

Return JSON only with exactly these keys:
{{
  "summary": "what was covered, how the session went, and one neutral tone line",
  "inferences": [
    {{
      "skill": "controlled lower-case vocabulary term",
      "level": "none | aware | working | solid",
      "confidence": 0.1,
      "evidence_quote": "verbatim learner-authored text"
    }}
  ]
}}
The summary must be at most about 150 tokens. Omit an inference unless a
verbatim learner quote supports it. Inferences are unconfirmed guesses.
"""


@dataclass(frozen=True, slots=True)
class SessionMemoryUpdate:
    """The two artifacts produced atomically at session close."""

    summary: dict[str, Any]
    inference_batch: tuple[SkillEntry, ...]


def _compact(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()[:limit]


def _json_chars(value: Mapping[str, Any]) -> int:
    """Measure the exact compact JSON shape the tutor sends to the model."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def _structural_profile(profile: LearnerProfile) -> dict[str, Any]:
    """Facts that may never exist only in a lossy prose summary."""
    return {
        "academic_level": profile.academic_level,
        "time_budget_min_per_day": profile.time_budget_min_per_day,
        "goals": [
            {
                "goal_id": goal.goal_id,
                "statement": goal.statement,
                "status": goal.status,
                "priority": goal.priority,
                "target_date": goal.target_date,
            }
            for goal in profile.goals
        ],
        # This field is the learner's declared constraints/preferences. It is
        # duplicated from the rendered profile intentionally: callers can
        # address it structurally, even if a stale summary contradicts it.
        "declared_constraints": profile.profile_note,
    }


def _skill_priority(entry: SkillEntry) -> tuple[int, str, str]:
    order = {"declared": 0, "assessed": 1, "inferred": 2}
    return (order[entry.source], entry.skill, entry.updated_at)


def build_tier1_memory(
    profile: LearnerProfile,
    *,
    active_path_position: Mapping[str, Any],
    session_spec: Mapping[str, Any],
    last_session_summary: Mapping[str, Any] | None,
    isolate: bool | None = None,
) -> dict[str, Any]:
    """Compose the always-in-context block under the hard character cap.

    Structural facts and the current-session coordinates are placed first.
    Skill claims then fill the remaining budget in declared, assessed,
    inferred order. The returned ``skills_omitted`` count makes truncation
    visible rather than silently implying the profile was complete.
    """
    if isolate is None:
        isolate = settings.enable_prompt_isolation

    summary: dict[str, Any] | None = None
    if last_session_summary is not None:
        text = _compact(last_session_summary.get("text"), limit=SESSION_SUMMARY_MAX_CHARS)
        summary_id = _compact(last_session_summary.get("summary_id"), limit=128)
        if text:
            summary = {
                "summary_id": summary_id,
                "lossy": True,
                "text": text,
            }

    position = {
        "path_id": _compact(active_path_position.get("path_id"), limit=128),
        "resource_id": _compact(active_path_position.get("resource_id"), limit=128),
        "position": active_path_position.get("position"),
        "entry_count": active_path_position.get("entry_count"),
    }
    today = {
        "title": _compact(session_spec.get("title"), limit=160),
        "available_minutes": session_spec.get("available_minutes"),
        "reading_guidance": list(session_spec.get("reading_guidance", []))[:8]
        if isinstance(session_spec.get("reading_guidance"), list)
        else [],
    }
    selected: list[SkillEntry] = []
    ordered = sorted(profile.skills, key=_skill_priority)

    def compose(skills: list[SkillEntry]) -> dict[str, Any]:
        # Goals and the learner's own constraints already live in the
        # structured block above. Do not duplicate their maximum-length prose
        # in the legacy renderer: duplicated context is still billed context.
        rendered_profile = replace(
            profile,
            goals=(),
            profile_note="",
            skills=tuple(skills),
        )
        return {
            "schema": "tier1.v1",
            "structured_profile": _structural_profile(profile),
            "profile_block": render_profile_for_prompt(rendered_profile, isolate=isolate),
            "active_path_position": position,
            "today_session": today,
            "last_session_summary": summary,
            "skills_omitted": len(ordered) - len(skills),
        }

    block = compose(selected)
    if _json_chars(block) > TIER1_CHAR_CEILING:
        raise ValueError(
            "Tier-1 structural facts exceed the hard context ceiling; "
            "refusing to truncate goals, time budget, or declared constraints"
        )
    for entry in ordered:
        candidate = compose([*selected, entry])
        if _json_chars(candidate) > TIER1_CHAR_CEILING:
            continue
        selected.append(entry)
        block = candidate

    if _json_chars(block) > TIER1_CHAR_CEILING:  # pragma: no cover - defensive invariant
        raise AssertionError("Tier-1 context exceeded its hard character ceiling")
    return block


def latest_session_summary(events: list[Any]) -> dict[str, Any] | None:
    """Return the newest valid lossy summary from append-only events."""
    for event in reversed(events):
        if getattr(event, "kind", None) != "session_completed":
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, Mapping):
            continue
        raw = payload.get("session_summary")
        if not isinstance(raw, Mapping) or raw.get("lossy") is not True:
            continue
        text = _compact(raw.get("text"), limit=SESSION_SUMMARY_MAX_CHARS)
        summary_id = _compact(raw.get("summary_id"), limit=128)
        if text and summary_id.startswith(SUMMARY_EVIDENCE_PREFIX):
            return {"summary_id": summary_id, "lossy": True, "text": text}
    return None


def _learner_transcript(state: SessionState) -> str:
    parts: list[str] = []
    for message in state.get("messages", []):
        if isinstance(message, HumanMessage) or (
            isinstance(message, BaseMessage) and getattr(message, "type", "") == "human"
        ):
            parts.append(_compact(message.content, limit=4_000))
    reply = _compact(state.get("learner_reply"), limit=4_000)
    if reply:
        parts.append(reply)
    return "\n".join(part for part in parts if part)[:12_000]


def _mock_summary(state: SessionState) -> str:
    spec = state.get("session_spec", {})
    title = _compact(spec.get("title"), limit=160) or "the assigned paper"
    turns = state.get("turn_number", 0)
    ended = " The learner ended the session early." if state.get("end_requested") else ""
    return (
        f"Covered {title} in {turns} guided turn(s); an explain-back was "
        f"{'recorded' if state.get('assessment') else 'not recorded'}.{ended} "
        "Tone was not inferred."
    )[:SESSION_SUMMARY_MAX_CHARS]


def _parse_inferences(raw: Any, *, transcript: str, run_id: str) -> tuple[SkillEntry, ...]:
    if not isinstance(raw, list):
        raise ValueError("session memory inferences must be a list")
    entries: list[SkillEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(raw[:MAX_INFERENCE_BATCH]):
        if not isinstance(item, Mapping) or set(item) != {
            "skill",
            "level",
            "confidence",
            "evidence_quote",
        }:
            raise ValueError(f"session memory inference[{index}] has an invalid shape")
        quote = _compact(item["evidence_quote"], limit=300)
        if not quote or quote not in transcript:
            raise ValueError(f"session memory inference[{index}] is not transcript-grounded")
        skill = _compact(item["skill"], limit=64)
        if skill in seen:
            raise ValueError(f"session memory inference[{index}] duplicates {skill!r}")
        seen.add(skill)
        entries.append(
            SkillEntry(
                skill=skill,
                level=item["level"],
                source="inferred",
                evidence_ref=f"session:{run_id}",
                confidence=float(item["confidence"]),
            )
        )
    return tuple(entries)


def generate_session_memory(state: SessionState) -> SessionMemoryUpdate:
    """Generate one lossy summary and one validated inference batch."""
    run_id = state["run_id"]
    transcript = _learner_transcript(state)
    if settings.use_mock_data:
        text = _mock_summary(state)
        inferences: tuple[SkillEntry, ...] = ()
    else:
        isolated = (
            wrap_untrusted_learner_text(transcript)
            if settings.enable_prompt_isolation
            else transcript
        )
        try:
            raw = call_llm_json(
                prompt=json.dumps(
                    {
                        "session_spec": state.get("session_spec", {}),
                        "session_plan": state.get("session_plan", {}),
                        "assessment_status": state.get("assessment", {}).get("status"),
                        "learner_transcript": isolated,
                    },
                    sort_keys=True,
                ),
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                model_name=settings.tutor_model or None,
                max_tokens=700,
                cache_system=settings.enable_prompt_caching,
            )
            if not isinstance(raw, Mapping) or set(raw) != {"summary", "inferences"}:
                raise ValueError("session memory response has an invalid shape")
            text = _compact(raw["summary"], limit=SESSION_SUMMARY_MAX_CHARS)
            if not text:
                raise ValueError("session memory summary is empty")
            inferences = _parse_inferences(raw["inferences"], transcript=transcript, run_id=run_id)
        except (JobCancelledError, CostBudgetExceeded):
            raise
        except Exception as exc:  # noqa: BLE001 - lossy memory degrades safely
            log.warning(
                "session_memory_generation_degraded",
                extra={"error_type": type(exc).__name__, "error": str(exc)},
            )
            text = _mock_summary(state)
            inferences = ()

    return SessionMemoryUpdate(
        summary={
            "summary_id": f"{SUMMARY_EVIDENCE_PREFIX}{run_id}",
            "lossy": True,
            "text": text,
        },
        inference_batch=inferences,
    )


__all__ = [
    "MAX_INFERENCE_BATCH",
    "SESSION_SUMMARY_MAX_CHARS",
    "SUMMARY_EVIDENCE_PREFIX",
    "SessionMemoryUpdate",
    "TIER1_CHAR_CEILING",
    "TIER1_TOKEN_CEILING",
    "build_tier1_memory",
    "generate_session_memory",
    "latest_session_summary",
]
