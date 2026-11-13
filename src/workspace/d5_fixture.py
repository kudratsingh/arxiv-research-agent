"""Explicit disposable replay storage and transport, never live authorization.

Public/financial snapshots exclude owner notes, history, policies and credentials.
The offline marker categorically prohibits a provider-mode D5 adapter.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from psycopg import sql
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.assistance import LocalAssistanceTransport
from src.workspace.d5_authorization import case_bindings, record_external
from src.workspace.d5_freeze import COUNT_OWNER, RUN_OWNER, compile_inputs, execution_owners
from src.workspace.qualification_budget import census
from src.workspace.store import WorkspaceStore

PUBLIC_TABLES = (
    "workspace_works",
    "workspace_versions",
    "workspace_observations",
    "workspace_material",
    "workspace_material_provenance",
    "workspace_sources",
    "workspace_ingest_runs",
)
FINANCIAL_TABLES = (
    "workspace_generation_jobs",
    "workspace_spend_reservations",
    "workspace_qualification_trials",
    "workspace_evaluation_programs",
    "workspace_evaluation_members",
)


def financial_rows(conn: Any, name: str) -> list[dict[str, Any]]:
    """Preserve numeric scale used by the exact accounting census hash.

    JSON floating-point conversion loses e.g. Decimal('0.40') -> 0.4. PostgreSQL
    jsonb_populate_record accepts numeric strings without changing that scale.
    No value, charge, historical binding or admission check is relaxed.
    """
    if name not in FINANCIAL_TABLES:
        raise AdmissionError("d5_financial_table_required")
    override = (
        sql.SQL(
            " || jsonb_build_object('amount',t.amount::text,'workflow',t.workflow::text,'judge',t.judge::text,'unknown',t.unknown::text)"
        )
        if name == "workspace_spend_reservations"
        else sql.SQL("")
    )
    return [
        r[0]
        for r in conn.execute(
            sql.SQL("SELECT to_jsonb(t){} FROM {} t").format(override, sql.Identifier(name))
        )
    ]


def snapshot(
    public: WorkspaceStore, financial: WorkspaceStore, program_id: str, profile_owner: str
) -> dict[str, Any]:
    with public.pool.connection() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        tables = {
            name: [
                r[0]
                for r in conn.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(name))
                )
            ]
            for name in PUBLIC_TABLES
        }
        if any(row["visibility_owner"] is not None for row in tables["workspace_works"]):
            raise AdmissionError("d5_public_snapshot_contains_private_works")
        profile_row = conn.execute(
            "SELECT data FROM workspace_profiles WHERE owner=%s", (profile_owner,)
        ).fetchone()
        if not profile_row:
            raise AdmissionError("d5_actual_profile_missing")
        actual_profile = profile_row[0]
        profile = {
            key: actual_profile[key]
            for key in (
                "topics",
                "custom_topics",
                "exclusions",
                "streams",
                "minutes",
                "exploration",
            )
        }
        # The public replay needs ranking preferences, not a private question or
        # a pinned-note identity. Keep authority hashes separately, locally.
        profile.update(research_question="", pinned_entry_id=None)
    with financial.pool.connection() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        members = [
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s ORDER BY owner",
                (program_id,),
            )
        ]
        if not members:
            raise AdmissionError("d5_historical_program_missing")
        history = census(conn, members[0], members=members)
        for name in FINANCIAL_TABLES:
            # Preserve all old financial rows, including initial count-only jobs.
            # No budget policy is imported; these records grant no new authority.
            tables[name] = financial_rows(conn, name)
    return {
        "tables": tables,
        "history": history,
        "program_id": program_id,
        "profile": profile,
        "profile_authority": {
            "actual_profile_digest": _digest(actual_profile),
            "research_question_digest": _digest(actual_profile.get("research_question", "")),
            "private_question_in_replay": False,
            "notes_history_in_replay": False,
        },
        "provenance": "Read-only retained public and financial snapshot; no fresh intake, private notes/history or operative budget policies",
    }


def install(store: WorkspaceStore, captured: dict[str, Any], *, fixture: bool) -> None:
    """Only an empty, explicitly named D5 database may receive replay data."""
    store.migrate()
    with store.pool.connection() as conn:
        db_row = conn.execute("SELECT current_database(),current_schema()").fetchone()
        assert db_row is not None
        database, schema = db_row
        if not database.startswith("workspace_d5_") and not schema.startswith("ws_test_"):
            raise AdmissionError("d5_disposable_storage_required")
        if conn.execute(
            "SELECT 1 FROM workspace_generation_jobs UNION ALL SELECT 1 FROM workspace_works LIMIT 1"
        ).fetchone():
            raise AdmissionError("d5_import_requires_empty_storage")
        for name in (*PUBLIC_TABLES, *FINANCIAL_TABLES):
            for row in captured["tables"][name]:
                conn.execute(
                    sql.SQL(
                        "INSERT INTO {} SELECT * FROM jsonb_populate_record(NULL::{}, %s)"
                    ).format(sql.Identifier(name), sql.Identifier(name)),
                    (Jsonb(row),),
                )
        if fixture:
            conn.execute(
                "INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only',%s)",
                (
                    Jsonb(
                        {
                            "synthetic_authorization_only": True,
                            "snapshot_history_digest": captured["history"]["history_digest"],
                            "historical_successor_authorizations": [
                                r["authorization_digest"]
                                for r in captured.get("recorded_successor_amendments", [])
                                if r["record"].get("authorization_kind") == "owner"
                                and r["record"].get("transport_mode") == "provider"
                            ],
                            "historical_amendment_authorizations": [
                                r["authorization_digest"]
                                for r in captured.get("recorded_amendments", [])
                                if r["record"].get("authorization_kind") == "owner"
                                and r["record"].get("transport_mode") == "provider"
                            ],
                            "historical_capacity_authorizations": [
                                r["authorization_digest"]
                                for r in captured.get("recorded_capacity_amendments", [])
                                if r["record"].get("authorization_kind") == "owner"
                                and r["record"].get("transport_mode") == "provider"
                            ],
                            "historical_third_authorizations": [
                                r["authorization_digest"]
                                for r in captured.get("recorded_third_amendments", [])
                                if r["record"].get("authorization_kind") == "owner"
                                and r["record"].get("transport_mode") == "provider"
                            ],
                        }
                    ),
                ),
            )
        # Restore already-recorded policy metadata, never create a new approval.
        # A fixture can read these mirrored hashes but can never dispatch live.
        for amendment in captured.get("recorded_amendments", []):
            if _digest(amendment["record"]) != amendment["authorization_digest"]:
                raise AdmissionError("d5_historical_amendment_digest_changed")
            conn.execute(
                "INSERT INTO workspace_programme_amendments SELECT * FROM jsonb_populate_record(NULL::workspace_programme_amendments,%s)",
                (Jsonb(amendment),),
            )
        for name, key in (
            ("workspace_programme_successor_amendments", "recorded_successor_amendments"),
            ("workspace_programme_third_amendments", "recorded_third_amendments"),
            ("workspace_programme_capacity_amendments", "recorded_capacity_amendments"),
            ("workspace_d5_scopes", "historical_scopes"),
            ("workspace_d5_stage_authorizations", "historical_stage_grants"),
            ("workspace_d5_case_runs", "historical_case_runs"),
            ("workspace_d5_campaign_extensions", "recorded_campaign_extensions"),
            ("workspace_d5_campaign_revocations", "recorded_campaign_revocations"),
            ("workspace_d5_campaign_outcomes", "recorded_campaign_outcomes"),
        ):
            for receipt in captured.get(key, []):
                conn.execute(
                    sql.SQL(
                        "INSERT INTO {} SELECT * FROM jsonb_populate_record(NULL::{},%s)"
                    ).format(sql.Identifier(name), sql.Identifier(name)),
                    (Jsonb(receipt),),
                )
        for owner in (RUN_OWNER, COUNT_OWNER):
            conn.execute(
                "INSERT INTO workspace_profiles VALUES(%s,1,%s)",
                (owner, Jsonb(captured["profile"])),
            )
        members = [
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
                (captured["program_id"],),
            )
        ]
        actual = census(conn, members[0], members=members)
        if actual != captured["history"]:
            raise AdmissionError("d5_imported_financial_history_changed")


def authorize_fixture(
    store: WorkspaceStore, packet: dict[str, Any], *, stages: tuple[str, ...] = ("A", "B", "C", "D")
) -> dict[str, Any]:
    """Only the offline command calls this. Never a provider/operator path."""
    compiled = compile_inputs(packet)
    now = datetime.now(UTC)
    receipt = {
        "approved": True,
        "approved_by": "Disposable offline fixture, not owner approval",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "packet_digest": packet["packet_digest"],
        "scope_id": "d5-" + packet["packet_digest"][:24],
        "limits": packet["limits"],
        "members": sorted({v["owner"] for v in compiled.values()}),
        "case_bindings_digest": _digest(case_bindings(compiled)),
        "transport_mode": "mock",
        "authorization_kind": "offline_fixture",
        "stages": list(stages),
    }
    with store.pool.connection() as conn:
        prior = conn.execute(
            "SELECT data->'authorization_record' FROM workspace_d5_scopes WHERE scope_id=%s",
            (receipt["scope_id"],),
        ).fetchone()
        if prior:
            # Reuse, never renew or reapprove. record_external validates the
            # original expiry/kind/digest; stopped/revoked stays stopped/revoked.
            receipt = prior[0]
    return record_external(
        store,
        packet_digest=packet["packet_digest"],
        scope_id=receipt["scope_id"],
        program_id=packet["program_id"],
        compiled=compiled,
        receipt=receipt,
        expected_history=packet["history"],
    )


def prepare_projects(store: WorkspaceStore, packet: dict[str, Any]) -> None:
    """Recreate only explicitly sealed isolated project context, no approval."""
    from src.workspace.context_schemas import ProjectData, ProjectWrite
    from src.workspace.context_store import WorkspaceContext

    context = WorkspaceContext(store)
    owners = tuple(dict.fromkeys(execution_owners(packet)))
    if packet.get("cohort_revision") == "procedural-v8":
        with store.pool.connection() as conn:
            for owner in owners:
                row = conn.execute(
                    "SELECT data FROM workspace_profiles WHERE owner=%s", (owner,)
                ).fetchone()
                if row:
                    if any(row[0].get(k) != v for k, v in packet["profile"].items()):
                        raise AdmissionError("d5_prepared_profile_changed")
                else:
                    conn.execute(
                        "INSERT INTO workspace_profiles VALUES(%s,1,%s)",
                        (owner, Jsonb(packet["profile"])),
                    )
    for case in (*packet["cases"], *packet.get("probes", [])):
        project = (case.get("sealed") or {}).get("project_context")
        if not project:
            continue
        for owner in owners:
            actual = context.write_project(
                owner,
                ProjectWrite(
                    id=project["id"],
                    revision=0,
                    request_id="freeze-" + case["id"],
                    data=ProjectData(
                        title="Experimental · " + case["id"],
                        question=project["question"],
                        scope=project["scope"],
                        constraints=project["constraints"],
                    ),
                ),
            )
            if actual["revision"] != project["revision"]:
                raise AdmissionError("d5_prepared_project_revision_changed")


class ReplayTransport:
    """Wire-valid simulation over the real adapter. Counts are synthetic, not tokens."""

    def __init__(self, case_id: str, *, scenario: str = "normal"):
        self.case_id, self.scenario = case_id, scenario
        self.contacts: list[dict[str, str]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.contacts.append({"endpoint": request.url.path, "digest": _digest(body)})
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        if self.scenario == "timeout":
            raise httpx.ReadTimeout("Synthetic uncertain completion", request=request)
        response = LocalAssistanceTransport.fixture(request).json()
        response["model"] = body["model"]
        if self.scenario == "truncated":
            response["stop_reason"] = "max_tokens"
            response["content"][0]["text"] = '{"claims":['
        elif self.scenario == "unsupported":
            output = json.loads(response["content"][0]["text"])
            if "checks" in output:
                for check in output["checks"]:
                    check["decision"] = "unsupported"
            response["content"][0]["text"] = json.dumps(output)
        response.update(
            id="offline-" + self.case_id + "-" + str(len(self.contacts)),
            usage={"input_tokens": 100, "output_tokens": 100},
        )
        return httpx.Response(200, json=response)
