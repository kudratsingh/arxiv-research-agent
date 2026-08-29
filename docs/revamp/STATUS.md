# Frontend revamp status

Updated: 2026-08-29 (Gate 3 closed; Gate 4 hardening wave in flight)  
Baseline: `e6e87396d32be5ae985c2d7cc0dd5ed6cf84b351`

## Current gate

**Gate 3 — approved 2026-08-29 under user delegation ([`DECISIONS.md` D-014](DECISIONS.md#d-014--gate-3-ratified-under-the-standing-delegation)). Gate 4 hardening is in flight.**

- Gate 3 basis: evidence pack (PR #107) + repairs (PRs #108, #111) + re-verification addendum (PR #112); the pack's known-gaps list is the Gate 4 workplan. Rulings: [`DECISIONS.md` D-011](DECISIONS.md#d-011--exec-coordinator-rulings-m0-wave-under-the-same-delegation)–[D-014](DECISIONS.md#d-014--gate-3-ratified-under-the-standing-delegation).
- Gate 4 merged so far: WO-30 proxy hardening (PR #109 — enforcing nonce CSP, proxy logging, healthcheck, MT-01 seams).
- In flight: WO-27 (`feat/wo-27-a11y-hardening`), WO-29 (`ci/wo-29-lighthouse-nightly`), WO-31 (`chore/wo-31-legacy-removal`). Queued: WO-28 (after WO-27), WO-32 (after WO-31), WO-33 (last).
- Reserved for the user: MT-01, DEPLOY, the paid eval campaign, and WO-27's human screen-reader transcription.

**Gate 2 — approved 2026-08-28 under user delegation.**

- Gate 1 approved 2026-08-28 (PR #68): human decisions in [`DECISIONS.md` D-009](DECISIONS.md#d-009--gate-1-human-decisions) — Direction A (Evidence Workbench), frozen backend, vertical slice, shared-principal model rejected as end state (→ MT-01).
- Gate 2 package (Phases 2–4) delivered by three concurrent author agents and merged on green CI: design brief + tokens (PR #71), architecture + migration (PR #70), work orders + dependency graph (PR #72). Independent package review: first pass REJECT (2 Major / 14 Minor), all corrected; second pass **APPROVE**, zero unresolved ([`REVIEW.md`](REVIEW.md#gate-2-package-review)).
- After Gate 1 the user delegated the remaining gate decisions ("no need for me, just keep going"). The sixteen Gate 2 rulings are recorded as [`DECISIONS.md` D-010](DECISIONS.md#d-010--gate-2-decisions-made-under-user-delegation); each follows the documented recommendation and its reviewer support assessment.
- Still reserved for the user: anything cost-bearing (Hetzner provisioning, paid model runs) and MT-01 implementation (proposal PR #69 is merged but PROPOSED, awaiting the user's own gate).

No backend contract has changed. No paid model, hosting, or provisioning action was taken.

## Workstream status

| ID | Title | Role | State | Branch | Blockers | Last update |
|---|---|---|---|---|---|---|
| G1-01 | Repository/product/API discovery | Orchestrator + backend specialist | done | `docs/frontend-revamp-gate-1` | — | 2026-08-28 |
| G1-02 | Current frontend inventory | Frontend specialist | done | `docs/frontend-revamp-gate-1` | — | 2026-08-28 |
| G1-03 | Screenshots, Lighthouse, bundle baseline | Orchestrator | done | `docs/frontend-revamp-gate-1` | — | 2026-08-28 |
| G1-04 | UX/accessibility/analog research | UX specialist | done | `docs/frontend-revamp-gate-1` | — | 2026-08-28 |
| G1-05 | Current technology research | Technology specialist | done | `docs/frontend-revamp-gate-1` | — | 2026-08-28 |
| G1-06 | Skill/plugin vetting | Orchestrator | done | `docs/frontend-revamp-gate-1` | — | 2026-08-28 |
| G1-07 | Candidate visual directions | Orchestrator | done — Direction A chosen | `docs/frontend-revamp-gate-1` | — | 2026-08-28 |
| G1-08 | Independent Gate 1 review | Separate reviewer | done — approved (second pass) | `docs/frontend-revamp-gate-1` | — | 2026-08-28 |
| G2-01 | Phase 2 design brief + tokens | Opus author agent | done — merged (PR #71) | `main` | — | 2026-08-28 |
| G2-02 | Phase 3 architecture + migration | Opus author agent | done — merged (PR #70) | `main` | — | 2026-08-28 |
| G2-03 | Phase 4 work orders + dependency graph | Opus author agent | done — merged (PR #72) after review corrections | `main` | — | 2026-08-28 |
| G2-04 | Independent Gate 2 package review | Separate reviewer | done — approved (second pass) | `main` | — | 2026-08-28 |
| MT-01 | Multi-tenancy backend proposal | Opus author agent | proposal merged (PR #69); PROPOSED | `main` | User's own approval gate; blocking questions in the proposal §8 | 2026-08-28 |
| EXEC | Product implementation (33 work orders, 26 Gate 3 / 7 Gate 4) | Worktree agent fleet | Gate 3 set done (26/26); Gate 4: WO-30 merged, WO-27/29/31 in flight | per-WO branches | Merges gated on green CI | 2026-08-29 |
| DEPLOY | Hetzner CX23 Helsinki deployment | Unassigned | blocked | — | Server availability and explicit cost approval (reserved for the user) | 2026-08-28 |

Deliverables: [`00-DISCOVERY.md`](00-DISCOVERY.md), [`baseline/`](baseline/README.md), [`01-RESEARCH.md`](01-RESEARCH.md), [`skills-installed.md`](skills-installed.md), [`02-DIRECTIONS.md`](02-DIRECTIONS.md), [`03-DESIGN-BRIEF.md`](03-DESIGN-BRIEF.md) + [`design/tokens.json`](design/tokens.json), [`04-ARCHITECTURE.md`](04-ARCHITECTURE.md), [`05-MIGRATION.md`](05-MIGRATION.md), [`06-WORK-ORDERS.md`](06-WORK-ORDERS.md), and [`../proposals/multi-tenancy.md`](../proposals/multi-tenancy.md).

## Loaded skills and companion capabilities

| Capability | Source/version | Active status |
|---|---|---|
| Frontend Design skill | Anthropic `anthropics/skills`, inspected commit `3b3fad96af16a10759d930941b4520ba0c40edae` | Active at `.agents/skills/frontend-design/SKILL.md`; registered in `skills-lock.json` |
| Claude Code frontend-design plugin equivalent | Official plugin 1.1.0, inspected commit `92bb6850f1bb51f4d18b03b23d643642f9d687b6` | Guidance byte-identical to active Codex skill; separate Claude-only manifest not installed |
| Frontend Aesthetics Cookbook | Anthropic cookbook commit `35f2eec7e44897c537e44441b7dff2f0ecbfb804` | Read as a research reference; no runtime install |
| Browser control plugin | Bundled Browser skill | Skill loaded; blocked because no in-app browser runtime is connected; local Chrome/Lighthouse fallback used |
| Plugin Management | Bundled plugin-management skill | Loaded for capability vetting; no external account connection needed |
| Delegation and review | Native Codex collaboration | Three research/discovery specialists complete; independent reviewer running |
| Version-aware library documentation | No documentation MCP exposed | Official docs/registries fallback active; exact versions and URLs retained in research digest |
| TDD / brainstorming workflow | No Superpowers-equivalent plugin exposed | Native gated plan/work-order/test protocol fallback active |
| Code review | No dedicated review plugin exposed | Separate native reviewer agent active; file/line verdict retained |

Full provenance, hashes, community candidates, and fallbacks: [`skills-installed.md`](skills-installed.md).

## Next decision

Gates 1–3 are decided. Gate 4 closes on the hardening/docs wave (WO-27–29, 31–33) and the before/after quality report (WO-33), to be ratified under the standing delegation and recorded in [`DECISIONS.md`](DECISIONS.md). The decisions that remain the user's: MT-01 approval (proposal §8 questions), anything cost-bearing (DEPLOY, a funded eval campaign), and the human screen-reader pass WO-27 prepares.
