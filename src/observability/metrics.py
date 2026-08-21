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

| Instrument                       | Kind             | Attributes         |
|----------------------------------|------------------|--------------------|
| `research_jobs_total`            | counter          | status, error_type |
| `research_job_duration_seconds`  | histogram        | status             |
| `research_active_jobs`           | observable gauge | -                  |
| `research_abandoned_node_threads`| observable gauge | -                  |
| `llm_cost_usd_total`             | counter (float)  | model              |
| `llm_calls_total`                | counter          | model              |
| `llm_retries_total`              | counter          | model              |
| `llm_upstream_errors_total`      | counter          | model, status      |
| `rate_limit_rejections_total`    | counter          | backend            |

The two LLM error/retry counters arrived with ADR 0051: Anthropic SDK
retries (429 / 529 / timeouts) were invisible — no app log, the SDK's
own retry line demoted below threshold, no metric — so a throttled
fleet was indistinguishable from a slow one.

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
check. That is deliberate, not an oversight: four of the nine
instruments describe a *server* (job outcomes, concurrency, 429s), and
a one-shot CLI run has no steady state for the remaining five to
sample — it would spin an export thread up and tear it down inside one
export interval. Tracing differs because `get_tracer()` configures
lazily on first span, which is what makes `traced_node` work under
`make eval`. If the eval runner ever needs the spend counters, the fix
is one `configure_metrics()` call at its entry point, not a lazy
configure on the record path (that would put an `enable_metrics` read
and a possible provider build on every LLM call).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

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
from src.observability.logging import get_logger

log = get_logger(__name__)

__all__ = [
    "configure_metrics",
    "metrics_enabled",
    "record_job_terminal",
    "record_llm_retries",
    "record_llm_upstream_error",
    "record_llm_usage",
    "record_rate_limit_rejection",
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
    llm_cost_usd_total: Counter
    llm_calls_total: Counter
    llm_retries_total: Counter
    llm_upstream_errors_total: Counter
    rate_limit_rejections_total: Counter


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
    registering a second pair of instruments. Callbacks must not raise
    and must not block: the SDK invokes them on its export thread every
    collection interval.

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


def record_job_terminal(
    *,
    status: str,
    error_type: str | None,
    duration_sec: float | None,
) -> None:
    """Record one job reaching a terminal state.

    Bumps `research_jobs_total` and, when the job actually started,
    observes `research_job_duration_seconds`. Called from the runner's
    single terminal-write choke point so every terminal path — success,
    failure, timeout, cost cap, HITL timeout, HITL cancel, shutdown
    cancel — is covered by construction.

    Args:
        status: Terminal `JobStatus` value (`succeeded`, `failed`,
            `cancelled`).
        error_type: The job's `error_type`, or `None` on non-failure
            paths; recorded as `"none"` so every series has the same
            attribute shape.
        duration_sec: `Job.elapsed_sec()`. `None` means the job never
            started, in which case there is no duration to observe and
            recording a zero would drag the histogram's low bucket
            down with a run that did no work.
    """
    instruments = _instruments
    if instruments is None:
        return
    instruments.jobs_total.add(
        1, {"status": status, "error_type": error_type or NO_ERROR}
    )
    if duration_sec is not None:
        instruments.job_duration_seconds.record(
            duration_sec, {"status": status}
        )


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
