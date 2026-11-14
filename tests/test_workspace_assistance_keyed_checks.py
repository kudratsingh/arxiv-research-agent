"""Offline identity and inverse controls; no provider or semantic acceptance."""

import json
from copy import deepcopy

import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from src.workspace import assistance_capacity_contract as v15
from src.workspace import assistance_keyed_checks as keyed
from src.workspace.assistance_coverage import QUALIFICATIONS, review_failed, validate_review

pytestmark = pytest.mark.unit


def fixture(count=8, parts=8, *, probe=False):
    ids = [f"blind-{i}:opaque" if probe else f"c{i + 1}" for i in range(count)]
    context = {
        "claim_inputs": [
            {"claim_id": key, "input_digest": "sha256:" + format(i + 1, "064x"), "claim": "sealed"}
            for i, key in enumerate(ids)
        ],
        "coverage_inputs": [
            {"part_id": f"p{i + 1}", "input_digest": "sha256:" + format(i + 101, "064x")}
            for i in range(parts)
        ],
    }
    judgments = {
        key: {"decision": "supported", "reason": "Selected passage retains this finding."}
        | (
            {}
            if probe
            else {
                "atomicity": "atomic",
                "qualifications": dict.fromkeys(QUALIFICATIONS, "retained"),
            }
        )
        for key in ids
    }
    raw = {
        "revision": keyed.REVISION,
        "checks" if probe else "claim_reviews": judgments,
        "prose_review": "procedural_only",
        "prose_findings": [],
    }
    if not probe:
        raw.update(
            coverage_checks={
                row["part_id"]: {"decision": "answered", "reason": "The request is answered."}
                for row in context["coverage_inputs"]
            },
            priority_review="respected",
        )
    return raw, context


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


@pytest.mark.parametrize(
    "count,parts,probe", [(8, 8, False), (12, 8, False), (5, 0, True), (0, 8, False)]
)
def test_exact_current_key_schema_and_lossless_round_trip(count, parts, probe):
    raw, context = fixture(count, parts, probe=probe)
    before = deepcopy((raw, context))
    schemas = keyed.schemas(context, probe=probe)
    assert schemas == keyed.schemas(context, probe=probe)
    assert schemas["wire"] == transform_schema(schemas["local"])
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(raw)
        assert schema["additionalProperties"] is False
        claims = schema["$defs"][
            schema["properties"]["checks" if probe else "claim_reviews"]["$ref"].split("/")[-1]
        ]
        assert set(claims["properties"]) == set(raw["checks" if probe else "claim_reviews"])
        assert set(claims.get("required", [])) == set(claims["properties"])
        assert claims["additionalProperties"] is False
        refs = [value["$ref"] for value in claims["properties"].values()]
        assert len(set(refs)) <= 1  # One shared judgment definition for every identity.
        assert all(
            value not in encoded(schema).decode()
            for value in ("input_digest", "claim_id", "part_id")
        )
    normalized = keyed.normalize(raw, context, probe=probe)
    model = keyed.probe_checks_model() if probe else keyed.checks_model()
    checks = model.model_validate(normalized)
    if not probe:
        validate_review(checks, context)
        assert not review_failed(
            checks,
            {"request_coverage": [{"id": f"p{i + 1}", "status": "answered"} for i in range(parts)]},
        )
        assert len(checks.claim_quality) == count
    assert len(checks.checks) == count
    assert keyed.compact(normalized, context, probe=probe) == raw
    assert (
        keyed.normalize(keyed.compact(normalized, context, probe=probe), context, probe=probe)
        == normalized
    )
    assert (raw, context) == before


@pytest.mark.parametrize("probe", [False, True])
@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "unknown",
        "array",
        "model_identity",
        "model_digest",
        "missing_decision",
        "extra",
        "revision",
    ],
)
def test_exact_wire_rejects_wrong_missing_unknown_and_fabricated_judgments(probe, mutation):
    raw, context = fixture(5, probe=probe)
    collection = "checks" if probe else "claim_reviews"
    key = next(iter(raw[collection]))
    if mutation == "missing":
        del raw[collection][key]
    elif mutation == "unknown":
        raw[collection]["unknown"] = raw[collection].pop(key)
    elif mutation == "array":
        raw[collection] = list(raw[collection].values())
    elif mutation == "model_identity":
        raw[collection][key]["claim_id"] = key
    elif mutation == "model_digest":
        raw[collection][key]["input_digest"] = context["claim_inputs"][0]["input_digest"]
    elif mutation == "missing_decision":
        del raw[collection][key]["decision"]
    elif mutation == "extra":
        raw["unknown"] = True
    else:
        raw["revision"] = "old"
    for schema in keyed.schemas(context, probe=probe).values():
        assert list(Draft202012Validator(schema).iter_errors(raw))
    with pytest.raises(ValueError):
        keyed.normalize(raw, context, probe=probe)


