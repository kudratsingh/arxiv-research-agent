# Portfolio polish — what turns the repo into a resume artifact

These are the "presentation" items that separate a well-engineered
codebase from a well-engineered codebase **that a reviewer can grok
in 90 seconds**. Distinct from
[`05-agentic-upgrade-plan.md`](05-agentic-upgrade-plan.md), which is
about making the system more agentic; this is about making the system
more legible.

Sequenced so a reviewer visiting the GitHub repo sees the value in
this order: architecture → demo → numbers → deployable → maintained.

## 1. Architecture diagram in the README (~1 day)

**Where:** top of `README.md`, above the setup instructions.

Mermaid or a checked-in PNG. Must show:

- The five agents (planner / search / reader / synthesizer / critic).
- The tools (arXiv search, PDF parser, chunker, chunk-ranker,
  embeddings).
- The state (`ResearchState`) as the shared bus.
- The observability sidecar (JSON logs, run_id, cost tracker, OTel
  spans).
- The eval loop (benchmark → runner → metrics → nightly diff).

Once the supervisor loop lands, a second "before / after" diagram
lives next to the first. **The comparison is the story.**

## 2. README demo output (~half day)

One real query, one final report inline. Not a screenshot — checked-in
markdown so it's greppable. Include:

- The exact query used.
- The truncated report body (with `[...]` markers for length).
- A sample per-query line from `summary.jsonl` (metrics + cost +
  latency).
- The run's `run_id` so a viewer can find the full artifact if we
  ship it.

**File:** `docs/demo.md` linked from the README, so the README stays
skimmable.

## 3. Eval results table in the README (~half day, ongoing)

Below the demo. Auto-generatable from `summary.md` — a small script
that reads the latest `outputs/eval/<run_id>/summary.md`, extracts
the aggregate row, and updates a stable block in the README between
HTML comment markers.

Columns: Query count / mean citation accuracy / mean faithfulness /
mean completeness / mean retrieval recall / mean cost per query /
mean latency / date of run.

The nightly CI workflow (`.github/workflows/eval-nightly.yml`) can
open a PR that updates that block — makes the numbers visibly fresh.

## 4. `Dockerfile` and `docker-compose.yml` (~1 day)

**File:** `Dockerfile` at repo root, `docker-compose.yml` alongside.

Requirements:

- Python 3.14-slim base.
- Multi-stage build: builder installs deps into a venv; runtime copies
  the venv and app.
- Non-root user.
- `HEALTHCHECK` hitting the FastAPI `/healthz` (see next section).
- `.dockerignore` covering `.venv`, `.cache`, `outputs`, `tests`,
  `.git`, `.github`.

`docker-compose.yml`:

- The app service.
- A Redis service (for the future paper cache — Sprint 3 item).
- A Postgres service (Sprint 4 embeddings cache).
- OTLP collector optional (commented, off by default) so a reviewer
  who has Jaeger / Tempo running can flip one flag to get traces.

## 5. FastAPI endpoint (~1-2 days)

**File:** `src/api/server.py` + `src/api/routes.py` +
`src/api/schemas.py`.

Endpoints:

- `POST /research` — takes `{query, run_id?}`, returns
  `{run_id, status: "started"}` and kicks off the workflow in a
  background task.
- `GET /research/{run_id}` — returns current state + last log lines
  + cost + latest metrics (once eval runs).
- `GET /research/{run_id}/stream` — SSE stream of `messages` +
  status transitions as the workflow progresses.
- `GET /healthz` — liveness. Returns 200 when settings loaded and
  Anthropic key present.
- `GET /readyz` — readiness. Returns 200 when SQLite checkpoint DB
  is writable + retry adapter has warmed up.

Uses the existing `run` function; no rewrite. Async wrapper around
the sync workflow (LangGraph offers `.ainvoke` — worth using).

The FastAPI surface **also** unlocks the demo — someone can `docker
compose up` and hit `POST /research` from Postman to see it work.

## 6. CI: lint + mypy + pytest (~1 day)

**File:** `.github/workflows/ci.yml`

Runs on every PR and every push to `main`:

- `make install-dev` (cached via pip cache).
- `make typecheck` (fails on new mypy errors — start with baseline
  and ratchet down).
