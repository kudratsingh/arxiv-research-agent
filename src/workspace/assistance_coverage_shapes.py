"""V9 wire-disjoint coverage. V8 models and archived requests remain unchanged."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.workspace.assistance_coverage import ClaimId

EvidenceGap = Literal[
    "application_context",
    "source_scope",
    "common_evaluation",
    "methods",
    "protocol",
    "data_splits",
    "metric_definition",
    "uncertainty_calibration",
    "memory_error_persistence",
]
OmissionGap = Literal["claim_budget", "not_prioritized"]


class ShapedEnvelope(BaseModel):
    """Export fixed literals as enums: the SDK drops const but preserves enum."""

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        schema = super().model_json_schema(*args, **kwargs)

        def enums(value: Any) -> None:
            if isinstance(value, dict):
                if "const" in value:
                    value["enum"] = [value.pop("const")]
                for child in value.values():
                    enums(child)
            elif isinstance(value, list):
                for child in value:
                    enums(child)

        enums(schema)
        return schema


class Answered(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["answered"]
    answer_claim_ids: tuple[ClaimId, ...] = Field(min_length=1, max_length=6)
    context_claim_ids: tuple[ClaimId, ...] = Field(max_length=6)
    gap: Literal["none"]


class EvidenceGapOnly(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["lacks_evidence"]
    gap: EvidenceGap


class OmittedOnly(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["omitted"]
    gap: OmissionGap


class EvidenceGapNotes(EvidenceGapOnly):
    context_claim_ids: tuple[ClaimId, ...] = Field(max_length=6)


class OmittedNotes(OmittedOnly):
    context_claim_ids: tuple[ClaimId, ...] = Field(max_length=6)


class MissingContext(EvidenceGapOnly):
    gap: Literal["application_context"]


def coverage_type(*, full: bool, missing_context: bool) -> Any:
    if missing_context:
        return MissingContext
    if full:
        return EvidenceGapOnly | OmittedOnly
    return Answered | EvidenceGapNotes | OmittedNotes
