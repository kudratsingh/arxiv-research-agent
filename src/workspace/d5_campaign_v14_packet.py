"""Prospective frozen successor; no provider or live permission I/O.

Only disposable fixture storage may prepare the campaign. Its public corpus,
questions, ranking and reference labels remain exposed development material.
"""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg import sql

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign_v14_policy import LIMITS, PROGRESSION, REVISION, ROUTES

BASE = "97d24567bc98753122315f135a621eb886cebb2b81c32eb5762572589f037e08"
ROOT = Path(__file__).resolve().parents[2]


def predecessor() -> dict[str, Any]:
    from src.workspace.d5_benchmark import read

    value = read(
        ROOT
        / "planning/15-evaluation-audit-and-recovery/evidence/consolidated-campaign-v13/packet.json.gz"
    )
    if (
        value.get("packet_digest") != BASE
        or _digest({k: v for k, v in value.items() if k != "packet_digest"}) != BASE
    ):
        raise AdmissionError("campaign_v14_archived_v13_changed")
    return value


def capture(store: Any, program_id: str) -> dict[str, Any]:
    """Read-only census; no migration, grant, reservation or financial changes."""
    from src.workspace.d5_campaign_v14_extension import history, parent
    from src.workspace.d5_fixture import FINANCIAL_TABLES, PUBLIC_TABLES, financial_rows
    from src.workspace.schemas import ProfileData

    with store.pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        _, baseline = history(conn, program_id)
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
            raise AdmissionError("campaign_v14_public_context_only")
        tables.update({name: financial_rows(conn, name) for name in FINANCIAL_TABLES})
        extras = {}
        for table, key in (
            ("workspace_programme_amendments", "recorded_amendments"),
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
            extras[key] = [
                r[0]
                for r in conn.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(table))
                )
            ]
        p = parent(conn, program_id)
    return {
        "tables": tables,
        **extras,
        "programme": p,
        "history": baseline,
        "program_id": program_id,
        "profile": ProfileData().model_dump(mode="json"),
        "profile_authority": "Unused synthetic storage profile; ranking uses retained owner-authoritative benchmark profile, never owner notes/history.",
        "provenance": "Read-only stopped v13 census; both liabilities retained without settlement.",
    }


