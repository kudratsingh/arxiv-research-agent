"""The degradation ladder's attribute vocabulary is closed (ADR 0081).

`research_degradations_total` is the instrument the quality SLI is
computed from, and `docs/reliability.md` §5 states the rule that makes
that SLI mean anything: *every rung must emit a distinct marker,
otherwise degradation makes the dashboard look better while the product
gets worse.* A marker is only distinct if its name is stable, so the
`rung` and `component` attributes are closed sets — the third closed
vocabulary in this repository after `ERROR_CODES` (ADR 0064) and
`KNOWN_EVENTS` (ADR 0067), and closed for both of the reasons those two
give:

- **Cardinality.** A metric attribute mints one series per distinct
  value, permanently. `key_id` is kept off metric attributes for exactly
  this reason (ADR 0049), and a `rung` interpolated from an exception or
  a URL would be the same mistake with a friendlier name.
- **Silent rot.** A dashboard panel or alert rule naming a value the
  code has stopped emitting does not error. It renders a flat zero, and
  a flat zero on a *quality* panel reads as an undegraded fleet — the
  most dangerous possible way for this particular instrument to fail.

## What this module actually checks

The closure check is **static**: `src/` is parsed and every literal or
named constant passed as `rung=` / `component=` is looked up in the
frozen set. Parsing the code rather than asserting a fixture is the
distinction `tests/test_log_contract.py` draws and the reason it draws
it — a fixture only proves that the fixture and the constant agree,
while a parse proves the *call sites* and the constant agree, which is
the invariant that matters when somebody adds a rung.

The runtime half is containment, not enforcement: an unregistered value
is recorded under `unregistered` and logged, so a mistake costs one
extra series instead of unbounded cardinality and cannot turn an
observability bug into a job failure at a call site whose whole purpose
is surviving a failure.

## The two sets are checked in different directions, on purpose

`DEGRADATION_COMPONENTS` is checked **both** ways: every emitted name is
registered *and* every registered name is emitted. A component is minted
only by a call site, so a registered one with no call site is dead
vocabulary — a filter that will never match.

`DEGRADATION_RUNGS` is checked forward only, because the ladder is
published in `docs/reliability.md` §5 and the *document* is the
authority for what the rungs are. Three of them have no emitter in
`src/` on this branch, and `_RUNGS_WITHOUT_EMITTERS` pins exactly which
three with the lane that owns each. That set is asserted in both
directions too, so wiring `src/agents/reader.py` turns this file red
until the entry is removed — which is how the gap closes itself instead
of living in a TODO nobody re-reads.

Mutation-check: adding `rung="anything"` at a call site fails
`test_every_rung_a_call_site_names_is_registered`; deleting the
`record_degradation_rung` call in `src/tools/embeddings.py` fails
`test_every_registered_component_is_actually_emitted`; instrumenting the
reader fails `test_the_uninstrumented_rungs_are_exactly_the_declared_ones`.
"""

from __future__ import annotations

import ast
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from src.config import Settings
from src.observability import metrics as metrics_module
from src.observability.logging import KNOWN_EVENTS
from src.observability.metrics import (
    DEGRADATION_COMPONENTS,
    DEGRADATION_RUNG_CACHE_STALE,
    DEGRADATION_RUNG_MODEL_FALLBACK,
    DEGRADATION_RUNG_PARTIAL_RESULTS,
    DEGRADATION_RUNG_REDUCED_TOOL,
    DEGRADATION_RUNGS,
    DEGRADATION_UNREGISTERED,
    record_degradation_rung,
)

pytestmark = [pytest.mark.unit]

_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_SRC: Final[Path] = _ROOT / "src"

#: The two functions that put a value on the counter's attributes.
#: `resilience.record_degradation` forwards to the metrics helper, so a
#: `rung=` at either call site reaches the instrument and both have to
#: be scanned.
_RECORDING_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"record_degradation_rung", "record_degradation"}
)

