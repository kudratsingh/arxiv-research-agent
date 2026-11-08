# D5 v8 procedural intents — prospective, offline only

v7r2 remains a stopped diagnostic: three of eight held-out workflows completed,
`learn-results` failed, and four Research workflows were unrun. Its packet,
original draft, Opus verdict, accounting, authorizations and blank human labels
are retained. No old result is reclassified or replayed by this repair.

## Captured failure and strict regression

The original `questions[0]` is:

> Which reported results are measured benchmark outcomes versus proposed applications such as use in autonomous discovery?

Opus supported six cited claims but flagged that question for presupposing an
application the abstract mentions only as background. The complete original
question/verdict and selected public material are in
`tests/fixtures/d5/stage-c-v7r2/`. A production-adapter MockTransport regression
reproduces the original rejection. Corrected outputs and subsequent synthetic
verdicts are software fixtures, never successful provider results or human gold.

## Bounded representation and local rendering

The opt-in schema revision is `workspace-assistance-neutral-intents-v6` for Learn
and Research. Existing purpose-specific schemas remain available for historical
diagnostics. New questions contain only an enum intent and emitted `claim_ids`.
`investigate_claim` requires at least one unique emitted claim ID; handles,
unknown IDs, duplicate IDs and free premise text are refused. Claim references
remain subject to exact provenance and whole-claim checking. Neutral questions
need no premise or scientific assertion. The locally rendered measurement intent
is:

> Which claims report measured results, and what applications, if any, does the excerpt propose?

Both modes now use bounded evidence-request codes for gaps, action codes for next
actions, and neutral abstention-reason codes. All displayed wording is local,
producer-bound and sent to the checker. An abstention cannot assert a new causal
or scientific explanation. No free text field is silently declared nonfactual.
The raw intent objects remain in immutable steps; Reader results use rendered
strings. List rendering preserves one-to-one field/index correspondence.

Exact transformed JSON Schema enforces enums, object shape, claim-ID vocabulary
and selected handle vocabulary. Local validators enforce uniqueness, references
to actually emitted claims, comparison source relationships, the six-claim and
three-procedure limits, and the existing 8000-byte cap. The SDK may move numeric
and length bounds into descriptions; local validation remains mandatory.

## One located repair, never relaxed final acceptance

The prospective request seals `located_prose_repair=first-check-only-v1`. The
historical request without that policy retains its original immediate stop.

A first-check `unscored_factual_content` verdict can consume the existing repair
only after its entire response, claim verdict batch, claim digests, exact
existing field/index, cancellation, authorization, source and usage checks pass.
The repair receives the exact prior finding and procedural fields plus the
existing claim-grounding report. It cannot expand evidence, change schemas or
use a second repair. Mandatory recheck reviews both claims and rendered prose.
Uncertain prose (`abstain`), malformed/missing locations, incomplete claim checks,
invalid provenance, and any residual prose finding on recheck stop the workflow.
Nothing becomes accepted merely because the checker supports the cited claims.

Legacy workflows and checker-only probes do not obtain the repair shortcut.
Old stopped scopes remain stopped. Provider errors, unknown completion and
admission refusals do not become content-repair opportunities.

## Independent evidence and unchanged quality policy

The offline suite covers exact original replay, one located repair, residual
rejection, neutral Learn, two-source Research, insufficient-evidence abstention,
wire/local rejection of free procedural assertions and invalid premise IDs.
Existing wrong-version/selected-span/quote/offset/Unicode tests remain required.
Mock count values are software fixtures, not token-fit evidence.

The successor freezes eight new question IDs and excludes every source version
selected anywhere in the preceding v7r2 packet from the held-out discovery pool.
Production ranking/edition/evidence selection is replayed over this declared
partition; no reference answer is substituted for retrieved context. The clock
and retained snapshot remain explicitly retrospective. New questions and selected
contexts are frozen before future paid outputs. The old eight cases, including
four unrun ones, stay in their original diagnostic cohort.

Completion8/8, 20 fully reviewed held-out facts, 20 decisive adversarial labels,
zero observed false passes and all other quality thresholds remain unchanged.
Development facts and machine support decisions cannot fill human minimums.
Every human label remains blank. Fewer eligible facts means HOLD; no added cases
or post-result threshold changes. See the separate v8 proposal for capacity and
approval prerequisites. No new provider contact or spend is authorized here.

The new repair policy additionally refuses missing, duplicate or mismatched
claim verdict IDs/digests before allowing any located-prose repair. A valid
field/index alone cannot rescue an invalid checker batch.

Candidate application `691398bf7ca157742b36350227941f87cc350c97`.
Frozen generation packet `1037d63e7c1a68a6f6a8c77d2c59d32ac8bb682cebf329485d1463551847ef2a`.
The separate smallest premise-calibration packet is
`ee48fbde1c7c747fa928b5ecf7abc70f4df54a44efbc62d782c16f6703f1a73b`.
Neither packet is approved; the old live scope and its3/8 score are unchanged.
