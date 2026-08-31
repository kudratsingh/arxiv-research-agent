"""State contract for the Phase W guided-read session graph.

The constructor lives beside the ``TypedDict`` for the same reason the
research graph's constructor lives in ``src.graph.state`` (ADR 0052): every
entry point starts from one total, reviewable shape.  The API persists the
bounded ``input_payload`` on the job row; this module turns that payload into
graph state without reaching into request or store globals.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class SessionState(TypedDict):
    """Complete state carried by one guided-read session.

    ``tier1`` is the bounded learner/profile snapshot. ``session_spec`` is
    the selected paper plus its briefing-companion guidance. Learner-authored
    prose is kept in ``learner_reply`` and ``messages``; it never becomes a
    control field. ``turn`` is the opaque pause payload the shared API runner
    publishes as ``turn_ready``.
    """

    run_id: str
    query: str
    principal_key_id: str
    tier1: dict[str, Any]
    session_spec: dict[str, Any]
    session_plan: dict[str, Any]
    messages: Annotated[list[Any], add_messages]
    activity: dict[str, Any]
    assessment: dict[str, Any]
    turn: dict[str, Any]
    learner_reply: str
    end_requested: bool
    turn_number: int
    awaiting_assessment: bool
    progress_events: list[dict[str, Any]]
    draft_report: str
    quality_score: float | None
    iteration: int


def _mapping(value: Any) -> dict[str, Any]:
    """Copy a mapping into a plain dict; otherwise return an empty block."""
    return dict(value) if isinstance(value, Mapping) else {}


def initial_session_state(
    input_payload: Mapping[str, Any] | None,
    run_id: str,
    query: str,
) -> SessionState:
    """Build the total state for a fresh guided-read session.

    The route owns validation and content/profile lookup. This constructor is
    deliberately defensive anyway because a Redis row can outlive the worker
    that wrote it. A malformed old payload becomes empty bounded context and
    is handled honestly by the check-in node; it never manufactures a profile
    or a paper.
    """
    payload = _mapping(input_payload)
    principal = payload.get("principal_key_id")
    return {
        "run_id": run_id,
        "query": query,
        "principal_key_id": principal if isinstance(principal, str) else "",
        "tier1": _mapping(payload.get("tier1")),
        "session_spec": _mapping(payload.get("session_spec")),
        "session_plan": {},
        "messages": [],
        "activity": {},
        "assessment": {},
        "turn": {},
        "learner_reply": "",
        "end_requested": False,
        "turn_number": 0,
        "awaiting_assessment": False,
        "progress_events": [],
        "draft_report": "",
        "quality_score": None,
        "iteration": 0,
    }
