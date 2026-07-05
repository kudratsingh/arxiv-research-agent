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


def rank_chunks_by_relevance(
    chunks: list[Chunk],
    subquestions: list[str],
    top_k: int = DEFAULT_TOP_K,
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

    Returns:
        Up to `top_k` chunks, each annotated with `relevance_score`,
        sorted by descending relevance.
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
    )[:top_k]

    return [
        RankedChunk(
            section=chunks[i]["section"],
            text=chunks[i]["text"],
            chunk_index=chunks[i]["chunk_index"],
            relevance_score=max_score[i],
        )
        for i in ranked_order
    ]
