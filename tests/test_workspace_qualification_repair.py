"""Wire-schema and selected-passage regressions; synthetic PDF, never provider quality."""

from __future__ import annotations

import io
import json
from dataclasses import asdict

import httpx
import pytest
from jsonschema import Draft202012Validator, ValidationError
from psycopg.types.json import Jsonb
from reportlab.pdfgen import canvas

from src.workspace import provider_adapter as p
from src.workspace.grounding import evidence_ref
from src.workspace.material import extract_pdf
from tests import test_workspace_provider_adapter as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def react(store):
    # Real work/version identifiers; explicitly synthetic three-page extraction.
    item = support.support.support.ingest(
        store,
        work_id="arxiv:2210.03629",
        version_id="arxiv:2210.03629:v3",
        title="ReAct: synthetic selected-passage regression",
        access_state="metadata",
    )
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, invariant=True)
    for page in (1, 2, 3):
        pdf.drawString(72, 720, f"Synthetic ReAct page {page}: evaluation with a fixed baseline.")
        pdf.showPage()
    pdf.save()
    material = extract_pdf(
        buffer.getvalue(), work_id=item["work_id"], version_id=item["version_id"]
    )
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_material VALUES (%s,%s,%s,%s,%s)",
            (
                material.material_id,
                material.version_id,
                material.content_hash,
                material.scope,
                Jsonb(asdict(material)),
            ),
        )
    page3 = next(s for s in material.spans if s.page == 3)
    inputs = p.prepare(store, "a", "deep_dive", [material.material_id], span_ids=[page3.span_id])
    support.approve(store, inputs, source_scopes=["full_text"])
    transport = support.Transport(store, inputs, decision="unsupported")
    adapter = p.QualificationAdapter(store, "a", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start("one", "0.5")["id"]
    return adapter, transport, job, material


def outside(value, material):
    draft = json.loads(value["content"][0]["text"])
    draft["claims"][0]["evidence"] = [asdict(evidence_ref(material, material.spans[0]))]
    return {**value, "content": [{"type": "text", "text": json.dumps(draft)}]}


@pytest.mark.parametrize("stage", ["draft", "repair", "checker_request", "checker_processing"])
async def test_page3_only_approval_refuses_valid_page1_reference_at_every_stage(store, stage):
    adapter, transport, job, material = react(store)
    assert material.spans[0].page == 1
    if stage != "draft":
        await adapter.advance(job)
    if stage == "repair":
        await adapter.advance(job)  # first checker asks for repair
    if stage in {"draft", "repair"}:
        transport.change = lambda v: outside(v, material)
    else:

        def alter_persisted_draft():
            with store.pool.connection() as conn:
                data = conn.execute(
                    "SELECT data FROM workspace_generation_jobs WHERE id=%s", (job,)
                ).fetchone()[0]
                draft = data["adapter"]["steps"][-1]["output"]
                draft["claims"][0]["evidence"] = [asdict(evidence_ref(material, material.spans[0]))]
                conn.execute(
                    "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job)
                )

        if stage == "checker_request":
            alter_persisted_draft()
        else:
            original = transport.__call__

            async def changed(request):
                response = await original(request)
                if request.url.path == "/v1/messages":
                    alter_persisted_draft()
                return response

            adapter.transport = httpx.MockTransport(changed)
    before = len(transport.calls)
    with pytest.raises(p.AdmissionError, match="unselected_span"):
        await adapter.advance(job)
    assert len(transport.calls) == before + (0 if stage == "checker_request" else 2)
    assert adapter.snapshot(job)["result"] is None
    # Draft/repair cannot reach an additional checker contact.
    if stage in {"draft", "repair"}:
        assert json.loads(transport.calls[-1][1]["messages"][0]["content"])["stage"] == stage


@pytest.mark.parametrize("alter", ["version", "offset", "quote"])
async def test_selected_page_still_requires_exact_version_offsets_and_quote(store, alter):
    adapter, transport, job, material = react(store)

    def change(value):
        draft = json.loads(value["content"][0]["text"])
        ref = draft["claims"][0]["evidence"][0]
        if alter == "version":
            ref["version_id"] += ":wrong"
        elif alter == "offset":
            ref["end"] += 1
        else:
            ref["quote"] += " invented"
        return {**value, "content": [{"type": "text", "text": json.dumps(draft)}]}

    transport.change = change
    with pytest.raises(ValueError):
        await adapter.advance(job)
    assert len(transport.calls) == 2 and adapter.snapshot(job)["result"] is None


@pytest.mark.parametrize("kind", ["summary", "deep_dive"])
async def test_realistic_wire_valid_draft_repair_and_check_round_trip(store, kind):
    adapter, transport, job = support.setup(store, kind=kind, decision="unsupported")
    while adapter.snapshot(job)["state"] == "running":
        result = await adapter.advance(job)
    assert result["state"] == "ready" and len(transport.calls) == 8
    stages = [
        json.loads(body["messages"][0]["content"])["stage"]
        for path, body in transport.calls
        if path == "/v1/messages"
    ]
    assert stages == ["draft", "check", "repair", "check"]
    assert result["result"]["experiment_only"] and result["result"]["draft"]["sections"]
    assert not result["result"]["checker_qualified"]


async def test_wire_and_local_semantics_reject_the_old_mapping_and_invalid_sections(store):
    adapter, transport, job = support.setup(store)
    wire = adapter.request(job)
    await adapter.advance(job)
    valid = adapter.snapshot(job)["steps"][0]["output"]
    validator = Draft202012Validator(wire["body"]["output_config"]["format"]["schema"])
    for sections in ({}, {"overview": ["c1"]}, []):
        invalid = {**valid, "sections": sections}
        with pytest.raises(ValidationError):
            validator.validate(invalid)
        with pytest.raises(ValueError):
            p.StudyDraft.model_validate(invalid)
    for sections in (
        [{"name": "overview", "claim_ids": ["missing"]}],
        [{"name": "method", "claim_ids": ["c1"]}],
        [{"name": "overview", "claim_ids": ["c1"]}] * 2,
    ):
        invalid = {**valid, "sections": sections}
        validator.validate(invalid)  # Semantic cross-references remain a local check.
        with pytest.raises(ValueError):
            p.StudyDraft.model_validate(invalid)
