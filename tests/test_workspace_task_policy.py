"""Archived v8r4b controls under a new, unapproved task-bound contract."""

import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from src.workspace.assistance_contract import resolve_draft, response_model, schemas
from src.workspace.assistance_policy import (
    TASK_REVISION,
    ApplicationContext,
    TaskContext,
    normalize_task_output,
    render_task_output,
    seal_task_policy,
)
from src.workspace.grounding import EvidenceRef
from src.workspace.material import SourceMaterial, SourceSpan

pytestmark = pytest.mark.unit

ARCHIVE = json.loads(
    gzip.decompress(
        (Path(__file__).parent / "fixtures/d5/stage-c-v8r4b/archived-controls.json.gz").read_bytes()
    )
)
SAFETY = "v8-research-insufficient"
RETRIEVAL = "v8-research-retrieval"
NORMAL = "v8-learn-measurement"


def policy(case_id, *, context=None):
    case = ARCHIVE["cases"][case_id]
    intent = (
        "application_assessment"
        if case_id == SAFETY
        else "comparison"
        if case_id == RETRIEVAL
        else "answer"
    )
    return seal_task_policy(
        TaskContext(intent=intent, application_context=context or ApplicationContext()),
        case["mode"],
        len({r["work_id"] for r in case["units"].values()}),
    )


def response(case_id):
    if case_id == SAFETY:
        return {
            "response": {
                "disposition": "full_abstention",
                "reason": "application_context_required",
                "next_action": "request_context",
                "context_requests": {k: "required" for k in policy(SAFETY)["missing_context"]},
            }
        }
    value = deepcopy(ARCHIVE["cases"][case_id]["output"])
    value["disposition"] = "comparison_abstention" if case_id == RETRIEVAL else "answer"
    if case_id == RETRIEVAL:
        value.pop("comparison_claims")
        value.pop("comparison_basis")
    return {"response": value}


def validate(case_id, value, *, selected_policy=None):
    c = ARCHIVE["cases"][case_id]
    pol = selected_policy or policy(case_id)
    exported = schemas(
        list(c["units"]), purpose=c["purpose"], revision=TASK_REVISION, task_policy=pol
    )
    Draft202012Validator(exported["local"]).validate(value)
    Draft202012Validator(exported["wire"]).validate(value)
    return resolve_draft(
        value,
        {h: EvidenceRef(**r) for h, r in c["units"].items()},
        tuple(
            SourceMaterial(**{**m, "spans": tuple(SourceSpan(**s) for s in m["spans"])})
            for m in ARCHIVE["materials"]
        ),
        purpose=c["purpose"],
        revision=TASK_REVISION,
        task_policy=pol,
    )


@pytest.mark.parametrize("case_id,count", [(SAFETY, 0), (RETRIEVAL, 6), (NORMAL, 6)])
def test_actual_local_wire_and_provenance_controls(case_id, count):
    draft, claims = validate(case_id, response(case_id))
    assert len(claims) == count
    assert bool(draft.abstention) == (case_id != NORMAL)


@pytest.mark.parametrize(
    "reason", ["application_context_required", "comparison_evidence_required", None]
)
def test_captured_safety_cannot_keep_claims_or_switch_reason(reason):
    captured = deepcopy(ARCHIVE["cases"][SAFETY]["output"])
    captured["abstention"] = reason
    for value in (
        captured,
        {"response": {**captured, "disposition": "answer"}},
        {"response": {**response(SAFETY)["response"], "claims": captured["claims"]}},
    ):
        with pytest.raises((ValueError, ValidationError)):
            validate(SAFETY, value)


@pytest.mark.parametrize("reason", ["comparison_evidence_required", None])
def test_full_abstention_cannot_change_application_reason_even_without_claims(reason):
    value = response(SAFETY)
    value["response"]["reason"] = reason
    with pytest.raises((ValueError, ValidationError)):
        validate(SAFETY, value)


@pytest.mark.parametrize(
    "field",
    [
        "claims",
        "background_claims",
        "assumption_claims",
        "limitation_claims",
        "comparison_claims",
        "comparison_basis",
        "questions",
        "proposal",
    ],
)
def test_full_schema_structurally_omits_factual_and_reference_fields(field):
    value = response(SAFETY)
    value["response"][field] = []
    with pytest.raises((ValueError, ValidationError)):
        validate(SAFETY, value)


def test_missing_context_derived_before_generation_and_request_values_trimmed():
    pol = policy(
        SAFETY,
        context=ApplicationContext(vehicle_configuration="  Rocket Twin test configuration  "),
    )
    assert pol["allowed_dispositions"] == ["full_abstention"]
    assert pol["missing_context"] == [
        "operating_envelope",
        "safety_objectives",
        "validation_evidence",
    ]
    assert pol["application_context"]["vehicle_configuration"] == "Rocket Twin test configuration"
    value = response(SAFETY)
    value["response"]["context_requests"].pop("vehicle_configuration")
    validate(SAFETY, value, selected_policy=pol)
    value["response"]["context_requests"]["vehicle_configuration"] = "required"
    with pytest.raises((ValueError, ValidationError)):
        validate(SAFETY, value, selected_policy=pol)


