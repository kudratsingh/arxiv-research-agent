# V15 verification and remaining limits

Runtime application: `c5b859cc22abe7b66fec562881ba274d4eef9afc`. Test-only
corrections: `a5842a0f` and `92285759`; no runtime producer or packet binding changes.
Packet: `243e225ec32bcc882c502af56f0131e19fe6fd87d2fac1a20ea4f1e55b7a2665`.
[Machine-readable gates](LOCAL-GATE-RECEIPT.json) bind actual log hashes.

## Final local result

The entire unchanged non-e2e selection ran with context instrumentation via
`make test-cov-diff VENV_PYTHON=...` plus term/permanent-XML reports. Actual summary:

```
7730 passed, 62 skipped, 53 deselected in 2480.33s (0:41:20)
Required test coverage of 89.0% reached. Total coverage: 94.38%
Total:   13013 lines
Missing: 476 lines
Coverage: 96%
```

All four unchanged package gates reread that same complete coverage database:
API88≥86, agents96≥92, security100≥97, eval95≥91 (printed percentages). No source
input, assertion, marker selection, floor or budget was reduced. The62local skips
include8private-archive controls; those ran separately against preserved real rows
and the complete extension module passed42/42. Existing optional environment skips
and remote runner's different available integrations must be reported separately.
The53E2E tests excluded from coverage passed in their separate Make tier.

Initial full `make test-cov` and patch runs failed three test-harness assertions:
two modules lacked explicit unit tiers, and a pre-017 fixture removed020tables but
retained020's marker. Their source tests were repaired with every original
assertion preserved. An early rerun was interrupted after discovering the tier
errors; its unrelated redaction test also hit a random UUID containing5432. A
deterministic public correlation ID now removes that false alarm while preserving
all raw-body/header leak checks and adding an ID assertion. Complete marker
preflight3/3 and changed-module/API controls40/40 pass. Every failed/interrupted
log and coverage database remains retained. The final full selection above is
the successful replacement, not a claim that the first Make invocation passed.

Strict mypy:230source files, success. Ruff and whitespace checks pass. Separate
research simulation20/20USD0; registry260objects/0mismatches.

Frontend:222files/4294tests; coverage statements98.17, branches94.28,
functions94.15, lines99.52percent; all existing thresholds pass. ESLint and
TypeScript pass. Production build and all unchanged route budgets pass. Today
first-load168225bytes against169984; Reader164307against169984. The isolated
build checkout and its original report remain preserved. No CSS or JS ceiling
was raised. The placeholder-origin egress failure was fixed. A lazy Reader test
exceeded its state wait under competing local build/test load; its unchanged
30test diagnostic passed, followed by the complete suite with bounded2workers.
Both failing and passing runs remain in evidence; no assertion or timeout changed.

## Actual pipeline and Reader proof

The exact frozen packet replayed14synthetic jobs/44Messages/44paired counts through
production admission, adapter, contact journal, cumulative accounting, persistence,
current-response report binding and the final report. Every workflow exercised
repair/recheck. Duplicate invocation dispatched nothing. Both historical holds
remain unchanged. The offline counts/usage/verdicts are synthetic; machine quality
is forciblyHOLD. Byte observations: request72027maximum, raw output27201,
normalized50132;44complete HTTP bodies were losslessly rehashed. See the separate
[replay](OFFLINE-REPLAY-RECEIPT.json), [size](SIZE-OBSERVATIONS.json) and
[regression/custody](REGRESSION-AND-CUSTODY-RECEIPT.json) receipts.

The preserved original v14 draft plus a checker derivative changing only revision
reached completed draft/check steps with unchanged104/110/82/87/92character
reasons. Its p1uncertainty still required repair. It was not accepted or credited
as a new provider success, and the historical original remainsFAILED.

16selection/receipt controls prove12coherent units across persisted26000character
material, legacy caps, quote/hash/offset drift refusal, consistent trimming, exact
received-byte retention for invalidUTF8/NUL, atomic storage and immutable retries.
21protected controls cover Learn/Research negative quality, final recheck failure,
wrong evidence/digests, missing verdicts, truncation/max_tokens, HTTP400, budget
refusal, cancellation/restart/new uncertainty and partial-body timeout/byte bounds.
They reran inside the final full selection. Independent machine review found no
unresolvedP1/P2 issue; [read review](INDEPENDENT-REVIEW.md) is not formal proof.

The c5b production browser check used stubbed APIs and blocked external traffic:
desktop/mobile×light/dark displayed all12complete claims and the complete reason
(994Unicode codepoints/996UTF16code units), exact citation anchor, and a420character
reference-note request. It did not persist browser writes, render the unavailable
source-material fixture, or exercise browser retry/durable reopen. Postgres
persistence and browser rendering remain separate evidence. Screenshots/trace:
`arxiv-evidence/d5-capacity-policy-20261114/browser-capacity-v3/`.

## Exact-head remote CI and custody

Local success is not hosted CI. The final published commit's nine-job workflow,
job conclusions, logs and artifact checksums are recorded in the permanent
publication receipt and the completion handoff. The workflow is dispatched on
the published branch, with the sentinel and no provider secret. Only its aggregate
Python bound changes45→60minutes, based on predecessor35m57s plus new controlled
replay/failure work; a parsed workflow comparison confirms all other gate fields,
steps, per-test bounds, selections and floors remain identical.

Permanent root: `arxiv-evidence/d5-capacity-policy-20261114/`. Raw failed/passing
outputs and test-row exports are retained there, including the exact original
v14 response regression and copied-ledger controls. All27v13 and48v14manifest
files verify unchanged. Current read-only census at03:00:15UTC matches the sealed
snapshot exactly, with migration020absent and no financial/authority mutation.

## What remains provider-dependent

Offline validation cannot establish remote schema grammar compilation, actual
paired token fit, complete OpusHigh thinking/verdict output within12ktokens/240s,
scientific support, checker reliability or personal usefulness. Exact paired
counts and both complete bound development paths gate future cohort progression.
The eight evaluation controls are exposed, and20machine references are correlated
and proposed, not independent human gold. Existing thresholds/minimums remain;
missing denominators stayUNSCORED/HOLD. Human qualification stays outside scope.

The sole future decision is [the consolidated request](APPROVAL-REQUEST.md):
new14/44/44/$14 scope; programme64/160/200/$20, daily/monthly$20, explicit≤7day
programme/≤24hour campaign expiry and both untouched holds. No authority is
activated here. Everyday generation, recurrence, notifications and owner previews
remain unchanged. No merge or deployment.

All rights reserved. No license or reuse permission is granted.
