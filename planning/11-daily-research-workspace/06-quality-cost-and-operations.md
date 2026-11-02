# Quality cost and operations

Date: 2026-11-02. Status: proposed acceptance and operating contract. Targets
below are initial product requirements to ratify with the owner; they are not
measured results. Use the work orders in document 05 to turn each gate into a
bounded change and evidence package. The owner selected daily briefing plus
guided deep dives and local-first operation with paid services approved
separately. A no-LLM metadata briefing, reading and notes are the first usable
slice; automatic paid generation and external delivery start disabled.

The daily workspace succeeds when the owner regularly finds useful new work,
understands why it matters, can inspect its evidence and carries an idea into
a concrete next step. More unread items, longer summaries and more agent calls
are not success measures.

## Capability release gates

| Gate | Required before release | What may proceed independently |
|---|---|---|
| Q0 metadata workspace | Source/identity/date correctness, coverage receipts, read/save state, secret-free fixtures, responsive accessibility and dependency baseline | Interests, topic navigation, the inbox and link-out reading can ship before model summaries |
| Q1 live intake | Adapter contracts/rate rules, restart/cursor tests, duplicate/version handling, safe fetching and honest partial coverage | A user can receive real metadata without a factual summary being generated |
| Q2 generated briefings | Versioned source material, claim-to-span traceability, summary scope labels, deterministic validation, reviewed representative output and approved spend | Deep-dive policies remain gated separately |
| Q3 guided deep dives and idea work | Material retrieval/retention, calibrated checks for the used policy, cancel/recovery, citation/limitation review, speculative labels and project artifacts | Ideas can be private proposals; no execution authority follows |
| Q4 unattended delivery | Durable occurrences/outbox, DST/catch-up/duplicate tests, destination verification, quiet hours, global budget admission and operational recovery | In-app alerts can precede external email/push |
| Q5 daily-use pilot | Owner walkthrough plus at least 14 days of operational/usefulness evidence; review misses, noise, costs and stale-source incidents | Broader source/topic availability can expand behind the same controls |

The historical five-arm evaluation campaign is not a blanket prerequisite for
a metadata inbox. Its unresolved measurement defects do matter before using
its metric to certify generated claim support or compare research policies.

## Required corrections from the prior review

The [2026-11-02 review](../10-current-state-review-2026-11-02.md) is the evidence
baseline. Carry the relevant work into this transformation:

- **Claim support:** citation-ID resolution cannot be labelled factual support.
  Keep identity/quote checks as deterministic diagnostics. Define a checked
  factual claim and measure actual support from the supplied source material.
- **Source scope:** retain ranked source material independently of an arm's
  evidence-store flag. Check that comparisons use compatible scopes. Metadata,
  abstract and full-text summaries must be visibly different product states.
- **Settings:** reject or explicitly restore runtime settings that disagree
  with the sealed instrument/task policy; record the actual request, not only
  an intended temperature/schema setting.
- **Artifact integration:** repair the calibration reader's actual campaign
  filenames/nesting/chunk format and exercise it against emitted artifacts.
- **Costing:** fix measured role-call/revision counts and use actual model
  routes and price revisions. Do not inherit old $22/$75 estimates.
- **Judging:** enable/record the intended schema path, preserve empty/null
  denominators, and add immutable repeat judging when estimating judge noise.

Use a narrow summary/deep-dive benchmark that reflects this product's actual
inputs. It should include papers, lab posts, news about papers, repositories,
revised work and missing full text. The old 20-query corpus alone does not
cover a daily multi-source feed.

## Proposed measurable acceptance

