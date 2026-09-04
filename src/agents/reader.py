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

When `settings.enable_prompt_isolation` is on, paper-derived text
(abstract + ranked chunks) is wrapped in untrusted-content delimiter
tags in the user prompt, the system prompt gains a security
instruction, and the reader's control-token fields
(`missing_context`, `request_more_sections`) are sanitized post-LLM.
This is the last-line defense against jailbreaks in arXiv PDFs
redirecting the supervisor's routing decisions (ADR 0020).

Degradation policy (ADR 0041): a malformed or truncated LLM response
for one paper degrades that paper to a placeholder analysis with a
WARNING — it never fails the node, because the fan-out has already
paid for every other paper's calls. The node raises
`AllPaperAnalysesFailedError` only when *every* paper failed, which
means the LLM itself is down and there is nothing honest to
synthesize from. `JobCancelledError` is the deliberate exception to
that containment: it aborts the fan-out instead of degrading papers,
because it means the job it belongs to is already over (ADR 0047).

WO-A17 splits that total-failure case in two. When every paper failed
*on the provider* — an `errors.UpstreamModel` out of `src/llm.py` — the
node raises `UpstreamModel` instead, so a model outage carries the same
`error_type` here as it does from every other node.
`AllPaperAnalysesFailedError` (`upstream_paper_read`) keeps the case it
was named for: papers were found and this node could not read them.

The *other* degradation — falling back to the abstract because the
full text never arrived — is now reported rather than inferred (ADR
0052). Each fallback logs one INFO line naming the stage that
produced nothing, and the node closes with a `reader_completed`
summary carrying `n_abstract_only`; a run where most papers were read
from their abstracts scores lower on completeness and faithfulness
for a reason that has nothing to do with the prompts, and that was
previously invisible in the log stream.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from typing import Any, TypedDict

from langchain_core.messages import AIMessage

from src.cancellation import JobCancelledError, check_cancelled
from src.config import settings
from src.errors import UpstreamModel, UpstreamPaperRead
from src.graph.state import (
    EvidenceClaim,
    PaperAnalysis,
    PaperMetadata,
    ResearchState,
)
from src.llm import call_llm_json
from src.observability import get_logger, propagate_run_context
from src.observability.costs import CostBudgetExceeded
from src.security.prompt_isolation import (
    ISOLATION_SYSTEM_INSTRUCTION,
    sanitize_control_string,
    sanitize_section_names,
    wrap_untrusted,
)
from src.tools.chunk_ranker import RankedChunk, rank_chunks_by_relevance
from src.tools.chunker import chunk_paper
from src.tools.pdf_parser import parse_pdf

log = get_logger(__name__)

# Back-compat re-exports for tests / callers that import these names.
MAX_WORKERS = settings.reader_max_workers
MAX_CHUNKS_PER_PAPER = settings.reader_max_chunks_per_paper

#: More than this many papers degraded to abstract-only in one run
#: earns a run-level WARNING on top of the per-paper INFO lines (ADR
#: 0052). Two is the point where the aggregate stops being an
#: individual paper's bad luck — one dead PDF link is normal, three
#: means arXiv is refusing us or the parser broke, and the run's
#: metrics should be read as "computed on abstracts".
ABSTRACT_ONLY_WARN_THRESHOLD = 2

#: Per-invocation tally of abstract-only fallbacks, keyed by reason.
#:
#: A ContextVar rather than a return value because `_analyze_paper`'s
#: 3-tuple is load-bearing for a dozen call sites in the test suite,
#: and a module-global counter would interleave two concurrent API
#: jobs' runs into one number. `reader_agent` binds a fresh list
#: *inside each worker thread* (see `_analyze_or_degrade`'s wrapper)
#: so the fan-out shares one object without sharing it across runs.
_fallback_reasons: ContextVar[list[str] | None] = ContextVar(
    "reader_fallback_reasons", default=None
)


