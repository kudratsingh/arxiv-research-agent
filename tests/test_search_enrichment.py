"""Tests for the search agent's Semantic Scholar enrichment path (ADR 0023).

Existing search-agent behavior stays byte-identical when the flag is
off. When it's on, arXiv seeds get expanded with one-hop S2 references
and the union is deduped by paper ID before the final ranking.
"""

from typing import Any

import pytest

from src.agents import search as search_module
from src.agents.search import _enrich_with_s2_references, search_agent
from src.config import Settings
from src.graph.state import PaperMetadata


def _paper(
    arxiv_id: str = "2311.09000", title: str = "Paper"
) -> PaperMetadata:
    return PaperMetadata(  # type: ignore[typeddict-item]
        id=f"http://arxiv.org/abs/{arxiv_id}",
        title=title,
        authors=["A"],
        abstract=f"Abstract for {title}.",
        url=f"http://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"http://arxiv.org/pdf/{arxiv_id}",
    )


def _s2_ref(paper_id: str, title: str) -> PaperMetadata:
    """A reference-shaped PaperMetadata as `_map_s2_paper` would produce."""
    return PaperMetadata(  # type: ignore[typeddict-item]
        id=paper_id,
        title=title,
        authors=["Ref Author"],
        abstract=f"Abstract for {title}.",
        url=f"https://example/{paper_id}",
        pdf_url="",
    )


def _stub_arxiv(monkeypatch: pytest.MonkeyPatch, papers: list[PaperMetadata]) -> None:
    monkeypatch.setattr(
        search_module,
        "search_arxiv",
        lambda query, max_results: papers,
    )


