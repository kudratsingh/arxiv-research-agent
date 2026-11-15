# Offline replay and future protected campaign commands

Run only from the permanent worktree with the lock-exact interpreter. Every report directory and fixture database must be new; never reseed an existing database or overwrite evidence. The snapshot path below is private local preserved public-context/financial history, not an authorization to copy owner notes or use a real key.

```sh
cd /Users/kudratsingh/Machine-Learning-Projects/arxiv-workspaces/workspace-d5-keyed-contract
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH="$PWD:/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps"
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export D5_PACKET=planning/15-evaluation-audit-and-recovery/evidence/keyed-contract-v16/packet.json.gz
export D5_EVIDENCE=/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-keyed-contract-20261114
"$VENV_PYTHON" -c 'import src; print(src.__file__)'
"$VENV_PYTHON" -m src.workspace.d5_campaign verify --packet "$D5_PACKET"
```

Create an explicitly new local fixture database before this invocation. `D5_POSTGRES_URL` must select that empty owned fixture database, never the active qualification ledger or an owner workspace database. The offline installer irreversibly marks fixture storage so the production provider path refuses it. The sentinel and offline flag are mandatory; the same protected adapter, admission, journal, normalization and scoring paths run with injectable MockTransport.

```sh
# Set D5_POSTGRES_URL to a NEW empty owned local disposable fixture database.
"$VENV_PYTHON" -m src.workspace.d5_campaign offline   --packet "$D5_PACKET"   --snapshot "$D5_EVIDENCE/FINAL-SNAPSHOT-V16.json.gz"   --out "$D5_EVIDENCE/owner-offline-replay-NEW"   --fixture-repair-all
```

The published replay used `workspace_d5_keyed_replay_r5_20261114` and `canonical-offline-replay-v16r5/`. Those existing artifacts are read-only evidence; do not rerun into them. The replay exercises all14jobs/44mockMessages/44mockcounts, forces every workflow's single quality repair and mandatory recheck, exports results and preserves every complete HTTP body in durable ledger snapshots. Mock usage/counts are not provider token measurements; fake positive support verdicts establish no factual quality. Current quality stays HOLD with blank human labels.

For a portable synthetic-policy complete gate, set `WORKSPACE_TEST_POSTGRES_URL` to an owned local `/workspace_d5_tests` database or omit it with local `initdb`/`pg_ctl` available. The gate creates one unique schema and exports its rows to the new output directory before teardown.

```sh
"$VENV_PYTHON" -m tests.d5_keyed_gate --out "$D5_EVIDENCE/portable-gate-NEW"
```

Focused regressions: `python -m pytest tests/test_workspace_assistance_keyed_contract.py tests/test_workspace_assistance_keyed_checks.py tests/test_workspace_d5_keyed_transport.py tests/test_workspace_d5_keyed_prompts.py tests/test_workspace_d5_v16_integration.py -q`. The last module needs an isolated local `WORKSPACE_TEST_POSTGRES_URL` whose database path is `/workspace_d5_tests` and exports test rows via `D5_TEST_EVIDENCE_DIR` before teardown. Required broader gates are recorded separately; full pytest must not inherit WORKSPACE_D5_OFFLINE because legacy opt-in/opt-out controls need their own environment.

## Future live sequence — UNEXECUTED, requires matching external owner approval

Use only the single active qualification ledger selected by the permanent ACTIVE-QUALIFICATION-LEDGER pointer (`workspace_d5_prose_v6_validation`). Reverify full census, both original holds, exact source/code/schema/settings/reference/answerability bindings, programme expiry, no active jobs and published-head CI. Do not load fixture authorization or snapshot-install this database. Opening a request preview cannot dispatch.

Generate a blank external-operator template (this does not approve it):

```sh
"$VENV_PYTHON" -m src.workspace.d5_campaign_operator template   --packet "$D5_PACKET" --authorization "$D5_EVIDENCE/owner-template-NEW.json"
```

Only after the matching owner approval, populate approval attribution/time/source and campaign expiry≤24hours after receipt and≤2026-11-21T11:03:57Z, keeping every immutable template binding unchanged. No budget/expiry/cap amendment field exists in this successor. Set historical_uncertainty_exception_approved only from the matching explicit approval. Preserve the actual receipt separately, not in the public repo.

After that approval only, apply021 on the existing ledger using the below bound-migration preflight. No migration has been applied there by this repair:

Before copying the future record/run sequence, use the separately approved qualification process, remove its offline/sentinel overrides and load its credential privately without printing it. Keep daily-workspace/frontend/test processes disabled. Do not perform these steps during offline preparation. Verify exact published-head CI and a clean tree first. This ordering clarification changes no request or authorization.

```sh
# UNEXECUTED. Requires the matching owner approval and the active ledger URL.
"$VENV_PYTHON" - <<'MIGRATION'
import os
from pathlib import Path
from urllib.parse import urlsplit
from src.workspace.d5_benchmark import database, read
from src.workspace.d5_freeze import verify
from src.workspace.store import WorkspaceStore
verify(read(Path(os.environ["D5_PACKET"])))
url = os.environ["D5_POSTGRES_URL"]
assert urlsplit(url).hostname in {"127.0.0.1", "localhost"}
assert urlsplit(url).path == "/workspace_d5_prose_v6_validation"
with database(url) as pool:
    with pool.connection() as conn:
        existing = {r[0] for r in conn.execute("SELECT revision FROM workspace_schema")}
    available = {p.stem for p in Path("src/workspace/migrations").glob("*.sql")}
    assert available - existing in ({"021_d5_keyed_continuation"}, set())
    WorkspaceStore(pool).migrate()
MIGRATION
# Reverify unchanged financial/source census; ensure NEW receipt/output paths.
"$VENV_PYTHON" -m src.workspace.d5_campaign_operator record   --packet "$D5_PACKET" --authorization "$D5_OWNER_AUTHORIZATION"   --receipt "$D5_NEW_ACTIVATION_RECEIPT"
"$VENV_PYTHON" -m src.workspace.d5_campaign run   --packet "$D5_PACKET" --out "$D5_NEW_QUARANTINED_OUTPUT"
```

Before any actual provider run, remove only the offline/sentinel overrides in the separately approved qualification process and load its credential privately without printing it. Daily-workspace/frontend/test processes remain disabled. No unrelated authentication smoke call or preliminary count pass. Never retry automatically. A receipt-write error after record may mean activation already committed: inspect the append-only ledger before doing anything again; never construct a replacement identity or renewal. On a stop, preserve all journal/raw/accounting records and do not restart the stopped scope.

The executable `run` automatically performs exact paired count→fit→Messages per stage. Dynamic checker/repair requests are created only from actual preceding outputs under the frozen templates, then journalled with exact body/settings/schema digests. No future response-dependent request is fabricated in the packet. Two valid development response contracts are required before evaluation/probes. Invalid first drafts remain terminal; only the existing completed negative-check branch may use one repair followed by mandatory recheck.

Human qualification and everyday generation/recurrence/notifications remain disabled. No merge or deployment.

All rights reserved. No license or reuse permission is granted.

Before any future live activation, also require the exact returned published commit and a clean tracked/untracked worktree (`git status --porcelain` empty). The packet automatically verifies the enumerated87producer hashes and adapter dependencies; the exact published-head/clean-tree check additionally protects the surrounding checkout. Do not treat an older CI run on a different commit as this package's verification.
