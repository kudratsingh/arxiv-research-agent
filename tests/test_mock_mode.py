"""`src/agents/mock_mode.py`, and the promise that it stays out of the way.

Two halves, and the second is the one that would catch a real
regression. The first exercises the generators: what they derive, what
they refuse to invent, and the labelling that keeps a mock briefing
from reading as a real one. The second is the golden half — with
`use_mock_data` off, every one of the five agents must reach
`call_llm_json` and must not touch this module, because the whole
premise of ADR 0080 is that the live path is unchanged.

The golden half is written as five separate tests rather than one
parametrised sweep because the five agents reach the model through five
different shapes (a fan-out, a retry helper, three direct calls), and a
sweep that passed would not say which of them still does.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.agents import critic as critic_module
from src.agents import mock_mode
from src.agents import planner as planner_module
from src.agents import reader as reader_module
from src.agents import synthesizer as synthesizer_module
from src.agents import verifier as verifier_module
from src.agents.search import MOCK_PAPERS
from src.config import Settings
from src.config import settings as real_settings
from src.graph.state import (
    Citation,
    PaperAnalysis,
    PaperMetadata,
    ResearchState,
    initial_research_state,
)

pytestmark = pytest.mark.unit


def _paper(**overrides: Any) -> PaperMetadata:
    """A fixture paper, overridable field by field."""
    base = PaperMetadata(
        id="http://arxiv.org/abs/2311.09000",
        title="A Survey on Hallucination",
        authors=["Ziwei Ji", "Nayeon Lee"],
        abstract=(
            "Large language models are prone to hallucinate under load. "
            "Short one. "
            "Retrieval reduces the rate by 34.8% on the benchmark we report."
        ),
        url="http://arxiv.org/abs/2311.09000",
        pdf_url="http://arxiv.org/pdf/2311.09000",
    )
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


class TestThePlan:
    def test_it_reuses_the_fallback_shape_rather_than_inventing_one(self) -> None:
        """The raw query, once, on both fields — ADR 0041's own fallback.

        A mock decomposition would be a guess about the topic dressed as
        an analysis of it. This shape is visibly shallow, which is the
        property ADR 0041 wanted from the fallback in the first place.
        """
        assert mock_mode.mock_plan("why do LLMs hallucinate?") == (
            ["why do LLMs hallucinate?"],
            ["why do LLMs hallucinate?"],
        )

    def test_a_blank_query_still_produces_a_plan(self) -> None:
        """`_build_fixed_pipeline` has no branch for an empty plan.

        The planner's live fallback has the same property: a plan field
        is never empty, because the search agent indexes it and the
        synthesizer builds sections from it.
        """
        sub_questions, search_queries = mock_mode.mock_plan("   ")
        assert sub_questions == search_queries == ["(no question was given)"]


class TestTheAnalysis:
    def test_every_finding_is_a_verbatim_span_of_the_abstract(self) -> None:
        paper = _paper()
        analysis = mock_mode.mock_analysis(paper)
        assert analysis["key_findings"]
        for finding in analysis["key_findings"]:
            assert finding in paper["abstract"]

    def test_a_percentage_does_not_end_a_sentence(self) -> None:
        """`34.8%` is not two sentences, and a naive split says it is."""
        findings = mock_mode.mock_analysis(_paper())["key_findings"]
        assert any("34.8% on the benchmark" in finding for finding in findings)

    def test_it_carries_the_paper_s_own_identity_not_the_generator_s(self) -> None:
        analysis = mock_mode.mock_analysis(_paper(id="s2:abc", title="Elsewhere"))
        assert analysis["paper_id"] == "s2:abc"
        assert analysis["title"] == "Elsewhere"

    def test_an_abstractless_paper_says_so_instead_of_reporting_nothing(self) -> None:
        """An empty `key_findings` reads as a paper that said nothing."""
        analysis = mock_mode.mock_analysis(_paper(abstract=""))
        assert analysis["key_findings"] == [
            "This paper carries no abstract, so mock mode has nothing to restate."
        ]

    def test_the_limitations_field_names_what_produced_the_text(self) -> None:
        """The degradation has to survive into the report's source data."""
        assert "not a model" in mock_mode.mock_analysis(_paper())["limitations"]


