# 0037. Redis-backed rate limiter + hot-reloadable keystore

- **Status**: accepted
- **Date**: 2026-07-13
- **Deciders**: kudratsingh
- **Follows**: [ADR 0033](0033-safety-hardening-bundle.md) (API-key auth)

## Context

ADR 0033 shipped `X-API-Key` auth + a per-worker in-memory
sliding-window rate limiter. Two follow-ups from that ADR's
"Not in scope" list:

**Rate-limit persistence.** The in-memory limiter's counter lives
in `deque`s on `app.state`. Under multi-worker uvicorn each worker
has its own counters, so the effective limit becomes
`api_key_hourly_limit * n_workers`. That defeats the point once
auth-on deployments hit real traffic — a 100/hour cap under 4
workers is really 400/hour.

**Key rotation.** `api_keys` is parsed once from a comma-separated
string at `create_app` startup. Rotating a compromised key means
editing the env var and restarting the process, which drops
in-flight jobs and interrupts every SSE stream.

Both are small bugs in isolation and share the same fix shape:
move the mutable state out of per-worker memory. Bundling them
into one PR keeps the "make auth actually production-ready" story
in one place.

## Decision

Two peer changes.

### 1. Pluggable rate limiter with a Redis backend

- `RateLimiter` becomes a `Protocol` with a single async method:
  `async check_and_record(key_id, *, now=None) -> None`.
- `InMemoryRateLimiter` is the ADR-0033 dataclass, renamed for
  clarity and switched to `asyncio.Lock` so it composes with the
  async `enforce_rate_limit` call site.
- `RedisRateLimiter` uses a ZSET keyed by `ratelimit:{key_id}`:
  1. `ZREMRANGEBYSCORE` prunes anything older than the sliding
     window.
  2. `ZADD` records the current submit with a UUID member and the
     timestamp as score.
  3. `ZCARD` counts what's now in the window.
  4. `EXPIRE` bumps the TTL so idle keys eventually vacate Redis.

  All four run in one pipeline. If `ZCARD` shows over-cap, roll
  the record back with `ZREM` before raising 429. Trade-off: a
  small race under adversarial concurrent load might let two
  requests both squeak past the boundary; acceptable at demo
  scale, and Lua-scripted atomicity is a follow-up if we ever see
  it fire.
- `build_rate_limiter(limit, backend, *, redis_client)` picks the
  backend from `settings.rate_limit_backend` ("memory" default,
  "redis" for the shared-across-workers case). `create_app`
  reuses the JobStore's Redis client when the JobStore is the
  Redis variant, so we don't open a second connection pool.
- `enforce_rate_limit` and the route call site (`submit_research`)
  are now async — required for the Redis path, harmless for the
  memory path.
- Compose flips `RATE_LIMIT_BACKEND=redis` alongside the existing
  `JOB_STORE=redis` and `CHECKPOINT_BACKEND=postgres`.

### 2. Hot-reloadable keystore from JSON file

- `settings.api_keys_file`: optional path to a JSON `{name: secret}`
  object. When set, overrides `settings.api_keys` and enables
  hot reload.
- `settings.api_keys_reload_interval_sec` (default 30) controls the
  mtime poll cadence.
- `KeystoreReloader` in `src/api/auth.py`:
  - `initial_load()` raises on parse failure — booting an auth-on
    app with a broken keystore fails fast rather than silently
    letting everyone in.
  - `run()` poll loop: check `os.path.getmtime`; on change,
    re-parse; on success, swap `app.state.api_keys`; on parse
    failure, log + drop the change + do NOT update
    `_last_mtime` so the next successful edit is still picked up.
  - Missing file after startup: log a warning, keep the current
    keystore. Handles the "operator edits the file in-place with
    an editor that unlinks and rewrites" pattern gracefully.
- Dict swap is atomic in CPython (`app.state.api_keys = new_keys`
  is a single reference reassignment), so no lock is needed on the
  read path — concurrent `require_principal` calls either see the
  old or the new dict, never a half-swap.

## Alternatives considered

- **Lua-scripted rate limiter for exact atomicity.** Rejected for
  now: adds a script to load + version, and the demo-scale cost of
  a tiny boundary race is one extra request through the cap. If
  observability shows the race firing meaningfully at production
  scale, upgrade then.
- **Rate limiter in Postgres** (share the ADR-0028 pool). Rejected:
  Postgres handles fine, but Redis is already in the stack, the
  sorted-set primitive is exactly the right shape, and Redis's
  `EXPIRE` beats a Postgres retention job.
- **Keystore in Redis with pub/sub for rotation events.** Rejected
  for this PR: works, but adds a Redis dependency to auth (today
  auth only needs Redis when `rate_limit_backend=redis`). File-
  based works everywhere including local dev without Redis, plays
  nicely with Kubernetes mounted secrets that update on the fly,
  and doesn't need a new pub/sub channel. Redis-based keystore is
  a follow-up if a customer needs sub-second rotation.
- **Watchdog / inotify** instead of mtime polling. Rejected:
  another dependency for a check that fires every 30s. Polling
  is simple, portable, and cheap.
- **Admin endpoint** (`POST /admin/reload-keys`). Rejected:
  chicken-and-egg — the admin endpoint needs auth of its own —
  and requires an operator action rather than declarative config.
  The file mechanism composes cleanly with GitOps + secret
  rotators.
- **Signal-based reload** (SIGHUP). Rejected: Unix-only, awkward
  in containers, and doesn't play nicely with async event loops.

## Consequences

**Positive**

- Rate limit is correct under multi-worker uvicorn. Compose stack
  ships correct out of the box.
- Key rotation is a file edit — no process restart, no dropped
  jobs, no SSE reconnects. Operators can integrate with Kubernetes
  Secret projection, HashiCorp Vault, Doppler, etc.
- One dependency-free code path for local dev: string-based keys
  + memory rate limiter still work exactly as before when the new
  settings are left at defaults.

**Negative**

- Rate limiter runs one Redis round-trip per submit. Fine at demo
  scale; a hot-hot deployment with 10k submits/sec would want
  either a burst budget with local batching or the Lua-script
  variant.
- The `_client` attribute we grab off `RedisJobStore` to share
  the connection is private — a light coupling. Alternative would
  be exposing a `client` property; noted as a follow-up.
- File-based keystore requires the file to exist and be readable
  at startup when configured. A stat-races-with-atomic-swap edge
  case exists (operator writes new file, we stat mid-swap) but
  a common editor pattern (write-tmp → rename) is atomic on POSIX.

**Follow-ups**

- Lua-scripted `check_and_record` if the boundary race becomes
  observable.
- Expose `RedisJobStore.client` as a public property to remove the
  `_client` coupling.
- Redis-backed keystore with pub/sub rotation events if a
  customer needs sub-second key propagation across workers
  (mtime polling has a ~30s worst-case delay).
- Admin cleanup migration for legacy NULL-owner rows (ADR 0036
  follow-up, unchanged by this PR).
