"""Metrics for the offline eval pipeline. Full strategy in `docs/eval.md`.

Landed:
  - citation_resolution_rate — deterministic, no LLM. Resolves every
    cited arXiv identifier against the papers the run actually
    retrieved, and reports `None` with a reason when the report cited
    nothing (see ADR 0074). **This is the citation metric the gate
    reads.**
  - citation_accuracy — pure regex + set membership, no LLM. Kept as a
    diagnostic only; see `measure_citation_accuracy` for what it gets
    wrong and why it survives anyway.
  - completeness — batched LLM-as-judge over expected topics on the
    final report (see ADR 0006).
  - faithfulness — extract-and-judge in one call against the evidence
    the writer actually had: each cited paper's abstract, plus the
    reader's ranked chunks for that paper when a caller supplies them
    (ADR 0007, revised by ADR 0100).
  - retrieval_recall — batched LLM-as-judge that asks whether the
    *retrieved paper set* is enough to cover each expected topic.
    Complements completeness by isolating retrieval-quality signal
    from report-generation-quality signal (see ADR 0013).

Every judge here is issued against `settings.eval_judge_model`, and every
judge prompt carries a version constant beside it (ADR 0070). Neither is
decoration: passing no model let a product-model upgrade silently change
the grader, and an unversioned prompt let an edit rebaseline a metric
with nothing in the row to say so. `RESEARCH_RUBRICS` is what a campaign
records; `tests/test_eval_rubric_versions.py` is what stops the text
moving under a stale version.

**Three judge-definition rules landed with ADR 0100, and each of them
moves numbers.**

1. *A rate with an empty denominator is `None` with a reason, never
   `1.0`.* Every judged metric here used to hand a free perfect mark to
   the run that gave it nothing to measure — no cited claims, no
   expected topics, no report at all. That is the same defect ADR 0074
   closed on the citation path, and it is closed here the same way: a
   `score` of `None` beside a `reason` naming which emptiness it was.
2. *Sources are identified by `paper_id`, not by surname and year.* Two
   papers by a Zhang in 2024 collided on one key and the second silently
   replaced the first, so a `[Zhang, 2024]` claim was judged against
   whichever abstract happened to be written last. Each cited paper now
   gets a cite key that is unique within the dossier, and a cite that
   still cannot be told apart is counted as `ambiguous_citation` rather
   than resolved to a guess.
3. *The judges sample at their own temperature and under their own
   schema.* `settings.eval_judge_temperature` (0.0) replaces the
   workflow's `llm_temperature` on these three calls only, and each
   carries the pydantic model its response is parsed into. What was
   actually sent is recorded on the result, because "the grader was
   resampled" and "the arm got worse" are otherwise the same row.

**A metric definition change rebaselines a campaign exactly as a prompt
edit does**, and ADR 0070's machinery is what records it: the
deterministic groundedness check rides in `RESEARCH_RUBRICS` under its
own version, so a row scored before this module read
`citation_resolution_rate` and a row scored after carry different
`provenance.rubric_versions`, and `regression_diff` refuses to compare
them (exit 3) instead of publishing a delta across two instruments.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final, TypedDict

import pydantic

from src.config import settings
from src.eval.groundedness import (
    GROUNDEDNESS_CHECK_VERSION,
    NORMALIZATION_SPEC,
    canonical_arxiv_id,
    measure_groundedness,
)
from src.eval.provenance import Rubric, judge_model
from src.graph.state import Citation, PaperMetadata
from src.llm import call_llm_json, resolve_profile

# Matches [Author, Year] and its common variants:
#   [Smith, 2023]
#   [Smith et al., 2023]
#   [Smith and Jones, 2023]
#   [Smith, 2023a]   (year suffix accepted but ignored at match time)
# The author group is non-greedy up to the comma before the year so we
# don't over-consume when the report contains multiple citations on one line.
_CITE_PATTERN = re.compile(
    r"\[([^\[\]]+?),\s*(\d{4})[a-zA-Z]?\]"
)

#: Same shape as `_CITE_PATTERN`, but it *keeps* the year suffix instead
#: of discarding it. The legacy pattern drops the letter because the
#: legacy metric has no use for it; the faithfulness dossier does, since
#: the suffix is exactly what tells two same-surname, same-year papers
#: apart (ADR 0100). Anchored by the caller, not here.
_SUFFIXED_CITE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\[([^\[\]]+?),\s*(\d{4})([a-zA-Z]?)\]"
)

# ---------------------------------------------------------------------------
# Why a judged score is `None` (ADR 0100, following ADR 0074's pattern).
#
# Each of these was a `1.0` before: the metric was handed nothing to
# measure and reported a perfect mark, which is the one answer a reader
# cannot tell apart from "this run was flawless". They are separate
# constants rather than one `no_data` because they have different owners
# — an empty report is a workflow failure, an empty topic list is a
# benchmark authoring error, and unavailable sources are a retrieval or
# plumbing problem — and a single code would have collapsed the three.
# ---------------------------------------------------------------------------

#: The report was empty or whitespace, so no judge was called at all.
EMPTY_REPORT: Final[str] = "empty_report"

#: The judge extracted no cited factual claim from a non-empty report.
NO_CITED_CLAIMS: Final[str] = "no_cited_claims"

#: Claims were extracted, but every one of them was excluded from the
#: denominator because its source could not be resolved or provided.
#: Distinct from `no_cited_claims`: the report did cite, and the harness
#: could not check it — that is a finding, not an absence.
ALL_SOURCES_UNAVAILABLE: Final[str] = "all_sources_unavailable"

#: The benchmark query declared no expected topics, so completeness and
#: retrieval recall have no denominator.
NO_EXPECTED_TOPICS: Final[str] = "no_expected_topics"

#: Every reason a judged score is `None`, for a caller that tabulates.
SCORE_REASONS: Final[frozenset[str]] = frozenset(
    {EMPTY_REPORT, NO_CITED_CLAIMS, ALL_SOURCES_UNAVAILABLE, NO_EXPECTED_TOPICS}
)

# ---------------------------------------------------------------------------
# How one claim's cite resolved to a source (ADR 0100).
# ---------------------------------------------------------------------------

#: The cite named exactly one paper in the dossier.
CITE_RESOLVED: Final[str] = "resolved"

#: The cite named a `(surname, year)` that two or more cited papers
#: share, and carried no suffix to tell them apart. **Never resolved to
#: one of them**: picking either would be a coin flip recorded as a
#: measurement, which is the EL-08 defect in a new costume.
CITE_AMBIGUOUS: Final[str] = "ambiguous_citation"

#: The cite parsed but names no paper in the dossier — the classic
#: fabricated citation, or a source the run never retrieved.
CITE_UNRESOLVED: Final[str] = "unresolved_citation"

#: The judge's `cite` field was not an `[Author, Year]` tag at all.
CITE_MALFORMED: Final[str] = "malformed_citation"

#: Every per-claim resolution outcome.
CITE_RESOLUTIONS: Final[frozenset[str]] = frozenset(
    {CITE_RESOLVED, CITE_AMBIGUOUS, CITE_UNRESOLVED, CITE_MALFORMED}
)

# ---------------------------------------------------------------------------
# What the faithfulness judge was allowed to see (ADR 0100, EL-09).
# ---------------------------------------------------------------------------

#: The dossier carried abstracts only — the ADR 0007 substrate. The
#: writer worked from ranked chunks, so a claim drawn from a paper's
#: body is judged unsupported here for want of the text, not for want
#: of truth. Recorded on the result so a reader can tell the two apart.
SOURCE_SCOPE_ABSTRACT_ONLY: Final[str] = "abstract_only"

#: At least one cited paper's dossier entry carried the reader's ranked
#: chunks beside its abstract — the judge saw what the writer saw.
SOURCE_SCOPE_ABSTRACT_AND_CHUNKS: Final[str] = "abstract_and_chunks"


class CitationAccuracyResult(TypedDict):
    """Outcome of the citation-accuracy metric."""

    score: float
    total_citations: int
    resolved: int
    unresolved: list[str]


def _normalize_first_author(author_field: str) -> str:
    """Extract and lowercase the first author's last name from a citation tag.

    Handles the three inline citation styles emitted by the synthesizer:
      - "Smith"                -> "smith"
      - "Smith et al."         -> "smith"
      - "Smith and Jones"      -> "smith"
    """
    cleaned = author_field.strip().rstrip(",").strip()

    # Trim any "et al." variant.
    lower = cleaned.lower()
    for suffix in (" et al.", " et al", " et. al.", " et. al"):
        if lower.endswith(suffix):
            cleaned = cleaned[: len(cleaned) - len(suffix)].rstrip()
            break

    # Two-author "X and Y" -> keep X.
    if " and " in cleaned:
        cleaned = cleaned.split(" and ", 1)[0].strip()

    tokens = cleaned.split()
    if not tokens:
        return ""
    return tokens[-1].lower()


def _build_citation_index(citations: list[Citation]) -> set[tuple[str, str]]:
    """Index the citation list by `(first_author_lastname, 4-digit-year)`."""
    index: set[tuple[str, str]] = set()
    for citation in citations:
        year = citation["year"].strip()[:4]
        authors = citation["authors"]
        if not authors or not authors[0].strip() or not year:
            continue
        # authors[0] is a full name ("Jane Doe") — last whitespace token.
        lastname_tokens = authors[0].strip().split()
        lastname = lastname_tokens[-1].lower() if lastname_tokens else ""
        if lastname:
            index.add((lastname, year))
    return index


def measure_citation_accuracy(
    report: str, citations: list[Citation]
) -> CitationAccuracyResult:
    """Legacy diagnostic: the fraction of `[Author, Year]` tags that resolve.

    **This metric no longer gates anything, and it is kept deliberately
    broken.** Two defects, both recorded in ADR 0074:

    1. A report with no inline citations scores `1.0` — a perfect mark
       for the exact failure the metric exists to catch.
    2. It never looks at an identifier. It matches `[Author, Year]` tags
       against a `(lastname, year)` index built from the same
       `state["citations"]` list the synthesizer wrote, so a model that
       invents a whole citation entry — plausible authors and a
       fabricated `paper_id` included — still scores `1.0`. This
       repository's own e2e fixture does exactly that.

    `measure_citation_resolution` below is the honest replacement and is
    what `regression_diff` gates on. This function survives for three
    reasons, none of them "it is still right":

    - **The row field may not be removed.** ADR 0070 forbids renaming or
      removing an existing `summary.jsonl` field, so `citation_accuracy`
      stays on the row — demoted to `RESEARCH_INFORMATIONAL_FIELDS`,
      tabulated and marked *(not gated)*.
    - **The published README block still averages it**
      (`src/eval/readme_update.py`), with its own compensating exclusion
      of zero-citation rows. Switching that table is a follow-up owned by
      whoever holds that module.
    - **It is the historical series.** Every number this repository has
      ever published under "citation accuracy" is this function's, and
      keeping it computable is what lets an old artifact still be read.

    Its behaviour is therefore frozen: fixing the zero-citation `1.0`
    here would silently change the legacy number, which is the same
    rebaselining-without-saying-so this work order exists to avoid.

    Parses `[Author, Year]` tags from the report body, deduplicates them,
    and checks each against a normalized index of the citation list.
    Normalization key: `(first-author-lastname-lowercased, 4-digit year)`.
    Year suffixes (`2023a`) are stripped before comparison; two-author
    (`X and Y`) and many-author (`X et al.`) styles keep only the first
    author's last name.

    A report with no inline citations returns `score=1.0` with
    `total_citations=0` — see the defect note above. Callers who want the
    honest answer call `measure_citation_resolution`.

    Args:
        report: Synthesized report markdown from the workflow.
        citations: The workflow's `Citation` list.

    Returns:
        `CitationAccuracyResult` with the aggregate score, counts, and
        the verbatim strings of any unresolved citations for debugging.
    """
    valid = _build_citation_index(citations)

    matches = _CITE_PATTERN.findall(report)
    if not matches:
        return CitationAccuracyResult(
            score=1.0,
            total_citations=0,
            resolved=0,
            unresolved=[],
        )

    # Deduplicate by normalized key so a citation used five times counts once.
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for author_field, year in matches:
        norm_key = (_normalize_first_author(author_field), year)
        if norm_key not in seen:
            seen.add(norm_key)
            unique.append((author_field, year))

    resolved = 0
    unresolved: list[str] = []
    for author_field, year in unique:
        norm_key = (_normalize_first_author(author_field), year)
        if norm_key in valid:
            resolved += 1
        else:
            unresolved.append(f"[{author_field.strip()}, {year}]")

    total = len(unique)
    return CitationAccuracyResult(
        score=resolved / total,
        total_citations=total,
        resolved=resolved,
        unresolved=unresolved,
    )


# ---------------------------------------------------------------------------
# Citation resolution — deterministic, no judge (ADR 0074).
# ---------------------------------------------------------------------------

#: The deterministic groundedness check, registered in the shared rubric
#: lock as a versioned instrument (ADR 0074's fourth follow-up, which
#: could not be done until one work order held both `metrics.py` and
#: `tests/fixtures/eval/rubric_lock.json`).
#:
#: `Rubric` was built for judge prompts, and the `prompt` slot here
#: carries `NORMALIZATION_SPEC` instead — the check's contract, as text.
#: That is not a misuse of the field so much as the field's actual
#: contract: what the lock defends is *the text whose edit makes two
#: scores incomparable*, and a deterministic check has one. The name is
#: the check's rather than any single metric's because one version
#: governs all three of its metrics.
#:
#: `citation_accuracy` is still deliberately absent from the lock — it
#: declares no spec text and no version constant, so there is nothing to
#: lock. The rule is "a metric is in the registry iff it publishes a
#: versioned definition", not "iff it calls a model".
GROUNDEDNESS_CHECK: Final[Rubric] = Rubric(
    name="groundedness",
    version=GROUNDEDNESS_CHECK_VERSION,
    prompt=NORMALIZATION_SPEC,
)


class CitationResolutionResult(TypedDict):
    """Outcome of the citation-resolution metric.

    Shaped like the other four results — `score` first, counts beside it
    — so `runner._get_score` and `_get_count` read it unchanged. The two
    fields the other results do not have are the point of the metric:

    Attributes:
        score: Resolved / checked, or **`None` when nothing was checked**.
            Never a free `1.0`.
        total_citations: The denominator, always published. A rate
            without one is not a measurement.
        resolved: The numerator.
        excluded: Cited identifiers that existed but could not be
            decided. Always 0 today — the citation path has no
            undecidable outcome — and carried anyway so a later one
            cannot quietly shrink the denominator unannounced.
        reason: Why `score` is `None` (`no_citations`), or `None`.
        unresolved: `"<identifier> [<reason>]"` per failure, for
            debugging — `citation_not_retrieved` and
            `citation_malformed` stay distinct because they have
            different owners.
        check_version: `GROUNDEDNESS_CHECK_VERSION` that produced this.
        spec_digest: Digest of the normalization contract, so a row can
            name its instrument without a lookup.
    """

    score: float | None
    total_citations: int
    resolved: int
    excluded: int
    reason: str | None
    unresolved: list[str]
    check_version: str
    spec_digest: str


def measure_citation_resolution(
    report: str, papers: list[PaperMetadata], citations: list[Citation]
) -> CitationResolutionResult:
    """Score the fraction of cited identifiers the run actually retrieved.

    The honest citation metric, and the one the regression gate reads.
    No model call, no network, no cost: it resolves each cited arXiv
    identifier against `build_corpus_index(papers)` — the papers *this
    run* fetched — rather than against arxiv.org, because a citation to
    a real paper the run never read is still a fabricated citation
    (ADR 0074 §1).

    Two surfaces are checked, deduplicated per `(identifier, surface)`:
    identifiers in the report body (`arXiv:…` or an `arxiv.org` URL) and
    the identifier each `state["citations"]` entry asserts. The second is
    the one `measure_citation_accuracy` cannot see at all.

    **The behaviour that makes this a replacement rather than a second
    opinion**: a report with no citations scores `None` with reason
    `no_citations`, not `1.0`.

    Args:
        report: Synthesized report markdown from the workflow.
        papers: `state["papers"]` — the only oracle for resolution.
        citations: The workflow's `Citation` list.

    Returns:
        `CitationResolutionResult`, whose `score` is `None` exactly when
        `total_citations` is 0.
    """
    result = measure_groundedness(report, papers, citations)
    metric = result["citation_resolution_rate"]
    return CitationResolutionResult(
        score=metric["value"],
        total_citations=metric["denominator"],
        resolved=metric["numerator"],
        excluded=metric["excluded"],
        reason=metric["reason"],
        unresolved=[
            f"{claim['subject']} [{claim['reason']}]"
            for claim in result["claims"]
            if claim["kind"] == "citation" and claim["grounded"] is False
        ],
        check_version=result["check"]["check_version"],
        spec_digest=result["check"]["spec_digest"],
    )


# ---------------------------------------------------------------------------
# The judge response contract (ADR 0100, EL-11).
#
# One definition of each judge's output shape, used twice: as `schema=`
# on the live call, so the provider constrains the response where the
# deployment has structured outputs on, and as the validation surface
# the deterministic mock judge (ADR 0095) builds its readings against.
# Two definitions would have been two contracts, and the free path's
# defensive coercions below would have hidden the drift.
#
# The models are shapes, not rubrics: field names, types and
# `extra="forbid"`, with no `min_length` or regex constraints. A
# constraint here is a whole-call failure on the structured path — the
# judge that answers with an empty `reason` would take a metric down
# rather than lose a sentence — and every bound worth enforcing is
# enforced by the aggregators, which have to keep working on the free
# path anyway.
#
# The base is declared here rather than imported from
# `src.contracts.kernel`, whose `StrictContractModel` is the same four
# settings. `tests/e2e/test_contract_shadow_research.py` asserts that
# importing `src.eval.runner` pulls in no `src.contracts` module at all
# — with the shadow off the contract code must not merely be inert, it
# must not be loaded — and this module is on that import path. Four
# lines of config are the cheaper side of that trade.
# ---------------------------------------------------------------------------


class JudgeOutputModel(pydantic.BaseModel):
    """Closed, immutable, non-coercing base for a judge's response."""

    model_config = pydantic.ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class TopicCoverageJudgement(JudgeOutputModel):
    """One topic-coverage decision, as the judge returns it."""

    topic: str
    covered: bool
    reason: str


