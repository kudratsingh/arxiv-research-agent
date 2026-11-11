# Coverage authority v10 — offline successor

Application `3c94e566228e6dc536518887e93c41d8832f8478`. Packet `880e4794cd08d26a4a9e63231d5d0d82ec99a267e65ff60dfc5f0994875fb864`. Scope `d5-880e4794cd08d26a4a9e6323`.
[Bindings](evidence/coverage-authority-v10/BINDINGS.json), [packet](evidence/coverage-authority-v10/packet.json.gz), [immutable-regression receipt](evidence/coverage-authority-v10/REGRESSION.json).

## Contract

New HTTP previews/submissions and the prospective qualification case use
`workspace-assistance-coverage-authority-v10`. Coverage alone names each part's
`answer_claim_ids` and `context_claim_ids`. Generated claims reject `part_ids`
under both the exact SDK-transformed schema and local shape model. The server
computes `claim_request_index`, preserving answer/context roles separately in
Reader output and checker input. This index is derived from validated coverage,
never accepted as model-authored authority, relevance or semantic support.

Unique IDs, referenced-ID existence, no orphans, duplicates or per-part role
overlap remain mandatory. Answered/evidence-gap/omitted wire branches and their
gap enums remain distinct. Full abstention omits claims and references.
Comparison-only context never answers the comparison. Sealed intent, requested
priority, six claims/8000 bytes, exact selected evidence and quotation/version/
offset checks remain. Every factual claim is subject to whole-claim support,
atomicity and qualification checks; every requested part and all procedural prose
remain checked. One repair requires a mandatory recheck; residual failures stop.

V8/v9 schemas, wire instructions and replay validators retain their original
semantics. The archived v9 draft still fails `request_part_claim_binding_mismatch`:
p3 context references c4/c5 but both claims name only p2. Its original text,
response, financial settlement and stopped identity remain unchanged and failed.
The new committed archive retains the original body, exact text SHA256 and
receipt identity. A separately labelled synthetic fixture deletes only
`claims.part_ids`; it receives no provider success or human-quality credit.

## Offline proof

The fixture derives c4/c5 as answer roles for p2 and context roles for p3.
p3 remains `lacks_evidence`, not an accepted protocol answer. Tests exercise that
fixture through production admission/adapter and mandatory checker dispatch.
A separate synthetic checker decision rejects a result incorrectly used as
an answer; one repair and recheck still fail if the misclassification remains.
Wrong references, orphans, duplicate claims/references, overlapping roles, status
conflicts, seven claims, priority violations, comparison-only context and full
abstention are tested. Existing new-request boundary and quality/prose regressions
now pin v10; legacy-specific tests remain on their archived versions.

Use the lock-exact Python from this worktree root; never run an external script
path that changes sys.path[0]. Tests use disposable Postgres schemas, the sentinel
and mocked transport. No real key is read.

```bash
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
export PYTHONPATH=/private/tmp/arxiv-calibration-preflight-deps:$PWD
"$VENV_PYTHON" -m pytest -q tests/test_workspace_coverage_authority.py tests/test_workspace_coverage_authority_runner.py tests/test_workspace_request_boundary.py tests/test_workspace_coverage_adapter.py tests/test_workspace_coverage_shapes_runner.py
"$VENV_PYTHON" -m src.workspace.d5_benchmark verify --packet planning/14-explore-and-research-modes/d5/evidence/coverage-authority-v10/packet.json.gz
```

Full private financial replay uses the already captured public/financial snapshot
in `outputs/d5/coverage-authority-v10/SNAPSHOT-BEFORE.json.gz`. A new **empty**
loopback database must have a name beginning `workspace_d5_`; do not reset an
existing one or use the live ledger. The CLI permanently marks it offline and
records synthetic A/B authority only there:

```bash
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_coverage_authority_v10
"$VENV_PYTHON" -m src.workspace.d5_coverage_replay replay \
  --snapshot outputs/d5/coverage-authority-v10/SNAPSHOT-BEFORE.json.gz \
  --packet planning/14-explore-and-research-modes/d5/evidence/coverage-authority-v10/packet.json.gz \
  --out outputs/d5/coverage-authority-v10/replay-new
```

A one-count fixture runs first; B without a separate fixture grant is refused.
The explicitly synthetic B grant then permits draft/check/repair/recheck. Mock
counts and verdicts establish control flow, never real token fit or quality.

## Separate unexecuted validation proposal

