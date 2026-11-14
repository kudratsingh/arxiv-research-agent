"""One external campaign receipt records capacity, quarantine policy and B/C/D.

No provider dispatch. A template stays unapproved. The runner never calls the
owner recorder; synthetic fixtures are confined to irreversibly marked storage.
"""

from __future__ import annotations

import argparse
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.workspace.admission import AdmissionError, _digest


def template(packet: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_authorization import case_bindings
    from src.workspace.d5_freeze import compile_inputs, verify

    verify(packet)
    compiled = compile_inputs(packet)
    value = deepcopy(
        {
            "approved": False,
            "approved_by": None,
            "approved_at": None,
            "approval_source": None,
            "expires_at": packet["programme"]["expires_at"],
            "authorization_kind": "owner",
            "transport_mode": "provider",
            "packet_digest": packet["packet_digest"],
            "scope_id": "d5-" + packet["packet_digest"][:24],
            "limits": packet["limits"],
            "members": sorted({e["owner"] for e in compiled.values()}),
            "stages": ["B", "C", "D"],
            "case_order": list(compiled),
            "case_bindings_digest": _digest(case_bindings(compiled)),
            "code_bindings": packet["code"],
            "adapter_binding": packet["adapter"],
            "source_bindings": packet["source_bindings"],
            "campaign_extension": packet["campaign_extension"],
            "capacity_amendment_approved": False,
            "historical_uncertainty_exception_approved": False,
        }
    )
    if packet.get("revision") == "d5-complete-machine-campaign-v14":
        value["budget_adjustment_approved"] = False
    if packet.get("revision") == "d5-comprehensive-machine-campaign-v15":
        value.update(budget_adjustment_approved=False, expiry_adjustment_approved=False,
                     programme_expires_at=None, expires_at=None)
    return value


def record(store: Any, packet: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_authorization import record_external
    from src.workspace.d5_benchmark import check_storage
    from src.workspace.d5_campaign_extension import record_external as activate
    from src.workspace.d5_fixture import prepare_projects
    from src.workspace.d5_freeze import compile_inputs

    expected = template(packet)
    mutable = {
        "approved",
        "approved_by",
        "approved_at",
        "approval_source",
        "expires_at",
        "authorization_kind",
        "transport_mode",
        "capacity_amendment_approved",
        "historical_uncertainty_exception_approved",
    }
    if "budget_adjustment_approved" in expected:
        mutable.add("budget_adjustment_approved")
    if "expiry_adjustment_approved" in expected:
        mutable.update({"expiry_adjustment_approved", "programme_expires_at"})
    if set(receipt) != set(expected) or any(
        receipt[k] != expected[k] for k in expected if k not in mutable
    ):
        raise AdmissionError("campaign_authorization_packet_binding_drift")
    if (
        receipt.get("approved") is not True
        or not receipt.get("approved_by")
        or not receipt.get("approval_source")
        or receipt.get("capacity_amendment_approved") is not True
        or receipt.get("historical_uncertainty_exception_approved") is not True
        or "budget_adjustment_approved" in expected
        and receipt.get("budget_adjustment_approved") is not True
    ):
        raise AdmissionError("campaign_explicit_consolidated_owner_approval_required")
    check_storage(store, packet)
    activated = activate(store, receipt)
    # Capacity/quarantine alone grant no provider path. The existing exact-input
    # scope recorder below must also succeed. Repeating this exact receipt does
    # not renew it; partial activation remains fail-closed and inspectable.
    prepare_projects(store, packet)
    scope = record_external(
        store,
        packet_digest=packet["packet_digest"],
        scope_id=receipt["scope_id"],
        program_id=packet["program_id"],
        compiled=compile_inputs(packet),
        receipt=receipt,
        expected_history=packet["history"],
    )
    return {
        "activation": activated,
        "scope": scope,
        "provider_contacts": 0,
        "expires_at": receipt["expires_at"],
    }


def authorize_fixture(store: Any, packet: dict[str, Any]) -> dict[str, Any]:
    with store.pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone():
            raise AdmissionError("campaign_fixture_database_required")
    if (
        os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
        or os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
    ):
        raise AdmissionError("campaign_offline_disabled_key_required")
    value = template(packet)
    now = datetime.now(UTC)
    value.update(
        approved=True,
        approved_by="Synthetic disposable fixture, not owner approval",
        approved_at=now.isoformat(),
        approval_source="Offline fixture only",
        expires_at=min(
            now + timedelta(hours=23), datetime.fromisoformat(packet["programme"]["expires_at"]) if packet.get("revision") != "d5-comprehensive-machine-campaign-v15" else now + timedelta(hours=23)
        ).isoformat(),
        authorization_kind="offline_fixture",
        transport_mode="mock",
        capacity_amendment_approved=True,
        historical_uncertainty_exception_approved=True,
    )
    if "budget_adjustment_approved" in value:
        value["budget_adjustment_approved"] = True
    if packet.get("revision") == "d5-comprehensive-machine-campaign-v15":
        value.update(expiry_adjustment_approved=True, programme_expires_at=(now + timedelta(days=7)).isoformat(), expires_at=(now + timedelta(hours=23)).isoformat())
    return record(store, packet, value)


def revoke(store: Any, packet: dict[str, Any], authorization: dict[str, Any]) -> dict[str, Any]:
    """Explicit operator revocation follows the selected append-only revision."""
    from psycopg.types.json import Jsonb

    if authorization.get("packet_digest") != packet["packet_digest"] or not authorization.get(
        "approved_by"
    ):
        raise AdmissionError("campaign_revocation_attribution_required")
    prospective = packet.get("revision") == "d5-complete-machine-campaign-v14"
    if prospective and authorization.get("scope_id") != "d5-" + packet["packet_digest"][:24]:
        raise AdmissionError("campaign_revocation_scope_binding_required")
    capacity = packet.get("revision") == "d5-comprehensive-machine-campaign-v15"
    if capacity and authorization.get("scope_id") != "d5-" + packet["packet_digest"][:24]:
        raise AdmissionError("campaign_revocation_scope_binding_required")
    statement = (
        "INSERT INTO workspace_d5_capacity_revision_revocations VALUES(%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING"
        if capacity else
        "INSERT INTO workspace_d5_campaign_successor_revocations VALUES(%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING"
        if prospective
        else "INSERT INTO workspace_d5_campaign_revocations VALUES(%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING"
    )
    with store.pool.connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ("evaluation:" + packet["program_id"],),
        )
        conn.execute(
            statement,
            (
                packet["campaign_extension"]["core"]["extension_id"],
                Jsonb(
                    {
                        "revoked_by": authorization["approved_by"],
                        "at": datetime.now(UTC).isoformat(),
                    }
                ),
            ),
        )
    return {"revoked": True, "provider_contacts": 0}


def main() -> None:
    from src.workspace.d5_benchmark import database, read, write
    from src.workspace.store import WorkspaceStore

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["template", "record", "revoke"])
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    packet = read(args.packet)
    if args.verb == "template":
        write(args.authorization, template(packet))
        return
    if args.receipt is None:
        parser.error("record/revoke requires --receipt")
    with database(os.environ["D5_POSTGRES_URL"]) as pool:
        store = WorkspaceStore(pool)
        if args.verb == "record":
            write(args.receipt, record(store, packet, read(args.authorization)))
        else:
            authorization = read(args.authorization)
            write(args.receipt, revoke(store, packet, authorization))


if __name__ == "__main__":
    main()
