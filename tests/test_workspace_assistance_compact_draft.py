"""Offline synthetic v14 controls; no provider acceptance or factual labels."""

import json
from copy import deepcopy

import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from src.workspace import assistance_compact_draft as compact
from src.workspace.assistance_contract import resolve_draft, schemas
from src.workspace.assistance_coverage import AUTHORITATIVE_COVERAGE_REVISION, decorate_fixture
from src.workspace.grounding import EvidenceRef
from src.workspace.material import SourceMaterial, SourceSpan
from tests.test_workspace_coverage_authority import ARCHIVED, synthetic
from tests.test_workspace_coverage_shapes import shaped
from tests.test_workspace_task_policy import ARCHIVE, NORMAL, RETRIEVAL, SAFETY, response

pytestmark = pytest.mark.unit


def control(case=NORMAL):
    source = ARCHIVE["cases"][case]
    policy = shaped(case)
    policy["revision"] = AUTHORITATIVE_COVERAGE_REVISION
    historical = decorate_fixture(response(case), policy)
    policy["revision"] = compact.REVISION
    payload = compact.fixture_payload(historical, source["purpose"], policy)
    return payload, list(source["units"]), source["purpose"], policy


def check(value, handles, purpose, policy):
    model = compact.response_model(handles, purpose, policy)
    local, wire = model.model_json_schema(), transform_schema(model)
    for schema in (local, wire):
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(value)
    model.model_validate(value)
    return compact.normalize(value, handles, purpose, policy)


def historical(value, coverage):
    result = deepcopy(value)
    result["response"]["coverage"] = deepcopy(coverage)
    if result["response"]["disposition"] == "full_abstention":
        for row in result["response"]["coverage"].values():
            row.pop("answer_claim_ids")
            row.pop("context_claim_ids")
    else:
        for row in result["response"]["coverage"].values():
            if row["status"] != "answered":
                row.pop("answer_claim_ids")
    return result


def resolve(value, handles, purpose, policy, case):
    base, coverage = check(value, handles, purpose, policy)
    catalog = {h: EvidenceRef(**r) for h, r in ARCHIVE["cases"][case]["units"].items()}
    materials = tuple(
        SourceMaterial(**{**m, "spans": tuple(SourceSpan(**s) for s in m["spans"])})
        for m in ARCHIVE["materials"]
    )
    return resolve_draft(
        historical(base, coverage),
        catalog,
        materials,
        purpose=purpose,
        revision=AUTHORITATIVE_COVERAGE_REVISION,
        task_policy=compact.legacy_policy(policy),
    )


@pytest.mark.parametrize("case,count", [(NORMAL, 6), (RETRIEVAL, 6), (SAFETY, 0)])
def test_learn_notes_and_full_use_actual_sdk_wire_and_strict_legacy(case, count):
    args = control(case)
    untouched = deepcopy(args)
    draft, claims = resolve(*args, case)
    assert args == untouched
    assert len(claims) == count
    assert bool(draft.abstention) == (case != NORMAL)
    base, rows = check(*args)
    assert list(rows) == [p["id"] for p in args[-1]["requested_parts"]]
    if case == SAFETY:
        assert (
            base["response"]["context_requests"] == response(SAFETY)["response"]["context_requests"]
        )
        assert "claims" not in base["response"]
    if case == RETRIEVAL:
        assert base["response"]["abstention"] == "comparison_evidence_required"
        assert "comparison_claims" not in base["response"]


def comparison_control():
    value, handles, purpose, policy = control(RETRIEVAL)
    body = value["response"]
    body["disposition"] = "answer"
    body["comparison_claims"] = ["c6"]
    source_claim = {}
    units = ARCHIVE["cases"][RETRIEVAL]["units"]
    for claim in body["claims"]:
        source_claim.setdefault(units[claim["handles"][0]]["work_id"], claim["claim_id"])
    body["comparison_basis"] = list(source_claim.values())
    assert len(body["comparison_basis"]) >= 2
    body["coverage"]["answered"] = [
        {
            "part_id": "p1",
            "answer_claim_ids": ["c6"],
            "context_claim_ids": [c["claim_id"] for c in body["claims"] if c["claim_id"] != "c6"],
        }
    ]
    body["coverage"]["lacks_evidence"] = []
    return value, handles, purpose, policy


