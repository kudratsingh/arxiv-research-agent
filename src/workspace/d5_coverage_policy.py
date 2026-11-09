"""Narrow A/B policy for request-coverage development, never a grant writer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.workspace.admission import AdmissionError, _digest
from src.workspace.qualification_budget import census

PROFILE = "request-coverage-development-v1"
LIMITS: dict[str, Any] = {
    "jobs": 3,
    "messages": 12,
    "counts": 15,
    "usd": "10",
    "concurrency": 1,
    "workflow_usd": "0.45",
    "probe_usd": "0",
    "headroom_usd": "1.00",
    "new_usd": "1.35",
    "stages": {
        "A": {"jobs": 0, "messages": 0, "counts": 3},
        "B": {"jobs": 3, "messages": 12, "counts": 12},
    },
}
PROGRAM_LIMITS = {"new_jobs": 34, "messages": 80, "counts": 99, "usd": "10", "concurrency": 1}


def programme(conn: Any, program_id: str) -> dict[str, Any]:
    """Verify the existing original authority and its append-only capacity receipt."""
    from src.workspace.programme_amendments import effective_limits

    original = conn.execute(
        "SELECT authorization_digest FROM workspace_evaluation_programs WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    capacity = conn.execute(
        "SELECT record,authorization_digest,proposal_digest,expires_at FROM workspace_programme_capacity_amendments WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    if not original or not capacity or _digest(capacity[0]) != capacity[1]:
        raise AdmissionError("coverage_active_programme_required")
    limits = effective_limits(conn, program_id, required_proposal_digest=capacity[2])
    if limits != PROGRAM_LIMITS or datetime.now(UTC) >= capacity[3]:
        raise AdmissionError("coverage_programme_limits_or_expiry")
    return {
        "program_id": program_id,
        "original_authorization_digest": original[0],
        "capacity_authorization_digest": capacity[1],
        "capacity_proposal_digest": capacity[2],
        "limits": limits,
        "expires_at": capacity[3].isoformat(),
    }


def validate_programme(
    conn: Any, program_id: str, expected: Any, expiry: datetime, *, already_guarded: bool = False
) -> None:
    if already_guarded:
        # guard_scope has just run guard_trial with the exact required capacity
        # digest. Reuse its full chain/history audit; do not perform that expensive
        # recursive audit twice per contact. Recheck the pinned metadata/expiry.
        original = conn.execute(
            "SELECT authorization_digest FROM workspace_evaluation_programs WHERE program_id=%s",
            (program_id,),
        ).fetchone()
        row = conn.execute(
            "SELECT record,authorization_digest,proposal_digest,expires_at FROM workspace_programme_capacity_amendments WHERE program_id=%s",
            (program_id,),
        ).fetchone()
        if not original or not row or _digest(row[0]) != row[1] or datetime.now(UTC) >= row[3]:
            raise AdmissionError("coverage_active_programme_required")
        actual = {
            "program_id": program_id,
            "original_authorization_digest": original[0],
            "capacity_authorization_digest": row[1],
            "capacity_proposal_digest": row[2],
            "limits": row[0]["amendment"]["amended_limits"],
            "expires_at": row[3].isoformat(),
        }
    else:
        actual = programme(conn, program_id)
    if (
        actual != expected
        or actual["limits"] != PROGRAM_LIMITS
        or expiry > datetime.fromisoformat(actual["expires_at"])
    ):
        raise AdmissionError("coverage_programme_binding_or_expiry_drift")


def registration(
    conn: Any, program_id: str, compiled: dict[str, Any], receipt: dict[str, Any]
) -> None:
    bindings = [e["input"]["settings"].get("d5_programme_binding") for e in compiled.values()]
    if not bindings or any(b != bindings[0] for b in bindings):
        raise AdmissionError("coverage_programme_binding_drift")
    if receipt["stages"] != ["A"]:
        raise AdmissionError("coverage_parent_A_only")
    start, expiry = (
        datetime.fromisoformat(receipt["approved_at"]),
        datetime.fromisoformat(receipt["expires_at"]),
    )
    if expiry > start + timedelta(days=1):
        raise AdmissionError("coverage_approval_max_24_hours")
    if len(compiled) != 6 or sorted(e["stage"] for e in compiled.values()) != ["A"] * 3 + ["B"] * 3:
        raise AdmissionError("coverage_exact_development_schedule_required")
    validate_programme(conn, program_id, bindings[0], expiry)


def stages(limits: dict[str, Any], requested: list[str]) -> None:
    if limits == LIMITS and requested != ["B"]:
        raise AdmissionError("coverage_separate_B_only_grant_required")


def measurements(conn: Any, bound: dict[str, Any]) -> None:
    for key, entry in bound["cases"].items():
        if entry["stage"] != "A":
            continue
        row = conn.execute(
            "SELECT j.state,j.data->'result',r.input_digest,j.data->'adapter'->'contacts',j.data->'sealed_input' FROM workspace_d5_case_runs r JOIN workspace_generation_jobs j ON j.id=r.job_id WHERE r.scope_id=%s AND r.case_id=%s",
            (bound["id"], key),
        ).fetchone()
        tokens = (row[1] or {}).get("input_tokens") if row else None
        contacts = (row[3] or []) if row else []
        if (
            not row
            or row[0] != "ready"
            or row[2] != entry["input_digest"]
            or type(tokens) is not int
            or tokens > 16000
            or tokens < 1
            or len(contacts) != 1
            or contacts[0].get("endpoint") != "messages/count_tokens"
            or contacts[0].get("state") != "completed"
        ):
            raise AdmissionError("coverage_three_bound_measurements_required")
        sealed_input = row[4]
        settings = sealed_input["settings"]
        receipt = contacts[0]
        body = receipt.get("body", {})
        # This sealed Sonnet thinking profile has no temperature field. Counts
        # remove only max_tokens; reconstructing the full body proves exact
        # model/settings/schema/context equality to the approved initial wire.
        generation = {**body, "max_tokens": settings["output_tokens"]}
        body_digest = _digest(body)
        if (
            _digest(sealed_input) != entry["input_digest"]
            or {"max_tokens", "temperature"} & body.keys()
            or body.get("model") != sealed_input["model_id"]
            or _digest(generation) != settings["d5_request"]["candidate_initial_wire_digest"]
            or receipt.get("generation_request_digest") != _digest(generation)
            or receipt.get("request_digest") != body_digest
            or row[1].get("count_request_digest") != body_digest
            or receipt.get("response", {}).get("input_tokens") != tokens
        ):
            raise AdmissionError("coverage_measurement_receipt_binding_drift")


def guard(
    conn: Any,
    bound: dict[str, Any],
    owner: str,
    settings: dict[str, Any],
    *,
    amount: Decimal | None,
    endpoint: str | None,
) -> None:
    validate_programme(
        conn,
        bound["program_id"],
        settings.get("d5_programme_binding"),
        datetime.fromisoformat(bound["authorization_record"]["expires_at"]),
        already_guarded=True,
    )
    if (
        settings.get("program_amendment_proposal_digest")
        != settings["d5_programme_binding"]["capacity_proposal_digest"]
    ):
        raise AdmissionError("coverage_programme_binding_drift")
    stage = bound["case"]["stage"]
    if stage not in LIMITS["stages"] or set(bound["stage_authorizations"]) - {"A", "B"}:
        raise AdmissionError("coverage_A_B_only")
    if stage == "B":
        measurements(conn, bound)
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT job_id FROM workspace_d5_case_runs WHERE scope_id=%s AND case_id=ANY(%s)",
            (bound["id"], [k for k, v in bound["cases"].items() if v["stage"] == stage]),
        )
    ]
    history = census(conn, owner, members=bound["members"], job_ids=ids)
    maximum = LIMITS["stages"][stage]
    if (
        history["messages"] + (endpoint == "messages") > maximum["messages"]
        or history["counts"] + (endpoint == "messages/count_tokens") > maximum["counts"]
    ):
        raise AdmissionError("coverage_stage_contact_cap_exceeded")
    if amount is not None:
        calls = 1 if stage == "A" else 4
        if (
            history["messages"] + (0 if stage == "A" else calls) > maximum["messages"]
            or history["counts"] + calls > maximum["counts"]
        ):
            raise AdmissionError("coverage_complete_stage_capacity_required")
        if stage == "B" and len(ids) >= maximum["jobs"]:
            raise AdmissionError("coverage_stage_job_cap_exceeded")
        if sum(
            Decimal(history[k]) for k in ("known_usd", "pending_usd", "unknown_usd")
        ) + amount > Decimal(LIMITS["new_usd"]):
            raise AdmissionError("coverage_new_spend_cap_exceeded")
