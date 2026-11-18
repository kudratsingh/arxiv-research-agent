# Frozen v20 runbook

Application `d33a0ccf7d21052bc20fef3047769befd85b4372`; packet `60cf5c83a3553c765993eb8cb2db5aed7bb5e382f9434baf9c893a3c582f4b27`; file SHA-256 `75683e109c2734d3bea0e2cba35185b12f0883d35ee32bdbe13ad9ea2b77d724`; proposal `408226e27fa923194d5cfa17bf437491b1435395e1f7dab5d6b3c90a89fd4578`; scope `d5-60cf5c83a3553c765993eb8c`. Copy existing packet bytes; do not rerun a freezer to recreate its timestamp/identity.

Run Python from this isolated worktree root. The local interpreter is `/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python`; local commands also use the existing exact-pinned dependency overlay `/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps` because the shared environment predates the qualification JSON-schema pins. CI installs the checked-in lockfile. Do not install into the shared venv. Verify `import src` resolves to this worktree.

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export PACKET_DIR=planning/15-evaluation-audit-and-recovery/evidence/behavior-v20
"$VENV_PYTHON" -c 'import src; print(src.__file__)'
"$VENV_PYTHON" -m src.workspace.d5_campaign verify --packet "$PACKET_DIR/packet.json.gz"
```

For the real protected offline replay, point D5_POSTGRES_URL at a **new empty disposable** local workspace_d5 database on15488, never the active ledger or owner storage. Supply the preserved exact52-job snapshot and a new permanent output directory. This marks fixture storage and creates only mock-only synthetic authority. The same production admission/adapter/journal runs with MockTransport; fake counts establish no real token fit.

```sh
export D5_POSTGRES_URL='<NEW empty isolated workspace_d5 database URL>'
"$VENV_PYTHON" -m src.workspace.d5_campaign offline \
  --packet "$PACKET_DIR/packet.json.gz" --snapshot "$EXACT_52_JOB_SNAPSHOT" \
  --fixture-repair-all --out "$NEW_PERMANENT_OFFLINE_RESULT_DIR"
```

The reported canonical replay uses the same frozen packet with ten cases and28 Message/count pairs, including six repair/recheck workflows. Never replay into occupied fixture storage. Retain raw journals, failed attempts and source/financial bindings before fixture teardown.

After a **new exact owner decision and resolution of required CI**, an operator may create an external owner receipt using the false template. Do not copy fixture authority. Approved fields, attribution, UTC receipt and expiry must be supplied from that decision; expiry is no later than24hours after receipt and2026-11-21T11:03:57Z. Set no capacity/budget/expiry approval fields. Keep the four exact quarantine exceptions. Before activation compare every source/financial/authority record with the sealed snapshot; any unrelated programme member/activity or changed prefix stops activation.

The following are **unexecuted provider commands**. Use only the private active ledger and the separately owner-approved credential environment; never set up a key during offline verification. Do not log environment values. The packet and matching external authorization are both required.

```sh
# AFTER the exact approval and required gates; not part of offline preparation.
"$VENV_PYTHON" -m src.workspace.d5_campaign_operator template \
  --packet "$PACKET_DIR/packet.json.gz" --authorization "$NEW_PRIVATE_OWNER_TEMPLATE"
"$VENV_PYTHON" -m src.workspace.d5_campaign_operator record \
  --packet "$PACKET_DIR/packet.json.gz" --authorization "$EXTERNAL_COMPLETED_OWNER_RECEIPT" \
  --receipt "$NEW_PRIVATE_ACTIVATION_RECEIPT"
"$VENV_PYTHON" -m src.workspace.d5_campaign run \
  --packet "$PACKET_DIR/packet.json.gz" --out "$NEW_PERMANENT_PROVIDER_RUN_DIR"
```

The operator record is append-only/idempotent and two-phase fail-closed; an identical receipt may finish interrupted local registration without renewing expiry or contacting a provider. Stopped/expired scopes are never renewed or replayed. Later read-only reporting recovers durable terminal state, even without the original runner's stop argument:

```sh
"$VENV_PYTHON" -m src.workspace.d5_campaign report \
  --packet "$PACKET_DIR/packet.json.gz" --out "$NEW_VERSIONED_REPORT_DIR"
```

The two new development identities must have complete latest-response contracts before evaluation/probes. A negative quality result is not acceptance. Only a decisive, completely metered quality rejection with no unresolved dimension, or the one independently reproduced allowlisted C semantic failure, may permit the next unrelated sealed case. An invalid first draft stays terminal for that case without repair/salvage/replacement. All systemic, authorization, binding, accounting, capacity, provider, truncation, uncertainty, cancellation, revocation or expiry failures stop the whole scope. No automatic retry.

The new request index seals10 initial Messages and matching count bodies. Checker/repair/recheck requests depend on actual preceding outputs and derive under frozen templates. Their actual digests are journaled when created and each requires a fresh exact paired count. No fabricated future bodies, old measurements or stale checker judgments may substitute.

Read-only preview3197 is simulated/fixture-only and owner3137/review3178 are untouched. Retained PDF excerpts and inherited abstract provenance remain limited; this is not fresh literature acquisition. Browser history reliability, compact mobile dock area and incomplete automated contrast findings remain documented limitations. Human labels stay blank, quality remains machine-only, and everyday generation/recurrence/notifications stay disabled.
