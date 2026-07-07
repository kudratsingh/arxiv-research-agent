# Planning

Living log of enterprise-readiness plans, feature ideas, and roadmap for the arxiv-research-agent project.

## Index

1. [Enterprise-Readiness Gaps](01-enterprise-gaps.md) — foundation work that separates prototype from production: observability, reliability, security, config, eval, API.
2. [Feature Ideas](02-feature-ideas.md) — catalog of feature ideas grouped by category (research quality, agent architecture, data/storage, UX, enterprise).
3. [Roadmap](03-roadmap.md) — prioritized sprint-by-sprint plan.
4. [Architecture Refactors](04-architecture-refactors.md) — concrete code refactors that unlock the roadmap, mapped to current files.
5. [Agentic Upgrade Plan](05-agentic-upgrade-plan.md) — the Sprint 2 focus: converting the fixed DAG into a supervisor loop, sequenced and constrained. Written after Sprint 1 wrap; incorporates the outside review recorded in PR #19.
6. [Portfolio Polish](06-portfolio-polish.md) — architecture diagram, README demo, eval results table, Dockerfile, FastAPI endpoint, CI workflow, "Production considerations" section. Interleaves with Sprints 2-3; the presentation layer that makes the repo a resume artifact.

## How to use this folder

- **Add ideas freely** — new files or new sections in existing files. Keep it a scratchpad, not a spec.
- **When a plan graduates to work**, move it to a GitHub issue / PR and link back to the planning doc that seeded it.
- **Update the roadmap** as sprints complete — mark items done inline; don't delete (this is a log).
- **Record decisions** — if an idea gets rejected, keep it with a short note on *why*. Future-you will want that.

## Current status snapshot (2026-07-07)

- **Sprint 1 done.** 20 merged PRs, 12 ADRs, 262 tests. What landed:
  - Full-text reader pipeline (PDF parser + chunker + FAISS chunk-ranker + reader with abstract fallback).
  - Anthropic migration (Sonnet 4.6 default) + SDK-native retry + `urllib3.Retry` on arXiv/PDF.
  - Typed frozen config via `pydantic-settings`.
  - Structured JSON logging with `run_id` propagation + per-run cost tracking + OTel tracing (opt-in).
  - LangGraph `SqliteSaver` checkpointing on by default.
  - Eval harness: 20-query benchmark, four metrics (citation accuracy, completeness, faithfulness, retrieval recall), sequential runner with error isolation, regression differ, nightly CI that fails on regression.
- **Baseline architecture is still agentic-lite** — five agents in a fixed DAG with one conditional edge on the critic. That's the honest label; the loop upgrade is next.
- **Next up (recommended)**: [05-agentic-upgrade-plan.md](05-agentic-upgrade-plan.md) — Sprint 2 turns the DAG into a supervisor loop. Freeze a baseline eval first (3 repeats), then land supervisor + verifier + evidence store behind flags, then measure.
