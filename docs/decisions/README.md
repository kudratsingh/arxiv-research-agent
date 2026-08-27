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

## When to write an ADR

- Choosing between competing libraries or frameworks.
- Choosing between competing algorithmic or architectural approaches.
- Introducing a new external dependency of any weight.
- Establishing a new project-wide convention.
- Reversing a prior ADR (write a new one with `Status: superseded by`).

If you're not sure whether a decision warrants an ADR, err toward
writing one. They're cheap to write and priceless six months later.
