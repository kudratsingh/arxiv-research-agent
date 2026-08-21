# Roadmap

Prioritized sprint-by-sprint plan. Ordered by (impact × unblocks-later-work) / effort.

## Sprint 1 (~2 weeks) — Make it observable and testable — **DONE**

- [x] Structured logging + `run_id` propagation through `ResearchState`  (PR #18)
- [x] OpenTelemetry tracing (Sprint 1 finish PR, off by default)
- [x] Per-run cost tracking (tokens + USD, per-model breakdown, in `summary.jsonl`)
- [x] Retry/backoff + timeouts on all external calls (Anthropic SDK-native + `urllib3.Retry` for arXiv/PDF)
- [x] LangGraph checkpointing (`SqliteSaver`, on by default, `.cache/checkpoints.sqlite`)
- [x] `pydantic-settings` for typed config (frozen, validated, 20+ fields)
- [x] Golden query dataset (20 queries across 12+ domains — was 10, expanded in Sprint 1 finish)
- [x] Basic eval harness: retrieval recall + citation accuracy + completeness + faithfulness
- [x] Nightly eval CI with regression detection + threshold-driven failure

**Sprint 1 accomplishment**: 20 merged PRs, 12 ADRs, 262 tests, four LLM-judged metrics with a working regression differ. The measurement substrate is in place — everything from here on ships with a "did it help?" number.

## Sprint 2 (~2 weeks) — Go agentic (loop engineering)

Reframed based on the outside review (recorded in
[`05-agentic-upgrade-plan.md`](05-agentic-upgrade-plan.md)). The FastAPI /
Docker / paper-cache items originally scoped here move to Sprint 3 —
loop engineering is a bigger interview-signal win and the eval harness
built in Sprint 1 is what makes measuring the loop upgrade possible.

- Freeze a baseline eval run (3 repeats, same commit) as the
  before-picture we'll compare the supervisor loop against.
- Extend `regression_diff` `METRIC_FIELDS` with `iterations`,
  `llm_calls`, and `cost_usd` so the harness catches loop-induced
  cost creep.
- `src/agents/supervisor.py`: single-LLM-call decider with a strict
  enum action space (`plan | search | read | verify | synthesize |
  critique | stop`). Behind `settings.enable_supervisor: bool = False`.
  Fixed pipeline stays as the default. **DONE — ADR 0014.**
- `src/agents/verifier.py`: promote ADR 0007's faithfulness judge
  into an in-loop node. Adds `verify` to the supervisor's action
  space; emits `verified / unsupported_claims / missing_evidence /
  recommended_action`. Behind `settings.enable_verifier: bool =
  False`, independent of `enable_supervisor` so the two features can
  be A/B'd separately against the Sprint 1 baseline. **DONE — ADR
  0015.**
- `src/graph/state.py`: `EvidenceClaim` TypedDict with
  `source_text` + `section` + `relevance_score` fields so verifier
  judges against chunks, not abstracts. Reader emits claims under
  `settings.enable_evidence_store`; verifier picks its dossier at
  call time. **DONE (5a) — ADR 0016.**
- Synthesizer prefers `state.evidence` over `paper_analyses` when
  populated; grounded prompt forbids filling gaps from abstracts.
  Same flag as 5a. Report output shape unchanged so downstream
  metrics keep working. **DONE (5b) — ADR 0017.**
- `ResearchState` extensions: `next_action`, `tool_history`,
  `open_questions`, `evidence`, `stop_reason`,
  `cost_budget_remaining`, `iteration_count_per_tool`.
- Budget enforcement: `max_cost_usd`, `max_search_rounds`,
  `max_reader_rounds` become supervisor stop conditions with
  recorded `stop_reason`.
- Prompt-injection guardrails on the reader — becomes an
  agent-control risk once routing depends on PDF content.

## Sprint 3 (~2 weeks) — Recovery actions + retrieval iteration

- `src/agents/query_refiner.py`: rewrites failed search queries
  using critic feedback + evidence gaps. Enables the supervisor's
  "search again" branch to actually try something different.
  **DONE — moved forward into Sprint 2 (item 6) — ADR 0018.**
- Reader requests more chunks: when analysis flags missing context,
  the reader emits `request_more_sections: [...]` and the supervisor
  can re-invoke it with a narrower brief.
- Semantic Scholar adapter + citation-graph traversal. **DONE — ADR
  0023.** Search agent walks the top-K arXiv seeds and unions their
  S2 references before the final ranking. One-hop only — forward
  citations and multi-hop traversal are deferred.
- Claude prompt caching for paper-corpus system messages. **DONE —
  ADR 0022.** Applied to every agent's system prompt via a single
  `enable_prompt_caching` flag; reader / supervisor drive the hit
  rate. Cost accumulator gains cache-read + cache-creation buckets
  so `summary.jsonl` reflects real caching savings.
- Cost-aware model routing: Haiku for extraction, Sonnet for
  synthesis, Opus for critic. **DONE — ADR 0021.** Per-agent config
  fields ship in this PR; recommended mapping documented; defaults
  unchanged until paired-diff eval runs confirm quality holds.

## Sprint 4 (~2 weeks) — Make it deployable

- FastAPI wrapper with an async job model.
- Streaming endpoint via SSE.
- Docker + docker-compose (app, Redis, Postgres).
- GitHub Actions CI for unit + integration (lint, mypy, tests,
  smoke query on mock papers).
- Paper cache moved from local `.cache/pdfs/` to Postgres + persisted
  embeddings (production-scale mandate follow-up on ADR 0002).

## Sprint 5 (~2 weeks) — Ship a real product surface

- Minimal web UI (Next.js or Streamlit) with streaming.
- Human-in-the-loop breakpoint after supervisor's plan step.
- Multi-format export (PDF, DOCX).
- Follow-up conversation mode.
- Slack bot (optional).

## Sprint 6+ — Enterprise moat

- Private corpus / BYO PDF.
- Multi-tenancy + RBAC + SSO.
- Bedrock / Vertex adapters.
- Reproducibility scoring, benchmark extraction.
- Skills registry (research playbooks) — see
  [`05-agentic-upgrade-plan.md`](05-agentic-upgrade-plan.md); deferred
  because it multiplies eval surface without proving core loop
  quality first.
- MCP adapter — expose `search_arxiv` / `parse_pdf` /
  `store_evidence` / `run_eval` as MCP tools.

## Log

<!-- Append entries here as sprints complete or plans change. -->

- _2026-07-05_ — Roadmap drafted. No sprints started yet.
- _2026-07-07_ — Sprint 1 done. 20 PRs, 12 ADRs, 262 tests, four eval
  metrics live, nightly CI catching regressions. Reordered Sprint 2:
  loop engineering (supervisor + verifier + evidence store) ahead of
  the deployment / infra items originally scoped there. Rationale in
  [`05-agentic-upgrade-plan.md`](05-agentic-upgrade-plan.md).
- _2026-07-13_ — Safety-hardening bundle (ADR 0033). Post-Sprint-5
  audit surfaced a cluster of production-blocking defects: no auth on
  any route, no per-run cost cap on the fixed-DAG path, arXiv on
  http://, unbounded PDF download, cross-turn prompt-injection via
  `prior_context`. All closed in one bundled PR behind the existing
  `enable_prompt_isolation` / new `enable_api_auth` flags. Deferred
  as follow-ups: per-principal store scoping, Redis-backed rate
  limiter, `SqliteSaver` → `PostgresSaver` (ADR 0013 revisit),
  cross-worker SSE via Redis pub/sub (ADR 0027 revisit), model-
  routing defaults (ADR 0021 revisit).
- _2026-07-13_ — Postgres checkpointer + cross-worker HITL (ADR
  0034). Closes crit-1 (per-request `SqliteSaver` leak) by
  compiling the workflow once at app startup and releasing the
  checkpointer's `ExitStack` on shutdown. Closes crit-2
  (RedisJobStore HITL never wakes runner on a different worker) by
  adding `publish_remote_resume` + `watch_for_remote_resume` on
  `hitl:resume:{job_id}` pub/sub. Revisits ADR 0013 and ADR 0027.
  Follow-ups remaining: SSE cross-worker via pub/sub, job redriver
  on restart, per-principal store scoping, model-routing defaults.
- _2026-07-13_ — Cross-worker SSE via Redis pub/sub (ADR 0035).
  Ports the ADR-0034 HITL pattern to node events on
  `events:{job_id}`. Runner + stream endpoint bypass the local
  `event_queue` when the store advertises pub/sub, so a stream
  request landing on a different worker than the runner still
  receives every frame + the terminal close. Removes the sticky-
  routing requirement documented in ADR 0027. Remaining follow-
  ups: job redriver on restart, per-principal store scoping,
  model-routing defaults, MiniLM → bge-small retrieval swap.
- _2026-07-13_ — Per-principal store scoping (ADR 0036). Follows
  ADR 0033: `principal_key_id` on both Job and Conversation;
  cross-principal reads/deletes return 404 (not 403);
  `list(principal_key_id=...)` pushes the filter into SQL for
  the Postgres store. Legacy NULL-owner rows are invisible
  under auth-on; documented as an admin-cleanup follow-up.
  Remaining follow-ups: Redis-backed rate limiter, hot-reloadable
  keystore, job redriver on restart, model-routing defaults,
  MiniLM → bge-small retrieval swap, SSE heartbeat rewrite.
- _2026-07-14_ — Redis rate limiter + hot-reloadable keystore (ADR
  0037). `RateLimiter` becomes a Protocol; `RedisRateLimiter`
  uses a shared ZSET so the counter is correct across API workers
  (compose sets `RATE_LIMIT_BACKEND=redis`). `KeystoreReloader`
  polls `settings.api_keys_file` mtime and swaps
  `app.state.api_keys` atomically — key rotation without restart.
  `enforce_rate_limit` now async. Remaining follow-ups: job
  redriver on restart, model-routing defaults, MiniLM →
  bge-small retrieval swap, SSE heartbeat rewrite, admin cleanup
  migration for legacy NULL-owner rows.
- _2026-08-20_ — Admin CLI for legacy NULL-owner rows (ADR 0039).
  Closes the last ADR 0036 follow-up. Rows written before
  per-principal scoping carry `principal_key_id = NULL` and are
  invisible to every principal under auth-on — not leaked, but not
  reachable either. `make admin-migrate` reports, assigns, or
  deletes them; an operator CLI rather than an automatic migration,
  because ADR 0036's reason for rejecting auto-assignment still
  holds (a wrong owner turns an access problem into a disclosure
  problem). Dry-run by default. Four correctness details that each
  took real thought: `assign` validates the target key against the
  live keystore, Redis rewrites preserve TTL via `PTTL`,
  availability is decided by which store is *selected* rather than
  by whether `postgres_url` happens to be set, and `delete` logs
  one record per destroyed row so an incident review can answer
  "was mine one of them?". Fixed alongside: compose never set
  `CONVERSATION_STORE` despite the setting's own description
  claiming it did, so the reference deployment ran conversations
  in-memory against a live Postgres — losing them on restart and
  404ing across workers. Remaining follow-ups: role-based access on
  `ApiKeyPrincipal` so these actions could move behind an
  authenticated endpoint, and a live-Postgres test for the SQL.
- _2026-08-20_ — Job redriver + SSE stream rewrite (ADR 0038). Two
  ends of one failure. `RedisJobStore.update` TTLs only terminal
  rows, so a worker dying mid-job left it `running` forever — and
  the SSE stream watching that job hung waiting for a terminal
  frame nobody would publish. Worker leases (`joblease:{job_id}`,
  owner-checked CAS) make "orphaned" distinguishable from "alive on
  another worker", so a rolling restart no longer reaps healthy
  work; the startup sweep takes a cluster-wide `redrive:lock`,
  reclaims leaseless non-terminal rows, and publishes the terminal
  frame that unhangs their streams. The lease is taken *before* the
  semaphore — jobs queued as `pending` are alive too. On the stream
  side, the old heartbeat race cancelled the event reader while it
  was suspended inside the async generator, running the generator's
  `finally` and killing the stream silently after the first quiet
  interval — i.e. on any workflow with a node slower than 15s. Loop
  extracted from the route into a testable `sse_event_stream()`,
  one long-lived read task, immediate keepalive, and an
  `api_sse_max_duration_sec` deadline emitting `stream_timeout`.
  Also closed a leaked pub/sub connection per disconnected client
  (Starlette never `aclose()`s a body iterator). A follow-up audit
  found four more against this code — stale-snapshot reclaim
  destroying `job.result`, a leaseless run after a Redis blip, an
  unenforced lease invariant, and SSE contract drift — all closed
  before merge. Remaining follow-ups: periodic (not just startup)
  sweep, pipelined batch claim, real-Redis coverage for the CAS
  abort path, ADR 0035 subscribe TOCTOU, `stream_timeout` handling
  in the web UI.
- _2026-08-20_ — Eval cost accounting + regression-gate accuracy
  (ADR 0044). `PRICES_USD_PER_MILLION` re-verified against
  published Anthropic pricing (Opus 4.7 was 3x high, Haiku 4.5
  20% low; current-generation ids added, `PRICES_LAST_VERIFIED`
  tripwire, coverage test over config model defaults). Nightly
  regression gate split by metric class: score metrics keep the
  ADR 0010 epsilon; `iterations`/`llm_calls`/`cost_usd` now need
  a per-metric absolute floor AND relative rise, so +1 call or a
  penny wiggle can't fail the nightly. Statistics limits
  documented in docs/eval.md. Remaining follow-ups:
  prices-in-settings, 3-repeat baseline to re-derive thresholds
  from measured spread.
- _2026-08-20_ — Config strictness + audit coverage gaps (ADR 0046).
  Every enum-valued settings field (`job_store`,
  `conversation_store`, `checkpoint_backend`, `rate_limit_backend`,
  `paper_cache`, `embedding_cache`, `log_level`) becomes a
  `Literal[...]` so an unrecognized env value fails at settings
  load with the field named, instead of silently selecting the
  downstream fallback backend. Closes five audit-flagged test
  gaps with mutation-checked behaviour tests: HTTP-level 429 on
  the submit route, route-level job ownership (principal A's job
  is 404 for B on GET/stream/review/export), `run_job`'s
  cost-cap + timeout handlers, the terminal SSE frame arriving
  over Redis pub/sub from a real `run_job`, and the hot-reload
  keystore + CORS wiring through `create_app`.
- _2026-08-20_ — Conversation store hardening (ADR 0043). Audit
  remediation for the conversation layer: `init_schema()` moves
  inside the `to_thread` closures so pool open + DDL never block
  the event loop; `append_job` serializes on the parent row
  (`FOR UPDATE`) with single-statement ordinal allocation and an
  ERROR log before any exception propagates past the store;
  `GET /conversations` gains limit/offset pagination (default 50,
  cap 200) pushed into SQL and composed with ADR 0036 scoping;
  delete carries ownership inline in one DELETE statement,
  closing that ADR's follow-up; `POST /conversations` now draws
  from the per-key hourly rate-limit budget. Remaining
  follow-ups: composite `(principal_key_id, updated_at DESC)`
  index, dedicated conversation-create limit + per-principal
  conversation ceiling, keyset cursor if deep paging appears.
- _2026-08-20_ — API guardrails + deploy hygiene (ADR 0042), from
  the audit remediation. Bounds the HITL `Plan` lists (20 items x
  500 chars — an unbounded revise pinned uncancellable executor
  threads and unbounded arXiv traffic); compares API keys as bytes
  (non-ASCII `X-API-Key` was an unauthenticated 500) and rejects
  duplicate principal names; `/healthz` pings Redis + Postgres
  under 2s timeouts, reports `ok`/`degraded` per dependency, and
  derives `active_jobs` from the worker's task set (was a constant
  0 under the Redis store); resume-publish failures on the review
  endpoint log at ERROR with the job_id instead of vanishing into
  `contextlib.suppress`; uvicorn gets `timeout_graceful_shutdown`
  (set in serve.py, which the compose command now boots, with
  `stop_grace_period` above it) so SIGTERM reaches the lifespan
  cleanup; `redact_url()` keeps connection-
  string credentials out of the JSON log stream; compose gains the
  CORS allowlist that makes the browser demo work at all plus
  `ENABLE_API_AUTH`/`API_KEYS` pass-through with the auth-on recipe
  in docs/security.md. Deferred, tracked there: body-size cap,
  `/readyz`, conversation rate limit, owner-id migration, cache
  purge command, web-UI key proxy.
