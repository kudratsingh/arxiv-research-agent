"""Planner agent: decomposes a research query into sub-questions and search queries."""

from typing import Any

from langchain_core.messages import AIMessage

from src.config import settings
from src.graph.state import ResearchState
from src.llm import call_llm_json
from src.security.prompt_isolation import (
    PRIOR_CONTEXT_ISOLATION_INSTRUCTION,
    wrap_untrusted_prior_context,
)

SYSTEM_PROMPT = """\
You are a research planning assistant specializing in ML/AI literature.

Given a user's research question, your job is to:
1. Break it into 2-4 focused sub-questions that together cover the topic comprehensively.
   Consider different angles: core methods, theoretical foundations, practical applications,
   benchmarks/evaluation, and recent advances.
2. For each sub-question, generate 1-2 targeted arXiv search queries.
   Search queries should be concise keyword phrases (not full sentences) that would
   retrieve relevant papers on arXiv. Use standard ML/AI terminology.

If the state includes a critique from a prior iteration, use that feedback to refine
your sub-questions and search queries — broaden coverage, target missed areas, or
sharpen specificity as the critique suggests.

Respond with valid JSON only, no markdown fencing:
{
  "sub_questions": ["...", "..."],
  "search_queries": ["...", "..."]
}
"""


def _build_user_prompt(state: ResearchState) -> str:
    """Build the user message from the current state.

    When `settings.enable_prompt_isolation` is on and the state
    carries `prior_context`, that content is wrapped in the
    prior-context untrusted-content tags before being pasted into
    the user message. The system prompt is separately guarded with
    ``PRIOR_CONTEXT_ISOLATION_INSTRUCTION`` — see `_build_system_prompt`
    and ADR 0033.
    """
    parts = [f"Research question: {state['query']}"]

    prior_context = state.get("prior_context", "")
    if prior_context:
        # ADR 0032: conversation follow-ups get top-K chunks from
        # prior reports embedded here. Position it above the
        # critique so the planner treats it as background rather
        # than corrective feedback.
        block = (
            wrap_untrusted_prior_context(prior_context)
            if settings.enable_prompt_isolation
            else prior_context
        )
        parts.append(
            "\nContext from prior queries in this conversation:\n"
            f"{block}\n\n"
            "Use these prior findings to (a) avoid redundantly "
            "researching what's already been covered and (b) target "
            "the gaps or follow-up threads the user is now asking "
            "about."
        )

    critique = state.get("critique", "")
    if critique:
        parts.append(f"\nPrevious critique (use this to improve your plan):\n{critique}")

    iteration = state.get("iteration", 0)
    if iteration > 0:
        parts.append(f"\nThis is revision iteration {iteration}. Address gaps identified above.")

    return "\n".join(parts)


def _build_system_prompt(state: ResearchState) -> str:
    """Return the base system prompt, plus the isolation instruction
    when the state carries prior_context and the flag is on.

    Kept as a separate helper so a stateless caller (tests) can
    assert on the exact system-prompt shape without reproducing the
    concatenation.
    """
    if state.get("prior_context") and settings.enable_prompt_isolation:
        return f"{PRIOR_CONTEXT_ISOLATION_INSTRUCTION}\n\n{SYSTEM_PROMPT}"
    return SYSTEM_PROMPT


def planner_agent(state: ResearchState) -> dict[str, Any]:
    """Decompose a research query into sub-questions and arXiv search queries.

    Args:
        state: Current research workflow state.

    Returns:
        Partial state update with sub_questions, search_queries, and a message.
    """
    user_prompt = _build_user_prompt(state)
    system_prompt = _build_system_prompt(state)

    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=system_prompt,
        model_name=settings.planner_model or None,
        max_tokens=1024,
        cache_system=settings.enable_prompt_caching,
    )

    sub_questions: list[str] = parsed["sub_questions"]
    search_queries: list[str] = parsed["search_queries"]

    return {
        "sub_questions": sub_questions,
        "search_queries": search_queries,
        "messages": [
            AIMessage(
                content=f"Planned {len(sub_questions)} sub-questions and "
                f"{len(search_queries)} search queries.",
                name="planner",
            )
        ],
    }
