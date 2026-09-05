"""Proof that the gate's citation metric is the honest one (ADR 0074).

`src/eval/groundedness.py` already proves the check itself. What is
under test here is the **swap**: that the adapter the runner calls
preserves the honest behaviour, that the metric it publishes carries its
denominator, and that a campaign scored before the swap cannot be
compared against one scored after it.

The demonstration this whole work order turns on is
`TestTheE2eFixtureDemonstration`: the repository's own recorded
synthesizer output cites a paper mock mode never retrieved.
`measure_citation_accuracy` scores it 1.0. The replacement scores it 0.0
over a denominator of 1. Both assertions sit in one test so the defect
is visible in the code rather than only in an ADR.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.agents.search import MOCK_PAPERS
from src.eval.groundedness import (
    CITATION_MALFORMED,
    CITATION_NOT_RETRIEVED,
    GROUNDEDNESS_CHECK_VERSION,
    NO_CITATIONS,
    spec_digest,
)
from src.eval.metrics import (
    GROUNDEDNESS_CHECK,
    RESEARCH_RUBRICS,
    measure_citation_accuracy,
    measure_citation_resolution,
)
from src.graph.state import Citation, PaperMetadata

pytestmark = pytest.mark.unit

E2E_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "e2e"
    / "research_llm_responses.json"
)


def _paper(paper_id: str, title: str = "A paper") -> PaperMetadata:
    return PaperMetadata(
        id=paper_id,
        title=title,
        authors=["Ada Lovelace"],
        abstract="An abstract.",
        url=paper_id,
        pdf_url=f"{paper_id}.pdf",
    )


def _citation(paper_id: str, *, year: str = "2023") -> Citation:
    return Citation(
        paper_id=paper_id,
        title="A paper",
        authors=["Ada Lovelace"],
        year=year,
        url=paper_id,
    )


def _synthesizer_fixture() -> dict[str, Any]:
    payload = json.loads(E2E_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    fixture = payload["synthesizer"]
    assert isinstance(fixture, dict)
    return fixture


class TestZeroCitationsIsNotAPerfectScore:
    """The defect, stated as an assertion on both metrics at once."""

    def test_the_legacy_metric_still_awards_a_free_one(self) -> None:
        # Deliberately unchanged. Fixing it in place would silently move
        # every number this repository has published under that name;
        # the field is demoted instead, and the gate reads the other one.
        assert measure_citation_accuracy("A report with no citations.", [])[
            "score"
        ] == 1.0

    def test_the_gated_metric_reports_nothing_measured(self) -> None:
        result = measure_citation_resolution("A report with no citations.", [], [])
        assert result["score"] is None
        assert result["total_citations"] == 0
        assert result["reason"] == NO_CITATIONS

    def test_the_denominator_is_published_even_when_the_score_is_none(self) -> None:
        # A rate without a denominator is not a measurement, and a
        # `None` without a reason is indistinguishable from a crash.
        result = measure_citation_resolution("Nothing cited.", MOCK_PAPERS, [])
        assert set(result) >= {"score", "total_citations", "reason"}
        assert result["total_citations"] == 0
        assert result["reason"] is not None


class TestTheE2eFixtureDemonstration:
    """The repository's own recorded output, scored by both metrics.

    Not a synthetic example: `tests/fixtures/e2e/research_llm_responses.json`
    is the checked-in synthesizer response the e2e tier replays, and it
    cites `arxiv:2311.05232` while mock mode's corpus holds `2311.09000`.
    """

    def test_the_fixture_still_cites_a_paper_mock_mode_never_retrieved(self) -> None:
        # Guards the demonstration itself: if the fixture is ever
        # repaired, the two tests below stop meaning anything, and this
        # one says so instead of them quietly passing for a new reason.
        cited = {c["paper_id"] for c in _synthesizer_fixture()["citations"]}
        retrieved = {paper["id"] for paper in MOCK_PAPERS}
        assert cited
        assert not (cited & retrieved)

    def test_the_legacy_metric_scores_the_fabricated_citation_perfect(self) -> None:
        fixture = _synthesizer_fixture()
        citations = [
            Citation(**{**c, "year": str(c["year"])}) for c in fixture["citations"]
        ]
        assert (
            measure_citation_accuracy(fixture["draft_report"], citations)["score"]
            == 1.0
        )

    def test_the_gated_metric_scores_it_zero_and_names_the_defect(self) -> None:
        fixture = _synthesizer_fixture()
        citations = [
            Citation(**{**c, "year": str(c["year"])}) for c in fixture["citations"]
        ]
        result = measure_citation_resolution(
            fixture["draft_report"], list(MOCK_PAPERS), citations
        )
        assert result["score"] == 0.0
        assert result["total_citations"] == 1
        assert result["resolved"] == 0
        assert result["unresolved"] == [f"arxiv:2311.05232 [{CITATION_NOT_RETRIEVED}]"]


class TestTheAdapterPreservesTheCheck:
    def test_a_retrieved_citation_resolves(self) -> None:
        papers = [_paper("http://arxiv.org/abs/2311.09000")]
        result = measure_citation_resolution(
            "A report.", papers, [_citation("arxiv:2311.09000")]
        )
        assert result["score"] == 1.0
        assert result["total_citations"] == 1
        assert result["unresolved"] == []

    def test_a_malformed_identifier_is_reported_as_its_own_defect(self) -> None:
        # `citation_not_retrieved` and `citation_malformed` have
        # different owners, so they must not collapse into one bucket on
        # the way through the adapter.
        result = measure_citation_resolution(
            "A report.", [_paper("http://arxiv.org/abs/2311.09000")],
            [_citation("not-an-identifier")],
        )
        assert result["score"] == 0.0
        assert result["unresolved"] == [f"not-an-identifier [{CITATION_MALFORMED}]"]

    def test_the_report_body_is_a_second_surface(self) -> None:
        # The surface `citation_accuracy` cannot see at all: an
        # identifier written into the prose, with no citation entry
        # behind it.
        papers = [_paper("http://arxiv.org/abs/2311.09000")]
        result = measure_citation_resolution(
            "As shown in arXiv:2501.99999, this is fabricated.", papers, []
        )
        assert result["total_citations"] == 1
        assert result["score"] == 0.0

    def test_a_paper_cited_five_times_counts_once(self) -> None:
        papers = [_paper("http://arxiv.org/abs/2311.09000")]
        report = " ".join(["arXiv:2311.09000"] * 5)
        result = measure_citation_resolution(report, papers, [])
        assert result["total_citations"] == 1

    def test_the_result_names_the_check_that_produced_it(self) -> None:
        result = measure_citation_resolution("A report.", [], [])
        assert result["check_version"] == GROUNDEDNESS_CHECK_VERSION
        assert result["spec_digest"] == spec_digest()

    def test_the_excluded_count_is_carried_rather_than_assumed_zero(self) -> None:
        # The citation path has no undecidable outcome today. Publishing
        # the field anyway is what stops a later one from quietly
        # shrinking the denominator.
        result = measure_citation_resolution(
            "A report.", [_paper("http://arxiv.org/abs/2311.09000")],
            [_citation("arxiv:2311.09000")],
        )
        assert result["excluded"] == 0


class TestTheSwapIsRecordedAsARebaseline:
    """ADR 0074's cost, handled by ADR 0070's machinery."""

    def test_the_check_rides_in_the_campaigns_versioned_instruments(self) -> None:
        assert GROUNDEDNESS_CHECK in RESEARCH_RUBRICS
        assert GROUNDEDNESS_CHECK.version == GROUNDEDNESS_CHECK_VERSION

    def test_the_registered_text_is_the_checks_own_spec(self) -> None:
        # Not a judge prompt. What the lock defends is the text whose
        # edit makes two scores incomparable, and a deterministic check
        # has one.
        assert GROUNDEDNESS_CHECK.digest == spec_digest()


class TestTheMetricCostsNothing:
    def test_no_judge_and_no_network_on_the_scoring_path(self) -> None:
        # Zero spend is structural in this package. `measure_groundedness`
        # is pure, and the adapter adds no call of its own — asserted by
        # reading the source rather than by trusting a mock.
        import inspect

        import src.eval.groundedness as groundedness_module

        source = inspect.getsource(measure_citation_resolution)
        assert "call_llm" not in source
        assert "judge_model" not in source
        assert "requests" not in inspect.getsource(groundedness_module)
