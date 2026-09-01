"""WO-W06 per-session cost ceiling, product outcomes, and cap isolation."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from src import llm as llm_module
from src.api import runner as runner_module
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.config import Settings
from src.observability import costs as costs_module
from src.observability.costs import current_costs, unpriced_models

pytestmark = pytest.mark.unit


class _CostCheckingWorkflow:
    """Simulate billed calls, then enter the real pre-call choke point."""

    def __init__(self, costs: tuple[float, ...]) -> None:
        self.costs = costs
        self.values: dict[str, Any] = {}
        self.client_constructed = False

    async def astream(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        accumulator = current_costs()
        assert accumulator is not None
        for cost in self.costs:
            accumulator.record(
                "claude-haiku-4-5",
                input_tokens=100,
                output_tokens=20,
                cost_usd=cost,
            )
        # This is the guard `call_llm` executes before `_get_client`.
        # A raise here proves the next paid call was refused.
        llm_module._check_cost_budget()
        self.client_constructed = True
        self.values = {"draft_report": "complete", "iteration": 1}
        yield {"close": dict(self.values)}

    async def aget_state(self, config: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(next=(), values=dict(self.values))


def _settings(behavior: str = "refuse") -> Settings:
    return Settings(
        max_cost_usd=2.0,
        learning_session_max_cost_usd=0.50,
        learning_session_cost_cap_behavior=behavior,
    )


async def _run(kind: str, configured: Settings) -> tuple[Job, _CostCheckingWorkflow]:
    store = InMemoryJobStore()
    job = Job(job_id=f"{kind}-cost", query="q", kind=kind)  # type: ignore[arg-type]
    workflow = _CostCheckingWorkflow((0.30, 0.25))
    await store.create(job)
    await run_job(job, workflow, store, asyncio.Semaphore(1))
    return job, workflow


@pytest.mark.parametrize(
    "behavior,expected_status,expected_cap_status,expected_error",
    [
        ("refuse", JobStatus.failed, "refused", "session_cost_cap_refused"),
        ("degraded_close", JobStatus.succeeded, "degraded_close", None),
    ],
)
async def test_both_at_cap_behaviors_are_explicit_and_make_no_next_call(
    monkeypatch: pytest.MonkeyPatch,
    behavior: str,
    expected_status: JobStatus,
    expected_cap_status: str,
    expected_error: str | None,
) -> None:
    configured = _settings(behavior)
    monkeypatch.setattr(runner_module, "settings", configured)
    monkeypatch.setattr(llm_module, "settings", configured)

    job, workflow = await _run("session", configured)

    assert workflow.client_constructed is False
    assert job.status is expected_status
    assert job.cost_cap_status == expected_cap_status
    assert job.error_type == expected_error
    assert job.cost_usd == pytest.approx(0.55)
    assert job.llm_calls == 2
    assert job.cost_cap_message is not None
    assert "$0.50 cost limit" in job.cost_cap_message
    assert "No further" in job.cost_cap_message or "no further" in job.cost_cap_message
    frames = []
    while not job.event_queue.empty():
        frames.append(job.event_queue.get_nowait())
    terminal = frames[-1]
    assert terminal["event"] == (
        "job_completed" if expected_status is JobStatus.succeeded else "job_failed"
    )
    assert terminal["data"]["cost_cap_status"] == expected_cap_status
    assert terminal["data"]["cost_usd"] == pytest.approx(0.55)
    assert terminal["data"]["llm_calls"] == 2


async def test_session_cap_does_not_bleed_into_research_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = _settings()
    monkeypatch.setattr(runner_module, "settings", configured)
    monkeypatch.setattr(llm_module, "settings", configured)

    session, _ = await _run("session", configured)
    research, workflow = await _run("research", configured)

    assert session.status is JobStatus.failed
    assert research.status is JobStatus.succeeded
    assert research.cost_cap_status == ""
    assert research.cost_usd == pytest.approx(0.55)
    assert workflow.client_constructed is True


async def test_successful_mock_accounting_reconciles_to_the_cent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = _settings()
    monkeypatch.setattr(runner_module, "settings", configured)
    monkeypatch.setattr(llm_module, "settings", configured)
    store = InMemoryJobStore()
    job = Job(job_id="session-accounting", query="q", kind="session")
    workflow = _CostCheckingWorkflow((0.04, 0.05))
    await store.create(job)

    await run_job(job, workflow, store, asyncio.Semaphore(1))

    assert job.status is JobStatus.succeeded
    assert round(job.cost_usd or 0.0, 2) == 0.09
    assert job.llm_calls == 2


def test_unpriced_tutor_route_warns_instead_of_silently_unpricing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    costs_module.reset_unpriced_warnings()
    with caplog.at_level(logging.WARNING, logger="src.observability.costs"):
        missing = unpriced_models(Settings(tutor_model="claude-tutor-new-99"))
    assert missing == {"claude-tutor-new-99"}
    warnings = [
        record for record in caplog.records if record.message == "unknown_model_pricing_fallback"
    ]
    assert len(warnings) == 1
    assert warnings[0].model == "claude-tutor-new-99"


def test_session_cap_defaults_to_conservative_refusal() -> None:
    configured = Settings()
    assert configured.learning_session_max_cost_usd == 0.50
    assert configured.learning_session_cost_cap_behavior == "refuse"
