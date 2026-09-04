# Planning

Living log of enterprise-readiness plans, feature ideas, and roadmap for the arxiv-research-agent project.

## Index

1. [Enterprise-Readiness Gaps](01-enterprise-gaps.md) — foundation work that separates prototype from production: observability, reliability, security, config, eval, API.
2. [Feature Ideas](02-feature-ideas.md) — catalog of feature ideas grouped by category (research quality, agent architecture, data/storage, UX, enterprise).
3. [Roadmap](03-roadmap.md) — prioritized sprint-by-sprint plan.
4. [Architecture Refactors](04-architecture-refactors.md) — concrete code refactors that unlock the roadmap, mapped to current files.
5. [Agentic Upgrade Plan](05-agentic-upgrade-plan.md) — the Sprint 2 focus: converting the fixed DAG into a supervisor loop, sequenced and constrained. Written after Sprint 1 wrap; incorporates the outside review recorded in PR #19.
6. [Portfolio Polish](06-portfolio-polish.md) — architecture diagram, README demo, eval results table, Dockerfile, FastAPI endpoint, CI workflow, "Production considerations" section. Interleaves with Sprints 2-3; the presentation layer that makes the repo a resume artifact.
7. [Agent Engineering Program](../docs/agent-engineering/README.md) — active,
   forward-looking architecture and evaluation plan for adaptive compute,
   robust verification, feedback learning, post-training, deep research, and
   long-horizon agents. Unlike the historical sprint notes here, this is a
   discussion draft and does not authorize implementation.

## How to use this folder

- **Add ideas freely** — new files or new sections in existing files. Keep it a scratchpad, not a spec.
- **When a plan graduates to work**, move it to a GitHub issue / PR and link back to the planning doc that seeded it.
- **Update the roadmap** as sprints complete — mark items done inline; don't delete (this is a log).
- **Record decisions** — if an idea gets rejected, keep it with a short note on *why*. Future-you will want that.

## Current status snapshot (2026-08-27)

- **Sprints 1-5 done, plus a post-Sprint-5 hardening campaign
  through ADR 0054.** 63 merged PRs, 54 ADRs, ~1,400 tests
  (`pytest -m "not e2e"`: 1399 passed / 27 skipped). What exists on
  `main`:
  - Both workflow shapes: fixed five-agent DAG (default) and the
    flag-gated supervisor loop with verifier, evidence store, query
    refiner, and reader recovery (Sprint 2).
  - Cost controls: per-agent model routing, prompt caching, per-run
    and per-call spend caps (ADRs 0021/0022/0033/0051).
  - Production HTTP surface: FastAPI async jobs, SSE streaming, HITL
    plan review, conversations, multi-format export, API-key auth +
    rate limiting + per-principal scoping, Next.js web UI.
  - Scale-out substrate: Redis job store + pub/sub + rate limiter,
    Postgres checkpoints/conversations/caches, worker leases + job
    redriver, bounded executor + cooperative cancel.
  - Observability: JSON logs, per-run costs, OTel tracing + metrics.
  - Eval harness: 20-query benchmark, four metrics (three
    LLM-judged, citation accuracy pure-regex),
    crash-safe runner with `--resume` + `--max-budget-usd`, nightly
    regression CI. First green campaign against `main` still pending.
- **Plans in this folder are historical.** 01/04/05/06 drove Sprints
  1-5 and are essentially landed; each file carries a status note up
  top. The live log and follow-up list is the tail of
  [03-roadmap.md](03-roadmap.md).
- **Current lane**: Hetzner deployment. CPU-only Torch, the generated
  runtime lock, Next.js server-side API auth, and the Caddy production
  boundary are implemented locally. Remaining gates are reviewed PR +
  green CI, explicit approval for the exact Hetzner charge, live host
  provisioning, and one separately approved Anthropic end-to-end run.
  The cassette e2e tier and `/readyz` remain open follow-ups.
