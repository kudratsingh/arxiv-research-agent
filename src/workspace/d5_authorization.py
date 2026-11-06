"""Separate operator recorder for explicit D5 authorizations; never a runner.

A proposal/credential cannot authorize dispatch. The benchmark execution module
never calls this writer. Offline synthetic authorization is further confined by
an irrevocable fixture-database marker and MockTransport policy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_scope import LIMITS, stage_authorizations
from src.workspace.qualification_budget import census
from src.workspace.store import WorkspaceStore


def case_bindings(compiled: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        key: {
            "owner": entry["owner"],
            "input_digest": _digest(entry["input"]),
            "operation": entry["input"]["settings"]["d5_operation"],
            "stage": entry["stage"],
        }
        for key, entry in compiled.items()
    }


def record_external(
    store: WorkspaceStore,
    *,
    packet_digest: str,
    scope_id: str,
    program_id: str,
    compiled: dict[str, dict[str, Any]],
    receipt: dict[str, Any],
    expected_history: dict[str, Any],
) -> dict[str, Any]:
    """Record only an independently supplied, exact, effective authorization.

    No defaults turn approved=false into true. Source/project preparation and
    exporting a template are separate from this permission-changing operation.
    """
    bindings = case_bindings(compiled)
    members = sorted({entry["owner"] for entry in compiled.values()})
    try:
        approved_at = datetime.fromisoformat(receipt["approved_at"])
        expires = datetime.fromisoformat(receipt["expires_at"])
    except (KeyError, ValueError, TypeError) as exc:
        raise AdmissionError("d5_external_authorization_required") from exc
    if (
        receipt.get("approved") is not True
        or not isinstance(receipt.get("approved_by"), str)
        or not receipt["approved_by"].strip()
        or receipt.get("packet_digest") != packet_digest
        or receipt.get("scope_id") != scope_id
        or receipt.get("limits") != LIMITS
        or receipt.get("members") != members
        or receipt.get("case_bindings_digest") != _digest(bindings)
        or receipt.get("transport_mode") not in {"mock", "provider"}
        or not isinstance(receipt.get("stages"), list)
        or not receipt["stages"]
        or set(receipt["stages"]) - {"A", "B", "C", "D"}
        or approved_at.tzinfo is None
        or expires.tzinfo is None
        or not approved_at <= datetime.now(UTC) < expires <= approved_at + timedelta(days=7)
    ):
        raise AdmissionError("d5_external_authorization_required")
    store.migrate()
    auth_digest = _digest(receipt)
    if any(not member.startswith("d5-") for member in members):
        raise AdmissionError("d5_isolated_principals_required")
    with store.pool.connection() as conn:
        for member in members:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("generation:" + member,)
            )
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("d5:" + scope_id,))
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + program_id,)
        )
        fixture = conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone()
        if (
            (
                receipt["transport_mode"] == "provider"
                and (fixture or receipt.get("authorization_kind") != "owner")
            )
            or receipt["transport_mode"] == "mock"
            and (not fixture or receipt.get("authorization_kind") != "offline_fixture")
        ):
            raise AdmissionError("d5_authorization_transport_or_fixture_mismatch")
        program = conn.execute(
            "SELECT authorization_digest FROM workspace_evaluation_programs WHERE program_id=%s",
            (program_id,),
        ).fetchone()
        if program is None:
            raise AdmissionError("d5_preserved_program_required")
        prior = conn.execute(
            "SELECT packet_digest,authorization_digest,data FROM workspace_d5_scopes WHERE scope_id=%s",
            (scope_id,),
        ).fetchone()
        if prior:
            if prior[:2] != (packet_digest, auth_digest):
                raise AdmissionError("d5_scope_authorization_immutable")
            return {"scope_id": scope_id, "authorization_digest": auth_digest, "duplicate": True}
        old_members = [
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
            )
        ]
        history = census(conn, old_members[0], members=old_members)
        if any(
            history.get(k) != expected_history.get(k)
            for k in (
                "history_digest",
                "messages",
                "counts",
                "known_usd",
                "unknown_usd",
                "pending_usd",
                "contact_checkpoints",
                "generation_job_ids",
            )
        ):
            raise AdmissionError("d5_historical_ledger_drift")
        if (
            history["uncertain_contacts"]
            or history["active_jobs"]
            or history["unknown_usd"] != "0"
            or history["pending_usd"] != "0"
        ):
            raise AdmissionError("d5_historical_liability_requires_reconciliation")
        if any(
            conn.execute(
                "SELECT 1 FROM workspace_generation_jobs WHERE owner=%s", (member,)
            ).fetchone()
            for member in members
        ):
            raise AdmissionError("d5_new_members_must_have_empty_financial_ledgers")
        data = {
            "limits": LIMITS,
            "members": members,
            "stages": receipt["stages"],
            "cases": bindings,
            "baseline": history,
            "authorization_record": receipt,
            "program_id": program_id,
        }
        conn.execute(
            "INSERT INTO workspace_d5_scopes(scope_id,packet_digest,authorization_digest,data,state,expires_at)VALUES(%s,%s,%s,%s,'active',%s)",
            (scope_id, packet_digest, auth_digest, Jsonb(data), expires),
        )
        # Programme membership and fixed generic policy rows grant no broader scope:
        # D5Admission requires the exact external scope/case bindings on every call.
        for member in members:
            membership = conn.execute(
                "SELECT program_id FROM workspace_evaluation_members WHERE owner=%s", (member,)
            ).fetchone()
            if membership and membership[0] != program_id:
                raise AdmissionError("d5_principal_already_bound_to_another_program")
            if not membership:
                conn.execute(
                    "INSERT INTO workspace_evaluation_members VALUES(%s,%s)", (member, program_id)
                )
            policy = {
                "approved": True,
                "model_ids": ["claude-sonnet-5-5"],
                "source_scopes": ["abstract", "excerpt"],
                "per_job_usd": "0.40",
                "day_usd": "10",
                "month_usd": "10",
                "valid_from": approved_at.isoformat(),
                "expires_at": expires.isoformat(),
                "approval_record": {
                    "approval_id": scope_id + "-" + member,
                    "approved_by": receipt["approved_by"],
                    "approved_at": approved_at.isoformat(),
                },
                "purpose": "workspace-d5-qualification-only",
                "transport_mode": receipt["transport_mode"],
                "everyday_generation": False,
                "program_id": program_id,
                "program_authorization_digest": program[0],
                "d5_scope_id": scope_id,
                "d5_authorization_digest": auth_digest,
            }
            conn.execute(
                "INSERT INTO workspace_budget_policies VALUES(%s,%s,%s)",
                (member, policy["approval_record"]["approval_id"], Jsonb(policy)),
            )
    return {
        "scope_id": scope_id,
        "authorization_digest": auth_digest,
        "approved_by": receipt["approved_by"],
        "provider_contacts": 0,
    }


def revoke(store: WorkspaceStore, scope_id: str) -> None:
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_d5_scopes SET state='revoked' WHERE scope_id=%s", (scope_id,)
        )


def stage_template(store: WorkspaceStore, scope_id: str, stages: list[str]) -> dict[str, Any]:
    """Read-only review artifact. A later receipt must be independently approved."""
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT packet_digest,authorization_digest,data,expires_at FROM workspace_d5_scopes WHERE scope_id=%s",
            (scope_id,),
        ).fetchone()
        if not row:
            raise AdmissionError("d5_parent_authorization_required")
        members = [
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
                (row[2]["program_id"],),
            )
        ]
        history = census(conn, members[0], members=members)
    return {
        "approved": False,
        "approved_by": None,
        "approved_at": None,
        "expires_at": row[3].isoformat(),
        "grant_id": "d5-grant-" + row[0][:16] + "-" + "".join(stages),
        "scope_id": scope_id,
        "packet_digest": row[0],
        "parent_authorization_digest": row[1],
        "limits": LIMITS,
        "members": row[2]["members"],
        "case_bindings_digest": _digest(row[2]["cases"]),
        "basis_history_digest": history["history_digest"],
        "transport_mode": row[2]["authorization_record"]["transport_mode"],
        "authorization_kind": row[2]["authorization_record"]["authorization_kind"],
        "stages": stages,
    }


def grant_external(store: WorkspaceStore, scope_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    """Append a separately approved stage, never rewrite/renew the base receipt."""
    try:
        approved_at = datetime.fromisoformat(receipt["approved_at"])
        expiry = datetime.fromisoformat(receipt["expires_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AdmissionError("d5_external_stage_authorization_required") from exc
    now = datetime.now(UTC)
    if (
        receipt.get("approved") is not True
        or not isinstance(receipt.get("approved_by"), str)
        or not receipt["approved_by"].strip()
        or receipt.get("scope_id") != scope_id
        or not isinstance(receipt.get("grant_id"), str)
        or not receipt["grant_id"].startswith("d5-grant-")
        or len(receipt["grant_id"]) > 120
        or not isinstance(receipt.get("stages"), list)
        or not receipt["stages"]
        or any(s not in {"B", "C", "D"} for s in receipt["stages"])
        or len(set(receipt["stages"])) != len(receipt["stages"])
        or approved_at.tzinfo is None
        or expiry.tzinfo is None
        or not approved_at <= now < expiry <= approved_at + timedelta(days=7)
    ):
        raise AdmissionError("d5_external_stage_authorization_required")
    digest = _digest(receipt)
    with store.pool.connection() as conn:
        parent = conn.execute(
            "SELECT data FROM workspace_d5_scopes WHERE scope_id=%s", (scope_id,)
        ).fetchone()
        if not parent:
            raise AdmissionError("d5_parent_authorization_required")
        for member in sorted(parent[0]["members"]):
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("generation:" + member,)
            )
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("d5:" + scope_id,))
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ("evaluation:" + parent[0]["program_id"],),
        )
        row = conn.execute(
            "SELECT packet_digest,authorization_digest,data,state,expires_at FROM workspace_d5_scopes WHERE scope_id=%s FOR UPDATE",
            (scope_id,),
        ).fetchone()
        if row is None or row[3] != "active" or not now < expiry <= row[4]:
            raise AdmissionError("d5_parent_scope_inactive_or_expiry_extended")
        data = row[2]
        if (
            receipt.get("packet_digest") != row[0]
            or receipt.get("parent_authorization_digest") != row[1]
            or receipt.get("limits") != LIMITS
            or receipt.get("members") != data["members"]
            or receipt.get("case_bindings_digest") != _digest(data["cases"])
            or receipt.get("transport_mode") != data["authorization_record"]["transport_mode"]
            or receipt.get("authorization_kind")
            != data["authorization_record"]["authorization_kind"]
            or _digest(data["authorization_record"]) != row[1]
        ):
            raise AdmissionError("d5_stage_parent_binding_drift")
        fixture = conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone()
        if bool(fixture) != (receipt["transport_mode"] == "mock"):
            raise AdmissionError("d5_authorization_transport_or_fixture_mismatch")
        prior = conn.execute(
            "SELECT authorization_digest FROM workspace_d5_stage_authorizations WHERE scope_id=%s AND grant_id=%s",
            (scope_id, receipt["grant_id"]),
        ).fetchone()
        if prior:
            if prior[0] != digest:
                raise AdmissionError("d5_stage_authorization_immutable")
            return {
                "grant_id": receipt["grant_id"],
                "authorization_digest": digest,
                "duplicate": True,
            }
        allowed = stage_authorizations(conn, scope_id, data, row[1], row[4], now)
        if set(receipt["stages"]) & allowed.keys():
            raise AdmissionError("d5_stage_already_authorized")
        members = [
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
                (data["program_id"],),
            )
        ]
        history = census(conn, members[0], members=members)
        if history["history_digest"] != receipt.get("basis_history_digest"):
            raise AdmissionError("d5_stage_accounting_basis_drift")
        if (
            history["active_jobs"]
            or history["uncertain_contacts"]
            or Decimal(history["unknown_usd"])
            or Decimal(history["pending_usd"])
        ):
            raise AdmissionError("d5_stage_unresolved_liability")
        conn.execute(
            "INSERT INTO workspace_d5_stage_authorizations(scope_id,grant_id,authorization_digest,record,expires_at) VALUES(%s,%s,%s,%s,%s)",
            (scope_id, receipt["grant_id"], digest, Jsonb(receipt), expiry),
        )
    return {
        "grant_id": receipt["grant_id"],
        "authorization_digest": digest,
        "stages": receipt["stages"],
        "provider_contacts": 0,
    }
