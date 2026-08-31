# 0057. Give jobs a kind, and generalize the HITL parking to `awaiting_learner`

- **Status**: accepted
- **Date**: 2026-08-30
- **Deciders**: kudratsingh (owner), Phase W fleet (WO-W01)

## Context

Phase W builds a guided-read tutoring session
(`planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md`, WO-W01). Its
scope ruling SR-01 ratifies `01-LEARNING-AGENT.md` §3.2's
recommendation: the session runs as a **second compiled LangGraph
graph** rather than as extra nodes in the research graph, because the
two have different shapes. A research run is job-shaped — state in,
nodes run, terminal state out, which is exactly what
`src/api/runner.py` was built to drive. A tutoring session is
turn-shaped: it stops and waits for a human between most steps.

The repo already has one sanctioned way to stop and wait for a human.
ADR 0030 built it for plan review: the workflow interrupts after the
planner, the runner moves the job to `pending_review`, publishes a
`plan_ready` frame, and blocks on `job.resume_event` until
`POST /research/{id}/review` sets it — or, under multi-worker uvicorn,
until ADR 0034's `hitl:resume:{job_id}` pub/sub message wakes a runner
parked on a different worker than the one that took the review. ADR
0038's lease keeps the redriver from mistaking a parked job for an
orphan; ADR 0053 replays the pause frame to a client that attaches
after the pause.

That is a lot of correctness, and a session needs all of it. It also
needs a *different* answer to two questions, which is what forced this
decision now rather than at WO-W03:

1. **How often is an interrupt a human decision?** For research,
   exactly once — `interrupt_after=["planner"]` re-arms on every
   re-plan, and ADR 0030 intends one review per query, so the runner
   auto-resumes the rest. For a session, *every* interrupt is the
   learner's turn. A session driven by the research policy would
   answer its own questions and report the result as a finished
   tutoring session.
2. **What bounds the wait, and how many waits are there?** Research
   bounds one review with `api_hitl_timeout_sec` and bounds its resume
   loop with `max_iterations + 2`. A twenty-turn session hits that
   ceiling on turn four.

WO-W01 is the phase's bottleneck work order and, per its own risk
notes, the highest-blast-radius backend change in the set: runner
churn with no Python cassette tier underneath it. The mitigation the
plan names is a sequencing constraint on *this* decision — the
generalization has to be proven against the behaviour that already
exists before the new state has any client.

## Decision

**One driver, two kinds, one parking mechanism.**

**`Job.kind: Literal["research", "session"]`, defaulting to
`"research"`** (`src/api/jobs.py`). A `Literal` rather than a
`StrEnum` like `JobStatus`: the value crosses the API boundary as a
plain string on `JobDetail.kind`, is stored as one in Redis, and has
no behaviour of its own. The default is what makes the field additive
in every direction at once — existing callers, existing rows, and
recorded fixtures all keep meaning what they meant.

**`JobStatus.awaiting_learner`, a non-terminal status** joining
`pending_review` in a new `PARKED_STATUSES` set. Parked is not a
synonym for review: `Job.is_awaiting_review()` stays
`pending_review`-only, because `POST /research/{id}/review` guards on
it and must 409 rather than push an approve/revise/cancel action into
a graph that has no idea what to do with one.

**`ParkingSpec` + `_park_until_resumed`** (`src/api/runner.py`). The
mechanism — write the parked status, publish the frame, subscribe to
the cross-worker resume channel, await the event, raise on expiry —
is written once. The spec records what differs: the status, the frame
emitter, the `settings` field bounding the wait, the exception raised
on timeout, and the log event. `HITL_PARKING` is the first instance;
`SESSION_TURN_PARKING` (`awaiting_learner` / `turn_ready` /
`session_turn_timeout_sec` / `SessionTurnTimeoutError`) is the second.

**`JobKindRuntime`**, the exhaustive record of what `run_job` does
differently per kind: the graph input, the pause policy
(`PauseHandler`), the pause ceiling, and the outer wall-clock timeout.
Nothing else in `run_job` branches on the kind. A session therefore
inherits ADR 0038's lease, ADR 0047's cancel token and drain, ADR
0051's cost accumulator, ADR 0049's outcome metrics, and the absorbing
terminal persistence — rather than a second driver having to earn all
of them again.

