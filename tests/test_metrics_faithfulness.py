"""Unit tests for the faithfulness metric.

Pure helpers (`build_source_index`, `_build_faithfulness_prompt`,
`_aggregate_claims`, `_cite_key_from_string`) are tested directly.
The full `measure_faithfulness` path is exercised once with
`call_llm_json` monkeypatched — no real Claude calls, no network.
"""

from typing import Any

import pytest

from src.eval import metrics as metrics_module
from src.eval.metrics import (
    ClaimJudgement,
    FaithfulnessResult,
    _aggregate_claims,
    _build_faithfulness_prompt,
    build_source_index,
    _cite_key_from_string,
    measure_faithfulness,
)
from src.graph.state import Citation, PaperMetadata


def _mk_paper(
    *, paper_id: str, first_author: str, abstract: str = "Some abstract."
) -> PaperMetadata:
    return PaperMetadata(
        id=paper_id,
        title="Paper title",
        authors=[first_author, "Second Author"],
        abstract=abstract,
        url=paper_id,
        pdf_url=f"{paper_id}.pdf",
    )


def _mk_citation(*, paper_id: str, year: str, first_author: str) -> Citation:
    return Citation(
        paper_id=paper_id,
        title="Paper title",
        authors=[first_author, "Second Author"],
        year=year,
        url=paper_id,
    )


class TestBuildSourceIndex:
    def test_joins_papers_and_citations_on_paper_id(self) -> None:
        papers = [
            _mk_paper(paper_id="p1", first_author="Jane Smith", abstract="A1"),
            _mk_paper(paper_id="p2", first_author="John Doe", abstract="A2"),
        ]
        citations = [
            _mk_citation(paper_id="p1", year="2023", first_author="Jane Smith"),
            _mk_citation(paper_id="p2", year="2024", first_author="John Doe"),
        ]
        index = build_source_index(papers, citations)
        assert index == {("smith", "2023"): "A1", ("doe", "2024"): "A2"}

    def test_paper_without_matching_citation_is_omitted(self) -> None:
        papers = [
            _mk_paper(paper_id="p1", first_author="Jane Smith"),
            _mk_paper(paper_id="uncited", first_author="Nobody Cited"),
        ]
        citations = [_mk_citation(paper_id="p1", year="2023", first_author="Jane Smith")]
        index = build_source_index(papers, citations)
        assert ("cited", "0000") not in index
        assert list(index.keys()) == [("smith", "2023")]

    def test_year_suffix_stripped(self) -> None:
        papers = [_mk_paper(paper_id="p1", first_author="Jane Smith")]
        citations = [
            _mk_citation(paper_id="p1", year="2023a", first_author="Jane Smith")
        ]
        assert build_source_index(papers, citations) == {
            ("smith", "2023"): "Some abstract."
        }

    def test_paper_without_authors_omitted(self) -> None:
        papers = [
            PaperMetadata(
                id="p1",
                title="t",
                authors=[],
                abstract="a",
                url="u",
                pdf_url="p",
            )
        ]
        citations = [_mk_citation(paper_id="p1", year="2023", first_author="X")]
        assert build_source_index(papers, citations) == {}

    def test_citation_without_year_omitted(self) -> None:
        papers = [_mk_paper(paper_id="p1", first_author="Jane Smith")]
        citations = [_mk_citation(paper_id="p1", year="", first_author="Jane Smith")]
        assert build_source_index(papers, citations) == {}


class TestBuildFaithfulnessPrompt:
    def test_report_appears_verbatim(self) -> None:
        prompt = _build_faithfulness_prompt(
            "REPORT BODY", {("smith", "2023"): "abstract text"}
        )
        assert "REPORT BODY" in prompt

    def test_each_source_appears_with_its_cite_key(self) -> None:
        source_index = {
            ("smith", "2023"): "smith abstract",
            ("doe", "2024"): "doe abstract",
        }
        prompt = _build_faithfulness_prompt("r", source_index)
        assert "[Smith, 2023]" in prompt
        assert "[Doe, 2024]" in prompt
        assert "smith abstract" in prompt
        assert "doe abstract" in prompt

    def test_empty_source_index_produces_no_sources_line(self) -> None:
        prompt = _build_faithfulness_prompt("r", {})
        assert "(none provided)" in prompt


