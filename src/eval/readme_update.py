"""Patch the README's eval-results block from a `summary.jsonl` file.

Nightly workflow calls this after producing the eval run; the
output goes into a stable block in README.md bracketed by:

    <!-- eval-nightly:start -->
    ...auto-generated content...
    <!-- eval-nightly:end -->

The script is idempotent: running it twice with the same input
produces the same output, and the block is the only region
touched. Anything outside the markers is preserved verbatim.

Invocation:

    python -m src.eval.readme_update \\
        --summary outputs/eval/<run_id>/summary.jsonl \\
        --readme README.md \\
        [--run-id <run_id>]

Exit codes:
    0 — README updated (or unchanged, still 0)
    1 — no markers found in the README
    2 — malformed summary.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# HTML comment markers so the nightly workflow's PR-opening step
# can rewrite the block without touching anything else.
START_MARKER = "<!-- eval-nightly:start -->"
END_MARKER = "<!-- eval-nightly:end -->"

# Fields in summary.jsonl the aggregate row cares about. Only rows
# with `error=None` count — a broken query shouldn't drag the mean.
METRIC_FIELDS: tuple[str, ...] = (
    "citation_accuracy",
    "faithfulness",
    "completeness",
    "retrieval_recall",
)
COST_FIELD = "cost_usd"
LATENCY_FIELD = "elapsed_sec"

# `citation_accuracy` is a ratio over the report's `[Author, Year]`
# tags: a report with none scores a free 1.0, which the metric's own
# docstring calls "the metric doesn't apply ... callers who want to
# penalize uncited reports can check `total_citations`". Averaging
# those 1.0s into the published README figure inflates it precisely
# when the system did the *least* citing, so rows reporting zero
# citations are excluded from that one mean and the exclusion is
# stated under the table (ADR 0050). Rows from summaries older than
# ADR 0050 carry no `total_citations` field at all; those stay in the
# mean rather than silently vanishing from it.
CITATION_FIELD = "citation_accuracy"
CITATION_COUNT_FIELD = "total_citations"

# Cost/latency are the *workflow's*, not the judges' — the runner
# splits them as of ADR 0050. `judge_cost_usd` is deliberately not
# published here: the README row answers "what does one research run
# cost", and the eval harness is not part of the product.


def render_block(
    records: list[dict[str, Any]], *, run_id: str | None = None
) -> str:
    """Build the auto-generated README block from summary.jsonl records.

    Returns just the markdown between the markers — the caller
    wraps in `START_MARKER \\n <this> \\n END_MARKER`.
    """
    ok_rows = [r for r in records if r.get("error") is None]
    total_queries = len(records)
    successful_queries = len(ok_rows)

    header = (
        "| Queries | Mean citation | Mean faithfulness | "
        "Mean completeness | Mean recall | "
        "Mean cost | Mean latency | Last run |"
    )
    sep = "|---|---|---|---|---|---|---|---|"

    if successful_queries == 0:
        # No successful runs — still emit a well-formed table so
        # the README stays skimmable even in a bad state.
        return "\n".join(
            [
                header,
                sep,
                f"| {total_queries} / 0 | - | - | - | - | - | - | "
                f"{_now_utc()} |",
            ]
        )

    cited_rows = _rows_with_citations(ok_rows)
    eligible = {f: ok_rows for f in METRIC_FIELDS}
    eligible[CITATION_FIELD] = cited_rows
    metrics = {f: _mean_or_none(rows, f) for f, rows in eligible.items()}
    cost = _mean_or_none(ok_rows, COST_FIELD)
    latency = _mean_or_none(ok_rows, LATENCY_FIELD)
    uncited = successful_queries - len(cited_rows)

    row = (
        f"| {successful_queries} / {total_queries} "
        f"| {_fmt_score(metrics['citation_accuracy'])} "
        f"| {_fmt_score(metrics['faithfulness'])} "
        f"| {_fmt_score(metrics['completeness'])} "
        f"| {_fmt_score(metrics['retrieval_recall'])} "
        f"| {_fmt_cost(cost)} "
        f"| {_fmt_latency(latency)} "
        f"| {_now_utc()} |"
    )
    lines = [
        f"_Auto-updated by the nightly eval workflow. "
        f"Run: `{run_id or 'unknown'}`._",
        "",
        header,
        sep,
        row,
    ]
    notes = ["Cost and latency are the workflow's, excluding eval-judge calls."]
    if uncited:
        notes.append(
            f"Citation accuracy is averaged over the {len(cited_rows)} of "
            f"{successful_queries} scored runs whose report contained at "
            f"least one citation; {uncited} produced none, where the metric "
            f"does not apply."
        )
    unscored = _unscored_note(eligible, metrics)
    if unscored:
        notes.append(unscored)
    lines += ["", "_" + " ".join(notes) + "_"]
    return "\n".join(lines)


def patch_readme(readme_path: Path, block: str) -> bool:
    """Rewrite the marked block. Returns True when the file changed."""
    text = readme_path.read_text(encoding="utf-8")
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError(
            f"Missing/malformed markers in {readme_path}. Expected "
            f"{START_MARKER!r} ... {END_MARKER!r}."
        )

    prefix = text[: start + len(START_MARKER)]
    suffix = text[end:]
    new_text = f"{prefix}\n{block}\n{suffix}"
    if new_text == text:
        return False
    readme_path.write_text(new_text, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mean_or_none(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [r[field] for r in rows if r.get(field) is not None]
    return statistics.fmean(values) if values else None


def _unscored_note(
    eligible: dict[str, list[dict[str, Any]]],
    metrics: dict[str, float | None],
) -> str:
    """Name any metric whose mean was taken over fewer runs than it could be.

    Since ADR 0050 a judge that fails leaves its metric `null` on the
    record instead of aborting the campaign, and `_mean_or_none` skips
    nulls. So `Mean faithfulness 0.420` can be an average of two runs
    sitting in a row headed `20 / 20` — the same shrunken-denominator
    lie the citation-accuracy exclusion above is careful to state, one
    cause further along. Published numbers state their denominator.
    """
    short = []
    for field, rows in sorted(eligible.items()):
        if metrics.get(field) is None:
            continue  # printed as `-`; nothing is being claimed
        scored = sum(1 for r in rows if r.get(field) is not None)
        if scored < len(rows):
            short.append(f"{field.replace('_', ' ')} over {scored} of {len(rows)}")
    if not short:
        return ""
    return (
        "Some runs went unscored where an eval judge failed, so these "
        "means cover fewer runs than the count above: "
        + "; ".join(short)
        + "."
    )


def _rows_with_citations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows where `citation_accuracy` is a meaningful measurement.

    A run whose report carried no `[Author, Year]` tags scores 1.0 by
    short-circuit, not by being accurate. `total_citations == 0` is the
    metric's own escape hatch for that; `None` (a pre-ADR-0050 summary
    that never recorded the count) is treated as unknown and kept.
    """
    return [r for r in rows if r.get(CITATION_COUNT_FIELD) != 0]


