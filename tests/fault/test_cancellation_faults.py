"""Cancellation lands between nodes and inside one (WO-A06 scenario 4).

LangGraph nodes are synchronous functions handed to a thread pool, and
threads cannot be killed from outside in CPython. Cancellation is
therefore cooperative: a token the runner sets, and two checkpoints
that read it — `_run_node_body` before a node is allowed to start, and
`call_llm` before a request is allowed to leave. This file drives both
through the real checkpoints rather than through stand-ins, because a
cancellation test that stubs the checkpoint is a test of the stub.

| moment | code | event | metric |
|---|---|---|---|
| between nodes | `cancelled_job` | `api_job_failed` | `research_jobs_total{status="failed", error_type="cancelled_job"}` |
| inside a node | `cancelled_job` | `api_job_failed` | same, plus `llm_calls_total` **records nothing** |
| shutdown | *(none)* | `api_job_cancelled` | `research_jobs_total{status="cancelled", error_type="none"}` |

Two asymmetries in that table are deliberate and both are asserted.

A `JobCancelledError` that escapes a node lands the job `failed`, not
`cancelled`: `run_job` has no `except JobCancelledError`, so it falls
to the generic handler and `_as_app_error` maps it to `cancelled_job`.
Shutdown is the other path — `asyncio.CancelledError` has its own
branch, lands `cancelled`, and writes no `error_type` at all, so the
metric attribute is the literal `none`. A run stopped by an operator
and a run stopped by a fault are different facts, and the two
terminal statuses are how a dashboard tells them apart.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from src import llm as llm_module
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.cancellation import (
    CancelToken,
    JobCancelledError,
    bind_cancel_token,
    current_cancel_token,
    reset_cancel_token,
)
from src.config import Settings
from src.errors import JOB_ERROR_TYPES, JobCancelled
from src.graph.workflow import _run_node_body

from .conftest import ScriptedWorkflow, TripleObserver

pytestmark = [pytest.mark.unit, pytest.mark.fault]


async def _run(job_id: str, workflow: Any) -> tuple[Job, InMemoryJobStore]:
    job = Job(job_id=job_id, query="q", hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)
    await run_job(job, workflow, store, asyncio.Semaphore(1))
    return job, store


class TestCancellationBetweenNodes:
    async def test_the_next_node_never_runs_and_the_job_says_why(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
    ) -> None:
        """Driven through `_run_node_body`, the real dispatch wrapper.

        The queued-behind-a-slow-pool case: the token was set while
        this node sat in the executor's queue, so running it would
        spend against a job that is already over. The wrapper
        registers the thread *before* it checks, which is what makes
        the two outcomes exhaustive — either the drain sees the thread
        or the check sees the token — and it is why the check has to be
        exercised where it lives.
        """
        executed: list[str] = []

        def _node(state: Any) -> dict[str, Any]:  # pragma: no cover - must not run
            executed.append("reader")
            return {}

        token = CancelToken("cancelled-between")
        token.cancel("job_timeout")

        def _dispatch_the_next_node() -> None:
            _run_node_body("reader", _node, {}, token)

        job, _ = await _run(
            "cancelled-between", scripted_workflow(on_stream=_dispatch_the_next_node)
        )

        assert executed == [], "a cancelled job must not start another node"
        assert job.status == JobStatus.failed
        assert job.error_type == JobCancelled.code
        assert job.error_type in JOB_ERROR_TYPES

        triple.assert_triple(
            code=job.error_type,
            event="api_job_failed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": JobCancelled.code},
        )

    async def test_the_abort_is_attributable_rather_than_anonymous(self) -> None:
        """The token carries the job and the reason it was set.

        Without them a cancelled node's traceback is indistinguishable
        from a spontaneous agent failure, and the runner's own drain
        logs would be the only place the cause survived.
        """
        token = CancelToken("attributable")
        token.cancel("shutdown")

        with pytest.raises(JobCancelledError) as raised:
            _run_node_body("reader", lambda _state: {}, {}, token)

        assert raised.value.job_id == "attributable"
        assert raised.value.reason == "shutdown"


class TestCancellationInsideANode:
    async def test_a_cancelled_job_stops_spending_before_the_request_leaves(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`call_llm` checks the token first, before anything costs money.

        The ordering inside `call_llm` is load-bearing and is asserted
        here by its consequences: the cancel check runs before the
        budget check and before `_get_client`, so a cancelled job on a
        cold process does not even construct a client. If the check
        moved below the call, this test would see an `llm_calls_total`
        point — which is exactly the accounting a cancelled job must
        not produce.
        """

        def _must_not_be_called() -> Any:  # pragma: no cover - the point of the test
            raise AssertionError("a cancelled job constructed an LLM client")

        monkeypatch.setattr(llm_module, "_get_client", _must_not_be_called)

        def _cancel_then_call() -> None:
            token = current_cancel_token()
            assert token is not None, "run_job must bind a cancel token"
            token.cancel("job_timeout")
            llm_module.call_llm("prompt", model_name="claude-sonnet-4-6")

        job, _ = await _run(
            "cancelled-inside", scripted_workflow(on_stream=_cancel_then_call)
        )

        assert job.status == JobStatus.failed
        assert job.error_type == JobCancelled.code
        assert job.cost_usd == pytest.approx(0.0)
        assert job.llm_calls == 0

        triple.assert_triple(
            code=job.error_type,
            event="api_job_failed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": JobCancelled.code},
        )
        # The negative half: no call, so no call metric and no spend metric.
        triple.assert_not_recorded("llm_calls_total")
        triple.assert_not_recorded("llm_cost_usd_total")

    async def test_the_cancel_check_outranks_the_cost_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An abandoned job's remaining budget is irrelevant.

        Both guards sit at the top of `call_llm` and either could
        plausibly come first. Cancellation wins: reporting
        `cost_budget_exceeded` for a run the operator already stopped
        would send whoever reads the job record looking at the wrong
        thing entirely.
        """
        from src.observability.costs import _current_costs, start_cost_tracking

        monkeypatch.setattr(llm_module, "settings", Settings(max_cost_usd=0.01))
        token = CancelToken("both-guards-armed")
        token.cancel("job_timeout")
        scope = bind_cancel_token(token)
        # An accumulator that is already over the cap, so the budget
        # guard would fire too if it got the chance. Reset in `finally`
        # because the ContextVar outlives the test in this same pytest
        # context, and an armed accumulator changes `call_llm`
        # everywhere.
        overspent = start_cost_tracking()
        overspent.record("claude-sonnet-4-6", input_tokens=1, output_tokens=0, cost_usd=9.99)
        try:
            with pytest.raises(JobCancelledError):
                llm_module.call_llm("prompt")
        finally:
            _current_costs.set(None)
            reset_cancel_token(scope)


class TestCancellationAtShutdown:
    async def test_a_shutdown_cancel_is_a_cancelled_job_not_a_failed_one(
        self,
        triple: TripleObserver,
        pinned_runner_settings: Any,
    ) -> None:
        """The worker is going away; nothing about the run was wrong.

        This is the only terminal branch in `run_job` that re-raises,
        because the lifespan's task-cancellation machinery has to see
        the `CancelledError` it sent. The job still reaches a terminal
        state and is still counted first, so a rolling restart does not
        make the fleet's job counter lose a run per worker.
        """

        class _NeverFinishingWorkflow:
            async def astream(self, state: Any, config: Any = None) -> Any:
                await asyncio.Event().wait()
                yield {}  # pragma: no cover - unreachable, keeps this a generator

            async def aget_state(self, config: Any = None) -> Any:  # pragma: no cover
                raise ValueError("No checkpointer set")

        job = Job(job_id="shut-down", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        task = asyncio.create_task(
            run_job(job, _NeverFinishingWorkflow(), store, asyncio.Semaphore(1))
        )
        # Yield until the runner is actually inside the stream, rather
        # than sleeping a guessed interval: a wall-clock wait here would
        # be both slower and flakier.
        while job.status != JobStatus.running:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert job.status == JobStatus.cancelled
        assert job.error_type is None
        assert job.error is None

        record = triple.assert_triple(
            code=None,
            event="api_job_cancelled",
            instrument="research_jobs_total",
            attributes={"status": "cancelled", "error_type": "none"},
        )
        # INFO, not ERROR: an operator asked for this.
        assert record.levelno == logging.INFO

        stored = await store.get("shut-down")
        assert stored is not None and stored.status == JobStatus.cancelled
