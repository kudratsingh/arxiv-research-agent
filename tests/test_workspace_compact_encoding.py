"""Prospective compact formats; all fixtures are synthetic, never live successes."""

from __future__ import annotations

import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from src.workspace import assistance_compact_encoding as codec
from src.workspace import assistance_keyed_contract as keyed
from src.workspace.provider_schema_compat import guard
from tests.test_workspace_assistance_capacity_contract import policy
from tests.test_workspace_assistance_keyed_contract import sample

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def example(mode="learn", count=2, parts=3, revision=codec.REVISION):
    old, handles, purpose, pol = sample(mode, parts=parts, count=count)
    envelope, coverage = keyed.normalize(old, handles, purpose, pol)
    pol = {**pol, codec.KEY: revision}
    value = codec.wire_payload(envelope, coverage, pol)
    return value, handles, purpose, pol, envelope, coverage


@pytest.mark.parametrize(
    "mode,count", [("learn", 1), ("learn", 8), ("research", 1), ("research", 12)]
)
@pytest.mark.parametrize("parts", [3, 8])
@pytest.mark.parametrize("revision", [codec.LIST_CONTROL, codec.REVISION])
def test_variable_claims_rich_roundtrip_and_actual_sdk(mode, count, parts, revision):
    value, h, p, pol, e, c = example(mode, count, parts, revision)
    before = deepcopy((value, h, p, pol))
    assert isinstance(value["response"]["claims"], list)
    assert len(value["response"]["claims"]) == count
    assert all(
        "claim_id" not in claim and "part_ids" not in claim for claim in value["response"]["claims"]
    )
    schemas = keyed.schemas(h, p, pol)
    assert schemas["wire"] == transform_schema(schemas["local"])
    for schema in schemas.values():
        Draft202012Validator(schema).validate(value)
    assert keyed.normalize(value, h, p, pol) == (e, c)
    assert [x["claim_id"] for x in e["response"]["claims"]] == [
        f"c{i}" for i in range(1, count + 1)
    ]
    assert keyed.wire_payload(e, c, pol) == value
    assert before == (value, h, p, pol)
    measured = guard(
        {"output_config": {"format": {"type": "json_schema", "schema": schemas["wire"]}}}
    )
    assert measured["expanded_union_nodes"] == (1 if revision == codec.REVISION else parts + 2)
    assert measured["optional_parameters_conservative"] == 0


def test_multiple_gaps_and_context_remain_lossless_and_inspectable():
    v, h, p, pol, e, c = example("research", 12, 8)
    c["p8"].update(
        status="lacks_evidence",
        gap="methods",
        gap_reasons=["methods", "metric_definition", "data_splits"],
        answer_claim_ids=[],
        context_claim_ids=["c1"],
    )
    v = keyed.wire_payload(e, c, pol)
    assert v["response"]["coverage"]["p8"]["answer_claim_ids"] == []
    assert keyed.normalize(v, h, p, pol) == (e, c)
    rendered = keyed.render(v, h, p, pol)
    assert rendered["request_coverage"][-1]["gap_reasons"] == [
        "methods",
        "metric_definition",
        "data_splits",
    ]
    assert rendered["claim_request_index"]["c1"]["context"] == ["p8"]


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_encoding",
        "claim_id",
        "part_ids",
        "placeholder",
        "empty_claims",
        "too_many_claims",
        "missing_part",
        "unknown_part",
        "orphan",
        "duplicate_ref",
        "unknown_ref",
        "context_overlap",
        "answer_with_gap",
        "gap_with_answer",
        "omission_with_evidence_reason",
        "duplicate_gap",
        "unselected_handle",
        "unscored_background",
        "neutral_premise",
        "cited_question_missing_claim",
    ],
)
def test_no_weakening_of_local_semantics(mutation):
    v, h, p, pol, _, _ = example()
    response = v["response"]
    row = response["coverage"]["p1"]
    if mutation == "unknown_encoding":
        pol[codec.KEY] = "not-sealed"
    elif mutation in {"claim_id", "part_ids"}:
        response["claims"][0][mutation] = "c7"
    elif mutation == "placeholder":
        response["claims"].append({"text": "", "handles": [], "required_scope": "unused"})
    elif mutation == "empty_claims":
        response["claims"] = []
    elif mutation == "too_many_claims":
        response["claims"] = response["claims"] * 8
    elif mutation == "missing_part":
        response["coverage"].pop("p3")
    elif mutation == "unknown_part":
        response["coverage"]["p9"] = deepcopy(row)
    elif mutation == "orphan":
        for item in response["coverage"].values():
            item["answer_claim_ids"] = ["c1"]
    elif mutation == "duplicate_ref":
        row["answer_claim_ids"] = ["c1", "c1"]
    elif mutation == "unknown_ref":
        row["answer_claim_ids"] = ["c8"]
    elif mutation == "context_overlap":
        row["context_claim_ids"] = list(row["answer_claim_ids"])
    elif mutation == "answer_with_gap":
        row["gap_reasons"] = ["methods"]
    elif mutation == "gap_with_answer":
        row.update(status="lacks_evidence", gap_reasons=["methods"])
    elif mutation == "omission_with_evidence_reason":
        row.update(status="omitted", gap_reasons=["methods"], answer_claim_ids=[])
    elif mutation == "duplicate_gap":
        row.update(status="lacks_evidence", gap_reasons=["methods", "methods"], answer_claim_ids=[])
    elif mutation == "unselected_handle":
        response["claims"][0]["handles"] = ["not-selected"]
    elif mutation == "unscored_background":
        response["background"] = "A factual assertion outside scored claims."
    elif mutation == "neutral_premise":
        response["questions"] = [{"intent": "methods", "claim_ids": ["c1"]}]
    elif mutation == "cited_question_missing_claim":
        response["questions"] = [{"intent": "investigate_claim", "claim_ids": []}]
    with pytest.raises(ValueError):
        keyed.normalize(v, h, p, pol)


