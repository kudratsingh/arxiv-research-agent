"""Purpose-specific schemas; corrected examples are synthetic, never paid results."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from src.workspace import assistance_contract as c
from src.workspace.grounding import validate_claims
from src.workspace.material import extract_text

pytestmark = pytest.mark.unit
FIXTURES = Path(__file__).parent / "fixtures/d5/stage-b-v3"


def payload(catalog, *, comparison=False):
    """SYNTHETIC fixture, not a correction of an accepted provider output."""
    value = {
        "claims": [
            {
                "claim_id": f"c{i + 1}",
                "text": ref.quote,
                "handles": [h],
                "required_scope": ref.scope,
            }
            for i, (h, ref) in enumerate(catalog.items())
        ],
        "background": "Inspect the cited passages before interpreting the result.",
        "assumptions": [],
        "gaps": ["Only selected passages are available."],
        "questions": ["Which evaluation conditions differ?"],
        "proposal": "Proposed next step: inspect the original evaluation conditions.",
        "abstention": None,
    }
    if comparison:
        value.update(
            comparison="Compare the separately cited settings before drawing a conclusion.",
            comparison_basis=[x["claim_id"] for x in value["claims"]],
        )
    return value


@pytest.fixture
def evidence():
    materials = [
        extract_text(
            "Method A improves accuracy only with external tools on a small benchmark. It can repeat earlier actions.",
            work_id="paper-a",
            version_id="paper-a:v1",
            scope="abstract",
        ),
        extract_text(
            "Method B reports lower accuracy on a different benchmark. The evaluation does not establish a direct performance comparison.",
            work_id="paper-b",
            version_id="paper-b:v1",
            scope="abstract",
        ),
    ]
    catalog = c.coherent_units(materials, {s.span_id for m in materials for s in m.spans})
    return materials, catalog


def validate_both(value, catalog, purpose):
    for schema in c.schemas(list(catalog), purpose=purpose).values():
        jsonschema.Draft202012Validator(schema).validate(value)
    return c.response_model(list(catalog), purpose=purpose).model_validate(value)


def test_original_failed_response_is_unchanged_and_rejected_by_new_wire_and_local_contract():
    bindings = json.loads((FIXTURES / "bindings.json").read_text())
    for name, digest in bindings["files"].items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest
    request = json.loads((FIXTURES / "dev-learn-initial-request.json").read_text())
    response = json.loads((FIXTURES / "dev-learn-provider-response.json").read_text())
    original = json.loads(response["content"][0]["text"])
    selected = json.loads(request["messages"][0]["content"])["sealed_request"]["units"]
    assert c.response_purpose("learn", selected) == "single_paper"
    # Historical wire accepted this structural payload; it remains a failed paid attempt.
    jsonschema.Draft202012Validator(request["output_config"]["format"]["schema"]).validate(original)
    assert original["comparison_basis"] == original["claims"][0]["handles"]
    for purpose in ("single_paper", "research_comparison"):
        for schema in c.schemas(list(selected), purpose=purpose).values():
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.Draft202012Validator(schema).validate(original)
        with pytest.raises(ValueError):
            c.response_model(list(selected), purpose=purpose).model_validate(original)
    assert bindings["content_accepted"] is False and bindings["state"] == "failed"


def test_shared_claim_id_enum_and_handle_descriptions_survive_sdk_transform():
    for schema in c.schemas(["u-selected"]).values():
        text = json.dumps(schema)
        basis = schema["properties"]["comparison_basis"]
        assert basis["items"]["enum"] == ["c1", "c2", "c3", "c4", "c5", "c6"]
        assert "NOT evidence handles" in basis["description"]
        assert "Selected evidence handles" in text and "never claim IDs" in text
        assert any(
            v.get("properties", {}).get("claim_id", {}).get("enum") == basis["items"]["enum"]
            for v in schema.get("$defs", {}).values()
        )


@pytest.mark.parametrize(
    "mode,works,expected",
    [
        ("learn", ["a"], "single_paper"),
        ("learn", ["a", "b"], "single_paper"),
        ("research", ["a"], "single_paper"),
        ("research", ["a", "a"], "single_paper"),
        ("research", ["a", "b"], "research_comparison"),
    ],
)
def test_applicability_uses_mode_and_distinct_selected_works(mode, works, expected):
    assert (
        c.response_purpose(mode, {str(i): {"work_id": w} for i, w in enumerate(works)}) == expected
    )


def test_single_paper_and_attributed_within_paper_contrast_validate_both(evidence):
    materials, all_units = evidence
    catalog = {h: ref for h, ref in all_units.items() if ref.work_id == "paper-a"}
    value = payload(catalog)
    # Contrast stays an attributed factual claim, with its complete qualification.
    value["claims"][0]["text"] = (
        "The selected abstract attributes an accuracy improvement to Method A only with external tools on a small benchmark, and notes repeated actions."
    )
    assert "comparison" not in validate_both(value, catalog, "single_paper").model_dump()
    _, claims = c.resolve_draft(value, catalog, materials, purpose="single_paper")
    report = validate_claims(claims, materials)
    assert report.assessments[0].identity_resolved and report.support_ratio is None
    for schema in c.schemas(list(catalog), purpose="single_paper").values():
        assert (
            "comparison" not in schema["properties"]
            and "comparison_basis" not in schema["properties"]
        )
        assert schema["additionalProperties"] is False


def test_two_source_research_comparison_requires_independent_citations(evidence):
    materials, catalog = evidence
    value = payload(catalog, comparison=True)
    validate_both(value, catalog, "research_comparison")
    draft, claims = c.resolve_draft(value, catalog, materials, purpose="research_comparison")
    assert (
        isinstance(draft, c.AssistanceDraft)
        and len({r.work_id for claim in claims for r in claim.evidence}) == 2
    )
    # A second version/passage of one paper cannot substitute for another work.
    h = next(iter(catalog))
    value["claims"][1]["handles"] = [h]
    with pytest.raises(ValueError, match="two_separately_cited"):
        c.resolve_draft(value, catalog, materials)


@pytest.mark.parametrize(
    "change",
    [
        "handle",
        "unknown_id",
        "missing_claim",
        "duplicate_basis",
        "duplicate_claim",
        "missing_basis",
        "basis_without_comparison",
        "one_basis",
    ],
)
def test_research_basis_refuses_invalid_missing_or_duplicate_references(evidence, change):
    _, catalog = evidence
    value = payload(catalog, comparison=True)
    if change == "handle":
        value["comparison_basis"] = [next(iter(catalog))]
    elif change == "unknown_id":
        value["comparison_basis"] = ["c7"]
    elif change == "missing_claim":
        value["comparison_basis"] = ["c1", "c6"]
    elif change == "duplicate_basis":
        value["comparison_basis"] = ["c1", "c1"]
    elif change == "duplicate_claim":
        value["claims"][1]["claim_id"] = "c1"
    elif change == "missing_basis":
        del value["comparison_basis"]
    elif change == "basis_without_comparison":
        value["comparison"] = ""
    else:
        value["comparison_basis"] = ["c1"]
    with pytest.raises(ValueError):
        c.response_model(list(catalog)).model_validate(value)
    if change in {"handle", "unknown_id", "missing_basis"}:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(c.schemas(list(catalog))["wire"]).validate(value)


@pytest.mark.parametrize("purpose", ["single_paper", "research_comparison"])
def test_insufficient_evidence_can_abstain_without_fabricated_comparison(evidence, purpose):
    materials, catalog = evidence
    value = payload(catalog, comparison=purpose == "research_comparison")
    value.update(
        claims=[],
        abstention="Selected abstracts do not establish a compatible comparison or safe deployment.",
    )
    if purpose == "research_comparison":
        value.update(comparison="", comparison_basis=[])
    validate_both(value, catalog, purpose)
    _, claims = c.resolve_draft(value, catalog, materials, purpose=purpose)
    assert claims == ()
    value["abstention"] = None
    with pytest.raises(ValueError, match="claims_or_abstention"):
        c.response_model(list(catalog), purpose=purpose).model_validate(value)


def test_synthetic_manual_correction_is_not_provider_success():
    original = json.loads((FIXTURES / "dev-learn-provider-response.json").read_text())
    request = json.loads((FIXTURES / "dev-learn-initial-request.json").read_text())
    selected = json.loads(request["messages"][0]["content"])["sealed_request"]["units"]
    synthetic = deepcopy(json.loads(original["content"][0]["text"]))
    synthetic.pop("comparison")
    synthetic.pop("comparison_basis")
    validate_both(synthetic, selected, "single_paper")
    assert original["content"][0]["text"] != json.dumps(synthetic)
    assert synthetic["background"].startswith("Unverified")  # Still requires checker/prose review.


def test_invalid_purpose_is_refused():
    with pytest.raises(ValueError, match="invalid_response_purpose"):
        c.response_model(["u1"], purpose="unchecked")
