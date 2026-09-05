# 0083. Make the trajectory durable and projected, evaluation-only, behind the D8 gate

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: Agent engineering program (P0-WO08)
- **Depends on**: ADR [0064](0064-error-taxonomy-and-envelope.md),
  ADR [0066](0066-genai-semantic-conventions.md),
  ADR [0067](0067-correlation-context-and-log-contract.md),
  ADR [0076](0076-fixed-verify-repair-research-policy.md),
  ADR [0077](0077-model-aware-request-profiles.md),
  ADR [0078](0078-contract-shadow-for-the-research-path.md),
  ADR [0080](0080-mock-mode-covers-the-whole-research-graph.md)
- **Implements**: P0-WO08 in
  [`docs/agent-engineering/12-p0-work-orders.md`](../agent-engineering/12-p0-work-orders.md)
  §14

## Context

ADR 0078 put a canonical trajectory beside every research run and then
deliberately threw it away: the events live in a bounded in-process
registry, die with the worker, and store no bodies at all. That was the
right stopping point for a work order whose job was to prove the
contracts could be *reached* from a running job without changing one.

It is a bad stopping point for the thing the program exists to do. The
five-arm experiment needs to reconstruct an episode after the fact —
which sources were admitted, which claims were checked, what the verdict
was, whether the repair produced a re-verified child, what it all cost —
and none of that survives the process that produced it. An in-memory
ledger can prove a schema; it cannot be evidence.

Three constraints decide the shape of the answer, and all three are
inherited rather than chosen:

- **D8 has not ruled.** P0-WO09 delivered the governance package but the
  decision on retained user and learner content is still an owner's to
  make. Anything this work order builds that could write a real
  principal's trajectory to a file would pre-empt that decision by
  making it moot.
- **Postgres is a different slice.** RFC 10 §14.1 recommends Postgres for
  envelopes and §20 slice 3 is the work order that builds it. Mixing a
  storage vendor choice into a schema-semantics work order is exactly
  what §20's PR rules tell us not to do.
- **The current runtime surfaces are load-bearing.** The SSE frame set is
  a hand-transcribed client contract (`tests/test_contract_sse_events.py`
  pins it from both sides), the log event registry is closed
  (ADR 0067), and the GenAI span attributes are read from a pinned
  specification (ADR 0066). A measurement layer that changed any of them
  would have broken the thing it was measuring.

There is also a smaller, more embarrassing constraint. Three ADRs
finished with a follow-up they could not perform because
`src/observability/` is a closed registry owned by another lane:
ADR 0076 wanted a log event for the verifier's verdict and one for the
repair action, ADR 0077 wanted `gen_ai.request.temperature` to be
*absent* on a model that rejects sampling parameters and a warning for a
model with no capability row, and ADR 0080 wanted five per-node mock-mode
events. This work order owns that package, so those follow-ups are
closed here rather than left to rot.

## Decision

**One durable ledger, three projections, and a capture gate that a flag
cannot open on its own.**

### The artifact adapter

`src/contracts/artifact_store.py` implements RFC 10 §7 against the local
filesystem: `stage()` hashes and screens bytes into a staging namespace,
`promote()` re-verifies and publishes them under
`cas/sha256/<aa>/<bb>/<hex>`, and every read re-derives the digest. Four
things are refused outright rather than sanitised — a signed URL, a
credential shape, raw private reasoning, and a data class below the run's
or below any source the artifact derives from. Deduplication is by
digest, so two callers staging the same bytes share one object; principal
scope is a *separate* index, so a global content hash never becomes a
cross-principal read. Retention is an interface (`RetentionHook`) and
nothing more: the store has no deleter, because a deleter before a
retention policy is a policy decision wearing an implementation's
clothes.

### The runtime bridge

`src/contracts/runtime_bridge.py` carries two bridges over one recording
path.

`ResearchRuntimeBridge` subclasses W05's `ShadowRun`, so everything the
shadow recorded is inherited unchanged and the parity diagnostics keep
working. What it adds is the rest of the RFC 10 §8 taxonomy — tools,
sources, evidence, claims, verification, repair, candidate revision and
selection, budget reservations, checkpoint resume, the HITL outcomes that
are not a plain answer, the non-terminal `failure.recorded`, and the
terminal `budget.reconciled` — plus a durable ledger underneath.

`GuidedLearningBridge` records a guided-reading session: admission, the
attempt, an action pair per session node, `checkpoint.saved` +
`hitl.requested` at every learner turn, `hitl.responded` +
`checkpoint.resumed` when the learner answers, the closing summary, and
one terminal event. **It writes no learner `ProgressEvent` and derives
none.** The module has no import edge into `src.learning`, so the rule is
structural rather than remembered, and a test asserts the absence of the
edge rather than the absence of the behaviour.

