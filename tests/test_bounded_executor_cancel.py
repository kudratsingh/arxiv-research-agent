"""Bounded node executor + cooperative cancellation (ADR 0047).

The defect this suite pins: graph nodes are synchronous, so the async
path runs them on a thread pool, and `asyncio.wait_for` can only cancel
the *coroutine* awaiting one. Before ADR 0047 a timed-out job released
its semaphore permit while the node thread kept running — still holding
a thread, still calling Claude, still billing — so
`api_max_concurrent_jobs` bounded coroutines rather than work.

Coverage is grouped by the three moving parts:

- `CancelToken` — the signal plus the in-flight registry and the
  process-wide zombie count `/healthz` reads.
- The node wrapper in `src.graph.workflow` — executor injection,
  registration, and the pre-flight cancel check.
- `run_job` / the lifespan — permit held across the drain, permit
  released (and the zombie counted) when the drain gives up, pool
  created and joined at shutdown.

Every test here was mutation-checked against the fix: each fails on
`main`'s behaviour (or with the specific line it guards reverted), not
merely on an import error.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.api import app as app_module
from src.api.app import create_app
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.cancellation import (
    CancelToken,
    JobCancelledError,
    abandoned_node_count,
    bind_cancel_token,
    check_cancelled,
    current_cancel_token,
    reset_cancel_token,
)
from src.config import Settings
from src.graph import workflow as workflow_module
from src.observability import current_run_id

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _wait_until(
    predicate: Callable[[], bool], *, timeout: float = 5.0, what: str = "condition"
) -> None:
    """Poll `predicate` on the event loop until true, or fail the test."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"{what} never became true within {timeout}s")
        await asyncio.sleep(0.01)


async def _await_event(event: threading.Event, *, timeout: float = 5.0) -> None:
    """Wait on a threading.Event without blocking the event loop."""
    got = await asyncio.to_thread(event.wait, timeout)
    assert got, "threading event never fired"


