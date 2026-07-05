"""Section-aware chunker for academic paper full text.

Detects standard academic section headers (Abstract, Introduction, Method,
Results, ...) in PyMuPDF-extracted text and splits each section into
chunks that fit under a target token budget, with overlap for continuity.

Pure function, stateless, thread-safe — designed to run inside any
concurrent fan-out.
"""

import re
from typing import TypedDict

DEFAULT_MAX_TOKENS = 800
DEFAULT_OVERLAP_TOKENS = 100

# Rough industry heuristic: 1 token ~= 4 characters of English prose.
# Swap for a real tokenizer (tiktoken / anthropic count_tokens) if we
# need tight budgeting for prompt-cost control.
CHARS_PER_TOKEN = 4

SECTION_HEADERS = (
    "abstract",
    "introduction",
    "related work",
    "background",
    "preliminaries",
    "problem statement",
    "problem formulation",
    "methodology",
    "methods",
    "method",
    "approach",
    "model",
    "architecture",
    "experimental setup",
    "experiments",
    "evaluation",
    "results",
    "analysis",
    "discussion",
    "ablation study",
    "ablation",
    "limitations",
    "conclusions",
    "conclusion",
    "future work",
    "references",
    "acknowledgments",
    "acknowledgements",
    "appendix",
)

_HEADER_PATTERN = re.compile(
    r"^\s*"
    r"(?:\d{1,2}(?:\.\d+)*\.?\s+|[IVX]{1,4}\.\s+)?"
    r"(" + "|".join(re.escape(h) for h in SECTION_HEADERS) + r")"
    r"\s*$",
    re.IGNORECASE | re.MULTILINE,
)


class Chunk(TypedDict):
    """A section-labeled slice of a paper's full text."""

    section: str
    text: str
    chunk_index: int


def _split_by_budget(
    text: str, max_tokens: int, overlap_tokens: int
) -> list[str]:
    """Split `text` into chunks under `max_tokens`, with `overlap_tokens` overlap.

    Prefers to break on paragraph (\\n\\n) then sentence (". ") boundaries
    within the target window; falls back to a hard cut if neither is
    available.
    """
    max_chars = max_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN

    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            para = text.rfind("\n\n", start, end)
            if para > start + max_chars // 2:
                end = para
            else:
                sent = text.rfind(". ", start, end)
                if sent > start + max_chars // 2:
                    end = sent + 1

        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)

        if end >= len(text):
            break
        start = max(start + 1, end - overlap_chars)

    return chunks


def chunk_paper(
    full_text: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Split a paper's full text into section-labeled chunks.

    Detects standard academic headers on their own line (with optional
    numeric or Roman prefix — "1 Introduction", "2.1 Method", "III. Results")
    and splits each section into chunks under `max_tokens`. Consecutive
    chunks within the same section share `overlap_tokens` of context.

    Text before the first detected header is labeled "preamble" (typically
    title / author block). Documents with no detectable headers fall back
    to fixed-size chunking labeled "body".

    Args:
        full_text: Concatenated PDF-extracted text of a paper.
        max_tokens: Target maximum tokens per chunk.
        overlap_tokens: Overlap between consecutive chunks in the same section.

    Returns:
        Ordered list of Chunk dicts. `chunk_index` restarts per section.
    """
    if not full_text or not full_text.strip():
        return []

    matches = list(_HEADER_PATTERN.finditer(full_text))

    if not matches:
        return [
            Chunk(section="body", text=piece, chunk_index=i)
            for i, piece in enumerate(
                _split_by_budget(full_text, max_tokens, overlap_tokens)
            )
        ]

    chunks: list[Chunk] = []

    preamble = full_text[: matches[0].start()].strip()
    if preamble:
        for i, piece in enumerate(
            _split_by_budget(preamble, max_tokens, overlap_tokens)
        ):
            chunks.append(Chunk(section="preamble", text=piece, chunk_index=i))

    for idx, match in enumerate(matches):
        section = match.group(1).lower().strip()
        body_start = match.end()
        body_end = (
            matches[idx + 1].start() if idx + 1 < len(matches) else len(full_text)
        )
        body = full_text[body_start:body_end].strip()
        if not body:
            continue
        for i, piece in enumerate(
            _split_by_budget(body, max_tokens, overlap_tokens)
        ):
            chunks.append(Chunk(section=section, text=piece, chunk_index=i))

    return chunks
