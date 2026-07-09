"""Verifier agent — runtime faithfulness check between synthesis and critique.

Promotes ADR-0007's offline faithfulness judge into an in-loop node. The
same extract-and-judge shape (per-claim decisions against cited paper
abstracts) but the response also carries a `recommended_action` the
supervisor can consume to pick a recovery step.

The verifier is a **supervisor-only** node. Under the fixed pipeline it
is never invoked; under the supervisor loop it is only reachable when
`settings.enable_verifier` is true. The two flags are independent so
supervisor and verifier can be A/B'd separately against the Sprint 1
baseline — see ADR 0015.

Design invariants:
- **No new prompt engineering** — ADR-0007's calibrated faithfulness
  prompt is reused verbatim as the basis; only the response schema is
  extended with `recommended_action`.
- **Cheap failure mode** — an empty / near-empty draft short-circuits
  with `verified=True` and no recommendation before the LLM call, so
  invoking `verify` before synthesis costs nothing.
- **Malformed judge output is recoverable** — parse failures fall back
  to `verified=False, recommended_action="revise_report"` rather than
  raising, so the loop keeps moving.
"""

from typing import Any

from langchain_core.messages import AIMessage

from src.config import settings
from src.eval.metrics import build_source_index
from src.graph.state import Citation, EvidenceClaim, PaperMetadata, ResearchState
from src.llm import call_llm_json
from src.observability import get_logger

log = get_logger(__name__)

# Recovery actions the verifier can recommend. Values are what the
# supervisor sees in state; each maps to a next action the supervisor
# can pick (search_more -> search / plan, read_more -> read, revise ->
# synthesize). Kept explicit rather than reusing supervisor's enum so
# the verifier's recommendation surface stays intent-shaped ("what's
# wrong") not routing-shaped ("what to do next"). Supervisor prompt
# translates.
VALID_RECOMMENDATIONS: frozenset[str] = frozenset(
    {"read_more", "search_more", "revise_report", ""}
)


VERIFIER_SYSTEM_PROMPT = """\
You are a runtime faithfulness verifier for a research-writing agent.
Given a draft research report and source material for each cited
paper, extract every factual claim that carries an inline citation
and judge whether the source SUPPORTS it. Then diagnose the failure
mode and recommend a recovery action for the workflow's supervisor.

Source material comes in two shapes depending on what the reader
extracted:
  - **Source chunks** — verbatim excerpts from the paper's full text,
    tagged with their section and relevance. Judge against these
    when available; they are the strongest evidence.
  - **Abstract fallback** — only the paper's abstract, marked
    "abstract (no chunks available)". Judge more strictly here since
    abstracts are a lower bound on what the paper actually claims.

Definitions:
  - A "factual claim" is a statement that could be true or false about
    the world — a method exists, an approach works, a result was
    observed. Skip transitional prose, framing sentences, and generic
    background.
  - "Supported" means the source states or clearly implies the claim.
    Reasonable paraphrase is fine; adding facts absent from the source
    is NOT.
  - If a cited paper has neither chunks nor an abstract, treat every
    claim citing it as missing evidence.

Recovery actions:
  - "read_more": the abstract likely does support the claim but the
    reader/synthesizer missed key detail — deeper reading of the same
    papers should fix it.
  - "search_more": the retrieved papers do not cover the topic; new
    searches are needed to find supporting sources.
  - "revise_report": the report over-claims or misinterprets the
    evidence — the synthesizer should tighten the language.
  - Leave `recommended_action` empty when `verified` is true.

Return JSON only, no markdown fencing:
{
  "verified": true|false,
  "unsupported_claims": ["<claim text>", ...],
  "missing_evidence": ["<topic / sub-question lacking a cited source>", ...],
  "recommended_action": "read_more|search_more|revise_report|",
  "reason": "one-sentence overall diagnosis"
}

Set `verified=true` ONLY when every cited claim is supported AND no
listed sub-question is missing evidence. Otherwise `verified=false`
and pick the single most impactful recovery action.
"""


