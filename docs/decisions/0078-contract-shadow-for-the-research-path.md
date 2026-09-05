# 0078. Bind the P0 contracts to the research path in shadow, default off

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: Agent engineering program (P0-WO05)
- **Depends on**: ADR [0064](0064-error-taxonomy-and-envelope.md),
  ADR [0065](0065-test-isolation-and-coverage-floor.md),
  ADR [0067](0067-correlation-context-and-log-contract.md),
  ADR [0070](0070-eval-integrity-provenance.md)
- **Implements**: P0-WO05 in
  [`docs/agent-engineering/12-p0-work-orders.md`](../agent-engineering/12-p0-work-orders.md)
  §11

## Context

Four contract packages landed in this repository over the last week —
the shared kernel (P0-WO00), `TaskSpec` and its deterministic compilers
(W01), the sealed `RunManifest` and its admission controller (W03), and
the append-only trajectory with its in-memory adapter (W04). Every one
of them is complete, tested and **unreachable from a running research
job**. They import no settings, no provider, no agent and no graph, by
design, so nothing in `src/` calls them and no research run has ever
produced a `TaskSpec`, a manifest or a trajectory event.

That is a reasonable place to have stopped, and a bad place to stay. The
five-arm policy experiment the program exists to run
([`07-first-policy-experiment.md`](../agent-engineering/07-first-policy-experiment.md))
depends on being able to say, of a run that already happened, *which
policy it was* — and today the only answer available is "read the
environment variables and hope". The specific hazard the work order
names is arm C: `ENABLE_VERIFIER=true` under the fixed pipeline looks
like a verify-and-repair policy in a settings dump and is a **no-op**,
because `_build_supervisor_loop` is the only place a `verifier` node is
ever registered. A comparison that treated that configuration as arm C
would report a difference between two runs of arm A.

Three constraints force the shape of the answer now rather than later:

- **D9 blocks every live baseline**, so this work cannot be paid for by
  running one. It has to be provable at zero spend, against canned
  agents and recorded fixtures.
- **D8 blocks retained user or production trajectory capture** until
  consent, retention and purpose are decided. So whatever is recorded
  must not be persisted.
- **The current product paths must not move.** Cancellation, recovery,
  checkpointing, the cost ceiling and the report path each took a long
  sequence of ADRs to get right, and a measurement layer that changed
  any of them would have destroyed the thing it was measuring.

## Decision

### 1. One setting, two values, and deliberately no third

`Settings.contract_shadow: Literal["off", "shadow"]`, default `"off"`.

`off` disables every hook. The check happens *before* the import, so a
deployment with the switch off does not merely skip the calls — it never
loads a contract module at all. `tests/e2e/test_contract_shadow_research.py`
asserts that out of process, because `sys.modules` inside the suite is
already polluted by the unit tiers.

`shadow` compiles, seals and records beside the run. It changes no graph
input, no graph output, no job outcome, no cost, and no persisted
schema.

There is no `enforce`. Refusing a run on a contract verdict is P0-WO07
(campaign lock) and P0-WO11 (Stage-0 qualification) work, and it is
gated on reviewing the evidence this switch produces. Adding the value
now would let a reviewer believe the decision had been taken.

### 2. `src/contracts/research_binding.py` — the only module that knows both halves

The contract packages stay runtime-free. This module is the single place
that reads `Settings` and a compiled LangGraph app, and it answers four
questions:

| Question | Entry point |
|---|---|
| What task is this run being asked to do? | `compile_research_intake`, `compile_eval_case` |
| What shape is the policy actually running? | `classify_policy_shape`, `arm_capability_gap` |
| What configuration was frozen before the first node? | `seal_research_episode` |
| Do the projections agree with the legacy record? | `compare_outcomes`, `compare_research_state` |

Sealing follows RFC 09 §5.1's order exactly: compile and persist the
task, classify the policy against the compiled graph, resolve admission,
build and separately hash the candidate-safe runtime projection, then
hash and seal the control-plane payload. It seals or it raises
`ResearchBindingError`; there is no degraded manifest.

### 3. Policy shape is read from the graph, never from a flag

`classify_policy_shape` reads the compiled app's node set and its
conditional edges through `get_graph()`. Every capability that has a
node is detected structurally:

| Arm | Selector | Detected by |
|---|---|---|
| A | `fixed` | no `supervisor`, no `verifier`, no verify/repair stage, evidence off |
| B | `fixed_evidence` | the same graph, evidence store on |
| C | `fixed_verify_repair` | CAP-02's `verify` **and** `repair` nodes, evidence store on |
| D | `supervisor_verified` | `supervisor` **and** `verifier` nodes, evidence store on |
| — | `capability_missing` | any other combination, with the absent capability named |

Two consequences follow, and they are the acceptance criteria:

- **`ENABLE_VERIFIER=true` under the fixed pipeline is arm A.** The flag
  registers no node there, so `runtime_flags.enable_verifier` reads
  `False`, the arm is A, and the policy digest is byte-identical to the
  run with the flag off — a no-op does not even move the digest.
