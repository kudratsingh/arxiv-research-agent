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
from src.workspace.d5_campaign_v19_policy import LIMITS, PROGRESSION, REVISION, ROUTES

BASE = "25eec8f541dbe7f70bf2fadee59f51c0d8b456980856cd4f38fce20b139e8bde"
ROOT = Path(__file__).resolve().parents[2]


def public_programme_authority(row: dict[str, Any]) -> dict[str, Any]:
    """Publish an authority commitment, never the private historical approval."""
    return {
        **{
            k: row[k]
            for k in ("extension_id", "authorization_digest", "programme_expires_at", "expires_at")
        },
        "row_digest": _digest(row),
    }


def predecessor() -> dict[str, Any]:
    from src.workspace.d5_benchmark import read

    value = read(
        ROOT
        / "planning/15-evaluation-audit-and-recovery/evidence/capacity-policy-v15r2/packet.json.gz"
    )
    if (
        value.get("packet_digest") != BASE
        or _digest({k: v for k, v in value.items() if k != "packet_digest"}) != BASE
    ):
        raise AdmissionError("campaign_v19_archived_predecessor_changed")
    return value


def capture(store: Any, program_id: str, preserved_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate read-only sources, census and holds; return exact preserved JSON."""
    from src.workspace.d5_campaign_v19_extension import proposal
    from src.workspace.d5_fixture import FINANCIAL_TABLES, PUBLIC_TABLES, financial_rows

    with store.pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        proposal(conn, program_id, "read-only-capture-validation", preserved_snapshot)
        for table in (*PUBLIC_TABLES, *FINANCIAL_TABLES):
            actual = (
                financial_rows(conn, table)
                if table in FINANCIAL_TABLES
                else [
                    r[0]
                    for r in conn.execute(
                        sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(table))
                    )
                ]
            )
            expected = preserved_snapshot["tables"][table]
            if sorted(_digest(r) for r in actual) != sorted(_digest(r) for r in expected):
                raise AdmissionError("campaign_v19_preserved_source_or_financial_snapshot_drift")
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
            ("workspace_d5_campaign_successors", "recorded_campaign_successors"),
            (
                "workspace_d5_campaign_successor_revocations",
                "recorded_campaign_successor_revocations",
            ),
            ("workspace_d5_capacity_revisions", "recorded_capacity_revisions"),
            (
                "workspace_d5_capacity_revision_revocations",
                "recorded_capacity_revision_revocations",
            ),
            ("workspace_d5_keyed_continuations", "recorded_keyed_continuations"),
            (
                "workspace_d5_keyed_continuation_revocations",
                "recorded_keyed_continuation_revocations",
            ),
        ):
            actual = [
                r[0]
                for r in conn.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(table))
                )
            ]
            if sorted(_digest(r) for r in actual) != sorted(
                _digest(r) for r in preserved_snapshot[key]
            ):
                raise AdmissionError("campaign_v19_preserved_authority_snapshot_drift")
    return deepcopy(preserved_snapshot)


def prepare_selection(
    store: Any,
    key: str,
    mode: str,
    question: str,
    units: dict[str, Any],
    *,
    intent: str = "answer",
    union_safe: bool = True,
) -> dict[str, Any]:
    """Use the qualification-only DTO and actual retained storage, never fake caps."""
    from src.workspace.d5_campaign_packet import BUILD_OWNER
    from src.workspace.d5_capacity_selection import build

    return upgrade(
        build(store, BUILD_OWNER, key, mode, question, units, intent=intent), union_safe=union_safe
    )


def upgrade(sealed: dict[str, Any], *, union_safe: bool = True) -> dict[str, Any]:
    from src.workspace.assistance import capacity
    from src.workspace.assistance_comparison_contract import schemas
    from src.workspace.assistance_consistency_checks import REVISION as CHECKER_TEMPLATE_REVISION
    from src.workspace.assistance_keyed_checks import finding_capacity
    from src.workspace.assistance_keyed_contract import REVISION as ASSISTANCE_REVISION
    from src.workspace.assistance_keyed_contract import seal_policy
    from src.workspace.assistance_policy import CoverageTaskContext
    from src.workspace.d5_adapter import initial_context
    from src.workspace.d5_capacity_policy import POLICY
    from src.workspace.d5_operations import wire

    if not union_safe:
        raise AdmissionError("campaign_v19_comparison_encoding_required")
    value = deepcopy(sealed)
    value["schema_revision"] = ASSISTANCE_REVISION
    value["model_id"] = ROUTES["draft_repair"]["model"]
    value["mode"] = "qualification_preview"
    value.pop("fixture_revision", None)
    value["producer"]["contract"] = ASSISTANCE_REVISION
    value["limits"] = {
        "max_calls": 4,
        "max_repairs": 1,
        "per_call_input_tokens": 40000,
        "paired_input_fit": 32000,
        "stage_output_tokens": {"draft": 8000, "repair": 8000, "check": 12000, "recheck": 12000},
        "max_input_tokens": 160000,
        "max_output_tokens": 40000,
        "max_source_bytes": POLICY["max_selected_evidence_utf8_bytes"],
        "max_spans": 12,
    }
    selection = value["assistance"]
    question = (
        selection["follow_up"]
        or (value.get("project_context") or {}).get("question")
        or f"Explain the selected paper: {selection['direction']} at {selection['depth']} depth"
    )
    value["task_policy"] = seal_policy(
        CoverageTaskContext.model_validate(selection["task_context"]),
        selection["mode"],
        len({u["work_id"] for u in value["units"].values()}),
        question,
    )
    if union_safe:
        from src.workspace.assistance_comparison_contract import KEY
        from src.workspace.assistance_comparison_contract import REVISION as ENCODING
        from src.workspace.provider_schema_compat import REVISION as COMPAT

        value["task_policy"][KEY] = ENCODING
        value["provider_schema_compatibility_revision"] = COMPAT
    value["response_schemas"] = schemas(
        list(value["units"]), value["response_purpose"], value["task_policy"]
    )
    for stage in ("draft", "repair"):
        value["stage_contracts"][stage]["output_schema"] = value["response_schemas"]["wire"]
        value["stage_contracts"][stage]["output_tokens"] = ROUTES["draft_repair"]["output_tokens"]
    value["stage_contracts"]["check"].pop("output_schema", None)
    value["stage_contracts"]["check"]["output_schema_template_revision"] = CHECKER_TEMPLATE_REVISION
    value["stage_contracts"]["check"]["output_tokens"] = ROUTES["check_recheck_probe"][
        "output_tokens"
    ]
    value["candidate_initial_wire"] = wire(initial_context(value), ROUTES)
    value["capacity"] = capacity(value)
    value["capacity_policy"] = deepcopy(POLICY)
    value["keyed_checker_finding_capacity"] = finding_capacity()
    return value


def freeze(store: Any, snapshot: dict[str, Any], *, union_safe: bool = True) -> dict[str, Any]:
    from src.workspace.assistance_consistency_checks import (
        NORMALIZATION_REVISION as COMPACT_NORMALIZATION_REVISION,
    )
    from src.workspace.assistance_consistency_checks import REVISION as CHECKER_TEMPLATE_REVISION
    from src.workspace.assistance_keyed_checks import finding_capacity
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_answerability import matrix
    from src.workspace.d5_campaign_packet import BUILD_OWNER, make_probes, plan_digest
    from src.workspace.d5_campaign_v19_extension import EXPIRY_POLICY, proposal
    from src.workspace.d5_capacity_policy import DEADLINES
    from src.workspace.d5_capacity_policy import POLICY as CAPACITY_POLICY
    from src.workspace.d5_freeze import code_bindings
    from src.workspace.d5_operations import wire
    from src.workspace.executor import FakeExecutor

    with store.pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone():
            raise AdmissionError("campaign_v19_freeze_disposable_fixture_required")
        old = predecessor()
        materials = tuple(
            FakeExecutor(store)._sources(conn, BUILD_OWNER, [m["material_id"]])[0]
            for m in old["materials"]
        )
    cases = []
    for c in old["cases"]:
        intent = c["sealed"]["task_policy"]["task_intent"]
        sealed = prepare_selection(
            store,
            c["id"],
            c["mode"],
            c["question"],
            c["sealed"]["units"],
            intent=intent,
            union_safe=union_safe,
        )
        cases.append(
            {
                **deepcopy(c),
                "sealed": sealed,
                "wire_digest": _digest(sealed["candidate_initial_wire"]),
                "predecessor_packet": BASE,
                "exposure": "Prospective new request identities on exposed questions/corpus; prior failures remain separate. Not fresh independent held-out evidence.",
            }
        )
    probes, references, exclusions = make_probes(store, materials)
    for probe in probes:
        from src.workspace.assistance_keyed_checks import schemas as keyed_schemas
        from src.workspace.d5_campaign_v16_packet import upgrade as probe_upgrade

        probe["sealed"] = probe_upgrade(probe["sealed"], union_safe=True)
        context = json.loads(probe["wire"]["messages"][0]["content"])
        context["operation"] = "probe"
        context["sealed_request"]["schema_revision"] = probe["sealed"]["schema_revision"]
        if union_safe:
            context["sealed_request"]["provider_schema_compatibility_revision"] = probe["sealed"][
                "provider_schema_compatibility_revision"
            ]
        context["output_schema"] = keyed_schemas(context, probe=True)["wire"]
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
                raise AdmissionError("campaign_v19_capture_source_changed_before_freeze")
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
        "programme": public_programme_authority(snapshot["programme"]),
        "limits": LIMITS,
        "operation_routes": ROUTES,
        "operation_deadlines": DEADLINES,
        "capacity_policy": CAPACITY_POLICY,
        "keyed_checker_finding_capacity": finding_capacity(),
        "expiry_policy": deepcopy(EXPIRY_POLICY),
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
        "checker_schema_template_revision": CHECKER_TEMPLATE_REVISION,
        "checker_normalization_revision": COMPACT_NORMALIZATION_REVISION,
        "answerability": matrix(cases),
        "stop_policy": "Broken development response contracts stop before evaluation. Valid negative quality verdicts remain failures and permit unrelated sealed cases. Preserve original hard stops for provider error, new uncertainty, drift, corruption, exhausted limits, expiry/revocation/cancellation. No retry or replacement identity.",
    }
    if union_safe:
        from src.workspace.assistance_comparison_contract import REVISION as ENCODING
        from src.workspace.provider_schema_compat import POLICY as COMPAT_POLICY

        value["wire_encoding_revision"] = ENCODING
        value["provider_schema_compatibility_policy"] = deepcopy(COMPAT_POLICY)
    value.pop("packet_digest", None)
    value.pop("checker_schemas", None)
    with store.pool.connection() as conn:
        value["campaign_extension"] = proposal(
            conn, snapshot["program_id"], plan_digest(value), snapshot
        )
    value["packet_digest"] = _digest(value)
    verify_packet(value)
    return value


def verify_discovery(value: dict[str, Any]) -> None:
    """Replay actual ranking, edition allocation and evidence selection for eight cases.

    The two development selections remain fixed evidence controls. The eight
    evaluation cases use the unchanged public corpus/profile and frozen clock;
    this verifies software replay, never retrieval or scientific quality.
    """
    from src.workspace.d5_campaign_packet import discovery
    from src.workspace.material import SourceMaterial, SourceSpan

    try:
        materials = tuple(
            SourceMaterial(**{**row, "spans": tuple(SourceSpan(**span) for span in row["spans"])})
            for row in value["materials"]
        )
        cases = value["cases"][2:]
        if len(cases) != 8:
            raise AdmissionError("campaign_v19_eight_discovery_replays_required")
        for index, case in enumerate(cases):
            actual = discovery(value, index, materials)
            if (
                case["id"] != "campaign-" + actual["id"]
                or any(
                    case.get(key) != actual[key]
                    for key in (
                        "mode",
                        "question",
                        "cohort",
                        "pipeline",
                        "ranking",
                        "edition",
                        "allocation",
                        "evidence_selection",
                        "selected_units",
                        "baselines",
                    )
                )
                or case["sealed"]["units"] != actual["selected_units"]
            ):
                raise AdmissionError("campaign_v19_actual_discovery_replay_drift")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, AdmissionError):
            raise
        raise AdmissionError("campaign_v19_actual_discovery_replay_drift") from exc


def verify_packet(value: dict[str, Any]) -> None:
    from src.workspace.assistance_comparison_contract import REVISION as ENCODING
    from src.workspace.assistance_comparison_contract import schemas
    from src.workspace.assistance_consistency_checks import (
        NORMALIZATION_REVISION as COMPACT_NORMALIZATION_REVISION,
    )
    from src.workspace.assistance_consistency_checks import REVISION as CHECKER_TEMPLATE_REVISION
    from src.workspace.assistance_keyed_checks import finding_capacity
    from src.workspace.assistance_keyed_contract import REVISION as DRAFT_REVISION
    from src.workspace.d5_adapter import initial_context
    from src.workspace.d5_answerability import matrix
    from src.workspace.d5_campaign_packet import plan_digest
    from src.workspace.d5_campaign_v19_extension import EXPIRY_POLICY, SNAPSHOT_DIGEST
    from src.workspace.d5_campaign_v19_extension import REVISION as EXTENSION_REVISION
    from src.workspace.d5_capacity_policy import DEADLINES
    from src.workspace.d5_capacity_policy import POLICY as CAPACITY_POLICY
    from src.workspace.d5_operations import wire
    from src.workspace.provider_schema_compat import POLICY as COMPAT_POLICY
    from src.workspace.provider_schema_compat import REVISION as COMPAT

    encoding = value.get("wire_encoding_revision")
    if encoding != ENCODING or value.get("provider_schema_compatibility_policy") != (
        COMPAT_POLICY if encoding else None
    ):
        raise AdmissionError("campaign_v19_provider_compatibility_policy_drift")
    from src.workspace.provider_schema_compat import guard

    if _digest({k: v for k, v in value.items() if k != "packet_digest"}) != value.get(
        "packet_digest"
    ):
        raise AdmissionError("campaign_v19_packet_digest_drift")
    old = predecessor()
    if (
        value.get("revision") != REVISION
        or value.get("approved") is not False
        or value.get("predecessor_packet") != BASE
        or value.get("limits") != LIMITS
        or value.get("operation_routes") != ROUTES
        or value.get("operation_deadlines") != DEADLINES
        or value.get("capacity_policy") != CAPACITY_POLICY
        or value.get("keyed_checker_finding_capacity") != finding_capacity()
        or value.get("expiry_policy") != EXPIRY_POLICY
        or value.get("progression") != PROGRESSION
        or value.get("measurement_cases") != []
        or value.get("human_qualification") is not False
        or value.get("checker_schema_template_revision") != CHECKER_TEMPLATE_REVISION
        or "checker_schemas" in value
        or value.get("checker_normalization_revision") != COMPACT_NORMALIZATION_REVISION
        or value.get("schedule") != old["schedule"]
        or len(value.get("cases", [])) != 10
        or len(value.get("probes", [])) != 4
    ):
        raise AdmissionError("campaign_v19_frozen_policy_or_schedule_drift")
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
            raise AdmissionError("campaign_v19_retrieval_or_cohort_drift")
        sealed = current["sealed"]
        if (
            sealed["schema_revision"] != DRAFT_REVISION
            or sealed.get("provider_schema_compatibility_revision")
            != (COMPAT if encoding else None)
            or sealed.get("keyed_checker_finding_capacity") != finding_capacity()
            or sealed["stage_contracts"]["check"].get("output_schema_template_revision")
            != CHECKER_TEMPLATE_REVISION
            or "output_schema" in sealed["stage_contracts"]["check"]
            or sealed["units"] != prior["sealed"]["units"]
            or sealed["task_policy"]
            != {
                **prior["sealed"]["task_policy"],
                "revision": DRAFT_REVISION,
                **({"wire_encoding_revision": ENCODING} if encoding else {}),
            }
            or sealed["response_schemas"]
            != schemas(
                list(sealed["units"]),
                sealed["response_purpose"],
                sealed["task_policy"],
            )
            or current["wire_digest"] != _digest(sealed["candidate_initial_wire"])
            or wire(initial_context(sealed), ROUTES) != sealed["candidate_initial_wire"]
        ):
            raise AdmissionError("campaign_v19_exact_draft_binding_drift")
        guard(sealed["candidate_initial_wire"])
    verify_discovery(value)
    # Reuse the frozen twenty balanced reference identities and exact passages.
    if value["probe_references"] != old["probe_references"] or value[
        "probe_reference_digest"
    ] != _digest(value["probe_references"]):
        raise AdmissionError("campaign_v19_reference_label_drift")
    from src.workspace.assistance_keyed_checks import schemas as keyed_schemas

    for probe, prior in zip(value["probes"], old["probes"], strict=True):
        earlier = json.loads(prior["wire"]["messages"][0]["content"])
        expected_context = {**earlier, "operation": "probe"}
        expected_context["sealed_request"] = {
            **earlier["sealed_request"],
            "schema_revision": DRAFT_REVISION,
        }
        if encoding:
            expected_context["sealed_request"]["provider_schema_compatibility_revision"] = COMPAT
        expected_context["output_schema"] = keyed_schemas(expected_context, probe=True)["wire"]
        if (
            probe["id"] != prior["id"]
            or probe.get("human_labels") is not None
            or probe["sealed"].get("provider_schema_compatibility_revision")
            != (COMPAT if encoding else None)
            or probe.get("cohort") != prior["cohort"]
            or probe["sealed"]["units"] != prior["sealed"]["units"]
            or probe["sealed"].get("keyed_checker_finding_capacity") != finding_capacity()
            or probe["wire"] != wire(expected_context, ROUTES)
        ):
            raise AdmissionError("campaign_v19_probe_evidence_or_wire_drift")
        guard(probe["wire"])
    if (
        value.get("answerability") != matrix(value["cases"])
        or value.get("scoring") != old["scoring"]
    ):
        raise AdmissionError("campaign_v19_answerability_or_threshold_drift")
    from src.workspace import d5_campaign_v19_extension as extension

    core = value["campaign_extension"]["core"]
    if (
        core.get("program_id") != extension.PROGRAM_ID
        or core.get("extension_id") != extension.PROGRAM_ID + "-comparison-v19"
        or core.get("limits") != extension.LIMITS
        or core.get("period_limits") != extension.PERIOD_LIMITS
        or core.get("programme_expiry") != extension.PROGRAMME_EXPIRY
        or core.get("parent")
        != {
            "extension_id": value["programme"]["extension_id"],
            "authorization_digest": value["programme"]["authorization_digest"],
            "row_digest": extension.PARENT_DIGEST,
        }
        or set(value["programme"])
        != {
            "extension_id",
            "authorization_digest",
            "programme_expires_at",
            "expires_at",
            "row_digest",
        }
        or value["programme"].get("row_digest") != extension.PARENT_DIGEST
        or value["programme"].get("programme_expires_at") != extension.PROGRAMME_EXPIRY
        or _digest(value["history"]) != extension.HISTORY_DIGEST
        or core.get("stopped_v18_scope")
        != {
            "scope_id": extension.SCOPE_ID,
            "row_digest": extension.SCOPE_DIGEST,
        }
        or _digest(core.get("basis_members")) != extension.BASIS_MEMBERS_DIGEST
        or _digest(core.get("retained_exceptions")) != extension.HOLDS_DIGEST
    ):
        raise AdmissionError("campaign_v19_extension_or_retained_history_drift")
    if (
        core.get("revision") != EXTENSION_REVISION
        or core.get("expiry_policy") != value["expiry_policy"]
        or value.get("snapshot_digest") != SNAPSHOT_DIGEST
        or core.get("snapshot_digest") != SNAPSHOT_DIGEST
        or core.get("campaign_limits") != LIMITS
        or core.get("basis") != value["history"]
        or core.get("plan_digest") != plan_digest(value)
        or value["campaign_extension"]["proposal_digest"] != _digest(core)
    ):
        raise AdmissionError("campaign_v19_capacity_or_snapshot_drift")
