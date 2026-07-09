"""Unit tests for the Semantic Scholar adapter (ADR 0023).

Focuses on the pure mapping logic (`_map_s2_paper`), the ID
converter (`_arxiv_url_to_s2_id`), and the network-fronting
functions with `_get_json` stubbed. No live network calls.
"""

from typing import Any

import pytest

from src.config import Settings
from src.tools import semantic_scholar as s2_module
from src.tools.semantic_scholar import (
    S2_API_BASE,
    _arxiv_url_to_s2_id,
    _headers,
    _map_s2_paper,
    get_references,
    search_papers,
)


def _s2_record(**overrides: Any) -> dict[str, Any]:
    """Build a minimal well-formed S2 paper record for mapping tests."""
    base: dict[str, Any] = {
        "paperId": "abc123",
        "title": "Some Paper",
        "abstract": "An abstract about retrieval.",
        "authors": [{"name": "Alice Smith"}, {"name": "Bob Doe"}],
        "openAccessPdf": {"url": "https://example/paper.pdf"},
        "externalIds": {},
        "year": 2024,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _map_s2_paper
# ---------------------------------------------------------------------------


class TestMapS2Paper:
    def test_maps_all_fields_when_arxiv_id_present(self) -> None:
        record = _s2_record(externalIds={"ArXiv": "2311.09000"})
        paper = _map_s2_paper(record)
        assert paper is not None
        # arXiv URL wins as the ID so we dedupe against arxiv_search results.
        assert paper["id"] == "http://arxiv.org/abs/2311.09000"
        assert paper["url"] == "http://arxiv.org/abs/2311.09000"
        # And when no openAccessPdf is provided we still derive an arXiv PDF url.
        assert paper["title"] == "Some Paper"
        assert paper["authors"] == ["Alice Smith", "Bob Doe"]
        assert paper["abstract"] == "An abstract about retrieval."

    def test_prefers_open_access_pdf_over_arxiv_default(self) -> None:
        record = _s2_record(externalIds={"ArXiv": "2311.09000"})
        paper = _map_s2_paper(record)
        assert paper is not None
        # openAccessPdf was set in the fixture — that wins.
        assert paper["pdf_url"] == "https://example/paper.pdf"

    def test_falls_back_to_arxiv_pdf_url_when_no_open_access(self) -> None:
        record = _s2_record(
            externalIds={"ArXiv": "2311.09000"}, openAccessPdf=None
        )
        paper = _map_s2_paper(record)
        assert paper is not None
        assert paper["pdf_url"] == "http://arxiv.org/pdf/2311.09000"

    def test_uses_s2_id_when_no_arxiv_external(self) -> None:
        record = _s2_record()  # no ArXiv externalId
        paper = _map_s2_paper(record)
        assert paper is not None
        assert paper["id"] == "s2:abc123"
        assert paper["url"].startswith("https://www.semanticscholar.org/paper/abc123")
        # PDF url from openAccessPdf still applies.
        assert paper["pdf_url"] == "https://example/paper.pdf"

    def test_pdf_empty_when_no_open_access_and_no_arxiv(self) -> None:
        record = _s2_record(openAccessPdf=None)
        paper = _map_s2_paper(record)
        assert paper is not None
        # Reader will fall back to abstract-only path (ADR 0004).
        assert paper["pdf_url"] == ""

    def test_returns_none_when_abstract_missing(self) -> None:
        assert _map_s2_paper(_s2_record(abstract=None)) is None
        assert _map_s2_paper(_s2_record(abstract="")) is None
        assert _map_s2_paper(_s2_record(abstract="   ")) is None

    def test_returns_none_when_title_missing(self) -> None:
        assert _map_s2_paper(_s2_record(title="")) is None
        assert _map_s2_paper(_s2_record(title=None)) is None

    def test_returns_none_when_no_id_available(self) -> None:
        record = _s2_record(paperId="")
        assert _map_s2_paper(record) is None

    def test_wrong_type_input_returns_none(self) -> None:
        assert _map_s2_paper(None) is None  # type: ignore[arg-type]
        assert _map_s2_paper("not a dict") is None  # type: ignore[arg-type]

    def test_authors_defensively_coerced(self) -> None:
        # Malformed entries skipped, non-list authors_raw yields empty.
        record = _s2_record(
            authors=[{"name": "Ok"}, "not a dict", {"name": ""}, {"name": None}]
        )
        paper = _map_s2_paper(record)
        assert paper is not None
        assert paper["authors"] == ["Ok"]

        record2 = _s2_record(authors="literally-a-string")
        paper2 = _map_s2_paper(record2)
        assert paper2 is not None
        assert paper2["authors"] == []


# ---------------------------------------------------------------------------
# _arxiv_url_to_s2_id
# ---------------------------------------------------------------------------


class TestArxivUrlToS2Id:
    def test_arxiv_url_becomes_arxiv_prefixed_id(self) -> None:
        assert (
            _arxiv_url_to_s2_id("http://arxiv.org/abs/2311.09000")
            == "ARXIV:2311.09000"
        )
        assert (
            _arxiv_url_to_s2_id("https://arxiv.org/abs/2311.09000")
            == "ARXIV:2311.09000"
        )

    def test_arxiv_url_with_trailing_slash(self) -> None:
        assert (
            _arxiv_url_to_s2_id("http://arxiv.org/abs/2311.09000/")
            == "ARXIV:2311.09000"
        )

    def test_s2_prefixed_id_returned_bare(self) -> None:
        assert _arxiv_url_to_s2_id("s2:abc123") == "abc123"

    def test_unknown_form_passes_through(self) -> None:
        # An id we don't recognize is handed to S2 as-is; S2 will error
        # and `_get_json` will swallow. That's acceptable and preserves
        # user-provided handles (e.g. `DOI:...`).
        assert _arxiv_url_to_s2_id("DOI:10.5555/foo") == "DOI:10.5555/foo"


# ---------------------------------------------------------------------------
# _headers — API key handling
# ---------------------------------------------------------------------------


class TestHeaders:
    def test_no_key_returns_empty_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            s2_module, "settings", Settings(semantic_scholar_api_key="")
        )
        assert _headers() == {}

    def test_with_key_returns_x_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            s2_module,
            "settings",
            Settings(semantic_scholar_api_key="test-key"),
        )
        assert _headers() == {"x-api-key": "test-key"}


