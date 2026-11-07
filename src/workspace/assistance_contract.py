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

LEGACY_REVISION = "workspace-assistance-purpose-specific-v2"
CITED_REVISION = "workspace-assistance-cited-sections-v3"
REVISION = "workspace-assistance-visible-bounds-v5"
RESEARCH_REVISION = "workspace-assistance-evidence-request-codes-v4"
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


ClaimId = Literal["c1", "c2", "c3", "c4", "c5", "c6"]
ResponsePurpose = Literal["single_paper", "research_comparison"]


def response_purpose(mode: str, catalog: dict[str, Any]) -> ResponsePurpose:
    """Only Research with at least two selected works offers cross-source prose.

    Within-paper contrasts belong in attributed, cited claims in either mode.
    A second version/passage of the same work is not a second source.
    """
    works = {ref["work_id"] if isinstance(ref, dict) else ref.work_id for ref in catalog.values()}
    return "research_comparison" if mode == "research" and len(works) >= 2 else "single_paper"


class AssistanceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim_id: ClaimId = Field(description="Unique ID of this emitted claim, c1 through c6.")
    text: str = Field(min_length=1, max_length=360)
    handles: tuple[str, ...] = Field(
        min_length=1,
        max_length=3,
        description="Selected evidence handles (u...), never claim IDs. Each passage must support this claim.",
    )
    required_scope: Literal["abstract", "excerpt", "full_text"] = "abstract"


class SinglePaperDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claims: tuple[AssistanceClaim, ...] = Field(max_length=MAX_CLAIMS)
    background: str = Field(max_length=360)
    assumptions: tuple[str, ...] = Field(max_length=3)
    gaps: tuple[str, ...] = Field(min_length=1, max_length=3)
    questions: tuple[str, ...] = Field(min_length=1, max_length=3)
    proposal: str = Field(max_length=360)
    abstention: str | None = Field(max_length=180)

    @model_validator(mode="after")
    def bounded(self) -> SinglePaperDraft:
        ids = {c.claim_id for c in self.claims}
        if len(ids) != len(self.claims):
            raise ValueError("claim_or_comparison_basis_mismatch")
        if not self.claims and not (self.abstention or "").strip():
            raise ValueError("claims_or_abstention_required")
        if any(not c.text.strip() or len(set(c.handles)) != len(c.handles) for c in self.claims):
            raise ValueError("blank_claim_or_duplicate_handle")
        if any(
            not x.strip() or len(x) > 180 for x in (*self.assumptions, *self.gaps, *self.questions)
        ):
            raise ValueError("invalid_bounded_explanation")
        if len(self.model_dump_json().encode()) > MAX_DRAFT_BYTES:
            raise ValueError("assistance_response_too_large")
        return self


class AssistanceDraft(SinglePaperDraft):
    """Cross-source comparison is applicable only to a sealed Research request."""

    comparison: str = Field(
        max_length=360,
        description="Cross-source interpretation grounded in comparison_basis, or empty when evidence is insufficient. All factual prose is checked.",
    )
    comparison_basis: tuple[ClaimId, ...] = Field(
        max_length=MAX_CLAIMS,
        description="IDs (c1...c6) of distinct claims emitted in claims, NOT evidence handles. A comparison needs independently cited claims from at least two selected works; otherwise use an empty comparison and basis.",
    )

    @model_validator(mode="after")
    def comparison_references(self) -> AssistanceDraft:
        ids = {claim.claim_id for claim in self.claims}
        if set(self.comparison_basis) - ids or len(set(self.comparison_basis)) != len(
            self.comparison_basis
        ):
            raise ValueError("claim_or_comparison_basis_mismatch")
        if self.comparison.strip() and len(self.comparison_basis) < 2:
            raise ValueError("comparison_requires_separate_evidence_claims")
        if not self.comparison.strip() and self.comparison_basis:
            raise ValueError("comparison_basis_without_comparison")
        return self


