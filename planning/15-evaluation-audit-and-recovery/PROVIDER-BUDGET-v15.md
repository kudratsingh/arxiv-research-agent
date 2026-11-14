# Prospective D5 v15 provider budget

This is a proposal and arithmetic review, not a grant, dispatch, measurement, settlement or quality result. It assumes the supplied frozen baseline of 36 jobs, 70 messages, 95 counts, $2.110597 actual, $0.875066 retained unknown holds, zero active work and no new uncertainty. A fresh authorized read-only preactivation census and reconciliation against immutable evidence are required; do not replace the holds with zero or infer cancellation. The stopped v14 evidence remains immutable.

Anthropic's [official model pricing](https://platform.claude.com/docs/en/about-claude/pricing) was checked read-only on 2026-11-14 UTC: standard Sonnet 5.5 is $2 input / $10 output and Opus 5.5 $4 input / $20 output per million tokens. The estimates below assume these exact standard rates, no cache writes, no fast mode or geographic surcharge, no extra tools, and no retries. The sealed wire must establish those assumptions; price or option drift requires a new estimate and approval, not silent use of this table. Counts and outputs are reserved independently of whether a provider call succeeds. Output tokens include model thinking. Quoted rates are not evidence of provider availability, acceptance, or eventual charges.

| Envelope | Input/output reservation | Calculation | Maximum estimated cost |
|---|---:|---:|---:|
| One Sonnet draft or repair | 40,000 / 8,000 tokens | 40,000 × $2/M + 8,000 × $10/M | $0.160000 |
| One Opus check, recheck, or probe batch | 40,000 / 12,000 tokens | 40,000 × $4/M + 12,000 × $20/M | $0.400000 |
| One full workflow | 2 Sonnet + 2 Opus | 2 × $0.16 + 2 × $0.40 | $1.120000 |
| Ten full workflows + four probe batches | 20 Sonnet + 24 Opus | 10 × $1.12 + 4 × $0.40 | $12.800000 |
| Rounded individual caps | 10 × $1.20 + 4 × $0.50 | Maximum authorized new scope, if separately granted | $14.000000 |

A bound count of at most 32,000 input tokens must precede each message; 40,000 input tokens per message is the conservative reservation, not a promised usable prompt size. Four count calls plus four messages per workflow and one count plus one message per probe yield 14 new jobs, at most 44 messages and 44 counts: proposed cumulative 50 jobs, 114 messages and 139 counts. The proposed programme ceilings 64 jobs, 160 messages and 200 counts provide headroom for accounting and admission, **not permission to run extra identities or contacts**. No automatic retry or replacement identity is implied.

| Programme budget composition | USD |
|---|---:|
| Prior known actual | 2.110597 |
| Full retained unknown holds | 0.875066 |
| Sum of prospective individual caps | 14.000000 |
| Additional buffer | 2.000000 |
| Total exposure at the stated caps and buffer | **19.985663** |
| Remaining under proposed $20.00 programme ceiling | **0.014337** |

The $12.80 calculated envelope and $14 rounded caps are alternatives in this comparison, not amounts to add together. The $2 buffer is included only once. The hold is retained once as unresolved potential liability; accounting rules must prevent double-counting any overlapping pending reserve while still retaining the full unresolved amount. The margin is only 1.4337 cents: even small unaccounted charges or drift can consume it. A higher ceiling or lower scope requires a fresh exact decision. Do not change the historic holds or reinterpret them as actual charges. This is an upper bound on model token charges under the stated rates and route assumptions, not a guarantee of invoices, latency, or token fit.

Proposed stage deadlines are count 60 seconds, draft/repair 120 seconds, check/recheck 240 seconds, and 1,200 seconds for the whole workflow from the durable reservation. Four counts plus two drafts and two checks total 960 seconds at their individual maximums, leaving 240 seconds of theoretical workflow time for all other overhead; it is not an availability guarantee. Every call remains bounded by the remaining workflow deadline. A local timeout or cancel cannot prove remote cancellation or erase exposure.

The current programme expiry was reported as 07:24 UTC and may expire before readiness; verify the actual sealed expiry during the fresh census. Propose a seven-day programme extension and a distinct 24-hour campaign grant only upon explicit future owner approval, with absolute UTC start/end times and exact frozen scope in the grant. Neither this proposal nor extending a programme creates dispatch authority. Gate on complete integration, final frozen identity, no new uncertainty, sufficient capacity, exact prices and route, and explicit approval. Stop on drift, uncertainty, provider error, expiry, cancellation, exhausted limits, or broken development contract; retain every original receipt and unresolved hold.

At review time `src/workspace/d5_capacity_policy.py` was a prospective untracked policy object, not proof the existing execution path enforced it. Existing `GenerationInput.snapshot` limits serialized input to 32,000 characters (`src/workspace/admission.py:98–130`); route validation accepts older route sets (`src/workspace/d5_operations.py:46`), and the D5 adapter pins historical input and transport values (`src/workspace/d5_adapter.py:535`). Provider count admission uses 80% of `settings["input_tokens"]` (`src/workspace/provider_adapter.py:589`, `:733`). These must be integrated and verified at the exact final head, along with reservations, report/probe paths, and conservative recovery. Large byte bounds do not prove 32,000-token fit. The final policy, packet, counts and authority must agree; no contact is authorized by this document.
