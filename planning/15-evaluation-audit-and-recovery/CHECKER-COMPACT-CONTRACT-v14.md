# Prospective compact COMPLETE checker contract v14

This is an offline candidate contract, based on `bcabf8f048cc4469b29987f48c6d3c506d7166f9`.
It grants no provider execution or token-count authority. Historical responses,
check models, campaign packets and measurements remain immutable. The checker
model and High effort setting are caller policy; this module changes neither.

`src/workspace/assistance_compact_checks.py` exports `wire_model()`, `schemas()`,
`normalize(raw)` and a synthetic-only `compact_fixture(normalized)` inverse.
The wire revision is `workspace-assistance-compact-checks-v14`; the expansion
identity is `workspace-assistance-compact-checks-normalization-v14`. Bind both
identities and exact schemas/source to prospective execution and report receipts.

Each `claim_reviews` record carries claim ID, input digest, support decision,
atomicity, the four explicit qualification dimensions (`study_scope`,
`comparator`, `metric_definition`, `conditions`) and one shared reason.
Normalization deterministically expands the same identity and reason into the
unchanged `CoverageChecks.checks` and `.claim_quality` rows. All per-part coverage
checks, located prose findings and priority judgments remain mandatory. Cardinality
stays at six claims, eight parts and ten prose findings. A missing field never
implies a passing judgment.

Reasons are nonblank, at most 96 Unicode characters, 120 UTF-8 bytes and 120
JSON-encoded UTF-8 bytes excluding the surrounding quotes. The serialized bound
covers escaping as well as Unicode. A reason should identify the material evidence
or unresolved issue across the row's judgments. The synthetic inverse refuses
distinct support/quality reasons or unequal/ differently ordered bindings; it does
not silently remove historical explanations. Existing synthetic fixtures need
one prospective shared reason before using this inverse.

The exact SDK-transformed schema preserves the singleton revision enum and the
flattened four-value coverage-decision enum. Singleton `const`, string patterns,
array maxima and custom validators are not dependable wire enforcement. Tests
therefore demonstrate both wire rejections and wire-valid/local-invalid controls.
After normalization, callers must use existing `validate_review` against sealed
claim/part bindings and `validate_locations` against the actual unscored prose.
The module rejects duplicate claims/parts/locations and inconsistent prose review
states locally, and guards both compact and normalized JSON at 8,000 UTF-8 bytes.

Provider completion is a separate mandatory caller gate: reject `max_tokens`
even if its JSON parses completely; never salvage truncated output. Preserve the
unaltered provider response and derive normalized output separately. Report
binding must independently repeat normalization from the current raw response,
then bind that raw response, normalization identity and normalized step. Old
`Checks` probes can retain their historical schema and caller completion checks.

The maximum-cardinality software fixtures use all six claim, eight part and ten
prose-finding slots, the longest categorical labels and maximum bounded reasons.
Sizes below are compact JSON with `ensure_ascii=False` and no extra whitespace.

| Reason fixture | Wire JSON bytes | Normalized JSON bytes | Wire bytes / 4 heuristic |
| --- | ---: | ---: | ---: |
| 96 ASCII characters | 5,980 | 7,228 | 1,495 |
| 60 two-byte Unicode characters | 6,556 | 7,948 | 1,639 |
| 30 four-byte Unicode characters | 6,556 | 7,948 | 1,639 |
| 96 ASCII characters including escaping | 6,556 | 7,948 | 1,639 |

The bytes/4 column is a rough heuristic, not measured provider tokens. It can
underestimate token use, particularly for Unicode. An 8,000-output-token caller
budget including thinking is a reasonable prospective evaluation candidate.
Reserve 2,500 tokens for thinking in planning, leaving 5,500 for visible output;
this allocation is an estimate and does not enforce an adaptive-thinking limit.
The module cannot prove actual token fit or provider completion. No provider or
count endpoint was contacted, and no checker semantic or human qualification is
claimed by these software fixtures.

The lock-exact interpreter imported `src` from this dedicated worktree. Offline
verification used `ANTHROPIC_API_KEY=local-preview-disabled`,
`WORKSPACE_D5_OFFLINE=1` and the existing jsonschema dependency overlay. New
contract tests: 102 passed. Combined contract/request-coverage/evidence-contract
suite: 168 passed, eight skipped under the existing fixture gates. Module strict
mypy and the focused ruff check passed. No live database was used.

Permanent private receipts are under
`~/Machine-Learning-Projects/arxiv-evidence/d5-provider-contract-repair-20261113/checker/`:
`REPORT.json`, `schemas.json`, maximum wire/normalized JSON fixtures, verification
logs and a SHA-256 manifest. They are local software evidence, not provider token
measurements, CI results or qualified checker verdicts. Root integration and its
broader adapter/report-binding gates remain separate work.

All rights reserved. No license or reuse permission is granted.

Independent location-selection check: the table above records selected maximum-cardinality examples, rather than universal JSON size maxima. Selecting all four scalar findings (`background`, `comparison`, `abstention`, `proposal`, each with null index), all three `assumptions` indices and all three `questions` indices yields **6,581 compact bytes and 7,973 normalized bytes** with 120-byte Unicode reasons. This is 25 bytes larger than the earlier selected examples. Both local 8,000-byte guards still apply; provider token fit remains unproven. The append-only additional location measurement and exact fixture files are preserved alongside the original receipts.
