"""Regression diff for eval runs.

Given two `summary.jsonl` files (baseline + current), produce a
markdown diff and exit non-zero if any metric regressed by more than
`--threshold` on any query. Wired into the nightly CI workflow (see
`.github/workflows/eval-nightly.yml`) so a real quality regression on
`main` fails the run and pages the maintainer.

Usage:
    python -m src.eval.regression_diff baseline.jsonl current.jsonl
    python -m src.eval.regression_diff baseline.jsonl current.jsonl --threshold 0.05
    python -m src.eval.regression_diff baseline.jsonl current.jsonl --output diff.md

Exit codes:
    0 — no regressions above threshold
    1 — one or more regressions detected
    2 — invalid input (missing current file, bad JSONL)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TypedDict

DEFAULT_THRESHOLD = 0.10

# Metrics to diff. Kept as a tuple so ordering in the report is stable.
METRIC_FIELDS: tuple[str, ...] = (
    "citation_accuracy",
    "completeness",
    "faithfulness",
    "retrieval_recall",
    "critic_score",
)


class QueryDiff(TypedDict):
    """Per-query diff between baseline and current runs."""

    query_id: str
    status: str  # "unchanged" | "regressed" | "improved" | "new" | "removed" | "errored" | "recovered"
    baseline_error: str | None
    current_error: str | None
    deltas: dict[str, float | None]  # metric_field -> current - baseline


class RegressionReport(TypedDict):
    """Aggregate diff over two eval runs."""

    diffs: list[QueryDiff]
    has_regressions: bool
    threshold: float
    aggregate_baseline: dict[str, float | None]
    aggregate_current: dict[str, float | None]
    aggregate_deltas: dict[str, float | None]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_summary(path: Path) -> dict[str, dict[str, Any]]:
    """Read a `summary.jsonl` file and index it by `query_id`.

    Returns an empty dict when the file does not exist so first-run
    diffs (no baseline yet) degrade gracefully instead of crashing.
    Malformed JSON is a hard error.
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
        query_id = record.get("query_id")
        if not isinstance(query_id, str) or not query_id:
            raise ValueError(
                f"{path}: line {line_no} has no query_id"
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


def _query_status(
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
    deltas: dict[str, float | None],
    threshold: float,
) -> str:
    """Classify a single query's baseline-vs-current shape."""
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

    # Regression = any metric dropped by more than threshold.
    regressed = any(
        delta is not None and delta < -threshold for delta in deltas.values()
    )
    if regressed:
        return "regressed"

    improved = any(
        delta is not None and delta > threshold for delta in deltas.values()
    )
    if improved:
        return "improved"

    return "unchanged"


def diff_summaries(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    threshold: float = DEFAULT_THRESHOLD,
) -> RegressionReport:
    """Compute per-query diffs and aggregate rollups.

    Args:
        baseline: `{query_id: summary_line}` from the reference run.
        current: `{query_id: summary_line}` from the new run.
        threshold: Minimum drop (as a raw score delta, e.g. `0.1`) that
            counts as a regression on a metric.

    Returns:
        `RegressionReport` with per-query status, per-metric deltas, and
        aggregate baseline/current/delta rollups over queries present in
        both runs.
    """
    diffs: list[QueryDiff] = []
    query_ids = sorted(set(baseline) | set(current))

    for query_id in query_ids:
        b = baseline.get(query_id)
        c = current.get(query_id)

        deltas: dict[str, float | None] = {}
        for field in METRIC_FIELDS:
            b_val = _score(b, field) if b else None
            c_val = _score(c, field) if c else None
            if b_val is None or c_val is None:
                deltas[field] = None
            else:
                deltas[field] = c_val - b_val

        diffs.append(
            QueryDiff(
                query_id=query_id,
                status=_query_status(b, c, deltas, threshold),
                baseline_error=(b or {}).get("error"),
                current_error=(c or {}).get("error"),
                deltas=deltas,
            )
        )

    aggregate_baseline = _aggregate_over_shared(baseline, current)
    aggregate_current = _aggregate_over_shared(current, baseline)
    aggregate_deltas: dict[str, float | None] = {}
    for field in METRIC_FIELDS:
        b = aggregate_baseline.get(field)
        c = aggregate_current.get(field)
        aggregate_deltas[field] = None if b is None or c is None else c - b

    return RegressionReport(
        diffs=diffs,
        has_regressions=any(d["status"] in ("regressed", "errored") for d in diffs),
        threshold=threshold,
        aggregate_baseline=aggregate_baseline,
        aggregate_current=aggregate_current,
        aggregate_deltas=aggregate_deltas,
    )


def _aggregate_over_shared(
    primary: dict[str, dict[str, Any]],
    secondary: dict[str, dict[str, Any]],
) -> dict[str, float | None]:
    """Mean of `primary`'s scores across queries also present in `secondary`.

    Restricting to shared queries makes baseline/current means directly
    comparable — they're computed over the same set.
    """
    shared = set(primary) & set(secondary)
    result: dict[str, float | None] = {}
    for field in METRIC_FIELDS:
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


def format_report(report: RegressionReport) -> str:
    """Render a `RegressionReport` as a markdown document."""
    threshold = report["threshold"]
    lines = [
        "# Eval regression diff",
        "",
        f"- **Threshold**: `{threshold:.2f}` (a metric drop larger than this is a regression)",
        f"- **Regressions detected**: {'yes' if report['has_regressions'] else 'no'}",
        "",
        "## Aggregate (over queries present in both runs)",
        "",
        "| Metric | Baseline | Current | Delta |",
        "|---|---:|---:|---:|",
    ]
    for field in METRIC_FIELDS:
        lines.append(
            f"| {field} "
            f"| {_fmt_score(report['aggregate_baseline'].get(field))} "
            f"| {_fmt_score(report['aggregate_current'].get(field))} "
            f"| {_fmt_delta(report['aggregate_deltas'].get(field))} |"
        )

    lines += [
        "",
        "## Per-query",
        "",
        "| Query | Status | Cit.Acc. Δ | Complete. Δ | Faithful. Δ | Recall Δ | Critic Δ |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for diff in report["diffs"]:
        lines.append(
            f"| {diff['query_id']} "
            f"| {diff['status']} "
            f"| {_fmt_delta(diff['deltas'].get('citation_accuracy'))} "
            f"| {_fmt_delta(diff['deltas'].get('completeness'))} "
            f"| {_fmt_delta(diff['deltas'].get('faithfulness'))} "
            f"| {_fmt_delta(diff['deltas'].get('retrieval_recall'))} "
            f"| {_fmt_delta(diff['deltas'].get('critic_score'))} |"
        )

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
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Regression threshold on raw scores (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Also write the markdown report to this path",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if not args.current.exists():
        print(f"Error: current file not found: {args.current}", file=sys.stderr)
        return 2

    try:
        baseline = load_summary(args.baseline)
        current = load_summary(args.current)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if not baseline:
        print(
            f"Note: baseline {args.baseline} not found or empty — "
            "treating first run as baseline.",
            file=sys.stderr,
        )

    report = diff_summaries(baseline, current, threshold=args.threshold)
    markdown = format_report(report)
    print(markdown)

    if args.output:
        args.output.write_text(markdown, encoding="utf-8")

    return 1 if report["has_regressions"] else 0


if __name__ == "__main__":
    sys.exit(main())
