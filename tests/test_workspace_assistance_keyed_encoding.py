"""Union-reduced successor fixtures are synthetic, never live successes."""

import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from src.workspace import assistance_keyed_contract as legacy
from src.workspace import assistance_keyed_encoding as codec
from src.workspace.provider_schema_compat import guard
from tests.test_workspace_assistance_capacity_contract import policy
from tests.test_workspace_assistance_keyed_contract import sample

pytestmark = pytest.mark.unit


def example(mode="learn", *, parts=3, count=1):
    old, h, p, pol = sample(mode, parts=parts, count=count)
    envelope, coverage = legacy.normalize(old, h, p, pol)
    new = {**pol, codec.KEY: codec.REVISION}
    return codec.wire_payload(envelope, coverage, new), h, p, new, envelope, coverage


def accepts(value, h, p, pol):
    for schema in legacy.schemas(h, p, pol).values():
        Draft202012Validator(schema).validate(value)
    legacy.response_model(h, p, pol).model_validate(value)


@pytest.mark.parametrize("mode,count", [("learn", 8), ("research", 12)])
@pytest.mark.parametrize("parts", [3, 8])
def test_required_keys_unused_slots_and_maximum_headroom(mode, count, parts):
    value, h, p, pol, e, c = example(mode, parts=parts)
    assert list(value["response"]["claims"]) == [f"c{i}" for i in range(1, count + 1)]
    assert all(value["response"]["claims"][f"c{i}"] == codec.UNUSED for i in range(2, count + 1))
    accepts(value, h, p, pol)
    assert legacy.normalize(value, h, p, pol) == (e, c)
    report = guard(
        {
            "output_config": {
                "format": {"type": "json_schema", "schema": legacy.schemas(h, p, pol)["wire"]}
            }
        }
    )
    assert report["schemas"][0]["direct_union_properties"] == parts + 1
    assert report["expanded_union_nodes"] == parts + 2
    assert report["optional_parameters_conservative"] == 0
    assert legacy.wire_payload(e, c, pol) == value


@pytest.mark.parametrize("mode,count", [("learn", 8), ("research", 12)])
def test_all_emitted_slots_preserve_multi_gaps_and_reciprocal_associations(mode, count):
    value, h, p, pol, e, c = example(mode, parts=8, count=count)
    c["p8"].update(
        status="lacks_evidence",
        gap="methods",
        gap_reasons=["methods", "metric_definition", "data_splits"],
        answer_claim_ids=[],
        context_claim_ids=["c1"],
    )
    value = legacy.wire_payload(e, c, pol)
    accepts(value, h, p, pol)
    normalized, coverage = legacy.normalize(value, h, p, pol)
    assert len(normalized["response"]["claims"]) == count
    assert coverage["p8"]["gap_reasons"] == c["p8"]["gap_reasons"]
    rendered = legacy.render(value, h, p, pol)
    assert rendered["claim_request_index"]["c1"]["context"] == ["p8"]
    assert len(rendered["request_coverage"][-1]["gap_texts"]) == 3


@pytest.mark.parametrize(
    "mutation",
    [
        "null",
        "unused_text",
        "unused_handles",
        "empty_active",
        "scope",
        "missing_key",
        "unknown_key",
        "second_id",
        "unused_reference",
        "orphan",
        "duplicate_ref",
        "unknown_encoding",
    ],
)
def test_no_weakening_of_identity_reference_or_unused_record_integrity(mutation):
    v, h, p, pol, _, _ = example()
    r = v["response"]
    if mutation == "null":
        r["claims"]["c2"] = None
    elif mutation == "unused_text":
        r["claims"]["c2"]["text"] = "A factual assertion cannot hide in an unused slot."
    elif mutation == "unused_handles":
        r["claims"]["c2"]["handles"] = [h[0]]
    elif mutation == "empty_active":
        r["claims"]["c2"]["required_scope"] = "abstract"
    elif mutation == "scope":
        r["claims"]["c1"]["required_scope"] = "unused"
    elif mutation == "missing_key":
        r["claims"].pop("c8")
    elif mutation == "unknown_key":
        r["claims"]["c9"] = deepcopy(codec.UNUSED)
    elif mutation == "second_id":
        r["claims"]["c1"]["claim_id"] = "c2"
    elif mutation == "unused_reference":
        r["coverage"]["p1"]["answer_claim_ids"] = ["c2"]
    elif mutation == "orphan":
        for row in r["coverage"].values():
            row["answer_claim_ids"] = []
    elif mutation == "duplicate_ref":
        r["coverage"]["p1"]["answer_claim_ids"] = ["c1", "c1"]
    elif mutation == "unknown_encoding":
        pol[codec.KEY] = "unapproved"
    with pytest.raises(ValueError):
        legacy.normalize(v, h, p, pol)


