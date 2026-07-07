"""Unit tests for the supervisor agent.

Pure helpers (`_summarize_state`, `_default_next_action`, `_emit`,
`route_after_supervisor`) are tested directly. The full
`supervisor_agent` path is exercised with `call_llm_json` monkeypatched
so no real Claude calls happen. Also tests the budget/iteration
short-circuits that skip the LLM entirely.
"""

from typing import Any

import pytest
from langgraph.graph import END

from src.agents import supervisor as sup
from src.agents.supervisor import (
    ACTION_TO_NODE,
    VALID_ACTIONS,
    _default_next_action,
    _summarize_state,
    route_after_supervisor,
    supervisor_agent,
)
from src.config import Settings
from src.graph.state import ResearchState
from src.observability import costs as costs_module
from src.observability import logging as logging_module


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_observability_state() -> None:
    """Ensure `current_costs()` is clean between tests."""
    yield
    costs_module._current_costs.set(None)
    logging_module._run_id.set("-")


def _empty_state(**overrides: Any) -> ResearchState:
    """A ResearchState with all fields present so TypedDict access is safe."""
    base: dict[str, Any] = {
        "run_id": "test-run",
        "query": "q?",
        "sub_questions": [],
        "search_queries": [],
        "papers": [],
        "paper_analyses": [],
        "draft_report": "",
        "citations": [],
        "critique": "",
        "quality_score": 0.0,
        "revision_needed": False,
        "revision_target": "",
        "iteration": 0,
        "next_action": "",
        "loop_iterations": 0,
        "stop_reason": "",
        "messages": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# _default_next_action — mirrors the fixed pipeline
# ---------------------------------------------------------------------------


class TestDefaultNextAction:
    def test_empty_state_goes_to_plan(self) -> None:
        assert _default_next_action(_empty_state()) == "plan"

    def test_sub_questions_but_no_papers_goes_to_search(self) -> None:
        state = _empty_state(sub_questions=["a", "b"])
        assert _default_next_action(state) == "search"

    def test_papers_but_no_analyses_goes_to_read(self) -> None:
        state = _empty_state(
            sub_questions=["a"], papers=[{"id": "x", "title": "t"}]  # type: ignore[list-item]
        )
        assert _default_next_action(state) == "read"

    def test_analyses_but_no_report_goes_to_synthesize(self) -> None:
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x", "title": "t"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
        )
        assert _default_next_action(state) == "synthesize"

    def test_report_but_no_critique_goes_to_critique(self) -> None:
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x", "title": "t"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
            draft_report="body",
        )
        assert _default_next_action(state) == "critique"

    def test_finished_state_goes_to_stop(self) -> None:
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x", "title": "t"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
            draft_report="body",
            critique="ok",
        )
        assert _default_next_action(state) == "stop"

    def test_critic_revision_routes_to_planner_target(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(max_iterations=3))
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x", "title": "t"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
            draft_report="body",
            critique="rewrite",
            revision_needed=True,
            revision_target="planner",
            iteration=1,
        )
        assert _default_next_action(state) == "plan"

    def test_revision_ignored_when_iteration_cap_hit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(max_iterations=3))
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x", "title": "t"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
            draft_report="body",
            critique="rewrite",
            revision_needed=True,
            revision_target="planner",
            iteration=3,
        )
        # iteration hit the cap; fall through to natural next step ("stop"
        # since everything downstream is populated).
        assert _default_next_action(state) == "stop"


# ---------------------------------------------------------------------------
# _summarize_state — prompt input
# ---------------------------------------------------------------------------


class TestSummarizeState:
    def test_includes_counts_and_query(self) -> None:
        state = _empty_state(
            query="what is X?",
            sub_questions=["a", "b"],
            papers=[{"id": "1"}] * 3,  # type: ignore[list-item]
        )
        summary = _summarize_state(state)
        assert "query: what is X?" in summary
        assert "sub_questions: 2" in summary
        assert "papers: 3" in summary

    def test_no_cost_context_when_no_accumulator(self) -> None:
        assert "$?" in _summarize_state(_empty_state())

    def test_critique_snippet_truncated_to_200_chars(self) -> None:
        state = _empty_state(critique="x" * 500)
        summary = _summarize_state(state)
        # Two hundred x's, no more.
        assert "x" * 200 in summary
        assert "x" * 201 not in summary


# ---------------------------------------------------------------------------
# supervisor_agent — behavior including short-circuits
# ---------------------------------------------------------------------------


