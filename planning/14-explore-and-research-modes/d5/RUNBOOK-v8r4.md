# D5 v8r4 capacity extension and qualification runbook

**Superseded unapproved preparation candidate.** Use [v8r4b](RUNBOOK-v8r4b.md). The original insufficient-case fixture diagnostic and raw mock report are preserved; no provider contact or live authority occurred.

**Offline implementation only. No cap, A/B/C/D grant or paid contact is authorized
by this file. Never copy fixture receipts into a live ledger.**

Packet `e6c6fac53aa32aba010fe1b484de0e7a8415593e62772d4405ec4fa14fd7c131`.
Application `05a12c76bc5ce8903fede1ba71937897fe21f386`.
Capacity proposal `8d699885e58d228f00fe2a9edadd13a14f4d7d58b54393875bd6f3693b7e34dc`.
[Proposal](PAID-VALIDATION-PROPOSAL-v8r4.md), [verification](evidence/qualification-v8r4/VERIFICATION.md).

## Offline verification and reproduction

Work from the isolated worktree root. The local dependency overlay is the
previously recovered offline overlay; no shared venv installation was performed.
On another machine use the repository's locked environment with matching packet
runtime dependency versions. A package/source mismatch must stop verification.

```sh
cd /private/tmp/arxiv-agent-eng-programme-capacity
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-calibration-preflight-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export PACKET=planning/14-explore-and-research-modes/d5/evidence/qualification-v8r4/packet.json.gz

$VENV_PYTHON -c 'import src; print(src.__file__)'
$VENV_PYTHON -m src.workspace.d5_benchmark verify --packet "$PACKET"
$VENV_PYTHON -m ruff check .
$VENV_PYTHON -m mypy src
WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests \
  $VENV_PYTHON -m pytest tests/test_workspace_programme_capacity.py \
  tests/test_workspace_programme_third_amendment.py \
  tests/test_workspace_programme_successors.py tests/test_workspace_programme_amendments.py -q
WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests \
  make test-cov-diff VENV_PYTHON="$VENV_PYTHON"
```

The following **actual offline replay command** was run against a newly created
empty disposable database. It installs the complete historical financial replay,
marks storage permanently provider-disabled, records only synthetic capacity/stage
receipts there, and uses the same production admission/adapter/journal/scorer.
Transport/counts/usage/verdicts are mocked; every workflow deliberately takes
one repair and mandatory recheck to exercise the full contact reservation.

```sh
D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_capacity_replay_20261108_v1 \
  $VENV_PYTHON - replay \
  --snapshot outputs/d5/capacity-extension/private/FINANCIAL-REPLAY-PRIVATE.json.gz \
  --packet "$PACKET" --out outputs/d5/capacity-extension/final-replay \
  < planning/14-explore-and-research-modes/d5/tools/prepare-capacity-v8.py
```

Do not overwrite or rerun that fixture identity. For a fresh mechanical replay,
create a new empty `workspace_d5_*` database on isolated port 15488 and select a
new output directory. Existing/nonempty stores and artifact paths are refused.
The helper never imports a snapshot into the active ledger. Its only active
connection is explicitly read-only, verifying 20/35/54/USD 0.904053, no pending or
unknown liability, the still-active 24/80/80 limits and both old scopes stopped.

The original private snapshot remains mode 0600 under a mode 0700 directory;
it contains locked prereview proofs and must not be published. Its digest and
producer command are in [the attestation](evidence/qualification-v8r4/GENERATOR-ATTESTATION.json).
No owner notes, reading history, drafts or newly read preferences are imported.
The corpus/clock are retained; this is not fresh intake or extraction qualification.

The final freeze was prepared in another empty disposable database:

```sh
D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_capacity_freeze_20261108_v1 \
  $VENV_PYTHON - prepare \
  --snapshot outputs/d5/capacity-extension/private/FINANCIAL-REPLAY-PRIVATE.json.gz \
  --packet planning/14-explore-and-research-modes/d5/evidence/qualification-v8r3/packet.json.gz \
  --out planning/14-explore-and-research-modes/d5/evidence/qualification-v8r4 \
  < planning/14-explore-and-research-modes/d5/tools/prepare-capacity-v8.py
```

This command now refuses those existing paths. Re-preparing with new paths/time
creates a different prospective packet; it does not inherit an old approval.
The v8r3 artifact is preserved as a predecessor and its old producer binding is
intentionally unsuitable for executing against the new code.

## Separate decision 1: capacity activation — NOT EXECUTED

Review [the exact proposal](evidence/qualification-v8r4/CAPACITY-PROPOSAL.json) and
[copyable capacity-only request](evidence/qualification-v8r4/CAP-ACTIVATION-APPROVAL-REQUEST.md).
It is approved=false. A valid activation must independently bind the original
programme, all three predecessor receipts, sealed 20/35/54 census and unchanged
expiry. Current caps stay 24/80/80 until the owner separately approves this step.

Only after that explicit approval, reverify the single active ledger pointer at
`/private/tmp/arxiv-agent-eng-workspace-assistance/outputs/d5/ACTIVE-QUALIFICATION-LEDGER.json`.
Use its existing `workspace_d5_prose_v6_validation` database and independently
supplied owner receipt. Never restore/reseed a checkpoint into that database.
The conditional operator entry point is:

