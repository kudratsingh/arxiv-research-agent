# 0094. Retiring `branch_plan_breadth`, the rule that could not fire

- **Status**: accepted
- **Date**: 2026-09-17
- **Deciders**: agent-capability lane (CAP-18)
- **Amends**: [ADR 0085](0085-deterministic-compute-controller.md) (the
  plan-time seam it left open),
  [ADR 0087](0087-branch-tier-reachability-on-the-benchmark.md) (which
  kept the rule unreachable on purpose)
- **Follows**: [ADR 0070](0070-eval-integrity-provenance.md) (a threshold
  an operator can move is one no evaluation can attribute a result to)

## Context

ADR 0085 shipped the deterministic compute controller with three feature
fields that are `None` on every path this repository ships, and said so
in the ADR itself. Two of them — `sub_question_count` and
`search_query_count` — were described as "the seam CAP-03 needs: a T2
decision is taken *after* planning and reads them, so the rule exists
now and fires only when the counts are known".

ADR 0086 built the branch tier and added `branch_plan_breadth`
(`sub_question_count >= 5` ⇒ T2) against that seam. ADR 0087 then
measured the twenty-query `research-policy-v1` suite, found the rule
firing zero times, named the cause — "the tier selects the *graph*, so
it is decided before the planner runs" — and **kept the rule anyway**,
"for the reason ADR 0085 carried the plan-time fields at all: the rule
has to exist before the caller that decides after planning does". It
also rejected building that caller, as "structurally impossible in the
current design".

So the rule has now been carried, unreachable, through three work
orders, each time on the promise of a caller that has not arrived. This
work order was asked to settle it: retire the rule, or make it
reachable. It retires it, and the reason is not the one the previous two
ADRs recorded.

## The evidence

Everything below is computed offline from the shipped rule table and the
twenty `research-policy-v1` objectives — no model, no plan, no clock.
The counterfactual feeds `extract_features` a `sub_question_count` that
no caller actually passes, which is precisely the situation a reachable
rule 12 would create.

### 1. It does not discriminate, at any plan size

| `sub_question_count` | rule fires on | tier changes vs. query-only |
|---|---|---|
| 1 | 0/20 | 0/20 |
| 2 | 0/20 | 0/20 |
| 3 | 0/20 | 0/20 |
| 4 | 0/20 | 10/20 (rule 7, not this one) |
| 5 | **20/20** | 12/20 |
| 6 | **20/20** | 12/20 |
| 7 | **20/20** | 12/20 |
| 8 | **20/20** | 12/20 |

This is the finding that decided the work order, and neither ADR 0085
nor ADR 0087 looked for it. `sub_question_count` is a property of **the
planner**, not of the query: the planner is handed one instruction and
produces a plan of roughly one size whatever it is asked about. A rule
keyed on it therefore fires on every query or on none — it can only ever
partition a suite 0/20 or 20/20.

That is not a difficulty signal. It is a global switch wearing a rule's
clothes, and a switch that sends *the entire suite* to the branch tier
is the exact shape ADR 0091 and ADR 0087 both refused when it was spelled
`BRANCH_ENTITY_THRESHOLD`. By contrast rules 9-11, which read the query,
partition the same suite **8/20** with a named reason per query.

So the honest statement of the defect is stronger than "no caller passes
the count". Even given the caller, the rule would carry no information
about the question it was asked to route.

### 2. The tier it escalates to cannot serve the breadth that fired it

`orchestration_max_branches` defaults to **4**, and
`src/policies/orchestration.py::plan_branches` slices
`questions[:limit]` — its own setting documents that "a plan with more
sub-questions than this loses the tail". The rule fires at **5**.

A five-sub-question plan escalated to T2 by this rule therefore arrives
at the branch tier and has its fifth sub-question dropped. The rule's
stated purpose is "a plan past the planner's own range is several
questions", and the graph it routes to is structurally unable to serve
the part of the plan that made it several questions. Firing the rule at
its own threshold and honouring it would need a second setting change,
in a different subsystem, that nothing asked for.

### 3. Reaching it at all needs a prompt change, which is frozen

