"""Unit tests for the query refiner agent.

Covers the pure prompt builder, the dedup logic, the fail-closed
policy (LLM errors and empty outputs keep current queries), and the
happy-path emission.
"""

from typing import Any

import pytest

from src.agents import query_refiner as refiner_module
from src.agents.query_refiner import (
    _build_user_prompt,
    _normalize,
    query_refiner_agent,
)
from src.config import Settings
from src.graph.state import ResearchState


def _empty_state(**overrides: Any) -> ResearchState:
    base: dict[str, Any] = {
        "run_id": "test-run",
        "query": "What is X?",
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
        "verified": False,
        "unsupported_claims": [],
        "missing_evidence": [],
        "verifier_recommendation": "",
        "evidence": [],
        "tried_search_queries": [],
        "messages": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def _stub_llm(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any] | Exception,
) -> dict[str, Any]:
    captured: dict[str, Any] = {"calls": 0}

    def fake(
        *,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        model_name: str | None = None,
        cache_system: bool = False,
    ) -> dict[str, Any]:
        captured["calls"] += 1
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        captured["max_tokens"] = max_tokens
        captured["model_name"] = model_name
        captured["cache_system"] = cache_system
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(refiner_module, "call_llm_json", fake)
    return captured


# ---------------------------------------------------------------------------
# Prompt shape
# ---------------------------------------------------------------------------


class TestBuildUserPrompt:
    def test_lists_tried_queries_and_current(self) -> None:
        state = _empty_state(
            query="RAG for hallucination?",
            sub_questions=["approaches", "benchmarks"],
            search_queries=["retrieval augmented generation"],
            tried_search_queries=["large language model hallucination"],
        )
        prompt = _build_user_prompt(state)
        assert "RAG for hallucination?" in prompt
        assert "  - approaches" in prompt
        assert "  - large language model hallucination" in prompt
        assert "  - retrieval augmented generation" in prompt

    def test_no_tried_shows_none_placeholder(self) -> None:
        prompt = _build_user_prompt(_empty_state())
        assert "Already-tried search queries:\n  (none)" in prompt

    def test_missing_evidence_reflected(self) -> None:
        state = _empty_state(
            missing_evidence=["convergence guarantees", "cost analysis"]
        )
        prompt = _build_user_prompt(state)
        assert "  - convergence guarantees" in prompt
        assert "  - cost analysis" in prompt

    def test_critique_included_when_present(self) -> None:
        state = _empty_state(critique="broaden to include benchmarks")
        prompt = _build_user_prompt(state)
        assert "Critic feedback (address these gaps):" in prompt
        assert "broaden to include benchmarks" in prompt

    def test_critique_omitted_when_absent(self) -> None:
        prompt = _build_user_prompt(_empty_state())
        assert "Critic feedback" not in prompt

    def test_papers_block_shows_titles(self) -> None:
        state = _empty_state(
            papers=[
                {"title": "Great RAG Paper", "abstract": "words " * 60},  # type: ignore[list-item]
                {"title": "Another Paper", "abstract": "short abstract"},  # type: ignore[list-item]
            ]
        )
        prompt = _build_user_prompt(state)
        assert "- Great RAG Paper" in prompt
        assert "- Another Paper" in prompt
        # First paper's abstract head should include the ellipsis marker.
        assert "..." in prompt


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


class TestNormalize:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("  RAG hallucination  ", "rag hallucination"),
            ("RAG Hallucination", "rag hallucination"),
            ("", ""),
        ],
    )
    def test_normalize_matches_case_and_whitespace(
        self, raw: str, expected: str
    ) -> None:
        assert _normalize(raw) == expected


# ---------------------------------------------------------------------------
# Fail-closed policy
# ---------------------------------------------------------------------------


class TestFailClosedPaths:
    def test_llm_exception_keeps_current(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(monkeypatch, RuntimeError("api down"))
        state = _empty_state(search_queries=["one", "two"])
        result = query_refiner_agent(state)
        # No search_queries or tried_search_queries in update -> unchanged.
        assert "search_queries" not in result
        assert "tried_search_queries" not in result
        assert result["messages"][0].name == "query_refiner"
        assert "kept current" in result["messages"][0].content

    def test_non_list_queries_field_keeps_current(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(monkeypatch, {"queries": "not a list"})
        result = query_refiner_agent(
            _empty_state(search_queries=["one"])
        )
        assert "search_queries" not in result

    def test_all_duplicates_keeps_current(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {"queries": ["RAG hallucination", "  rag hallucination  "]},
        )
        state = _empty_state(
            search_queries=["rag hallucination"],
        )
        result = query_refiner_agent(state)
        assert "search_queries" not in result
        assert "no queries distinct" in result["messages"][0].content

    def test_empty_queries_keeps_current(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(monkeypatch, {"queries": []})
        result = query_refiner_agent(_empty_state(search_queries=["a"]))
        assert "search_queries" not in result


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_fresh_queries_replace_and_history_extends(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "queries": [
                    "chain of thought benchmarks",
                    "prompt injection defense",
                ],
                "reason": "target benchmark gap",
            },
        )
        state = _empty_state(
            search_queries=["retrieval augmented generation"],
            tried_search_queries=["large language model hallucination"],
        )
        result = query_refiner_agent(state)
        # Fresh queries land in search_queries.
        assert result["search_queries"] == [
            "chain of thought benchmarks",
            "prompt injection defense",
        ]
        # History gets the previous current queries appended.
        assert result["tried_search_queries"] == [
            "large language model hallucination",
            "retrieval augmented generation",
        ]
        # Message reports count.
        assert "2 new queries" in result["messages"][0].content
        assert "target benchmark gap" in result["messages"][0].content

    def test_dedups_within_batch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {"queries": ["query one", "Query One", "query two"]},
        )
        result = query_refiner_agent(_empty_state())
        assert result["search_queries"] == ["query one", "query two"]

    def test_drops_non_string_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(monkeypatch, {"queries": [42, None, "real query", ""]})
        result = query_refiner_agent(_empty_state())
        assert result["search_queries"] == ["real query"]

    def test_respects_max_queries_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            refiner_module,
            "settings",
            Settings(query_refiner_max_queries=2),
        )
        _stub_llm(monkeypatch, {"queries": ["a", "b", "c", "d"]})
        result = query_refiner_agent(_empty_state())
        assert result["search_queries"] == ["a", "b"]

    def test_system_prompt_carries_config_max(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            refiner_module,
            "settings",
            Settings(query_refiner_max_queries=3),
        )
        captured = _stub_llm(monkeypatch, {"queries": ["x"]})
        query_refiner_agent(_empty_state())
        assert "at most 3 new queries" in captured["system_prompt"]
