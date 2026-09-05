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

ADR 0057 added the one case this design did not have before: a backend event
the web tier did not consume *yet*. `turn_ready` was emitted by the session
parking with no surface listening, so the gap was declared in
`WEB_UNCONSUMED_EVENT_NAMES` and tested from both directions — the backend
must emit it, and the web client must not yet declare it. A ledger entry
with an owner, not a hole.

WO-W13 CLOSED BOTH LEDGERS AND THEY ARE NOW EMPTY. `web/lib/api/events.ts`
declares `turn_ready` and `web/lib/api/models.ts` declares
`awaiting_learner`, so both names are back under the ordinary drift check —
`_declared_server_event_names() == PINNED_EVENT_NAMES` with nothing
subtracted. The two dicts stay in the file, empty, because they are the
mechanism rather than the debt: the next backend event that arrives ahead of
its surface gets an entry and an owner instead of a silent hole, and
`test_the_unconsumed_ledger_describes_reality_on_both_sides` still fails an
entry that has stopped being true in either direction.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.api import redriver as redriver_module
from src.api.jobs import Job, JobStatus
from src.api.routes import _terminal_event_name
from src.api.runner import terminal_event_data
from src.api.streaming import (
    PAUSE_EVENT_NAMES,
    STREAM_CLOSING_EVENT_NAMES,
    STREAM_TIMEOUT_EVENT,
    TERMINAL_EVENT_NAMES,
    TERMINAL_EVENT_STATUS,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract]

ROOT = Path(__file__).resolve().parents[1]
RUNNER_SRC = (ROOT / "src" / "api" / "runner.py").read_text(encoding="utf-8")
ROUTES_SRC = (ROOT / "src" / "api" / "routes.py").read_text(encoding="utf-8")
EVENTS_TS = (ROOT / "web" / "lib" / "api" / "events.ts").read_text(
    encoding="utf-8"
)
MODELS_TS = (ROOT / "web" / "lib" / "api" / "models.ts").read_text(
    encoding="utf-8"
)
REDRIVER_SRC = (ROOT / "src" / "api" / "redriver.py").read_text(encoding="utf-8")

#: Every key a terminal SSE frame carries, whichever of the three paths
#: built it: the runner's live emission, the route's attach-time replay,
#: and the redriver's publish for a job whose worker died.
#:
#: Written out rather than read off `terminal_event_data`, for the same
#: reason `PINNED_EVENT_NAMES` above is written out: a pin that derives
#: itself from its subject pins nothing. Adding a field to a terminal
#: frame is a contract change and should cost one deliberate line here.
#:
#: WO-A10 got the two `job_completed` frames onto one builder and left
#: the rest; WO-B3 finished it. Before that, `run_job` hand-built eight
#: more payloads (four keys for most failures, eight for a session cost
#: cap, three for a reviewer cancellation, two for a shutdown) and
#: `redriver.py` kept a ninth, eight-key copy. Nine hand-written
#: payloads beside the builder, in six distinct shapes, for three event
#: names — and the symptom was a client reading a key off whichever one
#: it happened to receive.
TERMINAL_FRAME_KEYS = frozenset(
    {
        "job_id",
        "status",
        "elapsed_sec",
        "error",
        "error_type",
        "cost_cap_status",
        "cost_cap_message",
        "iterations",
        "quality_score",
        "cost_usd",
        "llm_calls",
        "reason",
    }
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
    # EMPTY, and the assertions below are what keeps it honest rather than
    # decorative. `turn_ready` was the only entry; WO-W13 declared it in
    # `web/lib/api/events.ts` and decided all 11 x 26 cells of the machine's
    # transition table for it, so the debt is paid and the name is covered by
    # the ordinary cross-side tie again.
}

#: `JobStatus` members the web tier does not render yet, same ledger shape.
#: `JobDetail.status` is a bare `str` in the OpenAPI document, so the
#: frontend's vocabulary is hand-written too and nothing generated it.
WEB_UNRENDERED_JOB_STATUSES: dict[str, str] = {
    # EMPTY, for the same reason. WO-W13 added `awaiting_learner` to the
    # `JobStatus` union in `web/lib/api/models.ts` and gave it a phase, a
    # surface and copy, so the status is rendered rather than merely parsed.
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


def _terminal_payload_calls(source: str) -> list[ast.expr]:
    """The payload argument of every `_put_terminal_event` call.

    An AST walk rather than a regex, because the thing being asserted
    is *what kind of expression* the third argument is — a call to the
    shared builder, or a dict literal somebody wrote out again — and a
    regex cannot tell those apart across the line breaks black inserts.
    """
    tree = ast.parse(source)
    payloads: list[ast.expr] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_put_terminal_event"
        ):
            assert len(node.args) == 3, ast.dump(node)
            payloads.append(node.args[2])
    return payloads


