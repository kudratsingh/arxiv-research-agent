# D5 v6 offline runbook and future approval boundary

No command in this document supplies approval. The v5 scope stays stopped. The real ledger remains `workspace_d5_contract_v4_validation`; do not switch its active pointer during offline verification. Provider keys are unnecessary for all offline commands.

## Reproduce the sealed complete schedule

Run from the worktree root, with imports resolving here. Use a **new empty disposable database** on the isolated15488 cluster; do not reuse owner data or an existing report directory.

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export PACKET=planning/14-explore-and-research-modes/d5/d5-system-validation-v6r2.json.gz
export SNAPSHOT=planning/14-explore-and-research-modes/d5/d5-replay-inputs-v5.json.gz
export SUCCESSOR=planning/14-explore-and-research-modes/d5/programme-job-amendment-v2.json
$VENV_PYTHON -c 'import src; print(src.__file__)'
$VENV_PYTHON -m src.workspace.d5_benchmark verify --packet "$PACKET"
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_prose_v6_replay_new
$VENV_PYTHON - replay --packet "$PACKET" --snapshot "$SNAPSHOT" \
  --successor "$SUCCESSOR" --out outputs/d5/prose-repair-v6-replay-new \
  < planning/14-explore-and-research-modes/d5/tools/prepare-prose-v6.py
```

This installs retained public context and immutable financial history, mirrors the original recorded20→21 receipt byte-for-byte, and confines **synthetic**22-job and A–D permissions to a permanent fixture-marked database. Production admission, journal, exact counts, adapter, mandatory checker, bounded repair/recheck and scoring are exercised using MockTransport. Fixture storage cannot become a provider validation database; never remove its marker or copy its synthetic authorization.

The mirrored original receipt remains expiry-bound: replay also refuses after Nov13 23:24:01 PST rather than editing or extending that receipt.

The alternative `--development learn-only` uses `d5-system-validation-v6r2-learn-only.json.gz`, a different new empty database/report directory, and no successor activation. It funds only dev-learn and preserves eight C cases/four D batches under21. Do not run both alternatives against the paid programme.

## Focused and full offline gates

```sh
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
$VENV_PYTHON -m pytest -q tests/test_workspace_d5_prose_repair.py \
  tests/test_workspace_programme_successors.py tests/test_workspace_programme_amendments.py \
  tests/test_workspace_d5_adapter.py tests/test_workspace_d5_opus.py
unset WORKSPACE_D5_OFFLINE
make test-cov-diff VENV_PYTHON="$VENV_PYTHON"
make test-e2e VENV_PYTHON="$VENV_PYTHON"
make simulate-research VENV_PYTHON="$VENV_PYTHON"
$VENV_PYTHON -m src.contracts.registry parity
```

Module-scoped fixtures set the mock opt-in themselves. Leaving it unset globally exercises refusal paths as CI does. Frontend: `cd web`, then `npm run typecheck`, `npm run lint`, `npm test -- --run --coverage`, `npm run budgets`. Local socket access is required by existing healthcheck tests.

## Review preview

http://localhost:3195/workspace/today?mode=learn uses disposable `workspace_d5_prose_v6r2_offline`, API8195 and principal `d5-v6-validation-run`. Results are explicitly simulated/quarantined. Open the supplied result links in the evidence index, inspect a scored claim, follow its exact retained passage, return to Understand, explicitly save a simulated thread/project note, and reload/resume through Library. All writes affect the disposable principal only. Existing3137/3178/3193/3194 are preserved.

## Future operator commands — UNEXECUTED, separate approval required

The candidate amendment and packet are **approved=false**. First obtain owner review. Do not use a fixture DB, old stopped scope, expired authority or synthetic receipt. A future approved handoff needs a new **unmarked** validation DB, full census/checkpoint comparison with the single active ledger, and preservation of all prior job/result/contact records. If the live census differs from the sealed8 jobs/12 Messages/26 counts/USD0.196359, stop and produce a new reviewed binding rather than reseeding history.

After an independently approved handoff and21→22 amendment, these commands show the production path. They have not been run. Use the separately controlled credential mechanism only for approved execution; no key value belongs in a command, receipt or report.

```sh
# Future new unmarked database only, after explicit owner approval of the handoff.
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_prose_v6_validation
$VENV_PYTHON -m src.workspace.d5_benchmark init --packet "$PACKET" --snapshot "$SNAPSHOT"
# Independently supplied, owner-approved successor receipt; never the synthetic one.
$VENV_PYTHON -m src.workspace.programme_successors record \
  --program-id research-evaluation-20261105-v1 --receipt outputs/d5/owner-successor-v2.json
# Export a blank A-only template (no approval is created).
$VENV_PYTHON -m src.workspace.d5_operator template --packet "$PACKET" \
  --receipt outputs/d5/owner-v6-stage-a-template.json --stages A
# Only after explicit A-only approval and an independently completed receipt:
$VENV_PYTHON -m src.workspace.d5_operator record --packet "$PACKET" \
  --receipt outputs/d5/owner-v6-stage-a.json
# Four named counts only; requires approved provider credential environment.
$VENV_PYTHON -m src.workspace.d5_benchmark run --packet "$PACKET" --stage A \
  --out outputs/d5/v6-stage-a
# STOP and return counts/bindings for review; no automatic B execution.
# Only after a separate explicit B-only approval, preserving parent expiry:
$VENV_PYTHON -m src.workspace.d5_operator stage-template --packet "$PACKET" \
  --receipt outputs/d5/owner-v6-stage-b-template.json --stages B
$VENV_PYTHON -m src.workspace.d5_operator grant --packet "$PACKET" \
  --receipt outputs/d5/owner-v6-stage-b.json
$VENV_PYTHON -m src.workspace.d5_benchmark run --packet "$PACKET" --stage B \
  --out outputs/d5/v6-stage-b
# STOP for owner review. No C/D permission follows.
```

Expiry must be explicitly supplied, no later than the preserved amendment expiry2026-11-14T07:24:01Z (Nov13 23:24:01 PST). Revocation, expiry, drift, first provider/contract/admission/accounting failure or uncertain completion stops the scope. No automatic retries or alternate identities. All four original A receipts are historical only; all four new bodies need fresh measurements. Every funded stage also requires its own exact paired count. See [prospective choices](PAID-VALIDATION-PROPOSAL.md) and [wire/body audit](evidence/prose-repair-v6r2/binding-audit.json).
