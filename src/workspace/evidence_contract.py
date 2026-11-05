"""Small model outputs; exact evidence is always reconstructed from sealed spans.

Handles identify bounded, deterministic slices, not a substring search. Identical
text on different pages/versions stays distinct; offsets are Unicode code points.
No model-supplied quote, source ID, version, offset or section can become provenance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.workspace.grounding import EvidenceRef, evidence_ref
from src.workspace.material import SourceMaterial

CONTRACT_REVISION = "sealed-evidence-handles-v1"
SLICE_CHARS = 240
MAX_HANDLES = 200


class HandleClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    claim_id: str = Field(pattern=r"^c[1-3]$")
    text: str = Field(min_length=1, max_length=180)
    handles: tuple[str, ...] = Field(min_length=1, max_length=2)
    section: Literal["overview", "method", "assumptions", "comparison"] = "overview"


class CompactDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["summary", "deep_dive"]
    title: str = Field(min_length=1, max_length=96)
    claims: tuple[HandleClaim, ...] = Field(max_length=3)
    abstention: str | None = Field(default=None, max_length=160)
    question: str | None = Field(default=None, max_length=120)
    proposal: str | None = Field(default=None, max_length=160)
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
        if any(len(set(c.handles)) != len(c.handles) or not c.text.strip() for c in self.claims):
            raise ValueError("invalid_claim_or_duplicate_handle")
        limit = 1800 if self.kind == "summary" else 2800
        if len(json.dumps(self.model_dump(mode="json"), ensure_ascii=False).encode()) > limit:
            raise ValueError("compact_response_byte_limit")
        return self


class SummaryDraft(CompactDraft):
    kind: Literal["summary"]
    claims: tuple[HandleClaim, ...] = Field(max_length=2)


class ExcerptStudyDraft(CompactDraft):
    kind: Literal["deep_dive"]


def draft_schema(kind: str) -> type[CompactDraft]:
    if kind == "summary":
        return SummaryDraft
    if kind == "deep_dive":
        return ExcerptStudyDraft
    raise ValueError("invalid_draft_kind")


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
    return [
        {"handle": key, "text": ref.quote, "material_id": ref.material_id,
         "scope": ref.scope, "page": ref.page}
        for key, ref in catalog.items()
    ]
