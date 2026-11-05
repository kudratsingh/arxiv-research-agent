"""Small model outputs; exact evidence is always reconstructed from sealed spans.

Handles identify bounded, deterministic slices, not a substring search. Identical
text on different pages/versions stays distinct; offsets are Unicode code points.
No model-supplied quote, source ID, version, offset or section can become provenance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from enum import StrEnum
from types import GenericAlias
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from src.workspace.grounding import EvidenceRef, evidence_ref
from src.workspace.material import SourceMaterial

CONTRACT_REVISION = "sealed-single-selected-evidence-handle-v2"
SLICE_CHARS = 240
MAX_HANDLES = 200


class HandleClaim(BaseModel):
    """Generic non-dispatched template; the request factory closes its handle enum."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    # The SDK strips regex patterns from the wire. This finite enum survives.
    claim_id: Literal["c1", "c2", "c3"]
    text: str = Field(min_length=1, max_length=240)
    evidence_handle: str
    section: Literal["overview", "method", "assumptions", "comparison"] = "overview"


class CompactDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["summary", "deep_dive"]
    title: str = Field(min_length=1, max_length=96)
    claims: tuple[HandleClaim, ...] = Field(max_length=3)
    abstention: str | None = Field(default=None, max_length=160)
    question: str | None = Field(default=None, max_length=120)
    proposal: str | None = Field(default=None, max_length=240)
    limitation: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def bounds(self) -> CompactDraft:
        if not self.claims and not (self.abstention and self.abstention.strip()):
            raise ValueError("claims_or_explicit_abstention_required")
        if len({c.claim_id for c in self.claims}) != len(self.claims):
            raise ValueError("duplicate_claim_id")
        if self.kind == "summary" and (
            len(self.claims) > 2
            or any(c.section != "overview" for c in self.claims)
        ):
            raise ValueError("summary_bounds_or_sections")
        if any(not c.text.strip() for c in self.claims):
            raise ValueError("invalid_claim_text")
        limit = 1800 if self.kind == "summary" else 2800
        if len(json.dumps(self.model_dump(mode="json"), ensure_ascii=False).encode()) > limit:
            raise ValueError("compact_response_byte_limit")
        return self


class SummaryClaim(HandleClaim):
    # A single Literal emits const, which the SDK also strips. Keep its supported
    # enum explicit so the provider cannot validly choose a study-only section.
    section: Literal["overview"] = Field(
        default="overview", json_schema_extra={"enum": ["overview"]}
    )


class SummaryDraft(CompactDraft):
    kind: Literal["summary"] = Field(json_schema_extra={"enum": ["summary"]})
    claims: tuple[SummaryClaim, ...] = Field(max_length=2)


class ExcerptStudyDraft(CompactDraft):
    kind: Literal["deep_dive"] = Field(json_schema_extra={"enum": ["deep_dive"]})


def draft_schema(kind: str, selected_handles: Sequence[str]) -> type[CompactDraft]:
    """Exact local/wire response model, closed over this request's selected IDs.

    Base draft/claim classes are non-dispatched templates. Sorted enum members
    and catalog-derived names make schema identity independent of call order.
    Even a one-element enum remains an enum after the SDK's const stripping.
    """
    bases: dict[str, tuple[type[CompactDraft], type[HandleClaim], int]] = {"summary": (SummaryDraft, SummaryClaim, 2),
             "deep_dive": (ExcerptStudyDraft, HandleClaim, 3)}
    if kind not in bases:
        raise ValueError("invalid_draft_kind")
    if any(not isinstance(h, str) or not h.strip() for h in selected_handles):
        raise ValueError("invalid_selected_handle_enum")
    handles = tuple(sorted(set(selected_handles)))
    if not handles or len(handles) > MAX_HANDLES:
        raise ValueError("invalid_selected_handle_enum")
    identity = hashlib.sha256(json.dumps([kind, handles]).encode()).hexdigest()[:20]
    # Dynamic catalog values cannot be declared as a static enum class.
    enum_factory = cast(Callable[[str, dict[str, str]], type[StrEnum]], StrEnum)
    handle_type = enum_factory("SelectedEvidence_" + identity, {f"E{i}": h for i, h in enumerate(handles)})
    draft_base, claim_base, maximum = bases[kind]
    claim_model = create_model("SelectedClaim_" + identity, __base__=claim_base,
                               evidence_handle=(handle_type, ...))
    return create_model("SelectedDraft_" + identity, __base__=draft_base,
                        claims=(GenericAlias(tuple, (claim_model, Ellipsis)), Field(max_length=maximum)))


def evidence_catalog(
    materials: Sequence[SourceMaterial], selected_ids: set[str]
) -> dict[str, EvidenceRef]:
    catalog: dict[str, EvidenceRef] = {}
    found: set[str] = set()
    for material in materials:
        for span in material.spans:
            if span.span_id not in selected_ids:
                continue
            found.add(span.span_id)
            for start in range(span.start, span.end, SLICE_CHARS):
                ref = evidence_ref(material, span, start=start, end=min(start + SLICE_CHARS, span.end))
                encoded = json.dumps(asdict(ref), sort_keys=True, ensure_ascii=False).encode()
                handle = "e" + hashlib.sha256(encoded).hexdigest()[:12]
                if handle in catalog and catalog[handle] != ref:
                    raise ValueError("evidence_handle_collision")
                catalog[handle] = ref
    if found != selected_ids or not catalog or len(catalog) > MAX_HANDLES:
        raise ValueError("invalid_or_excessive_selected_evidence")
    return catalog


def catalog_wire(catalog: dict[str, EvidenceRef]) -> list[dict[str, object]]:
    # Source identities are supplied once in the request's source metadata.
    groups = {key: "g" + str(i+1) for i, key in enumerate(dict.fromkeys(
        (ref.material_id, ref.span_id) for ref in catalog.values()))}
    return [
        {"handle": key, "text": ref.quote, "material_id": ref.material_id,
         "scope": ref.scope, "page": ref.page,
         "group": groups[(ref.material_id, ref.span_id)], "start": ref.start, "end": ref.end}
        for key, ref in catalog.items()
    ]


def resolve_handles(catalog: dict[str, EvidenceRef], handles: Sequence[str],
                    materials: Sequence[SourceMaterial]) -> tuple[EvidenceRef, ...]:
    """Coalesce only adjacent slices of one parent span; never bridge a gap.

    The generic grounding validator correctly forbids duplicate parent-span
    refs. A pair of contiguous model-selected handles is one exact quotation,
    not duplicate evidence and not permission to expand the selected text.
    """
    groups: dict[tuple[str, str], list[EvidenceRef]] = {}
    for handle in handles:
        ref = catalog[handle]
        groups.setdefault((ref.material_id, ref.span_id), []).append(ref)
    result = []
    for (material_id, span_id), refs in groups.items():
        refs.sort(key=lambda r: r.start)
        if any(a.end != b.start for a, b in zip(refs, refs[1:], strict=False)):
            raise ValueError("noncontiguous_or_overlapping_evidence_handles")
        material = next(m for m in materials if m.material_id == material_id)
        span = next(s for s in material.spans if s.span_id == span_id)
        combined = evidence_ref(material, span, start=refs[0].start, end=refs[-1].end)
        if combined.quote != "".join(ref.quote for ref in refs):
            raise ValueError("selected_handle_quote_drift")
        result.append(combined)
    return tuple(result)
