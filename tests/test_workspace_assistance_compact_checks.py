"""Offline contract controls, never provider token/semantic qualification."""

import json
from copy import deepcopy

import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from src.workspace.assistance import CoverageChecks
from src.workspace.assistance_compact_checks import (
    COMPACT_CHECKS_REVISION,
    MAX_COMPACT_BYTES,
    MAX_REASON_BYTES,
    MAX_REASON_CHARS,
    compact_fixture,
    normalize,
    schemas,
    wire_model,
)
from src.workspace.assistance_coverage import QUALIFICATIONS, review_failed, validate_review

pytestmark = pytest.mark.unit


def fixture(*, maximum=False, reason="Selected passage retains the declared scope."):
    count, parts = (6, 8) if maximum else (1, 1)
    return {
        "revision": COMPACT_CHECKS_REVISION,
        "claim_reviews": [
            {
                "claim_id": f"c{i}",
                "input_digest": "sha256:" + str(i) * 64,
                "decision": "unsupported" if maximum else "supported",
                "atomicity": "uncertain" if maximum else "atomic",
                "qualifications": dict.fromkeys(
                    QUALIFICATIONS, "not_applicable" if maximum else "retained"
                ),
                "reason": reason,
            }
            for i in range(1, count + 1)
        ],
        "coverage_checks": [
            {
                "part_id": f"p{i}",
                "input_digest": "sha256:" + format(i, "x") * 64,
                "decision": "lacks_evidence" if maximum else "answered",
                "reason": reason,
            }
            for i in range(1, parts + 1)
        ],
        "prose_review": "unscored_factual_content" if maximum else "procedural_only",
        "prose_findings": [
            {"field": field, "index": index, "reason": reason}
            for field, index in (
                [
                    (field, index)
                    for field in ("assumptions", "gaps", "questions")
                    for index in range(3)
                ]
                + [("background", None)]
                if maximum
                else []
            )
        ],
        "priority_review": "uncertain" if maximum else "respected",
    }


def context(raw):
    return {
        "claim_inputs": [
            {key: row[key] for key in ("claim_id", "input_digest")} for row in raw["claim_reviews"]
        ],
        "coverage_inputs": [
            {key: row[key] for key in ("part_id", "input_digest")} for row in raw["coverage_checks"]
        ],
    }


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def test_exact_schema_and_normalization_are_deterministic_lossless_and_nonmutating():
    raw = fixture(maximum=True)
    original = deepcopy(raw)
    assert schemas() == {
        "local": wire_model().model_json_schema(),
        "wire": transform_schema(wire_model()),
    }
    Draft202012Validator(schemas()["wire"]).validate(raw)
    normalized = normalize(raw)
    checks = CoverageChecks.model_validate(normalized)
    validate_review(checks, context(raw))
    checks.validate_locations(
        {field: ["Nonblank"] * 3 for field in ("assumptions", "gaps", "questions")}
        | {"background": "Nonblank"}
    )
    assert len(checks.checks) == len(checks.claim_quality) == 6
    assert len(checks.coverage_checks) == 8
    assert len(checks.prose_findings) == 10
    assert compact_fixture(normalized) == raw
    assert normalize(compact_fixture(normalized)) == normalized
    assert normalize(raw) == normalized
    assert raw == original
    for support, quality, source in zip(
        checks.checks, checks.claim_quality, raw["claim_reviews"], strict=True
    ):
        assert support.claim_id == quality.claim_id == source["claim_id"]
        assert support.input_digest == quality.input_digest == source["input_digest"]
        assert support.reason == quality.reason == source["reason"]
        assert support.decision == source["decision"]
        assert quality.atomicity == source["atomicity"]
        assert quality.qualifications.model_dump() == source["qualifications"]


@pytest.mark.parametrize(
    "reason", ["x" * MAX_REASON_CHARS, "é" * 60, "😀" * 30, "x" * 72 + "\\" * 24]
)
def test_maximum_cardinality_worst_bounded_ascii_and_unicode_reasons(reason):
    raw = fixture(maximum=True, reason=reason)
    normalized = normalize(raw)
    Draft202012Validator(schemas()["wire"]).validate(raw)
    assert len(encoded(raw)) <= MAX_COMPACT_BYTES
    assert len(encoded(normalized)) <= MAX_COMPACT_BYTES
    assert len(reason.encode("utf-8")) <= MAX_REASON_BYTES
    assert len(raw["claim_reviews"]) == 6
    assert len(raw["coverage_checks"]) == 8
    assert len(raw["prose_findings"]) == 10


