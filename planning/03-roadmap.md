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
