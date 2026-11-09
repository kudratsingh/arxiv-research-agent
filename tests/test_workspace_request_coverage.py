"""Prospective coverage contracts. All semantic labels here are synthetic controls."""

from copy import deepcopy

import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from src.workspace.assistance import CoverageChecks
from src.workspace.assistance_contract import schemas
from src.workspace.assistance_coverage import (
    COVERAGE_REVISION,
    QUALIFICATIONS,
    CoverageRecord,
    RequestedPart,
    decorate_fixture,
    fixture_checks,
    normalize,
    prior_policy,
    render,
    review_context,
    review_failed,
    seal_coverage_policy,
    validate_review,
)
from src.workspace.assistance_policy import CoverageTaskContext
from tests.test_workspace_task_policy import ARCHIVE, NORMAL, RETRIEVAL, SAFETY, response

pytestmark = pytest.mark.unit


def policy(case=NORMAL, parts=()):
    value = ARCHIVE["cases"][case]
    return seal_coverage_policy(
        CoverageTaskContext(
            intent="application_assessment"
            if case == SAFETY
            else "comparison"
            if case == RETRIEVAL
            else "answer",
            requested_parts=parts,
        ),
        value["mode"],
        len({r["work_id"] for r in value["units"].values()}),
        value["question"],
    )


def payload(case=NORMAL, selected=None):
    return decorate_fixture(response(case), selected or policy(case))


def validate(case, value, pol=None):
    pol = pol or policy(case)
    c = ARCHIVE["cases"][case]
    exported = schemas(
        list(c["units"]), purpose=c["purpose"], revision=COVERAGE_REVISION, task_policy=pol
    )
    for schema in exported.values():
        if isinstance(schema, dict):
            Draft202012Validator(schema).validate(value)
    return normalize(value, list(c["units"]), c["purpose"], pol)


@pytest.mark.parametrize("case", [NORMAL, RETRIEVAL, SAFETY])
def test_wire_local_and_rendered_coverage(case):
    pol, value = policy(case), payload(case)
    validate(case, value, pol)
    c = ARCHIVE["cases"][case]
    result = render(value, list(c["units"]), c["purpose"], pol)
    assert result["coverage_complete"] is False
    assert result["request_coverage"][0]["request"] == c["question"]
    if case == SAFETY:
        assert result["claims"] == []
        assert result["request_coverage"][0]["gap"] == "application_context"
    if case == RETRIEVAL:
        assert result["comparison_unanswered"]
        assert result["request_coverage"][0]["answer_claim_ids"] == []
    assert schemas(
        list(reversed(c["units"])),
        purpose=c["purpose"],
        revision=COVERAGE_REVISION,
        task_policy=pol,
    ) == schemas(
        list(c["units"]), purpose=c["purpose"], revision=COVERAGE_REVISION, task_policy=pol
    )


def test_answered_and_multiple_parts_are_reciprocal_and_priority_ordered():
    parts = (
        RequestedPart(id="p1", request="Which metric and conditions?"),
        RequestedPart(id="p2", request="Secondary context"),
    )
    pol, value = policy(parts=parts), payload(selected=policy(parts=parts))
    row = value["response"]["coverage"]["p1"]
    row.update(
        status="answered",
        gap="none",
        answer_claim_ids=row.pop("context_claim_ids"),
        context_claim_ids=[],
    )
    validate(NORMAL, value, pol)
    value["response"]["coverage"]["p2"] = dict(
        status="omitted", gap="claim_budget", answer_claim_ids=[], context_claim_ids=[]
    )
    validate(NORMAL, value, pol)
    value["response"]["coverage"]["p1"], value["response"]["coverage"]["p2"] = (
        value["response"]["coverage"]["p2"],
        value["response"]["coverage"]["p1"],
    )
    for claim in value["response"]["claims"]:
        claim["part_ids"] = ["p2"]
    with pytest.raises(ValueError, match="prioritize"):
        normalize(value, list(ARCHIVE["cases"][NORMAL]["units"]), "single_paper", pol)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "unknown", "orphan", "reciprocal", "duplicate_part", "bad_ref", "seventh"],
)
def test_missing_unknown_and_stale_references_refused(mutation):
    v = payload()
    body = v["response"]
    if mutation == "missing":
        body["coverage"] = {}
    elif mutation == "unknown":
        body["coverage"]["p8"] = deepcopy(body["coverage"]["p1"])
    elif mutation == "orphan":
        body["coverage"]["p1"]["context_claim_ids"] = []
    elif mutation == "reciprocal":
        body["claims"][0]["part_ids"] = ["p2"]
    elif mutation == "duplicate_part":
        body["claims"][0]["part_ids"] = ["p1", "p1"]
    elif mutation == "bad_ref":
        body["coverage"]["p1"]["context_claim_ids"] = ["c6"]
    else:
        body["claims"].append(deepcopy(body["claims"][0]))
    with pytest.raises(ValueError):
        normalize(v, list(ARCHIVE["cases"][NORMAL]["units"]), "single_paper", policy())


