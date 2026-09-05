# `deploy/observability/`

Alert rules, a dashboard, a collector, a rule evaluator and two viewers
— as **files that nothing in the default stack runs**.

Nothing in this directory is wired into `docker-compose.yml`, and
`tests/test_operability_docs.py` asserts it stays that way. Standing up
a collector and a Prometheus is two more processes, two more volumes and
a disk that grows without asking; on a single box that is a real running
cost, and it is the owner's decision rather than this work order's.

They are opt-in, which is not the same as untested. Everything here is
brought up by a documented command that works, and CI parses the rule
file with `promtool` and resolves both compose layers on every PR — an
artifact nobody can run is not "reviewable", it is unfalsifiable.

The objectives these rules watch are derived in
[`docs/reliability.md`](../../docs/reliability.md); the incidents they
fire are in [`docs/runbooks/`](../../docs/runbooks/README.md); the
decision is [ADR 0073](../../docs/decisions/0073-slos-and-operational-readiness.md).

## The files

| File | What it is |
|---|---|
| [`alerts.yml`](alerts.yml) | Prometheus rule file. Two SLO burn-rate groups, a `quality` group on the degradation ladder (ADR 0081), and one rule per incident runbook. `promtool check rules` parses it on every PR (`.github/workflows/ci.yml`, the `docker-build` job) — before WO-INF1 nothing ever had. |
| [`log-alerts.yml`](log-alerts.yml) | Log-event alarms, in a repository-defined schema. **Not** Prometheus rules — these signals emit no metric, and a PromQL rule for a series that does not exist is the failure this directory exists to prevent. |
| [`dashboard.json`](dashboard.json) | Grafana dashboard, in **provisioning** form. Every instrument the repository emits appears on it exactly once. Loaded automatically by the viewers layer below; importable into any other Grafana unchanged. |
| [`otel-collector.yaml`](otel-collector.yaml) | Collector config. **Read the header block** — it pins `add_metric_suffixes: false`, which is the assumption every metric name in the two alert files depends on. |
| [`otel-collector-traces.yaml`](otel-collector-traces.yaml) | A twelve-line second `--config`, merged on top of the one above by the viewers layer, that sends traces to Jaeger instead of only to the debug log. |
| [`prometheus.yml`](prometheus.yml) | Scrapes the collector, evaluates `alerts.yml`. No Alertmanager: routing a page is a decision about who gets woken up, and there is no on-call rota to encode. |
| [`grafana/provisioning/`](grafana/provisioning) | The datasource and the dashboard provider Grafana reads at boot. `dashboard.json` resolves against the datasource declared here. |
| [`compose.observability.yml`](compose.observability.yml) | **Layer 2.** The collector and the rule evaluator, plus the app's exporters turned on. |
| [`compose.viewers.yml`](compose.viewers.yml) | **Layer 3.** Grafana and Jaeger — the two things that render what layer 2 collects. |

## Running it

Layer 2 is the one you leave running. It collects, it retains, and it
evaluates the rules:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/compose.observability.yml \
  up -d
```

Then:

- `http://127.0.0.1:9090/alerts` — the rules, evaluating
- `http://127.0.0.1:8889/metrics` — the collector's Prometheus surface,
  which is also the fastest way to see whether a metric name you expect
  is actually being emitted

Layer 3 is the one you bring up when you want to *look*. Add the third
`-f`:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/compose.observability.yml \
  -f deploy/observability/compose.viewers.yml \
  up -d
```

- `http://127.0.0.1:3001` — Grafana, opening on `dashboard.json` with
  the Prometheus above already wired in. No login: everything it serves
  is provisioned from files in this directory, so there is nothing to
  save and nothing to edit.
- `http://127.0.0.1:16686` — Jaeger, for the trace of a single run.
  In-memory storage, capped at 50k traces, gone when the container
  stops.

Grafana is on 3001 rather than 3000 because the base stack's `web`
already owns 3000.

