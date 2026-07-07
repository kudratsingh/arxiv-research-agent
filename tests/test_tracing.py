"""Unit tests for the OpenTelemetry tracing setup.

Uses the SDK's `InMemorySpanExporter` so we can assert on span
attributes, names, and status without running an OTLP endpoint.
"""

import pytest
from opentelemetry import trace as ot_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from src.config import Settings
from src.observability import tracing as tracing_module
from src.observability.tracing import traced_node


@pytest.fixture
def in_memory_tracer(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """Install a fresh in-memory tracer for this test only.

    Forces `enable_tracing=True`, swaps the SDK's global provider for
    one that exports to memory. OpenTelemetry only allows the global
    provider to be set once per process, so we bypass that guard by
    resetting the private `_TRACER_PROVIDER_SET_ONCE` flag — safer than
    poking at other internal state and avoids leaking a real provider
    across tests.
    """
    monkeypatch.setattr(
        tracing_module,
        "settings",
        Settings(enable_tracing=True, otel_exporter_endpoint=""),
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # OTel guards `set_tracer_provider` behind a "set once" flag; reset it
    # so successive tests install their own providers.
    trace_api = ot_trace
    monkeypatch.setattr(trace_api, "_TRACER_PROVIDER_SET_ONCE", trace_api._TRACER_PROVIDER_SET_ONCE.__class__(), raising=False)
    monkeypatch.setattr(trace_api, "_TRACER_PROVIDER", None, raising=False)
    trace_api.set_tracer_provider(provider)

    # Mark configured so the code path skips its own provider install.
    monkeypatch.setattr(tracing_module, "_configured", True)

    yield exporter

    exporter.clear()


class TestTracedNodeDisabled:
    def test_returns_original_fn_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tracing_module, "settings", Settings(enable_tracing=False)
        )

        def agent(state: dict) -> dict:
            return {"papers": [1, 2, 3]}

        wrapped = traced_node("planner", agent)
        # No wrapping cost paid when disabled — same object.
        assert wrapped is agent


class TestTracedNodeEnabled:
    def test_creates_span_named_after_node(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        def agent(state: dict) -> dict:
            return {"papers": []}

        wrapped = traced_node("planner", agent)
        wrapped({"query": "q", "iteration": 0})

        spans = in_memory_tracer.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "planner"

    def test_records_state_attributes(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        def agent(state: dict) -> dict:
            return {}

        wrapped = traced_node("planner", agent)
        wrapped({"query": "hallu?", "iteration": 2})

        span = in_memory_tracer.get_finished_spans()[0]
        assert span.attributes["state.query"] == "hallu?"
        assert span.attributes["state.iteration"] == "2"

    def test_records_result_counts(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        def agent(state: dict) -> dict:
            return {
                "papers": [1, 2, 3],
                "paper_analyses": [1],
                "citations": [1, 2],
                "quality_score": 0.72,
            }

        wrapped = traced_node("search", agent)
        wrapped({"query": "q"})

        attrs = in_memory_tracer.get_finished_spans()[0].attributes
        assert attrs["result.papers_count"] == 3
        assert attrs["result.paper_analyses_count"] == 1
        assert attrs["result.citations_count"] == 2
        assert attrs["result.quality_score"] == pytest.approx(0.72)

    def test_records_run_id_from_context(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        from src.observability import bind_run_id, reset_run_id

        token = bind_run_id("rid-observed")
        try:
            wrapped = traced_node("reader", lambda s: {})
            wrapped({"query": "q"})
        finally:
            reset_run_id(token)

        span = in_memory_tracer.get_finished_spans()[0]
        assert span.attributes["run_id"] == "rid-observed"

    def test_exception_recorded_and_reraised(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        def agent(state: dict) -> dict:
            raise RuntimeError("kaboom")

        wrapped = traced_node("critic", agent)
        with pytest.raises(RuntimeError, match="kaboom"):
            wrapped({"query": "q"})

        span = in_memory_tracer.get_finished_spans()[0]
        # Span status set to ERROR + exception event recorded.
        assert span.status.status_code == ot_trace.StatusCode.ERROR
        assert any(
            "kaboom" in (event.attributes or {}).get(
                "exception.message", ""
            )
            for event in span.events
        )


class TestConfigureTracing:
    def test_no_op_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tracing_module, "settings", Settings(enable_tracing=False)
        )
        monkeypatch.setattr(tracing_module, "_configured", False)
        # Should not touch the global provider.
        tracing_module.configure_tracing()
        assert tracing_module._configured is False

    def test_idempotent_when_already_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tracing_module, "settings", Settings(enable_tracing=True)
        )
        monkeypatch.setattr(tracing_module, "_configured", True)
        # Second call — should be a no-op, no exception.
        tracing_module.configure_tracing()
