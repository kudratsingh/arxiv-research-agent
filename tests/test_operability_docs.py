"""Operability artifacts are pinned to the code that produces them (ADR 0073).

Alerting rots **silently**. A renamed instrument does not make a rule
error and does not make a dashboard panel blank — it makes both match
nothing, forever, and a query matching nothing renders a flat zero. A
flat zero reads exactly like a healthy, idle fleet, so the failure is
invisible right up until the incident it was supposed to catch. Nothing
else in this repository would notice, which is why this file exists and
why it is the deliverable of WO-A12 rather than the prose it guards.

Six claims are under test, and each of them is a claim about two
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
  - **A dashboard panel can actually ASK its question** (WO-INF1). The
    first claim above checks the words in an `expr`; this one checks
    that the panel resolves a datasource something in
    `deploy/observability/` provisions. Both are needed, and for two
    waves only the first existed: `dashboard.json` shipped in Grafana's
    export-for-sharing format, so a provisioned copy rendered 28 panels
    against the literal uid `${DS_PROMETHEUS}` while every name in it
    was correct and this file was green.
  - **The alert rules are parsed by a parser** (WO-INF1). Nothing here
    reads PromQL — an `expr` that does not parse, a `for:` that is not
    a duration, a duplicated group name, all pass every check above and
    are rejected by Prometheus at load. `promtool` is what parses them,
    it runs in CI, and the step is asserted here because a deleted
    workflow step is otherwise invisible.

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

And it still stops short of *rendering*. `test_every_panel_resolves_a_
datasource` proves the panel has something to ask; it does not prove
Grafana draws a line, because that needs a Grafana. The command in
`deploy/observability/README.md` is how a human closes that last gap,
and WO-INF1's PR records the run.

Mutation-check: renaming any instrument in
`src/observability/metrics.py` (or any `METRIC_*` constant in
`semconv.py`) fails `test_every_alert_metric_exists_in_src`; deleting a
name from `KNOWN_EVENTS` fails
`test_every_runbook_log_signal_is_a_known_event`; restoring
`dashboard.json` to its pre-WO-INF1 export format fails
`test_the_dashboard_is_not_in_grafana_export_format` and
`test_every_panel_resolves_a_datasource` while
`test_every_dashboard_metric_exists_in_src` stays green, which is the
whole reason those two exist.
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
_WORKFLOW: Final = _ROOT / ".github" / "workflows" / "ci.yml"

#: Grafana's file provisioning, which `compose.viewers.yml` mounts.
_GRAFANA_PROVISIONING: Final = _OBS / "grafana" / "provisioning"
_GRAFANA_DATASOURCES: Final = _GRAFANA_PROVISIONING / "datasources" / "prometheus.yml"
_GRAFANA_DASHBOARDS: Final = _GRAFANA_PROVISIONING / "dashboards" / "dashboards.yml"

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

#: A Grafana datasource reference that is a dashboard variable rather
#: than a uid: `${datasource}`. `${DS_PROMETHEUS}` matches this too, and
#: is caught by the variable it names not being declared — which is
#: exactly the defect, because an `__inputs` token looks like a variable
#: and is not one.
_DATASOURCE_VARIABLE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")

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


def _dashboard() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        (_OBS / "dashboard.json").read_text(encoding="utf-8")
    )
    return document


def _dashboard_panels() -> list[dict[str, Any]]:
    """Every panel, including the ones nested inside a collapsed row.

    A collapsed row carries its children in its own `panels` list rather
    than at the top level, so a flat read of `document["panels"]` stops
    seeing a panel the moment somebody collapses the row above it —
    which is a UI gesture, not a decision to stop checking it.
    """
    panels: list[dict[str, Any]] = []
    for panel in _dashboard().get("panels", []):
        panels.append(panel)
        panels.extend(panel.get("panels", []))
    return panels


def _dashboard_targets() -> list[tuple[str, str]]:
    """Every `(panel title, expr)` in the dashboard definition."""
    return [
        (panel["title"], target["expr"])
        for panel in _dashboard_panels()
        for target in panel.get("targets", [])
    ]


def _dashboard_datasource_variables() -> dict[str, dict[str, Any]]:
    """The dashboard's `type: datasource` template variables, by name."""
    listed = _dashboard().get("templating", {}).get("list", [])
    return {
        variable["name"]: variable
        for variable in listed
        if variable.get("type") == "datasource"
    }


def _provisioned_datasources() -> dict[str, dict[str, Any]]:
    """The datasources Grafana provisioning declares, by uid."""
    document = _load_yaml(_GRAFANA_DATASOURCES.relative_to(_OBS).as_posix())
    return {source["uid"]: source for source in document["datasources"]}


