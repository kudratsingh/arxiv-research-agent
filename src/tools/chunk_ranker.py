"""FAISS-backed relevance ranking of paper chunks against sub-questions.

Sits between `chunker.chunk_paper` and the reader agent: given a paper's
chunks and the planner's sub-questions, return the top-K chunks whose
cosine similarity to *any* sub-question is highest. This is how full-text
ingestion stays cost-bounded — the reader consumes a handful of focused
snippets per paper instead of every page.

Pure w.r.t. its inputs (aside from the shared MiniLM singleton in
`embeddings`) — safe inside the reader's concurrent fan-out.
"""

from typing import TypedDict

import faiss
import numpy as np

from src.tools.chunker import Chunk
from src.tools.embeddings import encode_texts

DEFAULT_TOP_K = 8


class RankedChunk(TypedDict):
    """A chunk annotated with its cosine-similarity score."""

    section: str
    text: str
    chunk_index: int
    relevance_score: float


def _max_similarity_per_chunk(
    scores: np.ndarray, indices: np.ndarray, n_chunks: int
) -> list[float]:
    """Reduce a FAISS (n_queries, n_results) result to per-chunk max similarity.

    For each chunk index we take the highest similarity across all
    sub-questions — a chunk that strongly answers *any* sub-question is
    considered relevant. Chunks never returned by FAISS get a score of 0.

    Args:
        scores: `(n_queries, n_results)` similarity matrix from FAISS.
        indices: `(n_queries, n_results)` chunk indices (may contain -1
            padding when there are fewer results than requested).
        n_chunks: Total number of chunks in the input list.

    Returns:
        List of length `n_chunks` with the max similarity per chunk.
    """
    max_score = [0.0] * n_chunks
    n_queries, n_results = scores.shape
    for q in range(n_queries):
        for r in range(n_results):
            chunk_idx = int(indices[q][r])
            if chunk_idx < 0 or chunk_idx >= n_chunks:
                continue
            score = float(scores[q][r])
            if score > max_score[chunk_idx]:
                max_score[chunk_idx] = score
    return max_score


def _to_ranked_chunk(chunk: Chunk, score: float) -> RankedChunk:
    return RankedChunk(
        section=chunk["section"],
        text=chunk["text"],
        chunk_index=chunk["chunk_index"],
        relevance_score=score,
    )


def _apply_preferred_sections(
    ranked_order: list[int],
    chunks: list[Chunk],
    top_k: int,
    preferred_sections: list[str],
) -> list[int]:
    """Reserve top_k // 2 slots for chunks whose section matches `preferred_sections`.

    Used by the reader's recovery path (ADR 0019): after the reader
    signals it wants "results" or "limitations" re-read, we guarantee
    at least some chunks from those sections make the cut, even if
    they'd otherwise be edged out by higher-scoring intro / method
    chunks. Preferred chunks come first in the returned order so the
    reader prompt shows them prominently.

    Section-name comparison is case-insensitive.
    """
    preferred = {s.strip().lower() for s in preferred_sections if s.strip()}
    if not preferred:
        return ranked_order[:top_k]

    preferred_ids = [
        i for i in ranked_order if chunks[i]["section"].strip().lower() in preferred
    ]
    other_ids = [
        i for i in ranked_order if chunks[i]["section"].strip().lower() not in preferred
    ]
    if not preferred_ids:
        # No chunks in the requested sections — behave as though the
        # preference wasn't set at all. Keeps re-reads useful when the
        # reader guessed a section name that isn't in the paper.
        return ranked_order[:top_k]

    reserve = min(len(preferred_ids), max(1, top_k // 2))
    take_preferred = preferred_ids[:reserve]
    take_other = other_ids[: top_k - len(take_preferred)]
    return take_preferred + take_other


def rank_chunks_by_relevance(
    chunks: list[Chunk],
    subquestions: list[str],
    top_k: int = DEFAULT_TOP_K,
    preferred_sections: list[str] | None = None,
) -> list[RankedChunk]:
    """Return the top-K chunks by cosine similarity to any sub-question.

    Encodes chunks and sub-questions with the shared MiniLM model, runs
    a FAISS inner-product search (equivalent to cosine similarity given
    the L2-normalized embeddings), then takes the max score per chunk
    across sub-questions. Returned chunks are sorted by descending score.

    Args:
        chunks: Section-labeled chunks produced by `chunker.chunk_paper`.
        subquestions: Planner-produced sub-questions. If empty, the first
            `top_k` chunks are returned unranked (`relevance_score=0.0`).
        top_k: Maximum number of chunks to return.
        preferred_sections: Optional list of section names (case-
            insensitive) to reserve slots for. Used by the reader's
            recovery path (ADR 0019) to guarantee re-reads see chunks
            from the sections it flagged as under-covered. `None` (the
            default) preserves Sprint 1 behavior byte-for-byte.

    Returns:
        Up to `top_k` chunks, each annotated with `relevance_score`.
        Ordering is by descending relevance in the default case; when
        `preferred_sections` is applied, the reserved-slot chunks come
        first (still ordered by their own relevance) followed by the
        remaining top-scoring chunks.
    """
    if not chunks:
        return []

    if not subquestions:
        return [
            RankedChunk(
                section=chunk["section"],
                text=chunk["text"],
                chunk_index=chunk["chunk_index"],
                relevance_score=0.0,
            )
            for chunk in chunks[:top_k]
        ]

    chunk_embeddings = encode_texts([chunk["text"] for chunk in chunks])
    query_embeddings = encode_texts(subquestions)

    dimension = chunk_embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(chunk_embeddings)

    scores, indices = index.search(query_embeddings, len(chunks))
    max_score = _max_similarity_per_chunk(scores, indices, len(chunks))

    ranked_order = sorted(
        range(len(chunks)), key=lambda i: max_score[i], reverse=True
    )

    if preferred_sections:
        selection = _apply_preferred_sections(
            ranked_order, chunks, top_k, preferred_sections
        )
    else:
        selection = ranked_order[:top_k]

    return [_to_ranked_chunk(chunks[i], max_score[i]) for i in selection]
