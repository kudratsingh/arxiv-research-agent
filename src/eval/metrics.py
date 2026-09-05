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
  - faithfulness — extract-and-judge in one call against cited paper
    abstracts (see ADR 0007).
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

**A metric definition change rebaselines a campaign exactly as a prompt
edit does**, and ADR 0070's machinery is what records it: the
deterministic groundedness check rides in `RESEARCH_RUBRICS` under its
own version, so a row scored before this module read
`citation_resolution_rate` and a row scored after carry different
`provenance.rubric_versions`, and `regression_diff` refuses to compare
them (exit 3) instead of publishing a delta across two instruments.
"""

import re
from typing import Any, Final, TypedDict

from src.eval.groundedness import (
    GROUNDEDNESS_CHECK_VERSION,
    NORMALIZATION_SPEC,
    measure_groundedness,
)
from src.eval.provenance import Rubric, judge_model
from src.graph.state import Citation, PaperMetadata
from src.llm import call_llm_json

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
# Completeness — LLM-as-judge over expected topics.
# ---------------------------------------------------------------------------

#: Version of the completeness rubric below. Bumping it is the act that
#: declares "scores from before and after this edit are not comparable";
#: `tests/test_eval_rubric_versions.py` fails if the prompt text moves
#: without one (ADR 0070).
COMPLETENESS_RUBRIC_VERSION: Final[str] = "1.0.0"

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

Return JSON matching this exact schema, no markdown fencing:
{
  "coverage": [
    {"topic": "<verbatim topic>", "covered": true|false, "reason": "<one short sentence>"}
  ]
}

Include one object per input topic, in the same order. Be strict — err
toward "not covered" when in doubt.
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
    """Outcome of the completeness metric."""

    score: float
    total_topics: int
    covered_topics: int
    coverage: list[TopicCoverage]


def _build_completeness_prompt(report: str, topics: list[str]) -> str:
    """Assemble the user message for the completeness judge."""
    topic_lines = "\n".join(f"- {topic}" for topic in topics)
    return (
        f"Research briefing:\n\n{report}\n\n"
        f"Topics expected to be covered:\n{topic_lines}"
    )


def _aggregate_coverage(
    parsed: dict[str, Any], requested_topics: list[str]
) -> CompletenessResult:
    """Merge the judge's response with the requested topic list.

    Defensively handles judge output shape: missing topics are treated as
    uncovered with a note; extra / duplicate topics are ignored. The
    result always has exactly `len(requested_topics)` entries, in the
    same order as the input.
    """
    judged_map: dict[str, dict[str, Any]] = {}
    raw_coverage = parsed.get("coverage", [])
    if isinstance(raw_coverage, list):
        for item in raw_coverage:
            if isinstance(item, dict) and isinstance(item.get("topic"), str):
                # Keep the first occurrence if judge duplicates a topic.
                judged_map.setdefault(item["topic"], item)

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
    score = covered / total if total > 0 else 1.0

    return CompletenessResult(
        score=score,
        total_topics=total,
        covered_topics=covered,
        coverage=coverage,
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

    Empty `expected_topics` returns `score=1.0` with `total_topics=0` —
    the metric doesn't apply. Empty report is judged in the normal way
    (typically returns all-uncovered).

    Args:
        report: Synthesized report markdown from the workflow.
        expected_topics: Coverage targets from the benchmark query.

    Returns:
        `CompletenessResult` with aggregate score, counts, and per-topic
        decisions.
    """
    if not expected_topics:
        return CompletenessResult(
            score=1.0,
            total_topics=0,
            covered_topics=0,
            coverage=[],
        )

    user_prompt = _build_completeness_prompt(report, expected_topics)
    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=COMPLETENESS_SYSTEM_PROMPT,
        model_name=judge_model(),
        max_tokens=2048,
    )
    return _aggregate_coverage(parsed, expected_topics)


# ---------------------------------------------------------------------------
# Faithfulness — extract-and-judge each cited claim against its source.
# ---------------------------------------------------------------------------

#: Version of the faithfulness rubric. See `COMPLETENESS_RUBRIC_VERSION`.
FAITHFULNESS_RUBRIC_VERSION: Final[str] = "1.0.0"

