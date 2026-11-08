# D5 v7r2 historical operator runbook

**STOPPED:** v7r2 Stage C remains 3/8. The commands below are historical, not permission to resume. Use the [current offline repair/calibration runbook](RUNBOOK-v8.md) and [separate review proposal](QUESTION-PREMISE-CALIBRATION.md). No new authority is recorded by this update.

Application `f430f2d3e7a3a7ae78cacdf92855b8b3294d3c12`; packet `cf6b9e4c1e49d0192467bd28d0bae00eb1d05cf85bb850f904902840937fc871`. [Proposal and separate decisions](PAID-VALIDATION-PROPOSAL.md), [contract/limits](RESPONSE-REPAIR-v7.md). [Historical v6 instructions](RUNBOOK-v6.md) require their old source checkout and grant; they are not current permission.

## Offline commands — no provider credential needed

From the worktree root:

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled
export PACKET=planning/14-explore-and-research-modes/d5/d5-system-validation-v7r2.json.gz
export SNAPSHOT=planning/14-explore-and-research-modes/d5/d5-replay-inputs-v7.json.gz
export SUCCESSOR=planning/14-explore-and-research-modes/d5/programme-job-amendment-v3.json
$VENV_PYTHON -c 'import src; print(src.__file__)'
$VENV_PYTHON -m src.workspace.d5_benchmark verify --packet "$PACKET"
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
$VENV_PYTHON -m pytest -q tests/test_workspace_d5_gap_repair.py tests/test_workspace_programme_third_amendment.py
make test-cov-diff VENV_PYTHON="$VENV_PYTHON"
make test-e2e VENV_PYTHON="$VENV_PYTHON"
make simulate-research VENV_PYTHON="$VENV_PYTHON"
$VENV_PYTHON -m src.contracts.registry parity
```

Full replay needs a **new empty disposable database** on isolated15488; create it through the existing local Postgres operator, never delete/reuse owner or historical databases. Then:

```sh
export WORKSPACE_D5_OFFLINE=1
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_gap_v7_replay_new
$VENV_PYTHON - replay --packet "$PACKET" --snapshot "$SNAPSHOT" \
  --successor "$SUCCESSOR" --out outputs/d5/gap-v7-replay-new \
  < planning/14-explore-and-research-modes/d5/tools/prepare-gap-v7.py
unset WORKSPACE_D5_OFFLINE
```

The script permanently marks the disposable database provider-disabled, imports unchanged public/financial history, mirrors both already-recorded cap receipts, and creates explicitly synthetic24-job and A/B permissions. Synthetic dev verdicts deliberately exercise failure→repair→recheck success. C without its own grant must refuse; only a separately marked synthetic C/D grant completes the replay. Human reviews stay blank. The original abstaining-fixture refusal remains separate evidence. Mock counts are100, never claimed as actual token fit; synthetic verdicts are not independent support labels. The fixture database can never become the live validation ledger.

Frontend: from `web/`, run `npm run typecheck`, `npm run lint`, `npm test -- --run --coverage --maxWorkers=2`, and `npm run budgets`. Local socket/process permissions are required by existing healthcheck/E2E tests. Tests, timeouts, coverage floors and route budgets are unchanged. Existing previews use preserved standalone runtime copies.

## Future operator sequence — UNEXECUTED; separate approval required

Keep the single active isolated ledger at `workspace_d5_prose_v6_validation` and its stopped v6 scope. Do not initialize/reseed it, switch to a fixture DB, copy synthetic authority, load a key for a smoke call, or use an old authorization for this packet.

1. Read `outputs/d5/ACTIVE-QUALIFICATION-LEDGER.json`; verify current census exactly matches the sealed10 jobs/17 Messages/35 counts/USD0.351961, pending/unknown0 and original receipts. Confirm original v6 scope remains stopped, packet/code/evidence/settings match, and fixture marker is absent. Any drift stops this sequence.
2. Only after explicit owner approval of the separate22→24 proposal, record the externally supplied amendment receipt in this same isolated ledger. This adds no workflow permission or contacts and preserves Nov13,23:24:01 PST expiry. Do this before any new counts; the proposal binds the35-count census.
3. Only after explicit A approval, prepare the new isolated principals and project rows from this frozen packet, without altering existing records. A safe preparation pattern is shown below. Record the externally supplied A-only receipt through the operator; never mutate `approved=false` without the corresponding owner instruction.
4. Run only A: one new `measure-1` for Compare. Stop for owner review. All old A receipt identities remain historical; no reused fit claims.
5. Only after separate B approval, export a B stage template, record the independently supplied grant with the original parent expiry, and run B. Learn then Compare,2 jobs/8 Messages/8 exact paired counts,USD0.45/job/USD0.90 total. Stop for review. No C/D permission follows.

```sh
# UNEXECUTED. Keep the sentinel for preparation and operator recording.
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_prose_v6_validation
$VENV_PYTHON -m src.workspace.programme_third_amendment record \
  --program-id research-evaluation-20261105-v1 \
  --receipt outputs/d5/owner-approved-amendment-v3.json

