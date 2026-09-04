# 0067. One correlation context, and a log line that is bounded by contract

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: maintainer
- **Depends on**: ADR
  [0012](0012-observability-core-logging-costs.md),
  [0042](0042-api-guardrails-and-deploy-hygiene.md),
  [0049](0049-otel-metrics.md)

## Context

The logging layer had exactly one ContextVar — `_run_id`, default
`"-"` — and nothing else. No request id, no trace id, no span id, no
principal, no worker id, no service name, no version. Grouping by
`run_id` answers *what did this one run do*. It cannot answer *which
requests did that key make*, *which worker is stuck*, or *show me the
trace behind this error*, and the last of those is not a nice-to-have:
ADR 0013's spans and ADR 0049's metrics both exist, and nothing joins a
log line to either.

At the same time the formatter was maximally permissive in the other
direction. `JsonFormatter` copied **every** non-standard `LogRecord`
attribute into the payload verbatim, with no allowlist and no size cap.
Two call sites show what that bought:

- `routes.py` logged the raw user query on every submission.
- `runner.py`, on a terminal-persist failure, logged the **whole report
  body** — deliberately, so a lost success write would be recoverable
  from the log.

Both are reasonable local decisions and both put user text into an
indexed store with the retention of an error code. Redaction was one
rule — `redact_url` — with exactly one call site, covering connection
strings and nothing else: not API keys, not prompts, not learner text,
not paper content.

Three things force the decision now rather than later. WO-A07 needs a
context to hang span attributes on; WO-A10 needs one to bind at the
HTTP edge; and every field added to a log payload before the contract
exists is a field that has to be migrated after.

## Decision

### One context, in `src/observability/context.py`

A frozen `RequestContext` dataclass in one ContextVar, carrying
`run_id`, `job_id`, `request_id`, `job_kind`, `principal_hash` and
`worker_id`, plus `service` and `version` resolved once at import from
`settings.otel_service_name` and `importlib.metadata`.

Frozen because a context a fan-out worker can mutate is a context that
leaks across jobs: every change makes a new instance and a new `Token`,
which is what makes `reset` honest. `bind_context` **merges** rather
than replaces, because the edge, the runner and the graph each bind
different fields at different depths of one call stack and a replacing
setter would let the innermost silently erase the principal.
`clear_context` is the deliberate way to unset.

`bind_run_id` / `current_run_id` / `reset_run_id` keep working
unchanged; they are now a view onto the context's `run_id`, and
`run_id` keeps its `"-"` sentinel because consumers read it as format,
not as an implementation detail.

`propagate_run_context` is **extended, not replaced** — its signature
is unchanged, because the runner's thread pools call it and belong to
another work order. It now snapshots the whole context instead of one
string, which is what makes a reader thread's LLM call attributable to
the request and principal that paid for it.

### `principal_hash`, never the key id

`hash_principal(key_id)` returns a 12-character salted SHA-256 digest.
ADR 0049 already refused to label metrics by `key_id` — unbounded
operator-supplied cardinality, and the credential's own identity. A log
field that undid that would be strictly worse: a metric label lives
until the next scrape, a log field lives for the retention window.

Salted, from `LOG_PRINCIPAL_SALT`, because key ids are short
operator-chosen strings and a bare digest of one is recoverable from a
word list. Unset, each process generates its own salt at import: within
a process grouping still works, across the fleet it does not, and
`principal_salt_is_ephemeral()` says which you have. That is a weaker
default than a configured salt and a much stronger one than no salt.

### The log contract, in `src/observability/logging.py`

Four rules, all enforced by the formatter and all covered by
`tests/test_log_contract.py`:

1. **Context fields on every line**, plus `trace_id` / `span_id` read
   from the active OTel span when there is one. The API only — this
   module creates no spans, because a logger that started spans would
   be a logger that changed sampling decisions. WO-A07 owns tracing.
