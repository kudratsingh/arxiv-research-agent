# P7 mechanical checks

Application source: `83b196eb14b33cd3033453701e93482266366e5f`, based on
`dff860e16e89c22382bce88d98f64645dfdcbfc8`. The application files remained
unchanged between the revised production build, full checks and local source
commits. [Application manifest](application-source-manifest.json) records all
24 changed/new/deleted application/configuration files and verifies them
against this commit. The three byte-identical foundations are included too.

All commands ran from the isolated worktree's `web/` with
`ANTHROPIC_API_KEY=local-preview-disabled USE_MOCK_DATA=true
WORKSPACE_SCHEDULE_APPROVED=false`. Production build also used
`NEXT_TELEMETRY_DISABLED=1`. There were no provider contacts, real-source refreshes,
owner-data writes, dependency additions, or coverage exclusions/floor changes.
Vitest and production build did not overlap.

| Command | Result | Receipt |
|---|---|---|
| `npm run lint` | exit 0, zero warnings | [lint.log](lint.log) |
| `npm run typecheck` | exit 0 | [typecheck.log](typecheck.log) |
| `npm run build` | exit 0 | [final-build.log](final-build.log) |
| `node scripts/route-budgets.mjs` | exit 0, all 20 gated rows pass | [final-budgets.log](final-budgets.log) |
| `npm test -- --coverage` | exit 0, 201 files / 4,072 tests pass | [final-coverage.log](final-coverage.log) |

The separate build and unchanged budget-script commands perform the same two
steps as `npm run budgets`. [Machine-readable gate summary](gate-summary.json)
and [coverage summary](coverage-summary.json) retain the actual numerators and
denominators. Final coverage is 98.18% statements, 94.21% branches, 93.31%
functions and 99.46% lines, above the unchanged 98.15/94/92.2/99.11 floors.
Commands, queue, URL state and draft helpers each retain 100% statement, branch,
function and line coverage in the machine-readable summary.

CSS measured 23,940 B. The owner-approved `ceil(measured * 1.06 / 512) * 512`
ratchet is 25,600 B, leaving 1,660 B (6.93%) and staying below the unchanged
26,624 B hard cap. The mechanically derived transfer ceiling moves by the same
8,192 B to 327,680 B. Every JavaScript ceiling is unchanged. The legacy
`components/workspace/workspace.css` is deleted. The E58 implementation deviation under owner-authorized scope retains the
byte-identical `daily.css` / `daily-app` foundations rather than emit duplicate
form/focus rules. ROOT chose this reversible implementation to satisfy legacy
preservation and the CSS cap; no new owner-specific E58 ruling is claimed, and
this is not a budget exception. The Evidence Workbench stylesheet and shared token file are also
byte-identical to the base.

Focused regressions retain [83 review-edge checks](review-regressions.log),
[87 lazy-readiness checks](readiness-tests.log), and the [15 command-surface
checks](slash-regression.log). The final strict native-dialog focus fix also
passes [116 keyboard/navigation checks](dialog-trap-regression.log), including
actual Tab/Shift-Tab traversal in palette/help, browser-modifier preservation
and composition guards. Earlier full-suite attempts identified missing
lazy-content waits and then a statement coverage result of 98.14%. Assertions
for request bodies, versions, saved anchors, drafts and honesty were preserved;
the added real slash-submit/stale-context regression covers an actual execution
path. No threshold was lowered. The final full log supersedes those attempts.

An interim lazy FocusPaper/Reader boundary had an observed approximately 300 ms
mandatory-content reveal delay. Final FocusPaper is eager. Reader instead uses
an explicit cached-module/inflight loader after real item data, with stale and
unmount guards, visible error and explicit retry. The exact original editor key
and mounted draft remain stable across hash changes. The [106 focused content
readiness checks](core-readiness-regression.log) include real older-version draft
and passage recovery after a failed import followed by a new version, with no
writes. Cache/inflight/error/retry helpers have 100% coverage.

[Paired cold observations](observed-content-readiness-and-transfer.json) record
Reader and Today JavaScript response-body transfer including lazy chunks and
required-content DOM times. Reader is 229,514 B desktop / 177,456 B mobile,
above P6's 225,945 / 173,880 B by 3,569 / 3,576 B. There is no claimed total
transfer reduction. The observed interim reveal plateau is gone; final cold
Reader samples are 193–325 ms. These are single loopback observations, not a speed
benchmark or proof of uniformly faster performance than P6. Matched held-chunk,
failure/retry and no-data browser receipts are in the parent evidence package.
Mechanical checks do not replace that acceptance.

The inherited same-document Reader fragment gap has a bounded view-only fix;
it does not claim to solve the separately recorded broader unsaved-draft
browser Back/Forward limitation. Native form, exact version and saved-entry
precedence checks remain in the final suite.
