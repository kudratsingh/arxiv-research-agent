"""Prospective wire/local identity controls; synthetic, never provider success."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from src.workspace import assistance_capacity_contract as legacy
from src.workspace import assistance_keyed_contract as keyed
from tests.test_workspace_assistance_capacity_contract import fixture, policy

pytestmark = pytest.mark.unit


def sample(mode="learn", *, parts=3, count=None):
    value, handles, purpose, old = fixture(mode, parts=parts, count=count)
    envelope, coverage = legacy.normalize(value, handles, purpose, old)
    new = {**old, "revision": keyed.REVISION}
    return keyed.wire_payload(envelope, coverage, new), handles, purpose, new


def wire_accepts(value, handles, purpose, pol):
    for schema in keyed.schemas(handles, purpose, pol).values():
        Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize("mode,count", [("learn", 8), ("research", 12)])
def test_maximum_identity_maps_and_lossless_multiple_gaps(mode, count):
    value, h, p, pol = sample(mode, parts=8)
    row = value["response"]["coverage"]["p8"]
    row.update(
        status="lacks_evidence",
        gap_reasons=["methods", "metric_definition", "data_splits"],
        context_claim_ids=["c1"],
    )
    row.pop("answer_claim_ids")
    wire_accepts(value, h, p, pol)
    envelope, coverage = keyed.normalize(value, h, p, pol)
    assert len(envelope["response"]["claims"]) == count
    assert coverage["p8"]["gap_reasons"] == ["methods", "metric_definition", "data_splits"]
    assert keyed.wire_payload(envelope, coverage, pol) == value
    rendered = keyed.render(value, h, p, pol)
    assert rendered["request_coverage"][-1]["gap_reasons"] == row["gap_reasons"]
    assert len(rendered["request_coverage"][-1]["gap_texts"]) == 3
    assert rendered["claim_request_index"]["c1"]["context"] == ["p8"]
    assert not rendered["coverage_complete"]
    assert len(json.dumps(keyed.schemas(h, p, pol)["wire"]).encode()) < 24000


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_part",
        "unknown_part",
        "row_groups",
        "unknown_status",
        "conflicting_status",
        "answer_in_gap",
        "evidence_omission",
        "empty_answer",
        "extra_claim_id",
        "unknown_claim",
        "missing_slot",
        "learn_c9",
        "context_overlap",
        "unknown_ref",
        "orphan",
        "duplicate_ref",
        "duplicate_gap",
        "incorrect_none",
    ],
)
def test_rejects_structural_or_semantic_conflicts(mutation):
    value, h, p, pol = sample()
    r = value["response"]
    row = r["coverage"]["p1"]
    wire_fail = True
    if mutation == "missing_part":
        r["coverage"].pop("p3")
    elif mutation == "unknown_part":
        r["coverage"]["p9"] = deepcopy(row)
    elif mutation == "row_groups":
        r["coverage"] = {"answered": [row], "lacks_evidence": [], "omitted": []}
    elif mutation == "unknown_status":
        row["status"] = "anything"
    elif mutation == "conflicting_status":
        row["status"] = "lacks_evidence"
    elif mutation == "answer_in_gap":
        row.update(status="lacks_evidence", gap_reasons=["methods"])
    elif mutation == "evidence_omission":
        row.update(status="omitted", gap_reasons=["methods"])
        row.pop("answer_claim_ids")
    elif mutation == "empty_answer":
        row["answer_claim_ids"] = []
    elif mutation == "extra_claim_id":
        r["claims"]["c1"]["claim_id"] = "c2"
    elif mutation in {"unknown_claim", "learn_c9"}:
        r["claims"]["c9"] = deepcopy(r["claims"]["c1"])
    elif mutation == "missing_slot":
        r["claims"].pop("c8")
    elif mutation == "context_overlap":
        row["context_claim_ids"] = ["c1"]
        wire_fail = False
    elif mutation == "unknown_ref":
        row["answer_claim_ids"] = ["c12"]
    elif mutation == "orphan":
        for part in r["coverage"].values():
            part["answer_claim_ids"] = ["c1"]
        wire_fail = False
    elif mutation == "duplicate_ref":
        row["answer_claim_ids"] = ["c1", "c1"]
        wire_fail = False
    elif mutation == "duplicate_gap":
        row.update(status="lacks_evidence", gap_reasons=["methods", "methods"])
        row.pop("answer_claim_ids")
        wire_fail = False
    elif mutation == "incorrect_none":
        row["gap_reasons"] = ["methods"]
    with pytest.raises(ValueError):
        keyed.normalize(value, h, p, pol)
    if wire_fail:
        assert list(Draft202012Validator(keyed.schemas(h, p, pol)["wire"]).iter_errors(value))


def test_unknown_or_wrong_revision_and_no_missing_policy():
    value, h, p, pol = sample()
    with pytest.raises(ValueError, match="sealed_keyed_revision_mismatch"):
        keyed.schemas(h, p, {**pol, "revision": legacy.REVISION})
    with pytest.raises(ValueError, match="inconsistent_gap_reason_summary"):
        e, c = keyed.normalize(value, h, p, pol)
        c["p1"]["gap_reasons"] = ["methods"]
        keyed.wire_payload(e, c, pol)


def test_full_abstention_has_no_claims_or_references():
    pol = {
        **policy("research", parts=3, intent="application_assessment"),
        "revision": keyed.REVISION,
    }
    value = {
        "response": {
            "disposition": "full_abstention",
            "reason": "application_context_required",
            "next_action": "request_context",
            "context_requests": dict.fromkeys(pol["missing_context"], "required"),
            "coverage": {
                p["id"]: {"status": "lacks_evidence", "gap_reasons": ["application_context"]}
                for p in pol["requested_parts"]
            },
        }
    }
    wire_accepts(value, ["u1"], "single_paper", pol)
    e, c = keyed.normalize(value, ["u1"], "single_paper", pol)
    assert keyed.wire_payload(e, c, pol) == value
    assert keyed.render(value, ["u1"], "single_paper", pol)["claims"] == []
    for field, val in [
        ("claims", {}),
        ("context_claim_ids", ["c1"]),
        ("reason", "comparison_evidence_required"),
        ("disposition", "answer"),
    ]:
        v = deepcopy(value)
        if field == "context_claim_ids":
            v["response"]["coverage"]["p1"][field] = val
        else:
            v["response"][field] = val
        with pytest.raises(ValueError):
            keyed.normalize(v, ["u1"], "single_paper", pol)
        assert list(
            Draft202012Validator(keyed.schemas(["u1"], "single_paper", pol)["wire"]).iter_errors(v)
        )


def test_comparison_notes_cannot_become_answered_comparison():
    value, h, p, pol = sample("research", count=2)
    pol = {
        **pol,
        "task_intent": "comparison",
        "requested_parts": [
            {**pol["requested_parts"][0], "kind": "comparison"},
            *pol["requested_parts"][1:],
        ],
        "allowed_dispositions": ["answer", "comparison_abstention", "full_abstention"],
    }
    # Start from the application's own task sealer instead of invented policy.
    pol = {**policy("research", parts=3, intent="comparison"), "revision": keyed.REVISION}
    for part in pol["requested_parts"]:
        part["kind"] = "comparison"
    r = value["response"]
    r["disposition"] = "comparison_abstention"
    r["comparison_claims"] = []
    r["comparison_basis"] = []
    for row in r["coverage"].values():
        row.update(
            status="lacks_evidence",
            gap_reasons=["common_evaluation"],
            context_claim_ids=["c1", "c2"],
        )
        row.pop("answer_claim_ids")
    wire_accepts(value, h, "research_comparison", pol)
    rendered = keyed.render(value, h, "research_comparison", pol)
    assert rendered["comparison_unanswered"] and not rendered["coverage_complete"]
    assert rendered["claims"] and all(
        not p["answer_claim_ids"] for p in rendered["request_coverage"]
    )
    r["coverage"]["p1"] = {
        "status": "answered",
        "gap_reasons": ["none"],
        "answer_claim_ids": ["c1"],
        "context_claim_ids": [],
    }
    with pytest.raises(ValueError):
        keyed.normalize(value, h, "research_comparison", pol)
    assert list(
        Draft202012Validator(keyed.schemas(h, "research_comparison", pol)["wire"]).iter_errors(
            value
        )
    )


def test_schema_identity_is_stable_after_jsonb_key_reordering():
    value, _, purpose, pol = sample("research")
    first = keyed.schemas(["u2", "u1"], purpose, pol)
    assert first == keyed.schemas(["u1", "u2"], purpose, pol)
    assert first == keyed.schemas(["u2", "u1", "u2"], purpose, pol)
    assert keyed.normalize(value, ["u2", "u1"], purpose, pol) == keyed.normalize(
        value, ["u1", "u2"], purpose, pol
    )


def test_question_premises_and_comparison_basis_are_wire_enforced():
    value, h, p, pol = sample()
    value["response"]["questions"] = [{"intent": "investigate_claim", "claim_ids": []}]
    assert list(Draft202012Validator(keyed.schemas(h, p, pol)["wire"]).iter_errors(value))
    with pytest.raises(ValueError):
        keyed.normalize(value, h, p, pol)
    value["response"]["questions"] = [{"intent": "methods", "claim_ids": []}]
    wire_accepts(value, h, p, pol)


def test_exact_scope_is_required_on_new_wire_not_defaulted_from_legacy():
    value, handles, purpose, pol = sample()
    value["response"]["claims"]["c1"].pop("required_scope")
    assert list(
        Draft202012Validator(keyed.schemas(handles, purpose, pol)["wire"]).iter_errors(value)
    )
    with pytest.raises(ValueError):
        keyed.normalize(value, handles, purpose, pol)
