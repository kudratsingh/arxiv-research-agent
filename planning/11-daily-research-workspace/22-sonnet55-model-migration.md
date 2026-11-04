# Sonnet5.5 request migration — offline preparation

The owner selected Sonnet5.5 for subsequent API requests on2026-11-04. This
separate checkout preserves the exact06c593f code, V2 packet and receipts of the
stopped Sonnet4.6 experiment. It does not modify the running daily workspace or
controller frontend, install an approval, contact a provider, enable recurrence
or qualify the checker. All preparation/tests use the disabled-key sentinel.

## Compatible, sealed request shape

The qualification route is now `claude-sonnet-5-5`, adapter revision
`workspace-qualification-adapter-v3-sonnet55`, packet revision
`workspace-qualification-packet-v3-sonnet55`. No fallback or substitution exists.
Anthropic's [model page](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)
and [migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide)
were checked2026-11-04. Sampling fields are omitted because the model rejects
them. Explicit `thinking: {"type":"between_tools"}` avoids default up-front
thinking; medium effort is pinned for draft, checker, repair and recheck. No
tools are supplied, so this documented mode returns text only. Adaptive thinking
is not silently enabled. Model/settings/schema/selected evidence changes still
fail binding before transport construction. V2 packets and4.6 approvals refuse.

Standard global rate estimates are now $2/MTok input and $10/MTok output,
excluding caching, batch, fast or geographic premiums; no such options are
requested. The original caps remain8k/1.2k tokens per summary call and12k/2.4k
per study call. Four calls cost at most $0.112 per summary or $0.192 per study;
three summaries plus one study total $0.528, or $0.660 with1.25× headroom.
These are design bounds, not measured tokens or invoices. Job ceilings remain
$0.25/$0.40; total/day/month ceiling remains $1.25. No budget was reset.

The same four public contexts were read from the isolated experiment database
in transaction-read-only mode. ReAct is still its three selected page3 spans;
no new source, page or private context was added. The newly exported exact
bodies and digest manifest are at `outputs/qualification-sonnet55/trial-packet.json`
and in [the proposal](generation-trial.proposal.json). Output stays unapproved;
human labels remain blank. Sonnet4.6 counts cannot transfer to5.5's tokenizer.

## Stopped experiment remains a blocker

The prior run completed five counts and one Message. The Message hit the1200
output-token cap with incomplete JSON; no checker/repair/recheck ran. Reported
usage2443input/1200output accounts for $0.025329, with an additional conservative
$0.224671 unknown hold retained. Four recoverable partial claim objects also
fail exact quote-to-offset matching. This model migration repairs neither issue.
There is no accepted summary/study and no human/checker quality measurement.

Within the original16Messages/20counts scope,15Messages/15counts remain.
New model digests and request IDs do not authorize replaying the old uncertain
contact or resetting counters. Before dispatch: reconcile the old hold through
an audited decision, fix and test the response-size/reference contract, reseal
the exact compatible requests and explicitly account for prior contacts/spend
in the execution authorization. Do not enable or run the candidate four-job
packet merely because model choice or an API key is available.

## Verification and remaining work

The migrated transport fixtures require5.5 on every count/Message, no sampling
parameters, explicit between_tools and medium effort. Existing full draft →
check → repair → recheck fixtures still validate wire/local schemas. Targeted
regressions cover changed thinking/effort, V2 rejection, old-model approval
refusal, selected-span fences, separate role accounting and conservative recovery.
All are mechanical/synthetic evidence. Actual5.5 access, tokenization, remote
schema acceptance, output completeness, factual support and usefulness remain
unmeasured. Local command results are recorded in STATUS, not called remote CI.
