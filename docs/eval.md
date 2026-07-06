# Evaluation

Offline evaluation of the full research workflow. Distinct from the
in-loop `critic` agent (which scores a single run's draft) — this
pipeline runs the whole system on a fixed benchmark, computes
system-level metrics, and produces a report so we can measure the
effect of code changes on end-to-end quality.

Living under `src/eval/`. Design decision: [ADR 0005](decisions/0005-eval-approach.md) —
custom in-repo eval rather than adopting Ragas / DeepEval / LangSmith.

## Goals

- Detect regressions in end-to-end report quality when we change
  agent prompts, retrieval, or the model.
- Compare the impact of specific changes — e.g. swapping the embedding
  model, tightening K in the chunk ranker, adjusting the critic
  threshold.
- Produce a durable eval report artifact that ships alongside major
  merges to `main`.

## Non-goals

- Human eval. The benchmark is automated and cheap enough to run in
  CI; human eval is a separate, later track.
- Live scoring inside a production run. That's the `critic` agent's
  job.

## Components

### `src/eval/benchmark_queries.py` (this PR)

Ten hand-curated ML/AI research questions with `query_id`, `query`,
`domain`, `expected_topics`, and `notes`. Coverage across
hallucination, retrieval, alignment, reasoning, fine-tuning,
multimodal, efficiency, evaluation, architecture, and safety.

Invariants (protected by `tests/test_benchmark_queries.py`):
- IDs are kebab-case slugs, unique
- Every query is non-empty and ends with `?`
- `expected_topics` is a non-empty list of non-empty strings
- Domain diversity: at least 5 distinct domains

### `src/eval/metrics.py`

Three metrics, each landing as its own PR so the design and prompts
get scrutinized independently:

- **Citation accuracy** — **landed** (this PR). Pure regex + set
  membership over `(first-author-lastname, 4-digit-year)`. Handles
  `[Smith, 2023]`, `[Smith et al., 2023]`, `[Smith and Jones, 2023]`,
  year suffixes (`2023a`), and deduplicates repeated citations.
  Returns `{score, total_citations, resolved, unresolved}`.
- **Completeness** — **landed** (this PR). Single batched LLM-as-judge
  call — the judge sees the whole report plus the full topic list and
  returns per-topic `covered` decisions with short reasons. Strict
  prompt: name-dropping does not count. Aggregator defensively handles
  missing / extra / malformed judge output. See ADR
  [0006](decisions/0006-completeness-batched-judge.md) for the
  batched-vs-per-topic tradeoff.
- **Faithfulness** — **landed** (this PR). Single LLM-as-judge call
  extracts each factual, cited claim from the report and decides
  `supported: true|false|null` against the cited paper's abstract.
  Source of truth is `state["papers"]` abstracts joined with
  `state["citations"]` on `paper_id`. Score = supported / (supported +
  unsupported); `source_unavailable` claims are reported separately.
  Defensive override: if the judge claims support against a cite key
  we didn't provide, we force `supported=None`. See ADR
  [0007](decisions/0007-faithfulness-single-call-abstracts.md) for
  source-of-truth and denominator tradeoffs.

### `src/eval/runner.py`

**Landed.** Sequential batch runner with per-query error isolation
(see ADR [0008](decisions/0008-eval-runner-sequential-per-query-isolation.md)).
Fresh workflow per query for state-leak isolation. `Ctrl-C` flushes
partial results before exiting. Writes three output layers:

```
outputs/eval/<run_id>/
    queries/<query_id>.json  — full record: state + metrics + timing + err
    summary.jsonl            — one line per query (for dashboards / CI)
    summary.md               — human-readable table + aggregates
```

Run identifier: `YYYYMMDDTHHMMSSZ` UTC timestamp.

## Running an eval

```bash
make eval                                          # full benchmark
make eval QUERIES=hallucination-mitigation,rag-multi-hop
python -m src.eval.runner --output-dir custom/dir  # bypass Makefile
python -m src.eval.runner --help                   # full CLI reference
```

Requires `ANTHROPIC_API_KEY` in `.env` — the runner refuses to start
without it.

## What "tested" means for eval code itself

The eval code has its own unit tests: benchmark data invariants
(this PR), metric-scoring pure logic (per-metric PR — LLM-as-judge
callers are unit-tested against stubbed responses; the full metric
path is integration).

## Follow-ups

- ~~`feat/eval-metrics-citation-accuracy`~~ — landed.
- ~~`feat/eval-metrics-completeness`~~ — landed.
- ~~`feat/eval-metrics-faithfulness`~~ — landed.
- ~~`feat/eval-runner`~~ — landed.
- ~~`feat/anthropic-retry`~~ — landed. See ADR
  [0009](decisions/0009-anthropic-sdk-native-retry.md). SDK-native
  retry (4 retries, exponential backoff) + 120s timeout on every
  Claude call.
- `feat/eval-ci` — nightly GitHub Actions job runs the benchmark,
  diffs against the last main-branch run, comments regressions on the
  triggering PR.
- `feat/faithfulness-fulltext-source` — use cached full text
  (`.cache/pdfs/<id>.txt`) as faithfulness source when available,
  falling back to abstract. Underestimation of Phase-2 faithfulness
  today is documented in ADR 0007.
- Hand-labeled calibration set (~20-30 (report, topic) pairs and
  (claim, source) pairs) once real eval runs give us data to calibrate
  against. Alignment with human judgment is currently unmeasured.
