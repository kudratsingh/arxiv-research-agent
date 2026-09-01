# 0062. Bind a session-specific ceiling at the shared LLM choke point

- **Status**: accepted
- **Date**: 2026-09-01
- **Deciders**: maintainer

## Context

ADR 0051 made `src/llm.py::call_llm` the one pre-call spend choke point for
research, CLI, and evaluation runs. Guided-reading sessions need a smaller
ceiling: their estimated online spend is $0.07–0.17, while the research default
is $2.00. Applying the research ceiling would leave a single learner session
far too much room; replacing it globally would break the existing research
contract.

The session graph also parks between learner turns and may execute nodes in a
worker thread. The chosen ceiling therefore has to follow the job's execution
context, survive the graph's existing `copy_context()` handoff, and be reset
when the job exits. A module global or mutable setting would bleed between
concurrent research and session jobs.

Finally, reaching a ceiling is a product state, not an internal exception. The
deployment must be able either to refuse the session or to close it without one
more model call, while reporting exactly what happened and preserving the cost
already accumulated. Phase W builds both behaviors; the pilot decision chooses
one before real users are invited.

## Decision

Add `learning_session_max_cost_usd`, defaulting to `$0.50`, and
`learning_session_cost_cap_behavior`, defaulting to `refuse`. The upper bound is
a protective configuration limit, not a claim that a normal session should
approach it; measured pilot data will tighten the default.

At the start of every API job the runner binds the effective ceiling in a
`ContextVar`: session jobs bind `learning_session_max_cost_usd`, while research
jobs bind the existing `max_cost_usd`. `call_llm` continues to perform the
single authoritative pre-call check, now against that effective value. The
runner keeps ADR 0051's between-node check against the same value, and always
resets the binding in its terminal `finally` block. No second LLM client or
session-only enforcement path is introduced.

When a session reaches the ceiling:

- `refuse` produces a failed job with
  `error_type=session_cost_cap_refused`, `cost_cap_status=refused`, and explicit
  copy saying that no further tutor response was generated;
- `degraded_close` produces a succeeded terminal job with
  `cost_cap_status=degraded_close` and explicit copy saying that the work so far
  remains recorded and no further tutor response was generated.

Both outcomes surface `cost_cap_status`, `cost_cap_message`, `cost_usd`, and
`llm_calls` in the session snapshot and terminal event. The configured behavior
never attempts a final model-authored apology after the cap has fired.

Session-node spans record cumulative and delta cost/call attributes. The runner
also writes one structured cost record after each completed session node.
`unpriced_models(settings)` warns once for every configured model missing from
the price table, including `tutor_model` and `assessment_model`, so a routing
change cannot silently weaken enforcement.

## Alternatives considered

- **Lower `max_cost_usd` for the whole service** — simple, but changes the
  established research budget and cannot express the two products' different
  unit economics.
- **Check only between session graph nodes** — preserves the old runner shape,
  but permits intra-node overshoot and violates ADR 0051's shared-choke-point
  guarantee.
- **Pass the ceiling through every tutor and judge function** — explicit but
  duplicates enforcement, couples agents to deployment policy, and is easy to
  miss when a new model call is added.
- **Generate a graceful closing message after the ceiling fires** — better
  prose at the price of issuing exactly the call the ceiling refused. Static,
  honest copy is the only bounded close.
- **Use only the degraded close** — hides a consequential deployment choice.
  Both behaviors remain testable until the pilot owner decision is made.

## Consequences

- **Positive**: concurrent job kinds cannot inherit one another's ceiling; every
  model call remains guarded by the same choke point; at-cap outcomes are
  explicit and cost-accounted.
- **Positive**: model-routing changes emit a warning when pricing coverage is
  missing, and node traces show where session spend accumulated.
- **Negative**: `degraded_close` uses the normal success status even though the
  tutor did not reach its intended ending. Consumers must inspect
  `cost_cap_status`, which is why it is non-null and present on every session
  snapshot.
- **Negative**: the `$0.50` default is deliberately conservative headroom, not
  a calibrated learner-economics result.
- **Follow-ups**: WO-W13 renders both copy hooks; WO-W18/W20 compare measured
  session cost with the planning estimates; W-OD-5 selects pilot behavior.

