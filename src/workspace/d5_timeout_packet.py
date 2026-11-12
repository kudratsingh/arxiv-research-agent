"""Blocked prospective deadline proposal. No authority, accounting or provider I/O."""

from __future__ import annotations

import argparse
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_coverage_authority_packet import expected_case as prior_case
from src.workspace.d5_coverage_authority_packet import freeze as prior_freeze
from src.workspace.d5_coverage_packet import measurement_bindings
from src.workspace.d5_deadlines import POLICY

REVISION = "d5-operation-deadlines-development-packet-v1"
PREDECESSOR = "880e4794cd08d26a4a9e63231d5d0d82ec99a267e65ff60dfc5f0994875fb864"
CASE_ID = "development-v11-learn-deadlines"


def capture(store: Any, program_id: str) -> dict[str, Any]:
    """Read-only current baseline, including the overlapping unknown/pending hold."""
    from psycopg import sql

    from src.workspace.d5_coverage_policy import programme
    from src.workspace.d5_fixture import FINANCIAL_TABLES, PUBLIC_TABLES, financial_rows
    from src.workspace.qualification_budget import census
    from src.workspace.schemas import ProfileData

    with store.pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        members = sorted(row[0] for row in conn.execute("SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)))
        history = census(conn, members[0], members=members)
        baseline = conn.execute("SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s", (program_id,)).fetchone()[0]
        if (
            len(set(history["generation_job_ids"]) - set(baseline["generation_job_ids"])) != 33
            or (history["messages"], history["counts"], history["known_usd"], history["pending_usd"], history["unknown_usd"], history["uncertain_contacts"])
            != (65, 90, "1.853811", "0.425066", "0.425066", True)
            or history["active_jobs"]
        ):
            raise AdmissionError("d5_timeout_expected_uncertain_baseline_required")
        tables = {name: [row[0] for row in conn.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(name)))] for name in PUBLIC_TABLES}
        if any(row["visibility_owner"] is not None for row in tables["workspace_works"]):
            raise AdmissionError("d5_timeout_public_sources_only")
        for name in FINANCIAL_TABLES:
            tables[name] = financial_rows(conn, name)
        extras = {key: [row[0] for row in conn.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(table)))] for table, key in [
            ("workspace_programme_amendments", "recorded_amendments"),
            ("workspace_programme_successor_amendments", "recorded_successor_amendments"),
            ("workspace_programme_third_amendments", "recorded_third_amendments"),
            ("workspace_programme_capacity_amendments", "recorded_capacity_amendments"),
            ("workspace_d5_scopes", "historical_scopes"),
            ("workspace_d5_stage_authorizations", "historical_stage_grants"),
        ]}
        binding = programme(conn, program_id)
    return {"tables": tables, **extras, "programme": binding, "history": history, "program_id": program_id, "profile": ProfileData().model_dump(mode="json"), "profile_authority": "Unused synthetic storage profile; no owner preference imported", "provenance": "Read-only unresolved accounting and retained public context. Pending and unknown are the same hold; no reconciliation or authority created."}


def expected_case(corpus: list[dict[str, Any]]) -> dict[str, Any]:
    case = prior_case(corpus)
    return {**case, "id": CASE_ID, "predecessor_case": "development-v10-learn-coverage", "prior_outcome": "uncertain Opus check; original draft, contact and hold preserved"}


def blocked(history: dict[str, Any]) -> bool:
    from decimal import Decimal

    return bool(history["uncertain_contacts"] or history["active_jobs"] or any(Decimal(history[k]) for k in ("pending_usd", "unknown_usd")))


def verify_timeout(packet: dict[str, Any]) -> None:
    from datetime import datetime

    from anthropic import transform_schema

    from src.workspace.assistance import CoverageChecks
    from src.workspace.d5_coverage_policy import PROGRAM_LIMITS, SHAPED_LIMITS, SHAPED_PROFILE
    from src.workspace.d5_operations import ROUTES

    if (
        packet.get("revision") != REVISION
        or packet.get("predecessor_packet") != PREDECESSOR
        or packet.get("operation_deadlines") != POLICY
        or packet.get("reconciliation_required") is not blocked(packet["history"])
        or packet.get("planned_development_cases") != [CASE_ID]
        or packet.get("measurement_cases") != [CASE_ID]
        or packet.get("cases") != [expected_case(packet["corpus"])]
        or packet.get("measurements") != measurement_bindings(packet["cases"])
        or packet.get("measurement_reuse") != []
        or packet.get("probes") != []
        or packet.get("scope_profile") != SHAPED_PROFILE
        or packet.get("limits") != SHAPED_LIMITS
        or packet.get("operation_routes") != ROUTES
        or packet.get("checker_schemas") != {"local": CoverageChecks.model_json_schema(), "wire": transform_schema(CoverageChecks)}
        or packet["programme"]["limits"] != PROGRAM_LIMITS
        or packet["programme"]["capacity_proposal_digest"] != packet["programme_amendment"]["proposal_digest"]
        or packet["programme"]["program_id"] != packet["program_id"]
        or packet.get("human_qualification") is not False
    ):
        raise AdmissionError("d5_timeout_proposal_binding_drift")
    if datetime.fromisoformat(packet["programme"]["expires_at"]).tzinfo is None:
        raise AdmissionError("d5_timeout_programme_expiry_required")


def freeze(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Unknown liability is preserved and blocks activation, never reset to zero."""
    packet = prior_freeze(snapshot)
    packet.update(
        revision=REVISION,
        predecessor_packet=PREDECESSOR,
        cases=[expected_case(packet["corpus"])],
        planned_development_cases=[CASE_ID],
        measurement_cases=[CASE_ID],
        operation_deadlines=deepcopy(POLICY),
        reconciliation_required=blocked(snapshot["history"]),
        follow_up="One fresh development case only after authoritative uncertainty reconciliation, resealed history and separate owner approvals. Never resume/replay stopped v10.",
    )
    packet.pop("packet_digest", None)
    packet["measurements"] = measurement_bindings(packet["cases"])
    packet["packet_digest"] = _digest(packet)
    verify_timeout(packet)
    return packet


def main() -> None:
    from src.workspace.d5_benchmark import database, read, write
    from src.workspace.store import WorkspaceStore

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    if os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled" or os.environ.get("WORKSPACE_D5_OFFLINE") != "1":
        raise AdmissionError("d5_timeout_proposal_offline_only")
    if args.capture:
        with database(os.environ["D5_LEDGER_POSTGRES_URL"]) as pool:
            write(args.snapshot, capture(WorkspaceStore(pool), "research-evaluation-20261105-v1"))
    else:
        if args.packet is None:
            parser.error("--packet required to freeze")
        write(args.packet, freeze(read(args.snapshot)))


if __name__ == "__main__":
    main()
