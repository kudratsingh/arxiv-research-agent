"""SSE event formatting for the streaming endpoint.

Hand-rolled rather than pulling in `sse-starlette` — the SSE wire
protocol is a dozen lines and we don't need the library's extras
(retry hints, custom event-source names). Fewer deps, clearer code.

Wire format (per https://html.spec.whatwg.org/multipage/server-sent-events.html):

    event: <event_name>
    data: <json_payload>
    <blank line>

Event names emitted by the runner:

  - `node_started`   — a graph node began executing
  - `node_completed` — a graph node produced output; `state_delta` in data
  - `plan_ready`     — HITL breakpoint hit (ADR 0030); `plan` in data.
                       Not terminal — the stream stays open through the
                       review action + resumed nodes.
  - `job_completed`  — terminal frame; `result` field populated
  - `job_failed`     — terminal frame; `error` + `error_type` populated
  - `heartbeat`      — periodic keepalive so proxies don't drop the stream

Design in ADR 0026 (+ ADR 0030 for the HITL event).
"""

from __future__ import annotations

import json
from typing import Any

HEARTBEAT_INTERVAL_SEC: float = 15.0

TERMINAL_EVENT_NAMES: frozenset[str] = frozenset(
    {"job_completed", "job_failed", "job_cancelled"}
)


def format_sse(event: str, data: dict[str, Any]) -> bytes:
    """Encode `(event, data)` as one SSE frame.

    The payload is JSON so clients don't have to guess at the shape;
    the event name is the routing signal.
    """
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
    # A trailing blank line terminates the frame per the SSE spec.
    return f"event: {event}\ndata: {payload}\n\n".encode()


def format_heartbeat() -> bytes:
    """SSE comment frame — keeps intermediaries from closing an idle
    stream. Comment lines start with `:` and clients discard them.
    """
    return b": heartbeat\n\n"


def is_terminal_event(event_name: str) -> bool:
    """True when this event closes the stream from the server side."""
    return event_name in TERMINAL_EVENT_NAMES
