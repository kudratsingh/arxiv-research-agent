"""OpenTelemetry tracing: conventional GenAI spans, and one trace per job.

Provides `configure_tracing()` / `shutdown_tracing()` (called once at
process start and teardown), the span helpers every instrumented call
site uses, and the two functions that carry a trace across the job
queue. Uses the OTel SDK so any OTLP-compatible backend (Jaeger, Tempo,
Honeycomb, Grafana Cloud, ...) receives spans without a vendor SDK.

Off by default (`settings.enable_tracing`); when enabled with no
`otel_exporter_endpoint`, spans print to stderr via the console
exporter for local dev. Setting `otel_exporter_endpoint=http://...:4318`
switches to OTLP HTTP.

See ADR 0013 for the OTel-over-LangSmith decision and ADR 0066 for the
GenAI conventions, the trace-continuity design and the pinned
specification commit.

## What WO-A07 changed, and why it was the highest-value item

Before this rewrite, `start_as_current_span` appeared in this file and
nowhere else, `inject` / `extract` appeared nowhere in `src/` at all,
and model calls were not spans. A job was therefore *N disconnected
root spans* with the largest latency contributor missing from every one
of them, which makes "where did 400 seconds go" a question the
telemetry cannot answer at any sampling rate.

Two things fix that, and they are why this module is shaped the way it
is:

- **`inject_trace_context()` at submission, `attached_trace_context()`
  in the worker.** The API request that accepted a job and the worker
  process that later ran it are frequently not the same process — a
  redriven job is picked up by whichever worker swept it (ADR 0038) —
  so the link cannot be a ContextVar. It is a W3C `traceparent` carried
  on the job row, which is what the propagator API is for.
- **Conventional span names**, so the resulting trace is readable by
  something other than us: `invoke_workflow` for a run, `invoke_agent`
  / `plan` per graph node, `execute_tool` per retrieval call, `chat`
  per model call. The names, kinds and required attributes are
  constants in `src.observability.semconv`, read from a pinned
  specification commit.

## The two per-invocation counters

`gen_ai.invoke_agent.inference_calls` and `.tool_calls` are defined by
the conventions as "how many model calls / tool calls did *this* agent
invocation make" — precisely the process metric an agent system needs,
and one this repository previously had no way to answer. They are
collected by `_InvocationCounters`: `agent_span` binds a fresh counter
for the node's duration, `note_inference_call` (called from `src.llm`)
and `tool_span` bump it, and the node records both histograms as it
closes.

The counter is bound in a ContextVar and mutated in place, deliberately.
The reader node fans out across a thread pool (ADR 0047) and those
threads inherit a *copy of the context* — which copies the reference,
not the object — so a paper read on a worker thread still counts
against the node that spawned it. The lock is there because that same
property lets two threads bump one counter concurrently.

## Sampling

`trace_sample_ratio()` returns `settings.trace_sample_ratio`, a
validated `float | None` bounded to `[0.0, 1.0]`. `TRACE_SAMPLE_RATIO`
is still the environment variable that sets it — the field name is that
name lower-cased — so no deployment changes.

Unset means "install no sampler", which leaves the SDK's own
`OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG` handling intact: an
operator who already knows the standard variables keeps them, and one
who does not gets a single ratio to reason about.

Unlike content capture, the ratio is read *once*, at
`configure_tracing()`: a `TracerProvider` takes its sampler at
construction, so there is nothing a live re-read could change and the
value goes through `Settings` and nowhere else.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Final, TypeVar

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    Sampler,
    TraceIdRatioBased,
)

from src.config import TRACE_SAMPLE_RATIO_ENV as _TRACE_SAMPLE_RATIO_ENV
from src.config import settings
from src.observability import semconv
from src.observability.context import (
    FIELD_SERVICE,
    FIELD_VERSION,
    context_fields,
)
from src.observability.costs import current_costs
from src.observability.logging import (
    content_capture_enabled,
    get_logger,
)
from src.observability.metrics import (
    record_agent_invocation,
    record_tool_execution,
    record_workflow_invocation,
)

log = get_logger(__name__)

__all__ = [
    "TRACE_SAMPLE_RATIO_ENV",
    "agent_span",
    "attached_trace_context",
    "configure_tracing",
    "get_tracer",
    "inject_trace_context",
    "llm_span",
    "note_inference_call",
    "shutdown_tracing",
    "tool_span",
    "trace_sample_ratio",
    "traced_node",
    "traced_tool",
    "workflow_span",
]

_configured = False
_provider: TracerProvider | None = None
_TRACER_NAME = "arxiv-research-agent"

T = TypeVar("T")

#: The environment variable behind `settings.trace_sample_ratio`.
#: Re-exported from `src/config.py`, which owns the value now, because
#: this constant has been this module's public name for it since
#: ADR 0066 and the documentation refers to it.
TRACE_SAMPLE_RATIO_ENV: Final = _TRACE_SAMPLE_RATIO_ENV

# Budget for the final span flush, in milliseconds. Sized exactly like
# `metrics._SHUTDOWN_BUDGET_MS` and for the same reason: it is spent at
# the end of the ADR-0042 shutdown chain, after uvicorn's connection
# drain and possibly after the ADR-0047 node-executor join have already
# claimed most of the container's grace period. A collector that cannot
# accept an export in two seconds will not accept it in five.
_SHUTDOWN_BUDGET_MS: Final = 2_000


def _make_exporter() -> SpanExporter:
    """Return the exporter matching `settings.otel_exporter_endpoint`."""
    endpoint = settings.otel_exporter_endpoint.strip()
    if not endpoint:
        return ConsoleSpanExporter()
    return OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")


def trace_sample_ratio() -> float | None:
    """The configured head-sampling ratio, or None when unset.

    A one-line read of `settings.trace_sample_ratio`, kept as a function
    because it is this module's public name for the value and because
    reading `settings` through the module attribute is what lets a test
    monkeypatch it.

    The bounds moved with the value. This used to parse the environment
    itself and *clamp*: `TRACE_SAMPLE_RATIO=10` from an operator who
    meant 10% became 1.0 and sampled everything, and `=loads` warned
    and fell back. Both are now `ge`/`le` on the field, so either one
    is a refusal at settings load with pydantic naming the field — the
    ADR-0046 rule this repository applies to every other knob. It is a
    reversal of ADR 0066's local exception ("a typo must not be a
    process that will not boot"), and deliberately: that exception
    existed only because the value was not in `Settings`, and a
    sampling ratio silently multiplied by ten is a bill that a refusal
    at boot is not.

    Returns:
        A ratio in `[0.0, 1.0]`, or `None` when unset — which means
        "install no sampler", not "sample nothing".
    """
    return settings.trace_sample_ratio


def _make_sampler() -> Sampler | None:
    """Build the sampler for the configured ratio, or None to defer.

    `None` is not "sample nothing" — it is "pass `sampler=None` to
    `TracerProvider`", which makes the SDK read `OTEL_TRACES_SAMPLER`
    and `OTEL_TRACES_SAMPLER_ARG` itself. That is the behaviour every
    deployment had before this setting existed, so an operator already
    using the standard variables is not silently overridden.

    `ParentBased` in every case, because an unparented decision would
    let a worker re-decide sampling for a job whose submitting request
    was already sampled — which would tear apart exactly the trace
    continuity this work order exists to establish.
    """
    ratio = trace_sample_ratio()
    if ratio is None:
        return None
    if ratio >= 1.0:
        return ParentBased(ALWAYS_ON)
    if ratio <= 0.0:
        return ParentBased(ALWAYS_OFF)
    return ParentBased(TraceIdRatioBased(ratio))


def configure_tracing() -> None:
    """Initialize the global TracerProvider once.

    No-op when `settings.enable_tracing` is False or when tracing is
    already configured. Safe to call from every entry point.
    """
    global _configured, _provider
    if _configured or not settings.enable_tracing:
        return

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource, sampler=_make_sampler())

    exporter = _make_exporter()
    # Batch in production (OTLP), simple/synchronous for the console
    # exporter so `make eval` output remains ordered on stderr.
    if isinstance(exporter, ConsoleSpanExporter):
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _provider = provider
    _configured = True
    log.info(
        "tracing_configured",
        extra={
            "endpoint": settings.otel_exporter_endpoint or "console",
            "service": settings.otel_service_name,
            "sample_ratio": trace_sample_ratio(),
        },
    )


def shutdown_tracing(*, timeout_millis: int = _SHUTDOWN_BUDGET_MS) -> None:
    """Flush pending spans and tear the tracer provider down.

    The counterpart to `metrics.shutdown_metrics`, and the closure of a
    measured gap: without it the last `BatchSpanProcessor` window is
    dropped on every SIGTERM — precisely the window holding whatever the
    process was doing when it was told to stop.

    Failures are logged, never raised: losing the last export must not
    turn a clean shutdown into a crashing one. A no-op when nothing was
    configured, so a lifespan can call it unconditionally.

    Args:
        timeout_millis: Budget for the final flush. See
            `_SHUTDOWN_BUDGET_MS` for why it is as small as it is.
    """
    global _configured, _provider
    provider = _provider
    _provider = None
    _configured = False
    if provider is None:
        return
    try:
        provider.force_flush(timeout_millis=timeout_millis)
        provider.shutdown()
    except Exception:
        log.warning("tracing_shutdown_failed", exc_info=True)


def get_tracer() -> trace.Tracer:
    """Return the shared project tracer (initializes lazily)."""
    configure_tracing()
    return trace.get_tracer(_TRACER_NAME)


# ---------------------------------------------------------------------------
# Trace continuity across the job queue
# ---------------------------------------------------------------------------


def inject_trace_context() -> dict[str, str]:
    """Serialize the active trace context into a carrier for the job row.

    Called when a `Job` is constructed — that is, at submission, inside
    the request handler — so the carrier records the trace of the HTTP
    request that accepted the work.

    Returns:
        A W3C carrier (`traceparent`, plus `tracestate` when a vendor
        set one). Empty when nothing is sampled or no provider is
        configured, which is the common case in tests and CLI runs and
        is why every consumer reads an empty carrier as "no parent"
        rather than as an error.
    """
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier


@contextmanager
def attached_trace_context(carrier: Mapping[str, str] | None) -> Iterator[None]:
    """Attach the trace context a job was submitted under, for this scope.

    The other half of `inject_trace_context`, and the reason a job is
    one trace instead of N roots. The worker that runs a job is often
    not the process that accepted it, so the parent link has to survive
    Redis — which is what the W3C carrier on the job row does.

    Args:
        carrier: The stored carrier, or None/empty when the job was
            submitted with nothing sampled. Both mean "start a root span
            here", which is a no-op rather than a failure.
    """
    if not carrier:
        yield
        return
    token = otel_context.attach(extract(dict(carrier)))
    try:
        yield
    finally:
        otel_context.detach(token)


# ---------------------------------------------------------------------------
# Per-invocation counters
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _InvocationCounters:
    """Model and tool calls made during one agent invocation.

    Mutable and shared by reference across the threads a node fans out
    onto, which is what makes a per-paper read count against the reader
    node that spawned it. The lock exists for exactly that reason: `+=`
    on an attribute is load/add/store, and two reader threads finishing
    together would otherwise lose a count.
    """

    lock: threading.Lock = field(default_factory=threading.Lock)
    inference_calls: int = 0
    tool_calls: int = 0


_invocation: ContextVar[_InvocationCounters | None] = ContextVar(
    "genai_invocation_counters", default=None
)


def note_inference_call() -> None:
    """Count one model call against the enclosing agent invocation.

    Called from `src.llm`'s span wrapper for every call that reaches the
    provider, successful or not — the conventions say failed inference
    calls count, because an agent that burned four attempts did four
    inferences whatever came back.

    A no-op outside an agent span, which is what an eval judge call or
    an ad-hoc script gets.
    """
    counters = _invocation.get()
    if counters is None:
        return
    with counters.lock:
        counters.inference_calls += 1


def _note_tool_call() -> None:
    """Count one tool execution against the enclosing agent invocation."""
    counters = _invocation.get()
    if counters is None:
        return
    with counters.lock:
        counters.tool_calls += 1


# ---------------------------------------------------------------------------
# The conventional spans
# ---------------------------------------------------------------------------


def _record_error(span: trace.Span, exc: BaseException) -> None:
    """Mark a span failed the conventional way.

    `error.type` is the exception's class name, per the stable core
    conventions — the *type*, never the message, because the message is
    unbounded and frequently carries the input that caused it.
    """
    if isinstance(exc, Exception):
        span.record_exception(exc)
    span.set_attribute(semconv.ERROR_TYPE, type(exc).__name__)
    span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))


#: Context fields the span already carries by other means. `service`
#: and `version` are `Resource` attributes on every span this provider
#: emits, so repeating them per span would pay for the same fact once
#: per span instead of once per batch.
_RESOURCE_DUPLICATED_FIELDS: Final = frozenset({FIELD_SERVICE, FIELD_VERSION})


def _set_correlation_attributes(span: trace.Span) -> None:
    """Copy the ADR-0067 correlation context onto a span.

    Reuses `context_fields()` rather than reading the fields by hand,
    which is the follow-up ADR 0067 asked WO-A07 for: the log payload
    and the span attributes now derive from one function, so they
    cannot drift into two spellings of `job_id`.

    The result is that trace-to-log navigation works in both
    directions — a log line carries `trace_id` / `span_id`, and a span
    carries the `run_id` / `job_id` / `request_id` / `principal_hash`
    to query logs by.

    Unbound fields are simply absent, and `principal_hash` is a salted
    digest rather than the key id, so this adds no identifier to a span
    that the log stream does not already carry.
    """
    for name, value in context_fields().items():
        if name not in _RESOURCE_DUPLICATED_FIELDS:
            span.set_attribute(name, value)


def _telemetry_enabled() -> bool:
    """Whether either signal is on, so a wrapper is worth building.

    Read from `settings` rather than from `metrics.metrics_enabled()`
    because the graph is compiled in the API lifespan *before*
    `configure_metrics()` runs, so a live check would be False at
    exactly the moment the decision is made.
    """
    return settings.enable_tracing or settings.enable_metrics


@contextmanager
def workflow_span(
    workflow_name: str, *, conversation_id: str | None = None
) -> Iterator[trace.Span]:
    """`invoke_workflow {name}` — one span for a whole run.

    The conventions reserve `invoke_workflow` for a coordinated process
    of multiple agents or GenAI calls, and name LangGraph's
    `Graph.invoke` as an example of exactly that. It is the parent every
    node span hangs off, and — because the job's submission context is
    attached around it — the join between an API request and the work it
    caused.

    Args:
        workflow_name: `semconv.WORKFLOW_RESEARCH` or `WORKFLOW_SESSION`.
            Deliberately the same vocabulary as `job.kind` (ADR 0057),
            not a second one.
        conversation_id: The follow-up conversation this run belongs to
            (ADR 0032), which is precisely `gen_ai.conversation.id`.
    """
    if not _telemetry_enabled():
        yield trace.INVALID_SPAN
        return
    tracer = get_tracer()
    started = time.monotonic()
    error_type: str | None = None
    try:
        with tracer.start_as_current_span(
            semconv.span_name(semconv.OPERATION_INVOKE_WORKFLOW, workflow_name),
            kind=trace.SpanKind.INTERNAL,
        ) as span:
            span.set_attribute(
                semconv.GEN_AI_OPERATION_NAME, semconv.OPERATION_INVOKE_WORKFLOW
            )
            span.set_attribute(semconv.GEN_AI_WORKFLOW_NAME, workflow_name)
            if conversation_id:
                span.set_attribute(semconv.GEN_AI_CONVERSATION_ID, conversation_id)
            try:
                yield span
            except BaseException as exc:
                error_type = type(exc).__name__
                _record_error(span, exc)
                raise
    finally:
        record_workflow_invocation(
            workflow_name=workflow_name,
            duration_sec=time.monotonic() - started,
            error_type=error_type,
        )


@contextmanager
def agent_span(agent_name: str) -> Iterator[trace.Span]:
    """`invoke_agent {name}` — or `plan {name}` for the planner.

    One span per graph node, with a fresh `_InvocationCounters` bound for
    its duration so the two conventional per-invocation histograms can be
    recorded as it closes.

    Args:
        agent_name: The graph node's name, which is also
            `gen_ai.agent.name`. Bounded: node names are literals in
            `src/graph/`, never caller input.
    """
    operation = semconv.operation_for_agent(agent_name)
    if not _telemetry_enabled():
        yield trace.INVALID_SPAN
        return
    tracer = get_tracer()
    counters = _InvocationCounters()
    scope = _invocation.set(counters)
    started = time.monotonic()
    error_type: str | None = None
    try:
        with tracer.start_as_current_span(
            semconv.span_name(operation, agent_name),
            kind=trace.SpanKind.INTERNAL,
        ) as span:
            span.set_attribute(semconv.GEN_AI_OPERATION_NAME, operation)
            span.set_attribute(semconv.GEN_AI_AGENT_NAME, agent_name)
            try:
                yield span
            except BaseException as exc:
                error_type = type(exc).__name__
                _record_error(span, exc)
                raise
    finally:
        _invocation.reset(scope)
        with counters.lock:
            inference_calls = counters.inference_calls
            tool_calls = counters.tool_calls
        record_agent_invocation(
            agent_name=agent_name,
            duration_sec=time.monotonic() - started,
            inference_calls=inference_calls,
            tool_calls=tool_calls,
            error_type=error_type,
        )


@contextmanager
def tool_span(tool_name: str, *, tool_type: str) -> Iterator[trace.Span]:
    """`execute_tool {name}` — one arXiv / S2 / PDF / embedding call.

    The conventions are explicit that application developers should
    instrument the tool calls their own code makes rather than waiting
    for a framework to cover them; these call sites are that.

    Opening the span is also what makes the call countable: it bumps the
    enclosing agent invocation's `tool_calls`, so
    `gen_ai.invoke_agent.tool_calls` can never disagree with the number
    of `execute_tool` spans under that node.

    Args:
        tool_name: A `semconv.TOOL_*` constant. Never a caller-supplied
            string — that is what bounds the metric's cardinality.
        tool_type: `semconv.TOOL_TYPE_EXTENSION` for a tool that calls an
            external API, `TOOL_TYPE_DATASTORE` for one that queries data
            for retrieval.
    """
    if not _telemetry_enabled():
        yield trace.INVALID_SPAN
        return
    _note_tool_call()
    tracer = get_tracer()
    started = time.monotonic()
    error_type: str | None = None
    try:
        with tracer.start_as_current_span(
            semconv.span_name(semconv.OPERATION_EXECUTE_TOOL, tool_name),
            kind=trace.SpanKind.INTERNAL,
        ) as span:
            span.set_attribute(
                semconv.GEN_AI_OPERATION_NAME, semconv.OPERATION_EXECUTE_TOOL
            )
            span.set_attribute(semconv.GEN_AI_TOOL_NAME, tool_name)
            span.set_attribute(semconv.GEN_AI_TOOL_TYPE, tool_type)
            try:
                yield span
            except BaseException as exc:
                error_type = type(exc).__name__
                _record_error(span, exc)
                raise
    finally:
        record_tool_execution(
            tool_name=tool_name,
            duration_sec=time.monotonic() - started,
            error_type=error_type,
        )


def traced_tool(
    tool_name: str, *, tool_type: str
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator form of `tool_span`, for a tool module's entry point.

    Used where the tool function itself is the natural boundary. The
    context-manager form is used instead where the tool module belongs
    to another work order this wave and must not be edited — ADR 0066
    records which one, and why the two forms coexist for now.

    Args:
        tool_name: A `semconv.TOOL_*` constant.
        tool_type: A `semconv.TOOL_TYPE_*` constant.
    """

    def decorate(fn: Callable[..., T]) -> Callable[..., T]:
        def wrapped(*args: Any, **kwargs: Any) -> T:
            with tool_span(tool_name, tool_type=tool_type):
                return fn(*args, **kwargs)

        wrapped.__name__ = fn.__name__
        wrapped.__qualname__ = fn.__qualname__
        wrapped.__doc__ = fn.__doc__
        wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapped

    return decorate


