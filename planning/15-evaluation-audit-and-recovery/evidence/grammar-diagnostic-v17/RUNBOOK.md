# Diagnostic runbook

This revision is offline preparation. Do not run `record` or `run` against
the active ledger until the exact matching owner authorization is received.
The command cannot approve itself.

From the application worktree:

```bash
cd /Users/kudratsingh/Machine-Learning-Projects/arxiv-workspaces/workspace-d5-grammar-diagnostic
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH="$PWD:/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps"
export ANTHROPIC_API_KEY=local-preview-disabled
"$VENV_PYTHON" -c 'import src; print(src.__file__)'
P=planning/15-evaluation-audit-and-recovery/evidence/grammar-diagnostic-v17/packet.json.gz
"$VENV_PYTHON" -m src.workspace.d5_compatibility verify --packet "$P" --out /Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-grammar-diagnostic-20261115/new-offline-verification/VERIFY-unique.json
```

Choose an unused output path; existing reports are never overwritten.
The import must resolve to this worktree. Before any future dispatch, also run
`"$VENV_PYTHON" -c 'import anthropic, pydantic, jsonschema'` in the locked
qualification environment. jsonschema is an existing locked dev/qualification
tool, not a new runtime dependency or an everyday API requirement.
Old measurements cannot establish fit for these changed requests.

## Offline production-path verification

Use an isolated Postgres test database, never the owner's workspace database:

```bash
export WORKSPACE_TEST_POSTGRES_URL='postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests'
export D5_TEST_EVIDENCE_DIR='/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/d5-grammar-diagnostic-20261115/new-offline-verification'
"$VENV_PYTHON" -m pytest tests/test_workspace_d5_compatibility.py tests/test_workspace_compact_encoding.py tests/test_workspace_grammar_archives.py -q
```

The tests create independent disposable schemas, mark them offline-only, use
synthetic authority and MockTransport, and preserve fixture exports before
cleanup. They do not read a key or contact the provider. The six-case canonical
replay report is in the permanent evidence archive's FINAL-OFFLINE-REPLAY folder.
Its 44/78/103 census is a copied financial checkpoint plus **synthetic** contacts,
not the active ledger. Actual counts, remote compilation and quality are unmeasured.

## After separately receiving the exact approval

1. Verify final-head CI, git/source/SDK/packet/request bindings and the active
   ledger read-only. Recheck official standard prices; stop on drift.
2. Save the owner's actual approval and observed UTC receipt time in a new
   permanent live-run evidence directory. Derive its absolute expiry without
   extending programme authority.
3. Export the inactive template to a new file:
   `python -m src.workspace.d5_compatibility template --packet "$P" --out <new-template.json>`.
   An operator must fill it from that external approval, including owner
   attribution, receipt/expiry, owner/provider kind and both explicitly approved
   quarantine flags. Never copy a synthetic fixture authorization.
4. Verify D5_POSTGRES_URL resolves through the single active qualification-ledger
   pointer. Do not reseed, migrate, settle holds, or use owner3137/review3178.
5. Record authority only through the explicit operator command:
   `python -m src.workspace.d5_compatibility record --packet "$P" --authorization <owner-record.json> --out <new-record-receipt.json>`.
   This inserts the new diagnostic scope/policies only after exact read-only
   baseline checks. No migration or capacity/expiry change is required.
6. Load the already configured credential into only the approved experiment
   process using the existing protected local procedure. Do not print it, commit
   it, screenshot it or add an authentication smoke call. Keep frontend/everyday
   environments on the disabled sentinel.
7. Dispatch the sealed sequence:
   `python -m src.workspace.d5_compatibility run --packet "$P" --out <new-live-report.json>`.
   JSON, Markdown and HTML reports retain separate outcome axes. Each Message
   has its own exact paired count. The runner cannot create authority and refuses
   any previously started identity; a restart is inspection, never blind replay.
8. Preserve complete and partial bodies, journals, count/usage receipts and a
   read-only post-run census. Count holds once. Stop for review. Any later
   evaluation campaign needs a separate exact compatible encoding and grant.

A received grammar rejection is not proof of zero billing. Only the narrowly
explicit anticipated rejection policy may continue; new uncertain completion
always stops. Raw responses, prose, quotes and JSON are never truncated into a
pass. Fully metered invalid content remains failed; known usage is independent
of acceptance. No everyday Reader generation is enabled.

Revocation uses the existing operator utility
`src.workspace.d5_authorization.revoke(store, scope_id)` for this exact compat
scope. Its active-state fence is checked again before count and Message dispatch
and after a response. Revocation never erases contacts or releases an uncertain
hold. No revocation or new live authority is recorded during this preparation.
