"""Pure synthetic fixtures: contract checks, not model-quality evidence."""

from copy import deepcopy

import pytest

from src.workspace.assistance_consistency_contract import _normalize
from src.workspace.d5_quality_guidance import SYNTHETIC_EXAMPLES, guidance


def _policy(kind="source_facts", missing=()):
    return {"requested_parts": [{"id": "p1", "kind": kind}], "missing_context": list(missing)}


def _draft():
    return {
        "response": {
            "disposition": "answer",
            "claims": list(deepcopy(SYNTHETIC_EXAMPLES[0]["claims"])),
            "background_claims": [],
            "assumption_claims": [],
            "limitation_claims": [],
            "gaps": ["methods"],
            "questions": [
                {"intent": "methods", "context_claim_ids": ["c1"], "premise_claim_ids": []}
            ],
            "proposal": "inspect_methods",
            "coverage": {
                "p1": {
                    "status": "answered",
                    "gap_reasons": ["none"],
                    "answer_claim_ids": ["c1", "c2"],
                    "context_claim_ids": [],
                }
            },
        }
    }


pytestmark = pytest.mark.unit

def test_split_fixture_passes_real_coverage_normalization_and_preserves_context():
    result, coverage = _normalize(_draft(), "single_paper", _policy())
    assert coverage["p1"]["answer_claim_ids"] == ["c1", "c2"]
    claims = result["response"]["claims"]
    assert [c["handles"] for c in claims] == [["u1"], ["u1"]]
    assert all(c["required_scope"] == "abstract" for c in claims)


def test_answered_cannot_use_context_as_answer():
    value = _draft()
    value["response"]["coverage"]["p1"].update(answer_claim_ids=[], context_claim_ids=["c1", "c2"])
    with pytest.raises(ValueError, match="answered_requires_complete_answer_without_gaps"):
        _normalize(value, "single_paper", _policy())


def test_partial_needs_answer_and_real_gap():
    value = _draft()
    value["response"]["coverage"]["p1"].update(status="partial", gap_reasons=["methods"])
    _, coverage = _normalize(value, "single_paper", _policy())
    assert coverage["p1"]["gap_reasons"] == ["methods"]
    value["response"]["coverage"]["p1"]["gap_reasons"] = ["none"]
    with pytest.raises(ValueError, match="partial_requires_answer_and_real_remaining_gaps"):
        _normalize(value, "single_paper", _policy())


def test_missing_context_abstention_forbids_claim_references():
    value = {
        "response": {
            "disposition": "full_abstention",
            "reason": "application_context_required",
            "next_action": "request_context",
            "context_requests": {"setting": "required"},
            "coverage": {
                "p1": {"status": "lacks_evidence", "gap_reasons": ["application_context"]}
            },
        }
    }
    _, coverage = _normalize(value, "single_paper", _policy(missing=("setting",)))
    assert coverage["p1"]["answer_claim_ids"] == []
    value["response"]["coverage"]["p1"]["context_claim_ids"] = ["c1"]
    with pytest.raises(ValueError):
        _normalize(value, "single_paper", _policy(missing=("setting",)))


def test_unknown_phase_is_rejected():
    with pytest.raises(ValueError):
        guidance("check")


def test_comparison_abstention_keeps_notes_but_notes_cannot_answer():
    value = _draft()
    response = value["response"]
    response.update(comparison_claims=[], comparison_basis=[])
    response["coverage"] = {
        "p1": {
            "status": "lacks_evidence",
            "gap_reasons": ["common_evaluation"],
            "answer_claim_ids": [],
            "context_claim_ids": ["c1", "c2"],
        },
        "p2": {
            "status": "answered",
            "gap_reasons": ["none"],
            "answer_claim_ids": ["c1", "c2"],
            "context_claim_ids": [],
        },
    }
    policy = {
        "requested_parts": [
            {"id": "p1", "kind": "comparison"},
            {"id": "p2", "kind": "source_facts"},
        ],
        "missing_context": [],
    }
    result, coverage = _normalize(value, "research_comparison", policy)
    assert result["response"]["disposition"] == "comparison_abstention"
    assert len(result["response"]["claims"]) == 2
    assert coverage["p1"]["answer_claim_ids"] == []
    response["coverage"]["p1"].update(
        status="answered", gap_reasons=["none"], answer_claim_ids=["c1"], context_claim_ids=["c2"]
    )
    with pytest.raises(ValueError, match="source_notes_cannot_answer_comparison"):
        _normalize(value, "research_comparison", policy)
