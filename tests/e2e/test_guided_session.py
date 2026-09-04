"""A guided-read session, driven through its pauses to its close.

WO-A15 deliverable 2. The session graph is the one place in this
repository where the interesting behaviour *is* the pause: four bounded
turns, each one a durable LangGraph interrupt that the learner resumes.
A test that never stops at one is not testing the session.

This drives the compiled graph directly, the way
`src/eval/simulate_learner.py::drive_session` does — the same
`app.stream(...)` / `get_state(config)` / `Command(resume=...)` loop, on
the same mock path, because that seam is the repository's existing
proof that a whole session runs for nothing. What is deliberately *not*
reused is the learning benchmark's scenarios: `tests/fixtures/e2e/`
carries its own script so a re-tuned scenario cannot turn a wiring
regression into a green run, or a green run into a red one.

`tests/test_guided_session_graph.py` already drives a session over
HTTP and asserts the four turn kinds and `cost_usd == 0.0` on the job
row. This file is the layer under it: the node sequence itself, the
pause identity, and the durability of the interrupt across a rebuilt
graph — none of which the HTTP view can see.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from langgraph.types import Command

from src.graph.session_state import initial_session_state
from src.graph.session_workflow import build_session_workflow
from src.observability.costs import RunCosts

pytestmark = pytest.mark.e2e

#: The shape `_shape()` wires for a session the learner sees through:
#: check-in, the passage, then three tutor turns each bracketed by its
#: own learner-input node, then the assessment and the progress write.
#: Spelled out rather than derived, for the reason the research tier's
#: FIXED_PIPELINE is: a trajectory read off the graph agrees with any
#: rewiring, including a wrong one.
GUIDED_READ_TRAJECTORY = (
    "check_in",
    "passage",
    "learner_input_1",
    "tutor_1",
    "learner_input_2",
    "tutor_2",
    "learner_input_3",
    "tutor_3",
    "learner_input_4",
    "assess",
    "progress_update",
)

#: LangGraph's sentinel chunk key for a dynamic interrupt.
INTERRUPT_KEY = "__interrupt__"

#: The graph offers four learner turns plus at most one probe. Anything
#: past that is a routing bug, and a loop that never terminates would be
#: a bill in the funded tier — `simulate_learner` bounds itself for the
#: same reason.
MAX_PAUSES = 8


class _SessionDrive:
    """What one full drive of the session graph recorded."""

    def __init__(self) -> None:
        self.visited: list[str] = []
        self.pauses: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {}


def _drive_session(
    app: Any, config: dict[str, Any], first_input: Any, replies: Sequence[str]
) -> _SessionDrive:
    """Run a session to its close, answering each pause in turn.

    The loop is `simulate_learner`'s, kept deliberately close to it: run
    until the graph stops, ask the checkpoint whether a node is pending,
    and if one is, hand back exactly one learner reply. The script is
    consumed in order; once it runs out the learner ends the session,
    which is the honest way to stop rather than padding with filler that
    the assessment would then read.
    """
    drive = _SessionDrive()
    stream_input: Any = first_input
    while True:
        for chunk in app.stream(stream_input, config=config):
            for node in chunk:
                if node != INTERRUPT_KEY:
                    drive.visited.append(node)
        snapshot = app.get_state(config)
        if not getattr(snapshot, "next", ()):
            drive.state = dict(snapshot.values)
            return drive

        index = len(drive.pauses)
        drive.pauses.append(dict(snapshot.values.get("turn") or {}))
        assert index < MAX_PAUSES, "session graph paused more times than it can offer"
        exhausted = index >= len(replies)
        stream_input = Command(
            resume={
                "learner_reply": "" if exhausted else replies[index],
                "end_requested": exhausted,
            }
        )


@pytest.fixture
def session_settings(
    install_settings: Callable[..., Any], tmp_path: Path
) -> Callable[..., Any]:
    """Session settings, with the checkpointer the interrupt requires.

    `_compile` only attaches an interrupt when a checkpointer exists, so
    a session run with checkpointing off would not pause at all — it
    would run straight through with an empty learner reply and still
    look like a session. `Settings` refuses that combination outright
    (`enable_session_loop requires enable_checkpointing=true`); pinning
    it here makes the dependency visible at the test rather than only in
    the validator.
    """

    def _install(**overrides: Any) -> Any:
        return install_settings(
            enable_session_loop=True,
            enable_checkpointing=True,
            checkpoint_backend="sqlite",
            checkpoint_db_path=str(tmp_path / "e2e-sessions.sqlite"),
            **overrides,
        )

    return _install


class TestGuidedReadSession:
    def test_a_session_pauses_for_every_turn_and_closes_on_recorded_evidence(
        self,
        session_settings: Callable[..., Any],
        e2e_fixtures: Callable[[str], dict[str, Any]],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """Four pauses, the documented node sequence, and a free close.

        Two things make this more than "the session finished". First the
        node sequence: a graph that skipped `assess` would still produce
        a close summary, and a graph that skipped `progress_update`
        would produce one with nothing written behind it. Second the
        pause identity — the four turns must arrive as
        reflection, guided question, guided question, explain-back, in
        that order, because the explain-back is the one the assessment
        reads and a session that asks for it early assesses a warm-up.
        """
        fixture = e2e_fixtures("guided_session")
        session_settings()

        config = {"configurable": {"thread_id": "e2e-session-1"}}
        app = build_session_workflow()
        try:
            drive = _drive_session(
                app,
                config,
                initial_session_state(
                    fixture["input_payload"], "e2e-session-1", "Guided read"
                ),
                fixture["learner_replies"],
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert drive.visited == list(GUIDED_READ_TRAJECTORY)

        # One pause per learner turn, and every one of them consumed a
        # scripted reply — no filler, so nothing the assessment reads
        # was authored by the harness.
        assert len(drive.pauses) == len(fixture["learner_replies"]) == 4
        assert [pause["kind"] for pause in drive.pauses] == [
            "reflection",
            "guided_question",
            "guided_question",
            "explain_back",
        ]
        assert [pause["turn_number"] for pause in drive.pauses] == [1, 2, 3, 4]
        # Every pause must carry the prompt it is waiting on. A pause
        # with an empty prompt is a turn the learner cannot answer.
        assert all(pause["prompt"].strip() for pause in drive.pauses)

        # The plan the check-in wrote is honest about the time declared:
        # 25 minutes buys more than one section (`src/agents/tutor.py`
        # caps at 1 under 10 minutes, 2 under 20, 3 above).
        plan = drive.state["session_plan"]
        assert plan["sections"], "a session must plan at least one section"
        assert len(plan["sections"]) <= 3

        # ADR 0060: the shipped assessment judge records rather than
        # grades. A session that invented an outcome here would be the
        # defect, so the assertion is on the honest status, not on a
        # score.
        assert drive.state["assessment"]["status"] == "recorded_ungraded"
        assert drive.state["assessment"]["evidence_quote"].strip()

        # Every progress event must be traceable to the evidence that
        # produced it (Phase W's evidence-linked progress property).
        events = drive.state["progress_events"]
        assert [event["kind"] for event in events] == [
            "assessment",
            "session_completed",
        ]
        assert all(event["evidence_ref"].strip() for event in events)

        assert drive.state["draft_report"].strip(), "the close summary is shown verbatim"

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    def test_a_paused_session_survives_the_process_that_was_serving_it(
        self,
        session_settings: Callable[..., Any],
        e2e_fixtures: Callable[[str], dict[str, Any]],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """The pause is durable: a second graph resumes the same turn.

        This is the property `awaiting_learner` rests on. A session job
        parks for as long as `session_turn_timeout_sec` allows, and the
        learner may come back to a worker that never ran the first half
        of the session. If the interrupt lived only in the first graph's
        memory, the learner's reply would either be dropped or would
        restart the session — and a restarted guided read re-asks
        questions the learner has already answered.
        """
        fixture = e2e_fixtures("guided_session")
        session_settings()
        config = {"configurable": {"thread_id": "e2e-session-resume"}}

        first = build_session_workflow()
        try:
            for _ in first.stream(
                initial_session_state(
                    fixture["input_payload"], "e2e-session-resume", "Guided read"
                ),
                config=config,
            ):
                pass
            parked = first.get_state(config)
        finally:
            first._checkpointer_exit_stack.close()

        assert getattr(parked, "next", ()), "the graph must park on the first turn"
        assert parked.values["turn"]["kind"] == "reflection"

        # A different compiled graph over the same database — the
        # closest a test gets to the worker having been replaced.
        resumed = build_session_workflow()
        try:
            reattached = resumed.get_state(config)
            assert reattached.next == parked.next
            assert reattached.values["turn"] == parked.values["turn"]

            drive = _drive_session(
                resumed,
                config,
                Command(
                    resume={
                        "learner_reply": fixture["learner_replies"][0],
                        "end_requested": False,
                    }
                ),
                fixture["learner_replies"][1:],
            )
        finally:
            resumed._checkpointer_exit_stack.close()

        # The resumed half completes the session without re-running the
        # half the first graph already did.
        assert drive.visited == list(GUIDED_READ_TRAJECTORY)[2:]
        assert [pause["kind"] for pause in drive.pauses] == [
            "guided_question",
            "guided_question",
            "explain_back",
        ]
        assert drive.state["assessment"]["status"] == "recorded_ungraded"

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    def test_a_learner_who_leaves_early_still_gets_an_honest_close(
        self,
        session_settings: Callable[..., Any],
        e2e_fixtures: Callable[[str], dict[str, Any]],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """Ending after one turn routes to the close, not to an assessment.

        Abandonment is the ordinary case for a daily habit, not an edge
        case, and the graph's answer to it is a real branch:
        `route_after_turn` sends an `end_requested` turn straight to
        `progress_update`. What must not happen is an assessment: there
        is no explain-back to read, so grading one would be inventing an
        outcome — the exact dishonesty ADR 0060 exists to prevent.
        """
        fixture = e2e_fixtures("guided_session")
        session_settings()
        config = {"configurable": {"thread_id": "e2e-session-early-exit"}}

        app = build_session_workflow()
        try:
            drive = _drive_session(
                app,
                config,
                initial_session_state(
                    fixture["input_payload"], "e2e-session-early-exit", "Guided read"
                ),
                # An empty script: the learner's first act is to leave.
                replies=(),
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert drive.visited == [
            "check_in",
            "passage",
            "learner_input_1",
            "progress_update",
        ]
        assert len(drive.pauses) == 1
        assert "assess" not in drive.visited
        assert drive.state["assessment"].get("status") != "assessed"

        # The session still closes, and still writes its record: leaving
        # early is not an error path.
        assert drive.state["draft_report"].strip()
        assert [event["kind"] for event in drive.state["progress_events"]] == [
            "session_completed"
        ]

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0
