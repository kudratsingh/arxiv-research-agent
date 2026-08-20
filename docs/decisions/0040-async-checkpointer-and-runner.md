# 0040. Async checkpointer surface for the API runner

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: kudratsingh
- **Revisits**: [ADR 0034](0034-postgres-checkpointer-and-cross-worker-hitl.md)
  (checkpointer choice), [ADR 0030](0030-hitl-plan-review.md)
  (interrupt semantics)

## Context

The audit proved the HTTP research path had never executed a single
node. Three independent P0s, one shared shape: everything the API
tests stubbed, and only what they stubbed, was broken.

**P0-1 — sync savers under an async runner.** `run_job` drives the
compiled graph with `app.astream(...)`, whose Pregel loop awaits
`checkpointer.aget_tuple()` before the first node runs. But
`build_workflow()` only ever compiled with the synchronous
`SqliteSaver` (the shipped default) or `PostgresSaver` (what
docker-compose sets), and both inherit an async surface that raises
`NotImplementedError`. Every API job died instantly in **both**
shipped configurations. The CLI and eval runner never noticed —
they call the sync `app.invoke`, which the sync savers serve fine.

ADR 0034 explicitly rejected `AsyncPostgresSaver` on the premise
that "the workflow is sync end-to-end" and the runner drives it
"via `asyncio.to_thread`". That premise was factually wrong: the
runner's streaming path was `astream` all along. This ADR reverses
that rejection on corrected facts.

**P0-2 — HITL review 500 under Redis.** `RedisJobStore._job_to_json`
built its payload with `dataclasses.asdict(job)`, which deep-copies
every field *before* the persistent-field filter discards the
non-serializable ones. While the runner is parked in
`await job.resume_event.wait()`, the Event's waiter deque holds a
live `_asyncio.Future`; `copy.deepcopy` raises `TypeError: cannot
pickle '_asyncio.Future' object`. The review endpoint calls
`store.update` on exactly that object, so every review during a
pause returned 500 and left the job wedged.

**P0-3 — the container never booted.** The Dockerfile CMD passed
`--log-config /dev/null`; uvicorn treats any non-`.json`/`.yaml`
path as a stdlib `fileConfig` ini and raises `RuntimeError` on the
empty file before binding a socket. `src/api/serve.py` expresses
the same intent correctly as `log_config=None` — the CLI-flag
translation was simply wrong, and the observability layer already
configures the root logger.

Under those P0s the audit found runner-level correctness bugs in
the same lines, latent only because no job ever got far enough to
hit them:

- **Double execution.** The trailing
  `app.invoke(None if interrupted else initial_state)` re-ran the
  whole graph from START whenever the workflow had not interrupted
  (i.e. `ENABLE_HITL=false` or bypass): passing a non-None input on
  an existing thread is a fresh run, not a state read. Every LLM
  call doubled, invisibly, because the second run produces the same
  answer.
- **Multi-pause truncation.** ADR 0030 claims `interrupt_after=
  ["planner"]` "fires after the **first** planner invocation only".
  That is not how LangGraph works: the interrupt re-arms on *every*
  execution of the named node, so a critic-driven re-plan parks the
  graph at a second interrupt. The single-pause runner returned the
  interrupt snapshot as the final state and marked the rejected
  draft `succeeded`, leaving the thread parked in the checkpointer
  forever.
- **Fragile terminal writes.** The success-path `store.update` sat
  outside the error-containment `try`, so a Redis blip on the last
  write lost the finished report and violated `run_job`'s "never
  raises" contract; the prior-context retrieval sat *before* the
  `try`, so a conversation-store or embedding-model failure wedged
  the job in `running` with its SSE clients hanging.
- **`_local` never evicted.** `RedisJobStore` kept every job it ever
  handled — full report, a 1024-slot Queue, an Event — in a
  process-lifetime dict that also shadowed the retention TTL on the
  originating worker. Relatedly, `evict_older_than` had no
  production caller at all, so the in-memory store's documented
  retention never ran either.