**Every one of these ports binds to loopback and none of them asks for
a password.** The dashboards carry route templates, model names and
spend; the traces carry job and run ids. Do not publish them on a
public interface — tunnel instead:

```bash
ssh -N -L 3001:127.0.0.1:3001 -L 16686:127.0.0.1:16686 user@host
```

To take a layer down without touching the base stack — naming the
services, because a bare `docker compose down` resolves the project from
the working directory and would take the app with it:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/compose.observability.yml \
  -f deploy/observability/compose.viewers.yml \
  down grafana jaeger otel-collector prometheus
```

For a quick "is this instrumented at all" check with no collector at
all, `docs/development.md` has the console-exporter form: leave
`OTEL_EXPORTER_ENDPOINT` empty and both signals print to stderr.

## Seeing one job as one trace

The property `docs/observability.md` calls "one job is one trace" — the
HTTP request that accepts a job and the worker that runs it landing in
a single tree — is the hardest thing here to believe without looking at
it. This is the command that shows it, and it costs nothing:

```bash
TRACE_SAMPLE_RATIO=1.0 USE_MOCK_DATA=true \
ANTHROPIC_API_KEY=local-preview-disabled \
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/compose.observability.yml \
  -f deploy/observability/compose.viewers.yml \
  up -d --wait

curl -sS -X POST http://127.0.0.1:8000/research \
  -H 'content-type: application/json' \
  -d '{"query":"How do transformer models handle long context?","hitl_bypass":true}'

open 'http://127.0.0.1:16686/search?service=arxiv-research-agent&operation=POST%20%2Fresearch'
```

Both environment variables are load-bearing:

- **`TRACE_SAMPLE_RATIO=1.0`.** The overlay's default is `0.1`, so nine
  runs in ten produce no trace at all and the viewer looks broken. It is
  parameterised for exactly this reason.
- **`USE_MOCK_DATA=true`.** Mock mode (ADR 0080) runs the *whole*
  research graph — planner, search, reader, synthesizer, critic — with
  a deterministic branch in front of each model call, so the job
  **succeeds** with `llm_calls: 0` against the disabled key sentinel.

What you get is eight spans in one tree:

```
POST /research                     4 ms   (the HTTP edge, SERVER)
└── invoke_workflow research      38 ms   (the worker, after attaching
    ├── plan planner                       job.trace_context)
    ├── invoke_agent search
    │   └── execute_tool embedding_rank
    ├── invoke_agent reader
    ├── invoke_agent synthesizer
    └── invoke_agent critic
```

The child outliving its parent is the point: those are two different
processes, joined by the W3C carrier on the job row.

**What it does not show, and you should know before you go looking.**
There are **no `chat` spans**, because mock mode returns before every
model call — so no `gen_ai.request.model`, no token counts, no
`llm.cost_usd`, and the four spend panels on the Grafana dashboard stay
empty. A trace with `chat` spans in it needs a real credential and real
money.

Running the same command *without* `USE_MOCK_DATA` at the disabled
sentinel does get you one `chat` span for free, and it is the other
half of the same disappointment: the planner's first call fails, so the
trace is four spans —

```
POST /research
└── invoke_workflow research
    └── plan planner                    error.type=UpstreamModel
        └── chat claude-sonnet-4-6      error.type=UpstreamModel
