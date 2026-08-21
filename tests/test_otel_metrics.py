"""Unit tests for the OpenTelemetry metrics layer (ADR 0049).

Uses the SDK's `InMemoryMetricReader` so every assertion is made
against real aggregated metric data — the same objects the OTLP
exporter would serialize — without running a collector.

Named `test_otel_metrics.py` rather than `test_metrics.py` because the
`test_metrics_*.py` files in this directory are the *eval* LLM-judge
metrics (citation accuracy, completeness, ...), an unrelated meaning
of the word.

Covers, per instrument family:

- the terminal-job counter + duration histogram, including the
  attribute shape and the "never started" branch;
- the per-model LLM cost + call counters, recorded from the existing
  `record_llm_call` choke point;
- the 429 counter, recorded from the shared `_raise_429` helper for
  both limiter backends;
- the two observable gauges, which must reflect whatever the injected
  live-accounting callables say at collection time;
- the flag-off path: no provider, no instruments, and record helpers
  that are inert.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from fastapi import HTTPException
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from src.api import auth as auth_module
from src.api import runner as runner_module
from src.api.app import create_app
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.config import Settings
from src.observability import costs as costs_module
from src.observability import metrics as metrics_module

pytestmark = pytest.mark.unit


async def _no_sleep(_seconds: float) -> None:
    """Collapse the terminal-persist retry backoff in tests."""
    return None


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _reset_metrics_module() -> None:
    """Return `src.observability.metrics` to its unconfigured state.

    `shutdown_metrics` does the real work; the gauge bookkeeping is
    cleared alongside it. `_global_provider_set` is deliberately NOT
    reset — OTel's global meter provider genuinely is set-once per
    process, and pretending otherwise would let a test assert
    behaviour production can't reproduce.
    """
    metrics_module.shutdown_metrics()


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryMetricReader]:
    """Configure the metrics module against an in-memory reader.

    Forces `enable_metrics=True` on the module's `settings` handle
    (same monkeypatch idiom `test_tracing.py` uses) and tears the
    provider down afterwards so instruments never leak between tests.
    """
    _reset_metrics_module()
    monkeypatch.setattr(
        metrics_module,
        "settings",
        Settings(enable_metrics=True, otel_exporter_endpoint=""),
    )
    metric_reader = InMemoryMetricReader()
    metrics_module.configure_metrics(reader=metric_reader)
    yield metric_reader
    _reset_metrics_module()


@pytest.fixture
def disabled_metrics(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Force the flag off and leave the module unconfigured."""
    _reset_metrics_module()
    monkeypatch.setattr(
        metrics_module, "settings", Settings(enable_metrics=False)
    )
    yield
    _reset_metrics_module()


def _points(reader: InMemoryMetricReader, name: str) -> list[Any]:
    """Every data point currently aggregated for metric `name`.

    Returns:
        The points, in whatever order the SDK collected them; empty
        when the instrument has recorded nothing (or does not exist).
    """
    data = reader.get_metrics_data()
    if data is None:
        return []
    found: list[Any] = []
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == name:
                    found.extend(metric.data.data_points)
    return found


def _metric_names(reader: InMemoryMetricReader) -> set[str]:
    """Names of every metric the reader can currently collect."""
    data = reader.get_metrics_data()
    if data is None:
        return set()
    return {
        metric.name
        for resource_metric in data.resource_metrics
        for scope_metric in resource_metric.scope_metrics
        for metric in scope_metric.metrics
    }


def _point_for(points: list[Any], **attributes: Any) -> Any:
    """The single point whose attributes match `attributes` exactly."""
    matches = [
        point for point in points if dict(point.attributes) == attributes
    ]
    assert len(matches) == 1, (
        f"expected exactly one point with {attributes}, "
        f"got {[dict(p.attributes) for p in points]}"
    )
    return matches[0]


# ---------------------------------------------------------------------------
# Terminal job outcomes — counter + histogram
# ---------------------------------------------------------------------------


