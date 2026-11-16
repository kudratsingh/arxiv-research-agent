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


def test_explicitly_synthetic_matched_empirical_comparison_retains_all_conditions():
    from dataclasses import asdict

    from src.workspace.grounding import (
        SupportCheck,
        SupportDecision,
        claim_input_digest,
        evidence_ref,
        validate_claims,
    )
    from src.workspace.material import extract_text

    sources = tuple(
        extract_text(
            f"On synthetic task T, held-out split D has exactly 100 items. Under frozen settings C, method {name} correctly classifies {score} of the 100 items. Accuracy is correct items divided by 100.",
            work_id=f"synthetic:matched-{name}",
            version_id=f"synthetic:matched-{name}:v1",
            scope="excerpt",
        )
        for name, score in [("A", 80), ("B", 75)]
    )
    refs = {f"synthetic-{i}": evidence_ref(m, m.spans[0]) for i, m in enumerate(sources)}
    x, case, policy, _ = comparison()
    body = x["response"]
    body["claims"] = [
        {
            "text": "On synthetic task T and held-out split D of 100 items under settings C, method A correctly classifies 80/100 items (80% accuracy).",
            "handles": ["synthetic-0"],
            "required_scope": "excerpt",
        },
        {
            "text": "On synthetic task T and held-out split D of 100 items under settings C, method B correctly classifies 75/100 items (75% accuracy).",
            "handles": ["synthetic-1"],
            "required_scope": "excerpt",
        },
        {
            "text": "For synthetic task T, the same held-out split D of 100 items and settings C, the reported accuracy is 80% for method A versus 75% for method B.",
            "handles": ["synthetic-0", "synthetic-1"],
            "required_scope": "excerpt",
        },
    ]
    body.update(background_claims=["c1", "c2"], assumption_claims=[], limitation_claims=[])
    policy["requested_parts"] = [
        {
            "id": "p1",
            "request": "Compare accuracy for the matched synthetic task, split, denominator and conditions.",
            "kind": "comparison",
        },
        {
            "id": "p2",
            "request": "Give each separately cited synthetic source result.",
            "kind": "source_note",
        },
        {
            "id": "p3",
            "request": "Retain the task, split, denominator and settings in the answer.",
            "kind": "answer",
        },
    ]
    body["coverage"] = {
        "p1": {
            "status": "answered",
            "gap_reasons": ["none"],
            "answer_claim_ids": ["c3"],
            "context_claim_ids": ["c1", "c2"],
        },
        "p2": {
            "status": "answered",
            "gap_reasons": ["none"],
            "answer_claim_ids": ["c1", "c2"],
            "context_claim_ids": [],
        },
        "p3": {
            "status": "answered",
            "gap_reasons": ["none"],
            "answer_claim_ids": ["c1", "c2"],
            "context_claim_ids": ["c3"],
        },
    }
    for schema in codec.schemas(list(refs), case["purpose"], policy).values():
        Draft202012Validator(schema).validate(x)
    draft, claims = codec.resolve_draft(x, refs, sources, purpose=case["purpose"], policy=policy)
    assert list(draft.comparison_claims) == ["c3"]
    assert all(len(c.evidence) == (2 if c.claim_id == "c3" else 1) for c in claims)
    unjudged = validate_claims(claims, sources)
    assert all(
        not a.checked and a.decision == SupportDecision.ABSTAIN for a in unjudged.assessments
    )
    # Explicit test-oracle judgments exercise the gate; they are neither live
    # checker observations nor independent human qualification.
    judgments = tuple(
        SupportCheck(
            c.claim_id,
            claim_input_digest(c, sources),
            SupportDecision.SUPPORTED,
            "synthetic-test-oracle",
            "synthetic-v1",
            "Synthetic matched-conditions control only",
        )
        for c in claims
    )
    assessed = validate_claims(claims, sources, judgments)
    assert all(a.checked and a.decision == SupportDecision.SUPPORTED for a in assessed.assessments)
    assert [r.quote for r in claims[2].evidence] == [s.spans[0].text for s in sources]
    assert asdict(claims[2])["required_scope"] == "excerpt"


def test_shared_evaluation_gap_is_specific_to_performance_and_keeps_qualitative_answers():
    from src.workspace.assistance_coverage import GAP_TEXT

    legacy_text = GAP_TEXT["common_evaluation"]
    x, case, policy, _ = comparison("partial")
    view = codec.render(x, list(case["units"]), case["purpose"], policy)
    row = view["request_coverage"][0]
    assert row["gap_reasons"] == ["common_evaluation", "protocol"]
    assert row["gap_texts"] == [
        "Request compatible evaluation tasks, comparators, metrics and conditions before drawing performance conclusions.",
        GAP_TEXT["protocol"],
    ]
    assert row["answer_claim_ids"] == ["c5"]
    assert view["request_outcome"]["full_answer_credit"] is False
    assert GAP_TEXT["common_evaluation"] == legacy_text
    # A supported qualitative contrast has no shared-benchmark requirement.
    x, case, policy, packet = comparison()
    draft, _ = resolve(x, case, policy, packet)
    assert draft.comparison_claims == ("c5",)
    assert codec.render(x, list(case["units"]), case["purpose"], policy)["request_coverage"][0][
        "gap_reasons"
    ] == ["none"]
