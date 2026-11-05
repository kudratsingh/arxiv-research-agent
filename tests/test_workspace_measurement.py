"""Count-only and funded authorizations are disjoint; isolated Postgres/MockTransport."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import Mock

import httpx
import pytest

from src.workspace import measurement as m
from src.workspace import qualification as q
from src.workspace import qualification_run as run
from src.workspace.admission import AdmissionError, _digest
from src.workspace.provider_adapter import QualificationAdapter
from tests import test_workspace_provider_adapter as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def fixture(store):
    sources = []
    for version in range(1, 5):
        _, material, _ = support.support.source(store, version)
        sources.append(
            {"material_id": material, "job_kind": "summary" if version < 4 else "deep_dive"}
        )
    packet = q.packet(store, "a", {"sources": sources})
    approve(store, packet)
    return packet


def approve(store, packet, **changes):
    return support.admission.policy(
        store,
        model_ids=[support.p.MODEL],
        purpose="workspace-measurement-only",
        transport_mode="mock",
        everyday_generation=False,
        count_contacts_max=4,
        messages_contacts_max=0,
        count_requests=packet["measurement_only"]["count_requests"],
        **changes,
    )


def adapter(store, packet, handler):
    job, inputs = run.bound_jobs(store, "a", packet)[0]
    instance = m.MeasurementAdapter(store, "a", inputs, transport=httpx.MockTransport(handler))
    return instance, instance.start(job["measurement_request_id"])["id"]


async def test_four_counts_end_to_end_duplicate_noop_and_funded_authorization_separate(store):
    packet = fixture(store)
    calls = []

    async def handler(request):
        calls.append(request)
        assert request.url.path == "/v1/messages/count_tokens"
        assert _digest(json.loads(request.content)) in {
            j["count_request_digest"] for j in packet["jobs"]
        }
        return httpx.Response(200, json={"input_tokens": 123})

    result = await run.execute(
        store, "a", packet, "measurement", transport=httpx.MockTransport(handler)
    )
    assert len(result["results"]) == len(calls) == 4
    assert all(r["state"] == "ready" and r["result"]["measurement_only"] for r in result["results"])
    assert not result["everyday_generation"] and not result["checker_qualified"]
    await run.execute(store, "a", packet, "measurement", transport=httpx.MockTransport(handler))
    assert len(calls) == 4
    first, inputs = run.bound_jobs(store, "a", packet)[0]
    paid = QualificationAdapter(store, "a", inputs, transport=httpx.MockTransport(handler))
    with pytest.raises(AdmissionError, match="qualification_approval"):
        paid.start(first["proposed_request_id"], "0.25")
    # Separate synthetic experiment permission cannot reuse a count-only cache,
    # even if a broken external recorder reuses its approval identifier.
    support.approve(store, inputs, request_id=first["proposed_request_id"])
    funded = paid.start(first["proposed_request_id"], "0.25")
    assert funded["newly_started"] and funded["id"] not in {r["id"] for r in result["results"]}
    paid.control.cancel("a", funded["id"])
    with store.pool.connection() as conn:
        rows = conn.execute(
            "SELECT amount,workflow,judge,unknown FROM workspace_spend_reservations WHERE amount=0"
        ).fetchall()
    assert len(rows) == 4 and all(all(v == 0 for v in row) for row in rows)


async def test_measurement_cannot_generate_or_alter_approved_body_before_client(store, monkeypatch):
    packet = fixture(store)
    instance, job = adapter(store, packet, lambda _: None)
    client = Mock(side_effect=AssertionError("no client construction"))
    monkeypatch.setattr(httpx, "AsyncClient", client)
    wire = instance.request(job)
    for operation in (
        lambda: QualificationAdapter.advance(instance, job),
        lambda: instance._post("messages", wire["body"], job_id=job, ordinal=0),
    ):
        with pytest.raises(AdmissionError, match="endpoint_not_permitted|contact_fenced"):
            await operation()
    # Calling the inherited generator counted no contacts: the journal attempt
    # cannot create a client without a valid exact count body.
    body = {k: v for k, v in wire["body"].items() if k not in {"max_tokens", "temperature"}}
    with pytest.raises(AdmissionError, match="approved_count_body"):
        await instance._post(
            "messages/count_tokens", {**body, "model": "other"}, job_id=job, ordinal=0
        )
    client.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    [
        "revoked",
        "source",
        "cancel_before",
        "cancel_after",
        "timeout",
        "task_cancel",
        "restart",
        "invalid_bool",
        "invalid_negative",
    ],
)
async def test_count_fences_revocation_drift_cancellation_and_unknown_completion(store, fault):
    packet = fixture(store)
    calls = []
    instance = None
    job = None

    async def handler(request):
        calls.append(request)
        if fault == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if fault == "task_cancel":
            raise asyncio.CancelledError()
        if fault == "cancel_after":
            instance.control.cancel("a", job)
        return httpx.Response(
            200,
            json={
                "input_tokens": True
                if fault == "invalid_bool"
                else -1
                if fault == "invalid_negative"
                else 123
            },
        )

    instance, job = adapter(store, packet, handler)
    if fault == "revoked":
        approve(store, packet, approved=False)
    elif fault == "source":
        with store.pool.connection() as conn:
            conn.execute(
                "UPDATE workspace_material SET content_hash='changed' WHERE material_id=%s",
                (instance.inputs.sources[0].material_id,),
            )
    elif fault == "restart":
        instance._contact(job, instance.request(job), "messages/count_tokens")
        instance.control.recover("a", job)
    if fault in {"cancel_before", "cancel_after"}:
        result = await instance.advance(job, cancelled=lambda: fault == "cancel_before")
        assert result["state"] == "cancelled" and not instance.snapshot(job)["result"]
    else:
        with pytest.raises((ValueError, httpx.ReadTimeout, asyncio.CancelledError)):
            await instance.advance(job)
    assert len(calls) == (0 if fault in {"revoked", "source", "cancel_before", "restart"} else 1)
    before = len(calls)
    with pytest.raises(ValueError):
        await instance.advance(job)
    assert len(calls) == before


@pytest.mark.parametrize(
    "change",
    [
        {"purpose": "workspace-qualification"},
        {"count_contacts_max": 5},
        {"messages_contacts_max": 1},
        {"everyday_generation": True},
        {"count_requests": []},
        {"count_requests": [None] * 4},
        {
            "count_requests": [
                {"request_id": "x", "input_digest": "x", "count_request_digest": "x"}
            ]
            * 4
        },
    ],
)
async def test_malformed_or_excess_contact_permission_refused(store, change):
    packet = fixture(store)
    # Avoid duplicate keyword arguments in the synthetic approval helper.
    with store.pool.connection() as conn:
        data = conn.execute(
            "SELECT data FROM workspace_budget_policies WHERE owner='a'"
        ).fetchone()[0]
        data.update(change)
        from psycopg.types.json import Jsonb

        conn.execute("UPDATE workspace_budget_policies SET data=%s WHERE owner='a'", (Jsonb(data),))
    with pytest.raises(AdmissionError, match="measurement_only_approval"):
        adapter(store, packet, lambda _: None)


async def test_named_binding_zero_reservation_and_opposite_mode_permission(store):
    packet = fixture(store)
    job, inputs = run.bound_jobs(store, "a", packet)[0]
    instance = m.MeasurementAdapter(
        store, "a", inputs, transport=httpx.MockTransport(lambda _: None)
    )
    with pytest.raises(AdmissionError, match="must_be_zero"):
        instance.start(job["measurement_request_id"], "0.01")
    with pytest.raises(AdmissionError, match="count_request_id"):
        instance.start(packet["jobs"][1]["measurement_request_id"])
    with pytest.raises(AdmissionError, match="job_cap"):
        instance.control.reserve("a", job["measurement_request_id"], inputs, "0.01")
    support.approve(store, inputs, request_id=job["proposed_request_id"])
    with pytest.raises(AdmissionError, match="measurement_only_approval"):
        instance.start(job["measurement_request_id"])


async def test_runner_modes_packet_binding_restart_and_experiment_round_trip(
    store, monkeypatch, tmp_path, capsys
):
    packet = fixture(store)
    first, inputs = run.bound_jobs(store, "a", packet)[0]
    with pytest.raises(AdmissionError, match="qualification_mode"):
        await run.execute(store, "a", packet, "wrong")
    with pytest.raises(AdmissionError, match="bounded_v6"):
        run.bound_jobs(store, "a", {**packet, "jobs": []})
    duplicate = {**packet, "jobs": [packet["jobs"][0]] * 4}
    with pytest.raises(AdmissionError, match="distinct"):
        run.bound_jobs(store, "a", duplicate)
    corrupted = json.loads(json.dumps(packet))
    corrupted["jobs"][0]["initial_generation"]["body"]["model"] = "different"
    with pytest.raises(AdmissionError, match="packet_request_drift"):
        run.bound_jobs(store, "a", corrupted)
    with pytest.raises(AdmissionError, match="four_named"):
        await run.execute(store, "a", packet, "measurement", request_id="one")
    with pytest.raises(AdmissionError, match="named_experiment"):
        await run.execute(store, "a", packet, "experiment", request_id="wrong")
    with pytest.raises(AdmissionError, match="provider_disabled"):
        await run.execute(store, "a", packet, "measurement")
    support.approve(store, inputs, request_id=first["proposed_request_id"])
    transport = support.Transport(store, inputs, decision="unsupported")
    result = await run.execute(
        store,
        "a",
        packet,
        "experiment",
        request_id=first["proposed_request_id"],
        transport=httpx.MockTransport(transport),
    )
    assert result["experiment_only"] and len(transport.calls) == 8
    assert result["results"][0]["state"] == "ready"
    assert [s["stage"] for s in result["results"][0]["steps"]] == [
        "draft",
        "check",
        "repair",
        "check",
    ]
    assert not result["checker_qualified"]
    packet_file, output = tmp_path / "packet.json", tmp_path / "out" / "result.json"
    packet_file.write_text(json.dumps(packet))
    monkeypatch.setattr(run, "get_pool", lambda: store.pool)
    closed = Mock()
    monkeypatch.setattr(run, "close_pool", closed)

    async def mocked_execute(*args, **kwargs):
        assert kwargs["api_key"] == "local-preview-disabled" and not kwargs["enabled"]
        return result

    monkeypatch.setattr(run, "execute", mocked_execute)
    monkeypatch.setattr(
        "sys.argv",
        [
            "qualification_run",
            "--owner",
            "a",
            "--packet",
            str(packet_file),
            "--mode",
            "experiment",
            "--request-id",
            first["proposed_request_id"],
            "--output",
            str(output),
        ],
    )
    await asyncio.to_thread(run.main)
    assert json.loads(output.read_text()) == result
    assert "everyday generation remains disabled" in capsys.readouterr().out
    closed.assert_called_once()


async def test_runner_lost_job_and_cancelled_job_never_resubmitted(store):
    packet = fixture(store)
    instance, job = adapter(store, packet, lambda _: None)
    with pytest.raises(AdmissionError, match="requires_reconciliation"):
        await run.execute(
            store, "a", packet, "measurement", transport=httpx.MockTransport(lambda _: None)
        )
    assert instance.snapshot(job)["state"] == "uncertain"
    with pytest.raises(AdmissionError, match="terminal_job"):
        await run.execute(
            store, "a", packet, "measurement", transport=httpx.MockTransport(lambda _: None)
        )