def _compose_mounts(compose_file: str, service: str) -> dict[str, str]:
    """A service's bind mounts in one compose file, as target -> source.

    Short-form only (`source:target[:mode]`), which is the form every
    file in this directory uses.
    """
    definition = _load_yaml(compose_file)["services"][service]
    mounts: dict[str, str] = {}
    for entry in definition.get("volumes", []):
        source, target = entry.split(":")[:2]
        mounts[target] = source
    return mounts


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
        # A sanity band, not a fixture of the whole set: if the AST walk
        # silently stopped matching (a refactor to a helper, a rename of
        # the `meter` variable) every other test in this file would pass
        # vacuously, because an empty instrument set watches nothing.
        assert "research_jobs_total" in INSTRUMENTS
        assert semconv.METRIC_CLIENT_TOKEN_USAGE in INSTRUMENTS
        assert semconv.METRIC_HTTP_SERVER_REQUEST_DURATION in INSTRUMENTS
        # 21 today, and this was a bare `>= 20`. A floor only ever looks
        # down: `docs/architecture.md` claimed NINE instruments while this
        # set grew from nine to twenty-one, and this assertion — the one
        # place in the repository carrying the count as a number — stayed
        # green through all twelve of those additions. The upper edge is
        # what a floor cannot do. Five of headroom is more than any single
        # PR here has added and well under the twelve that made up the
        # drift, so ordinary growth passes and a wave has to come back to
        # this line, which is where the number prose quotes gets re-read.
        assert 20 <= len(INSTRUMENTS) <= 26, (
            f"{len(INSTRUMENTS)} instruments declared in src/. Below 20 the "
            "scan has probably stopped matching and every check in this file "
            "is passing vacuously. Above 26 the set has grown by a wave: "
            "re-centre this band and re-read the count wherever prose states "
            "it, which is the drift this upper edge exists to interrupt."
        )

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

    def test_the_dashboard_does_not_quietly_lose_a_panel(self) -> None:
        # Two failures this catches, and neither of them fails anything
        # else in this file.
        #
        # A panel that is DELETED. Every check above iterates the panel
        # list, and a loop over a shorter list passes; a dashboard with
        # one panel left would satisfy all of them. WO-INF1 rewrote this
        # file wholesale (out of Grafana's export format), and a
        # wholesale rewrite is exactly when a panel added last week
        # disappears without anybody noticing.
        #
        # A walk that STOPS DESCENDING. Collapse a row and its children
        # move into the row's own `panels` list; if `_dashboard_panels`
        # ever stopped following that, the checks above would pass over
        # what was left.
        #
        # The floor is today's exact count, not a round number under it:
        # losing one panel is the failure, so one lost panel has to be
        # the failure. Growth up to the ceiling is free — a new
        # instrument arrives with a panel, which is what
        # `test_every_instrument_is_watched_by_something` requires —
        # and past it the band gets re-centred deliberately.
        panels = [panel for panel in _dashboard_panels() if panel.get("targets")]
        targets = _dashboard_targets()
        assert 22 <= len(panels) <= 30, (
            f"{len(panels)} panels carry queries; 22 is the floor. Below "
            "it a panel has been dropped or the walk has stopped "
            "descending into collapsed rows, and every check above is "
            "iterating a shorter list without complaining."
        )
        assert 26 <= len(targets) <= 36, (
            f"{len(targets)} dashboard targets found; 26 is the floor. A "
            "panel can also lose one of several queries, which leaves "
            "the panel count intact."
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


class TestTheDashboardIsProvisionable:
    """A query naming a real metric is not the same as a working panel.

    The class above checks that every `expr` names an instrument `src/`
    emits. That is a real check and it was the ONLY one, which meant it
    could not tell a working dashboard from a dead one: `dashboard.json`
    shipped in Grafana's *export for sharing* format — an `__inputs`
    block plus `${DS_PROMETHEUS}` placeholders — and Grafana's file
    provisioning does not resolve `__inputs`. Every panel's datasource
    uid was the literal seven-character string `${DS_PROMETHEUS}`. On
    Grafana 12.3.0 that renders 28 panels, no banner, and one console
    line per panel: `Datasource ${DS_PROMETHEUS} was not found`.

    Every expression in it was correct. Every metric existed. The
    dashboard showed nothing, and the test said it was fine.

    So the claim here is the other half: a panel resolves a datasource
    that something in this repository actually provisions.
    """

    def test_the_dashboard_is_not_in_grafana_export_format(self) -> None:
        document = _dashboard()
        raw = (_OBS / "dashboard.json").read_text(encoding="utf-8")
        assert "__inputs" not in document, (
            "`__inputs` is Grafana's export-for-sharing format. The "
            "import *wizard* resolves it by asking a human which "
            "datasource to use; file provisioning does not resolve it "
            "at all, and leaves every panel pointed at a uid that is "
            "the placeholder string itself."
        )
        assert "${DS_" not in raw, (
            "a `${DS_*}` token is an `__inputs` placeholder. It looks "
            "like a dashboard variable and is not one: nothing "
            "substitutes it outside the import wizard."
        )

    def test_every_panel_resolves_a_datasource(self) -> None:
        variables = _dashboard_datasource_variables()
        provisioned = _provisioned_datasources()
        unresolved: list[str] = []

        for panel in _dashboard_panels():
            if not panel.get("targets"):
                continue  # a row, or a text panel: nothing to query
            title = panel["title"]
            source = panel.get("datasource")
            if not isinstance(source, dict) or "uid" not in source:
                unresolved.append(f"{title!r}: no datasource")
                continue

            uid = source["uid"]
            match = _DATASOURCE_VARIABLE.match(uid)
            if match is None:
                if uid not in provisioned:
                    unresolved.append(
                        f"{title!r}: uid {uid!r} is provisioned nowhere"
                    )
                continue

            variable = variables.get(match.group(1))
            if variable is None:
                unresolved.append(
                    f"{title!r}: {uid} names no datasource variable"
                )
                continue
            if variable.get("query") != source.get("type"):
                unresolved.append(
                    f"{title!r}: {uid} selects "
                    f"{variable.get('query')!r} datasources but the panel "
                    f"declares type {source.get('type')!r}"
                )
                continue
            # The variable's saved value is what a freshly provisioned
            # Grafana loads the panel against, before anybody touches
            # the picker. If it names a uid nothing provisions, the
            # first paint is empty.
            saved = (variable.get("current") or {}).get("value")
            if saved not in provisioned:
                unresolved.append(
                    f"{title!r}: {uid} defaults to uid {saved!r}, which "
                    "is provisioned nowhere"
                )

        assert not unresolved, (
            "these panels cannot resolve a datasource when the dashboard "
            f"is provisioned from a file: {unresolved}. A panel that "
            "cannot resolve one renders empty with no error banner, "
            "which is indistinguishable from an idle fleet — the same "
            "failure mode the metric-name checks above exist to catch, "
            "one layer down."
        )

    def test_the_provisioned_datasource_points_at_the_overlay(self) -> None:
        provisioned = _provisioned_datasources()
        assert len(provisioned) == 1, (
            "one datasource, so the dashboard variable's fallback (the "
            f"first Prometheus in the org) is unambiguous: {provisioned}"
        )
        (source,) = provisioned.values()
        assert source["type"] == "prometheus"
        # The compose service name on the overlay's network. `127.0.0.1`
        # here would be Grafana's own loopback, and a published host
        # port would not exist from inside the container.
        prometheus_port = _load_yaml("compose.observability.yml")["services"][
            "prometheus"
        ]["ports"][0]
        assert prometheus_port.endswith(":9090")
        assert source["url"] == "http://prometheus:9090"

    def test_the_dashboard_provider_reads_the_mounted_directory(self) -> None:
        # A provider pointing at an empty directory starts Grafana
        # perfectly happily and provisions nothing, which looks exactly
        # like a Grafana that is working until you go looking for the
        # dashboard. The two ends have to agree, so they are asserted to.
        provider = _load_yaml(_GRAFANA_DASHBOARDS.relative_to(_OBS).as_posix())
        (entry,) = provider["providers"]
        directory = entry["options"]["path"]

        mounts = _compose_mounts("compose.viewers.yml", "grafana")
        dashboards = {
            target: source
            for target, source in mounts.items()
            if target.startswith(f"{directory}/")
        }
        assert dashboards, (
            f"the provider reads {directory} and `compose.viewers.yml` "
            f"mounts nothing into it: {sorted(mounts)}"
        )
        assert set(dashboards.values()) == {"./deploy/observability/dashboard.json"}
        assert entry["type"] == "file"

        # And the provisioning tree itself reaches Grafana's own path,
        # or neither the provider nor the datasource is ever read.
        assert (
            mounts["/etc/grafana/provisioning"]
            == "./deploy/observability/grafana/provisioning"
        )


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


class TestTheViewersStayASeparateDecision:
    """Grafana and Jaeger are a third file, and the third file stays small.

    The overlay above is the thing you leave running: it has retention,
    it evaluates `alerts.yml`, and `:9090/alerts` answers the question
    that has to be answerable at 3am. Grafana and Jaeger are two more
    processes whose whole job is drawing pictures for somebody who is
    currently looking. They could not go in the overlay anyway —
    `test_the_overlay_only_adds_services_and_env` pins its service set —
    and that constraint happens to be the right shape.
    """

    def test_it_only_adds_the_two_viewers(self) -> None:
        base = yaml.safe_load(
            (_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        )
        overlay = _load_yaml("compose.observability.yml")
        viewers = _load_yaml("compose.viewers.yml")
        added = (
            set(viewers["services"]) - set(base["services"]) - set(overlay["services"])
        )
        assert added == {"grafana", "jaeger"}, (
            "the viewers file has grown a service that is neither a "
            f"viewer nor an override of something below it: {added}"
        )
        # The only default-stack service it touches, and — like the
        # overlay's own edit to it — additively, environment only.
        assert set(viewers["services"]) & set(base["services"]) == {"app"}
        assert set(viewers["services"]["app"]) == {"environment"}

    def test_it_does_not_turn_content_capture_on_either(self) -> None:
        # The overlay is asserted not to do this three tests up. A
        # second file that overrides `app`'s environment is a second
        # place it could happen, and paper text reaching a trace store
        # with a UI on it is strictly worse than it reaching a log line.
        env = _load_yaml("compose.viewers.yml")["services"]["app"]["environment"]
        assert "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT" not in env
        assert "LOG_CAPTURE_USER_CONTENT" not in env

    def test_the_trace_viewer_keeps_its_ingest_ports_off_the_host(self) -> None:
        # The UI is published on loopback; the OTLP receivers are not
        # published at all. A published 4317/4318 is an unauthenticated
        # write endpoint for anything that can reach the host.
        published = _load_yaml("compose.viewers.yml")["services"]["jaeger"]["ports"]
        assert [port.split(":")[-1] for port in published] == ["16686"]
        for port in published:
            assert "127.0.0.1" in port

    def test_the_traces_fragment_does_not_restate_the_suffix_setting(self) -> None:
        # `compose.viewers.yml` hands the collector a SECOND `--config`
        # rather than replacing the first, precisely so that
        # `add_metric_suffixes: false` — which every metric name in
        # `alerts.yml` and `dashboard.json` depends on, and which
        # `test_collector_disables_metric_suffixes` guards in exactly
        # one file — cannot acquire a second home to drift in.
        fragment = _load_yaml("otel-collector-traces.yaml")
        assert "prometheus" not in fragment["exporters"], (
            "the traces fragment has grown a Prometheus exporter, which "
            "means the suffix setting now exists in two files and the "
            "test that guards it only reads one of them"
        )
        # The whole document, not the raw text: the header block
        # explains the setting at length and should keep being allowed
        # to. What must not appear is the setting itself.
        assert "add_metric_suffixes" not in json.dumps(fragment)
        assert "metrics" not in fragment["service"]["pipelines"], (
            "the traces fragment restates the metrics pipeline, so the "
            "merged config no longer inherits it from the base file"
        )
        command = _load_yaml("compose.viewers.yml")["services"]["otel-collector"][
            "command"
        ]
        assert command == [
            "--config=/etc/otelcol/config.yaml",
            "--config=/etc/otelcol/traces.yaml",
        ], f"the base config is no longer the first --config: {command}"


class TestTheAlertRulesAreSyntaxChecked:
    """The rules were never parsed by anything until WO-INF1.

    Everything above reads `alerts.yml` as YAML and checks the metric
    NAMES inside it. None of that parses PromQL, and none of it is what
    Prometheus does at load: an `expr` that does not parse, a `for:`
    that is not a duration, a duplicated group name — every one of those
    passes this file and is rejected by the process that was supposed to
    evaluate it, at the moment somebody stands the overlay up during an
    incident.

    `promtool` is the parser, it ships inside the image the overlay
    already pins, and the CI step that runs it is asserted here because
    a deleted workflow step is otherwise invisible: the rules would go
    back to never having been parsed and every test in this file would
    stay green.
    """

    def test_ci_checks_the_alert_rules_with_promtool(self) -> None:
        workflow = _WORKFLOW.read_text(encoding="utf-8")
        assert "promtool" in workflow, (
            "no `promtool` in the workflow: nothing parses `alerts.yml` "
            "before the Prometheus that has to load it does"
        )
        assert "check rules /etc/prometheus/alerts.yml" in workflow
        # `check config` follows `rule_files:` out of prometheus.yml, so
        # it additionally proves the path the container loads from
        # resolves — but reports "0 rule files found" and SUCCEEDS if
        # that stanza is deleted, which is why both invocations are
        # asserted rather than either alone.
        assert "check config /etc/prometheus/prometheus.yml" in workflow

    def test_the_checker_is_the_image_that_evaluates_them(self) -> None:
        # A promtool from a different Prometheus than the one the
        # overlay runs is a checker that can accept what the evaluator
        # rejects — the exact class of silent drift this whole file
        # exists to prevent, one layer up.
        image = _load_yaml("compose.observability.yml")["services"]["prometheus"][
            "image"
        ]
        workflow = _WORKFLOW.read_text(encoding="utf-8")
        assert f"{image}\n" in workflow or f"{image} " in workflow, (
            f"the overlay evaluates the rules with {image}, and the "
            "workflow checks them with something else"
        )
