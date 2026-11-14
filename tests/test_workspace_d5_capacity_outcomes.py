from copy import deepcopy

import pytest

from src.workspace.d5_capacity_outcomes import classify_outcome


def reject(code, error_class="AdmissionError"):
    return {"state": "failed", "content_rejection": {"error": code, "error_class": error_class, "accepted": False}}


def checked(stop="end_turn"):
    return {"state": "failed", "contacts": [{"endpoint": "messages", "stage": "check", "state": "completed", "response": {"stop_reason": stop}}], "binding": {"status": "bound", "completed_checker_after_current_response": True}}


def test_unknown_and_unrun_never_pass():
    assert classify_outcome(None)["classification"] == "unknown_hold"
    assert classify_outcome({})["classification"] == "unknown_hold"
    assert classify_outcome({"state": [], "content_rejection": {"error": []}})["classification"] == "unknown_hold"
    assert classify_outcome({"state": "unrun"})["classification"] == "unrun"
    assert classify_outcome({"state": "ready", "mechanical_complete": True, "quality_acceptance": None})["classification"] == "unknown_hold"
    assert classify_outcome({"state": "ready", "mechanical_complete": True, "quality_acceptance": True})["classification"] == "success"


@pytest.mark.parametrize("code", ["d5_request_or_claim_quality_unresolved", "d5_whole_claim_support_unresolved", "d5_unscored_factual_prose"])
def test_quality_needs_explicit_binding_and_complete_final_check(code):
    outcome, snapshot = reject(code), checked()
    assert classify_outcome(outcome, snapshot)["classification"] == "negative_quality"
    snapshot.pop("binding")
    assert classify_outcome(outcome, snapshot)["classification"] == "unknown_hold"
    snapshot = checked()
    snapshot["contacts"][0]["stage"] = "draft"
    assert classify_outcome(outcome, snapshot)["classification"] == "unknown_hold"
    assert classify_outcome(outcome, checked("max_tokens")) == {"classification": "contract_failure", "subtype": "capacity_suspected", "formatting_observations": []}


def test_exact_failure_types_and_conservative_unknowns():
    assert classify_outcome(reject("response_size_exceeded"))["classification"] == "capacity_failure"
    assert classify_outcome(reject("arbitrary error", "ValidationError"))["classification"] == "contract_failure"
    assert classify_outcome(reject("arbitrary error", "JSONDecodeError"))["classification"] == "contract_failure"
    assert classify_outcome(reject("d5_checker_claim_binding_drift"))["classification"] == "contract_failure"
    assert classify_outcome(reject("provider_error"))["classification"] == "provider_failure"
    assert classify_outcome(reject("response_size_exceeded plus words"))["classification"] == "unknown_hold"
    assert classify_outcome({"state": "uncertain", "mechanical_complete": True, "quality_acceptance": True})["classification"] == "uncertain_completion"


def test_observations_are_soft_and_inputs_are_unchanged():
    outcome = {"state": "ready", "mechanical_complete": True, "quality_acceptance": True}
    snapshot = {"steps": [{"output": {"reason": "a" * 104, "text": "x" * 501}}]}
    before = deepcopy((outcome, snapshot))
    result = classify_outcome(outcome, snapshot)
    assert result["classification"] == "success"
    assert len(result["formatting_observations"]) == 1
    assert result["formatting_observations"][0]["disposition"] == "formatting_observation_only"
    assert (outcome, snapshot) == before
