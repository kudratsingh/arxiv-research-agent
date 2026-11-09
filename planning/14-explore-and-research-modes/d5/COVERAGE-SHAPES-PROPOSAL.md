# Coverage-shapes development follow-up — UNAPPROVED

This proposal authorizes nothing. Application`5e51269be259cf0d4ee6eacaddbccc63ace3fa2c`; packet`22b8e13bc39d78cb1203f2e613c7c488d7f5a403234840d5ae15dcfa3d44a477`; scope`d5-22b8e13bc39d78cb1203f2e6`. [Copyable A-only decision](COVERAGE-SHAPES-A-APPROVAL-REQUEST.md). Exact packet/application identities and offline
receipts are linked in [verification](evidence/coverage-shapes-v9/VERIFICATION.md).
The prior failed identity remains stopped. No historical count is reused for the
changed v9 request, schema or prompt. Human qualification and Stage D are deferred.

## Smallest useful follow-up

One **new** fixed-evidence Learn development case, `development-v9-learn-coverage`,
targets the observed status/reference failure. First request separate A-only
approval for its one sealed Sonnet count. Only after reviewing that actual receipt,
request B-only approval for the one workflow. Both require the current programme,
source/model/settings/schema/producer bindings, exact ledger and expiry checks.

B uses unchanged sealed Sonnet 5.5 draft/repair and Opus 5.5 adaptive High
check/recheck routes. Each actual stage must be paired with its exact model/body
count, fitting 16,000 input tokens. Capacity includes all four stages in advance.
One repair maximum; any repair requires recheck. Concurrency1, automatic retries0.
First drift, admission/provider/contract/accounting failure, revocation,
cancellation, expiry or uncertain completion stops. No substitutions, source
expansion, replay of stopped identities or extra cases.

| Choice | Fresh A counts | B jobs | B Messages max | B paired counts max | Cumulative jobs / Messages / counts | New B reservation | Historical + B | Including unchanged USD1 headroom |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| **Proposed: Learn only** | 1 | 1 | 4 | 4 | **32 / 66 / 90** | USD0.45 | USD2.252777 | USD3.252777 |
| Optional Learn + comparison | 2 | 2 | 8 | 8 | 33 / 70 / 95 | USD0.90 | USD2.702777 | USD3.702777 |
| Full three-case repeat | 3 | 3 | 12 | 12 | 34 / 74 / **100** | USD1.35 | USD3.152777 | USD4.152777 |

Baseline is **31 funded programme jobs /62 Messages /85 counts /USD1.802777**
estimated cumulative spend; pending and unknown0. Active caps remain
**34 jobs /80 Messages /99 counts /USD10**, concurrency1, expiry
**2026-11-14T07:24:01Z**. New scope grants cannot exceed 24 hours or that expiry,
and B cannot renew its A parent. No cap or expiry is activated/extended here.

The full three-case maximum cannot fit the current count cap: 85+3+12=100.
If that larger schedule is wanted, **99→100 counts is a separate programme
capacity decision and separately sealed scope**; neither money remaining nor this
repair grants it. The two-case and three-case alternatives are budget comparisons,
not executable grants under the one-case packet. No quality threshold is reduced.

The smallest case does not test live Research comparison or full abstention,
real semantic quality across topics, checker calibration, human usefulness or any
held-out minimum. Those paths have offline controls only. Development results
cannot fill held-out or human-review denominators. Token fit, remote schema
acceptance and model behavior remain unmeasured for v9.

## Prospective operator and runner commands

Use a generation-isolated qualification process/storage only after the relevant
explicit approval. These commands are listed for review and were **not run against
provider transport**. The template is approved=false and is not an approval.

```sh
export VENV_PYTHON=/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python
export PACKET=planning/14-explore-and-research-modes/d5/evidence/coverage-shapes-v9/packet.json.gz
export D5_POSTGRES_URL=postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_prose_v6_validation
"$VENV_PYTHON" -m src.workspace.d5_operator template --packet "$PACKET" --receipt outputs/d5/coverage-shapes-v9/A-template.json --stages A
```

After an externally supplied, matching A-only approval: use the existing
`d5_operator prepare` to verify storage/history and prepare isolated principals,
then `d5_operator record` with that independently recorded receipt. The runner
never creates permission. The exact paid command is:

```sh
"$VENV_PYTHON" -m src.workspace.d5_benchmark run --packet "$PACKET" --stage A --out outputs/d5/coverage-shapes-v9/A-approved-new
```

A covers measure-1 **once**, zero Messages/jobs/new spend. Stop after A for owner
review. B requires `d5_operator stage-template --stages B` binding the actual A
parent authorization and post-A census, an external B-only approval, then
`d5_operator grant` with that receipt. Its runner command is identical except
`--stage B` and a new B output directory. B maxima: one job, four Messages,
four exact paired counts, USD0.45 all-in; no C/D grant. Never copy a synthetic
replay receipt into live storage or load credentials into everyday/frontend tests.

Sealed operation budgets (unchanged, ESTIMATE; input/output prices per million):

| Operation | Model/settings | Planning input cap | Output cap | Prices input/output | Per-call planning bound |
|---|---|---:|---:|---:|---:|
| Draft or repair | Sonnet 5.5, between_tools, medium | 20,000 | 4,000 | USD2 / USD10 | USD0.080 |
| Check or recheck | Opus 5.5, adaptive, High | 20,000 | 3,200 including thinking/verdict | USD4 / USD20 | USD0.144 |

The actual paired-count admission allowance remains **16,000**, narrower than the
sealed 20,000 planning cap. A normal draft/check has a USD0.224 planning bound;
all four stages have USD0.448, covered by the unchanged USD0.45 all-in reservation.
Using16,000 counted input tokens instead gives a USD0.400 count-based subtotal.
The financial reservation still uses20,000: a count estimate is not actual
provider-reported usage. These are theoretical bounds, not expected usage or
measured token fit.
The retained price verification date is2026-11-06; no live price lookup or provider
contact was made in this offline batch. Outputs/think tokens share the output cap.

All prices remain the existing sealed ESTIMATE, not invoice-verified. No model,
settings, output allowance or pricing is silently changed. The all-in per-job
reservation, cumulative known/pending/unknown liability and USD1 headroom are
checked by existing admission. This offline repair made zero provider contacts
(including counts) and incurred USD0 new spend.
