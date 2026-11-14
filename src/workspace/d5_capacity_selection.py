"""Qualification-only persisted-source selection, independent of fake preview caps."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import Field

from src.workspace.admission import AdmissionError
from src.workspace.assistance import AssistanceInput, producer_binding
from src.workspace.assistance_contract import coherent_units, response_purpose
from src.workspace.assistance_coverage import RequestedPart
from src.workspace.assistance_policy import CoverageTaskContext
from src.workspace.context_schemas import ProjectData, ProjectWrite
from src.workspace.context_store import WorkspaceContext
from src.workspace.d5_capacity_policy import (
    ASSISTANCE_REVISION,
    MAX_SELECTED_UNITS,
    POLICY,
    protect,
)
from src.workspace.executor import FakeExecutor


class QualificationSelection(AssistanceInput):
    """Public legacy defaults stay fixed; this DTO never dispatches generation."""
    span_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_SELECTED_UNITS)
    unit_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_SELECTED_UNITS)
    follow_up: str = Field(default="", max_length=4000)


def build(store: Any, owner: str, key: str, mode: Any, question: str, units: dict[str, Any], *, intent: Any = "answer") -> dict[str, Any]:
    from src.workspace.admission import _digest
    if not 1 <= len(units) <= MAX_SELECTED_UNITS:
        raise AdmissionError("capacity_selected_unit_limit")
    protect(units, POLICY["max_selected_evidence_utf8_bytes"], code="capacity_selected_evidence_bytes_exceeded")
    refs = list(units.values())
    material_ids = list(dict.fromkeys(r["material_id"] for r in refs))
    span_ids = list(dict.fromkeys(r["span_id"] for r in refs))
    if len(material_ids) > POLICY["max_materials"]:
        raise AdmissionError("capacity_material_limit")
    question = question.strip()
    if not question:
        raise AdmissionError("request_question_required")
    pid = "project-" + _digest(key)[:32] if mode == "research" else None
    parts = (
        RequestedPart(id="p1", request=question, kind="comparison" if intent == "comparison" else "answer"),
        RequestedPart(id="p2", request="State separately cited source facts and retain study scope, comparator, metric definition and conditions.", kind="source_note"),
        RequestedPart(id="p3", request="Identify missing evidence or required details without inventing findings.", kind="answer"),
    )
    selection = QualificationSelection(
        mode=mode, work_id=refs[0]["work_id"], version_id=refs[0]["version_id"],
        material_ids=tuple(material_ids), span_ids=tuple(span_ids), unit_ids=tuple(units),
        follow_up=question, project_id=pid, project_revision=1 if pid else None,
        task_context=CoverageTaskContext(intent=intent, requested_parts=parts),
    )
    if pid:
        WorkspaceContext(store).write_project(owner, ProjectWrite(id=pid, revision=0, request_id="freeze-" + key, data=ProjectData(title="Experimental · " + key, question=question, scope="Frozen retained public sources only", constraints="No private notes/history, source expansion or everyday generation")))
    with store.pool.connection() as conn:
        material = FakeExecutor(store)._sources(conn, owner, material_ids)
        catalog = coherent_units(material, set(span_ids))
        if any(k not in catalog or asdict(catalog[k]) != v for k, v in units.items()):
            raise AdmissionError("d5_selected_evidence_drift")
        version_hashes = {}
        for ref in refs:
            row = conn.execute("SELECT data->>'content_hash' FROM workspace_versions WHERE work_id=%s AND version_id=%s", (ref["work_id"], ref["version_id"])).fetchone()
            if not row:
                raise AdmissionError("d5_source_version_drift")
            version_hashes[ref["version_id"]] = row[0]
    sources = [
        {"material_id": m.material_id, "work_id": m.work_id, "version_id": m.version_id,
         "content_hash": m.content_hash, "source_hash": m.source_hash, "scope": m.scope,
         "parser_revision": m.parser_revision, "complete": m.complete, "quality": m.quality,
         "offset_basis": m.offset_basis, "page_count": m.page_count, "page_numbers": m.page_numbers,
         "warnings": list(m.warnings), "spans": [asdict(span) for span in m.spans if span.span_id in span_ids]}
        for m in material
    ]
    project = {"id": pid, "revision": 1, "question": question, "scope": "Frozen retained public sources only", "constraints": "No private notes/history, source expansion or everyday generation"} if pid else None
    value = {
        "schema_revision": ASSISTANCE_REVISION, "mode": "qualification_preview", "kind": "deep_dive",
        "assistance": selection.model_dump(mode="json"), "project_context": project,
        "selection": {"material_ids": material_ids, "span_ids": span_ids},
        "units": units, "sources": sources, "version_hashes": version_hashes,
        "source_version_hash": version_hashes[refs[0]["version_id"]],
        "response_purpose": response_purpose(mode, units),
        "producer": {"contract": ASSISTANCE_REVISION, "code": producer_binding()},
        "private_context": {"notes": False, "profile": False, "reading_history": False},
        "settings": {"temperature": None, "thinking": {"type": "between_tools"}, "effort": "medium", "structured_outputs": True, "max_repairs": 1},
        "stage_contracts": {"draft": {"role": "workflow"}, "repair": {"role": "workflow"}, "check": {"role": "checker"}},
    }
    protect(value, POLICY["internal_json_bytes"])
    return value