- _2026-08-20_ — Retrieval and degradation honesty (ADR 0041),
  from the audit remediation. Mock papers now served only under
  `use_mock_data`; an empty live search raises
  `ArxivUnavailableError` / `NoPapersFoundError` instead of
  fabricating sources. Cache READ paths degrade to recompute
  (closing the ADR 0028 gap), one malformed LLM response degrades
  one paper / triggers one synthesizer retry instead of failing
  the run, S2 lookups strip the arXiv version suffix (enrichment
  was a silent 100% no-op), dedup keys canonicalized across
  sources, PDF fetches get an SSRF destination guard with per-hop
  redirect validation. Remaining follow-ups: IP-pinning fetch
  adapter for DNS rebinding, model-weights bake + readiness
  probe, per-node degradation counts on the job record.
- _2026-08-20_ — Supply-chain hardening (ADR 0045). Bounded version
  ranges (floors verified installable on py3.14, caps < next major)
  + committed `requirements-lock.txt`; CI installs the lock so the
  tested and gated sets are identical. Explicit `src` packaging,
  lazy PEP 562 `src.api` re-exports (import of a light submodule:
  3.52 s → 0.06 s), web stack to Next 15.5 / React 19 / Node 22 /
  vitest 4, PyMuPDF AGPL dual-license posture recorded (license
  choice deliberately left to the owner). Remaining follow-ups:
  hashed cross-platform lock, Next 16 + eslint 9 migration,
  Dependabot + pip-audit/npm-audit CI gates, license decision.
