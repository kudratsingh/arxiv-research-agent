"""Continuous process lifecycle plus real Postgres lease/stop recovery."""

from __future__ import annotations

import json
import os
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.workspace import scheduler
from src.workspace import worker as w
from src.workspace.schemas import ScheduleData, ScheduleWrite
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 2, 16, tzinfo=UTC)


def test_disabled_worker_has_heartbeat_but_no_cycle_or_dependency_construction(
    tmp_path: Path,
) -> None:
    cycle = MagicMock()
    path = tmp_path / "heartbeat.json"
    waits = []
    result = w.run_worker(
        cycle,
        enabled=True,
        approved=False,
        heartbeat_path=path,
        max_cycles=2,
        now=lambda: NOW,
        wait=waits.append,
    )
    cycle.assert_not_called()
    assert result.cycles == 2 and result.state == "stopped"
    assert waits == [30]
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text())["last_task_id"] is None
    assert not list(tmp_path.glob(".worker-heartbeat-*"))


def test_ready_idle_and_unique_attempt_tokens(tmp_path: Path) -> None:
    tokens = []

    def cycle(stop, token):
        assert not stop()
        tokens.append(token)
        return (
            {"state": "ready", "id": "task-1", "private_payload": "MUST NOT LOG"}
            if len(tokens) == 1
            else None
        )

    path = tmp_path / "heartbeat.json"
    result = w.run_worker(
        cycle,
        enabled=True,
        approved=True,
        heartbeat_path=path,
        max_cycles=2,
        now=lambda: NOW,
        wait=lambda _: None,
        worker_id="local-worker",
    )
    assert len(set(tokens)) == 2 and all(token.startswith("local-worker:") for token in tokens)
    assert result.last_task_id == "task-1" and result.last_ready_at == NOW.isoformat()
    assert "MUST NOT LOG" not in path.read_text()


def test_database_failure_is_degraded_without_private_exception_message(tmp_path: Path) -> None:
    path = tmp_path / "heartbeat.json"
    stop = threading.Event()
    states = []

    def wait(_):
        states.append(w.health(path, now=NOW))
        stop.set()

    result = w.run_worker(
        MagicMock(side_effect=RuntimeError("secret private note")),
        enabled=True,
        approved=True,
        stop=stop,
        heartbeat_path=path,
        now=lambda: NOW,
        wait=wait,
    )
    assert states[0]["heartbeat"]["state"] == "degraded" and not states[0]["healthy"]
    assert result.last_error_class == "RuntimeError"
    assert "secret private note" not in path.read_text()


def test_failed_attempt_is_not_reported_as_success(tmp_path: Path) -> None:
    result = w.run_worker(
        lambda *_: {"id": "task", "state": "failed_attempt"},
        enabled=True,
        approved=True,
        heartbeat_path=tmp_path / "hb",
        max_cycles=1,
        now=lambda: NOW,
    )
    assert result.last_error_class == "task_attempt_failed" and result.last_ready_at is None


def test_stop_before_start_is_inert_and_bad_bounds_refuse(tmp_path: Path) -> None:
    stop = threading.Event()
    stop.set()
    cycle = MagicMock()
    assert (
        w.run_worker(
            cycle,
            enabled=True,
            approved=True,
            stop=stop,
            heartbeat_path=tmp_path / "hb",
            now=lambda: NOW,
        ).cycles
        == 0
    )
    cycle.assert_not_called()
    for kwargs in ({"interval": 0}, {"interval": 301}, {"max_cycles": 0}):
        with pytest.raises(ValueError, match="invalid_worker_bounds"):
            w.run_worker(
                cycle, enabled=True, approved=True, heartbeat_path=tmp_path / "hb", **kwargs
            )
    with pytest.raises(ValueError, match="worker_clock_requires_timezone"):
        w.run_worker(
            cycle,
            enabled=False,
            approved=False,
            heartbeat_path=tmp_path / "hb",
            now=lambda: datetime(2026, 11, 2),
        )


