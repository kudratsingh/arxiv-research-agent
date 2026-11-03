# Grounded summary and guided deep-dive qualification proposal

Refreshed 2026-11-03 after the fake executor and exact request previews became
reviewable. **Unapproved and unexecuted.** This document and its JSON companion
are proposals, never approval records. Paid `/workspace/generate` remains 403;
no credential, numeric cap or fixture completion can enable a provider client.

## What can be reviewed now

Reader → Understand → synthetic workbench runs a real local pipeline over
retained evidence: select material/passages → inspect the exact sealed request
→ draft → evidence checks → optional repair and mandatory recheck → persist
→ inspect the result and return to its original source passage. It uses only
`fixture-workspace-v1`, not an SDK or a remotely selectable provider.

Four actual retained-source fake jobs reached `ready` in the isolated
`workspace-verification` database. Exact inputs, stage requests, results and
split counters are under `outputs/workspace-next/`; see
`fake-execution-receipt.json`, `summary-{1,2,3}-sealed-preview.json` and
`study-sealed-preview.json`. The latter selects original ReAct PDF page 3.
Local counters are explicitly simulated UTF-8 byte units, **not measured model
tokens**. Every actual USD field is zero. Synthetic quotation checks do not
qualify factual reasoning or establish a paper's scientific truth.

The job ledger now exercises atomic fake reservations, cache/source/settings
binding, bounded calls, owner isolation, cancellation, interrupted leases,
restart recovery and repair/recheck. A lost in-flight step is uncertain and is
not automatically replayed. Fake reservations are separate from paid approval
and spend tables. No paid approval writer is exposed.

## Model choices and price evidence

Official ordinary USD prices per million input/output tokens were rechecked
2026-11-03: Sonnet 4.6 **$3/$15**, Haiku 4.5 **$1/$5**, Sonnet 5.5 **$2/$10**,
and Haiku 5.5 **$0.10/$0.50** for prompts at most 100k tokens. These are public
price observations, not measured trial costs; no discounts are assumed.
[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing).

