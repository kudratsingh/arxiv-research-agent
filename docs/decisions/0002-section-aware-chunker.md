# 0002. Roll our own section-aware chunker over generic markdown splitters

- **Status**: accepted
- **Date**: 2026-07-05

## Context

Phase 2 requires splitting extracted paper text into chunks for FAISS
ranking against sub-questions and downstream reader consumption. Chunks
must carry section labels (Abstract / Introduction / Method / Results /
...) so the reader and synthesizer can reason about which part of a
paper a claim came from and so citations preserve provenance.

Input is PyMuPDF page-text output — mostly plain prose with occasional
line-broken headers like `1 Introduction`, `2.1 Method`, `II. Results`,
or `INTRODUCTION`.

## Decision

Ship `src/tools/chunker.py` with a regex-driven header detector tuned
to academic paper structure, plus paragraph/sentence-aware budget
splitting. Chunks are returned as `{section, text, chunk_index}`
`TypedDict`s.

- Header pattern: `^\s*(?:\d{1,2}(?:\.\d+)*\.?\s+|[IVX]{1,4}\.\s+)?<header>\s*$`
  where `<header>` is one of a fixed set (Abstract, Introduction, Method,
  Results, ...).
- Sections are split into chunks under a token budget with overlap for
  continuity. Boundary preference: paragraph, then sentence, then hard cut.
- Fallback: documents with no detectable headers produce `body` chunks.

## Alternatives considered

- **LangChain `MarkdownHeaderTextSplitter`** — rejected: expects
  markdown `#` headers, not the plain / numeric / Roman forms PyMuPDF
  produces.
- **LangChain `RecursiveCharacterTextSplitter`** — rejected: loses
  section labels, forcing us to reconstruct provenance downstream and
  defeating section-conditioned prompts.
- **`unstructured` library** — rejected for now: heavier dependency,
  primarily targets richer document formats (HTML, DOCX). Overkill for
  our page-text input. Reconsider if we ingest non-PDF sources.

## Consequences

- **Positive**:
  - Section labels are preserved end-to-end. The reader can
    section-condition its prompt; citations can point at the section a
    claim came from.
  - Pure function, no I/O, thread-safe — safe inside the reader's
    `ThreadPoolExecutor` fan-out under the project concurrency mandate.
  - No new heavyweight dependencies.
- **Negative**:
  - Regex is arXiv/ML-conference-tuned. Papers from other venues (IEEE,
    ACM) with non-standard header formats may fall back to `body`
    chunks. Acceptable for the current corpus.
  - Token budgeting uses a chars/4 heuristic; not exact.
- **Follow-ups**:
  - Swap the chars/4 heuristic for a real tokenizer
    (`tiktoken` cl100k_base or `anthropic.count_tokens`) when prompt-cost
    budgeting tightens.
  - Extend header list based on failures observed in real ingestions.
