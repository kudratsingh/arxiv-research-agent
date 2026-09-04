"""FastAPI application factory.

Owns the lifespan: the shared JobStore (in-memory or Redis-backed),
the workflow factory, the concurrency semaphore, the thread pool the
graph's synchronous nodes run on (ADR 0047), and the set of in-flight
tasks so shutdown can cancel them cleanly.

The factory takes injectable overrides for `build_workflow` and
`store` so tests can stub without patching `src.graph.workflow` or
`src.api.redis_store`.

It also owns the HTTP edge's observability: `ObservabilityMiddleware`
mints or adopts a request id, binds the ADR 0067 correlation context,
extracts inbound W3C trace context, records the RED metrics keyed on
the route template, and emits the one structured access line that
replaces uvicorn's (WO-A10).

The lifespan also runs the ADR-0038 startup redriver before serving
traffic, so jobs orphaned by the previous generation of workers are
reconciled (and their SSE clients unhung) rather than left claiming
`running` forever — and then keeps sweeping on
`settings.job_redrive_interval_sec` (ADR 0053), because the startup
sweep alone cannot see a lease that outlives the container it belonged
to.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import random
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.api.auth import (
    ApiKeyPrincipal,
    KeystoreReloader,
    build_rate_limiter,
    parse_api_keys,
    require_principal,
)
from src.api.conversations import (
    ConversationStore,
    build_conversation_store,
)
from src.api.jobs import InMemoryJobStore, Job, JobStore
from src.api.learn import router as learn_router
from src.api.redriver import (
    REDRIVE_LOCK_TTL_SEC,
    WORKER_ID,
    JobRedriver,
    RedriveReport,
)
from src.api.routes import router
from src.api.runner import SHUTDOWN_DRAIN_SEC, run_job
from src.api.sessions import router as session_router
from src.cancellation import abandoned_node_count
from src.config import settings
from src.errors import (
    ERROR_CODES,
    AppError,
    InvalidRequestError,
    error_class_for_code,
    error_class_for_status,
    error_envelope,
)
from src.graph.session_workflow import (
    build_session_workflow as default_build_session_workflow,
)
from src.graph.workflow import build_workflow as default_build_workflow
from src.learning.profile_store import (
    ProfileStore,
    build_profile_store,
    skill_entry_from_mapping,
)
from src.learning.progress_store import (
    ProgressEvent,
    ProgressEventStore,
    build_progress_event_store,
)
from src.observability import get_logger
from src.observability.context import (
    bind_context,
    hash_principal,
    reset_context,
)
from src.observability.metrics import (
    configure_metrics,
    metrics_enabled,
    record_http_active_request,
    record_http_server_request,
    register_runtime_gauges,
    shutdown_metrics,
)
from src.observability.semconv import (
    ERROR_TYPE,
    HTTP_REQUEST_METHOD,
    HTTP_RESPONSE_STATUS_CODE,
    HTTP_ROUTE,
    URL_SCHEME,
    http_request_method,
)
from src.observability.tracing import (
    attached_trace_context,
    get_tracer,
    shutdown_tracing,
)

log = get_logger(__name__)


def _request_id(request: Request) -> str:
    """The correlation id for one failed request.

    `ObservabilityMiddleware` has already put one on `request.state` and
    on every log record for this request, so this reads it back rather
    than minting a competing second identity — the seam ADR 0064 left
    open, now closed by WO-A10.

    The fallback survives because the handlers are reachable without the
    middleware: `TestClient(app)` on a router mounted by hand, and any
    caller that invokes a handler directly. An id minted here is still
    better than none — it ties the client's error body to the ERROR log
    line beside it, which is the whole reason the field exists.
    """
    existing = getattr(request.state, "request_id", None)
    return existing if isinstance(existing, str) and existing else uuid.uuid4().hex


def _error_response(
    request: Request,
    error: AppError,
    *,
    http_status: int | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """One envelope, one place, for all four handlers.

    `http_status` overrides the class's own status, and exists for
    exactly one caller: the `HTTPException` bridge. A 405 from the
    router has no class of its own, so it borrows the `invalid_*`
    family for its *code* — but it must still answer 405, or the
    bridge would silently rewrite every status the taxonomy has not
    given a class to.

    The response carries `X-Request-Id` as well as the body field. The
    Next.js proxy does not forward it today
    (`web/app/api/[...path]/route.ts`'s response allowlist), but
    `web/lib/api/errors.ts` already reads the header when it is present,
    so emitting it costs nothing and closes half the loop early.
    """
    request_id = _request_id(request)
    merged = {"X-Request-Id": request_id}
    if error.headers is not None:
        merged.update(error.headers)
    if headers is not None:
        merged.update(headers)
    return JSONResponse(
        status_code=http_status if http_status is not None else error.http_status,
        content=error_envelope(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            request_id=request_id,
            detail=error.wire_detail,
        ),
        headers=merged,
    )


def _log_boundary_error(
    request: Request,
    error: AppError,
    *,
    request_id: str,
    exc_info: bool,
    http_status: int | None = None,
) -> None:
    """Record the failure with the detail the client never sees.

    This is the other half of "stop leaking raw exception text": the
    text still has to go *somewhere*, and the somewhere is here, with
    the request id that the client was handed. Client errors (4xx) log
    at WARNING because a stream of them is a client problem worth
    seeing but not an incident; 5xx logs at ERROR with `exc_info`,
    which is the line that did not exist before this work order — an
    unhandled exception used to produce an untyped Starlette 500 and no
    log on that path at all.
    """
    status_code = http_status if http_status is not None else error.http_status
    payload = {
        "request_id": request_id,
        # `error_type` and `error`, not `error_code`/`error_detail`:
        # ADR 0067's `extra` allowlist already carries both names, they
        # are what every other failure line in this codebase uses, and
        # `error_type` is now literally the code.
        "error_type": error.code,
        "http_status": status_code,
        "method": request.method,
        # The route *template*, never the raw path: a path carries job
        # and conversation ids, and this string is a log field that
        # ends up grouped.
        "route": getattr(request.scope.get("route"), "path", None),
        # The human-readable half. Never in the response body.
        "error": error.log_detail,
    }
    if status_code >= 500:
        log.error("api_request_failed", extra=payload, exc_info=exc_info)
    else:
        log.warning("api_request_rejected", extra=payload, exc_info=exc_info)


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    """`AppError` — the typed path. The code is already decided."""
    error = exc if isinstance(exc, AppError) else AppError(str(exc))
    request_id = _request_id(request)
    request.state.request_id = request_id
    # `exc_info` only for the 5xx half: a 404 for a job that does not
    # exist is not worth a traceback, and 20 of them a second would
    # bury the ones that are.
    _log_boundary_error(
        request, error, request_id=request_id, exc_info=error.http_status >= 500
    )
    return _error_response(request, error)


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """`HTTPException` — the shapes that predate the taxonomy.

    Every `HTTPException` this repository raises has been converted to
    an `AppError`, so what reaches here is either FastAPI's own (a 405
    from the router, say) or one raised by a module this work order
    does not own (`src/api/learn.py`). Both still get a code: the
    `detail` string is looked up in `ERROR_CODES` first, and the status
    supplies the family code when it is not there.

    The `detail` value itself is passed through *verbatim*. That is
    what makes the envelope additive rather than breaking: the current
    web client reads structure out of two of these shapes, and the
    recorded fixtures in `web/contract/fixtures/` hold them.
    """
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - defensive
        return await _handle_app_error(request, exc)
    detail = exc.detail
    error_class = (
        error_class_for_code(detail)
        if isinstance(detail, str) and detail in ERROR_CODES
        else None
    ) or error_class_for_status(exc.status_code)
    error = error_class(
        log_detail=detail if isinstance(detail, str) else repr(detail),
        wire_detail=detail,
    )
    request_id = _request_id(request)
    request.state.request_id = request_id
    _log_boundary_error(
        request,
        error,
        request_id=request_id,
        exc_info=exc.status_code >= 500,
        http_status=exc.status_code,
    )
    return _error_response(
        request,
        error,
        http_status=exc.status_code,
        headers=dict(exc.headers or {}),
    )


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """`RequestValidationError` — FastAPI's 422 array, wrapped not replaced.

    `detail` keeps the `[{loc, msg, type}, ...]` array because the web
    client turns it into per-field messages
    (`readFieldIssues` in `web/lib/api/errors.ts`, rendered by the plan
    editor). Replacing it with a bare code would silently downgrade
    every form error in the product to "The request was rejected as
    invalid."
    """
    errors: list[Any] = (
        jsonable_encoder(exc.errors()) if isinstance(exc, RequestValidationError) else []
    )
    error = InvalidRequestError(log_detail=f"{len(errors)} field(s) rejected", wire_detail=errors)
    request_id = _request_id(request)
    request.state.request_id = request_id
    _log_boundary_error(request, error, request_id=request_id, exc_info=False)
    return _error_response(request, error)


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Bare `Exception` — the handler whose absence was the finding.

    Without it an unhandled exception became an untyped Starlette 500
    with no structured body and, on that path, no ERROR log anywhere.
    Now it is `internal_unexpected`, 500, with a traceback in the log
    and — the point — nothing of `str(exc)` in the response. psycopg,
    redis and httpx messages embed DSNs, hostnames and filesystem
    paths; that is exactly the text this handler exists to keep inside
    the process.

    Starlette's `ServerErrorMiddleware` re-raises after this returns,
    so the ASGI server still sees the exception and a test client
    constructed with `raise_app_exceptions=True` still fails loudly.
    """
    error = AppError(log_detail=f"{type(exc).__name__}: {exc}")
    request_id = _request_id(request)
    request.state.request_id = request_id
    _log_boundary_error(request, error, request_id=request_id, exc_info=True)
    return _error_response(request, error)


