# 0051. Enforce the spend ceiling at the LLM call, and make retries visible

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: maintainer

## Context

A pre-flight audit of the paths about to spend real money — `make run`
for a single query and `make eval` for a campaign — turned up one
structural gap and a cluster of blind spots around it.

### `max_cost_usd` was enforced on exactly one path

ADR 0033 added a per-run dollar ceiling and put the check in the API
runner's `on_node` callback, between graph nodes. That is the right
place for the API, and it is the *only* place it exists:

- `src/main.py` and `src/eval/runner.py` both drive the compiled graph
  with a bare `app.invoke(...)` and install no `on_node` hook, so
  neither has any ceiling at all.
- `src/agents/supervisor.py` has an independent budget short-circuit,
  but `enable_supervisor` defaults `False`, so on the shipped
  configuration that check never runs.

Under shipped defaults the spend is structurally bounded (Sonnet,
`max_papers=10`, `max_iterations=3`, order $0.5–1.5 per query against a
$2.00 cap), which is why this was a design gap rather than an active
overspend. But `MAX_PAPERS` accepts up to 50 and `MAX_ITERATIONS` up to
10, giving 11 passes × 50 reader calls with nothing anywhere to catch a
typo — and the campaign is the highest-spend path in the repo.

The same audit found a second, narrower hole in the API's own check:
because it fires *between* nodes, one node can overshoot the cap by its
entire spend. The reader fans out up to `max_papers` parallel LLM calls
inside a single node (`ThreadPoolExecutor` in `_analyze_or_degrade`), so
at `MAX_PAPERS=50` on an Opus model the overshoot is not a rounding
error.

### Hitting the ceiling threw away the artifact it had paid for

`run_job`'s `except CostBudgetExceeded` handler set `status`, `error`,
`error_type`, `completed_at`, `cost_usd` and `llm_calls`, and never
touched `job.result`. So `GET /research/{id}` returned a bill with
nothing attached. The worst shape of this: a run whose *final* node
pushes total spend to the cap has a complete report, and
`route_after_critique` has already returned `END` — and it was failed
with the report discarded. The draft was demonstrably in hand at raise
time, because `_invoke_streaming` does `merged.update(state_update)`
immediately *before* awaiting `on_node`.

### SDK retries were invisible

`src/llm.py` had no log statements at all. The Anthropic SDK retries
429s, 529s, connection errors and client-side timeouts on our behalf,
and its only non-DEBUG line about that is
`anthropic._base_client`'s `"Retrying request to %s in %f seconds"` at
INFO — which ADR 0042's blanket demotion of the `anthropic` logger tree
to WARNING silenced. There was also no metric. A rate-limited fleet was
therefore indistinguishable from a merely slow one, and the magnitude
is not small: `_calculate_retry_timeout` honours a server `retry-after`
header up to 60s, so four throttled attempts can burn ~4 minutes of
silent sleep on top of the request time.

### One flaky call could eat a whole job

The SDK applies `timeout` **per attempt**, not per call chain:
`request()` loops `for retries_taken in range(max_retries + 1)` and
`_attempt_request` rebuilds the request — timeout and all — every time.
At the shipped defaults that is 5 attempts × 120s = 600s of request
time for one logical call, which is *exactly* `api_job_timeout_sec`.
One unlucky call could consume an entire job's budget and the job would
die with nothing to show. (Confirmed: `APITimeoutError` subclasses
`APIConnectionError`, which `_should_retry_exception` returns `True`
for, so client-side timeouts really are retried.)

### An unpriced model corrupts the ceiling, not just the report

`estimate_cost` falls back to Sonnet pricing for any model id missing
from `PRICES_USD_PER_MILLION`. Since ADR 0033 that number feeds
`max_cost_usd` enforcement, so an off-table model priced 3.3× low lets
a $2.00 cap pass ~$6.60 of real spend. The coverage test meant to
prevent this was vacuous: it collected model ids from
`field.default`, and every per-agent routing field defaults to `""`, so
it only ever examined the single `anthropic_model` literal. A
deployment that sets `ANTHROPIC_MODEL` or any `*_MODEL` override to an
off-table id passed it untouched.

### stderr was not parseable, and a native crash was silent

