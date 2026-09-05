"""Cost cap enforcement (ADR 0033, extended by ADR 0051).

The supervisor loop has its own `max_cost_usd` short-circuit, but the
fixed-DAG path has none. The runner's `on_node` callback is the one
place both graph shapes flow through, so enforcement started there.

ADR 0051 added a second enforcement point at `src.llm.call_llm`,
because `on_node` only exists on the API path: `make run` and
`make eval` drive the graph with a bare `app.invoke(...)` and had no
ceiling at all. Both raise the same `CostBudgetExceeded` against the
same accumulator.

Layers under test:

- `_enforce_cost_cap` — the pure boundary math.
- The sync path — no runner, no `on_node`, spend still stops.
- `run_job`'s exception handlers — the audit found the
  `CostBudgetExceeded` and `TimeoutError` paths had zero coverage,
  so the suite stayed green even if a refactor dropped the handlers
  or scrambled `error_type`. The handler tests below assert only
  observable behaviour (job status transitions and event-frame
  payloads), not runner internals, so they survive the planned
  runner refactor as long as the contract holds.
- Report preservation — hitting the ceiling must not throw away a
  draft the run has already paid for.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from src import llm as llm_module
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import CostBudgetExceeded, _enforce_cost_cap, run_job
from src.config import Settings
from src.observability import costs as costs_module
from src.observability.costs import (
    RunCosts,
    current_costs,
    start_cost_tracking,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_leaked_accumulator() -> Any:
    """Leave the cost ContextVar unbound for the next test.

    `start_cost_tracking()` writes a module-level ContextVar that
    outlives the test in the same pytest context, and an armed
    accumulator changes `call_llm`'s behaviour everywhere.
    """
    token = costs_module._current_costs.set(None)
    try:
        yield
    finally:
        costs_module._current_costs.reset(token)


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


# ---- the sync path: no runner, no on_node, still a ceiling -------------


class _SpendingClient:
    """Fake Anthropic client that bills a fixed amount per call.

    Stands in for the SDK at `call_llm`'s seam so the ceiling can be
    exercised without a network — the tokens are chosen to produce a
    known per-call cost through the real `estimate_cost` path.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.messages = SimpleNamespace(with_raw_response=self)

    def create(self, **_kwargs: Any) -> Any:
        self.calls += 1
        usage = SimpleNamespace(
            input_tokens=200_000,
            output_tokens=0,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        # `id` / `model` / `stop_reason` are read by ADR 0066's `chat`
        # span; a double missing them would fail on an observability
        # attribute rather than on the ceiling this test is about.
        parsed = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            usage=usage,
            id="msg_fake",
            model="claude-sonnet-4-6",
            stop_reason="end_turn",
        )
        return SimpleNamespace(retries_taken=0, parse=lambda: parsed)


