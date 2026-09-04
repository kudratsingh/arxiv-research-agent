# 0073. Anchor the SLOs on the SRE quality SLI, and pin the alert rules to the code with a test

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: WO-A12 (Phase A, wave 3)

## Context

Every instrument this repository owns exports to nothing by default.
ADRs [0049](0049-otel-metrics.md), [0066](0066-genai-semantic-conventions.md)
and WO-A10 built the GenAI conventional set, the stable HTTP set and the
repository's own job/spend/queue instruments, and after all of that
there were no service level objectives, no error budget, no alert rules,
no dashboard, and exactly one page in `docs/runbooks/` — about issuing
pilot credentials. An instrument nobody has decided what to do with is a
line of code, not observability.

Three things forced the decision now rather than later.

**A pilot is imminent.** `docs/runbooks/pilot.md` is a procedure with
five named humans behind it. The first time a dependency fails during a
pilot is the wrong time to work out which log line says which backend
died.

**The instruments are new and will be renamed.** The GenAI conventions
are pre-stable, live in a repository with no tagged release, and ADR
0066 pins them to a *commit*. Names in that family are expected to
churn. A dashboard or an alert rule written against a name that later
changes does not error — it renders a flat zero, and a flat zero reads
as a healthy, idle fleet. That failure mode is silent, indefinite, and
discovered during an incident.

**There is no defensible published methodology for LLM quality error
budgets.** The 2026 "AI agent SLO" material is overwhelmingly marketing:
thresholds published with no derivation, no denominator, and no
statement of the population measured. Adopting one of those numbers
would give this repository a target it could not defend, which is worse
than having none.

## Decision

### 1. Anchor quality on the SRE Workbook's quality SLI, not on a vendor number

The SRE Workbook's SLI menu already lists **quality** as a first-class
SLI type: the proportion of responses served in an undegraded state.
Nothing in that definition requires determinism. Expressed as good
events over valid events — the same shape as every other SLI — error
budgets, burn rates and the multiwindow alerting tables apply to it
unmodified.

That is the whole theoretical content of `docs/reliability.md` §2, and
it is deliberately old and dull. It composes with `pass^k`
(ADR [0071](0071-eval-statistics-and-gates.md)) for the evaluation half
without either needing to know about the other.

### 2. Exclude degraded and shed requests from the latency SLI

A latency SLI that counts shed requests improves when the system sheds
harder, because a 429 is fast. One that counts degraded responses
improves when the reader gives up on full text, because an abstract is
quick to read. In both cases the dashboard gets better while the product
gets worse, and the operator is misinformed by their own instruments.

So the latency rules exclude `http.response.status_code` 429 and 503;
the job-latency rule is cut to `status="succeeded"`, because a timeout
kill lands in the histogram at exactly `API_JOB_TIMEOUT_SEC`; and
`degraded_close` is in the job-success denominator and not its
numerator. Those exclusions are counted against quality instead.

### 3. State the compounding arithmetic, and say the objectives are declared

`0.95⁵ = 0.774`. The linear research graph is exactly five agent nodes,
so that is not an illustration here — it is the product's shape. Read
backwards, holding 95% end to end across five steps requires 99.0% per
step.

Every objective in `docs/reliability.md` §3 is marked **declared, not
earned**: chosen, never measured, from a system that has not yet served
28 days of traffic. The first honest job of an SLO is to be revised
against measurement.

### 4. The name-consistency test is the deliverable

`tests/test_operability_docs.py` re-parses `src/` for every
`meter.create_*` call, resolves each instrument name (including the ones
that come from `semconv` constants), and asserts:

- every metric name in `deploy/observability/alerts.yml` and
  `dashboard.json` has an instrument behind it in `src/`;
- every instrument in `src/` appears in at least one of them, so a new
  instrument cannot be added and forgotten;
- every log event name in `log-alerts.yml` and in the runbooks is a
  member of `KNOWN_EVENTS`;
- every `runbook:` annotation points at a file that exists;
- `otel-collector.yaml` still pins `add_metric_suffixes: false`, which
  is the assumption every name in the two files depends on;
- `docker-compose.yml` still does not reference the overlay.

It fails when an instrument is renamed. That is the point of the whole
directory: alerting rots silently, and this is the mechanism that makes
the rot a red test instead of a quiet incident.

An instrument name the scan cannot resolve is a **failure**, not a skip.
A test with a silent hole in it is worse than no test, because it is
believed.

### 5. `add_metric_suffixes: false` on the collector

The OTLP→Prometheus translation appends unit and type suffixes by
default, driven by a unit table: `s` becomes `_seconds`, a monotonic sum
gains `_total`, and a unit the table does not know is appended verbatim.
`llm_cost_usd_total` carries unit `USD`, which the table does not know,
so its exported name is not one anybody would guess from the source —
and the test could only check it by reimplementing the exporter's unit
table and being subtly wrong about it after the next upgrade.

With suffixing off there is exactly one transformation left, it is
stated in the specification, and it is four characters of Python: every
character outside `[A-Za-z0-9_:]` becomes `_`. The cost is that the unit
is no longer in the metric name; it is carried in the instrument
description, in `docs/observability.md`, and in every dashboard panel's
`unit` field.