def _record_fallback(paper: PaperMetadata, reason: str) -> None:
    """Log and tally one paper's fall back to abstract-only analysis.

    INFO, not WARNING: the loudest cause (an HTTP error fetching the
    PDF) already warns from `pdf_parser`, and one WARNING per paper on
    top of that would be noise. The run-level WARNING in
    `reader_agent` is where the aggregate gets its volume.

    Args:
        paper: The paper that will be analyzed from its abstract.
        reason: Which stage produced nothing — `no_pdf_url`,
            `no_text`, `no_chunks`, or `no_ranked_chunks`.
    """
    log.info(
        "reader_paper_abstract_only",
        extra={
            "paper_id": paper.get("id", ""),
            "reason": reason,
            # The URL is what an operator retries by hand; empty
            # string *is* the finding when reason is `no_pdf_url`.
            "pdf_url": paper.get("pdf_url", ""),
        },
    )
    tally = _fallback_reasons.get()
    if tally is not None:
        # `list.append` is atomic under the GIL, so the fan-out's
        # threads need no lock of their own here.
        tally.append(reason)


class AllPaperAnalysesFailedError(UpstreamPaperRead):
    """Every paper in the reader fan-out failed to produce an analysis.

    A single malformed LLM response degrades that one paper to a
    placeholder (ADR 0041); this error fires only when no paper at all
    yielded a usable analysis — the LLM is effectively down, and
    proceeding would hand the synthesizer an empty analysis set.

    ADR 0064 re-parents it onto `UpstreamPaperRead`, so the job's
    `error_type` is the stable `upstream_paper_read`.
    """