def test_sync_pipeline_run_trips_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`make run` / `make eval` shape: an accumulator and nothing else.

    No `run_job`, no `on_node`, no supervisor — exactly what
    `src/main.py` and `src/eval/runner.py` set up before calling
    `app.invoke(...)`. Before ADR 0051 this loop ran until the queries
    ran out; now it stops at the ceiling.

    Mutation-check: removing `_check_cost_budget()` from `call_llm`
    makes the loop complete all 20 iterations and the `pytest.fail`
    below fires.
    """
    monkeypatch.setattr(
        llm_module, "settings", Settings(max_cost_usd=2.00)
    )
    client = _SpendingClient()
    monkeypatch.setattr(llm_module, "_get_client", lambda: client)

    costs = start_cost_tracking()
    # 200k Sonnet input tokens = $0.60 per call, so the $2.00 cap is
    # crossed on the fourth call's pre-flight check.
    for _ in range(20):
        try:
            llm_module.call_llm("q")
        except CostBudgetExceeded as exc:
            assert exc.cap_usd == 2.00
            assert exc.spent_usd >= 2.00
            break
    else:  # pragma: no cover - only reached when the cap never fires
        pytest.fail("call_llm never enforced max_cost_usd on the sync path")

    assert client.calls == 4
    assert costs.total_cost_usd == pytest.approx(2.40)


def test_reader_fanout_stops_spending_and_names_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The brake holds inside the reader's fan-out, and the label is honest.

    `reader_agent` re-raises `CostBudgetExceeded` from its per-paper
    degradation guard exactly as it re-raises `JobCancelledError`
    (ADR 0047's contract, extended by ADR 0051): once the ceiling
    trips, degrading each remaining paper in turn would carry the run
    on to synthesis and the judges — spending the calls the ceiling
    exists to stop. A capped run therefore surfaces as a budget stop,
    not as `AllPaperAnalysesFailedError`.

    Two guarantees pinned here: **not one call is issued** once the
    ceiling is crossed, and the exception that escapes the node names
    the real cause.

    Mutation-checks: removing `_check_cost_budget()` from `call_llm`
    makes `client.calls == 3`; removing `CostBudgetExceeded` from the
    reader's re-raise tuple turns the raise into
    `AllPaperAnalysesFailedError`. Both fail this test.
    """
    from src.agents.reader import reader_agent

    monkeypatch.setattr(llm_module, "settings", Settings(max_cost_usd=2.00))
    client = _SpendingClient()
    monkeypatch.setattr(llm_module, "_get_client", lambda: client)

    costs = start_cost_tracking()
    costs.record(
        "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0, cost_usd=3.00
    )

    papers = [
        {
            "id": f"p{i}",
            "title": f"Paper {i}",
            "abstract": "abstract text",
            "authors": ["A. Author"],
            "published": "2026-01-01",
            "pdf_url": "",
            "url": "http://example.invalid/p",
            "categories": ["cs.AI"],
            "summary": "summary",
        }
        for i in range(3)
    ]
    state: Any = {
        "run_id": "cap-probe",
        "query": "q",
        "sub_questions": ["s1"],
        "search_queries": [],
        "papers": papers,
        "paper_analyses": [],
        "draft_report": "",
        "citations": [],
        "critique": "",
        "quality_score": 0.0,
        "revision_needed": False,
        "revision_target": "",
        "iteration": 0,
        "next_action": "",
        "loop_iterations": 0,
        "stop_reason": "",
        "messages": [],
    }

    with pytest.raises(CostBudgetExceeded):
        reader_agent(state)

    # The load-bearing assertion: over the cap, the fan-out spends nothing.
    assert client.calls == 0
    assert costs.total_cost_usd == pytest.approx(3.00)


