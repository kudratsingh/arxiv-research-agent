"""One externally approved, sequential machine-only campaign. No approval writer."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb
from pydantic import ValidationError

from src.workspace.admission import AdmissionError, _digest

PROFILE = "consolidated-machine-evaluation-v12"
LIMITS: dict[str, Any] = {
    "jobs": 14,
    "messages": 44,
    "counts": 44,
    "usd": "10",
    "concurrency": 1,
    "workflow_usd": "0.45",
    "probe_usd": "0.15",
    "headroom_usd": "1.00",
    "new_usd": "5.10",
}
PROGRAM_LIMITS = {"new_jobs": 47, "messages": 109, "counts": 134, "usd": "10", "concurrency": 1}
CONTENT_ERRORS = frozenset(
    {
        "structured_text_required",
        "structured_object_required",
        "model_drift_or_incomplete_output",
        "d5_request_or_claim_quality_unresolved",
        "d5_whole_claim_support_unresolved",
        "d5_unscored_factual_prose",
        "d5_draft_scope_incompatible",
        "incomplete_check_batch",
        "blank_claim_or_duplicate_handle",
        "claim_or_comparison_basis_mismatch",
        "claim_or_section_reference_mismatch",
        "comparison_requires_separate_evidence_claims",
        "comparison_basis_without_comparison",
        "claims_or_abstention_required",
        "question_premise_requires_scored_claim",
        "assistance_response_too_large",
        "duplicate_claim_id",
        "orphaned_claim_outside_request",
        "duplicate_claim_part",
        "claim_part_reference_missing",
        "request_part_claim_binding_mismatch",
        "source_notes_cannot_answer_comparison",
        "prioritize_requested_parts_before_lower_priority_context",
        "unselected_evidence_handle",
        "comparison_requires_two_separately_cited_sources",
        "d5_checker_claim_binding_drift",
        "checker_prose_location_mismatch",
        "checker_prose_scalar_required",
        "checker_prose_location_blank",
        "claim_quality_binding_mismatch",
        "coverage_review_binding_mismatch",
        "d5_duplicate_json_key",
        "d5_nonfinite_json",
        "d5_compact_output_exceeded",
        "d5_structured_verdict_required",
        "d5_reasoning_block_invalid",
    }
)


def enabled(settings: dict[str, Any]) -> bool:
    return settings.get("d5_scope_profile") == PROFILE


def limits_for(settings: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_campaign_v14_policy import LIMITS as V14_LIMITS
    from src.workspace.d5_campaign_v14_policy import enabled as v14
    from src.workspace.d5_campaign_v15_policy import LIMITS as V15_LIMITS
    from src.workspace.d5_campaign_v15_policy import enabled as v15

    return V15_LIMITS if v15(settings) else V14_LIMITS if v14(settings) else LIMITS


def job_binding(conn: Any, job_id: str) -> tuple[str, dict[str, Any], str]:
    row = conn.execute(
        "SELECT j.state,j.data,r.amount::text,r.workflow::text,r.judge::text,r.unknown::text "
        "FROM workspace_generation_jobs j JOIN workspace_spend_reservations r ON r.job_id=j.id WHERE j.id=%s",
        (job_id,),
    ).fetchone()
    if not row:
        raise AdmissionError("campaign_job_receipt_missing")
    return row[0], row[1], _digest(list(row))


def audit_outcomes(conn: Any, scope_id: str) -> dict[str, Any]:
    found = {}
    for case, job, binding, record, digest in conn.execute(
        "SELECT case_id,job_id,job_digest,record,record_digest FROM workspace_d5_campaign_outcomes WHERE scope_id=%s ORDER BY case_id",
        (scope_id,),
    ):
        if _digest(record) != digest or job_binding(conn, job)[2] != binding:
            raise AdmissionError("campaign_accounting_or_outcome_corruption")
        found[case] = record
    return found


def guard_order(conn: Any, bound: dict[str, Any], case_id: str) -> None:
    order = bound["authorization_record"].get("case_order", [])
    if set(order) != set(bound["cases"]) or len(order) != len(bound["cases"]):
        raise AdmissionError("campaign_schedule_binding_drift")
    done = audit_outcomes(conn, bound["id"])
    if case_id not in order or any(k not in done for k in order[: order.index(case_id)]):
        raise AdmissionError("campaign_previous_case_not_terminal")
    from src.workspace.d5_campaign_v14_policy import LIMITS as V14_LIMITS
    from src.workspace.d5_campaign_v14_policy import require_development_contracts
    from src.workspace.d5_campaign_v15_policy import LIMITS as V15_LIMITS
    from src.workspace.d5_campaign_v15_policy import (
        require_development_contracts as require_capacity_contracts,
    )

    if bound["limits"] == V15_LIMITS and bound["cases"][case_id]["stage"] != "B":
        require_capacity_contracts(conn, bound)
    if bound["limits"] == V14_LIMITS and bound["cases"][case_id]["stage"] != "B":
        require_development_contracts(conn, bound)


def registration(
    conn: Any, program_id: str, compiled: dict[str, Any], receipt: dict[str, Any]
) -> None:
    from src.workspace.d5_campaign_extension import validate_scope
    from src.workspace.d5_campaign_v14_policy import LIMITS as V14_LIMITS
    from src.workspace.d5_campaign_v14_policy import ROUTES as V14_ROUTES
    from src.workspace.d5_campaign_v15_policy import LIMITS as V15_LIMITS
    from src.workspace.d5_capacity_policy import DEADLINES as V15_DEADLINES
    from src.workspace.d5_capacity_policy import POLICY as CAPACITY_POLICY
    from src.workspace.d5_capacity_policy import ROUTES as V15_ROUTES
    from src.workspace.d5_deadlines import POLICY
    from src.workspace.d5_operations import ROUTES

    capacity = receipt["limits"] == V15_LIMITS
    prospective = receipt["limits"] == V14_LIMITS
    expected_limits = V15_LIMITS if capacity else V14_LIMITS if prospective else LIMITS
    expected_routes = V15_ROUTES if capacity else V14_ROUTES if prospective else ROUTES
    expected_deadlines = V15_DEADLINES if capacity else POLICY
    if (
        receipt["limits"] != expected_limits
        or receipt["stages"] != ["B", "C", "D"]
        or len(compiled) != 14
        or [sum(e["stage"] == s for e in compiled.values()) for s in ("B", "C", "D")] != [2, 8, 4]
        or receipt.get("case_order") != list(compiled)
        or any(
            not enabled(e["input"]["settings"])
            or e["input"]["settings"].get("operation_deadlines") != expected_deadlines
            or capacity and e["input"]["settings"].get("d5_capacity_policy") != CAPACITY_POLICY
            or e["input"]["settings"].get("operation_routes") != expected_routes
            for e in compiled.values()
        )
    ):
        raise AdmissionError("campaign_exact_schedule_required")
    validate_scope(conn, program_id, receipt)


def guard(
    conn: Any,
    bound: dict[str, Any],
    owner: str,
    settings: dict[str, Any],
    *,
    amount: Decimal | None,
    endpoint: str | None,
) -> None:
    from src.workspace.qualification_budget import census

    limits = limits_for(settings)
    if bound["limits"] != limits or bound["stages"] != ["B", "C", "D"]:
        raise AdmissionError("campaign_scope_binding_drift")
    guard_order(conn, {**bound, "id": settings["d5_scope_id"]}, settings["d5_case_id"])
    history = census(conn, owner, members=bound["members"])
    # Pending already includes unknown; do not add it a second time.
    if Decimal(history["known_usd"]) + Decimal(history["pending_usd"]) + (amount or 0) > Decimal(
        limits["new_usd"]
    ):
        raise AdmissionError("campaign_new_spend_cap_exceeded")
    if amount is not None:
        done = audit_outcomes(conn, bound["id"])
        remaining = sum(
            (
                Decimal(
                    limits["probe_usd"] if e["operation"] == "probe" else limits["workflow_usd"]
                )
                for k, e in bound["cases"].items()
                if k not in done
            ),
            Decimal(0),
        )
        members = [
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
                (bound["program_id"],),
            )
        ]
        programme = census(conn, owner, members=members)
        if Decimal(programme["known_usd"]) + Decimal(
            programme["pending_usd"]
        ) + remaining + Decimal(limits["headroom_usd"]) > Decimal(limits["usd"]):
            raise AdmissionError("campaign_remaining_batch_requires_consolidated_budget_adjustment")


def preserve_content_rejection(
    store: Any, owner: str, inputs: Any, job_id: str, error: BaseException | None
) -> bool:
    """Only fully metered output failures continue. Binding/accounting faults stop."""
    if (
        not enabled(inputs.settings)
        or error is None
        or not (
            isinstance(error, (ValidationError, json.JSONDecodeError))
            or str(error) in CONTENT_ERRORS
        )
    ):
        return False
    with store.pool.connection() as conn:
        from src.workspace.d5_campaign_extension import active

        try:
            policy = conn.execute(
                "SELECT data FROM workspace_budget_policies WHERE owner=%s", (owner,)
            ).fetchone()
            if not policy or not active(
                conn, policy[0]["program_id"], inputs.settings["program_amendment_proposal_digest"]
            ):
                return False
        except AdmissionError:
            return False
        state, data, _ = job_binding(conn, job_id)
        reservation = conn.execute(
            "SELECT unknown FROM workspace_spend_reservations WHERE job_id=%s", (job_id,)
        ).fetchone()
        contacts = data.get("adapter", {}).get("contacts", [])
        if (
            state != "failed"
            or not reservation
            or reservation[0]
            or not contacts
            or any(c.get("state") != "completed" for c in contacts)
        ):
            return False
        if not any(c["endpoint"] == "messages" for c in contacts):
            return False
        # Model substitution and invalid usage never become a content-only failure.
        if any(
            c["response"].get("model") != c["body"].get("model")
            for c in contacts
            if c["endpoint"] == "messages"
        ):
            return False
        if not data.get("accounting_audits"):
            return False
        data["campaign_content_rejection"] = {
            "input_digest": _digest(inputs.snapshot()),
            "contacts_digest": _digest(contacts),
            "error_class": type(error).__name__,
            "error": str(error)[:1200],
            "accepted": False,
        }
        from src.workspace.d5_capacity_policy import enabled as capacity_enabled
        if capacity_enabled(dict(inputs.settings)):
            data["campaign_content_rejection"]["error"] = str(error)
            codes = []
            if isinstance(error, ValidationError):
                codes = [str(item.get("ctx", {}).get("error")) for item in error.errors() if item.get("ctx", {}).get("error") is not None]
            data["campaign_content_rejection"]["error_codes"] = codes
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s AND owner=%s",
            (Jsonb(data), job_id, owner),
        )
    return True


def record_outcome(
    store: Any, scope_id: str, case_id: str, job_id: str, expected_input: str
) -> dict[str, Any]:
    from src.workspace.admission import GenerationAdmission

    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT data FROM workspace_d5_scopes WHERE scope_id=%s", (scope_id,)
        ).fetchone()
        if not row or case_id not in row[0]["cases"]:
            raise AdmissionError("campaign_case_not_authorized")
        entry = row[0]["cases"][case_id]
        GenerationAdmission(store)._lock(conn, entry["owner"])
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("d5:" + scope_id,))
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ("evaluation:" + row[0]["program_id"],),
        )
        guard_order(conn, {**row[0], "id": scope_id}, case_id)
        state, data, binding = job_binding(conn, job_id)
        run = conn.execute(
            "SELECT input_digest,job_id FROM workspace_d5_case_runs WHERE scope_id=%s AND case_id=%s",
            (scope_id, case_id),
        ).fetchone()
        if (
            run != (expected_input, job_id)
            or expected_input != entry["input_digest"]
            or _digest(data["sealed_input"]) != expected_input
        ):
            raise AdmissionError("campaign_terminal_binding_drift")
        if (
            state not in {"ready", "failed"}
            or state == "failed"
            and not data.get("campaign_content_rejection")
        ):
            raise AdmissionError("campaign_terminal_content_receipt_required")
        record = {
            "case_id": case_id,
            "job_id": job_id,
            "state": state,
            "input_digest": expected_input,
            "mechanical_complete": state == "ready",
            "pipeline_contract_accepted": state == "ready",
            "quality_acceptance": None,  # Requires the separate frozen scorecard.
            "content_rejection": data.get("campaign_content_rejection"),
        }
        old = conn.execute(
            "SELECT record FROM workspace_d5_campaign_outcomes WHERE scope_id=%s AND case_id=%s",
            (scope_id, case_id),
        ).fetchone()
        if old:
            if old[0] != record:
                raise AdmissionError("campaign_outcome_immutable")
            return dict(old[0])
        conn.execute(
            "INSERT INTO workspace_d5_campaign_outcomes VALUES(%s,%s,%s,%s,%s,%s,clock_timestamp())",
            (scope_id, case_id, job_id, binding, Jsonb(record), _digest(record)),
        )
        return record