### 6. Two alert files, because two kinds of signal exist

`alerts.yml` is a Prometheus rule file and contains only metric-based
rules. `log-alerts.yml` is a repository-defined schema of log-event
alarms, because the injection alarm and six of the eight degradation
rungs emit **no metric at all**. Writing a PromQL rule for a series that
does not exist would be exactly the failure §4's test prevents, so those
signals are written in the shape they actually have, with the missing
instruments named in `docs/reliability.md` §7 and an upgrade path (the
collector's `count` connector) recorded in the file's header.

### 7. Nothing is stood up

`deploy/observability/` ships a collector config, a Prometheus config, a
compose overlay, the alert rules and a Grafana dashboard as **reviewable
files that are not wired into the default stack**. `docker-compose.yml`
is unchanged and a test asserts it stays that way. Standing up a
collector is two more processes, two more volumes and a disk that grows
without asking; on a single box that is a real running cost and it is
the owner's decision.

## Alternatives considered

- **Publish an "AI agent SLO" threshold from the 2026 literature** — the
  fastest path to a number, and the number would be indefensible. No
  derivation, no denominator, no stated population. Dealbreaker: this
  phase's entire premise is that a claim must be traceable to the
  artifact that enforces it.

- **Leave `add_metric_suffixes` at its default and teach the test the
  unit table** — keeps the conventional Prometheus naming that
  off-the-shelf dashboards expect. Rejected: it makes the test a second,
  independent implementation of an exporter's translation logic, which
  will drift from the exporter and fail in the direction of a *false
  green*. A test that is wrong about the names is worse than the rot it
  was written to catch.

- **Assert the alert rules against a checked-in list of metric names**
  — much simpler to write. Rejected for the reason
  `tests/test_log_contract.py` gives about the event registry: a fixture
  only proves the fixture and the constant agree. Parsing `src/` proves
  the *code* and the rules agree, which is the invariant that matters
  when somebody renames an instrument.

- **A single alerts file with the log alarms written as PromQL against
  series that do not exist yet** — one format, one file, and a set of
  rules that can never fire. Rejected outright; it is the exact failure
  mode this ADR exists to prevent, committed deliberately.

- **Add the missing instruments in this work order** — a
  `research_degradations_total` counter and a `research_job_cost_usd`
  histogram would make the quality and spend SLIs computable rather than
  declared. Rejected on scope: `src/observability/metrics.py` belongs to
  WO-A07 and `src/config.py` is edited by two other work orders in the
  same phase, and silently editing a peer's owned file creates a merge
  conflict for them. Recorded in `docs/reliability.md` §7 with the exact
  instrument each gap needs, which is the cheaper half of the work done
  and handed over.

- **Wire the collector into `docker compose up`** — makes the telemetry
  real for anyone who runs the stack. Rejected: `docker compose up` is
  the zero-config demo, every service in the default path has to be
  something a stranger can run without making a decision, and a
  collector plus a Prometheus is not that.

- **A circuit breaker as the containment in the provider-outage
  runbook** — the familiar answer. Already rejected in
  ADR [0068](0068-resilience-policy.md) in favour of the retry token
  bucket, and the runbook follows that decision rather than reopening
  it: the containment is confirming the budget is on, then draining.

## Consequences

- **Positive**: the objectives are stated, derived and falsifiable, and
  every one of them names the instrument that measures it. Seven
  incidents have a page that names the signal, three commands, a
  containment and a rollback. Alert rules and a dashboard exist as
  reviewable files. A renamed instrument now fails a test instead of
  silently rendering zero, and a new instrument cannot be added without
  appearing on the dashboard or being explicitly exempted.

- **Positive**: the gaps are enumerated rather than papered over.
  `docs/reliability.md` §7 lists eight things that cannot be measured
  today and names the instrument each one needs, which follows NIST AI
  RMF **MS-1.1-009**'s explicit sanction to record an unmeasurable risk
  with its reason.

- **Negative**: the quality SLI — the anchor of the entire document —
  has metric coverage for only two of the eight degradation rungs. Six
  are log-only, and until `record_degradation` becomes an OpenTelemetry
  instrument the burn-rate machinery cannot be applied to quality at
  all. The document says so in the same table that defines it.

- **Negative**: `add_metric_suffixes: false` diverges from what an
  off-the-shelf Prometheus dashboard for OpenTelemetry data expects.
  Anyone importing a third-party dashboard will find its queries do not
  match. Stated at the top of `otel-collector.yaml`, where somebody
  hitting that will be looking.

- **Negative**: the burn-rate rules carry a volume floor, so at pilot
  volumes the API availability rule will effectively never fire. That is
  the honest state — a ratio over a handful of events is noise — but it
  means the burn-rate machinery is, for now, built for a load this
  deployment does not have.

- **Follow-ups**: the two instruments in `docs/reliability.md` §7 items
  1 and 2 (`research_degradations_total`,
  `research_job_cost_usd`) are the highest-value observability work left
  in the repository, and each is roughly ten lines in a file this work
  order does not own. Items 3–8 are smaller and are recorded with the
  same specificity.
