"""Current, version-specific reading availability, separate from source metadata.

Derived summaries never rewrite an immutable provider observation. A metadata
record may acquire independently retained PDF excerpts; an empty/failed parser
result is not available reading material. Frozen Radar pages retain the summary
observed on their first request until the user refreshes that result set.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

PRIORITY = {"full_text": 0, "excerpt": 1, "abstract": 2, "metadata": 3}


def reading_availability(
    version: Mapping[str, Any], materials: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    retained = []
    for material in materials:
        if (
            material.get("work_id") != version["work_id"]
            or material.get("version_id") != version["version_id"]
            or material.get("scope") not in {"abstract", "excerpt", "full_text"}
            or material.get("quality") in {None, "empty", "failed"}
        ):
            continue
        spans = [
            span
            for span in material.get("spans", [])
            if span.get("work_id") == version["work_id"]
            and span.get("version_id") == version["version_id"]
            and span.get("material_id") == material.get("material_id")
            and isinstance(span.get("text"), str)
            and span["text"].strip()
        ]
        if not spans:
            continue
        count = material.get("page_count")
        is_pdf = type(count) is int and count > 0
        first = next(
            (span for span in spans if type(span.get("page")) is int and span["page"] > 0), None
        )
        anchor = None
        if is_pdf and first:
            anchor = f"material:{material['material_id']}:page:{first['page']}:{first['start']}:{first['end']}"
        retained.append(
            {
                "material_id": material["material_id"],
                "version_id": version["version_id"],
                "scope": material["scope"],
                "format": "pdf" if is_pdf else "text",
                "quality": material["quality"],
                "complete": bool(material.get("complete")),
                "page_count": count if is_pdf else None,
                "retained_pages": material.get("page_numbers")
                or (list(range(1, len(material.get("pages", [])) + 1)) if is_pdf else []),
                "first_anchor": anchor,
                "warnings": list(material.get("warnings", [])),
            }
        )
    retained.sort(
        key=lambda value: (PRIORITY[value["scope"]], value["format"] != "pdf", value["material_id"])
    )
    scopes = {value["scope"] for value in retained}
    # The observed abstract/feed text itself remains available for manual reading
    # even if an older installation has not populated its material index.
    if str(version.get("abstract") or "").strip():
        scopes.add("excerpt" if version.get("access_state") == "excerpt" else "abstract")
    if not scopes:
        scopes.add("metadata")
    available = sorted(scopes, key=PRIORITY.__getitem__)
    return {
        "reading_access_state": available[0],
        "available_scopes": available,
        "retained_materials": retained,
    }
