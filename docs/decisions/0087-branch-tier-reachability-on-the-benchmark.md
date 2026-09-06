# 0087. The branch tier's rules, measured against the benchmark

- **Status**: accepted
- **Date**: 2026-09-06
- **Deciders**: agent-capability lane (CAP-04b)
- **Amends**: [ADR 0085](0085-deterministic-compute-controller.md) (the
  rule table), [ADR 0086](0086-orchestrator-workers-for-the-branch-tier.md)
  (the branch table this adds two rows to)
- **Closes**: [ADR 0091](0091-listwise-candidate-selection-and-the-marginal-stop.md)'s
  "the router declines T2 on the shipped suite"
- **Follows**: [ADR 0070](0070-eval-integrity-provenance.md) (a threshold
  an operator can move is one no evaluation can attribute a result to)

## Context

CAP-09 made arm E runnable and then measured what it does. The answer,
pinned in `tests/test_listwise_selection.py`, was that on
`research-policy-v1`'s twenty queries the deterministic router allocates
**T0 12 / T1 8 / T2 0**. Arm E's identity *is* the router (ADR 0089), and
its branch tier — the orchestrator-workers graph, the listwise selector
and the marginal stop — is the half of it that costs money. A funded
arm-E run against this suite would therefore have measured adaptive
compute without once exercising the thing that makes it adaptive.

ADR 0091 recorded that as a known gap rather than fixing it, and refused
the obvious fix by name: "**Retune `BRANCH_ENTITY_THRESHOLD` so the suite
reaches T2.** Rejected for ADR 0070's reason: a threshold moved to make a
test exercise a path is a threshold no evaluation can attribute a result
to." That refusal stands. This work order does not move a threshold.

What it does instead is measure the twenty queries first and design
second, because the interesting fact turned out to be one nobody had
looked for.

## The evidence

Every feature below is computed offline by `extract_features` from the
query text alone — no model, no plan, no clock. `tok` is
`query_tokens`, `ent` is `entity_count`, `cmp` and `frsh` are the
comparative and freshness cues. "Before" is the tier `decide_tier`
allocated at `max_tier=BRANCH_TIER` before this work order; "after" is
the tier it allocates now, with the reasons on the record.

| # | Case | tok | ent | cmp | frsh | Before | After | Reasons (after) |
|---|---|---|---|---|---|---|---|---|
| 1 | `hallucination-mitigation` | 12 | 0 | – | ✓ | T1 | **T2** | `freshness_cue`, `branch_open_enumeration` |
| 2 | `rag-multi-hop` | 8 | 0 | – | – | T0 | T0 | `default_t0` |
| 3 | `alignment-beyond-rlhf` | 11 | 2 | – | – | T1 | **T2** | `multi_entity`, `branch_open_enumeration` |
| 4 | `cot-reasoning-effects` | 11 | 0 | – | – | T0 | T0 | `default_t0` |
| 5 | `lora-vs-full-finetune` | 12 | 1 | ✓ | – | T1 | **T2** | `comparative_cue`, `branch_paired_comparison` |
| 6 | `vlm-spatial-reasoning` | 8 | 0 | – | – | T0 | T0 | `default_t0` |
| 7 | `long-context-efficiency` | 11 | 0 | – | ✓ | T1 | **T2** | `freshness_cue`, `branch_open_enumeration` |
| 8 | `reasoning-benchmarks` | 11 | 0 | – | – | T0 | T0 | `default_t0` |
| 9 | `moe-vs-dense` | 12 | 0 | ✓ | – | T1 | **T2** | `comparative_cue`, `branch_paired_comparison` |
| 10 | `coding-agent-safety` | 8 | 0 | – | – | T0 | T0 | `default_t0` |
| 11 | `tool-use-agents` | 12 | 1 | – | – | T0 | T0 | `default_t0` |
| 12 | `synthetic-data-training` | 11 | 0 | – | – | T0 | T0 | `default_t0` |
| 13 | `quantization-inference` | 12 | 0 | ✓ | – | T1 | T1 | `comparative_cue` |
| 14 | `in-context-learning-mechanisms` | 9 | 0 | – | – | T0 | T0 | `default_t0` |
| 15 | `scaling-laws` | 14 | 0 | – | – | T0 | T0 | `default_t0` |
| 16 | `jailbreak-robustness` | 11 | 1 | – | ✓ | T1 | **T2** | `freshness_cue`, `branch_open_enumeration` |
| 17 | `reasoning-fine-tuning` | 11 | 3 | – | – | T1 | T1 | `multi_entity` |
| 18 | `speculative-decoding` | 9 | 1 | – | – | T0 | T0 | `default_t0` |
| 19 | `interpretability-methods` | 10 | 1 | – | – | T0 | **T2** | `branch_open_enumeration` |
| 20 | `agentic-memory-architectures` | 10 | 1 | – | – | T0 | **T2** | `branch_open_enumeration` |