class CitedSinglePaperDraft(BaseModel):
    """All explanatory statements are scored claims; sections only point to IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    claims: tuple[AssistanceClaim, ...] = Field(max_length=MAX_CLAIMS)
    background_claims: tuple[ClaimId, ...] = Field(
        max_length=MAX_CLAIMS,
        description="IDs of emitted, cited claims to display as background. No free factual prose.",
    )
    assumption_claims: tuple[ClaimId, ...] = Field(
        max_length=MAX_CLAIMS,
        description="IDs of emitted, cited claims describing source assumptions. Empty if unavailable.",
    )
    limitation_claims: tuple[ClaimId, ...] = Field(
        max_length=MAX_CLAIMS,
        description="IDs of emitted, cited claims describing substantive limitations.",
    )
    gaps: tuple[str, ...] = Field(
        min_length=1,
        max_length=3,
        description="Procedural requests for missing evidence, not scientific findings or assumptions.",
    )
    questions: tuple[str, ...] = Field(
        min_length=1,
        max_length=3,
        description="Neutral questions. Do not presuppose gains, causes or findings. Ask whether evidence establishes them.",
    )
    proposal: str = Field(
        max_length=360,
        description="Procedural proposed next action, never a finding. Avoid presupposed results.",
    )
    abstention: str | None = Field(
        max_length=180,
        description="Evidence insufficiency, not an unsupported scientific explanation.",
    )

    @model_validator(mode="after")
    def bounded(self) -> CitedSinglePaperDraft:
        ids = {c.claim_id for c in self.claims}
        refs = (self.background_claims, self.assumption_claims, self.limitation_claims)
        if len(ids) != len(self.claims) or any(set(r) - ids or len(set(r)) != len(r) for r in refs):
            raise ValueError("claim_or_section_reference_mismatch")
        if not self.claims and not (self.abstention or "").strip():
            raise ValueError("claims_or_abstention_required")
        if any(not c.text.strip() or len(set(c.handles)) != len(c.handles) for c in self.claims):
            raise ValueError("blank_claim_or_duplicate_handle")
        if any(not x.strip() or len(x) > 180 for x in (*self.gaps, *self.questions)):
            raise ValueError("invalid_bounded_explanation")
        if len(self.model_dump_json().encode()) > MAX_DRAFT_BYTES:
            raise ValueError("assistance_response_too_large")
        return self


class CitedAssistanceDraft(CitedSinglePaperDraft):
    comparison_claims: tuple[ClaimId, ...] = Field(
        max_length=MAX_CLAIMS,
        description="IDs of scored comparison claims. State any agreement, difference or compatibility in claims with separate evidence citations.",
    )
    comparison_basis: tuple[ClaimId, ...] = Field(
        max_length=MAX_CLAIMS,
        description="Distinct emitted claim IDs providing independent source bases from at least two works. Never evidence handles. Empty with no comparison.",
    )

    @model_validator(mode="after")
    def comparison_references(self) -> CitedAssistanceDraft:
        ids = {c.claim_id for c in self.claims}
        if any(
            set(r) - ids or len(set(r)) != len(r)
            for r in (self.comparison_claims, self.comparison_basis)
        ):
            raise ValueError("claim_or_comparison_basis_mismatch")
        if self.comparison_claims and len(self.comparison_basis) < 2:
            raise ValueError("comparison_requires_separate_evidence_claims")
        if not self.comparison_claims and self.comparison_basis:
            raise ValueError("comparison_basis_without_comparison")
        return self


# Research uses bounded codes; Learn retains prose with visible local bounds.
# Both prospective schemas change; completed v6 evidence stays historical.
EvidenceRequest = Literal[
    "methods", "evaluation", "ablations", "full_text", "counterevidence", "source_scope"
]
EVIDENCE_REQUESTS = {
    "methods": "Request the original methods and implementation details.",
    "evaluation": "Request evaluation sections, benchmarks, baselines and metrics from each selected source.",
    "ablations": "Request ablations and controlled comparisons from each selected source.",
    "full_text": "Request the relevant full-text sections before drawing further conclusions.",
    "counterevidence": "Search for and inspect evidence that could challenge the interpretation.",
    "source_scope": "Inspect source access scope and unavailable passages before making broader claims.",
}


def render_gaps(gaps: Sequence[str]) -> list[str]:
    """Render known procedural codes locally; preserve historical prose verbatim."""
    return [EVIDENCE_REQUESTS.get(value, value) for value in gaps]


class VisibleSinglePaperDraft(CitedSinglePaperDraft):
    """All local semantic limits: unique claim IDs, unique section references,
    nonblank claim texts and unique selected handles; claims or a nonblank
    abstention; entire response at most 8000 UTF-8 bytes, including JSON whitespace; normalized JSON also at most 8000 bytes. Each gap/question is
    nonblank and at most 180 Unicode characters. Every substantive statement
    must be a cited scored claim; procedural prose is checked too.
    """

    gaps: tuple[str, ...] = Field(
        min_length=1,
        max_length=3,
        description="One to three nonblank procedural evidence requests, each at most 180 Unicode characters. No scientific findings or presupposed results.",
    )
    questions: tuple[str, ...] = Field(
        min_length=1,
        max_length=3,
        description="One to three nonblank neutral questions, each at most 180 Unicode characters. No presupposed findings.",
    )


class EvidenceRequestDraft(CitedAssistanceDraft):
    """Research-only successor; no free text for procedural evidence requests.

    Local-only semantic constraints: unique c1-c6 IDs and section references;
    nonblank claims, unique selected handles; independently cited sources for
    comparison; claims or nonblank abstention; entire response at most 8000 UTF-8 bytes including whitespace; normalized JSON also at most 8000 bytes.
    Questions must be nonblank, at most 180 Unicode characters each. All prose
    is checked for hidden factual assertions. No code bypasses factual review.
    """

    gaps: tuple[EvidenceRequest, ...] = Field(
        min_length=1,
        max_length=3,
        description="One to three evidence-request codes, rendered locally as procedural requests. Use evaluation for missing benchmarks/baselines/metrics; ablations for missing controlled comparisons. Never emit prose here.",
    )
    questions: tuple[str, ...] = Field(
        min_length=1,
        max_length=3,
        description="One to three neutral, nonblank questions, each at most 180 Unicode characters. No presupposed findings; all substantive prose is checked.",
    )


def contract_revision(purpose: ResponsePurpose) -> str:
    return RESEARCH_REVISION if purpose == "research_comparison" else REVISION


def response_model(
    handles: Sequence[str],
    *,
    purpose: ResponsePurpose = "research_comparison",
    revision: str | None = None,
) -> type[SinglePaperDraft] | type[CitedSinglePaperDraft]:
    revision = revision or contract_revision(purpose)
    # json_schema_extra keeps even a singleton enum after the SDK transform.
    selected = sorted(set(handles))
    if not selected or len(selected) > MAX_SELECTED_UNITS:
        raise ValueError("select_one_to_eight_coherent_units")
    if purpose not in {"single_paper", "research_comparison"}:
        raise ValueError("invalid_response_purpose")
    if revision not in {
        REVISION,
        CITED_REVISION,
        RESEARCH_REVISION,
        LEGACY_REVISION,
        "workspace-assistance-coherent-multicitation-v1",
    }:
        raise ValueError("unsupported_assistance_contract_revision")
    legacy = revision not in {REVISION, CITED_REVISION, RESEARCH_REVISION}
    identity = digest([selected, purpose] if legacy else [selected, purpose, revision])[7:23]
    factory = cast(Callable[[str, dict[str, str]], type[StrEnum]], StrEnum)
    handle_type = factory(
        "D5Evidence_" + identity, {f"U{i}": key for i, key in enumerate(selected)}
    )
    claim = create_model(
        "D5Claim_" + identity,
        __base__=AssistanceClaim,
        handles=(
            GenericAlias(tuple, (handle_type, Ellipsis)),
            Field(
                min_length=1,
                max_length=3,
                description=AssistanceClaim.model_fields["handles"].description,
            ),
        ),
    )
    return create_model(
        "D5Draft_" + identity,
        __doc__=(
            VisibleSinglePaperDraft.__doc__
            if purpose == "single_paper"
            else EvidenceRequestDraft.__doc__
        )
        if revision in {REVISION, RESEARCH_REVISION}
        else None,
        __base__=(SinglePaperDraft if purpose == "single_paper" else AssistanceDraft)
        if legacy
        else (
            VisibleSinglePaperDraft
            if purpose == "single_paper" and revision == REVISION
            else CitedSinglePaperDraft
            if purpose == "single_paper"
            else EvidenceRequestDraft
            if revision == RESEARCH_REVISION
            else CitedAssistanceDraft
        ),
        claims=(GenericAlias(tuple, (claim, Ellipsis)), Field(max_length=MAX_CLAIMS)),
    )


def schemas(
    handles: Sequence[str],
    *,
    purpose: ResponsePurpose = "research_comparison",
    revision: str | None = None,
) -> dict[str, Any]:
    model = response_model(handles, purpose=purpose, revision=revision)
    return {"local": model.model_json_schema(), "wire": transform_schema(model)}


def resolve_draft(
    payload: dict[str, Any],
    catalog: dict[str, EvidenceRef],
    materials: Sequence[SourceMaterial],
    *,
    purpose: ResponsePurpose = "research_comparison",
    revision: str | None = None,
) -> tuple[SinglePaperDraft | CitedSinglePaperDraft, tuple[ResearchClaim, ...]]:
    draft = response_model(list(catalog), purpose=purpose, revision=revision).model_validate(
        payload
    )
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
    comparison = (isinstance(draft, AssistanceDraft) and bool(draft.comparison)) or (
        isinstance(draft, CitedAssistanceDraft) and bool(draft.comparison_claims)
    )
    if comparison and isinstance(draft, (AssistanceDraft, CitedAssistanceDraft)):
        by_id = {claim.claim_id: claim for claim in claims}
        compared_sources = {
            ref.work_id for key in draft.comparison_basis for ref in by_id[key].evidence
        }
        if len(compared_sources) < 2:
            raise ValueError("comparison_requires_two_separately_cited_sources")
    return draft, tuple(claims)
