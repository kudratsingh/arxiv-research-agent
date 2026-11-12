"""Versioned fixed-evidence development packet for the existing protected runner.

No approval recorder or provider client. Historical packets/scorer are unchanged.
"""

from __future__ import annotations

import subprocess
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from src.workspace.admission import AdmissionError, _digest
from src.workspace.assistance_contract import digest as response_digest
from src.workspace.assistance_contract import schemas
from src.workspace.assistance_coverage import COVERAGE_REVISION
from src.workspace.d5_coverage_policy import LIMITS, PROFILE, PROGRAM_LIMITS

REVISION = "d5-request-coverage-development-packet-v1"
PREDECESSOR = "sha256:14e761c2bb3139428a0093caae022a175b37f81bd6ce35f5a0082367a358b101"
CASE_IDS = [
    "development-v8-learn-conditions",
    "development-v8-research-retrieval",
    "development-v8-research-insufficient",
]


def is_packet(packet: dict[str, Any]) -> bool:
    return packet.get("revision") in {REVISION, "d5-coverage-shapes-development-packet-v2", "d5-coverage-authority-development-packet-v3", "d5-operation-deadlines-development-packet-v1"}


def owners(packet: dict[str, Any]) -> tuple[str, str]:
    prefix = "d5-coverage-" + packet["packet_digest"][:16]
    return prefix + "-run", prefix + "-measure"


