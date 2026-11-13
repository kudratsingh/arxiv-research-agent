"""Prospective compact COMPLETE verdict contract; pure offline validation only.

The wire carries each claim identity and shared explanation once. Normalization
expands it into the unchanged CoverageChecks model. This module neither repairs
truncated responses nor establishes provider stop status, bindings or truth.
Callers must first require a complete provider response and then run the existing
validate_review and validate_locations checks against sealed request context.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from anthropic import transform_schema
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.workspace.assistance_coverage import ClaimId, PartId, Retention
from src.workspace.grounding import SupportDecision

COMPACT_CHECKS_REVISION = "workspace-assistance-compact-checks-v14"
COMPACT_NORMALIZATION_REVISION = "workspace-assistance-compact-checks-normalization-v14"
MAX_REASON_CHARS = 96
MAX_REASON_BYTES = 120
MAX_REASON_JSON_BYTES = 120
MAX_COMPACT_BYTES = 8000


class CompactChecksRevision(StrEnum):
    V14 = COMPACT_CHECKS_REVISION


class _Reason(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: str = Field(
        min_length=1,
        max_length=MAX_REASON_CHARS,
        strict=True,
        description="Concise material evidence or unresolved issue across the row judgments; <=120 JSON-encoded UTF-8 bytes locally.",
    )

    @field_validator("reason")
    @classmethod
    def bounded_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("compact_reason_blank")
        if len(value.encode("utf-8")) > MAX_REASON_BYTES:
            raise ValueError("compact_reason_utf8_limit")
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) - 2 > MAX_REASON_JSON_BYTES:
            raise ValueError("compact_reason_json_limit")
        return value


class CompactClaimReview(_Reason):
    claim_id: ClaimId
    input_digest: str = Field(strict=True, pattern=r"^sha256:[a-f0-9]{64}$")
    decision: SupportDecision
    atomicity: Literal["atomic", "bundled", "uncertain"]
    qualifications: Retention


class CompactPartReview(_Reason):
    part_id: PartId
    input_digest: str = Field(strict=True, pattern=r"^sha256:[a-f0-9]{64}$")
    decision: Literal["answered", "lacks_evidence", "omitted", "uncertain"]


class CompactProseFinding(_Reason):
    field: Literal[
        "background", "assumptions", "comparison", "gaps", "questions", "proposal", "abstention"
    ]
    index: int | None = Field(ge=0, le=2, strict=True)

    @model_validator(mode="after")
    def indexed_field(self) -> CompactProseFinding:
        if (self.field in {"assumptions", "gaps", "questions"}) != (self.index is not None):
            raise ValueError("prose_finding_index_mismatch")
        return self


class CompactChecks(BaseModel):
    """All judgments remain mandatory; a shared reason covers claim judgments.

    Reasons concisely identify the material evidence or unresolved issue; their
    omission never defaults any support, atomicity or qualification judgment.
    UTF-8 byte bounds and semantic/binding checks are local validation duties,
    including where the SDK's transformed schema removes unsupported constraints.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    revision: CompactChecksRevision
    claim_reviews: tuple[CompactClaimReview, ...] = Field(max_length=6)
    coverage_checks: tuple[CompactPartReview, ...] = Field(max_length=8)
    prose_review: Literal["procedural_only", "unscored_factual_content", "abstain"]
    prose_findings: tuple[CompactProseFinding, ...] = Field(max_length=10)
    priority_review: Literal["respected", "violated", "uncertain"]

    @model_validator(mode="after")
    def complete_structure(self) -> CompactChecks:
        for rows, key in (
            (self.claim_reviews, "claim_id"),
            (self.coverage_checks, "part_id"),
        ):
            if len({getattr(row, key) for row in rows}) != len(rows):
                raise ValueError("compact_duplicate_" + key)
        if (self.prose_review == "procedural_only") != (not self.prose_findings):
            raise ValueError("prose_finding_required_or_inconsistent")
        locations = {(f.field, f.index) for f in self.prose_findings}
        if len(locations) != len(self.prose_findings):
            raise ValueError("duplicate_prose_finding")
        if len(_json_bytes(self.model_dump(mode="json"))) > MAX_COMPACT_BYTES:
            raise ValueError("compact_checks_utf8_limit")
        return self


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def wire_model() -> type[CompactChecks]:
    return CompactChecks


def schemas() -> dict[str, Any]:
    """Exact local and SDK-transformed schemas, without provider/count I/O."""
    return {"local": CompactChecks.model_json_schema(), "wire": transform_schema(CompactChecks)}


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Strictly expand a complete compact verdict without repairing its contents.

    The caller preserves raw provider bytes independently. This function takes no
    completion status: a max_tokens response, even with complete JSON, must be
    rejected by the caller before normalization. Existing context binding and
    located-prose validation remain mandatory after this structural step.
    """
    from src.workspace.assistance import CoverageChecks

    value = CompactChecks.model_validate(raw)
    claims = [row.model_dump(mode="json") for row in value.claim_reviews]
    result = {
        "checks": [
            {k: row[k] for k in ("claim_id", "input_digest", "decision", "reason")}
            for row in claims
        ],
        "claim_quality": [
            {
                k: row[k]
                for k in ("claim_id", "input_digest", "atomicity", "qualifications", "reason")
            }
            for row in claims
        ],
        "coverage_checks": [row.model_dump(mode="json") for row in value.coverage_checks],
        "prose_review": value.prose_review,
        "prose_findings": [row.model_dump(mode="json") for row in value.prose_findings],
        "priority_review": value.priority_review,
    }
    normalized = CoverageChecks.model_validate(result).model_dump(mode="json")
    if len(_json_bytes(normalized)) > MAX_COMPACT_BYTES:
        raise ValueError("compact_normalized_checks_utf8_limit")
    return normalized


def compact_fixture(normalized: dict[str, Any]) -> dict[str, Any]:
    """Inverse for synthetic fixtures with identical support/quality reasons.

    Refuse distinct reasons or differently ordered bindings rather than silently
    discard information. Historical responses are never migrated by this helper.
    """
    from src.workspace.assistance import CoverageChecks

    value = CoverageChecks.model_validate(normalized)
    support = value.checks
    quality = value.claim_quality
    if len(support) != len(quality):
        raise ValueError("compact_fixture_claim_binding_mismatch")
    rows = []
    for verdict, review in zip(support, quality, strict=True):
        if (verdict.claim_id, verdict.input_digest) != (review.claim_id, review.input_digest):
            raise ValueError("compact_fixture_claim_binding_mismatch")
        if verdict.reason != review.reason:
            raise ValueError("compact_fixture_distinct_reasons")
        rows.append({**review.model_dump(mode="json"), "decision": verdict.decision})
    raw = {
        "revision": COMPACT_CHECKS_REVISION,
        "claim_reviews": rows,
        "coverage_checks": [row.model_dump(mode="json") for row in value.coverage_checks],
        "prose_review": value.prose_review,
        "prose_findings": [row.model_dump(mode="json") for row in value.prose_findings],
        "priority_review": value.priority_review,
    }
    return CompactChecks.model_validate(raw).model_dump(mode="json")
