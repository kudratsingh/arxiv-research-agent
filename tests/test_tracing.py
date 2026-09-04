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
from src.observability import costs as costs_module
from src.observability import tracing as tracing_module
from src.observability.costs import RunCosts, current_costs
from src.observability.tracing import traced_node

pytestmark = pytest.mark.unit


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
    def test_creates_conventionally_named_span(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        """`plan {agent}` for the planner, not the bare node name.

        The conventions say `plan` SHOULD only be reported when the
        instrumentation can reliably tell planning from generic
        reasoning. Here it can: planning is a named node of the graph.
        """

        def agent(state: dict) -> dict:
            return {"papers": []}

        wrapped = traced_node("planner", agent)
        wrapped({"query": "q", "iteration": 0})

        spans = in_memory_tracer.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "plan planner"
        assert spans[0].attributes["gen_ai.operation.name"] == "plan"
        assert spans[0].attributes["gen_ai.agent.name"] == "planner"

    def test_every_other_node_is_an_invoke_agent_span(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        traced_node("search", lambda s: {})({"query": "q"})

        span = in_memory_tracer.get_finished_spans()[0]
        assert span.name == "invoke_agent search"
        assert span.attributes["gen_ai.operation.name"] == "invoke_agent"
        assert span.attributes["gen_ai.agent.name"] == "search"

    def test_records_state_attributes(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        def agent(state: dict) -> dict:
            return {}

        wrapped = traced_node("planner", agent)
        wrapped({"query": "hallu?", "iteration": 2})

        span = in_memory_tracer.get_finished_spans()[0]
        assert span.attributes["state.iteration"] == "2"

    def test_the_query_is_not_captured_by_default(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        """The research query is user content, and content stays off.

        It used to ride on every node span as `state.query`. The GenAI
        conventions class content capture as opt-in and Phase A does not
        opt in, so the span carries the shape of the work and not the
        text of it (ADR 0066).
        """
        traced_node("planner", lambda s: {})({"query": "a private query"})

        span = in_memory_tracer.get_finished_spans()[0]
        assert "state.query" not in span.attributes

    def test_the_query_is_captured_when_capture_is_opted_into(
        self,
        in_memory_tracer: InMemorySpanExporter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One switch, honoured by logs and spans alike.

        The variable is the only opt-in the conventions define; an
        operator who has made the content decision once should not have
        to discover a second switch to make it stick for traces.
        """
        monkeypatch.setenv(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true"
        )
        traced_node("planner", lambda s: {})({"query": "hallu?"})

        span = in_memory_tracer.get_finished_spans()[0]
        assert span.attributes["state.query"] == "hallu?"

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

    def test_records_cumulative_and_delta_llm_costs(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        accumulator = RunCosts()
        accumulator.record(
            "claude-haiku-4-5",
            input_tokens=10,
            output_tokens=2,
            cost_usd=0.03,
        )
        token = costs_module._current_costs.set(accumulator)

        def agent(state: dict) -> dict:
            costs = current_costs()
            assert costs is not None
            costs.record(
                "claude-haiku-4-5",
                input_tokens=20,
                output_tokens=4,
                cost_usd=0.07,
            )
            return {}

        try:
            traced_node("tutor", agent)({"query": "q"})
        finally:
            costs_module._current_costs.reset(token)

        attrs = in_memory_tracer.get_finished_spans()[0].attributes
        assert attrs["llm.cost_usd"] == pytest.approx(0.10)
        assert attrs["llm.cost_delta_usd"] == pytest.approx(0.07)
        assert attrs["llm.call_count"] == 2
        assert attrs["llm.call_delta"] == 1

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
