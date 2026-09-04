# Runbook — cost-cap storm

Runs are hitting their spend ceilings, repeatedly. The caps are working;
that is what a storm *is*. The incident is not "the cap fired", it is
"the work now costs more than the cap allows", and the two have entirely
different fixes.

Read this alongside [`pilot.md`](pilot.md) §3, which is where the
worst-case arithmetic lives. The sentence that page ends on is the one
to carry into this one: **the per-run caps bound one job, and nothing
bounds the sum.** There is no aggregate spend control in this repository
(MT-01 F4, Phase L0-01). The only aggregate control that exists is the
account-level limit on the provider side, and the only one you have
locally is stopping the workers.

## 1. The signal

| Signal | Where | What it means |
|---|---|---|
| `research_jobs_total{error_type="cost_budget_exceeded"}` | metric | A research run crossed `MAX_COST_USD` and stopped. A partial report may still be attached. |
| `research_jobs_total{status="degraded_close"}` | metric | A guided session hit `LEARNING_SESSION_MAX_COST_USD` under `LEARNING_SESSION_COST_CAP_BEHAVIOR=degraded_close` and was closed politely (ADR 0062). **The job row says `succeeded`** — this metric status is the only place it does not, and it exists because reporting it as an ordinary success made budget exhaustion invisible in the one signal an operator watches. |
| `research_jobs_total{error_type="session_cost_cap_refused"}` | metric | The `refuse` half of the same setting: the session declined another model call. |
| `llm_cost_usd_total{model}` | metric | Estimated spend, by model. `rate(...) * 3600` is USD/hour. |
| `gen_ai.invoke_agent.inference_calls`, `gen_ai.invoke_agent.tool_calls` | metric | Calls per agent invocation. A step change here is the shape of a loop that stopped terminating, which is the most expensive failure this system has. |
| `api_job_cost_budget_exceeded`, `api_session_cost_cap_reached`, `supervisor_cost_budget_stop` | log | The three call sites that stop work on cost, with the run's cost snapshot. |
| `llm_call` | log | Per call: `model`, `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cost_usd`, `retries`. Where a cost regression is actually diagnosed. |

Alert rules: `CostCapStorm`, `SpendRateHigh`.

**The number is an estimate.** `llm_cost_usd_total` is computed from
token counts and the pinned price table, not billed by the provider.
Treat it as the shape of the spend. The invoice is the invoice.

## 2. The first three commands

```bash
# 1. What is the spend, per call, right now — and is it tokens or volume?
dc logs --since 30m app | jq -c 'select(.message == "llm_call") | {model, input_tokens, output_tokens, cache_read_input_tokens, cost_usd, retries}' | tail -30

# 2. Which ceiling is firing, and on which kind of work?
dc logs --since 1h app | jq -c 'select(.message | test("cost_budget_exceeded|cost_cap_reached|cost_budget_stop"))'

# 3. What are the ceilings actually set to on this deployment?
dc exec app python -c "from src.config import settings; print(settings.max_cost_usd, settings.learning_session_max_cost_usd, settings.learning_session_cost_cap_behavior, settings.api_key_hourly_limit, settings.max_iterations)"
```

Command 1 separates the two causes in one screen. **Rising
`input_tokens` per call** is a prompt or a context that grew — a longer
paper set, more prior context, a bigger profile. **Flat tokens with more
calls** is a loop: check `max_iterations` and the supervisor.
**`cache_read_input_tokens` collapsing to zero** is a prompt-cache miss,
which multiplies input cost several-fold on identical work and is
usually a Postgres cache problem rather than a spend problem — see
[`postgres-loss.md`](postgres-loss.md).

## 3. Containment

In order of how fast they stop money, cheapest first.

**Lower the ceilings.** One `.env` edit and a restart. This does not
stop the storm, it bounds each instance of it, and it applies to the
operator's own runs too because the ceiling is per deployment.

```bash
# in .env: MAX_COST_USD, LEARNING_SESSION_MAX_COST_USD
dc up -d app
```

**Lower the hourly limit.** `API_KEY_HOURLY_LIMIT` bounds accepted
submissions per principal per hour, which is the term the pilot's
worst-case formula multiplies by 24 × D. Halving it halves the bound.
Redis-backed, so it is fleet-wide (ADR 0037) — unless Redis is degraded,
in which case it has silently become per-worker and this lever is
weaker than it looks. Check [`redis-loss.md`](redis-loss.md) §1 first.

**Stop the workers.** The only containment that actually stops spend.

```bash
dc stop app
```

In-flight jobs get the graceful drain; their rows become reclaimable
when the leases expire. Nothing is lost that would not also be lost by a
deploy.

**Then check the provider console.** An account-level budget is the only
thing that holds if this repository's arithmetic is wrong, and during a
storm it is the number worth reading with your own eyes.

## 4. Rollback

A cost storm that started at a deploy is a prompt change until proven
otherwise. Prompts are code here, so the rollback is a SHA:

```bash
git checkout --detach <previous-release-commit>
dc up --build -d app
```

Then prove the recovery on tokens, not on the alert clearing: run one
job and compare `input_tokens` per call in the `llm_call` lines against
the ones from before the deploy. An alert that stops firing because you
lowered the ceiling is not a fix, it is a smaller loss.

If the storm started at a *config* change — `MAX_ITERATIONS`,
`READER_MAX_CHUNKS_PER_PAPER`, `READER_MAX_WORKERS`, a model id —
restore the previous value and restart. Those four are the settings that
change cost per job without changing a line of code.

## 5. What this runbook does not cover

- **An aggregate cap.** It does not exist. Every lever here bounds a
  job, a principal or a deployment's willingness to keep running; none
  of them bounds the sum, and the honest containment is `dc stop app`.
- **Per-job cost as an SLI.** There is no `research_job_cost_usd`
  histogram, so "p95 cost per job by kind" cannot be computed today.
  [`../reliability.md`](../reliability.md) §7 records this as the one
  missing instrument that would make a spend objective measurable rather
  than declared.
- **Attributing spend to a principal.** Deliberately impossible from the
  metrics: `key_id` is unbounded operator-supplied text and is not a
  metric label (ADR 0049). The logs carry `principal_hash`, which groups
  correctly within a process and — without a fleet-wide
  `LOG_PRINCIPAL_SALT` — not across one.
- **Deciding what a budget should be.** That is the owner's, and
  [`pilot.md`](pilot.md) §3 is where the arithmetic to decide it lives.
