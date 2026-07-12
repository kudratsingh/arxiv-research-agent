"""Verify the planner injects `prior_context` into its user prompt (ADR 0032)."""

from __future__ import annotations

from typing import Any

import pytest

from src.agents.planner import _build_user_prompt, planner_agent


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "query": "hallucination reduction",
        "critique": "",
        "iteration": 0,
        "prior_context": "",
    }
    base.update(overrides)
    return base


class TestBuildUserPrompt:
    def test_no_prior_context_omits_the_section(self) -> None:
        prompt = _build_user_prompt(_state())  # type: ignore[arg-type]
        assert "Research question: hallucination reduction" in prompt
        assert "Context from prior queries" not in prompt

    def test_prior_context_appears_before_critique(self) -> None:
        ctx = "## Prior findings\n[query 1: earlier] chunk text"
        prompt = _build_user_prompt(
            _state(prior_context=ctx, critique="tighten the plan")  # type: ignore[arg-type]
        )
        assert "Context from prior queries" in prompt
        assert ctx in prompt
        assert "Previous critique" in prompt
        assert prompt.index(ctx) < prompt.index("Previous critique")

    def test_prior_context_and_iteration_hint_coexist(self) -> None:
        prompt = _build_user_prompt(
            _state(prior_context="ctx", iteration=2)  # type: ignore[arg-type]
        )
        assert "ctx" in prompt
        assert "revision iteration 2" in prompt


class TestPlannerAgentCallsLLM:
    """End-to-end contract: `planner_agent` builds a prompt that
    includes prior_context when set, then calls `call_llm_json`."""

    def test_planner_passes_prior_context_via_user_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_call(
            prompt: str, system_prompt: str = "", **_kwargs: Any
        ) -> dict[str, Any]:
            captured["prompt"] = prompt
            captured["system_prompt"] = system_prompt
            return {"sub_questions": ["q1", "q2"], "search_queries": ["s1"]}

        monkeypatch.setattr("src.agents.planner.call_llm_json", fake_call)

        state = _state(
            query="hallucination follow-up",
            prior_context="## Prior findings\n[query 1: earlier work] snippet",
        )
        result = planner_agent(state)  # type: ignore[arg-type]

        assert result["sub_questions"] == ["q1", "q2"]
        assert result["search_queries"] == ["s1"]
        assert "hallucination follow-up" in captured["prompt"]
        assert "## Prior findings" in captured["prompt"]
        # System prompt is unchanged — the context lives in the user
        # message, not the system prompt (ADR 0032).
        assert "Prior findings" not in captured["system_prompt"]
