"""Verifier agent — runtime faithfulness check between synthesis and critique.

Promotes ADR-0007's offline faithfulness judge into an in-loop node. The
same extract-and-judge shape (per-claim decisions against cited paper
abstracts) but the response also carries a `recommended_action` the
supervisor can consume to pick a recovery step.

Two entry points, one judge:

- `verifier_agent` — the **supervisor's** `verify` action, reachable
  only under the supervisor loop with `settings.enable_verifier` true.
  Unchanged by CAP-02; see ADR 0015.
- `verify_node` — the verification stage of the fixed verify-and-repair
  policy (`settings.research_policy="fixed_verify_repair"`, ADR 0076).
  It calls the same `run_verification` and additionally writes a
  first-class verdict — `pass` / `fail` / `abstain` — that the graph
  routes on and `src/policies/repair.py` decides from.

Under the legacy fixed pipeline neither is wired in, which is what
`ENABLE_VERIFIER=true` with the supervisor off has always meant and
still means: nothing.

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
- **A judge that did not answer has not found a fault** — every path
  that reaches a result without a usable judgement (empty draft, no
  citations, upstream error, unusable output) reports the verdict
  `abstain`, never `fail`. The supervisor's fields are unchanged; what
  changes is that the fixed policy will not spend its one repair on a
  diagnosis nobody made.
- **Mock mode makes no judgement** (ADR 0080) — under
  `settings.use_mock_data` both entry points report `verified=True`,
  no unsupported claims and no missing evidence, and construct no model
  client. The verdict that travels with it is `abstain`, not `pass`:
  nothing judged this report, and a `pass` would tell the fixed policy
  a faithfulness check succeeded. `abstain` is what the policy already
  does with an unjudged report, so a keyless run reaches the critic
  without spending its one repair.
"""

import json
from dataclasses import dataclass
from typing import Any, Final, Literal

from langchain_core.messages import AIMessage

from src.agents.mock_mode import MOCK_VERIFICATION_SUMMARY
from src.agents.schemas import VerifierOutput
from src.cancellation import JobCancelledError
from src.config import settings
from src.errors import UpstreamModelOutput
from src.eval.metrics import build_source_index
from src.graph.state import Citation, EvidenceClaim, PaperMetadata, ResearchState
from src.llm import call_llm_json
from src.observability import get_logger
from src.observability.costs import CostBudgetExceeded
from src.observability.metrics import (
    DEGRADATION_RUNG_MODEL_FALLBACK,
    record_degradation_rung,
)

log = get_logger(__name__)

Verdict = Literal["pass", "fail", "abstain"]
"""The verify node's first-class outcomes (ADR 0076).

`abstain` is not a polite `fail`. It is what the verifier's existing
short-circuit and fallback paths actually mean — no draft, no citations,
an upstream error, output the parser could not use — and folding it into
either of the other two would either repair a report nobody found fault
with or pass one nobody checked.
"""

VERDICT_REASONS: Final[frozenset[str]] = frozenset(
    {
        # pass
        "verified",
        # fail
        "unsupported_claims",
        "missing_evidence",
        "unsupported_and_missing",
        "verifier_reported_failure",
        # abstain
        "no_draft",
        "no_citations",
        "upstream_model",
        "upstream_model_output",
        # ADR 0080. Mock mode makes no judgement at all, which is a
        # different fact from a judge that was asked and could not
        # answer — and the only one of the five a reader can act on by
        # changing a setting rather than by investigating an incident.
        "mock_mode",
    }
)
"""Every reason code a verdict can carry, published by ADR 0076.

Two of them are `src/errors.py`'s own codes, reused rather than
reinvented: an abstention caused by a failed judge call reports
`upstream_model`, one caused by output the parser could not use reports
`upstream_model_output` — the same names those failures carry when they
reach a job as an error, so a dashboard can join the two surfaces.
"""

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


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    """One verification, in the two shapes its two callers need.

    `verifier_agent` (the supervisor's action, ADR 0015) needs only the
    state fields and its own message; the `verify` node of the
    fixed verify-and-repair policy (ADR 0076) also needs to know *which*
    of the three verdicts this was, which the fields alone cannot say —
    `verified=True` with empty lists is emitted both by a judge that
    approved the report and by the short-circuit that never asked one.

    Attributes:
        verdict: `pass`, `fail` or `abstain`.
        reason: A member of `VERDICT_REASONS`.
        summary: The human sentence, without a node-name prefix.
        fields: The state fields both callers write.
    """

    verdict: Verdict
    reason: str
    summary: str
    fields: dict[str, Any]


