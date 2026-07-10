"""Unit tests for the verifier agent.

The verifier is a pure LLM-driven node; `call_llm_json` is monkeypatched
so no real Claude calls happen. Tests cover:

- Empty-draft / no-citation short-circuits (no LLM call).
- Well-formed judge output pass-through.
- Malformed judge output — parse failure, wrong types, unknown
  `recommended_action` all fall back to a conservative default.
- Invariant: `verified=True` is never emitted alongside issues; missing
  recommendation is inferred from `missing_evidence` / `unsupported_claims`.
"""

from typing import Any

import pytest

from src.agents import verifier as verifier_module
from src.agents.verifier import (
    VALID_RECOMMENDATIONS,
    _build_user_prompt,
    _dossier_from_evidence,
    verifier_agent,
)
from src.config import Settings
from src.graph.state import ResearchState


def _empty_state(**overrides: Any) -> ResearchState:
    """A ResearchState with all fields present so TypedDict access is safe."""
    base: dict[str, Any] = {
        "run_id": "test-run",
        "query": "",
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


def _stub_llm(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any] | Exception
) -> dict[str, Any]:
    """Replace the verifier module's `call_llm_json` with a stub."""
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

    monkeypatch.setattr(verifier_module, "call_llm_json", fake)
    return captured


# ---------------------------------------------------------------------------
# Short-circuits (no LLM call)
# ---------------------------------------------------------------------------


class TestShortCircuits:
    def test_empty_draft_skips_llm_and_verifies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _stub_llm(monkeypatch, {"verified": False})
        result = verifier_agent(_empty_state())
        assert captured["calls"] == 0
        assert result["verified"] is True
        assert result["verifier_recommendation"] == ""
        assert result["unsupported_claims"] == []

    def test_draft_without_citations_skips_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _stub_llm(monkeypatch, {"verified": False})
        result = verifier_agent(_empty_state(draft_report="Some body."))
        assert captured["calls"] == 0
        assert result["verified"] is True


# ---------------------------------------------------------------------------
# Well-formed judge output
# ---------------------------------------------------------------------------


class TestSuccessPath:
    def _draft_state(self, **overrides: Any) -> ResearchState:
        return _empty_state(
            query="What is X?",
            sub_questions=["What is X?"],
            draft_report="The method works well [Smith, 2023].",
            papers=[
                {  # type: ignore[list-item]
                    "id": "p1",
                    "title": "T",
                    "authors": ["Jane Smith"],
                    "abstract": "Method works well in setting A.",
                    "url": "",
                    "pdf_url": "",
                }
            ],
            citations=[
                {  # type: ignore[list-item]
                    "paper_id": "p1",
                    "title": "T",
                    "authors": ["Jane Smith"],
                    "year": "2023",
                    "url": "",
                }
            ],
            **overrides,
        )

    def test_all_supported_returns_verified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "verified": True,
                "unsupported_claims": [],
                "missing_evidence": [],
                "recommended_action": "",
                "reason": "all claims supported",
            },
        )
        result = verifier_agent(self._draft_state())
        assert result["verified"] is True
        assert result["verifier_recommendation"] == ""
        assert result["unsupported_claims"] == []
        assert result["missing_evidence"] == []

    def test_unsupported_claim_maps_to_revise_report(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "verified": False,
                "unsupported_claims": ["The method achieves 99% accuracy."],
                "missing_evidence": [],
                "recommended_action": "revise_report",
                "reason": "over-claims accuracy",
            },
        )
        result = verifier_agent(self._draft_state())
        assert result["verified"] is False
        assert result["verifier_recommendation"] == "revise_report"
        assert result["unsupported_claims"] == [
            "The method achieves 99% accuracy."
        ]

    def test_missing_evidence_maps_to_search_more(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "verified": False,
                "unsupported_claims": [],
                "missing_evidence": ["convergence guarantees"],
                "recommended_action": "search_more",
                "reason": "no source for convergence",
            },
        )
        result = verifier_agent(self._draft_state())
        assert result["verifier_recommendation"] == "search_more"
        assert result["missing_evidence"] == ["convergence guarantees"]

    def test_read_more_recommendation_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "verified": False,
                "unsupported_claims": [],
                "missing_evidence": ["deeper detail from Smith 2023"],
                "recommended_action": "read_more",
                "reason": "detail exists in paper but wasn't extracted",
            },
        )
        result = verifier_agent(self._draft_state())
        assert result["verifier_recommendation"] == "read_more"


