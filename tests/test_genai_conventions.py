"""The OpenTelemetry GenAI conventions, asserted literally (ADR 0066).

Three things this file exists to prove, and one it exists to prevent.

**Prove 1 — the names are the standard's names.** Every conventional
attribute and metric name is asserted as a *literal string* here, not
by referencing the constant that produces it. A test that says
`assert span.attributes[GEN_AI_OPERATION_NAME] == ...` passes whatever
`GEN_AI_OPERATION_NAME` happens to spell, which is exactly the failure
mode a name-adoption work order has to rule out. Reading these
assertions should be enough to check the implementation against
`model/gen-ai/*.yaml` at the pinned commit without opening any source.

**Prove 2 — a job is one trace.** The measured baseline was "N
disconnected root spans"; `TestTraceContinuity` drives a real
`run_job` and asserts that the request that submitted the job, the
workflow, the node and the model call all carry one trace id and nest
in that order.

**Prove 3 — no attribute is unbounded.** Every metric attribute value
this system emits comes from a closed set: a job kind, a status, an
error type, a model id, a node name, a tool name. `TestCardinality`
drives a job whose query, id and content are deliberately distinctive
and asserts none of that text reaches a metric attribute.

**Prevent — `gen_ai.system`.** The attribute was renamed to
`gen_ai.provider.name` and the old spelling is the single most likely
stale string to appear in an implementation written from memory. A
test greps `src/` for it, because the cost of that mistake is
telemetry that looks right and parses nowhere.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry import trace as ot_trace
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

import src.observability.semconv as semconv
from src.api import runner as runner_module
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.config import Settings
from src.observability import metrics as metrics_module
from src.observability import tracing as tracing_module

pytestmark = pytest.mark.unit

_SRC = Path(__file__).resolve().parents[1] / "src"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    """A fresh in-memory tracer provider for this test only.

    Same idiom as `test_tracing.py`: OTel guards `set_tracer_provider`
    behind a set-once flag, so the flag is reset rather than any other
    internal state being poked, and the module is marked configured so
    the code path installs nothing of its own.
    """
    monkeypatch.setattr(
        tracing_module,
        "settings",
        Settings(enable_tracing=True, otel_exporter_endpoint=""),
    )
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        ot_trace,
        "_TRACER_PROVIDER_SET_ONCE",
        ot_trace._TRACER_PROVIDER_SET_ONCE.__class__(),
        raising=False,
    )
    monkeypatch.setattr(ot_trace, "_TRACER_PROVIDER", None, raising=False)
    ot_trace.set_tracer_provider(provider)
    monkeypatch.setattr(tracing_module, "_configured", True)
    yield exporter
    exporter.clear()


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryMetricReader]:
    """Configure the metrics module against an in-memory reader."""
    metrics_module.shutdown_metrics()
    monkeypatch.setattr(
        metrics_module,
        "settings",
        Settings(enable_metrics=True, otel_exporter_endpoint=""),
    )
    metric_reader = InMemoryMetricReader()
    metrics_module.configure_metrics(reader=metric_reader)
    yield metric_reader
    metrics_module.shutdown_metrics()


def _named(exporter: InMemorySpanExporter, name: str) -> ReadableSpan:
    """The single finished span called `name`."""
    matches = [s for s in exporter.get_finished_spans() if s.name == name]
    assert len(matches) == 1, (
        f"expected one span named {name!r}, got "
        f"{[s.name for s in exporter.get_finished_spans()]}"
    )
    return matches[0]


def _points(reader: InMemoryMetricReader, name: str) -> list[Any]:
    """Every data point currently aggregated for metric `name`."""
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


def _all_attribute_values(reader: InMemoryMetricReader) -> set[str]:
    """Every string attribute value across every collected data point."""
    data = reader.get_metrics_data()
    if data is None:
        return set()
    values: set[str] = set()
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                for point in metric.data.data_points:
                    for value in dict(point.attributes or {}).values():
                        if isinstance(value, str):
                            values.add(value)
    return values


# ---------------------------------------------------------------------------
# The names themselves
# ---------------------------------------------------------------------------


class TestTheNamesAreTheStandardsNames:
    """Literal assertions against the pinned specification commit.

    Read alongside `open-telemetry/semantic-conventions-genai` at
    `semconv.SEMCONV_GENAI_COMMIT`: `model/gen-ai/registry.yaml` for
    the attribute keys and enum members, `metrics.yaml` for the metric
    names and units.
    """

    def test_the_provider_attribute_is_not_the_renamed_one(self) -> None:
        """`gen_ai.provider.name`, never `gen_ai.system`."""
        assert semconv.GEN_AI_PROVIDER_NAME == "gen_ai.provider.name"

    def test_gen_ai_system_is_never_emitted_anywhere_in_src(self) -> None:
        """The stale name must not exist as a string literal in `src/`.

        Asserted by scanning the tree rather than by inspecting one
        module, because the failure this guards against is somebody
        adding a *second* instrumentation site from memory long after
        `semconv.py` got it right.

        Matched as a quoted literal specifically: prose explaining that
        the attribute *was* renamed is exactly what should stay in the
        tree, and a bare substring scan would forbid documenting the
        very mistake this test exists to prevent.
        """
        quoted = re.compile(r"""['"]gen_ai\.system['"]""")
        offenders = [
            str(path.relative_to(_SRC.parent))
            for path in _SRC.rglob("*.py")
            if quoted.search(path.read_text(encoding="utf-8"))
        ]
        assert offenders == [], (
            f"`gen_ai.system` was renamed to `gen_ai.provider.name`; "
            f"found in {offenders}"
        )

    def test_span_attribute_names(self) -> None:
        assert semconv.GEN_AI_OPERATION_NAME == "gen_ai.operation.name"
        assert semconv.GEN_AI_REQUEST_MODEL == "gen_ai.request.model"
        assert semconv.GEN_AI_REQUEST_MAX_TOKENS == "gen_ai.request.max_tokens"
        assert semconv.GEN_AI_REQUEST_TEMPERATURE == "gen_ai.request.temperature"
        assert semconv.GEN_AI_RESPONSE_ID == "gen_ai.response.id"
        assert semconv.GEN_AI_RESPONSE_MODEL == "gen_ai.response.model"
        assert (
            semconv.GEN_AI_RESPONSE_FINISH_REASONS
            == "gen_ai.response.finish_reasons"
        )
        assert semconv.GEN_AI_USAGE_INPUT_TOKENS == "gen_ai.usage.input_tokens"
        assert semconv.GEN_AI_USAGE_OUTPUT_TOKENS == "gen_ai.usage.output_tokens"
        assert (
            semconv.GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS
            == "gen_ai.usage.cache_read.input_tokens"
        )
        assert (
            semconv.GEN_AI_USAGE_CACHE_WRITE_INPUT_TOKENS
            == "gen_ai.usage.cache_write.input_tokens"
        )
        assert semconv.GEN_AI_AGENT_NAME == "gen_ai.agent.name"
        assert semconv.GEN_AI_TOOL_NAME == "gen_ai.tool.name"
        assert semconv.GEN_AI_TOOL_TYPE == "gen_ai.tool.type"
        assert semconv.GEN_AI_WORKFLOW_NAME == "gen_ai.workflow.name"
        assert semconv.GEN_AI_CONVERSATION_ID == "gen_ai.conversation.id"
        assert semconv.GEN_AI_TOKEN_TYPE == "gen_ai.token.type"
        # Stable core-semconv names, not GenAI ones.
        assert semconv.ERROR_TYPE == "error.type"
        assert semconv.SERVER_ADDRESS == "server.address"

    def test_metric_names_and_units(self) -> None:
        assert semconv.METRIC_CLIENT_TOKEN_USAGE == "gen_ai.client.token.usage"
        assert semconv.UNIT_TOKEN == "{token}"
        assert (
            semconv.METRIC_CLIENT_OPERATION_DURATION
            == "gen_ai.client.operation.duration"
        )
        assert semconv.METRIC_INVOKE_AGENT_DURATION == "gen_ai.invoke_agent.duration"
        assert (
            semconv.METRIC_INVOKE_AGENT_INFERENCE_CALLS
            == "gen_ai.invoke_agent.inference_calls"
        )
        assert semconv.UNIT_INFERENCE_CALL == "{inference_call}"
        assert (
            semconv.METRIC_INVOKE_AGENT_TOOL_CALLS
            == "gen_ai.invoke_agent.tool_calls"
        )
        assert semconv.UNIT_TOOL_CALL == "{tool_call}"
        assert semconv.METRIC_EXECUTE_TOOL_DURATION == "gen_ai.execute_tool.duration"
        assert (
            semconv.METRIC_INVOKE_WORKFLOW_DURATION
            == "gen_ai.invoke_workflow.duration"
        )
        # Seconds, never milliseconds: the conventions are explicit.
        assert semconv.UNIT_SECOND == "s"

    def test_enum_members(self) -> None:
        assert semconv.OPERATION_CHAT == "chat"
        assert semconv.OPERATION_INVOKE_AGENT == "invoke_agent"
        assert semconv.OPERATION_INVOKE_WORKFLOW == "invoke_workflow"
        assert semconv.OPERATION_EXECUTE_TOOL == "execute_tool"
        assert semconv.OPERATION_PLAN == "plan"
        assert semconv.PROVIDER_ANTHROPIC == "anthropic"
        assert semconv.TOKEN_TYPE_INPUT == "input"
        assert semconv.TOKEN_TYPE_OUTPUT == "output"

    def test_every_operation_used_is_a_member_of_the_enum(self) -> None:
        """The five this repository emits are members, not inventions."""
        used = {
            semconv.OPERATION_CHAT,
            semconv.OPERATION_INVOKE_AGENT,
            semconv.OPERATION_INVOKE_WORKFLOW,
            semconv.OPERATION_EXECUTE_TOOL,
            semconv.OPERATION_PLAN,
        }
        assert used <= semconv.OPERATION_NAMES

    def test_the_pinned_commit_is_a_commit(self) -> None:
        """There is no tagged release to pin, so a SHA is the pin.

        The GenAI conventions left the core repository at v1.42.0 for
        `semantic-conventions-genai`, which has no tags — which is why
        this is 40 hex characters rather than a version and why there
        is no versioned schema URL anywhere in the tree.
        """
        assert semconv.SEMCONV_GENAI_REPO == (
            "open-telemetry/semantic-conventions-genai"
        )
        assert re.fullmatch(r"[0-9a-f]{40}", semconv.SEMCONV_GENAI_COMMIT)

    def test_the_adr_pins_the_same_commit_the_code_does(self) -> None:
        """A pin recorded in prose and a pin used in code must agree."""
        adr = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "decisions"
            / "0066-genai-semantic-conventions.md"
        ).read_text(encoding="utf-8")
        assert semconv.SEMCONV_GENAI_COMMIT in adr

    def test_the_planner_is_the_only_plan_span(self) -> None:
        assert semconv.operation_for_agent("planner") == "plan"
        for node in ("search", "reader", "synthesizer", "critic", "supervisor"):
            assert semconv.operation_for_agent(node) == "invoke_agent"

    def test_span_names_follow_operation_then_identity(self) -> None:
        assert semconv.span_name("chat", "claude-sonnet-4-6") == (
            "chat claude-sonnet-4-6"
        )
        # The conventions say to fall back to the bare operation when
        # the identity is not readily available.
        assert semconv.span_name("invoke_agent", None) == "invoke_agent"


