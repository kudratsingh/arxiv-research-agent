"""LangGraph workflow: wires agents together with conditional routing."""

from langgraph.graph import END, StateGraph

from src.agents.critic import critic_agent
from src.agents.planner import planner_agent
from src.agents.reader import reader_agent
from src.agents.search import search_agent
from src.agents.synthesizer import synthesizer_agent
from src.graph.state import ResearchState


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


def build_workflow() -> StateGraph:
    """Construct and compile the research agent workflow graph."""
    workflow = StateGraph(ResearchState)

    workflow.add_node("planner", planner_agent)
    workflow.add_node("search", search_agent)
    workflow.add_node("reader", reader_agent)
    workflow.add_node("synthesizer", synthesizer_agent)
    workflow.add_node("critic", critic_agent)

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

    return workflow.compile()
