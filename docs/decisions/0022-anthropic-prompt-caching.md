# 0022. Anthropic prompt caching for agent system prompts

- **Status**: accepted
- **Date**: 2026-07-09
- **Depends on**: ADR
  [0001](0001-use-anthropic-sdk-directly.md),
  [0009](0009-anthropic-sdk-native-retry.md),
  [0012](0012-observability-core-logging-costs.md),
  [0021](0021-cost-aware-model-routing.md)

## Context

Every agent's `call_llm_json` currently sends the same system prompt
every call. That's fine when call volume is 1–3 per run (planner,
synthesizer, critic), but Sprint 2 landed two shapes where the same
system prompt fires many times per run:

- **Reader** — one call per paper, up to `max_papers=10`, all
  concurrent. Same system prompt every time (base analysis prompt +
  optional evidence / recovery / isolation addenda).
- **Supervisor** — one call per action, up to `max_loop_iterations=20`,
  within seconds of each other. Same system prompt every turn.

Anthropic ships **ephemeral prompt caching**: mark content blocks
with `cache_control: {type: "ephemeral"}` and the tokens are cached
for 5 minutes. Subsequent hits within that window bill at **10% of
the input token price**; the first call that stores the cache
carries a **25% premium** on the cached portion. Real workloads see
30–90% cost reduction depending on hit rate and cache size.

Sprint 3 planning docs call for this. The reader and supervisor are
the obvious hit-rate wins; the other agents get the flag too for
uniformity and future benefit (a critic revision loop can hit cache
too).

Constraints:

1. **Baseline unchanged with the flag off.** Same rule as every
   Sprint 2/3 flag: default preserves Sprint 1 behavior byte-for-
   byte, opt-in flips the behavior.
2. **Sub-minimum content behaves gracefully.** Anthropic's
   documented minimums are 1024 tokens (Sonnet) and 2048 tokens
   (Haiku). Content below the minimum simply doesn't cache — the
   API silently returns no `cache_creation_input_tokens`, no
   `cache_read_input_tokens`. Marking small system prompts costs
   nothing.
3. **Cost telemetry stays accurate.** The existing per-run cost
   accumulator (ADR 0012) needs new buckets for cache-read and
   cache-creation tokens so `summary.jsonl` reflects reality when
   caching is on.

## Decision

Extend `src/llm.py::call_llm` with a new keyword `cache_system:
bool = False`. When true, the system prompt is passed to the
Messages API as a single content block:

```python
system = [
    {
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }
]
```

Anthropic returns `usage.cache_read_input_tokens` and
`usage.cache_creation_input_tokens` on the response; both are read
via `getattr(..., 0)` so an older SDK that lacks the field doesn't
break the caller. Both values are forwarded to `record_llm_call`,
which threads them into `RunCosts.record` and `estimate_cost`.

Add config: `enable_prompt_caching: bool = False`. Each of the seven
agents passes `cache_system=settings.enable_prompt_caching` when
invoking `call_llm_json`. One line per agent, no per-agent
override — either the whole workflow uses caching or none of it
does. This is deliberate: fine-grained per-agent caching is
premature until we see paired-diff numbers showing which agents
actually benefit.

### Cost math

`estimate_cost` picks up two multipliers keyed off the base input
price for the model:

```python
_CACHE_READ_MULTIPLIER = 0.10
_CACHE_WRITE_MULTIPLIER = 1.25
```

Applied against a Sonnet input price of $3/M:

- Regular input: $3.00 / 1M tokens
- Cache read: $0.30 / 1M tokens
- Cache write (first time): $3.75 / 1M tokens
- Output: unchanged

The three input buckets are additive at billing time and appear
individually in `summary.jsonl` under
`total_cache_read_input_tokens` and
`total_cache_creation_input_tokens` (per-run and per-model). A
future observability follow-up can compute a "cache hit rate"
metric from those buckets; not shipped here because we want to see
real workload numbers first.

### Which agents benefit

Rough hit-rate expectations per agent when the flag is on:

