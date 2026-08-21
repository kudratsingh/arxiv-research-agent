# Architecture

System-level view of `arxiv-research-agent`: the two workflow shapes,
the HTTP surface layered on top, and the storage matrix that decides
where every piece of state lives. Everything here is derived from the
code on `main` (`src/graph/workflow.py`, `src/api/app.py`,
`src/api/routes.py`, `src/config.py`); the linked ADRs carry the
rationale — this page does not restate them.

## The workflow — two shapes

`src/graph/workflow.py::build_workflow` compiles one of two LangGraph
graphs over the shared `ResearchState` (`src/graph/state.py`),
selected by `settings.enable_supervisor`:

**Fixed pipeline (default)**

```
planner → search → reader → synthesizer → critic → END
   ↑         ↑                    ↑           │
   └─────────┴────────────────────┴───────────┘
     route_after_critique: on revision_needed, the critic's
     revision_target picks planner / search / synthesizer
     (capped at settings.max_iterations revisions)
```

**Supervisor loop** (`enable_supervisor=true`, ADR
[0014](decisions/0014-supervisor-loop-behind-flag.md))

```
START → supervisor → <chosen node> → supervisor → ... → END
```

Every agent node hands control back to the supervisor, which picks
the next action from a strict enum — `plan / search / read /
synthesize / critique / stop`, plus `verify` when
`enable_verifier` is on (ADR
[0015](decisions/0015-verifier-agent-runtime-faithfulness.md)) and
`refine_query` when `enable_query_refiner` is on (ADR
[0018](decisions/0018-query-refiner-recovery-action.md)). Budget and
iteration caps short-circuit before the LLM call; malformed judge
output falls back to rules that mirror the fixed-pipeline order.

Regardless of shape, `build_workflow` also wires two production
knobs:

- **Checkpointing** — `SqliteSaver` (per-worker) or `PostgresSaver`
  (shared across workers), selected by
  `settings.checkpoint_backend`. Postgres is required for
  multi-worker HITL. ADRs
  [0013](decisions/0013-sprint-1-finish-retry-checkpoint-tracing-recall.md)
  / [0034](decisions/0034-postgres-checkpointer-and-cross-worker-hitl.md).
- **Tracing** — `traced_node` wraps every agent in an OpenTelemetry
  span when `settings.enable_tracing` is on (ADR
  [0012](decisions/0012-observability-core-logging-costs.md)).
  Metrics ride the same OTLP endpoint behind their own flag (ADR
  [0049](decisions/0049-otel-metrics.md)), but no instrument wraps a
  node: they hang off choke points the API layer and the cost
  accumulator already own, and only an API worker installs a provider.

The compiled graph is expensive (it opens the checkpointer's
connection), so it is built **once** at app startup and shared —
never per request (ADR 0034).

Per-agent behavior (inputs, outputs, prompt design, failure modes)
lives in [`docs/agents/`](agents/) — one page per agent.

## The API layer

`src/api/` wraps the workflow in a FastAPI app (factory:
`app.py::create_app`; routes: `routes.py`). Design in ADR
[0025](decisions/0025-fastapi-async-job-model.md).

**Job model.** `POST /research` returns `202 Accepted` with a
`job_id` immediately; the runner (`runner.py`) drives the compiled
graph through `astream` (ADR
[0040](decisions/0040-async-checkpointer-and-runner.md)), bounded by
a process-wide semaphore (`api_max_concurrent_jobs`) and a hard
timeout (`api_job_timeout_sec`). Job lifecycle:
`pending → running → (pending_review →) succeeded / failed /
cancelled`. `GET /research/{job_id}` polls status + result.