class TestTheClaims:
    def test_claim_and_source_are_the_same_verbatim_span(self) -> None:
        """What the verifier judges against must be findable in the source.

        The live reader guarantees this by refusing to build a claim
        without a ranked chunk (ADR 0016); mock mode guarantees it by
        making the assertion and its evidence one slice of the abstract.
        """
        paper = _paper()
        claims = mock_mode.mock_claims(paper, sub_questions=["q"], max_claims=5)
        assert claims
        for claim in claims:
            assert claim["source_text"] == claim["claim"]
            assert claim["source_text"] in paper["abstract"]

    def test_a_fragment_too_short_to_assert_anything_is_dropped(self) -> None:
        """`Short one.` is three words; a claim has to be a claim."""
        claims = mock_mode.mock_claims(_paper(), sub_questions=[], max_claims=9)
        assert all(len(c["claim"].split()) >= mock_mode.MIN_CLAIM_WORDS for c in claims)
        assert not any(c["claim"].startswith("Short one") for c in claims)

    def test_the_cap_is_the_caller_s_setting_not_this_module_s(self) -> None:
        assert len(mock_mode.mock_claims(_paper(), sub_questions=[], max_claims=1)) == 1
        assert mock_mode.mock_claims(_paper(), sub_questions=[], max_claims=0) == []

    def test_attribution_names_a_sub_question_the_planner_asked(self) -> None:
        """Anything else would make `supports_question` untrustworthy.

        The live reader drops an attribution the planner never asked
        for, for the same reason.
        """
        claims = mock_mode.mock_claims(
            _paper(), sub_questions=["  ", "the real one"], max_claims=2
        )
        assert {c["supports_question"] for c in claims} == {"the real one"}

    def test_with_no_plan_the_attribution_is_empty_rather_than_guessed(self) -> None:
        claims = mock_mode.mock_claims(_paper(), sub_questions=[], max_claims=2)
        assert {c["supports_question"] for c in claims} == {""}

    def test_an_abstractless_paper_yields_no_claims(self) -> None:
        assert mock_mode.mock_claims(
            _paper(abstract=""), sub_questions=["q"], max_claims=5
        ) == []


