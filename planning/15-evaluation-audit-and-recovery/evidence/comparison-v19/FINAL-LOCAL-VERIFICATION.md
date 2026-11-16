# Final local verification of the frozen application

Application: `b1bad909b112c246b678c0194325ae974e4284bf`. Packet:
`00cc2c78e66fcc58c16a5afcf24db3c5177b6a8940ef2638c07a841edeacf48d`.
This is offline software evidence, not owner approval or provider/quality evidence.
The [one current decision](APPROVAL-DECISION-v2.md) remains prospective.

## Required local checks

| Check | Actual result |
| --- | --- |
| `make test-cov-diff` | 8378 passed, 54 skipped, 53 E2E deselected; 3448.27 seconds; exit 0 |
| Project coverage | 94.055266% unfiltered line/branch aggregate; required floor 89% |
| Patch coverage against origin/main | 95% printed; required floor 90% |
| Package floors | API 88/86, agents 96/92, security 100/97, eval 95/91 (printed actual/floor), all exit0 |
| Recorded coverage contexts | 10234 including import context; no context filtering for floors |
| New artifact/document/protocol/hygiene/harness checks | 133 passed in 34.74s, with coverage disabled to preserve the full-gate data |
| Final contract/authority/harness focus | 89 passed in 3.60s |
| Final Learn/Research production pipeline controls | 24 passed in 73.04s; 58 synthetic Message attempts +58 exact paired counts |
| Same frozen packet complete protected replay | 14 synthetic jobs /44 Messages /44 exact counts; zero duplicate dispatches |
| Strict Python typing | 249 source files, no issues |
| Required `ruff check .` | Passed |
| Python E2E | 53 passed, 8433 deselected,in 20.11s; zero spend |
| Scripted research simulation | 20/20 succeeded, 0 errored,USD0.0000 |
| Registry parity | 260 objects, 0 mismatches; no registry changes |
| Unchanged frontend tests/coverage | 4298 passed, 9 skipped; statements98.16%,branches94.34%,functions94.17%,lines99.52% |
| Unchanged frontend typecheck/lint/production build/budgets | Passed; CSS24868/25600B,Today JS169850/169984B,Reader JS165936/169984B |

The full local gate started before the new artifact test was added. That test
was subsequently verified in the133-test focused run. Exact-publication CI will
collect the final tree. Local54 skips are retained and are not reported as passes;
raw output and CI's own collected/skipped census are preserved separately.
The unchanged frontend tree was verified equal to the tested predecessor after
the final backend-only display correction.

## Actual browser and persistence evidence

The actual isolated Next/FastAPI/Postgres Reader passed 8/8 warmed journeys
(desktop 1440×1000 light / mobile 390×844 dark), spanning partial comparison,
comparison abstention/source notes, full abstention and Learn. It preserved
all gaps, answer/context and question roles, exact PDF excerpts, JSON/Markdown
exports, saved results, reload, settled thread resume and read-failure recovery.
API process restart preserved all 4 snapshots, entries and threads exactly.
106 runtime/Reader files matched both worktree and Git blobs at the application.

One cold development-server run remains7passes/1FastRefresh thread-navigation
timeout, with its original trace/log/video retained. The broader browser-history
limitation remains open. The source sidebar/header still shows the immutable
metadata observation while separate API fields identify available partial PDF
excerpts; that wording is ambiguous and is not claimed fixed here. Source identity
and exact passage checks do not establish complete-paper acquisition.

Both synthetic-preview and simulated/quarantined result labels occur in initial
captures. They are nontransient content but may scroll out of view; cropped
coverage screenshots alone do not prove a visible badge. The two development
PDF copies are distinct from inherited2610.* exposed benchmark abstracts whose
bibliographic acquisition provenance was not newly verified.

## Preserved failures and non-gating diagnostics

The first full run was intentionally cancelled for a prospective packet-privacy
repair; its partial data/logs remain. The second run failed2 harness assertions
identifying one new module without a unit-tier marker (8374 pass / 54 skip / 53 deselected,
94.06% coverage). The marker was fixed and the complete unchanged gate above passed.
Earlier mock/seed/browser/harness and local dependency-link failures remain private.

An additional repository-wide `ruff format --check` diagnostic was not green:
372 files would reformat. It was not applied. The repository explicitly excludes
formatting from gates in pyproject.toml ("Linting is a gate. Formatting is not").
The required lint command passed; no gate, test assertion, coverage floor or
performance ceiling was weakened.

## Accounting, authorization and publication

Database-enforced read-only preparation matched all historical/source/financial/
authority rows at 46 jobs / 80 Messages / 105 counts, known USD 2.533843 plus retained
USD 2.275066 overlapping liability counted once; no active jobs. Workflow known
USD 0.740467 and checker knownUSD 1.793376 remain separate. No live approval,
financial mutation, settlement, cap activation or new provider/count contact
occurred. Owner3137/review3178 and data remain unchanged.

The next protective campaign is 14 jobs / 44 Messages / 44 paired counts / USD 14.00; the
USD2 buffer brings existing exposure plus that envelope to USD 20.808909. The
prospective USD 22 programme/day/month adjustment is inactive. Existing64/160/200
caps and programme expiry 2026-11-21T11:03:57Z remain unchanged. Human fields stay
null; source integrity, scientific support, checker reliability, personal
usefulness and human qualification are separate. Actual provider token fit,
v19 remote compiler acceptance and live quality remain UNMEASURED.

The publication commit and **exact-head** hosted workflow/all-required-job results
are recorded after push in the permanent private `PUBLICATION.json` and final
handoff. This document asserts no hosted green result. Provider activation must
verify those actual results, this exact packet/code and a fresh unexpired owner
decision. Everyday generation, recurrence and notifications remain disabled;
no merge/deployment or original-agent qualification follows.

## Raw verification log identities

Private originals remain in permanent `arxiv-evidence/d5-comparison-v19-20261116/`.

| Retained file | SHA-256 |
| --- | --- |
| FULL-COV-DIFF-03.log | `06ece18a23aa0cd0529e5c4ac3bf83c6798086b9c5d1f3a1b5987b094f4b657b` |
| FULL-COV-DIFF-03-RESULT.json | `808194b9abfe4dbb98c484c46841b33ffb1db9a0904466017e213ddb97ac9cf6` |
| COVERAGE-FINAL-03.json | `891349696a35dafbda1f8c4b8e0617d713c1121bb348a9b9ec5d42b550c3c8fd` |
| FINAL-PACKAGE-FLOORS-01.log | `fdfdea9c613cccc10fb0be7ef01b31a6bcd9f12baa8fcadd5e91659e98b983c2` |
| FINAL-ARTIFACT-DOCS-01.log | `cd9a983218b830cd3508084548cccd8fb73bf90c2e22b4640d18d7cc88991266` |
| FINAL-MYPY-04.log | `96a18ececf4b151b9885583436b5bdfaedad3581843143601d87a09e3be99668` |
| FINAL-RUFF-07.log | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| TEST-E2E-02.log | `edf85b31bf10e688f786c490e8f1ddbd9ef9dde020fcbaaa73883a1ed5437719` |
| SIMULATE-RESEARCH-02.log | `04e5928d0fd6c0e49410c84724a91f44f9d0c985e4dca68f5b07c5bf0b96ba4e` |
| REGISTRY-PARITY-02.log | `ffe3a2763694f735d44ac4b58fee474f7091fa78a56db0f351933f7a88375886` |
