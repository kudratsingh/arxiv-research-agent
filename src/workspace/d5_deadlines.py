"""Sealed qualification-only deadlines. Timeouts never prove remote cancellation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.workspace.admission import AdmissionError

POLICY: dict[str, Any] = {
    "revision": "d5-operation-deadlines-v1",
    "count_seconds": 30,
    "draft_seconds": 30,
    "repair_seconds": 30,
    "check_seconds": 120,
    "recheck_seconds": 120,
    "workflow_seconds": 480,
    "origin": "durable_reservation_created_at",
}


def validate(value: Any) -> None:
    if value != POLICY:
        raise AdmissionError("d5_operation_deadline_policy_drift")


def now() -> datetime:
    """Wall-clock origin is persisted; tests advance a controlled clock."""
    return datetime.now(UTC)


def remaining(data: dict[str, Any]) -> float:
    try:
        origin = datetime.fromisoformat(data["created_at"])
        if origin.tzinfo is None:
            raise ValueError("timezone required")
    except (KeyError, TypeError, ValueError) as exc:
        raise AdmissionError("d5_durable_deadline_origin_required") from exc
    instant = now()
    if instant < origin:
        raise AdmissionError("d5_deadline_clock_precedes_reservation")
    seconds = (origin + timedelta(seconds=POLICY["workflow_seconds"]) - instant).total_seconds()
    if seconds <= 0:
        raise AdmissionError("d5_workflow_deadline_exceeded")
    return seconds


def timeout(path: str, contact: dict[str, Any], data: dict[str, Any]) -> float:
    stage = contact["stage"]
    if path == "messages/count_tokens":
        operation = "count"
    elif path == "messages" and stage in {"draft", "repair", "check"}:
        operation = "recheck" if stage == "check" and len(data["adapter"]["steps"]) == 3 else stage
    else:
        raise AdmissionError("d5_deadline_operation_required")
    return min(float(POLICY[operation + "_seconds"]), remaining(data))
