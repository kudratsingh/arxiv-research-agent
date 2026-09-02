"""Assert a scripted learner-simulation campaign was complete and free.

The per-PR CI job runs `src.eval.simulate_learner`'s scripted tier and
then runs this over the `summary.jsonl` it produced. Two questions, both
of which a passing exit code answers:

  - **Did the whole benchmark run?** Every scenario, no errors. A
    harness regression that makes twelve of fifteen sessions crash must
    fail the PR, not print a smaller table.
  - **Did it cost nothing?** Every cost column zero, every call count
    zero. The tier advertises zero spend and CI is given a deliberately
    invalid key; a non-zero column here means either the mock path
    stopped being taken or the accounting stopped being trustworthy,
    and both are worth a red build.

It also pins the structural-expectation baseline at campaign level: the
scripted tier's whole point is that a prompt or graph change which makes
plans dishonest or copy shaming fails *here*, before anything is funded.

Deliberately a module under `src/eval/` rather than a shell one-liner in
the workflow: it is type-checked under `mypy --strict`, unit-tested like
the rest of the harness, and runnable by hand in the same form CI runs
it. A `jq` incantation in a YAML block is none of those.

Usage:
    python -m src.eval.scripted_tier_check outputs/eval/<run>/summary.jsonl

Exit codes:
    0 — complete, free, and no unmet expectations
    1 — at least one check failed (the reasons are printed)
    2 — the summary file is missing or unreadable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.eval.learning_benchmark import LEARNING_SCENARIOS

#: Cost columns that must all be zero. `cost_usd` is the session graph's
#: own spend, the other two are the harness's (ADR 0050's split, one
#: column wider for this campaign) — in the scripted tier nobody pays.
COST_FIELDS: tuple[str, ...] = (
    "cost_usd",
    "learner_cost_usd",
    "judge_cost_usd",
    "total_cost_usd",
)

#: Call-count columns that must all be zero. A dollar figure can round
#: to zero; a call count cannot, so these are the stricter check.
CALL_FIELDS: tuple[str, ...] = (
    "llm_calls",
    "learner_llm_calls",
    "judge_llm_calls",
)


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Read a `summary.jsonl` into a list of rows.

    Args:
        path: The summary file.

    Returns:
        One dict per non-blank line, in file order.

    Raises:
        ValueError: The file is missing, or a line is not a JSON object.
    """
    if not path.is_file():
        raise ValueError(f"{path}: summary file not found")
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: invalid JSONL on line {line_no}: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{path}: line {line_no} is not a JSON object")
        rows.append(parsed)
    return rows


def _number(row: dict[str, Any], field: str) -> float | None:
    """A row's numeric field, or `None` when absent or unscored."""
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def total_spend(rows: list[dict[str, Any]]) -> float:
    """Sum of every row's `total_cost_usd`, treating nulls as zero."""
    return sum(_number(row, "total_cost_usd") or 0.0 for row in rows)


def check_rows(
    rows: list[dict[str, Any]], *, expected_sessions: int
) -> list[str]:
    """Check a scripted campaign's rows. Returns problems, empty when clean.

    Args:
        rows: Parsed `summary.jsonl` rows.
        expected_sessions: How many sessions the campaign should carry.

    Returns:
        A list of human-readable problems — all of them, not the first,
        so a broken run is diagnosable in one CI log.
    """
    problems: list[str] = []

    if len(rows) != expected_sessions:
        problems.append(
            f"expected {expected_sessions} session(s), found {len(rows)} — "
            "the campaign did not run the whole benchmark"
        )

    for row in rows:
        label = str(row.get("record_id") or row.get("scenario_id") or "<no id>")

        if row.get("tier") != "scripted":
            problems.append(f"{label}: tier is {row.get('tier')!r}, not 'scripted'")
        if row.get("error"):
            problems.append(f"{label}: errored — {row['error']}")
        if row.get("metrics_error"):
            problems.append(f"{label}: scoring failed — {row['metrics_error']}")

        for field in COST_FIELDS:
            value = _number(row, field)
            if value not in (None, 0.0):
                problems.append(
                    f"{label}: {field} is {value!r}, not zero — the scripted "
                    "tier is advertised as free"
                )
        for field in CALL_FIELDS:
            value = _number(row, field)
            if value not in (None, 0.0):
                problems.append(
                    f"{label}: {field} is {value!r}, not zero — something "
                    "reached a model"
                )

        failures = row.get("expectation_failures")
        if isinstance(failures, int) and failures:
            problems.append(
                f"{label}: {failures} unmet structural expectation(s). The "
                "scripted tier exists to catch this before a campaign is "
                "funded; read the run's summary.md for which."
            )

    spend = total_spend(rows)
    if round(spend, 4) != 0.0:
        problems.append(f"campaign spent ${spend:.4f}, expected $0.0000")

    return problems


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Assert a scripted learner-simulation campaign ran the whole "
            "benchmark for nothing."
        )
    )
    parser.add_argument(
        "summary", type=Path, help="Path to the campaign's summary.jsonl"
    )
    parser.add_argument(
        "--expected-sessions",
        type=int,
        default=len(LEARNING_SCENARIOS),
        help=(
            "Sessions the campaign should carry. Default: the benchmark's "
            f"scenario count ({len(LEARNING_SCENARIOS)})."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the checks over a summary file. Returns a process exit code."""
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    try:
        rows = load_rows(args.summary)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    problems = check_rows(rows, expected_sessions=args.expected_sessions)
    if problems:
        print("Scripted-tier check FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(
        f"Scripted tier OK: {len(rows)}/{args.expected_sessions} sessions, "
        f"${total_spend(rows):.4f} spent, 0 unmet expectations."
    )
    return 0


__all__ = [
    "CALL_FIELDS",
    "COST_FIELDS",
    "check_rows",
    "load_rows",
    "main",
    "total_spend",
]


if __name__ == "__main__":
    sys.exit(main())
