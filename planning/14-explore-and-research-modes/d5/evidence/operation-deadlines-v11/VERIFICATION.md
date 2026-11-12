# Offline verification: operation deadlines v11

Application `92c5a9eafa81bbaa279a5b44312f1519a1bd522c`; candidate packet
`079748d34931142270f947038df90dc1dcae135adf0b1b88d153324d3a1a5ef3`.
[Machine-readable local checks](LOCAL-CHECKS.json), [branch-inclusive coverage](LOCAL-COVERAGE.json), [identity](IDENTITY.json),
[preservation](PRESERVATION.json), [measurement audit](MEASUREMENT-AUDIT.json).

## Final local gates

Commands ran from the isolated worktree with the disabled-key sentinel. Database
writes used disposable test schemas, not the active qualification ledger.

- `make test-cov-diff`: **7127 passed, 54 skipped, 53 deselected in 1124.88s (0:18:44)**; **94.64% project / 97% patch**.
- Equivalent existing per-package coverage floors on that same full-suite data:
  api 88% (floor 86%), agents 96% (floor 92%), security 100% (floor 97%), eval 95% (floor 91%).
- New source patch coverage: deadlines96.9% (only real clock accessor untouched by
  controlled-time tests); packet100%. No coverage input, floor or test timeout changed.
- Final focused modules: **31 passed in 42.78s**.
- Earlier broader adapter/reuse/coverage focused run:93passed; final full gate
  above covers the final policy and added edge tests.
- Mypy: Success: no issues found in 207 source files; Ruff PASS; final documentation/hygiene95passed.
- Workflow E2E53passed; mock research20/20 at USD0; registry260objects/0mismatches.
- Frontend221files/4280passed/9skipped, existing coverage thresholds pass;
  typecheck/lint and production build pass. All enforced route budgets pass,
  CSS24,868bytes; Today JS169,843bytes against169,984. No frontend source changed.
  Existing jsdom canvas/scroll warnings remain; these tests are not browser proof.

## Cases and controls

The actual production adapter receives MockTransport and controlled virtual time.
The successful31-second checker fails under legacy30 and completes under120.
121seconds remains uncertain. Cancellation, expiry and process loss preserve the
synthetic hold through restart; alternate identities/duplicate starts refuse.
An overall480-second horizon caps an almost-expired check at5seconds. The complete
four-stage path preserves Sonnet/Opus routes, mandatory paired counts and one
repair/recheck. Wrong policy/origin/programme/schema bindings refuse.

The blocked prospective packet preserves the actual uncertain checkpoint.
Fixture authorization and operator preparation refuse before context writes.
No synthetic review labels or authorization are copied into the active ledger.
Mock counts, usage and verdicts establish software controls only, not actual token
fit, latency, factual quality or human qualification.

## Preserved diagnostics

The first focused run found a self-lock introduced in the new response deadline
read: it held a job-row lock while a second snapshot connection requested it.
Replacing that read with a plain SELECT fixed it; final tests and the full gate
pass without changing pytest's60-second limit. The initial mypy import-name
collision was fixed. Sandbox-only process/loopback errors were rerun with local
permissions; those interrupted attempts are not reported as passing gates.
Original logs remain in `outputs/d5/operation-deadlines-v11/`.

## Publication and CI

The application is the source/test commit above. A later publication commit adds
only planning/evidence. Local results do not establish remote CI. The final owner
handoff and `outputs/d5/operation-deadlines-v11/PUBLICATION.json` record the exact
published SHA and its Actions run after completion. [Branch Actions](https://github.com/kudratsingh/arxiv-research-agent/actions/workflows/ci.yml?query=branch%3Acodex%2Fworkspace-d5-operation-deadlines).
No PR, merge, deployment, owner3137/review3178 modification, provider contact,
live grant or account mutation is part of this revision.
