"""Runner-level cost cap (ADR 0033).

The supervisor loop has its own `max_cost_usd` short-circuit, but the
fixed-DAG path has none. The runner's `on_node` callback is the one
place both shapes flow through, so the enforcement lives there.

Two layers under test:

- `_enforce_cost_cap` — the pure boundary math.
- `run_job`'s exception handlers — the audit found the
  `CostBudgetExceeded` and `TimeoutError` paths had zero coverage,
  so the suite stayed green even if a refactor dropped the handlers
  or scrambled `error_type`. The handler tests below assert only
  observable behaviour (job status transitions and event-frame
  payloads), not runner internals, so they survive the planned
  runner refactor as long as the contract holds.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import CostBudgetExceeded, _enforce_cost_cap, run_job
from src.config import Settings
from src.observability.costs import RunCosts, current_costs

pytestmark = pytest.mark.unit


def test_under_cap_does_not_raise() -> None:
    costs = RunCosts()
    costs.record("claude-sonnet-4-6", input_tokens=100, output_tokens=50, cost_usd=0.10)
    _enforce_cost_cap(costs, cap_usd=2.00)  # no raise


def test_at_or_above_cap_raises_with_context() -> None:
    costs = RunCosts()
    costs.record(
        "claude-opus-4-7", input_tokens=1000, output_tokens=1000, cost_usd=1.50
    )
    costs.record(
        "claude-opus-4-7", input_tokens=1000, output_tokens=1000, cost_usd=0.55
    )
    with pytest.raises(CostBudgetExceeded) as exc_info:
        _enforce_cost_cap(costs, cap_usd=2.00)
    exc = exc_info.value
    assert exc.cap_usd == 2.00
    assert exc.spent_usd == pytest.approx(2.05, abs=0.01)
    assert "2.05" in str(exc) or "2.0500" in str(exc)
    assert "2.00" in str(exc)


def test_cap_at_boundary_raises() -> None:
    """Boundary: spend exactly at the cap must abort before the NEXT
    node runs. Otherwise a single expensive call sits right at the
    limit and the next node happily blows past it."""
    costs = RunCosts()
    costs.record(
        "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0, cost_usd=2.00
    )
    with pytest.raises(CostBudgetExceeded):
        _enforce_cost_cap(costs, cap_usd=2.00)


def test_zero_cost_never_raises() -> None:
    costs = RunCosts()
    _enforce_cost_cap(costs, cap_usd=0.01)  # empty accumulator, no raise


# ---- run_job handler coverage ------------------------------------------


class OverspendingStub:
    """Fake compiled workflow whose first node blows the cost cap.

    Records an LLM spend above `settings.max_cost_usd` on the run's
    accumulator (exactly what a real agent call does via
    `record_llm_call`), then yields a node update. The runner's
    `on_node` callback fires `_enforce_cost_cap` after the update and
    must raise `CostBudgetExceeded`.
    """

    def __init__(self, cost_usd: float) -> None:
        self._cost_usd = cost_usd

    async def astream(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        costs = current_costs()
        assert costs is not None, "run_job must start cost tracking"
        costs.record(
            "claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=0,
            cost_usd=self._cost_usd,
        )
        yield {"planner": {"iteration": 0}}

    def get_state(self, config: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(next=(), values={})

    def invoke(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:  # pragma: no cover - unreached past the cap
        return {}


class HangingStub:
    """Fake compiled workflow that never finishes its first node."""

    async def astream(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        await asyncio.sleep(60)
        yield {"planner": {}}  # pragma: no cover - timeout fires first

    def get_state(self, config: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(next=(), values={})

    def invoke(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:  # pragma: no cover - unreached
        return {}


def _drain_queue(job: Job) -> list[dict[str, Any]]:
    """Snapshot every frame the runner queued, in order."""
    frames: list[dict[str, Any]] = []
    while not job.event_queue.empty():
        frames.append(job.event_queue.get_nowait())
    return frames


async def test_run_job_cost_budget_exceeded_fails_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CostBudgetExceeded` mid-run ends as a failed job with
    `error_type=cost_budget_exceeded`, spend recorded, and a
    `job_failed` terminal frame carrying the documented fields.

    `src.api.runner.settings` is pinned to a real `Settings` because
    other API tests substitute a `SimpleNamespace` on the module and
    never restore it — without the pin, `run_job`'s `getattr`
    fallback would read `max_cost_usd=inf` and the cap would never
    fire depending on test order.
    """
    import src.api.runner as runner_module

    monkeypatch.setattr(runner_module, "settings", Settings(max_cost_usd=2.0))
    over_cap = 3.0
    job = Job(job_id="cost-blown", query="q", hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)

    await run_job(
        job,
        OverspendingStub(over_cap),
        store,
        asyncio.Semaphore(1),
    )

    assert job.status == JobStatus.failed
    assert job.error_type == "cost_budget_exceeded"
    assert job.error is not None and "exceeded cap" in job.error
    assert job.completed_at is not None
    # Spend at time of abort is preserved on the record — the bill
    # was incurred even though the run was cut short.
    assert job.cost_usd == pytest.approx(over_cap)
    assert job.llm_calls == 1

    # The store saw the terminal transition, not just the local object.
    stored = await store.get("cost-blown")
    assert stored is not None and stored.status == JobStatus.failed

    frames = _drain_queue(job)
    assert [f["event"] for f in frames] == [
        "job_started",
        "node_completed",
        "job_failed",
    ]
    terminal = frames[-1]["data"]
    assert set(terminal) == {"job_id", "error", "error_type", "elapsed_sec"}
    assert terminal["job_id"] == "cost-blown"
    assert terminal["error_type"] == "cost_budget_exceeded"


async def test_run_job_timeout_fails_the_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workflow overrunning `timeout_sec` ends as a failed job with
    `error_type=timeout` and a `job_failed` terminal frame."""
    import src.api.runner as runner_module

    # Same pinning rationale as the cost-cap test above.
    monkeypatch.setattr(runner_module, "settings", Settings())
    job = Job(job_id="too-slow", query="q", hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)

    await run_job(
        job,
        HangingStub(),
        store,
        asyncio.Semaphore(1),
        timeout_sec=1,
    )

    assert job.status == JobStatus.failed
    assert job.error_type == "timeout"
    assert job.error == "Workflow exceeded 1s timeout"
    assert job.completed_at is not None

    stored = await store.get("too-slow")
    assert stored is not None and stored.status == JobStatus.failed

    frames = _drain_queue(job)
    assert [f["event"] for f in frames] == ["job_started", "job_failed"]
    terminal = frames[-1]["data"]
    assert set(terminal) == {"job_id", "error", "error_type", "elapsed_sec"}
    assert terminal["error_type"] == "timeout"
