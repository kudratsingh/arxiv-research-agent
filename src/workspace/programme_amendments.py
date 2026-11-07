"""Append-only programme-specific 20->21 job amendment; never workflow permission.

A proposal is approved=false. Only the separate operator can record an external
approval, confined to MockTransport in a permanently marked fixture database.
Original programme limits, authorization, history and reservations are immutable.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.store import WorkspaceStore

REVISION = "programme-funded-job-amendment-v1"


def _program(conn: Any, program_id: str) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT limits,baseline,authorization_digest,parent_trial_id FROM workspace_evaluation_programs WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    if row is None:
        raise AdmissionError("amendment_original_programme_required")
    return tuple(row)


def proposal(conn: Any, program_id: str) -> dict[str, Any]:
    """Read-only template bound to original authorization and the full census."""
    from src.workspace.qualification_budget import PROGRAM_LIMITS, census

    row = _program(conn, program_id)
    if row[0] != PROGRAM_LIMITS:
        raise AdmissionError("amendment_original_policy_drift")
    members = sorted(
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
        )
    )
    history = census(conn, members[0], members=members)
    core = {
        "revision": REVISION,
        "version": 1,
        "amendment_id": program_id + "-funded-jobs-v1",
        "program_id": program_id,
        "original_authorization_digest": row[2],
        "original_baseline_digest": _digest(row[1]),
        "parent_trial_id": row[3],
        "original_limits": dict(PROGRAM_LIMITS),
        "amended_limits": {**PROGRAM_LIMITS, "new_jobs": 21},
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


def _core(core: dict[str, Any], program_id: str, row: tuple[Any, ...]) -> None:
    from src.workspace.qualification_budget import PROGRAM_LIMITS

    if (
        set(core)
        != {
            "revision",
            "version",
            "amendment_id",
            "program_id",
            "original_authorization_digest",
            "original_baseline_digest",
            "parent_trial_id",
            "original_limits",
            "amended_limits",
            "basis_members",
            "basis",
        }
        or core.get("revision") != REVISION
        or type(core.get("version")) is not int
        or core["version"] != 1
        or core.get("amendment_id") != program_id + "-funded-jobs-v1"
        or core.get("program_id") != program_id
        or row[0] != PROGRAM_LIMITS
        or core.get("original_limits") != PROGRAM_LIMITS
        or core.get("amended_limits") != {**PROGRAM_LIMITS, "new_jobs": 21}
        or core.get("original_authorization_digest") != row[2]
        or core.get("original_baseline_digest") != _digest(row[1])
        or core.get("parent_trial_id") != row[3]
        or not isinstance(core.get("basis"), dict)
        or not isinstance(core.get("basis_members"), list)
        or not core["basis_members"]
        or any(not isinstance(m, str) for m in core["basis_members"])
        or core["basis_members"] != sorted(set(core["basis_members"]))
    ):
        raise AdmissionError("amendment_programme_binding_or_limits_drift")


def _receipt(
    conn: Any, receipt: dict[str, Any], program_id: str, row: tuple[Any, ...], now: datetime
) -> dict[str, Any]:
    core = receipt.get("amendment")
    if not isinstance(core, dict):
        raise AdmissionError("amendment_external_authorization_required")
    _core(core, program_id, row)
    try:
        approved_at = datetime.fromisoformat(receipt["approved_at"])
        expiry = datetime.fromisoformat(receipt["expires_at"])
        valid_time = (
            approved_at.tzinfo is not None
            and expiry.tzinfo is not None
            and approved_at <= now < expiry <= approved_at + timedelta(days=7)
        )
    except (KeyError, ValueError, TypeError):
        valid_time = False
    marker = conn.execute("SELECT data FROM workspace_d5_fixture_marker").fetchone()
    fixture = bool(marker)
    historical_mirror = bool(
        marker and _digest(receipt) in marker[0].get("historical_amendment_authorizations", [])
    )
    if (
        receipt.get("approved") is not True
        or not isinstance(receipt.get("approved_by"), str)
        or not receipt["approved_by"].strip()
        or not isinstance(receipt.get("authorization_reference"), str)
        or not receipt["authorization_reference"].strip()
        or receipt.get("proposal_digest") != _digest(core)
        or not valid_time
        or receipt.get("authorization_kind")
        != ("offline_fixture" if fixture and not historical_mirror else "owner")
        or receipt.get("transport_mode")
        != ("mock" if fixture and not historical_mirror else "provider")
    ):
        raise AdmissionError("amendment_external_authorization_required")
    return core


def record_external(store: WorkspaceStore, receipt: dict[str, Any]) -> dict[str, Any]:
    """No caller-supplied limits can overwrite the original programme policy."""
    from src.workspace.qualification_budget import census

    if receipt.get("approved") is not True or not isinstance(receipt.get("amendment"), dict):
        raise AdmissionError("amendment_external_authorization_required")
    program_id = receipt["amendment"].get("program_id")
    if not isinstance(program_id, str):
        raise AdmissionError("amendment_original_programme_required")
    store.migrate()
    with store.pool.connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + program_id,)
        )
        row = _program(conn, program_id)
        core = _receipt(conn, receipt, program_id, row, datetime.now(UTC))
        digest = _digest(receipt)
        prior = conn.execute(
            "SELECT authorization_digest FROM workspace_programme_amendments WHERE program_id=%s",
            (program_id,),
        ).fetchone()
        if prior:
            if prior[0] != digest:
                raise AdmissionError("amendment_immutable_no_reapproval")
            return {
                "amendment_id": core["amendment_id"],
                "authorization_digest": digest,
                "duplicate": True,
            }
        members = sorted(
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
            )
        )
        history = census(conn, members[0], members=members)
        if members != core["basis_members"] or history != core["basis"]:
            raise AdmissionError("amendment_activation_census_drift")
        if (
            history["active_jobs"]
            or history["uncertain_contacts"]
            or history["pending_usd"] != "0"
            or history["unknown_usd"] != "0"
        ):
            raise AdmissionError("amendment_unresolved_reservation_or_completion")
        conn.execute(
            "INSERT INTO workspace_programme_amendments(program_id,revision,amendment_id,proposal_digest,authorization_digest,record,expires_at) VALUES(%s,1,%s,%s,%s,%s,%s)",
            (
                program_id,
                core["amendment_id"],
                receipt["proposal_digest"],
                digest,
                Jsonb(receipt),
                datetime.fromisoformat(receipt["expires_at"]),
            ),
        )
    return {
        "amendment_id": core["amendment_id"],
        "authorization_digest": digest,
        "proposal_digest": receipt["proposal_digest"],
        "effective_jobs": 21,
        "workflow_permission_created": False,
        "provider_contacts": 0,
    }


def effective_limits(
    conn: Any, program_id: str, *, required_proposal_digest: str | None = None
) -> dict[str, Any]:
    """The default remains20, and all other programmes/caps stay unchanged."""
    from src.workspace.qualification_budget import census

    row = _program(conn, program_id)
    amended = conn.execute(
        "SELECT record,authorization_digest,proposal_digest,expires_at FROM workspace_programme_amendments WHERE program_id=%s",
        (program_id,),
    ).fetchone()
    if not amended:
        if required_proposal_digest:
            raise AdmissionError("required_programme_amendment_not_active")
        return dict(row[0])
    receipt, auth_digest, proposal_digest, expiry = amended
    core = _receipt(conn, receipt, program_id, row, datetime.now(UTC))
    if (
        _digest(receipt) != auth_digest
        or receipt["proposal_digest"] != proposal_digest
        or datetime.fromisoformat(receipt["expires_at"]) != expiry
        or conn.execute(
            "SELECT 1 FROM workspace_programme_amendment_revocations WHERE amendment_id=%s",
            (core["amendment_id"],),
        ).fetchone()
    ):
        raise AdmissionError("programme_amendment_binding_or_revocation")
    historical_ids = sorted(core["basis"]["contact_checkpoints"])
    if (
        census(
            conn, core["basis_members"][0], members=core["basis_members"], job_ids=historical_ids
        )
        != core["basis"]
    ):
        raise AdmissionError("programme_amendment_historical_receipts_changed")
    from src.workspace.programme_successors import effective

    return effective(
        conn, program_id, dict(core["amended_limits"]), proposal_digest, required_proposal_digest
    )


def revoke(store: WorkspaceStore, amendment_id: str, *, actor: str) -> None:
    if not actor.strip():
        raise AdmissionError("amendment_revocation_actor_required")
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT program_id FROM workspace_programme_amendments WHERE amendment_id=%s",
            (amendment_id,),
        ).fetchone()
        if row is None:
            raise AdmissionError("amendment_original_programme_required")
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + row[0],)
        )
        conn.execute(
            "INSERT INTO workspace_programme_amendment_revocations(amendment_id,record) VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (amendment_id, Jsonb({"revoked_by": actor, "at": datetime.now(UTC).isoformat()})),
        )


def main() -> None:
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
        elif args.verb == "record":
            receipt = read(args.receipt)
            if receipt.get("amendment", {}).get("program_id") != args.program_id:
                raise AdmissionError("amendment_programme_binding_or_limits_drift")
            print(json.dumps(record_external(store, receipt)))
        else:
            receipt = read(args.receipt)
            if receipt.get("amendment", {}).get("program_id") != args.program_id:
                raise AdmissionError("amendment_programme_binding_or_limits_drift")
            revoke(
                store, receipt["amendment"]["amendment_id"], actor=receipt.get("approved_by") or ""
            )


if __name__ == "__main__":
    main()
