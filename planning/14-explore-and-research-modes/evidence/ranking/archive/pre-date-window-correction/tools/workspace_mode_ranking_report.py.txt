"""Reproduce a predeclared mode comparison from explicit local JSON inputs.

Run from the repository root: python -m tools.workspace_mode_ranking_report
--items public-items.json --profile profile.json --project project-data.json
--now 2026-11-05T12:00:00Z --output new-report-directory
No database, credentials, source acquisition, provider or optional model imports.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.workspace.mode_ranking import (
    MODE_POLICY_VERSION,
    known_mode_date,
    rank_mode_items,
    select_mode_edition,
)
from src.workspace.ranking import _tokens

REPORT_VERSION = "workspace-mode-ranking-development-report-v1"
ARMS = ("question_only", "profile_only", "combined_research", "chronological_diagnostic")


def _chronological_key(row: Mapping[str, Any]) -> tuple[bool, float, str]:
    date = known_mode_date(row)
    return date is None, -date.timestamp() if date is not None else 0, str(row["work_id"])


def _rank_change(position: int | None, baseline: int | None) -> int | None:
    return position - baseline if position is not None and baseline is not None else None


def _clock(value: str) -> datetime:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("timezone_required")
    return instant


def _filtered(items: Sequence[Mapping[str, Any]], filters: Mapping[str, Any], now: datetime) -> list[Mapping[str, Any]]:
    days = filters.get("days", 0)
    if type(days) is not int or not 0 <= days <= 365:
        raise ValueError("date_window_must_be_0_to_365_days")
    result = []
    for item in items:
        if filters.get("source_id") and item.get("source_id") != filters["source_id"]:
            continue
        if filters.get("access_state") and filters["access_state"] not in (item.get("available_scopes") or [item.get("access_state")]):
            continue
        if filters.get("status") and (item.get("reading") or {}).get("status", "unread") != filters["status"]:
            continue
        date = known_mode_date(item)
        if days and date is not None and date < now - timedelta(days=days):
            continue
        result.append(item)
    return result


def compare_modes(
    items: Sequence[Mapping[str, Any]], profile: Mapping[str, Any], project: Mapping[str, Any],
    *, now: datetime, filters: Mapping[str, Any] | None = None, minutes: int = 15,
) -> dict[str, Any]:
    """Research arms share the same Q/S-eligible pool; Learn remains separate.

    Source/access/status/date filters are applied once. Missing dates stay in
    the pool; chronological positions for them are explicitly unscored. All
    owner judgments stay blank, so no retrieval-quality estimate is computed.
    """
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    hard_filters = dict(filters or {})
    filtered = _filtered(items, hard_filters, now)
    learn = rank_mode_items(filtered, profile, now=now)
    research = rank_mode_items(filtered, profile, product_mode="research", project=project, now=now)
    by_id = {str(row["work_id"]): row for row in research}
    question = sorted(research, key=lambda row: (-row["mode_relevance"]["question_score"], -row["mode_relevance"]["scope_score"], str(row["work_id"])))
    declared = sorted(research, key=lambda row: (-row["mode_relevance"]["profile_keyword_score"], str(row["work_id"])))
    chronological = sorted(research, key=_chronological_key)
    arms = dict(zip(ARMS, (question, declared, research, chronological), strict=True))
    ranks = {name: {str(row["work_id"]): index + 1 for index, row in enumerate(rows)} for name, rows in arms.items()}
    known_positions = {str(row["work_id"]): index + 1 for index, row in enumerate(chronological) if known_mode_date(row) is not None}
    duplicate_ids = Counter(str(row["work_id"]) for row in items)
    rows = []
    for row in learn:
        work_id = str(row["work_id"])
        receipt = by_id[work_id]["mode_relevance"] if work_id in by_id else {
            **row["mode_relevance"], "product_mode": "research", "eligible": False,
            "question_tokens": sorted(_tokens(project["question"])),
            "scope_tokens": sorted(_tokens(project.get("scope", ""))),
            "sort_components": [0, 0, 0, row["mode_relevance"]["bounded_profile_score"], row["mode_relevance"]["freshness"]],
        }
        positions = {name: rank.get(work_id) for name, rank in ranks.items()}
        rows.append({
            "work_id": work_id, "version_id": row.get("version_id"), "title": row.get("title", ""),
            "source_id": row.get("source_id"), "published_at": row.get("published_at"),
            "updated_at": row.get("updated_at"), "announced_at": row.get("announced_at"),
            "legacy_relevance": row["relevance"], "mode_relevance": receipt, "ranks": positions,
            "rank_changes_from_question_only": {
                name: _rank_change(positions[name], positions["question_only"]) for name in ARMS
            },
            "chronological_known_date_rank": known_positions.get(work_id),
            "owner_usefulness": None, "owner_reason": None, "reference_relevance": None,
        })
    learn_selected, learn_allocation = select_mode_edition(learn, minutes, exploration=float(profile.get("exploration", .15)))
    research_selected, research_allocation = select_mode_edition(research, minutes, product_mode="research")
    known = sum(known_mode_date(row) is not None for row in research)
    full_known = sum(known_mode_date(row) is not None for row in learn)
    return {
        "report_version": REPORT_VERSION, "policy_version": MODE_POLICY_VERSION,
        "evidence_kind": "offline_development_mechanics_not_owner_usefulness_or_factual_quality",
        "clock": now.isoformat(), "project": dict(project), "hard_filters": hard_filters,
        "pool_policy": "Same hard-filtered Q/S-eligible candidates for all four Research arms; Learn uses the full hard-filtered visible pool separately.",
        "date_policy": "Aware update-before-publication dates only; invalid/missing dates stay unknown; announcement/acquisition/id dates are not substituted; unknown dates remain eligible and last in chronological diagnostic.",
        "duplicate_policy": "Ranking retains first occurrence of each work id after the shared explicit filters.",
        "counts": {"input_records": len(items), "unique_input_work_ids": len(duplicate_ids),
                   "duplicate_records": sum(n - 1 for n in duplicate_ids.values()),
                   "after_explicit_filters_records": len(filtered), "visible_after_exclusions_unique": len(learn),
                   "research_eligible_unique": len(research), "research_ineligible_unique": len(learn) - len(research)},
        "duplicate_work_ids": {key: n for key, n in sorted(duplicate_ids.items()) if n > 1},
        "denominators": {
            "research_chronology": {"known": known, "missing": len(research) - known, "total": len(research)},
            "full_pool_chronology": {"known": full_known, "missing": len(learn) - full_known, "total": len(learn)},
            "research_relevance": {"judged": 0, "unjudged": len(research), "total": len(research), "unjudged_fraction": 1.0 if research else None},
            "owner_usefulness": {"judged": 0, "unjudged": len(learn), "total": len(learn)},
        },
        "quality_metrics": {"known_reference_recall": None, "precision": None, "owner_usefulness": None,
                            "reason": "No reference labels or owner judgments were supplied; no quality denominator is invented."},
        "rankings": {name: [row["work_id"] for row in values] for name, values in arms.items()},
        "learn_ranking": [row["work_id"] for row in learn],
        "editions": {"learn": {"work_ids": [row["work_id"] for row in learn_selected], "allocation": learn_allocation},
                     "research": {"work_ids": [row["work_id"] for row in research_selected], "allocation": research_allocation}},
        "items": rows,
        "limitations": ["One development project context is not a held-out question evaluation.",
                        "Question retrieval and daily Explore usefulness are different targets.",
                        "Chronological ordering is only a limited diagnostic when publication/update dates are missing.",
                        "A lexical match, exact identity or ranking gain is not whole-claim factual support."],
    }


def markdown_report(report: Mapping[str, Any]) -> str:
    counts, dates = report["counts"], report["denominators"]["research_chronology"]
    lines = ["# Mode ranking development comparison", "", f"Policy `{report['policy_version']}` · clock `{report['clock']}`.", "",
             f"{counts['visible_after_exclusions_unique']} visible candidates; {counts['research_eligible_unique']} Q/S-eligible candidates shared by all Research arms. {counts['duplicate_records']} duplicate input records.", "",
             f"Chronology: {dates['known']}/{dates['total']} known publication/update dates; {dates['missing']} missing. Missing-date chronological positions are unscored. All owner/reference labels remain blank; recall, precision and usefulness are unscored.", "",
             report["pool_policy"], "", "| Source | Q | S | P | Question | Profile | Combined | Chronology |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report["items"]:
        title = html.escape(str(row["title"])).replace("|", "&#124;").replace("\n", " ")
        scores, ranks = row["mode_relevance"], row["ranks"]
        positions = [str(ranks[name]) if ranks[name] is not None else "unranked" for name in ARMS]
        if row["chronological_known_date_rank"] is None:
            positions[-1] = "unscored (date missing)" if scores["eligible"] else "unranked"
        lines.append(f"| {title} | {scores['question_score']} | {scores['scope_score']} | {scores['profile_keyword_score']} | " + " | ".join(positions) + " |")
    return "\n".join([*lines, "", "Learn edition: " + ", ".join(map(str, report["editions"]["learn"]["work_ids"])), "", "Research edition: " + ", ".join(map(str, report["editions"]["research"]["work_ids"])), "", *[f"- {text}" for text in report["limitations"]], ""])


def html_report(report: Mapping[str, Any]) -> str:
    # Escape the complete Markdown as a readable standalone artifact: no JS,
    # external resource or untrusted title markup is executed.
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Mode ranking development comparison</title><body><pre>' + html.escape(markdown_report(report)) + '</pre></body></html>\n'


def _load(path: Path) -> Any:
    if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("explicit_bounded_json_file_required")
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("items", "profile", "project", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--source-id", default="")
    parser.add_argument("--access-state", default="")
    parser.add_argument("--status", default="")
    parser.add_argument("--days", type=int, default=0)
    parser.add_argument("--minutes", type=int, choices=(5, 15, 45), default=15)
    args = parser.parse_args()
    items, profile, project = _load(args.items), _load(args.profile), _load(args.project)
    if isinstance(items, dict):
        items = items.get("items")
    if isinstance(profile, dict) and "data" in profile:
        profile = profile["data"]
    if not isinstance(items, list) or len(items) > 2000 or any(not isinstance(row, dict) or not isinstance(row.get("work_id"), str) or not isinstance(row.get("title"), str) for row in items):
        raise ValueError("bounded_item_list_required")
    if not isinstance(profile, dict) or not isinstance(project, dict):
        raise ValueError("profile_and_project_data_required")
    report = compare_modes(items, profile, project, now=_clock(args.now), minutes=args.minutes,
                           filters={"source_id": args.source_id, "access_state": args.access_state, "status": args.status, "days": args.days})
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = {}
    for name in ("items", "profile", "project"):
        path = getattr(args, name)
        inputs[name] = {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    sources = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
        Path(__file__), Path("src/workspace/mode_ranking.py"), Path("planning/14-explore-and-research-modes/07-ranking-policy-v1.md"))}
    report["reproduction"] = {"inputs": inputs, "source_sha256": sources,
                              "command": "python -m tools.workspace_mode_ranking_report --items ITEMS --profile PROFILE --project PROJECT --now " + args.now + " --output NEW_DIRECTORY (repeat the recorded filters/minutes)"}
    (args.output / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.output / "REPORT.md").write_text(markdown_report(report))
    (args.output / "index.html").write_text(html_report(report))
    print(json.dumps({"output": str(args.output), "counts": report["counts"], "quality_metrics": report["quality_metrics"]}))


if __name__ == "__main__":
    main()