@contextmanager
def llm_span(
    *,
    model: str,
    max_tokens: int,
    temperature: float | None,
    server_address: str,
) -> Iterator[trace.Span]:
    """`chat {model}` — the span the largest latency contributor lacked.

    CLIENT kind, because the call leaves the process. This is the one
    span type on which the conventions require `gen_ai.provider.name`,
    and the one place this repository sets it.

    Response and usage attributes are set by the caller after the call
    returns, because they do not exist until then; the caller also calls
    `note_inference_call`. Both live in `src.llm`, wrapped *around*
    `record_llm_call` so cost accounting stays single-sourced (ADR 0066).

    Args:
        model: `gen_ai.request.model` — the model asked for, which is not
            necessarily the one that answered.
        max_tokens: `gen_ai.request.max_tokens`.
        temperature: `gen_ai.request.temperature`, or `None` when the
            request carried no temperature at all.  ADR 0077 resolves a
            per-model request profile and drops sampling parameters for
            a model that rejects them, and the conventions want the
            attribute *absent* rather than reporting a value that was
            never sent — a span that claims `temperature=0.3` on a
            request which omitted it is a false statement about the
            request, and false is worse than missing when the attribute
            exists to explain a model's behaviour.  Closes ADR 0077's
            first follow-up (P0-WO08, ADR 0083).
        server_address: `server.address` — the provider host, so a trace
            shows which endpoint was slow.
    """
    if not _telemetry_enabled():
        yield trace.INVALID_SPAN
        return
    tracer = get_tracer()
    with tracer.start_as_current_span(
        semconv.span_name(semconv.OPERATION_CHAT, model),
        kind=trace.SpanKind.CLIENT,
    ) as span:
        span.set_attribute(semconv.GEN_AI_OPERATION_NAME, semconv.OPERATION_CHAT)
        span.set_attribute(semconv.GEN_AI_PROVIDER_NAME, semconv.PROVIDER_ANTHROPIC)
        span.set_attribute(semconv.GEN_AI_REQUEST_MODEL, model)
        span.set_attribute(semconv.GEN_AI_REQUEST_MAX_TOKENS, max_tokens)
        if temperature is not None:
            span.set_attribute(semconv.GEN_AI_REQUEST_TEMPERATURE, temperature)
        span.set_attribute(semconv.SERVER_ADDRESS, server_address)
        try:
            yield span
        except BaseException as exc:
            _record_error(span, exc)
            raise


