"""Unit tests for the synthesizer agent.

Two prompt paths to exercise (see ADR 0017):
- Base path — `enable_evidence_store=False` or `state.evidence` empty.
  Prompt must stay byte-identical to the Sprint 1 baseline.
- Evidence path — flag on AND evidence populated. Prompt gains a
  grounded evidence bank grouped by sub-question.

`call_llm_json` is monkeypatched so no real Claude calls happen.
"""

from typing import Any

import pytest

from src.agents import synthesizer as synth_module
from src.agents.synthesizer import (
    _build_user_prompt,
    _format_analyses_block,
    _format_evidence_block,
    _use_evidence_path,
    synthesizer_agent,
)
from src.config import Settings
from src.graph.state import ResearchState


def _empty_state(**overrides: Any) -> ResearchState:
    base: dict[str, Any] = {
        "run_id": "test-run",
        "query": "What is RAG?",
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
        "messages": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def _paper(paper_id: str = "p1", lastname: str = "Smith") -> Any:
    # 4 authors so "et al." fires — matches production paper metadata.
    return {
        "id": paper_id,
        "title": f"Paper {paper_id}",
        "authors": [f"Jane {lastname}", "John Doe", "Third Author", "Fourth Author"],
        "abstract": "abs",
        "url": f"http://example/{paper_id}",
        "pdf_url": f"http://example/{paper_id}.pdf",
    }


def _analysis(paper_id: str = "p1", title: str = "Paper p1") -> Any:
    return {
        "paper_id": paper_id,
        "title": title,
        "key_findings": ["k1", "k2"],
        "methodology": "some method",
        "results_summary": "some results",
        "limitations": "some limits",
        "relevance": 0.85,
    }


def _claim(
    paper_id: str = "p1",
    supports: str = "sub a",
    text: str = "F1 rose from 0.62 to 0.78.",
    section: str = "results",
    score: float = 0.85,
    claim_text: str = "F1 up.",
) -> Any:
    return {
        "claim": claim_text,
        "paper_id": paper_id,
        "section": section,
        "source_text": text,
        "relevance_score": score,
        "supports_question": supports,
    }


def _stub_llm(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    resp = response or {
        "draft_report": "# Report\n\nSome body [Smith, 2023].",
        "citations": [
            {
                "paper_id": "p1",
                "title": "Paper p1",
                "authors": ["Jane Smith"],
                "year": "2023",
                "url": "http://example/p1",
            }
        ],
    }

    def fake(
        *, prompt: str, system_prompt: str, max_tokens: int
    ) -> dict[str, Any]:
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        captured["max_tokens"] = max_tokens
        return resp

    monkeypatch.setattr(synth_module, "call_llm_json", fake)
    return captured


# ---------------------------------------------------------------------------
# _use_evidence_path — path selector
# ---------------------------------------------------------------------------


class TestUseEvidencePath:
    def test_false_when_flag_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            synth_module, "settings", Settings(enable_evidence_store=False)
        )
        state = _empty_state(evidence=[_claim()])
        assert _use_evidence_path(state) is False

    def test_false_when_flag_on_but_evidence_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            synth_module, "settings", Settings(enable_evidence_store=True)
        )
        assert _use_evidence_path(_empty_state()) is False

    def test_true_when_flag_on_and_evidence_populated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            synth_module, "settings", Settings(enable_evidence_store=True)
        )
        state = _empty_state(evidence=[_claim()])
        assert _use_evidence_path(state) is True


# ---------------------------------------------------------------------------
# Base-path prompt — must remain byte-identical to Sprint 1 baseline
# ---------------------------------------------------------------------------


class TestBasePathPromptStability:
    def test_analyses_block_has_expected_headers(self) -> None:
        state = _empty_state(
            papers=[_paper()],
            paper_analyses=[_analysis()],
        )
        block = _format_analyses_block(state)
        # These header lines are what the Sprint 1 baseline prompt used.
        assert "--- Paper 1 ---" in block
        assert "Title: Paper p1" in block
        assert "Authors: Jane Smith, John Doe, Third Author et al." in block
        assert "ID: p1" in block
        assert "URL: http://example/p1" in block
        assert 'Key findings: ["k1", "k2"]' in block
        assert "Methodology: some method" in block
        assert "Results: some results" in block
        assert "Limitations: some limits" in block
        assert "Relevance: 0.85" in block

    def test_base_prompt_has_no_evidence_bank(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            synth_module, "settings", Settings(enable_evidence_store=False)
        )
        state = _empty_state(
            papers=[_paper()],
            paper_analyses=[_analysis()],
            evidence=[_claim()],  # ignored under flag-off
        )
        prompt = _build_user_prompt(state)
        assert "Evidence bank" not in prompt
        assert "Sub-questions the briefing must cover" not in prompt

    def test_base_prompt_carries_critique_when_present(self) -> None:
        state = _empty_state(
            papers=[_paper()],
            paper_analyses=[_analysis()],
            critique="tighten section 2",
        )
        prompt = _build_user_prompt(state)
        assert "Previous critique (address this feedback):" in prompt
        assert "tighten section 2" in prompt