class TestCiteKeyFromString:
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
    _SOURCE_IDX = {("smith", "2023"): "abstract", ("doe", "2024"): "abstract"}

    def test_all_supported_scores_1(self) -> None:
        parsed = {
            "claims": [
                {"claim": "A", "cite": "[Smith, 2023]", "supported": True, "reason": "ok"},
                {"claim": "B", "cite": "[Doe, 2024]", "supported": True, "reason": "ok"},
            ]
        }
        result = _aggregate_claims(parsed, self._SOURCE_IDX)
        assert result["score"] == 1.0
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
        result = _aggregate_claims(parsed, self._SOURCE_IDX)
        assert result["score"] == 0.5
        assert result["supported"] == 1
        assert result["unsupported"] == 1

    def test_source_unavailable_excluded_from_denominator(self) -> None:
        parsed = {
            "claims": [
                {"claim": "A", "cite": "[Smith, 2023]", "supported": True, "reason": ""},
                {"claim": "B", "cite": "[Ghost, 2020]", "supported": None, "reason": ""},
            ]
        }
        result = _aggregate_claims(parsed, self._SOURCE_IDX)
        # supported=1 / (supported=1 + unsupported=0) = 1.0, unavailable reported separately.
        assert result["score"] == 1.0
        assert result["supported"] == 1
        assert result["unsupported"] == 0
        assert result["source_unavailable"] == 1
        assert result["total_claims"] == 2

    def test_judge_says_supported_but_source_missing_forces_unavailable(self) -> None:
        # If judge claims a source it wasn't given, we override to None.
        parsed = {
            "claims": [
                # Ghost isn't in source_idx; judge said "supported: true" but
                # we can't trust that.
                {"claim": "B", "cite": "[Ghost, 2020]", "supported": True, "reason": ""},
            ]
        }
        result = _aggregate_claims(parsed, self._SOURCE_IDX)
        assert result["source_unavailable"] == 1
        assert result["supported"] == 0
        assert result["unsupported"] == 0

    def test_malformed_claims_field_yields_empty_result(self) -> None:
        parsed: dict[str, Any] = {"claims": "not a list"}
        result = _aggregate_claims(parsed, self._SOURCE_IDX)
        assert result["total_claims"] == 0
        assert result["score"] == 1.0  # nothing to judge => trivially perfect

    def test_missing_claims_field_yields_empty_result(self) -> None:
        result = _aggregate_claims({}, self._SOURCE_IDX)
        assert result["total_claims"] == 0

    def test_bad_claim_entries_are_dropped(self) -> None:
        parsed = {
            "claims": [
                "not a dict",
                {"cite": "[Smith, 2023]"},  # missing claim text
                {"claim": ""},  # missing cite
                {"claim": "good", "cite": "[Smith, 2023]", "supported": True, "reason": ""},
            ]
        }
        result = _aggregate_claims(parsed, self._SOURCE_IDX)
        assert result["total_claims"] == 1
        assert result["supported"] == 1

    def test_non_bool_supported_field_treated_as_unavailable(self) -> None:
        parsed = {
            "claims": [
                {"claim": "A", "cite": "[Smith, 2023]", "supported": "yes", "reason": ""},
            ]
        }
        result = _aggregate_claims(parsed, self._SOURCE_IDX)
        # "yes" is not bool, not None -> treated as None (unavailable) so we
        # don't misattribute a text-y judge response as support.
        assert result["source_unavailable"] == 1


class TestMeasureFaithfulness:
    def test_empty_report_short_circuits_without_llm_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = {"n": 0}

        def _no(**_: Any) -> dict[str, Any]:
            called["n"] += 1
            return {}

        monkeypatch.setattr(metrics_module, "call_llm_json", _no)

        result = measure_faithfulness("", [], [])
        assert result["score"] == 1.0
        assert result["total_claims"] == 0
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

        def fake_judge(
            *, prompt: str, system_prompt: str, max_tokens: int
        ) -> dict[str, Any]:
            captured["prompt"] = prompt
            captured["max_tokens"] = max_tokens
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
        # Even though judge said supported=True, no source -> forced to None.
        assert result["source_unavailable"] == 1
        assert result["supported"] == 0
        assert result["score"] == 1.0  # 0/0 denom -> 1.0 (nothing judgeable)


class TestReturnedTypes:
    def test_faithfulness_result_keys(self) -> None:
        r = measure_faithfulness("", [], [])
        assert set(FaithfulnessResult.__required_keys__) == set(r.keys())

    def test_claim_judgement_keys(self) -> None:
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
            {("smith", "2023"): "abstract"},
        )
        assert set(ClaimJudgement.__required_keys__) == set(r["claims"][0].keys())
