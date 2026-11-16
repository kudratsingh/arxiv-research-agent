# Frozen v19 comparison campaign runbook

This is one prospective, unapproved campaign. The public authorization template must remain false, with the owner and approval-source fields null and approval expiry unset. No command below grants permission for a real provider or count contact by itself.

## Frozen identities

Application: `b1bad909b112c246b678c0194325ae974e4284bf`
Packet: `00cc2c78e66fcc58c16a5afcf24db3c5177b6a8940ef2638c07a841edeacf48d`
Packet file SHA-256: `fc32617537cefe6443026dc9be1750da7ecdd793f7634a9d39fcf330616eba13`
Proposal: `7fa75947efdb091bc1038f95d7a3e37d7ebcc48eb37137e1a40a543e8aa318b9`
Scope: `d5-00cc2c78e66fcc58c16a5afc`
Frozen baseline snapshot: `a767c3c158763f99acc58be2555559aa2668f430959c76421f9226e110d2beb8`

All packet, compiled-input, request, local/wire schema, proposal and selected-source hashes belong to this one frozen packet. Do not run a freezer again to recreate it: its creation timestamp changes the identity. Copy its existing bytes and verify the SHA-256.

## Evidence and source scope

The two development contexts retain real ReAct 2210.03629v3 and SelfRAG 2310.11511v1 PDF excerpts. The eight evaluation controls retain an inherited exposed benchmark-source/abstract snapshot with 2610.* identifiers. Their bibliographic metadata and public-paper acquisition provenance were not newly verified. The checks pin selected material hashes, versions, quotes and offsets; that identity evidence is separate from bibliographic provenance, fresh intake, semantic support and human usefulness.

The corpus, ten questions, ranking/selection, answerability, scoring thresholds and twenty balanced machine-reference controls remain frozen. There are two development identities, eight exposed evaluation identities and four probe batches. This is not held-out evidence. Machine-authored reference labels and synthetic model outputs are not independent or human gold. Browser review uses the retained ReAct/SelfRAG copies and synthetic outputs.

## Proposal and limits

The new campaign envelope is 14 jobs, at most 44 Messages and 44 fresh same-model paired count contacts, and USD14.00 new campaign reservation: ten workflows at USD1.20 each and four probes at USD0.50 each. Concurrency is 1. Each workflow allows one repair and requires a new check after any repair.

The separate proposal raises cumulative programme, day and month dollar ceilings from USD20 to USD22. The funded job/message/count caps remain 64/160/200. Programme expiry remains `2026-11-21T11:03:57+00:00`; a future owner-approved campaign expiry must be no later than 24 hours after approval and no later than that programme expiry. There is no renewal.

Historical known cost is USD2.533843; four exact historical holds retain an overlapping pending/unknown USD2.275066. Pending already includes unknown, so count that liability once. Known+retained liability+maximum new reservation is USD18.808909; adding the unchanged USD2.00 headroom is USD20.808909. No hold is settled, reduced, replayed or released by this proposal.

Frozen model settings and per-operation deadlines are authoritative in ROUTES-AND-LIMITS.json. Pricing settings are frozen estimates, not a fresh price claim. No additional standalone diagnostic identities are included.

## Offline artifact workflow

Run from the intended worktree root with its lock-exact Python. Supply the final packet directory and exact application commit to the prepared exporter and artifact verifier. The exporter never freezes or authorizes. The prepared public package contains only the frozen packet, deterministic prospective derivatives, a false template and sanitized software proofs.

1. Prepare derivatives from the existing final packet into a NEW artifact directory. Never overwrite a previous packet or evidence directory.
2. Run the read-only artifact verifier before replay. It checks the 14 initial request bodies, matching count bodies, local/wire output schemas, compiled inputs, proposal/source hashes, cohorts, machine-reference balance and structural privacy.
3. Replay the SAME published packet with the canonical helper below. Its database must be explicitly disposable and fixture-marked. Real provider mode is prohibited there. The helper installs the exact preserved snapshot and creates only synthetic authorization in that isolated test schema.

