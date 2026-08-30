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
from src.observability import get_logger, redact_url

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

-- ADR 0042: both caches accumulate forever (no TTL, no sweep), and
-- an age-based purge needs an index on `created_at` to avoid a
-- seq-scan over a multi-GB table. Added now, while the DDL can
-- still express it additively; the purge command itself is a
-- follow-up.
CREATE INDEX IF NOT EXISTS paper_cache_created_at_idx
    ON paper_cache (created_at);

CREATE TABLE IF NOT EXISTS embedding_cache (
    content_hash TEXT NOT NULL,
    model_name TEXT NOT NULL,
    embedding_bytes BYTEA NOT NULL,
    dimension INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (content_hash, model_name)
);

CREATE INDEX IF NOT EXISTS embedding_cache_created_at_idx
    ON embedding_cache (created_at);

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

-- === BEGIN learner_profiles (WO-W02, ADR 0058) =====================
-- APPEND-ONLY SECTION. Phase W cards extend SCHEMA_DDL by adding a
-- new comment-fenced block at the end, never by editing an earlier
-- one; the merge order is W02 then W07, and `init_schema` idempotence
-- is the shared guard both cards' tests assert
-- (planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md §5.4).
--
-- The first table in this repo that holds data about a *person*.
-- Keyed on `principal_key_id` (ADR 0036) rather than a stable owner
-- id, which is honest only for single-human / pilot deployments:
-- MT-01's finding F1 says `key_id` is a mutable display name, so a
-- reassigned key would inherit another human's skill history. Phase W
-- handles that operationally (pilot keys are issued fresh per person
-- and never reassigned, SR-02) and MT-01 / L0-05 is the real fix.
--
-- Provenance is enforced here, not only in Python. The CHECK
-- constraints below make a claim without a source, a declared claim
-- that is not confidence 1.0, an inferred claim above 0.6, or an
-- evidence-free inference unrepresentable *at rest* — a direct psql
-- INSERT is refused the same way the store is. The numeric bounds
-- mirror `src/learning/profile_store.py`; a test asserts the two
-- agree, because a cap that drifts is a cap that is not enforced.
CREATE TABLE IF NOT EXISTS learner_profiles (
    principal_key_id TEXT PRIMARY KEY,
    academic_level TEXT NOT NULL DEFAULT '',
    time_budget_min_per_day INTEGER NOT NULL DEFAULT 0,
    goals JSONB NOT NULL DEFAULT '[]'::jsonb,
    skills JSONB NOT NULL DEFAULT '[]'::jsonb,
    profile_note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 01 §1.3: the profile refuses the anonymous principal. The flag
    -- validator in `src/config.py` and the store both say so; the
    -- table says so too, so no path can create an ownerless profile.
    CONSTRAINT learner_profiles_principal_named
        CHECK (principal_key_id <> ''),

    CONSTRAINT learner_profiles_academic_level_vocab
        CHECK (academic_level IN (
            '', 'self-taught', 'undergrad', 'grad', 'postdoc', 'industry'
        )),
    CONSTRAINT learner_profiles_time_budget_bounded
        CHECK (time_budget_min_per_day BETWEEN 0 AND 1440),
    CONSTRAINT learner_profiles_profile_note_bounded
        CHECK (length(profile_note) <= 1000),

    CONSTRAINT learner_profiles_goals_capped
        CHECK (jsonb_typeof(goals) = 'array'
               AND jsonb_array_length(goals) <= 8),
    CONSTRAINT learner_profiles_goals_shaped CHECK (
        NOT jsonb_path_exists(goals, '$[*] ? (!exists(@.goal_id)
            || !exists(@.statement) || !exists(@.status)
            || !exists(@.priority) || !exists(@.target_date))')
        AND NOT jsonb_path_exists(goals, '$[*] ? (@.status != "active"
            && @.status != "paused" && @.status != "reached"
            && @.status != "abandoned")')
    ),

    CONSTRAINT learner_profiles_skills_capped
        CHECK (jsonb_typeof(skills) = 'array'
               AND jsonb_array_length(skills) <= 40),

    -- Every field present. There is no honest default for "where did
    -- this claim come from", so a row missing `source` is refused
    -- rather than defaulted.
    CONSTRAINT learner_profiles_skills_complete CHECK (
        NOT jsonb_path_exists(skills, '$[*] ? (!exists(@.skill)
            || !exists(@.level) || !exists(@.source)
            || !exists(@.evidence_ref) || !exists(@.confidence)
            || !exists(@.updated_at))')
    ),
    CONSTRAINT learner_profiles_skills_vocab CHECK (
        NOT jsonb_path_exists(skills, '$[*] ? (@.source != "declared"
            && @.source != "inferred" && @.source != "assessed")')
        AND NOT jsonb_path_exists(skills, '$[*] ? (@.level != "none"
            && @.level != "aware" && @.level != "working"
            && @.level != "solid")')
    ),
    -- 01 §1.2, the three honesty rules as arithmetic:
    --   confidence 1.0 is reserved for `declared`, and `declared` is
    --   nothing but 1.0; `inferred` is capped at 0.6; a non-declared
    --   claim must cite the session or assessment behind it, and a
    --   declared claim cites only itself.
    CONSTRAINT learner_profiles_skills_provenance CHECK (
        NOT jsonb_path_exists(skills, '$[*] ? (@.confidence <= 0.0
            || @.confidence > 1.0)')
        AND NOT jsonb_path_exists(skills, '$[*] ? (@.source == "declared"
            && @.confidence != 1.0)')
        AND NOT jsonb_path_exists(skills, '$[*] ? (@.source != "declared"
            && @.confidence >= 1.0)')
        AND NOT jsonb_path_exists(skills, '$[*] ? (@.source == "inferred"
            && @.confidence > 0.6)')
        AND NOT jsonb_path_exists(skills, '$[*] ? (@.source != "declared"
            && @.evidence_ref == "")')
        AND NOT jsonb_path_exists(skills, '$[*] ? (@.source == "declared"
            && @.evidence_ref != "")')
    )
);

CREATE INDEX IF NOT EXISTS learner_profiles_updated_at_idx
    ON learner_profiles (updated_at);
-- === END learner_profiles ==========================================
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
        #
        # ADR 0042: `statement_timeout` / `lock_timeout` bound every
        # query on the connection at the server side. Without them a
        # lock-blocked query (maintenance ALTER, autovacuum) holds
        # its `asyncio.to_thread` slot indefinitely, and enough such
        # requests starve the shared default executor with nothing
        # surfaced anywhere. 10s statements / 5s lock waits are far
        # above anything the caches or conversation store legitimately
        # do.
        kwargs={
            "connect_timeout": 5,
            "options": "-c statement_timeout=10000 -c lock_timeout=5000",
        },
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
            # ADR 0042: redact before logging — the libpq URL carries
            # the password inline, and `JsonFormatter` would index it
            # as a searchable top-level field in the log platform.
            log.info(
                "postgres_pool_opened", extra={"url": redact_url(resolved_url)}
            )
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
