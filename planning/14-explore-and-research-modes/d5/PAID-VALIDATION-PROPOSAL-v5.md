# D5 v5 Sonnet / Opus High proposal — UNAPPROVED

This is an offline candidate. **No new authorization, Messages contact, token-count contact or spend** occurred. The original programme is still capped at20 jobs. Stage B, C and D require separate explicit approvals. Everyday generation, recurrence and notifications remain disabled. Owner3137, review3178 and the existing previews are unchanged.

Packet [d5-system-validation-v5.json.gz](d5-system-validation-v5.json.gz):
`85afa214bd4634ca27e668470257b9ecb53b2dfe87fa018ec17856e46729b35b`.
Application `04945c61454f57b8597255587537db068951b12d`.
[Full bindings](d5-packet-identity-v5.json), [exact receipt audit](evidence/opus-checker-v5/binding-audit.json), [offline report/runbook](OPUS-CHECKER-v5.md).
V4 packet `f21f4b66e1eb99ab75c7c242a9bfa46acb78ccabc13fb885477e8160425fd95a`, its completed A receipts, stopped v3 result and [v4 proposal](PAID-VALIDATION-PROPOSAL-v4.md) remain historical. No failed job is replayed or removed.

## Separate prerequisite: programme job amendment

[Programme amendment v1](programme-job-amendment-v1.json) is **approved=false**, proposal digest `ef06dd6b87a565a205e722bfcf0062a102f345ead435095aaff2a3f65684943b`. It binds original programme `research-evaluation-20261105-v1`, authorization `791c57d58f6425a14845d18b6563200e932b3869de59805b586727916fbff7ae`, original parent/baseline, membership and the exact current ledger census. It changes only funded programme jobs20→21. The original policy row remains20; a separately recorded, versioned, revocable receipt provides the effective21 cap only for that programme. It does not authorize any workflow, contact or dollar of spending.

The live read-only census is7 funded programme jobs (8 identities including the parent),10 Messages,24 counts, estimatedUSD0.125611 (workflow0.110299/checker0.015312), pending/unknown0. The stopped v3 funded identity and all prior receipts remain. Thirteen jobs remain under20; B2+C8+D4 needs14. The amendment provides exactly that final slot. Money staysUSD10, Messages/counts80/80, concurrency1; existing holds and all quality thresholds are unchanged. **Do not activate this candidate without the owner's separate approval.** A changed census requires stop/review rather than rebasing the receipt automatically.

## Routes and sealed contracts

| Operation | Model | Thinking / effort | Raw input / paired count allowance | Output including thinking | Timeout | Estimated USD per million input / output |
|---|---|---|---|---:|---:|---|
| Draft, repair | claude-sonnet-5-5 | between_tools / medium |20000 /16000|4000|30s|2 /10|
| Check, recheck, all four D probe batches | claude-opus-5-5 | adaptive / high |20000 /16000|**3200**|30s|4 /20|

No temperature, cache, batch, premium speed, regional surcharge, tools, source expansion, model fallback or automatic HTTP retry. Every actual stage has its own exact paired count; a Sonnet count cannot admit an Opus request. Output cap includes adaptive thinking and the structured verdict. Recommend3200 to leave more verdict room than1800; this is **not measured fit**. The30s timeout and131072-byte response bound are unchanged and can still cause a Stage B stop. The adapter accepts one text verdict after optional thinking/redacted-thinking blocks, preserves the entire journal, and refuses partial/multiple/invalid verdicts.

Local and transformed schemas, selected evidence handles, exact sources/versions/material hashes/parser/Unicode offsets, project revision, prompts, settings, producer and scorer hashes are sealed in the packet/compiled inputs. Optional factual prose, whole-claim support and selected-span enforcement remain mandatory. Draft/check/repair/recheck wires derive from actual preceding responses under those frozen templates; future response-dependent request digests are recorded when created, never fabricated in advance. Private notes, preferences, reading history and drafts are excluded from remote context.

