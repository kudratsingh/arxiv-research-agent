"""Workflow compilation + background tasks in the app lifespan.

ADR 0034: `build_workflow()` was called per-request from `run_job`,
which opened a fresh checkpointer connection via `ExitStack` that
never closed until interpreter shutdown. Under load this leaked
SQLite file handles and — worse — put a single-writer SQLite file
under concurrent write pressure. The fix moves compilation into the
FastAPI lifespan; every job uses the same compiled instance.

ADR 0040 adds two lifespan behaviors pinned here: an async-mode
factory (returning an awaitable) is awaited at startup, and the
in-memory retention sweep runs periodically — but only for stores
without backend-managed retention (duck-typed on `scan_jobs`).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from asgi_lifespan import LifespanManager

from src.api import app as app_module
from src.api.app import create_app
from src.api.jobs import InMemoryJobStore, Job

pytestmark = pytest.mark.unit


@pytest.fixture
async def app_with_counting_factory() -> AsyncIterator[
    tuple[httpx.AsyncClient, list[int]]
]:
    """Yield (client, calls) — `calls` is a per-test counter of how
    many times `build_workflow` was invoked. Expect exactly 1."""
    calls: list[int] = []

    def counting_factory() -> Any:
        calls.append(1)
        return MagicMock(name="compiled_workflow")

    app = create_app(
        build_workflow=counting_factory,
        store=InMemoryJobStore(),
    )
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client, calls


@pytest.mark.asyncio
async def test_factory_runs_once_at_startup(
    app_with_counting_factory: tuple[httpx.AsyncClient, list[int]],
) -> None:
    _client, calls = app_with_counting_factory
    # Lifespan has already run — the factory should have fired once.
    assert sum(calls) == 1


@pytest.mark.asyncio
async def test_workflow_singleton_stored_on_app_state(
    app_with_counting_factory: tuple[httpx.AsyncClient, list[int]],
) -> None:
    """The compiled workflow lives on `app.state.workflow` and every
    request handler reads the same instance."""
    client, calls = app_with_counting_factory
    # Hit healthz to prove the app is up. Then dip into the app
    # state via the underlying app to verify the workflow slot.
    r = await client.get("/healthz")
    assert r.status_code == 200

    # Sanity: only the one startup call.
    assert sum(calls) == 1

    underlying = client._transport.app  # ASGI app
    assert underlying.state.workflow is not None
    # Should still be a MagicMock — our factory returned one.
    assert isinstance(underlying.state.workflow, MagicMock)


@pytest.mark.asyncio
async def test_async_factory_result_is_awaited() -> None:
    """ADR 0040: the production factory returns an awaitable (the
    async savers need a running loop to open); the lifespan must
    await it rather than store the bare coroutine."""
    compiled = MagicMock(name="compiled_workflow")

    async def _build() -> Any:
        return compiled

    app = create_app(build_workflow=_build, store=InMemoryJobStore())
    async with LifespanManager(app):
        assert app.state.workflow is compiled


class _CountingEvictStore(InMemoryJobStore):
    """InMemoryJobStore whose evict calls are observable."""

    def __init__(self) -> None:
        super().__init__()
        self.evict_calls = 0

    async def evict_older_than(self, retention_sec: int) -> int:
        self.evict_calls += 1
        return await super().evict_older_than(retention_sec)


class _BackendManagedStore(_CountingEvictStore):
    """A store advertising `scan_jobs` — the ADR-0038 marker for
    backend-managed retention (RedisJobStore expires rows via TTL)."""

    async def scan_jobs(self, *, max_scan: int) -> tuple[list[Job], bool]:
        return [], False


@pytest.mark.asyncio
async def test_retention_sweep_runs_for_in_memory_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0040: `evict_older_than` finally has a production caller —
    without the sweep, `api_job_retention_sec` was documented but
    unenforced for the in-memory store."""
    monkeypatch.setattr(app_module, "EVICT_SWEEP_INTERVAL_SEC", 0.01)
    store = _CountingEvictStore()
    app = create_app(
        build_workflow=lambda: MagicMock(name="wf"), store=store
    )
    async with LifespanManager(app):
        deadline = asyncio.get_event_loop().time() + 2.0
        while store.evict_calls == 0:
            assert asyncio.get_event_loop().time() < deadline, (
                "retention sweep never ran"
            )
            await asyncio.sleep(0.02)
    # Shutdown cancelled the task; no further sweeps after exit.
    settled = store.evict_calls
    await asyncio.sleep(0.05)
    assert store.evict_calls == settled


@pytest.mark.asyncio
async def test_retention_sweep_skipped_for_backend_managed_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "EVICT_SWEEP_INTERVAL_SEC", 0.01)
    store = _BackendManagedStore()
    app = create_app(
        build_workflow=lambda: MagicMock(name="wf"), store=store
    )
    async with LifespanManager(app):
        await asyncio.sleep(0.1)
    assert store.evict_calls == 0
