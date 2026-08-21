# Critic agent

Evaluates the synthesized draft and decides whether another revision
round is worth it — and if so, which agent should run again. Last node
in the fixed pipeline, where its `revision_target` drives the only
conditional edge; the `critique` action in the supervisor loop, where
its scores feed the supervisor's stop condition instead.

Source: `src/agents/critic.py`.

## Inputs

Reads from `ResearchState`:

- `query` — the research question the report must answer.
- `paper_analyses` — titles listed in the prompt so the judge knows
  what evidence base the draft had to work with.
- `draft_report` — the full draft under evaluation.
- `iteration` — current revision count; used for the force-approve cap.

## Outputs

Writes to `ResearchState`:

- `critique: str` — specific, actionable feedback.
- `quality_score: float` — the average of the five dimension scores.
- `revision_needed: bool` / `revision_target: str` — the routing
  decision (`planner` / `search` / `synthesizer`, or `""` on approve).
- `iteration: int` — incremented by 1.
- A `messages` entry (`AIMessage` named `"critic"`) with score, status,
  and `iteration/max_iterations`.

## Scoring rubric

Five dimensions, each 0.0-1.0, defined in `SYSTEM_PROMPT`:
completeness, accuracy, coherence, depth, balance. The routing rules
are stated to the judge directly:

- average >= 0.7 → approve (`revision_needed: false`).
- Missing topic coverage → `revision_target: "planner"`.
- Too few papers or weak evidence → `revision_target: "search"`.
- Weak synthesis, structure, or citations → `revision_target: "synthesizer"`.

## Iteration cap

After the LLM verdict, the agent force-approves when
`iteration >= settings.max_iterations` — `revision_needed` is
overridden to `False` regardless of score. This is the fixed
pipeline's loop-termination guarantee: without it, a persistently
low-scoring draft would cycle forever. (The supervisor loop has its
own independent caps — `max_loop_iterations` and `max_cost_usd`.)

Downstream, `route_after_critique` (`src/graph/workflow.py`) routes to
the named target only when `revision_needed` is true **and** the
target is one of the three valid nodes; anything else falls through to
`END`. A malformed `revision_target` therefore ends the run with the
current draft rather than crashing.

## Known failure modes

| Failure | Where | Handling |
|---|---|---|
| Anthropic 429 / 5xx | SDK layer | Retried by the SDK (ADR 0009); exhausted retries propagate — no fallback verdict is fabricated for a transport failure. |
| Response not JSON / not an object | `critic_agent` (ADR 0041 parse defense) | Logged at WARNING (`critic_response_unparseable` / `critic_response_not_an_object`) and coerced to safe defaults: **approved with score 0.0**. The critic is the terminal node — a formatting hiccup here must never discard the finished report the run already paid for. The zero score keeps the degradation honest in the summary line. |
| Wrong-typed fields (string score, non-`true` `revision_needed`) | `_safe_float` / literal-`true` check | Coerced with a WARNING; only a literal JSON `true` triggers revision. |
| `revision_needed` with an unroutable `revision_target` | `critic_agent` | `critic_revision_target_invalid` WARNING; revision cancelled — deliver the report rather than spin a round the graph cannot route. |
| `revision_target` outside the enum (stale checkpoint) | `route_after_critique` | Falls through to `END` — run finishes with the current draft. |
| Score inflation / judge drift | Not handled here | The offline eval metrics (`src/eval/metrics.py`) score the same reports independently, so systematic critic drift shows up in the nightly regression diff. |
| Injected paper text steering the verdict | Prompt path | Paper *titles* and the draft are in the prompt; reader-side isolation (ADR 0020) scrubs upstream, but the critic's own prompt is not yet tag-wrapped — same follow-up as the synthesizer/verifier (ADR 0020 non-goals). |

## Configuration

Settings that drive the critic (see `src/config.py`):

- `max_iterations: int = 3` — hard cap on critic-driven revision
  loops.
- `critic_model: str = ""` — per-agent model override (ADR 0021).
  Empty falls back to `anthropic_model`.
- `enable_prompt_caching: bool = False` — system-prompt caching (ADR
  0022).
- `min_quality_score: float = 0.75` — **supervisor-loop only**: the
  supervisor's stop threshold reads the critic's `quality_score`; the
  0.7 approve bar inside the critic's own prompt is independent of it.

## Testing

- Routing: `tests/test_smoke.py` — `route_after_critique` (approve →
  END, each valid target, invalid target → END, missing fields → END).
- Parse defense: `tests/test_parse_defense.py` — unparseable /
  non-object / wrong-typed judge output degrades to approved-with-
  zero-score instead of raising (ADR 0041).
- LLM-call plumbing: `tests/test_agent_model_routing.py` (the
  `critic_model` override) and `tests/test_agent_cache_flag.py` (the
  prompt-caching flag), both with `call_llm_json` monkeypatched.
- **Gap**: the force-approve-at-cap branch has no dedicated unit test
  today — a good first test for anyone touching this agent.
- Judge quality itself is guarded by the nightly eval, not unit tests.