- _2026-08-20_ — Documentation drift cleanup (audit remediation,
  docs-only). The audit's maintainability lane found the top-level
  index still described the Sprint-3 repo, `docs/README.md` pointed
  at files that didn't exist, and `docs/testing.md` described a
  three-directory layout and cassette e2e tier that were never
  built — with the `make test` / `pytest -m unit` trap hiding most
  of the suite from anyone who trusted it. Rewrote
  `CLAUDE-Agent-Proj-1.md` against the actual tree (Sprints 1-5 +
  hardening chain, ADRs 0001-0037, ~800 tests, Docs Map); wrote
  `docs/architecture.md` (workflow shapes, API layer, storage
  matrix) from the code; rewrote `docs/testing.md` to describe the
  flat marker-based reality, flag the Makefile trap, and label the
  e2e cassette tier explicitly as planned-not-built; added the
  missing `docs/agents/planner.md` / `search.md` / `critic.md` and
  de-drifted the five existing agent pages (landed follow-ups
  unmarked as pending, settings-vs-constants, test counts). No ADR —
  no decision changed; docs now match `main`.
- _2026-08-20_ — Async checkpointer + runner correctness (ADR
  0040). The audit's headline: the HTTP research path had never
  run a node. `astream` awaits the checkpointer's async surface,
  and both shipped backends compiled the sync savers — instant
  `NotImplementedError` on every job — while the Dockerfile CMD's
  `--log-config /dev/null` crashed uvicorn before binding and the
  Redis store's `asdict` serializer 500'd every HITL review by
  deep-copying a live Event waiter. `build_workflow` gains
  `async_checkpointer=True` (AsyncSqliteSaver / AsyncPostgresSaver
  on a reconnecting `psycopg_pool` pool; CLI + eval keep the sync
  default untouched); the runner goes `aget_state` /
  `aupdate_state`, resumes interrupts in a bounded loop (the
  re-armed planner interrupt no longer truncates re-planned jobs),
  and reads the final state from the checkpoint instead of a
  trailing `invoke` that silently doubled every LLM call. Terminal
  store writes retry + absorb, prior-context failures degrade
  instead of wedging jobs, `_local` evicts on terminal, terminal →
  different-terminal overwrites are refused, and the in-memory
  store finally gets its retention sweep. New
  `test_api_smoke_e2e.py` boots the production wiring end-to-end
  (verified failing on the pre-fix base). Remaining follow-ups:
  timeout path still abandons the node thread (needs a bounded
  executor + cancel token), `ConversationStore.update_title`,
  redriver-side CAS on `_fail_orphan`.
