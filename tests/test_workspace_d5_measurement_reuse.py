"""Explicit historical measurement links, synthetic fixtures and no live contact."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import httpx
import pytest
from psycopg.types.json import Jsonb

from src.workspace import d5_measurements as m
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import D5MeasurementAdapter
from tests import test_workspace_d5_adapter as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def measured(store, count=100):
    inputs = support.setup(store, operation="measurement", stages=["A"])
    transport = support.Transport()

    async def handler(request):
        response = await transport(request)
        return (
            httpx.Response(200, json={"input_tokens": count})
            if request.url.path.endswith("count_tokens")
            else response
        )

    adapter = D5MeasurementAdapter(store, "d5-run", inputs, transport=httpx.MockTransport(handler))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    with store.pool.connection() as conn:
        authorization = conn.execute(
            "SELECT data->'authorization_record' FROM workspace_d5_scopes"
        ).fetchone()[0]
    link = m.make_link(store, job["id"], authorization)
    settings = {
        **inputs.settings,
        "d5_packet_digest": "successor",
        "d5_scope_id": "d5-successor",
        "d5_request_id": "new-measure-1",
        "program_amendment_proposal_digest": "a" * 64,
    }
    return link, replace(inputs, settings=settings), transport


async def test_exact_request_and_settings_reuse_without_relabelling_or_contact(store):
    link, successor, transport = await measured(store)
    assert link["input_digest"] != _digest(successor.snapshot())
    with store.pool.connection() as conn:
        before = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id=%s", (link["job_id"],)
        ).fetchone()[0]
        before_jobs = conn.execute("SELECT count(*) FROM workspace_generation_jobs").fetchone()[0]
    proof = m.verify_reuse(store, link, "new-owner", successor, offline=True)
    assert proof["reused"] and proof["new_contacts"] == 0 and proof["input_tokens"] == 100
    assert len(transport.calls) == 1
    with store.pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT data FROM workspace_generation_jobs WHERE id=%s", (link["job_id"],)
            ).fetchone()[0]
            == before
        )
        assert (
            conn.execute("SELECT count(*) FROM workspace_generation_jobs").fetchone()[0]
            == before_jobs
        )
    with pytest.raises(AdmissionError):
        m.verify_reuse(
            store, link, "new-owner", successor, offline=False
        )  # Mock receipt never becomes provider evidence.


@pytest.mark.parametrize("field", ["model", "thinking", "effort", "prompt", "schema"])
async def test_changed_exact_wire_requires_a_fresh_named_count(store, monkeypatch, field):
    link, inputs, _ = await measured(store)
    adapter = D5MeasurementAdapter(
        store, "new-owner", inputs, transport=httpx.MockTransport(lambda _: None)
    )
    wire = deepcopy(adapter.request())
    if field == "model":
        wire["body"]["model"] = "different-model"
    elif field == "thinking":
        wire["body"]["thinking"] = {"type": "disabled"}
    elif field == "effort":
        wire["body"]["output_config"]["effort"] = "high"
    elif field == "prompt":
        wire["body"]["messages"][0]["content"] += " "
    else:
        wire["body"]["output_config"]["format"]["schema"]["description"] = "Changed schema"
    wire["request_digest"] = _digest(wire["body"])
    monkeypatch.setattr(D5MeasurementAdapter, "request", lambda *_: wire)
    with pytest.raises(AdmissionError, match="fresh_count_required"):
        m.verify_reuse(store, link, "new-owner", inputs, offline=True)
    compiled = {"measure-1": {"stage": "A", "owner": "new-owner", "input": inputs.snapshot()}}
    result = m.assess_reuse(store, {"measure-1": link}, compiled, offline=True)
    assert result == {"measurement_reuse": {}, "fresh_measurement_cases": ["measure-1"]}


@pytest.mark.parametrize(
    "change",
    [
        "not_ready",
        "missing",
        "fingerprint",
        "authorization",
        "contact",
        "response",
        "receipt_digest",
        "count",
        "wrong_packet",
        "selection",
        "settings",
    ],
)
async def test_bad_historical_receipt_binding_cannot_be_replaced_by_fresh_adaptive_contact(
    store, change
):
    link, inputs, transport = await measured(store)
    if change == "missing":
        link["job_id"] = "missing"
    elif change == "not_ready":
        with store.pool.connection() as conn:
            conn.execute(
                "UPDATE workspace_generation_jobs SET state='failed' WHERE id=%s", (link["job_id"],)
            )
    elif change in {"fingerprint", "contact", "response"}:
        with store.pool.connection() as conn:
            data = conn.execute(
                "SELECT data FROM workspace_generation_jobs WHERE id=%s", (link["job_id"],)
            ).fetchone()[0]
            if change == "fingerprint":
                data["sealed_input"]["model_id"] = "wrong"
            elif change == "contact":
                data["adapter"]["contacts"][0]["state"] = "dispatching"
            else:
                data["adapter"]["contacts"][0]["response"]["input_tokens"] = None
            conn.execute(
                "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s",
                (Jsonb(data), link["job_id"]),
            )
    elif change == "authorization":
        link["authorization_record"]["stages"] = ["A", "B"]
    elif change == "receipt_digest":
        link["contact_receipt_digest"] = "bad"
    elif change == "count":
        link["input_tokens"] = 1
    elif change == "wrong_packet":
        link["packet_digest"] = "wrong"
    elif change == "selection":
        link["binding"]["units_digest"] = "wrong"
    else:
        link["binding"]["settings"]["input_tokens"] = 25000
    with pytest.raises(AdmissionError):
        m.verify_reuse(store, link, "new-owner", inputs, offline=True)
    assert len(transport.calls) == 1


async def test_unavailable_mutated_source_refuses_even_when_old_count_is_small(store):
    link, inputs, _ = await measured(store)
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_material SET data=jsonb_set(data,'{pages}','[\"Mutated material\"]')"
        )
    with pytest.raises((AdmissionError, ValueError)):
        m.verify_reuse(store, link, "new-owner", inputs, offline=True)


async def test_malformed_link_and_missing_reference_plan(store):
    link, inputs, _ = await measured(store)
    with pytest.raises(AdmissionError, match="malformed"):
        m.verify_reuse(store, {}, "new-owner", inputs, offline=True)
    compiled = {
        "measure-1": {"stage": "A", "owner": "new-owner", "input": inputs.snapshot()},
        "workflow": {"stage": "B"},
    }
    assert m.assess_reuse(store, {}, compiled, offline=True)["fresh_measurement_cases"] == [
        "measure-1"
    ]
    assert (
        m.assess_reuse(store, {"measure-1": link}, compiled, offline=True)[
            "fresh_measurement_cases"
        ]
        == []
    )


async def test_identical_request_above_allowance_stops_instead_of_adaptive_recount(store):
    link, inputs, transport = await measured(store, count=16001)
    compiled = {"measure-1": {"stage": "A", "owner": "new-owner", "input": inputs.snapshot()}}
    with pytest.raises(AdmissionError, match="exceeds_allowance"):
        m.assess_reuse(store, {"measure-1": link}, compiled, offline=True)
    assert len(transport.calls) == 1
