"""Unit tests for the faithfulness metric.

Pure helpers (`build_faithfulness_sources`,
`_build_faithfulness_prompt`, `_aggregate_claims`, `resolve_cite`,
`_cite_key_from_string`) are tested directly. The full
`measure_faithfulness` path is exercised with `call_llm_json`
monkeypatched — no real Claude calls, no network, no spend.

The ADR 0100 cases are the ones to read first: two papers by a Zhang in
2024 must be judged against their own abstracts (EL-08), a claim
supported only by a body chunk must turn on whether the chunks were
supplied (EL-09), an empty denominator must be `None` with a reason
(EL-10), and each judge call must carry its own schema and temperature
(EL-11).
"""

from typing import Any

import pytest

from src.config import Settings
from src.eval import metrics as metrics_module
from src.eval import provenance as provenance_module
from src.eval.metrics import (
    ALL_SOURCES_UNAVAILABLE,
    CITE_AMBIGUOUS,
    CITE_MALFORMED,
    CITE_RESOLVED,
    CITE_UNRESOLVED,
    EMPTY_REPORT,
    NO_CITED_CLAIMS,
    SOURCE_SCOPE_ABSTRACT_AND_CHUNKS,
    SOURCE_SCOPE_ABSTRACT_ONLY,
    ClaimJudgement,
    FaithfulnessJudgeOutput,
    FaithfulnessResult,
    SourceDossier,
    _aggregate_claims,
    _build_faithfulness_prompt,
    _cite_key_from_string,
    build_faithfulness_sources,
    measure_faithfulness,
    resolve_cite,
)
from src.graph.state import Citation, PaperMetadata

pytestmark = pytest.mark.unit


def _mk_paper(
    *,
    paper_id: str,
    first_author: str,
    abstract: str = "Some abstract.",
    title: str = "Paper title",
    published: str | None = None,
) -> PaperMetadata:
    return PaperMetadata(
        id=paper_id,
        title=title,
        authors=[first_author, "Second Author"],
        abstract=abstract,
        url=paper_id,
        pdf_url=f"{paper_id}.pdf",
        published=published,
    )


def _mk_citation(*, paper_id: str, year: str, first_author: str) -> Citation:
    return Citation(
        paper_id=paper_id,
        title="Paper title",
        authors=[first_author, "Second Author"],
        year=year,
        url=paper_id,
    )


def _two_zhangs() -> tuple[list[PaperMetadata], list[Citation]]:
    """The EL-08 reproduction: two cited papers, one surname, one year."""
    papers = [
        _mk_paper(
            paper_id="p1",
            first_author="Wei Zhang",
            abstract="ZHANG-ONE proves the retrieval bound.",
            title="Retrieval bounds",
        ),
        _mk_paper(
            paper_id="p2",
            first_author="Lin Zhang",
            abstract="ZHANG-TWO measures annotator drift.",
            title="Annotator drift",
        ),
    ]
    citations = [
        _mk_citation(paper_id="p1", year="2024", first_author="Wei Zhang"),
        _mk_citation(paper_id="p2", year="2024", first_author="Lin Zhang"),
    ]
    return papers, citations


def _dossier_block(prompt: str, cite_key: str) -> str:
    """The prompt text the judge was given under one cite key.

    A stand-in for what a real judge reads: the block that opens with
    that key, up to the blank line. The fake judges below decide
    `supported` from this and nothing else, so a passing test can only
    have passed because the right text sat under the right key.
    """
    body = prompt.split("Cited papers:\n\n", 1)[1]
    for block in body.split("\n\n"):
        if block.startswith(f"[{cite_key}]"):
            return block
    return ""


class TestTheLegacyJoinIsGone:
    """LE-V: `build_source_index` had one caller left, and it was the bug.

    ADR 0100 kept that `(surname, year)` join alive at its original
    contract — two same-surname, same-year papers collapsing to one
    entry and all — because `src/agents/verifier.py` built its
    abstract-path dossier from its keys, and a metrics work order may not
    change a runtime agent's prompt. The class that used to sit here
    pinned the defect so the follow-up could not be lost.

    The follow-up landed: the verifier builds its dossier from
    `build_faithfulness_sources`, and a join with a known collision and
    no callers is a trap rather than an API. This is the assertion that
    replaces the pin — it fails if the function comes back.
    """

    def test_metrics_publishes_exactly_one_cited_source_join(self) -> None:
        assert not hasattr(metrics_module, "build_source_index")
        assert hasattr(metrics_module, "build_faithfulness_sources")


