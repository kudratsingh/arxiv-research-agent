# Frontend revamp changelog

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
