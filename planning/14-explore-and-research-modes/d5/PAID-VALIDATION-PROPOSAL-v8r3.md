# D5 v8r3 — reconciled-ledger qualification proposal

**UNAPPROVED, UNEXECUTED. Preparation made zero provider Messages / count contacts,
USD 0 new spend and no live authorization/cap change.**

Application/source baseline `d3a1d05297a7aa4c93f0f7ff6f492030bd06d36e`; prepared from published
`bc36c721888a72d048debf5158de2ce9d8367b3b` with source/scorer hashes unchanged.
New packet **`42aa787ca0aa9e22dd92a6eddb5a7b8642a9f8364526bccf3af66b3947de2b4c`**. New scope
`d5-42aa787ca0aa9e22dd92a6ed`. [Packet](evidence/qualification-v8r3/packet.json.gz),
[refresh receipt](evidence/qualification-v8r3/REFRESH-RECEIPT.json),
[budget](evidence/qualification-v8r3/BUDGET.json), [offline and conditional operator commands](RUNBOOK-v8r3.md).

## Reconciled basis and cohort preservation

Active database `workspace_d5_prose_v6_validation`, programme
`research-evaluation-20261105-v1`: **20 programme jobs, 35 Messages, 54 counts,
USD 0.904053 estimated**, workflow USD 0.285853/checker USD 0.618200, pending/unknown 0.
Effective caps remain **24 jobs / 80 Messages / 80 counts / USD 10/concurrency 1**.
Programme/amendment expiry remains **2026-11-14T07:24:01Z**; no renewal.

The metadata-only refresh preserves the frozen corpus, profile, clock, questions,
rankings, selected evidence, schemas, prompts, scoring/human rubric and stop rules.
No new intake, no source expansion, no new v8 outputs and no threshold tuning.
The archived profile remains the original frozen owner-interest profile, not a
fresh read or edit of owner3137 preferences.

- Original v7r2 remains a separate **3/8 stopped diagnostic**, one failed and four
  unrun cases; no replay or retrospective success credit.
- The four-probe premise diagnostic remains separate: 4/4 completed,
  false passes 0/2, false rejects 0/2, new USD 0.078988. Those calls/costs are already
  included once in USD 0.904053; do not add the old USD 0.60 reservation again.
  Four opinions on one claim do not fill the system 20-fact/20-probe minima.
- Refreshed held-out source versions have **no overlap** with that calibration
  source version. The existing 14-version v7r2 exclusion partition is unchanged.
- All v8r2 packet/snapshot artifacts remain immutable. New packet predecessor:
  `1037d63e7c1a68a6f6a8c77d2c59d32ac8bb682cebf329485d1463551847ef2a`.

The complete financial replay now includes private prereview proofs. It remains
local at `outputs/d5/v8-ledger-refresh/private-replay-v1/FINANCIAL-REPLAY-PRIVATE.json.gz`,
mode 0600 in a mode 0700 directory. Only its hash, aggregate history and frozen public
requests are published. Do not commit or send the raw financial replay/reviews.
The new disposable verification DB has a permanent provider-disabled marker and
zero operative budget policies/new scope grants.

## Exact separately approved A and B scopes

| Scope | Named cases | New jobs | Messages max | Counts max | New reservation |
|---|---|---:|---:|---:|---:|
| A | measure-1: initial dev-compare count |0|0|1|USD 0|
| B, only after A review | dev-learn, then dev-compare |2|8|8|USD 0.90|
| A+B maximum cumulative | — |22|43|63|USD 1.804053 history+reservation|

[Exact A scope](evidence/qualification-v8r3/STAGE-A-SCOPE.json),
[copyable A-only approval request](evidence/qualification-v8r3/STAGE-A-APPROVAL-REQUEST.md),
[approved=false operator template](evidence/qualification-v8r3/STAGE-A-OPERATOR-TEMPLATE.json).
One exact count request, model `claude-sonnet-5-5`; digest
`046b08e4a147c46dd07d950ad973f484c1bdd4c297424566fea6517de9ce5216`.
No old completed count matches it. Its equality to the prior **unexecuted** v8r2
export does not provide a measurement. A measures token fit only; it does not
establish Messages-schema acceptance or content/checker quality.

[Exact B scope](evidence/qualification-v8r3/STAGE-B-SCOPE.json),
[copyable conditional B-only approval request](evidence/qualification-v8r3/STAGE-B-APPROVAL-REQUEST.md).
Both cases remain development, not held-out. Learn exercises the repaired
single-paper explanation/neutral follow-ups; Compare exercises independently
cited multi-source bases and comparison limits. Initial wire digests:

