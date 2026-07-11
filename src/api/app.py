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
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.jobs import InMemoryJobStore, JobStore
from src.api.routes import router
from src.config import settings
from src.graph.workflow import build_workflow as default_build_workflow
from src.observability import get_logger

log = get_logger(__name__)

UI_DIR = Path(__file__).parent / "ui"


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
    max_concurrent_jobs: int | None = None,
) -> FastAPI:
    """Build a FastAPI app instance.

    Args:
        build_workflow: Zero-arg factory that returns a compiled
            LangGraph app. Defaults to the production workflow. Tests
            inject a stub that yields fake state updates.
        store: Persistence layer. Defaults to whichever `JobStore`
            `settings.job_store` selects (`memory` / `redis`).
        max_concurrent_jobs: Semaphore ceiling. Defaults to
            `settings.api_max_concurrent_jobs`.
    """
    factory = build_workflow or default_build_workflow
    job_store: JobStore = store if store is not None else _default_store()
    max_concurrent = max_concurrent_jobs or settings.api_max_concurrent_jobs

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.store = job_store
        app.state.build_workflow = factory
        app.state.semaphore = asyncio.Semaphore(max_concurrent)
        app.state.max_concurrent_jobs = max_concurrent
        app.state.tasks = set()
        log.info(
            "api_startup",
            extra={
                "max_concurrent_jobs": max_concurrent,
                "store": type(job_store).__name__,
            },
        )
        try:
            yield
        finally:
            # Cancel any jobs still running so shutdown is bounded.
            # The runner catches `CancelledError` and marks the job
            # `cancelled` before propagating.
            for task in list(app.state.tasks):
                task.cancel()
            for task in list(app.state.tasks):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
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
    app.include_router(router)

    # Demo UI (ADR 0029). Vanilla HTML/JS/CSS mounted as StaticFiles;
    # served from the same FastAPI process as the API. Include order
    # matters — routes register first so `/research`, `/healthz`, etc
    # take precedence over the static catchall.
    if UI_DIR.exists():
        app.mount(
            "/static",
            StaticFiles(directory=UI_DIR),
            name="static",
        )

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            # Explicit `/` handler (rather than `StaticFiles(html=True)`
            # at the root) so the OpenAPI schema at `/openapi.json`
            # stays reachable and `/docs` isn't shadowed by a catchall.
            return FileResponse(UI_DIR / "index.html")

    return app
