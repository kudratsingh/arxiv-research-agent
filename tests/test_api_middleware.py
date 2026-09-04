"""The HTTP edge: request ids, correlation, trace continuity, RED (WO-A10).

`create_app` used to add CORS and nothing else. There was no request id
on the wire, nothing bound the ADR 0067 correlation context, inbound
trace context was dropped at the socket, and there were no HTTP metrics
at all — so a fleet whose Redis had died reported *no movement on any
instrument*, which reads as an idle fleet rather than a failing one.

Four properties are asserted here, and each one failed before this
change:

- **A request is identifiable.** One id, adopted from the caller when
  they supplied a well-formed one, echoed in the response header, in
  ADR 0064's error envelope, and on every log line the request emits.
- **A request is joinable to a trace.** An inbound `traceparent` is
  adopted rather than replaced, which is what makes a caller's trace
  continue into ours and — via `Job.trace_context` — into the job.
- **A request is counted.** `http.server.request.duration` keyed on the
  route **template**, and `http.server.active_requests` that returns to
  zero.
- **A worker can be drained.** `/readyz` answers 503 when a dependency
  is down or the queue is saturated, while `/healthz` keeps its
  always-200 liveness semantics.

## Why the log assertions format through a live handler

`caplog` stores `LogRecord`s and formats them after the test body. That
is the wrong shape for anything the *context* supplies: `request_id`,
`principal_hash`, `trace_id` and `span_id` are read by `JsonFormatter`
at format time, and by then the request has ended and the context is
unbound. `shipped_log_lines` attaches a handler that formats at emit
time, exactly as the deployed root handler does, so these tests assert
on the line an operator greps rather than on a record that resembles it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from asgi_lifespan import LifespanManager
from opentelemetry import trace as ot_trace
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind, StatusCode

from src.api import app as app_module
from src.api import auth as auth_module
from src.api import routes as routes_module
from src.api.app import (
    CONTEXT_FIELD_REQUEST_ID,
    MAX_REQUEST_ID_CHARS,
    REQUEST_ID_HEADER,
    _http_error_type,
    _resolve_request_id,
    create_app,
)
from src.api.jobs import InMemoryJobStore
from src.config import Settings
from src.observability import JsonFormatter
from src.observability import metrics as metrics_module
from src.observability import tracing as tracing_module
from src.observability.context import CONTEXT_FIELDS

pytestmark = pytest.mark.integration

ACCESS_EVENT = "api_request_completed"

#: The instruments this file asserts on, under the names the **stable**
#: HTTP conventions give them. Unlike the `gen_ai.*` family these are
#: not expected to churn, which is why they are spelled out rather than
#: read back out of `semconv` — a pin that derives itself from its
#: subject pins nothing.
DURATION_METRIC = "http.server.request.duration"
ACTIVE_METRIC = "http.server.active_requests"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def reader(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemoryMetricReader]:
    """Arm the metric pipeline against an in-memory reader.

    Same idiom as `tests/test_otel_metrics.py`: `enable_metrics` is off
    in the shipped defaults, so the flag is forced on the metrics
    module's own `settings` handle and the provider is torn down
    afterwards so instruments never leak into the next test.
    """
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


@pytest.fixture
def traced(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    """Install a fresh in-memory tracer for one test.

    Same idiom as `tests/test_tracing.py`, including the reason for the
    set-once reset: OTel allows the global provider to be installed once
    per process, and successive tests each need their own exporter.
    `_configured` is forced True so `configure_tracing()` leaves the
    provider installed here alone.
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


@contextlib.contextmanager
def shipped_log_lines() -> Iterator[list[dict[str, Any]]]:
    """Capture the JSON lines the deployed root handler would write.

    See the module docstring: formatting has to happen at emit time or
    every context-supplied field is missing by the time a test looks.
    """
    lines: list[dict[str, Any]] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(json.loads(JsonFormatter().format(record)))

    handler = _Capture()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield lines
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


