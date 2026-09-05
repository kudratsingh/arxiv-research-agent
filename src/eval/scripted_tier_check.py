"""Assert a scripted campaign was complete and free.

The per-PR CI job runs `src.eval.simulate_learner`'s scripted tier and
then runs this over the `summary.jsonl` it produced. Three questions, all
of which a passing exit code answers:

  - **Did the whole benchmark run?** Every scenario, no errors. A
    harness regression that makes twelve of fifteen sessions crash must
    fail the PR, not print a smaller table.
  - **Did it cost nothing?** Every cost column zero, every call count
    zero. The tier advertises zero spend and CI is given a deliberately
    invalid key; a non-zero column here means either the mock path
    stopped being taken or the accounting stopped being trustworthy,
    and both are worth a red build.
  - **Can each row say what produced it?** Every row carries a complete
    provenance block — judge model, product model, rubric versions,
    commit, dataset fingerprint, tier, seed (ADR 0070). This is not a
    quality assertion; it is the precondition for one. A row that cannot
    name its instrument cannot be compared against another run, so the
    statistics WO-A09 builds on top would be computed over rows nobody
    can attribute.

It also pins the structural-expectation baseline at campaign level: the
scripted tier's whole point is that a prompt or graph change which makes
plans dishonest or copy shaming fails *here*, before anything is funded.

**Two lanes** (WO-C1). The learning lane is the original and is
unchanged — `--lane learning` is the default and asserts exactly what it
always did, down to the flag names. `--lane research` reads a
`src.eval.simulate_research` campaign, which is the research lane's own
free per-PR tier. The lanes differ in three ways and in nothing else:
which columns exist (the research tier has no simulated learner, so no
`learner_cost_usd`), how many records a complete campaign carries, and
the `tier` string each row must claim.

The research lane adds one assertion the learning lane has no analogue
for. `scripted_llm_calls` — the number of responses the scripted surface
handed the graph — must be **positive** while `llm_calls` is zero. The
pair is what separates "the graph ran and paid nothing" from "the graph
did not run": a campaign short-circuited to twenty empty records would
otherwise pass every cost check on this page, because nothing that never
ran ever spends.

Deliberately a module under `src/eval/` rather than a shell one-liner in
the workflow: it is type-checked under `mypy --strict`, unit-tested like
the rest of the harness, and runnable by hand in the same form CI runs
it. A `jq` incantation in a YAML block is none of those.

Usage:
    python -m src.eval.scripted_tier_check outputs/eval/<run>/summary.jsonl
    python -m src.eval.scripted_tier_check --lane research <run>/summary.jsonl

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
from typing import Any, NamedTuple

from src.eval.benchmark_queries import BENCHMARK_QUERIES
from src.eval.learning_benchmark import LEARNING_SCENARIOS
from src.eval.provenance import PROVENANCE_KEY, check_provenance

#: The two tier strings a row may claim, restated here rather than
#: imported from the campaigns that write them. Importing either module
#: would pull LangGraph and both compiled graphs into a check that reads
#: a JSONL file — this module is run as the step *after* a campaign, in
#: the same job, and a gate should not take seconds to start. The
#: duplication is the same trade `runner.REPEATS_FOR_CONFIDENCE` and
#: `simulate_learner.REPEATS_FOR_CONFIDENCE` already make, and it is
#: covered the same way: `tests/test_scripted_tier_check.py` pins each
#: against the constant the campaign actually writes.
SCRIPTED_TIER: str = "scripted"
RESEARCH_SCRIPTED_TIER: str = "research-scripted"

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

#: The research tier's cost columns. It has two payers rather than
#: three: there is no simulated learner, so `learner_cost_usd` would be
#: a column nothing writes — and a check that asserts a column is zero
#: when no row carries it asserts nothing.
RESEARCH_COST_FIELDS: tuple[str, ...] = (
    "cost_usd",
    "judge_cost_usd",
    "total_cost_usd",
)

RESEARCH_CALL_FIELDS: tuple[str, ...] = (
    "llm_calls",
    "judge_llm_calls",
)


class TierProfile(NamedTuple):
    """What a lane's clean campaign looks like.

    Everything that differs between the two scripted campaigns, in one
    value, so `check_rows` stays single-copy. The learning profile
    reproduces this module's pre-WO-C1 behaviour field for field —
    that is not a coincidence, it is the constraint: the learning lane's
    gate is the only one in this repository that has ever caught a
    regression, and this refactor is allowed to add beside it and
    nothing else.

    Attributes:
        name: `--lane <name>`.
        tier: The `tier` value every row must claim.
        expected_records: How many records a complete campaign carries.
        unit: What one record is, for the messages.
        unit_plural: Plural of the same. Spelled rather than derived —
            "querys" is what a naive `+ "s"` produces, and this string
            is in the one line an operator reads on a green run.
        cost_fields: Columns that must be zero.
        call_fields: Call counts that must be zero.
        proof_of_work_field: A column that must be **positive**, or
            `None`. See the module docstring: only the research lane has
            one, because only it can tell "ran for free" from "did not
            run" that way.
    """

    name: str
    tier: str
    expected_records: int
    unit: str
    unit_plural: str
    cost_fields: tuple[str, ...]
    call_fields: tuple[str, ...]
    proof_of_work_field: str | None = None


LEARNING_PROFILE = TierProfile(
    name="learning",
    tier=SCRIPTED_TIER,
    expected_records=len(LEARNING_SCENARIOS),
    unit="session",
    unit_plural="sessions",
    cost_fields=COST_FIELDS,
    call_fields=CALL_FIELDS,
)

RESEARCH_PROFILE = TierProfile(
    name="research",
    tier=RESEARCH_SCRIPTED_TIER,
    expected_records=len(BENCHMARK_QUERIES),
    unit="query",
    unit_plural="queries",
    cost_fields=RESEARCH_COST_FIELDS,
    call_fields=RESEARCH_CALL_FIELDS,
    proof_of_work_field="scripted_llm_calls",
)

#: Selectable lanes. `learning` is first and is the default, so an
#: existing caller's command line is unchanged.
PROFILES: dict[str, TierProfile] = {
    LEARNING_PROFILE.name: LEARNING_PROFILE,
    RESEARCH_PROFILE.name: RESEARCH_PROFILE,
}


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
    rows: list[dict[str, Any]],
    *,
    expected_sessions: int,
    profile: TierProfile = LEARNING_PROFILE,
) -> list[str]:
    """Check a scripted campaign's rows. Returns problems, empty when clean.

    Args:
        rows: Parsed `summary.jsonl` rows.
        expected_sessions: How many records the campaign should carry.
        profile: Which lane wrote them. Defaults to the learning lane,
            so every existing caller — the CI step included — gets
            byte-identical behaviour without passing anything.

    Returns:
        A list of human-readable problems — all of them, not the first,
        so a broken run is diagnosable in one CI log.
    """
    problems: list[str] = []

    if len(rows) != expected_sessions:
        problems.append(
            f"expected {expected_sessions} {profile.unit}(s), found "
            f"{len(rows)} — the campaign did not run the whole benchmark"
        )

    for row in rows:
        label = str(
            row.get("record_id")
            or row.get("scenario_id")
            or row.get("query_id")
            or "<no id>"
        )

        if row.get("tier") != profile.tier:
            problems.append(
                f"{label}: tier is {row.get('tier')!r}, not {profile.tier!r}"
            )
        if row.get("error"):
            problems.append(f"{label}: errored — {row['error']}")
        if row.get("metrics_error"):
            problems.append(f"{label}: scoring failed — {row['metrics_error']}")

        for field in profile.cost_fields:
            value = _number(row, field)
            if value not in (None, 0.0):
                problems.append(
                    f"{label}: {field} is {value!r}, not zero — the scripted "
                    "tier is advertised as free"
                )
        for field in profile.call_fields:
            value = _number(row, field)
            if value not in (None, 0.0):
                problems.append(
                    f"{label}: {field} is {value!r}, not zero — something "
                    "reached a model"
                )

        # The other half of the cost assertion, and the half a cost
        # column cannot make: nothing that never ran ever spends, so a
        # campaign of empty records passes every zero above.
        if profile.proof_of_work_field is not None:
            worked = _number(row, profile.proof_of_work_field)
            if not worked:
                problems.append(
                    f"{label}: {profile.proof_of_work_field} is {worked!r} — "
                    "the graph made no scripted call, so this row is a record "
                    "of nothing having run rather than of a free run"
                )

        failures = row.get("expectation_failures")
        if isinstance(failures, int) and failures:
            problems.append(
                f"{label}: {failures} unmet structural expectation(s). The "
                "scripted tier exists to catch this before a campaign is "
                "funded; read the run's summary.md for which."
            )

        # Additive to everything above, never a replacement (ADR 0070's
        # trap: this is the only gate in the repository that has ever
        # caught anything, so it only ever grows).
        problems += [
            f"{label}: {reason}" for reason in check_provenance(row.get(PROVENANCE_KEY))
        ]

    spend = total_spend(rows)
    if round(spend, 4) != 0.0:
        problems.append(f"campaign spent ${spend:.4f}, expected $0.0000")

    return problems


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Assert a scripted campaign ran the whole benchmark for nothing."
        )
    )
    parser.add_argument(
        "summary", type=Path, help="Path to the campaign's summary.jsonl"
    )
    parser.add_argument(
        "--lane",
        choices=sorted(PROFILES),
        default=LEARNING_PROFILE.name,
        help=(
            "Which scripted campaign wrote this summary. 'learning' "
            "(default) reads src/eval/simulate_learner.py's scripted tier; "
            "'research' reads src/eval/simulate_research.py's."
        ),
    )
    parser.add_argument(
        "--expected-sessions",
        type=int,
        default=None,
        help=(
            "Records the campaign should carry. Default: the selected "
            f"lane's benchmark size ({len(LEARNING_SCENARIOS)} scenarios for "
            f"learning, {len(BENCHMARK_QUERIES)} queries for research)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the checks over a summary file. Returns a process exit code."""
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    profile = PROFILES[args.lane]
    expected = (
        profile.expected_records
        if args.expected_sessions is None
        else args.expected_sessions
    )

    try:
        rows = load_rows(args.summary)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    problems = check_rows(rows, expected_sessions=expected, profile=profile)
    if problems:
        print("Scripted-tier check FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(
        f"Scripted tier OK: {len(rows)}/{expected} {profile.unit_plural}, "
        f"${total_spend(rows):.4f} spent, 0 unmet expectations, "
        f"{len(rows)} attributable row(s)."
    )
    return 0


__all__ = [
    "CALL_FIELDS",
    "COST_FIELDS",
    "RESEARCH_SCRIPTED_TIER",
    "SCRIPTED_TIER",
    "LEARNING_PROFILE",
    "PROFILES",
    "RESEARCH_CALL_FIELDS",
    "RESEARCH_COST_FIELDS",
    "RESEARCH_PROFILE",
    "TierProfile",
    "check_rows",
    "load_rows",
    "main",
    "total_spend",
]


if __name__ == "__main__":
    sys.exit(main())
