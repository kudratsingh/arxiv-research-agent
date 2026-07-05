"""Unit tests for the section-aware chunker."""

from src.tools.chunker import CHARS_PER_TOKEN, chunk_paper


class TestEmptyAndTrivial:
    def test_empty_string_returns_empty(self) -> None:
        assert chunk_paper("") == []

    def test_whitespace_only_returns_empty(self) -> None:
        assert chunk_paper("   \n\n \t  ") == []

    def test_short_document_no_headers_single_body_chunk(self) -> None:
        text = "A short standalone note with no section structure."
        result = chunk_paper(text)
        assert len(result) == 1
        assert result[0]["section"] == "body"
        assert result[0]["chunk_index"] == 0
        assert result[0]["text"] == text


class TestSectionDetection:
    def test_plain_headers_labeled_correctly(self) -> None:
        text = (
            "Abstract\nThis paper studies X.\n\n"
            "Introduction\nWe motivate the problem.\n\n"
            "Method\nWe propose Y.\n\n"
            "Results\nY works well.\n"
        )
        sections = [c["section"] for c in chunk_paper(text)]
        assert sections == ["abstract", "introduction", "method", "results"]

    def test_numeric_prefix_headers(self) -> None:
        text = (
            "1 Introduction\nMotivation here.\n\n"
            "2. Method\nOur approach.\n\n"
            "3.1 Ablation\nWe ablate.\n"
        )
        sections = [c["section"] for c in chunk_paper(text)]
        assert sections == ["introduction", "method", "ablation"]

    def test_roman_numeral_headers(self) -> None:
        text = "I. Introduction\nbody\n\nII. Method\nmore body\n"
        sections = [c["section"] for c in chunk_paper(text)]
        assert sections == ["introduction", "method"]

    def test_uppercase_headers(self) -> None:
        text = "INTRODUCTION\nbody\n\nCONCLUSION\nend\n"
        sections = [c["section"] for c in chunk_paper(text)]
        assert sections == ["introduction", "conclusion"]

    def test_header_word_in_body_does_not_trigger(self) -> None:
        text = (
            "Introduction\n"
            "In the introduction we describe results.\n"
            "The method section will follow.\n"
        )
        result = chunk_paper(text)
        # Only the standalone "Introduction" line should be a header.
        assert [c["section"] for c in result] == ["introduction"]


class TestPreamble:
    def test_text_before_first_header_is_preamble(self) -> None:
        text = (
            "A Great Paper\nJane Doe, John Roe\n\n"
            "Abstract\nWhat we did.\n"
        )
        result = chunk_paper(text)
        assert result[0]["section"] == "preamble"
        assert "Jane Doe" in result[0]["text"]
        assert result[1]["section"] == "abstract"


class TestChunking:
    def test_long_section_splits_with_incrementing_chunk_index(self) -> None:
        # Build a body well over the 800-token (~3200 char) default.
        paragraph = ("This is a sentence. " * 50).strip()  # ~1000 chars
        body = "\n\n".join([paragraph] * 5)  # ~5000 chars
        text = f"Method\n{body}\n"

        result = chunk_paper(text)
        method_chunks = [c for c in result if c["section"] == "method"]
        assert len(method_chunks) >= 2
        assert [c["chunk_index"] for c in method_chunks] == list(
            range(len(method_chunks))
        )
        for chunk in method_chunks:
            assert len(chunk["text"]) <= 800 * CHARS_PER_TOKEN

    def test_chunk_index_resets_per_section(self) -> None:
        paragraph = ("Sentence content here. " * 40).strip()
        body = "\n\n".join([paragraph] * 5)
        text = f"Method\n{body}\n\nResults\n{body}\n"

        result = chunk_paper(text)
        by_section: dict[str, list[int]] = {}
        for chunk in result:
            by_section.setdefault(chunk["section"], []).append(chunk["chunk_index"])
        for section, indices in by_section.items():
            assert indices == list(range(len(indices))), (
                f"section {section} indices: {indices}"
            )

    def test_no_headers_long_doc_falls_back_to_body_chunks(self) -> None:
        text = ("A sentence of prose. " * 500).strip()  # ~10000 chars
        result = chunk_paper(text)
        assert len(result) >= 2
        assert all(c["section"] == "body" for c in result)
        assert [c["chunk_index"] for c in result] == list(range(len(result)))


class TestCustomBudget:
    def test_smaller_budget_produces_more_chunks(self) -> None:
        text = ("Sentence content here. " * 200).strip()
        default_result = chunk_paper(text)
        tight_result = chunk_paper(text, max_tokens=100, overlap_tokens=10)
        assert len(tight_result) > len(default_result)
