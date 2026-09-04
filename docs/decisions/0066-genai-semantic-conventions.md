# 0066. GenAI semantic conventions, one trace per job, and RED/USE for the queue

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: maintainer
- **Depends on**: ADR
  [0013](0013-sprint-1-finish-retry-checkpoint-tracing-recall.md),
  [0038](0038-job-redriver-and-sse-stream.md),
  [0047](0047-bounded-executor-and-cooperative-cancel.md),
  [0049](0049-otel-metrics.md),
  [0057](0057-job-kinds-and-awaiting-learner.md),
  [0062](0062-session-specific-cost-ceilings.md),
  [0067](0067-correlation-context-and-log-contract.md)

## Context

The measured baseline (`planning/08-assurance/01-BASELINE.md` §5) found
four separate holes in the telemetry, and one of them is much larger
than the others.

**The large one: nothing joins a job together.**
`start_as_current_span` appeared in `tracing.py` and nowhere else,
`inject` / `extract` appeared nowhere in `src/` at all, and model calls
were not spans. So an API request, its queued job, its graph nodes and
its Anthropic round trips produced *N disconnected root spans* with the
largest latency contributor missing from every one of them. "Where did
400 seconds go" was not a question this system's tracing could answer
at any sampling rate. Adding attributes to spans that do not connect
would have been rearranging furniture.

**The other three.** No name in the repository followed the
OpenTelemetry GenAI semantic conventions — the instruments were
`llm_calls_total`, `llm_cost_usd_total`, `llm.cost_usd` — so no
off-the-shelf GenAI dashboard or vendor cost view could read any of it.
Job metrics carried no `kind`, so research jobs and guided-read
sessions shared one series and no session SLO could exist. A session
closed politely at its cost ceiling recorded `status="succeeded",
error_type="none"`, making budget exhaustion indistinguishable from a
clean run. Queue saturation was invisible until the ceiling was hit,
and there was no tracer flush on shutdown, so the last
`BatchSpanProcessor` window was dropped on every SIGTERM — precisely
when failures happen.

Adopting the conventions rather than inventing names costs the same
effort and buys the interoperability, which matters specifically
because the stated next step for this system is MCP and other agent
infrastructure. Infrastructure reads standard names.

## Decision

### 1. One name table, pinned to a commit

Every `gen_ai.*` string lives in `src/observability/semconv.py` and
nowhere else, read from:

```
open-telemetry/semantic-conventions-genai
94f432d7126f5884d30a2cdde6f4e89908ebb6fd   (2026-09-03)
  model/gen-ai/registry.yaml   attribute keys and enum members
  model/gen-ai/spans.yaml      span names, kinds, requirement levels
  model/gen-ai/metrics.yaml    metric names, instruments, units
```

**A commit, not a version, and that is not laziness.** The GenAI
conventions were deprecated out of the core `semantic-conventions`
repository at v1.42.0 and relocated to their own repository; v1.43.0
ships none of them, and the familiar
`opentelemetry.io/docs/specs/semconv/gen-ai/` pages are redirect stubs.
The new repository has **no tags and no releases** — verified against
the GitHub API, which returns an empty tag list — so there is no
versioned schema URL to put in a `Resource` and nothing to pin but a
SHA. Every definition adopted here carries a `Development` stability
badge. **These names are expected to churn.** One file to re-read
against a newer commit, one constant to bump, and a rename becomes a
reviewable diff instead of a search.

Two facts are worth recording because getting either wrong is easy and
silent:

- The provider attribute is **`gen_ai.provider.name`**. The older
  `gen_ai.system` was renamed, and it is the single most likely stale
  string to appear in an implementation written from memory.
  `tests/test_genai_conventions.py` scans `src/` for the quoted literal
  and fails if it ever reappears.
- **`OTEL_SEMCONV_STABILITY_OPT_IN` has nothing to do with GenAI
  content capture.** That claim is widely repeated and false; it
  appears nowhere in the conventions. The only opt-in variable they
  define is `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`, which
  ADR 0067 already wired into the log layer.

### 2. Trace continuity — the item worth more than every rename

