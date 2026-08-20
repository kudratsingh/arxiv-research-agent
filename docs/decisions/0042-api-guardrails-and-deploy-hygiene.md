# 0042. API guardrails + deploy hygiene bundle

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: kudratsingh
- **Follows**: [ADR 0025](0025-fastapi-async-job-model.md) (healthz),
  [ADR 0030](0030-hitl-plan-review.md) (plan review),
  [ADR 0033](0033-safety-hardening-bundle.md) (auth),
  [ADR 0034](0034-postgres-checkpointer-and-cross-worker-hitl.md)
  (cross-worker resume)

## Context

A security + operations audit of the API surface upheld a cluster of
findings that share one theme: the individual pieces work, but the
seams between them fail silent or fail open.

- **Unbounded plan lists.** `POST /research/{id}/review` with
  `action=revise` accepted an arbitrarily large `plan`. The search
  node walks `search_queries` one arXiv HTTP call plus a hard
  `time.sleep(3)` at a time on a default-executor thread that
  `asyncio.wait_for(api_job_timeout_sec)` cannot cancel — the timeout
  releases the semaphore slot but the thread keeps sleeping and
  calling arXiv. Ten revise requests with 2,000 queries each pin ten
  of the sixteen default executor threads for ~90 minutes and emit
  20,000 arXiv requests. A single 100,000-query plan pins a thread
  for days.
- **Non-ASCII `X-API-Key` was an unauthenticated 500.**
  `hmac.compare_digest` on `str` operands requires ASCII; Starlette
  decodes headers as latin-1, so any byte ≥ 0x80 raised TypeError
  through the ASGI stack — a traceback to an anonymous caller instead
  of the 401 every other bad-key path returns. Worse, one non-ASCII
  *configured* secret made the non-short-circuiting loop 500 every
  request, valid keys included.
- **`/healthz` checked nothing and lied.** It did no I/O, so it
  reported `ok` with Redis dead while every real route 500'd — and
  the compose healthcheck kept the container "healthy". `active_jobs`
  was computed only for `InMemoryJobStore`, i.e. hardcoded 0 in the
  shipped Redis configuration, exactly when an operator needs the
  saturation signal.
- **Swallowed HITL resume publish.** `review_plan` wrapped
  `publish_remote_resume` in `contextlib.suppress(Exception)`. Under
  multi-worker uvicorn that publish is the only thing that wakes a
  runner parked on another worker (ADR 0034); when it was lost the
  review returned 200 and the job died 30 minutes later on
  `hitl_timeout` with nothing in any log connecting the two.
- **SIGTERM never drained.** Neither `serve.py` nor the container
  command set `timeout_graceful_shutdown`, so uvicorn waited
  unbounded on open SSE connections before running the lifespan
  cleanup. Any client streaming at deploy time meant SIGKILL: jobs
  never cancelled, pools never closed, rows left `running` for the
  redriver to mark `orphaned`.
- **Credentials logged at INFO.** `postgres_pool` logged the raw
  libpq URL — password included — as an indexed JSON field on every
  process start.
- **The compose demo was browser-dead and its mitigation unbootable.**
  No `API_CORS_ALLOW_ORIGINS` meant every cross-origin UI request
  (web on :3000, API on :8000) was blocked at preflight. And the
  documented mitigation for the open-by-default API —
  `ENABLE_API_AUTH=true` — had no compose wiring at all.

## Decision

One bundle, because every fix is a one-file guardrail and the audit
findings interlock (the plan bound is only as good as the auth that
fronts it; the auth recipe is only as good as the compose wiring).

### 1. Bound the Plan schema

`Plan.sub_questions` and `Plan.search_queries` cap at **20 items of
500 chars each** (`MAX_PLAN_ITEMS` / `MAX_PLAN_ITEM_LEN` in
`schemas.py`). The planner emits 2–6 items of roughly a sentence, so
the cap is >3x headroom over anything the workflow produces while
capping the worst-case revise at 20 arXiv calls + 60s of politeness
sleep — inside the job timeout. The bound also applies on the
response path (`JobDetail.plan`), which is deliberate: a checkpoint
restored with a garbage plan should fail loudly, not render.

