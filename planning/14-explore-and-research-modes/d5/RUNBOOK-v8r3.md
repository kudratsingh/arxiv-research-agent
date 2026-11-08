# v8r3 ledger refresh and staged qualification runbook

**Preparation only. Zero provider Messages/count contacts, no live grant, cap
activation or new spend. Do not execute paid commands without their separate
owner approvals.** Packet:
`42aa787ca0aa9e22dd92a6eddb5a7b8642a9f8364526bccf3af66b3947de2b4c`.
Source baseline `d3a1d05297a7aa4c93f0f7ff6f492030bd06d36e`.

## Offline verification

From `/private/tmp/arxiv-agent-eng-qualification-v8-refresh`:

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PYTHONPATH=/private/tmp/arxiv-calibration-preflight-deps:$PWD
export ANTHROPIC_API_KEY=local-preview-disabled
export WORKSPACE_D5_OFFLINE=1
export PACKET=planning/14-explore-and-research-modes/d5/evidence/qualification-v8r3/packet.json.gz

$VENV_PYTHON -c 'import src; print(src.__file__)'
$VENV_PYTHON -m src.workspace.d5_benchmark verify --packet "$PACKET"
```

The refresh generator ran with a MockTransport that refuses every HTTP contact,
against a **new empty** `workspace_d5_v8r3_ledger_refresh_20261108` database on
isolated port 15488. It mirrors financial/history records only into permanently
provider-disabled replay storage, never the active ledger. No new scope or
budget policy exists there. The generator refuses to overwrite artifacts or
import into nonempty storage; choose a new DB/output revision to reproduce.
[Exact producer command and script hash](evidence/qualification-v8r3/GENERATOR-ATTESTATION.json).

Full financial replay and compiled inputs remain local/private:
`outputs/d5/v8-ledger-refresh/private-replay-v1/`. Do not publish them: historical
calibration job records contain the independent-review proofs. Public artifact
hashes attest to the complete ledger; no human labels enter new model context.
The original public corpus/profile snapshot and frozen case/scorer fields are
unchanged, including the old clock. This establishes retained replay, not fresh
source acquisition or full-paper extraction quality.

## Separate Stage A decision

Review [A scope](evidence/qualification-v8r3/STAGE-A-SCOPE.json),
[exact count body](evidence/qualification-v8r3/measure-1-request.json), and
[A-only approval text](evidence/qualification-v8r3/STAGE-A-APPROVAL-REQUEST.md).
The [operator template](evidence/qualification-v8r3/STAGE-A-OPERATOR-TEMPLATE.json)
is approved=false. It grants nothing.

Only after explicit owner A approval, the operator must:

1. Reverify 20 jobs / 35 Messages / 54 counts / USD 0.904053, pending/unknown 0, the active
   24-job amendment, packet/source/settings/schema bindings and expiry.
2. Prepare only packet-declared public contexts for the isolated v8 principals
   in `workspace_d5_prose_v6_validation` using the existing
   `src.workspace.d5_fixture.prepare_projects(store, packet)` helper. It refuses
   profile/project drift and grants no permission. Do not change owner3137 or
   replay fixture records/authorizations into the live ledger.
3. Record an independently supplied A-only receipt through the existing operator
   mechanism. No runner may create/approve its own receipt.
4. Load the existing credential only into the isolated experiment process,
   without displaying it or putting it in argv/history/logs. Use the approved
   count request, never an authentication smoke call.
5. Run exactly the A stage, then stop for review.

The execution entry points, **not executed during preparation**, are:

```sh
# After explicit A approval and all bindings have been checked:
$VENV_PYTHON -m src.workspace.d5_operator record \
  --packet "$PACKET" --receipt outputs/d5/v8r3-live-A/OWNER-A-RECEIPT.json
$VENV_PYTHON -m src.workspace.d5_benchmark run \
  --packet "$PACKET" --stage A --out outputs/d5/v8r3-live-A/results
```

Those commands require the existing isolated live-ledger `D5_POSTGRES_URL`, a
matching external owner receipt and the established credential loader. The
sentinel environment shown for offline checks must never be silently switched
by a runner. Generation remains gated. One A count, zero Messages, zero funded
jobs, USD0 new spend. A counts against the 80-contact programme ceiling. Successful
A alone establishes neither Messages-schema acceptance nor semantic quality.

## Separate Stage B decision after A review

Review [B scope](evidence/qualification-v8r3/STAGE-B-SCOPE.json),
[Learn wire](evidence/qualification-v8r3/dev-learn-request.json),
[Compare wire](evidence/qualification-v8r3/dev-compare-request.json), local/wire
schema exports and [B-only approval text](evidence/qualification-v8r3/STAGE-B-APPROVAL-REQUEST.md).
Do not fabricate a parent-authorization digest or a successful A receipt now.

After A completes and the owner separately approves B, verify the actual A
receipt and expected 20 jobs / 35 Messages / 55 counts / USD 0.904053, pending/unknown 0.
Create the read-only B template against the active, unexpired parent:

```sh
$VENV_PYTHON -m src.workspace.d5_operator stage-template \
  --packet "$PACKET" --stages B \
  --receipt outputs/d5/v8r3-live-B/B-TEMPLATE.json
# Record only an independently supplied matching owner B receipt:
$VENV_PYTHON -m src.workspace.d5_operator grant \
  --packet "$PACKET" --receipt outputs/d5/v8r3-live-B/OWNER-B-RECEIPT.json
$VENV_PYTHON -m src.workspace.d5_benchmark run \
  --packet "$PACKET" --stage B --out outputs/d5/v8r3-live-B/results
```

B is `dev-learn`, then `dev-compare`, one job/contact at a time. Maximum 2 funded
jobs / 8 Messages / 8 exact paired counts / USD 0.45 each / USD 0.90 total. At most one permitted
repair plus mandatory recheck per workflow; no automatic retries. Exact dynamic
bodies must derive from preceding journalled outputs under frozen templates,
source selections, schemas and limits. Every actual stage needs its own exact
paired count; the A request does not replace B's required paired count.

Stop on the sealed provider/contract/accounting/admission/drift/unknown failure
conditions, preserve failed/uncertain attempts and unrun census, and never create
alternate identities to replay a possibly completed contact. A valid repairable
first-check finding may use only the existing bounded repair/recheck path;
residual unscored prose still rejects. Return development outputs/costs and stop
for review before any C or D decision. Development is outside held-out minimums.

## Full-schedule capacity prerequisite

The full fixed A–D schedule needs cumulative 34 jobs / 79 Messages / 99 counts. Current
caps 24 / 80 / 80 are insufficient. The [separate capacity proposal](evidence/qualification-v8r3/CAPACITY-AMENDMENT-PROPOSAL.json)
requires 24→34 jobs and 80→99 counts, preserving USD 10, 80 Messages, concurrency 1 and
2026-11-14T07:24:01Z expiry. No cap/expiry has been changed by this refresh.

The present recorders do not support a count-cap extension. Implement/test and
freeze that policy before paid A/B when possible; otherwise any later producer
change requires a successor freeze and explicit measurement/development reuse
audit. Do not silently attach old jobs to new packet identities. No activation
command is offered for an unsupported amendment, and C/D each retain separate
approvals and all existing quality minimums.