def _paper_cite_lastname(paper: PaperMetadata) -> str:
    """First-author lowercased last name, or empty if unresolvable.

    Same normalization as `build_source_index` so the two dossier
    builders agree on which papers map to which cite keys.
    """
    authors = paper.get("authors", [])
    if not authors or not authors[0].strip():
        return ""
    return authors[0].strip().split()[-1].lower()


def _dossier_from_evidence(
    papers: list[PaperMetadata],
    citations: list[Citation],
    evidence: list[EvidenceClaim],
) -> str:
    """Build a `[Author, Year]`-keyed dossier from evidence claims.

    Groups evidence by paper_id, resolves each to its cite key against
    the citation list (same key shape as `build_source_index`), and
    emits one block per paper with all its evidence source_text
    chunks. Falls back to the abstract for cited papers that have no
    evidence claims (partial coverage) — that's the same conservative
    behavior as the abstract-only path.
    """
    year_by_id: dict[str, str] = {}
    for citation in citations:
        year = citation["year"].strip()[:4]
        if year:
            year_by_id[citation["paper_id"]] = year

    paper_by_id: dict[str, PaperMetadata] = {p["id"]: p for p in papers}

    evidence_by_paper: dict[str, list[EvidenceClaim]] = {}
    for claim in evidence:
        evidence_by_paper.setdefault(claim["paper_id"], []).append(claim)

    blocks: list[str] = []
    for paper_id, year in year_by_id.items():
        paper = paper_by_id.get(paper_id)
        if paper is None:
            continue
        lastname = _paper_cite_lastname(paper)
        if not lastname:
            continue
        cite_key = f"[{lastname.title()}, {year}]"

        claims_for_paper = evidence_by_paper.get(paper_id, [])
        if claims_for_paper:
            chunk_blocks = [
                f"({c['section']}, relevance={c['relevance_score']:.2f})\n{c['source_text']}"
                for c in claims_for_paper
            ]
            body = "\n\n".join(chunk_blocks)
            blocks.append(f"{cite_key} — source chunks:\n{body}\n")
        else:
            # Cited paper has no evidence claims (e.g. reader couldn't
            # fetch its PDF). Fall back to the abstract so the judge
            # isn't left blind on that paper.
            blocks.append(
                f"{cite_key} — abstract (no chunks available):\n{paper['abstract']}\n"
            )

    return "\n".join(blocks) or "(no cited papers with sources available)"


def _build_user_prompt(state: ResearchState) -> str:
    """Assemble the user message: report + cited-paper dossier + sub-questions.

    Two dossier shapes:
      - **Evidence path** (`enable_evidence_store=True` and `state.evidence`
        populated): dossier lists the actual ranked chunks the reader
        used, keyed by `[Author, Year]`. Judge decides against real
        text — the ADR-0007 abstract limitation is closed here.
      - **Abstract path** (default): uses `build_source_index` from
        `src.eval.metrics` so the runtime and offline judges agree on
        the abstract-only substrate.
    """
    report = state.get("draft_report", "")
    papers = state.get("papers", [])
    citations = state.get("citations", [])
    sub_questions = state.get("sub_questions", [])
    evidence = state.get("evidence", [])

    if settings.enable_evidence_store and evidence:
        dossier = _dossier_from_evidence(papers, citations, evidence)
        dossier_label = "Cited papers (ranked source chunks):"
    else:
        source_index = build_source_index(papers, citations)
        dossier_lines: list[str] = []
        for (lastname, year), abstract in source_index.items():
            cite_key = f"[{lastname.title()}, {year}]"
            dossier_lines.append(f"{cite_key}\n{abstract}\n")
        dossier = "\n".join(dossier_lines) or "(no cited papers with abstracts available)"
        dossier_label = "Cited papers (abstracts):"

    sub_q_lines = "\n".join(f"  - {q}" for q in sub_questions) or "  (none)"

    return (
        f"Research question: {state.get('query', '(unknown)')}\n\n"
        f"Sub-questions the report should cover:\n{sub_q_lines}\n\n"
        f"Draft report:\n\n{report}\n\n"
        f"{dossier_label}\n\n{dossier}"
    )


