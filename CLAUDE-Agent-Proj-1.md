# Multi-Agent Research Assistant for ML/AI Papers

## Project Overview
A multi-agent system that takes a natural language research question
about ML/AI, searches arXiv (optionally enriched via Semantic Scholar's
citation graph), extracts key findings from paper full text, synthesizes
a research briefing, and self-critiques for quality — orchestrated via
LangGraph with Claude as the reasoning engine. The workflow ships behind
a production HTTP surface: an async FastAPI job API with SSE streaming,
human-in-the-loop plan review, API-key auth with per-principal scoping,
multi-format export, conversation mode, and a Next.js web UI — all
deployable via Docker Compose with Redis + Postgres backends.

## Documentation

Excellent, thorough documentation is a non-negotiable requirement for
this project. Every significant module, agent, tool, and design decision
must be documented so that (a) a new engineer can be productive on day
one and (b) design intent survives contact with future changes.

To keep this file focused, detailed docs live in `docs/`. This file
(`CLAUDE-Agent-Proj-1.md`) is the top-level index — it summarizes the
system, states the principles, and points into `docs/` for anything
that needs more space.

Documentation requirements:
- Every module has a docstring explaining what it does and why.
- Every public function / class has a docstring with Args, Returns, and
  (where relevant) Raises sections.
- Every non-trivial architectural or technical decision gets an ADR in
  `docs/decisions/` (format: `docs/decisions/TEMPLATE.md`).
- Every agent gets a page in `docs/agents/<name>.md` covering inputs,
  outputs, prompt design, and known failure modes.
- Every phase deliverable is tracked in
  [`planning/03-roadmap.md`](planning/03-roadmap.md) — the single
  source of truth for sprint status.
- Every non-trivial change updates the relevant doc in the **same PR**.
  Doc drift is a bug — the reviewer should request updates if a diff
  changes behavior without changing docs.
- Docs describe `main` as it is. Planned work is labelled as planned.

### Docs Map

| Doc | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | The two workflow shapes, the API layer, the storage matrix |
| [`docs/agents/`](docs/agents/) | One page per agent: inputs, outputs, prompts, failure modes |
| [`docs/decisions/`](docs/decisions/README.md) | ADRs 0001-0037 — every non-trivial decision, indexed |
| [`docs/testing.md`](docs/testing.md) | Flat test layout, markers, what CI runs, the unbuilt e2e tier |
| [`docs/development.md`](docs/development.md) | Setup, Makefile targets, troubleshooting |
| [`docs/security.md`](docs/security.md) | Threat model, prompt-injection defenses |
| [`docs/eval.md`](docs/eval.md) | Benchmark, LLM-judge metrics, nightly regression CI |
| [`docs/demo.md`](docs/demo.md) | Canonical end-to-end example run |
| [`planning/03-roadmap.md`](planning/03-roadmap.md) | Sprint-by-sprint log + what's next |

## Testing

Every piece of code merged to `main` ships with tests. Untested code
does not merge. Full strategy in [`docs/testing.md`](docs/testing.md).
Summary:

- **Layout**: all tests live flat in `tests/test_*.py` — one test
  module per source module. ~800 tests on `main`.
- **Tiers via markers**, not directories: `unit` and `integration`
  markers are registered in `pyproject.toml`; the `e2e` marker is
  reserved for a cassette-based tier that is **planned, not built**.
  Most tests carry no marker, so marker-filtered runs
  (`pytest -m unit`) select only a small explicitly-marked subset.
- **The merge gate is the whole suite**: CI runs
  `pytest -m "not e2e"` (everything, today) plus ruff, strict mypy on
  `src/`, a Docker build, and the `web/` typecheck/lint/test/build.
  See ADR 0024 and `.github/workflows/ci.yml`.
- **No live services in tests**: fakeredis for Redis,
  `pytest-postgresql` for Postgres, monkeypatched `call_llm_json` for
  Claude, canned fixtures for arXiv / PDFs.
- **LLM code**: assert on response structure and prompt shape, never
  on exact model output. Pipeline-level quality is guarded by the
  nightly eval workflow, not the PR suite.

## Tech Stack
- **LLM**: Claude (Anthropic API via `anthropic` Python SDK, SDK-native
  retry; per-agent model routing + prompt caching behind flags)
- **Orchestration**: LangGraph (fixed pipeline or supervisor loop;
  SQLite / Postgres checkpointing)
- **API**: FastAPI + uvicorn — async job model, SSE streaming, HITL,
  auth + rate limiting, multi-format export (md / pdf / docx)
- **Paper Search**: arXiv API (`arxiv` package) + optional Semantic
  Scholar citation-graph enrichment
