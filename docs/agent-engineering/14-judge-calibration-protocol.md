# Judge-calibration protocol, label schemas and synthetic fixtures

Status: **DESIGN PACKAGE — NO JUDGING, NO LABELING CAMPAIGN, NO SPEND**

Date: **2026-09-05**

Work order: [`12-p0-work-orders.md`](12-p0-work-orders.md) §16 (P0-WO10)

Roadmap item: [`04-roadmap.md`](04-roadmap.md) AE-004

Inputs:

- [`03-evaluation-strategy.md`](03-evaluation-strategy.md) §4, §7, §8
- [`07-first-policy-experiment.md`](07-first-policy-experiment.md) §7, §8, Stage 5
- [`11-benchmark-data-registry-rfc.md`](11-benchmark-data-registry-rfc.md) §9, §11, §22
- [`13-governance-threat-review.md`](13-governance-threat-review.md) §3, §5, §8
- `docs/eval.md` — "Run provenance", "Rubric versions", "Judge–human
  calibration remains unmeasured", "What calibration found"
- ADRs [0070](../decisions/0070-eval-integrity-provenance.md),
  [0071](../decisions/0071-eval-statistics-and-gates.md),
  [0072](../decisions/0072-adversarial-safety-suite.md),
  [0074](../decisions/0074-deterministic-groundedness.md),
  [0075](../decisions/0075-scripted-research-tier-and-paired-claims.md)

**Nothing in this document has been executed.** No judge, provider or
paid grader has been called; no human-labeling campaign has started; no
owner or expert time has been committed. §12 lists exactly which steps
need which of those, and every one of them is still ahead of us. What
exists today is a vocabulary, a plan, a synthetic fixture corpus, a
metrics module and a gate — all of them running locally at zero cost.

---

## 1. What this package is for

`docs/eval.md` states the current position plainly: **judge–human
agreement is unmeasured on all four research metrics**, and it is
deferred rather than planned, "because it needs labelled human verdicts
nobody has produced". AE-004 is the item that changes that, and 12 §16 is
the no-cost half of it — everything that can be built before an owner
commits expert time or model spend.

The frame that shapes every decision below comes from 03 §7's first
sentence: **LLM judges are instruments, not labels.** An instrument can
be calibrated, and a calibrated instrument can carry a release gate. An
uncalibrated one produces numbers that look like measurements, and this
repository already publishes four of them.

So this document answers five questions:

1. What is a human calibration label, exactly, and what happens when two
   annotators disagree? (§3, §4, §5)
2. How many labelled items does each task slice need, and what can twenty
   queries actually resolve? (§6)
3. How is the judge blinded, and how is position bias measured rather
   than assumed? (§7)
4. What adversarial cases must the set contain, and what do they predict?
   (§8)
5. How is agreement reported, and when may a judge gate a release? (§9,
   §10)

Plus the two things an owner needs before saying yes: a cost and time
estimate with stop conditions (§11), and a list of what needs expert time
or paid calls (§12).

## 2. What landed with this document

| Artifact | Where | What it is |
|---|---|---|
| Label schemas | `src/calibration/labels.py` | The four label types, the annotator vocabulary, adjudication records, and the projection into W02's `LabelRecord` |
| Blinding and randomisation | `src/calibration/blinding.py` | Blinded ids, the hidden-field set, the seeded presentation schedule, the leak scan |
| Sampling plan | `src/calibration/sampling.py` | The ten task slices, the failure taxonomy, and the item counts derived from `src/eval/stats.py` |
| Calibration metrics and gate | `src/calibration/metrics.py` | φ/MCC with both positive rates, false pass/fail, abstention, position bias, slice coverage, and PROMOTE/HOLD/ROLLBACK |
| Adversarial fixtures | `tests/fixtures/calibration/` | 24 single-item cases across six families, 6 pairwise pairs in both orders, and a 12-item worked labelled set with full lineage |
| Fixture loader and validators | `src/calibration/fixtures.py` | Refuses a case that misstates its own outcome, or claims a measured verdict |
| Registry suite | `src/calibration/suite.py`, `eval_registry_calibration/` | `judge-calibration-v1`: 30 task cases, an evaluator-only label set, a grader profile pinning no model, a synthetic-generation record |
| Cost and time estimate | `src/calibration/estimate.py` | The template, its stop conditions, and one worked example at today's prices |

Tests:
`tests/test_calibration_{labels,metrics,sampling,blinding,fixtures,suite,estimate,protocol_doc}.py`
— 362 of them. The last one re-derives every number in *this document*
from the modules above rather than trusting the prose, in the manner
`tests/test_documented_claims.py` established: a sentence that stops
being true fails a test that quotes it back.

## 3. Label schemas

### 3.1 Four types, not one score

03 §7 asks for rubric-level and claim-level judgments rather than one
holistic score, so there are four label types and they have different
denominators:

| Type | Question | Decisions | Denominator |
|---|---|---|---|
| `claim_support` | Does the cited source support this claim? | `supported`, `unsupported`, `contradicted`, `not_verifiable`, `abstain` | per checked factual claim |
| `citation_correctness` | Does this citation point at a source that carries the claim? | `correct`, `wrong_source`, `unresolvable`, `abstain` | per resolved citation |
| `rubric_coverage` | Is this rubric item satisfied, with admissible evidence? | `covered`, `partial`, `not_covered`, `abstain` | per rubric item |
| `pairwise_preference` | Which of two reports is better? | `first`, `second`, `tie`, `abstain` | per pair, per presentation |

Three vocabulary choices are load-bearing.

