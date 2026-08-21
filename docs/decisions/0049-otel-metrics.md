# 0049. Emit OpenTelemetry metrics for jobs, spend, concurrency and rate limiting

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: maintainer

## Context

The audit's remaining P2 under observability was blunt: *no metrics of
any kind*. The service has three telemetry signals and none of them is
one:

- **Structured JSON logs** (ADR 0012) — every job outcome, every LLM
  call, every rate-limit decision is a line. Excellent for *why one
  request did that*, useless for *what is the fleet doing right now*.
- **OTel tracing** (ADR 0013) — spans per agent node, opt-in behind
  `enable_tracing`. Answers *where did this one run spend its time*.
- **Per-run cost accounting** (ADR 0012) — a `ContextVar`-scoped
  accumulator that dies with the run.

None of those answers the three questions an on-call engineer asks
first:

1. How many jobs are failing right now, and with what error?
2. What is the p95 job duration?
3. Are we near the concurrency ceiling?

Today all three are grep-and-count exercises over logs. Question 3 is
worse than that: `active_jobs` is only visible by polling every
worker's `/healthz` individually, and ADR 0047's abandoned node
threads — the ones that hold real capacity the semaphore no longer
covers — are visible nowhere else at all. ADR 0047 recorded
"`abandoned_node_threads` as a metric rather than a health field" as an
explicit follow-up; this is that.

The forcing constraint on *how*: the repo already standardized on
OpenTelemetry for tracing, and `opentelemetry-sdk` ships a metrics API
in the same distribution we already install and pin. Adding
`prometheus_client` would mean two telemetry stacks, two exporters and
two things to configure in a deployment that already runs an OTLP
collector for spans.

## Decision

Add an opt-in OTel metrics layer in `src/observability/metrics.py`,
gated and wired exactly like tracing.

### The gate

`settings.enable_metrics: bool = False`, mirroring `enable_tracing`,
and reusing the *same* `otel_exporter_endpoint` — one collector
receives both signals, and an operator who has already pointed the
service at a collector for spans turns metrics on with one boolean.
Empty endpoint means the console exporter, same local-dev affordance
tracing offers. `otel_metric_export_interval_sec` (default 60, bounded
1..3600 per ADR 0046) tunes the periodic reader.

With the flag off, `configure_metrics()` installs nothing and
`_instruments` stays `None`, so every record helper returns on its
first line — one module-global load and one `None` check. That is the
same "no wrapper when disabled" discipline `traced_node` follows: a
disabled deployment must not pay for a feature it turned off.

### The five instruments

| Instrument                        | Kind             | Attributes           | Recorded at |
|-----------------------------------|------------------|----------------------|-------------|
| `research_jobs_total`             | counter          | `status`, `error_type` | `runner._persist_terminal` |
| `research_job_duration_seconds`   | histogram        | `status`             | `runner._persist_terminal` |
| `research_active_jobs`            | observable gauge | —                    | lifespan callback |
| `research_abandoned_node_threads` | observable gauge | —                    | lifespan callback |
| `llm_cost_usd_total`              | counter (float)  | `model`              | `costs.record_llm_call` |
| `llm_calls_total`                 | counter          | `model`              | `costs.record_llm_call` |
| `rate_limit_rejections_total`     | counter          | `backend`            | `auth._raise_429` |

Every recording site is an existing choke point, chosen so that no
future call site can bypass the metric:

- **`_persist_terminal`** is the one function all seven of `run_job`'s
  terminal branches call — success, generic failure, timeout, cost cap,
  HITL timeout, HITL cancel, shutdown cancel. Duplicating two lines
  across seven branches would mean the eighth branch someone adds is
  silently uncounted. The record happens *before* the write and outside
  the retry loop: the job reached its terminal state whether or not the
  store accepted the row, and a Redis outage must not also make the
  fleet look idle.
- **`record_llm_call`** already funnels every LLM call in the repo —
  agent nodes included — through one function that computes the cost.
  The counters are bumped unconditionally there, unlike the per-run
  accumulator, which needs a run bound to the context: a call made
  outside a run still spent money.
- **`_raise_429`** is the shared response-shape helper both limiter
  backends already call. It grows one keyword-only `backend` argument
  that the counter needs and the HTTP response does not.
- **`JobRedriver._fail_orphan`** is the one terminal transition that
  never reaches `_persist_terminal`: the worker that owned the job died
  before any of `run_job`'s branches ran, and another worker's startup
  sweep reconciles the row (ADR 0038/0048). Leaving it uncounted would
  blind `research_jobs_total` to the failure mode the counter most
  exists for — a crash-looping worker would read as falling throughput
  and nothing else. Recorded *after* the compare-and-set lands, the
  mirror image of `_persist_terminal`'s rule: there the job is terminal
  whether or not the store agrees; here a lost CAS means the real owner
  finished it and will count it itself. No duration is observed — a
  reclaim's wall clock is mostly the time the row sat orphaned before a
  sweep noticed, which would report the scan interval as job latency.

