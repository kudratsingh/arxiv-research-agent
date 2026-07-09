# Architecture Decision Records

Every non-trivial design or technical decision in this project gets an
ADR — a short document capturing the context, the decision made, the
alternatives considered, and the consequences. ADRs are written before
or alongside the code that implements them, and are **amended (not
deleted)** when superseded.

## Format

See [`TEMPLATE.md`](TEMPLATE.md). Files are numbered `NNNN-slug.md` and
never renumbered.

## Index

- [0001](0001-use-anthropic-sdk-directly.md) — Use the Anthropic SDK
  directly, not LangChain's wrapper
- [0002](0002-section-aware-chunker.md) — Roll our own section-aware
  chunker over generic markdown splitters
- [0003](0003-chunk-ranker-max-similarity.md) — Rank paper chunks by
  max cosine similarity across sub-questions
- [0004](0004-reader-fulltext-with-abstract-fallback.md) — Reader
  consumes ranked full-text chunks with abstract fallback
- [0005](0005-custom-eval-over-ragas.md) — Roll our own eval pipeline
  instead of adopting Ragas / DeepEval / LangSmith
- [0006](0006-completeness-batched-judge.md) — Score completeness with
  a single batched LLM-as-judge call
- [0007](0007-faithfulness-single-call-abstracts.md) — Score
  faithfulness with a single-call judge over cited abstracts
- [0008](0008-eval-runner-sequential-per-query-isolation.md) — Eval
  runner: sequential runs, per-query error isolation, three-layer
  output
- [0009](0009-anthropic-sdk-native-retry.md) — Use the Anthropic SDK's
  built-in retry over a custom loop or `tenacity`
- [0010](0010-nightly-eval-ci.md) — Nightly eval CI with artifact-based
  baseline and regression diff
- [0011](0011-pydantic-settings-typed-config.md) — Typed configuration
  via `pydantic-settings`
- [0012](0012-observability-core-logging-costs.md) — Observability core:
  stdlib JSON logging, ContextVar run scope, per-run cost tracking
- [0013](0013-sprint-1-finish-retry-checkpoint-tracing-recall.md) —
  Finish Sprint 1: shared HTTP retry, SQLite checkpointing, OTel
  tracing, retrieval recall, expanded benchmark
- [0014](0014-supervisor-loop-behind-flag.md) — Supervisor loop
  behind a settings flag with strict-enum action space
- [0015](0015-verifier-agent-runtime-faithfulness.md) — Verifier
  agent: runtime faithfulness check as a supervisor action
- [0016](0016-evidence-store-source-text-verifier.md) — Evidence
  store: reader emits `EvidenceClaim`, verifier judges against
  `source_text`
- [0017](0017-synthesizer-evidence-swap.md) — Synthesizer prefers
  `EvidenceClaim`s when available
- [0018](0018-query-refiner-recovery-action.md) — Query refiner:
  new `refine_query` supervisor action, fail-closed dedup, flag-gated

## When to write an ADR

- Choosing between competing libraries or frameworks.
- Choosing between competing algorithmic or architectural approaches.
- Introducing a new external dependency of any weight.
- Establishing a new project-wide convention.
- Reversing a prior ADR (write a new one with `Status: superseded by`).

If you're not sure whether a decision warrants an ADR, err toward
writing one. They're cheap to write and priceless six months later.
