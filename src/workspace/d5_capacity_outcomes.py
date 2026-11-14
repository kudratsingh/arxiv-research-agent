"""Pure prospective diagnostics; these labels do not establish acceptance.

The caller supplies an independently verified current-check binding, when one
exists, as snapshot["binding"]. Raw receipts and original outcomes are untouched.
"""
from __future__ import annotations

from typing import Any

from src.workspace.d5_capacity_policy import observations

_QUALITY = frozenset({
    "d5_request_or_claim_quality_unresolved",
    "d5_whole_claim_support_unresolved",
    "d5_unscored_factual_prose",
})
_CAPACITY = frozenset({
    "d5_payload_capacity_exceeded", "d5_complete_stage_capacity_exceeded",
    "d5_compact_output_exceeded", "response_size_exceeded",
    "assistance_response_too_large", "compact_checks_utf8_limit",
    "compact_normalized_checks_utf8_limit", "input_measurement_exceeds_cap_or_invalid",
    "capacity_draft_bytes_exceeded", "capacity_compact_checks_bytes_exceeded",
    "capacity_normalized_checks_bytes_exceeded", "capacity_internal_output_exceeded",
    "capacity_selected_unit_limit",
})
_CONTRACT = frozenset({
    "d5_checker_claim_binding_drift", "incomplete_check_batch",
    "d5_duplicate_json_key", "d5_nonfinite_json", "d5_probe_claim_binding_drift",
    "section_claim_binding_mismatch", "orphan_claim", "duplicate_claim_id",
    "claim_quality_binding_mismatch", "coverage_review_binding_mismatch",
})
_PROVIDER = frozenset({"provider_error", "http_error", "invalid_provider_response"})
_UNCERTAIN = frozenset({"uncertain", "running", "interrupted", "dispatching"})


def classify_outcome(outcome: Any, snapshot: Any = None) -> dict[str, Any]:
    """Classify only explicit structured evidence, defaulting to unknown hold.

    ``snapshot.binding`` must be the result of independent current-response
    binding, not a guess from a completed contact. No state is modified.
    """
    result: dict[str, Any] = {
        "classification": "unknown_hold", "subtype": None,
        "formatting_observations": [],
    }
    if not isinstance(outcome, dict):
        return result
    snap = snapshot if isinstance(snapshot, dict) else {}
    steps = snap.get("steps")
    if isinstance(steps, list):
        for index, step in enumerate(steps):
            if isinstance(step, dict) and isinstance(step.get("output"), dict):
                for observation in observations(step["output"]):
                    result["formatting_observations"].append({"step": index, **observation})
    contacts = snap.get("contacts")
    contacts = contacts if isinstance(contacts, list) else []
    messages = [c for c in contacts if isinstance(c, dict) and c.get("endpoint") == "messages"]
    last = messages[-1] if messages else {}
    raw_response = last.get("response")
    response: dict[str, Any] = raw_response if isinstance(raw_response, dict) else {}
    raw_rejection = outcome.get("content_rejection")
    rejection: dict[str, Any] = raw_rejection if isinstance(raw_rejection, dict) else {}
    code = rejection.get("error") if isinstance(rejection.get("error"), str) else None
    error_class = rejection.get("error_class") if isinstance(rejection.get("error_class"), str) else None
    state = outcome.get("state") if isinstance(outcome.get("state"), str) else None
    snapshot_state = snap.get("state") if isinstance(snap.get("state"), str) else None
    contact_state = last.get("state") if isinstance(last.get("state"), str) else None
    if state in _UNCERTAIN or snapshot_state in _UNCERTAIN or contact_state in _UNCERTAIN:
        result["classification"] = "uncertain_completion"
    elif last.get("state") == "completed" and response.get("stop_reason") == "max_tokens":
        result.update(classification="contract_failure", subtype="capacity_suspected")
    elif code in _CAPACITY or any(value in _CAPACITY for value in rejection.get("error_codes", []) if isinstance(value, str)):
        result["classification"] = "capacity_failure"
    elif state in {"unrun", "not_run"} and not contacts:
        result["classification"] = "unrun"
    elif code in _QUALITY:
        binding = snap.get("binding")
        if (
            isinstance(binding, dict) and binding.get("status") == "bound"
            and binding.get("completed_checker_after_current_response") is True
            and last.get("stage") == "check" and last.get("state") == "completed"
            and response.get("stop_reason") == "end_turn"
            and rejection.get("accepted") is False
        ):
            result["classification"] = "negative_quality"
    elif code in _CONTRACT or error_class in {"ValidationError", "JSONDecodeError"}:
        result["classification"] = "contract_failure"
    elif code in _PROVIDER or error_class in {"HTTPStatusError", "ProviderError"}:
        result["classification"] = "provider_failure"
    elif (state == "ready" and outcome.get("mechanical_complete") is True
          and outcome.get("quality_acceptance") is True):
        result["classification"] = "success"
    return result
