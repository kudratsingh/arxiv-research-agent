# 0086. Orchestrator-workers for the branch tier (T2)

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: agent-capability lane (CAP-03)

## Context

`docs/agent-engineering/01-current-architecture.md` §6 records parallel
candidate search as **absent**. That is precise rather than harsh: the
reader already fans out across papers, but every paper it reads was
retrieved by one search, ranked against one query, for one trajectory.
Widening the corpus and widening the *enquiry* are different things, and
only the first exists today.

`02-target-architecture.md` §4 asks tier T2 for the second: "diverse
search branches or candidate outlines, listwise selection, verification"
for questions that are ambiguous or evidence-sparse. §4's compute-actions
list is more specific still — "generate alternative search plans, not
paraphrases of one plan" and "diversify retrieval by source, query
strategy, date window, and citation graph direction".

Three things landed before this work order and each decided part of the
shape:

- ADR 0076 built the fixed verify-and-repair stage and the `verify` /
  `repair` nodes, with the one-repair cap enforced in
  `route_after_verification`.
- ADR 0085 built the deterministic compute controller with T0 and T1,
  and left `MAX_DECIDABLE_TIER` as an explicit ceiling: "T2 needs a
  branch executor that does not exist until CAP-03".
- ADR 0083 built the runtime bridge, whose event registry has carried
  RFC 10 §6.3's `branch.*` and §6.4's `candidate.*` vocabulary since W05
  with nothing in this repository able to emit any of it.

`07-first-policy-experiment.md` §3 arm E is the destination: adaptive
compute *with* listwise selection and a marginal-stop rule. This work
order deliberately builds the first half of it, and the decision below
is as much about what it refuses to claim as about what it adds.

## Decision

Add a fourth graph shape, `research_policy="orchestrated_workers"`,
default-off, and make it selectable per run as compute tier T2 when
`orchestration="on"` and the controller is on.

```text
planner -> lead -> workers -> merge -> synthesizer -> verify
verify  -> repair   (verdict fail, no repair spent, one available)
verify  -> critic   (pass | abstain | the repair is spent)
repair  -> lead | synthesizer | critic
critic  -> route_after_critique, with `search` remapped to `lead`
```

**Three new nodes, no new agent.** `lead` bounds the planner's
sub-questions into at most `orchestration_max_branches` worker branches
in the plan's own order; `workers` runs each one; `merge` unions their
evidence tables. None of the three calls a model. The planner has
already decomposed the question, and a second model re-decomposing it
would spend a call to make the branch set non-deterministic.

**A branch is one sub-question on an isolated state.** `branch_input_state`
builds a complete fresh `ResearchState` from the canonical constructor
and the branch runs `search_agent` then `reader_agent` on it. The
branch's `query` **is** its sub-question, which is where the diversity
comes from: `search_agent` ranks the candidate pool against `query`, so
N branches retrieve N differently ranked corpora where N copies of one
query would retrieve the same corpus N times and call it a branch set.
Branch messages are dropped, so the run's message trajectory still
records nodes rather than a fan-out.

**Branches run one after another** on the node's own executor thread,
which ADR 0047 already bounds against `api_max_concurrent_jobs`.
Determinism decides it: the merge order has to be a function of the plan
and a thread pool would make it a function of scheduling. Cost seconds
it: the run ceiling is enforced against one accumulator at the shared
`call_llm` choke point, and N branches racing through that check is
exactly the stale read RFC 10 §8.7 describes. The parallelism T2 asks
for is in the retrieval, not in the wall clock.