# ---------------------------------------------------------------------------
# search_papers / get_references — network-fronting; stub _get_json
# ---------------------------------------------------------------------------


class TestSearchPapers:
    def test_empty_query_returns_empty(self) -> None:
        assert search_papers("", limit=5) == []
        assert search_papers("   ", limit=5) == []

    def test_zero_limit_returns_empty(self) -> None:
        assert search_papers("rag", limit=0) == []

    def test_maps_data_list_via_mapper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_get(path: str, params: dict[str, Any]) -> Any:
            captured["path"] = path
            captured["params"] = params
            return {
                "data": [
                    _s2_record(paperId="a", title="A"),
                    _s2_record(paperId="b", title="B", abstract=None),
                    _s2_record(paperId="c", title="C"),
                ]
            }

        monkeypatch.setattr(s2_module, "_get_json", fake_get)
        results = search_papers("rag", limit=10)
        assert captured["path"] == "/paper/search"
        assert captured["params"]["query"] == "rag"
        assert captured["params"]["limit"] == 10
        assert [p["title"] for p in results] == ["A", "C"]

    def test_bad_response_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # `_get_json` returns None on failure.
        monkeypatch.setattr(s2_module, "_get_json", lambda p, params: None)
        assert search_papers("rag", limit=5) == []

    def test_non_list_data_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            s2_module, "_get_json", lambda p, params: {"data": "not a list"}
        )
        assert search_papers("rag", limit=5) == []


class TestGetReferences:
    def test_empty_paper_id_returns_empty(self) -> None:
        assert get_references("", limit=5) == []
        assert get_references("   ", limit=5) == []

    def test_zero_limit_returns_empty(self) -> None:
        assert get_references("ARXIV:foo", limit=0) == []

    def test_extracts_citedPaper_from_edges(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_get(path: str, params: dict[str, Any]) -> Any:
            captured["path"] = path
            return {
                "data": [
                    {"citedPaper": _s2_record(paperId="ref-a", title="Ref A")},
                    {"citedPaper": _s2_record(paperId="ref-b", title="Ref B")},
                    # Malformed edges silently skipped:
                    {"citedPaper": None},
                    "not a dict",
                    {"other_key": "no citedPaper"},
                ]
            }

        monkeypatch.setattr(s2_module, "_get_json", fake_get)
        results = get_references("ARXIV:2311.09000", limit=5)
        assert captured["path"] == "/paper/ARXIV:2311.09000/references"
        assert [p["title"] for p in results] == ["Ref A", "Ref B"]

    def test_bad_response_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(s2_module, "_get_json", lambda p, params: None)
        assert get_references("ARXIV:foo", limit=5) == []


# ---------------------------------------------------------------------------
# Adapter surface / constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_api_base_is_v1_graph(self) -> None:
        # Sanity: if S2 changes their versioning we should fail loudly here.
        assert S2_API_BASE == "https://api.semanticscholar.org/graph/v1"