@pytest.mark.parametrize("decision", ["supported", "unsupported", "abstain"])
def test_every_support_verdict_survives(decision):
    raw = fixture()
    raw["claim_reviews"][0]["decision"] = decision
    assert normalize(raw)["checks"][0]["decision"] == decision


@pytest.mark.parametrize("atomicity", ["atomic", "bundled", "uncertain"])
def test_atomicity_survives_and_retains_error_direction(atomicity):
    raw = fixture()
    raw["claim_reviews"][0]["atomicity"] = atomicity
    value = CoverageChecks.model_validate(normalize(raw))
    assert value.claim_quality[0].atomicity == atomicity
    assert review_failed(value, {"request_coverage": [{"id": "p1", "status": "answered"}]}) == (
        atomicity != "atomic"
    )


@pytest.mark.parametrize("dimension", QUALIFICATIONS)
@pytest.mark.parametrize(
    "retention", ["retained", "lost", "not_reported", "not_applicable", "uncertain"]
)
def test_every_qualification_dimension_and_state_survives(dimension, retention):
    raw = fixture()
    raw["claim_reviews"][0]["qualifications"][dimension] = retention
    value = CoverageChecks.model_validate(normalize(raw))
    assert value.claim_quality[0].qualifications.model_dump()[dimension] == retention
    assert review_failed(value, {"request_coverage": [{"id": "p1", "status": "answered"}]}) == (
        retention in {"lost", "uncertain"}
    )


@pytest.mark.parametrize("decision", ["answered", "lacks_evidence", "omitted", "uncertain"])
def test_coverage_decisions_survive(decision):
    raw = fixture()
    raw["coverage_checks"][0]["decision"] = decision
    value = CoverageChecks.model_validate(normalize(raw))
    assert value.coverage_checks[0].decision == decision
    assert review_failed(value, {"request_coverage": [{"id": "p1", "status": "answered"}]}) == (
        decision != "answered"
    )


@pytest.mark.parametrize("priority", ["respected", "violated", "uncertain"])
def test_priority_states_survive(priority):
    raw = fixture()
    raw["priority_review"] = priority
    value = CoverageChecks.model_validate(normalize(raw))
    assert value.priority_review == priority
    assert review_failed(value, {"request_coverage": [{"id": "p1", "status": "answered"}]}) == (
        priority != "respected"
    )


@pytest.mark.parametrize(
    "collection,id_key,unknown",
    [("claim_reviews", "claim_id", "c2"), ("coverage_checks", "part_id", "p2")],
)
@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "stale"])
def test_missing_duplicate_unknown_and_stale_bindings_fail_existing_review(
    collection, id_key, unknown, mutation
):
    raw = fixture()
    ctx = context(raw)
    if mutation == "missing":
        raw[collection] = []
    elif mutation == "duplicate":
        raw[collection] *= 2
    elif mutation == "unknown":
        raw[collection][0][id_key] = unknown
    else:
        raw[collection][0]["input_digest"] = "sha256:" + "a" * 64
    with pytest.raises(ValueError):
        validate_review(CoverageChecks.model_validate(normalize(raw)), ctx)


@pytest.mark.parametrize(
    "field,index",
    [
        ("background", None),
        ("comparison", None),
        ("proposal", None),
        ("abstention", None),
        ("assumptions", 2),
        ("gaps", 0),
        ("questions", 1),
    ],
)
@pytest.mark.parametrize("review", ["unscored_factual_content", "abstain"])
def test_prose_states_and_all_field_index_locations_survive(field, index, review):
    raw = fixture()
    raw["prose_review"] = review
    raw["prose_findings"] = [{"field": field, "index": index, "reason": "Requires review."}]
    value = CoverageChecks.model_validate(normalize(raw))
    good = {field: "Nonblank" if index is None else ["Nonblank"] * 3}
    value.validate_locations(good)
    assert value.prose_review == review
    for prose in ({}, {field: " "}, {field: []}):
        with pytest.raises(ValueError, match="checker_prose_location_mismatch"):
            value.validate_locations(prose)


