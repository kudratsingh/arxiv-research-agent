"""Independent21->22 proposal/receipt; preserves predecessor and cannot extend it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.qualification_budget import PROGRAM_LIMITS, census
from src.workspace.store import WorkspaceStore


def _parent(conn: Any, program_id: str) -> tuple[dict[str, Any], str, datetime]:
    row = conn.execute(
        "SELECT record,authorization_digest,expires_at FROM workspace_programme_amendments WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    if not row or _digest(row[0]) != row[1]:
        raise AdmissionError("successor_predecessor_required")
    from src.workspace.programme_amendments import effective_limits

    assert row[0]["amendment"]["version"] == 1
    limits = effective_limits(conn, program_id, required_proposal_digest=row[0]["proposal_digest"])
    if limits != {**PROGRAM_LIMITS, "new_jobs": 21}:
        raise AdmissionError("successor_predecessor_policy_drift")
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
        "revision": "programme-funded-job-amendment-v2",
        "version": 2,
        "amendment_id": program_id + "-funded-jobs-v2",
        "program_id": program_id,
        "original_authorization_digest": parent["amendment"]["original_authorization_digest"],
        "original_baseline_digest": parent["amendment"]["original_baseline_digest"],
        "predecessor_authorization_digest": auth,
        "predecessor_proposal_digest": parent["proposal_digest"],
        "predecessor_expiry": expiry.isoformat(),
        "prior_limits": {**PROGRAM_LIMITS, "new_jobs": 21},
        "amended_limits": {**PROGRAM_LIMITS, "new_jobs": 22},
        "basis_members": members,
        "basis": history,
    }
    return {
        "amendment": core,
        "proposal_digest": _digest(core),
        "approved": False,
        "approved_by": None,
        "approved_at": None,
        "expires_at": None,
        "authorization_kind": "owner",
        "transport_mode": "provider",
        "authorization_reference": None,
    }


def _validate(conn: Any, receipt: dict[str, Any], program_id: str) -> dict[str, Any]:
    core = receipt.get("amendment", {})
    if not isinstance(core, dict):
        raise AdmissionError("successor_binding_or_limits_drift")
    parent, auth, expiry = _parent(conn, program_id)
    fixed = _proposal(conn, program_id, (parent, auth, expiry))["amendment"]
    # Historical basis may acquire new jobs after activation; all other bindings are immutable.
    if (
        set(core) != set(fixed)
        or any(core.get(k) != v for k, v in fixed.items() if k not in {"basis", "basis_members"})
        or receipt.get("proposal_digest") != _digest(core)
    ):
        raise AdmissionError("successor_binding_or_limits_drift")
    try:
        start = datetime.fromisoformat(receipt["approved_at"])
        end = datetime.fromisoformat(receipt["expires_at"])
        time_ok = (
            start.tzinfo is not None
            and end.tzinfo is not None
            and start <= datetime.now(UTC) < end <= min(start + timedelta(days=7), expiry)
        )
    except (KeyError, TypeError, ValueError):
        time_ok = False
    marker = conn.execute("SELECT data FROM workspace_d5_fixture_marker").fetchone()
    fixture = bool(marker)
    historical_mirror = bool(
        marker and _digest(receipt) in marker[0].get("historical_successor_authorizations", [])
    )
    if (
        receipt.get("approved") is not True
        or not receipt.get("approved_by")
        or not receipt.get("authorization_reference")
        or not time_ok
        or receipt.get("authorization_kind")
        != ("offline_fixture" if fixture and not historical_mirror else "owner")
        or receipt.get("transport_mode")
        != ("mock" if fixture and not historical_mirror else "provider")
    ):
        raise AdmissionError("successor_external_approval_or_expiry_required")
    if (
        not isinstance(core.get("basis"), dict)
        or not isinstance(core.get("basis_members"), list)
        or not core["basis_members"]
    ):
        raise AdmissionError("successor_basis_required")
    return dict(core)


def record_external(store: WorkspaceStore, receipt: dict[str, Any]) -> dict[str, Any]:
    if receipt.get("approved") is not True or not isinstance(receipt.get("amendment"), dict):
        raise AdmissionError("successor_external_approval_required")
    pid = receipt["amendment"].get("program_id")
    store.migrate()
    with store.pool.connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + str(pid),)
        )
        core = _validate(conn, receipt, pid)
        auth = _digest(receipt)
        old = conn.execute(
            "SELECT authorization_digest FROM workspace_programme_successor_amendments WHERE program_id=%s",
            (pid,),
        ).fetchone()
        if old:
            if old[0] != auth:
                raise AdmissionError("successor_immutable_no_reapproval")
            return {"authorization_digest": auth, "duplicate": True}
        current = proposal(conn, pid)["amendment"]
        if current != core:
            raise AdmissionError("successor_activation_census_drift")
        h = core["basis"]
        if (
            h["active_jobs"]
            or h["uncertain_contacts"]
            or h["pending_usd"] != "0"
            or h["unknown_usd"] != "0"
        ):
            raise AdmissionError("successor_unresolved_liability")
        conn.execute(
            "INSERT INTO workspace_programme_successor_amendments(program_id,revision,amendment_id,predecessor_authorization_digest,proposal_digest,authorization_digest,record,expires_at) VALUES(%s,2,%s,%s,%s,%s,%s,%s)",
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
        "effective_jobs": 22,
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
        "SELECT to_regclass('workspace_programme_successor_amendments')"
    ).fetchone()[0]
    row = (
        conn.execute(
            "SELECT record,authorization_digest,proposal_digest,expires_at FROM workspace_programme_successor_amendments WHERE program_id=%s",
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
        or expiry != datetime.fromisoformat(receipt["expires_at"])
        or conn.execute(
            "SELECT 1 FROM workspace_programme_successor_revocations WHERE amendment_id=%s",
            (core["amendment_id"],),
        ).fetchone()
    ):
        raise AdmissionError("successor_receipt_or_revocation_drift")
    if (
        census(
            conn,
            core["basis_members"][0],
            members=core["basis_members"],
            job_ids=sorted(core["basis"]["contact_checkpoints"]),
        )
        != core["basis"]
    ):
        raise AdmissionError("successor_historical_receipts_changed")
    if required == digest:
        return dict(core["amended_limits"])
    from src.workspace.programme_third_amendment import effective as third_effective

    return third_effective(conn, program_id, dict(core["amended_limits"]), digest, required)


def revoke(store: WorkspaceStore, amendment_id: str, *, actor: str) -> None:
    if not actor.strip():
        raise AdmissionError("successor_revocation_actor_required")
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT program_id FROM workspace_programme_successor_amendments WHERE amendment_id=%s",
            (amendment_id,),
        ).fetchone()
        if not row:
            raise AdmissionError("successor_receipt_required")
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + row[0],)
        )
        conn.execute(
            "INSERT INTO workspace_programme_successor_revocations VALUES(%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING",
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
                raise AdmissionError("successor_binding_or_limits_drift")
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