def test_comparison_only_source_notes_remain_unanswered_and_cannot_claim_an_answer():
    v, h, p, _, e, c = example("research", count=2)
    p = "research_comparison"
    pol = {
        **policy("research", parts=3, intent="comparison"),
        "revision": legacy.REVISION,
        codec.KEY: codec.REVISION,
    }
    e["response"]["disposition"] = "comparison_abstention"
    e["response"]["comparison_claims"] = []
    e["response"]["comparison_basis"] = []
    for part in pol["requested_parts"]:
        row = c[part["id"]]
        row.update(
            status="lacks_evidence",
            gap="common_evaluation",
            gap_reasons=["common_evaluation"],
            answer_claim_ids=[],
            context_claim_ids=["c1", "c2"],
        )
    v = legacy.wire_payload(e, c, pol)
    accepts(v, h, p, pol)
    assert legacy.render(v, h, p, pol)["comparison_unanswered"]
    comparison = next(x["id"] for x in pol["requested_parts"] if x["kind"] == "comparison")
    v["response"]["coverage"][comparison] = {
        "status": "answered",
        "gap_reasons": ["none"],
        "answer_claim_ids": ["c1"],
        "context_claim_ids": [],
    }
    # A cross-field semantic rule: the shared body does not permit this to
    # become an accepted draft or reach its checker.
    Draft202012Validator(legacy.schemas(h, p, pol)["wire"]).validate(v)
    with pytest.raises(ValueError):
        legacy.normalize(v, h, p, pol)


