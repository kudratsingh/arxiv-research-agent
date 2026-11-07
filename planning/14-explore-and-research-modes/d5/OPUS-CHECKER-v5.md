# D5 v5 runbook — offline completion, paid execution NOT RUN

Application `04945c61454f57b8597255587537db068951b12d`; packet `85afa214bd4634ca27e668470257b9ecb53b2dfe87fa018ec17856e46729b35b`. Final publication/CI identity is recorded separately in the evidence index. Keep the v4 packet, live ledger and historical failures immutable. This runbook grants no permission.

## Verified offline path

174 focused tests passed,96.49% combined coverage of the three new modules (operation routing100%, measurement reuse95%, amendment96%). All53 existing workflow/e2e tests passed; research simulation20/20 atUSD0; registry parity260/0. Complete source mypy passed192 files and ruff passed. Full Python/patch coverage passed6615tests/54skips with94.61%total and97%patch; all package floors passed. Documentation66/66. [Local receipt and output](evidence/opus-checker-v5/README.md) distinguish these from remote CI, which is pending at publication and bound separately by the final receipt.

The full retained-data replay completed10 workflows (two development/eight fresh) and all four five-item probe batches through production adapters/admission/journal/persistence/scoring. It consumed44 **mocked** Messages and44 **mocked** paired counts, exercised draft/check/repair/recheck, and reached21 programme jobs (22 identities including the parent) in disposable storage. Actual provider/count contacts and new spending were0. All labels remain blank; acceptanceHOLD and checker_qualified=false. This is software evidence, not real Opus token fit, remote schema acceptance or independent semantic validation.

Tests cover the original20 cap, explicit synthetic amendment admitting21/refusing22, other-programme isolation, unchanged original row, no workflow permission from an amendment, missing/revoked/expired/tampered receipts, exact census/history, accounting, complete reservation, model/count mismatches, malformed/truncated verdicts, selected evidence/source drift and all preserved legacy D5 failures. Simulated adaptive reasoning blocks are retained in the journal and never substituted for a structured verdict. Invalid completed content can settle known financial usage without becoming accepted; unknown completion remains held and unreplayable.

## Runnable offline commands

Run from `/private/tmp/arxiv-agent-eng-workspace-assistance`, with locked Python and imports resolving here. Never use the real credential for these commands.

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-qualification-schema-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
$VENV_PYTHON -c 'import src; print(src.__file__)'
export PACKET=planning/14-explore-and-research-modes/d5/d5-system-validation-v5.json.gz
$VENV_PYTHON -m src.workspace.d5_benchmark verify --packet "$PACKET"
export WORKSPACE_TEST_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests
$VENV_PYTHON -m pytest -q tests/test_workspace_d5_opus.py tests/test_workspace_programme_amendments.py tests/test_workspace_d5_measurement_reuse.py tests/test_workspace_d5_adapter.py tests/test_workspace_d5_benchmark.py tests/test_workspace_d5_stage_grants.py
make test-cov-diff VENV_PYTHON="$VENV_PYTHON"
make test-e2e VENV_PYTHON="$VENV_PYTHON"
make simulate-research VENV_PYTHON="$VENV_PYTHON"
$VENV_PYTHON -m src.contracts.registry parity
```

To reproduce the full packet schedule, create a **new empty disposable** database on the existing isolated D5 PostgreSQL15488, e.g. `workspace_d5_opus_v5_replay2`. Do not reuse/overwrite any current database. This script installs copied public/financial inputs; its synthetic amendment and workflow authorization are confined to a permanently marked fixture database and cannot dispatch a provider request.

```sh
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_opus_v5_replay2
$VENV_PYTHON - replay \
  --packet "$PACKET" \
  --snapshot planning/14-explore-and-research-modes/d5/d5-replay-inputs-v3.json.gz \
  --amendment planning/14-explore-and-research-modes/d5/programme-job-amendment-v1.json \
  --out outputs/d5/opus-v5-offline-replay2 \
  < planning/14-explore-and-research-modes/d5/tools/prepare-opus-v5.py