class TestJobTerminalMetrics:
    def test_success_records_counter_and_histogram(
        self, reader: InMemoryMetricReader
    ) -> None:
        metrics_module.record_job_terminal(
            status="succeeded", error_type=None, duration_sec=42.5
        )

        counted = _point_for(
            _points(reader, "research_jobs_total"),
            status="succeeded",
            error_type="none",
        )
        assert counted.value == 1

        timed = _point_for(
            _points(reader, "research_job_duration_seconds"),
            status="succeeded",
        )
        assert timed.count == 1
        assert timed.sum == pytest.approx(42.5)

    def test_failure_carries_error_type_attribute(
        self, reader: InMemoryMetricReader
    ) -> None:
        """The attribute that turns "jobs are failing" into "why"."""
        metrics_module.record_job_terminal(
            status="failed", error_type="timeout", duration_sec=901.0
        )
        metrics_module.record_job_terminal(
            status="failed", error_type="cost_budget_exceeded", duration_sec=3.0
        )

        points = _points(reader, "research_jobs_total")
        assert _point_for(points, status="failed", error_type="timeout").value == 1
        assert (
            _point_for(
                points, status="failed", error_type="cost_budget_exceeded"
            ).value
            == 1
        )
        # Both failures share the histogram series — the duration
        # question is "how long do failures take", not "per error type".
        timed = _point_for(
            _points(reader, "research_job_duration_seconds"), status="failed"
        )
        assert timed.count == 2

    def test_counter_accumulates_across_jobs(
        self, reader: InMemoryMetricReader
    ) -> None:
        for _ in range(3):
            metrics_module.record_job_terminal(
                status="succeeded", error_type=None, duration_sec=1.0
            )

        counted = _point_for(
            _points(reader, "research_jobs_total"),
            status="succeeded",
            error_type="none",
        )
        assert counted.value == 3

    def test_never_started_job_counts_but_is_not_timed(
        self, reader: InMemoryMetricReader
    ) -> None:
        """`Job.elapsed_sec()` is None before `started_at` is set.

        Recording a 0.0 there would put a job that did no work in the
        fastest bucket and drag p95 down.
        """
        metrics_module.record_job_terminal(
            status="cancelled", error_type=None, duration_sec=None
        )

        assert (
            _point_for(
                _points(reader, "research_jobs_total"),
                status="cancelled",
                error_type="none",
            ).value
            == 1
        )
        assert _points(reader, "research_job_duration_seconds") == []


# ---------------------------------------------------------------------------
# LLM cost + calls, recorded from the existing cost choke point
# ---------------------------------------------------------------------------


class TestLlmUsageMetrics:
    def test_record_llm_call_records_per_model(
        self, reader: InMemoryMetricReader
    ) -> None:
        """The wiring under test is `costs.record_llm_call`, not the
        metrics helper — every LLM call site funnels through it."""
        costs_module.record_llm_call(
            "claude-haiku-4-5", input_tokens=1_000_000, output_tokens=0
        )
        costs_module.record_llm_call(
            "claude-opus-5", input_tokens=1_000_000, output_tokens=0
        )
        costs_module.record_llm_call(
            "claude-haiku-4-5", input_tokens=1_000_000, output_tokens=0
        )

        calls = _points(reader, "llm_calls_total")
        assert _point_for(calls, model="claude-haiku-4-5").value == 2
        assert _point_for(calls, model="claude-opus-5").value == 1

        spend = _points(reader, "llm_cost_usd_total")
        # Haiku input is $1/M, Opus $5/M (src/observability/costs.py).
        assert _point_for(spend, model="claude-haiku-4-5").value == pytest.approx(
            2.0
        )
        assert _point_for(spend, model="claude-opus-5").value == pytest.approx(5.0)

    def test_records_without_an_active_run(
        self, reader: InMemoryMetricReader
    ) -> None:
        """No `start_cost_tracking()` — the accumulator is absent but
        the money was still spent, so the counters must move."""
        assert costs_module.current_costs() is None

        costs_module.record_llm_call(
            "claude-sonnet-5", input_tokens=1_000_000, output_tokens=0
        )

        assert _point_for(
            _points(reader, "llm_calls_total"), model="claude-sonnet-5"
        ).value == 1