@pytest.mark.parametrize(
    "mutation", ["missing", "unknown", "identity", "digest", "decision", "reason"]
)
def test_exact_coverage_keys_and_mandatory_decisions(mutation):
    raw, context = fixture()
    if mutation == "missing":
        del raw["coverage_checks"]["p1"]
    elif mutation == "unknown":
        raw["coverage_checks"]["p9"] = raw["coverage_checks"].pop("p1")
    elif mutation == "identity":
        raw["coverage_checks"]["p1"]["part_id"] = "p1"
    elif mutation == "digest":
        raw["coverage_checks"]["p1"]["input_digest"] = "sha256:" + "f" * 64
    else:
        del raw["coverage_checks"]["p1"][mutation]
    for schema in keyed.schemas(context).values():
        assert list(Draft202012Validator(schema).iter_errors(raw))
    with pytest.raises(ValueError):
        keyed.normalize(raw, context)


@pytest.mark.parametrize("probe", [False, True])
@pytest.mark.parametrize(
    "mutation",
    [
        "missing_claims",
        "not_list",
        "row_not_object",
        "duplicate",
        "missing_id",
        "blank_id",
        "oversized_id",
        "bad_id_type",
        "missing_digest",
        "malformed_digest",
        "digest_type",
        "upper_digest",
        "too_many",
    ],
)
def test_invalid_context_fails_before_schema_or_normalization(probe, mutation):
    raw, context = fixture(5, probe=probe)
    rows = context["claim_inputs"]
    if mutation == "missing_claims":
        del context["claim_inputs"]
    elif mutation == "not_list":
        context["claim_inputs"] = tuple(rows)
    elif mutation == "row_not_object":
        rows[0] = None
    elif mutation == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif mutation == "missing_id":
        del rows[0]["claim_id"]
    elif mutation in {"blank_id", "oversized_id", "bad_id_type"}:
        rows[0]["claim_id"] = {"blank_id": " ", "oversized_id": "x" * 121, "bad_id_type": 7}[
            mutation
        ]
    elif mutation == "missing_digest":
        del rows[0]["input_digest"]
    elif mutation in {"malformed_digest", "digest_type", "upper_digest"}:
        rows[0]["input_digest"] = {
            "malformed_digest": "bad",
            "digest_type": 7,
            "upper_digest": "sha256:" + "A" * 64,
        }[mutation]
    else:
        rows.extend(
            {"claim_id": f"extra{i}", "input_digest": "sha256:" + "a" * 64} for i in range(13)
        )
    for call in (
        lambda: keyed.schemas(context, probe=probe),
        lambda: keyed.normalize(raw, context, probe=probe),
    ):
        with pytest.raises(ValueError):
            call()


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown_id", "digest"])
def test_invalid_coverage_context_fails(mutation):
    raw, context = fixture()
    if mutation == "missing":
        del context["coverage_inputs"]
    elif mutation == "duplicate":
        context["coverage_inputs"].append(deepcopy(context["coverage_inputs"][0]))
    elif mutation == "unknown_id":
        context["coverage_inputs"][0]["part_id"] = "p9"
    else:
        context["coverage_inputs"][0]["input_digest"] = "bad"
    with pytest.raises(ValueError):
        keyed.schemas(context)
    with pytest.raises(ValueError):
        keyed.normalize(raw, context)


