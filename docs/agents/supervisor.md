# Supervisor agent

Chooses the next action in the research loop when
`settings.enable_supervisor` is `True`. Under the fixed pipeline
(the default) this agent is not instantiated.

Source: `src/agents/supervisor.py`. Design rationale: ADR
[0014](../decisions/0014-supervisor-loop-behind-flag.md).

## Inputs

Reads from `ResearchState`:

- `query` — the user's research question.
- `sub_questions` / `search_queries` — presence signals whether the
  planner has run.
- `papers` / `paper_analyses` — presence signals search / read progress.
- `draft_report` / `critique` / `quality_score` — synthesizer + critic
  progress.
- `revision_needed` / `revision_target` — from the critic; used by the
  rules-based fallback if the LLM returns garbage.
- `iteration` / `loop_iterations` — the two independent counters.
- Cost accumulator via `current_costs()` — for budget short-circuits.

## Outputs

Writes to `ResearchState`:

- `next_action: str` — one of `plan / search / read / synthesize /
  critique / stop`, plus `verify` when `enable_verifier` is on and
  `refine_query` when `enable_query_refiner` is on. Read by
  `route_after_supervisor`.
- `stop_reason: str` — populated only when `next_action == "stop"`.
  Known values: `quality_reached`, `budget_reached`,
  `max_iterations_reached`, `supervisor_stop`.
- `loop_iterations: int` — bumped by 1 on each supervisor call.
- A `messages` entry (`AIMessage` named `"supervisor"`) recording the
  decision + reason.

## Decision procedure

```
supervisor_agent(state):
    loop_iter = state.loop_iterations + 1

    # 1. Hard iteration cap — no LLM call.
    if loop_iter > settings.max_loop_iterations:
        return emit("stop", ..., "max_iterations_reached")

    # 2. Cost cap — no LLM call.
    if current_costs() >= settings.max_cost_usd:
        return emit("stop", ..., "budget_reached")

    # 3. Ask the LLM.
    try:
        parsed = call_llm_json(SUPERVISOR_PROMPT, _summarize_state(state))
    except Exception:
        return emit(_default_next_action(state), ..., "")

    # 4. Validate the response against VALID_ACTIONS.
    action = parsed.get("next_action", "")
    if action not in VALID_ACTIONS:
        return emit(_default_next_action(state), ..., "")

    # 5. Return the decision.
    return emit(action, ..., parsed.get("stop_reason", ""))
```

## Prompt shape

**System**: role + strict enum + `stop_when` list interpolated from
settings (`min_quality_score`, `max_cost_usd`, `max_loop_iterations`).
Response schema is `{next_action, reason, stop_reason}`; `stop_reason`
MUST be empty when not stopping.

**User**: compact state summary — counts of `sub_questions`, `papers`,
`paper_analyses`; presence flags for `draft_report`, `critique`;
current `quality_score`, `iteration`, `loop_iterations`, cost.
Critique text truncated to 200 chars so context stays cheap
(~300 tokens total).

## Fallback behavior — `_default_next_action`

Runs when:
- LLM raises
- JSON parse fails
- Response's `next_action` is missing or outside `VALID_ACTIONS`

Rules-based routing that mirrors the fixed pipeline order:

1. If `revision_needed` and under critic iteration cap → route to the
   critic's `revision_target` (`planner` / `search` / `synthesizer`).
2. Else, first empty field in the pipeline order wins: no
   `sub_questions` → `plan`; no `papers` → `search`; no
   `paper_analyses` → `read`; no `draft_report` → `synthesize`; no
   `critique` → `critique`.
3. Everything populated → `stop`.

## Known failure modes

| Failure | Where | Handling |
|---|---|---|
| Anthropic 429 after retries | `call_llm_json` (Anthropic SDK layer) | Caught here; falls back to `_default_next_action`. Logged as `supervisor_llm_failed_fallback_to_default`. |
| Malformed JSON | `call_llm_json` | Same — caught and fallback fires. |
| Response chose a disabled action (`verify` with `enable_verifier=False`, or any future flag-gated action) | Validation | Falls back to `_default_next_action`; logged as `supervisor_invalid_action_fallback` with the received value and the currently-available set. |
| Response chose an action outside `VALID_ACTIONS` entirely | Validation | Same fallback path. |
| Response returns `stop` with no `stop_reason` | Post-validation | Defaults to `supervisor_stop` so downstream analysis has a bucket. |
| Response returns non-stop action with a `stop_reason` | Post-validation | `stop_reason` cleared to empty. |
| Loop iterations exceed `max_loop_iterations` | Pre-LLM check | Returns `stop` with `stop_reason="max_iterations_reached"`. |
| Cumulative cost exceeds `max_cost_usd` | Pre-LLM check | Returns `stop` with `stop_reason="budget_reached"`. |
| Judge tries to redirect via prompt-injected paper text | Not yet mitigated | Called out in `planning/05-agentic-upgrade-plan.md` item 8 — reader-level isolation lands separately. |

## Configuration

Settings that drive the supervisor (see `src/config.py`):

- `enable_supervisor: bool = False` — master flag.
- `enable_verifier: bool = False` — adds `verify` to the action enum
  and wires the verifier node. Independent of `enable_supervisor` so
  the two can be A/B'd separately. See ADR 0015.
- `enable_query_refiner: bool = False` — adds `refine_query` to the
  action enum and wires the query_refiner node. Independent of every
  other Sprint 2 flag. See ADR 0018.
- `enable_reader_recovery: bool = False` — reader emits
  `analysis_complete` / `missing_context` / `request_more_sections`
  which surface on the supervisor state summary; the ranker biases
  re-reads toward the requested sections. Doesn't add a new action —
  the supervisor picks the existing `read` action to trigger a
  narrower re-read. See ADR 0019.
- `min_quality_score: float = 0.75` — mentioned in the prompt as a
  stop condition.
- `max_cost_usd: float = 2.00` — pre-LLM budget check.
- `max_loop_iterations: int = 20` — pre-LLM iteration check.

All env-overridable per ADR 0011.

## Testing

- Unit: `tests/test_supervisor.py` — 24 tests covering the
  rules-based fallback (each pipeline stage), the state summarizer,
  short-circuits (iteration cap + cost cap without LLM calls), the
  LLM path (valid action, stop-with-default-reason, stop-reason
  cleared on non-stop, invalid action, missing action, LLM exception,
  prompt shape), the router (every valid action + unknown fallback
  to `END`), and enum invariants.
- Integration: TODO once the first live run happens on the loop path.
- E2E: covered by the future workflow-level cassette suite.

## Follow-ups (tracked in `planning/05-agentic-upgrade-plan.md`)

- ~~`verify` action + verifier agent (item 4).~~ Landed — ADR 0015.
- ~~`EvidenceClaim` store + verifier judges chunks (item 5a).~~ Landed — ADR 0016.
- ~~Synthesizer reads from evidence (item 5b).~~ Landed — ADR 0017.
- ~~`refine_query` action + query refiner (item 6).~~ Landed — ADR 0018.
- ~~Reader-requests-more-chunks (item 7).~~ Landed — ADR 0019.
- Query refiner so "search again" is a real recovery action (item 6).
- Reader-requests-more-chunks (item 7).
- Prompt-injection isolation on the reader (item 8) — **severity
  upgraded** now that routing depends on paper text.
