"""Smoke tests for pure functions that don't require API access."""

from langgraph.graph import END

from src.graph.state import PaperMetadata
from src.graph.workflow import route_after_critique
from src.tools.arxiv_search import deduplicate_papers


def _mk_paper(paper_id: str, title: str = "T") -> PaperMetadata:
    return PaperMetadata(
        id=paper_id,
        title=title,
        authors=["A"],
        abstract="abstract",
        url=paper_id,
        pdf_url=paper_id,
    )


class TestDeduplicatePapers:
    def test_empty_input(self) -> None:
        assert deduplicate_papers([]) == []

    def test_removes_duplicates_keeps_first(self) -> None:
        papers = [
            _mk_paper("1", "first"),
            _mk_paper("2", "second"),
            _mk_paper("1", "duplicate-of-first"),
        ]
        result = deduplicate_papers(papers)
        assert [p["id"] for p in result] == ["1", "2"]
        assert result[0]["title"] == "first"

    def test_preserves_order(self) -> None:
        papers = [_mk_paper(str(i)) for i in range(5)]
        assert [p["id"] for p in deduplicate_papers(papers)] == ["0", "1", "2", "3", "4"]


class TestRouteAfterCritique:
    def test_no_revision_needed_returns_end(self) -> None:
        state = {"revision_needed": False, "revision_target": ""}
        assert route_after_critique(state) == END

    def test_valid_target_returns_target(self) -> None:
        for target in ("planner", "search", "synthesizer"):
            state = {"revision_needed": True, "revision_target": target}
            assert route_after_critique(state) == target

    def test_invalid_target_falls_through_to_end(self) -> None:
        state = {"revision_needed": True, "revision_target": "bogus"}
        assert route_after_critique(state) == END

    def test_missing_fields_returns_end(self) -> None:
        assert route_after_critique({}) == END
