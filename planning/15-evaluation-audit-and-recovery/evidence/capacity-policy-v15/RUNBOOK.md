# D5 v15 offline verification and future operator commands

Run from the permanent worktree. Do not install into the shared interpreter.
Every output directory must be new. Existing artifacts and grants stay unchanged.

```sh
cd /Users/kudratsingh/Machine-Learning-Projects/arxiv-workspaces/workspace-d5-capacity-policy
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export PYTHONPATH="$PWD:/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps"
export D5_PACKET=planning/15-evaluation-audit-and-recovery/evidence/capacity-policy-v15/packet.json.gz
export D5_EVIDENCE=/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-capacity-policy-20261114
export WORKSPACE_TEST_POSTGRES_URL='postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests'
"$VENV_PYTHON" -c 'import src; print(src.__file__)'
"$VENV_PYTHON" -m src.workspace.d5_campaign verify --packet "$D5_PACKET"
"$VENV_PYTHON" -m pytest tests/test_workspace_assistance_capacity_contract.py tests/test_workspace_d5_capacity_policy.py tests/test_workspace_d5_capacity_outcomes.py tests/test_workspace_d5_capacity_selection.py -q
"$VENV_PYTHON" -m pytest tests/test_workspace_d5_v15_integration.py tests/test_workspace_d5_v15_production_controls.py tests/test_workspace_d5_v15_extension.py -q
"$VENV_PYTHON" - --packet "$D5_PACKET"  --snapshot "$D5_EVIDENCE/baseline/READONLY-LEDGER-v1.json.gz"  --out "$D5_EVIDENCE/owner-offline-replay-new"  < planning/15-evaluation-audit-and-recovery/tools/replay-sealed-campaign-v15.py
```

The helper validates the disposable database name, creates one unique schema,
installs copied public inputs and immutable financial history, and uses synthetic
fixture authority plus MockTransport through actual admission, adapter and journal.
All rows export before teardown, even on assertion failure. It exercises14jobs,
44mockMessages and44mockcounts with full repair/recheck; duplicate invocation sends
nothing. Its fake usage/counts/positive judgments prove no scientific quality,
remote grammar acceptance or real token fit. Both original holds remain unchanged.

The offline packet preparer is executable via python - < planning/15-evaluation-audit-and-recovery/tools/prepare-sealed-campaign-v15.py
--snapshot <preserved-census> --out <NEW-directory>. Preparing another candidate
cannot replace this frozen packet or grant authority. Do not reseal after seeing
future campaign outputs.

## Future live commands — UNEXECUTED and unauthorized

Only a new external owner receipt matching APPROVAL-REQUEST may activate this
package. Use the single existing ledger workspace_d5_prose_v6_validation selected
by the active-ledger receipt. Never fork/reseed it or load test fixture authority.
Reverify exact bindings and census36/70/95, known2.110597, both holds0.875066,
current prices, no new uncertainty and explicit deadlines before activation.

After the separately recorded owner approval, apply the exact bound additive020
qualification migration with WorkspaceStore.migrate() on this existing ledger
only. It creates the successor receipt/revocation storage; this batch has NOT run
it there. Reverify the census after migration before recording the grant.

Use a separate isolated qualification process. Its credential must never be
printed or copied to artifacts, daily workspace or verification processes. Opening
Reader/request preview cannot dispatch. Do not add an authentication smoke call.
Do not carry the offline sentinel/OFFLINE pins into an approved provider process.

```sh
# UNEXECUTED: set these only AFTER the matching external owner approval.
# D5_POSTGRES_URL must select the existing active qualification ledger.
# D5_OWNER_AUTHORIZATION is the actual attributed owner receipt, not a fixture.
# UNEXECUTED: apply only the bound additive migration after owner approval.
"$VENV_PYTHON" - <<'MIGRATION'
import os
from pathlib import Path
from urllib.parse import urlsplit
from src.workspace.d5_benchmark import database, read
from src.workspace.d5_freeze import verify
from src.workspace.store import WorkspaceStore
verify(read(Path(os.environ["D5_PACKET"])))
url = os.environ["D5_POSTGRES_URL"]
assert urlsplit(url).path == "/workspace_d5_prose_v6_validation"
with database(url) as pool:
    with pool.connection() as conn:
        existing = {r[0] for r in conn.execute("SELECT revision FROM workspace_schema")}
    available = {path.stem for path in Path("src/workspace/migrations").glob("*.sql")}
    assert available - existing in ({"020_d5_capacity_campaign"}, set())
    WorkspaceStore(pool).migrate()
MIGRATION
# Preflight: absent receipt file and an existing writable parent directory.
"$VENV_PYTHON" - "$D5_NEW_ACTIVATION_RECEIPT" <<'RECEIPT'
import os, sys
from pathlib import Path
path = Path(sys.argv[1])
assert not path.exists() and path.parent.is_dir()
assert os.access(path.parent, os.W_OK)
RECEIPT
"$VENV_PYTHON" -m src.workspace.d5_campaign_operator record  --packet "$D5_PACKET" --authorization "$D5_OWNER_AUTHORIZATION"  --receipt "$D5_NEW_ACTIVATION_RECEIPT"
"$VENV_PYTHON" -m src.workspace.d5_campaign run  --packet "$D5_PACKET" --out "$D5_NEW_QUARANTINED_OUTPUT"
```

If record fails, inspect the append-only database activation/scope before any
repeat: recording precedes receipt-file writing. A write error does not prove
nothing activated. Preserve the exact receipt identity; never renew, reseed or
construct alternate authority to hide partial activation.

All fourteen identities run sequentially under one scope with automatic exact
count→fit→Messages admission. Maximum14/44/44/$14 new; workflow$1.20, probe$0.50.
Proposed programme64/160/200/$20 and daily/monthly$20 remain inactive. Explicitly
record a new programme expiry ≤7days after approval and campaign expiry ≤24hours;
old stopped grants remain closed. Sonnet8k, OpusHigh12k outputs include thinking;
reserve40kinput, require pairedcount≤32k. Counts60s, drafts/repairs120s,
checks/rechecks240s, workflow1200s from its durable origin. No retry or fifthcall.

Both development paths need remote schema acceptance and complete bound checks
before evaluation/probes. Valid negative quality remains failed but may continue
unrelated cases. Broken contracts/capacity, provider error/new uncertainty, drift,
corruption, exhaustion, cancellation/revocation/expiry stop dispatch. Preserve
partial/full receipts, failed content, validated usage and unknown liability
separately. Do not clear either historical hold or replay stopped jobs.

Human qualification, everyday generation, recurrence and notifications remain
disabled. Owner3137/review3178 stay untouched. No merge or deployment.

All rights reserved. No license or reuse permission is granted.
