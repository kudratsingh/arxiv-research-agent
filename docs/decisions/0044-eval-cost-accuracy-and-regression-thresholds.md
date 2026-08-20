# 0044. Refresh the price table and split the regression gate by metric class

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: maintainer

## Context

Two accuracy problems in the eval/cost stack, surfaced by the August
2026 audit.

**The price table was a model generation stale.** ADR 0012 hardcoded
`PRICES_USD_PER_MILLION` at project inception and accepted price drift
as a reporting-only risk. Two things changed since. First, the prices
actually drifted: Anthropic's published list price for
`claude-opus-4-7` is $5/$25 per 1M tokens (the table said $15/$75 —
3x high) and `claude-haiku-4-5` is $1/$5 (the table said $0.80/$4 —
20% low). Second, ADR 0033 wired the same accumulator into
`max_cost_usd` enforcement, so a wrong price is no longer a wrong
report line — it's a wrong control-plane decision. An operator
following ADR 0021's routing recommendations with an Opus critic
would hit `CostBudgetExceeded` at roughly a third of their real
budget; the Haiku reader — the highest-volume agent — under-billed
20%. The current model generation (`claude-opus-5`, `claude-opus-4-8`,
`claude-sonnet-5`) and the bare `claude-haiku-4-5` id were absent
entirely, falling through to the Sonnet-priced fallback.

**The nightly gate fired on ordinary variance.** ADR 0010 chose a
single global `--threshold` of 0.10, justified as "score deltas below
10 points are typical metric-noise on LLM-as-judge outputs" — a
rationale about 0-1 judge scores. But `METRIC_FIELDS` also carries
`iterations`, `llm_calls` (raw counts) and `cost_usd` (dollars), and
`_is_regression` compared all of them against the same scalar. At the
CI's live 0.10, one extra LLM call (+1.0), one extra critic revision
(+1.0), or eleven cents of cost drift each failed the nightly. Those
events are ordinary run-to-run variance in a system with live arXiv
retrieval, sampling temperature, and a critic that decides revisions —
so the gate was chronically red and a real `citation_accuracy -0.15`
night would land in an already-ignored alert. ADR 0010 itself
anticipated this: "tighten per-metric when we have real data."

## Decision

**Prices.** Re-verify `PRICES_USD_PER_MILLION` against Anthropic's
published pricing (via the maintained API reference, not memory):
Opus tier (`claude-opus-5`, `-4-8`, `-4-7`, `-4-6`) at $5/$25, Sonnet
tier (`claude-sonnet-5`, `-4-6`) at $3/$15, Haiku 4.5 (bare id and the
ADR 0021 dated id) at $1/$5. Cache multipliers stay at 10% read /
125% write — unchanged upstream. A `PRICES_LAST_VERIFIED` date
constant sits next to the table so staleness is visible at review
time; time-limited intro promos are ignored so we over- rather than
under-report. Unknown models keep the existing warn-per-call +
Sonnet-fallback behaviour (ADR 0012) — loud wrongness beats silent
zero. A test asserts the table covers every `claude-*` default in
`Settings` (base model plus all per-agent routing fields), so
onboarding a new model id without pricing it fails CI.

**Gate.** Judge metrics by class, direction-awareness preserved:

- *Score metrics* (0-1 judge outputs) keep ADR 0010's absolute
  epsilon, still overridable via `--threshold` (default 0.10).
- *Resource metrics* get per-metric two-leg bands in
  `RESOURCE_THRESHOLDS: {field: (absolute_floor, relative_fraction)}`
  — a rise regresses only when it exceeds **both**. `iterations`:
  (+1, +50%); `llm_calls`: (+4, +25%); `cost_usd`: (+$0.10, +25%).
  The floor stops single-unit and penny wiggles on small baselines;
  the relative leg stops proportionally-tiny drift on large ones.
  When the baseline is 0 or missing, the floor alone decides. The
  25% cost band implements the "cost creep > 25%" gate the README
  has documented since ADR 0012's follow-up.

`--threshold` no longer touches resource metrics — the CI workflow's
`--threshold 0.10` keeps its ADR 0010 meaning without a workflow
change.

## Alternatives considered

- **Prices in `Settings`** (ADR 0012's `feat/prices-in-settings`) —
  still the right follow-up, but orthogonal: an overridable table
  that ships wrong numbers is still wrong out of the box. Correct
  the data first; the override mechanism remains tracked.
- **Drop resource metrics from the gate entirely** (informational
  rows only) — loses the one genuinely valuable resource alarm:
  call/iteration runaway from a loop bug, and the documented cost
  creep gate. Bands keep the alarm and remove the noise.
- **Gate on aggregate means instead of per-query** — averaging 20
  queries does shrink judge noise, and it's the statistically better
  design for score metrics. Rejected for now because it changes what
  a red nightly *means* (per-query diagnostics would no longer gate)
  and deserves its own decision once a 3-repeat baseline quantifies
  the noise it would be tuned against. Documented as the measured
  path in docs/eval.md.
- **Thresholds from measured variance** — the honest ideal; nothing
  in `src/eval` measures run-to-run spread yet. The bands are
  explicitly priors sized from mechanics (one critic revision ≈ 2-3
  calls; one extra paper ≈ 1 call) and are to be re-derived from a
  3-repeat baseline run when we invest in one.

## Consequences

- **Positive**:
  - `job.cost_usd` and `max_cost_usd` enforcement price Opus 3x
    lower and Haiku 20% higher — i.e. correctly; ADR 0021 routing no
    longer trips the cost cap on phantom spend.
  - The nightly stops crying wolf: +1 call, +1 revision, or penny
    drift can no longer produce a red run, so a red run regains
    meaning.
  - Price staleness is now caught two ways: the coverage test fails
    when config routes to an unpriced model, and
    `PRICES_LAST_VERIFIED` makes table age visible in review.
- **Negative**:
  - The bands are priors, not statistics — they can still be wrong
    in both directions (a real +20% cost regression on an expensive
    run stays green; correlated noise across legs could still fire).
    docs/eval.md states the limits plainly.
  - Prices remain hardcoded; a price change still requires a release
    until `feat/prices-in-settings` lands.
  - Score-metric quantization (completeness/recall step ≈ 0.25) is
    documented but not fixed — the epsilon is still inoperative for
    those two metrics per-query.
- **Follow-ups**:
  - `feat/prices-in-settings` — unchanged from ADR 0012.
  - 3-repeat baseline run against an unchanged `main`; re-derive all
    thresholds from measured per-metric spread.
  - README's regression-gate line should cite this ADR alongside
    ADR 0010.
