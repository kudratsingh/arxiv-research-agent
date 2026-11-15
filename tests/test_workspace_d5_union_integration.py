"""Actual protected runner, new encoding and mocked SDK transport, disposable PG."""

import json
from copy import deepcopy

import pytest

from src.workspace.admission import AdmissionError
from src.workspace.d5_campaign import run
from src.workspace.d5_campaign_operator import authorize_fixture
from src.workspace.d5_campaign_v16_packet import capture, freeze, verify_packet
from src.workspace.d5_keyed_transport import KeyedCampaignTransport
from src.workspace.provider_schema_compat import ProviderSchemaError, guard
from tests import test_workspace_d5_v16_integration as legacy
from tests.d5_capacity_gate import export_rows

store = legacy.store
if hasattr(legacy, "workspace_pg"):
    workspace_pg_proc, workspace_pg = legacy.workspace_pg_proc, legacy.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.timeout(600)]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


async def setup(store, *, authorize=True):
    old = await legacy.setup_keyed(store, authorize=False)
    packet = freeze(store, capture(store, old["program_id"]), union_safe=True)
    assert packet["limits"] == old["limits"]
    assert packet["operation_routes"] == old["operation_routes"]
    assert packet["operation_deadlines"] == old["operation_deadlines"]
    assert packet["scoring"] == old["scoring"]
    assert packet["schedule"] == old["schedule"]
    assert packet["probe_references"] == old["probe_references"]
    if authorize:
        authorize_fixture(store, packet)
    return packet


async def test_full_protected_union_campaign_exact_actual_schema_guard_and_no_replay(store):
    transports = []

    def factory(key):
        handler = KeyedCampaignTransport(key, repair_all=True, scenario="long_narratives")
        transports.append(handler)
        return handler

    try:
        packet = await setup(store)
        report = await run(store, packet, offline=True, transport_factory=factory)
        assert report["stop"] is None, report["stop"]
        assert len(report["outcomes"]) == 14
        assert (
            report["accounting"]["new_scope"]["messages"]
            == report["accounting"]["new_scope"]["counts"]
            == 44
        )
        assert report["accounting"]["retained_hold_usd"] == "0.875066"
        assert report["human_labels"] is None and not report["human_qualification"]
        observed = []
        phases = set()
        for t in transports:
            for (path, _), raw in zip(t.contacts, t.request_bodies, strict=True):
                if path.endswith("/messages"):
                    body = json.loads(raw)
                    context = json.loads(body["messages"][0]["content"])
                    phases.add((context["phase"], context.get("operation")))
                    observed.append(guard(body))
        assert len(observed) == 44
        assert {p for p, _ in phases} == {"draft", "check", "repair"}
        assert ("check", "probe") in phases
        assert all(x["documented_limits_pass"] and x["planning_headroom_pass"] for x in observed)
        assert max(x["expanded_union_nodes"] for x in observed) <= 12
        assert all(x["optional_parameters_conservative"] == 0 for x in observed)
        assert all(c["assessment_binding"]["status"] == "bound" for c in report["cases"])
        before = sum(len(t.contacts) for t in transports)
        repeated = await run(store, packet, offline=True, transport_factory=factory)
        assert repeated["accounting"]["new_scope"] == report["accounting"]["new_scope"]
        assert sum(len(t.contacts) for t in transports) == before
    finally:
        export_rows(store, "union-safe-full-campaign")


async def test_union_guard_refuses_oversized_actual_schema_before_any_http_contact(
    store, monkeypatch
):
    from src.workspace import d5_operations

    real = d5_operations.build_wire
    transports = []

    def oversized(context):
        result = real(context)
        result["output_config"]["format"]["schema"] = {
            "type": "object",
            "properties": {
                f"u{i}": {"anyOf": [{"type": "string"}, {"type": "null"}]} for i in range(17)
            },
            "required": [f"u{i}" for i in range(17)],
            "additionalProperties": False,
        }
        return result

    def factory(key):
        t = KeyedCampaignTransport(key)
        transports.append(t)
        return t

    try:
        packet = await setup(store)
        monkeypatch.setattr(d5_operations, "build_wire", oversized)
        before = legacy.contacts(store)
        with pytest.raises(ProviderSchemaError, match="documented_limit"):
            await run(store, packet, offline=True, transport_factory=factory)
        assert not any(t.contacts for t in transports)
        assert legacy.contacts(store) == before
    finally:
        export_rows(store, "union-safe-predispatch-refusal")