- **A `research_policy` that *names* `fixed_verify_repair` without the
  compiled stage is `capability_missing`, not arm C.** A claim is not a
  capability.

The evidence store is the one capability read from a flag, because it
has no node — it is reader behaviour. The asymmetry is stated in the
function rather than left to be rediscovered.

Arm E stays unrepresentable for a structural reason no setting can
change: nothing in this repository routes a compute tier, branches a
candidate, or decides a marginal stop. `ARM_REQUIRED_CAPABILITIES["E"]`
names the four capabilities, `arm_capability_gap("E", shape)` returns
all four for every configuration this repository can compile, and
`policy_snapshot` hard-codes `adaptive_compute=False` so the contract's
own arm-E validator can never be satisfied by anything this builder
produces.

`enable_query_refiner` and `enable_reader_recovery` are held out. They
move the graph and therefore the policy digest — a manifest that hid
that would misdescribe the run — and they move no arm id.

### 4. The manifest records what is true, including what is not resolved

Three choices worth naming.

**Secrets are excluded by type, locators by name, and the manifest's own
rule is the backstop.** `settings_projection` walks `Settings.model_fields`,
drops every `SecretStr` before reading a value (so `get_secret_value()`
is never called anywhere in `src/contracts/`, asserted by an AST scan),
drops the eight deployment locators in `LOCATOR_SETTINGS_FIELDS`, and
then asks `validate_manifest_safe_content` about each surviving field.
That third filter is what excludes `api_key_hourly_limit` — a rate limit
holding no secret at all, whose *name* the contract's forbidden-key rule
reads as a credential. Delegating rather than copying the rule is why a
developer's `CHECKPOINT_DB_PATH` under `/Users/...` cannot make a seal
fail on one machine and pass in CI.

**A metered provider fails admission closed.** Under `USE_MOCK_DATA` the
declared provider is `local_mock` and unmetered. Anywhere else it is
Anthropic, which bills per token, so the manifest says `metered=True`,
`resolve_admission` demands an external approval this work order does
not have, and the seal refuses. The run is untouched and the bridge logs
`contract_shadow_unavailable`. This is the design: "possessing an API
key never authorizes chargeable work" has to be enforced somewhere, and
a shadow manifest that quietly called a metered provider free would be
the place it stopped being true.

**Unresolved refs say so.** A production API request has no benchmark
case, no split and no campaign lock, and those manifest sections are not
optional. Rather than borrowing a plausible-looking reference, each one
is minted as `shadow-unresolved-<kind>` at revision `0.0.0` with its
digest taken over that statement. P0-WO06 owns the registry and P0-WO07
the campaign lock; invariant 12 forbids inventing their provenance in
the meantime.

### 5. `src/contracts/shadow_bridge.py` — in memory, and contained

The bridge appends to `InMemoryTrajectoryStore` and nothing else. A
report becomes a digest, a byte length and a `cas://` locator; no bytes
are written anywhere, because the content-addressed adapter is W08's. A
bounded registry (32 runs) keeps finished episodes readable for tests
and for the eval record, and dies with the worker.

Event mapping, following RFC 10 §16:

| Runtime fact | Events |
|---|---|
| sealed manifest | `run.admitted` (always `run_seq` 1, binding the digest) |
| the process attempt | `attempt.started`, `budget.established` |
| one graph node completing | `action.started` + `action.completed` |
| one completed model call | `action.started` + `action.completed` carrying a `UsageDelta` |
| spend nearing the ceiling | one `budget.threshold_reached` |
| the HITL plan-review park | `checkpoint.saved`, `hitl.requested`, `hitl.responded` |
| the finished report | `candidate.created`, `final.candidate_selected`, `final.artifact_produced` |
| the job row's terminal status | `run.completed` / `run.failed` / `run.cancelled` / `budget.exhausted` + `run.budget_stopped` |

The `action.started` beside each completion is honest about what it is:
the runners observe *completions* — `astream` yields after a node
returns — so the pair's ordering is real and its timing is not. Wrapping
the node itself is W08's durable bridge.

`checkpoint.saved` fires only at the plan-review pause, which is the one
place the runner treats a LangGraph write as a declared recovery
boundary. RFC 10 permits ordinary per-step checkpointer writes to stay
in the checkpointer, and recording sixty of them would say nothing the
node sequence does not.

Every entry point runs inside `_contained`, which absorbs `Exception`,
latches `degraded` on the run, and logs `contract_shadow_failed` once —
not once per node. It deliberately does **not** catch `BaseException`,
because the test harness's network and spend guards are `BaseException`
subclasses precisely so that no `except Exception` in this repository
can swallow them.

### 6. Five hook sites in the runner, two in the eval runner, one in the scripted lane

