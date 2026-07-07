# 0014. Supervisor loop behind a settings flag with strict-enum action space

- **Status**: accepted
- **Date**: 2026-07-07

## Context

Sprint 1 built the measurement substrate (four eval metrics + nightly
regression diff). Sprint 2 uses it to test the actual thesis: does an
agentic supervisor loop beat the fixed pipeline on quality, given the
cost we pay for autonomy?

The current shape is a DAG with one conditional edge on the critic
(planner → search → reader → synthesizer → critic → …). Adding a
supervisor that picks the next action every turn is the biggest
agentic upgrade the codebase can absorb, and the eval harness now
makes it measurable. See
[`planning/05-agentic-upgrade-plan.md`](../../planning/05-agentic-upgrade-plan.md)
for the full Sprint 2 sequencing.

Two constraints dominate the design:

1. **The fixed pipeline must keep working**. Ops shouldn't lose the
   pre-Sprint-2 behavior — we can compare against it, ship on top of
   it, and roll back to it if the loop underperforms.
2. **Unconstrained supervisors thrash**. Every real-world LLM
   supervisor experiment I've seen fails on the "the model picked
   'plan' seventeen times in a row" failure mode. The action space
   must be a strict enum, malformed responses must fall back to
   something predictable, and the loop must have a hard iteration cap.

## Decision

Add `src/agents/supervisor.py` with `supervisor_agent(state) -> partial state`
and `route_after_supervisor(state) -> next node name`. Enable it via
`settings.enable_supervisor: bool = False`. `workflow.py::build_workflow`
picks the graph shape based on that flag:

- **Off (default)**: existing fixed-pipeline wiring, unchanged.
- **On**: `START → supervisor → chosen_node → supervisor → … → END`,
  where every agent node hands control back to the supervisor.

### Strict-enum action space

```python
VALID_ACTIONS = frozenset(
    {"plan", "search", "read", "synthesize", "critique", "stop"}
)
```

Any judge output outside this enum triggers `_default_next_action(state)`
— the deterministic rules-based fallback that mirrors the fixed
pipeline. Same fallback fires on:

- LLM exception (e.g. Anthropic 429 after retries)
- JSON parse failure (delegated to `call_llm_json`)
- Missing `next_action` field in the response

This is not a fatal error — the loop can always take a safe step.

### Budget short-circuits before the LLM call

```python
if state["loop_iterations"] + 1 > settings.max_loop_iterations:
    return _emit("stop", ..., "max_iterations_reached", ...)
if current_costs().total_cost_usd >= settings.max_cost_usd:
    return _emit("stop", ..., "budget_reached", ...)
```

Budget checks run **before** we ask the supervisor. Saves cost on the
supervisor's own call in the exact failure mode where we most need
cost restraint. `stop_reason` is recorded on state so downstream
analysis can bucket runs.

### State additions (`ResearchState`)

- `next_action: str` — the supervisor's last decision. Read by
  `route_after_supervisor`.
- `loop_iterations: int` — hard cap counter for supervisor
  invocations. Orthogonal to `iteration` (critic-revision counter).
- `stop_reason: str` — populated when action == "stop":
  `quality_reached | budget_reached | max_iterations_reached |
  supervisor_stop | llm_failed`.

### Settings additions (`src/config.py`)

- `enable_supervisor: bool = False` — the master flag
- `min_quality_score: float = 0.75` — quality-based stop threshold
- `max_cost_usd: float = 2.00` — per-run cost cap
- `max_loop_iterations: int = 20` — hard supervisor-invocation cap

### Regression-diff extension

`METRIC_FIELDS` gains `iterations`, `llm_calls`, `cost_usd`.
`METRIC_DIRECTIONS` maps each metric to `"higher_better"` or
`"lower_better"` so the classifier treats a cost rise as a
regression, not an "improvement" (which the old direction-blind logic
would have wrongly claimed).

`summary.jsonl` gains `loop_iterations` and `stop_reason` per query
so nightly runs surface loop behavior even without a full metric
recompute.

