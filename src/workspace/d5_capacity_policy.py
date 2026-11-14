"""One sealed prospective capacity policy; historical contracts stay unchanged.

Soft prose targets never confer support and never reject a complete response.
Aggregate bounds protect storage/transport, independent of provider token counts.
This module grants no authority and performs no provider or database contacts.
"""
from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from typing import Any

REVISION = "d5-comprehensive-capacity-v15"
ASSISTANCE_REVISION = "workspace-assistance-capacity-v15"
CHECKS_REVISION = "workspace-assistance-capacity-checks-v15"
NORMALIZATION_REVISION = "workspace-assistance-capacity-normalization-v15"
CLAIMS_BY_MODE = {"learn": 8, "research": 12}
MAX_SELECTED_UNITS = 12
MAX_CLAIM_CHARACTERS = 10000
MAX_CITATIONS = 6
CITATIONS_BY_MODE = {"learn": 3, "research": 6}
MAX_PARTS = 8
MAX_FINDINGS = 16
MAX_DRAFT_BYTES = 131072
MAX_COMPACT_CHECK_BYTES = 262144
MAX_NORMALIZED_CHECK_BYTES = 1048576
MAX_INTERNAL_BYTES = 8388608
MAX_HTTP_BYTES = 4194304
DEADLINES: dict[str, Any] = {
    "revision": "d5-operation-deadlines-v2-capacity",
    "count_seconds": 60, "draft_seconds": 120, "repair_seconds": 120,
    "check_seconds": 240, "recheck_seconds": 240, "workflow_seconds": 1200,
    "origin": "durable_reservation_created_at",
}
ROUTES: dict[str, Any] = {
    "revision": "d5-sonnet-opus-high-capacity-v3",
    "draft_repair": {
        "model": "claude-sonnet-5-5", "thinking": {"type": "between_tools"},
        "effort": "medium", "input_tokens": 40000, "output_tokens": 8000,
        "prices": {"input": "2", "output": "10", "verified_at": "2026-11-14"},
    },
    "check_recheck_probe": {
        "model": "claude-opus-5-5", "thinking": {"type": "adaptive"},
        "effort": "high", "input_tokens": 40000, "output_tokens": 12000,
        "prices": {"input": "4", "output": "20", "verified_at": "2026-11-14"},
    },
}
POLICY: dict[str, Any] = {
    "revision": REVISION,
    "assistance_revision": ASSISTANCE_REVISION,
    "checker_revision": CHECKS_REVISION,
    "normalization_revision": NORMALIZATION_REVISION,
    "claims_by_mode": CLAIMS_BY_MODE,
    "max_citations_per_claim": MAX_CITATIONS,
    "citations_by_mode": CITATIONS_BY_MODE,
    "max_selected_units": MAX_SELECTED_UNITS,
    "max_materials": 3,
    "max_unit_characters": 1600,
    "max_selected_evidence_utf8_bytes": MAX_DRAFT_BYTES,
    "max_requested_parts": MAX_PARTS,
    "max_prose_findings": MAX_FINDINGS,
    "soft_claim_characters": 500,
    "max_claim_characters": MAX_CLAIM_CHARACTERS,
    "max_procedural_gaps": 3,
    "max_follow_up_intents": 3,
    "soft_reason_characters": 240,
    "raw_draft_utf8_bytes": MAX_DRAFT_BYTES,
    "compact_checker_utf8_bytes": MAX_COMPACT_CHECK_BYTES,
    "normalized_checker_utf8_bytes": MAX_NORMALIZED_CHECK_BYTES,
    "internal_json_bytes": MAX_INTERNAL_BYTES,
    "sealed_input_json_bytes": MAX_INTERNAL_BYTES,
    "http_body_bytes": MAX_HTTP_BYTES,
    "paired_input_tokens_fit": 32000,
    "reservation_input_tokens": 40000,
    "max_messages_per_workflow": 4,
    "max_repairs": 1,
    "deadlines": DEADLINES,
    "operation_routes": ROUTES,
}


