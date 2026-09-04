"""Operability artifacts are pinned to the code that produces them (ADR 0073).

Alerting rots **silently**. A renamed instrument does not make a rule
error and does not make a dashboard panel blank — it makes both match
nothing, forever, and a query matching nothing renders a flat zero. A
flat zero reads exactly like a healthy, idle fleet, so the failure is
invisible right up until the incident it was supposed to catch. Nothing
else in this repository would notice, which is why this file exists and
why it is the deliverable of WO-A12 rather than the prose it guards.

Four claims are under test, and each of them is a claim about two
artifacts agreeing:

  - **Alert rules and dashboard panels name instruments that exist.**
    The instrument set is re-derived by parsing `src/` for every
    `meter.create_*` call — not read from a checked-in list, for the
    reason `tests/test_log_contract.py` gives about the event registry:
    a fixture only proves the fixture and the constant agree. Parsing
    proves the *code* and the rules agree, which is the invariant that
    matters when somebody renames an instrument.
  - **Every instrument is watched by something.** The reverse
    direction, so a new instrument cannot be added and quietly
    forgotten. `_UNWATCHED_INSTRUMENTS` is the escape hatch and it is
    deliberately empty.
  - **Runbooks and log alarms name signals that are emitted.** Log
    events go through `KNOWN_EVENTS`, which is already a closed set —
    "a runbook can name an event and be told when the code stops
    emitting it under that name" is the reason that set is closed, and
    this is the test that collects on it.
  - **The assumptions the names rest on are still true**: the collector
    still pins `add_metric_suffixes: false`, and the default compose
    path still does not reference the overlay.

## The one transformation between the two vocabularies

`src/` names instruments in OpenTelemetry form
(`gen_ai.client.operation.duration`); PromQL cannot contain a dot, so
the rules name them in Prometheus form
(`gen_ai_client_operation_duration`). `_prometheus_name` is the whole of
the translation, and it is only that simple because
`deploy/observability/otel-collector.yaml` sets
`add_metric_suffixes: false` — `test_collector_disables_metric_suffixes`
asserts that, because with suffixing on the exported name is put through
the exporter's *unit table* and this test could only follow it by
reimplementing that table and being subtly wrong about it after the next
collector upgrade. A test that is wrong about the names is worse than
the rot it was written to catch.

## Where this test deliberately stops

Backticked spans in the documentation that are not bare identifiers —
anything with a space, an `=`, a `*`, or a leading digit — are treated
as prose and skipped. That is a real hole and a narrow one: it means
`` `http.route="/research"` `` is not checked, while a typo in
`` `resilence_degraded` `` still fails. Widening it would require
parsing English.

Mutation-check: renaming any instrument in
`src/observability/metrics.py` (or any `METRIC_*` constant in
`semconv.py`) fails `test_every_alert_metric_exists_in_src`; deleting a
name from `KNOWN_EVENTS` fails
`test_every_runbook_log_signal_is_a_known_event`.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
from typing import Any, Final

import pytest
import yaml

from src.observability import semconv
from src.observability.logging import KNOWN_EVENTS

pytestmark = [pytest.mark.unit, pytest.mark.contract]

_ROOT: Final = pathlib.Path(__file__).resolve().parents[1]
_SRC: Final = _ROOT / "src"
_OBS: Final = _ROOT / "deploy" / "observability"
_RUNBOOKS: Final = _ROOT / "docs" / "runbooks"

#: The seven incident runbooks. `pilot.md` is deliberately absent: it
#: predates this work order, documents a *procedure* rather than an
#: incident, has no signal table, and carries dotted identifiers
#: (`arxiv.progress_purge`) that are Postgres names rather than
#: telemetry ones.
INCIDENT_RUNBOOKS: Final[tuple[str, ...]] = (
    "model-provider-outage.md",
    "redis-loss.md",
    "postgres-loss.md",
    "cost-cap-storm.md",
    "queue-saturation.md",
    "poison-job.md",
    "injection-alarm.md",
)

#: The four sections a runbook must have, in the order an operator needs
#: them at three in the morning.
REQUIRED_RUNBOOK_SECTIONS: Final[tuple[str, ...]] = (
    "## 1. The signal",
    "## 2. The first three commands",
    "## 3. Containment",
    "## 4. Rollback",
)

#: Instruments allowed to appear on no dashboard and in no alert rule.
#: Empty on purpose — an instrument nobody looks at is a line of code,
#: not observability, and adding a name here should require an argument
#: in the PR that does it.
_UNWATCHED_INSTRUMENTS: Final[frozenset[str]] = frozenset()

#: Every `Meter` factory. Listed rather than pattern-matched on
#: `create_*` so that a genuinely new instrument *kind* in a future
#: OpenTelemetry release is a test failure here — which is the moment to
#: decide whether it belongs on the dashboard — rather than a silent
#: omission from the scan.
_CREATE_METHODS: Final[frozenset[str]] = frozenset(
    {
        "create_counter",
        "create_up_down_counter",
        "create_histogram",
        "create_gauge",
        "create_observable_counter",
        "create_observable_up_down_counter",
        "create_observable_gauge",
    }
)

#: Prometheus' own histogram/summary suffixes. Added by the client
#: library's exposition format, not by the OTel-to-Prometheus name
#: translation, so they are stripped before a name is looked up rather
#: than being part of `_prometheus_name`.
_SERIES_SUFFIXES: Final[tuple[str, ...]] = ("_bucket", "_count", "_sum")

# PromQL lexical helpers. The grammar is not parsed — a metric selector
# is an identifier that is neither a function call, nor a label name,
# nor a keyword, nor inside a grouping clause — which is enough because
# the only expressions this test reads are the ones in this repository.
_PROMQL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "and",
        "bool",
        "by",
        "group_left",
        "group_right",
        "ignoring",
        "inf",
        "nan",
        "offset",
        "on",
        "or",
        "unless",
        "without",
    }
)
_PROMQL_STRING = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'")
_PROMQL_GROUPING = re.compile(
    r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)"
)
# The lookbehind is what stops `28d` from yielding the identifier `d`
# and `0.95` from yielding anything at all.
_IDENTIFIER = re.compile(r"(?<![0-9A-Za-z_:.])[A-Za-z_][A-Za-z0-9_]*")

#: A backticked span in a doc that is a bare telemetry identifier.
#: Anything else in backticks is prose and is skipped — see the module
#: docstring's note on where this test stops.
_DOC_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*$")


# ---------------------------------------------------------------------------
# Deriving the instrument set from the code
# ---------------------------------------------------------------------------


def _instrument_name_node(call: ast.Call) -> ast.expr | None:
    """Return the AST node holding the instrument's name, if any."""
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "name":
            return keyword.value
    return None


