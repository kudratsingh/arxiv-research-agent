"""The research workflow, start to report, asserted on its trajectory.

WO-A15 deliverable 1. Before this file the repository had no test that
drove the compiled research graph from a query to a finished report and
said which nodes ran: `tests/test_api_smoke_e2e.py` proves the *wiring*
holds (real graph, real checkpointer, real runner) and asserts the job
succeeded with one iteration, and every other test drives a node or two
in isolation.

The distinction this file is built around is that "the report is
non-empty" is not a trajectory assertion. A graph that skipped the
reader, or looped the synthesizer twice, or routed a revision to a node
the router cannot dispatch, still produces a non-empty report — the
critic's canned score would still land on the state and the run would
still be `succeeded`. So the assertions here are the node sequence, the
iteration count, the terminal state's citations, and the cost, and each
of them names a real defect it would catch.

Trajectory is read from two independent places on purpose:

  - the `stream` chunk keys, which are LangGraph's own record of which
    node produced which update, and
  - `messages[].name`, which is what each agent stamped on its own
    output before the reducer appended it.

They are built by different machinery and can disagree — a node that
returns an update without a message, or a message stamped with the
wrong name, splits them — so agreeing is a stronger statement than
either alone.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from src.graph.state import ResearchState, initial_research_state
from src.graph.workflow import build_workflow
from src.observability.costs import RunCosts

pytestmark = pytest.mark.e2e

#: The fixed pipeline's shape, in the order `_build_fixed_pipeline`
#: wires it. Spelled out rather than derived from the graph, because a
#: trajectory assertion that reads the graph to decide what to expect
#: agrees with any rewiring, including a wrong one.
FIXED_PIPELINE = ("planner", "search", "reader", "synthesizer", "critic")

#: LangGraph's sentinel chunk key for a dynamic interrupt. Not a node,
#: and the API runner skips it for the same reason.
INTERRUPT_KEY = "__interrupt__"


def _drive(
    app: Any, state: ResearchState, config: dict[str, Any] | None = None
) -> tuple[list[str], dict[str, Any]]:
    """Run the graph to completion, recording the node sequence.

    Returns the nodes in the order the graph reported them, and the
    final state. `stream` rather than `invoke` so the trajectory comes
    out of the run itself instead of being reconstructed afterwards,
    and both stream modes at once so the final state is the graph's own
    reduced view rather than this helper re-implementing `add_messages`
    by merging the updates by hand.
    """
    visited: list[str] = []
    final: dict[str, Any] = {}
    for mode, payload in app.stream(
        state, config=config, stream_mode=["updates", "values"]
    ):
        if mode == "values":
            final = dict(payload)
            continue
        for node in payload:
            # Not a node: LangGraph's sentinel key for a dynamic
            # interrupt. The API runner skips it for the same reason.
            if node != INTERRUPT_KEY:
                visited.append(node)
    return visited, final


def _message_trajectory(messages: Sequence[Any]) -> list[str]:
    """The node each message says produced it."""
    return [str(getattr(message, "name", "") or "") for message in messages]


class TestFullResearchWorkflow:
    def test_a_query_reaches_a_cited_report_through_every_node_in_order(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """One query, one pass: planner → search → reader → synthesizer → critic.

        The single assertion this test exists for is the node sequence.
        Everything below it is the evidence that the sequence was real
        work rather than five no-ops: the plan reached search, the
        papers reached the reader, the analyses reached the synthesizer,
        and the critic's verdict landed on the state.
        """
        install_settings(enable_checkpointing=False, enable_supervisor=False)
        research_llm_surface()

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("why do LLMs hallucinate?", "e2e-research-1")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == list(FIXED_PIPELINE)
        assert _message_trajectory(final["messages"]) == list(FIXED_PIPELINE)

        # The critic is the only node that touches `iteration`, so one
        # clean pass is exactly 1. A 2 here means the graph looped
        # without the router being asked to.
        assert final["iteration"] == 1

        # Each of these is the output of one node landing as the input
        # of the next. Together they are the difference between "the
        # nodes ran" and "the nodes ran and were connected".
        assert final["sub_questions"] and final["search_queries"]
        assert len(final["papers"]) == 5, "mock search serves five fixture papers"
        assert len(final["paper_analyses"]) == len(final["papers"])
        assert final["draft_report"].strip()
        assert final["quality_score"] == pytest.approx(0.88)
        assert final["revision_needed"] is False

        # Citations, not just a report. `_parse_citations` drops a
        # malformed entry silently, so an empty list here is the
        # signature of the synthesizer's parser rejecting its input —
        # a report that looks fine and cites nothing.
        assert final["citations"], "a finished report must carry its citations"
        for citation in final["citations"]:
            assert set(citation) >= {"paper_id", "title", "authors", "year", "url"}
            assert citation["title"].strip()

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    def test_a_critic_that_never_approves_stops_at_the_iteration_ceiling(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        e2e_fixtures: Callable[[str], dict[str, Any]],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """The revision loop is bounded, and it revises the node it named.

        The happy path above never exercises `route_after_critique`'s
        revision branch, so on its own it would pass against a graph
        whose critic → synthesizer edge was gone. Here the critic
        demands a synthesizer revision every time; the run must loop
        back to `synthesizer` (not to `planner`, and not to the top),
        and it must stop, because `max_iterations` is the only thing
        standing between a self-grading critic and an unbounded run.

        Asserted as a trajectory rather than as a final state for
        exactly that reason: `iteration == 2` is also what a graph that
        re-ran the whole pipeline would report.
        """
        responses = e2e_fixtures("research_llm_responses")
        settings = install_settings(
            enable_checkpointing=False, enable_supervisor=False, max_iterations=2
        )
        research_llm_surface(
            critic=[responses["critic_demands_synthesizer_revision"]]
        )

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("bounded loop", "e2e-research-loop")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == [
            "planner",
            "search",
            "reader",
            "synthesizer",
            "critic",
            # Two revisions, each back to the node the critic named —
            # not a re-plan, not a re-search, and not a rerun of the
            # whole pipeline. Then a third critic pass that the ceiling
            # forces to approve.
            "synthesizer",
            "critic",
            "synthesizer",
            "critic",
        ]

        # `max_iterations + 1`, and deliberately written that way rather
        # than as a bare 3. The critic compares *before* it increments
        # (`if iteration >= settings.max_iterations` then
        # `"iteration": iteration + 1`), so the run makes one more pass
        # than the ceiling names and the counter it reports overshoots
        # it by one. That is the shipped behaviour, and pinning it here
        # is the point: it is invisible to a unit test of the critic,
        # which never sees the loop it bounds.
        assert final["iteration"] == settings.max_iterations + 1

        # The ceiling ends the run by forcing an approval and clearing
        # the target, not by breaking the edge — so a passing run has a
        # deliverable report rather than a dangling revision request.
        assert final["revision_needed"] is False
        assert final["revision_target"] == ""
        assert final["draft_report"].strip()

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    def test_a_checkpointed_run_is_resumable_from_its_own_thread(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        tmp_path: Path,
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """The finished run's state survives in the checkpointer.

        Durability is the property the HITL pause and the redriver both
        rest on, and it is invisible to a run driven with checkpointing
        off. A second graph built against the same database and asked
        for the same thread must see the finished trajectory — if it
        sees an empty state, a resumed job restarts from the top and
        pays for the whole run again.
        """
        install_settings(
            enable_checkpointing=True,
            enable_supervisor=False,
            checkpoint_backend="sqlite",
            checkpoint_db_path=str(tmp_path / "e2e-research.sqlite"),
        )
        research_llm_surface()

        config = {"configurable": {"thread_id": "e2e-research-resume"}}
        app = build_workflow(enable_hitl=False)
        try:
            visited, _ = _drive(
                app,
                initial_research_state("durable run", "e2e-research-resume"),
                config,
            )
        finally:
            app._checkpointer_exit_stack.close()
        assert visited == list(FIXED_PIPELINE)

        reopened = build_workflow(enable_hitl=False)
        try:
            snapshot = reopened.get_state(config)
        finally:
            reopened._checkpointer_exit_stack.close()

        # No pending node: the checkpoint records a finished run, which
        # is what makes a reconnect idempotent rather than a re-run.
        assert not getattr(snapshot, "next", ())
        assert _message_trajectory(snapshot.values["messages"]) == list(FIXED_PIPELINE)
        assert snapshot.values["citations"]
        assert snapshot.values["iteration"] == 1

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0
