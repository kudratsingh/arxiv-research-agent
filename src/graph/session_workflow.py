"""Compiled LangGraph for one guided-read session (Phase W, WO-W03).

This is a second graph, not tutoring nodes grafted onto the research DAG. It
reuses the same checkpointer selection and the same wrapper semantics, so
sync/eval callers and the async API get the same durability, cancellation,
tracing, and bounded executor behavior as research jobs. The wrapper callable
itself is session-typed because LangGraph projects node input from annotations
(ADR 0059).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Executor
from contextlib import AsyncExitStack, ExitStack
from contextvars import copy_context
from typing import Any

from langgraph.graph import END, StateGraph

from src.agents.tutor import (
    assess_agent,
    check_in_agent,
    learner_input_agent,
    passage_agent,
    progress_update_agent,
    route_after_turn,
    tutor_agent,
)
from src.cancellation import CancelToken, current_cancel_token
from src.graph.session_state import SessionState
from src.graph.workflow import (
    _aopen_checkpointer,
    _open_checkpointer,
)
from src.observability import traced_node

SessionNodeFn = Callable[[SessionState], dict[str, Any]]
SessionNodeWrapper = Callable[[str, SessionNodeFn], Any]


def _run_session_node_body(
    name: str,
    fn: SessionNodeFn,
    state: SessionState,
    token: CancelToken | None,
) -> dict[str, Any]:
    if token is None:
        return fn(state)
    handle = token.enter_node(name)
    try:
        token.raise_if_cancelled()
        return fn(state)
    finally:
        token.exit_node(handle)


def _session_traced_wrapper(name: str, fn: SessionNodeFn) -> Any:
    traced = traced_node(name, fn)

    def node(state: SessionState) -> dict[str, Any]:
        return traced(state)

    return node


def _session_executor_wrapper(executor: Executor | None) -> SessionNodeWrapper:
    """Async wrapper whose input annotation preserves SessionState.

    LangGraph inspects a node callable's state annotation and projects the
    input to that schema. Reusing the research wrapper through a type cast
    therefore discarded session-only fields at runtime; a cast cannot alter
    the annotation LangGraph sees.
    """

    def wrap(name: str, fn: SessionNodeFn) -> Any:
        traced = traced_node(name, fn)

        async def node(state: SessionState) -> dict[str, Any]:
            token = current_cancel_token()
            if token is not None:
                token.raise_if_cancelled()
            loop = asyncio.get_running_loop()
            ctx = copy_context()
            return await loop.run_in_executor(
                executor,
                ctx.run,
                _run_session_node_body,
                name,
                traced,
                state,
                token,
            )

        node.__name__ = name
        return node

    return wrap


def _shape(wrap: SessionNodeWrapper) -> StateGraph[SessionState, Any, Any, Any]:
    graph = StateGraph(SessionState)
    graph.add_node("check_in", wrap("check_in", check_in_agent))
    graph.add_node("passage", wrap("passage", passage_agent))
    # Each bounded learner turn has its own checkpoint node. LangGraph keys a
    # dynamic interrupt to its node/task identity; distinct nodes therefore
    # make every replay and Command(resume=...) unambiguous across a process
    # restart instead of reusing a prior turn's resume value.
    for number in range(1, 5):
        name = f"learner_input_{number}"
        graph.add_node(name, wrap(name, learner_input_agent))
    for number in range(1, 4):
        name = f"tutor_{number}"
        graph.add_node(name, wrap(name, tutor_agent))
    graph.add_node("assess", wrap("assess", assess_agent))
    graph.add_node("progress_update", wrap("progress_update", progress_update_agent))

    graph.set_entry_point("check_in")
    graph.add_edge("check_in", "passage")
    graph.add_edge("passage", "learner_input_1")
    for number in range(1, 4):
        graph.add_conditional_edges(
            f"learner_input_{number}",
            route_after_turn,
            {
                "tutor": f"tutor_{number}",
                "assess": "assess",
                "progress_update": "progress_update",
            },
        )
        graph.add_edge(f"tutor_{number}", f"learner_input_{number + 1}")
    graph.add_conditional_edges(
        "learner_input_4",
        route_after_turn,
        {
            # Defensive only: tutor_3 marks the explain-back for assessment.
            "tutor": "assess",
            "assess": "assess",
            "progress_update": "progress_update",
        },
    )
    graph.add_edge("assess", "progress_update")
    graph.add_edge("progress_update", END)
    return graph


def _compile(graph: StateGraph[SessionState, Any, Any, Any], checkpointer: Any | None) -> Any:
    kwargs: dict[str, Any] = {}
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
        # learner_input uses LangGraph's dynamic interrupt primitive. This
        # avoids update_state being mistaken for a repeated completion of the
        # preceding tutor node.
    return graph.compile(**kwargs)


async def _abuild_session_workflow(node_executor: Executor | None) -> Any:
    stack = AsyncExitStack()
    try:
        checkpointer = await _aopen_checkpointer(stack)
    except BaseException:
        await stack.aclose()
        raise
    compiled = _compile(_shape(_session_executor_wrapper(node_executor)), checkpointer)
    compiled._checkpointer_aexit_stack = stack
    return compiled


def build_session_workflow(
    *,
    async_checkpointer: bool = False,
    node_executor: Executor | None = None,
) -> Any:
    """Build the guided-read graph on the configured checkpointer backend."""
    if async_checkpointer:
        return _abuild_session_workflow(node_executor)
    if node_executor is not None:
        raise ValueError(
            "node_executor applies to the async build only; pass async_checkpointer=True"
        )
    stack = ExitStack()
    checkpointer = _open_checkpointer(stack)
    compiled = _compile(_shape(_session_traced_wrapper), checkpointer)
    compiled._checkpointer_exit_stack = stack
    return compiled
