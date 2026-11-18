"""Frozen prospective continuation of only v19's unrun Research/probe identities."""

from __future__ import annotations

import hashlib
import os
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_continuation_policy import (
    CASE_MAP,
    DEADLINES,
    LIMITS,
    PERIOD_LIMITS,
    PROFILE,
    PROGRAM_LIMITS,
    PROGRAMME_EXPIRY,
    PROGRESSION,
    REVISION,
    ROUTES,
)

BASE = "00cc2c78e66fcc58c16a5afcf24db3c5177b6a8940ef2638c07a841edeacf48d"
ROOT = Path(__file__).resolve().parents[2]


def producer_bindings() -> dict[str, str]:
    names = (
        "d5_continuation_policy.py",
        "d5_continuation_authority.py",
        "d5_continuation_packet.py",
        "d5_continuation_report.py",
        "d5_case_isolation.py",
        "d5_behavior_scoring.py",
        "d5_quality_guidance.py",
    )
    return {
        n: "sha256:" + hashlib.sha256((ROOT / "src/workspace" / n).read_bytes()).hexdigest()
        for n in names
    }


def predecessor() -> dict[str, Any]:
    from src.workspace.d5_benchmark import read

    value = read(
        ROOT / "planning/15-evaluation-audit-and-recovery/evidence/comparison-v19/packet.json.gz"
    )
    if (
        value.get("packet_digest") != BASE
        or _digest({k: v for k, v in value.items() if k != "packet_digest"}) != BASE
    ):
        raise AdmissionError("continuation_immutable_v19_packet_changed")
    return value


def plan_digest(p: dict[str, Any]) -> str:
    return _digest(
        {
            k: v
            for k, v in p.items()
            if k not in {"packet_digest", "campaign_extension", "created_at", "application_commit"}
        }
    )


def _upgrade(case: dict[str, Any], *, probe: bool) -> dict[str, Any]:
    from src.workspace.assistance import capacity, producer_binding
    from src.workspace.d5_adapter import initial_context
    from src.workspace.d5_operations import wire
    from src.workspace.d5_quality_guidance import GUIDANCE_VERSION

    value: dict[str, Any] = deepcopy(case["sealed"])
    value["producer"]["code"] = producer_binding()
    if not probe:
        value["quality_guidance_revision"] = GUIDANCE_VERSION
        value["candidate_initial_wire"] = wire(initial_context(value), ROUTES)
        value["capacity"] = capacity(value)
    return value


def metadata() -> dict[str, Any]:
    """Fixed interpretation and immutable v19 ancestry, never caller bookkeeping."""
    return {
        "programme": {
            "extension_id": "research-evaluation-20261105-v1-comparison-v19",
            "authorization_digest": "ae43a8ca9e83991aabe21943d73a67a3d6ab7101382b3389f8d2696feb88f802",
            "programme_expires_at": "2026-11-21T11:03:57+00:00",
            "expires_at": "2026-11-18T00:34:09+00:00",
            "row_digest": "f521d303ec1237c675a6258dcde0eb806963b95b3e49ee053d07a31b5ad0ebff",
        },
        "development_reuse": {
            "old_packet": BASE,
            "old_checks_reused": False,
            "reason": "Draft and repair guidance, request contexts and producer hashes change in both modes; old input-bound verdicts remain historical. Two fresh development contracts are required.",
        },
        "continuation_lineage": {
            "preserved_original_evaluation_denominator": 8,
            "original_v19_report_quality": "FAIL",
            "original_v19_attempted_evaluation": 4,
            "unrun_research_references": list(CASE_MAP.values())[2:6],
            "new_evaluation_denominator": 4,
            "fresh_heldout": False,
        },
        "stop_policy": PROGRESSION["global_stop"],
    }


