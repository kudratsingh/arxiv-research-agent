# STATUS: workspace controller revamp

Updated: **2026-11-04 UTC**. State: **G6 supporting screens and owner-authorized paper/navigation refinement verified under E27. G7 consolidation remains pending.**

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
| G2 Shell | `235f676` (verified source; evidence attribution below) | 2026-11-04 02:42 UTC | PASS under E27 | See phase evidence and measurements below |
| G3 Today controller | `d4f5855` (verified source; evidence attribution below) | 2026-11-04 03:10 UTC | PASS under E27 | See phase evidence and measurements below |
| G4 Reader | `a933a71` (verified source; evidence attribution below) | 2026-11-04 06:05 UTC | PASS under E27 | See phase evidence and measurements below |
| G5 Radar & Library | `ade234b` (verified source; evidence attribution below) | 2026-11-04 07:19 UTC | PASS under E27 | See phase evidence and measurements below |
| G6 Interests · Sources · Review | `fda9d7616e8cbd0d882bcc41510a997ade117bf9` (verified application tree; source binding below) | 2026-11-04 | PASS under E27 | [P6 preview, browser walkthrough and recordings](evidence/after/p6-supporting-workflow/README.md); local checks below |
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


## Owner follow-up — mobile reading-density checkpoint

Source **`8ec35f8f026af207a618eebd4f013c2802259396`**. Starting pushed head
`3222ea8` was clean; fetch found no newer controller work. The owner extended
the batch through mobile density and P4, superseding the earlier stop at G3.

Mobile search is collapsed until Open search or `/`. Escape/Close search return
focus to the same toggle and preserve query/help; desktop search stays present.
The collapsed player retains navigation, Read and all paper actions, with 44px
controls and disabled boundaries. Smaller decorative cover/gaps/preamble recover
space without changing the 24px title, 16px abstract or source text sizes.
Synthetic notice, source/evidence disclosures, queue, exact versions/anchors,
URL focus and mutation/Undo logic are preserved.

The first stricter browser pass caught long-title second lines under the player.
A further spacing repair fixed it; no geometry assertion or type size was
weakened. The final read-only audit separately identifies actual API data (all
synthetic papers) and intercepted GET-state-only layout variants. One-, two-
and three-line abstract fixtures must render their declared line counts. Each
case requires the entire title and first min(2, available) rendered text lines
to clear the collapsed player on initial, queue selection and Reader return.
The intercepted variants are layout evidence, not source or persistence proof.

Actual browser result:

```json
{"cases": 30, "failures": 0, "blocked": 0, "consoleErrors": 0, "pageErrors": 0, "requestFailures": 0}
```

[Browser record](evidence/after/mobile-density/browser-audit.json) ·
[reproduction script](evidence/after/mobile-density/audit.cjs).

`npm run lint`, direct ESLint on the touched Shell/shortcut tests,
`npm run typecheck`, `npm test -- --coverage` and `make test-cov-diff` pass:

```text
 Test Files  189 passed (189)
      Tests  3862 passed (3862)
Statements   : 98.36% ( 4702/4780 )
Branches     : 94.72% ( 3699/3905 )
Functions    : 92.36% ( 1646/1782 )
Lines        : 99.37% ( 3948/3973 )
6042 passed, 54 skipped, 53 deselected in 473.25s (0:07:53)
Total:   3658 lines
Missing: 19 lines
Coverage: 99%
```

The new Shell mini-map warning came from resetting the subscribed cosmetic
preference outside act during test teardown; the reset is now wrapped in act.
No warning was filtered or silenced. The export stub now has the same download
attribute as production, allowing direct lint without disabling a rule. A new
test initially used an unsupported query option; corrected the test option and
reran typecheck and full coverage successfully. Existing assertions remain.

Production build succeeds. All JS ceilings pass; CSS is still the documented
interim E27 exception, with G7 consolidation unchanged and no ratchet:

```text
PASS      `/` first-load JS, excl. polyfill — 166,236 B (162.3 KiB) against 166,912 B (163.0 KiB)
PASS      `/c/[id]` first-load JS, excl. polyfill — 192,132 B (187.6 KiB) against 192,512 B (188.0 KiB)
PASS      `/learn` first-load JS, excl. polyfill — 164,954 B (161.1 KiB) against 166,912 B (163.0 KiB)
PASS      `/learn/paths/[id]` first-load JS, excl. polyfill — 165,873 B (162.0 KiB) against 169,984 B (166.0 KiB)
PASS      `/learn/sessions/[id]` first-load JS, excl. polyfill — 186,619 B (182.2 KiB) against 188,416 B (184.0 KiB)
PASS      `/learn/progress` first-load JS, excl. polyfill — 168,279 B (164.3 KiB) against 169,984 B (166.0 KiB)
PASS      Shared framework/runtime chunk — 134,091 B (130.9 KiB) against 139,264 B (136.0 KiB)
BREACH    All emitted CSS — 22,468 B (21.9 KiB) against 17,408 B (17.0 KiB)
PASS      All self-hosted font files (woff2, latin subset) — 103,476 B (101.1 KiB) against 109,568 B (107.0 KiB)
PASS      `/today` first-load JS, excl. polyfill — 153,594 B (150.0 KiB) against 163,840 B (160.0 KiB)
PASS      `/interests` first-load JS, excl. polyfill — 153,048 B (149.5 KiB) against 163,840 B (160.0 KiB)
PASS      `/library` first-load JS, excl. polyfill — 152,566 B (149.0 KiB) against 163,840 B (160.0 KiB)
PASS      `/library/items/[id]` first-load JS, excl. polyfill — 156,275 B (152.6 KiB) against 163,840 B (160.0 KiB)
PASS      `/workspace/today` first-load JS, excl. polyfill — 167,407 B (163.5 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/radar` first-load JS, excl. polyfill — 161,406 B (157.6 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/interests` first-load JS, excl. polyfill — 168,520 B (164.6 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/library` first-load JS, excl. polyfill — 163,739 B (159.9 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/items/[id]` first-load JS, excl. polyfill — 168,337 B (164.4 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/operations` first-load JS, excl. polyfill — 159,509 B (155.8 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/review` first-load JS, excl. polyfill — 160,689 B (156.9 KiB) against 169,984 B (166.0 KiB)
```

Preview: http://localhost:3148/workspace/today. Captures:
[dark desktop](evidence/after/mobile-density/desktop-dark-today.png),
[light desktop](evidence/after/mobile-density/desktop-light-today.png),
[dark mobile](evidence/after/mobile-density/mobile-dark-today.png),
[light mobile](evidence/after/mobile-density/mobile-light-today.png),
[long-title layout-only dark](evidence/after/mobile-density/mobile-dark-layout-only-long-title.png),
[long-title layout-only light](evidence/after/mobile-density/mobile-light-layout-only-long-title.png).

Only isolated synthetic accounts were read by this density audit; no browser
writes or external/source/provider contacts occurred. Owner 3137/data/preferences
remain untouched. Recurrence disabled; key setup/qualification remain deferred;
all PRs unmerged and no new PR opened. P4 source implementation starts after
this completed density checkpoint; its full live regression and Reader loop
will use fresh isolated fixture data.


## G4 — Reader integration and final mobile regression

Application source **`5fdbf48e35abce86ff09f99c40d7b3481c8c9d9d`**; final guard-test checkpoint **`a933a7195de41a33c473520b45e61a2d7d9235db`**; preceding mobile source
`8ec35f8`, pushed checkpoint `6df8694`. This gate adds evidence/status only after
the tested source commit. No newer controller branch work was found on fetch.

Reader now uses the Shell sidebar queue and floating reading actions, retaining
Back, version picker, Source/Understand/Your notes and the native note form in
main exactly once. Today queue respects edition order/pinned versions; Library
preserves view; Review uses its explicit packet order/version. Radar or missing,
failed or unknown Review packets stay honest back-only. Queue admission still
requires a work in state.works. No packet-only mutation shortcut was added.

Queue/version/Back navigation blocks while busy or when a private draft cannot
be stored. Existing source IDs/Unicode-codepoint offsets, draft keys, revision
and idempotency request bodies remain intact. Tab focus/scroll waits for panel
DOM commit. Desktop keeps panels available; mobile shows the active panel.
Missing older-version authors are unavailable rather than copied from latest.

A deferred-response regression reproduced a pre-existing private-text loss:
editing while an older entry save was pending could have new text cleared by
that response. Entry saves now temporarily lock the editor/kind/discard and
prevent a second submission or passage retarget; ordinary reading requests do
not lock the editor. Successful acknowledgement precedes clearing. The focused
test proves one request and retained pending text; recovery/conflict tests pass.

Existing test edits strengthen or adapt layout only: recovery test first proves
unsaved text blocks version switching, then explicitly discards before its
original version/ViewLatest assertions. Retained test awaits the genuinely
lazy synthetic context picker; request/anchor assertions remain unchanged.
The Shell act warning was fixed at the prior mobile gate without filtering.

### Local checks on source5fdbf48

`npm run lint`, direct touched-test ESLint, `npm run typecheck`,
`npm test -- --coverage`, production build and every JS budget row pass.
20 focused Reader tests and 97 existing focused tests pass. Full results pasted
from command logs:

```text
 Test Files  190 passed (190)
      Tests  3882 passed (3882)
Statements   : 98.15% ( 4785/4875 )
Branches     : 94.53% ( 3803/4023 )
Functions    : 92.29% ( 1664/1803 )
Lines        : 99.25% ( 4014/4044 )
  16 passed (22.9s)
6042 passed, 54 skipped, 53 deselected in 511.75s (0:08:31)
Total:   3658 lines
Missing: 19 lines
Coverage: 99%
```

Python gate ran from the worktree with locked arxiv-venv-lock Python,
`ANTHROPIC_API_KEY=local-preview-disabled`, runtime POSTGRES_URL/rate override
unset, and isolated `WORKSPACE_TEST_POSTGRES_URL` on controller PG15458. All
floors and test tiers remain unchanged. Python skips/deselections are explicitly
reported above; no paid or live-model test is claimed.

Production budget output (CSS exception **permitted by owner E27 through these
phases**, pending G7; no budget file/ceiling/floor changed):

```text
PASS      `/` first-load JS, excl. polyfill — 166,259 B (162.4 KiB) against 166,912 B (163.0 KiB)
PASS      `/c/[id]` first-load JS, excl. polyfill — 192,154 B (187.7 KiB) against 192,512 B (188.0 KiB)
PASS      `/learn` first-load JS, excl. polyfill — 164,971 B (161.1 KiB) against 166,912 B (163.0 KiB)
PASS      `/learn/paths/[id]` first-load JS, excl. polyfill — 165,890 B (162.0 KiB) against 169,984 B (166.0 KiB)
PASS      `/learn/sessions/[id]` first-load JS, excl. polyfill — 186,642 B (182.3 KiB) against 188,416 B (184.0 KiB)
PASS      `/learn/progress` first-load JS, excl. polyfill — 168,296 B (164.4 KiB) against 169,984 B (166.0 KiB)
PASS      Shared framework/runtime chunk — 134,108 B (131.0 KiB) against 139,264 B (136.0 KiB)
BREACH    All emitted CSS — 22,808 B (22.3 KiB) against 17,408 B (17.0 KiB)
PASS      All self-hosted font files (woff2, latin subset) — 103,476 B (101.1 KiB) against 109,568 B (107.0 KiB)
PASS      `/today` first-load JS, excl. polyfill — 153,611 B (150.0 KiB) against 163,840 B (160.0 KiB)
PASS      `/interests` first-load JS, excl. polyfill — 153,065 B (149.5 KiB) against 163,840 B (160.0 KiB)
PASS      `/library` first-load JS, excl. polyfill — 152,583 B (149.0 KiB) against 163,840 B (160.0 KiB)
PASS      `/library/items/[id]` first-load JS, excl. polyfill — 156,292 B (152.6 KiB) against 163,840 B (160.0 KiB)
PASS      `/workspace/today` first-load JS, excl. polyfill — 167,531 B (163.6 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/radar` first-load JS, excl. polyfill — 161,423 B (157.6 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/interests` first-load JS, excl. polyfill — 168,537 B (164.6 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/library` first-load JS, excl. polyfill — 163,756 B (159.9 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/items/[id]` first-load JS, excl. polyfill — 167,716 B (163.8 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/operations` first-load JS, excl. polyfill — 159,526 B (155.8 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/review` first-load JS, excl. polyfill — 160,706 B (156.9 KiB) against 169,984 B (166.0 KiB)
```

The first Reader build exceeded its JS ceiling by443B. Loading the labelled
synthetic workbench only after Understand opens, then retaining its mounted
state, resolves this without raising the ceiling. CSS consolidation remains G7.
The standard budget command still exits nonzero for the recorded CSS row;
that exception is disclosed, not called an entirely green budget gate.

### Browser and evidence

[Walkthrough and all captures](evidence/after/p4-reader/WALKTHROUGH.md).
Preview **http://localhost:3148/workspace/today** stays running with explicit
synthetic notice on all captures. Rich9-paper previews are read-only; write
verification uses fresh controller-p4 DB/principal, never owner data.

- Existing real-API live regression:16/16, desktop/mobile, unchanged assertions.
- New guarded walkthrough:12/12, two synthetic questions saved,503 draft/reload
  recovery and actual409 local/server separation, exact version2 Unicode anchor
  `abstract:181:186`, six Tabs to notes.13 bounded mutation requests recorded.
- Verification API restart:2/2 entries preserve all compared fields including
  text, revision, work/version and anchor. This is Postgres persistence evidence.
- Today density rerun after Reader:30/30 title/actual abstract-line geometry
  cases. Layout-only overrides remain labelled; no source claims inferred.
- Rich preview:4/4 themes/viewports,12 screenshots (Today/Reader/notes).
- Note textarea/Save clearance:4/4 themes/viewports.
- Reader axe:12/12 panels×themes×viewports, zero violations.
- Final browser audits:zero unexpected console/page/request failures or blocked
  external/provider/source requests. Four expected503/409 console events are
  retained in the write receipt. No physical phone test is claimed.

The initial walkthrough harness assumed Source was still selected after mobile
reading resumed notes; it now explicitly opens Source. It also waits for the
reading mutation to finish before testing form Tab order. An axe script initially
used same-document hash navigation rather than a fresh panel mount; corrected
the audit harness and reran. No product-truth assertion was weakened. Initial
focused test failures from duplicate Source-context wording and draft navigation
were resolved by a unique Retained-version-details label and the stronger
explicit-discard test described above. The intentionally failing draft-race
probe is historical reproduction evidence, not an unresolved final test.

### Scope and non-claims

G4 is complete for owner review. P5/P6 and broader final G7 matrix are not started
in this batch. Source/evidence boundaries remain; generated analysis, checker
qualification and personal usefulness are not established by synthetic data.
No provider contacts/spend, real-key request/configuration/test or automatic
qualification start; recurrence disabled. Owner3137/API8137/PG15438, data and
preferences unchanged. All PRs unmerged; no new controller PR.

GitHub CI does not run on this branch-only push (workflow is main-push/PR; owner
asked for no PR). These are exact-source local results, not green GitHub CI.
Final docs/evidence commit contains no source changes after these checks.

Independent adversarial review caught two additional confirmed gaps before the
final push: saved-context/other-version/Shell links bypassed the unavailable-
recovery guard, and reopening the same saved entry during its pending save
could replace the edited draft. Both are fixed with focused regression tests.
Capture-phase protection now covers same-tab anchor activation while unsafe or
busy, retaining fragment tabs, modified/new-tab links and downloads. Reopening
saved entries is disabled during entry saves. An unavailable-recovery draft also
triggers a document-unload warning. This does **not** establish interception of
Next client-side browser Back/Forward: if browser storage is unavailable, keep
the tab open and save or copy text before history navigation. Normal recoverable
draft history/return flows remain verified. No broader guarantee is claimed.

The first final frontend coverage rerun was launched inside the restricted
sandbox: seven unchanged healthcheck tests could not bind their ephemeral
127.0.0.1 servers (`listen EPERM`), then timed out. The full suite was rerun
with localhost socket permission; no tests, timeout or assertions were changed.
That failed attempt remains in the verification log; its result is not green.

Final reruns after adversarial-review fixes: all3882 frontend tests pass and all
unchanged coverage floors pass. The first unrestricted rerun passed every test
but statement coverage was98.03%, below98.15%; additional lifecycle/allowed-path
regressions close the gap. No coverage input or floor was changed. Test checkpoint
a933a71 adds tests only after application source5fdbf48; the final evidence commit
adds documentation/captures only.

The first final preview capture attempt failed with static-asset404s because the
preview server started before standalone static files finished copying. After
copy completed, only the isolated3148 server was restarted; the final four-case
capture audit and30-case density pass show zero browser errors. This was local
startup sequencing, not a product assertion changed to make a test pass.

Final live16 uses a fresh `workspace_controller_p4_final_live` database with the
production-wording flagfalse solely to retain its existing exact copy assertion.
The separate fresh `workspace_controller_p4_final_walk` run uses the synthetic
flagtrue, labelled captures and controller-p4 principal; the main3148 rich preview
also stays explicitly synthetic. Both keep the sentinel and disabled recurrence.

The first final live rerun passed but its stdout was not retained. A single
fresh-database rerun closed that artifact gap without changing tests; exact
[raw output](evidence/after/p4-reader/live-e2e.txt) is committed. The verification
stack was restored to the labelled final_walk database afterward, preserving
its two synthetic questions. No further retry or test broadening was performed.


## G5 — Radar and Library connected controller

Application **`ade234b48520782d32e388e16a3cb811f8a2cf2b`**, Radar WO-5.1 **`734773f`**; baseline **`2c06bde`**.
Initial checkout was clean and fetch found no newer controller commits. Main
remains88d283d. The checked application bytes were frozen before gates and are
identical to the committed source ([manifest](evidence/after/p5-discovery-return/application-tree.json)).
The following evidence commit changes docs/captures only.

Radar now presents one full available abstract and evidence scope, with filters
and the ordered result page in the sidebar/drawer. Focus uses replace-history
URL state independently of fetches. Server `as_of`, cursor, filters and focus
survive exact Reader return; filter/page changes reset focus. Next page is one
unique explicit control in the bar at page end. No stale card is presented as
a successful new search. Retry now starts a fresh request; a work added between
workspace and items snapshots gets a visible reading-state update and Undo.
Composer follows `q`, retains other filters for new queries and resets paging.

Library has the native five-view select and queue in the sidebar, one focused
source, exact-version notes, quick add and explicit import. Notes view retains
all entries in that view, focused work first, including unread sources. Reader
returns stay exactly `?view=...` (E07); selection is separately remembered per
principal/view, while explicit queue focus also lives in its URL. Missing
versions show unavailable rather than newer source content.

**Action location:** all Library Save/Unsave/Dismiss/Snooze/Undo controls live
only in the bar; no duplicate card controls. Export lives only in the Shell
footer. Import loads on explicit disclosure open, remains mounted when closed,
and never previews/applies automatically. Its requests, digest/conflict rules,
original retention and opt-in profile transfer remain unchanged. Reading,
manual save and import operations are mutually guarded against stale reload
races. P4 pending-save protections and readable type sizes are preserved.

### Exact local results

`npm run lint`, final `npm run typecheck`, direct touched-test/live-spec ESLint,
full coverage, production build and every JS budget row pass. Functions floor
raised91.8→92.2; statements98.15, branches94.0 and lines99.11 remain unchanged.
No input, exclusion, tier or budget was weakened. Actual pasted output:

```text
 Test Files  193 passed (193)
      Tests  3919 passed (3919)
Statements   : 98.18% ( 4924/5015 )
Branches     : 94.45% ( 3983/4217 )
Functions    : 92.66% ( 1706/1841 )
Lines        : 99.37% ( 4111/4137 )
  16 passed (21.6s)
6042 passed, 54 skipped, 53 deselected in 555.61s (0:09:15)
Total:   3658 lines
Missing: 19 lines
Coverage: 99%
```

`make test-cov-diff` ran from the worktree with locked arxiv-venv-lock Python,
disabled sentinel and isolated `WORKSPACE_TEST_POSTGRES_URL` on15458, with
runtime POSTGRES_URL/rate overrides unset. Skips/deselections are explicit;
no model or provider acceptance is implied. The final coupled README/config
count record also passes all three documented-claim tests after matching the
last measured3919-test/193-file run. No backend runtime code changed.

Production build/budget output:

```text
PASS      `/` first-load JS, excl. polyfill — 166,277 B (162.4 KiB) against 166,912 B (163.0 KiB)
PASS      `/c/[id]` first-load JS, excl. polyfill — 192,172 B (187.7 KiB) against 192,512 B (188.0 KiB)
PASS      `/learn` first-load JS, excl. polyfill — 164,989 B (161.1 KiB) against 166,912 B (163.0 KiB)
PASS      `/learn/paths/[id]` first-load JS, excl. polyfill — 165,908 B (162.0 KiB) against 169,984 B (166.0 KiB)
PASS      `/learn/sessions/[id]` first-load JS, excl. polyfill — 186,660 B (182.3 KiB) against 188,416 B (184.0 KiB)
PASS      `/learn/progress` first-load JS, excl. polyfill — 168,314 B (164.4 KiB) against 169,984 B (166.0 KiB)
PASS      Shared framework/runtime chunk — 134,126 B (131.0 KiB) against 139,264 B (136.0 KiB)
BREACH    All emitted CSS — 23,216 B (22.7 KiB) against 17,408 B (17.0 KiB)
PASS      All self-hosted font files (woff2, latin subset) — 103,476 B (101.1 KiB) against 109,568 B (107.0 KiB)
PASS      `/today` first-load JS, excl. polyfill — 153,629 B (150.0 KiB) against 163,840 B (160.0 KiB)
PASS      `/interests` first-load JS, excl. polyfill — 153,083 B (149.5 KiB) against 163,840 B (160.0 KiB)
PASS      `/library` first-load JS, excl. polyfill — 152,601 B (149.0 KiB) against 163,840 B (160.0 KiB)
PASS      `/library/items/[id]` first-load JS, excl. polyfill — 156,310 B (152.6 KiB) against 163,840 B (160.0 KiB)
PASS      `/workspace/today` first-load JS, excl. polyfill — 168,926 B (165.0 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/radar` first-load JS, excl. polyfill — 167,699 B (163.8 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/interests` first-load JS, excl. polyfill — 168,875 B (164.9 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/library` first-load JS, excl. polyfill — 167,771 B (163.8 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/items/[id]` first-load JS, excl. polyfill — 168,053 B (164.1 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/operations` first-load JS, excl. polyfill — 159,861 B (156.1 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/review` first-load JS, excl. polyfill — 161,039 B (157.3 KiB) against 169,984 B (166.0 KiB)
```

The sole nonzero budget row is emitted CSS, the owner-permitted E27 interim
exception through G6; G7 consolidation/legacy stylesheet removal remains due.
No ratchet changed JS ceilings. Library initially exceeded169984 by188B;
explicitly deferring import until needed reduced it below the unchanged bound.

### Browser acceptance and captures

[Runnable desktop/mobile walkthrough and gallery](evidence/after/p5-discovery-return/WALKTHROUGH.md)
· preview http://localhost:3148/workspace/radar?q=agent&days=0.

- Read-only preview39/39:1440/390/768/1024 × themes, including actual20+9
  pagination, full focused title clearance, drawer reachability and closure,
  composer/filter behavior, empty views and native controls.
- Final real-API live regression16/16 on fresh CI data; exact raw output retained.
- Guarded core walkthrough11/11: actual20+6 paging/cutoff/focus, Reader return,
  history/reload, Notes on two works, exact older v1 passage, unavailable→retry,
  successful empty search and failed-write→retry→Undo.
- Guarded tools5/5: expected422 retains input/no work; valid manual metadata
  save repeated without duplicate; explicit preview/import repeated without
  duplicate note/profile change; original retained; actual Markdown download.
- P5 axe12 cases, zero violations of any severity, including open mobile
  drawer and expanded import. P4 Reader axe12 cases also zero violations.
- Mobile lower-content reachability4/4: final abstract line, full evidence
  block and last Resume link can be scrolled clear of the fixed bar; actual
  hit testing confirms the note link is not covered.
- Preserved Today density30/30 on the populated-question fixture, unchanged
  full-title and first-two-actual-lines assertion and8px clearance. Clearly
  labelled GET-only long-title/short-abstract variants remain layout evidence.
- Final browser receipts record zero unexpected console/page/request errors,
  external/provider/refresh attempts or denied writes. Expected503 injections
  and reserved-host422 are retained rather than hidden.

Ten primary previews plus eight guarded walkthrough screenshots are linked.
They are DPR2 browser emulation, not physical-device qualification. Lower
abstract/notes content does not all fit at once: explicit scroll reachability
is verified, not a claim that the entire page is visible initially.

### Corrections and unsuccessful attempts retained

Applied E01/E03/E06/E07/E15/E19/E22/E27/E30/E46: responsive sidebar access,
sole export/page control, all Notes-view entries, exact Library return with
scoped selection restoration, no focus refetch and interim CSS reporting.
One justified E19 placement choice moves the **single** Next page control into
the bar, where it is explicit at390px; there is no sidebar duplicate.

Existing test edits and reasons are in each source commit body: experience
opens the import disclosure/selects a queue row before its former multi-card
assertion; Shell export assertion follows its sole footer location; retained
adds legacy card action coverage; API returns now retain bounded Radar page
state; live.spec only opens/closes moved sidebar controls. All original private
save, body, conflict, source/version, provenance and recovery assertions remain.

The initial full frontend suite passed3904 tests but missed coverage floors;
meaningful interaction/SSR/privacy cases close the gap. A later documented-
claims failure caught the stale177-file record beyond its15-file band; refresh
uses actual counts and raises the functions floor, not the lag band. Its first
restricted focused run passed but printed a sandbox psutil cleanup warning;
the final focused and full gates ran with required process/socket access.

The richer preview exposed six long-title Today density failures because its
saved-question body adds a line to the continuation strip. Recovering12px only
from noninteractive header/intro margins resolves all30 cases without reducing
fonts, hiding disclosures or changing the8px assertion. Pre-repair JSON is kept.

Initial preview audit35/39 used a wrong visible-role assumption for a closed
mobile/tablet drawer; the corrected audit asserts DOM uniqueness and explicitly
opens controls. Initial tools `.invalid` URL was rejected by existing safety
validation before any write; valid example.com metadata then exercised the
intended path. The initial seed import-path failure occurred before writes;
corrected verifiers use locked Python stdin and prove worktree src resolution.
An unrun tablet-script draft is excluded from acceptance and the commit.

### Boundaries and unresolved follow-up

Main3148 now uses a fresh clearly labelled38-work synthetic P5 preview account,
with the same nine-item Today edition and two seeded verification questions.
Old P4 workspace_rich remains preserved. Actual browser writes use separate
controller-p5 databases: final live starts3 works/4 versions; core walk starts27
and ends with two CI questions; tools then ends29 works/three synthetic questions.
No owner notes, preferences or usefulness labels were copied or invented.
Owner3137/API8137/PG15438 and all PRs remain untouched/unmerged.

The **browser-storage / client-side Back-Forward reliability limitation is
unresolved**. Save/copy text if recovery is unavailable; same-tab/unload guards
are not a guarantee over every Next history transition. Library return focus
also falls back if its session store is unavailable; explicit focus URLs work.

Provider contacts/spend zero; recurrence disabled; no real-key setup, no
qualification execution, no new runtime dependencies, no PR and no merge.
GitHub CI is not triggered by this branch-only push; verified results here are
local and tied to the application commit, not a green remote CI claim.
Stop at G5 for owner experience review. P6 is not started; broader G7/G8 visual
and browser matrices, CSS consolidation and paid quality evidence remain later.


## G6: supporting workflows and owner-authorized paper navigation

### Source and gate attribution

This checkpoint validates application commit `fda9d7616e8cbd0d882bcc41510a997ade117bf9`
on `claude/youthful-dirac-69v19d`, built on the G5 application rebased onto
`origin/main` at `17f9221`; the incoming main change is README-only. Four bounded
commits cover navigation/paper refinement, Interests, Operations and Review.
The application source froze after the Reader queue split and successful
production build; all 601 frozen web-file hashes remain unchanged through the
source commits. [Source binding](evidence/after/p6-supporting-workflow/source-binding.json)
records the exact application commit, web tree, build identity and file manifest.
No PR or merge is part of this phase. The earlier G5 stop is historical; the
owner subsequently authorized P6 and the paper/navigation refinement here.

### Delivered behavior and preserved contracts

Interests has a sidebar section index, grouped native form, Save/Discard in the
bar through the original form association, and a separately loaded topic
catalogue. Account-specific browser draft recovery retains raw multiline text,
base revision and retry identity. Opening the editor does not save preferences.
Failed/conflicting writes and mismatched acknowledged/reloaded revisions retain
the local draft for review. Unreadable recovery originals are preserved; when
storage is unavailable, the page warns and guards ordinary link/unload exits.

Sources & checks has an ordered queue with explicit status words and one focused
source receipt. Native schedule controls and the always-visible form-associated
save action retain the original request contract and force `enabled: false`.
Unknown focus falls back without a write; selecting sources does not refetch.
Synthetic-preview source-check buttons are disabled. Unit fixtures exercise the
explicit single-source/all-source refresh bodies without external contacts.

Review keeps every candidate form mounted in packet order under E05. The queue,
Previous/Next and keys 1/2/3 select the current candidate; number keys choose a
native radio without saving. Only the explicit Save judgment action submits a
label. Packet switches/preparation, leaving through ordinary links and pending
writes are guarded; explicit discard is required before replacing dirty forms.
Failures/conflicts retain drafts, revision and retry identity. No usefulness
judgments are inferred or automatically seeded into the preview account.

Today, Radar and Library use a neutral focused-paper surface. Shared navigation
settles the paper/route content at the requested inset using the actual desktop
main scroll container or mobile window, then applies a content-only transition.
The player and shell stay fixed. Reduced motion skips animation. Short documents
reserve only missing scroll extent in an aria-hidden tail. Route-ready history
restoration preserves Next history metadata and recorded positions; Reader entry
and exact passage targets retain priority. Deferred-runtime capture checkpoints
the outgoing source synchronously and cannot replay that position into a newer
destination. Native event cleanup occurs after dispatch rather than in a
microtask, preserving allowed Next link events and draft guard prevention.

Reader uses lazy Review-only neighbour lookup and a lazy sidebar queue to keep
the existing JS ceiling. Original source/version identities, API bodies, exact
saved-entry/passage anchoring, notes and native controls remain covered by the
existing suites. No runtime dependencies were added.

### Local mechanical verification

All app test/build commands use `ANTHROPIC_API_KEY=local-preview-disabled`,
`USE_MOCK_DATA=true` and disabled recurrence. Full Vitest runs separately from
Next production builds. Socket/process access was granted only for the existing
offline loopback test harness and isolated preview operations.

- `npm run lint`: exit0, zero warnings.
- `npm run typecheck`: exit0.
- `npm test -- --coverage`: exit0; unchanged global floors all pass.
- `npm run build`: exit0, production build; then
  `node scripts/route-budgets.mjs`: exit1 solely for the E27 CSS exception.
- Locked Python first proved `src.__file__` resolves to this exact worktree;
  `python -m pytest tests/test_documented_claims.py tests/test_repo_hygiene.py -q`:
  exit0. Python application source is unchanged in this phase. This refresh
  supplements the earlier full Python patch-coverage run; it does not invent a
  new full-suite result.
- `git diff --check`: exit0.

Command transcripts (trailing whitespace/progress-control formatting normalized
for version control): [frontend coverage](evidence/after/p6-supporting-workflow/gate-frontend-coverage.txt),
[lint](evidence/after/p6-supporting-workflow/gate-lint.txt),
[typecheck](evidence/after/p6-supporting-workflow/gate-typecheck.txt),
[production build](evidence/after/p6-supporting-workflow/gate-production-build.txt),
[budgets](evidence/after/p6-supporting-workflow/gate-budgets.txt),
[Python claims/hygiene](evidence/after/p6-supporting-workflow/gate-python-claims-hygiene.txt).

Actual frontend output:

```text
 Test Files  199 passed (199)
      Tests  4034 passed (4034)
   Duration  69.68s (transform 14.13s, setup 60.66s, import 19.68s, tests 213.17s, environment 126.29s)

=============================== Coverage summary ===============================
Statements   : 98.15% ( 5425/5527 )
Branches     : 94.39% ( 4496/4763 )
Functions    : 93.07% ( 1800/1934 )
Lines        : 99.42% ( 4469/4495 )
================================================================================
```

Actual fresh Python output:

```text
..................................................................       [100%]
66 passed in 11.95s
```

Production budget output, pasted from the final built tree:

```text
PASS      `/` first-load JS, excl. polyfill — 166,356 B (162.5 KiB) against 166,912 B (163.0 KiB)
PASS      `/c/[id]` first-load JS, excl. polyfill — 192,251 B (187.7 KiB) against 192,512 B (188.0 KiB)
PASS      `/learn` first-load JS, excl. polyfill — 165,068 B (161.2 KiB) against 166,912 B (163.0 KiB)
PASS      `/learn/paths/[id]` first-load JS, excl. polyfill — 165,987 B (162.1 KiB) against 169,984 B (166.0 KiB)
PASS      `/learn/sessions/[id]` first-load JS, excl. polyfill — 186,739 B (182.4 KiB) against 188,416 B (184.0 KiB)
PASS      `/learn/progress` first-load JS, excl. polyfill — 168,393 B (164.4 KiB) against 169,984 B (166.0 KiB)
PASS      Shared framework/runtime chunk — 134,205 B (131.1 KiB) against 139,264 B (136.0 KiB)
BREACH    All emitted CSS — 23,797 B (23.2 KiB) against 17,408 B (17.0 KiB)
PASS      All self-hosted font files (woff2, latin subset) — 103,476 B (101.1 KiB) against 109,568 B (107.0 KiB)
EXTERNAL  Total transferred JS on a settled report route, incl. lazy chunks — not measured here against 245,760 B (240.0 KiB)
REPORTED  Derived: total first-load transfer for `/c/[id]`, cold cache — 319,524 B (312.0 KiB) against 319,488 B (312.0 KiB)
PASS      `/today` first-load JS, excl. polyfill — 153,708 B (150.1 KiB) against 163,840 B (160.0 KiB)
PASS      `/interests` first-load JS, excl. polyfill — 153,162 B (149.6 KiB) against 163,840 B (160.0 KiB)
PASS      `/library` first-load JS, excl. polyfill — 152,680 B (149.1 KiB) against 163,840 B (160.0 KiB)
PASS      `/library/items/[id]` first-load JS, excl. polyfill — 156,389 B (152.7 KiB) against 163,840 B (160.0 KiB)
PASS      `/workspace/today` first-load JS, excl. polyfill — 166,750 B (162.8 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/radar` first-load JS, excl. polyfill — 166,041 B (162.1 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/interests` first-load JS, excl. polyfill — 167,446 B (163.5 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/library` first-load JS, excl. polyfill — 166,095 B (162.2 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/items/[id]` first-load JS, excl. polyfill — 169,925 B (165.9 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/operations` first-load JS, excl. polyfill — 164,490 B (160.6 KiB) against 169,984 B (166.0 KiB)
PASS      `/workspace/review` first-load JS, excl. polyfill — 166,818 B (162.9 KiB) against 169,984 B (166.0 KiB)
```

Every enforced JavaScript row passes. Reader has only 59B of headroom at this
checkpoint, so G7 changes require another build/budget measurement. Emitted CSS
is the sole failed enforced row under E27's explicit interim allowance through
G6; no ceiling, floor, include/exclude list, budget script or assertion was
weakened. G7 still must consolidate/remove the legacy workspace stylesheet and
make every enforced row green, using the kit's single ratchet only if needed.
The `REPORTED` transfer estimate is informational, as in the unchanged script.

### Browser evidence and remaining scope

The final production assets were copied to standalone and only the verified
isolated preview on3148 restarted. Its API8148/database
`workspace_controller_p6_preview` and principal `controller-p6-preview` remain
separate from the browser agent's3149/API8149 verification stack. Owner
3137/API8137/PG15438 remain untouched. No full process environment was inspected.

Final source-frozen browser acceptance is recorded in the
[P6 walkthrough and gallery](evidence/after/p6-supporting-workflow/README.md):

- Real loopback API/Postgres live regression: **16 passed (20.8s)** on fresh
  synthetic verification fixtures.
- Supporting workflow **10/10**: failed-save recovery, real409 conflict with
  draft retained, disabled-schedule save, Review drafts and explicit judgment,
  exact packet return and lazy Reader queue/version links.
- Read-only **28 cases plus2 tablet cases**: zero axe violations of any severity;
  all ten preview labels stay blank. Source-check UI **2/2** forwards zero
  refresh requests; native focus/announcement **2/2** and reduced motion **4/4** pass.
- Matched before/after **12/12 each**, actual themes and same synthetic
  work/version. Before captures use a separately reconstructed immutable G5
  `ade234b` build, never the controller build.
- Two actual decoded/reviewed WebM recordings: desktop11.60s/mobile10.68s,
  with exact retainedv1 20-character far passage visible at9.0s above the player.
  Final recording metrics retain approximately16px insets, rapid7/14ms input,
  restored Back positions870/1354px and four reversible saved-state-restored
  reading writes. Real loading frames remain.

Four expected503/409 messages are retained; unexpected console/page/request
failures are zero in final workflow acceptance. Earlier failed scripts/captures
remain under `pre-fix/`, excluded from acceptance. Theme-context and hidden-queue
harness corrections preserved the actual requirements. Verification ports
3149/8149 and temporary3150 are closed;3150's temporary G5 tree was removed.
Preview3148/API8148 remain running. The teardown receipt verifies owner
3137/API8137/PG15438 still running and untouched.

These are Chromium viewport checks with synthetic fixtures, not physical-device,
real source freshness, personal usefulness or paid model-quality evidence. The
separately authorized paid qualification is owned outside this frontend task.
GitHub CI is not triggered by the branch-only workflow; these are exact-source
local gates, with no green remote-CI claim.

The browser/client Back-Forward **unsaved-draft reliability limitation remains**.
Scroll/list restoration fixes do not guarantee form recovery over every Next
history transition. Save/copy draft text if recovery is unavailable. Interest
recovery is account-specific; it does not imply durable Review or schedule draft
history. G7 all-route/theme/width accessibility and responsive acceptance,
stylesheet consolidation and final G8 verification are not claimed here.

Applied P6 corrections include E01/E04/E05/E16/E18/E27/E50/E53: moved controls stay
reachable through the mobile drawer helper, form submits retain explicit native
association, all Review forms remain mounted, recurring schedule stays disabled,
receipt classes and refresh bodies are preserved, and CSS overrun is disclosed.
The only additional live-spec change opens the moved Review controls before the
existing packet-preparation assertion; existing product-truth assertions remain.
The existing topic-search unit assertion now awaits the lazy catalogue rather
than requiring synchronous mount; its label and interaction assertions remain.

Provider contacts/spend for this frontend task remain zero; recurrence remains
disabled. No owner data, credentials, qualification checkout, PR or merge was
accessed. Stop before full P7.
