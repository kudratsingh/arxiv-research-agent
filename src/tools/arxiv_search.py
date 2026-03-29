"""arXiv API wrapper for searching and retrieving paper metadata."""

import time
import xml.etree.ElementTree as ET

import requests

from src.graph.state import PaperMetadata

ARXIV_API_URL = "http://arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"


def search_arxiv(query: str, max_results: int = 5) -> list[PaperMetadata]:
    """Search arXiv for papers matching a query.

    Uses the main arxiv.org API endpoint directly with requests
    to avoid rate limiting issues with export.arxiv.org.

    Args:
        query: Search query string (keyword phrase).
        max_results: Maximum number of results to return per query.

    Returns:
        List of paper metadata dicts.
    """
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    try:
        for attempt in range(3):
            resp = requests.get(
                ARXIV_API_URL, params=params, timeout=30, allow_redirects=True
            )
            if resp.status_code == 200 and "Rate exceeded" not in resp.text:
                break
            time.sleep(5 * (attempt + 1))
        else:
            print(f"  [search] arXiv rate limited for query: {query}")
            return []

        if "Rate exceeded" in resp.text:
            print(f"  [search] arXiv rate limited for query: {query}")
            return []
    except (requests.RequestException, OSError) as e:
        print(f"  [search] arXiv request failed for query '{query}': {e}")
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