class CompletenessJudgeOutput(JudgeOutputModel):
    """The completeness judge's whole response."""

    coverage: tuple[TopicCoverageJudgement, ...]


class ClaimSupportJudgement(JudgeOutputModel):
    """One claim-support decision, as the judge returns it.

    `supported` is nullable because abstention is a first-class answer:
    the judge is told to return `null` when the cited source was not
    provided, and a schema that forced a boolean would convert every
    such abstention into a verdict.
    """

    claim: str
    cite: str
    supported: bool | None
    reason: str


class FaithfulnessJudgeOutput(JudgeOutputModel):
    """The faithfulness judge's whole response."""

    claims: tuple[ClaimSupportJudgement, ...]


class TopicRetrievalJudgement(TopicCoverageJudgement):
    """A topic decision that also names the papers behind it."""

    paper_ids: tuple[int, ...]


class RetrievalRecallJudgeOutput(JudgeOutputModel):
    """The retrieval-recall judge's whole response."""

    coverage: tuple[TopicRetrievalJudgement, ...]


class JudgeRequest(TypedDict):
    """What was actually sent for one judged metric.

    Recorded on the result rather than only in the provenance block
    because these three fields change the *number*, and a campaign that
    re-ran its judges at a different temperature or under a different
    output mode has to be able to say so from the row that carries the
    score.

    Attributes:
        model: The pinned judge model id (ADR 0070).
        temperature: The temperature the request carried, or `None`
            when the model's capability row rejects sampling parameters
            and the body carried none (ADR 0077). `None` is not 0.0:
            "no temperature field" and "temperature zero" are different
            requests, and only the provider knows what it does with the
            first.
        structured_output: Whether the schema below was actually sent as
            `output_config.format`. False both when the operator has not
            enabled structured outputs and when the judge model does not
            take them — from the row's point of view those are the same
            fact, that the response was parsed from free text.
        schema: Name of the pydantic model the response was read as.
    """

    model: str
    temperature: float | None
    structured_output: bool
    schema: str


