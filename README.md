# arxiv-research-agent

A multi-agent research assistant for ML/AI papers. Takes a natural-language
research question, searches arXiv (and optionally Semantic Scholar for
citation-graph enrichment), extracts findings from each paper's full text,
synthesizes a briefing, and self-critiques for quality. Orchestrated with
LangGraph and Claude.

Under the fixed pipeline (Sprint 1 shape) it's a five-agent DAG with one
conditional edge on the critic. Behind opt-in flags it becomes an agentic
supervisor loop with runtime faithfulness verification, evidence-grounded
synthesis, and search-layer / read-layer recovery actions.

## Architecture

### Fixed pipeline — Sprint 1 baseline (default)

```mermaid
flowchart LR
    User([User query]) --> Planner
    Planner --> Search
    Search --> Reader
    Reader --> Synthesizer
    Synthesizer --> Critic
    Critic -->|approved| Output([Report + citations])
    Critic -->|revise: search / plan / synthesize| Planner
    Critic -.-> Search
    Critic -.-> Synthesizer

    Search -.reads.-> ArXiv[(arXiv API)]
    Reader -.reads.-> PDF[PDF parser<br/>+ chunker<br/>+ ranker]
    Reader -.embeds.-> Emb[MiniLM<br/>+ FAISS]

    style Critic fill:#fef3c7
    style Output fill:#dcfce7
```

Every agent reads from and writes to a shared `ResearchState`
(`src/graph/state.py`). Loops back to the planner / search / synthesizer
when the critic flags revision, capped at `settings.max_iterations`.

### Supervisor loop — Sprint 2+ (opt-in)

```mermaid
flowchart TB
    User([User query]) --> Supervisor
    Supervisor -->|plan| Planner
    Supervisor -->|search| Search
    Supervisor -->|read| Reader
    Supervisor -->|synthesize| Synthesizer
    Supervisor -->|critique| Critic
    Supervisor -->|verify<br/><i>flag</i>| Verifier
    Supervisor -->|refine_query<br/><i>flag</i>| QueryRefiner
    Supervisor -->|stop| Output([Report + stop_reason])

    Planner --> Supervisor
    Search --> Supervisor
    Reader --> Supervisor
    Synthesizer --> Supervisor
    Critic --> Supervisor
    Verifier --> Supervisor
    QueryRefiner --> Supervisor

    style Supervisor fill:#dbeafe
    style Verifier fill:#e9d5ff
    style QueryRefiner fill:#e9d5ff
    style Output fill:#dcfce7
```

Every action node hands control back to the supervisor, which picks the
next action from a strict enum with budget short-circuits and fail-safe
fallback routing. See ADR
[0014](docs/decisions/0014-supervisor-loop-behind-flag.md).

### Shared substrate

```mermaid
flowchart LR
    subgraph "Agents"
        A[planner / search / reader<br/>synthesizer / critic<br/>+ verifier / query_refiner<br/>+ supervisor]
    end
    subgraph "Tools"
        T[arXiv search · Semantic Scholar<br/>PDF parser · section chunker<br/>FAISS ranker · MiniLM embeddings]
    end
    subgraph "State"
        S[ResearchState<br/>papers · analyses · evidence<br/>draft · citations · critique<br/>next_action · verifier_recommendation<br/>tried_search_queries · recovery signals]
    end
    subgraph "Observability"
        O[JSON logs · run_id<br/>per-run cost accumulator<br/>OTel spans · SQLite checkpoints]
    end
    subgraph "Eval"
        E[20-query benchmark<br/>citation accuracy · faithfulness<br/>completeness · retrieval recall<br/>nightly regression diff]
    end
    A <--> S
    A <--> T
    A --> O
    O --> E
```

- **Agents** read from and write to state; the supervisor picks the next
  agent every turn under the loop.
- **Tools** are pure functions the agents call; no LLM cost beyond the
  callers.
- **Observability** runs alongside every call; per-run cost with cache-
  read / cache-write breakdown when Anthropic prompt caching is on.
- **Eval** consumes the observability output; nightly CI diffs against
  the previous night's baseline and fails on regressions > 0.10.

## What lives behind flags

Every feature added after Sprint 1 is behind an independent flag so
comparisons against the Sprint 1 baseline stay apples-to-apples. Full
list in `src/config.py`.

| Flag | Sprint | What it enables | ADR |
|---|---|---|---|
| `enable_supervisor` | 2 | Observe-decide-act loop replaces the fixed DAG | [0014](docs/decisions/0014-supervisor-loop-behind-flag.md) |
| `enable_verifier` | 2 | `verify` action + runtime faithfulness judge | [0015](docs/decisions/0015-verifier-agent-runtime-faithfulness.md) |
| `enable_evidence_store` | 2 | Reader emits `EvidenceClaim`s; verifier judges chunks | [0016](docs/decisions/0016-evidence-store-source-text-verifier.md) / [0017](docs/decisions/0017-synthesizer-evidence-swap.md) |
| `enable_query_refiner` | 2 | `refine_query` recovery action | [0018](docs/decisions/0018-query-refiner-recovery-action.md) |
| `enable_reader_recovery` | 2 | Reader flags gaps; ranker biases re-reads by section | [0019](docs/decisions/0019-reader-requests-more-chunks.md) |
| `enable_prompt_isolation` | 2 | Untrusted-content tags + sanitization on reader | [0020](docs/decisions/0020-prompt-injection-isolation-reader.md) |
| `<agent>_model` (7 fields) | 3 | Per-agent Claude model routing | [0021](docs/decisions/0021-cost-aware-model-routing.md) |
| `enable_prompt_caching` | 3 | Anthropic ephemeral cache on system prompts | [0022](docs/decisions/0022-anthropic-prompt-caching.md) |
| `enable_semantic_scholar` | 3 | One-hop reference enrichment on top of arXiv | [0023](docs/decisions/0023-semantic-scholar-citation-graph.md) |

