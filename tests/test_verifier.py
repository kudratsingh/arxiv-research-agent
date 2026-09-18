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
from src.eval.metrics import build_faithfulness_sources
from src.graph.state import ResearchState

pytestmark = pytest.mark.unit


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
        # CAP-04: and the calling agent's name, so its
        # `<agent>_effort` override and the run's compute tier
        # can be resolved. Same reason as `schema` above: a
        # double that refused it would fail on the call.
        agent: str = "",
        # CAP-01: the gateway now takes a schema, and the four
        # structured agents pass theirs. A double that refused it
        # would fail on the call rather than on the behaviour.
        schema: type[Any] | None = None,
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
    """The two states that verify without reaching the model at all."""
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
    """How each verdict maps to the recommendation it implies."""
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
    """The invariants that correct a self-contradicting verdict."""
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
    """What unusable verifier output falls back to."""
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


def _rendered_evidence(
    papers: list[Any], citations: list[Any], evidence: list[Any]
) -> str:
    """Render the evidence dossier the way `run_verification` does.

    Identity comes from `build_faithfulness_sources` since LE-V — which
    papers are in, and what each is called — and this function renders
    the text. The two are exercised together because a rendering keyed
    off a different join is exactly the defect that was fixed.
    """
    return _dossier_from_evidence(
        build_faithfulness_sources(papers, citations), citations, evidence
    )


