# Prospective consistency contract v18

This revision repairs response meaning and bookkeeping exposed by the complete
v17r2 responses. It does not rewrite an old job, adjudicate a source claim, resume
the stopped scope, or qualify a checker. Every converted example is synthetic.

## Three independent repairs

| Concern | Prospective representation | Enforcement and remaining semantics |
|---|---|---|
| Question topic vs premise | `context_claim_ids` and `premise_claim_ids` | Context links make no assertion; neutral intents may have them. Only `investigate_claim` has premises and requires at least one. The wire supplies explicit role descriptions and closed ID enums. Local validation rejects duplicates, overlap, missing/unknown references and neutral factual premises. Whole-claim and located-prose checking remain mandatory. |
| Partial request coverage | One required named object per sealed part; status `answered`, `partial`, `lacks_evidence`, or `omitted`; lossless `gap_reasons` | `answered` needs answer refs and exactly `none`; `partial` needs answer refs and genuine remaining gaps; evidence absence/omission forbid answers and use their own reasons. Flat records retain the compiled family rather than conditional unions. These reciprocal conditions remain explicit semantic checks. Context does not earn answer credit. |
| Coverage criticism vs factual prose | `coverage_checks.<part>.critiques`, exact-location `prose_findings`, exact-location `prose_uncertainties` | Every current claim, part and location is required. All independent findings remain lists. A missing list is not an empty judgment. The server derives the global prose state and machine aggregate; the model cannot contradict its findings with a global clear flag. A generic/missing-detail critique blocks coverage acceptance without becoming a factual-prose error. |

The normal body's one-value `answer` tag selects the claim-bearing structure; it
is not a claim that the request was fully answered. Request outcome is derived
from the sealed part records. Partial work never earns full-answer credit, even
if every cited claim is judged supported. Declared complete work remains
unreviewed until supplied current-response judgments are bound and checked.

A full abstention structurally contains no claims or claim references. Missing
application context still permits only that branch. Comparison-only source notes
remain independently cited and checked while the requested comparison stays
unanswered. Partial comparisons preserve both their useful answer and every
remaining gap.

## Invariants retained

- Claims are an array of emitted findings only; their IDs are server-derived by
  position. Coverage remains the sole request-to-claim mapping. No unused slots,
  duplicate reverse mapping, or fabricated missing judgments are introduced.
- Closed required part/checker keys preserve exactly-once identities. Unknown,
  missing and duplicate JSON identities are rejected. References to non-emitted
  positions, orphans, duplicate references and answer/context overlap fail.
- Learn retains eight claims maximum; Research twelve. Atomicity, study scope,
  comparator, metric definition and conditions remain reviewed. Comparisons need
  independent cited bases from at least two selected works.
- Selected handles resolve to immutable version/material/hash/parser/scope and
  Unicode offsets. Identity or a valid quotation alone establishes no support.
- Current checker context binds the complete response, including coverage,
  rendered questions and other prose. A repair needs its own completed check;
  an uncertain recheck cannot inherit earlier assessments.
- Existing payload protections, routes, accounting, concurrency, deadlines and
  bounded one-repair/mandatory-recheck workflow remain. Invalid first drafts
  remain terminal; the four-request diagnostic itself has no repairs.

## Complete-original regression lineage

The three files under `tests/fixtures/d5/consistency-v18` match the complete
archived generated text byte for byte. `LINEAGE.json` records SHA-256 values.
Original HTTP responses, private journals and accounting remain in permanent
`arxiv-evidence/provider-compat-live-v17r2-20261116T002251Z` storage.

1. Original Compact Learn fails its historical neutral-question rule. A synthetic
   role-only conversion exposes the next failure: all three parts were declared
   answered while carrying genuine missing methods/protocol/metric/data gaps.
   A separately synthetic partial conversion retains all five claim texts and
   every gap, then proceeds through provenance, rendering and checker context.
   No factual-support or provider-success credit is assigned.
2. Original small checker fails its historical global prose/located-findings
   consistency rule. A synthetic category conversion retains the entire missing
   detail criticism under p3 coverage. Remaining validation exposes the original
   bundled c1, uncertain comparator on c2, and p2/p3 coverage disagreements.
   Those negative machine judgments remain negative; they are not human gold.
   The critique placement under p3 is an explicitly synthetic development choice;
   the original finding supplied no part-specific critique identity. It is not
   a recovered historical part judgment or an independent label.
3. The completed accepted-schema control remains historical and unqualified; it
   is not repeated in the successor diagnostic.

## Aggregate policy

Explicit unsupported claims, lost qualifications, bundled findings, violated
priority, substantive factual-prose findings, coverage critiques, or decisive
coverage disagreement produce `FAIL`. In the absence of a decisive failure,
checker abstentions and uncertain support/quality/coverage/prose/priority produce
`HOLD`. Complete positive supplied judgments can produce a machine-contract
`PASS`; scientific quality and human qualification remain `UNMEASURED`.

Coverage is reported independently as full, partial, insufficient, omitted and
uncertain part counts. Checker counts reflect its supplied opinions; a disagreement
never rewrites the draft declaration or earns answer credit. Full-answer credit requires every part answered, no
coverage disagreement or critique, and a passing machine quality gate. No absent
judgment or empty evidence denominator becomes a positive label.

## Compatibility boundary

The successor retains emitted-claim arrays, required keyed part/checker objects,
shared finding/location definitions and a single abstention union. No conditional
branch is added per part or claim. Actual SDK-transformed draft, repair, checker,
recheck and maximum-cardinality shapes are checked locally. These observations
are neither remote compiler acceptance nor measured token fit. Only a separately
approved exact four-request diagnostic can measure those facts.