def access_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Just the access lines, in order."""
    return [line for line in lines if line["message"] == ACCESS_EVENT]


def points(reader: InMemoryMetricReader, name: str) -> list[Any]:
    """Every aggregated data point for `name`."""
    data = reader.get_metrics_data()
    if data is None:
        return []
    return [
        point
        for resource_metric in data.resource_metrics
        for scope_metric in resource_metric.scope_metrics
        for metric in scope_metric.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def one_point(reader: InMemoryMetricReader, name: str, **attributes: Any) -> Any:
    """The single point of `name` carrying at least `attributes`."""
    candidates = points(reader, name)
    matches = [
        point
        for point in candidates
        if all(dict(point.attributes).get(k) == v for k, v in attributes.items())
    ]
    assert len(matches) == 1, (
        f"expected exactly one {name} point carrying {attributes}, got "
        f"{[dict(p.attributes) for p in candidates]}"
    )
    return matches[0]


class _PingStore(InMemoryJobStore):
    """An in-memory store wearing a Redis client whose ping the test owns.

    `_redis_status` duck-types on `_client.ping`, so this is the whole
    surface a health probe sees. Subclassing `InMemoryJobStore` rather
    than faking one keeps every other route working, which matters
    because `/readyz` reads the same lifespan state the job routes do.
    """

    def __init__(self, *, healthy: bool = True) -> None:
        super().__init__()
        self.healthy = healthy

        async def _ping() -> bool:
            if not self.healthy:
                raise ConnectionError("redis://user:secret@cache:6379 refused")
            return True

        # Named `_client` because that is the attribute `create_app` and
        # `_redis_status` both duck-type on (ADR 0037 follow-up).
        self._client = type("_FakeRedis", (), {"ping": staticmethod(_ping)})()


@contextlib.asynccontextmanager
async def booted(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings: Settings | None = None,
    store: InMemoryJobStore | None = None,
    max_concurrent_jobs: int = 4,
) -> AsyncIterator[tuple[httpx.AsyncClient, Any]]:
    """Boot the real app with the real middleware stack.

    No middleware is injected and none is stubbed: the point of every
    test below is what `create_app` actually assembles, and a fixture
    that installed its own copy would assert the fixture.

    Yields the client and the app, because the readiness tests need to
    reach into `app.state.tasks` to make the worker look busy.
    """
    overridden = settings or Settings()
    for module in (app_module, auth_module, routes_module):
        monkeypatch.setattr(module, "settings", overridden)

    app = create_app(
        build_workflow=lambda: MagicMock(),
        store=store if store is not None else InMemoryJobStore(),
        max_concurrent_jobs=max_concurrent_jobs,
    )
    async with (
        LifespanManager(app),
        httpx.AsyncClient(
            # `raise_app_exceptions=False` so the 500 body ADR 0064
            # produces is observable; `ServerErrorMiddleware` re-raises
            # after the handler has answered.
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client,
    ):
        yield client, app


# ---------------------------------------------------------------------------
# The request id
# ---------------------------------------------------------------------------


class TestTheRequestIdIsOneValue:
    async def test_a_response_carries_an_id_and_the_log_line_carries_the_same_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The join an operator makes from a user's bug report."""
        async with booted(monkeypatch) as (client, _):
            with shipped_log_lines() as lines:
                response = await client.get("/healthz")

        request_id = response.headers[REQUEST_ID_HEADER]
        assert request_id
        (line,) = access_lines(lines)
        assert line["request_id"] == request_id

    async def test_a_well_formed_inbound_id_is_adopted_rather_than_replaced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second id would make the caller's logs unjoinable to ours.

        The Next.js proxy, a load balancer and a calling service all
        stamp an id before we see the request. Minting our own on top
        leaves an operator holding the caller's id with no way to find
        our side of the same request.
        """
        supplied = "0HMV1B2C3D4E5-42"
        async with booted(monkeypatch) as (client, _):
            with shipped_log_lines() as lines:
                response = await client.get(
                    "/healthz", headers={REQUEST_ID_HEADER: supplied}
                )

        assert response.headers[REQUEST_ID_HEADER] == supplied
        assert access_lines(lines)[0]["request_id"] == supplied

    @pytest.mark.parametrize(
        "hostile",
        [
            "abc\ndef",  # a newline aimed at the log stream
            "x" * (MAX_REQUEST_ID_CHARS + 1),  # a blob aimed at the index
            "id with spaces",
            "<script>alert(1)</script>",
            "",
        ],
        ids=["newline", "too-long", "spaces", "markup", "empty"],
    )
    def test_a_hostile_inbound_id_is_discarded_rather_than_sanitized(
        self, hostile: str
    ) -> None:
        """Discarded, not cleaned up.

        Sanitizing would keep an attacker's string on the line in a
        mangled form and leave the field untrustworthy; minting a fresh
        one keeps the field meaning exactly one thing. Asserted on the
        resolver directly because httpx refuses to *send* some of these
        — which is a second layer, not the one under test.
        """
        headers = httpx.Headers({REQUEST_ID_HEADER: hostile})
        from starlette.datastructures import Headers as StarletteHeaders

        resolved = _resolve_request_id(
            StarletteHeaders({REQUEST_ID_HEADER: headers.get(REQUEST_ID_HEADER, "")})
        )
        assert resolved != hostile
        assert len(resolved) == 32  # a fresh uuid4 hex

    async def test_the_error_envelope_and_the_header_agree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR 0064 left this seam open on purpose; WO-A10 closes it.

        The envelope's `request_id` used to be minted at the moment of
        failure, so it could not appear on any other line for the same
        request. It now reads the middleware's value off
        `request.state`.
        """
        async with booted(monkeypatch) as (client, _):
            with shipped_log_lines() as lines:
                response = await client.get("/research/does-not-exist")

        assert response.status_code == 404
        envelope_id = response.json()["error"]["request_id"]
        assert response.headers[REQUEST_ID_HEADER] == envelope_id
        # And the same id is on both lines the request produced: the
        # rejection and the access line.
        rejected = [line for line in lines if line["message"] == "api_request_rejected"]
        assert [line["request_id"] for line in rejected] == [envelope_id]
        assert access_lines(lines)[0]["request_id"] == envelope_id

    async def test_the_header_is_not_duplicated_on_an_error_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_error_response` sets the header too; two would let a proxy pick."""
        async with booted(monkeypatch) as (client, _):
            response = await client.get("/research/does-not-exist")

        assert response.headers.get_list(REQUEST_ID_HEADER) == [
            response.json()["error"]["request_id"]
        ]


# ---------------------------------------------------------------------------
# The access line
# ---------------------------------------------------------------------------


class TestTheStructuredAccessLine:
    async def test_it_carries_the_route_template_and_never_the_raw_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The cardinality rule, on the log side.

        A raw path carries the job id. As a log field that is indexed
        per value, which is the same failure the `http.route` metric
        attribute exists to prevent — so the two use one rule and one
        source.
        """
        async with booted(monkeypatch) as (client, _):
            with shipped_log_lines() as lines:
                await client.get("/research/9f2c4b1e77aa4d10")

        (line,) = access_lines(lines)
        assert line["route"] == "/research/{job_id}"
        assert "9f2c4b1e77aa4d10" not in json.dumps(line)

    async def test_every_field_survives_the_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dropped field is silent, which is why this is asserted.

        `_log_boundary_error` had been passing `method`, `route` and
        `http_status` since ADR 0064 and all three were being dropped:
        it splats a dict built on the line above, so the log contract's
        AST scan never saw the keys and nothing failed. Registering them
        is part of this work order; this is the test that would catch
        the same mistake again.
        """
        async with booted(monkeypatch) as (client, _):
            with shipped_log_lines() as lines:
                await client.get("/healthz")

        (line,) = access_lines(lines)
        assert line["method"] == "GET"
        assert line["route"] == "/healthz"
        assert line["http_status"] == 200
        assert isinstance(line["elapsed_ms"], float)
        assert "dropped_extra_keys" not in line
        assert "unregistered_event" not in line

    async def test_a_path_that_matched_no_route_carries_no_route_at_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`None`, not the raw path and not a placeholder.

        The conventions make `http.route` conditionally required
        precisely so "no route matched" is expressible. Filling it with
        the path here would put one series per 404'd URL into the store,
        which is a cardinality bomb anyone can fire from outside.
        """
        async with booted(monkeypatch) as (client, _):
            with shipped_log_lines() as lines:
                response = await client.get("/no/such/surface")

        assert response.status_code == 404
        (line,) = access_lines(lines)
        assert line["route"] is None
        assert "no/such/surface" not in json.dumps(line)

    async def test_it_stays_info_even_for_a_server_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 4xx/5xx judgement is made once, by ADR 0064's handlers.

        A WARNING here would double-report every failure and make
        "count of WARNING lines" mean nothing.
        """
        broken = InMemoryJobStore()

        async def _explode(_job: Any) -> None:
            raise ConnectionError("redis is gone")

        monkeypatch.setattr(broken, "create", _explode)

        async with booted(monkeypatch, store=broken) as (client, _):
            with shipped_log_lines() as lines:
                response = await client.post(
                    "/research", json={"query": "q", "hitl_bypass": True}
                )

        assert response.status_code == 500
        (line,) = access_lines(lines)
        assert line["level"] == "INFO"
        assert line["http_status"] == 500
        # The ERROR line beside it is the one that carries the verdict.
        assert [
            entry["level"]
            for entry in lines
            if entry["message"] == "api_request_failed"
        ] == ["ERROR"]

    def test_serve_turns_uvicorns_own_access_log_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two access logs for one request would be worse than either.

        The replacement only holds if uvicorn's prose line is actually
        disabled where the container boots. `tests/e2e/test_http_surface.py`
        proves the effect on a real socket; this pins the setting, which
        is the part a refactor can silently drop.
        """
        import src.api.serve as serve_module

        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            serve_module.uvicorn,
            "run",
            lambda *args, **kwargs: captured.update(kwargs),
        )
        serve_module.main()

        assert captured["access_log"] is False
        # Still deferring to the JSON logger for everything else.
        assert captured["log_config"] is None


# ---------------------------------------------------------------------------
# Correlation context
# ---------------------------------------------------------------------------


class TestTheCorrelationContextIsBoundAtTheEdge:
    async def test_the_principal_reaches_the_line_as_a_hash_not_a_key_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR 0049 refused to attribute metrics by `key_id`; the log
        layer must not quietly undo that. A metric label lives until the
        next scrape, a log field lives for the retention window."""
        from src.observability.context import hash_principal

        settings = Settings(enable_api_auth=True, api_keys="acme-prod:s3cret")
        async with booted(monkeypatch, settings=settings) as (client, _):
            with shipped_log_lines() as lines:
                await client.get("/research/nope", headers={"X-API-Key": "s3cret"})

        (line,) = access_lines(lines)
        assert line["principal_hash"] == hash_principal("acme-prod")
        assert "acme-prod" not in json.dumps(line)
        assert "s3cret" not in json.dumps(line)

    async def test_an_unauthenticated_request_binds_no_principal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bad key must still be a 401 from the route, not a 500 from
        the middleware — and it must not hash to a shared bucket."""
        settings = Settings(enable_api_auth=True, api_keys="acme-prod:s3cret")
        async with booted(monkeypatch, settings=settings) as (client, _):
            with shipped_log_lines() as lines:
                response = await client.get(
                    "/research/nope", headers={"X-API-Key": "wrong"}
                )

        assert response.status_code == 401
        (line,) = access_lines(lines)
        assert "principal_hash" not in line

    async def test_a_misconfigured_keystore_is_still_the_routes_500_not_ours(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The middleware authorizes nothing and must fail nothing.

        Resolving the principal reuses `require_principal`, which raises
        `ApiAuthMisconfigured` when auth is on with an empty keystore.
        Swallowing it here is what keeps an observability helper from
        turning a request into a failure it would not otherwise have
        had — the route dependency still raises, and the operator still
        gets the 500 that tells them the deployment is misconfigured.
        """
        settings = Settings(enable_api_auth=True, api_keys="")
        async with booted(monkeypatch, settings=settings) as (client, _):
            with shipped_log_lines() as lines:
                response = await client.get(
                    "/research/nope", headers={"X-API-Key": "anything"}
                )

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "api_auth_misconfigured"
        (line,) = access_lines(lines)
        assert "principal_hash" not in line
        assert line["http_status"] == 500

    async def test_the_context_does_not_leak_into_the_next_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two requests, two ids. A context left bound would attribute
        the second request's lines to the first one's caller."""
        async with booted(monkeypatch) as (client, _):
            with shipped_log_lines() as lines:
                await client.get("/healthz")
                await client.get("/healthz")

        first, second = access_lines(lines)
        assert first["request_id"] != second["request_id"]


class TestInboundTraceContext:
    async def test_a_callers_traceparent_is_adopted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The outer hop ADR 0066 left open.

        ADR 0066 made a job one trace from submission inward. Without
        extraction at the socket a caller that already had a trace still
        ends up with two disconnected halves.
        """
        trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        async with booted(monkeypatch) as (client, _):
            with shipped_log_lines() as lines:
                await client.get(
                    "/healthz",
                    headers={"traceparent": f"00-{trace_id}-00f067aa0ba902b7-01"},
                )

        (line,) = access_lines(lines)
        assert line["trace_id"] == trace_id

    async def test_a_request_without_one_is_not_given_a_fabricated_trace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With tracing off there is no span, so there is no id to
        report — reporting one would invent a trace nothing exported."""
        async with booted(monkeypatch) as (client, _):
            with shipped_log_lines() as lines:
                await client.get("/healthz")

        (line,) = access_lines(lines)
        assert "trace_id" not in line

    async def test_a_malformed_traceparent_does_not_break_the_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Header content is caller-controlled; the propagator is
        tolerant, and this pins that the edge stays tolerant with it."""
        async with booted(monkeypatch) as (client, _):
            response = await client.get(
                "/healthz", headers={"traceparent": "not-a-traceparent"}
            )

        assert response.status_code == 200


class TestTheServerSpan:
    """With tracing on, the edge opens the span the doc's tree shows.

    `docs/observability.md` draws `POST /research` as the root of a
    job's trace. Before this there was no such span: `run_job`'s
    `invoke_workflow` was the root, so an API request and the work it
    caused were joinable only when a *caller* had already started a
    trace for us to inherit.
    """

    async def test_it_is_named_for_the_method_and_the_route_template(
        self, monkeypatch: pytest.MonkeyPatch, traced: InMemorySpanExporter
    ) -> None:
        """`{method} {route}`, which is the conventional server span
        name — and it cannot be known when the span starts, because
        routing has not happened yet. The rename in `_finish` is the
        same two-step every ASGI instrumentation performs."""
        async with booted(
            monkeypatch, settings=Settings(enable_tracing=True)
        ) as (client, _):
            await client.get("/research/9f2c4b1e77aa4d10")

        (span,) = traced.get_finished_spans()
        assert span.name == "GET /research/{job_id}"
        assert span.kind is SpanKind.SERVER
        attributes = dict(span.attributes or {})
        assert attributes["http.route"] == "/research/{job_id}"
        assert attributes["http.request.method"] == "GET"
        assert attributes["http.response.status_code"] == 404
        assert attributes["url.scheme"] == "http"
        # A 404 is not a server error, so the span is not marked one.
        assert "error.type" not in attributes

    async def test_it_continues_the_callers_trace_rather_than_starting_one(
        self, monkeypatch: pytest.MonkeyPatch, traced: InMemorySpanExporter
    ) -> None:
        """The acceptance criterion, asserted on the trace itself.

        A log line carrying the inbound id would pass a weaker version
        of this test while the span was still a fresh root. What has to
        be true is that the *span* hangs off the caller's — that is what
        makes one trace across the hop, and what `inject_trace_context`
        then carries onto the job row.
        """
        trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        parent_span_id = "00f067aa0ba902b7"
        async with booted(
            monkeypatch, settings=Settings(enable_tracing=True)
        ) as (client, _):
            await client.get(
                "/healthz",
                headers={"traceparent": f"00-{trace_id}-{parent_span_id}-01"},
            )

        (span,) = traced.get_finished_spans()
        assert format(span.context.trace_id, "032x") == trace_id
        assert span.parent is not None
        assert format(span.parent.span_id, "016x") == parent_span_id

    async def test_a_request_with_no_caller_trace_starts_a_root(
        self, monkeypatch: pytest.MonkeyPatch, traced: InMemorySpanExporter
    ) -> None:
        """Which is the improvement over doing nothing: submit and the
        job it queues now share a trace even when nobody upstream had
        one to give us."""
        async with booted(
            monkeypatch, settings=Settings(enable_tracing=True)
        ) as (client, _):
            await client.get("/healthz")

        (span,) = traced.get_finished_spans()
        assert span.parent is None
        assert span.context.trace_id != 0

    async def test_an_unrouted_path_keeps_the_bare_method_as_the_span_name(
        self, monkeypatch: pytest.MonkeyPatch, traced: InMemorySpanExporter
    ) -> None:
        """No route matched, so there is no template to name it with —
        and the raw path must not stand in, or every 404'd URL becomes
        its own span name in the trace UI's aggregate views."""
        async with booted(
            monkeypatch, settings=Settings(enable_tracing=True)
        ) as (client, _):
            await client.get("/no/such/surface")

        (span,) = traced.get_finished_spans()
        assert span.name == "GET"
        assert "http.route" not in dict(span.attributes or {})

    async def test_an_unhandled_exception_marks_the_span_and_names_the_class(
        self, monkeypatch: pytest.MonkeyPatch, traced: InMemorySpanExporter
    ) -> None:
        """`error.type` is the exception class, never the message — a
        message routinely carries the connection string that caused it
        (ADR 0042)."""
        broken = InMemoryJobStore()

        async def _explode(_job: Any) -> None:
            raise ConnectionError("redis://user:s3cr3t@cache:6379 refused")

        monkeypatch.setattr(broken, "create", _explode)

        async with booted(
            monkeypatch, settings=Settings(enable_tracing=True), store=broken
        ) as (client, _):
            await client.post("/research", json={"query": "q", "hitl_bypass": True})

        (span,) = traced.get_finished_spans()
        attributes = dict(span.attributes or {})
        assert attributes["error.type"] == "ConnectionError"
        assert attributes["http.response.status_code"] == 500
        assert span.status.status_code is StatusCode.ERROR
        assert "s3cr3t" not in str(attributes)

    async def test_an_unknown_method_keeps_the_original_on_the_span_only(
        self, monkeypatch: pytest.MonkeyPatch, traced: InMemorySpanExporter
    ) -> None:
        """A span is one record, so unbounded input costs one field
        there; the same value on a metric attribute would mint a series
        per value, which is why `_OTHER` is what the metric sees."""
        async with booted(
            monkeypatch, settings=Settings(enable_tracing=True)
        ) as (client, _):
            await client.request("PROPFIND", "/healthz")

        (span,) = traced.get_finished_spans()
        attributes = dict(span.attributes or {})
        assert attributes["http.request.method"] == "_OTHER"
        assert attributes["http.request.method_original"] == "PROPFIND"

    async def test_the_span_id_reaches_the_access_line(
        self, monkeypatch: pytest.MonkeyPatch, traced: InMemorySpanExporter
    ) -> None:
        """Log-to-trace navigation in both directions: the line names
        the span, and the span carries the request id to query logs by.
        The access line is emitted while the span is still current
        precisely so this holds."""
        async with booted(
            monkeypatch, settings=Settings(enable_tracing=True)
        ) as (client, _):
            with shipped_log_lines() as lines:
                response = await client.get("/healthz")

        (line,) = access_lines(lines)
        (span,) = traced.get_finished_spans()
        assert line["trace_id"] == format(span.context.trace_id, "032x")
        assert line["span_id"] == format(span.context.span_id, "016x")
        assert dict(span.attributes or {})[CONTEXT_FIELD_REQUEST_ID] == (
            response.headers[REQUEST_ID_HEADER]
        )

    def test_the_span_spells_the_request_id_the_way_the_log_payload_does(
        self,
    ) -> None:
        """Two spellings of one fact make a join that finds nothing.

        ADR 0067's `CONTEXT_FIELDS` is the single place that decides the
        name; this is the check that the span attribute is drawn from
        the same vocabulary rather than typed out beside it.
        """
        assert CONTEXT_FIELD_REQUEST_ID in CONTEXT_FIELDS


# ---------------------------------------------------------------------------
# RED metrics
# ---------------------------------------------------------------------------


class TestTheRedMetrics:
    async def test_the_duration_histogram_is_keyed_on_the_route_template(
        self, monkeypatch: pytest.MonkeyPatch, reader: InMemoryMetricReader
    ) -> None:
        """The rule the specification states outright.

        Three requests to three different job ids are one series, not
        three. With the raw path they would be three, and a busy
        deployment would mint one per job for the retention of the
        metric store.
        """
        async with booted(monkeypatch) as (client, _):
            for job_id in ("aaaa", "bbbb", "cccc"):
                await client.get(f"/research/{job_id}")

        point = one_point(
            reader,
            DURATION_METRIC,
            **{
                "http.route": "/research/{job_id}",
                "http.request.method": "GET",
                "http.response.status_code": 404,
            },
        )
        assert point.count == 3
        assert dict(point.attributes)["url.scheme"] == "http"
        # A 4xx is the client's fault, not a server failure. Counting it
        # as one is how an availability SLI ends up measuring the
        # client's behaviour instead of ours.
        assert dict(point.attributes)["error.type"] == "none"

    async def test_the_histogram_count_is_the_request_count(
        self, monkeypatch: pytest.MonkeyPatch, reader: InMemoryMetricReader
    ) -> None:
        """Why there is no `http_requests_total` beside it.

        The stable conventions define no request counter because a
        histogram already carries one. A second instrument would double
        the write volume to answer a question this already answers,
        under a name no standard dashboard reads.
        """
        async with booted(monkeypatch) as (client, _):
            await client.get("/healthz")
            await client.get("/healthz")

        point = one_point(reader, DURATION_METRIC, **{"http.route": "/healthz"})
        assert point.count == 2
        assert point.sum >= 0

    async def test_a_server_error_names_the_exception_in_error_type(
        self, monkeypatch: pytest.MonkeyPatch, reader: InMemoryMetricReader
    ) -> None:
        """The leg that used to be empty.

        A Redis outage at submit moved no metric at all before this —
        the request never became a job, so no job counter could see it,
        and a fleet whose Redis had died read as idle. It is now a 500
        rate on `POST /research`, and `error.type` says which dependency
        died. `tests/fault/test_redis_faults.py` asserts the same thing
        from the fault tier's three-legged angle.
        """
        broken = InMemoryJobStore()

        async def _explode(_job: Any) -> None:
            raise ConnectionError("redis is gone")

        monkeypatch.setattr(broken, "create", _explode)

        async with booted(monkeypatch, store=broken) as (client, _):
            response = await client.post(
                "/research", json={"query": "q", "hitl_bypass": True}
            )

        assert response.status_code == 500
        point = one_point(
            reader,
            DURATION_METRIC,
            **{
                "http.route": "/research",
                "http.response.status_code": 500,
                "error.type": "ConnectionError",
            },
        )
        assert point.count == 1

    async def test_an_unknown_method_collapses_to_other(
        self, monkeypatch: pytest.MonkeyPatch, reader: InMemoryMetricReader
    ) -> None:
        """A cardinality attack anyone can fire from outside.

        `http.request.method` is attacker-controlled on an open port, so
        a loop sending `AAAA`…`ZZZZ` would mint a series per request.
        The conventions require the `_OTHER` substitution for exactly
        this, and it is a requirement rather than a nicety.
        """
        async with booted(monkeypatch) as (client, _):
            await client.request("PROPFIND", "/healthz")
            await client.request("SEARCH", "/healthz")

        recorded = {
            dict(point.attributes)["http.request.method"]
            for point in points(reader, DURATION_METRIC)
        }
        assert recorded == {"_OTHER"}

    async def test_in_flight_returns_to_zero(
        self, monkeypatch: pytest.MonkeyPatch, reader: InMemoryMetricReader
    ) -> None:
        """An UpDownCounter that only counts up reads as a permanently
        saturated worker, which is worse than no instrument at all."""
        async with booted(monkeypatch) as (client, _):
            await client.get("/healthz")
            await client.get("/research/nope")

        assert [point.value for point in points(reader, ACTIVE_METRIC)] == [0]

    async def test_it_decrements_even_when_the_application_raises(
        self, monkeypatch: pytest.MonkeyPatch, reader: InMemoryMetricReader
    ) -> None:
        """The half a `finally` exists for."""
        broken = InMemoryJobStore()

        async def _explode(_job: Any) -> None:
            raise ConnectionError("redis is gone")

        monkeypatch.setattr(broken, "create", _explode)

        async with booted(monkeypatch, store=broken) as (client, _):
            await client.post("/research", json={"query": "q", "hitl_bypass": True})

        assert [point.value for point in points(reader, ACTIVE_METRIC)] == [0]

    async def test_nothing_is_recorded_when_metrics_are_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shipped default. The record helpers return on their
        `None` check, so a disabled deployment pays one module-global
        load per request and nothing else."""
        metrics_module.shutdown_metrics()
        async with booted(monkeypatch) as (client, _):
            response = await client.get("/healthz")

        assert response.status_code == 200
        assert not metrics_module.metrics_enabled()


class TestTheConventionalErrorTypeRule:
    """`_http_error_type` in isolation — the three cases, in order."""

    def test_an_escaped_exception_is_named_by_its_class(self) -> None:
        assert _http_error_type(500, "ConnectionError") == "ConnectionError"

    def test_a_handled_5xx_falls_back_to_the_status(self) -> None:
        # ADR 0064's envelope leaves no exception to name, and the
        # conventions say to record the status code as a string.
        assert _http_error_type(503, None) == "503"

    @pytest.mark.parametrize("status_code", [200, 202, 304, 401, 404, 429])
    def test_nothing_below_500_is_an_error(self, status_code: int) -> None:
        assert _http_error_type(status_code, None) is None


# ---------------------------------------------------------------------------
# The liveness / readiness split
# ---------------------------------------------------------------------------


class TestTheHealthReadinessSplit:
    async def test_healthz_stays_200_while_a_dependency_is_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Kept deliberately, and safe *because* `/readyz` now exists.

        Restarting a worker does not fix a dead Redis, so a liveness
        probe that 503s on dependency failure turns a backend blip into
        a rolling-restart storm.
        """
        store = _PingStore(healthy=False)
        async with booted(monkeypatch, store=store) as (client, _):
            response = await client.get("/healthz")

        assert response.status_code == 200
        assert response.json()["status"] == "degraded"

    async def test_readyz_is_200_when_the_worker_can_take_work(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _PingStore(healthy=True)
        async with booted(monkeypatch, store=store) as (client, _):
            response = await client.get("/readyz")

        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "ok"
        assert body["dependencies"] == {"redis": "ok"}

    async def test_readyz_is_503_with_redis_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The drain signal that did not exist.

        Without it an orchestrator kept routing submits to a worker
        whose Redis had gone away, and every one of them could only 500.
        """
        store = _PingStore(healthy=False)
        async with booted(monkeypatch, store=store) as (client, _):
            response = await client.get("/readyz")

        body = response.json()
        assert response.status_code == 503
        assert body["status"] == "degraded"
        assert body["dependencies"]["redis"].startswith("error:")
        # The probe reports the exception *type*, never the message —
        # a redis connection error's text carries the URL, and
        # `redis_url` embeds the password (ADR 0042).
        assert "secret" not in json.dumps(body)

    async def test_readyz_recovers_when_the_dependency_does(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A readiness signal that latches is a worker that never comes
        back into rotation."""
        store = _PingStore(healthy=False)
        async with booted(monkeypatch, store=store) as (client, _):
            assert (await client.get("/readyz")).status_code == 503
            store.healthy = True
            assert (await client.get("/readyz")).status_code == 200

    async def test_readyz_is_503_when_every_permit_is_taken(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Saturation is a readiness fact, not a liveness one.

        A submit accepted here would sit in `pending` behind the
        ceiling. A balancer that skips this worker sends it to one that
        can start it now.
        """
        store = _PingStore(healthy=True)
        async with booted(monkeypatch, store=store, max_concurrent_jobs=1) as (
            client,
            app,
        ):
            held = asyncio.Event()
            task = asyncio.create_task(held.wait(), name="fake-in-flight-job")
            app.state.tasks.add(task)
            try:
                response = await client.get("/readyz")
                # `/healthz` is unmoved: the process is alive, and that
                # is the only question it answers.
                liveness = await client.get("/healthz")
            finally:
                held.set()
                await task
                app.state.tasks.discard(task)

        body = response.json()
        assert response.status_code == 503
        assert liveness.status_code == 200
        # No dependency failed, so the *reason* has to be readable from
        # the counts rather than from `status` — which is why the body
        # shape did not need a third status value.
        assert body["dependencies"] == {"redis": "ok"}
        assert body["active_jobs"] >= body["max_concurrent_jobs"]

    async def test_readyz_is_absent_from_the_generated_contract(self) -> None:
        """Deliberate, and worth pinning so it is a decision rather than
        an oversight.

        `web/contract/openapi.json` is the frontend's generated
        contract — snapshotted, regenerated into `schema.d.ts`, and
        pinned again in `web/tests/api.test.ts`. `/readyz` has no
        browser client, so publishing it would churn three `web/`
        artifacts to describe a route no generated client calls.
        """
        document = create_app().openapi()

        assert "/readyz" not in document["paths"]
        assert "/healthz" in document["paths"]

    async def test_both_probes_are_auth_exempt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An orchestrator probe cannot present a key.

        Safe because both report only counts and dependency *types* —
        nothing a caller could not learn by watching the service fail.
        """
        settings = Settings(enable_api_auth=True, api_keys="acme:s3cret")
        store = _PingStore(healthy=True)
        async with booted(monkeypatch, settings=settings, store=store) as (client, _):
            assert (await client.get("/healthz")).status_code == 200
            assert (await client.get("/readyz")).status_code == 200
            # The contrast: a real route still requires the key.
            assert (await client.get("/research/x")).status_code == 401