@pytest.mark.parametrize(
    "mutation",
    [
        "revision",
        "missing_dimension",
        "unknown_dimension",
        "support",
        "atomicity",
        "retention",
        "coverage",
        "priority",
        "extra",
        "claim_id",
        "part_id",
        "missing_reason",
    ],
)
def test_exact_sdk_schema_rejects_structural_negative_controls(mutation):
    raw = fixture()
    claim = raw["claim_reviews"][0]
    if mutation == "revision":
        raw["revision"] = "older"
    elif mutation == "missing_dimension":
        del claim["qualifications"]["conditions"]
    elif mutation == "unknown_dimension":
        claim["qualifications"]["new"] = "retained"
    elif mutation == "support":
        claim["decision"] = "probably"
    elif mutation == "atomicity":
        claim["atomicity"] = "joined"
    elif mutation == "retention":
        claim["qualifications"]["conditions"] = "ignored"
    elif mutation == "coverage":
        raw["coverage_checks"][0]["decision"] = "ignored"
    elif mutation == "priority":
        raw["priority_review"] = "ignored"
    elif mutation == "extra":
        claim["extra"] = "ignored"
    elif mutation == "digest":
        claim["input_digest"] = "not-a-digest"
    elif mutation == "claim_id":
        claim["claim_id"] = "c7"
    elif mutation == "part_id":
        raw["coverage_checks"][0]["part_id"] = "p9"
    else:
        del claim["reason"]
    assert list(Draft202012Validator(schemas()["wire"]).iter_errors(raw))
    with pytest.raises(ValueError):
        normalize(raw)


@pytest.mark.parametrize("collection", ["claim_reviews", "coverage_checks", "prose_findings"])
@pytest.mark.parametrize("reason", ["", " ", "x" * 97, "é" * 61, "😀" * 31, "\x00" * 21])
def test_local_reason_bounds_for_every_reason_collection(collection, reason):
    raw = fixture(maximum=True)
    raw[collection][0]["reason"] = reason
    with pytest.raises(ValueError):
        normalize(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        "scalar_index",
        "list_null",
        "negative",
        "large",
        "bool_index",
        "duplicate",
        "procedural_with_finding",
        "abstain_no_finding",
        "factual_no_finding",
    ],
)
def test_prose_error_states_fail(mutation):
    raw = fixture()
    raw["prose_review"] = "abstain"
    raw["prose_findings"] = [{"field": "gaps", "index": 0, "reason": "Review."}]
    finding = raw["prose_findings"][0]
    if mutation == "scalar_index":
        finding["field"] = "background"
    elif mutation == "list_null":
        finding["index"] = None
    elif mutation in {"negative", "large", "bool_index"}:
        finding["index"] = {"negative": -1, "large": 3, "bool_index": True}[mutation]
    elif mutation == "duplicate":
        raw["prose_findings"] *= 2
    elif mutation == "procedural_with_finding":
        raw["prose_review"] = "procedural_only"
    else:
        raw["prose_review"] = (
            "abstain" if mutation == "abstain_no_finding" else "unscored_factual_content"
        )
        raw["prose_findings"] = []
    with pytest.raises(ValueError):
        normalize(raw)


def test_transformed_schema_does_not_replace_local_cardinality_and_utf8_validation():
    validator = Draft202012Validator(schemas()["wire"])
    for collection in ("claim_reviews", "coverage_checks", "prose_findings"):
        raw = fixture(maximum=True)
        raw[collection].append(deepcopy(raw[collection][0]))
        validator.validate(raw)  # SDK strips unsupported maxItems; local remains mandatory.
        with pytest.raises(ValueError):
            normalize(raw)
    raw = fixture()
    raw["claim_reviews"][0]["input_digest"] = "not-a-digest"
    validator.validate(raw)  # SDK strips string pattern; binding remains local.
    with pytest.raises(ValueError):
        normalize(raw)
    raw = fixture(reason="😀" * 31)
    validator.validate(raw)  # UTF-8 bytes are deliberately a local constraint.
    with pytest.raises(ValueError, match="compact_reason_utf8_limit"):
        normalize(raw)


def test_empty_claim_and_coverage_collections_require_context_not_fabricated_reviews():
    raw = fixture()
    raw["claim_reviews"] = []
    raw["coverage_checks"] = []
    value = CoverageChecks.model_validate(normalize(raw))
    validate_review(value, {"claim_inputs": [], "coverage_inputs": []})
    with pytest.raises(ValueError, match="claim_quality_binding_mismatch"):
        validate_review(value, context(fixture()))


def test_fixture_inverse_refuses_information_loss_or_binding_changes():
    good = normalize(fixture())
    for mutation in ("reason", "digest", "missing"):
        bad = deepcopy(good)
        if mutation == "reason":
            bad["claim_quality"][0]["reason"] = "Distinct explanation."
        elif mutation == "digest":
            bad["claim_quality"][0]["input_digest"] = "sha256:" + "a" * 64
        else:
            bad["claim_quality"] = []
        with pytest.raises(ValueError):
            compact_fixture(bad)
