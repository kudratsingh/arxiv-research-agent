# 0043. Conversation store hardening

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: kudratsingh
- **Follows**: [ADR 0032](0032-conversation-mode.md) (conversation
  mode), [ADR 0036](0036-per-principal-store-scoping.md)
  (per-principal scoping)

## Context

The production audit upheld four findings against the conversation
layer, all of the same shape: code that is correct at demo scale
and wrong under concurrency or volume.

1. **Blocking DDL on the event loop.** All five
   `PostgresConversationStore` methods called the synchronous
   `init_schema()` before entering their `asyncio.to_thread`
   closure. When the once-guard hadn't tripped yet, that call did
   a blocking `pool.open(wait=True, timeout=10.0)` plus the full
   schema DDL — including an `ALTER TABLE` needing ACCESS
   EXCLUSIVE — on the loop thread. A worker booting while Postgres
   was slow or briefly unreachable froze every in-flight request,
   SSE heartbeats included — and because `/healthz` ran into the
   same freeze, the container healthcheck could kill the worker.

2. **Ordinal race on append.** `append_job` read
   `MAX(ordinal)` and inserted `MAX+1` in two statements. Two
   follow-up jobs in the same conversation completing together
   both computed the same ordinal; the loser died on the primary
   key. The runner wraps the append in
   `contextlib.suppress(Exception)`, so the failure — a fully
   paid-for report — vanished with no log line, no metric, and a
   permanent hole in the thread.

3. **Unbounded list.** `GET /conversations` returned every row the
   principal ever created, serialized as one JSON array. At 10k
   conversations that's a full-table sort and a ~1.5 MB response
   per sidebar mount, with no server-side lever to cap it.

4. **Fetch-then-delete pair.** `DELETE /conversations/{id}` did
   the ADR 0036 two-round-trip dance (fetch for the ownership
   check, then delete) — already flagged as a follow-up in that
   ADR, and also a small TOCTOU window between check and delete.

## Decision

Ship four changes as one bundle, all inside
`src/api/conversations.py` + the conversation route handlers.

1. **Schema bootstrap moves into the `_run` closures.** Every
   Postgres method now calls `init_schema()` as the first line of
   the closure that `asyncio.to_thread` executes, so pool open +
   DDL always run on a worker thread. `init_schema` keeps its own
   process-wide once-guard, so every call after the first is a
   boolean check — no per-request cost, no extra class-level
   guard to keep in sync with the pool module's test seams.

2. **Appends serialize on the parent row.** The existence check
   becomes `SELECT 1 ... FOR UPDATE`: concurrent appends to one
   conversation queue on the row lock instead of racing. The
   insert itself computes `COALESCE(MAX(ordinal), 0) + 1` inside
   a single `INSERT ... SELECT ... RETURNING` statement, so even
   without the lock there is no read-modify-write gap. And because
   the runner's blanket suppress is upstream of this module, the
   store logs `conversation_append_failed` at ERROR before any
   exception propagates — a lost report is now at minimum
   observable. The in-memory store mirrors the `MAX+1` allocation
   (previously `len+1`) so the two implementations stay
   behaviorally identical.

3. **Offset pagination on `list`.** `GET /conversations` takes
   `limit` (default 50, cap 200, enforced by FastAPI `Query`
   validation) and `offset` (≥ 0). Both ride through
   `ConversationStore.list` into SQL `LIMIT/OFFSET` under
   Postgres and a post-sort slice in memory. The ADR 0036
   principal filter composes underneath: offset counts the
   caller's own rows. `conversation_id` tie-breaks equal
   `updated_at` values in both stores so consecutive pages never
   overlap or skip. Defaults live in `conversations.py`
   (`DEFAULT_LIST_LIMIT` / `MAX_LIST_LIMIT`) so the store and the
   route can't drift apart.

