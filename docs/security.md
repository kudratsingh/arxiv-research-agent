# Security

## Threat model

The workflow ingests arXiv PDFs. That's untrusted content: anyone
can publish a paper, and the reader passes paper text directly into
a Claude call whose output the workflow acts on. Sprint 2 landed a
supervisor loop that reads reader-emitted control tokens, which
made prompt injection a **workflow-control** risk on top of the
existing "the report is wrong" risk.

Attackers we defend against:

- A malicious arXiv paper with a jailbreak in its abstract or full
  text, aiming to redirect the supervisor's next action, stop the
  loop early, or smuggle instructions into the report via evidence
  claims.
- An in-flight MITM sitting between the workflow and arXiv, trying
  to inject attacker-chosen `PaperMetadata` that then drives Claude
  prompts and PDF fetches.
- An adversarial PDF host serving multi-hundred-MB content in
  response to `parse_pdf`, aiming to exhaust worker memory.
- An anonymous HTTP caller trying to drain the Anthropic account by
  hitting `POST /research` at scale.
- A conversation follow-up where a prior report — itself derived
  from adversarial-controllable paper text — carries a jailbreak
  that redirects the planner on the next turn.

Not in scope:

- Content-safety filtering (offensive text in abstracts).
- Injection via user-supplied query strings (short, controlled).
- Compromised Claude / Anthropic infrastructure.
- Compromised arXiv delivery infrastructure (the workflow does not
  cryptographically verify PDFs).

## Defenses

### Reader prompt-injection isolation (ADR 0020)

Behind `settings.enable_prompt_isolation` (default off; **flip on
whenever `enable_supervisor` is on**). Three layers:

1. **Delimiter isolation**. Paper-derived text (abstract + ranked
   chunks) is wrapped in `<untrusted_paper_text>...</untrusted_paper_text>`
   tags in the reader's user prompt. Close tags in the content are
   escaped so a paper can't terminate the wrapper.
2. **Explicit system-prompt instruction**. `ISOLATION_SYSTEM_INSTRUCTION`
   is prepended to the reader's system prompt when the flag is on.
   It names the delimiter tags and the exact control fields it's
   protecting (`analysis_complete`, `request_more_sections`,
   `missing_context`).
3. **Output sanitization on control fields**.
   `sanitize_control_string(missing_context)` trims / caps at 300
   chars / blanks on jailbreak markers.
   `sanitize_section_names(request_more_sections)` drops entries
   longer than 50 chars, entries with disallowed characters, and
   entries with jailbreak markers. `_parse_claim` runs the same
   filter on `EvidenceClaim.claim` and drops the claim on match.

Source: `src/security/prompt_isolation.py`. Wired at
`src/agents/reader.py::_analyze_paper` and
`src/agents/reader.py::_parse_recovery_signal` /
`src/agents/reader.py::_parse_claim`.

**Not sanitized**: `EvidenceClaim.source_text` (the verifier judges
against it; must be verbatim), `key_findings` / `methodology` /
`results_summary` / `limitations` (flow to synthesizer, not to
supervisor control tokens). These are follow-up work.

### Planner prior_context isolation (ADR 0033)

Behind the same `settings.enable_prompt_isolation` flag. When
conversation mode (ADR 0032) retrieves prior-report chunks into
`state.prior_context`, the planner:

1. Wraps the text with
   `<untrusted_prior_context>...</untrusted_prior_context>` tags via
   `wrap_untrusted_prior_context()`. Close tags in the content are
   escaped.
2. Prepends `PRIOR_CONTEXT_ISOLATION_INSTRUCTION` to the system
   prompt. It names the tag pair and the exact control fields it's
   protecting (`sub_questions`, `search_queries`).

Wired at `src/agents/planner.py::_build_user_prompt` and
`src/agents/planner.py::_build_system_prompt`. Same defense pattern
as the reader; distinct tags so the guardrail can name the fields
precisely.

### Transport hardening (ADR 0033)

- `ARXIV_API_URL` is `https://export.arxiv.org/api/query`. An
  in-flight MITM cannot substitute paper metadata.
- Response parsing uses `defusedxml.ElementTree`, which raises
  `EntitiesForbidden` on any DOCTYPE + entity payload — no XXE,
  no billion-laughs.

