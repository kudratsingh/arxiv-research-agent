"""Tests for the prior-context retriever (ADR 0032)."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from src.api.conversations import Conversation, ConversationJob
from src.api.retriever import (
    MAX_CHUNK_CHARS,
    MIN_CHUNK_CHARS,
    format_context_for_planner,
    retrieve_prior_context,
)


def _job(ordinal: int, query: str, report: str) -> ConversationJob:
    return ConversationJob(
        job_id=f"j{ordinal}",
        ordinal=ordinal,
        query=query,
        report=report,
    )


class TestChunkingBehavior:
    """The chunker isn't exposed but its behavior is observable via
    the retriever's output — grouping, section attribution."""

    def test_empty_conversation_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conv = Conversation(conversation_id="c", title="T")
        assert retrieve_prior_context(conv, "any query", top_k=5) == []

    def test_top_k_zero_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conv = Conversation(
            conversation_id="c",
            title="T",
            jobs=[_job(1, "q", "# Sec\n\n" + "text " * 50)],
        )
        assert retrieve_prior_context(conv, "q", top_k=0) == []

    def test_report_with_headings_is_section_attributed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        report = (
            "# Training-time approaches\n\n"
            + "Training methods discussion. " * 10
            + "\n\n"
            + "# Generation-time approaches\n\n"
            + "Generation methods discussion. " * 10
        )
        # Stub encoder — return orthogonal vectors so exactly one
        # section wins for a given query.
        stubbed = _make_stub_encoder(
            {
                "Training methods discussion.": np.array([1.0, 0.0], dtype=np.float32),
                "Generation methods discussion.": np.array([0.0, 1.0], dtype=np.float32),
                "prompt about training": np.array([1.0, 0.0], dtype=np.float32),
            }
        )
        monkeypatch.setattr("src.api.retriever.encode_texts", stubbed)

        conv = Conversation(
            conversation_id="c",
            title="T",
            jobs=[_job(1, "prev q", report)],
        )
        chunks = retrieve_prior_context(conv, "prompt about training", top_k=1)
        assert len(chunks) == 1
        assert chunks[0]["section"] == "Training-time approaches"
        assert chunks[0]["ordinal"] == 1

    def test_report_below_min_chunk_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A tiny report — under MIN_CHUNK_CHARS — has no chunks.
        conv = Conversation(
            conversation_id="c",
            title="T",
            jobs=[_job(1, "q", "# Tiny\n\ntoo short")],
        )
        assert retrieve_prior_context(conv, "q", top_k=5) == []


class TestRankingBehavior:
    def test_returns_top_k_ordered_by_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Three sections, each distinguishable by encoder output.
        # The query embedding matches one perfectly and the other
        # two partially.
        report = (
            "# A\n\n" + "aa " * 40 + "\n\n"
            "# B\n\n" + "bb " * 40 + "\n\n"
            "# C\n\n" + "cc " * 40
        )
        # Return distinct vectors per chunk text prefix.
        def _stub_encode(texts: list[str]) -> np.ndarray:
            out = np.zeros((len(texts), 3), dtype=np.float32)
            for i, t in enumerate(texts):
                if "aa" in t:
                    out[i] = np.array([1.0, 0.0, 0.0])
                elif "bb" in t:
                    out[i] = np.array([0.9, 0.5, 0.0])
                    out[i] /= np.linalg.norm(out[i])
                elif "cc" in t:
                    out[i] = np.array([0.5, 0.9, 0.0])
                    out[i] /= np.linalg.norm(out[i])
                else:
                    # query embedding
                    out[i] = np.array([1.0, 0.0, 0.0])
            return out

        monkeypatch.setattr("src.api.retriever.encode_texts", _stub_encode)

        conv = Conversation(
            conversation_id="c",
            title="T",
            jobs=[_job(1, "q", report)],
        )
        chunks = retrieve_prior_context(conv, "match aa", top_k=3)
        # Top result should be A (perfect match), then B (partial), then C.
        assert chunks[0]["section"] == "A"
        assert chunks[0]["relevance_score"] > chunks[1]["relevance_score"]
        assert chunks[1]["relevance_score"] > chunks[2]["relevance_score"]


class TestFormatContextForPlanner:
    def test_empty_chunks_returns_empty_string(self) -> None:
        assert format_context_for_planner([]) == ""

    def test_includes_ordinal_query_section_and_text(self) -> None:
        chunks = [
            {
                "job_id": "j1",
                "ordinal": 1,
                "query": "hallucination survey",
                "section": "Training-time",
                "text": "RLHF-V uses fine-grained feedback",
                "relevance_score": 0.9,
            },
        ]
        out = format_context_for_planner(chunks)  # type: ignore[arg-type]
        assert "Prior findings" in out
        assert "query 1: hallucination survey" in out
        assert "section: Training-time" in out
        assert "RLHF-V uses fine-grained feedback" in out

    def test_empty_section_falls_back_to_introduction(self) -> None:
        chunks = [
            {
                "job_id": "j1",
                "ordinal": 1,
                "query": "q",
                "section": "",
                "text": "preamble body",
                "relevance_score": 0.5,
            },
        ]
        out = format_context_for_planner(chunks)  # type: ignore[arg-type]
        assert "section: (introduction)" in out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stub_encoder(
    lookup: dict[str, np.ndarray],
) -> Callable[[list[str]], np.ndarray]:
    """Return an encoder that maps texts to precomputed L2-normalized
    vectors by substring match; unknown texts get a zero-vector so
    they don't dominate the search."""

    def encode(texts: list[str]) -> np.ndarray:
        vecs: list[np.ndarray] = []
        for t in texts:
            match: np.ndarray | None = None
            for key, vec in lookup.items():
                if key in t:
                    match = vec
                    break
            if match is None:
                match = np.zeros_like(next(iter(lookup.values())))
            # Ensure L2-normalized for cosine consistency.
            norm = np.linalg.norm(match)
            if norm > 0:
                match = match / norm
            vecs.append(match)
        return np.array(vecs, dtype=np.float32)

    return encode


class TestChunkSizeGuardrails:
    """Regression: MIN_CHUNK_CHARS / MAX_CHUNK_CHARS values shape how
    retrieval-friendly the chunks are. Freeze them to catch accidental
    tuning."""

    def test_min_chunk_chars_reasonable(self) -> None:
        assert 50 <= MIN_CHUNK_CHARS <= 200

    def test_max_chunk_chars_reasonable(self) -> None:
        # ~200-300 tokens fits comfortably in a planner prompt for K=5.
        assert 500 <= MAX_CHUNK_CHARS <= 1500
