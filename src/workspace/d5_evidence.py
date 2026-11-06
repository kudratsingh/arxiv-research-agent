"""Deterministic evidence selection, never a semantic/extraction qualification.

Every returned quotation is an unchanged page-local Unicode range. Headers and
known extraction failures are inspected/labelled, never rewritten as source text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from src.workspace.assistance_contract import coherent_units
from src.workspace.grounding import EvidenceRef
from src.workspace.material import SourceMaterial

POLICY = "d5-scientific-coherent-selection-v1"


def assess(ref: EvidenceRef, material: SourceMaterial) -> dict[str, Any]:
    text = ref.quote
    words = re.findall(r"[A-Za-z]{2,}", text)
    flags = []
    if len(words) < 12:
        flags.append("too_little_scientific_context")
    if text and sum(c.isalpha() for c in text) / len(text) < 0.4:
        flags.append("dense_symbols_or_layout_artifacts")
    if re.match(r"^(Preprint\.?|Published as a conference paper|arXiv:)", text):
        flags.append("front_matter_or_header")
    if "@" in text[:400] or len(re.findall(r"https?://", text)) > 2:
        flags.append("author_or_link_block")
    for warning in material.warnings:
        bad = any(
            term in warning.lower()
            for term in ("corrupt", "interleav", "unreliable", "unqualified")
        )
        pages = {int(n) for n in re.findall(r"original\s*page\s*(\d+)", warning, re.I)}
        if bad and ref.page in pages:
            flags.append("known_page_extraction_failure")
    return {
        "eligible": not flags,
        "flags": sorted(set(flags)),
        "basis": "Bounded heuristic, not human extraction review or factual support",
    }


def select(
    materials: Sequence[SourceMaterial], *, question: str, max_units: int = 2
) -> dict[str, Any]:
    terms = set(re.findall(r"[a-z]{3,}", question.lower()))
    options = []
    rejected: list[dict[str, Any]] = []
    for material in materials:
        try:
            units = coherent_units([material], {s.span_id for s in material.spans})
        except ValueError:
            rejected.append({"material_id": material.material_id, "reason": "no_coherent_unit"})
            continue
        for key, ref in units.items():
            quality = assess(ref, material)
            if not quality["eligible"]:
                rejected.append({"unit_id": key, "reference": asdict(ref), "quality": quality})
                continue
            overlap = len(terms & set(re.findall(r"[a-z]{3,}", ref.quote.lower())))
            options.append(
                (
                    -(1 if ref.scope == "abstract" else 0),
                    -overlap,
                    ref.page or 0,
                    ref.start,
                    key,
                    ref,
                    quality,
                )
            )
    options.sort(key=lambda x: x[:5])
    chosen = options[:max_units]
    return {
        "policy": POLICY,
        "selected": [{"id": x[4], "reference": asdict(x[5]), "quality": x[6]} for x in chosen],
        "rejected": rejected,
        "eligible_units": len(options),
        "source_contacts": 0,
    }
