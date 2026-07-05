"""Reader agent: extracts structured findings from paper abstracts."""

from concurrent.futures import ThreadPoolExecutor

from langchain_core.messages import AIMessage

from src.graph.state import PaperAnalysis, PaperMetadata, ResearchState
from src.llm import call_llm_json

MAX_WORKERS = 5

SYSTEM_PROMPT = """\
You are a research paper analysis assistant. Given a paper's title and abstract,
extract structured information.

Respond with valid JSON only, no markdown fencing:
{
  "key_findings": ["finding 1", "finding 2", ...],
  "methodology": "brief description of the approach/method",
  "results_summary": "key quantitative or qualitative results",
  "limitations": "noted or inferred limitations",
  "relevance": 0.0 to 1.0 score for how relevant this paper is to the research question
}

Be concise but precise. Pull findings directly from what the abstract states.
Do not fabricate details not present in the abstract.
"""


def _analyze_paper(paper: PaperMetadata, query: str) -> PaperAnalysis:
    """Extract structured analysis from a single paper's abstract."""
    user_prompt = (
        f"Research question: {query}\n\n"
        f"Paper title: {paper['title']}\n\n"
        f"Abstract:\n{paper['abstract']}"
    )

    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        max_tokens=1024,
    )

    return PaperAnalysis(
        paper_id=paper["id"],
        title=paper["title"],
        key_findings=parsed["key_findings"],
        methodology=parsed["methodology"],
        results_summary=parsed["results_summary"],
        limitations=parsed["limitations"],
        relevance=float(parsed["relevance"]),
    )


def reader_agent(state: ResearchState) -> dict:
    """Extract structured findings from each paper's abstract.

    Calls Claude once per paper to pull out key findings, methodology,
    results, limitations, and a relevance score.

    Args:
        state: Current research workflow state with papers populated.

    Returns:
        Partial state update with paper_analyses and a message.
    """
    papers = state["papers"]
    query = state["query"]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        analyses: list[PaperAnalysis] = list(
            executor.map(lambda p: _analyze_paper(p, query), papers)
        )

    return {
        "paper_analyses": analyses,
        "messages": [
            AIMessage(
                content=f"Analyzed {len(analyses)} papers from their abstracts.",
                name="reader",
            )
        ],
    }