async def test_sealed_provider_policy_and_marker_cannot_drift(store):
    try:
        packet = await setup(store, authorize=False)
        for mutation in ("policy", "encoding", "marker", "schema"):
            changed = deepcopy(packet)
            if mutation == "policy":
                changed["provider_schema_compatibility_policy"]["documented_limits"][
                    "union_parameters"
                ] = 17
            elif mutation == "encoding":
                changed["wire_encoding_revision"] = "unknown"
            elif mutation == "marker":
                changed["cases"][0]["sealed"].pop("provider_schema_compatibility_revision")
            else:
                changed["cases"][0]["sealed"]["response_schemas"]["wire"]["properties"][
                    "unknown"
                ] = {"type": "string"}
            with pytest.raises(AdmissionError):
                verify_packet(changed)
    finally:
        export_rows(store, "union-safe-policy-drift")


@pytest.mark.parametrize("reject", [False, True])
async def test_canonical_unused_slots_reach_actual_checker_and_support_still_gates(store, reject):
    import httpx
    from jsonschema import Draft202012Validator

    from src.workspace.assistance_keyed_encoding import UNUSED

    class SparseSynthetic(KeyedCampaignTransport):
        async def __call__(self, request):
            result = await super().__call__(request)
            if not request.url.path.endswith("/messages"):
                return result
            body = json.loads(request.content)
            context = json.loads(body["messages"][0]["content"])
            if context["phase"] not in {"draft", "repair"}:
                return result
            value = result.json()
            block = next(b for b in value["content"] if b["type"] == "text")
            payload = json.loads(block["text"])
            response = payload["response"]
            for key in response["claims"]:
                if key != "c1":
                    response["claims"][key] = deepcopy(UNUSED)
            for field in ("background_claims", "assumption_claims", "limitation_claims"):
                response[field] = [key for key in response[field] if key == "c1"]
            for question in response["questions"]:
                question["claim_ids"] = ["c1"] if question["intent"] == "investigate_claim" else []
            for row in response["coverage"].values():
                row["context_claim_ids"] = [key for key in row["context_claim_ids"] if key == "c1"]
                if row["status"] == "answered":
                    row["answer_claim_ids"] = ["c1"]
            Draft202012Validator(body["output_config"]["format"]["schema"]).validate(payload)
            block["text"] = json.dumps(payload)
            value["id"] += "-separately-labelled-synthetic-sparse"
            return httpx.Response(200, json=value)

    handlers = []

    def factory(key):
        h = SparseSynthetic(key, repair_all=True, scenario="unsupported" if reject else "normal")
        handlers.append(h)
        return h

    try:
        packet = await setup(store)
        report = await run(
            store, packet, offline=True, transport_factory=factory, checkpoint_after=1
        )
        assert report["stop"] is None, report["stop"]
        assert len(report["outcomes"]) == 1
        assert report["outcomes"]["campaign-dev-learn"]["state"] == (
            "failed" if reject else "ready"
        )
        assert report["cases"][0]["assessment_binding"]["status"] == "bound"
        assert (
            report["accounting"]["new_scope"]["messages"]
            == report["accounting"]["new_scope"]["counts"]
            == 4
        )
        check_bodies = [
            json.loads(raw)
            for h in handlers
            for (path, _), raw in zip(h.contacts, h.request_bodies, strict=True)
            if path.endswith("/messages")
            and json.loads(json.loads(raw)["messages"][0]["content"])["phase"] == "check"
        ]
        assert len(check_bodies) == 2
        for b in check_bodies:
            assert guard(b)["documented_limits_pass"]
            assert len(json.loads(b["messages"][0]["content"])["claim_inputs"]) == 1
        assert report["human_labels"] is None
    finally:
        export_rows(store, "union-safe-sparse-support-" + str(reject))