def _judge_request(schema: type[pydantic.BaseModel]) -> JudgeRequest:
    """Describe the judge call about to be issued, or just issued.

    Resolved through `src.llm.resolve_profile` rather than read off
    settings, so the record says what the *request* carried: an operator
    who sets `eval_judge_temperature=0.0` and routes the judge to a
    model that refuses sampling parameters gets `None` here, which is
    the truth, instead of a 0.0 that never left the process.
    """
    profile = resolve_profile(
        judge_model(), temperature=settings.eval_judge_temperature
    )
    return JudgeRequest(
        model=profile.model,
        temperature=profile.temperature,
        structured_output=profile.structured_outputs,
        schema=schema.__name__,
    )


# ---------------------------------------------------------------------------
# Completeness — LLM-as-judge over expected topics.
# ---------------------------------------------------------------------------

#: Version of the completeness rubric below. Bumping it is the act that
#: declares "scores from before and after this edit are not comparable";
#: `tests/test_eval_rubric_versions.py` fails if the prompt text moves
#: without one (ADR 0070).
#:
#: 2.0.0 (ADR 0100): the instrument changed, not just the words. A query
#: with no expected topics now scores `None` with a reason instead of a
#: free 1.0, and the call is issued at `eval_judge_temperature` under
#: `CompletenessJudgeOutput`. The prompt below moved with it because the
#: lock binds a version to prompt text — see ADR 0100 §"Why the two
#: topic rubrics moved too".
COMPLETENESS_RUBRIC_VERSION: Final[str] = "2.0.0"

COMPLETENESS_SYSTEM_PROMPT = """\
You are a strict research report evaluator. Given a research briefing and
a list of topics the briefing was expected to cover, decide for each topic
whether the briefing MEANINGFULLY ADDRESSES it.

"Meaningfully addresses" means:
  - The topic is discussed with specific content — methods, findings,
    tradeoffs, comparisons, quantitative results — not just name-dropped
    or listed in passing.
  - A single sentence that only names the topic does NOT count.
  - Discussion of a synonymous or clearly equivalent concept DOES count.

Return JSON matching this exact schema — the object alone, with no prose
around it and no markdown fencing. Where output schemas are enforced,
this is the schema they are enforced against:
{
  "coverage": [
    {"topic": "<verbatim topic>", "covered": true|false, "reason": "<one short sentence>"}
  ]
}

Include one object per input topic, in the same order, and add no topic
that was not given to you. Be strict — err toward "not covered" when in
doubt.
"""

COMPLETENESS_RUBRIC: Final[Rubric] = Rubric(
    name="completeness",
    version=COMPLETENESS_RUBRIC_VERSION,
    prompt=COMPLETENESS_SYSTEM_PROMPT,
)


class TopicCoverage(TypedDict):
    """Per-topic decision emitted by the completeness judge."""

    topic: str
    covered: bool
    reason: str


