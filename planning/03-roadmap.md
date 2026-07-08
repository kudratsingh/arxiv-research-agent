# Roadmap

Prioritized sprint-by-sprint plan. Ordered by (impact × unblocks-later-work) / effort.

## Sprint 1 (~2 weeks) — Make it observable and testable — **DONE**

- [x] Structured logging + `run_id` propagation through `ResearchState`  (PR #18)
- [x] OpenTelemetry tracing (Sprint 1 finish PR, off by default)
- [x] Per-run cost tracking (tokens + USD, per-model breakdown, in `summary.jsonl`)
- [x] Retry/backoff + timeouts on all external calls (Anthropic SDK-native + `urllib3.Retry` for arXiv/PDF)
- [x] LangGraph checkpointing (`SqliteSaver`, on by default, `.cache/checkpoints.sqlite`)
- [x] `pydantic-settings` for typed config (frozen, validated, 20+ fields)
- [x] Golden query dataset (20 queries across 12+ domains — was 10, expanded in Sprint 1 finish)
- [x] Basic eval harness: retrieval recall + citation accuracy + completeness + faithfulness
- [x] Nightly eval CI with regression detection + threshold-driven failure

**Sprint 1 accomplishment**: 20 merged PRs, 12 ADRs, 262 tests, four LLM-judged metrics with a working regression differ. The measurement substrate is in place — everything from here on ships with a "did it help?" number.

## Sprint 2 (~2 weeks) — Go agentic (loop engineering)

Reframed based on the outside review (recorded in
[`05-agentic-upgrade-plan.md`](05-agentic-upgrade-plan.md)). The FastAPI /
Docker / paper-cache items originally scoped here move to Sprint 3 —
loop engineering is a bigger interview-signal win and the eval harness
built in Sprint 1 is what makes measuring the loop upgrade possible.

- Freeze a baseline eval run (3 repeats, same commit) as the
  before-picture we'll compare the supervisor loop against.
- Extend `regression_diff` `METRIC_FIELDS` with `iterations`,
  `llm_calls`, and `cost_usd` so the harness catches loop-induced
  cost creep.
- `src/agents/supervisor.py`: single-LLM-call decider with a strict
  enum action space (`plan | search | read | verify | synthesize |
  critique | stop`). Behind `settings.enable_supervisor: bool = False`.
  Fixed pipeline stays as the default. **DONE — ADR 0014.**
- `src/agents/verifier.py`: promote ADR 0007's faithfulness judge
  into an in-loop node. Adds `verify` to the supervisor's action
  space; emits `verified / unsupported_claims / missing_evidence /
  recommended_action`. Behind `settings.enable_verifier: bool =
  False`, independent of `enable_supervisor` so the two features can
  be A/B'd separately against the Sprint 1 baseline. **DONE — ADR
  0015.**
- `src/graph/state.py`: `EvidenceClaim` TypedDict with
  `source_text` + `section` + `relevance_score` fields so verifier
  judges against chunks, not abstracts. Reader emits claims under
  `settings.enable_evidence_store`; verifier picks its dossier at
  call time. **DONE (5a) — ADR 0016.**
- Synthesizer prefers `state.evidence` over `paper_analyses` when
  populated; grounded prompt forbids filling gaps from abstracts.
  Same flag as 5a. Report output shape unchanged so downstream
  metrics keep working. **DONE (5b) — ADR 0017.**
- `ResearchState` extensions: `next_action`, `tool_history`,
  `open_questions`, `evidence`, `stop_reason`,
  `cost_budget_remaining`, `iteration_count_per_tool`.
- Budget enforcement: `max_cost_usd`, `max_search_rounds`,
  `max_reader_rounds` become supervisor stop conditions with
  recorded `stop_reason`.
- Prompt-injection guardrails on the reader — becomes an
  agent-control risk once routing depends on PDF content.

## Sprint 3 (~2 weeks) — Recovery actions + retrieval iteration

- `src/agents/query_refiner.py`: rewrites failed search queries
  using critic feedback + evidence gaps. Enables the supervisor's
  "search again" branch to actually try something different.
- Reader requests more chunks: when analysis flags missing context,
  the reader emits `request_more_sections: [...]` and the supervisor
  can re-invoke it with a narrower brief.
- Semantic Scholar adapter + citation-graph traversal (still on the
  list; deferred from original Sprint 3).
- Claude prompt caching for paper-corpus system messages.
- Cost-aware model routing: Haiku for extraction, Sonnet for
  synthesis, Opus for critic.

## Sprint 4 (~2 weeks) — Make it deployable

- FastAPI wrapper with an async job model.
- Streaming endpoint via SSE.
- Docker + docker-compose (app, Redis, Postgres).
- GitHub Actions CI for unit + integration (lint, mypy, tests,
  smoke query on mock papers).
- Paper cache moved from local `.cache/pdfs/` to Postgres + persisted
  embeddings (production-scale mandate follow-up on ADR 0002).

## Sprint 5 (~2 weeks) — Ship a real product surface

- Minimal web UI (Next.js or Streamlit) with streaming.
- Human-in-the-loop breakpoint after supervisor's plan step.
- Multi-format export (PDF, DOCX).
- Follow-up conversation mode.
- Slack bot (optional).

## Sprint 6+ — Enterprise moat

- Private corpus / BYO PDF.
- Multi-tenancy + RBAC + SSO.
- Bedrock / Vertex adapters.
- Reproducibility scoring, benchmark extraction.
- Skills registry (research playbooks) — see
  [`05-agentic-upgrade-plan.md`](05-agentic-upgrade-plan.md); deferred
  because it multiplies eval surface without proving core loop
  quality first.
- MCP adapter — expose `search_arxiv` / `parse_pdf` /
  `store_evidence` / `run_eval` as MCP tools.

## Log

<!-- Append entries here as sprints complete or plans change. -->

- _2026-07-05_ — Roadmap drafted. No sprints started yet.
- _2026-07-07_ — Sprint 1 done. 20 PRs, 12 ADRs, 262 tests, four eval
  metrics live, nightly CI catching regressions. Reordered Sprint 2:
  loop engineering (supervisor + verifier + evidence store) ahead of
  the deployment / infra items originally scoped there. Rationale in
  [`05-agentic-upgrade-plan.md`](05-agentic-upgrade-plan.md).