# ---------------------------------------------------------------------------
# Consistency invariants
# ---------------------------------------------------------------------------


class TestInvariants:
    def _draft_state(self) -> ResearchState:
        return _empty_state(
            draft_report="body [Smith, 2023].",
            citations=[
                {  # type: ignore[list-item]
                    "paper_id": "p1",
                    "title": "T",
                    "authors": ["Jane Smith"],
                    "year": "2023",
                    "url": "",
                }
            ],
        )

    def test_verified_true_with_issues_downgrades_to_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "verified": True,
                "unsupported_claims": ["c"],
                "missing_evidence": [],
                "recommended_action": "revise_report",
            },
        )
        result = verifier_agent(self._draft_state())
        # Judge said True but flagged an issue — verifier flips to False.
        assert result["verified"] is False
        # And doesn't drop the recommendation.
        assert result["verifier_recommendation"] == "revise_report"

    def test_verified_true_drops_stale_recommendation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "verified": True,
                "unsupported_claims": [],
                "missing_evidence": [],
                "recommended_action": "revise_report",
            },
        )
        result = verifier_agent(self._draft_state())
        assert result["verified"] is True
        assert result["verifier_recommendation"] == ""

    def test_missing_recommendation_inferred_from_missing_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "verified": False,
                "unsupported_claims": [],
                "missing_evidence": ["topic X"],
                "recommended_action": "",
            },
        )
        result = verifier_agent(self._draft_state())
        assert result["verifier_recommendation"] == "search_more"

    def test_missing_recommendation_inferred_from_unsupported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "verified": False,
                "unsupported_claims": ["claim c"],
                "missing_evidence": [],
                "recommended_action": "",
            },
        )
        result = verifier_agent(self._draft_state())
        assert result["verifier_recommendation"] == "revise_report"


# ---------------------------------------------------------------------------
# Malformed / hostile judge output
# ---------------------------------------------------------------------------


class TestMalformedOutput:
    def _draft_state(self) -> ResearchState:
        return _empty_state(
            draft_report="body [Smith, 2023].",
            citations=[
                {  # type: ignore[list-item]
                    "paper_id": "p1",
                    "title": "T",
                    "authors": ["Jane Smith"],
                    "year": "2023",
                    "url": "",
                }
            ],
        )

    def test_llm_exception_falls_back_to_revise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(monkeypatch, RuntimeError("api down"))
        result = verifier_agent(self._draft_state())
        assert result["verified"] is False
        assert result["verifier_recommendation"] == "revise_report"

    def test_unknown_recommendation_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "verified": False,
                "unsupported_claims": ["c"],
                "missing_evidence": [],
                "recommended_action": "wave_a_wand",
            },
        )
        result = verifier_agent(self._draft_state())
        # Unknown recommendation dropped, then inferred from unsupported.
        assert result["verifier_recommendation"] == "revise_report"

    def test_wrong_types_coerced_to_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_llm(
            monkeypatch,
            {
                "verified": "yes",  # not a bool
                "unsupported_claims": "not a list",
                "missing_evidence": [None, "", "real"],
                "recommended_action": 42,
            },
        )
        result = verifier_agent(self._draft_state())
        # `verified` truthy-but-not-True -> False.
        assert result["verified"] is False
        assert result["unsupported_claims"] == []
        assert result["missing_evidence"] == ["real"]
        assert result["verifier_recommendation"] == "search_more"

    def test_valid_recommendations_frozen_set_content(self) -> None:
        # Guard against accidental widening — the supervisor's mapping
        # from recommendation to next_action depends on this set.
        assert frozenset(
            {"read_more", "search_more", "revise_report", ""}
        ) == VALID_RECOMMENDATIONS


# ---------------------------------------------------------------------------
# Evidence-store dossier (ADR 0016) — chunks replace abstracts when available.
# ---------------------------------------------------------------------------


def _mk_paper(paper_id: str = "p1", lastname: str = "Smith") -> Any:
    return {
        "id": paper_id,
        "title": "T",
        "authors": [f"Jane {lastname}"],
        "abstract": "An abstract sentence.",
        "url": "",
        "pdf_url": "",
    }


def _mk_citation(paper_id: str = "p1", year: str = "2023", lastname: str = "Smith") -> Any:
    return {
        "paper_id": paper_id,
        "title": "T",
        "authors": [f"Jane {lastname}"],
        "year": year,
        "url": "",
    }


