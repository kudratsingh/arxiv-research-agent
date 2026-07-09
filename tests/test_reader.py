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
    _analyze_paper,
    _build_evidence_user_prompt,
    _build_user_prompt,
    _format_numbered_chunks,
    _gather_context,
    _parse_claim,
    reader_agent,
)
from src.config import Settings
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
            lambda _c, _s, top_k, preferred_sections=None: [],
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
            chunks: list[Any],
            subqs: list[str],
            top_k: int,
            preferred_sections: list[str] | None = None,
        ) -> list[dict[str, Any]]:
            captured["chunks"] = chunks
            captured["subqs"] = subqs
            captured["top_k"] = top_k
            captured["preferred"] = preferred_sections
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


# ---------------------------------------------------------------------------
# Evidence store path (ADR 0016) — reader emits claims when flag is on.
# ---------------------------------------------------------------------------


def _fake_ranked_chunks() -> list[dict[str, Any]]:
    return [
        {
            "section": "method",
            "text": "We use retrieval augmented generation.",
            "chunk_index": 0,
            "relevance_score": 0.91,
        },
        {
            "section": "results",
            "text": "F1 rose from 0.62 to 0.78.",
            "chunk_index": 1,
            "relevance_score": 0.85,
        },
    ]


class TestNumberedChunkFormatting:
    def test_numbers_start_at_one_and_tag_section(self) -> None:
        formatted = _format_numbered_chunks(_fake_ranked_chunks())  # type: ignore[arg-type]
        assert formatted.startswith("[1] [method] We use")
        assert "[2] [results] F1 rose" in formatted


class TestEvidencePromptShape:
    def test_evidence_prompt_includes_sub_questions_and_numbered_excerpts(
        self,
    ) -> None:
        paper = _mk_paper(title="RAG survey", abstract="An abstract.")
        excerpts = _format_numbered_chunks(_fake_ranked_chunks())  # type: ignore[arg-type]
        prompt = _build_evidence_user_prompt(
            paper, "Q?", ["sub a", "sub b"], excerpts
        )
        assert "Sub-questions the report should cover:" in prompt
        assert "  - sub a" in prompt
        assert "  - sub b" in prompt
        assert "[1] [method]" in prompt
        assert "numbered, section-tagged" in prompt


class TestParseClaim:
    def _ranked(self) -> list[dict[str, Any]]:
        return _fake_ranked_chunks()

    def test_valid_claim_binds_to_source_text(self) -> None:
        claim = _parse_claim(
            {
                "claim": "RAG improves F1.",
                "chunk_index": 2,
                "supports_question": "sub b",
            },
            "p1",
            self._ranked(),  # type: ignore[arg-type]
            {"sub a", "sub b"},
        )
        assert claim is not None
        assert claim["claim"] == "RAG improves F1."
        assert claim["paper_id"] == "p1"
        assert claim["section"] == "results"
        assert claim["source_text"] == "F1 rose from 0.62 to 0.78."
        assert claim["relevance_score"] == 0.85
        assert claim["supports_question"] == "sub b"

    def test_out_of_range_chunk_index_drops_claim(self) -> None:
        claim = _parse_claim(
            {"claim": "x", "chunk_index": 99},
            "p1",
            self._ranked(),  # type: ignore[arg-type]
            set(),
        )
        assert claim is None

    def test_missing_chunk_index_drops_claim(self) -> None:
        claim = _parse_claim(
            {"claim": "x"},
            "p1",
            self._ranked(),  # type: ignore[arg-type]
            set(),
        )
        assert claim is None

    def test_empty_claim_dropped(self) -> None:
        claim = _parse_claim(
            {"claim": "  ", "chunk_index": 1},
            "p1",
            self._ranked(),  # type: ignore[arg-type]
            set(),
        )
        assert claim is None

    def test_unrecognized_supports_question_cleared(self) -> None:
        claim = _parse_claim(
            {
                "claim": "c",
                "chunk_index": 1,
                "supports_question": "hallucinated sub-question",
            },
            "p1",
            self._ranked(),  # type: ignore[arg-type]
            {"sub a"},
        )
        assert claim is not None
        # Not in the subquestion set -> cleared, not accepted verbatim.
        assert claim["supports_question"] == ""

    def test_non_dict_dropped(self) -> None:
        assert _parse_claim("bad", "p1", self._ranked(), set()) is None  # type: ignore[arg-type]


