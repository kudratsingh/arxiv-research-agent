"""Shared Postgres connection pool + idempotent schema bootstrap.

Sprint 4 PR 4 (ADR 0028) introduces two Postgres-backed caches
(`PaperCache`, `EmbeddingCache`). Both share one connection pool
that's created lazily on first use and lives at module scope for
the process lifetime.

`psycopg` v3 (sync mode) rather than `asyncpg` because the callers
— `pdf_parser.parse_pdf` from the reader's `ThreadPoolExecutor`,
`embeddings.encode_texts` from a similar fan-out — are sync. Async
would force `asyncio.run(...)` inside a thread, which is a hazard.
"""

from __future__ import annotations

import threading
from typing import Any

from psycopg_pool import ConnectionPool

from src.config import settings
from src.observability import get_logger

log = get_logger(__name__)

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()
_schema_initialized = False

# One-shot DDL. Idempotent — safe to run on every process startup
# even when the tables already exist. Kept inline (not in a .sql
# file) so the schema is version-controlled with the code that
# reads and writes it.
SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS paper_cache (
    paper_key TEXT PRIMARY KEY,
    pdf_url TEXT NOT NULL,
    full_text TEXT NOT NULL,
    text_length INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS paper_cache_pdf_url_idx
    ON paper_cache (pdf_url);

CREATE TABLE IF NOT EXISTS embedding_cache (
    content_hash TEXT NOT NULL,
    model_name TEXT NOT NULL,
    embedding_bytes BYTEA NOT NULL,
    dimension INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (content_hash, model_name)
);

-- Conversations (Sprint 5 PR 4, ADR 0032). A conversation links
-- multiple research jobs into a follow-up thread; the planner
-- retrieves top-K chunks from prior jobs in the same conversation
-- to bias the new plan toward continuity.
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- ADR 0036: owner under `enable_api_auth`. NULL on legacy rows
    -- and on rows written under auth-off. Ownership checks in
    -- `src/api/routes.py` treat NULL as invisible under auth-on.
    principal_key_id TEXT NULL
);

-- ADR 0036 migration for pre-existing tables that were created
-- before `principal_key_id` was part of the schema. Postgres 9.6+
-- supports `IF NOT EXISTS` on ADD COLUMN so this is idempotent on
-- both fresh and upgraded databases.
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS principal_key_id TEXT NULL;

CREATE INDEX IF NOT EXISTS conversations_principal_key_id_idx
    ON conversations (principal_key_id)
    WHERE principal_key_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS conversation_jobs (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id)
        ON DELETE CASCADE,
    job_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    query TEXT NOT NULL,
    report TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (conversation_id, ordinal)
);

CREATE INDEX IF NOT EXISTS conversation_jobs_conversation_idx
    ON conversation_jobs (conversation_id, ordinal);
CREATE INDEX IF NOT EXISTS conversation_jobs_job_id_idx
    ON conversation_jobs (job_id);
"""


def _make_pool(url: str, *, min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    """Construct a `ConnectionPool` and wait for it to open.

    `open=True` makes the pool start accepting `connection()` calls
    only after at least `min_size` connections are established, so
    the first request doesn't pay the connect latency.
    """
    pool = ConnectionPool(
        url,
        min_size=min_size,
        max_size=max_size,
        # Sane per-connection timeouts so a hung Postgres doesn't
        # wedge a reader thread. Callers already handle failures
        # gracefully — they log and fall back to the disk path.
        kwargs={"connect_timeout": 5},
        open=False,
    )
    pool.open(wait=True, timeout=10.0)
    return pool


def get_pool(url: str | None = None) -> ConnectionPool:
    """Return the process-wide connection pool, opening it on first call.

    Idempotent: subsequent calls return the same pool. `url=None`
    defaults to `settings.postgres_url`. Raises `RuntimeError` if
    called with an empty URL — the caller should have gated on
    `settings.postgres_url` being non-empty before invoking.
    """
    global _pool
    if _pool is not None:
        return _pool

    resolved_url = url if url is not None else settings.postgres_url
    if not resolved_url:
        raise RuntimeError(
            "postgres_url is empty; set POSTGRES_URL before selecting a "
            "postgres-backed cache."
        )

    with _pool_lock:
        # Double-checked: another thread may have opened the pool
        # between the fast-path check and the lock acquisition.
        if _pool is None:
            _pool = _make_pool(resolved_url)
            log.info("postgres_pool_opened", extra={"url": resolved_url})
    return _pool


def init_schema(url: str | None = None) -> None:
    """Run the idempotent DDL once per process.

    Safe to call from concurrent threads — the first caller wins
    and later callers no-op. `CREATE TABLE IF NOT EXISTS` makes the
    DDL itself concurrency-safe at the Postgres level, but keeping
    a Python-side gate saves round-trips.
    """
    global _schema_initialized
    if _schema_initialized:
        return

    pool = get_pool(url)
    with _pool_lock:
        if _schema_initialized:
            return
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(SCHEMA_DDL)
            conn.commit()
        _schema_initialized = True
        log.info("postgres_schema_initialized")


def close_pool() -> None:
    """Release the pool. Called from tests and would be called from
    a graceful process-shutdown hook if we grow one."""
    global _pool, _schema_initialized
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None
        _schema_initialized = False


def _reset_for_test(pool: ConnectionPool | None = None) -> None:
    """Test seam — inject a pre-built pool (e.g. from pytest-postgresql).

    Not part of the public surface; the underscore + docstring flag
    intent, and tests only reach in when they need a hand-managed
    lifecycle.
    """
    global _pool, _schema_initialized
    with _pool_lock:
        _pool = pool
        _schema_initialized = False


def _connection() -> Any:
    """Convenience: `with _connection() as conn: ...` for caches."""
    return get_pool().connection()
