# Offline verification and future protected execution

Run from the permanent worktree. Never overwrite an evidence/output directory or reseed an existing database. Retain every predecessor. Use the lock-exact interpreter; measure from the worktree with -c, a heredoc, or python - < file.

```sh
cd /Users/kudratsingh/Machine-Learning-Projects/arxiv-workspaces/workspace-d5-union-compatibility
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH="$PWD:/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps"
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export D5_PACKET=planning/15-evaluation-audit-and-recovery/evidence/keyed-contract-v16r2/packet.json.gz
export D5_EVIDENCE=/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-union-compatibility-20261115
export D5_SNAPSHOT=/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-keyed-contract-20261114/FINAL-SNAPSHOT-V16.json.gz
"$VENV_PYTHON" -c 'import src; print(src.__file__)'
"$VENV_PYTHON" -m src.workspace.d5_campaign verify --packet "$D5_PACKET"
```

Set D5_POSTGRES_URL to a NEW empty owned local disposable fixture database. Never install a snapshot or synthetic authorization in the active ledger or owner data. The offline installer irreversibly marks fixture storage so the real provider path refuses it.

```sh
"$VENV_PYTHON" -m src.workspace.d5_campaign offline --packet "$D5_PACKET" --snapshot "$D5_SNAPSHOT" --out "$D5_EVIDENCE/owner-offline-replay-NEW" --fixture-repair-all
```

The verified canonical fixture uses workspace_d5_union_replay_20261115 and canonical-replay-v16r2. Do not rerun into either. It exercises14jobs/44mockMessages/44exact mockpairedcounts, including every workflow's single repair and mandatory recheck. All88actual SDK request bodies and final current-response bindings were verified. Synthetic counts/support/usage establish software behavior, not token fit or provider quality; quality remains HOLD, human fields blank.

Portable complete production-shaped synthetic gate, with a fresh output directory and owned local WORKSPACE_TEST_POSTGRES_URL ending /workspace_d5_tests (or local initdb/pg_ctl available):

```sh
"$VENV_PYTHON" -m tests.d5_keyed_gate --union-safe --out "$D5_EVIDENCE/portable-union-gate-NEW"
"$VENV_PYTHON" -m pytest tests/test_workspace_provider_schema_compat.py tests/test_workspace_assistance_keyed_encoding.py tests/test_workspace_d5_union_integration.py -q
```

The integration tests preserve fixture rows under D5_TEST_EVIDENCE_DIR before teardown. Required full coverage must NOT inherit WORKSPACE_D5_OFFLINE, because existing opt-in/opt-out tests exercise both modes. The disabled key remains mandatory. No pip changes to the shared lock-exact venv.

## Future live sequence — UNEXECUTED, requires the exact matching external owner approval

The only active ledger is workspace_d5_prose_v6_validation, identified by the permanent ACTIVE-QUALIFICATION-LEDGER pointer. Do not reseed it or replay stopped identities. Reverify a clean tracked/untracked worktree at the exact returned published commit and all9green CI checks,89producer/71adapter hashes, packet/source/version/material/span/schema/settings/reference/answerability/scoring bindings, programme expiry, full financial census, both unchanged holds and no active job/new uncertainty. The actual guard runs on final transformed bodies before paired count/Messages.

Generate an unapproved operator template (this grants nothing):

```sh
"$VENV_PYTHON" -m src.workspace.d5_campaign_operator template --packet "$D5_PACKET" --authorization "$D5_EVIDENCE/owner-template-NEW.json"
```

Only after matching owner approval, fill its attribution/time/source, approved flag and exact historical-exception approval. Campaign expiry must be at most24hours after observed approval and no later than2026-11-21T11:03:57Z. Preserve every immutable binding. This successor contains no capacity/budget/expiry renewal. Save the owner's actual approval and resulting receipt privately; never copy fixture authorization.

BEFORE the future migration/record/run block: use only the separately approved qualification process, remove its offline/sentinel overrides, and load its credential privately without printing or logging it. Keep owner/frontend/test environments disabled. These credential steps and every following mutation are unexecuted during preparation. Verify the clean exact published head and complete read-only census again.

Only matching future approval permits additive021 on the active ledger. It is byte-identical to the predecessor migration, not applied live during this repair:

```sh
# UNEXECUTED: matching owner approval and active-ledger URL required.
"$VENV_PYTHON" - <<'MIGRATION'
import os
from pathlib import Path
from urllib.parse import urlsplit
from src.workspace.d5_benchmark import database, read
from src.workspace.d5_freeze import verify
from src.workspace.store import WorkspaceStore
verify(read(Path(os.environ["D5_PACKET"])))
url=os.environ["D5_POSTGRES_URL"]
assert urlsplit(url).hostname in {"127.0.0.1", "localhost"}
assert urlsplit(url).path == "/workspace_d5_prose_v6_validation"
with database(url) as pool:
    with pool.connection() as conn:
        existing={r[0] for r in conn.execute("SELECT revision FROM workspace_schema")}
    available={p.stem for p in Path("src/workspace/migrations").glob("*.sql")}
    assert available-existing in ({"021_d5_keyed_continuation"},set())
    WorkspaceStore(pool).migrate()
MIGRATION
# Reverify unchanged census; use NEW activation receipt/output paths.
"$VENV_PYTHON" -m src.workspace.d5_campaign_operator record --packet "$D5_PACKET" --authorization "$D5_OWNER_AUTHORIZATION" --receipt "$D5_NEW_ACTIVATION_RECEIPT"
"$VENV_PYTHON" -m src.workspace.d5_campaign run --packet "$D5_PACKET" --out "$D5_NEW_QUARANTINED_OUTPUT"
```

The single run automatically performs exact model/body/settings count→fit≤32000→Messages for every stage. No preliminary standalone count pass. Dynamic schemas and current-response input digests are recorded when derived. Both development contracts must complete before evaluation/probes. A fully metered valid negative quality result stays failed quality and may permit unrelated cases to continue; contract/provider/binding/accounting/capacity failures, NEW uncertainty, cancellation, revocation or expiry stop dispatch. No retry, replacement identity or stopped-scope replay. A record receipt-write failure can occur after DB commit: inspect the append-only ledger rather than repeating activation blindly.

Everyday generation, recurrence and notifications remain disabled. Human qualification outside scope. No merge/deployment.

All rights reserved. No license or reuse permission is granted.