- Learn `3f28827518a1f1d6e6f6f5b4cfcbb7c9513368588c55a92a4c683530f07c9714`.
- Compare `219f2c5670ba7b193e480c9258da85258d4d57202030e844059389e34dcabe44`.

B requires successful input-bound A, an active unexpired parent and a later
separate B grant. At most one repair and mandatory recheck per workflow.
Exact dynamic checker/repair bodies cannot exist before actual prior outputs;
their templates, schemas, source selection, code and limits are frozen now, and
exact request digests must be recorded before each paired count/dispatch.
No stopped result is replayed, no measurement is reused across different bodies,
and a failed/uncertain contact still consumes its relevant allowance.

Routes unchanged: Sonnet 5.5 between-tools/medium, 4,000 output for drafts/repairs;
Opus 5.5 adaptive/high, 3,200 output including thinking for checks/rechecks/probes.
Each measured input must fit 16,000 tokens against 20,000 raw admission headroom.
No current token estimate is invented. Both A and B fit current caps without an
amendment. Each grant window is the earlier of 24 hours after explicit approval,
its existing parent expiry and 2026-11-14T07:24:01Z. Stop if expired/revoked; never
silently renew or create alternate identities.

## Full schedule and separate capacity decision

| Stage | Jobs | Messages max | Counts max | Reservation USD |
|---|---:|---:|---:|---:|
| A |0|0|1|0|
| B |2|8|8|0.90|
| C: eight frozen held-out workflows |8|32|32|3.60|
| D: four fixed five-item probe batches |4|4|4|0.60|
| New full schedule |14|44|45|5.10|
| Cumulative maximum |**34**|**79**|**99**|History included below|

[Combined job/count amendment proposal](evidence/qualification-v8r3/CAPACITY-AMENDMENT-PROPOSAL.json):
**24→34 jobs (+10), 80→99 counts (+19)**. Keep 80 Messages, USD 10, concurrency 1,
all predecessor receipts, liabilities and programme expiry unchanged.
Proposal digest **`3f47029086fd846968aa93f14f64a693739b5bc1485d4fbb4a2f3793ec4662ef`**. This is not activated and grants no
A/B/C/D execution. There is no spare-case or automatic retry allowance.

**Implementation prerequisite:** existing amendment recorders only change job
caps; they cannot activate a count cap of 99. A separately reviewed, versioned job/count
policy extension and its boundary/revocation/history tests are required before
full-schedule activation. Freeze any changed producer code before paid A/B when
possible. If ledger-guard code changes after paid development, do an explicit
request/source/code/receipt-reuse audit and successor freeze; never silently
attach old jobs / results to a new packet. Resolving this extension before paid
A/B avoids that later binding risk. The present A/B scopes remain concrete and
runnable on current code/current caps after their separate approvals.

At sealed **ESTIMATE** rates (Sonnet USD 2/10, Opus USD 4/20 per million input/output),
a full four-stage workflow has USD 0.448 usage bound and USD 0.45 reservation;
a probe USD 0.144 usage bound/USD 0.15 reservation. New full usage bound USD 5.056;
reserve USD 5.10. Historical USD 0.904053 + reserve USD 5.10 + unchanged USD 1 buffer
= **USD 7.004053**, within the unchanged USD 10 ceiling. No double counting of
released calibration holds, no new spend authorization. These are bounds, not
measured v8 costs or invoice verification. Recheck official pricing before any
later separately approved dispatch; drift stops, not silently substitutes.
Reference: https://platform.claude.com/docs/en/about-claude/pricing .

## Unchanged evidence gates

Eight-of-eight held-out completion; 20 fully reviewed factual items and 20 decisive
adversarial items; zero observed false passes; missing/unreviewed/empty denominators
remain HOLD/UNSCORED. Seven potentially answerable cases permit 42 claim slots at
six each; 20 reviewed eligible facts are feasible, not guaranteed. The eighth case
must abstain appropriately on an unspecified controller/vehicle/envelope.
Four D batches provide 20 proposed items; human judgments remain blank. Do not add
cases or reduce thresholds after results. The four earlier premise prelabels
and development results cannot fill these minima. Small correlated samples do
not establish general checker reliability or personal everyday usefulness.

C and D each require their own later approval and successful prerequisites.
Everyday generation, recurrence and notifications remain disabled. Owner3137 and
review3178, data/preferences and the old scopes are untouched. Nothing here
records an amendment, approval, reservation or provider contact.