def test_research_answer_retains_separate_cited_source_basis():
    args = comparison_control()
    draft, claims = resolve(*args, RETRIEVAL)
    assert draft.comparison_claims == ("c6",)
    assert len(claims) == 6
    value, handles, purpose, policy = args
    # A structurally valid two-ID basis from one source still fails provenance resolution.
    body = value["response"]
    units = ARCHIVE["cases"][RETRIEVAL]["units"]
    first_work = units[body["claims"][0]["handles"][0]]["work_id"]
    same_work = [
        c["claim_id"]
        for c in body["claims"]
        if {units[h]["work_id"] for h in c["handles"]} == {first_work}
    ]
    assert len(same_work) >= 2
    body["comparison_basis"] = same_work[:2]
    check(value, handles, purpose, policy)
    with pytest.raises(ValueError, match="comparison_requires_two_separately_cited_sources"):
        resolve(value, handles, purpose, policy, RETRIEVAL)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_group",
        "missing_part",
        "unknown_part",
        "duplicate_part",
        "overlap_part",
        "orphan",
        "unknown_ref",
        "duplicate_ref",
        "overlap_ref",
        "duplicate_claim",
        "retired_part_ids",
        "seventh_claim",
        "too_many_handles",
        "unselected_handle",
        "scope",
        "blank_claim",
        "long_claim",
        "duplicate_handle",
        "extra",
        "raw_abstention",
        "premise",
        "section_ref",
        "empty_answer",
        "wrong_gap",
        "priority",
    ],
)
def test_malformed_claim_bearing_rejected_by_both_local_entrypoints(mutation):
    value, handles, purpose, policy = control()
    body = value["response"]
    row = body["coverage"]["lacks_evidence"][0]
    if mutation == "missing_group":
        del body["coverage"]["answered"]
    elif mutation == "missing_part":
        body["coverage"]["lacks_evidence"] = []
    elif mutation == "unknown_part":
        row["part_id"] = "p8"
    elif mutation == "duplicate_part":
        body["coverage"]["lacks_evidence"].append(deepcopy(row))
    elif mutation == "overlap_part":
        body["coverage"]["omitted"].append(
            {"part_id": "p1", "gap": "claim_budget", "context_claim_ids": []}
        )
    elif mutation == "orphan":
        row["context_claim_ids"].remove("c1")
    elif mutation == "unknown_ref":
        row["context_claim_ids"] = ["c7"]
    elif mutation == "duplicate_ref":
        row["context_claim_ids"] = ["c1", "c1"]
    elif mutation == "overlap_ref":
        body["coverage"]["answered"] = [
            {
                "part_id": "p1",
                "answer_claim_ids": ["c1"],
                "context_claim_ids": row["context_claim_ids"],
            }
        ]
        body["coverage"]["lacks_evidence"] = []
    elif mutation == "duplicate_claim":
        body["claims"][1]["claim_id"] = "c1"
    elif mutation == "retired_part_ids":
        body["claims"][0]["part_ids"] = ["p1"]
    elif mutation == "seventh_claim":
        body["claims"].append(deepcopy(body["claims"][0]))
    elif mutation == "too_many_handles":
        body["claims"][0]["handles"] = (handles * 4)[:4]
    elif mutation == "unselected_handle":
        body["claims"][0]["handles"] = ["u-not-selected"]
    elif mutation == "scope":
        body["claims"][0]["required_scope"] = "metadata"
    elif mutation == "blank_claim":
        body["claims"][0]["text"] = " "
    elif mutation == "long_claim":
        body["claims"][0]["text"] = "x" * 361
    elif mutation == "duplicate_handle":
        body["claims"][0]["handles"] *= 2
    elif mutation == "extra":
        body["free_explanation"] = "unscored"
    elif mutation == "raw_abstention":
        body["abstention"] = None
    elif mutation == "premise":
        body["questions"] = [{"intent": "investigate_claim", "claim_ids": []}]
    elif mutation == "section_ref":
        body["background_claims"] = ["c7"]
    elif mutation == "empty_answer":
        body["coverage"]["answered"] = [
            {"part_id": "p1", "answer_claim_ids": [], "context_claim_ids": row["context_claim_ids"]}
        ]
        body["coverage"]["lacks_evidence"] = []
    elif mutation == "wrong_gap":
        row["gap"] = "claim_budget"
    else:
        policy["requested_parts"].append({"id": "p2", "request": "Second part", "kind": "answer"})
        body["coverage"]["omitted"] = [
            {"part_id": "p1", "gap": "claim_budget", "context_claim_ids": []}
        ]
        row["part_id"] = "p2"
    model = compact.response_model(handles, purpose, policy)
    with pytest.raises(ValueError):
        model.model_validate(value)
    with pytest.raises(ValueError):
        compact.normalize(value, handles, purpose, policy)


