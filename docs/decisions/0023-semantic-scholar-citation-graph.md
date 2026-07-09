# 0023. Semantic Scholar adapter + one-hop citation-graph enrichment

- **Status**: accepted
- **Date**: 2026-07-09
- **Depends on**: ADR
  [0004](0004-reader-fulltext-with-abstract-fallback.md),
  [0013](0013-sprint-1-finish-retry-checkpoint-tracing-recall.md)

## Context

The search agent queries arXiv exclusively. That covers ML/AI
preprints well, but leaves three gaps:

1. **Non-arXiv venues** — top conference and journal papers that
   never posted a preprint (rare in ML but common in adjacent fields
   we may want to cover: HCI, biology, econ).
2. **Related work discovery** — when a paper's `related work` section
   or references are the exact material the workflow needs, we have
   no way to walk from a seed paper to its references without asking
   the reader to hallucinate them.
3. **Retrieval recall regressions** — the verifier's
   `missing_evidence` and the query refiner's rewrites can only chase
   what arXiv indexes.

Semantic Scholar's Graph API solves both:

- Broader index: papers from any venue with a resolvable identifier.
- One-hop citation graph: `/paper/{id}/references` and
  `/paper/{id}/citations` endpoints.
- Free tier with anonymous rate limit (~100 requests per 5 min per
  IP); optional API key raises that to 1 req/sec sustained.

Sprint 3 planning docs call for a "Semantic Scholar adapter +
citation-graph traversal" as the final Sprint 3 item. This ADR
delivers the substrate: an adapter tool + a one-hop reference-
based enrichment in the search agent. Deeper traversals (BFS to N
hops, forward citations, co-citation clustering) are follow-up work.

Constraints:

1. **Baseline preserved.** Same rule as every recent flag: default
   off, `enable_semantic_scholar=False` gives byte-identical arXiv-
   only behavior.
2. **Failure-tolerant enrichment.** S2 is a second source, not a
   dependency. Any S2 failure (network, rate limit, malformed
   response) must degrade gracefully to arXiv-only.
3. **Deduping across sources.** arXiv seeds and S2 references should
   not appear twice when S2 references have an arXiv external ID.
4. **Bounded fan-out.** S2 has rate limits; the number of outbound
   S2 requests per workflow must be capped.

## Decision

Add `src/tools/semantic_scholar.py` with two public functions and
their supporting helpers:

- `search_papers(query, limit)` — S2 keyword search. Currently
  exposed but **not** wired into the workflow; kept public for
  future "search other sources" supervisor actions.
- `get_references(paper_id, limit)` — one-hop references for a
  paper. This is what the search agent uses.

Both go through the shared retrying HTTP session (`build_retrying_session`
from ADR 0013) so 429s and 5xxs get exponential backoff for free.
Both return `list[PaperMetadata]` and swallow recoverable errors
(returning `[]`) — the search agent must never crash because of an
S2 hiccup.

### Response mapping

`_map_s2_paper(item) -> PaperMetadata | None` centralizes the
mapping and enforces two invariants:

1. **arXiv URL wins as the paper ID when available.** If the S2
   paper carries an `externalIds.ArXiv` value, the `PaperMetadata.id`
   is set to the canonical `http://arxiv.org/abs/{arxiv_id}` form
   and `pdf_url` falls back to `http://arxiv.org/pdf/{arxiv_id}` when
   no open-access PDF was provided. This means an S2-sourced
   reference that duplicates an arXiv-sourced seed dedupes naturally
   via `arxiv_search.deduplicate_papers` (which keys off `id`).
2. **Abstract is required.** No abstract → return `None` and drop
   the paper. The reader's ADR-0004 abstract-fallback path needs
   *something* to read; a paper with neither PDF nor abstract can't
   contribute regardless of source. Same argument for missing title
   or missing ID.

For S2-only papers (no arXiv external ID), the ID is prefixed
`s2:<paperId>` so it's still unique across sources and visibly
distinguishable in logs.

### Search agent integration

`search_agent` gets a new post-arXiv step, gated by
`settings.enable_semantic_scholar` AND the arXiv path not being on
the mock-data fallback:

```
arXiv search → dedupe → [S2 enrichment] → dedupe again → rank → cap
```

`_enrich_with_s2_references(query, seed_papers)`:

1. Pre-rank the seed papers by embedding similarity (reusing
   `rank_papers_by_relevance` from `src/tools/embeddings`).