def freeze(store: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_behavior_scoring import POLICY
    from src.workspace.d5_benchmark import check_storage
    from src.workspace.d5_campaign_v19_packet import public_programme_authority, verify_discovery
    from src.workspace.d5_continuation_authority import SNAPSHOT_DIGEST, proposal
    from src.workspace.d5_freeze import code_bindings
    from src.workspace.d5_quality_guidance import GUIDANCE_VERSION

    if (
        os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
        or os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
    ):
        raise AdmissionError("continuation_freeze_offline_only")
    with store.pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone():
            raise AdmissionError("continuation_freeze_fixture_required")
    if _digest(snapshot) != SNAPSHOT_DIGEST:
        raise AdmissionError("continuation_exact_snapshot_required")
    old = predecessor()
    check_storage(store, old)
    verify_discovery(old)
    originals = {c["id"]: c for c in (*old["cases"], *old["probes"])}
    cases = []
    probes = []
    for key, prior in CASE_MAP.items():
        probe = "probe-" in key
        case = deepcopy(originals[prior])
        case.update(
            id=key, reference_case_id=prior, protocol_cohort=REVISION, predecessor_packet=BASE
        )
        case["sealed"] = _upgrade(case, probe=probe)
        if not probe:
            case["wire_digest"] = _digest(case["sealed"]["candidate_initial_wire"])
            cases.append(case)
        else:
            probes.append(case)
    parent = next(
        r for r in snapshot["recorded_keyed_continuations"] if r["scope_id"] == "d5-" + BASE[:24]
    )
    value = {
        **deepcopy(old),
        "revision": REVISION,
        "approved": False,
        "application_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "predecessor_packet": BASE,
        "programme": public_programme_authority(parent),
        "history": snapshot["history"],
        "snapshot_digest": SNAPSHOT_DIGEST,
        "limits": deepcopy(LIMITS),
        "cases": cases,
        "probes": probes,
        "schedule": list(CASE_MAP),
        "measurement_cases": [],
        "progression": deepcopy(PROGRESSION),
        "continuation_producer": producer_bindings(),
        "quality_guidance_revision": GUIDANCE_VERSION,
        "code": code_bindings(),
        "adapter": qualification_producer(),
        "scoring": {
            **deepcopy(old["scoring"]),
            "revision": POLICY,
            "evaluation_denominator": 4,
            "historical_evaluation_denominator": 8,
            "completion_min_ratio": 0.90,
            "interpretation": "Behavior under frozen evidence versus full research-need fulfillment are separate. No pooling of old/development claims into current thresholds.",
        },
        "development_reuse": {
            "old_packet": BASE,
            "old_checks_reused": False,
            "reason": "Draft and repair guidance, request contexts and producer hashes change in both modes; old input-bound verdicts remain historical. Two fresh development contracts are required.",
        },
        "continuation_lineage": {
            "preserved_original_evaluation_denominator": 8,
            "original_v19_report_quality": "FAIL",
            "original_v19_attempted_evaluation": 4,
            "unrun_research_references": list(CASE_MAP.values())[2:6],
            "new_evaluation_denominator": 4,
            "fresh_heldout": False,
        },
        "stop_policy": PROGRESSION["global_stop"],
    }
    value.update(metadata())
    value.pop("packet_digest", None)
    value.pop("campaign_extension", None)
    with store.pool.connection() as conn:
        value["campaign_extension"] = proposal(
            conn, value["program_id"], plan_digest(value), snapshot
        )
    value["packet_digest"] = _digest(value)
    verify_packet(value)
    return value


def verify_packet(p: dict[str, Any]) -> None:
    from src.workspace.assistance_comparison_contract import schemas
    from src.workspace.d5_adapter import initial_context, qualification_producer
    from src.workspace.d5_behavior_scoring import POLICY
    from src.workspace.d5_continuation_authority import SNAPSHOT_DIGEST
    from src.workspace.d5_freeze import code_bindings
    from src.workspace.d5_operations import wire
    from src.workspace.d5_quality_guidance import GUIDANCE_VERSION
    from src.workspace.provider_schema_compat import guard

    old = predecessor()
    if any(p.get(k) != v for k, v in metadata().items()):
        raise AdmissionError("continuation_interpretation_or_ancestry_drift")
    if (
        p.get("revision") != REVISION
        or p.get("approved") is not False
        or p.get("predecessor_packet") != BASE
        or p.get("packet_digest") != _digest({k: v for k, v in p.items() if k != "packet_digest"})
        or p.get("limits") != LIMITS
        or p.get("schedule") != list(CASE_MAP)
        or p.get("operation_routes") != ROUTES
        or p.get("operation_deadlines") != DEADLINES
        or p.get("snapshot_digest") != SNAPSHOT_DIGEST
        or p.get("measurement_cases") != []
        or p.get("progression") != PROGRESSION
        or p.get("code") != code_bindings()
        or p.get("adapter") != qualification_producer()
        or p.get("continuation_producer") != producer_bindings()
        or p.get("quality_guidance_revision") != GUIDANCE_VERSION
        or p.get("human_qualification") is not False
        or len(p.get("cases", [])) != 6
        or len(p.get("probes", [])) != 4
    ):
        raise AdmissionError("continuation_frozen_protocol_drift")
    # Every inherited metadata field stays fixed, not merely the obvious text
    # and evidence fields. Rehashing a coordinated mutation is not authority.
    revised = {
        "revision",
        "application_commit",
        "created_at",
        "predecessor_packet",
        "programme",
        "history",
        "snapshot_digest",
        "limits",
        "cases",
        "probes",
        "schedule",
        "measurement_cases",
        "progression",
        "code",
        "adapter",
        "scoring",
        "stop_policy",
        "campaign_extension",
        "packet_digest",
        "continuation_producer",
        "quality_guidance_revision",
        "development_reuse",
        "continuation_lineage",
    }
    if set(p) != set(old) | revised or any(p[k] != old[k] for k in old if k not in revised):
        raise AdmissionError("continuation_frozen_sources_ranking_references_changed")
    import re

    try:
        created = datetime.fromisoformat(p["created_at"])
        valid_created = created.tzinfo is not None and created.utcoffset() == timedelta(0)
    except (TypeError, ValueError):
        valid_created = False
    if (
        not isinstance(p["application_commit"], str)
        or not re.fullmatch(r"[a-f0-9]{40}", p["application_commit"])
        or not valid_created
    ):
        raise AdmissionError("continuation_application_or_creation_identity_invalid")
    expected_scoring = {
        **old["scoring"],
        "revision": POLICY,
        "evaluation_denominator": 4,
        "historical_evaluation_denominator": 8,
        "completion_min_ratio": 0.90,
        "interpretation": "Behavior under frozen evidence versus full research-need fulfillment are separate. No pooling of old/development claims into current thresholds.",
    }
    if p.get("scoring") != expected_scoring:
        raise AdmissionError("continuation_frozen_substantive_threshold_drift")
    original = {c["id"]: c for c in (*old["cases"], *old["probes"])}
    for current, (key, prior_id) in zip((*p["cases"], *p["probes"]), CASE_MAP.items(), strict=True):
        prior = original[prior_id]
        probe = key.endswith(tuple("probe-" + str(i) for i in range(1, 5)))
        if (
            current.get("id") != key
            or current.get("reference_case_id") != prior_id
            or current.get("protocol_cohort") != REVISION
            or current.get("predecessor_packet") != BASE
            or set(current)
            != set(prior) | {"reference_case_id", "protocol_cohort", "predecessor_packet"}
        ):
            raise AdmissionError("continuation_case_lineage_drift")
        for field in prior:
            if (
                field
                not in (
                    {"id", "sealed", "predecessor_packet"}
                    | ({"wire_digest"} if not probe else set())
                )
                and current.get(field) != prior[field]
            ):
                raise AdmissionError("continuation_question_or_selection_drift")
        sealed = current["sealed"]
        expected = _upgrade(prior, probe=probe)
        if sealed != expected:
            raise AdmissionError("continuation_sealed_request_or_source_drift")
        if probe:
            if current["wire"] != prior["wire"]:
                raise AdmissionError("continuation_probe_body_or_reference_drift")
            body = current["wire"]
        else:
            schema = schemas(
                list(sealed["units"]), sealed["response_purpose"], sealed["task_policy"]
            )
            body = wire(initial_context(sealed), ROUTES)
            if (
                schema != sealed["response_schemas"]
                or body != sealed["candidate_initial_wire"]
                or current["wire_digest"] != _digest(body)
            ):
                raise AdmissionError("continuation_actual_schema_or_wire_drift")
        guard(body)
        guard({k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}})
    from src.workspace import d5_continuation_authority as authority

    core = p["campaign_extension"]["core"]
    fixed = {
        "revision": authority.AUTHORITY_REVISION,
        "extension_id": authority.EXTENSION_ID,
        "program_id": authority.PROGRAM_ID,
        "parent_v19": {
            "extension_id": metadata()["programme"]["extension_id"],
            "authorization_digest": metadata()["programme"]["authorization_digest"],
            "row_digest": authority.PARENT_ROW,
            "scope_id": authority.PARENT_SCOPE,
            "scope_row_digest": authority.PARENT_SCOPE_ROW,
        },
        "capacity_ancestor": {
            "extension_id": authority.PROGRAM_ID + "-capacity-v15",
            "authorization_digest": "6dfa60a072ea45fbd097e1b26b06d27d489d18afaaf57d06d49c5af2a15c7596",
            "row_digest": "e04732bb950b9a1d173aefe6efec97bf8ae19ab917d5186c8d2d1f1f1605013a",
        },
        "snapshot_digest": authority.SNAPSHOT_DIGEST,
        "limits": PROGRAM_LIMITS,
        "period_limits": PERIOD_LIMITS,
        "campaign_limits": LIMITS,
        "plan_digest": plan_digest(p),
        "programme_expiry": PROGRAMME_EXPIRY,
        "expiry_policy": {"campaign_max_seconds_from_approval": 86400, "programme_renewal": False},
        "capacity_change": False,
        "budget_change": False,
    }
    if (
        set(p["campaign_extension"]) != {"core", "proposal_digest", "approved"}
        or p["campaign_extension"]["approved"] is not False
        or set(core) != set(fixed) | {"basis_members", "basis", "retained_exceptions"}
        or any(core.get(k) != v for k, v in fixed.items())
        or _digest(core["basis_members"]) != authority.MEMBERS_DIGEST
        or _digest(core["basis"]) != authority.HISTORY_DIGEST
        or _digest(core["retained_exceptions"]) != authority.HOLDS_DIGEST
        or core["basis"] != p["history"]
        or p["campaign_extension"]["proposal_digest"] != _digest(core)
    ):
        raise AdmissionError("continuation_plan_or_authority_binding_drift")


