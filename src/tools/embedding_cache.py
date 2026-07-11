"""EmbeddingCache: pluggable persisted store for MiniLM output vectors.

Skipping MiniLM inference for texts we've already seen saves ~30ms
per batch on CPU, larger under load. The cache is keyed on
`(content_hash, model_name)` so a model swap doesn't return stale
vectors and cache invalidation is a no-op — simply change the
model name.

Two implementations, one Protocol:

- `NoOpEmbeddingCache` — the default. Every `get*` returns `None`
  and `put*` is a no-op, preserving Sprint 1 behavior byte-identical.
- `PostgresEmbeddingCache` — `embedding_cache` table via
  `postgres_pool`. Vectors are stored as bytea (`numpy.tobytes`) so
  we don't need the pgvector extension; we're not doing similarity
  search in Postgres, only key-value cache of vectors that FAISS
  then indexes in memory.

Design in ADR 0028.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np

from src.config import settings
from src.observability import get_logger
from src.tools.embeddings import MODEL_NAME

log = get_logger(__name__)


def content_hash(text: str) -> str:
    """Stable, collision-resistant key for the embedding cache.

    SHA256 is overkill for cache keying but the cost is negligible
    (single-digit microseconds per text) and it eliminates any
    concern about hash collisions in the wild.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache(Protocol):
    """Structural type for embedding caches.

    `get_many` is the primary read path because embeddings are
    always encoded in batches; a single-item `get` would force
    N round-trips per FAISS build. Returns a dict of only the
    hits — misses are filled in by the caller via MiniLM inference.
    """

    def get_many(
        self, hashes: list[str], model_name: str
    ) -> dict[str, np.ndarray]: ...

    def put_many(
        self,
        entries: list[tuple[str, np.ndarray]],
        model_name: str,
    ) -> None: ...


# ---------------------------------------------------------------------
# No-op implementation — Sprint 1 behavior, byte-identical when the
# feature flag is off.
# ---------------------------------------------------------------------


class NoOpEmbeddingCache:
    """Default cache. Every `get_many` reports a full miss."""

    def get_many(
        self, hashes: list[str], model_name: str
    ) -> dict[str, np.ndarray]:
        return {}

    def put_many(
        self,
        entries: list[tuple[str, np.ndarray]],
        model_name: str,
    ) -> None:
        return None


# ---------------------------------------------------------------------
# Postgres implementation.
# ---------------------------------------------------------------------


class PostgresEmbeddingCache:
    """`embedding_cache` table via the shared connection pool.

    Storage layout per row: `(content_hash, model_name, embedding_bytes,
    dimension)`. Vectors are `float32` — the sentence-transformers
    output type — encoded via `ndarray.tobytes()` and rehydrated
    with `np.frombuffer(...).reshape(-1)`.
    """

    def get_many(
        self, hashes: list[str], model_name: str
    ) -> dict[str, np.ndarray]:
        if not hashes:
            return {}
        from src.tools.postgres_pool import _connection, init_schema

        init_schema()
        with _connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT content_hash, embedding_bytes, dimension
                FROM embedding_cache
                WHERE model_name = %s AND content_hash = ANY(%s)
                """,
                (model_name, hashes),
            )
            rows = cur.fetchall()
        result: dict[str, np.ndarray] = {}
        for row in rows:
            key, blob, dim = row
            vec = np.frombuffer(bytes(blob), dtype=np.float32).reshape(dim)
            result[str(key)] = vec
        return result

    def put_many(
        self,
        entries: list[tuple[str, np.ndarray]],
        model_name: str,
    ) -> None:
        if not entries:
            return
        from src.tools.postgres_pool import _connection, init_schema

        init_schema()
        rows = [
            (
                key,
                model_name,
                vec.astype(np.float32).tobytes(),
                int(vec.shape[0]),
            )
            for key, vec in entries
        ]
        with _connection() as conn, conn.cursor() as cur:
            # `executemany` runs UPSERT per row. Not the fastest for
            # very large batches (the chunker's ~20 chunks is fine);
            # switch to COPY if we ever ingest a corpus.
            cur.executemany(
                """
                INSERT INTO embedding_cache
                    (content_hash, model_name, embedding_bytes, dimension)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (content_hash, model_name) DO UPDATE SET
                    embedding_bytes = EXCLUDED.embedding_bytes,
                    dimension = EXCLUDED.dimension
                """,
                rows,
            )
            conn.commit()


# ---------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------


_cache: EmbeddingCache | None = None


def get_embedding_cache() -> EmbeddingCache:
    """Return the module-level singleton, selected by settings."""
    global _cache
    if _cache is not None:
        return _cache

    if settings.embedding_cache == "postgres":
        _cache = PostgresEmbeddingCache()
        log.info("embedding_cache_selected", extra={"impl": "postgres"})
    else:
        _cache = NoOpEmbeddingCache()
        log.info(
            "embedding_cache_selected",
            extra={"impl": "noop", "model": MODEL_NAME},
        )
    return _cache


def _reset_for_test(cache: EmbeddingCache | None = None) -> None:
    """Test seam — inject a cache or clear the singleton."""
    global _cache
    _cache = cache
