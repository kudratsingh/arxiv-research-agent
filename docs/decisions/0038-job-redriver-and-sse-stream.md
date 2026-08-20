# 0038. Job redriver and SSE stream rewrite

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: kudratsingh
- **Follows**: [ADR 0027](0027-docker-compose-redis-job-store.md) (Redis job store),
  [ADR 0035](0035-cross-worker-sse-pubsub.md) (cross-worker SSE)

## Context

Two follow-ups left open by the ADR 0033–0037 hardening chain. They
are paired because they are the same failure, seen from the two ends
of one connection: a worker dies and its job is stranded `running`
forever, and the stream that was watching that job hangs waiting for
a terminal frame. Fixing either alone leaves the user's experience
broken. Neither is visible in a single-process happy path, which is
why both were deferred and why both need closing before the service
takes real traffic.

(The third follow-up from that chain, the operator cleanup tool for
legacy `NULL`-owner rows, is [ADR 0039](0039-admin-null-owner-migration.md).)

### 1. Orphaned jobs survive forever

`RedisJobStore.update()` applies a TTL only when `job.is_terminal()`.
A non-terminal row therefore has no expiry. When the worker running a
job dies — deploy, crash, OOM, scale-in — the row stays `running`
permanently: `GET /research/{id}` keeps answering `running`, and
`GET /research/{id}/stream` subscribes to `events:{job_id}` and waits
for a terminal frame that nobody will ever publish. Nothing in the
system reconciles it.

The naive fix — "fail every non-terminal job at startup" — is worse
than the bug. With N workers, worker 3 restarting would reap the jobs
running healthily on workers 1 and 2. Every rolling deploy would
destroy in-flight work. The hard requirement is not reconciliation; it
is **distinguishing orphaned from alive**.

### 2. The SSE stream dies after the first idle heartbeat

`stream_research` raced the event read against the heartbeat:

```python
get_task = asyncio.create_task(_next_event())          # fresh every iteration
heartbeat_task = asyncio.create_task(asyncio.sleep(HEARTBEAT_INTERVAL_SEC))
done, pending = await asyncio.wait({get_task, heartbeat_task}, return_when=FIRST_COMPLETED)
for p in pending:
    p.cancel()
```

When the heartbeat won — i.e. whenever a workflow node took longer than
15 seconds, which is most of them — `get_task` was cancelled *while
suspended inside the async generator*. That throws `CancelledError` into
the generator at its suspension point, which runs its `finally`: for
`RedisJobStore.subscribe_events` that is `unsubscribe` +
`pubsub.aclose()`. The drainer was then permanently closed, the next
`__anext__` raised immediately, and the stream ended — silently, with no
terminal frame. Reproduced against the pre-change implementation: the
scenario "quiet for longer than the heartbeat, then an event, then a
terminal frame" produced exactly `[b': heartbeat\n\n']` and nothing
else.

There was a second, narrower loss window: a frame already pulled off
the queue by a cancelled `get_task` was dropped.

## Decision

### 1. Worker leases + a startup redriver

**Leases.** A worker holds `joblease:{job_id}` for as long as it owns a
job, refreshed every `job_lease_refresh_sec` (30s) against a
`job_lease_ttl_sec` (90s) TTL. Lease expiry *is* the orphan signal, and
`job_lease_ttl_sec` is therefore also the worst-case delay before a
crashed worker's jobs become reclaimable.

The lease is taken **before** the concurrency semaphore, not inside it.
`JobStatus.pending` is documented as "queued behind the semaphore", so a
job waiting for a slot is non-terminal and alive; acquiring the lease
inside the semaphore would leave every queued job leaseless and a peer
worker's sweep would reap it. This is the single subtlest ordering
constraint in the design.

Refresh and release are owner-checked compare-and-set: a worker that has
already lost its lease must not extend, or delete, its successor's
claim.

**Redriver.** `JobRedriver.sweep()` runs once in the FastAPI lifespan
before `yield`. It:

1. No-ops unless the store exposes `scan_jobs` — nothing survives an
   `InMemoryJobStore` restart, so there is nothing to reconcile.
2. Takes a cluster-wide `redrive:lock` (`SET NX EX`). All workers boot
   at once; without it they would race to reclaim the same rows.
3. Scans up to `job_redrive_max_scan` (10 000) job keys with cursor-based
   `SCAN`, never `KEYS`. Undeserializable rows are logged and skipped
   rather than aborting the sweep.
4. Skips terminal jobs and jobs whose lease is still held.
5. Reclaims the rest by **atomically claiming the lease first**, so the
   rightful owner cannot flip the row to `running` between the liveness
   check and the write.
6. Publishes a terminal `job_failed` frame on `events:{job_id}` for every
   reclaimed job. This is the half that actually unhangs the SSE clients
   that motivated the work — reconciling the row alone would leave them
   waiting.

**Reclaim policy.** `running` and `pending_review` are always failed with
`error_type="orphaned"`: resuming them would double-charge for LLM calls
already made. `pending` jobs never started, so they carry no partial work
and no spend, and are resubmitted when `job_redrive_requeue_pending` is
set. `create_app` supplies the resubmit callback, spawning `run_job`
against the same workflow, semaphore and task set as `submit_research`.

The sweep is bounded by `asyncio.wait_for(..., REDRIVE_LOCK_TTL_SEC)` —
`build_redis_client` sets no socket timeout, so an unreachable Redis
would otherwise hold the process in "starting" indefinitely — and every
failure path is logged and swallowed. A redriver bug must never stop the
app from booting.

### 2. SSE stream rewrite

The loop moves out of a closure nested inside the route handler and into
`sse_event_stream()` in `src/api/streaming.py`, taking its drainer,
disconnect check and clock as parameters so it is testable without
FastAPI, Redis, or real sleeping.