class TestTheBriefing:
    def _briefing(self, **overrides: Any) -> tuple[str, list[Any]]:
        papers = list(MOCK_PAPERS)
        kwargs: dict[str, Any] = {
            "query": "why do LLMs hallucinate?",
            "sub_questions": ["why do LLMs hallucinate?"],
            "papers": papers,
            "analyses": [mock_mode.mock_analysis(p) for p in papers],
            "evidence": [],
            "evidence_path": False,
        }
        kwargs.update(overrides)
        return mock_mode.mock_briefing(**kwargs)

    def test_the_first_line_is_the_banner_exactly(self) -> None:
        """Not "starts with", not "contains" — the first line, verbatim.

        A label a reader has to scroll to find is a label that did not
        do its job, and this is the one assertion that stops a mock
        report from being mistaken for a real one.
        """
        report, _ = self._briefing()
        assert report.splitlines()[0] == "Mock mode: fixture papers, no model call."
        assert report.splitlines()[0] == mock_mode.MOCK_BANNER

    def test_every_retrieved_paper_is_cited_on_both_surfaces(self) -> None:
        """`groundedness` checks the body and the citation list.

        A briefing that carried only one of them would leave half the
        check untested and a fabricated entry undetected.
        """
        report, citations = self._briefing()
        assert len(citations) == len(MOCK_PAPERS)
        for paper in MOCK_PAPERS:
            assert f"arXiv:{mock_mode.arxiv_tail(paper['id'])}" in report
        assert {c["paper_id"] for c in citations} == {p["id"] for p in MOCK_PAPERS}

    def test_sections_follow_the_plan_and_deal_every_paper_once(self) -> None:
        report, _ = self._briefing(sub_questions=["first ask", "second ask"])
        assert "## first ask" in report and "## second ask" in report
        for paper in MOCK_PAPERS:
            assert report.count(f"arXiv:{mock_mode.arxiv_tail(paper['id'])}") == 1

    def test_a_sub_question_the_corpus_cannot_answer_says_so(self) -> None:
        """Dropping the section would hide the gap the plan exposed."""
        report, _ = self._briefing(
            papers=[MOCK_PAPERS[0]],
            analyses=[mock_mode.mock_analysis(MOCK_PAPERS[0])],
            sub_questions=["answered", "unanswered"],
        )
        assert "No retrieved paper was assigned to this sub-question." in report

    def test_a_plan_with_no_sub_questions_still_produces_one_section(self) -> None:
        report, _ = self._briefing(sub_questions=[])
        assert "## Findings" in report

    def test_it_quotes_nothing(self) -> None:
        """So ADR 0074's quote check reports `no_quotes`, honestly.

        `extract_quotes` reads any six-word span inside double quotes as
        a claim. With no full text to check it against, every such claim
        would be undecidable — a column of exclusions that says nothing
        — so the briefing declines to create the denominator.
        """
        report, _ = self._briefing()
        assert '"' not in report

    def test_the_evidence_path_prints_the_source_the_verifier_judges(self) -> None:
        papers = [MOCK_PAPERS[0]]
        claims = mock_mode.mock_claims(papers[0], sub_questions=["q"], max_claims=2)
        report, _ = self._briefing(
            papers=papers,
            analyses=[mock_mode.mock_analysis(papers[0])],
            sub_questions=["q"],
            evidence=claims,
            evidence_path=True,
        )
        for claim in claims:
            assert f"- Evidence (abstract): {claim['source_text']}" in report

    def test_the_two_paths_cite_identically(self) -> None:
        """Which is what makes their groundedness numbers comparable."""
        papers = [MOCK_PAPERS[0]]
        analyses = [mock_mode.mock_analysis(papers[0])]
        claims = mock_mode.mock_claims(papers[0], sub_questions=["q"], max_claims=2)
        _, base = self._briefing(papers=papers, analyses=analyses, sub_questions=["q"])
        _, grounded = self._briefing(
            papers=papers,
            analyses=analyses,
            sub_questions=["q"],
            evidence=claims,
            evidence_path=True,
        )
        assert base == grounded

    def test_an_empty_corpus_produces_a_briefing_that_cites_nothing(self) -> None:
        """And says how many papers it had, rather than pretending."""
        report, citations = self._briefing(papers=[], analyses=[])
        assert citations == []
        assert report.splitlines()[0] == mock_mode.MOCK_BANNER
        assert "assembled from 0 fixture paper(s)" in report

    def test_a_titleless_paper_keeps_its_citation_entry(self) -> None:
        """`_parse_citations` drops a titleless entry, shrinking the claim
        set without saying so. Naming the paper by its identifier keeps
        the entry and keeps the gap visible."""
        papers = [_paper(title="")]
        _, citations = self._briefing(
            papers=papers, analyses=[mock_mode.mock_analysis(papers[0])]
        )
        assert citations[0]["title"] == "Untitled paper http://arxiv.org/abs/2311.09000"


class TestTheIdentifierHelpers:
    @pytest.mark.parametrize(
        ("paper_id", "expected"),
        [
            ("http://arxiv.org/abs/2311.09000", "2311.09000"),
            ("http://arxiv.org/abs/2311.09000/", "2311.09000"),
            ("2311.09000", "2311.09000"),
            ("s2:abcdef", "s2:abcdef"),
        ],
    )
    def test_the_tail_is_the_bare_identifier(
        self, paper_id: str, expected: str
    ) -> None:
        assert mock_mode.arxiv_tail(paper_id) == expected

    @pytest.mark.parametrize(
        ("paper_id", "expected"),
        [
            ("http://arxiv.org/abs/2311.09000", "2023"),
            ("http://arxiv.org/abs/2401.01313", "2024"),
            ("cs.CL/0301001", ""),
            ("s2:abcdef", ""),
        ],
    )
    def test_the_year_is_read_off_the_yymm_prefix(
        self, paper_id: str, expected: str
    ) -> None:
        assert mock_mode.arxiv_year(paper_id) == expected


# ---------------------------------------------------------------------------
# The golden half: with the setting off, this module is not reached
# ---------------------------------------------------------------------------