def test_every_terminal_frame_the_runner_emits_comes_from_one_builder() -> None:
    """The structural half of the convergence, and the load-bearing one.

    Pinning the key set (below) catches a builder that changed shape. It
    cannot catch the failure that actually happened twice in this
    repository: somebody adding a terminal path and writing the payload
    out by hand next to it, which is how there came to be nine shapes
    for three event names. That is a property of the *expression* at
    each emit site, so it is asserted as one.

    A new terminal path fails here until it routes through
    `terminal_event_data`. If a future path genuinely cannot — it has a
    field no job row carries, say — the answer is to widen the builder
    (`reason` is the precedent) rather than to add a tenth shape.
    """
    payloads = _terminal_payload_calls(RUNNER_SRC)
    # Guard against a walk that quietly matches nothing.
    assert len(payloads) == 10, len(payloads)
    for payload in payloads:
        assert isinstance(payload, ast.Call), ast.dump(payload)
        assert isinstance(payload.func, ast.Name), ast.dump(payload)
        assert payload.func.id == "terminal_event_data", ast.dump(payload)


def test_the_terminal_payload_has_exactly_one_shape() -> None:
    """The three producers, asserted against one literal.

    `terminal_event_data` is the runner's live frame and — through a
    one-line delegate each — the route's replay and the redriver's
    publish. Reading all three back proves the delegates are still
    delegates rather than copies that drifted, which is precisely what
    `redriver.py`'s did: its docstring claimed a field-for-field sync
    with a function that had already become a forwarder, while the copy
    itself was three fields short.
    """
    job = _job(JobStatus.failed)

    assert set(terminal_event_data(job)) == TERMINAL_FRAME_KEYS
    assert set(redriver_module._terminal_event_data(job)) == TERMINAL_FRAME_KEYS
    # The route's replay, through the same private delegate the stream
    # endpoint calls.
    from src.api.routes import _terminal_event_data as replay_data

    assert set(replay_data(job)) == TERMINAL_FRAME_KEYS

    # `reason` is the one key a replay can never fill: no column on the
    # job row carries it. A nullable key a client can read
    # unconditionally is the whole point of the union.
    assert terminal_event_data(job)["reason"] is None
    assert terminal_event_data(job, reason="shutdown")["reason"] == "shutdown"


def test_the_redriver_no_longer_keeps_its_own_copy() -> None:
    """The claim the old docstring made, now enforced instead of asserted.

    `src/api/runner.py` imports `WORKER_ID` from `redriver`, so the
    import back has to be deferred into the function body — which is
    exactly the kind of detail that decays into a re-copied dict the
    next time somebody tidies the imports. Reading the source keeps the
    delegation honest without depending on the two dicts happening to
    match.
    """
    assert "from src.api.runner import terminal_event_data" in REDRIVER_SRC
    # And no second literal: the reclaim path publishes the delegate's
    # result, never a dict it built itself.
    assert '"quality_score": job.quality_score' not in REDRIVER_SRC


def test_attach_replay_reuses_the_runner_terminal_names() -> None:
    """One name, one payload shape, and never a name of its own.

    `routes.py` replays a terminal outcome under the same event name the
    runner would have used. A separate replay-only name would be a
    fourth event the client would have to learn, so this pins that it
    stays three.

    The docstring here used to say the replay carried "`status` added
    and `llm_calls` dropped" — true when it was written, and the exact
    drift WO-A10 removed. Both frames are `terminal_event_data` now;
    `test_the_terminal_payload_has_exactly_one_shape` is where that is
    asserted.
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


def test_the_web_client_declares_every_job_status_or_declares_the_gap() -> None:
    """The drift check `JobStatus` never had, added because 0057 widened it.

    `JobDetail.status` is a bare `str` in the OpenAPI document, so
    nothing generates the frontend's view of the vocabulary either —
    `web/lib/api/models.ts` narrows it by hand, exactly as it does the
    event names, and until now nothing compared the two. That gap is
    how `awaiting_learner` could reach a browser as a status the client
    parses into a Zod enum that rejects it and a copy table that
    answers `undefined`, with every build still green.

    Same ledger shape as the events above, and the same two-sided
    assertion: an entry has to name a status the backend really has,
    and has to disappear the moment the web tier picks it up.
    """
    block = re.search(
        r"export type JobStatus =(.*?);", MODELS_TS, re.DOTALL
    )
    assert block is not None, "JobStatus union not found in models.ts"
    declared = set(re.findall(r'"([a-z_]+)"', block.group(1)))

    backend = {status.value for status in JobStatus}
    for status, owner in WEB_UNRENDERED_JOB_STATUSES.items():
        assert status in backend, f"{status} is listed as unrendered but is not a JobStatus"
        assert status not in declared, (
            f"{status} is declared in models.ts; drop it from "
            "WEB_UNRENDERED_JOB_STATUSES so the drift check covers it again"
        )
        assert owner, f"{status} has no owning work order"

    assert declared == backend - set(WEB_UNRENDERED_JOB_STATUSES)


def test_the_web_client_keeps_stream_timeout_out_of_the_terminal_set() -> None:
    block = re.search(
        r"export const TERMINAL_EVENTS.*?\[(.*?)\]", EVENTS_TS, re.DOTALL
    )
    assert block is not None

    declared = set(re.findall(r'"([a-z_]+)"', block.group(1)))
    assert declared == set(TERMINAL_EVENT_NAMES)
    assert STREAM_TIMEOUT_EVENT not in declared
