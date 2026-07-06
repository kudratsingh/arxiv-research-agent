"""Metrics for the offline eval pipeline.

Each metric lands as its own PR so its logic (and, where relevant, its
LLM-as-judge prompt) gets reviewed on its own. Full strategy in
`docs/eval.md`.

Landed:
  - citation_accuracy — pure regex + set membership, no LLM.

Follow-ups:
  - completeness  (feat/eval-metrics-completeness)  — LLM-as-judge
  - faithfulness  (feat/eval-metrics-faithfulness)  — LLM-as-judge
"""

import re
from typing import TypedDict

from src.graph.state import Citation

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
