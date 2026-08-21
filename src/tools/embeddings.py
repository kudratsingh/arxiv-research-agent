"""HuggingFace embeddings + FAISS ranking for paper relevance.

Exposes a shared `encode_texts` helper so downstream retrieval modules
(paper ranking, chunk ranking) all use the same model and normalization
convention. Model is lazy-loaded and cached at module scope.

Under `settings.embedding_cache="postgres"`, `encode_texts` first
looks up every text's L2-normalized vector by content hash in the
`embedding_cache` table (ADR 0028); MiniLM only runs on misses.
Under the default `"none"`, every call re-encodes — Sprint 1
behavior byte-identical.

Device selection is explicit (ADR 0052). `settings.embedding_device`
defaults to `"cpu"`, which is *not* what sentence-transformers would
pick on its own: on an Apple-silicon host the library selects `mps`,
and a torch forward pass on the Metal backend has taken the whole
process down with a SIGSEGV under concurrent encodes — a native
crash, so no Python traceback and no log line. Pinning the device is
the half of that containment that lives here; `"auto"` restores the
library's own pick for deployments that want GPU encode.
"""

from __future__ import annotations

import threading

import numpy as np
from sentence_transformers import SentenceTransformer

from src.config import settings
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


def _resolve_device() -> str | None:
    """Translate `settings.embedding_device` into a `SentenceTransformer` arg.

    `"auto"` maps to `None`, which is what the constructor treats as
    "pick a device yourself" — that is the pre-ADR-0052 behavior, kept
    reachable but no longer the default. Every other value is passed
    through verbatim as an explicit device string.

    Returns:
        The device string to construct with, or None to let the
        library choose.
    """
    device = settings.embedding_device
    return None if device == "auto" else device


def _get_model() -> SentenceTransformer:
    """Lazy-load the sentence transformer model (module-level singleton).

    Thread-safe: the unlocked fast path serves the common case, and the
    re-check inside the lock guarantees exactly one construction under
    concurrent first-callers.

    The device comes from `settings.embedding_device` (ADR 0052) and
    is logged once, at construction — the log line is the only way an
    operator can tell after the fact which backend a run's embeddings
    ran on, and "which backend" is the first question asked when a
    worker dies with exit 139 and no traceback.
    """
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                device = _resolve_device()
                _model = SentenceTransformer(MODEL_NAME, device=device)
                log.info(
                    "embedding_model_loaded",
                    extra={
                        "model": MODEL_NAME,
                        "configured_device": settings.embedding_device,
                        # What torch actually bound to. Under `auto`
                        # this is the only place the real answer
                        # appears; under an explicit setting it is the
                        # confirmation that the request was honored.
                        "resolved_device": str(
                            getattr(_model, "device", "unknown")
                        ),
                    },
                )
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
    # recompute instead of failing the caller's node and job. The
    # write path below is guarded the same way, and logs the same way
    # — ADR 0028's "degrades to recompute, only shows up in the logs"
    # consequence, made true on both sides (ADR 0041, ADR 0052).
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
    # vectors and a cache-write hiccup shouldn't block encoding — but
    # it is not silent (ADR 0052). A cache that reads fine and refuses
    # every write has a 0% hit rate forever and no other symptom than
    # the bill; the read path above and `paper_cache_put_failed` in
    # `pdf_parser` both log, and this site used to be the one
    # `contextlib.suppress(Exception)` that did not.
    try:
        cache.put_many(
            [(hashes[miss_indices[i]], fresh[i]) for i in range(len(miss_texts))],
            MODEL_NAME,
        )
    except Exception as exc:
        log.warning(
            "embedding_cache_put_failed",
            extra={"n_vectors": len(miss_texts), "error": str(exc)},
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
