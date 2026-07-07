"""Supervisor agent — chooses the next action in the research loop.

Enabled via `settings.enable_supervisor` (default off). When on, the
workflow becomes an observe-decide-act loop: supervisor picks the next
node from a strict action enum, that node runs, then control returns
to the supervisor. When off, the fixed pipeline (planner -> search ->
reader -> synthesizer -> critic) runs unchanged.

Design (ADR 0014):
- **Strict enum action space** — the LLM's response is validated
  against `VALID_ACTIONS`; anything outside falls back to the fixed
  pipeline's default next step. Not a fatal error; a recoverable
  fallback so the loop can never derail from a malformed judge.
- **Budget short-circuits before the LLM call** — if we're already
  past `max_cost_usd` or `max_loop_iterations`, we don't ask the
  supervisor, we stop with a specific `stop_reason`. Saves cost when
  the loop is misbehaving.
- **`stop_reason` is recorded on state** so downstream analysis /
  eval can bucket runs: `quality_reached` / `budget_reached` /
  `max_iterations_reached` / `supervisor_stop` / `llm_failed`.
"""

from typing import Any

from langchain_core.messages import AIMessage

from src.config import settings
from src.graph.state import ResearchState
from src.llm import call_llm_json
from src.observability import current_costs, get_logger

log = get_logger(__name__)

# Strict action set. Any judge output outside this set falls back to
# the deterministic pipeline-order routing.
VALID_ACTIONS: frozenset[str] = frozenset(
    {"plan", "search", "read", "synthesize", "critique", "stop"}
)

# Map action -> LangGraph node name for the router. Kept as a module
# constant so the workflow file and this file share the mapping.
ACTION_TO_NODE: dict[str, str] = {
    "plan": "planner",
    "search": "search",
    "read": "reader",
    "synthesize": "synthesizer",
    "critique": "critic",
}


SUPERVISOR_SYSTEM_PROMPT = """\
You are the supervisor of a multi-agent research workflow. On each
step, you decide the next action based on the current state.

Available actions (choose exactly one):
- plan       : (Re-)decompose the query into sub-questions + search queries
- search     : Search arXiv for papers matching current search queries
- read       : Extract structured findings from retrieved papers
- synthesize : Write or revise the research report from paper analyses
- critique   : Score the current draft report for quality
- stop       : Finish the workflow

Choose the action that best advances the workflow given progress so
far. Prefer STOP when:
- Critic's quality_score >= {min_quality}
- Cost usage >= ${max_cost:.2f}
- Loop iterations >= {max_iterations}
- No progress in recent iterations (same action repeating without new
  outputs)

Follow the natural pipeline unless there's a clear reason to deviate:
plan -> search -> read -> synthesize -> critique. Deviate to re-search
when papers are weak, re-read when analyses miss context, re-plan when
the critic flags missing coverage.

Return JSON only, no markdown fencing:
{{
  "next_action": "plan|search|read|synthesize|critique|stop",
  "reason": "one-sentence justification",
  "stop_reason": "quality_reached|budget_reached|max_iterations_reached|supervisor_stop"
}}

`stop_reason` MUST be an empty string when `next_action` != "stop".
"""


def _summarize_state(state: ResearchState) -> str:
    """Compact one-block state summary for the supervisor prompt.

    Keeps the prompt cheap (~300 tokens) — the supervisor doesn't need
    full paper contents, just a progress snapshot to pick a next action.
    """
    costs = current_costs()
    cost_str = (
        f"${costs.total_cost_usd:.4f}" if costs is not None else "$?"
    )
    quality = state.get("quality_score", 0.0)
    critique_snippet = (state.get("critique") or "")[:200]
    critique_display = (
        f"critique_snippet: {critique_snippet}"
        if critique_snippet
        else "critique_snippet: (none)"
    )
    return "\n".join(
        [
            f"query: {state.get('query', '(none)')}",
            f"sub_questions: {len(state.get('sub_questions', []))}",
            f"search_queries: {len(state.get('search_queries', []))}",
            f"papers: {len(state.get('papers', []))}",
            f"paper_analyses: {len(state.get('paper_analyses', []))}",
            f"draft_report_written: {'yes' if state.get('draft_report') else 'no'}",
            f"has_critique: {'yes' if state.get('critique') else 'no'}",
            f"quality_score: {quality:.2f}",
            f"revision_needed: {state.get('revision_needed', False)}",
            f"revision_target: {state.get('revision_target', '(none)')}",
            f"iteration: {state.get('iteration', 0)}",
            f"loop_iterations: {state.get('loop_iterations', 0)}",
            f"cost_usd: {cost_str}",
            critique_display,
        ]
    )


