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

When `settings.enable_evidence_store` is on, the same LLM call also
emits per-paper `EvidenceClaim`s. Each claim keeps a `source_text`
pointer back to the ranked chunk it came from so the verifier can
judge against real text instead of the paper's abstract. See ADR 0016.

When `settings.enable_reader_recovery` is on, the LLM also emits three
"do we have enough?" signals per paper (`analysis_complete`,
`missing_context`, `request_more_sections`); they get aggregated onto
state so the supervisor can pick `read` again with a narrower brief.
On the re-invocation, `rank_chunks_by_relevance` reserves slots for
chunks from the requested sections. See ADR 0019.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypedDict

from langchain_core.messages import AIMessage

from src.config import settings
from src.graph.state import (
    EvidenceClaim,
    PaperAnalysis,
    PaperMetadata,
    ResearchState,
)
from src.llm import call_llm_json
from src.observability import get_logger, propagate_run_context
from src.tools.chunk_ranker import RankedChunk, rank_chunks_by_relevance
from src.tools.chunker import chunk_paper
from src.tools.pdf_parser import parse_pdf

log = get_logger(__name__)

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


# ---------------------------------------------------------------------------
# Evidence store prompt — used only when `settings.enable_evidence_store` is on.
# Extends the analysis response with a `claims` list. Each claim carries a
# 1-based `chunk_index` that pins it to a specific ranked excerpt so the reader
# can resolve `source_text` deterministically after the call.
# ---------------------------------------------------------------------------

EVIDENCE_SYSTEM_PROMPT = """\
You are a research paper analysis assistant. Given a paper's title, abstract,
the research question's sub-questions, and (when available) ranked excerpts
from its full text, produce structured findings AND a list of evidence claims
grounded in specific excerpts.

Respond with valid JSON only, no markdown fencing:
{{
  "key_findings": ["finding 1", "finding 2", ...],
  "methodology": "brief description of the approach/method",
  "results_summary": "key quantitative or qualitative results",
  "limitations": "noted or inferred limitations",
  "relevance": 0.0 to 1.0 score for how relevant this paper is to the research question,
  "claims": [
    {{
      "claim": "a single factual assertion, paraphrase OK, one sentence",
      "chunk_index": 1,
      "supports_question": "one of the sub-questions verbatim, or empty string"
    }}
  ]
}}

Claim rules:
- Emit at most {max_claims} claims total across all excerpts.
- Every claim MUST reference the 1-based `chunk_index` of the excerpt it
  came from. Do NOT invent claims not present in the excerpts.
- A "factual claim" is something that could be true or false about the
  world — a method exists, a result was observed, a limitation applies.
  Skip framing / transitional prose.
- If none of the excerpts are relevant, return `"claims": []`. Do not
  reach for the abstract to fill quota.
- When a claim clearly answers one of the listed sub-questions, put
  that sub-question verbatim in `supports_question`; otherwise `""`.

For key_findings / methodology / results / limitations / relevance,
same rules as the base analysis prompt: pull directly from the text,
prefer excerpts over abstract, do not fabricate.
"""


# ---------------------------------------------------------------------------
# Recovery addendum — appended to whichever system prompt is in use when
# `settings.enable_reader_recovery` is on. Adds three "did we get enough?"
# fields to the response schema without duplicating the two base prompts.
# ADR 0019.
# ---------------------------------------------------------------------------

RECOVERY_ADDENDUM = """

Additionally, extend the JSON response with three fields the workflow's
supervisor will act on:
  "analysis_complete": true or false — whether the excerpts provided
    were enough to answer the sub-questions for THIS paper. Set false
    when key context (a specific section, a metric, a table) is
    missing.
  "missing_context": short string describing what's missing (empty
    when analysis_complete is true).
  "request_more_sections": list of section-name strings whose text
    would fill the gap ("results", "limitations", "experiments",
    "related work", ...). Empty list when analysis_complete is true
    or when you cannot name which sections to ask for.

If the abstract-only fallback was used ("Full text unavailable"),
analysis_complete MUST be false, missing_context should say "full
text unavailable", and request_more_sections should be empty.
"""


class ReaderRecoverySignal(TypedDict):
    """Per-paper "did we get enough?" signal (ADR 0019).

    Emitted only when `settings.enable_reader_recovery` is on. Under
    the base configuration the reader always returns a signal with
    `analysis_complete=True` so aggregators see a "nothing to
    recover from" default.
    """

    analysis_complete: bool
    missing_context: str
    request_more_sections: list[str]