**`contradicted` is separate from `unsupported`.** 03 §4 asks for
contradiction recall as its own measure. A source that says the opposite
is a different failure from a source that is silent, and collapsing them
hides the one that matters more.

**`not_verifiable` is separate from `abstain`.** The first is a property
of the item — no admissible evidence could settle it. The second is a
property of the annotator — I cannot decide from what I was shown. Both
project to "nothing" on the pass/fail axis, and 07 §7 requires that they
stay visible and never become passes.

**`first` and `second` are positions, not candidates.** That is what
makes position bias measurable at all (§7).

### 3.2 What one label carries

Every `CalibrationLabel` records:

- `label_id` — stable within its set;
- `blinded_item_id` — `itm-<12 hex>`, never the case id, the arm, or the
  candidate. An annotator who can see which arm produced a report is not
  blind, and a label that records the arm un-blinds every later reader;
- `label_type` and `decision`, checked against that type's vocabulary;
- `confidence` — `low` / `medium` / `high`. A **category**, because 03 §4
  is explicit that "confident writing is not confidence data" and because
  three buckets can be adjudicated where a float invites an average
  nobody can defend. Used for routing (03 §7.8 sends low-confidence items
  to adjudication), never for weighting;
- `rationale_ref` — a reference, not inline prose, so the rationale can
  carry a stricter data class than the label and so deleting it under 13
  §6 does not destroy the lineage;
- `annotator` — an **opaque pseudonym** (`ann-<id>`) plus a kind plus the
  guideline revision that annotator was working from. 13 §3.1 makes the
  pseudonym-to-person mapping a separate, key-erasable record owned by
  the human-evaluation steward;
- `labeled_at` — RFC 3339 UTC;
- `guideline_ref` — the exact guideline revision object;
- `time_spent_seconds` — optional, and `None` when unmeasured rather than
  zero as a stand-in. It feeds §11's expert-time budget.

### 3.3 A model verdict is not a label

`AnnotatorKind` names five kinds. Four may produce a reference decision:

| Kind | May be reference truth | Counts as expert time |
|---|---|---|
| `human_expert` | yes | yes |
| `human_reviewer` | yes | yes |
| `deterministic_check` | yes — reproducible, and its definition is versioned (ADR 0074) | no |
| `synthetic_construction` | yes, **only for authored fixtures** — see §8.4 | no |
| `model` | **never, at any temperature** | no |

`CalibrationLabel` raises on a `model` annotator by name. A judge's
answer is a `JudgeVerdict` — a different type, with a grader profile, a
rubric name and a rubric version instead of an annotator, because what
produced it is an instrument configuration. **There is no way to spell
"a model produced ground truth" in this vocabulary.**

RFC 11 §9.2 permits model output to become a *weak-label* dataset later,
under a separately approved data process, and requires it to stay
distinguishable from human or deterministic truth. The type split is what
makes that promotion something somebody has to write rather than
something that happens by leaving a field set.

`model` stays in the vocabulary precisely so it can be named and refused.
A vocabulary that omitted it would leave "a model wrote this" expressible
as a human kind with a machine behind it.

### 3.4 How this maps onto the registry

W02's `LabelRecord` (RFC 11 §9.2) is the immutable registry primitive:
one target ref, one opaque `label_type`, one `value_ref` to a content
object, one `annotator_id`, an `agreement_state` and a supersession
slot. It is deliberately generic, and generic is why it needs the
vocabulary above sitting over it.

`registry_label_records()` projects one labelled item into:

- **one record per individual decision**, with `label_type` set to
  `<type>.<annotator_kind>` so the registry itself says what produced
  each one; and
- **one record for the adjudicated outcome**, `agreement_state`
  `adjudicated`.

The adjudicated record does **not** set `supersedes_ref`. Adjudication
*adds* a record; pointing supersession at the decisions it settled would
encode exactly the overwrite RFC 11 §9.2 forbids. Supersession stays
reserved for a corrected label — a different event with a different
meaning.

Decision *values* are bound by `value_ref` digest to small content
objects, which is W06's finding applied here: a reference answer lives in
a content object, so "how many items were called unsupported" is
answerable by counting refs, and every label naming that decision shares
one digest.

## 4. Annotation guide

This is the guide an annotator works from. It is versioned: changing it
changes `guideline_revision`, and labels from before and after are two
populations that a report must not average. `src/calibration/suite.py`
registers revision `1.0.0` as `calibration_guideline` content.

### 4.1 The general rules

1. **Judge the claim against the source shown, and nothing else.** Not
   against what you know to be true. A correct claim cited to a source
   that does not carry it is `wrong_source`, not `correct`.
2. **Never reward fluency, length, hedging, or confidence.** A report
   that reads well and asserts something the source does not say is
   `unsupported`. A report that reads badly and is entailed is
   `supported`.
3. **Naming a genuine evidence gap is satisfying the gap item**, not
   failing the question. This is the behaviour 07 §7 asks for when it
   says abstained claims stay visible and do not become passes.
4. **You may not resolve your own disagreement by averaging.** If you and
   another annotator differ, the item goes to adjudication with both
   decisions intact.
5. **Write a rationale for every decision**, one or two sentences, naming
   the sentence in the source you relied on. An adjudicator cannot review
   a decision that gives no reason.
6. **If you can see which arm, model or system produced a report, stop
   and report a blinding breach.** Do not label the item.

### 4.2 Claim support

- `supported` — the cited source states the claim, or entails it without
  a further assumption. "Entails without a further assumption" means: a
  reader who accepts the source must accept the claim. A source reporting
  "a 7.8-point improvement" supports "improves recall"; it does not
  support "improves recall substantially in production".
