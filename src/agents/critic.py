"""Critic agent: evaluates the draft report and decides if revision is needed."""

from langchain_core.messages import AIMessage

from src.config import settings
from src.graph.state import ResearchState
from src.llm import call_llm_json

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


def critic_agent(state: ResearchState) -> dict:
    """Evaluate the draft research briefing for quality.

    Uses Claude for rigorous evaluation. Scores on five dimensions and
    decides whether revision is needed, routing back to the appropriate
    agent if so.

    Args:
        state: Current research workflow state with draft_report populated.

    Returns:
        Partial state update with critique, quality_score, revision flags, and a message.
    """
    user_prompt = _build_user_prompt(state)

    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        model_name=settings.critic_model or None,
        max_tokens=2048,
    )

    revision_needed = parsed["revision_needed"]
    revision_target = parsed["revision_target"] if revision_needed else ""
    iteration = state.get("iteration", 0)

    # Force approve if we've hit max iterations
    if iteration >= settings.max_iterations:
        revision_needed = False
        revision_target = ""

    status = "approved" if not revision_needed else f"needs revision → {revision_target}"

    return {
        "critique": parsed["critique"],
        "quality_score": float(parsed["average_score"]),
        "revision_needed": revision_needed,
        "revision_target": revision_target,
        "iteration": iteration + 1,
        "messages": [
            AIMessage(
                content=(
                    f"Quality score: {parsed['average_score']:.2f} — {status}. "
                    f"(iteration {iteration + 1}/{settings.max_iterations})"
                ),
                name="critic",
            )
        ],
    }