**Two settings** (`src/config.py`, `.env.example`):
`session_turn_timeout_sec` (default 1800) and `session_max_turns`
(default 40), which also sizes the session's outer wall-clock backstop.
No flag: WO-W01 ships the lifecycle, and the Phase W capability flags
land with the graph that needs them.

**The cross-worker channel is reused, not duplicated.**
`hitl:resume:{job_id}` is keyed by job id, not by what the job is
waiting for. `publish_remote_resume` gains an optional `payload` key
alongside `plan`, additive in both directions — an older worker
ignores it, a newer worker reads `None` from a message without it —
carried on `Job.resume_payload`. `resume_plan` stays plan-shaped;
a learner's reply is not a plan and is not stored as one.

**`turn_ready` is a pause frame, not an outcome.** It is deliberately
absent from `TERMINAL_EVENT_STATUS`, `TERMINAL_EVENT_NAMES` and
`STREAM_CLOSING_EVENT_NAMES`, exactly as `plan_ready` is, and
`src/api/streaming.py::PAUSE_EVENT_NAMES` records the two together so
the property is asserted rather than commented. A closing pause frame
would end the stream at the moment the human is supposed to act — once
per run for research, once per *turn* for a session. `Job.turn`
carries the parked turn on the row so ADR 0053's attach-time replay
works for a page reload mid-session, which SR-01 calls table stakes.

**Sequencing — the mitigation is part of the decision.** The
generalization landed in its own commit with `pending_review` as its
only client and no test file touched, and the full Python suite passed
at the same counts before and after it. Only then did
`awaiting_learner` gain a client. Anything that made the refactor
invisible to the existing suite — a helper that swallowed the emit
site's literal event name, say — was treated as a design error rather
than a test to update, which is why `ParkingSpec.emit` is a callable
with a real `_put_event` call in it rather than an event-name string.

## Alternatives considered

- **Wedge session turns into the research graph and reuse
  `pending_review` as-is** — no new status, no new kind, no runner
  change. Rejected by SR-01 and by the semantics: `pending_review`
  means "a human is deciding whether this plan is good", and the
  review endpoint acts on that meaning. Overloading it would let a
  learner's turn be resolved by `action=approve`, and would make
  `ResearchState` carry tutoring fields it has no business holding.
- **A second driver — `run_session_job` beside `run_job`.** Simplest
  diff, worst outcome. The lease, the drain, the cost cap, the
  compare-and-set terminal persistence and the outcome metrics are
  fifty ADRs of accumulated correctness, and a parallel driver either
  duplicates them or quietly does without. `01-LEARNING-AGENT.md` §5.1
  is explicit that this is "new job *types*, same lifecycle".
- **A thin chat loop outside LangGraph.** Less code, and forfeits
  exactly what the repo already paid for: checkpointed mid-session
  resume, cancellation, and cost enforcement through `call_llm`. 01
  §3.2 weighed this and recommended against; SR-01 ratifies that.
- **A shared base class for the two parking timeout exceptions**
  (`ParkedTimeoutError`, with the flavours subclassing it). Cleaner
  Python, and it breaks a real drift check:
  `web/tests/copy/errorTypeDrift.test.ts` derives the frontend's error
  vocabulary by matching `class X(Exception)` in `src/`, so a shared
  base would drop *both* timeouts out of the enumeration and silently
  un-map them. `SessionTurnTimeoutError` is a plain `Exception`
  sibling, intercepted by name, and a test pins that it stays one.
- **A second resume channel, `session:resume:{job_id}`.** Symmetrical
  and pointless: the channel is keyed by job id and a job has exactly
  one parking at a time. A second channel would double the pub/sub
  bookkeeping to express nothing the payload does not already say.
- **Declare `turn_ready` in `web/lib/api/events.ts` now.** It is the
  end state, and it is WO-W13's: adding the name forces ten rows into
  `web/lib/job/machine.ts`'s total transition table for a phase no
  route can currently reach. The gap is instead declared in
  `tests/test_contract_sse_events.py::WEB_UNCONSUMED_EVENT_NAMES`
  with its owning work order, and asserted from both sides — the
  backend must emit it, and the web client must not yet declare it —
  so it is a ledger entry rather than a hole.

