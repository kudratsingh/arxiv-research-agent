"""v20 authoring guidance never enters a checker request."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.workspace.admission import _digest
from src.workspace.d5_adapter import (
    D5Adapter,
    D5ProbeAdapter,
    checker_context,
    initial_context,
    prepare_input,
)
from src.workspace.d5_campaign_v19_packet import predecessor, upgrade
from src.workspace.d5_capacity_policy import DEADLINES, ROUTES
from src.workspace.d5_capacity_policy import POLICY as CAPACITY_POLICY
from src.workspace.d5_comparison_transport import draft_payload
from src.workspace.d5_operations import wire
from src.workspace.d5_quality_guidance import GUIDANCE_VERSION, guidance
from src.workspace.d5_report_binding import current_check, message_output
from tests.test_workspace_d5_behavior_scoring import retained_materials, synthetic_snapshot

pytestmark = pytest.mark.unit


def test_v20_actual_stage_wires_isolate_guidance_and_bind_latest_response():
    packet = predecessor()
    original = packet["cases"][0]
    sealed = upgrade(original["sealed"])
    sealed["quality_guidance_revision"] = GUIDANCE_VERSION
    context = initial_context(sealed)
    assert context["authoring_guidance"]["text"] == guidance("draft")
    draft = draft_payload(context, long=False)
    materials = retained_materials(packet)
    case = {**original, "sealed": sealed}
    snap = synthetic_snapshot(case, draft, materials, ROUTES, recheck=True)
    for step in snap["steps"]:
        step["model_id"] = "synthetic-offline"
    sealed["capacity"]["stage_input_bytes_max"] = dict.fromkeys(
        ("draft", "check", "repair", "recheck"), 9999999
    )
    sealed["candidate_initial_wire_digest"] = _digest(wire(initial_context(sealed), ROUTES))
    settings = prepare_input(
        sealed,
        scope_id="test",
        packet_digest="0" * 64,
        case_id="synthetic",
        operation_routes=ROUTES,
        operation_deadlines=DEADLINES,
        capacity_policy=CAPACITY_POLICY,
        repair_located_prose=True,
    ).settings
    settings["d5_request"]["candidate_initial_wire_digest"] = _digest(
        wire(initial_context(settings["d5_request"]), ROUTES)
    )
    adapter = D5Adapter.__new__(D5Adapter)
    adapter.inputs = SimpleNamespace(settings=settings)
    adapter._context = lambda: ([], materials)
    adapter._response_output = lambda response, body: message_output(
        {
            "body": body,
            "response": response,
            "stage": json.loads(body["messages"][0]["content"])["phase"],
        }
    )
    for count, phase, expected in (
        (0, "draft", "draft"),
        (1, "check", None),
        (2, "repair", "repair"),
        (3, "check", None),
    ):
        selected = {"steps": snap["steps"][:count], "contacts": snap["contacts"][: count * 2]}
        adapter.snapshot = lambda _job, selected=selected: selected
        result = adapter.request("synthetic") if count else adapter.request()
        request = json.loads(result["body"]["messages"][0]["content"])
        assert result["stage"] == phase
        assert request["sealed_request"]["quality_guidance_revision"] == GUIDANCE_VERSION
        if expected:
            assert request["authoring_guidance"]["text"] == guidance(expected)
        else:
            assert "authoring_guidance" not in request
            assert request["role"] == "checker"
            assert request["checked_response_digest"] == _digest(snap["steps"][count - 1]["output"])
    bound = current_check(sealed, snap, materials, routes=ROUTES)
    assert bound["binding"]["status"] == "bound"
    expected_wire = wire(checker_context(sealed, draft, materials), ROUTES)
    assert bound["context"] == json.loads(expected_wire["messages"][0]["content"])


def test_legacy_context_and_probe_body_unchanged():
    packet = predecessor()
    sealed = upgrade(packet["cases"][0]["sealed"])
    legacy = initial_context(sealed)
    assert "authoring_guidance" not in legacy
    draft = draft_payload(legacy, long=False)
    assert "authoring_guidance" not in checker_context(sealed, draft, retained_materials(packet))
    probe = deepcopy(packet["probes"][0]["wire"])
    assert "authoring_guidance" not in json.loads(probe["messages"][0]["content"])
    probe_case = packet["probes"][0]
    settings = prepare_input(
        probe_case["sealed"],
        scope_id="test",
        packet_digest="0" * 64,
        case_id=probe_case["id"],
        operation="probe",
        probe_wire=probe,
        operation_routes=ROUTES,
        operation_deadlines=DEADLINES,
        capacity_policy=CAPACITY_POLICY,
    ).settings
    adapter = D5ProbeAdapter.__new__(D5ProbeAdapter)
    adapter.inputs = SimpleNamespace(settings=settings)
    adapter._context = lambda: ([], retained_materials(packet))
    actual = adapter.request()
    assert actual["body"] == probe
    assert "authoring_guidance" not in json.loads(actual["body"]["messages"][0]["content"])
