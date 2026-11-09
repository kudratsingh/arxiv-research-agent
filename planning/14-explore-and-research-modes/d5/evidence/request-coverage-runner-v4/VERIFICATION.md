# Request-coverage protected runner — offline verification

Application: `6803cd34b90943f2c70974615e2ea51e58f02010` (implementation starts at
`500e7bd5`, then bounded audit optimization, calendar-safe fixtures and canonical
metadata binding). Test-only dispatch-boundary correction: `58839a7a`.
Starting publication: `bec2a42c3463496466bcc71bed37c22d3aff7c1e`.
Packet: `f48b3f24fd7c831d76aed787faebc4e64b2c322ef80657d0a2f6bd8ea6ee0b86`.
Scope: `d5-f48b3f24fd7c831d76aed787`. No live scope/grant has been recorded.

[Exact packet](packet.json.gz), [compiled request/case bindings](BINDINGS.json),
[replay receipt](REPLAY-EVIDENCE.json), [preservation receipt](PRESERVATION.json),
[canonical source receipt](CANONICAL-SOURCE-BINDING.json),
[read-only live readiness](LIVE-READINESS-READONLY.json).
[Runnable commands](../../COVERAGE-RUNNER.md),
[separate A-only request](../../COVERAGE-STAGE-A-APPROVAL-REQUEST.md),
[B remains a later decision](../../COVERAGE-STAGE-B-PROPOSAL.md).

## Actual protected replay

The final packet ran through `d5_benchmark`, `D5MeasurementAdapter`, `D5Adapter`,
the existing operator recorder, scope admission, original programme and all
amendment/history audits, reservations and contact journal. Only the transport
was mocked. Disposable database: `workspace_d5_coverage_runner_v4_final`, port15488.
The permanently marked fixture database cannot dispatch provider calls. Its
synthetic authority does not authorize any live scope.

- A: three ready count-only helpers, zero Messages and zero funded jobs.
- B before its own grant: refused with `d5_stage_not_authorized`.
- After a separate synthetic B grant: three mechanically ready development
  workflows. Learn runs draft → check → changed repair → mandatory second check;
  Research retains separate source notes without claiming the missing comparison;
  the application-safety control fully abstains and asks for the four missing
  context fields.
- Actual replay uses eight synthetic Messages and eleven synthetic counts total,
  including A. Copied cumulative ledger:33 jobs/69 Messages/92 counts;
  original known estimate remainsUSD1.779493, pending/unknown0. Real new contacts
  and spend remain zero.
- Maximum-envelope regression forces repair/recheck in all three controls:
  twelve Messages and fifteen counts including A, cumulative33/73/96. It also
  attempts extra A/B contacts and requires refusal.
- Synthetic integer100 counts are **not provider token measurements**. Synthetic
  checker verdicts are not whole-claim quality, request-coverage or human evidence.
  Acceptance remains HOLD, all human labels null, every case development.

Raw replay is retained locally at
`outputs/d5/coverage-runner-v1/verified-replay-v4/REPLAY.json` with its SHA256 in
the committed compact receipt. It includes exact dynamic checker/repair request
and receipt digests; no future response-dependent requests were invented.

## Refusal and preservation coverage

Targeted unit/PostgreSQL tests cover unsupported profile/extra case/request,
source/model/settings/schema/producer drift, B without A or its own grant,
C/D grants and execution, A's exact model/body/input/result receipt binding,
programme/scope expiry and revocation, global job/count caps, full-workflow
capacity and new-spend refusal, invalid/truncated completed responses and stable
inspection of completed identities without extra contact. The three amendment
validators audit the predecessor once per validation, then audit it afresh on the
next operation; they do not cache across transactions or contacts.

The read-only before/after comparison includes all historical permission tables,
contact history, the active ledger pointer, frozen v8r4b packet/scorer/results
and supplied Codex synthetic exports. All match. Actual live ledger remains
30 jobs/61 Messages/81 counts/USD1.779493, pending/unknown0. Existing programme
34 jobs/80 Messages/99 counts/USD10/concurrency1 and expiry
2026-11-14T07:24:01Z are unchanged. Stage D remains deferred/ungranted.
Owner3137/review3178 and owner preferences/notes/judgments were not written.

## Gate results