## Decision

**One flag, two surfaces.** `build_workflow(async_checkpointer=
False)` keeps today's sync savers and sync return value — the CLI
(`src/main.py`) and the eval runner are byte-for-byte unaffected,
and the existing sync dispatch tests pin that. With
`async_checkpointer=True` the function returns an *awaitable* of
the compiled graph (opening the async savers requires a running
loop), built on:

- `sqlite` → `AsyncSqliteSaver` over `aiosqlite` (new declared
  dependency; it was already installed transitively).
- `postgres` → `AsyncPostgresSaver` constructed against a
  `psycopg_pool.AsyncConnectionPool` with
  `check=check_connection`, explicit `connect_timeout`, and the
  connection kwargs the saver requires (`autocommit`, `dict_row`,
  `prepare_threshold=0`). The pool closes ADR 0034's own follow-up:
  the sync path's `from_conn_string` pinned the whole process to
  one un-pooled `psycopg.Connection` that never reconnects, so a
  Postgres restart wedged every worker permanently. The pool checks
  out a connection per checkpoint operation and replaces dead ones.

Teardown is an `AsyncExitStack` attached to the compiled app
(`_checkpointer_aexit_stack`); the `create_app` lifespan awaits the
factory result when it is awaitable and awaits the stack's
`aclose()` at shutdown. Injected test factories remain plain
callables.

**The runner goes properly async**: `aget_state` / `aupdate_state`
replace the `to_thread(get_state)` / `to_thread(update_state)`
bridges, and the trailing `invoke` is deleted entirely — the final
state is read from the checkpoint's settled values
(`aget_state(config).values`), which executes nothing. When
checkpointing is disabled the runner folds the streamed node
updates together instead, so every settings combination now
completes instead of raising.

**Resume is a bounded loop.** After each stream pass the runner
checks `aget_state(config).next`; the first pause runs the ADR 0030
review protocol (`plan_ready`, `pending_review`, resume wait), and
every subsequent pause auto-resumes with a `None` input and no
review — preserving ADR 0030's one-review-per-query *intent* while
correcting its false claim about `interrupt_after` semantics. The
loop is bounded at `settings.max_iterations + 2`; the critic
force-approves at `max_iterations`, so exceeding the bound means
the graph and runner disagree structurally and the job fails
loudly rather than shipping a truncated draft.

**Terminal writes are absorbed, contained, and attributable.**
Every terminal `store.update` routes through a retrying
`_persist_terminal` helper that logs `api_job_terminal_persist_
failed` (with the full result, so a lost success write is
recoverable from logs) instead of raising; the containment `try`
now opens before the `running` persist so the prior-context block
and the `job_started` publish are inside it (a prior-context
failure additionally degrades to a context-free run rather than
failing the job); `reset_run_id` moved to a `finally` after the
terminal emission so outcome records carry the run_id; SSE publish
failures are logged (terminal frames retried, then ERROR) instead
of suppressed; and the conversation-append failure on the success
path is logged instead of swallowed.

**Redis store hygiene.** `_job_to_json` builds its payload with
per-field `getattr` over `_persistent_fields()` — no `asdict`, no
deep copy, no P0-2. `_job_from_json` derives its accepted keys from
the same `_persistent_fields()` so the read path is structurally
symmetric with the write path and tolerates unknown keys. `update()`
drops the `_local` entry once the job is terminal (pub/sub owns
delivery past that point per ADR 0035) and refuses a terminal →
different-terminal overwrite (first terminal write wins — a
redriver's `failed/orphaned` cannot be silently resurrected as
`succeeded` after clients saw the terminal frame); `get()` serves
`_local` only for live jobs and drops stale entries when Redis says
the row is gone, making the retention TTL and operator deletes
authoritative everywhere.

