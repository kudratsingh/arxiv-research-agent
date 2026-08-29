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

## D-011 — EXEC coordinator rulings (M0 wave, under the same delegation)

- Date: 2026-08-28
- Status: recorded as ruled
- Authority: the D-010 delegation; each ruling was made in response to an
  implementation agent's honest flag rather than silently absorbed.
- Rulings:
  1. **Shared framework/runtime budget raised 120 → 138 KiB** (PR #77,
     ratchet rule). WO-23's script measured the row at 130,865 B on
     untouched `main` — React DOM (63,370 B) + the Next app-router
     runtime (65,603 B) exceed the inferred 122,880 B ceiling before any
     application code. 138 KiB = 141,312 B is 8.0% headroom over the
     measured baseline, matching the other rows' +8.1/+8.2%. The raise
     is recorded inside `web/budgets.json`'s `ratchet` array and printed
     by every budget report.
  2. **Next 16 manifest substitution accepted** (PR #77):
     `app-build-manifest.json` no longer exists; the derived app-router
     chunk union is cross-proved against the script tags in the
     prerendered HTML.
  3. **WO-03 error-message dual channel accepted** (PR #75):
     `ApiFailure.message` is the user-facing sentence; the legacy
     `ApiError.message` string survives only for shim neutrality and is
     deleted with the shims in M4. Billable writes carry **no default
     timeout** (R-01: a client timeout on `POST /research` hides a run
     being paid for); reads carry 15 s.
  4. **WO-04 scope extension accepted** (PR #79): one `contract:check`
     step in `.github/workflows/ci.yml` — its criterion literally
     requires CI to fail on drift.
  5. **WO-02 shared-file touches accepted** (PR #80): a 4-line
     `vitest.config.mts` alias stubbing `next/font/local`, and one
     future-proofed assertion in WO-01's token test.
  6. **Integration incident recorded** (PR #78): PRs #76 and #77 were
     independently green but their combination failed on `main` — the
     repo-wide hex-colour scan matched the `#defa` prefix of Next's
     `#default` manifest module keys in WO-23's fixtures. `main` was red
     for one push run (~6 minutes); fixed forward by tightening the
     scan's lookahead to `(?!\w)`. Coordinator process change: every
     merge is now gated on the CI watch's exit status in a single
     guarded command.
  7. **Fleet hazard added to `06-WORK-ORDERS.md` §5.4**: the compose
     file's hardcoded `container_name` values let one agent's
     `docker compose down` remove another agent's running stack
     (observed; no data loss — the victim had already finished).
- Needs human review: no (delegated); listed here so the audit trail of
  every deviation from the ratified package is complete.

## D-012 — EXEC coordinator rulings (surface and quality-gate waves, under the same delegation)

- Date: 2026-08-29
- Status: recorded as ruled
- Authority: the D-010 delegation; each ruling was made in response to an
  implementation agent's honest flag rather than silently absorbed.
- Rulings:
  1. **npm-audit gate scoped by dependency tree** (PR #100, C4). The
     production tree is gated at zero advisories with no exception
     mechanism (`npm audit --audit-level=high --omit=dev`); the dev tree
     is gated against `web/audit-exceptions.json`, which fails on any
     unlisted advisory, on stale entries, and on new advisories against
     an already-excepted package (entries key on the advisory-id set,
     not the package). Seeded with the three `image-size` reports
     reached only through `@storybook/nextjs-vite` (three packages
     carrying two upstream GHSAs; no fix available). Rationale: the
     baseline's "0 across 669" predates Storybook (WO-06); blocking the
     merge train on an unfixable dev-chain advisory guards nothing the
     production image ships.
  2. **WO-19 retirement deferral accepted** (PR #98 → completed in
     PR #101). The DOM-level retirement of `JobSummary`/`ExportDropdown`
     rides WO-20's `ConversationThread` rewrite — the only render path
     to both — behind an import-ratchet test
     (`web/tests/patterns/retirement.test.ts`); files stay on disk for
     WO-31. The merged e2e state table had already scheduled the swap
     for WO-20 by name.
  3. **`PENDING_COMPOSITION` routing accepted** (PR #99 → discharged in
     PR #101). WO-22's nine residual axe violations — all in legacy
     `ConversationThread`/`PlanReview` markup, including two contrast
     regressions new against baseline (`#64748b` on `--canvas` @12px
     = 4.41; white on `#059669` = 3.76) — were pinned in a register that
     fails when a pin goes stale, rather than hotfixed in files WO-20
     replaces wholesale. WO-20's composition deleted all nine pins and
     the sweep reports 40/40 state×theme audits at zero violations.
  4. **`/` route budget raised 148,480 → 167,936 B** (PR #101, ratchet
     rule; measured 158,899 B). The in-budget alternative was built and
     measured, not assumed: a `React.lazy` composer lands `/` at
     143,426 B but Next resolves the lazy boundary's fallback into the
     prerendered HTML — verified on the build — so the route would ship
     a document with no `h1` and fail `page-has-heading-one`, which the
     axe gate holds at zero. Accessibility gate beats budget row. Net
     across both routes the composition is −4,189 B, with `/c/[id]`
     dropping 199,425 → 182,784 B. Recorded in `web/budgets.json`'s
     ratchet array and pinned by test.
  5. **Nightly matrix via a workflow-level `schedule:` trigger accepted**
     (PR #100, criterion 4 deviation). Gating per-job would have added
     `if:` conditions to five jobs WO-24 does not own; `web-e2e` is the
     only job whose behaviour differs by event.
  6. **Axe audit viewport pinned at the baseline's 1440×1200** (PR #99).
     At Playwright's default 1280×720 axe downgrades below-the-fold
     contrast findings to `incomplete` and the sweep under-reports
     against the retained baseline — the viewport is load-bearing for
     criterion 1's comparability claim.
  7. **WO-20's two deliberately unwired edges recorded as accepted
     residuals** (PR #101): `LandingComposer`'s `createThread` mutation
     and its `unreachable` prop stay unwired pending a shared
     QueryClient that would cost `/` ~8 KB it does not have; `/c/[id]`
     consequently runs two Query caches whose only shared key is
     `conversations.detail` and whose only cross-cache write navigates
     away. To be restated in WO-26's `known-gaps.md`.
- Needs human review: no (delegated); listed here so the audit trail of
  every deviation from the ratified package is complete.

## D-013 — Coordinator process incident: PR #103 merged with a red check

- Date: 2026-08-29
- Status: recorded; procedure corrected
- What happened: the docs-only roadmap PR #103 was squash-merged while
  its `web e2e (chromium + axe)` job was red. The coordinator's
  verification pipeline (`gh pr checks 103 | awk … && gh pr merge …`)
  keyed the merge on the pipeline's exit status — awk's, always 0 —
  instead of `gh pr checks`' own; a `--watch …; echo` background
  watcher had likewise masked the failure behind the echo's exit code.
- Impact: none to `main`'s code. The diff was 15 documentation lines in
  `planning/03-roadmap.md`; the tree was byte-identical to the state
  that had passed the full 8-job matrix at PR #102.
- The red itself: an infrastructure flake, not a regression — the
  `web-e2e` image bake was rate-limited by Hugging Face (HTTP 429) while
  downloading the MiniLM embedding weights. A `--failed` re-run of the
  same run (33251684100) completed green end to end, retroactively
  validating the merged state.
- Corrections:
  1. The merge gate is now a **bare, unpiped `gh pr checks <n>`** whose
     own exit status `&&`-chains into the merge; filters may render the
     output but never sit between the check and the decision. Watchers
     signal "settled" only; the bare re-check decides.
  2. The Hugging Face dependency in the CI image bake is recorded as a
     reliability risk under fleet concurrency; caching the weights
     (HF hub cache or a docker layer-cache) is queued as a CI hardening
     candidate once WO-30 — the last sanctioned `ci.yml` editor —
     merges. Until then the standing mitigation is a `--failed` re-run.
- Needs human review: no (delegated); recorded per the D-011 precedent
  that every merge-process incident enters the audit trail.

## D-014 — Gate 3 ratified (under the standing delegation)

- Date: 2026-08-29
- Status: **Gate 3 closed — approved**
- Authority: the D-010 delegation.
- Basis: all 26 Gate 3 work orders merged (PRs #74–#101 plus repairs);
  evidence pack PR #107 measured 8/10 criteria PASS and reported the two
  failures honestly; repairs merged as PR #108 (criterion 1 — 23 stories
  closing §4 rows 5/B and the RC-10 union) and PR #111 (criterion 7 —
  mobile CLS 0.134 → 0.000 on every route, `/c/[id]` mobile LCP
  3.2–3.7 s → 1.3–1.4 s, Performance 85–88 → 100); addendum PR #112
  re-verified both with the pack's own method on `d3460a7`
  (10/10 criteria now hold; every number re-derived from committed
  artifacts). The pack claims no accessibility conformance; the
  known-gaps list is the Gate 4 workplan.
- Rulings bundled into this close:
  1. **Coverage `functions` floor re-seeded 95.05 → 87.5** (PR #108):
     the dual-project function-list concatenation hazard documented in
     `web/vitest.config.mts` fired when Storybook first loaded the
     route-composition import graph; statements/lines/branches rose or
     held. Structural re-seed, not a quality drop; the proper
     de-duplication fix belongs to the config owner (follow-up).
  2. **CSP `style-src-attr 'unsafe-inline'` accepted** (PR #109):
     scoped to style *attributes* only (`style-src 'self'` intact,
     honored separately by all three engines — measured, not assumed);
     sole consumer is `Skeleton`'s geometry props; the source fix
     spans seven call sites and is recorded as follow-up in
     `docs/security.md`.
  3. **`/` dynamic rendering accepted as inherent to the nonce CSP**
     (PR #109): a per-request nonce cannot live in a cached document.
     Consequences recorded: `/` fails the desktop bfcache audit by
     design (`no-store`; the RC-18 gate is `/c/[id]`, which is
     unchanged cell for cell), and WO-23's manifest cross-check for `/`
     reads "skipped — not statically prerendered" (WO-31 asked to
     restore equivalent corroboration if cheap).
  4. **Near-ceiling Lighthouse cells carry both samples** (PR #111,
     #112 practice): where a lab metric lands within ~10% of its
     ceiling, two samples are committed and neither discarded; the
     verdict is stated against the worse one.
- Still reserved for the user: MT-01 (PROPOSED), anything cost-bearing
  (DEPLOY, the never-yet-funded eval campaign), and WO-27's human
  screen-reader transcription.
- Needs human review: no (delegated); recorded with the full audit trail
  per D-009–D-013.

## D-015 — Gate 4 ratified with one reservation (under the standing delegation)

- Date: 2026-08-29
- Status: **Gate 4 closed — approved, with RR-02 reserved to the user**
- Authority: the D-010 delegation.
- Basis: all seven Gate 4 work orders merged — WO-30 (PR #109),
  WO-27 (#115), WO-29 (#116 + runner-ceiling amendment #119),
  WO-31 (#114), WO-28 (#118), WO-32 (#117), WO-33 (#120). The Gate 4
  evidence pack walks every §4.2 artifact, the §4.3 forbidden-claims
  checklist, the twelve §11 ambiguity ratifications, and the
  before/after quality report; the nightly Lighthouse gate is proven
  by a real-runner failure diagnosed and a real-runner pass
  (runs 33262680039 → 33265437903).
- The reservation: **RR-02** — WO-27 criterion 3's screen-reader
  transcriptions (VoiceOver + Safari on macOS and iOS; NVDA + Firefox)
  require a human operator and were not executed; the protocol is
  written and waiting. A delegation cannot manufacture a human
  transcription, so the gate closes with this named as the one
  outstanding criterion, owned by the user, tracked as RR-02 with
  blocker status in `evidence/gate-4/residual-risks.md`.
- Rulings bundled into this close:
  1. **Nightly TBT runner ceiling** (PR #119): the ratified §8.2 TBT
     ceilings stay asserted at `warn`; a runner `error` ceiling of 2×
     the ratified value applies **per form factor** (mobile 300 ms,
     desktop 100 ms) — the worker's per-form-factor amendment of the
     coordinator's flat-300 wording is accepted as the more faithful
     reading. Evidence: 36 mobile samples spanning 55–290 ms on 2-core
     runners for cells that measure 10–63 ms locally. A future failure
     here means a dedicated runner, not another doubling.
  2. **WO-31's six budget ratchet-downs recorded** (PR #114), closing
     `web/budgets.json`'s "to be recorded in DECISIONS.md" pointers:
     `/` 167,936→166,912 B; `/c/[id]` 199,680→192,512 B; shared
     runtime 141,312→139,264 B; CSS 12,288→11,264 B; fonts
     122,880→109,568 B; derived total 334,848→313,344 B. Coverage
     floors ratcheted up to 97.61/93.37/88.1/98.57.
  3. **WO-28's superset reading accepted** (PR #118): the ambiguous
     "four degraded states" is discharged by covering all seven
     degraded states with retained baseline screenshots, so every
     reading of the card is a subset.
  4. **WO-33 findings routed to owners**: the budget report's false
     "baseline not an ancestor" sentence (`route-budgets.mjs:661`,
     WO-23 owner); two stale doc references (`ci.yml` line numbers,
     a deleted-module pointer in 06 §11); `last-event-id`'s D-010 r15
     reservation unpinned by test or comment (RR-14, WO-30 owner);
     two pre-existing broken links in WO-27's pack. None changes a
     gate verdict; all live in the residual register with owners.
- The full residual register is `evidence/gate-4/residual-risks.md`
  RR-01–RR-19. Reserved to the user beyond RR-02: MT-01 (PROPOSED),
  DEPLOY, a funded eval campaign, the license decision, and the
  GitHub social-preview upload.
- Needs human review: RR-02 only; everything else delegated and
  recorded per D-009–D-014.
