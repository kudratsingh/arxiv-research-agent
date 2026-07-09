"""End-to-end coverage for the `enable_prompt_caching` flag (ADR 0022).

For each agent that makes an LLM call, verify:
  1. `enable_prompt_caching=False` → `cache_system=False` at the LLM helper.
  2. `enable_prompt_caching=True` → `cache_system=True` at the LLM helper.

The test stubs installed by `tests/conftest`-style patterns capture the
kwargs passed into `call_llm_json`; this file exercises each agent
just enough to see the kwarg on the way through.
"""

from typing import Any

import pytest

from src.agents import (
    critic as critic_module,
)
from src.agents import (
    planner as planner_module,
)
from src.agents import (
    query_refiner as refiner_module,
)
from src.agents import (
    reader as reader_module,
)
from src.agents import (
    supervisor as sup_module,
)
from src.agents import (
    synthesizer as synth_module,
)
from src.agents import (
    verifier as verifier_module,
)
from src.config import Settings


def _capture_llm(monkeypatch: pytest.MonkeyPatch, module: Any) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake(
        *,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        model_name: str | None = None,
        cache_system: bool = False,
    ) -> dict[str, Any]:
        captured["cache_system"] = cache_system
        return {
            "sub_questions": ["s"],
            "search_queries": ["q"],
            "key_findings": ["k"],
            "methodology": "m",
            "results_summary": "r",
            "limitations": "l",
            "relevance": 0.5,
            "draft_report": "body",
            "citations": [],
            "scores": {
                "completeness": 0.9,
                "accuracy": 0.9,
                "coherence": 0.9,
                "depth": 0.9,
                "balance": 0.9,
            },
            "average_score": 0.9,
            "critique": "ok",
            "revision_needed": False,
            "revision_target": "none",
            "verified": True,
            "unsupported_claims": [],
            "missing_evidence": [],
            "recommended_action": "",
            "reason": "ok",
            "next_action": "stop",
            "stop_reason": "supervisor_stop",
            "queries": ["q1"],
        }

    monkeypatch.setattr(module, "call_llm_json", fake)
    return captured


def _empty_state(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "run_id": "t",
        "query": "Q?",
        "sub_questions": ["a"],
        "search_queries": ["q"],
        "papers": [],
        "paper_analyses": [
            {
                "paper_id": "p1",
                "title": "T",
                "key_findings": ["k"],
                "methodology": "m",
                "results_summary": "r",
                "limitations": "l",
                "relevance": 0.5,
            }
        ],
        "draft_report": "body [Smith, 2023].",
        "citations": [
            {
                "paper_id": "p1",
                "title": "T",
                "authors": ["Jane Smith"],
                "year": "2023",
                "url": "",
            }
        ],
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
        "reader_analysis_complete": True,
        "reader_missing_context": "",
        "reader_requested_sections": [],
        "messages": [],
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "module,agent_fn,extra_stub",
    [
        (planner_module, "planner_agent", None),
        (critic_module, "critic_agent", None),
        (synth_module, "synthesizer_agent", None),
        (verifier_module, "verifier_agent", None),
        (sup_module, "supervisor_agent", None),
        (refiner_module, "query_refiner_agent", None),
    ],
    ids=[
        "planner",
        "critic",
        "synthesizer",
        "verifier",
        "supervisor",
        "query_refiner",
    ],
)
class TestAgentCacheFlagPassthrough:
    def test_flag_off_sends_cache_false(
        self,
        monkeypatch: pytest.MonkeyPatch,
        module: Any,
        agent_fn: str,
        extra_stub: Any,
    ) -> None:
        monkeypatch.setattr(module, "settings", Settings(enable_prompt_caching=False))
        captured = _capture_llm(monkeypatch, module)
        getattr(module, agent_fn)(_empty_state())
        assert captured["cache_system"] is False

    def test_flag_on_sends_cache_true(
        self,
        monkeypatch: pytest.MonkeyPatch,
        module: Any,
        agent_fn: str,
        extra_stub: Any,
    ) -> None:
        monkeypatch.setattr(module, "settings", Settings(enable_prompt_caching=True))
        captured = _capture_llm(monkeypatch, module)
        getattr(module, agent_fn)(_empty_state())
        assert captured["cache_system"] is True


class TestReaderCacheFlag:
    """Reader is exercised through `_analyze_paper` because `reader_agent`
    calls it under a thread pool."""

    def _stub_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        monkeypatch.setattr(
            reader_module, "parse_pdf", lambda _url: "some full text"
        )
        monkeypatch.setattr(
            reader_module,
            "chunk_paper",
            lambda _t: [{"section": "method", "text": "m", "chunk_index": 0}],
        )
        monkeypatch.setattr(
            reader_module,
            "rank_chunks_by_relevance",
            lambda _c, _s, top_k, preferred_sections=None: [
                {
                    "section": "method",
                    "text": "method body",
                    "chunk_index": 0,
                    "relevance_score": 0.9,
                },
            ],
        )
        return _capture_llm(monkeypatch, reader_module)

    def _paper(self) -> Any:
        return {
            "id": "p",
            "title": "T",
            "authors": ["A"],
            "abstract": "abs",
            "url": "",
            "pdf_url": "",
        }

    def test_flag_off_sends_cache_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_prompt_caching=False)
        )
        captured = self._stub_pipeline(monkeypatch)
        reader_module._analyze_paper(self._paper(), "Q?", ["a"])
        assert captured["cache_system"] is False

    def test_flag_on_sends_cache_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_prompt_caching=True)
        )
        captured = self._stub_pipeline(monkeypatch)
        reader_module._analyze_paper(self._paper(), "Q?", ["a"])
        assert captured["cache_system"] is True


class TestCachingDefaultOff:
    def test_default_settings_have_caching_off(self) -> None:
        # Contract: baseline behavior unchanged unless user opts in.
        assert Settings().enable_prompt_caching is False
