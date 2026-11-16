# Offline verification and inactive diagnostic runbook

Run from the durable `workspace-d5-consistency-v18` worktree. Set the locked
interpreter and disabled-key sentinel explicitly. No command here records real
approval or contacts a provider unless the separately marked future sequence is
used after matching external authority.

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export ANTHROPIC_API_KEY=local-preview-disabled
export PYTHONPATH="$PWD:/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps"
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
unset WORKSPACE_D5_V15_PARENT_SNAPSHOT
export WORKSPACE_D5_V15_ARCHIVED_PARENT_SNAPSHOT=/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/campaign-live-v14-20261114T000552Z/POST-STOP-LEDGER.json.gz
"$VENV_PYTHON" -c 'import src; print(src.__file__)'
"$VENV_PYTHON" -m pytest tests/test_workspace_consistency_contract.py tests/test_workspace_consistency_pipeline.py tests/test_workspace_d5_consistency_integration.py -v
make test-cov-diff VENV_PYTHON="$VENV_PYTHON"
```

The tests use isolated `ws_test_*` schemas, explicit synthetic authorization and
MockTransport. They reconstruct recorded historical charges as fixture data;
new mocked usage is zero spend. Test markers categorically forbid provider mode.
No live financial row, scope, grant or source record is changed.

The inherited storage guard requires the canonical local test database name
`workspace_d5_tests`. Each test creates and drops only its unique `ws_test_*`
schema; the public schema was verified empty. The active financial validation
ledger is a different database and is never used for write-based tests.

The two inherited parent consumers intentionally need different identities.
Production controls rebuild their synthetic parent with the existing
`prepare(..., authorize=False)` routine when the shared override is absent.
The optional historical controls compare exact archived v14 identities; the new
archive-specific test option supplies the preserved post-stop ledger only to
those controls. The old shared override remains backward compatible. Neither
fixture is an input to live authority, and neither changes the active 42/76/101
ledger. No assertion, guard, floor or historical identity was relaxed.

Initial local attempts mixed these inputs and failed the guard, layout or exact
identity checks. All attempts and synthetic candidate snapshots remain in
permanent evidence. Never edit or relabel a snapshot to satisfy an identity.

Packet-only verification and an **unapproved** external template:

```sh
PACKET=planning/15-evaluation-audit-and-recovery/evidence/consistency-v18/packet.json.gz
"$VENV_PYTHON" -m src.workspace.d5_compatibility verify --packet "$PACKET" --out outputs/d5/v18-verify-new.json
"$VENV_PYTHON" -m src.workspace.d5_compatibility template --packet "$PACKET" --out outputs/d5/v18-unapproved-template-new.json
```

Output paths must be new. The tool refuses to overwrite evidence. A blank
operator template cannot activate a scope, and a synthetic template cannot be
used in a provider database.

## Future execution, unexecuted

Only after the owner separately approves the exact four identities, packet,
application, limits, expiry and four historical quarantine bindings:

1. Reverify exact-head CI, source/SDK/schema/settings/request/price/evidence
   bindings, the single ledger census, stopped parent and all retained holds.
   Any drift stops activation. Do not reseal to bypass a mismatch.
2. Prepare a fresh external operator file from the template, with the actual
   owner decision, observed UTC receipt/expiry and historical exception true.
   `anticipated_received_rejection_continuation_approved` stays **false**.
   Record it through the existing operator, using the active validation ledger.
3. Load credentials only in that isolated experiment process without printing
   them. Keep every everyday/frontend environment disabled. Do not add an
   authentication call or standalone count pass.
4. Run once. Each named Messages call is immediately preceded by its exact
   same-model/body/settings count. Preserve all raw requests/responses/journals.

```sh
# FUTURE ONLY; requires a separately approved, externally completed file.
"$VENV_PYTHON" -m src.workspace.d5_compatibility record --packet "$PACKET" --authorization /absolute/private/owner-approved-v18.json --out /absolute/permanent/new-activation.json
"$VENV_PYTHON" -m src.workspace.d5_compatibility run --packet "$PACKET" --out /absolute/permanent/new-four-request-result.json
```

`D5_POSTGRES_URL` must point to the verified active qualification ledger, never
owner3137/review3178 or a fixture database. The runner does not create approval.

Order: Compact Learn → dependent Compact Research → independent small fixed
checker → dependent maximum fixed checker. A fully metered local failure remains
unavailable and skips its dependent case; an independent fixed checker can
continue. Any provider error, new uncertainty, drift, corrupt accounting, limit,
revocation, cancellation or expiry stops all dispatch. A grammar HTTP400 has no
new continuation exception and retains its full reservation. No retries, repairs,
replacement identities, full campaign or everyday generation are authorized.
