"""Checkpointer backend selection in `build_workflow` (ADR 0034/0040).

The audit surfaced two related crits: the SqliteSaver was opened
per-request (leak), and multi-worker HITL couldn't work under
SqliteSaver anyway (single-writer file). ADR 0034 introduces a
`checkpoint_backend` selector and shifts compilation to app
startup. These tests pin the dispatch: `sqlite` calls into
`langgraph.checkpoint.sqlite.SqliteSaver`, `postgres` calls into
`langgraph.checkpoint.postgres.PostgresSaver`, and an unknown
value fails fast at configuration time.

ADR 0040 adds the async surface the API runner requires: with
`async_checkpointer=True`, `sqlite` dispatches to `AsyncSqliteSaver`
and `postgres` to `AsyncPostgresSaver` on a reconnecting
`psycopg_pool.AsyncConnectionPool`. The sync dispatch tests above
double as the proof that the CLI / eval path (`build_workflow()`
with defaults) still gets the sync savers, unchanged.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.graph import workflow as workflow_module

pytestmark = pytest.mark.unit


class TestOpenCheckpointer:
    """`_open_checkpointer` is the branch point — verify it dispatches
    to the correct backend without booting a real DB."""

    def test_disabled_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(enable_checkpointing=False),
        )
        with ExitStack() as stack:
            assert workflow_module._open_checkpointer(stack) is None

    def test_sqlite_backend_opens_sqlite_saver(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(
                enable_checkpointing=True,
                checkpoint_backend="sqlite",
                checkpoint_db_path=str(tmp_path / "cp.sqlite"),
            ),
        )
        with (
            patch(
                "langgraph.checkpoint.sqlite.SqliteSaver.from_conn_string"
            ) as sqlite_ctor,
            patch(
                "langgraph.checkpoint.postgres.PostgresSaver.from_conn_string"
            ) as postgres_ctor,
        ):
            fake_cm = MagicMock()
            fake_cm.__enter__ = MagicMock(return_value=MagicMock(name="saver"))
            fake_cm.__exit__ = MagicMock(return_value=False)
            sqlite_ctor.return_value = fake_cm

            with ExitStack() as stack:
                got = workflow_module._open_checkpointer(stack)

            sqlite_ctor.assert_called_once()
            postgres_ctor.assert_not_called()
            assert got is not None

    def test_postgres_backend_opens_postgres_saver_and_calls_setup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(
                enable_checkpointing=True,
                checkpoint_backend="postgres",
                postgres_url="postgresql://arxiv:arxiv@postgres:5432/arxiv",
            ),
        )
        fake_saver = MagicMock(name="postgres_saver")
        with (
            patch(
                "langgraph.checkpoint.postgres.PostgresSaver.from_conn_string"
            ) as postgres_ctor,
            patch(
                "langgraph.checkpoint.sqlite.SqliteSaver.from_conn_string"
            ) as sqlite_ctor,
        ):
            fake_cm = MagicMock()
            fake_cm.__enter__ = MagicMock(return_value=fake_saver)
            fake_cm.__exit__ = MagicMock(return_value=False)
            postgres_ctor.return_value = fake_cm

            with ExitStack() as stack:
                got = workflow_module._open_checkpointer(stack)

            postgres_ctor.assert_called_once_with(
                "postgresql://arxiv:arxiv@postgres:5432/arxiv"
            )
            sqlite_ctor.assert_not_called()
            # `.setup()` is idempotent DDL — must be called so a
            # cold Postgres has the checkpoint tables ready.
            fake_saver.setup.assert_called_once()
            assert got is fake_saver

    def test_postgres_backend_empty_url_fails_fast(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(
                enable_checkpointing=True,
                checkpoint_backend="postgres",
                postgres_url="",
            ),
        )
        with ExitStack() as stack, pytest.raises(RuntimeError, match="POSTGRES_URL"):
            workflow_module._open_checkpointer(stack)

    def test_unknown_backend_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR 0046 made `checkpoint_backend` a Literal, so a real
        `Settings` can no longer carry an unknown value (that
        rejection is pinned in test_config.py). The raise here is
        defense-in-depth for direct callers that bypass settings —
        reach it with a namespace stub."""
        from types import SimpleNamespace

        monkeypatch.setattr(
            workflow_module,
            "settings",
            SimpleNamespace(
                enable_checkpointing=True,
                checkpoint_backend="mysql",
            ),
        )
        with ExitStack() as stack, pytest.raises(ValueError, match="checkpoint_backend"):
            workflow_module._open_checkpointer(stack)


