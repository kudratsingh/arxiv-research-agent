"""Invariants of the section-aware chunker (ADR 0002, ADR 0069).

`chunk_paper` is a pure function over an unbounded input space — a
paper's extracted text is whatever PyMuPDF produced — and
`tests/test_chunker.py` pins a dozen documents someone thought of. The
properties below are what has to hold for *every* document, and the
first of them is the one no example test can state: that the chunker
is lossless, because "lossless" is a claim about the text that was
**not** generated.

The token budgets these strategies draw are deliberately small (5-50
rather than the shipped 800). Splitting is what the properties are
about, and a 20-character budget reaches it with a 20-character
document, which keeps the tier's wall clock in seconds.
"""

from __future__ import annotations

import string

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from src.tools.chunker import (
    _HEADER_PATTERN,
    CHARS_PER_TOKEN,
    SECTION_HEADERS,
    chunk_paper,
)

pytestmark = [pytest.mark.unit, pytest.mark.property]

#: Words are lowercase-only and drawn at random, so a generated body
#: spelling one of the 29 section headers is vanishingly unlikely; the
#: `assume` in `prose` closes the gap rather than trusting the odds.
_WORD = st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=12)
_SENTENCE = st.lists(_WORD, min_size=1, max_size=12).map(lambda w: " ".join(w) + ".")
_PARAGRAPH = st.lists(_SENTENCE, min_size=1, max_size=5).map(" ".join)

#: Padding for the whitespace-perturbation property. Spaces and tabs
#: only: a newline would move the header onto another line, which is a
#: change of document rather than of whitespace.
_PAD = st.text(alphabet=" \t", max_size=4)


@st.composite
def prose(draw: st.DrawFn, *, max_paragraphs: int = 4) -> str:
    """Free text carrying no section header on any line."""
    paragraphs = draw(st.lists(_PARAGRAPH, min_size=0, max_size=max_paragraphs))
    text = "\n\n".join(paragraphs)
    assume(_HEADER_PATTERN.search(text) is None)
    return text


@st.composite
def budget(draw: st.DrawFn) -> tuple[int, int]:
    """A `(max_tokens, overlap_tokens)` pair with the overlap under the budget.

    Drawn as a pair rather than independently so no example is
    discarded: an overlap at or above the budget drives
    `_split_by_budget` into its one-chunk-per-character degradation
    (ADR 0069 records it as a configuration hazard), which is a
    different question from the ones these properties ask.
    """
    max_tokens = draw(st.integers(min_value=5, max_value=50))
    return max_tokens, draw(st.integers(min_value=0, max_value=max_tokens - 1))


@st.composite
def sectioned_document(draw: st.DrawFn) -> tuple[str, list[tuple[str, str]]]:
    """A preamble plus `[(header, body), ...]`, unrendered.

    Returned unrendered so the perturbation property can lay the same
    document out twice with different whitespace around its headers.
    """
    preamble = draw(prose(max_paragraphs=1))
    sections = draw(
        st.lists(
            st.tuples(st.sampled_from(SECTION_HEADERS), prose(max_paragraphs=2)),
            min_size=1,
            max_size=4,
        )
    )
    return preamble, sections


def render(
    preamble: str, sections: list[tuple[str, str]], pads: list[tuple[str, str]]
) -> str:
    """Lay a document out with `pads[i]` of whitespace around header `i`."""
    blocks: list[str] = [preamble] if preamble else []
    for (header, body), (lead, trail) in zip(sections, pads, strict=True):
        blocks.append(f"{lead}{header}{trail}")
        blocks.append(body)
    return "\n\n".join(blocks)


def unpadded(document: tuple[str, list[tuple[str, str]]]) -> str:
    """Render a document with no padding at all."""
    preamble, sections = document
    return render(preamble, sections, [("", "")] * len(sections))


def dense(text: str) -> str:
    """The text with every whitespace character removed.

    The chunker strips each piece it emits, so whitespace at a chunk
    boundary is legitimately gone; a losslessness claim can only be
    about the characters that carry content.
    """
    return "".join(text.split())


def occurrences(source: str, piece: str) -> list[int]:
    """Every index at which `piece` sits in `source`."""
    found: list[int] = []
    index = source.find(piece)
    while index != -1:
        found.append(index)
        index = source.find(piece, index + 1)
    return found


def advance(source: str, covered: int, piece: str) -> int | None:
    """Fit `piece` into `source` without leaving a gap; return the new frontier.

    The chunker emits overlapping windows and the spans are not
    recoverable from the output, so coverage has to be established by
    *placing* each chunk somewhere consistent. Two facts make that
    tractable rather than a search.

    A chunk may start before the previous one ended, but never after —
    that is the gap the property is looking for — so `start <=
    covered` is the whole admissibility test. And a larger frontier
    weakly dominates a smaller one: it admits every placement the
    smaller admits and ends at least as far along. So carrying the
    single largest frontier forward is not a heuristic that might
    strand a later chunk; it is optimal, and a failure here means no
    consistent placement exists at all.

    Returns `None` when nothing is admissible, which is itself the
    failure: the chunk is not a contiguous slice of the source, or it
    starts past the text the chunks before it accounted for.
    """
    reachable = [
        start + len(piece)
        for start in occurrences(source, piece)
        if start <= covered
    ]
    if not reachable:
        return None
    return max(covered, *reachable)