def _resolve_instrument_name(node: ast.expr) -> str | None:
    """Resolve one `meter.create_*` name argument to a string.

    Two shapes exist in `src/` and both are deliberate: the
    repository's own instruments are string literals, and the
    conventional ones are `semconv.METRIC_*` constants so that a
    pre-stable name lives in exactly one file (ADR 0066).

    Returns:
        The instrument name, or None when the argument is neither of
        those — which the caller turns into a **failure**, never a
        skip. A scan with a silent hole in it is worse than no scan,
        because it is believed.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "semconv"
    ):
        resolved = getattr(semconv, node.attr, None)
        return resolved if isinstance(resolved, str) else None
    return None


def _declared_instruments() -> tuple[dict[str, str], list[str]]:
    """Parse `src/` for every instrument name and where it is declared.

    Returns:
        A mapping of OpenTelemetry instrument name to `path:line`, and
        a list of `path:line` strings for call sites whose name could
        not be resolved.
    """
    found: dict[str, str] = {}
    unresolved: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in _CREATE_METHODS:
                continue
            where = f"{path.relative_to(_ROOT)}:{node.lineno}"
            name_node = _instrument_name_node(node)
            name = _resolve_instrument_name(name_node) if name_node else None
            if name is None:
                unresolved.append(where)
                continue
            found[name] = where
    return found, unresolved


def _semconv_names() -> frozenset[str]:
    """Every dotted string constant in `semconv`.

    Dotted only: the module also holds enum *values* (`chat`,
    `research`, `anthropic`) and allowing those would let a bare prose
    word pass a documentation check. A dotted constant is unambiguously
    a conventional attribute or metric name.
    """
    return frozenset(
        value
        for name, value in vars(semconv).items()
        if not name.startswith("_") and isinstance(value, str) and "." in value
    )


def _prometheus_name(otel_name: str) -> str:
    """Translate an OpenTelemetry metric name to its Prometheus form.

    The **entire** translation, and it is only this small because the
    collector overlay sets `add_metric_suffixes: false`. With the
    exporter's default, unit and type suffixes are appended from a unit
    table — `s` becomes `_seconds`, monotonic sums gain `_total`, and a
    unit the table does not know (`USD`, on `llm_cost_usd_total`) is
    appended verbatim — and this function would have to become a second
    implementation of that table.
    """
    return re.sub(r"[^A-Za-z0-9_:]", "_", otel_name)


INSTRUMENTS, UNRESOLVED_INSTRUMENTS = _declared_instruments()
SEMCONV_NAMES = _semconv_names()
PROM_TO_OTEL: Final[dict[str, str]] = {
    _prometheus_name(name): name for name in INSTRUMENTS
}


def _lookup_metric(name: str) -> str | None:
    """Resolve a Prometheus series name to its OTel instrument name."""
    if name in PROM_TO_OTEL:
        return PROM_TO_OTEL[name]
    for suffix in _SERIES_SUFFIXES:
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            if base in PROM_TO_OTEL:
                return PROM_TO_OTEL[base]
    return None


# ---------------------------------------------------------------------------
# Reading the artifacts
# ---------------------------------------------------------------------------


def _metric_names_in_promql(expr: str) -> set[str]:
    """Every metric selector in one PromQL expression."""
    text = _PROMQL_STRING.sub(" ", expr)
    text = _PROMQL_GROUPING.sub(" ", text)
    names: set[str] = set()
    for match in _IDENTIFIER.finditer(text):
        name = match.group(0)
        if name in _PROMQL_KEYWORDS:
            continue
        rest = text[match.end() :].lstrip()
        if rest.startswith("("):
            continue  # a function call, not a series
        if rest.startswith(("=~", "!~", "!=")):
            continue  # a label matcher
        if rest.startswith("=") and not rest.startswith("=="):
            continue  # a label matcher; `==` is a comparison
        names.add(name)
    return names


def _load_yaml(name: str) -> Any:
    return yaml.safe_load((_OBS / name).read_text(encoding="utf-8"))


def _alert_rules() -> list[dict[str, Any]]:
    document = _load_yaml("alerts.yml")
    return [rule for group in document["groups"] for rule in group["rules"]]


def _log_alarms() -> list[dict[str, Any]]:
    alarms: list[dict[str, Any]] = _load_yaml("log-alerts.yml")["alerts"]
    return alarms


def _dashboard_targets() -> list[tuple[str, str]]:
    """Every `(panel title, expr)` in the dashboard definition."""
    document = json.loads((_OBS / "dashboard.json").read_text(encoding="utf-8"))
    return [
        (panel["title"], target["expr"])
        for panel in document["panels"]
        for target in panel.get("targets", [])
    ]


def _signal_table_rows(runbook: str) -> list[tuple[str, str]]:
    """Return `(signal cell, where cell)` for one runbook's §1 table.

    The table is the runbook's contract with the code: column one names
    the signal, column two says whether it is a metric or a log event.
    """
    text = (_RUNBOOKS / runbook).read_text(encoding="utf-8")
    section = text.split("## 1. The signal", 1)[1].split("\n## ", 1)[0]
    rows: list[tuple[str, str]] = []
    for line in section.splitlines():
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2 or cells[0] == "Signal":
            continue
        rows.append((cells[0], cells[1]))
    return rows


def _doc_identifiers(cell: str) -> list[str]:
    """Bare telemetry identifiers backticked inside one table cell.

    A trailing PromQL label selector is stripped, so
    `` `research_jobs_total{error_type="orphaned"}` `` resolves to the
    instrument. Spans that are not bare identifiers are prose.
    """
    identifiers: list[str] = []
    for span in re.findall(r"`([^`]+)`", cell):
        span = re.sub(r"\{.*\}$", "", span).strip()
        if span and _DOC_IDENTIFIER.match(span):
            identifiers.append(span)
    return identifiers


# ---------------------------------------------------------------------------
# The scan itself has to be sound before anything it produces means
# anything
# ---------------------------------------------------------------------------


class TestTheInstrumentScan:
    def test_every_instrument_name_in_src_is_resolvable(self) -> None:
        assert not UNRESOLVED_INSTRUMENTS, (
            "these `meter.create_*` call sites name their instrument in a "
            "form this test cannot resolve, so nothing below actually "
            "checks them: "
            f"{UNRESOLVED_INSTRUMENTS}. Use a string literal or a "
            "`semconv.` constant."
        )

    def test_the_scan_finds_the_families_it_is_supposed_to(self) -> None:
        # A sanity floor, not a fixture of the whole set: if the AST walk
        # silently stopped matching (a refactor to a helper, a rename of
        # the `meter` variable) every other test in this file would pass
        # vacuously, because an empty instrument set watches nothing.
        assert "research_jobs_total" in INSTRUMENTS
        assert semconv.METRIC_CLIENT_TOKEN_USAGE in INSTRUMENTS
        assert semconv.METRIC_HTTP_SERVER_REQUEST_DURATION in INSTRUMENTS
        assert len(INSTRUMENTS) >= 20

    def test_the_prometheus_translation_is_the_documented_one(self) -> None:
        assert _prometheus_name("gen_ai.client.token.usage") == (
            "gen_ai_client_token_usage"
        )
        assert _prometheus_name("http.server.request.duration") == (
            "http_server_request_duration"
        )
        # Already Prometheus-shaped names pass through untouched, which
        # is why the repository's own instruments need no alias.
        assert _prometheus_name("research_jobs_total") == "research_jobs_total"


# ---------------------------------------------------------------------------
# The deliverable
# ---------------------------------------------------------------------------


class TestAlertRulesNameRealInstruments:
    def test_every_alert_metric_exists_in_src(self) -> None:
        missing: list[str] = []
        for rule in _alert_rules():
            for name in _metric_names_in_promql(rule["expr"]):
                if _lookup_metric(name) is None:
                    missing.append(f"{rule['alert']} -> {name}")
        assert not missing, (
            "alert rules reference metrics that no instrument in `src/` "
            f"emits: {missing}. A rule naming a metric that does not "
            "exist never fires and never errors — it matches nothing, "
            "which renders as a flat zero and reads as a healthy fleet."
        )

    def test_every_dashboard_metric_exists_in_src(self) -> None:
        missing: list[str] = []
        for title, expr in _dashboard_targets():
            for name in _metric_names_in_promql(expr):
                if _lookup_metric(name) is None:
                    missing.append(f"{title!r} -> {name}")
        assert not missing, (
            f"dashboard panels reference metrics that no longer exist: {missing}"
        )

    def test_every_instrument_is_watched_by_something(self) -> None:
        watched: set[str] = set()
        for rule in _alert_rules():
            watched |= _metric_names_in_promql(rule["expr"])
        for _, expr in _dashboard_targets():
            watched |= _metric_names_in_promql(expr)
        resolved = {
            otel
            for name in watched
            if (otel := _lookup_metric(name)) is not None
        }
        unwatched = set(INSTRUMENTS) - resolved - _UNWATCHED_INSTRUMENTS
        assert not unwatched, (
            "these instruments appear on no dashboard panel and in no "
            f"alert rule: {sorted(unwatched)}. Add a panel, or add the "
            "name to `_UNWATCHED_INSTRUMENTS` with an argument for why "
            "nobody needs to see it."
        )

    def test_every_alert_names_a_runbook_that_exists(self) -> None:
        for rule in _alert_rules():
            runbook = rule["annotations"]["runbook"]
            assert (_ROOT / runbook).is_file(), (
                f"{rule['alert']} points at {runbook}, which does not exist"
            )

    def test_every_alert_signal_event_is_a_known_event(self) -> None:
        unknown: list[str] = []
        for rule in _alert_rules():
            for event in rule["annotations"]["signal_events"].split():
                if event not in KNOWN_EVENTS:
                    unknown.append(f"{rule['alert']} -> {event}")
        assert not unknown, (
            "alert annotations name log events that `src/` no longer "
            f"emits: {unknown}"
        )

    def test_every_alert_declares_a_severity_the_runbooks_use(self) -> None:
        # Two values, deliberately. A third severity is a routing
        # decision, and there is nobody to route to.
        for rule in _alert_rules():
            assert rule["labels"]["severity"] in {"page", "ticket"}


class TestLogAlarmsNameRealEvents:
    def test_every_log_alarm_event_is_a_known_event(self) -> None:
        unknown: list[str] = []
        for alarm in _log_alarms():
            for event in alarm["events"]:
                if event not in KNOWN_EVENTS:
                    unknown.append(f"{alarm['name']} -> {event}")
        assert not unknown, (
            "log alarms name events that are not in `KNOWN_EVENTS`, so "
            f"they match nothing: {unknown}"
        )

    def test_every_log_alarm_is_complete(self) -> None:
        required = {
            "name",
            "events",
            "level",
            "window",
            "threshold",
            "severity",
            "runbook",
            "why",
        }
        for alarm in _log_alarms():
            missing = required - set(alarm)
            assert not missing, f"{alarm.get('name')} is missing {missing}"
            assert (_ROOT / alarm["runbook"]).is_file()
            assert alarm["severity"] in {"page", "ticket"}

    def test_log_alarms_only_exist_for_signals_with_no_metric(self) -> None:
        # The file's whole justification. If an event's signal ever gains
        # an instrument, the alarm belongs in `alerts.yml` where a
        # burn rate can be computed from it, and this test is the
        # reminder to move it.
        for alarm in _log_alarms():
            for event in alarm["events"]:
                assert _lookup_metric(_prometheus_name(event)) is None, (
                    f"{alarm['name']} watches {event}, which now has an "
                    "instrument — move it to alerts.yml"
                )


class TestRunbooksNameSignalsThatExist:
    @pytest.mark.parametrize("runbook", INCIDENT_RUNBOOKS)
    def test_runbook_has_the_four_required_sections(self, runbook: str) -> None:
        text = (_RUNBOOKS / runbook).read_text(encoding="utf-8")
        for heading in REQUIRED_RUNBOOK_SECTIONS:
            assert heading in text, f"{runbook} has no {heading!r}"

    @pytest.mark.parametrize("runbook", INCIDENT_RUNBOOKS)
    def test_runbook_gives_three_numbered_commands(self, runbook: str) -> None:
        text = (_RUNBOOKS / runbook).read_text(encoding="utf-8")
        section = text.split(REQUIRED_RUNBOOK_SECTIONS[1], 1)[1]
        section = section.split("\n## ", 1)[0]
        assert "```bash" in section
        for number in ("# 1.", "# 2.", "# 3."):
            assert number in section, f"{runbook} has no command {number}"

    @pytest.mark.parametrize("runbook", INCIDENT_RUNBOOKS)
    def test_runbook_has_a_signal_table(self, runbook: str) -> None:
        assert _signal_table_rows(runbook), (
            f"{runbook} has no rows in its signal table, so it names no "
            "signal at all"
        )

    @pytest.mark.parametrize("runbook", INCIDENT_RUNBOOKS)
    def test_every_runbook_metric_signal_is_an_instrument(
        self, runbook: str
    ) -> None:
        missing: list[str] = []
        for signal, where in _signal_table_rows(runbook):
            if "metric" not in where:
                continue
            for identifier in _doc_identifiers(signal):
                if identifier not in INSTRUMENTS:
                    missing.append(identifier)
        assert not missing, (
            f"{runbook} names metrics that `src/` does not emit: {missing}. "
            "A runbook that names a signal no instrument emits is worse "
            "than no runbook — it costs an operator ten minutes before "
            "they conclude the signal is broken rather than the fleet "
            "healthy."
        )

    @pytest.mark.parametrize("runbook", INCIDENT_RUNBOOKS)
    def test_every_runbook_log_signal_is_a_known_event(
        self, runbook: str
    ) -> None:
        missing: list[str] = []
        for signal, where in _signal_table_rows(runbook):
            if "log" not in where or "metric" in where:
                continue
            for identifier in _doc_identifiers(signal):
                if identifier not in KNOWN_EVENTS:
                    missing.append(identifier)
        assert not missing, (
            f"{runbook} names log events that are not in `KNOWN_EVENTS`: "
            f"{missing}"
        )

    def test_the_index_lists_every_runbook(self) -> None:
        index = (_RUNBOOKS / "README.md").read_text(encoding="utf-8")
        for runbook in INCIDENT_RUNBOOKS:
            assert f"]({runbook})" in index, f"{runbook} is not in the index"
        # Every `.md` in the directory is either an incident runbook, the
        # index, or the pilot procedure. A page that is none of those has
        # been added without being indexed.
        present = {path.name for path in _RUNBOOKS.glob("*.md")}
        assert present == {*INCIDENT_RUNBOOKS, "README.md", "pilot.md"}


class TestTheSLODocumentNamesRealInstruments:
    def test_every_instrument_in_the_sli_table_exists(self) -> None:
        text = (_ROOT / "docs" / "reliability.md").read_text(encoding="utf-8")
        section = text.split("## 3. The SLIs and their objectives", 1)[1]
        section = section.split("\n## ", 1)[0]
        missing: list[str] = []
        for line in section.splitlines():
            if not line.startswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != 4 or cells[0] == "SLI":
                continue
            for identifier in _doc_identifiers(cells[2]):
                if identifier not in INSTRUMENTS and identifier not in (
                    SEMCONV_NAMES
                ):
                    missing.append(identifier)
        assert not missing, (
            "the SLI table names instruments or conventional attributes "
            f"that do not exist: {missing}. An objective whose instrument "
            "is gone is not an objective, it is a slogan."
        )


# ---------------------------------------------------------------------------
# The assumptions the names rest on
# ---------------------------------------------------------------------------


class TestTheOverlayStaysOptional:
    def test_collector_disables_metric_suffixes(self) -> None:
        config = _load_yaml("otel-collector.yaml")
        exporter = config["exporters"]["prometheus"]
        assert exporter["add_metric_suffixes"] is False, (
            "every metric name in alerts.yml and dashboard.json assumes "
            "the Prometheus name is the OTel name with dots replaced. "
            "Turning suffixes on breaks all of them at once, silently. "
            "If this is a deliberate change, `_prometheus_name` in this "
            "file moves with it."
        )

    def test_the_default_compose_path_does_not_reference_the_overlay(
        self,
    ) -> None:
        compose = (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert "observability" not in compose, (
            "`docker compose up` is the zero-config demo. A collector and "
            "a Prometheus are two more processes and a disk that grows "
            "without asking, and standing them up is the owner's decision."
        )

    def test_the_overlay_only_adds_services_and_env(self) -> None:
        overlay = _load_yaml("compose.observability.yml")
        base = yaml.safe_load(
            (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        )
        added = set(overlay["services"]) - set(base["services"])
        assert added == {"otel-collector", "prometheus"}
        # The single edit to a service that ships by default, and it is
        # additive environment: no image, command, ports or volumes.
        assert set(overlay["services"]["app"]) == {"environment"}

    def test_the_overlay_does_not_turn_content_capture_on(self) -> None:
        # Turning it on sends paper text, research queries and learner
        # writing to the collector. Both flags default to off and the
        # overlay must not be the thing that changes that.
        text = (_OBS / "compose.observability.yml").read_text(encoding="utf-8")
        env = _load_yaml("compose.observability.yml")["services"]["app"][
            "environment"
        ]
        assert "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT" not in env
        assert "LOG_CAPTURE_USER_CONTENT" not in env
        # ...and the reason is written down where somebody editing it will
        # read it, not only here.
        assert "CAPTURE_MESSAGE_CONTENT" in text