class CompletenessResult(TypedDict):
    """Outcome of the completeness metric.

    Attributes:
        score: Covered / expected, or `None` when there were no expected
            topics. Never a free 1.0 for an empty denominator (ADR
            0100).
        reason: `no_expected_topics` when `score` is `None`, else
            `None`.
        total_topics: The denominator, always published.
        covered_topics: The numerator.
        coverage: One decision per requested topic, in request order.
        judge: What the judge call carried, or `None` when the
            short-circuit meant no judge was called.
    """

    score: float | None
    reason: str | None
    total_topics: int
    covered_topics: int
    coverage: list[TopicCoverage]
    judge: JudgeRequest | None


def _build_completeness_prompt(report: str, topics: list[str]) -> str:
    """Assemble the user message for the completeness judge."""
    topic_lines = "\n".join(f"- {topic}" for topic in topics)
    return (
        f"Research briefing:\n\n{report}\n\n"
        f"Topics expected to be covered:\n{topic_lines}"
    )


def _judged_items(parsed: dict[str, Any], field: str) -> dict[str, dict[str, Any]]:
    """Index a judge's topic decisions by topic, defensively.

    Accepts a tuple as readily as a list: the structured-output path
    returns a validated model's `model_dump()`, whose tuple fields are
    tuples, and an `isinstance(..., list)` check would have silently
    read every structured response as "the judge returned nothing".
    """
    judged_map: dict[str, dict[str, Any]] = {}
    raw = parsed.get(field, [])
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("topic"), str):
                # Keep the first occurrence if the judge duplicates a topic.
                judged_map.setdefault(item["topic"], item)
    return judged_map


def _aggregate_coverage(
    parsed: dict[str, Any],
    requested_topics: list[str],
    judge: JudgeRequest | None = None,
) -> CompletenessResult:
    """Merge the judge's response with the requested topic list.

    Defensively handles judge output shape: missing topics are treated as
    uncovered with a note; extra / duplicate topics are ignored. The
    result always has exactly `len(requested_topics)` entries, in the
    same order as the input.
    """
    judged_map = _judged_items(parsed, "coverage")

    coverage: list[TopicCoverage] = []
    for topic in requested_topics:
        item = judged_map.get(topic)
        if item is None:
            coverage.append(
                TopicCoverage(
                    topic=topic,
                    covered=False,
                    reason="Judge did not return a decision for this topic.",
                )
            )
        else:
            coverage.append(
                TopicCoverage(
                    topic=topic,
                    covered=bool(item.get("covered", False)),
                    reason=str(item.get("reason", "")),
                )
            )

    covered = sum(1 for c in coverage if c["covered"])
    total = len(requested_topics)

    return CompletenessResult(
        score=covered / total if total > 0 else None,
        reason=None if total > 0 else NO_EXPECTED_TOPICS,
        total_topics=total,
        covered_topics=covered,
        coverage=coverage,
        judge=judge,
    )


def measure_completeness(
    report: str,
    expected_topics: list[str],
) -> CompletenessResult:
    """Score how many expected topics the report meaningfully covers.

    Uses a single LLM-as-judge call: the judge sees the whole report and
    the full topic list, and returns a per-topic covered / not-covered
    decision with a short reason (see `docs/decisions/0006-*` for why
    batched over per-topic).

    Empty `expected_topics` returns `score=None` with reason
    `no_expected_topics` and makes no LLM call — the metric does not
    apply, which is a different statement from the 1.0 it used to
    report (ADR 0100). Empty report is judged in the normal way
    (typically returns all-uncovered), because a query that expected
    topics and got no report is a real zero.

    Args:
        report: Synthesized report markdown from the workflow.
        expected_topics: Coverage targets from the benchmark query.

    Returns:
        `CompletenessResult` with aggregate score, counts, and per-topic
        decisions.
    """
    if not expected_topics:
        return CompletenessResult(
            score=None,
            reason=NO_EXPECTED_TOPICS,
            total_topics=0,
            covered_topics=0,
            coverage=[],
            judge=None,
        )

    user_prompt = _build_completeness_prompt(report, expected_topics)
    judge = _judge_request(CompletenessJudgeOutput)
    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=COMPLETENESS_SYSTEM_PROMPT,
        model_name=judge_model(),
        max_tokens=2048,
        schema=CompletenessJudgeOutput,
        temperature=settings.eval_judge_temperature,
    )
    return _aggregate_coverage(parsed, expected_topics, judge)


# ---------------------------------------------------------------------------
# Faithfulness — extract-and-judge each cited claim against its source.
# ---------------------------------------------------------------------------

#: Version of the faithfulness rubric. See `COMPLETENESS_RUBRIC_VERSION`.
#:
#: 2.0.0 (ADR 0100) is the largest definition change of the three. The
#: judge is now shown the reader's ranked chunks beside each cited
#: abstract when a caller supplies them, cite keys are unique within the
#: dossier, an ambiguous cite abstains instead of resolving to whichever
#: paper was written last, and an empty denominator is `None`. A 1.0.0
#: score and a 2.0.0 score are not the same measurement.
FAITHFULNESS_RUBRIC_VERSION: Final[str] = "2.0.0"

FAITHFULNESS_SYSTEM_PROMPT = """\
You are a strict research report faithfulness evaluator. Given a research
briefing and a dossier of the sources it cites, extract every factual
claim in the briefing that carries an inline citation, then decide
whether each claim is SUPPORTED by the material provided for the paper it
cites.

Each dossier entry opens with its cite key alone on a line, in the form
[Surname, Year] — with a letter after the year (2024a, 2024b) when two
cited papers share a surname and a year. Below it come the paper's title,
its abstract, and, where they are available, the ranked excerpts the
briefing's author actually read from that paper.

Definitions:
  - A "factual claim" is a statement that could be true or false about the
    world — a method exists, an approach works, a result was observed.
    Skip transitional prose, framing sentences, and generic background.
  - "Supported" means: the material provided for the cited paper — its
    abstract together with any excerpts shown under the same cite key —
    either states the claim directly or clearly implies it. Reasonable
    paraphrase is fine; adding facts not present in that material is NOT.
  - Judge each claim ONLY against the entry it cites. Text under another
    cite key belongs to another paper and cannot support this claim.
  - If the cited paper has no dossier entry at all, set supported to null.

Copy the cite key back verbatim, including any letter after the year. If
the briefing's own tag cannot be matched to a single entry — it says
[Zhang, 2024] where the dossier holds both [Zhang, 2024a] and
[Zhang, 2024b] — return the tag as the briefing wrote it rather than
guessing which paper was meant.

Return JSON matching this exact schema — the object alone, with no prose
around it and no markdown fencing. Where output schemas are enforced,
this is the schema they are enforced against:
{
  "claims": [
    {
      "claim": "the factual assertion, lightly paraphrased is fine",
      "cite": "[Author, Year]",
      "supported": true|false|null,
      "reason": "one-sentence justification, quoting the source when possible"
    }
  ]
}

Include one object per claim. Be strict — err toward "not supported" when
the provided material does not clearly back the claim.
"""

FAITHFULNESS_RUBRIC: Final[Rubric] = Rubric(
    name="faithfulness",
    version=FAITHFULNESS_RUBRIC_VERSION,
    prompt=FAITHFULNESS_SYSTEM_PROMPT,
)


class ClaimJudgement(TypedDict):
    """Per-claim decision emitted by the faithfulness judge.

    Attributes:
        claim: The factual assertion the judge extracted.
        cite: The cite tag the judge returned, verbatim.
        paper_id: The paper the cite resolved to, or `None` when it
            resolved to none. The field EL-08 was missing: a decision
            that cannot name the document it was taken against cannot be
            audited, and could not have caught the collision.
        resolution: One of `CITE_RESOLUTIONS` — why this claim does or
            does not count. Separate from `reason`, which is the judge's
            prose and is not machine-readable.
        supported: The verdict, or `None` when the claim is excluded
            from the denominator.
        reason: The judge's one-sentence justification.
    """

    claim: str
    cite: str
    paper_id: str | None
    resolution: str
    supported: bool | None
    reason: str


