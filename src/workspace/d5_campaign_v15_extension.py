"""Append-only capacity successor; original receipts and liabilities never change.

Historical producer hashes belong to the stopped predecessor, not this producer.
New expiry is an explicit bounded owner decision, never a renewal of old grants.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign_v15_policy import LIMITS, PROGRAM_LIMITS
from src.workspace.qualification_budget import census

REVISION = "programme-comprehensive-capacity-successor-v7"
HISTORICAL_PROGRAMME_EXPIRY = "2026-11-14T07:24:01+00:00"


def _fixture(conn: Any) -> bool:
    return bool(conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone())


def expiry_policy(historical_expiry: str) -> dict[str, Any]:
    return {
        "historical_programme_expiry": historical_expiry,
        "programme_max_seconds_from_approval": 604800,
        "campaign_max_seconds_from_approval": 86400,
        "requires_explicit_extension": True,
    }


def parent(conn: Any, program_id: str) -> dict[str, Any]:
    """Audit immutable v14 receipts without revalidating historical producers."""
    from src.workspace.d5_campaign_v14_extension import REVISION as PRIOR_REVISION
    from src.workspace.d5_campaign_v14_extension import parent as prior_parent
    from src.workspace.d5_campaign_v14_extension import retained_bindings
    from src.workspace.d5_campaign_v14_policy import LIMITS as PRIOR_LIMITS
    from src.workspace.d5_campaign_v14_policy import PROGRAM_LIMITS as PRIOR_PROGRAM_LIMITS

    row = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_campaign_successors t WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    if not row:
        raise AdmissionError("campaign_v15_parent_receipt_required")
    value = row[0]
    record = value["record"]
    core = record.get("campaign_extension", {}).get("core", {})
    earlier = prior_parent(conn, program_id)
    retained = retained_bindings(conn, program_id)
    scope = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_scopes t WHERE scope_id=%s", (value["scope_id"],)
    ).fetchone()
    if (
        value.get("revision") != 6
        or _digest(record) != value["authorization_digest"]
        or _digest(core) != value["proposal_digest"]
        or core.get("revision") != PRIOR_REVISION
        or core.get("program_id") != program_id
        or core.get("extension_id") != value["extension_id"]
        or record.get("campaign_extension", {}).get("proposal_digest") != value["proposal_digest"]
        or core.get("limits") != PRIOR_PROGRAM_LIMITS
        or core.get("campaign_limits") != PRIOR_LIMITS
        or core.get("parent") != earlier
        or core.get("programme_expiry") != earlier["expires_at"]
        or core.get("retained_exceptions") != retained
        or record.get("packet_digest") != value["packet_digest"]
        or record.get("scope_id") != value["scope_id"]
        or record.get("approved") is not True
        or record.get("budget_adjustment_approved") is not True
        or record.get("capacity_amendment_approved") is not True
        or record.get("historical_uncertainty_exception_approved") is not True
        or not scope
        or scope[0]["state"] != "stopped"
        or scope[0]["packet_digest"] != value["packet_digest"]
        or scope[0]["authorization_digest"] != value["authorization_digest"]
        or scope[0]["data"].get("authorization_record") != record
        or datetime.fromisoformat(record["expires_at"])
        != datetime.fromisoformat(value["expires_at"])
        or datetime.fromisoformat(scope[0]["expires_at"])
        != datetime.fromisoformat(record["expires_at"])
        or conn.execute(
            "SELECT 1 FROM workspace_d5_campaign_successor_revocations WHERE extension_id=%s",
            (value["extension_id"],),
        ).fetchone()
    ):
        raise AdmissionError("campaign_v15_parent_or_stopped_scope_drift")
    return {
        "extension_id": value["extension_id"],
        "authorization_digest": value["authorization_digest"],
        "proposal_digest": value["proposal_digest"],
        "packet_digest": value["packet_digest"],
        "scope_id": value["scope_id"],
        "expires_at": record["expires_at"],
        "programme_expires_at": core["programme_expiry"],
        "limits": core["limits"],
        "row_digest": _digest(value),
        "stopped_scope_digest": _digest(scope[0]),
        "predecessor_seal": earlier["predecessor_seal"],
    }


def history(conn: Any, program_id: str) -> tuple[list[str], dict[str, Any]]:
    members = sorted(
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
        )
    )
    if not members:
        raise AdmissionError("campaign_v15_programme_members_required")
    value = census(conn, members[0], members=members)
    row = conn.execute(
        "SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s", (program_id,)
    ).fetchone()
    if not row:
        raise AdmissionError("campaign_v15_programme_baseline_required")
    if len(set(value["generation_job_ids"]) - set(row[0]["generation_job_ids"])) != 36 or (
        value["messages"],
        value["counts"],
        value["known_usd"],
        value["pending_usd"],
        value["unknown_usd"],
        value["active_jobs"],
    ) != (70, 95, "2.110597", "0.875066", "0.875066", []):
        raise AdmissionError("campaign_v15_sealed_36_70_95_baseline_required")
    return members, value


def proposal(conn: Any, program_id: str, plan_digest: str) -> dict[str, Any]:
    from src.workspace.d5_campaign_v14_extension import retained_bindings

    if not isinstance(plan_digest, str) or not plan_digest.strip():
        raise AdmissionError("campaign_v15_plan_identity_required")
    p = parent(conn, program_id)
    members, baseline = history(conn, program_id)
    core = {
        "revision": REVISION,
        "extension_id": program_id + "-capacity-v15",
        "program_id": program_id,
        "parent": p,
        "limits": PROGRAM_LIMITS,
        "campaign_limits": LIMITS,
        "plan_digest": plan_digest,
        "basis_members": members,
        "basis": baseline,
        "retained_exceptions": retained_bindings(conn, program_id),
        "expiry_policy": expiry_policy(p["programme_expires_at"]),
        "dollar_adjustment": {"from": "12", "to": "20", "approved": False},
        "liability_policy": "Quarantine only the two immutable named records for this campaign. Retain both full holds exactly once; no billing/cancellation finding and no replay. Any new uncertainty stops.",
    }
    return {"core": core, "proposal_digest": _digest(core), "approved": False}


def _validate(conn: Any, receipt: dict[str, Any], program_id: str) -> dict[str, Any]:
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_campaign_policy import audit_outcomes
    from src.workspace.d5_campaign_v14_extension import retained_bindings
    from src.workspace.d5_freeze import code_bindings

    core = receipt.get("campaign_extension", {}).get("core", {})
    p = core.get("parent", {})
    if (
        core.get("revision") != REVISION
        or core.get("program_id") != program_id
        or core.get("extension_id") != program_id + "-capacity-v15"
        or core.get("limits") != PROGRAM_LIMITS
        or core.get("campaign_limits") != LIMITS
        or core.get("expiry_policy") != expiry_policy(p.get("programme_expires_at"))
        or receipt.get("campaign_extension", {}).get("proposal_digest") != _digest(core)
        or p != parent(conn, program_id)
        or core.get("retained_exceptions") != retained_bindings(conn, program_id)
        or core.get("dollar_adjustment") != {"from": "12", "to": "20", "approved": False}
        or receipt.get("expiry_adjustment_approved") is not True
        or receipt.get("budget_adjustment_approved") is not True
        or receipt.get("capacity_amendment_approved") is not True
        or receipt.get("historical_uncertainty_exception_approved") is not True
        or receipt.get("code_bindings") != code_bindings()
        or receipt.get("adapter_binding") != qualification_producer()
        or receipt.get("limits") != LIMITS
        or receipt.get("stages") != ["B", "C", "D"]
        or len(receipt.get("case_order", [])) != 14
        or len(set(receipt.get("case_order", []))) != 14
        or not receipt.get("packet_digest")
        or not receipt.get("scope_id")
    ):
        raise AdmissionError("campaign_v15_receipt_or_parent_binding_drift")
    fixture = _fixture(conn)
    try:
        start = datetime.fromisoformat(receipt["approved_at"])
        expiry = datetime.fromisoformat(receipt["expires_at"])
        programme_expiry = datetime.fromisoformat(receipt["programme_expires_at"])
        valid_time = bool(
            all(
                t.tzinfo and t.utcoffset() == timedelta(0)
                for t in (start, expiry, programme_expiry)
            )
            and start
            <= datetime.now(UTC)
            < expiry
            <= min(start + timedelta(hours=24), programme_expiry)
            <= start + timedelta(days=7)
            and datetime.now(UTC) < programme_expiry <= start + timedelta(days=7)
        )
    except (KeyError, TypeError, ValueError):
        valid_time = False
    if (
        receipt.get("approved") is not True
        or not isinstance(receipt.get("approved_by"), str)
        or not receipt["approved_by"].strip()
        or not isinstance(receipt.get("approval_source"), str)
        or not receipt["approval_source"].strip()
        or not valid_time
        or receipt.get("transport_mode") != ("mock" if fixture else "provider")
        or receipt.get("authorization_kind") != ("offline_fixture" if fixture else "owner")
    ):
        raise AdmissionError("campaign_v15_external_owner_authorization_required")
    actual = census(
        conn,
        core["basis_members"][0],
        members=core["basis_members"],
        job_ids=sorted(core["basis"]["contact_checkpoints"]),
    )
    if actual != core["basis"]:
        raise AdmissionError("campaign_v15_historical_receipts_changed")
    expected = receipt.get("source_bindings", {})
    observed = {}
    for label, table, key in (
        ("versions", "workspace_versions", "version_id"),
        ("materials", "workspace_material", "material_id"),
    ):
        observed[label] = {
            r[0]: _digest(r[1])
            for r in conn.execute(
                sql.SQL("SELECT {},data FROM {} WHERE {}=ANY(%s)").format(
                    sql.Identifier(key), sql.Identifier(table), sql.Identifier(key)
                ),
                (list(expected.get(label, {})),),
            )
        }
    if not expected.get("versions") or not expected.get("materials") or observed != expected:
        raise AdmissionError("campaign_v15_source_binding_drift")
    audit_outcomes(conn, receipt["scope_id"])
    return dict(core)


def active(
    conn: Any, program_id: str, required: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not conn.execute("SELECT to_regclass('workspace_d5_capacity_revisions')").fetchone()[0]:
        return None
    row = conn.execute(
        "SELECT record,authorization_digest,proposal_digest,packet_digest,scope_id,expires_at,extension_id,programme_expires_at,predecessor_extension_id,predecessor_authorization_digest FROM workspace_d5_capacity_revisions WHERE program_id=%s AND (%s::text IS NULL OR proposal_digest=%s) ORDER BY created_at DESC,extension_id DESC LIMIT 1",
        (program_id, required, required),
    ).fetchone()
    if not row or required is not None and required != row[2]:
        return None
    (
        receipt,
        digest,
        pdigest,
        packet,
        scope_id,
        expiry,
        extension_id,
        programme_expiry,
        predecessor_extension,
        predecessor_authorization,
    ) = row
    if (
        _digest(receipt) != digest
        or receipt["campaign_extension"]["core"].get("parent", {}).get("extension_id")
        != predecessor_extension
        or receipt["campaign_extension"]["core"].get("parent", {}).get("authorization_digest")
        != predecessor_authorization
        or receipt["campaign_extension"]["core"].get("extension_id") != extension_id
        or receipt["campaign_extension"]["proposal_digest"] != pdigest
        or receipt["packet_digest"] != packet
        or receipt["scope_id"] != scope_id
        or datetime.fromisoformat(receipt["expires_at"]) != expiry
        or datetime.fromisoformat(receipt["programme_expires_at"]) != programme_expiry
        or conn.execute(
            "SELECT 1 FROM workspace_d5_capacity_revision_revocations WHERE extension_id=%s",
            (extension_id,),
        ).fetchone()
    ):
        raise AdmissionError("campaign_v15_revoked_or_receipt_drift")
    return receipt, _validate(conn, receipt, program_id)


def record_external(store: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("approved") is not True:
        raise AdmissionError("campaign_v15_explicit_owner_approval_required")
    core = receipt.get("campaign_extension", {}).get("core", {})
    pid = core.get("program_id")
    store.migrate()
    with store.pool.connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + str(pid),)
        )
        _validate(conn, receipt, pid)
        digest = _digest(receipt)
        prior = conn.execute(
            "SELECT authorization_digest FROM workspace_d5_capacity_revisions WHERE extension_id=%s",
            (core["extension_id"],),
        ).fetchone()
        if prior:
            if conn.execute(
                "SELECT 1 FROM workspace_d5_capacity_revision_revocations WHERE extension_id=%s",
                (core["extension_id"],),
            ).fetchone():
                raise AdmissionError("campaign_v15_revoked_or_receipt_drift")
            if prior[0] != digest:
                raise AdmissionError("campaign_v15_immutable_no_reapproval")
            return {"authorization_digest": digest, "duplicate": True}
        if proposal(conn, pid, core["plan_digest"])["core"] != core:
            raise AdmissionError("campaign_v15_activation_census_drift")
        conn.execute(
            "INSERT INTO workspace_d5_capacity_revisions(program_id,revision,extension_id,predecessor_extension_id,predecessor_authorization_digest,proposal_digest,authorization_digest,packet_digest,scope_id,record,expires_at,programme_expires_at) VALUES(%s,7,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                pid,
                core["extension_id"],
                core["parent"]["extension_id"],
                core["parent"]["authorization_digest"],
                receipt["campaign_extension"]["proposal_digest"],
                digest,
                receipt["packet_digest"],
                receipt["scope_id"],
                Jsonb(receipt),
                datetime.fromisoformat(receipt["expires_at"]),
                datetime.fromisoformat(receipt["programme_expires_at"]),
            ),
        )
    return {
        "authorization_digest": digest,
        "limits": PROGRAM_LIMITS,
        "retained_liability_usd": "0.875066",
        "financial_rows_changed": False,
        "provider_contacts": 0,
    }


def guard_exception(
    conn: Any, policy: dict[str, Any], found: Any, current_job: str | None
) -> dict[str, Any]:
    receipt, core = found
    if policy.get("d5_scope_id") != receipt["scope_id"] or policy.get(
        "d5_authorization_digest"
    ) != _digest(receipt):
        raise AdmissionError("campaign_v15_exception_scope_mismatch")
    excluded = [e["binding"]["job_id"] for e in core["retained_exceptions"]]
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
            "SELECT id FROM workspace_generation_jobs WHERE owner=ANY(%s)AND NOT(id=ANY(%s))",
            (members, excluded),
        )
    ]
    rest = census(conn, members[0], members=members, job_ids=ids)
    contacts = conn.execute(
        "SELECT j.id,j.state,c.value->>'state' FROM workspace_generation_jobs j CROSS JOIN LATERAL jsonb_array_elements(COALESCE(j.data->'adapter'->'contacts','[]')) c WHERE j.owner=ANY(%s)AND NOT(j.id=ANY(%s))AND c.value->>'state' IN('running','dispatching')",
        (members, excluded),
    )
    if Decimal(rest["unknown_usd"]) or any(
        state == "dispatching" or jid != current_job or job_state != "running"
        for jid, job_state, state in contacts
    ):
        raise AdmissionError("campaign_v15_new_external_uncertainty")
    return {
        "retained_exceptions": core["retained_exceptions"],
        "retained_liability_usd": "0.875066",
        "settled": False,
    }
