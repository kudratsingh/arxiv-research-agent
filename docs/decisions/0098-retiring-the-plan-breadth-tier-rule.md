# 0098. Retiring `plan_breadth`, the last rule that read a plan it could not see

- **Status**: accepted
- **Date**: 2026-09-17
- **Deciders**: agent-capability lane (CAP-19), owner ruling R11
- **Amends**: [ADR 0085](0085-deterministic-compute-controller.md) (its
  rule table and its `REASON_CODES`),
  [ADR 0094](0094-retiring-the-unreachable-plan-breadth-branch-rule.md)
  (which measured this defect, named it, and deliberately left the rule)
- **Follows**: [ADR 0070](0070-eval-integrity-provenance.md) (a threshold
  an operator can move is one no evaluation can attribute a result to)

## Context

ADR 0094 retired `branch_plan_breadth` from the branch table and closed
with a residual it wrote in bold: **rule 7 `plan_breadth` (T1) has the
identical defect** and was not retired, because it is a member of
`TIER_RULES` and therefore of `REASON_CODES` — "the vocabulary a
*flag-off* deployment emits, and a surface ADR 0085 published for CAP-03
and W05 to rely on". Its stated reason for leaving it was blast radius,
not doubt: "a published-surface change bundled into a cleanup is a
change nobody reviews as one."

Owner ruling R11 asked for that review. This ADR is it. The conclusion
is the same as ADR 0094's, the measurement is stronger, and the
published-surface question — the one thing ADR 0094 did not answer —
turns out to have a short answer that nobody had gone and checked.

## The evidence

Computed offline from the shipped rule table and the twenty
`research-policy-v1` objectives: no model, no plan, no clock, no spend.
The counterfactual feeds `extract_features` the counts that no caller
passes, which is exactly the situation a reachable rule 7 would create.

### 1. It has never fired

Both call sites — `src/api/runner.py::_compute_decision` and
`src/campaign/execute.py::_tier_app` — call `extract_features` with the
query alone, so `sub_question_count` and `search_query_count` are always
`None` and `_plan_breadth` returns `False`. **0 of the 20** rows in
`tests/test_listwise_selection.py::SUITE_ROUTING` carries `plan_breadth`
as a reason, and none ever has.

As ADR 0087 established and ADR 0094 repeated, that is a consequence
rather than an oversight: the tier selects the *graph*, so it is decided
before the planner runs.

### 2. It cannot discriminate, at any threshold

| count | rule fires on | tier changes, flag-off | tier changes, `orchestration=on` |
|---|---|---|---|
| `sub_question_count` 1–3 | 0/20 | 0/20 | 0/20 |
| `sub_question_count` 4–10 | **20/20** | 12/20 | 10/20 |
| `search_query_count` 1–5 | 0/20 | 0/20 | 0/20 |
| `search_query_count` 6–10 | **20/20** | 12/20 | 10/20 |

A pure step function, on both axes, under both ceilings. There is no
value of either threshold at which the rule partitions this suite,
because its input is a property of **the planner** rather than of the
query: the planner is handed one instruction and produces a plan of
roughly one size whatever it is asked about. ADR 0094 found this for
`sub_question_count >= 5`; it holds for `>= 4`, for the query count, and
for every other value.

For contrast, on the same twenty queries the rules that read the query
partition it:

| rule | fires on |
|---|---|
| `comparative_cue` | 3/20 |
| `freshness_cue` | 3/20 |
| `multi_entity` | 2/20 |
| `branch_open_enumeration` | 6/20 |
| `branch_paired_comparison` | 2/20 |
| `default_t0` | 10/20 |

### 3. Its threshold sits *inside* the planner's range, which is worse

This is where rule 7 is not merely as bad as the branch rule ADR 0094
retired but worse, and it is the fact that inverts ADR 0085's original
justification.

