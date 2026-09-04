# Runbook — model-provider outage

The Anthropic API is failing, slow, or refusing this deployment's
credential. Every agent node in both workflows makes model calls, so
this is the outage with the widest blast radius and the only one where
*doing nothing* costs money: a failing call still pays for the tokens it
sent, and the retry envelope pays for them several times.

Read [`../reliability.md`](../reliability.md) §5 first if the symptom is
"reports are getting worse" rather than "calls are failing" — a provider
that is degraded rather than down shows up on the degradation ladder,
not here.

## 1. The signal

| Signal | Where | What it means |
|---|---|---|
| `gen_ai.client.operation.duration` count with `error.type != "none"` | metric | Calls that failed **after** the SDK exhausted its own retries. The conventional denominator is the same instrument's total count. |
| `llm_upstream_errors_total{model,status}` | metric | The same failures, with the HTTP status — or `connection` when the call never got one. `401`/`403` is a credential, `429` is a provider rate limit, `529` is Anthropic overload, `connection` is network or DNS. |
| `llm_retries_total{model}` | metric | The SDK's own `retries_taken`. Rising here with `llm_calls_total` flat means calls are *succeeding on retry* — latency is being paid, the error budget is not. This rises **before** the outage. |
| `llm_calls_total{model}` | metric | Successes only. Zero here with errors non-zero is a total outage. |
| `llm_upstream_error` | log | One line per exhausted call, with `model` and `status`. |
| `llm_retry_budget_clamped` / `retry_envelope_clamped` | log | The retry count the operator configured is not the one being honoured, because the worst-case chain would not fit the job's wall clock. |
| `reader_degraded_to_abstract_only` | log | The reader gave up on full text and used the abstract. The report still ships and the user is never told (`../reliability.md` §5). |

Alert rules: `ModelProviderErrorRateHigh`, `ModelProviderNoSuccessfulCalls`,
`ToolLatencyP95High` in
[`alerts.yml`](../../deploy/observability/alerts.yml).

## 2. The first three commands

```bash
# 1. Is it us or them? Status, model, and whether a key is even configured.
dc logs --since 15m app | jq -c 'select(.message == "llm_upstream_error")' | tail -20

# 2. Are calls failing, or just slow? Successes carry `retries` and `latency_ms`.
dc logs --since 15m app | jq -c 'select(.message == "llm_call") | {model, retries, latency_ms, cost_usd}' | tail -20

# 3. Is anything else broken, or is this only the provider?
dc exec app curl -fsS http://localhost:8000/healthz
```

Command 1 tells you the class within seconds: a `status` of `401` is a
credential and no amount of waiting fixes it; `429` and `529` are the
provider's and waiting is exactly right; `connection` is a network path
and may be this box.

## 3. Containment

Pick by class. In every case the containment is **stopping the spend**,
not restoring the feature — there is no aggregate spend cap in this
repository (MT-01 F4), so a failing fleet retrying against a broken
provider spends until somebody stops it.

**Credential (`401`/`403`).** Nothing to wait for.

```bash
dc stop app          # stops accepting work and stops spending
# fix ANTHROPIC_API_KEY in .env, then:
dc up -d app
```

**Provider outage or overload (`429`, `5xx`, `connection`).** The
correct response is to stop paying the retry envelope. `enable_retry_budget`
already does this per process (ADR 0068): the token bucket throttles
*retries* while leaving first attempts alone, so a healthy caller is
never affected and a fleet against a dead provider stops multiplying its
own load. Confirm it is on before doing anything else:

```bash
dc exec app python -c "from src.config import settings; print(settings.enable_retry_budget, settings.retry_budget_capacity, settings.anthropic_max_retries)"
```

If it is off, turn it on and restart `app`. If it is on and the provider
is still down, drain rather than thrash:

```bash
dc stop app
```

In-flight jobs get uvicorn's 10s graceful window plus the node drain
(ADR 0047), and a job the worker was holding becomes reclaimable when
its `joblease:` key expires — the redriver picks it up on the next
start. Stopping is not data loss.

**Slow but succeeding.** Do not stop anything. Lower
`ANTHROPIC_MAX_RETRIES` so a slow call fails inside its job budget
instead of eating it, and let it ride. `retry_envelope_clamped` in the
log tells you whether the clamp has already done this for you.

## 4. Rollback

There is nothing to roll back unless the incident followed a change.
If it did — a model id, a prompt, a `MAX_TOKENS`, a dependency bump —
the rollback is the deployment one, and it is a SHA:

```bash
git checkout --detach <previous-release-commit>
dc up --build -d app
dc exec app curl -fsS http://localhost:8000/healthz
```

Confirm recovery on the signal, not on the absence of the alert: watch
`llm_calls_total` climb from zero. An alert that stops firing because
the fleet stopped calling is not a recovery.

## 5. What this runbook does not cover

- **Reports that are wrong rather than absent.** A provider serving
  degraded output produces successful calls, a green job-success SLI and
  a worse product. That is `../reliability.md` §5, and this repository
  cannot currently measure it.
- **Provider-side spend caps.** An account budget stops calls with a
  `4xx` that looks like any other refusal here. It is the one class in
  §2's table this page cannot distinguish, and checking the provider
  console is the only way.
- **arXiv, Semantic Scholar and PDF fetches.** Different dependency,
  different owning retry level (`urllib3.Retry`), same table row —
  `ToolLatencyP95High` names which tool by `gen_ai.tool.name`. They fail
  a job's *content*, not its ability to run.
