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

## D-010 — Gate 2 decisions (made under user delegation)

- Date: 2026-08-28
- Status: recorded; Gate 2 approved
- Authority: after Gate 1 the user delegated the remaining revamp gate
  decisions to the coordinator ("no need for me, just keep going and get
  everything done"). Every ruling below follows the recommendation
  documented in the package, and each was independently assessed as
  evidence-supported by the Gate 2 reviewer before ratification (the two
  assessed as thin — the two-family plan editor and the font-budget
  feasibility — are ratified with their documented fallbacks/ratchets).
  Anything that costs money (deployment, paid model runs) and MT-01
  implementation remain reserved for the user.
- Package approved: `03-DESIGN-BRIEF.md` + `design/tokens.json` (PR #71),
  `04-ARCHITECTURE.md` + `05-MIGRATION.md` (PR #70), `06-WORK-ORDERS.md`
  (PR #72). Independent review: first pass REJECT (2 Major / 14 Minor),
  all corrected; second pass APPROVE with zero unresolved findings
  (`REVIEW.md`).
- Rulings:
  1. **Architecture (D-002 confirmed)** — keep Next.js with the
     same-origin server proxy as the sole credential boundary; ADR 0055
     to be written in WO-32.
  2. **Partial-report export** — exposed, labelled partial on screen
     (03 §8.1; closes R-14). A partial marker *inside* the exported file
     is a backend exporter change, not scheduled.
  3. **Deletion copy** — "Delete thread", with the honest second
     sentence about job-store retention
     (`src/api/conversations.py:547`, `src/config.py:307`).
  4. **`error_type` vocabulary** — mapped sentence primary, raw string
     always one disclosure away, drift test enforces non-lossiness.
  5. **`hitl_bypass`** — stays unavailable in the UI as a stated rule;
     test-enforced absence.
  6. **Product lexicon** — thread / run / briefing / checkpoint,
     three-register split per RC-12; export filenames stay upstream.
  7. **Typefaces** — the three OFL families including RC-20's Literata
     Italic 400 (eight faces); WO-02 measures first; RC-01 ratchet rule
     governs any budget raise (see R-17).
  8. **Two-family plan editor** — approved with WO-17's
     `aria-describedby` fallback load-bearing.
  9. **Trace-spine blind-spot** — the dimensioned static void is
     approved; the fallback is a status-only chip, never invented
     stages.
  10. **Web-container healthcheck** — probe `/api/healthz` requiring
      HTTP 200 but not failing on `status: degraded` (04 §11.12).
  11. **Bundle budgets** — RC-01's reconciled table ratified
      (`/` 145 KiB, `/c/[id]` 195 KiB, shared 120 KiB, CSS 12 KiB,
      fonts 120 KiB, total route JS 240 KiB; derived 327 KiB first-load
      transfer reported, not gated).
  12. **`job.plan = None` permanence** — accepted for this revamp
      (R-16); durable plan lineage is a future backend proposal beside
      MT-01.
  13. **Review deadline** — not exposed; `api_hitl_timeout_sec` is
      server config, and the UI shows no countdown.
  14. **MT-01 seams** — S1/S2/S5 as specified; reserved names only, no
      files, one-directional dependency per the proposal's §5.7.
  15. **`last-event-id`** — declared reserved in the proxy allowlist; no
      code change either way.
  16. **Reconciliations RC-01…RC-21** — ratified as resolved in
      `06-WORK-ORDERS.md` §1, including both co-critical 12-node chains
      and the 12-wave schedule in §5.
- Consequences: EXEC unblocks. Implementation runs as concurrent
  work-order PRs per `06-WORK-ORDERS.md` §5, merged only on green CI;
  Gate 3 requires the merged foundation + vertical slice with
  Storybook/state evidence; Gate 4 requires the hardening/docs wave and
  the before/after quality report. WO-08 is expected to overrun its size
  estimate (reviewer note) — treated as expected, not a decomposition
  failure.
- Needs human review: no further review for these rulings (delegated);
  the ship decision's cost-bearing follow-ons (deployment) and MT-01
  remain the user's.