- **PDF Parsing**: PyMuPDF (`fitz`)
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` + FAISS
  (`faiss-cpu`), optional Postgres-backed embedding cache
- **Storage**: Redis (job store, SSE/HITL pub/sub, rate limiter) and
  Postgres via `psycopg` (checkpoints, conversations, paper +
  embedding caches) — all pluggable, in-memory/disk defaults for
  local dev
- **Web UI**: Next.js + Tailwind (`web/`), tested with Vitest
- **Config**: `pydantic-settings` typed settings surface (`src/config.py`,
  ADR 0011) loading from env vars + `.env`
- **Observability**: structured JSON logging, per-run cost tracking,
  opt-in OpenTelemetry tracing
- **Deploy**: Dockerfile + docker-compose (API + web + Redis + Postgres)

## Directory Structure
```
arxiv-research-agent/
├── CLAUDE-Agent-Proj-1.md      # This file — the index
├── README.md
├── pyproject.toml              # Deps + pytest/mypy/ruff config
├── Makefile                    # Common targets (see docs/development.md)
├── Dockerfile
├── docker-compose.yml          # API + web + Redis + Postgres stack
├── .env.example                # ANTHROPIC_API_KEY etc. (never commit .env)
├── .github/workflows/          # ci.yml (per-PR), eval-nightly.yml
├── src/
│   ├── agents/                 # planner, search, reader, synthesizer,
│   │                           # critic, supervisor, verifier, query_refiner
│   ├── api/                    # FastAPI surface: app factory, routes,
│   │   │                       # jobs, runner, streaming, auth,
│   │   │                       # conversations, retriever, redis_store,
│   │   │                       # schemas, serve
│   │   └── exporters/          # md / pdf / docx report renderers
│   ├── graph/
│   │   ├── state.py            # ResearchState TypedDict + typed sub-schemas
│   │   └── workflow.py         # LangGraph wiring: both shapes + checkpointing
│   ├── tools/                  # arxiv_search, pdf_parser, chunker,
│   │                           # chunk_ranker, embeddings, embedding_cache,
│   │                           # paper_cache, postgres_pool, http_session,
│   │                           # semantic_scholar
│   ├── eval/                   # benchmark_queries, metrics, runner,
│   │                           # regression_diff, readme_update
│   ├── observability/          # JSON logging, cost tracking, OTel tracing
│   ├── security/               # prompt_isolation (ADR 0020 / 0033)
│   ├── config.py               # pydantic-settings typed config surface
│   ├── llm.py                  # Shared Anthropic client + JSON helper
│   └── main.py                 # CLI entry point
├── tests/                      # Flat test_*.py modules (~800 tests)
├── web/                        # Next.js UI (app/, components/, lib/, tests/)
├── docs/                       # Deep docs — see the Docs Map above
├── planning/                   # Roadmap + sprint plans
└── outputs/                    # Generated reports + eval runs (gitignored)
```

## Architecture

Two workflow shapes over the same `ResearchState`, selected by
`settings.enable_supervisor`:

```
Fixed pipeline (default):
User Query → PLANNER → SEARCH → READER → SYNTHESIZER → CRITIC → Output
                ↑         ↑                    ↑            │
                └─────────┴────────────────────┴────────────┘
                  critic routes revisions (max_iterations cap)

Supervisor loop (flag-gated):
START → SUPERVISOR → <action> → SUPERVISOR → ... → stop
        actions: plan/search/read/synthesize/critique/stop
        (+ verify, refine_query behind their own flags)
