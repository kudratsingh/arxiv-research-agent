# 0091. Listwise candidate selection and the marginal-stop record

- **Status**: accepted
- **Date**: 2026-09-06
- **Deciders**: agent-capability lane (CAP-09)
- **Completes**: [ADR 0086](0086-orchestrator-workers-for-the-branch-tier.md)
  (the branch tier, which shipped the first half of arm E and named this
  work order as the second)
- **Follows**: [ADR 0085](0085-deterministic-compute-controller.md) (the
  T0/T1/T2 controller), [ADR 0089](0089-non-arm-policy-snapshots-and-one-registry-root.md)
  (arm E redefined structurally), [ADR 0088](0088-campaign-execution-loop.md)
  (the loop that now runs arm E's sixty episodes)

## Context

Arm E has been `capability_missing` since the first policy experiment was
written, and by 2026-09-05 the refusal had shrunk to exactly two names:

```
Arm E graph lacks marginal_stop, candidate_lineage_selector: the listwise
candidate selector and the marginal-stop record are CAP-09's and nothing
in this repository builds them yet
```

Everything else was in place. CAP-04 built the deterministic compute
controller and made `adaptive_compute_router` earnable from a setting
(ADR 0085, ADR 0089). CAP-03 built the branch tier: N bounded workers,
each researching one sub-question on an isolated state, a deterministic
merge with provenance, and — the part that matters here — a
`candidate.created` event per succeeded branch, content-addressed on that
branch's evidence index, which ADR 0086 wrote down as "the candidate
lineage a listwise selector needs exists before the selector does".

`02-target-architecture.md` §4 asks tier T2 for three things: "diverse
search branches or candidate outlines, listwise selection, verification".
ADR 0086 delivered the first and the third and said so. §4's compute
actions ask for a fourth thing that had no owner at all: "stop when the
expected marginal quality gain is below the next action's cost".

So this work order is two capabilities, and the whole design question for
each is *where the decision lives*, because both have an obvious wrong
place to put them.

## Decision

### A `select` stage between `workers` and `merge`

```text
planner -> lead -> workers -> select -> merge -> synthesizer -> verify -> ...
```

Compiled only when `candidate_selection="listwise"`. With the setting at
its default the orchestrator-workers graph is byte-identical to the one
ADR 0086 published — same nodes, same edges, same digest — which is what
keeps `candidate_lineage_selector` a capability a **node** earns rather
than one a name claims.

**Between the workers and the merge, because that is the only place a
selection can still change anything.** After the merge the branch tables
are unioned and their bulk output released; a selector downstream of it
would be a report about a decision already taken.

**A candidate is a succeeded branch's evidence table**, which is not a
convenience: it is the object `ResearchRuntimeBridge.branch_candidate`
already records as RFC 10 §6.4's sibling `candidate.created`. The thing
this module ranks and the thing the trajectory already names are one
object rather than two that have to be joined afterwards.

**Listwise means one call over the whole list**, and the word is
load-bearing for two reasons that both point the same way. Pairwise over
N candidates is O(N²) calls where this is one, and the branch tier's
whole cost argument is that orchestration adds no model calls of its own
beyond the branches themselves. And pairwise comparisons are not
guaranteed transitive, so the ranking a run recorded could depend on the
comparison order — the same non-determinism ADR 0086 refused a thread
pool over.

**Two selectors, one record.** `listwise_deterministic` ranks by
`(evidence_count desc, analysis_count desc, plan order)` — every term a
number the run already counted, so no model, no clock, no I/O. It runs
under `USE_MOCK_DATA`, where every branch reads the same fixture corpus
and the counts tie, so the ranking *is* fixture order at zero spend; and
it runs whenever the model path fails. `listwise_model` makes one
`call_llm_json` with a pydantic schema, which reaches the provider as
`output_config.format` through `anthropic.transform_schema` when
`enable_structured_outputs` is on and drives validation on the way back
either way. Never free-text parsing.

**A malformed answer degrades; it is never repaired.** A ranking that
names four of five candidates is not a ranking with one omission, it is
evidence that the model did not do the task, and filling the gap in would
put a number in the record that nothing produced. The selector falls back
to the deterministic ranking and logs `candidate_selection_degraded`.

**Selection is a decision with an effect.** `merge_branches` unions only
the selected branches, bounded on both sides: the top-ranked candidate is
always selected (an empty evidence table would let a fluent, sourceless
briefing ship, ADR 0041), `selection_max_candidates` is a ceiling on
breadth rather than a quota, and a rejected branch keeps its record, its
status and its `candidate.created` event — RFC 10 §6.4: "rejection or
non-selection never deletes a candidate". What a selection cannot touch
is the merge's `base`: evidence an earlier pass already merged is what
the report was built on, and a later selection that could retract it
would be the deletion ADR 0086 refused for the repair.

### A marginal stop inside the branch loop

`marginal_stop="on"` makes `run_branches` measure each branch as it
settles and stop before launching the next when the gain falls below
`marginal_stop_threshold`.

**Inside the sequential loop, because that is the only place the rule can
actually prevent spend.** A stop decided after the loop would be a report
about dollars already gone. This is the same argument ADR 0086 makes for
enforcing the branch cost share at the shared `call_llm` choke point
rather than in the node.

**The gain is defined only in quantities the run already tracks**: new
deduplicated papers plus new evidence claims contributed beyond every
succeeded branch before it, over the dollars that branch was allowed to
spend. Both dedup keys are the merge's own — ADR 0041's
`canonical_paper_key` for papers, (paper, section, claim) for claims —
because "new" has to mean the same thing to the stop rule as it does to
the merge, or the rule stops on gains the report never receives.

**The denominator is the branch's cost *share*, not its measured spend.**
Two reasons, and the second is the one that matters. Actual spend is zero
under `USE_MOCK_DATA` and would make every gain infinite; and the share
is what the *next* branch will cost, which is the quantity a stop
decision is actually about — "was the last branch worth what the next one
will cost". Using the measured spend would compare a gain against a bill
already paid.

**A failed, cancelled or budget-stopped branch never triggers a stop.**
Its gain is zero for reasons that have nothing to do with whether more
retrieval would help, and stopping on it would turn one upstream fault
into a shortened run.

**Branches that were never launched are recorded, not dropped**, with a
new `stopped` status and the reason code
`marginal_gain_below_threshold`. RFC 10 §6.3's closure does not delete a
branch, and a run whose record simply ended would be indistinguishable
from one that planned fewer. The bridge settles them as
`branch.cancelled` with that reason — nothing *failed*, and
`branch.failed` takes a `failure_class`.

**The record exists whether or not the rule fired.** "Measured, and the
gain held" and "never measured" are different facts about a run, and only
a record that exists in both cases distinguishes them.

### Both records reach the trajectory the way the branches do

Neither `src/graph/` nor `src/policies/` may import a contract module
(ADR 0078 keeps them off a flag-off deployment's import graph), so both
records travel out on the node's state update and are read by
`observe_node` — the route ADR 0086 already built for branches.
`observe_selection` is a no-op on the four paths `observe_branches` is a
no-op on, and the common one is that no other shape carries either key at
all, so a flag-off run pays two `.get` calls.

The events are RFC 10 §8.6's, unchanged and already in W04's registry:
`candidate.scored` per eligible candidate with its score artifact, one
`candidate.selected` naming the eligible set and the chosen id, and
`compute.stop_decided` with the considered action, the gain method, the
gain and the incremental cost. **No new event type was needed**, which is
the strongest evidence the RFC's vocabulary was designed for this.

The selection record names *branches*; the trajectory names *candidates*.
A candidate id is the digest of an artifact this bridge stored and a
graph node cannot derive one, so `_branch_candidates` joins the two
vocabularies in the one place that mints both. `candidate.selected`'s
`selected_candidate_id` is the top-ranked candidate — the shape RFC 10
§8.6 defines — and the full subset is in the selection artifact the
payload already points at, because widening the event would be a change
to W04's registry for something the artifact already carries.

### Arm E's row becomes the real configuration

`ARM_SETTINGS["E"]` was a copy of arm D's, kept as a placeholder that
documented that the closest expressible configuration was still not arm
E. It is now:

```python
"E": {
    "enable_supervisor": False,
    "enable_evidence_store": True,
    "enable_verifier": False,
    "research_policy": "legacy",
    "compute_controller": "deterministic",
    "orchestration": "on",
    "candidate_selection": "listwise",
    "marginal_stop": "on",
}
```

Two entries will surprise a reader and both are forced.

`research_policy` is **`legacy`, not `orchestrated_workers`**. ADR 0085
refuses a compute controller beside a policy that fixes the shape for the
whole process — two claimants for the graph is one too many — and
`src/config.py` enforces it at load. Arm E's identity *is* the router
(ADR 0089), so the router is what the row turns on, and the branch tier
reaches the arm as the controller's T2 rather than as a pinned shape.
`enable_supervisor` is **false** because ADR 0089 removed the supervisor
from arm E's definition.

`UNRUNNABLE_ARMS` is now empty. It is kept rather than deleted: it is the
mechanism by which a *future* arm can be declared before it is built, and
a campaign denominator needs to account for such an arm's episodes as
excluded-with-reason rather than have them vanish.

### `read_deployment_shape`, because a controller run is a set of graphs

`arm_graph_probe` used to read the *primary* compiled graph. For a
controller deployment that answers about whichever shape happens to be
primary, and arm E's primary is the T0 fixed pipeline — a probe that read
only it would report a capability set no run of that deployment is
bounded by.

`read_deployment_shape` unions the primary with the controller's attached
per-tier graphs. For every deployment with the controller off there are
no attached graphs and it returns the primary unchanged, so arms A-D's
declarations, classifications and digests are byte-for-byte where they
were. RFC 09 §7.2 draws the same line this does: arm E's allowed tiers,
router and hard bounds are *manifest inputs*, while the tier actually
selected is a runtime fact.

`GraphEpisodeRunner` selects the tier graph per episode for the same
reason — a campaign that sealed an arm-E manifest and then ran whichever
graph was primary would be recording a policy the episode did not
execute. It mirrors `src/api/runner.py::_select_tier_workflow` and is a
string comparison for every other arm.

## Consequences

- **Positive.** Arm E is runnable: `UNRUNNABLE_ARMS` is empty, the
  W07b full matrix reconciles **300 completed / 0 excluded** at
  `$0.000000` with zero model calls, and the dry-run lock's 300/240/60
  becomes 300/300/0. The candidate lineage ADR 0086 built now has a
  consumer, so a selector oracle gap is measurable from the trajectory
  alone. Every arm-E capability is earned structurally or by a setting
  the settings validator refuses on a deployment that cannot exercise it.
- **Defaults did not move.** `candidate_selection` and `marginal_stop`
  both default off; the compiled graphs, the golden request fixture, the
  A-D policy digests and the scripted research tier (20/20, `$0.0000`)
  are unchanged. Arm E's golden digest is a new row rather than a moved
  one, which is the check that pinning it exists for.
- **Negative: a rejection has a cost.** A branch the selector rejects
  spent its model calls and contributes no evidence. That is the point of
  a selector and it is also a real waste, and it is why
  `selection_max_candidates` defaults to `orchestration_max_branches`'
  own default: the shipped behaviour is "select nothing out" until an
  operator narrows it deliberately.
- **Negative: the marginal stop can end a run early on a corpus that
  repeats itself.** Under `USE_MOCK_DATA` every branch reads the same
  five fixture papers, so a second branch's marginal gain is exactly
  zero and the rule fires immediately. That is correct behaviour on a
  degenerate corpus and it means the mock lane exercises the *stop*
  rather than the multi-branch merge whenever both are on.
- **Known gap — the router declines T2 on the shipped suite.** Over
  `research-policy-v1`'s twenty queries the branch tier's two rules (a
  comparison over three or more entities, or a plan broader than the
  planner's own range) do not fire: the distribution is **T0 12, T1 8,
  T2 0**. Arm E therefore runs and seals on this suite without ever
  reaching its own branch tier. That is a result rather than a defect —
  what "adaptive" buys is decided by the difficulty features, not by the
  arm's name — and it is pinned in
  `tests/test_listwise_selection.py::TestTheRouterOnTheShippedSuite` so
  a later change to `TIER_RULES` shows up as a change to that number.
  Retuning the table belongs to CAP-04 and to ADR 0070's discipline
  about thresholds an operator can move.
- **Known gap — per-run classification still reads the selected graph.**
  `classify_policy_shape` is handed the graph a run actually executed, so
  a T0 run inside an arm-E deployment classifies as arm B and a T1 run as
  arm C. That is unchanged from CAP-04 and it is arguably right for a
  *run*, but it means arm E is a **deployment-level** identity that only
  `read_deployment_shape` reads. Making the live shadow agree would flip
  every controller deployment's per-run arm label and is a contract
  change of its own.
- **Known gap — the campaign trajectory carries no tier decision.**
  `GraphEpisodeRunner` selects the tier but has no bridge to record
  `compute.tier_selected` on; `EpisodeRunner`'s protocol has no hook and
  widening it would break every scripted runner in
  `tests/test_campaign_execution.py`. The tier is inferable from the
  visited node list. Closing it means one optional keyword on that
  protocol.
- **Known gap — the selector has no per-agent effort override.** It
  calls `call_llm_json` with no `agent`, so it takes the deployment-wide
  `llm_effort` and `anthropic_model`. Adding `selector` to
  `EFFORT_AGENTS` would add two settings fields and a routing row; it is
  a one-line change the day an operator needs it.
- **Follow-ups.** A second diversity dimension is still ADR 0086's
  follow-up and still its own ADR. A learned selector — preference
  training over the `candidate.scored` records this now emits — is
  `02-target-architecture.md` §7's item 4 and needs data before it needs
  a design.

## Alternatives considered

- **Pairwise or tournament selection.** Rejected on both grounds above:
  O(N²) model calls against a policy whose cost claim is that
  orchestration adds none, and a ranking that can depend on comparison
  order.
- **Let the selector re-rank everything on every pass.** Rejected: the
  merge is incremental (ADR 0086) and a later pass that could reject an
  already-merged branch would delete the evidence the report was built
  on. Eligibility is therefore "succeeded and still carrying evidence",
  which excludes already-merged branches by construction because the
  merge releases their bulk output.
- **Make the selector a new agent under `src/agents/`.** Rejected: it
  chooses between candidates rather than producing content, which is
  what `src/policies/` is for — the same reasoning that put
  `decide_repair` and `decide_tier` there.
- **Score candidates individually and threshold.** Rejected: it is
  pointwise, not listwise, and RFC 10 §6.4 asks for listwise selection
  specifically because a candidate's value depends on what the others
  already cover.
- **Earn `candidate_lineage_selector` from the setting, like the compute
  router.** Rejected. The router has no node because ADR 0085's
  controller chooses *between* compiled graphs before a run starts, and
  no stage of the chosen graph can represent that. A selection is a
  stage. Reading it from a setting would give up the one thing that
  makes the capability checkable.
- **Set `ARM_SETTINGS["E"]` to `research_policy="orchestrated_workers"`
  so every arm-E episode runs the branch tier.** Attractive — it would
  have exercised the selector sixty times in the full matrix instead of
  zero — and rejected, because it is not arm E. Pinning T2 for the whole
  process is the opposite of a router selecting among T0/T1/T2, and
  `adaptive_compute_router` would have had to be earned from something
  that does not route. The honest configuration that declines T2 is
  better than a dishonest one that always takes it.
- **Retune `BRANCH_ENTITY_THRESHOLD` so the suite reaches T2.** Rejected
  for ADR 0070's reason: a threshold moved to make a test exercise a
  path is a threshold no evaluation can attribute a result to.
- **Widen `candidate.selected` to carry every selected id.** Rejected: it
  is a change to W04's closed event registry for something the selection
  artifact the payload already references carries in full.
- **A new `marginal_stop` trajectory event.** Rejected: RFC 10 §8.6's
  `compute.stop_decided` is exactly this event, down to the field names,
  and inventing a synonym is how two records of one fact start
  disagreeing.