## Alternatives considered

### Enable-supervisor toggle

- **Delete the fixed pipeline once the loop lands.** Rejected. The
  fixed pipeline is our ground truth — every future loop iteration
  should be able to run against it. Also cheaper for smoke tests.
- **Runtime routing based on query complexity.** Attractive but
  premature; we'd be tuning two systems at once. Ship the loop
  behind a flag first; adaptive routing after we have a working loop
  and something to route between.

### Action space

- **Free-form JSON, validated on read.** Rejected. The reviewer's
  "constrain the action space hard" is exactly the right note —
  loose action space → thrash → regression → hours of prompt-
  engineering. Enum + fallback is boring and correct.
- **Enum includes `verify` from day one.** The verifier agent doesn't
  exist yet. Adding a stub that raises `NotImplementedError` would
  poison the fallback path. `verify` gets added when
  `src/agents/verifier.py` lands.

### Fallback behavior

- **Raise on malformed judge output.** Rejected. Makes the loop
  brittle — one bad LLM response kills the whole run. The deterministic
  rules-based fallback preserves progress while flagging (via
  `log.warning`) that the supervisor is misbehaving.
- **Always fall back to `stop`.** Rejected. Too pessimistic — a
  garbled judge response early in the loop shouldn't terminate a
  research task with no output.

### Budget enforcement

- **Estimate the supervisor call's cost against budget before making
  the call.** Attractive but wrong-shaped: we can't know the cost
  until after the response. Instead: short-circuit at loop iteration
  start based on accumulated cost.
- **Prompt-only enforcement** (put the budget rules in the prompt
  and hope the LLM respects them). Rejected. The whole reason we're
  building this the "hard" way is that LLMs don't reliably respect
  soft budget signals.

### State schema

- **Full state extension per `planning/05` item 5.75** (research_goal,
  open_tasks, completed_tasks, evidence, tool_history, evidence_gaps,
  confidence, cost_budget_remaining, budget_used). Deferred to when
  the verifier + evidence store land. Adding empty fields now would
  create schema drift for state accessors that don't need them yet.
- **`stop_reason` as an enum type.** Kept as `str` for now — the
  supervisor prompt can return unforeseen strings and we don't want
  a validation error to override a legitimate stop. Downstream
  analysis buckets by known prefixes.

## Consequences

- **Positive**:
  - Fixed pipeline preserved as ground truth. `enable_supervisor=False`
    is a code-free rollback.
  - Loop shape is `observe → decide → act`; failure modes are logged
    at every fallback so we can see when the supervisor is
    misbehaving without opening the eval JSON.
  - Cost/iteration runaway shows up in the nightly regression diff
    as a real regression (direction-aware classification), not as an
    "improvement" that a naive delta comparison would produce.
  - The three new settings knobs are typed and immutable (per ADR
    0011). Env-var-driven experimentation is safe.
- **Negative**:
  - Adds ~7-10 LLM calls per query. At Sonnet prices this is
    ~1.7-2× per-query cost. The eval harness measures this.
  - Two workflow shapes to maintain. Mitigated by keeping them in
    separate `_build_*` helpers in `workflow.py`, sharing agent
    construction.
  - `next_action` / `loop_iterations` / `stop_reason` are always
    present on state (both shapes) — under the fixed pipeline they
    stay at their initial values. Small schema surface cost.
- **Follow-ups (from `planning/05`)**:
  - `feat/verifier-agent` — add `verify` to `VALID_ACTIONS`;
    supervisor can dispatch it.
  - `feat/evidence-store` — reader emits `EvidenceClaim`s;
    supervisor sees `evidence_gaps` for planning.
  - `feat/query-refiner` — supervisor's "search again" chooses new
    queries via the refiner, not the same failed ones.
  - `feat/reader-requests-more-chunks` — supervisor honors reader's
    self-declared incomplete analyses.
  - `feat/prompt-injection-isolation-reader` — severity is now
    higher; routing decisions depend on text influenced by
    arXiv PDFs.
