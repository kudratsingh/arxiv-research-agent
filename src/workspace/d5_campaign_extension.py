"""Append-only campaign capacity and exact historical quarantine exception.

No settlement: original uncertain rows, contacts, result and full hold never change.
Only an independently recorded owner receipt can activate this policy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign_policy import LIMITS, PROGRAM_LIMITS
from src.workspace.qualification_budget import census

REVISION = "programme-consolidated-campaign-v5"


def predecessor_seal(conn: Any, program_id: str) -> dict[str, Any]:
    """Fresh exact metadata/receipt audit, no cross-operation verification cache.

    Activation fully validates the legacy chain. Pin its entire immutable rows
    and revocation state; the campaign separately re-audits ALL old financial
    rows on every operation, a superset of each predecessor's old checkpoints.
    """
    from psycopg import sql

    result: dict[str, Any] = {}
    for table, revoked in (
        ("workspace_programme_amendments", "workspace_programme_amendment_revocations"),
        ("workspace_programme_successor_amendments", "workspace_programme_successor_revocations"),
        ("workspace_programme_third_amendments", "workspace_programme_third_revocations"),
        ("workspace_programme_capacity_amendments", "workspace_programme_capacity_revocations"),
    ):
        row = conn.execute(
            sql.SQL("SELECT to_jsonb(t) FROM {} t WHERE program_id=%s").format(
                sql.Identifier(table)
            ),
            (program_id,),
        ).fetchone()
        if not row:
            raise AdmissionError("campaign_capacity_predecessor_required")
        result[table] = _digest(row[0])
        result[revoked] = [
            _digest(r[0])
            for r in conn.execute(
                sql.SQL(
                    "SELECT to_jsonb(r) FROM {} r JOIN {} a USING(amendment_id) WHERE a.program_id=%s ORDER BY amendment_id"
                ).format(sql.Identifier(revoked), sql.Identifier(table)),
                (program_id,),
            )
        ]
    row = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_evaluation_programs t WHERE program_id=%s", (program_id,)
    ).fetchone()
    if not row:
        raise AdmissionError("campaign_original_programme_required")
    result["original_programme"] = _digest(row[0])
    return result


def parent(conn: Any, program_id: str) -> dict[str, Any]:
    from src.workspace.programme_amendments import effective_limits

    row = conn.execute(
        "SELECT record,authorization_digest,proposal_digest,expires_at FROM workspace_programme_capacity_amendments WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    if not row or _digest(row[0]) != row[1]:
        raise AdmissionError("campaign_capacity_predecessor_required")
    prior = {**PROGRAM_LIMITS, "new_jobs": 34, "messages": 80, "counts": 99}
    if (
        effective_limits(conn, program_id, required_proposal_digest=row[2]) != prior
        or datetime.now(UTC) >= row[3]
    ):
        raise AdmissionError("campaign_capacity_predecessor_drift_or_expiry")
    original = conn.execute(
        "SELECT authorization_digest FROM workspace_evaluation_programs WHERE program_id=%s",
        (program_id,),
    ).fetchone()[0]
    return {
        "authorization_digest": row[1],
        "proposal_digest": row[2],
        "original_authorization_digest": original,
        "limits": prior,
        "expires_at": row[3].isoformat(),
        "predecessor_seal": predecessor_seal(conn, program_id),
    }


def uncertain_binding(conn: Any, job_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT to_jsonb(j),to_jsonb(r)||jsonb_build_object('amount',r.amount::text,'workflow',r.workflow::text,'judge',r.judge::text,'unknown',r.unknown::text) "
        "FROM workspace_generation_jobs j JOIN workspace_spend_reservations r ON r.job_id=j.id WHERE j.id=%s",
        (job_id,),
    ).fetchone()
    if not row:
        raise AdmissionError("campaign_original_uncertain_job_required")
    job, hold = row
    unresolved = [
        c
        for c in job["data"].get("adapter", {}).get("contacts", [])
        if c.get("state") in {"dispatching", "running"}
    ]
    if (
        job["state"] != "uncertain"
        or job["data"].get("result") is not None
        or hold["state"] != "uncertain"
        or Decimal(hold["unknown"]) != Decimal("0.425066")
        or len(unresolved) != 1
        or unresolved[0]["endpoint"] != "messages"
    ):
        raise AdmissionError("campaign_exact_historical_exception_required")
    contact = unresolved[0]
    body = contact.get("body", {})
    if (
        contact.get("stage") != "check"
        or body.get("model") != "claude-opus-5-5"
        or contact.get("request_digest") != _digest(body)
    ):
        raise AdmissionError("campaign_uncertain_receipt_binding_required")
    scope_id = job["data"].get("sealed_input", {}).get("settings", {}).get("d5_scope_id")
    scope = (
        conn.execute(
            "SELECT to_jsonb(s) FROM workspace_d5_scopes s WHERE scope_id=%s", (scope_id,)
        ).fetchone()
        if scope_id
        else None
    )
    if scope and scope[0]["state"] not in {"stopped", "revoked"}:
        raise AdmissionError("campaign_original_scope_must_remain_closed")
    if not scope and not conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone():
        raise AdmissionError("campaign_original_scope_required")
    return {
        "job_id": job_id,
        "owner": job["owner"],
        "original_row_digest": _digest({"job": job, "reservation": hold}),
        "original_scope_digest": _digest(scope[0])
        if scope
        else "synthetic_fixture_without_legacy_scope",
        "contact_digest": _digest(unresolved[0]),
        "request_digest": unresolved[0]["request_digest"],
        "hold_usd": hold["unknown"],
        "original_state": "uncertain",
        "result_available": False,
        "settled": False,
        "upstream_completion_established": False,
        "billing_established": False,
        "policy": "Exclude only this immutable historical contact from the operational uncertainty veto for the bound campaign. Retain its entire hold in cumulative exposure exactly once. Any new uncertainty stops dispatch.",
    }


def proposal(conn: Any, program_id: str, plan_digest: str) -> dict[str, Any]:
    p = parent(conn, program_id)
    members = sorted(
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
        )
    )
    history = census(conn, members[0], members=members)
    baseline = conn.execute(
        "SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s", (program_id,)
    ).fetchone()[0]
    if len(set(history["generation_job_ids"]) - set(baseline["generation_job_ids"])) != 33 or (
        history["messages"],
        history["counts"],
        history["known_usd"],
        history["pending_usd"],
        history["unknown_usd"],
        history["active_jobs"],
    ) != (65, 90, "1.853811", "0.425066", "0.425066", []):
        raise AdmissionError("campaign_sealed_33_65_90_baseline_required")
    jobs = [
        r[0]
        for r in conn.execute(
            "SELECT j.id FROM workspace_generation_jobs j JOIN workspace_spend_reservations r ON r.job_id=j.id WHERE j.owner=ANY(%s)AND(j.state='uncertain' OR r.unknown>0)",
            (members,),
        )
    ]
    if len(jobs) != 1:
        raise AdmissionError("campaign_exactly_one_historical_hold_required")
    core = {
        "revision": REVISION,
        "extension_id": program_id + "-campaign-v5",
        "program_id": program_id,
        "parent": p,
        "limits": PROGRAM_LIMITS,
        "campaign_limits": LIMITS,
        "plan_digest": plan_digest,
        "basis_members": members,
        "basis": history,
        "historical_exception": uncertain_binding(conn, jobs[0]),
        "programme_expiry": p["expires_at"],
    }
    return {"core": core, "proposal_digest": _digest(core), "approved": False}


def _validate(conn: Any, record: dict[str, Any], program_id: str) -> dict[str, Any]:
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_campaign_policy import audit_outcomes
    from src.workspace.d5_freeze import code_bindings

    core = record.get("campaign_extension", {}).get("core", {})
    p = core.get("parent", {})
    if p.get("predecessor_seal") != predecessor_seal(conn, program_id):
        raise AdmissionError("campaign_predecessor_receipt_or_revocation_changed")
    expected_sources = record.get("source_bindings", {})
    actual_sources = {
        "versions": {
            r[0]: _digest(r[1])
            for r in conn.execute(
                "SELECT version_id,data FROM workspace_versions WHERE version_id=ANY(%s)",
                (list(expected_sources.get("versions", {})),),
            )
        },
        "materials": {
            r[0]: _digest(r[1])
            for r in conn.execute(
                "SELECT material_id,data FROM workspace_material WHERE material_id=ANY(%s)",
                (list(expected_sources.get("materials", {})),),
            )
        },
    }
    if (
        not expected_sources.get("versions")
        or not expected_sources.get("materials")
        or actual_sources != expected_sources
    ):
        raise AdmissionError("campaign_frozen_source_binding_drift")
    if (
        core.get("revision") != REVISION
        or core.get("program_id") != program_id
        or core.get("extension_id") != program_id + "-campaign-v5"
        or p.get("limits") != {**PROGRAM_LIMITS, "new_jobs": 34, "messages": 80, "counts": 99}
        or core.get("limits") != PROGRAM_LIMITS
        or core.get("campaign_limits") != LIMITS
        or core.get("programme_expiry") != p["expires_at"]
        or record.get("campaign_extension", {}).get("proposal_digest") != _digest(core)
        or record.get("historical_uncertainty_exception_approved") is not True
        or record.get("capacity_amendment_approved") is not True
        or record.get("code_bindings") != code_bindings()
        or record.get("adapter_binding") != qualification_producer()
    ):
        raise AdmissionError("campaign_extension_or_exception_binding_drift")
    try:
        start, end = (
            datetime.fromisoformat(record["approved_at"]),
            datetime.fromisoformat(record["expires_at"]),
        )
        valid_time = (
            start.tzinfo
            and end.tzinfo
            and start
            <= datetime.now(UTC)
            < end
            <= min(start + timedelta(hours=24), datetime.fromisoformat(p["expires_at"]))
        )
    except (KeyError, TypeError, ValueError):
        valid_time = False
    fixture = bool(conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone())
    if (
        record.get("approved") is not True
        or not record.get("approved_by")
        or not record.get("approval_source")
        or not valid_time
        or record.get("transport_mode") != ("mock" if fixture else "provider")
        or record.get("authorization_kind") != ("offline_fixture" if fixture else "owner")
    ):
        raise AdmissionError("campaign_external_owner_authorization_required")
    historical = census(
        conn,
        core["basis_members"][0],
        members=core["basis_members"],
        job_ids=sorted(core["basis"]["contact_checkpoints"]),
    )
    if (
        historical != core["basis"]
        or uncertain_binding(conn, core["historical_exception"]["job_id"])
        != core["historical_exception"]
    ):
        raise AdmissionError("campaign_original_history_or_hold_changed")
    if (
        record.get("case_order") is None
        or len(record["case_order"]) != 14
        or len(set(record["case_order"])) != 14
        or record.get("limits") != LIMITS
        or record.get("stages") != ["B", "C", "D"]
    ):
        raise AdmissionError("campaign_scope_or_schedule_binding_drift")
    audit_outcomes(conn, record["scope_id"])
    return dict(core)


def active(
    conn: Any, program_id: str, required: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    from src.workspace.d5_campaign_v14_extension import active as successor_active

    successor = successor_active(conn, program_id, required)
    if successor is not None:
        return successor
    if not conn.execute("SELECT to_regclass('workspace_d5_campaign_extensions')").fetchone()[0]:
        return None
    row = conn.execute(
        "SELECT record,authorization_digest,proposal_digest,packet_digest,scope_id,expires_at FROM workspace_d5_campaign_extensions WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    if not row:
        return None
    record, digest, pdigest, packet, scope, expiry = row
    core = _validate(conn, record, program_id)
    if (
        _digest(record) != digest
        or required is not None
        and required != pdigest
        or record["campaign_extension"]["proposal_digest"] != pdigest
        or record["packet_digest"] != packet
        or record["scope_id"] != scope
        or datetime.fromisoformat(record["expires_at"]) != expiry
        or conn.execute(
            "SELECT 1 FROM workspace_d5_campaign_revocations WHERE extension_id=%s",
            (core["extension_id"],),
        ).fetchone()
    ):
        raise AdmissionError("campaign_extension_receipt_or_revocation_drift")
    return record, core


def effective(
    conn: Any,
    program_id: str,
    prior_limits: dict[str, Any],
    prior_digest: str,
    required: str | None,
) -> dict[str, Any]:
    if required == prior_digest:
        return prior_limits
    found = active(conn, program_id, required)
    if found:
        return dict(found[1]["limits"])
    if required is not None:
        raise AdmissionError("programme_amendment_binding_or_revocation")
    return prior_limits


def record_external(store: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_campaign_v14_extension import REVISION as SUCCESSOR_REVISION
    from src.workspace.d5_campaign_v14_extension import record_external as record_successor

    if receipt.get("campaign_extension", {}).get("core", {}).get("revision") == SUCCESSOR_REVISION:
        return record_successor(store, receipt)
    if receipt.get("approved") is not True or not receipt.get("approved_by"):
        raise AdmissionError("campaign_external_owner_authorization_required")
    core = receipt.get("campaign_extension", {}).get("core", {})
    pid = core.get("program_id")
    store.migrate()
    with store.pool.connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + str(pid),)
        )
        _validate(conn, receipt, pid)
        old = conn.execute(
            "SELECT authorization_digest FROM workspace_d5_campaign_extensions WHERE program_id=%s",
            (pid,),
        ).fetchone()
        digest = _digest(receipt)
        if old:
            if old[0] != digest:
                raise AdmissionError("campaign_extension_immutable_no_reapproval")
            return {"authorization_digest": digest, "duplicate": True}
        if proposal(conn, pid, core["plan_digest"])["core"] != core:
            raise AdmissionError("campaign_activation_census_drift")
        conn.execute(
            "INSERT INTO workspace_d5_campaign_extensions(program_id,revision,extension_id,predecessor_authorization_digest,proposal_digest,authorization_digest,packet_digest,scope_id,record,expires_at) VALUES(%s,5,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                pid,
                core["extension_id"],
                core["parent"]["authorization_digest"],
                receipt["campaign_extension"]["proposal_digest"],
                digest,
                receipt["packet_digest"],
                receipt["scope_id"],
                Jsonb(receipt),
                datetime.fromisoformat(receipt["expires_at"]),
            ),
        )
    return {
        "authorization_digest": digest,
        "provider_contacts": 0,
        "financial_rows_changed": False,
        "limits": PROGRAM_LIMITS,
        "historical_hold_retained": core["historical_exception"]["hold_usd"],
    }


def validate_scope(conn: Any, program_id: str, receipt: dict[str, Any]) -> None:
    found = active(conn, program_id, receipt.get("campaign_extension", {}).get("proposal_digest"))
    if not found or found[0] != receipt:
        raise AdmissionError("campaign_matching_activation_required")


def guard_exception(
    conn: Any, policy: dict[str, Any], *, verified: Any = None, current_job: str | None = None
) -> dict[str, Any]:
    """Ignore one frozen operational veto, never its liability or any new contact."""
    found = verified or active(
        conn, policy["program_id"], policy.get("program_amendment_proposal_digest")
    )
    if not found:
        raise AdmissionError("program_external_completion_uncertain")
    receipt, core = found
    from src.workspace.d5_campaign_v14_extension import REVISION as SUCCESSOR_REVISION
    from src.workspace.d5_campaign_v14_extension import guard_exception as successor_guard

    if core["revision"] == SUCCESSOR_REVISION:
        return successor_guard(conn, policy, found, current_job)
    if policy.get("d5_scope_id") != receipt["scope_id"] or policy.get(
        "d5_authorization_digest"
    ) != _digest(receipt):
        raise AdmissionError("campaign_exception_scope_mismatch")
    members = [
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
            (policy["program_id"],),
        )
    ]
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM workspace_generation_jobs WHERE owner=ANY(%s)AND id<>%s",
            (members, core["historical_exception"]["job_id"]),
        )
    ]
    rest = census(conn, members[0], members=members, job_ids=ids)
    # The existing journal calls an allocated, not-yet-dispatched contact
    # 'running'. Permit only that current operation; never a dispatching contact
    # or an unfinished contact recovered by another runner/process.
    contacts = conn.execute(
        "SELECT j.id,j.state,c.value->>'state' FROM workspace_generation_jobs j CROSS JOIN LATERAL jsonb_array_elements(COALESCE(j.data->'adapter'->'contacts','[]')) c WHERE j.owner=ANY(%s)AND j.id<>%s AND c.value->>'state' IN('running','dispatching')",
        (members, core["historical_exception"]["job_id"]),
    )
    uncertain = any(
        state == "dispatching" or jid != current_job or job_state != "running"
        for jid, job_state, state in contacts
    )
    if uncertain or Decimal(rest["unknown_usd"]):
        raise AdmissionError("campaign_new_external_completion_uncertain")
    return dict(core["historical_exception"])
