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

Mock mode (ADR 0080): under `settings.use_mock_data` the briefing is
assembled by `src.agents.mock_mode` from the state's own papers,
analyses and evidence, and no model client is constructed. Its first
line is `mock_mode.MOCK_BANNER`, so a mock report can never be read as
a real one — the report is the artefact that gets exported,
checkpointed and pasted elsewhere, so the label travels in the document
rather than only in a log line. Both prompt paths have a mock
counterpart; the citation surfaces are identical on either, so the two
score the same.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any, Final

from langchain_core.messages import AIMessage

from src.agents import mock_mode
from src.config import settings
from src.errors import UpstreamModelOutput
from src.graph.state import Citation, EvidenceClaim, ResearchState
from src.llm import _retry_envelope, call_llm_json
from src.observability import get_logger

log = get_logger(__name__)

#: Share of `api_job_timeout_sec` this node's *pair* of attempts may
#: occupy in the worst case. The same 0.75 `src/llm.py` gives a single
#: model call chain: the synthesizer is one node of five, but it is the
#: node that produces the deliverable, and a share below the model's own
#: would refuse the corrective retry on every deployment — which would
#: be deleting the recovery rather than bounding it.
_RETRY_BUDGET_FRACTION: Final = 0.75

#: Claims one repair block may list. A verifier that flags more than ten
#: unsupported claims has rejected the report rather than found faults in
#: it, and a prompt that listed all of them would be asking for a rewrite
#: under the name of a repair (ADR 0076).
_MAX_REPAIR_CLAIMS: Final = 10


def _worst_case_call_sec() -> float:
    """Wall clock one `call_llm_json` can burn before it gives up.

    Reads `src.llm._retry_envelope` — a private name, imported rather
    than re-derived on purpose. The number this function needs is
    whatever the SDK client was actually *constructed* with, and a
    second copy of that arithmetic would agree with it right up until
    someone changed one of them. `admin_migrate` reaches into
    `postgres_pool._connection` for the same reason: the seam is
    private to discourage callers, not to hide a fact.

    Returns:
        `(max_retries + 1) * timeout_sec`, the SDK applying its timeout
        per attempt rather than per call chain.
    """
    max_retries, timeout_sec = _retry_envelope()
    return (max_retries + 1) * timeout_sec


def _second_attempt_fits(elapsed_sec: float) -> bool:
    """True when a corrective retry still fits inside the job's budget.

    ADR 0068 follow-up 3. `src/llm.py` clamps *one* call chain against
    `api_job_timeout_sec`; it cannot see that this node makes the call
    twice, and 2 x 5 x 120s against a 600s job was the worst case that
    arithmetic left open. The retry survived WO-A04's consolidation
    because it is a *semantic* retry — a different prompt, not the same
    request, and the only thing that rescues a `max_tokens` truncation
    — so the fix is to bound it, not to remove it.

    Bounded against the time already spent rather than against the
    static pair, because the pair's worst case is not what a healthy
    run costs: a first attempt that returned in nine seconds leaves
    almost the whole budget, and refusing the retry there would trade a
    recoverable report for an arithmetic that never happened.

    Args:
        elapsed_sec: Wall clock the first attempt actually took.

    Returns:
        Whether to issue the second call.
    """
    budget_sec = settings.api_job_timeout_sec * _RETRY_BUDGET_FRACTION
    worst_case_sec = _worst_case_call_sec()
    if elapsed_sec + worst_case_sec <= budget_sec:
        return True
    # WARNING for the reason `src/llm.py` logs its own clamp at WARNING:
    # the run is about to fail with `upstream_model_output` and the
    # recovery that would have been tried was skipped by a budget, not
    # by the model. Without this line the shape of the incident ("why
    # did it not retry?") is unanswerable.
    log.warning(
        "synthesizer_retry_budget_exhausted",
        extra={
            "elapsed_sec": round(elapsed_sec, 1),
            "budget_sec": budget_sec,
            "worst_case_request_sec": worst_case_sec,
        },
    )
    return False


