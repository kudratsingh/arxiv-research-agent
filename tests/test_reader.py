"""Unit tests for the reader agent.

Covers the pure prompt-builder and the context-gathering pipeline (with
`parse_pdf` / `chunk_paper` / `rank_chunks_by_relevance` monkeypatched so
no PDFs are downloaded and no model is loaded).

The full `_analyze_paper` and `reader_agent` paths are exercised at
integration time (they call Claude); this file stays fast and offline.
"""

from typing import Any

import pytest

from src.agents import reader as reader_module
from src.agents.reader import (
    MAX_CHUNKS_PER_PAPER,
    _build_user_prompt,
    _gather_context,
)
from src.graph.state import PaperMetadata


def _mk_paper(
    *,
    title: str = "Some Paper",
    abstract: str = "An abstract.",
    pdf_url: str = "http://arxiv.org/pdf/1234.56789",
) -> PaperMetadata:
    return PaperMetadata(
        id="http://arxiv.org/abs/1234.56789",
        title=title,
        authors=["A"],
        abstract=abstract,
        url="http://arxiv.org/abs/1234.56789",
        pdf_url=pdf_url,
    )


class TestBuildUserPrompt:
    def test_always_includes_query_title_abstract(self) -> None:
        paper = _mk_paper(title="Hallu Survey", abstract="LLMs hallucinate.")
        prompt = _build_user_prompt(paper, "How to reduce hallucination?", "")
        assert "Research question: How to reduce hallucination?" in prompt
        assert "Paper title: Hallu Survey" in prompt
        assert "LLMs hallucinate." in prompt

    def test_with_context_includes_excerpts_section(self) -> None:
        paper = _mk_paper()
        context = "[method] We fine-tune ..."
        prompt = _build_user_prompt(paper, "Q?", context)
        assert "Relevant excerpts from the paper's full text" in prompt
        assert "[method] We fine-tune ..." in prompt
        assert "Full text unavailable" not in prompt

    def test_without_context_notes_fallback(self) -> None:
        paper = _mk_paper()
        prompt = _build_user_prompt(paper, "Q?", "")
        assert "Full text unavailable" in prompt
        assert "abstract only" in prompt


class TestGatherContextFallback:
    def test_pdf_fetch_failure_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "")
        result = _gather_context(_mk_paper(), ["what is X?"])
        assert result == ""

    def test_no_chunks_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "parse_pdf", lambda _url: "some text"
        )
        monkeypatch.setattr(reader_module, "chunk_paper", lambda _text: [])
        result = _gather_context(_mk_paper(), ["what is X?"])
        assert result == ""

    def test_empty_ranked_result_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "parse_pdf", lambda _url: "some text"
        )
        monkeypatch.setattr(
            reader_module,
            "chunk_paper",
            lambda _text: [
                {"section": "method", "text": "m", "chunk_index": 0}
            ],
        )
        monkeypatch.setattr(
            reader_module,
            "rank_chunks_by_relevance",
            lambda _c, _s, top_k: [],
        )
        result = _gather_context(_mk_paper(), ["Q"])
        assert result == ""


class TestGatherContextFormatting:
    def test_formats_ranked_chunks_with_section_tags(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "parse_pdf", lambda _url: "full paper text"
        )
        monkeypatch.setattr(
            reader_module,
            "chunk_paper",
            lambda _text: [
                {"section": "introduction", "text": "intro body", "chunk_index": 0},
                {"section": "method", "text": "method body", "chunk_index": 0},
                {"section": "results", "text": "results body", "chunk_index": 0},
            ],
        )

        captured: dict[str, Any] = {}

        def fake_rank(
            chunks: list[Any], subqs: list[str], top_k: int
        ) -> list[dict[str, Any]]:
            captured["chunks"] = chunks
            captured["subqs"] = subqs
            captured["top_k"] = top_k
            return [
                {
                    "section": "method",
                    "text": "method body",
                    "chunk_index": 0,
                    "relevance_score": 0.9,
                },
                {
                    "section": "results",
                    "text": "results body",
                    "chunk_index": 0,
                    "relevance_score": 0.7,
                },
            ]

        monkeypatch.setattr(reader_module, "rank_chunks_by_relevance", fake_rank)

        result = _gather_context(_mk_paper(), ["sub-question a", "sub-question b"])

        # Format: each chunk on its own with [section] tag, separated by blank line.
        assert result == (
            "[method] method body\n\n[results] results body"
        )
        # Ranker gets the paper's chunks, the sub-questions, and MAX_CHUNKS_PER_PAPER
        assert captured["chunks"] and len(captured["chunks"]) == 3
        assert captured["subqs"] == ["sub-question a", "sub-question b"]
        assert captured["top_k"] == MAX_CHUNKS_PER_PAPER
