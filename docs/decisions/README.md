# Architecture Decision Records

Every non-trivial design or technical decision in this project gets an
ADR — a short document capturing the context, the decision made, the
alternatives considered, and the consequences. ADRs are written before
or alongside the code that implements them, and are **amended (not
deleted)** when superseded.

## Format

See [`TEMPLATE.md`](TEMPLATE.md). Files are numbered `NNNN-slug.md` and
never renumbered.

## Index

- [0001](0001-use-anthropic-sdk-directly.md) — Use the Anthropic SDK
  directly, not LangChain's wrapper
- [0002](0002-section-aware-chunker.md) — Roll our own section-aware
  chunker over generic markdown splitters
- [0003](0003-chunk-ranker-max-similarity.md) — Rank paper chunks by
  max cosine similarity across sub-questions
- [0004](0004-reader-fulltext-with-abstract-fallback.md) — Reader
  consumes ranked full-text chunks with abstract fallback
- [0005](0005-custom-eval-over-ragas.md) — Roll our own eval pipeline
  instead of adopting Ragas / DeepEval / LangSmith
- [0006](0006-completeness-batched-judge.md) — Score completeness with
  a single batched LLM-as-judge call
- [0007](0007-faithfulness-single-call-abstracts.md) — Score
  faithfulness with a single-call judge over cited abstracts
- [0008](0008-eval-runner-sequential-per-query-isolation.md) — Eval
  runner: sequential runs, per-query error isolation, three-layer
  output
- [0009](0009-anthropic-sdk-native-retry.md) — Use the Anthropic SDK's
  built-in retry over a custom loop or `tenacity`
- [0010](0010-nightly-eval-ci.md) — Nightly eval CI with artifact-based
  baseline and regression diff
- [0011](0011-pydantic-settings-typed-config.md) — Typed configuration
  via `pydantic-settings`
- [0012](0012-observability-core-logging-costs.md) — Observability core:
  stdlib JSON logging, ContextVar run scope, per-run cost tracking
- [0013](0013-sprint-1-finish-retry-checkpoint-tracing-recall.md) —
  Finish Sprint 1: shared HTTP retry, SQLite checkpointing, OTel
  tracing, retrieval recall, expanded benchmark
- [0014](0014-supervisor-loop-behind-flag.md) — Supervisor loop
  behind a settings flag with strict-enum action space
- [0015](0015-verifier-agent-runtime-faithfulness.md) — Verifier
  agent: runtime faithfulness check as a supervisor action
- [0016](0016-evidence-store-source-text-verifier.md) — Evidence
  store: reader emits `EvidenceClaim`, verifier judges against
  `source_text`
- [0017](0017-synthesizer-evidence-swap.md) — Synthesizer prefers
  `EvidenceClaim`s when available
- [0018](0018-query-refiner-recovery-action.md) — Query refiner:
  new `refine_query` supervisor action, fail-closed dedup, flag-gated
- [0019](0019-reader-requests-more-chunks.md) — Reader-requests-more-chunks:
  read-layer recovery, ranker section bias, flag-gated
- [0020](0020-prompt-injection-isolation-reader.md) — Prompt-injection
  isolation on the reader: untrusted-content delimiters, output
  sanitization, jailbreak-marker filter, flag-gated
- [0021](0021-cost-aware-model-routing.md) — Cost-aware model routing:
  per-agent Claude model overrides, recommended Haiku targets
- [0022](0022-anthropic-prompt-caching.md) — Anthropic prompt caching
  for agent system prompts: `cache_system` flag on `call_llm`, cache
  read/write cost tracking, flag-gated
- [0023](0023-semantic-scholar-citation-graph.md) — Semantic Scholar
  adapter + one-hop reference enrichment in the search agent,
  flag-gated
- [0024](0024-pr-ci-lint-mypy-tests.md) — Per-PR CI gate: ruff +
  strict mypy + the pytest suite on every PR and push to `main`
- [0025](0025-fastapi-async-job-model.md) — FastAPI + async job model
  over the sync workflow: `POST /research` returns 202 + `job_id`,
  status polling, bounded concurrency
- [0026](0026-sse-streaming-endpoint.md) — Hand-rolled SSE streaming
  endpoint for live job events
- [0027](0027-docker-compose-redis-job-store.md) — Dockerfile +
  docker-compose stack + RedisJobStore for multi-worker deployment
