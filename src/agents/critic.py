"""Critic agent: evaluates the draft report and decides if revision is needed.

Parse defense (ADR 0041): the critic is the terminal node of the fixed
pipeline — by the time it runs, the report is already written. A
malformed judge response therefore never fails the job: scores coerce
with safe defaults, an unusable response degrades to "approved with a
zero score" at WARNING, and the finished report is delivered.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage

from src.config import settings
from src.graph.state import ResearchState
from src.llm import call_llm_json
from src.observability import get_logger

log = get_logger(__name__)

# The only revision targets the workflow graph can route to; anything
# else from the judge ("none", a typo, an injected string) means no
# revision round.
_VALID_REVISION_TARGETS = frozenset({"planner", "search", "synthesizer"})


def _safe_float(raw: Any, default: float = 0.0) -> float:
    """Coerce a judge-emitted score to float, falling back on `default`.

    Accepts the number the schema asks for and the JSON-string variant
    models sometimes emit (`"0.82"`). Logged at WARNING on fallback so
    a judge drifting off-schema is visible.
    """
    try:
        return float(raw)
    except (TypeError, ValueError):
        log.warning("critic_score_unparseable", extra={"raw": repr(raw)})
        return default

SYSTEM_PROMPT = """\
You are a rigorous research quality evaluator. Given a research question, the papers
that were analyzed, and a draft research briefing, evaluate the briefing on these
dimensions (each scored 0.0 to 1.0):

1. **Completeness**: Does the briefing address all aspects of the research question?
2. **Accuracy**: Are claims properly supported by the cited papers?
3. **Coherence**: Is the briefing well-structured and logically organized?
4. **Depth**: Does it go beyond surface-level summaries to provide real insight?
5. **Balance**: Does it fairly represent different approaches and viewpoints?

Respond with valid JSON only, no markdown fencing:
{
  "scores": {
    "completeness": 0.0,
    "accuracy": 0.0,
    "coherence": 0.0,
    "depth": 0.0,
    "balance": 0.0
  },
  "average_score": 0.0,
  "critique": "specific, actionable feedback on what to improve",
  "revision_needed": true or false,
  "revision_target": "planner" | "search" | "synthesizer" | "none"
}

Revision decision rules:
- Average score >= 0.7 → approve (revision_needed: false, revision_target: "none")
- Missing topic coverage → revision_target: "planner"
- Too few papers or weak evidence → revision_target: "search"
- Weak synthesis, poor structure, or bad citations → revision_target: "synthesizer"

Be demanding but fair. Provide concrete suggestions, not vague criticism.
"""


def _build_user_prompt(state: ResearchState) -> str:
    """Build the user message with all context for evaluation."""
    paper_titles = "\n".join(
        f"  - {a['title']}" for a in state["paper_analyses"]
    )

    return (
        f"Research question: {state['query']}\n\n"
        f"Papers analyzed ({len(state['paper_analyses'])}):\n{paper_titles}\n\n"
        f"Draft report:\n{state['draft_report']}"
    )


def critic_agent(state: ResearchState) -> dict[str, Any]:
    """Evaluate the draft research briefing for quality.

    Uses Claude for rigorous evaluation. Scores on five dimensions and
    decides whether revision is needed, routing back to the appropriate
    agent if so.

    A malformed judge response never discards the finished report: an
    unparseable body or off-schema fields coerce to safe defaults
    (approve, zero score) with a WARNING — see module docstring / ADR
    0041.

    Args:
        state: Current research workflow state with draft_report populated.

    Returns:
        Partial state update with critique, quality_score, revision flags, and a message.
    """
    user_prompt = _build_user_prompt(state)

    try:
        parsed = call_llm_json(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            model_name=settings.critic_model or None,
            max_tokens=2048,
            cache_system=settings.enable_prompt_caching,
        )
    except json.JSONDecodeError as exc:
        log.warning(
            "critic_response_unparseable",
            extra={"error": str(exc)},
        )
        parsed = {}

    # Coerce the score exactly once and reuse it everywhere — reading
    # the raw value a second time for the message used to crash on a
    # string score that survived the state-field coercion.
    score = _safe_float(parsed.get("average_score"))
    # Match the verifier's idiom: only a literal JSON `true` means
    # revision (verifier.py treats `parsed.get("verified")` the same way).
    revision_needed = parsed.get("revision_needed") is True
    revision_target = ""
    if revision_needed:
        target_raw = str(parsed.get("revision_target") or "").strip().lower()
        if target_raw in _VALID_REVISION_TARGETS:
            revision_target = target_raw
        else:
            # No routable target — deliver the report rather than spin
            # a revision round the graph cannot route.
            log.warning(
                "critic_revision_target_invalid",
                extra={"raw": repr(parsed.get("revision_target"))},
            )
            revision_needed = False

    critique = str(parsed.get("critique") or "").strip()
    iteration = state.get("iteration", 0)

    # Force approve if we've hit max iterations
    if iteration >= settings.max_iterations:
        revision_needed = False
        revision_target = ""

    status = "approved" if not revision_needed else f"needs revision → {revision_target}"

    return {
        "critique": critique,
        "quality_score": score,
        "revision_needed": revision_needed,
        "revision_target": revision_target,
        "iteration": iteration + 1,
        "messages": [
            AIMessage(
                content=(
                    f"Quality score: {score:.2f} — {status}. "
                    f"(iteration {iteration + 1}/{settings.max_iterations})"
                ),
                name="critic",
            )
        ],
    }