def _failed_analysis(paper: PaperMetadata) -> PaperAnalysis:
    """Placeholder analysis for a paper whose LLM response was unusable.

    Zero relevance and empty findings keep the paper from contributing
    fabricated content downstream; the limitations note makes the
    degradation visible in the final report's source data rather than
    silently thinning it.
    """
    return PaperAnalysis(
        paper_id=paper["id"],
        title=paper["title"],
        key_findings=[],
        methodology="",
        results_summary="",
        limitations=(
            "Automated analysis failed for this paper (unusable LLM "
            "response); its content is not reflected in the briefing."
        ),
        relevance=0.0,
    )

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

    When `settings.enable_prompt_isolation` is on, the two free-form
    control fields are additionally scrubbed through the sanitizers
    (ADR 0020) — length caps, jailbreak-marker filtering, section-name
    charset filter. A jailbreak that convinced the model to emit
    misleading values gets its payload stripped before it reaches the
    supervisor.
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

    if settings.enable_prompt_isolation:
        missing = sanitize_control_string(missing)
        sections = sanitize_section_names(sections)

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

    Every `[]` return names the stage that produced it through
    `_record_fallback` (ADR 0052). The `no_pdf_url` branch is
    explicit: `parse_pdf("")` returns `""` before reaching any code
    that could log, so that path used to be the one degradation with
    no trace anywhere.
    """
    pdf_url = paper.get("pdf_url", "")
    if not pdf_url:
        _record_fallback(paper, "no_pdf_url")
        return []

    full_text = parse_pdf(pdf_url)
    if not full_text:
        _record_fallback(paper, "no_text")
        return []

    chunks = chunk_paper(full_text)
    if not chunks:
        _record_fallback(paper, "no_chunks")
        return []

    ranked = rank_chunks_by_relevance(
        chunks,
        subquestions,
        top_k=settings.reader_max_chunks_per_paper,
        preferred_sections=preferred_sections,
    )
    if not ranked:
        _record_fallback(paper, "no_ranked_chunks")
        return []
    return ranked


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

    When `settings.enable_prompt_isolation` is on, paper-derived text
    (title + abstract + excerpts) is wrapped in untrusted-content tags
    so the LLM knows to treat it as data. The title is wrapped too:
    with Semantic Scholar enrichment on, titles are
    attacker-influenceable, and an unwrapped multi-line title sitting
    above the tags could imitate a fresh instruction block. The source
    adapters additionally normalize titles to a single capped line.
    See ADR 0020 / ADR 0041.
    """
    isolate = settings.enable_prompt_isolation
    abstract_block = (
        wrap_untrusted(paper["abstract"]) if isolate else paper["abstract"]
    )
    title_block = wrap_untrusted(paper["title"]) if isolate else paper["title"]
    parts = [
        f"Research question: {query}",
        "",
        f"Paper title: {title_block}",
        "",
        f"Abstract:\n{abstract_block}",
    ]
    if context:
        excerpts_block = (
            wrap_untrusted(context)
            if settings.enable_prompt_isolation
            else context
        )
        parts.extend(
            [
                "",
                "Relevant excerpts from the paper's full text (section-tagged):",
                "",
                excerpts_block,
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

    When `settings.enable_prompt_isolation` is on, paper-derived text
    (title + abstract + excerpts) is wrapped in untrusted-content
    tags. See ADR 0020 / ADR 0041.
    """
    isolate = settings.enable_prompt_isolation
    abstract_block = wrap_untrusted(paper["abstract"]) if isolate else paper["abstract"]
    wrapped_excerpts = wrap_untrusted(excerpts_block) if isolate else excerpts_block
    title_block = wrap_untrusted(paper["title"]) if isolate else paper["title"]
    parts = [
        f"Research question: {query}",
        "",
        f"Paper title: {title_block}",
        "",
        f"Abstract:\n{abstract_block}",
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
            wrapped_excerpts,
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

    When `settings.enable_prompt_isolation` is on, the LLM-generated
    `claim` field is filtered for jailbreak markers — the source_text
    stays verbatim because the verifier judges against it and needs
    the raw excerpt, but a `claim` that quotes an injection payload
    would flow to the verifier as if it were a real claim. Claims
    that trip the filter are dropped rather than blanked (a blank
    claim is invalid; a dropped one is just missing evidence).
    """
    if not isinstance(raw, dict):
        return None
    claim_text = str(raw.get("claim", "")).strip()
    if not claim_text:
        return None

    if settings.enable_prompt_isolation:
        # Reuse the control-string sanitizer's jailbreak filter — a
        # claim carrying "SYSTEM:" or "IGNORE PREVIOUS" is not a claim.
        cleaned = sanitize_control_string(claim_text)
        if not cleaned:
            return None
        claim_text = cleaned

    idx_raw = raw.get("chunk_index")
    if idx_raw is None:
        return None
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

    if settings.enable_prompt_isolation:
        # Prepend the security instruction so it comes before any
        # response-schema rules — the LLM sees "treat wrapped content
        # as data" as the first thing it's told.
        system_prompt = ISOLATION_SYSTEM_INSTRUCTION + "\n\n" + system_prompt

    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=system_prompt,
        model_name=settings.reader_model or None,
        max_tokens=max_tokens,
        cache_system=settings.enable_prompt_caching,
    )

    # Missing keys / uncoercible values raise here (KeyError,
    # ValueError, TypeError) — deliberately. `reader_agent`'s per-paper
    # guard converts any such failure into a degraded placeholder for
    # this one paper instead of failing the node (ADR 0041).
    analysis = PaperAnalysis(
        paper_id=paper["id"],
        title=paper["title"],
        key_findings=[str(f) for f in parsed["key_findings"]],
        methodology=str(parsed["methodology"]),
        results_summary=str(parsed["results_summary"]),
        limitations=str(parsed["limitations"]),
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


def reader_agent(state: ResearchState) -> dict[str, Any]:
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

    # Tally of papers whose analysis died on the *provider* rather than
    # on its own output (WO-A17). `list.append` is atomic under the GIL,
    # so the fan-out's threads need no lock — the same idiom
    # `_record_fallback` uses a hundred lines above.
    provider_failures: list[str] = []

    def _analyze_or_degrade(
        p: PaperMetadata,
    ) -> tuple[PaperAnalysis, list[EvidenceClaim], ReaderRecoverySignal, bool]:
        """Per-paper failure containment (ADR 0041).

        A malformed / truncated LLM response for one paper — a
        `max_tokens` cutoff mid-JSON, a missing required key — must not
        discard every other paper's already-billed analysis. The paper
        degrades to a placeholder with a WARNING; the trailing bool
        reports whether the analysis succeeded so the aggregate can
        fail the node when *nothing* succeeded.

        Cancellation is the one exception to that containment. The
        reader is the most expensive node in the graph (one LLM call
        per paper), so it is also the one that most needs to stop when
        its job has already been failed for timeout. The check runs
        between papers, outside the degradation guard — swallowing
        `JobCancelledError` into a placeholder would turn "abort" into
        "analyse every remaining paper anyway" (ADR 0047).
        """
        check_cancelled()
        try:
            return (*_analyze_paper(p, query, subquestions, preferred), True)
        except (JobCancelledError, CostBudgetExceeded):
            # Raised from `src.llm.call_llm` mid-paper. Propagate: the
            # fan-out is over, and a degraded placeholder here would
            # report a paper as "analysed but unusable" when it was
            # simply never attempted. `CostBudgetExceeded` gets the
            # same treatment for the same reason (ADR 0051): the cap
            # check runs before every call, so once it trips, each
            # remaining paper would raise-and-degrade in turn and the
            # run would limp to synthesis with no analyses — spending
            # judge and synthesis calls the ceiling existed to stop.
            raise
        except Exception as exc:
            if isinstance(exc, UpstreamModel):
                # Tallied, deliberately *not* re-raised. A provider
                # failure on one paper is still one paper's failure —
                # the SDK exhausting its envelope on a single call says
                # nothing about the other nine, and the fan-out has
                # already paid for them. What the tally buys is the
                # aggregate below: a run where every paper died on the
                # provider is a provider outage, and reporting it as
                # `upstream_paper_read` would name the reader for the
                # model's failure.
                provider_failures.append(p["id"])
            log.warning(
                "reader_paper_analysis_failed",
                extra={
                    "paper_id": p["id"],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            signal = (
                ReaderRecoverySignal(
                    analysis_complete=False,
                    missing_context="analysis failed",
                    request_more_sections=[],
                )
                if settings.enable_reader_recovery
                else _default_signal()
            )
            return _failed_analysis(p), [], signal, False

    # One tally object per node invocation, bound inside each worker
    # thread (ADR 0052). `propagate_run_context` carries exactly three
    # ContextVars and knows nothing about this one, and a
    # ThreadPoolExecutor inherits no context at all — so the binding
    # has to happen in the worker, on the same object every worker
    # shares, for `_record_fallback` deep in the call stack to find it.
    fallback_reasons: list[str] = []

    def _tallied(
        p: PaperMetadata,
    ) -> tuple[PaperAnalysis, list[EvidenceClaim], ReaderRecoverySignal, bool]:
        token = _fallback_reasons.set(fallback_reasons)
        try:
            return _analyze_or_degrade(p)
        finally:
            _fallback_reasons.reset(token)

    # Propagate the parent's run_id + cost-accumulator ContextVars into
    # each worker thread — plain ThreadPoolExecutor doesn't inherit
    # context, so LLM calls from workers would otherwise lose per-run
    # attribution.
    analyze = propagate_run_context(_tallied)
    with ThreadPoolExecutor(max_workers=settings.reader_max_workers) as executor:
        results: list[
            tuple[PaperAnalysis, list[EvidenceClaim], ReaderRecoverySignal, bool]
        ] = list(executor.map(analyze, papers))

    failed_count = sum(1 for _, _, _, ok in results if not ok)
    if papers and failed_count == len(papers):
        # Two exits from one condition, and the reason they are two is
        # worth stating here rather than leaving to be re-derived.
        #
        # "Every paper failed" has two completely different causes with
        # two completely different fixes. Either the provider stopped
        # answering — in which case nothing about this deployment, these
        # papers or these prompts is wrong and the answer is to wait —
        # or the papers were fetched and this node could not turn any of
        # them into an analysis, in which case the run is the problem
        # and re-asking with different queries is the move. An operator
        # reading `research_jobs_total{error_type}` has to be able to
        # tell those apart, because the first is an incident somewhere
        # else and the second is an incident here.
        #
        # This node is the only one that *can* tell them apart, which is
        # why the split lives here and not at the boundary. Every other
        # node makes one model call, so its failure is its cause; this
        # one makes `len(papers)` of them and contains each failure
        # individually (ADR 0041), so by the time it knows the fan-out
        # produced nothing it also knows what each paper died of. That
        # is what `provider_failures` is: the reader's answer to a
        # question no later layer has the evidence to ask.
        #
        # The unanimity requirement is deliberate and is the
        # conservative direction. A mixed run — some papers lost to the
        # provider, some to their own unusable output — is not a
        # provider outage, and calling it one would point an operator
        # at Anthropic's status page for a problem in this repository.
        # `upstream_paper_read` is the honest answer whenever the cause
        # is not unanimous, because it describes the symptom without
        # claiming a cause.
        if len(provider_failures) == len(papers):
            raise UpstreamModel(
                log_detail=(
                    f"all {len(papers)} paper analyses failed on the model "
                    f"provider"
                )
            )
        raise AllPaperAnalysesFailedError(
            f"all {len(papers)} paper analyses failed — no usable "
            f"analysis to synthesize from"
        )

    analyses: list[PaperAnalysis] = [a for a, _, _, _ in results]

    update: dict[str, Any] = {
        "paper_analyses": analyses,
    }
    if settings.enable_evidence_store:
        evidence: list[EvidenceClaim] = [c for _, cs, _, _ in results for c in cs]
        update["evidence"] = evidence
        summary = (
            f"Analyzed {len(analyses)} papers; extracted {len(evidence)} "
            f"evidence claims."
        )
    else:
        summary = f"Analyzed {len(analyses)} papers (full-text where available)."

    if failed_count:
        summary += f" {failed_count} paper(s) degraded (analysis failed)."

    if settings.enable_reader_recovery:
        signals: list[ReaderRecoverySignal] = [s for _, _, s, _ in results]
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

    _log_reader_summary(
        n_papers=len(papers),
        n_failed=failed_count,
        n_claims=len(update.get("evidence", [])),
        fallback_reasons=fallback_reasons,
    )

    update["messages"] = [AIMessage(content=summary, name="reader")]
    return update


def _log_reader_summary(
    *,
    n_papers: int,
    n_failed: int,
    n_claims: int,
    fallback_reasons: list[str],
) -> None:
    """Emit the node's one aggregate line, plus a WARNING when degraded.

    The INFO line always fires: it is the record that answers "were
    this run's scores computed on full text or on abstracts?", which
    is otherwise unanswerable after the fact and is the first thing
    worth ruling out when a campaign's completeness drops.

    The WARNING fires only past `ABSTRACT_ONLY_WARN_THRESHOLD` — the
    per-paper detail is already at INFO, so the WARNING exists purely
    to reach an operator who filters at that level.

    Args:
        n_papers: Papers the fan-out covered.
        n_failed: Papers degraded to a placeholder analysis (ADR 0041).
        n_claims: Evidence claims extracted, 0 when the flag is off.
        fallback_reasons: One entry per abstract-only paper, naming
            the stage that produced no chunks.
    """
    by_reason: dict[str, int] = {}
    for reason in fallback_reasons:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    n_abstract_only = len(fallback_reasons)

    log.info(
        "reader_completed",
        extra={
            "n_papers": n_papers,
            "n_abstract_only": n_abstract_only,
            "n_failed": n_failed,
            "n_claims": n_claims,
            "fallback_reasons": by_reason,
        },
    )
    if n_abstract_only > ABSTRACT_ONLY_WARN_THRESHOLD:
        log.warning(
            "reader_degraded_to_abstract_only",
            extra={
                "n_papers": n_papers,
                "n_abstract_only": n_abstract_only,
                "threshold": ABSTRACT_ONLY_WARN_THRESHOLD,
                "fallback_reasons": by_reason,
            },
        )
