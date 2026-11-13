# V14 verification and future campaign commands

No command or false template grants its own authority. Owner3137/review3178 stay
unchanged. Everyday generation, recurrence and notifications remain disabled.

## Offline replay — runnable without approval

Run from the dedicated permanent worktree. The shared interpreter is not modified.
Use the existing disposable test database only; the helper enforces its database
name and creates a unique schema. Keep each output directory new and permanent.

```sh
cd /Users/kudratsingh/Machine-Learning-Projects/arxiv-workspaces/workspace-d5-provider-contract-repair
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export PYTHONPATH="$PWD:/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps"
export D5_PACKET=planning/15-evaluation-audit-and-recovery/evidence/provider-contract-v14/packet.json.gz
export D5_EVIDENCE=/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-provider-contract-repair-20261113
export WORKSPACE_TEST_POSTGRES_URL='postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests'

"$VENV_PYTHON" -c 'import sys,src; print(sys.version); print(src.__file__)'
"$VENV_PYTHON" -m src.workspace.d5_campaign verify --packet "$D5_PACKET"
"$VENV_PYTHON" -m pytest tests/test_workspace_assistance_compact_draft.py tests/test_workspace_assistance_compact_checks.py tests/test_workspace_d5_v14_extension_controls.py tests/test_workspace_d5_v14_independent_controls.py -q
"$VENV_PYTHON" -m pytest tests/test_workspace_d5_v14_integration.py tests/test_workspace_d5_v14_production_controls.py -q

# A NEW directory is required. The exact original snapshot stays immutable.
"$VENV_PYTHON" - --packet "$D5_PACKET" \
  --snapshot "$D5_EVIDENCE/baseline/FINAL-READONLY-LEDGER.json.gz" \
  --out "$D5_EVIDENCE/owner-offline-replay-new" \
  < planning/15-evaluation-audit-and-recovery/tools/replay-sealed-campaign-v14.py
```

The same production campaign/admission/provider adapter runs 14 jobs and the maximum
44 Messages/44 paired counts using MockTransport and synthetic external authority.
Raw reports are retained before schema teardown. A second invocation within the
same fixture dispatches nothing. Fake counts, usage and verdicts demonstrate
software behavior, not remote schema acceptance, actual token fit or checker quality.
The copied real baseline and both original liabilities are verified unchanged.

For a new offline freeze, `python -m src.workspace.d5_campaign freeze-v14 --packet
<new-path> --snapshot <captured-path>` is explicit and requires disposable fixture
storage plus the sentinel/OFFLINE pins. Do not re-freeze or tune this packet after
examining its future evaluation outputs. Old `freeze` retains its original behavior.

## Future operator and live runner — UNEXECUTED

The owner must approve [the exact consolidated request](APPROVAL-REQUEST.md),
including the proposed dollar/capacity adjustment and both separately identified
liability exceptions. Select the existing single active ledger from the permanent
active-ledger receipts: workspace_d5_prose_v6_validation. Do not reseed, fork or
replay a stopped scope. Recheck all packet/code/source/schema/settings bindings,
35/68/93 census, both holds, official pricing and expiry before activation.

Use the current operator mechanism. The copied template remains false until an
externally attributed real owner authorization is supplied. Neither the runner
nor this package creates that authority. The existing local credential may be
loaded only into that separately authorized qualification process, never printed
or copied into artifacts, daily services or verification environments.

```sh
# UNEXECUTED: D5_POSTGRES_URL must name the existing active ledger.
# D5_OWNER_AUTHORIZATION is a separately supplied, matching owner receipt.
"$VENV_PYTHON" -m src.workspace.d5_campaign_operator record \
  --packet "$D5_PACKET" --authorization "$D5_OWNER_AUTHORIZATION" \
  --receipt "$D5_NEW_ACTIVATION_RECEIPT"
"$VENV_PYTHON" -m src.workspace.d5_campaign run \
  --packet "$D5_PACKET" --out "$D5_NEW_QUARANTINED_OUTPUT"
```

Do not carry the offline sentinel/OFFLINE environment into an approved provider
process; use a fresh isolated process configured by the operator. Do not test a key
with an unrelated smoke request. There is no standalone preliminary-count pass.
Each real Messages request automatically receives its own exact-body/model/settings
paired token-count estimate and must fit the 16,000-input allowance. Dynamic check,
repair and recheck requests derive from actual preceding outputs under frozen
contracts; their exact bodies and digests are journaled when created.

Remote compiler acceptance and complete final checker output must be demonstrated
for BOTH development identities before evaluation/probes. A valid negative quality
verdict remains a failed result and does not become accepted content. The historical
`pipeline_contract_accepted` outcome field follows the ready-state bit; the new
development progression uses the stronger independently recomputed complete-response
binding, not that bit or a provisional positive claim decision.

The prospective qualification policy uses$12 cumulative and$12 daily/monthly
ceilings, all confined to this exact programme and separately approved scope.
These ceilings are inactive; the existing$10 limits remain unchanged.
The maximum is 14 jobs/44 Messages/44 counts/$7.50 new; $0.65 per workflow and
$0.25 per probe batch. Concurrency one, Sonnet output4,000, Opus adaptive High
output8,000 including thinking. Counts/drafts/repairs30s, checks/rechecks120s,
workflow480s. No retries. Stop on broken development contract, provider error or
new uncertainty, drift/corruption, exhaustion, expiry/revocation or cancellation.
Fully metered evaluation content failures can continue unrelated frozen cases.

Expected successful-run duration is approximately30–60minutes; the sum of maximum
contact deadlines is80minutes, with workflow envelopes/local work allowing about
90–100minutes. These are planning estimates, not measurements or guarantees. Any
hard stop may end the run sooner. Check remaining expiry before proposing execution.
No deadline is extended by this packet.

All rights reserved. No license or reuse permission is granted.