**Before: T0 12 / T1 8 / T2 0. After: T0 10 / T1 2 / T2 8.**

Four counterfactuals were measured before any rule was written, and
three of them are why the obvious fixes are not in this ADR:

- **Rule 9 (`branch_multi_entity_comparison`) fires zero times, and
  lowering `BRANCH_ENTITY_THRESHOLD` from 3 to 2 also fires zero times.**
  No query on the suite carries a comparison word beside two recognised
  entities. The threshold was never the binding constraint;
  `_is_entity_token` was. It recognises acronyms, internal capitals and
  digit-bearing tokens, so it counts one entity in "LoRA and full
  fine-tuning" and none at all in "mixture-of-experts models compare to
  dense models" — the operands of the suite's only two real system
  comparisons are invisible to it however low the threshold goes.
- **Rule 10 (`branch_plan_breadth`) is unreachable on every shipped
  path.** `src/api/runner.py::_compute_decision` and
  `src/campaign/execute.py::_tier_app` both call `extract_features` with
  the query alone, so `sub_question_count` is always `None` and
  `_branch_plan_breadth` correctly treats `None` as unanswered. It cannot
  be made reachable by passing the count either: the tier selects the
  *graph*, so it is decided before the planner runs. And the planner is
  instructed to "2-4 focused sub-questions", which puts `>= 5` past its
  own range; under `USE_MOCK_DATA` `mock_plan` returns exactly one.
- **No query trips two T1 escalations.** "Several independent difficulty
  signals ⇒ T2" would also have fired zero times.
- **`long_query` never fires.** The longest query on the suite is 14
  whitespace tokens against a threshold of 24.

**The learning lane cannot reach this controller at all**, so there is no
second table: `_compute_decision` returns `None` for any job whose
`kind` is not `research`, and `guided-learning-v1`'s cases are
`learning.guided_reading` tasks that run as `session` jobs on the guided
read session graph, which has no tiers.

## Decision

Two rules are **added** to `BRANCH_TIER_RULES`, and the two features they
read are added to `ComputeFeatures`. No threshold moves, no default
moves, and `TIER_RULES` — the table a deployment with the branch tier off
evaluates — is untouched.

The shared principle is ADR 0086's own, stated once: **a ranked corpus
ranks by one similarity, so it cannot give balanced coverage to several
independent lines of enquiry.** ADR 0085 wrote that as "one ranked corpus
cannot serve N compared systems" and "a plan past the planner's own range
is several questions". Both are the same claim, and both are detectable
before the planner runs.

### Rule 10, `branch_paired_comparison`

Fires when a comparison word is present **and** the query binds two
comparison *operands* with an explicit connective: `versus`, `vs`,
`compare(d|s) to`, `compare(d|s) with`, or the `between … and` frame.

Its falsifiable purpose: *a query naming two operands needs each covered,
and one similarity ranking over the whole query returns whichever operand
the literature is richer in.* It is falsified if the per-operand branches
of a two-way comparison return the same papers.

Two exclusions carry the rule's weight, and both are deliberate:

- **A bare coordinating "and" is not a connective here.** "How do modern
  low-bit quantization methods trade off inference cost and quality?"
  compares two *properties of one method class*; one corpus about low-bit
  quantization carries both, and it stays T1. `between` is included
  precisely because it is the word that requires two operands
  grammatically. This is also why `compare X and Y` is absent, which
  keeps ADR 0086's own pinned decision for "compare RAG and CoVe" at T1
  unchanged.
- **A connective without a comparison word is not a comparison.** "the
  relationship between attention and memory" binds two operands and
  compares nothing, so the rule asks for `comparative_cue` as well.

