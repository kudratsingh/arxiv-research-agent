"""Metrics for the offline eval pipeline.

Each metric lands as its own PR so its logic (and, where relevant, its
LLM-as-judge prompt) gets reviewed on its own. Full strategy in
`docs/eval.md`.

Landed:
  - citation_accuracy — pure regex + set membership, no LLM.
  - completeness — batched LLM-as-judge over expected topics
    (see ADR 0006).
  - faithfulness — extract-and-judge in one call against cited paper
    abstracts (see ADR 0007).
"""

import re
from typing import Any, TypedDict

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
    """Score the fraction of inline citations that resolve to the citation list.

    Parses `[Author, Year]` tags from the report body, deduplicates them,
    and checks each against a normalized index of the citation list.
    Normalization key: `(first-author-lastname-lowercased, 4-digit year)`.
    Year suffixes (`2023a`) are stripped before comparison; two-author
    (`X and Y`) and many-author (`X et al.`) styles keep only the first
    author's last name.

    A report with no inline citations returns `score=1.0` with
    `total_citations=0` — the metric doesn't apply. Callers who want to
    penalize uncited reports can check `total_citations` separately.

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
# Completeness — LLM-as-judge over expected topics.
# ---------------------------------------------------------------------------

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
        max_tokens=2048,
    )
    return _aggregate_coverage(parsed, expected_topics)


# ---------------------------------------------------------------------------
# Faithfulness — extract-and-judge each cited claim against its source.
# ---------------------------------------------------------------------------

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


def _build_source_index(
    papers: list[PaperMetadata], citations: list[Citation]
) -> dict[tuple[str, str], str]:
    """Join papers and citations on `paper_id` to produce a cite-key -> abstract map.

    Returns `{(first-author-lastname-lower, 4-digit-year): abstract}` for
    every cited paper we have both a citation entry and a `PaperMetadata`
    entry for.
    """
    year_by_id: dict[str, str] = {}
    for citation in citations:
        year = citation["year"].strip()[:4]
        if year:
            year_by_id[citation["paper_id"]] = year

    index: dict[tuple[str, str], str] = {}
    for paper in papers:
        year = year_by_id.get(paper["id"])
        if not year or not paper["authors"]:
            continue
        first_author = paper["authors"][0].strip()
        if not first_author:
            continue
        lastname = first_author.split()[-1].lower()
        if lastname:
            index[(lastname, year)] = paper["abstract"]
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

    source_index = _build_source_index(papers, citations)
    user_prompt = _build_faithfulness_prompt(report, source_index)
    parsed = call_llm_json(
        prompt=user_prompt,
        system_prompt=FAITHFULNESS_SYSTEM_PROMPT,
        max_tokens=4096,
    )
    return _aggregate_claims(parsed, source_index)
