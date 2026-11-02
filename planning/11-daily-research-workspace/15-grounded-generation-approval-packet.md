# Grounded summary and guided deep-dive qualification proposal

Prepared 2026-11-02. **Unapproved and unexecuted.** This file is a proposal,
never an approval record. Existing credentials, model availability and numeric
caps do not authorize a call. The application continues to return 403 before
constructing a provider. Q2/Q3 remain required later milestones.

## Model choices and price evidence

Official pricing checked on 2026-11-02, USD per million ordinary input/output
tokens: Haiku 4.5 **$1/$5**, Sonnet 4.6 **$3/$15**, Sonnet 5 **$2/$10**,
Sonnet 5.5 **$2/$10**, and Haiku 5.5 **$0.10/$0.50** for inputs at most 100k.
[Anthropic price table](https://platform.claude.com/docs/en/about-claude/pricing).

Proposed first instrument: `claude-sonnet-4-6` for both workflow and checking,
already explicitly represented by the repository's capability table.
Its published ID remains active/legacy; this avoids an unqualified model-route
change in the first measurement.
[Official model specification](https://platform.claude.com/docs/en/models/sonnet-4-6/overview).

Sonnet/Haiku 5.5 are current alternatives, requiring an explicit capability,
tokenizer, price and schema-path update before qualification. A family-prefix
guess is insufficient. The repository's historical Sonnet 5 price is stale;
it must not be used for admission. This proposal uses only the verified
Sonnet 4.6 row. No hosted subscription or API credit purchase is proposed.

## Exact proposed source and privacy scope

Use only selected public material already retained by the local workspace:

| Sample | Source/version | Expected evidence boundary |
|---|---|---|
| Agent memory | `arxiv:2610.41482:v1`, KEEPER | Retained abstract; explain only what it states; methods questions may abstain |
| Retrieval/claims | `arxiv:2610.41552:v1`, knowledge relation extraction | Retained abstract; distinguish reported results from unsupported extrapolation |
| Missing material | Google Research sleep-framework observed revision `42d6cea8785311a4` | Very short publisher feed excerpt; refuse invented mechanism/results |

Seal exact material IDs, hashes, parser, source versions and spans at approval;
changed bytes invalidate cached outputs. Exclude private notes, browser drafts,
unrelated files and conversation history. Include the organizing research
question only if the owner explicitly selects it as approved context. No new
URLs, tools, article-body fetches or arbitrary repository execution occur in
the model job. Public source text remains untrusted input, not instructions.

The tiny trial is **three summaries and one bounded abstract-scope guided
study**, with explicit abstentions. It is not full-text deep-dive acceptance.
A methods/equations deep dive needs a separately retained, permission-checked
scientific document and page/section/offset extraction review before its trial.

The companion `generation-trial.proposal.json` pins the currently retained
material IDs, version hashes and scopes; it is explicitly unapproved. Proposed
request settings: draft temperature 0.2, checking temperature 0.0, thinking off,
effort omitted, structured JSON output, SDK automatic retries off, concurrency
one, 30-second call timeout and at most nine calls across the qualification.
Count the complete request before each call; refuse inputs above the envelope
instead of silently truncating evidence. Only one study repair is allowed.

## Call/token envelope and estimates

The following are conservative design bounds, **not measured token counts**.
Use an exact local tokenizer or a separately authorized token-count endpoint
before requesting execution. Inputs include system instructions, schemas,
source text and prior draft where applicable. No cache/batch discounts assumed.

| Job | Normal path | Maximum input/output per call | Worst calls | Unbuffered estimate | Proposed job cap |
|---|---|---|---:|---:|---:|
| Summary | draft then independent support/schema check | draft 6,000/1,200; check 8,000/800 | 2 | $0.072 | $0.10 |
| Guided study | explain then check; one optional repair | draft 16,000/2,400; check 18,000/1,200; repair 18,000/2,400 | 3 | $0.246 | $0.32 |

At the proposed model price, a short summary using half those token bounds is
about $0.036; a typical three-quarter envelope is $0.054; the maximum is
$0.072. The guided-study design scenarios are about $0.078 (half-size, no
repair), $0.117 (three-quarter-size, no repair), and $0.246 (full envelope,
repair). These arithmetic scenarios are estimates; they do not assert model
quality or actual reasoning-token behavior. Any thinking tokens must fit the
same output ceiling and be recorded.

The 1.25x margin yields $0.090 per summary and $0.3075 per study; the proposed
rounded caps are above those values. Three maximum summary jobs plus one
study reserve **$0.62**. Propose **$0.75 total qualification**, **$0.75/day** and
**$0.75/month**, one job at a time, with **zero automatic scheduling**. These
ceilings are proposals; no policy row has been created. Provider billing can
overshoot an estimate, so record actual/unknown spend and stop further work
rather than treating a missing receipt as zero.

## Preconditions before asking for execution approval

Mechanical foundations implemented: immutable source material/spans; a
model-free claim validator that separates citation identity from support;
artifact-shape calibration repair; atomic owner/job/day/month reservations;
settings/source/version digest checks; nullable unscored denominators;
actual role/model routing and revision-aware median/worst-case cost estimates;
single-start and recovery fences; separate workflow/judge/unknown accounting;
and sentinel/default-mode tests that refuse before provider construction.

Still required: implement the actual summary/study executor and schema path;
bind the sealed settings to every actual gateway request; enforce call/token/
fan-out bounds and cooperative cancellation; refresh the exact allowed model
capability/price evidence; measure tokens; review a permitted full-text sample
for the later methods trial; connect representative expert packets/labels and
calibrate the actual checker. No historical evaluation claim is upgraded by a
fake checker agreeing with its own fixture.

The owner must then review the concrete scope/envelope, choose any private
context, approve the exact trial and ceilings, and provide a specific GO.
Approval is the final enabling step after those prerequisites are reviewable.

## Stop and acceptance rules

Stop before another call on: missing/revoked/expired approval, source/settings/
model/schema drift, unpriced route, admission refusal, reached call/token/
spend ceiling, unknown billing, malformed output, fabricated citation or number,
unsupported factual claim, or user cancellation. A refusal leaves source
reading and notes usable. An interrupted possibly billed request becomes
uncertain; recovery does not blindly resend it.

For every output retain input/material hashes, actual model/settings, request
identity, usage, separate costs, claim/check denominators and missing material.
Every asserted factual sentence needs exact source spans and an explicit
support check. Resolving an ID proves identity only. Abstract-only methods
must abstain. Inferences and experiment proposals stay labelled.

For the four-item qualification, owner review must find no invented citation,
number or unlabelled inference; inspect all proposed claim/span pairs and
scope refusals, plus one cancellation/cache/version-change case. Publish the
small denominators without a population-quality claim. Expansion toward Q2's
30 examples/100 claim pairs and Q3's representative deep dives requires a new
reviewed budget; this tiny trial cannot satisfy those launch gates by itself.
