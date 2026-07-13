"""Workflow is compiled once at app startup (ADR 0034).

Audit finding: `build_workflow()` was called per-request from
`run_job`, which opened a fresh checkpointer connection via
`ExitStack` that never closed until interpreter shutdown. Under
load this leaked SQLite file handles and — worse — put a
single-writer SQLite file under concurrent write pressure. The
fix moves compilation into the FastAPI lifespan; every job uses
the same compiled instance.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from asgi_lifespan import LifespanManager

from src.api.app import create_app
from src.api.jobs import InMemoryJobStore

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
