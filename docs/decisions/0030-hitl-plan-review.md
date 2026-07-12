# 0030. Human-in-the-loop plan review after the planner

- **Status**: accepted
- **Date**: 2026-07-11
- **Depends on**: ADR
  [0014](0014-supervisor-loop-behind-flag.md) (workflow),
  [0025](0025-fastapi-async-job-model.md) (job model),
  [0026](0026-sse-streaming-endpoint.md) (SSE),
  [0029](0029-nextjs-web-ui.md) (web UI)

## Context

Sprint 5's product-surface arc opens with a demo UI (ADR 0029)
that lets a reviewer submit a query and watch nodes complete. The
next unlock is agency: giving the reviewer a chance to steer the
workflow before it commits to a plan. Without that, "run
research" is a black box between submit and result — the whole
point of a multi-agent surface is that the human can
see-and-shape the intermediate reasoning.

The planner is the highest-leverage intervention point. It
decomposes a natural-language query into `sub_questions` and
`search_queries` that drive every downstream node — search
scope, retrieval breadth, citation footprint. A misinterpreted
question wastes 30-90 seconds of workflow + Anthropic spend; a
review-and-edit before search costs a click.

The roadmap item is item #2 in
[`planning/03-roadmap.md`](../planning/03-roadmap.md) Sprint 5:
"Human-in-the-loop breakpoint after supervisor's plan step."

## Decision

Pause after the planner on the initial plan, expose the plan for
review over HTTP, resume on a human decision. Feature-flagged **on
by default** (`enable_hitl=True`) with per-query bypass for
programmatic callers.

### Where the interrupt fires

`build_workflow()` compiles the graph with
`interrupt_after=["planner"]` when `settings.enable_hitl` is on.
This fires after the **first** planner invocation only — the
supervisor loop's mid-run re-planning (critic-driven revisions,
supervisor-picked plan actions) runs uninterrupted. Rationale:
one review per query keeps the demo tight; a reviewer who
wanted per-revision control could opt into that later.