def _default_next_action(state: ResearchState) -> str:
    """Fixed-pipeline fallback when supervisor output can't be trusted.

    Used when the LLM returns an invalid action, the call raises, or
    JSON parsing fails. Mirrors the pre-supervisor routing order and
    respects `revision_needed` from the critic.
    """
    if state.get("revision_needed") and state.get("iteration", 0) < settings.max_iterations:
        target = state.get("revision_target", "")
        if target == "planner":
            return "plan"
        if target == "search":
            return "search"
        if target == "synthesizer":
            return "synthesize"

    if not state.get("sub_questions"):
        return "plan"
    if not state.get("papers"):
        return "search"
    if not state.get("paper_analyses"):
        return "read"
    if not state.get("draft_report"):
        return "synthesize"
    if not state.get("critique"):
        return "critique"
    return "stop"


def _emit(
    action: str,
    reason: str,
    stop_reason: str,
    loop_iter: int,
) -> dict[str, Any]:
    """Build the partial-state update the supervisor returns."""
    return {
        "next_action": action,
        "stop_reason": stop_reason,
        "loop_iterations": loop_iter,
        "messages": [
            AIMessage(
                content=f"supervisor -> {action}: {reason}",
                name="supervisor",
            )
        ],
    }


def _clean_string(value: Any) -> str:
    """Coerce a judge-returned field to a stripped string, safely."""
    if isinstance(value, str):
        return value.strip()
    return ""


def supervisor_agent(state: ResearchState) -> dict[str, Any]:
    """Decide the next action given current workflow state.

    Args:
        state: Full `ResearchState`. Reads the counts/flags fields to
            summarize progress; reads `loop_iterations` for the hard
            cap check.

    Returns:
        Partial state update with `next_action`, `stop_reason`,
        `loop_iterations`, and an `AIMessage` recording the decision.
    """
    loop_iter = state.get("loop_iterations", 0) + 1

    # Hard iteration cap — never even ask the LLM.
    if loop_iter > settings.max_loop_iterations:
        log.warning(
            "supervisor_max_iterations_stop",
            extra={"loop_iter": loop_iter, "cap": settings.max_loop_iterations},
        )
        return _emit(
            "stop",
            "loop iterations exceeded",
            "max_iterations_reached",
            loop_iter,
        )

    # Cost cap — supervisor refuses further actions above budget.
    costs = current_costs()
    if costs is not None and costs.total_cost_usd >= settings.max_cost_usd:
        log.warning(
            "supervisor_cost_budget_stop",
            extra={
                "cost_usd": costs.total_cost_usd,
                "cap": settings.max_cost_usd,
            },
        )
        return _emit(
            "stop", "cost budget exhausted", "budget_reached", loop_iter
        )

    user_prompt = _summarize_state(state)
    system_prompt = SUPERVISOR_SYSTEM_PROMPT.format(
        min_quality=settings.min_quality_score,
        max_cost=settings.max_cost_usd,
        max_iterations=settings.max_loop_iterations,
    )

    try:
        parsed = call_llm_json(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=512,
        )
    except Exception as exc:  # noqa: BLE001 — recoverable, log + fallback
        log.warning(
            "supervisor_llm_failed_fallback_to_default",
            extra={"error": str(exc)},
        )
        fallback = _default_next_action(state)
        return _emit(
            fallback,
            f"supervisor LLM failed ({type(exc).__name__}); used default",
            "" if fallback != "stop" else "supervisor_stop",
            loop_iter,
        )

    action = _clean_string(parsed.get("next_action"))
    reason = _clean_string(parsed.get("reason"))
    stop_reason = _clean_string(parsed.get("stop_reason"))

    if action not in VALID_ACTIONS:
        log.warning(
            "supervisor_invalid_action_fallback",
            extra={"received": action, "parsed_keys": list(parsed.keys())},
        )
        fallback = _default_next_action(state)
        return _emit(
            fallback,
            f"invalid action '{action}'; fell back to default",
            "" if fallback != "stop" else "supervisor_stop",
            loop_iter,
        )

    # If the supervisor chose "stop" but didn't give a reason, default to a
    # generic supervisor_stop so downstream analysis has *something*.
    if action == "stop" and not stop_reason:
        stop_reason = "supervisor_stop"

    # Conversely, ignore stop_reason when we're not stopping.
    if action != "stop":
        stop_reason = ""

    return _emit(action, reason or "(no reason given)", stop_reason, loop_iter)


def route_after_supervisor(state: ResearchState) -> str:
    """Conditional edge: translate `state['next_action']` to a node name.

    Returns the LangGraph node name (or `END`) to run next. Unknown /
    missing actions map to `END` so the graph can never wedge.
    """
    from langgraph.graph import END

    action = state.get("next_action", "")
    if action == "stop":
        return END
    node = ACTION_TO_NODE.get(action)
    if node is None:
        log.warning(
            "route_after_supervisor_unknown_action_endpoint",
            extra={"action": action},
        )
        return END
    return node
