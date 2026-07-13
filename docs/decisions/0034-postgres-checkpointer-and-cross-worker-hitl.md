# 0034. Postgres checkpointer + cross-worker HITL resume

- **Status**: accepted
- **Date**: 2026-07-13
- **Deciders**: kudratsingh
- **Revisits**: [ADR 0013](0013-sprint-1-finish-retry-checkpoint-tracing-recall.md) (SqliteSaver), [ADR 0027](0027-docker-compose-redis-job-store.md) (cross-worker signaling)

## Context

Two related audit crits blocked the deploy story:

**Crit 1 — SqliteSaver leak.** `build_workflow()` was called from
`src/api/runner.py` inside `run_job` for every submitted job. Each
call opened a fresh `SqliteSaver` inside an `ExitStack` that never
closed until interpreter shutdown, so:

- File descriptors leaked at 1-per-job. Under sustained load this
  eventually exhausted the process FD cap.
- The shared `.cache/checkpoints.sqlite` file saw concurrent writers
  from multiple runners. SQLite is single-writer; concurrent writes
  block or corrupt.
- Under multi-worker uvicorn the situation was worse: every worker
  wrote to the same file simultaneously.

**Crit 2 — Cross-worker HITL resume dead-ended.** ADR 0025's
`RedisJobStore` correctly excludes `event_queue` and `resume_event`
from the JSON-serialized shape — `asyncio.Queue` and `asyncio.Event`
are per-worker asyncio primitives, not portable state. But the
review endpoint's implementation depended on those primitives to
wake the runner:

1. `POST /research/{id}/review` lands on worker B.
2. B fetches the Job from Redis → reconstructed dataclass with a
   fresh, unset `asyncio.Event`.
3. B sets `resume_event` on its local copy.
4. Worker A (the runner) is `await`-ing its OWN `resume_event`.
5. A never wakes; job sits in `pending_review` until
   `api_hitl_timeout_sec` (default 1800s) — silent, mysterious.

The `RedisJobStore` docstring even flagged this as future work.
Meanwhile HITL ships default-on, so this is the default failure
mode on any real multi-worker deployment.

Both crits share a root cause: the runner assumes single-worker.
Fixing the checkpointer without fixing HITL delivers half a
deploy story. Fixing HITL without a shared checkpointer doesn't
work either — LangGraph can only resume a thread on the same
checkpointer instance. Bundling them keeps the "multi-worker
uvicorn now actually works" story in one PR.

## Decision

Ship four changes as one bundle.

1. **Pluggable checkpointer backend.**
   `settings.checkpoint_backend: Literal["sqlite", "postgres"]`
   defaults to `sqlite` for backward compatibility. Compose sets
   `postgres`. `src/graph/workflow.py::_open_checkpointer`
   dispatches on the setting:
   - `sqlite` → `SqliteSaver.from_conn_string(checkpoint_db_path)`.
   - `postgres` → `PostgresSaver.from_conn_string(postgres_url)`
     followed by `.setup()` (idempotent DDL). Reuses the same
     Postgres instance the ADR-0028 caches use.
   - Unknown → `ValueError` at startup, not at request time.

2. **Compile once at startup.** The FastAPI lifespan in
   `src/api/app.py::create_app` now calls `build_workflow()`
   exactly once and stores the compiled instance on
   `app.state.workflow`. The runner (`run_job`, `_invoke_streaming`)
   takes a pre-compiled `workflow` argument; the review endpoint
   reads it via `state["workflow"]`. Shutdown closes the
   checkpointer's `ExitStack` explicitly — the leak is gone.

3. **Redis pub/sub for cross-worker HITL resume.**
   `RedisJobStore` gains two methods:
   - `publish_remote_resume(job_id, action, plan)` — publishes
     `{action, plan}` JSON to `hitl:resume:{job_id}` on Redis
     pub/sub. Called from the review endpoint after persisting the
     decision.
   - `watch_for_remote_resume(job)` — subscribes, awaits the first
     message, hydrates `job.resume_action` + `job.resume_plan`,
     sets `job.resume_event`, returns.

   `_handle_hitl_pause` in the runner spawns
   `watch_for_remote_resume` as a background task alongside the
   local `await resume_event.wait()`. Whichever fires first wakes
   the runner. The subscription task is cancelled in `finally` so
   the same-worker fast path doesn't leak a pubsub connection.

4. **Compose defaults flipped.** `CHECKPOINT_BACKEND=postgres`
   is set in `docker-compose.yml` so the multi-service stack
   works correctly out of the box. Local `python -m src.api.serve`
   still defaults to SQLite — no infra required for dev.

