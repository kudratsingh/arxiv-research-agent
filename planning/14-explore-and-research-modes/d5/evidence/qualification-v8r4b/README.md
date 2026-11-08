# v8r4b — capacity-bound successor, offline preparation


Packet `1429b39296792b8bc3d5530d28bcc56600048b149310fc10df30c2ee6048a7a7`;
application `68c23441cdc351cfb4938f2a01b58597423aca7c`.
No live activation, stage approval, provider contact or new spend.

- [Proposal / budget / unchanged quality gates](../../PAID-VALIDATION-PROPOSAL-v8r4b.md).
- [Runnable offline and conditional operator commands](../../RUNBOOK-v8r4b.md).
- [Packet](packet.json.gz), [freeze receipt](FREEZE-RECEIPT.json),
  [read-only active-ledger audit](LEDGER-AUDIT.json), [producer attestation](GENERATOR-ATTESTATION.json).
- [Capacity-only activation request](CAP-ACTIVATION-APPROVAL-REQUEST.md) and
  [approved=false exact operator proposal](CAPACITY-PROPOSAL.json).
- [Separate A request](STAGE-A-APPROVAL-REQUEST.md), [A scope](STAGE-A-SCOPE.json),
  [approved=false operator template](STAGE-A-OPERATOR-TEMPLATE.json), [count body](measure-1-request.json).
- [Separate conditional B request](STAGE-B-APPROVAL-REQUEST.md), [B scope](STAGE-B-SCOPE.json),
  [Learn request](dev-learn-request.json), [Compare request](dev-compare-request.json).
- [Initial bindings](INITIAL-BINDINGS.json), [measurement non-reuse audit](MEASUREMENT-AUDIT.json),
  [budget](BUDGET.json), [verification](VERIFICATION.md).

Per-case files export both local and transmitted response schemas. Exact dynamic
checker/repair/recheck requests are derived from actual preceding outputs under
frozen templates and limits; their future digests are not invented here.

The original v8r3, v7r2 3/8 and separate four-probe diagnostic remain immutable.
No historical failures or owner labels are retagged. Financial replay contains
private prereview proofs and stays ignored/protected locally, never in these
public artifacts or new model context. All new human-quality fields stay blank.

The implemented policy remains inactive on the actual ledger: 24 jobs / 80
Messages / 80 counts / USD 10 / concurrency 1. Only an independently approved,
matching version-4 receipt can change it to 34 / 80 / 99; no stage permission
follows. Programme expiry remains 2026-11-14T07:24:01Z.

[Corrected full replay receipt](REPLAY-RECEIPT.json) and [synthetic case census](CASE-CENSUS.json) include the zero-claim application-context abstention. [Binding audit](BINDING-AUDIT.json) verifies unchanged inputs/rules and preserved historical files. The earlier fixture error remains a [separate diagnostic](../qualification-v8r4/INSUFFICIENT-FIXTURE-DIAGNOSTIC.json), with no acceptance credit.
