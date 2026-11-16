"""Prospective synthetic comparisons; immutable v18 failure receives no new credit."""

import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError

from src.workspace import assistance_comparison_contract as codec
from src.workspace import assistance_consistency_contract as old
from src.workspace import d5_compatibility_packet as spec
from src.workspace.grounding import EvidenceRef
from src.workspace.provider_schema_compat import guard

pytestmark = [pytest.mark.unit, pytest.mark.contract]
ROOT = Path(__file__).resolve().parents[1]
F = ROOT / "tests/fixtures/d5/comparison-v19"


def fixture():
    p = json.loads(
        gzip.decompress(
            (
                ROOT
                / "planning/15-evaluation-audit-and-recovery/evidence/consistency-v18/packet.json.gz"
            ).read_bytes()
        )
    )
    case = next(c for c in p["cases"] if c["id"] == "research-compact")
    pol = {**case["policy"], codec.KEY: codec.REVISION}
    original = json.loads((F / "research-compact-v18-original.json").read_text())
    x = deepcopy(original)
    x["response"].pop("comparison_claims")
    x["response"].pop("comparison_basis")
    return x, case, pol, p


def resolve(x, c, pol, p):
    return codec.resolve_draft(
        x,
        {k: EvidenceRef(**u) for k, u in c["units"].items()},
        spec.materials(p),
        purpose=c["purpose"],
        policy=pol,
    )


def notes():
    x, c, pol, p = fixture()
    row = x["response"]["coverage"]["p1"]
    refs = row["answer_claim_ids"] + row["context_claim_ids"]
    row.update(status="lacks_evidence", answer_claim_ids=[], context_claim_ids=refs)
    return x, c, pol, p


def comparison(status="answered", performance=False):
    x, c, pol, p = notes()
    b = x["response"]
    allhandles = list(c["units"])
    assert len({u["work_id"] for u in c["units"].values()}) == 2
    # Explicit synthetic semantic control, not a rewritten provider success.
    b["claims"].append(
        {
            "text": "Synthetic performance comparison requiring independently checked compatible tasks and metrics."
            if performance
            else "Synthetic qualitative contrast: Self-RAG uses reflection tokens to control retrieval, whereas ReAct interleaves reasoning and actions.",
            "handles": allhandles,
            "required_scope": "excerpt",
        }
    )
    b["coverage"]["p1"].update(
        status=status,
        answer_claim_ids=["c5"],
        context_claim_ids=["c1", "c2", "c3", "c4"],
        gap_reasons=["none"] if status == "answered" else ["common_evaluation", "protocol"],
    )
    return x, c, pol, p


def test_original_remains_rejected_and_hash_bound():
    lineage = json.loads((F / "LINEAGE.json").read_text())
    assert (
        hashlib.sha256((F / "research-compact-v18-original.json").read_bytes()).hexdigest()
        == lineage["fixture_sha256"]
    )
    _, c, _, _ = fixture()
    original = json.loads((F / "research-compact-v18-original.json").read_text())
    with pytest.raises(ValueError, match="source_notes_cannot_answer_comparison"):
        old.normalize(original, list(c["units"]), c["purpose"], c["policy"])
    x, c, pol, p = fixture()
    # Removing bookkeeping alone does not manufacture the missing source bases.
    with pytest.raises(
        ValueError, match="comparison_finding_requires_separately_cited_source_bases"
    ):
        resolve(x, c, pol, p)
    assert x["response"]["claims"] == original["response"]["claims"]
    assert x["response"]["coverage"] == original["response"]["coverage"]


