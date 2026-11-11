"""Prospective request-part coverage and claim quality. No provider/approval I/O.

Declared coverage and machine review are separate from semantic truth and human
qualification. Historical v7 and its scorer are not rewritten.
"""

from __future__ import annotations

import json
from types import GenericAlias
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

COVERAGE_REVISION = "workspace-assistance-request-coverage-v8"
SHAPED_COVERAGE_REVISION = "workspace-assistance-coverage-shapes-v9"
AUTHORITATIVE_COVERAGE_REVISION = "workspace-assistance-coverage-authority-v10"
SHAPED_REVISIONS = frozenset({SHAPED_COVERAGE_REVISION, AUTHORITATIVE_COVERAGE_REVISION})
COVERAGE_REVISIONS = frozenset({COVERAGE_REVISION, *SHAPED_REVISIONS})
PartId = Literal["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"]
ClaimId = Literal["c1", "c2", "c3", "c4", "c5", "c6"]
Status = Literal["answered", "lacks_evidence", "omitted"]
Gap = Literal[
    "none",
    "application_context",
    "source_scope",
    "common_evaluation",
    "methods",
    "protocol",
    "data_splits",
    "metric_definition",
    "uncertainty_calibration",
    "memory_error_persistence",
    "claim_budget",
    "not_prioritized",
]
GAP_TEXT = {
    "none": "No evidence gap declared.",
    "application_context": "Provide the missing application context.",
    "source_scope": "Request the relevant source material.",
    "common_evaluation": "Request common tasks, metrics and relevance judgments before comparing.",
    "methods": "Request the missing method specification and implementation details.",
    "protocol": "Request evaluation scope, protocol and condition breakdowns.",
    "data_splits": "Request dataset access, splits and reproduction settings.",
    "metric_definition": "Request the metric definition and its denominator.",
    "uncertainty_calibration": "Request confidence calibration and coverage at abstention thresholds.",
    "memory_error_persistence": "Request direct measurements of incorrect stored information over time.",
    "claim_budget": "Not answered within the six-claim budget.",
    "not_prioritized": "Not answered in this response.",
}
QUALIFICATIONS = ("study_scope", "comparator", "metric_definition", "conditions")


class RequestedPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: PartId
    request: str = Field(min_length=1, max_length=4000)
    kind: Literal["answer", "comparison", "source_note"] = "answer"

    @model_validator(mode="after")
    def nonblank(self) -> RequestedPart:
        if not self.request.strip():
            raise ValueError("blank_requested_part")
        return self


def requested_parts(context: Any, question: str) -> tuple[list[dict[str, Any]], str]:
    values = context.requested_parts
    if not values:
        text = question.strip()
        if not text:
            raise ValueError("request_question_required")
        if len(text) > 4000:
            raise ValueError("split_request_into_bounded_parts")
        values = (
            RequestedPart(
                id="p1",
                request=text,
                kind="comparison" if context.intent == "comparison" else "answer",
            ),
        )
        basis = "Complete request recorded as one part; no automatic semantic decomposition"
    else:
        basis = "Explicit application/user parts, in priority order"
    if [p.id for p in values] != [f"p{i + 1}" for i in range(len(values))]:
        raise ValueError("requested_parts_must_have_unique_ordered_ids")
    if context.intent == "comparison" and not any(p.kind == "comparison" for p in values):
        raise ValueError("comparison_request_part_required")
    return [p.model_dump(mode="json") for p in values], basis


def seal_coverage_policy(
    context: Any, mode: str, count: int, question: str, *, revision: str = COVERAGE_REVISION
) -> dict[str, Any]:
    from src.workspace.assistance_policy import TaskContext, seal_task_policy

    old = seal_task_policy(
        TaskContext(intent=context.intent, application_context=context.application_context),
        mode,
        count,
    )
    parts, basis = requested_parts(context, question)
    if revision not in COVERAGE_REVISIONS:
        raise ValueError("coverage_revision_required")
    return {**old, "revision": revision, "requested_parts": parts, "parts_basis": basis}


