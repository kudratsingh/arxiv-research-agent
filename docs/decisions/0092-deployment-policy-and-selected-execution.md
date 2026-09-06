# 0092. Record the deployment policy and selected execution separately

- **Status**: accepted
- **Date**: 2026-09-06
- **Deciders**: agent-capability lane (W13)
- **Follows**: [ADR 0085](0085-deterministic-compute-controller.md),
  [ADR 0088](0088-campaign-execution-loop.md), and
  [ADR 0091](0091-listwise-candidate-selection-and-the-marginal-stop.md)

## Context

Arm E is a deployment-level policy: a deterministic router bounded to
T0, T1, and T2, with the branch, listwise-selection, and marginal-stop
capabilities available. A particular run executes only one member of
that set. Before this decision those two facts were forced through one
field:

- the campaign sealed the deployment union as arm E but discarded the
  selected tier and its rule before the first graph node; and
- the API shadow sealed the selected graph alone, so a T0 run inside an
  arm-E deployment was classified as arm B.

The trajectory registry already contains `compute.tier_selected`, but
the campaign runner had no seam through which to emit it. Recording the
event alone would still leave the immutable manifest unable to say what
graph the event claims was selected.

## Decision

The manifest carries two distinct records:

1. `policy` remains the deployment policy. Under arm E it is
   `policy_kind="research_arm"`, `arm_id="E"`, and its graph digest and
   capabilities describe the complete selectable deployment.
2. `policy_execution` records the selected tier, eligible set, decision
   rule ids, feature-snapshot digest, tier-budget reference, and the
   selected graph's digest and node set.

An arm-E manifest without `policy_execution` is invalid. An execution
record is also invalid unless its deployment is an adaptive research
arm and the selected tier is allowed by that policy. The established
`PolicySnapshot` schema does not gain a field, so the golden A--D policy
digests remain byte-identical.

`GraphEpisodeRunner` exposes the smallest additional campaign seam:
`prepare_episode` derives the pure controller decision and selected
shape before sealing, and the call receives an `on_tier` callback. The
runner derives the decision again against the graph it actually drives;
the callback refuses a mismatch with the sealed execution and appends
`compute.tier_selected` before the first node action. Injected legacy
runners keep their existing callable signature because only a runner
that provides the preparation hook receives the callback.

On the API path, the runner retains the deployment graph while selecting
the per-run graph. The contract bridge classifies the deployment when
and only when its union structurally earns arm E; deployments that do
not earn E retain the selected graph's existing classification. The
same controller decision builds `policy_execution` and the existing
trajectory hook emits it.

## Consequences

- Every arm-E campaign episode is attributable both to the deployed
  policy and to the tier graph it executed.
- A T0 execution under arm E is never grouped with arm B.
- The manifest and trajectory carry the same tier, eligible set, rule
  ids, feature reference, and budget reference; divergence fails before
  an episode can become a completed datum.
- The mock 20 x 3 x 5 campaign remains 300 completed, zero excluded,
  `$0.000000`, and zero model/provider calls, while all 60 arm-E
  trajectories now contain exactly one pre-node tier-selection event.
- Preparing an adaptive campaign episode compiles its graph once to seal
  the selected shape and once to execute it. This is deliberate until a
  later runner-lifecycle change can hold a compiled graph safely across
  the manifest seal; correctness and immutability take precedence over
  saving a local compile that performs no model or network work.
