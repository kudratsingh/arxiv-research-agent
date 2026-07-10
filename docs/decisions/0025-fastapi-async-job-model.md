# 0025. FastAPI + async job model over the sync workflow

- **Status**: accepted
- **Date**: 2026-07-10
- **Depends on**: ADR
  [0014](0014-supervisor-loop-behind-flag.md) (workflow shape),
  [0024](0024-pr-ci-lint-mypy-tests.md) (CI gate)
- **Related**: ADR
  [0026](0026-sse-streaming-endpoint.md) (streaming surface)

## Context

Sprint 4 needs an HTTP surface so the workflow is reachable from
anything other than a shell — a web UI (Sprint 5), a batch harness,
a Slack bot, or a research automation. Sprint 1–3 shipped only the
CLI entry point (`python -m src.main "<query>"`), which is fine for
eval and iteration but useless as a product surface.

Constraints:

- **Sync workflow, async caller.** LangGraph's compiled app is
  callable synchronously (`app.invoke`) and also exposes async
  variants (`app.ainvoke`, `app.astream`). Under the hood the reader
  uses a `ThreadPoolExecutor` for parallel paper analysis; a client
  request that blocks the FastAPI event loop for 30–60 seconds
  serializes every other request. Runs must not block the loop.
- **Long-running.** A typical query is 30–90 seconds, well beyond a
  reasonable client HTTP read timeout. Synchronous response-on-invoke
  is not viable; we need a job model where clients get a `job_id`
  immediately and poll (or stream, ADR 0026) for progress.
- **Production-scale mandate.** The design must not preclude
  horizontal scaling to thousands of concurrent users. That doesn't
  mean shipping the horizontally-scaled version here, but the API
  surface must be stable when we swap the in-memory job store for a
  Redis-backed one in Sprint 4 PR 3+.
- **No new external services in this PR.** Sprint 4 PR 3 adds Redis
  + Postgres via Docker compose. This PR is API-surface-only so it
  can be exercised and reviewed independently.

## Decision

New `src/api/` package with:

- **`create_app()`** — FastAPI application factory. Accepts an
  injectable `build_workflow` callable and an injectable `JobStore`
  so tests hand in stubs without patching module globals. Owns the
  lifespan: `JobStore`, `asyncio.Semaphore`, and the set of
  in-flight background tasks.
- **`Job` + `JobStatus`** — dataclass capturing the request, the
  terminal state, timing, cost, and error. Status enum:
  `pending` / `running` / `succeeded` / `failed` / `cancelled`. Each
  `Job` owns an `asyncio.Queue` for streamed workflow events (see
  ADR 0026); the queue is bounded (1024) so a slow SSE consumer
  applies backpressure to the runner instead of unbounded memory
  growth.
- **`JobStore` Protocol + `InMemoryJobStore`** — one method surface
  (`create` / `get` / `update` / `evict_older_than`) so Sprint 4 PR
  3+ can swap in a Redis-backed store without touching the routes.
  `InMemoryJobStore` is a `dict` guarded by `asyncio.Lock`; jobs die
  with the process, which is fine at this stage because a real run
  is short-lived and the Redis migration is the next PR.
- **`asyncio.Semaphore(max_concurrent_jobs)`** — hard ceiling on
  concurrent workflow invocations per process. Default 10, config-
  tunable via `settings.api_max_concurrent_jobs`. Under a real job
  queue (a follow-up PR) this becomes a per-worker cap; today it
  caps the whole single-process app.
- **`asyncio.wait_for(..., timeout=api_job_timeout_sec)`** — hard
  per-job timeout, default 600 s. Jobs exceeding this are marked
  `failed` with `error_type = "timeout"`. Independent of the
  client's HTTP read timeout on the streaming endpoint.
- **Routes**:
  - `POST /research` — accepts `{query}`, creates a `Job`, kicks off
    `run_job(...)` as an `asyncio.create_task`, returns 202 with
    `{job_id, status_url, stream_url}`. Never blocks on workflow
    completion.
  - `GET /research/{job_id}` — full lifecycle snapshot including
    result, error, cost, and metrics.
  - `GET /research/{job_id}/stream` — SSE stream, ADR 0026.
  - `GET /healthz` — liveness + concurrency headroom.
- **`run_job(...)`** — the runner. Enforces the semaphore + timeout,
  binds a `run_id` ContextVar (so per-run logs and cost tracking
  work exactly like they do in the CLI + eval paths), streams
  intermediate events via `app.astream`, and captures all failure
  modes onto the `Job` record so the function itself never raises
  into the calling task.

## Alternatives considered

- **Sync workflow directly under FastAPI (`app.invoke` in a route
  handler).** Blocks the event loop for the workflow's duration;
  serializes every other request. Only viable with a large uvicorn
  worker pool per user, which trades good async ergonomics for pod
  count. Rejected.
- **`fastapi.BackgroundTasks`.** Simpler than an explicit task set,
  but its tasks run *after* the response is sent and cannot be
  streamed — the SSE endpoint requires an ongoing task the streamer
  can attach to. Also no cancellation surface. Rejected on both
  counts.
- **Celery / RQ / Dramatiq worker + queue.** Right shape for
  horizontal scaling, but every one of them needs Redis (which
  arrives in Sprint 4 PR 3) plus a separate worker process. Doing
  this in the same PR triples the review surface and blocks a
  reviewable API-surface milestone on infra we haven't stood up
  yet. The `JobStore` Protocol keeps the door open — Sprint 5's
  scaling PR swaps the runner for a real worker without touching
  the routes.
- **arq (asyncio-native queue).** Same shape trade-off as Celery
  but async-friendly. Same rejection: Redis dep first.
- **`asyncio.to_thread(app.invoke)` only, no streaming.** Simpler
  and works for the polling path, but forfeits SSE, which is the
  UX story for a long-running workflow. Adopting `app.astream`
  costs nothing at this scale (the workflow itself is sync-threaded
  under the hood, but LangGraph exposes an async streaming API).
  Rejected — the streaming path is the interesting one.
- **In-memory `list` for events instead of `asyncio.Queue`.** Works
  for polling but not streaming: a real streamer needs a way to
  await the next event without spin-polling. Rejected.

## Consequences

- **Positive.** The API surface exists, is exercisable from any
  HTTP client, and doesn't spend Anthropic credits on PR CI (the
  stub-workflow test harness in `tests/test_api_routes.py` mocks
  the workflow). ADR 0024's CI gates protect the routes; ADR 0026's
  SSE endpoint gives clients real-time progress. The
  `JobStore` Protocol keeps the Redis migration a two-file change.
- **Negative.** In-memory storage means a process restart drops
  in-flight jobs. That's acceptable at this stage — the workflow is
  idempotent and the client can resubmit — but not acceptable for
  the eventual production deployment; Sprint 4 PR 4 fixes it. The
  semaphore-per-process concurrency cap means we can't horizontally
  scale until the real queue lands; a burst of traffic backs up in
  `pending` state until slots free, which is the correct behavior
  but not the horizontally-scaled behavior.
- **Follow-ups.**
  - **Sprint 4 PR 3**: Docker + docker-compose adds Redis + Postgres.
  - **Sprint 4 PR 4**: `RedisJobStore` implementation swaps in
    behind the `JobStore` Protocol; job records survive restarts.
  - **Follow-up**: proper async job queue (arq) once Redis is
    stable, replacing the in-process `asyncio.create_task` runner.
  - **Follow-up**: OpenAPI operation IDs + JSON-schema publication
    so client SDKs can be generated.
