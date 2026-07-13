# 0035. Cross-worker SSE events via Redis pub/sub

- **Status**: accepted
- **Date**: 2026-07-13
- **Deciders**: kudratsingh
- **Revisits**: [ADR 0027](0027-docker-compose-redis-job-store.md) (cross-worker signalling)

## Context

ADR 0027 landed `RedisJobStore` for horizontal-scale API. It
correctly excluded `event_queue` (a per-worker `asyncio.Queue`)
from the JSON-serialized shape, but the streaming endpoint
`GET /research/{job_id}/stream` still drained `job.event_queue` on
the worker it landed on. Consequence documented at the time: SSE
required sticky routing (session affinity by `job_id`) on any load
balancer sitting in front of a multi-worker uvicorn.

Sticky routing on `job_id` is nontrivial:

- Not every reverse proxy can hash on a URL path segment. Path-hash
  is straightforward with Nginx / Envoy but requires custom config;
  cookie-based sticky routing (the default in most managed LBs) only
  works after the FIRST request, and the SSE request is often the
  first one for a given `job_id`.
- The audit called this out as crit-adjacent for the same reason as
  the ADR-0034 HITL bug: it ships default-broken under a naïve
  multi-worker deploy.

ADR 0034 landed the equivalent fix for HITL resume. This ADR ports
the same pattern to node events. Bundling the two would have
enlarged that PR without changing the shape; sequencing them keeps
each mechanism reviewable on its own.

## Decision

Three changes, mirroring ADR 0034 as closely as possible so the
mental model is shared between HITL resume and event streaming.

1. **`RedisJobStore.publish_event(job_id, event, data)`** publishes
   a JSON `{event, data}` frame to `events:{job_id}` on Redis
   pub/sub. Called from the runner's `_put_event` and
   `_put_terminal_event` whenever the current context's store
   advertises the method.

2. **`RedisJobStore.subscribe_events(job_id) -> AsyncIterator`**
   subscribes to the channel and yields frames until a terminal
   event (`job_completed` / `job_failed` / `job_cancelled`), then
   returns. Cleanup runs in `finally`: unsubscribe + release the
   pubsub connection. Malformed payloads are logged and skipped
   rather than crashing the subscriber.

3. **Runner + stream endpoint prefer pub/sub when available.**
   `_put_event` and `_put_terminal_event` read a
   `_current_store: ContextVar[JobStore | None]` bound at the top
   of `run_job` (same ContextVar pattern as `_current_costs` in
   observability). When the store has `publish_event`, we call it
   and **skip the local `job.event_queue`** — under multi-worker
   the runner's queue has no consumer, and a blocking
   `event_queue.put()` on the terminal frame would deadlock the
   runner after 1024 events accumulate. `stream_research` picks
   `store.subscribe_events` over `drain_events` via `getattr`.
   The generator gets an explicit `aclose()` in the endpoint's
   `finally` so a disconnected client tears down the Redis pubsub
   without relying on generator GC.

Detection is duck-typed (`getattr(store, "publish_event", None)` /
`getattr(store, "subscribe_events", None)`) — same idiom as
`watch_for_remote_resume` in ADR 0034. `InMemoryJobStore` doesn't
implement these methods; its single-worker world uses the local
queue as before, unchanged.

## Alternatives considered

- **Redis Streams instead of pub/sub.** Streams give at-least-once
  delivery + consumer groups + replay from an offset. Rejected:
  every worker would need to advance an independent consumer
  cursor per stream (per job), and the "fan out one live event to
  many potential subscribers" pattern is exactly what pub/sub
  optimizes. The durable snapshot of terminal jobs is already in
  the Redis Job entry, so replay isn't a use case — reconnecting
  clients hit the endpoint, see the terminal state, get the single
  replay frame, and close. No stream replay needed.

- **Sticky routing on the load balancer (status quo).** Rejected:
  works only when the LB has path-hash support or a cookie has
  already been set. For a fresh SSE request against a Redis-backed
  job store, cookie-based affinity is a 50/50 coin flip until the
  first response. This is exactly the multi-worker foot-gun the
  audit flagged.

- **Poll instead of stream** (GET `/research/{id}` in a loop).
  Rejected: works fine for programmatic clients but breaks the
  demo UI's live experience and doubles the client complexity for
  a bug that's addressable server-side.

- **Runner publishes to both pub/sub AND local queue.** Rejected:
  double-delivery in the same-worker case, either duplicate events
  on the wire or extra bookkeeping to dedupe. The chosen shape —
  pub/sub OR local queue, never both — is simpler and matches how
  ADR 0034's HITL resume handles same-worker vs cross-worker (fast
  path + subscription).

- **Threading `store` through every `_put_event` call site**
  instead of a ContextVar. Rejected: 13 call sites and a
  cross-cutting concern. The ContextVar pattern is already
  established for `run_id` and `current_costs`, so this fits.

## Consequences

**Positive**

- Multi-worker uvicorn + `RedisJobStore` now streams SSE without
  sticky routing on the LB. The compose stack works end-to-end
  under a naïve horizontal-scale deployment.
- No local-queue deadlock: the blocking `_put_terminal_event`
  path is only reachable under `InMemoryJobStore`, where a
  consumer is guaranteed to be on the same worker.
- Client disconnect explicitly aclose()s the async generator, so
  the Redis pubsub subscription is released deterministically.
  Previously the drain-loop path leaked event_queue slots on
  disconnect (audit finding).

**Negative**

- One Redis publish per node event. At the current pace (roughly
  5-10 events per job) this is negligible. At 10k concurrent jobs
  each firing 10 events/sec it's a Redis workload the operator
  should be aware of — but so is having 10k concurrent jobs.
- Same-worker deployments with `RedisJobStore` now round-trip
  every event through Redis. Small perf cost for consistency;
  detecting "am I on the runner's worker" would add complexity
  without meaningful benefit at demo scale.
- Pub/sub is fire-and-forget: a subscriber that connects AFTER an
  event fires misses it. This was already true for the local queue
  (an event `get_nowait`-ed off the queue is gone) — the fix stays
  the same: reconnecting clients hit the terminal replay branch or
  see the current state via `GET /research/{id}`.

**Follow-ups**

- Consolidate the pub/sub subscription pattern across HITL resume
  and events into a helper if a third channel is added.
- Consider a lightweight `JobEventBus` Protocol so callers don't
  reach into `RedisJobStore` via `getattr`. Not urgent: two methods,
  two consumers.
- Rewrite the SSE stream loop to use `asyncio.wait_for` instead of
  the current create-task-per-iteration heartbeat pattern (audit
  finding). Independent PR.
