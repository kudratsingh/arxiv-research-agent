"""Prospective offline capacity contracts never establish provider acceptance."""

import hashlib
import json
from copy import deepcopy

import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from src.workspace import assistance_capacity_contract as capacity
from src.workspace.assistance_coverage import QUALIFICATIONS, review_failed, validate_review
from src.workspace.assistance_policy import CoverageTaskContext
from src.workspace.d5_capacity_policy import (
    MAX_COMPACT_CHECK_BYTES,
    MAX_DRAFT_BYTES,
    MAX_NORMALIZED_CHECK_BYTES,
    observations,
)

pytestmark = pytest.mark.unit


def policy(mode="research", *, parts=8, intent="answer", sources=2):
    return capacity.seal_policy(
        CoverageTaskContext.model_validate(
            {
                "intent": intent,
                "requested_parts": [
                    {
                        "id": f"p{i}",
                        "request": f"Question {i}",
                        "kind": "comparison" if intent == "comparison" else "answer",
                    }
                    for i in range(1, parts + 1)
                ],
            }
        ),
        mode,
        sources,
        "Question",
    )


def fixture(
    mode="research",
    *,
    count=None,
    parts=8,
    text="An atomic result with every reported qualification.",
):
    count = count or (12 if mode == "research" else 8)
    pol = policy(mode, parts=parts, sources=2 if mode == "research" else 1)
    value = {
        "response": {
            "disposition": "answer",
            "claims": [
                {"claim_id": f"c{i}", "text": text, "handles": ["u1"], "required_scope": "abstract"}
                for i in range(1, count + 1)
            ],
            "background_claims": ["c1"],
            "assumption_claims": [],
            "limitation_claims": [],
            "gaps": ["source_scope"],
            "questions": [{"intent": "investigate_claim", "claim_ids": [f"c{count}"]}],
            "proposal": "inspect_scope",
            "coverage": {
                "answered": [
                    {
                        "part_id": f"p{i}",
                        "answer_claim_ids": [f"c{j}" for j in range(1, count + 1)]
                        if i == 1
                        else ["c1"],
                        "context_claim_ids": [],
                    }
                    for i in range(1, parts + 1)
                ],
                "lacks_evidence": [],
                "omitted": [],
            },
        }
    }
    return value, ["u1"], "single_paper", pol


def raw_checks(
    *, count=12, parts=8, reason="Reported scope and limitations remain material.", negative=False
):
    return {
        "revision": capacity.CHECKS_REVISION,
        "claim_reviews": [
            {
                "claim_id": f"c{i}",
                "input_digest": "sha256:" + format(i, "x") * 64,
                "decision": "abstain" if negative else "supported",
                "atomicity": "uncertain" if negative else "atomic",
                "qualifications": dict.fromkeys(
                    QUALIFICATIONS, "uncertain" if negative else "retained"
                ),
                "reason": reason,
            }
            for i in range(1, count + 1)
        ],
        "coverage_checks": [
            {
                "part_id": f"p{i}",
                "input_digest": "sha256:" + format(i, "x") * 64,
                "decision": "uncertain" if negative else "answered",
                "reason": reason,
            }
            for i in range(1, parts + 1)
        ],
        "prose_review": "unscored_factual_content" if negative else "procedural_only",
        "prose_findings": (
            [
                {"field": f, "index": i, "reason": reason}
                for f in ("assumptions", "gaps", "questions")
                for i in range(3)
            ]
            + [
                {"field": f, "index": None, "reason": reason}
                for f in ("background", "comparison", "proposal", "abstention")
            ]
        )
        if negative
        else [],
        "priority_review": "uncertain" if negative else "respected",
    }


def test_mode_aware_maximums_and_twelve_selected_handles():
    for mode, count in (("learn", 8), ("research", 12)):
        args = fixture(mode)
        before = deepcopy(args)
        handles = [f"u{i}" for i in range(1, 13)]
        envelope, coverage = capacity.normalize(args[0], handles, args[2], args[3])
        assert len(envelope["response"]["claims"]) == count
        assert capacity.wire_payload(envelope, coverage, args[3]) == args[0]
        assert args == before
        for exported in capacity.schemas(handles, args[2], args[3]).values():
            Draft202012Validator.check_schema(exported)
            Draft202012Validator(exported).validate(args[0])
        with pytest.raises(ValueError, match="selected_unit_limit"):
            capacity.normalize(args[0], [f"u{i}" for i in range(13)], args[2], args[3])
    value, handles, purpose, pol = fixture("learn", count=9)
    with pytest.raises(ValueError):
        capacity.normalize(value, handles, purpose, pol)


