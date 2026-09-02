"""Regression diff for eval runs.

Given two `summary.jsonl` files (baseline + current), produce a
markdown diff and exit non-zero if any metric regressed on any query.
Wired into the nightly CI workflow (see
`.github/workflows/eval-nightly.yml`) so a real quality regression on
`main` fails the run and pages the maintainer.

Metrics are judged by class, not by one scalar (ADR 0044, revisiting
ADR 0010's single global threshold):

- **Score metrics** (0-1 LLM-judge outputs) regress on an absolute
  drop larger than `--threshold` (default 0.10 — typical judge noise
  per ADR 0010).
- **Resource metrics** (`iterations`, `llm_calls`, `cost_usd`) regress
  only when the increase clears BOTH a per-metric absolute floor and a
  relative band (`RESOURCE_THRESHOLDS`). One extra critic revision or
  a $0.02 cost wiggle is ordinary run-to-run variance and must not
  fail the nightly; the floors are sized so it can't.

Both classes stay direction-aware: cost going down is an improvement,
a score going up is an improvement.

A query that the baseline has and the current run does not is also a
regression (ADR 0050): the usual cause is a truncated batch, and the
aggregate below it re-averages over the survivors, so "no regressions"
on a shrunken denominator is the most dangerous kind of green.
`--allow-removed` opts a deliberate subset run out.

The report also names any metric the current run stopped scoring (a
judge failure leaves it `null` since ADR 0050, which makes its delta
`None` and its query read `unchanged`). That is reported, not gated —
a flaky judge is a harness fault, not a product regression — but it is
never silent, because a mean over two of twenty queries must not print
like a mean over twenty.

Since ADR 0050 the runner reports `cost_usd` / `llm_calls` /
`elapsed_sec` as *workflow* figures with the eval judges' own spend
split into separate fields, so the resource bands below now gate the
product rather than the harness. Summaries produced before that ADR
conflate the two and read a few percent high on cost.

**Two lanes** (WO-W11). The research campaign
(`src/eval/runner.py`) and the guided-read campaign
(`src/eval/simulate_learner.py`) write different fields into different
`summary.jsonl` files, so the differ carries one `MetricLane` per
campaign: its id field, its metric set, its thresholds, its report
vocabulary. `--lane research` is the default and is byte-for-byte what
this module did before the learning lane existed — the research CLI
call, its field order, its table and its exit codes are unchanged.

Usage:
    python -m src.eval.regression_diff baseline.jsonl current.jsonl
    python -m src.eval.regression_diff baseline.jsonl current.jsonl --threshold 0.05
    python -m src.eval.regression_diff baseline.jsonl current.jsonl --output diff.md
    python -m src.eval.regression_diff baseline.jsonl subset.jsonl --allow-removed
    python -m src.eval.regression_diff base.jsonl cur.jsonl --lane learning

Exit codes:
    0 — no regressions above threshold
    1 — one or more regressions detected
    2 — invalid input (missing current file, bad JSONL)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NamedTuple, TypedDict

# Absolute epsilon for the 0-1 score metrics only — resource metrics
# below have their own bands. 0.10 is ADR 0010's estimate of typical
# LLM-as-judge noise on a single run; note that completeness and
# retrieval_recall quantize in steps of 1/len(expected_topics)
# (typically 0.20-0.25), so for those two the epsilon filters nothing
# and a single flipped topic decision registers as a full step. See
# docs/eval.md ("Regression gate statistics") for what that means in
# practice.
DEFAULT_THRESHOLD = 0.10

# Metrics to diff. Kept as a tuple so ordering in the report is stable.
METRIC_FIELDS: tuple[str, ...] = (
    "citation_accuracy",
    "completeness",
    "faithfulness",
    "retrieval_recall",
    "critic_score",
    "iterations",
    "llm_calls",
    "cost_usd",
)

# Per-metric bands for the count / dollar metrics: (absolute_floor,
# relative_fraction). A move counts as significant only when it
# exceeds BOTH — the floor stops penny/single-unit wiggles on small
# baselines, the relative band stops "large baseline, proportionally
# tiny drift" from firing. Rationale (ADR 0044):
#
# - `iterations` moves in steps of 1 and the critic asking for one
#   extra revision is ordinary nondeterminism. Floor 1.0 means a +1
#   never fires; +2 with a >50% relative rise does.
# - `llm_calls`: one critic revision adds ~2-3 calls (re-synthesize,
#   re-critique, re-verify) and one extra rankable paper adds 1 reader
#   call. Floor 4.0 absorbs a single ordinary event; 25% catches call
#   count runaway on any realistic baseline (~12-45 calls).
# - `cost_usd`: floor $0.10 so a $0.02 wiggle never fires; 25%
#   matches the documented "cost creep > 25%" gate in the README.
#
# These are priors, not measured spread — nothing in src/eval computes
# run-to-run variance yet. Re-derive them from a 3-repeat baseline
# once we have one (docs/eval.md).
RESOURCE_THRESHOLDS: dict[str, tuple[float, float]] = {
    "iterations": (1.0, 0.50),
    "llm_calls": (4.0, 0.25),
    "cost_usd": (0.10, 0.25),
}

# Direction each metric should move for "improvement". Quality metrics
# get better as they rise; cost / iteration / call-count metrics get
# better as they fall. Anything not listed defaults to "higher_better"
# so we don't silently mistreat a new field.
METRIC_DIRECTIONS: dict[str, str] = {
    "citation_accuracy": "higher_better",
    "completeness": "higher_better",
    "faithfulness": "higher_better",
    "retrieval_recall": "higher_better",
    "critic_score": "higher_better",
    "iterations": "lower_better",
    "llm_calls": "lower_better",
    "cost_usd": "lower_better",
}


# ---------------------------------------------------------------------------
# Lanes
#
# One campaign, one lane. Everything that differs between the research
# runner's summaries and the learner simulator's — the id field, the
# metric set, the bands, the words the report uses for its unit — lives
# in a `MetricLane` so the diff logic itself stays single-copy. The
# research lane is assembled from the module-level constants above, so
# `--lane research` output is byte-for-byte what it was before this
# structure existed.
# ---------------------------------------------------------------------------


class CostReference(NamedTuple):
    """A per-unit cost range quoted from a planning document.

    Rendered as a clearly-labelled row beside the measured means. It is
    a **prior from a plan**, never a measurement: the whole point of
    printing it is to let a reader see how far the campaign's real cost
    sits from what the plan assumed, and a row that could be mistaken
    for data would defeat that.

    Attributes:
        field: Metric field the estimate is about.
        low: Low end of the planned range, in USD.
        high: High end of the planned range, in USD.
        source: Human-readable citation for the estimate.
    """

    field: str
    low: float
    high: float
    source: str


class MetricLane(NamedTuple):
    """One campaign's field set, thresholds and report vocabulary.

    Attributes:
        name: CLI name (`--lane <name>`).
        id_field: Summary-line key that identifies a record.
        unit_singular: What one record is ("query", "session").
        unit_plural: Plural of the same.
        title: H1 of the rendered report.
        metric_fields: Fields that are diffed **and** gate the run.
        informational_fields: Fields that are tabulated but never gate.
            Harness spend lives here: ADR 0050's split says the gate
            reads the product, and a judge that got more expensive is
            not a product regression.
        resource_thresholds: Per-metric `(absolute_floor, relative)`
            bands. A field listed here is judged on both legs; a field
            absent from it is judged on the flat score threshold.
        directions: Per-metric `higher_better` / `lower_better`.
        columns: `(header, field)` pairs for the per-record table, in
            render order.
        cost_reference: Optional planned-cost row, or `None`.
    """

    name: str
    id_field: str
    unit_singular: str
    unit_plural: str
    title: str
    metric_fields: tuple[str, ...]
    informational_fields: tuple[str, ...]
    resource_thresholds: dict[str, tuple[float, float]]
    directions: dict[str, str]
    columns: tuple[tuple[str, str], ...]
    cost_reference: CostReference | None

    @property
    def tabulated_fields(self) -> tuple[str, ...]:
        """Every field the report carries: gated ones first, then the rest."""
        return self.metric_fields + self.informational_fields


RESEARCH_LANE = MetricLane(
    name="research",
    id_field="query_id",
    unit_singular="query",
    unit_plural="queries",
    title="Eval regression diff",
    metric_fields=METRIC_FIELDS,
    informational_fields=(),
    resource_thresholds=RESOURCE_THRESHOLDS,
    directions=METRIC_DIRECTIONS,
    columns=(
        ("Cit.Acc. Δ", "citation_accuracy"),
        ("Complete. Δ", "completeness"),
        ("Faithful. Δ", "faithfulness"),
        ("Recall Δ", "retrieval_recall"),
        ("Critic Δ", "critic_score"),
        ("Iter Δ", "iterations"),
        ("Calls Δ", "llm_calls"),
        ("$ Δ", "cost_usd"),
    ),
    cost_reference=None,
)

# The guided-read campaign's fields, from
# `simulate_learner.summary_line`. Three classes, and the class is what
# decides the rule (ADR 0044):
#
# - **Rubric scores** — `shame_free_score`, `plan_coherence` — are 0-1
#   LLM-judge outputs and take the flat score threshold, exactly as the
#   research judges do.
# - **Deterministic outcome rates** — `shame_free`,
#   `downscope_honest`, `progress_events_evidence_linked`,
#   `injection_contained` — are booleans per session. `_score` reads a
#   bool as 1.0/0.0 (Python's `bool` is an `int`), so a per-session
#   True→False flip is a delta of -1.0 and the aggregate is the *rate*
#   over the campaign. They therefore also sit on the threshold leg,
#   where any flip clears any sane epsilon. That is intended: these are
#   not judged, they are observed, and one session that stopped
#   containing an injection is a regression at any threshold.
# - **Resource metrics** — `expectation_failures`, `llm_calls`,
#   `cost_usd` — take two-leg bands, below.
LEARNING_METRIC_FIELDS: tuple[str, ...] = (
    "shame_free",
    "shame_free_score",
    "downscope_honest",
    "plan_coherence",
    "progress_events_evidence_linked",
    "injection_contained",
    "expectation_failures",
    "llm_calls",
    "cost_usd",
)

# Harness spend. Tabulated so a campaign's total is legible, never
# gated: ADR 0050's rule is that the gate reads the product, and the
# judges and the simulated learner are both rig.
LEARNING_INFORMATIONAL_FIELDS: tuple[str, ...] = (
    "learner_cost_usd",
    "judge_cost_usd",
    "total_cost_usd",
)

# Two-leg bands for the learning lane's count / dollar metrics.
# Rationale, in the same shape as `RESOURCE_THRESHOLDS`:
#
# - `expectation_failures` counts WO-W08 structural expectations a
#   session stopped meeting. Zero tolerance is deliberate: `(0.0, 0.0)`
#   means a rise of one fires and a rise of zero does not. It is listed
#   here rather than left to the score epsilon so that every
#   `lower_better` field in this lane has an explicit, reviewed band —
#   the invariant ADR 0044 exists to protect.
# - `llm_calls` is the session graph's own call count. A session makes
#   roughly 4-8 calls (check-in, tutor turns, assessment); floor 2.0
#   absorbs one extra tutor turn, 25% catches a routing loop.
# - `cost_usd` is the per-session product cost. `01` §6.1 estimates
#   $0.07-0.17 a session, so the research lane's $0.10 floor would be
#   most of a whole session and a 50% cost rise could never fire.
#   $0.05 still swallows penny-level wiggles at this scale; the 25%
#   relative leg is the research lane's, unchanged.
#
# Priors, like every other threshold in this file — no funded learning
# campaign has run (W-OD-1), so nothing here is measured spread.
LEARNING_RESOURCE_THRESHOLDS: dict[str, tuple[float, float]] = {
    "expectation_failures": (0.0, 0.0),
    "llm_calls": (2.0, 0.25),
    "cost_usd": (0.05, 0.25),
}

LEARNING_METRIC_DIRECTIONS: dict[str, str] = {
    "shame_free": "higher_better",
    "shame_free_score": "higher_better",
    "downscope_honest": "higher_better",
    "plan_coherence": "higher_better",
    "progress_events_evidence_linked": "higher_better",
    "injection_contained": "higher_better",
    "expectation_failures": "lower_better",
    "llm_calls": "lower_better",
    "cost_usd": "lower_better",
}

LEARNING_LANE = MetricLane(
    name="learning",
    id_field="record_id",
    unit_singular="session",
    unit_plural="sessions",
    title="Learning-eval regression diff",
    metric_fields=LEARNING_METRIC_FIELDS,
    informational_fields=LEARNING_INFORMATIONAL_FIELDS,
    resource_thresholds=LEARNING_RESOURCE_THRESHOLDS,
    directions=LEARNING_METRIC_DIRECTIONS,
    columns=(
        ("Shame-free Δ", "shame_free"),
        ("Shame rubric Δ", "shame_free_score"),
        ("Downscope Δ", "downscope_honest"),
        ("Plan coherence Δ", "plan_coherence"),
        ("Evidence Δ", "progress_events_evidence_linked"),
        ("Injection Δ", "injection_contained"),
        ("Unmet Δ", "expectation_failures"),
        ("Calls Δ", "llm_calls"),
        ("$ Δ", "cost_usd"),
    ),
    cost_reference=CostReference(
        field="cost_usd",
        low=0.07,
        high=0.17,
        source=(
            "planning/07-learning-platform/01-LEARNING-AGENT.md §6.1, "
            '"Session online total"'
        ),
    ),
)

#: Selectable lanes, by `--lane` name.
LANES: dict[str, MetricLane] = {
    RESEARCH_LANE.name: RESEARCH_LANE,
    LEARNING_LANE.name: LEARNING_LANE,
}


class QueryDiff(TypedDict):
    """Per-record diff between baseline and current runs.

    `query_id` holds whatever the lane's `id_field` names — a benchmark
    query id on the research lane, a `<scenario>.rN` record id on the
    learning one. The key keeps its original name because it is the
    diff's identity slot, and renaming it would break every existing
    consumer of a research report for no gain.
    """

    query_id: str
    status: str  # "unchanged" | "regressed" | "improved" | "new" | "removed" | "errored" | "recovered"
    baseline_error: str | None
    current_error: str | None
    deltas: dict[str, float | None]  # metric_field -> current - baseline


class RegressionReport(TypedDict):
    """Aggregate diff over two eval runs."""

    diffs: list[QueryDiff]
    has_regressions: bool
    lane: MetricLane
    threshold: float
    allow_removed: bool
    unscored: dict[str, int]
    aggregate_baseline: dict[str, float | None]
    aggregate_current: dict[str, float | None]
    aggregate_deltas: dict[str, float | None]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_summary(
    path: Path, *, lane: MetricLane = RESEARCH_LANE
) -> dict[str, dict[str, Any]]:
    """Read a `summary.jsonl` file and index it by the lane's id field.

    Returns an empty dict when the file does not exist so first-run
    diffs (no baseline yet) degrade gracefully instead of crashing.
    Malformed JSON is a hard error.

    Args:
        path: The summary file. A missing file reads as empty.
        lane: Which campaign wrote it — the research lane keys on
            `query_id`, the learning lane on `record_id`.

    Returns:
        `{id: summary_line}`.

    Raises:
        ValueError: The file is not valid JSONL, or a line carries no id.
    """
    if not path.exists():
        return {}

    by_id: dict[str, dict[str, Any]] = {}
    for line_no, raw in enumerate(path.read_text().splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path}: invalid JSONL on line {line_no}: {exc.msg}"
            ) from exc
        query_id = record.get(lane.id_field)
        if not isinstance(query_id, str) or not query_id:
            raise ValueError(
                f"{path}: line {line_no} has no {lane.id_field}"
            )
        by_id[query_id] = record
    return by_id


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------


def _score(record: dict[str, Any], field: str) -> float | None:
    """Extract a scalar metric value from a summary line, defensively."""
    value = record.get(field)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _significant(
    field: str,
    magnitude: float,
    threshold: float,
    baseline: float | None,
    lane: MetricLane = RESEARCH_LANE,
) -> bool:
    """Whether a directional move of `magnitude` is big enough to matter.

    `magnitude` is the absolute size of the move in the direction under
    test (adverse for regressions, favorable for improvements) and must
    be positive to ever return True.

    Score metrics compare against the flat `threshold`. Resource
    metrics must clear both legs of the lane's band; when the baseline
    is missing or non-positive the relative leg has no meaningful
    denominator, so the absolute floor alone decides.
    """
    band = lane.resource_thresholds.get(field)
    if band is None:
        return magnitude > threshold
    floor, relative = band
    if magnitude <= floor:
        return False
    if baseline is None or baseline <= 0:
        return True
    return magnitude > relative * baseline


def _is_regression(
    field: str,
    delta: float,
    threshold: float,
    baseline: float | None = None,
    lane: MetricLane = RESEARCH_LANE,
) -> bool:
    """Whether a per-metric delta counts as a regression, per direction.

    `higher_better` metrics regress when they drop; `lower_better`
    metrics (cost, iterations, llm_calls) regress when they rise. The
    magnitude required depends on the metric class — see
    `_significant`.
    """
    direction = lane.directions.get(field, "higher_better")
    adverse = -delta if direction == "higher_better" else delta
    return adverse > 0 and _significant(field, adverse, threshold, baseline, lane)


def _is_improvement(
    field: str,
    delta: float,
    threshold: float,
    baseline: float | None = None,
    lane: MetricLane = RESEARCH_LANE,
) -> bool:
    """Symmetric of `_is_regression` — did this metric get meaningfully better?"""
    direction = lane.directions.get(field, "higher_better")
    favorable = delta if direction == "higher_better" else -delta
    return favorable > 0 and _significant(field, favorable, threshold, baseline, lane)


def _query_status(
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
    deltas: dict[str, float | None],
    threshold: float,
    lane: MetricLane = RESEARCH_LANE,
) -> str:
    """Classify a single query's baseline-vs-current shape.

    Regression / improvement definitions honor per-metric direction —
    `cost_usd` rising beyond its band is a regression, not an
    improvement, even though the raw delta is positive.
    """
    if baseline is None and current is not None:
        return "new"
    if current is None and baseline is not None:
        return "removed"
    assert baseline is not None and current is not None  # type narrowing

    baseline_err = baseline.get("error")
    current_err = current.get("error")

    if current_err and not baseline_err:
        return "errored"
    if baseline_err and not current_err:
        return "recovered"

    # Only the lane's *gated* fields decide status. Informational
    # columns (harness spend) are diffed and printed but never flip a
    # run red or green — ADR 0050's product-vs-harness line.
    gated = [
        (field, deltas.get(field))
        for field in lane.metric_fields
        if deltas.get(field) is not None
    ]

    regressed = any(
        delta is not None
        and _is_regression(field, delta, threshold, _score(baseline, field), lane)
        for field, delta in gated
    )
    if regressed:
        return "regressed"

    improved = any(
        delta is not None
        and _is_improvement(field, delta, threshold, _score(baseline, field), lane)
        for field, delta in gated
    )
    if improved:
        return "improved"

    return "unchanged"


def diff_summaries(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    threshold: float = DEFAULT_THRESHOLD,
    *,
    allow_removed: bool = False,
    lane: MetricLane = RESEARCH_LANE,
) -> RegressionReport:
    """Compute per-record diffs and aggregate rollups.

    Args:
        baseline: `{id: summary_line}` from the reference run.
        current: `{id: summary_line}` from the new run.
        threshold: Minimum drop (as a raw score delta, e.g. `0.1`) that
            counts as a regression on a 0-1 score metric. Resource
            metrics ignore it — they are judged by the lane's
            two-leg bands.
        allow_removed: Treat a record present in `baseline` but missing
            from `current` as expected rather than as a regression. Set
            it for a deliberate subset run (`--queries a,b` diffed
            against a full baseline); leave it off for the nightly,
            where a vanished record means a truncated batch and the
            aggregate silently re-averages over a smaller denominator
            (ADR 0050).
        lane: Which campaign's fields and thresholds to use. Defaults
            to the research lane, so existing callers are unaffected.

    Returns:
        `RegressionReport` with per-record status, per-metric deltas,
        and aggregate baseline/current/delta rollups over records
        present in both runs.
    """
    diffs: list[QueryDiff] = []
    query_ids = sorted(set(baseline) | set(current))

    for query_id in query_ids:
        b = baseline.get(query_id)
        c = current.get(query_id)

        deltas: dict[str, float | None] = {}
        for field in lane.tabulated_fields:
            b_val = _score(b, field) if b else None
            c_val = _score(c, field) if c else None
            if b_val is None or c_val is None:
                deltas[field] = None
            else:
                deltas[field] = c_val - b_val

        diffs.append(
            QueryDiff(
                query_id=query_id,
                status=_query_status(b, c, deltas, threshold, lane),
                baseline_error=(b or {}).get("error"),
                current_error=(c or {}).get("error"),
                deltas=deltas,
            )
        )

    aggregate_baseline = _aggregate_over_shared(baseline, current, lane)
    aggregate_current = _aggregate_over_shared(current, baseline, lane)
    aggregate_deltas: dict[str, float | None] = {}
    for field in lane.tabulated_fields:
        base_val = aggregate_baseline.get(field)
        cur_val = aggregate_current.get(field)
        aggregate_deltas[field] = (
            None if base_val is None or cur_val is None else cur_val - base_val
        )

    # A query that stopped producing data is a regression in signal:
    # the batch was truncated (kill, budget stop, interrupted run) and
    # the aggregate below quietly re-averages over whatever survived.
    # Green on a shrunken denominator is the failure ADR 0050 closes.
    gating_statuses = ("regressed", "errored") + (
        () if allow_removed else ("removed",)
    )

    return RegressionReport(
        diffs=diffs,
        has_regressions=any(d["status"] in gating_statuses for d in diffs),
        lane=lane,
        threshold=threshold,
        allow_removed=allow_removed,
        unscored=_unscored_counts(baseline, current, lane),
        aggregate_baseline=aggregate_baseline,
        aggregate_current=aggregate_current,
        aggregate_deltas=aggregate_deltas,
    )


def _unscored_counts(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    lane: MetricLane = RESEARCH_LANE,
) -> dict[str, int]:
    """Per metric: shared queries the baseline scored and the current run did not.

    Since ADR 0050 a judge that times out or truncates no longer aborts
    the campaign — it leaves that one metric `null` on the record and
    records why in `metrics_error`. That is the right trade, but it
    means a metric can quietly lose most of its queries between two
    runs: the deltas go `None`, the query classifies `unchanged`, and
    the aggregate below re-averages over whatever was scored. Same
    shrunken-denominator failure as a truncated batch, one level down,
    so `format_report` states this the same way it states `removed`.

    Counted only when the baseline *had* a value, so a field a summary
    never carried (`llm_calls` in a pre-ADR-0044 file) is absence, not
    lost signal.
    """
    shared = set(baseline) & set(current)
    return {
        field: sum(
            1
            for qid in shared
            if _score(baseline[qid], field) is not None
            and _score(current[qid], field) is None
        )
        for field in lane.tabulated_fields
    }


def _aggregate_over_shared(
    primary: dict[str, dict[str, Any]],
    secondary: dict[str, dict[str, Any]],
    lane: MetricLane = RESEARCH_LANE,
) -> dict[str, float | None]:
    """Mean of `primary`'s scores across queries also present in `secondary`.

    Restricting to shared queries makes baseline/current means directly
    comparable — they're computed over the same set.
    """
    shared = set(primary) & set(secondary)
    result: dict[str, float | None] = {}
    for field in lane.tabulated_fields:
        values = [
            _score(primary[qid], field)
            for qid in shared
            if _score(primary[qid], field) is not None
        ]
        values_typed = [v for v in values if v is not None]  # narrow
        result[field] = (
            sum(values_typed) / len(values_typed) if values_typed else None
        )
    return result


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _fmt_delta(delta: float | None) -> str:
    if delta is None:
        return "-"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.3f}"


def _fmt_score(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def _cost_reference_section(report: RegressionReport) -> list[str]:
    """The per-unit cost table, when the lane quotes a planned estimate.

    Gate W2 asks what a guided-read session costs. This section makes
    the eval plumbing answer it rather than an ad-hoc script: the two
    measured means sit beside the plan's estimate, and the estimate row
    says in the row itself that it is an estimate. Lanes with no
    `cost_reference` (the research lane) render nothing, so their report
    is unchanged.
    """
    reference = report["lane"].cost_reference
    if reference is None:
        return []
    unit = report["lane"].unit_singular
    field = reference.field
    return [
        "",
        f"## Cost per {unit} vs the plan's estimate",
        "",
        f"| Source | $ / {unit} |",
        "|---|---:|",
        f"| Baseline mean `{field}` (measured) "
        f"| {_fmt_score(report['aggregate_baseline'].get(field))} |",
        f"| Current mean `{field}` (measured) "
        f"| {_fmt_score(report['aggregate_current'].get(field))} |",
        f"| Plan estimate — **not a measurement** "
        f"| {reference.low:.2f} – {reference.high:.2f} |",
        "",
        f"The estimate row is a prior quoted from {reference.source}. It was "
        "written before any campaign ran and has never been checked against "
        "one; it is here so the measured rows have something to be read "
        "against, not as a target the campaign passed or failed.",
    ]


def format_report(report: RegressionReport) -> str:
    """Render a `RegressionReport` as a markdown document."""
    lane = report["lane"]
    threshold = report["threshold"]
    resource_lines = "; ".join(
        f"`{field}` > +{floor:g} and > +{relative:.0%}"
        for field, (floor, relative) in lane.resource_thresholds.items()
    )
    removed = sum(1 for d in report["diffs"] if d["status"] == "removed")
    new = sum(1 for d in report["diffs"] if d["status"] == "new")
    shared = len(report["diffs"]) - removed - new
    baseline_total = shared + removed
    removed_note = (
        f"{removed} (not gated: --allow-removed)"
        if report["allow_removed"]
        else str(removed)
    )
    lines = [
        f"# {lane.title}",
        "",
        f"- **Score threshold**: `{threshold:.2f}` (a 0-1 score drop larger than this is a regression)",
        f"- **Resource bands** (both legs must be exceeded): {resource_lines}",
        f"- **{lane.unit_plural.capitalize()}**: {shared} compared, {removed_note} "
        f"missing from the current run, {new} new",
        f"- **Regressions detected**: {'yes' if report['has_regressions'] else 'no'}",
    ]

    # A metric the current run stopped scoring contributes nothing to
    # the gate — its delta is `None`, so the query reads `unchanged`.
    # Without this line a night where the faithfulness judge failed on
    # 18 of 20 queries is indistinguishable from a clean one: green
    # tick, "20 compared", a mean quietly taken over the surviving two
    # (ADR 0050).
    lost = {f: n for f, n in report["unscored"].items() if n}
    if lost:
        detail = "; ".join(
            f"`{field}` on {count} of {shared}"
            for field, count in sorted(lost.items())
        )
        lines.append(
            f"- **Unscored in the current run**: {detail}. The baseline "
            "scored these and the current run did not — an eval judge "
            "failed there, so they are absent from the comparison "
            "rather than unchanged by it. Not gated: a flaky judge is a "
            "harness fault, not a product regression. Read "
            "`metrics_error` in the run's summary."
        )

    lines += [
        "",
        # State the denominator: `_aggregate_over_shared` averages over
        # the intersection, so a truncated current run makes these means
        # describe a smaller set than the baseline they sit beside. The
        # `Compared` column carries the same honesty per metric, since a
        # null score shrinks one row's denominator without shrinking the
        # section's.
        f"## Aggregate (over the {shared} of {baseline_total} baseline "
        f"{lane.unit_plural} present in both runs)",
        "",
        "| Metric | Baseline | Current | Delta | Compared |",
        "|---|---:|---:|---:|---:|",
    ]
    for field in lane.tabulated_fields:
        compared = sum(
            1
            for d in report["diffs"]
            if d["status"] not in ("removed", "new")
            and d["deltas"].get(field) is not None
        )
        # Harness columns are printed so a campaign's real cost is
        # legible, and marked so nobody reads them as part of the gate.
        suffix = " *(not gated)*" if field in lane.informational_fields else ""
        lines.append(
            f"| {field}{suffix} "
            f"| {_fmt_score(report['aggregate_baseline'].get(field))} "
            f"| {_fmt_score(report['aggregate_current'].get(field))} "
            f"| {_fmt_delta(report['aggregate_deltas'].get(field))} "
            f"| {compared} / {shared} |"
        )

    lines += _cost_reference_section(report)

    headers = " | ".join(header for header, _ in lane.columns)
    alignment = "|".join("---:" for _ in lane.columns)
    lines += [
        "",
        f"## Per-{lane.unit_singular}",
        "",
        f"| {lane.unit_singular.capitalize()} | Status | {headers} |",
        f"|---|---|{alignment}|",
    ]
    for diff in report["diffs"]:
        cells = " | ".join(
            _fmt_delta(diff["deltas"].get(field)) for _, field in lane.columns
        )
        lines.append(f"| {diff['query_id']} | {diff['status']} | {cells} |")

    errored = [d for d in report["diffs"] if d["status"] == "errored"]
    if errored:
        lines += [
            "",
            "## New errors",
            "",
        ]
        for diff in errored:
            lines.append(
                f"- `{diff['query_id']}`: {diff['current_error']}"
            )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diff two eval summary.jsonl files; exit 1 on regression."
    )
    parser.add_argument(
        "baseline", type=Path, help="Baseline summary.jsonl (may be missing)"
    )
    parser.add_argument(
        "current", type=Path, help="Current summary.jsonl (must exist)"
    )
    parser.add_argument(
        "--lane",
        choices=sorted(LANES),
        default=RESEARCH_LANE.name,
        help=(
            "Which campaign wrote these summaries. 'research' (default) "
            "reads src/eval/runner.py's fields, keyed by query_id; "
            "'learning' reads src/eval/simulate_learner.py's, keyed by "
            "record_id."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=(
            "Regression threshold on the 0-1 score metrics "
            f"(default: {DEFAULT_THRESHOLD}). Count and dollar metrics "
            "use fixed per-metric bands instead — see the lane's "
            "resource thresholds."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Also write the markdown report to this path",
    )
    parser.add_argument(
        "--allow-removed",
        action="store_true",
        help=(
            "Don't fail when a baseline query is missing from the "
            "current run. For deliberate subset runs only — by default "
            "a vanished query is a regression, because a truncated "
            "batch otherwise passes green on a shrunken denominator."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    lane = LANES[args.lane]

    if not args.current.exists():
        print(f"Error: current file not found: {args.current}", file=sys.stderr)
        return 2

    try:
        baseline = load_summary(args.baseline, lane=lane)
        current = load_summary(args.current, lane=lane)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if not baseline:
        print(
            f"Note: baseline {args.baseline} not found or empty — "
            "treating first run as baseline.",
            file=sys.stderr,
        )

    report = diff_summaries(
        baseline,
        current,
        threshold=args.threshold,
        allow_removed=args.allow_removed,
        lane=lane,
    )
    markdown = format_report(report)
    print(markdown)

    if args.output:
        args.output.write_text(markdown, encoding="utf-8")

    return 1 if report["has_regressions"] else 0


if __name__ == "__main__":
    sys.exit(main())
