"""Proof that the deterministic groundedness check measures the agent.

Three things are being defended here, and they are not the same thing:

1. **The metric is honest.** Zero citations is `None` with a reason, not
   `1.0`. `TestZeroIsNotAPerfectScore` puts the new metric side by side
   with `metrics.measure_citation_accuracy` on the same input so the
   defect being fixed is visible in the assertion rather than only in an
   ADR.
2. **The normalization is exactly what the docs say.** Every rule in the
   module docstring's table has its own test, and
   `TestWhatIsNotNormalized` fixes the other edge: a changed word, a
   changed number or a reordered clause must fail. A quote check with a
   generous matcher is a quote check that measures nothing.
3. **Nothing here can reach a model or a socket.** Asserted structurally
   (`TestNoJudgeNoNetwork`), not by trusting the harness.

The fixture corpus (`tests/fixtures/groundedness/run.json`) is
hand-authored and says so; its `_readme` lists every PDF-extraction
artefact planted in it and why.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from src.eval import groundedness as g
from src.eval.metrics import measure_citation_accuracy
from src.eval.provenance import PROVENANCE_KEY, RunProvenance
from src.graph.state import Citation, EvidenceClaim, PaperMetadata

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "groundedness" / "run.json"

#: The normalization contract, locked. Changing `NORMALIZATION_SPEC`
#: without bumping `GROUNDEDNESS_CHECK_VERSION` fails here — the same
#: mechanism `tests/test_eval_rubric_versions.py` applies to judge
#: prompts, applied to a check that has no prompt. Rows scored either
#: side of a spec change are not comparable, and this is what makes
#: somebody say so.
LOCKED_SPEC_VERSION = "1.0.0"
LOCKED_SPEC_DIGEST = "a8abd511c0e11b6d040314fbb3cd2d6850f53a49591982de47d9c5028cebf1f3"


def _fixture() -> dict[str, Any]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _papers() -> list[PaperMetadata]:
    return [PaperMetadata(**paper) for paper in _fixture()["papers"]]


def _citations() -> list[Citation]:
    return [Citation(**citation) for citation in _fixture()["citations"]]


def _paper(paper_id: str, abstract: str = "an abstract") -> PaperMetadata:
    return PaperMetadata(
        id=paper_id,
        title="t",
        authors=["A B"],
        abstract=abstract,
        url=paper_id,
        pdf_url=paper_id,
    )


def _citation(paper_id: str, author: str = "Rosen", year: str = "2024") -> Citation:
    return Citation(
        paper_id=paper_id, title="t", authors=[f"X {author}"], year=year, url=paper_id
    )


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


class TestCanonicalArxivId:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2311.09000", "arxiv:2311.09000"),
            ("arXiv:2311.09000", "arxiv:2311.09000"),
            ("arxiv: 2311.09000", "arxiv:2311.09000"),
            ("http://arxiv.org/abs/2311.09000", "arxiv:2311.09000"),
            ("https://www.arxiv.org/abs/2311.09000", "arxiv:2311.09000"),
            ("https://arxiv.org/pdf/2311.09000v1.pdf", "arxiv:2311.09000"),
            ("  arxiv:2311.09000v12  ", "arxiv:2311.09000"),
            # Six sequence digits: arXiv issues four or five.
            ("2311.090001", None),
        ],
    )
    def test_the_surface_forms_this_repository_actually_produces(
        self, raw: str, expected: str | None
    ) -> None:
        assert g.canonical_arxiv_id(raw) == expected

    def test_the_version_suffix_is_stripped_so_v1_and_v2_are_one_paper(self) -> None:
        """A citation to v2 of a paper fetched at v1 is not a fabrication.

        Treating it as one would make the metric measure arXiv's
        revision history instead of the agent's honesty.
        """
        assert g.canonical_arxiv_id("2311.09000v2") == g.canonical_arxiv_id(
            "2311.09000"
        )

    def test_old_style_identifiers_resolve_and_fold_case(self) -> None:
        assert g.canonical_arxiv_id("cs.CL/0301001") == "arxiv:cs.cl/0301001"
        assert g.canonical_arxiv_id("arXiv:math/0309136") == "arxiv:math/0309136"
        assert g.canonical_arxiv_id("cs.cl/0301001") == g.canonical_arxiv_id(
            "CS.CL/0301001"
        )

    @pytest.mark.parametrize(
        "raw",
        ["", "   ", "99.9", "24x1.0000", "2311.900", "s2:9a1f", "not an id at all"],
    )
    def test_a_non_identifier_is_rejected_rather_than_coerced(self, raw: str) -> None:
        assert g.canonical_arxiv_id(raw) is None

    def test_a_non_arxiv_paper_keeps_its_own_identity(self) -> None:
        """Semantic Scholar results are real retrieved papers.

        `src/tools/semantic_scholar.py` gives them an `s2:` id. A
        citation to one must resolve, so `paper_key` indexes them under
        their raw id rather than discarding them for not being arXiv.
        """
        assert g.paper_key("s2:9a1f") == "s2:9a1f"
        assert g.paper_key("http://arxiv.org/abs/2311.09000") == "arxiv:2311.09000"


class TestIdentifierExtraction:
    def test_prefixed_and_url_forms_are_both_found(self) -> None:
        report = (
            "See arXiv:2311.09000 and https://arxiv.org/abs/2305.13269 for the "
            "background."
        )
        found = {item["canonical"] for item in g.extract_report_identifiers(report)}
        assert found == {"arxiv:2311.09000", "arxiv:2305.13269"}

    def test_a_bare_number_in_prose_is_not_treated_as_a_citation(self) -> None:
        """The false-positive cost is not worth the extra recall.

        A report that writes a number without saying it is an arXiv id
        has not made a checkable claim, and numeric text is common.
        """
        assert g.extract_report_identifiers("the ratio was 2311.09000 to one") == []

    def test_prose_after_the_prefix_is_not_a_fabricated_identifier(self) -> None:
        assert g.extract_report_identifiers("arXiv: a preprint server") == []

    def test_a_malformed_identifier_after_the_prefix_is_still_extracted(self) -> None:
        """Claiming an arXiv id and not producing one is a citation defect.

        Dropping it silently would let the worst-formed citations escape
        the metric entirely.
        """
        found = g.extract_report_identifiers("catalogued as arXiv:24x1.0000 there")
        assert len(found) == 1
        assert found[0]["raw"] == "24x1.0000"
        assert found[0]["canonical"] is None

    def test_identifiers_inside_code_spans_are_ignored(self) -> None:
        report = 'An example: `{"paper_id": "arXiv:2311.09000"}` in the payload.'
        assert g.extract_report_identifiers(report) == []

    def test_the_citation_list_is_its_own_surface(self) -> None:
        found = g.extract_citation_list_identifiers(
            [_citation("http://arxiv.org/abs/2401.00001")]
        )
        assert found[0]["origin"] == "citation_list"
        assert found[0]["locator"] == "citations[0].paper_id"
        assert found[0]["canonical"] == "arxiv:2401.00001"

    def test_the_url_is_read_only_when_paper_id_is_empty(self) -> None:
        entry = Citation(
            paper_id="",
            title="t",
            authors=["A"],
            year="2024",
            url="http://arxiv.org/abs/2401.00002",
        )
        found = g.extract_citation_list_identifiers([entry])
        assert [item["locator"] for item in found] == ["citations[0].url"]

    def test_an_entry_asserting_no_identifier_is_not_a_claim(self) -> None:
        entry = Citation(paper_id="", title="t", authors=["A"], year="2024", url="")
        assert g.extract_citation_list_identifiers([entry]) == []


# ---------------------------------------------------------------------------
# Normalization — one test per documented rule
# ---------------------------------------------------------------------------


class TestNormalizationRules:
    """Each rule in the module docstring's table, proved on its own."""

    def test_rule_1_format_characters_and_soft_hyphens_are_removed(self) -> None:
        # ZERO WIDTH SPACE, SOFT HYPHEN, BOM — all invisible, none of
        # them a difference a reader could see.
        assert g.fold("inter­national​ test﻿") == "international test"

    def test_rule_2_nfkc_folds_the_ligatures_a_tex_pdf_extracts(self) -> None:
        assert g.fold("ﬁne-tuned") == "fine-tuned"
        assert g.fold("diﬀers") == "differs"
        assert g.fold("ﬂuency") == "fluency"
        assert g.fold("and so on…") == "and so on..."

    def test_rule_3_a_hyphen_at_a_line_break_is_joined(self) -> None:
        assert g.fold("inter-\nnational corpus") == "international corpus"
        assert g.fold("inter-\n   national corpus") == "international corpus"

    def test_rule_3_leaves_a_line_break_before_a_capital_alone(self) -> None:
        """`Anglo-\\nAmerican` is a compound, not a broken word.

        The rule cannot tell the two apart in general; requiring a
        lower-case continuation is the conservative half, and the
        skeleton level catches whatever this misses.
        """
        assert g.fold("Anglo-\nAmerican") == "anglo-\namerican".replace("\n", " ")

    def test_rule_4_curly_quotes_and_primes_fold_to_ascii(self) -> None:
        assert g.fold("“closed-book”") == '"closed-book"'
        assert g.fold("the model’s output") == "the model's output"
        assert g.fold("«cited»") == '"cited"'

    def test_rule_5_every_dash_code_point_folds_to_a_hyphen(self) -> None:
        for dash in "‐‑‒–—―−":
            assert g.fold(f"12.4{dash}point") == "12.4-point"

    def test_rule_6_every_whitespace_run_collapses_to_one_space(self) -> None:
        assert g.fold("benchmark suite") == "benchmark suite"
        assert g.fold("a\t\tb\n\nc de") == "a b c d e"
        assert g.fold("  padded  ") == "padded"

    def test_rule_7_case_is_folded(self) -> None:
        assert g.fold("State-Of-The-Art") == g.fold("state-of-the-art")

    def test_the_skeleton_level_drops_hyphens_spaces_and_punctuation(self) -> None:
        assert g.skeleton("state-of-the-art, decoding.") == "stateoftheartdecoding"

    def test_the_skeleton_level_is_what_survives_a_broken_compound(self) -> None:
        """`state-\\nof-the-art` is exactly what rule 3 mangles.

        `fold` turns it into `state-oftheart`, which does not equal
        `state-of-the-art`. Removing hyphens outright makes the two
        identical, which is why the skeleton level exists at all.
        """
        assert g.fold("state-\nof-the-art") != g.fold("state-of-the-art")
        assert g.skeleton("state-\nof-the-art") == g.skeleton("state-of-the-art")


