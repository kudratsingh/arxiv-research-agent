# STATUS: workspace controller revamp

Updated: **2026-11-03**. State: **P0 baseline verified; isolated stack and before captures ready.**

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
| 09:05– | The owner asked for a full planning kit and a copyable prompt. This kit was written: `00`–`09`, `README`, `STATUS`, `tools/`, `evidence/before/`. Pushed as `f5be574`. |
| 09:13–09:31 | Independent review: fact-check and cold-read lenses returned **82 findings (7 blockers, 24 major, 51 minor)**, recorded as [10-review-corrections.md](10-review-corrections.md), which overrides 00–09. The requirements-coverage lens was stopped by the owner's time limit before it reported. |

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

## P0 / WO-0.1 — local baseline (application code unchanged from 916f038)

Starting branch head `82d538fc2b8c63769052fdc6a8a23610d67cf48b` includes the
new errata over `f5be574`; all82findings read. Local checks used their own
`node_modules` (`npm ci` exit0), locked Python resolving `src` to this worktree,
and the disabled provider key. No application source changed.

Commands, completed sequentially for final results: `npm run lint` (exit0),
`npm run typecheck` (exit0), `npm run budgets` (exit0), `npx vitest run` (exit0),
then the exact subset command from E71 (exit0). Copied command output:

```text
 Test Files  177 passed (177)
      Tests  3714 passed (3714)
   Duration  67.83s (transform 13.20s, setup 63.60s, import 23.37s, tests 180.06s, environment 161.96s)

 Test Files  53 passed (53)
      Tests  1417 passed (1417)
   Duration  18.44s (transform 3.99s, setup 12.02s, import 5.85s, tests 49.29s, environment 46.09s)
```

Every budget row, pasted from the build output:

```text
PASS      `/` first-load JS, excl. polyfill — 165,925 B (162.0 KiB) against 166,912 B (163.0 KiB)
PASS      `/c/[id]` first-load JS, excl. polyfill — 191,821 B (187.3 KiB) against 192,512 B (188.0 KiB)
PASS      `/learn` first-load JS, excl. polyfill — 164,643 B (160.8 KiB) against 166,912 B (163.0 KiB)
PASS      `/learn/paths/[id]` first-load JS, excl. polyfill — 165,562 B (161.7 KiB) against 169,984 B (166.0 KiB)
PASS      `/learn/sessions/[id]` first-load JS, excl. polyfill — 186,308 B (181.9 KiB) against 188,416 B (184.0 KiB)
PASS      `/learn/progress` first-load JS, excl. polyfill — 167,968 B (164.0 KiB) against 169,984 B (166.0 KiB)
PASS      Shared framework/runtime chunk — 134,089 B (130.9 KiB) against 139,264 B (136.0 KiB)
PASS      All emitted CSS — 17,378 B (17.0 KiB) against 17,408 B (17.0 KiB)
PASS      All self-hosted font files (woff2, latin subset) — 103,476 B (101.1 KiB) against 109,568 B (107.0 KiB)
EXTERNAL  Total transferred JS on a settled report route, incl. lazy chunks — not measured here against 245,760 B (240.0 KiB)
REPORTED  Derived: total first-load transfer for `/c/[id]`, cold cache — 312,675 B (305.3 KiB) against 319,488 B (312.0 KiB)
PASS      `/today` first-load JS, excl. polyfill — 153,283 B (149.7 KiB) against 163,840 B (160.0 KiB)
PASS      `/interests` first-load JS, excl. polyfill — 152,737 B (149.2 KiB) against 163,840 B (160.0 KiB)
PASS      `/library` first-load JS, excl. polyfill — 152,255 B (148.7 KiB) against 163,840 B (160.0 KiB)
PASS      `/library/items/[id]` first-load JS, excl. polyfill — 155,964 B (152.3 KiB) against 163,840 B (160.0 KiB)
PASS      `/workspace/today` first-load JS, excl. polyfill — 157,366 B (153.7 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/radar` first-load JS, excl. polyfill — 155,812 B (152.2 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/interests` first-load JS, excl. polyfill — 162,969 B (159.1 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/library` first-load JS, excl. polyfill — 158,145 B (154.4 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/items/[id]` first-load JS, excl. polyfill — 162,783 B (159.0 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/operations` first-load JS, excl. polyfill — 153,958 B (150.3 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/review` first-load JS, excl. polyfill — 155,128 B (151.5 KiB) against 169,984 B (166.0 KiB)
```

The first full test run overlapped the build: two bundle assertions read a
missing `.next/app-path-routes-manifest.json`; seven other failures were
sandbox loopback EPERM. Its log is retained at
`/private/tmp/controller-p0-vitest-concurrent.log`. A concurrently started
subset timed out under contention and was stopped (exit130), preserved as
`/private/tmp/controller-p0-vitest-subset-aborted.log`. No tests were edited.
The permitted post-build full run and isolated subset above both pass. All
subsequent gates run build and test commands sequentially.

The handoff's Linux87B CSS headroom is platform/build-specific: the local
production build above has30B. E27 governs temporary G1–G6 CSS overruns; no
budget ratchet has been applied. Existing owner services3137/8137/15438 and
private data remain untouched. PR285's backend qualification repair stays
on its separate unmerged branch; this requested frontend branch builds on916f038.
