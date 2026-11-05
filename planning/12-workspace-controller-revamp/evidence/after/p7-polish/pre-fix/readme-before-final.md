# P7 browser verification — in progress

These are baseline results and prepared verification harnesses. **No final P7
browser gate or recording is claimed yet.** The implementation owner withdrew
the first source/build/static-copy freeze for two bounded edge fixes; its captures
are preserved under `pre-fix/first-freeze-withdrawn`. A revised freeze is awaited.
Application source edits, builds,
budgets and preview3168/API8168 remain that owner's responsibility.

The unchanged P6 baseline is commit
`dff860e16e89c22382bce88d98f64645dfdcbfc8`, tree
`43c5f34c0f238909a8b1fe65684de3a917cb0a5e`, production build
`FqOkJwvSTsd5JfZCNhztE`; see [binding](baseline/source-binding.json).
All runs record their actual UTC timestamps. Source and app binding for final
P7 remains pending the frozen application and the root agent's commit.

| Evidence | Baseline result | Scope/limits |
| --- | --- | --- |
| [Responsive/axe/CSP matrix](baseline/report.json) | 70/70 route/theme/width cases;28 primary axe scans with0 violations;28 DPR2 PNGs | Seven workspace routes;390/768/1024/1280/1440; both themes. All70 CSP headers have nonce/no unsafe-eval. No policy events. |
| [Form/focus](baseline/form-focus/report.json) | 4/4 | Actual keyboard focus outline and computed textarea styles, both sizes/themes. |
| [Coarse-pointer targets](baseline/touch-targets/report.json) | 14/14 measurements;0 buttons/navigation controls below44px |390px, actual coarse pointer, all seven routes/both themes. Inline prose links excluded. |
| [Fictional Today and Workbench](baseline/legacy/report.json) | 8/8 | Fresh direct loads, both sizes/themes. Workbench axe0; fictional Today has one inherited moderate region rule finding for two preview-banner texts. |
| [Legacy pages after workspace navigation](baseline/legacy-via-workspace/report.json) | 8/8 | Visible workspace→fictional preview→Research a question links. All eight screenshots, computed states and axe results are [identical](baseline/legacy-via-workspace/direct-comparison.json) to direct-load baseline. |
| [Cold exact Reader entry](baseline/reader-readiness/report.json) | 4/4 | Exact retained long abstract/range/quote and16px placement. Cold settled JS response-body bytes225945 desktop/173880 mobile; single observations, not a benchmark. |
| [Cold focused paper routes](baseline/paper-readiness/report.json) | 12/12 | Fresh Today/Radar/Library contexts across both sizes/themes. Exact selected versions/titles/abstracts and first DOM/visible readiness; settled bytes recorded for each route. |
| [CI Source→Notes→Source](ci/p6-source-notes/report.json) | 4/4 | Actual UI tab clicks and8 real reading-position POSTs in disposable CI. Logical reading fields restored; revisions naturally advance8→16. Notes/profile/sources/schedule unchanged. Desktop225945B/26 scripts and mobile173880B/18 scripts at all three settled stages. |
| [Native queue/Reader sequence](baseline/geometry/report.json) | Confirmed inherited failure in all4 contexts | Initial clearance, queue870, rapidJ/J/K, Radar page2 and native Back870/Forward reach the far-fragment step, where no mark appears. See [independent diagnosis](review/inherited-hash-gap/README.md). |

The CI Source/Notes run has an [observer limitation](ci/p6-source-notes/observer-limitations.json):
ignore its first-Notes timestamp and observer phases, which did not account for
CSS `data-active`. Explicit stage checks did assert actual textbox visibility,
POST200 and enabled controls. Source/heading readiness, transfer/waterfall data,
explicit settled stages and restoration assertions remain valid. The future
harness observes actual panel rectangles and `data-active`.

All preview reads block browser mutations and external requests. Preview review
labels and reasons remain blank. Data is explicitly synthetic offline fixture
data; no scientific validity, source freshness, personal usefulness or human
quality acceptance is implied. The CI run writes only the separately named
synthetic verification principal. Provider/source/generation contacts are zero
for these baseline observations.

## Preserved unsuccessful and preliminary attempts

- `pre-fix/form-focus-volatile-as-of`: controls passed focus checks, but the first
  unchanged-state comparison mistakenly included the per-response `as_of` clock.
- `pre-fix/geometry-radar-query`: an old walkthrough's `navigation` filter did
  not have enough preview results for page2; corrected to the fixture's proven
  `agent` filter. This is separate from the genuine far-fragment failure.
- `pre-fix/reader-readiness-initial-timing`: successful initial observations;
  repeated only to add navigation-relative request epochs for a proper waterfall.
- `pre-fix/p6-source-notes-restore-race`: one cleanup attempted stale-revision
  restore while the Source tab POST was finishing and received409. The corrected
  run explicitly waits for each reading POST200 and enabled controls. All raw
  files are retained. No owner data or application source was involved.
- `pre-fix/frozen-geometry-immediate-hash-check`: first-freeze geometry3/4;
  mobile light observed the old hash immediately after fragment Back. Corrected
  harness waits boundedly for the required URL, retaining the exact same expected
  hash and mark assertions.