`src/agents/planner.py` instructs "2-4 focused sub-questions", which puts
`>= 5` past the planner's own range; under `USE_MOCK_DATA`, `mock_plan`
returns exactly one (ADR 0041's fallback shape). The only way a real plan
crosses the threshold is a planner that was asked for more.

Prompt text is an instrument (ADR 0070, and this lane's charter §4.5):
changing it re-baselines every metric measured against it. "Widen the
planner's range so a routing rule can fire" inverts the dependency — the
instrument would be changed to suit the router.

### 4. Nothing else reads it

`branch_plan_breadth` appears in no contract, no registry, no manifest
field, no fixture and no golden. `PolicyExecutionSnapshot.decision_rule_ids`
records the reasons a decision *produced*, never the vocabulary it could
produce, and this rule has never produced one. `ALL_REASON_CODES` — the
union a cross-table consumer would group by — has no consumer at all.

## Decision

**Retire the rule.** `branch_plan_breadth` is removed from
`BRANCH_TIER_RULES`, along with its predicate `_branch_plan_breadth` and
its threshold `BRANCH_SUB_QUESTION_THRESHOLD`. `BRANCH_REASON_CODES`
goes from four members to three.

The threshold goes with the rule rather than being kept "for a future
caller", which is the habit that produced this ADR: a constant no
predicate reads is a claim nothing can falsify.

`branch_open_enumeration` (rule 11) already carries the signal this rule
was reaching for. ADR 0087 wrote it as "the pre-plan reading of rule 12's
'a plan past the planner's own range is several questions'", and it
reads that signal where it is actually answerable — off the query,
before the graph is selected — and where it discriminates 8/20 rather
than 20/20. Retiring rule 12 loses no coverage, because rule 11 is the
coverage.

### The alternative: a post-plan re-route

The work order's option (b) was to make the rule reachable — run the
planner on the selected graph, and escalate to the branch tier if the
plan's breadth crosses the threshold, without repeating work already
done. It is worth stating why this is not small, because at first glance
the graphs make it look small: `_build_orchestrated_workers` sets its
entry point to `planner` and its first edge is `planner -> lead`, so a
run that had already planned could in principle enter the branch graph
at `lead` with its plan intact. No planning would be repeated.

Three things stop it, and only the first is mechanical.

- **The record's ordering guarantee inverts.** ADR 0085 made the
  position of `_select_tier_workflow` the deliverable rather than an
  implementation detail: selection happens *before* `_contract_shadow`,
  "so the binding classifies the graph the job will actually run", and
  `compute.tier_selected` is emitted before the first node "so the
  features are in the record before the decision they explain and the
  decision before the compute it authorised". A post-plan escalation
  breaks both halves. The manifest would have been sealed against the
  graph the run *started* on, and the tier event would either have to be
  emitted twice — leaving a consumer to decide which of two
  `compute.tier_selected` events is the tier — or emitted late, after
  compute it did not authorise had already been spent. Neither is a
  change to a rule; both are changes to what a trajectory means.
- **One graph with a conditional edge is already rejected, on the
  record.** ADR 0085's alternatives section rules it out because W05's
  binding reads the policy id off the *compiled shape*: a shape
  containing both `verify` and `lead` classifies as the orchestrated
  policy whether or not the run reached either, so a T0 run's manifest
  would claim arm E. That objection is untouched by anything here.
- **It would buy a rule that still cannot fire.** This is the decisive
  one. Even with the re-route built, §1 says the rule routes the whole
  suite or none of it; §2 says the tier it routes to would discard the
  fifth sub-question; §3 says no real plan reaches five without a prompt
  re-baseline. The engineering would be spent to reach a rule that,
  once reached, carries no signal.

A caller that planned first and then chose a tier is a different
architecture, and — ADR 0087's point, still correct — it would also have
to explain what the plan it discarded cost. If that architecture is ever
built, the rule to add is the one measured against it, not this one
exhumed.

## What did not move

- **No `feature_snapshot_ref` moved.** The digest is taken over
  `ComputeFeatures.as_dict()`, and no field changed:
  `sub_question_count` and `search_query_count` are deliberately **kept**
  as fields. Dropping them would have moved the digest on every
  controller-on deployment and broken the join between arm-E
  trajectories recorded either side of this ADR — the cost ADR 0087 paid
  when it added two fields, and there is no reason to pay it for a
  deletion. Retiring a *rule* moves no digest; retiring a *field* does.
- **`TIER_RULES`, `REASON_CODES`, `COMPUTE_TIERS`, `TIER_LIMITS`,
  `BRANCH_TIER_LIMITS`, `MAX_DECIDABLE_TIER` and every threshold
  constant are unchanged**, so `_rules_for(MAX_DECIDABLE_TIER) ==
  TIER_RULES` still holds and a flag-off deployment evaluates exactly the
  table CAP-04 baselined.
- **The pinned per-query routing is byte-identical.**
  `tests/test_listwise_selection.py::SUITE_ROUTING` is unchanged, tier
  for tier and reason for reason: T0 10 / T1 2 / T2 8. The retired rule
  contributed no reason to any of the twenty rows, which is the whole
  case against it.
- **No arm's policy digest moved.** `ARM_SETTINGS` is untouched and
  `GOLDEN_ARM_POLICY_DIGESTS` for arms A-D is unchanged.
- **Defaults, goldens and the scripted tier are byte-identical.**
  `compute_controller` and `orchestration` both still default off, so
  the compiled graph set, the golden request fixture and the scripted
  research tier (20/20, `$0.0000`) are what they were.

## Consequences

- The branch table now contains only rules that a shipped caller can
  actually reach, so "which rule bought this branch" has three possible
  answers and all three are answerable from the query.
- A consumer that enumerated `BRANCH_REASON_CODES` sees three members
  rather than four. Nothing in this repository does, and no recorded
  decision has ever carried the retired code, so no stored trajectory
  becomes unreadable.
- **Known residual: rule 7 `plan_breadth` (T1) has the identical
  defect** and is deliberately not retired here. It reads the same two
  counts from the same two call sites, and the same measurement says it
  is false for all twenty queries below its threshold and true for all
  twenty at or above it. It is kept because it is a member of
  `TIER_RULES` and therefore of `REASON_CODES` — the vocabulary a
  *flag-off* deployment emits, and a surface ADR 0085 published for
  CAP-03 and W05 to rely on. Removing it is a published-surface change
  and deserves its own decision rather than a ride on this one. It is
  pinned by
  `tests/test_orchestration_controller.py::test_no_branch_rule_reads_a_plan_time_count`,
  which asserts that the counts still move the T1 table, so the day rule
  7 goes that line says so.
- **Known gap, unchanged:** the plan-time counts remain fields nothing
  reads for a decision that can fire. They are retained for the digest's
  sake, which is an honest reason but not a functional one; if rule 7 is
  ever retired too, the fields and the digest break should be decided
  together and once.

## Alternatives considered

- **Keep the rule and document it harder.** This is what ADR 0087 did,
  and the result is that a rule which cannot fire was carried through a
  third work order and had to be re-measured from scratch to be
  understood. Documentation did not stop it costing review attention
  every time the table was read.
- **Build the post-plan re-route.** Covered above: not small, inverts the
  record's ordering guarantee, and arrives at a rule that still carries
  no signal.
- **Lower the threshold from 5 to 3 or 4 so real plans reach it.**
  Rejected on ADR 0070's grounds, as ADR 0091 and ADR 0087 both rejected
  the analogous move on `BRANCH_ENTITY_THRESHOLD` — and on the
  measurement, which says the outcome is 20/20 rather than a useful
  partition at *every* value, so no threshold exists that would make the
  rule discriminate.
- **Retire rule 7 in the same change.** Tempting, since the defect is
  identical and the two rules are one mistake made twice. Rejected for
  blast radius: it changes `REASON_CODES`, which ADR 0085 published and
  ADR 0087 was careful to leave alone, and a published-surface change
  bundled into a cleanup is a change nobody reviews as one. Recorded as
  open above instead.
- **Delete the plan-time fields along with the rule.** Rejected: it
  moves `feature_snapshot_ref` for every controller-on deployment, which
  is a real cost to arm-E analysis, in exchange for tidiness. The fields
  are inert; the digest is not.

## What is not verified without a live call

Nothing here is a quality claim, and this ADR removes a rule rather than
adding one, so it makes the router's behaviour *no* less verified than
ADR 0087 left it. Specifically still unestablished, unchanged from ADR
0087: whether rules 9-11's escalations correlate with difficulty at all,
and whether the branches of a branched run return evidence a single
ranked corpus would have missed. CAP-06 is where those become
answerable.