@pytest.mark.parametrize("text", ["x" * 1000, "é" * 1000, "🚀" * 1000, '\\"\n' * 1000])
def test_long_complete_narrative_is_preserved_and_only_observed(text):
    args = fixture(text=text)
    result = capacity.render(*args)
    assert result["claims"][0]["text"] == text
    assert result["questions"] == [
        "What evidence supports or limits the referenced claim? Refer to cited claims c12."
    ]
    assert observations(args[0])
    assert len(json.dumps(args[0], ensure_ascii=False).encode()) < MAX_DRAFT_BYTES
    raw = raw_checks(reason=text, negative=True)
    normalized = capacity.normalize_checks(raw)
    assert normalized["checks"][0]["reason"] == text
    assert normalized["claim_quality"][0]["reason"] == text
    assert normalized["coverage_checks"][0]["reason"] == text
    assert normalized["prose_findings"][0]["reason"] == text


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_id",
        "orphan",
        "unknown_ref",
        "duplicate_ref",
        "overlap",
        "empty_answer",
        "double_part",
        "missing_part",
        "unknown_part",
        "unknown_handle",
        "duplicate_handle",
        "unknown_section",
        "unscored_premise",
        "extra_prose",
        "priority",
        "blank_claim",
        "unscored_question",
    ],
)
def test_complete_provenance_and_coverage_gates_remain_strict(mutation):
    value, handles, purpose, pol = fixture()
    r, coverage = value["response"], value["response"]["coverage"]
    if mutation == "duplicate_id":
        r["claims"][1]["claim_id"] = "c1"
    elif mutation == "orphan":
        coverage["answered"][0]["answer_claim_ids"].remove("c12")
    elif mutation == "unknown_ref":
        coverage["answered"][0]["answer_claim_ids"] = ["c13"]
    elif mutation == "duplicate_ref":
        coverage["answered"][0]["answer_claim_ids"].append("c1")
    elif mutation == "overlap":
        coverage["answered"][0]["context_claim_ids"] = ["c1"]
    elif mutation == "empty_answer":
        coverage["answered"][0]["answer_claim_ids"] = []
    elif mutation == "double_part":
        coverage["lacks_evidence"].append(
            {"part_id": "p1", "gap": "source_scope", "context_claim_ids": []}
        )
    elif mutation == "missing_part":
        coverage["answered"].pop()
    elif mutation == "unknown_part":
        coverage["answered"][0]["part_id"] = "p9"
    elif mutation == "unknown_handle":
        r["claims"][0]["handles"] = ["u99"]
    elif mutation == "duplicate_handle":
        r["claims"][0]["handles"] = ["u1", "u1"]
    elif mutation == "unknown_section":
        r["background_claims"] = ["c13"]
    elif mutation == "unscored_premise":
        r["questions"][0]["claim_ids"] = []
    elif mutation == "extra_prose":
        r["background"] = "Unscored factual assertion"
    elif mutation == "priority":
        coverage["answered"].pop(0)
        coverage["omitted"].append(
            {"part_id": "p1", "gap": "claim_budget", "context_claim_ids": []}
        )
    elif mutation == "blank_claim":
        r["claims"][0]["text"] = "   "
    else:
        r["questions"][0]["premise"] = "Unscored factual assertion"
    with pytest.raises(ValueError):
        capacity.normalize(value, handles, purpose, pol)


def test_full_abstention_retains_missing_context_and_forbids_claims():
    pol = policy(intent="application_assessment")
    value = {
        "response": {
            "disposition": "full_abstention",
            "reason": "application_context_required",
            "next_action": "request_context",
            "context_requests": {k: "required" for k in pol["missing_context"]},
            "coverage": {
                "lacks_evidence": [
                    {"part_id": p["id"], "gap": "application_context"}
                    for p in pol["requested_parts"]
                ]
            },
        }
    }
    result = capacity.render(value, ["u1"], "single_paper", pol)
    assert result["claims"] == [] and result["claim_request_index"] == {}
    assert len(result["context_requests"]) == 4
    for field in ("claims", "background_claims", "abstention"):
        bad = deepcopy(value)
        bad["response"][field] = []
        with pytest.raises(ValueError):
            capacity.normalize(bad, ["u1"], "single_paper", pol)


