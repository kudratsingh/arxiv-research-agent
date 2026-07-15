"""FastAPI application factory.

Owns the lifespan: the shared JobStore (in-memory or Redis-backed),
the workflow factory, the concurrency semaphore, and the set of
in-flight tasks so shutdown can cancel them cleanly.

The factory takes injectable overrides for `build_workflow` and
`store` so tests can stub without patching `src.graph.workflow` or
`src.api.redis_store`.
"""

from __future__ import annotations

import asyncio
import contextlib
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
from src.api.jobs import InMemoryJobStore, JobStore
from src.api.routes import router
from src.config import settings
from src.graph.workflow import build_workflow as default_build_workflow
from src.observability import get_logger

log = get_logger(__name__)


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
        log.info(
            "api_store_selected",
            extra={"store": "redis", "redis_url": settings.redis_url},
        )
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
    factory = build_workflow or default_build_workflow
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
        compiled_workflow = factory()
        app.state.workflow = compiled_workflow
        app.state.store = job_store
        app.state.conversation_store = conv_store
        app.state.semaphore = asyncio.Semaphore(max_concurrent)
        app.state.max_concurrent_jobs = max_concurrent
        app.state.tasks = set()
        app.state.rate_limiter = rate_limiter

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
            # Cancel any jobs still running so shutdown is bounded.
            # The runner catches `CancelledError` and marks the job
            # `cancelled` before propagating.
            for task in list(app.state.tasks):
                task.cancel()
            for task in list(app.state.tasks):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            # Release the workflow's checkpointer connections (SQLite
            # or Postgres) via the ExitStack the compiler attached.
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