class _ExecutorNodeStub:
    """Compiled-workflow stand-in that drives one real ADR-0047 node.

    Mirrors how Pregel drives a graph node on the async path: await the
    node callable, surface its update as a `{node: update}` chunk. Using
    the real wrapper (rather than faking the thread hop) is what makes
    the runner tests below exercise the actual registration + drain.
    """

    def __init__(self, node: Callable[[dict[str, Any]], Any]) -> None:
        self._node = node

    async def astream(
        self, state: dict[str, Any] | None, config: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"planner": await self._node(state or {})}

    async def aget_state(self, config: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(next=(), values={"draft_report": "done"})


def _cooperative_agent(
    started: threading.Event,
    observed: threading.Event,
    linger: threading.Event | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """An agent that polls its cancel token and unwinds when it is set.

    Stands in for the real thing: `src.llm.call_llm` performs exactly
    this check before every request, so a real node unwinds at its next
    LLM call. `linger` (when given) holds the thread *after* it noticed
    the cancellation, which is how a test can inspect the runner while a
    node thread is provably still in flight.

    The poll is deadline-bounded so that a regression which never sets
    the token fails on the `observed` assertion instead of spinning a
    pool thread forever and hanging the suite.
    """

    def agent(state: dict[str, Any]) -> dict[str, Any]:
        started.set()
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            try:
                check_cancelled()
            except JobCancelledError:
                break
            time.sleep(0.005)
        else:
            return {"iteration": 0}  # token never arrived — see docstring
        observed.set()
        if linger is not None:
            linger.wait(10.0)
        check_cancelled()  # real agents unwind by raising, not returning
        raise AssertionError("unreachable: token was set")  # pragma: no cover

    return agent


def _stubborn_agent(
    started: threading.Event, release: threading.Event
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """An agent that never checks its token — the zombie case."""

    def agent(state: dict[str, Any]) -> dict[str, Any]:
        started.set()
        release.wait(30.0)
        return {"iteration": 1}

    return agent


# ---------------------------------------------------------------------------
# CancelToken
# ---------------------------------------------------------------------------


class TestCancelToken:
    def test_cancel_is_idempotent_and_keeps_the_first_reason(self) -> None:
        token = CancelToken("j1")
        assert not token.is_cancelled()
        token.cancel("job_timeout")
        token.cancel("shutdown")
        assert token.is_cancelled()
        # The first cause is the true one; a later shutdown must not
        # rewrite why the job actually died.
        assert token.reason == "job_timeout"

    def test_raise_if_cancelled_names_the_job_and_the_reason(self) -> None:
        token = CancelToken("j2")
        token.raise_if_cancelled()  # no-op while unset
        token.cancel("job_timeout")
        with pytest.raises(JobCancelledError) as exc_info:
            token.raise_if_cancelled()
        assert exc_info.value.job_id == "j2"
        assert exc_info.value.reason == "job_timeout"

    def test_check_cancelled_is_a_noop_without_a_bound_token(self) -> None:
        # The CLI, the eval runner and every direct agent unit test run
        # with no token bound; the check must be invisible there.
        assert current_cancel_token() is None
        check_cancelled()

    def test_running_nodes_tracks_enter_and_exit(self) -> None:
        token = CancelToken("j3")
        assert token.running_nodes() == []
        first = token.enter_node("planner")
        second = token.enter_node("reader")
        assert token.running_nodes() == ["planner", "reader"]
        token.exit_node(first)
        assert token.running_nodes() == ["reader"]
        # Double-exit is ignored rather than corrupting the registry.
        token.exit_node(first)
        token.exit_node(second)
        assert token.running_nodes() == []

    async def test_drain_returns_empty_once_the_thread_returns(self) -> None:
        token = CancelToken("j4")
        handle = token.enter_node("planner")

        async def _finish_soon() -> None:
            await asyncio.sleep(0.05)
            token.exit_node(handle)

        asyncio.create_task(_finish_soon())
        assert await token.drain(2.0) == []

    async def test_drain_reports_what_was_still_running_at_expiry(self) -> None:
        token = CancelToken("j5")
        token.enter_node("reader")
        started = time.monotonic()
        assert await token.drain(0.1) == ["reader"]
        # The budget is a real bound, not a busy-loop that returns
        # immediately or one that waits forever.
        assert 0.09 <= time.monotonic() - started < 2.0

    async def test_abandoned_thread_stays_counted_until_it_returns(self) -> None:
        assert abandoned_node_count() == 0
        token = CancelToken("j6")
        handle = token.enter_node("reader")
        assert await token.drain(0.05) == ["reader"]
        assert token.abandon() == ["reader"]
        # The permit is gone but the thread is not: /healthz must keep
        # counting it or the worker advertises capacity it lacks.
        assert abandoned_node_count() == 1
        token.exit_node(handle)
        assert abandoned_node_count() == 0

    def test_abandon_with_nothing_running_reports_no_zombie(self) -> None:
        # The thread returned between the drain giving up and `abandon`.
        # There is no zombie to report and nothing to count.
        assert abandoned_node_count() == 0
        token = CancelToken("j7")
        assert token.abandon() == []
        assert abandoned_node_count() == 0

    def test_node_entering_after_abandon_stays_balanced(self) -> None:
        assert abandoned_node_count() == 0
        token = CancelToken("j8")
        token.abandon()
        handle = token.enter_node("critic")
        assert abandoned_node_count() == 1
        token.exit_node(handle)
        assert abandoned_node_count() == 0


# ---------------------------------------------------------------------------
# The node wrapper
# ---------------------------------------------------------------------------


class TestExecutorNode:
    async def test_agent_runs_on_the_supplied_pool(self) -> None:
        """The point of the wrapper: nodes land on *our* executor.

        LangGraph's own coercion hard-codes `run_in_executor(None, ...)`,
        i.e. the loop's default pool, which is sized independently of
        `api_max_concurrent_jobs`. A thread named after our prefix is
        the proof that the injection took.
        """
        seen: dict[str, str] = {}

        def agent(state: dict[str, Any]) -> dict[str, Any]:
            seen["thread"] = threading.current_thread().name
            return {"iteration": 1}

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="adr47-pool")
        try:
            node = workflow_module._executor_wrapper(executor)("planner", agent)
            assert await node({}) == {"iteration": 1}
            assert seen["thread"].startswith("adr47-pool")
        finally:
            executor.shutdown(wait=True)

    async def test_running_node_is_registered_on_the_token(self) -> None:
        token = CancelToken("wrap-1")
        scope = bind_cancel_token(token)
        inside = threading.Event()
        release = threading.Event()

        def agent(state: dict[str, Any]) -> dict[str, Any]:
            inside.set()
            release.wait(5.0)
            return {}

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            node = workflow_module._executor_wrapper(executor)("reader", agent)
            task = asyncio.create_task(node({}))
            await _await_event(inside)
            # This registration is what lets the runner tell "coroutine
            # cancelled" apart from "thread returned".
            assert token.running_nodes() == ["reader"]
            release.set()
            await asyncio.wait_for(task, timeout=5)
            assert token.running_nodes() == []
        finally:
            release.set()
            executor.shutdown(wait=True)
            reset_cancel_token(scope)

    async def test_cancelled_job_never_occupies_a_pool_slot(self) -> None:
        token = CancelToken("wrap-2")
        token.cancel("job_timeout")
        scope = bind_cancel_token(token)
        calls: list[str] = []

        def agent(state: dict[str, Any]) -> dict[str, Any]:
            calls.append("ran")  # pragma: no cover - must not happen
            return {}

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            node = workflow_module._executor_wrapper(executor)("planner", agent)
            with pytest.raises(JobCancelledError):
                await node({})
            assert calls == []
        finally:
            executor.shutdown(wait=True)
            reset_cancel_token(scope)

    async def test_run_context_reaches_the_node_thread(self) -> None:
        """run_id, cost accumulator and cancel token all ride along.

        `run_in_executor` only copies contextvars on its *default*
        executor branch — with an explicit pool the wrapper has to copy
        the context itself, or every node thread loses its run
        attribution and its ability to see a cancellation.
        """
        from src.observability import bind_run_id, reset_run_id

        token = CancelToken("wrap-3")
        scope = bind_cancel_token(token)
        run_scope = bind_run_id("run-abc")
        seen: dict[str, Any] = {}

        def agent(state: dict[str, Any]) -> dict[str, Any]:
            seen["run_id"] = current_run_id()
            seen["token"] = current_cancel_token()
            return {}

        executor = ThreadPoolExecutor(max_workers=1)
        try:
            node = workflow_module._executor_wrapper(executor)("critic", agent)
            await node({})
            assert seen["run_id"] == "run-abc"
            assert seen["token"] is token
        finally:
            executor.shutdown(wait=True)
            reset_run_id(run_scope)
            reset_cancel_token(scope)

    async def test_node_without_a_token_still_runs(self) -> None:
        # Programmatic callers (and the smoke test's stub graphs) build
        # an async workflow with no job behind it.
        assert current_cancel_token() is None
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            node = workflow_module._executor_wrapper(executor)(
                "planner", lambda state: {"iteration": 7}
            )
            assert await node({}) == {"iteration": 7}
        finally:
            executor.shutdown(wait=True)

    def test_sync_build_refuses_a_node_executor(self) -> None:
        """The sync `invoke` path calls nodes inline; an executor there
        would be silently ignored, so it fails loudly instead."""
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            with pytest.raises(ValueError, match="async build only"):
                workflow_module.build_workflow(node_executor=executor)
        finally:
            executor.shutdown(wait=True)


# ---------------------------------------------------------------------------
# run_job: cancel + drain
# ---------------------------------------------------------------------------


def _drain_queue(job: Job) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while not job.event_queue.empty():
        frames.append(job.event_queue.get_nowait())
    return frames


class TestRunnerDrain:
    async def test_timeout_cancels_the_token_and_the_node_unwinds(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The headline: a timed-out job's node thread actually stops.

        Pre-ADR-0047 nothing ever set a token, so the node ran to
        completion (or forever) after the job was already failed.
        """
        import src.api.runner as runner_module

        monkeypatch.setattr(
            runner_module, "settings", Settings(api_job_drain_timeout_sec=10)
        )
        started, observed = threading.Event(), threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)
        job = Job(job_id="cancel-me", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        try:
            node = workflow_module._executor_wrapper(executor)(
                "planner", _cooperative_agent(started, observed)
            )
            with caplog.at_level(logging.INFO, logger="src.api.runner"):
                await asyncio.wait_for(
                    run_job(
                        job,
                        _ExecutorNodeStub(node),
                        store,
                        asyncio.Semaphore(1),
                        timeout_sec=1,
                    ),
                    timeout=20,
                )
        finally:
            executor.shutdown(wait=True)

        assert started.is_set()
        assert observed.is_set(), "node never saw its cancel token"
        assert job.status == JobStatus.failed
        assert job.error_type == "timeout"
        # Drain completed: no thread was left behind, nothing counted.
        assert abandoned_node_count() == 0
        messages = [r.message for r in caplog.records]
        assert "api_job_node_drain_completed" in messages
        assert "api_job_node_drain_expired" not in messages

    async def test_permit_is_held_until_the_node_thread_returns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The property the audit said a partial fix would fake.

        The job is terminal for its client the moment the timeout
        fires — but the concurrency permit stays held while the node
        thread is still executing, so a second submit queues instead of
        overcommitting the worker.
        """
        import src.api.runner as runner_module

        monkeypatch.setattr(
            runner_module, "settings", Settings(api_job_drain_timeout_sec=20)
        )
        started, observed, linger = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        executor = ThreadPoolExecutor(max_workers=1)
        job = Job(job_id="hold-permit", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)
        semaphore = asyncio.Semaphore(1)
        second_started = asyncio.Event()

        async def _second_submit() -> None:
            async with semaphore:
                second_started.set()

        node = workflow_module._executor_wrapper(executor)(
            "planner", _cooperative_agent(started, observed, linger)
        )
        runner = asyncio.create_task(
            run_job(
                job,
                _ExecutorNodeStub(node),
                store,
                semaphore,
                timeout_sec=1,
            )
        )
        queued = asyncio.create_task(_second_submit())
        try:
            await _await_event(started, timeout=10)
            await _await_event(observed, timeout=10)
            await _wait_until(
                lambda: job.status == JobStatus.failed, what="job marked failed"
            )

            # Client-visible outcome is already final...
            assert job.completed_at is not None
            # ...while the node thread is provably still in the pool.
            assert semaphore.locked()
            assert not second_started.is_set(), (
                "permit was released while the node thread was still running"
            )

            linger.set()
            await asyncio.wait_for(runner, timeout=20)
            # Only now does the queued job get its turn.
            await asyncio.wait_for(second_started.wait(), timeout=5)
            assert abandoned_node_count() == 0
        finally:
            linger.set()
            queued.cancel()
            executor.shutdown(wait=True)

    async def test_drain_expiry_logs_the_zombie_and_keeps_counting_it(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A node that ignores its token cannot hold the worker forever.

        The permit goes back after the bounded drain — but the thread is
        still out there, so it stays in the process-wide abandoned count
        (and therefore in `/healthz`'s `active_jobs`) until it returns.
        """
        import src.api.runner as runner_module

        monkeypatch.setattr(
            runner_module, "settings", Settings(api_job_drain_timeout_sec=1)
        )
        started, release = threading.Event(), threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)
        job = Job(job_id="zombie", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)
        semaphore = asyncio.Semaphore(1)
        assert abandoned_node_count() == 0

        try:
            node = workflow_module._executor_wrapper(executor)(
                "reader", _stubborn_agent(started, release)
            )
            with caplog.at_level(logging.WARNING, logger="src.api.runner"):
                await asyncio.wait_for(
                    run_job(
                        job,
                        _ExecutorNodeStub(node),
                        store,
                        semaphore,
                        timeout_sec=1,
                    ),
                    timeout=30,
                )

            assert started.is_set()
            # Permit released: one wedged node must not wedge the worker.
            assert not semaphore.locked()
            # But the accounting stays honest about it.
            assert abandoned_node_count() == 1
            expired = [
                r for r in caplog.records if r.message == "api_job_node_drain_expired"
            ]
            assert len(expired) == 1
            assert expired[0].levelno == logging.WARNING
            assert expired[0].nodes == ["reader"]  # type: ignore[attr-defined]
            assert expired[0].job_id == "zombie"  # type: ignore[attr-defined]

            release.set()
            await _wait_until(
                lambda: abandoned_node_count() == 0,
                what="zombie count settling back to zero",
            )
        finally:
            release.set()
            executor.shutdown(wait=True)

    async def test_shutdown_cancellation_also_drains_the_node_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancelling the job task at SIGTERM unwinds the node too.

        Under a shorter ceiling than the timeout path
        (`SHUTDOWN_DRAIN_SEC`), because here the wait competes with
        uvicorn's own graceful drain inside the container's grace
        period. Without it the lifespan's pool join would be the first
        thing to notice the thread — with nothing left to wait on.
        """
        import src.api.runner as runner_module

        monkeypatch.setattr(
            runner_module, "settings", Settings(api_job_drain_timeout_sec=30)
        )
        # The configured budget is 30s; the shutdown path must clamp it.
        assert runner_module.SHUTDOWN_DRAIN_SEC <= 10.0
        started, observed = threading.Event(), threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)
        job = Job(job_id="sigterm", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        node = workflow_module._executor_wrapper(executor)(
            "planner", _cooperative_agent(started, observed)
        )
        task = asyncio.create_task(
            run_job(job, _ExecutorNodeStub(node), store, asyncio.Semaphore(1))
        )
        try:
            await _await_event(started, timeout=10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=20)
            assert observed.is_set(), "node never saw the shutdown token"
            assert job.status == JobStatus.cancelled
            assert abandoned_node_count() == 0
        finally:
            executor.shutdown(wait=True)

    async def test_timeout_contract_is_unchanged_by_the_drain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status, error_type and the terminal frame stay exactly what
        ADR 0025 promised — the drain is invisible to clients."""
        import src.api.runner as runner_module

        monkeypatch.setattr(
            runner_module, "settings", Settings(api_job_drain_timeout_sec=10)
        )
        started, observed = threading.Event(), threading.Event()
        executor = ThreadPoolExecutor(max_workers=1)
        job = Job(job_id="contract", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        try:
            node = workflow_module._executor_wrapper(executor)(
                "planner", _cooperative_agent(started, observed)
            )
            await asyncio.wait_for(
                run_job(
                    job,
                    _ExecutorNodeStub(node),
                    store,
                    asyncio.Semaphore(1),
                    timeout_sec=1,
                ),
                timeout=20,
            )
        finally:
            executor.shutdown(wait=True)

        assert job.status == JobStatus.failed
        assert job.error == "Workflow exceeded 1s timeout"
        assert job.error_type == "timeout"
        stored = await store.get("contract")
        assert stored is not None and stored.status == JobStatus.failed

        frames = _drain_queue(job)
        assert [f["event"] for f in frames] == ["job_started", "job_failed"]
        terminal = frames[-1]["data"]
        assert set(terminal) == {"job_id", "error", "error_type", "elapsed_sec"}
        assert terminal["error_type"] == "timeout"


# ---------------------------------------------------------------------------
# Lifespan wiring + /healthz accounting
# ---------------------------------------------------------------------------


class TestLifespanWiring:
    async def test_pool_is_sized_to_the_job_ceiling_and_shut_down(self) -> None:
        app = create_app(
            build_workflow=lambda: MagicMock(name="wf"),
            store=InMemoryJobStore(),
            max_concurrent_jobs=3,
        )
        async with LifespanManager(app):
            executor = app.state.node_executor
            assert isinstance(executor, ThreadPoolExecutor)
            # Sizing the pool to the semaphore is what makes the
            # semaphore a bound on threads rather than on coroutines.
            assert executor._max_workers == 3
        # Shutdown really happened: the pool refuses new work, so a
        # leaked reference cannot keep spawning threads post-shutdown.
        with pytest.raises(RuntimeError):
            executor.submit(lambda: None)

    async def test_default_factory_hands_the_pool_to_the_graph_builder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without this the pool exists but the graph never uses it —
        nodes would still land on the loop's default executor."""
        captured: dict[str, Any] = {}

        def _fake_build(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock(name="compiled")

        monkeypatch.setattr(app_module, "default_build_workflow", _fake_build)
        app = create_app(store=InMemoryJobStore())
        async with LifespanManager(app):
            assert captured["async_checkpointer"] is True
            assert captured["node_executor"] is app.state.node_executor

    async def test_healthz_counts_abandoned_threads_as_active(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A zombie thread still occupies the worker; `/healthz` says so."""
        import src.api.routes as routes_module

        monkeypatch.setattr(routes_module, "abandoned_node_count", lambda: 2)
        app = create_app(
            build_workflow=lambda: MagicMock(name="wf"),
            store=InMemoryJobStore(),
            max_concurrent_jobs=4,
        )
        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = (await client.get("/healthz")).json()
        # No job tasks in flight, so the whole count is zombies.
        assert body["active_jobs"] == 2
        assert body["abandoned_node_threads"] == 2
        assert body["max_concurrent_jobs"] == 4


# ---------------------------------------------------------------------------
# Call-site checks: LLM + reader fan-out
# ---------------------------------------------------------------------------


class TestCallSites:
    def test_call_llm_aborts_before_touching_the_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The check that actually stops the spend on a dead job."""
        from src import llm as llm_module

        def _boom() -> Any:
            raise AssertionError(
                "cancelled job must not reach the Anthropic client"
            )

        monkeypatch.setattr(llm_module, "_get_client", _boom)
        token = CancelToken("llm-job")
        token.cancel("job_timeout")
        scope = bind_cancel_token(token)
        try:
            with pytest.raises(JobCancelledError) as exc_info:
                llm_module.call_llm("prompt")
            assert exc_info.value.reason == "job_timeout"
        finally:
            reset_cancel_token(scope)

    def test_reader_fan_out_stops_at_the_next_paper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One LLM call per paper: the reader is the node that most
        needs to notice a cancellation mid-flight. With one worker the
        papers are analysed in order, so paper 2 is the first to see
        the token the runner set while paper 1 was in flight."""
        from src.agents import reader as reader_module

        monkeypatch.setattr(
            reader_module, "settings", Settings(reader_max_workers=1)
        )
        token = CancelToken("reader-job")
        scope = bind_cancel_token(token)
        analysed: list[str] = []

        def _fake_analyze(
            paper: dict[str, Any],
            query: str,
            subquestions: list[str],
            preferred: list[str] | None = None,
        ) -> Any:
            analysed.append(paper["id"])
            # The runner times out while the first paper is in flight.
            token.cancel("job_timeout")
            return (
                reader_module._failed_analysis(paper),
                [],
                reader_module._default_signal(),
            )

        monkeypatch.setattr(reader_module, "_analyze_paper", _fake_analyze)
        papers = [
            {"id": f"p{i}", "title": f"t{i}", "abstract": "", "pdf_url": ""}
            for i in range(1, 4)
        ]
        state = {"papers": papers, "query": "q", "sub_questions": []}

        try:
            with pytest.raises(JobCancelledError):
                reader_module.reader_agent(state)  # type: ignore[arg-type]
        finally:
            reset_cancel_token(scope)

        # Papers 2 and 3 were never attempted — and they were not
        # silently degraded to placeholders either, which is what
        # swallowing the error inside the per-paper guard would do.
        assert analysed == ["p1"]