### Which processes emit

`configure_metrics()` has one caller, the API lifespan, so the
instruments are live in an API worker and nowhere else: `make run` and
`make eval` set `ENABLE_METRICS` in vain. That is a decision, not an
omission. Four of the seven instruments describe a *server* (job
outcomes, concurrency, 429s), and a one-shot CLI run has no steady
state for the other three to sample — it would spin an export thread up
and tear it down inside a single export interval. Tracing differs
because `get_tracer()` configures lazily on first span, which is what
makes `traced_node` work under `make eval`; the metrics equivalent
would put an `enable_metrics` read and a possible provider build on
every LLM call, which is exactly the flag-off cost this design avoids.
If the eval runner ever wants the spend counters, the fix is one
`configure_metrics()` call at its entry point.

### Attribute-cardinality rules

`error_type` is normalised to the literal `"none"` on non-failure
paths rather than omitted, so `succeeded` and `failed` series have the
same attribute shape and `sum by (status)` needs one query, not two.
Rate-limit rejections are attributed by *backend* (`memory` / `redis`),
never by `key_id`: principal names are unbounded operator-supplied
strings, and the rejected principal is already named in the 429 body
and the request log. Job duration is attributed by `status` only —
"how long do failures take" is a question, "how long does each error
type take" is a cardinality bill.

### The gauges read the existing accounting

`research_active_jobs` and `research_abandoned_node_threads` are
*observable* gauges whose callbacks the API lifespan supplies:

```python
register_runtime_gauges(
    active_jobs=lambda: len(app.state.tasks) + abandoned_node_count(),
    abandoned_node_threads=abandoned_node_count,
)
```

That is the same expression `/healthz` reports, closing over the same
sources — this worker's in-flight task set and `src.cancellation`'s
process-wide abandoned count. Nothing is duplicated, so the gauge and
the health endpoint cannot drift into two disagreeing numbers. Passing
callables rather than importing app state also keeps
`src/observability/` free of any knowledge of the API layer.

### Lifespan wiring

`configure_metrics()` + `register_runtime_gauges(...)` run in the
lifespan next to the other startup wiring (ADR 0040/0047), before any
job can record. `shutdown_metrics()` runs *last* in the teardown —
after the in-flight jobs are cancelled — so the terminal counters
those cancellations just recorded make it into the final export. It
runs in a thread (`asyncio.to_thread`) because the SDK's shutdown
blocks on its export thread, and blocking the loop would stall
uvicorn's own shutdown.

Being last also means it is first in line for the orchestrator's
SIGKILL, and the chain ADR 0042 sizes has no room to spare: compose
grants `stop_grace_period: 15s`, uvicorn spends up to
`timeout_graceful_shutdown=10` draining connections *before* the
lifespan teardown starts, and it puts no timeout on the teardown
itself — so the container's remaining ~5s is the only bound, and ADR
0047's node-executor join can already claim all of it. The flush is
therefore best-effort by construction, and its budget is deliberately
the smallest in the chain (2s, `metrics._SHUTDOWN_BUDGET_MS`): a
collector that cannot accept an export in two seconds will not accept
it in five, and the SDK's export thread is a daemon, so overrunning
costs the last export window rather than hanging the process.

### The provider is module-local

Unlike `trace.set_tracer_provider`, we do not *depend* on OTel's
global meter provider: every measurement goes through this module's
helpers, which read this module's own provider reference. The global
is still set once, best-effort, so third-party instrumentation added
later lands in the same pipeline — but OTel guards that setter behind
a set-once-per-process flag, and treating it as the source of truth
would make the provider un-swappable within a process. Both the tests
and a lifespan that may configure and tear down more than once need it
to be swappable.

## Alternatives considered

- **`prometheus_client` with a `/metrics` scrape endpoint** — the
  obvious industry default, and the audit's own phrasing hints at it.
  Rejected on two counts. Architecturally it means a second telemetry
  stack alongside the OTel tracing this repo already standardized on,
  with its own exporter, its own configuration surface and its own
  registry lifecycle to reconcile with the lifespan. Practically it is
  not installed, and the constraint here is to redesign around what is
  — `opentelemetry-sdk` ships metrics in the same pinned distribution
  as the tracing SDK. An OTLP collector can export to Prometheus
  anyway, so nothing is lost on the scrape side.
- **Deriving metrics from the structured logs** (log-based metrics in
  the aggregator) — zero code, and the fields are already there. But
  it makes the alerting story depend on a log pipeline that does not
  exist yet, gives no p95 without server-side aggregation of every job
  line, and cannot express the two gauges at all: nothing is logged
  when a worker is *sitting* at its concurrency ceiling, only when
  jobs cross it.
