"""OpenTelemetry metrics setup.

The service had structured logs (ADR 0012), opt-in tracing (ADR 0013)
and per-run cost accounting, but no metrics at all: an on-call engineer
could not answer "how many jobs are failing right now", "what is the
p95 job duration" or "are we near the concurrency ceiling" without
grepping logs. This module closes that gap with the instruments
that answer those questions, on the OTel metrics API — the same
telemetry stack tracing already uses, so one OTLP collector receives
both signals. See ADR 0049.

Structure deliberately mirrors `src.observability.tracing`:

- `configure_metrics()` installs a `MeterProvider` once at process
  start, gated on `settings.enable_metrics` and pointed at
  `settings.otel_exporter_endpoint` (empty => console exporter for
  local dev, exactly as tracing does).
- Every recording site calls a small public helper
  (`record_job_terminal`, `record_llm_usage`,
  `record_rate_limit_rejection`) rather than reaching for a meter.
  With the flag off those helpers see `_instruments is None` and
  return on the first line, so a disabled deployment pays one
  module-global load per record point and nothing else — the same
  "no wrapper when disabled" discipline `traced_node` follows.
- `shutdown_metrics()` flushes and tears the provider down; the API
  lifespan calls it alongside the other teardown (ADR 0040/0047).

## Why the provider is module-local

Unlike `trace.set_tracer_provider`, we do not *depend* on OTel's
global meter provider: every measurement in this repo goes through the
helpers below, which read this module's own provider. The global is
still set once, best-effort, so any third-party instrumentation added
later lands in the same pipeline — but because OTel guards that setter
behind a set-once flag, treating it as the source of truth would make
the provider un-swappable within a process, which both the tests and a
lifespan that configures/shuts down more than once need it to be.

## The instruments

Repository-native, and the ones dashboards have read since ADR 0049:

| Instrument                        | Kind             | Attributes               |
|-----------------------------------|------------------|--------------------------|
| `research_jobs_total`             | counter          | status, error_type, kind |
| `research_job_duration_seconds`   | histogram        | status, kind             |
| `research_job_queue_wait_seconds` | histogram        | kind                     |
| `research_active_jobs`            | observable gauge | -                        |
| `research_abandoned_node_threads` | observable gauge | -                        |
| `research_queue_depth`            | observable gauge | -                        |
| `research_queue_saturation_ratio` | observable gauge | -                        |
| `llm_cost_usd_total`              | counter (float)  | model                    |
| `llm_calls_total`                 | counter          | model                    |
| `llm_retries_total`               | counter          | model                    |
| `llm_upstream_errors_total`       | counter          | model, status            |
| `rate_limit_rejections_total`     | counter          | backend                  |
| `research_degradations_total`     | counter          | rung, component          |

## The degradation counter, and why its attributes are a closed set

`research_degradations_total` is the instrument `docs/reliability.md`
§7 asked for. The quality SLI that document is built on — the SRE
Workbook's *proportion of responses served in an undegraded state* — is
the anchor for every objective in its §3, and until this counter
existed it could not be computed: six of the eight rungs of the §5
ladder emitted a log line and nothing else, so "how degraded is the
fleet right now" was a `jq` over container logs rather than a query.

Its attributes are closed sets (`DEGRADATION_RUNGS`,
`DEGRADATION_COMPONENTS`), for the third time in this repository and
for the reasons both earlier times give. `ERROR_CODES` is closed
because "an open string used as a metric attribute is unbounded
cardinality" (ADR 0064); `KNOWN_EVENTS` is closed so "a dashboard, an
alert rule and a runbook can name an event and be told when the code
stops emitting it under that name" (ADR 0067). Both apply here
verbatim, and the second is the sharper one: a `rung` value nobody
emits any more renders a flat zero on a quality panel, which reads
exactly like an undegraded fleet.

`reason` is deliberately *not* an attribute, even though §7 sketched
the instrument as `{component,reason}`. It stays on the structured log
line, for the reason `record_rate_limit_rejection` gives about
`key_id`: the metric answers "how much, at which rung, in which
component", and the log answers "why". See ADR 0081.

Conventional, added by WO-A07 from the pinned GenAI specification
commit in `src.observability.semconv` — all histograms:

| Instrument                            | Attributes                          |
|---------------------------------------|-------------------------------------|
| `gen_ai.client.token.usage`           | operation, provider, request.model, response.model, token.type |
| `gen_ai.client.operation.duration`    | operation, provider, request.model, response.model, error.type |
| `gen_ai.invoke_agent.duration`        | agent.name, error.type              |
| `gen_ai.invoke_agent.inference_calls` | agent.name                          |
| `gen_ai.invoke_agent.tool_calls`      | agent.name                          |
| `gen_ai.execute_tool.duration`        | operation, tool.name, error.type    |
| `gen_ai.invoke_workflow.duration`     | workflow.name, error.type           |

Conventional and **stable**, added by WO-A10 — the HTTP server family,
which unlike the GenAI names is pinned by the specification rather than
by a commit:

| Instrument                     | Kind             | Attributes                                                        |
|--------------------------------|------------------|-------------------------------------------------------------------|
| `http.server.request.duration` | histogram (s)    | http.request.method, http.route, http.response.status_code, url.scheme, error.type |
| `http.server.active_requests`  | up/down counter  | http.request.method, url.scheme                                   |

There is no `http_requests_total`, on purpose: the histogram's `count`
*is* the request count, which is why the conventions define no counter.

The two LLM error/retry counters arrived with ADR 0051: Anthropic SDK
retries (429 / 529 / timeouts) were invisible — no app log, the SDK's
own retry line demoted below threshold, no metric — so a throttled
fleet was indistinguishable from a slow one.

## Why both tables exist, and for how long

`llm_calls_total` and `gen_ai.client.operation.duration`'s *count* are
the same measurement under two names, and so are
`research_job_duration_seconds` and `gen_ai.invoke_workflow.duration`
for a job. Emitting both **doubles the instrument count on this
family**, which is a real cost paid on every export: more series in the
collector, more cardinality in the backend, a larger OTLP payload each
interval. It is paid deliberately and for one release only.

Dropping a name silently is the failure mode this avoids. A dashboard
panel, an alert rule and a runbook that name `llm_calls_total` do not
error when the series stops arriving — they render a flat zero, which
reads as "the fleet is idle" rather than "the metric was renamed".
Nothing else in the observability stack fails that quietly. WO-A06's
fault-injection tier also asserts on these names as they stand on
`main`, so the aliases are load-bearing for a test suite and not only
for a dashboard.

**These aliases may be dropped after one release**, once the
dashboards, alert rules and runbooks WO-A12 writes name the
conventional instruments and `gen_ai.*` has been observed arriving in
the collector. `llm_cost_usd_total` is *not* an alias and does not
expire: the conventions define no cost attribute or metric at all
(`02-STANDARDS.md` §1.3), so it is the only name that measurement has.

## Queue saturation without a second counter

`research_queue_depth` and `research_queue_saturation_ratio` are
derived from the *existing* `active_jobs` callable the API lifespan
already injects, against `settings.api_max_concurrent_jobs`. They are
computed here rather than instrumented at the semaphore because a
second counter at the acquire site could disagree with `/healthz`,
which is the failure ADR 0049 avoided for the first two gauges and
avoids again here. What they cost in exchange is stated on
`register_runtime_gauges`: depth is an upper bound, not an exact count.

The two gauges are *observable*: they read the live accounting
`/healthz` already reports (in-flight job tasks, ADR 0047's abandoned
node threads) through callbacks the API lifespan supplies. Nothing is
duplicated — the callbacks close over the existing sources, so a gauge
can never disagree with the health endpoint.

## Which processes emit

`configure_metrics()` has exactly one caller: the API lifespan. So the
instruments are live in an API worker and nowhere else — `make run`
and `make eval` set `enable_metrics` in vain, because those processes
install no provider and every helper below returns on its `None`
check. That is deliberate, not an oversight: eleven of the twenty-two
instruments describe a *server* (job outcomes, queue depth,
concurrency, 429s, degradations, and the HTTP server family), and a
one-shot CLI run has no steady state for the four observable gauges
among them to sample — it would spin an export thread up and tear it
down inside one export interval. (This sentence read "four of the nine"
until WO-B2: written at ADR 0049's count and left behind by twelve
additions, the last surviving copy of a number `docs/architecture.md`
also carried. The count is banded in `tests/test_operability_docs.py`
now, so the next wave has to come back to it — WO-D5 is a wave coming
back to it.)

It also means **an eval campaign contributes nothing to the quality
SLI**, which matters more for `research_degradations_total` than for
the rest: a rung taken under `make eval` is a real degradation of a
real run and it is counted nowhere. `docs/reliability.md` §7 item 6
already records that gap for every instrument; it is worth naming again
here because the degradation counter is the one an eval run is most
likely to move. Tracing differs because `get_tracer()` configures
lazily on first span, which is what makes `traced_node` work under
`make eval`. If the eval runner ever needs the spend counters, the fix
is one `configure_metrics()` call at its entry point, not a lazy
configure on the record path (that would put an `enable_metrics` read
and a possible provider build on every LLM call).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from opentelemetry import metrics as otel_metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.metrics import (
    CallbackOptions,
    Counter,
    Histogram,
    Meter,
    ObservableGauge,
    Observation,
    UpDownCounter,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricExporter,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource

from src.config import settings
from src.observability import semconv
from src.observability.logging import get_logger

log = get_logger(__name__)

__all__ = [
    "DEGRADATION_COMPONENTS",
    "DEGRADATION_RUNGS",
    "DEGRADATION_RUNG_BOUNDED_QUEUE",
    "DEGRADATION_RUNG_CACHE_STALE",
    "DEGRADATION_RUNG_MODEL_FALLBACK",
    "DEGRADATION_RUNG_PARTIAL_RESULTS",
    "DEGRADATION_RUNG_REDUCED_TOOL",
    "DEGRADATION_RUNG_REFUSAL",
    "DEGRADATION_RUNG_STREAMING_PARTIAL",
    "DEGRADATION_RUNG_WEAKENED_GUARANTEE",
    "DEGRADATION_UNREGISTERED",
    "configure_metrics",
    "metrics_enabled",
    "record_agent_invocation",
    "record_degradation_rung",
    "record_genai_client_call",
    "record_http_active_request",
    "record_http_server_request",
    "record_job_terminal",
    "record_llm_retries",
    "record_llm_upstream_error",
    "record_llm_usage",
    "record_rate_limit_rejection",
    "record_tool_execution",
    "record_trajectory_event",
    "record_trajectory_fault",
    "record_workflow_invocation",
    "register_runtime_gauges",
    "shutdown_metrics",
]

_METER_NAME = "arxiv-research-agent"

# Attribute value used when a terminal job carries no error type
# (`succeeded` / `cancelled`). A literal beats omitting the attribute:
# a missing key makes those series a *different* shape from the failure
# series, so `sum by (status)` over `research_jobs_total` would need a
# separate query per outcome.
NO_ERROR = "none"

# Budget for the final flush in `shutdown_metrics`, in milliseconds.
#
# Small because it is spent at the *end* of an already-tight chain.
# ADR 0042 sizes that chain: compose grants `stop_grace_period: 15s`
# and uvicorn spends up to `timeout_graceful_shutdown=10` draining
# connections *before* it runs the lifespan teardown at all — and
# uvicorn puts no timeout on the teardown itself, so the container's
# remaining ~5s is the only bound. The node-executor join (ADR 0047)
# can already claim all of it, so the metrics flush is best-effort by
# construction and must not make things worse: a collector that cannot
# accept an export in two seconds will not accept it in five, and the
# SDK's export thread is a daemon, so overrunning loses the last window
# rather than hanging the process.
_SHUTDOWN_BUDGET_MS = 2_000.0

# Buckets for `research_job_duration_seconds`, in seconds. A research
# job is minutes-scale work (several LLM round trips per node), so the
# SDK's default sub-second-heavy boundaries would put every real job in
# the overflow bucket and make p95 unreadable. These span a fast cached
# run (~10s) through the default `api_job_timeout_sec` neighbourhood and
# past it, so a timing-out fleet is visible as mass in the tail rather
# than as a single saturated `+Inf`.
_JOB_DURATION_BUCKETS: tuple[float, ...] = (
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    1200.0,
    1800.0,
    3600.0,
)

# Buckets for `research_job_queue_wait_seconds`, in seconds. Sub-second
# boundaries matter here in a way they do not for job duration: on an
# unsaturated fleet a job waits microseconds for its permit, and the
# whole value of the metric is telling that apart from "waited four
# minutes behind the concurrency ceiling". The tail reaches an hour
# because a deep queue on a small worker genuinely does.
_QUEUE_WAIT_BUCKETS: tuple[float, ...] = (
    0.001,
    0.01,
    0.1,
    1.0,
    5.0,
    15.0,
    60.0,
    300.0,
    900.0,
    3600.0,
)

# Buckets for the conventional GenAI duration histograms, in seconds.
# The SDK's defaults are sub-second-heavy; a model call is seconds, a
# graph node is several of them, and a workflow is minutes, so the
# defaults would put nearly every observation in the overflow bucket
# and make p95 unreadable — the same reasoning that sized
# `_JOB_DURATION_BUCKETS`. One set for all four so a dashboard can
# stack agent, tool and workflow latency on shared boundaries.
_GENAI_DURATION_BUCKETS: tuple[float, ...] = (
    0.1,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
)

# Buckets for `gen_ai.client.token.usage`, in tokens. Spans a short
# system prompt through the 200k-token context window, which is the
# range a request can actually occupy.
_TOKEN_BUCKETS: tuple[float, ...] = (
    64.0,
    256.0,
    1024.0,
    4096.0,
    16384.0,
    65536.0,
    200000.0,
)

# Buckets for the two per-agent-invocation call counters. Small
# integers, because the interesting question is "did this node make one
# model call or eleven" — an agent that made 40 tool calls in one
# invocation is a loop, and the top bucket is there to make that
# visible rather than to resolve it precisely.
_CALL_COUNT_BUCKETS: tuple[float, ...] = (
    1.0,
    2.0,
    4.0,
    8.0,
    16.0,
    32.0,
    64.0,
)

# Buckets for `http.server.request.duration`, in seconds. These are the
# conventions' own advisory boundaries, copied rather than chosen: the
# HTTP conventions publish a bucket set, every off-the-shelf HTTP
# dashboard computes its quantiles against it, and picking "better"
# boundaries here would make this service's p95 incomparable with every
# other service in a fleet for no gain. They are also right for the
# shape: an API surface whose fast routes are `/healthz` and a 202
# submit belongs in the millisecond decades, which is exactly where the
# resolution is.
_HTTP_DURATION_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    7.5,
    10.0,
)

# Attribute value for a measurement that did not fail. Same literal and
# same reason as `NO_ERROR`, which it deliberately equals: `error.type`
# is a conventional attribute name but its "nothing went wrong" value
# is ours to choose, and choosing a second one would make
# `sum by (error_type)` and `sum by (error.type)` disagree about what
# success looks like.
NO_ERROR_TYPE = NO_ERROR

#: Metric attribute naming the job kind (ADR 0057) — `research` or
#: `session`. Bounded by `JobKind` being a `Literal`, which is what
#: makes it safe as a metric attribute: it is the axis session SLOs are
#: cut along, and without it both kinds share one series.
ATTR_KIND = "kind"

#: `research_jobs_total`'s `status` for a session that hit its cost
#: ceiling and was closed politely rather than failed (ADR 0062). It is
#: not a `JobStatus` — the row really is `succeeded`, and the API
#: contract does not change — but reporting it as a plain success made
#: budget exhaustion indistinguishable from a clean run in metrics,
#: which is the whole reason the value exists here.
STATUS_DEGRADED_CLOSE = "degraded_close"


# ---------------------------------------------------------------------------
# The degradation ladder's attribute vocabulary (docs/reliability.md §5)
# ---------------------------------------------------------------------------
#
# One constant per rung of the published ladder, in the ladder's own
# order — cheapest degradation first. The names are the *rung's*
# identity, not the call site's: two different caches failing are one
# rung and two components, which is what makes `sum by (rung)` the §5
# table drawn as a graph and `sum by (component)` the answer to which
# subsystem to open a runbook for.

#: Rung 1 — paper text or embeddings could not be served from their
#: Postgres cache, so the work is recomputed or refetched (ADR 0028's
#: "degrades to recompute", ADR 0041).
DEGRADATION_RUNG_CACHE_STALE = "cache_stale"

#: Rung 2 — search proceeds on partial upstream results, keeps prior
#: papers, or serves the labelled fixture set.
DEGRADATION_RUNG_REDUCED_TOOL = "reduced_tool"

#: Rung 3 — a result is produced from less evidence than was asked for;
#: the reader's abstract-only fallback is the named instance.
DEGRADATION_RUNG_PARTIAL_RESULTS = "partial_results"

#: Rung 4 — a stream ends at its deadline with whatever exists, without
#: a terminal frame.
DEGRADATION_RUNG_STREAMING_PARTIAL = "streaming_partial"

#: Rung 5 — a node's model output was unusable and a default action was
#: substituted. Not a cheaper-model fallback; there is no such path.
DEGRADATION_RUNG_MODEL_FALLBACK = "model_fallback"

#: Rung 6 — work waits behind `api_max_concurrent_jobs`.
DEGRADATION_RUNG_BOUNDED_QUEUE = "bounded_queue"

#: Rung 6b — a guarantee is still served but a weaker one than the
#: configuration claims: the Redis rate limiter failing open to its
#: per-worker fallback (ADR 0068).
DEGRADATION_RUNG_WEAKENED_GUARANTEE = "weakened_guarantee"

#: Rung 7 — the honest refusal: a 429, a 503, a cost ceiling declining
#: or closing politely.
DEGRADATION_RUNG_REFUSAL = "refusal"

#: The overflow bucket, and the only member of `DEGRADATION_RUNGS` that
#: is not a rung. A call site naming a rung outside the set records
#: here instead of minting a new series — so a mistake costs one extra
#: point rather than unbounded cardinality — and
#: `tests/test_degradation_ladder.py` forbids any call site in `src/`
#: from naming it, so the mistake is caught in CI rather than lived
#: with. `logging.py`'s `FIELD_UNREGISTERED_EVENT` is the same trade:
#: flag it, do not lose it, and let a static test be the enforcement.
DEGRADATION_UNREGISTERED = "unregistered"

#: Every rung a metric attribute may carry. Closed for the reasons in
#: this module's docstring. Three members have no emitter in `src/`
#: today because their only call sites are in another lane's files;
#: `tests/test_degradation_ladder.py` names them and their owners, and
#: goes red when one gains an emitter, which is how the gap closes
#: itself rather than living in a comment.
DEGRADATION_RUNGS: Final[frozenset[str]] = frozenset(
    {
        DEGRADATION_RUNG_CACHE_STALE,
        DEGRADATION_RUNG_REDUCED_TOOL,
        DEGRADATION_RUNG_PARTIAL_RESULTS,
        DEGRADATION_RUNG_STREAMING_PARTIAL,
        DEGRADATION_RUNG_MODEL_FALLBACK,
        DEGRADATION_RUNG_BOUNDED_QUEUE,
        DEGRADATION_RUNG_WEAKENED_GUARANTEE,
        DEGRADATION_RUNG_REFUSAL,
        DEGRADATION_UNREGISTERED,
    }
)

#: Every component a metric attribute may carry — the subsystem that
#: degraded, at the granularity an operator picks a runbook by.
#:
#: Unlike `DEGRADATION_RUNGS` this set is *exactly* what `src/` emits,
#: and the test asserts both directions. A rung may outrun its emitters
#: because the ladder is published in `docs/reliability.md` and the
#: document is the authority; a component name is only ever minted by a
#: call site, so one with no call site is dead vocabulary and a
#: dashboard filter that will never match.
DEGRADATION_COMPONENTS: Final[frozenset[str]] = frozenset(
    {
        "embedding_cache",
        "paper_cache",
        "rate_limiter",
        "sse_stream",
        DEGRADATION_UNREGISTERED,
    }
)


@dataclass(frozen=True)
class _Instruments:
    """The synchronous instruments, created once per configured provider.

    Held as one frozen bundle behind a single module global so the
    record helpers can do one load + one `None` check on the hot path,
    and so `shutdown_metrics` re-arms the disabled path atomically
    rather than leaving half the instruments live.
    """

    jobs_total: Counter
    job_duration_seconds: Histogram
    job_queue_wait_seconds: Histogram
    llm_cost_usd_total: Counter
    llm_calls_total: Counter
    llm_retries_total: Counter
    llm_upstream_errors_total: Counter
    rate_limit_rejections_total: Counter
    degradations_total: Counter
    # The conventional GenAI family. Separate fields rather than a
    # second bundle so `shutdown_metrics` still disarms every
    # instrument with one assignment.
    genai_token_usage: Histogram
    genai_client_operation_duration: Histogram
    genai_agent_duration: Histogram
    genai_agent_inference_calls: Histogram
    genai_agent_tool_calls: Histogram
    genai_tool_duration: Histogram
    genai_workflow_duration: Histogram
    # The stable HTTP server family (WO-A10). Same bundle for the same
    # reason: one `None` check disarms the whole surface.
    http_server_request_duration: Histogram
    http_server_active_requests: UpDownCounter
    # P0-WO08's contract-event family (ADR 0083). Two counters, not one
    # per surface: the question an operator asks is "is the ledger
    # accepting events, and is anything downstream of the accept
    # failing", and two series answer it without a `event_type`
    # dimension whose cardinality is the whole RFC 10 taxonomy.
    trajectory_events_total: Counter
    trajectory_faults_total: Counter


_provider: MeterProvider | None = None
_meter: Meter | None = None
_instruments: _Instruments | None = None
# Observable gauges are kept alive here for the provider's lifetime.
# The meter holds its own reference, but an explicit one documents that
# these are not garbage — the SDK calls back into them on every export.
_gauges: list[ObservableGauge] = []
# Where the gauge callbacks read from, indirected through a dict so a
# second `register_runtime_gauges` (two `create_app()`s in one test
# process) rebinds the source instead of registering a second
# same-named instrument that still reads the first app's dead state.
_gauge_sources: dict[str, Callable[[], int]] = {}
_global_provider_set = False


def _make_reader() -> MetricReader:
    """Return the metric reader matching `settings.otel_exporter_endpoint`.

    Mirrors `tracing._make_exporter`: an empty endpoint means local
    dev, where periodically dumping the metric stream to stderr is more
    useful than silently buffering it; a set endpoint means OTLP HTTP,
    where the collector owns the aggregation.
    """
    endpoint = settings.otel_exporter_endpoint.strip()
    exporter: MetricExporter
    if not endpoint:
        exporter = ConsoleMetricExporter()
    else:
        exporter = OTLPMetricExporter(
            endpoint=endpoint.rstrip("/") + "/v1/metrics"
        )
    return PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=settings.otel_metric_export_interval_sec * 1000,
    )


def _build_instruments(meter: Meter) -> _Instruments:
    """Create every synchronous instrument on `meter`.

    Kept separate from `configure_metrics` so the instrument
    definitions — names, units, descriptions — read as one table.
    """
    return _Instruments(
        jobs_total=meter.create_counter(
            "research_jobs_total",
            unit="1",
            description=(
                "Research jobs that reached a terminal state, by "
                "terminal status and error type."
            ),
        ),
        job_duration_seconds=meter.create_histogram(
            "research_job_duration_seconds",
            unit="s",
            description=(
                "Wall-clock duration of a research job from start to "
                "terminal state."
            ),
            explicit_bucket_boundaries_advisory=list(_JOB_DURATION_BUCKETS),
        ),
        job_queue_wait_seconds=meter.create_histogram(
            "research_job_queue_wait_seconds",
            unit="s",
            description=(
                "Time a job spent accepted but not yet started — the "
                "wait behind `api_max_concurrent_jobs`. The USE 'wait' "
                "for the job queue."
            ),
            explicit_bucket_boundaries_advisory=list(_QUEUE_WAIT_BUCKETS),
        ),
        llm_cost_usd_total=meter.create_counter(
            "llm_cost_usd_total",
            unit="USD",
            description="Estimated LLM spend, by model.",
        ),
        llm_calls_total=meter.create_counter(
            "llm_calls_total",
            unit="1",
            description="Completed LLM calls, by model.",
        ),
        llm_retries_total=meter.create_counter(
            "llm_retries_total",
            unit="1",
            description=(
                "Anthropic SDK attempts discarded before a call "
                "succeeded (the SDK's own `retries_taken`), by model."
            ),
        ),
        llm_upstream_errors_total=meter.create_counter(
            "llm_upstream_errors_total",
            unit="1",
            description=(
                "LLM calls that failed after the SDK exhausted its "
                "retries, by model and HTTP status "
                "(`connection` when the call never got one)."
            ),
        ),
        rate_limit_rejections_total=meter.create_counter(
            "rate_limit_rejections_total",
            unit="1",
            description=(
                "Requests rejected with HTTP 429 by the per-key rate "
                "limiter, by limiter backend."
            ),
        ),
        degradations_total=meter.create_counter(
            "research_degradations_total",
            unit="1",
            description=(
                "Responses served in a degraded state, by rung of the "
                "degradation ladder (docs/reliability.md §5) and by the "
                "component that degraded. The denominator of the "
                "quality SLI."
            ),
        ),
        # --- The conventional GenAI family (ADR 0066) ------------------
        #
        # Names, units and instrument kinds are `semconv` constants read
        # from a pinned specification commit, never literals here: an
        # instrument named from memory produces telemetry that no
        # off-the-shelf GenAI dashboard parses, and it fails silently.
        genai_token_usage=meter.create_histogram(
            semconv.METRIC_CLIENT_TOKEN_USAGE,
            unit=semconv.UNIT_TOKEN,
            description="Input and output tokens used, by token type.",
            explicit_bucket_boundaries_advisory=list(_TOKEN_BUCKETS),
        ),
        genai_client_operation_duration=meter.create_histogram(
            semconv.METRIC_CLIENT_OPERATION_DURATION,
            unit=semconv.UNIT_SECOND,
            description="Duration of one provider-facing GenAI operation.",
            explicit_bucket_boundaries_advisory=list(_GENAI_DURATION_BUCKETS),
        ),
        genai_agent_duration=meter.create_histogram(
            semconv.METRIC_INVOKE_AGENT_DURATION,
            unit=semconv.UNIT_SECOND,
            description="End-to-end duration of one in-process agent invocation.",
            explicit_bucket_boundaries_advisory=list(_GENAI_DURATION_BUCKETS),
        ),
        genai_agent_inference_calls=meter.create_histogram(
            semconv.METRIC_INVOKE_AGENT_INFERENCE_CALLS,
            unit=semconv.UNIT_INFERENCE_CALL,
            description=(
                "Model calls one agent invocation issued, failed ones "
                "included."
            ),
            explicit_bucket_boundaries_advisory=list(_CALL_COUNT_BUCKETS),
        ),
        genai_agent_tool_calls=meter.create_histogram(
            semconv.METRIC_INVOKE_AGENT_TOOL_CALLS,
            unit=semconv.UNIT_TOOL_CALL,
            description=(
                "Tool calls one agent invocation triggered, failed ones "
                "included."
            ),
            explicit_bucket_boundaries_advisory=list(_CALL_COUNT_BUCKETS),
        ),
        genai_tool_duration=meter.create_histogram(
            semconv.METRIC_EXECUTE_TOOL_DURATION,
            unit=semconv.UNIT_SECOND,
            description="Duration of one tool execution.",
            explicit_bucket_boundaries_advisory=list(_GENAI_DURATION_BUCKETS),
        ),
        genai_workflow_duration=meter.create_histogram(
            semconv.METRIC_INVOKE_WORKFLOW_DURATION,
            unit=semconv.UNIT_SECOND,
            description="End-to-end duration of one workflow execution.",
            explicit_bucket_boundaries_advisory=list(_GENAI_DURATION_BUCKETS),
        ),
        # --- The stable HTTP server family (WO-A10) --------------------
        #
        # Two instruments, not three. The conventions define **no**
        # request counter, and that is not an omission: a histogram
        # already carries its own `count`, so `rate(count)` is the R of
        # RED and `rate(count) by status` is the E. Adding a
        # `http_requests_total` beside it would double the write volume
        # to answer a question the histogram answers, under a name no
        # standard dashboard reads. 03-ARCHITECTURE.md §5.3 asks for
        # "request count by route-template/method/status" and this is
        # where that count comes from.
        http_server_request_duration=meter.create_histogram(
            semconv.METRIC_HTTP_SERVER_REQUEST_DURATION,
            unit=semconv.UNIT_SECOND,
            description=(
                "Duration of one inbound HTTP request, by route "
                "template, method and response status."
            ),
            explicit_bucket_boundaries_advisory=list(_HTTP_DURATION_BUCKETS),
        ),
        http_server_active_requests=meter.create_up_down_counter(
            semconv.METRIC_HTTP_SERVER_ACTIVE_REQUESTS,
            unit=semconv.UNIT_REQUEST,
            description="Requests currently in flight on this worker.",
        ),
        # --- P0-WO08's contract event bridge (ADR 0083) ---------------
        trajectory_events_total=meter.create_counter(
            "trajectory_events_total",
            unit="1",
            description=(
                "Canonical trajectory events proposed to the ledger, by "
                "lane and by whether the append was accepted, rejected "
                "or answered from the idempotency index."
            ),
        ),
        trajectory_faults_total=meter.create_counter(
            "trajectory_faults_total",
            unit="1",
            description=(
                "Failures downstream of, or refused before, a trajectory "
                "append — durable sink writes, projections, artifact "
                "integrity and scope, and cost reconciliation — by stage "
                "and canonical error code."
            ),
        ),
    )


def configure_metrics(*, reader: MetricReader | None = None) -> None:
    """Initialize the meter provider and instruments once.

    No-op when `settings.enable_metrics` is False or when metrics are
    already configured, so it is safe to call from every entry point —
    same contract as `configure_tracing`.

    Args:
        reader: Metric reader to install instead of the exporting one
            `settings.otel_exporter_endpoint` selects. Tests pass an
            `InMemoryMetricReader`; production leaves it `None`.
    """
    global _provider, _meter, _instruments, _global_provider_set
    if _instruments is not None or not settings.enable_metrics:
        return

    resource = Resource.create({"service.name": settings.otel_service_name})
    metric_reader = reader if reader is not None else _make_reader()
    provider = MeterProvider(metric_readers=[metric_reader], resource=resource)

    if not _global_provider_set:
        # Best-effort only, and never read back: see the module
        # docstring on why this module owns its provider rather than
        # deferring to OTel's set-once global.
        otel_metrics.set_meter_provider(provider)
        _global_provider_set = True

    _provider = provider
    _meter = provider.get_meter(_METER_NAME)
    _instruments = _build_instruments(_meter)
    log.info(
        "metrics_configured",
        extra={
            "endpoint": settings.otel_exporter_endpoint or "console",
            "service": settings.otel_service_name,
            "export_interval_sec": settings.otel_metric_export_interval_sec,
        },
    )


def metrics_enabled() -> bool:
    """Whether instruments are live — i.e. recordings will be kept."""
    return _instruments is not None


def register_runtime_gauges(
    *,
    active_jobs: Callable[[], int],
    abandoned_node_threads: Callable[[], int],
) -> None:
    """Attach the two observable gauges to the live accounting.

    Called from the API lifespan with callables that read the *existing*
    sources `/healthz` reports from — this worker's in-flight job task
    set and `src.cancellation.abandoned_node_count()`. Passing callables
    rather than importing app state keeps this module free of any
    knowledge of the API layer, and guarantees the gauge and the health
    endpoint can never drift apart into two counters.

    A no-op when metrics are disabled, so the lifespan can call it
    unconditionally. Calling it again rebinds the sources rather than
    registering a second set of instruments. Callbacks must not raise
    and must not block: the SDK invokes them on its export thread every
    collection interval.

    ## The two queue gauges, and what they are worth

    WO-A07 added `research_queue_depth` and
    `research_queue_saturation_ratio` here rather than at the
    semaphore, derived from the *same* `active_jobs` callable, because
    the baseline's complaint was that saturation is invisible until the
    ceiling is hit — and a second counter at the acquire site could
    disagree with `/healthz`, which is the drift ADR 0049 avoided for
    the first two gauges.

    The honest limitation, stated rather than papered over:
    `active_jobs` is queued + running + *abandoned node threads*, so
    `depth = active - ceiling` counts an abandoned thread (ADR 0047) as
    though it still occupied a permit. It does not, so depth is an
    **upper bound** on the number of jobs actually waiting. Abandoned
    threads are rare, are separately observable on
    `research_abandoned_node_threads`, and a saturation signal that
    errs toward "more contended than it is" is the right direction for
    the error to point.

    Args:
        active_jobs: Returns this worker's current job count —
            queued + running + abandoned node threads (ADR 0047).
        abandoned_node_threads: Returns the node threads this worker
            gave up waiting on that are still executing.
    """
    if _instruments is None or _meter is None:
        return

    already_registered = bool(_gauges)
    _gauge_sources["research_active_jobs"] = active_jobs
    _gauge_sources["research_abandoned_node_threads"] = abandoned_node_threads
    if already_registered:
        return

    def _observer(name: str) -> Callable[[CallbackOptions], Iterable[Observation]]:
        def _observe(options: CallbackOptions) -> Iterable[Observation]:
            source = _gauge_sources.get(name)
            # The source is unbound only between `shutdown_metrics` and
            # a re-register; reporting nothing beats reporting a zero
            # the worker cannot vouch for.
            return [] if source is None else [Observation(source())]

        return _observe

    _gauges.append(
        _meter.create_observable_gauge(
            "research_active_jobs",
            callbacks=[_observer("research_active_jobs")],
            unit="1",
            description=(
                "Jobs this worker currently owns (queued + running) plus "
                "the node threads it abandoned but that are still "
                "executing — the same figure /healthz reports."
            ),
        )
    )
    _gauges.append(
        _meter.create_observable_gauge(
            "research_abandoned_node_threads",
            callbacks=[_observer("research_abandoned_node_threads")],
            unit="1",
            description=(
                "Node threads whose drain budget expired and that this "
                "worker no longer waits for (ADR 0047)."
            ),
        )
    )

    def _queue_observer(
        derive: Callable[[int, int], float],
    ) -> Callable[[CallbackOptions], Iterable[Observation]]:
        """Build a callback deriving a queue figure from `active_jobs`.

        The ceiling is read at collection time, not closed over, so a
        deployment that changes `api_max_concurrent_jobs` and restarts
        does not need this registration to be re-run to be correct.
        """

        def _observe(options: CallbackOptions) -> Iterable[Observation]:
            source = _gauge_sources.get("research_active_jobs")
            if source is None:
                return []
            ceiling = max(1, settings.api_max_concurrent_jobs)
            return [Observation(derive(source(), ceiling))]

        return _observe

    _gauges.append(
        _meter.create_observable_gauge(
            "research_queue_depth",
            callbacks=[_queue_observer(lambda active, ceiling: max(0, active - ceiling))],
            unit="1",
            description=(
                "Jobs this worker owns that are waiting for a "
                "concurrency permit rather than running. An upper "
                "bound — see `register_runtime_gauges`."
            ),
        )
    )
    _gauges.append(
        _meter.create_observable_gauge(
            "research_queue_saturation_ratio",
            callbacks=[_queue_observer(lambda active, ceiling: active / ceiling)],
            unit="1",
            description=(
                "Owned jobs divided by `api_max_concurrent_jobs`. The "
                "USE 'utilisation'/'saturation' pair in one series: 1.0 "
                "means the ceiling is exactly full, above 1.0 means "
                "work is queueing behind it."
            ),
        )
    )


def record_job_terminal(
    *,
    status: str,
    error_type: str | None,
    duration_sec: float | None,
    kind: str | None = None,
    cost_cap_status: str = "",
    queue_wait_sec: float | None = None,
) -> None:
    """Record one job reaching a terminal state.

    Bumps `research_jobs_total` and, when the job actually started,
    observes `research_job_duration_seconds` and
    `research_job_queue_wait_seconds`. Called from the runner's single
    terminal-write choke point so every terminal path — success,
    failure, timeout, cost cap, HITL timeout, HITL cancel, shutdown
    cancel — is covered by construction.

    ## Two corrections WO-A07 made here

    **`kind` is now an attribute.** Without it, research jobs and
    guided-read sessions share one series, so no session SLO can be
    built and a session regression is invisible inside the research
    volume. It is safe as an attribute precisely because `JobKind` is a
    two-member `Literal` (ADR 0057) rather than a free string.

    **A degraded close no longer reports as a plain success.** When a
    session hits its cost ceiling under
    `learning_session_cost_cap_behavior=degraded_close` (ADR 0062) the
    job really does end `succeeded` with no error — the learner gets a
    polite close, and the API contract says so. But recording that as
    `status="succeeded", error_type="none"` made budget exhaustion
    indistinguishable from a clean run in the only signal an operator
    watches, so the metric's `status` becomes `degraded_close`. It is a
    metric outcome, not a `JobStatus`; nothing on the wire changes.

    Args:
        status: Terminal `JobStatus` value (`succeeded`, `failed`,
            `cancelled`).
        error_type: The job's `error_type`, or `None` on non-failure
            paths; recorded as `"none"` so every series has the same
            attribute shape.
        duration_sec: `Job.elapsed_sec()`. `None` means the job never
            started, in which case there is no duration to observe and
            recording a zero would drag the histogram's low bucket down
            with a run that did no work.
        kind: `Job.kind`. `None` from a caller that predates the field
            is recorded as `"unknown"` rather than omitted, so the
            series keeps one shape — the same reasoning as `NO_ERROR`.
        cost_cap_status: `Job.cost_cap_status` (ADR 0062). Only
            `degraded_close` changes what is recorded.
        queue_wait_sec: Seconds between acceptance and start. `None`
            when the job never started.
    """
    instruments = _instruments
    if instruments is None:
        return
    outcome = (
        STATUS_DEGRADED_CLOSE
        if cost_cap_status == STATUS_DEGRADED_CLOSE
        else status
    )
    kind_attr = kind or "unknown"
    instruments.jobs_total.add(
        1,
        {
            "status": outcome,
            "error_type": error_type or NO_ERROR,
            ATTR_KIND: kind_attr,
        },
    )
    if duration_sec is not None:
        instruments.job_duration_seconds.record(
            duration_sec, {"status": outcome, ATTR_KIND: kind_attr}
        )
    if queue_wait_sec is not None:
        instruments.job_queue_wait_seconds.record(
            queue_wait_sec, {ATTR_KIND: kind_attr}
        )


def record_genai_client_call(
    *,
    request_model: str,
    response_model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_sec: float,
    error_type: str | None,
) -> None:
    """Record one provider-facing model call, conventionally.

    The conventional counterpart to `record_llm_usage`, and deliberately
    a second function rather than an extension of it. `record_llm_usage`
    is called from `costs.record_llm_call`, which is the cost choke
    point and knows nothing about response models, latency or failures;
    this is called from `src.llm`'s span wrapper, which knows all three
    because it is holding the span that measured them. Cost therefore
    stays single-sourced and this adds no second opinion about it —
    there is no conventional cost metric to have one with
    (`02-STANDARDS.md` §1.3).

    `gen_ai.client.operation.duration`'s *count* is the conventional
    reading of "how many model calls" and is what `llm_calls_total`
    aliases.

    Args:
        request_model: The model asked for.
        response_model: The model that answered, when the provider said.
            Omitted from the attributes when `None` — recording the
            request model in its place would invent a fact.
        input_tokens: Non-cached input tokens, or `None` on a failed
            call where `usage` never existed.
        output_tokens: Output tokens, or `None` for the same reason.
        duration_sec: Wall clock for the whole call chain, retries
            included — the same figure the span measured.
        error_type: Exception class name when the call failed, else
            `None`.
    """
    instruments = _instruments
    if instruments is None:
        return
    attributes: dict[str, str] = {
        semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_CHAT,
        semconv.GEN_AI_PROVIDER_NAME: semconv.PROVIDER_ANTHROPIC,
        semconv.GEN_AI_REQUEST_MODEL: request_model,
    }
    if response_model:
        attributes[semconv.GEN_AI_RESPONSE_MODEL] = response_model
    instruments.genai_client_operation_duration.record(
        duration_sec,
        {**attributes, semconv.ERROR_TYPE: error_type or NO_ERROR_TYPE},
    )
    if input_tokens is not None:
        instruments.genai_token_usage.record(
            input_tokens,
            {**attributes, semconv.GEN_AI_TOKEN_TYPE: semconv.TOKEN_TYPE_INPUT},
        )
    if output_tokens is not None:
        instruments.genai_token_usage.record(
            output_tokens,
            {**attributes, semconv.GEN_AI_TOKEN_TYPE: semconv.TOKEN_TYPE_OUTPUT},
        )


def record_agent_invocation(
    *,
    agent_name: str,
    duration_sec: float,
    inference_calls: int,
    tool_calls: int,
    error_type: str | None,
) -> None:
    """Record one graph node's invocation, conventionally.

    Emits all three of the agent-level instruments together because the
    conventions say the two counters SHOULD be reported alongside the
    `invoke_agent` span for the same invocation — reporting a duration
    without the calls that filled it is what makes "this node took 90
    seconds" unactionable.

    Args:
        agent_name: The graph node's name. Bounded: node names are
            literals in `src/graph/`.
        duration_sec: Wall clock for the node.
        inference_calls: Model calls the node made, failures included.
        tool_calls: Tool executions the node triggered, failures
            included.
        error_type: Exception class name when the node raised, else
            `None`.
    """
    instruments = _instruments
    if instruments is None:
        return
    identity = {semconv.GEN_AI_AGENT_NAME: agent_name}
    instruments.genai_agent_duration.record(
        duration_sec, {**identity, semconv.ERROR_TYPE: error_type or NO_ERROR_TYPE}
    )
    instruments.genai_agent_inference_calls.record(inference_calls, identity)
    instruments.genai_agent_tool_calls.record(tool_calls, identity)


def record_tool_execution(
    *, tool_name: str, duration_sec: float, error_type: str | None
) -> None:
    """Record one tool execution, conventionally.

    Args:
        tool_name: A `semconv.TOOL_*` constant — never caller input,
            which is what bounds this series.
        duration_sec: Wall clock for the tool call.
        error_type: Exception class name when the tool raised, else
            `None`.
    """
    instruments = _instruments
    if instruments is None:
        return
    instruments.genai_tool_duration.record(
        duration_sec,
        {
            semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_EXECUTE_TOOL,
            semconv.GEN_AI_TOOL_NAME: tool_name,
            semconv.ERROR_TYPE: error_type or NO_ERROR_TYPE,
        },
    )


def record_workflow_invocation(
    *, workflow_name: str, duration_sec: float, error_type: str | None
) -> None:
    """Record one whole run, conventionally.

    The conventional reading of `research_job_duration_seconds`, which
    it aliases for one release. The two measure slightly different
    spans of time and that is deliberate: the job histogram measures
    from acceptance through the terminal write, while this measures the
    workflow execution the span bounds. A dashboard comparing them sees
    the queue wait and the terminal persistence, which is a useful
    difference rather than a discrepancy.

    Args:
        workflow_name: `semconv.WORKFLOW_RESEARCH` or `WORKFLOW_SESSION`.
        duration_sec: Wall clock for the workflow span.
        error_type: Exception class name when the run raised, else
            `None`.
    """
    instruments = _instruments
    if instruments is None:
        return
    instruments.genai_workflow_duration.record(
        duration_sec,
        {
            semconv.GEN_AI_WORKFLOW_NAME: workflow_name,
            semconv.ERROR_TYPE: error_type or NO_ERROR_TYPE,
        },
    )


def record_http_active_request(*, method: str, scheme: str, delta: int) -> None:
    """Move `http.server.active_requests` by `delta` (WO-A10).

    Called twice per request — `+1` before the application is entered
    and `-1` from the middleware's `finally`, so a request that raises
    still decrements. The pairing is the whole contract: an UpDownCounter
    that only ever counts up reads as a permanently saturated worker and
    is worse than no instrument at all.

    Args:
        method: Output of `semconv.http_request_method`, never the raw
            method — this attribute is attacker-controlled on an open
            port and `_OTHER` is what bounds it.
        scheme: `http` or `https`.
        delta: `+1` on entry, `-1` on exit.
    """
    instruments = _instruments
    if instruments is None:
        return
    instruments.http_server_active_requests.add(
        delta,
        {
            semconv.HTTP_REQUEST_METHOD: method,
            semconv.URL_SCHEME: scheme,
        },
    )


def record_http_server_request(
    *,
    method: str,
    route: str | None,
    status_code: int,
    scheme: str,
    duration_sec: float,
    error_type: str | None,
) -> None:
    """Record one served HTTP request (WO-A10).

    The RED triple for the HTTP surface, out of one instrument: the
    histogram's `count` is the rate, `count` split by
    `http.response.status_code` is the error rate, and its buckets are
    the duration. See `_build_instruments` for why there is no separate
    counter.

    Args:
        method: Output of `semconv.http_request_method`.
        route: The matched route **template** (`/research/{job_id}`), or
            `None` when nothing matched. Omitted from the attributes in
            that case rather than filled with the raw path or a
            placeholder: the conventions mark `http.route` conditionally
            required precisely so that "no route" is expressible, and a
            raw path here would put one series per job id into the
            store, which is the failure the attribute exists to prevent.
        status_code: The response status. An `int`, because the
            conventions type it as one and a string would sort `"1000"`
            before `"200"` in every consumer.
        scheme: `http` or `https`.
        duration_sec: Wall clock from the first byte of the request to
            the last byte of the response, in **seconds**.
        error_type: The exception class name when the request died
            before a response, else `None`. `"none"` is recorded for a
            successful request, and the status code as a string for a
            5xx — see `_http_error_type` in `src/api/app.py`, which is
            where that decision is made and explained.
    """
    instruments = _instruments
    if instruments is None:
        return
    attributes: dict[str, str | int] = {
        semconv.HTTP_REQUEST_METHOD: method,
        semconv.HTTP_RESPONSE_STATUS_CODE: status_code,
        semconv.URL_SCHEME: scheme,
        semconv.ERROR_TYPE: error_type or NO_ERROR_TYPE,
    }
    if route is not None:
        attributes[semconv.HTTP_ROUTE] = route
    instruments.http_server_request_duration.record(duration_sec, attributes)


def record_llm_usage(*, model: str, cost_usd: float) -> None:
    """Record one completed LLM call and its estimated cost.

    Called from `src.observability.costs.record_llm_call`, which every
    LLM call site in the repo already funnels through — agent nodes
    included — so one wiring point covers them all. Unlike the per-run
    accumulator this is process-wide and survives the run: the counters
    answer "what is this deployment spending, by model", which no
    per-run `ContextVar` can.

    Recorded only in a process that configured a provider, which today
    means the API workers — see this module's "Which processes emit"
    note. `make run` and `make eval` still log and accumulate cost the
    way they always did.

    Args:
        model: Model id the call was billed against.
        cost_usd: Estimated cost from `estimate_cost`.
    """
    instruments = _instruments
    if instruments is None:
        return
    attributes = {"model": model}
    instruments.llm_calls_total.add(1, attributes)
    instruments.llm_cost_usd_total.add(cost_usd, attributes)


def record_llm_retries(*, model: str, retries: int) -> None:
    """Record attempts the Anthropic SDK discarded before one succeeded.

    Called from `src.observability.costs.record_llm_call` with the SDK's
    own `retries_taken`, which `src.llm.call_llm` reads off the raw
    response (ADR 0051). Before this, SDK-internal retries were entirely
    invisible: the retry line is logged by `anthropic._base_client` at
    INFO, which the log config demoted to WARNING, so a rate-limited
    fleet looked like slow calls and nothing else.

    No app-level retry loop is involved — this counts what the SDK
    already did, so the count stays correct if `anthropic_max_retries`
    changes.

    Args:
        model: Model id the call was billed against.
        retries: `retries_taken` for one call. Callers skip the zero
            case, but a zero here is harmless — a counter `add(0)` is a
            no-op that still creates the series.
    """
    instruments = _instruments
    if instruments is None:
        return
    instruments.llm_retries_total.add(retries, {"model": model})


def record_llm_upstream_error(*, model: str, status: str) -> None:
    """Record an LLM call that failed after the SDK gave up retrying.

    The companion to `record_llm_retries`: retries that eventually
    succeed cost latency, retries that run out cost the whole node. Both
    have to be visible for "the API is degraded" to be answerable
    without reading logs (ADR 0051).

    Args:
        model: Model id the failed call targeted.
        status: HTTP status as a string, or `"connection"` when the
            call failed before any response (timeout, DNS, reset).
            Bounded cardinality either way — never the message text.
    """
    instruments = _instruments
    if instruments is None:
        return
    instruments.llm_upstream_errors_total.add(
        1, {"model": model, "status": status}
    )


def record_rate_limit_rejection(*, backend: str) -> None:
    """Record one request rejected with HTTP 429 by the rate limiter.

    Attributed by limiter backend (`memory` / `redis`, ADR 0037) rather
    than by principal: `key_id` is unbounded operator-supplied
    cardinality, and a metric label is the wrong place to carry it —
    the 429's structured log line already names the key.

    Args:
        backend: The limiter implementation that rejected the request.
    """
    instruments = _instruments
    if instruments is None:
        return
    instruments.rate_limit_rejections_total.add(1, {"backend": backend})


def record_degradation_rung(*, rung: str, component: str) -> None:
    """Record one response served in a degraded state.

    The measurement behind the quality SLI: `docs/reliability.md` §2
    defines quality as *the proportion of responses served in an
    undegraded state*, and this is the numerator's complement. §5's
    ladder is the `rung` vocabulary and this counter is what turns that
    table from a list of log events into something §4's burn-rate
    machinery can be pointed at unchanged.

    Not named `record_degradation`, deliberately.
    `src.resilience.record_degradation` already owns that name and does
    a different job — it logs `resilience_degraded` and keeps the
    in-process counter ADR 0068 shipped. This one only moves the OTel
    instrument, which is what lets every *other* rung keep its own
    distinct log event instead of being folded onto
    `resilience_degraded`. That fold-in would have been the obvious
    reading of §7, and it is wrong: `deploy/observability/log-alerts.yml`
    pages at threshold 1 in 15m on `resilience_degraded`, so routing a
    Postgres cache blip through it would wake somebody for a rung that
    is working as designed.

    Unknown values are recorded under `DEGRADATION_UNREGISTERED` rather
    than passed through. A metric attribute is the one place an
    unregistered string is expensive rather than merely untidy — it
    mints a series per distinct value, forever — and a helper that
    raised instead would turn an observability bug into a job failure
    at a call site whose entire purpose is to survive a failure. The
    static check in `tests/test_degradation_ladder.py` is the
    enforcement; this is the containment.

    Args:
        rung: A member of `DEGRADATION_RUNGS` — which rung of the
            ladder was taken, not which call site took it.
        component: A member of `DEGRADATION_COMPONENTS` — the subsystem
            that degraded, at the granularity a runbook is written for.
    """
    instruments = _instruments
    if instruments is None:
        return
    if rung not in DEGRADATION_RUNGS:
        log.warning(
            "degradation_rung_unregistered",
            extra={"rung": rung, "component": component},
        )
        rung = DEGRADATION_UNREGISTERED
    if component not in DEGRADATION_COMPONENTS:
        log.warning(
            "degradation_rung_unregistered",
            extra={"rung": rung, "component": component},
        )
        component = DEGRADATION_UNREGISTERED
    instruments.degradations_total.add(1, {"rung": rung, "component": component})


#: Lanes a trajectory event can be recorded on. Bounded by construction
#: — a bridge belongs to the research path or the guided-learning path —
#: which is what makes it safe as a metric attribute.
TRAJECTORY_LANES: Final[frozenset[str]] = frozenset({"research", "guided_learning"})

#: Outcomes of one proposed append. `deduplicated` is not a failure: it
#: is the idempotency index answering a retry with the event it already
#: stored (RFC 10 §11.2), and counting it separately from `accepted` is
#: how a retry storm becomes visible instead of looking like traffic.
TRAJECTORY_OUTCOMES: Final[frozenset[str]] = frozenset(
    {"accepted", "deduplicated", "rejected"}
)

#: Stages a trajectory fault can be attributed to. Every one of them is
#: *downstream of, or upstream of*, the ledger accept — never the accept
#: itself, because an append that fails is a `rejected` event above.
TRAJECTORY_FAULT_STAGES: Final[frozenset[str]] = frozenset(
    {
        "sink_write",
        "projection",
        "artifact_integrity",
        "artifact_access",
        "cost_reconciliation",
        "chain_verification",
    }
)


def record_trajectory_event(*, lane: str, outcome: str) -> None:
    """Record one proposed canonical trajectory event (ADR 0083).

    Args:
        lane: `research` or `guided_learning`.
        outcome: `accepted`, `deduplicated`, or `rejected`.
    """
    instruments = _instruments
    if instruments is None:
        return
    instruments.trajectory_events_total.add(1, {"lane": lane, "outcome": outcome})


def record_trajectory_fault(*, stage: str, error_type: str) -> None:
    """Record one failure around the trajectory bridge (ADR 0083).

    Attributed by `error_type` drawn from ADR 0064's closed registry
    rather than by exception class, for the same reason every other
    failure metric in this module is: a class name is a refactor away
    from renaming a series, and the fault tier asserts the code, the log
    event and this point together.

    Args:
        stage: A member of `TRAJECTORY_FAULT_STAGES`.
        error_type: A member of `src.errors.ERROR_CODES`.
    """
    instruments = _instruments
    if instruments is None:
        return
    instruments.trajectory_faults_total.add(
        1, {"stage": stage, "error_type": error_type}
    )


def shutdown_metrics(*, timeout_millis: float = _SHUTDOWN_BUDGET_MS) -> None:
    """Flush pending measurements and tear the provider down.

    Called from the API lifespan's teardown. Disarming `_instruments`
    *first* is deliberate: provider shutdown makes every instrument
    inert anyway, and a job finishing during the drain would otherwise
    record into a dying pipeline. A no-op when nothing is configured.

    Failures are logged, never raised — losing the last export window
    must not turn a clean shutdown into a crashing one.

    Args:
        timeout_millis: Budget for the final export. See
            `_SHUTDOWN_BUDGET_MS` for why it is as small as it is.
    """
    global _provider, _meter, _instruments
    provider = _provider
    _instruments = None
    _meter = None
    _provider = None
    _gauges.clear()
    _gauge_sources.clear()
    if provider is None:
        return
    try:
        provider.shutdown(timeout_millis=timeout_millis)
    except Exception:
        log.warning("metrics_shutdown_failed", exc_info=True)