`Job` gains a `trace_context: dict[str, str]` field whose default
factory injects the W3C carrier at construction, and `run_job` attaches
it before opening the run's `invoke_workflow` span. Submit → workflow →
node → model call is one trace.

Three choices inside that are load-bearing:

- **A carrier on the row, not a ContextVar.** The worker that runs a
  job is frequently not the process that accepted it: a redriven job is
  picked up by whichever worker swept it (ADR 0038). A ContextVar
  cannot cross that boundary; `traceparent` on the persisted row can,
  and `redis_store` derives its field list from the dataclass so it
  round-trips with no serializer change.
- **A `default_factory`, not a line in each submit handler.** There is
  more than one place a `Job` is constructed, and one of them
  forgetting would break continuity in the way that is hardest to
  notice — the trace would still look complete, just smaller.
- **`ParentBased` sampling, always.** An unparented ratio sampler would
  let the worker re-roll the decision for a job whose submitting
  request was already sampled, which would tear apart exactly the join
  being built.

### 3. The graph maps onto conventional spans, not invented ones

| Span | Kind | What it is here |
|---|---|---|
| `invoke_workflow {gen_ai.workflow.name}` | INTERNAL | one research run or guided-read session |
| `invoke_agent {gen_ai.agent.name}` | INTERNAL | one graph node |
| `plan {gen_ai.agent.name}` | INTERNAL | the planner node |
| `execute_tool {gen_ai.tool.name}` | INTERNAL | arXiv / Semantic Scholar / PDF / embedding |
| `chat {gen_ai.request.model}` | CLIENT | one Anthropic round trip |

`plan` is emitted for the planner specifically. The conventions say it
SHOULD only be reported when the instrumentation can *reliably*
distinguish planning from generic reasoning; here it can, because
planning is a named node of the graph rather than a phase to be
inferred.

`gen_ai.workflow.name` takes `research` / `session` — the same
vocabulary as `job.kind` (ADR 0057) rather than a second one — and
`gen_ai.conversation.id` takes the job's existing `conversation_id`
(ADR 0032), because a follow-up thread is a conversation in the
conventions' sense and needs no new identifier.

**`gen_ai.provider.name` is set on the `chat` span only.** This is a
question `02-STANDARDS.md` §1.2 leaves open, and `spans.yaml` at the
pinned commit settles it: the attribute is `required` on
`gen_ai.inference.client` and on the metric attribute group, and is not
listed at all on `invoke_agent.internal`, `execute_tool.internal`,
`invoke_workflow.internal` or `plan.internal`, whose required set is
`gen_ai.operation.name` plus `gen_ai.tool.name` for a tool span. That
is the right answer on the merits too: a local PDF parse has no
inference provider, and labelling one `anthropic` would be a
convenient lie on a cost dashboard.

### 4. The two per-invocation counters

`gen_ai.invoke_agent.inference_calls` and
`gen_ai.invoke_agent.tool_calls` are defined by the conventions as
"model calls / tool calls made during one agent invocation" — exactly
the process metrics an agent system needs, already named, and ones this
repository previously had no way to answer.

They are collected by a small counter object bound in a ContextVar for
the duration of an agent span: `src.llm` bumps the inference count,
`tool_span` bumps the tool count as it opens. Two consequences of that
design are deliberate. The tool count can never disagree with the
number of `execute_tool` spans under the node, because opening the span
*is* the increment. And the counter is mutated in place rather than
replaced, so the reader node's per-paper thread fan-out (ADR 0047) —
whose threads inherit a copy of the context, and therefore the same
object — counts against the node that spawned it. That sharing is why
the counter carries a lock.

Failed calls count, per the conventions: an agent that burned four
attempts did four inferences whatever came back.

### 5. Job metrics: `kind`, and the end of the flattering success

`record_job_terminal` gains `kind`, `cost_cap_status` and
`queue_wait_sec`, all passed from `_persist_terminal` — the runner's
single terminal-write choke point, which is what made adding them one
edit rather than seven.

