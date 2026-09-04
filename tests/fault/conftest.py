"""The fault tier's shared machinery: how the triple is observed.

Every test in this directory asserts the same three things about one
injected failure, and this module is the only place that knows how to
look at each of them:

1. **The error code** — a member of `src.errors.ERROR_CODES`, read off
   whatever surface the failure actually reaches (`job.error_type`, the
   HTTP envelope's `error.code`, the redriver's write). Never a class
   name, never a message.
2. **The log event** — a member of `src.observability.logging.KNOWN_EVENTS`,
   matched on `record.message`, which is where `get_logger`'s callers
   put the event name.
3. **The metric** — a real aggregated data point out of an
   `InMemoryMetricReader`, the same object the OTLP exporter would
   serialize.

Asserting one leg is what unit tests already do; the reason this tier
exists is that the three contracts are only mutually enforcing when a
single failure is asserted on all three at once. A refactor that
renames a code, drops a log line or forks a metric series breaks
exactly one leg, and a test that watches one leg cannot see it.

The observer is a fixture rather than an importable helper on purpose:
`tests/` is importable only through the sys.path entry pytest happens
to insert, and `tests/conftest.py` already declines to rest anything on
that.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from src.api.jobs import Job
from src.config import Settings
from src.errors import ERROR_CODES
from src.observability import metrics as metrics_module
from src.observability.logging import KNOWN_EVENTS

#: Instrument names as they exist on `main` today.
#:
#: WO-A07 is renaming these to the OpenTelemetry GenAI semantic
#: conventions in parallel with this work order, and has been asked to
#: keep the current names as aliases for one release. This tier
#: therefore asserts the names that exist on its own branch: asserting
#: on `gen_ai.*` would make every test here red until A07 merged, and
#: asserting on the aliases is what proves the alias promise was kept.
#: When the alias window closes, this set moves and the tests below
#: follow it — which is the point of naming them in one place.
LIVE_INSTRUMENTS: frozenset[str] = frozenset(
    {
        "research_jobs_total",
        "research_job_duration_seconds",
        "llm_cost_usd_total",
        "llm_calls_total",
        "llm_retries_total",
        "llm_upstream_errors_total",
        "rate_limit_rejections_total",
        # WO-A10's HTTP RED histogram. Stable-conventions naming, and
        # the one instrument in this set that can see a failure which
        # never became a job — which is exactly the gap
        # `test_redis_faults.py`'s submit scenario had recorded as an
        # empty metric leg.
        "http.server.request.duration",
    }
)


@dataclass(frozen=True)
class TripleObserver:
    """One handle over the three channels a failure has to show up on.

    Holds the metric reader and the log capture together so a test
    reads as one statement about one failure rather than as three
    unrelated assertions that happen to sit in the same function.
    """

    reader: InMemoryMetricReader
    caplog: pytest.LogCaptureFixture

    # ---- logs ---------------------------------------------------------

    def records(self, event: str) -> list[logging.LogRecord]:
        """Every captured record whose event name is `event`.

        `record.message` rather than `record.getMessage()`: these lines
        carry no `%`-args, and `message` is what `JsonFormatter` reads
        to decide whether the name is registered.
        """
        return [r for r in self.caplog.records if r.message == event]

    def one_record(self, event: str) -> logging.LogRecord:
        """The single record for `event`, failing if there is not exactly one."""
        found = self.records(event)
        assert len(found) == 1, (
            f"expected exactly one {event!r} record, got {len(found)}; "
            f"captured events: {sorted({r.message for r in self.caplog.records})}"
        )
        return found[0]

    # ---- metrics ------------------------------------------------------

    def points(self, instrument: str) -> list[Any]:
        """Every data point currently aggregated for `instrument`."""
        data = self.reader.get_metrics_data()
        if data is None:
            return []
        return [
            point
            for resource_metric in data.resource_metrics
            for scope_metric in resource_metric.scope_metrics
            for metric in scope_metric.metrics
            if metric.name == instrument
            for point in metric.data.data_points
        ]

    def instrument_names(self) -> set[str]:
        """Every metric name the reader can currently collect."""
        data = self.reader.get_metrics_data()
        if data is None:
            return set()
        return {
            metric.name
            for resource_metric in data.resource_metrics
            for scope_metric in resource_metric.scope_metrics
            for metric in scope_metric.metrics
        }

    def point(self, instrument: str, **attributes: Any) -> Any:
        """The one point of `instrument` carrying at least `attributes`.

        Matching on the named attributes rather than on the whole set,
        with **exactly one** match required. The uniqueness half is
        what catches the failure an exact match would catch: a series
        that forked — `error_type` splitting in two, say — produces two
        points that both carry the named attributes, and this fails.

        The reason it is not an exact match is coordination, not
        convenience. WO-A07 is adding a `kind` attribute to the job
        metrics in this same wave, and an exact match would turn every
        `research_jobs_total` assertion in this tier red the day it
        merged — fifteen tests to update for one deliberate change.
        The exact shape is pinned once instead, in
        `test_triple_contract.py`, which is the single place A07
        touches.
        """
        candidates = self.points(instrument)
        matches = [
            point
            for point in candidates
            if all(dict(point.attributes).get(key) == value for key, value in attributes.items())
        ]
        assert len(matches) == 1, (
            f"expected exactly one {instrument} point carrying {attributes}, got "
            f"{[dict(p.attributes) for p in candidates]}"
        )
        return matches[0]

    # ---- the triple ---------------------------------------------------

    def assert_triple(
        self,
        *,
        code: str | None,
        event: str,
        instrument: str,
        attributes: Mapping[str, Any],
        value: float = 1,
    ) -> logging.LogRecord:
        """Assert one failure landed on all three contracts.

        `code` is the value the *caller has already read off the
        system* — the job record, the response envelope, the store row.
        Passing it here does two further jobs: it proves the value is
        inside the closed set, and where the log line carries an
        `error_type` field it proves the log agrees with the surface
        the client saw. Those two used to disagree, which is the
        finding this whole phase starts from.

        Args:
            code: The observed `AppError.code`, or `None` for a fault
                whose contract is that the job does *not* acquire one.
            event: The log event name; must be registered.
            instrument: The metric instrument; must be one that exists.
            attributes: The exact attribute set of the point expected
                to have moved.
            value: Expected counter value, or minimum histogram count.

        Returns:
            The log record, so a caller can go on to assert its fields.
        """
        if code is not None:
            assert code in ERROR_CODES, f"{code!r} is not a registered error code"
        assert event in KNOWN_EVENTS, f"{event!r} is not a registered log event"
        assert instrument in LIVE_INSTRUMENTS, (
            f"{instrument!r} is not an instrument that exists on this branch"
        )

        record = self.one_record(event)
        logged_code = getattr(record, "error_type", None)
        if code is not None and logged_code is not None:
            assert logged_code == code, (
                f"the {event!r} line says error_type={logged_code!r} while the "
                f"surface says {code!r}; the log and the client contract have forked"
            )

        point = self.point(instrument, **dict(attributes))
        # Counters expose `value`; histograms expose `count` + `sum`.
        observed = getattr(point, "value", None)
        if observed is None:
            observed = point.count
        assert observed == value, (
            f"{instrument}{dict(attributes)} = {observed}, expected {value}"
        )
        return record

    def assert_not_recorded(self, instrument: str) -> None:
        """Assert `instrument` has no points at all.

        The negative half of the triple, and not a weaker claim: some
        of the faults below are invisible to the job counter *by
        construction* — a submit that never became a job cannot move a
        job metric — and writing that down is what stops a later change
        from quietly making the fault visible somewhere nobody looks.
        """
        recorded = self.points(instrument)
        assert recorded == [], (
            f"expected {instrument} to have recorded nothing, got "
            f"{[dict(p.attributes) for p in recorded]}"
        )


@pytest.fixture
def triple(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TripleObserver]:
    """Arm the metric pipeline and the log capture for one fault.

    The metrics module is configured against an `InMemoryMetricReader`
    the way `tests/test_otel_metrics.py` does it — `enable_metrics` is
    off in the shipped defaults, so the flag is forced on this module's
    `settings` handle and the provider is torn down afterwards so
    instruments never leak into the next test.

    `caplog` is opened at DEBUG on the *root* logger rather than on a
    named one. Several of the events below are INFO
    (`api_job_cancelled`) and the root's level is whatever
    `settings.log_level` made it, so a per-logger `at_level` would
    filter them out before caplog's handler ever saw them.
    """
    metrics_module.shutdown_metrics()
    monkeypatch.setattr(
        metrics_module,
        "settings",
        Settings(enable_metrics=True, otel_exporter_endpoint=""),
    )
    reader = InMemoryMetricReader()
    metrics_module.configure_metrics(reader=reader)
    with caplog.at_level(logging.DEBUG):
        yield TripleObserver(reader=reader, caplog=caplog)
    metrics_module.shutdown_metrics()


@pytest.fixture
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse the runner's retry backoff to nothing.

    `_persist_terminal` and `_put_terminal_event` each sleep `0.1 *
    attempt` between attempts. Three attempts apiece is 0.6s of pure
    waiting per failing job, and this tier drives several of them; the
    behaviour under test is the retry *count* and the escalation to an
    ERROR, neither of which the delay contributes to.
    """
    import src.api.runner as runner_module

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(runner_module.asyncio, "sleep", _instant)


