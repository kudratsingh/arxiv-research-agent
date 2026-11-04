# STATUS: workspace controller revamp

Updated: **2026-11-04 UTC**. State: **G2 and G3 verified; focused Today ready for owner experience review. P4 onward deferred.**

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
| G0 Setup & baseline | `83bea0a` (verified app code unchanged from `82d538f` / `916f038`) | 2026-11-03 09:55 UTC | PASS | [Before captures](evidence/before/p0-macos/); logs and deviations below |
| G1 Foundations | `1bf1a0c816c74eaff7ac53735d6ae8990ef94ee3` (verified application tree) | 2026-11-03 10:25 UTC | PASS under E27 | [G1 captures](evidence/after/g1-foundations/); CSS-only interim overrun recorded below |
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

## P0 / WO-0.2 — isolated stack and before captures

The Linux-only stack recipe was adapted to macOS without changing backend code:
Compose project `arxiv-controller-p0`, Postgres15458, `workspace_rich` API8148/
frontend3148 and separate browser-test `workspace` API8149/frontend3149. Both
frontends run the real **production** build with CSP enabled. Every process
uses the disabled provider key; recurrence is off. The rich feed bytes and
browser fixtures are offline synthetic inputs, not live science/source evidence.
Separate explicit DB URLs applied E31; the owner's3137/8137/15438 were preserved.

Tool correction E79: screenshot capture accepts THEME/DPR, preserves BASE/ITEM,
names images by theme and width, waits on loaded content, and blocks forbidden
refresh POSTs. This explicitly required screenshot-tool edit is the exception
to the frontend-only source scope; application code is unchanged. No tests edited.

Copied browser-suite output:

```text
  16 passed (20.1s)
```

Image manifest (computed from PNG headers):

```text
{"count": 28, "pixel_widths": [780, 2880], "dpr": 2}
```

All7routes ×2themes ×2widths are in
[evidence/before/p0-macos](evidence/before/p0-macos/), with hashes and dimensions
in [capture-manifest.json](evidence/before/p0-macos/capture-manifest.json).
Today before: [dark desktop](evidence/before/p0-macos/desktop-dark-today.png),
[light desktop](evidence/before/p0-macos/desktop-light-today.png),
[dark390px](evidence/before/p0-macos/mobile-dark-today.png),
[light390px](evidence/before/p0-macos/mobile-light-today.png). Capture agent
reviewed all4Today images; root also inspected desktop dark/mobile light. The
long feed and second context column are the baseline to replace, not the new
controller. Capture reported no browser console errors; this is not a full CSP
audit. Initial sandbox Chromium launch failed; permitted retry succeeded.

Mandatory pre-push Python gate, copied output:

```text
6042 passed, 54 skipped, 53 deselected in 418.50s (0:06:58)
Total:   3658 lines
Missing: 19 lines
Coverage: 99%
```

The owner subsequently authorized the separate PR285/06c593f one-off paid
qualification experiment. Controller work remains at G0, with no P1 source
implementation yet; its key remains disabled. Waiting for the owner's promised
new frontend instructions while the independent experiment is prepared. No PR
was opened for this branch, no PR merged, and no owner data was modified.

## Owner steering: mascot name

The owner renamed the mascot **Jazzy**. The original red pixel bookmark-ribbon
design, moods and generic `Mascot` component API remain unchanged. Current kit
references and heading anchors were updated; this overrides the original name
default. No application branding or out-of-scope surfaces were renamed.

## P1 integration — foundations and Jazzy

WO-1.1 appends only the scoped23-role workspace palette and a header comment;
the existing global theme/Workbench declarations are unchanged. The scoped
contrast parser checks actual token values and both dark mechanisms. A deliberate
light-ink mutation failed at1.09:1 versus4.5:1 and was restored; the targeted
suite passed27files/568tests. Explicit missing-value guards fixed strict indexed
access in the new test without weakening its checks. E36/E41: the progress track
is decorative; the fill must contrast against it and the surrounding surfaces.