A `degraded_close` now records `status="degraded_close"`. The job row
really is `succeeded` with no error, and that product contract (ADR
0062) does not change; what changes is that the metric stops saying the
same thing as an ordinary success, so `sum by (status)` shows cost
ceilings binding. `refused` is deliberately *not* remapped: that path
already ends `failed` with a real error type, and overriding its status
would lose information rather than add any.

### 6. USE for the queue, derived rather than counted twice

`research_job_queue_wait_seconds` is observed from the job's own
`created_at` / `started_at` at the same choke point.
`research_queue_depth` and `research_queue_saturation_ratio` are
observable gauges derived from the **existing** `active_jobs` callable
the lifespan already injects, against `api_max_concurrent_jobs`.

Instrumenting the semaphore directly would have been more precise and
would have introduced a second counter that could disagree with
`/healthz` — the drift ADR 0049 specifically avoided for the first two
gauges. The cost of deriving instead is stated rather than hidden:
`active_jobs` includes abandoned node threads (ADR 0047), which no
longer hold permits, so depth is an **upper bound** on jobs actually
waiting. A saturation signal that errs toward "more contended than it
is" errs in the right direction.

### 7. Old names kept as aliases, for one release

Every pre-existing instrument keeps working. `llm_calls_total` and
`gen_ai.client.operation.duration`'s count are the same measurement
under two names, as are `research_job_duration_seconds` and
`gen_ai.invoke_workflow.duration` for a job.

This **doubles the instrument count on that family** and is paid on
every export: more series in the collector, more cardinality in the
backend, a bigger OTLP payload each interval. It is paid because
dropping a name silently is the worse failure. A dashboard panel, an
alert rule or a runbook naming a series that stops arriving does not
error — it renders a flat zero, which reads as "the fleet is idle"
rather than "the metric was renamed". WO-A06's fault-injection tier
additionally asserts on these names as they stand on `main`, so the
aliases are load-bearing for a peer's test suite and not only for
dashboards.

**They may be dropped after one release**, once WO-A12's dashboards,
alert rules and runbooks name the conventional instruments and
`gen_ai.*` has been observed arriving in a collector.

`llm_cost_usd_total` is **not** an alias and does not expire. The
conventions define no cost attribute and no cost metric at all, so it
is the only name that measurement has.

### 8. Content capture stays off

No opt-in content attribute (`gen_ai.input.messages`,
`gen_ai.output.messages`, `gen_ai.system_instructions`,
`gen_ai.tool.definitions`, `gen_ai.retrieval.documents`) is defined or
set. This telemetry would otherwise carry paper text, learner text and
research queries.

One existing attribute changed to honour that. `traced_node` put the
user's raw research query on every node span as `state.query`; it is
now emitted only when `content_capture_enabled()` says so — the same
switch the log layer already reads, so an operator makes the content
decision once rather than discovering a second one.

### 9. Sampling and shutdown

`TRACE_SAMPLE_RATIO` is read from the environment by
`tracing.trace_sample_ratio()`, the way ADR 0067 reads its
content-capture flag and for the same reason: `src/config.py` belongs
to another work order this wave. **Unset installs no sampler**, which
leaves the SDK's own `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG`
handling intact — an operator already using the standard variables is
not silently overridden by a repository default. An unparseable value
warns and falls back rather than raising: a typo in an environment must
not be a process that will not boot.

`shutdown_tracing()` mirrors `shutdown_metrics()` and is called from
the same lifespan teardown, flush-then-shutdown on a 2-second budget,
failures logged and never raised.

## Alternatives considered

- **Invent private names.** Same effort, none of the interoperability,
  and it would make the MCP conventions — which live in the same
  repository and are the stated next step — a second vocabulary to
  reconcile rather than a continuation.
- **Wait for the conventions to stabilise.** They have no release
  process to stabilise into yet, and every span written in the
  meantime is a span that has to be migrated later. Pinning a SHA and
  saying so costs less than deferring.
- **Rename instruments in place rather than aliasing.** Cheaper, and it
  breaks dashboards silently — see §7. Also breaks a peer work order's
  tests, which is the version of that failure that would have been
  caught, unlike the dashboards.