- `contradicted` — the source states the reverse of the claim, or states
  something the claim cannot be true alongside.
- `unsupported` — the source exists and is silent, or says less than the
  claim. **Clause 4.2 (the worked disagreement in
  `labelled_set.json`):** when a source exists and is silent, the
  decision is `unsupported`; `not_verifiable` is reserved for claims that
  *no* admissible source could settle.
- `not_verifiable` — the claim is not the kind of thing the corpus could
  settle (a value judgement, a prediction, an unfalsifiable framing).
- `abstain` — you cannot decide from the material shown. Say why.

Quantifier claims are the trap this set is full of. "The literature
agrees that X" is a claim about the literature, and a source reporting X
while naming a disagreeing study does not support it.

### 4.3 Citation correctness

The identifier already resolved — that is decidable without a person, and
`src/eval/groundedness.py` (ADR 0074) does it. This label starts where
the deterministic check stops:

- `correct` — the resolved source carries the associated claim.
- `wrong_source` — the source is real and does not carry the claim.
  Includes the common case where the claim is *true* and the citation is
  to the wrong paper.
- `unresolvable` — the citation is malformed or names nothing in the
  retrieved corpus. (Overlaps the deterministic check; kept so an
  annotator is never forced to pick a wrong label.)
- `abstain` — as above.

### 4.4 Rubric coverage

- `covered` — the rubric item is satisfied **with admissible evidence**.
  A statement naming a genuine evidence gap satisfies the gap item.
- `partial` — some of the item is satisfied. Projects to *not satisfied*
  on the binary axis, because 07 §7 defines task-rubric success as items
  satisfied with admissible evidence and a half-answer is not one.
- `not_covered` — the item is not addressed, or is addressed without
  admissible evidence.
- `abstain` — as above.

### 4.5 Pairwise preference

- Read both reports. Decide which better answers the question with
  admissible evidence.
- **Record the position you chose, not the report you think it was.**
  Annotators see one order only; the swap is a judge control (§7), and
  asking a person to read the same pair twice measures their memory.
- `tie` is a real answer and is not a failure to decide. `abstain` is for
  a pair you cannot compare at all.

## 5. Disagreement and adjudication

### 5.1 The rule