def prior_policy(policy: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.assistance_policy import TASK_REVISION, validate_task_policy

    old = {k: v for k, v in policy.items() if k not in {"requested_parts", "parts_basis"}}
    old["revision"] = TASK_REVISION
    validate_task_policy(old)
    parts = tuple(RequestedPart.model_validate(p) for p in policy["requested_parts"])
    if not 1 <= len(parts) <= 8 or [p.id for p in parts] != [
        f"p{i + 1}" for i in range(len(parts))
    ]:
        raise ValueError("sealed_request_parts_invalid")
    if policy["revision"] not in COVERAGE_REVISIONS:
        raise ValueError("coverage_revision_required")
    if old["task_intent"] == "comparison" and not any(p.kind == "comparison" for p in parts):
        raise ValueError("comparison_request_part_required")
    return old


class CoverageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Status
    answer_claim_ids: tuple[ClaimId, ...] = Field(max_length=6)
    context_claim_ids: tuple[ClaimId, ...] = Field(max_length=6)
    gap: Gap

    @model_validator(mode="after")
    def disposition(self) -> CoverageRecord:
        if (self.status == "answered") != bool(self.answer_claim_ids):
            raise ValueError("answer_references_require_answered_status")
        if (self.status == "answered") != (self.gap == "none"):
            raise ValueError("coverage_gap_mismatch")
        if self.status == "omitted" and self.gap not in {"claim_budget", "not_prioritized"}:
            raise ValueError("omission_reason_required")
        if self.status == "lacks_evidence" and self.gap in {"claim_budget", "not_prioritized"}:
            raise ValueError("omission_is_not_evidence_absence")
        refs = (*self.answer_claim_ids, *self.context_claim_ids)
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate_coverage_reference")
        return self


class NoReferenceCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["lacks_evidence", "omitted"]
    gap: Gap


def response_model(handles: list[str], purpose: str, policy: dict[str, Any]) -> type[BaseModel]:
    from src.workspace.assistance_contract import digest
    from src.workspace.assistance_policy import task_response_model

    old = prior_policy(policy)
    base = task_response_model(sorted(set(handles)), purpose, old)
    identity = digest([sorted(set(handles)), purpose, policy])[7:23]
    part_type = Literal[tuple(p["id"] for p in policy["requested_parts"])]  # type: ignore[valid-type]
    annotation = base.model_fields["response"].annotation
    variants = get_args(annotation) or (annotation,)
    branches = []
    for original in variants:
        full = get_args(original.model_fields["disposition"].annotation) == ("full_abstention",)
        record: Any = NoReferenceCoverage if full else CoverageRecord
        if full and policy["missing_context"]:
            record = create_model(
                "MissingContextCoverage_" + identity,
                __base__=NoReferenceCoverage,
                status=(Literal["lacks_evidence"], ...),
                gap=(Literal["application_context"], ...),
            )
        if policy["revision"] in SHAPED_REVISIONS:
            from src.workspace.assistance_coverage_shapes import coverage_type

            record = coverage_type(full=full, missing_context=bool(policy["missing_context"]))
        coverage_fields: dict[str, Any] = {
            p["id"]: (record, ...) for p in policy["requested_parts"]
        }
        coverage = create_model(
            "Coverage_" + ("Full_" if full else "Claims_") + identity,
            __config__=ConfigDict(extra="forbid", frozen=True),
            **coverage_fields,
        )
        fields: dict[str, Any] = {
            "coverage": (
                coverage,
                Field(
                    description="Every sealed requested part exactly once. Source notes are context, not an answered comparison. No free explanatory prose."
                ),
            )
        }
        if not full:
            original_claim = get_args(original.model_fields["claims"].annotation)[0]
            claim = create_model(
                "AtomicClaim_" + identity,
                __base__=original_claim,
                part_ids=(
                    GenericAlias(tuple, (part_type, ...)),
                    Field(
                        min_length=1,
                        max_length=8,
                        description="Sealed request parts this ONE independently testable finding addresses. Retain study/task scope, comparator, metric definition and conditions in text; cite each passage separately. Never merge separate results to fit the six-claim cap.",
                    ),
                ),
            )
            if policy["revision"] == AUTHORITATIVE_COVERAGE_REVISION:
                # The base claim forbids extras, including the retired part_ids.
                claim = original_claim
            fields["claims"] = (
                GenericAlias(tuple, (claim, ...)),
                Field(min_length=1, max_length=6),
            )
        branches.append(
            create_model(
                "Covered_" + original.__name__ + "_" + identity, __base__=original, **fields
            )
        )
    from functools import reduce
    from operator import or_

    from src.workspace.assistance_coverage_shapes import ShapedEnvelope as shaped_envelope

    return create_model(
        "CoveredResponse_" + identity,
        __base__=shaped_envelope if policy["revision"] in SHAPED_REVISIONS else BaseModel,
        __config__=ConfigDict(extra="forbid", frozen=True),
        response=(
            reduce(or_, branches),
            Field(
                description="Entire response <=8000 UTF-8 bytes. Prioritize requested parts in their sealed order; explicitly record evidence gaps or budget omissions."
            ),
        ),
    )


def normalize(
    payload: dict[str, Any], handles: list[str], purpose: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 8000:
        raise ValueError("assistance_response_too_large")
    value = (
        response_model(handles, purpose, policy)
        .model_validate(payload)
        .model_dump(mode="json")["response"]
    )
    coverage = value.pop("coverage")
    full = value["disposition"] == "full_abstention"
    claims = value.get("claims", [])
    by_id = {c["claim_id"]: c for c in claims}
    authoritative = policy["revision"] == AUTHORITATIVE_COVERAGE_REVISION
    if authoritative and len(by_id) != len(claims):
        raise ValueError("duplicate_claim_id")
    referenced = set()
    for p in policy["requested_parts"]:
        row = coverage[p["id"]]
        if policy["revision"] in SHAPED_REVISIONS:
            row.setdefault("answer_claim_ids", [])
            row.setdefault("context_claim_ids", [])
        if full or policy["revision"] in SHAPED_REVISIONS:
            CoverageRecord.model_validate({"answer_claim_ids": [], "context_claim_ids": [], **row})
        for role in ("answer_claim_ids", "context_claim_ids"):
            refs = row.get(role, [])
            for claim_id in refs:
                if claim_id not in by_id or (
                    not authoritative and p["id"] not in by_id[claim_id]["part_ids"]
                ):
                    raise ValueError("request_part_claim_binding_mismatch")
            referenced.update(refs)
        if (
            p["kind"] == "comparison"
            and row["status"] == "answered"
            and (
                value["disposition"] != "answer"
                or not set(row["answer_claim_ids"]) <= set(value.get("comparison_claims", []))
            )
        ):
            raise ValueError("source_notes_cannot_answer_comparison")
    if referenced != set(by_id):
        raise ValueError("orphaned_claim_outside_request")
    for c in (() if authoritative else claims):
        if len(set(c["part_ids"])) != len(c["part_ids"]):
            raise ValueError("duplicate_claim_part")
        for part_id in c["part_ids"]:
            row = coverage[part_id]
            if c["claim_id"] not in row["answer_claim_ids"] + row["context_claim_ids"]:
                raise ValueError("claim_part_reference_missing")
        c.pop("part_ids")
    omitted = False
    for p in policy["requested_parts"]:
        row = coverage[p["id"]]
        if omitted and (row.get("answer_claim_ids") or row.get("context_claim_ids")):
            raise ValueError("prioritize_requested_parts_before_lower_priority_context")
        omitted = omitted or row["status"] == "omitted"
    return {"response": value}, coverage


def render(
    payload: dict[str, Any], handles: list[str], purpose: str, policy: dict[str, Any]
) -> dict[str, Any]:
    from src.workspace.assistance_policy import render_task_output

    base, coverage = normalize(payload, handles, purpose, policy)
    result = render_task_output(base, handles, purpose, prior_policy(policy))
    rows = [
        {**p, **coverage[p["id"]], "gap_text": GAP_TEXT[coverage[p["id"]]["gap"]]}
        for p in policy["requested_parts"]
    ]
    return {
        **result,
        "request_coverage": rows,
        "coverage_complete": all(r["status"] == "answered" for r in rows),
        "coverage_basis": "Declared coverage; machine checks are unqualified and human review is unmeasured",
        **({"claim_request_index": reverse_index(coverage)} if policy["revision"] == AUTHORITATIVE_COVERAGE_REVISION else {}),
    }


def reverse_index(coverage: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Derived roles only; associations establish neither relevance nor support."""
    result: dict[str, dict[str, list[str]]] = {}
    for part_id, row in coverage.items():
        for role in ("answer", "context"):
            for claim_id in row.get(role + "_claim_ids", []):
                result.setdefault(claim_id, {"answer": [], "context": []})[role].append(part_id)
    return {claim_id: result[claim_id] for claim_id in sorted(result)}


class Retention(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    study_scope: Literal["retained", "lost", "not_reported", "not_applicable", "uncertain"]
    comparator: Literal["retained", "lost", "not_reported", "not_applicable", "uncertain"]
    metric_definition: Literal["retained", "lost", "not_reported", "not_applicable", "uncertain"]
    conditions: Literal["retained", "lost", "not_reported", "not_applicable", "uncertain"]


class ClaimQuality(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim_id: ClaimId
    input_digest: str
    atomicity: Literal["atomic", "bundled", "uncertain"]
    qualifications: Retention
    reason: str = Field(min_length=1, max_length=240)


class PartReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    part_id: PartId
    input_digest: str
    decision: Status | Literal["uncertain"]
    reason: str = Field(min_length=1, max_length=240)


def review_context(
    policy: dict[str, Any],
    rendered: dict[str, Any],
    claim_inputs: list[dict[str, Any]],
    units: dict[str, Any],
) -> dict[str, Any]:
    from src.workspace.assistance_contract import digest

    parts = [
        {
            "part_id": p["id"],
            "input_digest": digest(
                {
                    "part": p,
                    "coverage": rendered["request_coverage"][i],
                    "claims": claim_inputs,
                    "units": units,
                }
            ),
        }
        for i, p in enumerate(policy["requested_parts"])
    ]
    return {
        "request_parts": policy["requested_parts"],
        "coverage_inputs": parts,
        "declared_coverage": rendered["request_coverage"],
        **({"claim_request_index": rendered["claim_request_index"]} if policy["revision"] == AUTHORITATIVE_COVERAGE_REVISION else {}),
        "quality_rubric": {
            "atomicity": "one independently testable finding per claim, not separate outcomes joined together",
            "qualifications": list(QUALIFICATIONS),
            "coverage": "Judge the whole requested part; context notes do not answer a comparison. Available-but-unanswered evidence is omission, not lacks_evidence.",
            "priority": "Higher-priority question parts before lower-priority context; never bundle findings to evade six claims.",
        },
    }


def validate_review(checks: Any, context: dict[str, Any]) -> None:
    expected = {c["claim_id"]: c["input_digest"] for c in context["claim_inputs"]}
    actual = {c.claim_id: c.input_digest for c in checks.claim_quality}
    if len(actual) != len(checks.claim_quality) or expected != actual:
        raise ValueError("claim_quality_binding_mismatch")
    expected_parts = {p["part_id"]: p["input_digest"] for p in context["coverage_inputs"]}
    actual_parts = {p.part_id: p.input_digest for p in checks.coverage_checks}
    if len(actual_parts) != len(checks.coverage_checks) or expected_parts != actual_parts:
        raise ValueError("coverage_review_binding_mismatch")


def review_failed(checks: Any, rendered: dict[str, Any]) -> bool:
    declared = {r["id"]: r["status"] for r in rendered["request_coverage"]}
    return (
        checks.priority_review != "respected"
        or any(
            c.atomicity != "atomic"
            or any(v in {"lost", "uncertain"} for v in c.qualifications.model_dump().values())
            for c in checks.claim_quality
        )
        or any(
            p.decision == "uncertain" or p.decision != declared[p.part_id]
            for p in checks.coverage_checks
        )
    )


def fixture_checks(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Software fixture only; never independent semantic or human evidence."""
    rows = {r["id"]: r["status"] for r in context["declared_coverage"]}
    return {
        **payload,
        "claim_quality": [
            {
                "claim_id": c["claim_id"],
                "input_digest": c["input_digest"],
                "atomicity": "atomic",
                "qualifications": dict.fromkeys(QUALIFICATIONS, "retained"),
                "reason": "Synthetic software fixture; semantic accuracy unmeasured.",
            }
            for c in context["claim_inputs"]
        ],
        "coverage_checks": [
            {
                "part_id": p["part_id"],
                "input_digest": p["input_digest"],
                "decision": rows[p["part_id"]],
                "reason": "Synthetic software fixture; coverage unmeasured.",
            }
            for p in context["coverage_inputs"]
        ],
        "priority_review": "respected",
    }


def decorate_fixture(payload: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Context-only local extractive fixture, never a qualified answer."""
    from copy import deepcopy

    value = deepcopy(payload["response"])
    full = value["disposition"] == "full_abstention"
    first = policy["requested_parts"][0]["id"]
    for claim in value.get("claims", []):
        if policy["revision"] != AUTHORITATIVE_COVERAGE_REVISION:
            claim["part_ids"] = [first]
    coverage = {}
    for part in policy["requested_parts"]:
        row: dict[str, Any] = {
            "status": "lacks_evidence",
            "gap": "application_context"
            if policy["missing_context"]
            else "common_evaluation"
            if part["kind"] == "comparison"
            else "source_scope",
        }
        if not full:
            row.update(
                answer_claim_ids=[],
                context_claim_ids=[c["claim_id"] for c in value["claims"]]
                if part["id"] == first
                else [],
            )
        if policy["revision"] in SHAPED_REVISIONS:
            row.pop("answer_claim_ids", None)
        coverage[part["id"]] = row
    value["coverage"] = coverage
    return {"response": value}