- [0028](0028-postgres-paper-cache-and-embedding-cache.md) —
  Postgres-backed PaperCache + EmbeddingCache behind pluggable
  settings, disk / no-op defaults preserved
- [0029](0029-nextjs-web-ui.md) — Next.js web UI as a separate
  compose service, tested in CI alongside the Python suite
- [0030](0030-hitl-plan-review.md) — Human-in-the-loop plan review:
  workflow interrupts after the planner; `POST /research/{id}/review`
  approves / edits / cancels
- [0031](0031-multi-format-export.md) — Multi-format report export
  (Markdown, PDF, DOCX) via `GET /research/{id}/export`
- [0032](0032-conversation-mode.md) — Follow-up conversation mode:
  threads group jobs, prior-report chunks retrieved into the
  planner's prompt
- [0033](0033-safety-hardening-bundle.md) — Safety hardening bundle:
  arXiv HTTPS + defusedxml, PDF streaming size cap, tightened cache
  key, runner-level cost cap, planner `prior_context` isolation,
  API-key auth + per-key rate limits + CORS allowlist
- [0034](0034-postgres-checkpointer-and-cross-worker-hitl.md) —
  Pluggable checkpointer backend (Postgres in compose), workflow
  compiled once at app startup, Redis pub/sub for cross-worker
  HITL resume; revisits ADR 0013 and ADR 0027
- [0035](0035-cross-worker-sse-pubsub.md) — Cross-worker SSE
  fan-out via Redis pub/sub on `events:{job_id}`; runner + stream
  endpoint bypass the local queue when the store supports pub/sub.
  Closes the sticky-routing requirement documented in ADR 0027
- [0036](0036-per-principal-store-scoping.md) — Per-principal
  ownership on Job + Conversation: 404 on cross-principal access,
  list filter pushed into SQL, legacy `NULL`-owner rows invisible
  under auth-on. Follows ADR 0033.
- [0037](0037-redis-rate-limiter-and-keystore-reload.md) —
  Pluggable rate limiter (Redis ZSET backend correct across
  workers) + hot-reloadable keystore from a JSON file. Follows
  ADR 0033.
- [0038](0038-job-redriver-and-sse-stream.md) — Worker leases +
  a startup job redriver, so a dead worker's jobs are reconciled
  and their streams unhung instead of stuck `running` forever;
  SSE stream loop rewritten after the old heartbeat race
  cancelled the event reader mid-generator and silently killed
  the stream on the first quiet interval. Follows ADR 0027, 0035.
- [0039](0039-admin-null-owner-migration.md) — Operator CLI
  (`make admin-migrate`) for the legacy `NULL`-owner rows ADR
  0036 left unreachable under auth-on. Dry-run by default;
  validates the target key against the live keystore, preserves
  Redis TTLs on rewrite, and decides availability from the
  selected store rather than a shared URL. Follows ADR 0036.
- [0040](0040-async-checkpointer-and-runner.md) — Async
  checkpointer surface (`AsyncSqliteSaver` / `AsyncPostgresSaver`
  on a reconnecting pool) for the `astream`-driven API runner —
  the sync savers raised `NotImplementedError` before the first
  node, in both shipped configs. Runner resume becomes a bounded
  loop (`interrupt_after` re-arms per planner run), the double-
  executing trailing `invoke` is removed, terminal writes are
  retried + contained, the Redis store stops deep-copying live
  asyncio primitives, and a production-wiring smoke test pins the
  whole path. Revisits ADR 0034; corrects ADR 0030's interrupt
  semantics.
- [0041](0041-retrieval-and-degradation-honesty.md) —
  Retrieval and degradation honesty: mock papers gated behind
  `use_mock_data` only (typed errors for empty live search),
  cache reads degrade to recompute, per-paper reader failure
  containment, parse defense across the agents, S2 version-strip
  + canonical dedup, PDF SSRF guard. Follows ADRs 0004, 0023,
  0028, 0033.
- [0042](0042-api-guardrails-and-deploy-hygiene.md) — API
  guardrails + deploy hygiene: bounded HITL plan lists, bytes-safe
  key comparison, honest dependency-checking `/healthz`, logged
  resume-publish failures, bounded SIGTERM drain, credential
  redaction in logs, compose CORS + bootable auth. Follows
  ADR 0033/0034.
- [0043](0043-conversation-store-hardening.md) — Conversation
  store hardening: schema bootstrap off the event loop, appends
  serialized on the parent row with single-statement ordinal
  allocation, limit/offset pagination on the list endpoint, and
  ownership inline in a one-statement DELETE. Follows ADR 0032
  and ADR 0036.
