"""FastAPI application factory.

Owns the lifespan: the shared JobStore (in-memory or Redis-backed),
the workflow factory, the concurrency semaphore, and the set of
in-flight tasks so shutdown can cancel them cleanly.

The factory takes injectable overrides for `build_workflow` and
`store` so tests can stub without patching `src.graph.workflow` or
`src.api.redis_store`.

The lifespan also runs the ADR-0038 startup redriver before serving
traffic, so jobs orphaned by the previous generation of workers are
reconciled (and their SSE clients unhung) rather than left claiming
`running` forever.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from src.api.redriver import (
    REDRIVE_LOCK_TTL_SEC,
    WORKER_ID,
    JobRedriver,
    RedriveReport,
)
from src.api.routes import router
from src.api.runner import run_job
from src.config import settings
from src.graph.workflow import build_workflow as default_build_workflow
from src.observability import get_logger

log = get_logger(__name__)

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
            evicted = await store.evict_older_than(
                settings.api_job_retention_sec
            )
            if evicted:
                log.info("api_jobs_evicted", extra={"count": evicted})
        except Exception:
            log.warning("api_job_evict_sweep_failed", exc_info=True)


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
    store: JobStore | None = None,
    conversation_store: ConversationStore | None = None,
    max_concurrent_jobs: int | None = None,
) -> FastAPI:
    """Build a FastAPI app instance.

    Args:
        build_workflow: Zero-arg factory that returns a compiled
            LangGraph app. Defaults to the production workflow. Tests
            inject a stub that yields fake state updates.
        store: Persistence layer. Defaults to whichever `JobStore`
            `settings.job_store` selects (`memory` / `redis`).
        conversation_store: Conversation persistence (ADR 0032).
            Defaults to whichever `ConversationStore`
            `settings.conversation_store` selects
            (`memory` / `postgres`).
        max_concurrent_jobs: Semaphore ceiling. Defaults to
            `settings.api_max_concurrent_jobs`.
    """
    # ADR 0040: the API runner drives the graph through its async
    # surface, so the production factory compiles with the ASYNC
    # savers. The sync default (CLI / eval runner) would kill every
    # job with `NotImplementedError` before its first node.
    factory = build_workflow or (
        lambda: default_build_workflow(async_checkpointer=True)
    )
    job_store: JobStore = store if store is not None else _default_store()
    conv_store: ConversationStore = (
        conversation_store
        if conversation_store is not None
        else build_conversation_store()
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
        # ADR 0040: the async-checkpointer factory returns an
        # awaitable (opening AsyncSqliteSaver / the Postgres pool
        # needs a running loop, which this lifespan is). Test-injected
        # stub factories stay plain callables, hence the check.
        compiled_workflow = factory()
        if inspect.isawaitable(compiled_workflow):
            compiled_workflow = await compiled_workflow
        app.state.workflow = compiled_workflow
        app.state.store = job_store
        app.state.conversation_store = conv_store
        app.state.semaphore = asyncio.Semaphore(max_concurrent)
        app.state.max_concurrent_jobs = max_concurrent
        app.state.tasks = set()
        app.state.rate_limiter = rate_limiter
        # ADR 0038: one id per process, stamped on job leases and the
        # redrive lock so every reclaim is attributable to a worker.
        app.state.worker_id = WORKER_ID

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
                    workflow=compiled_workflow,
                    store=job_store,
                    semaphore=app.state.semaphore,
                    conversation_store=conv_store,
                ),
                name=f"job-{job.job_id}",
            )
            app.state.tasks.add(task)
            task.add_done_callback(app.state.tasks.discard)

        redrive_report = RedriveReport()
        if settings.enable_job_redriver:
            try:
                # Bounded by the redrive lock's own TTL. Past that the
                # sweep no longer holds the lock, so continuing would
                # only race whoever took it next — and `build_redis_client`
                # sets no socket timeout, so an unreachable Redis would
                # otherwise hold the process in "starting" indefinitely.
                redrive_report = await asyncio.wait_for(
                    JobRedriver(
                        job_store, resubmit=_resubmit_orphaned
                    ).sweep(),
                    timeout=REDRIVE_LOCK_TTL_SEC,
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
            reloader_task = asyncio.create_task(
                keystore_reloader.run(), name="keystore-reloader"
            )
        else:
            app.state.api_keys = api_keys

        log.info(
            "api_startup",
            extra={
                "max_concurrent_jobs": max_concurrent,
                "store": type(job_store).__name__,
                "conversation_store": type(conv_store).__name__,
                "auth_enabled": settings.enable_api_auth,
                "api_keys_configured": len(app.state.api_keys),
                "keystore_source": (
                    "file" if settings.api_keys_file else "settings"
                ),
                "rate_limit_backend": settings.rate_limit_backend,
                "checkpoint_backend": settings.checkpoint_backend,
                "worker_id": WORKER_ID,
                "job_redriver_enabled": settings.enable_job_redriver,
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
            # ADR 0038: the redrive sweep is awaited during startup and
            # owns no long-lived task, so there is nothing to cancel
            # here. The per-job lease refresh tasks belong to `run_job`
            # and are torn down by the job cancellation below.
            # Cancel any jobs still running so shutdown is bounded.
            # The runner catches `CancelledError` and marks the job
            # `cancelled` before propagating.
            for task in list(app.state.tasks):
                task.cancel()
            for task in list(app.state.tasks):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            # Release the workflow's checkpointer connections via
            # whichever stack the builder attached: the async stack
            # (aiosqlite connection / Postgres pool, ADR 0040) on the
            # production path, the sync ExitStack when a caller
            # injected a sync-mode factory.
            aexit_stack = getattr(
                compiled_workflow, "_checkpointer_aexit_stack", None
            )
            if aexit_stack is not None:
                with contextlib.suppress(Exception):
                    await aexit_stack.aclose()
            exit_stack = getattr(compiled_workflow, "_checkpointer_exit_stack", None)
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
            log.info("api_shutdown", extra={"cancelled_jobs": len(app.state.tasks)})

    app = FastAPI(
        title="arxiv-research-agent",
        description=(
            "HTTP surface over the multi-agent research workflow. "
            "See docs/decisions/0025-fastapi-async-job-model.md."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # ADR 0033: CORS is opt-in via `settings.api_cors_allow_origins`.
    # Empty (default) => no CORS middleware, so same-origin only.
    origins = [
        o.strip()
        for o in settings.api_cors_allow_origins.split(",")
        if o.strip()
    ]
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
    return app