# Only after explicit A approval: prepare new principals/projects, never overwrite.
$VENV_PYTHON - <<'PY'
import os
from psycopg.types.json import Jsonb
from src.workspace.d5_benchmark import database, read, check_storage
from src.workspace.d5_fixture import prepare_projects
from src.workspace.d5_freeze import verify, RUN_OWNER, COUNT_OWNER
from src.workspace.qualification_budget import census
from src.workspace.store import WorkspaceStore
from pathlib import Path
p=read(Path(os.environ['PACKET'])); verify(p)
with database(os.environ['D5_POSTGRES_URL']) as pool:
    store=WorkspaceStore(pool); check_storage(store,p)
    with pool.connection() as c:
        assert not c.execute('SELECT 1 FROM workspace_d5_fixture_marker').fetchone()
        members=[r[0] for r in c.execute('SELECT owner FROM workspace_evaluation_members WHERE program_id=%s',(p['program_id'],))]
        assert census(c,members[0],members=members)==p['history']
        assert c.execute("SELECT state FROM workspace_d5_scopes WHERE scope_id='d5-7e21713caee474fbafa31d19'").fetchone()[0]=='stopped'
        for owner in (RUN_OWNER,COUNT_OWNER):
            row=c.execute('SELECT data FROM workspace_profiles WHERE owner=%s',(owner,)).fetchone()
            if row: assert row[0]==p['profile']
            else: c.execute('INSERT INTO workspace_profiles VALUES(%s,1,%s)',(owner,Jsonb(p['profile'])))
    prepare_projects(store,p)
PY
$VENV_PYTHON -m src.workspace.d5_operator record --packet "$PACKET" \
  --receipt outputs/d5/owner-approved-v7-A.json
# The operator mechanism may now load the configured credential without display.
# Do not put a key value in a command or file generated by this workflow.
$VENV_PYTHON -m src.workspace.d5_benchmark run --packet "$PACKET" --stage A \
  --out outputs/d5/v7-stage-A-approved
# STOP for owner review. The following commands require a later B-only approval.
$VENV_PYTHON -m src.workspace.d5_operator stage-template --packet "$PACKET" \
  --stages B --receipt outputs/d5/v7-B-template.json
$VENV_PYTHON -m src.workspace.d5_operator grant --packet "$PACKET" \
  --receipt outputs/d5/owner-approved-v7-B.json
$VENV_PYTHON -m src.workspace.d5_benchmark run --packet "$PACKET" --stage B \
  --out outputs/d5/v7-stage-B-approved
```

The real credential is read only by an approved execution process, never displayed, logged, committed, passed as a CLI argument or used in unrelated auth tests. Keep everyday/frontend environments on the sentinel. Pricing/request/producer drift, expired/revoked authority, count over16000, contract/provider/accounting failure, cancellation or unknown completion stops the scope. No automatic retry or alternate request identity. Exact dynamic check/repair/recheck requests derive from actual preceding outputs and are journalled when created.

Expiry cannot exceed **2026-11-14T07:24:01Z**. A parent scope may use a shorter owner-selected expiry; appended grants cannot extend it. Future C and D require their own reviewed decisions. The programme retainsUSD10,80/80 contacts, concurrency1, all8 C cases/4 D batches and unchanged quality minimums. This offline successor renews no previous approval.