```

The HTTP layer wraps the compiled workflow in an async job model —
`POST /research` → 202 + `job_id`, SSE streaming, HITL plan review,
conversations, export — with pluggable Redis/Postgres backends for
every stateful concern. Full picture, including the storage matrix
and which setting selects each backend:
[`docs/architecture.md`](docs/architecture.md).

The full state schema lives in `src/graph/state.py` (`ResearchState`
plus typed sub-schemas `PaperMetadata`, `PaperAnalysis`, `Citation`,
`EvidenceClaim`) — the docstrings there document which flags populate
which fields.

## Agents

One page per agent in [`docs/agents/`](docs/agents/):

- [`planner`](docs/agents/planner.md) — decomposes the query into
  sub-questions + arXiv search queries; consumes conversation
  `prior_context` and critic feedback on revisions.
- [`search`](docs/agents/search.md) — arXiv search, dedup, optional
  S2 citation-graph enrichment, FAISS relevance ranking.
- [`reader`](docs/agents/reader.md) — PDF → section-aware chunks →
  ranked excerpts → structured per-paper analysis; abstract fallback;
  evidence claims, recovery signals, and prompt isolation behind flags.
- [`synthesizer`](docs/agents/synthesizer.md) — findings → markdown
  briefing with citations; evidence-grounded path behind a flag.
- [`critic`](docs/agents/critic.md) — five-dimension scoring; routes
  revisions to planner / search / synthesizer below the 0.7 bar.
- [`supervisor`](docs/agents/supervisor.md) — flag-gated loop
  controller with strict action enum + budget short-circuits.
- [`verifier`](docs/agents/verifier.md) — flag-gated runtime
  faithfulness check with recovery recommendations.
- [`query_refiner`](docs/agents/query_refiner.md) — flag-gated
  search-recovery action producing fresh, deduped queries.

## Conventions
- Use the `anthropic` SDK directly for Claude API calls (not
  langchain-anthropic) — ADR 0001. All calls go through `src/llm.py`.
- All agents are pure functions: take ResearchState, return partial
  state updates.
- All tunables live in `src/config.py` (`pydantic-settings`, ADR 0011)
  and map to env vars loaded from `.env` — no string-typed env reads
  at call sites.
- Type hints on everything; `mypy --strict` is green on `src/`.
- Docstrings on all public functions.
- Keep agent system prompts in the agent files (not separate config).

## Development Workflow

We land work on feature branches and open PRs against `main` — no
direct pushes to `main`.

Branch naming: `<type>/<slug>` — e.g. `feat/pdf-parser`,
`fix/arxiv-timeout`, `docs/readme`, `chore/deps-bump`,
`test/critic-routing`.

PR requirements:
- **Bundle related concerns into one PR.** Cluster changes by subsystem
  (all "observability core" pieces together), by architectural theme
  (a foundation + its natural first consumers), or by sprint slice
  (all Sprint 1 reliability items). ~400-800 additions is the sweet
  spot; smaller PRs are fine for genuinely isolated fixes. **Do not
  fragment cohesive work into nano-PRs** — the review overhead
  outweighs the granularity signal.
- Do not bundle *unrelated* concerns (a doc-only change alongside a
  bug fix). Cohesion still matters; this is not a license for
  grab-bag PRs.
- Title is concise and describes what changed (under 70 chars).
- Body explains the *why* (motivation, tradeoffs), links related issues,
  and includes a short test plan.
- Tests and docs for the diff ship in the same PR (per the Testing and
  Documentation mandates above). The full suite
  (`pytest tests/ -m "not e2e"`), `mypy --strict src/`, and
  `ruff check` must pass locally before opening the PR.
- Squash-merge to keep `main` history linear and each PR a single commit.

## Commands

Everything goes through the `Makefile`. Common targets:

```bash
make install-dev          # fresh venv + runtime + dev deps
make test-all             # full suite — matches the CI gate
make typecheck            # mypy src/
make run QUERY='What are the latest approaches to reducing hallucination in LLMs?'
make eval                 # batch-run the benchmark
```

> Note: `make test` currently runs only the explicitly-marked `unit`
> subset (~55 tests), **not** the CI gate — see the "known trap" in
> [`docs/testing.md`](docs/testing.md). Use `make test-all` (or
> `pytest tests/ -q -m "not e2e"`) before opening a PR.

Serving the API locally: `python -m src.api.serve` (or
`docker compose up` for the full stack). Full setup, targets, and
troubleshooting in [`docs/development.md`](docs/development.md).

## Current Status

Sprints 1-5 are complete, followed by a post-Sprint-5 production
hardening chain. 37 ADRs (0001-0037), ~800 tests, per-PR CI (lint +
strict mypy + full test suite + Docker + web), nightly LLM-judged eval
CI. The dated, per-merge log — and the authoritative list of what's
next — lives in [`planning/03-roadmap.md`](planning/03-roadmap.md).

- **Sprint 1 — observable + testable**: eval pipeline (20-query
  benchmark, 4 LLM-judge metrics, nightly regression CI), typed
  config, structured logging + cost tracking, OTel tracing,
  checkpointing, retries. ADRs 0001-0013.
- **Sprint 2 — go agentic**: supervisor loop, verifier, evidence
  store, evidence-grounded synthesizer, query refiner, reader
  recovery, reader prompt-injection isolation — each behind an
  independent flag so every combination is A/B-measurable against the
  Sprint 1 baseline. ADRs 0014-0020.
- **Sprint 3 — cost + retrieval**: per-agent model routing, Anthropic
  prompt caching, Semantic Scholar citation-graph enrichment. ADRs
  0021-0023.
- **Sprint 4 — deployable**: per-PR CI, FastAPI async job model, SSE
  streaming, Docker Compose with Redis job store, Postgres paper +
  embedding caches. ADRs 0024-0028.
- **Sprint 5 — product surface**: Next.js web UI, HITL plan review,
  multi-format export (md/pdf/docx), conversation mode with
  prior-context retrieval. ADRs 0029-0032.
- **Post-Sprint-5 hardening**: safety bundle (auth, rate limiting,
  cost-cap enforcement, PDF byte cap, prior-context isolation — ADR
  0033), Postgres checkpointer + cross-worker HITL (ADR 0034),
  cross-worker SSE via Redis pub/sub (ADR 0035), per-principal store
  scoping (ADR 0036), Redis rate limiter + hot-reloadable keystore
  (ADR 0037).

Open follow-ups are tracked at the tail of the roadmap log — notably
the job redriver on restart, model-routing defaults, the e2e cassette
tier (see [`docs/testing.md`](docs/testing.md)), and the admin cleanup
migration for legacy NULL-owner rows.