The runner's discovery of the pub/sub subscriber is duck-typed
(`getattr(store, "watch_for_remote_resume", None)`). `InMemoryJobStore`
doesn't implement it — same-worker `resume_event` handles that
case natively, so the check reads as "no cross-worker signal
needed" without a hierarchical Store interface change.

## Alternatives considered

- **Sqlite in WAL mode**, hoping multi-writer semantics improve.
  Rejected: WAL still serializes writers; the FD leak per job
  isn't addressed; and the horizontal-scaling story needs a real
  shared checkpointer anyway. WAL is a bandaid that would still
  fail under real load.

- **Per-worker `SqliteSaver` with worker-partitioned thread IDs.**
  Rejected: solves the "single writer" problem but requires
  sticky routing on the load balancer for HITL to work, breaks
  the RedisJobStore's "any worker can serve any job" property,
  and inherits the FD leak.

- **`AsyncPostgresSaver` (async LangGraph checkpointer)** instead
  of the sync `PostgresSaver` running under `asyncio.to_thread`.
  Rejected for this PR: the runner already calls `app.get_state`
  and `app.invoke` via `asyncio.to_thread` (the workflow is sync
  end-to-end). Introducing async at the checkpointer alone
  would create a mixed-mode surface without meaningful throughput
  gains. Follow-up if profiling shows the checkpointer as the
  bottleneck.

- **Redis Streams instead of pub/sub for HITL resume.** Streams
  give at-least-once delivery + consumer groups. Rejected:
  overkill for a one-shot resume signal. If the runner's
  worker crashes between the review and the `resume_event.set()`,
  the job is already durably in `pending_review` in Redis, and a
  redriver can restart it — but that's a separate feature (job
  redrivers on restart) not gated by this ADR. Pub/sub is fine
  for the "wake a running task" primitive.

- **Send the resume decision via the existing `event_queue`
  Redis-backed** (also pub/sub-ify events). Rejected for this PR:
  events flow one-way (runner → SSE); HITL flows the other way
  (review → runner). Sharing infrastructure would couple two
  independent concerns. SSE cross-worker is a real follow-up
  bug flagged in ADR 0027; separate PR because it doesn't ship
  default-on the way HITL does.

- **Rebuild the workflow lazily on first request** (still-once,
  just not at startup). Rejected: hides the checkpointer boot
  behind an unpredictable first-request latency, and any
  build-time failure lands on a user-facing 500 instead of a
  clear startup error the operator sees before traffic starts.

## Consequences

**Positive**

- Multi-worker uvicorn actually works: HITL wakes across workers,
  and the checkpointer no longer corrupts under concurrent writes.
- Checkpointer connections live for the process lifetime, not per
  request. FD leak closed; the `_checkpointer_exit_stack` is
  released on shutdown.
- Postgres is now the "batteries included" backend in compose,
  matching the paper-cache / embedding-cache / conversation-store
  choices the earlier ADRs already made.
- ADR 0030 (HITL) is now actually production-safe as documented.

**Negative**

- The Postgres checkpointer runs `.setup()` at startup, adding
  ~200ms cold-start latency the first time a fresh Postgres is
  seen. Subsequent starts see `CREATE TABLE IF NOT EXISTS`
  no-op — negligible.
- `langgraph-checkpoint-postgres` adds one dependency (transitive
  psycopg is already present via the ADR-0028 pool).
- The `hitl:resume:{job_id}` pub/sub channel adds one Redis
  subscription per HITL-waiting job on the runner's worker. Fine
  at demo scale; at 10k concurrent HITL pauses per worker we'd
  want to consolidate onto a single subscriber with pattern
  matching. Documented; not blocking.

**Follow-ups**

- SSE cross-worker via Redis pub/sub (ADR 0027 revisit). Same
  pattern as HITL — publish node events on `events:{job_id}`,
  subscribe from the streaming endpoint. Independent PR.
- Job redriver on restart: if a worker crashes mid-run, its Redis
  job entry is stuck in `running`; a startup sweep could reset
  those to `failed` with `error_type=worker_restart`.
- Share the ADR-0028 psycopg pool with `PostgresSaver` instead of
  the checkpointer opening its own connections. Straightforward
  once we confirm the LangGraph API surface for injecting a
  connection.
- Async checkpointer (`AsyncPostgresSaver`) once profiling
  justifies the async-mode surface.
