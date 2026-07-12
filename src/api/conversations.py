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
from typing import Protocol

MAX_TITLE_LEN = 80


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


class ConversationStore(Protocol):
    """Structural type for conversation storage. Safe under concurrent
    asyncio tasks."""

    async def create(self, conversation: Conversation) -> None: ...

    async def get(self, conversation_id: str) -> Conversation | None: ...

    async def list(self) -> list[Conversation]: ...

    async def append_job(
        self,
        conversation_id: str,
        job_id: str,
        query: str,
        report: str,
    ) -> ConversationJob | None: ...

    async def delete(self, conversation_id: str) -> bool: ...


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

    async def list(self) -> list[Conversation]:
        async with self._lock:
            # Sort most-recent-first so the sidebar's top item is the
            # active conversation.
            return sorted(
                (
                    Conversation(
                        conversation_id=c.conversation_id,
                        title=c.title,
                        created_at=c.created_at,
                        updated_at=c.updated_at,
                        jobs=[],
                    )
                    for c in self._conversations.values()
                ),
                key=lambda c: c.updated_at,
                reverse=True,
            )

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
            job = ConversationJob(
                job_id=job_id,
                ordinal=len(conversation.jobs) + 1,
                query=query,
                report=report,
            )
            conversation.jobs.append(job)
            conversation.updated_at = time.time()
            return job

    async def delete(self, conversation_id: str) -> bool:
        async with self._lock:
            return self._conversations.pop(conversation_id, None) is not None


# ---------------------------------------------------------------------------
# Postgres implementation — durable + shared across workers.
# ---------------------------------------------------------------------------


class PostgresConversationStore:
    """`conversations` + `conversation_jobs` tables via the pool
    from `postgres_pool`. Read/write operations run under the pool's
    connection context; no local caching (unlike `RedisJobStore`,
    which keeps a worker-local dict for live-queue affinity — that
    concern doesn't apply to conversations)."""

    async def create(self, conversation: Conversation) -> None:
        from src.tools.postgres_pool import _connection, init_schema

        init_schema()

        def _run() -> None:
            with _connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO conversations (conversation_id, title)
                    VALUES (%s, %s)
                    """,
                    (conversation.conversation_id, conversation.title),
                )
                conn.commit()

        await asyncio.to_thread(_run)

    async def get(self, conversation_id: str) -> Conversation | None:
        from src.tools.postgres_pool import _connection, init_schema

        init_schema()

        def _run() -> Conversation | None:
            with _connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT conversation_id, title, created_at, updated_at
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
                )

        return await asyncio.to_thread(_run)

    async def list(self) -> list[Conversation]:
        from src.tools.postgres_pool import _connection, init_schema

        init_schema()

        def _run() -> list[Conversation]:
            with _connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT conversation_id, title, created_at, updated_at
                    FROM conversations
                    ORDER BY updated_at DESC
                    """
                )
                return [
                    Conversation(
                        conversation_id=str(r[0]),
                        title=str(r[1]),
                        created_at=r[2].timestamp() if r[2] else time.time(),
                        updated_at=r[3].timestamp() if r[3] else time.time(),
                        jobs=[],
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

        init_schema()

        def _run() -> ConversationJob | None:
            with _connection() as conn, conn.cursor() as cur:
                # Guard the FK: if the conversation is missing return
                # None so the caller can 404 (matches the in-memory
                # store's behavior).
                cur.execute(
                    "SELECT 1 FROM conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                if cur.fetchone() is None:
                    return None
                cur.execute(
                    """
                    SELECT COALESCE(MAX(ordinal), 0) + 1
                    FROM conversation_jobs
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                next_ordinal_row = cur.fetchone()
                next_ordinal = int(next_ordinal_row[0]) if next_ordinal_row else 1
                cur.execute(
                    """
                    INSERT INTO conversation_jobs
                        (conversation_id, job_id, ordinal, query, report)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING created_at
                    """,
                    (conversation_id, job_id, next_ordinal, query, report),
                )
                created_row = cur.fetchone()
                created_at = (
                    created_row[0].timestamp() if created_row else time.time()
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

        return await asyncio.to_thread(_run)

    async def delete(self, conversation_id: str) -> bool:
        from src.tools.postgres_pool import _connection, init_schema

        init_schema()

        def _run() -> bool:
            with _connection() as conn, conn.cursor() as cur:
                # ON DELETE CASCADE handles conversation_jobs cleanup.
                cur.execute(
                    "DELETE FROM conversations WHERE conversation_id = %s",
                    (conversation_id,),
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
    "InMemoryConversationStore",
    "MAX_TITLE_LEN",
    "PostgresConversationStore",
    "build_conversation_store",
    "new_conversation_id",
    "title_from_query",
]
