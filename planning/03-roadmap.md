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

### Frontend production revamp — gated follow-up

- [x] Gate 1 discovery: product/domain/API/route/state/quality inventory,
  no-cost browser baseline, current-source UX/technology research, skill
  audit, and three preliminary visual directions.
- [x] Gate 1 human approval (2026-08-28): Direction A (Evidence Workbench),
  frozen-backend boundary, and first vertical slice approved; the private
  shared-workspace assumption was **rejected as the end state** — real
  end-user multi-tenancy is tracked as a separate, own-gated backend
  workstream (MT-01 in `docs/revamp/STATUS.md`), not part of this revamp.
- [x] Gate 2 approval after Phases 2–4 (2026-08-28, under the user's
  standing delegation): design brief/tokens (PR #71), architecture +
  migration (PR #70), work orders + dependency graph (PR #72) — all
  independently reviewed (reject → corrected → approve) and merged on
  green CI; the sixteen rulings are `docs/revamp/DECISIONS.md` D-010.
- [ ] Gate 3 approval after the foundation and one complete vertical slice
  are merged: Storybook/state evidence, end-to-end behavior, and tests.
- [ ] Gate 4 approval after quality hardening and documentation: before/after
  quality report, operational docs, rollout plan, and ship decision.

Gate 1 evidence is indexed from [`docs/revamp/STATUS.md`](../docs/revamp/STATUS.md).
Product implementation remains intentionally blocked until Gate 1 is approved.

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

- _2026-08-21_ — Eval-runner hardening (ADR 0050), ahead of the first
  live campaign. The harness could not hold onto work it had already
  paid for. `_run_and_score` guarded the workflow invocation and
  computed the four metrics *outside* that guard, so one 529 on query
  12's faithfulness judge walked out through a loop that caught only
  `KeyboardInterrupt`: query 12's finished workflow output was never
  appended, queries 13-20 never ran, and both ADR 0008's explicit
  per-query isolation decision and the function's own "Never raises"
  docstring were violated in one line. Metrics are now scored one at a
  time inside `except Exception` — a failed judge lands as `None` with
  its message on a `metrics_error` field while `state`, `costs` and
  `elapsed_sec` survive, because the workflow output is the expensive
  artifact and the score is the cheap one. `reset_run_id` moved into
  `finally`, where it stops leaking a dead query's run_id into the next
  query's logs. Output is written as it is produced —
  `queries/<id>.json` plus a flushed `summary.jsonl` line per query,
  `summary.md` rebuilt from disk at the end — so a kill loses at most
  the in-flight query, and `--resume` re-enters a campaign without
  re-paying for what finished. SIGTERM is mapped onto
  `KeyboardInterrupt` so `docker stop` and an Actions cancellation take
  the same flushing path Ctrl-C had, and the in-flight record rides out
  on an `EvalInterrupted` rather than being dropped. Cost accounting
  now splits the product from the harness: the record snapshots spend
  before the judges run, so `cost_usd` / `llm_calls` / `elapsed_sec`
  are the workflow's and `judge_cost_usd` / `judge_llm_calls` /
  `scoring_sec` are the rig's, with `total_cost_usd` their sum. The
  name `cost_usd` was kept deliberately: renaming it would have diffed
  as `None` against every existing baseline and silently switched the
  regression gate's cost band off, which is worse than a field whose
  meaning is documented as having narrowed. Three green-while-wrong
  paths closed — an empty `draft_report` is now a `NoReportProduced`
  error instead of a free `citation_accuracy=1.0` / `faithfulness=1.0`
  (and skips two wasted judge calls), reports with zero citations leave
  the README's citation mean with the exclusion and its denominator
  stated under the table, and a query present in the baseline but
  missing from the current run is a regression instead of vanishing
  while the aggregate quietly re-averages over the survivors
  (`--allow-removed` opts a deliberate subset run out). `make eval`
  stopped returning 0 on a total outage: distinct codes for partial
  failure, all-failed, budget stop and interrupt, with the counts on
  the closing line. A populated `--output-dir` is refused without
  `--resume` rather than truncating a prior campaign's records, and
  `--max-budget-usd` stops the batch cleanly between queries against
  accumulated workflow+judge spend (per-call enforcement is ADR 0051's
  choke point, not this one's). The nightly workflow — silently red for
  15+ consecutive nights on an unset secret, dying with a "copy
  .env.example" message that reads like a code bug — now fails fast
  with a message naming the owner action, uploads its artifacts on
  `always()` so a batch that died at query 15 still refreshes the
  baseline the *next* night depends on, installs from
  `requirements-lock.txt` like CI does, and gets the 120 minutes 20
  queries actually need. Fifteen mutants planted across the judge
  guard, the run_id reset, the checkpointer close, the empty-report
  guard, the cost split, the cell escaping, the budget check, the
  output-dir refusal, resume, the exit codes, the interrupt record, the
  incremental write, the removed-query gate, the citation denominator
  and the SIGTERM handler — all caught. Remaining: `summary.md` is
  still end-of-run only, so a SIGKILL leaves it stale beside a current
  `summary.jsonl`; the ceiling cannot stop a query already in flight;
  `--resume` skips errored queries too (delete the record to retry
  one); and the nightly's missing API key is now legible rather than
  fixed.

- _2026-08-21_ — Verification pass on ADR 0050 found one seam the
  hardening itself opened and closed it (decision 10 in the ADR).
  Judge isolation converts an aborted campaign into a `null` metric,
  and both consumers of `summary.jsonl` were averaging over whatever
  survived without saying so: the README could publish
  `Mean faithfulness 0.420` from two runs inside a row headed
  `20 / 20`, and `regression_diff` turned the same nulls into `None`
  deltas, classifying all twenty queries `unchanged` and exiting green
  on a night where eighteen judges failed — the exact shrunken
  denominator decision 6 had just closed one level up, with
  `metrics_error` written by the runner and read by nobody. Neither
  gates now (a flaky judge is a harness fault, not a product
  regression, and ~60 judge calls a night would redden the nightly for
  it), but neither is silent either: the README names any metric whose
  mean covers fewer runs than the count beside it, the diff report
  carries a per-metric `Compared` column plus a header line naming what
  went unscored, and the runner's closing line adds `N partially
  scored`. The workflow-cost caveat also used to ride inside the
  uncited-rows note, so it disappeared on any night where every report
  cited something; it prints unconditionally. Ten more mutants planted
  across the new counting and rendering — all caught.
- _2026-08-20_ — LLM cost enforcement and visibility (ADR 0051),
  closing the pre-flight audit's cost-control cluster before the first
  live campaign. The headline gap: `max_cost_usd` had exactly one
  enforcement point, the API runner's `on_node` callback (ADR 0033), and
  neither path about to spend real money goes through it —
  `src/main.py` and `src/eval/runner.py` both drive the graph with a
  bare `app.invoke(...)`, and the supervisor's independent check is
  dead under the shipped `enable_supervisor=False`. The check now lives
  in `src.llm.call_llm`, the one function every entry point funnels
  through, which fixes the CLI and eval paths and the API's own
  intra-node overshoot in a single edit (the reader fans out up to
  `max_papers` parallel calls inside one node, so a between-nodes check
  can be beaten by a whole node's spend). `CostBudgetExceeded` and the
  cap helper moved to `src/observability/costs.py` so the LLM layer
  raises the exception the runner catches without importing the API
  layer; both are re-bound in `src/api/runner.py` under the names that
  were already public. The between-nodes check stays — the two cannot
  disagree, since they raise the same class from the same accumulator,
  and `on_node` still catches a node that spends outside `call_llm`.
  Second, hitting the ceiling no longer destroys the artifact: the
  draft in the runner's merged state rides out on the exception and
  lands on `job.result`, so a run whose *final* node crossed the cap —
  a complete report, `route_after_critique` already returned `END` —
  is retrievable and exportable instead of being a bill with nothing
  attached. Third, the SDK's retries stopped being invisible:
  `with_raw_response.retries_taken` is the SDK's own count of discarded
  attempts, recorded as `llm_retries_total` and on the `llm_call` line
  next to a measured `latency_ms`, with `llm_upstream_errors_total`
  for the calls that outlive the retry budget — and no second retry
  loop anywhere, so ADR 0009's SDK-native choice stands. ADR 0042's
  blanket demotion of the `anthropic` tree is narrowed to spare
  `anthropic._base_client`'s retry line at INFO. Fourth, the retry
  envelope is clamped from `api_job_timeout_sec`: the SDK applies
  `timeout` per *attempt*, so the shipped 4 retries × 120s bounded one
  logical call at exactly the 600s job timeout — one unlucky call could
  eat a whole job. Attempts get trimmed to 2, never the timeout, since
  a shorter timeout abandons slow-but-healthy generations and
  Anthropic bills those with no `usage` coming back. Fifth, an
  unpriced model warns once per id instead of once per call (hundreds a
  run), and the price-coverage test — which was vacuous, reading
  `field.default` when every routing field defaults to `""` — now
  resolves runtime values through new `resolved_model_ids()` /
  `unpriced_models()` helpers; `claude-fable-5`, `claude-mythos-5` and
  `claude-opus-4-5` added to the table. Sixth, stderr is JSON lines
  again (ML-stack loggers demoted, HF progress-bar env `setdefault`ed)
  and `faulthandler` is armed, so the intermittent MiniLM SIGSEGV
  leaves a traceback rather than exit 139. Plus the lease-path P3s:
  `exc_info` on acquire/refresh failures with first-warns-then-debugs
  volume control, and a `run_id` bound inside the keeper task, which
  `asyncio.create_task` had been snapshotting before `run_job` bound
  one. Sixteen mutants planted, all sixteen caught. Remaining
  follow-ups: `unpriced_models()` at startup as a WARNING; the
  `max_cost_usd` description in `src/config.py` and
  `docs/architecture.md:183` still scope the cap to the API runner; the
  thread-pinning half of the SIGSEGV in `src/tools/embeddings.py`
  (needs a ≥200-run soak, the repro rate is ~4%); a `partial` flag on
  `JobDetail`; streaming the synthesizer so a long generation cannot
  trip the HTTP timeout at all. Retried attempts' token spend stays
  uncapturable in-process — `usage` exists only on a 2xx body, so
  `retries_taken` is a count and Anthropic's billing is the only
  reconciliation.
- _2026-08-20_ — Native-crash containment + data-lifecycle edges (ADR
  0052). The process had been dying with exit 139, a macOS
  crash-reporter dialog and nothing in the logs, because a native
  crash unwinds nothing. Two independent crashes, measured apart. The
  common one is an OpenMP barrier race: torch defaults to one OpenMP
  worker per core, three copies of `libomp.dylib` ship in the venv
  (torch, faiss, scikit-learn), and the reader fans out over five
  threads that each call `model.encode` — a probe with exactly that
  shape segfaults **10/10**, faulting in
  `libomp.dylib::__kmp_suspend_64`. That is not a test-fleet
  phenomenon; it is one process running the reader, which is what
  `make run`, `make eval` and a `POST /research` all do.
  `_get_model` now calls `torch.set_num_threads(1)` before
  constructing the model — in process rather than via
  `OMP_NUM_THREADS`, because the env var only helps callers that go
  through a wrapper setting it and a bare `pytest`, `uvicorn` and
  `python -m src.main` do not — and the probe goes to **0/15**. The
  rarer crash is Apple's Metal driver (`fill_mps_kernel`, ~1/6 even
  with the threads pinned), which is what the device pin is for:
  `_get_model` resolves `settings.embedding_device` (default `cpu`;
  `auto` is the opt-in that restores the library's own pick, and
  carries that residual) and logs the configured device, the bound
  device and the thread count once at construction — the only artifact
  that outlives a SIGSEGV. The four test tiers keep the
  `OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false` prefix as a second
  layer covering faiss's and scikit-learn's libomp copies at import.
  Shipped with the data-lifecycle edges a crash lands on, all from the
  same pre-flight audit. `admin_migrate assign/delete` now exit 2
  under `enable_api_auth=false` unless the operator passes
  `--include-all-auth-off`: with auth off `routes._principal_key_id`
  returns None for every request, so every row ever written has a NULL
  owner and the tool's "legacy NULL-owner rows" predicate selects the
  entire store — and `enable_api_auth` defaults to False, making that
  the *default* posture of the most destructive command in the tree;
  `report` is never refused but now opens with the auth mode and says
  out loud that the counts are the whole store. Two silent store
  failures became records: a job row that will not parse logs
  `job_status_bad_payload` naming the consequence
  (`terminal_transition_guard_bypassed`) while a missing key stays
  quiet, and a refused terminal write carries the result length, the
  first 200 characters, both statuses and the cost — at ERROR when
  what it discarded was a finished `succeeded` report, WARNING when it
  was a `failed` write that lost nothing. `make run` salvages the
  checkpoint on failure: the synthesizer runs before the critic, so a
  late-node failure strands a complete `draft_report` in
  `.cache/checkpoints.sqlite` that no CLI surface could read — it now
  lands in `outputs/<run_id>-recovered.md`, best-effort from inside
  the `except` so it can never mask the real exception, with the
  `thread_id` logged on every failure either way. `make clean` stops
  deleting `.cache/checkpoints.sqlite` (graph state, not a cache,
  including any run paused at the HITL breakpoint); `clean-all` is the
  target that removes it. The CLI's ten-keys-stale third copy of the
  initial `ResearchState` is gone, replaced by
  `initial_research_state` beside the TypedDict it mirrors, with a
  parametrized drift test pinning the API and eval runners' copies
  until they adopt it. The reader's abstract-only degradation is
  audible for the first time — one INFO line per paper naming the
  stage (`no_pdf_url`, `no_text`, `no_chunks`, `no_ranked_chunks`)
  tallied through a ContextVar bound inside each worker thread, a
  `reader_completed` summary carrying `n_abstract_only`, and a
  run-level WARNING past two — as is the embedding cache's write path,
  which was the last bare `contextlib.suppress(Exception)` in the
  cache tier. And `docs/demo.md` stops claiming the mock-data run
  makes no external calls beyond Anthropic: `MOCK_PAPERS` carries real
  `pdf_url`s, so a cold run downloads five real arXiv PDFs; the doc
  now tables the hosts it actually contacts and documents the warm
  `.cache/pdfs` second run as the genuinely Anthropic-only path.
  Mutants planted against the device pin, the reader tally's thread
  binding, the corrupt-payload log, the checkpoint salvage and the
  auth-off gate — all caught. Remaining follow-ups: `faulthandler` +
  process env hygiene land in the observability lane; the API and eval
  runners still hold their own `_initial_state` copies; there is no
  `--no-pdf` switch and no checked-in full-text fixture, so a
  cold-cache offline demo remains impossible; and the salvaged report
  is a partial artifact with no metrics, critique or verification.
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
- _2026-08-21_ — Top-level docs refresh (docs-only, no behavior
  change). What was stale: the README's project-status section ended
  at Sprint 5 and claimed "1,200+ tests" and a nightly e2e tier that
  does not exist; `CLAUDE-Agent-Proj-1.md` indexed ADRs only through
  0037, counted ~800 tests, described `make test` as "~55 tests"
  (the unit-marked subset is now 522/1426 collected), and listed the
  job redriver and admin migration as open follow-ups though both
  landed (ADRs 0038/0039); `planning/README.md`'s status snapshot
  was still Sprint 1 (2026-07-07); `.env.example` held a single
  variable. Now authoritative: README carries the current
  architecture summary (both workflow shapes + the production HTTP
  surface), a security-posture section sourced from
  `docs/security.md`, the eval-runner hardening summary (resume /
  budget / judge isolation) with the results table honestly marked
  pending the first green campaign, the four-service compose
  description, and fresh counts (53 ADRs, 63 merged PRs, 1399
  passed / 27 skipped on the `not e2e` gate);
  `CLAUDE-Agent-Proj-1.md` indexes through ADR 0053 with the three
  post-Sprint-5 waves and the current follow-up list;
  `.env.example` documents the operator-facing settings with
  comments sourced from `src/config.py`; planning files 01/02/04/05/06
  carry dated status notes up top with historical content untouched.
  All numbers in this entry were derived fresh from the tree at the
  time of writing, not copied from prior docs.
- _2026-08-27_ — Hetzner production-boundary closeout (ADR 0054).
  The deployment target is a single Hetzner Cloud VPS, selected by the
  maintainer after comparing the free/paid host options. Local work
  remains non-billable until the exact Console order is approved.
  Closed the three deployment blockers ADR 0053 measured: a generated
  `requirements-runtime-lock.txt` removes the dev-only closure, and
  every Linux architecture installs the locked Torch version from the
  official CPU index; the Linux/arm64 API image falls from 5.88 GB to
  1.70 GB and passes a `--network none` MiniLM encode as
  `torch 2.12.1+cpu`. Next moves to 16.3.3 (zero production npm audit
  findings), and a tested server-only `/api` route injects the API key
  while streaming SSE/exports, so the browser no longer needs either
  CORS or a public secret. Base Compose binds app/web to loopback and
  parameterizes Postgres; the production overlay removes both host
  ports, forces auth/prompt isolation/spend guards, and makes Caddy
  2.11.4 the sole public HTTPS/basic-auth edge. A deployment runbook
  records firewall, DNS, exact-commit deploy/rollback, and backup
  boundaries. Remaining: merge the reviewed PR, provision only after
  explicit Hetzner cost approval, verify TLS/health on the host, then
  separately approve one paid Anthropic end-to-end query.
- _2026-08-28_ — Frontend revamp Gate 2 closed. Three concurrent Opus
  author agents produced the Phase 2–4 package (Evidence Workbench design
  brief + machine-readable tokens, architecture + migration plan, 33
  work orders with a verified dependency graph), plus the separate MT-01
  multi-tenancy proposal (PROPOSED, awaiting the user's own gate). An
  independent package reviewer rejected the first pass (2 Major /
  14 Minor — all corrected pre-merge on the work-orders branch), then
  approved with zero unresolved findings. All four PRs (#69–#72)
  squash-merged on green CI. The sixteen Gate 2 rulings were ratified
  under the user's standing delegation (`docs/revamp/DECISIONS.md`
  D-010). Implementation (EXEC) begins: 26 Gate 3 work orders + 7
  Gate 4, run as a concurrent worktree-agent fleet, merges gated on
  green CI. Cost-bearing actions and MT-01 remain reserved for the user.
- _2026-08-28_ — Frontend revamp Gate 1 closed. The interrupted second-pass
  independent review was re-run by a fresh reviewer and returned APPROVE
  with two minor, non-blocking findings (Lighthouse capture provenance —
  disclosed in the baseline README; Direction C stage-label constraint —
  carried into Phase 2). The human Gate 1 decisions were recorded
  (`docs/revamp/DECISIONS.md` D-009): Direction A (Evidence Workbench),
  frozen backend confirmed, vertical slice approved, and real end-user
  multi-tenancy adopted as the intended end state via a separate own-gated
  backend workstream (MT-01). Next: Phase 2 design brief toward Gate 2.
- _2026-08-28_ — Frontend production-revamp Gate 1 candidate. Completed a
  fresh product/frontend/backend-contract inventory, captured synthetic local
  mobile/desktop Lighthouse and visual evidence with an invalid model key,
  measured current bundles, researched standards/category analogs/current
  tooling, pinned Anthropic's official frontend-design guidance, and prepared
  three backend-feasible directions. No product code, API shape, paid model,
  hosting order, or deployment state changed. The detailed design brief is
  blocked on the human Gate 1 decisions recorded in `docs/revamp/STATUS.md`.
- _2026-08-29_ — Frontend revamp EXEC: Gate 3 implementation set fully
  merged (25/33 work orders, PRs #74–#101; bookkeeping #102). The waves:
  M0 foundation (tokens, typed client, budgets, CI smoke), the M1–M3
  surface wave (primitives → patterns → features), and the quality-gate
  wave — axe gate with `landmark-one-main`/`region` 12→0 and an empty
  allowlist, seeded Playwright harness with a paid-path interceptor,
  route-JS budgets, an 8-job web CI, and the route composition that
  retired the legacy thread UI (CLS 0.000, net route JS −4.2 KB).
  Coordinator rulings under the standing delegation:
  `docs/revamp/DECISIONS.md` D-011/D-012. In flight: the Gate 3
  evidence pack (WO-26), proxy hardening (WO-30), and a
  public-presentation polish (README/diagrams/screenshots, agent docs,
  demo/eval accuracy). Remaining after those: WO-27–29, 31–33 toward
  Gate 4. Reserved for the user: MT-01 approval and anything
  cost-bearing (deploy, paid eval campaign).