#: Files that *define or forward* the helper rather than calling it from
#: a degradation site. Their `rung=rung` pass-throughs are variables by
#: construction, so they are excluded from the scan — otherwise the
#: resolvability check would fail on the two lines whose whole job is
#: to be generic.
_FORWARDING_MODULES: Final[frozenset[str]] = frozenset(
    {"src/observability/metrics.py", "src/resilience.py"}
)

#: Rungs that carry a metric already, through an instrument that is not
#: this counter, and are deliberately **not** also counted here.
#:
#: A second counter at a site that already has one is the failure
#: `metrics.py` names for queue saturation — "a second counter at the
#: acquire site could disagree with `/healthz`" — and a rejection
#: counted on both `rate_limit_rejections_total` and
#: `research_degradations_total` is two numbers that can drift apart
#: about one event. The cost is that a quality SLI query is a sum over
#: three instruments rather than one, which `docs/reliability.md` §3
#: writes out rather than hides.
_RUNGS_MEASURED_ELSEWHERE: Final[dict[str, str]] = {
    "bounded_queue": (
        "research_queue_depth, research_queue_saturation_ratio and "
        "research_job_queue_wait_seconds — the queue was already the one rung "
        "with gauges (ADR 0049)"
    ),
    "refusal": (
        "rate_limit_rejections_total, research_jobs_total{status='degraded_close'} "
        "and {error_type='cost_budget_exceeded'} — §5 calls this the one rung "
        "that is honest by construction, and it was honest in metrics too"
    ),
}

#: Rungs of `docs/reliability.md` §5 that nothing in `src/` emits on
#: this branch, each with the lane that owns the only file it could be
#: emitted from. This is a fence boundary, not a design gap: WO-D5 held
#: a one-PR exception for `src/observability/**` and none at all for
#: `src/agents/**`, and an honest five-of-eight beats a fence breach.
#:
#: Asserted in **both** directions below. Removing a rung from here
#: without instrumenting it fails; instrumenting one without removing it
#: from here also fails.
_RUNGS_WITHOUT_EMITTERS: Final[dict[str, str]] = {
    DEGRADATION_RUNG_REDUCED_TOOL: (
        "src/agents/search.py — capability lane (search_partial_arxiv_failure, "
        "search_empty_keeping_prior_papers, search_mock_data_served, "
        "search_query_cap_applied)"
    ),
    DEGRADATION_RUNG_PARTIAL_RESULTS: (
        "src/agents/reader.py — capability lane (reader_degraded_to_abstract_only, "
        "reader_paper_abstract_only). docs/reliability.md §5 calls this row the "
        "named failure of the whole document, which is why it is written down "
        "here rather than left to be noticed"
    ),
    DEGRADATION_RUNG_MODEL_FALLBACK: (
        "src/agents/{supervisor,verifier,planner,synthesizer}.py — capability lane"
    ),
}


