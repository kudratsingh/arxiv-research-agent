"""Planner agent: decomposes a research query into sub-questions and search queries."""

from langchain_core.messages import AIMessage

from src.config import settings
from src.graph.state import ResearchState
from src.llm import call_llm_json

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
    """Build the user message from the current state."""
    parts = [f"Research question: {state['query']}"]

    critique = state.get("critique", "")
    if critique:
        parts.append(f"\nPrevious critique (use this to improve your plan):\n{critique}")

    iteration = state.get("iteration", 0)
    if iteration > 0:
        parts.append(f"\nThis is revision iteration {iteration}. Address gaps identified above.")

    return "\n".join(parts)


def planner_agent(state: ResearchState) -> dict:
    """Decompose a research query into sub-questions and arXiv search queries.

    Args:
        state: Current research workflow state.

    Returns:
        Partial state update with sub_questions, search_queries, and a message.
    """
    user_prompt = _build_user_prompt(state)

    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        model_name=settings.planner_model or None,
        max_tokens=1024,
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