class SynthesizerOutputError(UpstreamModelOutput):
    """The synthesizer produced no usable draft report, even after a retry.

    Raised when both the original call and the single corrective retry
    yielded unparseable JSON or an empty `draft_report`. The failure
    reads as what it is — a synthesis output failure — rather than a
    generic `JSONDecodeError` (ADR 0041), and since ADR 0064 it reaches
    the job as the stable code `upstream_model_output`.
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


def _repair_instruction(state: ResearchState) -> str:
    """The `qualify_or_remove_claims` repair block, or nothing at all.

    ADR 0076's second repair. It is an additional **user**-prompt block
    and never a change to either system prompt: prompt text is the
    instrument the first policy experiment measures with, and rewording
    it re-baselines every faithfulness number that has ever been
    recorded (ADR 0070). So the repair arrives the way a critique
    already does — as context for this one call.

    Gated on `repair_action`, which only `src/policies/repair.py` writes
    and only under `research_policy="fixed_verify_repair"`. Under every
    other configuration the key is absent from the state and this
    returns the empty string, which is what keeps the shipped prompt
    byte-identical.

    Args:
        state: Current state, after the repair node ran.

    Returns:
        The block, or `""` when no claim repair is in force.
    """
    if state.get("repair_action") != "qualify_or_remove_claims":
        return ""
    claims = [
        claim.strip()
        for claim in state.get("unsupported_claims", [])
        if isinstance(claim, str) and claim.strip()
    ]
    if not claims:
        return ""
    listed = "\n".join(f"  - {claim}" for claim in claims[:_MAX_REPAIR_CLAIMS])
    return (
        "\nVerification repair — the runtime verifier could not find "
        "support for the following claims in the material above:\n"
        f"{listed}\n"
        "\nRewrite the briefing so that each of those claims is either "
        "qualified to exactly what a listed source supports or removed. "
        "Change nothing else: keep the same structure, the same sections "
        "and the same citations, and do not introduce new claims."
    )


def _build_user_prompt(state: ResearchState) -> str:
    """Build the user message; shape depends on `_use_evidence_path`.

    The base path stays byte-identical to the Sprint 1 baseline.
    The evidence path keeps the base analyses block for context and
    APPENDS the grounded evidence bank — analyses give the LLM the
    "shape" of each paper (methodology / limitations), while the
    evidence block is what it's allowed to draw factual claims from.

    A third, optional block closes the prompt when the fixed
    verify-and-repair policy selected a claim repair — last, because it
    is the instruction for *this* call rather than material to write
    from.
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

    repair = _repair_instruction(state)
    if repair:
        parts.append(repair)

    return "\n".join(parts)


def _call_with_one_retry(user_prompt: str, system_prompt: str) -> dict[str, Any]:
    """Call the LLM; retry exactly once when the response is unusable.

    "Unusable" means unparseable JSON or a missing/empty
    `draft_report` — the `max_tokens`-truncation signature. The retry
    re-issues the same prompt with a corrective nudge appended; one
    extra call is cheap next to the already-billed reader fan-out it
    can rescue (ADR 0041).

    The retry is bounded against the job budget (ADR 0068 follow-up 3):
    the SDK's own envelope is clamped for *one* call and this node makes
    two, so the second is issued only when `_second_attempt_fits` says
    its worst case still lands inside `api_job_timeout_sec`. When it
    does not, the node fails now with `SynthesizerOutputError` instead
    of failing in two minutes with a job timeout — the same run, ended
    by the code that describes it.

    Args:
        user_prompt: The assembled synthesis prompt.
        system_prompt: The active system prompt (base or evidence path).

    Returns:
        The parsed response dict, guaranteed to carry a non-empty
        `draft_report` string.

    Raises:
        SynthesizerOutputError: Both attempts were unusable, or the
            first was unusable and the second did not fit the budget.
    """
    prompt = user_prompt
    started = time.monotonic()
    for attempt in (1, 2):
        try:
            # 8192, not the old 4096: the prompt asks for an
            # 800-1500-word report plus up to 10 citation objects,
            # which JSON-escaped lands near 3000-3300 tokens — 4096
            # left no margin, making truncation deterministic for long
            # reports (a retry at the same cap could never rescue it).
            parsed = call_llm_json(
                prompt=prompt,
                system_prompt=system_prompt,
                model_name=settings.synthesizer_model or None,
                max_tokens=8192,
                cache_system=settings.enable_prompt_caching,
            )
        except json.JSONDecodeError as exc:
            log.warning(
                "synthesizer_response_unparseable",
                extra={"attempt": attempt, "error": str(exc)},
            )
            parsed = {}
        if not isinstance(parsed, dict):
            # Valid JSON that isn't an object — `call_llm_json`'s dict
            # return type is a cast, not a runtime guarantee. Treated
            # as unusable, same as unparseable JSON.
            log.warning(
                "synthesizer_response_not_an_object",
                extra={"attempt": attempt, "raw_type": type(parsed).__name__},
            )
            parsed = {}
        if str(parsed.get("draft_report") or "").strip():
            return parsed
        if attempt == 1:
            if not _second_attempt_fits(time.monotonic() - started):
                break
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

    if settings.use_mock_data:
        draft_report, citations = mock_mode.mock_briefing(
            query=state["query"],
            sub_questions=state.get("sub_questions", []),
            papers=state.get("papers", []),
            analyses=state.get("paper_analyses", []),
            evidence=state.get("evidence", []),
            evidence_path=evidence_path,
        )
        log.info(
            "synthesizer_mock_briefing_served",
            extra={
                "n_papers": len(state.get("papers", [])),
                "n_claims": len(state.get("evidence", [])),
            },
        )
        return {
            "draft_report": draft_report,
            "citations": citations,
            "messages": [
                AIMessage(
                    content=(
                        f"Synthesized report with {len(citations)} citations "
                        f"(mock data; no synthesis was performed)."
                    ),
                    name="synthesizer",
                )
            ],
        }

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