def upgrade(sealed: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.assistance import build_wire, capacity
    from src.workspace.assistance_compact_checks import schemas as checker_schemas
    from src.workspace.assistance_compact_draft import REVISION as DRAFT_REVISION
    from src.workspace.assistance_contract import schemas

    value = deepcopy(sealed)
    value["schema_revision"] = DRAFT_REVISION
    value["task_policy"]["revision"] = DRAFT_REVISION
    value["response_schemas"] = schemas(
        list(value["units"]),
        purpose=value["response_purpose"],
        revision=DRAFT_REVISION,
        task_policy=value["task_policy"],
    )
    for stage in ("draft", "repair"):
        value["stage_contracts"][stage]["output_schema"] = value["response_schemas"]["wire"]
    value["stage_contracts"]["check"]["output_schema"] = checker_schemas()["wire"]
    context = json.loads(value["candidate_initial_wire"]["messages"][0]["content"])
    context["sealed_request"]["schema_revision"] = DRAFT_REVISION
    context["sealed_request"]["task_policy"] = value["task_policy"]
    context["output_schema"] = value["response_schemas"]["wire"]
    value["candidate_initial_wire"] = build_wire(context)
    value["capacity"] = capacity(value)
    return value


def freeze(store: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.assistance_compact_checks import COMPACT_NORMALIZATION_REVISION
    from src.workspace.assistance_compact_checks import schemas as checker_schemas
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_answerability import matrix
    from src.workspace.d5_campaign_packet import BUILD_OWNER, make_probes, plan_digest, selection
    from src.workspace.d5_campaign_v14_extension import proposal
    from src.workspace.d5_freeze import code_bindings
    from src.workspace.d5_operations import wire
    from src.workspace.executor import FakeExecutor

    with store.pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone():
            raise AdmissionError("campaign_v14_freeze_disposable_fixture_required")
        old = predecessor()
        materials = tuple(
            FakeExecutor(store)._sources(conn, BUILD_OWNER, [m["material_id"]])[0]
            for m in old["materials"]
        )
    cases = []
    for c in old["cases"]:
        intent = c["sealed"]["task_policy"]["task_intent"]
        sealed = selection(
            store, c["id"], c["mode"], c["question"], c["sealed"]["units"], intent=intent
        )
        sealed = upgrade(sealed)
        cases.append(
            {
                **deepcopy(c),
                "sealed": sealed,
                "wire_digest": _digest(sealed["candidate_initial_wire"]),
                "predecessor_packet": BASE,
                "exposure": "Prospective new request identities on exposed questions/corpus; prior v13 failures remain separate. Not fresh independent held-out evidence.",
            }
        )
    probes, references, exclusions = make_probes(store, materials)
    for probe in probes:
        context = json.loads(probe["wire"]["messages"][0]["content"])
        context["output_schema"] = probe["wire"]["output_config"]["format"]["schema"]
        # Probe purpose stays claim support under its original local schema.
        probe["wire"] = wire(context, ROUTES)
    selected_materials = {
        r["material_id"] for c in (*cases, *probes) for r in c["sealed"]["units"].values()
    }
    source_bindings = {
        "versions": {
            r["version_id"]: _digest(r["data"])
            for r in snapshot["tables"]["workspace_versions"]
            if r["version_id"] in {c["version_id"] for c in old["corpus"]}
        },
        "materials": {
            r["material_id"]: _digest(r["data"])
            for r in snapshot["tables"]["workspace_material"]
            if r["material_id"] in selected_materials
        },
    }
    with store.pool.connection() as conn:
        for label, table, key in (
            ("versions", "workspace_versions", "version_id"),
            ("materials", "workspace_material", "material_id"),
        ):
            actual = {
                r[0]: _digest(r[1])
                for r in conn.execute(
                    sql.SQL("SELECT {},data FROM {} WHERE {}=ANY(%s)").format(
                        sql.Identifier(key), sql.Identifier(table), sql.Identifier(key)
                    ),
                    (list(source_bindings[label]),),
                )
            }
            if actual != source_bindings[label]:
                raise AdmissionError("campaign_v14_capture_source_changed_before_freeze")
    value = {
        **deepcopy(old),
        "revision": REVISION,
        "approved": False,
        "application_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "predecessor_packet": BASE,
        "program_id": snapshot["program_id"],
        "history": snapshot["history"],
        "snapshot_digest": _digest(snapshot),
        "programme": snapshot["programme"],
        "limits": LIMITS,
        "operation_routes": ROUTES,
        "progression": PROGRESSION,
        "cases": cases,
        "probes": probes,
        "probe_references": references,
        "probe_reference_digest": _digest(references),
        "probe_evidence_exclusions": exclusions,
        "schedule": [c["id"] for c in (*cases, *probes)],
        "measurement_cases": [],
        "materials": [asdict(m) for m in materials],
        "code": code_bindings(),
        "adapter": qualification_producer(),
        "source_bindings": source_bindings,
        "checker_schemas": checker_schemas(),
        "checker_normalization_revision": COMPACT_NORMALIZATION_REVISION,
        "answerability": matrix(cases),
        "stop_policy": "Broken development response contracts stop before evaluation. Valid negative quality verdicts remain failures and permit unrelated sealed cases. Preserve original hard stops for provider error, new uncertainty, drift, corruption, exhausted limits, expiry/revocation/cancellation. No retry or replacement identity.",
    }
    value.pop("packet_digest", None)
    with store.pool.connection() as conn:
        value["campaign_extension"] = proposal(conn, snapshot["program_id"], plan_digest(value))
    value["packet_digest"] = _digest(value)
    verify_packet(value)
    return value


def verify_packet(value: dict[str, Any]) -> None:
    from src.workspace.assistance_compact_checks import COMPACT_NORMALIZATION_REVISION
    from src.workspace.assistance_compact_checks import schemas as checker_schemas
    from src.workspace.assistance_compact_draft import REVISION as DRAFT_REVISION
    from src.workspace.assistance_contract import schemas
    from src.workspace.d5_adapter import initial_context
    from src.workspace.d5_answerability import matrix
    from src.workspace.d5_campaign_packet import plan_digest
    from src.workspace.d5_campaign_v14_extension import REVISION as EXTENSION_REVISION
    from src.workspace.d5_operations import wire

    old = predecessor()
    if (
        value.get("revision") != REVISION
        or value.get("approved") is not False
        or value.get("predecessor_packet") != BASE
        or value.get("limits") != LIMITS
        or value.get("operation_routes") != ROUTES
        or value.get("progression") != PROGRESSION
        or value.get("measurement_cases") != []
        or value.get("human_qualification") is not False
        or value.get("checker_schemas") != checker_schemas()
        or value.get("checker_normalization_revision") != COMPACT_NORMALIZATION_REVISION
        or value.get("schedule") != old["schedule"]
        or len(value.get("cases", [])) != 10
        or len(value.get("probes", [])) != 4
    ):
        raise AdmissionError("campaign_v14_frozen_policy_or_schedule_drift")
    for current, prior in zip(value["cases"], old["cases"], strict=True):
        if any(
            current.get(k) != prior.get(k)
            for k in (
                "id",
                "cohort",
                "pipeline",
                "mode",
                "question",
                "ranking",
                "edition",
                "evidence_selection",
                "baselines",
            )
        ):
            raise AdmissionError("campaign_v14_retrieval_or_cohort_drift")
        sealed = current["sealed"]
        if (
            sealed["schema_revision"] != DRAFT_REVISION
            or sealed["units"] != prior["sealed"]["units"]
            or sealed["task_policy"]
            != {**prior["sealed"]["task_policy"], "revision": DRAFT_REVISION}
            or sealed["response_schemas"]
            != schemas(
                list(sealed["units"]),
                purpose=sealed["response_purpose"],
                revision=DRAFT_REVISION,
                task_policy=sealed["task_policy"],
            )
            or current["wire_digest"] != _digest(sealed["candidate_initial_wire"])
            or wire(initial_context(sealed), ROUTES) != sealed["candidate_initial_wire"]
        ):
            raise AdmissionError("campaign_v14_exact_draft_binding_drift")
    # Reuse the frozen twenty balanced reference identities and exact passages.
    if value["probe_references"] != old["probe_references"] or value[
        "probe_reference_digest"
    ] != _digest(value["probe_references"]):
        raise AdmissionError("campaign_v14_reference_label_drift")
    for probe, prior in zip(value["probes"], old["probes"], strict=True):
        actual = json.loads(probe["wire"]["messages"][0]["content"])
        earlier = json.loads(prior["wire"]["messages"][0]["content"])
        expected_context = {
            **earlier,
            "output_schema": prior["wire"]["output_config"]["format"]["schema"],
        }
        if (
            probe["id"] != prior["id"]
            or probe.get("human_labels") is not None
            or probe.get("cohort") != prior["cohort"]
            or probe["sealed"]["units"] != prior["sealed"]["units"]
            or actual != earlier
            or probe["wire"] != wire(expected_context, ROUTES)
        ):
            raise AdmissionError("campaign_v14_probe_evidence_or_wire_drift")
    if (
        value.get("answerability") != matrix(value["cases"])
        or value.get("scoring") != old["scoring"]
    ):
        raise AdmissionError("campaign_v14_answerability_or_threshold_drift")
    core = value["campaign_extension"]["core"]
    if (
        core.get("revision") != EXTENSION_REVISION
        or core.get("basis") != value["history"]
        or core.get("plan_digest") != plan_digest(value)
        or value["campaign_extension"]["proposal_digest"] != _digest(core)
    ):
        raise AdmissionError("campaign_v14_capacity_or_snapshot_drift")
