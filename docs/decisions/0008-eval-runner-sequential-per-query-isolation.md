# 0008. Eval runner: sequential runs, per-query error isolation, three-layer output

- **Status**: accepted
- **Date**: 2026-07-06

## Context

With the three metrics landed (ADRs
[0005](0005-custom-eval-over-ragas.md) →
[0007](0007-faithfulness-single-call-abstracts.md)), we need the piece
that ties them together: a CLI runner that invokes the workflow on
each benchmark query, applies the metrics, and persists results for
review, regression detection, and dashboard-style rollups.

Design decisions cluster around three axes: concurrency,
fault-tolerance, and output shape.

## Decision

### Concurrency: sequential

Queries run one at a time. No `asyncio` / `ThreadPoolExecutor` fan-out
in the runner.

### Fault tolerance: per-query error isolation

Each query invocation is wrapped in `try/except Exception`. Errors are
captured onto the record (`error`, `traceback` fields) and the loop
continues to the next query. Ctrl-C flushes partial results to disk
before exiting.

### Output shape: three layers

```
outputs/eval/<run_id>/
    queries/<query_id>.json  — full record: state + metrics + timing + err
    summary.jsonl            — one line per query (id + scores + timing)
    summary.md               — markdown table + aggregate row
```

- `queries/*.json` — indispensable for debugging a specific run
  ("why did this query fail?").
- `summary.jsonl` — machine-readable rollup for downstream dashboards /
  CI / regression comparison.
- `summary.md` — the artifact a human reads first.

Run identifier: `YYYYMMDDTHHMMSSZ` UTC timestamp, used as the
subdirectory name.

## Alternatives considered

### Concurrency

- **Parallel queries via `ThreadPoolExecutor`.** Rejected for now.
  Each query fires 10-50+ Claude calls plus arXiv fetches. At K
  concurrent queries the load multiplies; arXiv rate-limits are easy
  to trip, and Anthropic 429s add non-deterministic noise. Sequential
  keeps the run predictable and lets us reason about total cost. When
  we add proper retry/backoff (`feat/anthropic-retry`,
  `feat/arxiv-download-retry`) we can revisit — likely with a small
  fixed concurrency (~2-3).
- **Parallel metrics within a query.** All three metrics are pure
  once the state exists, and the LLM-as-judge metrics (completeness,
  faithfulness) could run in parallel. Rejected: only saves seconds
  per query and complicates the code path. Not worth it until we're
  actively tuning eval throughput.

### Fault tolerance

- **Fail-fast on first error.** Rejected. A single bad query would
  waste every successful run's cost. Regression detection wants the
  successful runs' scores even when siblings fail.
- **Retry failed queries within the runner.** Rejected. Retries
  belong at the transport layer (Anthropic 429s, arXiv HTTP failures)
  where they can be exponential-backed-off and observed. Retrying at
  the query level would compound cost silently. The `traceback` field
  on error records is enough to diagnose whether a retry would help.

### Output shape

- **Single monolithic JSON file.** Rejected. Grows unwieldy quickly;
  no clean way to grep for a specific query's record. Individual
  files are trivial to inspect (`cat queries/hallucination-mitigation.json`).
- **Database (SQLite / Postgres).** Rejected for MVP. JSON files
  cover the current needs (view individual runs, compare across
  runs) without an operational dependency. When we add a real
  dashboard we'll revisit — likely a `runs` table in Postgres per
  the production-scale mandate, with the JSONL as an append-only
  source of truth.
- **CSV summary instead of JSONL.** Rejected. Metric result dicts
  contain nested structures (`coverage` list for completeness,
  `claims` list for faithfulness) that flatten poorly to CSV. JSONL
  preserves structure while staying `jq`-friendly and
  streamable.

### Workflow build lifecycle

- **Build workflow once, invoke N times.** Rejected. Workflow is
  cheap to build (just wiring), invoke is where the cost is. Building
  fresh per query guarantees no cross-run state leakage — the
  `messages` reducer or any node-level cache can't accidentally
  survive.

## Consequences

- **Positive**:
  - Predictable total runtime and cost — no thundering-herd on external
    services.
  - Partial-progress preservation on interrupt. `Ctrl-C` during a
    12-query run flushes the completed ones and their scores.
  - Errors don't cascade — a failing query is diagnosable, not fatal.
  - Three output layers serve three consumers cleanly (debugger,
    dashboard, human).
- **Negative**:
  - Full eval takes `sum(query_runtime)` — likely 10-20 minutes for
    the 10-query benchmark. Not runnable in fast CI; needs a nightly
    slot. Tracked as `feat/eval-ci` follow-up.
- **Follow-ups**:
  - `feat/anthropic-retry` — makes eval robust to 429s (rate-limit
    variability was a common failure mode in early manual runs).
  - `feat/eval-ci` — nightly GitHub Actions job that runs eval,
    diffs against the last main-branch run, comments regressions on
    the PR that triggered them.
  - Metric-level parallelism once the runner is proven; only if it
    materially cuts total runtime.
