"""Real Postgres, actual wire contracts, synthetic approvals and MockTransport only.

Synthetic usage integers are test inputs, never measurements or quality labels.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
from jsonschema import Draft202012Validator

from src.workspace import provider_adapter as p
from src.workspace.admission import AdmissionError, _digest
from src.workspace.evidence_contract import draft_schema
from src.workspace.qualification_budget import census, register_trial
from tests import test_workspace_admission as admission
from tests import test_workspace_executor as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def prepared(store, kind="summary"):
    _, material, _ = support.source(store)
    return p.prepare(store, "a", kind, [material])


def approve(store, inputs, **changes):
    if changes.get("transport_mode") == "provider":
        with store.pool.connection() as conn:
            history = census(conn, "a")
        register_trial(store, "a", "synthetic-trial", history["history_digest"])
        changes["trial_id"] = "synthetic-trial"
    return admission.policy(store, **{
        "model_ids": [p.MODEL], "purpose": "workspace-qualification",
        "request_digest": _digest(inputs.snapshot()), "transport_mode": "mock",
        "everyday_generation": False, "request_id": "one", **changes,
    })


class Transport:
    def __init__(self, store, inputs, *, decision="supported", change=None):
        self.calls = []
        self.decision, self.change = decision, change
        self.store, self.inputs = store, inputs
        self.adapter = None
        self.job = None

    async def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        assert request.url.host == "api.anthropic.com"
        assert request.headers["x-api-key"] == "local-preview-disabled"
        assert body["model"] == p.MODEL and "output_config" in body
        assert body["thinking"] == {"type": "between_tools"}
        assert body["output_config"]["effort"] == "medium"
        assert not {"temperature", "top_p", "top_k"} & body.keys()
        if request.url.path.endswith("count_tokens"):
            assert "max_tokens" not in body and "temperature" not in body
            return httpx.Response(200, json={"input_tokens": 100})
        context = json.loads(body["messages"][0]["content"])
        assert context["private_context"] == {"notes": False, "history": False, "profile": False}
        if context["stage"] == "check":
            output = {
                "checks": [
                    {
                        "claim_id": item["claim"]["claim_id"],
                        "input_digest": item["input_digest"],
                        "decision": self.decision,
                        "reason": "Synthetic fixture decision, not quality evidence",
                    }
                    for item in context["claims"]
                ]
            }
        else:
            output = {
                "kind": self.inputs.kind,
                "abstention": None,
                "title": "Mock transport draft",
                "claims": [{"claim_id": "c1", "text": "The retained source reports a fixed evaluation.",
                            "handles": [context["evidence"][0]["handle"]], "section": "overview"}],
                "question": "Which evaluation setting limits this finding?",
                "limitation": "Retained excerpts only; omitted pages were not reviewed.",
                "proposal": "Propose a fixed-baseline replication." if self.inputs.kind == "deep_dive" else None,
            }
        schema = body["output_config"]["format"]["schema"]
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(json.loads(json.dumps(output)))
        (p.Checks if context["stage"] == "check" else draft_schema(self.inputs.kind)).model_validate(output)
        value = {
            "id": "msg_synthetic_" + str(len(self.calls)),
            "model": p.MODEL,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 110, "output_tokens": 90},
            "content": [{"type": "text", "text": json.dumps(output)}],
        }
        if self.change:
            value = self.change(value)
        return httpx.Response(200, json=value)


def setup(store, **kwargs):
    inputs = prepared(store, kwargs.pop("kind", "summary"))
    approve(store, inputs)
    transport = Transport(store, inputs, **kwargs)
    adapter = p.QualificationAdapter(store, "a", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start("one", "0.5")
    transport.adapter, transport.job = adapter, job["id"]
    return adapter, transport, job["id"]


@pytest.mark.parametrize(
    "kind,decision,calls",
    [("summary", "supported", 4), ("deep_dive", "unsupported", 8), ("summary", "abstain", 8)],
)
async def test_exact_wire_to_durable_experiment_result_and_bounded_repair(
    store, kind, decision, calls
):
    adapter, transport, job = setup(store, kind=kind, decision=decision)
    first_wire = adapter.request(job)
    assert first_wire == adapter.request(job)
    assert first_wire["request_digest"] == _digest(first_wire["body"])
    while adapter.snapshot(job)["state"] == "running":
        result = await adapter.advance(job)
    assert result["state"] == "ready" and len(transport.calls) == calls
    assert result["result"]["experiment_only"] and not result["result"]["checker_qualified"]
    assert not result["result"]["everyday_generation"]
    assert result["workflow_usd"] == result["checker_usd"] == "0"
    assert "synthetic" in result["usage_basis"]
    assert {step["role"] for step in result["steps"]} == {"workflow", "checker"}
    assert all(c["state"] == "completed" for c in result["contacts"])
    assert adapter.start("one", "0.5")["cached"]
    with pytest.raises(AdmissionError):
        await adapter.advance(job)
    assert len(transport.calls) == calls


async def test_gate_binding_and_separate_qualification_approval_before_client(store, monkeypatch):
    inputs = prepared(store)
    client = Mock(side_effect=AssertionError("must refuse before client construction"))
    monkeypatch.setattr(p.httpx, "AsyncClient", client)
    for kwargs in ({}, {"enabled": True}, {"enabled": True, "api_key": "also-blocked-by-sentinel"}):
        with pytest.raises(AdmissionError, match="provider_disabled"):
            p.QualificationAdapter(store, "a", inputs, **kwargs)
    with pytest.raises(AdmissionError, match="mock_transport_required"):
        p.QualificationAdapter(store, "a", inputs, transport=object())
    with pytest.raises(AdmissionError, match="mock_credential_required"):
        p.QualificationAdapter(
            store, "a", inputs, transport=httpx.MockTransport(lambda r: None), api_key="real-key"
        )
    for changed in (
        replace(inputs, model_id="unknown"),
        replace(inputs, private_question="private"),
        replace(inputs, settings={**inputs.settings, "temperature": 0.8}),
    ):
        with pytest.raises(AdmissionError, match="sealed_execution_drift"):
            p.QualificationAdapter(
                store, "a", changed, transport=httpx.MockTransport(lambda r: None)
            )
    adapter = p.QualificationAdapter(
        store, "a", inputs, transport=httpx.MockTransport(lambda r: None)
    )
    with pytest.raises(AdmissionError, match="reservation_below_envelope"):
        adapter.start("small", "0.01")
    with pytest.raises(AdmissionError, match="owner_approval_required"):
        adapter.start("no", "0.5")
    admission.policy(store, model_ids=[p.MODEL])
    with pytest.raises(AdmissionError, match="qualification_approval_required"):
        adapter.start("not-qualification", "0.5")
    approve(store, inputs, transport_mode="provider", request_id="wrong-mode")
    with pytest.raises(AdmissionError, match="approval_transport_mismatch"):
        adapter.start("wrong-mode", "0.5")
    client.assert_not_called()


@pytest.mark.parametrize(
    "change,error",
    [
        (lambda v: {**v, "model": "wrong"}, "invalid_or_unpriced"),
        (lambda v: {**v, "stop_reason": "max_tokens"}, "incomplete_output"),
        (
            lambda v: {**v, "usage": {"input_tokens": True, "output_tokens": 0}},
            "invalid_or_unpriced",
        ),
        (
            lambda v: {**v, "usage": {"input_tokens": 10, "output_tokens": -1}},
            "invalid_or_unpriced",
        ),
        (
            lambda v: {
                **v,
                "usage": {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 2},
            },
            "invalid_or_unpriced",
        ),
        (lambda v: {**v, "usage": {"input_tokens": 8001, "output_tokens": 1}}, "usage_cap"),
        (lambda v: {**v, "usage": {"input_tokens": 1, "output_tokens": 1201}}, "usage_cap"),
        (lambda v: {**v, "content": []}, "structured_text"),
        (lambda v: {**v, "content": [{"type": "thinking"}]}, "structured_text"),
        (lambda v: {**v, "content": [{"type": "text", "text": "not json"}]}, "Expecting value"),
    ],
)
async def test_invalid_or_incomplete_billed_output_is_fenced_never_replayed(store, change, error):
    adapter, transport, job = setup(store, change=change)
    with pytest.raises((AdmissionError, ValueError), match=error):
        await adapter.advance(job)
    unknown = "invalid_or_unpriced" in error
    assert adapter.snapshot(job)["state"] == ("uncertain" if unknown else "failed")
    assert (admission.row(store, job)[4] > 0) is unknown
    assert adapter.snapshot(job)["result"] is None
    with pytest.raises(AdmissionError):
        await adapter.advance(job)
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "fault",
    [
        "timeout",
        "redirect",
        "429",
        "oversized",
        "shape",
        "count_negative",
        "count_bool",
        "count_large",
    ],
)
async def test_counting_contact_failures_no_generation_or_implicit_retries(store, fault):
    inputs = prepared(store)
    approve(store, inputs, request_id="fault")
    calls = []

    async def handler(request):
        calls.append(request)
        if fault == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if fault == "redirect":
            return httpx.Response(302, headers={"location": "https://other.invalid"})
        if fault == "429":
            return httpx.Response(429, headers={"retry-after": "30"})
        if fault == "oversized":
            return httpx.Response(200, content=b"x" * 131073)
        if fault == "shape":
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json={
                "input_tokens": {"count_negative": -1, "count_bool": True, "count_large": 6401}[
                    fault
                ]
            },
        )

    adapter = p.QualificationAdapter(store, "a", inputs, transport=httpx.MockTransport(handler))
    job = adapter.start("fault", "0.5")["id"]
    with pytest.raises((AdmissionError, httpx.HTTPError)):
        await adapter.advance(job)
    assert len(calls) == 1
    assert adapter.snapshot(job)["state"] == ("failed" if fault == "count_large" else "uncertain")
    if fault == "count_large":
        assert admission.row(store, job)[4] == 0
        assert adapter.snapshot(job)["result"] is None


async def test_cancel_restart_and_competing_contact_are_fenced(store):
    adapter, transport, job = setup(store)
    assert (await adapter.advance(job, cancelled=lambda: True))["state"] == "cancelled"
    assert not transport.calls
    adapter, transport, job = setup_new(store, "second")
    wire = adapter.request(job)
    adapter._contact(job, wire, "messages/count_tokens")
    with pytest.raises(AdmissionError, match="contact_fenced"):
        adapter._contact(job, wire, "messages/count_tokens")
    restarted = p.QualificationAdapter(
        store, "a", adapter.inputs, transport=httpx.MockTransport(transport)
    )
    restarted.control.recover("a", job)
    assert restarted.snapshot(job)["state"] == "uncertain"
    with pytest.raises(AdmissionError):
        await restarted.advance(job)
    assert not transport.calls


def setup_new(store, request_id):
    inputs = prepared(store)
    approve(store, inputs, request_id=request_id)
    transport = Transport(store, inputs)
    adapter = p.QualificationAdapter(store, "a", inputs, transport=httpx.MockTransport(transport))
    return adapter, transport, adapter.start(request_id, "0.5")["id"]


async def test_cancellation_during_generation_retains_receipt_and_discards_output(store):
    adapter, transport, job = setup(store)
    original = transport.__call__

    async def handler(request):
        response = await original(request)
        if request.url.path == "/v1/messages":
            adapter.control.cancel("a", job)
        return response

    adapter.transport = httpx.MockTransport(handler)
    result = await adapter.advance(job)
    assert result["state"] == "cancelled" and not result["steps"] and not result["result"]
    assert result["contacts"][-1]["response"]["usage"]["input_tokens"] == 110
    assert admission.row(store, job)[4] == 0


async def test_task_cancellation_and_policy_drift_preserve_unknown(store):
    adapter, _, job = setup(store)

    async def interrupted(request):
        raise asyncio.CancelledError()

    adapter.transport = httpx.MockTransport(interrupted)
    with pytest.raises(asyncio.CancelledError):
        await adapter.advance(job)
    assert admission.row(store, job)[4] > 0
    adapter, transport, job = setup_new(store, "other")
    approve(store, adapter.inputs, day_usd="2.1", request_id="other")
    with pytest.raises(AdmissionError, match="contact_fenced"):
        await adapter.advance(job)
    assert not transport.calls


async def test_dispatch_rechecks_transport_and_credential_drift_before_client(store, monkeypatch):
    adapter, _, job = setup(store)
    constructor = Mock(side_effect=AssertionError("no client construction"))
    monkeypatch.setattr(p.httpx, "AsyncClient", constructor)
    adapter.transport = None
    with pytest.raises(AdmissionError, match="mock_transport_drift"):
        await adapter.advance(job)
    adapter.mode = "provider"
    with pytest.raises(AdmissionError, match="provider_disabled"):
        await adapter._post("messages", {})
    constructor.assert_not_called()


async def test_count_cancel_and_known_receipt_cancel_are_distinct(store):
    adapter, transport, job = setup(store)
    original = transport.__call__

    async def cancelled_count(request):
        response = await original(request)
        adapter.control.cancel("a", job)
        return response

    adapter.transport = httpx.MockTransport(cancelled_count)
    assert (await adapter.advance(job))["state"] == "cancelled"
    assert len(transport.calls) == 1
    for request_id, stop_after, expected in [("after-count", 2, 1), ("after-usage", 3, 2)]:
        adapter, transport, job = setup_new(store, request_id)
        checks = []

        def cancelled(checks=checks, stop_after=stop_after):
            checks.append(True)
            return len(checks) >= stop_after

        assert (await adapter.advance(job, cancelled=cancelled))["state"] == "cancelled"
        assert len(transport.calls) == expected


async def test_kind_schema_checker_provenance_and_capability_drift_refuse(store, monkeypatch):
    def wrong_kind(value):
        draft = json.loads(value["content"][0]["text"])
        draft["kind"] = "deep_dive"
        return {**value, "content": [{"type": "text", "text": json.dumps(draft)}]}

    adapter, _, job = setup(store, change=wrong_kind)
    with pytest.raises(AdmissionError, match="kind_drift"):
        await adapter.advance(job)
    adapter, transport, job = setup_new(store, "provenance")
    await adapter.advance(job)

    def drift(value):
        checks = json.loads(value["content"][0]["text"])
        checks["checks"][0]["input_digest"] = "sha256:" + "0" * 64
        return {**value, "content": [{"type": "text", "text": json.dumps(checks)}]}

    transport.change = drift
    with pytest.raises(ValueError, match="checker_input_drift"):
        await adapter.advance(job)
    monkeypatch.setattr(p, "MODEL_CAPABILITIES", {})
    with pytest.raises(AdmissionError, match="unsupported_model"):
        p.QualificationAdapter(store, "a", adapter.inputs, transport=httpx.MockTransport(transport))


async def test_provider_branch_uses_mocked_transport_but_records_priced_role_usage(
    store, monkeypatch
):
    # Exercise the priced branch without sockets. This explicit test injection
    # provides synthetic response usage, not measured or invoice-backed tokens.
    inputs = prepared(store)
    approve(store, inputs, transport_mode="provider", request_id="priced-branch")
    transport = Transport(store, inputs)
    original_client = httpx.AsyncClient

    def mock_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(transport)
        return original_client(**kwargs)

    monkeypatch.setattr(p.httpx, "AsyncClient", mock_client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-not-a-credential")
    adapter = p.QualificationAdapter(
        store, "a", inputs, api_key="synthetic-test-not-a-credential", enabled=True
    )
    # Only this test's handler accepts the synthetic key; production handler
    # assertions continue to require the disabled sentinel for offline mode.
    original = transport.__call__

    async def handler(request):
        request.headers["x-api-key"] = "local-preview-disabled"
        return await original(request)

    transport.__call__ = handler

    # Special methods are resolved on the class, so inject the handler directly.
    def mock_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(**kwargs)

    monkeypatch.setattr(p.httpx, "AsyncClient", mock_client)
    job = adapter.start("priced-branch", "0.5")["id"]
    await adapter.advance(job)
    result = await adapter.advance(job)
    assert result["state"] == "ready"
    assert result["workflow_usd"] == result["checker_usd"] == "0.00112"
    assert admission.row(store, job)[2:5] == (
        p.Decimal("0.00112"),
        p.Decimal("0.00112"),
        p.Decimal(0),
    )


async def test_named_approval_cannot_be_reused_for_another_request_id(store):
    adapter, transport, job = setup(store)
    with pytest.raises(AdmissionError, match="approved_request_id_required"):
        adapter.start("another", "0.5")
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM workspace_generation_jobs").fetchone()[0] == 1
    with pytest.raises(AdmissionError, match="endpoint_not_permitted"):
        await adapter._post("not-an-approved-endpoint", {})
    assert not transport.calls


async def test_transport_construction_requires_the_exact_unconsumed_approved_journal(
    store, monkeypatch
):
    adapter, _, job = setup(store)
    constructor = Mock(side_effect=AssertionError("must refuse before transport construction"))
    monkeypatch.setattr(p.httpx, "AsyncClient", constructor)
    wire = adapter.request(job)
    body = {k: v for k, v in wire["body"].items() if k not in {"max_tokens", "temperature"}}
    with pytest.raises(AdmissionError, match="approved_contact_journal_required"):
        await adapter._post("messages/count_tokens", body)
    ordinal = adapter._contact(job, wire, "messages/count_tokens")
    for endpoint, changed, index in [
        ("messages", body, ordinal),
        ("messages/count_tokens", {**body, "model": "wrong"}, ordinal),
        ("messages/count_tokens", body, ordinal + 1),
    ]:
        with pytest.raises(AdmissionError, match="approved_contact_journal_required"):
            await adapter._post(endpoint, changed, job_id=job, ordinal=index)
    constructor.assert_not_called()
    # Claiming a contact before a lost client construction consumes it. A new
    # process cannot send it again merely because no response was journalled.
    with pytest.raises(AssertionError, match="transport construction"):
        await adapter._post("messages/count_tokens", body, job_id=job, ordinal=ordinal)
    with pytest.raises(AdmissionError, match="approved_contact_journal_required"):
        await adapter._post("messages/count_tokens", body, job_id=job, ordinal=ordinal)
    assert constructor.call_count == 1


@pytest.mark.parametrize(
    "count", [{"input_tokens": 6401}, {"input_tokens": None}, {"input_tokens": True}]
)
async def test_message_client_cannot_construct_without_a_bound_admissible_count(
    store, monkeypatch, count
):
    adapter, _, job = setup(store)
    wire = adapter.request(job)
    ordinal = adapter._contact(job, wire, "messages/count_tokens")
    adapter._record(job, ordinal, count)
    ordinal = adapter._contact(job, wire, "messages")
    constructor = Mock(side_effect=AssertionError("no message client"))
    monkeypatch.setattr(p.httpx, "AsyncClient", constructor)
    with pytest.raises(AdmissionError, match="bound_count_receipt_required"):
        await adapter._post("messages", wire["body"], job_id=job, ordinal=ordinal)
    constructor.assert_not_called()
