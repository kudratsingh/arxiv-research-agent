"""Tests for the ConversationStore (in-memory + Postgres) and the
conversation endpoints (ADR 0032).

Postgres tests use `pytest-postgresql`; identical setup to the
paper-cache and embedding-cache tests. Skipped locally when the
system doesn't have the `postgres` server binary.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import threading
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.api import create_app
from src.api.conversations import (
    Conversation,
    InMemoryConversationStore,
    PostgresConversationStore,
    new_conversation_id,
    title_from_query,
)
from src.config import Settings
from src.tools import postgres_pool

_postgres_available = shutil.which("postgres") is not None
pytestmark_postgres = pytest.mark.skipif(
    not _postgres_available,
    reason="postgres server binary not found; install `postgresql` locally to run",
)

if _postgres_available:
    from pytest_postgresql import factories

    postgresql_proc = factories.postgresql_proc(port=None, unixsocketdir="/tmp")
    postgresql_db = factories.postgresql("postgresql_proc")


# ---------------------------------------------------------------------------
# Pure-function helpers
# ---------------------------------------------------------------------------


# Tier is declared per class in this module (ADR 0065): the Postgres
# and HTTP sections below are `integration`, so a module-level `unit`
# would sit on those too.
@pytest.mark.unit
class TestTitleFromQuery:
    def test_short_query_stays_intact(self) -> None:
        assert title_from_query("what is X?") == "what is X?"

    def test_whitespace_normalized(self) -> None:
        assert title_from_query("  multi   line\nquery ") == "multi line query"

    def test_long_query_truncated_with_ellipsis(self) -> None:
        long_q = "x" * 200
        got = title_from_query(long_q)
        assert len(got) <= 80
        assert got.endswith("…")


@pytest.mark.unit
class TestNewConversationId:
    def test_returns_16_hex_chars(self) -> None:
        cid = new_conversation_id()
        assert len(cid) == 16
        assert all(c in "0123456789abcdef" for c in cid)

    def test_ids_are_unique(self) -> None:
        assert new_conversation_id() != new_conversation_id()


# ---------------------------------------------------------------------------
# InMemoryConversationStore
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInMemoryConversationStore:
    async def test_create_then_get(self) -> None:
        store = InMemoryConversationStore()
        conv = Conversation(conversation_id="c1", title="First")
        await store.create(conv)
        got = await store.get("c1")
        assert got is not None
        assert got.title == "First"

    async def test_get_missing_returns_none(self) -> None:
        store = InMemoryConversationStore()
        assert await store.get("nope") is None

    async def test_list_returns_conversations_without_jobs(self) -> None:
        store = InMemoryConversationStore()
        for i in range(3):
            await store.create(
                Conversation(conversation_id=f"c{i}", title=f"Title {i}")
            )
        got = await store.list()
        assert len(got) == 3
        assert all(c.jobs == [] for c in got)

    async def test_list_sorted_most_recent_first(self) -> None:
        store = InMemoryConversationStore()
        await store.create(Conversation(conversation_id="a", title="A"))
        await store.create(Conversation(conversation_id="b", title="B"))
        # Bump b's updated_at.
        await store.append_job("b", "j1", "q1", "report1")
        got = await store.list()
        assert got[0].conversation_id == "b"

    async def test_append_job_assigns_ordinals(self) -> None:
        store = InMemoryConversationStore()
        await store.create(Conversation(conversation_id="c", title="C"))
        j1 = await store.append_job("c", "j1", "q1", "report1")
        j2 = await store.append_job("c", "j2", "q2", "report2")
        assert j1 is not None and j1.ordinal == 1
        assert j2 is not None and j2.ordinal == 2

    async def test_append_job_to_missing_conversation_returns_none(
        self,
    ) -> None:
        store = InMemoryConversationStore()
        assert await store.append_job("nope", "j1", "q", "r") is None

    async def test_append_job_bumps_updated_at(self) -> None:
        store = InMemoryConversationStore()
        await store.create(Conversation(conversation_id="c", title="C"))
        got_before = await store.get("c")
        assert got_before is not None
        before = got_before.updated_at
        # Sleep a hair so the timestamp comparison isn't ambiguous.
        time.sleep(0.005)
        await store.append_job("c", "j1", "q", "r")
        got_after = await store.get("c")
        assert got_after is not None
        assert got_after.updated_at > before

    async def test_delete_removes_conversation(self) -> None:
        store = InMemoryConversationStore()
        await store.create(Conversation(conversation_id="c", title="C"))
        assert await store.delete("c") is True
        assert await store.get("c") is None

    async def test_delete_missing_returns_false(self) -> None:
        store = InMemoryConversationStore()
        assert await store.delete("nope") is False


@pytest.mark.unit
class TestUpdateTitle:
    """ADR 0048, closing the ADR 0040 follow-up.

    The runner's first-job auto-title mutated the `Conversation`
    object it had just fetched. That happens to persist in-memory
    (same object) and does nothing at all under Postgres (a detached
    row), so every Postgres deployment kept the "New conversation"
    placeholder forever. A store method is the only way the two
    backends can agree.
    """

    async def test_renames_an_existing_conversation(self) -> None:
        store = InMemoryConversationStore()
        await store.create(
            Conversation(conversation_id="c", title="New conversation")
        )

        assert await store.update_title("c", "Attention mechanisms") is True

        got = await store.get("c")
        assert got is not None
        assert got.title == "Attention mechanisms"

    async def test_missing_conversation_returns_false(self) -> None:
        store = InMemoryConversationStore()
        assert await store.update_title("nope", "T") is False

    async def test_rename_does_not_reorder_the_sidebar(self) -> None:
        # `updated_at` is activity, and a rename is not activity. If it
        # bumped, auto-titling the first job of an old thread would
        # jump it to the top of every client's list.
        store = InMemoryConversationStore()
        await store.create(Conversation(conversation_id="a", title="A"))
        await store.create(Conversation(conversation_id="b", title="B"))
        await store.append_job("b", "j1", "q", "r")
        before = await store.get("a")
        assert before is not None

        time.sleep(0.005)
        assert await store.update_title("a", "A renamed") is True

        after = await store.get("a")
        assert after is not None
        assert after.updated_at == before.updated_at
        assert [c.conversation_id for c in await store.list()] == ["b", "a"]

    async def test_rename_is_ownership_agnostic(self) -> None:
        # Matches `get` and `append_job`, not `list` and `delete`: the
        # only caller is the runner's auto-title, which acts on a
        # conversation the job is already attached to and has no
        # principal in hand.
        store = InMemoryConversationStore()
        await store.create(
            Conversation(
                conversation_id="c", title="T", principal_key_id="alice"
            )
        )
        assert await store.update_title("c", "Renamed") is True
        got = await store.get("c")
        assert got is not None
        assert got.title == "Renamed"
        assert got.principal_key_id == "alice"


@pytest.mark.unit
class TestInMemoryListPagination:
    """ADR 0043: `list` takes limit/offset so the sidebar query is
    bounded no matter how many conversations accumulate."""

    async def _seeded(self, n: int) -> InMemoryConversationStore:
        store = InMemoryConversationStore()
        for i in range(n):
            await store.create(
                Conversation(
                    conversation_id=f"c{i}",
                    title=f"T{i}",
                    # Explicit, strictly increasing timestamps so
                    # "newest first" ordering is deterministic.
                    created_at=1000.0 + i,
                    updated_at=1000.0 + i,
                )
            )
        return store

    async def test_limit_caps_page_size(self) -> None:
        store = await self._seeded(5)
        got = await store.list(limit=2)
        assert [c.conversation_id for c in got] == ["c4", "c3"]

    async def test_offset_skips_newest(self) -> None:
        store = await self._seeded(5)
        got = await store.list(limit=2, offset=2)
        assert [c.conversation_id for c in got] == ["c2", "c1"]

    async def test_offset_past_end_returns_empty(self) -> None:
        store = await self._seeded(3)
        assert await store.list(limit=50, offset=10) == []

    async def test_pages_are_disjoint_and_cover_everything(self) -> None:
        store = await self._seeded(5)
        page1 = await store.list(limit=3, offset=0)
        page2 = await store.list(limit=3, offset=3)
        ids = [c.conversation_id for c in page1 + page2]
        assert ids == ["c4", "c3", "c2", "c1", "c0"]

    async def test_offset_counts_within_principal_scope(self) -> None:
        """Scoping composes with pagination: offset counts the
        caller's own rows, not global rows (ADR 0043)."""
        store = InMemoryConversationStore()
        for i in range(4):
            owner = "alice" if i % 2 == 0 else "bob"
            await store.create(
                Conversation(
                    conversation_id=f"c{i}",
                    title=f"T{i}",
                    created_at=1000.0 + i,
                    updated_at=1000.0 + i,
                    principal_key_id=owner,
                )
            )
        got = await store.list("alice", limit=1, offset=1)
        assert [c.conversation_id for c in got] == ["c0"]
        assert all(c.principal_key_id == "alice" for c in got)


