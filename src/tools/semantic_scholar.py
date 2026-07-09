"""Semantic Scholar Graph API adapter (ADR 0023).

Second source alongside arXiv: broader coverage (conferences, journals,
non-arXiv preprints) plus one-hop citation-graph traversal via
`get_references`. Used by the search agent to enrich arXiv seeds with
their references when `settings.enable_semantic_scholar` is on.

Every S2 paper is mapped to the workflow's `PaperMetadata` shape. When
the paper carries an arXiv external ID we surface the arXiv URL as the
paper's `id` — that way S2-sourced papers dedupe naturally against
arXiv-sourced ones (`arxiv_search.deduplicate_papers` keys off `id`).
Otherwise we prefix the S2 paperId with `s2:` so it's still unique but
obviously distinguishable in logs.

Papers without an abstract are dropped at the adapter boundary. The
reader's abstract-fallback path (ADR 0004) needs *some* text; a paper
with neither PDF nor abstract can't be analyzed regardless of source.
"""

from __future__ import annotations

from typing import Any

from src.config import settings
from src.graph.state import PaperMetadata
from src.observability import get_logger
from src.tools.http_session import build_retrying_session

log = get_logger(__name__)

S2_API_BASE = "https://api.semanticscholar.org/graph/v1"

# Fields we pull for every paper. The API rejects unknown fields (400)
# so keep this in sync with what `_map_s2_paper` reads.
_PAPER_FIELDS = (
    "paperId,title,abstract,authors,openAccessPdf,externalIds,year,venue"
)


def _headers() -> dict[str, str]:
    """Build the auth header dict — anonymous when no API key is set."""
    if settings.semantic_scholar_api_key:
        return {"x-api-key": settings.semantic_scholar_api_key}
    return {}


def _map_s2_paper(item: dict[str, Any]) -> PaperMetadata | None:
    """Convert one Semantic Scholar paper object to `PaperMetadata`.

    Returns `None` when the paper is unusable (no abstract, no title, or
    can't produce a stable ID). Silent-drop is deliberate: enrichment
    should degrade gracefully when S2 returns a sparse record.
    """
    if not isinstance(item, dict):
        return None

    title = str(item.get("title") or "").strip()
    abstract = item.get("abstract")
    if not title or not isinstance(abstract, str) or not abstract.strip():
        return None

    authors_raw = item.get("authors") or []
    authors: list[str] = []
    if isinstance(authors_raw, list):
        for a in authors_raw:
            if isinstance(a, dict):
                name = str(a.get("name") or "").strip()
                if name:
                    authors.append(name)

    external = item.get("externalIds") or {}
    arxiv_id = None
    if isinstance(external, dict):
        arxiv_id_raw = external.get("ArXiv")
        if isinstance(arxiv_id_raw, str) and arxiv_id_raw.strip():
            arxiv_id = arxiv_id_raw.strip()

    # Prefer the arXiv URL as the paper id so this record dedupes
    # against arXiv-sourced entries. Fall back to a namespaced S2 id.
    if arxiv_id:
        paper_id = f"http://arxiv.org/abs/{arxiv_id}"
        landing_url = f"http://arxiv.org/abs/{arxiv_id}"
    else:
        s2_id = str(item.get("paperId") or "").strip()
        if not s2_id:
            return None
        paper_id = f"s2:{s2_id}"
        landing_url = f"https://www.semanticscholar.org/paper/{s2_id}"

    # openAccessPdf.url when available; empty string forces the reader's
    # abstract-only path (ADR 0004) without an HTTP fetch attempt.
    pdf_url = ""
    oa = item.get("openAccessPdf")
    if isinstance(oa, dict):
        candidate = str(oa.get("url") or "").strip()
        if candidate:
            pdf_url = candidate
    if not pdf_url and arxiv_id:
        pdf_url = f"http://arxiv.org/pdf/{arxiv_id}"

    return PaperMetadata(
        id=paper_id,
        title=title,
        authors=authors,
        abstract=abstract.strip(),
        url=landing_url,
        pdf_url=pdf_url,
    )


