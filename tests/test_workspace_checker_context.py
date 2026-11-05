"""V7 stage contexts: exact cited evidence, isolated SQL and MockTransport only."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from psycopg.types.json import Jsonb

from src.workspace import provider_adapter as p
from src.workspace import qualification, qualification_run
from src.workspace.admission import AdmissionError, _digest
from src.workspace.grounding import ClaimKind, claim_input_digest
from tests import test_workspace_provider_adapter as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration
FIXTURE = Path(__file__).parent / "fixtures/qualification_failures/sonnet55-v6-q02-checker-envelope.json"


def test_retained_failed_q02_context_keeps_every_claim_byte_without_duplicate_sources():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "9935d1a746e28e59102a0ca1f3da5b99a1200b7ee2c8a52c38f0e9a0a7cd1f35"
    retained = json.loads(raw)
    old = json.loads(retained["checker_count_body"]["messages"][0]["content"])
    assert retained["original_state"] == "failed" and retained["result_accepted"] is False
    assert retained["human_labels"] is None and retained["new_checker_messages"] == 0
    assert retained["reservation"]["unknown"] == "0"
    assert retained["draft_response"]["usage"]["input_tokens"] == 5567
    assert retained["draft_response"]["usage"]["output_tokens"] == 374
    assert retained["draft_response"]["stop_reason"] == "end_turn"
    settings = retained["sealed_input"]["settings"]
    assert settings["input_tokens"] == 8000 and settings["output_tokens"] == 1200
    assert retained["checker_count_response"]["input_tokens"] == 6715 > 8000 * 4 / 5
    new = p._checker_context(old["kind"], old["task"], old["claims"])
    assert set(new) == {"kind", "task", "private_context", "stage", "instructions", "claims"}
    assert new["claims"] == old["claims"]
    assert json.dumps(new["claims"], ensure_ascii=False, sort_keys=True).encode() == json.dumps(old["claims"], ensure_ascii=False, sort_keys=True).encode()
    assert new["private_context"] == old["private_context"]
    assert len(json.dumps(new, ensure_ascii=False, sort_keys=True).encode()) < len(json.dumps(old, ensure_ascii=False, sort_keys=True).encode())
    # Byte reduction is not a token estimate or evidence that a new count fits.
    assert "its own supplied evidence quotes" in new["instructions"]
    assert "another claim's evidence" in new["instructions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["summary", "deep_dive"])
async def test_exact_stage_wires_keep_original_selection_and_only_cited_checker_quotes(store, kind):
    first = ("Cited alpha. " * 180)[:2000]
    middle = ("UNSELECTED_BOUNDARY " * 150)[:2000]
    last = ("UNRELATED_SELECTED_BOUNDARY " * 100)[:2000]
    _, material, data = support.support.source(store, abstract=first + middle + last)
    selected = [data["spans"][index]["span_id"] for index in [0, 2]]
    inputs = p.prepare(store, "a", kind, [material], span_ids=selected, question="What does the cited source establish?")
    support.approve(store, inputs)
    transport = support.Transport(store, inputs, decision="unsupported")

    def revise(value):
        if json.loads(transport.calls[-1][1]["messages"][0]["content"])["stage"] == "repair":
            output = json.loads(value["content"][0]["text"])
            output["claims"][0]["text"] = "A revised synthetic statement requiring its own recheck."
            value = {**value, "content": [{"type": "text", "text": json.dumps(output)}]}
        return value

    transport.change = revise
    adapter = p.QualificationAdapter(store, "a", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start("one", "0.5")["id"]
    initial = None
    check_digests = []
    for stage in ["draft", "check", "repair", "check"]:
        wire = adapter.request(job)
        context = json.loads(wire["body"]["messages"][0]["content"])
        assert context["stage"] == stage and context["task"] == inputs.settings["research_task"]
        assert "UNSELECTED_BOUNDARY" not in json.dumps(context)
        if stage == "check":
            assert set(context) == {"kind", "task", "private_context", "stage", "instructions", "claims"}
            assert wire["body"]["system"] == p.CHECKER_SYSTEM
            assert "UNRELATED_SELECTED_BOUNDARY" not in json.dumps(context)
            draft = adapter._draft(adapter.snapshot(job)["steps"][-1]["output"])
            _, materials = adapter._context()
            expected = [{"claim": asdict(claim), "input_digest": claim_input_digest(claim, materials)}
                        for claim in draft.claims if claim.kind == ClaimKind.FACTUAL]
            assert context["claims"] == json.loads(json.dumps(expected))
            assert all(len(item["claim"]["evidence"]) == 1 and
                       len(item["claim"]["evidence"][0]["quote"]) <= 240 for item in context["claims"])
            check_digests.append(context["claims"][0]["input_digest"])
        else:
            assert wire["body"]["system"] == p.SYSTEM
            assert "UNRELATED_SELECTED_BOUNDARY" in json.dumps(context)
            if stage == "draft":
                initial = context
                assert "previous_output" not in context
            else:
                assert set(context) == {"kind", "task", "private_context", "stage", "sources", "evidence", "draft", "checks"}
                assert context["sources"] == initial["sources"] and context["evidence"] == initial["evidence"]
                steps = adapter.snapshot(job)["steps"]
                assert context["draft"] == steps[0]["output"]
                assert context["checks"] == steps[1]["output"]["checks"]
                assert "grounding" not in context and "previous_output" not in context
        before = len(transport.calls)
        await adapter.advance(job)
        paired = transport.calls[before:]
        assert [path for path, _ in paired] == ["/v1/messages/count_tokens", "/v1/messages"]
        assert paired[0][1] == {k: v for k, v in wire["body"].items() if k not in {"max_tokens", "temperature"}}
        assert paired[1][1] == wire["body"]
    assert check_digests[0] != check_digests[1]
    assert adapter.snapshot(job)["state"] == "ready" and len(transport.calls) == 8
    assert inputs.settings["max_calls"] == 4 and inputs.settings["max_repairs"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["input_digest", "claim_id", "decision"])
async def test_repair_projection_cannot_hide_corrupt_checker_feedback(store, field):
    adapter, transport, job = support.setup(store, decision="unsupported")
    await adapter.advance(job)
    await adapter.advance(job)
    with store.pool.connection() as conn:
        data = conn.execute("SELECT data FROM workspace_generation_jobs WHERE id=%s", (job,)).fetchone()[0]
        data["adapter"]["steps"][1]["output"]["checks"][0][field] = {
            "input_digest": "sha256:" + "0" * 64, "claim_id": "different", "decision": "invented"}[field]
        conn.execute("UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job))
    calls = len(transport.calls)
    with pytest.raises(ValueError):
        adapter.request(job)
    assert len(transport.calls) == calls


def test_v8_context_seal_and_strict_v7_packet_rejection(store):
    inputs = support.prepared(store)
    assert inputs.settings["context_revision"] == p.CONTEXT_REVISION
    assert inputs.settings["checker_system_digest"] == _digest(p.CHECKER_SYSTEM)
    assert inputs.settings["checker_instructions_digest"] == _digest(p.CHECKER_INSTRUCTIONS)
    for field in ["context_revision", "checker_system_digest", "checker_instructions_digest"]:
        changed = replace(inputs, settings={**inputs.settings, field: "old"})
        with pytest.raises(AdmissionError, match="sealed_execution_drift"):
            p.QualificationAdapter(store, "a", changed, transport=httpx.MockTransport(lambda _: pytest.fail("no contact")))
    packet = qualification.packet(store, "a", {"sources": [{"material_id": inputs.sources[0].material_id, "job_kind": "summary"}]})
    assert packet["revision"] == "workspace-qualification-packet-v8-single-selected-evidence"
    never_read = Mock(side_effect=AssertionError("reject stale revision before source binding"))
    with pytest.raises(AdmissionError, match="bounded_v8_single_evidence"):
        qualification_run.bound_jobs(never_read, "a", {**packet, "revision": "workspace-qualification-packet-v7-stage-scoped-context"})
    never_read.assert_not_called()
