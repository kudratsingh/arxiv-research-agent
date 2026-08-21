# Evaluation

Offline evaluation of the full research workflow. Distinct from the
in-loop `critic` agent (which scores a single run's draft) — this
pipeline runs the whole system on a fixed benchmark, computes
system-level metrics, and produces a report so we can measure the
effect of code changes on end-to-end quality.

Living under `src/eval/`. Design decision: [ADR
0005](decisions/0005-custom-eval-over-ragas.md) — custom in-repo eval
rather than adopting Ragas / DeepEval / LangSmith.

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

### `src/eval/benchmark_queries.py`

Twenty hand-curated ML/AI research questions with `query_id`, `query`,
`domain`, `expected_topics`, and `notes` (the original ten were
doubled by ADR
[0013](decisions/0013-sprint-1-finish-retry-checkpoint-tracing-recall.md)).
Coverage across hallucination, retrieval, alignment, reasoning,
fine-tuning, multimodal, efficiency, evaluation, architecture, and
safety.

Invariants (protected by `tests/test_benchmark_queries.py`):
- IDs are kebab-case slugs, unique
- Every query is non-empty and ends with `?`
- `expected_topics` is a non-empty list of non-empty strings
- Domain diversity: at least 5 distinct domains

### `src/eval/metrics.py`

Four metrics, each of which landed as its own PR so the design and
prompts got scrutinized independently:

- **Citation accuracy**. Pure regex + set
  membership over `(first-author-lastname, 4-digit-year)`. Handles
  `[Smith, 2023]`, `[Smith et al., 2023]`, `[Smith and Jones, 2023]`,
  year suffixes (`2023a`), and deduplicates repeated citations.
  Returns `{score, total_citations, resolved, unresolved}`.
- **Completeness**. Single batched LLM-as-judge
  call — the judge sees the whole report plus the full topic list and
  returns per-topic `covered` decisions with short reasons. Strict
  prompt: name-dropping does not count. Aggregator defensively handles
  missing / extra / malformed judge output. See ADR
  [0006](decisions/0006-completeness-batched-judge.md) for the
  batched-vs-per-topic tradeoff.
- **Faithfulness**. Single LLM-as-judge call
  extracts each factual, cited claim from the report and decides
  `supported: true|false|null` against the cited paper's abstract.
  Source of truth is `state["papers"]` abstracts joined with
  `state["citations"]` on `paper_id`. Score = supported / (supported +
  unsupported); `source_unavailable` claims are reported separately.
  Defensive override: if the judge claims support against a cite key
  we didn't provide, we force `supported=None`. See ADR
  [0007](decisions/0007-faithfulness-single-call-abstracts.md) for
  source-of-truth and denominator tradeoffs.
- **Retrieval recall**. LLM-as-judge over the retrieved paper set
  against `expected_topics` — did search actually fetch material for
  each expected topic, independent of what the report did with it
  (ADR 0013).

### `src/eval/runner.py`

**Landed.** Sequential batch runner with per-query error isolation
(see ADR [0008](decisions/0008-eval-runner-sequential-per-query-isolation.md),
hardened by ADR [0050](decisions/0050-eval-runner-hardening.md)).
Fresh workflow per query for state-leak isolation, and its checkpointer
is closed after every query. Writes three output layers:

```
outputs/eval/<run_id>/
    queries/<query_id>.json  — full record: state + metrics + timing + err
    summary.jsonl            — one line per query (for dashboards / CI)
    summary.md               — human-readable table + aggregates
```

Run identifier: `YYYYMMDDTHHMMSSZ` UTC timestamp.

`queries/*.json` is the durable layer: it is written the moment a query
finishes, and both summary files are derived from it at the end of the
run. `summary.jsonl` also gets its line appended and flushed per query,
so it stays useful mid-campaign; the end-of-run rebuild is what
collapses the duplicate lines a resumed run appends.

### Isolation, crash-safety and interrupts

- **A judge failure costs one metric, not the batch.** Each of the four
  metrics is scored inside its own guard. A judge that times out, 429s
  past its retries or truncates into invalid JSON leaves that metric as
  `null`, records the reason in `metrics_error`, and keeps the run's
  state, spend and timing — the workflow output is what cost money.
  Neither the query nor the campaign fails on it, so both consumers of
  `summary.jsonl` state the denominator they actually averaged over
  (below) and the runner's closing line counts the affected queries.
- **A kill loses at most the in-flight query.** Everything finished is
  already on disk.
- **`Ctrl-C` and SIGTERM take the same path.** `kill`, `docker stop`
  and an Actions cancellation flush partial results, the in-flight
  query's record included, before exiting `130`.
- **`--resume` re-enters a campaign** without re-paying: queries whose
  `queries/<id>.json` exists are skipped and folded into the final
  summary. That includes *errored* queries — to retry one, delete its
  record file first.
- **A populated `--output-dir` is refused** unless `--resume` is
  passed, so a repair run cannot overwrite a previous campaign's
  records.

### Cost accounting: product vs harness

Since ADR 0050 the summary separates the agent's spend from the eval
rig's:

| Field | Covers |
|---|---|
| `cost_usd`, `llm_calls`, `elapsed_sec` | the workflow run |
| `judge_cost_usd`, `judge_llm_calls`, `scoring_sec` | the scoring judges |
| `total_cost_usd` | both — what the benchmark query cost to run |

The README block and the regression gate's `cost_usd` band both read
the *workflow* figures, so neither is polluted by judge noise.
Summaries written before ADR 0050 folded judge spend into `cost_usd`
and read a few percent high; they are not comparable on cost with newer
ones.

## Running an eval

```bash
make eval                                          # full benchmark
make eval QUERIES=hallucination-mitigation,rag-multi-hop
python -m src.eval.runner --output-dir custom/dir  # bypass Makefile
python -m src.eval.runner --output-dir custom/dir --resume
python -m src.eval.runner --max-budget-usd 25      # campaign ceiling
python -m src.eval.runner --help                   # full CLI reference
```

Requires `ANTHROPIC_API_KEY` in `.env` — the runner refuses to start
without it.

`--max-budget-usd` is checked *between* queries against accumulated
workflow+judge spend (including spend reused from a resumed campaign),
so the final query can overshoot the ceiling by its own cost. It is a
campaign ceiling, and the only one the eval path owns — the per-call
dollar cap is ADR 0051's, at `call_llm`.

### Campaign run-book

For a paid multi-query campaign (as opposed to a one-query smoke):

```bash
API_JOB_TIMEOUT_SEC=3600 \
python -m src.eval.runner \
  --output-dir outputs/eval/campaign-<name> \
  --max-budget-usd 25
# interrupted or partially failed? same command + --resume
```

- **`API_JOB_TIMEOUT_SEC=3600` restores retry headroom.** The LLM
  client clamps its retry envelope so one call chain fits inside 75%
  of `api_job_timeout_sec` (`src/llm.py::_retry_envelope`, ADR 0051)
  — and the clamp applies on the eval path too, even though no API
  job exists there. At the defaults (600s timeout, 120s per attempt)
  only 3 attempts fit, so the configured `anthropic_max_retries=4`
  is cut to 2 (the client warns once:
  `llm_retry_budget_clamped`). Raising the env var to 3600 lets all
  4 retries through — worth it on a long campaign where a transient
  529 otherwise costs a whole query record.
- **Name the output dir** so `--resume` has a stable target; the
  runner refuses a populated dir without `--resume`, and `--resume`
  skips every query whose `queries/<id>.json` already exists
  (delete a record file to retry that query).
- **`--max-budget-usd`** stops the campaign between queries at the
  ceiling (exit 5) with everything already scored safely on disk.
- **Watch the exit code** (table below) — a `0` means every attempted
  query succeeded; `3` means the campaign completed but the summary
  contains errored queries.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | every attempted query succeeded |
| 1 | configuration error (no `ANTHROPIC_API_KEY`) |
| 2 | usage error (non-empty output directory without `--resume`) |
| 3 | completed, but at least one query errored |
| 4 | every attempted query errored |
| 5 | stopped early on the `--max-budget-usd` ceiling |
| 130 | interrupted (Ctrl-C / SIGTERM); partial results are on disk |

Precedence is "why is the campaign incomplete" before "how did the
queries go": an interrupted or budget-stopped run reports as such even
when the queries it did run all passed.

## Regression gate

`src/eval/regression_diff.py` diffs two `summary.jsonl` runs and exits
non-zero on regression — the nightly workflow
(`.github/workflows/eval-nightly.yml`) turns that into a red run.
Metrics are judged by class (ADR
[0044](decisions/0044-eval-cost-accuracy-and-regression-thresholds.md),
revisiting ADR [0010](decisions/0010-nightly-eval-ci.md)'s single
global threshold):

| Metric class | Metrics | Regression rule |
|---|---|---|
| Score (0-1 judge outputs) | `citation_accuracy`, `completeness`, `faithfulness`, `retrieval_recall`, `critic_score` | absolute drop > `--threshold` (default 0.10) |
| Resource (counts / dollars) | `iterations`, `llm_calls`, `cost_usd` | rise > per-metric absolute floor **and** > per-metric relative band (`RESOURCE_THRESHOLDS`) |

Both classes are direction-aware: a score rising or a cost falling
past the same bounds is an *improvement*, never a regression. The
resource bands are floor `+1` / `+50%` for `iterations`, `+4` /
`+25%` for `llm_calls`, and `+$0.10` / `+25%` for `cost_usd` — sized
so one extra critic revision, one extra rankable paper, or a $0.02
cost wiggle can never fail the nightly on its own.

A **query present in the baseline but missing from the current run** is
also a regression (ADR 0050). The usual cause is a truncated batch, and
the aggregate row re-averages over whatever survived — so "no
regressions" on a shrunken denominator is the most dangerous kind of
green. The report states the denominator it used
(`over the 15 of 20 baseline queries present in both runs`), and
`--allow-removed` opts a deliberate `--queries` subset run out of the
gate without excusing real regressions in the queries it did run.

A **metric the current run stopped scoring** is the same shrunken
denominator one level down: a failed judge leaves the metric `null`, so
its delta is `None`, so the query reads `unchanged`. The gate stays
green on purpose — a flaky judge is a harness fault, not a product
regression — but the report never hides it. Each aggregate row carries
a `Compared` column (`faithfulness … | 2 / 20`), and a metric the
baseline scored while the current run did not gets named in the header.

### The statistics, honestly

The gate compares **two single runs** of a nondeterministic system
(live arXiv results, sampling temperature, a critic that decides
whether to ask for revisions). What that means in practice:

- **Quantization dominates the score epsilon for ratio metrics.**
  `completeness` and `retrieval_recall` move in steps of
  `1/len(expected_topics)` — typically 0.20-0.25 per query. The 0.10
  epsilon therefore filters *nothing* for those two: a single
  borderline topic decision flipping registers as a full step and
  fires the per-query gate. `citation_accuracy` and `faithfulness`
  have finer denominators (citations / claims), where 0.10 is a real
  noise filter.
- **The thresholds are priors, not measured spread.** Nothing in
  `src/eval` computes run-to-run variance today (no stdev, no
  confidence intervals). The bands come from reasoning about the
  mechanics (what one critic revision costs in calls and dollars),
  not from data.
- **What we can detect:** sustained quality collapses (a metric
  dropping ≥ 2 quantization steps, or across several queries), call
  or iteration runaway (loop bugs), and cost creep above 25%.
- **What we cannot detect:** single-query, single-step ratio-metric
  drops are indistinguishable from judge noise; slow drift below the
  bands accumulates silently (ADR 0010 already documents the
  gradual-drift blind spot — each nightly rebaselines on the previous
  night).
- **The fix, when we invest in it:** run the benchmark 3+ times
  against an unchanged `main`, compute per-metric spread, and set the
  thresholds at ~3x the observed noise. Until a 3-repeat baseline
  exists, treat a red nightly on exactly one query and one metric
  with suspicion and read the per-query table before reverting
  anything.

## The published README block

`src/eval/readme_update.py` patches the
`<!-- eval-nightly:start -->` … `<!-- eval-nightly:end -->` block in
`README.md` from a `summary.jsonl`. Two honesty rules apply to what it
publishes (ADR 0050):

- **Cost and latency are the workflow's**, not the judges' — the
  README row answers "what does one research run cost", and the eval
  harness is not part of the product.
- **Runs whose report contained no citations are excluded from the
  citation-accuracy mean.** `measure_citation_accuracy` short-circuits
  a report with zero `[Author, Year]` tags to 1.0 — its own docstring
  says the metric doesn't apply — and averaging those in would inflate
  the published figure exactly when the agent cited least. The block
  states the exclusion and its denominator under the table. Other
  metrics keep the full denominator; a report with no citations still
  has real completeness and recall.
- **Every published mean states how many runs it covers.** A judge
  failure leaves its metric `null`, and the mean silently skips nulls —
  so any metric averaged over fewer runs than the `Queries` count is
  named under the table with its own denominator.

## What "tested" means for eval code itself

The eval code has its own unit tests: benchmark data invariants
(`tests/test_benchmark_queries.py`), metric-scoring pure logic
(`tests/test_metrics_*.py` — LLM-as-judge callers are unit-tested
against stubbed responses), the runner's isolation / resume / exit
codes (`tests/test_eval_runner.py`), the regression gate
(`tests/test_regression_diff.py`), and the README block
(`tests/test_readme_update.py`).

## Follow-ups

- ~~`feat/eval-metrics-citation-accuracy`~~ — landed.
- ~~`feat/eval-metrics-completeness`~~ — landed.
- ~~`feat/eval-metrics-faithfulness`~~ — landed.
- ~~`feat/eval-runner`~~ — landed.
- ~~`feat/anthropic-retry`~~ — landed. See ADR
  [0009](decisions/0009-anthropic-sdk-native-retry.md). SDK-native
  retry (4 retries, exponential backoff) + 120s timeout on every
  Claude call.
- ~~`feat/eval-ci`~~ — landed. Nightly GitHub Actions workflow at
  `.github/workflows/eval-nightly.yml` runs the benchmark, diffs
  against the previous nightly (via built-in `gh` CLI + Actions
  artifacts — no third-party actions), and fails the workflow on
  regressions >10 points. See ADR
  [0010](decisions/0010-nightly-eval-ci.md).
- `feat/faithfulness-fulltext-source` — use cached full text
  (`.cache/pdfs/<id>.txt`) as faithfulness source when available,
  falling back to abstract. Underestimation of Phase-2 faithfulness
  today is documented in ADR 0007.
- Hand-labeled calibration set (~20-30 (report, topic) pairs and
  (claim, source) pairs) once real eval runs give us data to calibrate
  against. Alignment with human judgment is currently unmeasured.