@pytest.mark.parametrize(
    "field",
    [
        "claims",
        "background_claims",
        "assumption_claims",
        "limitation_claims",
        "comparison_claims",
        "comparison_basis",
        "questions",
        "part_ids",
    ],
)
def test_full_abstention_wire_forbids_all_claim_and_reference_fields(field):
    value, handles, purpose, policy = control(SAFETY)
    value["response"][field] = []
    model = compact.response_model(handles, purpose, policy)
    assert list(Draft202012Validator(transform_schema(model)).iter_errors(value))
    with pytest.raises(ValueError):
        model.model_validate(value)


@pytest.mark.parametrize(
    "mutation",
    [
        "null_reason",
        "wrong_reason",
        "missing_request",
        "extra_request",
        "wrong_gap",
        "claims",
        "context_ref",
        "answer_ref",
        "answered_group",
        "omitted_group",
        "answer",
    ],
)
def test_missing_application_context_only_allows_complete_reference_free_abstention(mutation):
    value, handles, purpose, policy = control(SAFETY)
    body = value["response"]
    if mutation == "null_reason":
        body["reason"] = None
    elif mutation == "wrong_reason":
        body["reason"] = "insufficient_selected_evidence"
    elif mutation == "missing_request":
        del body["context_requests"][policy["missing_context"][0]]
    elif mutation == "extra_request":
        body["context_requests"]["extra"] = "required"
    elif mutation == "wrong_gap":
        body["coverage"]["lacks_evidence"][0]["gap"] = "source_scope"
    elif mutation == "claims":
        body["claims"] = []
    elif mutation in {"context_ref", "answer_ref"}:
        body["coverage"]["lacks_evidence"][0][
            "context_claim_ids" if mutation == "context_ref" else "answer_claim_ids"
        ] = []
    elif mutation == "answered_group":
        body["coverage"]["answered"] = []
    elif mutation == "omitted_group":
        body["coverage"]["omitted"] = []
    else:
        body["disposition"] = "answer"
    model = compact.response_model(handles, purpose, policy)
    assert list(Draft202012Validator(transform_schema(model)).iter_errors(value))
    with pytest.raises(ValueError):
        model.model_validate(value)


@pytest.mark.parametrize("mutation", ["answered_notes", "comparison_notes", "single_basis"])
def test_comparison_notes_and_answer_basis_cannot_bypass_old_checks(mutation):
    args = comparison_control() if mutation == "single_basis" else control(RETRIEVAL)
    value, handles, purpose, policy = args
    body = value["response"]
    if mutation == "single_basis":
        body["comparison_basis"] = body["comparison_basis"][:1]
    elif mutation == "comparison_notes":
        body["comparison_claims"] = ["c1"]
        body["comparison_basis"] = ["c1", "c2"]
    else:
        row = body["coverage"]["lacks_evidence"].pop()
        body["coverage"]["answered"] = [
            {"part_id": "p1", "answer_claim_ids": row["context_claim_ids"], "context_claim_ids": []}
        ]
    with pytest.raises(ValueError):
        compact.response_model(handles, purpose, policy).model_validate(value)


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def test_wire_has_one_union_and_shared_claim_evidence_and_id_definitions():
    for case in (NORMAL, RETRIEVAL):
        _, handles, purpose, policy = control(case)
        wire = transform_schema(compact.response_model(handles, purpose, policy))
        nodes = [n for n in walk(wire) if isinstance(n, dict)]
        assert sum("anyOf" in n for n in nodes) == 1
        assert len(wire["properties"]["response"]["anyOf"]) == 2
        definitions = list(wire["$defs"].values())
        assert sum("claim_id" in d.get("properties", {}) for d in definitions) == 1
        assert sum(n.get("enum") == ["c1", "c2", "c3", "c4", "c5", "c6"] for n in nodes) == 1
        assert sum(n.get("enum") == sorted(handles) for n in nodes) == 1
        properties = next(
            d["properties"] for d in definitions if "claims" in d.get("properties", {})
        )
        assert ("comparison_basis" in properties) == (case == RETRIEVAL)
        assert "maxItems" not in properties["claims"]
        assert "maxItems: 6" in properties["claims"]["description"]
        claim = next(d for d in definitions if "claim_id" in d.get("properties", {}))
        assert "maxLength" not in claim["properties"]["text"]
        assert "maxLength: 360" in claim["properties"]["text"]["description"]
        assert all(
            n.get("additionalProperties") is False for n in nodes if n.get("type") == "object"
        )