class TestWhatIsNotNormalized:
    """The other edge. A matcher that forgives everything measures nothing."""

    SOURCE = "the model attains a 12.4-point improvement over the baseline"

    def test_one_changed_word_fails_at_every_level(self) -> None:
        assert (
            g.locate_quote(
                "the model attains a 12.4-point regression over the baseline",
                self.SOURCE,
            )
            is None
        )

    def test_one_changed_number_fails_at_every_level(self) -> None:
        assert (
            g.locate_quote(
                "the model attains a 13.4-point improvement over the baseline",
                self.SOURCE,
            )
            is None
        )

    def test_reordered_words_fail_at_every_level(self) -> None:
        assert (
            g.locate_quote(
                "a 12.4-point improvement the model attains over the baseline",
                self.SOURCE,
            )
            is None
        )

    def test_a_dropped_word_fails_at_every_level(self) -> None:
        assert (
            g.locate_quote("the model attains a improvement over the baseline", self.SOURCE)
            is None
        )


class TestLocateQuote:
    def test_the_weakest_level_that_matched_is_the_one_reported(self) -> None:
        source = "The fine-tuned model\nattains a gain."
        assert g.locate_quote("The fine-tuned model", source) == "exact"
        assert g.locate_quote("the fine-tuned model attains", source) == "folded"
        assert g.locate_quote("the fine tuned model attains", source) == "skeleton"

    def test_a_quote_spanning_a_line_of_the_pdf_needs_no_more_than_folding(
        self,
    ) -> None:
        """The single most common reason a naive check fails.

        `page.get_text()` returns a hard newline at every rendered line
        break, so a quotation of more than a few words practically never
        matches as a raw substring.
        """
        source = "State-of-the-art decoding\nreduces unsupported claims."
        assert g.locate_quote("State-of-the-art decoding reduces", source) is not None
        assert "State-of-the-art decoding reduces" not in source

    def test_an_elided_quote_is_matched_fragment_by_fragment_in_order(self) -> None:
        source = "we report a large gain, the largest we measured, with no loss"
        assert g.locate_quote("we report a large gain ... with no loss", source)
        assert g.locate_quote("we report a large gain […] with no loss", source)

    def test_an_elided_quote_whose_fragments_are_out_of_order_is_not_found(
        self,
    ) -> None:
        source = "we report a large gain, the largest we measured, with no loss"
        assert g.locate_quote("with no loss ... we report a large gain", source) is None

    def test_an_empty_quote_is_never_located(self) -> None:
        assert g.locate_quote("   ", "anything at all") is None

    def test_a_fragment_that_normalizes_away_carries_no_evidence(self) -> None:
        """`"gain ... — ... with no loss"` must not become a wildcard.

        A fragment of pure punctuation projects to the empty string. It
        is skipped rather than matched, and the surviving fragments still
        have to appear in order, so skipping cannot invent a match.
        """
        source = "we report a large gain, the largest we measured, with no loss"
        assert g.locate_quote("we report a large gain ... — ... with no loss", source)
        assert g.locate_quote("with no loss ... — ... we report a large gain", source) is None


