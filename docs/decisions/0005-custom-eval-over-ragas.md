# 0005. Roll our own eval pipeline instead of adopting Ragas / DeepEval / LangSmith

- **Status**: accepted
- **Date**: 2026-07-05

## Context

Phase 3 requires an offline eval pipeline that scores end-to-end
report quality on a benchmark of research queries. The industry has
several established options — Ragas (RAG-specific), DeepEval (broad
LLM eval), LangSmith (LangChain-native), Braintrust. Each ships with
implementations of the metrics we care about (faithfulness,
completeness, citation accuracy), which is tempting because it means
we don't write LLM-as-judge prompts ourselves.

The catch is fit. This system does not produce a single QA answer
against a single retrieved context — it produces a **multi-agent
research briefing**: a markdown report grouped by theme, with
`[Author, Year]` inline citations that resolve against a citation
list carried in state. Standard RAG eval libraries assume:

- one question in, one answer out
- flat retrieved-context list, not section-tagged chunks per paper
- reference-based scoring (needs a gold answer), which we do not have
  and cannot realistically create for 10 open-ended research
  questions

## Decision

Build the eval pipeline in-repo under `src/eval/`. Own the metric
definitions, the LLM-as-judge prompts, and the report shape. Borrow
patterns (LLM-as-judge, per-claim decomposition) from the ecosystem
without importing the libraries.

Structure:

- `src/eval/benchmark_queries.py` — hand-curated ML/AI queries with
  `expected_topics` for reference-free completeness scoring.
- `src/eval/metrics.py` — three metrics: **faithfulness**,
  **completeness**, **citation accuracy**. Each lands as its own PR.
- `src/eval/runner.py` — batch runner, writes JSONL + markdown
  reports to `outputs/eval/<timestamp>/`.

All LLM-as-judge calls go through the existing `src/llm.py` helpers
so caching, backoff, and observability apply uniformly across the
codebase.

## Alternatives considered

- **Ragas.** Rejected. Its `faithfulness`, `answer_relevancy`, and
  `context_precision` metrics assume flat (question, contexts, answer)
  tuples. Our report is not an answer — it's a structured document
  with inline citations that resolve against an explicit citation
  list. Reshaping our output to fit Ragas discards the structure we
  built the whole pipeline to produce.
- **DeepEval.** Rejected. Broader scope than Ragas, but same
  QA-shaped bias. Its "hallucination" metric wants a `context` field;
  our context is per-paper and section-tagged.
- **LangSmith eval.** Rejected. Tightly coupled to LangSmith tracing
  (which we don't use — we call the Anthropic SDK directly per
  ADR [0001](0001-use-anthropic-sdk-directly.md)). Its evaluators
  work but importing them means pulling in more of LangChain than we
  currently need.
- **Braintrust.** Rejected for now on cost / lock-in grounds. May
  revisit if we grow to needing a hosted eval dashboard.
- **No eval, ship on vibes.** Rejected. The production-scale mandate
  requires reproducible quality measurement, especially as we start
  changing prompts and models.

## Consequences

- **Positive**:
  - Metrics are tuned to the exact output shape (markdown +
    `[Author, Year]` + citation list) — no lossy reshaping.
  - Prompts live in-repo, reviewable in the same PR as the code they
    score. Doc mandate compliance is automatic.
  - No new heavyweight dependencies.
  - LLM-as-judge calls flow through the same `src/llm.py` helpers,
    inheriting caching / backoff / observability improvements without
    parallel work in a second library.
- **Negative**:
  - We reimplement LLM-as-judge prompt patterns that Ragas et al.
    have iterated on. Risk of prompt-engineering mistakes. Mitigation:
    each metric ships in its own PR with prompt review.
  - No community-benchmarked scores. If someone asks "is your
    faithfulness metric well-calibrated?" the answer is "as
    well-calibrated as our judge prompt." Mitigation: unit-test the
    metric on hand-labeled small examples.
- **Follow-ups**:
  - Once metrics stabilize, add a small human-labeled calibration set
    so we can compare LLM-judge scores against human judgment.
  - Revisit Ragas / Braintrust when we have a hosted dashboard need.