The schema bound covers the HTTP path only. A belt-and-braces cap in
`search_agent` itself (bounding any plan restored from a checkpoint)
is requested from the workflow side rather than done here — the
search agent is not this change's file.

### 2. Compare API keys as bytes

`_lookup_principal` encodes the presented header back to latin-1
(recovering the exact wire bytes; a non-latin-1 `str` can only come
from a direct caller and matches nothing) and each configured secret
as utf-8, then runs the same non-short-circuiting
`hmac.compare_digest` loop over bytes — which has no ASCII
restriction. Non-ASCII presented keys are now a clean 401; a
non-ASCII configured secret authenticates against its utf-8 wire
bytes instead of poisoning the loop.

Both keystore parsers also reject **duplicate principal names** the
same way they already rejected duplicate secrets (the JSON parser
needs an `object_pairs_hook` — `json.loads` silently keeps the last
value for a repeated key). `key_id` is what ADR 0036 stamps onto
rows as the owner, so a reused name silently merges two tenants'
data. Consequence, now documented in `docs/security.md`: **a key_id
is a permanent identifier** — rename it and the principal's rows
404; reuse it and the new holder inherits the old tenant's data.

### 3. `/healthz` reports honestly, and stays HTTP 200

The handler now pings what the deployment actually configures, each
under a 2s `asyncio.wait_for`:

- **Redis** — duck-typed off the store's `_client` (the same
  coupling `create_app` already uses; making it a public property
  stays an ADR 0037 follow-up). In-memory stores simply don't
  produce the key.
- **Postgres** — `SELECT 1` through the shared pool in a thread,
  only when `settings.postgres_url` is set.

The response gains `dependencies: {name: "ok" | "error: <Type>"}`
and `status` becomes `ok`/`degraded`. `active_jobs` is now
`len(app.state.tasks)` — this worker's in-flight job tasks (queued +
running), store-independent, so the field is finally non-zero under
the shipped Redis store. It is documented as per-worker; a
cluster-wide count would need `scan_jobs` and its own endpoint.

**What healthz deliberately does not do**: it never returns 503.
It answers "is this process alive"; restarting the process does not
fix a dead Redis, and a probe that fails on dependency loss turns a
backend blip into a rolling-restart storm (`restart: unless-stopped`
+ failing healthcheck). Orchestrators that want dependency-gated
routing should parse `status`/`dependencies` from the body — a
separate `/readyz` with 503 semantics remains open as the
planning/06 follow-up. The endpoint stays auth-exempt: probes can't
send keys.

### 4. Log the dropped resume publish

The `contextlib.suppress` around `publish_remote_resume` becomes
`try/except` + `log.error("hitl_resume_publish_failed", exc_info=...,
extra={job_id, action})`. The 200 response is kept: the decision is
durably persisted on the job row before the publish, and the
same-worker path resumes via the local Event regardless — a 503
would tell the reviewer their (persisted) decision failed. What was
missing was the log line that lets the 3am engineer connect a
`hitl_timeout` to the publish that was dropped 30 minutes earlier.
The same unlogged suppressions in `runner._put_event` /
`_put_terminal_event` are the runner file's to fix.

### 5. Bounded graceful shutdown

`serve.py` passes `timeout_graceful_shutdown=10` to uvicorn, and
the compose `app` service overrides the container command to
`python -m src.api.serve` with `stop_grace_period: 15s`, making
`serve.py` the single source of truth for the drain *and* for
`log_config=None`. Routing through `serve.py` is load-bearing, not
taste: the uvicorn CLI cannot express "no log config" — the
Dockerfile CMD's `--log-config /dev/null` is rejected at boot
(`fileConfig` refuses an empty file), so a CLI-style compose
override either crashes the container or re-installs uvicorn's
default non-JSON loggers. Fixing the Dockerfile CMD itself is the
container file's follow-up; the compose override does not depend on
it. The ordering constraint is the point: uvicorn drains SSE for at
most 10s, *then* runs the lifespan cleanup (cancel jobs →
`cancelled` + terminal frame, close checkpointer + pools), and the
orchestrator's kill must come after that — so grace period > drain
timeout, and k8s deployments must keep
`terminationGracePeriodSeconds` above 10s likewise.

