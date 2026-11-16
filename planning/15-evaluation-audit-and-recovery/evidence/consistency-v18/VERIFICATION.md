# Verification — frozen v18 application and inactive diagnostic

Application: `b125d0d84953b97d40de7463863c9f56cf2ee0af`.

Packet: `fa06446ac6cb32e6a4bd0eca89d95b4198bf090d7e6fafdea82d5c434a988cd0`.

All results below are local offline mechanics. The complete final gate used the
unchanged Make target, locked interpreter, disabled-key sentinel, per-test
coverage contexts, canonical test database with unique disposable schemas, and
the separate exact historical-parent input documented in [RUNBOOK](RUNBOOK.md).
No provider/count contact, live authority or financial mutation was made.

## Full local coverage and patch gate

Command: `make test-cov-diff VENV_PYTHON=$VENV_PYTHON`, with
`COVERAGE_CORE=ctrace PYTEST_ADDOPTS=--cov-context=test` and the runbook environment.
Verbatim final output from `FULL-COVERAGE-DIFF-05.log`:

```text
Required test coverage of 89.0% reached. Total coverage: 94.38%
8284 passed, 54 skipped, 53 deselected in 3253.31s (0:54:13)
Total:   15531 lines
Missing: 578 lines
Coverage: 96%
-------------
```

The same complete data was checked against every unchanged package floor:

```text
api floor 86 actual 88
agents floor 92 actual 96
security floor 97 actual 100
eval floor 91 actual 95
project 94.37951029756603 contexts 10097
```

Raw SQLite coverage data, XML, JSON and contexts are preserved. The project
floor remains 89%; patch floor 90%; API/agents/security/eval floors remain
86/92/97/91. Nothing was omitted or excluded to obtain these results.

## Focused and composed evidence

| Check | Observed outcome | Evidence log |
|---|---|---|
| Complete originals, roles, coverage, categorized judgments | 57 passed | FINAL-SEMANTIC-AND-ARTIFACT-01.log |
| Inherited/current structural contracts and malformed selectors | 252 passed | STRUCTURAL-CROSSCHECK-03.log |
| Legacy 32 KB envelopes and prospective dependency binding | 124 passed | LEGACY-AND-CURRENT-REGRESSION-02.log |
| Production adapter, isolated Postgres, synthetic draft/check/repair/recheck controls | 65 passed | PROTECTED-INTEGRATION-07.log |
| Both abstention forms through mandatory checking and persisted Reader output | 2 passed | ABSTENTION-PRODUCTION-01.log |
| Complete-original synthetic derivatives through the adapter | 1 passed | ORIGINAL-DERIVATIVE-ADAPTER-01.log |
| Exact archived parent and regenerated synthetic production controls together | 63 passed | INHERITED-SEPARATE-INPUTS-FINAL.log |
| Ruff | all checks passed | RUFF-PUBLICATION.log |
| Strict mypy | 244 source files, no issues | MYPY-PUBLICATION.log |
| Python E2E | 53 passed | PYTHON-E2E-PUBLICATION.log |
| Scripted research simulation | 20/20, USD0 | SIMULATE-RESEARCH-PUBLICATION.log |
| Registry parity | 260 objects, zero mismatches | REGISTRY-PARITY-PUBLICATION.log |

These focused rows overlap; they are not a sum of independent observations or
human/scientific validation. Final full-suite coverage includes the source
corrections, new abstention tests and separate archive-input test option.

The exact four-request frozen packet also completed a production-runner replay
in disposable Postgres with MockTransport, then refused replay before any new
contact. All four returned complete, locally valid **synthetic** responses;
scientific quality remains UNMEASURED. A fresh read-only process/pool verified
all four persisted results and exact source links. This is not a claim that an
HTTP service was restarted. Separate current-response and uncertain-recheck
controls keep unavailable judgments unavailable.

## Frontend checks and budgets

Typecheck, lint, full Vitest coverage, production build and route budgets pass
for the unchanged final application frontend. Verbatim test/coverage output:

```text
 Test Files  223 passed (223)
      Tests  4298 passed | 9 skipped (4307)
Statements   : 98.15% ( 6756/6883 )
Branches     : 94.41% ( 5880/6228 )
Functions    : 94.09% ( 2246/2387 )
Lines        : 99.49% ( 5274/5301 )
```

The measured Today bundle is 169,845 B against 169,984 B; Reader is 165,930 B
against 169,984 B; emitted CSS 24,868 B against 25,600 B. The raw build report
retains all routes. No budget or coverage ceiling/floor changed. The added
Reader regression verifies partial status, complete gap rendering and no
full-answer credit. Browser results are reported separately by hosted CI;
this batch claims no new manual native-browser/visual acceptance.

## Preserved failed and interrupted attempts

The first two full attempts exposed the legacy producer-map 32 KB pressure and
malformed-context selector regression; source corrections retain the original
bound and validation error behavior. Subsequent local configuration attempts
mixed a synthetic parent with optional exact-archive controls. No snapshot was
relabelled, no historical assertion removed, and no storage guard relaxed.
A separate test-only archive input resolves that configuration ambiguity.

```text
FULL-COVERAGE-DIFF-03.log: 21 failed, 8252 passed, 62 skipped, 53 deselected in 3044.98s (0:50:44)
FULL-COVERAGE-DIFF-04.log: 8274 passed, 54 skipped, 53 deselected, 8 errors in 3354.00s (0:55:54)
```

These predecessor runs are **not green**. Their full logs, coverage data and
XML, synthetic snapshot candidates, partial evidence and helper corrections
remain in permanent storage. Initial dependency-unavailable/skipped focused
attempts also remain; later real-Postgres passes do not erase them.

## Publication CI and preservation

[CI for the review branch](https://github.com/kudratsingh/arxiv-research-agent/actions?query=branch%3Acodex%2Fworkspace-d5-consistency-v18)
must be verified against the actual publication SHA and all nine job
conclusions. No local result is a hosted success. The final exact-head run ID,
head SHA, individual conclusions, raw logs/artifacts and checksums are recorded
in permanent `PUBLICATION-RECEIPT.json`, delivered with the final handoff.
No later documentation-only commit is silently treated as verified.

Canonical custody: `arxiv-evidence/d5-consistency-v18-20261116/` (owner-only).
All 1,154 checked predecessor members and complete v17r2 generated originals
match their recorded checksums. Read-only active ledger remains
42 jobs / 76 Messages / 101 counts / USD2.252281 known estimated usage plus
USD2.275066 overlapping retained liability, counted once; no active jobs.
Owner3137/review3178 remain untouched. Every converted output is synthetic.
The new operator template is false/unapproved; no diagnostic dispatch is enabled.