def test_byte_budget_and_canonical_handle_order_are_local():
    value, handles, purpose, policy = control()
    assert (
        compact.response_model(handles, purpose, policy).model_json_schema()
        == compact.response_model(list(reversed(handles)), purpose, policy).model_json_schema()
    )
    # UTF-8 bytes, rather than Unicode character count, govern the whole JSON cap.
    value["response"]["claims"][0]["text"] = "é" * 360
    value["response"]["claims"][1]["text"] = "é" * 360
    body = json.dumps(value, ensure_ascii=False)
    assert len(body.encode()) < 8000
    for claim in value["response"]["claims"]:
        claim["text"] = "🚀" * 360
    assert len(json.dumps(value, ensure_ascii=False).encode()) > 8000
    with pytest.raises(ValueError, match="too_large"):
        compact.normalize(value, handles, purpose, policy)
    with pytest.raises(ValueError, match="too_large"):
        compact.response_model(handles, purpose, policy).model_validate(value)


def test_archived_rejection_preserved_and_v10_export_remains_byte_identical():
    frozen = deepcopy(ARCHIVED)
    old = ARCHIVED["sealed"]
    old_schema = schemas(
        list(old["units"]),
        purpose=old["response_purpose"],
        revision=old["schema_revision"],
        task_policy=old["task_policy"],
    )
    assert old_schema["wire"] == ARCHIVED["transmitted_body"]["output_config"]["format"]["schema"]
    policy = deepcopy(old["task_policy"])
    policy["revision"] = compact.REVISION
    original = json.loads(ARCHIVED["text"])
    converted_rejection = compact.fixture_payload(original, old["response_purpose"], policy)
    with pytest.raises(ValueError):
        compact.normalize(converted_rejection, list(old["units"]), old["response_purpose"], policy)
    successor = compact.fixture_payload(synthetic(), old["response_purpose"], policy)
    check(successor, list(old["units"]), old["response_purpose"], policy)
    assert frozen == ARCHIVED and ARCHIVED["accepted"] is False
    assert (
        schemas(
            list(old["units"]),
            purpose=old["response_purpose"],
            revision=old["schema_revision"],
            task_policy=old["task_policy"],
        )
        == old_schema
    )


def test_invalid_or_mutated_sealed_policy_cannot_compile():
    _, handles, purpose, policy = control()
    for key, changed in [
        ("revision", AUTHORITATIVE_COVERAGE_REVISION),
        ("allowed_dispositions", ["answer"]),
        ("missing_context", ["vehicle_configuration"]),
    ]:
        bad = {**policy, key: changed}
        with pytest.raises(ValueError):
            compact.response_model(handles, purpose, bad)
    with pytest.raises(ValueError):
        compact.response_model([], purpose, policy)
    with pytest.raises(ValueError):
        compact.response_model(handles, "unsupported", policy)


def test_full_abstention_without_missing_context_has_no_reference_fields():
    _, handles, purpose, policy = control()
    value = {
        "response": {
            "disposition": "full_abstention",
            "reason": "insufficient_selected_evidence",
            "next_action": "request_context",
            "coverage": {
                "lacks_evidence": [{"part_id": "p1", "gap": "source_scope"}],
                "omitted": [],
            },
        }
    }
    check(value, handles, purpose, policy)
    value["response"]["coverage"]["lacks_evidence"][0]["context_claim_ids"] = []
    wire = transform_schema(compact.response_model(handles, purpose, policy))
    assert list(Draft202012Validator(wire).iter_errors(value))
    with pytest.raises(ValueError):
        compact.normalize(value, handles, purpose, policy)