# ---------------------------------------------------------------------------
# Rate-limit rejections, recorded where the 429 is raised
# ---------------------------------------------------------------------------


class TestRateLimitRejectionMetric:
    async def test_in_memory_limiter_429_records(
        self, reader: InMemoryMetricReader
    ) -> None:
        limiter = auth_module.InMemoryRateLimiter(limit_per_hour=1)
        await limiter.check_and_record("tenant-a")

        with pytest.raises(HTTPException) as excinfo:
            await limiter.check_and_record("tenant-a")
        assert excinfo.value.status_code == 429

        assert (
            _point_for(
                _points(reader, "rate_limit_rejections_total"), backend="memory"
            ).value
            == 1
        )

    async def test_allowed_requests_record_nothing(
        self, reader: InMemoryMetricReader
    ) -> None:
        """Only rejections count — a limiter that recorded on every
        call would turn this into a request counter and the alert
        "rejections are climbing" into noise."""
        limiter = auth_module.InMemoryRateLimiter(limit_per_hour=5)
        for _ in range(5):
            await limiter.check_and_record("tenant-b")

        assert _points(reader, "rate_limit_rejections_total") == []

    def test_backend_attribute_distinguishes_limiters(
        self, reader: InMemoryMetricReader
    ) -> None:
        """Both backends go through `_raise_429`; the attribute is what
        tells "Redis limiter is rejecting" from "this worker is"."""
        for backend in ("memory", "redis", "redis"):
            with pytest.raises(HTTPException):
                auth_module._raise_429("k", 5, 60, backend=backend)

        points = _points(reader, "rate_limit_rejections_total")
        assert _point_for(points, backend="memory").value == 1
        assert _point_for(points, backend="redis").value == 2


# ---------------------------------------------------------------------------
# Observable gauges — must read the live accounting, not a copy
# ---------------------------------------------------------------------------


class TestRuntimeGauges:
    def test_gauges_reflect_live_accounting_at_collection_time(
        self, reader: InMemoryMetricReader
    ) -> None:
        live = {"active": 0, "abandoned": 0}
        metrics_module.register_runtime_gauges(
            active_jobs=lambda: live["active"],
            abandoned_node_threads=lambda: live["abandoned"],
        )

        assert _points(reader, "research_active_jobs")[0].value == 0

        # Mutate the *source*, not the metric — an observable gauge
        # that cached its value would still report 0 here.
        live["active"] = 7
        live["abandoned"] = 2

        assert _points(reader, "research_active_jobs")[0].value == 7
        assert _points(reader, "research_abandoned_node_threads")[0].value == 2

    def test_reregistration_rebinds_instead_of_duplicating(
        self, reader: InMemoryMetricReader
    ) -> None:
        """Two `create_app()`s in one process must not leave a gauge
        reading the first app's dead task set, nor register a second
        same-named instrument the SDK would then have to de-duplicate."""
        metrics_module.register_runtime_gauges(
            active_jobs=lambda: 1, abandoned_node_threads=lambda: 0
        )
        metrics_module.register_runtime_gauges(
            active_jobs=lambda: 99, abandoned_node_threads=lambda: 0
        )

        # Exactly the two gauges this module defines, created once.
        assert len(metrics_module._gauges) == 2
        points = _points(reader, "research_active_jobs")
        assert len(points) == 1
        assert points[0].value == 99

    def test_no_gauges_registered_when_disabled(
        self, disabled_metrics: None
    ) -> None:
        metrics_module.register_runtime_gauges(
            active_jobs=lambda: 5, abandoned_node_threads=lambda: 5
        )
        assert metrics_module._gauges == []
        assert metrics_module._gauge_sources == {}