# ---------------------------------------------------------------------------
# The observability middleware (WO-A10)
# ---------------------------------------------------------------------------

#: Both the header a caller may supply and the one every response
#: carries back. One name in both directions, because a gateway that
#: stamps an id on the way in expects to read it on the way out.
REQUEST_ID_HEADER: Final = "X-Request-Id"

#: The span attribute for the request id. It must be the name ADR
#: 0067's `CONTEXT_FIELDS` gives the same fact — the log payload and the
#: span have to spell it identically or a query joining a trace to its
#: lines finds nothing. Written out rather than indexed out of that
#: tuple, because a positional index into a field list is a bug waiting
#: for a reordering; `tests/test_api_middleware.py` asserts the
#: membership instead.
CONTEXT_FIELD_REQUEST_ID: Final = "request_id"

#: An inbound request id is caller-controlled text that ends up in an
#: indexed log store, in a response header, and on a span. So it is
#: adopted only when it looks like an identifier: the character class is
#: what a UUID, a ULID, a W3C trace id or an nginx `$request_id` all fit
#: inside, and nothing else. Anything outside it — a newline aimed at
#: the log stream, a 4 KB blob aimed at the index, a header-splitting
#: `\r\n` — is not sanitized, it is discarded, and a fresh id is minted
#: in its place. Sanitizing would keep an attacker's string on the line
#: in a mangled form; discarding keeps the field trustworthy.
MAX_REQUEST_ID_CHARS: Final = 128
_REQUEST_ID_PATTERN: Final = re.compile(rf"\A[A-Za-z0-9._:\-]{{1,{MAX_REQUEST_ID_CHARS}}}\Z")

#: Cap for `http.request.method_original`, which is raw client bytes and
#: is only ever set on a *span* (never on a metric attribute — that is
#: what `_OTHER` is for). Sixteen characters is longer than every method
#: any registry defines and short enough that the field cannot become a
#: payload.
_MAX_METHOD_ORIGINAL_CHARS: Final = 16


