"""Synthesizer agent: combines paper analyses into a structured research briefing."""

import json

from langchain_core.messages import AIMessage

from src.graph.state import Citation, ResearchState
from src.llm import call_llm_json

SYSTEM_PROMPT = """\
You are a research synthesis expert. Given a set of analyzed ML/AI papers and a
research question, produce a structured research briefing in markdown.

Your briefing must:
1. Group findings by theme or approach — do not just summarize paper by paper.
2. Compare methodologies and results across papers.
3. Identify areas of consensus, contradictions, and gaps in the literature.
4. Cite papers inline as [Author, Year] (use first author's last name).
5. End with a "Key Takeaways" section and "Open Questions" section.

Respond with valid JSON only, no markdown fencing:
{
  "draft_report": "the full markdown report as a string",
  "citations": [
    {
      "paper_id": "...",
      "title": "...",
      "authors": ["..."],
      "year": "...",
      "url": "..."
    }
  ]
}

Make the report thorough but concise — aim for 800-1500 words.
"""


def _build_user_prompt(state: ResearchState) -> str:
    """Build the user message with the research question and all paper analyses."""
    parts = [f"Research question: {state['query']}\n"]

    critique = state.get("critique", "")
    if critique:
        parts.append(f"Previous critique (address this feedback):\n{critique}\n")

    parts.append("Papers analyzed:\n")
    for i, analysis in enumerate(state["paper_analyses"], 1):
        paper = next(
            (p for p in state["papers"] if p["id"] == analysis["paper_id"]),
            None,
        )
        authors_str = ", ".join(paper["authors"][:3]) if paper else "Unknown"
        if paper and len(paper["authors"]) > 3:
            authors_str += " et al."

        parts.append(
            f"--- Paper {i} ---\n"
            f"Title: {analysis['title']}\n"
            f"Authors: {authors_str}\n"
            f"ID: {analysis['paper_id']}\n"
            f"URL: {paper['url'] if paper else 'N/A'}\n"
            f"Key findings: {json.dumps(analysis['key_findings'])}\n"
            f"Methodology: {analysis['methodology']}\n"
            f"Results: {analysis['results_summary']}\n"
            f"Limitations: {analysis['limitations']}\n"
            f"Relevance: {analysis['relevance']}\n"
        )

    return "\n".join(parts)


def synthesizer_agent(state: ResearchState) -> dict:
    """Synthesize paper analyses into a structured research briefing.

    Uses Gemini Pro for high-quality synthesis across papers, grouping by
    theme, comparing methods, and identifying consensus/contradictions.

    Args:
        state: Current research workflow state with paper_analyses populated.

    Returns:
        Partial state update with draft_report, citations, and a message.
    """
    user_prompt = _build_user_prompt(state)

    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        max_tokens=4096,
    )

    citations = [
        Citation(
            paper_id=c["paper_id"],
            title=c["title"],
            authors=c["authors"],
            year=c["year"],
            url=c["url"],
        )
        for c in parsed["citations"]
    ]

    return {
        "draft_report": parsed["draft_report"],
        "citations": citations,
        "messages": [
            AIMessage(
                content=f"Synthesized report with {len(citations)} citations.",
                name="synthesizer",
            )
        ],
    }