```sh
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export WORKSPACE_TEST_POSTGRES_URL='<existing isolated workspace_d5_tests URL>'
"$VENV_PYTHON" - < planning/15-evaluation-audit-and-recovery/tools/replay-frozen-comparison-v19.py \
  --packet "$PACKET_DIR/packet.json.gz" \
  --snapshot "$EXACT_PRESERVED_SNAPSHOT" \
  --out "$NEW_PERMANENT_PRIVATE_REPLAY_DIR"
```

This helper reads the packet; it does not call a freezer. Keep FROZEN-PACKET.json.gz, REPLAY-INPUT-BINDINGS.json, all raw request/response journals, GATE.json, reports and synthetic grant exports in permanent private evidence storage, including failed attempts.

4. Finalize only sanitized SDK guard receipts from that replay. Require the exact input packet SHA/digest. Export schema metrics and request hashes for the 44 actual SDK mock operations and their44 paired counts; do not export synthetic grants, raw ledger rows, model responses or dynamic-body journals.
5. Run the artifact verifier with `--require-replay`. Original artifact manifests remain immutable; proof manifests are appended separately. Public JSON must contain no raw `record`, `authorization_record`, owner-approval values, credentials or synthetic grant. Only the false template may contain null owner/approval-source placeholders.

The request index seals14 initial bodies and exact same-model count bodies. Later checker, repair and recheck bodies depend on actual prior responses and cannot be invented or prefilled. Each future generation body needs its own fresh count. Historical v18 compatibility references and mock counts are never reused as new count receipts.

Passing schema guards, local tests and mock replay establishes software mechanics only. Actual token fit, provider grammar compilation/acceptance, scientific quality and human qualification remain unmeasured. The historical v18 compatibility proof belongs to its own contract and identities.

## External owner decision and provider operation

Do not contact a provider or count endpoint until a separate explicit owner decision names the exact application, packet, proposal, scope,14 identities, USD14 new scope, proposed USD22 ceilings, unchanged caps/expiry and four retained holds. A configured key is not permission. Keep the completed owner approval and its source in a new private evidence file, never in the public package. The public false template remains unchanged.

Only after that decision and required checks have passed may the operator validate the actual private ledger against the frozen baseline and record the exact private receipt. The writer requires the real verified packet, not caller-asserted hashes. The canonical commands are:

```sh
# AFTER the explicit scoped owner decision; private ledger/key environment only.
"$VENV_PYTHON" -m src.workspace.d5_campaign_operator record \
  --packet "$PACKET_DIR/packet.json.gz" \
  --authorization "$PRIVATE_COMPLETED_OWNER_RECEIPT" \
  --receipt "$NEW_PRIVATE_RECORDING_RECEIPT"
"$VENV_PYTHON" -m src.workspace.d5_campaign run \
  --packet "$PACKET_DIR/packet.json.gz" \
  --out "$NEW_PERMANENT_PRIVATE_PROVIDER_RUN_DIR"
```

The operator uses the private `D5_POSTGRES_URL`; do not point a provider operation at fixture storage. The owner configures any real credential only in the approved provider-run shell. Never place a key in chat, a packet, a command argument or a committed file.

Stop on provider error, new external uncertainty, drift, corruption, exhausted limits, expiry, revocation or cancellation. Preserve raw/partial/failed responses and full holds; do not salvage incomplete JSON, retry, replace identities, reseal, settle historical uncertainty or make another contact after a stop without a new decision. Exact recording is idempotent; it never renews expiry. A valid negative quality verdict remains a failure and can permit the next unrelated sealed identity only when its complete current response/check contract is proved. A broken development contract stops before evaluation and probes.

Reports must keep formatting, parsing/contracts, selected-source identity, semantic judgments, checker reliability, research quality and human qualification separate. No everyday-generation activation follows from this campaign.
