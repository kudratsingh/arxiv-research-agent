"""Drift check 4 of 4: the SSE event-name set, pinned on both sides.

The stream is not in the OpenAPI document, so nothing generates the frontend's
view of it — `web/lib/api/events.ts` is transcribed from this backend by hand
(04-ARCHITECTURE.md §3.2). That makes an added backend event a silent hole:
the server starts sending a frame no client has ever heard of, and no build
anywhere fails.

This is the producer half. It does three things:

1. Pins the set to a literal, so a change to `TERMINAL_EVENT_STATUS` fails.
2. Derives the set from the emit sites in `src/api/runner.py`,
   `src/api/routes.py` and `src/api/streaming.py`, so adding a *non-terminal*
   event — which no constant would notice — fails too.
3. Reads the literal back out of `web/lib/api/events.ts`, so the two sides
   cannot drift apart.

The consumer half is `web/tests/contract/events.test.ts`. Adding a backend
event breaks both.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.api.jobs import Job, JobStatus
from src.api.routes import _terminal_event_name
from src.api.streaming import (
    STREAM_CLOSING_EVENT_NAMES,
    STREAM_TIMEOUT_EVENT,
    TERMINAL_EVENT_NAMES,
    TERMINAL_EVENT_STATUS,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
RUNNER_SRC = (ROOT / "src" / "api" / "runner.py").read_text(encoding="utf-8")
ROUTES_SRC = (ROOT / "src" / "api" / "routes.py").read_text(encoding="utf-8")
EVENTS_TS = (ROOT / "web" / "lib" / "api" / "events.ts").read_text(
    encoding="utf-8"
)

#: `TERMINAL_EVENT_NAMES ∪ {job_started, node_completed, plan_ready} ∪
#: {STREAM_TIMEOUT_EVENT}` — written out rather than composed, because a pin
#: that derives itself from its subject pins nothing.
PINNED_EVENT_NAMES = frozenset(
    {
        "job_started",
        "node_completed",
        "plan_ready",
        "job_completed",
        "job_failed",
        "job_cancelled",
        "stream_timeout",
    }
)

#: The runner's own emit helpers. Both take `(job, event_name, payload)`.
_RUNNER_EMIT = re.compile(
    r'_put_(?:terminal_)?event\(\s*job,\s*"([a-z_]+)"', re.MULTILINE
)

#: Attach-time replay writes frames directly (`routes.py:438-441`, `:464`).
_ROUTE_EMIT = re.compile(r'format_sse\(\s*"([a-z_]+)"')


def _job(status: JobStatus) -> Job:
    """A job row carrying nothing but the status the name depends on."""
    return Job(job_id="contract-pin", query="contract-pin", status=status)


def _runner_event_names() -> set[str]:
    return set(_RUNNER_EMIT.findall(RUNNER_SRC))


def _route_event_names() -> set[str]:
    """Names the stream route can write, including the dynamic terminal one."""
    names = set(_ROUTE_EMIT.findall(ROUTES_SRC))
    # `format_sse(_terminal_event_name(job), ...)` — resolved by asking the
    # function, so a fourth terminal status would show up here.
    for status in JobStatus:
        names.add(_terminal_event_name(_job(status)))
    return names


def test_pinned_set_is_the_documented_union() -> None:
    assert (
        TERMINAL_EVENT_NAMES
        | {"job_started", "node_completed", "plan_ready"}
        | {STREAM_TIMEOUT_EVENT}
        == PINNED_EVENT_NAMES
    )


def test_terminal_names_stay_derived_from_their_status_mapping() -> None:
    # `TERMINAL_EVENT_NAMES` is `frozenset(TERMINAL_EVENT_STATUS)`, and the
    # stream stops on a strictly wider set.
    assert frozenset(TERMINAL_EVENT_STATUS) == TERMINAL_EVENT_NAMES
    assert set(TERMINAL_EVENT_NAMES) == {
        "job_completed",
        "job_failed",
        "job_cancelled",
    }
    assert set(STREAM_CLOSING_EVENT_NAMES) == TERMINAL_EVENT_NAMES | {
        STREAM_TIMEOUT_EVENT
    }
    # The stream ended; the job did not (`streaming.py:108-114`).
    assert STREAM_TIMEOUT_EVENT not in TERMINAL_EVENT_NAMES


def test_every_emitted_name_is_in_the_pinned_set() -> None:
    """The half a constant cannot catch: a new event at a new emit site."""
    runner = _runner_event_names()
    routes = _route_event_names()

    # Guard against a regex that quietly matches nothing.
    assert len(runner) == 6, runner
    assert "plan_ready" in routes

    assert runner | routes | {STREAM_TIMEOUT_EVENT} == PINNED_EVENT_NAMES


def test_there_is_no_node_started() -> None:
    # `src/api/streaming.py:13-35` says so explicitly: the runner emits only
    # after a node returns. It is the event people assume exists.
    assert "node_started" not in _runner_event_names()
    assert "node_started" not in PINNED_EVENT_NAMES


def test_attach_replay_reuses_the_runner_terminal_names() -> None:
    """One name, two payload shapes — but never a name of its own.

    `routes.py:857-867` replays a terminal outcome under the same event name
    the runner would have used, with `status` added and `llm_calls` dropped.
    A separate replay-only name would be a fourth event the client would have
    to learn, so this pins that it stays three.
    """
    replayed = {
        _terminal_event_name(_job(status))
        for status in (
            JobStatus.succeeded,
            JobStatus.failed,
            JobStatus.cancelled,
        )
    }
    assert replayed == TERMINAL_EVENT_NAMES


def test_the_web_client_declares_exactly_the_same_set() -> None:
    """Cross-side tie: `web/lib/api/events.ts` is hand-written, so read it.

    The Vitest half asserts the same list from inside the module system; this
    reads the source so that a backend change alone is enough to fail the
    Python job, without anyone having to run the web suite.
    """
    block = re.search(
        r"export const SERVER_EVENT_NAMES = \[(.*?)\] as const;",
        EVENTS_TS,
        re.DOTALL,
    )
    assert block is not None, "SERVER_EVENT_NAMES not found in events.ts"

    declared = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert declared == PINNED_EVENT_NAMES


def test_the_web_client_keeps_stream_timeout_out_of_the_terminal_set() -> None:
    block = re.search(
        r"export const TERMINAL_EVENTS.*?\[(.*?)\]", EVENTS_TS, re.DOTALL
    )
    assert block is not None

    declared = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert declared == set(TERMINAL_EVENT_NAMES)
    assert STREAM_TIMEOUT_EVENT not in declared