@pytest.mark.parametrize(
    "identifier", ["__private", "model_dump", "row_0", "opaque.with/slash:α", "c1"]
)
def test_probe_opaque_keys_are_exact_even_for_model_field_names(identifier):
    raw, context = fixture(1, 0, probe=True)
    row = raw["checks"].pop(context["claim_inputs"][0]["claim_id"])
    raw["checks"][identifier] = row
    context["claim_inputs"][0]["claim_id"] = identifier
    Draft202012Validator(keyed.schemas(context, probe=True)["wire"]).validate(raw)
    normalized = keyed.normalize(raw, context, probe=True)
    assert normalized["checks"][0]["claim_id"] == identifier
    assert keyed.compact(normalized, context, probe=True) == raw
    keyed.probe_checks_model([identifier]).model_validate(normalized)


@pytest.mark.parametrize("probe", [False, True])
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
def test_independent_prose_findings_share_location_and_keep_full_validation(probe, field, index):
    raw, context = fixture(5, probe=probe)
    raw["prose_review"] = "unscored_factual_content"
    raw["prose_findings"] = [
        {"field": field, "index": index, "reason": reason}
        for reason in ("Unsupported numerical result.", "Independent scope omission.")
    ]
    normalized = keyed.normalize(raw, context, probe=probe)
    model = keyed.probe_checks_model() if probe else keyed.checks_model()
    checks = model.model_validate(normalized)
    checks.validate_locations({field: "Nonblank" if index is None else ["Nonblank"] * 3})
    for prose in ({}, {field: " "}, {field: []}, {field: [" "] * 3}):
        with pytest.raises(ValueError, match="checker_prose_location_mismatch"):
            checks.validate_locations(prose)
    assert keyed.compact(normalized, context, probe=probe) == raw
    # The historical class retains its duplicate-location semantics.
    with pytest.raises(ValueError, match="duplicate_prose_finding"):
        (v15.probe_checks_model() if probe else v15.checks_model()).model_validate(normalized)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "scalar_index",
        "null_list_index",
        "negative_index",
        "large_index",
        "boolean_index",
        "procedural_findings",
        "missing_findings",
        "blank_reason",
        "too_many",
    ],
)
def test_prose_errors_still_rejected(mutation):
    raw, context = fixture()
    raw["prose_review"] = "abstain"
    raw["prose_findings"] = [{"field": "gaps", "index": 0, "reason": "Review material result."}]
    finding = raw["prose_findings"][0]
    if mutation == "duplicate":
        raw["prose_findings"] *= 2
    elif mutation == "scalar_index":
        finding["field"] = "background"
    elif mutation.endswith("index"):
        finding["index"] = {
            "null_list_index": None,
            "negative_index": -1,
            "large_index": 3,
            "boolean_index": True,
        }[mutation]
    elif mutation == "procedural_findings":
        raw["prose_review"] = "procedural_only"
    elif mutation == "missing_findings":
        raw["prose_findings"] = []
    elif mutation == "blank_reason":
        finding["reason"] = " "
    else:
        raw["prose_findings"] = [{**finding, "reason": str(i)} for i in range(17)]
    with pytest.raises(ValueError):
        keyed.normalize(raw, context)


@pytest.mark.parametrize("decision", ["supported", "unsupported", "abstain"])
def test_support_decisions_survive_without_inference(decision):
    raw, context = fixture()
    raw["claim_reviews"]["c1"]["decision"] = decision
    assert keyed.normalize(raw, context)["checks"][0]["decision"] == decision


@pytest.mark.parametrize("dimension", QUALIFICATIONS)
@pytest.mark.parametrize(
    "retention", ["retained", "lost", "not_reported", "not_applicable", "uncertain"]
)
def test_every_qualification_dimension_and_state_survives(dimension, retention):
    raw, context = fixture()
    raw["claim_reviews"]["c1"]["qualifications"][dimension] = retention
    assert (
        keyed.normalize(raw, context)["claim_quality"][0]["qualifications"][dimension] == retention
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "atomicity",
        "qualification",
        "missing_dimension",
        "unknown_dimension",
        "coverage",
        "priority",
        "reason",
    ],
)
def test_mandatory_semantic_fields_never_default_or_repair(mutation):
    raw, context = fixture()
    claim = raw["claim_reviews"]["c1"]
    if mutation == "atomicity":
        del claim["atomicity"]
    elif mutation == "qualification":
        claim["qualifications"]["conditions"] = "ignored"
    elif mutation == "missing_dimension":
        del claim["qualifications"]["conditions"]
    elif mutation == "unknown_dimension":
        claim["qualifications"]["extra"] = "retained"
    elif mutation == "coverage":
        raw["coverage_checks"]["p1"]["decision"] = "ignored"
    elif mutation == "priority":
        del raw["priority_review"]
    else:
        del claim["reason"]
    with pytest.raises(ValueError):
        keyed.normalize(raw, context)


