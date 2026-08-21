# 0047. Run graph nodes on a bounded executor and cancel them cooperatively

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: project owner

## Context

`run_job` wraps the workflow in
`asyncio.wait_for(..., timeout=api_job_timeout_sec)`. That was the
whole of the timeout story, and it was half a story.

Every node in this graph is a *synchronous* function — `planner_agent`,
`reader_agent` and friends take state and return state, with blocking
Anthropic calls and PyMuPDF parsing inside. On the async path
(ADR 0040) LangGraph coerces such a callable in
`langgraph/_internal/_runnable.py::coerce_to_runnable`:

```python
return RunnableCallable(
    thing,
    wraps(thing)(partial(run_in_executor, None, thing)),
    ...
)
```

That `None` is the event loop's **default** `ThreadPoolExecutor`.
Cancelling the coroutine that awaits it — which is all `wait_for` can
do — cancels the `asyncio` future. The `concurrent.futures.Future`
underneath is cancelled only if it has not started; a node already
running keeps running. Threads cannot be killed from outside in
CPython.

Three consequences, all live in the shipped configuration:

1. **`api_max_concurrent_jobs` stopped bounding real concurrency.**
   The permit was released the moment `wait_for` raised, while the
   zombie thread kept a slot in a pool the semaphore never sized. Under
   a run of slow jobs the worker's thread count and its LLM
   concurrency climb past the ceiling the operator configured.