"Logs sink to stderr" is only useful if stderr is machine-readable. A
measured full-workflow run emitted 22 JSON lines and 34 non-JSON ones —
tqdm bars and ML-stack INFO chatter — with one JSON record *physically
split* by an interleaved progress bar, i.e. records lost to a parser
rather than merely surrounded by noise. Separately, an audit reproduced
a SIGSEGV inside MiniLM's pooling forward pass under the reader's
thread-pool fan-out (~1 run in 25 under process-level concurrency); with
no `faulthandler` anywhere in the repo, the process died with exit 139
and zero Python output.

## Decision

### 1. The ceiling moves to the choke point every entry point shares

`src.llm.call_llm` checks the run's accumulated spend against
`settings.max_cost_usd` **before** issuing a call, and raises the
existing `CostBudgetExceeded`.

`CostBudgetExceeded` and `_enforce_cost_cap` move from
`src/api/runner.py` to `src/observability/costs.py`, next to the
accumulator they are raised against, so the LLM layer can raise the
exception the runner catches without importing the API layer. Both are
re-bound in `src/api/runner.py` under the names they have always had —
`CostBudgetExceeded` is part of the runner's public surface — and
`CostBudgetExceeded` is additionally exported from
`src.observability` so CLI and eval callers have a first-class import.

Three properties make this safe to put on the hottest path in the repo:

- **No accumulator, no check.** `current_costs()` returning `None`
  means no run is being tracked (a unit test, an ad-hoc script) — there
  is nothing to measure against, so behaviour is unchanged, exactly the
  rule `record_llm_call` already follows.
- **Checked before, not after.** The point is to not spend the *next*
  dollar. The accumulator can only ever lag by calls still in flight.
- **Cancellation outranks the budget.** `check_cancelled()` stays
  first: an abandoned job's spend does not matter, and a timed-out job
  must report `timeout`, not a misleading `cost_budget_exceeded`.

The runner's between-nodes check **stays**. The two are not redundant
and they cannot double-fire into an inconsistent outcome: both raise
the same class from the same accumulator, so whichever fires first is
the one `run_job` handles. The per-call check is what bounds
*intra-node* overshoot; the `on_node` check still catches a node that
spent without going through `call_llm`. The supervisor's own
short-circuit remains the earlier, softer stop.

### 2. The ceiling no longer destroys the report

`_invoke_streaming` catches `CostBudgetExceeded`, attaches
`merged["draft_report"]` to the exception as `partial_report`, and
re-raises. `run_job`'s handler sets `job.result` from it. The job stays
`failed` with `error_type=cost_budget_exceeded` — the caller must know
the report is partial — but `GET /research/{id}` and the export routes
now return the artifact the money already bought. `""` normalises to
`None`, because a `JobDetail` carrying `result: ""` would tell a client
an empty report exists.

Reading `merged` rather than the checkpoint is deliberate: `merged` is
the frame's own state, needs no extra async round trip, and returns
something even with checkpointing disabled. It also covers the
raised-from-inside-a-node case, where `on_node` never runs at all.

The `api_job_cost_budget_exceeded` log line grows
`partial_report_chars`, because "did the spend buy anything" is the
first question asked about a capped job.

### 3. Retries are counted and logged, without a second retry loop

`call_llm` calls `client.messages.with_raw_response.create(...)` and
reads `raw.retries_taken` — the SDK's own count of attempts it
discarded before the one that returned — then hands it to
`record_llm_call` along with the measured `latency_ms`. **No
app-level retry loop is added**; the SDK's remains the only one, so the
count stays correct if `anthropic_max_retries` changes. `retries_taken`
is read as a typed attribute rather than through `getattr`, so an SDK
upgrade that removes it fails mypy instead of silently reporting zero
forever.

Three new signals fall out of that:

| Signal | Where |
|---|---|
| `llm_retries_total{model}` | counter, from `record_llm_call` |
| `llm_upstream_errors_total{model,status}` | counter, from `call_llm`'s handlers |
| `retries` + `latency_ms` on the `llm_call` log line | `record_llm_call` |

`call_llm` also catches `APIStatusError` and `APIConnectionError`
(which covers `APITimeoutError`), logs `llm_upstream_error` at WARNING
with model, status, `request_id` and elapsed ms, and **re-raises
unchanged**. By the time either escapes, the SDK has already burned
every attempt, so this is the only trace those attempts will ever
leave.