def _get_json(path: str, params: dict[str, Any]) -> Any | None:
    """GET a JSON body from the S2 API, or `None` on any recoverable error.

    Recoverable errors (network exception, non-2xx status after the
    session's built-in retries have exhausted, JSON parse failure) are
    logged and swallowed. Enrichment is optional — S2 flaking out
    should never derail a workflow.
    """
    session = build_retrying_session()
    url = f"{S2_API_BASE}{path}"
    try:
        response = session.get(
            url,
            params=params,
            headers=_headers(),
            timeout=settings.semantic_scholar_timeout_sec,
        )
    except Exception as exc:  # noqa: BLE001 — network is not fatal for enrichment
        log.warning(
            "semantic_scholar_request_failed",
            extra={"url": url, "error": str(exc)},
        )
        return None

    if not response.ok:
        log.warning(
            "semantic_scholar_bad_status",
            extra={"url": url, "status_code": response.status_code},
        )
        return None
    try:
        return response.json()
    except ValueError as exc:
        log.warning(
            "semantic_scholar_bad_json",
            extra={"url": url, "error": str(exc)},
        )
        return None


def search_papers(query: str, limit: int = 10) -> list[PaperMetadata]:
    """Search Semantic Scholar for papers matching `query`.

    Returns up to `limit` papers with abstracts, mapped to
    `PaperMetadata`. Empty list on any hard failure (see `_get_json`).

    Not currently wired into the main workflow — the search agent uses
    references-based enrichment (`get_references`) rather than a direct
    S2 search. Exposed here for future portfolio work (e.g. a "search
    other sources" supervisor action).
    """
    if limit <= 0 or not query.strip():
        return []
    payload = _get_json(
        "/paper/search",
        params={
            "query": query,
            "limit": limit,
            "fields": _PAPER_FIELDS,
        },
    )
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") or []
    if not isinstance(data, list):
        return []
    papers: list[PaperMetadata] = []
    for item in data:
        mapped = _map_s2_paper(item)
        if mapped is not None:
            papers.append(mapped)
    return papers


def get_references(paper_id: str, limit: int = 5) -> list[PaperMetadata]:
    """One-hop reference-graph traversal for a paper.

    Given an S2 paperId OR any of the "external ID" formats S2 accepts
    (`ARXIV:2311.09000`, `DOI:...`, etc.), fetch that paper's cited
    references and return up to `limit` of them as `PaperMetadata`.

    The workflow uses this to expand each arXiv seed paper by its
    references, giving the reader broader material to analyze without
    a new search round.
    """
    if limit <= 0 or not paper_id.strip():
        return []
    payload = _get_json(
        f"/paper/{paper_id}/references",
        params={
            "limit": limit,
            "fields": _PAPER_FIELDS,
        },
    )
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") or []
    if not isinstance(data, list):
        return []
    papers: list[PaperMetadata] = []
    for edge in data:
        if not isinstance(edge, dict):
            continue
        # The references endpoint wraps each entry in `{citedPaper: {...}}`.
        cited = edge.get("citedPaper")
        if not isinstance(cited, dict):
            continue
        mapped = _map_s2_paper(cited)
        if mapped is not None:
            papers.append(mapped)
    return papers


def _arxiv_url_to_s2_id(paper_id: str) -> str:
    """Convert one of our arXiv URL ids to an S2-accepted external ID.

    S2's REST API accepts `ARXIV:<arxiv_id>` as a paper identifier —
    handy because our arXiv-sourced papers carry the URL form as their
    `id`. Non-arXiv ids pass through unchanged (S2 already accepts its
    own paperId).
    """
    marker = "arxiv.org/abs/"
    idx = paper_id.find(marker)
    if idx >= 0:
        arxiv_id = paper_id[idx + len(marker):].strip("/")
        if arxiv_id:
            return f"ARXIV:{arxiv_id}"
    if paper_id.startswith("s2:"):
        return paper_id[3:]
    return paper_id
