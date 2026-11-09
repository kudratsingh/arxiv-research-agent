"""Append-only 24->34 jobs / 80->99 counts; capacity never grants a paid stage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.qualification_budget import PROGRAM_LIMITS, census
from src.workspace.store import WorkspaceStore


def _parent(conn: Any, program_id: str) -> tuple[dict[str, Any], str, datetime]:
    from src.workspace.programme_amendments import effective_limits

    row = conn.execute(
        "SELECT record,authorization_digest,expires_at FROM workspace_programme_third_amendments WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    if not row or _digest(row[0]) != row[1]:
        raise AdmissionError("capacity_predecessor_required")
    if effective_limits(conn, program_id, required_proposal_digest=row[0]["proposal_digest"]) != {
        **PROGRAM_LIMITS,
        "new_jobs": 24,
    }:
        raise AdmissionError("capacity_predecessor_policy_drift")
    return row[0], row[1], row[2]


def proposal(conn: Any, program_id: str) -> dict[str, Any]:
    return _proposal(conn, program_id, _parent(conn, program_id))


def _proposal(
    conn: Any, program_id: str, parent_binding: tuple[dict[str, Any], str, datetime]
) -> dict[str, Any]:
    # The caller has already verified this predecessor in the same synchronous
    # operation. Reuse that result instead of recursively auditing it twice.
    # Nothing is cached across operations, transactions or provider contacts.
    parent, auth, expiry = parent_binding
    members = sorted(
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
        )
    )
    history = census(conn, members[0], members=members)
    core = {
        "revision": "programme-capacity-amendment-v4",
        "version": 4,
        "amendment_id": program_id + "-capacity-v4",
        "program_id": program_id,
        "original_authorization_digest": parent["amendment"]["original_authorization_digest"],
        "original_baseline_digest": parent["amendment"]["original_baseline_digest"],
        "predecessor_authorization_digest": auth,
        "predecessor_proposal_digest": parent["proposal_digest"],
        "predecessor_expiry": expiry.isoformat(),
        "prior_limits": {**PROGRAM_LIMITS, "new_jobs": 24},
        "amended_limits": {**PROGRAM_LIMITS, "new_jobs": 34, "counts": 99},
        "basis_members": members,
        "basis": history,
    }
    return {
        "amendment": core,
        "proposal_digest": _digest(core),
        "approved": False,
        "approved_by": None,
        "approved_at": None,
        "expires_at": expiry.isoformat(),
        "authorization_kind": "owner",
        "transport_mode": "provider",
        "authorization_reference": None,
    }


def _validate(conn: Any, receipt: dict[str, Any], program_id: str) -> dict[str, Any]:
    core = receipt.get("amendment", {})
    if not isinstance(core, dict):
        raise AdmissionError("capacity_binding_or_limits_drift")
    parent, auth, expiry = _parent(conn, program_id)
    fixed = _proposal(conn, program_id, (parent, auth, expiry))["amendment"]
    # Historical basis may acquire new jobs after activation; all other bindings are immutable.
    if (
        set(core) != set(fixed)
        or _digest({k: v for k, v in core.items() if k not in {"basis", "basis_members"}})
        != _digest({k: v for k, v in fixed.items() if k not in {"basis", "basis_members"}})
        or receipt.get("proposal_digest") != _digest(core)
    ):
        raise AdmissionError("capacity_binding_or_limits_drift")
    try:
        start = datetime.fromisoformat(receipt["approved_at"])
        end = datetime.fromisoformat(receipt["expires_at"])
        time_ok = (
            start.tzinfo is not None
            and end.tzinfo is not None
            and datetime.fromisoformat(parent["approved_at"]) <= start <= datetime.now(UTC) < end
            and end == expiry
        )
    except (KeyError, TypeError, ValueError):
        time_ok = False
    marker = conn.execute("SELECT data FROM workspace_d5_fixture_marker").fetchone()
    fixture = bool(marker)
    historical_mirror = bool(
        marker and _digest(receipt) in marker[0].get("historical_capacity_authorizations", [])
    )
    if (
        receipt.get("approved") is not True
        or not isinstance(receipt.get("approved_by"), str)
        or not receipt["approved_by"].strip()
        or not isinstance(receipt.get("authorization_reference"), str)
        or not receipt["authorization_reference"].strip()
        or not time_ok
        or receipt.get("authorization_kind")
        != ("offline_fixture" if fixture and not historical_mirror else "owner")
        or receipt.get("transport_mode")
        != ("mock" if fixture and not historical_mirror else "provider")
    ):
        raise AdmissionError("capacity_external_approval_or_expiry_required")
    if (
        not isinstance(core.get("basis"), dict)
        or not isinstance(core.get("basis_members"), list)
        or not core["basis_members"]
        or any(not isinstance(member, str) for member in core["basis_members"])
        or core["basis_members"] != sorted(set(core["basis_members"]))
    ):
        raise AdmissionError("capacity_basis_required")
    return dict(core)


def record_external(store: WorkspaceStore, receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("approved") is not True or not isinstance(receipt.get("amendment"), dict):
        raise AdmissionError("capacity_external_approval_required")
    pid = receipt["amendment"].get("program_id")
    if not isinstance(pid, str):
        raise AdmissionError("capacity_predecessor_required")
    store.migrate()
    with store.pool.connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + str(pid),)
        )
        core = _validate(conn, receipt, pid)
        auth = _digest(receipt)
        old = conn.execute(
            "SELECT authorization_digest FROM workspace_programme_capacity_amendments WHERE program_id=%s",
            (pid,),
        ).fetchone()
        if old:
            if old[0] != auth:
                raise AdmissionError("capacity_immutable_no_reapproval")
            return {"authorization_digest": auth, "duplicate": True}
        current = proposal(conn, pid)["amendment"]
        if _digest(current) != _digest(core):
            raise AdmissionError("capacity_activation_census_drift")
        h = core["basis"]
        if (
            h["active_jobs"]
            or h["uncertain_contacts"]
            or h["pending_usd"] != "0"
            or h["unknown_usd"] != "0"
        ):
            raise AdmissionError("capacity_unresolved_liability")
        conn.execute(
            "INSERT INTO workspace_programme_capacity_amendments(program_id,revision,amendment_id,predecessor_authorization_digest,proposal_digest,authorization_digest,record,expires_at) VALUES(%s,4,%s,%s,%s,%s,%s,%s)",
            (
                pid,
                core["amendment_id"],
                core["predecessor_authorization_digest"],
                receipt["proposal_digest"],
                auth,
                Jsonb(receipt),
                datetime.fromisoformat(receipt["expires_at"]),
            ),
        )
    return {
        "amendment_id": core["amendment_id"],
        "proposal_digest": receipt["proposal_digest"],
        "authorization_digest": auth,
        "effective_jobs": 34,
        "effective_counts": 99,
        "workflow_permission_created": False,
        "provider_contacts": 0,
    }


def effective(
    conn: Any,
    program_id: str,
    parent_limits: dict[str, Any],
    parent_proposal: str,
    required: str | None,
) -> dict[str, Any]:
    if required == parent_proposal:
        return parent_limits
    exists = conn.execute(
        "SELECT to_regclass('workspace_programme_capacity_amendments')"
    ).fetchone()[0]
    row = (
        conn.execute(
            "SELECT record,authorization_digest,proposal_digest,expires_at FROM workspace_programme_capacity_amendments WHERE program_id=%s",
            (program_id,),
        ).fetchone()
        if exists
        else None
    )
    if not row:
        if required:
            raise AdmissionError("programme_amendment_binding_or_revocation")
        return parent_limits
    receipt, auth, digest, expiry = row
    core = _validate(conn, receipt, program_id)
    if (
        _digest(receipt) != auth
        or digest != receipt["proposal_digest"]
        or required
        and required != digest
        or expiry != datetime.fromisoformat(receipt["expires_at"])
        or conn.execute(
            "SELECT 1 FROM workspace_programme_capacity_revocations WHERE amendment_id=%s",
            (core["amendment_id"],),
        ).fetchone()
    ):
        raise AdmissionError("capacity_receipt_or_revocation_drift")
    if (
        census(
            conn,
            core["basis_members"][0],
            members=core["basis_members"],
            job_ids=sorted(core["basis"]["contact_checkpoints"]),
        )
        != core["basis"]
    ):
        raise AdmissionError("capacity_historical_receipts_changed")
    return dict(core["amended_limits"])


def revoke(store: WorkspaceStore, amendment_id: str, *, actor: str) -> None:
    if not isinstance(actor, str) or not actor.strip():
        raise AdmissionError("capacity_revocation_actor_required")
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT program_id FROM workspace_programme_capacity_amendments WHERE amendment_id=%s",
            (amendment_id,),
        ).fetchone()
        if not row:
            raise AdmissionError("capacity_receipt_required")
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + row[0],)
        )
        conn.execute(
            "INSERT INTO workspace_programme_capacity_revocations VALUES(%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING",
            (amendment_id, Jsonb({"revoked_by": actor, "at": datetime.now(UTC).isoformat()})),
        )


def main() -> None:
    import argparse
    import json
    import os
    from pathlib import Path

    from src.workspace.d5_benchmark import database, read, write

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["template", "record", "revoke"])
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    with database(os.environ["D5_POSTGRES_URL"]) as pool:
        store = WorkspaceStore(pool)
        if args.verb == "template":
            with pool.connection() as conn:
                conn.execute("SET TRANSACTION READ ONLY")
                write(args.receipt, proposal(conn, args.program_id))
        else:
            receipt = read(args.receipt)
            if receipt.get("amendment", {}).get("program_id") != args.program_id:
                raise AdmissionError("capacity_binding_or_limits_drift")
            if args.verb == "record":
                print(json.dumps(record_external(store, receipt)))
            else:
                revoke(
                    store,
                    receipt["amendment"]["amendment_id"],
                    actor=receipt.get("approved_by") or "",
                )


if __name__ == "__main__":
    main()