- `pytest tests/ -x --ff` — full unit tier. E2E cassette work is
  future, out of scope for CI.
- A tiny smoke query against mock data (`USE_MOCK_DATA=true`) to
  catch import / wiring regressions the unit tests miss.
- Optional: `ruff check src/` and `ruff format --check src/` — small
  change, big polish signal. Add `ruff>=0.7` to dev deps.

The green ✓ badge in the README is the biggest professionalism
signal a reviewer sees. Landing this is worth outsized effort.

**Interaction with nightly eval CI:** the nightly workflow already
runs the eval benchmark. `ci.yml` is fast (~2 min) and runs on every
PR; nightly is slow (~15 min) and runs once a day. They complement,
they don't overlap.

## 7. "Production considerations" section in the README (~1 day)

Short (300-500 words), grouped by the operational concerns any
production-scale AI system has to answer. Structure:

### Rate limits

- Anthropic: SDK-native retries with exponential backoff on 408 /
  409 / 429 / 5xx, 4 retries + 120s timeout. See ADR 0009.
- arXiv API + PDFs: `urllib3.Retry` on `GET`s with `Retry-After`
  honored. See ADR 0013.

### Retries and timeouts

Pointer to `settings.anthropic_max_retries` /
`settings.http_max_retries` / `settings.anthropic_timeout_sec`. Every
tunable is one env var away.

### Caching

- PDF cache on disk (`.cache/pdfs/<arxiv-id>.pdf` +
  `<arxiv-id>.txt`) — cited as an MVP shortcut in ADR 0002; production
  target is Redis / S3 for shared cache across replicas.
- Anthropic prompt caching — planned in Sprint 3 for the system
  prompts that repeat across every query.

### Cost

- Per-run cost tracking (per-model breakdown) in `summary.jsonl`.
- Nightly regression diff surfaces cost creep as first-class metric
  (extends to `cost_usd` in Sprint 2 per the agentic upgrade plan).
- Model routing plan: Haiku for extraction, Sonnet for synthesis,
  Opus for critic (Sprint 3).

### Failure handling

- Reader falls back to abstract when PDF fetch / extract / chunk /
  rank yield nothing (ADR 0004).
- Runner isolates per-query failures — a broken query doesn't kill
  the batch (ADR 0008).
- Runs are checkpointed to SQLite so an interrupted workflow is
  resumable by re-invoking with the same `run_id`.

### Evaluation

- 20 benchmark queries, four metrics (citation accuracy,
  faithfulness, completeness, retrieval recall).
- Nightly CI runs the benchmark, diffs against the previous night's
  baseline via `regression_diff`, fails the workflow on regressions
  > 0.10.

### Observability

- Structured JSON logs to stderr with `run_id` on every record.
- Per-run cost accumulator (per-model breakdown).
- OpenTelemetry spans opt-in via `settings.enable_tracing=true`;
  OTLP HTTP endpoint configurable.

### Security (once supervisor lands)

- Prompt-injection isolation on the reader — see
  [`05-agentic-upgrade-plan.md`](05-agentic-upgrade-plan.md) item 8.
  Not yet landed. **Flagged here so a reviewer sees we've thought
  about it, not that we've forgotten.**

## Sequencing

These interleave with the agentic upgrade plan:

- **Sprint 2 (agentic):** supervisor + verifier + evidence store.
- **Alongside Sprint 2 (portfolio):** architecture diagram + README
  demo + eval results block. All doc-only, low risk, high signal.
- **Sprint 3 (deployable):** Dockerfile + FastAPI + CI workflow +
  Production considerations README section.
- **After Sprint 3:** ruff + auto-README-updater from nightly eval.

## The reviewer's 90-second experience

By the end of Sprint 3, someone landing on the repo should:

1. **See the architecture diagram** — get the system shape in 10s.
2. **Read the one-paragraph pitch** — problem, approach, current
   state in another 10s.
3. **See the eval results table** — trust that the numbers exist.
4. **See the demo output** — trust that it produces real reports.
5. **See the CI badge green + the "Production considerations"
   section** — trust it's operationally serious.
6. **Only then dig into the code.**

That's the polish target. Everything above is in service of it.
