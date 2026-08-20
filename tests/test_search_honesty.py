"""Retrieval-honesty tests for the search agent and arXiv tool (ADR 0041).

The headline behavior under test: `MOCK_PAPERS` is reachable ONLY under
`settings.use_mock_data`. A live search that yields nothing raises a
typed error — `NoPapersFoundError` for a genuine zero-hit answer,
`ArxivUnavailableError` when every query failed at the transport level —
so the job fails with an honest `error_type` instead of shipping a
briefing built on five hardcoded off-topic papers.

Mutation-checked: every raising test here fails against the pre-fix
code (which substituted `MOCK_PAPERS` and returned a normal update),
and the cap test fails without `MAX_SEARCH_QUERIES_PER_RUN` trimming.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agents import search as search_module
from src.agents.search import MAX_SEARCH_QUERIES_PER_RUN, NoPapersFoundError, search_agent
from src.config import Settings
from src.graph.state import PaperMetadata
from src.tools.arxiv_search import (
    ArxivUnavailableError,
    canonical_paper_key,
    deduplicate_papers,
    search_arxiv,
)

pytestmark = pytest.mark.unit


def _paper(arxiv_id: str = "2311.09000", title: str = "Paper") -> PaperMetadata:
    return PaperMetadata(
        id=f"http://arxiv.org/abs/{arxiv_id}",
        title=title,
        authors=["A"],
        abstract=f"Abstract for {title}.",
        url=f"http://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"http://arxiv.org/pdf/{arxiv_id}",
    )


def _state(
    search_queries: list[str] | None = None, papers: list[PaperMetadata] | None = None
) -> Any:
    state: dict[str, Any] = {
        "query": "What is RAG?",
        "search_queries": search_queries or ["retrieval augmented generation"],
    }
    if papers is not None:
        state["papers"] = papers
    return state


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_module.time, "sleep", lambda _s: None)


def _live_settings(**overrides: Any) -> Settings:
    return Settings(use_mock_data=False, enable_semantic_scholar=False, **overrides)


def _stub_ranker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        search_module,
        "rank_papers_by_relevance",
        lambda query, papers, top_k: papers[:top_k],
    )


class TestMockGating:
    def test_zero_live_results_never_serves_mock_papers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pre-fix code substituted MOCK_PAPERS here — the core P1."""
        monkeypatch.setattr(search_module, "settings", _live_settings())
        _stub_ranker(monkeypatch)
        monkeypatch.setattr(
            search_module,
            "search_arxiv",
            lambda q, max_results, raise_on_unavailable=False: [],
        )
        with pytest.raises(NoPapersFoundError):
            search_agent(_state())

    def test_all_queries_unavailable_raises_arxiv_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(search_module, "settings", _live_settings())
        _stub_ranker(monkeypatch)
        _no_sleep(monkeypatch)

        def _down(q: str, max_results: int, raise_on_unavailable: bool = False) -> Any:
            raise ArxivUnavailableError("rate limited")

        monkeypatch.setattr(search_module, "search_arxiv", _down)
        with pytest.raises(ArxivUnavailableError):
            search_agent(_state(["q1", "q2"]))

    def test_partial_failure_proceeds_with_found_papers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(search_module, "settings", _live_settings())
        _stub_ranker(monkeypatch)
        _no_sleep(monkeypatch)
        calls = {"n": 0}

        def _flaky(q: str, max_results: int, raise_on_unavailable: bool = False) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ArxivUnavailableError("down")
            return [_paper()]

        monkeypatch.setattr(search_module, "search_arxiv", _flaky)
        update = search_agent(_state(["q1", "q2"]))
        assert len(update["papers"]) == 1
        assert "arXiv" in update["messages"][0].content

    def test_mock_data_flag_serves_mock_papers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            search_module, "settings", Settings(use_mock_data=True)
        )
        _stub_ranker(monkeypatch)
        update = search_agent(_state())
        assert update["papers"] == search_module.MOCK_PAPERS
        assert "mock data" in update["messages"][0].content

    def test_empty_re_search_keeps_prior_papers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A supervisor-loop re-search that finds nothing must not
        destroy the result set an earlier round already paid for —
        and must not raise either."""
        monkeypatch.setattr(search_module, "settings", _live_settings())
        _stub_ranker(monkeypatch)
        monkeypatch.setattr(
            search_module,
            "search_arxiv",
            lambda q, max_results, raise_on_unavailable=False: [],
        )
        prior = [_paper("2401.00001", "Prior")]
        update = search_agent(_state(papers=prior))
        assert update["papers"] == prior
        assert "keeping" in update["messages"][0].content


class TestQueryCap:
    def test_oversized_plan_trimmed_to_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(search_module, "settings", _live_settings())
        _stub_ranker(monkeypatch)
        _no_sleep(monkeypatch)
        seen: list[str] = []

        def _record(q: str, max_results: int, raise_on_unavailable: bool = False) -> Any:
            seen.append(q)
            return [_paper()]

        monkeypatch.setattr(search_module, "search_arxiv", _record)
        oversized = [f"query {i}" for i in range(MAX_SEARCH_QUERIES_PER_RUN + 20)]
        search_agent(_state(oversized))
        assert len(seen) == MAX_SEARCH_QUERIES_PER_RUN
        assert seen == oversized[:MAX_SEARCH_QUERIES_PER_RUN]


class TestSearchArxivUnavailableContract:
    def _rate_limited_response(self) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "whoa there — Rate exceeded, slow down"
        return resp

    def test_default_returns_empty_on_rate_limit(self) -> None:
        with patch(
            "src.tools.arxiv_search.build_retrying_session"
        ) as factory:
            factory.return_value.get.return_value = self._rate_limited_response()
            assert search_arxiv("q", max_results=5) == []

    def test_opt_in_raises_on_rate_limit(self) -> None:
        with patch(
            "src.tools.arxiv_search.build_retrying_session"
        ) as factory:
            factory.return_value.get.return_value = self._rate_limited_response()
            with pytest.raises(ArxivUnavailableError):
                search_arxiv("q", max_results=5, raise_on_unavailable=True)

    def test_opt_in_raises_on_connection_error(self) -> None:
        import requests

        with patch(
            "src.tools.arxiv_search.build_retrying_session"
        ) as factory:
            factory.return_value.get.side_effect = requests.ConnectionError("boom")
            with pytest.raises(ArxivUnavailableError):
                search_arxiv("q", max_results=5, raise_on_unavailable=True)

    def test_zero_hit_200_does_not_raise(self) -> None:
        """A genuinely empty Atom feed is a *successful* search."""
        resp = MagicMock()
        resp.status_code = 200
        resp.text = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        )
        with patch(
            "src.tools.arxiv_search.build_retrying_session"
        ) as factory:
            factory.return_value.get.return_value = resp
            assert search_arxiv("q", max_results=5, raise_on_unavailable=True) == []


class TestCanonicalDedup:
    def test_versioned_http_and_unversioned_https_collide(self) -> None:
        assert canonical_paper_key(
            "http://arxiv.org/abs/2311.09000v1"
        ) == canonical_paper_key("https://arxiv.org/abs/2311.09000")

    def test_distinct_arxiv_ids_do_not_collide(self) -> None:
        assert canonical_paper_key(
            "http://arxiv.org/abs/2311.09000"
        ) != canonical_paper_key("http://arxiv.org/abs/2311.09001")

    def test_non_arxiv_ids_pass_through(self) -> None:
        assert canonical_paper_key("s2:abc123") == "s2:abc123"

    def test_deduplicate_collapses_cross_source_duplicates(self) -> None:
        seed = _paper("2311.09000v1", "Seed")
        s2_dup = PaperMetadata(
            id="https://arxiv.org/abs/2311.09000",
            title="Seed (from S2)",
            authors=["A"],
            abstract="a",
            url="https://arxiv.org/abs/2311.09000",
            pdf_url="",
        )
        unique = deduplicate_papers([seed, s2_dup])
        assert unique == [seed]
