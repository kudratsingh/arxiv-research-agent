"""Mixed-model qualification through the production journal, synthetic transport only."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest
from jsonschema import validate

from src.workspace import d5_adapter as d
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_operations import OPUS_LIMITS, ROUTES, reservation, wire
from src.workspace.qualification_accounting import priced_usage
from tests import test_workspace_d5_adapter as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class Mixed(support.Transport):
    async def __call__(self, request):
        reply = await super().__call__(request)
        body = json.loads(request.content)
        if not request.url.path.endswith("count_tokens"):
            value = reply.json()
            value["model"] = body["model"]
            output = json.loads(value["content"][-1]["text"])
            validate(output, body["output_config"]["format"]["schema"])
            assert value["model"] == body["model"]
            if body["model"] == "claude-opus-5-5":
                value["content"].insert(
                    0,
                    {
                        "type": "thinking",
                        "thinking": "Synthetic reasoning, not quality evidence",
                        "signature": "offline-signature",
                    },
                )
            return httpx.Response(200, json=value)
        return reply


async def test_four_stage_mixed_models_and_exact_paired_counts_split_prices(store):
    inputs = support.setup(store, routes=deepcopy(ROUTES))
    transport = Mixed("unsupported")
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    for _ in range(4):
        result = await adapter.advance(job["id"])
    assert result["state"] == "ready" and result["result"]["grounding"]["unsupported"] > 0
    assert [s["model_id"] for s in result["steps"]] == [
        "claude-sonnet-5-5",
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    ]
    costs = {"workflow": Decimal(0), "checker": Decimal(0)}
    for index in range(0, 8, 2):
        count, message = result["contacts"][index : index + 2]
        assert count["body"] == {
            k: v for k, v in message["body"].items() if k not in {"max_tokens", "temperature"}
        }
        assert (
            count["generation_request_digest"]
            == message["generation_request_digest"]
            == _digest(message["body"])
        )
        stage = message["stage"]
        model = "claude-opus-5-5" if stage == "check" else "claude-sonnet-5-5"
        assert message["body"]["model"] == model
        if stage == "check":
            assert message["body"]["thinking"] == {"type": "adaptive"}
            assert message["body"]["output_config"]["effort"] == "high"
            assert message["body"]["max_tokens"] == 3200
        billing = adapter._billing_input({"stage": stage, "body": message["body"]})
        _, _, cost = priced_usage(message["response"], billing)
        costs["checker" if stage == "check" else "workflow"] += cost
    assert costs == {"workflow": Decimal("0.0024"), "checker": Decimal("0.0048")}
    assert result["workflow_usd"] == result["checker_usd"] == "0"  # No real billing in mock mode.


@pytest.mark.parametrize("amount", ["0.40", "0.447999", "0.451"])
async def test_complete_envelope_must_be_reserved_without_raising_authorized_cap(store, amount):
    inputs = support.setup(store, routes=deepcopy(ROUTES))
    transport = Mixed()
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    with pytest.raises(AdmissionError):
        adapter.start(inputs.settings["d5_request_id"], amount)
    assert transport.calls == []


@pytest.mark.parametrize("failure", ["wrong_model", "truncated", "invalid_json", "invalid_schema"])
async def test_bad_opus_verdict_stays_failed_not_accepted_or_retried(store, failure):
    inputs = support.setup(store, routes=deepcopy(ROUTES))
    delegate = Mixed()

    async def fixture(request):
        result = await delegate(request)
        body = json.loads(request.content)
        if request.url.path.endswith("messages") and body["model"] == "claude-opus-5-5":
            value = result.json()
            if failure == "wrong_model":
                value["model"] = "claude-sonnet-5-5"
            elif failure == "truncated":
                value["stop_reason"] = "max_tokens"
            elif failure == "invalid_json":
                value["content"][-1]["text"] = '{"checks":'
            else:
                value["content"][-1]["text"] = '{"checks":[],"prose_review":"factual"}'
            return httpx.Response(200, json=value)
        return result

    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(fixture))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    with pytest.raises((AdmissionError, ValueError)):
        await adapter.advance(job["id"])
    result = adapter.snapshot(job["id"])
    assert result["state"] in {"failed", "uncertain"} and result.get("result") is None
    assert len(delegate.calls) == 4
    with pytest.raises((AdmissionError, ValueError)):
        await adapter.advance(job["id"])
    assert len(delegate.calls) == 4


async def test_wrong_model_count_body_and_cross_request_pair_refused_before_transport(store):
    inputs = support.setup(store, routes=deepcopy(ROUTES))
    transport = Mixed()
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    candidate = adapter.request(job["id"])
    wrong = deepcopy(candidate)
    wrong["body"]["model"] = "claude-opus-5-5"
    wrong["request_digest"] = _digest(wrong["body"])
    with pytest.raises(AdmissionError, match="contact_fenced_or_drifted"):
        adapter._contact(job["id"], wrong, "messages/count_tokens")
    ordinal = adapter._contact(job["id"], candidate, "messages/count_tokens")
    count_body = {
        k: v for k, v in candidate["body"].items() if k not in {"max_tokens", "temperature"}
    }
    with pytest.raises(AdmissionError, match="approved_contact_journal_required"):
        await adapter._post(
            "messages/count_tokens",
            {**count_body, "model": "claude-opus-5-5"},
            job_id=job["id"],
            ordinal=ordinal,
        )
    assert transport.calls == []


async def test_complete_mixed_model_benchmark_includes_four_opus_probes(store, monkeypatch):

    from src.workspace.d5_benchmark import run
    from src.workspace.d5_fixture import authorize_fixture
    from tests.test_workspace_d5_benchmark import corpus

    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    packet = corpus(store)
    packet["operation_routes"] = deepcopy(ROUTES)
    packet["limits"] = deepcopy(OPUS_LIMITS)
    for probe in packet["probes"]:
        context = json.loads(probe["wire"]["messages"][0]["content"])
        probe["wire"] = wire({**context, "output_schema": packet["checker_schema"]["wire"]}, ROUTES)
    packet["packet_digest"] = _digest({k: v for k, v in packet.items() if k != "packet_digest"})
    with store.pool.connection() as conn:
        conn.execute("INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only','{}')")
    authorize_fixture(store, packet)
    report = await run(store, packet, "all", offline=True)
    assert len(report["cases"]) == 10 and all(c["completion"] for c in report["cases"])
    with store.pool.connection() as conn:
        probes = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE data->'sealed_input'->'settings'->>'d5_operation'='probe'"
        ).fetchall()
    assert len(probes) == 4
    for (data,) in probes:
        messages = [c for c in data["adapter"]["contacts"] if c["endpoint"] == "messages"]
        assert len(messages) == 1 and messages[0]["body"]["model"] == "claude-opus-5-5"
        assert messages[0]["body"]["max_tokens"] == 3200
    assert report["accounting"]["actual_new_provider_contacts"] == 0


async def test_exact_budget_and_invalid_route_are_closed(store):
    assert reservation(ROUTES) == Decimal("0.448")
    assert reservation(ROUTES, probe=True) == Decimal("0.144")
    assert 10 * reservation(ROUTES) + 4 * reservation(ROUTES, probe=True) == Decimal("5.056")
    bad = deepcopy(ROUTES)
    bad["check_recheck_probe"]["effort"] = "medium"
    with pytest.raises(AdmissionError, match="operation_routes_drift"):
        reservation(bad)
    inputs = support.setup(store, routes=deepcopy(ROUTES))
    tampered = replace(inputs, settings={**inputs.settings, "operation_routes": bad})
    with pytest.raises(AdmissionError, match="operation_routes_drift"):
        d.D5Adapter(store, "d5-run", tampered, transport=httpx.MockTransport(Mixed()))


async def test_completed_but_truncated_opus_receipt_reconciles_by_actual_operation_prices(store):
    from psycopg.types.json import Jsonb

    from src.workspace.qualification_accounting import settle_failed_response

    inputs = support.setup(store, routes=deepcopy(ROUTES))
    delegate = Mixed()

    async def fixture(request):
        response = await delegate(request)
        if (
            request.url.path.endswith("messages")
            and json.loads(request.content)["model"] == "claude-opus-5-5"
        ):
            value = response.json()
            value["stop_reason"] = "max_tokens"
            return httpx.Response(200, json=value)
        return response

    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(fixture))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    with pytest.raises(AdmissionError):
        await adapter.advance(job["id"])
    # Audit-only synthetic provider journal, never an executable permission.
    with store.pool.connection() as conn:
        data = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id=%s", (job["id"],)
        ).fetchone()[0]
        data["adapter"]["mode"] = "provider"
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job["id"])
        )
    audit = settle_failed_response(
        store, "d5-run", job["id"], receipt_id="synthetic-operation-pricing-audit"
    )
    assert Decimal(audit["workflow_usd"]) == Decimal("0.0012")
    assert Decimal(audit["checker_usd"]) == Decimal("0.0024")
    assert audit["content_accepted"] is False and audit["state"] == "failed"
    with store.pool.connection() as conn:
        data = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id=%s", (job["id"],)
        ).fetchone()[0]
        data["adapter"]["contacts"][-1]["body"]["model"] = "claude-sonnet-5-5"
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job["id"])
        )
    with pytest.raises(AdmissionError, match="accounting_operation_binding_drift"):
        settle_failed_response(store, "d5-run", job["id"], receipt_id="synthetic-corrupt-operation")


@pytest.mark.parametrize("changed", ["model", "hash"])
async def test_paired_count_receipt_model_and_body_hash_must_match_before_messages(store, changed):
    from psycopg.types.json import Jsonb

    inputs = support.setup(store, routes=deepcopy(ROUTES))
    transport = Mixed()
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    candidate = adapter.request(job["id"])
    ordinal = adapter._contact(job["id"], candidate, "messages/count_tokens")
    adapter._record(job["id"], ordinal, {"input_tokens": 100})
    with store.pool.connection() as conn:
        data = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id=%s", (job["id"],)
        ).fetchone()[0]
        count = data["adapter"]["contacts"][0]
        if changed == "model":
            count["body"]["model"] = "claude-opus-5-5"
        else:
            count["request_digest"] = "wrong-count-body-digest"
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job["id"])
        )
    ordinal = adapter._contact(job["id"], candidate, "messages")
    with pytest.raises(AdmissionError, match="bound_count_receipt_required"):
        await adapter._post("messages", candidate["body"], job_id=job["id"], ordinal=ordinal)
    assert transport.calls == []


@pytest.mark.parametrize(
    "content",
    [
        None,
        [],
        [{"type": "tool_use"}, {"type": "text", "text": "{}"}],
        [{"type": "thinking", "thinking": None}, {"type": "text", "text": "{}"}],
        [{"type": "text", "text": "{}"}, {"type": "text", "text": "{}"}],
        [{"type": "thinking", "thinking": "reasoning without verdict"}],
        [None],
        [{"type": "text", "text": None}],
    ],
)
async def test_reasoning_cannot_substitute_or_add_an_extra_verdict(content):
    from src.workspace.d5_operations import verdict_text

    with pytest.raises(AdmissionError):
        verdict_text({"content": content})


async def test_redacted_reasoning_and_unknown_stage():
    from src.workspace.d5_operations import route, verdict_text

    assert (
        verdict_text(
            {
                "content": [
                    {"type": "redacted_thinking", "data": "opaque"},
                    {"type": "text", "text": "{}"},
                ]
            }
        )
        == "{}"
    )
    with pytest.raises(AdmissionError, match="operation_stage_required"):
        route(ROUTES, "other")
