"""OpenTelemetry tracing setup.

Provides `configure_tracing()` (called once at process start) and
`traced_node(name, fn)` (wraps an agent function with a span). Uses the
OTel SDK so any OTLP-compatible backend (Jaeger, Tempo, Honeycomb,
Grafana Cloud, ...) can receive spans without a vendor-specific SDK.

Off by default (`settings.enable_tracing`); when enabled with no
`otel_exporter_endpoint`, spans print to stderr via the console
exporter for local dev. Setting `otel_exporter_endpoint=http://...:4318`
switches to OTLP HTTP.

See ADR 0013 for the OTel-over-LangSmith decision.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)

from src.config import settings
from src.observability.costs import current_costs
from src.observability.logging import current_run_id, get_logger

log = get_logger(__name__)

_configured = False
_TRACER_NAME = "arxiv-research-agent"

T = TypeVar("T")


def _make_exporter() -> SpanExporter:
    """Return the exporter matching `settings.otel_exporter_endpoint`."""
    endpoint = settings.otel_exporter_endpoint.strip()
    if not endpoint:
        return ConsoleSpanExporter()
    return OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")


def configure_tracing() -> None:
    """Initialize the global TracerProvider once.

    No-op when `settings.enable_tracing` is False or when tracing is
    already configured. Safe to call from every entry point.
    """
    global _configured
    if _configured or not settings.enable_tracing:
        return

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    exporter = _make_exporter()
    # Batch in production (OTLP), simple/synchronous for the console
    # exporter so `make eval` output remains ordered on stderr.
    if isinstance(exporter, ConsoleSpanExporter):
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _configured = True
    log.info(
        "tracing_configured",
        extra={
            "endpoint": settings.otel_exporter_endpoint or "console",
            "service": settings.otel_service_name,
        },
    )


def get_tracer() -> trace.Tracer:
    """Return the shared project tracer (initializes lazily)."""
    configure_tracing()
    return trace.get_tracer(_TRACER_NAME)


def traced_node(
    name: str, fn: Callable[..., T]
) -> Callable[..., T]:
    """Wrap an agent-node function so its execution becomes a span.

    Preserves the `state -> partial_state` shape LangGraph nodes use.
    Records `run_id`, `query`, `iteration`, and any counts observable
    from the returned partial state as span attributes.

    Falls back to a no-op wrapper when tracing is disabled so agents
    don't pay the tracer/API-call overhead in the common case.
    """
    if not settings.enable_tracing:
        return fn

    tracer = get_tracer()

    def wrapped(state: dict[str, Any]) -> T:
        with tracer.start_as_current_span(name) as span:
            costs_before = current_costs()
            before_snapshot = costs_before.as_dict() if costs_before is not None else None
            span.set_attribute("run_id", current_run_id())
            if isinstance(state, dict):
                for key in ("query", "iteration"):
                    value = state.get(key)
                    if value is not None:
                        span.set_attribute(f"state.{key}", str(value))
            try:
                result = fn(state)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                raise

            if isinstance(result, dict):
                for key in ("papers", "paper_analyses", "citations"):
                    value = result.get(key)
                    if isinstance(value, list):
                        span.set_attribute(f"result.{key}_count", len(value))
                score = result.get("quality_score")
                if isinstance(score, (int, float)):
                    span.set_attribute("result.quality_score", float(score))
            costs_after = current_costs()
            if costs_after is not None:
                after_snapshot = costs_after.as_dict()
                after_usd = float(after_snapshot["total_cost_usd"])
                after_calls = int(after_snapshot["call_count"])
                before_usd = (
                    float(before_snapshot["total_cost_usd"]) if before_snapshot is not None else 0.0
                )
                before_calls = (
                    int(before_snapshot["call_count"]) if before_snapshot is not None else 0
                )
                span.set_attribute("llm.cost_usd", after_usd)
                span.set_attribute("llm.cost_delta_usd", round(after_usd - before_usd, 6))
                span.set_attribute("llm.call_count", after_calls)
                span.set_attribute("llm.call_delta", after_calls - before_calls)
            return result

    return wrapped