def _constant_value(node: ast.expr) -> str | None:
    """Resolve one `rung=` / `component=` argument to its string value.

    Three forms are resolvable and nothing else is: a string literal, a
    bare `DEGRADATION_*` name, and a `metrics.DEGRADATION_*` attribute
    access. An f-string or a variable is deliberately *not* resolvable —
    it is also exactly the shape an unbounded attribute arrives in, so
    `test_every_attribute_a_call_site_names_is_resolvable` failing is
    the intended outcome rather than a limitation to work around.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    name: str | None = None
    if isinstance(node, ast.Name):
        name = node.id
    elif isinstance(node, ast.Attribute):
        name = node.attr
    if name is not None and name.startswith("DEGRADATION_"):
        value = getattr(metrics_module, name, None)
        if isinstance(value, str):
            return value
    return None


def _recorded_from_source() -> tuple[
    set[tuple[str, int, str]], set[tuple[str, int, str]], set[tuple[str, int]]
]:
    """Every `(file, line, value)` reaching the counter's attributes.

    Returns rungs, components and the call sites whose arguments could
    not be resolved — as `(file, line)` triples so a failure names the
    call site rather than only the offending string, which is the shape
    `tests/test_log_contract.py` settled on for the same reason.
    """
    rungs: set[tuple[str, int, str]] = set()
    components: set[tuple[str, int, str]] = set()
    unresolved: set[tuple[str, int]] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else ""
            )
            if called not in _RECORDING_FUNCTIONS:
                continue
            where = str(path.relative_to(_ROOT))
            if where in _FORWARDING_MODULES:
                continue
            for keyword in node.keywords:
                if keyword.arg not in {"rung", "component"}:
                    continue
                value = _constant_value(keyword.value)
                if value is None:
                    unresolved.add((where, node.lineno))
                elif keyword.arg == "rung":
                    rungs.add((where, node.lineno, value))
                else:
                    components.add((where, node.lineno, value))
    return rungs, components, unresolved


RUNGS_EMITTED, COMPONENTS_EMITTED, UNRESOLVED = _recorded_from_source()


@pytest.fixture
def degradation_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[InMemoryMetricReader]:
    """The metrics module configured against an in-memory reader.

    A local copy of `test_genai_conventions.py`'s fixture rather than a
    shared one: `tests/conftest.py` deliberately rests nothing on the
    sys.path entry that would make a cross-module import work.
    """
    metrics_module.shutdown_metrics()
    monkeypatch.setattr(
        metrics_module,
        "settings",
        Settings(enable_metrics=True, otel_exporter_endpoint=""),
    )
    reader = InMemoryMetricReader()
    metrics_module.configure_metrics(reader=reader)
    yield reader
    metrics_module.shutdown_metrics()


class TestTheScanItself:
    def test_the_scan_finds_the_call_sites_it_is_supposed_to(self) -> None:
        # Without this, a refactor that renamed the helper would make
        # every check below pass vacuously against an empty set — the
        # failure `test_operability_docs.py` guards its own AST walk
        # against, and for the same reason.
        files = {where for where, _, _ in RUNGS_EMITTED}
        assert files == {
            "src/api/auth.py",
            "src/api/streaming.py",
            "src/tools/embeddings.py",
            "src/tools/pdf_parser.py",
        }, (
            f"the degradation call sites in src/ have moved: {sorted(files)}. "
            "If that is deliberate, update this list — it is the sanity band "
            "that stops every check below passing vacuously against an empty "
            "set when a refactor renames the helper."
        )

    def test_every_attribute_a_call_site_names_is_resolvable(self) -> None:
        assert not UNRESOLVED, (
            "these call sites pass a `rung=` or `component=` this test cannot "
            f"resolve to a constant: {sorted(UNRESOLVED)}. An interpolated "
            "metric attribute is unbounded cardinality (ADR 0049); use a "
            "`DEGRADATION_*` constant."
        )


class TestTheVocabularyIsClosed:
    def test_every_rung_a_call_site_names_is_registered(self) -> None:
        unregistered = sorted(r for r in RUNGS_EMITTED if r[2] not in DEGRADATION_RUNGS)
        assert not unregistered, (
            "these call sites name a rung outside DEGRADATION_RUNGS — register "
            "it in src/observability/metrics.py and give it a row in "
            f"docs/reliability.md §5: {unregistered}"
        )

    def test_every_component_a_call_site_names_is_registered(self) -> None:
        unregistered = sorted(
            c for c in COMPONENTS_EMITTED if c[2] not in DEGRADATION_COMPONENTS
        )
        assert not unregistered, (
            "these call sites name a component outside DEGRADATION_COMPONENTS "
            f"— register it in src/observability/metrics.py: {unregistered}"
        )

    def test_no_call_site_names_the_overflow_bucket(self) -> None:
        # `unregistered` exists so a mistake costs one series instead of
        # unbounded cardinality. A call site naming it deliberately would
        # turn the containment into a hiding place.
        named = sorted(
            site
            for site in RUNGS_EMITTED | COMPONENTS_EMITTED
            if site[2] == DEGRADATION_UNREGISTERED
        )
        assert not named, (
            f"{named} names the overflow bucket directly. It is where an "
            "unregistered value lands, not a value to choose."
        )

    def test_every_registered_component_is_actually_emitted(self) -> None:
        # The reverse direction, which `DEGRADATION_RUNGS` cannot have.
        emitted = {value for _, _, value in COMPONENTS_EMITTED}
        dead = sorted(DEGRADATION_COMPONENTS - emitted - {DEGRADATION_UNREGISTERED})
        assert not dead, (
            f"these components are registered but nothing in src/ emits them: "
            f"{dead}. A component name is minted by a call site, so one with no "
            "call site is a dashboard filter that will never match — delete it, "
            "or wire the site that was supposed to use it."
        )

    def test_the_vocabulary_reads_as_machine_tokens(self) -> None:
        # A closed set only helps if its members are the kind of thing a
        # PromQL selector can carry. Same check, same reason, as the one
        # `test_log_contract.py` runs over KNOWN_EVENTS.
        malformed = sorted(
            value
            for value in DEGRADATION_RUNGS | DEGRADATION_COMPONENTS
            if not re.fullmatch(r"[a-z][a-z0-9_]*", value)
        )
        assert not malformed, malformed


class TestTheLadderMatchesTheDocument:
    """`docs/reliability.md` §5 is the authority for what a rung is."""

    @staticmethod
    def _section_five() -> str:
        text = (_ROOT / "docs" / "reliability.md").read_text(encoding="utf-8")
        return text.split("## 5. The degradation ladder", 1)[1].split("\n## ", 1)[0]

    def test_every_rung_appears_in_the_published_ladder(self) -> None:
        section = self._section_five()
        missing = sorted(
            rung
            for rung in DEGRADATION_RUNGS - {DEGRADATION_UNREGISTERED}
            if rung not in section
        )
        assert not missing, (
            "these rungs are in DEGRADATION_RUNGS but named nowhere in "
            f"docs/reliability.md §5: {missing}. A rung an operator cannot "
            "look up is a metric attribute, not a rung."
        )

    def test_every_rung_is_accounted_for_exactly_once(self) -> None:
        # Each of the eight rungs is in exactly one of three states:
        # counted here, counted by a different instrument, or counted by
        # nothing and owned by a named lane. A rung in none of them is
        # the invisible degradation §5 exists to forbid; a rung in two
        # is double-counted, which is the same lie with the sign
        # flipped.
        emitted = {value for _, _, value in RUNGS_EMITTED}
        elsewhere = set(_RUNGS_MEASURED_ELSEWHERE)
        silent = set(_RUNGS_WITHOUT_EMITTERS)
        ladder = DEGRADATION_RUNGS - {DEGRADATION_UNREGISTERED}

        assert emitted | elsewhere | silent == ladder, (
            f"unaccounted rungs: {sorted(ladder - emitted - elsewhere - silent)}"
        )
        assert not emitted & elsewhere, (
            f"double-counted: {sorted(emitted & elsewhere)} is on this counter "
            "and on another instrument, so the two can disagree about one event"
        )
        assert not emitted & silent, sorted(emitted & silent)
        assert not elsewhere & silent, sorted(elsewhere & silent)

    def test_the_uninstrumented_rungs_are_exactly_the_declared_ones(self) -> None:
        emitted = {value for _, _, value in RUNGS_EMITTED}
        silent = (
            DEGRADATION_RUNGS
            - emitted
            - set(_RUNGS_MEASURED_ELSEWHERE)
            - {DEGRADATION_UNREGISTERED}
        )
        assert silent == set(_RUNGS_WITHOUT_EMITTERS), (
            "the set of rungs with no emitter in src/ has moved. Now silent: "
            f"{sorted(silent)}; declared silent: "
            f"{sorted(_RUNGS_WITHOUT_EMITTERS)}. If you have just instrumented "
            "one, delete its entry from `_RUNGS_WITHOUT_EMITTERS` and update "
            "docs/reliability.md §5's 'On a metric?' column."
        )

    def test_each_silent_rung_names_the_lane_that_owns_it(self) -> None:
        # An unmeasured rung is allowed; an unmeasured rung with nobody
        # named for it is how a gap survives three waves.
        for rung, owner in _RUNGS_WITHOUT_EMITTERS.items():
            assert "src/" in owner and "lane" in owner, (
                f"{rung} declares no owning file and lane: {owner!r}"
            )

    def test_each_rung_measured_elsewhere_names_its_instrument(self) -> None:
        # A rung excused from this counter has to say what does count
        # it, or "measured elsewhere" is just "not measured" in a better
        # suit. Every name given must be a real instrument.
        for rung, instruments in _RUNGS_MEASURED_ELSEWHERE.items():
            assert any(
                name in instruments
                for name in ("research_", "rate_limit_rejections_total")
            ), f"{rung} names no instrument: {instruments!r}"


class TestTheRuntimeContainsWhatTheScanWouldCatch:
    """The static check is the enforcement; this is the blast radius."""

    def test_an_unregistered_rung_lands_in_the_overflow_bucket(
        self, caplog: pytest.LogCaptureFixture, degradation_reader: Any
    ) -> None:
        with caplog.at_level(logging.WARNING):
            record_degradation_rung(rung="not_a_rung", component="paper_cache")

        point = _only_point(degradation_reader, "research_degradations_total")
        attributes = dict(point.attributes)
        assert attributes["rung"] == DEGRADATION_UNREGISTERED
        assert attributes["component"] == "paper_cache"
        assert point.value == 1
        assert "degradation_rung_unregistered" in {r.message for r in caplog.records}

    def test_an_unregistered_component_lands_in_the_overflow_bucket(
        self, caplog: pytest.LogCaptureFixture, degradation_reader: Any
    ) -> None:
        with caplog.at_level(logging.WARNING):
            record_degradation_rung(
                rung=DEGRADATION_RUNG_CACHE_STALE, component="whatever"
            )

        attributes = dict(
            _only_point(degradation_reader, "research_degradations_total").attributes
        )
        assert attributes["rung"] == DEGRADATION_RUNG_CACHE_STALE
        assert attributes["component"] == DEGRADATION_UNREGISTERED

    def test_a_registered_pair_is_recorded_verbatim(
        self, degradation_reader: Any
    ) -> None:
        record_degradation_rung(
            rung=DEGRADATION_RUNG_CACHE_STALE, component="embedding_cache"
        )

        attributes = dict(
            _only_point(degradation_reader, "research_degradations_total").attributes
        )
        assert attributes == {"rung": "cache_stale", "component": "embedding_cache"}

    def test_the_helper_is_inert_with_no_provider(self) -> None:
        # Every other record helper returns on its `None` check with
        # metrics disabled, and a degradation site is the last place
        # that should raise: it is already on a failure path.
        record_degradation_rung(rung=DEGRADATION_RUNG_CACHE_STALE, component="x")

    def test_the_overflow_event_is_registered(self) -> None:
        assert "degradation_rung_unregistered" in KNOWN_EVENTS


def _only_point(reader: Any, instrument: str) -> Any:
    """The single data point `instrument` has recorded."""
    data = reader.get_metrics_data()
    points = [
        point
        for resource_metric in data.resource_metrics
        for scope_metric in resource_metric.scope_metrics
        for metric in scope_metric.metrics
        if metric.name == instrument
        for point in metric.data.data_points
    ]
    assert len(points) == 1, f"expected one {instrument} point, got {points}"
    return points[0]