```

That script's `seal` verb, with a new output packet filename and empty disposable database, reproduces the prospective freeze from the same inputs. The packet binds the tool/source hashes and application commit; a changed producer requires a new revision, never overwrite the current artifact. The four historical real measurements stay attached to their original v4 jobs. Mock paired-count values remain synthetic100, not measured token fit. The full original report and synthetic amendment receipt are retained under outputs/d5/opus-checker-v5/replay and [compressed evidence](evidence/opus-checker-v5/SYNTHETIC-results.json.gz).

## Before any later paid work — operator boundary

**Not executed in this batch.** There are two distinct decisions: approve the programme-specific20→21 amendment, then approve the fresh B-only packet/limits. No C/D permission follows. Current live storage remains `workspace_d5_contract_v4_validation`; pointer `outputs/d5/ACTIVE-QUALIFICATION-LEDGER.json` stays unchanged. Candidate fixture databases must never become validation databases or have their fixture marker removed.

A future operator must use a fresh **unmarked** isolated validation database, e.g. `workspace_d5_opus_v5_validation`, initialized with the exact captured public/financial snapshot. Before switching the single active-ledger pointer, compare its full census/checkpoint hashes against the current active ledger:7 programme jobs,10 Messages,24 counts,USD0.125611, pending/unknown0. Preserve original v3/v4 storage and prevent concurrent use of both ledgers. A mismatch stops the handoff. Do not reseed an earlier snapshot or reset funded identities. This handoff and receipt recording are part of the separately reviewed operator action, not permission supplied by this document.

The following are concrete future commands, **UNEXECUTED**, after that storage handoff and the corresponding independent approvals. Key loading stays in the existing separate operator mechanism; no key is needed for templates/receipts. `record` cannot invent approval, and rejects approved=false. The new scope is B-only; the historical A receipt is not renewed or extended.

```sh
# Future unmarked empty DB only, before dispatch; keep sentinel during preparation.
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_opus_v5_validation
$VENV_PYTHON -m src.workspace.d5_benchmark init --packet "$PACKET" \
  --snapshot planning/14-explore-and-research-modes/d5/d5-replay-inputs-v3.json.gz
# Verify full census vs current active ledger; perform the reviewed single-ledger handoff.
# Only AFTER separate owner approval: supply a filled versioned amendment receipt
# derived from programme-job-amendment-v1.json, never from a synthetic receipt.
$VENV_PYTHON -m src.workspace.programme_amendments record \
  --program-id research-evaluation-20261105-v1 \
  --receipt outputs/d5/owner-programme-amendment-v1.json
# Export approved=false B-only template; owner approval must independently fill it:
$VENV_PYTHON -m src.workspace.d5_operator template --packet "$PACKET" \
  --stages B --receipt outputs/d5/owner-opus-v5-B.json
# Only AFTER matching explicit Stage B approval:
$VENV_PYTHON -m src.workspace.d5_operator record --packet "$PACKET" \
  --receipt outputs/d5/owner-opus-v5-B.json
# Only in the independently authorized operator process with safe key loading:
# unset WORKSPACE_D5_OFFLINE; load ANTHROPIC_API_KEY without displaying it.
$VENV_PYTHON -m src.workspace.d5_benchmark run --packet "$PACKET" --stage B \
  --out outputs/d5/paid-opus-v5-B
# STOP. No C/D authorization, no A rerun, no automatic retries.
# Scope revocation, no provider contact:
$VENV_PYTHON -m src.workspace.d5_operator revoke --packet "$PACKET" \
  --receipt outputs/d5/owner-opus-v5-B.json
```

Per-job reservationUSD0.45 covers the completeUSD0.448 Sonnet-draft/Opus-check/Sonnet-repair/Opus-recheck bound before the first dispatch. Stage B permits only2jobs,8Messages/8paired counts andUSD0.90 new spend. Each actual body/model must match its paired count. Opus's16000-token measured allowance and3200-token total output cap are strict; mock fit grants nothing. No independent measurement pass is proposed. Stop on the first contract/provider/admission/accounting failure, source/settings/schema/producer drift, cancellation, revocation/expiry or uncertain completion. Keep the journal, settle only validated known usage, and never retry a possibly completed contact under another identity.

Human review remains [the existing sidecar workflow](HUMAN-REVIEW-RUNBOOK.md). No synthetic labels populate the real worksheet. A resolving quote cannot establish whole-claim support; invalid provenance cannot be rescued by positive support labels. Development facts do not enter held-out minimums. Insufficient/unreviewable judgments and missing denominators remain unscored/HOLD. The initial programme's q01–q04 failures and original aggregate remain unchanged.