The first composed coverage run found one old EOF-slice assumption in
`tests/patterns/ReportReader.test.tsx`: its reader-token fence included all later
CSS. The assertion now stops before the separately scoped workspace fence,
preserving its no-media-query rule for the unchanged Report Reader. No production
Workbench source or CSS was changed. Test-edit reason: pinned old EOF layout.

WO-1.2 supplies original eight-part Jazzy SVG, icons and deterministic cover art.
E08 separates eyes/pupils/mouth/closed/alert paths; reduced-motion disables ambient
animation. `coverSeed` owns a small dedicated `lib/workspace/cover.ts` to avoid
P1 parallel ownership conflicts; component/cover tests remain separate from queue
tests. No runtime dependency was added. All current kit name references use Jazzy.

WO-1.3 preserves pinned Today/Library queues and exact reader targets, adds local
URL subscriptions with a named SSR snapshot, and a pure keymap. Today-only safe
focus retention preserves exact Library/Review return URLs (E07/E22/E70). Enter
and arrows leave native interactive controls alone; Shift guards were tightened
after root review. Queue/URL/commands plus cover helpers reach100%line/branch
coverage. Focused suite90tests passed; no existing request-body assertion changed.

Standard lint/typecheck pass. Composed full-suite/coverage output, copied:

```text
 Test Files  184 passed (184)
      Tests  3803 passed (3803)
Statements   : 98.31% ( 4435/4511 )
Branches     : 94.32% ( 3375/3578 )
Functions    : 92.23% ( 1591/1725 )
Lines        : 99.38% ( 3727/3750 )
```

G1 closure still awaits the measured build/budget record and phase screenshots;
E27 permits a recorded CSS-only interim overrun throughG6, with no early ratchet.
The approved one-off qualification remains separately prepared and waiting for
the owner's credential; frontend processes continue using the disabled sentinel.

## G1 closure / WO-1.4 — measured interim headroom

Verified source commits: WO-1.1 `9afe2df`, WO-1.2 `d0127fb`, WO-1.3 `1bf1a0c`.
The G1 full suite passes3803tests in184files and all original coverage floors.
Queue/URL/commands/cover helpers are each100%lines/branches. No new dependency,
backend source, source-refresh behavior or API request body changed.

Build succeeds. Budget command exits1 **only for emitted CSS**. This is the
explicit E27 interim G1–G6 allowance, not a green budget claim: scoped palette
raises CSS to17944B against17408B. No ratchet was applied. G7 must remove
`components/workspace/workspace.css`, reduce first, and finish within the
pre-authorized caps. All JS rows pass. Exact command output:

```text
PASS      `/` first-load JS, excl. polyfill — 165,929 B (162.0 KiB) against 166,912 B (163.0 KiB)
PASS      `/c/[id]` first-load JS, excl. polyfill — 191,824 B (187.3 KiB) against 192,512 B (188.0 KiB)
PASS      `/learn` first-load JS, excl. polyfill — 164,641 B (160.8 KiB) against 166,912 B (163.0 KiB)
PASS      `/learn/paths/[id]` first-load JS, excl. polyfill — 165,560 B (161.7 KiB) against 169,984 B (166.0 KiB)
PASS      `/learn/sessions/[id]` first-load JS, excl. polyfill — 186,312 B (181.9 KiB) against 188,416 B (184.0 KiB)
PASS      `/learn/progress` first-load JS, excl. polyfill — 167,966 B (164.0 KiB) against 169,984 B (166.0 KiB)
PASS      Shared framework/runtime chunk — 134,087 B (130.9 KiB) against 139,264 B (136.0 KiB)
BREACH    All emitted CSS — 17,944 B (17.5 KiB) against 17,408 B (17.0 KiB)
PASS      All self-hosted font files (woff2, latin subset) — 103,476 B (101.1 KiB) against 109,568 B (107.0 KiB)
EXTERNAL  Total transferred JS on a settled report route, incl. lazy chunks — not measured here against 245,760 B (240.0 KiB)
REPORTED  Derived: total first-load transfer for `/c/[id]`, cold cache — 313,244 B (305.9 KiB) against 319,488 B (312.0 KiB)
PASS      `/today` first-load JS, excl. polyfill — 153,281 B (149.7 KiB) against 163,840 B (160.0 KiB)
PASS      `/interests` first-load JS, excl. polyfill — 152,735 B (149.2 KiB) against 163,840 B (160.0 KiB)
PASS      `/library` first-load JS, excl. polyfill — 152,253 B (148.7 KiB) against 163,840 B (160.0 KiB)
PASS      `/library/items/[id]` first-load JS, excl. polyfill — 155,962 B (152.3 KiB) against 163,840 B (160.0 KiB)
PASS      `/workspace/today` first-load JS, excl. polyfill — 157,395 B (153.7 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/radar` first-load JS, excl. polyfill — 155,841 B (152.2 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/interests` first-load JS, excl. polyfill — 162,995 B (159.2 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/library` first-load JS, excl. polyfill — 158,174 B (154.5 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/items/[id]` first-load JS, excl. polyfill — 162,808 B (159.0 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/operations` first-load JS, excl. polyfill — 153,985 B (150.4 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/review` first-load JS, excl. polyfill — 155,159 B (151.5 KiB) against 169,984 B (166.0 KiB)
```

Required pre-push Python gate output:

```text
6042 passed, 54 skipped, 53 deselected in 474.03s (0:07:54)
Total:   3658 lines
Missing: 19 lines
Coverage: 99%
```

G1 Today preview (palette-only; shell/controller integration is still P2/P3):
[dark desktop](evidence/after/g1-foundations/desktop-dark-today.png),
[light desktop](evidence/after/g1-foundations/desktop-light-today.png),
[dark390px](evidence/after/g1-foundations/mobile-dark-today.png),
[light390px](evidence/after/g1-foundations/mobile-light-today.png).
All four are DPR2 from the offline synthetic rich seed; capture manifest records
zero console errors. Root inspected dark desktop and light mobile.

Owner steering superseded the temporary waiting state: frontend agents continue
through the gates while the separately approved experiment awaits its credential.
Astra medium owns the complex foundations/shell lane; Terra high owns bounded
visual primitives and keyboard/composer work. Frontend remains sentinel-only,
no source refresh, recurrence disabled, owner data/services preserved, no PR.


## G2 closure — responsive Shell and explicit sample provenance

Source attribution: WO-2.2 `c6b109e` (composer/commands), WO-2.1 `235f676`
(Shell/slots/preferences/provenance and cached-drawer fix). Starting head was
`6a4c6b8`; fetch found no newer controller-branch work. `origin/main` is already
an ancestor. Existing local P2 work was preserved.

`WORKSPACE_SYNTHETIC_PREVIEW=1` is read explicitly on the server. The isolated
[design preview](http://localhost:3148/workspace/today) persistently states
**Design preview · synthetic sample papers** and labels coverage as sample
checks. With the flag absent, production retains its real-metadata and private
save wording. Save and evidence-scope boundaries are unchanged. No hostname or
paper-ID guessing is used. Seeded checks do not establish live source coverage.

Commands: `npm run lint`, `npm run typecheck`, `npm test -- --coverage`,
`npm run budgets`; live regression command:
`WORKSPACE_LIVE_URL=http://127.0.0.1:3149 npx --no-install playwright test --config=live-workspace-e2e/playwright.config.ts --reporter=line`.
All processes used the disabled-key sentinel. Actual output:

```text
 Test Files  188 passed (188)
      Tests  3833 passed (3833)
Statements   : 98.37% ( 4649/4726 )
Branches     : 94.67% ( 3572/3773 )
Functions    : 92.42% ( 1636/1770 )
Lines        : 99.41% ( 3902/3925 )
  16 passed (21.0s)
6042 passed, 54 skipped, 53 deselected in 443.14s (0:07:23)
Total:   3658 lines
Missing: 19 lines
Coverage: 99%
```

Browser audit: `NODE_PATH=web/node_modules node outputs/controller-session/g2-shell-audit.cjs`
(run from the worktree, with the NODE_PATH resolved absolutely). Actual result:

```json
{"cases": 80, "failed": 0, "console_errors": 0, "page_errors": 0, "failed_requests": 0, "blocked_requests": 0}
```

[Full browser record](evidence/after/g2-shell/browser-audit.json) covers all seven
surfaces, Reader discovered through a fixture link, both themes, widths 1440,
390, 768 and 1024; active navigation, collapse, drawer trap/Escape/focus return,
route closure, composer query and slash routing. Unit coverage proves inline
and single portal rendering, enabled-control dispatch, native-field guards,
inert/disabled protection and one status region. Existing durable save, failed
save, source-version, keyboard, note export and review assertions remain green.
No live-suite assertion was weakened or changed.

The first broader audit exposed a real cached-template defect: Back could
restore Today with the drawer open even after the page fully rendered. Added
a `popstate` dismissal listener and a Back/Forward regression. The original
audit had four failures; the final audit above reran all cases successfully.

CSS-only budget exit 1 remains the explicit E27 allowance through G6; no
ratchet or coverage floor changed. Build succeeds, every JS row passes:

```text
PASS      `/` first-load JS, excl. polyfill — 166,241 B (162.3 KiB) against 166,912 B (163.0 KiB)
PASS      `/c/[id]` first-load JS, excl. polyfill — 192,136 B (187.6 KiB) against 192,512 B (188.0 KiB)
PASS      `/learn` first-load JS, excl. polyfill — 164,953 B (161.1 KiB) against 166,912 B (163.0 KiB)
PASS      `/learn/paths/[id]` first-load JS, excl. polyfill — 165,872 B (162.0 KiB) against 169,984 B (166.0 KiB)
PASS      `/learn/sessions/[id]` first-load JS, excl. polyfill — 186,624 B (182.3 KiB) against 188,416 B (184.0 KiB)
PASS      `/learn/progress` first-load JS, excl. polyfill — 168,278 B (164.3 KiB) against 169,984 B (166.0 KiB)
PASS      Shared framework/runtime chunk — 134,090 B (130.9 KiB) against 139,264 B (136.0 KiB)
BREACH    All emitted CSS — 20,313 B (19.8 KiB) against 17,408 B (17.0 KiB)
PASS      All self-hosted font files (woff2, latin subset) — 103,476 B (101.1 KiB) against 109,568 B (107.0 KiB)
PASS      `/today` first-load JS, excl. polyfill — 153,593 B (150.0 KiB) against 163,840 B (160.0 KiB)
PASS      `/interests` first-load JS, excl. polyfill — 153,047 B (149.5 KiB) against 163,840 B (160.0 KiB)
PASS      `/library` first-load JS, excl. polyfill — 152,565 B (149.0 KiB) against 163,840 B (160.0 KiB)
PASS      `/library/items/[id]` first-load JS, excl. polyfill — 156,274 B (152.6 KiB) against 163,840 B (160.0 KiB)
PASS      `/workspace/today` first-load JS, excl. polyfill — 162,262 B (158.5 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/radar` first-load JS, excl. polyfill — 160,708 B (156.9 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/interests` first-load JS, excl. polyfill — 167,855 B (163.9 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/library` first-load JS, excl. polyfill — 163,041 B (159.2 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/items/[id]` first-load JS, excl. polyfill — 167,672 B (163.7 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/operations` first-load JS, excl. polyfill — 158,844 B (155.1 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/review` first-load JS, excl. polyfill — 160,024 B (156.3 KiB) against 169,984 B (166.0 KiB)
```

G7 still must consolidate and delete `components/workspace/workspace.css`
before applying any permitted CSS ratchet. P2 retains the old multi-card Today
content; the single-paper reading stage is P3. Desktop uses an internal stage
scroller, so its full-page captures show that viewport rather than every paper.

Today captures (synthetic data, DPR2):
[dark desktop](evidence/after/g2-shell/desktop-dark-today.png),
[light desktop](evidence/after/g2-shell/desktop-light-today.png),
[dark mobile](evidence/after/g2-shell/mobile-dark-today.png),
[light mobile](evidence/after/g2-shell/mobile-light-today.png).

Applied errata: E20/E21 three slots and Shell-owned composer; E25 retained
`daily-app`; E15 uses the permitted alternative of suppressing Shell export on
Library; E28 reserves palette UI for P7. E42/RC05 deviation: the cosmetic
sidebar preference has an in-document fallback when storage is blocked, with
SSR snapshots and failure tests. The only existing test edit, routes.test.tsx,
asserts admitted content through the new provider rather than a raw JSX return;
all admission and product-truth assertions stay intact.

Owner workspace 3137/API8137/PG15438 and owner preferences remain untouched.
Verification uses isolated PG15458, APIs8148/8149 and the e2e principal. Backend
source and dependencies are unchanged. Provider contacts/spend are zero,
recurrence disabled. Per latest owner steering the qualification experiment is
deferred: no key request/configuration/test or automatic execution tonight.
P4 onward is outside this batch; no PR opened and no merge performed.


## G3 closure / WO-3.1–3.2 — one pinned paper in focus

Verified implementation commit: **`d4f5855ff2b5863baee73c02d10ff452904b267b`**.
This gate-record commit contains only documentation and browser evidence.
[Runnable design preview](http://localhost:3148/workspace/today) ·
[desktop/mobile walkthrough and exact run commands](evidence/after/g3-today/WALKTHROUGH.md).

Today has one paper article, its full available abstract, retained-version
byline, relevance rationale and explicit evidence scope. The ordered edition
queue lives in the sidebar; the bar owns bounded navigation and the single
Save/Dismiss/Snooze/Undo controls. Search has a visible submit button. Local
commands use the current enabled control. The exact edition version is passed
through readerTarget; an unavailable pinned version is omitted with the
existing warning, never replaced by a newer version.

Queue/Previous/Next/j/k use reactive focus URL replacement. Back/Forward and
reload retain selection. Successful dismiss/snooze chooses the next surviving
item or predecessor at the boundary; failed writes leave the selection and
retry identity intact. Undo restores the original paper even after manual
navigation, and a failed Undo leaves the current selection unchanged. The
reading hook now returns success booleans and exposes its Undo work id; request
bodies and revision/idempotency behavior are unchanged. Pending mutations,
profile writes and refresh disable conflicting writes while navigation remains
available.

The new multi-paper module uses four items, plus evidence-scope cases for PDF
text, selected PDF pages, feed excerpt and metadata. It covers delayed saves,
failed writes, native/inert controls, exact Reader anchors, older/missing
versions, unknown focus, drawer selection and source-health states. All former
Today/Reader/Library/save/conflict/version assertions remain unchanged; the
existing focused regression set passed without any layout-test edits.

Final commands: `npm run lint`, `npm run typecheck`, `npm test -- --coverage`,
`npm run budgets`; the unchanged live Playwright suite against fresh isolated
DB `workspace_e2e_g3_final` through API8149/web3149. Python invocation:
`env -u POSTGRES_URL -u WORKSPACE_RATE_DATABASE_URL WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15458/workspace make test-cov-diff VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python`
(with the disabled-key sentinel). Actual output:

```text
 Test Files  189 passed (189)
      Tests  3858 passed (3858)
Statements   : 98.36% ( 4684/4762 )
Branches     : 94.69% ( 3677/3883 )
Functions    : 92.35% ( 1644/1780 )
Lines        : 99.36% ( 3935/3960 )
  16 passed (21.0s)
6042 passed, 54 skipped, 53 deselected in 408.78s (0:06:48)
Total:   3658 lines
Missing: 19 lines
Coverage: 99%
```

Full committed [browser audit](evidence/after/g3-today/browser-audit.json) and
[reproduction script](evidence/after/g3-today/audit.cjs) exercise the richer
nine-paper edition in both themes at desktop/mobile, plus tablet transitions.
Actual final result:

```json
{"cases": 43, "failed": 0, "unexpected_console_errors": 0, "page_errors": 0, "failed_requests": 0, "blocked_requests": 0, "expected_injected_503": 1}
```

Read-only axe on Today, both themes at desktop and mobile:

```json
[
  {
    "width": 1440,
    "theme": "dark",
    "violations": 0,
    "seriousCritical": 0
  },
  {
    "width": 1440,
    "theme": "light",
    "violations": 0,
    "seriousCritical": 0
  },
  {
    "width": 390,
    "theme": "dark",
    "violations": 0,
    "seriousCritical": 0
  },
  {
    "width": 390,
    "theme": "light",
    "violations": 0,
    "seriousCritical": 0
  }
]
```

[Detailed axe record](evidence/after/g3-today/axe.json). This Today coverage is
not the future G7 all-route accessibility matrix.

Visual review found a real issue the initial title-top check missed: the mobile
player covered most of the title. The repaired mobile layout removes duplicate
header Read/position/date presentation, keeps notice/source checks/breadcrumb,
tightens the continuation strip, and puts the entire title across the reading
column below a small cover row. The bar retains Read/progress; Edition details
retain the date/context; Source and pin options remain reachable. The audit now
requires the whole title to clear the bar on initial load, queue selection and
Reader return, in both themes. Captured mobile title ends above the player;
measurements are retained in the browser receipt and [mobile geometry record](evidence/after/g3-today/mobile-geometry.json).

Independent read-only review found and fixed two additional concrete issues:
progress used the wrong track token (now the approved subtle track), and a new
byline could fall back to newer authors for an older version with no authors.
Missing authors now remain explicitly unknown for that version, with a
regression test. Browser contrast checks enforce the progress fill/track bound
in every audited context. Desktop composition is preserved. Jazzy appears in
branding and Today loading/error/empty states; current name scans find no Folio.

Screenshots (synthetic sample data, DPR2, actual viewport):
[dark desktop](evidence/after/g3-today/desktop-dark-today.png),
[light desktop](evidence/after/g3-today/desktop-light-today.png),
[dark mobile](evidence/after/g3-today/mobile-dark-today.png),
[light mobile](evidence/after/g3-today/mobile-light-today.png),
[mobile queue](evidence/after/g3-today/mobile-dark-queue-open.png),
[Reader return](evidence/after/g3-today/desktop-dark-reader-return.png).
Root inspected desktop and mobile captures; browser verification is separate
from owner experience approval.

Final build succeeds; every JS ceiling is preserved and passes. CSS-only
budget exit 1 remains E27's explicit interim G1–G6 allowance, with no ratchet:

```text
PASS      `/` first-load JS, excl. polyfill — 166,240 B (162.3 KiB) against 166,912 B (163.0 KiB)
PASS      `/c/[id]` first-load JS, excl. polyfill — 192,135 B (187.6 KiB) against 192,512 B (188.0 KiB)
PASS      `/learn` first-load JS, excl. polyfill — 164,952 B (161.1 KiB) against 166,912 B (163.0 KiB)
PASS      `/learn/paths/[id]` first-load JS, excl. polyfill — 165,871 B (162.0 KiB) against 169,984 B (166.0 KiB)
PASS      `/learn/sessions/[id]` first-load JS, excl. polyfill — 186,623 B (182.2 KiB) against 188,416 B (184.0 KiB)
PASS      `/learn/progress` first-load JS, excl. polyfill — 168,277 B (164.3 KiB) against 169,984 B (166.0 KiB)
PASS      Shared framework/runtime chunk — 134,089 B (130.9 KiB) against 139,264 B (136.0 KiB)
BREACH    All emitted CSS — 22,346 B (21.8 KiB) against 17,408 B (17.0 KiB)
PASS      All self-hosted font files (woff2, latin subset) — 103,476 B (101.1 KiB) against 109,568 B (107.0 KiB)
PASS      `/today` first-load JS, excl. polyfill — 153,592 B (150.0 KiB) against 163,840 B (160.0 KiB)
PASS      `/interests` first-load JS, excl. polyfill — 153,046 B (149.5 KiB) against 163,840 B (160.0 KiB)
PASS      `/library` first-load JS, excl. polyfill — 152,564 B (149.0 KiB) against 163,840 B (160.0 KiB)
PASS      `/library/items/[id]` first-load JS, excl. polyfill — 156,273 B (152.6 KiB) against 163,840 B (160.0 KiB)
PASS      `/workspace/today` first-load JS, excl. polyfill — 167,200 B (163.3 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/radar` first-load JS, excl. polyfill — 161,210 B (157.4 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/interests` first-load JS, excl. polyfill — 168,324 B (164.4 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/library` first-load JS, excl. polyfill — 163,543 B (159.7 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/items/[id]` first-load JS, excl. polyfill — 168,141 B (164.2 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/operations` first-load JS, excl. polyfill — 159,313 B (155.6 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/review` first-load JS, excl. polyfill — 160,493 B (156.7 KiB) against 169,984 B (166.0 KiB)
```

G7 must consolidate/delete `components/workspace/workspace.css` and reduce
before any allowed final ratchet. Budget files, coverage floors, backend source,
fictional-preview production files and Evidence Workbench files were not changed.

### Failed, interrupted and unrun checks

- One Python invocation incorrectly used the runtime rate-governor override,
  causing a local-file-governor assertion and skipping DB tests. No source/test
  assertion was changed. Corrected to WORKSPACE_TEST_POSTGRES_URL, proved the
  failing test passes, and reran the full gate above with DB integration active.
- A repeated live-suite run on the already-used regression API hit its unchanged
  per-key write quota (HTTP429): two failed, two did not run, twelve passed. The
  final full suite above uses a fresh isolated DB/API process and passes. No
  rate limit, timeout, save assertion, or test tier was weakened.
- One exploratory audit recorded two canceled same-origin Next RSC requests
  during rapid navigation. Explicit network settlement between cases and before
  context close removes the cancellation; final raw records report zero failed
  requests. The one 503 in the final audit is deliberate failure injection.
- Python's skips and deselected e2e tier are shown in the exact output above.
  No provider trial, real source-intake quality, physical-phone test, owner
  usefulness judgment, or broader G7 visual/accessibility matrix is claimed.
- GitHub CI has no run for branch-only pushes here: ci.yml triggers on main
  pushes or PRs, and the owner explicitly requested no controller PR. Local
  phase gates above are the verified evidence, not a green GitHub CI claim.

### Scope and remaining work

P2 and P3 are complete for review. P4 Reader redesign and later surfaces, palette
UI and G7 CSS consolidation are deferred by this batch's scope. Reader itself
retains all manual reading/notes, exact source scope, durable failure recovery
and return behavior. The design preview remains synthetic, with live refresh
disabled on Today; production defaults keep real-metadata wording. Reversible
fixture tests restore reading fields but advance revision/activity history,
which is explicitly recorded rather than presented as a full rollback.

Owner 3137/API8137/PG15438 and owner data/preferences remain intact. Verification
writes use only the isolated e2e fixture accounts/databases. Provider contacts
and spend remain zero; recurrence remains disabled. The separately approved
qualification worktree is unchanged and unexecuted; no real-key request,
configuration, test, or automatic start was performed. All PRs stay unmerged;
no new controller PR was opened. Stop at this G3 experience review.