def _mk_claim(
    paper_id: str = "p1",
    section: str = "results",
    text: str = "F1 rose from 0.62 to 0.78.",
    score: float = 0.85,
) -> Any:
    return {
        "claim": "F1 up.",
        "paper_id": paper_id,
        "section": section,
        "source_text": text,
        "relevance_score": score,
        "supports_question": "",
    }


class TestDossierFromEvidence:
    def test_cited_paper_with_evidence_uses_chunks(self) -> None:
        dossier = _dossier_from_evidence(
            [_mk_paper()],
            [_mk_citation()],
            [_mk_claim(text="F1 rose from 0.62 to 0.78.")],
        )
        assert "[Smith, 2023] — source chunks:" in dossier
        assert "(results, relevance=0.85)" in dossier
        assert "F1 rose from 0.62 to 0.78." in dossier
        assert "An abstract sentence." not in dossier

    def test_cited_paper_without_evidence_falls_back_to_abstract(self) -> None:
        dossier = _dossier_from_evidence(
            [_mk_paper()], [_mk_citation()], evidence=[]
        )
        assert "[Smith, 2023] — abstract (no chunks available):" in dossier
        assert "An abstract sentence." in dossier

    def test_uncited_paper_skipped(self) -> None:
        # Uncited paper (Doe) + cited-but-missing paper (Smith citation
        # with no matching paper metadata) -> both excluded, dossier
        # ends up empty and returns the placeholder.
        dossier = _dossier_from_evidence(
            [_mk_paper("p2", lastname="Doe")], [_mk_citation()], []
        )
        assert "Doe" not in dossier
        assert "no cited papers" in dossier

    def test_cited_paper_and_uncited_paper_only_cited_appears(self) -> None:
        # Both papers exist in metadata; only Smith is cited. Doe should
        # be excluded from the dossier regardless.
        dossier = _dossier_from_evidence(
            [_mk_paper("p1", lastname="Smith"), _mk_paper("p2", lastname="Doe")],
            [_mk_citation("p1", "2023", "Smith")],
            [],
        )
        assert "[Smith, 2023]" in dossier
        assert "Doe" not in dossier

    def test_multiple_claims_per_paper_stacked(self) -> None:
        dossier = _dossier_from_evidence(
            [_mk_paper()],
            [_mk_citation()],
            [
                _mk_claim(text="chunk one"),
                _mk_claim(text="chunk two", section="method", score=0.9),
            ],
        )
        assert dossier.count("[Smith, 2023]") == 1  # one block per paper
        assert "chunk one" in dossier
        assert "chunk two" in dossier
        assert "(method, relevance=0.90)" in dossier

    def test_no_citations_yields_placeholder(self) -> None:
        assert _dossier_from_evidence([], [], []) == "(no cited papers with sources available)"


class TestBuildUserPromptSourceSelection:
    def test_flag_off_uses_abstract_dossier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            verifier_module, "settings", Settings(enable_evidence_store=False)
        )
        state = _empty_state(
            draft_report="body [Smith, 2023].",
            papers=[_mk_paper()],
            citations=[_mk_citation()],
            evidence=[_mk_claim()],  # populated but flag off -> ignored
        )
        prompt = _build_user_prompt(state)
        assert "Cited papers (abstracts):" in prompt
        assert "An abstract sentence." in prompt
        assert "Cited papers (ranked source chunks):" not in prompt

    def test_flag_on_with_evidence_uses_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            verifier_module, "settings", Settings(enable_evidence_store=True)
        )
        state = _empty_state(
            draft_report="body [Smith, 2023].",
            papers=[_mk_paper()],
            citations=[_mk_citation()],
            evidence=[_mk_claim(text="F1 rose 62 to 78.")],
        )
        prompt = _build_user_prompt(state)
        assert "Cited papers (ranked source chunks):" in prompt
        assert "F1 rose 62 to 78." in prompt
        # The chunk-based path doesn't ship the abstract for papers with claims.
        assert "An abstract sentence." not in prompt

    def test_flag_on_no_evidence_falls_back_to_abstract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Flag on but reader produced no claims (e.g. all PDFs missing) —
        # verifier should quietly fall through to the abstract path.
        monkeypatch.setattr(
            verifier_module, "settings", Settings(enable_evidence_store=True)
        )
        state = _empty_state(
            draft_report="body [Smith, 2023].",
            papers=[_mk_paper()],
            citations=[_mk_citation()],
            evidence=[],
        )
        prompt = _build_user_prompt(state)
        assert "Cited papers (abstracts):" in prompt