def measurement_bindings(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for i, case in enumerate(cases, 1):
        body = {
            k: v
            for k, v in case["sealed"]["candidate_initial_wire"].items()
            if k not in {"max_tokens", "temperature"}
        }
        result.append(
            {
                "id": f"measure-{i}",
                "workflow": case["id"],
                "body": body,
                "request_digest": _digest(body),
                "model": body["model"],
            }
        )
    return result


def canonical_request(sealed: dict[str, Any], corpus: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind metadata hashes separately from unchanged retained-material hashes.

    The predecessor was prepared in a disposable fixture whose version rows
    used material source hashes. Canonical storage uses its own metadata hash.
    Only these two local metadata-binding fields change; the transmitted body,
    selected passages, source identity and all other sealed fields remain exact.
    """
    hashes = {row["version_id"]: row.get("content_hash") for row in corpus}
    versions = set(sealed["version_hashes"])
    if any(not isinstance(hashes.get(v), str) or not hashes[v] for v in versions):
        raise AdmissionError("coverage_canonical_metadata_required")
    result = deepcopy(sealed)
    result["version_hashes"] = {v: hashes[v] for v in sorted(versions)}
    result["source_version_hash"] = hashes[sealed["assistance"]["version_id"]]
    return result


def current_request(sealed: dict[str, Any], corpus: list[dict[str, Any]]) -> dict[str, Any]:
    """Fresh local replay binds current producer, without rewriting an old packet."""
    from src.workspace.assistance import producer_binding

    result = canonical_request(sealed, corpus)
    result["producer"]["code"] = producer_binding()
    return result


def verify_controls(packet: dict[str, Any]) -> None:
    if packet.get("revision") == "d5-operation-deadlines-development-packet-v1":
        from src.workspace.d5_timeout_packet import verify_timeout

        verify_timeout(packet)
        return
    if packet.get("revision") == "d5-coverage-authority-development-packet-v3":
        from src.workspace.d5_coverage_authority_packet import verify_shapes

        verify_shapes(packet)
        return
    if packet.get("revision") == "d5-coverage-shapes-development-packet-v2":
        from src.workspace.d5_coverage_shapes_packet import verify_shapes

        verify_shapes(packet)
        return

    from pathlib import Path

    from anthropic import transform_schema

    from src.workspace.assistance import CoverageChecks, producer_binding
    from src.workspace.d5_benchmark import read
    from src.workspace.d5_operations import ROUTES

    original = read(
        Path(__file__).resolve().parents[2]
        / "planning/14-explore-and-research-modes/d5/evidence/request-coverage-v8/proposal.json.gz"
    )
    if (
        original["packet_digest"] != PREDECESSOR
        or response_digest({k: v for k, v in original.items() if k != "packet_digest"})
        != PREDECESSOR
    ):
        raise AdmissionError("coverage_predecessor_manifest_changed")
    if (
        packet.get("predecessor_proposal") != PREDECESSOR
        or packet.get("limits") != LIMITS
        or packet.get("planned_development_cases") != CASE_IDS
        or packet.get("measurement_cases") != CASE_IDS
        or packet.get("probes") != []
        or packet.get("scope_profile") != PROFILE
        or packet.get("measurement_reuse")
        or packet.get("human_qualification") is not False
        or len(packet["cases"]) != 3
    ):
        raise AdmissionError("coverage_frozen_schedule_changed")
    if (
        packet.get("operation_routes") != ROUTES
        or packet.get("measurements") != measurement_bindings(packet["cases"])
        or packet.get("checker_schemas")
        != {"local": CoverageChecks.model_json_schema(), "wire": transform_schema(CoverageChecks)}
    ):
        raise AdmissionError("coverage_stage_schema_or_measurement_binding_drift")
    if packet["programme"].get("limits") != PROGRAM_LIMITS:
        raise AdmissionError("coverage_frozen_programme_limits_changed")
    try:
        expiry = datetime.fromisoformat(packet["programme"]["expires_at"])
        if expiry.tzinfo is None:
            raise ValueError("timezone required")
    except (KeyError, ValueError, TypeError) as exc:
        raise AdmissionError("coverage_frozen_programme_expiry_required") from exc
    expected = {c["id"]: c for c in original["cases"]}
    for case in packet["cases"]:
        reference = expected.get(case["id"])
        if (
            not reference
            or case.get("cohort") != "development"
            or case.get("pipeline") != "fixed_evidence_diagnostic"
            or case["sealed"] != current_request(reference["sealed"], packet["corpus"])
            or case["mode"] != reference["input"]["mode"]
            or case["question"] != reference["input"]["follow_up"]
        ):
            raise AdmissionError("coverage_development_identity_or_context_changed")
        sealed = case["sealed"]
        if (
            sealed["schema_revision"] != COVERAGE_REVISION
            or sealed["producer"]["code"] != producer_binding()
            or sealed["response_schemas"]
            != schemas(
                list(sealed["units"]),
                purpose=sealed["response_purpose"],
                revision=COVERAGE_REVISION,
                task_policy=sealed["task_policy"],
            )
        ):
            raise AdmissionError("coverage_producer_or_schema_changed")
    if (
        [c["id"] for c in packet["cases"]] != CASE_IDS
        or packet["programme"]["program_id"] != packet["program_id"]
        or packet["programme"]["capacity_proposal_digest"]
        != packet["programme_amendment"]["proposal_digest"]
    ):
        raise AdmissionError("coverage_scope_or_order_changed")


def compile_controls(packet: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_adapter import prepare_input

    run_owner, count_owner = owners(packet)
    compiled = {}
    for i, case in enumerate(packet["cases"], 1):
        for key, owner, stage, operation in (
            (case["id"], run_owner, "B", "workflow"),
            (f"measure-{i}", count_owner, "A", "measurement"),
        ):
            compiled[key] = {
                "owner": owner,
                "stage": stage,
                "input": prepare_input(
                    case["sealed"],
                    scope_id="d5-" + packet["packet_digest"][:24],
                    packet_digest=packet["packet_digest"],
                    case_id=key,
                    operation=operation,
                    programme_amendment_digest=packet["programme"]["capacity_proposal_digest"],
                    operation_routes=packet["operation_routes"],
                    repair_located_prose=True,
                    scope_profile=packet["scope_profile"],
                    programme_binding=packet["programme"],
                    operation_deadlines=packet.get("operation_deadlines"),
                ).snapshot(),
            }
    return compiled


def freeze_controls(
    manifest: dict[str, Any], snapshot: dict[str, Any], programme: dict[str, Any]
) -> dict[str, Any]:
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_freeze import code_bindings
    from src.workspace.d5_operations import ROUTES

    if manifest.get("packet_digest") != PREDECESSOR or manifest.get("approved") is not False:
        raise AdmissionError("coverage_expected_unapproved_predecessor_required")
    corpus = [r["data"] for r in snapshot["tables"]["workspace_versions"]]
    cases = [
        {
            "id": c["id"],
            "cohort": "development",
            "pipeline": "fixed_evidence_diagnostic",
            "mode": c["input"]["mode"],
            "question": c["input"]["follow_up"],
            "sealed": current_request(c["sealed"], corpus),
            "wire_digest": _digest(c["initial_wire"]),
            "human_review": None,
        }
        for c in manifest["cases"]
    ]
    materials = [r["data"] for r in snapshot["tables"]["workspace_material"]]
    packet = {
        "revision": REVISION,
        "approved": False,
        "predecessor_proposal": PREDECESSOR,
        "scope_profile": PROFILE,
        "limits": deepcopy(LIMITS),
        "program_id": snapshot["program_id"],
        "programme": programme,
        "programme_amendment": {"proposal_digest": programme["capacity_proposal_digest"]},
        "history": snapshot["history"],
        "snapshot_digest": _digest(snapshot),
        "code": code_bindings(),
        "adapter": qualification_producer(),
        "operation_routes": ROUTES,
        "cases": cases,
        "planned_development_cases": CASE_IDS,
        "measurement_cases": CASE_IDS,
        "probes": [],
        "materials": materials,
        "corpus": corpus,
        "profile": snapshot["profile"],
        "human_qualification": False,
        "fresh_held_out": False,
        "intake": "Retained public snapshot replay, not fresh intake or complete-paper extraction",
        "stop_rules": "First drift, admission/provider/contract error, cancellation or uncertain completion stops; no automatic retries, model substitution, new IDs or source expansion",
    }
    from anthropic import transform_schema

    from src.workspace.assistance import CoverageChecks

    packet["checker_schemas"] = {
        "local": CoverageChecks.model_json_schema(),
        "wire": transform_schema(CoverageChecks),
    }
    packet["measurements"] = measurement_bindings(cases)
    packet["application_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()
    packet["created_at"] = datetime.now(UTC).isoformat()
    packet["packet_digest"] = _digest(packet)
    verify_controls(packet)
    return packet


def report_controls(store: Any, packet: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_results import QualificationResults
    from src.workspace.qualification_budget import census

    compiled = compile_controls(packet)
    snapshots = {}
    with store.pool.connection() as conn:
        for key, entry in compiled.items():
            job_id = (
                "gen-" + _digest([entry["owner"], entry["input"]["settings"]["d5_request_id"]])[:40]
            )
            if conn.execute(
                "SELECT 1 FROM workspace_generation_jobs WHERE id=%s AND owner=%s",
                (job_id, entry["owner"]),
            ).fetchone():
                snapshots[key] = QualificationResults(store).snapshot(entry["owner"], job_id)
        members = [
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
                (packet["program_id"],),
            )
        ]
        cumulative = census(conn, members[0], members=members)
        new = census(conn, owners(packet)[0], members=list(owners(packet)))
        baseline = conn.execute(
            "SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s",
            (packet["program_id"],),
        ).fetchone()[0]
        programme_jobs = len(
            set(cumulative["generation_job_ids"]) - set(baseline["generation_job_ids"])
        )
    cases = [
        {
            "id": c["id"],
            "cohort": "development",
            "completion": snapshots.get(c["id"], {}).get("state") == "ready",
            "state": snapshots.get(c["id"], {}).get("state", "unrun"),
            "request_coverage": (snapshots.get(c["id"], {}).get("assistance_output") or {}).get(
                "request_coverage"
            ),
            "human_review": None,
        }
        for c in packet["cases"]
    ]
    simulated = bool(snapshots) and all(v.get("simulated") for v in snapshots.values())
    measurements = []
    for sealed in packet["measurements"]:
        observed = snapshots.get(sealed["id"], {})
        result = observed.get("result") or {}
        tokens = result.get("input_tokens")
        measurements.append(
            {
                "id": sealed["id"],
                "workflow": sealed["workflow"],
                "state": observed.get("state", "unrun"),
                "model": sealed["model"],
                "request_digest": sealed["request_digest"],
                "receipt_digest": result.get("count_request_digest"),
                "provider_input_tokens": None if simulated else tokens,
                "synthetic_input_tokens": tokens if simulated else None,
                "fits_16000": tokens <= 16000 if type(tokens) is int else None,
                "basis": result.get("basis", "unmeasured"),
            }
        )
    return {
        "revision": REVISION,
        "packet_digest": packet["packet_digest"],
        "execution_mode": "mock" if simulated else "provider" if snapshots else "unrun",
        "measurements": measurements,
        "basis": "Protected fixed-evidence development controls. Synthetic counts/verdicts in mock mode are software evidence only; provider outputs remain quarantined. No retrieval or human qualification claim.",
        "cases": cases,
        "raw_results": snapshots,
        "accounting": {
            "cumulative": cumulative,
            "cumulative_programme_jobs": programme_jobs,
            "new_scope": new,
            "new_funded_jobs": len(new["generation_job_ids"]),
            "historical": packet["history"],
            "actual_new_messages": 0 if simulated or not snapshots else new["messages"],
            "actual_new_counts": 0 if simulated or not snapshots else new["counts"],
            "workflow_usd": str(
                sum(Decimal(v.get("workflow_usd", "0")) for v in snapshots.values())
            ),
            "checker_usd": str(sum(Decimal(v.get("checker_usd", "0")) for v in snapshots.values())),
            "unknown_usd": new["unknown_usd"],
        },
        "acceptance": "HOLD: human qualification is out of scope and model quality is unmeasured",
        "checker_qualified": False,
        "everyday_generation": False,
        "human_labels": None,
    }


def markdown_controls(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Request-coverage development controls",
            "",
            report["basis"],
            "",
            "| Case | Cohort | State |",
            "|---|---|---|",
            *[f"| {c['id']} | development | {c['state']} |" for c in report["cases"]],
            "",
            report["acceptance"],
            "",
            "| Measurement | State | Provider tokens | Synthetic tokens |",
            "|---|---|---:|---:|",
            *[
                f"| {m['id']} | {m['state']} | {m['provider_input_tokens']} | {m['synthetic_input_tokens']} |"
                for m in report.get("measurements", [])
            ],
            "",
            "Accounting and exact passage/request/usage receipts are in results.json; archived v8r4b scoring is unchanged.",
            "",
        ]
    )