def _resolve_request_id(headers: Headers) -> str:
    """Adopt the caller's request id, or mint one.

    Adopting matters more than minting: a request that arrives from the
    Next.js proxy, a load balancer or another service already has an id
    in that hop's logs, and minting a second one here means an operator
    holding the caller's id can never find our side of the same request.

    Args:
        headers: The inbound request headers.

    Returns:
        The caller's id when it is well-formed, else a fresh hex id.
    """
    supplied = headers.get(REQUEST_ID_HEADER)
    if supplied and _REQUEST_ID_PATTERN.match(supplied):
        return supplied
    return uuid.uuid4().hex


def _http_error_type(status_code: int, exception_type: str | None) -> str | None:
    """The conventional `error.type` for one served request.

    Three cases, in the order the conventions state them:

    - The application raised before or during the response — the
      exception's class name, which is the most specific fact available.
    - The response was a 5xx — the status code as a string. A 5xx that
      was *handled* (ADR 0064's envelope) has no exception to name, and
      the conventions say to fall back to the status.
    - Anything else, 4xx included — no error. A client sending a bad
      request is not a server failure, and counting it as one is how an
      availability SLI ends up measuring the client's behaviour.

    Args:
        status_code: The status actually sent, or 500 when nothing was.
        exception_type: Class name of an exception that escaped, or None.

    Returns:
        The attribute value, or None for a request that did not fail.
    """
    if exception_type is not None:
        return exception_type
    if status_code >= 500:
        return str(status_code)
    return None


def _route_template(scope: Scope) -> str | None:
    """The matched route template, or None when nothing matched.

    FastAPI puts the matched `APIRoute` on the scope during routing, so
    this is only meaningful *after* the application has run — which is
    why every caller here reads it in a `finally`.

    Never the raw path. `/research/{job_id}` is one series and one log
    field; `/research/9f2c…` is one per job, and both a metric store and
    a log index charge for that by the cardinal.
    """
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else None