### 6. `redact_url` before logging connection strings

`src/observability/logging.py` grows `redact_url()` (exported from
the package): userinfo → `***`, scheme/host/port/path kept.
`postgres_pool` uses it at the startup log; the `redis_url` log site
in `app.py` and any future ones migrate as their files are touched.

Two smaller logging fixes ride along: `JsonFormatter` timestamps are
now UTC ISO-8601 with milliseconds and an explicit offset (local
second-granularity stamps made cross-host incident timelines
ambiguous), and the httpx/anthropic library-logger demotion is
skipped when the root level is DEBUG, so `LOG_LEVEL=DEBUG` +
`ANTHROPIC_LOG=debug` actually produces SDK request logs.

### 7. Compose: CORS on, auth bootable

`docker-compose.yml` sets
`API_CORS_ALLOW_ORIGINS: ${API_CORS_ALLOW_ORIGINS:-http://localhost:${WEB_PORT:-3000}}`
— an explicit allowlist, never `*`, because the middleware runs with
`allow_credentials=True`. It also passes through
`ENABLE_API_AUTH` (default `false`) and `API_KEYS` (default empty),
so the documented mitigation is one env flip:
`ENABLE_API_AUTH=true API_KEYS="ops:sk_..." docker compose up`.
`/healthz` being auth-exempt is what keeps the healthcheck (and the
`web` service's `service_healthy` gate) green under auth-on. Known
limit, documented in `docs/security.md`: the shipped web UI cannot
send `X-API-Key`, so auth-on currently protects curl/SDK access; a
server-side proxy route in the Next.js app is the web lane's
follow-up.

Postgres rides along with two audit fixes in its own file:
server-side `statement_timeout=10000` / `lock_timeout=5000` on every
pooled connection (a lock-blocked query no longer holds an executor
thread forever), and `created_at` indexes on both cache tables so an
age-based purge is expressible before the tables are multi-GB — the
purge command itself is a follow-up.

## Alternatives considered

- **503 from /healthz on dependency failure.** Rejected (see §3):
  couples process liveness to backend liveness and creates restart
  storms. A separate `/readyz` is the right home for 503 semantics.
- **503 from the review endpoint on publish failure.** Rejected: the
  decision is already durably persisted and the same-worker path has
  already resumed; a 503 invites a retry of an operation that
  half-succeeded. Logging + the runner-side poll fallback (runner
  file's follow-up) close the gap at lower blast radius.
- **Require `API_KEYS` in compose (`:?` like `ANTHROPIC_API_KEY`).**
  Rejected for now: it breaks the zero-config demo the README
  promises, and auth-on breaks the shipped web UI anyway. Revisit
  when the web proxy route lands.
- **Owner-id derived from the secret hash** (fixing rename/reuse
  structurally rather than by documentation). Right long-term shape,
  but it needs a row migration and an ADR 0036 revisit; duplicate-
  name rejection + the permanence rule are the cheap interim.

## Consequences

- A revise plan larger than 20×500 is a 422, applied before
  anything is persisted. Existing checkpoints with oversized plans
  fail response validation on `GET /research/{id}` — loud by design.
- Health output changes shape (`dependencies` added); the compose
  healthcheck (`curl -fsS`) is unaffected since the status code
  stays 200.
- Every process start logs redacted URLs; anyone grepping logs for
  full connection strings loses that (bad) capability.
- `docker compose down` now completes in ≤15s with jobs marked
  `cancelled` instead of hanging until SIGKILL and orphaning them.
- Deferred, tracked in the audit follow-ups: request body-size
  middleware, admission control / queue caps, `/readyz`, rate
  limiting `POST /conversations`, idempotency keys, OpenAPI security
  scheme, the cache purge command, and Alembic-style migrations
  (ADR 0028's revisit trigger has been met).