class FaithfulnessResult(TypedDict):
    """Outcome of the faithfulness metric.

    `score` is `supported / (supported + unsupported)`, or `None` when
    that denominator is empty — the report was blank, the judge
    extracted no cited claim, or every claim it did extract was
    excluded. Which of the three is in `reason` (ADR 0100); before it,
    all three published a 1.0.

    Claims whose cited source could not be provided or could not be
    identified (`supported=None`) are excluded from the denominator and
    counted separately, so "the judge said no" never reads the same as
    "we could not ask".

    Attributes:
        score: Supported over decided, or `None`.
        reason: Why `score` is `None`, drawn from `SCORE_REASONS`, or
            `None` when it is a number.
        total_claims: Every claim the judge returned, decided or not.
        supported: Numerator.
        unsupported: The rest of the denominator.
        source_unavailable: Claims excluded from the denominator, for
            any of the three resolution failures below. Kept under its
            ADR 0007 name and meaning — `src/campaign/report.py` reads
            it as the abstention count.
        ambiguous_citations: Of those, the ones whose cite named a
            `(surname, year)` shared by two or more cited papers.
            Counted rather than resolved (EL-08).
        unresolved_citations: Of those, the ones whose cite named no
            cited paper at all.
        malformed_citations: Of those, the ones whose cite was not an
            `[Author, Year]` tag.
        collision_count: How many cited papers shared a
            `(surname, year)` with another and needed a disambiguating
            suffix — equivalently, how many dossier entries the old
            surname-year index would have silently dropped. 0 on a
            normal run; a positive number here is the EL-08 condition,
            now survived rather than hidden.
        source_scope: `abstract_only` or `abstract_and_chunks` — what
            the judge was shown. A faithfulness number is only
            comparable to another taken at the same scope.
        sources_total: Cited papers in the dossier.
        sources_with_chunks: How many of them carried the reader's
            ranked chunks.
        claims: Per-claim decisions.
        judge: What the judge call carried, or `None` when no judge was
            called.
    """

    score: float | None
    reason: str | None
    total_claims: int
    supported: int
    unsupported: int
    source_unavailable: int
    ambiguous_citations: int
    unresolved_citations: int
    malformed_citations: int
    collision_count: int
    source_scope: str
    sources_total: int
    sources_with_chunks: int
    claims: list[ClaimJudgement]
    judge: JudgeRequest | None


class SourceDocument(TypedDict):
    """One cited paper, as the faithfulness judge is shown it.

    Attributes:
        paper_id: `PaperMetadata.id` — the identity the dossier is keyed
            by, and the thing EL-08 was missing.
        cite_key: The bracket-free key the judge sees and echoes back,
            e.g. `Zhang, 2024` or `Zhang, 2024a`. Unique within a
            dossier by construction.
        lastname: First author's lowercased last name.
        year: The four-digit year presented in the cite key.
        suffix: The disambiguating letter, or `""` when the base key was
            already unique.
        title: The paper's title, shown beside the key so the judge can
            tell two same-surname papers apart even if it ignores the
            suffix.
        abstract: The abstract.
        chunks: The reader's ranked chunks for this paper, in rank
            order. Empty when the caller supplied none.
        source_scope: `abstract_only` or `abstract_and_chunks`, for this
            paper.
    """

    paper_id: str
    cite_key: str
    lastname: str
    year: str
    suffix: str
    title: str
    abstract: str
    chunks: list[str]
    source_scope: str


class SourceDossier(TypedDict):
    """Every cited paper, plus the maps that resolve a cite back to one.

    Attributes:
        sources: The cited papers, in the order `papers` gave them.
        by_cite_key: Normalised full cite key (`"zhang|2024|a"`) to
            `paper_id`. One entry per source.
        by_base_key: Normalised base key (`"zhang|2024"`) to every
            `paper_id` that answers to it. A list, because that is the
            collision EL-08 pretended did not exist; a base key with two
            entries resolves to neither.
        collision_count: Cited papers that share a base key with another.
        source_scope: The dossier-wide scope.
        sources_with_chunks: How many sources carried reader chunks.
    """

    sources: list[SourceDocument]
    by_cite_key: dict[str, str]
    by_base_key: dict[str, list[str]]
    collision_count: int
    source_scope: str
    sources_with_chunks: int


def build_source_index(
    papers: list[PaperMetadata], citations: list[Citation]
) -> dict[tuple[str, str], str]:
    """Join papers and citations into a surname-year -> abstract map.

    Returns `{(first-author-lastname-lower, 4-digit-year): abstract}` for
    every cited paper we have both a citation entry and a `PaperMetadata`
    entry for.

    **This is the runtime verifier's adapter, and it is kept at its
    original contract on purpose.** The faithfulness metric no longer
    calls it: a `(surname, year)` key cannot hold two papers by a Zhang
    in 2024, and the second silently replaced the first — so a
    `[Zhang, 2024]` claim was judged against whichever abstract this
    loop wrote last (EL-08). `build_faithfulness_sources` below is what
    the metric uses now, keyed by `paper_id`.

    ADR 0015 shares this function with `src/agents/verifier.py`, whose
    abstract-path dossier is built from the returned keys. Changing the
    return shape here would change the verifier's prompt, which belongs
    to a different owner and a different lane, so the contract stays and
    the metric moved instead. **The verifier therefore still loses one
    of two same-surname, same-year papers**; ADR 0100 records that as an
    open follow-up for whoever holds `verifier.py` next, not as
    something this function quietly fixed underneath it.

    Public API — do not widen without reading ADR 0015 first.
    """
    year_by_id: dict[str, str] = {}
    for citation in citations:
        cited_year = citation["year"].strip()[:4]
        if cited_year:
            year_by_id[citation["paper_id"]] = cited_year

    index: dict[tuple[str, str], str] = {}
    for paper in papers:
        paper_year = year_by_id.get(paper["id"])
        if not paper_year or not paper["authors"]:
            continue
        first_author = paper["authors"][0].strip()
        if not first_author:
            continue
        lastname = first_author.split()[-1].lower()
        if lastname:
            index[(lastname, paper_year)] = paper["abstract"]
    return index


def _year_from_paper_id(paper_id: str) -> str:
    """The submission year encoded in an arXiv identifier, or `""`.

    arXiv ids carry `YYMM` in their first four digits — `2401.00001` and
    `cs.CL/0301001` alike — which makes the identifier the only
    year-bearing field `PaperMetadata` has. It is preferred over the
    citation's year for one reason: the citation list is written by the
    synthesizer, the same model whose output the metric is checking, and
    a metric that takes a document's identity from the text under
    examination has no way to catch a year the model invented. The
    retrieval pipeline wrote the id.

    Returns `""` for anything that is not a well-formed arXiv id, which
    is the signal to fall back to the citation's year — the local
    fixtures and every non-arXiv corpus land here.
    """
    canonical = canonical_arxiv_id(paper_id)
    if canonical is None:
        return ""
    tail = canonical.split(":", 1)[1].rsplit("/", 1)[-1]
    digits = tail[:4]
    # One guard, three ways to fail: too few characters to be a `YYMM`,
    # characters that are not digits, or a month nobody has. Each means
    # the id carries no date and the citation's year is the better
    # answer.
    if len(digits) != 4 or not digits.isdigit() or not 1 <= int(digits[2:]) <= 12:
        return ""
    two_digit_year = int(digits[:2])
    # arXiv opened in 1991 and its ids have never carried a century.
    # Anything from 91 up is the 1990s; everything else is 20xx, which
    # holds until 2091 and is documented rather than silently assumed.
    century = 1900 if two_digit_year >= 91 else 2000
    return str(century + two_digit_year)


def _base_key(lastname: str, year: str) -> str:
    """The normalised `(surname, year)` key, as one hashable string."""
    return f"{lastname}|{year}"


def _full_key(lastname: str, year: str, suffix: str) -> str:
    """The normalised full cite key, suffix included."""
    return f"{lastname}|{year}|{suffix.lower()}"


