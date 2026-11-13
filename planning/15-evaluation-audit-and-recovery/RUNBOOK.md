# Historical v13 runbook — stopped

Do not activate or resume this stopped scope. Its frozen packet and run evidence remain retained. Use the separate [prospective v14 package and runbook](evidence/provider-contract-v14/RUNBOOK.md) for the unapproved repair; the historical instructions below are preserved as history.

---

# Audit recovery and consolidated campaign runbook

This revision prepares one unexecuted approval. No command below authorizes itself.
Owner3137/review3178 remain separate and generation-disabled. The authoritative
private retention rulebook is linked by the repository's AGENTS.md.

## Identities and evidence

- Qualification application: `a3cf3d7c579ec61cd628d758b341c34daaad3dc0`.
- Packet: `97d24567bc98753122315f135a621eb886cebb2b81c32eb5762572589f037e08`.
- Scope: `d5-97d24567bc98753122315f13`.
- Capacity/exception proposal: `c582b5f64dfb515ca079f17a179365208f00dd1f098fa2c081f46aeec4d8b028`.
- Matrix: `fdf88e73d7a5691a9cc503f89cdd82dadb868b82344f416afb7032c3a485a8a5`.
- Scoring: `workspace-campaign-scoring-v13`.
- Frozen snapshot semantic digest: `28c045e30d5cc318fb552c36d5755c025291bc29d0e236e36d6e9dbddd55225c`.

See [scope/criteria](evidence/consolidated-campaign-v13/CAMPAIGN-SCOPE.md),
[one approval request](evidence/consolidated-campaign-v13/APPROVAL-REQUEST.md) and
[verification](evidence/consolidated-campaign-v13/VERIFICATION.md).
V12 and historical cohorts remain retained. Their old checker requests do not
supply current judgments under the new whole-response policy.

## Offline verification — runnable now

Run from the permanent worktree root. The shared interpreter is never modified.
The test-only dependency overlay is retained in arxiv-tooling; it supplies the
wire-schema validator, not a second production runtime.

```sh
cd /Users/kudratsingh/Machine-Learning-Projects/arxiv-workspaces/workspace-d5-audit-recovery
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export ANTHROPIC_API_KEY=local-preview-disabled WORKSPACE_D5_OFFLINE=1
export PYTHONPATH="$PWD:/Users/kudratsingh/Machine-Learning-Projects/arxiv-tooling/d5-test-deps"
export WORKSPACE_TEST_POSTGRES_URL='postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_tests'
export D5_PACKET=planning/15-evaluation-audit-and-recovery/evidence/consolidated-campaign-v13/packet.json.gz
export D5_EVIDENCE=/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/evaluation-audit-recovery-20261113

"$VENV_PYTHON" -c 'import sys,src; print(sys.version); print(src.__file__)'
"$VENV_PYTHON" -m src.workspace.d5_campaign verify --packet "$D5_PACKET"
"$VENV_PYTHON" -m pytest tests/test_workspace_d5_report_binding.py tests/test_workspace_d5_report_binding_integration.py tests/test_workspace_d5_answerability.py tests/test_evidence_custody_audit.py -q

# Choose a NEW permanent output directory. Existing output is never overwritten.
"$VENV_PYTHON" - --packet "$D5_PACKET" \
  --snapshot "$D5_EVIDENCE/LEDGER-BEFORE-FINAL.json.gz" \
  --out "$D5_EVIDENCE/owner-replay-new-revision" \
  < planning/15-evaluation-audit-and-recovery/tools/replay-sealed-campaign.py
```

The replay creates a unique disposable schema in workspace_d5_tests, installs
copied public inputs/accounting, irreversibly marks it as a fixture, and uses the
production campaign/admission/adapter with MockTransport. It proves the maximal
14-job/44-Message/44-count envelope, exact current check binding and duplicate-run
suppression. Its synthetic counts, verdicts and costs prove software plumbing;
they do not prove provider token fit, remote acceptance or scientific quality.
Results, request/response receipts, analysis binding and readable reports are
retained before disposable storage teardown. The real ledger is never installed
into, migrated or modified by this replay. No private notes/history are included.

## Future operator sequence — NOT executed or authorized