[Machine-readable check receipt](CHECKS.json). Results below use the exact source
of application6803cd34 and test commit58839a7a; their `src/` trees are identical.

| Check | Actual result |
|---|---|
| `make test-cov-diff` | 7020 passed, 54 skipped, 53 deselected in 1198.94s (0:19:58) |
| Project / patch coverage | 94.59% / 96% |
| Package floors, API / agents / security / eval | 88 / 96 / 100 / 95%; floors 86 / 92 / 97 / 91% unchanged |
| Final targeted policy/runner/calendar/harness | 124 passed in 156.80s (0:02:36) |
| Prose and hygiene | 95 passed in 24.70s |
| Workflow E2E | ===================== 53 passed, 7074 deselected in 25.19s ===================== |
| Mock simulation | 20/20 succeeded, 0 errored, total $0.0000 |
| Registry parity | 260 objects /0 mismatches (no registry object changed) |
| Ruff / strict mypy | All checks passed! / Success: no issues found in 202 source files |
| Exact packet verify | Passed |

The final source has no uncommitted runtime changes. No coverage input, floor,
timeout or assertion was weakened. New replay CLI module coverage is reported
separately in CHECKS.json; the actual standalone three-case replay covers the
executable driver outside the pytest coverage selection.

Exact published-head remote CI is tracked independently in the
[branch Actions record](https://github.com/kudratsingh/arxiv-research-agent/actions/workflows/ci.yml?query=branch%3Acodex%2Fworkspace-d5-coverage-runner)
and final publication receipt/owner handoff. Local success is not remote CI.

Frontend source, API contracts, registry objects and runtime dependencies are
unchanged. This task adds no browser or model-quality qualification claim.

## Retained diagnostics and limits

The pre-optimization coverage run failed two inherited tests when fixed Nov2
synthetic observations aged out of the seven-day window. Their synthetic fetch
(and Radar first-seen) timestamps now use the isolated database clock; all
assertions remain. That run also reproduced maximum-envelope timeouts. Profiling
identified duplicate recursive predecessor validation inside proposal rebuilding;
the bounded optimization preserves full per-contact audits and the60-second test
limit. The obsolete run was interrupted; SIGINT did not end it promptly, and it
was terminated before the final stable gate. Its partial data is not acceptance.

An intermediate focused coverage run passed176 tests but failed three new tests
because they were collected as synchronous under the module's asyncio mark.
They are now async; the final suite recollects them. Its21.60% project-wide
coverage reflects a narrow selection and was not a full coverage pass. A typo in
one diagnostic harness path collected no tests; the corrected command is retained.

The first stable pre-canonical full gate passed7014 tests/54 inherited skips/
53 separate E2E deselections,94.58% project and96% patch. That result is preserved
for its producer, not substituted for the final gate. Additional read-only
preflight correctly rejected the prototype's synthetic metadata; a canonical-
storage-only candidate then correctly failed because its sealed local metadata
fields still carried fixture hashes. The final compiler corrects only
`version_hashes` and `source_version_hash` from canonical public metadata, while
retaining exact material hashes, passages, count bodies, schemas and settings.
PostgreSQL coverage uses deliberately distinct metadata/material hashes through A
and B; drift after reservation must fail on advance before any count. No immutable
live source record was rewritten.

An initial canonical-focused command lacked the existing isolated `jsonschema`
test overlay and failed collection; no shared venv was modified. The next run
passed66 tests but caught two test expectations: metadata tampering targeted an
unselected extra fixture, and drift was incorrectly expected at reservation
rather than dispatch. Corrected tests exercise selected metadata at the actual
pre-count boundary; both focused regressions pass. An early full run which had
already collected the obsolete assertion was stopped and recollected.

The pre-optimization500e7bd5 candidate and replay are retained under ignored
`outputs/d5/coverage-runner-v1/pre-optimization/`. The sealed-artifact writer
refused overwrite; this final candidate uses a new `request-coverage-runner-v4`
path. Attempting the old packet on newer source also correctly refused producer
drift before mock contacts. No old paid output or authority was rebound.

Prices are carried-forward ESTIMATE, not freshly reverified offline. Actual
remote schema acceptance, measured token fit, model quality and human review
remain unmeasured. No provider Stage A/B or live grant is executed here.