**Node execution + cancellation.** Agents are synchronous, so the
async path runs each node on a lifespan-owned `ThreadPoolExecutor`
sized to `api_max_concurrent_jobs` — the semaphore then bounds
threads rather than coroutines. A timeout can only cancel the
awaiting coroutine, so the runner also sets a per-job cancel token
(checked before every LLM call and between the reader's papers) and
holds the job's permit until the node thread actually returns,
bounded by `api_job_drain_timeout_sec`. Threads it gives up on stay
counted in `/healthz`'s `active_jobs`. ADR
[0047](decisions/0047-bounded-executor-and-cooperative-cancel.md).

**SSE streaming.** `GET /research/{job_id}/stream` streams events as
the runner emits them: `node_completed`, `plan_ready`,
`job_completed`, `job_failed`, `job_cancelled`, plus heartbeats so
proxies don't drop the stream and a `stream_timeout` frame when
`api_sse_max_duration_sec` closes a long-lived connection (ADRs
[0026](decisions/0026-sse-streaming-endpoint.md) /
[0038](decisions/0038-job-redriver-and-sse-stream.md)). Connecting to
an already-finished job replays the single terminal frame and closes,
which makes reconnects idempotent; connecting to a job parked in
`pending_review` replays its `plan_ready` frame the same way, so a
reconnect during plan review sees the plan instead of waiting out the
HITL timeout in silence (ADR
[0053](decisions/0053-api-web-container-preflight.md)). Under the Redis
job store, events fan out across workers via pub/sub on
`events:{job_id}` so the streaming request need not land on the
worker running the job (ADR
[0035](decisions/0035-cross-worker-sse-pubsub.md)); a late subscriber
on that path sees only events published after it connects — which is
why the replays above are snapshots read from the job row, not a
backlog.

**Job leases + redriver.** Under the Redis job store, a worker holds
`joblease:{job_id}` (TTL `job_lease_ttl_sec`, refreshed in the
background) while it runs a job; a worker that dies stops refreshing,
and the redriver reclaims its orphaned jobs — failing them with
`error_type=orphaned` (or resubmitting still-`pending` ones when
`job_redrive_requeue_pending` is on). The sweep runs at startup **and**
on a jittered `job_redrive_interval_sec` timer, because a container
restarted inside its own lease window sees the dead lease as live at
boot and needs a later pass (ADR 0053). Sweeps serialize on a
cluster-wide `redrive:lock`, and every reclaim is a compare-and-set
(`update_if_status`, WATCH/MULTI/EXEC) so a job that finishes while
the sweep is deciding keeps its report (ADRs
[0038](decisions/0038-job-redriver-and-sse-stream.md) /
[0048](decisions/0048-redriver-cas-and-store-edges.md) / 0053).

**HITL.** When `enable_hitl` is on, the workflow interrupts after
the planner; the job parks in `pending_review` and
`POST /research/{job_id}/review` approves or edits the plan
(sub-questions + search queries) before search runs. Per-request
bypass via `{"hitl_bypass": true}` — the runner resumes the
interrupt immediately without emitting a review event. (The eval
runner and CLI avoid the pause upstream instead, compiling the
workflow with `enable_hitl=False`.) ADR
[0030](decisions/0030-hitl-plan-review.md); cross-worker resume via
Redis pub/sub in ADR 0034.

**Conversations.** `POST/GET/DELETE /conversations` group jobs into
threads; follow-up jobs get `prior_context` — top-K chunks retrieved
from the thread's prior reports (`retriever.py`) — injected into the
planner's prompt (ADR [0032](decisions/0032-conversation-mode.md)).

**Export.** `GET /research/{job_id}/export?format=md|pdf|docx`
renders the finished report via `src/api/exporters/` (ADR
[0031](decisions/0031-multi-format-export.md)).

**Auth, scoping, rate limiting** (`auth.py`). Opt-in behind
`enable_api_auth`: every route (except `/healthz`) requires an
`X-API-Key` header resolved against the keystore — either the
`api_keys` setting or a hot-reloadable JSON file (`api_keys_file`,
ADR [0037](decisions/0037-redis-rate-limiter-and-keystore-reload.md)).
Jobs and conversations are scoped to the creating principal;
cross-principal access returns 404 (ADR
[0036](decisions/0036-per-principal-store-scoping.md)). Submits are
rate-limited per key per sliding hour — in-memory per worker, or a
shared Redis ZSET under `rate_limit_backend=redis` (ADR 0037). The
broader hardening bundle (cost cap enforcement, PDF size cap, CORS
opt-in, prompt-isolation extensions) is ADR
[0033](decisions/0033-safety-hardening-bundle.md); threat model in
[`docs/security.md`](security.md).

**Web UI.** `web/` is a Next.js single-page client (query form, live
SSE event log, plan review, report view with export, conversation
sidebar), built and tested in CI alongside the Python suite (ADR
[0029](decisions/0029-nextjs-web-ui.md)).

## Storage matrix

Every stateful concern has a pluggable backend chosen by one
setting in `src/config.py`. Defaults favor zero-dependency local
dev; the compose stack (`docker-compose.yml`, ADR
[0027](decisions/0027-docker-compose-redis-job-store.md)) selects
the shared backends.

| Concern | Setting | Options (default first) | Shared across workers? | ADR |
|---|---|---|---|---|
| Job store (status, result, events) | `job_store` | `memory` / `redis` | Redis only | 0025, 0027 |
| SSE + HITL fan-out | (follows job store) | in-process queue / Redis pub/sub | Redis only | 0034, 0035 |
| Conversation store | `conversation_store` | `memory` / `postgres` | Postgres only | 0032 |
| LangGraph checkpoints | `checkpoint_backend` | `sqlite` / `postgres` | Postgres only | 0013, 0034 |
| Paper cache (parsed PDF text) | `paper_cache` | `disk` / `postgres` | Postgres only | 0028 |
| Embedding cache | `embedding_cache` | `none` / `postgres` | Postgres only | 0028 |
| Rate limiter | `rate_limit_backend` | `memory` / `redis` | Redis only | 0033, 0037 |
| API keystore | `api_keys` / `api_keys_file` | env string / JSON file (hot-reload) | file is shared by mount | 0033, 0037 |

Rule of thumb: a single-process deployment can run entirely on the
defaults; any horizontally-scaled deployment needs `redis` for the
job store + rate limiter and `postgres` for checkpoints,
conversations, and caches — which is exactly what
`docker-compose.yml` wires.

The container image installs `requirements-lock.txt` (never
pyproject's ranges, so it runs the dependency set CI tested) and
bakes the MiniLM embedding weights into the image at build time —
the first live job no longer downloads ~90MB inside its own timeout
budget (ADR [0053](decisions/0053-api-web-container-preflight.md);
pinned without a build by `tests/test_container_contract.py`).

## Cross-cutting concerns

- **LLM access** — one shared client (`src/llm.py`), SDK-native
  retry (ADR [0009](decisions/0009-anthropic-sdk-native-retry.md)),
  per-agent model routing (ADR
  [0021](decisions/0021-cost-aware-model-routing.md)), prompt caching
  (ADR [0022](decisions/0022-anthropic-prompt-caching.md)).
  `call_llm` is the enforcement choke point (ADR
  [0051](decisions/0051-llm-cost-enforcement-and-visibility.md)): it
  checks the per-job cancel token, then the run's accumulated spend
  against `max_cost_usd`, before every call — so the dollar ceiling
  binds on the CLI and eval paths too, and a node's parallel fan-out
  cannot overshoot by its whole spend. The retry envelope is clamped
  so one flaky call chain fits inside 75% of `api_job_timeout_sec`,
  and the SDK's own `retries_taken` is logged and counted per call.
- **Embeddings** — MiniLM via sentence-transformers
  (`src/tools/embeddings.py`), shared by paper ranking, chunk
  ranking, and conversation retrieval. Torch's OpenMP pool is pinned
  to one thread at model load and the device is explicit
  (`embedding_device`, default `cpu`) — both are native-crash
  containments, logged once at model load (ADR
  [0052](decisions/0052-native-crash-containment-and-data-lifecycle-edges.md)).
  The container image ships the weights pre-baked (ADR 0053).
- **Observability** — three signals out of `src/observability/`.
  **Logs**: structured JSON with `run_id` propagation, plus per-run
  cost accounting (ADR
  [0012](decisions/0012-observability-core-logging-costs.md)); the
  runner's between-nodes `max_cost_usd` check (ADR
  [0033](decisions/0033-safety-hardening-bundle.md)) remains as the
  coarser stop above the per-call ceiling in `call_llm` (ADR 0051).
  **Traces**: `traced_node` spans per agent behind `enable_tracing`
  (ADR
  [0013](decisions/0013-sprint-1-finish-retry-checkpoint-tracing-recall.md)).
  **Metrics**: nine OTel instruments behind `enable_metrics` (ADR
  [0049](decisions/0049-otel-metrics.md), extended by ADR 0051) —
  terminal job counts by status + error type, a job-duration
  histogram, LLM spend, call, retry and upstream-error counts by
  model, rate-limit rejections by backend, and observable
  gauges for this worker's in-flight jobs and its abandoned node
  threads. Traces and metrics share one `otel_exporter_endpoint`, so
  a single OTLP collector receives both. Every metric is recorded at
  an existing choke point — the runner's terminal write, the cost
  accumulator, the shared 429 helper — and the gauges observe the
  same accounting `/healthz` reports rather than a second set of
  counters. Pointing a collector at it:
  [`development.md`](development.md#opentelemetry-traces--metrics).
- **Evaluation** — custom in-repo benchmark + LLM-judge metrics
  (`src/eval/`, ADR [0005](decisions/0005-custom-eval-over-ragas.md))
  run nightly in CI with regression diffing (ADR
  [0010](decisions/0010-nightly-eval-ci.md)). The campaign runner is
  crash-safe: per-query persistence, `--resume`, per-metric judge
  isolation, a `--max-budget-usd` ceiling, and honest exit codes
  (ADR [0050](decisions/0050-eval-runner-hardening.md)); strategy in
  [`docs/eval.md`](eval.md).