| Agent | Calls per run | System prompt stability | Expected hit rate |
|---|---|---|---|
| Reader | 5–10 (parallel fan-out) | Stable per run | High after first call |
| Supervisor | 5–20 (sequential) | Stable per run | Very high |
| Verifier | 1–3 | Stable per run | Medium (revisions) |
| Critic | 1–3 | Stable per run | Medium |
| Synthesizer | 1–3 | Stable per run | Medium |
| Query refiner | 0–2 | Stable per run | Low (few calls) |
| Planner | 1–2 | Stable per run | Low |

The reader and supervisor drive the interesting savings; the
others benefit modestly from the second call onward inside a 5-
minute window.

### Below-minimum content

Sonnet requires ≥ 1024 tokens for a cache block, Haiku ≥ 2048.
Several of our system prompts sit below that today (planner,
critic core, base reader). When the API sees a cache-marked block
below the minimum, it silently caches nothing:
`cache_creation_input_tokens = 0`, `cache_read_input_tokens = 0`,
tokens billed at the normal input rate. **Marking small prompts is
a no-op, not an error.** We do not try to detect and skip below-
minimum content client-side; the API handles it correctly and any
size heuristic we wrote would drift as prompts grow.

## Alternatives considered

**Cache the user message too, not just the system prompt.** The
reader's user prompt is per-paper (varies every call); caching it
would produce all writes, no hits. The supervisor's user prompt is
a per-turn state summary that also varies. Both cases don't
benefit. The verifier's dossier is stable-ish but the report
inside it changes across revisions, so the boundary between
cacheable and non-cacheable would need surgical block splitting.
Deferred until we have workload numbers that motivate the extra
complexity.

**Per-agent `enable_<agent>_caching` flags.** Symmetric with the
per-agent model overrides in ADR 0021. Rejected as premature —
seven flags to document and audit, all likely default to the same
value. Ship one flag; split later if paired-diff data ever shows
one agent needs different behavior.

**Automatic caching everywhere by default.** Would require flipping
the flag on unconditionally. Rejected on baseline grounds: Sprint 2
eval comparisons were done without caching, and moving the default
now would confound the flag-A/B story. Same argument as ADR 0021's
"ship the knobs, keep defaults" stance. Sprint 4 will flip
defaults once paired-diff runs confirm behavior.

**Use Anthropic's `1h` cache TTL (beta).** Longer TTL, better hit
rate. Rejected because it's still beta at project inception; the
5-minute `ephemeral` cache is GA and matches our runtime shape
(one workflow completes in well under 5 minutes).

**Write a cache client wrapper that batches metrics locally rather
than trusting the API response.** Over-engineering. The API's
`usage` fields are the source of truth for billing; anything we
count locally would just re-derive them.

## Consequences

**Wins**

- 30–90% input cost reduction on the reader (parallel fan-out) and
  supervisor (loop iterations) when the flag is on, depending on
  system prompt size and cache hit rate.
- Cost accumulator now surfaces cache-read and cache-write buckets
  per model, giving eval / operators visibility into how much cache
  actually fired.
- Small blast radius: 7 agents × 1 line each, one new config
  field, no new dependencies. Backwards compatible: existing
  callers of `call_llm` / `call_llm_json` / `record_llm_call` /
  `estimate_cost` are unaffected.

**Tradeoffs**

- Sub-minimum system prompts don't cache but pass through the
  marker anyway. The API bills correctly (normal input rate); no
  wasted spend, just no savings.
- Cache-write premium (25%) hits the first call of every run. If a
  workflow only ever fires one supervisor call (never happens in
  practice under the loop, but theoretically), the caching flag is
  a net loss. Bounded by the fact that supervisor loops always
  fire multiple times.
- Test infrastructure had to grow `cache_system` in the fake
  signatures; mechanical, same pattern as ADR 0021's `model_name`
  addition.
- `RunCosts` snapshot dict grew two new top-level and per-model
  fields. Downstream JSON consumers that hard-code the field list
  need to add these; the regression differ's field-tracking will
  need an update if we want it to catch cache-token creep as a
  regression signal (follow-up).

**Non-goals (deferred)**

- Extending caching to user-message content (verifier dossier,
  synthesizer evidence bank).
- Per-agent cache flags.
- Default-on with baseline shift (Sprint 4).
- Automated "cache hit rate" derived metric on `summary.jsonl`.
- Regression differ awareness of the new cache-token fields.