```

— and the job is `failed` with `error_type=upstream_model`. Mock mode
shows the whole shape and no model calls; the sentinel shows a model
call and no whole shape. Pick the half you need. This repository has no
free way to produce a clean tree of successful model calls, and a
command that implied otherwise would waste your afternoon.

## The naming rule, which is the whole reason this is checkable

Every metric name in `alerts.yml` and `dashboard.json` is the
OpenTelemetry instrument name with **every character outside
`[A-Za-z0-9_:]` replaced by `_`**, and nothing else:

| In `src/` | In Prometheus |
|---|---|
| `gen_ai.client.operation.duration` | `gen_ai_client_operation_duration` |
| `http.server.request.duration` | `http_server_request_duration` |
| `research_jobs_total` | `research_jobs_total` |

Histograms keep Prometheus' own `_bucket` / `_count` / `_sum` suffixes,
which are the client library's and not the translation's.

That one-to-one mapping only holds because `otel-collector.yaml` sets
`add_metric_suffixes: false`. With the exporter's default the name is
put through a unit table instead — `s` becomes `_seconds`, monotonic
sums gain `_total`, and a unit the table does not know (`USD`, on
`llm_cost_usd_total`) is appended verbatim — and the exported names
stop being derivable from the source by anything short of a second
implementation of the exporter.

**If you turn suffixing on, three things move together:** `alerts.yml`,
`dashboard.json`, and `_prometheus_name` in
`tests/test_operability_docs.py`. The test asserts the collector line is
still there so that cannot happen by halves.

## What the test enforces

`tests/test_operability_docs.py` re-parses `src/` for every
`meter.create_*` call — resolving `semconv` constants, and **failing**
rather than skipping on a name it cannot resolve — and then checks:

1. every metric name in `alerts.yml` and `dashboard.json` has an
   instrument behind it;
2. every instrument in `src/` appears in at least one of them, so a new
   instrument cannot be added and quietly forgotten;
3. every log event name in `log-alerts.yml` and in every runbook's
   signal table is a member of `KNOWN_EVENTS`;
4. every `runbook:` annotation points at a file that exists;
5. every runbook has all four required sections;
6. `otel-collector.yaml` still pins `add_metric_suffixes: false`, and
   `otel-collector-traces.yaml` still does not restate it;
7. `docker-compose.yml` still does not mention this directory, and
   `compose.viewers.yml` still adds exactly `{grafana, jaeger}`;
8. every dashboard panel **resolves a datasource** that
   `grafana/provisioning/` declares, and the dashboard provider reads
   the directory `compose.viewers.yml` mounts the dashboard into;
9. CI still runs `promtool` over `alerts.yml`, with the same pinned
   Prometheus image the overlay evaluates them with.

Check 1 is the one that matters. Alerting rots silently: a renamed
instrument does not make a rule error, it makes the rule match nothing —
forever — and a rule matching nothing looks exactly like a healthy
fleet. There is no other mechanism in this repository that would notice.

Checks 8 and 9 exist because check 1 turned out to be **necessary and
not sufficient**, twice over.

- `dashboard.json` shipped in Grafana's export-for-sharing format: an
  `__inputs` block and `${DS_PROMETHEUS}` placeholders that the import
  wizard resolves by asking a human and that **file provisioning does
  not resolve at all**. Every metric name in it was correct and check 1
  was green, while a provisioned copy rendered 28 panels against a
  datasource uid that was the literal placeholder string. Check 8 is
  the other half of the claim: a panel names a real metric *and* has
  something to ask.
- Nothing had ever *parsed* `alerts.yml`. Check 1 reads it as YAML and
  looks at names; it does not parse PromQL, and an `expr` that does not
  parse or a `for:` that is not a duration passes every check in that
  file and is rejected by Prometheus at load — which is to say, during
  the first incident the rule was written for.

## Every threshold here is declared, not earned

No deployment of this system has produced 28 days of traffic. The
numbers were chosen so that the alerting machinery has something to
evaluate, and `docs/reliability.md` §2 says at length why publishing
them anyway is still worth doing. When the pilot produces data, the
expected outcome is that several of them move.

Two are worth calling out before anyone acts on them:

- **`SpendRateHigh`'s 1.00 USD/hour** is a placeholder. There is no
  approved budget to derive it from; the rule carries the derivation to
  run once there is one.
- **The burn-rate rules' volume floors** (200 requests, 10 jobs) mean
  that at five-person-pilot volumes the API availability rule will
  effectively never fire. That is honest — a ratio over a handful of
  events is noise — and it is why the per-incident rules in the other
  groups are the ones that will actually do the work.
