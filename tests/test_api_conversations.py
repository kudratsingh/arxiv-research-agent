"""Tests for the ConversationStore (in-memory + Postgres) and the
conversation endpoints (ADR 0032).

Postgres tests use `pytest-postgresql`; identical setup to the
paper-cache and embedding-cache tests. Skipped locally when the
system doesn't have the `postgres` server binary.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import AsyncIterator, Iterator

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
        assert await s.delete("c") is True
        assert await s.get("c") is None

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


async def _client() -> AsyncIterator[AsyncClient]:
    app = create_app(build_workflow=lambda: _StubWorkflow())
    async with LifespanManager(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


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