- _2026-08-20_ — Redriver CAS + the store edges around it (ADR
  0048), finishing the recorded follow-ups of ADRs 0038 and 0040.
  Three of them shared one root: a read and a write that were not
  one step. The sweep's re-read and `update`'s terminal-transition
  guard both narrowed the reclaim race without closing it — a job
  finishing in the gap still had its `succeeded` row, report and
  all, replaced by `failed/orphaned`.
  `RedisJobStore.update_if_status` folds the comparison and the
  write into one WATCH/MULTI/EXEC; `_fail_orphan` gates *both* the
  store write and the `job_failed` publish on it landing,
  counting a lost CAS as
  `skipped_live`. The refused-overwrite half moved to
  `publish_event`, which now drops a terminal frame that
  contradicts the persisted row — no client sees `job_completed`
  after `job_failed` — chosen over a `-> None` Protocol change or
  an exception `_persist_terminal` would have reported as data
  loss. Also: `_local` eviction into a `finally` so a Redis outage
  cannot grow worker memory job by job; `scan_jobs` proves
  terminality from the retention TTL and skips those keys before
  the MGET, so a boot over a keyspace of finished jobs transfers
  integers instead of reports; `redrive:lock` TTL 120s → 30s so a
  worker killed mid-sweep stops locking out its own restart (the
  lock is a de-dup optimization, not the safety mechanism — the
  per-job `SET NX` claim is); `ConversationStore.update_title` on
  the Protocol and both impls, so auto-titling stops being a no-op
  against a detached Postgres row; and the SSE deadline branch
  flushes a frame the read task already produced, skipping
  `stream_timeout` when that frame is terminal. ADR 0038's claim
  that the `WatchError` abort path is untestable under `fakeredis`
  is wrong on 2.36.2 and is corrected in ADR 0048: an interloping
  client covers the abort branch for the lease CAS and the reclaim
  CAS, directly and through a real sweep. Twelve mutants planted
  against the new guards, all caught. Remaining follow-ups: the
  runner's `_append_to_conversation` still mutates the fetched
  conversation instead of calling `update_title` (one line, store
  side ready), `_requeue`'s write is still a plain `update`, and
  the periodic redrive sweep is still unbuilt.
