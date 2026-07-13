"""Checkpointer backend selection in `build_workflow` (ADR 0034).

The audit surfaced two related crits: the SqliteSaver was opened
per-request (leak), and multi-worker HITL couldn't work under
SqliteSaver anyway (single-writer file). ADR 0034 introduces a
`checkpoint_backend` selector and shifts compilation to app
startup. These tests pin the dispatch: `sqlite` calls into
`langgraph.checkpoint.sqlite.SqliteSaver`, `postgres` calls into
`langgraph.checkpoint.postgres.PostgresSaver`, and an unknown
value fails fast at configuration time.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

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
        monkeypatch.setattr(
            workflow_module,
            "settings",
            Settings(
                enable_checkpointing=True,
                checkpoint_backend="mysql",
            ),
        )
        with ExitStack() as stack, pytest.raises(ValueError, match="checkpoint_backend"):
            workflow_module._open_checkpointer(stack)
