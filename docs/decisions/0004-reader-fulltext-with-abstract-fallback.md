# 0004. Reader consumes ranked full-text chunks with abstract fallback

- **Status**: accepted
- **Date**: 2026-07-05
- **Supersedes**: the Phase-1 abstract-only reader path implicit in ADR
  0001's original scope

## Context

The Phase-2 building blocks — `pdf_parser` (ADR follow-up on PR #2),
`chunker` (ADR [0002](0002-section-aware-chunker.md)), and
`chunk_ranker` (ADR [0003](0003-chunk-ranker-max-similarity.md)) — are
in `main`. The reader was still calling Claude with title + abstract
only, wasting the retrieval pipeline built specifically to feed it.

Wiring them together introduces failure modes that didn't exist before:
PDFs can 404, arXiv can rate-limit downloads, PyMuPDF can barf on
unusual layouts, and the chunker can produce zero results on
non-standard headers. We need a strategy for what happens when any
stage of `parse_pdf -> chunk_paper -> rank_chunks_by_relevance`
returns nothing.

## Decision

For each paper, the reader runs the pipeline `parse_pdf -> chunk_paper
-> rank_chunks_by_relevance` and passes the top-K ranked chunks to
Claude alongside title + abstract. If **any** stage yields an empty
result, the reader gracefully falls back to abstract-only analysis
(the previous behavior) and tells Claude explicitly that full text
was unavailable.

- `K = 5` (`MAX_CHUNKS_PER_PAPER` in `src/agents/reader.py`) — bounds
  per-paper prompt size at ~5 × 800 tokens.
- Ranker input: the planner's `state["sub_questions"]`, not the raw
  query — sub-questions are what the planner decomposed the query into
  for coverage.
- Prompt structure: title + abstract are always present; excerpts
  section is appended when available and section-tagged
  (`[method] ...`).
- Fallback signal is explicit in the prompt so the model can calibrate
  the `relevance` score accordingly.
- Reader continues to fan out via `ThreadPoolExecutor(max_workers=5)`;
  each worker owns its own PDF download → extraction → encode → LLM
  call. The MiniLM model is a module-level singleton, shared read-only
  across threads (standard PyTorch inference pattern).

## Alternatives considered

- **Hard-fail the paper on any PDF failure.** Rejected: destroys
  coverage. arXiv rate-limits are common and non-deterministic; losing
  papers to transient network hiccups would degrade every re-run.
- **Retry the whole paper if the PDF failed.** Rejected: PDFs that
  return a non-PDF response body or 404 don't recover on retry.
  Retries belong at the HTTP layer (a future `feat/anthropic-retry` +
  `feat/arxiv-retry` pair), not at the agent layer.
- **Feed the whole PDF text unranked.** Rejected on the cost /
  attention grounds already argued in ADR 0002 and 0003.
- **Pass sub-questions to the LLM as separate calls (one prompt per
  sub-question).** Rejected: N-fold multiplier on cost with unclear
  quality gain. Max-similarity ranking already aggregates
  sub-question coverage at retrieval time.

## Consequences

- **Positive**:
  - Full-text-aware analysis when possible; graceful degradation when
    not. No paper is silently dropped.
  - The model knows whether it saw the full text — the `relevance`
    score becomes trustworthy across mixed-availability batches.
  - Reader stays a pure state → state function; failure handling is
    local to `_gather_context`, not the workflow.
- **Negative**:
  - A batch where every PDF fails looks (to state-level observers)
    identical to a Phase-1 run. Only the AIMessage says
    "full-text where available." Follow-up: emit a structured
    per-paper "source: fulltext|abstract" field so eval can attribute
    quality regressions.
  - Prompt tokens per paper roughly double vs Phase-1. Cost is
    manageable at K=5 chunks × 10 papers = 50 chunks × ~800 tokens =
    40k tokens per run; tighten K if this becomes a budget issue.
- **Follow-ups**:
  - HTTP retry / backoff for arXiv PDF downloads
    (`feat/arxiv-download-retry`).
  - Emit a per-paper `source: "fulltext" | "abstract"` field in
    `PaperAnalysis` for observability (`feat/reader-provenance`).