@given(
    text=st.one_of(prose(), sectioned_document().map(unpadded)),
    budgets=budget(),
)
def test_no_chunk_exceeds_the_configured_token_budget(
    text: str, budgets: tuple[int, int]
) -> None:
    """No emitted chunk is longer than `max_tokens * CHARS_PER_TOKEN`.

    The budget is what downstream prompt-cost control is sized
    against, so a chunk over it is a bill nobody planned for.
    """
    max_tokens, overlap_tokens = budgets

    chunks = chunk_paper(text, max_tokens=max_tokens, overlap_tokens=overlap_tokens)

    ceiling = max_tokens * CHARS_PER_TOKEN
    for chunk in chunks:
        assert len(chunk["text"]) <= ceiling, (
            f"chunk of {len(chunk['text'])} chars exceeds the "
            f"{ceiling}-char budget: {chunk!r}"
        )


@given(text=prose(), budgets=budget())
def test_chunking_header_free_text_loses_none_of_it(
    text: str, budgets: tuple[int, int]
) -> None:
    """Every non-whitespace character of a header-free document survives, in order.

    Scoped to header-free text on purpose: `chunk_paper` deliberately
    drops a header *line* once it has used it as a label, so a
    sectioned document is lossy by design and the invariant would be
    false as stated. Everything the chunker is not deliberately
    discarding has to come out the other side.
    """
    max_tokens, overlap_tokens = budgets

    chunks = chunk_paper(text, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
    source = dense(text)

    if not source:
        assert chunks == []
        return

    covered = 0
    for chunk in chunks:
        piece = dense(chunk["text"])
        assert piece, f"the chunker emitted an all-whitespace chunk: {chunk!r}"
        frontier = advance(source, covered, piece)
        assert frontier is not None, (
            f"chunk {chunk!r} is not a contiguous slice of the source that "
            f"starts at or before content character {covered}"
        )
        covered = frontier

    assert covered == len(source), (
        f"the chunks cover {covered} of {len(source)} content characters; "
        f"{source[covered:]!r} was dropped"
    )


@given(text=prose(), budgets=budget())
def test_rechunking_a_chunk_returns_that_chunk_unchanged(
    text: str, budgets: tuple[int, int]
) -> None:
    """Chunking is idempotent: a chunk re-chunked at the same budget is itself.

    A chunk that split again would mean the first pass emitted
    something over budget; a chunk that came back altered would mean
    the chunker is not a function of its input alone, and the
    embedding cache — keyed on chunk text — would be keyed on a moving
    value.
    """
    max_tokens, overlap_tokens = budgets

    for chunk in chunk_paper(
        text, max_tokens=max_tokens, overlap_tokens=overlap_tokens
    ):
        # A hard cut can end a chunk immediately after a word that
        # begins a line, manufacturing a header line (`\s*$` matches at
        # end of string) that the whole document did not contain. That
        # is a property of slicing, not a chunker defect, and it is the
        # one case where re-chunking legitimately relabels.
        if _HEADER_PATTERN.search(chunk["text"]) is not None:
            continue
        again = chunk_paper(
            chunk["text"], max_tokens=max_tokens, overlap_tokens=overlap_tokens
        )
        assert [piece["text"] for piece in again] == [chunk["text"]]


@given(document=sectioned_document(), data=st.data())
def test_section_labels_and_bodies_ignore_whitespace_around_headers(
    document: tuple[str, list[tuple[str, str]]], data: st.DataObject
) -> None:
    """Padding a header line with spaces or tabs changes nothing in the output.

    A header's own line is layout, not content: extraction leaves
    ragged indentation and trailing spaces on it routinely, and a
    chunker whose section boundaries moved with that would label two
    extractions of the same paper differently.
    """
    preamble, sections = document
    pads = st.lists(
        st.tuples(_PAD, _PAD), min_size=len(sections), max_size=len(sections)
    )

    left = chunk_paper(render(preamble, sections, data.draw(pads)))
    right = chunk_paper(render(preamble, sections, data.draw(pads)))

    assert left == right


@given(document=sectioned_document())
def test_chunk_index_restarts_at_zero_for_each_section_and_never_skips(
    document: tuple[str, list[tuple[str, str]]],
) -> None:
    """`chunk_index` counts within a section: it is 0, or one past its predecessor.

    `chunk_paper`'s docstring promises the index restarts per section,
    and downstream code reassembles reading order from it. A single
    global counter would satisfy every example test that looks at only
    one section.
    """
    chunks = chunk_paper(unpadded(document))
    assume(chunks)

    assert chunks[0]["chunk_index"] == 0
    for previous, current in zip(chunks, chunks[1:], strict=False):
        if current["chunk_index"] == 0:
            continue
        assert current["chunk_index"] == previous["chunk_index"] + 1
        assert current["section"] == previous["section"], (
            "a continuing chunk_index crossed a section boundary: "
            f"{previous!r} -> {current!r}"
        )