**Retention sweep.** The lifespan runs a five-minute
`evict_older_than` sweep task — duck-typed like the other store
capabilities: skipped for stores advertising `scan_jobs` (the
ADR 0038 marker for backend-managed retention; Redis expires rows
via key TTL), cancelled at shutdown like the keystore reloader.

**Dockerfile CMD** drops `--log-config /dev/null`.

**The test that would have caught all of it**:
`tests/test_api_smoke_e2e.py` boots `create_app()` with **no
injected factory or store** — the production wiring — and drives
one job over HTTP through the real graph, the real
`AsyncSqliteSaver` at a tmp path, and the real runner, with only
the network seams canned (per-agent `call_llm_json`, PDF fetch,
embedding ranking). Verified failing on the pre-fix base with the
exact audited `NotImplementedError`. The HITL stub suite now pins
the async surface itself (sync `invoke`/`get_state` raise on
touch), the no-double-run guarantee, and the multi-pause loop; the
old permanent `SimpleNamespace` settings swap is replaced with
monkeypatched real `Settings` copies, and the defensive `getattr`
shims it forced into the runner are deleted.

## Alternatives considered

- **Sync all the way** — replace `astream` with `stream` under
  `asyncio.to_thread` and keep the sync savers. Rejected: every
  event and HITL hand-off would cross a thread boundary; the
  cross-worker resume (`watch_for_remote_resume`) and pub/sub
  fan-out are asyncio-native; and the async savers are the
  supported LangGraph surface for exactly this shape. ADR 0034's
  contrary rejection rested on the false premise that the runner
  was sync.
- **One async surface for every caller** (CLI and eval switch to
  `ainvoke`). Rejected for this PR: it forces `asyncio.run`
  scaffolding into two entry points that are correct today, for no
  behavioral gain. The flag keeps the blast radius at the API
  boundary; the existing CLI-path tests prove the default is
  untouched.
- **`build_workflow` stays sync and blocks on a private loop** to
  open the async savers. Rejected: `create_app`'s lifespan already
  runs on the loop; spinning a second loop to open connections that
  must then live on the first is exactly the kind of cross-loop
  binding aiosqlite and psycopg_pool forbid.
- **Reviewing every pause** instead of auto-resuming later ones.
  Rejected: ADR 0030 deliberately chose one review per query; a
  re-plan pause mid-run with no client waiting would just hang
  until `api_hitl_timeout_sec`. Revisit if per-revision review
  becomes a product requirement.
- **A bounded LRU for `_local`** instead of terminal eviction.
  Rejected as primary fix: under ADR 0035 a terminal job has no
  remaining use for its local instance at all, so eviction is
  strictly correct; an LRU would only paper over a leak that no
  longer exists.

## Consequences

- **Positive**: the API research path works — in both shipped
  configurations, proven end-to-end by a test that boots the
  production wiring. LLM spend is halved on the no-review path
  (the double run is gone). A twice-re-planned job completes
  instead of shipping its rejected draft. A Postgres restart costs
  at most the in-flight jobs, not the process. HITL reviews under
  Redis work while the runner is paused. Worker memory is bounded
  by live jobs, not history.
- **Negative**: `build_workflow`'s return type is now mode-
  dependent (compiled app vs. awaitable) — documented, and typed
  `Any` either way, but a caller passing `async_checkpointer=True`
  must await. The terminal-transition guard adds one Redis GET per
  terminal write (read-then-write, not atomic — a true CAS is left
  to the redriver-side follow-up). The smoke test adds ~4s to the
  integration tier.
- **Follow-ups**: the job-timeout path still abandons the node
  thread (semaphore released while the thread runs on the default
  executor — the audit's P1 at runner.py:617); needs a dedicated
  bounded executor plus a cooperative cancel token in the agents,
  tracked separately. `ConversationStore.update_title` so
  auto-titling persists under Postgres. Correct ADR 0030's
  interrupt-semantics paragraph in place (this ADR is the record;
  the older text now carries a superseded claim).
