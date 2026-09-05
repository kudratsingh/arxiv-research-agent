# 0077. Make the LLM gateway's request model-aware

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: Agent-capability lane (CAP-01)

## Context

[`src/llm.py`](../../src/llm.py) has been the choke point for spend
(ADR [0051](0051-llm-cost-enforcement-and-visibility.md)), retries,
cancellation (ADR [0047](0047-cooperative-cancellation.md)) and the
`chat` span (ADR [0066](0066-genai-semantic-conventions.md)). It has
never been a choke point for the *request*. Every call went out with
the same body:

```python
client.messages.with_raw_response.create(
    model=resolved_model,
    max_tokens=max_tokens,
    temperature=_TEMPERATURE,          # 0.3, a module constant
    system=_build_system_param(...),
    messages=[{"role": "user", "content": prompt}],
)
```

Four things follow from that, measured on `origin/main` at
`760efd0`:

**1. The gateway breaks the day the model id changes.** Opus 4.7 and
later, Opus 5, Sonnet 5, and the Fable/Mythos tier **reject** sampling
parameters with an HTTP 400. The shipped default is
`claude-sonnet-4-6`, the last generation that still accepts them, so
the fault is invisible today and total tomorrow: setting
`ANTHROPIC_MODEL=claude-opus-5` — a one-variable change ADR
[0021](0021-cost-aware-model-routing.md) explicitly invites, and one
`src/observability/costs.py` already prices — fails every call on every
node. The same is true one agent at a time through
`PLANNER_MODEL`/`READER_MODEL`/…

**2. Every structured agent pays for free-text JSON.** `call_llm_json`
obtains its dict with `json.loads`, then retries with `strict=False`.
Planner, critic, supervisor and verifier each carry a hand-written
recovery path for the times that fails (ADR
[0041](0041-retrieval-and-degradation-honesty.md)) — the planner degrades to
the raw query, the critic approves with a zero score. The API has
supported constraining generation to a schema for a year and this
repository has never asked it to.

**3. Nothing uses the cheapest test-time-compute lever there is.**
`docs/agent-engineering/02-target-architecture.md` §4 builds a compute
tier ladder and never names `output_config.effort`, which is one field
and moves thinking depth and token spend together within a single
model.

**4. Enabling thinking today would return empty strings.** Response
text came from joining `type == "text"` blocks, which is right — but a
response whose *only* block is a `thinking` block joined to `""`, and
`""` is what every caller would have received as the model's answer.
The planner would have fallen back to the raw query, the critic
approved at zero, and the run finished `succeeded` having been told
nothing.

The installed SDK (`anthropic==0.116.0`, pinned in both lockfiles)
already ships `output_config`, `effort`, adaptive thinking, and
`messages.parse`. Nothing here needs a dependency change.

## Decision

### 1. One table, and it is the only place a model id appears

[`src/llm_models.py`](../../src/llm_models.py) maps a model id to
`ModelCapabilities(sampling_params, adaptive_thinking, effort_levels,
structured_outputs, source)`. It is pure — no imports from `src/`, no
logging, no I/O — and it is the only file in `src/` outside the config
defaults that names a Claude model.

`effort_levels` is a set rather than the boolean the work order asked
for, because effort is not a yes/no: Haiku 4.5 rejects the field
outright, Opus 4.5 accepts `low`/`medium`/`high`, Sonnet 4.6 has no
`xhigh`, and Opus 4.7 and later take all five. A boolean would have
made `LLM_EFFORT=xhigh` on the *default model* a runtime 400 that no
load-time check could catch. `caps.effort` remains as the boolean
derived from it.

