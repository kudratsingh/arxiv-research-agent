# Consolidated campaign: offline verification and bindings

Application **`51073b1fb1353073e71b69709985b1ae133de946`**.
Packet **`b5e2a815c3d639ebfc38d538c0d2481a040e38e2828475e6ba13445fb741e655`**.
Scope `d5-b5e2a815c3d639ebfc38d538`.
Capacity/exception proposal
`1b37b48c6259203107ee15d8a8399f90bd832d8e620d6ea09b5eaa795ddb7f0f`.

[Identity](IDENTITY.json), [packet](packet.json.gz),
[compiled exact inputs](compiled-inputs.json.gz),
[capacity and exact exception proposal](capacity-and-exception-proposal.json),
[unapproved operator template](owner-authorization-template.json),
[one approval request](APPROVAL-REQUEST.md),
[runbook and policy](../../CONSOLIDATED-CAMPAIGN.md).

## What ran

All Python commands ran from the isolated worktree with the locked interpreter,
disabled credential sentinel and offline flag. Writes used owned disposable
Postgres databases/schemas. No real grant, capacity activation, liability
settlement, provider/count contact or new spend occurred.

The full final packet ran through production admission, D5 adapters, contact
journal, exact paired measurements, mandatory checking, one repair/recheck,
persisted results and the machine-only report. Only transport/usage/verdicts and
new external authorization were synthetic. Public sources and copied historical
financial inputs came from the actual read-only checkpoint.

- **14 terminal jobs / 44 mock Messages / 44 mock paired counts**, ten complete
  draft/check/repair/recheck paths plus four probe batches. Copied cumulative
  programme totals **47 / 109 / 134**. The pre-programme funded baseline is
  excluded from the programme job counter, not silently discarded from money.
- Original **$0.425066** pending/unknown hold retained and counted once.
- All eight evaluation workflows mechanically complete in this simulation;
  generated mock claims **10**, below the required **20**, and **seven primary
  requests remain unanswered**. The quality verdict correctly remains **HOLD**.
  Mock positive checker verdicts establish no factual or token-fit evidence.
- Twenty predeclared machine-reference probe records: ten supported and ten
  unsupported, ten matched pairs, six shared passages. Both error directions
  are exercised by scoring tests; missing/invalid/abstaining verdicts retain
  their explicit denominators. There is no independent human gold or checker
  certification. [Locked references](machine-reference-set.json),
  [blinded checker payloads](blinded-checker-requests.json.gz).
- A separate disposable production-runner control actually progressed
  **failed Learn → ready comparison → ready evaluation**, preserving the failed
  response and its rejection. It did not replay it into a pass or stop unrelated
  cases. [Control receipt](CONTENT-CONTINUATION.json),
  [simulated raw results](CONTENT-CONTINUATION-RESULTS.json.gz).
- The separate bounded complete gate repeats a completed campaign and asserts
  zero duplicate dispatches. Its 14-job envelope is a CI command with a five
  minute bound; the existing per-test 60-second limit is unchanged.

[Final packet replay receipt](OFFLINE-REPLAY.json),
[readable simulated report](OFFLINE-REPORT-display.md),
[full simulated results](OFFLINE-RESULTS.json.gz).

## Safety and regression checks

The first focused campaign/scoring run passed **28 tests in 613.29s**. After
consolidating repeated fixture setup while retaining every mutation/assertion,
the operator/report and rollback-isolated drift controls passed **2 tests in
85.88s**. No pre-existing assertion, floor or tier was weakened.

Tests cover unapproved/partial receipt refusal, old limits before activation,
last allowed programme job/contact and refusal of the next, old-hold/contact/
source/predecessor drift, revocation/expiry, cross-scope exception borrowing,
oversized inputs, new uncertain completion, restart refusal without replay,
metered content failures, immutable outcome/accounting bindings, and unapproved
operator templates. The actual CLI paths export a false template, idempotently
record synthetic authorization in marked storage, recompute reports and revoke.
Fixture-only options refuse provider mode.

Ruff passes; strict mypy passes **213 source files**. Workflow E2E **53 pass**;
research simulation **20/20 at $0**; registry **260 objects / 0 mismatches**.
The final full-suite/patch coverage and package floors are recorded separately
after completion; local checks do not imply remote CI success.

## Audits and implementation review

[Preservation audit](PRESERVATION.json) confirms **287 original files** and the
entire original public/financial/scope/grant snapshot match their before hashes.
The live ledger remains **33 programme jobs / 65 Messages / 90 counts /
$1.853811 known estimated** plus the overlapping **$0.425066** hold. Owner3137,
review3178, old stopped scopes, failed responses and historical scores remain
untouched. The historical completion/billing remains unresolved.

Confirmed implementation findings were fixed before sealing: templates now
deep-copy packet objects; reports separate pipeline completion from quality
acceptance; programme job counts exclude only the original programme baseline;
and request-coverage rows use their actual rendered identifiers. The schema
cache contains only bounded pure model types keyed by the entire policy and
handles, with copied policy and fresh exported schemas. It caches no approval,
source, ledger, support verdict or other admission decision. Fresh full old-row,
predecessor/revocation, source and outcome audits run at each protected operation.

Earlier offline diagnostics are retained under
`outputs/d5/consolidated-campaign-v12/`. They exposed an invalid five-unit probe
context, a missing synthetic uncertainty binding, a report-key mismatch and
mock support abstentions. Fixtures/reporting were corrected, provenance and
quality gates retained. A whole sequential campaign exceeded the existing
single-test bound; it became its own bounded integration command rather than
raising the timeout or dropping any case. Real source data and original failed
provider outputs were not corrected or reclassified.

## Publication and remaining limits

The application commit above contains runtime code, tests and the bounded CI
gate. The later publication adds planning/evidence only. Final exact-head CI is
recorded by the owner handoff and local `outputs/d5/consolidated-campaign-v12/PUBLICATION.json`;
[branch Actions](https://github.com/kudratsingh/arxiv-research-agent/actions/workflows/ci.yml?query=branch%3Acodex%2Fworkspace-d5-campaign-complete)
is authoritative. No PR, merge or deployment.

The packet is prospective and unapproved. End-to-end questions are new but the
retained corpus is exposed, snapshot intake is not fresh, PDF samples have known
extraction limits, and machine labels/claims share sources. Human qualification,
owner usefulness and real provider token fit/latency/quality remain unmeasured.
Everyday generation, notifications and recurrence remain disabled.