FAITHFULNESS_SYSTEM_PROMPT = """\
You are a strict research report faithfulness evaluator. Given a research
briefing and the abstracts of the papers it cites, extract every factual
claim in the briefing that carries an inline citation, then decide whether
each claim is SUPPORTED by the cited paper's abstract.

Definitions:
  - A "factual claim" is a statement that could be true or false about the
    world — a method exists, an approach works, a result was observed.
    Skip transitional prose, framing sentences, and generic background.
  - "Supported" means: the paper's abstract either states the claim
    directly or clearly implies it. Reasonable paraphrase is fine; adding
    facts not present in the abstract is NOT.
  - If the cited paper's abstract is not provided (marked
    "abstract unavailable"), set supported to null.

Return JSON matching this exact schema, no markdown fencing:
{
  "claims": [
    {
      "claim": "the factual assertion, lightly paraphrased is fine",
      "cite": "[Author, Year]",
      "supported": true|false|null,
      "reason": "one-sentence justification, quoting the abstract when possible"
    }
  ]
}

Include one object per claim. Be strict — err toward "not supported" when
the abstract does not clearly back the claim.
"""

FAITHFULNESS_RUBRIC: Final[Rubric] = Rubric(
    name="faithfulness",
    version=FAITHFULNESS_RUBRIC_VERSION,
    prompt=FAITHFULNESS_SYSTEM_PROMPT,
)


class ClaimJudgement(TypedDict):
    """Per-claim decision emitted by the faithfulness judge."""

    claim: str
    cite: str
    supported: bool | None
    reason: str


class FaithfulnessResult(TypedDict):
    """Outcome of the faithfulness metric.

    `score` is `supported / (supported + unsupported)`. Claims whose
    cited source we could not provide (`supported=None`) are excluded
    from the denominator and reported separately via
    `source_unavailable` so callers can distinguish "the judge said no"
    from "we didn't have the source."
    """

    score: float
    total_claims: int
    supported: int
    unsupported: int
    source_unavailable: int
    claims: list[ClaimJudgement]