# ---------------------------------------------------------------------------
# Evidence-path prompt — grouped, source-grounded excerpts
# ---------------------------------------------------------------------------


class TestEvidenceBlockFormatting:
    def test_groups_by_supports_question_in_planner_order(self) -> None:
        state = _empty_state(
            papers=[_paper("p1"), _paper("p2", lastname="Doe")],
            sub_questions=["sub a", "sub b"],
            evidence=[
                _claim(paper_id="p1", supports="sub b", claim_text="B-claim"),
                _claim(paper_id="p2", supports="sub a", claim_text="A-claim"),
            ],
        )
        block = _format_evidence_block(state)
        a_idx = block.index("Sub-question: sub a")
        b_idx = block.index("Sub-question: sub b")
        # Planner order preserved (sub a comes before sub b in the prompt).
        assert a_idx < b_idx
        assert "A-claim" in block
        assert "B-claim" in block

    def test_orders_by_relevance_within_a_group(self) -> None:
        state = _empty_state(
            papers=[_paper()],
            sub_questions=["sub a"],
            evidence=[
                _claim(supports="sub a", claim_text="weak", score=0.3),
                _claim(supports="sub a", claim_text="strong", score=0.9),
            ],
        )
        block = _format_evidence_block(state)
        assert block.index("strong") < block.index("weak")

    def test_unassigned_claims_kept_under_dedicated_heading(self) -> None:
        state = _empty_state(
            papers=[_paper()],
            sub_questions=["sub a"],
            evidence=[
                _claim(supports="", claim_text="orphan claim"),
            ],
        )
        block = _format_evidence_block(state)
        assert "Unassigned excerpts" in block
        assert "orphan claim" in block

    def test_includes_source_text_verbatim(self) -> None:
        state = _empty_state(
            papers=[_paper()],
            sub_questions=["sub a"],
            evidence=[
                _claim(
                    supports="sub a",
                    text="Full-text excerpt with numbers 0.62 to 0.78.",
                    section="results",
                    score=0.91,
                )
            ],
        )
        block = _format_evidence_block(state)
        assert "excerpt: Full-text excerpt with numbers 0.62 to 0.78." in block
        assert "(results, relevance=0.91)" in block


class TestEvidencePathPromptShape:
    def test_evidence_prompt_appended_to_analyses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            synth_module, "settings", Settings(enable_evidence_store=True)
        )
        state = _empty_state(
            papers=[_paper()],
            paper_analyses=[_analysis()],
            sub_questions=["sub a"],
            evidence=[_claim()],
        )
        prompt = _build_user_prompt(state)
        assert "--- Paper 1 ---" in prompt  # analyses still there
        assert "Sub-questions the briefing must cover:" in prompt
        assert "  - sub a" in prompt
        assert "Evidence bank" in prompt
        assert "Sub-question: sub a" in prompt


# ---------------------------------------------------------------------------
# synthesizer_agent — full path selection + output shape
# ---------------------------------------------------------------------------


class TestSynthesizerAgentPathSelection:
    def test_flag_off_uses_base_system_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            synth_module, "settings", Settings(enable_evidence_store=False)
        )
        captured = _stub_llm(monkeypatch)
        state = _empty_state(
            papers=[_paper()],
            paper_analyses=[_analysis()],
            evidence=[_claim()],  # ignored
        )
        result = synthesizer_agent(state)
        # Base prompt lacks the GROUNDING RULES section.
        assert "GROUNDING RULES" not in captured["system_prompt"]
        assert result["draft_report"].startswith("# Report")

    def test_flag_on_with_evidence_uses_evidence_system_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            synth_module, "settings", Settings(enable_evidence_store=True)
        )
        captured = _stub_llm(monkeypatch)
        state = _empty_state(
            papers=[_paper()],
            paper_analyses=[_analysis()],
            sub_questions=["sub a"],
            evidence=[_claim()],
        )
        synthesizer_agent(state)
        assert "GROUNDING RULES" in captured["system_prompt"]

    def test_flag_on_but_evidence_empty_falls_back_to_base(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            synth_module, "settings", Settings(enable_evidence_store=True)
        )
        captured = _stub_llm(monkeypatch)
        state = _empty_state(
            papers=[_paper()],
            paper_analyses=[_analysis()],
            evidence=[],
        )
        synthesizer_agent(state)
        assert "GROUNDING RULES" not in captured["system_prompt"]

    def test_returns_citations_and_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(monkeypatch)
        state = _empty_state(
            papers=[_paper()],
            paper_analyses=[_analysis()],
        )
        result = synthesizer_agent(state)
        assert len(result["citations"]) == 1
        assert result["citations"][0]["paper_id"] == "p1"
        assert result["messages"][0].name == "synthesizer"

    def test_evidence_path_message_reports_grounded_claims(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            synth_module, "settings", Settings(enable_evidence_store=True)
        )
        _stub_llm(monkeypatch)
        state = _empty_state(
            papers=[_paper()],
            paper_analyses=[_analysis()],
            evidence=[_claim(), _claim(claim_text="c2")],
        )
        result = synthesizer_agent(state)
        content = result["messages"][0].content
        assert "grounded claims" in content
        assert "2" in content  # "from 2 grounded claims"
