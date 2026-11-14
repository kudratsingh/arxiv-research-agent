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
    """Recognize a frozen policy; execution separately verifies its sealed binding."""
    if value == POLICY:
        return
    from src.workspace.d5_capacity_policy import DEADLINES

    if value != DEADLINES:
        raise AdmissionError("d5_operation_deadline_policy_drift")


def _policy(data: dict[str, Any]) -> dict[str, Any]:
    """Select only from the reservation's original, persisted input settings.

    Older callers supplied only the durable origin. They retain the historical
    horizon. A prospective deadline requires the whole exact capacity policy;
    a loose timer value, a missing seal or a capacity marker alone cannot opt in.
    """
    sealed = data.get("sealed_input")
    if sealed is None:
        return POLICY
    if not isinstance(sealed, dict) or not isinstance(sealed.get("settings"), dict):
        raise AdmissionError("d5_operation_deadline_policy_drift")
    settings = sealed["settings"]
    if "d5_capacity_policy" in settings:
        from src.workspace.d5_capacity_policy import DEADLINES, enabled

        try:
            capacity_enabled = enabled(settings)
        except (TypeError, ValueError) as exc:
            raise AdmissionError("d5_operation_deadline_policy_drift") from exc
        if not capacity_enabled or settings.get("operation_deadlines") != DEADLINES:
            raise AdmissionError("d5_operation_deadline_policy_drift")
        return DEADLINES
    if settings.get("operation_deadlines", POLICY) != POLICY:
        raise AdmissionError("d5_operation_deadline_capacity_binding_required")
    return POLICY


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
    policy = _policy(data)
    seconds = (origin + timedelta(seconds=policy["workflow_seconds"]) - instant).total_seconds()
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
    return min(float(_policy(data)[operation + "_seconds"]), remaining(data))