Propose `claude-sonnet-4-6` for both workflow and checking for the first bounded
measurement. It has an explicit repository capability row; the official page
lists it active/legacy with the same ID and $3/$15 price. Model availability is
not execution approval. Newer Sonnet/Haiku routes require deliberate capability,
tokenizer and schema qualification first. Historical repository price rows
must not override the refreshed proposal.
[Official Sonnet 4.6 specification](https://platform.claude.com/docs/en/models/sonnet-4-6/overview).

## Exact proposed source and privacy scope

The machine-readable companion pins material/version/source/content hashes,
parser revisions, scopes and selected study span IDs. The local exact request
artifacts show every source character the fake pipeline actually submitted.
They do not pretend a future paid request already has its final digest.

| Sample | Retained source | Allowed scope |
|---|---|---|
| Summary 1 | KEEPER, `arxiv:2610.41482`, metadata revision `e5c832a06d88973f` | Abstract only; methods/results not stated there must abstain |
| Summary 2 | Knowledge-relation extraction, `arxiv:2610.41552`, metadata revision `1c364e8ae805a931` | Abstract only; distinguish reported statements from extrapolation |
| Summary 3 | Google Research sleep-framework revision `42d6cea8785311a4` | Short feed excerpt; refuse invented mechanisms or results |
| Guided study | ReAct `2210.03629v3`, material `mat-2b7a38f3cfa1449f7728f044688ca2c2` | Three retained passages on original PDF page 3; excerpt scope, not a whole-paper reading |

Exclude private notes, browser drafts, preferences, reading history, unrelated
files and implicit organizing questions. An optional question starts blank and
is included only through an explicit context choice. Public source text is
untrusted evidence, never executable instructions. No tools, new URL fetches,
article-body fetches or repository code execution occur inside a job.

ReAct and Self-RAG selected-page text is available for manual reading, with
stable original-page/Unicode-offset anchors and retained extraction warnings.
Equations, figure glyphs and table structure are not qualified for generated
interpretation. See [the extraction inspection](18-fulltext-qualification.md).
An abstract-scoped study remains labelled abstract-scoped; an excerpt study
cannot imply appendix, equation or full-paper coverage.

## Proposed request envelope and cost

This tiny trial is **three summaries and one excerpt-scoped guided study**.
Proposed paid settings: draft temperature 0.2, checker temperature 0.0, thinking
disabled, effort omitted, structured JSON, SDK retries zero, concurrency one,
30-second call timeout. These differ from the fake instrument's sealed
settings (temperature 0, structured JSON, one repair); actual paid gateway
binding and token enforcement remain preconditions, not established facts.

One repair is permitted for either job kind and **every repair is rechecked**.
A four-call maximum replaces the old packet's three-call study bound, which
omitted rechecking. Total worst-case trial calls are sixteen. Stop rather than
silently truncating source material or expanding a call envelope.

All token counts below are conservative design ceilings, **not measurements**.
Complete input includes instructions, schemas, evidence and prior draft/check
state. Before execution, measure the final bound request with an appropriate
local tokenizer or separately authorized count endpoint. No endpoint was used.

| Job/stage | Maximum input/output tokens |
|---|---:|
| Summary draft | 6,000 / 1,200 |
| Summary check | 8,000 / 800 |
| Summary repair | 8,000 / 1,200 |
| Summary recheck | 8,000 / 800 |
| Study draft | 16,000 / 2,400 |
| Study check | 18,000 / 1,200 |
| Study repair | 18,000 / 2,400 |
| Study recheck | 18,000 / 1,200 |

| Envelope | Workflow | Checker | Raw maximum estimate | With 1.25× margin | Proposed job cap |
|---|---:|---:|---:|---:|---:|
| One summary, including repair | $0.078 | $0.072 | $0.150 | $0.1875 | $0.20 |
| One study, including repair | $0.174 | $0.144 | $0.318 | $0.3975 | $0.40 |

The two-call no-repair paths estimate $0.072 per summary and $0.156 per study.
These arithmetic scenarios do not predict quality, actual tokenization or
billing. Four worst-case jobs total **$0.768** before margin; the rounded job
reservations total **$1.00**. Proposed trial/day/month ceilings are each
**$1.25**, one job at a time, recurrence off. No policy/approval row was created.
Unknown usage/billing remains a separate liability; it cannot be treated as
zero or used to admit more work.

## Remaining conditions before execution approval

Implemented and testable now: source/version/span retention; explicit evidence
selection and context preview; exact fake request/stage binding; persisted
workflow/checker/unknown accounting; atomic fake reservation; bounded repair
and recheck; cancellation, stale-cache refusal and restart fences; result
presentation with findings, inference and proposed actions distinguished.

Still required for paid execution:

- A reviewed paid adapter that binds actual model/settings/schema/source scope
  and enforces measured input/output/call limits on every gateway request.
- Exact token measurements and a refreshed paid request digest tied to the
  proposed public context, model capability and current price evidence.
- Representative human claim/span review and actual checker qualification.
  Fixture agreement supplies no measured false-pass rate or scientific-quality
  evidence; the tiny trial itself cannot certify a checker.
- The owner's specific GO naming model, context, one-off scope and ceilings.
  There is no code-generated approval and no broad credential-based consent.

Until these are met, manual source reading, notes and fake protocol review
remain usable. The paid path stays inaccessible. The owner can review this
concrete proposal now without approving execution.

## Stop rules and small-sample acceptance

Stop before another call on revoked/missing approval, changed source/settings/
model/schema, unpriced route, exceeded call/token/spend envelope, unknown
billing, malformed output, fabricated source/number, unsupported factual claim
or cancellation. A possibly billed interrupted call remains uncertain and is
never blindly resent. Retain every input/stage digest, actual model/settings,
usage split, source scope and claim/check denominator.

For the eventual four-item trial inspect every asserted claim/span pair and
scope refusal. Findings must link to retained evidence; assumptions and
limitations remain explicit; connections/inferences and proposed experiments
are visibly separate. No invented citation/number or unlabelled inference is
acceptable. Include cancellation, cache and source-version-change cases.
Report small denominators without population claims. Q2's 30 examples/100
claim pairs and Q3's representative guided dives remain later launch gates
with separately reviewed budgets and human/model evidence.