@pytest.mark.parametrize("probe", [False, True])
@pytest.mark.parametrize("mutation", ["reason", "digest", "identity", "order", "extra_normalized"])
def test_inverse_refuses_lost_information_or_conflicting_bindings(probe, mutation):
    raw, context = fixture(5, probe=probe)
    normalized = keyed.normalize(raw, context, probe=probe)
    if mutation == "reason":
        if probe:
            # Probe has no shared support/quality reason and remains invertible.
            normalized["checks"][0]["reason"] = "Independent reason."
            assert (
                keyed.normalize(keyed.compact(normalized, context, probe=True), context, probe=True)
                == normalized
            )
            return
        normalized["claim_quality"][0]["reason"] = "Distinct reason must not be discarded."
    elif mutation == "digest":
        normalized["checks"][0]["input_digest"] = "sha256:" + "f" * 64
        if not probe:
            normalized["claim_quality"][0]["input_digest"] = "sha256:" + "f" * 64
    elif mutation == "identity":
        normalized["checks"][0]["claim_id"] = "unknown" if probe else "c12"
        if not probe:
            normalized["claim_quality"][0]["claim_id"] = "c12"
    elif mutation == "order":
        normalized["checks"].reverse()
        if not probe:
            normalized["claim_quality"].reverse()
    else:
        normalized["extra"] = "never discard"
    with pytest.raises(ValueError):
        keyed.compact(normalized, context, probe=probe)


def test_long_reasons_and_original_context_digests_are_preserved():
    raw, context = fixture(12)
    reason = "Independent material evidence α😀. " * 50
    raw["claim_reviews"]["c12"]["reason"] = reason
    normalized = keyed.normalize(raw, context)
    assert normalized["checks"][11]["reason"] == reason
    assert [row["input_digest"] for row in normalized["checks"]] == [
        row["input_digest"] for row in context["claim_inputs"]
    ]
    assert keyed.compact(normalized, context) == raw


def test_context_not_model_supplies_each_current_digest():
    raw, context = fixture()
    first = keyed.normalize(raw, context)
    context["claim_inputs"][0]["input_digest"] = "sha256:" + "e" * 64
    context["coverage_inputs"][0]["input_digest"] = "sha256:" + "f" * 64
    second = keyed.normalize(raw, context)
    assert second["checks"][0]["input_digest"] != first["checks"][0]["input_digest"]
    assert (
        second["coverage_checks"][0]["input_digest"] != first["coverage_checks"][0]["input_digest"]
    )
    with pytest.raises(ValueError):
        keyed.compact(first, context)


def test_storage_bounds_are_still_local_and_probe_excludes_quality_coverage():
    raw, context = fixture(1)
    raw["claim_reviews"]["c1"]["reason"] = "x" * 262144
    with pytest.raises(ValueError, match="capacity_compact_checks_bytes_exceeded"):
        keyed.normalize(raw, context)
    raw, context = fixture(5, probe=True)
    raw["priority_review"] = "respected"
    with pytest.raises(ValueError):
        keyed.normalize(raw, context, probe=True)


@pytest.mark.parametrize("collection", ["checks", "claim_quality", "coverage_checks"])
def test_normalized_models_reject_duplicate_reviews(collection):
    raw, context = fixture()
    normalized = keyed.normalize(raw, context)
    normalized[collection] = normalized[collection][:2]
    normalized[collection][1] = deepcopy(normalized[collection][0])
    with pytest.raises(ValueError):
        keyed.checks_model().model_validate(normalized)


def test_probe_identity_factory_and_context_require_valid_inputs():
    for identifiers in ([], ["same", "same"], [" "], ["x" * 121]):
        with pytest.raises(ValueError):
            keyed.probe_checks_model(identifiers)
    with pytest.raises(ValueError, match="keyed_context_invalid"):
        keyed.schemas(None)