`DurableTrajectoryStore` subclasses W04's in-memory adapter and puts the
sink write *inside* the same lock that allocates `run_seq`. That is the
one design detail worth arguing about, and the reason is concurrency: a
sink written outside the lock produces a file whose line order is not
sequence order when two branches append at once, and `import_jsonl` would
then have to sort before it could verify a chain. Projections run
outside that lock, after the accept has returned, each contained
separately.

### The sink

A run-scoped JSONL directory, not Postgres:

```text
<contract_event_sink_root>/runs/<run_id>/run_scope.json
<contract_event_sink_root>/runs/<run_id>/events.jsonl
<contract_event_sink_root>/runs/<run_id>/head.json
```

One directory per run because the logical API orders by
`(run_id, run_seq)`; because "give me that episode" becomes a path;
because retention deletion becomes a directory removal when a policy
eventually authorizes one; and because two concurrent runs then contend
for nothing. Every line is flushed and fsync'd before the call returns.

### The capture gate

`contract_event_capture` is `off` by default and its only other value is
`evaluation_only`. There is deliberately no `production` member, and the
gate is two-sided: `capture_permitted()` requires *both* that the flag
allows capture *and* that the run's consent scope is one of
`evaluation_only`, `public_source_evaluation` or `synthetic_test`. A real
research job and a real learner session carry `product_operation_only`,
are refused the sink and the artifact store whatever the flag says, and
keep exactly W05's in-memory behaviour. **Production and user-content
capture remain disabled pending D8**, and the sentence is enforced by a
parametrized test over every consent scope rather than by this paragraph.

### The projections

RFC 10 §16 pairs each canonical event with the runtime surface it may be
projected onto, and this work order implements that pairing as a
*derivation* rather than an emitter.

- **SSE.** `src/api/streaming.py` gains `CANONICAL_EVENT_PROJECTION`,
  `HITL_EVENT_PROJECTION` and `sse_event_name_for()`. Nothing writes a
  frame; no new event name reaches the wire; every projected name is a
  member of the set `tests/test_contract_sse_events.py` already pins, and
  the terminal frame is asserted byte-identical to the one
  `terminal_event_data` builds.
- **Logs.** One registered name, `trajectory_event_recorded`, carrying
  the RFC 10 type in a field — off by default, because a line per
  canonical event roughly doubles a research job's log volume to answer a
  question the ledger already answers.
- **OTel.** A span *event* on the currently active span, plus `trace_ref`
  copied onto the envelope. Copied, not depended on: a sampled-out span
  leaves the field absent and changes nothing about the event.

### Cost reconciliation

`budget.reconciled` is appended after the terminal event — W04's registry
allows exactly this type post-terminal — comparing the ledger's summed
usage deltas with the `RunCosts` snapshot. The tolerance is
`RECONCILIATION_UNIT_USD × (llm_calls + 1)`: one micro-dollar per
recorded call, because each delta is quantized to six decimals before it
is appended while `RunCosts` sums the provider's unrounded figures, plus
one unit for the accumulator's own float-to-`Decimal` conversion. Beyond
that the run fails closed — status `failed`, an `integrity_failure`
reason code, a WARNING and a metric point — rather than rounding a
disagreement away.

### The three ADRs' follow-ups

- `llm_span` now takes `float | None` and omits
  `gen_ai.request.temperature` when nothing was sent; `src/llm.py` passes
  `profile.temperature` directly (ADR 0077 follow-up 1).
- `unknown_model_capability_fallback` is registered and emitted once per
  run by the bridge for a model with no capability row (ADR 0077
  follow-up 2).
- `verify_verdict_recorded` and `repair_action_selected` are registered
  and emitted from the canonical events they describe (ADR 0076).
- The five `*_mock_*_served` names are registered, so the emit at each
  branch is now a one-line change in one file (ADR 0080).

## Alternatives considered

- **Write the Postgres adapter now.** Rejected on RFC 10 §20's own
  slicing and on §20's PR rule against mixing storage vendor choice with
  schema semantics. A local JSONL sink proves ordering, idempotency, the
  hash chain, artifact promotion and reconciliation with no
  infrastructure and no migration; the interface is the deliverable and
  the file format is behind it.
- **One shared JSONL file for every run.** Rejected: reads would have to
  filter, fsyncs would contend across concurrent runs, and a future
  retention deletion would have to rewrite a file rather than remove a
  directory.
