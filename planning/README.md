# Planning

Living log of enterprise-readiness plans, feature ideas, and roadmap for the arxiv-research-agent project.

## Index

1. [Enterprise-Readiness Gaps](01-enterprise-gaps.md) — foundation work that separates prototype from production: observability, reliability, security, config, eval, API.
2. [Feature Ideas](02-feature-ideas.md) — catalog of feature ideas grouped by category (research quality, agent architecture, data/storage, UX, enterprise).
3. [Roadmap](03-roadmap.md) — prioritized sprint-by-sprint plan.
4. [Architecture Refactors](04-architecture-refactors.md) — concrete code refactors that unlock the roadmap, mapped to current files.

## How to use this folder

- **Add ideas freely** — new files or new sections in existing files. Keep it a scratchpad, not a spec.
- **When a plan graduates to work**, move it to a GitHub issue / PR and link back to the planning doc that seeded it.
- **Update the roadmap** as sprints complete — mark items done inline; don't delete (this is a log).
- **Record decisions** — if an idea gets rejected, keep it with a short note on *why*. Future-you will want that.

## Current status snapshot

- Baseline architecture: 5-agent LangGraph pipeline (planner → search → reader → synthesizer → critic), Claude reasoning, arXiv + FAISS retrieval.
- Recent work: full-text reader pipeline, FAISS chunk ranker, PDF parser.
- Next up (recommended): Sprint 1 from the roadmap — observability + eval — before layering more features.
