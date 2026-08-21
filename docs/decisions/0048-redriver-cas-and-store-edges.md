# 0048. Redriver compare-and-set, and the store edges around it

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: kudratsingh
- **Follows**: [ADR 0038](0038-job-redriver-and-sse-stream.md) (job
  redriver + SSE stream rewrite), [ADR 0040](0040-async-checkpointer-and-runner.md)
  (async checkpointer + runner correctness)

## Context

ADR 0038 and ADR 0040 each closed their headline bug and each left a
short list of recorded follow-ups in the code they touched. This ADR
finishes that list. The items are small individually; three of them
share one root, which is what makes them worth one decision record
rather than eight commits with no explanation.

**The shared root: a read and a write that are not one step.**

ADR 0038 reclaimed an orphaned job by claiming its lease with
`SET NX` and then writing `failed/orphaned`. The post-merge audit
narrowed that with a re-read under the claim — a job that finished
between the scan and the reconcile released its lease on the way out,
so the `SET NX` *succeeds* and the sweep would otherwise overwrite a
`succeeded` row, report and all. ADR 0040 added a second guard on the
other side: `RedisJobStore.update` refuses a terminal → *different*
terminal overwrite, so a runner finishing after a redriver cannot
resurrect the row as `succeeded`.

Neither guard closes the actual window, because both are GET-then-SET:

1. The sweep re-reads the row: `running`. It decides to reclaim.
2. The owning worker finishes and writes `succeeded`.
3. The sweep writes `failed/orphaned`. `update`'s guard reads the row,
   sees `succeeded` — a terminal status, but the *attempted* write is
   also terminal and different, so the guard fires… only because the
   owner happened to win the race. Reverse the order by a millisecond
   and the guard reads `running`, waves the write through, and the
   finished report is gone.

And the guard, when it *does* fire, was invisible to its caller. The
runner's terminal path is `_persist_terminal` followed by
`_put_terminal_event`; the refusal is logged inside the store and
`update` returns `None`, so the runner published its `job_completed`
regardless. A client could watch `job_completed` arrive after
`job_failed`, for a job whose stored outcome is `failed` and whose
result it will never be able to fetch.

**The rest**, from the same two audits:

- `_local` was popped after the terminal SET returned, so a Redis
  outage in which every terminal persist attempt failed left one entry
  per finished job — report, 1024-slot Queue, Event — for the process
  lifetime. Worker memory grew for exactly as long as the outage
  lasted (`redis_store.py:322`).
- `scan_jobs` MGET'd every job key and threw the terminal ones away a
  line later. In a healthy deployment nearly every row inside the
  retention window is terminal and carries a full report body, so each
  boot dragged the entire finished keyspace over the wire to discard
  it (`redis_store.py:619`).
- A worker killed mid-sweep held `redrive:lock` for its full 120s TTL,
  so its own restart hit `job_redriver_skipped_locked` and reconciled
  nothing (`redriver.py:204`).
- `ConversationStore` had no `update_title`, so the runner's first-job
  auto-title mutated a fetched `Conversation` object: a no-op against
  Postgres, where the row is detached. Every Postgres deployment kept
  the "New conversation" placeholder forever.
- The SSE deadline branch discarded a frame the read task had already
  produced. The window is real and narrow: the previous iteration's
  `wait` timed out, the loop yielded a keepalive, the drainer completed
  during that yield, and the deadline fired on resume. A client whose
  job ended microseconds before the hour got `stream_timeout` and was
  sent to reconnect to a job that was already over
  (`streaming.py:225`).

## Decision

### 1. `update_if_status` — a real CAS for the reclaim write

`RedisJobStore.update_if_status(job, *, expected)` wraps the
comparison and the write in one `WATCH`/`MULTI`/`EXEC` on the job key,
returning `False` when the stored status is not `expected` or when
Redis aborts the `EXEC`. `JobRedriver._fail_orphan` routes its write
through it with `expected` set to the status the sweep re-read under
its claim, and **both** halves of the reclaim — the store write and
the `job_failed` publish — are conditional on it landing. A lost CAS
counts as `skipped_live`, releases the claim, and publishes nothing.

Optimistic locking rather than `EVAL` for the reason ADR 0038 already
gave: `fakeredis` implements `EVAL` only with the optional native
`lupa` extension.

It is a duck-typed extra, not a `JobStore` Protocol member — the same
treatment `scan_jobs`, `publish_event` and the lease surface get, and
for the same reason: `InMemoryJobStore` has no cross-process race to
arbitrate. `_write_reclaim` falls back to a plain `update` for stores
that do not offer it.