ADR 0085 sized the thresholds "against the planner's own instruction: it
is asked for `2-4 focused sub-questions` and `1-2 targeted queries`
each, so four sub-questions is the top of its range and six queries is
the upper half of the 2-8 that range implies." ADR 0094 could argue that
`branch_plan_breadth`'s 5 was *past* the planner's range and therefore
unreachable without a prompt change — an instrument change ADR 0070
forbids as a fix for a router.

Rule 7's 4 is not past the range. It is the top of it. So a planner that
*complies with its instruction* produces four sub-questions on the modal
query, and the rule escalates nearly everything it sees. Under the
default ceiling that is **12/20 — the entire T0 population**, which is
the control arm. A rule that escalates the control arm is not a
difficulty signal; it is a global switch wearing a rule's clothes, which
is the shape ADR 0091 and ADR 0087 both refused when it was spelled
`BRANCH_ENTITY_THRESHOLD`.

The rule therefore fails in both directions at once: unreachable as
shipped, and uninformative if it were ever reached.

### 4. The tier it escalates to answers a different question

T1 is arm C's `research_fixed_verify_repair` graph: it verifies the
claims a plan produced and repairs at most one. It does not widen the
plan, add a branch, or retrieve a second corpus. Escalating a *breadth*
signal into a *verification* budget is not incoherent — more
sub-questions do mean more claims to check — but it is not the thing the
rule's own table entry claims to buy ("plan-time breadth, for callers
that decide after planning"). This is a weaker objection than ADR 0094's
§2, where the branch tier would structurally drop the fifth sub-question
that fired the rule, and it is recorded at its real weight rather than
inflated to match.

### 5. What is *not* wrong with rule 6, and why the distinction matters

`long_query` also fires **0/20** on this suite: `research-policy-v1`'s
objectives run 8–14 whitespace tokens and the threshold is 24. ADR 0087
already recorded that zero.

It is a different zero, and keeping the two apart is the point of this
section. `long_query` is reachable — `POST /research` accepts a query of
any length — and it discriminates: given a 24-token query it separates
that query from a short one. Its zero is a gap in *the suite's* coverage
of the rule. `plan_breadth`'s zero is a property of the rule: no caller
could reach it, and any caller that did would get 20/20.

"Fires zero times on the benchmark" is therefore not the criterion for
retirement and is not used as one here. The criterion is that the rule
cannot be reached by a shipped caller *and* cannot carry information
about the query if it were. Rule 7 is the only rule in either table that
meets it.

## Decision

**Retire the rule.** `plan_breadth` is removed from `TIER_RULES`, along
with its predicate `_plan_breadth` and both thresholds,
`PLAN_SUB_QUESTION_THRESHOLD` and `PLAN_SEARCH_QUERY_THRESHOLD`.
`REASON_CODES` goes from eight members to seven.

The thresholds go with the rule rather than being kept for a future
caller, for the reason ADR 0094 gave when it deleted
`BRANCH_SUB_QUESTION_THRESHOLD`: a constant no predicate reads is a
claim nothing can falsify.

The surviving rows keep the numbers ADR 0085 issued — the table now
reads 1, 2, 3, 4, 5, 6, 8 — because ADR 0086, ADR 0087 and ADR 0094 all
cite rules by number, and renumbering would silently falsify three
records to save one integer. The module docstring says "there is no rule
7" in the same place and for the same reason it says "there is no rule
12".

### The published-surface question ADR 0094 deferred

ADR 0094 left the rule because `REASON_CODES` is published, and a
published surface deserves its own decision. Having now made that
decision, the honest report is that the surface is narrower than either
ADR assumed, and no one had checked.

`REASON_CODES` is a **module** surface, not a sealed contract one. The
three places a reason vocabulary could have been sealed were each
checked, and none of them enumerates it:

- **The trajectory event schema.** `compute.tier_selected`'s payload is
  closed to five registered fields and carries the fired codes in
  `reason_codes` as a plain list of strings. The field that *is*
  validated against a closed set — `ProposedTrajectoryEvent.reason_codes`
  on the envelope, checked against `REGISTERED_REASON_CODES` — is left
  empty by `RuntimeTrajectoryBridge.compute_tier_selected`, and
  `REGISTERED_REASON_CODES` is `ERROR_CODES` plus trajectory *outcomes*,
  which is disjoint from the compute rule ids and always has been. No
  compute rule id has ever been checked against a closed vocabulary.
