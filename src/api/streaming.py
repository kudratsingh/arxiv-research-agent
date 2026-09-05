"""SSE wire format + the server-side streaming loop.

Hand-rolled rather than pulling in `sse-starlette` — the SSE wire
protocol is a dozen lines and we don't need the library's extras
(retry hints, custom event-source names). Fewer deps, clearer code.

Wire format (per https://html.spec.whatwg.org/multipage/server-sent-events.html):

    event: <event_name>
    data: <json_payload>
    <blank line>

Event names emitted by the runner:

  - `job_started`    — the runner picked the job up off the queue
  - `node_completed` — a graph node produced output; `state_delta` in data
  - `plan_ready`     — HITL breakpoint hit (ADR 0030); `plan` in data.
                       Not terminal — the stream stays open through the
                       review action + resumed nodes.
  - `turn_ready`     — a `session` job parked in `awaiting_learner`
                       (ADR 0057); `turn` in data. Not terminal, for
                       exactly the reason `plan_ready` is not: the
                       stream carries the whole session, and a frame
                       that closed it would make every turn cost a
                       reconnect.
  - `job_completed`  — terminal frame; `result` field populated
  - `job_failed`     — terminal frame; `error` + `error_type` populated
  - `job_cancelled`  — terminal frame; client cancel or app shutdown
  - `heartbeat`      — periodic keepalive so proxies don't drop the stream

This list is the contract clients code against, so it is kept exact:
there is no `node_started` (the runner only emits after a node
returns), and `job_started` / `job_cancelled` are real frames a client
must handle. `tests/test_sse_stream.py` pins the terminal names
against the runner's; the non-terminal ones are documentation.

Emitted by the server itself, never by the runner:

  - `stream_timeout` — the connection hit `api_sse_max_duration_sec`
                       (ADR 0038). The job is *not* finished; the
                       client should reconnect to the same stream URL.

`sse_event_stream` lives here rather than inside the route handler so
the loop is testable without FastAPI, without Redis, and without real
sleeping: it takes its drainer, its disconnect probe and its clock as
parameters. See ADR 0038 for why that mattered — the previous
in-route loop raced a fresh `__anext__` task against a sleep and
cancelled the loser, which tore the drainer down at its suspension
point and silently killed the stream after the first idle heartbeat.

Design in ADR 0026 (+ ADR 0030 for the HITL event, ADR 0038 for the
loop rewrite).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Mapping,
)
from types import MappingProxyType
from typing import Any

from src.observability import (
    DEGRADATION_RUNG_STREAMING_PARTIAL,
    get_logger,
    record_degradation_rung,
)

log = get_logger(__name__)

HEARTBEAT_INTERVAL_SEC: float = 15.0

# Fallback ceiling on a single connection's lifetime. The live value
# is `settings.api_sse_max_duration_sec`; this constant only supplies
# the default when a caller (a test, usually) passes neither.
MAX_STREAM_DURATION_SEC: float = 3600.0

STREAM_TIMEOUT_EVENT: str = "stream_timeout"

# The outcome each terminal frame asserts, as a `JobStatus` *value*.
# Deliberately plain strings rather than the enum: `src.api.jobs`
# imports nothing from here today and this module is imported by the
# store, so keeping the dependency one-way avoids an import cycle for
# a three-entry lookup table. `tests/test_sse_stream.py` pins the
# mapping against the real `JobStatus` members.
#
# `RedisJobStore.publish_event` uses it to answer "does this terminal
# frame agree with the row that is actually persisted?" (ADR 0048) —
# a `job_completed` published after a redriver already wrote
# `failed/orphaned` would show a client a success it will never be
# able to fetch.
TERMINAL_EVENT_STATUS: Mapping[str, str] = MappingProxyType(
    {
        "job_completed": "succeeded",
        "job_failed": "failed",
        "job_cancelled": "cancelled",
    }
)

# "Did the job reach a terminal state?" — these are the runner's own
# terminal frames, and nothing else belongs here. This is the single
# definition: `RedisJobStore.subscribe_events` imports it for the same
# question on the pub/sub side, and `_terminal_event_name` in
# routes.py produces exactly these three names on replay. Derived from
# `TERMINAL_EVENT_STATUS` so the two cannot drift apart.
TERMINAL_EVENT_NAMES: frozenset[str] = frozenset(TERMINAL_EVENT_STATUS)

# "Should the server stop streaming?" — a strictly wider question
# (ADR 0038). `stream_timeout` closes the connection while the job
# keeps running, so it is deliberately *not* a member of
# `TERMINAL_EVENT_NAMES`: a subscriber that treated it as a job
# outcome would report a healthy job as finished, and the store's
# pub/sub reader would stop consuming a channel that still has
# frames coming.
STREAM_CLOSING_EVENT_NAMES: frozenset[str] = TERMINAL_EVENT_NAMES | {
    STREAM_TIMEOUT_EVENT
}

# The frames that say "a human has to do something now". Not a
# dispatch table — nothing branches on this set — but the deliberate
# record ADR 0057 asks for: adding a parking status means adding a
# pause frame, and a pause frame that leaked into either set above
# would end the stream at the moment the human was supposed to act.
# `tests/test_contract_sse_events.py` asserts the disjointness rather
# than trusting this comment.
PAUSE_EVENT_NAMES: frozenset[str] = frozenset({"plan_ready", "turn_ready"})


# ---------------------------------------------------------------------------
# Canonical-event projection (P0-WO08, ADR 0083)
#
# RFC 10 §16 pairs each canonical trajectory event with the runtime
# surface it may be projected onto. This table is that pairing, and it is
# deliberately a *derivation* rather than an emitter: nothing here writes
# a frame, no new event name appears on the wire, and the byte-for-byte
# shape of every frame the web tier consumes is unchanged. Its whole
# value is that the claim "the SSE stream is a projection of the ledger"
# becomes checkable — `tests/test_contract_runtime_bridge.py` asserts
# that the projected name for a terminal event equals the name the runner
# already emits and that the projected frame is byte-identical to the one
# `terminal_event_data` builds.
#
# Every value is a member of the pinned set in
# `tests/test_contract_sse_events.py`; a canonical event with no safe
# projection maps to nothing at all rather than to an invented frame.
# ---------------------------------------------------------------------------

#: Canonical event type -> the existing SSE frame it projects onto.
#: `hitl.requested` is absent because its frame depends on the request
#: kind — see `sse_event_name_for`.
CANONICAL_EVENT_PROJECTION: Mapping[str, str] = MappingProxyType(
    {
        "attempt.started": "job_started",
        "action.completed": "node_completed",
        "run.completed": "job_completed",
        "run.failed": "job_failed",
        "run.budget_stopped": "job_failed",
        "run.cancelled": "job_cancelled",
    }
)

#: HITL request kind -> the parking frame it projects onto. RFC 10 §8.8:
#: "The existing `plan_ready` and `turn_ready` SSE frames are projections
#: of `hitl.requested`, not canonical writes from the client stream."
HITL_EVENT_PROJECTION: Mapping[str, str] = MappingProxyType(
    {
        "plan_review": "plan_ready",
        "learner_turn": "turn_ready",
    }
)


def sse_event_name_for(
    event_type: str, *, request_kind: str | None = None
) -> str | None:
    """The SSE frame one canonical trajectory event projects onto.

    Args:
        event_type: An RFC 10 §8 event type.
        request_kind: For `hitl.requested`, the pause's kind.

    Returns:
        An existing SSE event name, or `None` when this canonical event
        has no client-visible projection — which is the common case and
        not a gap: the ledger records far more than a browser needs, and
        a projection nobody asked for would be a new client contract.
    """
    if event_type == "hitl.requested":
        return HITL_EVENT_PROJECTION.get(request_kind or "")
    return CANONICAL_EVENT_PROJECTION.get(event_type)


#: The three line terminators the SSE spec recognises (CR, LF, CRLF),
#: deleted from an event name before it reaches the wire. A `str`
#: translation table rather than three `replace` calls so CRLF costs one
#: pass and cannot leave a stray CR behind.
_LINE_TERMINATORS: Mapping[int, None] = str.maketrans({"\r": None, "\n": None})


def format_sse(event: str, data: dict[str, Any]) -> bytes:
    """Encode `(event, data)` as one SSE frame.

    The payload is JSON so clients don't have to guess at the shape;
    the event name is the routing signal.

    The name is stripped of line terminators first. SSE has no framing
    beyond the blank line, so a name containing one does not produce a
    malformed frame — it produces *two* frames, and the client routes
    the remainder as an event it has never heard of while the server
    reports nothing. The `data:` line is already safe because
    `json.dumps` escapes newlines inside strings; the event name had no
    equivalent. Unreachable from the closed set of names the runner
    emits today, and that is exactly why it is worth fixing now: the
    day a name is derived from anything a client supplies, the injection
    is already in the encoder.

    Args:
        event: SSE event name, used by the client as the routing key.
        data: JSON-serializable payload for the `data:` line.

    Returns:
        The encoded frame, terminated by a blank line.
    """
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
    safe_event = event.translate(_LINE_TERMINATORS)
    if safe_event != event:
        # The sanitised name, never the raw one: this line exists
        # because something put a frame separator in an event name, and
        # echoing it verbatim would carry the same split into the log
        # stream's own record of the incident.
        log.warning("sse_event_name_sanitised", extra={"event": safe_event})
    # A trailing blank line terminates the frame per the SSE spec.
    return f"event: {safe_event}\ndata: {payload}\n\n".encode()


def format_heartbeat() -> bytes:
    """SSE comment frame — keeps intermediaries from closing an idle
    stream. Comment lines start with `:` and clients discard them.

    Returns:
        The encoded comment frame.
    """
    return b": heartbeat\n\n"


def is_terminal_event(event_name: str) -> bool:
    """True when this event means the *job* reached a terminal state.

    Args:
        event_name: SSE event name off the wire.

    Returns:
        True for the runner's terminal frames. `stream_timeout` is
        not one of them — see `STREAM_CLOSING_EVENT_NAMES`.
    """
    return event_name in TERMINAL_EVENT_NAMES


def closes_stream(event_name: str) -> bool:
    """True when the server stops streaming after this event.

    Args:
        event_name: SSE event name about to be written to the wire.

    Returns:
        True for the runner's terminal frames *and* for the
        server-generated `stream_timeout`.
    """
    return event_name in STREAM_CLOSING_EVENT_NAMES


async def _next_frame(drainer: AsyncIterator[dict[str, Any]]) -> dict[str, Any]:
    """Wrap `drainer.__anext__()` in a real coroutine.

    `create_task` needs a coroutine; `__anext__` is only typed as an
    Awaitable. This is the whole reason the wrapper exists.

    Args:
        drainer: The event source being pulled.

    Returns:
        The next frame.

    Raises:
        StopAsyncIteration: The drainer is exhausted.
    """
    return await drainer.__anext__()


async def sse_event_stream(
    drainer: AsyncIterator[dict[str, Any]],
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
    heartbeat_sec: float = HEARTBEAT_INTERVAL_SEC,
    max_duration_sec: float = MAX_STREAM_DURATION_SEC,
    now: Callable[[], float] = time.monotonic,
    job_id: str | None = None,
) -> AsyncGenerator[bytes, None]:
    """Turn a frame drainer into an SSE byte stream (ADR 0038).

    Emits one keepalive immediately, then each frame the drainer
    produces, interleaving keepalives whenever the job stays quiet
    for `heartbeat_sec`. Stops on a terminal frame, on client
    disconnect, on drainer exhaustion, or at the stream deadline —
    and closes the drainer on every one of those paths.

    The pending-read task is created **once** and kept alive across
    iterations. `asyncio.wait(..., timeout=...)` leaves an unfinished
    task pending instead of cancelling it, which is what keeps the
    drainer alive through an idle heartbeat; the previous
    `FIRST_COMPLETED` + `cancel()` loop threw `CancelledError` into
    the drainer at its suspension point, ran its `finally` (for
    `RedisJobStore.subscribe_events`: unsubscribe + `pubsub.aclose()`)
    and left every subsequent read raising. A frame already pulled
    off the queue by that cancelled task was lost with it.

    At the deadline a frame the read task has *already* produced is
    flushed before the stream closes (ADR 0048). If that frame is a
    closing one the `stream_timeout` frame is skipped entirely —
    `stream_timeout` means "reconnect, the job is still going", which
    is exactly wrong once the job has ended.

    The drainer's cleanup lives in this generator's `finally`, so a
    caller that can abandon the stream part-way — `StreamingResponse`
    drops its body iterator on socket loss without closing it — must
    wrap it in `contextlib.aclosing`. Left to the async-generator
    finalizer, the unsubscribe runs whenever GC gets round to it.

    Args:
        drainer: Async iterator of `{"event": str, "data": dict}`
            frames — `drain_events` for `InMemoryJobStore`, or
            `RedisJobStore.subscribe_events` under ADR 0035.
        is_disconnected: Probe for client disconnect, normally
            `request.is_disconnected`. Only polled between wakeups,
            so detection latency is bounded by `heartbeat_sec` (a
            disconnected client costs at most one idle interval of
            a pinned connection).
        heartbeat_sec: Idle interval between keepalive frames.
        max_duration_sec: Ceiling on the connection's lifetime.
        now: Monotonic clock, injectable so tests can drive the
            deadline without sleeping.
        job_id: Included in log records and in the `stream_timeout`
            payload when known.

    Yields:
        Encoded SSE frames, ready to write to the socket.
    """
    deadline = now() + max_duration_sec
    get_task: asyncio.Task[dict[str, Any]] | None = None
    # Everything, including the opening keepalive, sits inside the
    # `try` so the drainer is closed even when the client vanishes
    # between connect and first read.
    try:
        # Bytes on the wire before anything is awaited: it flushes any
        # proxy that buffers until first output, and makes
        # time-to-first-byte independent of how long the first graph
        # node runs.
        yield format_heartbeat()

        while True:
            if await is_disconnected():
                log.info("sse_client_disconnected", extra={"job_id": job_id})
                return

            remaining = deadline - now()
            if remaining <= 0.0:
                # The read task may already hold a frame produced
                # while we were suspended in the `yield` above (audit
                # P3, ADR 0048): the previous iteration's `wait` timed
                # out, the drainer completed a moment later, and the
                # deadline then fired. Discarding it lost real output —
                # and, when it was the terminal frame, told the client
                # to reconnect to a job that had already finished.
                if get_task is not None and get_task.done():
                    finished, get_task = get_task, None
                    try:
                        frame = finished.result()
                    except StopAsyncIteration:
                        return
                    event_name = str(frame.get("event", ""))
                    yield format_sse(event_name, frame.get("data") or {})
                    if closes_stream(event_name):
                        # The job ended. `stream_timeout` exists to
                        # tell the client to reconnect; appending it
                        # after a terminal frame would send it back to
                        # a stream that has nothing left to say.
                        log.info(
                            "sse_terminal_frame_flushed_at_deadline",
                            extra={"job_id": job_id, "event": event_name},
                        )
                        return

                # A wedged job must not pin a worker connection
                # forever. Distinguishable from a terminal frame so
                # the client reconnects rather than reporting the job
                # as finished.
                log.info(
                    "sse_stream_deadline_reached",
                    extra={"job_id": job_id, "max_duration_sec": max_duration_sec},
                )
                # Rung 4 of the degradation ladder: the client keeps
                # what arrived and is told to reconnect, which is a
                # partial delivery rather than a failure. Counted here
                # and *not* at the branch above — a terminal frame
                # flushed at the deadline is the recovery, not the
                # degradation, and counting it would inflate the one
                # number the quality SLI is computed from
                # (docs/reliability.md §5, ADR 0081).
                record_degradation_rung(
                    rung=DEGRADATION_RUNG_STREAMING_PARTIAL,
                    component="sse_stream",
                )
                yield format_sse(
                    STREAM_TIMEOUT_EVENT,
                    {
                        "job_id": job_id,
                        "reason": "max_duration_exceeded",
                        "max_duration_sec": max_duration_sec,
                        "reconnect": True,
                    },
                )
                return

            if get_task is None:
                get_task = asyncio.create_task(_next_frame(drainer))

            # A timeout here leaves `get_task` pending and untouched —
            # that is the fix. Never `cancel()` it mid-read.
            done, _pending = await asyncio.wait(
                {get_task}, timeout=min(heartbeat_sec, remaining)
            )
            if not done:
                yield format_heartbeat()
                continue

            # The task produced something; the next iteration needs a
            # fresh read, so drop our handle before touching the
            # result — an exception must not leave a finished task
            # queued for cancellation in `finally`.
            finished, get_task = get_task, None
            try:
                frame = finished.result()
            except StopAsyncIteration:
                # Drainer closed itself (job went terminal, or the
                # pub/sub channel ended). Nothing left to send.
                return

            event_name = str(frame.get("event", ""))
            yield format_sse(event_name, frame.get("data") or {})
            if closes_stream(event_name):
                return
    finally:
        # Cancel exactly once, and await the cancellation so the
        # drainer's own cleanup gets to run before we call `aclose`
        # on it — `aclose()` on a generator another task is still
        # suspended inside raises "already running".
        if get_task is not None:
            get_task.cancel()
            try:
                await get_task
            except asyncio.CancelledError:
                # Expected — we just cancelled it. Not re-raised: the
                # exception that brought us into `finally` (if any) is
                # the one the caller needs to see.
                pass
            except Exception:
                # The drainer raised on its way out. There is no client
                # left to tell, but swallowing it without a trace hides
                # a broken pub/sub connection.
                log.warning(
                    "sse_drainer_read_failed",
                    extra={"job_id": job_id},
                    exc_info=True,
                )
        # Explicit close so the pub/sub subscriber's `finally` clause
        # runs (unsubscribe + release the Redis connection). Relying
        # on generator GC would leak a Redis pubsub client per
        # disconnected SSE client.
        aclose = getattr(drainer, "aclose", None)
        if callable(aclose):
            try:
                await aclose()
            except Exception:
                # Best-effort: the connection is going away regardless,
                # but a repeated failure here means pubsub cleanup is
                # not happening and connections are accumulating.
                log.warning(
                    "sse_drainer_close_failed",
                    extra={"job_id": job_id},
                    exc_info=True,
                )