class TestAnalyzePaperEvidencePath:
    def _stub_pipeline(
        self,
        monkeypatch: pytest.MonkeyPatch,
        parsed_response: dict[str, Any],
        ranked: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Wire the reader pipeline stubs and return the captured LLM call."""
        monkeypatch.setattr(
            reader_module, "parse_pdf", lambda _url: "full text"
        )
        monkeypatch.setattr(
            reader_module,
            "chunk_paper",
            lambda _text: [
                {"section": "method", "text": "m", "chunk_index": 0}
            ],
        )
        chunks = ranked if ranked is not None else _fake_ranked_chunks()
        monkeypatch.setattr(
            reader_module,
            "rank_chunks_by_relevance",
            lambda _c, _s, top_k, preferred_sections=None: chunks,
        )

        captured: dict[str, Any] = {}

        def fake_llm(
            *, prompt: str, system_prompt: str, max_tokens: int
        ) -> dict[str, Any]:
            captured["prompt"] = prompt
            captured["system_prompt"] = system_prompt
            captured["max_tokens"] = max_tokens
            return parsed_response

        monkeypatch.setattr(reader_module, "call_llm_json", fake_llm)
        return captured

    def _base_response(self, **overrides: Any) -> dict[str, Any]:
        base = {
            "key_findings": ["a", "b"],
            "methodology": "m",
            "results_summary": "r",
            "limitations": "L",
            "relevance": 0.8,
        }
        base.update(overrides)
        return base

    def test_flag_off_returns_no_claims(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_evidence_store=False)
        )
        captured = self._stub_pipeline(monkeypatch, self._base_response())
        _, claims, _ = _analyze_paper(_mk_paper(), "Q?", ["sub a"])
        assert claims == []
        # System prompt is the baseline analysis prompt.
        assert "claims" not in captured["system_prompt"]

    def test_flag_on_extracts_and_binds_claims(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module,
            "settings",
            Settings(enable_evidence_store=True, reader_max_claims_per_paper=5),
        )
        response = self._base_response(
            claims=[
                {
                    "claim": "RAG works.",
                    "chunk_index": 1,
                    "supports_question": "sub a",
                },
                {
                    "claim": "F1 up.",
                    "chunk_index": 2,
                    "supports_question": "sub b",
                },
            ]
        )
        self._stub_pipeline(monkeypatch, response)
        analysis, claims, _ = _analyze_paper(_mk_paper(), "Q?", ["sub a", "sub b"])

        assert analysis["key_findings"] == ["a", "b"]
        assert len(claims) == 2
        assert claims[0]["claim"] == "RAG works."
        assert claims[0]["source_text"].startswith("We use")
        assert claims[1]["claim"] == "F1 up."
        assert claims[1]["source_text"].startswith("F1 rose")

    def test_flag_on_no_ranked_chunks_skips_claim_extraction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # PDF missing -> ranked=[] -> no claims regardless of flag.
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_evidence_store=True)
        )
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "")
        captured: dict[str, Any] = {}

        def fake_llm(**kwargs: Any) -> dict[str, Any]:
            captured["system_prompt"] = kwargs["system_prompt"]
            return self._base_response()

        monkeypatch.setattr(reader_module, "call_llm_json", fake_llm)

        _, claims, _ = _analyze_paper(_mk_paper(), "Q?", ["sub a"])
        assert claims == []
        # Falls back to the base analysis prompt (not the evidence prompt).
        assert "claims" not in captured["system_prompt"]

    def test_flag_on_caps_claims_at_config_limit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module,
            "settings",
            Settings(enable_evidence_store=True, reader_max_claims_per_paper=1),
        )
        response = self._base_response(
            claims=[
                {"claim": "one", "chunk_index": 1},
                {"claim": "two", "chunk_index": 2},
                {"claim": "three", "chunk_index": 1},
            ]
        )
        self._stub_pipeline(monkeypatch, response)
        _, claims, _ = _analyze_paper(_mk_paper(), "Q?", [])
        assert len(claims) == 1


class TestReaderAgentEmission:
    def test_flag_off_omits_evidence_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_evidence_store=False)
        )

        def fake_analyze(paper: PaperMetadata, *_a: Any, **_kw: Any) -> Any:
            return (
                {
                    "paper_id": paper["id"],
                    "title": paper["title"],
                    "key_findings": [],
                    "methodology": "",
                    "results_summary": "",
                    "limitations": "",
                    "relevance": 0.0,
                },
                [],
                {
                    "analysis_complete": True,
                    "missing_context": "",
                    "request_more_sections": [],
                },
            )

        monkeypatch.setattr(reader_module, "_analyze_paper", fake_analyze)
        state = {
            "papers": [_mk_paper()],
            "query": "Q?",
            "sub_questions": ["a"],
        }
        update = reader_agent(state)  # type: ignore[arg-type]
        # `evidence` is not in the returned update when the flag is off,
        # so it doesn't clobber whatever state might carry.
        assert "evidence" not in update
        assert len(update["paper_analyses"]) == 1

    def test_flag_on_includes_evidence_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_evidence_store=True)
        )

        def fake_analyze(paper: PaperMetadata, *_a: Any, **_kw: Any) -> Any:
            analysis = {
                "paper_id": paper["id"],
                "title": paper["title"],
                "key_findings": [],
                "methodology": "",
                "results_summary": "",
                "limitations": "",
                "relevance": 0.0,
            }
            claim = {
                "claim": "c",
                "paper_id": paper["id"],
                "section": "method",
                "source_text": "text",
                "relevance_score": 0.9,
                "supports_question": "",
            }
            signal = {
                "analysis_complete": True,
                "missing_context": "",
                "request_more_sections": [],
            }
            return analysis, [claim], signal

        monkeypatch.setattr(reader_module, "_analyze_paper", fake_analyze)
        state = {
            "papers": [_mk_paper()],
            "query": "Q?",
            "sub_questions": ["a"],
        }
        update = reader_agent(state)  # type: ignore[arg-type]
        assert "evidence" in update
        assert len(update["evidence"]) == 1
        assert update["evidence"][0]["source_text"] == "text"