# ---------------------------------------------------------------------------
# The spans
# ---------------------------------------------------------------------------


class TestConventionalSpans:
    def test_llm_span_carries_the_required_pair_and_the_request(
        self, spans: InMemorySpanExporter
    ) -> None:
        """`chat {model}`, CLIENT, with the two required attributes.

        The inference span is the one span type on which
        `gen_ai.provider.name` is `required` in `spans.yaml`, and the
        one place this repository sets it.
        """
        with tracing_module.llm_span(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            temperature=0.3,
            server_address="api.anthropic.com",
        ):
            pass

        span = _named(spans, "chat claude-sonnet-4-6")
        assert span.kind is ot_trace.SpanKind.CLIENT
        assert span.attributes["gen_ai.operation.name"] == "chat"
        assert span.attributes["gen_ai.provider.name"] == "anthropic"
        assert span.attributes["gen_ai.request.model"] == "claude-sonnet-4-6"
        assert span.attributes["gen_ai.request.max_tokens"] == 4096
        assert span.attributes["gen_ai.request.temperature"] == pytest.approx(0.3)
        assert span.attributes["server.address"] == "api.anthropic.com"

    def test_agent_span_is_internal_and_names_the_agent(
        self, spans: InMemorySpanExporter
    ) -> None:
        with tracing_module.agent_span("reader"):
            pass

        span = _named(spans, "invoke_agent reader")
        assert span.kind is ot_trace.SpanKind.INTERNAL
        assert span.attributes["gen_ai.operation.name"] == "invoke_agent"
        assert span.attributes["gen_ai.agent.name"] == "reader"

    def test_tool_span_names_the_tool_and_its_type(
        self, spans: InMemorySpanExporter
    ) -> None:
        with tracing_module.tool_span(
            semconv.TOOL_ARXIV_SEARCH, tool_type=semconv.TOOL_TYPE_EXTENSION
        ):
            pass

        span = _named(spans, "execute_tool arxiv_search")
        assert span.kind is ot_trace.SpanKind.INTERNAL
        assert span.attributes["gen_ai.operation.name"] == "execute_tool"
        assert span.attributes["gen_ai.tool.name"] == "arxiv_search"
        assert span.attributes["gen_ai.tool.type"] == "extension"

    def test_workflow_span_carries_the_conversation_id(
        self, spans: InMemorySpanExporter
    ) -> None:
        """ADR 0032's conversation is `gen_ai.conversation.id` exactly.

        A follow-up thread is a conversation in the conventions' sense,
        so the repository's existing id needs no second name.
        """
        with tracing_module.workflow_span("research", conversation_id="conv-9"):
            pass

        span = _named(spans, "invoke_workflow research")
        assert span.kind is ot_trace.SpanKind.INTERNAL
        assert span.attributes["gen_ai.operation.name"] == "invoke_workflow"
        assert span.attributes["gen_ai.workflow.name"] == "research"
        assert span.attributes["gen_ai.conversation.id"] == "conv-9"

    def test_a_failing_span_records_the_error_type_not_the_message(
        self, spans: InMemorySpanExporter
    ) -> None:
        """`error.type` is the class name; the message is unbounded.

        A message routinely carries the input that caused it, which is
        exactly what must not become a span attribute.
        """
        with (
            pytest.raises(RuntimeError),
            tracing_module.tool_span(
                semconv.TOOL_PDF_PARSE, tool_type=semconv.TOOL_TYPE_EXTENSION
            ),
        ):
            raise RuntimeError("the secret query text")

        span = _named(spans, "execute_tool pdf_parse")
        assert span.attributes["error.type"] == "RuntimeError"
        assert "the secret query text" not in str(dict(span.attributes))

    def test_a_node_span_carries_the_correlation_context(
        self, spans: InMemorySpanExporter
    ) -> None:
        """Trace-to-log navigation, in the other direction.

        A log line already carries `trace_id` / `span_id` (ADR 0067).
        This is the return trip: the span carries the identifiers to
        query logs by, and it gets them from `context_fields()` — the
        same function the formatter uses — so the two cannot drift into
        two spellings of `job_id`.
        """
        from src.observability import bind_context, hash_principal, reset_context

        token = bind_context(
            run_id="run-7",
            job_id="job-7",
            request_id="req-7",
            job_kind="research",
            principal_hash=hash_principal("pilot-key"),
            worker_id="worker-7",
        )
        try:
            tracing_module.traced_node("reader", lambda s: {})({})
        finally:
            reset_context(token)

        attributes = _named(spans, "invoke_agent reader").attributes
        assert attributes["run_id"] == "run-7"
        assert attributes["job_id"] == "job-7"
        assert attributes["request_id"] == "req-7"
        assert attributes["job_kind"] == "research"
        assert attributes["worker_id"] == "worker-7"
        # A salted digest, never the key id — the same rule the log
        # contract enforces, for the same reason.
        assert attributes["principal_hash"] != "pilot-key"
        # `service` / `version` are Resource attributes on every span
        # this provider emits; repeating them per span would pay for
        # the same fact once per span instead of once per batch.
        assert "service" not in attributes
        assert "version" not in attributes

    def test_a_tool_call_nests_under_the_agent_that_made_it(
        self, spans: InMemorySpanExporter
    ) -> None:
        with (
            tracing_module.agent_span("search"),
            tracing_module.tool_span(
                semconv.TOOL_ARXIV_SEARCH,
                tool_type=semconv.TOOL_TYPE_EXTENSION,
            ),
        ):
            pass

        agent = _named(spans, "invoke_agent search")
        tool = _named(spans, "execute_tool arxiv_search")
        assert tool.parent is not None
        assert tool.parent.span_id == agent.context.span_id


