"""V9 status-disjoint wire objects. Corrected outputs are SYNTHETIC, not live passes."""

import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator, ValidationError

from src.workspace.assistance_contract import schemas
from src.workspace.assistance_coverage import (
    SHAPED_COVERAGE_REVISION,
    decorate_fixture,
    normalize,
    render,
)
from src.workspace.d5_benchmark import read
from src.workspace.d5_coverage_shapes_packet import PREDECESSOR_PATH, reseal
from tests.test_workspace_request_coverage import policy
from tests.test_workspace_task_policy import ARCHIVE, NORMAL, RETRIEVAL, SAFETY, response

pytestmark = pytest.mark.unit
ARCHIVED = json.loads(
    gzip.decompress(
        (Path(__file__).parent / "fixtures/workspace/coverage-shapes-archive.json.gz").read_bytes()
    )
)


def shaped(case=NORMAL):
    p = policy(case)
    p["revision"] = SHAPED_COVERAGE_REVISION
    return p


def validate(case, value, pol=None):
    p = pol or shaped(case)
    c = ARCHIVE["cases"][case]
    from src.workspace.assistance_coverage import response_model

    m = response_model(list(c["units"]), c["purpose"], p)
    exported = schemas(
        list(c["units"]), purpose=c["purpose"], revision=SHAPED_COVERAGE_REVISION, task_policy=p
    )
    assert exported["wire"] == transform_schema(m)
    for schema in exported.values():
        Draft202012Validator(schema).validate(value)
    m.model_validate(value)
    return render(value, list(c["units"]), c["purpose"], p)


def test_actual_rejected_draft_was_wire_valid_v8_but_is_wire_invalid_v9():
    assert hashlib.sha256(ARCHIVED["text"].encode()).hexdigest() == ARCHIVED["text_sha256"]
    raw = json.loads(ARCHIVED["text"])
    assert raw["response"]["coverage"]["p3"]["answer_claim_ids"] == ["c5"]
    Draft202012Validator(ARCHIVED["contact"]["body"]["output_config"]["format"]["schema"]).validate(
        raw
    )
    sealed = reseal(read(PREDECESSOR_PATH)["cases"][0]["sealed"])
    for schema in sealed["response_schemas"].values():
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(raw)
    with pytest.raises(ValueError):
        normalize(raw, list(sealed["units"]), sealed["response_purpose"], sealed["task_policy"])
    assert ARCHIVED["accepted"] is False


def test_synthetic_correction_c5_is_only_context_for_missing_protocol():
    original = json.loads(ARCHIVED["text"])
    corrected = deepcopy(original)
    corrected["response"]["coverage"]["p3"] = {
        "status": "lacks_evidence",
        "gap": "protocol",
        "context_claim_ids": ["c5"],
    }
    sealed = reseal(read(PREDECESSOR_PATH)["cases"][0]["sealed"])
    for schema in sealed["response_schemas"].values():
        Draft202012Validator(schema).validate(corrected)
    output = render(
        corrected, list(sealed["units"]), sealed["response_purpose"], sealed["task_policy"]
    )
    row = output["request_coverage"][2]
    assert row["answer_claim_ids"] == [] and row["context_claim_ids"] == ["c5"]
    assert row["status"] == "lacks_evidence" and not output["coverage_complete"]
    assert original == json.loads(ARCHIVED["text"])


@pytest.mark.parametrize("case", [NORMAL, RETRIEVAL, SAFETY])
def test_status_shapes_render_through_existing_reader_contract(case):
    p = shaped(case)
    value = decorate_fixture(response(case), p)
    output = validate(case, value)
    assert not output["coverage_complete"]
    assert output["request_coverage"][0]["answer_claim_ids"] == []
    if case == RETRIEVAL:
        assert output["comparison_unanswered"] and output["claims"]
    if case == SAFETY:
        assert not output["claims"] and output["context_requests"]