- **Emit `gen_ai.provider.name` on every span for consistency.** One
  rule instead of two, at the price of asserting that a local PDF parse
  was served by Anthropic. The conventions do not ask for it on those
  spans; consistency is not worth a false attribution.
- **Instrument the semaphore for queue depth.** More precise, and a
  second source of truth that could disagree with `/healthz` — see §6.
- **Put the trace carrier in the job's `input_payload`.** Would have
  avoided a new field, and would have mixed a transport concern into
  the structured product input a session is redriven from. A named
  field is what a reader can ignore.
- **Record the conventional token/duration histograms inside
  `costs.record_llm_call`.** That is the cost choke point and knows
  nothing about response models, latency or failures; the span wrapper
  knows all three because it is holding the span that measured them.
  Keeping them separate is what keeps cost single-sourced.
- **Extend the log layer to emit spans.** Rejected in ADR 0067 and
  still right: a logger that started spans would be a logger that
  changed sampling decisions.

## Consequences

- **Positive**:
  - A job is one trace, across the queue and across processes. "Where
    did the time go" is answerable, and log lines already carry
    `trace_id` / `span_id` (ADR 0067), so log-to-trace navigation works
    with no further change.
  - Model calls are spans with conventional request, response and usage
    attributes, so a GenAI dashboard reads this system's telemetry
    without a translation layer.
  - Per-agent-invocation inference and tool counts exist, under the
    names the conventions already gave them.
  - Session SLOs become buildable (`kind`), cost ceilings become
    visible (`degraded_close`), queue pressure becomes visible before
    the ceiling binds, and the last export window survives SIGTERM.
  - The raw research query is off node spans by default.
- **Negative**:
  - The instrument count on the LLM and job families is doubled for one
    release. §7 says what that costs and when it ends.
  - The pinned conventions are pre-stable and will churn; some of these
    names will change. `semconv.py` is the blast radius.
  - Two shapes of tool instrumentation coexist — a decorator on three
    tool modules and a call-site context manager for arXiv — because
    `src/tools/arxiv_search.py` belongs to a peer work order this wave.
    Cosmetic, and named in the gaps below so it is not mistaken for a
    distinction.

## Known gaps, deliberately left

1. **`configure_metrics()` still has one caller.** The API lifespan.
   CLI and eval runs install no meter provider, so every record helper
   returns on its `None` check and the new conventional metrics are
   emitted by API workers only. Widening that was explicitly out of
   scope for this work order; tracing does not share the limitation,
   because `get_tracer()` configures lazily on first span.
2. **The redriver's orphan-fail path records `kind="unknown"`.**
   `_fail_orphan` has `job.kind` in hand but does not pass it, because
   `src/api/redriver.py` belongs to WO-A04 this wave. The current value
   is pinned by a test so the fix shows up as a failing assertion
   rather than as a series quietly changing shape.
3. **`TRACE_SAMPLE_RATIO` is not in `Settings`.** Same reason and same
   fold-in as ADR 0067's content-capture flag: `src/config.py` belongs
   to another work order this wave. WO-A12 folds it in, keeping the
   environment variable as the pydantic-settings alias.
4. **No `invoke_workflow` span on the CLI or eval paths.** The span is
   opened by `run_job`, so `make run` and `make eval` produce node
   spans without a workflow parent. Closing it means a span at
   `src/main.py`'s and the eval runner's entry points, neither of which
   this work order owns.
5. **`gen_ai.evaluation.result` is not emitted.** It is the defined
   event shape for attaching an eval verdict to a trace
   (`gen_ai.evaluation.name`, `.score.value`, `.score.label`,
   `.explanation`, `gen_ai.response.id`). WO-A08/A09 should adopt it
   rather than invent one.
6. **MCP conventions are not implemented.** `mcp.method.name`,
   `mcp.session.id`, `mcp.client.operation.duration` and the rest live
   in the same pinned repository. Adopting `gen_ai.*` now is what makes
   that a continuation instead of a second convention.
7. **`server.address` falls back to a constant** when the client
   singleton has been replaced by a test double that does not emulate
   `base_url`. Every real deployment resolves it from the SDK client.