class TestSupervisorShortCircuits:
    def test_iteration_cap_stops_without_llm_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = {"n": 0}

        def _no(**_: Any) -> dict[str, Any]:
            called["n"] += 1
            return {}

        monkeypatch.setattr(sup, "call_llm_json", _no)
        monkeypatch.setattr(sup, "settings", Settings(max_loop_iterations=5))

        state = _empty_state(loop_iterations=5)
        result = supervisor_agent(state)

        assert called["n"] == 0
        assert result["next_action"] == "stop"
        assert result["stop_reason"] == "max_iterations_reached"
        assert result["loop_iterations"] == 6

    def test_cost_cap_stops_without_llm_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = {"n": 0}

        def _no(**_: Any) -> dict[str, Any]:
            called["n"] += 1
            return {}

        monkeypatch.setattr(sup, "call_llm_json", _no)
        monkeypatch.setattr(sup, "settings", Settings(max_cost_usd=1.0))

        # Simulate an accumulator that's over budget.
        from src.observability import start_cost_tracking

        costs = start_cost_tracking()
        costs.record("claude-sonnet-4-6", 400_000, 0, 1.5)  # 1.5 USD

        result = supervisor_agent(_empty_state())

        assert called["n"] == 0
        assert result["next_action"] == "stop"
        assert result["stop_reason"] == "budget_reached"


class TestSupervisorLLMPath:
    def _stub_llm(
        self, monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
    ) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        def fake(
            *, prompt: str, system_prompt: str, max_tokens: int
        ) -> dict[str, Any]:
            captured["prompt"] = prompt
            captured["system_prompt"] = system_prompt
            captured["max_tokens"] = max_tokens
            return response

        monkeypatch.setattr(sup, "call_llm_json", fake)
        return captured

    def test_valid_action_returned_verbatim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_llm(
            monkeypatch,
            {"next_action": "search", "reason": "need papers", "stop_reason": ""},
        )
        result = supervisor_agent(_empty_state(sub_questions=["a"]))
        assert result["next_action"] == "search"
        assert result["stop_reason"] == ""
        assert result["loop_iterations"] == 1

    def test_stop_action_records_supervisor_stop_default_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_llm(
            monkeypatch,
            {"next_action": "stop", "reason": "quality reached", "stop_reason": ""},
        )
        result = supervisor_agent(_empty_state(quality_score=0.9))
        assert result["next_action"] == "stop"
        assert result["stop_reason"] == "supervisor_stop"

    def test_stop_reason_ignored_when_not_stopping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_llm(
            monkeypatch,
            {"next_action": "read", "reason": "extract findings", "stop_reason": "budget_reached"},
        )
        result = supervisor_agent(_empty_state(papers=[{"id": "x"}]))  # type: ignore[list-item]
        # Judge included a stop_reason but chose a non-stop action — we drop it.
        assert result["stop_reason"] == ""

    def test_invalid_action_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_llm(
            monkeypatch,
            {"next_action": "hallucinate", "reason": "why not", "stop_reason": ""},
        )
        result = supervisor_agent(_empty_state())  # empty -> default is "plan"
        assert result["next_action"] == "plan"

    def test_missing_action_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_llm(monkeypatch, {"reason": "no action field"})
        assert (
            supervisor_agent(_empty_state())["next_action"] == "plan"
        )

    def test_llm_exception_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**_: Any) -> dict[str, Any]:
            raise RuntimeError("api down")

        monkeypatch.setattr(sup, "call_llm_json", _boom)
        result = supervisor_agent(_empty_state())
        assert result["next_action"] == "plan"

    def test_prompt_includes_state_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._stub_llm(
            monkeypatch,
            {"next_action": "search", "reason": "", "stop_reason": ""},
        )
        supervisor_agent(_empty_state(query="hallu?", sub_questions=["a"]))
        assert "query: hallu?" in captured["prompt"]
        assert "sub_questions: 1" in captured["prompt"]


# ---------------------------------------------------------------------------
# route_after_supervisor
# ---------------------------------------------------------------------------


class TestRouteAfterSupervisor:
    @pytest.mark.parametrize(
        "action,expected",
        [
            ("plan", "planner"),
            ("search", "search"),
            ("read", "reader"),
            ("synthesize", "synthesizer"),
            ("critique", "critic"),
        ],
    )
    def test_valid_actions_map_to_nodes(self, action: str, expected: str) -> None:
        state = _empty_state(next_action=action)
        assert route_after_supervisor(state) == expected

    def test_stop_returns_end(self) -> None:
        assert route_after_supervisor(_empty_state(next_action="stop")) == END

    def test_missing_action_returns_end(self) -> None:
        assert route_after_supervisor(_empty_state()) == END

    def test_unknown_action_returns_end(self) -> None:
        state = _empty_state(next_action="dance")
        assert route_after_supervisor(state) == END


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


class TestActionEnumInvariants:
    def test_action_to_node_covers_every_action_except_stop(self) -> None:
        assert set(ACTION_TO_NODE.keys()) == VALID_ACTIONS - {"stop"}

    def test_action_to_node_values_all_distinct(self) -> None:
        values = list(ACTION_TO_NODE.values())
        assert len(values) == len(set(values))
