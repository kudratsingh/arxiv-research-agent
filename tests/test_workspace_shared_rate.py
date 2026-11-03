"""Cross-worker source pacing on isolated real Postgres, with zero HTTP requests."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from src.workspace import rate_limit as r
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


@pytest.fixture
def rate_url(store):
    return make_conninfo(store.pool.conninfo, **store.pool.kwargs)


def last_start(store, group):
    with store.pool.connection() as connection:
        row = connection.execute(
            "SELECT last_started_at FROM workspace_source_rate WHERE group_id=%s", (group,)
        ).fetchone()
    return row[0] if row else None


def test_two_workers_serialize_and_respect_committed_db_clock_interval(store, rate_url):
    barrier = threading.Barrier(2)
    mutex = threading.Lock()
    active = 0
    maximum = 0
    starts = []

    def fetch_slot():
        nonlocal active, maximum
        barrier.wait(timeout=2)
        with r.shared_rate_slot(rate_url, "arxiv", 0.02):
            with mutex:
                active += 1
                maximum = max(maximum, active)
                starts.append(last_start(store, "arxiv"))
            with store.pool.connection() as connection:
                sessions = connection.execute(
                    "SELECT a.state,a.xact_start FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid WHERE a.application_name='workspace-source-rate' AND a.datname=current_database() AND l.locktype='advisory' AND l.granted"
                ).fetchall()
                assert sessions == [("idle", None)]
            time.sleep(0.01)
            with mutex:
                active -= 1

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = workers.submit(fetch_slot), workers.submit(fetch_slot)
        first.result(timeout=3)
        second.result(timeout=3)
    assert maximum == 1 and active == 0
    assert len(starts) == 2 and starts[1] - starts[0] >= timedelta(seconds=0.02)
    assert last_start(store, "arxiv") == starts[1]


def test_separate_groups_can_enter_while_another_source_is_active(store, rate_url):
    def another_group():
        with r.shared_rate_slot(rate_url, "google-research", 0, max_wait=0.5):
            return last_start(store, "google-research")

    with r.shared_rate_slot(rate_url, "arxiv", 0), ThreadPoolExecutor(max_workers=1) as worker:
        assert worker.submit(another_group).result(timeout=2) is not None
    assert last_start(store, "arxiv") is not None


@pytest.mark.parametrize("error", [ValueError("fetch failed"), KeyboardInterrupt("cancelled")])
def test_body_exceptions_are_preserved_and_always_release_session_lock(store, rate_url, error):
    with pytest.raises(type(error)) as raised, r.shared_rate_slot(rate_url, "arxiv", 0):
        raise error
    assert raised.value is error
    first = last_start(store, "arxiv")
    with r.shared_rate_slot(rate_url, "arxiv", 0, max_wait=0.5):
        assert last_start(store, "arxiv") > first


def test_busy_group_fails_closed_without_timestamp_advance(store, rate_url):
    def competing_worker():
        with (
            pytest.raises(r.SharedRateError, match="^shared_source_rate_unavailable$"),
            r.shared_rate_slot(rate_url, "arxiv", 0, max_wait=0.05),
        ):
            pytest.fail("busy shared lock must not admit a fetch")

    with r.shared_rate_slot(rate_url, "arxiv", 0):
        before = last_start(store, "arxiv")
        with ThreadPoolExecutor(max_workers=1) as worker:
            worker.submit(competing_worker).result(timeout=2)
        assert last_start(store, "arxiv") == before
    with r.shared_rate_slot(rate_url, "arxiv", 0, max_wait=0.5):
        assert last_start(store, "arxiv") > before


def test_spacing_beyond_wait_budget_refuses_without_advancing_timestamp(store, rate_url):
    with r.shared_rate_slot(rate_url, "arxiv", 0):
        pass
    before = last_start(store, "arxiv")
    with (
        pytest.raises(r.SharedRateError, match="^shared_source_rate_unavailable$"),
        r.shared_rate_slot(rate_url, "arxiv", 60, max_wait=0.1),
    ):
        pytest.fail("a spacing wait outside the budget must refuse")
    assert last_start(store, "arxiv") == before


def test_database_statement_timeout_fails_closed_and_releases_advisory_lock(store, rate_url):
    with store.pool.connection() as blocker:
        blocker.execute("LOCK TABLE workspace_source_rate IN ACCESS EXCLUSIVE MODE")
        with (
            pytest.raises(r.SharedRateError, match="^shared_source_rate_unavailable$"),
            r.shared_rate_slot(rate_url, "arxiv", 0, max_wait=0.05),
        ):
            pytest.fail("a blocked DB statement must time out before admission")
    assert last_start(store, "arxiv") is None
    with r.shared_rate_slot(rate_url, "arxiv", 0, max_wait=0.5):
        assert last_start(store, "arxiv") is not None


@pytest.mark.parametrize(
    "changes",
    [
        {"postgres_url": ""},
        {"group": " "},
        {"group": "x" * 201},
        {"group": "source\x00name"},
        {"interval": -1},
        {"interval": float("nan")},
        {"interval": True},
        {"max_wait": 0},
        {"max_wait": 11},
        {"max_wait": float("inf")},
    ],
)
def test_invalid_bounds_refuse_before_connection(monkeypatch, changes):
    connect = Mock(side_effect=AssertionError("invalid bounds must not connect"))
    monkeypatch.setattr(r.psycopg, "connect", connect)
    arguments = {"postgres_url": "postgresql://unused/workspace", "group": "arxiv", "interval": 3.1}
    with (
        pytest.raises(r.SharedRateError, match="^shared_source_rate_unavailable$"),
        r.shared_rate_slot(**{**arguments, **changes}),
    ):
        pytest.fail("invalid shared-rate parameters must refuse")
    connect.assert_not_called()


def test_database_connection_errors_are_generic_with_bounded_connection_and_statements(monkeypatch):
    connect = Mock(side_effect=psycopg.OperationalError("private-password-and-host"))
    monkeypatch.setattr(r.psycopg, "connect", connect)
    with (
        pytest.raises(r.SharedRateError, match="^shared_source_rate_unavailable$") as raised,
        r.shared_rate_slot(
            "postgresql://user:secret@unavailable/workspace?options=-c%20search_path%3Disolated,public",
            "arxiv",
            3.1,
        ),
    ):
        pytest.fail("failed database connection must refuse")
    assert raised.value.__suppress_context__
    assert "private" not in str(raised.value) and "secret" not in str(raised.value)
    parameters = conninfo_to_dict(connect.call_args.args[0])
    assert connect.call_args.kwargs == {"autocommit": True}
    assert parameters["connect_timeout"] == "2" and parameters["tcp_user_timeout"] == "2000"
    assert "search_path=isolated,public" in parameters["options"]
    assert "statement_timeout=2000" in parameters["options"]
    assert "idle_in_transaction_session_timeout=2000" in parameters["options"]


def test_consecutive_sessions_wait_for_the_same_db_clock_interval(store, rate_url):
    with r.shared_rate_slot(rate_url, "arxiv", 0):
        before = last_start(store, "arxiv")
    with r.shared_rate_slot(rate_url, "arxiv", 0.1, max_wait=1):
        after = last_start(store, "arxiv")
    assert after - before >= timedelta(seconds=0.1)
