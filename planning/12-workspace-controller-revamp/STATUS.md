# STATUS: workspace controller revamp

Updated: **2026-11-03**. State: **PLANNED. Kit complete; implementation not
started.**

The implementing agent updates this file at every gate (G0–G8). Numbers are
pasted from command output and never typed by hand.

## Timeline

| When (2026-11-03, UTC) | What happened |
|---|---|
| 08:20 | Owner asked for a full revamp of the arXiv agent frontend: a VS Code / Claude Code style controller, one highlighted paper with move-to-next, the queue order in a sidebar, one large sidebar, black/white text with red accents, a cartoon mascot, and a bottom bar like Claude Code's. Five screenshots of the live workspace were attached. |
| 08:22 | The UI in the screenshots was not on `main`. It was found on `origin/codex/daily-workspace-*`, stacked preview ⊂ live ⊂ next ⊂ readiness, with the tip at `916f038`. |
| 08:27 | `claude/youthful-dirac-69v19d`, which had no commits of its own, was fast-forwarded to `codex/daily-workspace-readiness` and pushed. That brought in 23 commits over main. `npm ci` was run in `web/`. |
| 08:31 | Baseline: `vitest run tests/workspace tests/daily tests/shell tests/tokens.test.ts tests/copy tests/primitives` gave **53 files, 1417 tests passed**. `typecheck` clean, `lint` clean. |
| 08:30–09:05 | A six-agent read-only mapping workflow ran, producing [recon/](recon/) (guardrails, tests, reader, surfaces, styles, run path). The run-path agent brought up Postgres, the API and Next with offline seed data and ran the live e2e suite: **16/16 passed**. |
| 08:40–08:55 | The owner added references: "spotify has a nice frontend and designs that we can use" and a Claude Code web app screenshot ("this layout is also nice and clean"). The design direction was agreed in chat. |
| 08:55 | The owner set a time limit. A first handoff brief was written and pushed (`18096be`); it now lives at [recon/00-first-session-brief.md](recon/00-first-session-brief.md). |
| 09:05– | The owner asked for a full planning kit and a copyable prompt. This kit was written: `00`–`09`, `README`, `STATUS`, `tools/`, `evidence/before/`. |

## Key facts at handoff

- **Branch:** `claude/youthful-dirac-69v19d`. The code base is
  `916f038` plus the kit.
- **Baseline checks:** green (above). Budget measurements at `916f038`,
  from recon/01 §4:

  | Row | Measured / ceiling |
  |---|---|
  | emitted CSS | **17,321 / 17,408 B** (87 B headroom) |
  | `/workspace/today` | 157,032 / 169,984 |
  | `/workspace/radar` | 155,497 / 169,984 |
  | `/workspace/library` | 157,829 / 169,984 |
  | `/workspace/interests` | 162,655 / 169,984 |
  | `/workspace/items/[id]` | 162,472 / 169,984 |
  | `/workspace/operations` | 153,632 / 169,984 |
  | `/workspace/review` | 154,792 / 169,984 |

- **Palette mechanism tested green.** A scoped fence appended to
  `app/tokens.css` that redeclares the 23 `--color-*` roles under
  `.workspace-app` passed 189 targeted tests with no test changes (recon/01
  §2, Option B).
- **Local stack verified** ([08-local-stack.md](08-local-stack.md)).
  Seeding the rich demo at 45 minutes gives a 9-item, 5/5-sources edition.
  The live e2e suite gave 16/16 on the CI-fixture DB.

## Gate log (implementing agent fills this in)

| Gate | Commit | Date | Result | Notes / links |
|---|---|---|---|---|
| G0 Setup & baseline | | | | |
| G1 Foundations | | | | |
| G2 Shell | | | | |
| G3 Today controller | | | | |
| G4 Reader | | | | |
| G5 Radar & Library | | | | |
| G6 Interests · Sources · Review | | | | |
| G7 Polish | | | | |
| G8 Verify & ship | | | | |

## Deviations from the kit

*(Record any place where the code disagreed with the kit, and what was
chosen.)*

## Budget ratchets applied

*(Row, from, to, measured, headroom, commit. See 04 §6 for the caps.)*

## Follow-ups

*(Anything deferred, with the reason.)*
