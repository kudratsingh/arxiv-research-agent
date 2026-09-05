# P0-WO12 approval packet — DRAFT TEMPLATE

Status: **DRAFT — NOT AN APPROVAL REQUEST. NO SPEND AUTHORIZED.**

Date drafted: **2026-09-05**

Prepared by: P0-WO11, from
[`15-stage0-qualification-report.md`](15-stage0-qualification-report.md),
W07's matrix, W10's estimate template, and the price table in
`src/observability/costs.py`.

Blocking decision: **D9** — every live baseline, model judge, paid label
and funded experiment.

---

## 0. Read this first

**This document is not asking for anything.** It is the packet
[`12 §18`](12-p0-work-orders.md) requires, pre-filled so that an owner
who later chooses to consider W12 is reading a form with the arithmetic
already done rather than a blank one. Every monetary and time figure
below is marked `ESTIMATE / RE-PRICE BEFORE APPROVAL`. The go/no-go
question in §9 is **left unanswered on purpose**, and this draft does not
propose an answer to it.

**Three of the packet's own preconditions are not met today.** They are
listed in §8, and the largest is that the campaign execution loop does
not exist: `src/campaign/` plans, locks and seals episodes and has no
code that runs one. An approval granted today could not be spent.

**Every token count below is an unmeasured assumption.** They describe
prompts that exist and have never been run against this benchmark. They
are the first thing to re-derive — ideally from a single real episode
under a separately approved micro-cap — before this packet is presented.

---

## 1. What is being estimated

12 §18's initial scope recommendation, taken literally:

> Start with the current fixed policy only to estimate variance and cost.
> Add a paired existing-policy arm only if the approved cap covers the
> comparison and the analysis remains interpretable. Do not include
> unimplemented C or E.

So: **arm A only, the whole development suite, three repeats.**

| | |
|---|---|
| Suite | `research-policy-v1@1.0.0`, digest `sha256:b7536e62c8dc8f89…` |
| Cases | all 20, in the task set's own order |
| Arms | **A only** (`fixed`) |
| Repeats | 3 |
| Episodes | **60** |
| Corpus mode | `snapshot` |
| Interleaving | not applicable at one arm; the seed is still recorded |
| Campaign lock | `sha256:d45d39fd7df5d2ef…` (recompute at plan time; a moved digest is a different campaign) |
| Judge calls | 3 LLM rubrics per episode (`completeness`, `faithfulness`, `retrieval_recall`); `groundedness` is deterministic (ADR 0074) and free |

Arm C is implemented and could be run. It is deliberately excluded here
because 12 §18 says the first funded stage estimates variance rather than
compares policies, and because a two-arm campaign roughly doubles the
bill for a question a one-arm baseline has to answer first.

---

## 2. Provider and model ids — RE-PIN BEFORE APPROVAL