def test_flat_status_relationship_is_explicit_local_gate_not_claimed_wire_enforcement():
    v, h, p, pol, _, _ = example()
    v["response"]["coverage"]["p1"].update(status="lacks_evidence", gap_reasons=["methods"])
    Draft202012Validator(keyed.schemas(h, p, pol)["wire"]).validate(v)
    with pytest.raises(ValueError, match="forbids_answer"):
        keyed.normalize(v, h, p, pol)


def test_full_abstention_stays_structurally_claim_free():
    pol = {
        **policy("research", parts=3, intent="application_assessment"),
        "revision": keyed.REVISION,
        codec.KEY: codec.REVISION,
    }
    v = {
        "response": {
            "disposition": "full_abstention",
            "reason": "application_context_required",
            "next_action": "request_context",
            "context_requests": dict.fromkeys(pol["missing_context"], "required"),
            "coverage": {
                part["id"]: {"status": "lacks_evidence", "gap_reasons": ["application_context"]}
                for part in pol["requested_parts"]
            },
        }
    }
    for schema in keyed.schemas(["u1"], "single_paper", pol).values():
        Draft202012Validator(schema).validate(v)
    rendered = keyed.render(v, ["u1"], "single_paper", pol)
    assert rendered["claims"] == [] and len(rendered["context_requests"]) == 4
    for field in ["claims", "answer_claim_ids", "context_claim_ids"]:
        invalid = deepcopy(v)
        if field == "claims":
            invalid["response"][field] = []
        else:
            invalid["response"]["coverage"]["p1"][field] = []
        with pytest.raises(ValueError):
            keyed.normalize(invalid, ["u1"], "single_paper", pol)


def test_comparison_only_notes_stay_unanswered():
    v, h, _, pol, e, c = example("research", 2)
    pol = {
        **policy("research", parts=3, intent="comparison"),
        "revision": keyed.REVISION,
        codec.KEY: codec.REVISION,
    }
    e["response"].update(
        disposition="comparison_abstention", comparison_claims=[], comparison_basis=[]
    )
    for row in c.values():
        row.update(
            status="lacks_evidence",
            gap="common_evaluation",
            gap_reasons=["common_evaluation"],
            answer_claim_ids=[],
            context_claim_ids=["c1", "c2"],
        )
    v = keyed.wire_payload(e, c, pol)
    rendered = keyed.render(v, h, "research_comparison", pol)
    assert rendered["comparison_unanswered"] and not rendered["coverage_complete"]
    comparison = next(x["id"] for x in pol["requested_parts"] if x["kind"] == "comparison")
    v["response"]["coverage"][comparison].update(
        status="answered", gap_reasons=["none"], answer_claim_ids=["c1"], context_claim_ids=[]
    )
    with pytest.raises(ValueError):
        keyed.normalize(v, h, "research_comparison", pol)


def test_owned_inverse_refuses_renumbering_historical_noncontiguous_ids():
    _, _, _, pol, e, c = example()
    e["response"]["claims"][1]["claim_id"] = "c3"
    with pytest.raises(ValueError, match="renumber"):
        codec.wire_payload(e, c, pol)


def test_archived_schemas_remain_identical_under_original_revisions():
    path = Path(
        "planning/15-evaluation-audit-and-recovery/evidence/keyed-contract-v16r2/packet.json.gz"
    )
    packet = json.loads(gzip.decompress(path.read_bytes()))
    for case in packet["cases"]:
        sealed = case["sealed"]
        assert (
            keyed.schemas(list(sealed["units"]), sealed["response_purpose"], sealed["task_policy"])
            == sealed["response_schemas"]
        )
