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

ADR 0057 adds the one case this design did not have before: a backend event
the web tier does not consume *yet*. `turn_ready` is emitted by the session
parking, and the surface that listens for it is WO-W13's — adding it to
`web/lib/api/events.ts` today would force ten new rows into
`web/lib/job/machine.ts`'s total transition table for a phase no route can
reach. So the gap is declared, in `WEB_UNCONSUMED_EVENT_NAMES`, and tested
from both directions: the backend must emit it, and the web client must not
yet declare it. That is a ledger entry with an owner, not a hole.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.api.jobs import Job, JobStatus
from src.api.routes import _terminal_event_name
from src.api.streaming import (
    PAUSE_EVENT_NAMES,
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

#: `TERMINAL_EVENT_NAMES ∪ {job_started, node_completed} ∪ PAUSE_EVENT_NAMES ∪
#: {STREAM_TIMEOUT_EVENT}` — written out rather than composed, because a pin
#: that derives itself from its subject pins nothing.
PINNED_EVENT_NAMES = frozenset(
    {
        "job_started",
        "node_completed",
        "plan_ready",
        "turn_ready",
        "job_completed",
        "job_failed",
        "job_cancelled",
        "stream_timeout",
    }
)

#: Backend events the web tier does not listen for yet, with the work order
#: that closes each. Every name here is one the server really emits, so the
#: entry is a declared debt rather than an omission — and both halves are
#: asserted below, so neither a forgotten pickup nor a premature one passes.
WEB_UNCONSUMED_EVENT_NAMES: dict[str, str] = {
    # WO-W13 (the guided-read session view) adds the listener. Until a
    # route can create a `kind="session"` job there is nothing for the
    # client to render, and declaring the name early would force ten
    # rows into `web/lib/job/machine.ts`'s total transition table for a
    # phase that is unreachable.
    "turn_ready": "WO-W13",
}

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
        | {"job_started", "node_completed"}
        | PAUSE_EVENT_NAMES
        | {STREAM_TIMEOUT_EVENT}
        == PINNED_EVENT_NAMES
    )


def test_pause_frames_never_end_the_stream() -> None:
    """The property ADR 0057 asks to be asserted rather than commented.

    A parking frame says "a human has to act now". Landing one in either
    closing set would tear the connection down at exactly the moment the
    human is supposed to act — and for a session, which parks once per
    turn rather than once per run, that would be every turn.
    """
    assert {"plan_ready", "turn_ready"} == PAUSE_EVENT_NAMES
    assert not (PAUSE_EVENT_NAMES & TERMINAL_EVENT_NAMES)
    assert not (PAUSE_EVENT_NAMES & STREAM_CLOSING_EVENT_NAMES)
    # And each is a real event, not a name that only exists in the set.
    assert PAUSE_EVENT_NAMES <= PINNED_EVENT_NAMES


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
    assert len(runner) == 7, runner
    assert "plan_ready" in routes
    # Both parking frames have an attach-time replay (ADR 0053/0057), so
    # both are emitted from the route as well as from the runner.
    assert routes >= PAUSE_EVENT_NAMES

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


def _declared_server_event_names() -> set[str]:
    block = re.search(
        r"export const SERVER_EVENT_NAMES = \[(.*?)\] as const;",
        EVENTS_TS,
        re.DOTALL,
    )
    assert block is not None, "SERVER_EVENT_NAMES not found in events.ts"
    return set(re.findall(r'"([a-z_]+)"', block.group(1)))


def test_the_web_client_declares_exactly_the_same_set() -> None:
    """Cross-side tie: `web/lib/api/events.ts` is hand-written, so read it.

    The Vitest half asserts the same list from inside the module system; this
    reads the source so that a backend change alone is enough to fail the
    Python job, without anyone having to run the web suite.

    "The same set" now means "the same set, minus the declared debts" —
    see `WEB_UNCONSUMED_EVENT_NAMES`. A backend event that is neither
    consumed nor listed there still fails here, which is the property
    this test existed for.
    """
    assert (
        _declared_server_event_names()
        == PINNED_EVENT_NAMES - set(WEB_UNCONSUMED_EVENT_NAMES)
    )


def test_the_unconsumed_ledger_describes_reality_on_both_sides() -> None:
    """A debt that is not real is worse than no ledger at all.

    Both halves, because both ways of being wrong are silent: an entry
    for an event the backend does not emit would excuse the web tier
    from a name that will never arrive, and an entry for one the web
    tier *has* since picked up would keep excusing it forever — the
    listener would exist while the drift check went on ignoring it.
    """
    emitted = _runner_event_names() | _route_event_names()
    declared = _declared_server_event_names()
    for name, owner in WEB_UNCONSUMED_EVENT_NAMES.items():
        assert name in emitted, f"{name} is listed as unconsumed but never emitted"
        assert name not in declared, (
            f"{name} is declared in events.ts; drop it from "
            "WEB_UNCONSUMED_EVENT_NAMES so the drift check covers it again"
        )
        assert owner, f"{name} has no owning work order"


def test_the_web_client_keeps_stream_timeout_out_of_the_terminal_set() -> None:
    block = re.search(
        r"export const TERMINAL_EVENTS.*?\[(.*?)\]", EVENTS_TS, re.DOTALL
    )
    assert block is not None

    declared = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert declared == set(TERMINAL_EVENT_NAMES)
    assert STREAM_TIMEOUT_EVENT not in declared
