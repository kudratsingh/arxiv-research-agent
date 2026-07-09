"""Unit tests for the chunk ranker.

Covers the pure numpy reduction (`_max_similarity_per_chunk`) and the
early-exit branches of `rank_chunks_by_relevance` (empty chunks, empty
sub-questions). The model-backed happy path is exercised at integration
time — this file stays fast and does not import `sentence_transformers`.
"""

import numpy as np
import pytest

from src.tools.chunk_ranker import (
    RankedChunk,
    _apply_preferred_sections,
    _max_similarity_per_chunk,
    rank_chunks_by_relevance,
)
from src.tools.chunker import Chunk


def _mk_chunk(section: str, text: str, idx: int) -> Chunk:
    return Chunk(section=section, text=text, chunk_index=idx)


class TestMaxSimilarityPerChunk:
    def test_single_query_maps_to_chunk_indices(self) -> None:
        scores = np.array([[0.9, 0.5, 0.1]], dtype=np.float32)
        indices = np.array([[2, 0, 1]], dtype=np.int64)
        assert _max_similarity_per_chunk(scores, indices, 3) == pytest.approx(
            [0.5, 0.1, 0.9]
        )

    def test_multiple_queries_takes_max(self) -> None:
        # Two sub-questions, three chunks.
        # Q0: chunk 0 -> 0.4, chunk 1 -> 0.9, chunk 2 -> 0.2
        # Q1: chunk 0 -> 0.7, chunk 1 -> 0.3, chunk 2 -> 0.8
        # Max per chunk:      0 -> 0.7,       1 -> 0.9,      2 -> 0.8
        scores = np.array(
            [
                [0.9, 0.4, 0.2],
                [0.8, 0.7, 0.3],
            ],
            dtype=np.float32,
        )
        indices = np.array(
            [
                [1, 0, 2],
                [2, 0, 1],
            ],
            dtype=np.int64,
        )
        result = _max_similarity_per_chunk(scores, indices, 3)
        assert result == pytest.approx([0.7, 0.9, 0.8])

    def test_negative_indices_are_ignored(self) -> None:
        scores = np.array([[0.9, 0.5, 0.1]], dtype=np.float32)
        indices = np.array([[0, -1, 1]], dtype=np.int64)
        result = _max_similarity_per_chunk(scores, indices, 2)
        assert result == pytest.approx([0.9, 0.1])

    def test_out_of_range_indices_are_ignored(self) -> None:
        # FAISS shouldn't return indices >= n_chunks, but guard anyway.
        scores = np.array([[0.9, 0.5]], dtype=np.float32)
        indices = np.array([[0, 99]], dtype=np.int64)
        result = _max_similarity_per_chunk(scores, indices, 2)
        assert result == pytest.approx([0.9, 0.0])

    def test_chunks_never_returned_get_zero(self) -> None:
        scores = np.array([[0.9]], dtype=np.float32)
        indices = np.array([[0]], dtype=np.int64)
        result = _max_similarity_per_chunk(scores, indices, 3)
        assert result == pytest.approx([0.9, 0.0, 0.0])


class TestRankChunksEarlyExits:
    def test_empty_chunks_returns_empty(self) -> None:
        assert rank_chunks_by_relevance([], ["what is X?"]) == []

    def test_no_subquestions_returns_first_top_k_unscored(self) -> None:
        chunks = [
            _mk_chunk("intro", "A", 0),
            _mk_chunk("intro", "B", 1),
            _mk_chunk("method", "C", 0),
            _mk_chunk("results", "D", 0),
        ]
        result = rank_chunks_by_relevance(chunks, [], top_k=2)
        assert len(result) == 2
        assert all(r["relevance_score"] == 0.0 for r in result)
        assert [r["text"] for r in result] == ["A", "B"]

    def test_no_subquestions_respects_top_k_over_available(self) -> None:
        chunks = [_mk_chunk("intro", "A", 0)]
        result = rank_chunks_by_relevance(chunks, [], top_k=10)
        assert len(result) == 1

    def test_result_shape_matches_ranked_chunk_type(self) -> None:
        chunks = [_mk_chunk("intro", "A", 0)]
        result = rank_chunks_by_relevance(chunks, [], top_k=1)
        entry = result[0]
        # RankedChunk keys
        assert set(entry.keys()) == {
            "section",
            "text",
            "chunk_index",
            "relevance_score",
        }
        assert entry["section"] == "intro"
        assert entry["text"] == "A"
        assert entry["chunk_index"] == 0
        assert isinstance(entry["relevance_score"], float)


class TestRankedChunkType:
    def test_ranked_chunk_is_typed_dict_of_expected_fields(self) -> None:
        rc = RankedChunk(
            section="s", text="t", chunk_index=0, relevance_score=0.5
        )
        assert rc["section"] == "s"
        assert rc["text"] == "t"
        assert rc["chunk_index"] == 0
        assert rc["relevance_score"] == 0.5


# ---------------------------------------------------------------------------
# _apply_preferred_sections (ADR 0019) — reserves slots for requested sections.
# ---------------------------------------------------------------------------


class TestApplyPreferredSections:
    def _chunks(self) -> list[Chunk]:
        return [
            _mk_chunk("intro", "A", 0),
            _mk_chunk("method", "B", 1),
            _mk_chunk("results", "C", 2),
            _mk_chunk("limitations", "D", 3),
            _mk_chunk("conclusion", "E", 4),
        ]

    def test_empty_preferred_returns_top_k(self) -> None:
        # ranked_order sorted by score already; preferred=[] behaves like
        # a plain top-K truncation.
        result = _apply_preferred_sections(
            [0, 1, 2, 3, 4], self._chunks(), top_k=3, preferred_sections=[]
        )
        assert result == [0, 1, 2]

    def test_reserves_top_k_over_2_slots_for_preferred(self) -> None:
        # top_k=4, so 2 slots reserved for "results"/"limitations".
        # Ranked order is [0=intro, 1=method, 2=results, 3=limits, 4=concl].
        result = _apply_preferred_sections(
            [0, 1, 2, 3, 4],
            self._chunks(),
            top_k=4,
            preferred_sections=["results", "limitations"],
        )
        # Preferred first (2 slots), then top of the rest (2 slots).
        assert result[:2] == [2, 3]
        assert result[2:] == [0, 1]

    def test_case_insensitive_matching(self) -> None:
        result = _apply_preferred_sections(
            [0, 1, 2, 3, 4],
            self._chunks(),
            top_k=3,
            preferred_sections=["RESULTS"],
        )
        assert 2 in result[:1]

    def test_no_matching_preferred_falls_through_to_top_k(self) -> None:
        # "appendix" isn't a section in any chunk — behaves like no preference.
        result = _apply_preferred_sections(
            [0, 1, 2, 3, 4],
            self._chunks(),
            top_k=3,
            preferred_sections=["appendix"],
        )
        assert result == [0, 1, 2]

    def test_reserve_capped_at_available_preferred_count(self) -> None:
        # Only one preferred chunk exists — reserve doesn't over-allocate.
        result = _apply_preferred_sections(
            [0, 1, 2, 3, 4],
            self._chunks(),
            top_k=4,
            preferred_sections=["results"],
        )
        # top_k // 2 = 2, but only 1 "results" chunk exists.
        assert result[0] == 2
        # Rest fills from top of ranked_order excluding "results".
        assert result[1:] == [0, 1, 3]
