# Uncertain v10 checker: evidence and resolution plan

This is a read-only investigation, not permission to clear the hold or contact
the provider. The stopped run, original draft, checker body and receipts remain
at their original paths. Neither invalid content nor a local timeout is a
financial settlement receipt.

## Preserved facts

Programme census: **33 funded jobs / 65 Messages / 90 counts**. Known estimated
spend **$1.853811** plus **one $0.425066 hold** gives **$2.278877** maximum
currently accounted exposure. Pending and unknown both describe that same hold;
they must not be summed twice. There is no new spend in this repair.

Stopped scope `d5-880e4794cd08d26a4a9e6323` is revoked; its A/B parent expired
2026-11-12T02:59:48Z. Programme expiry remains 2026-11-14T07:24:01Z.

| Record | Preserved value |
| --- | --- |
| Funded job | `gen-ba942321c16d5ed10cc41cff7f6c1ac9f5a98877` |
| Original packet | `880e4794cd08d26a4a9e63231d5d0d82ec99a267e65ff60dfc5f0994875fb864` |
| Checker contact | ordinal 3, Messages, dispatching, no complete response/usage |
| Checker request digest | `1cadf794e80188f2807316fe73542a685eeea1660e742ba28af53a710b015f4f` |
| Checker count digest | `fc8a9bc77ba244db6d1e8f60fed147a4ef284f2915f13ed89857fda4405ef34e` |
| Preliminary checker count | 10,769 input tokens; not actual billed usage |
| Completed draft | Sonnet 5.5, 7,877 input / 918 output tokens, $0.024934 estimate |
| Whole local job interval | 2026-11-11T03:08:30Z to 03:09:19Z; not precise provider completion time |

Original evidence is in
`/private/tmp/arxiv-agent-eng-workspace-coverage-authority/outputs/d5/coverage-authority-stage-b-20261111/`.
`STAGE-B-RESULTS.json` file SHA256 is
`9b07b94d62683ea512d8b10795c99a82d97fbc9439abf753d57db0b6bfd41bb6`.
No provider message ID or request-header receipt was captured for the timed-out
checker. The journal has no validated response body, stop reason or actual usage.
Zero recognized checker cost is therefore not evidence of zero upstream cost.

## Evidence-backed options, in order

1. **Owner-supplied provider evidence, reviewed offline.** A redacted console
   export, invoice detail or support record may establish completion and usage
   if it can be uniquely associated with this model, account/workspace, key alias,
   time window and request. Preserve its original bytes, source, timestamp and
   hash. An aggregate usage total, no visible billing entry, or the local count
   alone cannot uniquely settle this contact.
2. **Separately authorized, bounded read-only usage investigation.** First verify
   the provider's current documented reporting facility, account permissions and
   granularity. Bring back an exact endpoint/method, time window, maximum reads
   and pagination, credential requirements and matching rule for approval. This
   would be a new provider contact scope, with no Messages, token counts, job
   replay or generation. No such access has been tested or enabled here.
3. **Owner/support inquiry.** An external support message requires separate
   authorization; this task sends none. The owner can obtain redacted evidence
   directly. Without authoritative attributable evidence, keep the hold and
   stop admission.

The [installed SDK inspection](evidence/operation-deadlines-v11/SDK-INSPECTION.json)
records resource hashes and method names without constructing a client. The
installed Anthropic SDK's synchronous Messages resource and this runner have
create/count/stream paths, but no implemented sealed single-message recovery path
that can retrieve this missing receipt. This local code inspection is not a
claim about all current provider reporting products. No speculative endpoint,
administrator key or unrelated authentication test is used.

## Requirements for any later financial reconciliation

The existing `qualification_accounting.settle_failed_response` requires completed
contacts with validated response usage. It rejects the current unreceived
contact as `external_completion_still_uncertain`. Do not weaken it or manufacture
a response to make it pass.

If authoritative usage evidence becomes available, propose a separately reviewed
append-only reconciliation mechanism/receipt appropriate to that evidence.
Bind the original programme, job, ordinal, request digest, before-state, evidence
hash, attribution and historical model/prices. State recognized workflow/checker
cost, any remaining uncertainty and after-state explicitly. Financial settlement
must remain separate from content acceptance. Keep the original contact and hold
history; do not rewrite or delete them. A late response, if recovered, is a
quarantined historical artifact, not permission to resume the revoked job.

Booking the full reservation as fabricated actual usage, treating expiry as
completion, moving to another principal or ignoring the global concurrency guard
are not resolution options. This revision performs no accounting mutation and
does not create a settlement authorization.

## Before a future experiment

Reconcile only with approved evidence and procedure, verify the complete updated
ledger census, then freeze a new packet against its actual history. The present
candidate explicitly retains the hold and is blocked. Do not silently replace
its history or reuse its digest after settlement. A new experiment also needs
fresh separate A/B grants, within the unchanged programme expiry and limits.