# ---------------------------------------------------------------------------
# The metrics
# ---------------------------------------------------------------------------


class TestConventionalMetrics:
    def test_the_client_metrics_are_emitted_under_their_exact_names(
        self, reader: InMemoryMetricReader
    ) -> None:
        metrics_module.record_genai_client_call(
            request_model="claude-sonnet-4-6",
            response_model="claude-sonnet-4-6",
            input_tokens=120,
            output_tokens=40,
            duration_sec=1.5,
            error_type=None,
        )

        assert "gen_ai.client.token.usage" in _metric_names(reader)
        assert "gen_ai.client.operation.duration" in _metric_names(reader)

        points = {
            dict(p.attributes)["gen_ai.token.type"]: p
            for p in _points(reader, "gen_ai.client.token.usage")
        }
        assert points["input"].sum == 120
        assert points["output"].sum == 40
        attributes = dict(points["input"].attributes)
        assert attributes["gen_ai.provider.name"] == "anthropic"
        assert attributes["gen_ai.operation.name"] == "chat"
        assert attributes["gen_ai.request.model"] == "claude-sonnet-4-6"
        assert attributes["gen_ai.response.model"] == "claude-sonnet-4-6"

    def test_a_failed_call_is_timed_but_has_no_tokens(
        self, reader: InMemoryMetricReader
    ) -> None:
        """`usage` exists only on a 2xx body — the duration still does.

        A call that spent eight minutes exhausting retries before
        failing is a different incident from one that failed instantly,
        and only the duration histogram can tell them apart.
        """
        metrics_module.record_genai_client_call(
            request_model="claude-sonnet-4-6",
            response_model=None,
            input_tokens=None,
            output_tokens=None,
            duration_sec=480.0,
            error_type="APITimeoutError",
        )

        assert _points(reader, "gen_ai.client.token.usage") == []
        timed = _points(reader, "gen_ai.client.operation.duration")
        assert len(timed) == 1
        assert dict(timed[0].attributes)["error.type"] == "APITimeoutError"

    def test_the_two_per_invocation_counters_are_emitted(
        self, reader: InMemoryMetricReader
    ) -> None:
        """The conventions already name what an agent system needs.

        "Inference calls per agent invocation" and "tool calls per
        agent invocation" are defined metrics, so this repository does
        not get to invent a shape for them.
        """
        metrics_module.record_agent_invocation(
            agent_name="search",
            duration_sec=12.0,
            inference_calls=3,
            tool_calls=5,
            error_type=None,
        )

        names = _metric_names(reader)
        assert "gen_ai.invoke_agent.duration" in names
        assert "gen_ai.invoke_agent.inference_calls" in names
        assert "gen_ai.invoke_agent.tool_calls" in names

        inference = _points(reader, "gen_ai.invoke_agent.inference_calls")[0]
        tools = _points(reader, "gen_ai.invoke_agent.tool_calls")[0]
        assert inference.sum == 3
        assert tools.sum == 5
        assert dict(inference.attributes)["gen_ai.agent.name"] == "search"

    def test_tool_and_workflow_durations_are_emitted(
        self, reader: InMemoryMetricReader
    ) -> None:
        metrics_module.record_tool_execution(
            tool_name=semconv.TOOL_PDF_PARSE, duration_sec=2.0, error_type=None
        )
        metrics_module.record_workflow_invocation(
            workflow_name=semconv.WORKFLOW_SESSION,
            duration_sec=300.0,
            error_type=None,
        )

        names = _metric_names(reader)
        assert "gen_ai.execute_tool.duration" in names
        assert "gen_ai.invoke_workflow.duration" in names
        tool = dict(_points(reader, "gen_ai.execute_tool.duration")[0].attributes)
        assert tool["gen_ai.tool.name"] == "pdf_parse"
        assert tool["gen_ai.operation.name"] == "execute_tool"
        flow = dict(
            _points(reader, "gen_ai.invoke_workflow.duration")[0].attributes
        )
        assert flow["gen_ai.workflow.name"] == "session"

    def test_the_pre_existing_names_still_work(
        self, reader: InMemoryMetricReader
    ) -> None:
        """Aliases, kept for one release, and load-bearing right now.

        A dashboard whose series stops arriving renders a flat zero,
        which reads as "the fleet is idle" rather than "the metric was
        renamed" — and WO-A06's fault tier asserts on these names as
        they stand on `main`. Neither may break silently.
        """
        metrics_module.record_llm_usage(model="claude-opus-5", cost_usd=1.25)
        metrics_module.record_job_terminal(
            status="succeeded",
            error_type=None,
            duration_sec=10.0,
            kind="research",
            queue_wait_sec=0.5,
        )

        names = _metric_names(reader)
        for alias in (
            "llm_calls_total",
            "llm_cost_usd_total",
            "research_jobs_total",
            "research_job_duration_seconds",
        ):
            assert alias in names

    def test_cost_keeps_its_own_name_because_the_conventions_have_none(
        self, reader: InMemoryMetricReader
    ) -> None:
        """`llm_cost_usd_total` is not an alias and does not expire.

        The GenAI conventions define no cost attribute and no cost
        metric, so this is the only name the measurement has.
        """
        metrics_module.record_llm_usage(model="claude-opus-5", cost_usd=1.25)

        assert "llm_cost_usd_total" in _metric_names(reader)
        assert not any(
            name.startswith("gen_ai.") and "cost" in name
            for name in _metric_names(reader)
        )