class ObservabilityMiddleware:
    """One pass over every HTTP request: id, context, trace, RED, access.

    A raw ASGI middleware rather than a `BaseHTTPMiddleware` subclass,
    and that is not a style preference. `BaseHTTPMiddleware` runs the
    downstream application in a separate anyio task and proxies
    `receive` through a memory stream, which breaks
    `Request.is_disconnected()` — the exact call `stream_research` uses
    to decide when to stop an SSE stream (`routes.py`). Wrapping the
    streaming surface of this app in a middleware that hides client
    disconnects would trade an access log for leaked pub/sub
    connections. A raw ASGI callable touches neither channel: it reads
    the status off `http.response.start` on the way past and otherwise
    hands `receive` and `send` through untouched.

    Five things happen here, in one place because they all key off the
    same request and would otherwise be five things that could disagree
    about which request they were describing:

    1. **A request id**, adopted from the caller when well-formed
       (`_resolve_request_id`) and echoed in the response header. It
       lands on `scope["state"]` too, which is where ADR 0064's error
       envelope reads it from, so the body, the header and the log line
       carry one value.
    2. **The ADR 0067 context**, bound for the life of the request, so
       every line any code emits under it carries `request_id` and —
       when auth is on — a salted `principal_hash`.
    3. **Inbound W3C trace context**, extracted at the edge. ADR 0066
       already made a job one trace from submission inward; this is the
       missing outer hop, so a caller's trace continues into ours
       instead of stopping at the socket.
    4. **RED metrics**, keyed on the route *template*.
    5. **One structured access line**, replacing uvicorn's prose one
       (`serve.py` turns that off).

    Ordering note: this middleware is added **last** in `create_app`,
    which makes it the outermost user middleware — so a CORS preflight,
    a 404 for an unrouted path and a 405 from the router are all
    measured, and the duration includes everything below it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Lifespan and websocket scopes have no status, no route and
            # no duration worth a histogram. Nothing to add, so add
            # nothing rather than half of it.
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = _resolve_request_id(headers)
        # `scope["state"]` is what `Request.state` is backed by, so
        # writing here is what makes `_request_id(request)` in the
        # exception handlers below read the same value.
        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        method = http_request_method(scope.get("method", ""))
        raw_method = scope.get("method", "")
        scheme = scope.get("scheme", "http")

        status_code = 500
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                message.setdefault("headers", [])
                response_headers = MutableHeaders(scope=message)
                # ADR 0064's `_error_response` sets this itself, with the
                # same value; appending a second copy would hand the
                # client two headers of one name and let a proxy pick.
                if REQUEST_ID_HEADER not in response_headers:
                    response_headers.append(REQUEST_ID_HEADER, request_id)
            await send(message)

        principal_hash = await _principal_hash(scope, receive)
        started = time.perf_counter()
        token = bind_context(request_id=request_id, principal_hash=principal_hash)
        # Last statement before the `try`, so the `+1` and the `-1` in
        # its `finally` are a pair by construction. Anything between
        # them that could raise would leave the counter climbing, and a
        # counter that only climbs reads as a permanently saturated
        # worker.
        record_http_active_request(method=method, scheme=scheme, delta=1)
        exception_type: str | None = None
        try:
            with contextlib.ExitStack() as stack:
                # The whole header mapping, not a hand-picked
                # `traceparent`: the propagator decides which keys it
                # owns, so a deployment that configures B3 or Jaeger
                # propagation keeps working without an edit here.
                stack.enter_context(attached_trace_context(dict(headers)))
                span = self._start_span(stack, method, scheme, request_id)
                try:
                    await self._app(scope, receive, send_wrapper)
                except BaseException as exc:
                    # `BaseException`, so a client disconnect
                    # (`CancelledError` on an SSE stream) is measured
                    # and logged like any other outcome rather than
                    # vanishing. Re-raised untouched: this middleware
                    # observes, it does not handle.
                    exception_type = type(exc).__name__
                    raise
                finally:
                    self._finish(
                        span=span,
                        scope=scope,
                        method=method,
                        raw_method=raw_method,
                        scheme=scheme,
                        # A response that never started is a 500 to the
                        # client, whatever the ASGI server writes on the
                        # socket, so it is recorded as one.
                        status_code=status_code if response_started else 500,
                        exception_type=exception_type,
                        duration_sec=time.perf_counter() - started,
                    )
        finally:
            reset_context(token)
            record_http_active_request(method=method, scheme=scheme, delta=-1)

    def _start_span(
        self,
        stack: contextlib.ExitStack,
        method: str,
        scheme: str,
        request_id: str,
    ) -> trace.Span | None:
        """Open the SERVER span, or None when tracing is off.

        Guarded on the flag rather than relying on OTel's no-op tracer,
        and the reason is a correctness one rather than a cost one: a
        no-op tracer makes `INVALID_SPAN` current, which would *replace*
        an inbound trace context that had just been attached — so a
        deployment with tracing off would silently stop propagating a
        caller's `traceparent` onto the job row it submitted.

        The span is named for the method alone; `_finish` renames it
        once routing has said which template matched, which is the same
        two-step every ASGI instrumentation performs because a span has
        to start before the router runs.

        `request_id` rides on the span so trace-to-log navigation works
        in both directions: the access line names the span, and the span
        names the id every other line for that request carries. Only
        this one context field is set — `run_id`, `job_id` and
        `job_kind` are not bound at the HTTP edge, and copying an
        unbound field would write nothing but noise.
        """
        if not settings.enable_tracing:
            return None
        span = stack.enter_context(
            get_tracer().start_as_current_span(method, kind=trace.SpanKind.SERVER)
        )
        span.set_attribute(HTTP_REQUEST_METHOD, method)
        span.set_attribute(URL_SCHEME, scheme)
        span.set_attribute(CONTEXT_FIELD_REQUEST_ID, request_id)
        return span

    def _finish(
        self,
        *,
        span: trace.Span | None,
        scope: Scope,
        method: str,
        raw_method: str,
        scheme: str,
        status_code: int,
        exception_type: str | None,
        duration_sec: float,
    ) -> None:
        """Close out one request: span, metric, access line — in that order.

        Order matters only for the last step: the access line is emitted
        while the span is still current, so it carries `trace_id` and
        `span_id` and an operator can jump from the line to the trace.
        """
        route = _route_template(scope)
        error_type = _http_error_type(status_code, exception_type)

        if span is not None:
            if route is not None:
                # `{method} {route}` is the conventional server span
                # name, and it cannot be known before the router runs.
                span.update_name(f"{method} {route}")
                span.set_attribute(HTTP_ROUTE, route)
            if method != raw_method and raw_method:
                # Conditionally required when the method was replaced by
                # `_OTHER`. On the span only: a span is one record, so
                # unbounded input costs one field, whereas the same
                # value on a metric attribute would mint a series per
                # value — which is the attack `_OTHER` exists to stop.
                span.set_attribute(
                    "http.request.method_original",
                    raw_method[:_MAX_METHOD_ORIGINAL_CHARS],
                )
            span.set_attribute(HTTP_RESPONSE_STATUS_CODE, status_code)
            if error_type is not None:
                span.set_attribute(ERROR_TYPE, error_type)
                span.set_status(trace.Status(trace.StatusCode.ERROR, error_type))

        record_http_server_request(
            method=method,
            route=route,
            status_code=status_code,
            scheme=scheme,
            duration_sec=duration_sec,
            error_type=error_type,
        )

        # One line per served request, always INFO. The 4xx/5xx
        # judgement is already made — and made once — by ADR 0064's
        # `api_request_rejected` / `api_request_failed`; a second
        # WARNING here would double-report every failure and make
        # "count of WARNING lines" mean nothing.
        #
        # `request_id`, `principal_hash`, `trace_id` and `span_id` are
        # not passed: they are on the bound context and the formatter
        # puts them on every line, and passing them again would be a
        # second spelling of the same fact.
        log.info(
            "api_request_completed",
            extra={
                "method": method,
                "route": route,
                "http_status": status_code,
                "elapsed_ms": round(duration_sec * 1000, 3),
                "error_type": error_type,
            },
        )


async def _principal_hash(scope: Scope, receive: Receive) -> str | None:
    """The salted digest of the calling principal, best-effort.

    Resolved through `require_principal` — the same function the routes
    depend on — rather than through a second copy of the lookup, so the
    log stream cannot come to disagree with the authorization decision
    about who a caller is. It costs one extra constant-time keystore
    scan per request, which is the price of not having two answers.

    Every failure is swallowed and returns `None`. This function
    authorizes nothing: a missing or invalid key must still produce the
    401 the route dependency raises, and an observability helper that
    could turn a request into a 500 would be a worse bug than the
    missing field it was added to supply.

    Args:
        scope: The ASGI scope, for `app.state.api_keys` and the header.
        receive: Passed to `Request` and never called — the body is not
            read here, and reading it would consume it before the route.

    Returns:
        A 12-character salted digest, or None when auth is off, the key
        is absent or invalid, or anything at all went wrong.
    """
    try:
        principal = await require_principal(Request(scope, receive))
    except Exception:  # noqa: BLE001 - observability must never fail a request
        return None
    if principal is None:
        return None
    return hash_principal(principal.key_id)


# How often the in-memory retention sweep runs (ADR 0040). Coarse on
# purpose: retention is measured in hours, so a five-minute cadence
# bounds staleness at a fraction of the window without waking an idle
# worker constantly. Module-level so tests can shrink it.
EVICT_SWEEP_INTERVAL_SEC = 300


async def _evict_terminal_jobs_forever(store: JobStore) -> None:
    """Periodically evict old terminal jobs until cancelled (ADR 0040).

    Runs as a lifespan-owned background task for stores whose
    retention is not backend-managed — without it,
    `settings.api_job_retention_sec` was documented but unenforced for
    `InMemoryJobStore`: every finished job's full report stayed
    resident until the process died. A sweep failure is logged and the
    loop keeps going; retention is housekeeping, never a crash.

    Args:
        store: The job store to sweep via its `evict_older_than`.
    """
    while True:
        await asyncio.sleep(EVICT_SWEEP_INTERVAL_SEC)
        try:
            evicted = await store.evict_older_than(settings.api_job_retention_sec)
            if evicted:
                log.info("api_jobs_evicted", extra={"count": evicted})
        except Exception:
            log.warning("api_job_evict_sweep_failed", exc_info=True)


# Fraction of one interval the periodic redrive waits before its first
# sweep (ADR 0053). A fleet started by one `docker compose up` / one
# rollout boots in lockstep, so an unjittered timer would put every
# worker's sweep on the same second: all but one would find the
# redrive lock taken and log `job_redriver_skipped_locked` forever,
# and the reclaim would depend on whichever worker happened to win.
# Spreading the phase over a quarter of the interval decorrelates them
# without meaningfully delaying the first sweep.
REDRIVE_JITTER_RATIO = 0.25


async def _redrive_forever(
    redriver: JobRedriver,
    interval_sec: float,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Re-run the redrive sweep on a fixed interval until cancelled.

    ADR 0053. ADR 0038's sweep ran once, at startup, which misses the
    case that motivated leases in the first place: a container SIGKILLed
    (OOM, `docker compose kill`, a grace-period overrun) and restarted
    by `restart: unless-stopped` inside `job_lease_ttl_sec` comes back
    to find its *own* dead lease still live in Redis. The boot sweep
    correctly declines to touch the job — from the outside a live lease
    is indistinguishable from a healthy peer mid-run — and then no
    later sweep ever happens, so the row stays `running` forever, with
    `GET /research/{id}` and the SSE stream both waiting on a terminal
    frame nobody will publish. A sweep an interval later sees the
    expired lease and reclaims it.

    Failures never break the loop: reconciliation is best-effort
    housekeeping, and a redriver bug must not take a serving worker
    down with it. Cancellation propagates so shutdown stays prompt.

    Args:
        redriver: Sweeper to run. Constructed once by the caller so
            every sweep shares the worker id and the resubmit hook.
        interval_sec: Seconds between sweeps.
        sleep: Injectable for tests, which assert the cadence rather
            than living through it.
    """
    # Phase offset first, then a full interval — the startup sweep has
    # already run by the time this task exists, so sweeping immediately
    # would only re-take the lock for a keyspace just examined.
    await sleep(random.uniform(0, interval_sec * REDRIVE_JITTER_RATIO))
    while True:
        await sleep(interval_sec)
        try:
            # Same bound as the startup sweep: past the lock's TTL this
            # sweep no longer holds it, so continuing would just race
            # whoever took it next.
            report = await asyncio.wait_for(redriver.sweep(), timeout=REDRIVE_LOCK_TTL_SEC)
        except TimeoutError:
            log.warning(
                "job_redriver_periodic_timeout",
                extra={
                    "worker_id": WORKER_ID,
                    "timeout_sec": REDRIVE_LOCK_TTL_SEC,
                },
            )
            continue
        except Exception:
            log.exception(
                "job_redriver_periodic_failed",
                extra={"worker_id": WORKER_ID},
            )
            continue
        if report.orphaned or report.failed or report.requeued:
            # Silent on an empty sweep — this runs every few minutes on
            # every worker, and the steady state is "nothing to do".
            log.info(
                "job_redriver_periodic_reclaimed",
                extra={
                    "worker_id": WORKER_ID,
                    "redrive_orphaned": report.orphaned,
                    "redrive_failed": report.failed,
                    "redrive_requeued": report.requeued,
                    "redrive_skipped_live": report.skipped_live,
                },
            )