def test_heartbeat_write_failure_refuses_invisible_work_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycle = MagicMock()
    monkeypatch.setattr(w.os, "replace", MagicMock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        w.run_worker(
            cycle, enabled=True, approved=True, heartbeat_path=tmp_path / "hb", max_cycles=1
        )
    cycle.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_health_current_stale_stopped_clock_skew_and_invalid_shape(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    heartbeat = w.WorkerHeartbeat("worker", os.getpid(), "idle", NOW.isoformat())
    w.write_heartbeat(path, heartbeat)
    assert w.health(path, now=NOW)["healthy"]
    assert not w.health(path, now=NOW + timedelta(seconds=361))["healthy"]
    assert not w.health(path, now=NOW - timedelta(minutes=2))["healthy"]
    for bad in (
        {"extra_private_key": "never reflected"},
        [],
        {**json.loads(path.read_text()), "updated_at": "not-time"},
        {**json.loads(path.read_text()), "updated_at": "2026-11-02T10:00:00"},
    ):
        path.write_text(json.dumps(bad))
        result = w.health(path, now=NOW)
        assert not result["healthy"] and "never reflected" not in json.dumps(result)
    path.write_text("x" * 16001)
    assert not w.health(path, now=NOW)["healthy"]
    path.unlink()
    assert not w.health(path, now=NOW)["healthy"]
    with pytest.raises(ValueError, match="invalid_health_age"):
        w.health(path, max_age=0)


def test_cli_disabled_path_restores_signal_handlers_and_never_opens_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import config
    from src.tools import postgres_pool

    monkeypatch.setattr(
        config,
        "settings",
        config.settings.model_copy(
            update={"enable_workspace": True, "workspace_schedule_approved": False}
        ),
    )
    pool = MagicMock(side_effect=AssertionError("disabled worker constructed DB"))
    monkeypatch.setattr(postgres_pool, "get_pool", pool)
    original = signal.getsignal(signal.SIGTERM)
    path = tmp_path / "hb"
    assert w.main(["--heartbeat", str(path), "--max-cycles", "1"]) == 0
    assert signal.getsignal(signal.SIGTERM) == original
    pool.assert_not_called()
    assert os.environ["ANTHROPIC_API_KEY"] == "local-preview-disabled"
    assert w.main(["--heartbeat", str(path), "--healthcheck"]) == 1
    w.write_heartbeat(
        path, w.WorkerHeartbeat("worker", os.getpid(), "disabled", datetime.now(UTC).isoformat())
    )
    assert w.main(["--heartbeat", str(path), "--healthcheck"]) == 0


def test_cooperative_stop_is_checked_before_and_after_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build = MagicMock()
    assert w.durable_cycle(object(), build, lambda: True, "token") is None
    build.assert_not_called()

    def run(store, guarded, worker):
        return guarded("owner")

    monkeypatch.setattr(scheduler, "run_once", run)
    values = iter([False, True])
    with pytest.raises(w.WorkerStopping):
        w.durable_cycle(object(), build, lambda: next(values), "token")
    build.assert_not_called()
    stop = threading.Event()

    def stopping_build(owner):
        stop.set()
        return {"id": "not-published"}

    with pytest.raises(w.WorkerStopping):
        w.durable_cycle(object(), stopping_build, stop.is_set, "token")


def test_real_pg_stop_during_build_requeues_without_publication_then_recovers(store) -> None:
    now = datetime.now(UTC)
    scheduler.write_schedule(
        store,
        "worker-test",
        ScheduleWrite(revision=0, request_id="enable", data=ScheduleData(enabled=True)),
        approved=True,
        now=now - timedelta(days=1),
    )
    stop = threading.Event()

    def build(owner):
        result = store.edition(owner, [], minutes=15, revision=0, persist=False)
        stop.set()
        return result

    first = w.durable_cycle(store, build, stop.is_set, "interrupted-worker")
    assert first["state"] == "failed_attempt" and store.editions("worker-test") == []
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM workspace_delivery_intents").fetchone()[0] == 0
        conn.execute("UPDATE workspace_tasks SET due_at=%s", (now - timedelta(seconds=1),))
    stop.clear()
    result = w.durable_cycle(
        store,
        lambda owner: store.edition(owner, [], minutes=15, revision=0, persist=False),
        stop.is_set,
        "restarted-worker",
    )
    assert result["state"] == "ready" and result["id"] == first["id"]
    assert len(store.editions("worker-test")) == 1


def test_real_pg_continuous_workers_race_one_occurrence_and_recover_expired_lease(
    store, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    scheduler.write_schedule(
        store,
        "worker-test",
        ScheduleWrite(revision=0, request_id="enable", data=ScheduleData(enabled=True)),
        approved=True,
        now=now - timedelta(days=1),
    )
    scheduler.enqueue_due(store, now=now)
    dead = scheduler.claim(store, "dead-worker", now=now)
    assert dead is not None
    with store.pool.connection() as connection:
        connection.execute(
            "UPDATE workspace_tasks SET lease_until=%s WHERE id=%s",
            (now - timedelta(seconds=1), dead["id"]),
        )

    def build(owner):
        return store.edition(owner, [], minutes=15, revision=0, persist=False)

    def run(index):
        return w.run_worker(
            lambda stop, token: w.durable_cycle(store, build, stop, token),
            enabled=True,
            approved=True,
            heartbeat_path=tmp_path / f"worker-{index}",
            max_cycles=1,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(run, [1, 2]))
    assert sum(status.last_ready_at is not None for status in statuses) == 1
    assert len(store.editions("worker-test")) == 1
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM workspace_delivery_intents").fetchone()[0] == 1


def test_cli_approved_worker_reuses_one_real_pool_and_closes_it(
    store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src import config
    from src.tools import postgres_pool
    from src.workspace import routes

    monkeypatch.setattr(
        config,
        "settings",
        config.settings.model_copy(
            update={"enable_workspace": True, "workspace_schedule_approved": True}
        ),
    )
    monkeypatch.setattr(routes, "_store", None)
    opened = MagicMock(return_value=store.pool)
    closed = MagicMock()
    monkeypatch.setattr(postgres_pool, "get_pool", opened)
    monkeypatch.setattr(postgres_pool, "close_pool", closed)
    assert (
        w.main(["--heartbeat", str(tmp_path / "hb"), "--max-cycles", "2", "--poll-seconds", "1"])
        == 0
    )
    opened.assert_called_once()
    closed.assert_called_once()
    assert json.loads((tmp_path / "hb").read_text())["cycles"] == 2


def test_health_rejects_invalid_runtime_field_types(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    base = {"worker_id": "worker", "pid": 123, "state": "idle", "updated_at": NOW.isoformat()}
    for changed in ({"state": []}, {"pid": "unknown"}, {"cycles": "many"}):
        path.write_text(json.dumps({**base, **changed}))
        assert w.health(path, now=NOW) == {
            "healthy": False,
            "reason": "heartbeat_unavailable_or_invalid",
        }
