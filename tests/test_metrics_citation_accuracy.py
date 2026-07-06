"""Unit tests for the citation-accuracy metric.

Pure logic — no LLM, no I/O. Covers the tag regex, first-author
normalization, deduplication, year-suffix handling, and the empty-input
corner cases.
"""

from src.eval.metrics import (
    CitationAccuracyResult,
    _normalize_first_author,
    measure_citation_accuracy,
)
from src.graph.state import Citation


def _mk_citation(
    lastname: str, year: str, *, first_name: str = "First"
) -> Citation:
    return Citation(
        paper_id=f"arxiv:{lastname}-{year}",
        title=f"{lastname} paper",
        authors=[f"{first_name} {lastname}"],
        year=year,
        url=f"http://arxiv.org/abs/{lastname}-{year}",
    )


class TestNormalizeFirstAuthor:
    def test_single_author(self) -> None:
        assert _normalize_first_author("Smith") == "smith"

    def test_lowercases_mixed_case(self) -> None:
        assert _normalize_first_author("McDonald") == "mcdonald"

    def test_et_al_stripped(self) -> None:
        assert _normalize_first_author("Smith et al.") == "smith"
        assert _normalize_first_author("Smith et al") == "smith"
        assert _normalize_first_author("Smith et. al.") == "smith"

    def test_two_author_and_style_keeps_first(self) -> None:
        assert _normalize_first_author("Smith and Jones") == "smith"

    def test_full_name_takes_last_token(self) -> None:
        # If the author field is "Jane Doe" (full name accidentally passed in),
        # the last whitespace token is the last name.
        assert _normalize_first_author("Jane Doe") == "doe"

    def test_empty_returns_empty(self) -> None:
        assert _normalize_first_author("") == ""
        assert _normalize_first_author("   ") == ""


class TestMeasureCitationAccuracy:
    def test_all_citations_resolve(self) -> None:
        report = "As shown by [Smith, 2023], the method works."
        citations = [_mk_citation("Smith", "2023")]

        result = measure_citation_accuracy(report, citations)

        assert result["score"] == 1.0
        assert result["total_citations"] == 1
        assert result["resolved"] == 1
        assert result["unresolved"] == []

    def test_no_citations_in_report_returns_perfect_and_zero_total(self) -> None:
        report = "This report has no citations."
        result = measure_citation_accuracy(report, [_mk_citation("Smith", "2023")])
        assert result["score"] == 1.0
        assert result["total_citations"] == 0
        assert result["resolved"] == 0

    def test_partial_resolution(self) -> None:
        report = (
            "Both [Smith, 2023] and [Ghost, 2020] contributed to this line."
        )
        citations = [_mk_citation("Smith", "2023")]  # Ghost is not in the list

        result = measure_citation_accuracy(report, citations)

        assert result["total_citations"] == 2
        assert result["resolved"] == 1
        assert result["score"] == 0.5
        assert result["unresolved"] == ["[Ghost, 2020]"]

    def test_et_al_citation_resolves(self) -> None:
        report = "See [Doe et al., 2024]."
        citations = [
            Citation(
                paper_id="p1",
                title="A",
                authors=["Jane Doe", "John Roe", "Kim Poe"],
                year="2024",
                url="u",
            )
        ]
        assert measure_citation_accuracy(report, citations)["score"] == 1.0

    def test_two_author_and_style_resolves_on_first_author(self) -> None:
        report = "See [Smith and Jones, 2023]."
        citations = [_mk_citation("Smith", "2023")]
        assert measure_citation_accuracy(report, citations)["score"] == 1.0

    def test_year_suffix_in_report_stripped(self) -> None:
        # Report writes [Smith, 2023a]; citation list stores year "2023".
        report = "See [Smith, 2023a] and [Smith, 2023b]."
        citations = [_mk_citation("Smith", "2023")]
        # Both cite the same paper — dedup to one entry, which resolves.
        result = measure_citation_accuracy(report, citations)
        assert result["total_citations"] == 1
        assert result["score"] == 1.0

    def test_duplicate_citations_counted_once(self) -> None:
        report = "See [Smith, 2023]. Also [Smith, 2023]. And once more [Smith, 2023]."
        citations = [_mk_citation("Smith", "2023")]
        result = measure_citation_accuracy(report, citations)
        assert result["total_citations"] == 1
        assert result["resolved"] == 1

    def test_multiple_distinct_citations_dedup_per_key(self) -> None:
        report = (
            "First [Smith, 2023], then [Jones, 2022], then [Smith et al., 2023]."
        )
        citations = [
            _mk_citation("Smith", "2023"),
            _mk_citation("Jones", "2022"),
        ]
        result = measure_citation_accuracy(report, citations)
        # [Smith, 2023] and [Smith et al., 2023] normalize to the same key.
        assert result["total_citations"] == 2
        assert result["resolved"] == 2
        assert result["score"] == 1.0

    def test_empty_citations_all_unresolved(self) -> None:
        report = "See [Smith, 2023] and [Jones, 2022]."
        result = measure_citation_accuracy(report, [])
        assert result["score"] == 0.0
        assert result["total_citations"] == 2
        assert result["resolved"] == 0
        assert set(result["unresolved"]) == {"[Smith, 2023]", "[Jones, 2022]"}

    def test_returned_type_is_citation_accuracy_result(self) -> None:
        result = measure_citation_accuracy("", [])
        # TypedDicts are dicts at runtime; check shape.
        assert set(CitationAccuracyResult.__required_keys__) == set(result.keys())

    def test_case_insensitive_author_matching(self) -> None:
        report = "See [SMITH, 2023]."
        citations = [_mk_citation("smith", "2023")]  # lowercased citation
        assert measure_citation_accuracy(report, citations)["score"] == 1.0