def _default_store() -> JobStore:
    """Pick the JobStore implementation from settings.

    Isolated so tests can inject their own store via `create_app(store=...)`
    without touching `settings.job_store`. Also keeps the `redis`
    import lazy so the in-memory path never touches the redis client
    at import time.
    """
    if settings.job_store == "redis":
        # Lazy import — the redis client isn't needed unless we're
        # selecting the Redis-backed store. Keeps `create_app()` fast
        # for the in-memory / test path.
        from src.api.redis_store import RedisJobStore, build_redis_client

        client = build_redis_client(settings.redis_url)
        # Backend name only — `redis_url` carries credentials inline
        # and structured log fields get indexed verbatim (audit P2).
        log.info("api_store_selected", extra={"store": "redis"})
        return RedisJobStore(client)
    log.info("api_store_selected", extra={"store": "memory"})
    return InMemoryJobStore()


def create_app(
    *,
    build_workflow: Callable[[], Any] | None = None,
    build_session_workflow: Callable[[], Any] | None = None,
    store: JobStore | None = None,
    conversation_store: ConversationStore | None = None,
    profile_store: ProfileStore | None = None,
    progress_event_store: ProgressEventStore | None = None,
    max_concurrent_jobs: int | None = None,
) -> FastAPI:
    """Build a FastAPI app instance.

    Args:
        build_workflow: Zero-arg factory that returns a compiled
            LangGraph app. Defaults to the production workflow. Tests
            inject a stub that yields fake state updates.
        build_session_workflow: Optional zero-arg guided-session graph
            factory. When omitted beside an injected research factory,
            the injection is reused so legacy app tests do not open a
            second real checkpointer.
        store: Persistence layer. Defaults to whichever `JobStore`
            `settings.job_store` selects (`memory` / `redis`).
        conversation_store: Conversation persistence (ADR 0032).
            Defaults to whichever `ConversationStore`
            `settings.conversation_store` selects
            (`memory` / `postgres`).
        profile_store: Learner-profile persistence (ADR 0058).
            Defaults to whichever `ProfileStore`
            `settings.learner_profile_store` selects. Constructed
            regardless of `enable_learner_profile` — both
            implementations are inert until a method runs, and the
            route layer owns the flag check, so the flag stays a
            single decision in one place.
        progress_event_store: Append-only learner progress ledger
            (WO-W07). Defaults to whichever `ProgressEventStore`
            `settings.progress_event_store` selects, and constructed
            unconditionally for the same reason as the profile store.
        max_concurrent_jobs: Semaphore ceiling. Defaults to
            `settings.api_max_concurrent_jobs`.
    """

    def _make_workflow(node_executor: ThreadPoolExecutor) -> Any:
        """Compile the graph this app will serve every job from.

        ADR 0040: the API runner drives the graph through its async
        surface, so the production factory compiles with the ASYNC
        savers — the sync default (CLI / eval runner) would kill every
        job with `NotImplementedError` before its first node.

        ADR 0047: it also hands the graph the app's node pool, so the
        synchronous agent functions run somewhere bounded and
        observable instead of on the event loop's default executor.
        An injected test factory is called as-is; stub workflows have
        no real nodes to place.
        """
        if build_workflow is not None:
            return build_workflow()
        return default_build_workflow(async_checkpointer=True, node_executor=node_executor)

    def _make_session_workflow(node_executor: ThreadPoolExecutor) -> Any:
        if build_session_workflow is not None:
            return build_session_workflow()
        if build_workflow is not None:
            return build_workflow()
        return default_build_session_workflow(async_checkpointer=True, node_executor=node_executor)

    job_store: JobStore = store if store is not None else _default_store()
    conv_store: ConversationStore = (
        conversation_store if conversation_store is not None else build_conversation_store()
    )
    prof_store: ProfileStore = profile_store if profile_store is not None else build_profile_store()
    # WO-W07: built unconditionally, for the reason above. The default
    # `memory` variant touches nothing, so `enable_learner_profile` stays
    # the single gate and a flag-off deployment builds an empty ledger it
    # never reads.
    progress_store: ProgressEventStore = (
        progress_event_store if progress_event_store is not None else build_progress_event_store()
    )
    max_concurrent = max_concurrent_jobs or settings.api_max_concurrent_jobs

    # ADR 0033: parse API keys + build the rate limiter once at
    # startup so every request handler shares the same instances.
    # `enable_api_auth=False` still parses (an empty string yields
    # an empty dict) so a misconfigured `api_keys` value fails fast
    # regardless of the flag.
    #
    # ADR 0037: when `api_keys_file` is set, that file is the source
    # of truth and gets loaded + watched by `KeystoreReloader` inside
    # the lifespan. Otherwise the string is the source of truth.
    api_keys = parse_api_keys(settings.api_keys)

    # ADR 0037: rate limiter backend is pluggable. Redis backend
    # needs a client; we prefer to share the JobStore's if it's the
    # Redis variant, so we don't open a second connection pool.
    redis_client_for_rl: Any = getattr(job_store, "_client", None)
    rate_limiter = build_rate_limiter(
        settings.api_key_hourly_limit,
        settings.rate_limit_backend,
        redis_client=redis_client_for_rl,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # ADR 0034: compile the workflow ONCE at startup. The old
        # code invoked `build_workflow()` per request, which opened
        # a fresh checkpointer + ExitStack per job — a slow leak of
        # DB connections and, under SqliteSaver, a corruption risk
        # on the shared file across concurrent writers.
        #
        # ADR 0047: the pool every synchronous graph node runs on,
        # sized to the job ceiling so `api_max_concurrent_jobs` bounds
        # threads and not just coroutines. Built before the workflow
        # because the compiled graph closes over it. Threads are
        # spawned lazily on first submit, so a factory that raises
        # below leaks nothing.
        node_executor = ThreadPoolExecutor(
            max_workers=max_concurrent, thread_name_prefix="graph-node"
        )
        app.state.node_executor = node_executor

        # ADR 0040: the async-checkpointer factory returns an
        # awaitable (opening AsyncSqliteSaver / the Postgres pool
        # needs a running loop, which this lifespan is). Test-injected
        # stub factories stay plain callables, hence the check.
        compiled_workflow = _make_workflow(node_executor)
        if inspect.isawaitable(compiled_workflow):
            compiled_workflow = await compiled_workflow
        if build_session_workflow is None and build_workflow is not None:
            # A legacy injected factory represents one test/stub graph. Reuse
            # its compiled instance instead of invoking the factory twice;
            # tests that exercise sessions inject the second factory
            # explicitly.
            compiled_session_workflow = compiled_workflow
        else:
            compiled_session_workflow = _make_session_workflow(node_executor)
            if inspect.isawaitable(compiled_session_workflow):
                compiled_session_workflow = await compiled_session_workflow
        app.state.workflow = compiled_workflow
        app.state.session_workflow = compiled_session_workflow
        app.state.store = job_store
        app.state.conversation_store = conv_store
        app.state.profile_store = prof_store
        app.state.progress_event_store = progress_store
        app.state.semaphore = asyncio.Semaphore(max_concurrent)
        app.state.max_concurrent_jobs = max_concurrent
        app.state.tasks = set()
        app.state.rate_limiter = rate_limiter
        # ADR 0038: one id per process, stamped on job leases and the
        # redrive lock so every reclaim is attributable to a worker.
        app.state.worker_id = WORKER_ID
        # ADR 0053: dependencies `/healthz` has already logged as down,
        # so the handler logs the transition and not every probe.
        # Lifespan-owned rather than module-global so two apps in one
        # test process cannot latch each other's health edges.
        app.state.degraded_dependencies = set()

        # ADR 0049: install the meter provider before anything can
        # record, and hand the two observable gauges the *same*
        # accounting `/healthz` reports from rather than a second set
        # of counters that could drift from it. Both calls no-op when
        # `enable_metrics` is off, so this stays unconditional.
        configure_metrics()
        register_runtime_gauges(
            active_jobs=lambda: len(app.state.tasks) + abandoned_node_count(),
            abandoned_node_threads=abandoned_node_count,
        )

        # ADR 0038: reconcile whatever the previous generation of
        # workers left stuck in a non-terminal status. Awaited rather
        # than fired-and-forgotten: a sweep racing the first request
        # could reclaim a job the new worker had just accepted, and a
        # slightly slower boot is the cheaper trade. Any failure is
        # logged and swallowed — reconciliation is best-effort, and a
        # redriver bug must never stop the app from starting.
        async def _resubmit_orphaned(job: Job) -> None:
            """Put a reclaimed `pending` job back in flight (ADR 0038).

            Only reached for jobs the redriver found in `pending` —
            accepted but never started, so there is no partial work
            and no LLM spend to double-charge for. Mirrors the spawn
            in `submit_research`: same workflow, same semaphore, and
            registered in `app.state.tasks` so shutdown cancels it
            like any other in-flight job.

            The redriver drops its own claim on the job's lease
            before calling this, so `run_job` can take the lease
            itself.

            Args:
                job: The reclaimed job, already reset to `pending`.
            """
            task = asyncio.create_task(
                run_job(
                    job,
                    workflow=(
                        compiled_session_workflow if job.kind == "session" else compiled_workflow
                    ),
                    store=job_store,
                    semaphore=app.state.semaphore,
                    conversation_store=conv_store,
                    progress_event_store=progress_store,
                    progress_event_decoder=ProgressEvent.from_json_dict,
                    profile_store=prof_store,
                    profile_skill_decoder=skill_entry_from_mapping,
                ),
                name=f"job-{job.job_id}",
            )
            app.state.tasks.add(task)
            task.add_done_callback(app.state.tasks.discard)

        redrive_report = RedriveReport()
        redriver = JobRedriver(job_store, resubmit=_resubmit_orphaned)
        if settings.enable_job_redriver:
            try:
                # Bounded by the redrive lock's own TTL. Past that the
                # sweep no longer holds the lock, so continuing would
                # only race whoever took it next — and `build_redis_client`
                # sets no socket timeout, so an unreachable Redis would
                # otherwise hold the process in "starting" indefinitely.
                redrive_report = await asyncio.wait_for(
                    redriver.sweep(), timeout=REDRIVE_LOCK_TTL_SEC
                )
            except TimeoutError:
                log.warning(
                    "job_redriver_startup_timeout",
                    extra={
                        "worker_id": WORKER_ID,
                        "timeout_sec": REDRIVE_LOCK_TTL_SEC,
                    },
                )
            except Exception:
                log.exception(
                    "job_redriver_startup_failed",
                    extra={"worker_id": WORKER_ID},
                )

        # ADR 0040: periodic retention sweep for stores that have no
        # backend-managed retention. Duck-typed like the other store
        # capabilities (`publish_event`, `acquire_lease`): a store
        # advertising `scan_jobs` manages retention in the backend —
        # RedisJobStore expires terminal rows via key TTL (ADR 0027) —
        # while the in-memory store's `evict_older_than` previously
        # had no production caller at all, so terminal jobs (full
        # report included) accumulated until the process died.
        evict_task: asyncio.Task[None] | None = None
        if not callable(getattr(job_store, "scan_jobs", None)):
            evict_task = asyncio.create_task(
                _evict_terminal_jobs_forever(job_store),
                name="job-retention-sweep",
            )

        # ADR 0053: keep sweeping after boot. Guarded on the same flag
        # as the startup sweep and on the same store capability the
        # redriver itself checks — under `InMemoryJobStore` nothing
        # survives a restart, so a recurring sweep would burn a task to
        # log `job_redriver_store_unsupported` forever. Cross-worker
        # serialization is already handled: every sweep takes the
        # redrive lock, so only one worker in the fleet reclaims per
        # tick and the rest no-op.
        redrive_task: asyncio.Task[None] | None = None
        if settings.enable_job_redriver and callable(getattr(job_store, "scan_jobs", None)):
            redrive_task = asyncio.create_task(
                _redrive_forever(redriver, float(settings.job_redrive_interval_sec)),
                name="job-redrive-sweep",
            )

        # ADR 0037: if `api_keys_file` is configured, load from it
        # and start a reloader task. Otherwise use the string-based
        # keystore parsed above.
        reloader_task: asyncio.Task[None] | None = None
        keystore_reloader: KeystoreReloader | None = None
        if settings.api_keys_file:

            def _apply_keystore(new_keys: dict[str, ApiKeyPrincipal]) -> None:
                # Dict assignment is atomic in CPython — no lock
                # needed. Concurrent lookups either see the old or
                # the new dict, never a half-swapped state.
                app.state.api_keys = new_keys

            keystore_reloader = KeystoreReloader(
                settings.api_keys_file,
                _apply_keystore,
                interval_sec=settings.api_keys_reload_interval_sec,
            )
            initial = await keystore_reloader.initial_load()
            app.state.api_keys = initial
            reloader_task = asyncio.create_task(keystore_reloader.run(), name="keystore-reloader")
        else:
            app.state.api_keys = api_keys

        log.info(
            "api_startup",
            extra={
                "max_concurrent_jobs": max_concurrent,
                "store": type(job_store).__name__,
                "conversation_store": type(conv_store).__name__,
                "learner_profile_enabled": settings.enable_learner_profile,
                "learner_profile_store": type(prof_store).__name__,
                "progress_event_store": type(progress_store).__name__,
                "auth_enabled": settings.enable_api_auth,
                "api_keys_configured": len(app.state.api_keys),
                "keystore_source": ("file" if settings.api_keys_file else "settings"),
                "rate_limit_backend": settings.rate_limit_backend,
                "checkpoint_backend": settings.checkpoint_backend,
                "worker_id": WORKER_ID,
                "metrics_enabled": metrics_enabled(),
                "job_redriver_enabled": settings.enable_job_redriver,
                "job_redriver_periodic": redrive_task is not None,
                "job_redrive_interval_sec": settings.job_redrive_interval_sec,
                "redrive_orphaned": redrive_report.orphaned,
                "redrive_failed": redrive_report.failed,
                "redrive_requeued": redrive_report.requeued,
                "redrive_skipped_live": redrive_report.skipped_live,
                "redrive_scan_capped": redrive_report.scan_capped,
            },
        )
        try:
            yield
        finally:
            # ADR 0037: stop the reloader before the rest of shutdown
            # so it doesn't try to log a swap into a torn-down app.
            if reloader_task is not None:
                reloader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await reloader_task
            # ADR 0040: same teardown discipline for the retention
            # sweep as for the reloader.
            if evict_task is not None:
                evict_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await evict_task
            # ADR 0053: the periodic sweep is cancelled before the jobs
            # below, so it cannot reclaim a job on its way out — the
            # runners are about to mark those `cancelled` themselves,
            # and a sweep racing them would publish a second terminal
            # frame for the same job. (The per-job lease refresh tasks
            # belong to `run_job` and are torn down by the job
            # cancellation below.)
            if redrive_task is not None:
                redrive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await redrive_task
            # Cancel any jobs still running so shutdown is bounded.
            # The runner catches `CancelledError` and marks the job
            # `cancelled` before propagating.
            for task in list(app.state.tasks):
                task.cancel()
            for task in list(app.state.tasks):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            # ADR 0047: the runners above have already drained their
            # own cooperating nodes. Drop whatever is still queued,
            # stop accepting submissions, then join — bounded, because
            # a node that ignores its cancel token must not be able to
            # hold SIGTERM open past the orchestrator's grace period.
            # Without this join the process could not exit cleanly at
            # all: pool threads are non-daemon.
            join_budget = min(float(settings.api_job_drain_timeout_sec), SHUTDOWN_DRAIN_SEC)
            node_executor.shutdown(wait=False, cancel_futures=True)
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(node_executor.shutdown, wait=True),
                    timeout=join_budget,
                )
            except TimeoutError:
                log.warning(
                    "api_node_executor_drain_timeout",
                    extra={
                        "drain_budget_sec": join_budget,
                        "abandoned_node_threads": abandoned_node_count(),
                    },
                )
            # Release the workflow's checkpointer connections via
            # whichever stack the builder attached: the async stack
            # (aiosqlite connection / Postgres pool, ADR 0040) on the
            # production path, the sync ExitStack when a caller
            # injected a sync-mode factory.
            compiled_graphs = [compiled_workflow]
            if compiled_session_workflow is not compiled_workflow:
                compiled_graphs.append(compiled_session_workflow)
            for compiled in compiled_graphs:
                aexit_stack = getattr(compiled, "_checkpointer_aexit_stack", None)
                if aexit_stack is not None:
                    with contextlib.suppress(Exception):
                        await aexit_stack.aclose()
                exit_stack = getattr(compiled, "_checkpointer_exit_stack", None)
                if exit_stack is not None:
                    with contextlib.suppress(Exception):
                        exit_stack.close()
            # Close the Redis connection pool if we own one. The
            # InMemoryJobStore has no `close` method — that's the
            # signal that this is a no-op path.
            close = getattr(job_store, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    await close()
            # ADR 0049: last, so the terminal counters every cancelled
            # job above just recorded make it into the final export.
            # Runs in a thread — the SDK's shutdown blocks on its
            # export thread, and blocking the event loop here would
            # stall uvicorn's own shutdown. Being last also means it is
            # first in line for the orchestrator's SIGKILL if the drains
            # above ran long, which is why its budget is the smallest in
            # the chain (`metrics._SHUTDOWN_BUDGET_MS`) and why losing it
            # costs one export window and nothing else. The guard keeps a
            # metrics-off shutdown from paying for a thread hop to reach
            # a no-op.
            if metrics_enabled():
                await asyncio.to_thread(shutdown_metrics)
            # ADR 0066: the same treatment for spans, which had none.
            # Without this the last `BatchSpanProcessor` window is
            # dropped on every SIGTERM — exactly the window holding the
            # cancellations and drains performed just above, which is
            # what an operator most wants after an unexplained restart.
            # Thread-hopped and flag-guarded for the same reasons as the
            # metrics flush.
            if settings.enable_tracing:
                await asyncio.to_thread(shutdown_tracing)
            log.info(
                "api_shutdown",
                extra={
                    "cancelled_jobs": len(app.state.tasks),
                    "abandoned_node_threads": abandoned_node_count(),
                },
            )

    app = FastAPI(
        title="arxiv-research-agent",
        description=(
            "HTTP surface over the multi-agent research workflow. "
            "See docs/decisions/0025-fastapi-async-job-model.md."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # ADR 0064: four handlers, and between them every exception that can
    # leave a route now produces the same envelope with a code drawn
    # from `ERROR_CODES`. Registered here rather than as decorators
    # because `create_app` is a factory — a decorator would bind to
    # whichever app object happened to be constructed first.
    #
    # Order of registration does not matter (Starlette dispatches on the
    # most specific registered class), but order of *reading* does:
    # `Exception` is the one that had to exist. Everything above it is
    # refinement.
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected)

    # ADR 0033: CORS is opt-in via `settings.api_cors_allow_origins`.
    # Empty (default) => no CORS middleware, so same-origin only.
    origins = [o.strip() for o in settings.api_cors_allow_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "X-API-Key"],
        )
        log.info("api_cors_enabled", extra={"origins": origins})

    # WO-A10. Added last, which makes it the **outermost** user
    # middleware: `add_middleware` inserts at the front of the stack, so
    # the last registration is the first to see a request. That is the
    # position this one needs — a CORS preflight, a 404 for a path no
    # route matched and a 405 from the router are all requests a fleet
    # has to be able to see, and the duration it records is the one the
    # client experienced rather than the one that remained after the
    # layers above had taken their cut.
    app.add_middleware(ObservabilityMiddleware)

    app.include_router(router)
    # WO-W15: the read-only learning-content surface. Its own router and
    # its own module, so the Phase W fleet does not three-way-merge
    # `routes.py` (05-WEDGE-WORK-ORDERS.md §5.4). It holds no lifespan
    # state — the manifests are files in the image — so it needs nothing
    # from the block above, and its routes 404 while
    # `enable_learn_content` is off.
    app.include_router(learn_router)
    app.include_router(session_router)
    return app
