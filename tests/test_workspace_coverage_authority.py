"""V10 single mapping; archived rejection and synthetic successor remain distinct."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from src.workspace.assistance_contract import schemas
from src.workspace.assistance_coverage import (
    AUTHORITATIVE_COVERAGE_REVISION,
    decorate_fixture,
    normalize,
    render,
)
from src.workspace.d5_benchmark import read
from src.workspace.d5_coverage_authority_packet import reseal
from tests.test_workspace_coverage_shapes import shaped
from tests.test_workspace_task_policy import ARCHIVE, NORMAL, RETRIEVAL, SAFETY, response

pytestmark = pytest.mark.unit
ARCHIVED = read(Path(__file__).parent / "fixtures/workspace/coverage-authority-archive.json.gz")


def synthetic():
    """Only delete the retired field. Never write back to original/provider data."""
    value = json.loads(ARCHIVED["text"])
    for claim in value["response"]["claims"]:
        del claim["part_ids"]
    return value


def check(value, sealed=None):
    s = sealed or reseal(ARCHIVED["sealed"])
    exported = schemas(list(s["units"]), purpose=s["response_purpose"], revision=s["schema_revision"], task_policy=s["task_policy"])
    for schema in exported.values():
        Draft202012Validator(schema).validate(value)
    return render(value, list(s["units"]), s["response_purpose"], s["task_policy"])


def test_original_rejection_is_immutable_legacy_and_successor_is_explicitly_synthetic():
    original = json.loads(ARCHIVED["text"])
    old = ARCHIVED["sealed"]
    assert schemas(list(old["units"]), purpose=old["response_purpose"], revision=old["schema_revision"], task_policy=old["task_policy"])["wire"] == ARCHIVED["transmitted_body"]["output_config"]["format"]["schema"]
    Draft202012Validator(ARCHIVED["transmitted_body"]["output_config"]["format"]["schema"]).validate(original)
    with pytest.raises(ValueError, match="request_part_claim_binding_mismatch"):
        normalize(original, list(old["units"]), old["response_purpose"], old["task_policy"])
    with pytest.raises(ValidationError):
        check(original)
    result = check(synthetic())
    assert result["claim_request_index"] == {
        "c1": {"answer": ["p1"], "context": []},
        "c2": {"answer": ["p1", "p2"], "context": []},
        "c3": {"answer": ["p2"], "context": []},
        "c4": {"answer": ["p2"], "context": ["p3"]},
        "c5": {"answer": ["p2"], "context": ["p3"]},
    }
    assert result["request_coverage"][2]["status"] == "lacks_evidence"
    assert result["request_coverage"][2]["answer_claim_ids"] == []
    assert not result["coverage_complete"]
    assert "unmeasured" in result["coverage_basis"]
    assert hashlib.sha256(ARCHIVED["text"].encode()).hexdigest() == ARCHIVED["text_sha256"]
    assert original == json.loads(ARCHIVED["text"]) and ARCHIVED["accepted"] is False


@pytest.mark.parametrize("mutation", ["removed_field", "unknown", "orphan", "duplicate_id", "duplicate_ref", "overlap", "answer_empty", "gap", "evidence_answer", "omission_gap", "seventh", "unknown_part", "priority"])
def test_malformed_single_mapping_rejected(mutation):
    value = synthetic()
    r = value["response"]
    row = r["coverage"]["p1"]
    if mutation == "removed_field":
        r["claims"][0]["part_ids"] = ["p1"]
    elif mutation == "unknown":
        row["answer_claim_ids"] = ["c6"]
    elif mutation == "orphan":
        row["answer_claim_ids"].remove("c1")
    elif mutation == "duplicate_id":
        r["claims"][1]["claim_id"] = "c1"
    elif mutation == "duplicate_ref":
        row["answer_claim_ids"].append("c1")
    elif mutation == "overlap":
        row["context_claim_ids"] = ["c1"]
    elif mutation == "answer_empty":
        row["answer_claim_ids"] = []
    elif mutation == "gap":
        row["gap"] = "protocol"
    elif mutation == "evidence_answer":
        r["coverage"]["p3"]["answer_claim_ids"] = []
    elif mutation == "omission_gap":
        r["coverage"]["p3"].update(status="omitted", gap="protocol")
    elif mutation == "seventh":
        r["claims"] += [deepcopy(r["claims"][0])] * 2
    elif mutation == "unknown_part":
        r["coverage"]["p4"] = row
    else:
        r["coverage"]["p1"] = {"status": "omitted", "gap": "claim_budget", "context_claim_ids": []}
        r["coverage"]["p2"]["context_claim_ids"] = ["c1"]
    with pytest.raises((ValueError, ValidationError)):
        check(value)


@pytest.mark.parametrize("case", [NORMAL, RETRIEVAL, SAFETY])
def test_normal_comparison_only_and_full_abstention(case):
    c = ARCHIVE["cases"][case]
    policy = shaped(case)
    policy["revision"] = AUTHORITATIVE_COVERAGE_REVISION
    value = decorate_fixture(response(case), policy)
    sealed = {"units": c["units"], "response_purpose": c["purpose"], "schema_revision": AUTHORITATIVE_COVERAGE_REVISION, "task_policy": policy}
    result = check(value, sealed)
    assert not result["coverage_complete"]
    if case == SAFETY:
        assert result["claims"] == [] and result["claim_request_index"] == {}
        for field in ["claims", "background_claims", "part_ids"]:
            bad = deepcopy(value)
            bad["response"][field] = []
            with pytest.raises(ValidationError):
                check(bad, sealed)
    if case == RETRIEVAL:
        assert result["claims"] and result["comparison_unanswered"]
        bad = deepcopy(value)
        bad["response"]["coverage"]["p1"] = {"status": "answered", "gap": "none", "answer_claim_ids": ["c1"], "context_claim_ids": []}
        with pytest.raises(ValueError, match="source_notes_cannot_answer_comparison"):
            check(bad, sealed)


def test_closed_wire_claims_and_singleton_status_enums():
    sealed = reseal(ARCHIVED["sealed"])
    wire = sealed["response_schemas"]["wire"]
    claim_schemas = [d for d in wire["$defs"].values() if "claim_id" in d.get("properties", {})]
    assert claim_schemas
    assert all(d["additionalProperties"] is False and "part_ids" not in d["properties"] for d in claim_schemas)
    statuses = [d["properties"]["status"] for d in wire["$defs"].values() if "status" in d.get("properties", {})]
    assert {tuple(x["enum"]) for x in statuses} == {("answered",), ("omitted",), ("lacks_evidence",)}