def test_full_application_abstention_has_no_claims_or_reference_fields():
    pol = {
        **policy("research", parts=8, intent="application_assessment"),
        "revision": legacy.REVISION,
        codec.KEY: codec.REVISION,
    }
    v = {
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
    h = ["h1"]
    p = "research_comparison"
    accepts(v, h, p, pol)
    assert legacy.render(v, h, p, pol)["response_disposition"] == "full_abstention"
    for extra in (
        {"claims": {}},
        {"reason": "comparison_unavailable"},
        {
            "coverage": {
                **v["response"]["coverage"],
                "p1": {"status": "omitted", "gap_reasons": ["claim_budget"]},
            }
        },
    ):
        bad = deepcopy(v)
        bad["response"].update(extra)
        with pytest.raises(ValueError):
            legacy.normalize(bad, h, p, pol)
        assert list(Draft202012Validator(legacy.schemas(h, p, pol)["wire"]).iter_errors(bad))


def test_all_original_v16_schemas_remain_byte_equivalent_without_encoding_marker():
    root = (
        Path(__file__).resolve().parents[1]
        / "planning/15-evaluation-audit-and-recovery/evidence/keyed-contract-v16"
    )
    packet = json.loads(gzip.decompress((root / "packet.json.gz").read_bytes()))
    archived = json.loads(gzip.decompress((root / "DRAFT-SCHEMAS.json.gz").read_bytes()))
    for case in packet["cases"]:
        s = case["sealed"]
        assert (
            legacy.schemas(list(s["units"]), s["response_purpose"], s["task_policy"])
            == archived[case["id"]]
        )


def test_full_without_context_keeps_multiple_gaps_and_rejects_omission_relabeling():
    pol = {**policy("learn", parts=3, sources=1), "revision": legacy.REVISION}
    value = {
        "response": {
            "disposition": "full_abstention",
            "reason": "insufficient_selected_evidence",
            "next_action": "request_context",
            "coverage": {
                p["id"]: {
                    "status": "lacks_evidence",
                    "gap_reasons": ["methods", "metric_definition"],
                }
                for p in pol["requested_parts"]
            },
        }
    }
    new = {**pol, codec.KEY: codec.REVISION}
    accepts(value, ["u1"], "single_paper", new)
    envelope, coverage = legacy.normalize(value, ["u1"], "single_paper", new)
    assert legacy.wire_payload(envelope, coverage, new) == value
    assert all(
        len(row["gap_texts"]) == 2
        for row in legacy.render(value, ["u1"], "single_paper", new)["request_coverage"]
    )
    omitted = deepcopy(value)
    for row in omitted["response"]["coverage"].values():
        row.update(status="omitted", gap_reasons=["claim_budget"])
    old_e, old_c = legacy.normalize(omitted, ["u1"], "single_paper", pol)
    with pytest.raises(ValueError, match="full_abstention_requires_evidence_gaps"):
        legacy.wire_payload(old_e, old_c, new)


def test_new_marker_and_actual_prompt_are_bound_without_changing_legacy_wire():
    from src.workspace.d5_capacity_policy import ROUTES
    from src.workspace.d5_operations import wire
    from src.workspace.provider_schema_compat import REVISION
    from tests.test_workspace_d5_keyed_transport import context

    ctx = context("learn")
    ctx["output_schema"] = legacy.schemas(
        list(ctx["sealed_request"]["units"]), "single_paper", ctx["sealed_request"]["task_policy"]
    )["wire"]
    old = wire(ctx, ROUTES)
    ctx["sealed_request"]["task_policy"][codec.KEY] = codec.REVISION
    ctx["output_schema"] = legacy.schemas(
        list(ctx["sealed_request"]["units"]), "single_paper", ctx["sealed_request"]["task_policy"]
    )["wire"]
    with pytest.raises(ValueError, match="compatibility_binding_required"):
        wire(ctx, ROUTES)
    ctx["sealed_request"]["provider_schema_compatibility_revision"] = REVISION
    actual = wire(ctx, ROUTES)
    prompt = json.loads(actual["messages"][0]["content"])
    assert '"required_scope":"unused"' in prompt["identity_contract"]
    assert "null means" not in prompt["identity_contract"]
    assert old != actual and actual["model"] == old["model"]
    ctx["sealed_request"]["provider_schema_compatibility_revision"] = "unknown"
    with pytest.raises(ValueError, match="compatibility_binding_required"):
        wire(ctx, ROUTES)


def test_maximum_research_comparison_preserves_independent_cited_bases():
    from src.workspace import assistance_capacity_contract as capacity
    from tests.test_workspace_assistance_capacity_contract import fixture

    value, _, _, _ = fixture("research", parts=8, count=12)
    pol = policy("research", parts=8, intent="comparison")
    response = value["response"]
    response["comparison_claims"] = ["c3"]
    response["comparison_basis"] = ["c1", "c2"]
    response["claims"][1]["handles"] = ["u2"]
    response["claims"][2]["handles"] = ["u1", "u2"]
    for index, row in enumerate(response["coverage"]["answered"]):
        row["answer_claim_ids"] = ["c3"]
        row["context_claim_ids"] = [f"c{i}" for i in range(1, 13) if i != 3] if index == 0 else []
    envelope, coverage = capacity.normalize(value, ["u1", "u2"], "research_comparison", pol)
    coverage = {key: {**row, "gap_reasons": [row["gap"]]} for key, row in coverage.items()}
    new = {**pol, "revision": legacy.REVISION, codec.KEY: codec.REVISION}
    wire = legacy.wire_payload(envelope, coverage, new)
    accepts(wire, ["u1", "u2"], "research_comparison", new)
    report = guard(
        {
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": legacy.schemas(["u1", "u2"], "research_comparison", new)["wire"],
                }
            }
        }
    )
    assert report["schemas"][0]["direct_union_properties"] == 9
    assert report["expanded_union_nodes"] == 10
    assert legacy.normalize(wire, ["u1", "u2"], "research_comparison", new) == (envelope, coverage)
