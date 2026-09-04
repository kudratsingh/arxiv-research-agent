# Observability — the log contract

Every line this service writes is one JSON object on stderr. This page
is the contract that object obeys: which fields are always there, which
`extra=` fields are allowed, what is redacted, and what you have to do
to add an event or a field.

The design decision behind it is
[ADR 0067](decisions/0067-correlation-context-and-log-contract.md);
the original logging core is
[ADR 0012](decisions/0012-observability-core-logging-costs.md).

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
2. **The content-capture flag is not in `Settings`.** It is read from
   the environment by `content_capture_enabled()`. WO-A12 folds both
   names into `Settings`, at which point the env vars stay as the
   pydantic-settings aliases.
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
