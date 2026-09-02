# Per-session cost accounting and cap enforcement

Gate W1's row:

> Per-session cost accounting reconciles; cap enforcement proven |
> deterministic tests | W06

**Resolved.** Six deterministic tests, no model call, no network.
`tests/test_session_cost_cap.py` — **6 tests**, `--collect-only` on `3ccb650`.
Produced by **WO-W06**, PR
[#144](https://github.com/kudratsingh/arxiv-research-agent/pull/144), merged
`2114c47` on 2026-09-01. ADR **0062**.

---

## 1. The settings, and their defaults

| Setting | Env | Default | What it is |
|---|---|---|---|
| `learning_session_max_cost_usd` | `LEARNING_SESSION_MAX_COST_USD` | **0.50** | per-session ceiling. Research jobs continue on `MAX_COST_USD` |
| `learning_session_cost_cap_behavior` | `LEARNING_SESSION_COST_CAP_BEHAVIOR` | **`refuse`** | at-cap product behaviour: `refuse` or `degraded_close` |

Neither is a feature flag — see [`flags.md`](flags.md) §1.
`test_session_cap_defaults_to_conservative_refusal` (`:163`) pins both defaults,
which is the honest reading of "conservative": the default is to stop, not to
close with less.

## 2. Accounting reconciles

`test_successful_mock_accounting_reconciles_to_the_cent` (`:131`) drives a
workflow that bills `0.04` then `0.05` through the real pre-call choke point and
asserts on the persisted job:

```python
assert round(job.cost_usd or 0.0, 2) == 0.09
assert job.llm_calls == 2
```

To the cent, and the call count beside it.

## 3. Cap enforcement, both behaviours

`test_both_at_cap_behaviors_are_explicit_and_make_no_next_call` (`:80`) is
parametrized over both:

| behaviour | job status | `cost_cap_status` | `error_type` |
|---|---|---|---|
| `refuse` | `failed` | `"refused"` | `session_cost_cap_refused` |
| `degraded_close` | `succeeded` | `"degraded_close"` | `None` |

In both rows the test asserts **`workflow.client_constructed is False`** — the
cap fires *before* the next call is constructed, so "enforced" means the money
was not spent rather than that it was noticed afterwards. It also asserts the
persisted totals (`cost_usd == 0.55`, `llm_calls == 2`), that
`cost_cap_message` names the `$0.50 cost limit` and says no further work will
happen, and that the **terminal SSE frame** carries `cost_cap_status`,
`cost_usd` and `llm_calls` — so the learner-facing surface is told the same
fact the store holds.

## 4. The cap does not bleed

`test_session_cap_does_not_bleed_into_research_kind` (`:114`) runs both job
kinds against one settings object: the session job fails at `$0.50`, the
research job succeeds at `$0.55` with `cost_cap_status == ""` and its client
constructed. One choke point, two ceilings, no cross-talk.

## 5. Unpriced routes warn rather than silently price at zero

`test_unpriced_tutor_route_warns_instead_of_silently_unpricing` (`:149`) sets
`tutor_model="claude-tutor-new-99"` and asserts `unpriced_models()` reports it
and that exactly one `unknown_model_pricing_fallback` warning names it. A
model with no price entry would otherwise reconcile to `$0.00` — which is the
failure mode that would make every number in this file meaningless.

## 6. Where the harness's own money is kept separate

**ADR 0050** splits product spend from harness spend, and WO-W10 added a third
payer column. `simulate_learner`'s `summary.jsonl` carries:

- `cost_usd` — **the session graph. The product.** The only column that may
  ever be quoted as what a guided read costs a learner.
- `learner_cost_usd` — the simulated learner. Harness.
- `judge_cost_usd` — the judges. Harness.
- their sum, which is what `--max-budget-usd` counts against, *"because it is
  money whichever side of the boundary it sits on"* (PR
  [#145](https://github.com/kudratsingh/arxiv-research-agent/pull/145)).

The regression differ tabulates all three and gates **only** `cost_usd`;
`TestLearningLaneHarnessCostIsNotGated` proves a 100× judge-cost rise does not
fail a run. Coordinator ruling: **no ADR for the third payer column — it is an
application of ADR 0050.**

## 7. What this row does not prove

**Every figure above is a mock-mode figure.** The measured mean `cost_usd`
across the 15-scenario CI campaign is `$0.0000`
([`artifacts/scripted-simulation-summary.md`](artifacts/scripted-simulation-summary.md)),
because nothing was bought. The plan's estimate of **$0.07 – $0.17** per
session (`01-LEARNING-AGENT.md` §6.1, "Session online total") is printed beside
it in that artifact and is labelled **not a measurement** in the row itself.

The reconciliation proves the *arithmetic and the choke point*. It does not
prove the *price*. Nothing in this repository has ever measured what a guided
read costs — [`known-gaps.md`](known-gaps.md) §2.