class TestDossierFromEvidence:
    """Which papers enter the dossier, and what stands in for evidence."""
    def test_cited_paper_with_evidence_uses_chunks(self) -> None:
        dossier = _rendered_evidence(
            [_mk_paper()],
            [_mk_citation()],
            [_mk_claim(text="F1 rose from 0.62 to 0.78.")],
        )
        assert "[Smith, 2023] — T" in dossier
        assert "source chunks:" in dossier
        assert "(results, relevance=0.85)" in dossier
        assert "F1 rose from 0.62 to 0.78." in dossier
        assert "An abstract sentence." not in dossier

    def test_cited_paper_without_evidence_falls_back_to_abstract(self) -> None:
        dossier = _rendered_evidence([_mk_paper()], [_mk_citation()], [])
        assert "[Smith, 2023] — T" in dossier
        assert "abstract (no chunks available):" in dossier
        assert "An abstract sentence." in dossier

    def test_uncited_paper_skipped(self) -> None:
        # Uncited paper (Doe) + cited-but-missing paper (Smith citation
        # with no matching paper metadata) -> both excluded, dossier
        # ends up empty and returns the placeholder.
        dossier = _rendered_evidence(
            [_mk_paper("p2", lastname="Doe")], [_mk_citation()], []
        )
        assert "Doe" not in dossier
        assert "no cited papers" in dossier

    def test_cited_paper_and_uncited_paper_only_cited_appears(self) -> None:
        # Both papers exist in metadata; only Smith is cited. Doe should
        # be excluded from the dossier regardless.
        dossier = _rendered_evidence(
            [_mk_paper("p1", lastname="Smith"), _mk_paper("p2", lastname="Doe")],
            [_mk_citation("p1", "2023", "Smith")],
            [],
        )
        assert "[Smith, 2023]" in dossier
        assert "Doe" not in dossier

    def test_multiple_claims_per_paper_stacked(self) -> None:
        dossier = _rendered_evidence(
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
        assert _rendered_evidence([], [], []) == (
            "(no cited papers with sources available)"
        )

    def test_two_same_surname_same_year_papers_are_two_blocks(self) -> None:
        """EL-08 on the runtime path, which ADR 0100 left open.

        Both papers are cited, both are by a Zhang, both are from 2024.
        The old rendering minted `[Zhang, 2024]` from the citation list
        for each of them and emitted two blocks under one key, so the
        judge was shown two abstracts it had no way to tell apart — the
        same ambiguity the metric's index resolved by dropping one.
        """
        papers = [
            _mk_paper("p1", lastname="Zhang"),
            _mk_paper("p2", lastname="Zhang"),
        ]
        citations = [
            _mk_citation("p1", "2024", "Zhang"),
            _mk_citation("p2", "2024", "Zhang"),
        ]

        dossier = _rendered_evidence(papers, citations, [])

        assert "[Zhang, 2024a]" in dossier
        assert "[Zhang, 2024b]" in dossier
        assert dossier.count("abstract (no chunks available):") == 2

    def test_the_briefings_own_year_is_printed_when_it_differs(self) -> None:
        """The dossier's year is metadata's; the briefing's tags are not.

        A paper whose arXiv id says 2024 and whose citation entry says
        2023 is keyed `[Smith, 2024]` in the dossier, and the briefing
        says `[Smith, 2023]`. Printing the alias is what stops the judge
        concluding the cited paper was never provided.
        """
        dossier = _rendered_evidence(
            [_mk_paper("http://arxiv.org/abs/2401.00001")],
            [_mk_citation("http://arxiv.org/abs/2401.00001", "2023")],
            [],
        )

        assert "[Smith, 2024] — T" in dossier
        assert "cite this paper as [Smith, 2023]" in dossier


def _dossier_for(state: ResearchState) -> Any:
    """The dossier `run_verification` would build for this state."""
    return build_faithfulness_sources(
        state.get("papers", []), state.get("citations", [])
    )


class TestBuildUserPromptSourceSelection:
    """Which source the prompt uses, by flag and by available evidence."""
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
        prompt = _build_user_prompt(state, _dossier_for(state))
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
        prompt = _build_user_prompt(state, _dossier_for(state))
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
        prompt = _build_user_prompt(state, _dossier_for(state))
        assert "Cited papers (abstracts):" in prompt


# ---------------------------------------------------------------------------
# Ambiguous citations — ADR 0100's open item, closed at runtime (LE-V)
# ---------------------------------------------------------------------------


class TestAmbiguousCitationAbstains:
    """Two Zhangs, one tag, no verdict.

    Before LE-V the abstract dossier came from `build_source_index`,
    whose `(surname, year)` key held one entry for the two of them: the
    second paper overwrote the first and every `[Zhang, 2024]` claim was
    judged against whichever abstract the loop wrote last. ADR 0100 fixed
    the offline metric and recorded this half as open, because closing it
    changes a runtime agent's prompt.

    Both halves are pinned here: the dossier now carries both papers
    under distinct keys, and a briefing whose own tag cannot say which of
    them it meant abstains instead of guessing.
    """

    @staticmethod
    def _two_zhangs() -> tuple[list[Any], list[Any]]:
        return (
            [_mk_paper("p1", lastname="Zhang"), _mk_paper("p2", lastname="Zhang")],
            [
                _mk_citation("p1", "2024", "Zhang"),
                _mk_citation("p2", "2024", "Zhang"),
            ],
        )

    def _state(self, report: str) -> ResearchState:
        papers, citations = self._two_zhangs()
        return _empty_state(draft_report=report, papers=papers, citations=citations)

    def test_an_unsuffixed_tag_abstains_before_the_model_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(verifier_module, "settings", Settings())
        captured = _stub_llm(monkeypatch, {"verified": False})

        outcome = verifier_module.run_verification(
            self._state("Scaling helps [Zhang, 2024].")
        )

        assert outcome.verdict == "abstain"
        assert outcome.reason == "ambiguous_citation"
        # The point of abstaining *here* rather than after: a judgement
        # nobody could make must not be paid for.
        assert captured["calls"] == 0

    def test_the_reason_is_published_on_the_verdict_table(self) -> None:
        assert "ambiguous_citation" in verifier_module.VERDICT_REASONS

    def test_the_summary_names_the_contested_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(verifier_module, "settings", Settings())
        _stub_llm(monkeypatch, {"verified": False})

        outcome = verifier_module.run_verification(
            self._state("Scaling helps [Zhang, 2024].")
        )

        assert "[Zhang, 2024]" in outcome.summary

    def test_it_abstains_rather_than_failing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`fail` would spend the fixed policy's one repair (ADR 0076).

        A repair aimed at a claim that may have been checked against the
        wrong paper is a second synthesis bought with a coin flip.
        """
        monkeypatch.setattr(verifier_module, "settings", Settings())
        _stub_llm(monkeypatch, {"verified": False})

        update = verifier_module.verify_node(
            self._state("Scaling helps [Zhang, 2024].")
        )

        assert update["verification_verdict"] == "abstain"
        assert update["verification_reason"] == "ambiguous_citation"
        assert update["verified"] is True
        assert update["unsupported_claims"] == []

    def test_a_suffixed_tag_is_judged_normally(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The disambiguation is usable, so the verification proceeds."""
        monkeypatch.setattr(verifier_module, "settings", Settings())
        captured = _stub_llm(
            monkeypatch,
            {
                "verified": True,
                "unsupported_claims": [],
                "missing_evidence": [],
                "recommended_action": "",
                "reason": "all supported",
            },
        )

        outcome = verifier_module.run_verification(
            self._state("Scaling helps [Zhang, 2024a].")
        )

        assert outcome.verdict == "pass"
        assert captured["calls"] == 1
        assert "[Zhang, 2024a]" in captured["prompt"]
        assert "[Zhang, 2024b]" in captured["prompt"]

    def test_a_collision_the_briefing_never_cites_is_not_a_stop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Narrow on purpose: the trigger is the briefing's own tag.

        Two Zhangs in the corpus that the prose never cites ambiguously
        are perfectly judgeable — the dossier prints them apart — so an
        abstention here would throw away a verification for nothing.
        """
        monkeypatch.setattr(verifier_module, "settings", Settings())
        papers, citations = self._two_zhangs()
        papers.append(_mk_paper("p3", lastname="Smith"))
        citations.append(_mk_citation("p3", "2023", "Smith"))
        captured = _stub_llm(
            monkeypatch,
            {
                "verified": True,
                "unsupported_claims": [],
                "missing_evidence": [],
                "recommended_action": "",
                "reason": "all supported",
            },
        )

        outcome = verifier_module.run_verification(
            _empty_state(
                draft_report="Retrieval grounds output [Smith, 2023].",
                papers=papers,
                citations=citations,
            )
        )

        assert outcome.verdict == "pass"
        assert captured["calls"] == 1

    def test_an_unresolvable_tag_is_the_verifiers_job_not_a_stop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cite naming no paper is the fabrication the judge must catch."""
        monkeypatch.setattr(verifier_module, "settings", Settings())
        captured = _stub_llm(
            monkeypatch,
            {
                "verified": False,
                "unsupported_claims": ["invented"],
                "missing_evidence": [],
                "recommended_action": "revise_report",
                "reason": "cites a paper we never retrieved",
            },
        )

        outcome = verifier_module.run_verification(
            _empty_state(
                draft_report="A claim [Nobody, 1999].",
                papers=[_mk_paper()],
                citations=[_mk_citation()],
            )
        )

        assert outcome.verdict == "fail"
        assert captured["calls"] == 1

    def test_the_abstention_is_logged_once_with_its_keys(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(verifier_module, "settings", Settings())
        _stub_llm(monkeypatch, {"verified": False})

        with caplog.at_level("WARNING", logger="src.agents.verifier"):
            verifier_module.run_verification(
                self._state("Scaling helps [Zhang, 2024]; and again [Zhang, 2024].")
            )

        lines = [
            record
            for record in caplog.records
            if record.message == "verifier_ambiguous_citations_abstained"
        ]
        assert len(lines) == 1
        # Deduplicated: one contested key, cited twice.
        assert lines[0].count == 1  # type: ignore[attr-defined]
        assert lines[0].detail == "[Zhang, 2024]"  # type: ignore[attr-defined]