class TestBuildFaithfulnessSources:
    """Identity by `paper_id`, unique cite keys, and declared scope."""

    def test_two_same_surname_same_year_papers_both_survive(self) -> None:
        papers, citations = _two_zhangs()
        dossier = build_faithfulness_sources(papers, citations)

        assert [s["paper_id"] for s in dossier["sources"]] == ["p1", "p2"]
        assert [s["cite_key"] for s in dossier["sources"]] == [
            "Zhang, 2024a",
            "Zhang, 2024b",
        ]
        assert dossier["collision_count"] == 2
        assert dossier["sources"][0]["abstract"].startswith("ZHANG-ONE")
        assert dossier["sources"][1]["abstract"].startswith("ZHANG-TWO")

    def test_an_uncontested_key_carries_no_suffix(self) -> None:
        papers = [_mk_paper(paper_id="p1", first_author="Jane Smith")]
        citations = [_mk_citation(paper_id="p1", year="2023", first_author="Jane Smith")]
        dossier = build_faithfulness_sources(papers, citations)

        assert dossier["sources"][0]["cite_key"] == "Smith, 2023"
        assert dossier["sources"][0]["suffix"] == ""
        assert dossier["collision_count"] == 0

    def test_the_year_comes_from_the_paper_id_when_it_is_an_arxiv_id(self) -> None:
        # The citation says 2019; the identifier the retrieval pipeline
        # wrote says 2401 -> 2024. The metric trusts the pipeline, not
        # the model whose output it is checking.
        paper_id = "https://arxiv.org/abs/2401.00001"
        papers = [_mk_paper(paper_id=paper_id, first_author="Jane Smith")]
        citations = [
            _mk_citation(paper_id=paper_id, year="2019", first_author="Jane Smith")
        ]
        dossier = build_faithfulness_sources(papers, citations)

        assert dossier["sources"][0]["year"] == "2024"

    def test_the_publication_date_outranks_the_identifier(self) -> None:
        """LE-V. Three year sources, in order of independence.

        `published` is what the retrieval source *stated*; the
        identifier's `YYMM` is a submission month inferred from a
        numbering scheme; the citation's year was written by the model
        under examination. The first one available wins.
        """
        paper_id = "https://arxiv.org/abs/2401.00001"
        papers = [
            _mk_paper(
                paper_id=paper_id, first_author="Jane Smith", published="2023-12-30"
            )
        ]
        citations = [
            _mk_citation(paper_id=paper_id, year="2019", first_author="Jane Smith")
        ]
        dossier = build_faithfulness_sources(papers, citations)

        assert dossier["sources"][0]["year"] == "2023"

    def test_a_year_precision_date_is_enough(self) -> None:
        """Semantic Scholar states a year and no more; that is a date."""
        papers = [
            _mk_paper(
                paper_id="local-fixture-1",
                first_author="Jane Smith",
                published="2021",
            )
        ]
        citations = [
            _mk_citation(paper_id="local-fixture-1", year="2019", first_author="J Smith")
        ]

        assert build_faithfulness_sources(papers, citations)["sources"][0]["year"] == (
            "2021"
        )

    def test_an_unreadable_date_falls_through_rather_than_deciding(self) -> None:
        paper_id = "https://arxiv.org/abs/2401.00001"
        for unreadable in ("", "   ", "last Tuesday", "0000-01-01", None):
            papers = [
                _mk_paper(
                    paper_id=paper_id,
                    first_author="Jane Smith",
                    published=unreadable,
                )
            ]
            citations = [
                _mk_citation(paper_id=paper_id, year="2019", first_author="J Smith")
            ]
            dossier = build_faithfulness_sources(papers, citations)

            assert dossier["sources"][0]["year"] == "2024", unreadable

    def test_a_paper_recorded_before_the_key_existed_still_joins(self) -> None:
        """`episode-state.json` files written before LE-V have no such key.

        They are parsed straight back into `PaperMetadata`, so a
        subscript here would turn an old snapshot into a `KeyError` on a
        re-judge months later.
        """
        legacy: Any = {
            "id": "https://arxiv.org/abs/2401.00001",
            "title": "t",
            "authors": ["Jane Smith"],
            "abstract": "a",
            "url": "u",
            "pdf_url": "p",
        }
        citations = [
            _mk_citation(
                paper_id="https://arxiv.org/abs/2401.00001",
                year="2019",
                first_author="J Smith",
            )
        ]

        assert build_faithfulness_sources([legacy], citations)["sources"][0][
            "year"
        ] == "2024"

    def test_the_citations_year_still_resolves_as_an_alias(self) -> None:
        # The report's inline tags were written from the citation list,
        # so a dossier the report's own tags cannot address would trade
        # one silent failure for another.
        paper_id = "https://arxiv.org/abs/2401.00001"
        papers = [_mk_paper(paper_id=paper_id, first_author="Jane Smith")]
        citations = [
            _mk_citation(paper_id=paper_id, year="2019", first_author="Jane Smith")
        ]
        dossier = build_faithfulness_sources(papers, citations)

        assert resolve_cite("[Smith, 2019]", dossier) == (paper_id, CITE_RESOLVED)
        assert resolve_cite("[Smith, 2024]", dossier) == (paper_id, CITE_RESOLVED)

    def test_the_citation_year_is_the_fallback_for_a_non_arxiv_id(self) -> None:
        papers = [_mk_paper(paper_id="local-fixture-1", first_author="Jane Smith")]
        citations = [
            _mk_citation(paper_id="local-fixture-1", year="2023", first_author="J Smith")
        ]
        dossier = build_faithfulness_sources(papers, citations)
        assert dossier["sources"][0]["year"] == "2023"

    def test_an_identifier_with_an_impossible_month_is_not_a_date(self) -> None:
        # `2413` parses as an arXiv id and is not a `YYMM`. Falling back
        # is the honest move; reading it as month 13 would invent a year.
        papers = [_mk_paper(paper_id="2413.00001", first_author="Jane Smith")]
        citations = [
            _mk_citation(paper_id="2413.00001", year="2019", first_author="J Smith")
        ]
        assert build_faithfulness_sources(papers, citations)["sources"][0]["year"] == (
            "2019"
        )

    def test_a_blank_first_author_omits_the_paper(self) -> None:
        papers = [
            PaperMetadata(
                id="p1", title="t", authors=["   "], abstract="a", url="u", pdf_url="p"
            )
        ]
        citations = [_mk_citation(paper_id="p1", year="2023", first_author="X")]
        assert build_faithfulness_sources(papers, citations)["sources"] == []

    def test_an_old_style_arxiv_id_yields_its_century(self) -> None:
        papers = [_mk_paper(paper_id="cs.CL/0301001", first_author="Jane Smith")]
        citations = [
            _mk_citation(paper_id="cs.CL/0301001", year="2019", first_author="J Smith")
        ]
        assert build_faithfulness_sources(papers, citations)["sources"][0]["year"] == (
            "2003"
        )

    def test_papers_without_a_citation_authors_or_year_are_omitted(self) -> None:
        papers = [
            _mk_paper(paper_id="uncited", first_author="Nobody Cited"),
            PaperMetadata(
                id="no-authors", title="t", authors=[], abstract="a", url="u", pdf_url="p"
            ),
            _mk_paper(paper_id="no-year", first_author="Jane Smith"),
        ]
        citations = [
            _mk_citation(paper_id="no-authors", year="2023", first_author="X"),
            _mk_citation(paper_id="no-year", year="", first_author="Jane Smith"),
        ]
        assert build_faithfulness_sources(papers, citations)["sources"] == []

    def test_supplied_chunks_change_the_declared_scope(self) -> None:
        papers, citations = _two_zhangs()
        dossier = build_faithfulness_sources(
            papers, citations, {"p1": ["first chunk", "   ", "second chunk"]}
        )

        assert dossier["source_scope"] == SOURCE_SCOPE_ABSTRACT_AND_CHUNKS
        assert dossier["sources_with_chunks"] == 1
        # Blank chunks are dropped rather than shown as empty excerpts.
        assert dossier["sources"][0]["chunks"] == ["first chunk", "second chunk"]
        assert dossier["sources"][0]["source_scope"] == SOURCE_SCOPE_ABSTRACT_AND_CHUNKS
        assert dossier["sources"][1]["source_scope"] == SOURCE_SCOPE_ABSTRACT_ONLY

    def test_no_chunks_is_abstract_only(self) -> None:
        papers, citations = _two_zhangs()
        dossier = build_faithfulness_sources(papers, citations)
        assert dossier["source_scope"] == SOURCE_SCOPE_ABSTRACT_ONLY
        assert dossier["sources_with_chunks"] == 0

    def test_more_than_twenty_six_collisions_still_get_distinct_keys(self) -> None:
        papers = [
            _mk_paper(paper_id=f"p{i}", first_author="Wei Zhang") for i in range(30)
        ]
        citations = [
            _mk_citation(paper_id=f"p{i}", year="2024", first_author="Wei Zhang")
            for i in range(30)
        ]
        dossier = build_faithfulness_sources(papers, citations)
        keys = [s["cite_key"] for s in dossier["sources"]]
        assert len(set(keys)) == 30
        assert keys[26] == "Zhang, 2024aa"


