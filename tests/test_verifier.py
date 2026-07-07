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
from src.agents.verifier import VALID_RECOMMENDATIONS, verifier_agent
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
        *, prompt: str, system_prompt: str, max_tokens: int
    ) -> dict[str, Any]:
        captured["calls"] += 1
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        captured["max_tokens"] = max_tokens
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
        assert VALID_RECOMMENDATIONS == frozenset(
            {"read_more", "search_more", "revise_report", ""}
        )
