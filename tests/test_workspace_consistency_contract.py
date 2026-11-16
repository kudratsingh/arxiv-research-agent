"""Full original public payloads are immutable; every altered example is synthetic.

Passing these tests establishes mechanical contracts only, never provider success,
whole-claim truth, independent human support or a qualified checker.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from src.workspace import assistance_consistency_checks as checks
from src.workspace import assistance_consistency_contract as codec
from src.workspace import assistance_keyed_checks as oldchecks
from src.workspace import assistance_keyed_contract as keyed
from src.workspace import d5_compatibility_packet as oldspec
from src.workspace.assistance_coverage import review_failed
from src.workspace.d5_adapter import checker_context
from src.workspace.grounding import EvidenceRef, validate_claims
from src.workspace.provider_schema_compat import guard
from tests.test_workspace_assistance_capacity_contract import policy
from tests.test_workspace_compact_encoding import example as previous_example

pytestmark = [pytest.mark.unit, pytest.mark.contract]
ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/d5/consistency-v18"


def predecessor():
    return json.loads(
        gzip.decompress(
            (
                ROOT
                / "planning/15-evaluation-audit-and-recovery/evidence/grammar-diagnostic-v17r2/packet.json.gz"
            ).read_bytes()
        )
    )


def original(name):
    return json.loads((FIX / (name + "-original.json")).read_text())


def synthetic_upgrade(value):
    """Explicit test-only derivative; never modify or accept a historical job."""
    x = deepcopy(value)
    if x["response"]["disposition"] != "full_abstention":
        x["response"]["disposition"] = "answer"
        for q in x["response"]["questions"]:
            refs = q.pop("claim_ids")
            q.update(
                context_claim_ids=[] if q["intent"] == "investigate_claim" else refs,
                premise_claim_ids=refs if q["intent"] == "investigate_claim" else [],
            )
    return x


def learn(stage="complete"):
    p = predecessor()
    case = next(c for c in p["cases"] if c["id"] == "learn-compact")
    pol = {**case["policy"], codec.KEY: codec.REVISION}
    x = synthetic_upgrade(original("learn-compact"))
    if stage == "complete":
        for row in x["response"]["coverage"].values():
            row["status"] = "partial"
    return x, case, pol, p


def context_for_learn(x, case, pol, p):
    previous = json.loads(
        gzip.decompress(
            (
                ROOT
                / "planning/15-evaluation-audit-and-recovery/evidence/keyed-contract-v16r2/packet.json.gz"
            ).read_bytes()
        )
    )
    sealed = deepcopy(previous["cases"][0]["sealed"])
    sealed["task_policy"] = pol
    return checker_context(sealed, x, oldspec.materials(p))


def synthetic_verdict(context):
    return {
        "revision": checks.REVISION,
        "claim_reviews": {
            c["claim_id"]: {
                "decision": "supported",
                "reason": "Synthetic software control; scientific quality unmeasured.",
                "atomicity": "atomic",
                "qualifications": dict.fromkeys(
                    ["study_scope", "comparator", "metric_definition", "conditions"], "retained"
                ),
            }
            for c in context["claim_inputs"]
        },
        "coverage_checks": {
            r["part_id"]: {
                "decision": next(
                    p["status"] for p in context["declared_coverage"] if p["id"] == r["part_id"]
                ),
                "reason": "Synthetic explicit matching judgment, not independent evidence.",
                "critiques": [],
            }
            for r in context["coverage_inputs"]
        },
        "prose_findings": {k: [] for k in oldchecks.prose_locations(context)},
        "prose_uncertainties": {k: [] for k in oldchecks.prose_locations(context)},
        "priority_review": "respected",
    }


def synthetic_old_checker():
    p = predecessor()
    context = deepcopy(next(c for c in p["cases"] if c["id"] == "checker-small")["context"])
    context["checker_normalization_revision"] = checks.NORMALIZATION_REVISION
    x = original("checker-small")
    x["revision"] = checks.REVISION
    x.pop("prose_review")
    criticism = list(x["prose_findings"]["l2"])
    for row in x["coverage_checks"].values():
        row["critiques"] = []
    x["coverage_checks"]["p3"]["critiques"] = criticism
    x["prose_findings"] = {k: [] for k in oldchecks.prose_locations(context)}
    x["prose_uncertainties"] = {k: [] for k in oldchecks.prose_locations(context)}
    return x, context


def test_original_generated_payloads_are_complete_and_immutable():
    lineage = json.loads((FIX / "LINEAGE.json").read_text())
    for row in lineage["fixtures"]:
        assert hashlib.sha256((ROOT / row["fixture"]).read_bytes()).hexdigest() == row["sha256"]
    x, case, _, p = learn()
    with pytest.raises(ValueError, match="compact_neutral_question_forbids_claim_premise"):
        keyed.normalize(
            original("learn-compact"), list(case["units"]), case["purpose"], case["policy"]
        )
    oldcontext = next(c for c in p["cases"] if c["id"] == "checker-small")["context"]
    with pytest.raises(ValueError, match="prose_finding_required_or_inconsistent"):
        oldchecks.normalize(original("checker-small"), oldcontext)
    assert len(original("learn-compact")["response"]["claims"]) == 5


def test_stepwise_original_learn_exposes_masked_coverage_then_reaches_provenance_and_checker():
    x, case, pol, p = learn("question-only")
    for schema in codec.schemas(list(case["units"]), case["purpose"], pol).values():
        Draft202012Validator(schema).validate(x)
    with pytest.raises(ValueError, match="answered_requires_complete_answer_without_gaps"):
        codec.normalize(x, list(case["units"]), case["purpose"], pol)
    x, case, pol, p = learn()
    e, c = keyed.normalize(x, list(case["units"]), case["purpose"], pol)
    assert codec.wire_payload(e, c, pol) == x
    assert [r["gap_reasons"] for r in c.values()] == [
        r["gap_reasons"] for r in original("learn-compact")["response"]["coverage"].values()
    ]
    rendered = keyed.render(x, list(case["units"]), case["purpose"], pol)
    assert (
        rendered["request_outcome"]["partial_parts"] == 3
        and rendered["request_outcome"]["fully_answered_parts"] == 0
    )
    assert (
        not rendered["coverage_complete"] and not rendered["request_outcome"]["full_answer_credit"]
    )
    assert rendered["question_references"][1]["context_claim_ids"] == ["c2", "c4"]
    assert rendered["question_references"][1]["premise_claim_ids"] == []
    draft, claims = keyed.resolve_draft(
        x,
        {k: EvidenceRef(**v) for k, v in case["units"].items()},
        oldspec.materials(p),
        purpose=case["purpose"],
        policy=pol,
    )
    assert [c.text for c in claims] == [
        c["text"] for c in original("learn-compact")["response"]["claims"]
    ]
    grounding = validate_claims(claims, oldspec.materials(p))
    assert grounding.checked == 0 and grounding.support_ratio is None
    context = context_for_learn(x, case, pol, p)
    assert context["question_reference_roles"] == rendered["question_references"]
    raw = synthetic_verdict(context)
    normalized = checks.normalize(raw, context)
    verdict = checks.Checks.model_validate(normalized)
    summary = checks.aggregate(verdict, context)
    assert summary["partial_parts"] == 3 and not summary["full_answer_credit"]
    assert not review_failed(verdict, rendered)


def test_original_checker_reclassification_preserves_every_negative_judgment_and_exposes_remaining_path():
    x, context = synthetic_old_checker()
    for schema in checks.schemas(context).values():
        Draft202012Validator(schema).validate(x)
    normalized = oldchecks.normalize(x, context)
    v = checks.Checks.model_validate(normalized)
    assert (
        v.prose_review == "procedural_only"
        and not v.prose_findings
        and len(v.coverage_critiques) == 1
    )
    assert v.claim_quality[0].atomicity == "bundled"
    assert v.claim_quality[1].qualifications.comparator == "uncertain"
    assert v.coverage_checks[1].decision == "answered"
    summary = checks.aggregate(v, context)
    assert summary["coverage_disagreements"] == ["p2", "p3"] and summary["quality_gate"] == "FAIL"
    assert summary["coverage_critique_count"] == 1 and summary["factual_prose_findings"] == 0
    assert not summary["full_answer_credit"]
    assert review_failed(v, {"request_coverage": context["declared_coverage"]})
    assert checks.compact(normalized, context) == x


@pytest.mark.parametrize("kind", ["unsupported_factual_prose", "uncertain"])
def test_prose_findings_are_not_ignored_or_relabelled_as_quality_success(kind):
    x, context = synthetic_old_checker()
    key = next(
        k for k, r in oldchecks.prose_locations(context).items() if r["field"] == "questions"
    )
    x["prose_findings" if kind == "unsupported_factual_prose" else "prose_uncertainties"][key] = [
        "Synthetic adversarial assertion or unresolved premise."
    ]
    v = checks.Checks.model_validate(checks.normalize(x, context))
    assert v.prose_review == (
        "unscored_factual_content" if kind == "unsupported_factual_prose" else "abstain"
    )
    assert (
        len(v.prose_findings) + len(v.prose_uncertainties) == 1 and len(v.coverage_critiques) == 1
    )
    assert checks.compact(v.model_dump(mode="json"), context) == x
    assert checks.aggregate(v, context)["quality_gate"] != "PASS"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_claim",
        "unknown_claim",
        "missing_part",
        "unknown_part",
        "missing_location",
        "old_global_flag",
        "missing_uncertainty_location",
        "missing_critiques",
        "duplicate_critique",
        "missing_reason",
    ],
)
def test_checker_requires_every_judgment_and_categorized_finding(mutation):
    x, context = synthetic_old_checker()
    if mutation == "missing_claim":
        x["claim_reviews"].pop("c1")
    elif mutation == "unknown_claim":
        x["claim_reviews"]["c12"] = deepcopy(x["claim_reviews"]["c1"])
    elif mutation == "missing_part":
        x["coverage_checks"].pop("p1")
    elif mutation == "unknown_part":
        x["coverage_checks"]["p8"] = deepcopy(x["coverage_checks"]["p1"])
    elif mutation == "missing_location":
        x["prose_findings"].pop("l1")
    elif mutation == "old_global_flag":
        x["prose_review"] = "procedural_only"
    elif mutation == "missing_uncertainty_location":
        x["prose_uncertainties"].pop("l1")
    elif mutation == "missing_critiques":
        x["coverage_checks"]["p3"].pop("critiques")
    elif mutation == "duplicate_critique":
        x["coverage_checks"]["p3"]["critiques"] *= 2
    elif mutation == "missing_reason":
        x["coverage_checks"]["p3"].pop("reason")
    with pytest.raises(ValueError):
        checks.normalize(x, context)


@pytest.mark.parametrize(
    "mutation",
    [
        "neutral_premise",
        "missing_premise",
        "old_question_mapping",
        "overlapping_question_roles",
        "unknown_question_ref",
        "answer_with_gap",
        "partial_without_answer",
        "partial_none",
        "evidence_with_answer",
        "omission_with_evidence_gap",
        "duplicate_ref",
        "orphan",
        "extra_part",
        "unknown_gap",
    ],
)
def test_draft_rejects_ambiguity_without_deleting_gaps_or_changing_claims(mutation):
    x, case, pol, p = learn()
    r = x["response"]
    q = r["questions"][1]
    row = r["coverage"]["p1"]
    if mutation == "neutral_premise":
        q["premise_claim_ids"] = ["c1"]
    elif mutation == "missing_premise":
        q.update(intent="investigate_claim")
    elif mutation == "old_question_mapping":
        q["claim_ids"] = []
    elif mutation == "overlapping_question_roles":
        q.update(intent="investigate_claim", premise_claim_ids=["c2"])
    elif mutation == "unknown_question_ref":
        q["context_claim_ids"] = ["c8"]
    elif mutation == "answer_with_gap":
        row["status"] = "answered"
    elif mutation == "partial_without_answer":
        row["answer_claim_ids"] = []
    elif mutation == "partial_none":
        row["gap_reasons"] = ["none"]
    elif mutation == "evidence_with_answer":
        row["status"] = "lacks_evidence"
    elif mutation == "omission_with_evidence_gap":
        row.update(status="omitted", answer_claim_ids=[])
    elif mutation == "duplicate_ref":
        row["answer_claim_ids"].append("c1")
    elif mutation == "orphan":
        r["claims"].append(deepcopy(r["claims"][0]))
    elif mutation == "extra_part":
        r["coverage"]["p8"] = deepcopy(row)
    elif mutation == "unknown_gap":
        row["gap_reasons"] = ["made_up"]
    with pytest.raises(ValueError):
        codec.normalize(x, list(case["units"]), case["purpose"], pol)


@pytest.mark.parametrize(
    "mode,count", [("learn", 1), ("learn", 8), ("research", 2), ("research", 12)]
)
@pytest.mark.parametrize("parts", [3, 8])
def test_maximum_supported_shapes_keep_compiled_family_structure(mode, count, parts):
    old, h, p, pol, _, _ = previous_example(mode, count, parts)
    pol = {**pol, codec.KEY: codec.REVISION}
    x = synthetic_upgrade(old)
    model = codec.schemas(h, p, pol)
    assert model["wire"] == transform_schema(model["local"])
    for schema in model.values():
        Draft202012Validator(schema).validate(x)
    e, c = codec.normalize(x, h, p, pol)
    assert codec.wire_payload(e, c, pol) == x
    assert (
        guard({"output_config": {"format": {"type": "json_schema", "schema": model["wire"]}}})[
            "expanded_union_nodes"
        ]
        == 1
    )


def test_full_abstention_keeps_claims_and_references_structurally_absent():
    pol = {
        **policy("research", parts=3, intent="application_assessment"),
        "revision": keyed.REVISION,
        codec.KEY: codec.REVISION,
    }
    x = {
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
    for schema in codec.schemas(["u1"], "single_paper", pol).values():
        Draft202012Validator(schema).validate(x)
    rendered = codec.render(x, ["u1"], "single_paper", pol)
    assert not rendered["claims"] and not rendered["coverage_complete"]
    for field in ["claims", "context_claim_ids", "answer_claim_ids"]:
        y = deepcopy(x)
        if field == "claims":
            y["response"][field] = []
        else:
            y["response"]["coverage"]["p1"][field] = []
        with pytest.raises(ValueError):
            codec.normalize(y, ["u1"], "single_paper", pol)


def test_comparison_notes_do_not_earn_comparison_or_full_answer_credit():
    old, h, p, pol, _, _ = previous_example("research", 2, 3)
    pol = {
        **policy("research", parts=3, intent="comparison"),
        "revision": keyed.REVISION,
        codec.KEY: codec.REVISION,
    }
    x = synthetic_upgrade(old)
    x["response"].update(comparison_claims=[], comparison_basis=[])
    for row in x["response"]["coverage"].values():
        row.update(
            status="lacks_evidence",
            gap_reasons=["common_evaluation"],
            answer_claim_ids=[],
            context_claim_ids=["c1", "c2"],
        )
    r = codec.render(x, h, "research_comparison", pol)
    assert r["comparison_unanswered"] and not r["coverage_complete"]
    assert r["request_outcome"]["status"] == "insufficient_evidence"
    assert r["response_disposition"] == "comparison_abstention"


@pytest.mark.parametrize(
    "judgment,expected", [("supported", "PASS"), ("unsupported", "FAIL"), ("abstain", "HOLD")]
)
def test_aggregate_uses_supplied_support_and_preserves_empty_quality_denominators(
    judgment, expected
):
    x, case, pol, p = learn()
    context = context_for_learn(x, case, pol, p)
    raw = synthetic_verdict(context)
    for row in raw["claim_reviews"].values():
        row["decision"] = judgment
    v = checks.Checks.model_validate(checks.normalize(raw, context))
    summary = checks.aggregate(v, context)
    assert summary["quality_gate"] == expected and summary["partial_parts"] == 3
    assert not summary["full_answer_credit"] and summary["scientific_quality"] == "UNMEASURED"


@pytest.mark.parametrize("kind", ["part", "atomicity", "qualification", "priority", "prose"])
def test_uncertainties_are_explicit_blocks_not_invented_negative_or_positive_judgments(kind):
    x, case, pol, p = learn()
    context = context_for_learn(x, case, pol, p)
    raw = synthetic_verdict(context)
    if kind == "part":
        raw["coverage_checks"]["p1"]["decision"] = "uncertain"
    elif kind == "atomicity":
        raw["claim_reviews"]["c1"]["atomicity"] = "uncertain"
    elif kind == "qualification":
        raw["claim_reviews"]["c1"]["qualifications"]["study_scope"] = "uncertain"
    elif kind == "priority":
        raw["priority_review"] = "uncertain"
    else:
        raw["prose_uncertainties"][next(iter(raw["prose_uncertainties"]))] = [
            "Synthetic unresolved premise, not an established factual error."
        ]
    v = checks.Checks.model_validate(checks.normalize(raw, context))
    assert checks.aggregate(v, context)["quality_gate"] == "HOLD"
    raw["claim_reviews"]["c1"]["decision"] = "unsupported"
    v = checks.Checks.model_validate(checks.normalize(raw, context))
    assert checks.aggregate(v, context)["quality_gate"] == "FAIL"


def test_required_locations_support_multiple_independent_findings_without_global_flag():
    x, case, pol, p = learn()
    context = context_for_learn(x, case, pol, p)
    raw = synthetic_verdict(context)
    key = next(iter(raw["prose_findings"]))
    raw["prose_findings"][key] = [
        "Synthetic unsupported premise A.",
        "Synthetic independent unsupported premise B.",
    ]
    raw["coverage_checks"]["p1"]["critiques"] = [
        "Synthetic missing method.",
        "Synthetic missing protocol.",
    ]
    v = checks.Checks.model_validate(checks.normalize(raw, context))
    assert len(v.prose_findings) == 2 and len(v.coverage_critiques) == 2
    assert checks.compact(v.model_dump(mode="json"), context) == raw
    assert checks.aggregate(v, context)["factual_prose_findings"] == 2
    altered = v.model_dump(mode="json")
    altered["prose_review"] = "procedural_only"
    with pytest.raises(ValueError, match="derived_prose_state_mismatch"):
        checks.Checks.model_validate(altered)
    altered = v.model_dump(mode="json")
    altered["coverage_critiques"][0]["input_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="coverage_critique_binding_mismatch"):
        checks.Checks.model_validate(altered)
    altered = v.model_dump(mode="json")
    altered["checks"][0]["input_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="claim_quality_binding_mismatch"):
        checks.Checks.model_validate(altered)


def test_partial_roundtrip_refuses_silent_gap_loss_and_renumbering():
    x, case, pol, p = learn()
    e, c = codec.normalize(x, list(case["units"]), case["purpose"], pol)
    for field in ["summary", "extra", "part", "reference", "claim_order"]:
        a, b = deepcopy(e), deepcopy(c)
        if field == "summary":
            b["p1"]["gap"] = "none"
        elif field == "extra":
            b["p1"]["new_field"] = "not_allowed"
        elif field == "part":
            b.pop("p3")
        elif field == "reference":
            b["p1"]["context_claim_ids"] = ["c1"]
        else:
            a["response"]["claims"].reverse()
        with pytest.raises(ValueError):
            codec.wire_payload(a, b, pol)
    # No mutation of original or synthetic input while rejecting derivatives.
    assert codec.wire_payload(e, c, pol) == x


def test_missing_current_bindings_and_unselected_or_wrong_version_evidence_remain_rejected():
    x, case, pol, p = learn()
    context = context_for_learn(x, case, pol, p)
    normalized = checks.normalize(synthetic_verdict(context), context)
    stale = deepcopy(context)
    stale["coverage_inputs"][0]["input_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="coverage_review_binding_mismatch"):
        checks.aggregate(checks.Checks.model_validate(normalized), stale)
    for mutation in ["unknown_handle", "wrong_version", "changed_quote", "wrong_offset"]:
        catalog = {k: EvidenceRef(**v) for k, v in case["units"].items()}
        data = deepcopy(x)
        key = data["response"]["claims"][0]["handles"][0]
        if mutation == "unknown_handle":
            data["response"]["claims"][0]["handles"] = ["unselected"]
        else:
            from dataclasses import asdict

            row = asdict(catalog[key])
            if mutation == "wrong_version":
                row["version_id"] = "arxiv:2210.03629:v999"
            elif mutation == "changed_quote":
                row["quote"] = "A fabricated quotation."
            else:
                row["start"] += 1
            catalog[key] = EvidenceRef(**row)
        with pytest.raises(ValueError):
            codec.resolve_draft(
                data, catalog, oldspec.materials(p), purpose=case["purpose"], policy=pol
            )
