# 0089. Non-arm policy snapshots, learning context kinds, and one registry root

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: P0 contract follow-ups (W03b, W01b, W06b)
- **Amends**: [ADR 0078](0078-contract-shadow-for-the-research-path.md)
  (the policy shape a research run seals against),
  [ADR 0079](0079-benchmark-registry-migration-and-parity.md) (the
  registry's content vocabulary and its parity property), and
  [`09-run-manifest-rfc.md`](../agent-engineering/09-run-manifest-rfc.md)
  §19, [`08-task-spec-rfc.md`](../agent-engineering/08-task-spec-rfc.md)
  §20, [`11-benchmark-data-registry-rfc.md`](../agent-engineering/11-benchmark-data-registry-rfc.md)
  §23
- **Follows**: [ADR 0083](0083-runtime-event-bridge-and-artifact-adapter.md)
  (the guided-session binding that stood in for a manifest),
  [ADR 0085](0085-deterministic-compute-controller.md) (the T0/T1
  controller), [ADR 0086](0086-orchestrator-workers-for-the-branch-tier.md)
  (the branch tier and its non-arm classification)

## Context

Three work orders shipped, each recorded the same shape of finding, and
each recorded it as a gap in somebody else's file. Read together they are
one finding: **a contract that was closed at the moment it was written
started refusing the things the repository went on to build.**

**PR #222 (W08).** A guided-reading session had to seal *something*
before its first node ran. `RunManifestPayload` required a
`PolicySnapshot`, and that snapshot's `arm_id` enumerated exactly the
five research arms of
[`07-first-policy-experiment.md`](../agent-engineering/07-first-policy-experiment.md).
A reading session is none of them, and putting a false arm id on a sealed
control-plane object is worse than having no manifest — a false arm id is
a claim an experiment would later read as evidence. So W08 built
`GuidedSessionBinding`, a four-field substitute, and ADR 0083 said in
plain words that extending the policy snapshot "is a contract change and
belongs to whoever takes that RFC's next revision".

**PR #230 (CAP-03).** ADR 0086's orchestrator-workers graph has the same
problem from the other side. It is a *designed* research policy — a lead,
a bounded set of workers, a merge — and it is not one of the five arms.
It could not seal a manifest, so it declined, and a branch run became
indistinguishable in the record from a configuration nobody designed. The
work order wrote `test_the_branch_shape_cannot_seal_a_manifest_yet` "so
the gap closes loudly".

**PR #214 (W06).** `ContextRef.kind_matches_ref` admitted only
corpus-shaped reference kinds, and `compile_benchmark_case` stamped
`supplied_corpus` on every candidate ref. Every guided-learning case in
`eval_registry/` carries three refs — a scenario input, a persona and a
paper — and none of them is corpus-shaped, so a learning case could only
compile with an empty context list. ADR 0079 recorded it as a follow-up.

**PR #217 (W10).** The judge-calibration suite went to a second root,
`eval_registry_calibration/`, for two stated reasons: W06's `ContentKind`
and `ContentPayload` were closed, so a `calibration_item` could not be
filed under `eval_registry/content/` at all; and W06's parity called any
object its own modules did not build an `unregistered_object`. Both are
properties of one schema module. Neither is a fact about the objects, and
neither survives a third suite.

One assumption runs under all four, and it is worth stating because it is
what the repository stopped being able to afford: that the first policy
experiment's five arms were the only shapes a run could have. They were
the only shapes when RFC 09 was written. CAP-03, CAP-04 and W08 each
added one.

## Decision

### `PolicySnapshot` gains a `policy_kind` discriminator

| `policy_kind` | Identity fields | What it means |
|---|---|---|
| `research_arm` | `arm_id` (`A`–`E`), `selector` | One of the five arms. A–D's validator is unchanged. |
| `research_shape` | `policy_id`, `shape_nodes` | A designed research policy that is not an arm — `research_orchestrated_workers`, and controller-selected runs that are not one of the five. |
| `guided_session` | `policy_id`, `session_graph` | The learning graph, named and versioned. |

`shape_nodes` is the compiled graph's node set, sorted and unique.
`graph_digest` already pins the structure; the node set makes what was
pinned readable without a second checkout, so a shape id cannot quietly
come to mean a different graph.

**The honesty rule the old design was protecting is kept, and it is kept
structurally.** An arm snapshot carries no `policy_id`, no `shape_nodes`
and no `session_graph`; a non-arm snapshot carries no `arm_id` and no
`selector`; a `guided_session` requires every research runtime flag and
every research capability to be **false** and its `PolicyConfig` to be
empty, so a session manifest cannot be read as a research run with the
flags turned off. And a shape with no designed policy behind it still
refuses to seal: `policy_kind` discriminates between designed policies,
it is not a licence to name anything. `research_capability_missing`
remains what an undesigned combination classifies as, and
`policy_snapshot` still raises for it.

`PolicyShape` gains a matching `policy_kind` and a `sealable` property.
`representable` is deliberately **not** widened — it answers "is this one
of the first policy experiment's arms?", the answer for a branch run is
still no, and a field that changed meaning would be worse than a field
that is joined by a second one.

Every arm snapshot's canonical JSON gains one key, so A–E's snapshot
digests moved once. Nothing checked in pinned the old values; A–D's
structure, selectors, flags, capabilities and manifest content are
unchanged, and the four new values are pinned as goldens in
`tests/test_contract_research_binding.py`.

### Arm E is redefined structurally, and no longer requires a supervisor

`07-first-policy-experiment.md` §3 defines arm E as "supervisor plus
adaptive compute", and it was written before adaptive compute existed.
When it arrived it was not built on the supervisor:

- **ADR 0085** built the deterministic compute controller as a T0/T1
  selector over the *fixed* shapes, and refuses to load beside
  `enable_supervisor=true` — two things choosing the graph is one too
  many.
- **ADR 0086** built the branch tier (T2) over the same fixed substrate,
  and refuses a supervisor for the same reason.

So the original definition had become self-defeating: on the only
implementation of adaptive compute this repository has, requiring a
supervisor would make arm E unreachable by construction. Arm E is now:

> a deterministic compute controller selecting among T0/T1/T2 with
> candidate branching, **and** a listwise candidate selector, **and** a
> marginal-stop record.

The validator requires `enable_evidence_store` (a branch tier whose
reader emits no claims merges empty tables — arm C's refusal, arrived at
from the other side), the `adaptive_compute` capability, ordered T0–T2
tiers with a default, the router/branch/selection/stop configuration RFC
09 §7.2 already specified, and all four of `adaptive_compute_router`,
`candidate_branching`, `marginal_stop`, `candidate_lineage_selector`. A
supervisor is permitted and not required.

`adaptive_compute_router` becomes *earnable*, and by a setting rather
than a node, because ADR 0085's controller chooses between compiled
graphs before a run starts and no stage of the chosen graph can represent
it. It is still not earnable by a policy *name*: the setting is refused
at load unless the shapes it selects among are legal, which is what makes
reading it from configuration safe.

**Arm E remains `capability_missing`.** What changed is that the refusal
now names what is absent instead of a category:

```
Arm E graph lacks marginal_stop, candidate_lineage_selector: the listwise
candidate selector and the marginal-stop record are CAP-09's and nothing
in this repository builds them yet
```

### Both lanes seal the same manifest

`seal_episode_manifest` takes an already-decided `PolicySnapshot` rather
than a research policy shape, and the research and guided-learning
bridges both call it — so "the learning lane uses the same admission
controller" becomes a fact about one call site instead of two copies of a
call. `GuidedSessionBinding` keeps its name and its `schema_kind` and
becomes a **wrapper**: one `manifest` field, with `task_ref`,
`receipt_digest`, `admission`, `graph_digest`, `policy_id`,
`policy_version`, `environment_class` and `sealed_at` read back off it as
properties. Nothing is duplicated, so nothing can disagree.

`src/campaign/**` is untouched and its A–D dry run is unchanged.

### Three learning `ContextRef` kinds, derived rather than declared

`ContextRef.kind` gains `learning_scenario_input`, `learning_persona` and
`learning_paper`, each admitting exactly its own registry content kind
with no aliasing — `kind` reaches the candidate verbatim through the
runtime projection, so a persona ref in a `learning_paper` slot would be
a different claim about what the candidate was shown.
`compile_benchmark_case` derives the role and the purpose from
`ImmutableObjectRef.kind`, which already carries the registry's own
answer, and falls back to `supplied_corpus` for the research lane's
corpus and snapshot refs.

**The evaluator kinds are excluded by hand-enumeration, not by pattern.**
`learning_script`, `learning_expectations` and `learning_fixture` are the
suite's reference answers, sealed `ObjectVisibility.EVALUATOR`, and
`LabelRecord.value_ref` points at one of them. A rule phrased as "every
`learning_*` content kind" would hand the candidate the answer key, so
membership is a per-kind decision that matches the visibility each object
is sealed with.

### One registry root

`ContentKind` gains eight members and `ContentPayload` the nine models
that go with them, **imported from `src/calibration/suite.py` rather than
redefined**: two copies of a content model is how two trees stop agreeing
about what a `calibration_item` is. Two collisions are resolved rather
than papered over.

- `retention_terms` and `retention_policy` carry field-for-field
  identical payloads, so a smart union cannot tell them apart and would
  resolve one to the other's class — after which the envelope's own
  kind check rejects a perfectly valid object for contradicting itself.
  `ContentEnvelope` therefore parses its payload as the model its
  declared `schema_kind` names.
- `deliverable_contract` is one kind with two genuinely different shapes.
  Its entry lists both models, first match wins, and their ids do not
  collide.

All 120 calibration files moved into `eval_registry/` **byte for byte**;
no object of either suite was renamed, re-sealed or re-digested, and
`eval_registry_calibration/` is gone. `src/calibration/suite.py` points
at the one root.

W06's central property — "the checked-in tree is exactly what the modules
build" — is a property of the *tree*, so under one root it is restated
over the union or it says nothing about half the files.
`build_full_registry()` is both bundles, with the calibration content
re-validated into `ContentEnvelope`; that re-validation is the widening's
proof rather than a formality, because a payload that did not round-trip
would raise there instead of producing a tree the reader cannot read
back. `python -m src.contracts.registry parity` reports 257 objects and
0 mismatches, and `python -m src.contracts.benchmark_adapters`
regenerates the whole tree (`--benchmarks-only` writes just the two
benchmarks into a scratch directory).

## Consequences

- Every run this repository can start can now seal a manifest, so a
  branch run and a guided session appear in the record under their own
  names instead of not appearing at all.
- Arm E's gap is two capabilities rather than four, and CAP-09 closes it.
  A campaign follow-up should also drop `enable_supervisor: True` from
  `src/campaign/arms.py`'s `ARM_SETTINGS["E"]`, which still copies arm
  D's row and now describes an arm that no longer exists. The row is
  inert today — `UNRUNNABLE_ARMS` refuses arm E before a snapshot is
  built — and `src/campaign/**` was outside this work order.
- A third registry suite is an ordinary addition: declare its content
  kinds, add its builder to the union, and the property holds without a
  fourth root.
- Arm snapshot digests moved once. Nothing checked in pinned them, but a
  reader comparing a pre-0089 run record with a post-0089 one will see
  different policy digests for structurally identical arms, and the
  replicate group ids derived from them differ too.
- [`16-w12-approval-packet-draft.md`](../agent-engineering/16-w12-approval-packet-draft.md)
  §234 still cites `eval_registry_calibration/` in its W10 row. That
  document was outside this work order's editable set; the path needs one
  line changed.

## Alternatives considered

- **A separate `SessionManifest` for the learning lane.** Rejected: two
  manifest schemas is two admission controllers a month later, and the
  thing a session actually needed was one field on a discriminator.
- **Label the branch tier arm E.** Rejected by ADR 0086 already, and
  still rejected: it would claim the selector CAP-09 has yet to build.
- **A structural union with no tag field, to keep A–D's digests
  byte-identical.** Rejected: pydantic would discriminate three policy
  forms by which fields happen to be present, which is exactly the
  "guess what this object is" the discriminator exists to remove. A
  one-time digest move on an object nothing has pinned is the cheaper
  cost.
- **Forbid a supervisor in arm E rather than merely not requiring one.**
  Attractive — ADR 0085 makes `enable_supervisor=true` unreachable for a
  controller run anyway — and rejected because `src/campaign/arms.py`
  still declares that combination for arm E and is not this work order's
  file. A contract that refuses what a sibling module declares is a trap
  for whoever runs into it first.
- **Keep two registry roots and teach the parity report about both.**
  Rejected: that is the same amount of work and leaves the next suite
  choosing a third root.
- **Copy W10's payload models into `benchmark_adapters`.** Rejected for
  the reason the whole ADR exists: a duplicated contract is a contract
  that will disagree with itself.