def test_comparison_source_notes_cannot_answer_or_presuppose_comparison():
    value, handles, purpose, _ = fixture(parts=1)
    pol = policy(parts=1, intent="comparison")
    r = value["response"]
    r.update(disposition="comparison_abstention", comparison_claims=[], comparison_basis=[])
    r["coverage"] = {
        "answered": [],
        "lacks_evidence": [
            {
                "part_id": "p1",
                "gap": "common_evaluation",
                "context_claim_ids": [f"c{i}" for i in range(1, 13)],
            }
        ],
        "omitted": [],
    }
    result = capacity.render(value, handles, "research_comparison", pol)
    assert result["comparison_unanswered"]
    bad = deepcopy(value)
    bad["response"]["coverage"] = {
        "answered": [
            {
                "part_id": "p1",
                "answer_claim_ids": ["c1"],
                "context_claim_ids": [f"c{i}" for i in range(2, 13)],
            }
        ],
        "lacks_evidence": [],
        "omitted": [],
    }
    with pytest.raises(ValueError, match="source_notes_cannot_answer_comparison"):
        capacity.normalize(bad, handles, "research_comparison", pol)
    bad = deepcopy(value)
    bad["response"].update(comparison_claims=["c1"], comparison_basis=["c1", "c2"])
    with pytest.raises(ValueError, match="source_notes_cannot_answer_comparison"):
        capacity.normalize(bad, handles, "research_comparison", pol)


def test_maximum_checker_rows_and_all_negative_findings_survive_losslessly():
    raw = raw_checks(reason="All scientific qualifications remain uncertain. " * 20, negative=True)
    before = deepcopy(raw)
    exported = capacity.check_schemas()
    assert exported["wire"] == transform_schema(capacity.CompactChecks)
    for schema in exported.values():
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(raw)
    normalized = capacity.normalize_checks(raw)
    assert len(normalized["checks"]) == len(normalized["claim_quality"]) == 12
    assert len(normalized["coverage_checks"]) == 8
    assert len(normalized["prose_findings"]) == 13
    assert len(json.dumps(raw).encode()) < MAX_COMPACT_CHECK_BYTES
    assert len(json.dumps(normalized).encode()) < MAX_NORMALIZED_CHECK_BYTES
    assert capacity.compact_checks_fixture(normalized) == raw == before
    checks = capacity.checks_model().model_validate(normalized)
    context = {
        "claim_inputs": [
            {k: row[k] for k in ("claim_id", "input_digest")} for row in raw["claim_reviews"]
        ],
        "coverage_inputs": [
            {k: row[k] for k in ("part_id", "input_digest")} for row in raw["coverage_checks"]
        ],
    }
    validate_review(checks, context)
    checks.validate_locations(
        {
            "background": "Text",
            "comparison": "Text",
            "proposal": "Text",
            "abstention": "Text",
            **dict.fromkeys(("assumptions", "gaps", "questions"), ["Text"] * 3),
        }
    )
    assert review_failed(
        checks, {"request_coverage": [{"id": f"p{i}", "status": "answered"} for i in range(1, 9)]}
    )
    context["claim_inputs"][0]["input_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="claim_quality_binding_mismatch"):
        validate_review(checks, context)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_claim",
        "duplicate_part",
        "missing_quality",
        "missing_part",
        "missing_reason",
        "blank_reason",
        "missing_qualification",
        "missing_atomicity",
        "invalid_location",
        "duplicate_location",
        "inconsistent_prose",
        "wrong_revision",
    ],
)
def test_checker_does_not_drop_mandatory_judgments_or_negative_findings(mutation):
    raw = raw_checks(negative=True)
    if mutation == "duplicate_claim":
        raw["claim_reviews"][1]["claim_id"] = "c1"
    elif mutation == "duplicate_part":
        raw["coverage_checks"][1]["part_id"] = "p1"
    elif mutation == "missing_quality":
        del raw["claim_reviews"]
    elif mutation == "missing_part":
        del raw["coverage_checks"]
    elif mutation == "missing_reason":
        del raw["claim_reviews"][0]["reason"]
    elif mutation == "blank_reason":
        raw["claim_reviews"][0]["reason"] = " "
    elif mutation == "missing_qualification":
        del raw["claim_reviews"][0]["qualifications"]["conditions"]
    elif mutation == "missing_atomicity":
        del raw["claim_reviews"][0]["atomicity"]
    elif mutation == "invalid_location":
        raw["prose_findings"][0]["index"] = None
    elif mutation == "duplicate_location":
        raw["prose_findings"][1] = raw["prose_findings"][0]
    elif mutation == "inconsistent_prose":
        raw["prose_review"] = "procedural_only"
    else:
        raw["revision"] = "workspace-assistance-compact-checks-v14"
    with pytest.raises(ValueError):
        capacity.normalize_checks(raw)


