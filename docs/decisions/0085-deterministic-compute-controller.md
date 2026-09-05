# 0085. Deterministic compute controller v1 (T0/T1)

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: Agent-capability lane (CAP-04)

## Context

[`02-target-architecture.md`](../agent-engineering/02-target-architecture.md)
§4 asks for a compute controller that "should allocate a bounded
strategy, not a raw token budget", and
[`01-current-architecture.md`](../agent-engineering/01-current-architecture.md)
§6 records what exists instead: adaptive test-time compute is **absent**
— "static loop and spend caps; no difficulty/uncertainty-based
allocation". Two lines of work are blocked behind that absence.

**Arm E cannot start.**
[`07-first-policy-experiment.md`](../agent-engineering/07-first-policy-experiment.md)
needs difficulty features recorded *before* the compute decision and a
router that acts on them. [`04-roadmap.md`](../agent-engineering/04-roadmap.md)
AE-200 and AE-203 say the same thing from the roadmap's side.

**And two capabilities that already exist reach nothing.** ADR
[0077](0077-model-aware-request-profiles.md) landed nine
`<agent>_effort` settings that no call site passed, so setting
`READER_EFFORT=low` changed no request. ADR
[0076](0076-fixed-verify-repair-research-policy.md) landed the
verify-and-repair graph as `research_policy=fixed_verify_repair`,
selected once at settings load — so a *deployment* is arm B or arm C for
its whole life and a **run** cannot choose. Both are the same shape of
gap: a mechanism with no decision attached to it.

Two assumptions, either of which would change the answer if false. That
the first experiment freezes its instrument, so a threshold an operator
can move would make a result unattributable (ADR
[0070](0070-eval-integrity-provenance.md)). And that a *deterministic*
router has to be measured before a learned one is worth building — §4's
own roadmap puts "learn a small difficulty/compute router from
trajectory outcomes" after the deterministic one, because a learned
router with no baseline has nothing to be better than.

## Decision

### One switch, and it is off

```python
compute_controller: Literal["off", "deterministic"] = "off"
```

`off` is today, byte for byte: one graph is compiled, its node and edge
listing is the one already committed at
`tests/fixtures/graph/legacy-shapes.txt`, no tier is bound, no decision
is recorded, and `Settings.effort_for` is the ADR-0077 function.

`deterministic` requires `research_policy=legacy`,
`enable_supervisor=false` and `enable_verifier=false`, refused at load
with every offending flag named. Each of those three already claims the
shape the controller is choosing, and two claimants is one too many.

**`enable_evidence_store` is deliberately *not* required**, which is an
asymmetry with ADR 0076 and worth stating. There, the flag decides
whether a manifest may be *labelled* arm C, so a load-time refusal is
the only place the mislabelling can be made impossible. Here it decides
only how the selected graph classifies, and
[`research_binding.py`](../../src/contracts/research_binding.py) already
answers that honestly without help: with the evidence store on, T0 is
`research_fixed_evidence` and T1 is `research_fixed_verify_repair`;
without it, T0 is `research_fixed` and T1 earns
`research_capability_missing` with `evidence_store` named as the gap.
The classifier telling the truth is better than a refusal, and it also
keeps `COMPUTE_CONTROLLER=deterministic` loadable on its own — which the
settings property sweep in `tests/property/test_property_config.py`
requires of every declared `Literal` member that is not in
`COUPLED_FIELDS`.

### The features, and what they honestly are

[`src/policies/compute.py`](../../src/policies/compute.py) is pure: no
model call, no settings read, no clock, no I/O. `extract_features`
produces eight fields, and three of them are `None` on every path this
repository ships today:

| Feature | Source | Available today |
|---|---|---|
| `query_tokens` | whitespace count | yes |
| `entity_count` | distinct all-caps / internal-capital / digit-bearing tokens | yes |
| `comparative_cue` | a phrase from `COMPARATIVE_CUES` | yes |
| `freshness_cue` | a phrase from `FRESHNESS_CUES` | yes |
| `requested_depth` | the caller | no — `POST /research` has no depth field |
| `task_kind` | the sealed `TaskSpec` | no — see below |
| `sub_question_count` | the plan | no — the tier is chosen before the planner runs |
| `search_query_count` | the plan | no — same |