Baseline32 funded jobs/63Messages/87counts/USD1.828877estimated; pending/unknown0.
Effective caps34jobs/80Messages/99counts/USD10/concurrency1 are unchanged.
Expiry remains2026-11-14T07:24:01Z. Existing stopped scopes stay closed. No real
provider/count contacts, live grants, new spend or cap changes are made here.
Human qualification, StageD and everyday generation remain out of scope;
recurrence/notifications disabled; owner3137/review3178 untouched.

| Stage | Cases | New jobs | Messages max | Counts max | New cost ceiling |
|---|---|---:|---:|---:|---:|
| A, separate approval | measure-1 | 0 | 0 | 1 | USD0 |
| B, separate later approval | development-v10-learn-coverage | 1 | 4 | 4 | USD0.45 |

Maximum cumulative33jobs/67Messages/92counts/USD2.278877estimated.
Historical estimates remain estimates, not invoice confirmation. The complete
four-stage conservative route reservation is USD0.448, rounded to the unchanged
USD0.45 ceiling: Sonnet input2/output10 per million, Opus input4/output20 per
million, sealed rates verified2026-11-06. At the enforced16000 input allowance
and output caps4000/3200, the four-call usage bound is USD0.400. These are bounds,
not measured predictions. HistoricalUSD1.828877 + proposedUSD0.45 + retainedUSD1
buffer = USD3.278877, belowUSD10. No prices or settings are changed.

Sonnet5.5 adaptive/medium drafts and repair; Opus5.5 adaptive/high check/recheck.
Maximum4Messages,4paired counts,14400total output tokens. Counts must measure
the exact actual stage body/model/settings and fit16000 before Messages.
Mandatory check, at most one repair then mandatory recheck; no retries,
substitutions, source expansion or alternate identities. Stop on drift,
provider/contract/admission failure or uncertain completion. Failed/uncertain
contacts consume capacity; invalid completed content is accounted separately.

One fresh StageA request is needed: `80fb9cb6f20ee54c95a2bd77ee93c6115bb4c34e8644fe8eeb30ab77e3766f08`.
V9's84086fe7 count cannot establish fit for this changed prompt/schema. No old
measurement is reused. B's later count/check/repair bodies depend on the actual
preceding output under sealed templates and are journaled when derived.

[A-only approval request](COVERAGE-AUTHORITY-A-APPROVAL-REQUEST.md) and
[B-only later request](COVERAGE-AUTHORITY-B-APPROVAL-REQUEST.md) are proposals,
not permission. The operator mechanism remains separate from the runner:

```bash
# Only AFTER separate A approval, with the sentinel still set:
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_prose_v6_validation
PACKET=planning/14-explore-and-research-modes/d5/evidence/coverage-authority-v10/packet.json.gz
"$VENV_PYTHON" -m src.workspace.d5_operator prepare --packet "$PACKET" --receipt outputs/d5/coverage-authority-A/PREPARED.json
"$VENV_PYTHON" -m src.workspace.d5_operator template --packet "$PACKET" --stages A --receipt outputs/d5/coverage-authority-A/A-template.json
# Independently approved owner A receipt, NEVER copied from fixtures:
"$VENV_PYTHON" -m src.workspace.d5_operator record --packet "$PACKET" --receipt outputs/d5/coverage-authority-A/OWNER-A.json
# Only the isolated qualification process may then securely load the configured key.
"$VENV_PYTHON" -m src.workspace.d5_benchmark run --packet "$PACKET" --stage A --out outputs/d5/coverage-authority-A/result
# STOP for review. Only AFTER separate B approval and fresh ledger verification:
"$VENV_PYTHON" -m src.workspace.d5_operator stage-template --packet "$PACKET" --stages B --receipt outputs/d5/coverage-authority-B/B-template.json
"$VENV_PYTHON" -m src.workspace.d5_operator grant --packet "$PACKET" --receipt outputs/d5/coverage-authority-B/OWNER-B.json
"$VENV_PYTHON" -m src.workspace.d5_benchmark run --packet "$PACKET" --stage B --out outputs/d5/coverage-authority-B/result
```

Commands cannot dispatch with the sentinel; no command creates its own approval.
Each prospective grant expires at the earliest of24hours from receipt, the
existing parent expiry if any, and the programme expiry. Live ledger drift is a
refusal, not a reason to overwrite/reseed history. Full gates, exact-head CI and
preservation receipts are recorded in [verification](evidence/coverage-authority-v10/VERIFICATION.md).