- _2026-08-20_ — Bounded node executor + cooperative cancellation
  (ADR 0047), closing the last open P1 from the audit and the
  follow-up ADR 0040 left behind. `asyncio.wait_for` cancelled the
  coroutine awaiting a graph node, never the node's thread —
  LangGraph coerces sync nodes onto the event loop's *default* pool
  with a hard-coded `None` executor — so a timed-out job released
  its semaphore permit while the zombie thread kept calling Claude
  for a job already marked `failed`, past `max_cost_usd`'s
  enforcement point, on a non-daemon thread that held SIGTERM open.
  Nodes now run on a lifespan-owned `ThreadPoolExecutor` sized to
  `api_max_concurrent_jobs` (the async build registers an async
  wrapper that does the dispatch itself; the sync CLI / eval build
  is untouched), a per-job `CancelToken` rides a ContextVar into
  `src/llm.py` and the reader's per-paper fan-out, and the runner
  holds the permit across a bounded drain
  (`api_job_drain_timeout_sec`, default 30s) after emitting the
  terminal frame — so the client is released immediately but the
  concurrency ceiling is not. Threads the drain gives up on are
  logged by name and stay in `/healthz`'s `active_jobs` (broken out
  as `abandoned_node_threads`) until they return. Remaining
  follow-ups: async agents on `AsyncAnthropic` (would replace
  cooperative cancellation with the real thing), cancel checks
  inside the synthesizer / verifier loops, `abandoned_node_threads`
  as a metric rather than a health field, and a
  `POST /research/{id}/cancel` endpoint now that the machinery
  exists.
