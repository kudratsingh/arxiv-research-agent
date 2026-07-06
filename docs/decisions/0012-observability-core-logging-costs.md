# 0012. Observability core — stdlib JSON logging, ContextVar run scope, per-run cost tracking

- **Status**: accepted
- **Date**: 2026-07-06

## Context

Sprint 1's observability track needs three primitives that everything
else (tracing, cost dashboards, regression triage) builds on:

1. **Structured logs** so downstream tools can `jq` / grep / index.
2. **A run identifier** propagated through every log line and metric
   so events from one workflow invocation can be grouped.
3. **Cost tracking** — token counts and USD estimates per LLM call,
   totalled per run and per model, so we can catch cost regressions
   in the nightly diff (`feat/eval-ci`) and answer "what did that
   run cost me?" without inference.

## Decision

### Structured logging: stdlib `logging` + JSON formatter

- `logging` module from the standard library. `logger.info("event",
  extra={"k": "v"})` — no new API to learn.
- `JsonFormatter` (`src/observability/logging.py`) emits one JSON
  object per record with `ts`, `level`, `logger`, `run_id`,
  `message`, and any `extra=` fields as top-level keys.
- Level from `settings.log_level` at configuration time. Sinks to
  stderr so eval / runner stdout stays clean for report content.
- Noisy library loggers (`httpx`, `httpcore`, `anthropic`,
  `urllib3`) capped at WARNING.

### Run scope: `contextvars.ContextVar`

- Single ContextVar (`_run_id`) holds the current run's identifier,
  default `"-"` when no run is active.
- `bind_run_id(run_id)` returns a Token; `reset_run_id(token)` at
  end. `main.run()` and `eval.runner._run_and_score` wrap the whole
  invocation in a try/finally.

### Cost tracking: ContextVar-scoped accumulator

- `RunCosts` dataclass holds cumulative totals + per-model breakdown
  behind a `threading.Lock` so reader ThreadPool workers can safely
  contribute concurrently.
- `_current_costs: ContextVar[RunCosts | None]` — per-run isolation
  without global mutable state that would break under future async
  multi-tenancy.
- `record_llm_call(model, in_tokens, out_tokens)` called inside
  `src/llm.call_llm` after every successful `messages.create`. No-op
  when no accumulator is bound (unit tests, ad-hoc scripts).
- Price table (`PRICES_USD_PER_MILLION`) hardcoded to Anthropic's
  list price at project inception. Unknown model falls back to
  Sonnet **with a warning** — silent under-reporting is exactly what
  we're guarding against.

### Cross-thread propagation: `propagate_run_context`

`ThreadPoolExecutor` doesn't inherit `ContextVar` state — the reader
would otherwise lose per-run attribution for every LLM call from a
worker thread. `Context.run(...)` from `copy_context()` can only be
entered once per Context instance, so it's unsafe for reuse across
multiple `executor.map` calls.

`propagate_run_context(fn)` snapshots the caller's `run_id` and
current cost accumulator at wrap time (once, on the parent thread),
then re-binds them in whichever worker thread runs the wrapped call.
Cleanup via try/finally guarantees no leak into the worker's next
task.

### State schema

`run_id` field added to `ResearchState`. `main.run(query)` and
`eval.runner._run_and_score` set it on the initial state (uuid4 hex,
16 chars) so downstream artifacts (per-query JSON records, workflow
messages) carry the same identifier that appears in logs.

### Eval summary integration

`summary.jsonl` and `summary.md` now include `cost_usd` and
`llm_calls` per query, plus a total-cost line in the run's markdown
summary. Cost regressions will show up in the nightly diff alongside
metric regressions once `feat/eval-ci-cost` extends the regression
diff to include cost as a first-class metric (follow-up).

## Alternatives considered

### Logging library

- **`structlog`** — cleaner API (`log.bind(...)`, deferred rendering),
  but a new dep with its own configuration surface. Rejected: we
  can express everything we need with stdlib + a formatter subclass,
  and stdlib is what every Python operator already knows.
- **`loguru`** — batteries-included, easy but idiosyncratic API
  (`from loguru import logger`; no logger hierarchy). Rejected on
  the same grounds as structlog plus its non-idiomatic pattern.
- **Rolling our own logger class.** Rejected. Reinvents stdlib
  poorly and forces call sites to import a custom API.

### Log format

- **Human-readable colored logs** for local dev. Attractive but
  splits the codebase between two formatters — one for dev, one for
  prod. Deferred: JSON is machine-readable AND legible enough for
  local use with `jq`, and dev-time filtering is easier when the
  format is the same everywhere.

### Run scope

- **Thread-local instead of ContextVar.** Rejected. Doesn't
  propagate across asyncio boundaries; would need a rewrite for
  future async runners. ContextVar is the modern replacement.
- **Pass `run_id` explicitly through every function signature.**
  Rejected as noise. `ResearchState.run_id` handles the state layer;
  ContextVar handles the log/cost layer; both derive from the same
  identifier assigned at run entry.

### Cost table location

- **Env-configurable price table.** Attractive under the config
  mandate (ADR 0011), but a nested-object env var (per-model prices)
  is awkward. Kept in code for now; migrate to `settings` when we
  need to override without a code change (e.g. discount tiers).
- **Fetch prices from Anthropic API.** No such API exists.

### Cross-thread propagation

- **`copy_context()` + `ctx.run(fn)`.** The obvious first attempt.
  Fails because Context objects can only be entered once. Would need
  a fresh copy per call, and `Context.copy()` isn't a public API.
- **`asyncio` with proper Task context propagation.** Correct
  long-term direction, but converting the reader's synchronous
  fan-out to async is out of scope for this piece. Tracked as
  `feat/reader-async`.

## Consequences

- **Positive**:
  - Every log line carries `run_id`, `level`, `logger`, and any
    structured extras — greppable, aggregatable, ready for a
    future dashboard.
  - Cost is measured, not estimated. Nightly eval diff will surface
    a Haiku-migration cost win (or a prompt-bloat cost loss)
    numerically.
  - Reader fan-out preserves per-run attribution — no more phantom
    LLM calls with `run_id="-"` in worker-thread logs.
  - `main.run()` gains a `run_id` parameter for callers who want to
    join workflow runs to their own tracing context.
- **Negative**:
  - JSON logs are less readable at the console than plain text.
    Mitigated by `jq` and `less`; a dev-mode plain formatter can be
    added later without breaking downstream consumers.
  - Cost accuracy depends on the hardcoded price table. If Anthropic
    changes prices, we get the ratio wrong until the table is
    updated. Warning-on-unknown-model + a follow-up
    (`feat/prices-in-settings`) catch the two most likely drift
    modes.
  - `record_llm_call` inside `call_llm` adds a small per-call
    overhead (dict update under a Lock). Negligible next to network
    latency.
- **Follow-ups**:
  - `feat/otel-tracing` — OpenTelemetry spans per agent node
    exporting to console + OTLP. Uses the same `run_id` for trace
    correlation.
  - `feat/prices-in-settings` — move `PRICES_USD_PER_MILLION` into
    `Settings` for override without a code change.
  - `feat/eval-ci-cost` — extend the nightly regression diff to
    surface `cost_usd` as a first-class metric.
  - `feat/reader-async` — convert the reader's per-paper fan-out
    from ThreadPool to asyncio, removing the need for manual context
    propagation.