- `pre-fix/first-freeze-withdrawn`: bounded-hash-wait geometry3/4, with all four
  repaired far fragments/fragment Back/Forward reached. Mobile light then failed
  a Source-bottom snapshot immediately after programmatic scrolling; subsequent
  harness uses an actual wheel and waits for the measured maximum scroll. This
  remains an investigation, not an accepted app regression or a passing final
  recording. Independently, the implementation owner withdrew this build for
  terminal list-route outage settlement and initial entry/named-tab fixes.

## Isolation and service ownership

Owner3137/API8137, original preview3148/API8148 and pilot3158/API8158 are preserved.
The P7 implementation owner controls preview3168/API8168. Browser regression CI
uses only new DB `workspace_controller_p7_ci` on verification PostgreSQL15458,
principal `controller-p7-ci`, API8169 and frontend3169. The [setup receipt](ci/setup.json)
records its unique database ownership comment and canonical3-work/4-version seed.
The sentinel is `local-preview-disabled`, mock data is enabled and recurrence is
false. Dummy local auth credentials are not provider credentials.

Temporary P6 baseline Node PID16339 on3169 was verified and stopped after the
Source/Notes observations. CI API PID10951 on8169 remains; frontend3169 is free
pending the final P7 build. After final checks, teardown must verify exact owned
PIDs and the CI database ownership comment before stopping only those services
and dropping only the new CI database. Preview3168 and all sibling services stay.

## Final verification queued after source/build freeze

- [read-only-matrix.cjs](read-only-matrix.cjs): same70 responsive cases,28 axes,
  actual themes, CSP nonce/no-eval/no events and blank review/state preservation.
- [form-focus.cjs](form-focus.cjs), [touch-targets.cjs](touch-targets.cjs),
  [legacy-readonly.cjs](legacy-readonly.cjs): matched focus/forms/coarse targets and
  direct plus navigated fictional Today/Workbench screenshots.
- [command-ui.cjs](command-ui.cjs): palette/shortcuts axes, focus trap, visible
  active option, CtrlK/MetaK, filter/Enter/Escape, modal shortcut isolation on Today
  and Review, stale slash rows, typing guards, local theme restoration, mobile
  drawer ownership, collapsed-rail hidden commands, actual desktop/mobile WebMs.
- [moods-motion.cjs](moods-motion.cjs): captured synthetic latency/outage/empty
  states; busy/alert/sleepy moods; no CSS/WAAPI animation under reduced motion.
  Injection is software-only evidence and is never forwarded as a source check.
- [geometry-sequence.cjs](geometry-sequence.cjs): native queue/rapid/history/far
  range, fragment Back/Forward, live position announcement/player focus, source
  and notes lower-content clearance, actual desktop/mobile WebMs.
- [reader-readiness.cjs](reader-readiness.cjs),
  [ci/source-notes-transfer.cjs](ci/source-notes-transfer.cjs): cold long-source
  and matched actual Source/Notes settled JS/request waterfalls/ready stages.
  Mandatory ReaderContent deferral is disclosed; a lower official initial-bundle
  number alone is not an actual-transfer or user-speed reduction claim.
- [paper-readiness.cjs](paper-readiness.cjs),
  [delayed-paper-core.cjs](delayed-paper-core.cjs): mandatory FocusPaper is also
  deferred on Today/Radar/Library. Compare actual settled bytes and first focused
  title/abstract readiness, and hold the real chunk while rapidJ/J/K changes queue
  selection, requiring a truthful busy state and the final exact paper after release.
- [delayed-reader-core.cjs](delayed-reader-core.cjs): hold the actual mandatory
  ReaderContent chunk, assert a visible busy fallback, change the hash while held,
  release original bytes and require the exact unobscured retained mark.
- Unchanged existing16 live-workspace regressions on CI, then
  [ci/daily-loop.cjs](ci/daily-loop.cjs): real keyboard daily loop, deliberate held
  save/conflict/pending-route guard/retry in disposable CI; actual two WebMs.
- [inspect-videos.py](inspect-videos.py): decode complete successful-run WebMs and
  create timestamped contact sheets for explicit visual review. It refuses to
  call failed/partial runs final. Visual acceptance is recorded separately.

These extra scripts live in evidence rather than silently joining the existing
`**/*.spec.ts` regression suite. The existing16-test baseline stays distinct from
the additional axe/interaction measurements (E73 implementation deviation).
The root agent conditionally approved keeping byte-identical `daily.css` and
`daily-app` foundations (E58 deviation); final visual checks cover their effect.
CSS caps/headroom and JavaScript measurement/ceilings remain unchanged.

Run browser scripts from the P7 worktree root with:

```sh
NODE_PATH=/private/tmp/arxiv-agent-eng-workspace-controller/web/node_modules node planning/12-workspace-controller-revamp/evidence/after/p7-polish/<script>.cjs
```

Phase/base/principal scripts take `final http://127.0.0.1:3168 controller-p7-preview`.
Legacy carry-over adds `--via-workspace`. The CI Source/Notes script takes `p7`;
set `P7_SOURCE_COMMIT` to the frozen application binding. Exact actual commands,
logs, application hashes, final results, video inspection and teardown receipts
will be appended after execution. No push/PR/merge or P9 work is authorized.
