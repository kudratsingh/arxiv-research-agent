"""Four-request prospective consistency diagnostic; freezing grants no authority.

The completed schema controls and stopped v17r2 jobs are historical. No body or
measurement is replayed. All code, schemas, source context and current financial
history are sealed before a separate external owner decision.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from importlib.metadata import version
from typing import Any

from src.workspace import assistance_consistency_checks as checks
from src.workspace import assistance_consistency_contract as codec
from src.workspace import d5_compatibility_packet as previous
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import checker_context
from src.workspace.d5_capacity_policy import ROUTES
from src.workspace.grounding import EvidenceRef
from src.workspace.provider_schema_compat import guard

REVISION = previous.SUCCESSOR_REVISION
ORDER = ("learn-compact", "research-compact", "checker-small", "checker-maximum")
LIMITS = {"jobs": 4, "messages": 4, "counts": 4, "new_USD": "1.40", "concurrency": 1}


def _wire(context: dict[str, Any], schema: dict[str, Any], *, check: bool) -> dict[str, Any]:
    value = previous._wire(context, schema, check=check)
    assert isinstance(value["system"], str)
    value["system"] += (
        " Categorize coverage critiques separately from unsupported factual prose. Supply every required part and location judgment. Do not supply a global prose-clear flag; aggregates are server-derived."
        if check
        else " Question context links assert no premise; factual premises require explicit scored claim references. Use partial coverage when useful answers retain genuine gaps. Preserve every gap. The body tag does not grant full-answer credit."
    )
    return value


def _sealed(source: dict[str, Any], policy: dict[str, Any], purpose: str) -> dict[str, Any]:
    value: dict[str, Any] = deepcopy(source["context"]["sealed_request"])
    value.update(units=deepcopy(source["units"]), task_policy=policy, response_purpose=purpose)
    return value


def _checker(source: dict[str, Any], materials: Any) -> dict[str, Any]:
    policy = {**source["policy"], codec.KEY: codec.REVISION}
    purpose = source["purpose"]
    draft = deepcopy(source["fixed_draft"])
    body = draft["response"]
    body["disposition"] = "answer"
    for q in body["questions"]:
        refs = q.pop("claim_ids")
        q.update(context_claim_ids=refs, premise_claim_ids=[])
    for part in policy["requested_parts"]:
        row = body["coverage"][part["id"]]
        row.setdefault("answer_claim_ids", [])
        if part["kind"] == "source_note":
            row.update(
                status="partial",
                answer_claim_ids=list(row["context_claim_ids"]),
                context_claim_ids=[],
                gap_reasons=["metric_definition", "protocol"],
            )
    sealed = _sealed(source, policy, purpose)
    context = checker_context(sealed, draft, materials)
    schemas = checks.schemas(context)
    return {
        **{k: deepcopy(source[k]) for k in ["id", "family", "purpose", "units"]},
        "encoding": checks.REVISION,
        "policy": policy,
        "fixed_draft": draft,
        "sealed": sealed,
        "context": context,
        "schemas": schemas,
        "body": _wire(context, schemas["wire"], check=True),
        "reservation_USD": "0.50",
        "machine_reference": None,
        "human_labels": None,
        "conditional": "checker-small complete and locally valid"
        if source["id"] == "checker-maximum"
        else None,
        "fixture_basis": "Fixed source-only synthetic shape control, including intentionally correlated repeated claims at maximum size. No human gold or model-quality evidence.",
    }


def freeze(snapshot: dict[str, Any], predecessor: dict[str, Any]) -> dict[str, Any]:
    history = snapshot["history"]
    if (
        history["messages"] != 76
        or history["counts"] != 101
        or history["known_usd"] != "2.252281"
        or history["unknown_usd"] != "2.275066"
        or history["pending_usd"] != "2.275066"
        or history["active_jobs"]
        or len(
            set(history["generation_job_ids"])
            - set(snapshot["programme_baseline"]["generation_job_ids"])
        )
        != 42
    ):
        raise AdmissionError("consistency_42_76_101_checkpoint_required")
    if predecessor.get("revision") != previous.REVISION or _digest(
        {k: v for k, v in predecessor.items() if k != "packet_digest"}
    ) != predecessor.get("packet_digest"):
        raise AdmissionError("consistency_predecessor_packet_drift")
    parent = snapshot["parent_stopped_scope"]
    if (
        parent["state"] != "stopped"
        or parent["packet_digest"] != predecessor["packet_digest"]
        or parent["data"].get("packet") != predecessor
    ):
        raise AdmissionError("consistency_stopped_v17_parent_required")
    cases = []
    for name in ORDER:
        source = next(c for c in predecessor["cases"] if c["id"] == name)
        if source["family"] == "checker":
            case = _checker(source, previous.materials(predecessor))
        else:
            policy = {**source["policy"], codec.KEY: codec.REVISION}
            schemas = codec.schemas(list(source["units"]), source["purpose"], policy)
            context = json.loads(source["body"]["messages"][0]["content"])
            context.update(
                case=name,
                purpose="quarantined v18 consistency compatibility diagnostic",
                task_policy={k: v for k, v in policy.items() if k != codec.KEY},
                format_rule="Only actual claims; server assigns c1,c2 by emission order. Coverage alone maps answer/context roles. Questions separately list topic context and factual premises. Preserve genuine partial/evidence/omission gaps. Aggregates are server-derived; no private notes/history/preferences.",
            )
            case = {
                **{
                    k: deepcopy(source[k])
                    for k in ["id", "family", "purpose", "units", "source_case"]
                },
                "encoding": codec.REVISION,
                "policy": policy,
                "schemas": schemas,
                "context": context,
                "body": _wire(context, schemas["wire"], check=False),
                "reservation_USD": "0.20",
                "machine_reference": None,
                "human_labels": None,
                "conditional": "learn-compact complete and locally valid"
                if name == "research-compact"
                else None,
            }
        case["request_digest"] = _digest(case["body"])
        case["count_digest"] = _digest(
            {k: v for k, v in case["body"].items() if k not in {"max_tokens", "temperature"}}
        )
        cases.append(case)
    value = {
        "revision": REVISION,
        "SDK": {"anthropic": version("anthropic"), "pydantic": version("pydantic")},
        "code": previous.producer(),
        "program_id": snapshot["program_id"],
        "programme_limits": previous.PROGRAM_LIMITS,
        "programme_expiry": snapshot["programme"]["record"]["programme_expires_at"],
        "limits": LIMITS,
        "basis_members": snapshot["members"],
        "basis": history,
        "programme_baseline": snapshot["programme_baseline"],
        "programme_parent": snapshot["programme"],
        "snapshot_digest": _digest(snapshot),
        "source_bindings": deepcopy(predecessor["source_bindings"]),
        "materials": deepcopy(predecessor["materials"]),
        "parent_stopped_scope": parent,
        "retained_liabilities": snapshot["retained_liabilities"],
        "predecessor_packet_digest": predecessor["packet_digest"],
        "cases": cases,
        "private_context": {"notes": False, "history": False, "preferences": False},
        "everyday_generation": False,
        "received_rejection_continuation": False,
        "progression": {
            "first_provider_error": "stop and retain full reservation",
            "research": "only after complete locally valid Compact Learn",
            "maximum": "only after complete locally valid small checker",
            "local_content_rejection": "preserve, skip dependent case; independent fixed checker may proceed",
            "new_uncertainty_drift_accounting_budget_expiry_revocation_cancellation": "stop",
            "max_tokens_or_incomplete_output": "unavailable, no salvage",
            "repairs": 0,
            "automatic_retries": 0,
        },
        "new_approval": False,
        "human_qualification": False,
        "full_campaign_readiness": "NOT ESTABLISHED; no quality or checker qualification inferred.",
    }
    value["packet_digest"] = _digest(value)
    verify(value)
    return value


def verify(packet: dict[str, Any]) -> None:
    if (
        packet.get("revision") != REVISION
        or packet.get("limits") != LIMITS
        or packet.get("programme_limits") != previous.PROGRAM_LIMITS
        or packet.get("code") != previous.producer()
        or packet.get("SDK") != {"anthropic": version("anthropic"), "pydantic": version("pydantic")}
    ):
        raise AdmissionError("consistency_code_SDK_or_limits_drift")
    if (
        _digest({k: v for k, v in packet.items() if k != "packet_digest"})
        != packet.get("packet_digest")
        or tuple(c["id"] for c in packet["cases"]) != ORDER
    ):
        raise AdmissionError("consistency_packet_or_identity_drift")
    if (
        packet.get("received_rejection_continuation") is not False
        or packet.get("new_approval") is not False
    ):
        raise AdmissionError("consistency_no_live_authority_or_rejection_exception")
    for case in packet["cases"]:
        check = case["family"] == "checker"
        body = case["body"]
        route = ROUTES["check_recheck_probe" if check else "draft_repair"]
        guard(body)
        if check:
            expected_context = checker_context(
                case["sealed"], case["fixed_draft"], previous.materials(packet)
            )
            schemas = checks.schemas(expected_context)
            if case["context"] != expected_context:
                raise AdmissionError("consistency_checker_context_drift")
        else:
            schemas = codec.schemas(list(case["units"]), case["purpose"], case["policy"])
            expected_context = case["context"]
            if case["encoding"] != codec.REVISION or not codec.enabled(case["policy"]):
                raise AdmissionError("consistency_policy_drift")
        if (
            case["schemas"] != schemas
            or body != _wire(expected_context, schemas["wire"], check=check)
            or case["reservation_USD"] != ("0.50" if check else "0.20")
            or body["model"] != route["model"]
        ):
            raise AdmissionError("consistency_schema_settings_or_request_drift")
        if case["request_digest"] != _digest(body) or case["count_digest"] != _digest(
            {k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}}
        ):
            raise AdmissionError("consistency_exact_paired_request_drift")


def observed(
    payload: dict[str, Any], case: dict[str, Any], packet: dict[str, Any]
) -> dict[str, Any]:
    if case["family"] == "checker":
        normalized = checks.normalize(payload, case["context"])
        model = checks.Checks.model_validate(normalized)
        return {
            "normalized": normalized,
            "current_response_digest": case["context"]["checked_response_digest"],
            "derived_machine_summary": checks.aggregate(model, case["context"]),
            "human_labels": None,
            "research_quality": "UNMEASURED; fixed synthetic shape control, not independent checker qualification",
        }
    draft, claims = codec.resolve_draft(
        payload,
        {k: EvidenceRef(**v) for k, v in case["units"].items()},
        previous.materials(packet),
        purpose=case["purpose"],
        policy=case["policy"],
    )
    normalized, coverage = codec.normalize(
        payload, list(case["units"]), case["purpose"], case["policy"]
    )
    from src.workspace.grounding import validate_claims

    provenance = validate_claims(claims, previous.materials(packet))
    if any(not a.identity_resolved or not a.scope_compatible for a in provenance.assessments):
        raise AdmissionError("consistency_provenance_invalid")
    return {
        "normalized": normalized,
        "coverage": coverage,
        "reader_view": codec.render(payload, list(case["units"]), case["purpose"], case["policy"]),
        "draft": draft.model_dump(mode="json"),
        "provenance": asdict(provenance),
        "human_labels": None,
        "research_quality": "UNMEASURED; no dynamic checker was dispatched",
    }