@pytest.fixture
def live_mode(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """`use_mock_data=False` on every agent module, stated rather than assumed.

    The harness scrubs `USE_MOCK_DATA` and rebuilds the singleton, so
    the shipped default already holds — but a golden test whose premise
    is a default is a test that goes quiet the day the default moves.
    """
    live = real_settings.model_copy(update={"use_mock_data": False})
    assert isinstance(live, Settings)
    for module in (
        "src.agents.critic",
        "src.agents.planner",
        "src.agents.reader",
        "src.agents.synthesizer",
        "src.agents.verifier",
    ):
        monkeypatch.setattr(f"{module}.settings", live)
    return live


@pytest.fixture
def mock_mode_is_a_trap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any entry into a mock generator fail the test that entered it.

    Asserting on the *output* would not do: three of the five agents
    have degradation paths that produce a plausible-looking result from
    nothing (ADR 0041), so a mock branch taken by mistake could be
    indistinguishable from a live call that came back malformed.
    """

    def _trap(name: str) -> Any:
        def _boom(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError(
                f"mock_mode.{name} was entered with use_mock_data=False"
            )

        return _boom

    for name in (
        "mock_plan",
        "mock_analysis",
        "mock_claims",
        "mock_briefing",
        "mock_critique",
    ):
        monkeypatch.setattr(mock_mode, name, _trap(name))


def _recorder(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    """A `call_llm_json` stand-in plus the log of what it was asked."""
    calls: list[dict[str, Any]] = []

    def _call(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return dict(payload)

    return calls, _call


def _state(**overrides: Any) -> ResearchState:
    state = initial_research_state("why do LLMs hallucinate?", "golden-1")
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def _analysis(paper_id: str) -> PaperAnalysis:
    """The smallest analysis the synthesizer and critic prompts unpack."""
    return PaperAnalysis(
        paper_id=paper_id,
        title="A Survey on Hallucination",
        key_findings=["f"],
        methodology="m",
        results_summary="r",
        limitations="l",
        relevance=0.5,
    )


class TestTheLivePathIsUnchanged:
    def test_the_planner_reaches_the_model(
        self,
        live_mode: Settings,
        mock_mode_is_a_trap: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls, call = _recorder(
            {"sub_questions": ["a"], "search_queries": ["b"]}
        )
        monkeypatch.setattr(planner_module, "call_llm_json", call)
        update = planner_module.planner_agent(_state())
        assert len(calls) == 1
        assert update["sub_questions"] == ["a"]
        assert "(mock data)" not in update["messages"][0].content

    def test_the_reader_reaches_the_model(
        self,
        live_mode: Settings,
        mock_mode_is_a_trap: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls, call = _recorder(
            {
                "key_findings": ["f"],
                "methodology": "m",
                "results_summary": "r",
                "limitations": "l",
                "relevance": 0.5,
            }
        )
        monkeypatch.setattr(reader_module, "call_llm_json", call)
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "")
        update = reader_module.reader_agent(
            _state(papers=[_paper()], sub_questions=["q"])
        )
        assert len(calls) == 1
        assert update["paper_analyses"][0]["key_findings"] == ["f"]

    def test_the_synthesizer_reaches_the_model(
        self,
        live_mode: Settings,
        mock_mode_is_a_trap: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls, call = _recorder({"draft_report": "# Real", "citations": []})
        monkeypatch.setattr(synthesizer_module, "call_llm_json", call)
        update = synthesizer_module.synthesizer_agent(
            _state(papers=[_paper()], paper_analyses=[_analysis(_paper()["id"])])
        )
        assert len(calls) == 1
        assert update["draft_report"] == "# Real"

    def test_the_critic_reaches_the_model(
        self,
        live_mode: Settings,
        mock_mode_is_a_trap: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls, call = _recorder(
            {
                "average_score": 0.42,
                "critique": "real critique",
                "revision_needed": False,
            }
        )
        monkeypatch.setattr(critic_module, "call_llm_json", call)
        update = critic_module.critic_agent(
            _state(draft_report="# Real", paper_analyses=[_analysis("p")])
        )
        assert len(calls) == 1
        assert update["quality_score"] == pytest.approx(0.42)
        assert update["critique"] == "real critique"

    def test_the_verifier_reaches_the_model(
        self,
        live_mode: Settings,
        mock_mode_is_a_trap: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls, call = _recorder(
            {"verified": False, "unsupported_claims": ["c"], "reason": "real"}
        )
        monkeypatch.setattr(verifier_module, "call_llm_json", call)
        update = verifier_module.verifier_agent(
            _state(
                draft_report="# Real [Ji, 2023]",
                papers=[_paper()],
                citations=[
                    Citation(
                        paper_id=_paper()["id"],
                        title="A Survey on Hallucination",
                        authors=["Ziwei Ji"],
                        year="2023",
                        url=_paper()["url"],
                    )
                ],
            )
        )
        assert len(calls) == 1
        assert update["verified"] is False
        assert mock_mode.MOCK_VERIFICATION_SUMMARY not in update["messages"][0].content
