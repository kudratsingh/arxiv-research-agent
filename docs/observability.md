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

[The HTTP edge](#the-http-edge) is where both contracts start. One
middleware mints or adopts the request id, binds the correlation
context, extracts inbound trace context, records the RED metrics and
writes the access line — so everything below it is handed a request
that is already identified, joined to a trace, and counted.

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

The variable is `Settings.log_principal_salt` (WO-C3) — the last of
ADR 0067's flags to move out of a direct `os.environ` read. Two things
follow. It is a `SecretStr`, so it renders as `**********` in a repr,
in `model_dump()` and in `model_dump_json()`: a leaked salt puts the
key ids back within reach of a word list, so nothing may print it, and
`src/observability/context.py` takes the raw value exactly once,
through `get_secret_value()`. And a *blank* value is unset, not a
salt — `LOG_PRINCIPAL_SALT=` in a Compose file leaves you in the
per-process mode, which is what `principal_salt_is_ephemeral()` will
tell you.

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

One setting opts in — `LOG_CAPTURE_USER_CONTENT` in `Settings` — and it
answers to two environment variables:

- **`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`** — the flag
  the OpenTelemetry GenAI conventions define, and the one to prefer.
- **`LOG_CAPTURE_USER_CONTENT`** — the older repo-local name, kept so
  no deployment has to change.

They are the same switch: either one turns content on **for logs and
for spans together**, because it is one content decision. (An earlier
version of this page called the second one "logs only". It never was —
`traced_node` reads the same resolver — and the claim is corrected
rather than quietly dropped.)

Alias order is precedence, which matters only if you set both and they
disagree: the conventional name is checked first, so
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` with
`LOG_CAPTURE_USER_CONTENT=true` leaves capture **off**.

The default is off. The conventions are explicit that instrumentations
"SHOULD NOT capture [message content] by default, but SHOULD provide an
option for users to opt in".

**This is the one setting you may change without a restart.** Every
other knob in `Settings` is read from a frozen singleton built at
import; this one is re-read from the environment on every line, because
it is what an operator reaches for mid-incident to see what a parse
failure was actually handed. The value the process booted with is
validated by pydantic — `LOG_CAPTURE_USER_CONTENT=ture` refuses to
start, naming the variable you set — and a live flip is checked against
the same true/false grammar, with a value outside it leaving the
configured value standing and warning once under
`content_capture_flag_invalid`.

> **Note:** turning capture on means a failed terminal write logs the
> whole report body again, which is how a lost success used to be
> recoverable from the log. Off is the default because the recovery
> path is worth less than the exposure; know which trade you are making.

### Credentials are always scrubbed

Nine rules run over every string the formatter emits — the message,
each `extra` value, and the formatted traceback. The traceback matters
most: the leak that actually happened was not a call site logging a
password, it was a connection error whose *message* carried the URL.

They live in `REDACTION_RULES` in `src/observability/logging.py`, in
the order they run, each with a name. The names are what the property
tier parametrises over, so a rule added without a generator fails a
test rather than shipping unproven.

| Rule | Example in | Example out |
|---|---|---|
| `url_userinfo` | `postgres://u:pw@db/x` | `postgres://***@db/x` |
| `bearer_token` | `Bearer abc123.def456` | `Bearer ***` |
| `sk_api_key` | `sk-ant-api03-AbC123…` | `sk-***` |
| `environment_scoped_key` | `gw_live_PROBEprobe…` | `gw_live_***` |
| `vendor_prefixed_token` | `ghp_16CharsAndMore…`, `xoxb-2345…` | `ghp_***`, `xoxb-***` |
| `aws_access_key_id` | `AKIAIOSFODNN7EXAMPLE` | `AKIA***` |
| `json_web_token` | `eyJhbGci….eyJzdWIi….dBjftJ…` | `***[jwt]` |
| `email_address` | `jane.doe@lab.example.org` | `***@lab.example.org` |
| `base64_blob` | 40+ mixed-case chars with a digit | `***[78 chars]` |

**Order is load-bearing.** URL userinfo runs first so
`postgres://user:pw@host` cannot be claimed by the email rule on its
`pw@host` tail, and every prefixed rule runs ahead of the blob rule for
the same kind of reason: `ghp_` plus thirty-six characters is *also* a
forty-character base64-ish run, and `***[40 chars]` would hide the
secret while losing the one thing an operator needs — which console to
go and revoke at. A secret hidden under the wrong rule looks correct in
a test and is wrong in production.

**Precision is the constraint, not recall.** Every rule is narrowed so
that legitimate content survives byte-for-byte, and the narrowings are
specific:

- The blob rule requires mixed case *and* a digit, so a lowercase hex
  digest or a long CamelCase identifier survives — deleting those would
  delete the ids operators join on.
- `environment_scoped_key` admits no `_` inside the body and matches
  `_live_` / `_test_` case-sensitively, so `feature_flag_test_data` and
  the *name* `STRIPE_LIVE_SECRET_KEY` are untouched.
- `vendor_prefixed_token` runs off a closed list of published issuer
  prefixes, and only the dash-separated issuers (Slack, GitLab) admit a
  dash in the body — which is what keeps `hf_all-MiniLM-L6-v2`, a model
  name, out of its jaws.
- The email rule keeps the domain, because the domain is the diagnostic
  half and the local part is the personal one.

Measured: the four rules ADR 0084 added were run over every tracked
text line in this repository — 1,246,805 lines across 1,725 files — and
changed two, both of them gateway-credential test fixtures. Two gaps
are recorded rather than closed badly: short `Basic <base64>`
credentials, and unprefixed high-entropy secrets such as an AWS
*secret* access key, which no text rule can tell from a content hash.
ADR 0084 says why each rule is in and what was deliberately left out.

`redact_url` remains the right call when you know you are holding a
URL: it parses where the regex matches, and returns `***` for input it
cannot parse rather than passing an unproven string through.

## The HTTP edge

One middleware — `ObservabilityMiddleware` in `src/api/app.py` — owns
everything that happens to a request before and after the router sees
it. It is a raw ASGI callable rather than a `BaseHTTPMiddleware`
subclass, because `BaseHTTPMiddleware` proxies `receive` through a
memory stream and breaks `Request.is_disconnected()`, which is the call
`GET /research/{job_id}/stream` uses to notice that an SSE client has
gone away. Trading that for an access log would leak a pub/sub
connection per disconnect.

It is registered **last** in `create_app`, which puts it outermost: a
CORS preflight, a 404 for an unrouted path and a 405 from the router
are all requests a fleet has to be able to see.

### The request id

`X-Request-Id`, in both directions. An inbound one is **adopted** when
it matches `[A-Za-z0-9._:-]{1,128}` — a UUID, a ULID, a W3C trace id
and an nginx `$request_id` all fit inside that — so an operator holding
the caller's id can find our side of the same request. Anything else is
*discarded* rather than sanitized, and a fresh one minted: keeping an
attacker's string on the line in a mangled form leaves the field
untrustworthy, and this value ends up in an indexed store, in a
response header and on a span.

One value reaches four places: the response header, ADR 0064's error
envelope (`error.request_id`), every log line the request emits (via
the bound context), and the `request_id` attribute on its server span.

### The access line

`api_request_completed`, at INFO whatever the status, with the facts as
fields:

```json
{"ts":"...","level":"INFO","logger":"src.api.app","message":"api_request_completed",
 "request_id":"bffb…","method":"GET","route":"/research/{job_id}","http_status":200,
 "elapsed_ms":7.918,"error_type":null}
```

It replaces uvicorn's, which `serve.py` turns off with
`access_log=False`. Under `log_config=None` and with the access log on,
`uvicorn.access` records propagate into our root handler and arrive as
JSON whose `message` is the prose
`'127.0.0.1:52344 - "GET /research/9f2c HTTP/1.1" 200'` — five facts in
one string, none of them a field, with the raw path inside it.

It stays INFO for a 5xx on purpose: the 4xx/5xx judgement is made once,
by ADR 0064's `api_request_rejected` / `api_request_failed`, and a
second WARNING here would double-report every failure.

`route` is the route **template**, never the raw path — the same rule
the `http.route` metric attribute follows, and for the same reason: a
path carries job and conversation ids, and a log field is indexed per
value. A request that matched no route reports `route: null`.

### Liveness and readiness

| Endpoint | Question | Status |
|---|---|---|
| `/healthz` | Is this process alive? | **Always 200**, with `status: degraded` in the body when a dependency is down |
| `/readyz` | Can this worker take more traffic? | 200 when ready, **503** when a dependency is down or the queue is saturated |

`/healthz` keeps its always-200 semantics deliberately (ADR 0042):
restarting a worker does not fix a dead Redis, so a liveness probe that
503s on dependency failure turns a backend blip into a rolling-restart
storm. That was only ever safe once readiness existed — without
`/readyz` an orchestrator had no way to drain a worker whose Redis had
gone away, and every submit it kept receiving could only 500.

Both endpoints run the same probes through one helper, so they cannot
come to disagree about whether Redis is up, and they share one latched
edge set, so an outage logs `api_health_dependency_degraded` once
however many probes observe it.

`/readyz` also 503s at saturation — `active_jobs >= max_concurrent_jobs`
— because a job accepted then would sit in `pending` behind the
concurrency ceiling. The body is the same shape either way, and the
*reason* is readable from it (`dependencies` names a failed backend;
`active_jobs` against `max_concurrent_jobs` shows saturation) rather
than needing a third `status` value.

`/readyz` is deliberately **absent** from
`web/contract/openapi.json`. That document is the frontend's generated
contract — snapshotted by a test, regenerated into `schema.d.ts`, and
pinned again in `web/tests/api.test.ts` — and `/readyz` has no browser
client. It is documented here and in
[`architecture.md`](architecture.md) instead.

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
POST /research                     (ObservabilityMiddleware, SERVER)
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

The **outer hop** is the middleware's. It extracts inbound W3C context
from the request headers, so a caller who already had a trace — the
Next.js proxy, another service — gets one trace across the hop instead
of two disconnected halves; and when nobody upstream had one, the
server span is the root that submit and its job then share. The whole
header mapping is handed to the propagator rather than a hand-picked
`traceparent`, so a deployment configured for B3 or Jaeger propagation
keeps working with no edit at the edge.

The span is opened before routing (a span has to start before the
router runs) and **renamed** in the middleware's `finally` once the
matched template is known — the same two-step every ASGI
instrumentation performs.

### The spans

| Span name | Kind | Opened by |
|---|---|---|
| `{method} {route}` | SERVER | `ObservabilityMiddleware`, per HTTP request |
| `invoke_workflow {research\|session}` | INTERNAL | `run_job` |
| `invoke_agent {node}` | INTERNAL | `traced_node`, per graph node |
| `plan {node}` | INTERNAL | `traced_node`, for the planner only |
| `execute_tool {tool}` | INTERNAL | the tool call sites |
| `chat {model}` | CLIENT | `src.llm.call_llm` |

Attributes, all from `src/observability/semconv.py`:

| Span | Attributes |
|---|---|
| `{method} {route}` | `http.request.method`, `http.route`, `http.response.status_code`, `url.scheme`, `error.type`, `request_id`, plus `http.request.method_original` when the method collapsed to `_OTHER` |
| `invoke_workflow` | `gen_ai.operation.name`, `gen_ai.workflow.name`, `gen_ai.conversation.id`, `error.type` |
| `invoke_agent` / `plan` | `gen_ai.operation.name`, `gen_ai.agent.name`, `error.type`, plus `run_id`, `state.iteration`, `result.*_count`, `llm.cost_usd`, `llm.cost_delta_usd`, `llm.call_count`, `llm.call_delta` |
| `execute_tool` | `gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.tool.type`, `error.type` |
| `chat` | `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.request.max_tokens`, `gen_ai.request.temperature`, `server.address`, `gen_ai.response.id`, `gen_ai.response.model`, `gen_ai.response.finish_reasons`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_write.input_tokens`, `error.type` |

Four things about that table are worth knowing rather than
rediscovering:

- **The provider attribute is `gen_ai.provider.name`, not
  `gen_ai.system`.** The older name was renamed and is the most likely
  stale string in code written from memory. A test scans `src/` for it.
- **It is set on the `chat` span only.** The conventions require it on
  the inference span; the four in-process spans do not take it, and a
  local PDF parse has no inference provider to name.
- **`error.type` is the exception class name, never the message.** A
  message routinely carries the input that caused it. On the server
  span it falls back to the status code as a string for a 5xx that was
  already handled and left no exception to name.
- **`http.request.method_original` is on the span and never on a
  metric.** A span is one record, so a rejected method costs one field
  there; the same value as a metric attribute would mint a series per
  value, which is what `_OTHER` exists to stop.

### Sampling

`TRACE_SAMPLE_RATIO=0.1` samples one trace in ten. Leaving it unset
installs no sampler at all, so the SDK's own `OTEL_TRACES_SAMPLER` /
`OTEL_TRACES_SAMPLER_ARG` still apply — if you already know those, they
keep working. The sampler is always parent-based, so a worker never
re-decides for a job whose request was already sampled.

It is `Settings.trace_sample_ratio`, a `float | None` bounded to
`[0.0, 1.0]`, and it is read once at `configure_tracing()` because a
`TracerProvider` takes its sampler at construction. **A value outside
that interval, or one that is not a number, now stops the process at
settings load.** It used to clamp and warn, which meant
`TRACE_SAMPLE_RATIO=10` from somebody who meant 10% sampled every trace
in production and said nothing. Refusing is the ADR-0046 rule every
other knob here follows; the reversal of ADR 0066's local exception is
deliberate and is recorded in that ADR's gap list.

**When you are trying to look at one specific run, set it to `1.0`.**
The observability overlay's own default is `0.1`, which means nine
attempts in ten produce nothing at all and the trace viewer looks broken
rather than empty. The overlay reads the variable from the host
(`compose.observability.yml`) precisely so that this is a prefix on one
command rather than an edit to a file.

### Actually looking at one

The span table above is a claim, and until WO-INF1 there was no way in
this repository to check it: the collector overlay exported traces to
`debug: verbosity: basic`, which writes a span count to a log and is not
a waterfall.

[`deploy/observability/compose.viewers.yml`](../deploy/observability/compose.viewers.yml)
adds Jaeger — all-in-one, in-memory, loopback only — and
[its README](../deploy/observability/README.md#seeing-one-job-as-one-trace)
carries the one command that renders a job as a single tree at zero
spend. The short version:

```bash
TRACE_SAMPLE_RATIO=1.0 USE_MOCK_DATA=true \
ANTHROPIC_API_KEY=local-preview-disabled \
docker compose -f docker-compose.yml \
  -f deploy/observability/compose.observability.yml \
  -f deploy/observability/compose.viewers.yml up -d --wait
```

Then `POST /research` and open `http://127.0.0.1:16686`. Eight spans,
one trace, across two processes — which is the "one job is one trace"
property above, seen rather than asserted.

The honest limit: mock mode (ADR 0080) branches in front of every model
call, so that trace contains **no `chat` spans** and none of the
`gen_ai.*` request, usage or cost attributes in the table above. Those
need a real credential and real money. Dropping `USE_MOCK_DATA` at the
disabled sentinel does produce a `chat` span for free — but the job
fails at the planner's first call, so the trace is four spans ending in
`error.type=UpstreamModel` rather than a graph. So: mock mode shows the
whole shape and no model calls; the sentinel shows a model call and no
whole shape. Both prove the trace is continuous across the process
boundary, and neither is a clean tree of successful model calls.

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

### The HTTP surface — RED

Unlike the GenAI family, the HTTP conventions are **stable**, so these
names are pinned by the specification rather than by a commit:

| Instrument | Kind | Unit | Attributes |
|---|---|---|---|
| `http.server.request.duration` | histogram | `s` | `http.request.method`, `http.route`, `http.response.status_code`, `url.scheme`, `error.type` |
| `http.server.active_requests` | up/down counter | `{request}` | `http.request.method`, `url.scheme` |

**There is no request counter, and that is not an omission.** A
histogram carries its own `count`, so `rate(count)` is the R of RED and
`rate(count) by http.response.status_code` is the E — which is exactly
why the conventions define no `http.server.request.total`. Adding one
would double the write volume to answer a question this already
answers, under a name no off-the-shelf dashboard reads.

Three attribute rules, all from the specification rather than from us:

- **`http.route` is the template**, `/research/{job_id}`, never the raw
  path. The path carries a job id, so the raw form is one series per
  job.
- **`http.route` is absent when nothing matched.** The attribute is
  conditionally required precisely so "no route" is expressible;
  filling it with the path would put one series per 404'd URL into the
  store, which anyone outside can fire at will.
- **An unknown method becomes `_OTHER`.** `http.request.method` is
  attacker-controlled on an open port, and a loop sending `AAAA`…`ZZZZ`
  would otherwise mint a series per request.

`error.type` follows the same "every series has one shape" rule as the
GenAI instruments: `"none"` for a request that did not fail, the
exception class for one that raised, and the status code as a string
for a 5xx that ADR 0064's boundary had already handled. A 4xx is not an
error — counting a client's bad request as a server failure is how an
availability SLI ends up measuring the caller's behaviour.

Together with the queue gauges below, this is what closed the gap the
fault tier had recorded: a Redis outage at submit used to move **no
instrument at all**, because the request never became a job, so a fleet
whose Redis had died read as idle rather than as failing.

One caveat when reading the histogram: `GET /research/{job_id}/stream`
is an SSE connection held open for the life of a job, so its
observations are job durations rather than request latencies and land
in the top bucket. Cut latency panels by `http.route` and leave that one
out; it is honest data about a different question. It is also why the
in-flight counter is worth watching separately — an SSE client holds
`http.server.active_requests` up for the whole run, correctly.

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
| `research_degradations_total` | counter | `rung`, `component` |
| `trajectory_events_total` | counter | `lane`, `outcome` |
| `trajectory_faults_total` | counter | `stage`, `error_type` |

`rung` and `component` on `research_degradations_total` are **closed
sets** (`DEGRADATION_RUNGS`, `DEGRADATION_COMPONENTS` in
`src/observability/metrics.py`), enforced by an AST scan of `src/` in
`tests/test_degradation_ladder.py`. `rung` names a row of
[`reliability.md` §5](reliability.md#5-the-degradation-ladder)'s ladder
and is what the quality SLI is computed from; `component` names the
subsystem that degraded, at the granularity a runbook is written for.
The `reason` that `resilience.record_degradation` also takes is
deliberately *not* here — it stays on the `resilience_degraded` log
line, because the metric answers "how much, at which rung" and the log
answers "why" (ADR 0081).

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
status, an error *type*, a model id, a graph node name, a tool name, a
route template, a known HTTP method.
Nothing takes a query, a job id, a URL, a paper id or a principal.
`tests/test_genai_conventions.py` drives a job with a distinctive query
and asserts none of it reaches a metric attribute.

The HTTP surface is the only one whose attributes come from *outside*
the process, which is why two of its three rules above are containment
rules rather than naming ones.

## The contract event bridge (P0-WO08, ADR 0083)

The canonical trajectory (RFC 10) is a **ledger**, not a log, and this
section is about how it touches the three surfaces this page describes
without becoming a fourth one.

**The ledger is written first, and a projection can never unwrite it.**
An accepted event is durable — in memory always, and in a run-scoped
JSONL file when capture is permitted — before any log line, span
attribute or SSE comparison happens. Every projection runs inside its own
containment: it can fail, it is counted and named when it does
(`trajectory_projection_failed`, with the projection's name in `stage`),
and the event stays exactly where it was. RFC 10 §16 puts it in one
sentence: "projection failures do not alter history."

**The three projections.**

| Canonical event | Projection | Where |
|---|---|---|
| `attempt.started` | `job_started` SSE | `sse_event_name_for` |
| `action.completed` | `node_completed` SSE | `sse_event_name_for` |
| `hitl.requested` (`plan_review` / `learner_turn`) | `plan_ready` / `turn_ready` SSE | `sse_event_name_for` |
| `run.completed` / `run.failed` / `run.budget_stopped` / `run.cancelled` | the three terminal frames | `sse_event_name_for` |
| any | `trajectory_event_recorded` log line | `CONTRACT_EVENT_LOG_PROJECTION`, off by default |
| any | a span event on the active span | always on |

The SSE column is a **derivation, not an emitter**. Nothing in the
bridge writes a frame, no new event name reaches the wire, and every
projected name is a member of the set `tests/test_contract_sse_events.py`
already pins from both sides. The terminal case is asserted
byte-identical to the frame `terminal_event_data` builds, which is what
makes "the stream is a projection of the ledger" a checkable claim
rather than a comforting one.

The log projection is off by default. One INFO per canonical event
roughly doubles a research job's log volume to answer a question the
ledger already answers, so it is a debugging switch
(`CONTRACT_EVENT_LOG_PROJECTION=true`) rather than a default.

The span projection adds a span *event* rather than a span: RFC 10 §16
allows spans to be sampled without affecting the ledger, so a trace is a
view of a trajectory and never its record. In the other direction the
envelope carries `trace_ref` — the active trace and span ids, copied when
one exists and simply absent when it does not.

**Two metrics, and what each is for.** `trajectory_events_total{lane,
outcome}` is the recording rate; `outcome` is `accepted`, `deduplicated`
(an idempotent retry answered from the index, RFC 10 §11.2) or
`rejected`. `trajectory_faults_total{stage, error_type}` is everything
that failed around the accept — `sink_write`, `projection`,
`artifact_integrity`, `artifact_access`, `cost_reconciliation`,
`chain_verification` — attributed by a member of ADR 0064's closed error
registry. A non-zero fault rate beside a climbing accepted rate is the
designed behaviour, not an incident. A sustained `sink_write` rate means
episodes are being recorded and not written down.

**Capture is gated twice, and neither gate is a preference.**
`CONTRACT_EVENT_CAPTURE` is `off` by default and its only other value is
`evaluation_only`; there is no `production` value. Independently, a run
whose consent scope is `product_operation_only` — which is what a real
research job and a real learner session carry — is refused the durable
sink and the artifact store whatever the flag says. Production and
user-content capture stay disabled pending D8 (P0-WO09), and that
sentence is enforced by a test over every consent scope rather than by
this paragraph.

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

**One closed, and worth saying why it stayed open.** This list used to
begin with "the content-capture and sampling flags are not in
`Settings`", and named **WO-A12** as the work order that would fold
them in. That sentence was wrong on its face: WO-A12's owned-file list
did not include `src/config.py`, so the fix was assigned to a card that
could not make it, and the gap outlived two waves for a planning reason
rather than a design one. **WO-B4** folded all three in —
`LOG_CAPTURE_USER_CONTENT` as a `Settings` field with the conventional
variable as its alias, and `TRACE_SAMPLE_RATIO` as a bounded float. The
environment variables are unchanged; only out-of-range and
unparseable *values* behave differently, and they now refuse rather
than clamp.

1. **The `job_failed` and `job_cancelled` SSE frames still have two
   shapes.** WO-A10 reconciled the two `job_completed` frames onto one
   builder (`src/api/runner.py::terminal_event_data`) and the route's
   replay uses it for every terminal frame — but the runner's *live*
   failure and cancellation frames still build their own smaller
   payloads at eight call sites, because that work order owned only the
   `job_completed` one. A client reading a live `job_failed` still gets
   `{job_id, error, error_type, elapsed_sec}` where the replay gives it
   eleven fields. Same defect, same fix, one call site at a time.
2. **`src/api/redriver.py` keeps its own copy of the terminal payload.**
   Its `_terminal_event_data` says it is "kept field-for-field in sync"
   with the route's and no longer is; it predates the shared builder and
   belongs to another work order. Merging it is a three-line change
   whenever that file is next opened.
3. **A schema standard is landing.** ISO/IEC FDIS 24970 (AI system
   logging) is at stage 50.20 and likely to become the reference for
   exactly the fields above. The field names are therefore constants in
   two places — the envelope block in `logging.py` and `CONTEXT_FIELDS`
   / `context_fields()` in `context.py` — rather than literals scattered
   through the formatter, so remapping is an edit rather than a hunt.
4. **Metrics exist only inside API workers.** `configure_metrics()`
   has one caller — the API lifespan — so `make run` and `make eval`
   install no meter provider and every record helper returns on its
   `None` check. Deliberate for the server-shaped instruments;
   widening it was out of scope for ADR 0066.
5. **No `invoke_workflow` span on the CLI or eval paths.** The span is
   opened by `run_job`, so those entry points produce node spans with
   no workflow parent.
6. **The redriver records `kind="unknown"`** on both of its terminal
   outcomes — a failed orphan and, since ADR 0068, a dead-lettered
   job. It has `job.kind` in hand but does not pass it;
   `src/api/redriver.py` belonged to another work order. A test pins
   the current value so the fix is visible when it lands.
7. **The GenAI conventions are pre-stable and will churn.** They have
   left the core semantic-conventions repository and their new home has
   no tagged release, so ADR 0066 pins a commit SHA. Every `gen_ai.*`
   name is a constant in `src/observability/semconv.py` — one file to
   re-read against a newer commit.