This does **not** overturn ADR 0085's "two entities is a comparison the
fixed path answers from one ranked corpus". That sentence was about
`entity_count`, and the evidence above shows `entity_count` never saw
these operands at all, so it was never tested. Where the two disagree —
a two-operand comparison whose operands are spelled out — the argument
above is the one on the record, and `BRANCH_ENTITY_THRESHOLD` keeps its
value and its meaning.

### Rule 11, `branch_open_enumeration`

Fires when an enumerative interrogative (`what`, `which`) is followed by
a plural **solution-class** noun: `approaches`, `methods`, `techniques`,
`architectures`, `defenses`/`defences`, `strategies`, `algorithms`,
`frameworks`, `designs`, `mitigations`, `schemes`.

Its falsifiable purpose: *a query that asks for members of a solution
class does not name them, so the plan has to discover them and each one
is its own retrieval.* This is rule 12's "a plan past the planner's own
range is several questions" read before the planner runs, which is where
it has to be read because the tier selects the graph. It is falsified if
such a query's branches converge on one sub-literature.

Three choices narrow it, and each is a claim rather than a convenience:

- **The interrogative is required.** A "how" question asks how one named
  thing behaves and its plural nouns *modify* that thing: "How do
  speculative decoding methods reduce LLM serving latency?" is one
  method family, not an open set. Every one of the suite's nine "how"
  queries is of that shape.
- **The noun must be plural, and a solution class.** A singular head asks
  for one answer ("What **role** does synthetic data play…", T0).
  Observation classes are deliberately excluded — `benchmarks`,
  `evaluations`, `mechanisms`, `findings`, `results` name studies *of one
  object of study*, and one ranked corpus about that object carries them.
  That is what keeps `reasoning-benchmarks`, `coding-agent-safety` and
  `in-context-learning-mechanisms` at T0.
- **Only the first interrogative is examined.** Exact rather than
  approximate: every later interrogative's window is a subset of the
  first one's.

### What is deliberately not added

Imperative and nominal breadth phrasings — "survey of…", "the landscape
of…", "an overview of…" — are absent. They fire on none of the twenty,
so this benchmark cannot attribute anything to them, and ADR 0070 does
not permit vocabulary that only an intuition supports. "state of the art"
is already a `FRESHNESS_CUES` phrase and stays there.

Rule 12 is kept, unreachable, for the reason ADR 0085 carried the
plan-time fields at all: the rule has to exist before the caller that
decides after planning does. Its unreachability is now pinned by a test
rather than left to be rediscovered.

## Consequences

- **Positive: arm E exercises all three of its tiers.** On
  `research-policy-v1` the router now allocates T0 10 / T1 2 / T2 8, and
  the full mock matrix confirms the tiers were *executed* and not merely
  named: across arm E's 60 episodes the eight branched cases show
  `workers` and `select` in every one of their three repeats — 24
  episodes on the orchestrator-workers graph — and the other twelve
  cases show neither node in any repeat. The listwise selector and the
  marginal-stop record now have a benchmark that reaches them.
- **Positive: the record says why.** Every branched episode carries a
  `branch_*` reason code in `compute.tier_selected`, so "which rule
  bought this branch" is answerable per episode rather than per suite.
  The per-query table is pinned in
  `tests/test_listwise_selection.py::SUITE_ROUTING` with its reasons, so
  a later table change shows up as a named query moving for a named
  reason instead of as a distribution that shifted.
- **Negative: 40% of the suite now pays for branching.** That is real
  money in a funded run — eight cases × three repeats × N branches — and
  it is the honest consequence of a suite that is, by its own docstring,
  "broad survey questions, tradeoff questions, comparison questions".
  `docs/agent-engineering/16-w12-approval-packet-draft.md` carries the
  before/after distribution so the owner prices what they are approving.
- **Negative: T1 thins to two cases.** Six of the eight queries that
  branch were T1 before, so the middle tier's sample on this suite is now
  `quantization-inference` and `reasoning-fine-tuning` and nothing else.
  A T0-vs-T1 contrast drawn from arm E alone on this suite would rest on
  two cases; arm C is the arm that answers that question with twenty.