2. Walk the top-`settings.semantic_scholar_seed_count` seeds.
3. For each, resolve the seed's `id` to an S2-accepted external ID
   via `_arxiv_url_to_s2_id` (arXiv URL → `ARXIV:2311.09000`, `s2:`
   prefix stripped, anything else passed through so DOI-form ids
   work).
4. Fetch `settings.semantic_scholar_refs_per_seed` references per
   seed.
5. Return the union of everything.

The search agent then unions arXiv seeds + S2 references, runs
`deduplicate_papers` (which dedupes by `id`, catching S2 refs that
were also arXiv seeds), and finally ranks + caps at
`settings.max_papers`.

### Bounded fan-out

Outbound S2 calls per workflow are capped at
`seed_count × refs_per_seed` (default 3 × 3 = 9 references
requests per workflow). Well within S2's anonymous rate limit even
without an API key. Setting `semantic_scholar_seed_count=0`
effectively disables enrichment without touching the flag, useful
for cost-sensitive deployments.

### Mock-data path stays offline

When arXiv returns nothing and we fall back to `MOCK_PAPERS`, S2
enrichment is skipped explicitly. Mock runs should be reproducible
and offline; adding a network call would break that.

## Alternatives considered

**Search S2 directly, replace arXiv.** Considered. Rejected because
arXiv provides direct PDF URLs and is what our chunker + full-text
reader is calibrated on. S2's `openAccessPdf` links vary in quality
(publisher sites, mirrors, sometimes 404). arXiv-first + S2-
augment matches how the workflow's PDF fetcher performs best.

**Search S2 as a second source alongside arXiv.** Would broaden
retrieval more than references-only enrichment. Rejected for this
PR because it also multiplies the S2 rate-limit footprint (one call
per sub-question, not per seed) and re-implements search UX we
already have. Follow-up work if we see specific queries where
arXiv-only recall is weak.

**Cache S2 responses on disk to avoid repeat requests.** Tempting
for eval runs. Rejected as premature: the fan-out is bounded (< 10
calls per workflow) and rate limits aren't the bottleneck. If we
scale to larger benchmarks we can add a `requests-cache`
integration.

**Traverse citations forward, not just references.** `paper/{id}/
citations` returns papers that cite this one — often the most-recent
follow-up work. Rejected for this PR because it can dwarf the seed
set (a widely-cited paper has hundreds of citations); needs its own
ranking and de-noising pass. Ship references-first, revisit
citations if paired-diff data motivates it.

**Two-hop references.** Would find "the papers this paper's
references cite" — deep related-work discovery. Rejected because
fan-out explodes quadratically and most two-hop matches drift far
from the query. Same "revisit if paired-diff motivates" reasoning.

**Do the enrichment inside the search tool, not the agent.**
Considered. Rejected because the agent already owns the arXiv
result dedupe and the fallback-to-mock decision; splitting
enrichment across two files would blur ownership.

## Consequences

**Wins**

- Second retrieval source flag-gated behind
  `enable_semantic_scholar`. Broader coverage possible with one
  env-var flip.
- One-hop reference traversal delivers "related work" as
  first-class retrieval material without asking the LLM to guess.
- Dedup-across-sources is invisible: an S2 reference with an arXiv
  external ID collapses with the arXiv seed automatically.
- Baseline preserved: arXiv-only runs continue producing the same
  paper set as Sprint 1.
- Failure-tolerant: any S2 error path drops the enrichment and
  hands the workflow the original arXiv set.

**Tradeoffs**

- Adds one outbound HTTP dependency (S2 Graph API). Rate-limited
  and network-fronted like arXiv; retries piggyback on the shared
  session.
- `_map_s2_paper`'s "no abstract → drop the paper" rule silently
  discards papers whose S2 record lacks an abstract, which happens
  more often than you'd think for older / non-CS papers. Acceptable
  because the reader needs abstract-or-full-text to analyze; a
  paper we can't read isn't useful even if we retrieved it.
- The reference lookup uses the arXiv external ID; papers with only
  an S2 paperId (rare among arXiv-sourced seeds) are skipped rather
  than passed through as an S2-native lookup. This is defensive —
  S2 accepts both, but silently mis-routing an unknown-form id
  would hide bugs. Documented in `_arxiv_url_to_s2_id`.

**Non-goals (deferred)**

- Direct S2 search as a workflow step (function is exported for
  future use).
- Forward-citation traversal.
- Multi-hop references or co-citation clustering.
- Persistent S2 response cache.
- New `search_semantic_scholar` supervisor action.
