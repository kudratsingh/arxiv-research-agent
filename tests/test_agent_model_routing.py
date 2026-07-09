"""End-to-end coverage for per-agent model overrides (ADR 0021).

For each agent that makes an LLM call, verify:
  1. Empty override string → `call_llm_json` gets `model_name=None`
     (falls back to `settings.anthropic_model` inside the LLM helper).
  2. Non-empty override string → that exact model ID is passed through.

Kept as a focused smoke suite rather than duplicating every agent's
full logic; the individual agent test files already cover the LLM
path shape.
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
    """Replace the module's `call_llm_json` with a stub that records the model."""
    captured: dict[str, Any] = {}

    def fake(
        *,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        captured["model_name"] = model_name
        # Return the union of every response shape any agent expects.
        return {
            # planner
            "sub_questions": ["s"],
            "search_queries": ["q"],
            # reader
            "key_findings": ["k"],
            "methodology": "m",
            "results_summary": "r",
            "limitations": "l",
            "relevance": 0.5,
            # synthesizer
            "draft_report": "body",
            "citations": [],
            # critic
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
            # verifier
            "verified": True,
            "unsupported_claims": [],
            "missing_evidence": [],
            "recommended_action": "",
            "reason": "ok",
            # supervisor
            "next_action": "stop",
            "stop_reason": "supervisor_stop",
            # query_refiner
            "queries": ["q1", "q2"],
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


class TestPlannerRouting:
    def test_empty_override_passes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(planner_module, "settings", Settings(planner_model=""))
        captured = _capture_llm(monkeypatch, planner_module)
        planner_module.planner_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] is None

    def test_override_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            planner_module,
            "settings",
            Settings(planner_model="claude-haiku-4-5-20251001"),
        )
        captured = _capture_llm(monkeypatch, planner_module)
        planner_module.planner_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] == "claude-haiku-4-5-20251001"


class TestCriticRouting:
    def test_empty_override_passes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(critic_module, "settings", Settings(critic_model=""))
        captured = _capture_llm(monkeypatch, critic_module)
        critic_module.critic_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] is None

    def test_override_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            critic_module,
            "settings",
            Settings(critic_model="claude-opus-4-7"),
        )
        captured = _capture_llm(monkeypatch, critic_module)
        critic_module.critic_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] == "claude-opus-4-7"


class TestSynthesizerRouting:
    def test_empty_override_passes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(synth_module, "settings", Settings(synthesizer_model=""))
        captured = _capture_llm(monkeypatch, synth_module)
        synth_module.synthesizer_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] is None

    def test_override_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            synth_module,
            "settings",
            Settings(synthesizer_model="claude-sonnet-4-6"),
        )
        captured = _capture_llm(monkeypatch, synth_module)
        synth_module.synthesizer_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] == "claude-sonnet-4-6"


class TestVerifierRouting:
    def test_empty_override_passes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(verifier_module, "settings", Settings(verifier_model=""))
        captured = _capture_llm(monkeypatch, verifier_module)
        verifier_module.verifier_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] is None

    def test_override_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            verifier_module,
            "settings",
            Settings(verifier_model="claude-haiku-4-5-20251001"),
        )
        captured = _capture_llm(monkeypatch, verifier_module)
        verifier_module.verifier_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] == "claude-haiku-4-5-20251001"


class TestSupervisorRouting:
    def test_empty_override_passes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup_module, "settings", Settings(supervisor_model=""))
        captured = _capture_llm(monkeypatch, sup_module)
        sup_module.supervisor_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] is None

    def test_override_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sup_module,
            "settings",
            Settings(supervisor_model="claude-haiku-4-5-20251001"),
        )
        captured = _capture_llm(monkeypatch, sup_module)
        sup_module.supervisor_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] == "claude-haiku-4-5-20251001"


class TestQueryRefinerRouting:
    def test_empty_override_passes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            refiner_module, "settings", Settings(query_refiner_model="")
        )
        captured = _capture_llm(monkeypatch, refiner_module)
        refiner_module.query_refiner_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] is None

    def test_override_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            refiner_module,
            "settings",
            Settings(query_refiner_model="claude-haiku-4-5-20251001"),
        )
        captured = _capture_llm(monkeypatch, refiner_module)
        refiner_module.query_refiner_agent(_empty_state())  # type: ignore[arg-type]
        assert captured["model_name"] == "claude-haiku-4-5-20251001"


class TestReaderRouting:
    """Reader is the highest-value routing target — one call per paper."""

    def _stub_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> dict[str, Any]:
        # Bypass PDF/chunk/rank so we can inspect the LLM call cleanly.
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

    def test_empty_override_passes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(reader_module, "settings", Settings(reader_model=""))
        captured = self._stub_pipeline(monkeypatch)
        reader_module._analyze_paper(
            {  # type: ignore[arg-type]
                "id": "p",
                "title": "T",
                "authors": ["A"],
                "abstract": "abs",
                "url": "",
                "pdf_url": "",
            },
            "Q?",
            ["a"],
        )
        assert captured["model_name"] is None

    def test_override_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module,
            "settings",
            Settings(reader_model="claude-haiku-4-5-20251001"),
        )
        captured = self._stub_pipeline(monkeypatch)
        reader_module._analyze_paper(
            {  # type: ignore[arg-type]
                "id": "p",
                "title": "T",
                "authors": ["A"],
                "abstract": "abs",
                "url": "",
                "pdf_url": "",
            },
            "Q?",
            ["a"],
        )
        assert captured["model_name"] == "claude-haiku-4-5-20251001"


class TestConfigDefaults:
    def test_all_agent_model_overrides_default_to_empty(self) -> None:
        # Contract: default settings have every override empty so the
        # base config exactly matches Sprint 1 behavior.
        s = Settings()
        for field in (
            "reader_model",
            "planner_model",
            "synthesizer_model",
            "critic_model",
            "verifier_model",
            "supervisor_model",
            "query_refiner_model",
        ):
            assert getattr(s, field) == "", f"{field} default drifted"
