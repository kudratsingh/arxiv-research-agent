"""The cost ceiling trips mid-run (WO-A06 scenario 6).

`tests/test_runner_cost_cap.py` already pins the job record and the SSE
frame. What it cannot see — and what a capped run is actually judged on
in production — is whether the three contracts agree:

| leg | value |
|---|---|
| code | `cost_budget_exceeded` |
| event | `api_job_cost_budget_exceeded` |
| metric | `research_jobs_total{status="failed", error_type="cost_budget_exceeded"}` |

The terminal status is not this tier's opinion. ADR 0051 §2 rules it:
"The job stays `failed` with `error_type=cost_budget_exceeded` — the
caller must know the report is partial — but `GET /research/{id}` and
the export routes now return the artifact the money already bought."
Both halves of that sentence are asserted below, because they are the
two ways a cost cap goes wrong: reporting success on a truncated run,
or throwing away a report the operator has already been billed for.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.errors import JOB_ERROR_TYPES, BudgetExceededRun
from src.observability.costs import CostBudgetExceeded, current_costs

from .conftest import ScriptedWorkflow, TripleObserver

pytestmark = [pytest.mark.unit, pytest.mark.fault]

#: Over `Settings().max_cost_usd` by a wide margin, so the cap fires on
#: the first `on_node` check rather than depending on the shipped
#: default's exact value.
OVERSPEND_USD = 250.0

REPORT = "# Findings\n\nOne paragraph the operator has already paid for."


def _spend_over_the_cap() -> None:
    """Bill the run's accumulator the way a real agent call does.

    Through `RunCosts.record` rather than a patched total: the runner's
    `on_node` callback reads the accumulator, and a test that set the
    number some other way would pass against a runner that had stopped
    reading it.
    """
    costs = current_costs()
    assert costs is not None, "run_job must have started cost tracking"
    costs.record(
        "claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=0,
        cost_usd=OVERSPEND_USD,
    )


async def _run_capped_job(
    job_id: str,
    workflow: Any,
) -> tuple[Job, InMemoryJobStore]:
    job = Job(job_id=job_id, query="q", hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)
    await run_job(job, workflow, store, asyncio.Semaphore(1))
    return job, store


class TestTheCapTripsMidRun:
    async def test_a_capped_run_agrees_on_the_code_the_event_and_the_metric(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        frames: Any,
    ) -> None:
        """The whole reason this tier exists, on the one fault that costs money."""
        workflow = scripted_workflow(
            updates=[{"planner": {"iteration": 0}}], on_stream=_spend_over_the_cap
        )

        job, store = await _run_capped_job("capped", workflow)

        assert job.status == JobStatus.failed
        assert job.error_type == BudgetExceededRun.code
        # `error` is the code too, not joined exception text (ADR 0064).
        assert job.error == job.error_type

        record = triple.assert_triple(
            code=job.error_type,
            event="api_job_cost_budget_exceeded",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": "cost_budget_exceeded"},
        )
        # "Did the spend buy anything" is the first question asked about
        # a capped job, so the log line has to be able to answer it.
        assert getattr(record, "spent_usd", None) == pytest.approx(OVERSPEND_USD)
        assert getattr(record, "cap_usd", None) == pinned_runner_settings.max_cost_usd

        # The duration histogram shares the `failed` series with every
        # other failure — the question is "how long do failures take",
        # not "per error type" — so it is asserted separately.
        timed = triple.point("research_job_duration_seconds", status="failed")
        assert timed.count == 1

        stored = await store.get("capped")
        assert stored is not None and stored.status == JobStatus.failed
        assert [f["event"] for f in frames(job)][-1] == "job_failed"

    async def test_the_code_is_one_a_run_is_allowed_to_carry(self) -> None:
        """`ERROR_CODES` is the whole vocabulary; `JOB_ERROR_TYPES` is the
        subset a *run* can end as, and it is what the frontend's copy
        dictionary is derived from. A cap that landed a code outside it
        would render as an unmapped error in the product."""
        assert BudgetExceededRun.code in JOB_ERROR_TYPES

    async def test_the_report_already_paid_for_survives_the_ceiling(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
    ) -> None:
        """Failing the job is right; discarding the artifact is not.

        The failure arrives from inside the stream, after a node has
        already produced a draft — the `call_llm` pre-flight shape,
        which never reaches `on_node` at all, so the draft has to come
        out of the runner's merged state.
        """
        workflow = scripted_workflow(
            updates=[{"synthesizer": {"draft_report": REPORT}}],
            raises=CostBudgetExceeded(
                spent_usd=OVERSPEND_USD, cap_usd=pinned_runner_settings.max_cost_usd
            ),
        )

        job, store = await _run_capped_job("capped-with-report", workflow)

        assert job.status == JobStatus.failed
        assert job.result == REPORT
        stored = await store.get("capped-with-report")
        # Durable, not just on the in-memory object: the retrieval path
        # reads the store, and a bill with nothing attached is what this
        # assertion exists to prevent.
        assert stored is not None and stored.result == REPORT

        record = triple.assert_triple(
            code=job.error_type,
            event="api_job_cost_budget_exceeded",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": "cost_budget_exceeded"},
        )
        assert getattr(record, "partial_report_chars", None) == len(REPORT)

    async def test_the_spend_at_the_moment_of_the_abort_is_on_the_record(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
    ) -> None:
        """The bill was incurred even though the run was cut short.

        A capped job that reported `cost_usd=None` would make the one
        number the cap exists to control unreadable at exactly the
        moment it matters.
        """
        workflow = scripted_workflow(
            updates=[{"planner": {"iteration": 0}}], on_stream=_spend_over_the_cap
        )

        job, _ = await _run_capped_job("capped-billed", workflow)

        assert job.cost_usd == pytest.approx(OVERSPEND_USD)
        assert job.llm_calls == 1
        triple.assert_triple(
            code=job.error_type,
            event="api_job_cost_budget_exceeded",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": "cost_budget_exceeded"},
        )