def test_aggregate_bounds_refuse_before_return_without_silently_shortening():
    args = fixture(text="🚀" * 4000)
    frozen = deepcopy(args)
    with pytest.raises(ValueError, match="capacity_draft_bytes_exceeded"):
        capacity.normalize(*args)
    assert args == frozen
    raw = raw_checks(reason="🚀" * 10000)
    before = deepcopy(raw)
    with pytest.raises(ValueError, match="capacity_compact_checks_bytes_exceeded"):
        capacity.normalize_checks(raw)
    assert raw == before


def test_probe_has_broad_reasons_and_same_strict_prose_locations():
    raw = raw_checks(reason="Detailed evidence qualification. " * 100)
    expanded = capacity.normalize_checks(raw)
    value = {k: expanded[k] for k in ("checks", "prose_review", "prose_findings")}
    assert len(capacity.probe_checks_model().model_validate(value).checks) == 12
    value["checks"][0]["reason"] = " "
    with pytest.raises(ValueError):
        capacity.probe_checks_model().model_validate(value)


def test_frozen_historical_wire_and_failed_rejection_remain_unchanged():
    from src.workspace.assistance_compact_draft import normalize as old_normalize
    from tests.test_workspace_assistance_compact_draft import control

    old_value, handles, purpose, old_policy = control()
    before = deepcopy((old_value, old_policy))
    old_value["response"]["claims"][0]["text"] = "Scope, comparator, metric and conditions. " * 30
    encoded = json.dumps(old_value, sort_keys=True).encode()
    frozen_digest = hashlib.sha256(encoded).hexdigest()
    with pytest.raises(ValueError):
        old_normalize(old_value, handles, purpose, old_policy)
    successor_policy = {**deepcopy(old_policy), "revision": capacity.REVISION}
    envelope, _ = capacity.normalize(old_value, handles, purpose, successor_policy)
    assert envelope["response"]["claims"][0]["text"] == old_value["response"]["claims"][0]["text"]
    assert (
        hashlib.sha256(json.dumps(old_value, sort_keys=True).encode()).hexdigest() == frozen_digest
    )
    assert old_policy == before[1]
    with pytest.raises(ValueError):
        old_normalize(old_value, handles, purpose, old_policy)


@pytest.mark.parametrize("length", [104, 110, 512, 1024])
def test_soft_reason_target_never_rejects_or_rewrites_complete_reason(length):
    reason = "é" * length
    raw = raw_checks(reason=reason)
    value = capacity.normalize_checks(raw)
    assert value["checks"][0]["reason"] == reason
    assert value["claim_quality"][0]["reason"] == reason
    assert capacity.compact_checks_fixture(value) == raw


@pytest.mark.parametrize("field", ["claim_reviews", "coverage_checks"])
def test_missing_individual_judgment_still_fails_exact_context_binding(field):
    raw = raw_checks()
    context = {
        "claim_inputs": [
            {k: row[k] for k in ("claim_id", "input_digest")} for row in raw["claim_reviews"]
        ],
        "coverage_inputs": [
            {k: row[k] for k in ("part_id", "input_digest")} for row in raw["coverage_checks"]
        ],
    }
    raw[field].pop()
    checks = capacity.checks_model().model_validate(capacity.normalize_checks(raw))
    with pytest.raises(ValueError, match="binding_mismatch"):
        validate_review(checks, context)


