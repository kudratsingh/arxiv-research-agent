"""Prospective qualification routes and complete monetary envelope; no dispatch.

Legacy packets have no operation_routes and retain their original Sonnet path.
The proposed route requires its own packet and independently recorded approval.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.workspace.admission import AdmissionError
from src.workspace.assistance import build_wire

OPUS_LIMITS: dict[str, Any] = {
    "jobs": 14,
    "messages": 44,
    "counts": 45,
    "usd": "10",
    "concurrency": 1,
    "workflow_usd": "0.45",
    "probe_usd": "0.15",
    "headroom_usd": "1.00",
}
ROUTES: dict[str, Any] = {
    "revision": "d5-sonnet-opus-high-v1",
    "draft_repair": {
        "model": "claude-sonnet-5-5",
        "thinking": {"type": "between_tools"},
        "effort": "medium",
        "input_tokens": 20000,
        "output_tokens": 4000,
        "prices": {"input": "2", "output": "10", "verified_at": "2026-11-06"},
    },
    "check_recheck_probe": {
        "model": "claude-opus-5-5",
        "thinking": {"type": "adaptive"},
        "effort": "high",
        "input_tokens": 20000,
        "output_tokens": 3200,
        "prices": {"input": "4", "output": "20", "verified_at": "2026-11-06"},
    },
}


def validate(routes: Any) -> None:
    if routes != ROUTES:
        raise AdmissionError("d5_operation_routes_drift")


def route(routes: dict[str, Any], stage: str) -> dict[str, Any]:
    validate(routes)
    if stage not in {"draft", "repair", "check"}:
        raise AdmissionError("d5_operation_stage_required")
    return dict(routes["check_recheck_probe" if stage == "check" else "draft_repair"])


def wire(context: dict[str, Any], routes: dict[str, Any]) -> dict[str, Any]:
    selected = route(routes, context["phase"])
    result = build_wire(context)
    result["model"] = selected["model"]
    result["thinking"] = selected["thinking"]
    result["max_tokens"] = selected["output_tokens"]
    result["output_config"]["effort"] = selected["effort"]
    return result


def reservation(routes: dict[str, Any], *, probe: bool = False) -> Decimal:
    def cost(stage: str) -> Decimal:
        r = route(routes, stage)
        return (
            Decimal(r["input_tokens"]) * Decimal(r["prices"]["input"])
            + Decimal(r["output_tokens"]) * Decimal(r["prices"]["output"])
        ) / 1_000_000

    return cost("check") if probe else 2 * cost("draft") + 2 * cost("check")


def verdict_text(response: dict[str, Any]) -> str:
    """One verdict after optional reasoning blocks; raw journal stays unchanged."""
    content = response.get("content")
    if not isinstance(content, list) or not content or len(content) > 16:
        raise AdmissionError("d5_structured_verdict_required")
    for block in content[:-1]:
        if not isinstance(block, dict) or block.get("type") not in {
            "thinking",
            "redacted_thinking",
        }:
            raise AdmissionError("d5_structured_verdict_required")
        key = "thinking" if block["type"] == "thinking" else "data"
        if not isinstance(block.get(key), str):
            raise AdmissionError("d5_reasoning_block_invalid")
    final = content[-1]
    if (
        not isinstance(final, dict)
        or final.get("type") != "text"
        or not isinstance(final.get("text"), str)
    ):
        raise AdmissionError("d5_structured_verdict_required")
    return str(final["text"])