The `task_kind` case is the interesting one, because it is *structural*
rather than merely unbuilt. The tier selects the graph, and W05's
binding classifies the policy from the compiled graph it is handed — so
the graph has to be chosen before the episode is sealed, and the sealed
spec's `task_kind` cannot inform the choice that produced it. (It would
also not discriminate: `compile_research_intake` compiles exactly one
research kind.) The field is carried in the snapshot for the callers
that hold a spec already, and no rule keys on it.

The plan-time counts are the seam CAP-03 needs: a T2 decision is taken
*after* planning and reads them, so the rule exists now and fires only
when the counts are known. `None` is not zero, and `_plan_breadth`
treats it as "unanswered" rather than "narrow".

**Entity counting deliberately ignores sentence case.** "What" and
"Compare" open half the queries in the benchmark corpus, so counting a
leading capital would make `entity_count` a proxy for "the query is a
sentence". Three shapes count instead: all-caps of two or more (`RAG`),
an internal capital (`GPT`, `ResNet`, `arXiv`), and a digit beside a
letter (`4-bit`, `Llama-3`).

**A bare year is not a freshness cue.** "the 1998 LSTM paper" is the
opposite of a recency request, so `FRESHNESS_CUES` is phrase-only.

### The rule table

Evaluated in order. The two `requested_depth` rules are **decisive** —
they short-circuit, in both directions — and everything else is an
escalation: any one selects T1, none leaves T0.

| # | Rule | Fires when | Tier |
|---|---|---|---|
| 1 | `depth_quick` | `requested_depth == "quick"` | T0 |
| 2 | `depth_deep` | `requested_depth == "deep"` | T1 |
| 3 | `comparative_cue` | a comparison phrase is present | T1 |
| 4 | `freshness_cue` | a recency phrase is present | T1 |
| 5 | `multi_entity` | `entity_count >= 2` | T1 |
| 6 | `long_query` | `query_tokens >= 24` | T1 |
| 7 | `plan_breadth` | `sub_question_count >= 4` or `search_query_count >= 6` | T1 |
| 8 | `default_t0` | nothing above fired | T0 |

Every matching escalation is reported, not only the first: the reasons
are the audit trail an arm-E analysis groups by, and reporting one would
make two structurally different escalations indistinguishable.

The four thresholds are module constants, not settings. A threshold an
operator can move is a threshold no evaluation can attribute a result
to; moving one is an ADR and a re-baseline. Their sizing: 24 tokens is
about two sentences; two entities is the smallest query that can carry a
cross-entity claim, which is the claim class verification catches; and
the plan thresholds sit at the top of the planner's own instructed range
("2-4 focused sub-questions", "1-2 targeted queries" each).

### The tiers, and their limits

`MAX_DECIDABLE_TIER` is `T1`, by construction. T2 needs the branch
executor CAP-03 builds, and T3 is refused by the trajectory contract
itself (`src/contracts/trajectory.py` raises on
`compute.tier_selected` with `tier == "T3"`). A controller that could
name a tier it cannot execute would put an unrunnable decision in the
record.

| Tier | Graph | Verifications | Repairs |
|---|---|---|---|
| T0 | the fixed pipeline | 0 — there is no `verify` node | 0 |
| T1 | ADR 0076's verify-and-repair graph | at most 2 | at most 1 |

These limits are **descriptions of a structural guarantee, not a second
budget**. T0 cannot verify because the node does not exist in its shape,
and the one-repair cap is enforced where it already was, in
`route_after_verification`. Writing them into the decision is what lets a
record say what it authorised, and what lets a test assert the graph and
the record agree. No new runtime check is added, which is deliberate:
the cost ceiling and the cancel token are the run's real bounds and both
are unchanged.

### Two shapes, one checkpointer, selected per run

`build_workflow` compiles the alternate shape alongside the primary and
attaches the pair as `compute_tier_graphs(app)`. Three properties
follow, and each was a design constraint rather than a convenience:

- **T0 *is* the primary graph**, not a second compilation of the same
  edges. "Off is today" and "T0 is today" are then the same claim.
- **One checkpointer.** ADR [0034](0034-postgres-checkpointer-and-cross-worker-hitl.md) closed
  a leak of one saver per job; two independently built graphs would
  reopen it as two per process — under `SqliteSaver`, two writers on one
  file. The alternate is compiled against the primary's checkpointer and
  the primary keeps the only teardown handle, which the API lifespan
  already closes.
- **`build_workflow`'s signature and return type do not move.** The CLI,
  the eval runner, `shadow_bridge.graph_shape`'s one-off compile and
  every test that builds a graph keep holding a compiled app that
  behaves exactly as before.

Selection is one reassignment at the top of `run_job`, and its position
is the deliverable rather than an implementation detail: it happens
*before* `_contract_shadow`, so the binding classifies the graph the job
will actually run. **The runner never names a policy id.** An escalated
job's manifest says arm C because arm C's graph is what ran.

It lives in `run_job` rather than at the three `create_task` call sites
because that is the one function every job kind and every submission
path — `POST /research`, the redriver's resubmit, the session route —
already passes through. A graph with no tier mapping on it (a test's
stub, the guided-session graph, any build made with the controller off)
falls through to "run whatever you were handed", which is what keeps
every injected factory working in either position of the switch.

### Per-agent effort, and the tier override

Every `call_llm_json` call site in `src/agents/` now passes
`agent=<name>`, so ADR 0077's nine `<agent>_effort` fields stop being
fields nothing reads. With all of them at their `""` default the
resolved profile is unchanged and the request body is the one
`tests/fixtures/llm/request_kwargs_golden.json` pins.

```python
tier_effort_overrides: dict[str, str] = {}   # e.g. {"T1.verifier": "high"}
```

Resolved inside `Settings.effort_for`, above `<agent>_effort` and
`llm_effort`, and only while a run has a tier bound — a ContextVar in
`src/policies/compute.py`, the same shape as the cancel token
(ADR [0047](0047-bounded-executor-and-cooperative-cancel.md)) and the effective cost cap,
and copied into the node thread by the `copy_context()` the graph's
executor wrapper already does for those two. Two independent defaults
have to fail before an escalated run's request changes: the controller
has to be on *and* the map has to name the agent.

`"off"` is refused as a value. `""` already means "no override applies",
and a spelling that meant "send no effort" would be indistinguishable
from it; `<AGENT>_EFFORT=off` is what turns an agent's effort off. Every
level is checked against that agent's routed model at load, for the
reason ADR 0077 gives — an unsupported level is an HTTP 400 on every
call, not a degraded one.

### The decision reaches the trajectory, and not SSE

RFC 10 §8.6's `compute.tier_selected` has been in the event registry
since W05 with nothing in this repository able to emit it, because
nothing allocated compute. `ResearchRuntimeBridge.compute_tier_selected`
emits it immediately after the shadow opens and before the first node,
so the features are in the record before the decision they explain and
the decision before the compute it authorised.

The payload is closed to five registered fields, so the features arrive
as a **reference**: `feature_snapshot_ref` is `sha256:` over the
canonical snapshot. Two runs that saw the same features carry the same
ref, and neither carries the query — which is what lets the decision
ride on a `product_operation_only` run while D8's retained-content
question is open (ADR [0083](0083-runtime-event-bridge-and-artifact-adapter.md)).
`tier_budget_ref` spells the tier's limits
(`tier-budget:T1:verifications=2:repairs=1`).

**The decision is not in SSE.** `node_completed` carries `node` and
`state_delta` and nothing else; a third key would move a frame shape
`tests/test_contract_sse_events.py` pins byte-for-byte. The work order
permits omitting it on exactly that condition, and this is that
condition.

## Consequences

- Arm E's prerequisites exist: features are extracted and recorded
  before the allocation, and a deterministic router acts on them. Arm E
  itself stays `capability_missing` — it needs CAP-03's branching and
  CAP-09's listwise selection, neither of which is here.