- _2026-08-20_ — OpenTelemetry metrics (ADR 0049), closing the
  audit's last observability P2 and ADR 0047's
  `abandoned_node_threads` follow-up. The service had three
  telemetry signals and none of them was a metric: logs answer "why
  did this one request do that", traces answer "where did this run
  spend its time", and the per-run cost accumulator dies with the
  run — so "how many jobs are failing right now", "what is the p95
  job duration" and "are we near the concurrency ceiling" were all
  grep-and-count. Seven instruments now live in
  `src/observability/metrics.py` on the OTel metrics API that ships
  in the already-pinned `opentelemetry-sdk`; `prometheus_client`
  would have meant a second telemetry stack, a second exporter and a
  second configuration surface for a repo that already runs an OTLP
  collector for spans. Gated behind `enable_metrics` and sharing
  tracing's `otel_exporter_endpoint`, so both signals are two
  booleans and one URL. Every record point is an *existing* choke
  point rather than a new call site: `_persist_terminal` (the one
  function all seven of `run_job`'s terminal branches pass through,
  recorded before the write so a wedged store cannot also make the
  fleet look idle), `record_llm_call` (every LLM call site in the
  repo, recorded unconditionally — a call outside a run still spent
  money), and `_raise_429` (both limiter backends, which grew a
  keyword-only `backend` the counter needs and the response does
  not). The two concurrency gauges are *observable* and read the
  same accounting `/healthz` reports — this worker's task set plus
  `abandoned_node_count()` — through callables the lifespan
  supplies, so the gauge and the health endpoint cannot drift into
  two disagreeing numbers, and `src/observability/` stays free of
  any knowledge of the API layer. Cardinality is deliberate:
  `error_type` normalises to `"none"` so every series has one
  attribute shape, rejections are labelled by backend and never by
  `key_id`, and duration is bucketed 5s..3600s because the SDK's
  sub-second defaults put every real research job in the overflow
  bucket. Flag off means no provider, no instruments and one `None`
  check per record point. Twelve mutants planted against the
  terminal-record, cost-record, 429-record and gauge points, all
  caught. Remaining follow-ups: no instrument for queue *wait* time
  (the leading indicator `research_active_jobs` only shows once
  saturated), cache hit ratios and outbound arXiv / Semantic Scholar
  latency uninstrumented, exemplars linking a slow duration to its
  trace unused, and neither the compose stack nor the deploy docs
  ship a collector service — the operator wires their own from the
  snippet in `docs/development.md`.

