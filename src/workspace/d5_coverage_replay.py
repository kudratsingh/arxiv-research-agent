"""Offline-only packet preparation and disposable production-adapter replay.

Synthetic A/B permission exists only in a fixture-marked database. Provider mode
uses d5_operator and d5_benchmark, never this permission-fixture path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from psycopg import sql

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_coverage_packet import CASE_IDS, freeze_controls, is_packet
from src.workspace.d5_coverage_policy import programme


class CoverageTransport:
    """Unqualified, wire-shaped fixtures. Counts/usage are synthetic, not measured."""

    def __init__(self, case_id: str, *, repair_all: bool = False):
        self.case_id, self.repair_all, self.checks = case_id, repair_all, 0
        self.contacts: list[dict[str, str]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        from src.workspace.assistance import LocalAssistanceTransport

        body = json.loads(request.content)
        self.contacts.append({"endpoint": request.url.path, "digest": _digest(body)})
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        context = json.loads(body["messages"][0]["content"])
        response = LocalAssistanceTransport.fixture(request).json()
        payload = json.loads(response["content"][0]["text"])
        learn = self.case_id in {CASE_IDS[0], "development-v9-learn-coverage", "development-v10-learn-coverage"}
        repair = learn or self.repair_all
        if context["phase"] == "draft" and learn:
            payload["response"]["claims"][0]["text"] = "Synthetic unsupported development control."
        if context["phase"] == "check":
            self.checks += 1
            for c in payload["checks"]:
                c["decision"] = (
                    "unsupported" if repair and self.checks == 1 and learn else "supported"
                )
                c["reason"] = (
                    "Synthetic software verdict; semantic quality and human support unmeasured."
                )
            if repair and self.checks == 1 and not learn:
                payload["coverage_checks"][0]["decision"] = "uncertain"
        response.update(
            model=body["model"],
            id="offline-coverage-" + self.case_id + "-" + str(len(self.contacts)),
            usage={"input_tokens": 100, "output_tokens": 100},
        )
        response["content"][0]["text"] = json.dumps(payload)
        return httpx.Response(200, json=response)


def capture(
    public: Any,
    ledger: Any,
    program_id: str,
    *,
    expected: tuple[int, int, int, str] = (30, 61, 81, "1.779493"),
) -> dict[str, Any]:
    from src.workspace.d5_fixture import FINANCIAL_TABLES, PUBLIC_TABLES, financial_rows
    from src.workspace.qualification_budget import census

    with public.pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        tables = {
            name: [
                r[0]
                for r in conn.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(name))
                )
            ]
            for name in PUBLIC_TABLES
        }
        if any(r["visibility_owner"] is not None for r in tables["workspace_works"]):
            raise AdmissionError("coverage_public_snapshot_only")
    with ledger.pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        binding = programme(conn, program_id)
        members = sorted(
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
            )
        )
        history = census(conn, members[0], members=members)
        for name in FINANCIAL_TABLES:
            tables[name] = financial_rows(conn, name)
        extra = {
            key: [
                r[0]
                for r in conn.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(name))
                )
            ]
            for name, key in (
                ("workspace_programme_amendments", "recorded_amendments"),
                ("workspace_programme_successor_amendments", "recorded_successor_amendments"),
                ("workspace_programme_third_amendments", "recorded_third_amendments"),
                ("workspace_programme_capacity_amendments", "recorded_capacity_amendments"),
                ("workspace_d5_scopes", "historical_scopes"),
                ("workspace_d5_stage_authorizations", "historical_stage_grants"),
            )
        }
    if (
        history["messages"] != expected[1]
        or history["counts"] != expected[2]
        or history["known_usd"] != expected[3]
        or history["pending_usd"] != "0"
        or history["unknown_usd"] != "0"
        or history["active_jobs"]
        or history["uncertain_contacts"]
    ):
        raise AdmissionError("coverage_expected_reconciled_ledger_required")
    with ledger.pool.connection() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        base = conn.execute(
            "SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s", (program_id,)
        ).fetchone()[0]
        if len(set(history["generation_job_ids"]) - set(base["generation_job_ids"])) != expected[0]:
            raise AdmissionError("coverage_expected_programme_job_census_required")
    from src.workspace.schemas import ProfileData

    return {
        "tables": tables,
        **extra,
        "programme": binding,
        "history": history,
        "program_id": program_id,
        "profile": ProfileData().model_dump(mode="json"),
        "profile_authority": "Unused synthetic storage profile; no ranking/owner-profile claim",
        "provenance": "Read-only public replay and full reconciled accounting. No private notes/preferences/history, budget policies or credentials imported.",
    }


def fixture_A(store: Any, packet: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_authorization import case_bindings, record_external
    from src.workspace.d5_freeze import compile_inputs

    with store.pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone():
            raise AdmissionError("coverage_fixture_database_required")
    compiled = compile_inputs(packet)
    now = datetime.now(UTC)
    expiry = min(
        now + timedelta(hours=23), datetime.fromisoformat(packet["programme"]["expires_at"])
    )
    receipt = {
        "approved": True,
        "approved_by": "Disposable synthetic fixture, never owner authorization",
        "approved_at": now.isoformat(),
        "expires_at": expiry.isoformat(),
        "packet_digest": packet["packet_digest"],
        "scope_id": "d5-" + packet["packet_digest"][:24],
        "limits": packet["limits"],
        "members": sorted({e["owner"] for e in compiled.values()}),
        "case_bindings_digest": _digest(case_bindings(compiled)),
        "transport_mode": "mock",
        "authorization_kind": "offline_fixture",
        "stages": ["A"],
    }
    return record_external(
        store,
        packet_digest=packet["packet_digest"],
        scope_id=receipt["scope_id"],
        program_id=packet["program_id"],
        compiled=compiled,
        receipt=receipt,
        expected_history=packet["history"],
    )


async def replay(store: Any, packet: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_authorization import grant_external, stage_template
    from src.workspace.d5_benchmark import run
    from src.workspace.d5_fixture import install, prepare_projects

    if (
        snapshot.get("programme") != packet["programme"]
        or _digest(snapshot) != packet["snapshot_digest"]
        or not is_packet(packet)
    ):
        raise AdmissionError("coverage_replay_snapshot_binding_changed")
    install(store, snapshot, fixture=True)
    prepare_projects(store, packet)
    fixture_A(store, packet)
    A = await run(store, packet, "A", offline=True)
    try:
        await run(store, packet, "B", offline=True)
    except AdmissionError as exc:
        if str(exc) != "d5_stage_not_authorized":
            raise
        refusal = str(exc)
    else:
        raise AdmissionError("coverage_missing_B_grant_not_refused")
    scope = "d5-" + packet["packet_digest"][:24]
    B_receipt = stage_template(store, scope, ["B"])
    B_receipt.update(
        approved=True,
        approved_by="Separate disposable B fixture, never owner authorization",
        approved_at=datetime.now(UTC).isoformat(),
    )
    grant = grant_external(store, scope, B_receipt)
    B = await run(store, packet, "B", offline=True)
    return {
        "packet_digest": packet["packet_digest"],
        "scope_id": scope,
        "A": A,
        "B_without_grant": refusal,
        "B_fixture_grant": grant,
        "B": B,
        "new_provider_contacts": 0,
        "new_count_contacts": 0,
        "new_spend_usd": "0",
        "human_qualification": False,
    }


def main() -> None:
    from src.workspace.d5_benchmark import database, read, write
    from src.workspace.store import WorkspaceStore

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["capture", "freeze", "replay"])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--proposal", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if (
        os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
        or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
    ):
        raise AdmissionError("coverage_offline_disabled_key_required")
    if args.verb == "capture":
        with (
            database(os.environ["D5_PUBLIC_POSTGRES_URL"]) as public,
            database(os.environ["D5_LEDGER_POSTGRES_URL"]) as financial,
        ):
            captured = capture(
                WorkspaceStore(public), WorkspaceStore(financial), "research-evaluation-20261105-v1"
            )
        write(args.snapshot, captured)
        print(json.dumps({"snapshot_digest": _digest(captured), "provider_contacts": 0}))
        return
    if args.packet is None:
        parser.error("--packet required")
    captured = read(args.snapshot)
    if args.verb == "freeze":
        if args.proposal is None:
            parser.error("--proposal required")
        packet = freeze_controls(read(args.proposal), captured, captured["programme"])
        write(args.packet, packet)
        print(
            json.dumps(
                {
                    "packet_digest": packet["packet_digest"],
                    "scope_id": "d5-" + packet["packet_digest"][:24],
                    "approved": False,
                }
            )
        )
        return
    if args.out is None or args.out.exists():
        parser.error("--out must be a new directory")
    with database(os.environ["D5_POSTGRES_URL"]) as pool:
        report = asyncio.run(replay(WorkspaceStore(pool), read(args.packet), captured))
    write(args.out / "REPLAY.json", report)
    print(
        json.dumps(
            {
                "completed": sum(c["completion"] for c in report["B"]["cases"]),
                "new_provider_contacts": 0,
                "new_count_contacts": 0,
                "new_spend_usd": "0",
            }
        )
    )


if __name__ == "__main__":
    main()
