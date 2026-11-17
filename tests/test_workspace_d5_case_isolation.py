"""Original v19 failure custody and typed prospective eligibility controls."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from src.workspace import d5_campaign
from src.workspace.admission import AdmissionError
from src.workspace.d5_case_isolation import (
    _semantic_code,
    eligible_error,
    preserve_failed_case,
    stop_details,
)
from tests.d5_case_isolation_fixtures import FaultTransport, storage
from tests.d5_comparison_gate import SNAPSHOT, setup

EVALUATION = "campaign-eval-learn-mechanism"
SEMANTIC_FAILURE = "answered_requires_complete_answer_without_gaps"
HISTORICAL = Path.home() / (
    "Machine-Learning-Projects/arxiv-evidence/campaign-live-v19-20261117T003409Z/"
    "cases/campaign-eval-learn-measurement"
)


@pytest.mark.integration
def test_exact_preserved_measurement_response_replays_without_mutation():
    from src.workspace.assistance_comparison_contract import response_model

    if not HISTORICAL.is_dir():
        pytest.skip("read-only preserved owner-local historical response unavailable")
    expected = {
        "01-draft-message.response.raw": "3be962576f005b6479c87d0b6bfd9f5e48ba9346983f43f4618ffe0b62bffd92",
        "SEALED-REQUEST.json": "7fa9d725e02b5fb476c386b731cfe8e264a46a9a030c4cf6b3cfee9b347f22b4",
        "CONTACT-JOURNAL.json": "19b32a2da0c4bb2b69656a23e25c6317919250e3a0a0db48347664d50161d0cd",
    }
    evidence = {}
    for name, digest in expected.items():
        raw = (HISTORICAL / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        evidence[name] = json.loads(raw)
    response = evidence["01-draft-message.response.raw"]
    sealed = evidence["SEALED-REQUEST.json"]
    binding = evidence["CONTACT-JOURNAL.json"]
    draft = json.loads(response["content"][0]["text"])
    context = sealed["original_selected_context"]
    body = sealed["initial_generation_request"]
    Draft202012Validator(body["output_config"]["format"]["schema"]).validate(draft)
    assert binding["state"] == "failed" and len(binding["contacts"]) == 2
    assert binding["contacts"][1]["response"] == response
    assert response["stop_reason"] == "end_turn"
    assert draft["response"]["coverage"]["p2"]["status"] == "answered"
    assert not draft["response"]["coverage"]["p2"]["answer_claim_ids"]
    assert draft["response"]["coverage"]["p2"]["context_claim_ids"]
    model = response_model(
        list(context["units"]), context["response_purpose"], context["task_policy"]
    )
    with pytest.raises(ValidationError) as captured:
        model.model_validate(draft)
    assert _semantic_code(captured.value) == SEMANTIC_FAILURE


@pytest.mark.integration
async def test_v19_still_stops_on_same_evaluation_failure(monkeypatch):
    if not SNAPSHOT.exists() or not os.environ.get("WORKSPACE_TEST_POSTGRES_URL"):
        pytest.skip("preserved owner-local v19 snapshot and disposable test Postgres required")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    with storage() as store:
        packet = setup(store)
        calls = {}

        def factory(key):
            assert key not in calls
            calls[key] = FaultTransport(key, fault="semantic" if key == EVALUATION else "")
            return calls[key]

        report = await d5_campaign.run(store, packet, offline=True, transport_factory=factory)
        assert report["stop"]["case_id"] == EVALUATION
        assert report["stop"]["reason"] == "campaign_development_contract_incomplete"
        assert "classification" not in report["stop"]
        assert list(calls) == packet["schedule"][:3]


@pytest.mark.unit
def test_arbitrary_exception_never_classifies_by_copied_error_text():
    for error in (
        RuntimeError(SEMANTIC_FAILURE),
        ValueError(SEMANTIC_FAILURE),
        RuntimeError("d5_whole_claim_support_unresolved"),
        AdmissionError(SEMANTIC_FAILURE),
    ):
        assert _semantic_code(error) is None
        assert not eligible_error(error)
        assert not preserve_failed_case(None, "unused", {"stage": "C"}, error)
    stop = stop_details(RuntimeError(SEMANTIC_FAILURE), "C", "draft", {})
    assert stop["classification"] == "unexpected_exception"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("suffix", "classification"),
    [
        ("contract_incomplete", "current_response_contract_failure"),
        ("binding_drift", "current_response_binding_failure"),
        ("material_unavailable", "current_response_material_unavailable"),
    ],
)
def test_v20_stop_uses_failed_case_stage_when_reusing_checker_validation(suffix, classification):
    raw = "campaign_development_" + suffix
    error = AdmissionError(raw)
    development = stop_details(error, "B", "development_contract", {})
    assert development == {
        "stage": "B",
        "local_stage": "development_contract",
        "classification": "development_contract_failure",
        "reason_code": raw,
    }
    for stage in ("C", "D"):
        reason = "campaign_current_response_" + suffix
        assert stop_details(error, stage, "check", {}) == {
            "stage": stage,
            "local_stage": "check",
            "classification": classification,
            "reason_code": reason,
            "reason": reason,
            "raw_reason": raw,
        }