- **Seal a `RunManifest` for the guided-learning lane.** Rejected, and
  this is the sharpest trade in the work order. RFC 09's
  `RunManifestPayload` requires a `PolicySnapshot` whose `arm_id`
  enumerates exactly the five research arms; a guided reading session is
  none of them, and putting a false arm id on a sealed control-plane
  object is worse than having no manifest, because a false arm id is a
  claim a later experiment would read as evidence. The lane seals a
  `GuidedSessionBinding` instead — the compiled TaskSpec's ref, the
  compilation receipt digest, the *real* admission resolution (so a
  metered provider with no approval fails closed there too) and the
  session graph's digest — and the trajectory's `manifest_digest` carries
  that binding's digest. Extending RFC 09's policy snapshot to express a
  non-arm policy is a contract change and belongs to that RFC's next
  revision, not to a bridge.
- **Derive a learner `ProgressEvent` from the session trajectory.**
  Rejected on RFC 10 §22 item 10 and on the work order. A progress ledger
  is a validated, principal-scoped, learner-owned record with its own
  provenance rules (ADR 0058); a trajectory is an operational record of
  what a policy did. Deriving one from the other would launder an
  operational fact into a claim about a person's understanding.
- **Rely on W04's idempotency to make a checkpoint resume safe.**
  Rejected because it does not work, and finding out why was useful. A
  resume takes a new process lease, so a replayed action's envelope
  carries a different `attempt_id` and therefore a different producer
  semantic digest — which the store is *right* to call an
  `IdempotencyConflict` rather than silently accept. Only the bridge
  knows the second proposal is the same logical action, so the bridge
  keeps the replay guard and the store keeps its conflict.
- **Let a projection failure fail the append.** Rejected on RFC 10 §16
  ("projection failures do not alter history") and on ADR 0078's
  structural promise. A run must end exactly as it would have without
  this module.
- **Sanitise refused artifact content instead of rejecting it.**
  Rejected: RFC 10 §10.1 says a detected secret is not persisted for
  debugging, and a redacted body is a body somebody will later argue
  about.
- **Sixty registered log event names, one per RFC 10 event type.**
  Rejected: the closed registry exists so a dashboard can be told when a
  name stops being emitted, and sixty names that all mean "an event was
  recorded" give that mechanism nothing to protect.

## Consequences

- **Positive.** A research episode and a guided-learning episode now
  reconstruct at the decision and artifact level from a file alone, with
  the hash chain verified on the way in. That is the P0 program gate's
  second bullet, and it is now demonstrable rather than planned.
- **Positive.** Three ADRs' blocked follow-ups are closed, and
  `gen_ai.request.temperature` stops asserting a value the request never
  carried.
- **Positive.** The artifact adapter gives the bodies a home that is
  content-addressed, integrity-checked, principal-scoped and refusal-
  first, which is what lets events stay bounded without losing the
  evidence they point at.
- **Negative.** There are now two ways to record a research trajectory —
  W05's `ShadowRun` and this bridge's subclass of it — and a future
  change to the event vocabulary has to be made in the parent to reach
  both. The alternative was a second recorder that would drift.
- **Negative.** The guided-learning lane has a sealed binding rather than
  a sealed manifest, which means `manifest_digest` means something
  slightly different on that lane. It is documented on the model, in the
  scope, and in the summary block, and it is a smaller lie than a false
  arm id — but it is a seam, and RFC 09's next revision should close it.
- **Negative.** The durable sink fsyncs per event. That is irrelevant
  beside a graph node and would be a real cost if this ever became a
  per-token ledger; it is the price of "durable" meaning durable.
- **Negative.** `contract_event_capture` is a second gate beside
  `contract_shadow`, and an operator now has two switches to reason
  about. They answer different questions — "is anything recorded" and "is
  anything written down" — and collapsing them would have made the D8
  gate a side effect of a diagnostic flag.
- **Follow-ups.**
  - Wire the five `*_mock_*_served` emits and the `verify`/`repair` node
    emits at their own call sites: `src/agents/planner.py:138`,
    `src/agents/reader.py:629` and `:637`, `src/agents/synthesizer.py:540`,
    `src/agents/critic.py:122`. Owner: whoever next opens those files.
  - Call `observe_reconciliation` and `observe_close` from
    `src/api/runner.py`'s terminal choke point. Both are written and
    tested; neither is wired there, because
    `tests/test_contract_shadow_runtime.py` pins a job trajectory's last
    event as the terminal one and `budget.reconciled` comes after it.
    Moving that assertion is a change to W05's test rather than an
    addition to this path, and an API job has no durable ledger for the
    reconciliation to make self-checking anyway. Owner: whoever
    re-baselines that assertion, or P0-WO11.
  - The Postgres adapter (RFC 10 §20 slice 3), with the same three-method
    `TrajectorySink` interface.
  - A retention deleter, once D8 and a retention policy exist. The hook
    interface is in place and deliberately inert.
  - Extend RFC 09's `PolicySnapshot` so a non-arm policy — a guided
    session, or any future product lane — can seal a real manifest.