**The merge is deterministic and incremental.** Papers are deduplicated
on `canonical_paper_key` (ADR 0041's key), claims on
(paper, section, claim text), and one `EvidenceProvenance` row per
retained paper names every branch that found it and the sub-question
that branch was researching. It is *incremental* because the graph can
re-enter the tier: the retrieval repair adds a branch per named gap and
the merge unions it with what the run already had. A merge that started
empty would let a repair delete the evidence the report was built on —
"reflect again is not a recovery policy" (`02-target-architecture.md`
§5) applies to deleting evidence too.

**The compute controller gains T2 as a second table.** `TIER_RULES`,
`COMPUTE_TIERS`, `TIER_LIMITS` and `REASON_CODES` are untouched; the
branch tier's two rules, limits and reason codes live in `BRANCH_*`
constants and are appended only when `decide_tier` is given a raised
`max_tier`. "Off is unchanged" is then true by construction rather than
by inspection. `src/api/runner.py` raises the ceiling exactly when
`settings.orchestration` is `on`, and `src/graph/workflow.py` compiles
the T2 graph on the same condition, so the controller can never name a
tier the process has no graph for.

**Caps.** Three, each enforced where it cannot be skipped:

| Cap | Setting | Default | Enforced by |
|---|---|---|---|
| branches per run | `orchestration_max_branches` | 4 | `plan_branches` slices the sub-question list |
| papers per branch | `orchestration_max_papers_per_branch` | 4 | sliced between search and reader — which makes it the branch's *model-call* cap too, since the reader spends one call per paper |
| dollars per branch | `orchestration_branch_cost_share` | 0.4 | `bind_effective_cost_cap` at the shared choke point |

The cost share is a containment device rather than an allocation: the
shares deliberately over-subscribe the run ceiling, because the ceiling
is the real bound and shares summing to 1.0 would starve later branches
whenever an early one finished cheap. A branch that trips its share is
recorded `budget_stopped` and its siblings still run; a run that trips
the ceiling raises the same `CostBudgetExceeded` ADR 0051 already
handles, producing the existing partial report.

**Failure is per branch; cancellation is not.** A branch that raises is
recorded `failed` with the typed code from `src/errors.py` and the next
branch runs. A cancelled job stops there and the exception propagates —
containing it would turn "abort" into "run the remaining branches
anyway", which is the accounting lie ADR 0047 exists to close. A run
where *no* branch succeeded raises the first branch's own exception, so
the job's `error_type` is exactly what a single-trajectory run would
have carried (`not_found_papers`, `upstream_arxiv`,
`upstream_paper_read`) rather than an empty evidence table and a fluent,
sourceless briefing (ADR 0041).

**Lineage, and no selector.** Every branch reaches the trajectory as RFC
10 §6.3's `branch.created` / `branch.completed` / `branch.failed` /
`branch.cancelled`, and every succeeded branch's evidence table as a
§6.4 sibling `candidate.created` whose id is derived from a
content-addressed *index* of its claims — claim, paper, section,
sub-question, and not the source chunks, which are already in the report
artifact. `ResearchRuntimeBridge.record_branch` is driven from the graph
state through `observe_node`, because ADR 0078 keeps contract modules off
a flag-off deployment's import graph and the branch record already
travels out on the node update the runner observes.

**What this shape is classified as.** `research_orchestrated_workers`,
with `arm_id=None` and arm E's remaining gap named in
`missing_capabilities`. It earns exactly one arm-E capability —
`candidate_branching` — and the classifier is asked about the
orchestration nodes *first*, because the shape also carries `verify` and
`repair` and a classifier that checked those first would file every
branch run under arm C and make the branching invisible in the record.

## Alternatives considered

- **A thread pool over branches.** Rejected on both grounds above:
  non-deterministic merge order, and N concurrent readers past one
  cost check. RFC 10 §8.7's reservation protocol is the mechanism that
  would make it safe, and nothing implements reservations yet.
- **Route the retrieval repair to a `search` node, as arm C does.**
  Rejected: it would replace the run's papers with one gap's, discarding
  every branch's evidence to keep the repair's. Routing to `lead`
  instead makes the repair *add* a branch, which is also why this graph
  needs no top-level `search` node at all.
- **Two more rows in `TIER_RULES` behind a flag.** Rejected: a merged
  table filtered by tier produces the same decisions right up until
  someone reorders it, and CAP-04's reason tuples are a record an
  evaluation groups by. Two tables make the guarantee structural.
- **Label the shape arm E.** Refused. `run_manifest.py`'s arm-E
  validator wants a supervisor, `marginal_stop` and a selection
  configuration, and this shape honestly has none of them.
- **Label it arm C, since its verification stage is arm C's.** Refused
  for the reason `classify_policy_shape` exists: it would put branch
  runs in arm C's distribution, and an experiment comparing C against a
  control would be comparing C against a mixture.
- **A `lead` that asks a model to decompose the question again.**
  Rejected: a second decomposition costs a call, makes the branch set
  non-deterministic, and puts two disagreeing plans in one run. The
  planner's plan is the plan.
- **Log events for branch outcomes.** Not taken. The log-event registry
  in `src/observability/logging.py` is closed and belongs to another
  lane, and `src/policies/` carries no logger today (neither `repair.py`
  nor `compute.py` does). Branch outcomes are on the state, in the
  node's SSE message, and in the trajectory — a richer record than a
  log line.

## Consequences

- **Positive**: retrieval diversifies along a real axis with provenance
  back to the branch, the sub-question and the paper; a failed branch
  costs a branch instead of a run; the candidate lineage a listwise
  selector needs exists before the selector does; and a flag-off
  deployment compiles the same graphs, evaluates the same rule table and
  records the same eligible tiers it did before.
- **Negative**: the branch tier multiplies the reader, which is the
  expensive node — worst case `max_branches × max_papers_per_branch`
  model calls where the fixed path makes `max_papers`. The branch set
  only grows within a run (a repair or a critic-driven re-plan appends),
  so a long critic loop carries more branch records than it retires.
  And `worker_branches` is a new state key that a checkpoint persists;
  the merge releases each branch's bulk output to keep that bounded.
- **Known gap — the branch shape cannot seal a manifest.**
  `run_manifest.PolicySnapshot.arm_id` is a required `A`-`E`, so a
  non-arm shape has no manifest form and `start_research_job` declines
  the shadow exactly as it declines every other non-arm shape. The
  lineage recorder is complete and exercised, and it activates for any
  run whose episode seals; making a branch run's own episode sealable
  needs a non-arm form in `src/contracts/run_manifest.py`, which is not
  this work order's file. `tests/test_orchestration_controller.py`
  asserts the gap so it closes loudly.
- **Known gap — the cost share does not reach the reader's threads.**
  `bind_effective_cost_cap` binds a ContextVar and
  `propagate_run_context` (`src/observability/logging.py`) carries three
  into the reader's per-paper fan-out, of which the effective cap is not
  one. Inside that fan-out the choke point falls back to
  `settings.max_cost_usd`, so the **run ceiling always holds** and a
  branch can overshoot only its own share, by at most one bounded
  fan-out. Each branch records the spend it actually made. Closing it
  means adding the cap to `propagate_run_context`, in a fenced module.
- **Known gap — model calls stay on the main branch.** The branch scope
  is a ContextVar and the reader records from worker threads, so a call
  cannot be stamped with a branch without risking the *wrong* branch.
  Each branch's own call count rides on its record instead: an
  under-claim by choice.
- **Follow-ups**: CAP-09 adds the listwise selector over these
  candidates and the marginal-stop record, which is what closes arm E;
  a second diversity dimension (date window, citation direction) would
  be a second `diversity_dimension` value and its own ADR;
  `tier_effort_overrides` does not accept a `T2.` key, because
  `COMPUTE_TIERS` is deliberately unextended.
