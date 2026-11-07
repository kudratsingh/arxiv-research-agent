# D5 v4 offline verification and prospective validation

Current unapproved packet `f21f4b66e1eb99ab75c7c242a9bfa46acb78ccabc13fb885477e8160425fd95a`; application `9bd25a82d313070e810038c8de42c0dc3d9cb8b1`. **No provider/count calls in this repair batch.** V3 Stage B remains stopped at dev-learn; current live accounting10Messages/20counts/estimatedUSD0.125611, pending/unknown0. The actual blank human worksheet and historical failures are unchanged.

Read [the contract repair runbook](CONTRACT-REPAIR-v4.md), [offline quality report](OFFLINE-QUALITY.md), [future-only approval proposal](PAID-VALIDATION-PROPOSAL.md), and [exact request bindings](evidence/contract-repair-v4/prospective-requests.json). The [v3 runbook](RUNBOOK-v3.md) is historical: its old requests do not match the new producer or prove v4 fit.

```sh
cd /private/tmp/arxiv-agent-eng-workspace-assistance
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export PACKET=planning/14-explore-and-research-modes/d5/d5-system-validation-v4.json.gz
$VENV_PYTHON -c 'import pathlib,src; print(pathlib.Path(src.__file__).resolve())'
$VENV_PYTHON -m src.workspace.d5_benchmark verify --packet "$PACKET"
```

Prepared isolated offline DB`workspace_d5_contract_v4_offline` has a permanent fixture marker and synthetic A/B-only authorization. Its mock counts/usage are not real measurements or spend. Provider mode is forbidden there. The separate unmarked prospective DB`workspace_d5_contract_v4_validation` has zero policies/scopes/grants; it is NOT the active stopped ledger.

Use a new offline report directory for read-only export. No runner or authorization writer is required:

```sh
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_contract_v4_offline
$VENV_PYTHON -m src.workspace.d5_benchmark report --packet "$PACKET" --out outputs/d5/contract-v4-readonly
```

For a fresh reproducible offline replay, create a new disposable D5-prefixed DB on15488, initialize it with `d5-replay-inputs-v2.json.gz` and `--offline-fixture`, explicitly authorize only A/B with `src.workspace.d5_fixture.authorize_fixture(..., stages=("A","B"))` in that marked DB, then run `offline --stage A` and `offline --stage B` with distinct output directories. The same protected adapter and programme ledger enforce capacity. Do not run all stages: current history plus the original whole schedule exceeds the unchanged programme job cap.

All reviews remain versioned sidecars; use [the importer](HUMAN-REVIEW-RUNBOOK.md) with the exact original v4 result/packet. Do not label a synthetic corrected draft as a successful provider response or copy synthetic labels into real worksheets. Owner3137/review3178 remain untouched; recurrence, notifications and everyday generation remain disabled. Publication and CI evidence are linked in the repair runbook when complete.