class TestResolveCite:
    """Which cite forms resolve, which abstain, and which are refused."""

    @staticmethod
    def _dossier() -> SourceDossier:
        papers, citations = _two_zhangs()
        papers.append(_mk_paper(paper_id="p3", first_author="Jane Smith"))
        citations.append(
            _mk_citation(paper_id="p3", year="2023", first_author="Jane Smith")
        )
        return build_faithfulness_sources(papers, citations)

    def test_a_suffixed_key_resolves_to_its_own_paper(self) -> None:
        dossier = self._dossier()
        assert resolve_cite("[Zhang, 2024a]", dossier) == ("p1", CITE_RESOLVED)
        assert resolve_cite("[Zhang, 2024b]", dossier) == ("p2", CITE_RESOLVED)

    def test_an_unsuffixed_key_with_one_candidate_resolves(self) -> None:
        assert resolve_cite("[Smith, 2023]", self._dossier()) == ("p3", CITE_RESOLVED)

    def test_an_unsuffixed_key_with_two_candidates_abstains(self) -> None:
        # The EL-08 case at resolution time: never resolved to one of
        # them, because either choice would be a coin flip recorded as a
        # measurement.
        assert resolve_cite("[Zhang, 2024]", self._dossier()) == (None, CITE_AMBIGUOUS)

    def test_an_unknown_paper_is_unresolved(self) -> None:
        assert resolve_cite("[Ghost, 2020]", self._dossier()) == (
            None,
            CITE_UNRESOLVED,
        )

    def test_a_non_citation_is_malformed(self) -> None:
        dossier = self._dossier()
        assert resolve_cite("not a citation", dossier) == (None, CITE_MALFORMED)
        assert resolve_cite("", dossier) == (None, CITE_MALFORMED)

    def test_a_cite_whose_author_field_is_punctuation_is_malformed(self) -> None:
        # Matches the tag shape, normalises to no surname at all.
        assert resolve_cite("[ , 2023]", self._dossier()) == (None, CITE_MALFORMED)

    def test_the_bare_and_et_al_forms_are_accepted(self) -> None:
        dossier = self._dossier()
        assert resolve_cite("Smith, 2023", dossier) == ("p3", CITE_RESOLVED)
        assert resolve_cite("[Smith et al., 2023]", dossier) == ("p3", CITE_RESOLVED)

    def test_a_suffix_naming_no_entry_falls_back_to_the_base_key(self) -> None:
        # The judge invented `c`; there are only `a` and `b`. That is
        # still an ambiguous `[Zhang, 2024]`, not a resolution to `a`.
        assert resolve_cite("[Zhang, 2024c]", self._dossier()) == (
            None,
            CITE_AMBIGUOUS,
        )