| Area | Initial acceptance evidence |
|---|---|
| Identity and dates | A hand-reviewed fixture set of at least 60 mixed records covering DOI/arXiv/version/URL aliases, syndicated stories, date precision, late indexing and ambiguous titles; zero known false hard merges |
| Intake recovery | Fault injection at every cursor/page commit boundary; restart produces the same logical items without losing a tested late-indexed item; duplicate task attempts publish one occurrence |
| Coverage | Every live digest carries source set, requested interval, successful interval, last success and failures; a deliberately failed adapter produces a visible partial result |
| Relevance | Owner labels at least 50 mixed candidates before tuning; record precision among the top 10, missed-useful items and exclusion violations. Proposed pilot target: at least 7 of the top 10 useful, with no exclusion violation; adjust only with a documented new evaluation revision |
| Diversity | Report field, source-type and publisher concentration, duplicates and exploration share; no fixed “fairness” number invented across unrelated scientific disciplines |
| Factual summaries | At least 30 source-backed examples and 100 checked claim/span pairs, including adversarial/abstract-only/missing-content cases; no fabricated citation, unsupported numerical result or unlabelled inference in the reviewed launch set |
| Completeness and caveats | User-visible summaries preserve the tested material's decisive assumptions, scope, limitations and reported status; an unavailable section produces a stated gap |
| Idea quality | Ten reviewed idea/experiment artifacts identify evidence, assumptions, nearest related work, a falsifier and a feasible first test. No automatic claim of novelty or “validated idea” |
| Schedule and delivery | Test timezone changes, both DST transitions, a 72-hour outage, two workers racing, crashes before/after provider acceptance, pause and resend; no duplicate in-app occurrence in the test set |
| UX | Keyboard completion of interests → briefing → source → deep dive → saved note; screen-reader review of core paths; responsive at 390 px; no new critical/serious axe findings |
| Performance | On a declared seeded corpus/hardware, proposed p95 Today/filter API below 1 s and saved-source detail below 2 s. Display long job progress immediately; do not make the first page wait for an LLM |
| Costs | Every model attempt has a real usage/cost or explicit unknown estimate; concurrent admission cannot exceed the approved reservation policy; a deliberately reached cap still permits metadata viewing |

These samples are launch checks, not strong population-level quality claims.
Publish denominators, unresolved labels and intervals where appropriate. One
owner's usefulness labels support a personal ranking decision, not a claim
that the product is optimal for every researcher.

## Ranking and feedback evaluation

Keep ingestion fixtures and ranking labels separate from holdout evaluation.
Preserve date cutoffs so a retrospective trial does not use later citation
counts or future revisions. Compare the proposed ranker to chronological and
keyword/watch baselines on the same candidate set and item cutoff.

Report primary usefulness at a fixed reading budget, distinct-source coverage,
duplicate rate, explicit exclusions, missed-useful items and unexpected but
useful discoveries. Track return-to-read and project follow-through as optional
behavioral signals. Do not equate scrolling, dwell time or opening a paper
with learning, satisfaction or consent to train.

User feedback should distinguish “already knew this”, “wrong field”, “too
introductory”, “too advanced”, “low evidence”, “duplicate” and “useful for this
project”. An undoable event changes future rankings under a recorded policy;
it never silently deletes the source or changes a user-declared interest.

## Source and summary evidence

Each summary shows its material scope, observed date/version, authors'
reported result, relevant baseline, limitations and the next source action.
If only an abstract was available, do not imply the methods, appendix,
experiments or code were read. “Official announcement” describes origin,
not independent verification of a performance claim.

Treat citation edges, replicated results, reported contradictions and model
inferences as different relation types. A generated relationship must name
the common mechanism/benchmark/assumption and the exact evidence supporting
it. Missing proof remains a suggested connection to investigate.

Keep a small audit for claims the summarizer/judge failed to extract. Judging
only extracted claims can miss an unsupported sentence entirely. Preserve
the original output and corrected revision rather than overwriting history.

## Global cost admission

Scheduled work needs an unattended spend policy. Existing per-job cost checks
and planner HITL are insufficient when many scheduled jobs can overlap.

Use an atomic Postgres admission transaction to reserve a conservative amount
against the owner's approved day/month ceiling before the first paid call.
Each task receives a bounded allocation, model/tool allowlist, token/output
limits, maximum attempts and deadline. Workers recheck the reservation before
each fan-out. Keep actual spend, remaining reservations and uncertain provider
attempts in the same account view; do not count an unknown call as zero.

On completion, reconcile billed usage, release unused reservation and retain
overshoot/unknowns. An interrupted call can be billable even if no answer was
saved. The policy must bound fan-out and retries, and state that the provider's
own billing limit is an additional backstop rather than a perfect reservation
system. Revoked approval stops future admissions and queued paid work.