def _stub_ranker(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace the ranker with an order-preserving pass-through."""
    captured: dict[str, Any] = {}

    def fake_rank(
        query: str, papers: list[PaperMetadata], top_k: int
    ) -> list[PaperMetadata]:
        captured["query"] = query
        captured["papers"] = papers
        captured["top_k"] = top_k
        return papers[:top_k]

    monkeypatch.setattr(search_module, "rank_papers_by_relevance", fake_rank)
    return captured


def _state(
    query: str = "What is RAG?", search_queries: list[str] | None = None
) -> Any:
    return {
        "query": query,
        "search_queries": search_queries or ["retrieval augmented generation"],
    }


# ---------------------------------------------------------------------------
# _enrich_with_s2_references — the pure enrichment step
# ---------------------------------------------------------------------------


class TestEnrichWithS2References:
    def test_no_seeds_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            search_module,
            "settings",
            Settings(
                semantic_scholar_seed_count=3,
                semantic_scholar_refs_per_seed=3,
            ),
        )
        # Never touches S2 because there are no seeds to expand.
        called = {"n": 0}

        def _no(_id: str, limit: int) -> list[PaperMetadata]:
            called["n"] += 1
            return []

        monkeypatch.setattr(search_module, "get_references", _no)
        _stub_ranker(monkeypatch)
        assert _enrich_with_s2_references("q", []) == []
        assert called["n"] == 0

    def test_zero_seed_count_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            search_module,
            "settings",
            Settings(semantic_scholar_seed_count=0),
        )
        called = {"n": 0}

        def _no(_id: str, limit: int) -> list[PaperMetadata]:
            called["n"] += 1
            return []

        monkeypatch.setattr(search_module, "get_references", _no)
        _stub_ranker(monkeypatch)
        assert (
            _enrich_with_s2_references("q", [_paper()]) == []
        )
        assert called["n"] == 0

    def test_expands_top_k_seeds_with_references(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            search_module,
            "settings",
            Settings(
                semantic_scholar_seed_count=2,
                semantic_scholar_refs_per_seed=3,
            ),
        )
        _stub_ranker(monkeypatch)  # pass-through ranker

        seen_ids: list[str] = []

        def fake_get_refs(
            paper_id: str, limit: int
        ) -> list[PaperMetadata]:
            seen_ids.append(paper_id)
            assert limit == 3
            return [_s2_ref(f"s2:ref-{paper_id}", f"Ref of {paper_id}")]

        monkeypatch.setattr(search_module, "get_references", fake_get_refs)

        seeds = [_paper("2311.09000"), _paper("2312.00001"), _paper("2401.01313")]
        refs = _enrich_with_s2_references("q", seeds)

        # Only the top-2 seeds get expanded (pass-through ranker preserves order).
        assert seen_ids == ["ARXIV:2311.09000", "ARXIV:2312.00001"]
        assert len(refs) == 2
        assert refs[0]["title"].startswith("Ref of ARXIV:2311.09000")

    def test_skips_seeds_without_recognizable_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            search_module,
            "settings",
            Settings(
                semantic_scholar_seed_count=5,
                semantic_scholar_refs_per_seed=3,
            ),
        )
        _stub_ranker(monkeypatch)

        called: list[str] = []

        def fake_get_refs(paper_id: str, limit: int) -> list[PaperMetadata]:
            called.append(paper_id)
            return []

        monkeypatch.setattr(search_module, "get_references", fake_get_refs)

        # Seed with an unrecognized id shape shouldn't get looked up.
        arxiv_seed = _paper("2311.09000")
        weird_seed = PaperMetadata(  # type: ignore[typeddict-item]
            id="http://example.com/something-not-arxiv",
            title="Weird",
            authors=["X"],
            abstract="a",
            url="",
            pdf_url="",
        )
        _enrich_with_s2_references("q", [arxiv_seed, weird_seed])
        assert called == ["ARXIV:2311.09000"]


# ---------------------------------------------------------------------------
# search_agent — flag-gated integration
# ---------------------------------------------------------------------------


class TestSearchAgentFlagOff:
    def test_flag_off_never_calls_s2(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            search_module,
            "settings",
            Settings(enable_semantic_scholar=False, use_mock_data=False),
        )
        _stub_arxiv(monkeypatch, [_paper("2311.09000", "P1")])
        _stub_ranker(monkeypatch)

        called = {"n": 0}
        monkeypatch.setattr(
            search_module,
            "get_references",
            lambda pid, limit: (called.update(n=called["n"] + 1) or []),
        )

        update = search_agent(_state())
        assert called["n"] == 0
        assert len(update["papers"]) == 1
        assert "arXiv" in update["messages"][0].content


class TestSearchAgentFlagOn:
    def test_flag_on_unions_arxiv_and_s2_references(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            search_module,
            "settings",
            Settings(
                enable_semantic_scholar=True,
                use_mock_data=False,
                semantic_scholar_seed_count=1,
                semantic_scholar_refs_per_seed=2,
                max_papers=5,
            ),
        )
        arxiv_papers = [_paper("2311.09000", "arXiv1")]
        _stub_arxiv(monkeypatch, arxiv_papers)
        captured = _stub_ranker(monkeypatch)

        def fake_get_refs(paper_id: str, limit: int) -> list[PaperMetadata]:
            return [
                _s2_ref("s2:ref-a", "S2 Ref A"),
                _s2_ref("s2:ref-b", "S2 Ref B"),
            ]

        monkeypatch.setattr(search_module, "get_references", fake_get_refs)

        update = search_agent(_state())
        # Ranker saw the union: arXiv seed + two S2 refs.
        assert len(captured["papers"]) == 3
        seen_ids = [p["id"] for p in captured["papers"]]
        assert "http://arxiv.org/abs/2311.09000" in seen_ids
        assert "s2:ref-a" in seen_ids
        assert "s2:ref-b" in seen_ids
        assert "S2 references" in update["messages"][0].content

    def test_s2_reference_with_arxiv_id_dedupes_against_seed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If S2 returns a reference that happens to also be one of our
        # arXiv seeds, the URL-form id collides and dedup keeps one.
        monkeypatch.setattr(
            search_module,
            "settings",
            Settings(
                enable_semantic_scholar=True,
                use_mock_data=False,
                semantic_scholar_seed_count=1,
                semantic_scholar_refs_per_seed=1,
                max_papers=5,
            ),
        )
        _stub_arxiv(
            monkeypatch, [_paper("2311.09000", "Seed"), _paper("2312.00001", "Other")]
        )
        captured = _stub_ranker(monkeypatch)

        def fake_get_refs(paper_id: str, limit: int) -> list[PaperMetadata]:
            # S2 returns a paper whose arXiv external ID matches an
            # existing seed — mapped to the same URL-form id.
            return [_s2_ref("http://arxiv.org/abs/2311.09000", "Seed dup")]

        monkeypatch.setattr(search_module, "get_references", fake_get_refs)

        search_agent(_state())
        ranked_input_ids = [p["id"] for p in captured["papers"]]
        # Deduped: the arXiv URL id appears exactly once.
        assert ranked_input_ids.count("http://arxiv.org/abs/2311.09000") == 1

    def test_mock_data_short_circuit_skips_s2(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # When arXiv returns nothing and we fall back to mock data,
        # we shouldn't hit S2 either — mock runs should be offline.
        monkeypatch.setattr(
            search_module,
            "settings",
            Settings(
                enable_semantic_scholar=True,
                use_mock_data=False,
                semantic_scholar_seed_count=3,
                semantic_scholar_refs_per_seed=3,
            ),
        )
        _stub_arxiv(monkeypatch, [])
        _stub_ranker(monkeypatch)

        called = {"n": 0}
        monkeypatch.setattr(
            search_module,
            "get_references",
            lambda pid, limit: (called.update(n=called["n"] + 1) or []),
        )

        update = search_agent(_state())
        assert called["n"] == 0
        assert "mock data" in update["messages"][0].content
