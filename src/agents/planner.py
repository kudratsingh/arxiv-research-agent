"""Planner agent: decomposes a research query into sub-questions and search queries.

Parse defense (ADR 0041): a malformed LLM response degrades the plan
to the user's raw query as the single sub-question and search query,
logged at WARNING — the pipeline still runs an honest (if shallower)
search rather than failing the job over a formatting hiccup at its
cheapest stage.

Mock mode (ADR 0080): under `settings.use_mock_data` the plan is built
by `src.agents.mock_mode` from the query text and no model client is
constructed.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage

from src.agents import mock_mode
from src.agents.schemas import PlannerOutput
from src.config import settings
from src.graph.state import ResearchState
from src.llm import call_llm_json
from src.observability import get_logger
from src.observability.metrics import (
    DEGRADATION_RUNG_MODEL_FALLBACK,
    record_degradation_rung,
)
from src.security.prompt_isolation import (
    PRIOR_CONTEXT_ISOLATION_INSTRUCTION,
    wrap_untrusted_prior_context,
)

log = get_logger(__name__)


def _coerce_str_list(raw: Any) -> list[str]:
    """Keep only non-empty strings from an LLM-emitted list field."""
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]

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

    A malformed LLM response (unparseable JSON, missing or empty list
    fields) degrades to the raw query as the single sub-question and
    search query, with a WARNING — see the module docstring and ADR
    0041.

    Args:
        state: Current research workflow state.

    Returns:
        Partial state update with sub_questions, search_queries, and a message.
    """
    if settings.use_mock_data:
        # Before the prompt is even built, for the reason the search
        # agent checks the same setting first: mock mode is a different
        # source of truth, not a different way of asking the model.
        mock_sub_questions, mock_search_queries = mock_mode.mock_plan(state["query"])
        log.info(
            "planner_mock_plan_served",
            extra={
                "n_sub_questions": len(mock_sub_questions),
                "n_search_queries": len(mock_search_queries),
            },
        )
        return {
            "sub_questions": mock_sub_questions,
            "search_queries": mock_search_queries,
            "messages": [
                AIMessage(
                    content=f"Planned {len(mock_sub_questions)} sub-questions and "
                    f"{len(mock_search_queries)} search queries (mock data).",
                    name="planner",
                )
            ],
        }

    user_prompt = _build_user_prompt(state)
    system_prompt = _build_system_prompt(state)

    try:
        parsed = call_llm_json(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model_name=settings.planner_model or None,
            max_tokens=1024,
            cache_system=settings.enable_prompt_caching,
            schema=PlannerOutput,
        )
    except json.JSONDecodeError as exc:
        log.warning(
            "planner_response_unparseable",
            extra={"error": str(exc)},
        )
        parsed = {}
    if not isinstance(parsed, dict):
        # Valid JSON that isn't an object (a bare list / string /
        # number) — `call_llm_json`'s dict return type is a cast, not
        # a runtime guarantee. Same fallback as unparseable JSON.
        log.warning(
            "planner_response_not_an_object",
            extra={"raw_type": type(parsed).__name__},
        )
        parsed = {}

    sub_questions: list[str] = _coerce_str_list(parsed.get("sub_questions"))
    search_queries: list[str] = _coerce_str_list(parsed.get("search_queries"))

    if not sub_questions or not search_queries:
        log.warning(
            "planner_plan_fallback_to_query",
            extra={
                "n_sub_questions": len(sub_questions),
                "n_search_queries": len(search_queries),
            },
        )
        # Rung 5 of `docs/reliability.md` §5: no usable plan came back,
        # so the raw query stands in for one. Every node downstream
        # then works from a plan the planner never produced, under a
        # run that will report `succeeded`. ADR 0081.
        record_degradation_rung(
            rung=DEGRADATION_RUNG_MODEL_FALLBACK, component="planner"
        )
        sub_questions = sub_questions or [state["query"]]
        search_queries = search_queries or [state["query"]]

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