Only the [single explicit owner approval](evidence/consolidated-campaign-v13/APPROVAL-REQUEST.md)
may activate the exact capacity/old-uncertainty exception and frozen campaign.
A false template cannot be recorded. Never copy fixture approval into real storage.

After approval, the operator must compare a fresh **read-only** census and every
packet/source/schema/settings/producer binding against this freeze. Select the
**existing single active ledger**, workspace_d5_prose_v6_validation, from the
retained active-ledger pointer. Do not reseed a former checkpoint or fork a second
live financial ledger. Use the packet's isolated principal and public evidence.
The configured local credential may be loaded only in the authorized qualification
process; never display it or enable it in daily/preview environments.

The existing operator mechanism records the externally attributed owner receipt:

```sh
# UNEXECUTED: requires real owner approval and matching operator-supplied files.
# D5_POSTGRES_URL must name the existing active ledger, not a fixture copy.
"$VENV_PYTHON" -m src.workspace.d5_campaign_operator record \
  --packet "$D5_PACKET" --authorization "$D5_OWNER_AUTHORIZATION" \
  --receipt "$D5_NEW_ACTIVATION_RECEIPT"
"$VENV_PYTHON" -m src.workspace.d5_campaign run \
  --packet "$D5_PACKET" --out "$D5_NEW_QUARANTINED_OUTPUT"
```

One grant covers2 development,8 exposed-corpus evaluation and4 checker batches.
Every Messages contact automatically gets its exact paired count and fit check
(≤16,000 input tokens). No preliminary count-only or individual-case approval
handoffs. Dynamic check/repair/recheck requests are derived from actual preceding
outputs under frozen templates; exact bodies/digests are recorded when constructed.
Models, evidence, quality gates, one repair/mandatory recheck and concurrency1 stay
sealed. Sonnet draft/repair output4000; Opus adaptive High check/recheck/probe
output3200. Counts/drafts/repairs30s, checks/rechecks120s, overall workflow480s.

A fully metered content rejection remains failed and may allow an unrelated case
to continue. Stop for binding drift, accounting corruption, capacity/budget
exhaustion, expiry/revocation, cancellation, provider error or **any new uncertainty**.
Never retry, replace identities, tune mid-cohort or replay old failures into passes.
Progress reports do not request new routine decisions within the approved scope.

## Money, old uncertainty and expiry

The live baseline remains33 programme jobs/65 Messages/90 counts/$1.853811 known
estimated usage plus ONE overlapping$0.425066 pending/unknown hold. Activated caps
are34/80/99; proposed caps are47/109/134. Dollar ceiling$10 and concurrency1 do not
change. Proposed new maximum14jobs/44Messages/44counts/$5.10, including all checking,
repair/recheck and helpers. Per workflow$0.45; per probe batch$0.15.

At the inherited sealed estimate rates (Sonnet$2/$10 and Opus$4/$20 per million
input/output tokens), reservations are$0.080 per Sonnet call,$0.144 per Opus call,
$0.448 for a full workflow and$5.056 for the complete B–D schedule. Authorized
rounded caps sum to$5.10. These are estimates, not new provider measurements or
invoice settlement. The predecessor documented the official
[pricing reference](https://platform.claude.com/docs/en/about-claude/pricing);
this batch preserves those price bindings without provider contact or substitution.
Rates/compatibility must still be checked before any separately approved execution.

Known spend + retained hold + full campaign cap =$7.378877. Including the existing
$1 buffer gives$8.378877, below$10. Do not shrink the schedule to avoid a future
budget decision. Before a later batch approaches the ceiling, request one
consolidated adjustment with results, remaining work and maximum cost.

The exact historical quarantine exception requires owner approval. Preserve the
old uncertain job/contact, unavailable result, revoked scope and full hold; count
it once, never release it. The exception establishes neither upstream completion
nor billing nor physical cancellation. It cannot cover a new uncertain contact.

Programme expiry stays2026-11-14T07:24:01Z (November13,11:24:01PM PST). A future
campaign grant expires at the earlier of24hours after approval and that time.
If expired, stop and bring the necessary prospective decision; never renew silently.
Expected bounded completion is approximately90–100minutes after valid approval,
subject to earlier hard stops. No live authority is activated by this document.

All rights reserved. No license or reuse permission is granted.