def test_provided_context_is_not_scientific_evidence_or_safety_approval():
    pol = policy(
        SAFETY,
        context=ApplicationContext(
            **{k: "Explicitly supplied, unverified" for k in policy(SAFETY)["required_context"]}
        ),
    )
    assert pol["missing_context"] == []
    assert pol["allowed_dispositions"] == ["full_abstention", "answer"]
    assert "not verified source evidence" in pol["context_basis"]


@pytest.mark.parametrize("mode,count", [("unknown", 1), ("research", 0), ("research", True)])
def test_invalid_application_policy(mode, count):
    with pytest.raises((ValueError, ValidationError)):
        seal_task_policy(TaskContext(), mode, count)


def test_task_intent_is_not_inferred_from_question_or_number_of_sources():
    assert seal_task_policy(TaskContext(), "research", 2)["task_intent"] == "answer"
    with pytest.raises(ValueError, match="research_task_intent"):
        seal_task_policy(TaskContext(intent="comparison"), "learn", 1)
    with pytest.raises(ValueError, match="requires_assessment"):
        seal_task_policy(
            TaskContext(application_context=ApplicationContext(safety_objectives="private input")),
            "research",
            1,
        )
    assert seal_task_policy(TaskContext(intent="comparison"), "research", 1)[
        "allowed_dispositions"
    ] == ["full_abstention", "comparison_abstention"]


def test_policy_tampering_and_omission_are_not_accepted():
    c = ARCHIVE["cases"][SAFETY]
    for field, changed in [
        ("allowed_dispositions", ["answer"]),
        ("missing_context", []),
        ("required_context", []),
    ]:
        pol = policy(SAFETY)
        pol[field] = changed
        with pytest.raises(ValueError, match="sealed_task_policy_changed"):
            schemas(list(c["units"]), purpose=c["purpose"], revision=TASK_REVISION, task_policy=pol)
    with pytest.raises(ValueError, match="sealed_task_policy_required"):
        response_model(list(c["units"]), revision=TASK_REVISION)
    with pytest.raises(ValueError, match="sealed_task_policy_required"):
        resolve_draft({}, {}, (), revision=TASK_REVISION)


def test_comparison_notes_do_not_allow_comparison_conclusion_or_unselected_notes():
    for field in ("comparison_claims", "comparison_basis", "unverified_prose"):
        value = response(RETRIEVAL)
        value["response"][field] = ["c1"]
        with pytest.raises((ValueError, ValidationError)):
            validate(RETRIEVAL, value)
    value = response(RETRIEVAL)
    value["response"]["claims"][0]["handles"] = ["unselected"]
    with pytest.raises((ValueError, ValidationError)):
        validate(RETRIEVAL, value)


def test_comparison_answer_requires_independently_cited_comparison_claims():
    value = response(RETRIEVAL)
    value["response"].update(
        disposition="answer", abstention=None, comparison_claims=[], comparison_basis=[]
    )
    with pytest.raises(ValueError, match="comparison_answer_requires_scored_comparison"):
        validate(RETRIEVAL, value)
    value["response"].update(comparison_claims=["c1"], comparison_basis=["c1", "c4"])
    validate(RETRIEVAL, value)


def test_full_and_partial_rendering_preserve_the_disposition():
    c = ARCHIVE["cases"][SAFETY]
    result = render_task_output(response(SAFETY), list(c["units"]), c["purpose"], policy(SAFETY))
    assert result["claims"] == []
    assert len(result["context_requests"]) == 4
    assert "vehicle" in result["context_requests"][0]
    assert "operating envelope" in result["context_requests"][1]
    assert "safety objectives" in result["context_requests"][2]
    assert "validation evidence" in result["context_requests"][3]
    assert result["response_disposition"] == "full_abstention"
    c = ARCHIVE["cases"][RETRIEVAL]
    result = render_task_output(
        response(RETRIEVAL), list(c["units"]), c["purpose"], policy(RETRIEVAL)
    )
    assert result["comparison_unanswered"] and len(result["claims"]) == 6
    assert result["comparison_claims"] == []


def test_generic_full_abstention_and_byte_bound():
    c = ARCHIVE["cases"][NORMAL]
    value = {
        "response": {
            "disposition": "full_abstention",
            "reason": "insufficient_selected_evidence",
            "next_action": "request_context",
        }
    }
    validate(NORMAL, value)
    value["junk"] = "a" * 8001
    with pytest.raises(ValueError, match="too_large"):
        normalize_task_output(value, list(c["units"]), c["purpose"], policy(NORMAL))
