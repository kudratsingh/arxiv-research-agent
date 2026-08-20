"""Conversation model + pluggable store (ADR 0032).

A conversation links multiple research jobs into a thread. The
planner uses prior jobs' reports as retrievable context so
follow-ups can build on earlier findings without the client
re-quoting them.

Storage: `ConversationStore` Protocol with two implementations —
`InMemoryConversationStore` (default, single-worker) and
`PostgresConversationStore` (durable, shared across workers via
the connection pool from ADR 0028). Selection driven by
`settings.conversation_store`.

Follows the JobStore pattern from ADR 0025 for consistency.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.observability import get_logger

log = get_logger(__name__)

MAX_TITLE_LEN = 80

# Pagination contract (ADR 0043): the route layer defaults to
# DEFAULT_LIST_LIMIT and caps the client-supplied limit at
# MAX_LIST_LIMIT. The store honors whatever it's handed — clamping
# is a route-layer concern so stores stay dumb.
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


def new_conversation_id() -> str:
    return uuid.uuid4().hex[:16]


def title_from_query(query: str) -> str:
    """Truncate the first query into a display title.

    Cheap and predictable; an LLM-generated title is a follow-up.
    A trailing ellipsis signals truncation to the reviewer.
    """
    normalized = " ".join(query.split())
    if len(normalized) <= MAX_TITLE_LEN:
        return normalized
    return normalized[: MAX_TITLE_LEN - 1].rstrip() + "…"


@dataclass
class ConversationJob:
    """A single job's slot in a conversation — just enough to
    reconstruct the thread and feed the retriever.
    """

    job_id: str
    ordinal: int
    query: str
    report: str
    created_at: float = field(default_factory=time.time)


@dataclass
class Conversation:
    """Thread of jobs. `jobs` is loaded lazily by the store methods;
    `list_conversations` returns Conversation objects with an empty
    jobs list to keep the sidebar cheap.
    """

    conversation_id: str
    title: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    jobs: list[ConversationJob] = field(default_factory=list)
    # ADR 0036: owner under `enable_api_auth`. See the same field on
    # `Job` in `src/api/jobs.py` for the ownership model.
    principal_key_id: str | None = None


class ConversationStore(Protocol):
    """Structural type for conversation storage. Safe under concurrent
    asyncio tasks."""

    async def create(self, conversation: Conversation) -> None: ...

    async def get(self, conversation_id: str) -> Conversation | None: ...

    async def list(
        self,
        principal_key_id: str | None = None,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[Conversation]: ...

    async def append_job(
        self,
        conversation_id: str,
        job_id: str,
        query: str,
        report: str,
    ) -> ConversationJob | None: ...

    async def delete(
        self,
        conversation_id: str,
        principal_key_id: str | None = None,
    ) -> bool: ...


# ---------------------------------------------------------------------------
# InMemory implementation — default, single-worker, dies with the process.
# ---------------------------------------------------------------------------


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._lock = asyncio.Lock()

    async def create(self, conversation: Conversation) -> None:
        async with self._lock:
            self._conversations[conversation.conversation_id] = conversation

    async def get(self, conversation_id: str) -> Conversation | None:
        async with self._lock:
            return self._conversations.get(conversation_id)

    async def list(
        self,
        principal_key_id: str | None = None,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[Conversation]:
        async with self._lock:
            # ADR 0036: under auth-on the caller's principal is
            # threaded through; only rows they own come back. Under
            # auth-off (`principal_key_id=None`) return everything —
            # legacy demo behavior.
            def _visible(c: Conversation) -> bool:
                if principal_key_id is None:
                    return True
                return c.principal_key_id == principal_key_id

            # Sort most-recent-first so the sidebar's top item is the
            # active conversation. `conversation_id` tie-breaks equal
            # timestamps so pages are stable across requests — same
            # ORDER BY as the Postgres store (ADR 0043).
            ordered = sorted(
                (
                    Conversation(
                        conversation_id=c.conversation_id,
                        title=c.title,
                        created_at=c.created_at,
                        updated_at=c.updated_at,
                        jobs=[],
                        principal_key_id=c.principal_key_id,
                    )
                    for c in self._conversations.values()
                    if _visible(c)
                ),
                key=lambda c: (-c.updated_at, c.conversation_id),
            )
            # ADR 0043: paginate after the scoping filter so offset
            # counts the caller's own rows, mirroring SQL
            # WHERE ... ORDER BY ... LIMIT/OFFSET semantics.
            return ordered[offset : offset + limit]

    async def append_job(
        self,
        conversation_id: str,
        job_id: str,
        query: str,
        report: str,
    ) -> ConversationJob | None:
        async with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                return None
            # ADR 0043: MAX(ordinal)+1 rather than len()+1, mirroring
            # the Postgres store's allocation so the two impls stay
            # behaviorally identical even if jobs are ever removed.
            job = ConversationJob(
                job_id=job_id,
                ordinal=max((j.ordinal for j in conversation.jobs), default=0) + 1,
                query=query,
                report=report,
            )
            conversation.jobs.append(job)
            conversation.updated_at = time.time()
            return job

    async def delete(
        self,
        conversation_id: str,
        principal_key_id: str | None = None,
    ) -> bool:
        async with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                return False
            # ADR 0043: ownership rides inside the delete itself.
            # `principal_key_id=None` means unscoped (auth-off);
            # under auth-on a mismatch — including legacy rows whose
            # owner is None — reports False, which the route maps to
            # the same 404 a missing id gets (ADR 0036).
            if (
                principal_key_id is not None
                and conversation.principal_key_id != principal_key_id
            ):
                return False
            del self._conversations[conversation_id]
            return True


# ---------------------------------------------------------------------------
# Postgres implementation — durable + shared across workers.
# ---------------------------------------------------------------------------


class PostgresConversationStore:
    """`conversations` + `conversation_jobs` tables via the pool
    from `postgres_pool`. Read/write operations run under the pool's
    connection context; no local caching (unlike `RedisJobStore`,
    which keeps a worker-local dict for live-queue affinity — that
    concern doesn't apply to conversations).

    Every `_run` closure below opens with `init_schema()` so the
    bootstrap DDL — pool open included — executes on the
    `asyncio.to_thread` worker, never on the event loop.
    `init_schema` carries its own process-wide once-guard, so calls
    after the first are a boolean check (ADR 0043; previously the
    call sat on the loop and a slow `pool.open(wait=True)` froze
    every in-flight request, SSE heartbeats included).
    """

    async def create(self, conversation: Conversation) -> None:
        from src.tools.postgres_pool import _connection, init_schema

        def _run() -> None:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversations
                        (conversation_id, title, principal_key_id)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        conversation.conversation_id,
                        conversation.title,
                        conversation.principal_key_id,
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_run)

    async def get(self, conversation_id: str) -> Conversation | None:
        from src.tools.postgres_pool import _connection, init_schema

        def _run() -> Conversation | None:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT conversation_id, title, created_at, updated_at,
                           principal_key_id
                    FROM conversations
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                created_at = row[2].timestamp() if row[2] else time.time()
                updated_at = row[3].timestamp() if row[3] else time.time()

                cur.execute(
                    """
                    SELECT job_id, ordinal, query, report, created_at
                    FROM conversation_jobs
                    WHERE conversation_id = %s
                    ORDER BY ordinal
                    """,
                    (conversation_id,),
                )
                jobs = [
                    ConversationJob(
                        job_id=jr[0],
                        ordinal=int(jr[1]),
                        query=jr[2],
                        report=jr[3],
                        created_at=jr[4].timestamp() if jr[4] else time.time(),
                    )
                    for jr in cur.fetchall()
                ]
                return Conversation(
                    conversation_id=str(row[0]),
                    title=str(row[1]),
                    created_at=created_at,
                    updated_at=updated_at,
                    jobs=jobs,
                    principal_key_id=row[4],
                )

        return await asyncio.to_thread(_run)

    async def list(
        self,
        principal_key_id: str | None = None,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> list[Conversation]:
        from src.tools.postgres_pool import _connection, init_schema

        # ADR 0036: push the principal filter into SQL so scaled
        # deployments don't paginate through other tenants' rows.
        # `principal_key_id IS NULL` in the WHERE branch is
        # intentionally excluded from auth-on results — legacy rows
        # with no owner stay invisible until admin cleanup.
        where_clause = ""
        params: tuple[Any, ...] = ()
        if principal_key_id is not None:
            where_clause = "WHERE principal_key_id = %s"
            params = (principal_key_id,)
        # ADR 0043: LIMIT/OFFSET in SQL so a 10k-conversation tenant
        # never drags the full table over the wire per sidebar load.
        # `conversation_id` tie-breaks equal `updated_at` values so
        # consecutive pages don't overlap or skip rows.
        params = (*params, limit, offset)

        def _run() -> list[Conversation]:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT conversation_id, title, created_at, updated_at,
                           principal_key_id
                    FROM conversations
                    {where_clause}
                    ORDER BY updated_at DESC, conversation_id
                    LIMIT %s OFFSET %s
                    """,
                    params,
                )
                return [
                    Conversation(
                        conversation_id=str(r[0]),
                        title=str(r[1]),
                        created_at=r[2].timestamp() if r[2] else time.time(),
                        updated_at=r[3].timestamp() if r[3] else time.time(),
                        jobs=[],
                        principal_key_id=r[4],
                    )
                    for r in cur.fetchall()
                ]

        return await asyncio.to_thread(_run)

    async def append_job(
        self,
        conversation_id: str,
        job_id: str,
        query: str,
        report: str,
    ) -> ConversationJob | None:
        from src.tools.postgres_pool import _connection, init_schema

        def _run() -> ConversationJob | None:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                # Guard the FK and serialize concurrent appends in
                # one step: `FOR UPDATE` locks the parent row for the
                # rest of the transaction, so two appends to the same
                # conversation queue here instead of both computing
                # the same MAX(ordinal) and colliding on the primary
                # key (ADR 0043). A missing conversation still
                # returns None so the caller can 404 (matches the
                # in-memory store's behavior).
                cur.execute(
                    """
                    SELECT 1 FROM conversations
                    WHERE conversation_id = %s
                    FOR UPDATE
                    """,
                    (conversation_id,),
                )
                if cur.fetchone() is None:
                    return None
                # Ordinal allocation and insert as one statement —
                # no read-modify-write gap even without the row lock
                # above (belt and braces, ADR 0043).
                cur.execute(
                    """
                    INSERT INTO conversation_jobs
                        (conversation_id, job_id, ordinal, query, report)
                    SELECT %s, %s, COALESCE(MAX(ordinal), 0) + 1, %s, %s
                    FROM conversation_jobs
                    WHERE conversation_id = %s
                    RETURNING ordinal, created_at
                    """,
                    (conversation_id, job_id, query, report, conversation_id),
                )
                inserted_row = cur.fetchone()
                next_ordinal = int(inserted_row[0]) if inserted_row else 1
                created_at = (
                    inserted_row[1].timestamp()
                    if inserted_row and inserted_row[1]
                    else time.time()
                )
                cur.execute(
                    """
                    UPDATE conversations
                    SET updated_at = NOW()
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                conn.commit()
                return ConversationJob(
                    job_id=job_id,
                    ordinal=next_ordinal,
                    query=query,
                    report=report,
                    created_at=created_at,
                )

        try:
            return await asyncio.to_thread(_run)
        except Exception:
            # ADR 0043: the runner wraps this call in a blanket
            # suppress, so without a log line here a failed append —
            # a fully paid-for report — vanishes without trace. Log
            # at ERROR before propagating; visibility must live in
            # the store because the caller's suppress is upstream.
            log.exception(
                "conversation_append_failed",
                extra={
                    "conversation_id": conversation_id,
                    "job_id": job_id,
                },
            )
            raise

    async def delete(
        self,
        conversation_id: str,
        principal_key_id: str | None = None,
    ) -> bool:
        from src.tools.postgres_pool import _connection, init_schema

        # ADR 0043 (ADR 0036 follow-up): ownership rides inside the
        # DELETE itself — one statement, no fetch-then-delete pair.
        # `principal_key_id = %s` never matches a NULL owner, so
        # legacy rows stay untouchable under auth-on, and a mismatch
        # is indistinguishable from a missing id (False → 404).
        where_clause = "WHERE conversation_id = %s"
        params: tuple[Any, ...] = (conversation_id,)
        if principal_key_id is not None:
            where_clause += " AND principal_key_id = %s"
            params = (conversation_id, principal_key_id)

        def _run() -> bool:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                # ON DELETE CASCADE handles conversation_jobs cleanup.
                cur.execute(
                    f"DELETE FROM conversations {where_clause}",
                    params,
                )
                # `rowcount` on psycopg's cursor is typed loosely;
                # coerce to bool so mypy strict is happy.
                deleted: bool = bool(cur.rowcount and cur.rowcount > 0)
                conn.commit()
                return deleted

        return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# Factory — matches JobStore's lazy-selection pattern (ADR 0025).
# ---------------------------------------------------------------------------


def build_conversation_store() -> ConversationStore:
    """Select and construct the store based on `settings.conversation_store`.

    Lazy so the postgres pool isn't touched when the in-memory
    variant is selected.
    """
    from src.config import settings

    if settings.conversation_store == "postgres":
        return PostgresConversationStore()
    return InMemoryConversationStore()


def _reset_for_test(store: ConversationStore | None = None) -> None:
    """Test seam — the app builds its store in `create_app`; tests can
    inject via that path or override the factory return value here."""
    # Kept for API symmetry with the paper/embedding cache modules;
    # actual override happens at `create_app` call sites.
    return None


__all__ = [
    "Conversation",
    "ConversationJob",
    "ConversationStore",
    "DEFAULT_LIST_LIMIT",
    "InMemoryConversationStore",
    "MAX_LIST_LIMIT",
    "MAX_TITLE_LEN",
    "PostgresConversationStore",
    "build_conversation_store",
    "new_conversation_id",
    "title_from_query",
]