def build_faithfulness_sources(
    papers: list[PaperMetadata],
    citations: list[Citation],
    chunks_by_paper: Mapping[str, Sequence[str]] | None = None,
) -> SourceDossier:
    """Assemble the cited-source dossier, keyed by `paper_id` (EL-08).

    The replacement for `build_source_index` on the metric path, and the
    two fixes ADR 0100 makes to ADR 0007 live here.

    **Identity.** One entry per cited paper, keyed by `paper_id`, so two
    papers by a Zhang in 2024 are two entries rather than one. Each gets
    a cite key that is unique *within this dossier*: the base
    `Surname, Year`, plus a lowercase letter when the base is shared —
    the ordinary academic disambiguation, and a form the judge already
    understands. The paper's title is printed beside the key as a second
    way to tell them apart. Both the presented year and the citation's
    year are registered as resolution aliases, because the report's
    inline tags were written from the citation list and a dossier the
    report's own tags cannot address would trade one silent failure for
    another.

    **Scope.** `chunks_by_paper` maps `paper_id` to that paper's ranked
    reader chunks, in rank order. Supplied, they go into the dossier
    beside the abstract and the entry is `abstract_and_chunks`; omitted,
    the entry is `abstract_only` and the result says so. That is the
    ADR 0007 limitation made visible instead of assumed: the reader
    works from the top `reader_max_chunks_per_paper` chunks, so a judge
    given only abstracts marks every body-only claim unsupported and
    reports the harness's blind spot as the report's error.

    Args:
        papers: `state["papers"]` — the retrieval agent's metadata.
        citations: `state["citations"]` — the synthesizer's citation
            list. A paper with no citation entry is not cited and is
            omitted.
        chunks_by_paper: Optional `paper_id -> ranked chunk texts`.
            Empty or missing entries fall back to abstract-only for that
            paper. Blank chunks are dropped.

    Returns:
        A `SourceDossier`. `sources` is in `papers` order, so a dossier
        rendered twice from the same state is byte-identical.
    """
    year_by_id: dict[str, str] = {}
    for citation in citations:
        cited_year = citation["year"].strip()[:4]
        if cited_year:
            year_by_id[citation["paper_id"]] = cited_year

    # Pass one: identity and the presented year, per cited paper.
    staged: list[tuple[PaperMetadata, str, str, str]] = []
    for paper in papers:
        cited_year = year_by_id.get(paper["id"], "")
        if not cited_year or not paper["authors"]:
            continue
        first_author = paper["authors"][0].strip()
        if not first_author:
            continue
        # Non-empty after the strip, so `split()` has at least one token
        # and the last of them is a non-empty surname. No second guard.
        lastname = first_author.split()[-1].lower()
        year = _year_from_paper_id(paper["id"]) or cited_year
        staged.append((paper, lastname, year, cited_year))

    # Pass two: which base keys are shared, and therefore need a suffix.
    base_counts: dict[str, int] = {}
    for _, lastname, year, _ in staged:
        base_counts[_base_key(lastname, year)] = (
            base_counts.get(_base_key(lastname, year), 0) + 1
        )
    assigned: dict[str, int] = {}

    sources: list[SourceDocument] = []
    by_cite_key: dict[str, str] = {}
    by_base_key: dict[str, list[str]] = {}
    collisions = 0
    with_chunks = 0

    for paper, lastname, year, cited_year in staged:
        base = _base_key(lastname, year)
        suffix = ""
        if base_counts[base] > 1:
            collisions += 1
            index = assigned.get(base, 0)
            assigned[base] = index + 1
            # a, b, c … then aa, ab … past 26, which no real dossier
            # reaches but which must still produce distinct keys.
            suffix = _suffix_for(index)
        chunks = [
            text.strip()
            for text in (chunks_by_paper or {}).get(paper["id"], ())
            if text and text.strip()
        ]
        if chunks:
            with_chunks += 1
        sources.append(
            SourceDocument(
                paper_id=paper["id"],
                cite_key=f"{lastname.title()}, {year}{suffix}",
                lastname=lastname,
                year=year,
                suffix=suffix,
                title=paper["title"],
                abstract=paper["abstract"],
                chunks=chunks,
                source_scope=(
                    SOURCE_SCOPE_ABSTRACT_AND_CHUNKS
                    if chunks
                    else SOURCE_SCOPE_ABSTRACT_ONLY
                ),
            )
        )
        by_cite_key[_full_key(lastname, year, suffix)] = paper["id"]
        for alias in {year, cited_year}:
            bucket = by_base_key.setdefault(_base_key(lastname, alias), [])
            # One entry per paper: a `papers` list that repeats an id
            # must not make its own cite look contested.
            if paper["id"] not in bucket:
                bucket.append(paper["id"])

    return SourceDossier(
        sources=sources,
        by_cite_key=by_cite_key,
        by_base_key=by_base_key,
        collision_count=collisions,
        source_scope=(
            SOURCE_SCOPE_ABSTRACT_AND_CHUNKS
            if with_chunks
            else SOURCE_SCOPE_ABSTRACT_ONLY
        ),
        sources_with_chunks=with_chunks,
    )


def _suffix_for(index: int) -> str:
    """`0 -> "a"`, `25 -> "z"`, `26 -> "aa"`. Distinct for every index."""
    letters = ""
    position = index
    while True:
        letters = chr(ord("a") + position % 26) + letters
        position = position // 26 - 1
        if position < 0:
            return letters


def _build_faithfulness_prompt(report: str, dossier: SourceDossier) -> str:
    """Assemble the user message for the faithfulness judge.

    The report verbatim, then one block per cited paper. Each block
    opens with its cite key alone on a line — the mock judge (ADR 0095)
    reads the dossier back by exactly that shape, and a judge scanning
    for a key it was told to echo finds it at a line start — followed by
    the title, the abstract, and the reader's ranked excerpts when the
    caller supplied them.
    """
    if not dossier["sources"]:
        return f"Research briefing:\n\n{report}\n\nCited papers: (none provided)"

    blocks: list[str] = []
    for source in dossier["sources"]:
        lines = [
            f"[{source['cite_key']}]",
            f"Title: {source['title']}",
            f"Abstract: {source['abstract']}",
        ]
        if source["chunks"]:
            lines.append(
                f"Excerpts the briefing's author read, in rank order "
                f"({len(source['chunks'])}):"
            )
            lines += [
                f"  ({position}) {text}"
                for position, text in enumerate(source["chunks"], start=1)
            ]
        else:
            lines.append(
                "Excerpts: none available — judge this paper by its abstract."
            )
        blocks.append("\n".join(lines) + "\n")

    return (
        f"Research briefing:\n\n{report}\n\n"
        f"Cited papers:\n\n" + "\n".join(blocks)
    )


def resolve_cite(cite: str, dossier: SourceDossier) -> tuple[str | None, str]:
    """Map a judge-returned cite tag back to the paper it names.

    Three stages, and the order matters. An explicit suffix is honoured
    first, because that is the key the dossier actually printed. Failing
    that, the base `(surname, year)` is looked up — resolving only when
    exactly one cited paper answers to it. Two papers answering is
    `ambiguous_citation` and **stops there**: the old index resolved the
    same case by keeping whichever paper it wrote last, which is a coin
    flip published as a measurement.

    Args:
        cite: Whatever the judge put in the `cite` field, bracketed or
            not.
        dossier: The dossier the judge was shown.

    Returns:
        `(paper_id, resolution)`. `paper_id` is `None` for every
        resolution except `resolved`.
    """
    text = cite.strip()
    match = _SUFFIXED_CITE_PATTERN.match(text) or _SUFFIXED_CITE_PATTERN.match(
        f"[{text}]"
    )
    if not match:
        return None, CITE_MALFORMED
    lastname = _normalize_first_author(match.group(1))
    if not lastname:
        return None, CITE_MALFORMED
    year, suffix = match.group(2), match.group(3)

    if suffix:
        paper_id = dossier["by_cite_key"].get(_full_key(lastname, year, suffix))
        if paper_id is not None:
            return paper_id, CITE_RESOLVED

    candidates = dossier["by_base_key"].get(_base_key(lastname, year), [])
    if len(candidates) == 1:
        return candidates[0], CITE_RESOLVED
    if len(candidates) > 1:
        return None, CITE_AMBIGUOUS
    return None, CITE_UNRESOLVED


