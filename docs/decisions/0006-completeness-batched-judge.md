# 0006. Score completeness with a single batched LLM-as-judge call

- **Status**: accepted
- **Date**: 2026-07-05

## Context

The completeness metric asks: does the report meaningfully address the
research query's `expected_topics`? Under ADR
[0005](0005-custom-eval-over-ragas.md) we own the judge prompts. We
need to choose how to invoke the judge — one call for all topics or
one call per topic — and how to structure the response.

Constraints:

- Benchmark queries have 3-6 expected topics each; 10 queries in the
  set (`benchmark_queries.py`).
- Full eval run per PR would cost roughly `queries × topics` judge
  calls if per-topic, or `queries` calls if batched.
- Production-scale mandate: cost-aware LLM usage, especially in
  paths that run repeatedly (which eval is).

## Decision

**One LLM call per report**, evaluating all `expected_topics` for that
report in a single batched prompt. The judge returns JSON with a
`coverage` list — one entry per topic, each with `covered: bool` and a
`reason` string.

- Judge prompt is strict: "meaningfully addresses" must involve
  specific content, not name-dropping; single-sentence mentions do not
  count.
- Response is defensively aggregated: missing topics from the judge
  are marked uncovered with an explanatory note; extras / duplicates
  in the response are ignored. Output always has exactly
  `len(expected_topics)` entries in the requested order.

## Alternatives considered

- **One call per topic.** Rejected. 3-6× cost multiplier per report
  for uncertain quality gain. Batched judging is standard in
  Ragas / DeepEval / recent LLM-as-judge papers. Also, per-call
  isolation could inflate false positives — a topic that's clearly
  not covered stands out more when the model sees it alongside topics
  that are covered.
- **Give the judge a scale (0-2 or 0-5).** Rejected for now. Binary
  is easier to calibrate and audit; noisy graded responses would
  dominate score movement between runs. Revisit if we find binary is
  too coarse in practice.
- **Ask the judge to quote supporting passages.** Attractive for
  interpretability but roughly doubles output tokens. Deferred — the
  `reason` field already provides some interpretability; add
  citations later if debugging demands it.
- **Use retrieval (embed report + topic, threshold cosine sim).**
  Rejected. Retrieval can't tell "mentioned once" from "meaningfully
  addressed" — the whole point of using a judge.

## Consequences

- **Positive**:
  - Cost stays `O(queries)`, not `O(queries × topics)`.
  - Judge sees relative coverage across topics — helps calibrate
    "meaningfully addresses" against the specific report.
  - Response schema is stable and testable independent of the LLM
    (via `_aggregate_coverage`).
- **Negative**:
  - Batching means one bad completion invalidates all topic decisions
    for that report. Mitigation: defensive aggregator degrades
    gracefully; a follow-up could add a retry with a tighter prompt.
  - No graded coverage. A report that covers a topic thoroughly and
    one that mentions it in a paragraph score identically.
- **Follow-ups**:
  - Add optional retry-on-bad-schema in `call_llm_json`
    (tracked with `feat/anthropic-retry`).
  - Small hand-labeled calibration set once metrics are exercised in
    real eval runs — check the judge's decisions against a human on
    ~20 (report, topic) pairs and tune the strictness knob if needed.
