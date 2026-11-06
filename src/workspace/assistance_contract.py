"""D5 evidence/response contract. Historical V8 remains byte-identical.

Units are exact contiguous retained text, not arbitrary fixed-width snippets.
Sentence segmentation is a bounded heuristic, not extraction qualification.
Different units remain separate citations even on the same page.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict
from enum import StrEnum
from types import GenericAlias
from typing import Any, Literal, cast

from anthropic import transform_schema
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from src.workspace.grounding import (
    ClaimKind,
    EvidenceRef,
    ResearchClaim,
    evidence_ref,
    validate_claims,
)
from src.workspace.material import SourceMaterial

REVISION = "workspace-assistance-coherent-multicitation-v1"
MAX_UNIT_CHARS = 1600
MAX_SELECTED_UNITS = 8
MAX_CLAIMS = 6
MAX_DRAFT_BYTES = 8_000


def digest(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    )


def coherent_units(
    materials: Sequence[SourceMaterial], selected_spans: set[str]
) -> dict[str, EvidenceRef]:
    """Use complete retained paragraphs/sentence groups; never expand selection.

    Partial edge sentences at a retained-span boundary are omitted. A very long
    sentence is unavailable rather than shortened into a misleading proposition.
    Adjacent qualifiers fit in one unit whenever the bound permits them. The UI
    still discloses neighboring/omitted material and all source-scope limitations.
    """
    validate_claims([], materials)
    found: set[str] = set()
    units: dict[str, EvidenceRef] = {}
    for material in materials:
        if material.scope == "metadata":
            continue
        for span in material.spans:
            if span.span_id not in selected_spans:
                continue
            found.add(span.span_id)
            page_index = (
                material.page_numbers.index(span.page)
                if material.page_numbers is not None and span.page is not None
                else (span.page or 1) - 1
            )
            page = material.pages[page_index]
            start, end = span.start, span.end
            known_boundary = False
            if material.page_count is not None and span.start == 0:
                # Retain the original page verbatim. Only choose a later exact
                # offset when a known PDF header/front-matter boundary exists.
                heading = (
                    re.search(r"(?m)^[ \t]*ABSTRACT[ \t]*$", page[start:end])
                    if span.page == 1
                    else None
                )
                if heading:
                    start += heading.end()
                    while start < end and page[start].isspace():
                        start += 1
                    known_boundary = True
                else:
                    header = re.match(
                        r"(?:Published as[^\n]*|Preprint\.?)[ \t]*\n+", page[start:end]
                    )
                    if header:
                        start += header.end()
                        known_boundary = True
            # Do not turn a chopped leading/trailing sentence into full evidence.
            if start and not known_boundary and not re.search(r"[.!?]\s*$|\n\s*\n$", page[:start]):
                boundary = re.search(r"[.!?](?:[\"'”’)]*)\s+|\n\s*\n", page[start:end])
                if boundary is None:
                    continue
                start += boundary.end()
            if end < len(page) and not re.search(r"[.!?][\"'”’)]*\s*$|\n\s*\n$", page[start:end]):
                boundaries = list(re.finditer(r"[.!?][\"'”’)]*(?=\s)|\n\s*\n", page[start:end]))
                if not boundaries:
                    continue
                end = start + boundaries[-1].end()
            # Pack consecutive complete sentences; preserve all original bytes
            # between them, including whitespace/Unicode and paragraph breaks.
            pieces = list(
                re.finditer(r".+?(?:[.!?][\"'”’)]*(?=\s|$)|\n\s*\n|$)", page[start:end], re.S)
            )
            first: int | None = None
            last = start
            for piece in pieces:
                a, b = start + piece.start(), start + piece.end()
                while a < b and page[a].isspace():
                    a += 1
                while b > a and page[b - 1].isspace():
                    b -= 1
                if b <= a:
                    continue
                if first is not None and b - first > MAX_UNIT_CHARS:
                    ref = evidence_ref(material, span, start=first, end=last)
                    units["u" + digest(asdict(ref))[7:27]] = ref
                    first = None
                if b - a > MAX_UNIT_CHARS:
                    continue
                if first is None:
                    first = a
                last = b
            if first is not None:
                ref = evidence_ref(material, span, start=first, end=last)
                units["u" + digest(asdict(ref))[7:27]] = ref
    if selected_spans != found or not units:
        raise ValueError("coherent_selected_evidence_unavailable")
    # Span text is a separately persisted field: do not trust it merely because
    # the material's page hash is valid. Refuse corruption before previewing.
    for reference in units.values():
        check = ResearchClaim("unit", "Selected evidence", ClaimKind.FACTUAL, (reference,))
        if not validate_claims([check], materials).assessments[0].identity_resolved:
            raise ValueError("coherent_unit_provenance_invalid")
    return units


class AssistanceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim_id: Literal["c1", "c2", "c3", "c4", "c5", "c6"]
    text: str = Field(min_length=1, max_length=360)
    handles: tuple[str, ...] = Field(min_length=1, max_length=3)
    required_scope: Literal["abstract", "excerpt", "full_text"] = "abstract"


class AssistanceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claims: tuple[AssistanceClaim, ...] = Field(max_length=MAX_CLAIMS)
    background: str = Field(max_length=360)
    comparison: str = Field(max_length=360)
    comparison_basis: tuple[str, ...] = Field(max_length=MAX_CLAIMS)
    assumptions: tuple[str, ...] = Field(max_length=3)
    gaps: tuple[str, ...] = Field(min_length=1, max_length=3)
    questions: tuple[str, ...] = Field(min_length=1, max_length=3)
    proposal: str = Field(max_length=360)
    abstention: str | None = Field(max_length=180)

    @model_validator(mode="after")
    def bounded(self) -> AssistanceDraft:
        ids = {c.claim_id for c in self.claims}
        if len(ids) != len(self.claims) or set(self.comparison_basis) - ids:
            raise ValueError("claim_or_comparison_basis_mismatch")
        if not self.claims and not (self.abstention or "").strip():
            raise ValueError("claims_or_abstention_required")
        if self.comparison and len(self.comparison_basis) < 2:
            raise ValueError("comparison_requires_separate_evidence_claims")
        if any(not c.text.strip() or len(set(c.handles)) != len(c.handles) for c in self.claims):
            raise ValueError("blank_claim_or_duplicate_handle")
        if any(
            not x.strip() or len(x) > 180 for x in (*self.assumptions, *self.gaps, *self.questions)
        ):
            raise ValueError("invalid_bounded_explanation")
        if len(self.model_dump_json().encode()) > MAX_DRAFT_BYTES:
            raise ValueError("assistance_response_too_large")
        return self


def response_model(handles: Sequence[str]) -> type[AssistanceDraft]:
    # json_schema_extra keeps even a singleton enum after the SDK transform.
    selected = sorted(set(handles))
    if not selected or len(selected) > MAX_SELECTED_UNITS:
        raise ValueError("select_one_to_eight_coherent_units")
    identity = digest(selected)[7:23]
    factory = cast(Callable[[str, dict[str, str]], type[StrEnum]], StrEnum)
    handle_type = factory(
        "D5Evidence_" + identity, {f"U{i}": key for i, key in enumerate(selected)}
    )
    claim = create_model(
        "D5Claim_" + identity,
        __base__=AssistanceClaim,
        handles=(GenericAlias(tuple, (handle_type, Ellipsis)), Field(min_length=1, max_length=3)),
    )
    return create_model(
        "D5Draft_" + identity,
        __base__=AssistanceDraft,
        claims=(GenericAlias(tuple, (claim, Ellipsis)), Field(max_length=MAX_CLAIMS)),
    )


def schemas(handles: Sequence[str]) -> dict[str, Any]:
    model = response_model(handles)
    return {"local": model.model_json_schema(), "wire": transform_schema(model)}


def resolve_draft(
    payload: dict[str, Any], catalog: dict[str, EvidenceRef], materials: Sequence[SourceMaterial]
) -> tuple[AssistanceDraft, tuple[ResearchClaim, ...]]:
    draft = response_model(list(catalog)).model_validate(payload)
    claims = []
    for claim in draft.claims:
        if any(handle not in catalog for handle in claim.handles):
            raise ValueError("unselected_evidence_handle")
        refs = tuple(catalog[handle] for handle in claim.handles)
        # Never coalesce separate quotations, even if they share a parent/page.
        value = ResearchClaim(
            claim.claim_id, claim.text, ClaimKind.FACTUAL, refs, required_scope=claim.required_scope
        )
        report = validate_claims([value], materials)
        if not report.assessments[0].identity_resolved:
            raise ValueError("assistance_evidence_identity_failed")
        claims.append(value)
    if draft.comparison:
        by_id = {claim.claim_id: claim for claim in claims}
        compared_sources = {
            ref.work_id for key in draft.comparison_basis for ref in by_id[key].evidence
        }
        if len(compared_sources) < 2:
            raise ValueError("comparison_requires_two_separately_cited_sources")
    return draft, tuple(claims)
