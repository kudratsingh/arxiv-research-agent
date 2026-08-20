# Search agent

Runs the planner's search queries against arXiv, deduplicates by paper
ID, optionally enriches the pool via Semantic Scholar's citation graph,
and ranks the union by embedding similarity to the original research
question. Second node in the fixed pipeline; the `search` action in the
supervisor loop. The only agent with no LLM call of its own.

Source: `src/agents/search.py`. Enrichment design: ADR
[0023](../decisions/0023-semantic-scholar-citation-graph.md).

## Inputs

Reads from `ResearchState`:

- `search_queries` — the queries to run (from the planner, or from the
  query refiner on a recovery round).
- `query` — the original research question; the ranking target for
  both the final relevance ranking and the S2 seed selection.

## Outputs

Writes to `ResearchState`:

- `papers: list[PaperMetadata]` — deduped, relevance-ranked, capped at
  `settings.max_papers`.
- A `messages` entry (`AIMessage` named `"search"`) with the count and
  source label (`arXiv` / `arXiv + N S2 references` / `mock data`).

## Pipeline

```
for each search_query:                # 3s sleep between queries —
    search_arxiv(sq, max_results=      # arXiv API courtesy rate
        settings.results_per_query)
        |
        v
deduplicate_papers(all results)       # keyed by paper id
        |
        v  (empty? -> MOCK_PAPERS fallback)
        |
_enrich_with_s2_references(...)       # only when enable_semantic_scholar
        |                             # and not on the mock-data path
        v
deduplicate_papers(arxiv + s2)        # arXiv-URL ids collide with S2 refs
        |                             # carrying an arXiv external ID
        v
rank_papers_by_relevance(query, ...,  # MiniLM + FAISS cosine
    top_k=settings.max_papers)
```

## Semantic Scholar enrichment (ADR 0023)

When `settings.enable_semantic_scholar` is on, the agent pre-ranks the
arXiv results against the query, walks the top
`semantic_scholar_seed_count` seeds, and fetches
`semantic_scholar_refs_per_seed` one-hop references per seed via
`src/tools/semantic_scholar.py`. Seeds without an arXiv ID are skipped
(S2 lookup needs a reliable external-ID form). Fan-out is bounded at
`seed_count × refs_per_seed`; per-seed failures are silent —
enrichment is best-effort and must never derail the workflow. S2
references that carry an arXiv external ID map to the same paper `id`
as their arXiv twin, so the union dedupes naturally. Enrichment is
skipped entirely on the mock-data path.

## Known failure modes

| Failure | Where | Handling |
|---|---|---|
| arXiv API down / empty results | `search_arxiv` (retried via the shared `urllib3.Retry` session, ADR 0013) | Falls back to the built-in `MOCK_PAPERS` set so the workflow always has something to read. The message labels the source `mock data`. |
| S2 API error / rate limit | `get_references` | Swallowed per seed; that seed contributes no references. Worst case = arXiv-only results, i.e. flag-off behavior. |
| Duplicate papers across sub-queries | `deduplicate_papers` | Keyed by `id`, first occurrence wins. |
| Over-broad result pool | Final ranking | `rank_papers_by_relevance` caps at `settings.max_papers` against the *original* query, not the sub-queries. |

Note the mock fallback is a **dev/demo affordance**, not a production
recovery path: a report silently built from mock papers would be worse
than a failed job. The `source_label` in the agent's message exists so
that path is always visible in logs and the event stream.

## Configuration

Settings that drive search (see `src/config.py`):

- `use_mock_data: bool = False` — force the mock set (offline demo).
- `results_per_query: int = 5` — arXiv results fetched per query.
- `max_papers: int = 10` — cap on the final ranked set.
- `enable_semantic_scholar: bool = False` — master enrichment flag.
- `semantic_scholar_seed_count: int = 3` / `semantic_scholar_refs_per_seed: int = 3`
  — enrichment fan-out bounds. Zero seed count disables enrichment
  even with the flag on.
- `semantic_scholar_api_key: str = ""` — optional; raises the S2 rate
  limit.

## Testing

- Unit: `tests/test_arxiv_search.py` — the arXiv adapter (query
  building, response mapping, dedup); `tests/test_smoke.py` — dedup
  edge cases.
- Enrichment: `tests/test_search_enrichment.py` — flag off = baseline
  byte-identical, seed selection, non-arXiv seed skipping, S2 failure
  tolerance, union dedup, fan-out bounds, message labels.
- S2 adapter: `tests/test_semantic_scholar.py` — response mapping, ID
  conversion, error handling against canned responses.
