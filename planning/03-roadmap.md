# Roadmap

Prioritized sprint-by-sprint plan. Ordered by (impact × unblocks-later-work) / effort.

## Sprint 1 (~2 weeks) — Make it observable and testable

- Structured logging + `run_id` propagation through `ResearchState`
- LangSmith or OpenTelemetry tracing
- Per-run cost tracking (token counts + $ per agent per iteration)
- Retry/backoff + timeouts on all external calls
- LangGraph checkpointing (`SqliteSaver`)
- `pydantic-settings` for typed config
- Golden query dataset (~20 queries)
- Basic eval harness: retrieval recall, citation accuracy

**Why first:** you cannot improve what you cannot measure. Everything downstream benefits — feature experiments in later sprints depend on the eval harness to know if they helped.

## Sprint 2 (~2 weeks) — Make it deployable

- FastAPI wrapper with async job model
- Streaming endpoint via SSE
- Docker + docker-compose (app, Redis, Postgres)
- GitHub Actions CI (lint, mypy, tests, smoke query)
- Paper cache (Postgres + persisted embeddings)
- Prompt-injection isolation in reader

## Sprint 3 (~2 weeks) — Raise quality ceiling

- Semantic Scholar adapter + citation graph traversal
- Parallel reader via LangGraph `Send`
- Claude prompt caching for paper corpus
- Cost-aware model routing (Haiku for extraction, Sonnet for synthesis, Opus for critique)
- Contradiction detection agent
- Richer critic feedback (topic-level)

## Sprint 4 (~2 weeks) — Ship a real product surface

- Minimal web UI (Next.js or Streamlit) with streaming
- Human-in-the-loop breakpoint after planner
- Multi-format export (PDF, DOCX)
- Follow-up conversation mode
- Slack bot (optional)

## Sprint 5+ — Enterprise moat

- Private corpus / BYO PDF
- Multi-tenancy + RBAC + SSO
- Budget controls
- Bedrock/Vertex adapters
- Reproducibility scoring, benchmark extraction

## Log

<!-- Append entries here as sprints complete or plans change. -->

- _2026-07-05_ — Roadmap drafted. No sprints started yet.
