# V15r2 verification and remaining limits

Runtime application: `a0ad5c2ceb5ba1d69753f1bd398876e054e90792`.
Packet: `25eec8f541dbe7f70bf2fadee59f51c0d8b456980856cd4f38fce20b139e8bde`.
The [gate receipt](LOCAL-GATE-RECEIPT.json) binds the original log hashes.

## Final local gates

The full unchanged non-E2E selection ran with branch coverage, the C tracer and
per-test coverage contexts through `make test-cov-diff`. Actual results:

```
7764 passed, 62 skipped, 53 deselected in 1851.88s (0:30:51)
Required test coverage of 89.0% reached. Total coverage: 94.38%
Total:   13014 lines
Missing: 476 lines
Coverage: 96%
```

All four package floors reread that same complete coverage database: API 88 ≥ 86,
agents 96 ≥ 92, security 100 printed ≥ 97, eval 95 ≥ 91. No selection, coverage
input, floor, assertion or watchdog was weakened. The 62 skips include eight
private archive controls; the complete extension module separately passed 42/42
with its original POST-STOP-LEDGER snapshot copied into disposable storage.

The first supplemental invocation used the general census layout and produced
34 passes / eight setup errors. Correcting the snapshot path changes no source
or assertion; both original logs remain. Power transitions were retained in
`ci-profile-repair/POWER-TRANSITIONS-v1.json`. UTC wall time is not the duration
reported by pytest. Separate E2E: 53/53; research simulation: 20/20, USD 0;
registry: 260 objects / zero mismatches; strict mypy: 230 files; Ruff passes.
Documentation/hygiene tests passed 66/66 before final publication formatting.

## Cancelled predecessor CI and measured repair

[Run 43556087526](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/43556087526)
on head 47473977 ended CANCELLED: eight successful jobs and one cancelled Python
job. Seven earlier 60-second test timeouts were logged. The suite reached 89%
test progress, not 89% code coverage. It produced no final pytest totals or
completed project/package/patch floors. Later Python E2E, campaign, safety and
simulation steps were skipped. All nine original job logs, the workflow archive
and eight artifacts are preserved; successful uploads are not passing gates.

Profiling an unchanged protected checkpoint found 1,484,736 matcher calls and
170 ranking calls. The regex requires an escaped literal substring. The fix
skips only absent literals; every possible positive still receives the original
Unicode word-boundary and plural check. Regex searches fell from 1,492,597 to
66,645; ranking cumulative time fell from 29.45 to 2.99 seconds. The same test's
profiled call took 38.65 seconds before and 12.24 after; both passed.

The 34 equivalence tests cover Unicode, escaping, whitespace, boundaries,
exclusions and complete rankings on the frozen 40-item public corpus. Affected
campaign/report-binding modules plus those controls passed 50/50 under
CI-shaped coverage in 148.36 seconds; slowest test 11.48 seconds. The default
60-second test watchdog and 60-minute aggregate CI bound remain unchanged.
These local measurements do not establish hosted CI success.

## Exact protected pipeline and original response

The new packet replayed 14 synthetic jobs, 44 Messages and 44 paired counts
through production admission, adapter, journal, cumulative accounting,
persistence and current-response report binding. All workflows repaired and
rechecked; duplicate invocation dispatched nothing. Both historical holds remain
unchanged. All 88 complete HTTP bodies were losslessly reconstructed and hashed.
Maximum observed request: 72,027 UTF-8 bytes; raw output: 27,201; normalized
output: 50,132. Counts, usage and verdicts are synthetic. Quality remains HOLD.
See [replay](OFFLINE-REPLAY-RECEIPT.json) and [sizes](SIZE-OBSERVATIONS.json).

A fresh original-response replay on this source retained all reasons exactly:
104 / 110 / 82 / 87 / 92 characters. Only the checker revision changed in the
labelled derivative. It reached semantic review, where p1 uncertainty still
requires repair. No repair was dispatched in that control. The old contract
still rejects the unchanged original and its historical result remains FAILED.
See [regression and custody](REGRESSION-AND-CUSTODY-RECEIPT.json).

## Frontend and predecessor evidence

The entire web tree is byte-identical to c5b859cc. Its 4,294 frontend tests,
production build and unchanged route budgets apply to that same web source.
Today first-load: 168,225 bytes against 169,984; Reader: 164,307 against 169,984.
The four production-browser captures use stubbed APIs and block external traffic.
They show all 12 complete claims, the full 994-codepoint checker explanation,
an exact citation anchor and a reference-note request. They do not prove durable
browser saving, unavailable source-passage rendering or real provider quality.
The final published head's full hosted workflow must report its own result.

The earlier full c5b result, failed/interrupted attempts and their logs remain
separately attributed in the [predecessor verification](../capacity-policy-v15/VERIFICATION.md).
All 27 v13 and 48 v14 manifest entries verify unchanged; no predecessor deletion
or overwrite. Permanent evidence root: `arxiv-evidence/d5-capacity-policy-20261114/`.

## Identity, authority and remaining uncertainty

Only ranking.py changed among the 78 source bindings since candidate 243. Frozen
cases, probes, rankings, evidence, schemas, models, thresholds, answerability,
limits, budgets and expiry policy remain equal. The [read-only census](READONLY-CENSUS-RECEIPT.json)
at 05:41:25 UTC matches 36 / 70 / 95, USD 2.110597 known estimated usage and
USD 0.875066 overlapping holds counted once. Migration 020 is absent. No provider
contacts, live grants, migrations, accounting changes or expiry changes occurred.

Offline proof cannot establish remote grammar compilation, actual token fit,
complete Opus High output/thinking within 12,000 tokens / 240 seconds, scientific
support, checker reliability or usefulness. Both complete bound development
paths gate future progression. The eight evaluation controls were exposed;
20 machine references are proposed and correlated, not human gold. Missing
judgments and denominators stay UNSCORED/HOLD. Human qualification is outside scope.

The only future decision is the [consolidated approval request](APPROVAL-REQUEST.md):
14 / 44 / 44 / USD 14 new; programme 64 / 160 / 200 / USD 20, daily/monthly USD 20,
explicit programme ≤ seven days and campaign ≤ 24 hours after approval, and both
untouched holds. Every approval flag remains false. Everyday generation,
recurrence, notifications and owner3137/review3178 remain unchanged. No merge or deployment.

All rights reserved. No license or reuse permission is granted.