def owners(p: dict[str, Any]) -> tuple[str, str]:
    owner = "d5-continuation-" + p["packet_digest"][:16] + "-run"
    return owner, owner


def compile_packet(p: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_adapter import prepare_input

    actor = owners(p)[0]
    scope = "d5-" + p["packet_digest"][:24]
    compiled = {}
    for index, c in enumerate((*p["cases"], *p["probes"])):
        probe = index >= 6
        raw = prepare_input(
            c["sealed"],
            scope_id=scope,
            packet_digest=p["packet_digest"],
            case_id=c["id"],
            operation="probe" if probe else "workflow",
            probe_wire=c["wire"] if probe else None,
            programme_amendment_digest=p["campaign_extension"]["proposal_digest"],
            operation_routes=ROUTES,
            scope_profile=PROFILE,
            operation_deadlines=DEADLINES,
            capacity_policy=p["capacity_policy"],
            repair_located_prose=True,
        ).snapshot()
        raw["settings"].update(
            d5_campaign_revision=REVISION, continuation_producer=p["continuation_producer"]
        )
        compiled[c["id"]] = {
            "owner": actor,
            "stage": "D" if probe else "B" if index < 2 else "C",
            "input": raw,
        }
    return compiled


def template(p: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_authorization import case_bindings

    verify_packet(p)
    compiled = compile_packet(p)
    return {
        "approved": False,
        "approved_by": None,
        "approved_at": None,
        "approval_source": None,
        "expires_at": None,
        "authorization_kind": "owner",
        "transport_mode": "provider",
        "campaign_revision": REVISION,
        "packet_digest": p["packet_digest"],
        "scope_id": "d5-" + p["packet_digest"][:24],
        "limits": p["limits"],
        "members": sorted({e["owner"] for e in compiled.values()}),
        "stages": ["B", "C", "D"],
        "case_order": list(compiled),
        "case_bindings_digest": _digest(case_bindings(compiled)),
        "code_bindings": p["code"],
        "adapter_binding": p["adapter"],
        "source_bindings": p["source_bindings"],
        "campaign_extension": p["campaign_extension"],
        "continuation_producer": p["continuation_producer"],
        "capacity_amendment_approved": False,
        "budget_adjustment_approved": False,
        "historical_uncertainty_exception_approved": False,
        "programme_limits": PROGRAM_LIMITS,
        "period_limits": PERIOD_LIMITS,
        "programme_expires_at": PROGRAMME_EXPIRY,
    }


def record(store: Any, p: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_authorization import record_external as scope_record
    from src.workspace.d5_benchmark import check_storage
    from src.workspace.d5_continuation_authority import record_external
    from src.workspace.d5_fixture import prepare_projects

    expected = template(p)
    mutable = {
        "approved",
        "approved_by",
        "approved_at",
        "approval_source",
        "expires_at",
        "authorization_kind",
        "transport_mode",
        "historical_uncertainty_exception_approved",
    }
    if set(receipt) != set(expected) or any(
        receipt[k] != expected[k] for k in expected if k not in mutable
    ):
        raise AdmissionError("continuation_exact_owner_receipt_required")
    # Fail-closed two-phase recording: an authority row alone admits nothing.
    # An identical receipt may resume source/project preparation and scope
    # registration without a new identity, changed expiry or provider contact.
    # Different receipts are immutable-rejected by record_external.
    check_storage(store, p)
    activation = record_external(store, receipt, packet=p)
    prepare_projects(store, p)
    scope = scope_record(
        store,
        packet_digest=p["packet_digest"],
        scope_id=receipt["scope_id"],
        program_id=p["program_id"],
        compiled=compile_packet(p),
        receipt=receipt,
        expected_history=p["history"],
    )
    return {
        "activation": activation,
        "scope": scope,
        "provider_contacts": 0,
        "expires_at": receipt["expires_at"],
    }


def authorize_fixture(store: Any, p: dict[str, Any]) -> dict[str, Any]:
    with store.pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone():
            raise AdmissionError("continuation_fixture_database_required")
    if (
        os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
        or os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
    ):
        raise AdmissionError("continuation_fixture_mock_only")
    value = template(p)
    now = datetime.now(UTC)
    value.update(
        approved=True,
        approved_by="Synthetic disposable fixture, not owner approval",
        approved_at=now.isoformat(),
        approval_source="Offline fixture only",
        expires_at=min(
            now + timedelta(hours=23), datetime.fromisoformat(PROGRAMME_EXPIRY)
        ).isoformat(),
        authorization_kind="offline_fixture",
        transport_mode="mock",
        historical_uncertainty_exception_approved=True,
    )
    return record(store, p, value)