Proposed defaults before owner approval: metadata intake and cached reading
work; zero automatic model generation and no external delivery. Once approved,
the owner chooses the actual day/month and per-deep-dive caps. Warn before
depletion, preserve a remaining-budget explanation and degrade to metadata
instead of repeatedly failing the whole briefing.

For a monthly estimate, compute:

```text
LLM spend = sum over roles and actual attempts of
  (uncached input tokens * input price
   + cached read/write tokens * their applicable prices
   + output tokens * output price) / 1,000,000

total operating spend = LLM spend + selected APIs + hosting/storage/backups
                     + approved notification service
```

The planning worksheet should vary candidate count, shortlist size, digest
frequency, average source length, deep dives per week, verification passes,
cache reuse, revision/retry rate and retention. Compare low/typical/high
scenarios using then-current provider prices. A broad topic catalogue does
not mean fetching or summarizing every topic every day.

## Operational behavior

| Incident | Required product/worker behavior |
|---|---|
| Source fails or quota returns 429 | Respect Retry-After, retain cursor/checkpoint, reduce retry pressure, show last success and missing interval |
| No new matched work | Show a successful empty check with scope/date; do not invent a summary or force discovery filler |
| Model unavailable or cap reached | Show metadata and cached summaries; preserve the blocked deep-dive request and clear retry/approval action |
| PDF extraction fails | Keep link and metadata; offer available abstract with its label; record parser reason |
| Worker dies | Lease expires; replay only safe uncommitted stages; preserve completed artifacts and uncertain billable attempts |
| DB unavailable | Refuse paid work and durable mutations; show a clear unavailable state; do not fall back to an untracked scheduled mode |
| Notification provider acceptance unknown | Mark uncertain, avoid blind resend, provide owner reconciliation/resend action |
| Laptop slept | One bounded catch-up digest after restart; disclose missing window; no flood of old immediate alerts |
| Correction/retraction appears | Link the changed status to affected saved/generated artifacts and surface a meaningful update; retain version history |
| Bad source or malicious content | Quarantine the source/material and identify affected artifacts; do not execute embedded instructions |

Owner operations view: next scheduled check, last successful run by connector,
coverage window, queue age, attempt/dead-letter counts, digest readiness,
delivery acceptance, source-material failures, cache reuse and approved versus
reserved/spent/unknown cost. Notifications about failures are themselves
deduplicated and respect quiet hours except for owner-selected critical cases.

Record correlation IDs and hashes, not full article text, private research
notes or credentials in routine logs. Keep private exports and backups scoped
and verify one restore before relying on a hosted workspace. Define metadata,
full-text cache, notes, usage and delivery-log retention separately with a
clear export/delete path.

## Testing and release sequence

1. Contract and migration checks use recorded public metadata and synthetic
   private notes; network remains disabled in ordinary tests.
2. Deterministic ranking and intake fixtures cover conflicting identifiers,
   duplicates, revisions, stale dates, empty updates and source outages.
3. A complete frontend path runs against fixtures before live integrations.
   “Last checked” and “read” indicators come from real state, not mock animation.
4. Live API probes are read-only and bounded by approved adapter terms/keys.
   Persist source receipts without triggering model generation.
5. A separately approved model smoke measures actual usage/schema behavior
   and then samples short summaries and a deep dive under explicit caps.
6. A scheduled shadow run creates private in-app digests; review quality,
   duplicates and dates before enabling an external destination.
7. Complete the 14-day personal pilot. Keep a short issue log of useful items,
   misses, noise, source gaps, idea follow-through, spend and operator work.
   Select the next expansion from these observations.

The reviewed main branch's dependency audit and cancelled Python CI job need
fresh disposition before deployment. Do not disable the gate or broaden
exceptions to claim readiness. Local test success is separate evidence from
current production dependency findings and a real personal-use pilot.

No launch gate requires a learned ranker, arbitrary code runner, public signup,
autonomous experiment execution or model training. Those need independent
task/evaluation/permission designs after the daily workspace proves useful.
