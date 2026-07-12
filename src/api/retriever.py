"""Prior-report retrieval for conversation follow-ups (ADR 0032).

Takes a `Conversation` (with prior jobs) and a new query, chunks
each prior report by markdown section, and returns the top-K
chunks by cosine similarity against the query. Uses the shared
MiniLM embeddings + FAISS from `src.tools.embeddings` /
`src.tools.chunk_ranker`, so the embedding cache from ADR 0028
warms up over conversation lifetime.

The retriever is a plain function (not a class) because it holds
no state — inputs are the conversation + query, outputs are the
top-K chunks. Called from the runner right before the workflow
executes; the retrieved chunks land on `ResearchState.prior_context`
and the planner reads them from there.
"""

from __future__ import annotations

import re
from typing import TypedDict

import numpy as np

from src.api.conversations import Conversation
from src.observability import get_logger
from src.tools.embeddings import encode_texts

log = get_logger(__name__)

MIN_CHUNK_CHARS = 80
MAX_CHUNK_CHARS = 900  # ~225 tokens; small enough to fit K=5 comfortably


class RetrievedChunk(TypedDict):
    """A snippet from a prior report, ranked by relevance to the new query."""

    job_id: str
    ordinal: int
    query: str
    section: str
    text: str
    relevance_score: float


class _ReportChunk(TypedDict):
    """Internal — before ranking is applied."""

    job_id: str
    ordinal: int
    query: str
    section: str
    text: str


# ---------------------------------------------------------------------------
# Chunking: split markdown reports by heading, then size-cap each section.
# ---------------------------------------------------------------------------

# Matches ATX-style markdown headings up to H3 at line start.
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)


def _split_report_by_heading(report: str) -> list[tuple[str, str]]:
    """Return `[(section_title, section_body), ...]` for a markdown
    report. Content before the first heading falls under an empty
    section title.
    """
    sections: list[tuple[str, str]] = []
    matches = list(_HEADING_RE.finditer(report))
    if not matches:
        return [("", report.strip())]

    # Preamble (content before any heading).
    preamble = report[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for i, m in enumerate(matches):
        title = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(report)
        body = report[body_start:body_end].strip()
        # Skip a heading with an empty body — nothing to retrieve.
        if body:
            sections.append((title, body))
    return sections


def _size_cap(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split a long section into paragraph-boundary chunks under
    `max_chars`. Paragraphs are the natural break; if a single
    paragraph exceeds the budget, hard-split it.
    """
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            # Flush current, then hard-split the oversize paragraph.
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(para), max_chars):
                chunks.append(para[start : start + max_chars])
            continue
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks


def _report_to_chunks(job_id: str, ordinal: int, query: str, report: str) -> list[_ReportChunk]:
    chunks: list[_ReportChunk] = []
    for section_title, body in _split_report_by_heading(report):
        for text in _size_cap(body):
            if len(text) < MIN_CHUNK_CHARS:
                continue
            chunks.append(
                _ReportChunk(
                    job_id=job_id,
                    ordinal=ordinal,
                    query=query,
                    section=section_title,
                    text=text,
                )
            )
    return chunks


# ---------------------------------------------------------------------------
# Retrieval — encode + rank against the new query.
# ---------------------------------------------------------------------------


def retrieve_prior_context(
    conversation: Conversation,
    query: str,
    top_k: int,
) -> list[RetrievedChunk]:
    """Rank prior-report chunks by cosine similarity to `query`.

    Returns at most `top_k` chunks, ordered by descending
    relevance. Empty list when the conversation has no jobs yet.

    Cosine similarity is computed via `numpy.dot` on L2-normalized
    embeddings (matches ADR 0028's `encode_texts` normalization).
    FAISS is available but overkill for the tens-of-chunks scale a
    conversation produces; a straight dot-product is cheaper and
    keeps the dependency graph flat.
    """
    if top_k <= 0:
        return []
    if not conversation.jobs:
        return []

    chunks: list[_ReportChunk] = []
    for job in conversation.jobs:
        chunks.extend(_report_to_chunks(job.job_id, job.ordinal, job.query, job.report))

    if not chunks:
        return []

    chunk_embeddings = encode_texts([c["text"] for c in chunks])
    query_embedding = encode_texts([query])[0]

    # `encode_texts` L2-normalizes; dot product = cosine similarity.
    scores = np.dot(chunk_embeddings, query_embedding)
    top_indices = np.argsort(-scores)[:top_k]

    result: list[RetrievedChunk] = []
    for i in top_indices:
        idx = int(i)
        chunk = chunks[idx]
        result.append(
            RetrievedChunk(
                job_id=chunk["job_id"],
                ordinal=chunk["ordinal"],
                query=chunk["query"],
                section=chunk["section"],
                text=chunk["text"],
                relevance_score=float(scores[idx]),
            )
        )
    log.info(
        "conversation_context_retrieved",
        extra={
            "conversation_id": conversation.conversation_id,
            "n_chunks_indexed": len(chunks),
            "n_returned": len(result),
        },
    )
    return result


def format_context_for_planner(chunks: list[RetrievedChunk]) -> str:
    """Compact prompt block for the planner's system prompt.

    Structured as `[job N, section: TITLE] snippet` so the planner
    can reason about which prior query each fact came from. Empty
    string when there's no context, so callers can append
    unconditionally.
    """
    if not chunks:
        return ""
    lines = ["## Prior findings from this conversation"]
    for chunk in chunks:
        section = chunk["section"] or "(introduction)"
        header = f"[query {chunk['ordinal']}: {chunk['query']} · section: {section}]"
        lines.append(header)
        lines.append(chunk["text"])
        lines.append("")
    return "\n".join(lines).rstrip()
