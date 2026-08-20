# 0041. Retrieval and degradation honesty

- **Status**: accepted
- **Date**: 2026-08-20
- **Depends on**: ADR
  [0004](0004-reader-fulltext-with-abstract-fallback.md) (abstract
  fallback), [0020](0020-prompt-injection-isolation-reader.md)
  (prompt isolation), [0023](0023-semantic-scholar-citation-graph.md)
  (S2 enrichment), [0028](0028-postgres-paper-cache-and-embedding-cache.md)
  (pluggable caches), [0033](0033-safety-hardening-bundle.md)
  (safety hardening)

## Context

An audit of the retrieval path found a cluster of failures that share
one root: the pipeline preferred *finishing* over *being right about
what happened*.

- **Fabricated sources (P1).** `search_agent` substituted the five
  hardcoded `MOCK_PAPERS` whenever live arXiv returned zero results —
  outage, rate limit, or a genuine zero-hit query — announced only by
  a `print()` to stdout. The full pipeline then ran on five
  hallucination/RAG papers regardless of what the user asked, and the
  job was recorded `succeeded`. At rate-limit scale this is a
  systematic, not exceptional, condition.
- **Silent enrichment no-op (P2).** arXiv Atom ids carry a `vN`
  version suffix that Semantic Scholar's external-ID lookup 404s on,
  so with `enable_semantic_scholar=true` every `get_references` call
  failed quietly and retrieval was byte-identical to flag-off. The
  same version/scheme mismatch also broke the cross-source dedup that
  ADR 0023 promised.
- **Cache reads as job-killers (P1).** The Postgres-backed
  paper/embedding caches guarded only their WRITE paths. A read-side
  `PoolTimeout` or `OperationalError` propagated up through the
  reader fan-out and failed the whole job — contradicting ADR 0028's
  stated "degrades to recompute, only shows up in the logs".
- **One malformed LLM response kills the run (P2).** The reader,
  planner, synthesizer, and critic all indexed required keys on
  `call_llm_json` output bare. A single `max_tokens` truncation
  mid-JSON — an HTTP 200 the SDK never retries — discarded a fully
  billed run, worst in the reader where `executor.map` re-raises the
  first exception and throws away every other paper's completed
  analysis.

## Decision

One policy, applied per component according to what an honest answer
costs at that point in the pipeline:

**Fabricating sources is never acceptable.** `MOCK_PAPERS` is
reachable only under `settings.use_mock_data` (a fully offline mode).
A live search that yields nothing raises a typed, well-named error —
`ArxivUnavailableError` when every query failed at the transport level
(the tool layer distinguishes this via
`search_arxiv(..., raise_on_unavailable=True)`), `NoPapersFoundError`
when arXiv answered with zero hits. The API runner maps the exception
class name to the job's `error_type`, so the failure is honest and
alertable. Two carve-outs keep partial progress: a partially failed
query batch proceeds with what it found (WARNING), and a
supervisor-loop re-search that finds nothing keeps the prior round's
papers instead of raising.

**Degrade with logs when a component is an optimization; fail the job
when the product itself is unproducible.** Concretely:

| Component | On failure | Why |
|---|---|---|
| Cache reads (`get_many`, `get_text`) | Treat as miss, WARNING, recompute | Caches are optimizations; ADR 0028 already promised this and the write side already did it. |
| Reader, one paper's LLM response | Degrade that paper to a placeholder analysis (`relevance=0.0`, explicit limitations note), WARNING | The fan-out already billed every other paper; one paper's formatting failure must not discard nine good analyses. |
| Reader, every paper failed | Raise `AllPaperAnalysesFailedError` | The LLM is effectively down; synthesizing from nothing would be a hollow report. |
| Planner response malformed | Fall back to the raw query as the single sub-question / search query, WARNING | Cheapest stage; an honest shallow search beats a dead job. |
| Synthesizer response malformed / truncated | Retry once with a corrective nudge, then raise typed `SynthesizerOutputError`; output cap raised 4096 → 8192 | The report IS the product — there is no honest fallback for it, but one cheap retry can rescue the whole billed run. Format-failure retry only; transport retries stay SDK-native (ADR 0009). The old 4096 cap left no margin over the ~3000-3300 tokens a full report costs, so truncation was deterministic and a same-cap retry could never rescue it. |
| Synthesizer citations entries malformed | Drop individually, WARNING | A thinner citation list is still a real report; the verifier/critic flag gaps. |
| Critic response malformed | Approve with score 0.0, WARNING; scores coerce via `_safe_float`; `revision_needed` requires literal `true` (verifier's idiom) | Terminal node — the report is already written; a judge formatting bug must not discard it. |
| Verifier / query refiner | Unchanged | Both already fail closed with logged fallbacks (ADRs 0015, 0018); they set the idiom the critic now follows. |

"Malformed" includes valid JSON that is not an object (a bare list or
string): `call_llm_json`'s dict return type is a cast, not a runtime
guarantee, so the planner, synthesizer, and critic all check the shape
before indexing and degrade exactly as they do for unparseable JSON.
The reader is covered by its per-paper catch-all.

**Everything visible through the structured logger.** The lone
`print()` in the agent layer is gone; every degradation logs at
WARNING with enough context (`paper_id`, counts, error types) to
alert on.

Shipped in the same change because they share the honesty root:

- **S2 version strip + canonical dedup.** `_arxiv_url_to_s2_id`
  strips `vN`; `deduplicate_papers` keys on `canonical_paper_key`
  (scheme- and version-insensitive for arXiv URLs) so seeds and S2
  references actually collide. `_map_s2_paper` now emits https URLs.
- **Search query cap.** `MAX_SEARCH_QUERIES_PER_RUN = 12` in the
  search agent — defense in depth against an oversized HITL-edited
  plan driving unbounded arXiv traffic (the schema bound lives at the
  API layer).
- **SSRF guard on PDF fetches.** `_is_fetchable` in `pdf_parser`
  requires https and rejects destinations resolving to non-public
  addresses; redirects are walked manually with each hop re-validated
  (`allow_redirects=False`), closing the 302-to-metadata-endpoint
  path through S2's attacker-influenceable `openAccessPdf.url`. arXiv
  hosts are trusted (their URLs come from arXiv's own TLS feed) and
  get http→https upgraded.
- **Title normalization + isolation.** Both source adapters normalize
  titles to one ≤300-char line; the reader wraps the title in the
  untrusted-content tags when isolation is on (the old "titles are
  short and controlled" premise died with S2 enrichment).
- **Model-load lock.** `_get_model()` uses the same double-checked
  lock as `postgres_pool.get_pool` so concurrent cold-start callers
  load MiniLM once.

## Alternatives considered

- **Provenance field instead of failing (`paper_source` on state/Job,
  mock papers as a labeled fallback)** — keeps jobs "succeeding"
  during outages, but a fluent briefing citing off-topic papers is
  worse than an honest failure no matter how it's labeled; clients
  ignore metadata. Dealbreaker: it still fabricates sources.
- **Retry-with-nudge everywhere (planner/reader/critic too)** — costs
  an extra call at every node for failures whose fallbacks are
  already honest and free. Only the synthesizer, where failure means
  losing the entire billed run, justifies the spend.
- **Sentinel return (`None` / result object) instead of exceptions
  from `search_arxiv`** — would force every caller to change
  signature-side; the keyword opt-in keeps the historical `[]`
  contract for existing callers and tests.
- **Version-preserving dedup keys** — treats `v1`/`v2` of a preprint
  as different papers and double-bills the reader for near-identical
  text; rejected.
- **Blanket redirect ban on PDF fetches** — simpler than manual
  walking, but open-access hosts redirect routinely (DOI resolvers,
  CDNs); we'd trade a real capability for implementation ease when
  per-hop validation costs little.

## Consequences

- **Positive**: an arXiv outage now reads as `ArxivUnavailableError`
  on the job record instead of a confident off-topic briefing marked
  `succeeded`. Postgres restarts cost latency, not jobs. One
  truncated response costs one paper (reader) or one retry
  (synthesizer), not the run. S2 enrichment does what its flag says.
  Every degradation is one log query away.
- **Negative**: jobs that used to "succeed" during outages now fail —
  dashboards will show more failures; that is the point, but it may
  surprise. The synthesizer retry adds up to one extra full-size call
  in the malformed case. The SSRF pre-flight adds a DNS resolve per
  non-arXiv PDF host.
- **Follow-ups**: pre-flight resolve does not pin the connection IP,
  so DNS rebinding remains theoretically possible (record accepted;
  full fix needs an IP-pinning adapter). Readiness probe that
  exercises `_get_model()` plus baked-in model weights (audit
  finding, deployment-layer work). Surface per-node degradation
  counts (papers degraded, PDFs fallen back) as SSE/job fields.
