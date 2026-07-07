# 0016. Evidence store — reader emits `EvidenceClaim`, verifier judges against `source_text`

- **Status**: accepted
- **Date**: 2026-07-07
- **Depends on**: ADR
  [0004](0004-reader-fulltext-with-abstract-fallback.md),
  [0007](0007-faithfulness-single-call-abstracts.md),
  [0015](0015-verifier-agent-runtime-faithfulness.md)

## Context

ADR 0007 built the faithfulness metric against paper abstracts and
explicitly called out the known limitation: **abstracts are a lower
bound on paper content**. Any factual claim well-supported by a
result section will look "unsupported" to a judge that never sees the
result section. ADR 0015 promoted the same judge into a runtime
verifier agent, inheriting the same limitation.

Sprint 2 item 5 (see
[`planning/05-agentic-upgrade-plan.md`](../../planning/05-agentic-upgrade-plan.md))
calls this out as the concrete fix: the reader is already doing all
the work — parsing PDFs, chunking, ranking chunks by relevance to
sub-questions — and then discards everything but a summary. Threading
those ranked chunks through the pipeline as **evidence claims** turns
the abstract-only substrate into a chunk-level substrate.

Three constraints dominate the design:

1. **The fixed pipeline must stay untouched**. The Sprint 1 baseline
   is the reference every other Sprint 2 configuration is compared
   against. Changing the reader's prompt shape or emission format
   unconditionally would move the baseline and confound A/B tests.
2. **A/B'd independently of the supervisor and verifier flags**. Same
   argument as ADR 0015: we want to measure "did the substrate
   change help?" separately from "did the loop help?" and "did the
   verifier help?"
3. **Deferrable synthesizer swap**. The plan's full item 5 also
   changes synthesizer emission (report writes from claims, not
   analyses). That's a report-shape change — separate blast radius,
   separate PR. This ADR ships the substrate + verifier upgrade; the
   synthesizer swap is item 5b.

## Decision

Add a new `EvidenceClaim` TypedDict in `src/graph/state.py`, a new
`evidence: list[EvidenceClaim]` state field, and a new
`settings.enable_evidence_store: bool = False` flag independent of
`enable_supervisor` and `enable_verifier`. Reader extends its LLM
call when the flag is on; verifier chooses its dossier shape at call
time.

### `EvidenceClaim` shape

```python
class EvidenceClaim(TypedDict):
    claim: str              # factual assertion the reader extracted
    paper_id: str           # matches PaperMetadata.id
    section: str            # source section from the chunker
    source_text: str        # the ranked chunk verbatim
    relevance_score: float  # cosine similarity from the chunk ranker
    supports_question: str  # sub-question this answers, or ""
```

Key field is `source_text` — the verifier judges against this
verbatim excerpt, not an abstract summary of the whole paper.
`section` and `relevance_score` are surfaced to the judge so it can
weight structural context (results > related-work, high-relevance >
low-relevance).

### Reader path

- **Flag off (default)**: `_gather_context` + `_build_user_prompt` +
  `SYSTEM_PROMPT` are byte-identical to the Sprint 1 baseline. No
  extra tokens, no schema changes. `evidence` key is absent from the
  reader's returned state update so it can never clobber upstream
  state.
- **Flag on with ranked chunks**: `_build_evidence_user_prompt` +
  `EVIDENCE_SYSTEM_PROMPT` replace the base prompts. The response
  extends the base schema with a `claims: [...]` list where each
  claim carries a 1-based `chunk_index` into the numbered excerpts.
  The reader validates the index server-side (`_parse_claim` drops
  claims with missing / out-of-range indices) and hydrates
  `source_text`, `section`, and `relevance_score` from the ranked
  chunk itself. LLM never sees `source_text` on the return path — we
  own that field, no risk of the model paraphrasing it.
- **Flag on but no ranked chunks** (PDF unavailable / extraction
  failed / all chunks filtered out): falls back to the base prompt
  path. `evidence` is emitted as an empty list. **We do not fabricate
  `source_text` from the abstract** — an evidence claim with no
  chunk is worse than no evidence claim at all, because the verifier
  would judge against a synthesized source.

### Verifier path

`_build_user_prompt` chooses at call time:

- **Chunks dossier** (`enable_evidence_store=True` and
  `state.evidence` non-empty): dossier is grouped by cited paper,
  keyed by `[Author, Year]` (same key shape as
  `build_source_index`), with each paper's ranked chunks listed
  verbatim under their section tags. Papers cited but lacking
  evidence claims (partial coverage) fall back to their abstract in
  the same dossier block. That mixed presentation lets the judge
  distinguish "abstract-only, judge strictly" from "real text,
  judge normally" per paper.
- **Abstracts dossier** (default): unchanged from ADR 0015. Same
  substrate as the offline faithfulness metric.

The verifier's system prompt is extended to describe both source
shapes so the judge can calibrate strictness per paper.

### Cost bounds

- `settings.reader_max_claims_per_paper: int = 5` caps claim
  emission per paper. With 10 papers max (`settings.max_papers`)
  and 5 claims each, dossier size is bounded at ~50 chunks — well
  below the verifier's context budget.
- Reader max_tokens raised from 1024 → 1536 on the evidence path
  (roughly +512 for the claims list). Per-paper LLM call count is
  unchanged (still one).

## Alternatives considered

**Emit claims as a second LLM call after the base analysis.** Cleaner
separation but doubles the reader's LLM cost per paper. Since the
reader is already the most expensive agent (one call per paper × up
to 10 papers), doubling it was untenable. Single-call schema
extension keeps cost close to baseline.

**Have the reader pass ranked chunks straight through as
`RankedChunk` objects, no LLM-generated claims.** Verifier would then
match its own claims against those chunks. Rejected because
`RankedChunk` has no notion of *which* claim a chunk supports —
that's the whole point of the intermediate `EvidenceClaim` layer.
Without it, the verifier judges every claim against every chunk of
every cited paper, blowing up prompt size and giving the judge no
help with attribution.

**Ship the synthesizer swap in the same PR.** Would deliver the full
"every sentence traces to a claim ID" win. Rejected on blast-radius
grounds: the synthesizer swap changes the report shape (the artifact
end users see) and touches completeness / citation-accuracy metrics.
Ship the substrate + verifier upgrade first, measure its lift on the
verifier's decisions, then swap synthesizer knowing whether the
substrate paid off.

**Use `PaperAnalysis.key_findings` as a proxy for claims.** Would
require no new type. Rejected because `key_findings` are free-form
strings with no back-reference to source text — the whole ADR-0007
limitation persists.

**Reuse the existing offline `build_source_index` for the runtime
dossier.** Considered, and the abstract path in fact does. But
building an evidence-based dossier needs the reverse join (evidence
→ cite key), which is a different data flow than the offline metric.
Two dossier builders was cleaner than one generalized one with a
mode switch.

## Consequences

**Wins**

- Verifier judges against real text — the ADR-0007 abstract
  limitation is closed for papers whose PDFs the reader could parse.
- New surface is flag-gated; fixed pipeline stays byte-identical to
  Sprint 1 baseline.
- Independent flag lets us measure substrate lift in isolation. Four
  measurable configurations now supported:
  `fixed` / `sup-only` / `sup+ver` / `sup+ver+evidence`.
- `EvidenceClaim` type + `evidence` state field give the synthesizer
  swap (item 5b) a clean landing spot with no additional plumbing.

**Tradeoffs**

- Reader per-paper LLM cost rises ~15-25% on the evidence path
  (mostly the claims output tokens, plus modest input growth from
  sub-questions and numbered excerpts). Bounded by
  `reader_max_claims_per_paper` and `reader_max_chunks_per_paper`.
- Verifier prompt gets larger on the chunks path — up to
  `max_papers × reader_max_chunks_per_paper` chunks worth of dossier
  text. Below Anthropic's context limits but non-trivial cost per
  verify call.
- Mixed dossier (chunks + abstract fallback per paper) is a slightly
  harder judge target than a homogeneous dossier. Mitigated by
  telling the judge in the system prompt how to calibrate
  differently per source shape.

**Non-goals (deferred)**

- Synthesizer reading from `evidence` (item 5b). Report shape still
  comes from `paper_analyses`.
- `open_questions` / `evidence_gaps` state fields for the supervisor
  to consume. Those need a producer that isn't the reader — the
  planner or verifier — and can land alongside item 6 (query
  refiner).
- Evidence-aware completeness / citation-accuracy metrics. The
  offline metric surface stays abstract-based for now so eval
  comparability holds across the substrate switch.