2. **Spend continued past the failure.** The job was already `failed`
   with `error_type=timeout`; the reader's per-paper fan-out kept
   issuing Claude calls against `ANTHROPIC_API_KEY`, unattributable to
   any live job and uncapped by `max_cost_usd` (whose enforcement point
   is the runner's between-nodes callback, which no longer runs).
3. **The process could not exit cleanly.** `ThreadPoolExecutor`
   threads are non-daemon; the interpreter joins them at exit. A node
   blocked on a 120s Anthropic timeout held SIGTERM open with nothing
   in the lifespan waiting on it or even able to see it.

The audit rated a partial fix worse than none: releasing the permit
while the thread runs "fakes the property" — the number on `/healthz`
looks right and means nothing.

## Decision

Three pieces, all of them in the API's own layer:

**1. A dedicated, bounded node pool.** `create_app`'s lifespan builds
`ThreadPoolExecutor(max_workers=api_max_concurrent_jobs,
thread_name_prefix="graph-node")`, stores it on `app.state`, and passes
it to `build_workflow(async_checkpointer=True, node_executor=...)`. On
lifespan exit — after the in-flight jobs have been cancelled and
drained — it calls `shutdown(wait=False, cancel_futures=True)` to drop
queued work, then joins with `asyncio.wait_for(asyncio.to_thread(
shutdown, wait=True), timeout=api_job_drain_timeout_sec)`.

Since LangGraph offers no supported hook for injecting an executor on
the async path (see the alternatives below), the graph builder
registers each node as an **async** callable that performs the
dispatch itself:

```python
async def node(state):
    token = current_cancel_token()
    if token is not None:
        token.raise_if_cancelled()
    ctx = copy_context()
    return await asyncio.get_running_loop().run_in_executor(
        executor, ctx.run, _run_node_body, name, traced, state, token
    )
```

LangGraph natively supports async node functions, so this is a
supported registration, not a monkeypatch. The explicit `copy_context`
is load-bearing: `run_in_executor` propagates contextvars only on its
default-executor branch, and `run_id`, the cost accumulator and the
cancel token all have to reach the node thread. The sync build (CLI,
eval runner, which drive `invoke`) keeps registering plain callables —
`RunnableCallable` with no sync surface would raise there — and
`build_workflow` rejects `node_executor` without `async_checkpointer`
rather than ignoring it.

**2. Cooperative cancellation.** New leaf module `src/cancellation.py`:
a `CancelToken` (a `threading.Event` plus the registry of node threads
currently executing for that job) bound to a `ContextVar`, exactly the
shape `_current_costs` uses in `src.observability.costs`. `run_job`
creates one per job. The checks:

- `src/llm.py::call_llm` calls `check_cancelled()` before
  `_get_client()`. This is the one funnel every agent's spend goes
  through, so it is the checkpoint that actually stops the bill.
- `reader_agent`'s per-paper fan-out checks between papers, *outside*
  the ADR-0041 degradation guard, and re-raises `JobCancelledError`
  rather than degrading a paper that was never attempted.
- `propagate_run_context` carries the token into fan-out worker
  threads alongside `run_id` and the accumulator.

On timeout, `run_job` sets the token, writes the terminal state and
emits the terminal SSE frame (so the client is released immediately),
and *then* — still inside `async with semaphore` — drains: it waits
for the registered node threads to actually return, bounded by
`api_job_drain_timeout_sec`.

The shutdown (`CancelledError`) path drains too, but under a separate
ceiling, `runner.SHUTDOWN_DRAIN_SEC` (5s), which also caps the
lifespan's pool join. On timeout the permit is what we are protecting
and patience pays; at SIGTERM the wait competes with uvicorn's own
graceful drain inside the container's `stop_grace_period`, and a node
already inside an Anthropic request would not return within 30s
either. Compose's grace period moves 15s → 30s to stay above the
whole chain (uvicorn 10s + job drains + pool join).

**3. Honest accounting when the drain gives up.** If the budget
expires, `CancelToken.abandon()` moves the still-running threads into a
process-wide count, the runner logs
`api_job_node_drain_expired` (WARNING, naming the nodes and the job),
and only then does the permit go back. `/healthz` adds that count to
`active_jobs` and breaks it out as `abandoned_node_threads`, so the
worker never advertises capacity it does not have — ADR 0042's honesty
rule applied to the one number ADR 0042 left optimistic. The count
decrements when each thread finally returns.

**Config.** One new field: `api_job_drain_timeout_sec` (default 30,
1–300). Sizing reuses `api_max_concurrent_jobs`.

## Alternatives considered

- **Pass an executor to LangGraph through `config`** — the obvious
  first choice, and the one this ADR would have preferred.
  `langchain_core.runnables.config.run_in_executor` *does* accept an
  executor, but LangGraph's `coerce_to_runnable` binds it as
  `partial(run_in_executor, None, thing)` at graph-build time. The
  `None` is not read from the `RunnableConfig`, and there is no
  `configurable` key that reaches it. Verified against
  langgraph 1.2.7 / langchain-core 1.4.8. Rejected: not available.
- **Monkeypatch `coerce_to_runnable` / reach into
  `RunnableCallable.afunc`** — would give executor injection without
  changing our node registration, at the price of depending on a
  private call path that has already moved once (`langgraph.utils.
  runnable` is now a back-compat shim over `langgraph._internal.
  _runnable`). Rejected: a silent break on a patch release, in the code
  path that runs every node.
- **Make the agents `async def`** — the structurally cleanest answer:
  no thread pool, no cooperative token, real cancellation. It means
  rewriting seven agents plus the Anthropic client usage onto
  `AsyncAnthropic`, and the CLI + eval runner drive the same agents
  through the sync `invoke`, so both surfaces would have to move
  together. Rejected for this change as far too large; recorded as the
  long-term direction.
- **Release the permit and simply log the zombie** — the "partial fix"
  the audit pre-emptively rejected. `api_max_concurrent_jobs` would
  keep a number that no longer describes the process. Rejected.
- **Hold the permit indefinitely until the thread returns** — honest,
  but one node ignoring its token permanently removes a slot, and the
  same wait sits on the SIGTERM path. Rejected in favour of a bounded
  drain plus visible zombie accounting.
- **Wait on the `concurrent.futures.Future`s instead of polling a
  registry** — the futures are created inside Pregel's loop and are not
  reachable from the runner, and the fallback (no injected executor)
  path has no future at all. The registry is populated by the node
  thread itself, so it measures exactly "the thread is still running".
  The 20ms poll only ever runs on the timeout / shutdown path.
- **`daemon=True` node threads** — would let the process exit, but
  daemon threads are killed mid-write at interpreter shutdown and
  `ThreadPoolExecutor` does not expose the option anyway. Rejected.

## Consequences

- **Positive**: `api_max_concurrent_jobs` bounds threads and LLM
  concurrency again, not just coroutines. A timed-out job stops
  spending at its next LLM call instead of running to completion
  uncharged. The process has a bounded, joined pool to shut down.
  `/healthz` reports a concurrency figure the worker can back up, and
  names the zombies when it cannot.
- **Negative**: nodes on the async path are now async wrappers, so the
  sync and async builds no longer register identical callables — a
  compiled async graph cannot be driven by `invoke` (it never was).
  Cancellation is cooperative, so a node between checkpoints still runs
  to its next check; a single Anthropic call can take up to
  `anthropic_timeout_sec` to reach one. `api_job_drain_timeout_sec`
  becomes a shutdown-latency knob that has to stay under the
  orchestrator's SIGTERM grace period. The token adds a `ContextVar`
  read to every LLM call (negligible) and one more thing that must be
  propagated across every thread boundary we introduce.
- **Follow-ups**: async agents + `AsyncAnthropic`, which would replace
  the cooperative token with real cancellation; a cancel check inside
  the synthesizer's and verifier's own loops (today they abort at their
  next `call_llm`, which is usually the same thing); exposing
  `abandoned_node_threads` as a metric rather than only a health field
  and a log line; a `POST /research/{id}/cancel` endpoint, which now has
  the machinery it needs.
