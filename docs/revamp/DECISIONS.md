# Frontend revamp decision log

## D-001 — Treat the product as a research workflow

- Date: 2026-08-28
- Status: accepted for Gate 1
- Decision: classify the product primarily as a workflow/productivity application, secondarily as a research/content workbench and developer/operational tool.
- Why: the central contract is question → plan review → long-running workflow → report/metrics/export, not conversational turn-taking alone.
- Alternatives: chatbot, document reader, analytics dashboard, or operational monitor as the primary model.
- Reversal cost: low before Phase 2; high after shell and component architecture.
- Needs human review: no; evidence-backed discovery classification.

## D-002 — Preserve the Next.js server boundary

- Date: 2026-08-28
- Status: preliminary; architecture confirmation at Gate 2
- Decision: retain Next.js and its same-origin Node proxy unless a later ADR presents stronger evidence.
- Why: the proxy keeps the upstream API key out of browser code and correctly streams SSE and downloads. A client-only rewrite would have to recreate this boundary.
- Alternatives: client-only React plus a separate BFF; another SSR/full-stack framework; server-rendered non-React UI.
- Reversal cost: high after foundation work; requires security, streaming, Docker, and route migration.
- Needs human review: yes at Gate 2 if the architecture recommendation remains unchanged.

## D-003 — Interpret five routes as five meaningful states

- Date: 2026-08-28
- Status: accepted for Gate 1
- Decision: audit landing, empty conversation, populated report, plan review, and not-found/recovery across the existing two page templates.
- Why: inventing URLs would not improve evidence; long-running state variants are the real product surfaces.
- Alternatives: audit only two URLs; add artificial routes solely to reach five.
- Reversal cost: low; add new route/state evidence later.
- Needs human review: no.

## D-004 — Use synthetic local baseline data

- Date: 2026-08-28
- Status: accepted
- Decision: use a deliberately invalid Anthropic key plus synthetic local Postgres/Redis records for baseline capture.
- Why: it exercises the frontend states without a paid model call or accidental non-idempotent research submission.
- Alternatives: real model run; mock only static HTML; skip populated states.
- Reversal cost: low; a separately approved paid baseline can supplement it later.
- Needs human review: no; this follows the explicit cost boundary.

## D-005 — Install the official Anthropic frontend-design skill

- Date: 2026-08-28
- Status: accepted
- Decision: install the official `anthropics/skills` frontend-design guidance in the project-scoped Codex skill directory and record it in `skills-lock.json`.
- Why: the standalone skill is byte-identical to the Claude Code plugin's embedded guidance and is the environment-native way to apply the supplied design process.
- Alternatives: install a Claude-only plugin manifest; copy unpinned guidance; use no design skill.
- Reversal cost: low; remove two project files and the lock entry.
- Needs human review: no; explicitly required by the supplied orchestrator brief.

## D-006 — Defer community skill installation

- Date: 2026-08-28
- Status: accepted for Gate 1
- Decision: record vetted candidates but do not install broad community packs before stack/quality architecture is approved.
- Why: the current repository already provides most runtime behavior; adding overlapping skills before the work orders are known increases instruction and supply-chain surface without clear value.
- Alternatives: install every relevant community pack; install one framework and one accessibility pack immediately.
- Reversal cost: low; candidates can be re-evaluated and pinned per work order.
- Needs human review: no, unless a specific community skill is requested.

## D-007 — Do not fabricate structured evidence UI

- Date: 2026-08-28
- Status: confirmed by the user at Gate 1 (see D-009)
- Decision: base the revamp signature on the real question, approved plan, pipeline stages, report, and metrics. Do not parse Markdown into invented claim/paper contracts.
- Why: structured papers, citations, claims, and evidence are not exposed by the frozen HTTP API.
- Alternatives: fragile Markdown parsing; frontend-local shadow schema; separately approved versioned backend contract.
- Reversal cost: medium; later structured evidence can extend the trace without replacing the shell.
- Needs human review: yes at Gate 1.

## D-008 — Stop before implementation

- Date: 2026-08-28
- Status: accepted
- Decision: finish and independently review Gate 1 artifacts, then wait for explicit direction approval.
- Why: this follows the supplied orchestrator's human-gate protocol and avoids designing the detailed system before the product direction is selected.
- Alternatives: proceed directly to the design system or implementation.
- Reversal cost: none; the gate deliberately prevents premature cost.
- Needs human review: yes; the user must resolve the Gate 1 questions.

## D-009 — Gate 1 human decisions

- Date: 2026-08-28
- Status: recorded; Gate 1 approved
- Decision: the user answered the four blocking Gate 1 questions:
  1. **Direction A — Evidence Workbench** becomes the Phase 2 design brief.
  2. The shared-principal deployment model is **not** accepted as the end
     state: the product should gain real end-user multi-tenancy. This is a
     separate backend workstream (MT-01), outside the frozen-backend
     boundary of this revamp.
  3. The frozen-backend rule is **confirmed**: unsupported concepts are
     omitted, not simulated. Until MT-01 ships, this includes per-user
     identity — the revamp shell must not fake login or per-user views.
  4. The first vertical slice is **approved** as proposed: new question →
     reload-safe job → plan review → stream/reconnect →
     report/metrics/export.
- Consequences: G2-01 (Phase 2 design brief) unblocks. The brief must
  design the shell so user identity and auth can be added without
  rearchitecture (navigation, ownership affordances, and a reserved login
  surface), while the implemented revamp continues to target the current
  single-principal proxy until MT-01 lands. MT-01 should build on the
  existing per-principal scoping (ADRs 0033/0036/0037) — most plausibly a
  web login/session mapped to per-user principals in the Next.js proxy —
  and needs its own gated proposal and ADR before any backend change.
- Needs human review: MT-01's proposal, cost, and rollout require their
  own explicit approval; nothing in this revamp implements it.
