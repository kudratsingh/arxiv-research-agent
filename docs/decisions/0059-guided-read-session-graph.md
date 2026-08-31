# 0059. Guided-read session graph and replay-safe learner turns

- **Status**: accepted
- **Date**: 2026-08-31
- **Deciders**: kudratsingh
- **Follows**: [ADR 0030](0030-hitl-plan-review.md) (human parking),
  [ADR 0034](0034-multi-worker-hitl-postgres.md) (cross-worker resume),
  [ADR 0047](0047-bounded-executor-and-cooperative-cancel.md) (bounded node
  execution), [ADR 0057](0057-job-kinds-and-awaiting-learner.md) (session job
  lifecycle), and [ADR 0058](0058-learner-profile-store-and-provenance.md)
  (principal-scoped Tier-1 profile)
- **Implements**: WO-W03 in
  [`planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md`](../../planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md#wo-w03--guided-read-session-graph)

## Context

ADR 0057 created the job-machine vocabulary for a learner turn but deliberately
did not invent the tutoring graph. WO-W03 has to make that state reachable while
preserving the properties the research graph already earned: durable
checkpoints, a bounded executor, cancellation, per-principal ownership, SSE,
cost accounting, redrive handling, and no model construction in mock mode.

Two details are load-bearing.

First, a learner reply is not a plan edit. Applying it with `update_state` to an
`interrupt_after` checkpoint attributes the update to the preceding node. On a
repeated tutor node that can re-arm the same interrupt and publish the old turn
again without processing the reply. LangGraph's dynamic `interrupt()` plus
`Command(resume=...)` is the replay-safe input primitive intended for this
shape.

Second, LangGraph inspects a node callable's state annotation and projects its
input to that schema. The shared ADR 0047 async wrapper is annotated
`ResearchState`; casting it to a session wrapper satisfies a type checker but
does not change the annotation LangGraph sees. Doing that silently drops
session-only fields such as `turn`, `tier1`, and `session_spec` at runtime.

## Decision

### A separate, total session graph

`SessionState` is a total `TypedDict` constructed by
`initial_session_state()`. The API persists the bounded input on the job row:
the principal id, a provenance-preserving Tier-1 profile snapshot, and a
validated paper/session specification extracted from the published content
manifest and its approved briefing companion.

`build_session_workflow()` compiles a second graph:

```text
check_in -> passage -> learner_input_1 -> tutor_1
                     -> learner_input_2 -> tutor_2
                     -> learner_input_3 -> tutor_3
                     -> learner_input_4 -> assess -> progress_update -> END
```

Each learner-input node can route directly to `progress_update` when the learner
ends early. The four input nodes are intentionally distinct. Dynamic interrupt
identity includes the node/task identity; unique nodes make each persisted
resume unambiguous across process reattachment. The bounded shape also makes
the promised session ceiling inspectable rather than hiding it in an open loop.

The session graph has its own typed sync and async wrappers. They retain ADR
0047's cancel-token registration, executor bound, context propagation, and
tracing, while presenting `SessionState` to LangGraph. Sharing behavior is
required; sharing a callable whose annotation changes runtime semantics is not.

### One job runner, one durable resume protocol

The existing `run_job` remains the only driver. The session pause handler parks
the row in `awaiting_learner`, writes the opaque turn to the row before emitting
`turn_ready`, and returns `Command(resume=reply)` after the authenticated turn
endpoint wakes it. Research HITL still returns `None` after its checkpoint edit.
The generic streaming loop accepts either resume form and never restarts from
`START`.

For Redis, the worker subscribes to the resume channel and signals readiness
*before* the learner-facing frame is published. This closes ADR 0057's
subscribe-after-publish race: once a client can see a question, some worker is
already able to hear the answer.

The HTTP surface is:

- `POST /learn/sessions` — validates auth, profile, published content, and an
  approved companion; creates a `kind=session` job.
- `GET /learn/sessions/{session_id}` — owner-scoped status/current-turn read.
- `POST /learn/sessions/{session_id}/turn` — owner-scoped reply or explicit
  early end.
- the existing `GET /research/{job_id}/stream` — reused unchanged for SSE.

All routes exist in OpenAPI regardless of flags. With `enable_session_loop=false`
they return `404 session_loop_disabled`; the generated client contract does not
depend on deployment configuration. Enabling the loop requires API auth through
the learner-profile invariant, plus checkpointing explicitly.

### Honest baseline assessment

WO-W03 records the explain-back as `recorded_ungraded`. It quotes the learner's
own words as evidence and writes append-only `assessment` and
`session_completed` events, but produces no score or mastery percentage. WO-W04
owns the calibrated explain-back judge. A missing future judge is represented as
missing, not approximated by a progress bar.

The mock path is deterministic and constructs no Anthropic client. Real tutor
JSON is allowlisted and parse-defended; malformed output falls back to a bounded
plan or asks the learner to restate instead of inventing an interpretation.

## Alternatives considered

- **Graft tutoring nodes onto `ResearchState`.** Rejected: it couples two
  different control loops and makes learner text available to research routing.
- **Use repeated `interrupt_after` plus `update_state`.** Rejected after the
  integration proof reproduced a stale-turn replay.
- **Cast the research wrapper to a session wrapper.** Rejected after the
  integration proof showed LangGraph follows runtime annotations, not casts.
- **Store the conversation only in the job row.** Rejected: it cannot resume a
  partially completed graph after a worker dies and duplicates checkpoint state.
- **Write an inferred mastery score now.** Rejected by the Phase W honesty rule;
  the evaluator and calibration evidence do not exist yet.

## Consequences

- A full four-pause session, an early end, owner isolation, malformed model
  output, mock zero-call behavior, and SQLite process reattachment are testable
  without paid inference.
- Session input is bounded to four learner turns for this wedge. A later adaptive
  loop is a new decision because it changes cost and timeout ceilings.
- The generated OpenAPI/types and proxy literal whitelist grow by three paths
  and two literal segments (`sessions`, `turn`).
- WO-W13 still owns browser rendering of `awaiting_learner` and `turn_ready`.
- WO-W04 replaces the guidance-only assessment node; it must preserve quoted
  learner evidence and the absence of fake mastery.