def _default_signal() -> ReaderRecoverySignal:
    return ReaderRecoverySignal(
        analysis_complete=True,
        missing_context="",
        request_more_sections=[],
    )


def _parse_recovery_signal(parsed: dict[str, Any]) -> ReaderRecoverySignal:
    """Coerce the LLM's recovery fields into a safe `ReaderRecoverySignal`.

    Fail-open: any missing / wrong-typed field defaults to
    "analysis complete" so a broken response doesn't spuriously
    trigger a re-read loop.
    """
    complete_raw = parsed.get("analysis_complete")
    complete = complete_raw is True or complete_raw is None

    missing_raw = parsed.get("missing_context", "")
    missing = missing_raw.strip() if isinstance(missing_raw, str) else ""

    sections_raw = parsed.get("request_more_sections", [])
    sections: list[str] = []
    if isinstance(sections_raw, list):
        for item in sections_raw:
            if isinstance(item, str) and item.strip():
                sections.append(item.strip())

    # Consistency: if the model said complete but flagged a gap, trust
    # the gap and downgrade. Otherwise `analysis_complete` is a lie
    # from the supervisor's perspective.
    if complete and (missing or sections):
        complete = False

    if complete:
        missing = ""
        sections = []

    return ReaderRecoverySignal(
        analysis_complete=complete,
        missing_context=missing,
        request_more_sections=sections,
    )


def _gather_ranked_chunks(
    paper: PaperMetadata,
    subquestions: list[str],
    preferred_sections: list[str] | None = None,
) -> list[RankedChunk]:
    """Fetch, chunk, and rank the paper's full text.

    Returns the ranked chunks (up to `reader_max_chunks_per_paper`) or
    an empty list if any stage yields nothing. Callers treat `[]` as
    the signal to fall back to abstract-only analysis.

    `preferred_sections` (recovery path, ADR 0019) is passed through to
    the ranker so re-reads can promote chunks from sections the last
    read flagged as under-covered. `None` preserves the Sprint 1
    behavior.
    """
    full_text = parse_pdf(paper["pdf_url"])
    if not full_text:
        return []

    chunks = chunk_paper(full_text)
    if not chunks:
        return []

    ranked = rank_chunks_by_relevance(
        chunks,
        subquestions,
        top_k=settings.reader_max_chunks_per_paper,
        preferred_sections=preferred_sections,
    )
    return ranked or []


def _gather_context(paper: PaperMetadata, subquestions: list[str]) -> str:
    """Base-path excerpt block — unchanged format for baseline stability.

    Returns the ranked excerpts formatted as `[section] text` blocks
    separated by blank lines, or `""` if any pipeline stage yields
    nothing. Callers treat `""` as the signal to fall back to
    abstract-only analysis.
    """
    ranked = _gather_ranked_chunks(paper, subquestions)
    if not ranked:
        return ""
    return "\n\n".join(f"[{c['section']}] {c['text']}" for c in ranked)


def _format_numbered_chunks(ranked: list[RankedChunk]) -> str:
    """Evidence-path excerpt block: numbered so claims can pin `chunk_index`.

    Only used on the evidence-store path so the fixed-pipeline reader
    prompt stays byte-identical to Sprint 1's baseline.
    """
    return "\n\n".join(
        f"[{i}] [{c['section']}] {c['text']}"
        for i, c in enumerate(ranked, start=1)
    )