### PDF fetch guardrails (ADR 0033)

- `_download_pdf` streams with `iter_content` and aborts once
  `settings.pdf_max_bytes` (default 50 MiB) is reached. Servers
  that declare `Content-Length` above the cap are refused before
  any bytes flow.
- `_cache_key` only extracts an arXiv ID when
  `urlparse(pdf_url).hostname` is under `arxiv.org`; other hosts
  fall through to a SHA hash of the full URL, so a URL like
  `https://evil.com/2311.09000/attack.pdf` cannot poison the cache
  slot for the real arXiv paper.

### Per-run cost cap (ADR 0033)

`src/api/runner.py::_enforce_cost_cap` runs from the runner's
`on_node` callback between graph nodes and raises
`CostBudgetExceeded` when `RunCosts.total_cost_usd >=
settings.max_cost_usd`. The job terminates as `failed` with
`error_type=cost_budget_exceeded`. This is the only enforcement
point that catches the fixed-DAG path where the supervisor's own
check doesn't apply.

### API-key auth + rate limiting + CORS (ADR 0033)

Behind `settings.enable_api_auth` (default off; **flip on for any
exposed deployment**). Three layers:

1. **API-key authentication**. Every `/research` and `/conversations`
   route carries `dependencies=[Depends(require_principal)]`. The
   dependency reads the `X-API-Key` header, looks it up in the
   startup-parsed keystore (`settings.api_keys`, format
   `name:secret,name:secret`), and returns an `ApiKeyPrincipal`.
   Missing or unknown key -> 401. Lookup uses `hmac.compare_digest`
   in a non-short-circuiting loop for constant-time comparison —
   over **bytes**, not str (ADR 0042): Starlette decodes headers as
   latin-1, and `compare_digest` on str raises TypeError for any
   non-ASCII character, which used to turn a one-byte probe into an
   unauthenticated 500 with a traceback. `/healthz` and `/docs`
   stay open.

   **A `key_id` (the name half of a keystore entry) is a permanent
   identifier.** It is what ADR 0036 stamps onto every job and
   conversation as the owner. Renaming a key orphans that
   principal's rows (404 on everything); reusing a retired name
   hands the new holder the previous tenant's data. Both parsers
   reject duplicate names for this reason (ADR 0042) — rotate the
   *secret* under a stable name, never the name.
2. **Per-key rate limit**. `RateLimiter` records submit timestamps
   per principal in an in-memory sliding window. When a key
   exceeds `settings.api_key_hourly_limit` submits per hour,
   `POST /research` returns 429 with a `Retry-After` header. Only
   the submit route is throttled; reads / status calls are not.
3. **CORS allowlist**. When `settings.api_cors_allow_origins` is
   non-empty (comma-separated origins), FastAPI's `CORSMiddleware`
   is installed with those origins allowed, `X-API-Key` in
   `allow_headers`, and credentials allowed. Empty (default) means
   no middleware — same-origin only.

Source: `src/api/auth.py`. Wired in `src/api/app.py::create_app`
and route decorators in `src/api/routes.py`.

### Redis rate limiter + hot-reloadable keystore (ADR 0037)

Follow-up to the ADR-0033 auth bundle:

- `settings.rate_limit_backend`: `memory` (default, per-worker) or
  `redis` (shared ZSET on `ratelimit:{key_id}`, correct across API
  workers). Compose sets `redis`. Reuses the ADR-0027 JobStore's
  Redis client so no extra connection pool is opened.
- `settings.api_keys_file`: optional path to a JSON `{name: secret}`
  file. When set, overrides `settings.api_keys` and enables hot
  reload — a background `KeystoreReloader` polls mtime every
  `settings.api_keys_reload_interval_sec` (default 30) and swaps
  `app.state.api_keys` atomically. Parse failures are logged and
  the current keystore is retained; a bad edit doesn't lock
  legitimate callers out.

Wired in `src/api/auth.py::{InMemoryRateLimiter,RedisRateLimiter,
KeystoreReloader,build_rate_limiter,load_keystore_from_file}` and
`src/api/app.py::create_app`. `enforce_rate_limit` is async now so
both backends fit the same call site.

