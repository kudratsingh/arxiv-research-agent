# Planner agent

Decomposes the user's research question into 2-4 focused sub-questions
and 1-2 targeted arXiv search queries per sub-question. First node in
the fixed pipeline; the `plan` action in the supervisor loop. Also the
HITL breakpoint: when `settings.enable_hitl` is on, the workflow
interrupts right after this agent so a human can review + edit the plan
before search runs (ADR
[0030](../decisions/0030-hitl-plan-review.md)).

Source: `src/agents/planner.py`.

## Inputs

Reads from `ResearchState`:

- `query` — the user's research question. The only required field.
- `prior_context` — conversation mode only (ADR
  [0032](../decisions/0032-conversation-mode.md)): top-K chunks
  retrieved from the thread's prior reports, injected by the API
  runner before the workflow starts. Blank outside conversations.
- `critique` — previous critic feedback, if any. Included verbatim so
  the revision addresses it.
- `iteration` — when `> 0`, the prompt states which revision round
  this is.

## Outputs

Writes to `ResearchState`:

- `sub_questions: list[str]` — 2-4 focused sub-questions.
- `search_queries: list[str]` — concise keyword phrases for arXiv.
- A `messages` entry (`AIMessage` named `"planner"`) with the counts.

## Prompt design

**System** (`SYSTEM_PROMPT`): role + the decomposition rules (cover
methods / theory / applications / benchmarks / recency angles; search
queries are keyword phrases, not sentences) + the JSON response schema
`{sub_questions, search_queries}`. When the state carries
`prior_context` **and** `settings.enable_prompt_isolation` is on,
`PRIOR_CONTEXT_ISOLATION_INSTRUCTION` is prepended — prior reports were
synthesized from untrusted paper text, so a cross-turn injection could
otherwise steer this run's plan (ADR
[0033](../decisions/0033-safety-hardening-bundle.md)).

**User**: the research question, then (in order):

- `prior_context`, wrapped in untrusted-content tags when isolation is
  on, positioned *above* the critique so the model treats it as
  background rather than corrective feedback. The instruction tells the
  model to avoid re-researching covered ground and to target the gaps
  the follow-up asks about.
- The previous critique, if any.
- The revision-iteration note, if `iteration > 0`.

## Known failure modes

| Failure | Where | Handling |
|---|---|---|
| Anthropic 429 / 5xx | SDK layer | Retried by the SDK (`anthropic_max_retries`, ADR 0009); exhausted retries propagate — a transport failure is not a formatting hiccup. |
| Response not JSON / not an object | `planner_agent` (ADR 0041 parse defense) | Logged at WARNING (`planner_response_unparseable` / `planner_response_not_an_object`) and treated as an empty plan — see the next row. |
| Missing / empty / wrong-typed `sub_questions` or `search_queries` | `planner_agent` | Falls back to the user's **raw query** as the single sub-question and search query, logged as `planner_plan_fallback_to_query` (ADR 0041). The pipeline runs an honest, shallower search rather than failing the job at its cheapest stage. |
| Prompt injection via `prior_context` | Cross-turn (ADR 0033) | Mitigated behind `enable_prompt_isolation`: wrap + system instruction. Off by default. |

The fallback is the raw query, never a fabricated decomposition: a
degraded plan is visibly shallow (one sub-question) rather than
plausible-looking garbage, and the WARNING makes the degradation
greppable. (Before ADR 0041 a malformed response propagated and
failed the whole job.)

## Configuration

Settings that drive the planner (see `src/config.py`):

- `planner_model: str = ""` — per-agent model override (ADR 0021).
  Empty falls back to `anthropic_model`.
- `enable_prompt_caching: bool = False` — marks the system prompt for
  Anthropic's ephemeral cache (ADR 0022).
- `enable_prompt_isolation: bool = False` — gates the prior-context
  wrapping described above (ADR 0033).
- `enable_hitl: bool = True` — the post-planner interrupt lives in the
  workflow wiring, not here, but it is this agent's output the human
  reviews (ADR 0030).

## Testing

- Unit: `tests/test_planner_prior_context.py` — prompt-builder
  coverage: prior-context block presence/absence, ordering relative to
  the critique, isolation wrapping on/off, system-prompt shape, and
  full-agent behavior with `call_llm_json` monkeypatched.
- Parse defense: `tests/test_parse_defense.py::TestPlannerParseDefense`
  — unparseable / non-object / wrong-typed responses all degrade to
  the raw-query plan instead of raising (ADR 0041).
- LLM-call plumbing: `tests/test_agent_model_routing.py` (the
  `planner_model` override) and `tests/test_agent_cache_flag.py` (the
  prompt-caching flag).
- Plan-review flow (edited sub-questions / search queries resuming the
  workflow): `tests/test_api_hitl.py`.