def _coerce_string_list(value: Any) -> list[str]:
    """Coerce a judge-returned field to a list of non-empty strings, safely."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _clean_recommendation(value: Any) -> str:
    """Coerce recommendation to a validated enum value; unknown -> empty."""
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    if normalized in VALID_RECOMMENDATIONS:
        return normalized
    return ""


def _empty_result(reason: str) -> dict[str, Any]:
    """Partial-state update for a no-work verification (empty draft, etc.)."""
    return {
        "verified": True,
        "unsupported_claims": [],
        "missing_evidence": [],
        "verifier_recommendation": "",
        "messages": [
            AIMessage(content=f"verifier -> skipped: {reason}", name="verifier")
        ],
    }


def _fallback_result(reason: str) -> dict[str, Any]:
    """Partial-state update when the judge output can't be trusted.

    Conservative default: `verified=False, recommended_action="revise_report"`.
    That routes the supervisor to another synthesis pass rather than
    blocking the loop or letting an unverified draft slip through.
    """
    return {
        "verified": False,
        "unsupported_claims": [],
        "missing_evidence": [],
        "verifier_recommendation": "revise_report",
        "messages": [
            AIMessage(
                content=f"verifier -> fallback (revise_report): {reason}",
                name="verifier",
            )
        ],
    }


def verifier_agent(state: ResearchState) -> dict[str, Any]:
    """Judge the draft report's faithfulness and recommend recovery.

    Reads: `draft_report`, `papers`, `citations`, `sub_questions`,
    `query`. Writes: `verified`, `unsupported_claims`, `missing_evidence`,
    `verifier_recommendation`, plus a message.

    Runs a single LLM call. Cost-tracked via `call_llm_json`. Cost/
    iteration caps are enforced by the supervisor before this node is
    reached, so no budget check here.

    Args:
        state: Full `ResearchState`. Must have a populated
            `draft_report` for the verification to run; empty drafts
            short-circuit with `verified=True`.

    Returns:
        Partial state update — see field list above.
    """
    report = state.get("draft_report", "")
    if not report.strip():
        return _empty_result("no draft to verify")

    if not state.get("citations"):
        # A report with no citations has nothing verifiable in ADR-0007's
        # frame. Flag it but don't block — the critic will catch it.
        return _empty_result("draft has no citations")

    user_prompt = _build_user_prompt(state)

    try:
        parsed = call_llm_json(
            prompt=user_prompt,
            system_prompt=VERIFIER_SYSTEM_PROMPT,
            model_name=settings.verifier_model or None,
            max_tokens=2048,
            cache_system=settings.enable_prompt_caching,
        )
    except Exception as exc:  # noqa: BLE001 — recoverable, log + fallback
        log.warning(
            "verifier_llm_failed_fallback",
            extra={"error": str(exc)},
        )
        return _fallback_result(f"LLM call failed ({type(exc).__name__})")

    verified_raw = parsed.get("verified")
    verified = verified_raw is True  # anything non-True -> False

    unsupported = _coerce_string_list(parsed.get("unsupported_claims"))
    missing = _coerce_string_list(parsed.get("missing_evidence"))
    recommendation = _clean_recommendation(parsed.get("recommended_action"))

    # If judge said verified=True but flagged issues, downgrade to False —
    # verified must mean "no follow-up needed".
    if verified and (unsupported or missing):
        verified = False

    # If not verified but no recommendation, pick a sensible default.
    if not verified and not recommendation:
        if missing and not unsupported:
            recommendation = "search_more"
        elif unsupported:
            recommendation = "revise_report"

    # If verified, drop any lingering recommendation.
    if verified:
        recommendation = ""

    reason = str(parsed.get("reason", "")).strip() or "(no reason given)"
    summary = (
        f"verified={verified}, unsupported={len(unsupported)}, "
        f"missing={len(missing)}, action={recommendation or 'none'} — {reason}"
    )

    return {
        "verified": verified,
        "unsupported_claims": unsupported,
        "missing_evidence": missing,
        "verifier_recommendation": recommendation,
        "messages": [
            AIMessage(content=f"verifier -> {summary}", name="verifier")
        ],
    }
