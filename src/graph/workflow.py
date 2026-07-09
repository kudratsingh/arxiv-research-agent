"""LangGraph workflow: wires agents together with conditional routing.

Two workflow shapes are supported, chosen by `settings.enable_supervisor`:

- **Fixed pipeline (default)**: planner -> search -> reader ->
  synthesizer -> critic, with one conditional route from the critic
  back to planner / search / synthesizer or to END.
- **Supervisor loop**: START -> supervisor -> chosen node -> supervisor
  -> ... -> stop. The supervisor picks the next action every turn
  from a strict enum; unknown / bad actions fall back to the
  fixed-pipeline order. See ADR 0014.

Two production knobs configured here regardless of shape:

- **Checkpointing** via `SqliteSaver` (ADR 0013 piece #2). Persists
  per-node state to `settings.checkpoint_db_path` so an interrupted
  run can be resumed by re-invoking with the same `thread_id`.
- **Tracing** via `traced_node` (ADR 0012 follow-up). When
  `settings.enable_tracing` is on, every agent execution becomes an
  OpenTelemetry span with `run_id` / query / iteration attributes.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from src.agents.critic import critic_agent
from src.agents.planner import planner_agent
from src.agents.query_refiner import query_refiner_agent
from src.agents.reader import reader_agent
from src.agents.search import search_agent
from src.agents.supervisor import route_after_supervisor, supervisor_agent
from src.agents.synthesizer import synthesizer_agent
from src.agents.verifier import verifier_agent
from src.config import settings
from src.graph.state import ResearchState
from src.observability import traced_node


def route_after_critique(state: ResearchState) -> str:
    """Conditional edge: route based on critic's revision decision.

    Returns the node name to route to, or END to finish.
    """
    if not state.get("revision_needed", False):
        return END

    target = state.get("revision_target", "")
    if target in ("planner", "search", "synthesizer"):
        return target

    return END


def _open_checkpointer(exit_stack: ExitStack) -> Any | None:
    """Open a SqliteSaver and register its teardown on `exit_stack`.

    Returns `None` when checkpointing is disabled via settings so
    `workflow.compile()` gets a plain compile call.
    """
    if not settings.enable_checkpointing:
        return None

    # Import kept local so the checkpoint-sqlite dep is optional at
    # import time — if a user removes it, only compilation fails.
    from langgraph.checkpoint.sqlite import SqliteSaver

    db_path = Path(settings.checkpoint_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cm = SqliteSaver.from_conn_string(str(db_path))
    return exit_stack.enter_context(cm)


def _build_fixed_pipeline(workflow: StateGraph) -> None:
    """Wire the classic planner -> search -> reader -> synthesizer -> critic path."""
    workflow.add_node("planner", traced_node("planner", planner_agent))
    workflow.add_node("search", traced_node("search", search_agent))
    workflow.add_node("reader", traced_node("reader", reader_agent))
    workflow.add_node("synthesizer", traced_node("synthesizer", synthesizer_agent))
    workflow.add_node("critic", traced_node("critic", critic_agent))

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "search")
    workflow.add_edge("search", "reader")
    workflow.add_edge("reader", "synthesizer")
    workflow.add_edge("synthesizer", "critic")

    workflow.add_conditional_edges(
        "critic",
        route_after_critique,
        {
            "planner": "planner",
            "search": "search",
            "synthesizer": "synthesizer",
            END: END,
        },
    )


def _build_supervisor_loop(workflow: StateGraph) -> None:
    """Wire the supervisor -> action -> supervisor loop.

    Every agent node hands control back to the supervisor when it
    finishes; the supervisor's conditional edge picks the next node
    or terminates.

    Optional nodes are only added when their flags are on:
      - `verifier` — `settings.enable_verifier`
      - `query_refiner` — `settings.enable_query_refiner`

    When a flag is off, the supervisor's action enum excludes the
    corresponding action (see `_available_actions` in the supervisor
    module), so those branches of the conditional edge are
    unreachable.
    """
    workflow.add_node("supervisor", traced_node("supervisor", supervisor_agent))
    workflow.add_node("planner", traced_node("planner", planner_agent))
    workflow.add_node("search", traced_node("search", search_agent))
    workflow.add_node("reader", traced_node("reader", reader_agent))
    workflow.add_node("synthesizer", traced_node("synthesizer", synthesizer_agent))
    workflow.add_node("critic", traced_node("critic", critic_agent))

    action_nodes = ["planner", "search", "reader", "synthesizer", "critic"]
    route_map: dict[str, str] = {n: n for n in action_nodes}

    if settings.enable_verifier:
        workflow.add_node("verifier", traced_node("verifier", verifier_agent))
        action_nodes.append("verifier")
        route_map["verifier"] = "verifier"

    if settings.enable_query_refiner:
        workflow.add_node(
            "query_refiner",
            traced_node("query_refiner", query_refiner_agent),
        )
        action_nodes.append("query_refiner")
        route_map["query_refiner"] = "query_refiner"

    workflow.set_entry_point("supervisor")

    workflow.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {**route_map, END: END},
    )

    for node in action_nodes:
        workflow.add_edge(node, "supervisor")


def build_workflow() -> Any:
    """Construct and compile the research agent workflow graph.

    Shape depends on `settings.enable_supervisor`:
    - Off (default) — fixed pipeline with a single conditional edge on
      the critic.
    - On — supervisor loop; every agent hands control back to the
      supervisor, which picks the next action or stops.

    When `settings.enable_checkpointing` is on, the compiled graph
    persists state after each node so a run can be resumed by
    invoking with `config={"configurable": {"thread_id": <run_id>}}`.

    When `settings.enable_tracing` is on, every agent execution is
    wrapped in an OpenTelemetry span.
    """
    workflow = StateGraph(ResearchState)

    if settings.enable_supervisor:
        _build_supervisor_loop(workflow)
    else:
        _build_fixed_pipeline(workflow)

    # ExitStack keeps the SqliteSaver context alive for the compiled
    # graph's lifetime. We attach it to the compiled object so callers
    # don't have to think about teardown.
    exit_stack = ExitStack()
    checkpointer = _open_checkpointer(exit_stack)
    if checkpointer is not None:
        compiled = workflow.compile(checkpointer=checkpointer)
    else:
        compiled = workflow.compile()

    # Attach so a caller who cares can `close()`; ExitStack cleanup
    # otherwise runs at interpreter shutdown.
    compiled._checkpointer_exit_stack = exit_stack  # type: ignore[attr-defined]
    return compiled
