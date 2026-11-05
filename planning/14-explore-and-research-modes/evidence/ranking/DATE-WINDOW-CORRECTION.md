# Explicit date-window eligibility correction

This supersedes only the explicit `days>0` eligibility clause in the original
[protocol](PROTOCOL.md). The app and its API tests require a known aware
publication/update date within a selected date window. The original comparator
kept unknown dates in that window, so its eligible pool could diverge from the app.

The corrected comparator applies the same rule: `days>0` excludes unknown,
invalid, naive and out-of-window dates. `days=0` still retains unknown dates,
which remain last and unscored in the chronological diagnostic. Update-before-
publication precedence and the prohibition on inferred announcement/acquisition/
identifier dates are unchanged. No ranking formula, score, mode policy, weight,
question, quality threshold or owner label changes.

[The correction receipt](date-window-correction-receipt.json) was written before
the code change or any new public-pool comparison. It maps original tool/test/
protocol/manifest paths to exact byte-preserved `.py.txt`/Markdown/JSON snapshots
and hashes under `archive/pre-date-window-correction/`. The initial development
v1/v2 reports use `days=0` and remain intact. No new public-pool comparison was
needed for this correction; targeted synthetic positive/negative tests cover the
shared API eligibility rule. Future report exports identify tool report revision
`workspace-mode-ranking-development-report-v2-date-window`.