```sh
# After explicit matching cap-only approval, not during this offline batch:
D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_prose_v6_validation \
  $VENV_PYTHON -m src.workspace.programme_capacity record \
  --program-id research-evaluation-20261105-v1 \
  --receipt outputs/d5/v8r4-live/OWNER-CAP-RECEIPT.json
```

It records a new version-4 receipt; no prior row/expiry is overwritten. No provider
key/contact is needed for cap activation. Return its actual authorization digest
and stop. It creates no stage scope or funded workflow permission.

## Separate decision 2: Stage A — NOT EXECUTED

After cap review, use [the A-only request](evidence/qualification-v8r4/STAGE-A-APPROVAL-REQUEST.md)
and [exact A scope](evidence/qualification-v8r4/STAGE-A-SCOPE.json). No old count
receipt matches; measure-1 is the one initial dev-compare Sonnet request. The
published operator template is approved=false and has no approval time/expiry.
Do not turn it into an owner receipt without a new explicit A approval.

Only after A approval: verify active capacity receipt, producer/dependency/source/
model/settings/schema/request bindings, current ledger 20/35/54/USD 0.904053 and
expiry. Prepare only the frozen public contexts for the isolated v8 principals
using the existing retry-safe `d5_fixture.prepare_projects` helper. Do not import
financial fixtures, private notes, preferences, review proofs or history into context.
The following context-preparation command is conditional on that A approval;
it grants nothing and makes no provider contact. It refuses a fixture database,
a missing capacity activation or a changed ledger before writing public contexts:

```sh
# After explicit A approval; never seed financial rows into this active ledger:
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_prose_v6_validation
$VENV_PYTHON - <<'PYCONTEXT'
import os
from pathlib import Path
from src.workspace.d5_benchmark import database, read
from src.workspace.d5_fixture import prepare_projects
from src.workspace.d5_freeze import verify
from src.workspace.programme_amendments import effective_limits
from src.workspace.qualification_budget import census
from src.workspace.store import WorkspaceStore
packet = read(Path(os.environ["PACKET"]))
verify(packet)
with database(os.environ["D5_POSTGRES_URL"]) as pool:
    with pool.connection() as conn:
        assert not conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone()
        members = sorted(row[0] for row in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
            (packet["program_id"],)))
        assert census(conn, members[0], members=members) == packet["history"]
        assert effective_limits(conn, packet["program_id"], required_proposal_digest=
            packet["programme_amendment"]["proposal_digest"]) == {
            "new_jobs": 34, "messages": 80, "counts": 99, "usd": "10", "concurrency": 1}
    prepare_projects(WorkspaceStore(pool), packet)
PYCONTEXT
```

Record the externally supplied A-only receipt, then use the established isolated
credential loader without printing the value or adding it to argv/history/artifacts.
Use only the approved count call to validate access; never an authentication smoke.

```sh
# After explicit A approval, active cap, context preparation and secure loader:
$VENV_PYTHON -m src.workspace.d5_operator record \
  --packet "$PACKET" --receipt outputs/d5/v8r4-live/OWNER-A-RECEIPT.json
$VENV_PYTHON -m src.workspace.d5_benchmark run \
  --packet "$PACKET" --stage A --out outputs/d5/v8r4-live-A/results
```

These paid-stage commands also require the existing active-ledger D5_POSTGRES_URL
and approved execution environment. The offline sentinel environment above must
never be silently switched by the runner. One count, zero Messages/funded jobs/
new spend. Stop at any binding/authentication/admission/provider/uncertain failure;
no retry or alternate identity. Return actual measurement and stop for B review.

## Separate decision 3: Stage B — NOT EXECUTED

After successful A and separate review, use [the conditional B request](evidence/qualification-v8r4/STAGE-B-APPROVAL-REQUEST.md)
and [B scope](evidence/qualification-v8r4/STAGE-B-SCOPE.json). Expected ledger:
20 jobs / 35 Messages / 55 counts / USD 0.904053, pending/unknown zero. Verify the
actual A receipt, active amendment and unexpired/unrevoked parent. The B template
can only be made against that real parent; do not fabricate its future digest.

```sh
# Only after real A and the owner's separate B decision:
$VENV_PYTHON -m src.workspace.d5_operator stage-template \
  --packet "$PACKET" --stages B --receipt outputs/d5/v8r4-live/B-TEMPLATE.json
$VENV_PYTHON -m src.workspace.d5_operator grant \
  --packet "$PACKET" --receipt outputs/d5/v8r4-live/OWNER-B-RECEIPT.json
$VENV_PYTHON -m src.workspace.d5_benchmark run \
  --packet "$PACKET" --stage B --out outputs/d5/v8r4-live-B/results
```

Run dev-learn then dev-compare, one job/call at a time. At most 2 jobs, 8 Messages,
8 exact paired counts, USD 0.45/job and USD 0.90 total; mandatory check, at most
one repair and mandatory recheck. Every actual stage must fit its measured input
allowance. Source/settings/schema drift, invalid content, accounting mismatch,
provider errors or uncertain completion stop the scope; preserve all receipts.
A valid repairable first-check finding may only take the predeclared one repair.
Residual invalid/unscored prose still rejects. No adaptive retries or substitution.

Return both development outcomes, actual usage, costs and liabilities. Human
judgments stay blank. Stop before separately approved C or D; development cannot
fill held-out minimums. Recurrence, notifications and everyday generation stay off.