# ---------------------------------------------------------------------------
# Job metrics: kind, degraded close, queue
# ---------------------------------------------------------------------------


class TestJobOutcomeCorrections:
    def test_kind_separates_research_from_session(
        self, reader: InMemoryMetricReader
    ) -> None:
        """Without it both kinds share a series and no session SLO exists."""
        metrics_module.record_job_terminal(
            status="succeeded", error_type=None, duration_sec=5.0, kind="research"
        )
        metrics_module.record_job_terminal(
            status="succeeded", error_type=None, duration_sec=5.0, kind="session"
        )

        kinds = {
            dict(p.attributes)["kind"]
            for p in _points(reader, "research_jobs_total")
        }
        assert kinds == {"research", "session"}

    def test_a_degraded_close_no_longer_reports_as_a_plain_success(
        self, reader: InMemoryMetricReader
    ) -> None:
        """The measured gap: budget exhaustion looked like a clean run.

        The row really is `succeeded` with no error — that is the
        product contract (ADR 0062) and it does not change. What
        changes is that the metric stops saying the same thing as an
        ordinary success, because an operator watching
        `sum by (status)` could not otherwise see cost ceilings binding.
        """
        metrics_module.record_job_terminal(
            status="succeeded",
            error_type=None,
            duration_sec=20.0,
            kind="session",
            cost_cap_status="degraded_close",
        )

        statuses = {
            dict(p.attributes)["status"]
            for p in _points(reader, "research_jobs_total")
        }
        assert statuses == {"degraded_close"}
        assert "succeeded" not in statuses

    def test_a_refused_cap_still_reports_as_the_failure_it_is(
        self, reader: InMemoryMetricReader
    ) -> None:
        """Only `degraded_close` is remapped.

        The `refused` behaviour already ends the job `failed` with a
        real error type, so overriding its status would *lose*
        information rather than add any.
        """
        metrics_module.record_job_terminal(
            status="failed",
            error_type="budget_exceeded_session",
            duration_sec=20.0,
            kind="session",
            cost_cap_status="refused",
        )

        point = _points(reader, "research_jobs_total")[0]
        assert dict(point.attributes)["status"] == "failed"
        assert dict(point.attributes)["error_type"] == "budget_exceeded_session"

    def test_queue_wait_is_observed_separately_from_duration(
        self, reader: InMemoryMetricReader
    ) -> None:
        """USE's 'wait' for the job queue, which the baseline lacked."""
        metrics_module.record_job_terminal(
            status="succeeded",
            error_type=None,
            duration_sec=60.0,
            kind="research",
            queue_wait_sec=42.0,
        )

        waited = _points(reader, "research_job_queue_wait_seconds")
        assert len(waited) == 1
        assert waited[0].sum == pytest.approx(42.0)
        assert dict(waited[0].attributes) == {"kind": "research"}

    def test_the_queue_gauges_read_saturation_off_the_live_accounting(
        self, reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Derived from the same source `/healthz` reports from.

        A second counter at the semaphore could disagree with the
        health endpoint, which is the drift ADR 0049 avoided for the
        first two gauges.
        """
        monkeypatch.setattr(
            metrics_module,
            "settings",
            Settings(enable_metrics=True, api_max_concurrent_jobs=4),
        )
        metrics_module.register_runtime_gauges(
            active_jobs=lambda: 6, abandoned_node_threads=lambda: 0
        )

        assert _points(reader, "research_queue_depth")[0].value == 2
        assert _points(reader, "research_queue_saturation_ratio")[
            0
        ].value == pytest.approx(1.5)

    def test_an_idle_worker_reports_no_queue_depth(
        self, reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            metrics_module,
            "settings",
            Settings(enable_metrics=True, api_max_concurrent_jobs=4),
        )
        metrics_module.register_runtime_gauges(
            active_jobs=lambda: 1, abandoned_node_threads=lambda: 0
        )

        assert _points(reader, "research_queue_depth")[0].value == 0
        assert _points(reader, "research_queue_saturation_ratio")[
            0
        ].value == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Trace continuity — the highest-value item in the work order
# ---------------------------------------------------------------------------


class _TracedStub:
    """A compiled-workflow double that opens the spans a real graph does.

    It runs one traced node and, inside it, one model span — which is
    the shape the assertion needs: submit -> workflow -> node -> model
    call, across the queue boundary that `run_job` sits on.
    """

    async def astream(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> Any:
        def node(_state: dict[str, Any]) -> dict[str, Any]:
            with tracing_module.llm_span(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                temperature=0.3,
                server_address="api.anthropic.com",
            ):
                tracing_module.note_inference_call()
            return {"iteration": 1}

        yield {"planner": tracing_module.traced_node("planner", node)({})}

    async def aget_state(self, config: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(
            next=(), values={"draft_report": "done", "iteration": 1}
        )


class TestTraceContinuity:
    async def test_submit_node_and_model_call_share_one_trace(
        self,
        spans: InMemorySpanExporter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The measured baseline was N disconnected root spans.

        The submitting request and the worker that runs the job are
        frequently different processes, so the link cannot be a
        ContextVar: it is a W3C carrier written onto the job row at
        construction and attached by `run_job` before it opens the
        run's workflow span.
        """
        monkeypatch.setattr(runner_module, "settings", Settings())
        tracer = ot_trace.get_tracer("test")

        # The API request that accepts the job. `Job(...)` is
        # constructed inside it, which is what captures the context.
        with tracer.start_as_current_span("POST /research") as request_span:
            request_trace_id = request_span.get_span_context().trace_id
            job = Job(job_id="trace-1", query="q", hitl_bypass=True)

        assert "traceparent" in job.trace_context

        store = InMemoryJobStore()
        await store.create(job)
        # Deliberately outside the request span: this stands in for the
        # worker, which in production is a different task and often a
        # different process entirely.
        await run_job(job, _TracedStub(), store, asyncio.Semaphore(1))
        assert job.status is JobStatus.succeeded

        workflow = _named(spans, "invoke_workflow research")
        node = _named(spans, "plan planner")
        model = _named(spans, "chat claude-sonnet-4-6")

        # One trace, all the way from the request that asked for it.
        assert workflow.context.trace_id == request_trace_id
        assert node.context.trace_id == request_trace_id
        assert model.context.trace_id == request_trace_id

        # And nested in the right order, so the trace answers "where
        # did the time go" rather than merely "these things happened".
        assert workflow.parent is not None
        assert workflow.parent.span_id == request_span.get_span_context().span_id
        assert node.parent is not None
        assert node.parent.span_id == workflow.context.span_id
        assert model.parent is not None
        assert model.parent.span_id == node.context.span_id

    def test_a_job_submitted_outside_a_trace_carries_an_empty_carrier(
        self, spans: InMemorySpanExporter
    ) -> None:
        """An unsampled submission is "no parent", not an error.

        Every consumer reads an empty carrier that way, which is what
        makes CLI runs and tests work without a provider.
        """
        job = Job(job_id="no-trace", query="q")
        assert job.trace_context == {}

    def test_attaching_an_empty_carrier_is_a_no_op(self) -> None:
        with tracing_module.attached_trace_context({}):
            pass
        with tracing_module.attached_trace_context(None):
            pass

    def test_a_carrier_round_trips_through_the_job_row(
        self, spans: InMemorySpanExporter
    ) -> None:
        """The carrier survives serialization, which is the whole point.

        `redis_store` derives its persistent field list from the `Job`
        dataclass, so a dict of strings is exactly what can cross a
        process boundary — which is what a redriven job needs.
        """
        tracer = ot_trace.get_tracer("test")
        with tracer.start_as_current_span("submit") as submitted:
            carrier = tracing_module.inject_trace_context()
            expected = submitted.get_span_context().trace_id

        with (
            tracing_module.attached_trace_context(carrier),
            tracer.start_as_current_span("worker") as resumed,
        ):
            assert resumed.get_span_context().trace_id == expected


# ---------------------------------------------------------------------------
# Cardinality
# ---------------------------------------------------------------------------


class TestCardinality:
    """No attribute takes an unbounded value.

    A metric attribute is a series, and a series per distinct value is
    how a collector falls over. Everything this system attributes by is
    drawn from a closed set: a job kind, a terminal status, an error
    *type*, a model id, a graph node name, a tool name.
    """

    async def test_no_user_or_request_text_reaches_a_metric_attribute(
        self,
        reader: InMemoryMetricReader,
        spans: InMemorySpanExporter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(runner_module, "settings", Settings())

        query = "a-distinctive-unbounded-research-query"
        job = Job(job_id="cardinality-probe-id", query=query, hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)
        await run_job(job, _TracedStub(), store, asyncio.Semaphore(1))

        values = _all_attribute_values(reader)
        assert query not in values
        assert job.job_id not in values
        # Nothing merely *containing* them either — a composed
        # attribute would be just as unbounded as a bare one.
        assert not any(query in value or job.job_id in value for value in values)

    def test_every_emitted_attribute_value_is_from_a_closed_set(
        self, reader: InMemoryMetricReader
    ) -> None:
        """Enumerate the vocabulary, then assert nothing escapes it."""
        metrics_module.record_job_terminal(
            status="failed",
            error_type="timeout",
            duration_sec=1.0,
            kind="session",
            queue_wait_sec=1.0,
        )
        metrics_module.record_agent_invocation(
            agent_name="critic",
            duration_sec=1.0,
            inference_calls=1,
            tool_calls=0,
            error_type=None,
        )
        metrics_module.record_tool_execution(
            tool_name=semconv.TOOL_EMBEDDING_RANK,
            duration_sec=1.0,
            error_type="TimeoutError",
        )
        metrics_module.record_workflow_invocation(
            workflow_name=semconv.WORKFLOW_RESEARCH,
            duration_sec=1.0,
            error_type=None,
        )
        metrics_module.record_genai_client_call(
            request_model="claude-sonnet-4-6",
            response_model="claude-sonnet-4-6",
            input_tokens=1,
            output_tokens=1,
            duration_sec=1.0,
            error_type=None,
        )

        allowed = {
            # Job outcomes.
            "failed",
            "timeout",
            "session",
            # Agent, tool and workflow identities — literals in
            # `src/graph/` and `semconv`, never caller input.
            "critic",
            semconv.TOOL_EMBEDDING_RANK,
            semconv.WORKFLOW_RESEARCH,
            # Conventional operation / provider / token enums.
            semconv.OPERATION_CHAT,
            semconv.OPERATION_EXECUTE_TOOL,
            semconv.PROVIDER_ANTHROPIC,
            semconv.TOKEN_TYPE_INPUT,
            semconv.TOKEN_TYPE_OUTPUT,
            # Model ids: bounded by the price table, and the axis spend
            # has to be attributed along.
            "claude-sonnet-4-6",
            # Error types: exception class names and error codes, both
            # closed sets. Never a message.
            "TimeoutError",
            metrics_module.NO_ERROR,
        }
        assert _all_attribute_values(reader) <= allowed

    def test_tool_names_are_a_closed_set(self) -> None:
        """A tool span never takes a caller-supplied name.

        This is what bounds `gen_ai.execute_tool.duration` and
        `gen_ai.invoke_agent.tool_calls`: the call sites pass a
        constant, so the series count is the size of this set.
        """
        assert semconv.TOOL_ARXIV_SEARCH in semconv.TOOL_NAMES
        assert len(semconv.TOOL_NAMES) == 5


# ---------------------------------------------------------------------------
# Sampling and shutdown
# ---------------------------------------------------------------------------


class TestSamplingConfiguration:
    """Sampling without knowing the OTel environment variables."""

    def test_unset_defers_to_the_sdks_own_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """None means "install no sampler", not "sample nothing".

        An operator already using `OTEL_TRACES_SAMPLER` must not be
        silently overridden by a repository default.
        """
        monkeypatch.delenv(tracing_module.TRACE_SAMPLE_RATIO_ENV, raising=False)
        assert tracing_module.trace_sample_ratio() is None
        assert tracing_module._make_sampler() is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("0.1", 0.1), ("1", 1.0), ("0", 0.0), ("-3", 0.0), ("9", 1.0)],
    )
    def test_the_ratio_is_read_and_clamped(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: float
    ) -> None:
        monkeypatch.setenv(tracing_module.TRACE_SAMPLE_RATIO_ENV, raw)
        assert tracing_module.trace_sample_ratio() == pytest.approx(expected)
        assert tracing_module._make_sampler() is not None

    def test_a_typo_does_not_stop_the_process_from_starting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bad value in an operator's environment is a warning.

        Raising here would turn a typo into a process that will not
        boot, which is a worse outcome than tracing falling back to the
        SDK's own defaults.
        """
        monkeypatch.setenv(tracing_module.TRACE_SAMPLE_RATIO_ENV, "loads")
        assert tracing_module.trace_sample_ratio() is None

    def test_the_sampler_is_parent_based_so_a_worker_cannot_re_decide(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The decision travels with the trace, or continuity is lost.

        An unparented ratio sampler would let the worker re-roll for a
        job whose submitting request was already sampled, tearing apart
        exactly the join this work order exists to build.
        """
        monkeypatch.setenv(tracing_module.TRACE_SAMPLE_RATIO_ENV, "0.25")
        sampler = tracing_module._make_sampler()
        assert sampler is not None
        assert "ParentBased" in sampler.get_description()