def _aggregate_claims(
    parsed: dict[str, Any],
    dossier: SourceDossier,
    judge: JudgeRequest | None = None,
) -> FaithfulnessResult:
    """Turn parsed judge output into a `FaithfulnessResult`.

    Defensively handles bad judge output — a missing or malformed
    `claims` field yields an empty result rather than an exception.
    Every claim is re-resolved against the dossier here rather than
    trusted from the judge: a verdict whose cite names no source we
    provided, or names two, becomes `supported=None` whatever the judge
    said, so a judge cannot manufacture support for a source it was
    never shown.

    The denominator is `supported + unsupported`. When that is empty the
    score is `None` with a reason, not 1.0 — and the two empty cases are
    told apart, because "the judge found nothing to check" and "we could
    not check anything the judge found" have different causes (ADR
    0100).
    """
    raw = parsed.get("claims", [])
    if not isinstance(raw, (list, tuple)):
        raw = []

    claims: list[ClaimJudgement] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cite = str(item.get("cite", "")).strip()
        claim_text = str(item.get("claim", "")).strip()
        if not claim_text or not cite:
            continue

        supported_raw = item.get("supported")
        judge_says: bool | None
        if isinstance(supported_raw, bool):
            judge_says = supported_raw
        else:
            # `null`, and anything that is neither a bool nor null —
            # a text-y "yes" is not a verdict and must not become one.
            judge_says = None

        paper_id, resolution = resolve_cite(cite, dossier)
        if resolution != CITE_RESOLVED:
            judge_says = None

        claims.append(
            ClaimJudgement(
                claim=claim_text,
                cite=cite,
                paper_id=paper_id,
                resolution=resolution,
                supported=judge_says,
                reason=str(item.get("reason", "")),
            )
        )

    supported = sum(1 for c in claims if c["supported"] is True)
    unsupported = sum(1 for c in claims if c["supported"] is False)
    source_unavailable = sum(1 for c in claims if c["supported"] is None)
    total = len(claims)

    denom = supported + unsupported
    reason: str | None = None
    if denom == 0:
        reason = NO_CITED_CLAIMS if total == 0 else ALL_SOURCES_UNAVAILABLE

    return FaithfulnessResult(
        score=supported / denom if denom > 0 else None,
        reason=reason,
        total_claims=total,
        supported=supported,
        unsupported=unsupported,
        source_unavailable=source_unavailable,
        ambiguous_citations=sum(
            1 for c in claims if c["resolution"] == CITE_AMBIGUOUS
        ),
        unresolved_citations=sum(
            1 for c in claims if c["resolution"] == CITE_UNRESOLVED
        ),
        malformed_citations=sum(
            1 for c in claims if c["resolution"] == CITE_MALFORMED
        ),
        collision_count=dossier["collision_count"],
        source_scope=dossier["source_scope"],
        sources_total=len(dossier["sources"]),
        sources_with_chunks=dossier["sources_with_chunks"],
        claims=claims,
        judge=judge,
    )


def _cite_key_from_string(cite: str) -> tuple[str, str] | None:
    """Extract `(lastname_lower, year)` from a `[Author, Year]` string.

    Returns `None` if the string does not match the expected shape.
    Reuses the same normalization rules as the citation-accuracy metric.
    """
    match = _CITE_PATTERN.match(cite.strip())
    if not match:
        # The judge may return the cite key without brackets. Try wrapping.
        match = _CITE_PATTERN.match(f"[{cite.strip()}]")
        if not match:
            return None
    author_field, year = match.group(1), match.group(2)
    lastname = _normalize_first_author(author_field)
    if not lastname:
        return None
    return (lastname, year)


def measure_faithfulness(
    report: str,
    papers: list[PaperMetadata],
    citations: list[Citation],
    chunks_by_paper: Mapping[str, Sequence[str]] | None = None,
) -> FaithfulnessResult:
    """Score the fraction of cited claims supported by their cited paper.

    Single LLM-as-judge call: the judge extracts each factual, cited
    claim from the report and decides whether the material provided for
    the cited paper supports it. Claims whose cite could not be resolved
    to exactly one provided source are excluded from the denominator and
    counted as `source_unavailable` (ADR 0007 chose that denominator;
    ADR 0100 kept it and made its three causes separable).

    **What the judge sees is a caller's decision (EL-09).** With
    `chunks_by_paper` supplied, each cited paper's entry carries the
    reader's ranked chunks beside its abstract and the result reports
    `source_scope="abstract_and_chunks"`. Without it, the entry is the
    abstract alone and the result says `abstract_only` — the ADR 0007
    substrate, on which a claim drawn from a paper's body is marked
    unsupported for want of the text rather than for want of truth. The
    two scopes are different instruments; do not average them.

    **Cost.** Supplying chunks grows the faithfulness input by roughly
    three to six times — the abstract is a few hundred tokens and the
    reader's chunks are several thousand per paper — which is an
    ESTIMATED +$0.07–0.12 per episode at present judge pricing. It is
    the only judge whose input grows; completeness and retrieval recall
    are unchanged.

    Empty report short-circuits to `score=None` with reason
    `empty_report` and makes no LLM call. It used to short-circuit to
    1.0, which awarded a perfect faithfulness mark to a run that wrote
    nothing.

    Args:
        report: Synthesized report markdown from the workflow.
        papers: `state["papers"]` — the retrieval agent's paper metadata.
        citations: `state["citations"]` — the synthesizer's citation list.
        chunks_by_paper: Optional `paper_id -> ranked chunk texts` for
            cited papers, in rank order. The campaign side supplies it
            from the persisted episode state; the offline runner and the
            mock judge do not, and land on `abstract_only`.

    Returns:
        `FaithfulnessResult` with the score, tallies, and per-claim
        decisions.
    """
    dossier = build_faithfulness_sources(papers, citations, chunks_by_paper)
    if not report.strip():
        return FaithfulnessResult(
            score=None,
            reason=EMPTY_REPORT,
            total_claims=0,
            supported=0,
            unsupported=0,
            source_unavailable=0,
            ambiguous_citations=0,
            unresolved_citations=0,
            malformed_citations=0,
            collision_count=dossier["collision_count"],
            source_scope=dossier["source_scope"],
            sources_total=len(dossier["sources"]),
            sources_with_chunks=dossier["sources_with_chunks"],
            claims=[],
            judge=None,
        )

    user_prompt = _build_faithfulness_prompt(report, dossier)
    judge = _judge_request(FaithfulnessJudgeOutput)
    # 8192, not 4096: the judge returns one verdict object per claim
    # over the full report, and the pre-flight scan measured routine
    # truncation-into-invalid-JSON at the old cap on long reports. An
    # output cap costs nothing unless tokens are actually generated,
    # so the low cap bought only wasted judge calls (same reasoning as
    # the synthesizer's cap in ADR 0041's follow-up).
    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=FAITHFULNESS_SYSTEM_PROMPT,
        model_name=judge_model(),
        max_tokens=8192,
        schema=FaithfulnessJudgeOutput,
        temperature=settings.eval_judge_temperature,
    )
    return _aggregate_claims(parsed, dossier, judge)


# ---------------------------------------------------------------------------
# Retrieval recall — is the retrieved paper set enough to cover the topics?
# ---------------------------------------------------------------------------

