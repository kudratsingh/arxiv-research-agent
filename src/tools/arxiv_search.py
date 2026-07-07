"""arXiv API wrapper for searching and retrieving paper metadata."""

import xml.etree.ElementTree as ET

import requests

from src.graph.state import PaperMetadata
from src.observability import get_logger
from src.tools.http_session import build_retrying_session

ARXIV_API_URL = "http://arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"

log = get_logger(__name__)


def search_arxiv(query: str, max_results: int = 5) -> list[PaperMetadata]:
    """Search arXiv for papers matching a query.

    Uses the main arxiv.org API endpoint through a retrying session
    (see `tools/http_session.build_retrying_session`) so transient
    429s and 5xxs don't turn into empty result sets.

    Args:
        query: Search query string (keyword phrase).
        max_results: Maximum number of results to return per query.

    Returns:
        List of paper metadata dicts. Empty list on hard failure —
        callers fall back to mock data / continue with fewer papers.
    """
    params = {
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
        return []

    if resp.status_code != 200 or "Rate exceeded" in resp.text:
        log.warning(
            "arxiv_search_rate_limited",
            extra={"query": query, "status": resp.status_code},
        )
        return []

    root = ET.fromstring(resp.text)
    papers: list[PaperMetadata] = []

    for entry in root.findall(f"{ATOM_NS}entry"):
        entry_id = entry.findtext(f"{ATOM_NS}id", "")
        title = entry.findtext(f"{ATOM_NS}title", "").strip().replace("\n", " ")
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


def deduplicate_papers(papers: list[PaperMetadata]) -> list[PaperMetadata]:
    """Remove duplicate papers by ID, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[PaperMetadata] = []
    for paper in papers:
        if paper["id"] not in seen:
            seen.add(paper["id"])
            unique.append(paper)
    return unique
