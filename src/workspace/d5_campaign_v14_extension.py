"""Append-only prospective successor with two distinct retained liabilities.

This module never settles either contact. The parent v13 receipt is historical:
its old producer hashes are pinned, never replaced with this implementation.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign_v14_policy import LIMITS, PROGRAM_LIMITS
from src.workspace.qualification_budget import census

REVISION = "programme-complete-verdict-successor-v6"


def parent(conn: Any, program_id: str) -> dict[str, Any]:
    from src.workspace.d5_campaign_extension import predecessor_seal

    row = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_campaign_extensions t WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    if not row:
        raise AdmissionError("campaign_v14_parent_receipt_required")
    value = row[0]
    record = value["record"]
    core = record.get("campaign_extension", {}).get("core", {})
    legacy_seal = predecessor_seal(conn, program_id)
    scope = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_scopes t WHERE scope_id=%s", (value["scope_id"],)
    ).fetchone()
    if (
        _digest(record) != value["authorization_digest"]
        or _digest(core) != value["proposal_digest"]
        or core.get("revision") != "programme-consolidated-campaign-v5"
        or core.get("limits")
        != {"new_jobs": 47, "messages": 109, "counts": 134, "usd": "10", "concurrency": 1}
        or record.get("packet_digest") != value["packet_digest"]
        or not scope
        or scope[0]["state"] != "stopped"
        or scope[0]["packet_digest"] != value["packet_digest"]
        or record.get("approved") is not True
        or record.get("capacity_amendment_approved") is not True
        or record.get("historical_uncertainty_exception_approved") is not True
        or record.get("scope_id") != value["scope_id"]
        or scope[0]["authorization_digest"] != value["authorization_digest"]
        or scope[0]["data"].get("authorization_record") != record
        or datetime.fromisoformat(record["expires_at"])
        != datetime.fromisoformat(value["expires_at"])
        or legacy_seal != core.get("parent", {}).get("predecessor_seal")
        or conn.execute(
            "SELECT 1 FROM workspace_d5_campaign_revocations WHERE extension_id=%s",
            (value["extension_id"],),
        ).fetchone()
    ):
        raise AdmissionError("campaign_v14_parent_or_stopped_scope_drift")
    return {
        "authorization_digest": value["authorization_digest"],
        "proposal_digest": value["proposal_digest"],
        "packet_digest": value["packet_digest"],
        "scope_id": value["scope_id"],
        "expires_at": record["expires_at"],
        "limits": core["limits"],
        "row_digest": _digest(value),
        "stopped_scope_digest": _digest(scope[0]),
        "predecessor_seal": legacy_seal,
    }


def retained_bindings(conn: Any, program_id: str) -> list[dict[str, Any]]:
    """One unknown upstream contact and one fully received usage-less rejection."""
    from src.workspace.d5_campaign_extension import uncertain_binding

    members = [
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
        )
    ]
    rows = conn.execute(
        "SELECT to_jsonb(j),to_jsonb(r)||jsonb_build_object('amount',r.amount::text,'workflow',r.workflow::text,'judge',r.judge::text,'unknown',r.unknown::text) FROM workspace_generation_jobs j JOIN workspace_spend_reservations r ON r.job_id=j.id WHERE j.owner=ANY(%s)AND r.unknown>0 ORDER BY j.id",
        (members,),
    ).fetchall()
    if len(rows) != 2:
        raise AdmissionError("campaign_v14_exact_two_retained_holds_required")
    result: list[dict[str, Any]] = []
    predecessor = parent(conn, program_id)
    for job, hold in rows:
        if Decimal(hold["unknown"]) == Decimal("0.425066"):
            result.append(
                {
                    "kind": "unknown_upstream_completion",
                    "binding": uncertain_binding(conn, job["id"]),
                }
            )
            continue
        contacts = job["data"].get("adapter", {}).get("contacts", [])
        contact = contacts[-1] if contacts else {}
        response = contact.get("response", {})
        raw = response.get("raw_body")
        settings = job["data"].get("sealed_input", {}).get("settings", {})
        if (
            job["state"] != "uncertain"
            or job["data"].get("result") is not None
            or hold["state"] != "uncertain"
            or Decimal(hold["unknown"]) != Decimal("0.45")
            or len(contacts) != 2
            or any(c.get("state") != "completed" for c in contacts)
            or contacts[0].get("endpoint") != "messages/count_tokens"
            or contacts[0].get("request_digest") != _digest(contacts[0].get("body"))
            or contacts[0].get("body")
            != {
                k: v
                for k, v in contact.get("body", {}).items()
                if k not in {"max_tokens", "temperature"}
            }
            or type(contacts[0].get("response", {}).get("input_tokens")) is not int
            or not 0 <= contacts[0]["response"]["input_tokens"] <= 16000
            or contact.get("endpoint") != "messages"
            or contact.get("stage") != "draft"
            or contact.get("request_digest") != _digest(contact.get("body"))
            or contacts[0].get("generation_request_digest") != contact.get("request_digest")
            or contact.get("body", {}).get("model") != "claude-sonnet-5-5"
            or response.get("http_status") != 400
            or response.get("complete_body") is not True
            or response.get("usage_validated") is not False
            or not isinstance(raw, str)
            or response.get("body_digest") != hashlib.sha256(raw.encode()).hexdigest()
            or settings.get("d5_scope_id") != predecessor["scope_id"]
            or settings.get("d5_packet_digest") != predecessor["packet_digest"]
            or settings.get("d5_case_id") != "campaign-dev-compare"
        ):
            raise AdmissionError("campaign_v14_exact_received_http400_hold_required")
        result.append(
            {
                "kind": "received_http400_usage_unvalidated",
                "binding": {
                    "job_id": job["id"],
                    "owner": job["owner"],
                    "original_row_digest": _digest({"job": job, "reservation": hold}),
                    "contact_digest": _digest(contact),
                    "request_digest": contact["request_digest"],
                    "scope_id": predecessor["scope_id"],
                    "packet_digest": predecessor["packet_digest"],
                    "original_state": "uncertain",
                    "http_status": 400,
                    "complete_body": True,
                    "usage_validated": False,
                    "body_digest": response["body_digest"],
                    "hold_usd": hold["unknown"],
                    "result_available": False,
                    "billing_established": False,
                    "settled": False,
                },
            }
        )
    if sorted(r["kind"] for r in result) != [
        "received_http400_usage_unvalidated",
        "unknown_upstream_completion",
    ]:
        raise AdmissionError("campaign_v14_distinct_liability_evidence_required")
    return sorted(result, key=lambda r: r["kind"])


def history(conn: Any, program_id: str) -> tuple[list[str], dict[str, Any]]:
    members = sorted(
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
        )
    )
    value = census(conn, members[0], members=members)
    baseline = conn.execute(
        "SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s", (program_id,)
    ).fetchone()[0]
    if len(set(value["generation_job_ids"]) - set(baseline["generation_job_ids"])) != 35 or (
        value["messages"],
        value["counts"],
        value["known_usd"],
        value["pending_usd"],
        value["unknown_usd"],
        value["active_jobs"],
    ) != (68, 93, "1.986755", "0.875066", "0.875066", []):
        raise AdmissionError("campaign_v14_sealed_35_68_93_baseline_required")
    return members, value


def proposal(conn: Any, program_id: str, plan_digest: str) -> dict[str, Any]:
    p = parent(conn, program_id)
    if datetime.now(UTC) >= datetime.fromisoformat(p["expires_at"]):
        raise AdmissionError("campaign_v14_existing_programme_expired_new_decision_required")
    members, baseline = history(conn, program_id)
    core = {
        "revision": REVISION,
        "extension_id": program_id + "-campaign-v6",
        "program_id": program_id,
        "parent": p,
        "limits": PROGRAM_LIMITS,
        "campaign_limits": LIMITS,
        "plan_digest": plan_digest,
        "basis_members": members,
        "basis": baseline,
        "retained_exceptions": retained_bindings(conn, program_id),
        "programme_expiry": p["expires_at"],
        "dollar_adjustment": {"from": "10", "to": "12", "approved": False},
        "liability_policy": "Quarantine only the two immutable named records for this new campaign. Retain both full holds once; establish no billing/cancellation and permit no replay. Any new uncertainty stops.",
    }
    return {"core": core, "proposal_digest": _digest(core), "approved": False}


def _validate(conn: Any, receipt: dict[str, Any], program_id: str) -> dict[str, Any]:
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_campaign_policy import audit_outcomes
    from src.workspace.d5_freeze import code_bindings

    core = receipt.get("campaign_extension", {}).get("core", {})
    p = core.get("parent", {})
    if (
        core.get("revision") != REVISION
        or core.get("program_id") != program_id
        or core.get("extension_id") != program_id + "-campaign-v6"
        or core.get("limits") != PROGRAM_LIMITS
        or core.get("campaign_limits") != LIMITS
        or core.get("programme_expiry") != p.get("expires_at")
        or receipt.get("campaign_extension", {}).get("proposal_digest") != _digest(core)
        or p != parent(conn, program_id)
        or core.get("retained_exceptions") != retained_bindings(conn, program_id)
        or core.get("dollar_adjustment") != {"from": "10", "to": "12", "approved": False}
        or receipt.get("budget_adjustment_approved") is not True
        or receipt.get("capacity_amendment_approved") is not True
        or receipt.get("historical_uncertainty_exception_approved") is not True
        or receipt.get("code_bindings") != code_bindings()
        or receipt.get("adapter_binding") != qualification_producer()
        or receipt.get("limits") != LIMITS
        or receipt.get("stages") != ["B", "C", "D"]
        or len(set(receipt.get("case_order", []))) != 14
    ):
        raise AdmissionError("campaign_v14_receipt_or_parent_binding_drift")
    fixture = bool(conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone())
    try:
        start = datetime.fromisoformat(receipt["approved_at"])
        expiry = datetime.fromisoformat(receipt["expires_at"])
        valid_time = bool(
            start.tzinfo
            and expiry.tzinfo
            and start
            <= datetime.now(UTC)
            < expiry
            <= min(start + timedelta(hours=24), datetime.fromisoformat(p["expires_at"]))
        )
    except (KeyError, TypeError, ValueError):
        valid_time = False
    if (
        receipt.get("approved") is not True
        or not receipt.get("approved_by")
        or not receipt.get("approval_source")
        or not valid_time
        or receipt.get("transport_mode") != ("mock" if fixture else "provider")
        or receipt.get("authorization_kind") != ("offline_fixture" if fixture else "owner")
    ):
        raise AdmissionError("campaign_v14_external_owner_authorization_required")
    actual = census(
        conn,
        core["basis_members"][0],
        members=core["basis_members"],
        job_ids=sorted(core["basis"]["contact_checkpoints"]),
    )
    if actual != core["basis"]:
        raise AdmissionError("campaign_v14_historical_receipts_changed")
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
        raise AdmissionError("campaign_v14_source_binding_drift")
    audit_outcomes(conn, receipt["scope_id"])
    return dict(core)


def active(
    conn: Any, program_id: str, required: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not conn.execute("SELECT to_regclass('workspace_d5_campaign_successors')").fetchone()[0]:
        return None
    row = conn.execute(
        "SELECT record,authorization_digest,proposal_digest,packet_digest,scope_id,expires_at,extension_id FROM workspace_d5_campaign_successors WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    if not row or required is not None and required != row[2]:
        return None
    receipt, digest, pdigest, packet, scope_id, expiry, extension_id = row
    if (
        _digest(receipt) != digest
        or receipt["campaign_extension"]["proposal_digest"] != pdigest
        or receipt["packet_digest"] != packet
        or receipt["scope_id"] != scope_id
        or datetime.fromisoformat(receipt["expires_at"]) != expiry
        or conn.execute(
            "SELECT 1 FROM workspace_d5_campaign_successor_revocations WHERE extension_id=%s",
            (extension_id,),
        ).fetchone()
    ):
        raise AdmissionError("campaign_v14_revoked_or_receipt_drift")
    return receipt, _validate(conn, receipt, program_id)


def record_external(store: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("approved") is not True:
        raise AdmissionError("campaign_v14_explicit_owner_approval_required")
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
            "SELECT authorization_digest FROM workspace_d5_campaign_successors WHERE program_id=%s",
            (pid,),
        ).fetchone()
        if prior:
            if prior[0] != digest:
                raise AdmissionError("campaign_v14_immutable_no_reapproval")
            return {"authorization_digest": digest, "duplicate": True}
        if proposal(conn, pid, core["plan_digest"])["core"] != core:
            raise AdmissionError("campaign_v14_activation_census_drift")
        conn.execute(
            "INSERT INTO workspace_d5_campaign_successors(program_id,revision,extension_id,predecessor_authorization_digest,proposal_digest,authorization_digest,packet_digest,scope_id,record,expires_at) VALUES(%s,6,%s,%s,%s,%s,%s,%s,%s,%s)",
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
        raise AdmissionError("campaign_v14_exception_scope_mismatch")
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
        raise AdmissionError("campaign_v14_new_external_uncertainty")
    return {
        "retained_exceptions": core["retained_exceptions"],
        "retained_liability_usd": "0.875066",
        "settled": False,
    }