Corollary: `orphaned == failed + requeued` still holds in
`RedriveReport`, but `orphaned` is now incremented *after* the outcome
is known rather than before.

### 2. Terminal-frame suppression lives in `publish_event`

A terminal frame is checked against the persisted row before it goes
on the wire: if the stored status is itself terminal and disagrees
with what the frame asserts, the frame is dropped and logged as
`sse_terminal_frame_suppressed`. `TERMINAL_EVENT_STATUS` in
`streaming.py` is the name → status map, and `TERMINAL_EVENT_NAMES` is
now derived from it so the two cannot drift.

This is the enforcement point rather than the runner because:

- Making `update`'s refusal observable through a return value means
  changing its `-> None` Protocol signature and `InMemoryJobStore`
  with it, for a condition that store can never be in.
- A typed exception fits the signature but is actively wrong here:
  `_persist_terminal` treats any raise as a transient store failure,
  so a refusal would be retried three times and then logged as
  `api_job_terminal_persist_failed` with the full report — reporting
  data loss for a write that was correctly declined.
- `publish_event` is where the frame becomes visible, so enforcing
  there covers every publisher — runner, redriver, and anything added
  later — with no runner change at all.

A missing row (retention TTL fired) or a non-terminal row (the
terminal persist failed outright) still publishes: "no opinion" must
not hang a subscriber waiting on a close signal. Cost is one GET per
terminal frame, which is at most one per job; non-terminal frames are
not checked, so the per-node hot path is untouched.

### 3. `_local` eviction moves into a `finally`

`update`'s whole body is wrapped, so a terminal job's `_local` entry
is dropped on every exit — write landed, guard refused, either Redis
call raised. Evicting on failure costs this worker a better answer
(`get` falls back to the stale non-terminal Redis row) but that is the
answer every *other* worker is already giving, and the outcome is
recoverable from `api_job_terminal_persist_failed`. An unbounded dict
ends in an OOM that takes the live jobs with it.

### 4. `scan_jobs` returns non-terminal rows, and skips the rest cheaply

The only place a job row is given an expiry is the terminal branch of
`update` / `update_if_status`, so `TTL >= 0` is a proof of terminality
that costs an integer reply instead of a report body. `_terminal_keys`
pipelines a `TTL` per key in the batch and the MGET covers only what
is left. The proof is one-directional — `retention_sec = 0` gives
terminal rows no TTL — so terminal rows are still dropped after
deserialization; the TTL check is an optimization layered on the real
filter, never a replacement for it.

The `(jobs, capped)` tuple is unchanged and `max_scan` still counts
*keys*, so the cap bounds the work rather than the yield.
`RedriveReport.scanned` now means "non-terminal rows the sweep had to
consider", which for a keyspace of finished jobs is zero.

### 5. The `WatchError` abort path is testable — ADR 0038 was wrong

ADR 0038 recorded the CAS abort branch as uncoverable because
"`fakeredis` resolves without true concurrency", and listed a
real-Redis integration marker as the follow-up. Re-checked against the
installed `fakeredis` 2.36.2: **the claim does not hold.** fakeredis
marks a watched key dirty on any write landing after the `WATCH`, and
redis-py's pipeline holds a connection of its own, so a write issued
through the ordinary client while the pipeline is mid-transaction
aborts the `EXEC` exactly as a real Redis would.

`tests/test_api_redis_store.py` gains an `InterlopingClient` that
fires a foreign write from inside the pipeline's `GET` on a named
watched key — the precise window optimistic locking exists to lose —
and the abort branch is now covered for `_compare_and_apply` (lease
refresh and release) and for `update_if_status`, the latter both
directly and end-to-end through a real sweep. Each test asserts the
instrumentation actually fired, so it cannot pass by never triggering.
ADR 0038's "Negative" bullet and its "real-Redis integration marker
(or `lupa`)" follow-up are superseded by this section.

### 6. `REDRIVE_LOCK_TTL_SEC`: 120s → 30s

Mid-sweep death is not an edge case — on a deploy it is the likely way
a sweep ends — and the recorded mitigation options were worse than the
knob. Recognising the dead holder and taking the lock from it is
unavailable: `WORKER_ID` is regenerated per process, so a restarted
worker cannot identify its own previous incarnation. Lease fencing is
an epic for a P3.

Shrinking is safe because the redrive lock is a de-duplication
optimization, not the safety mechanism. Mutual exclusion on an
individual job comes from `acquire_lease`'s `SET NX` plus the re-read
and now the CAS; two overlapping sweeps duplicate work but cannot
double-reclaim. A sweep is bounded work — at most
`job_redrive_max_scan` keys, now with terminal rows filtered before
their bodies are fetched — so 30s is ample and the cost of being wrong
is a redundant scan. `create_app` reuses the constant as the
`asyncio.wait_for` bound on the sweep, so worst-case boot delay
against an unreachable Redis improves by the same 90s.