class TestBuildFaithfulnessPrompt:
    """What the prompt carries, verbatim, and per source."""

    def test_report_appears_verbatim(self) -> None:
        papers, citations = _two_zhangs()
        prompt = _build_faithfulness_prompt(
            "REPORT BODY", build_faithfulness_sources(papers, citations)
        )
        assert "REPORT BODY" in prompt

    def test_each_source_appears_under_its_own_key_with_its_title(self) -> None:
        papers, citations = _two_zhangs()
        prompt = _build_faithfulness_prompt(
            "r", build_faithfulness_sources(papers, citations)
        )

        assert "[Zhang, 2024a]\nTitle: Retrieval bounds" in prompt
        assert "[Zhang, 2024b]\nTitle: Annotator drift" in prompt
        assert "ZHANG-ONE" in _dossier_block(prompt, "Zhang, 2024a")
        assert "ZHANG-TWO" not in _dossier_block(prompt, "Zhang, 2024a")

    def test_chunks_are_rendered_in_rank_order_when_supplied(self) -> None:
        papers, citations = _two_zhangs()
        prompt = _build_faithfulness_prompt(
            "r",
            build_faithfulness_sources(papers, citations, {"p1": ["top", "next"]}),
        )
        block = _dossier_block(prompt, "Zhang, 2024a")

        assert "(1) top" in block
        assert "(2) next" in block
        assert block.index("(1) top") < block.index("(2) next")

    def test_a_paper_without_chunks_says_so(self) -> None:
        papers, citations = _two_zhangs()
        prompt = _build_faithfulness_prompt(
            "r", build_faithfulness_sources(papers, citations)
        )
        assert "none available" in _dossier_block(prompt, "Zhang, 2024a")

    def test_empty_source_index_produces_no_sources_line(self) -> None:
        assert "(none provided)" in _build_faithfulness_prompt(
            "r", build_faithfulness_sources([], [])
        )


