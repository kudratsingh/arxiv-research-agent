# 0003. Rank paper chunks by max cosine similarity across sub-questions

- **Status**: accepted
- **Date**: 2026-07-05

## Context

Phase 2 requires the reader to consume the *relevant* parts of each
paper's full text, not the whole thing — otherwise every read call
becomes a 20k+ token dump into Claude, which blows up latency, cost,
and quality of attention. The chunker (ADR
[0002](0002-section-aware-chunker.md)) already splits each paper into
section-labeled chunks. We need a ranker that picks the top-K chunks
for the reader per paper.

The planner produces 2-4 sub-questions per query. Any chunk that
strongly answers any one of those sub-questions is worth reading — a
chunk that discusses hallucination mitigation isn't punished for
ignoring the parallel sub-question about benchmarks.

## Decision

Ship `src/tools/chunk_ranker.py` with `rank_chunks_by_relevance(chunks,
subquestions, top_k) -> list[RankedChunk]`.

- Encode chunks and sub-questions with the shared MiniLM model via the
  `embeddings.encode_texts` helper (added in this PR).
- FAISS `IndexFlatIP` inner-product search over L2-normalized
  embeddings — equivalent to cosine similarity.
- Reduce the `(n_queries, n_chunks)` similarity matrix to
  **per-chunk max** across sub-questions.
- Return the top-K by score, sorted descending, each annotated with
  `relevance_score: float`.

`_max_similarity_per_chunk` is factored out as a pure numpy function
so it's cheap to unit-test without loading the encoder.

## Alternatives considered

- **Sum / mean across sub-questions.** Rejected: a chunk answering
  every sub-question a little is not what we want — we want the
  strongest signal per sub-question. Max preserves that.
- **Per-sub-question top-K/n rather than global top-K.** Attractive
  for coverage — guarantees every sub-question gets *some* chunk. But
  produces N × K chunks and forces the reader to reason about which
  sub-question a chunk maps to. Deferred; may revisit once we see
  coverage failures in the eval pipeline.
- **Reranker on top of embeddings (bge-reranker, Cohere Rerank, LLM
  scoring).** Deferred: adds latency and cost for uncertain gain at our
  chunk sizes. Consider once retrieval quality becomes the bottleneck.
- **Skip ranking, feed all chunks to the reader.** Rejected on
  cost/latency grounds under the production-scale mandate.

## Consequences

- **Positive**:
  - Bounded reader input: `top_k` chunks per paper regardless of paper
    length. Cost stays linear in paper count, not paper length.
  - Sub-question-aware — chunks are chosen against the planner's
    decomposition, not the raw query.
  - Reuses the shared MiniLM model (via `encode_texts`) — no additional
    dependency, no extra model load.
  - Pure function; safe inside the reader's concurrent fan-out.
- **Negative**:
  - Max reduction can under-cover sub-questions that produce weaker
    similarity signals overall. Watch this in eval.
  - MiniLM is a small general-purpose model. A retrieval-tuned model
    (bge-small, gte-small) would likely improve recall but adds
    dependency weight. Reconsider if retrieval becomes the bottleneck.
- **Follow-ups**:
  - Wire this into the reader (`feat/reader-fulltext`).
  - Extend the eval pipeline with a retrieval-quality metric so we can
    measure the impact of switching models or ranking strategies.