**Disagreement is retained. Adjudication creates a new record; it never
deletes or overwrites the decisions it settles.** RFC 11 §9.2, 11 §22
("preserve individual labels plus adjudication, never consensus-only
overwrite"), 12 §16, and 13 §3.1 all say this, and
`AdjudicationRecord` is the shape that enforces it: the individual
decisions are *inside* the record.

An item whose annotators disagree with **no** adjudication has **no
resolved decision**. Not a majority, not the first label, not the
expert's. `LabelledItem.resolved_decision` returns `None`, the item is
reported as `disputed`, and it stays out of every denominator until a
person settles it. Anything else is the consensus overwrite wearing a
default's clothes, and
`find_integrity_violations()` raises it as an integrity violation if a
report tries to count one.

### 5.2 The five rules, and when each applies

| Rule | Applies when | Requires | Outcome may differ from the decisions |
|---|---|---|---|
| `unanimous` | Every decision agrees | — | no |
| `majority` | A strict majority exists | ≥3 decisions in practice | no |
| `expert_override` | The adjudicating expert finds something no annotator claimed | An expert adjudicator **and** a written rationale | **yes** |
| `guideline_rule` | A guide clause settles it | A rationale naming the clause | no |
| `unresolved` | The adjudicator cannot settle it from the material | A rationale | outcome is `None` |

Every rule requires a **human** adjudicator. A deterministic check can
produce a label and cannot settle a dispute between two people about what
a source says.

`unresolved` is not a failure to record. It is an item the material
cannot decide, it is reportable, and it stays out of every denominator —
`labelled_set.json` carries one as a worked example.

### 5.3 The escalation path

1. Two annotators label every item independently. They do not see each
   other's decisions or rationales.
2. Items where they agree are `agreed` and resolve without an
   adjudicator.
3. Items where they disagree, **plus** items where either annotator
   recorded `low` confidence, go to a third reader. 03 §7.8 asks for
   exactly this routing.
4. The adjudicator reads both rationales and the material, and records
   one of the five rules above.
5. An adjudication backlog above a quarter of labelled items, or one
   annotator diverging from every other on more than half of shared
   items, **stops labeling** and triggers a guide revision (§11's
   `annotator-disagreement-collapse`). Resume under a new guideline
   revision; do not re-label the backlog under the old one.

### 5.4 The rule that has no exception

**A label is never edited after seeing a judge's verdict on it.** RFC 11
§11: benchmark failures and negative results do not authorize editing a
label to favour a candidate, and a judge verdict is a candidate result. A
genuine labelling error is fixed by a *superseding* record carrying its
own rationale, in the open, not by an edit.

## 6. Sampling plan

### 6.1 Two different sizing questions

Conflating these is how a calibration set ends up either unaffordable or
meaningless.

**The judge question is precision.** "Can this judge gate a release?" is
about *bounds*: is the false-pass rate below the ceiling, and how wide is
the interval. That is `items_for_precision()` and
`items_to_bound_below()`, both searching `src/eval/stats.wilson_interval`
rather than quoting a normal-approximation formula that is wrong at
exactly this n.

**The campaign question is separation.** "Is arm B better than arm A?" is
about *differences*, and 07 §8 fixes the method: paired over queries,
repeats nested inside. That is `mcnemar_required_pairs()` and
`unpaired_required_per_arm()`.

Every number below is produced by calling those functions, and
`tests/test_calibration_sampling.py` reproduces each one.

### 6.2 The noise floor of a twenty-query set — stated explicitly

> **Noise floor at 20 paired items.** The smallest difference that
> reaches significance at all is **20%**; the smallest detectable at 80%
> power is **35%**. A 5-point move needs **77 pairs** to be significant,
> **155** to be detected, and about **906 items per arm** without
> pairing. A per-slice gate on 20 items is therefore a threshold printed
> beside a coin flip, and every slice number below is a diagnostic.

Two more numbers make it concrete. A Wilson interval on 16 of 20 —
an observed 80% — runs `[0.584, 0.919]`, a width of 0.335. On 20 of 20
it still runs `[0.839, 1.000]`. `small_sample_caveat()` prints the
sentence a report owes its reader below 200 datapoints, and every
calibration report carries it.

The consequence for this protocol: **the 20-query research benchmark can
carry a calibration set's *items*, but it cannot carry a per-slice gate.**
Slice rates are reported as diagnostics with their intervals, and 03 §8
is the reason — multiple slices are diagnostic unless a correction and a
gate were declared in advance, and this protocol declares neither.

### 6.3 The slices

Ten task slices, from 07 §8's five required axes at two levels each. Two
levels rather than three is a sizing decision: at the item counts below,
a third level buys a third interval too wide to read.

| Axis | Slices |
|---|---|
| retrieval vs synthesis | `retrieval-heavy`, `synthesis-heavy` |
| straightforward vs ambiguous | `straightforward`, `ambiguous-comparative` |
| evidence density | `evidence-rich`, `evidence-sparse` |
| contradiction present | `contradiction-present`, `contradiction-absent` |
| baseline difficulty | `baseline-easy`, `baseline-hard` |

Every slice records its own **assignment rule**, and `SliceSpec` refuses
a spec whose membership is assigned from candidate outcomes — 07 §8
requires assignment "without looking at candidate outcomes". The
difficulty axis is the one that could go wrong, so its rule names the
*baseline* arm's recorded results and freezes membership before any
candidate runs.

### 6.4 The failure taxonomy is a stratification, not a sizing axis

03 §8's thirteen classes are carried in `FAILURE_CLASSES` and used as
reporting tags. They are **not** sized: ten slices times thirteen classes
is 130 cells, and a calibration set that powered every cell would need
tens of thousands of expert judgements. Reporting is per class with its
interval; gating is not.

### 6.5 The item counts

Planning inputs: an expected false-pass rate of 10%, a declared ceiling
of 10%, and 95% two-sided intervals throughout.

| Question | Items | What it buys |
|---|---|---|
| Per-slice diagnostic interval | **34** per slice | ±0.10 half-width on a rate near 0.10 |
| Whole-set interval | **141** | ±0.05 half-width on a rate near 0.10 |
| Whole-set bound at an observed 5% | **127** | Wilson upper bound clears the 10% ceiling |
| Whole-set bound at an observed 2% | **53** | as above |
| Whole-set bound at an observed 0% | **35** | as above; agrees with the rule of three's `3/n ≤ 0.10` at n≥30 |
| Pessimistic total if no case belonged to two slices | 340 | ten slices at 34 |

Each slice is sized identically, deliberately: allocating more items to a
slice because it "looks harder" is allocating from a prior, and the same
rule that fixes slice *membership* before outcomes are seen should fix
slice *size*. A campaign that later observes a much higher rate on one
slice may re-size it — as a new plan revision with a recorded reason.

**The recommended first set is 141 items, stratified across the ten
slices, reported with whole-set bounds and per-slice diagnostics.** Not
340: the marginal slice precision is not worth 200 extra expert
judgements before anyone has seen a single real disagreement rate.

For the campaign question, unchanged from ADR 0071: **77** paired
episodes for a 5-point arm difference to reach significance, **155** at
80% power, **906** per arm unpaired.

### 6.6 What exists today

**30 synthetic items.** That is the pilot, it is one fifth of the
recommended set, and every one of its reference decisions is a
construction fact rather than an expert judgement (§8.4). It proves the
pipeline runs. It calibrates nothing.

## 7. Blinding and randomisation

### 7.1 What the judge must not see

03 §7.2 names two things — candidate identity and experiment arm. The
plan hides those **and the fields that reconstruct them**, because a
report tagged with its policy, its model, its run id or its cost is not
blinded, it is blinded in the one field somebody remembered:

`arm_id`, `candidate_id`, `policy_id`, `model_id`, `prompt_version`,
`run_id`, `repeat_index`, `campaign_id`, `cost_usd`, `latency_ms`,
`split_membership`, `reference_answer`, `expected_label`.

A `BlindingPlan` that hides fewer is refused. It may hide more.

### 7.2 Two layers

**Layer one — identity.** Items are addressed by
`itm-<12 hex>`, derived as `sha256(salt ‖ NUL ‖ case_id)` truncated to 48
bits. The salt lives in an evaluator-only object and never appears in a
label, a verdict or a report, so the blinded corpus can be handed around
without handing around the key. (The NUL separator is not decoration:
without it `("ab","cd")` and `("a","bcd")` collide, and a campaign that
salts per slice would get two slices sharing an id.)

**Layer two — content.** `leaked_identity_terms()` scans every *rendered*
judge input for arm names, policy names and model ids, word-boundary
anchored and case-insensitive. It catches the identity that came back
through the prose after the fields were already clean: a report that says
"the verify-and-repair pass found", a heading with an arm label. **A
finding here is an integrity violation, not a warning** (§10), and it
stops the campaign (§11).

### 7.3 Order randomisation, and the position-bias test

`docs/eval.md` records the state of the evidence this design is written
against: **verbosity bias has collapsed** (below 0.011 across 21 measured
judges) and **position bias has not**. The control it names is swap/AB+BA
averaging.

So every pairwise item is presented in **both** orders. Not sampled into
one: a single-order design gives a preference rate with a position
confound inside it and no way to separate them afterwards, and
`BlindingPlan` refuses a pairwise plan that does not swap.

Position bias is then a measured quantity:

- `first_position_rate` — the share of readings won by whichever report
  was shown first. An `ab` reading of "first" and a `ba` reading of
  "first" name **different reports**, so an unbiased judge splits them
  and an always-first judge produces two wins on the same pair.
- `bias` = `first_position_rate − 0.5`. Zero is unbiased, so this is the
  quantity the threshold applies to.
- `consistency_rate` — the share of pairs where both orders picked the
  same report. The complementary view, reported beside the rate so a
  reader does not take the arithmetic on trust.
- `ties` — counted and excluded from the position share, because a judge
  that ties everything has no measurable position bias and that is a fact
  about the judge rather than a clean bill of health.

A pair seen in one order contributes nothing and is reported as
**unmeasured**. Unmeasured is not zero, and the gate answers HOLD.

The presentation schedule is seeded (`random.Random(seed)`, its own
instance, as `src/eval/stats.py`'s bootstrap does) and shuffles the
flattened list so the two orders of one pair are never adjacent — a judge
shown the same pair twice in a row is answering a memory question. What
the seed pins is the *schedule*: the Messages API exposes no sampling
seed, so a seeded schedule does not make a judge deterministic and this
protocol does not pretend otherwise.

Annotators, unlike judges, see **one** order. Asking a person to read the
same pair twice measures their memory.

## 8. Adversarial fixtures

### 8.1 The six families

03 §7.5 requires plausible unsupported prose, citation swaps, verbosity,
stylistic polish, and injected instructions in source text; 12 §16 adds
contradiction and honest abstention.

| Family | Cases | Probes |
|---|---:|---|
| `unsupported_polish` | 4 | Fluent, well-cited prose asserting something adjacent to what the source says |
| `verbosity` | 4 | Hedged padding around a false operative claim, and two verbose-and-correct controls |
| `citation_swap` | 4 | A real finding attributed to the wrong paper, from near-miss to far-miss |
| `injected_source_instructions` | 4 | Source text addressing the grader directly, from blunt to provenance-dressed |
| `contradiction` | 4 | A quantifier claim about the literature; a source stating the reverse |
| `honest_abstention` | 4 | A report naming a genuine evidence gap, which the rubric's gap item asks for |
| **pairwise** | 6 | Position bias, in both orders |

Every excerpt is written for this work order. No paper text is copied, no
model generated a case, and every arXiv-shaped identifier is invented
with a sequence number below 1000 so nothing in the corpus resolves to a
real record.

### 8.2 Every case carries its expected results

Each case declares its `expected_reference_decision`, its
`expected_judge_verdict`, and the `expected_outcome` cell it is designed
to land in. The outcome is **checked against `classify_outcome()` on
load**, so a case cannot claim to be a false pass while describing a true
one.

The predicted cells across the 24 single-item cases: 11 false passes, 5
true passes, 5 true fails, 3 false fails. That mix is deliberate — a
corpus of only false passes cannot tell a bad judge from one that says
"unsupported" to everything.

### 8.3 Every expected verdict is a hypothesis

`expected_judge_verdict` is a **prediction about a failure mode, written
before any judge ran.** The loader refuses a case whose `verdict_basis`
says `measured`, and `decide()` will never PROMOTE a report whose basis
is `hypothesis`. That refusal is the mechanical form of this work order's
central constraint: no judge has been called, and a fixture asserting a
measured verdict would be the first place that stopped being true.

Where the prediction is that the judge gets it *right* — the verbosity
controls, the resisted injection, the far-miss citation swap — the
reasoning is written into the case's `why`, and it is usually that the
refutation is arithmetic or explicit rather than rhetorical.

### 8.4 A stress set is not a calibration set

This is the most important sentence in §8. **Every case here was authored
to trip a judge, so the rates it produces describe the corpus.** Pooled
with a representative sample they would drag every number down; reported
alone they say "the judge fails 11 of 24 cases we designed to make it
fail", which is a sentence about the fixture author.

So each file declares a `stratum`, the loader refuses to mix two, and the
protocol reports the two strata separately and never averages them. Only
the representative stratum can size a gate.

There is a second reason these items cannot count toward AE-004. Their
reference decisions carry annotator kind `synthetic_construction`: on an
item this repository *authored*, the reference is a fact about the
construction — the source excerpt was written not to contain the claim —
so it is true by the same mechanism that makes a unit-test expectation
true. It is not an expert judgement about a real report, it has one
"annotator" and therefore no possible disagreement, and
`campaign_eligible()` disqualifies every one of them.
`tests/test_calibration_fixtures.py` asserts that the whole stress
corpus is disqualified.

### 8.5 The worked labelled set

`tests/fixtures/calibration/labelled_set.json` is the other half: twelve
items with the lineage a real campaign produces — two and three
annotators per item, genuine disagreement, one adjudication under each of
the five rules including an escalation that resolves to nothing. Its
confusion table is hand-computed in the tests: 4 true passes, 2 false
passes, 3 true fails, 1 false fail, 1 judge abstention, 1 unresolved
reference. Every `rationale_ref` and `guideline_ref` in it is the sha256
of the content carried beside it and the loader checks that, so editing a
rationale without re-deriving its digest fails the load.

It is a worked example for the annotation guide, and it is twelve items.
It calibrates nothing either.

### 8.6 The registry suite

`eval_registry_calibration/` holds `judge-calibration-v1`: 30 task cases,
an evaluator-only label set of 30 reference decisions bound by
`value_ref` digest, a rubric set whose every item is evaluator-only, a
development split, a retention policy, and a grader profile that **pins
no model** — RFC 11 §9.3 makes selecting a model grader invalid without a
recorded cost approval, and there is none. What the profile pins instead
is the `judge_probe_lock`: the four rubric names, versions and prompt
digests `src/eval/metrics.RESEARCH_RUBRICS` publishes today. When a judge
is eventually measured, a version there that no longer matches the live
rubric is what makes the gate answer HOLD (03 §7.7).

Contamination is recorded as `public_repository` — the honest value the
moment this merges, and the reason `promotion` is a *prohibited* use on
every object. That the material is **synthetic** is a separate fact, and
`Exposure` has no value for it, so it lives in a
`synthetic-generation-record` content object per RFC 11 §11: generator,
empty `source_inputs`, `generated_by_model: false`, and the human review
record.

**Why a separate registry root.** W06's tree at `eval_registry/` is
guarded by tests that make it *exactly* what
`src/contracts/benchmark_adapters.py` builds — the file set is compared
byte for byte, the task-case ids are compared against the two benchmark
modules, and its parity report calls anything else `unregistered_object`.
Those are the right guarantees for a migration whose whole claim is
"nothing changed", and they mean a second suite cannot be added to that
root without weakening them. Its `ContentKind` enum is closed as well, so
this suite's content kinds could not be filed under
`eval_registry/content/` without editing W06's schema module. So the
calibration suite gets its own root **in W06's exact layout**
(`<kind>/<id>/<revision>.json`, content under `content/`), resolved by
W02's own `LocalRegistry` — which takes a root parameter precisely
because more than one tree can exist. Nothing about W06's tree changes,
and nothing about this one is special-cased.

`python -m src.calibration.suite parity` proves the checked-in tree is
what the fixtures build, exactly as W06's parity CLI does for its own.

## 9. Metrics, and the reporting form

### 9.1 The form was fixed before the measurement existed

`docs/eval.md` wrote down what this report must contain, and
`src/calibration/metrics.py` enforces all three clauses:

- **φ / MCC with both positive rates.** For binary verdicts Pearson,
  Spearman, Kendall, φ and MCC are the same statistic, and κ = q·φ is
  uninterpretable without the two positive rates.
- **Never quote raw agreement alone.** It overstates chance-corrected
  agreement by 33–41 points: in a 21-judge study, 85% exact match was a κ
  of about 0.48. Raw agreement is computed — a reader wants it — and
  `report_lines()` prints it on the *same line* as φ and both positive
  rates, so there is no line a reader can copy that carries it without
  the numbers that qualify it. A test asserts that property.
- **State how abstentions were counted.** The choice swings measured
  accuracy by 10–34 points on identical verdicts, so `AbstentionPolicy`
  is a required field of every report and
  `agreement_under_each_policy()` computes all three so the swing is
  visible rather than arguable.

φ is `None` — not `0.0` — when any margin of the table is zero. A judge
that passed everything, or a slice where the reference never said "fail",
means *this table cannot distinguish agreement from a constant answer*,
and reporting 0.0 would be a claim of "no association" the data does not
support.

### 9.2 The abstention policy this protocol recommends

`excluded`. An abstention is the judge declining to assert, and counting
a decline as a failure punishes the behaviour 07 §7 asks for. It is a
recommendation and not an assumption: the field is required, all three
are computed, and the abstention **rate** is always reported from the raw
triples so no policy can make abstentions disappear from the report that
measures them.

### 9.3 The six measures

| Measure | Numerator | Denominator |
|---|---|---|
| agreement (φ, raw, both positive rates) | — | items both sides decided |
| **false pass** | judge passed, reference failed | items the **reference called fail** |
| **false fail** | judge failed, reference passed | items the **reference called pass** |
| abstention | judge asserted nothing | items with a resolved reference decision |
| position bias | first-position wins | 2 × pairs shown in both orders |
| slice coverage | resolved items in the slice | the plan's per-slice target |

The three error denominators differ, and that is the point. False pass
over the reference-fail items answers "when the work was bad, how often
did the judge wave it through". Dividing it by all items instead would
make a judge look better simply by being given more good work.

A seventh number is reported and belongs to the campaign rather than the
judge: **unresolved reference rate**, over every item seen. A set with
many of them needs more adjudication before it gates anything.

Every rate carries its numerator, its denominator and a Wilson interval
from `src/eval/stats.py` — no second implementation of the same formula
— and a zero denominator produces `None` rather than 0.0.

## 10. The gate: may this judge gate a release?

AE-004's exit criterion is that judge performance is reported by slice
and **unsupported confidence is not used as a release gate**. `decide()`
is the refusal half, and it mirrors ADR 0072's safety gate field for
field — same three states, same `GateDecision` shape, and a test asserts
the two types have identical fields, because two gates in one repository
answering in different vocabularies is two things a reader has to learn.

| State | Means |
|---|---|
| **PROMOTE** | This judge may carry a release gate. |
| **HOLD** | Its numbers are diagnostics only. |
| **ROLLBACK** | It must not gate a release. |

Evaluated in a fixed order:

**1. The integrity veto, first and unconditionally.** Any of
`model_verdict_as_ground_truth`, `blinding_breach`,
`unadjudicated_dispute_counted`, `slice_reported_without_items`,
`reference_answer_visible_to_judge` is a ROLLBACK that **blocks even in
advisory mode**. No interval is computed. A calibration set with a
blinding breach in it is not a weaker measurement; it is a measurement of
something else. (`model_verdict_as_ground_truth` cannot be produced
today — the schema refuses it at construction — and stays declared
because a future ingest path reading labels from elsewhere will need to
raise it, and a violation class invented at the moment it is first needed
is one nobody wrote a response to.)

**2. Comparability and sufficiency → HOLD.** Predicted rather than
measured verdicts; a rubric version that has moved since the set was
labelled; fewer resolved items than the declared minimum; any planned
slice with no resolved item.

**3. The measurement.** The false-pass Wilson **upper bound** against the
ceiling, φ against its floor, and the position-bias interval against its
band. A bound that fails is ROLLBACK; an interval that straddles its
threshold is HOLD; all clear is PROMOTE.

An upper bound rather than a point estimate, because a point estimate of
0/12 is 0.0 and its upper bound is 0.24.

### 10.1 The proposed thresholds — not approved

| Threshold | Proposed | Why |
|---|---|---|
| false-pass ceiling (upper bound) | 0.10 | A judge that waves through one bad report in ten cannot gate a release whose primary outcome is supported-claim precision |
| φ floor | 0.60 | Below it the judge and the reference are barely related |
| position-bias band | ±0.05 | `docs/eval.md` records position bias as the one presentation bias that has *not* collapsed |
| minimum resolved items | 127 | What `items_to_bound_below()` says a 5% observed rate needs before its upper bound clears 10% |

`UsabilityThresholds.approved_by_owner` is fixed `False` and the model
**refuses** to be constructed with it true: an owner approval is recorded
in 07 §12's approval ledger, not typed into a threshold object. 07 §7
requires the non-inferiority margin to be set from the repeated baseline
and human calibration *before* candidate results are unblinded, and
neither exists.

### 10.2 HOLD is the expected answer, and it is useful

Every report this repository can produce today HOLDs, for the right
reason: the verdicts are predictions. "This judge's numbers are
diagnostics, not a gate" is a decision a campaign can act on. A green
light computed from eleven items is not.

## 11. Cost and time estimate

`src/calibration/estimate.py` is the template. It carries priced model
lines, expert-time lines, per-episode and campaign caps, an explicit
in-flight overshoot rule (12 §18 asks for it by name, because a ceiling
with no in-flight rule is a ceiling crossed once per concurrency unit),
and stop conditions.

**There is no field a caller can set to make an estimate into an
approval.** `requires_repricing` is fixed `True`, `campaign_started` is
fixed `False`, and no `approved` field exists — an object that could
represent an approval is an object somebody will eventually point at
instead of the ledger.

### 11.1 The worked example, at today's prices

Priced **2026-09-05** against `src/observability/costs.py`, whose
`PRICES_LAST_VERIFIED` is **2026-08-20**. Model: `claude-sonnet-5`
($3/$15 per million). 141 single-item probes, 40 pairs.

| Line | Calls | Tokens in/out | Cost |
|---|---:|---|---:|
| single-item verdicts | 141 | 2,200 / 200 | $1.354 |
| pairwise verdicts, both orders | 80 | 3,600 / 200 | $1.104 |
| repeat pass for judge self-consistency | 141 | 2,200 / 200 | $1.354 |
| **total model spend** | | | **$3.81** |

| Line | Items | Minutes each | People | Hours |
|---|---:|---:|---:|---:|
| claim-support and citation labelling | 141 | 6 | 2 | 28.2 |
| pairwise preference labelling | 40 | 8 | 2 | 10.7 |
| adjudication of disputed items | 35 | 10 | 1 | 5.8 |
| guide authoring and annotator calibration session | 1 | 240 | 1 | 4.0 |
| **total expert time** | | | | **48.7 h** |

Caps: **$0.05 per episode, $25.00 per campaign**.

**The finding this template exists to make visible: the model spend is
roughly the cost of a coffee and the human time is roughly a working
week.** An estimate reporting only dollars would answer the easy
question. Expert time is the binding constraint on AE-004, and it is the
number an owner is actually approving.

Every input above is an assumption and is labelled as one: the token
counts describe prompts that have not been written, the disputed fraction
is a planning figure (and is itself an output of the first campaign), and
the prices must be re-verified against the provider's published list
before this is presented. `price_staleness()` prints the sentence the
estimate owes its reader once the table is more than 30 days old, and
the rendered packet opens with `ESTIMATE ONLY — NOT AN APPROVAL` and
closes with `NOTHING IN THIS ESTIMATE HAS BEEN RUN`.

### 11.2 Stop conditions

Adapted from 07 §9 to a labeling campaign, because the failure modes of a
labeling run are not the failure modes of a policy comparison.

| Condition | Trigger | Action |
|---|---|---|
| `campaign-cap-reached` | Cumulative spend hits the campaign cap | Stop, finish in-flight calls, publish the partial report with its denominators. Stopping is an outcome, not a pause |
| `episode-cap-reached` | One item exceeds the per-episode cap | Score it null, **keep it in the denominator**, continue |
| `expert-budget-reached` | Approved hours exhausted | Stop labeling; report per-slice coverage and name every slice that fell short. An under-covered slice is reported unmeasured, never interpolated |
| `instrument-moved` | A prompt, rubric version, model route or source representation changes mid-campaign | Stop. Labels before and after measure two instruments; resume as a new campaign against a new probe lock |
| `blinding-breach` | Any rendered judge input names an arm, model or candidate | Stop immediately; discard every verdict after the breach. Gated at absolute zero |
| `annotator-disagreement-collapse` | Adjudication backlog above a quarter of items, or one annotator diverging from every other on more than half of shared items | Pause; revise the guide; resume under a new guideline revision. Do not re-label the backlog under the old one |
| `labels-would-be-edited` | Anyone proposes changing a label after seeing a judge's verdict | **Refuse.** Fix a genuine error with a superseding record and its own rationale |

## 12. What needs expert time or paid model calls — and none of it started

**This is the section an owner reads.** Everything above is built and
runs at zero cost. Everything below is blocked.

### 12.1 Needs approved expert time (blocked on an owner decision)

| Step | Who | Rough size | Blocked by |
|---|---|---|---|
| Draft the representative item pool: select 141 claims, citations and rubric items across the ten slices | maintainer or domain expert | ~8 h | owner time |
| Author guideline revision 1.0.0 for real material and run the annotator calibration session | expert | 4 h | owner time |
| Independent labelling, two annotators per item | 2 experts | ~39 h combined | 13 §5's human-label retention decision; D8.10 |
| Adjudicate disputed and low-confidence items | expert | ~6 h | as above |
| Assign slice membership for the difficulty axis from a frozen baseline arm | maintainer | ~1 h | needs a repeated baseline (AE-005/W12) |
| Review and activate a *representative* calibration suite revision | owner | ~1 h | RFC 11 §11 human review before activation |

13 §5's decision table has no approved retention policy for human labels,
and D8.10 requires "separate purpose authority, restricted evaluator
role, individual-label/adjudication lineage, accepted retention, and any
required time/spend approval" before a human-evaluation campaign. The
lineage half is built; the other four are owner decisions.

### 12.2 Needs paid model calls (blocked on D9)

| Step | Calls | Estimated | Blocked by |
|---|---:|---:|---|
| Judge every single-item probe once | 141 | $1.35 | D9 |
| Judge every pair in both orders | 80 | $1.10 | D9 |
| Second independent reading, for judge self-consistency | 141 | $1.35 | D9 |
| **total** | **362** | **$3.81** | D9 |

12 §2's D9 blocks every live baseline, model judge, paid label and funded
experiment. Possessing an API key or declaring a positive ceiling never
authorizes chargeable work (12 §3.10).

### 12.3 What has and has not happened

- **No judge, provider or grader call has been made.** Every
  `JudgeVerdict` in this repository carries `basis: "hypothesis"`, the
  fixture loader refuses one that claims otherwise, and `decide()` will
  never PROMOTE a report built from them.
- **No human-labeling campaign has started.** No annotator has been
  recruited, briefed or paid. The 30 reference decisions that exist are
  construction facts about synthetic items (§8.4) and `campaign_eligible()`
  disqualifies all of them.
- **No expert or owner time has been committed** beyond the authoring of
  this package.
- **No model is pinned** in the grader profile, and no cost approval
  exists for one.
- **Nothing in `src/eval/**` changed.** This package reads
  `src/eval/stats.py`, `src/eval/metrics.RESEARCH_RUBRICS` and
  `src/observability/costs.py`, and writes to none of them.

## 13. What W11 and W12 consume from this

**P0-WO11 (Stage-0 contract qualification)** takes:

- the `judge-calibration-v1` suite reference as a fourth registry object
  its dry-run campaign lock can resolve, in the evaluator role under
  `calibration` use;
- `find_integrity_violations()` and `leaked_identity_terms()` for its
  privacy/redaction/leakage/adversarial report;
- the negative-projection evidence in `tests/test_calibration_suite.py`:
  a candidate resolves neither the label set (denied by kind) nor a task
  case (denied by visibility) nor the answer-key content.

**P0-WO12 (funded repeated baseline)** takes:

- §11's estimate template as the shape of its approval packet's cost
  section — with prices re-verified, which `price_staleness()` will say
  out loud;
- §11.2's stop conditions;
- `decide()` as the answer to "may we gate on this judge", which will be
  HOLD until a representative set is labelled;
- §6.2's noise floor as the honest frame for what its first repeated
  baseline can and cannot resolve.

## 14. Open owner decisions

| Decision | Needed before | Recommendation |
|---|---|---|
| Human-label retention and consent (13 §5, D8.10) | Any labelling of real material | Adopt a labels-specific retention policy; do not inherit the registry's repository-history terms |
| Expert-time budget | The 48.7 h in §11.1 | Approve or cut a line; the pairwise set is the cheapest line to drop and costs the position-bias measurement |
| The four thresholds in §10.1 | Any PROMOTE | Set from the repeated baseline (07 §7), not from this document |
| Whether a validation/sealed calibration split is needed | Any promotion claim | Today's split is `development`, because a sealed split fails closed without the access broker 13 §8 leaves open |
| Which instrument to calibrate first | The first paid pass | `faithfulness` — it is the judge closest to supported-claim precision, the first primary outcome (D1) |

## 15. Validation

```bash
python -m ruff check .
python -m mypy --strict src/
python -m pytest -m "not e2e" -q
python -m src.calibration.suite parity
```

The parity command proves the checked-in `eval_registry_calibration/`
tree is exactly what the fixtures build. It writes nothing, calls
nothing, and costs nothing.
