"""Virtual seconds through production admission/HTTP; no real sleeps or provider."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from src.workspace import d5_adapter as d
from src.workspace import d5_deadlines as deadlines
from src.workspace import provider_adapter as provider
from src.workspace.admission import AdmissionError
from tests import test_workspace_coverage_adapter as support
from tests.test_workspace_task_policy import NORMAL

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc, workspace_pg = support.workspace_pg_proc, support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


class Clock:
    def __init__(self):
        self.seconds = 0
        self.base = datetime.now(UTC)
        self.stack = []

    def now(self):
        return self.base + timedelta(seconds=self.seconds)

    def advance(self, seconds):
        self.seconds += seconds
        if any(self.seconds >= deadline for deadline in self.stack):
            raise TimeoutError("Synthetic controlled-time deadline; no provider contact")

    def timeout(self, seconds):
        clock = self

        class Timer:
            async def __aenter__(self):
                clock.stack.append(clock.seconds + seconds)
                return self

            async def __aexit__(self, *args):
                clock.stack.pop()

        return Timer()


class Delayed(support.Transport):
    def __init__(self, clock, delay=31, fault=None, defect=None):
        super().__init__(NORMAL, defect=defect)
        self.clock, self.delay, self.fault = clock, delay, fault
        self.attempts, self.timeouts = [], []
        self.adapter, self.job = None, None

    async def __call__(self, request):
        body = json.loads(request.content)
        self.attempts.append((request.url.path, body["model"]))
        self.timeouts.append(request.extensions["timeout"]["read"])
        if request.url.path.endswith("/messages") and body["model"] == "claude-opus-5-5":
            self.clock.advance(self.delay)
            if self.fault == "cancel":
                self.adapter.control.cancel("d5-run", self.job)
                raise asyncio.CancelledError()
            if self.fault == "restart":
                self.adapter.control.recover("d5-run", self.job)
                raise TimeoutError("Synthetic process loss before response")
            if self.fault == "expiry":
                with self.adapter.store.pool.connection() as conn:
                    conn.execute("UPDATE workspace_d5_scopes SET expires_at=%s", (datetime.now(UTC) - timedelta(seconds=1),))
                raise TimeoutError("Synthetic expiry during unreceived request")
        return await super().__call__(request)


def runtime(store, monkeypatch, clock, transport, *, sealed=True):
    original = d.prepare_input
    with monkeypatch.context() as setup_patch:
        if sealed:
            setup_patch.setattr(
                d,
                "prepare_input",
                lambda *a, **kw: original(*a, **kw, operation_deadlines=deadlines.POLICY),
            )
        adapter, inputs = support.runtime(store, NORMAL, transport)
    job = adapter.start(inputs.settings["d5_request_id"])
    transport.adapter, transport.job = adapter, job["id"]
    with store.pool.connection() as conn:
        data = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id=%s", (job["id"],)
        ).fetchone()[0]
    clock.base = datetime.fromisoformat(data["created_at"])
    monkeypatch.setattr(deadlines, "now", clock.now)
    monkeypatch.setattr(provider.asyncio, "timeout", clock.timeout)
    monkeypatch.setattr(provider, "monotonic", lambda: clock.seconds)
    return adapter, inputs, job["id"]


@pytest.mark.parametrize("sealed", [False, True])
async def test_valid_checker_after31_virtual_seconds_legacy_refuses_new_completes(
    store, monkeypatch, sealed
):
    clock = Clock()
    transport = Delayed(clock)
    adapter, _, job = runtime(store, monkeypatch, clock, transport, sealed=sealed)
    await adapter.advance(job)
    if sealed:
        result = await adapter.advance(job)
        assert result["state"] == "ready" and not result["result"]["checker_qualified"]
        assert transport.timeouts == [30, 30, 30, 120]
        assert len(result["contacts"]) == 4
        assert result["contacts"][-1]["timeout_seconds"] == 120
        timings = result["contacts"][-1]["timing"]["events"]
        assert [e["event"] for e in timings] == ["dispatch", "first_body_byte", "full_body"]
        assert [e["elapsed_seconds"] for e in timings] == [0, 31, 31]
        assert all(datetime.fromisoformat(e["utc"]).tzinfo for e in timings)
        assert adapter.start(adapter.inputs.settings["d5_request_id"])["state"] == "ready"
        assert len(transport.attempts) == 4
    else:
        with pytest.raises(TimeoutError):
            await adapter.advance(job)
        assert adapter.snapshot(job)["state"] == "uncertain"
        assert transport.timeouts == [30, 30, 30, 30]


async def test_new_timeout_after121_virtual_seconds_retains_uncertainty_and_no_replay(
    store, monkeypatch
):
    clock = Clock()
    transport = Delayed(clock, delay=121)
    adapter, inputs, job = runtime(store, monkeypatch, clock, transport)
    await adapter.advance(job)
    with pytest.raises(TimeoutError):
        await adapter.advance(job)
    result = adapter.snapshot(job)
    assert result["state"] == "uncertain" and result["result"] is None
    assert (
        result["contacts"][-1]["state"] == "dispatching"
        and "response" not in result["contacts"][-1]
    )
    assert len(transport.attempts) == 4
    timings = result["contacts"][-1]["timing"]["events"]
    assert [e["event"] for e in timings] == ["dispatch", "timeout"]
    assert timings[-1]["elapsed_seconds"] == 121
    with store.pool.connection() as conn:
        held = conn.execute(
            "SELECT unknown FROM workspace_spend_reservations WHERE job_id=%s", (job,)
        ).fetchone()[0]
    assert held == Decimal("0.45")
    restarted = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    with pytest.raises(AdmissionError):
        await restarted.advance(job)
    with pytest.raises(AdmissionError):
        restarted.start(inputs.settings["d5_request_id"])
    with pytest.raises(AdmissionError):
        restarted.start("alternate-id")
    assert len(transport.attempts) == 4
    with store.pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT unknown FROM workspace_spend_reservations WHERE job_id=%s", (job,)
            ).fetchone()[0]
            == held
        )


@pytest.mark.parametrize("fault", ["cancel", "restart", "expiry"])
async def test_interruption_expiry_restart_do_not_cancel_remote_or_release_hold(store, monkeypatch, fault):
    clock = Clock()
    transport = Delayed(clock, fault=fault)
    adapter, inputs, job = runtime(store, monkeypatch, clock, transport)
    await adapter.advance(job)
    with pytest.raises((TimeoutError, asyncio.CancelledError)):
        await adapter.advance(job)
    snapshot = adapter.snapshot(job)
    assert snapshot["state"] in {"uncertain", "cancelled"} and snapshot["result"] is None
    assert snapshot["contacts"][-1]["state"] == "dispatching"
    with store.pool.connection() as conn:
        before = conn.execute("SELECT amount,workflow,judge,unknown FROM workspace_spend_reservations WHERE job_id=%s", (job,)).fetchone()
    assert before == (Decimal("0.45"), Decimal(0), Decimal(0), Decimal("0.45"))
    restarted = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    with pytest.raises(AdmissionError):
        await restarted.advance(job)
    assert len(transport.attempts) == 4
    with store.pool.connection() as conn:
        assert conn.execute("SELECT amount,workflow,judge,unknown FROM workspace_spend_reservations WHERE job_id=%s", (job,)).fetchone() == before


async def test_workflow480_deadline_caps_call_and_restart_never_resets_origin(store, monkeypatch):
    clock = Clock()
    transport = Delayed(clock, delay=6)
    adapter, inputs, job = runtime(store, monkeypatch, clock, transport)
    await adapter.advance(job)
    clock.advance(475)
    with pytest.raises(TimeoutError):
        await adapter.advance(job)
    assert transport.timeouts[-1] == pytest.approx(5)
    assert adapter.snapshot(job)["state"] == "uncertain"
    restarted = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    with pytest.raises(AdmissionError, match="workflow_deadline_exceeded"):
        await restarted.advance(job)
    assert len(transport.attempts) == 4
    with store.pool.connection() as conn:
        assert conn.execute("SELECT unknown FROM workspace_spend_reservations WHERE job_id=%s", (job,)).fetchone()[0] == Decimal("0.45")


async def test_complete_four_stage_flow_preserves_models_budgets_and_paired_counts(store, monkeypatch):
    clock = Clock()
    transport = Delayed(clock, defect="bundle")
    adapter, inputs, job = runtime(store, monkeypatch, clock, transport)
    for _ in range(4):
        result = await adapter.advance(job)
    assert result["state"] == "ready"
    assert [s["stage"] for s in result["steps"]] == ["draft", "check", "repair", "check"]
    assert transport.timeouts == [30, 30, 30, 120, 30, 30, 30, 120]
    assert [s["model_id"] for s in result["steps"]] == ["claude-sonnet-5-5", "claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
    assert len(result["contacts"]) == 8 and clock.seconds == 62
    assert inputs.settings["max_repairs"] == 1 and result["workflow_usd"] == result["checker_usd"] == "0"


@pytest.mark.parametrize("data", [{}, {"created_at": None}, {"created_at": "bad"}, {"created_at": "2026-11-11T00:00:00"}])
async def test_deadline_requires_durable_timezone_origin(data):
    with pytest.raises(AdmissionError, match="durable_deadline_origin"):
        deadlines.remaining(data)


async def test_policy_and_operation_drift_are_refused():
    for value in [None, {}, {**deadlines.POLICY, "check_seconds": 121}]:
        with pytest.raises(AdmissionError, match="policy_drift"):
            deadlines.validate(value)
    with pytest.raises(AdmissionError, match="operation_required"):
        deadlines.timeout("unknown", {"stage": "draft"}, {})


async def test_future_origin_cannot_extend_the_overall_horizon(monkeypatch):
    now = datetime.now(UTC)
    monkeypatch.setattr(deadlines, "now", lambda: now)
    with pytest.raises(AdmissionError, match="clock_precedes"):
        deadlines.remaining({"created_at": (now + timedelta(seconds=1)).isoformat()})
