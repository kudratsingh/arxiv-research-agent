# Planning

Living log of enterprise-readiness plans, feature ideas, and roadmap for the arxiv-research-agent project.

## Index

1. [Enterprise-Readiness Gaps](01-enterprise-gaps.md) — foundation work that separates prototype from production: observability, reliability, security, config, eval, API.
2. [Feature Ideas](02-feature-ideas.md) — catalog of feature ideas grouped by category (research quality, agent architecture, data/storage, UX, enterprise).
3. [Roadmap](03-roadmap.md) — prioritized sprint-by-sprint plan.
4. [Architecture Refactors](04-architecture-refactors.md) — concrete code refactors that unlock the roadmap, mapped to current files.
5. [Agentic Upgrade Plan](05-agentic-upgrade-plan.md) — the Sprint 2 focus: converting the fixed DAG into a supervisor loop, sequenced and constrained. Written after Sprint 1 wrap; incorporates the outside review recorded in PR #19.
6. [Portfolio Polish](06-portfolio-polish.md) — architecture diagram, README demo, eval results table, Dockerfile, FastAPI endpoint, CI workflow, "Production considerations" section. Interleaves with Sprints 2-3; the presentation layer that makes the repo a resume artifact.
7. [Learning Platform](07-learning-platform/STATUS.md) — the guided-reading
   wedge: vision, learning agent, content, architecture roadmap, strategy
   alternatives and the W-series work orders, with the gate W1/W2 evidence
   packs. [`STATUS.md`](07-learning-platform/STATUS.md) is the index; the rest
   is only navigable through it.
8. [Assurance](08-assurance/STATUS.md) — the assurance campaign: charter,
   baseline, standards, architecture, work orders and gates, plus the gate-A3
   evidence pack. [`STATUS.md`](08-assurance/STATUS.md) is the index and the
   live record of what is still open.
9. [Agent Capability](09-agent-capability/STATUS.md) — the capability lane
   that built the gateway request profiles, the verify-and-repair and
   orchestrator-workers shapes, the deterministic compute controller, the
   listwise selector and marginal stop, and the SDK 1.x upgrade. Charter,
   work orders, and the lane's execution log.
10. [Agent Engineering Program](../docs/agent-engineering/README.md) — the
    forward-looking architecture and evaluation plan for adaptive compute,
    robust verification, feedback learning, post-training, deep research, and
    long-horizon agents, together with the four P0 contract RFCs. It is a
    planning package plus the contracts that have landed against it; it does
    not authorize implementation, and nothing in it authorizes spend.

## How to use this folder

- **Add ideas freely** — new files or new sections in existing files. Keep it a scratchpad, not a spec.
- **When a plan graduates to work**, move it to a GitHub issue / PR and link back to the planning doc that seeded it.
- **Update the roadmap** as sprints complete — mark items done inline; don't delete (this is a log).
- **Record decisions** — if an idea gets rejected, keep it with a short note on *why*. Future-you will want that.

## Current status snapshot (2026-09-17)

- **Sprints 1-5 done, then four campaigns: the post-Sprint-5 hardening
  chain (through ADR 0054), the frontend revamp, the assurance lane, and
  the agent-engineering / agent-capability lanes (ADRs 0075-0096).** 253
  merged PRs and 96 ADRs (`gh search`, `ls docs/decisions/0*.md | wc
  -l`); `pytest --collect-only -q` collects 5,380 tests. What exists on
  `main`:
  - Four workflow shapes: the fixed five-agent DAG (default), the
    flag-gated supervisor loop with verifier / evidence store / query
    refiner / reader recovery (Sprint 2), `fixed_verify_repair` (ADR
    0076) and `orchestrated_workers` (ADR 0086). The last two are off by
    default, and `COMPUTE_CONTROLLER=deterministic` can select a shape
    per job instead of per process (ADRs 0085/0091).
  - Cost controls: per-agent model routing, prompt caching, per-run
    and per-call spend caps (ADRs 0021/0022/0033/0051), plus per-agent
    reasoning effort (ADR 0077).
  - Production HTTP surface: FastAPI async jobs, SSE streaming, HITL
    plan review, conversations, multi-format export, API-key auth +
    rate limiting + per-principal scoping, Next.js web UI.
  - Scale-out substrate: Redis job store + pub/sub + rate limiter,
    Postgres checkpoints/conversations/caches, worker leases + job
    redriver, bounded executor + cooperative cancel.
  - Observability: JSON logs, per-run costs, OTel tracing + metrics.
  - Eval harness: 20-query benchmark, **five** metrics (faithfulness,
    completeness and retrieval recall LLM-judged;
    `citation_resolution_rate` deterministic and the one the gate reads;
    `citation_accuracy` pure regex, diagnostic only), crash-safe runner
    with `--resume` + `--max-budget-usd`.
  - The policy-experiment layer: four typed contracts (`src/contracts/`),
    the digest-verified benchmark registry (`eval_registry/`), the
    campaign harness `python -m src.campaign
    plan|dry-run|run|resume|status|report` with five arms A-E, mock mode
    over the whole research graph, a deterministic mock judge, and the
    offline calibration packets `python -m src.calibration
    packets|ingest`.
- **No funded run has ever happened.** The nightly eval workflow and the
  nightly Lighthouse workflow are both `disabled_manually` at the
  repository; the eval harness has never produced a `summary.jsonl`, so
  the regression gate has never compared two real runs and there are no
  quality numbers anywhere in this repo. The full `20 x 3 x 5` campaign
  matrix runs end to end under `USE_MOCK_DATA=true` at exactly
  `$0.000000`, which proves the contracts and the denominators and says
  nothing about whether any arm is better.
- **Plans in this folder are historical.** 01/04/05/06 drove Sprints
  1-5 and are essentially landed; each file carries a status note up
  top. The live log and follow-up list is the tail of
  [03-roadmap.md](03-roadmap.md); the campaign status pages are
  [07-learning-platform/STATUS.md](07-learning-platform/STATUS.md),
  [08-assurance/STATUS.md](08-assurance/STATUS.md) and
  [09-agent-capability/STATUS.md](09-agent-capability/STATUS.md).
- **Open and owner-gated**, nearly all of it on cost: the funded
  repeated policy baseline (W12), the funded live smoke of the SDK 1.x
  gateway path (CAP-06), Hetzner provisioning, MT-01 multi-tenancy, and
  the human screen-reader pass. `/readyz` shipped alongside `/healthz`;
  the cassette e2e tier is still an open follow-up — the Python `e2e`
  tier exists and gates every PR, but it runs on mock mode rather than
  recorded provider responses.
- **Settled 2026-09-17: the licensing posture.** W-OD-3 is decided —
  **no licence, all rights reserved.** No `LICENSE` file is adopted and
  no grant is offered; the repository is published to be read, not
  reused. `README.md` §Rights is the statement. It does not discharge
  PyMuPDF's AGPL §13 obligation, which runs from an operator to the
  users a deployment serves (`docs/development.md` §Dependency
  licensing).