### API guardrails + deploy hygiene (ADR 0042)

Closes the audit findings on the seams between the ADR 0030/0033/0034
pieces:

- **Bounded HITL plans.** `Plan.sub_questions` / `Plan.search_queries`
  cap at 20 items x 500 chars (the planner emits 2-6). Before the
  cap, one `action=revise` request could hand the search node
  thousands of queries — each an arXiv call plus a hard 3s sleep on
  an executor thread the job timeout cannot cancel.
- **Loud resume-publish failures.** A failed
  `publish_remote_resume` on `POST /research/{id}/review` is logged
  at ERROR with the `job_id` (`hitl_resume_publish_failed`) instead
  of being suppressed — the review's 200 stands (the decision is
  persisted; the same-worker path resumed via the local Event), but
  the incident timeline now contains the drop.
- **Honest `/healthz`.** Pings Redis (via the store's client) and
  Postgres (when configured) under 2s timeouts, reports
  `status: ok|degraded` + a per-dependency breakdown, and computes
  `active_jobs` from the worker's own task set (it was a constant 0
  under the shipped Redis store). Always HTTP 200 — liveness, not
  readiness; see ADR 0042 for why.
- **Bounded drain.** `timeout_graceful_shutdown=10` in `serve.py`,
  which the compose command boots (`python -m src.api.serve`), plus
  `stop_grace_period: 30s`, so SIGTERM actually reaches the
  lifespan cleanup instead of hanging on open SSE streams until
  SIGKILL orphans in-flight jobs. The cleanup itself is bounded at
  every step (ADR 0047): cancelled jobs wait at most
  `runner.SHUTDOWN_DRAIN_SEC` for their node threads to unwind, and
  the node pool's join is capped the same way, so no single wedged
  agent can hold the container open to SIGKILL.
- **Credential redaction.** `redact_url()` in
  `src/observability/logging.py` strips userinfo from connection
  URLs before they hit the indexed JSON log stream; wired at the
  Postgres pool's startup log, remaining call sites migrate as
  their files are touched.

### Turning auth on under compose (ADR 0042)

The compose stack ships auth-off so `docker compose up` stays a
zero-config demo — which means the API is anonymous and unthrottled
on whatever interface `APP_PORT` is published to. **Never expose the
demo configuration beyond localhost.** To gate it:

```bash
ENABLE_API_AUTH=true API_KEYS="ops:$(openssl rand -hex 24)" \
  docker compose up
```

Both variables pass through `docker-compose.yml` into the app
service. Notes:

- Set **both** — `ENABLE_API_AUTH=true` with an empty `API_KEYS`
  boots, but every gated request 500s with
  `api_auth_misconfigured` (fail-closed, nothing is exposed).
- `/healthz` is auth-exempt by design, so the container healthcheck
  and the `web` service's `service_healthy` gate keep passing.
- The rate limiter activates with auth (it is keyed per principal)
  and is Redis-backed in compose, so the limit holds across
  workers.
- CORS: the compose default allowlists the web UI's origin
  (`http://localhost:${WEB_PORT}`) via `API_CORS_ALLOW_ORIGINS` —
  always an explicit allowlist, never `*`, because the middleware
  allows credentials. Override the variable for staging/prod
  origins.
- **Known limit:** the shipped web UI cannot send `X-API-Key`
  (plain `fetch`, and `EventSource` cannot set headers at all), so
  with auth on the UI's API calls 401. Auth-on currently protects
  curl/SDK access; the fix — a Next.js route handler that proxies
  to the API and injects the key server-side — is tracked as a
  web-lane follow-up.

### Per-principal Job + Conversation scoping (ADR 0036)

Every `Job` and `Conversation` carries a `principal_key_id: str |
None` field set to the caller's key_id at creation time. Route
handlers call `_check_ownership(resource_key_id, caller,
detail=...)` after every fetch:

- Auth off: caller has no principal; all rows are visible (legacy
  demo behavior).
- Auth on: caller must own the resource; otherwise **404** (not
  403 — leaking "this exists but you can't touch it" is an info-
  disclosure vector).
- Legacy rows (`principal_key_id=None`) are invisible under auth-on
  until an admin cleanup migration.