class TestCiteKeyFromString:
    """The legacy helper's contract, which a property test also pins."""

    def test_parses_bracketed_form(self) -> None:
        assert _cite_key_from_string("[Smith, 2023]") == ("smith", "2023")

    def test_parses_et_al_form(self) -> None:
        assert _cite_key_from_string("[Smith et al., 2023]") == ("smith", "2023")

    def test_parses_bare_form(self) -> None:
        # Judge sometimes returns without brackets — helper accepts both.
        assert _cite_key_from_string("Smith, 2023") == ("smith", "2023")

    def test_returns_none_on_gibberish(self) -> None:
        assert _cite_key_from_string("not a citation") is None
        assert _cite_key_from_string("") is None

    def test_year_suffix_dropped(self) -> None:
        assert _cite_key_from_string("[Smith, 2023a]") == ("smith", "2023")


class TestAggregateClaims:
    """How claims aggregate, and what leaves the denominator."""

    @staticmethod
    def _dossier() -> SourceDossier:
        papers = [
            _mk_paper(paper_id="p1", first_author="Jane Smith", abstract="abstract"),
            _mk_paper(paper_id="p2", first_author="John Doe", abstract="abstract"),
        ]
        citations = [
            _mk_citation(paper_id="p1", year="2023", first_author="Jane Smith"),
            _mk_citation(paper_id="p2", year="2024", first_author="John Doe"),
        ]
        return build_faithfulness_sources(papers, citations)

    def test_all_supported_scores_1(self) -> None:
        parsed = {
            "claims": [
                {"claim": "A", "cite": "[Smith, 2023]", "supported": True, "reason": "ok"},
                {"claim": "B", "cite": "[Doe, 2024]", "supported": True, "reason": "ok"},
            ]
        }
        result = _aggregate_claims(parsed, self._dossier())
        assert result["score"] == 1.0
        assert result["reason"] is None
        assert result["supported"] == 2
        assert result["unsupported"] == 0
        assert result["source_unavailable"] == 0

    def test_partial_support(self) -> None:
        parsed = {
            "claims": [
                {"claim": "A", "cite": "[Smith, 2023]", "supported": True, "reason": ""},
                {"claim": "B", "cite": "[Doe, 2024]", "supported": False, "reason": ""},
            ]
        }
        result = _aggregate_claims(parsed, self._dossier())
        assert result["score"] == 0.5
        assert result["supported"] == 1
        assert result["unsupported"] == 1

    def test_a_resolved_claim_records_the_paper_it_was_judged_against(self) -> None:
        parsed = {
            "claims": [
                {"claim": "A", "cite": "[Doe, 2024]", "supported": True, "reason": ""}
            ]
        }
        claim = _aggregate_claims(parsed, self._dossier())["claims"][0]
        assert claim["paper_id"] == "p2"
        assert claim["resolution"] == CITE_RESOLVED

    def test_source_unavailable_excluded_from_denominator(self) -> None:
        parsed = {
            "claims": [
                {"claim": "A", "cite": "[Smith, 2023]", "supported": True, "reason": ""},
                {"claim": "B", "cite": "[Ghost, 2020]", "supported": None, "reason": ""},
            ]
        }
        result = _aggregate_claims(parsed, self._dossier())
        assert result["score"] == 1.0
        assert result["supported"] == 1
        assert result["unsupported"] == 0
        assert result["source_unavailable"] == 1
        assert result["unresolved_citations"] == 1
        assert result["total_claims"] == 2

    def test_judge_says_supported_but_source_missing_forces_unavailable(self) -> None:
        # If judge claims a source it wasn't given, we override to None.
        parsed = {
            "claims": [
                {"claim": "B", "cite": "[Ghost, 2020]", "supported": True, "reason": ""},
            ]
        }
        result = _aggregate_claims(parsed, self._dossier())
        assert result["source_unavailable"] == 1
        assert result["supported"] == 0
        assert result["unsupported"] == 0

    def test_an_ambiguous_cite_abstains_and_is_counted(self) -> None:
        """EL-08's acceptance: never silently resolved."""
        papers, citations = _two_zhangs()
        dossier = build_faithfulness_sources(papers, citations)
        parsed = {
            "claims": [
                {"claim": "A", "cite": "[Zhang, 2024]", "supported": True, "reason": ""}
            ]
        }
        result = _aggregate_claims(parsed, dossier)

        assert result["claims"][0]["supported"] is None
        assert result["claims"][0]["paper_id"] is None
        assert result["claims"][0]["resolution"] == CITE_AMBIGUOUS
        assert result["ambiguous_citations"] == 1
        assert result["source_unavailable"] == 1
        assert result["collision_count"] == 2
        assert result["score"] is None
        assert result["reason"] == ALL_SOURCES_UNAVAILABLE

    def test_a_malformed_cite_is_counted_apart_from_an_unknown_one(self) -> None:
        parsed = {
            "claims": [
                {"claim": "A", "cite": "see above", "supported": True, "reason": ""},
                {"claim": "B", "cite": "[Ghost, 2020]", "supported": True, "reason": ""},
            ]
        }
        result = _aggregate_claims(parsed, self._dossier())
        assert result["malformed_citations"] == 1
        assert result["unresolved_citations"] == 1

    def test_no_claims_is_none_with_no_cited_claims(self) -> None:
        result = _aggregate_claims({"claims": []}, self._dossier())
        assert result["score"] is None
        assert result["reason"] == NO_CITED_CLAIMS
        assert result["total_claims"] == 0

    def test_claims_but_no_decidable_one_is_none_with_its_own_reason(self) -> None:
        # Distinct from the case above: the report *did* cite, and the
        # harness could not check any of it. That is a finding.
        parsed = {
            "claims": [
                {"claim": "A", "cite": "[Ghost, 2020]", "supported": True, "reason": ""}
            ]
        }
        result = _aggregate_claims(parsed, self._dossier())
        assert result["score"] is None
        assert result["reason"] == ALL_SOURCES_UNAVAILABLE
        assert result["total_claims"] == 1

    def test_malformed_claims_field_yields_empty_result(self) -> None:
        parsed: dict[str, Any] = {"claims": "not a list"}
        result = _aggregate_claims(parsed, self._dossier())
        assert result["total_claims"] == 0
        assert result["score"] is None
        assert result["reason"] == NO_CITED_CLAIMS

    def test_missing_claims_field_yields_empty_result(self) -> None:
        assert _aggregate_claims({}, self._dossier())["total_claims"] == 0

    def test_a_tuple_claims_field_is_read_like_a_list(self) -> None:
        parsed: dict[str, Any] = {
            "claims": (
                {"claim": "A", "cite": "[Smith, 2023]", "supported": True, "reason": "ok"},
            )
        }
        assert _aggregate_claims(parsed, self._dossier())["score"] == 1.0

    def test_bad_claim_entries_are_dropped(self) -> None:
        parsed = {
            "claims": [
                "not a dict",
                {"cite": "[Smith, 2023]"},  # missing claim text
                {"claim": ""},  # missing cite
                {"claim": "good", "cite": "[Smith, 2023]", "supported": True, "reason": ""},
            ]
        }
        result = _aggregate_claims(parsed, self._dossier())
        assert result["total_claims"] == 1
        assert result["supported"] == 1

    def test_non_bool_supported_field_treated_as_unavailable(self) -> None:
        parsed = {
            "claims": [
                {"claim": "A", "cite": "[Smith, 2023]", "supported": "yes", "reason": ""},
            ]
        }
        result = _aggregate_claims(parsed, self._dossier())
        # "yes" is not bool, not None -> treated as None (unavailable) so we
        # don't misattribute a text-y judge response as support.
        assert result["source_unavailable"] == 1

    def test_the_dossier_facts_ride_on_every_result(self) -> None:
        result = _aggregate_claims({"claims": []}, self._dossier())
        assert result["sources_total"] == 2
        assert result["sources_with_chunks"] == 0
        assert result["source_scope"] == SOURCE_SCOPE_ABSTRACT_ONLY
        assert result["collision_count"] == 0