class TestTracerShutdown:
    def test_shutdown_flushes_and_disarms(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The counterpart to `shutdown_metrics`, which had no twin.

        Without it the last `BatchSpanProcessor` window is lost on
        every SIGTERM — precisely when failures happen.
        """
        flushed: list[int] = []
        provider = SimpleNamespace(
            force_flush=lambda timeout_millis: flushed.append(timeout_millis),
            shutdown=lambda: flushed.append(-1),
        )
        monkeypatch.setattr(tracing_module, "_provider", provider)
        monkeypatch.setattr(tracing_module, "_configured", True)

        tracing_module.shutdown_tracing(timeout_millis=1234)

        assert flushed == [1234, -1]
        assert tracing_module._provider is None
        assert tracing_module._configured is False

    def test_shutdown_when_never_configured_is_a_no_op(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(tracing_module, "_provider", None)
        tracing_module.shutdown_tracing()
        assert tracing_module._provider is None

    def test_a_failing_flush_does_not_crash_the_shutdown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Losing an export window must not turn a clean stop into a crash."""

        def _boom(timeout_millis: int) -> None:
            raise RuntimeError("collector gone")

        provider = SimpleNamespace(force_flush=_boom, shutdown=lambda: None)
        monkeypatch.setattr(tracing_module, "_provider", provider)

        tracing_module.shutdown_tracing()

        assert tracing_module._provider is None


# ---------------------------------------------------------------------------
# The per-invocation counters, end to end
# ---------------------------------------------------------------------------


class TestPerInvocationCounters:
    def test_a_nodes_model_and_tool_calls_are_counted_against_it(
        self, reader: InMemoryMetricReader, spans: InMemorySpanExporter
    ) -> None:
        """The counters and the spans cannot disagree.

        A tool call is counted by `tool_span` itself, so the value of
        `gen_ai.invoke_agent.tool_calls` is by construction the number
        of `execute_tool` spans under that node.
        """
        with tracing_module.agent_span("search"):
            tracing_module.note_inference_call()
            tracing_module.note_inference_call()
            for _ in range(3):
                with tracing_module.tool_span(
                    semconv.TOOL_ARXIV_SEARCH,
                    tool_type=semconv.TOOL_TYPE_EXTENSION,
                ):
                    pass

        inference = _points(reader, "gen_ai.invoke_agent.inference_calls")[0]
        tools = _points(reader, "gen_ai.invoke_agent.tool_calls")[0]
        assert inference.sum == 2
        assert tools.sum == 3
        assert len(
            [s for s in spans.get_finished_spans() if s.name.startswith("execute_tool")]
        ) == 3

    def test_calls_outside_an_agent_span_are_not_misattributed(
        self, reader: InMemoryMetricReader, spans: InMemorySpanExporter
    ) -> None:
        """An eval judge call belongs to no agent invocation.

        Counting it against whichever node happened to run last would
        be worse than not counting it at all.
        """
        tracing_module.note_inference_call()

        assert _points(reader, "gen_ai.invoke_agent.inference_calls") == []


# ---------------------------------------------------------------------------
# The disabled path, and provider construction
# ---------------------------------------------------------------------------


class TestTelemetryOffCostsNothing:
    """With both flags off, no wrapper is built and no span is opened.

    The discipline `traced_node` established and every helper added
    since follows: a disabled deployment pays one settings read at the
    call site and nothing else.
    """

    @pytest.fixture(autouse=True)
    def _both_signals_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            tracing_module,
            "settings",
            Settings(enable_tracing=False, enable_metrics=False),
        )

    def test_traced_node_returns_the_original_callable(self) -> None:
        def agent(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        assert tracing_module.traced_node("planner", agent) is agent

    def test_every_span_helper_yields_the_invalid_span(self) -> None:
        with tracing_module.workflow_span("research") as span:
            assert span is ot_trace.INVALID_SPAN
        with tracing_module.agent_span("search") as span:
            assert span is ot_trace.INVALID_SPAN
        with tracing_module.tool_span(
            semconv.TOOL_PDF_PARSE, tool_type=semconv.TOOL_TYPE_EXTENSION
        ) as span:
            assert span is ot_trace.INVALID_SPAN
        with tracing_module.llm_span(
            model="m", max_tokens=1, temperature=0.0, server_address="h"
        ) as span:
            assert span is ot_trace.INVALID_SPAN

    def test_metrics_alone_are_enough_to_build_the_wrapper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The graph is compiled before `configure_metrics()` runs.

        So the decision reads `settings`, not `metrics_enabled()` — a
        live check would be False at exactly the moment it is asked.
        """
        monkeypatch.setattr(
            tracing_module,
            "settings",
            Settings(enable_tracing=False, enable_metrics=True),
        )

        def agent(state: dict[str, Any]) -> dict[str, Any]:
            return {}

        assert tracing_module.traced_node("planner", agent) is not agent


class TestProviderConstruction:
    """`configure_tracing` itself, run rather than stubbed."""

    @pytest.fixture
    def fresh_global(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        """Let this test install a real provider, and take it back after."""
        monkeypatch.setattr(
            ot_trace,
            "_TRACER_PROVIDER_SET_ONCE",
            ot_trace._TRACER_PROVIDER_SET_ONCE.__class__(),
            raising=False,
        )
        monkeypatch.setattr(ot_trace, "_TRACER_PROVIDER", None, raising=False)
        monkeypatch.setattr(tracing_module, "_configured", False)
        monkeypatch.setattr(tracing_module, "_provider", None)
        yield
        tracing_module._provider = None
        tracing_module._configured = False

    def test_an_empty_endpoint_gets_the_console_exporter(
        self, fresh_global: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Local dev sees spans on stderr rather than buffering them."""
        monkeypatch.setattr(
            tracing_module,
            "settings",
            Settings(enable_tracing=True, otel_exporter_endpoint=""),
        )
        monkeypatch.setenv(tracing_module.TRACE_SAMPLE_RATIO_ENV, "0.5")

        tracing_module.configure_tracing()

        assert tracing_module._configured is True
        assert tracing_module._provider is not None
        assert "ParentBased" in tracing_module._provider.sampler.get_description()

    def test_an_endpoint_gets_the_otlp_traces_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exporter appends `/v1/traces`, as OTLP HTTP requires."""
        monkeypatch.setattr(
            tracing_module,
            "settings",
            Settings(
                enable_tracing=True,
                otel_exporter_endpoint="http://collector:4318/",
            ),
        )

        exporter = tracing_module._make_exporter()

        assert "collector:4318/v1/traces" in exporter._endpoint

    def test_configure_is_a_no_op_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tracing_module, "settings", Settings(enable_tracing=False)
        )
        monkeypatch.setattr(tracing_module, "_configured", False)

        tracing_module.configure_tracing()

        assert tracing_module._configured is False


class TestTracedToolDecorator:
    def test_the_decorator_opens_a_span_and_keeps_the_function(
        self, spans: InMemorySpanExporter
    ) -> None:
        """Three of the four tools carry this; arXiv uses the call-site
        form because its module belongs to a peer work order."""

        @tracing_module.traced_tool(
            semconv.TOOL_SEMANTIC_SCHOLAR_SEARCH,
            tool_type=semconv.TOOL_TYPE_EXTENSION,
        )
        def search(query: str) -> list[str]:
            """Docstring survives."""
            return [query]

        assert search("q") == ["q"]
        assert search.__name__ == "search"
        assert search.__doc__ == "Docstring survives."

        span = _named(spans, "execute_tool semantic_scholar_search")
        assert span.attributes["gen_ai.tool.name"] == "semantic_scholar_search"

    def test_a_raising_tool_still_records_and_re_raises(
        self, spans: InMemorySpanExporter, reader: InMemoryMetricReader
    ) -> None:
        @tracing_module.traced_tool(
            semconv.TOOL_PDF_PARSE, tool_type=semconv.TOOL_TYPE_EXTENSION
        )
        def parse(url: str) -> str:
            raise ValueError("bad pdf")

        with pytest.raises(ValueError, match="bad pdf"):
            parse("http://example.invalid/p.pdf")

        assert _named(spans, "execute_tool pdf_parse").attributes[
            "error.type"
        ] == "ValueError"
        timed = _points(reader, "gen_ai.execute_tool.duration")[0]
        assert dict(timed.attributes)["error.type"] == "ValueError"


class TestFailingScopesAreRecorded:
    def test_a_failing_workflow_records_its_error_type(
        self, spans: InMemorySpanExporter, reader: InMemoryMetricReader
    ) -> None:
        with pytest.raises(RuntimeError), tracing_module.workflow_span("research"):
            raise RuntimeError("graph blew up")

        assert _named(spans, "invoke_workflow research").attributes[
            "error.type"
        ] == "RuntimeError"
        timed = _points(reader, "gen_ai.invoke_workflow.duration")[0]
        assert dict(timed.attributes)["error.type"] == "RuntimeError"

    def test_a_failing_agent_still_reports_its_call_counts(
        self, spans: InMemorySpanExporter, reader: InMemoryMetricReader
    ) -> None:
        """A node that died after two model calls still made two.

        Recording the counters only on the happy path would make a
        failing node look cheap, which is the opposite of true.
        """
        with pytest.raises(RuntimeError), tracing_module.agent_span("critic"):
            tracing_module.note_inference_call()
            tracing_module.note_inference_call()
            raise RuntimeError("boom")

        assert _points(reader, "gen_ai.invoke_agent.inference_calls")[0].sum == 2
        duration = _points(reader, "gen_ai.invoke_agent.duration")[0]
        assert dict(duration.attributes)["error.type"] == "RuntimeError"

    def test_a_failing_model_call_marks_the_chat_span(
        self, spans: InMemorySpanExporter
    ) -> None:
        with pytest.raises(TimeoutError), tracing_module.llm_span(
            model="claude-sonnet-4-6",
            max_tokens=16,
            temperature=0.3,
            server_address="api.anthropic.com",
        ):
            raise TimeoutError("upstream")

        span = _named(spans, "chat claude-sonnet-4-6")
        assert span.attributes["error.type"] == "TimeoutError"
        assert span.status.status_code is ot_trace.StatusCode.ERROR
