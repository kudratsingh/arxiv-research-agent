"""LangGraph workflow: wires agents together with conditional routing.

Two production knobs configured here:

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
from src.agents.reader import reader_agent
from src.agents.search import search_agent
from src.agents.synthesizer import synthesizer_agent
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


def build_workflow() -> Any:
    """Construct and compile the research agent workflow graph.

    When `settings.enable_checkpointing` is on, the compiled graph
    persists state after each node so a run can be resumed by
    invoking with `config={"configurable": {"thread_id": <run_id>}}`.

    When `settings.enable_tracing` is on, every agent execution is
    wrapped in an OpenTelemetry span (no-op wrapper otherwise so we
    don't pay tracer overhead when disabled).
    """
    workflow = StateGraph(ResearchState)

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