def _abstained(reason: str, detail: str) -> VerificationOutcome:
    """No-work verification: empty draft, no citations, unusable judge.

    Keeps `verified=True` on the state for the pre-LLM short-circuits
    because that is what the supervisor path has always read there and
    ADR 0015's contract still says; the verdict carried alongside is what
    tells the fixed policy that nothing was actually judged.
    """
    return VerificationOutcome(
        verdict="abstain",
        reason=reason,
        summary=f"skipped: {detail}",
        fields={
            "verified": True,
            "unsupported_claims": [],
            "missing_evidence": [],
            "verifier_recommendation": "",
        },
    )


def _fallback_outcome(reason: str, detail: str) -> VerificationOutcome:
    """The judge output can't be trusted.

    Conservative default for the supervisor path, unchanged:
    `verified=False, recommended_action="revise_report"` routes it to
    another synthesis pass rather than blocking the loop or letting an
    unverified draft slip through. The verdict is `abstain` all the
    same — a judge that failed to answer has not found a fault, and the
    fixed policy must not spend its one repair as though it had.
    """
    return VerificationOutcome(
        verdict="abstain",
        reason=reason,
        summary=f"fallback (revise_report): {detail}",
        fields={
            "verified": False,
            "unsupported_claims": [],
            "missing_evidence": [],
            "verifier_recommendation": "revise_report",
        },
    )


def _mock_outcome() -> VerificationOutcome:
    """Mock mode's verification: `verified=True`, and nothing judged it.

    ADR 0080. The state fields are the ones every consumer of ADR 0015's
    contract reads for "no follow-up needed", because a mock briefing
    restates the fixture corpus and cites the papers the run retrieved —
    there is nothing for a faithfulness judge to fail it on, and
    `verified=False` would park a keyless demo in a recovery loop.

    The *verdict* is `abstain` rather than `pass`, and the difference is
    the whole reason this lives beside the two helpers above rather than
    reusing either. `pass` would tell `src/policies/repair.py` that a
    faithfulness check succeeded; `abstain` says no check happened,
    which is true and which that module already knows how to route
    (verdict != "fail" -> no repair). This is the fifth abstain reason
    code, extending the four ADR 0076 published.
    """
    return VerificationOutcome(
        verdict="abstain",
        reason="mock_mode",
        summary=MOCK_VERIFICATION_SUMMARY,
        fields={
            "verified": True,
            "unsupported_claims": [],
            "missing_evidence": [],
            "verifier_recommendation": "",
        },
    )


def _failure_reason(unsupported: list[str], missing: list[str]) -> str:
    """Which of the fail codes this verdict earned."""
    if unsupported and missing:
        return "unsupported_and_missing"
    if unsupported:
        return "unsupported_claims"
    if missing:
        return "missing_evidence"
    return "verifier_reported_failure"