- **The run manifest.** `PolicyExecutionSnapshot.decision_rule_ids` is
  typed `tuple[PolicyMember, ...]` — a label *pattern*, not an
  enumeration — and records the reasons a decision produced, never the
  vocabulary it could produce. This rule has never produced one.
  `PolicySnapshot`'s `PolicyConfig` carries the router's *version*, not
  its reason codes.
- **The contract registry.** No registry object names any compute reason
  code. `python -m src.contracts.registry parity` reports **257 objects,
  0 mismatches**, unchanged.

So RFC 09 §7 and RFC 10 §8.6's additive/deprecation discipline has
nothing to deprecate: there is no sealed enumeration to version, no
fixture or golden that names the code, and no stored trajectory that can
carry it, because it never fired. The removal is a source-level change
to a tuple that only this repository's own tests read. Both tests that
read it now pin the vocabulary as a literal tuple, so the next move —
in either direction — is a reviewed diff rather than a number that
changed for an unstated reason.

### `DIFFICULTY_FEATURES_VERSION` is deliberately **not** bumped

`src/contracts/research_binding.py` says it is "bumped when either
rule's behaviour moves", and it rides on arm E's `PolicyConfig` and
therefore on arm E's policy digest. The argument for bumping it is that
a rule left the table. The argument against, which wins:

The router's behaviour has not moved on any input a caller can produce.
Both counts are `None` on every shipped path and `_plan_breadth` was
`False` on `None`, so `decide_tier(extract_features(q))` returns the
same tier, the same reasons and the same eligible set for every query,
at both ceilings, before and after this change — verified over the whole
suite. The behaviour differs only on hypothetical inputs that no caller
constructs.

Bumping would move arm E's `GOLDEN_ARM_POLICY_DIGESTS` entry and split
arm-E analysis into before and after, buying a version boundary that
separates two identical routers. That is the same trade ADR 0094 refused
for the feature fields, refused again here for the same reason: a
re-baseline is a real cost to attribution, and it should be paid for a
real behaviour change. ADR 0094 set this precedent silently by retiring
a rule without bumping; this ADR states it, so the next retirement does
not have to re-derive it.

## What did not move

- **No `feature_snapshot_ref` moved.** The digest is a `sha256:` over
  `ComputeFeatures.as_dict()`, and no field changed:
  `sub_question_count` and `search_query_count` are deliberately **kept**
  as fields, now read by no rule in either table.
- **No arm's policy digest moved.** `ARM_SETTINGS` is untouched,
  `DIFFICULTY_FEATURES_VERSION` stays `1.0.0`, and
  `GOLDEN_ARM_POLICY_DIGESTS` is unchanged for arms A–D **and E**. Arm
  E's config carries the router's version, not its vocabulary, which is
  why the one published surface that moved reaches no digest.
- **The pinned per-query routing is byte-identical.**
  `tests/test_listwise_selection.py::SUITE_ROUTING` is unchanged, tier
  for tier and reason for reason: **T0 10 / T1 2 / T2 8**. The retired
  rule contributed no reason to any of the twenty rows, which is the
  whole case against it.
- **`COMPUTE_TIERS`, `TIER_LIMITS`, `BRANCH_TIER_LIMITS`,
  `BRANCH_REASON_CODES`, `MAX_DECIDABLE_TIER` and every surviving
  threshold are unchanged**, so `src/config.py`'s validation of
  `tier_effort_overrides` accepts exactly what it did.
- **Defaults, goldens and the scripted tier are byte-identical.**
  `compute_controller` and `orchestration` both still default off, so
  the compiled graph set, the golden request fixture and the scripted
  research tier (20/20, `$0.0000`) are what they were.
- **Registry parity is unchanged**: 257 objects, 0 mismatches.

## Consequences