LangGraph's `interrupt_after` requires the checkpointer to be
enabled (there's no state to resume from otherwise). The compile
code short-circuits the interrupt when `settings.enable_checkpointing`
is off, treating an interrupt-without-checkpointer as an incoherent
configuration.

### Runner protocol

`src/api/runner.py::_invoke_streaming` becomes a two-phase
astream:

1. **Phase 1** — `astream(initial_state, config)` runs until the
   workflow interrupts (planner output emitted, next node pending).
2. **Check** — `app.get_state(config).next` reports the pending
   nodes; a non-empty tuple means we're paused.
3. **Pause** — `_handle_hitl_pause` populates `job.plan =
   {sub_questions, search_queries}`, transitions status to
   `pending_review`, emits a `plan_ready` SSE event, and `await`s
   `job.resume_event` under `api_hitl_timeout_sec`.
4. **Resume** — on the caller's decision:
   - `approve`: proceed to phase 5 without state edits.
   - `revise`: `app.update_state(config, edited_plan)`, then
     phase 5.
   - `cancel`: raise `HitlCancelledError`, caught in `run_job` and
     translated to `status=cancelled`.
   - Timeout: raise `HitlTimeoutError`, caught in `run_job` and
     translated to `status=failed, error_type=hitl_timeout`.
5. **Phase 2** — `astream(None, config)` resumes from the
   checkpoint. Passing `None` is the LangGraph convention for
   "resume from where we paused, no fresh input."

The runner does **not** hold the semaphore across the review wait
— that would starve other jobs on a busy worker. Wait, actually
it does: the semaphore is acquired at the top of `run_job` and
released only on `return`. This is a deliberate trade-off in the
current PR: HITL runs count against the concurrent-jobs ceiling
so a queue of reviews can't crowd out fresh work. Revisit with a
priority queue if we ever get a workload where that matters.

### API surface

- `POST /research` gains an optional `hitl_bypass: bool` field.
  When true the runner skips the pause even if the workflow is
  compiled with an interrupt — the eval runner and the CLI use
  this. Matches the settings-level flag but at per-request
  granularity.
- `POST /research/{id}/review` — new endpoint. Body:
  `{action: "approve"|"revise"|"cancel", plan?: {sub_questions,
  search_queries}}`. Guarded 404 if the job doesn't exist, 409 if
  the job isn't in `pending_review`, 422 if `action=revise` is
  missing a plan.
- `GET /research/{id}` — response gains a `plan` field, populated
  when `status=pending_review`.

### SSE event

New non-terminal event `plan_ready` per ADR 0026's compact frame
convention: `{job_id, plan: {sub_questions, search_queries}}`.
Stream stays open through the review + resume. Clients that
prefer polling can hit `GET /research/{id}` on any
`pending_review` cue.

### Web UI

`PlanReview` component (amber-themed, distinct from the neutral
progress panel and the destructive red action) with editable
lists for both fields and three actions:
- **Approve as-is** — enabled while the plan is unedited; sends
  `action=approve`.
- **Save edits & approve** — enabled while the plan is edited;
  sends `action=revise` with the working copy (empty entries
  filtered).
- **Cancel job** — always enabled; sends `action=cancel`.

The `useResearchStream` hook exposes a new `awaiting_review`
status and a `review(action, plan?)` action.

### Bypass path

Three callers must not pause:

1. **Eval runner** (`src/eval/runner.py`) — nightly benchmark runs
   unattended. `build_workflow(enable_hitl=False)`.
2. **CLI** (`src/main.py`) — no way to accept a review from stdin
   mid-run. `build_workflow(enable_hitl=False)`.
3. **API programmatic callers** — pass `hitl_bypass=true` on POST
   /research. The runner honors it even when the workflow is
   compiled with an interrupt (compile-time setting is
   unconditional; the runner resumes immediately).

## Alternatives considered

- **Pause on every planner invocation** including supervisor-loop
  re-planning. Rejected as too demo-hostile: a critic-driven
  revision would require a click every time. Roadmap item is
  explicit about "after the plan step" as the initial review, not
  per-loop. A `hitl_mode: "first"|"every"|"none"` per-request
  toggle could land later without touching the compile surface.
- **Pause on approve-or-cancel only, no edit surface.** Trivially
  simpler UI but loses the point of HITL — the value is
  steering, not just gating.
- **Free-form state editing.** Give the reviewer keys to the
  whole `ResearchState`. Rejected: opens a hole for arbitrary
  state manipulation (papers, citations, iteration counter) that
  bypasses every guardrail downstream. `sub_questions` and
  `search_queries` are the two fields the planner produces; edit
  those and the rest re-derives correctly.
- **Redis-backed resume signal.** Would let a POST /review on
  worker B wake a paused job on worker A. Rejected for this PR:
  builds on Redis pub/sub which is a real subsystem to stand up;
  same worker-affinity story as SSE (ADR 0027). Documented as a
  follow-up.
- **Feature flag off by default.** Considered — matches the
  Sprint 2/3 pattern of every-new-feature-behind-a-flag. Rejected
  by maintainer for the demo showcase story: HITL is the
  headline feature of Sprint 5 PR 2, and hiding it behind a flag
  makes the demo require extra config. Instead, on by default
  with a per-query bypass — the shape that a demo reviewer sees
  the feature, and the eval harness sidesteps it without a
  global toggle.
- **Include the plan on every `GET /research/{id}`.** Rejected:
  the plan is meaningful only while the workflow is paused. Once
  resumed, `sub_questions` and `search_queries` are exposed via
  the report and the state trace; the `plan` field on JobDetail
  stays `None` outside the pause window.

## Consequences

- **Positive.** The demo now shows agency — a reviewer sees the
  planner's output, edits it, and watches the edited plan drive
  the rest of the workflow. Every non-interactive caller (eval,
  CLI, programmatic API consumers) opts out cleanly. The
  interrupt is a first-class LangGraph feature, so we're not
  fighting the framework.
- **Neutral — status enum grows.** `JobStatus.pending_review`
  is a new non-terminal state. Every client (JobSummary,
  ResearchApp, EventLog) needs to know about it or route through
  the terminal-events check. The `TERMINAL_STATUSES` frozen set
  gates the "is this settled" question in one place, so
  regressions surface fast.
- **Negative — worker affinity for the resume signal.** The
  runner's `resume_event` is an in-process `asyncio.Event`. A
  POST /review that lands on a different worker than the runner
  can't wake the pause. Under the single-worker default this is
  fine; under a load-balanced multi-worker deploy the review
  request needs sticky routing on `job_id`. Documented on the
  ADR; matches the existing SSE affinity story (ADR 0027).
- **Negative — the review-wait counts against the concurrency
  semaphore.** A queue of pending_review jobs can crowd out
  fresh work. Acceptable at demo scale; revisit if production
  workloads exhibit this.
- **Follow-ups.**
  - **Redis pub/sub for cross-worker resume** — remove the
    sticky-routing requirement.
  - **Per-query `hitl_mode`** — `first` / `every` / `none` on
    POST /research for reviewers who want mid-run interventions.
  - **HITL breakpoint at additional nodes** — after the reader
    (verify evidence coverage), after the synthesizer (approve
    citations). Same infrastructure; different `interrupt_after`
    entries.
  - **Draft-mode preview** — show the planner's output *before*
    it runs (i.e., before any LLM call for planning). Requires
    a real cost-preview mechanism.