class TestTheJudgeSeesTheRightSource:
    """EL-08's end-to-end acceptance, through a judge that actually reads."""

    def test_each_zhang_claim_is_judged_against_its_own_abstract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        papers, citations = _two_zhangs()

        def reading_judge(**kwargs: Any) -> dict[str, Any]:
            """Decide from the text under each cite key, like a judge."""
            prompt = str(kwargs["prompt"])
            return {
                "claims": [
                    {
                        "claim": "the retrieval bound is proved",
                        "cite": "[Zhang, 2024a]",
                        "supported": "ZHANG-ONE"
                        in _dossier_block(prompt, "Zhang, 2024a"),
                        "reason": "read from the block",
                    },
                    {
                        "claim": "annotator drift was measured",
                        "cite": "[Zhang, 2024b]",
                        "supported": "ZHANG-TWO"
                        in _dossier_block(prompt, "Zhang, 2024b"),
                        "reason": "read from the block",
                    },
                ]
            }

        monkeypatch.setattr(metrics_module, "call_llm_json", reading_judge)

        result = measure_faithfulness("a report body", papers, citations)

        assert result["score"] == 1.0
        assert [c["paper_id"] for c in result["claims"]] == ["p1", "p2"]
        assert all(c["supported"] is True for c in result["claims"])
        assert result["collision_count"] == 2
        assert result["sources_total"] == 2

    def test_both_papers_survive_the_join(self) -> None:
        # The defect, stated as an assertion rather than as prose: the
        # old `(surname, year)` join kept one entry for two papers, so a
        # `[Zhang, 2024]` claim about the first was checked against the
        # second's abstract. The dossier keeps both, under keys that tell
        # them apart.
        papers, citations = _two_zhangs()
        dossier = build_faithfulness_sources(papers, citations)
        assert [source["cite_key"] for source in dossier["sources"]] == [
            "Zhang, 2024a",
            "Zhang, 2024b",
        ]


