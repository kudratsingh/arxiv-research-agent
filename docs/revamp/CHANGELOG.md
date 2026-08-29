# Frontend revamp changelog

## 2026-08-29 — Gate 3 closed (under user delegation)

- Ratified as [`DECISIONS.md` D-014](DECISIONS.md#d-014--gate-3-ratified-under-the-standing-delegation): all 26 Gate 3 work orders merged; evidence pack (PR #107, honest 8/10) + criterion repairs (PR #108 stories; PR #111 mobile CLS 0.134→0.000 and `/c` LCP into budget) + re-verification addendum (PR #112) bring all ten criteria to PASS on `d3460a7`.
- Gate 4 progress alongside the close: WO-30 proxy hardening merged (PR #109 — enforcing nonce CSP, structured proxy logging with whitelist redaction, body-parsing healthcheck, MT-01 seams; `apiProxyRoute.test.ts` byte-identical). In flight: WO-27 (a11y hardening), WO-29 (Lighthouse nightly), WO-31 (legacy removal); queued: WO-28, WO-32, WO-33.
- Public-presentation campaign completed the same day: README overhaul with verified diagrams/screenshots/badges (PR #110), agent design docs with per-agent diagrams (PR #104), demo/eval/index accuracy pass (PR #106), roadmap entry (PR #103), incident record D-013 (PR #105).

## 2026-08-29 — EXEC: quality gates, route composition, and the 8-job CI

- Merged on green CI: the probe-alignment follow-up from the merged-main integration run (PR #97, merged by the user), WO-19 MetricsStrip + ExportDisclosure (PR #98), WO-22 axe gate (PR #99), WO-24 CI wiring (PR #100), and WO-20 route composition (PR #101). **25/33 work orders merged; every Gate 3 implementation work order is on `main`.**
- Headlines: `landmark-one-main`/`region` axe violations went 12/12 baseline states → **zero** with the allowlist empty; the route composition retired seven legacy modules from the render path behind a widened import ratchet; CLS 0.000 held in a live-run browser test across three consecutive runs; net route JS fell 4,189 B with `/c/[id]` gaining 16,896 B of budget headroom; CI grew from five to eight jobs (coverage thresholds, the npm-audit gate, budgets artifact, Storybook build + story tests, seeded chromium+axe e2e; the full five-project browser matrix moved to a nightly schedule).
- Real defects found and fixed inside the wave: an R-01 double-submit window in `LandingComposer` that bought a second run (caught by the paid-path interceptor discipline), three CLS sources (reading-column scrollbar, spine void reflow, run-panel geometry), and two contrast/heading regressions the new axe gate caught in the composition itself.
- Coordinator rulings recorded as [`DECISIONS.md` D-012](DECISIONS.md#d-012--exec-coordinator-rulings-surface-and-quality-gate-waves-under-the-same-delegation): audit-gate scoping, the `/` budget ratchet, the retirement deferral, and the `PENDING_COMPOSITION` routing.
- Process incident recorded as [`DECISIONS.md` D-013](DECISIONS.md#d-013--coordinator-process-incident-pr-103-merged-with-a-red-check): docs-only PR #103 was merged while `web e2e` was red (an exit-code-masking verification pipeline); the red was a Hugging Face 429 flake in the image bake, re-run green. Merge gate corrected to key on `gh pr checks`' own exit status.
- In flight: WO-26 Gate 3 evidence pack (`docs/wo-26-gate-3-evidence`) and WO-30 proxy hardening (`feat/wo-30-proxy-hardening`).

## 2026-08-28→29 — EXEC: surface wave (M1–M3)

- Merged on green CI, in merge order: WO-05 test harness (PR #82), WO-06 Storybook + a11y addon (PR #83), WO-11 query layer (PR #84), WO-07 primitives (PR #85), WO-10 job state machine (PR #86), WO-12 copy dictionary (PR #87), WO-08 workbench shell (PR #88), WO-18 ReportReader (PR #89), WO-16 Diagnostics (PR #90), WO-13 QueryComposer (PR #91), WO-15 trace spine (PR #92), WO-17 PlanEditor (PR #93), WO-14 ThreadRail (PR #94), WO-09 recovery surfaces (PR #95), WO-21 Playwright harness + seeded stack + paid-path interceptor (PR #96). M0 rulings and the integration-incident record merged as PR #81.
- The merged-main integration run after the wave exposed four stale probe expectations and one first-paint scheduler race that per-PR CI could not see; repaired in PR #97 with a definitive 158/158 five-project matrix.

## 2026-08-28 — EXEC: M0 foundation wave (in progress)

- Merged on green CI: WO-25 web-image CI smoke + prod overlay (PR #74), WO-03 typed API client + shims (PR #75), WO-01 design-token foundation (PR #76), WO-23 route budgets (PR #77), WO-04 recorded contract fixtures + four drift checks (PR #79), WO-02 self-hosted typography with measured metrics and CLS 0.000 proof (PR #80). In flight: WO-05, WO-06.
- Coordinator rulings during the wave recorded as `DECISIONS.md` D-011, including the ratchet-rule raise of the shared framework/runtime budget row (120 → 138 KiB) after WO-23 measured it infeasible on untouched `main`.
- Integration incident: independently-green PRs #76 + #77 conflicted on `main` (hex-scan false positive on Next manifest `#default` keys); red for one push run, fixed forward in PR #78 with a tightened lookahead. Merge process now gates on CI-watch exit status in one guarded command.
- Fleet hazard added to `06-WORK-ORDERS.md` §5.4: hardcoded compose `container_name` values collide across agent worktrees.

## 2026-08-28 — Gate 2 approved and closed (under user delegation)

- Merged the Phase 2–4 package on green CI: design brief + tokens (PR #71), architecture + migration (PR #70), work orders + dependency graph (PR #72), authored by three concurrent agents; MT-01 multi-tenancy proposal merged separately (PR #69, PROPOSED).
- Independent Gate 2 package review: first pass REJECT (2 Major / 14 Minor), all corrected on the unmerged work-orders branch; second pass APPROVE with zero unresolved findings. Record appended to `REVIEW.md`.
- Ratified the sixteen Gate 2 rulings as `DECISIONS.md` D-010 under the user's standing delegation; every ruling follows the documented recommendation and its reviewer support assessment.
- Applied the two reviewer findings against merged files: 03 §8.4's `hitl_bypass` eval-runner claim corrected (`enable_hitl=False` at `src/eval/runner.py:297`); 05 §2.1's "worst axe state" restated as a three-way tie.
- Risk register updated: R-03/R-14 closed, R-07 resolved-to-MT-01, R-16 (plan lineage) and R-17 (font-budget floor) added.
- EXEC unblocked: implementation begins as concurrent work-order PRs per `06-WORK-ORDERS.md` §5.

## 2026-08-28 — Gate 1 approved and closed

- Recorded the human Gate 1 decisions as `DECISIONS.md` D-009: Direction A (Evidence Workbench); frozen-backend rule confirmed; vertical slice approved; shared-principal model rejected as the end state, with real multi-tenancy tracked as separate backend workstream MT-01.
- Updated `STATUS.md` (G2-01 unblocked pending PR merge, MT-01 added), `00-DISCOVERY.md` (answers recorded), and the roadmap.

## 2026-08-28 — Gate 1 second-pass review approved

- Re-ran the interrupted second-pass independent review with a fresh reviewer agent; verdict **APPROVE** with two minor, non-blocking findings.
- Added the Lighthouse capture-provenance disclosure to `baseline/README.md` (finding 1).
- Carried the Direction C checkpoint-ruler constraint forward as a Phase 2 requirement (finding 2).
- Updated `STATUS.md`: all G1 workstreams done; the sole remaining Gate 1 blocker is the human decision set.

## 2026-08-28 — Gate 1 candidate

- Completed repository, product, route, component, state, API, CI, deployment, dependency, and git-history discovery.
- Captured six successful local Lighthouse runs, 27 visual artifacts, and 12 standalone axe reports without calling a paid model; added deterministic local-only seed/capture specs.
- Measured route bundle baselines and verified typecheck, lint, 78 tests, production build, and dependency audit.
- Researched workflow UX, accessibility, performance, mature design systems, adjacent research products, and current frontend tooling.
- Installed and pinned Anthropic's official frontend-design skill for Codex; inspected the byte-identical Claude Code plugin guidance and official frontend-aesthetics cookbook.
- Produced three preliminary, backend-feasible visual directions.
- Stopped before design-system architecture or product code, pending Gate 1 approval.