#: Version of the retrieval-recall rubric. See `COMPLETENESS_RUBRIC_VERSION`.
#:
#: 2.0.0 (ADR 0100), for the same reasons as completeness: no expected
#: topics now scores `None` rather than 1.0, and the call carries
#: `eval_judge_temperature` and `RetrievalRecallJudgeOutput`.
RETRIEVAL_RECALL_RUBRIC_VERSION: Final[str] = "2.0.0"

RETRIEVAL_RECALL_SYSTEM_PROMPT = """\
You are a strict retrieval-quality evaluator. Given a list of expected
research topics and a list of paper titles + abstracts, decide for each
topic whether AT LEAST ONE of the papers PLAUSIBLY COVERS it — i.e.
whether that paper would be a useful primary or secondary source for
writing about the topic.

Definitions:
  - "Plausibly covers" means: the abstract discusses the topic or an
    obvious component / synonym of the topic. Do not require the
    paper to be the definitive reference.
  - A paper that only mentions the topic in passing does NOT count.
  - You are evaluating the SEARCH results, not a final report. Do not
    penalize a topic just because no single paper covers ALL of it.

Return JSON matching this exact schema — the object alone, with no prose
around it and no markdown fencing. Where output schemas are enforced,
this is the schema they are enforced against:
{
  "coverage": [
    {"topic": "<verbatim topic>", "covered": true|false,
     "paper_ids": [<0-based indices into the paper list>],
     "reason": "<one short sentence>"}
  ]
}

Include one object per input topic, in the same order, and add no topic
that was not given to you. `paper_ids` is the list of paper indices you
consider strong matches for the topic (empty when covered is false). Be
strict — err toward "not covered" when the paper list doesn't clearly
support the topic.
"""

RETRIEVAL_RECALL_RUBRIC: Final[Rubric] = Rubric(
    name="retrieval_recall",
    version=RETRIEVAL_RECALL_RUBRIC_VERSION,
    prompt=RETRIEVAL_RECALL_SYSTEM_PROMPT,
)

#: Every versioned instrument the research campaign runs, in the order a
#: row records them. Three judges and one deterministic check.
#:
#: `groundedness` is here even though it calls no model, and that is the
#: correction ADR 0074 asked for: the test that used to assert this set
#: reasoned "a rubric version for a deterministic metric would be
#: provenance theatre", which confuses *has no judge* with *has no
#: definition*. The check publishes a version constant and a spec digest
#: precisely so a change to it can be seen from a row. Its presence is
#: also the mechanism by which swapping `citation_accuracy` for
#: `citation_resolution_rate` refuses to compare against an older
#: baseline instead of silently diffing across the swap.
#:
#: `citation_accuracy` remains absent: it publishes neither, so there is
#: nothing a lock could hold it to.
RESEARCH_RUBRICS: Final[tuple[Rubric, ...]] = (
    COMPLETENESS_RUBRIC,
    FAITHFULNESS_RUBRIC,
    GROUNDEDNESS_CHECK,
    RETRIEVAL_RECALL_RUBRIC,
)


class TopicRetrieval(TypedDict):
    """Per-topic decision emitted by the retrieval recall judge."""

    topic: str
    covered: bool
    paper_ids: list[int]
    reason: str


class RetrievalRecallResult(TypedDict):
    """Outcome of the retrieval recall metric.

    Shaped like `CompletenessResult` — same denominator, same `None`
    rule for an empty one (ADR 0100). A retrieved set that covers no
    topic still scores 0.0: that denominator is not empty, and 0.0 is a
    measurement.
    """

    score: float | None
    reason: str | None
    total_topics: int
    covered_topics: int
    coverage: list[TopicRetrieval]
    judge: JudgeRequest | None


def _build_retrieval_recall_prompt(
    papers: list[PaperMetadata], expected_topics: list[str]
) -> str:
    """Assemble the user message for the retrieval recall judge."""
    paper_block = "\n\n".join(
        f"[{i}] {paper['title']}\n{paper['abstract']}"
        for i, paper in enumerate(papers)
    )
    topic_lines = "\n".join(f"- {topic}" for topic in expected_topics)
    return (
        f"Retrieved papers:\n\n{paper_block}\n\n"
        f"Topics expected to be covered:\n{topic_lines}"
    )


def _aggregate_retrieval(
    parsed: dict[str, Any],
    requested_topics: list[str],
    n_papers: int,
    judge: JudgeRequest | None = None,
) -> RetrievalRecallResult:
    """Merge judge output with the requested topic list, defensively.

    Missing topics fall back to `covered=False`. Paper IDs are
    clamped to valid indices — a judge that hallucinates an out-of-
    range index gets the invalid IDs dropped rather than crashing.
    """
    judged_map = _judged_items(parsed, "coverage")

    coverage: list[TopicRetrieval] = []
    for topic in requested_topics:
        item = judged_map.get(topic)
        if item is None:
            coverage.append(
                TopicRetrieval(
                    topic=topic,
                    covered=False,
                    paper_ids=[],
                    reason="Judge did not return a decision for this topic.",
                )
            )
            continue

        raw_ids = item.get("paper_ids", ())
        if not isinstance(raw_ids, (list, tuple)):
            raw_ids = ()
        clean_ids = [
            int(pid)
            for pid in raw_ids
            if isinstance(pid, (int, bool)) and not isinstance(pid, bool)
            and 0 <= int(pid) < n_papers
        ]
        coverage.append(
            TopicRetrieval(
                topic=topic,
                covered=bool(item.get("covered", False)),
                paper_ids=clean_ids,
                reason=str(item.get("reason", "")),
            )
        )

    covered = sum(1 for c in coverage if c["covered"])
    total = len(requested_topics)

    return RetrievalRecallResult(
        score=covered / total if total > 0 else None,
        reason=None if total > 0 else NO_EXPECTED_TOPICS,
        total_topics=total,
        covered_topics=covered,
        coverage=coverage,
        judge=judge,
    )


def measure_retrieval_recall(
    papers: list[PaperMetadata],
    expected_topics: list[str],
) -> RetrievalRecallResult:
    """Score whether the retrieved paper set plausibly covers each expected topic.

    Complements `measure_completeness`: completeness asks "did the
    *report* cover the topic?", retrieval recall asks "did we *find
    the right papers* to cover the topic in the first place?"
    Together they isolate whether a regression is retrieval-side
    (search agent) or generation-side (reader / synthesizer).

    Empty inputs short-circuit without an LLM call, and the two are not
    the same answer (ADR 0100):
      - No topics: `score=None`, reason `no_expected_topics`. There is
        no denominator, so there is no rate — it used to report 1.0.
      - No papers, topics present: `score=0.0`, all topics uncovered.
        That denominator is real and the zero is earned.

    Args:
        papers: `state["papers"]` — the search agent's ranked output.
        expected_topics: Coverage targets from the benchmark query.

    Returns:
        `RetrievalRecallResult` with the aggregate score, counts, and
        per-topic decisions annotated with the paper indices the judge
        considered good matches.
    """
    if not expected_topics:
        return RetrievalRecallResult(
            score=None,
            reason=NO_EXPECTED_TOPICS,
            total_topics=0,
            covered_topics=0,
            coverage=[],
            judge=None,
        )
    if not papers:
        return RetrievalRecallResult(
            score=0.0,
            reason=None,
            total_topics=len(expected_topics),
            covered_topics=0,
            coverage=[
                TopicRetrieval(
                    topic=topic,
                    covered=False,
                    paper_ids=[],
                    reason="No papers retrieved.",
                )
                for topic in expected_topics
            ],
            judge=None,
        )

    user_prompt = _build_retrieval_recall_prompt(papers, expected_topics)
    judge = _judge_request(RetrievalRecallJudgeOutput)
    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=RETRIEVAL_RECALL_SYSTEM_PROMPT,
        model_name=judge_model(),
        max_tokens=2048,
        schema=RetrievalRecallJudgeOutput,
        temperature=settings.eval_judge_temperature,
    )
    return _aggregate_retrieval(parsed, expected_topics, len(papers), judge)
