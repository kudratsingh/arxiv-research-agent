# Workspace controller revamp: planning kit

Prepared **2026-11-03** for Kudrat Singh and the implementation agent.

This kit turns the live research workspace (`/workspace/*`) from a long
scrolling list into an **integrated controller**:
- **One focused paper** at a time, stepped through with prev and next.
- **One large sidebar** with the ordered queue and every control.
- **A floating bottom control bar**, modelled on the Claude Code web
  composer and Spotify's now-playing bar.
- A **high-contrast black / white / red** palette in dark and light.
- An original **cartoon pixel mascot**, Folio.

The visual and layout references are the Claude Code web app, Spotify and
VS Code. Only their patterns are borrowed; none of their assets are.

> **Start here:** paste [09-agent-prompt.md](09-agent-prompt.md) into the
> coding agent. It points the agent at everything else, in order.

## Contents

| File | Purpose |
|---|---|
| [00-charter.md](00-charter.md) | The owner's words verbatim, scope and non-goals, success criteria S1–S8, design, engineering and product-truth principles |
| [01-references.md](01-references.md) | Claude Code web, the Claude Code composer, Spotify and VS Code: what we take from each and what we don't |
| [02-design-system.md](02-design-system.md) | Palette for both themes with a computed contrast table, typography, space, radius, motion, icons, the **Folio mascot pixel grid**, cover tiles, component specs |
| [03-screens-and-flows.md](03-screens-and-flows.md) | Shell anatomy with desktop, tablet and mobile wireframes, keyboard map, control bar, and per-route layouts for Today, Reader, Radar, Library, Interests, Sources & checks and Review, plus global states and the command palette |
| [04-architecture.md](04-architecture.md) | File plan; Shell; slots (portal with inline fallback); URL focus state; the `data-command` keyboard and palette mechanism; budgets with a pre-authorized ratchet; CSS rules; accessibility contract |
| [05-phases-and-work-orders.md](05-phases-and-work-orders.md) | P0–P8 (P9 optional): work orders with owned files, steps, tests and acceptance |
| [06-gates-and-verification.md](06-gates-and-verification.md) | Gate criteria G0–G8, standard check commands, visual QA checklist, Definition of Done |
| [07-test-impact.md](07-test-impact.md) | Which tests break and why, what may change versus what must not, copy that must stay verbatim, e2e plan, new tests to add |
| [08-local-stack.md](08-local-stack.md) | **Verified** recipe to run Postgres, the API and Next with offline seeded data; screenshots; live e2e (16/16 baseline) |
| [09-agent-prompt.md](09-agent-prompt.md) | The copyable assignment for the coding agent |
| [STATUS.md](STATUS.md) | Timeline so far and the live record to update at every gate |
| [recon/](recon/) | Six read-only discovery reports with file:line evidence: guardrails, tests, reader, surfaces, styles, run path. They also hold the first-session brief. |
| [tools/](tools/) | `rich_seed.py` (offline 9-item demo seed, loopback-only) and `shot.cjs` (7 routes × desktop/mobile screenshots) |
| [evidence/before/](evidence/before/) | "Before" captures from the seeded stack. The implementer adds `evidence/after/`. |

## Decisions

### Settled by the owner

| Decision | Setting |
|---|---|
| Interaction model | One highlighted paper at a time, with move-to-next; the queue order is visible in a sidebar |
| Sidebars | Exactly **one** large sidebar holding all controls ("for now") |
| Palette | High contrast: black and white for text, **red accents** |
| Personality | Cartoonish or modern integrated look, with a mascot (our own) |
| Bottom bar | Like the Claude Code web composer |
| References | Claude Code web layout, Spotify and VS Code / Codex |

### Defaults the agent should use unless the owner says otherwise

| Topic | Default |
|---|---|
| Scope | Live workspace only (`/workspace/*`). Evidence Workbench, learn and the fictional preview are unchanged (P9 is optional). |
| Theme | Keep Light / Dark / System. Design dark first; light gets equal finish. |
| Mascot | "Folio", a red pixel bookmark creature (grid in 02 §6). The owner may rename or restyle it. |
| Brand text | Keep "Research workspace". |
| Review in nav | Yes, promoted to the sixth nav row. |
| Command palette | Yes, lazy-loaded (`⌘K`), plus `?` shortcuts help. |
| Budgets | Ratchets pre-authorized up to the caps in 04 §6 (CSS ≤ 26 KiB; live route JS ≤ +8 KiB each). |
| PR | Push the branch only; no PR unless asked. |

### Open decisions (ask the owner only if they block)

1. Should the composer eventually *ask about this paper* through a model?
   This would be P9.2 and needs spend approval. Today it is search plus
   commands only.
2. Should the new palette later extend app-wide (P9.1)?
3. Should a right-hand context panel come later (P9.3)?

## Relationship to the other kits

- This kit builds directly on
  [11-daily-research-workspace](../11-daily-research-workspace/README.md),
  which delivered the live workspace's data model, routes and honesty rules.
  This kit changes **presentation and interaction only**.
- The repo's governance (tokens, copy, CSP, budgets, coverage) comes from
  the Evidence Workbench revamp in `docs/revamp/` and the assurance
  campaign in [08-assurance](../08-assurance/STATUS.md). This kit works
  within those rules and relaxes them only through recorded ratchets.
