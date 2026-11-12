# Unexecuted one-case deadline validation proposal

**Blocked by unresolved external completion. Not an approval request to dispatch
now.** No grant, accounting mutation, provider/count contact, cap change, expiry
change or spend is authorized by this document.

Review candidate packet:
`079748d34931142270f947038df90dc1dcae135adf0b1b88d153324d3a1a5ef3`,
application `92c5a9eafa81bbaa279a5b44312f1519a1bd522c`,
[packet](evidence/operation-deadlines-v11/packet.json.gz),
[compiled inputs](evidence/operation-deadlines-v11/compiled-inputs.json.gz).
It seals the actual uncertain checkpoint and `reconciliation_required=true`.
The operator and existing external authorization guard refuse that checkpoint.
After genuine reconciliation, a new revision must bind the actual new history
before the owner can approve any live experiment. This candidate cannot be
silently made runnable by clearing its flag.

## Smallest useful prospective scope

One fresh development case, `development-v11-learn-deadlines`, tests the Learn
path with the unchanged v10 coverage-authority response contract and the proposed
deadline policy. Keep the old run uncertain, not replayed. Human qualification
and Stage C/D remain out of scope. It cannot establish Research comparison
quality, general checker reliability, real repair latency unless a repair occurs,
or everyday usefulness.

| Stage | Maximum new funded jobs | Messages | Counts | New spend bound |
| --- | ---: | ---: | ---: | ---: |
| A, separate future approval | 0 | 0 | 1 preliminary count | $0 |
| B, separate future approval | 1 | 4 | 4 exact paired counts | $0.45 |
| Both, after resolution | 1 | 4 | 5 | $0.45 |

From 33 / 65 / 90, this reaches at most **34 jobs / 69 Messages / 95 counts**.
Existing programme caps remain **34 / 80 / 99 / $10**, concurrency one. This uses
the last funded slot; unused dollars do not authorize further work. No capacity
or expiry amendment is proposed. Future grants must expire no later than
2026-11-14T07:24:01Z and cannot renew the revoked/expired v10 scope.

## Monetary envelope and settings

| Operation | Maximum input admitted | Output cap | Sealed estimate rates, input/output per million | Reservation |
| --- | ---: | ---: | --- | ---: |
| Sonnet 5.5 draft or repair | 16,000 measured; 20,000 conservative bound | 4,000 | $2 / $10 | $0.080 each |
| Opus 5.5 adaptive High check or recheck | 16,000 measured; 20,000 conservative bound | 3,200 including thinking | $4 / $20 | $0.144 each |
| Complete draft/check/repair/recheck | — | — | historical sealed estimates | $0.448, within $0.45 |

These are unchanged estimates sealed on 2026-11-06, not newly verified prices or
an invoice. Any future approval preflight must recheck documented pricing without
silently changing the sealed rates. Historical known spend $1.853811 plus the
single overlapping $0.425066 hold plus a prospective $0.45 is **$2.728877**;
with the existing $1 headroom, **$3.728877**, below $10. This arithmetic does not
permit admission while uncertain or predict the eventual reconciled usage.

Count/draft/repair remain 30 seconds; check/recheck 120 seconds; overall workflow
480 seconds from persisted reservation creation. One repair maximum, mandatory
check, mandatory recheck after repair, concurrency one, no automatic retries.
Whole-claim, prose, coverage, atomicity, qualification and exact provenance gates
remain. Dynamic checker/repair bodies are derived from actual preceding output
under the frozen templates, then sealed and measured before dispatch. No future
response-dependent request digest is invented.

## Preliminary measurement audit

[Read-only audit](evidence/operation-deadlines-v11/MEASUREMENT-AUDIT.json) verifies
the historical real Stage A receipt against the candidate with the production
no-dispatch exact-body verifier. Its 7,877-token result matches count digest
`80fb9cb6f20ee54c95a2bd77ee93c6115bb4c34e8644fe8eeb30ab77e3766f08`,
model/settings/schema/source selection and generation wire body. The new deadline
policy is non-wire metadata. Historical job and authorization remain unchanged.
This proves technical exact-body eligibility, not current authorization.

The candidate retains the narrower existing fresh-scope Stage A requirement and
has no active cross-scope reuse map. Therefore this conservative proposal budgets
one fresh preliminary count. It does not retag the old receipt or bypass that
guard. Reuse would require an explicitly reviewed versioned scope mechanism and
approval; it is unnecessary for this bounded proposal. Every new Messages call
still requires an exact paired count, even if preliminary measurement is reused.

## Future approval sequence, after prerequisites

1. Resolve the old contact through the separate evidence-backed accounting plan.
2. Capture actual post-resolution history and seal a successor against final code,
   exact source/schema/settings and unchanged limits. Verify remaining expiry.
3. Bring the new digest and exact preliminary count body back for **A-only**
   approval, then return the actual count and ledger. No Messages in A.
4. Bring the same sealed case and actual A receipt back for separate **B-only**
   approval: one job, up to four Messages/four paired counts, $0.45 all-in.
5. Run only after that approval, stop on first drift/refusal/provider/contract or
   uncertain failure, preserve all receipts and return quarantined outputs.

The [offline commands](OPERATION-DEADLINES.md#offline-verification-commands) are
runnable now. Paid commands are deliberately not armed: a blocked baseline has
no valid preparation receipt or grant. No synthetic test authorization can be
copied into the live ledger. Everyday generation, recurrence and notifications
remain disabled.