- **Negative: the cue tables are English and hand-written.** Both new
  features are closed vocabularies over normalised text, with every
  weakness `COMPARATIVE_CUES` already had: no morphology, no synonyms, no
  other language. They are constants for ADR 0085's reason — an operator
  who could edit them could edit what an experiment measured — and
  widening one is an ADR and a re-baseline, as this one was.
- **`feature_snapshot_ref` moves for every controller-on deployment.**
  `ComputeFeatures` gained two fields, so the digest over the snapshot
  changes. That is correct — the decision now reads two more inputs and a
  ref that did not move would claim otherwise — but it means arm-E
  trajectories from before this ADR cannot be joined to later ones on
  that ref. Nothing pinned a literal digest.
- **Defaults did not move.** `compute_controller` and `orchestration`
  both default off; `TIER_RULES`, `REASON_CODES`, `COMPUTE_TIERS`,
  `TIER_LIMITS`, `BRANCH_TIER_LIMITS`, `MAX_DECIDABLE_TIER` and every
  threshold constant are unchanged; `ARM_SETTINGS["E"]` is unchanged, so
  no arm's policy digest moves; the golden request fixture and the
  scripted research tier (20/20, `$0.0000`) are unchanged; and
  `_rules_for(MAX_DECIDABLE_TIER) == TIER_RULES` still holds, so a
  flag-off deployment evaluates the table CAP-04 baselined and can emit
  none of the new reason codes.
- **Known gap — one benchmark, twenty queries, one author.** The rules
  are attributed to `research-policy-v1` and to nothing else. Both are
  falsifiable claims about retrieval that this suite does not test
  directly: it scores reports, not per-branch corpus overlap. Measuring
  the branches' actual novelty against the T1 corpus needs the funded
  run, and is the first thing that run should be asked.
- **Known gap — the campaign trajectory still carries no tier decision.**
  Unchanged from ADR 0091: `GraphEpisodeRunner` selects the tier graph
  but has no bridge to record `compute.tier_selected` on, so the routing
  above is inferable from the node route rather than read off the event.
  That is how the matrix test asserts it.

## Alternatives considered

- **Lower `BRANCH_ENTITY_THRESHOLD` to 2.** Rejected twice over: ADR 0091
  rejected it on ADR 0070's grounds, and the measurement above shows it
  would have changed nothing — zero queries carry a comparison word
  beside two recognised entities.
- **Teach `_is_entity_token` to recognise multiword lowercase system
  names.** Attractive, because it is the actual measurement defect, and
  rejected: it needs either a gazetteer (which is data an operator
  curates, so it is a threshold by another name) or a model call (which
  ends the controller's determinism). Detecting the *connective* needs
  neither and answers the question the rule actually asks.
- **Make T2 the top of an ordering: two or more T1 escalations branch.**
  Rejected on the evidence — no query on the suite trips two — and on
  principle: `comparative_cue` and `freshness_cue` are independent
  difficulty signals, and their conjunction is not a claim about needing
  several corpora.
- **Fire rule 11 on any plural noun after `what`.** Rejected: it makes
  `entity_count`'s old mistake in a new place, firing on "What models…"
  and "What systems…" where the plural names the object of study rather
  than a set of alternatives. The solution/observation split is the whole
  content of the rule.
- **Feed the plan counts back and make rule 12 reachable.** Rejected as
  structurally impossible in the current design: the tier selects the
  graph, so it is decided before the planner runs. A caller that planned
  first and then chose a tier would be a different architecture, and it
  would also have to explain what the plan it discarded cost.
- **Add "survey", "landscape", "state of the art" as breadth vocabulary.**
  Rejected: they fire on none of the twenty, so nothing here can
  attribute a result to them, and "state of the art" is already a
  freshness cue.
- **Change `ARM_SETTINGS["E"]` so more episodes branch.** Rejected for
  ADR 0091's reason, unchanged: pinning the shape is the opposite of a
  router, and arm E's identity is the router.
- **Leave the table alone and record that arm E cannot be evaluated on
  this benchmark.** This was the stated valid outcome for this work
  order, and the evidence table is what decided against it: two of the
  twenty queries are textbook two-system comparisons and six are open
  enumerations over a solution class, so the suite does contain the
  shapes T2 exists for. The router could not see them, which is a defect
  in the router rather than in the benchmark.
