# 0027. Dockerfile + docker-compose + RedisJobStore

- **Status**: accepted
- **Date**: 2026-07-10
- **Depends on**: ADR
  [0025](0025-fastapi-async-job-model.md) (JobStore Protocol),
  [0026](0026-sse-streaming-endpoint.md) (SSE streaming)

## Context

Sprint 4 PR 2 shipped a working API surface but two production
constraints stayed unaddressed:

- **The app has no deployment shape.** No image, no way to run it
  the same way a production orchestrator (Kubernetes, ECS, Nomad)
  would. Contributors run it via `python -m src.api.serve`; that's
  useful for local iteration but not for staging, demo deploys, or
  the CI-driven container smoke tests that catch dependency-graph
  regressions.
- **Single-worker only.** `InMemoryJobStore` scopes job state to
  one uvicorn process. A second worker can't serve GET requests
  for jobs the first worker created — the whole point of running
  behind a load balancer is defeated. Horizontal scaling was
  scoped to Sprint 4 PR 4 in ADR 0025, but bundling it into this
  PR (rather than PR 4) makes the compose stack meaningful the day
  it lands: Redis exists in compose *and* the app talks to it.

The paper cache work stays with PR 4 as originally scoped; that's
where the Postgres story pays off. Postgres sits idle in this
PR's compose stack — visible in the URL config surface, running
in the container, but nothing writes to it yet. Cost of "idle
Postgres" is measured in single-digit MB of RAM per compose stack;
carrying it now keeps PR 4's diff narrower and eliminates the
docker-compose churn PR 4 would otherwise need.

## Decision

### Multi-stage Dockerfile

Two stages, both `python:3.14-slim`:

- **Builder** — creates `/opt/venv`, installs the runtime deps from
  `pyproject.toml`, then installs the app itself with `--no-deps`.
  The dep install and the source install are separate `COPY` +
  `RUN` layers so unchanged deps land as a cached layer even when
  the source changes. `--mount=type=cache,target=/root/.cache/pip`
  keeps the pip download cache across builds within a runner (GHA
  cache for CI, buildkit cache for local).
- **Runtime** — copies `/opt/venv` + the source from the builder,
  installs `curl` (for the HEALTHCHECK), creates a non-root `app`
  user (uid 1000), sets `USER app`, and runs uvicorn against
  `src.api.app:create_app --factory`. No build toolchain, no test
  deps, no docs in the final image.

Runtime image target size: ~500 MB (dominated by
`sentence-transformers` + PyMuPDF + faiss weights). Reasonable
for a Python ML container; a follow-up can strip the
sentence-transformers model download to a separate volume mount
if the size matters.

`HEALTHCHECK` hits `/healthz` every 15 s. Compose's
`depends_on: condition: service_healthy` waits for it before
starting downstream services, which matters for orchestrators
that block routing on health.

### docker-compose.yml

Three services:

- **`app`** — built from `./Dockerfile`, port 8000, healthchecked.
  Environment: `ANTHROPIC_API_KEY` from the host (required, no
  default — `${VAR:?...}` errors clearly if missing); `JOB_STORE=redis`;
  `REDIS_URL=redis://redis:6379/0`; `POSTGRES_URL=postgresql://...`
  (unused this PR). Depends on `redis` and `postgres` being healthy.
- **`redis`** — `redis:7-alpine` with `--appendonly yes` for
  durability. Named volume `redis-data` so `docker compose down`
  preserves jobs across restarts; `down -v` wipes.
- **`postgres`** — `postgres:16-alpine`, standard env config
  (user/pass/db all `arxiv`; production overrides via env). Named
  volume `postgres-data`. Idle in this PR; wired up in PR 4.

Neither Redis nor Postgres publishes a host port by default — the
app talks to them over the compose default network. Commented-out
lines make debugging with `redis-cli` / `psql` from the host a
one-line uncomment.

### RedisJobStore

Implements the `JobStore` Protocol from ADR 0025 against
`redis.asyncio`. Layout:

- One key per job: `job:{job_id}` holds JSON-serialized persistent
  fields.
- `event_queue` is **not** persisted — it's an `asyncio.Queue`
  bound to the worker that runs the job. Streaming events across
  workers would need Redis pub/sub, tracked as a follow-up.
- **Local instance cache**: the store keeps a `dict[job_id, Job]`
  of jobs it created on this worker. `get()` returns the cached
  instance when available so streaming picks up the live queue;
  otherwise it rehydrates from Redis. This is the "sticky routing
  for SSE, shared state for polling" trade-off spelled out in the
  Consequences section below.