- _2026-08-20_ — API / web / container pre-flight (ADR 0053), from
  walking the path a first-time operator takes rather than reading
  modules: `docker compose up`, open the UI, type a query. Five
  breaks, none of which any test could see because none drove the
  *sequence*. **P0**: the landing page created a conversation,
  `POST`ed `/research`, threw the returned `job_id` away and pushed
  `/c/{id}` — and nothing downstream could recover it, because the
  thread reads only `useParams` and a `pending_review` job never
  appears in `GET /conversations/{id}` (the runner appends on
  success only). With HITL on by default the run parked, published
  `plan_ready` to an empty channel, and died 30 minutes later on the
  timeout: one billed planner call, one blank page. The id now
  travels as `?job=`, the thread `attach`es to it through the same
  stream reader `submit` uses, and the thread `router.replace`s the
  URL for jobs it starts itself — so the URL always names the job in
  flight and a reload rejoins it instead of buying a second one. The
  `attach` guard keys on the live `EventSource` rather than a "have
  attached" flag, which is what makes StrictMode's mount → cleanup →
  mount end with exactly one stream instead of zero. **P2s**:
  `plan_ready` is now replayed on attach for a job parked in
  `pending_review` (published once, and neither transport keeps a
  backlog — pub/sub drops messages with no subscriber, the in-memory
  queue is single-consumer — so every reconnect during review used
  to get heartbeats until the HITL timeout), guarded on status *and*
  a populated plan so a torn write can't invite approval of an empty
  plan and a stale plan on a `running` job can't re-open a settled
  review; the image installs `requirements-lock.txt` and then the
  project `--no-deps`, so the container finally runs the set CI
  tests instead of a fresh resolution of pyproject's `< next major`
  ranges; MiniLM is baked at build time under an `HF_HOME` both
  stages share, ending the ~90MB download that used to run inside
  the first job's own timeout budget while `/healthz` reported `ok`;
  and the redrive sweep now repeats on `job_redrive_interval_sec`
  with a quarter-interval jitter, because a container SIGKILLed and
  restarted inside `job_lease_ttl_sec` comes back to its own live
  lease, which the boot sweep correctly refuses to touch and no
  later sweep ever revisited. **P3s**: `/healthz` logs one WARNING
  per transition into degraded and one INFO on recovery, naming the
  dependency and carrying only the exception type (the probe text
  can contain a credentialed URL) — edges, not the ~17k lines a
  15-second probe would produce over a weekend outage; and the
  README's copy-paste curl example no longer stalls 30 minutes on a
  review nobody is going to answer. Mutation-checked: the landing
  page's discarded id, the missing adopt, the `attach` guard, the
  URL sync, the replay and its status guard, the jitter, the store
  capability guard, the shutdown cancel, the settings-driven
  interval, the sweep timeout, and all five health-logging edges —
  every mutant killed. The two build-time fixes can't be asserted by
  running the app, so `tests/test_container_contract.py` pins their
  coupling to the source instead — the bake regex against
  `MODEL_NAME`, one `HF_HOME` across both stages, the lock install,
  and the absence of a compose volume over the cache path — and the
  image was then actually built and run: `docker run --network none
  -e HF_HUB_OFFLINE=1 … encode_texts([...])` returns a `(1, 384)`
  vector, which is the bake proving itself with no network at all.
  That build also produced the first honest number for the image:
  **5.88GB**, of which the baked weights are 88MB (1.5%) and
  `site-packages/nvidia/*` is 2.9GB — the lock is frozen on macOS
  (ADR 0045's recorded limit), so pip resolves torch's Linux extras
  at install time and picks the CUDA build for a service whose
  `embedding_device` defaults to `"cpu"`. Pre-existing (`pip install
  .` resolved the same graph) but now measured, so it is a follow-up
  instead of folklore. Remaining
  follow-ups: pin the CPU-only torch build so the image stops
  carrying 2.9GB of CUDA wheels; split the lockfile into runtime and
  dev sets so the image stops shipping pytest/mypy/ruff (parity
  chosen over size, deliberately); list in-flight jobs on `GET /conversations/{id}` so
  a thread can adopt without the URL; the web UI still cannot send
  `X-API-Key`, so the shipped demo remains auth-off (ADR 0042); and
  no readiness probe distinct from `/healthz` — explicitly out of
  scope here.