# ---------------------------------------------------------------------------
# Quote extraction
# ---------------------------------------------------------------------------


class TestQuoteExtraction:
    def test_a_short_quoted_span_is_terminology_not_a_quotation(self) -> None:
        """Scare quotes and terminology must not enter the denominator.

        Checking `the "attention" mechanism` against a paper measures the
        report's punctuation habits.
        """
        report = 'The "attention" mechanism and its "hallucination" problem.'
        assert g.extract_quotes(report) == []

    def test_a_span_of_the_minimum_length_is_a_quotation(self) -> None:
        words = " ".join(f"w{n}" for n in range(g.MIN_QUOTE_WORDS))
        assert len(g.extract_quotes(f'They wrote "{words}" in the paper.')) == 1
        shorter = " ".join(f"w{n}" for n in range(g.MIN_QUOTE_WORDS - 1))
        assert g.extract_quotes(f'They wrote "{shorter}" in the paper.') == []

    def test_curly_quotes_are_extracted_too(self) -> None:
        words = " ".join(f"w{n}" for n in range(g.MIN_QUOTE_WORDS))
        quotes = g.extract_quotes(f"They wrote “{words}” in the paper.")
        assert [quote["text"] for quote in quotes] == [words]

    def test_a_span_crossing_a_blank_line_is_a_mismatched_delimiter(self) -> None:
        report = 'He said "one two three four five six\n\nseven eight nine ten" here.'
        assert g.extract_quotes(report) == []

    def test_a_span_longer_than_the_cap_is_not_a_quotation(self) -> None:
        long_span = "word " * (g.MAX_QUOTE_CHARS // 2)
        assert g.extract_quotes(f'x "{long_span}" y') == []

    def test_quotes_inside_code_spans_are_ignored(self) -> None:
        report = '```\n"one two three four five six seven"\n```'
        assert g.extract_quotes(report) == []

    def test_attribution_looks_forward_first(self) -> None:
        report = (
            'The paper says "one two three four five six seven" [Rosen, 2024].'
        )
        quotes = g.extract_quotes(report, [_citation("arxiv:2401.00001")])
        assert quotes[0]["attributed_to"] == "arxiv:2401.00001"
        assert quotes[0]["attribution"] == "author_year"

    def test_attribution_falls_back_to_a_lead_in(self) -> None:
        report = 'As arXiv:2401.00001 puts it, "one two three four five six seven".'
        quotes = g.extract_quotes(report)
        assert quotes[0]["attributed_to"] == "arxiv:2401.00001"
        assert quotes[0]["attribution"] == "arxiv_id"

    def test_an_explicit_identifier_outranks_an_author_year_tag(self) -> None:
        """The id names the paper; the tag names it through a list the model wrote."""
        report = (
            '"one two three four five six seven" (arXiv:2401.00002) [Rosen, 2024].'
        )
        quotes = g.extract_quotes(report, [_citation("arxiv:2401.00001")])
        assert quotes[0]["attributed_to"] == "arxiv:2401.00002"

    @pytest.mark.parametrize(
        "tag", ["[Rosen, 2024]", "[Rosen et al., 2024]", "[Rosen and Mensah, 2024]"]
    )
    def test_the_three_inline_citation_forms_all_attribute(self, tag: str) -> None:
        """The forms `src/agents/synthesizer.py` actually emits."""
        report = f'The paper says "one two three four five six seven" {tag}.'
        quotes = g.extract_quotes(report, [_citation("arxiv:2401.00001")])
        assert quotes[0]["attributed_to"] == "arxiv:2401.00001"

    @pytest.mark.parametrize(
        "entry",
        [
            Citation(paper_id="arxiv:1", title="t", authors=[], year="2024", url=""),
            Citation(paper_id="arxiv:1", title="t", authors=["X"], year="", url=""),
            Citation(paper_id="arxiv:1", title="t", authors=["  "], year="2024", url=""),
        ],
    )
    def test_a_citation_entry_that_names_nobody_attributes_nothing(
        self, entry: Citation
    ) -> None:
        report = 'The paper says "one two three four five six seven" [X, 2024].'
        assert g.extract_quotes(report, [entry])[0]["attributed_to"] is None

    def test_attribution_does_not_reach_across_a_paragraph_break(self) -> None:
        report = (
            '"one two three four five six seven" is asserted here.\n\n'
            "The source is [Rosen, 2024]."
        )
        quotes = g.extract_quotes(report, [_citation("arxiv:2401.00001")])
        assert quotes[0]["attributed_to"] is None
        assert quotes[0]["attribution"] == "none"


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


class TestSourceIndex:
    def test_parsed_text_beats_evidence_chunks_beats_the_abstract(self) -> None:
        paper = _paper("http://arxiv.org/abs/2401.00001", abstract="the abstract")
        claim = EvidenceClaim(
            claim="c",
            paper_id="arxiv:2401.00001",
            section="results",
            source_text="a ranked chunk",
            relevance_score=0.9,
            supports_question="q",
        )

        abstract_only = g.build_source_index([paper])
        assert abstract_only["arxiv:2401.00001"]["origin"] == "abstract"
        assert abstract_only["arxiv:2401.00001"]["completeness"] == "partial"

        with_chunks = g.build_source_index([paper], evidence=[claim])
        assert with_chunks["arxiv:2401.00001"]["origin"] == "evidence_chunks"
        assert with_chunks["arxiv:2401.00001"]["completeness"] == "partial"

        with_text = g.build_source_index(
            [paper],
            evidence=[claim],
            full_texts={"http://arxiv.org/abs/2401.00001": "the whole paper"},
        )
        assert with_text["arxiv:2401.00001"]["origin"] == "pdf_text"
        assert with_text["arxiv:2401.00001"]["completeness"] == "full"

    def test_a_quote_can_never_bridge_two_evidence_chunks(self) -> None:
        """The chunks are non-contiguous; a match across them is invented text.

        This is why `SourceText` keeps `segments`. Joining them into one
        string would not be enough: whitespace collapses at the `folded`
        level and disappears entirely at `skeleton`, so no separator
        made of blank lines or punctuation survives to keep the two
        excerpts apart.
        """
        paper = _paper("http://arxiv.org/abs/2401.00001")
        claims = [
            EvidenceClaim(
                claim="c",
                paper_id="arxiv:2401.00001",
                section="results",
                source_text=text,
                relevance_score=0.5,
                supports_question="q",
            )
            for text in ("the first chunk ends here", "and a second one begins")
        ]
        source = g.build_source_index([paper], evidence=claims)["arxiv:2401.00001"]
        bridging = "the first chunk ends here and a second one begins"

        assert source["segments"] == [
            "the first chunk ends here",
            "and a second one begins",
        ]
        assert g.locate_quote_in_segments(bridging, source["segments"]) is None
        # The naive alternative — matching the joined text — would have
        # found it, which is exactly the false positive being prevented.
        assert g.locate_quote(bridging, source["text"]) == "folded"

    def test_the_strongest_match_across_segments_is_the_one_reported(self) -> None:
        assert (
            g.locate_quote_in_segments("one two three", ["ONE  two three", "one two three"])
            == "exact"
        )
        assert g.locate_quote_in_segments("one two three", ["nothing here"]) is None

    def test_a_paper_with_no_text_at_all_is_absent_from_the_index(self) -> None:
        assert g.build_source_index([_paper("arxiv:2401.00001", abstract="  ")]) == {}

    def test_a_paper_with_no_identifier_is_skipped_rather_than_indexed_as_empty(
        self,
    ) -> None:
        """An id-less row would otherwise claim the `""` key for itself."""
        assert g.build_source_index([_paper("", abstract="text")]) == {}
        assert g.build_corpus_index([_paper("")]) == {}

    def test_a_blank_full_text_falls_through_to_the_next_source(self) -> None:
        paper = _paper("arxiv:2401.00001", abstract="the abstract")
        index = g.build_source_index([paper], full_texts={"arxiv:2401.00001": "  "})
        assert index["arxiv:2401.00001"]["origin"] == "abstract"

    def test_coverage_is_published_so_the_rate_can_be_read(self) -> None:
        fixture = _fixture()
        coverage = g.source_coverage(
            g.build_source_index(_papers(), full_texts=fixture["pdf_text"])
        )
        assert coverage == g.SourceCoverage(
            papers=3, full_text=2, evidence_chunks=0, abstract_only=1
        )


# ---------------------------------------------------------------------------
# Citation resolution
# ---------------------------------------------------------------------------


class TestCitationResolution:
    def test_a_citation_to_a_paper_the_run_never_retrieved_is_flagged(self) -> None:
        """The headline acceptance case, and the interesting failure.

        Note what is *not* consulted: arxiv.org. `2402.99999` may well be
        a real paper — a citation to a real paper the run never read is
        still fabricated.
        """
        result = g.measure_groundedness(
            "Later work confirms it (arXiv:2402.99999).",
            [_paper("http://arxiv.org/abs/2401.00001")],
            [],
        )
        assert [claim["reason"] for claim in result["claims"]] == [
            g.CITATION_NOT_RETRIEVED
        ]
        assert result["citation_resolution_rate"]["value"] == 0.0
        assert result["report_grounded"] is False

    def test_a_malformed_identifier_reports_a_different_reason(self) -> None:
        """Two defects, two owners. Collapsing them loses the diagnosis."""
        result = g.measure_groundedness(
            "Catalogued as arXiv:24x1.0000 in the appendix.",
            [_paper("http://arxiv.org/abs/2401.00001")],
            [],
        )
        assert [claim["reason"] for claim in result["claims"]] == [
            g.CITATION_MALFORMED
        ]
        assert g.CITATION_MALFORMED != g.CITATION_NOT_RETRIEVED

    def test_a_retrieved_paper_resolves_through_any_surface_form(self) -> None:
        result = g.measure_groundedness(
            "See https://arxiv.org/pdf/2401.00001v3.pdf for the method.",
            [_paper("http://arxiv.org/abs/2401.00001")],
            [_citation("arxiv:2401.00001")],
        )
        assert result["citation_resolution_rate"]["value"] == 1.0
        assert result["citation_resolution_rate"]["denominator"] == 2

    def test_a_repeated_citation_on_one_surface_counts_once(self) -> None:
        """Citation density must not be able to move the score."""
        report = "a (arXiv:2401.00001) b (arXiv:2401.00001) c (arXiv:2401.00001)"
        result = g.measure_groundedness(
            report, [_paper("http://arxiv.org/abs/2401.00001")], []
        )
        assert result["citation_resolution_rate"]["denominator"] == 1

    def test_a_semantic_scholar_paper_the_run_retrieved_resolves(self) -> None:
        result = g.measure_groundedness("", [_paper("s2:9a1f")], [_citation("s2:9a1f")])
        assert result["citation_resolution_rate"]["value"] == 1.0

    def test_the_citation_list_is_checked_even_when_the_body_names_nothing(
        self,
    ) -> None:
        """The surface `citation_accuracy` cannot see.

        A fabricated entry with plausible authors and a fabricated
        `paper_id` scores 1.0 there, because the tag is matched against
        the same list that invented it.
        """
        report = "Constrained decoding helps [Rosen, 2024]."
        citations = [_citation("http://arxiv.org/abs/2402.99999")]
        papers = [_paper("http://arxiv.org/abs/2401.00001")]

        assert measure_citation_accuracy(report, citations)["score"] == 1.0

        result = g.measure_groundedness(report, papers, citations)
        assert result["citation_resolution_rate"]["value"] == 0.0
        assert result["claims"][0]["locator"] == "citations[0].paper_id"


# ---------------------------------------------------------------------------
# Quote verdicts
# ---------------------------------------------------------------------------


class TestQuoteVerdicts:
    PAPER = "http://arxiv.org/abs/2401.00001"
    TEXT = "State-of-the-\nart decoding reduces unsupported claims by 41%."

    def _measure(self, report: str, **kwargs: Any) -> g.GroundednessResult:
        return g.measure_groundedness(
            report,
            [_paper(self.PAPER, abstract="")],
            [_citation(self.PAPER)],
            full_texts={self.PAPER: self.TEXT},
            **kwargs,
        )

    def test_a_quote_broken_by_hyphenation_across_a_line_passes(self) -> None:
        result = self._measure(
            'It finds "State-of-the-art decoding reduces unsupported claims by 41%" '
            "[Rosen, 2024]."
        )
        quote = result["claims"][-1]
        assert quote["reason"] == g.QUOTE_VERBATIM
        assert result["quote_verbatim_rate"]["value"] == 1.0

    def test_a_near_miss_quote_fails(self) -> None:
        """One word changed. Nothing about that is forgiven."""
        result = self._measure(
            'It finds "State-of-the-art decoding reduces unsupported errors by 41%" '
            "[Rosen, 2024]."
        )
        quote = result["claims"][-1]
        assert quote["grounded"] is False
        assert quote["reason"] == g.QUOTE_NOT_FOUND

    def test_a_quote_found_in_a_different_retrieved_paper_is_misattributed(
        self,
    ) -> None:
        """A defect only a deterministic check can name.

        Claimed only when the attributed paper's source is complete —
        otherwise "not in the excerpt we hold" is not evidence that it is
        somewhere else.
        """
        other = "http://arxiv.org/abs/2401.00002"
        result = g.measure_groundedness(
            'The method paper says "a form of implicit fact-checking during '
            'generation" [Rosen, 2024].',
            [_paper(self.PAPER, abstract=""), _paper(other, abstract="")],
            [_citation(self.PAPER), _citation(other, author="Nair")],
            full_texts={
                self.PAPER: self.TEXT,
                other: "It provides a form of implicit fact-checking during generation.",
            },
        )
        quote = result["claims"][-1]
        assert quote["reason"] == g.QUOTE_MISATTRIBUTED
        assert "arxiv:2401.00002" in quote["detail"]

    def test_a_quote_cannot_be_falsified_against_an_incomplete_source(self) -> None:
        """The trap the work order names, taken seriously.

        Given only an abstract, "not found" means "not in the abstract".
        Scoring that as a hallucination would measure the PDF cache.
        """
        result = g.measure_groundedness(
            'It finds "State-of-the-art decoding reduces unsupported claims by 41%" '
            "[Rosen, 2024].",
            [_paper(self.PAPER, abstract="A short abstract about decoding.")],
            [_citation(self.PAPER)],
        )
        quote = result["claims"][-1]
        assert quote["grounded"] is None
        assert quote["reason"] == g.QUOTE_SOURCE_INCOMPLETE
        assert result["quote_verbatim_rate"]["excluded"] == 1

    def test_a_hit_against_an_incomplete_source_still_counts(self) -> None:
        """A partial source can prove a quote; it just cannot disprove one."""
        result = g.measure_groundedness(
            'It finds "decoding reduces unsupported claims by 41%" [Rosen, 2024].',
            [_paper(self.PAPER, abstract="decoding reduces unsupported claims by 41%")],
            [_citation(self.PAPER)],
        )
        assert result["claims"][-1]["reason"] == g.QUOTE_VERBATIM

    def test_an_unattributed_quote_is_undecidable_not_wrong(self) -> None:
        """We will not guess a source and then fail the report for the guess."""
        result = self._measure('Somebody wrote "one two three four five six seven".')
        quote = result["claims"][-1]
        assert quote["grounded"] is None
        assert quote["reason"] == g.QUOTE_UNATTRIBUTED

    def test_an_elided_quote_with_a_tiny_fragment_is_undecidable(self) -> None:
        """Two words either side of an ellipsis can be found in any paper."""
        result = self._measure(
            'It finds "State-of-the-art decoding reduces ... by 41%" [Rosen, 2024].'
        )
        quote = result["claims"][-1]
        assert quote["grounded"] is None
        assert quote["reason"] == g.QUOTE_ELIDED_UNCHECKABLE

    def test_a_quote_attributed_to_a_paper_with_no_text_at_all_is_undecidable(
        self,
    ) -> None:
        result = g.measure_groundedness(
            'It finds "State-of-the-art decoding reduces unsupported claims by 41%" '
            "[Rosen, 2024].",
            [_paper(self.PAPER, abstract="")],
            [_citation(self.PAPER)],
        )
        quote = result["claims"][-1]
        assert quote["reason"] == g.QUOTE_SOURCE_INCOMPLETE
        assert "no text at all" in quote["detail"]

    def test_byte_exact_quotations_are_counted_separately(self) -> None:
        """How many quotes needed no normalization at all is itself a signal."""
        result = self._measure(
            'It finds "art decoding reduces unsupported claims by 41%" [Rosen, 2024].'
        )
        assert result["exact_quote_count"] == 1


# ---------------------------------------------------------------------------
# Honest denominators
# ---------------------------------------------------------------------------


class TestZeroIsNotAPerfectScore:
    """The defect this module exists not to repeat.

    `metrics.measure_citation_accuracy` returns 1.0 for a report with no
    citations: a perfect score for the exact failure the metric was
    written to catch. Both halves are asserted here so the contrast is in
    the test, not only in the ADR.
    """

    def test_the_old_metric_rewards_a_report_with_no_citations(self) -> None:
        assert measure_citation_accuracy("A report with no citations.", [])["score"] == 1.0

    def test_the_new_metric_reports_none_with_a_reason(self) -> None:
        result = g.measure_groundedness("A report with no citations.", [], [])
        metric = result["citation_resolution_rate"]
        assert metric["value"] is None
        assert metric["reason"] == g.NO_CITATIONS
        assert metric["denominator"] == 0

    def test_no_quotations_and_no_checkable_quotations_are_different_facts(
        self,
    ) -> None:
        """A missing PDF cache must not hide behind a clean-looking metric."""
        silent = g.measure_groundedness("Nothing is quoted here at all.", [], [])
        assert silent["quote_verbatim_rate"]["reason"] == g.NO_QUOTES

        unfalsifiable = g.measure_groundedness(
            'It finds "one two three four five six seven" [Rosen, 2024].',
            [_paper("http://arxiv.org/abs/2401.00001", abstract="short")],
            [_citation("http://arxiv.org/abs/2401.00001")],
        )
        assert unfalsifiable["quote_verbatim_rate"]["reason"] == g.NO_CHECKABLE_QUOTES

    def test_an_unsupported_claim_count_of_zero_out_of_zero_is_none(self) -> None:
        """Zero problems found in nothing checked is not "nothing wrong"."""
        result = g.measure_groundedness("", [], [])
        metric = result["unsupported_claim_count"]
        assert metric["value"] is None
        assert metric["reason"] == g.NO_CHECKABLE_CLAIMS

    def test_report_grounded_is_none_when_nothing_could_be_decided(self) -> None:
        assert g.measure_groundedness("", [], [])["report_grounded"] is None

    def test_every_metric_publishes_its_denominator(self) -> None:
        fixture = _fixture()
        result = g.measure_groundedness(
            fixture["reports"]["grounded"],
            _papers(),
            _citations(),
            full_texts=fixture["pdf_text"],
        )
        for name in (
            "citation_resolution_rate",
            "quote_verbatim_rate",
            "unsupported_claim_count",
        ):
            metric = result[name]  # type: ignore[literal-required]
            assert set(metric) == {
                "name",
                "value",
                "numerator",
                "denominator",
                "excluded",
                "reason",
            }
            assert metric["name"] == name
            assert (metric["value"] is None) == (metric["reason"] is not None)

    def test_a_reason_is_always_one_of_the_declared_codes(self) -> None:
        fixture = _fixture()
        for report in fixture["reports"].values():
            result = g.measure_groundedness(
                report, _papers(), _citations(), full_texts=fixture["pdf_text"]
            )
            for claim in result["claims"]:
                assert claim["reason"] in g.CLAIM_REASONS
            for name in (
                "citation_resolution_rate",
                "quote_verbatim_rate",
                "unsupported_claim_count",
            ):
                reason = result[name]["reason"]  # type: ignore[literal-required]
                assert reason is None or reason in g.EMPTY_METRIC_REASONS


# ---------------------------------------------------------------------------
# The paired variable WO-A09 consumes
# ---------------------------------------------------------------------------


class TestPairedOutcomes:
    def test_claim_ids_are_content_derived_and_stable_across_runs(self) -> None:
        """Pairing needs an id that does not move when the report does."""
        first = g.measure_groundedness(
            "See arXiv:2401.00001.", [_paper("arxiv:2401.00001")], []
        )
        second = g.measure_groundedness(
            "A longer preamble, and then see arXiv:2401.00001 at the end.",
            [_paper("arxiv:2401.00001")],
            [],
        )
        assert g.paired_outcomes(first) == g.paired_outcomes(second)

    def test_the_same_claim_in_two_arms_pairs_on_one_id(self) -> None:
        baseline = g.measure_groundedness(
            "See arXiv:2402.99999.", [_paper("arxiv:2401.00001")], []
        )
        candidate = g.measure_groundedness(
            "See arXiv:2402.99999.",
            [_paper("arxiv:2401.00001"), _paper("arxiv:2402.99999")],
            [],
        )
        shared = set(g.paired_outcomes(baseline)) & set(g.paired_outcomes(candidate))
        assert len(shared) == 1
        claim_id = shared.pop()
        assert g.paired_outcomes(baseline)[claim_id] is False
        assert g.paired_outcomes(candidate)[claim_id] is True

    def test_undecided_claims_are_dropped_rather_than_defaulted(self) -> None:
        """A claim that could not be checked is not evidence either way."""
        result = g.measure_groundedness(
            'Somebody wrote "one two three four five six seven".',
            [_paper("arxiv:2401.00001")],
            [],
        )
        assert any(claim["grounded"] is None for claim in result["claims"])
        assert g.paired_outcomes(result) == {}


# ---------------------------------------------------------------------------
# Attribution of the check itself
# ---------------------------------------------------------------------------


class TestCheckIdentity:
    def test_the_normalization_spec_is_locked_to_its_version(self) -> None:
        """Editing the spec without bumping the version fails here.

        Same contract as `tests/test_eval_rubric_versions.py`, applied to
        a check with no prompt: rows scored either side of a spec change
        are not comparable, and somebody has to say so.
        """
        assert g.GROUNDEDNESS_CHECK_VERSION == LOCKED_SPEC_VERSION
        assert g.spec_digest() == LOCKED_SPEC_DIGEST

    def test_a_result_names_the_check_that_produced_it(self) -> None:
        result = g.measure_groundedness("", [], [])
        assert result["check"] == g.check_identity()
        assert result["min_quote_words"] == g.MIN_QUOTE_WORDS

    def test_a_result_carries_the_run_provenance_it_was_given(self) -> None:
        """ADR 0070's terms, applied to a row that is not a judge's."""
        block = RunProvenance(
            harness_version="1.0.0",
            judge_model="none",
            product_model="none",
            rubric_versions={"groundedness": g.GROUNDEDNESS_CHECK_VERSION},
            code_commit="0" * 40,
            code_dirty=False,
            dataset_version="groundedness@1:abc",
            tier="research",
            seed=0,
            mock_mode=True,
            captured_at="2026-09-04T00:00:00+00:00",
        )
        result = g.measure_groundedness("", [], [], provenance=block)
        assert result[PROVENANCE_KEY] == block  # type: ignore[literal-required]
        assert g.measure_groundedness("", [], [])["provenance"] is None


class TestNoJudgeNoNetwork:
    """Asserted structurally, not by trusting the harness to catch it."""

    SOURCE = inspect.getsource(g)

    def test_the_module_imports_nothing_that_can_call_a_model(self) -> None:
        assert "src.llm" not in self.SOURCE
        assert "call_llm_json" not in self.SOURCE

    def test_the_module_imports_nothing_that_can_open_a_socket(self) -> None:
        for forbidden in ("requests", "urllib", "httpx", "socket", "arxiv.org/api"):
            assert f"import {forbidden}" not in self.SOURCE

    def test_a_full_measurement_touches_no_settings_and_no_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Belt and braces: a real measurement with the LLM entrypoint mined."""
        import src.llm as llm_module

        def explode(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("groundedness must never call a model")

        monkeypatch.setattr(llm_module, "call_llm_json", explode)
        fixture = _fixture()
        result = g.measure_groundedness(
            fixture["reports"]["hallucinated"],
            _papers(),
            _citations(),
            full_texts=fixture["pdf_text"],
        )
        assert result["report_grounded"] is False


# ---------------------------------------------------------------------------
# The fixture corpus, end to end
# ---------------------------------------------------------------------------


class TestTheFixtureCorpus:
    """Calibration, run as a test. See `docs/eval.md` for the findings."""

    def test_the_clean_report_scores_clean_on_both_checks(self) -> None:
        fixture = _fixture()
        result = g.measure_groundedness(
            fixture["reports"]["grounded"],
            _papers(),
            _citations(),
            full_texts=fixture["pdf_text"],
        )
        assert result["citation_resolution_rate"]["value"] == 1.0
        assert result["quote_verbatim_rate"]["value"] == 1.0
        assert result["unsupported_claim_count"]["numerator"] == 0
        assert result["report_grounded"] is True

    def test_the_hallucinated_report_names_every_defect_separately(self) -> None:
        fixture = _fixture()
        result = g.measure_groundedness(
            fixture["reports"]["hallucinated"],
            _papers(),
            _citations(),
            full_texts=fixture["pdf_text"],
        )
        reasons = {claim["reason"] for claim in result["claims"]}
        assert {
            g.CITATION_NOT_RETRIEVED,
            g.CITATION_MALFORMED,
            g.QUOTE_NOT_FOUND,
            g.QUOTE_MISATTRIBUTED,
        } <= reasons
        assert result["unsupported_claim_count"]["numerator"] == 4
        assert result["unsupported_claim_count"]["denominator"] == 8

    def test_the_partial_source_report_excludes_what_it_cannot_decide(self) -> None:
        fixture = _fixture()
        result = g.measure_groundedness(
            fixture["reports"]["partial_source"],
            _papers(),
            _citations(),
            full_texts=fixture["pdf_text"],
        )
        assert result["quote_verbatim_rate"]["denominator"] == 1
        assert result["quote_verbatim_rate"]["excluded"] == 2
        assert {
            claim["reason"]
            for claim in result["claims"]
            if claim["grounded"] is None
        } == {g.QUOTE_SOURCE_INCOMPLETE, g.QUOTE_UNATTRIBUTED}

    def test_a_report_that_quotes_nothing_still_has_its_citations_checked(
        self,
    ) -> None:
        fixture = _fixture()
        result = g.measure_groundedness(
            fixture["reports"]["quiet"],
            _papers(),
            _citations(),
            full_texts=fixture["pdf_text"],
        )
        assert result["quote_verbatim_rate"]["reason"] == g.NO_QUOTES
        assert result["citation_resolution_rate"]["denominator"] == 3

    def test_the_fixture_declares_its_own_provenance(self) -> None:
        """A hand-authored fixture that does not say so is a recorded one."""
        readme = "\n".join(_fixture()["_readme"])
        assert "Hand-authored, not recorded" in readme
        assert "No PDF is fetched" in readme