class TestAsyncOpenCheckpointer:
    """ADR 0040: `_aopen_checkpointer` must dispatch to the ASYNC
    savers — the sync ones raise `NotImplementedError` from every
    async method, so an `astream`-driven runner cannot use them."""

    async def test_disabled_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(enable_checkpointing=False),
        )
        async with AsyncExitStack() as stack:
            assert await workflow_module._aopen_checkpointer(stack) is None

    async def test_sqlite_backend_opens_async_sqlite_saver(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(
                enable_checkpointing=True,
                checkpoint_backend="sqlite",
                checkpoint_db_path=str(tmp_path / "cp.sqlite"),
            ),
        )
        fake_saver = MagicMock(name="async_sqlite_saver")
        fake_cm = MagicMock()
        fake_cm.__aenter__ = AsyncMock(return_value=fake_saver)
        fake_cm.__aexit__ = AsyncMock(return_value=False)
        with (
            patch(
                "langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver.from_conn_string",
                return_value=fake_cm,
            ) as async_ctor,
            patch(
                "langgraph.checkpoint.sqlite.SqliteSaver.from_conn_string"
            ) as sync_ctor,
        ):
            async with AsyncExitStack() as stack:
                got = await workflow_module._aopen_checkpointer(stack)
                assert got is fake_saver
            async_ctor.assert_called_once()
            sync_ctor.assert_not_called()
        # The stack owns the saver's lifetime.
        fake_cm.__aexit__.assert_awaited_once()

    async def test_postgres_backend_builds_pool_and_calls_setup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        url = "postgresql://arxiv:arxiv@postgres:5432/arxiv"
        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(
                enable_checkpointing=True,
                checkpoint_backend="postgres",
                postgres_url=url,
            ),
        )
        fake_pool = MagicMock(name="async_pool")
        fake_pool.open = AsyncMock()
        fake_pool.close = AsyncMock()
        fake_saver = MagicMock(name="async_postgres_saver")
        fake_saver.setup = AsyncMock()
        with (
            patch(
                "psycopg_pool.AsyncConnectionPool", return_value=fake_pool
            ) as pool_ctor,
            patch(
                "langgraph.checkpoint.postgres.aio.AsyncPostgresSaver",
                return_value=fake_saver,
            ) as saver_ctor,
        ):
            async with AsyncExitStack() as stack:
                got = await workflow_module._aopen_checkpointer(stack)
                assert got is fake_saver
                # Pool built against the URL, with reconnect-friendly
                # connection kwargs, and explicitly opened.
                assert pool_ctor.call_args.args[0] == url
                kwargs = pool_ctor.call_args.kwargs
                assert kwargs["kwargs"]["autocommit"] is True
                assert kwargs["kwargs"]["prepare_threshold"] == 0
                assert kwargs["check"] is not None
                fake_pool.open.assert_awaited_once()
                saver_ctor.assert_called_once_with(fake_pool)
                # Idempotent DDL, same as the sync path.
                fake_saver.setup.assert_awaited_once()
            # Stack teardown closes the pool.
            fake_pool.close.assert_awaited_once()

    async def test_postgres_backend_empty_url_fails_fast(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(
                enable_checkpointing=True,
                checkpoint_backend="postgres",
                postgres_url="",
            ),
        )
        async with AsyncExitStack() as stack:
            with pytest.raises(RuntimeError, match="POSTGRES_URL"):
                await workflow_module._aopen_checkpointer(stack)

    async def test_unknown_backend_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(
                enable_checkpointing=True,
                checkpoint_backend="mysql",
            ),
        )
        async with AsyncExitStack() as stack:
            with pytest.raises(ValueError, match="checkpoint_backend"):
                await workflow_module._aopen_checkpointer(stack)


class TestBuildWorkflowModes:
    """`build_workflow` keeps its sync contract for the CLI / eval
    path and returns an awaitable for the API path (ADR 0040)."""

    def test_sync_mode_returns_compiled_app_directly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import inspect

        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(enable_checkpointing=False),
        )
        compiled = workflow_module.build_workflow()
        assert not inspect.isawaitable(compiled)
        # Sync teardown handle attached; no async stack.
        assert hasattr(compiled, "_checkpointer_exit_stack")
        assert not hasattr(compiled, "_checkpointer_aexit_stack")

    async def test_async_mode_returns_awaitable_with_async_stack(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import inspect

        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(enable_checkpointing=False),
        )
        maybe = workflow_module.build_workflow(async_checkpointer=True)
        assert inspect.isawaitable(maybe)
        compiled = await maybe
        assert hasattr(compiled, "_checkpointer_aexit_stack")
        await compiled._checkpointer_aexit_stack.aclose()