`src/api/runner.py` gains a `_current_shadow` ContextVar — the same
pattern, for the same reason, as `_current_store` — and five additive
calls: the scope that seals and binds the model-call observer, the
per-chunk `_shadow_node` in `on_node`, `_shadow_terminal` inside
`_persist_terminal` (the one place all eight terminal branches pass
through, which is exactly why ADR 0049 put the outcome metrics there),
and the two around the plan-review park.

`src/eval/runner.py` gains a context manager around the `invoke` call
and one terminal hook in the `finally`, which covers the failure, the
missing-report, the scored-success and the interrupt exits because all
four return the same record object. The observer is bound only around
`invoke`, because everything after it is harness spend — ADR 0050's
boundary, and a judge call recorded as a workflow model call would put
the eval rig's cost inside the product's trajectory.

`src/eval/simulate_research.py` gains one changed call line, passing
WO-D0's `EpisodeHooks` seam a `ScriptedResearchHooks` — or `None`, which
is the whole of the default path.

`src/observability/costs.py` gains `bind_llm_call_observer`, a
ContextVar sink notified after `record_llm_call` has already recorded
the call. A ContextVar rather than a process-global list for the reason
`_current_costs` is one: the reader records from a thread pool and the
runner copies its context into every node thread, so a job's observer
sees that job's calls and no others.

### 7. Parity diagnostics are pure functions

`compare_outcomes(LegacyOutcome, ContractOutcome)` returns a typed tuple
of `ParityMismatch`, comparing the objective against the submitted
query, the terminal event against the job status (a budget stop is a
`failed` row and a `run.budget_stopped` event), the model-call count,
the cost, the final artifact digest, and any `task_spec_ref` already on
the row. No settings, no clock, no I/O, no graph — which is what lets a
test corrupt one field and name the mismatch it produces, and what will
let a later work order run the check over stored records.

## Alternatives considered

- **Read the arm from `Settings` alone** — the cheapest possible
  implementation, and the one that produces the exact error this work
  order exists to prevent: `ENABLE_VERIFIER=true` on the fixed graph
  would be recorded as a verify-and-repair policy that never ran.
- **Wrap the graph nodes to emit events** — a richer trajectory with
  real start timestamps, at the price of editing `src/graph/workflow.py`
  on the hot path of every run, in a work order whose entire promise is
  that the run does not change. The `astream` chunks the runners already
  consume carry the same node sequence; W08 can take the wrapper when it
  owns the durable bridge.
- **Persist the trajectory to disk or Postgres** — would make the
  evidence durable and would also be exactly the retained capture D8
  blocks. In memory, bounded, dies with the worker.
- **Seal a manifest for a metered provider anyway, marked "unpaid"** —
  would let a shadow episode exist in every deployment. It would also
  mean a sealed manifest whose approval section says a chargeable
  provider needed no approval, which is the one claim a manifest must
  never make.
- **Emit a new `run.started` event to mirror the `job_started` SSE
  frame** — RFC 10 §16's projection table names one, but §8.1's registry
  does not contain it and unregistered event types are rejected. The
  frame projects from `attempt.started` instead; the discrepancy is
  worth an RFC amendment and is not worth an unregistered event.
- **Put the binding outside `src/contracts/`** — would keep the package
  literally runtime-free. It would also separate the glue from the
  contracts it is glue for, and the package boundary is already stated
  in each module's docstring: `kernel`, `task_spec`, `registry`,
  `run_manifest` and `trajectory` import no runtime; `research_binding`
  and `shadow_bridge` are the two that do, and they are named for it.

## Consequences

- **Positive**: A/B/D are mechanically distinguishable without executing
  a live model, and C becomes distinguishable the moment its stage is
  compiled rather than the moment somebody sets a flag. C cannot be
  faked by `ENABLE_VERIFIER=true`; E cannot be represented at all. Every
  research run under the switch produces one immutable task, one sealed
  manifest, and a hash-chained trajectory that round-trips through the
  contract's own importer. The parity check gives a reviewer a number
  — mismatches — rather than an impression.
- **Negative**: five more call sites in `src/api/runner.py` and two in
  `src/eval/runner.py`, in files that were already long. A shadow
  episode seals only where the provider is unmetered, so a live
  deployment gets `contract_shadow_unavailable` and no evidence until
  W07 supplies an approval backend. The trajectory's node events carry a
  start timestamp that is really the completion's, and say so. `src/contracts/`
  is no longer uniformly runtime-free.
- **Follow-ups**: P0-WO08 owns durable persistence, the content-addressed
  artifact adapter, the SSE/log/trace projections derived *from* canonical
  events rather than beside them, `RunCosts` reconciliation
  (`budget.reconciled`), and per-node action timing. P0-WO06 owns the
  benchmark registry that replaces the unresolved registry refs; P0-WO07
  owns the campaign lock, the approval backend and the repeat
  orchestrator. RFC 10 §16's `run.started` needs reconciling with §8.1's
  registry. Enforcement — refusing a run on a contract verdict — stays
  out until the shadow evidence is reviewed.