@pytest.mark.parametrize(
    "factory",
    [notes, comparison, lambda: comparison("partial"), lambda: comparison(performance=True)],
)
def test_wire_normalization_and_lossless_roundtrip(factory):
    x, c, pol, p = factory()
    for schema in codec.schemas(list(c["units"]), c["purpose"], pol).values():
        Draft202012Validator(schema).validate(x)
    e, coverage = codec.normalize(x, list(c["units"]), c["purpose"], pol)
    assert codec.wire_payload(e, coverage, pol) == x
    draft, claims = resolve(x, c, pol, p)
    view = codec.render(x, list(c["units"]), c["purpose"], pol)
    assert len(claims) == len(x["response"]["claims"])
    row = coverage["p1"]
    assert row["gap_reasons"] == x["response"]["coverage"]["p1"]["gap_reasons"]
    assert list(draft.comparison_claims) == row["answer_claim_ids"]
    assert list(draft.comparison_basis) == row["answer_claim_ids"]
    if row["status"] != "answered":
        assert view["request_outcome"]["full_answer_credit"] is False
    if not row["answer_claim_ids"]:
        assert (
            view["comparison_unanswered"]
            and view["response_disposition"] == "comparison_abstention"
        )
    # Valid identity/shape never establishes semantic factual support.
    assert "not semantic acceptance" in view["coverage_basis"]


@pytest.mark.parametrize("field", ["comparison_claims", "comparison_basis"])
def test_removed_competing_mapping_is_forbidden(field):
    x, c, pol, _ = comparison()
    x["response"][field] = ["c1"]
    with pytest.raises(ValueError):
        codec.normalize(x, list(c["units"]), c["purpose"], pol)
    with pytest.raises(SchemaValidationError):
        Draft202012Validator(codec.schemas(list(c["units"]), c["purpose"], pol)["wire"]).validate(x)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b["coverage"]["p1"].update(answer_claim_ids=["c12"]),
        lambda b: b["coverage"]["p1"].update(answer_claim_ids=["c5", "c5"]),
        lambda b: b["coverage"]["p1"].update(context_claim_ids=["c5"]),
        lambda b: b["coverage"]["p1"].update(status="answered"),
        lambda b: b["claims"][4].update(handles=["not-selected"]),
    ],
)
def test_malformed_and_false_completion_rejected(mutation):
    x, c, pol, p = comparison("partial")
    mutation(x["response"])
    with pytest.raises(ValueError):
        resolve(x, c, pol, p)


def test_schema_guard_actual_sdk_and_no_duplicate_comparison_metadata():
    x, c, pol, _ = comparison()
    s = codec.schemas(list(c["units"]), c["purpose"], pol)["wire"]
    body = deepcopy(c["body"])
    body["output_config"]["format"]["schema"] = s
    assert guard(body)
    assert "comparison_claims" not in json.dumps(s) and "comparison_basis" not in json.dumps(s)


def test_checker_sees_derived_comparison_abstention_and_keeps_original_wire_tag():
    from src.workspace.admission import _digest
    from src.workspace.d5_adapter import checker_context
    from src.workspace.d5_campaign_v19_packet import predecessor, upgrade

    x, case, pol, packet = notes()
    sealed = upgrade(
        next(c for c in predecessor()["cases"] if c["id"] == "campaign-dev-compare")["sealed"]
    )
    sealed["task_policy"] = pol
    sealed["units"] = case["units"]
    context = checker_context(sealed, x, spec.materials(packet))
    assert x["response"]["disposition"] == "answer"
    assert context["response_layout"]["wire_body_tag"] == "answer"
    assert context["response_layout"]["disposition"] == "comparison_abstention"
    assert context["checked_response_digest"] == _digest(x)
    assert context["comparison_answer_basis"]["p1"]["answer_claim_ids"] == []
    assert context["request_outcome"]["full_answer_credit"] is False


@pytest.mark.parametrize("bad", ["quote", "offset", "version", "hash"])
def test_comparison_citations_keep_exact_material_version_quote_and_unicode_offsets(bad):
    from dataclasses import replace

    x, case, pol, packet = comparison()
    catalog = {k: EvidenceRef(**u) for k, u in case["units"].items()}
    key = next(iter(catalog))
    oldref = catalog[key]
    changes = {
        "quote": {"quote": "Fabricated quotation"},
        "offset": {"start": oldref.start + 1},
        "version": {"version_id": oldref.version_id + "-wrong"},
        "hash": {"source_hash": "sha256:" + "0" * 64},
    }
    catalog[key] = replace(oldref, **changes[bad])
    with pytest.raises(ValueError):
        codec.resolve_draft(x, catalog, spec.materials(packet), purpose=case["purpose"], policy=pol)
