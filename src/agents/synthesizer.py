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

Parse defense (ADR 0041): the synthesizer runs after the whole reader
fan-out has been billed, so one malformed response must not discard
the run. An unusable response (unparseable JSON, missing/empty
`draft_report` — typically a `max_tokens` truncation mid-string) is
retried exactly once with a corrective nudge; if the retry is also
unusable the node raises the typed `SynthesizerOutputError` so the job
fails with an honest `error_type` — the draft report IS the product,
there is no honest fallback for it. Malformed `citations` entries, by
contrast, are individually dropped with a WARNING: a report with a
thinner citation list is still a real report, and the verifier/critic
flag citation gaps downstream.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from langchain_core.messages import AIMessage

from src.config import settings
from src.graph.state import Citation, EvidenceClaim, ResearchState
from src.llm import call_llm_json
from src.observability import get_logger

log = get_logger(__name__)


class SynthesizerOutputError(RuntimeError):
    """The synthesizer produced no usable draft report, even after a retry.

    Raised when both the original call and the single corrective retry
    yielded unparseable JSON or an empty `draft_report`. The API runner
    maps the class name straight to the job's `error_type`, so the
    failure reads as what it is — a synthesis output failure — rather
    than a generic `JSONDecodeError` (ADR 0041).
    """


_RETRY_NUDGE = (
    "Your previous response was not valid JSON with a non-empty "
    '"draft_report" string. Respond again with ONLY the JSON object '
    "described in the system prompt — no markdown fencing, no prose "
    "outside the JSON."
)

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


def _call_with_one_retry(user_prompt: str, system_prompt: str) -> dict[str, Any]:
    """Call the LLM; retry exactly once when the response is unusable.

    "Unusable" means unparseable JSON or a missing/empty
    `draft_report` — the `max_tokens`-truncation signature. The retry
    re-issues the same prompt with a corrective nudge appended; one
    extra call is cheap next to the already-billed reader fan-out it
    can rescue (ADR 0041).

    Args:
        user_prompt: The assembled synthesis prompt.
        system_prompt: The active system prompt (base or evidence path).

    Returns:
        The parsed response dict, guaranteed to carry a non-empty
        `draft_report` string.

    Raises:
        SynthesizerOutputError: Both attempts were unusable.
    """
    prompt = user_prompt
    for attempt in (1, 2):
        try:
            parsed = call_llm_json(
                prompt=prompt,
                system_prompt=system_prompt,
                model_name=settings.synthesizer_model or None,
                max_tokens=4096,
                cache_system=settings.enable_prompt_caching,
            )
        except json.JSONDecodeError as exc:
            log.warning(
                "synthesizer_response_unparseable",
                extra={"attempt": attempt, "error": str(exc)},
            )
            parsed = {}
        if str(parsed.get("draft_report") or "").strip():
            return parsed
        if attempt == 1:
            log.warning(
                "synthesizer_retrying_malformed_response",
                extra={"attempt": attempt},
            )
            prompt = f"{user_prompt}\n\n{_RETRY_NUDGE}"
    raise SynthesizerOutputError(
        "synthesizer produced no usable draft_report after one retry"
    )


def _parse_citations(raw: Any) -> list[Citation]:
    """Coerce the LLM's `citations` list, dropping malformed entries.

    Per-entry defense: one broken citation object costs that one
    citation, not the report. Dropped entries are logged at WARNING so
    a model drifting off-schema is visible in the run's logs.
    """
    if not isinstance(raw, list):
        if raw is not None:
            log.warning(
                "synthesizer_citations_not_a_list",
                extra={"raw_type": type(raw).__name__},
            )
        return []
    citations: list[Citation] = []
    dropped = 0
    for entry in raw:
        if not isinstance(entry, dict) or not str(entry.get("title") or "").strip():
            dropped += 1
            continue
        authors_raw = entry.get("authors")
        authors = (
            [str(a) for a in authors_raw] if isinstance(authors_raw, list) else []
        )
        citations.append(
            Citation(
                paper_id=str(entry.get("paper_id") or ""),
                title=str(entry.get("title") or "").strip(),
                authors=authors,
                year=str(entry.get("year") or ""),
                url=str(entry.get("url") or ""),
            )
        )
    if dropped:
        log.warning(
            "synthesizer_citations_dropped",
            extra={"dropped": dropped, "kept": len(citations)},
        )
    return citations


def synthesizer_agent(state: ResearchState) -> dict[str, Any]:
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

    Raises:
        SynthesizerOutputError: The LLM produced no usable
            `draft_report` on the original call or the single retry
            (ADR 0041).
    """
    evidence_path = _use_evidence_path(state)
    user_prompt = _build_user_prompt(state)
    system_prompt = EVIDENCE_SYSTEM_PROMPT if evidence_path else SYSTEM_PROMPT

    parsed = _call_with_one_retry(user_prompt, system_prompt)
    draft_report = str(parsed.get("draft_report") or "")
    citations = _parse_citations(parsed.get("citations"))

    if evidence_path:
        summary = (
            f"Synthesized report from {len(state.get('evidence', []))} "
            f"grounded claims with {len(citations)} citations."
        )
    else:
        summary = f"Synthesized report with {len(citations)} citations."

    return {
        "draft_report": draft_report,
        "citations": citations,
        "messages": [AIMessage(content=summary, name="synthesizer")],
    }