And `anthropic._base_client` is pulled back out of the blanket
demotion: it is held at `max(INFO, root.level)`, so its retry line
survives at `LOG_LEVEL=INFO` while `LOG_LEVEL=WARNING` still means
WARNING and every other `anthropic.*` logger stays quiet. ADR 0042's
`ANTHROPIC_LOG=debug` escape hatch is untouched.

### 4. The call chain is clamped to fit inside a job

`_retry_envelope()` derives the client's `max_retries` from
`api_job_timeout_sec × 0.75 ÷ anthropic_timeout_sec`. At the shipped
defaults that trims 4 retries to 2: 3 attempts × 120s = 360s of request
time, plus at most 2 × 60s of `retry-after` backoff = 480s worst case,
inside the 600s job timeout with room for the rest of the graph.

**Attempts are trimmed, never the timeout.** A shorter per-attempt
timeout would abandon slow-but-healthy generations, and that costs
money twice: Anthropic bills the abandoned attempt and no `usage` comes
back to record it. At least one attempt always survives, so an operator
who sets a timeout larger than the whole budget gets one long call
rather than a refusal. When the clamp actually bites, client
construction logs `llm_retry_budget_clamped` at WARNING with both
numbers — silently ignoring an explicit `ANTHROPIC_MAX_RETRIES` is the
kind of override that costs an afternoon to find.

This lives in `src/llm.py` rather than as a `model_validator` in
`src/config.py` because the two settings are individually valid; it is
their *product* against a third setting that is not, and deriving it at
client construction keeps a legal env combination from refusing to
boot.

### 5. Unpriced models warn once, and the coverage check reads runtime values

`estimate_cost`'s fallback warning is now **once per model id per
process**, guarded by a lock (the reader records from a thread pool).
Before this, an off-table model emitted one WARNING per LLM call —
hundreds in a run — which is how a line that matters got lost in the
lines that don't. The warning names the fallback and the file to edit,
because the action it asks for is "add a row", not "investigate".
`reset_unpriced_warnings()` is the test seam.

Two new helpers in `costs.py` make the coverage check real:

- `resolved_model_ids(config)` — the base model plus every non-empty
  `<agent>_model` override, derived from the model's own fields so a
  new agent's routing field is covered the day it is added.
- `unpriced_models(config)` — those ids minus the price table.

Both take a `Settings` **instance**, because the question worth asking
is "is *this* environment priced", not "are the import-time defaults
priced".

Missing rows added: `claude-fable-5` and `claude-mythos-5` at $10/$50,
`claude-opus-4-5` at $5/$25.

### 6. stderr stays parseable, and a native crash leaves a trace

`_configure_root_once` now also:

- demotes `sentence_transformers`, `transformers`, `huggingface_hub`
  and `faiss` to WARNING. `sentence_transformers` matters twice over:
  its progress-bar default is
  `logger.getEffectiveLevel() in (INFO, DEBUG)`, so demoting the logger
  turns the tqdm bars off at the library's own gate rather than by
  monkeypatching its call sites;
- `setdefault`s `HF_HUB_DISABLE_PROGRESS_BARS=1`,
  `TOKENIZERS_PARALLELISM=false` and `TRANSFORMERS_VERBOSITY=error`,
  because bars and fork warnings write straight to stderr and no logger
  level can reach them. `setdefault`, so an operator debugging a model
  load can still export their own value;
- arms `faulthandler`, so a SIGSEGV in torch / faiss / tokenizers
  prints every thread's stack instead of nothing. Best-effort:
  `enable()` needs a real file descriptor and does not always get one,
  so an unavailable handler is logged at DEBUG and shrugged off —
  crash diagnostics must never stop the app from configuring logging.

### 7. Lease diagnostics

Two P3s on the job-lease path, which is the liveness proof the redriver
reads before reclaiming a job:

- `job_lease_acquire_error` / `job_lease_refresh_error` now carry
  `exc_info`. The keeper's failures are timer-driven, so
  `_log_lease_failure` warns with a traceback on the first failure of a
  streak and drops to DEBUG with a running count for the repeats,
  resetting on the next success — a Redis outage otherwise produces one
  stack trace per job per refresh tick.
