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

**Three of the packet's own preconditions are not met today**, and they
are listed in §8. The one that used to lead that list — that the campaign
execution loop did not exist — was closed by P0-WO07b
([ADR 0088](../decisions/0088-campaign-execution-loop.md)):
`src/campaign/` now runs the episodes it plans, and the full mock matrix
executes end to end at `$0.000000`. What remains is an owner's: an
approval record someone actually created, model ids and prices verified
at run time, and token counts that have never been measured. An approval
granted today would be spendable and would still be spending against
unmeasured numbers.

**And a fourth thing, which nobody had noticed until a rehearsal looked
for it.** P0-WO20 added `python -m src.campaign rehearse`, which walks
the funded path under the zero-spend sentinel and stops at the
credential. It reports that §1's `corpus_mode: snapshot` resolves to the
*mock* corpus, under which every agent is model-free — so the scope this
packet prices could not spend a dollar if it were approved. §8.3 has the
measurements and what they leave for the owner to decide. The scope in
§1 and the figures in §3 are left exactly as they were: correcting them
would be answering §9.

**Every token count below is an unmeasured assumption.** They describe
prompts that exist and have never been run against this benchmark. They
are the first thing to re-derive — ideally from a single real episode
under a separately approved micro-cap — before this packet is presented.

---

## 1. What is being estimated

12 §18's initial scope recommendation, taken literally:

> Start with the current fixed policy only to estimate variance and cost.
> Add a paired existing-policy arm only if the approved cap covers the
> comparison and the analysis remains interpretable. C and E are no longer
> unimplemented, but the recommendation stands: a first funded run sizes
> the variance, and adding the two newest arms to it buys a wider matrix
> rather than a better estimate.

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

### 1.1 Arm E reachability on `research-policy-v1`

Arm E is now implemented too (ADR 0091), and it is **not** in this scope
either. This note exists so that a later request to add it is priced
against what it would actually exercise rather than against its name.

Arm E's identity is a router: a deterministic controller allocating each
query to T0 (the fixed pipeline), T1 (verify-and-repair) or T2 (the
orchestrator-workers branch graph, with listwise selection and a marginal
stop). What it exercises therefore depends entirely on how the twenty
queries route, and that number has moved once already:

| | T0 | T1 | T2 | What a 60-episode arm-E run would exercise |
|---|---:|---:|---:|---|
| Before ADR 0087 (as shipped by CAP-09) | 12 | 8 | 0 | branching, selection and the marginal stop: **never** |
| After ADR 0087 (`main` today) | 10 | 2 | 8 | 30 episodes T0, 6 episodes T1, **24 episodes on the branch graph** |

The eight branched cases are `hallucination-mitigation`,
`alignment-beyond-rlhf`, `lora-vs-full-finetune`,
`long-context-efficiency`, `moe-vs-dense`, `jailbreak-robustness`,
`interpretability-methods` and `agentic-memory-architectures`: two
two-system comparisons and six open enumerations over a class of
approaches. Each carries the rule that branched it in its
`compute.tier_selected` record, and the per-query table with its reasons
is pinned in `tests/test_listwise_selection.py`.

**Two consequences for pricing, both against arm E and neither hidden.**
A T2 episode is not one workflow pass: it is up to
`ORCHESTRATION_MAX_BRANCHES` branches, each with its own search and its
own reader calls, bounded by `ORCHESTRATION_MAX_PAPERS_PER_BRANCH` and by
a per-branch share of the episode cap. The 24 branched episodes are
therefore the expensive fifth of the arm, and §3's per-episode figure —
computed for arm A's single pass — does not describe them. And arm E's
own T0-versus-T1 contrast would rest on 30 and 6 episodes respectively,
which is thin; arms A and C answer that question with 60 each.

The pre-ADR-0087 row is kept deliberately. The honest reading of a funded
arm-E run approved before 2026-09-06 is that it would have measured
adaptive compute and never once reached the adaptive part.

---

