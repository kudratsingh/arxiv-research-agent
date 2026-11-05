# P7 final browser verification

**G7 local runtime verification passes on application commit
`6b2eccf069537d90423359fc74c033f27e665cd6`.** The final production build is
`5OYFfRwG4lvr66GcP9lc0`; tracked web tree
`e4f4f72d1b49f1647fb116e52105c90b03c0335c`. All final gates below were rerun on
that frozen application, including motion, forms, targets and legacy comparisons.
See the [source binding](final/source-binding.json),
[standalone static asset hashes](final/static-asset-manifest.json), and
[machine summary](summary.json). The independent browser owner changed no
application source. Mechanical build/test/budget evidence is separately owned in
[checks/](checks/README.md).

The running review surface is
[synthetic P7 preview](http://127.0.0.1:3168/workspace/today), with the actual
`Design preview · synthetic sample papers` label. Its source fixture includes
39 works/40 versions and a retained 4,059-character synthetic abstract. This is
mechanical UI evidence, not owner usefulness, generated understanding, scientific
quality, new source freshness, or five days of personal use. Run timestamps are
actual UTC times; the fixture's edition/source dates are not new observations.

## Final results

| Gate | Final result | Evidence |
| --- | --- | --- |
| Seven workspace routes × both themes × five widths | 70/70; 28 primary axe scans, zero violations; 42 tablet geometry cases; 28 DPR2 primary PNGs | [matrix](final/report.json) |
| CSP and responsive containment | All 70 nonce policies/no unsafe-eval; zero violations, runtime errors, external or mutation requests; desktop document overflow zero | [matrix](final/report.json) |
| Commands, help and drawer | 4/4 contexts; eight dialog axe scans zero; strict Tab/ShiftTab wrap, active option visibility, return focus, shortcuts/parser order, stale context, no modal background action | [commands](final/commands/report.json) |
| Drawer composition/modifiers | 390px and 900px; composing Escape and Ctrl+Shift+Tab preserved; ordinary Escape still closes/restores focus | [drawer](final/drawer-ime-modifier/report.json) |
| Busy, empty and outage moods | 8/8 normal/reduced contexts; captured software-only outages; normal article170ms, reduced article/mascot/equalizer motion zero | [moods](final/moods-motion/report.json) |
| Native queue/Reader flow and full lower content | 4/4; rapid J/J/K, real Radar page2, immediate870px Read, Back870/Forward, same-document far hash/Back/Forward, exact20Unicode characters,16px inset; both top and bottom of last target in usable viewport, hit-test, paint frames and actual decoded video | [geometry](final/geometry/report.json) |
| Cold exact Reader passage | 4/4; exact retained version/quote, ready source+mark, settled JS including mandatory async code | [Reader observations](final/reader-readiness/report.json) |
| Fresh Today/Radar/Library content | 12/12; exact title/abstract and DOM/visible readiness; full settled JS/waterfalls | [paper observations](final/paper-readiness/report.json) |
| Mandatory Reader code held | 2/2; truthful busy state, change hash while held, release actual chunk, latest exact passage lands | [held chunk](final/delayed-reader-core/report.json) |
| Reader code failure/retry | 2/2; deliberate one-request abort, visible error and explicit code-only retry, same version/latest hash, one state read, no writes | [failure/retry](final/reader-chunk-failure/report.json) |
| Reader missing item/outage | 4/4; truthful terminal heading, no editor chunk fetched | [no-data](final/reader-module-no-data/report.json) |
| Reader stale code response | 2/2; navigate away while code held, no ghost Reader; next exact work/version renders with cached code | [stale navigation](final/reader-stale-module/report.json) |
| Fictional Today and Evidence Workbench | 8 direct +8 actual client-route cases; all16 exact pixel/computed-state/axe equality to unchanged P6 | [legacy comparison](final/legacy-comparison.json), [direct](final/legacy/report.json), [client route](final/legacy-via-workspace/report.json) |
| Keyboard form foundations | 4/4; actual focus-visible2px outline+4px offset; computed form styles equal baseline | [forms](final/form-focus/report.json), [comparison](final/form-focus/baseline-comparison.json) |
| Coarse-pointer targets | 14/14 route/theme measurements; visible buttons/navigation controls ≥44px; inline prose links excluded; small[] | [targets](final/touch-targets/report.json) |
| Existing live regressions | Unchanged16/16 pass,23.5s; disposable canonical CI only | [raw results](ci/live16/results.json), [command log](ci/live16/command.log) |
| Pending-save ordinary/slash search | 4/4 Reader/Interests desktop+390; working sessionStorage; actual held POST; no URL/history/timeOrigin/unload/intent change, latest draft retained,390 help/Close focus and nativewheel reachability; real success then both search types work | [pending saves](ci/pending-composer-search/report.json) |
| Dirty Review search guard | 2/2; ordinary/slash blocked, latest radio/reason retained, explicit discard; no feedback POST; durable judgments all blank and protected state byte-identical | [dirty Review](ci/dirty-review-composer-search/report.json) |
| Keyboard daily loop | 2/2; Skip main→J→O→Notes→save→palette refusal→intercepted409→keyboard retry→Today→J; logical reading restored | [daily loop](ci/daily-loop/report.json) |
| Source→Notes→Source | 4/4; actual UI tabs and8 own-CI reading writes; logical fields restored, notes/profile/sources/schedule unchanged; no additional script bytes after Notes | [stage observations](ci/p7-source-notes/report.json) |
| Preview state and judgments | All readonly captures preserve state; ten labels and reasons remain blank | [matrix label checks](final/report.json) |

The fictional `/today` page retains the same moderate axe `region` finding for two
preview-banner text nodes as P6. Workbench, workspace routes and dialogs have zero
axe violations. There are no serious/critical legacy findings.

## Review the actual preview recordings

These four WebMs were recorded on the synthetic-labelled preview3168 and bound
to the final application. Their cold loading frames remain present. They are
short automated mechanical sequences, not a human-paced usability study.

- Commands: [desktop dark](final/commands/desktop-dark.webm), [mobile light](final/commands/mobile-light.webm).
- Queue/Reader/last-content flow: [desktop dark](final/geometry/desktop-dark.webm), [mobile light](final/geometry/mobile-light.webm).
- Today: [desktop light](final/desktop-light-today.png), [desktop dark](final/desktop-dark-today.png), [mobile light](final/mobile-light-today.png), [mobile dark](final/mobile-dark-today.png).

Two additional [desktop](ci/daily-loop/desktop.webm) and
[mobile](ci/daily-loop/mobile.webm) clips show the disposable CI keyboard/conflict
flow. They use the production application with canonical synthetic CI fixtures;
they are **not a real-source owner preview**.

All six WebMs fully decode with exit0. All six decoded contact sheets were
visually reviewed, along with eight actual native critical geometry frames.
The [inspection report](final/video-inspection/report.json) records hashes,
durations and review scope. [Critical native frames](final/video-inspection/critical-native-frames.json)
match the real source/Notes states to their PNG counterparts; the RGB distance
is a matching aid, not an equality claim. Lower source text, full footer and
Notes last line visibly paint above the player. Desktop brand/sidebar remain
in view with document scroll0. The one-fps contact-sheet labels are nominal
sampling labels; native frame indices are retained for precise identification.

## Initial budget versus actual later code

The official initial JS metric and all ceilings are unchanged; source-owned
[mechanical receipts](checks/README.md) report4079 tests/201 files and all20 budget
rows passing. CSS is23,940B under25,600B. ROOT chose reuse of the byte-identical
`daily.css`/daily-app foundations within the owner-authorized legacy-preservation
and CSS-cap scope; this is the recorded E58 implementation deviation, not a new
literal owner ruling.

Reader's mandatory retained-content module still arrives after item data. Busy,
error, code-only retry, stale responses and latest-hash readiness were verified
in the real browser. FocusPaper is eager; the obsolete delayed-FocusPaper-chunk
case is retired rather than called a pass.

Final cold Reader settled JS response-body bytes are230,347 desktop and178,289
mobile, **4,402/4,409B more than P6**. The final exact source and mark appeared in
192–221ms in these individual loopback observations; code-busy phases were about
11–13ms. These are uncontrolled single observations, not a speed benchmark or
a total-transfer reduction. [Raw waterfalls](final/reader-readiness/report.json),
[paper stages](final/paper-readiness/report.json) and
[Source/Notes stages](ci/p7-source-notes/report.json) retain every request and
ready timestamp. All settled totals include the later mandatory code.

## Isolation and cleanup

All custom browser harnesses block external requests, source refresh, provider
and unauthorized mutation endpoints. Writes are confined to the separately
created `controller-p7-ci` principal/database on3169/API8169. Reader positions
and profile data were restored logically after those cases; revisions naturally
advance. The unchanged live16 suite includes two explicit **local synthetic $0**
workflow cases; they are not real model generation. Provider calls and source
refresh forwarding remain zero, sentinel configuration is
`local-preview-disabled`, and recurrence remains false.

[Teardown](ci/teardown.json) verified and stopped only Node82833/API10951, checked
the exact unique database ownership comment and zero remaining connections, and
dropped only `workspace_controller_p7_ci`. Preview3168/API8168 remains running.
Owner3137/8137/PG15438, original3148/8148, pilot3158/8158 and sharedPG15458 listener
identities are byte-identical before/after cleanup. No owner or preview writes
were made. [Final own-CI snapshot](ci/final-owned-state.json) is synthetic evidence.

## Preserved failures and reproducibility

Earlier source snapshots and failed/partial captures remain under [pre-fix/](pre-fix/).
The preserved `pre-fix/readme-before-final.md` retains original bytes; its relative
links resolve from the original `p7-polish/` root, not its archival directory.
The original83b final receipts, recordings and CI results are preserved under
[pre-guard-repair-83b](pre-fix/pre-guard-repair-83b/browser-path-mapping.json), with
original source/path identities. Every gate in the final table was rerun on6b;
no older run is silently relabelled.

The original P6 far-hash gap is separately diagnosed in
[review/inherited-hash-gap](review/inherited-hash-gap/README.md). Other preserved
findings include strict native dialog focus escape, hidden-theme containing-block
overflow, artificial core reveal latency, and the extreme1e6-wheel blank attempts.
The final physical gate uses bounded native wheels, full top+bottom clearance,
hit-testing, paint frames and actual decoded video; it does not waive those
failed attempts. CSS injection was diagnostic only and never used in final runs.

One-line harness change reason: the repaired shared preflight veto prevents an
anchor from being created, so the daily-loop observer now asserts the actual
cancelled same-origin navigation protocol and zero accepted/downstream action.
Its original canceled-anchor observer, absolute-versus-relative URL mismatch,
and early history-checkpoint comparison are preserved. The final baseline waits
for actual native scroll/history checkpoint agreement and stable focus before
Enter, then compares the **entire** history state with no field exclusions.
Desktop actual scroll stayed1764 while its prior509 checkpoint caught up;
mobile stayed667. Palette opening caused no actual background jump.

A prior Save-enabled keyboard readiness failure and an unsupported bundled-ffmpeg
`fps` filter attempt are preserved too. The decoder uses supported output-rate
sampling and passthrough native frames. Tool setup mistakes (system Python
without Pillow and a syntax-check typo corrected before browser launch) are not
passing browser evidence.

Harnesses live beside this README. Use the root worktree with
`NODE_PATH=/private/tmp/arxiv-agent-eng-workspace-controller/web/node_modules`;
Playwright uses the bundled Chromium. [Exact run commands](run-commands.json),
[raw command logs](final/logs/) and [artifact hashes](browser-artifact-hashes.json)
make the runs reviewable. Browser hashes exclude all `checks/` ownership,
README/summary/hash receipt self-cycles. Remote CI, PR, push and merge were not
performed. OS-level IME behavior, other browser engines, real external outages,
provider reliability and owner usefulness remain unassessed.