- The lease keeper binds its own `run_id`. `asyncio.create_task`
  snapshots the context at creation and `run_job` binds the run_id
  *after* `_job_lease.__aenter__` has spawned the task, so every keeper
  line formatted with the `-` default. `_job_lease` also binds it
  around its own acquire, then unwinds before yielding so `run_job`'s
  bind owns the scope.

## Alternatives considered

- **Add `--max-cost-usd` to the eval runner and leave `call_llm`
  alone** — fixes one of the three unenforced paths, leaves `make run`
  uncovered, and does nothing about intra-node overshoot on the API
  path. The per-call check covers all of it in one place. (The eval
  runner's *batch* budget, which is a different question — total
  campaign spend across queries — is ADR 0050's.)
- **A `model_validator` on `Settings` that rejects unpriced model ids
  at import** — attractive, and the audit recommended it. Rejected for
  now: it makes a new Anthropic model id a hard boot failure until
  someone edits the price table, which is the wrong failure mode for a
  service that should keep running while its cost reporting is stale.
  `unpriced_models()` gives an operator the same check to run
  deliberately; wiring it into startup as a WARNING is a follow-up.
- **`max_retries=0` on the client and retry in-repo** — gives true
  per-attempt visibility, since each attempt would be ours to log.
  Rejected: it replaces a well-tested SDK retry policy (`retry-after`
  parsing, `x-should-retry`, jittered exponential backoff, the
  `__cause__` walk for connection errors) with a hand-rolled one, for
  observability we can get by reading `retries_taken`. ADR 0009 chose
  SDK-native retries deliberately; this does not reverse that.
- **Lowering `anthropic_timeout_sec` instead of trimming attempts** —
  cheaper to implement, but abandons slow healthy generations and pays
  for them twice (see §4).
- **Changing `anthropic_max_retries`'s default in `src/config.py`** —
  the clean fix if the two settings were independent. They are not: the
  safe value depends on `anthropic_timeout_sec` and
  `api_job_timeout_sec`, so a static default is wrong for any operator
  who changes either.
- **Reading the checkpoint for the partial report instead of `merged`**
  — an extra async round trip for state the frame already holds, and it
  returns nothing at all with checkpointing disabled.
- **Passing `show_progress_bar=False` at the `model.encode` call site**
  — belt-and-braces, and it does not depend on a third-party gate. Left
  as an option for `src/tools/embeddings.py`, which is out of this
  change's scope; the logger demotion covers the same ground for every
  caller at once.

## Consequences

- **Positive**: every entry point — CLI, eval campaign, API job — now
  has a dollar ceiling, enforced at the one function they all funnel
  through, with per-call granularity instead of per-node. Money already
  spent yields its artifact instead of a bare error. A throttled fleet
  is visible as `llm_retries_total` climbing rather than as unexplained
  wall-clock. One flaky call can no longer consume a whole job. An
  off-table model warns once, legibly, and `unpriced_models()` answers
  the question for a whole environment. stderr is JSON lines again, and
  a native crash leaves a stack trace.
- **Negative**: `call_llm` takes on two responsibilities it did not
  have (a settings read and an accumulator read per call — both
  in-process, no I/O). `_retry_envelope` can silently override an
  operator's explicit `ANTHROPIC_MAX_RETRIES`; it warns, but it is
  still an override. `with_raw_response` couples us to a specific SDK
  response surface — mitigated by reading `retries_taken` as a typed
  attribute so an upgrade fails the type check. Holding
  `anthropic._base_client` at INFO adds one line per retried call to
  the stream, which is the point but is not free.
- **Known limits, stated honestly**:
  - **Retried attempts' spend is not capturable.** `usage` exists only
    on a 2xx body, so the tokens an abandoned attempt burned are
    reported by nobody — not by the SDK, not in `costs.as_dict()`, not
    on the job record. `retries_taken` is a *count*, and that is the
    ceiling of what is knowable in-process. The only way to reconcile
    it is Anthropic's own billing.
  - **The response carries no retry header.** The SDK sends
    `x-stainless-retry-count` on the request; nothing comes back. The
    parsed `Message` carries no retry information either, which is why
    the raw response is needed at all.
  - **Agents' degradation guards absorb the ceiling's exception.**
    `reader_agent` wraps each paper in `except Exception` and
    substitutes a placeholder, re-raising only `JobCancelledError`;
    `supervisor`, `verifier` and `query_refiner` have the same shape.
    So a `CostBudgetExceeded` raised from `call_llm` inside one of those
    nodes is caught and degraded, and when it hits every paper the reader
    raises `AllPaperAnalysesFailedError` instead — a capped sync run is
    reported as a reader failure, with one misleading
    `reader_paper_analysis_failed` WARNING per paper.

    The *brake* is unaffected and that is the part that matters: once the
    ceiling is crossed no further call is issued, which
    `test_reader_fanout_stops_spending_but_reshapes_the_error` pins
    directly (zero calls, spend unchanged). Only the label is wrong. The
    API path is effectively immune — `on_node` stops the run at the
    preceding node boundary, so the reader cannot *start* over the cap
    unless `max_papers` is 1 — but the sync revision loop
    (`critic -> planner -> ... -> reader`) can re-enter the reader with
    the accumulator already over, and it is the sync path this ADR set
    out to protect. Closing it means teaching the agents to re-raise
    `CostBudgetExceeded` alongside `JobCancelledError` — the same
    argument `reader.py` already makes for cancellation, "swallowing an
    abort would turn it into analyse-everything-anyway" — and
    `src/agents/*` was outside this change's file scope.
  - **The clamp always fires at the shipped defaults.** 4 retries x 120s
    exceeds 75% of the 600s job budget, so every process logs
    `llm_retry_budget_clamped` at WARNING once at client construction
    even when the operator set nothing. The line is accurate and carries
    the numbers, but a warning that is always present is a warning
    operators learn to skip; keying it to `model_fields_set` (warn only
    on an explicit `ANTHROPIC_MAX_RETRIES`) is the tidier shape.
  - **The clamp uses `api_job_timeout_sec` on every path**, including
    `make run` and `make eval`, which have no job timeout. It is a
    global bound on one call chain, which is a reasonable thing to want
    everywhere, but the number it is derived from is named for the API.
  - **`src/config.py`'s `max_cost_usd` description still says
    "Enforced by the API runner between graph nodes"**, and
    `docs/architecture.md:183` has the same narrowing. Both are now
    incomplete. Neither file was in this change's scope; correcting
    them is a follow-up.
  - **Two adjacent diagnostics gaps are untouched**, both outside this
    change's file scope: `src/api/redriver.py`'s
    `job_redriver_publish_failed` still logs without `exc_info`, and a
    corrupt Redis job row still disables `src/api/redis_store.py`'s
    terminal-transition guard silently.
  - **The SIGSEGV is only half-fixed.** `faulthandler` makes it
    diagnosable; it does not make it stop. The mitigation half —
    pinning `OMP_NUM_THREADS` / `torch.set_num_threads(1)`, or
    serialising encoding behind the existing model lock — belongs in
    `src/tools/embeddings.py` and needs a real soak (≥200 runs) before
    anyone believes a fix, since the reproduction rate is ~4%.
- **Follow-ups**: re-raise `CostBudgetExceeded` from the agents'
  degradation guards so a capped run is labelled as one; key the
  retry-clamp warning to `model_fields_set`; run
  `unpriced_models(settings)` at startup and WARN;
  widen `max_cost_usd`'s config description and
  `docs/architecture.md`; the embeddings thread-pinning half of the
  SIGSEGV; a `partial` flag on `JobDetail` so a client can tell a
  capped report from a complete one without reading `error_type`;
  streaming the synthesizer's 8192-token generation so a long
  completion cannot trip the HTTP timeout at all.

## Testing

Sixteen mutants planted and all sixteen caught: dropping the per-call
budget check, un-clamping the retry envelope, hard-coding `retries=0`,
skipping the upstream-error record, dropping the warn-once guard,
resolving models from field defaults instead of runtime values,
dropping the retries counter, re-closing the SDK retry logger, dropping
the ML-stack env defaults, discarding the partial report (both at the
handler and at the `_invoke_streaming` rescue), dropping either
run_id bind on the lease path, dropping the acquire `exc_info`,
warning unconditionally on lease failure, and never resetting the
failure streak.