- **TTL-based retention**: when a job goes terminal, `update()`
  writes the JSON with `EX=api_job_retention_sec`. Redis handles
  eviction; `evict_older_than()` is a no-op under Redis.
- **Store selection** happens in `create_app._default_store()`
  based on `settings.job_store`. `"memory"` (default) →
  `InMemoryJobStore`; `"redis"` → `RedisJobStore` +
  `build_redis_client(settings.redis_url)`. The redis import is
  lazy so the in-memory path never touches the redis client at
  import time.

### CI: `docker-build` job

New parallel job in `.github/workflows/ci.yml` runs
`docker/setup-buildx-action` + `docker compose config` +
`docker/build-push-action` with GitHub Actions cache. Doesn't push
anywhere — just verifies the Dockerfile builds and the compose
schema is valid, so a broken `pyproject.toml` dependency or a bad
Dockerfile syntax fails the PR at the same tier as ruff/mypy/tests.

## Alternatives considered

- **Single-stage Dockerfile.** Simpler but ships the build
  toolchain in the runtime image, tripling the size. Rejected.
- **`python:3.14` (non-slim).** Fatter base with `apt` toolchain
  pre-installed. Cost: ~800 MB base vs ~120 MB slim. Rejected —
  the only C-extension deps we need (`fitz`, `faiss-cpu`) already
  ship binary wheels for py314.
- **Distroless (`gcr.io/distroless/python3`).** Much smaller,
  much fewer moving parts. Rejected: distroless doesn't ship
  `curl`, which the HEALTHCHECK uses; we'd need a Go-based
  healthcheck binary or a Python HTTP call. Not worth the
  complexity for a first-pass image.
- **Poetry / uv / Rye as the build tool.** All would work; pip
  matches the rest of the repo's tooling and the CI config, so
  the Dockerfile uses pip too. Consistency > marginal build-time
  savings.
- **`sse-starlette` / `EventSourceResponse` for streaming across
  workers.** Would eventually need Redis pub/sub anyway. Kept
  out of this PR — the streaming-across-workers story is a
  follow-up (see Consequences).
- **Postgres for the JobStore instead of Redis.** Postgres works
  for job records, but SSE-adjacent event streaming *and*
  short-TTL retention both fit Redis's shape better. Postgres is
  the right home for the paper cache (durable, queryable, indexed),
  Redis for the API's session-scoped state.
- **Kubernetes manifests / Helm chart instead of compose.** The
  target for this PR is local + CI + demo deploys. Kubernetes
  manifests would be premature — the `compose` file is the
  right substrate for the current phase, and every compose service
  translates one-to-one to a Kubernetes Deployment + Service when
  we get there.
- **Skip the RedisJobStore in this PR** (deferring it to PR 4 per
  the original ADR 0025 plan). Rejected: it makes Redis in
  compose meaningful the day it lands, avoids a follow-up
  "Redis compose stack that nothing talks to" review round, and
  the API surface becomes horizontally scalable — the whole
  point of containerizing it.

## Consequences

- **Positive.** The app is now runnable via
  `docker compose up` on any machine with Docker installed, no
  Python setup required. Multi-worker uvicorn deployments work
  correctly for the polling API — every worker sees every job.
  Redis handles retention automatically via TTL, no sweeper
  needed. CI catches Dockerfile + compose regressions on every
  PR. The `JobStore` Protocol is exercised by two production
  implementations, which validates the abstraction.
- **Negative — SSE requires job affinity.** A client can only
  reach the *live event stream* on the worker that runs the job
  (the `event_queue` is worker-local). Under a load balancer this
  means either sticky sessions keyed on the job_id path, or
  clients polling instead of streaming when the request lands on
  a different worker. The polling path serves the terminal snapshot
  correctly across workers; only the intermediate-event stream
  needs affinity. A Redis pub/sub follow-up would remove this
  constraint but adds real complexity (per-job channels, backpressure,
  reconnect cursor handling); deferred until a client actually
  needs cross-worker streaming.
- **Negative — Postgres idle.** The compose stack runs a
  Postgres container that's unused until PR 4. Costs ~50 MB RAM
  and one connection slot; acceptable.
- **Follow-ups.**
  - **Sprint 4 PR 4**: Postgres-backed paper cache + persisted
    embeddings. Uses the `POSTGRES_URL` already in this PR's
    compose file.
  - **Redis pub/sub for streaming across workers**, if a client
    actually needs it. Untriggered until then.
  - **Image size trimming**: split the sentence-transformers
    weights out of the runtime image so cold starts don't pay
    the ~200 MB embedding-model tax on every deploy.
  - **Kubernetes manifests**: translate the compose stack when
    we have a target cluster.