def build_source_index(
    papers: list[PaperMetadata], citations: list[Citation]
) -> dict[tuple[str, str], str]:
    """Join papers and citations on `paper_id` to produce a cite-key -> abstract map.

    Returns `{(first-author-lastname-lower, 4-digit-year): abstract}` for
    every cited paper we have both a citation entry and a `PaperMetadata`
    entry for.

    Public API — shared between the offline faithfulness metric (ADR
    0007) and the runtime verifier agent (ADR 0015) so both use the
    same citation-to-abstract join.
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


def _build_faithfulness_prompt(
    report: str, source_index: dict[tuple[str, str], str]
) -> str:
    """Assemble the user message for the faithfulness judge.

    Includes the report verbatim followed by an inline dossier of each
    cited paper's abstract, tagged with the `[Author, Year]` cite key
    the judge will match against.
    """
    if not source_index:
        return f"Research briefing:\n\n{report}\n\nCited papers: (none provided)"

    dossier_lines: list[str] = []
    for (lastname, year), abstract in source_index.items():
        # Present the cite key in title case for readability; matching is
        # case-insensitive downstream so the visual form doesn't matter.
        cite_key = f"[{lastname.title()}, {year}]"
        dossier_lines.append(f"{cite_key}\n{abstract}\n")

    dossier = "\n".join(dossier_lines)
    return (
        f"Research briefing:\n\n{report}\n\n"
        f"Cited papers (abstracts):\n\n{dossier}"
    )


def _aggregate_claims(
    parsed: dict[str, Any],
    source_index: dict[tuple[str, str], str],
) -> FaithfulnessResult:
    """Turn parsed judge output into a `FaithfulnessResult`.

    Defensively handles bad judge output — a missing / malformed
    `claims` field yields an empty result rather than an exception.
    Claims whose cite doesn't resolve to a known source are marked
    `supported=None` regardless of what the judge said, so the judge
    can't over-claim support for sources we didn't provide.
    """
    raw = parsed.get("claims", [])
    if not isinstance(raw, list):
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
        if supported_raw is None:
            judge_says = None
        elif isinstance(supported_raw, bool):
            judge_says = supported_raw
        else:
            # Non-bool, non-null - treat as None so we don't misattribute.
            judge_says = None

        # Cross-check the cite against our source index; if the judge
        # judged a claim against a source we didn't provide, force
        # supported=None regardless of what the judge returned.
        cite_key = _cite_key_from_string(cite)
        if cite_key is None or cite_key not in source_index:
            judge_says = None

        claims.append(
            ClaimJudgement(
                claim=claim_text,
                cite=cite,
                supported=judge_says,
                reason=str(item.get("reason", "")),
            )
        )

    supported = sum(1 for c in claims if c["supported"] is True)
    unsupported = sum(1 for c in claims if c["supported"] is False)
    source_unavailable = sum(1 for c in claims if c["supported"] is None)
    total = len(claims)

    denom = supported + unsupported
    score = supported / denom if denom > 0 else 1.0

    return FaithfulnessResult(
        score=score,
        total_claims=total,
        supported=supported,
        unsupported=unsupported,
        source_unavailable=source_unavailable,
        claims=claims,
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
) -> FaithfulnessResult:
    """Score the fraction of cited claims supported by their cited paper.

    Single LLM-as-judge call: the judge extracts each factual, cited
    claim from the report and decides whether the cited paper's abstract
    supports it. Claims whose cited paper we could not provide the
    abstract for are excluded from the score denominator and reported as
    `source_unavailable` (see ADR 0007 for the denominator choice and the
    abstract-only source decision).

    Empty report short-circuits to `score=1.0` with `total_claims=0` and
    makes no LLM call.

    Args:
        report: Synthesized report markdown from the workflow.
        papers: `state["papers"]` — the retrieval agent's paper metadata.
        citations: `state["citations"]` — the synthesizer's citation list.

    Returns:
        `FaithfulnessResult` with the score, tallies, and per-claim
        decisions.
    """
    if not report.strip():
        return FaithfulnessResult(
            score=1.0,
            total_claims=0,
            supported=0,
            unsupported=0,
            source_unavailable=0,
            claims=[],
        )

    source_index = build_source_index(papers, citations)
    user_prompt = _build_faithfulness_prompt(report, source_index)
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
    )
    return _aggregate_claims(parsed, source_index)


# ---------------------------------------------------------------------------
# Retrieval recall — is the retrieved paper set enough to cover the topics?
# ---------------------------------------------------------------------------

#: Version of the retrieval-recall rubric. See `COMPLETENESS_RUBRIC_VERSION`.
RETRIEVAL_RECALL_RUBRIC_VERSION: Final[str] = "1.0.0"

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

Return JSON matching this exact schema, no markdown fencing:
{
  "coverage": [
    {"topic": "<verbatim topic>", "covered": true|false,
     "paper_ids": [<0-based indices into the paper list>],
     "reason": "<one short sentence>"}
  ]
}

Include one object per input topic, in the same order. `paper_ids` is
the list of paper indices you consider strong matches for the topic
(empty when covered is false). Be strict — err toward "not covered"
when the paper list doesn't clearly support the topic.
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
    """Outcome of the retrieval recall metric."""

    score: float
    total_topics: int
    covered_topics: int
    coverage: list[TopicRetrieval]


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
) -> RetrievalRecallResult:
    """Merge judge output with the requested topic list, defensively.

    Missing topics fall back to `covered=False`. Paper IDs are
    clamped to valid indices — a judge that hallucinates an out-of-
    range index gets the invalid IDs dropped rather than crashing.
    """
    judged_map: dict[str, dict[str, Any]] = {}
    raw = parsed.get("coverage", [])
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("topic"), str):
                judged_map.setdefault(item["topic"], item)

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

        raw_ids = item.get("paper_ids", [])
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
    score = covered / total if total > 0 else 1.0

    return RetrievalRecallResult(
        score=score,
        total_topics=total,
        covered_topics=covered,
        coverage=coverage,
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

    Empty inputs short-circuit without an LLM call:
      - No topics: `score=1.0`, `total_topics=0`.
      - No papers with topics: `score=0.0`, all topics uncovered.

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
            score=1.0,
            total_topics=0,
            covered_topics=0,
            coverage=[],
        )
    if not papers:
        return RetrievalRecallResult(
            score=0.0,
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
        )

    user_prompt = _build_retrieval_recall_prompt(papers, expected_topics)
    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=RETRIEVAL_RECALL_SYSTEM_PROMPT,
        model_name=judge_model(),
        max_tokens=2048,
    )
    return _aggregate_retrieval(parsed, expected_topics, len(papers))