Full design log in
[`docs/decisions/`](docs/decisions/README.md); the roadmap lives in
[`CLAUDE-Agent-Proj-1.md`](CLAUDE-Agent-Proj-1.md).

## Demo

See [`docs/demo.md`](docs/demo.md) for a full example run: the query,
the report the workflow produced, and the per-query line from
`summary.jsonl` with metrics + cost + latency.

## Setup

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Copy `.env.example` to `.env` and add your Anthropic API key:

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

## Run

```bash
python -m src.main "What are the latest approaches to reducing hallucination in LLMs?"
```

The final markdown report is printed to stdout and saved to
`outputs/report_<timestamp>.md`.

### Offline mode

If arXiv is rate-limiting or unavailable, force the built-in mock
papers instead of a live search:

```bash
USE_MOCK_DATA=true python -m src.main "..."
```

### With the supervisor loop and verifier

```bash
ENABLE_SUPERVISOR=true \
ENABLE_VERIFIER=true \
ENABLE_EVIDENCE_STORE=true \
python -m src.main "..."
```

## HTTP API

FastAPI surface layered on top of the workflow. Async job model —
submit a query, get a `job_id`, poll for the result or stream
events over Server-Sent Events. Full design in ADRs
[0025](docs/decisions/0025-fastapi-async-job-model.md) and
[0026](docs/decisions/0026-sse-streaming-endpoint.md).

```bash
python -m src.api.serve                       # bind 127.0.0.1:8000
# or override host/port via env:
API_HOST=0.0.0.0 API_PORT=8080 python -m src.api.serve
```

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/research` | Submit a query. Returns 202 with `job_id`, `status_url`, `stream_url`. |
| `GET`  | `/research/{job_id}` | Full lifecycle snapshot (status, result, error, cost, metrics). |
| `GET`  | `/research/{job_id}/stream` | SSE event stream: `job_started` → N × `node_completed` → terminal frame. |
| `GET`  | `/healthz` | Liveness + concurrency headroom. |
| `GET`  | `/docs` | Auto-generated OpenAPI docs. |

### Example

```bash
# submit
curl -s -X POST localhost:8000/research \
  -H 'content-type: application/json' \
  -d '{"query": "chain-of-verification for hallucination"}' | jq .
# → {"job_id": "abc123...", "status_url": "/research/abc123...", ...}

# poll
curl -s localhost:8000/research/abc123... | jq .status

# stream
curl -N localhost:8000/research/abc123.../stream
# → event: job_started
#    data: {"job_id": "abc123...", "query": "..."}
#    ...
#    event: job_completed
#    data: {"iterations": 1, "quality_score": 0.9, "cost_usd": 0.087, ...}
```

Concurrency is bounded per process by
`API_MAX_CONCURRENT_JOBS` (default 10) via `asyncio.Semaphore`;
per-job timeout by `API_JOB_TIMEOUT_SEC` (default 600). Jobs live
in an in-memory store by default; set `JOB_STORE=redis` +
`REDIS_URL=redis://...` to swap in the Redis-backed store for
horizontal scaling and durability across worker restarts
(compose stack below wires this up automatically).

## Run in Docker

Full compose stack — app + Redis (JobStore) + Postgres (paper cache,
Sprint 4 PR 4). See ADR
[0027](docs/decisions/0027-docker-compose-redis-job-store.md) for
image design + service topology.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
docker compose up --build
# → http://localhost:8000/healthz  → 200
# → http://localhost:8000/docs     → OpenAPI UI
```

`ANTHROPIC_API_KEY` is the only required host variable. The compose
file publishes `APP_PORT` (default 8000) to the host; Redis and
Postgres stay on the internal compose network. Named volumes
`redis-data` + `postgres-data` persist state across `docker compose
down`; `down -v` wipes them.

Multi-worker uvicorn is safe under `JOB_STORE=redis` — every worker
reads/writes the shared Redis-backed store. Note that SSE streaming
requires job affinity (see ADR 0027 Consequences); polling works
across workers unconditionally.

## Eval

Twenty benchmark queries covering hallucination, retrieval, alignment,
reasoning, efficiency, and safety topics
(`src/eval/benchmark_queries.py`). Four LLM-judged metrics — citation
accuracy, faithfulness, completeness, retrieval recall — plus critic
score, iteration count, LLM call count, and cost per query in
`summary.jsonl`. Full eval design in [`docs/eval.md`](docs/eval.md).

```bash
python -m src.eval.runner              # run the benchmark
python -m src.eval.regression_diff \
  outputs/eval/<baseline>/summary.jsonl \
  outputs/eval/<candidate>/summary.jsonl
```

## Tests

```bash
pytest tests/ -q
```

560+ tests across unit + integration tiers (see
[`docs/testing.md`](docs/testing.md) for the strategy).

## Project status

**Sprint 4 in progress.** Sprint 1 shipped the observability + eval
substrate; Sprint 2 shipped the supervisor loop + verifier +
evidence store + recovery actions + prompt-injection isolation;
Sprint 3 shipped cost-aware model routing + Anthropic prompt
caching + Semantic Scholar citation-graph enrichment; Sprint 4 is
now shipping the deployable slice — PR CI (ADR 0024) + FastAPI /
async job / SSE surface (ADRs 0025, 0026) already merged. Next up:
Docker + docker-compose + Postgres-backed paper cache.

Full status and phase-by-phase plan in
[`CLAUDE-Agent-Proj-1.md`](CLAUDE-Agent-Proj-1.md).