`ConversationStore.list(principal_key_id=...)` pushes the filter
into SQL for the Postgres store so scaled deployments don't drag
other tenants' rows across the wire per request.

`POST /research` additionally verifies the caller owns the
`conversation_id` they're piggybacking on — otherwise a hostile
key holder could dump their cost-bearing job into another
principal's thread.

Wired in `src/api/routes.py::_check_ownership` and
`_principal_key_id`. Postgres schema migration in
`src/tools/postgres_pool.py::SCHEMA_DDL` (ADD COLUMN IF NOT EXISTS
+ partial index on non-NULL).

### Legacy NULL-owner cleanup (ADR 0039)

ADR 0036 left rows written before it with `principal_key_id = NULL`,
invisible to every principal under auth-on. `python -m
src.api.admin_migrate` (`make admin-migrate`) is the operator tool
for them — deliberately a CLI a human drives, not an automatic
migration, because ADR 0036's reason for rejecting auto-assignment
still holds: the correct owner is usually knowable only by reading
the query text.

Safety properties worth knowing before you run it:

- **Dry-run by default.** Nothing writes without `--yes`. `report`
  never writes at all.
- `assign --owner KEY_ID` **validates the key against the live
  keystore** (`api_keys`, or `api_keys_file` when set, matching
  `create_app`'s resolution order). Assigning to a nonexistent key
  would bury the data one level deeper.
- Rewriting a Redis row **preserves its TTL**. A plain `SET` would
  resurrect expired terminal jobs.
- Availability is decided by which store is *selected*, not by
  whether a URL happens to be configured — `postgres_url` is shared
  with the paper cache, embedding cache, and the ADR 0034
  checkpointer, so gating on it alone would point the tool at a
  `conversations` table the running service never reads.
- `delete` emits one structured log record per destroyed row. Once
  a Redis key is gone there is no other surviving evidence of what
  it was, so an aggregate count could never answer "was mine one of
  them?" during an incident review.

Blast radius is bounded by `--limit`, which applies **per store** —
`--store all --limit N` can touch up to 2N rows.
### Job leases and the redrive lock (ADR 0038)

Two new Redis keyspaces: `joblease:{job_id}` (held by the worker
running a job, owner-checked CAS on refresh and release) and
`redrive:lock` (cluster-wide, held for the duration of a startup
sweep). Both are namespaced by the store's `key_prefix`, so two
deployments sharing one Redis cannot claim each other's leases or
contend for a single global lock.

`job_lease_ttl_sec` is the worst-case delay before a crashed
worker's jobs become reclaimable — and, correspondingly, the window
in which a hung-but-alive worker keeps its jobs off-limits to the
redriver.

### Adversarial tests

- `tests/test_reader_isolation.py` — canned jailbreak strings in the
  abstract, in the LLM's response (simulating a compromised model),
  and in evidence claims. Verifies both flag positions.
- `tests/test_planner_prior_context.py::TestPriorContextIsolation`
  — asserts that adversarial-looking prior_context is wrapped, not
  obeyed, when `enable_prompt_isolation` is on, and that the flag
  gates whether the system instruction is added.
- `tests/test_arxiv_search.py::test_search_arxiv_rejects_entity_expansion`
  — proves `defusedxml` refuses a billion-laughs payload.
- `tests/test_pdf_parser.py::TestDownloadPdf` — proves declared-
  oversize and mid-stream oversize both abort without allocating
  the whole PDF, and that a URL masquerading with an arXiv-shaped
  path but a non-arXiv host doesn't share a cache slot with the
  real arXiv paper.
- `tests/test_runner_cost_cap.py` — proves `_enforce_cost_cap`
  raises `CostBudgetExceeded` at and above the ceiling, and that
  the empty accumulator never trips.
- `tests/test_api_auth.py` — end-to-end HTTPX suite proves every
  `/research` and `/conversations` route rejects missing / invalid
  keys and accepts a valid key, `/healthz` stays open, and the
  sliding-window rate limiter buckets per principal.
- `tests/test_per_principal_scoping.py` — end-to-end HTTPX suite
  with two API keys: verifies that principal B gets 404 on
  principal A's conversations (read, delete, piggyback via
  `POST /research`), that `GET /conversations` filters by
  principal, that `_check_ownership` treats legacy NULL-owner rows
  as invisible under auth-on, and that auth-off behavior is
  unchanged.
