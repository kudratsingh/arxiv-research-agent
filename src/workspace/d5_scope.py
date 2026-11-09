"""D5's stricter, external-authorization scope over the cumulative ledger.

No approval writer lives here. Shared scope and programme locks cover both
principals and all workflow/checker/count helpers. Offline fixture databases can
never dispatch a provider contact, even if a caller supplies a credential.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.workspace.admission import AdmissionError, GenerationAdmission, _digest
from src.workspace.qualification_budget import census
from src.workspace.qualification_budget import guard as guard_trial

LIMITS: dict[str, Any] = {
    "jobs": 14,
    "messages": 44,
    "counts": 48,
    "usd": "10",
    "concurrency": 1,
    "workflow_usd": "0.40",
    "probe_usd": "0.08",
    "headroom_usd": "1.00",
}


def limits_for(settings: dict[str, Any]) -> dict[str, Any]:
    if settings.get("d5_scope_profile"):
        from src.workspace.d5_coverage_policy import profile_limits

        return profile_limits(settings["d5_scope_profile"])
    if settings.get("operation_routes"):
        from src.workspace.d5_operations import OPUS_LIMITS, validate

        validate(settings["operation_routes"])
        return OPUS_LIMITS
    return LIMITS


def valid_limits(value: Any) -> bool:
    from src.workspace.d5_coverage_policy import PROFILES
    from src.workspace.d5_operations import OPUS_LIMITS

    return value in (LIMITS, OPUS_LIMITS, *PROFILES.values())


def stage_authorizations(
    conn: Any,
    scope_id: str,
    data: dict[str, Any],
    parent_digest: str,
    parent_expiry: datetime,
    now: datetime,
) -> dict[str, str]:
    """Read/verify append-only external grants; no permission writer here."""
    allowed = {stage: parent_digest for stage in data["stages"]}
    for digest, receipt, expiry in conn.execute(
        "SELECT authorization_digest,record,expires_at FROM workspace_d5_stage_authorizations WHERE scope_id=%s ORDER BY grant_id",
        (scope_id,),
    ):
        if (
            _digest(receipt) != digest
            or receipt.get("approved") is not True
            or not receipt.get("approved_by")
            or receipt.get("scope_id") != scope_id
            or receipt.get("parent_authorization_digest") != parent_digest
            or receipt.get("packet_digest") != data["authorization_record"]["packet_digest"]
            or receipt.get("limits") != data["limits"]
            or receipt.get("members") != data["members"]
            or receipt.get("case_bindings_digest") != _digest(data["cases"])
            or receipt.get("transport_mode") != data["authorization_record"]["transport_mode"]
            or receipt.get("authorization_kind")
            != data["authorization_record"]["authorization_kind"]
            or not isinstance(receipt.get("stages"), list)
            or not receipt["stages"]
            or set(receipt["stages"]) - {"B", "C", "D"}
            or datetime.fromisoformat(receipt["expires_at"]) != expiry
            or expiry > parent_expiry
        ):
            raise AdmissionError("d5_stage_authorization_binding_drift")
        if now < expiry:
            for stage in receipt["stages"]:
                if stage in allowed:
                    raise AdmissionError("d5_overlapping_stage_authorizations")
                allowed[stage] = digest
    return allowed


def require_development(conn: Any, scope_id: str, cases: dict[str, Any]) -> None:
    """Machine development success is a prerequisite, never human qualification."""
    required = {key: value for key, value in cases.items() if value["stage"] == "B"}
    if not required:
        raise AdmissionError("d5_successful_development_evidence_required")
    for key, entry in required.items():
        row = conn.execute(
            "SELECT j.state,j.data->'result',r.input_digest FROM workspace_d5_case_runs r JOIN workspace_generation_jobs j ON j.id=r.job_id WHERE r.scope_id=%s AND r.case_id=%s",
            (scope_id, key),
        ).fetchone()
        assessments = (row[1] or {}).get("grounding", {}).get("assessments", []) if row else []
        if (
            not row
            or row[0] != "ready"
            or row[2] != entry["input_digest"]
            or not assessments
            or any(
                a.get("decision") != "supported"
                or a.get("identity_resolved") is not True
                or a.get("scope_compatible") is not True
                for a in assessments
            )
        ):
            raise AdmissionError("d5_successful_development_evidence_required")


def scope(
    conn: Any, owner: str, inputs: dict[str, Any], policy: dict[str, Any], now: datetime
) -> dict[str, Any]:
    settings = inputs["settings"]
    scope_id = settings.get("d5_scope_id")
    if not isinstance(scope_id, str) or not scope_id.startswith("d5-"):
        raise AdmissionError("d5_external_scope_required")
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("d5:" + scope_id,))
    row = conn.execute(
        "SELECT packet_digest,authorization_digest,data,state,expires_at FROM workspace_d5_scopes WHERE scope_id=%s FOR UPDATE",
        (scope_id,),
    ).fetchone()
    if (
        not row
        or row[3] != "active"
        or now >= row[4]
        or owner not in row[2].get("members", [])
        or row[0] != settings.get("d5_packet_digest")
        or row[1] != policy.get("d5_authorization_digest")
        or not valid_limits(row[2].get("limits"))
        or (
            settings.get("d5_operation") != "measurement"
            and row[2].get("limits") != limits_for(settings)
        )
        or policy.get("d5_scope_id") != scope_id
    ):
        raise AdmissionError("d5_scope_missing_revoked_expired_or_drifted")
    data = dict(row[2])
    if settings.get("program_amendment_proposal_digest") != data.get(
        "program_amendment_proposal_digest"
    ) or settings.get("program_amendment_proposal_digest") != policy.get(
        "program_amendment_proposal_digest"
    ):
        raise AdmissionError("d5_programme_amendment_binding_drift")
    receipt = data.get("authorization_record", {})
    if (
        receipt.get("approved") is not True
        or not receipt.get("approved_by")
        or _digest(receipt) != row[1]
        or receipt.get("packet_digest") != row[0]
        or receipt.get("limits") != data["limits"]
        or receipt.get("members") != data.get("members")
        or receipt.get("stages") != data.get("stages")
        or receipt.get("case_bindings_digest") != _digest(data.get("cases", {}))
        or receipt.get("transport_mode") != policy.get("transport_mode")
        or receipt.get("authorization_kind")
        != ("offline_fixture" if policy.get("transport_mode") == "mock" else "owner")
        or datetime.fromisoformat(receipt["expires_at"]) != row[4]
    ):
        raise AdmissionError("d5_external_authorization_binding_drift")
    if (
        policy.get("transport_mode") == "provider"
        and conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone()
    ):
        raise AdmissionError("provider_forbidden_in_offline_fixture_database")
    allowed = stage_authorizations(conn, scope_id, data, row[1], row[4], now)
    cases = data.get("cases", {})
    case = cases.get(settings.get("d5_case_id"))
    if (
        not isinstance(case, dict)
        or case.get("input_digest") != _digest(inputs)
        or case.get("owner") != owner
        or case.get("operation") != settings.get("d5_operation")
    ):
        raise AdmissionError("d5_case_not_externally_authorized")
    if case.get("stage") not in allowed:
        raise AdmissionError("d5_stage_not_authorized")
    if case.get("stage") == "C":
        require_development(conn, scope_id, cases)
    return {
        **data,
        "id": scope_id,
        "case": case,
        "stage_authorizations": allowed,
        "authorization_digest": row[1],
    }


def guard_scope(
    conn: Any,
    owner: str,
    inputs: dict[str, Any],
    policy: dict[str, Any],
    *,
    amount: Decimal | None = None,
    endpoint: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    bound = scope(conn, owner, inputs, policy, datetime.now(UTC))
    # Original programme accounting/holds/history checks remain authoritative.
    guard_trial(
        conn,
        owner,
        policy,
        reserve_usd=amount,
        current_job=job_id,
        next_endpoint=endpoint,
        reserve_operation=inputs["settings"]["d5_operation"],
    )
    if inputs["settings"].get("d5_scope_profile"):
        from src.workspace.d5_coverage_policy import guard as coverage_guard

        coverage_guard(conn, bound, owner, inputs["settings"], amount=amount, endpoint=endpoint)
    history = census(conn, owner, members=bound["members"])
    baseline = bound["baseline"]
    limits = bound["limits"]
    # Scope members start empty; historical money lives in the same programme's
    # immutable parent ledger and is checked by guard_trial, never reset here.
    messages, counts = history["messages"], history["counts"]
    if (
        messages + (endpoint == "messages") > limits["messages"]
        or counts + (endpoint == "messages/count_tokens") > limits["counts"]
    ):
        raise AdmissionError("d5_scope_contact_cap_exceeded")
    jobs = conn.execute(
        "SELECT count(*) FROM workspace_d5_case_runs WHERE scope_id=%s AND input_digest IS NOT NULL",
        (bound["id"],),
    ).fetchone()[0]
    operation = inputs["settings"]["d5_operation"]
    if endpoint == "messages" and operation == "measurement":
        raise AdmissionError("measurement_messages_forbidden")
    if amount is not None:
        # Count-only helper jobs consume contacts but not generation-job slots.
        generating = conn.execute(
            "SELECT count(*) FROM workspace_d5_case_runs r JOIN workspace_generation_jobs j ON j.id=r.job_id WHERE r.scope_id=%s AND j.data->'sealed_input'->'settings'->>'d5_operation' <> 'measurement'",
            (bound["id"],),
        ).fetchone()[0]
        if operation != "measurement" and generating >= limits["jobs"]:
            raise AdmissionError("d5_scope_job_cap_exceeded")
        required = 1 if operation in {"measurement", "probe"} else 4
        if (
            messages + (0 if operation == "measurement" else required) > limits["messages"]
            or counts + required > limits["counts"]
        ):
            raise AdmissionError("d5_complete_workflow_contact_capacity_required")
        maximum = (
            Decimal("0")
            if operation == "measurement"
            else Decimal(limits["probe_usd"] if operation == "probe" else limits["workflow_usd"])
        )
        if inputs["settings"].get("operation_routes") and operation != "measurement":
            from src.workspace.d5_operations import reservation

            if amount < reservation(
                inputs["settings"]["operation_routes"], probe=operation == "probe"
            ):
                raise AdmissionError("d5_complete_operation_reservation_required")
        if amount > maximum:
            raise AdmissionError("d5_per_job_cap_exceeded")
        if history["uncertain_contacts"] or Decimal(history["unknown_usd"]):
            raise AdmissionError("d5_uncertain_completion_requires_reconciliation")
        if (
            Decimal(baseline["known_usd"])
            + Decimal(history["known_usd"])
            + Decimal(history["pending_usd"])
            + amount
            + Decimal(limits["headroom_usd"])
        ) > Decimal(limits["usd"]):
            raise AdmissionError("d5_cumulative_headroom_exceeded")
    if any(active != job_id for active in history["active_jobs"]):
        raise AdmissionError("d5_one_job_at_a_time")
    return {**bound, "usage": history, "case_runs": jobs}


class D5Admission(GenerationAdmission):
    def _record_reservation(
        self, conn: Any, owner: str, inputs: dict[str, Any], job_id: str
    ) -> None:
        settings = inputs["settings"]
        prior = conn.execute(
            "SELECT job_id,input_digest FROM workspace_d5_case_runs WHERE packet_digest=%s AND case_id=%s",
            (settings["d5_packet_digest"], settings["d5_case_id"]),
        ).fetchone()
        if prior and prior != (job_id, _digest(inputs)):
            raise AdmissionError("d5_case_already_attempted_no_replay")
        conn.execute(
            "INSERT INTO workspace_d5_case_runs(scope_id,case_id,packet_digest,owner,job_id,input_digest) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(scope_id,case_id) DO NOTHING",
            (
                settings["d5_scope_id"],
                settings["d5_case_id"],
                settings["d5_packet_digest"],
                owner,
                job_id,
                _digest(inputs),
            ),
        )
        policy_row = conn.execute(
            "SELECT data FROM workspace_budget_policies WHERE owner=%s", (owner,)
        ).fetchone()
        if policy_row is None:
            raise AdmissionError("d5_qualification_policy_missing")
        bound = scope(conn, owner, inputs, policy_row[0], datetime.now(UTC))
        chain = list(
            dict.fromkeys(
                [
                    bound["authorization_digest"],
                    bound["stage_authorizations"][bound["case"]["stage"]],
                ]
            )
        )
        from psycopg.types.json import Jsonb

        conn.execute(
            "UPDATE workspace_generation_jobs SET data=jsonb_set(data,'{d5_authorization_chain}',%s) WHERE id=%s",
            (Jsonb(chain), job_id),
        )

    @staticmethod
    def _valid_amount(amount: Decimal) -> bool:
        return amount >= 0

    @staticmethod
    def _policy(
        conn: Any, owner: str, inputs: dict[str, Any], now: datetime
    ) -> tuple[str, dict[str, Any]]:
        approval, policy = GenerationAdmission._policy(conn, owner, inputs, now)
        if (
            policy.get("purpose") != "workspace-d5-qualification-only"
            or policy.get("everyday_generation") is not False
            or policy.get("transport_mode") not in {"mock", "provider"}
            or not policy.get("program_id")
        ):
            raise AdmissionError("d5_qualification_only_approval_required")
        scope(conn, owner, inputs, policy, now)
        return approval, policy

    @staticmethod
    def _request_id(policy: dict[str, Any], request_id: str, inputs: dict[str, Any]) -> None:
        expected = inputs["settings"].get("d5_request_id")
        if not expected or expected != request_id:
            raise AdmissionError("d5_named_request_required")

    def _admit_input(
        self, conn: Any, owner: str, inputs: dict[str, Any], policy: dict[str, Any], amount: Decimal
    ) -> None:
        settings = inputs["settings"]
        operation = settings["d5_operation"]
        calls = 0 if operation == "measurement" else 1 if operation == "probe" else 4
        minimum = (
            (Decimal(settings["input_tokens"]) * 2 + Decimal(settings["output_tokens"]) * 10)
            * calls
            * Decimal("1.25")
            / 1_000_000
        )
        if amount < minimum:
            raise AdmissionError("d5_reservation_below_complete_envelope")
        guard_scope(conn, owner, inputs, policy, amount=amount)