- [0044](0044-eval-cost-accuracy-and-regression-thresholds.md) —
  Price table re-verified against published Anthropic pricing
  (Opus was 3x high, Haiku 20% low) with a coverage test over
  config model defaults; nightly regression gate split by metric
  class — score epsilon per ADR 0010, two-leg absolute+relative
  bands for counts/dollars. Revisits ADR 0010; follows ADR 0012.
  **Regression-gate half superseded by
  [ADR 0071](0071-eval-statistics-and-gates.md)** — the flat score
  epsilon is replaced by a per-quantum band, `critic_score` is demoted,
  repeats are aggregated, and the gate ends in a three-state decision.
  Its price-table half and its metric-class split stand.
- [0045](0045-supply-chain-pinning-lockfile-and-license-posture.md) —
  Supply-chain hardening: bounded version ranges +
  `requirements-lock.txt` (CI installs the lock), explicit `src`
  packaging, lazy PEP 562 `src.api` re-exports, the original Next 15 /
  React 19 / Node 22 / vitest 4 upgrade, and PyMuPDF AGPL posture.
- [0046](0046-literal-typed-config-enums.md) — Enum-valued settings
  become `Literal[...]` so a typo'd env var dies at load instead of
  silently selecting the fallback backend; plus behaviour tests for
  the five untested control paths the audit flagged (HTTP 429, job
  ownership stamping, runner cost-cap/timeout handlers, terminal SSE
  frame over pub/sub, keystore + CORS wiring). Follows ADR 0011.
- [0047](0047-bounded-executor-and-cooperative-cancel.md) — Bounded
  node executor + cooperative cancellation. A job timeout cancelled
  the coroutine but not the synchronous node's thread, so
  `api_max_concurrent_jobs` bounded coroutines while zombie threads
  kept calling Claude on a job already marked failed. Graph nodes
  now run on a lifespan-owned pool sized to the job ceiling, a
  per-job cancel token is checked before every LLM call and between
  the reader's papers, and the runner holds the concurrency permit
  until the node thread actually returns — with the threads it gives
  up on still counted in `/healthz`. Follows ADR 0040; extends
  ADR 0042's honesty rule to `active_jobs`.
- [0048](0048-redriver-cas-and-store-edges.md) — Redriver
  compare-and-set (`update_if_status`, WATCH/MULTI/EXEC) so a job
  that finishes while the sweep is deciding keeps its report and
  its clients keep the truth; terminal-frame suppression moved into
  `publish_event` so no client sees `job_completed` after
  `job_failed`; `_local` eviction into a `finally` so a Redis
  outage cannot grow worker memory; `scan_jobs` skips terminal rows
  by TTL before hydrating report bodies; `redrive:lock` TTL 120s →
  30s so a worker killed mid-sweep stops locking out its own
  restart; `ConversationStore.update_title`; SSE deadline flushes a
  frame the read already produced. Corrects ADR 0038's claim that
  the `WatchError` abort path is untestable under `fakeredis` — it
  is now covered. Finishes the recorded follow-ups of ADR 0038 and
  ADR 0040.
- [0049](0049-otel-metrics.md) — OpenTelemetry metrics. The service
  had logs, opt-in traces and per-run cost accounting but no metrics
  at all, so "how many jobs are failing right now", "what is the p95
  job duration" and "are we near the concurrency ceiling" were
  grep-and-count exercises. Seven instruments on the OTel metrics API
  from the already-pinned SDK — rather than a second telemetry stack —
  gated behind `enable_metrics` and sharing tracing's OTLP endpoint.
  Every record point is an existing choke point (`_persist_terminal`,
  `record_llm_call`, `_raise_429`), and the two concurrency gauges
  observe the same accounting `/healthz` reports instead of a second
  set of counters. Closes ADR 0047's `abandoned_node_threads`
  follow-up. (ADR 0051 later adds two more instruments on the same
  meter: SDK retries and upstream errors.)
