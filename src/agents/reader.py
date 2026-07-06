"""Reader agent: extracts structured findings from paper full text.

For each paper the reader:
  1. Downloads and extracts the PDF via `parse_pdf` (cached on disk).
  2. Splits the text into section-labeled chunks via `chunk_paper`.
  3. Ranks chunks against the planner's sub-questions via
     `rank_chunks_by_relevance`, keeping the top-K.
  4. Prompts Claude with title + abstract + ranked excerpts.

If any of steps 1-3 yields nothing (PDF unavailable, extraction failed,
no chunks), the reader gracefully falls back to abstract-only analysis
— coverage is preserved at the cost of a shallower read. Papers are
processed concurrently via a `ThreadPoolExecutor`.
"""

from concurrent.futures import ThreadPoolExecutor

from langchain_core.messages import AIMessage

from src.config import settings
from src.graph.state import PaperAnalysis, PaperMetadata, ResearchState
from src.llm import call_llm_json
from src.observability import propagate_run_context
from src.tools.chunk_ranker import rank_chunks_by_relevance
from src.tools.chunker import chunk_paper
from src.tools.pdf_parser import parse_pdf

# Back-compat re-exports for tests / callers that import these names.
MAX_WORKERS = settings.reader_max_workers
MAX_CHUNKS_PER_PAPER = settings.reader_max_chunks_per_paper

SYSTEM_PROMPT = """\
You are a research paper analysis assistant. Given a paper's title, abstract,
and (when available) ranked excerpts from its full text, extract structured
information.

Respond with valid JSON only, no markdown fencing:
{
  "key_findings": ["finding 1", "finding 2", ...],
  "methodology": "brief description of the approach/method",
  "results_summary": "key quantitative or qualitative results",
  "limitations": "noted or inferred limitations",
  "relevance": 0.0 to 1.0 score for how relevant this paper is to the research question
}

Be concise but precise. Pull findings directly from what the paper states.
Do not fabricate details not present in the provided text. When excerpts
are present, prefer them over the abstract for methodology and results.
"""


def _gather_context(paper: PaperMetadata, subquestions: list[str]) -> str:
    """Fetch, chunk, and rank the paper's full text.

    Returns a formatted excerpt block ready to paste into the prompt, or
    an empty string if any stage yields nothing. Callers treat `""` as
    the signal to fall back to abstract-only analysis.
    """
    full_text = parse_pdf(paper["pdf_url"])
    if not full_text:
        return ""

    chunks = chunk_paper(full_text)
    if not chunks:
        return ""

    ranked = rank_chunks_by_relevance(
        chunks, subquestions, top_k=settings.reader_max_chunks_per_paper
    )
    if not ranked:
        return ""

    return "\n\n".join(f"[{c['section']}] {c['text']}" for c in ranked)


def _build_user_prompt(
    paper: PaperMetadata, query: str, context: str
) -> str:
    """Assemble the reader's user prompt.

    Includes the query, title, and abstract in every case. Appends
    ranked full-text excerpts when `context` is non-empty; otherwise
    tells the model that only the abstract is available so `relevance`
    can be calibrated accordingly.
    """
    parts = [
        f"Research question: {query}",
        "",
        f"Paper title: {paper['title']}",
        "",
        f"Abstract:\n{paper['abstract']}",
    ]
    if context:
        parts.extend(
            [
                "",
                "Relevant excerpts from the paper's full text (section-tagged):",
                "",
                context,
            ]
        )
    else:
        parts.extend(
            [
                "",
                "(Full text unavailable; base your analysis on the abstract only.)",
            ]
        )
    return "\n".join(parts)


def _analyze_paper(
    paper: PaperMetadata, query: str, subquestions: list[str]
) -> PaperAnalysis:
    """Produce a structured analysis for a single paper."""
    context = _gather_context(paper, subquestions)
    user_prompt = _build_user_prompt(paper, query, context)

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
    """Read each paper (full text when available, abstract otherwise) in parallel.

    Args:
        state: Current research workflow state with `papers` populated
            and (optionally) `sub_questions` for chunk ranking.

    Returns:
        Partial state update with `paper_analyses` and a message.
    """
    papers = state["papers"]
    query = state["query"]
    subquestions = state.get("sub_questions", [])

    # Propagate the parent's run_id + cost-accumulator ContextVars into
    # each worker thread — plain ThreadPoolExecutor doesn't inherit
    # context, so LLM calls from workers would otherwise lose per-run
    # attribution.
    analyze = propagate_run_context(
        lambda p: _analyze_paper(p, query, subquestions)
    )
    with ThreadPoolExecutor(max_workers=settings.reader_max_workers) as executor:
        analyses: list[PaperAnalysis] = list(executor.map(analyze, papers))

    return {
        "paper_analyses": analyses,
        "messages": [
            AIMessage(
                content=f"Analyzed {len(analyses)} papers (full-text where available).",
                name="reader",
            )
        ],
    }
