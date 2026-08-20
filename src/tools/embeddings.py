"""HuggingFace embeddings + FAISS ranking for paper relevance.

Exposes a shared `encode_texts` helper so downstream retrieval modules
(paper ranking, chunk ranking) all use the same model and normalization
convention. Model is lazy-loaded and cached at module scope.

Under `settings.embedding_cache="postgres"`, `encode_texts` first
looks up every text's L2-normalized vector by content hash in the
`embedding_cache` table (ADR 0028); MiniLM only runs on misses.
Under the default `"none"`, every call re-encodes — Sprint 1
behavior byte-identical.
"""

from __future__ import annotations

import contextlib
import threading

import numpy as np
from sentence_transformers import SentenceTransformer

from src.graph.state import PaperMetadata
from src.observability import get_logger

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

log = get_logger(__name__)

_model: SentenceTransformer | None = None
# Double-checked locking, same pattern as `postgres_pool.get_pool` —
# the reader's ThreadPoolExecutor and concurrent jobs' search nodes can
# all hit a cold `_get_model()` simultaneously, and without the lock
# each would load its own ~90MB SentenceTransformer.
_model_lock = threading.Lock()


def _get_model() -> SentenceTransformer:
    """Lazy-load the sentence transformer model (module-level singleton).

    Thread-safe: the unlocked fast path serves the common case, and the
    re-check inside the lock guarantees exactly one construction under
    concurrent first-callers.
    """
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(MODEL_NAME)
    return _model


def _encode_uncached(texts: list[str]) -> np.ndarray:
    """Direct MiniLM path — no cache lookup. Isolated so callers
    that already know they're cache-missing don't pay the round-trip.
    """
    model = _get_model()
    encoded = model.encode(texts, normalize_embeddings=True)
    return np.asarray(encoded, dtype=np.float32)


def encode_texts(texts: list[str]) -> np.ndarray:
    """Encode texts as L2-normalized sentence embeddings.

    Normalization means the inner product between two encoded vectors
    equals their cosine similarity, so `faiss.IndexFlatIP` yields a
    cosine-similarity search.

    Cache-aware: hits skip MiniLM inference. Cache misses run through
    the model and get written back so a repeat encode is a lookup.
    Return order matches the input order exactly regardless of hit /
    miss mix.

    Args:
        texts: Strings to encode.

    Returns:
        `(n, d)` float32 ndarray of L2-normalized embeddings. Returns
        an empty `(0, 0)` array when `texts` is empty.
    """
    if not texts:
        return np.empty((0, 0), dtype=np.float32)

    # Local import to keep the module import graph acyclic — the
    # embedding_cache module imports MODEL_NAME from here.
    from src.tools.embedding_cache import content_hash, get_embedding_cache

    cache = get_embedding_cache()
    hashes = [content_hash(t) for t in texts]
    # The cache is an optimization, never a dependency: a backend
    # failure (pool timeout, Postgres restart) degrades to a full
    # recompute instead of failing the caller's node and job. Mirrors
    # the already-guarded write path below — ADR 0028's "degrades to
    # recompute, only shows up in the logs" consequence, made true on
    # the read side too (ADR 0041).
    hits: dict[str, np.ndarray] = {}
    try:
        hits = cache.get_many(hashes, MODEL_NAME)
    except Exception as exc:
        log.warning(
            "embedding_cache_get_failed",
            extra={"n_texts": len(texts), "error": str(exc)},
        )

    if len(hits) == len(texts):
        # Full-hit fast path — no MiniLM invocation, no put.
        return np.stack([hits[h] for h in hashes]).astype(np.float32)

    miss_indices = [i for i, h in enumerate(hashes) if h not in hits]
    miss_texts = [texts[i] for i in miss_indices]
    fresh = _encode_uncached(miss_texts)

    # Write the fresh vectors back to the cache for next time. A
    # write failure is best-effort — callers already got their
    # vectors and a cache-write hiccup shouldn't block encoding.
    with contextlib.suppress(Exception):
        cache.put_many(
            [(hashes[miss_indices[i]], fresh[i]) for i in range(len(miss_texts))],
            MODEL_NAME,
        )

    # Stitch hits + misses back into input order.
    dim = fresh.shape[1] if fresh.size else next(iter(hits.values())).shape[0]
    out = np.empty((len(texts), dim), dtype=np.float32)
    miss_iter = iter(range(len(miss_texts)))
    for i, h in enumerate(hashes):
        if h in hits:
            out[i] = hits[h]
        else:
            out[i] = fresh[next(miss_iter)]
    return out


def rank_papers_by_relevance(
    query: str,
    papers: list[PaperMetadata],
    top_k: int = 10,
) -> list[PaperMetadata]:
    """Rank papers by cosine similarity between query and abstracts using FAISS.

    Args:
        query: The original research query.
        papers: List of paper metadata with abstracts.
        top_k: Number of top papers to return.

    Returns:
        Papers sorted by descending relevance, capped at `top_k`.
    """
    if not papers:
        return []

    if len(papers) <= top_k:
        return papers

    import faiss

    abstract_embeddings = encode_texts([p["abstract"] for p in papers])
    query_embedding = encode_texts([query])

    dimension = abstract_embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(abstract_embeddings)

    _, indices = index.search(query_embedding, min(top_k, len(papers)))

    return [papers[idx] for idx in indices[0] if idx < len(papers)]