4. **Ownership inline in DELETE.** `ConversationStore.delete`
   grows a `principal_key_id` keyword: `None` means unscoped
   (auth-off, legacy behavior); a value appends
   `AND principal_key_id = %s` to the single DELETE statement.
   SQL equality never matches a NULL owner, so legacy rows stay
   untouchable under auth-on, and a mismatch returns `False` —
   which the route maps to the same 404 a missing id gets,
   preserving ADR 0036's 404-not-403 rule exactly. This closes
   that ADR's "single-statement delete" follow-up and removes the
   check/delete window.

Additionally, `POST /conversations` now calls
`enforce_rate_limit` — it was the one durable write the per-key
hourly limiter never saw, so a leaked key could accrete unbounded
rows on the shared Postgres with no signal. It draws from the same
budget as `/research` submits for now (see Alternatives).

## Alternatives considered

- **Keyset (cursor) pagination** instead of `LIMIT/OFFSET`.
  Keyset is O(1) at any depth and immune to skew when rows are
  inserted mid-scroll; offset degrades linearly. Rejected for
  now: the sidebar's access pattern is "first page, occasionally
  second," the offset SQL is trivially indexable, and the API
  contract (`limit`/`offset` integers) is the simplest thing a UI
  can consume. A cursor on `(updated_at, conversation_id)` can be
  added later without breaking `limit`, since the parameters are
  additive.

- **Bounded retry on `UniqueViolation`** instead of the row lock.
  Works, but retries multiply the `updated_at` bump and make the
  failure path the common path under contention. The `FOR UPDATE`
  lock costs one lock acquisition on a row we already read and
  update in the same transaction, and makes collisions
  structurally impossible rather than statistically recovered.

- **Class-level once-guard** for the schema bootstrap instead of
  calling the already-guarded `init_schema()` per closure. A
  second guard would have to be reset in lockstep with
  `postgres_pool._reset_for_test`, which tests call today; the
  pool module's own guard is the single source of truth and its
  fast path is one boolean check.

- **A dedicated `api_conversation_hourly_limit`** with its own
  bucket for `POST /conversations`. Cleaner — creates and submits
  have different natural rates — but it needs a new setting and a
  keyed bucket scheme in the limiter, which are outside this
  change's file boundary. Sharing the existing per-key budget
  closes the unbounded-write hole today; the dedicated bucket is
  a follow-up.

- **Fixing the runner's `contextlib.suppress`** around the append
  call. That's the right long-term home for a retry, but the
  suppress lives in `runner.py`; the store-side ERROR log is
  deliberately placed so visibility does not depend on every
  caller doing the right thing.

## Consequences

**Positive**

- No request handler ever blocks the event loop on pool open or
  DDL; a slow or down Postgres degrades conversation endpoints
  only, not the whole worker.
- Concurrent follow-up jobs in one conversation both land, with
  consecutive ordinals; a failed append is loud in the logs.
- Sidebar reads are bounded at 200 rows regardless of tenant
  size, and paging composes with per-principal scoping.
- One fewer round trip on delete, and no ownership TOCTOU.

**Negative**

- `ConversationStore.list` and `.delete` signatures changed;
  external implementers of the Protocol must add the new keyword
  args (in-repo, all call sites are the route layer and runner).
- Clients that expected `GET /conversations` to return everything
  now get at most 200 rows per request and must page.
- Conversation creates now consume `/research` rate-limit budget
  under auth-on — acceptable until the dedicated bucket lands.

**Follow-ups**

- Composite index `(principal_key_id, updated_at DESC)` on
  `conversations` so the scoped, ordered, paginated query is
  fully index-served (`SCHEMA_DDL` lives in `postgres_pool.py`).
- Dedicated `api_conversation_hourly_limit` + per-principal
  ceiling on live conversations (409 past the cap).
- Keyset cursor as an additive parameter if deep paging shows up
  in access logs.
- `limit_jobs` projection on `get` so follow-up retrieval stops
  re-reading entire long threads (audit P3, spans the runner).