class TestTheJudgeSeesWhatTheWriterSaw:
    """EL-09: the same claim, scored two ways, by scope alone."""

    @staticmethod
    def _body_only_judge(**kwargs: Any) -> dict[str, Any]:
        """Support the claim only if the body sentence was provided."""
        block = _dossier_block(str(kwargs["prompt"]), "Smith, 2023")
        return {
            "claims": [
                {
                    "claim": "the ablation removed 12 points",
                    "cite": "[Smith, 2023]",
                    "supported": "ABLATION-12-POINTS" in block,
                    "reason": "from the provided material",
                }
            ]
        }

    @staticmethod
    def _papers() -> tuple[list[PaperMetadata], list[Citation]]:
        papers = [
            _mk_paper(
                paper_id="p1",
                first_author="Jane Smith",
                abstract="We study ablations. (The number is not in the abstract.)",
            )
        ]
        citations = [
            _mk_citation(paper_id="p1", year="2023", first_author="Jane Smith")
        ]
        return papers, citations

    def test_a_body_only_claim_is_supported_when_chunks_are_supplied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(metrics_module, "call_llm_json", self._body_only_judge)
        papers, citations = self._papers()

        result = measure_faithfulness(
            "a report body",
            papers,
            citations,
            {"p1": ["In the results, ABLATION-12-POINTS was observed."]},
        )

        assert result["claims"][0]["supported"] is True
        assert result["score"] == 1.0
        assert result["source_scope"] == SOURCE_SCOPE_ABSTRACT_AND_CHUNKS
        assert result["sources_with_chunks"] == 1

    def test_the_same_claim_is_unsupported_on_abstracts_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(metrics_module, "call_llm_json", self._body_only_judge)
        papers, citations = self._papers()

        result = measure_faithfulness("a report body", papers, citations)

        assert result["claims"][0]["supported"] is False
        assert result["score"] == 0.0
        # The scope is on the result, so a reader can tell "the report
        # was wrong" from "the harness could not see the evidence".
        assert result["source_scope"] == SOURCE_SCOPE_ABSTRACT_ONLY
        assert result["sources_with_chunks"] == 0


