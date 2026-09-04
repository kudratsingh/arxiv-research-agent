# `deploy/observability/`

Alert rules, a dashboard, a collector and a rule evaluator — as
**reviewable files that nothing runs**.

Nothing in this directory is wired into `docker-compose.yml`, and
`tests/test_operability_docs.py` asserts it stays that way. Standing up
a collector and a Prometheus is two more processes, two more volumes and
a disk that grows without asking; on a single box that is a real running
cost, and it is the owner's decision rather than this work order's.

The objectives these rules watch are derived in
[`docs/reliability.md`](../../docs/reliability.md); the incidents they
fire are in [`docs/runbooks/`](../../docs/runbooks/README.md); the
decision is [ADR 0073](../../docs/decisions/0073-slos-and-operational-readiness.md).

## The files

| File | What it is |
|---|---|
| [`alerts.yml`](alerts.yml) | Prometheus rule file. Two SLO burn-rate groups and one rule per incident runbook. Loadable by `promtool check rules`. |
| [`log-alerts.yml`](log-alerts.yml) | Log-event alarms, in a repository-defined schema. **Not** Prometheus rules — these signals emit no metric, and a PromQL rule for a series that does not exist is the failure this directory exists to prevent. |
| [`dashboard.json`](dashboard.json) | Grafana dashboard. Every instrument the repository emits appears on it exactly once. Import it into any Grafana pointed at the Prometheus below. |
| [`otel-collector.yaml`](otel-collector.yaml) | Collector config. **Read the header block** — it pins `add_metric_suffixes: false`, which is the assumption every metric name in the two alert files depends on. |
| [`prometheus.yml`](prometheus.yml) | Scrapes the collector, evaluates `alerts.yml`. No Alertmanager: routing a page is a decision about who gets woken up, and there is no on-call rota to encode. |
| [`compose.observability.yml`](compose.observability.yml) | The overlay that runs the two of them and turns the app's exporters on. |

## Running it

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

Both ports bind to loopback. Neither has authentication, and the metrics
carry route templates, model names and spend.

To take it down without touching the base stack:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/compose.observability.yml \
  down otel-collector prometheus
```

For a quick "is this instrumented at all" check with no collector at
all, `docs/development.md` has the console-exporter form: leave
`OTEL_EXPORTER_ENDPOINT` empty and both signals print to stderr.

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
6. `otel-collector.yaml` still pins `add_metric_suffixes: false`;
7. `docker-compose.yml` still does not mention this directory.

Check 1 is the one that matters. Alerting rots silently: a renamed
instrument does not make a rule error, it makes the rule match nothing —
forever — and a rule matching nothing looks exactly like a healthy
fleet. There is no other mechanism in this repository that would notice.

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