- **Recording the terminal metric in each of `run_job`'s seven
  branches** — more explicit at each site, and arguably easier to read
  in isolation. Rejected: seven copies of the same two lines is seven
  places to forget, and the eighth branch added later would be
  uncounted with nothing failing. The mutation check below covers
  exactly this.
- **A `/metrics` route on the FastAPI app** — would require the
  Prometheus exporter, and would put a scrape surface on the same
  authenticated app whose auth `/healthz` already has to be exempted
  from. Push-to-collector keeps the API surface unchanged.
- **Attributing spend and rejections by principal (`key_id`)** —
  genuinely useful for per-tenant billing dashboards, and tempting
  since the value is right there. Rejected as unbounded cardinality in
  a metric label; per-tenant attribution belongs in the log pipeline
  or a billing table, not in a time series.
- **Making metrics on by default** — they are cheap and the flag is a
  step operators must remember. Rejected for symmetry with
  `enable_tracing`: telemetry that ships data off-process is opt-in in
  this repo, and the console exporter's periodic dump to stderr would
  otherwise become the default local-dev experience.

## Consequences

- **Positive**: the three on-call questions are answerable from a
  dashboard. `sum by (status, error_type) (rate(research_jobs_total))`
  is the failure rate and its causes;
  `histogram_quantile(0.95, research_job_duration_seconds)` is the p95;
  `research_active_jobs` against `api_max_concurrent_jobs` is the
  headroom. `llm_cost_usd_total by model` turns per-run cost
  accounting into a fleet spend rate, which no `ContextVar` could.
  `research_abandoned_node_threads` closes ADR 0047's follow-up: the
  zombie count is now a series you can alert on rather than a field on
  a health probe nobody scrapes into a time series.
- **Positive**: one telemetry stack, one endpoint setting, one
  collector. Turning on tracing and metrics together is two booleans
  and one URL.
- **Negative**: `_persist_terminal` now does something its name does
  not say. Mitigated by a why-comment and by the mutation check, but a
  future refactor that splits terminal persistence must carry the
  record with it.
- **Negative**: `_raise_429` grew a parameter that exists purely for
  telemetry. The alternative — recording separately in each backend —
  duplicates the choke point the helper exists to be.
- **Negative**: the histogram's bucket boundaries are hand-picked
  (5s..3600s) because the SDK's sub-second defaults would put every
  real research job in the overflow bucket. They are an advisory hint;
  a collector configured with a View overrides them, and they will
  need revisiting if typical job duration moves by an order of
  magnitude.
- **Negative**: with the console exporter (empty endpoint) the
  periodic reader dumps the whole metric stream to stderr every
  `otel_metric_export_interval_sec`. Fine for a local collector-less
  poke, noisy if left on.
- **Follow-ups**: no instrument yet for queue *wait* time (time spent
  behind the semaphore before `running`), which is the leading
  indicator of the ceiling that `research_active_jobs` only shows once
  saturated. Cache hit ratios (paper cache, embedding cache) and
  arXiv/Semantic-Scholar outbound latency are the obvious next
  instruments. Exemplars linking a slow duration observation to its
  trace are supported by the SDK and unused here. Neither the compose
  stack nor the deploy docs ship a collector service yet — the
  operator wires their own.

## Verification

`tests/test_otel_metrics.py` asserts against real aggregated metric
data through the SDK's `InMemoryMetricReader` — the same objects the
OTLP exporter serializes — covering each instrument family, the
gauges' liveness, the provider lifecycle, and the flag-off path (no
provider, no instruments, inert helpers). The two end-to-end classes
drive `run_job` and the real `create_app` lifespan, so the wiring is
covered rather than just the helpers.

Eighteen mutants were planted against the load-bearing points and all
eighteen are caught: dropping the terminal record; moving it inside the
persist retry loop so a store failure suppresses it; dropping the LLM
usage record; feeding the cost counter a constant; dropping the 429
record; hard-coding its `backend` attribute; dropping the `"none"`
error-type normalisation; attributing the duration histogram by
`error_type` too; timing a never-started job as zero; snapshotting the
gauge instead of observing it; ignoring `enable_metrics`; making
`configure_metrics` non-idempotent; re-registering the gauges instead
of rebinding their sources; never registering the gauges in the
lifespan; dropping `+ abandoned_node_count()` from the lifespan's
`active_jobs` callback so the gauge drifts from `/healthz`; exporting
metrics to the `/v1/traces` path; leaving the instruments armed after
shutdown; and never shutting the provider down.

The `abandoned_node_count()` mutant is why
`test_gauges_agree_with_healthz_on_abandoned_threads` asserts the gauge
against a live `GET /healthz` response rather than against a literal:
a hand-written expectation passes just as happily when the two numbers
have quietly become two different numbers.
