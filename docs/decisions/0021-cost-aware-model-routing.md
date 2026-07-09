# 0021. Cost-aware model routing: per-agent Claude model overrides

- **Status**: accepted
- **Date**: 2026-07-08
- **Depends on**: ADR
  [0001](0001-use-anthropic-sdk-directly.md),
  [0011](0011-pydantic-settings-typed-config.md)

## Context

Sprint 1 wired every agent to a single model via `settings.anthropic_model`
(default: `claude-sonnet-4-6`). That was the right starting point —
one lever, easy to reason about. Sprint 2 shipped seven agents, most
of them with quite different task shapes:

| Agent | Task | Volume | Judgment intensity |
|---|---|---|---|
| Planner | Decompose query | 1 call / run | Medium |
| Reader | Per-paper extraction | Up to 10 calls / run | Low |
| Synthesizer | Report writing | 1–3 calls / run | High |
| Critic | Quality scoring | 1–3 calls / run | High |
| Verifier | Faithfulness judge | ≤ N calls / loop | High |
| Supervisor | Routing decision | ≤ 20 calls / loop | Low |
| Query refiner | Rewrite queries | ≤ N calls / loop | Medium |

Anthropic's pricing sits at roughly:

- Haiku 4.5 — cheapest, fastest, good at structured extraction and
  short generation.
- Sonnet 4.6 — mid-tier; today's `anthropic_model` default; balanced
  quality/cost.
- Opus 4.7 — highest quality; expensive; best for judgment-heavy
  tasks where a marginal quality bump pays for the cost.

Running everything on Sonnet leaves cost on the table. Reader alone
is 60%+ of a typical run's spend (one call per paper). Supervisor is
a distant second under the loop. Both of those are exactly the
tasks Haiku is tuned for. Meanwhile the critic and verifier are
judgment tasks where Sonnet or Opus is probably worth it.

Sprint 3 item in [`planning/03-roadmap.md`](../../planning/03-roadmap.md)
calls this out as **cost-aware model routing: Haiku for extraction,
Sonnet for synthesis, Opus for critic**. The plumbing is already
there — `src/llm.py::call_llm_json` accepts `model_name`. What's
missing is per-agent configuration and a documented recommendation.

## Decision

Add seven per-agent model-override fields to `Settings`, each a
`str` defaulting to `""`. Every agent reads its own field and passes
`model_name=settings.<agent>_model or None` into its
`call_llm_json` invocation:

```python
# src/config.py
reader_model: str = ""
planner_model: str = ""
synthesizer_model: str = ""
critic_model: str = ""
verifier_model: str = ""
supervisor_model: str = ""
query_refiner_model: str = ""
```

**Default behavior is unchanged.** Empty string → `None` →
`call_llm_json` uses `settings.anthropic_model` — byte-identical to
Sprint 1 / Sprint 2. This ADR ships the config knobs and the
recommended mapping, not a new default.

### Recommended per-agent mapping

For deployment with `enable_supervisor` on, we recommend:

| Agent | Model | Why |
|---|---|---|
| Reader | `claude-haiku-4-5-20251001` | Structured extraction, Haiku's sweet spot. Highest per-run volume — biggest cost lever. |
| Supervisor | `claude-haiku-4-5-20251001` | Short routing decision, ≤ 512 output tokens. Fast responses matter for loop latency. |
| Query refiner | `claude-haiku-4-5-20251001` | Short generation task. |
| Planner | `claude-sonnet-4-6` (default) | Decomposition benefits from stronger reasoning; volume is low. |
| Synthesizer | `claude-sonnet-4-6` (default) | Report writing benefits from stronger prose. |
| Verifier | `claude-sonnet-4-6` (default) | Faithfulness judgment; ADR 0007 was calibrated on Sonnet. |
| Critic | `claude-sonnet-4-6` (default) | Quality judgment. |

The critic and verifier are the two agents where a Sonnet→Opus
upgrade might be worth measuring — both are judgment-heavy — but
Sonnet has been the calibration baseline for every eval to date, so
we default them to Sonnet and leave Opus as an opt-in.

### Rejected: shipping the recommended mapping as defaults

The recommended mapping would give a large day-one cost cut, but it
also shifts the workflow's baseline behavior in ways that confound
Sprint 2's flag-A/B story. Every Sprint 2 configuration was measured
with everything on Sonnet; changing the default now would mean every
regression-diff comparison also captures a model-swap effect. Ship
the knobs; document the recommendation; flip the defaults in Sprint
4 after paired-diff eval runs confirm quality holds.

## Alternatives considered

**Ship a single `enable_haiku_reader: bool` flag rather than a
full override surface.** Simpler API. Rejected because it's the
wrong abstraction — the shape we want is "each agent picks its own
model", not "reader-vs-not". Adding one flag per agent-model pair
would explode; adding one string per agent is the natural
factoring.

**Add a helper `resolve_agent_model(agent_name)` that centralizes
the fallback.** Considered. Rejected as over-engineering: each call
site is one line (`model_name=settings.reader_model or None`), and
inline reads more clearly at each agent than a shared helper that
adds an import + indirection.

**Wire a per-agent budget in tokens or dollars** so cost caps apply
per-agent, not just per-workflow. Rejected as scope creep — the
supervisor already caps per-workflow spend via `max_cost_usd`
(ADR 0014), and per-agent caps aren't required to route models.
Follow-up work once we have per-agent cost telemetry.

**Route models based on task detected from the state** (e.g., "if
the report is short, use Haiku"). Rejected as YAGNI — the per-agent
mapping is stable enough that dynamic routing would just add
non-determinism.

**Use LiteLLM or a routing library instead of hard-coded Claude
model IDs.** Rejected — ADR 0001 says we use the Anthropic SDK
directly. Adding a routing layer would undo that choice.

## Consequences

**Wins**

- Reader can move to Haiku with one env-var change — the largest
  cost lever unlocked with zero code diff at deploy time.
- Supervisor and query refiner can also drop to Haiku, cutting loop
  cost tax by roughly half.
- Judgment-heavy agents (critic, verifier, synthesizer) stay on
  Sonnet by default; users who want to trial Opus can with a single
  config change.
- Cost accumulator (ADR 0012) already tracks per-model, so
  per-model breakdown in `summary.jsonl` doubles as per-agent
  breakdown once overrides diverge.
- No refactor required — call sites take one keyword each.

**Tradeoffs**

- Seven new config fields to document and audit. Kept minimal by
  co-locating them in one block in `src/config.py` and one section
  in this ADR.
- Test stubs for `call_llm_json` had to grow a `model_name=None`
  keyword. Small, mechanical change; done in this PR.
- Users who don't set overrides continue paying Sonnet prices for
  the reader — the interview-signal recommendation is documented
  here but not defaulted in code. Sprint 4 flips defaults.
- Per-agent cost debugging still requires cross-referencing
  per-model cost breakdown against the recommended mapping. A
  future observability follow-up (per-agent tagging on cost calls)
  would close that gap.

**Non-goals (deferred)**

- Changing the default `anthropic_model` for any agent — Sprint 4.
- Per-agent budget enforcement.
- Automatic routing based on state / cost telemetry.
- Prompt caching (Sprint 3, separate ADR).
