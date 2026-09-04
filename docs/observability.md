# Observability — logs, traces and metrics

Two contracts live on this page.

**The log contract** — every line this service writes is one JSON
object on stderr: which fields are always there, which `extra=` fields
are allowed, what is redacted, and what you have to do to add an event
or a field. The decision behind it is
[ADR 0067](decisions/0067-correlation-context-and-log-contract.md); the
original logging core is
[ADR 0012](decisions/0012-observability-core-logging-costs.md).

**The telemetry contract** — [traces](#traces) and
[metrics](#metrics), which follow the OpenTelemetry GenAI semantic
conventions rather than names of our own. The decision behind that is
[ADR 0066](decisions/0066-genai-semantic-conventions.md); the metrics
layer is [ADR 0049](decisions/0049-otel-metrics.md) and the tracer is
[ADR 0013](decisions/0013-sprint-1-finish-retry-checkpoint-tracing-recall.md).

The three signals join on the same identifiers: a log line carries
`trace_id` and `span_id` whenever a span is live, and `run_id` /
`job_id` are the same values on all three.

## The envelope

Present on every record, whether anything is bound or not:

| Field | Meaning |
|---|---|
| `ts` | UTC, millisecond precision, explicit offset (ADR 0042) |
| `level` | `DEBUG` … `CRITICAL` |
| `logger` | Dotted module name |
| `message` | The event name — see [event names](#event-names) |
| `run_id` | Workflow invocation, or `"-"` when nothing is bound |
| `service` | `settings.otel_service_name`, the same value the tracer's `Resource` carries |
| `version` | Package version from installed metadata |

Present when bound, and omitted rather than emitted as `null` when not:

| Field | Bound by | Meaning |
|---|---|---|
| `job_id` | the runner | The API job |
| `request_id` | the HTTP edge | The inbound request that started the work |
| `job_kind` | the runner | `research` / `session` (ADR 0057) |
| `principal_hash` | the auth layer | Salted digest of the API key id — **never the key id** |
| `worker_id` | the runner | The process executing |
| `trace_id`, `span_id` | an active OTel span | Log-to-trace navigation |

Present only when something went wrong with the line itself:

| Field | Meaning |
|---|---|
| `exception` | Formatted traceback, scrubbed |
| `dropped_extra_keys`, `dropped_extra_count` | `extra` keys the allowlist refused |
| `unregistered_event` | The event name is not in `KNOWN_EVENTS` (only flagged for `src.*` loggers) |

### Binding a context

```python
from src.observability import bind_context, reset_context, hash_principal

token = bind_context(
    request_id=request_id,
    principal_hash=hash_principal(key_id),
)
try:
    ...
finally:
    reset_context(token)
```

`bind_context` **merges**. The edge binds `request_id` and
`principal_hash`, the runner binds `job_id` and `worker_id`, the graph
binds `run_id`, and each is a separate call at a different depth of one
call stack. A replacing setter would let the innermost one erase the
principal. There is no way to unset a single field; use
`clear_context()` when a thread or task moves on to unrelated work.

`bind_run_id` / `reset_run_id` still work and are still the right call
when `run_id` is all you have.

### Across a thread pool

`ThreadPoolExecutor` does not carry ContextVars into worker threads.
Wrap the callable:

```python
with ThreadPoolExecutor(...) as executor:
    analyses = list(executor.map(propagate_run_context(fn), items))
```

That helper snapshots the whole `RequestContext` — not just `run_id` —
plus the cost accumulator and the cancel token, and clears them again
when the call returns so the pooled thread does not attribute the next
job's lines to this one's principal.

### `principal_hash`

`hash_principal(key_id)` returns a 12-character salted SHA-256 digest.
The key id itself never appears in a log line, matching the metrics
layer's deliberate refusal to label by `key_id` (ADR 0049) — a metric
label lives until the next scrape, a log field lives for the whole
retention window.

Set **`LOG_PRINCIPAL_SALT`** to the same value across the fleet. Without
it each process generates its own salt at import, so a principal's lines
group correctly *within* a process and not across one. Unsalted was
never an option: key ids are short operator-chosen strings and a bare
digest of one is recoverable from a word list.
`principal_salt_is_ephemeral()` reports which mode you are in.

## Event names

`message` is an event name, not a sentence. The names are a closed set,
`KNOWN_EVENTS` in `src/observability/logging.py`, and
`tests/test_log_contract.py` re-parses `src/` to prove every emitted
name is registered.

Adding a log line therefore means adding its name to the registry. That
is the point: a dashboard, an alert rule or a runbook can name an event
and be told when the code stops emitting it under that name, instead of
quietly matching nothing forever.

Pruning is *not* enforced. Deleting the last emitter of an event is
rare, and leaving the name registered for a release is how a
still-deployed older worker's lines stay recognised.

Library loggers (`httpx`, `anthropic`, …) are exempt — their messages
are prose, and flagging every one would make the field meaningless.

## `extra=` fields

Two rules, both enforced in the formatter:

- **Allowlist.** Only keys in `ALLOWED_EXTRA_KEYS` reach the payload.
  Anything else is dropped, named in `dropped_extra_keys` on the line,
  and counted process-wide (`dropped_extra_key_counts()`).
- **Size cap.** Strings over `MAX_EXTRA_VALUE_CHARS` (2048) are
  truncated with a marker saying how much was cut; containers are
  clipped to `MAX_EXTRA_ITEMS` (50) per level and walked no deeper than
  `MAX_EXTRA_DEPTH` (3); `bytes` are reported by size and never decoded.

A field nobody vetted costs storage, index cardinality and — for a
report body or a user query — exposure. If your new field is a
legitimate machine fact, register it. If it is user content, see below.

A caller may *fill* a context field from `extra` when nothing has bound
it — `job_id` and `worker_id` arrive that way at most call sites today
— but may never *overwrite* a bound one. Otherwise any call site could
attribute its line to a principal that did not make the request.

## Redaction

### User content is off by default

Values under `USER_CONTENT_KEYS` — `query`, `result`, `raw`, `payload`,
`preview`, `goals`, `turn` and friends — are replaced with
`[redacted: N chars]`. The size survives because "did the model produce
anything" is answerable without the text.

Opt in with either:

- **`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`** — the flag
  the OpenTelemetry GenAI conventions define, and the one to set if you
  also want span content.
- **`LOG_CAPTURE_USER_CONTENT`** — the narrower repo-local alias: logs
  only.

Both default to off. The conventions are explicit that instrumentations
"SHOULD NOT capture [message content] by default, but SHOULD provide an
option for users to opt in".

> **Note:** turning capture on means a failed terminal write logs the
> whole report body again, which is how a lost success used to be
> recoverable from the log. Off is the default because the recovery
> path is worth less than the exposure; know which trade you are making.

### Credentials are always scrubbed

Five rules run over every string the formatter emits — the message,
each `extra` value, and the formatted traceback. The traceback matters
most: the leak that actually happened was not a call site logging a
password, it was a connection error whose *message* carried the URL.

| Rule | Example in | Example out |
|---|---|---|
| URL userinfo | `postgres://u:pw@db/x` | `postgres://***@db/x` |
| Bearer token | `Bearer abc123.def456` | `Bearer ***` |
| `sk-` API key | `sk-ant-api03-AbC123…` | `sk-***` |
| Email address | `jane.doe@lab.example.org` | `***@lab.example.org` |
| Base64-ish blob | 40+ mixed-case chars with a digit | `***[78 chars]` |

The last two are deliberately conservative. The email rule keeps the
domain because the domain is the diagnostic half and the local part is
the personal one. The blob rule requires mixed case *and* a digit, so a
lowercase hex digest or a long CamelCase identifier survives — deleting
those would delete the ids operators join on.

`redact_url` remains the right call when you know you are holding a
URL: it parses where the regex matches, and returns `***` for input it
cannot parse rather than passing an unproven string through.

## Traces

Off by default (`ENABLE_TRACING`). With no `OTEL_EXPORTER_ENDPOINT`,
spans print to stderr; set it to an OTLP HTTP endpoint
(`http://collector:4318`) and they go there instead.

### One job is one trace

This is the property everything else hangs off. A job's spans used to
be N disconnected roots, because the process that accepts a job is
frequently not the process that runs it — a redriven job is picked up
by whichever worker swept it. So the trace context is **injected onto
the job row** when the `Job` is constructed, and **attached by the
worker** before it opens the run's span:

```
POST /research                     (the request's span)
└── invoke_workflow research       (run_job, after attaching job.trace_context)
    ├── plan planner
    │   └── chat claude-sonnet-4-6
    └── invoke_agent search
        ├── chat claude-sonnet-4-6
        └── execute_tool arxiv_search
```

`Job.trace_context` holds a W3C carrier (`traceparent`, plus
`tracestate` when a vendor set one). It is empty when nothing was
sampled, which every consumer reads as "no parent" — that is why CLI
runs and tests work with no provider installed.

### The spans

| Span name | Kind | Opened by |
|---|---|---|
| `invoke_workflow {research\|session}` | INTERNAL | `run_job` |
| `invoke_agent {node}` | INTERNAL | `traced_node`, per graph node |
| `plan {node}` | INTERNAL | `traced_node`, for the planner only |
| `execute_tool {tool}` | INTERNAL | the tool call sites |
| `chat {model}` | CLIENT | `src.llm.call_llm` |

Attributes, all from `src/observability/semconv.py`:

| Span | Attributes |
|---|---|
| `invoke_workflow` | `gen_ai.operation.name`, `gen_ai.workflow.name`, `gen_ai.conversation.id`, `error.type` |
| `invoke_agent` / `plan` | `gen_ai.operation.name`, `gen_ai.agent.name`, `error.type`, plus `run_id`, `state.iteration`, `result.*_count`, `llm.cost_usd`, `llm.cost_delta_usd`, `llm.call_count`, `llm.call_delta` |
| `execute_tool` | `gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.tool.type`, `error.type` |
| `chat` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.request.max_tokens`, `gen_ai.request.temperature`, `server.address`, `gen_ai.response.id`, `gen_ai.response.model`, `gen_ai.response.finish_reasons`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_write.input_tokens`, `error.type` |

Three things about that table are worth knowing rather than
rediscovering:

- **The provider attribute is `gen_ai.provider.name`, not
  `gen_ai.system`.** The older name was renamed and is the most likely
  stale string in code written from memory. A test scans `src/` for it.
- **It is set on the `chat` span only.** The conventions require it on
  the inference span; the four in-process spans do not take it, and a
  local PDF parse has no inference provider to name.
- **`error.type` is the exception class name, never the message.** A
  message routinely carries the input that caused it.

### Sampling

`TRACE_SAMPLE_RATIO=0.1` samples one trace in ten. Leaving it unset
installs no sampler at all, so the SDK's own `OTEL_TRACES_SAMPLER` /
`OTEL_TRACES_SAMPLER_ARG` still apply — if you already know those, they
keep working. The sampler is always parent-based, so a worker never
re-decides for a job whose request was already sampled.

An unparseable value logs `tracing_sample_ratio_invalid` and falls
back; it does not stop the process from starting.

### Content stays off

Spans carry the *shape* of the work, not the text of it. The research
query is not on a node span, prompts and completions are not on the
`chat` span, and none of the conventions' opt-in content attributes are
set. `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` turns
capture on for logs **and** spans together — it is one decision, not
two.

`OTEL_SEMCONV_STABILITY_OPT_IN` has nothing to do with this, despite
what a lot of blog posts say. It appears nowhere in the GenAI
conventions.

## Metrics

Off by default (`ENABLE_METRICS`), and — today — installed only by the
API lifespan, so CLI and eval runs emit nothing. Tracing has no such
limitation because the tracer configures lazily on the first span.

### Conventional instruments

All histograms, all named from the pinned specification commit:

| Instrument | Unit | Attributes |
|---|---|---|
| `gen_ai.client.token.usage` | `{token}` | operation, provider, request/response model, `gen_ai.token.type` |
| `gen_ai.client.operation.duration` | `s` | the same, plus `error.type` |
| `gen_ai.invoke_agent.duration` | `s` | `gen_ai.agent.name`, `error.type` |
| `gen_ai.invoke_agent.inference_calls` | `{inference_call}` | `gen_ai.agent.name` |
| `gen_ai.invoke_agent.tool_calls` | `{tool_call}` | `gen_ai.agent.name` |
| `gen_ai.execute_tool.duration` | `s` | operation, `gen_ai.tool.name`, `error.type` |
| `gen_ai.invoke_workflow.duration` | `s` | `gen_ai.workflow.name`, `error.type` |

The two `invoke_agent` counters answer "how many model calls and tool
calls did this node make" — the questions an agent system most needs
and the ones this repository could not answer before. A tool call is
counted by the tool span itself, so the counter can never disagree with
the number of `execute_tool` spans under the node.

### Repository instruments

| Instrument | Kind | Attributes |
|---|---|---|
| `research_jobs_total` | counter | `status`, `error_type`, `kind` |
| `research_job_duration_seconds` | histogram | `status`, `kind` |
| `research_job_queue_wait_seconds` | histogram | `kind` |
| `research_active_jobs` | gauge | — |
| `research_abandoned_node_threads` | gauge | — |
| `research_queue_depth` | gauge | — |
| `research_queue_saturation_ratio` | gauge | — |
| `llm_cost_usd_total` | counter | `model` |
| `llm_calls_total` | counter | `model` |
| `llm_retries_total` | counter | `model` |
| `llm_upstream_errors_total` | counter | `model`, `status` |
| `rate_limit_rejections_total` | counter | `backend` |

`status` on `research_jobs_total` takes one extra value that is not a
`JobStatus`: **`degraded_close`**, for a session that hit its cost
ceiling and was closed politely (ADR 0062). The job row really is
`succeeded` — the API contract does not change — but reporting it as an
ordinary success made budget exhaustion invisible in the one signal an
operator watches.

`research_queue_depth` is `active_jobs - api_max_concurrent_jobs`,
floored at zero, and is an **upper bound**: `active_jobs` includes
abandoned node threads, which no longer hold permits. A saturation
signal that errs toward "more contended than it is" errs in the useful
direction.

### The old names still work, for one release

`llm_calls_total` and `gen_ai.client.operation.duration`'s count are
the same measurement; so are `research_job_duration_seconds` and
`gen_ai.invoke_workflow.duration`. Both are emitted, which doubles the
series on those families — a real cost, paid because a renamed metric
does not error, it renders a flat zero, and a flat zero reads as "the
fleet is idle".

Once dashboards and alert rules name the `gen_ai.*` instruments, the
aliases can go. **`llm_cost_usd_total` is not one of them**: the
conventions define no cost metric, so that is the only name it has.

### No attribute is unbounded

Everything above attributes by a closed set — a job kind, a terminal
status, an error *type*, a model id, a graph node name, a tool name.
Nothing takes a query, a job id, a URL, a paper id or a principal.
`tests/test_genai_conventions.py` drives a job with a distinctive query
and asserts none of it reaches a metric attribute.

## Adding to the contract

1. New event: add the name to `KNOWN_EVENTS`.
2. New field: add the key to `ALLOWED_EXTRA_KEYS`; if it carries user or
   model text, add it to `USER_CONTENT_KEYS` too.
3. Run `pytest tests/test_log_contract.py`. It re-derives both
   registries from `src/` and names the file and line of anything
   unregistered.

Keys that only reach `extra=` through a `**` splat are invisible to
that scan and are registered by hand, with a comment beside them saying
where they come from.

## Known gaps

1. **uvicorn access lines are not JSON.** `serve.py` runs with
   `log_config=None`, so access lines arrive as unparsed text alongside
   the JSON stream. WO-A10 owns the fix; nothing here changes it.
2. **The content-capture and sampling flags are not in `Settings`.**
   `content_capture_enabled()` and `trace_sample_ratio()` read
   `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`,
   `LOG_CAPTURE_USER_CONTENT` and `TRACE_SAMPLE_RATIO` from the
   environment, because `src/config.py` belonged to other work orders
   in both waves. WO-A12 folds all three into `Settings`, at which
   point the env vars stay as the pydantic-settings aliases.
3. **The context is defined but not yet bound at the edges.** Nothing in
   `src/api/**` calls `bind_context` yet, so `request_id`,
   `principal_hash` and `job_kind` are absent from live lines until
   WO-A10 wires them. The contract is in place first on purpose: the
   fields have to exist before anything can fill them.
4. **`admin_migrate` logs `owner` verbatim**, which is a principal
   identifier. It should become a `principal_hash`; the file belongs to
   another work order.
5. **A schema standard is landing.** ISO/IEC FDIS 24970 (AI system
   logging) is at stage 50.20 and likely to become the reference for
   exactly the fields above. The field names are therefore constants in
   two places — the envelope block in `logging.py` and `CONTEXT_FIELDS`
   / `context_fields()` in `context.py` — rather than literals scattered
   through the formatter, so remapping is an edit rather than a hunt.
6. **Metrics exist only inside API workers.** `configure_metrics()`
   has one caller — the API lifespan — so `make run` and `make eval`
   install no meter provider and every record helper returns on its
   `None` check. Deliberate for the server-shaped instruments;
   widening it was out of scope for ADR 0066.
7. **No `invoke_workflow` span on the CLI or eval paths.** The span is
   opened by `run_job`, so those entry points produce node spans with
   no workflow parent.
8. **The redriver records `kind="unknown"`** on both of its terminal
   outcomes — a failed orphan and, since ADR 0068, a dead-lettered
   job. It has `job.kind` in hand but does not pass it;
   `src/api/redriver.py` belonged to another work order. A test pins
   the current value so the fix is visible when it lands.
9. **The GenAI conventions are pre-stable and will churn.** They have
   left the core semantic-conventions repository and their new home has
   no tagged release, so ADR 0066 pins a commit SHA. Every `gen_ai.*`
   name is a constant in `src/observability/semconv.py` — one file to
   re-read against a newer commit.
