"""Model-free admission of future per-claim support checks.

Resolving a citation/span is an identity diagnostic, never factual support. A
factual decision requires a separate explicit checker verdict bound to the exact
claim, retained material version, parser and quoted offsets. This validator does
not infer truth from lexical overlap, a real citation ID, model agreement or a
well-formed verdict. Checker quality/calibration and claim-extraction recall are
separate launch gates. These contracts do not change historical eval metrics.

Materials come from the authoritative retained store; callers cannot substitute
arbitrary content under an old version. Factual claims and labelled inferences
are kept separate. Abstract-only material cannot certify missing methods/body
content, even when a supplied checker says ``supported``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum

from src.workspace.material import Scope, SourceMaterial, SourceSpan


class GroundingError(ValueError):
    """A provenance/instrument violation; no support result may be published."""


class ClaimKind(StrEnum):
    FACTUAL = "factual"
    INFERENCE = "inference"


class SupportDecision(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class EvidenceRef:
    material_id: str
    span_id: str
    work_id: str
    version_id: str
    source_hash: str
    scope: Scope
    parser_revision: str
    page: int | None
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class ResearchClaim:
    claim_id: str
    text: str
    kind: ClaimKind
    evidence: tuple[EvidenceRef, ...] = ()
    required_scope: Scope = "abstract"
    required_section: str | None = None
    inference_label: str | None = None


@dataclass(frozen=True)
class SupportCheck:
    claim_id: str
    input_digest: str
    decision: SupportDecision
    checker_id: str
    checker_revision: str
    reason: str


@dataclass(frozen=True)
class ClaimAssessment:
    claim_id: str
    kind: ClaimKind
    identity_resolved: bool
    scope_compatible: bool
    checked: bool
    decision: SupportDecision | None
    reason: str
    input_digest: str | None
    checker_id: str | None = None
    checker_revision: str | None = None
    inference_label: str | None = None


@dataclass(frozen=True)
class GroundingReport:
    assessments: tuple[ClaimAssessment, ...]
    total_factual: int
    checked: int
    supported: int
    unsupported: int
    abstained: int
    decided: int
    support_ratio: float | None
    inference_count: int
    ratio_basis: str = (
        "supported / (supported + unsupported); abstentions excluded, unscored is null"
    )
    check_basis: str = "explicit current checker verdicts over compatible retained evidence; includes checker abstentions"
    validator_revision: str = "workspace-grounding-v1"


def evidence_ref(
    material: SourceMaterial, span: SourceSpan, *, start: int | None = None, end: int | None = None
) -> EvidenceRef:
    """A precise quote into one retained span; offsets are page-local Unicode."""
    first = span.start if start is None else start
    last = span.end if end is None else end
    if span not in material.spans or not span.start <= first < last <= span.end:
        raise GroundingError("quote_outside_retained_span")
    return EvidenceRef(
        material.material_id,
        span.span_id,
        material.work_id,
        material.version_id,
        material.source_hash,
        material.scope,
        material.parser_revision,
        span.page,
        first,
        last,
        span.text[first - span.start : last - span.start],
    )


def _materials(materials: Sequence[SourceMaterial]) -> dict[str, SourceMaterial]:
    by_id: dict[str, SourceMaterial] = {}
    for material in materials:
        if material.material_id in by_id:
            raise GroundingError("duplicate_material_id")
        if len({span.span_id for span in material.spans}) != len(material.spans):
            raise GroundingError("duplicate_retained_span_id")
        expected_hash = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(list(material.pages), ensure_ascii=False, separators=(",", ":")).encode()
            ).hexdigest()
        )
        if expected_hash != material.content_hash:
            raise GroundingError("retained_material_content_drift")
        if material.page_numbers is not None and (
            len(material.page_numbers) != len(material.pages)
            or any(type(page) is not int or page < 1 or material.page_count is None or page > material.page_count for page in material.page_numbers)
            or list(material.page_numbers) != sorted(set(material.page_numbers))
        ):
            raise GroundingError("retained_page_mapping_drift")
        by_id[material.material_id] = material
    return by_id


def _resolve(
    ref: EvidenceRef, materials: dict[str, SourceMaterial]
) -> tuple[SourceMaterial, SourceSpan] | None:
    material = materials.get(ref.material_id)
    if material is None:
        return None
    spans = {span.span_id: span for span in material.spans}
    span = spans.get(ref.span_id)
    if span is None:
        return None
    if (ref.work_id, ref.version_id, ref.source_hash, ref.scope, ref.parser_revision, ref.page) != (
        material.work_id,
        material.version_id,
        material.source_hash,
        material.scope,
        material.parser_revision,
        span.page,
    ):
        raise GroundingError("source_version_or_scope_drift")
    if (
        span.work_id,
        span.version_id,
        span.material_id,
        span.source_hash,
        span.scope,
        span.parser_revision,
    ) != (
        material.work_id,
        material.version_id,
        material.material_id,
        material.source_hash,
        material.scope,
        material.parser_revision,
    ):
        raise GroundingError("retained_span_identity_drift")
    if material.page_numbers is not None:
        if span.page not in material.page_numbers:
            raise GroundingError("retained_page_mapping_drift")
        page_index = material.page_numbers.index(span.page)
    else:
        page_index = span.page - 1 if span.page is not None else 0
    if (
        not 0 <= page_index < len(material.pages)
        or material.pages[page_index][span.start : span.end] != span.text
    ):
        raise GroundingError("retained_span_content_drift")
    if (
        not span.start <= ref.start < ref.end <= span.end
        or not ref.quote
        or ref.quote != span.text[ref.start - span.start : ref.end - span.start]
    ):
        raise GroundingError("quote_not_in_retained_span")
    return material, span


def _claim_shape(claim: ResearchClaim) -> None:
    if (
        not claim.claim_id.strip()
        or len(claim.claim_id) > 120
        or not claim.text.strip()
        or len(claim.text) > 10000
    ):
        raise GroundingError("invalid_claim")
    if claim.kind not in {ClaimKind.FACTUAL, ClaimKind.INFERENCE} or claim.required_scope not in {
        "metadata",
        "abstract",
        "excerpt",
        "full_text",
    }:
        raise GroundingError("invalid_claim_kind_or_scope")
    if claim.kind == ClaimKind.INFERENCE and not (claim.inference_label or "").strip():
        raise GroundingError("inference_label_required")
    if claim.kind == ClaimKind.FACTUAL and claim.inference_label is not None:
        raise GroundingError("factual_claim_cannot_be_labelled_inference")
    # Distinct, nonoverlapping quotations from one retained parent remain
    # separate citations. Do not merge their intervening, unselected text.
    for index, ref in enumerate(claim.evidence):
        if any(
            other.material_id == ref.material_id
            and other.span_id == ref.span_id
            and max(other.start, ref.start) < min(other.end, ref.end)
            for other in claim.evidence[:index]
        ):
            raise GroundingError("duplicate_evidence_span")


def _digest(claim: ResearchClaim, resolved: Sequence[tuple[SourceMaterial, SourceSpan]]) -> str:
    value = {
        "claim": asdict(claim),
        "materials": [
            {
                "material_id": material.material_id,
                "content_hash": material.content_hash,
                "source_hash": material.source_hash,
                "version_id": material.version_id,
                "parser_revision": material.parser_revision,
                "scope": material.scope,
                "complete": material.complete,
                "quality": material.quality,
                "offset_basis": material.offset_basis,
                "page_numbers": material.page_numbers,
                "warnings": material.warnings,
                "span": asdict(span),
            }
            for material, span in resolved
        ],
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    )


def claim_input_digest(claim: ResearchClaim, materials: Sequence[SourceMaterial]) -> str:
    """Seal the actual checker input; refusal on missing/drifted evidence."""
    _claim_shape(claim)
    available = _materials(materials)
    resolved = [_resolve(ref, available) for ref in claim.evidence]
    if not resolved or any(value is None for value in resolved):
        raise GroundingError("checker_input_unavailable")
    return _digest(claim, [value for value in resolved if value is not None])


def _scope_compatible(claim: ResearchClaim, material: SourceMaterial, span: SourceSpan) -> bool:
    scope = material.scope
    if claim.required_scope == "full_text" and (scope != "full_text" or not material.complete):
        return False
    if (
        claim.required_scope == "abstract"
        and scope not in {"abstract", "full_text"}
        and not (scope == "excerpt" and span.section == "abstract")
    ):
        return False
    if claim.required_scope == "excerpt" and scope == "metadata":
        return False
    section = (claim.required_section or "").lower()
    # A method/body claim cannot be certified from an abstract by weakening its
    # declared required_scope. A properly identified excerpt can be sufficient.
    if section and section != "abstract":
        if scope in {"metadata", "abstract"}:
            return False
        if scope == "excerpt" and (span.section or "").lower() != section:
            return False
    return True


def validate_claims(
    claims: Sequence[ResearchClaim],
    materials: Sequence[SourceMaterial],
    checks: Sequence[SupportCheck] = (),
) -> GroundingReport:
    """Admit explicit checks, preserving abstentions and the factual denominator.

    Missing refs abstain without a check. Supplying a decided check for missing
    inputs is an integrity error, rather than silently trusting its verdict.
    Valid citation identity alone always remains unscored. Inferences are never
    promoted to factual findings and cannot carry a support-check verdict.
    """
    available = _materials(materials)
    if len({claim.claim_id for claim in claims}) != len(claims):
        raise GroundingError("duplicate_claim_id")
    if len({check.claim_id for check in checks}) != len(checks):
        raise GroundingError("duplicate_check")
    by_check = {check.claim_id: check for check in checks}
    if set(by_check) - {claim.claim_id for claim in claims}:
        raise GroundingError("check_has_unknown_claim")
    assessments: list[ClaimAssessment] = []
    for claim in claims:
        _claim_shape(claim)
        found = [_resolve(ref, available) for ref in claim.evidence]
        resolved = [entry for entry in found if entry is not None]
        identity = bool(found) and len(found) == len(resolved)
        compatible = identity and all(
            _scope_compatible(claim, material, span) for material, span in resolved
        )
        digest = _digest(claim, resolved) if identity else None
        check = by_check.get(claim.claim_id)
        if claim.kind == ClaimKind.INFERENCE:
            if check:
                raise GroundingError("inference_cannot_be_verified")
            assessments.append(
                ClaimAssessment(
                    claim.claim_id,
                    claim.kind,
                    identity,
                    compatible,
                    False,
                    None,
                    "labelled_inference_not_factual_support",
                    digest,
                    inference_label=claim.inference_label,
                )
            )
            continue
        if check:
            if (
                check.decision not in set(SupportDecision)
                or not check.checker_id.strip()
                or not check.checker_revision.strip()
                or not check.reason.strip()
            ):
                raise GroundingError("invalid_support_check")
            if not identity:
                raise GroundingError("check_references_missing")
            if check.input_digest != digest:
                raise GroundingError("checker_input_drift")
        if not identity:
            decision, reason, checked = SupportDecision.ABSTAIN, "evidence_reference_missing", False
        elif not compatible:
            decision, reason, checked = SupportDecision.ABSTAIN, "source_scope_insufficient", False
        elif not check:
            decision, reason, checked = SupportDecision.ABSTAIN, "factual_support_unmeasured", False
        else:
            decision, reason, checked = check.decision, check.reason, True
        assessments.append(
            ClaimAssessment(
                claim.claim_id,
                claim.kind,
                identity,
                compatible,
                checked,
                decision,
                reason,
                digest,
                checker_id=check.checker_id if check else None,
                checker_revision=check.checker_revision if check else None,
            )
        )
    factual = [assessment for assessment in assessments if assessment.kind == ClaimKind.FACTUAL]
    supported = sum(a.decision == SupportDecision.SUPPORTED for a in factual)
    unsupported = sum(a.decision == SupportDecision.UNSUPPORTED for a in factual)
    abstained = sum(a.decision == SupportDecision.ABSTAIN for a in factual)
    decided = supported + unsupported
    return GroundingReport(
        tuple(assessments),
        len(factual),
        sum(a.checked for a in factual),
        supported,
        unsupported,
        abstained,
        decided,
        supported / decided if decided else None,
        len(assessments) - len(factual),
    )
