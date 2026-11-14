"""Prospective v15 complete response contracts; pure offline transformations.

No archived response is migrated or accepted here. Callers must retain the raw
response, require the original complete provider stop, and independently bind
all judgments to the exact current response and selected evidence. Successful
validation establishes a response contract, never scientific or human quality.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from enum import StrEnum
from functools import lru_cache
from types import GenericAlias
from typing import Any, Literal, cast

from anthropic import transform_schema
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from src.workspace.assistance_contract import (
    ABSTENTION_INTENTS,
    ACTION_INTENTS,
    QUESTION_INTENTS,
    EvidenceRequest,
    digest,
    render_gaps,
)
from src.workspace.assistance_coverage import (
    GAP_TEXT,
    PartId,
    Retention,
    requested_parts,
    reverse_index,
)
from src.workspace.assistance_coverage_shapes import EvidenceGap, OmissionGap, ShapedEnvelope
from src.workspace.assistance_policy import (
    CONTEXT_REQUESTS,
    CoverageTaskContext,
    TaskContext,
    seal_task_policy,
    validate_task_policy,
)
from src.workspace.d5_capacity_policy import (
    ASSISTANCE_REVISION,
    CHECKS_REVISION,
    CLAIMS_BY_MODE,
    MAX_CITATIONS,
    MAX_FINDINGS,
    MAX_PARTS,
    NORMALIZATION_REVISION,
)
from src.workspace.grounding import (
    ClaimKind,
    EvidenceRef,
    ResearchClaim,
    SupportDecision,
    validate_claims,
)
from src.workspace.material import SourceMaterial

# Semantic revisions are separate from historical v14 contracts.
REVISION = ASSISTANCE_REVISION
COMPACT_NORMALIZATION_REVISION = NORMALIZATION_REVISION
_MAX_CLAIMS = max(CLAIMS_BY_MODE.values())


def _limits() -> dict[str, Any]:
    """Read one prospective policy; never reinterpret historical global bounds."""
    from src.workspace.d5_capacity_policy import POLICY

    return POLICY


def _bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _bounded(value: Any, limit: int, error: str) -> None:
    if len(_bytes(value)) > limit:
        raise ValueError(error)


def seal_policy(context: Any, mode: str, count: int, question: str) -> dict[str, Any]:
    """Seal mode, requested parts and application/task semantics before drafting."""
    old = seal_task_policy(
        TaskContext(intent=context.intent, application_context=context.application_context),
        mode,
        count,
    )
    parts, basis = requested_parts(context, question)
    return {**old, "revision": REVISION, "requested_parts": parts, "parts_basis": basis}


def validate_policy(policy: dict[str, Any]) -> None:
    from src.workspace.assistance_policy import TASK_REVISION

    if policy.get("revision") != REVISION:
        raise ValueError("sealed_capacity_revision_mismatch")
    old = {k: v for k, v in policy.items() if k not in {"requested_parts", "parts_basis"}}
    old["revision"] = TASK_REVISION
    validate_task_policy(old)
    context = CoverageTaskContext.model_validate(
        {
            "intent": policy["task_intent"],
            "application_context": policy["application_context"],
            "requested_parts": policy["requested_parts"],
        }
    )
    parts, _ = requested_parts(context, "")
    if parts != policy["requested_parts"] or policy["parts_basis"] not in {
        "Explicit application/user parts, in priority order",
        "Complete request recorded as one part; no automatic semantic decomposition",
    }:
        raise ValueError("sealed_request_parts_invalid")


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaimKey(StrEnum):
    C1 = "c1"
    C2 = "c2"
    C3 = "c3"
    C4 = "c4"
    C5 = "c5"
    C6 = "c6"
    C7 = "c7"
    C8 = "c8"
    C9 = "c9"
    C10 = "c10"
    C11 = "c11"
    C12 = "c12"


class CapacityClaim(_Closed):
    claim_id: ClaimKey
    text: str = Field(
        min_length=1,
        strict=True,
        description="One atomic finding with every material qualification; 500 characters is a soft target, not a hard limit.",
    )
    handles: tuple[str, ...] = Field(min_length=1, max_length=MAX_CITATIONS)
    required_scope: Literal["abstract", "excerpt", "full_text"] = "abstract"

    @model_validator(mode="after")
    def complete_claim(self) -> CapacityClaim:
        if not self.text.strip() or len(set(self.handles)) != len(self.handles):
            raise ValueError("blank_claim_or_duplicate_handle")
        return self


class CapacityQuestion(_Closed):
    intent: Literal[
        "measured_and_proposed",
        "methods",
        "qualifications",
        "implementation",
        "counterevidence",
        "application_scope",
        "investigate_claim",
    ]
    claim_ids: tuple[ClaimKey, ...] = Field(max_length=_MAX_CLAIMS)

    @model_validator(mode="after")
    def references(self) -> CapacityQuestion:
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("duplicate_question_reference")
        if self.intent == "investigate_claim" and not self.claim_ids:
            raise ValueError("question_premise_requires_scored_claim")
        return self


class CapacityDraft(_Closed):
    """Normalized procedural draft without legacy field or six-claim bounds."""

    claims: tuple[CapacityClaim, ...] = Field(max_length=_MAX_CLAIMS)
    background_claims: tuple[ClaimKey, ...] = Field(max_length=_MAX_CLAIMS)
    assumption_claims: tuple[ClaimKey, ...] = Field(max_length=_MAX_CLAIMS)
    limitation_claims: tuple[ClaimKey, ...] = Field(max_length=_MAX_CLAIMS)
    gaps: tuple[EvidenceRequest, ...] = Field(min_length=1, max_length=3)
    questions: tuple[CapacityQuestion, ...] = Field(min_length=1, max_length=3)
    proposal: Literal[
        "inspect_methods",
        "inspect_evaluation",
        "seek_counterevidence",
        "inspect_scope",
        "request_context",
    ]
    abstention: (
        Literal[
            "insufficient_selected_evidence",
            "application_context_required",
            "comparison_evidence_required",
        ]
        | None
    )
    comparison_claims: tuple[ClaimKey, ...] = Field(default=(), max_length=_MAX_CLAIMS)
    comparison_basis: tuple[ClaimKey, ...] = Field(default=(), max_length=_MAX_CLAIMS)

    @model_validator(mode="after")
    def references(self) -> CapacityDraft:
        ids = {c.claim_id for c in self.claims}
        refs = (
            self.background_claims,
            self.assumption_claims,
            self.limitation_claims,
            self.comparison_claims,
            self.comparison_basis,
            *(q.claim_ids for q in self.questions),
        )
        if len(ids) != len(self.claims) or any(set(r) - ids or len(set(r)) != len(r) for r in refs):
            raise ValueError("claim_or_section_reference_mismatch")
        if not self.claims and self.abstention is None:
            raise ValueError("claims_or_abstention_required")
        if self.comparison_claims and len(self.comparison_basis) < 2:
            raise ValueError("comparison_requires_separate_evidence_claims")
        if not self.comparison_claims and self.comparison_basis:
            raise ValueError("comparison_basis_without_comparison")
        _bounded(
            self.model_dump(mode="json"),
            _limits()["internal_json_bytes"],
            "capacity_internal_output_exceeded",
        )
        return self


def _references(minimum: int = 0, *, maximum: int = _MAX_CLAIMS) -> tuple[Any, Any]:
    return tuple[ClaimKey, ...], Field(min_length=minimum, max_length=maximum)


def _coverage_model(identity: str, policy: dict[str, Any], *, full: bool) -> type[BaseModel]:
    factory = cast(Any, StrEnum)
    part = factory(
        "CapacityPart_" + identity, {p["id"]: p["id"] for p in policy["requested_parts"]}
    )
    refs: dict[str, Any] = {} if full else {"context_claim_ids": _references()}
    evidence = create_model(
        "CapacityGap_" + identity + str(full),
        __base__=_Closed,
        part_id=(part, ...),
        gap=(Literal["application_context"] if policy["missing_context"] else EvidenceGap, ...),
        **refs,
    )
    fields: dict[str, Any] = {
        "lacks_evidence": (GenericAlias(tuple, (evidence, ...)), Field(max_length=MAX_PARTS))
    }
    if not full:
        answered = create_model(
            "CapacityAnswered_" + identity,
            __base__=_Closed,
            part_id=(part, ...),
            answer_claim_ids=_references(1),
            **refs,
        )
        fields["answered"] = (GenericAlias(tuple, (answered, ...)), Field(max_length=MAX_PARTS))
    if not policy["missing_context"]:
        omitted = create_model(
            "CapacityOmitted_" + identity + str(full),
            __base__=_Closed,
            part_id=(part, ...),
            gap=(OmissionGap, ...),
            **refs,
        )
        fields["omitted"] = (GenericAlias(tuple, (omitted, ...)), Field(max_length=MAX_PARTS))
    return create_model("CapacityCoverage_" + identity + str(full), __base__=_Closed, **fields)


def response_model(handles: Sequence[str], purpose: str, policy: dict[str, Any]) -> type[BaseModel]:
    return _cached_model(tuple(handles), purpose, json.dumps(policy, sort_keys=True, ensure_ascii=False))


@lru_cache(maxsize=128)
def _cached_model(handles: tuple[str, ...], purpose: str, policy_json: str) -> type[BaseModel]:
    policy = json.loads(policy_json)
    policy = deepcopy(policy)
    validate_policy(policy)
    selected = sorted(set(handles))
    if not selected or len(selected) > _limits()["max_selected_units"]:
        raise ValueError("capacity_selected_unit_limit")
    if purpose not in {"single_paper", "research_comparison"}:
        raise ValueError("invalid_response_purpose")
    if purpose == "research_comparison" and (
        policy["mode"] != "research" or policy["selected_work_count"] < 2
    ):
        raise ValueError("comparison_requires_two_selected_research_sources")
    identity = digest([selected, purpose, policy])[7:23]
    cap = _limits()["claims_by_mode"][policy["mode"]]
    handle = cast(Any, StrEnum)(
        "CapacityHandle_" + identity, {f"U{i}": v for i, v in enumerate(selected)}
    )
    claim = create_model(
        "CapacityClaim_" + identity,
        __base__=CapacityClaim,
        handles=(GenericAlias(tuple, (handle, ...)), Field(min_length=1, max_length=MAX_CITATIONS)),
    )
    full_fields: dict[str, Any] = {
        "disposition": (Literal["full_abstention"], ...),
        "reason": (
            Literal["application_context_required"]
            if policy["missing_context"]
            else Literal["insufficient_selected_evidence"],
            ...,
        ),
        "next_action": (Literal["request_context"], ...),
        "coverage": (_coverage_model(identity, policy, full=True), ...),
    }
    if policy["missing_context"]:
        context_fields: dict[str, Any] = {
            k: (Literal["required"], ...) for k in policy["missing_context"]
        }
        context = create_model(
            "CapacityContext_" + identity,
            __base__=_Closed,
            **context_fields,
        )
        full_fields["context_requests"] = (context, ...)
    full = create_model("CapacityFull_" + identity, __base__=_Closed, **full_fields)
    branches: Any = full
    allowed = tuple(d for d in policy["allowed_dispositions"] if d != "full_abstention")
    if allowed:
        fields: dict[str, Any] = {
            "claims": (GenericAlias(tuple, (claim, ...)), Field(min_length=1, max_length=cap)),
            "background_claims": _references(maximum=cap),
            "assumption_claims": _references(maximum=cap),
            "limitation_claims": _references(maximum=cap),
            "gaps": (tuple[EvidenceRequest, ...], Field(min_length=1, max_length=3)),
            "questions": (tuple[CapacityQuestion, ...], Field(min_length=1, max_length=3)),
            "proposal": (CapacityDraft.model_fields["proposal"].annotation, ...),
            "disposition": (Literal[allowed], ...),
            "coverage": (_coverage_model(identity, policy, full=False), ...),
        }
        if purpose == "research_comparison":
            fields.update(
                comparison_claims=_references(maximum=cap),
                comparison_basis=_references(maximum=cap),
            )
        claim_bearing = create_model("CapacityClaims_" + identity, __base__=_Closed, **fields)
        branches = full | claim_bearing

    class Envelope(ShapedEnvelope):
        model_config = ConfigDict(extra="forbid", frozen=True)

        @model_validator(mode="after")
        def complete_semantics(self) -> Envelope:
            _normalize_validated(self.model_dump(mode="json"), selected, purpose, policy)
            return self

    return create_model(
        "CapacityResponse_" + identity,
        __base__=Envelope,
        response=(
            branches,
            Field(
                description="Coverage alone maps every sealed part exactly once; retain atomic findings and every qualification. Aggregate payload protection replaces hard narrative field lengths."
            ),
        ),
    )


def schemas(handles: Sequence[str], purpose: str, policy: dict[str, Any]) -> dict[str, Any]:
    model = response_model(handles, purpose, policy)
    return {"local": model.model_json_schema(), "wire": transform_schema(model)}


def _normalize_validated(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    _bounded(payload, _limits()["raw_draft_utf8_bytes"], "capacity_draft_bytes_exceeded")
    value = deepcopy(payload["response"])
    coverage: dict[str, Any] = {}
    full = value["disposition"] == "full_abstention"
    for status, rows in value.pop("coverage").items():
        for row in rows:
            part = row["part_id"]
            if part in coverage:
                raise ValueError("duplicate_or_overlapping_coverage_part")
            coverage[part] = {
                "status": status,
                "gap": "none" if status == "answered" else row["gap"],
                "answer_claim_ids": list(row.get("answer_claim_ids", [])),
                "context_claim_ids": list(row.get("context_claim_ids", [])),
            }
    if set(coverage) != {p["id"] for p in policy["requested_parts"]}:
        raise ValueError("exact_sealed_part_coverage_required")
    coverage = {p["id"]: coverage[p["id"]] for p in policy["requested_parts"]}
    ids = {c["claim_id"] for c in value.get("claims", [])}
    if len(ids) != len(value.get("claims", [])):
        raise ValueError("duplicate_claim_id")
    referenced: set[str] = set()
    omitted = False
    for part in policy["requested_parts"]:
        row = coverage[part["id"]]
        refs = row["answer_claim_ids"] + row["context_claim_ids"]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate_coverage_reference")
        if set(refs) - ids or full and refs:
            raise ValueError("request_part_claim_binding_mismatch")
        if omitted and refs:
            raise ValueError("prioritize_requested_parts_before_lower_priority_context")
        omitted = omitted or row["status"] == "omitted"
        if (
            part["kind"] == "comparison"
            and row["status"] == "answered"
            and (
                value["disposition"] != "answer"
                or not set(row["answer_claim_ids"]) <= set(value.get("comparison_claims", []))
            )
        ):
            raise ValueError("source_notes_cannot_answer_comparison")
        referenced.update(refs)
    if referenced != ids:
        raise ValueError("orphaned_claim_outside_request")
    if not full:
        value["abstention"] = None
        if value["disposition"] == "comparison_abstention":
            if value.get("comparison_claims") or value.get("comparison_basis"):
                raise ValueError("source_notes_cannot_answer_comparison")
            value["abstention"] = "comparison_evidence_required"
        normalized = {k: v for k, v in value.items() if k != "disposition"}
        draft = CapacityDraft.model_validate(normalized)
        if (
            policy["task_intent"] == "comparison"
            and value["disposition"] == "answer"
            and not draft.comparison_claims
        ):
            raise ValueError("comparison_answer_requires_scored_comparison")
    _bounded(
        {"response": value, "coverage": coverage},
        _limits()["internal_json_bytes"],
        "capacity_internal_output_exceeded",
    )
    return {"response": value}, coverage


def normalize(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    _bounded(payload, _limits()["raw_draft_utf8_bytes"], "capacity_draft_bytes_exceeded")
    parsed = response_model(handles, purpose, policy).model_validate(payload)
    return _normalize_validated(parsed.model_dump(mode="json"), handles, purpose, policy)


def validate(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> None:
    normalize(payload, handles, purpose, policy)


def wire_payload(
    envelope: dict[str, Any], coverage: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    """Explicit synthetic/owned normalized-to-wire derivative, never a migration."""
    validate_policy(policy)
    value = deepcopy(envelope["response"])
    full = value["disposition"] == "full_abstention"
    if not full:
        value.pop("abstention", None)
    groups: dict[str, Any] = {"lacks_evidence": []}
    if not full:
        groups["answered"] = []
    if not policy["missing_context"]:
        groups["omitted"] = []
    if set(coverage) != {p["id"] for p in policy["requested_parts"]}:
        raise ValueError("exact_sealed_part_coverage_required")
    for part in policy["requested_parts"]:
        row = coverage[part["id"]]
        status = row["status"]
        if set(row) - {"status", "gap", "answer_claim_ids", "context_claim_ids"}:
            raise ValueError("unknown_coverage_field")
        answer = row.get("answer_claim_ids", [])
        context = row.get("context_claim_ids", [])
        refs = [*answer, *context]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate_coverage_reference")
        if status == "answered":
            if not answer or row.get("gap") != "none":
                raise ValueError("coverage_gap_mismatch")
        elif answer:
            raise ValueError("answer_references_require_answered_status")
        if status == "omitted" and row.get("gap") not in {"claim_budget", "not_prioritized"}:
            raise ValueError("omission_reason_required")
        if status == "lacks_evidence" and row.get("gap") in {
            "none",
            "claim_budget",
            "not_prioritized",
        }:
            raise ValueError("omission_is_not_evidence_absence")
        if status not in groups:
            raise ValueError("coverage_disposition_mismatch")
        item: dict[str, Any] = {"part_id": part["id"]}
        if status == "answered":
            item["answer_claim_ids"] = deepcopy(row["answer_claim_ids"])
        else:
            item["gap"] = row["gap"]
        if not full:
            item["context_claim_ids"] = deepcopy(row.get("context_claim_ids", []))
        elif row.get("answer_claim_ids") or row.get("context_claim_ids"):
            raise ValueError("full_abstention_forbids_claim_references")
        groups[status].append(item)
    value["coverage"] = groups
    return {"response": value}


def normalized_draft(envelope: dict[str, Any], purpose: str) -> CapacityDraft:
    value = deepcopy(envelope["response"])
    disposition = value.pop("disposition")
    if disposition == "full_abstention":
        value = {
            "claims": [],
            "background_claims": [],
            "assumption_claims": [],
            "limitation_claims": [],
            "gaps": ["source_scope"],
            "questions": [{"intent": "application_scope", "claim_ids": []}],
            "proposal": "request_context",
            "abstention": value["reason"],
        }
    if purpose == "research_comparison":
        value.setdefault("comparison_claims", [])
        value.setdefault("comparison_basis", [])
    return CapacityDraft.model_validate(value)


def render(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> dict[str, Any]:
    envelope, coverage = normalize(payload, handles, purpose, policy)
    draft = normalized_draft(envelope, purpose)
    value = draft.model_dump(mode="json")
    questions = [
        QUESTION_INTENTS[q.intent]
        + (" Refer to cited claims " + ", ".join(q.claim_ids) + "." if q.claim_ids else "")
        for q in draft.questions
    ]
    requests = [CONTEXT_REQUESTS[k] for k in policy["missing_context"]]
    rows = [
        {
            **part,
            **coverage[part["id"]],
            "gap_text": (
                f"Not answered within the {_limits()['claims_by_mode'][policy['mode']]}-claim budget."
                if coverage[part["id"]]["gap"] == "claim_budget"
                else GAP_TEXT[coverage[part["id"]]["gap"]]
            ),
        }
        for part in policy["requested_parts"]
    ]
    return {
        **value,
        "questions": questions,
        "gaps": render_gaps(draft.gaps),
        "proposal": " ".join(requests) if requests else ACTION_INTENTS[draft.proposal],
        "abstention": ABSTENTION_INTENTS.get(draft.abstention or "", draft.abstention),
        "response_disposition": envelope["response"]["disposition"],
        "context_requests": requests,
        "comparison_unanswered": envelope["response"]["disposition"] == "comparison_abstention",
        "request_coverage": rows,
        "coverage_complete": all(r["status"] == "answered" for r in rows),
        "claim_request_index": reverse_index(coverage),
        "coverage_basis": "Declared coverage; machine checks are unqualified and human review is unmeasured",
    }


def resolve_draft(
    payload: dict[str, Any],
    catalog: dict[str, EvidenceRef],
    materials: Sequence[SourceMaterial],
    *,
    purpose: str,
    policy: dict[str, Any],
) -> tuple[CapacityDraft, tuple[ResearchClaim, ...]]:
    envelope, _ = normalize(payload, list(catalog), purpose, policy)
    draft = normalized_draft(envelope, purpose)
    claims = []
    for claim in draft.claims:
        if any(h not in catalog for h in claim.handles):
            raise ValueError("unselected_evidence_handle")
        value = ResearchClaim(
            claim.claim_id,
            claim.text,
            ClaimKind.FACTUAL,
            tuple(catalog[h] for h in claim.handles),
            required_scope=claim.required_scope,
        )
        report = validate_claims([value], materials)
        if not report.assessments[0].identity_resolved:
            raise ValueError("assistance_evidence_identity_failed")
        claims.append(value)
    if draft.comparison_claims:
        by_id = {c.claim_id: c for c in claims}
        works = {r.work_id for key in draft.comparison_basis for r in by_id[key].evidence}
        if len(works) < 2:
            raise ValueError("comparison_requires_two_separately_cited_sources")
    return draft, tuple(claims)


class _Reason(_Closed):
    reason: str = Field(
        min_length=1,
        strict=True,
        description="Material evidence or unresolved issue; 240 characters is a soft target, not a hard limit. Never drop findings to fit.",
    )

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("capacity_reason_blank")
        return value


class ClaimReview(_Reason):
    claim_id: ClaimKey
    input_digest: str = Field(strict=True, pattern=r"^sha256:[a-f0-9]{64}$")
    decision: SupportDecision
    atomicity: Literal["atomic", "bundled", "uncertain"]
    qualifications: Retention


class PartReview(_Reason):
    part_id: PartId
    input_digest: str = Field(strict=True, pattern=r"^sha256:[a-f0-9]{64}$")
    decision: Literal["answered", "lacks_evidence", "omitted", "uncertain"]


class ProseFinding(_Reason):
    field: Literal[
        "background", "assumptions", "comparison", "gaps", "questions", "proposal", "abstention"
    ]
    index: int | None = Field(ge=0, le=2, strict=True)

    @model_validator(mode="after")
    def indexed(self) -> ProseFinding:
        if (self.field in {"assumptions", "gaps", "questions"}) != (self.index is not None):
            raise ValueError("prose_finding_index_mismatch")
        return self


class _ChecksRevision(StrEnum):
    V15 = CHECKS_REVISION


class CompactChecks(_Closed):
    revision: _ChecksRevision
    claim_reviews: tuple[ClaimReview, ...] = Field(max_length=_MAX_CLAIMS)
    coverage_checks: tuple[PartReview, ...] = Field(max_length=MAX_PARTS)
    prose_review: Literal["procedural_only", "unscored_factual_content", "abstain"]
    prose_findings: tuple[ProseFinding, ...] = Field(max_length=MAX_FINDINGS)
    priority_review: Literal["respected", "violated", "uncertain"]

    @model_validator(mode="after")
    def complete_structure(self) -> CompactChecks:
        _check_structure(
            self.claim_reviews, self.coverage_checks, self.prose_review, self.prose_findings
        )
        _bounded(
            self.model_dump(mode="json"),
            _limits()["compact_checker_utf8_bytes"],
            "capacity_compact_checks_bytes_exceeded",
        )
        return self


class SupportReview(_Reason):
    claim_id: ClaimKey
    input_digest: str = Field(strict=True, pattern=r"^sha256:[a-f0-9]{64}$")
    decision: SupportDecision


class QualityReview(_Reason):
    claim_id: ClaimKey
    input_digest: str = Field(strict=True, pattern=r"^sha256:[a-f0-9]{64}$")
    atomicity: Literal["atomic", "bundled", "uncertain"]
    qualifications: Retention


def _check_structure(claims: Any, parts: Any, prose_review: str, findings: Any) -> None:
    for rows, key in ((claims, "claim_id"), (parts, "part_id")):
        if len({getattr(r, key) for r in rows}) != len(rows):
            raise ValueError("capacity_duplicate_" + key)
    if (prose_review == "procedural_only") != (not findings):
        raise ValueError("prose_finding_required_or_inconsistent")
    if len({(f.field, f.index) for f in findings}) != len(findings):
        raise ValueError("duplicate_prose_finding")


class CoverageChecks(_Closed):
    checks: tuple[SupportReview, ...] = Field(max_length=_MAX_CLAIMS)
    claim_quality: tuple[QualityReview, ...] = Field(max_length=_MAX_CLAIMS)
    coverage_checks: tuple[PartReview, ...] = Field(max_length=MAX_PARTS)
    prose_review: Literal["procedural_only", "unscored_factual_content", "abstain"]
    prose_findings: tuple[ProseFinding, ...] = Field(max_length=MAX_FINDINGS)
    priority_review: Literal["respected", "violated", "uncertain"]

    @model_validator(mode="after")
    def complete_structure(self) -> CoverageChecks:
        _check_structure(self.checks, self.coverage_checks, self.prose_review, self.prose_findings)
        support = {c.claim_id: c.input_digest for c in self.checks}
        quality = {c.claim_id: c.input_digest for c in self.claim_quality}
        if len(quality) != len(self.claim_quality) or support != quality:
            raise ValueError("claim_quality_binding_mismatch")
        _bounded(
            self.model_dump(mode="json"),
            _limits()["normalized_checker_utf8_bytes"],
            "capacity_normalized_checks_bytes_exceeded",
        )
        return self

    def validate_locations(self, prose: dict[str, Any]) -> None:
        _validate_locations(self.prose_findings, prose)


def _validate_locations(findings: Sequence[ProseFinding], prose: dict[str, Any]) -> None:
    """Locate every finding in the exact rendered prose, without legacy bounds."""
    for finding in findings:
        if finding.field not in prose:
            raise ValueError("checker_prose_location_mismatch")
        value = prose[finding.field]
        if finding.index is not None:
            if not isinstance(value, list) or finding.index >= len(value):
                raise ValueError("checker_prose_location_mismatch")
            value = value[finding.index]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("checker_prose_location_mismatch")


def checks_model() -> type[CoverageChecks]:
    return CoverageChecks


def check_schemas() -> dict[str, Any]:
    return {"local": CompactChecks.model_json_schema(), "wire": transform_schema(CompactChecks)}


def normalize_checks(raw: dict[str, Any]) -> dict[str, Any]:
    _bounded(raw, _limits()["compact_checker_utf8_bytes"], "capacity_compact_checks_bytes_exceeded")
    value = CompactChecks.model_validate(raw)
    rows = [r.model_dump(mode="json") for r in value.claim_reviews]
    return CoverageChecks.model_validate(
        {
            "checks": [
                {k: r[k] for k in ("claim_id", "input_digest", "decision", "reason")} for r in rows
            ],
            "claim_quality": [
                {
                    k: r[k]
                    for k in ("claim_id", "input_digest", "atomicity", "qualifications", "reason")
                }
                for r in rows
            ],
            "coverage_checks": [r.model_dump(mode="json") for r in value.coverage_checks],
            "prose_review": value.prose_review,
            "prose_findings": [r.model_dump(mode="json") for r in value.prose_findings],
            "priority_review": value.priority_review,
        }
    ).model_dump(mode="json")


def compact_checks_fixture(normalized: dict[str, Any]) -> dict[str, Any]:
    """Lossless synthetic inverse; refuse different reasons instead of merging."""
    value = CoverageChecks.model_validate(normalized)
    rows = []
    for support, quality in zip(value.checks, value.claim_quality, strict=True):
        if (support.claim_id, support.input_digest) != (quality.claim_id, quality.input_digest):
            raise ValueError("compact_fixture_claim_binding_mismatch")
        if support.reason != quality.reason:
            raise ValueError("compact_fixture_distinct_reasons")
        rows.append({**quality.model_dump(mode="json"), "decision": support.decision})
    result = {
        "revision": CHECKS_REVISION,
        "claim_reviews": rows,
        "coverage_checks": [r.model_dump(mode="json") for r in value.coverage_checks],
        "prose_review": value.prose_review,
        "prose_findings": [r.model_dump(mode="json") for r in value.prose_findings],
        "priority_review": value.priority_review,
    }
    return CompactChecks.model_validate(result).model_dump(mode="json")


class ProbeChecks(_Closed):
    """Support/prose probe contract; independent of whole-answer coverage rows."""

    checks: tuple[SupportReview, ...] = Field(max_length=_MAX_CLAIMS)
    prose_review: Literal["procedural_only", "unscored_factual_content", "abstain"]
    prose_findings: tuple[ProseFinding, ...] = Field(max_length=MAX_FINDINGS)

    @model_validator(mode="after")
    def complete_structure(self) -> ProbeChecks:
        _check_structure(self.checks, (), self.prose_review, self.prose_findings)
        _bounded(
            self.model_dump(mode="json"),
            _limits()["normalized_checker_utf8_bytes"],
            "capacity_normalized_checks_bytes_exceeded",
        )
        return self

    def validate_locations(self, prose: dict[str, Any]) -> None:
        _validate_locations(self.prose_findings, prose)


def probe_checks_model() -> type[ProbeChecks]:
    return ProbeChecks
