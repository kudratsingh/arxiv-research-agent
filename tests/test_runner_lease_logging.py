"""Diagnostics on the job-lease path (ADR 0051).

The lease is the liveness proof `src.api.redriver` checks before
reclaiming a non-terminal job as orphaned (ADR 0038), so when it
misbehaves the blast radius is other workers' healthy jobs. An audit
found its logging unable to support that investigation on two counts:

  - every `except Exception` around acquire / refresh logged a bare
    event name — no exception type, no message, no traceback — so
    "Redis refused the connection" and "WRONGTYPE on the lease key"
    were the same line;
  - every record the lease keeper emitted carried `run_id="-"`, because
    `asyncio.create_task` snapshots the context at creation and
    `run_job` binds the run_id *after* `_job_lease.__aenter__` has
    already spawned the task.

Both are diagnostics rather than behaviour, so these tests assert on
what reaches a handler: the event, its level, whether it carries
`exc_info`, and the run_id in scope at emission time. The run_id is
resolved by `JsonFormatter` from a ContextVar rather than stored on the
record, so it has to be sampled during `emit`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from src.api import runner as runner_module
from src.api.runner import _job_lease, _log_lease_failure, _refresh_lease_forever
from src.observability import current_run_id

pytestmark = pytest.mark.unit

JOB_ID = "job-lease-1"
WORKER_ID = "worker-a"


class _Captured:
    """One log record, plus the run_id that was bound when it fired."""

    def __init__(self, record: logging.LogRecord) -> None:
        self.event = record.getMessage()
        self.level = record.levelno
        self.has_traceback = record.exc_info is not None
        self.run_id = current_run_id()
        self.consecutive = getattr(record, "consecutive", None)
        self.job_id = getattr(record, "job_id", None)


class _RunIdCapturingHandler(logging.Handler):
    """Sample `current_run_id()` at emit time, like `JsonFormatter` does."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.captured: list[_Captured] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.captured.append(_Captured(record))

    def events(self, name: str) -> list[_Captured]:
        return [c for c in self.captured if c.event == name]


@pytest.fixture
def caught() -> Any:
    """Attach a capturing handler to the runner's logger."""
    handler = _RunIdCapturingHandler()
    logger = logging.getLogger("src.api.runner")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


class _LeaseSettings:
    """Minimal stand-in for the two lease knobs the keeper reads."""

    def __init__(self, refresh_sec: int = 0, ttl_sec: int = 60) -> None:
        self.job_lease_refresh_sec = refresh_sec
        self.job_lease_ttl_sec = ttl_sec


class TestLeaseFailureLogging:
    """First failure of a streak carries the traceback; repeats do not.

    A Redis outage produces one of these per job per refresh tick. An
    unconditional stack trace turns a dependency blip into a log flood
    that buries what an operator is looking for, so the volume control
    is part of the fix, not a hedge against it.
    """

    def test_first_failure_warns_with_a_traceback(
        self, caught: _RunIdCapturingHandler
    ) -> None:
        try:
            raise ConnectionError("redis refused")
        except ConnectionError:
            _log_lease_failure(
                "job_lease_refresh_error",
                job_id=JOB_ID,
                worker_id=WORKER_ID,
                consecutive=1,
            )

        (record,) = caught.events("job_lease_refresh_error")
        assert record.level == logging.WARNING
        assert record.has_traceback
        assert record.consecutive == 1

    def test_repeats_drop_to_debug_but_keep_the_count(
        self, caught: _RunIdCapturingHandler
    ) -> None:
        try:
            raise ConnectionError("redis still refused")
        except ConnectionError:
            _log_lease_failure(
                "job_lease_refresh_error",
                job_id=JOB_ID,
                worker_id=WORKER_ID,
                consecutive=7,
            )

        (record,) = caught.events("job_lease_refresh_error")
        assert record.level == logging.DEBUG
        assert record.consecutive == 7
        # Still carries the traceback — demoting the level must not
        # also throw away the detail, or DEBUG buys nothing.
        assert record.has_traceback