def test_source_notes_cannot_be_relabelled_answered_comparison():
    v = payload(RETRIEVAL)
    row = v["response"]["coverage"]["p1"]
    row.update(
        status="answered",
        gap="none",
        answer_claim_ids=row["context_claim_ids"],
        context_claim_ids=[],
    )
    with pytest.raises(ValueError, match="source_notes"):
        normalize(
            v, list(ARCHIVE["cases"][RETRIEVAL]["units"]), "research_comparison", policy(RETRIEVAL)
        )


@pytest.mark.parametrize(
    "row",
    [
        dict(status="answered", gap="none", answer_claim_ids=[], context_claim_ids=[]),
        dict(status="omitted", gap="methods", answer_claim_ids=[], context_claim_ids=[]),
        dict(
            status="lacks_evidence", gap="claim_budget", answer_claim_ids=[], context_claim_ids=[]
        ),
        dict(
            status="lacks_evidence",
            gap="methods",
            answer_claim_ids=[],
            context_claim_ids=["c1", "c1"],
        ),
    ],
)
def test_gap_dispositions_cannot_hide_omissions(row):
    with pytest.raises(ValueError):
        CoverageRecord(**row)


def test_requested_part_bounds_canonical_policy_and_nonblank():
    for parts in [
        (RequestedPart(id="p2", request="bad order"),),
        (RequestedPart(id="p1", request="a"), RequestedPart(id="p1", request="b")),
    ]:
        with pytest.raises(ValueError):
            policy(parts=parts)
    with pytest.raises(ValueError):
        RequestedPart(id="p1", request=" ")
    with pytest.raises(ValueError):
        seal_coverage_policy(CoverageTaskContext(), "learn", 1, "")
    with pytest.raises(ValueError):
        seal_coverage_policy(CoverageTaskContext(), "learn", 1, "a" * 4001)
    assert (
        len(
            seal_coverage_policy(CoverageTaskContext(), "learn", 1, "a" * 4000)["requested_parts"][
                0
            ]["request"]
        )
        == 4000
    )
    with pytest.raises(ValueError):
        policy(RETRIEVAL, (RequestedPart(id="p1", request="missing comparison"),))
    changed = policy()
    changed["revision"] = "old"
    with pytest.raises(ValueError):
        prior_policy(changed)
    changed = policy()
    changed["requested_parts"] = []
    with pytest.raises(ValueError):
        prior_policy(changed)


def context():
    pol = policy()
    result = render(payload(), list(ARCHIVE["cases"][NORMAL]["units"]), "single_paper", pol)
    claims = [{"claim_id": "c1", "input_digest": "sha256:claim"}]
    return {
        **review_context(pol, result, claims, ARCHIVE["cases"][NORMAL]["units"]),
        "claim_inputs": claims,
    }, result


def test_review_wire_bindings_and_error_directions():
    ctx, result = context()
    good = fixture_checks(dict(checks=[], prose_review="procedural_only", prose_findings=[]), ctx)
    Draft202012Validator(transform_schema(CoverageChecks)).validate(good)
    checks = CoverageChecks.model_validate(good)
    validate_review(checks, ctx)
    assert not review_failed(checks, result)
    for field in ("claim_quality", "coverage_checks"):
        for change in ("missing", "duplicate", "stale"):
            bad = deepcopy(good)
            if change == "missing":
                bad[field] = []
            elif change == "duplicate":
                bad[field] *= 2
            else:
                bad[field][0]["input_digest"] = "wrong"
            with pytest.raises(ValueError):
                validate_review(CoverageChecks.model_validate(bad), ctx)
    for dimension in QUALIFICATIONS:
        bad = deepcopy(good)
        bad["claim_quality"][0]["qualifications"][dimension] = "lost"
        assert review_failed(CoverageChecks.model_validate(bad), result)
    for mutation in ("bundled", "uncertain", "priority", "coverage"):
        bad = deepcopy(good)
        if mutation in ("bundled", "uncertain"):
            bad["claim_quality"][0]["atomicity"] = mutation
        elif mutation == "priority":
            bad["priority_review"] = "violated"
        else:
            bad["coverage_checks"][0]["decision"] = "answered"
        assert review_failed(CoverageChecks.model_validate(bad), result)
