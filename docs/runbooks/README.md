# Runbooks

One page per incident the instruments make visible. Each names **the
signal**, **the first three commands**, **the containment action** and
**the rollback**, in that order, because that is the order an operator
needs them in at three in the morning.

The objectives these defend, the error budgets, and the degradation
ladder are in [`../reliability.md`](../reliability.md). The alert rules
that fire them are
[`deploy/observability/alerts.yml`](../../deploy/observability/alerts.yml)
(metric-based) and
[`deploy/observability/log-alerts.yml`](../../deploy/observability/log-alerts.yml)
(log-based). Neither is wired into the default stack.

## The index

| Runbook | Fires on | Severity |
|---|---|---|
| [`model-provider-outage.md`](model-provider-outage.md) | `ModelProviderErrorRateHigh`, `ModelProviderNoSuccessfulCalls`, `ToolLatencyP95High` | page |
| [`redis-loss.md`](redis-loss.md) | `RateLimiterFellBackToMemory`, `SubmitPathFailing`, `SubmitLatencyP95High` | page |
| [`postgres-loss.md`](postgres-loss.md) | `JobsOrphanedByDeadWorkers`, `TerminalStateOrStreamLost` | page / ticket |
| [`cost-cap-storm.md`](cost-cap-storm.md) | `CostCapStorm`, `SpendRateHigh` | page |
| [`queue-saturation.md`](queue-saturation.md) | `QueueSaturated`, `QueueWaitP95High`, `AbandonedNodeThreads` | ticket |
| [`poison-job.md`](poison-job.md) | `PoisonJobDeadLettered` | page |
| [`injection-alarm.md`](injection-alarm.md) | `SupervisorReceivedAnUnknownAction`, `ReaderControlOutputUnparseable` | page |
| [`pilot.md`](pilot.md) | Not an incident — the bounded-pilot procedure | — |

The two SLO burn-rate alerts (`ApiAvailabilityBudgetBurn*`,
`JobSuccessBudgetBurnFast`) do not have a page of their own on purpose.
They say the budget is going, not *why*; the cause is always one of the
seven above, and sending an operator to a page that says "look at the
other pages" would waste the first minute of an incident. They point
here instead.

## The shell function every page assumes

Every runbook writes `dc` where it means the deployment's compose
invocation. Define it once at the top of your session:

```bash
# Production, on the Hetzner box:
dc() { docker compose -f docker-compose.yml -f deploy/hetzner/compose.prod.yml "$@"; }

# Pilot:
dc() { docker compose -f docker-compose.yml -f deploy/pilot/compose.pilot.yml "$@"; }

# Local:
dc() { docker compose "$@"; }
```

Three services carry the state these pages are about: `app` (FastAPI and
the workflow), `redis` (jobs, events, leases, rate-limit counters) and
`postgres` (conversations, caches, LangGraph checkpoints).

## Reading the log stream

Every line is one JSON object on stderr, so `jq` is the tool and the
`message` field is the event name. The names are a closed set
(`KNOWN_EVENTS` in `src/observability/logging.py`) which is why a
runbook can name one and be told by a test when the code stops emitting
it. Two forms worth memorising:

```bash
# Everything at WARNING or above, most recent last.
dc logs --since 30m app | jq -c 'select(.level != "INFO" and .level != "DEBUG")'

# One event, with the fields that matter.
dc logs --since 30m app | jq -c 'select(.message == "resilience_degraded")'
```

`docker compose logs` emits non-JSON lines of its own around container
starts, so `jq` will complain on those; add `-R 'fromjson? // empty'`
before the filter if the noise is in the way.

## Two things that are true of every page here

**`/healthz` is always 200.** It answers "is this process alive", and
restarting a worker does not fix a dead Redis — a liveness probe that
503s on a dependency turns a backend blip into a rolling-restart storm.
Read its **body**: `status`, `dependencies`, `active_jobs`. `/readyz` is
the endpoint that returns 503, and nothing in the shipped compose stack
polls it.

**Nothing here is an aggregate spend control.** The per-job ceilings
bound one job; nothing bounds the sum. During any incident that involves
model calls, the containment action that actually stops spend is
stopping the workers.