- **One long-lived read task** across iterations, awaited with
  `asyncio.wait({get_task}, timeout=...)` so a timeout leaves it running
  instead of cancelling it. It is cancelled exactly once, in the
  `finally`. This is the fix for the bug above.
- **An immediate keepalive on open**, so time-to-first-byte does not
  depend on how long the first node takes.
- **A stream deadline** (`api_sse_max_duration_sec`, 1h) emitting a
  `stream_timeout` event. A stream on a wedged job must not pin a worker
  connection forever.
- `stream_timeout` is deliberately **not** in `TERMINAL_EVENT_NAMES`.
  The two sets answer different questions — "did the job end?" versus
  "should the server stop streaming?" — and are named accordingly
  (`STREAM_CLOSING_EVENT_NAMES` is the wider one). A subscriber that
  conflated them would report a healthy job as finished.
- The route wraps the delegate in `contextlib.aclosing`. Starlette's
  `StreamingResponse` never calls `aclose()` on its body iterator, so a
  bare `async for` would abandon the generator unclosed and defer its
  `finally` to the async-generator finalizer — one leaked pubsub
  connection per disconnected client, which is precisely the leak ADR
  0035 closed.

## Alternatives considered

- **Fail all non-terminal jobs at startup, no leases.** Simple and
  wrong: every rolling deploy would destroy the work in flight on every
  other worker. Rejected outright — the lease is the point.

- **Lua `EVAL` for the owner-checked lease CAS** (the original plan).
  `fakeredis` implements `EVAL` only with the optional native `lupa`
  extension, which is not in the test matrix, so a Lua path would be
  untestable. Shipped WATCH/MULTI/EXEC optimistic locking instead:
  identical guarantee (Redis aborts the `EXEC` if the key moved after
  the `WATCH`), one extra round trip per refresh — every 30s per running
  job, so negligible. Revisit if `lupa` is ever added.

- **Requeue `running` jobs from their LangGraph checkpoint.** Tempting,
  since ADR 0034 already persists checkpoints. Rejected for now:
  resuming mid-graph needs thread-id reconciliation and a story for
  partially-recorded costs. Failing with a distinct `orphaned` error type
  is honest and cheap; resurrection can be a later ADR.

- **A background sweeper on an interval instead of at startup.** A
  periodic sweep would catch a worker that dies while its peers stay up,
  which the startup sweep misses until the next boot. Deferred rather
  than rejected — it is the natural next iteration, but startup is where
  the orphan population is concentrated (a deploy restarts everything)
  and a periodic sweep multiplies the lock-contention surface.

- **A `sse-starlette` dependency** for the streaming loop. Still not
  worth it — the cancellation bug was ours, not the wire protocol's, and
  the rewritten loop is ~80 lines with tests we control.

## Consequences

**Positive**

- A worker can die without stranding its jobs. `GET /research/{id}`
  eventually tells the truth, and the SSE clients waiting on those jobs
  get a terminal frame instead of hanging.
- A rolling restart no longer reaps healthy work — leases make the
  distinction, and the queued-behind-the-semaphore case is covered.
- SSE streams survive quiet periods. Any workflow with a node slower
  than the heartbeat interval previously lost its stream; that is most
  real queries.
- One leaked Redis pubsub connection per disconnected client is closed.
- The streaming loop is unit-testable in isolation for the first time.

**Negative**

- Two new Redis keyspaces (`joblease:{job_id}`, `redrive:lock`) and one
  write per job every 30s. Trivial next to job rows, but it is new
  traffic against the same instance.
- Boot is slower by one sweep, bounded at `REDRIVE_LOCK_TTL_SEC`.
- `_reconcile` issues up to three sequential round trips per reclaimed
  job. At `job_redrive_max_scan=10000` that is a lot of sequential I/O;
  the `wait_for` bound stops it wedging a boot, but a pipelined batch
  claim is the right shape if the cap is ever raised.
- The `WatchError` abort branch of the lease CAS has no coverage —
  `fakeredis` resolves without true concurrency. The guarantee is sound;
  only that path is unproven on the current matrix.

**Follow-ups**

Findings from the post-merge audit that are *not* closed here, and
belong to the code this ADR touches:

- A worker killed mid-sweep holds `redrive:lock` for its full 120s
  TTL, so its own restart skips reconciliation entirely.
- A `pending` row is briefly visible to a peer sweep between
  `store.create` and the runner's first `acquire_lease`. Bounded by
  the re-read added after the audit, but not eliminated.
- `scan_jobs` hydrates full result bodies for terminal rows the sweep
  discards immediately; a projection would avoid the transfer.

Closed after the audit rather than at first write: the reclaim now
re-reads the row under its claim instead of trusting the scan
snapshot (a job that finished in between had its `result` destroyed),
and a transient Redis error at acquire no longer leaves a job
leaseless — and therefore reapable — for its entire run.

- Periodic redrive sweep, not just at startup, for workers that die
  while their peers stay up.
- Pipelined batch claim in `_reconcile` before raising
  `job_redrive_max_scan`.
- Real-Redis integration marker (or `lupa`) to cover the CAS abort path.
- Close the pre-existing ADR 0035 subscribe TOCTOU: a job can reach a
  terminal state between `store.get()` and the lazy pubsub subscribe, so
  the terminal frame is published with no subscriber. Previously this
  hung forever; it now idles to `api_sse_max_duration_sec` and emits
  `stream_timeout`. Bounded, not closed.
- The web UI's `EventSource` consumer should treat `stream_timeout` as a
  reconnect signal rather than a job outcome; today an unknown event name
  is ignored and the UI sits on a closed stream.
- `scan_jobs` materializes up to `max_scan` deserialized jobs at once; a
  streaming iterator is the right shape for a much larger cap.