class TestMeasureFaithfulness:
    """The whole path, including the short circuit and a missing source."""

    def test_empty_report_short_circuits_without_llm_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = {"n": 0}

        def _no(**_: Any) -> dict[str, Any]:
            called["n"] += 1
            return {}

        monkeypatch.setattr(metrics_module, "call_llm_json", _no)

        result = measure_faithfulness("", [], [])
        # ADR 0100: a run that produced no report is not a perfect one.
        assert result["score"] is None
        assert result["reason"] == EMPTY_REPORT
        assert result["total_claims"] == 0
        assert result["judge"] is None
        assert called["n"] == 0

    def test_end_to_end_with_stubbed_judge(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        papers = [
            _mk_paper(
                paper_id="p1",
                first_author="Jane Smith",
                abstract="Smith 2023 shows X.",
            ),
            _mk_paper(
                paper_id="p2",
                first_author="John Doe",
                abstract="Doe 2024 shows Y.",
            ),
        ]
        citations = [
            _mk_citation(paper_id="p1", year="2023", first_author="Jane Smith"),
            _mk_citation(paper_id="p2", year="2024", first_author="John Doe"),
        ]

        captured: dict[str, Any] = {}

        def fake_judge(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "claims": [
                    {
                        "claim": "X is shown by Smith.",
                        "cite": "[Smith, 2023]",
                        "supported": True,
                        "reason": "Smith 2023 shows X",
                    },
                    {
                        "claim": "Y is disproven by Doe.",
                        "cite": "[Doe, 2024]",
                        "supported": False,
                        "reason": "abstract only shows Y",
                    },
                ]
            }

        monkeypatch.setattr(metrics_module, "call_llm_json", fake_judge)

        result = measure_faithfulness("a report body", papers, citations)

        assert result["total_claims"] == 2
        assert result["supported"] == 1
        assert result["unsupported"] == 1
        assert result["score"] == 0.5
        # Judge prompt should include both dossier entries.
        assert "[Smith, 2023]" in captured["prompt"]
        assert "[Doe, 2024]" in captured["prompt"]
        assert "Smith 2023 shows X." in captured["prompt"]
        assert captured["max_tokens"] == 8192

    def test_end_to_end_source_missing_marks_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No papers or citations provided at all.
        def fake_judge(**_: Any) -> dict[str, Any]:
            return {
                "claims": [
                    {
                        "claim": "Some claim",
                        "cite": "[Ghost, 2020]",
                        "supported": True,
                        "reason": "hallucinated support",
                    }
                ]
            }

        monkeypatch.setattr(metrics_module, "call_llm_json", fake_judge)

        result = measure_faithfulness("something", [], [])
        # Even though judge said supported=True, no source -> forced to None,
        # and the empty denominator is now `None` rather than a free 1.0.
        assert result["source_unavailable"] == 1
        assert result["supported"] == 0
        assert result["score"] is None
        assert result["reason"] == ALL_SOURCES_UNAVAILABLE

    def test_the_judge_call_carries_its_schema_and_its_own_temperature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EL-11: the judge does not sample at the workflow's setting."""
        seen: dict[str, Any] = {}

        def fake_judge(**kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return {"claims": []}

        monkeypatch.setattr(metrics_module, "call_llm_json", fake_judge)
        monkeypatch.setattr(
            metrics_module,
            "settings",
            Settings(llm_temperature=0.7, eval_judge_temperature=0.0),
        )

        result = measure_faithfulness("a report", [], [])

        assert seen["schema"] is FaithfulnessJudgeOutput
        assert seen["temperature"] == 0.0
        assert result["judge"] is not None
        assert result["judge"]["schema"] == "FaithfulnessJudgeOutput"
        assert result["judge"]["model"] == seen["model_name"]


class TestReturnedTypes:
    """The result's keys are exactly the ones its type declares."""

    def test_faithfulness_result_keys(self) -> None:
        r = measure_faithfulness("", [], [])
        assert set(FaithfulnessResult.__required_keys__) == set(r.keys())

    def test_claim_judgement_keys(self) -> None:
        papers = [_mk_paper(paper_id="p1", first_author="Jane Smith")]
        citations = [_mk_citation(paper_id="p1", year="2023", first_author="Jane Smith")]
        r = _aggregate_claims(
            {
                "claims": [
                    {
                        "claim": "c",
                        "cite": "[Smith, 2023]",
                        "supported": True,
                        "reason": "",
                    }
                ]
            },
            build_faithfulness_sources(papers, citations),
        )
        assert set(ClaimJudgement.__required_keys__) == set(r["claims"][0].keys())


class TestTheJudgeIsPinned:
    """ADR 0070: the judge must not follow the product model.

    Before this, `measure_faithfulness` passed no `model_name`, so
    `src/llm.py` fell through to `settings.anthropic_model` — upgrading
    the product silently changed the grader.
    """

    def test_the_judge_call_names_the_pinned_eval_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def fake_judge(**kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return {"claims": []}

        monkeypatch.setattr(metrics_module, "call_llm_json", fake_judge)
        monkeypatch.setattr(
            provenance_module,
            "settings",
            Settings(anthropic_model="product-v2", eval_judge_model="judge-v1"),
        )

        measure_faithfulness("a report", [], [])

        assert seen["model_name"] == "judge-v1"
        assert seen["model_name"] != "product-v2"

    def test_the_judge_model_is_read_per_call_not_at_import(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[str] = []

        def fake_judge(**kwargs: Any) -> dict[str, Any]:
            seen.append(str(kwargs["model_name"]))
            return {"claims": []}

        monkeypatch.setattr(metrics_module, "call_llm_json", fake_judge)
        for model in ("judge-a", "judge-b"):
            monkeypatch.setattr(
                provenance_module, "settings", Settings(eval_judge_model=model)
            )
            measure_faithfulness("a report", [], [])
        assert seen == ["judge-a", "judge-b"]