class TestLeaseKeeperContext:
    async def test_keeper_lines_carry_the_run_id(
        self, caught: _RunIdCapturingHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mutation-check: drop the `bind_run_id(job_id)` from
        `_refresh_lease_forever` and every run_id below reads `-`."""
        monkeypatch.setattr(runner_module, "settings", _LeaseSettings())

        calls = {"n": 0}

        async def refresh(job_id: str, worker_id: str, ttl: int) -> bool:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("redis blip")
            # Second tick: the lease is gone, so the keeper stops.
            return False

        await asyncio.create_task(
            _refresh_lease_forever(refresh, JOB_ID, WORKER_ID)
        )

        errors = caught.events("job_lease_refresh_error")
        lost = caught.events("job_lease_lost")
        assert len(errors) == 1
        assert len(lost) == 1
        assert [c.run_id for c in errors + lost] == [JOB_ID, JOB_ID]

    async def test_keeper_bind_does_not_leak_to_the_caller(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A task's context is its own copy; the reset in `finally` is
        belt-and-braces for the inline-await case."""
        monkeypatch.setattr(runner_module, "settings", _LeaseSettings())

        async def refresh(job_id: str, worker_id: str, ttl: int) -> bool:
            return False

        assert current_run_id() == "-"
        await asyncio.create_task(
            _refresh_lease_forever(refresh, JOB_ID, WORKER_ID)
        )
        assert current_run_id() == "-"

    async def test_streak_counter_resets_after_a_good_tick(
        self, caught: _RunIdCapturingHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second outage must warn again rather than hide behind the
        first — otherwise the volume control silences the signal."""
        monkeypatch.setattr(runner_module, "settings", _LeaseSettings())

        script = [ConnectionError("blip 1"), True, ConnectionError("blip 2"), False]

        async def refresh(job_id: str, worker_id: str, ttl: int) -> bool:
            step = script.pop(0)
            if isinstance(step, Exception):
                raise step
            return step

        await asyncio.create_task(
            _refresh_lease_forever(refresh, JOB_ID, WORKER_ID)
        )

        levels = [c.level for c in caught.events("job_lease_refresh_error")]
        assert levels == [logging.WARNING, logging.WARNING]


class _StubStore:
    """Duck-typed lease surface: `_job_lease` detects it by attribute."""

    def __init__(self, *, acquire_result: Any) -> None:
        self._acquire_result = acquire_result
        self.released: list[str] = []

    async def acquire_lease(self, job_id: str, worker_id: str, ttl: int) -> bool:
        if isinstance(self._acquire_result, Exception):
            raise self._acquire_result
        return bool(self._acquire_result)

    async def refresh_lease(self, job_id: str, worker_id: str, ttl: int) -> bool:
        return True

    async def release_lease(self, job_id: str, worker_id: str) -> None:
        self.released.append(job_id)


class TestJobLeaseAcquireLogging:
    async def test_acquire_error_carries_detail_and_run_id(
        self, caught: _RunIdCapturingHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """"The acquire raised" without saying what it raised cannot
        tell a connection refusal from a WRONGTYPE on the lease key."""
        # A long refresh interval so the keeper never ticks inside the
        # test; the context manager cancels it on exit.
        monkeypatch.setattr(
            runner_module, "settings", _LeaseSettings(refresh_sec=3600)
        )
        store = _StubStore(acquire_result=ConnectionError("redis down"))

        async with _job_lease(store, JOB_ID, WORKER_ID):
            pass

        (record,) = caught.events("job_lease_acquire_error")
        assert record.has_traceback
        assert record.run_id == JOB_ID
        assert record.job_id == JOB_ID

    async def test_contended_lease_is_logged_with_the_run_id(
        self, caught: _RunIdCapturingHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module, "settings", _LeaseSettings(refresh_sec=3600)
        )
        store = _StubStore(acquire_result=False)

        async with _job_lease(store, JOB_ID, WORKER_ID):
            pass

        (record,) = caught.events("job_lease_contended")
        assert record.run_id == JOB_ID
        # Contended means someone else rightfully holds the key, so we
        # neither keep retrying nor release it out from under them.
        assert store.released == []

    async def test_contended_lease_does_not_leak_the_run_id_binding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module, "settings", _LeaseSettings(refresh_sec=3600)
        )
        store = _StubStore(acquire_result=False)

        async with _job_lease(store, JOB_ID, WORKER_ID):
            # `run_job` does its own `bind_run_id` in here; the lease's
            # scoped bind must already be unwound so that one owns the
            # scope.
            assert current_run_id() == "-"

    async def test_held_lease_is_released_on_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module, "settings", _LeaseSettings(refresh_sec=3600)
        )
        store = _StubStore(acquire_result=True)

        async with _job_lease(store, JOB_ID, WORKER_ID):
            pass

        assert store.released == [JOB_ID]