- A deployment can, for the first time, run the cheap shape and the
  verify-and-repair shape in the same process, minutes apart, chosen by
  the query. That is the thing `research_policy` structurally cannot do.
- `<agent>_effort` becomes live configuration. A deployment that already
  set one of those fields expecting it to do nothing will see its
  request change; the fields have shipped for one work order and are
  documented as overrides, so this is the fix rather than a regression.
- Two compiled graphs cost one extra `StateGraph.compile()` at startup
  and no extra connection. Nothing is compiled at all with the
  controller off.
- A second graph is one more thing a change to `_build_fixed_pipeline`
  or `_build_fixed_verify_repair` has to be correct for. The golden
  listing and `tests/e2e/test_compute_controller.py` are the guard.

### Alternatives rejected

- **One graph with a conditional edge after the synthesizer.** Cheaper
  to compile and it would produce both trajectories. Rejected because
  the policy id would then be one id for both tiers: W05's binding reads
  the compiled shape, and a shape that contains `verify` classifies as
  arm C whether or not the run reached it. The manifest would say arm C
  for a T0 run.
- **Selection at the `create_task` call sites.** Three call sites, one
  of which (`src/api/routes.py`) is outside this lane's boundary, and a
  fourth would be added the next time a submission path appears.
- **A `PolicyRouter` façade returned by `build_workflow`.** It would
  have to reimplement `astream` / `aget_state` / `aupdate_state` /
  `get_graph` and would break `read_graph_shape` for the callers that
  legitimately want one shape.
- **Passing the tier through the call chain instead of a ContextVar.**
  Five signatures — `_invoke_streaming`, the node wrapper, every agent,
  `call_llm_json`, `call_llm` — would grow a compute argument. The
  precedent for the ContextVar is already load-bearing for two values
  that have the same shape of problem.
- **A learned or model-based difficulty estimate.** Explicitly out of
  scope: §4's roadmap puts it after the deterministic router, and it
  would spend a model call to decide whether to spend model calls.
- **Enforcing new per-tier caps** (papers, calls, cost). Rejected as
  behaviour this work order was not asked to change; the tiers describe
  what their graphs structurally allow and the existing ceilings are
  untouched.

## What CAP-03 and W05 may rely on

Published surface, changed only with a new ADR:

- the setting `compute_controller` and its values `off` /
  `deterministic`, and `tier_effort_overrides` keyed `<tier>.<agent>`;
- `src.policies.compute`: `ComputeTier`, `COMPUTE_TIERS`,
  `MAX_DECIDABLE_TIER`, `ComputeFeatures`, `extract_features`,
  `decide_tier`, `ComputeDecision`, `TierLimits`, `TIER_LIMITS`,
  `REASON_CODES`, and the `bind_compute_tier` / `active_compute_tier` /
  `reset_compute_tier` triple;
- `src.graph.workflow.compute_tier_graphs(app)` and the tier keys
  `"T0"` / `"T1"` in the mapping it returns;
- that the effective policy id is the *selected graph's*, derived by
  `read_graph_shape`, and never named by the runner;
- `ResearchRuntimeBridge.compute_tier_selected` and the module-level
  `observe_compute_tier`, taking primitives so `src/contracts` acquires
  no dependency on `src/policies`.

## What is not verified without a live call

This work order proves structure and cost, and nothing about quality.
Specifically **not** established:

- that the rule table's escalations correlate with difficulty at all.
  Every threshold is a stated hypothesis, and the first honest test of
  it is a paired evaluation, not this ADR;
- that escalating to T1 improves claim support enough to justify the
  extra synthesis and two verifications. That is H2, which ADR 0076
  built the mechanism for and this one supplies the allocation to;
- that raising the verifier's effort on T1 changes a real model's
  verdict quality, or its latency, in the direction intended. The
  keyword is asserted to reach the request; what a model does with it is
  unmeasured;
- what fraction of a real query mix escalates. Measured on the benchmark
  corpus it would be a number; measured on production traffic it would
  be a different one, and neither exists yet.

CAP-06 is the funded live smoke where the first three become answerable.
Until it runs, no number produced by this controller may be quoted as a
quality finding.
