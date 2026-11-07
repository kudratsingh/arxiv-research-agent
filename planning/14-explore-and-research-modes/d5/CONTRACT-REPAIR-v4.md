# D5 v4 contract repair — offline, no renewed permission

Current source changes separate single-paper explanations from applicable Research comparisons. `ClaimId` is shared by claims and comparison_basis; transformed Research wire schemas carry its c1–c6 enum and explicit evidence-handle/claim-ID descriptions. Single-paper wire schemas have no comparison fields. Applicable Research requires at least two distinct selected works; two versions of one work do not suffice. Missing/duplicate basis references and invalid evidence relationships still fail locally.

The unchanged failed Stage B response and original exact request are [regression fixtures](../../../tests/fixtures/d5/stage-b-v3/README.md). Local original quarantined artifacts remain under outputs/d5/stage-b-20261106. A manually corrected response used in tests is synthetic and never a provider success. The stopped v3 scope is never renewed/replayed by these commands.

## Remaining quota and prospective identities

[Quota receipt](d5-quota-v4.json) binds the original programme authorization, original one-job baseline, current eight funded identities,10Messages/20counts and estimatedUSD0.125611. Programme usage is7/20 new jobs;13 remain, with70Messages/60counts andUSD9.874389 monetary headroom (USD8.874389 after preservingUSD1 uncertainty headroom). The failed Stage B job consumes one of the seven, even though no content was accepted.

V4 proposes two explicitly disclosed new qualification principals (`d5-v4-validation-run`, `d5-v4-validation-measure`) in the SAME preserved programme. The operator requires empty new principals and the exact full historical census before recording a new scope. Their use is prospective, explicitly approval-bound, and cannot reset the programme ledger or revive the stopped v3 identity. The snapshot excludes operative scope grants/policies; copied financial records are not permission. No provider-mode approval is created in this batch.

The same benchmark definitions, cohorts, ranking, sources and thresholds are retained for reproducibility. C/D are NOT proposed for execution: after two new development jobs only11 funded slots would remain, versus12 jobs in the original C/D schedule. The20-fact/20-probe minima are not reduced, and no additional cases or raised ceilings are authorized.

## Offline commands

Run from this worktree root; never run an external script with the wrong sys.path. All provider environments remain sentinel-disabled.

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export PACKET=planning/14-explore-and-research-modes/d5/d5-system-validation-v4.json.gz
$VENV_PYTHON -m src.workspace.d5_benchmark verify --packet "$PACKET"
$VENV_PYTHON -m pytest -q tests/test_workspace_d5_contract.py tests/test_workspace_d5_adapter.py tests/test_workspace_assistance.py tests/test_workspace_d5_benchmark.py tests/test_workspace_d5_reviews.py tests/test_workspace_d5_stage_grants.py
```

Use a fresh disposable DB with `d5-replay-inputs-v2.json.gz`, retaining the latest failed real identity and all accounting. The evidence command installs a fixture marker before synthetic authorization. It runs only A and B under the SAME protected adapter/admission, without live transport. The proposal contains future paid commands; none is run or approved here. A full `offline --stage all` with this history would eventually hit the real programme funded-job cap; do not remove historical jobs or raise the cap to make it green.

Initial measurements for the changed requests are unmeasured. v3 counts are historical, not v4 fit evidence. Response-dependent check/repair/recheck bodies/digests are frozen from their preceding synthetic outputs for offline evidence only; future provider outputs determine different exact bodies under the same bound templates.

## Publication gate

The final application/publication hashes, CI URL, exact result counts, failed intermediate checks and byte-bound evidence are appended after completion. Required floors/budgets and original browser assertions are preserved. Owner3137/review3178 are not used for writes. All changes remain unmerged and undeployed.

Prospective packet **`f21f4b66e1eb99ab75c7c242a9bfa46acb78ccabc13fb885477e8160425fd95a`**, application **`9bd25a82d313070e810038c8de42c0dc3d9cb8b1`**; approved=false. [Full identity receipt](d5-packet-identity.json).

## One executable fresh offline replay

The versioned tool installs only into an already-created, empty isolated database. It sets the permanent fixture marker before recording synthetic A/B permission, refuses a nonempty target/output directory, and calls the exact protected runner. It cannot read a credential or choose provider transport. Use another unique database/report name on later replays; do not delete or overwrite history.

```sh
# After choosing a NEW disposable DB name on the existing isolated PostgreSQL15488:
docker compose -p arxiv-d5-20261105 -f scripts/workspace-d5-compose.yml exec -T postgres psql -U workspace -d postgres -v ON_ERROR_STOP=1 -c 'CREATE DATABASE workspace_d5_contract_v4_repro;'
ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1 PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD $VENV_PYTHON - --database workspace_d5_contract_v4_repro --out outputs/d5/contract-v4-repro < planning/14-explore-and-research-modes/d5/evidence/contract-repair-v4/tools/offline-ab.py
```

This copied-ledger simulation's contact census includes mock contacts; `actual_new_provider_contacts=0` is the relevant execution fact. It never replaces the real active10/20/$0.125611 ledger.

Stable local gate:6536passed/54inherited skips,97%patch; all package floors pass. [Full evidence index](evidence/contract-repair-v4/README.md). Remote exact-head CI is recorded in outputs/d5/contract-repair-v4/FINAL-PUBLICATION.json.