@pytest.mark.unit
class TestInMemoryScopedDelete:
    """ADR 0043: ownership rides inside `delete` itself, closing the
    ADR 0036 fetch-then-delete follow-up."""

    async def test_unscoped_delete_removes_any_row(self) -> None:
        store = InMemoryConversationStore()
        await store.create(
            Conversation(
                conversation_id="c", title="C", principal_key_id="alice"
            )
        )
        # `principal_key_id=None` == auth-off: legacy demo behavior.
        assert await store.delete("c") is True

    async def test_matching_principal_deletes(self) -> None:
        store = InMemoryConversationStore()
        await store.create(
            Conversation(
                conversation_id="c", title="C", principal_key_id="alice"
            )
        )
        assert await store.delete("c", principal_key_id="alice") is True
        assert await store.get("c") is None

    async def test_mismatched_principal_leaves_row_intact(self) -> None:
        store = InMemoryConversationStore()
        await store.create(
            Conversation(
                conversation_id="c", title="C", principal_key_id="alice"
            )
        )
        assert await store.delete("c", principal_key_id="bob") is False
        assert await store.get("c") is not None

    async def test_legacy_null_owner_is_untouchable_under_auth(self) -> None:
        store = InMemoryConversationStore()
        await store.create(
            Conversation(conversation_id="c", title="C", principal_key_id=None)
        )
        assert await store.delete("c", principal_key_id="alice") is False
        assert await store.get("c") is not None