def validate(value: Any) -> None:
    if value != POLICY:
        raise ValueError("d5_capacity_policy_drift")


def enabled(settings: dict[str, Any]) -> bool:
    value = settings.get("d5_capacity_policy")
    if value is None:
        return False
    validate(value)
    return True


def capacity_for(mode: str) -> dict[str, Any]:
    if mode not in CLAIMS_BY_MODE:
        raise ValueError("d5_capacity_mode_required")
    return {**deepcopy(POLICY), "max_claims": CLAIMS_BY_MODE[mode]}


def json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def protect(value: Any, maximum: int, *, code: str = "d5_payload_capacity_exceeded") -> None:
    size = len(value.encode("utf-8")) if isinstance(value, str) else json_bytes(value)
    if size > maximum:
        raise ValueError(code)


def observations(value: Any) -> list[dict[str, Any]]:
    """Non-gating prose diagnostics, with no truncation or text rewriting."""
    found: list[dict[str, Any]] = []
    def visit(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                visit(child, path + "." + key)
                if key in {"reason", "text"} and isinstance(child, str):
                    target = POLICY["soft_reason_characters" if key == "reason" else "soft_claim_characters"]
                    if len(child) > target:
                        found.append({"path": path + "." + key, "characters": len(child), "target": target, "disposition": "formatting_observation_only"})
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, path + "." + str(index))
    visit(value, "response")
    return found


def envelope(request: dict[str, Any]) -> dict[str, Any]:
    """Bound serialized representations, never claim measured token fit.

    Four independent stage envelopes allow JSON escaping/normalization expansion.
    Actual exact paired counts remain mandatory before every Messages contact.
    """
    base = json_bytes(request.get("candidate_initial_wire", request))
    protect(request, MAX_INTERNAL_BYTES)
    unit_bytes = json_bytes(request.get("units", {}))
    bounds = {
        "draft": min(MAX_INTERNAL_BYTES, 6 * base + MAX_DRAFT_BYTES),
        "check": min(MAX_INTERNAL_BYTES, 6 * (base + MAX_DRAFT_BYTES + 36 * unit_bytes)),
        "repair": min(MAX_INTERNAL_BYTES, 6 * (base + MAX_DRAFT_BYTES + MAX_NORMALIZED_CHECK_BYTES)),
        "recheck": min(MAX_INTERNAL_BYTES, 6 * (base + MAX_DRAFT_BYTES + 36 * unit_bytes)),
    }
    return {
        "basis": "Serialized byte protection and soft prose targets; not measured token fit",
        "capacity_policy": deepcopy(POLICY), "stage_input_bytes_max": bounds,
        "input_bytes_reserved": sum(bounds.values()),
        "output_bytes_per_call_max": MAX_COMPACT_CHECK_BYTES,
        "output_bytes_reserved": 2 * MAX_DRAFT_BYTES + 2 * MAX_COMPACT_CHECK_BYTES,
        "normalized_output_bytes_max": MAX_NORMALIZED_CHECK_BYTES,
        "max_calls": 4, "max_repairs": 1,
        "offline_token_estimates": {key: {"heuristic": (value + 2) // 3, "conservative_byte_units": value} for key, value in bounds.items()},
        "provider_token_counts": None, "actual_provider_usage": None,
        "actual_usd": "0.000000",
    }


def monetary_envelope() -> dict[str, str]:
    def cost(route: str) -> Decimal:
        r = ROUTES[route]
        return (Decimal(r["input_tokens"]) * Decimal(r["prices"]["input"]) + Decimal(r["output_tokens"]) * Decimal(r["prices"]["output"])) / Decimal(1000000)
    draft, checker = cost("draft_repair"), cost("check_recheck_probe")
    return {"draft_or_repair": str(draft), "check_recheck_or_probe": str(checker), "workflow": str(2 * draft + 2 * checker), "ten_workflows_four_probes": str(20 * draft + 24 * checker)}
