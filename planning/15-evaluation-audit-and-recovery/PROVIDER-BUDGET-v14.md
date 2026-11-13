# D5 v14 provider budget and readiness

This is a prospective machine-only plan, not an approval or live-run result. The stopped v13 scope remains immutable. A fresh preactivation ledger census, final packet and code gates, and explicit owner approval are required. The first production-path PostgreSQL replay passed at integration commit `618ade960a3b962eb72d3bdb487a9effc62570c4`; the full 14-job replay and remaining gates are still in progress. Mocked replay does not prove provider schema acceptance or evaluation quality.

## Capacity and whole-envelope exposure

The preserved v13 final stop receipt records 35 funded jobs, 68 Messages calls, 93 counts, and $1.986755 in known estimated usage. The $0.875066 pending and unknown totals overlap and consist of two different unresolved holds: $0.425066 for an unknown upstream contact and $0.45 for a complete HTTP 400 response whose usage was not validated. Count each hold once. Neither has been settled or assumed to be zero. A future quarantine decision must bind each case separately; it cannot resume v13 or authorize replay of the old contacts.

| Resource | Recorded baseline | Maximum new scope | Required cumulative | Active ceiling |
| --- | ---: | ---: | ---: | ---: |
| Funded jobs | 35 | 14 | 49 | 47 |
| Messages | 68 | 44 | 112 | 109 |
| Paired token counts | 93 | 44 | 137 | 134 |

The 14 jobs comprise two development workflows, eight evaluation workflows, and four probe batches with 20 balanced machine-reference probes. Each actual Messages call requires a paired provider count of the bound request; the 44 counts are included above, with no separate Stage A. The count response must fit the 16,000-input-token limit. Exact pairing refers to binding the count to the intended request: Anthropic describes token counting as an estimate, so it is not actual billed usage. See [token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting). A 20,000-token input allowance is a conservative reservation assumption, not the fit threshold or a measurement.

| Whole-envelope planning component | USD |
| --- | ---: |
| Known estimated historical usage | 1.986755 |
| Both retained holds, counted once | 0.875066 |
| Maximum new rounded reservations | 7.50 |
| Existing planning buffer | 1.00 |
| Total | 11.361821 |

The active $10 cumulative ceiling fails even without the buffer: $1.986755 + $0.875066 + $7.50 = $10.361821. A $12 cumulative ceiling is proposed, with concurrency one. The buffer does not authorize additional jobs or calls. Reservations are future exposure, not realized spend; reconcile them against actual usage and retain uncertain liability without double counting.

## Rates and reservations

The planning calculation assumes standard uncached input and output pricing, no fast-mode premium, and the limits below. [Anthropic's pricing page](https://platform.claude.com/docs/en/about-claude/pricing) lists these rates in US dollars per million tokens; verify the final sealed route, pricing and any additional charges before approval.

| Route | Input / million | Output / million | Assumed input / call | Output ceiling / call | Reservation / call |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sonnet 5.5 draft or repair | $2 | $10 | 20,000 | 4,000 | $0.08 |
| Opus 5.5 adaptive High check, recheck or probe | $4 | $20 | 20,000 | 8,000 | $0.24 |

One maximal-repair workflow has two Sonnet calls and two Opus calls: $0.64, rounded upward to $0.65. Each probe has one Opus call: $0.24, rounded upward to $0.25. Ten maximal workflows and four probes comprise at most 20 Sonnet plus 24 Opus calls, or 44 Messages and their 44 paired counts. Their unrounded total is $7.36; the rounded per-job envelope is **$7.50**. Repairs are conditional; a check is mandatory and any repair requires a recheck.

The 8,000-token Opus output ceiling includes both thinking and final response, not 8,000 tokens for each. Anthropic states that thinking is billed as output and counts toward `max_tokens` ([thinking documentation](https://platform.claude.com/docs/en/build-with-claude/thinking)). Actual thinking and output vary; the ceiling and reservation are not measured usage or a guarantee of a complete checker response. Record provider-reported usage separately, and retain a full hold when usage cannot be validated under the accounting policy. The earlier incomplete 3,200-token checker response does not establish that 8,000 will succeed.

## Readiness and expiry

Before evaluation or probes, both development workflows must pass the remote schema and complete input-bound final checker contract after their latest draft or repair. A complete negative quality verdict remains a failed quality outcome but is not a broken contract. A broken development contract, provider error, accounting or binding drift, new uncertainty, expiry, or another sealed hard stop halts dispatch. A fully metered evaluation content failure may continue only as allowed by the sealed stop policy. No automatic retries are authorized by this proposal.

The existing programme deadline is **2026-11-14 07:24:01 UTC** (2026-11-13 23:24:01 PST). At the 2026-11-13 10:40:47 UTC clock check it was 20 hours, 43 minutes and 14 seconds away. Recheck the clock and authority before activation and each dispatch. The prospective approval expires at the earlier of 24 hours after approval or that existing deadline. If the deadline has passed or the gates cannot fit, a separate explicit owner decision with a new deadline and scope is required; no extension is automatic.

The prospective approval must bind the final packet, application, published head, capacity and exception proposal, both holds, limits, contract gate and expiry. It does not authorize human qualification, everyday generation, recurrence, notifications, merge or deployment.