# ---------------------------------------------------------------------------
# PostgresConversationStore
# ---------------------------------------------------------------------------


def _override_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    fresh = Settings(**overrides)  # type: ignore[arg-type]
    monkeypatch.setattr(postgres_pool, "settings", fresh)


if _postgres_available:

    @pytest.fixture
    def pg_url(
        postgresql_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[str]:
        info = postgresql_db.info
        url = f"postgresql://{info.user}:@{info.host}:{info.port}/{info.dbname}"
        _override_settings(monkeypatch, postgres_url=url)
        postgres_pool._reset_for_test(None)
        yield url
        postgres_pool.close_pool()


@pytestmark_postgres
@pytest.mark.integration
class TestPostgresConversationStore:
    async def test_create_and_get_roundtrip(self, pg_url: str) -> None:
        store = PostgresConversationStore()
        await store.create(Conversation(conversation_id="c1", title="First"))
        got = await store.get("c1")
        assert got is not None
        assert got.title == "First"

    async def test_get_missing_returns_none(self, pg_url: str) -> None:
        store = PostgresConversationStore()
        assert await store.get("nope") is None

    async def test_append_job_and_get_returns_jobs_in_order(
        self, pg_url: str
    ) -> None:
        store = PostgresConversationStore()
        await store.create(Conversation(conversation_id="c", title="C"))
        await store.append_job("c", "j1", "q1", "report1")
        await store.append_job("c", "j2", "q2", "report2")
        got = await store.get("c")
        assert got is not None
        assert [j.ordinal for j in got.jobs] == [1, 2]
        assert got.jobs[0].job_id == "j1"

    async def test_list_orders_by_updated_at_desc(self, pg_url: str) -> None:
        store = PostgresConversationStore()
        await store.create(Conversation(conversation_id="a", title="A"))
        await store.create(Conversation(conversation_id="b", title="B"))
        # Bump b.
        await store.append_job("b", "j1", "q", "r")
        got = await store.list()
        assert got[0].conversation_id == "b"

    async def test_delete_cascades_to_jobs(self, pg_url: str) -> None:
        store = PostgresConversationStore()
        await store.create(Conversation(conversation_id="c", title="C"))
        await store.append_job("c", "j1", "q", "r")
        assert await store.delete("c") is True

        # Verify the conversation_jobs row went with it (FK cascade).
        with psycopg.connect(pg_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM conversation_jobs "
                "WHERE conversation_id = %s",
                ("c",),
            )
            assert cur.fetchone() == (0,)

    async def test_list_pagination(self, pg_url: str) -> None:
        """ADR 0043: LIMIT/OFFSET applied in SQL, newest first, with
        disjoint consecutive pages."""
        store = PostgresConversationStore()
        for i in range(5):
            await store.create(
                Conversation(conversation_id=f"c{i}", title=f"T{i}")
            )
            # Bump updated_at in creation order so ordering is
            # deterministic (NOW() has microsecond resolution but
            # the inserts can share a transaction timestamp).
            await store.append_job(f"c{i}", f"j{i}", "q", "r")

        page1 = await store.list(limit=2)
        page2 = await store.list(limit=2, offset=2)
        assert [c.conversation_id for c in page1] == ["c4", "c3"]
        assert [c.conversation_id for c in page2] == ["c2", "c1"]
        assert await store.list(limit=50, offset=10) == []

    async def test_list_pagination_composes_with_scoping(
        self, pg_url: str
    ) -> None:
        store = PostgresConversationStore()
        for i in range(4):
            owner = "alice" if i % 2 == 0 else "bob"
            await store.create(
                Conversation(
                    conversation_id=f"c{i}",
                    title=f"T{i}",
                    principal_key_id=owner,
                )
            )
            await store.append_job(f"c{i}", f"j{i}", "q", "r")

        got = await store.list("alice", limit=1, offset=1)
        assert [c.conversation_id for c in got] == ["c0"]
        assert all(c.principal_key_id == "alice" for c in got)

    async def test_scoped_delete_single_statement(self, pg_url: str) -> None:
        """ADR 0043: mismatch and legacy-NULL rows survive a scoped
        delete; a matching owner's delete succeeds."""
        store = PostgresConversationStore()
        await store.create(
            Conversation(
                conversation_id="owned", title="T", principal_key_id="alice"
            )
        )
        await store.create(
            Conversation(
                conversation_id="legacy", title="T", principal_key_id=None
            )
        )

        assert await store.delete("owned", principal_key_id="bob") is False
        assert await store.get("owned") is not None
        assert await store.delete("legacy", principal_key_id="alice") is False
        assert await store.get("legacy") is not None
        assert await store.delete("owned", principal_key_id="alice") is True
        assert await store.get("owned") is None
        # Auth-off (`None`) stays unscoped.
        assert await store.delete("legacy") is True

    async def test_update_title_persists(self, pg_url: str) -> None:
        """ADR 0048. Mutating the fetched `Conversation` was a no-op
        here — the row is detached — so auto-titling never reached the
        database and the placeholder survived forever."""
        store = PostgresConversationStore()
        await store.create(
            Conversation(conversation_id="c", title="New conversation")
        )

        assert await store.update_title("c", "Attention mechanisms") is True

        got = await store.get("c")
        assert got is not None
        assert got.title == "Attention mechanisms"

    async def test_update_title_missing_returns_false(
        self, pg_url: str
    ) -> None:
        store = PostgresConversationStore()
        assert await store.update_title("nope", "T") is False

    async def test_update_title_leaves_updated_at_alone(
        self, pg_url: str
    ) -> None:
        # A rename must not reorder the sidebar; the SET list omitting
        # `updated_at` is what guarantees that, and the column has no
        # ON UPDATE trigger behind it.
        store = PostgresConversationStore()
        await store.create(Conversation(conversation_id="c", title="T"))
        before = await store.get("c")
        assert before is not None

        assert await store.update_title("c", "Renamed") is True

        after = await store.get("c")
        assert after is not None
        assert after.updated_at == before.updated_at

    async def test_update_title_is_ownership_agnostic(
        self, pg_url: str
    ) -> None:
        store = PostgresConversationStore()
        await store.create(
            Conversation(
                conversation_id="c", title="T", principal_key_id="alice"
            )
        )
        assert await store.update_title("c", "Renamed") is True
        got = await store.get("c")
        assert got is not None
        assert got.title == "Renamed"
        assert got.principal_key_id == "alice"

    async def test_concurrent_appends_never_collide(self, pg_url: str) -> None:
        """ADR 0043: the parent-row lock serializes concurrent
        appends, so N parallel appends land as ordinals 1..N instead
        of racing on MAX(ordinal) and dying on the primary key."""
        store = PostgresConversationStore()
        await store.create(Conversation(conversation_id="c", title="C"))

        results = await asyncio.gather(
            *(store.append_job("c", f"j{i}", "q", "r") for i in range(8))
        )
        ordinals = sorted(j.ordinal for j in results if j is not None)
        assert ordinals == list(range(1, 9))

        got = await store.get("c")
        assert got is not None
        assert len(got.jobs) == 8


# ---------------------------------------------------------------------------
# Postgres store — loop-safety + failure-visibility unit tests.
# These run without a Postgres server: the pool module's seams are
# monkeypatched with fakes, so they exercise the store's threading
# and logging behavior, not SQL.
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Just enough cursor for the store's code paths: every SELECT
    comes back empty, every DELETE reports zero rows."""

    rowcount = 0

    def execute(self, sql: str, params: Any = None) -> None:
        return None

    def fetchone(self) -> Any:
        return None

    def fetchall(self) -> list[Any]:
        return []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class _FakeConnection:
    def cursor(self) -> _FakeCursor:
        return _FakeCursor()

    def commit(self) -> None:
        return None

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *args: Any) -> None:
        return None


@pytest.mark.unit
class TestSchemaInitStaysOffTheEventLoop:
    """ADR 0043: `init_schema()` — pool open + DDL, blocking, up to
    10s+ — must run on the `asyncio.to_thread` worker. On the loop it
    froze every in-flight request while Postgres was slow or down."""

    async def test_no_method_calls_init_schema_on_the_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[threading.Thread] = []

        def fake_init_schema(url: str | None = None) -> None:
            calls.append(threading.current_thread())

        monkeypatch.setattr(postgres_pool, "init_schema", fake_init_schema)
        monkeypatch.setattr(
            postgres_pool, "_connection", lambda: _FakeConnection()
        )

        store = PostgresConversationStore()
        loop_thread = threading.current_thread()

        await store.create(Conversation(conversation_id="c", title="C"))
        await store.get("c")
        await store.list()
        await store.append_job("c", "j", "q", "r")
        await store.delete("c")

        # All five methods bootstrapped the schema, and none did it
        # on the event-loop thread.
        assert len(calls) == 5
        assert all(t is not loop_thread for t in calls)


@pytest.mark.unit
class TestAppendFailureIsLogged:
    """ADR 0043: the runner suppresses append errors wholesale, so
    the store logs at ERROR before the exception propagates —
    otherwise a paid-for report disappears with no trace."""

    async def test_append_error_logs_then_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def fake_init_schema(url: str | None = None) -> None:
            return None

        def broken_connection() -> Any:
            raise RuntimeError("pool exploded")

        monkeypatch.setattr(postgres_pool, "init_schema", fake_init_schema)
        monkeypatch.setattr(postgres_pool, "_connection", broken_connection)

        store = PostgresConversationStore()
        with (
            caplog.at_level(logging.ERROR, logger="src.api.conversations"),
            pytest.raises(RuntimeError, match="pool exploded"),
        ):
            await store.append_job("c", "j1", "q", "r")

        messages = [r.message for r in caplog.records]
        assert "conversation_append_failed" in messages


# ---------------------------------------------------------------------------
# Cross-impl parity contract
# ---------------------------------------------------------------------------


class TestParityContract:
    """The two stores should be behaviorally equivalent for the calls
    the API layer makes."""

    async def _run(self, store: object) -> None:
        s: InMemoryConversationStore | PostgresConversationStore = store  # type: ignore[assignment]
        await s.create(Conversation(conversation_id="c", title="C"))
        assert (await s.get("c")) is not None
        j = await s.append_job("c", "j1", "q1", "report1")
        assert j is not None and j.ordinal == 1
        detail = await s.get("c")
        assert detail is not None
        assert len(detail.jobs) == 1
        # ADR 0048: `update_title` is part of the surface the API layer
        # uses, so parity covers it too.
        assert await s.update_title("c", "Renamed") is True
        renamed = await s.get("c")
        assert renamed is not None and renamed.title == "Renamed"
        assert await s.update_title("nope", "T") is False
        assert await s.delete("c") is True
        assert await s.get("c") is None

    @pytest.mark.unit
    async def test_in_memory_satisfies_contract(self) -> None:
        await self._run(InMemoryConversationStore())

    @pytestmark_postgres
    @pytest.mark.integration
    async def test_postgres_satisfies_contract(self, pg_url: str) -> None:
        await self._run(PostgresConversationStore())


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


class _StubWorkflow:
    """Minimal workflow — every job succeeds instantly with a canned
    report body containing a deterministic keyword the retriever can
    target."""

    def __init__(self, report: str = "# Report\n\nBody paragraph.") -> None:
        self.report = report

    async def astream(self, state, config=None):  # type: ignore[no-untyped-def]
        if state is not None:
            yield {"planner": {"iteration": 0}}

    def get_state(self, config=None):  # type: ignore[no-untyped-def]
        from types import SimpleNamespace

        return SimpleNamespace(next=(), values={"draft_report": self.report})

    def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
        return {"draft_report": self.report, "iteration": 1, "quality_score": 0.9}

    async def aget_state(self, config=None):  # type: ignore[no-untyped-def]
        # ADR 0040: the async runner reads the settled values here.
        from types import SimpleNamespace

        return SimpleNamespace(
            next=(),
            values={
                "draft_report": self.report,
                "iteration": 1,
                "quality_score": 0.9,
            },
        )


async def _client() -> AsyncIterator[AsyncClient]:
    app = create_app(build_workflow=lambda: _StubWorkflow())
    async with LifespanManager(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


# Drives the real ASGI app through httpx, so `integration` by the tier
# definition in docs/testing.md.
@pytest.mark.integration
class TestConversationEndpoints:
    async def test_create_returns_201_with_defaults(self) -> None:
        async for client in _client():
            resp = await client.post("/conversations", json={})
            assert resp.status_code == 201
            body = resp.json()
            assert len(body["conversation_id"]) == 16
            assert body["title"] == "New conversation"
            assert body["jobs"] == []

    async def test_create_with_title(self) -> None:
        async for client in _client():
            resp = await client.post(
                "/conversations", json={"title": "Hallucination research"}
            )
            assert resp.status_code == 201
            assert resp.json()["title"] == "Hallucination research"

    async def test_list_empty_returns_empty_array(self) -> None:
        async for client in _client():
            resp = await client.get("/conversations")
            assert resp.status_code == 200
            assert resp.json() == []

    async def test_list_returns_created_conversations(self) -> None:
        async for client in _client():
            for i in range(3):
                await client.post("/conversations", json={"title": f"T{i}"})
            resp = await client.get("/conversations")
            assert resp.status_code == 200
            assert len(resp.json()) == 3

    async def test_list_respects_limit_and_offset(self) -> None:
        async for client in _client():
            for i in range(3):
                await client.post("/conversations", json={"title": f"T{i}"})
            page1 = await client.get("/conversations", params={"limit": 2})
            assert page1.status_code == 200
            assert len(page1.json()) == 2
            page2 = await client.get(
                "/conversations", params={"limit": 2, "offset": 2}
            )
            assert page2.status_code == 200
            assert len(page2.json()) == 1
            # No overlap between consecutive pages.
            ids1 = {c["conversation_id"] for c in page1.json()}
            ids2 = {c["conversation_id"] for c in page2.json()}
            assert not ids1 & ids2

    async def test_list_limit_above_cap_is_422(self) -> None:
        async for client in _client():
            resp = await client.get("/conversations", params={"limit": 201})
            assert resp.status_code == 422

    async def test_list_limit_zero_is_422(self) -> None:
        async for client in _client():
            resp = await client.get("/conversations", params={"limit": 0})
            assert resp.status_code == 422

    async def test_list_negative_offset_is_422(self) -> None:
        async for client in _client():
            resp = await client.get("/conversations", params={"offset": -1})
            assert resp.status_code == 422

    async def test_get_returns_404_for_missing(self) -> None:
        async for client in _client():
            resp = await client.get("/conversations/nonexistent")
            assert resp.status_code == 404

    async def test_delete_returns_204_then_404(self) -> None:
        async for client in _client():
            cid = (
                (await client.post("/conversations", json={"title": "T"}))
                .json()["conversation_id"]
            )
            resp = await client.delete(f"/conversations/{cid}")
            assert resp.status_code == 204
            resp = await client.get(f"/conversations/{cid}")
            assert resp.status_code == 404

    async def test_delete_missing_returns_404(self) -> None:
        async for client in _client():
            resp = await client.delete("/conversations/nonexistent")
            assert resp.status_code == 404


@pytest.mark.integration
class TestResearchWithConversation:
    async def test_bad_conversation_id_is_404(self) -> None:
        async for client in _client():
            resp = await client.post(
                "/research",
                json={
                    "query": "q",
                    "hitl_bypass": True,
                    "conversation_id": "nope",
                },
            )
            assert resp.status_code == 404
            assert resp.json()["detail"] == "conversation_not_found"

    async def test_successful_job_appended_to_conversation(self) -> None:
        async for client in _client():
            cid = (
                (await client.post("/conversations", json={"title": "T"}))
                .json()["conversation_id"]
            )
            r = await client.post(
                "/research",
                json={
                    "query": "hallucination",
                    "hitl_bypass": True,
                    "conversation_id": cid,
                },
            )
            assert r.status_code == 202
            job_id = r.json()["job_id"]

            # Wait for terminal.
            import asyncio as _a

            for _ in range(50):
                d = await client.get(f"/research/{job_id}")
                if d.json()["status"] == "succeeded":
                    break
                await _a.sleep(0.02)

            # The conversation now carries the job.
            detail = (await client.get(f"/conversations/{cid}")).json()
            assert len(detail["jobs"]) == 1
            assert detail["jobs"][0]["job_id"] == job_id
            assert detail["jobs"][0]["ordinal"] == 1
            assert "Body paragraph" in detail["jobs"][0]["report"]

    async def test_job_detail_carries_conversation_id(self) -> None:
        async for client in _client():
            cid = (
                (await client.post("/conversations", json={"title": "T"}))
                .json()["conversation_id"]
            )
            r = await client.post(
                "/research",
                json={
                    "query": "q",
                    "hitl_bypass": True,
                    "conversation_id": cid,
                },
            )
            job_id = r.json()["job_id"]
            detail = (await client.get(f"/research/{job_id}")).json()
            assert detail["conversation_id"] == cid


@pytest.mark.asyncio
@pytest.mark.integration
async def test_first_job_auto_title_persists_through_the_store() -> None:
    """The auto-title must go through `update_title` (ADR 0048).

    Mutating the fetched Conversation object was enough for the
    in-memory store but a silent no-op under Postgres — the rename
    vanished on the next read from another worker. This drives the
    runner's append path and asserts the store-level rename happened.
    """
    from src.api.jobs import Job, JobStatus
    from src.api.runner import _append_to_conversation

    store = InMemoryConversationStore()
    await store.create(Conversation(conversation_id="c1", title="New conversation"))

    calls: list[tuple[str, str]] = []
    original = store.update_title

    async def recording(conversation_id: str, title: str) -> bool:
        calls.append((conversation_id, title))
        return await original(conversation_id, title)

    store.update_title = recording  # type: ignore[method-assign]

    job = Job(job_id="j1", query="what is flash attention", conversation_id="c1")
    job.status = JobStatus.succeeded
    job.result = "# Report"
    await _append_to_conversation(store, job)

    assert calls, "auto-title bypassed the store's update_title"
    got = await store.get("c1")
    assert got is not None and got.title != "New conversation"
