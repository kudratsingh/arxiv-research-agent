"""`/healthz` logs dependency *edges*, not the steady state (ADR 0053).

The endpoint already reported a dead Redis in its response body and
wrote nothing at all to the log, so an outage left no trace in the
stream an operator greps after the fact — the only witness was
whatever happened to be scraping the endpoint. Logging every probe
would be the opposite failure: compose polls every 15s, so a
weekend-long outage would bury the timeline in ~17k identical lines.

So: one WARNING on the way down, one INFO on the way back, naming the
dependency. These tests pin both halves — the line that must appear
and the 999 that must not.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from src.api.routes import _log_health_transitions, healthz

pytestmark = pytest.mark.unit

DEGRADED_EVENT = "api_health_dependency_degraded"
RECOVERED_EVENT = "api_health_dependency_recovered"


def _events(caplog: pytest.LogCaptureFixture) -> list[tuple[str, int]]:
    """(event name, level) for the health records only."""
    return [
        (r.getMessage(), r.levelno)
        for r in caplog.records
        if r.getMessage() in {DEGRADED_EVENT, RECOVERED_EVENT}
    ]


class TestTransitionHelper:
    """`_log_health_transitions` in isolation — one probe at a time."""

    def test_first_failure_warns_once_naming_the_dependency(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        known: set[str] = set()
        with caplog.at_level(logging.INFO):
            _log_health_transitions(
                {"redis": "error: ConnectionError"}, known
            )

        assert _events(caplog) == [(DEGRADED_EVENT, logging.WARNING)]
        record = caplog.records[-1]
        assert record.dependency == "redis"  # type: ignore[attr-defined]
        assert (
            record.dependency_status  # type: ignore[attr-defined]
            == "error: ConnectionError"
        )
        assert known == {"redis"}

    def test_a_continuing_outage_is_silent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The compose healthcheck probes every 15s. One line per probe
        # would be ~5,700 lines a day for a single dead dependency.
        known: set[str] = set()
        with caplog.at_level(logging.INFO):
            for _ in range(50):
                _log_health_transitions(
                    {"redis": "error: ConnectionError"}, known
                )

        assert _events(caplog) == [(DEGRADED_EVENT, logging.WARNING)]

    def test_recovery_logs_once_and_re_arms(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        known: set[str] = set()
        with caplog.at_level(logging.INFO):
            _log_health_transitions({"redis": "error: TimeoutError"}, known)
            _log_health_transitions({"redis": "ok"}, known)
            _log_health_transitions({"redis": "ok"}, known)
            # A flapping dependency must warn again on the next dip,
            # or only the first outage of a process's life is visible.
            _log_health_transitions({"redis": "error: TimeoutError"}, known)

        assert _events(caplog) == [
            (DEGRADED_EVENT, logging.WARNING),
            (RECOVERED_EVENT, logging.INFO),
            (DEGRADED_EVENT, logging.WARNING),
        ]

    def test_each_dependency_is_tracked_separately(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        known: set[str] = set()
        with caplog.at_level(logging.INFO):
            _log_health_transitions(
                {"redis": "error: ConnectionError", "postgres": "ok"}, known
            )
            _log_health_transitions(
                {"redis": "error: ConnectionError", "postgres": "error: OpError"},
                known,
            )

        named = [
            r.dependency  # type: ignore[attr-defined]
            for r in caplog.records
            if r.getMessage() == DEGRADED_EVENT
        ]
        assert named == ["redis", "postgres"]
        assert known == {"redis", "postgres"}

    def test_a_dependency_that_stops_being_probed_is_unlatched(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # `postgres_url` cleared between probes: the dependency leaves
        # the payload entirely. Leaving it latched would mean its
        # eventual return logs a recovery for an edge nobody ever saw.
        known: set[str] = set()
        with caplog.at_level(logging.INFO):
            _log_health_transitions({"postgres": "error: OpError"}, known)
            _log_health_transitions({}, known)

        assert known == set()
        assert _events(caplog) == [(DEGRADED_EVENT, logging.WARNING)]

    def test_no_credentials_reach_the_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The probes deliberately report `type(exc).__name__` and not
        # the message (ADR 0042): a redis-py connection error's text
        # tends to carry the URL, and `redis_url` embeds the password.
        known: set[str] = set()
        with caplog.at_level(logging.INFO):
            _log_health_transitions(
                {"redis": "error: ConnectionError"}, known
            )

        blob = " ".join(
            f"{r.getMessage()} {getattr(r, 'dependency_status', '')}"
            for r in caplog.records
        )
        assert "://" not in blob
        assert "password" not in blob


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


class _PingStore:
    """A store whose Redis ping the test controls."""

    def __init__(self) -> None:
        self.healthy = True
        self._client = SimpleNamespace(ping=self._ping)

    async def _ping(self) -> bool:
        if not self.healthy:
            raise ConnectionError("redis://user:secret@host:6379 refused")
        return True


def _request(store: _PingStore, app_state: SimpleNamespace) -> Request:
    async def receive() -> dict[str, Any]:  # pragma: no cover - never polled
        return {"type": "http.request"}

    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/healthz",
        "headers": [],
        "query_string": b"",
        "app": SimpleNamespace(state=app_state),
    }
    return Request(scope, receive)


def _state(store: _PingStore) -> SimpleNamespace:
    return SimpleNamespace(
        store=store,
        workflow=None,
        semaphore=None,
        max_concurrent_jobs=4,
        tasks=set(),
        conversation_store=None,
        degraded_dependencies=set(),
    )


class TestHealthzWiring:
    async def test_probe_logs_the_edge_and_reports_it_in_the_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        store = _PingStore()
        state = _state(store)
        with caplog.at_level(logging.INFO):
            ok = await healthz(_request(store, state))
            store.healthy = False
            bad = await healthz(_request(store, state))
            again = await healthz(_request(store, state))

        assert ok.status == "ok"
        # The body half is ADR 0042's and must not have changed.
        assert bad.status == "degraded"
        assert bad.dependencies["redis"].startswith("error:")
        assert again.status == "degraded"
        # One line for three probes, and it names the dependency.
        assert _events(caplog) == [(DEGRADED_EVENT, logging.WARNING)]
        assert caplog.records[-1].dependency == "redis"  # type: ignore[attr-defined]

    async def test_state_is_per_app_not_module_global(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Two apps in one test process (or one ASGI mount inside
        # another) must not latch each other's edges — the second app
        # would then never report its own outage.
        store_a, store_b = _PingStore(), _PingStore()
        store_a.healthy = store_b.healthy = False
        with caplog.at_level(logging.INFO):
            await healthz(_request(store_a, _state(store_a)))
            await healthz(_request(store_b, _state(store_b)))

        assert _events(caplog) == [
            (DEGRADED_EVENT, logging.WARNING),
            (DEGRADED_EVENT, logging.WARNING),
        ]

    async def test_works_on_an_app_assembled_without_the_lifespan(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # `/healthz` is the endpoint most likely to be called against a
        # bare `TestClient(app)` with no lifespan run. It must log the
        # edge rather than raise `AttributeError` at the caller.
        store = _PingStore()
        store.healthy = False
        bare = SimpleNamespace(
            store=store,
            workflow=None,
            semaphore=None,
            max_concurrent_jobs=1,
            tasks=set(),
            conversation_store=None,
        )
        with caplog.at_level(logging.INFO):
            first = await healthz(_request(store, bare))
            second = await healthz(_request(store, bare))

        assert first.status == "degraded"
        assert second.status == "degraded"
        # Still edges-only: the set created on first use is stored back
        # on the app state, so probe two is silent.
        assert _events(caplog) == [(DEGRADED_EVENT, logging.WARNING)]