def test_sync_run_without_tracking_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No accumulator bound means no run to measure.

    A unit test or an ad-hoc script has no budget to exceed, and must
    keep working exactly as it did — the same rule `record_llm_call`
    already follows.
    """
    monkeypatch.setattr(
        llm_module, "settings", Settings(max_cost_usd=0.01)
    )
    client = _SpendingClient()
    monkeypatch.setattr(llm_module, "_get_client", lambda: client)

    assert current_costs() is None
    for _ in range(3):
        llm_module.call_llm("q")

    assert client.calls == 3


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


class ReportThenOverspendStub:
    """Produces a report, then blows the cap.

    Two shapes in one, selected by `raise_from_node`:

    - `False` — the node that finished the report is also the node
      whose spend crossed the ceiling, so `on_node` raises after the
      update has already landed in the runner's merged state. This is
      the "run completed on its final node and was failed anyway"
      case the audit called out.
    - `True` — the exception comes out of the *stream* itself, which
      is what `src.llm.call_llm`'s per-call check does from inside a
      later node (ADR 0051). The earlier node's report must survive
      that too.
    """

    def __init__(self, cost_usd: float, *, raise_from_node: bool) -> None:
        self._cost_usd = cost_usd
        self._raise_from_node = raise_from_node

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
        yield {"synthesizer": {"draft_report": "# Findings\n\nParagraph."}}
        if self._raise_from_node:
            raise CostBudgetExceeded(
                spent_usd=self._cost_usd, cap_usd=2.0
            )

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
    # ADR 0064: the cap's own sentence ("... exceeded cap ...") is a
    # log field now; the job record carries the code.
    assert job.error == "cost_budget_exceeded"
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
    # WO-B3: this used to pin a four-key literal of its own. Every
    # terminal frame is `terminal_event_data`'s twelve keys now, live
    # and replayed alike, and the shape is pinned once in
    # `tests/test_contract_sse_events.py` rather than re-listed at each
    # site — four copies of a payload shape being how the shapes came
    # to disagree in the first place.
    assert terminal["status"] == "failed"
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
    assert job.error == "timeout"
    assert job.completed_at is not None

    stored = await store.get("too-slow")
    assert stored is not None and stored.status == JobStatus.failed

    frames = _drain_queue(job)
    assert [f["event"] for f in frames] == ["job_started", "job_failed"]
    terminal = frames[-1]["data"]
    # WO-B3: this used to pin a four-key literal of its own. Every
    # terminal frame is `terminal_event_data`'s twelve keys now, live
    # and replayed alike, and the shape is pinned once in
    # `tests/test_contract_sse_events.py` rather than re-listed at each
    # site — four copies of a payload shape being how the shapes came
    # to disagree in the first place.
    assert terminal["status"] == "failed"
    assert terminal["error_type"] == "timeout"


# ---- the paid-for draft must survive the ceiling (ADR 0051) -----------


async def test_capped_job_keeps_the_report_it_already_paid_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failing the job is right; throwing away the artifact is not.

    The old handler set status / error / error_type / cost and returned
    without ever touching `job.result`, so `GET /research/{id}` returned
    a bill with nothing attached — even for a run whose *last* node
    produced a complete report and happened to cross the cap doing it.

    Mutation-check: deleting the `job.result = exc.partial_report`
    assignment leaves `job.result` None and this fails; deleting the
    `except CostBudgetExceeded` block in `_invoke_streaming` leaves
    `partial_report` empty and it fails the same way.
    """
    import src.api.runner as runner_module

    monkeypatch.setattr(runner_module, "settings", Settings(max_cost_usd=2.0))
    job = Job(job_id="cost-blown-with-report", query="q", hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)

    await run_job(
        job,
        ReportThenOverspendStub(3.0, raise_from_node=False),
        store,
        asyncio.Semaphore(1),
    )

    assert job.status == JobStatus.failed
    assert job.error_type == "cost_budget_exceeded"
    assert job.result == "# Findings\n\nParagraph."
    # And it is durable, not just on the in-memory object — the
    # retrieval path reads the store.
    stored = await store.get("cost-blown-with-report")
    assert stored is not None
    assert stored.result == "# Findings\n\nParagraph."


async def test_report_survives_a_cap_raised_from_inside_a_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`call_llm`'s per-call check raises from inside the graph.

    That path never reaches `on_node`, so the draft has to be
    recovered from the runner's merged state rather than from the
    callback's own frame.
    """
    import src.api.runner as runner_module

    monkeypatch.setattr(runner_module, "settings", Settings(max_cost_usd=2.0))
    job = Job(job_id="cost-blown-mid-node", query="q", hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)

    await run_job(
        job,
        ReportThenOverspendStub(1.0, raise_from_node=True),
        store,
        asyncio.Semaphore(1),
    )

    assert job.status == JobStatus.failed
    assert job.error_type == "cost_budget_exceeded"
    assert job.result == "# Findings\n\nParagraph."


async def test_capped_job_with_no_report_stores_none_not_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that bought nothing must not look like it bought a blank.

    `""` and `None` read very differently downstream: the export route
    refuses on falsy `result`, but a `JobDetail` carrying `result: ""`
    tells a client a report exists and is empty.
    """
    import src.api.runner as runner_module

    monkeypatch.setattr(runner_module, "settings", Settings(max_cost_usd=2.0))
    job = Job(job_id="cost-blown-no-report", query="q", hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)

    await run_job(job, OverspendingStub(3.0), store, asyncio.Semaphore(1))

    assert job.status == JobStatus.failed
    assert job.result is None