def test_twelve_claims_resolve_against_original_exact_material_without_legacy_caps():
    from src.workspace.grounding import EvidenceRef
    from src.workspace.material import SourceMaterial, SourceSpan
    from tests.test_workspace_task_policy import ARCHIVE, NORMAL

    selected = ARCHIVE["cases"][NORMAL]["units"]
    catalog = {h: EvidenceRef(**r) for h, r in selected.items()}
    handle = next(iter(catalog))
    materials = tuple(
        SourceMaterial(**{**m, "spans": tuple(SourceSpan(**s) for s in m["spans"])})
        for m in ARCHIVE["materials"]
    )
    value, _, purpose, pol = fixture(text="Detailed qualified atomic claim. " * 30)
    for row in value["response"]["claims"]:
        row["handles"] = [handle]
    draft, claims = capacity.resolve_draft(value, catalog, materials, purpose=purpose, policy=pol)
    assert len(draft.claims) == len(claims) == 12
    assert claims[-1].text == value["response"]["claims"][-1]["text"]
    assert claims[-1].evidence == (catalog[handle],)
    from dataclasses import replace

    corrupt = {**catalog, handle: replace(catalog[handle], quote="Altered quotation")}
    with pytest.raises(ValueError):
        capacity.resolve_draft(value, corrupt, materials, purpose=purpose, policy=pol)


def test_comparison_basis_requires_two_independently_cited_works():
    from src.workspace.grounding import EvidenceRef
    from src.workspace.material import SourceMaterial, SourceSpan
    from tests.test_workspace_task_policy import ARCHIVE, RETRIEVAL

    selected = ARCHIVE["cases"][RETRIEVAL]["units"]
    catalog = {h: EvidenceRef(**r) for h, r in selected.items()}
    materials = tuple(
        SourceMaterial(**{**m, "spans": tuple(SourceSpan(**s) for s in m["spans"])})
        for m in ARCHIVE["materials"]
    )
    value, _, _, _ = fixture(parts=1)
    pol = policy(parts=1, intent="comparison")
    r = value["response"]
    r.update(comparison_claims=["c1"], comparison_basis=["c1", "c2"])
    r["coverage"]["answered"][0].update(
        answer_claim_ids=["c1"], context_claim_ids=[f"c{i}" for i in range(2, 13)]
    )
    first = next(iter(catalog))
    second = next(h for h, ref in catalog.items() if ref.work_id != catalog[first].work_id)
    for row in r["claims"]:
        row["handles"] = [first]
    with pytest.raises(ValueError, match="comparison_requires_two_separately_cited_sources"):
        capacity.resolve_draft(value, catalog, materials, purpose="research_comparison", policy=pol)
    r["claims"][1]["handles"] = [second]
    assert (
        len(
            capacity.resolve_draft(
                value, catalog, materials, purpose="research_comparison", policy=pol
            )[1]
        )
        == 12
    )


@pytest.mark.parametrize("change", ["hidden_answer", "bad_gap", "unknown", "duplicate"])
def test_synthetic_wire_conversion_never_silently_discards_bad_coverage(change):
    value, handles, purpose, pol = fixture()
    envelope, coverage = capacity.normalize(value, handles, purpose, pol)
    row = coverage["p1"]
    if change == "hidden_answer":
        row.update(status="lacks_evidence", gap="source_scope")
    elif change == "bad_gap":
        row["gap"] = "protocol"
    elif change == "unknown":
        row["unscored"] = "Ignored assertion"
    else:
        row["context_claim_ids"] = ["c1"]
    with pytest.raises(ValueError):
        capacity.wire_payload(envelope, coverage, pol)


def test_model_captures_owned_policy_and_selected_handles_in_canonical_order():
    value, handles, purpose, pol = fixture()
    first = capacity.response_model([*handles, "u2"], purpose, pol)
    second = capacity.response_model(["u2", *handles], purpose, pol)
    assert first.model_json_schema() == second.model_json_schema()
    before = deepcopy(value)
    pol["requested_parts"] = []
    handles.clear()
    first.model_validate(value)
    assert value == before