Resolution is exact id, then longest known-id prefix on a `-` segment
boundary (so `claude-haiku-4-5-20251001` and `claude-opus-5-1` inherit
their base model's surface, and `claude-opus-50` does not), then family
prefix, then a conservative row.

**Every guess guesses downwards.** A family row keeps that family's
current sampling answer and switches every opt-in feature off; the
conservative row sends nothing at all. The asymmetry is the argument:
guessing low costs a feature on a call that still works, guessing high
costs an HTTP 400 on every call. Those are not comparable.

### 2. A frozen profile per call, resolved from settings ∧ capabilities

`RequestProfile(model, temperature, adaptive_thinking, effort,
structured_outputs)` holds *answers*, not inputs — `None` and `""` mean
"do not send this field" — so `_build_request_kwargs` is a
transcription rather than a second place the enabled-and-supported
logic could drift. A feature is sent only when the operator enabled it
**and** the row allows it.

New `Settings` fields, all defaulting to today's behaviour:
`llm_thinking` (`off`), `llm_effort` (`""`), nine `<agent>_effort`
overrides, `enable_structured_outputs` (`False`), `llm_temperature`
(`0.3` — the constant `_TEMPERATURE` held, now a setting).

The per-agent overrides carry an `off` member the global field does
not. Without it, `LLM_EFFORT=high` plus ADR 0021's own recommendation
`READER_MODEL=claude-haiku-4-5` is a configuration with no expression
and no fix, because an empty override *inherits*. `off` is how one
agent opts out of an inherited level.

### 3. Thinking and effort are refused at load; temperature and schemas degrade

`Settings._check_request_profile_is_supported` raises `ValueError`
naming the field, the model, and what that model does accept, whenever
`llm_thinking` or an effort level is unsupported by a model it would
reach. `enable_structured_outputs` and `llm_temperature` are
deliberately not checked.

The line between them is whether there is a good runtime answer.
Thinking and effort have none — the call fails, on every node, for the
whole deployment, so a config that cannot make one successful request
should not start. Sampling and structured outputs both degrade to
exactly the pre-ADR-0077 behaviour. Refusing to boot over a feature
that has a working fallback would make the strict check
indistinguishable from a strictness preference.

### 4. Structured outputs go through `create`, not `messages.parse`

The SDK's documented path is `client.messages.parse(output_format=...)`,
which transforms the schema and validates the response in one call.
This gateway does not use it, and the reason is measured rather than
stylistic: in `anthropic` 0.116.0, `MessagesWithRawResponse` wraps only
`create` and `count_tokens`
(`.venv/.../anthropic/resources/messages/messages.py:3083`). There is
no `with_raw_response.parse`, and `raw.retries_taken` is ADR 0051's
entire retry-visibility fix. Calling `parse` would mean either losing
that or duplicating the span, cost-accounting and exception-mapping
block around a second call site.

So the schema is transformed with the SDK's own public
`anthropic.transform_schema` — the same function `parse` calls to build
`output_config.format` — sent through `create`, and validated here with
the same pydantic model. What reaches the wire is identical; what
reaches `record_llm_call` is not.

### 5. Schemas transcribe the prompts, and hide their own docstrings

[`src/agents/schemas.py`](../../src/agents/schemas.py) carries
`PlannerOutput`, `CriticOutput`, `SupervisorOutput`, `VerifierOutput`.
Every field name, type and enum member is what the agent's existing
`SYSTEM_PROMPT` already asks for; no prompt text moved.
`_hide_docstring_from_the_model` strips the class docstring from the
generated schema, because pydantic would otherwise ship this file's
internal notes to the model as `description` — prompt text arriving
through a side door, under a work order whose discipline is that prompt
wording does not move (ADR [0070](0070-eval-integrity-provenance.md)).

`SupervisorOutput.next_action` stays a plain `str`. Its prompt's enum
is built per call from `_available_actions()`, so a static enum would
either offer an action the deployment has disabled or forbid one it has
enabled.

The hand-written coercions in all four agents are **kept**. Structured
outputs remove the failure mode those coercions survive; they do not
remove the need to survive it, because the flag is off by default and
off on every unsupporting model.

### 6. Thinking blocks are skipped, and a text-free response now raises

`_text_of` joins `type == "text"` blocks and never reads or logs a
`thinking` block. A response with **no** text block raises
`UpstreamModelOutput` (ADR
[0064](0064-error-taxonomy-and-envelope.md)), the code for "the
provider answered and the content was unusable", after cost is
recorded — the call happened and Anthropic billed it whatever came
back.

## Alternatives considered

- **Send `temperature` only when the model is not in a deny-list.** A
  deny-list of models that reject sampling is the same table upside
  down, and it fails open: a model nobody has heard of gets the
  parameter and the 400. The table fails closed.
- **Read capabilities from `GET /v1/models/{id}`.** The API exposes
  exactly this (`ModelCapabilities` in the SDK's own types). Rejected:
  the check has to run at settings-load time, the suite is offline by
  construction (ADR
  [0065](0065-test-isolation-and-coverage-floor.md)), and a request
  shape that depends on a provider round-trip fails differently every
  time it is wrong. The endpoint is the right way to *re-verify* the
  table; `CAPABILITIES_LAST_VERIFIED` is the tripwire that asks someone
  to, exactly as ADR [0044](0044-price-table-refresh.md) does for
  prices.
- **`messages.parse`.** See §4 — it costs `retries_taken`.
- **A boolean `effort` capability.** See §1 — it cannot express
  `xhigh` on Sonnet 4.6.
- **Refuse to boot on unsupported structured outputs too.** See §3 —
  it has a fallback and they do not.
- **Delete the agents' hand-written coercions once schemas are on.**
  They are the default path's only defence and would have to come back
  the moment a deployment routes an agent to a model with no structured
  output support.

## Consequences

- **Positive.** Changing `ANTHROPIC_MODEL` to any priced model is now
  a working change rather than a total outage. Thinking, effort and
  structured outputs are each one environment variable, and each is
  refused at load or silently skipped rather than failing in
  production. Model quirks have one home with a verification date on
  it.
- **Negative — an unknown model id loses `temperature`.** Before this,
  an id outside the price table still received `temperature=0.3`; now
  it receives nothing. That is the conservative direction (an
  unrecognised id is more likely to be a newer model that rejects
  sampling than an older one that needs it), but it is a behaviour
  change for a deployment pointing at a proxy or a private id, and
  `undescribed_models()` is how such a deployment finds out.
- **Negative — schema violations become job failures on two nodes.**
  With `enable_structured_outputs` on, a response that does not satisfy
  the schema raises `upstream_model_output`. The verifier and
  supervisor absorb it into their existing fallbacks; the planner and
  critic catch only `json.JSONDecodeError`, so for them it ends the
  job. That is a *typed* failure in place of a silent degradation, and
  it only exists behind the flag.
- **Negative — turning thinking or effort on re-baselines every eval
  metric.** The judges in `src/eval/**` reach the provider through this
  same gateway, so a global `LLM_THINKING`/`LLM_EFFORT` changes the
  grader as well as the product. ADR 0070's rule applies: a regression
  diff across that change compares two different instruments. The
  per-agent overrides exist partly so the change can be made without
  moving the judges.
- **Follow-ups.**
  1. **`gen_ai.request.temperature` cannot yet be absent.** The
     conventions want the attribute omitted when no temperature was
     sent. `llm_span` takes a required `float`
     (`src/observability/tracing.py:642`) and sets the attribute
     unconditionally (`:676`), and `src/observability/**` is fenced for
     another lane's work orders. The attribute is therefore truthful on
     every model that accepts sampling and reports the
     configured-but-unsent value on one that does not. The fix is
     `float | None` in that signature plus a guarded `set_attribute`;
     `src/llm.py` then passes `profile.temperature` directly.
  2. **No WARNING names an undescribed model id.** ADR
     [0067](0067-correlation-context-and-log-contract.md) keeps a
     closed event registry in the same fenced package, so a new event
     name could not land with this change.
     `unknown_model_pricing_fallback` covers the same population in
     practice — `tests/test_llm_models.py` requires a capability row
     for every priced id — and `undescribed_models()` is the
     programmatic answer meanwhile.
  3. **Per-agent effort is not wired at the call sites.** The nine
     `<agent>_effort` fields are validated at load and honoured by
     `call_llm(agent=...)`, but no agent passes its name yet: this work
     order fences edits to the four structured agents to the schema
     argument alone. One keyword per call site finishes it, and the
     T0/T1 compute controller (CAP-04) is the work order that needs it.
  4. **Nothing here is verified against a live model.** Zero spend is a
     hard constraint of this lane. Every claim above is a claim about
     the *request shape*; that the provider accepts each shape is
     verified by CAP-06's funded smoke.
