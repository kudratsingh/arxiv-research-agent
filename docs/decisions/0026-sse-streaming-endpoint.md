# 0026. Hand-rolled SSE streaming endpoint

- **Status**: accepted
- **Date**: 2026-07-10
- **Depends on**: ADR
  [0025](0025-fastapi-async-job-model.md) (job model)

## Context

The polling API from ADR 0025 (`GET /research/{job_id}`) works but
gives a poor UX for a workflow that takes 30–90 seconds — a UI has
to guess at a polling interval and either waste requests polling too
fast or leave the user staring at a stale spinner polling too slow.
Real-time progress (per-node updates, cost tick-up, iteration
counter, terminal frame) needs a push channel.

Two industry-standard options for one-way server-to-client push over
HTTP:

- **WebSockets.** Bidirectional, requires HTTP upgrade, proxies need
  explicit configuration, no automatic reconnect in the spec.
- **Server-Sent Events (SSE).** One-way, plain HTTP, browsers
  auto-reconnect via `EventSource`, works through vanilla reverse
  proxies (nginx + friends) once `X-Accel-Buffering: no` is set.

The workflow only pushes; the client never talks back mid-stream
(cancel is a separate REST call, not a bidirectional message).
Bidirectional messaging is over-engineering; the SSE trade-offs
(one-way, HTTP, less framework code) are a strict win.

## Decision

New endpoint `GET /research/{job_id}/stream` returns a FastAPI
`StreamingResponse` with `media_type="text/event-stream"`. Wire
format is hand-rolled in `src/api/streaming.py` — the SSE spec is
under 20 lines of code and we don't need the extras that
`sse-starlette` provides (retry hints, custom event-source names).
Fewer deps, and the code is legible on the page.

### Event schema

```
event: <event_name>
data: <compact JSON payload>
<blank line>
```

Event names, in order:

- `job_started` — one frame, kicks the stream. Contains `job_id`
  and `query`.
- `node_completed` (N frames) — one per LangGraph node executed;
  `data.state_delta` carries the scalar fields that changed
  (`iteration`, `quality_score`, etc.). Large fields (paper lists,
  citations) are excluded from the stream because they change
  frequently and the full snapshot is one poll away on
  `GET /research/{job_id}`.
- `job_completed` **or** `job_failed` **or** `job_cancelled` — one
  terminal frame, then the server closes the response. Terminal
  frame carries the same numeric fields as the polling endpoint
  (cost, iterations, elapsed) so an SSE-only client never needs to
  poll.

Heartbeat: a `: heartbeat\n\n` comment frame every
`HEARTBEAT_INTERVAL_SEC = 15` if no events fire in that window.
Comment lines are discarded by SSE clients (per the WHATWG spec),
so they keep intermediaries from timing out the connection without
polluting the event log.

### Reconnect semantics

If a client connects to `/stream` after the job has already
terminated, the server replays exactly one terminal frame and
closes. That makes reconnects idempotent — a UI can safely retry
the stream after a network hiccup and always get the final state.

If the job is still running when a client reconnects, the client
gets the *rest* of the event stream from that point onward
(intermediate events already emitted are dropped when the queue
rotates — the polling endpoint is the authoritative event history,
not the stream).

### Disconnect handling

The endpoint checks `await request.is_disconnected()` between
events and exits cleanly on client disconnect. The job itself
continues running in the background — a disconnected client is not
a cancel signal (cancel is a separate REST action; not shipped in
this PR because the CLI + eval paths don't need it, though the
runner already handles `CancelledError` for the lifespan-shutdown
path).

### Reverse-proxy compatibility

Response headers:

- `Cache-Control: no-cache` — SSE must not be cached mid-stream.
- `X-Accel-Buffering: no` — disables nginx's response buffering;
  without it, nginx accumulates the whole response before flushing.
- `Connection: keep-alive` — belt + suspenders for older proxies.

## Alternatives considered

- **`sse-starlette` library.** Widely used, adds ~200 LOC of
  polished helpers. Buys us less than we thought: our event schema
  is fixed, we don't need `EventSourceResponse`'s retry hint (SSE
  clients auto-reconnect), and its `ping` mechanism is what our
  15-second heartbeat already does. Rejected on
  "dependency-for-nothing" grounds.
- **WebSockets.** Bidirectional, no clear win here since the
  client never speaks. More framework overhead (upgrade handshake,
  ping/pong, framing), and `EventSource`'s auto-reconnect story is
  strictly nicer than a WebSocket client's manual retry loop.
  Rejected.
- **Long-polling.** Client makes a request, server holds it open
  for N seconds waiting for an event. Simple but wasteful —
  reconnects on every event, and the timing story on the client
  gets hairy. Rejected.
- **Push events into the polling endpoint via a `since` cursor.**
  Cleaner (fewer endpoints) but requires the client to poll at all
  — the UX we're trying to fix. Rejected.
- **Include the full state snapshot on every `node_completed`.**
  Tempting because the client wouldn't need to poll for the full
  result. Rejected: paper analyses and evidence lists can be 10–100
  KB each and stream growth becomes unbounded as the workflow
  iterates. Scalar deltas on the stream + one final `GET` for the
  full result is a cleaner split.

## Consequences

- **Positive.** Real-time UX for a long-running workflow with zero
  new deps. Reconnects are idempotent. Reverse-proxy compatibility
  is one header away. The event schema is deliberately compact so
  the wire cost is negligible compared to the workflow cost. The
  client's UI can render node-by-node progress the moment nodes
  finish rather than at poll boundaries.
- **Negative.** The reconnect story drops intermediate events if
  the queue rotates while a client is disconnected. That's the
  correct trade-off for an unbounded stream on a bounded queue,
  but a UI that cares about the full event history must persist it
  itself. Two options in a follow-up: raise the queue bound
  (memory-cheap), or persist the event stream to the JobStore (more
  work, unlocks history-on-reconnect).
- **Follow-ups.**
  - **Cancel endpoint** — `POST /research/{job_id}/cancel`, once we
    have a client that needs it. The runner already handles the
    `CancelledError` path for lifespan shutdown, so wiring is
    small.
  - **Event history in the JobStore** — for reconnects that want
    every event since submit rather than only future events.
  - **Retry hint** — a `retry: <ms>\n` frame at the start of the
    stream tunes the browser's `EventSource` reconnect backoff.
    Skipped for now because the default (~3 s) is fine.