def test_all_eight_parts_partition_locally_and_model_owns_policy():
    value, handles, purpose, policy = control()
    policy["requested_parts"] = [
        {"id": f"p{i}", "request": f"Part {i}", "kind": "answer"} for i in range(1, 9)
    ]
    value["response"]["coverage"]["omitted"] = [
        {"part_id": f"p{i}", "gap": "claim_budget", "context_claim_ids": []} for i in range(2, 9)
    ]
    _, rows = check(value, handles, purpose, policy)
    assert list(rows) == [f"p{i}" for i in range(1, 9)]
    model = compact.response_model(handles, purpose, policy)
    schema_before = model.model_json_schema()
    policy["allowed_dispositions"] = []
    policy["requested_parts"] = []
    model.model_validate(value)
    assert model.model_json_schema() == schema_before
    del value["response"]["coverage"]["omitted"][0]
    with pytest.raises(ValueError, match="exact_sealed_part_coverage_required"):
        model.model_validate(value)


def test_learn_cannot_add_comparison_structure_and_notes_disposition():
    value, handles, purpose, policy = control()
    for field, extra in [
        ("comparison_claims", []),
        ("comparison_basis", []),
        ("disposition", "comparison_abstention"),
    ]:
        bad = deepcopy(value)
        bad["response"][field] = extra
        with pytest.raises(ValueError):
            compact.response_model(handles, purpose, policy).model_validate(bad)


def test_valid_wire_is_insufficient_for_exact_partition_and_reference_semantics():
    value, handles, purpose, policy = control()
    # The SDK schema cannot express these cross-row/reference invariants.
    model = compact.response_model(handles, purpose, policy)
    wire = transform_schema(model)
    for mutation in ("missing", "duplicate", "orphan"):
        bad = deepcopy(value)
        rows = bad["response"]["coverage"]["lacks_evidence"]
        if mutation == "missing":
            rows.clear()
        elif mutation == "duplicate":
            rows.append(deepcopy(rows[0]))
        else:
            rows[0]["context_claim_ids"].remove("c1")
        Draft202012Validator(wire).validate(bad)
        with pytest.raises(ValueError):
            model.model_validate(bad)


def test_fixture_conversion_cannot_drop_unknown_parts_or_repair_wrong_reason():
    _, _, purpose, policy = control()
    old_policy = compact.legacy_policy(policy)
    value = decorate_fixture(response(NORMAL), old_policy)
    unknown = deepcopy(value)
    unknown["response"]["coverage"]["p8"] = deepcopy(unknown["response"]["coverage"]["p1"])
    with pytest.raises(ValueError, match="exact_sealed_part_coverage_required"):
        compact.fixture_payload(unknown, purpose, policy)
    value["response"]["abstention"] = "application_context_required"
    with pytest.raises(ValueError, match="fixture_abstention_disposition_mismatch"):
        compact.fixture_payload(value, purpose, policy)


@pytest.mark.parametrize(
    "mutation",
    [
        "answered_gap",
        "answered_extra",
        "evidence_answer_refs",
        "evidence_wrong_gap",
        "omission_wrong_gap",
        "duplicate_refs",
        "missing_abstention",
    ],
)
def test_fixture_conversion_validates_source_fields_before_discard(mutation):
    _, _, purpose, policy = control()
    value = decorate_fixture(response(NORMAL), compact.legacy_policy(policy))
    row = value["response"]["coverage"]["p1"]
    if mutation in {"answered_gap", "answered_extra"}:
        row.update(
            status="answered",
            gap="source_scope" if mutation == "answered_gap" else "none",
            answer_claim_ids=row["context_claim_ids"],
            context_claim_ids=[],
        )
        if mutation == "answered_extra":
            row["source_reason"] = "must not disappear"
    elif mutation == "evidence_answer_refs":
        row["answer_claim_ids"] = []
    elif mutation == "evidence_wrong_gap":
        row["gap"] = "none"
    elif mutation == "omission_wrong_gap":
        row["status"] = "omitted"
    elif mutation == "duplicate_refs":
        row["context_claim_ids"] = ["c1", "c1"]
    else:
        del value["response"]["abstention"]
    original = deepcopy(value)
    with pytest.raises(ValueError):
        compact.fixture_payload(value, purpose, policy)
    assert value == original