- `tests/test_redis_rate_limiter.py` — fakeredis-backed: under/
  over-limit → 429, sliding window slides, rollback on over-cap
  keeps the ZSET tight, per-key isolation, and — the production
  win — two `RedisRateLimiter` instances against the same Redis
  see the same counter (which the memory backend can't do).
- `tests/test_keystore_reloader.py` — file-format contract
  (bad JSON, non-object shape, empty values, duplicate secrets),
  initial-load seeds mtime, in-flight reload picks up a file
  change, and a broken edit is logged + skipped without evicting
  the current in-memory keystore.
- `tests/test_api_auth.py::test_non_ascii_key_returns_401_not_500`
  — parametrized raw-byte `X-API-Key` values (utf-8 Cyrillic, a
  lone `\xff`, a copy-pasted NBSP) each get a clean 401 instead of
  the pre-ADR-0042 TypeError 500; companion unit tests prove an
  ASCII key still matches when a non-ASCII secret sits in the
  keystore, and that a non-ASCII secret matches its own utf-8
  wire bytes.
- `tests/test_api_hitl.py::TestPlanBounds` — a 21-query or
  501-char-item revise plan is a 422 and is never applied to the
  workflow; a plan at exactly the caps goes through.
- `tests/test_api_hitl.py::TestResumePublishFailure` — a store
  whose `publish_remote_resume` raises still yields a 200 review,
  and the failure lands in the log with `job_id`, action, and
  traceback.
- `tests/test_api_guardrails.py` — compose contract pins (CORS
  allowlist present and never `*`, auth env pass-through, bounded
  drain with grace period above it), uvicorn graceful-shutdown
  wiring, and the Postgres pool's server-side timeouts.
- `tests/test_log_redaction.py` — `redact_url` strips passwords,
  password-only userinfo, and bare usernames while leaving
  credential-free URLs untouched.

## Follow-ups

- Extend isolation into the synthesizer and verifier prompts (they
  read `EvidenceClaim.source_text` and paper analyses; both are
  vectors even with the reader defended).
- Default `enable_prompt_isolation` on once Sprint 4 baseline
  numbers exist with it enabled.
- Structured logging / metrics on sanitization drops so we can see
  how often the filter fires in production.
- Content-classifier-based rejection at ingest (an extra Claude
  call per paper; scope for Sprint 5+ if the deployment model
  justifies the cost).
- Atomic-write PDF cache (write to `.tmp` sibling, rename on
  completion).
- Role-based access on `ApiKeyPrincipal`, so `admin_migrate`'s
  actions can eventually be driven through an authenticated
  endpoint instead of shell access to a worker (ADR 0039
  follow-up).
- Single-statement `DELETE ... WHERE principal_key_id=%s` to
  collapse the get+delete round-trip on `DELETE /conversations`.
- Lua-scripted `check_and_record` for the Redis rate limiter if
  the boundary race becomes observable (ADR 0037 follow-up).
- Expose `RedisJobStore.client` as a public property to remove
  the `_client` coupling in `create_app` and `/healthz`
  (ADR 0037 follow-up).
- Next.js proxy route that injects `X-API-Key` server-side so the
  web UI works under `ENABLE_API_AUTH=true` (ADR 0042 known
  limit).
- Request body-size cap as an outermost ASGI middleware — today
  the full body is buffered before auth runs (ADR 0042 deferred).
- Rate-limit `POST /conversations` and cap per-principal
  conversation counts (only `/research` is throttled today).
- Derive the stored owner from the secret (stable `owner_id`)
  instead of the mutable display name — removes the rename/reuse
  hazard structurally; needs a row migration (ADR 0042 interim:
  duplicate-name rejection + permanence rule).
- `/readyz` with 503-on-dependency-failure semantics for
  orchestrators that want dependency-gated routing (`/healthz`
  deliberately stays 200 — ADR 0042).
- Cache purge command (`--older-than-days`) now that the
  `created_at` indexes exist to support it (ADR 0042).
