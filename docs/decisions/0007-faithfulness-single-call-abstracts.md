# 0007. Score faithfulness with a single-call judge over cited abstracts

- **Status**: accepted
- **Date**: 2026-07-06

## Context

The faithfulness metric asks: for each factual claim in the report, does
the cited paper actually support it? This is the hardest of the three
eval metrics. Two orthogonal design choices dominate cost, complexity,
and signal quality:

1. **What is the source of truth for "supports"?** Abstract, reader
   analysis, cached full text, or fetched-fresh full text?
2. **How many LLM calls?** One (extract + judge together), two
   (decompose, then judge), or N (decompose, then per-claim judge)?

We already own the judge under ADR
[0005](0005-custom-eval-over-ragas.md). Prior decisions on completeness
(ADR [0006](0006-completeness-batched-judge.md)) established a
preference for batched judgment when it doesn't lose signal.

## Decision

**Source**: cited paper abstracts, joined from `state["papers"]` and
`state["citations"]` on `paper_id`. Abstracts are original,
deterministic, always present, and cheap enough to inline for every
cited paper.

**Shape**: **one LLM call** — the judge extracts each factual, cited
claim from the report and decides `supported: true|false|null` in the
same response. Response schema:

```json
{
  "claims": [
    {"claim": "...", "cite": "[Author, Year]",
     "supported": true|false|null, "reason": "..."}
  ]
}
```

**Score**: `supported / (supported + unsupported)`. Claims whose cited
source we did not provide (or whose cite key doesn't resolve to a
paper in `state`) are marked `supported=None` and **excluded from the
denominator**. `total_claims` and `source_unavailable` are reported
separately so callers can distinguish "judge said no" from "we didn't
have the source."

**Defensive aggregation**: even if the judge returns `supported=true`
against a cite key we did not provide in the dossier, we override to
`None`. The judge cannot manufacture support for sources we didn't
show it.

## Alternatives considered

### Source of truth

- **Reader analysis (`paper_analyses[i]`).** Rejected: this measures
  synthesizer-vs-reader faithfulness, not synthesizer-vs-paper
  faithfulness. The reader's summary is itself generated content; if
  we treat it as ground truth we compound generation errors.
- **Cached full text (`.cache/pdfs/<id>.txt`).** Attractive — richer
  source, catches claims the abstract wouldn't. Rejected for MVP:
  cache hit is not guaranteed at eval time (eval may run against
  historical outputs where the cache has since been cleared), and
  full text can be 10-50K tokens per paper which multiplies dossier
  size across 10 cited papers. Follow-up: use full text when a
  cache hit exists, fall back to abstract otherwise.
- **Fetched-fresh full text.** Rejected on cost and reproducibility
  grounds — every eval run would re-hit arXiv.

### Number of calls

- **Two calls: decompose then judge.** Cleaner separation of
  responsibilities and matches Ragas conventions. Rejected for MVP:
  double the cost per report for uncertain quality gain at our
  report sizes (a synthesized briefing is 800-1500 words). Revisit
  if single-call decomposition proves unreliable in real eval runs.
- **N calls: one per claim.** Rejected. `queries × claims` cost
  multiplier with no clear signal advantage — inline citation batches
  give the judge cross-claim context that helps calibrate strictness.

### Score denominator

- **Include `source_unavailable` as unsupported.** Rejected. Penalizes
  the report for eval infrastructure gaps we can fix (missing paper
  in state). The `source_unavailable` count is still surfaced so
  callers can penalize if they want.
- **Exclude entirely (only report supported/unsupported).** Rejected.
  Consumers of the metric need to see how much of the report the
  judge actually evaluated.

## Consequences

- **Positive**:
  - Cost stays `O(queries)`, matching completeness. One call per
    report for both metrics.
  - Score is a fraction of claims *actually judgeable*. Not
    conflated with source-availability infrastructure gaps.
  - Judge sees the full dossier at once — can compare claims across
    papers if the report makes contrasting statements.
  - Defensive override on `supported=true` for missing sources
    protects against the judge hallucinating support.
- **Negative**:
  - Abstract is a *lower bound* on what the paper says. A report that
    accurately cites methodology or results from the paper's method
    section will be marked "unsupported" because that content isn't
    in the abstract. Real faithfulness is systematically
    underestimated for Phase-2 (full-text) reader outputs.
  - Single-call means the extraction and judging steps share a
    prompt; a bad extraction poisons the whole result. Mitigation:
    the aggregator is defensive; a follow-up can split if we see
    extraction failures dominate.
- **Follow-ups**:
  - When the pdf-parser cache hits, use full text instead of abstract
    (tracked as `feat/faithfulness-fulltext-source`).
  - Add a small hand-labeled calibration set once metrics run in
    real evals (same idea as the completeness follow-up in ADR 0006).