class ScriptedWorkflow:
    """A compiled-graph stand-in that yields updates, then fails on cue.

    One stub rather than one per scenario, because the *graph* is never
    what these tests are about: every fault below is injected either
    into a dependency the runner talks to or into the exception a node
    hands back, and the graph's only job is to deliver it at a chosen
    moment. Two moments are distinguishable and both matter:

    - `raises` alone — the failure arrives before any node update, so
      the runner's merged state is empty and there is no artifact to
      preserve;
    - `updates` then `raises` — the failure arrives after a node has
      already produced something, which is the case where "the job
      failed" and "the work is lost" have to be different answers.

    Mirrors the surface `run_job` actually touches: `astream` for the
    streaming path, plus the `get_state` / `invoke` pair the HITL
    check and the sync fallback reach for.
    """

    def __init__(
        self,
        *,
        updates: Sequence[dict[str, Any]] = (),
        raises: BaseException | None = None,
        on_stream: Callable[[], None] | None = None,
    ) -> None:
        self._updates = list(updates)
        self._raises = raises
        self._on_stream = on_stream
        self.stream_count = 0

    async def astream(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.stream_count += 1
        if self._on_stream is not None:
            self._on_stream()
        for update in self._updates:
            yield update
        if self._raises is not None:
            raise self._raises

    async def aget_state(self, config: dict[str, Any] | None = None) -> Any:
        """Answer the way a graph compiled without a checkpointer does.

        `_invoke_streaming` reads the checkpoint after the stream ends
        to find out whether the graph interrupted. LangGraph signals
        "there is nothing to read" with a `ValueError` naming the
        missing checkpointer, and the runner matches that sentinel
        narrowly and falls back to its own merged state. Raising it
        here is therefore not a shortcut around the runner — it is the
        production path for `enable_checkpointing=False`, and it keeps
        this stub from having to reimplement state merging just to hand
        it straight back.
        """
        raise ValueError("No checkpointer set")

    def get_state(self, config: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(next=(), values={})

    def invoke(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:  # pragma: no cover - the async path is the one under test
        return {}


@pytest.fixture
def scripted_workflow() -> type[ScriptedWorkflow]:
    """The workflow stub, handed over rather than imported.

    Same reasoning as `triple`: nothing in this tier should depend on
    `tests/` being importable as a package.
    """
    return ScriptedWorkflow


@pytest.fixture
def pinned_runner_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Pin `src.api.runner.settings` to a real `Settings` for this test.

    Other API modules substitute a `SimpleNamespace` on the runner and
    do not always restore it, so without this the runner's `getattr`
    fallbacks read whatever the previous test left behind — which
    changes whether a cost cap fires and makes this tier's outcome
    depend on collection order. `tests/test_runner_cost_cap.py` carries
    the same pin for the same reason.
    """
    import src.api.runner as runner_module

    pinned = Settings()
    monkeypatch.setattr(runner_module, "settings", pinned)
    return pinned


def drain_frames(job: Job) -> list[dict[str, Any]]:
    """Snapshot every SSE frame the runner queued for `job`, in order."""
    frames: list[dict[str, Any]] = []
    while not job.event_queue.empty():
        frames.append(job.event_queue.get_nowait())
    return frames


@pytest.fixture
def frames() -> Callable[[Job], list[dict[str, Any]]]:
    """The queued-frame reader, as a fixture for the same import reason."""
    return drain_frames