def run_verification(state: ResearchState) -> VerificationOutcome:
    """Judge the draft and classify the result into a first-class verdict.

    The whole body of `verifier_agent` as it has always been, plus the
    verdict classification the fixed policy needs. Split out rather than
    duplicated so the supervisor's action and the policy's `verify` node
    cannot drift into judging differently — there is one judge here, and
    two ways of reporting it.

    Args:
        state: Full `ResearchState`.

    Returns:
        The outcome. Exactly one LLM call, except on the two
        short-circuits, which make none.
    """
    if settings.use_mock_data:
        return _mock_outcome()

    report = state.get("draft_report", "")
    if not report.strip():
        return _abstained("no_draft", "no draft to verify")

    if not state.get("citations"):
        # A report with no citations has nothing verifiable in ADR-0007's
        # frame. Flag it but don't block — the critic will catch it.
        return _abstained("no_citations", "draft has no citations")

    user_prompt = _build_user_prompt(state)

    try:
        parsed = call_llm_json(
            prompt=user_prompt,
            system_prompt=VERIFIER_SYSTEM_PROMPT,
            model_name=settings.verifier_model or None,
            max_tokens=2048,
            cache_system=settings.enable_prompt_caching,
            schema=VerifierOutput,
        )
    except (JobCancelledError, CostBudgetExceeded):
        # Neither is a judgement, and both are raised by `call_llm`
        # before it issues anything (ADR 0047 / 0051). Re-raised ahead of
        # the broad handler below, the same way `src/agents/reader.py`
        # re-raises them out of its fan-out: swallowing a budget stop
        # into an abstention would let the run continue past its own
        # ceiling — under the fixed verify-and-repair policy, straight
        # into a repair, a second synthesis and a second verification,
        # which is exactly the spend the ceiling exists to prevent.
        raise
    except Exception as exc:  # noqa: BLE001 — recoverable, log + fallback
        log.warning(
            "verifier_llm_failed_fallback",
            extra={"error": str(exc)},
        )
        # Rung 5 of `docs/reliability.md` §5: the judge did not answer
        # usably and a fallback outcome is substituted. The run
        # continues and reports `succeeded` with a verification nobody
        # performed, which is exactly the degradation the quality SLI
        # was defined to see. ADR 0081.
        record_degradation_rung(
            rung=DEGRADATION_RUNG_MODEL_FALLBACK, component="verifier"
        )
        # Two abstention codes, not one: output the parser could not use
        # is a different operational problem from a provider that did not
        # answer, and `src/errors.py` already names both.
        unusable = isinstance(exc, json.JSONDecodeError | UpstreamModelOutput)
        return _fallback_outcome(
            "upstream_model_output" if unusable else "upstream_model",
            f"LLM call failed ({type(exc).__name__})",
        )

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

    return VerificationOutcome(
        verdict="pass" if verified else "fail",
        reason="verified" if verified else _failure_reason(unsupported, missing),
        summary=summary,
        fields={
            "verified": verified,
            "unsupported_claims": unsupported,
            "missing_evidence": missing,
            "verifier_recommendation": recommendation,
        },
    )


def verifier_agent(state: ResearchState) -> dict[str, Any]:
    """Judge the draft report's faithfulness and recommend recovery.

    Reads: `draft_report`, `papers`, `citations`, `sub_questions`,
    `query`. Writes: `verified`, `unsupported_claims`, `missing_evidence`,
    `verifier_recommendation`, plus a message.

    Runs a single LLM call. Cost-tracked via `call_llm_json`. Cost/
    iteration caps are enforced by the supervisor before this node is
    reached, so no budget check here.

    This is the **supervisor's** verify action (ADR 0015) and its state
    update is unchanged: the verdict `run_verification` also produces is
    not written here, because nothing on the supervisor path reads it and
    adding a key to arm D's state would move a substrate the first
    experiment freezes.

    Args:
        state: Full `ResearchState`. Must have a populated
            `draft_report` for the verification to run; empty drafts
            short-circuit with `verified=True`.

    Returns:
        Partial state update — see field list above.
    """
    outcome = run_verification(state)
    return {
        **outcome.fields,
        "messages": [
            AIMessage(content=f"verifier -> {outcome.summary}", name="verifier")
        ],
    }


def verify_node(state: ResearchState) -> dict[str, Any]:
    """Graph node: the fixed policy's verification stage (ADR 0076).

    Same judge, same prompt, same cost as the supervisor's action. What
    it adds is the verdict, written to state as a first-class value the
    router and `src/policies/repair.py` can act on, plus the two repair
    bookkeeping keys carried through unchanged so all four of the
    policy's keys are present on the state from the first verification
    onward. That matters for a state read out of a checkpoint or off an
    SSE frame: a missing key and a key holding "nothing yet" are
    indistinguishable to a consumer, and the run manifest reads both.

    `repair_count` is *not* reset here. Re-verification after a repair
    is exactly the case the one-repair cap has to survive.

    Args:
        state: Full `ResearchState`.

    Returns:
        Partial state update: the verifier's own fields, the four policy
        keys, and one message stamped `verify`.
    """
    outcome = run_verification(state)
    return {
        **outcome.fields,
        "verification_verdict": outcome.verdict,
        "verification_reason": outcome.reason,
        "repair_count": int(state.get("repair_count", 0) or 0),
        "repair_action": str(state.get("repair_action", "") or ""),
        "messages": [
            AIMessage(
                content=(
                    f"verify -> {outcome.verdict} ({outcome.reason}): "
                    f"{outcome.summary}"
                ),
                name="verify",
            )
        ],
    }