2. **A closed event-name set.** `KNOWN_EVENTS` holds the 190 names
   `src/` emits today; the test re-parses the source and fails on any
   name that skipped registration, naming file and line. A record from
   a `src.*` logger whose message is unregistered is flagged
   `unregistered_event` on the line itself, so a violation is visible
   in production and not only in CI.
3. **An allowlist and a size cap for `extra`.** 197 registered keys;
   anything else is dropped, named in `dropped_extra_keys`, and counted
   process-wide. Strings cap at 2 KiB with a truncation marker,
   containers clip at 50 items per level and 3 levels deep, `bytes` are
   reported by size and never decoded. A caller may *fill* an unbound
   context field from `extra` — which is how today's `job_id` and
   `worker_id` call sites keep working — but never *overwrite* a bound
   one, or any call site could attribute its line to another principal.
4. **Redaction by default.** User-content keys are elided to
   `[redacted: N chars]`, and every surviving string — message, `extra`
   value and formatted traceback — is scrubbed for URL userinfo, bearer
   tokens, `sk-` keys, email addresses and long base64-ish blobs.

The traceback is the one that matters most. The leak ADR 0042 fixed was
not a call site logging a password on purpose; it was a connection
error whose *message* carried the URL, and the stack trace that
repeated it. `redact_url` survives unchanged for callers that know they
hold a URL: it parses where the new rules match, and returns `***` for
input it cannot parse rather than passing an unproven string through.

### Content capture follows the GenAI convention

The opt-in flag is
**`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`** — the only
opt-in environment variable the OpenTelemetry GenAI conventions define
— with `LOG_CAPTURE_USER_CONTENT` as a narrower repo-local alias that
scopes the decision to logs alone. Either being truthy enables capture.

The convention's guidance is stronger than "off by default" and is
worth quoting, because it sanctions the design rather than merely
permitting it. Instrumentations "SHOULD NOT capture [message content]
by default, but SHOULD provide an option for users to opt in", and the
spec names three patterns: (a) do not record content, (b) record it on
span attributes — explicitly a pre-production pattern, and (c) store it
externally and record only references, the production pattern. What
this ADR implements is (a), with a size reference retained, and a
documented path to (c) when there is somewhere external to put it.

Note that the per-message events some older instrumentation emits
(`gen_ai.user.message`, `gen_ai.choice`) have been **removed** from the
conventions in favour of opt-in span attributes plus a single
`gen_ai.client.inference.operation.details` event. Nothing here is
modelled on those names.

The flag is read from the environment rather than from `Settings`
because `src/config.py` belongs to another work order this wave. WO-A12
folds both names in, keeping them as the pydantic-settings aliases so
no deployment has to change.

### Field names are constants, in two places

ISO/IEC FDIS 24970 — the AI-system-logging standard — is at stage 50.20
and publishes shortly. It is likely to become the reference schema for
exactly the fields defined here. So the envelope names live in a named
block in `logging.py` and the correlation names in `CONTEXT_FIELDS` /
`context_fields()` in `context.py`, rather than as literals inside the
formatter: remapping to a published schema should be an edit to two
blocks, not a search through a function.

## Alternatives considered

- **Keep `run_id` and add more ContextVars.** One per field is
  simplest to write and worst to maintain: `propagate_run_context`
  grows a line per field, every one is a place to forget a `reset`, and
  nothing guarantees they are consistent with each other. One frozen
  record is one snapshot, one token, one reset.
- **A mutable context object.** Cheaper binds, and a fan-out worker
  mutating a shared context is a cross-job leak with no stack trace.
  Rejected on the strength of exactly that failure mode.
- **Log the key id and rely on access control on the log store.**
  Rejected. Access control on a log store is a policy that changes;
  a hash is a property that does not. And the metrics layer had already
  made the opposite call, so this would have left two answers to one
  question.
