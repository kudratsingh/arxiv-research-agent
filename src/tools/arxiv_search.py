"""arXiv API wrapper for searching and retrieving paper metadata.

Uses HTTPS for the arXiv Atom feed (an in-flight MITM otherwise gets
to inject attacker-chosen `PaperMetadata` that drives Claude prompts
and PDF fetches downstream) and `defusedxml` to parse the response
(closes XML-external-entity / billion-laughs attacks on the parser).
See ADR 0033.

`search_arxiv` can distinguish "arXiv was unreachable" from "arXiv
answered with zero hits" via `raise_on_unavailable` — the search agent
needs that distinction to fail a job with an honest error name instead
of conflating an outage with an empty topic (ADR 0041). The default
(`False`) preserves the historical return-`[]` contract for existing
callers and tests.
"""

from __future__ import annotations

import re

import requests
from defusedxml import ElementTree as ET

from src.errors import UpstreamArxiv
from src.graph.state import PaperMetadata
from src.observability import get_logger
from src.tools.http_session import build_retrying_session

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"

# arXiv IDs as they appear in abs/pdf URLs, with an optional version
# suffix. Used for canonical dedup keys (ADR 0041): the same paper can
# arrive as `http://arxiv.org/abs/2311.09000v1` (Atom feed) and
# `https://arxiv.org/abs/2311.09000` (Semantic Scholar external ID),
# and both must collide to one entry.
_ARXIV_ABS_ID = re.compile(r"arxiv\.org/abs/([^?#]+?)(?:v\d+)?/?$", re.IGNORECASE)

log = get_logger(__name__)


class ArxivUnavailableError(UpstreamArxiv):
    """arXiv could not serve results — outage, rate limit, or bad response.

    Raised (only when a caller opts in via `raise_on_unavailable`) for a
    connection failure, a non-200 status, or arXiv's in-band 200
    "Rate exceeded" body. Distinct from a legitimate empty result set,
    which is a successful search that found nothing.

    Re-parented onto `UpstreamArxiv` by ADR 0064, so the job's
    `error_type` is now the stable code `upstream_arxiv` rather than
    this class's name — the name can be refactored without forking a
    metric series or breaking a client branch.
    """


def search_arxiv(
    query: str,
    max_results: int = 5,
    *,
    raise_on_unavailable: bool = False,
) -> list[PaperMetadata]:
    """Search arXiv for papers matching a query.

    Uses the main arxiv.org API endpoint through a retrying session
    (see `tools/http_session.build_retrying_session`) so transient
    429s and 5xxs don't turn into empty result sets.

    Args:
        query: Search query string (keyword phrase).
        max_results: Maximum number of results to return per query.
        raise_on_unavailable: When True, a hard failure (connection
            error, non-200, in-band rate-limit body) raises
            `ArxivUnavailableError` instead of returning `[]`, so the
            caller can tell an outage apart from zero hits.

    Returns:
        List of paper metadata dicts. Empty list on hard failure when
        `raise_on_unavailable` is False (historical contract), or on a
        successful search that genuinely matched nothing.

    Raises:
        ArxivUnavailableError: Hard failure with
            `raise_on_unavailable=True`.
    """
    params: dict[str, str | int] = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    session = build_retrying_session()
    try:
        resp = session.get(
            ARXIV_API_URL, params=params, timeout=30, allow_redirects=True
        )
    except (requests.RequestException, OSError) as exc:
        log.warning(
            "arxiv_search_request_failed",
            extra={"query": query, "error": str(exc)},
        )
        if raise_on_unavailable:
            raise ArxivUnavailableError(
                f"arXiv request failed: {type(exc).__name__}: {exc}"
            ) from exc
        return []

    if resp.status_code != 200 or "Rate exceeded" in resp.text:
        log.warning(
            "arxiv_search_rate_limited",
            extra={"query": query, "status": resp.status_code},
        )
        if raise_on_unavailable:
            raise ArxivUnavailableError(
                f"arXiv refused to serve results (status {resp.status_code})"
            )
        return []

    root = ET.fromstring(resp.text)
    papers: list[PaperMetadata] = []

    for entry in root.findall(f"{ATOM_NS}entry"):
        entry_id = entry.findtext(f"{ATOM_NS}id", "")
        # Titles must come out single-line and length-capped: the reader
        # interpolates them into its prompt outside the untrusted-content
        # tags, and that is only safe on a normalized title (ADR 0020 /
        # ADR 0041). Collapse all whitespace runs, not just newlines.
        title = " ".join(entry.findtext(f"{ATOM_NS}title", "").split())[:300]
        abstract = entry.findtext(f"{ATOM_NS}summary", "").strip().replace("\n", " ")

        # Skip entries that are just API metadata (no real title)
        if not title or title.startswith("Error"):
            continue

        authors = [
            name.text or ""
            for author in entry.findall(f"{ATOM_NS}author")
            for name in author.findall(f"{ATOM_NS}name")
        ]

        pdf_url = ""
        for link in entry.findall(f"{ATOM_NS}link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")

        papers.append(
            PaperMetadata(
                id=entry_id,
                title=title,
                authors=authors,
                abstract=abstract,
                url=entry_id,
                pdf_url=pdf_url,
            )
        )

    return papers


def canonical_paper_key(paper_id: str) -> str:
    """Reduce a paper ID to the form used for dedup comparisons.

    arXiv-URL ids collapse to `arxiv:<bare-id>` — scheme, host case,
    trailing slash, and the `vN` version suffix are all erased, because
    the same paper arrives as `http://arxiv.org/abs/2311.09000v1` from
    the Atom feed and as `https://arxiv.org/abs/2311.09000` from the
    Semantic Scholar external-ID mapping. Version-insensitive is
    deliberate: two versions of one preprint are one paper for
    retrieval purposes, and reading both would double-bill the reader
    for near-identical text (ADR 0023 / ADR 0041).

    Non-arXiv ids pass through unchanged.

    Args:
        paper_id: The `PaperMetadata.id` value from any source.

    Returns:
        A canonical key string suitable for equality comparison.
    """
    match = _ARXIV_ABS_ID.search(paper_id)
    if match:
        return f"arxiv:{match.group(1).lower()}"
    return paper_id


def deduplicate_papers(papers: list[PaperMetadata]) -> list[PaperMetadata]:
    """Remove duplicate papers, keeping the first occurrence.

    Keys on `canonical_paper_key` rather than the raw `id` so
    arXiv-sourced entries (versioned, `http://`) collide with
    Semantic-Scholar-sourced entries for the same paper (unversioned,
    `https://`) as ADR 0023 promises.
    """
    seen: set[str] = set()
    unique: list[PaperMetadata] = []
    for paper in papers:
        key = canonical_paper_key(paper["id"])
        if key not in seen:
            seen.add(key)
            unique.append(paper)
    return unique
