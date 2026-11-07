"""Frozen denominators: mechanical integrity, machine opinions, human review.

Empty or unreviewed quantities remain None. Identity alone cannot pass a factual
gate, and a positive semantic label cannot excuse a bad quote/offset/version.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.workspace.assistance_contract import resolve_draft
from src.workspace.grounding import EvidenceRef, validate_claims


def factual_gate(
    *, provenance: bool | None, human_support: bool | None, human_omissions: bool | None
) -> str:
    if provenance is not True:
        return "FAIL"
    if human_support is None or human_omissions is None:
        return "UNSCORED"
    return "PASS" if human_support and human_omissions else "FAIL"


def score_case(
    case: dict[str, Any], snapshot: dict[str, Any] | None, materials: Any
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": case["id"],
        "cohort": case["cohort"],
        "pipeline": case["pipeline"],
        "completion": bool(snapshot and snapshot.get("state") == "ready"),
        "upstream_failure": case.get("upstream_failure"),
        "human_review": None,
        "retrieval": {
            "ranked": len(case["ranking"]),
            "selected_works": len(
                {r["work_id"] for r in (case.get("sealed") or {}).get("units", {}).values()}
            ),
            "duplicates": len(case["edition"]) - len(set(case["edition"])),
            "known_reference_recall": None,
            "owner_usefulness": None,
            "literature_recall": None,
        },
        "provenance": None,
        "claims": [],
        "whole_claim_support": None,
        "atomicity": None,
        "comparisons": None,
        "counterevidence": None,
        "omissions": None,
        "abstention": None,
        "factual_gate": "UNSCORED",
        "accepted_result": False,
        "workflow_usd": snapshot.get("workflow_usd") if snapshot else None,
        "checker_usd": snapshot.get("checker_usd") if snapshot else None,
        "unknown_usd": snapshot.get("unknown_usd") if snapshot else None,
        "latency_seconds": snapshot.get("latency_seconds") if snapshot else None,
        "quality_basis": "Machine checks are not independent human validation",
    }
    if not snapshot or not result["completion"]:
        return result
    workflows = [s for s in snapshot.get("steps", []) if s["stage"] in {"draft", "repair"}]
    if not workflows:
        return result
    try:
        output = {k: v for k, v in workflows[-1]["output"].items() if k != "grounding"}
        draft, claims = resolve_draft(
            output,
            {k: EvidenceRef(**v) for k, v in case["sealed"]["units"].items()},
            materials,
            purpose=case["sealed"].get("response_purpose", "research_comparison"),
        )
        report = validate_claims(claims, materials)
        result["provenance"] = (
            all(a.identity_resolved and a.scope_compatible for a in report.assessments)
            if claims
            else None
        )
        result["claims"] = [{**asdict(c), "human_support": None, "atomicity": None} for c in claims]
        result["abstention"] = draft.abstention
        result["factual_gate"] = (
            factual_gate(provenance=result["provenance"], human_support=None, human_omissions=None)
            if claims
            else "UNSCORED"
        )
        result["machine_grounding"] = snapshot.get("result", {}).get("grounding")
    except (ValueError, KeyError, TypeError):
        result["provenance"] = False
        result["factual_gate"] = "FAIL"
    return result


def markdown(report: dict[str, Any]) -> str:
    rows = [
        "# D5 quarantined benchmark",
        "",
        report["basis"],
        "",
        "| Case | Cohort | Complete | Provenance | Factual gate |",
        "|---|---|---|---|---|",
    ]
    for case in report["cases"]:
        rows.append(
            f"| {case['id']} | {case['cohort']} | {case['completion']} | {case['provenance']} | {case['factual_gate']} |"
        )
    rows += [
        "",
        "Completion is reported by cohort; the eight fresh system cases keep their denominator even when retrieval or generation fails. Development and fixed checker diagnostics are separate.",
        "",
        "Whole-claim support, comparison compatibility, counterevidence, omissions and personal usefulness require independent review. The machine checker and mechanical provenance validator do not supply those labels.",
        "",
        (
            "No review labels have been supplied. Unknown and empty denominators are unscored."
            if report.get("human_labels") is None
            else "Supplied review labels are graded separately from mechanical integrity. Inspect their provenance; synthetic labels are not human evidence."
        )
        + " No checker qualification or everyday generation is enabled.",
        "",
        "Accounting:",
        "",
        "```json",
        __import__("json").dumps(report["accounting"], indent=2),
        "```",
        "",
        "Historical 0/9 aggregate is unchanged. q01 is development; q02–q04 are preserved failures/stops, not replayed here.",
    ]
    if report.get("quality"):
        rows += [
            "",
            "Review grading (" + report["quality"]["basis"] + "):",
            "",
            "```json",
            __import__("json").dumps(report["quality"], indent=2),
            "```",
            "",
        ]
    return "\n".join(rows) + "\n"