# ---------------------------------------------------------------------------
# The graph node wrapper
# ---------------------------------------------------------------------------


def traced_node(name: str, fn: Callable[..., T]) -> Callable[..., T]:
    """Wrap an agent-node function so its execution becomes an agent span.

    Preserves the `state -> partial_state` shape LangGraph nodes use, and
    is registered by both graph builders (`src/graph/workflow.py`,
    `src/graph/session_workflow.py`).

    The span is the conventional `invoke_agent {node}` — `plan {planner}`
    for the planner — and the node's LLM and tool calls become its
    children rather than roots of their own.

    The pre-WO-A07 attributes (`run_id`, `state.iteration`,
    `result.*_count`, `llm.cost_usd` and friends) are **kept**. They are
    what the existing dashboards read, cost has no conventional attribute
    at all (`02-STANDARDS.md` §1.3), and the per-node result counts are
    this repository's own product signal rather than anything the
    conventions describe. `run_id` now arrives through
    `_set_correlation_attributes`, which brings the rest of the ADR-0067
    context with it — so a span can be queried back to its log lines.

    One attribute is deliberately *not* kept unconditionally.
    `state.query` carried the user's raw research query onto every node
    span; that is user content, the conventions class content capture as
    opt-in, and Phase A keeps it off. It is now emitted only when
    `content_capture_enabled()` says so — the same switch the log layer
    already honours, so an operator makes the content decision once
    (ADR 0066).

    Falls back to a no-op wrapper when both telemetry signals are off, so
    agents don't pay the tracer/metric overhead in the common case.
    """
    if not _telemetry_enabled():
        return fn

    def wrapped(state: dict[str, Any]) -> T:
        with agent_span(name) as span:
            costs_before = current_costs()
            before_snapshot = costs_before.as_dict() if costs_before is not None else None
            _set_correlation_attributes(span)
            if isinstance(state, dict):
                iteration = state.get("iteration")
                if iteration is not None:
                    span.set_attribute("state.iteration", str(iteration))
                query = state.get("query")
                if query is not None and content_capture_enabled():
                    span.set_attribute("state.query", str(query))
            result = fn(state)

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
