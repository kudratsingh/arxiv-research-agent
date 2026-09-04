"""FastAPI application factory.

Owns the lifespan: the shared JobStore (in-memory or Redis-backed),
the workflow factory, the concurrency semaphore, the thread pool the
graph's synchronous nodes run on (ADR 0047), and the set of in-flight
tasks so shutdown can cancel them cleanly.

The factory takes injectable overrides for `build_workflow` and
`store` so tests can stub without patching `src.graph.workflow` or
`src.api.redis_store`.

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
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.auth import (
    ApiKeyPrincipal,
    KeystoreReloader,
    build_rate_limiter,
    parse_api_keys,
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
from src.observability.metrics import (
    configure_metrics,
    metrics_enabled,
    register_runtime_gauges,
    shutdown_metrics,
)
from src.observability.tracing import shutdown_tracing

log = get_logger(__name__)


def _request_id(request: Request) -> str:
    """The correlation id for one failed request.

    There is no request-id infrastructure in this process yet — WO-A10
    adds the middleware that mints one per request and puts it in the
    observability context. Until then the id is generated *here*, at the
    moment of failure, which is enough to tie a client's error body to
    the ERROR log line beside it and is the whole reason the field
    exists in the envelope.

    It reads `request.state.request_id` first so that when the
    middleware lands this function needs no edit: the same id will then
    already be on the request and every log record for it, and the
    locally-minted fallback becomes dead code rather than a competing
    second identity. See ADR 0064 "Seams".
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