| Role | Setting | Value on `main` today | Required action |
|---|---|---|---|
| Workflow model | `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | **RE-PIN.** 07 §4 requires one exact then-current id, resolved immediately before the run. |
| Judge model | `EVAL_JUDGE_MODEL` | `claude-sonnet-4-6` | **RE-PIN.** A separate instrument (ADR 0070); changing it invalidates every prior baseline. |
| Per-agent overrides | `*_MODEL` | all empty | Keep empty, or record one explicit mapping used identically for the whole campaign. |
| Temperature | `src/llm._TEMPERATURE` | `0.3` | **STATE THE VALUE PRICED.** Recorded in the manifest, not enforced by the campaign. |
| Price table | `PRICES_LAST_VERIFIED` | **2026-08-20** | **RE-VERIFY** against the provider's published list. `price_staleness()` prints the warning once the table is over 30 days old. |

`claude-sonnet-4-6` is priced at **$3.00 / $15.00 per million tokens**
(input / output) in `src/observability/costs.py`. Every figure in §3 is
computed at that rate.

---

## 3. Cost — ESTIMATE / RE-PRICE BEFORE APPROVAL

Computed by `src/calibration/estimate.py`'s own `JudgeCallLine.cost_usd`
against the live price table, at 60 episodes. Call counts are derived
from the graph, not guessed; token counts are assumptions and are marked
as such.

### 3.1 One pass per episode (the expected case)

| Line | Calls | in / out per call | Cost |
|---|---:|---|---:|
| planner | 60 | 900 / 400 | $0.522000 |
| reader (one call per paper, `max_papers=10`) | 600 | 3,000 / 700 | $11.700000 |
| synthesizer | 60 | 6,000 / 2,000 | $2.880000 |
| critic | 60 | 3,500 / 600 | $1.170000 |
| **workflow subtotal** | 780 | | **$16.272000** |
| judge: completeness | 60 | 5,000 / 800 | $1.620000 |
| judge: faithfulness | 60 | 8,000 / 1,500 | $2.790000 |
| judge: retrieval_recall | 60 | 6,000 / 800 | $1.800000 |
| **judge subtotal** | 180 | | **$6.210000** |
| **campaign total** | **960** | | **$22.482000** |

Per episode: workflow **$0.271200**, judge **$0.103500**, total
**$0.374700**.

`ESTIMATE / RE-PRICE BEFORE APPROVAL` — every row.

### 3.2 The worst case the TaskSpec permits

`research_binding._execution_limits` computes arm A's model-call ceiling
as `(1 + max_papers + 2) * max_iterations + 4 = 43`, against 13 at one
pass. If every episode revised twice and read ten papers each time:

| | ESTIMATE |
|---|---:|
| workflow at 3.31× | **$53.82** |
| campaign total | **$60.03** |

**The cap must be set against this number, not against §3.1.** A cap sized
to the expected case is a cap that stops a campaign whose only fault was
that the critic asked for revisions.

### 3.3 Proposed caps — REQUIRES OWNER DECISION

| Cap | Proposed | Basis |
|---|---:|---|
| Per-episode total | **$1.500000** | 1.5× the §3.2 per-episode worst case ($1.00), rounded up; below the shipped `max_cost_usd` default of $2.00 |
| Per-episode workflow | **$1.200000** | |
| Per-episode judge | **$0.300000** | |
| Campaign total | **$75.000000** | 1.25× the §3.2 worst case, so a campaign that hits the cap has genuinely gone wrong rather than merely been under-estimated |

`ESTIMATE / RE-PRICE BEFORE APPROVAL`. Note the structural constraint the
contract already enforces: a positive campaign cap without an approval id
is not expressible, and an approval id with a zero cap is not either.

### 3.4 In-flight overshoot

12 §18 asks for this by name, because a ceiling with no in-flight rule is
a ceiling crossed once per concurrency unit.

`CampaignBudget.enforcement` is
`"between-episodes-with-in-flight-overshoot-risk"`, and the name is
honest: the check happens *between* episodes. At concurrency 1 the
maximum overshoot is one episode's per-episode cap ($1.50). At
concurrency N it is N × that.

**Recommendation: run the baseline at concurrency 1.** Sixty episodes at
an expected ~2 minutes each is about two hours of wall clock, which is
not worth an N-fold overshoot exposure on the first funded run. If
concurrency is wanted later, the overshoot bound must be restated at
that N.

*(The enforcement predicate `budget_stop_reached` exists and has no
production caller today — see §8.)*

---

## 4. Expert and owner time — ESTIMATE

| Line | Items | Minutes each | People | Hours |
|---|---:|---:|---:|---:|
| Read the scorecard and error analysis | 1 | 120 | 1 | 2.0 |
| Assign difficulty-slice membership from the frozen baseline | 20 | 3 | 1 | 1.0 |
| **total** | | | | **3.0 h** |

`ESTIMATE`. This is the *baseline's* own time cost and is small. It is
not the calibration campaign's.

**The number an owner should weigh beside it**: W10's judge-calibration
protocol estimates **48.7 h** of expert time across two annotators plus
adjudication for its recommended 141-item set, against **$3.81** of model
spend — a working week of human time for the price of a coffee. That
campaign is separately blocked (D8.10 plus 13 §5's human-label retention
decision) and is **not** part of W12. It is named here because the W12
baseline is a prerequisite for one of its steps: slice membership must be
assigned from a frozen baseline arm, and no such baseline exists.

---

## 5. Stop rules

Adapted from 07 §9 to a single-arm baseline. Stopping is an outcome:
completed episodes are preserved and the reason is published.

| Condition | Trigger | Action |
|---|---|---|
| `campaign-cap-reached` | Cumulative workflow + judge spend reaches the campaign cap | Stop between episodes, finish in-flight work, publish the partial report with its denominators. Do not raise the cap and continue — that is a new campaign with lineage. |
| `episode-cap-reached` | One episode crosses its per-episode cap | Terminate it `budget_stopped`, **keep it in the denominator**, continue. |
| `manifest-mismatch` | A sealed episode manifest does not match the declared arm | Stop. A run that cannot prove what it ran is not data. |
| `provider-drift` | Model id, API version or price table changes mid-campaign | Stop. Episodes before and after measure two instruments; resume as a new campaign against a new lock. |
| `judge-failure-rate` | More than 10% of episodes lose a primary score to judge failure | Stop and report the null-score denominator. A campaign whose scores are mostly absent is not a variance estimate. |
| `source-drift` | The resolved corpus mode is not `snapshot`, or the source snapshot digest moves | Stop. Refused at seal time already; a stop rule for the case where it changes between episodes. |
| `label-or-grader-edit` | Anyone proposes changing a label, rubric or grader after seeing results | **Refuse.** Supersede with a new revision and its own rationale. |
| `safety-or-privacy-event` | Any hard violation class from ADR 0072, or any leakage of hidden evaluation material | Stop immediately. Gated at absolute zero. |

---

## 6. Interleaving, resume, rerun and artifact retention

- **Interleaving** — not applicable at one arm. The seed is still
  recorded, and the matrix compiler still derives block order from it, so
  adding a second arm later produces an interleaved design without a
  code change.
- **Resume** — reuses the same lock and cap. A raised cap, a changed arm
  set, a changed case selection, a changed repeat count or a new seed all
  move the campaign id and are refused with lineage named as the remedy.
  Pending = runnable and no terminal `completion.json`.
- **Rerun** — a new run id and a `__rerun-N` directory with `RunLineage`
  naming its parent. A completed episode is never overwritten (three
  independent layers; report §5.2).
- **Retention** — episode artifacts land under
  `outputs/campaign/research-policy-v1/<campaign-id>/` per 07 §10. Every
  event is `training_eligible: false`; consent for this lane is
  `evaluation_only` over a public benchmark, so no D8 decision on
  retained user or learner content is engaged. **A retention *period* has
  not been decided and is an owner call.**

---

## 7. The no-cost W10/W11 evidence

| Requirement | Where |
|---|---|
| W11 Stage-0 qualification | [`15-stage0-qualification-report.md`](15-stage0-qualification-report.md), and `tests/test_stage0_qualification.py` |
| Dry-run lock, 300/240/60, zero provider init | report §2 |
| A/B/C/D sealed against real compiled graphs; E non-runnable | report §3 |
| Four synthetic episodes, verified chains, zero parity mismatches | report §4 |
| Denominator and identity integrity | report §5 |
| Privacy, leakage, adversarial, ASR gate | report §6 |
| W10 calibration protocol and fixtures | [`14-judge-calibration-protocol.md`](14-judge-calibration-protocol.md), `src/calibration/`, `eval_registry_calibration/` |
| Governance and threat review | [`13-governance-threat-review.md`](13-governance-threat-review.md) |
| Zero-external-call attestation | report §8 |

---

## 8. Preconditions not met today

An approval granted now could not be executed. Listing this in the packet
rather than discovering it after an approval is the point of the packet.

1. **The campaign execution loop does not exist.** `src/campaign/` plans,
   locks, declares arms, compiles the matrix, opens the ledger, seals a
   campaign manifest and seals one episode's `RunManifest` — and never
   runs an episode. Nothing writes `completion.json`, so the ledger's
   reconciliation path has only ever seen receipts a test wrote, and
   `budget_stop_reached` (`src/campaign/planner.py:645`) — the
   between-episodes enforcement §3.4 relies on — has no production
   caller. It belongs at `planner.py:575` with a `run` verb at
   `cli.py:72`. **This is the one remaining code item.**
2. **The approval backend is a shape, not an authority.**
   `LocalApprovalRecordBackend` reads a JSON file of records and
   delegates verification to W03's `FakeLocalApprovalBackend`. It fails
   closed correctly and it is not a record an owner created.
3. **Prices and model ids are not re-verified.** §2.
4. **Token counts are unmeasured.** §3's basis. A single episode under a
   separately approved micro-cap would replace every assumption in that
   table with a measurement, and is the cheapest way to make this packet
   real.

---

## 9. The decision

> **Do you approve a funded arm-A baseline of 60 episodes over
> `research-policy-v1`, at a per-episode cap of $______ and a campaign
> cap of $______, on model id `____________________` at prices verified
> on ____-__-__, under the stop rules in §5?**

**This question is unanswered and this document does not propose an
answer to it.** Nothing in this repository may be read as an approval:
`requires_repricing` is fixed `True` on every estimate object,
`campaign_started` is fixed `False`, no `approved` field exists anywhere
in `src/calibration/estimate.py`, and possessing an API key or declaring
a positive ceiling never authorizes chargeable work (12 §3.10).

**NOTHING IN THIS PACKET HAS BEEN RUN.** No provider call, no judge call,
no paid label, and no dollar has been spent by any work order that
produced it.