@pytest.mark.parametrize(
    "status,gap",
    [("answered", "none"), ("lacks_evidence", "protocol"), ("omitted", "claim_budget")],
)
def test_valid_status_specific_controls(status, gap):
    p = shaped()
    value = decorate_fixture(response(NORMAL), p)
    row = value["response"]["coverage"]["p1"]
    ids = row["context_claim_ids"]
    row.update(status=status, gap=gap)
    if status == "answered":
        row.update(answer_claim_ids=ids, context_claim_ids=[])
    output = validate(NORMAL, value)
    assert output["coverage_complete"] == (status == "answered")
    assert output["request_coverage"][0]["context_claim_ids"] == (
        [] if status == "answered" else ids
    )


@pytest.mark.parametrize(
    "row",
    [
        {"status": "answered", "gap": "none", "answer_claim_ids": [], "context_claim_ids": []},
        {
            "status": "answered",
            "gap": "protocol",
            "answer_claim_ids": ["c1"],
            "context_claim_ids": [],
        },
        {"status": "lacks_evidence", "gap": "none", "context_claim_ids": []},
        {"status": "lacks_evidence", "gap": "claim_budget", "context_claim_ids": []},
        {"status": "omitted", "gap": "protocol", "context_claim_ids": []},
        {"status": "invented", "gap": "protocol", "context_claim_ids": []},
        {
            "status": "lacks_evidence",
            "gap": "protocol",
            "answer_claim_ids": [],
            "context_claim_ids": [],
        },
        {
            "status": "omitted",
            "gap": "not_prioritized",
            "answer_claim_ids": ["c1"],
            "context_claim_ids": [],
        },
    ],
)
def test_illegal_shape_rejected_by_actual_sdk_schema(row):
    p = shaped()
    value = decorate_fixture(response(NORMAL), p)
    value["response"]["coverage"]["p1"] = row
    s = schemas(
        list(ARCHIVE["cases"][NORMAL]["units"]),
        purpose="single_paper",
        revision=SHAPED_COVERAGE_REVISION,
        task_policy=p,
    )
    for schema in s.values():
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(value)
    with pytest.raises(ValueError):
        normalize(value, list(ARCHIVE["cases"][NORMAL]["units"]), "single_paper", p)


def test_fixed_enums_survive_transform_including_full_abstention_and_context_fields():
    p = shaped(SAFETY)
    exported = schemas(
        list(ARCHIVE["cases"][SAFETY]["units"]),
        purpose="single_paper",
        revision=SHAPED_COVERAGE_REVISION,
        task_policy=p,
    )

    def check(local, wire):
        if isinstance(local, dict):
            assert "const" not in local
            if "enum" in local:
                assert wire["enum"] == local["enum"]
            for k in ("$defs", "properties"):
                for name, child in local.get(k, {}).items():
                    check(child, wire[k][name])
            for k in ("anyOf",):
                for a, b in zip(local.get(k, []), wire.get(k, []), strict=True):
                    check(a, b)

    check(exported["local"], exported["wire"])
    value = decorate_fixture(response(SAFETY), p)
    value["response"]["coverage"]["p1"]["gap"] = "protocol"
    with pytest.raises(ValidationError):
        Draft202012Validator(exported["wire"]).validate(value)


@pytest.mark.parametrize("mutation", ["duplicate", "overlap", "orphan", "unknown_part", "seventh"])
def test_local_reciprocal_and_cap_checks_preserved(mutation):
    p = shaped()
    value = decorate_fixture(response(NORMAL), p)
    r = value["response"]
    row = r["coverage"]["p1"]
    if mutation == "duplicate":
        row["context_claim_ids"].append(row["context_claim_ids"][0])
    elif mutation == "overlap":
        row.update(status="answered", gap="none", answer_claim_ids=["c1"])
    elif mutation == "orphan":
        row["context_claim_ids"] = []
    elif mutation == "unknown_part":
        r["claims"][0]["part_ids"] = ["p8"]
    else:
        r["claims"].append(deepcopy(r["claims"][0]))
    with pytest.raises(ValueError):
        normalize(value, list(ARCHIVE["cases"][NORMAL]["units"]), "single_paper", p)