Official standard global rates and settings were checked using public documentation on2026-11-06 Pacific: [pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Opus5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview), [adaptive-thinking compatibility](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide), [effort](https://platform.claude.com/docs/en/build-with-claude/effort), [Sonnet5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview). Prices remain **ESTIMATE**, not invoice verification; recheck before future dispatch and stop on a mismatch. No model API was contacted for this verification.

## Exact Stage A reuse

The following are historical provider estimates, not new contacts. The [binding audit](evidence/opus-checker-v5/binding-audit.json) compares both full generation-body and actual count-body digests, model, thinking/effort, output allowance, prompt, local/wire schema, selected source/version/hash/offsets and the original authorization/contact/result identities. Every original job/receipt stays attached to v4. Changed bodies/settings require fresh count-only approval; corrupt or oversized historical receipts stop instead of triggering an adaptive recount.

| Receipt | Exact Sonnet initial request | Historical input estimate | Allowance | Reuse |
|---|---|---:|---:|---|
| measure-1 |dev-learn|2568|16000|yes|
| measure-2 |dev-compare|3753|16000|yes|
| measure-3 |research-retrieval|3718|16000|yes|
| measure-4 |research-insufficient|3364|16000|yes|

**Fresh preliminary count-only requests required: none.** Historical A completion gives no successor permission and proves no Opus token fit, remote schema acceptance or verdict quality. Stage B must establish those through its permitted paired counts/checks. Sonnet draft/repair settings and exact initial request bodies are unchanged.

## Usage bounds, reservations and feasibility

All usage bounds below charge20000 input tokens per call, including the25% margin over the16000 measured allowance; all declared output tokens, thinking included, are charged. Full repair/recheck is reserved before draft dispatch. Known workflow/checker spending and unknown liability remain separate. Mock counts are synthetic integers, never token measurements.

| Unit | Messages / paired counts max | Output tokens max | Usage bound USD | Reservation / proposed ceiling USD |
|---|---:|---:|---:|---:|
| Sonnet draft or repair |1 /1|4000|0.080|included in job|
| Opus check, recheck or probe |1 /1|3200|0.144|included in job|
| Complete workflow including repair/recheck |4 /4|14400|0.448|**0.45**|
| One probe batch |1 /1|3200|0.144|**0.15**|
| B: two development jobs |8 /8|28800|0.896|**0.90**|
| C: eight held-out jobs |32 /32|115200|3.584|3.60|
| D: four probe batches |4 /4|12800|0.576|0.60|
| B–D total,14 funded jobs |44 /44|156800|**5.056**|**5.10**|
| Plus historical0.125611 and existing1.00 buffer |cumulative54 /68|—|**6.181611**|**6.225611**|

At1800 Opus output tokens the identical full schedule boundsUSD4.384;3200 addsUSD0.672 (24 Opus calls×1400 tokens×USD20/million). Rounded reservations leaveUSD3.774389 of the unchangedUSD10 ceiling beyond history and the buffer. Reservations are admitted one job at a time, not permission to spend unused capacity. Stage B alone has a hard new ceilingUSD0.90 andUSD0.45 per job; these replace neither existing live authorizations nor the oldUSD0.40/0.08 limits. They require explicit prospective approval. Eight B Messages/eight paired counts would take the real ledger at most to18/32,9 programme jobs andUSD1.025611 estimated cumulative. No standalone measurement pass is proposed.

## Cohorts and quality rules unchanged

B: `dev-learn`, then `dev-compare`; development only, outside held-out denominators. C: `learn-method`, `learn-assumptions`, `learn-build`, `learn-results`, `research-memory`, `research-retrieval`, `research-evaluation`, `research-insufficient`. D: `probe-1` through `probe-4`, five machine-proposed adversarial items per batch, not assumed human gold. The eight fresh cases, all four batches, full20-reviewed-fact/20-decisive-reviewed-probe minimums,8/8 completion and zero false-pass rule remain. Seven potentially answerable cases×six claims gives42 possible fact slots; reaching20 is feasible but not guaranteed. If results/reviews fall short, HOLD; do not add cases, lower minimums or count development facts. Human usefulness and support labels remain blank. This small trial cannot statistically certify checker reliability, fresh intake, full-paper extraction or everyday usefulness. Retained40-work/42-material inputs and the two bounded PDF samples keep their existing limitations.

## Copyable Stage B-only approval request — not an approval

> After separately reviewing/approving programme amendment `ef06dd6b87a565a205e722bfcf0062a102f345ead435095aaff2a3f65684943b`, please approve **Stage B only** for D5 v5 packet `85afa214bd4634ca27e668470257b9ecb53b2dfe87fa018ec17856e46729b35b`, application `04945c61454f57b8597255587537db068951b12d`. Use a fresh B-only external authorization, with its own stated expiry, and a verified single-active-ledger handoff preserving7 programme jobs,10 Messages,24 counts andUSD0.125611. Run only `dev-learn` then `dev-compare`: two new funded development identities, at most8 Messages and8 exact paired counts,USD0.45 all-in per job andUSD0.90 maximum new spend, including mandatory checking and at most one repair/recheck. Draft/repair use sealed Sonnet5.5 between_tools/medium; check/recheck use Opus5.5 adaptive/high with3200 output tokens including thinking. Reuse only the four audited exact v4 Sonnet A receipts; do not rerun A. One job/call at a time, no retries/substitution/extra context. Stop on the first provider/contract/admission/accounting failure, uncertain completion, drift, cancellation, revocation or expiry. Preserve failures and historical receipts. Human labels stay blank. **No Stage C/D, everyday generation or recurrence. Stop after B for review.**

This request is distinct from the amendment approval. Neither this proposal, a key, old A permission, mock authorization nor remaining budget activates either decision. [Runnable offline and future operator commands](OPUS-CHECKER-v5.md). Future activation/paid commands below that runbook's boundary remain **unexecuted**.
