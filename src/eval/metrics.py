"""Metrics for the offline eval pipeline.

Each metric lands as its own PR so its logic (and, where relevant, its
LLM-as-judge prompt) gets reviewed on its own. Full strategy in
`docs/eval.md`.

Landed:
  - citation_accuracy — pure regex + set membership, no LLM.
  - completeness — batched LLM-as-judge over expected topics
    (see ADR 0006).

Follow-ups:
  - faithfulness  (feat/eval-metrics-faithfulness)  — LLM-as-judge
"""

import re
from typing import Any, TypedDict

from src.graph.state import Citation
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