- [0050](0050-eval-runner-hardening.md) — Eval-runner hardening. The
  campaign is the next live spend, and the harness could not hold onto
  work it had paid for: one judge 529 aborted the batch and discarded
  the failing query's finished workflow output, nothing reached disk
  until the end, SIGTERM killed without flushing, and `make eval`
  returned 0 when every query failed. Per-metric judge isolation
  (honouring ADR 0008's contract and `_run_and_score`'s "Never
  raises"), per-query persistence plus `--resume` and a SIGTERM
  handler, workflow spend split from judge spend so the README figure
  and the `cost_usd` gate describe the agent rather than the eval rig
  (revisiting ADR 0044), empty reports and truncated batches made red
  instead of green, honest exit codes, a refusal to overwrite a prior
  campaign's directory, `--max-budget-usd`, and a nightly workflow that
  says which owner action fixes its 15-night-old red.
- [0051](0051-llm-cost-enforcement-and-visibility.md) — LLM cost
  enforcement and visibility. `max_cost_usd` was enforced only in the
  API runner's `on_node` callback, so `make run` and `make eval` — the
  two paths about to spend real money — had no dollar ceiling at all,
  and even on the API path a single node could overshoot by its whole
  fan-out. The check moves to `src.llm.call_llm`, the one function
  every entry point funnels through, with `CostBudgetExceeded` and the
  cap helper relocated to `observability.costs` so the LLM layer never
  imports the API layer; the between-nodes check stays as the coarser
  stop. Hitting the ceiling now keeps the draft the run already paid
  for instead of returning a bill with nothing attached. Alongside
  that: SDK retries become countable and loggable via
  `with_raw_response.retries_taken` (no second retry loop —
  ADR 0009's SDK-native choice stands), the retry envelope is clamped
  so one flaky call cannot eat a whole `api_job_timeout_sec`, unpriced
  models warn once per id and the coverage check reads runtime values
  instead of field defaults, and stderr goes back to being parseable
  JSON with `faulthandler` armed. Extends ADR 0033; narrows
  ADR 0042's `anthropic` logger demotion to spare the SDK's retry
  line.
- [0052](0052-native-crash-containment-and-data-lifecycle-edges.md) —
  Native-crash containment + data-lifecycle edges. The reader's
  five-way encode fan-out was killing the process with a SIGSEGV in
  the OpenMP barrier — no traceback, no log line, on `make run` and
  `make eval` as much as on `make test` — because torch defaults to
  one OpenMP thread per core and three vendored `libomp` copies ship
  in the venv. `torch.set_num_threads(1)` at model load takes a
  reader-shaped probe from 10/10 crashes to 0/15;
  `settings.embedding_device` (default `cpu`) additionally pins the
  backend away from the separate, rarer Metal-driver crash, and both
  choices are logged at model load. Shipped with the data edges a
  crash lands on: `admin_migrate assign/delete` refuse to run under
  `enable_api_auth=false` without `--include-all-auth-off` (with auth
  off *every* row is NULL-owner, so the tool's predicate selects the
  whole store), a corrupt job row and a refused terminal write are now
  audible instead of silent, `make run` salvages a finished report
  from the checkpoint when a later node fails, `make clean` stops
  deleting the graph checkpoints (`clean-all` does), the CLI's stale
  third copy of the initial `ResearchState` is replaced by one
  canonical initializer, and `docs/demo.md` stops claiming the
  mock-data run makes no external calls beyond Anthropic — it
  downloads five real arXiv PDFs.
- [0053](0053-api-web-container-preflight.md) — Make the shipped demo
  path survive its own first run. Walking `docker compose up` → open
  the UI → type a query found five breaks the suite could not see
  because no test drove the *sequence*: the landing page discarded
  the `job_id` it had just paid for and redirected to a page that
  could never recover it; `plan_ready` was published once and never
  replayed, so any reconnect during review waited out the 30-minute
  HITL timeout in silence; the image installed pyproject's ranges
  rather than `requirements-lock.txt`; the first live job downloaded
  ~90MB of MiniLM weights inside its own timeout budget while
  `/healthz` said `ok`; and the startup-only redriver left a job
  `running` forever when a container restarted inside its own lease.
  The job id now travels in `?job=`, the thread attaches instead of
  submitting, the stream replays `plan_ready` for a parked job, the
  image installs the lock and bakes the model, and the sweep repeats
  on `job_redrive_interval_sec`. `/healthz` also logs one WARNING
  per transition into degraded. Extends ADR 0038's redriver and
  ADR 0042's honesty rule; consumes ADR 0045's lockfile.
- [0054](0054-hetzner-production-boundary.md) — Close the production
  boundary for a single Hetzner VPS: generated runtime lock and
  CPU-only Torch, Next.js 16 server-only authenticated API proxy,
  loopback-safe local ports, parameterized Postgres credentials, and a
  Caddy HTTPS/basic-auth edge that is the only production host publish.
  Adds the reviewed single-host runbook and rollback contract.
- [0055](0055-frontend-architecture-confirmation.md) — Confirm Next.js App
  Router + the same-origin Node proxy as the frontend architecture. Makes
  D-002 binding under three constraints: `web/app/api/[...path]/route.ts`
  stays the **sole** credential boundary with `runtime = "nodejs"` and
  `dynamic = "force-dynamic"` pinned; the proxy gains request logging and a
  CSP before rollout (discharged); and Tailwind 4, TypeScript 7 and Turbopack
  each need their own ADR. The decisive argument is one D-002 never made:
  native `EventSource` and `<a download>` cannot carry a request header, so
  under `ENABLE_API_AUTH=true` a same-origin server hop is the only mechanism
  that makes the stream and the exports work at all. Also records the reserved
  names (`/login`, `/settings`, `/api/auth/*`) and that `/` is dynamically
  rendered as an inherent consequence of the per-request nonce.
- [0056](0056-design-tokens.md) — Design tokens: one source of values
  (`web/app/tokens.css`, the only file that may hold a literal colour), one
  source of names (`web/lib/tokens.ts`), Tailwind built from that module, and
  a bidirectional parity test plus an ESLint literal-colour ban instead of a
  generator. Records the RC-02 reconciled role set — the brief's 23 colour
  roles win, `04-ARCHITECTURE.md` §6.1's enumeration is superseded, `success`
  and `warning` do not exist — and the RC-01 ratified route budgets with the
  ratchet rule and the full movement history: D-011's shared-chunk raise,
  D-012's `/` raise (accessibility gate beats budget row), and WO-31's
  ratchet-down of six rows to the measured post-cleanup values.
- [0057](0057-job-kinds-and-awaiting-learner.md) — Give jobs a `kind`
  (`research` | `session`, defaulted so the field is additive) and
  generalize ADR 0030's `pending_review` parking into one mechanism
  with two flavours: `ParkingSpec` + `_park_until_resumed`, with
  `awaiting_learner` / `turn_ready` / `session_turn_timeout_sec` as
  the second. One driver serves both kinds — `JobKindRuntime` is the
  exhaustive record of the four decisions that differ (graph input,
  pause policy, pause ceiling, outer timeout) — so a Phase W tutoring
  session inherits the lease, cancel token, cost accumulator, outcome
  metrics, redrive policy and attach-time replay instead of a second
  runner earning them again. Reuses the ADR 0034 `hitl:resume:{job_id}`
  channel with an additive `payload` key rather than a second channel,
  and keeps `turn_ready` out of the terminal and stream-closing sets so
  a session does not cost a reconnect per turn. Records the sequencing
  that de-risked it: the generalization merged proven against
  `pending_review` with no test touched, before the new state had any
  client.
- [0058](0058-learner-profile-store-and-provenance.md) — The learner
  profile store (Phase W, WO-W02): the first personal data this repo
  keeps, with `declared` / `inferred` / `assessed` provenance on every
  skill claim made **unrepresentable to violate** at three layers — a
  `source` field with no default and no `None`, `(skill, source)` keying
  so a contradicting assessment lands beside a declaration instead of on
  top of it, and `jsonb_path_exists` CHECK constraints that refuse a
  bad claim to a `psql` session too. The serializer re-reads its own
  output so an inferred claim cannot render outside the "unconfirmed
  impressions" block, and learner-authored free text gets its own
  `<untrusted_learner_text>` isolation tags on the ADR 0033 pattern.
  Records `enable_learner_profile` (requiring `enable_api_auth` at
  settings load), the `GET/PUT/DELETE /learn/profile` surface, the
  first-class deletion promise **with its stated exception** (the
  shared paper/embedding caches), and — as this decision's real cost —
  that `principal_key_id` is a mutable display name until MT-01.
- [0059](0059-guided-read-session-graph.md) — The Phase W guided-read
  graph and its replay-safe learner-turn protocol: a total `SessionState`,
  four distinct dynamic-interrupt input nodes resumed with
  `Command(resume=...)`, a session-typed ADR 0047 executor wrapper (because
  LangGraph projects node input from runtime annotations), three owner-scoped
  `/learn/sessions*` endpoints, subscribe-before-frame Redis ordering, and an
  honest `recorded_ungraded` explain-back that writes evidence but no mastery
  percentage. Records the stale-turn bug the integration proof found and why
  casts or repeated `interrupt_after` updates are not safe substitutes.
- [0060](0060-evidence-grounded-assessment-judge.md) — The default-off,
  one-shot explain-back judge: exact response shape, learner-verbatim evidence
  on every finding, whole-judgment degradation to explicit `unassessed`, and
  at most one follow-up probe before a fixed edge to progress update. Raw judge
  output never enters learner-facing contracts, mock mode makes no call, and
  all outputs remain tutor guidance until the WO-W09 prior is owner-ratified.
- [0061](0061-bounded-tier1-session-memory.md) — The Phase W memory subset:
  a CI-enforced 2.5K-token-estimate Tier-1 ceiling, structural facts that win
  over lossy prose, one visibly lossy close-time session summary, and a
  transcript-grounded inference batch applied only after session close. A
  `summary:*` id is structurally invalid as skill evidence; each inference must
  instead cite the exact closing session.
- [0062](0062-session-specific-cost-ceilings.md) — A task-local effective
  ceiling keeps guided-reading sessions at their own `$0.50` default while
  research retains `max_cost_usd`, with the shared `call_llm` choke point still
  authoritative. Both refused and degraded-close outcomes are explicit, model
  routing warns when pricing is missing, and session node spans carry
  cumulative and delta cost/call attributes.
- [0063](0063-pilot-principal-edge-mapping.md) — A default-off, topology-guarded
  mapping at MT-01 seam S1: the pilot edge authenticates one `basic_auth` user
  per pilot and forwards the username, and `resolveUpstreamPrincipal` maps it
  to that pilot's per-principal API key from a server-side env map. Only the
  literal `on` enables it; the username is refused without the edge's shared
  secret; an ambiguous configuration, an unknown username and a sixth pilot all
  refuse to serve rather than falling back to the shared key. **To be superseded
  by MT-01** — it is a hand-run slice of L0-03, not a foundation for one.
- [0064](0064-error-taxonomy-and-envelope.md) — every failure that leaves the process carries a stable code from a closed set, and an envelope carries it.
- [0065](0065-test-isolation-and-coverage-floor.md) — the suite cannot reach the network, a real model client, or a developer `.env`; coverage has a measured floor that only ratchets up.
- [0066](0066-genai-semantic-conventions.md) — telemetry uses the OpenTelemetry GenAI names, and a job is one trace from submit to model call.
- [0067](0067-correlation-context-and-log-contract.md) — one correlation context for every signal, with an allowlisted, size-capped, redacted log payload.
- [0068](0068-resilience-policy.md) — retry at one level per dependency, on a shared budget, with Full Jitter; a token bucket rather than a circuit breaker.
- [0069](0069-property-based-testing.md) — invariants over generated input for the parsers, redaction, config and frame encoding.
- [0070](0070-eval-integrity-provenance.md) — pinned judges, versioned rubrics, and a provenance block on every eval row.
- [0071](0071-eval-statistics-and-gates.md) — Eval statistics and
  aggregate gates: the comparison is paired (906 items per arm unpaired
  versus 77 paired — both reproduced by `src/eval/stats.py` rather than
  quoted), repeats are aggregated by task on both lanes before anything
  is diffed and the research runner gains `--repeats`, the score epsilon
  is derived from each metric's quantum so one flipped topic decision
  passes and two fire, `critic_score` is demoted from gate to
  diagnostic, two runs whose provenance says they are not comparable are
  refused rather than diffed, and the report ends in PROMOTE / HOLD /
  ROLLBACK carrying an interval, `pass^k`, the rule of three, and an
  explicit statement that at N=20 the central-limit approximation
  underestimates uncertainty. Zero model calls inside the gate.
  **Supersedes the regression-gate half of
  [ADR 0044](0044-eval-cost-accuracy-and-regression-thresholds.md)**;
  follows ADR 0070.
- [0072](0072-adversarial-safety-suite.md) — Gate safety on a **regression
  delta and behavioural assertions**, not on an absolute rate and a canary.
  The evidence base it replaces was five regexes plus a literal-canary
  substring check, which asks a question about spelling: a model that obeys
  an injection and paraphrases the canary scores as contained. In its place,
  an authored 42-case corpus (`tests/fixtures/safety/`), a deterministic
  model-free scorer and gate (`src/eval/safety_suite.py`), and a
  `security`-marked tier. Each case carries an `obedient_output`, so total
  compliance is assumed rather than paid for; the gate is a delta plus a
  categorical veto at absolute zero, because attack success rate is a
  property of the deployment surface and at n=42 an absolute threshold flips
  on noise. OWASP categories are cited as **codes only** — the prose is
  CC BY-SA 4.0 and viral.
- [0073](0073-slos-and-operational-readiness.md) — SLOs anchored on the
  SRE Workbook's **quality** SLI rather than on a vendor threshold, with
  degraded and shed requests excluded from the latency SLI and counted
  against quality, the compounding arithmetic (0.95^5 = 77.4% across the
  five-node research graph) stated in the document, and every objective
  marked *declared, not earned*. Seven runbooks, alert rules and a
  dashboard ship under `deploy/observability/` as reviewable files that
  nothing runs. The deliverable is `tests/test_operability_docs.py`: it
  re-parses `src/` for every instrument and fails when a rule names one
  that no longer exists, because a renamed instrument does not error --
  it renders a flat zero, and a flat zero reads as a healthy fleet.
- [0074](0074-deterministic-groundedness.md) — Measure groundedness
  **deterministically, against the run's own corpus**. The arXiv domain makes
  two accuracy signals decidable without a judge: whether every cited
  identifier resolves, and whether every quoted span appears verbatim in the
  paper's parsed text. `src/eval/groundedness.py` checks identifiers against
  `state["papers"]` rather than the network — a citation to a real paper the
  run never fetched is still a fabricated citation, and that is the
  interesting failure. Fixes the failure mode `citation_accuracy` has today,
  where zero citations scores 1.0: the new metrics report their denominators,
  and no citations is `None` with a reason code. Produces the per-claim
  binary outcome ADR 0071's paired path needs, at zero spend and with no
  drift when a model is upgraded.
- [0075](0075-scripted-research-tier-and-paired-claims.md) — Give the
  research lane a free gate, and run the paired path on it.
  `src/eval/simulate_research.py` replays the whole research benchmark
  against the real compiled graph under `USE_MOCK_DATA=true` with a
  scripted model surface, for `$0.0000` and about five seconds — the
  research lane's counterpart of the scripted tier the learning lane has
  had since WO-W10, and the first per-PR gate that lane has ever had.
  Each record emits ADR 0074's per-claim `paired_outcomes`, and
  `regression_diff` pairs two campaigns on them with ADR 0071's McNemar
  path — the caller that apparatus never had. Adds a third, deterministic
  lane: one adverse claim is a regression, and an unchanged comparison
  may promote rather than being told it was underpowered, because a
  fixed function of the code has no sampling noise to be underpowered
  against.
- [0076](0076-fixed-verify-repair-research-policy.md) — Fixed
  verify-and-repair research policy (Arm C): a `research_policy`
  selector adds a third graph shape — synthesizer → `verify` →
  at most one typed `repair` → re-verify → critic — behind a
  default-off setting that refuses to load with the supervisor or
  the legacy verifier flag. Abstain is a first-class verdict; the
  repair decision is deterministic. Default settings compile to the
  same graph as before, proven by a golden node/edge listing.
- [0077](0077-model-aware-request-profiles.md) — Make the LLM gateway's
  request model-aware. `src/llm_models.py` becomes the one place a model
  quirk lives — a pure table of what each Claude model accepts, with a
  cited source and a verification date per row — and `src/llm.py`
  resolves a frozen `RequestProfile` per call from it, sending
  `temperature`, `thinking` and `output_config` only where the model
  takes them. Until this, `temperature=0.3` went to every model, which
  is an HTTP 400 on Opus 4.7 and later: the gateway broke the day the
  model id moved, and the shipped default was simply the last generation
  that still accepted sampling. Thinking and effort are refused at
  settings load because neither has a runtime answer; temperature and
  structured outputs are not, because both degrade. `thinking` blocks
  are skipped in the response and a text-free answer raises ADR 0064's
  `upstream_model_output` instead of returning the empty string every
  caller used to read as content. Default-off and byte-identical, held
  by a golden fixture captured from the unmodified gateway.
- [0078](0078-contract-shadow-for-the-research-path.md) — Bind the P0
  contracts to the research path in shadow, default off. `CONTRACT_SHADOW`
  compiles a `TaskSpec` at research intake and at eval-case selection,
  seals a `RunManifest` before the first node runs, and records a
  hash-chained trajectory in memory beside the run — changing no graph
  input, no job outcome, no cost and no stored schema, and importing no
  contract module at all while the switch is off. Policy identity is read
  from the *compiled graph* rather than from the flags, which is what
  makes `ENABLE_VERIFIER=true` on the fixed pipeline classify as arm A
  instead of masquerading as arm C, and what leaves arm E unrepresentable
  until something actually routes compute tiers. A metered provider fails
  admission closed rather than sealing a manifest that implies permission
  to spend.
- [0079](0079-benchmark-registry-migration-and-parity.md) — Register the
  existing benchmarks, prove parity, and change nothing they mean. The
  twenty research queries and fifteen guided-reading scenarios enter
  `eval_registry/` as immutable objects at their existing ids and in
  their existing order; expected topics, learner scripts and grader
  configuration become an evaluator-only overlay the candidate role
  cannot resolve; the public suite is mechanically barred from
  promotion use. Adapters rebuild the runners' exact data shapes from
  registry content and a parity report names any divergence, so the
  runners keep reading their own modules until a later ADR moves them.
- [0080](0080-mock-mode-covers-the-whole-research-graph.md) — **Mock
  mode covers the whole research graph.** `USE_MOCK_DATA` swapped arXiv
  for five fixture papers and left planner, reader, synthesizer, critic
  and verifier calling the provider, so a stack with no credential
  answered `POST /research` with a 202 and then a `failed` job
  (`error_type=upstream_model`, `llm_calls=0`) four seconds later —
  there was no keyless path to a briefing at all. Each of the five now
  has a deterministic branch before its model call, generated from the
  run's own inputs by `src/agents/mock_mode.py`: analyses and evidence
  claims are verbatim spans of the paper's abstract, citations name the
  papers actually retrieved, and the briefing opens with the exact line
  `Mock mode: fixture papers, no model call.` so it can never read as a
  real one. `src/llm.py` is untouched and the live path is
  byte-identical. **No output here is a quality signal** — the critic's
  score and the verifier's verdict are constants. Closes half of ADR
  0075's own follow-up list.
- [0081](0081-degradation-counter-and-the-quality-sli.md) — **Count
  degradations on a closed rung vocabulary, and make the quality SLI
  computable.** `docs/reliability.md` rests every objective it declares
  on the SRE Workbook's quality SLI, and six of the eight rungs of its
  degradation ladder emitted a log line and nothing else, so the anchor
  metric could not be computed and §3 had no quality row at all.
  `research_degradations_total{rung,component}` is that instrument, with
  both attributes drawn from `frozenset` vocabularies — the third closed
  set here after `ERROR_CODES` (unbounded cardinality) and
  `KNOWN_EVENTS` (silent rot), enforced by an AST scan of `src/` rather
  than a fixture. `reason` stays a log field: the metric answers how
  much and where, the log answers why. Rungs keep their own distinct log
  events instead of folding onto `resilience_degraded`, which pages at
  threshold 1. Five of eight rungs are now metered; the three that are
  not have every call site in another lane's files, and the test names
  them, their owner, and fails when one is wired — so the SLI is
  honestly a lower bound and says so on the row.

- [0082](0082-campaign-lock-repeats-and-denominators.md) — **Derive the
  campaign id, enumerate the whole matrix, keep every episode in the
  denominator.** A campaign id is now a digest of the frozen protocol,
  the registry lock and the lineage edge, so re-planning an unchanged
  design resumes and raising a cap by a cent *cannot* — it is a
  different campaign, and `resume` says so and names lineage as the
  remedy. The design matrix is enumerated over all five arms including
  the ones this checkout cannot run (arm E is `capability_missing` and
  its slots are excluded-with-reason, so 20 x 3 x 5 reports as 300
  expected / 240 planned / 60 excluded), arm order is interleaved per
  block from a seed the manifest records, and the denominator ledger is
  written before the first episode so a failure, timeout, cancellation,
  budget stop or null metric can never leave it. A local approval-record
  backend satisfies W03's admission so a metered provider can be
  admitted in a test, with credentials read only after the record
  verifies — **a live campaign still needs the owner's D9 approval and
  P0-WO12 stays blocked**. Snapshot and live campaigns are refused a
  shared summary.

## When to write an ADR

- Choosing between competing libraries or frameworks.
- Choosing between competing algorithmic or architectural approaches.
- Introducing a new external dependency of any weight.
- Establishing a new project-wide convention.
- Reversing a prior ADR (write a new one with `Status: superseded by`).

If you're not sure whether a decision warrants an ADR, err toward
writing one. They're cheap to write and priceless six months later.