def _build_user_prompt(
    paper: PaperMetadata, query: str, context: str
) -> str:
    """Base-path user prompt — unchanged for baseline stability.

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


def _build_evidence_user_prompt(
    paper: PaperMetadata,
    query: str,
    subquestions: list[str],
    excerpts_block: str,
) -> str:
    """Evidence-path user prompt: adds sub-questions + numbered excerpts.

    The evidence path always has excerpts (claims are only extracted
    when `_gather_ranked_chunks` yielded chunks). Sub-questions are
    included so the LLM can attribute each claim to the one it
    answers.
    """
    parts = [
        f"Research question: {query}",
        "",
        f"Paper title: {paper['title']}",
        "",
        f"Abstract:\n{paper['abstract']}",
    ]
    if subquestions:
        parts.extend(
            [
                "",
                "Sub-questions the report should cover:",
                *(f"  - {q}" for q in subquestions),
            ]
        )
    parts.extend(
        [
            "",
            "Ranked excerpts from the paper's full text (numbered, section-tagged):",
            "",
            excerpts_block,
        ]
    )
    return "\n".join(parts)


def _parse_claim(
    raw: Any,
    paper_id: str,
    ranked: list[RankedChunk],
    subquestions: set[str],
) -> EvidenceClaim | None:
    """Convert one raw judge-emitted claim into a validated `EvidenceClaim`.

    Returns `None` when the claim is unusable — most commonly a
    missing / out-of-range `chunk_index` (which means we can't
    resolve `source_text` and the verifier would be judging air).
    Silent-drop is deliberate: a broken claim shouldn't crash the
    read, and paper-analysis output is still populated regardless.
    """
    if not isinstance(raw, dict):
        return None
    claim_text = str(raw.get("claim", "")).strip()
    if not claim_text:
        return None

    idx_raw = raw.get("chunk_index")
    try:
        idx_one_based = int(idx_raw)  # accepts int or str-ints
    except (TypeError, ValueError):
        return None
    idx = idx_one_based - 1
    if idx < 0 or idx >= len(ranked):
        return None
    chunk = ranked[idx]

    supports = str(raw.get("supports_question", "")).strip()
    # Only accept an attribution the planner actually asked for; anything
    # else gets dropped to "" so the field stays a trustworthy signal.
    if supports and supports not in subquestions:
        supports = ""

    return EvidenceClaim(
        claim=claim_text,
        paper_id=paper_id,
        section=chunk["section"],
        source_text=chunk["text"],
        relevance_score=float(chunk["relevance_score"]),
        supports_question=supports,
    )


def _analyze_paper(
    paper: PaperMetadata,
    query: str,
    subquestions: list[str],
    preferred_sections: list[str] | None = None,
) -> tuple[PaperAnalysis, list[EvidenceClaim], ReaderRecoverySignal]:
    """Produce a structured analysis (and, if enabled, evidence claims and
    a recovery signal).

    The evidence-store branch runs a slightly larger single LLM call
    (~ +512 output tokens for the claims list) rather than a second
    call, so per-paper cost stays close to the base path. When the
    ranked-chunks list is empty, evidence claims are always empty —
    we don't fabricate `source_text` from the abstract.

    Base-path prompts are kept byte-identical to the Sprint 1 baseline
    so `enable_evidence_store=False` and `enable_reader_recovery=False`
    runs are directly comparable to pre-flag results.

    `preferred_sections` (ADR 0019) is passed to the ranker so a
    supervisor-driven re-read can promote chunks from the sections the
    previous read flagged as under-covered.
    """
    ranked = _gather_ranked_chunks(paper, subquestions, preferred_sections)
    evidence_on = settings.enable_evidence_store and bool(ranked)
    recovery_on = settings.enable_reader_recovery

    if evidence_on:
        user_prompt = _build_evidence_user_prompt(
            paper, query, subquestions, _format_numbered_chunks(ranked)
        )
        system_prompt = EVIDENCE_SYSTEM_PROMPT.format(
            max_claims=settings.reader_max_claims_per_paper
        )
        max_tokens = 1536
    else:
        context = "\n\n".join(f"[{c['section']}] {c['text']}" for c in ranked)
        user_prompt = _build_user_prompt(paper, query, context)
        system_prompt = SYSTEM_PROMPT
        max_tokens = 1024

    if recovery_on:
        system_prompt = system_prompt + RECOVERY_ADDENDUM
        # Recovery fields add ~150 tokens to the response.
        max_tokens += 256

    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
    )

    analysis = PaperAnalysis(
        paper_id=paper["id"],
        title=paper["title"],
        key_findings=parsed["key_findings"],
        methodology=parsed["methodology"],
        results_summary=parsed["results_summary"],
        limitations=parsed["limitations"],
        relevance=float(parsed["relevance"]),
    )

    claims: list[EvidenceClaim] = []
    if evidence_on and ranked:
        raw_claims = parsed.get("claims", [])
        if not isinstance(raw_claims, list):
            raw_claims = []
        subq_set = {q for q in subquestions if q}
        cap = settings.reader_max_claims_per_paper
        for raw in raw_claims[:cap]:
            parsed_claim = _parse_claim(raw, paper["id"], ranked, subq_set)
            if parsed_claim is not None:
                claims.append(parsed_claim)

    if recovery_on:
        signal = _parse_recovery_signal(parsed)
        # Abstract-only path is always "not complete" from the reader's
        # own perspective, regardless of what the LLM said — full text
        # would still improve the analysis. Force the signal here so
        # the supervisor sees the truth.
        if not ranked:
            signal = ReaderRecoverySignal(
                analysis_complete=False,
                missing_context="full text unavailable",
                request_more_sections=[],
            )
    else:
        signal = _default_signal()

    return analysis, claims, signal


def _aggregate_recovery(
    papers: list[PaperMetadata],
    signals: list[ReaderRecoverySignal],
) -> tuple[bool, str, list[str]]:
    """Reduce per-paper recovery signals to workflow-level state.

    `analysis_complete` is the AND across papers (any incomplete paper
    means the workflow has work to recover from). `missing_context` is
    a semicolon-joined list of "<paper title>: <what's missing>" so the
    supervisor's state summary carries actionable text.
    `request_more_sections` is the deduped union (lowercase-key) so the
    ranker's re-invocation covers every requested section without
    repeating.
    """
    all_complete = True
    missing_parts: list[str] = []
    section_seen: set[str] = set()
    section_union: list[str] = []
    for paper, signal in zip(papers, signals, strict=True):
        if not signal["analysis_complete"]:
            all_complete = False
            if signal["missing_context"]:
                missing_parts.append(
                    f"{paper.get('title', '(untitled)')}: {signal['missing_context']}"
                )
        for section in signal["request_more_sections"]:
            key = section.strip().lower()
            if not key or key in section_seen:
                continue
            section_seen.add(key)
            section_union.append(section.strip())
    return all_complete, "; ".join(missing_parts), section_union


def reader_agent(state: ResearchState) -> dict:
    """Read each paper (full text when available, abstract otherwise) in parallel.

    Args:
        state: Current research workflow state with `papers` populated
            and (optionally) `sub_questions` for chunk ranking. When
            `settings.enable_reader_recovery` is on and
            `state.reader_requested_sections` is populated, the ranker
            reserves slots for chunks from those sections (ADR 0019).

    Returns:
        Partial state update with `paper_analyses`, `evidence` (only
        when `enable_evidence_store` is on), recovery signals (only
        when `enable_reader_recovery` is on), and a message.
    """
    papers = state["papers"]
    query = state["query"]
    subquestions = state.get("sub_questions", [])
    requested = (
        state.get("reader_requested_sections", [])
        if settings.enable_reader_recovery
        else []
    )
    preferred: list[str] | None = requested if requested else None

    # Propagate the parent's run_id + cost-accumulator ContextVars into
    # each worker thread — plain ThreadPoolExecutor doesn't inherit
    # context, so LLM calls from workers would otherwise lose per-run
    # attribution.
    analyze = propagate_run_context(
        lambda p: _analyze_paper(p, query, subquestions, preferred)
    )
    with ThreadPoolExecutor(max_workers=settings.reader_max_workers) as executor:
        results: list[
            tuple[PaperAnalysis, list[EvidenceClaim], ReaderRecoverySignal]
        ] = list(executor.map(analyze, papers))

    analyses: list[PaperAnalysis] = [a for a, _, _ in results]

    update: dict = {
        "paper_analyses": analyses,
    }
    if settings.enable_evidence_store:
        evidence: list[EvidenceClaim] = [c for _, cs, _ in results for c in cs]
        update["evidence"] = evidence
        summary = (
            f"Analyzed {len(analyses)} papers; extracted {len(evidence)} "
            f"evidence claims."
        )
    else:
        summary = f"Analyzed {len(analyses)} papers (full-text where available)."

    if settings.enable_reader_recovery:
        signals: list[ReaderRecoverySignal] = [s for _, _, s in results]
        complete, missing, sections = _aggregate_recovery(papers, signals)
        update["reader_analysis_complete"] = complete
        update["reader_missing_context"] = missing
        update["reader_requested_sections"] = sections
        if not complete:
            summary += (
                f" Recovery: {len(sections)} section(s) requested "
                f"({', '.join(sections) or 'none named'})."
            )
        else:
            summary += " Recovery: all papers reported complete."

    update["messages"] = [AIMessage(content=summary, name="reader")]
    return update
