"""Separate operator permission recorder. Never imported by the paid runner.

Templates are approved=false. An independently supplied explicit owner receipt
is mandatory; neither a key nor an existing programme grants this new scope.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.workspace.admission import _digest
from src.workspace.d5_authorization import (
    case_bindings,
    grant_external,
    record_external,
    revoke,
    stage_template,
)
from src.workspace.d5_benchmark import database, read, write
from src.workspace.d5_freeze import compile_inputs
from src.workspace.store import WorkspaceStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "verb", choices=["template", "prepare", "record", "stage-template", "grant", "revoke"]
    )
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--stages",
        help="Comma-separated predeclared stage names; template defaults A, stage-template B",
    )
    args = parser.parse_args()
    packet = read(args.packet)
    compiled = compile_inputs(packet)
    scope_id = "d5-" + packet["packet_digest"][:24]
    if args.verb == "template":
        write(
            args.receipt,
            {
                "approved": False,
                "approved_by": None,
                "approved_at": None,
                "expires_at": None,
                "authorization_kind": "owner",
                "transport_mode": "provider",
                "packet_digest": packet["packet_digest"],
                "scope_id": scope_id,
                "limits": packet["limits"],
                "members": sorted({v["owner"] for v in compiled.values()}),
                "case_bindings_digest": _digest(case_bindings(compiled)),
                "stages": (args.stages or "A").split(","),
            },
        )
        return
    with database(os.environ["D5_POSTGRES_URL"]) as pool:
        store = WorkspaceStore(pool)
        store.migrate()
        if args.verb == "prepare":
            from datetime import datetime

            from src.workspace.admission import AdmissionError
            from src.workspace.d5_benchmark import check_storage
            from src.workspace.d5_coverage_packet import is_packet
            from src.workspace.d5_coverage_policy import validate_programme
            from src.workspace.d5_fixture import prepare_projects
            from src.workspace.qualification_budget import census

            if not is_packet(packet):
                raise AdmissionError("coverage_prepare_requires_development_packet")
            check_storage(store, packet)
            with pool.connection() as conn:
                validate_programme(
                    conn,
                    packet["program_id"],
                    packet["programme"],
                    datetime.fromisoformat(packet["programme"]["expires_at"]),
                )
                members = [
                    r[0]
                    for r in conn.execute(
                        "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
                        (packet["program_id"],),
                    )
                ]
                history = census(conn, members[0], members=members)
                if history != packet["history"]:
                    raise AdmissionError("d5_historical_ledger_drift")
            prepare_projects(store, packet)
            write(
                args.receipt,
                {
                    "prepared": sorted({e["owner"] for e in compiled.values()}),
                    "packet_digest": packet["packet_digest"],
                    "scope_id": scope_id,
                    "history_digest": history["history_digest"],
                    "approval_created": False,
                    "provider_contacts": 0,
                },
            )
        elif args.verb == "stage-template":
            write(args.receipt, stage_template(store, scope_id, (args.stages or "B").split(",")))
        elif args.verb == "grant":
            print(json.dumps(grant_external(store, scope_id, read(args.receipt))))
        elif args.verb == "revoke":
            revoke(store, scope_id)
            print(json.dumps({"revoked": scope_id, "provider_contacts": 0}))
        else:
            print(
                json.dumps(
                    record_external(
                        store,
                        packet_digest=packet["packet_digest"],
                        scope_id=scope_id,
                        program_id=packet["program_id"],
                        compiled=compiled,
                        receipt=read(args.receipt),
                        expected_history=packet["history"],
                    )
                )
            )


if __name__ == "__main__":
    main()
