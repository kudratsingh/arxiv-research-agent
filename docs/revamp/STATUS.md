# Frontend revamp status

Updated: 2026-08-28  
Branch: `docs/frontend-revamp-gate-1`  
Baseline: `e6e87396d32be5ae985c2d7cc0dd5ed6cf84b351`

## Current gate

**Gate 1 — approved 2026-08-28.** Independent second-pass review returned **APPROVE** with two minor, non-blocking findings (see [`REVIEW.md`](REVIEW.md)), and the human Gate 1 decisions are recorded in [`DECISIONS.md`](DECISIONS.md#d-009--gate-1-human-decisions): Direction A (Evidence Workbench), frozen-backend rule confirmed, vertical slice approved, and the shared-principal model **rejected as the end state** — real multi-tenancy is tracked as separate backend workstream MT-01.

No product implementation has started. No backend contract changed. No paid model, hosting, or provisioning action was taken.

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
| G2-01 | Phase 2 design brief | Unassigned | todo | — | Gate 1 PR merge | 2026-08-28 |
| MT-01 | Multi-tenancy backend proposal | Unassigned | todo | — | Own gated proposal + ADR; separate from this revamp | 2026-08-28 |
| EXEC | Product implementation | Unassigned | todo | — | Gate 2/3 | 2026-08-28 |
| DEPLOY | Hetzner CX23 Helsinki deployment | Unassigned | blocked | — | Server availability and explicit cost approval | 2026-08-28 |

Deliverables: [`00-DISCOVERY.md`](00-DISCOVERY.md), [`baseline/`](baseline/README.md), [`01-RESEARCH.md`](01-RESEARCH.md), [`skills-installed.md`](skills-installed.md), and [`02-DIRECTIONS.md`](02-DIRECTIONS.md).

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

Gate 1 is decided. Next: merge the Gate 1 PR, then Phase 2 — the Evidence Workbench design brief (tokens, architecture, budgets, migration strategy, work orders, dependency graph) toward Gate 2. The next human gate is Gate 2 approval of that package; MT-01 (multi-tenancy) needs its own proposal approval before any backend change.