# ---------------------------------------------------------------------------
# Flag-off: nothing configured, nothing recorded, nothing raised
# ---------------------------------------------------------------------------


class TestDisabled:
    def test_configure_installs_no_provider(
        self, disabled_metrics: None
    ) -> None:
        metrics_module.configure_metrics()

        assert metrics_module._provider is None
        assert metrics_module._meter is None
        assert metrics_module._instruments is None
        assert metrics_module.metrics_enabled() is False

    def test_record_helpers_are_inert(self, disabled_metrics: None) -> None:
        """The hot paths call these unconditionally; with the flag off
        they must add no instruments and must not raise."""
        metrics_module.configure_metrics()

        metrics_module.record_job_terminal(
            status="succeeded", error_type=None, duration_sec=1.0
        )
        metrics_module.record_llm_usage(model="claude-opus-5", cost_usd=1.0)
        metrics_module.record_rate_limit_rejection(backend="redis")

        assert metrics_module._instruments is None

    def test_hot_path_callers_stay_silent(
        self, disabled_metrics: None
    ) -> None:
        """Same check one level up: the real call sites, flag off."""
        metrics_module.configure_metrics()

        costs_module.record_llm_call(
            "claude-opus-5", input_tokens=10, output_tokens=10
        )
        with pytest.raises(HTTPException):
            auth_module._raise_429("k", 1, 1, backend="memory")

        assert metrics_module._instruments is None

    def test_shutdown_when_never_configured_is_a_no_op(
        self, disabled_metrics: None
    ) -> None:
        metrics_module.shutdown_metrics()
        assert metrics_module._provider is None


# ---------------------------------------------------------------------------
# The real recording sites: the runner's terminal path
# ---------------------------------------------------------------------------