@pytest.mark.parametrize("mutation", ["reason", "claims", "refs", "status"])
def test_full_abstention_cannot_be_used_as_source_notes(mutation):
    p = shaped(SAFETY)
    value = decorate_fixture(response(SAFETY), p)
    if mutation == "reason":
        value["response"]["reason"] = "comparison_only"
    elif mutation == "claims":
        value["response"]["claims"] = []
    elif mutation == "refs":
        value["response"]["coverage"]["p1"]["context_claim_ids"] = []
    else:
        value["response"]["coverage"]["p1"]["status"] = "omitted"
    s = schemas(
        list(ARCHIVE["cases"][SAFETY]["units"]),
        purpose="single_paper",
        revision=SHAPED_COVERAGE_REVISION,
        task_policy=p,
    )
    with pytest.raises(ValidationError):
        Draft202012Validator(s["wire"]).validate(value)
    with pytest.raises(ValueError):
        normalize(value, list(ARCHIVE["cases"][SAFETY]["units"]), "single_paper", p)


def test_unknown_coverage_revision_cannot_be_sealed():
    from src.workspace.assistance_coverage import seal_coverage_policy
    from src.workspace.assistance_policy import CoverageTaskContext

    with pytest.raises(ValueError, match="coverage_revision"):
        seal_coverage_policy(CoverageTaskContext(), "learn", 1, "Explain", revision="future")


def test_coverage_revision_cannot_be_substituted():
    from src.workspace.assistance_coverage import COVERAGE_REVISION

    with pytest.raises(ValueError, match="revision_mismatch"):
        schemas(
            list(ARCHIVE["cases"][NORMAL]["units"]),
            purpose="single_paper",
            revision=COVERAGE_REVISION,
            task_policy=shaped(),
        )


@pytest.mark.parametrize(
    "status,gap", [("lacks_evidence", "source_scope"), ("omitted", "not_prioritized")]
)
def test_full_abstention_without_missing_application_context(status, gap):
    p = shaped()
    value = {
        "response": {
            "disposition": "full_abstention",
            "reason": "insufficient_selected_evidence",
            "next_action": "request_context",
            "coverage": {"p1": {"status": status, "gap": gap}},
        }
    }
    result = validate(NORMAL, value, p)
    assert result["claims"] == [] and result["request_coverage"][0]["context_claim_ids"] == []


def test_result_claim_cannot_answer_protocol_part_when_checker_finds_it_context_only():
    """Synthetic semantic verdict: a valid shape alone never earns acceptance."""
    from src.workspace.assistance import CoverageChecks
    from src.workspace.assistance_coverage import fixture_checks, review_context, review_failed

    value = json.loads(ARCHIVED["text"])
    value["response"]["coverage"]["p3"] = {
        "status": "answered",
        "gap": "none",
        "answer_claim_ids": ["c5"],
        "context_claim_ids": [],
    }
    sealed = reseal(read(PREDECESSOR_PATH)["cases"][0]["sealed"])
    rendered = render(
        value, list(sealed["units"]), sealed["response_purpose"], sealed["task_policy"]
    )
    claim_inputs = [
        {"claim_id": c["claim_id"], "input_digest": "synthetic-" + c["claim_id"]}
        for c in value["response"]["claims"]
    ]
    context = {
        "claim_inputs": claim_inputs,
        **review_context(sealed["task_policy"], rendered, claim_inputs, sealed["units"]),
    }
    checks = fixture_checks(
        {"checks": [], "prose_review": "procedural_only", "prose_findings": []}, context
    )
    checks["coverage_checks"][2]["decision"] = "lacks_evidence"
    checks["coverage_checks"][2]["reason"] = (
        "Synthetic control: c5 is a result, not the unspecified protocol."
    )
    assert review_failed(CoverageChecks.model_validate(checks), rendered)
