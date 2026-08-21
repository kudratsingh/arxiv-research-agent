# Search agent

Queries arXiv with the planner's search queries, deduplicates,
optionally enriches through Semantic Scholar's citation graph, and
ranks the pool by embedding similarity to the user's question. One of
the five agents wired through the LangGraph workflow.

Source: `src/agents/search.py`. Design rationale: ADRs
[0023](../decisions/0023-semantic-scholar-citation-graph.md) and
[0041](../decisions/0041-retrieval-and-degradation-honesty.md).

## Inputs

Reads from `ResearchState`:

- `search_queries: list[str]` — the planner's (possibly HITL-edited)
  keyword queries.
- `query: str` — the original research question, used as the ranking
  target.
- `papers` — read only to preserve a prior round's results when a
  supervisor-loop re-search comes up empty (see below).

## Outputs

- `papers: list[PaperMetadata]` — ranked, deduped, capped at
  `settings.max_papers`.
- A `messages` entry (`AIMessage` named `"search"`) reporting the
  count and source (`arXiv`, `arXiv + N S2 references`, or
  `mock data`).

## Retrieval honesty (ADR 0041)

The built-in `MOCK_PAPERS` demo fixture is served **only** under
`settings.use_mock_data`, in which case the agent is fully offline
(no arXiv, no S2). A live search never silently substitutes fabricated
sources. When live retrieval yields nothing:

| Situation | Behavior |
|---|---|
| Every query failed at the transport level (outage, rate limit, non-200) | Raises `ArxivUnavailableError` — the job fails with that `error_type`. |
| arXiv answered, but zero papers matched | Raises `NoPapersFoundError`. |
| Some queries failed, others found papers | Proceeds with what was found; logs `search_partial_arxiv_failure` at WARNING. |
| Re-search (supervisor loop) found nothing but state already has papers | Keeps the prior papers, logs `search_empty_keeping_prior_papers` — an empty round must not destroy results an earlier round paid for. |

The tool layer supports the distinction via
`search_arxiv(..., raise_on_unavailable=True)`; the default `False`
preserves the historical return-`[]` contract for other callers.

## Query cap

`MAX_SEARCH_QUERIES_PER_RUN = 12` bounds the per-run arXiv traffic.
The planner's schema already bounds plan size, but a HITL-edited plan
arrives from outside that schema — this cap is defense in depth. Trims
are logged (`search_query_cap_applied`).

## Deduplication

`deduplicate_papers` keys on `canonical_paper_key`, which collapses
arXiv URL ids scheme- and version-insensitively
(`http://arxiv.org/abs/2311.09000v1` ≡
`https://arxiv.org/abs/2311.09000`). This is what makes the ADR 0023
promise real: arXiv Atom seeds carry a `vN` suffix while Semantic
Scholar's external-ID mapping emits the unversioned form, and the two
must collide to one entry. First occurrence wins, so the arXiv seed
beats an S2 duplicate.

## Ranking

The deduped pool is ranked against the original question by cosine
similarity over MiniLM embeddings — `rank_papers_by_relevance` in
`src/tools/embeddings.py`, a FAISS inner-product index — capped at
`settings.max_papers`. The encoder is the process-wide shared model:
torch's OpenMP pool is pinned to one thread and the device is
explicit (`embedding_device`, default `cpu`) — the native-crash
containments of ADR 0052 — and `embedding_cache=postgres` skips
re-encoding texts seen before (ADR 0028).

## Semantic Scholar enrichment (ADR 0023)

Gated by `settings.enable_semantic_scholar`. The top
`semantic_scholar_seed_count` seeds (pre-ranked against the query) are
expanded with up to `semantic_scholar_refs_per_seed` one-hop
references each. Lookups strip the arXiv version suffix
(`ARXIV:2405.12345`, not `...v2`) — S2 404s on versioned external ids,
which previously made enrichment a 100% silent no-op.

## Testing

- `tests/test_search_honesty.py` — mock gating, typed failures,
  partial-failure behavior, prior-papers preservation, the query cap,
  the tool-layer `raise_on_unavailable` contract, and canonical dedup.
- `tests/test_search_enrichment.py` — S2 enrichment flag behavior,
  version-stripped lookups, cross-source dedup.
