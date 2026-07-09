"""Synthesizer agent: combines paper analyses into a structured research briefing.

Two prompt paths, gated by `settings.enable_evidence_store` (see ADR
0016 / 0017):

- **Base path (default)** — reads only `paper_analyses`, byte-identical
  to the Sprint 1 baseline so evaluations remain apples-to-apples.
- **Evidence path** — when the flag is on and `state.evidence` is
  populated, prompt is augmented with per-sub-question grounded
  excerpts drawn from `EvidenceClaim.source_text`. The LLM is told
  to ground every factual sentence in one of the provided excerpts;
  the report format on the outside is unchanged (still markdown with
  inline `[Author, Year]` citations) so downstream metrics and the
  verifier keep working without a schema change.
"""

import json
from collections import defaultdict

from langchain_core.messages import AIMessage

from src.config import settings
from src.graph.state import Citation, EvidenceClaim, ResearchState
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


EVIDENCE_SYSTEM_PROMPT = """\
You are a research synthesis expert. Given a set of analyzed ML/AI papers,
a research question, and a bank of source-grounded evidence excerpts (each
tied to a specific paper and section), produce a structured research
briefing in markdown.

Your briefing must:
1. Group findings by theme or approach — do not just summarize paper by paper.
2. Compare methodologies and results across papers.
3. Identify areas of consensus, contradictions, and gaps in the literature.
4. Cite papers inline as [Author, Year] (use first author's last name).
5. End with a "Key Takeaways" section and "Open Questions" section.

GROUNDING RULES (this is what makes this task different from the base prompt):
- Every factual claim in the briefing MUST be traceable to one of the
  provided evidence excerpts. If an excerpt doesn't support a claim, do not
  make the claim.
- When the evidence bank is silent on a topic the sub-questions call for,
  say so explicitly in "Open Questions" — do NOT fill the gap from the
  paper's abstract or your prior knowledge.
- Paraphrasing an excerpt is fine; introducing facts absent from every
  excerpt is not.

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


def _use_evidence_path(state: ResearchState) -> bool:
    """Whether the evidence-grounded prompt path should be taken.

    Both conditions must hold: (1) flag on, (2) reader actually produced
    claims. When the flag is on but `evidence` is empty (all PDFs failed
    to parse, for instance), we transparently fall back to the base
    path rather than force a grounded report against no grounding.
    """
    return settings.enable_evidence_store and bool(state.get("evidence"))


def _paper_authors_by_id(state: ResearchState) -> dict[str, str]:
    """Author label per paper_id, formatted for the prompt.

    Matches the base path's "First, Second, Third et al." format so the
    two prompts feed the LLM structurally identical paper headers.
    """
    labels: dict[str, str] = {}
    for paper in state.get("papers", []):
        authors = paper.get("authors", []) or []
        head = ", ".join(authors[:3]) or "Unknown"
        if len(authors) > 3:
            head += " et al."
        labels[paper["id"]] = head
    return labels


def _format_analyses_block(state: ResearchState) -> str:
    """Base-path paper block — unchanged for baseline stability."""
    labels = _paper_authors_by_id(state)
    parts: list[str] = []
    for i, analysis in enumerate(state["paper_analyses"], 1):
        paper = next(
            (p for p in state["papers"] if p["id"] == analysis["paper_id"]),
            None,
        )
        authors_str = labels.get(analysis["paper_id"], "Unknown")
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


def _format_evidence_block(state: ResearchState) -> str:
    """Evidence-path block: excerpts grouped by sub-question.

    Excerpts inside each sub-question are ordered by relevance (highest
    first) so the LLM sees the strongest support first. Claims whose
    `supports_question` is empty are collected under an "(unassigned)"
    heading so their evidence isn't dropped on the floor.
    """
    labels = _paper_authors_by_id(state)
    grouped: dict[str, list[EvidenceClaim]] = defaultdict(list)
    for claim in state.get("evidence", []):
        key = claim["supports_question"] or "(unassigned)"
        grouped[key].append(claim)
    for claims in grouped.values():
        claims.sort(key=lambda c: c["relevance_score"], reverse=True)

    # Sub-questions come first in the planner's order so the block
    # reads top-to-bottom the same way the report will.
    ordered_keys: list[str] = []
    seen: set[str] = set()
    for q in state.get("sub_questions", []):
        if q in grouped:
            ordered_keys.append(q)
            seen.add(q)
    for key in grouped:
        if key not in seen:
            ordered_keys.append(key)

    lines: list[str] = []
    for key in ordered_keys:
        heading = f"### Sub-question: {key}" if key != "(unassigned)" else "### Unassigned excerpts"
        lines.append(heading)
        for claim in grouped[key]:
            author = labels.get(claim["paper_id"], "Unknown")
            header = (
                f"- [{author}] ({claim['section']}, "
                f"relevance={claim['relevance_score']:.2f}) — claim: {claim['claim']}"
            )
            lines.append(header)
            lines.append(f"    excerpt: {claim['source_text']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _build_user_prompt(state: ResearchState) -> str:
    """Build the user message; shape depends on `_use_evidence_path`.

    The base path stays byte-identical to the Sprint 1 baseline.
    The evidence path keeps the base analyses block for context and
    APPENDS the grounded evidence bank — analyses give the LLM the
    "shape" of each paper (methodology / limitations), while the
    evidence block is what it's allowed to draw factual claims from.
    """
    parts = [f"Research question: {state['query']}\n"]

    critique = state.get("critique", "")
    if critique:
        parts.append(f"Previous critique (address this feedback):\n{critique}\n")

    parts.append("Papers analyzed:\n")
    parts.append(_format_analyses_block(state))

    if _use_evidence_path(state):
        sub_qs = state.get("sub_questions", [])
        sub_q_lines = "\n".join(f"  - {q}" for q in sub_qs) or "  (none)"
        parts.append("\nSub-questions the briefing must cover:")
        parts.append(sub_q_lines)
        parts.append("\nEvidence bank (source-grounded excerpts):")
        parts.append("")
        parts.append(_format_evidence_block(state))

    return "\n".join(parts)


def synthesizer_agent(state: ResearchState) -> dict:
    """Synthesize paper analyses into a structured research briefing.

    Under the fixed pipeline (or when the evidence store is off / empty)
    the prompt and behavior are unchanged from the Sprint 1 baseline.
    When `settings.enable_evidence_store` is on and the reader produced
    claims, the LLM is given a grounded evidence bank and told to draw
    every factual sentence from it (ADR 0017).

    Args:
        state: Current research workflow state with paper_analyses
            populated (and, on the evidence path, `evidence`).

    Returns:
        Partial state update with draft_report, citations, and a message.
    """
    evidence_path = _use_evidence_path(state)
    user_prompt = _build_user_prompt(state)
    system_prompt = EVIDENCE_SYSTEM_PROMPT if evidence_path else SYSTEM_PROMPT

    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=system_prompt,
        model_name=settings.synthesizer_model or None,
        max_tokens=4096,
        cache_system=settings.enable_prompt_caching,
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

    if evidence_path:
        summary = (
            f"Synthesized report from {len(state.get('evidence', []))} "
            f"grounded claims with {len(citations)} citations."
        )
    else:
        summary = f"Synthesized report with {len(citations)} citations."

    return {
        "draft_report": parsed["draft_report"],
        "citations": citations,
        "messages": [AIMessage(content=summary, name="synthesizer")],
    }
