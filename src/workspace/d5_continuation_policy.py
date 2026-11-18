"""Prospective bounded continuation; no authority, provider I/O or legacy changes."""

from __future__ import annotations

from typing import Any

from src.workspace.d5_capacity_policy import DEADLINES as DEADLINES
from src.workspace.d5_capacity_policy import ROUTES as ROUTES

REVISION = "d5-behavior-continuation-v20"
PROFILE = "consolidated-machine-evaluation-v12"
LIMITS: dict[str, Any] = {
    "jobs": 10,
    "messages": 28,
    "counts": 28,
    "usd": "22",
    "new_usd": "9.20",
    "workflow_usd": "1.20",
    "probe_usd": "0.50",
    "headroom_usd": "2.00",
    "concurrency": 1,
}
PROGRAM_LIMITS = {"new_jobs": 64, "messages": 160, "counts": 200, "usd": "22", "concurrency": 1}
PERIOD_LIMITS = {"day_usd": "22", "month_usd": "22"}
PROGRAMME_EXPIRY = "2026-11-21T11:03:57+00:00"
CASE_MAP = {
    "continuation-v20-dev-learn": "campaign-dev-learn",
    "continuation-v20-dev-compare": "campaign-dev-compare",
    "continuation-v20-research-memory": "campaign-eval-research-memory",
    "continuation-v20-research-retrieval": "campaign-eval-research-retrieval",
    "continuation-v20-research-verification": "campaign-eval-research-verification",
    "continuation-v20-research-insufficient": "campaign-eval-research-insufficient",
    "continuation-v20-probe-1": "campaign-probe-1",
    "continuation-v20-probe-2": "campaign-probe-2",
    "continuation-v20-probe-3": "campaign-probe-3",
    "continuation-v20-probe-4": "campaign-probe-4",
}
PROGRESSION = {
    "revision": "metered-evaluation-content-isolation-v20",
    "development": "Both new development identities require complete current-response final checker contracts; complete negative quality is not acceptance.",
    "evaluation": "A narrowly allowlisted, independently reproduced, fully received end_turn and fully metered semantic content failure fails only that case. No invalid-first-draft repair, salvage or acceptance.",
    "global_stop": "Provider/auth/accounting/binding/capacity errors, missing or malformed judgments, truncation, new uncertainty, expiry, revocation or cancellation stop all dispatch.",
    "retries": 0,
    "maximum_quality_repairs": 1,
    "mandatory_recheck": True,
}


def enabled(settings: dict[str, Any]) -> bool:
    return settings.get("d5_campaign_revision") == REVISION


def registration(
    conn: Any, program_id: str, compiled: dict[str, Any], receipt: dict[str, Any]
) -> None:
    from src.workspace.admission import AdmissionError
    from src.workspace.d5_campaign_extension import validate_scope
    from src.workspace.d5_capacity_policy import POLICY

    if (
        receipt.get("campaign_revision") != REVISION
        or receipt.get("limits") != LIMITS
        or receipt.get("stages") != ["B", "C", "D"]
        or list(compiled) != list(CASE_MAP)
        or receipt.get("case_order") != list(CASE_MAP)
        or [sum(e["stage"] == s for e in compiled.values()) for s in ("B", "C", "D")] != [2, 4, 4]
        or any(
            not enabled(e["input"]["settings"])
            or e["input"]["settings"].get("operation_routes") != ROUTES
            or e["input"]["settings"].get("operation_deadlines") != DEADLINES
            or e["input"]["settings"].get("d5_capacity_policy") != POLICY
            for e in compiled.values()
        )
    ):
        raise AdmissionError("continuation_exact_schedule_or_routes_required")
    validate_scope(conn, program_id, receipt)


def guard_order(conn: Any, bound: dict[str, Any], case_id: str) -> None:
    from src.workspace.admission import AdmissionError
    from src.workspace.d5_campaign_policy import audit_outcomes
    from src.workspace.d5_campaign_v19_policy import require_development_contracts

    order = list(CASE_MAP)
    if (
        bound["authorization_record"].get("campaign_revision") != REVISION
        or bound["authorization_record"].get("case_order") != order
        or set(bound["cases"]) != set(order)
        or case_id not in order
    ):
        raise AdmissionError("continuation_schedule_binding_drift")
    done = audit_outcomes(conn, bound["id"])
    if any(key not in done for key in order[: order.index(case_id)]):
        raise AdmissionError("campaign_previous_case_not_terminal")
    if bound["cases"][case_id]["stage"] != "B":
        require_development_contracts(conn, bound)