### 7. `ConversationStore.update_title`

Added to the Protocol and both implementations: `UPDATE conversations
SET title` under Postgres, a guarded mutation in memory, `bool` return
so the caller can tell "renamed" from "vanished".

Ownership-agnostic, matching `get` and `append_job` rather than `list`
and `delete`: the only caller is the runner's first-job auto-title,
which acts on a conversation the job is already attached to and holds
no principal. It does not bump `updated_at` — a rename is not
activity, and bumping would jump an old thread to the top of every
client's sidebar. It does not truncate; `title_from_query` owns
`MAX_TITLE_LEN`, keeping stores dumb like the ADR 0043 pagination
contract.

The runner-side call site is not changed here (see Follow-ups).

### 8. SSE deadline flushes a frame the read already produced

When the deadline fires and the pending read task is `done()`, its
frame is emitted before the stream closes. If that frame closes the
stream, `stream_timeout` is skipped entirely: `stream_timeout` means
"reconnect, the job is still going", which is exactly wrong once the
job has ended. A non-terminal frame is flushed and then followed by
`stream_timeout` as before — the client gets the work it paid for
*and* the reconnect signal.

The regression tests drive the generator by hand with a manually
advanced clock. The ordering being pinned (loop suspended at its
keepalive yield, read task completing during that yield, deadline
firing on resume) cannot be expressed as a wall-clock race that fails
reliably against the buggy code.

## Alternatives considered

- **`update` returns `bool`** so the runner can skip its publish.
  Rejected: the `JobStore` Protocol declares `-> None`, `bool` is not
  a subtype of it, and `InMemoryJobStore` would have to change to
  report a condition it can never be in. The suppression belongs where
  the frame becomes visible.
- **A typed `TerminalTransitionRefused` exception.** Fits the
  signature and is the wrong shape: `_persist_terminal` absorbs and
  retries every exception, so a correct refusal would be retried three
  times and reported as lost data.
- **A projection for `scan_jobs`** (fetch only the `status` field
  server-side). Not available: rows are plain JSON strings and
  RedisJSON is not a dependency we want for one sweep. The retention
  TTL already encodes the same fact for free.
- **A separate `job:index:nonterminal` set** maintained on every
  status change. Strictly better asymptotics, and a second source of
  truth that can drift from the rows it indexes — the exact class of
  bug this ADR is closing three of. Revisit if `job_redrive_max_scan`
  is ever raised past 10k.
- **CAS the requeue write too.** `_requeue` writes `pending` over
  `pending` while holding the claim, so no owner can be running it;
  the reclaim is where a lost race destroys a report. Left alone to
  keep the change scoped, noted below.
- **Lease fencing tokens** for the redrive lock instead of a shorter
  TTL. The right answer if the lock ever becomes a safety mechanism.
  It is not one — per-job claims are — so this would be building an
  epic for a P3.

## Consequences

- **Positive**: a job that finishes while the sweep is deciding cannot
  have its report destroyed or its clients told it failed. A client
  cannot see two contradictory terminal frames. Worker memory is
  bounded during a Redis outage rather than growing with it. A sweep
  over a keyspace of finished jobs transfers integers instead of
  reports. A worker killed mid-sweep blocks its own restart for 30s,
  not two minutes. Auto-titling works under Postgres. A job that ends
  on the deadline boundary delivers its terminal frame.
- **Negative**: one extra pipelined round trip per SCAN batch when
  most rows are non-terminal (the unhealthy case), and one GET per
  terminal publish. `update_if_status` costs a WATCH round trip per
  reclaim, paid only on the reclaim path. `RedriveReport.scanned`
  changes meaning, so historical log comparisons across this change
  are not like-for-like. `TERMINAL_EVENT_STATUS` duplicates
  `JobStatus` values as plain strings to keep `src.api.jobs` out of
  `streaming.py`'s imports — pinned by a test against the real enum
  and against `routes._terminal_event_name`.
- **Follow-ups**:
  - `_append_to_conversation` in `src/api/runner.py` should call
    `conversation_store.update_title(job.conversation_id,
    title_from_query(job.query))` instead of mutating the fetched
    object. One line; the store side is ready. Owned by the runner
    lane.
  - `_requeue`'s store write is still a plain `update`.
  - A periodic redrive sweep (ADR 0038's open item) is untouched, and
    is where the shorter lock TTL will matter most.
  - The web UI's `EventSource` consumer still treats `stream_timeout`
    as an unknown event (ADR 0038's open item).