## 2. Provider and model ids — RE-PIN BEFORE APPROVAL

**Ids verified on `main` 334280d on 2026-09-17.** The tables below are
read off `src/llm_models.py` and `src/config.py` rather than
transcribed, and `python -m src.campaign rehearse` re-reads them on
every run (§8). What is re-pinned here is the **ids**: every price cell
below and in §3 is untouched and still carries
`ESTIMATE / RE-PRICE BEFORE APPROVAL`, because a price is a provider
fact this repository has no way to check.

### 2.1 What this campaign would route to

| Role | Setting | Value on `main` today | Required action |
|---|---|---|---|
| Workflow model | `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | **RE-PIN.** 07 §4 requires one exact then-current id, resolved immediately before the run. |
| Judge model | `EVAL_JUDGE_MODEL` | `claude-sonnet-4-6` | **RE-PIN.** A separate instrument (ADR 0070); changing it invalidates every prior baseline. |
| Per-agent overrides | `*_MODEL` | all empty | Keep empty, or record one explicit mapping used identically for the whole campaign. |
| Temperature | `LLM_TEMPERATURE` (`settings.llm_temperature`) | `0.3` | **STATE THE VALUE PRICED.** Recorded in the manifest, not enforced by the campaign. Sent only to a model whose row below says `sampling ✓`; ADR 0077 drops it for the rest rather than taking a 400. |
| Price table | `PRICES_LAST_VERIFIED` | **2026-08-20** | **RE-VERIFY** against the provider's published list. `price_staleness()` prints the warning once the table is over 30 days old. |

`claude-sonnet-4-6` is priced at **$3.00 / $15.00 per million tokens**
(input / output) in `src/observability/costs.py`. Every figure in §3 is
computed at that rate.

### 2.2 The ids the gateway actually knows

`src/llm_models.py`'s exact-id table (ADR 0077), which is what decides
the shape of every request this campaign would send. It is the reason
§2.1's "re-pin" is a one-line change rather than a hunt: an id in this
table is a fully described id, and an id that is not is served a
conservative row with every opt-in feature off.
`CAPABILITIES_LAST_VERIFIED` is **2026-09-05**.

| Model id | `temperature` | adaptive thinking | `output_config.effort` | structured outputs |
|---|---|---|---|---|
| `claude-fable-5` | ✗ 400 | ✓ | low, medium, high, xhigh, max | ✓ |
| `claude-mythos-5` | ✗ 400 | ✓ | low, medium, high, xhigh, max | ✓ |
| `claude-opus-5` | ✗ 400 | ✓ | low, medium, high, xhigh, max | ✓ |
| `claude-opus-4-8` | ✗ 400 | ✓ | low, medium, high, xhigh, max | ✓ |
| `claude-opus-4-7` | ✗ 400 | ✓ | low, medium, high, xhigh, max | ✓ |
| `claude-opus-4-6` | ✓ | ✓ | low, medium, high, max | ✓ |
| `claude-opus-4-5` | ✓ | ✗ | low, medium, high | ✓ |
| `claude-sonnet-5` | ✗ 400 | ✓ | low, medium, high, xhigh, max | ✓ |
| **`claude-sonnet-4-6`** | ✓ | ✓ | low, medium, high, max | ✓ |
| `claude-haiku-4-5` | ✓ | ✗ | *(rejected outright)* | ✓ |
| `claude-haiku-4-5-20251001` | ✓ | ✗ | *(rejected outright)* | ✓ |

Eleven rows, and every one of them is also in
`PRICES_USD_PER_MILLION` — `tests/test_llm_models.py` holds the two
tables to the same set, so a fully-priced deployment is a fully
described one. Five family prefixes (`claude-fable-`, `claude-mythos-`,
`claude-opus-`, `claude-sonnet-`, `claude-haiku-`) catch an unseen
member of a known family and guess *downwards*.

**What §2.1's re-pin therefore costs, today.** Both roles resolve to
`claude-sonnet-4-6`, which is in the table and accepts the temperature
this campaign would price. Re-pinning to any other row is a settings
change with no code change — but re-pinning to a row whose
`temperature` cell reads ✗ silently changes the instrument, because the
gateway stops sending the sampling parameter §2.1 says was priced. A
re-pin across that line needs a sentence in §9's decision, not just a
new id.

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

*(The enforcement predicate `budget_stop_reached` has had a production
caller since P0-WO07b, and a test that stops a campaign at its cap — see
§8.)*

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
  `outputs/campaign/research-policy-v1/<campaign-id>/` per 07 §10, one
  directory per episode holding its sealed manifest and projection, its
  trajectory copy and sink reference, its attempt receipts, its record,
  its scores and its terminal `completion.json`; canonical events go to
  the durable sink at `outputs/trajectories/runs/<run_id>/`. Every
  event is `training_eligible: false`; consent for this lane is
  `evaluation_only` over a public benchmark, so no D8 decision on
  retained user or learner content is engaged. **A retention *period* has
  not been decided and is an owner call.**

---

## 7. The no-cost W10/W11 evidence

| Requirement | Where |
|---|---|
| W11 Stage-0 qualification | [`15-stage0-qualification-report.md`](15-stage0-qualification-report.md), and `tests/test_stage0_qualification.py` |
| W07b execution loop, full mock matrix at zero cost | report §12, and `tests/test_campaign_execution.py` |
| Dry-run lock over the whole suite, zero provider init | report §2 (300/240/60 as measured on 2026-09-05; 300/300/0 since arm E became runnable) |
| A/B/C/D sealed against real compiled graphs | report §3; arm E earns its own graph since ADR 0091 and is sealed by `tests/test_campaign_execution.py` |
| Four synthetic episodes, verified chains, zero parity mismatches | report §4 |
| Denominator and identity integrity | report §5 |
| Privacy, leakage, adversarial, ASR gate | report §6 |
| W10 calibration protocol and fixtures | [`14-judge-calibration-protocol.md`](14-judge-calibration-protocol.md), `src/calibration/` and its `packets`/`ingest` verbs, `eval_registry/` (the calibration suite moved there byte for byte, ADR 0089). Packets can be written and labels ingested; no human has labelled anything and no judge has been called. |
| Governance and threat review | [`13-governance-threat-review.md`](13-governance-threat-review.md) |
| Zero-external-call attestation | report §8 |

---

## 8. Preconditions not met today

An approval granted now could not be executed. Listing this in the packet
rather than discovering it after an approval is the point of the packet.

Until P0-WO20 this list was a *claim*: somebody had read the code and
believed these four lines were the whole of what was missing. It is now
a **measurement**. `python -m src.campaign rehearse --campaign-id <id>`
walks the funded path — approval check, ledger open, episode manifest
sealed against the real compiled graph, provider credential, provider
client — under `ANTHROPIC_API_KEY=local-preview-disabled`, and reports
where it stopped and what it found still owed. It runs no episode,
makes no network call, and leaves the campaign directory exactly as it
found it. Every line below that says "owed" is a line the rehearsal
derives from the tree on each run rather than one this document asserts.

### 8.1 Mechanical now — these three cost nothing and are done

| Was | Is now |
|---|---|
| The campaign execution loop does not exist | **Closed by P0-WO07b.** `src/campaign/execute.py` runs the pending episodes of a planned campaign; `completion.json` is written by production code, so the ledger's reconciliation path consumes receipts the loop wrote; `budget_stop_reached` — the between-episodes enforcement §3.4 relies on — has a caller and a test that stops a campaign at its cap. The full `20 x 3 x 5` mock matrix reconciles 300 completed and 0 excluded at `$0.000000` with `llm_calls=0` on every episode ([`15-stage0-qualification-report.md`](15-stage0-qualification-report.md) §12). |
| §1's scope is prose in this document | **Closed by P0-WO20.** [`campaigns/w12-arm-a-baseline.plan.json`](../../campaigns/w12-arm-a-baseline.plan.json) is the 60-episode arm-A design, checked in: campaign id, protocol and lock digests, the arm declaration digest, the case set in the task set's order, the repeats, the seed, every cap at zero, `chargeable: false`, `network_calls: 0`, and the command that produced it. `tests/test_campaign_plan_artifact.py` re-derives it from `eval_registry/` and compares byte for byte, so a registry change that moves a digest fails a test instead of leaving this packet describing a campaign nobody can plan. |
| §2's model ids are placeholders | **Closed by P0-WO20.** §2 now carries `src/llm_models.py`'s eleven exact ids and their capability rows, verified on `main` 334280d on 2026-09-17, with the price cells deliberately untouched. |
| Nobody can tell whether *anything else* is missing without funding a run | **Closed by P0-WO20.** `rehearse` is that answer, and 8.2 and 8.3 are what it returns. |

**None of this makes a figure in §3 measured.** The token counts are
still assumptions and the prices are still stale; the plan artifact
describes a design, not a result.

### 8.2 Still the owner's — three lines, none of them code

1. **An approval record.** `LocalApprovalRecordBackend` reads a JSON
   file of records and delegates verification to W03's
   `FakeLocalApprovalBackend`. It fails closed correctly and it is not a
   record an owner created. The rehearsal reports this line as owed
   whenever the backend it was handed holds nothing — and proves the
   machinery behind it works, because
   `tests/test_campaign_rehearsal.py` rehearses a chargeable campaign
   against a record built the way an operator would build one, and that
   walk verifies the approval, seals the manifest, and stops at the
   credential.
2. **Prices re-verified, ids re-pinned at run time.** §2. The *ids* are
   now pinned and both roles resolve to a fully described model; the
   *prices* were last verified 2026-08-20 and `price_staleness()` says
   so. This line stays owed on every rehearsal by construction: 07 §4
   requires the resolution to happen immediately before the run, and no
   check in this repository can stand in for reading the provider's
   published list.
3. **Token counts measured.** §3's basis. The rehearsal reads the
   campaign's own completed count and reports this owed while it is
   zero. A single episode under a separately approved micro-cap would
   replace every assumption in that table with a measurement, and is
   still the cheapest way to make this packet real.

### 8.3 Found by the rehearsal — §1's corpus mode is not a funded run's

This one is new, and it is the reason a rehearsal is worth more than a
re-read.

`corpus_mode: snapshot` in §1's table means `CorpusMode.SUPPLIED`, and
`src/contracts/research_binding.py:source_scope` resolves *supplied* to
exactly one thing: `USE_MOCK_DATA=true`, the five fixture papers of
ADR 0041. Under that setting ADR 0080 makes all five research agents
model-free — planner, reader, synthesizer, critic and verifier are
served by `src/agents/mock_mode.py` and no client is constructed at all.
So the scope as §1 writes it is not a campaign that could spend $22 or
$60; it is a campaign that spends **$0.000000** and measures nothing,
which is precisely what 15 §12's mock matrix already did.

Measured, both ways, on `main` 334280d:

| Deployment | `corpus_mode` | What `rehearse` reports |
|---|---|---|
| `USE_MOCK_DATA=true` | `snapshot` | Walks to `provider-credential-probed`. Every earlier step passes; both provider doors refuse under the sentinel. **And no model would ever be called, because mock mode serves every agent.** |
| `USE_MOCK_DATA=false` | `snapshot` | Refuses at `episode-manifest-sealed`: *"campaign declares corpus_mode=snapshot but the episode resolves to live"*. |
| `USE_MOCK_DATA=false` | `live`, zero cap | Refuses at `episode-manifest-sealed`: *"episode admission failed closed: task policy forbids chargeable work"* — the metered provider fails closed against a zero budget, exactly as invariant 10 requires. |
| `USE_MOCK_DATA=false` | `live`, positive caps, approval record | Walks to `provider-credential-probed`. This is the funded shape, and nothing in the path is missing before the credential. |

**What this means for the decision in §9.** A funded arm-A baseline has
to be planned `--corpus-mode live`, which moves the campaign id (the id
digests the protocol) and makes §5's `source-drift` stop rule — written
as "stop if the resolved corpus mode is not `snapshot`" — read backwards
for the campaign it would govern. Two consequences the owner is owed
before answering §9, and neither is fixed here because both are the
owner's call:

- **§1's `snapshot` row and §5's `source-drift` rule need restating for
  a live baseline**, or the baseline needs a controlled corpus that is
  not the mock fixture set. This repository has no third option today.
- **The variance a live baseline measures includes arXiv's own
  variability**, which is not what §1 set out to size. That is a design
  question for whoever answers §9, not a defect in the code.

The checked-in plan artifact stays `snapshot` on purpose: it is the
design §1 describes, published so that this disagreement is visible in a
diff rather than discovered by an approved run. §8.4 publishes the other
one beside it.

---

### 8.4 The two variants, side by side — REQUIRES OWNER DECISION

§8.3 established that the baseline §1 describes and the baseline §1
*wants* are not the same campaign. Rather than rewrite §1 on the owner's
behalf, both designs are now published, produced by the same
`dry-run --artifact` path from the same registry and differing in
exactly one argument. Neither is approved, both are sealed at zero caps,
and planning either one costs nothing and contacts nobody.

| | `snapshot` variant | `live` variant |
|---|---|---|
| File | [`campaigns/w12-arm-a-baseline.plan.json`](../../campaigns/w12-arm-a-baseline.plan.json) | [`campaigns/w12-arm-a-baseline-live.plan.json`](../../campaigns/w12-arm-a-baseline-live.plan.json) |
| Command | `--corpus-mode snapshot` | `--corpus-mode live` |
| Campaign id | `camp_8c810c0a9a334487b37330d20a6c67d5` | `camp_d53219123389b6b6f2de22c44d0926a5` |
| Protocol digest | `sha256:9a7e1805…bd5e5b71` | `sha256:f5b3e627…bebeb063b` |
| Registry lock digest | `sha256:d45d39fd…c7d20a18` | `sha256:77ceba17…4b2a70bd` |
| Design matrix | 20 cases × 3 repeats × arm A = 60 | identical, slot for slot |
| What it would measure | nothing: `snapshot` resolves to `USE_MOCK_DATA=true`, ADR 0080 serves all five agents from `src/agents/mock_mode.py`, no client is constructed | a real arm-A baseline on `supported_claim_precision`, with arXiv's own variability inside the variance |
| What it would cost, funded | `$0.000000` | §3's estimate, once §2's ids are re-priced |
| §5 `source-drift` | satisfied trivially — the rule stops a run whose corpus is *not* `snapshot` | **reads backwards**: the rule as written would stop this campaign at its first episode |
| `chargeable` / `approval_id` / `network_calls` | `false` / `null` / `0` | `false` / `null` / `0` |

The three digests move together because all three take the corpus mode
as input; the design, the case ids in the task set's own order and the
arm declaration digest do not move at all, which is what makes the two
files a choice between variants rather than two different experiments.
`tests/test_campaign_plan_artifact.py` holds both to byte equality
against the registry and asserts that exactly those fields differ.

One consequence is visible in the live file itself: its `describes`
field does **not** carry the packet preface the snapshot file carries,
because `is_w12_baseline` pins `corpus_mode=snapshot`. That is left as
it is rather than smoothed over. The live plan is not the scope §1
states, and a reader who opens the JSON alone should not be told it is.

Funding the live variant means restating §1's corpus row and §5's
`source-drift` rule. Funding the snapshot variant means accepting that
the run measures nothing a mock matrix has not already measured. There
is no third artifact here because this repository has no third option
today — **the owner chooses; nothing here is approved.**

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