- **A denylist for `extra` instead of an allowlist.** Cheaper to adopt
  — nothing breaks on day one — and it fails open. The field that leaks
  is by definition the one nobody thought to deny. The allowlist's cost
  is a registry edit per new field; that cost is the feature.
- **Truncate the whole payload rather than per value.** One cap is
  simpler, but it makes which field survives depend on dict ordering,
  so the same event truncates differently run to run. Per-value bounds
  are predictable.
- **Redact by inspecting values rather than by key name.** A heuristic
  that guesses whether a string is user content is a heuristic that
  will be wrong on the day it matters, in both directions. Key
  membership is explicit and auditable.
- **Enforce the event-name set at runtime by dropping unknown events.**
  Rejected outright: losing a log line because its name was not
  registered is a worse failure than the one being prevented. The
  runtime signal is a flag on the line; the enforcement is a test.

## Consequences

- **Positive**:
  - A log line is joinable — to the request, the job, the worker, the
    principal and, when a span is live, the trace. Log-to-trace
    navigation and exemplars become possible for WO-A07 without further
    changes here.
  - Raw user queries and report bodies stop reaching the log stream.
  - Every log payload is bounded: the worst case per field is 2 KiB
    plus a marker, rather than however large the value happened to be.
  - Adding a log line now costs a registry edit, and the test says
    exactly which file and line is unregistered.
  - Credentials are scrubbed from tracebacks, which is where they
    actually appeared.

- **Negative**:
  - A field not on the allowlist is silently absent from the payload —
    "silently" only in the sense that the drop is reported in
    `dropped_extra_keys` rather than raising. A developer who does not
    read the line will think their `extra` did nothing.
  - The registries are long (190 names, 197 keys) and are a merge
    conflict surface for any wave that adds log lines in parallel.
    Sorted single-item-per-line to keep conflicts textual and trivial.
  - **A failed terminal write no longer leaves the report body in the
    log.** That was a deliberate recovery path (`runner.py`), and it is
    gone unless content capture is enabled. The trade is stated rather
    than hidden: exposure on every failure outweighs recoverability on
    a rare one, and the size is still logged.
  - Keys reaching `extra=` through a `**` splat are invisible to the
    static test and are registered by hand. The comment beside them
    says where they come from; a future splat of an unregistered dict
    will be caught at runtime by the drop report, not by CI.
  - `logging._run_id` survived as a deprecated compatibility view,
    because `tests/test_observability.py`'s teardown fixture reset it
    directly and that file belonged to no work order that wave.
    **Removed by ADR 0066**, which owned that test file: both teardown
    fixtures now call `clear_context()`, which is strictly better for a
    teardown — it resets the whole context rather than the one field
    the old name could see. There is one ContextVar and one name for it
    again.

- **Follow-ups**:
  - **WO-A10** binds the context at the HTTP edge (`request_id`,
    `principal_hash`) and in the runner (`job_id`, `job_kind`,
    `worker_id`). Until then those fields exist and are unbound in live
    lines — the contract lands before the fillers on purpose.
  - **WO-A10** also owns uvicorn's `log_config=None` (`serve.py:37`),
    which leaves access lines as unparsed text alongside the JSON
    stream. Explicitly not fixed here.
  - **WO-A12** moves the content-capture flag and `LOG_PRINCIPAL_SALT`
    into `Settings`. ADR 0066 adds `TRACE_SAMPLE_RATIO` to that list,
    read the same way and for the same reason.
  - **WO-A07** reuses `context_fields()` for span attributes so the log
    payload and the span cannot drift. **Done in ADR 0066**:
    `tracing._set_correlation_attributes` copies the context onto every
    node span, minus `service` / `version`, which the tracer's
    `Resource` already carries. Trace-to-log navigation now works in
    both directions.
  - `src/api/admin_migrate.py` logs `owner` — a principal identifier —
    verbatim. It should carry `principal_hash` instead.
  - ~~Delete `logging._run_id` when something next touches
    `tests/test_observability.py`.~~ Done in ADR 0066.