class _SucceedingStub:
    """Fake compiled workflow that finishes after one node."""

    async def astream(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        yield {"planner": {"iteration": 1}}

    async def aget_state(self, config: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(
            next=(), values={"draft_report": "done", "iteration": 1}
        )


class _ExplodingStub:
    """Fake compiled workflow whose first node raises."""

    async def astream(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        raise RuntimeError("kaboom")
        yield {}  # pragma: no cover - unreachable, keeps this a generator


class TestRunnerTerminalWiring:
    """`run_job` end-to-end against the in-memory reader.

    These are the tests that would fail if the record call were ever
    lifted out of `_persist_terminal` — asserting on the helper alone
    would not notice.
    """

    async def test_succeeded_job_records_counter_and_duration(
        self, reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner_module, "settings", Settings())
        job = Job(job_id="metrics-ok", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        await run_job(job, _SucceedingStub(), store, asyncio.Semaphore(1))
        assert job.status is JobStatus.succeeded

        assert (
            _point_for(
                _points(reader, "research_jobs_total"),
                status="succeeded",
                error_type="none",
            ).value
            == 1
        )
        timed = _point_for(
            _points(reader, "research_job_duration_seconds"),
            status="succeeded",
        )
        assert timed.count == 1
        # The job really ran, so the observed duration is the job's own
        # elapsed time rather than a placeholder.
        assert timed.sum == pytest.approx(job.elapsed_sec(), abs=0.5)

    async def test_failed_job_records_its_error_type(
        self, reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner_module, "settings", Settings())
        job = Job(job_id="metrics-boom", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        await run_job(job, _ExplodingStub(), store, asyncio.Semaphore(1))
        assert job.status is JobStatus.failed
        assert job.error_type == "RuntimeError"

        assert (
            _point_for(
                _points(reader, "research_jobs_total"),
                status="failed",
                error_type="RuntimeError",
            ).value
            == 1
        )

    async def test_records_even_when_the_store_write_fails(
        self, reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A wedged store must not also make the fleet look idle.

        `_persist_terminal` absorbs store failures after retrying; the
        job still reached its terminal state, so the counter must move
        regardless.
        """
        monkeypatch.setattr(runner_module, "settings", Settings())
        job = Job(job_id="metrics-nostore", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        async def _boom(_: Job) -> None:
            raise ConnectionError("redis is down")

        monkeypatch.setattr(store, "update", _boom)
        monkeypatch.setattr(runner_module.asyncio, "sleep", _no_sleep)

        await run_job(job, _SucceedingStub(), store, asyncio.Semaphore(1))

        assert (
            _point_for(
                _points(reader, "research_jobs_total"),
                status="failed",
                error_type="ConnectionError",
            ).value
            == 1
        )


# ---------------------------------------------------------------------------
# The lifespan wiring: gauges bound to the app's live accounting
# ---------------------------------------------------------------------------


class TestLifespanWiring:
    async def test_gauges_track_the_apps_in_flight_tasks(
        self, reader: InMemoryMetricReader
    ) -> None:
        """`create_app`'s lifespan must bind `research_active_jobs` to
        the same task set `/healthz` counts, not to a copy."""
        app = create_app(
            build_workflow=lambda: _SucceedingStub(),
            store=InMemoryJobStore(),
            max_concurrent_jobs=2,
        )
        async with LifespanManager(app):
            assert _points(reader, "research_active_jobs")[0].value == 0

            gate: asyncio.Event = asyncio.Event()

            async def _parked() -> None:
                await gate.wait()

            task = asyncio.create_task(_parked())
            app.state.tasks.add(task)
            try:
                assert _points(reader, "research_active_jobs")[0].value == 1
            finally:
                gate.set()
                await task
                app.state.tasks.discard(task)

            assert _points(reader, "research_active_jobs")[0].value == 0

    async def test_shutdown_tears_the_provider_down(
        self, reader: InMemoryMetricReader
    ) -> None:
        app = create_app(
            build_workflow=lambda: _SucceedingStub(),
            store=InMemoryJobStore(),
        )
        async with LifespanManager(app):
            assert metrics_module.metrics_enabled() is True
        assert metrics_module.metrics_enabled() is False
        assert metrics_module._provider is None


# ---------------------------------------------------------------------------
# Provider lifecycle
# ---------------------------------------------------------------------------


class TestProviderLifecycle:
    def test_configure_is_idempotent(
        self, reader: InMemoryMetricReader
    ) -> None:
        instruments = metrics_module._instruments
        second_reader = InMemoryMetricReader()
        metrics_module.configure_metrics(reader=second_reader)

        # Same bundle: the second call did not rebuild the pipeline
        # under the recorded-into instruments.
        assert metrics_module._instruments is instruments
        assert _metric_names(second_reader) == set()

    def test_shutdown_disarms_recording(
        self, reader: InMemoryMetricReader
    ) -> None:
        metrics_module.record_job_terminal(
            status="succeeded", error_type=None, duration_sec=1.0
        )
        metrics_module.shutdown_metrics()

        assert metrics_module.metrics_enabled() is False
        # Recording after teardown must not raise on the way out of a
        # process that is already shutting down.
        metrics_module.record_job_terminal(
            status="failed", error_type="timeout", duration_sec=1.0
        )

    def test_exporting_reader_selected_from_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty endpoint => console, set endpoint => OTLP `/v1/metrics`
        — the same rule `tracing._make_exporter` follows for spans."""
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.sdk.metrics.export import ConsoleMetricExporter

        monkeypatch.setattr(
            metrics_module,
            "settings",
            Settings(enable_metrics=True, otel_exporter_endpoint=""),
        )
        console_reader = metrics_module._make_reader()
        assert isinstance(console_reader._exporter, ConsoleMetricExporter)

        monkeypatch.setattr(
            metrics_module,
            "settings",
            Settings(
                enable_metrics=True,
                otel_exporter_endpoint="http://collector:4318/",
            ),
        )
        otlp_reader = metrics_module._make_reader()
        assert isinstance(otlp_reader._exporter, OTLPMetricExporter)
        assert (
            otlp_reader._exporter._endpoint
            == "http://collector:4318/v1/metrics"
        )
        otlp_reader.shutdown()
        console_reader.shutdown()