## Consequences

- **Positive**: a session job is an ordinary job. It gets the lease,
  the semaphore, the cancel token, the cost accumulator, the outcome
  metrics, the redrive policy and the SSE replay without any of that
  being rebuilt or re-argued. WO-W03 writes a graph and a pause
  payload, not a runtime.
- **Positive**: the per-kind differences are now enumerable.
  `JobKindRuntime` has four fields, so "what changes when a third kind
  arrives" has an answer that is not "read `run_job` and hope" — which
  matters, because 01 §5.1 already names curriculum and precompute
  kinds for Phase L.
- **Positive**: the research path is provably unchanged. The refactor
  commit touched no test and moved no test count.
- **Negative**: `run_job`'s control flow now has an indirection a
  reader has to follow — `runtime_for(job.kind)` before the shared
  body. Mitigated by the runtime being resolved once, up front, with
  everything below it explicitly shared.
- **Negative**: `session_max_turns` is a second ceiling to reason
  about, and it sizes the outer wall-clock backstop as well as the
  pause count, so raising it lengthens how long a wedged session can
  hold a semaphore permit. The per-turn timeout is the mechanism that
  actually ends an abandoned session; this is only the backstop.
- **Negative**: the web tier now knowingly ignores an event the
  backend emits, and a `JobStatus` member. Bounded by the ledgers in
  `tests/test_contract_sse_events.py`
  (`WEB_UNCONSUMED_EVENT_NAMES`, `WEB_UNRENDERED_JOB_STATUSES`) and by
  there being no route that can create a `session` job yet. The status
  ledger is a drift check that did not previously exist at all —
  `JobDetail.status` is a bare `str` in the OpenAPI document, so
  nothing generated the frontend's vocabulary and nothing compared the
  two hand-written lists.
- **Negative, and the one that is not merely deferred**: unlike
  `kind`, **widening `JobStatus` is not backward compatible for an
  already-running worker.** `RedisJobStore._job_from_json` reconstructs
  the status with `JobStatus(...)` and no fallback, so a worker built
  before this change that reads a row parked in `awaiting_learner`
  raises `ValueError` out of `store.get` — a 500 on the job's detail,
  stream and review endpoints. There is no fix available from this
  side: a value the reader has never heard of cannot be honestly
  mapped onto one it has, and defaulting it would report a parked
  session as `pending`. The operational rule is therefore ordering —
  **workers are upgraded before any job can park in a new status** —
  which Phase W satisfies trivially, because no route creates a
  `session` job until WO-W03/WO-W13. It is stated here so the next
  status widening does not rediscover it during a deploy.
- **Negative**: the ADR 0034 subscribe-after-publish window is now hit
  once per *turn* rather than once per run. `watch_for_remote_resume`
  is spawned after the frame goes out, so a resume published inside
  that window has no subscriber; the runner then waits out the full
  parking timeout. Pre-existing and unchanged in mechanism — closing
  it means reordering ADR 0034's subscription, which is not this
  card's to touch — but a session multiplies the exposure and its
  timeout is terminal, so WO-W03 should subscribe before publishing
  when it wires the turn endpoint.
- **Follow-ups**: WO-W03 owns `SessionState`, `build_session_workflow`
  and the shape of the `turn` payload (`SESSION_TURN_STATE_KEY`);
  `_session_initial_state` seeds identity only and is replaced by that
  card's constructor. WO-W13 adds the `turn_ready` listener, the
  `awaiting_learner` phase in `web/lib/job/machine.ts`, the
  `awaiting_learner` member of the web `JobStatus` union, re-records
  the job fixtures against a session-aware stack, and makes
  `JobDetail.kind` required in `web/lib/api/models.ts`. WO-W06 adds
  per-session cost caps against the accumulator this decision keeps
  intact. **Not decided here**: what ends a session early. Plan review
  has `action=cancel` because a reviewer is vetoing spend about to
  happen; a learner stopping is a pedagogical event, and whether it
  should be a graph-level "end session" turn or a runner-level cancel
  is WO-W03's to answer. Until then an abandoned session ends at
  `session_turn_timeout_sec` with `error_type=session_turn_timeout`.