def _fmt_score(v: float | None) -> str:
    return f"{v:.3f}" if v is not None else "-"


def _fmt_cost(v: float | None) -> str:
    return f"${v:.4f}" if v is not None else "-"


def _fmt_latency(v: float | None) -> str:
    return f"{v:.1f}s" if v is not None else "-"


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch the README's eval-results block from a "
        "summary.jsonl file.",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        required=True,
        help="Path to summary.jsonl produced by the eval runner.",
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=Path("README.md"),
        help="README.md to patch (default: ./README.md).",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional run identifier surfaced in the block header.",
    )
    return parser.parse_args(argv)


def _load_records(summary: Path) -> list[dict[str, Any]]:
    """Read every JSON line as a record; raise on malformed input."""
    lines = summary.read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = []
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"summary.jsonl line {i} is not valid JSON: {exc}"
            ) from exc
    return records


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if not args.summary.exists():
        print(f"Error: summary file not found: {args.summary}", file=sys.stderr)
        return 2
    if not args.readme.exists():
        print(f"Error: README file not found: {args.readme}", file=sys.stderr)
        return 2

    try:
        records = _load_records(args.summary)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    block = render_block(records, run_id=args.run_id)

    try:
        changed = patch_readme(args.readme, block)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"README {'updated' if changed else 'unchanged'} "
        f"({len(records)} records, run_id={args.run_id or '-'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