- Every rule in both tables now decides from the query alone. That is
  asserted as a property rather than as the absence of two ids, in
  `tests/test_compute_policy.py::test_no_rule_in_the_default_table_reads_a_plan_time_count`
  and
  `tests/test_orchestration_controller.py::test_no_rule_in_either_table_reads_a_plan_time_count`,
  both of which sweep the counts rather than sampling one value —
  because the defect being guarded against is precisely one that a
  single-value check would have missed.
- A consumer that enumerated `REASON_CODES` sees seven members rather
  than eight. Nothing outside this repository's tests does, and no
  recorded decision has ever carried the retired code, so no stored
  trajectory becomes unreadable.
- The plan-time counts are now fields that **no rule reads at all**.
  ADR 0094 flagged the day this would arrive and asked that "the fields
  and the digest break should be decided together and once". They are,
  here: the fields stay. Their justification was never the rule — ADR
  0094 said so explicitly — it was the digest, and the digest is
  unaffected by which rules exist. They would go in a change that is
  already paying for a `feature_snapshot_ref` re-baseline for some other
  reason; a deletion is not a reason to start paying.
- ADR 0094's "known residual" and its "known gap, unchanged" are both
  closed.

## Alternatives considered

- **Keep it, and document it harder.** ADR 0087 did this to
  `branch_plan_breadth` and ADR 0094 had to re-measure the rule from
  scratch to understand it; ADR 0094 then did a milder version of the
  same thing to rule 7, and this ADR re-measured it from scratch. Twice
  is the pattern, not the accident.
- **Make it reachable with a post-plan re-route.** Rejected for the
  three reasons ADR 0094 gives at length and does not need repeating:
  it inverts the trajectory's ordering guarantee, W05's binding reads
  the policy id off the compiled shape, and it would buy a rule that
  §2 says still carries no signal. None of those arguments depends on
  which table the rule sat in.
- **Lower or raise the threshold so real plans discriminate.** Rejected
  on the measurement rather than on principle: §2 says the outcome is
  0/20 or 20/20 at *every* value on *both* axes, so no threshold exists
  that would make the rule discriminate. ADR 0070 would forbid moving it
  even if one did.
- **Keep the rule and delete the two feature fields instead.** The
  inverse trade, and the wrong one in both halves: it would move
  `feature_snapshot_ref` on every controller-on deployment (a real cost
  to arm-E analysis) while leaving in place the thing that actually
  misinforms — a table row claiming a signal it does not carry.
- **Retire `long_query` too, since it also fires 0/20.** Rejected, and
  §5 is the argument: its zero is a property of this suite's short
  objectives, not of the rule, and the rule is reachable and
  discriminating for any caller who submits a long query. Retiring on
  "fired zero times on the benchmark" would make the benchmark's
  coverage gaps into deletions of working code.
- **Renumber the table 1–7.** Rejected: three ADRs cite these rules by
  number.

## What is not verified without a live call

Nothing here is a quality claim. This ADR removes a rule rather than
adding one, and the removal is provably behaviour-preserving on every
input a caller can construct, so it makes the router's behaviour no less
verified than ADR 0094 left it. Specifically still unestablished,
unchanged from ADR 0087 and ADR 0094: whether the surviving escalations
correlate with difficulty at all, and whether the branches of a branched
run return evidence a single ranked corpus would have missed. CAP-06 is
where those become answerable.

One thing this ADR does newly expose, recorded rather than fixed because
the fix is a caller and not a deletion. Four of the controller's ten
features are set by no shipped path, and after this change they fall
into two distinct kinds:

- `requested_depth` is **read** — decisively, by rules 1 and 2 — and
  merely never set, because `POST /research` carries no depth field. A
  surface that grew one would light it up unchanged.
- `task_kind` and the two plan counts are read by **no rule at all**.
  `task_kind` has been in that state since ADR 0085; the counts joined
  it here.

The second kind is the one worth watching, and the reason this ADR does
not act on it is that both remaining members are load-bearing for the
digest rather than for a decision — an honest reason, and still not a
functional one.
