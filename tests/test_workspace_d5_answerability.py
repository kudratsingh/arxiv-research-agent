"""Frozen prospective machine references, separate from producer and human labels."""

import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_answerability import matrix, score_parts

pytestmark = pytest.mark.unit


def archived_cases():
    p = (
        Path(__file__).resolve().parents[1]
        / "planning/14-explore-and-research-modes/d5/evidence/consolidated-campaign-v12/packet.json.gz"
    )
    return json.loads(gzip.decompress(p.read_bytes()))["cases"]


def scored(case_id, *, status="lacks_evidence", disposition="answer", bound=True):
    return {
        "id": case_id,
        "declared_coverage": [{"id": "p" + str(i), "status": status} for i in range(1, 4)],
        "machine_coverage": [{"part_id": "p" + str(i), "decision": status} for i in range(1, 4)],
        "assessment_binding": {"status": "bound" if bound else "unavailable"},
        "response_disposition": disposition,
        "whole_claim_support": {"unsupported": 0},
    }


def test_matrix_locks_all_24_exact_parts_evidence_and_selection_without_mutating_requests():
    cases = archived_cases()
    before = deepcopy(cases)
    ref = matrix(cases)
    assert cases == before and len(ref["rows"]) == 24
    assert ref["matrix_digest"] == _digest({k: v for k, v in ref.items() if k != "matrix_digest"})
    for row in ref["rows"]:
        case = next(c for c in cases if c["id"] == row["case_id"])
        part = next(
            p for p in case["sealed"]["task_policy"]["requested_parts"] if p["id"] == row["part_id"]
        )
        assert row["requested_part"] == part and row["request_digest"] == _digest(part)
        assert row["selection_digest"] == _digest(case["evidence_selection"])
        assert row["human_review"] is None and row["provenance"] == "machine_reference"
        for evidence in row["selected_evidence"]:
            original = case["sealed"]["units"][evidence["handle"]]
            assert evidence["reference_digest"] == _digest(original)
            assert evidence["quote_digest"] == _digest(original["quote"])
            assert evidence["scope"] == "abstract"
    assert matrix(cases) == ref


@pytest.mark.parametrize("kind", ["missing_case", "missing_part", "changed_part_id"])
def test_incomplete_or_changed_requested_parts_cannot_freeze(kind):
    cases = archived_cases()
    if kind == "missing_case":
        cases.pop()
    elif kind == "missing_part":
        cases[-1]["sealed"]["task_policy"]["requested_parts"].pop()
    else:
        cases[-1]["sealed"]["task_policy"]["requested_parts"][0]["id"] = "p9"
    with pytest.raises(AdmissionError, match="answerability_"):
        matrix(cases)


def test_prospective_matrix_changes_when_source_request_or_ranking_changes():
    for kind in ("request", "evidence", "ranking"):
        cases = archived_cases()
        original = matrix(cases)["matrix_digest"]
        case = cases[-1]
        if kind == "request":
            case["sealed"]["task_policy"]["requested_parts"][0]["request"] += " Changed"
        elif kind == "evidence":
            next(iter(case["sealed"]["units"].values()))["version_id"] += "-wrong"
        else:
            case["ranking"].reverse()
        assert matrix(cases)["matrix_digest"] != original


def test_comparison_abstention_can_be_appropriate_while_research_need_remains_unmet():
    ref = matrix(archived_cases())
    case = scored("campaign-eval-research-retrieval", disposition="comparison_abstention")
    parts = score_parts(case, ref)
    assert parts[0]["appropriate_abstention_machine_reference"] is True
    assert parts[0]["request_fulfillment"] == "unmet"
    assert parts[0]["research_need_unmet"] is True and parts[0]["retrieval_gap"] is True
    assert parts[0]["unsupported_claims_in_case"] == 0
    assert all(p["human_judgment"] is None for p in parts)
    case["response_disposition"] = "answer"
    assert score_parts(case, ref)[0]["appropriate_abstention_machine_reference"] is False


def test_full_application_abstention_is_not_a_retrieval_gap_or_comparison_abstention():
    ref = matrix(archived_cases())
    case = scored("campaign-eval-research-insufficient", disposition="full_abstention")
    parts = score_parts(case, ref)
    assert all(p["appropriate_abstention_machine_reference"] is True for p in parts)
    assert all(p["retrieval_gap"] is False for p in parts)
    case["response_disposition"] = "comparison_abstention"
    assert all(
        p["appropriate_abstention_machine_reference"] is False for p in score_parts(case, ref)
    )


def test_missing_evidence_omissions_and_unsupported_answers_are_different():
    ref = matrix(archived_cases())
    case = scored("campaign-eval-learn-conditions", status="answered")
    p1, p2, p3 = score_parts(case, ref)
    assert p1["request_fulfillment"] == "unsupported_answer"
    assert p2["request_fulfillment"] == "partial"
    assert p3["request_fulfillment"] == "met"
    case = scored(case["id"])
    assert score_parts(case, ref)[2]["request_fulfillment"] == "omitted_answer"
    case = scored(case["id"], status="omitted")
    assert all(p["request_fulfillment"] == "omitted_answer" for p in score_parts(case, ref))


@pytest.mark.parametrize("kind", ["unbound", "uncertain", "missing"])
def test_unavailable_or_uncertain_judgments_cannot_score_fulfillment(kind):
    ref = matrix(archived_cases())
    case = scored("campaign-eval-learn-conditions", status="answered", bound=kind != "unbound")
    if kind == "missing":
        case["machine_coverage"] = None
    if kind == "uncertain":
        for row in case["machine_coverage"]:
            row["decision"] = "uncertain"
    assert all(p["request_fulfillment"] == "UNSCORED" for p in score_parts(case, ref))


def test_reference_labels_cannot_become_wire_inputs():
    from src.workspace.d5_adapter import initial_context

    cases = archived_cases()
    before = [initial_context(c["sealed"]) for c in cases]
    ref = matrix(cases)
    ref["rows"][0]["answerability"] = "insufficient"
    assert [initial_context(c["sealed"]) for c in cases] == before
    assert all(
        "reference_answerability" not in json.dumps(c) and "machine_reference" not in json.dumps(c)
        for c in before
    )
