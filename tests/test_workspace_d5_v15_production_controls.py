"""Independent protected v15 failures; copied sources and synthetic authority only.

Transport mutations are deliberate software controls, not scientific judgments.
Every test preserves both original liabilities and exports evidence before its
unique disposable schema is dropped. No owner ledger or provider is contacted.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from src.workspace.admission import AdmissionError, GenerationAdmission, _digest
from src.workspace.d5_benchmark import read, write
from src.workspace.d5_campaign import run
from src.workspace.d5_campaign_operator import authorize_fixture
from src.workspace.d5_capacity_transport import CapacityCampaignTransport
from tests import test_workspace_d5_campaign as base
from tests.d5_capacity_gate import export_rows, prepare

store = base.store
if hasattr(base, "workspace_pg"):
    workspace_pg_proc, workspace_pg = base.workspace_pg_proc, base.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.timeout(600)]

# Only immutable historical fixture rows are reused. Every test still receives
# a fresh schema, packet, synthetic grant, protected admission and transport.
_SYNTHETIC_PARENT = None


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


@pytest.fixture(autouse=True)
def retain_before_teardown(request, store):
    yield
    export_rows(store, request.node.name)


async def protected_packet(store):
    """Use an explicit retained snapshot locally; rebuild the synthetic chain in CI."""
    from src.workspace.d5_campaign_v15_packet import capture, freeze
    from src.workspace.d5_fixture import install
    from src.workspace.schemas import ProfileData

    path = os.environ.get("WORKSPACE_D5_V15_PARENT_SNAPSHOT")
    if path:
        snapshot = read(Path(path))
    else:
        global _SYNTHETIC_PARENT
        if _SYNTHETIC_PARENT is None:
            from tests.d5_campaign_gate import storage

            with storage() as seed_store:
                try:
                    # Stop before prospective authorization: cached rows confer
                    # no v15 scope, stage, budget or provider authority.
                    await prepare(seed_store, authorize=False)
                    _SYNTHETIC_PARENT = capture(seed_store, "evaluation")
                finally:
                    export_rows(seed_store, "production-controls-historical-seed")
        snapshot = deepcopy(_SYNTHETIC_PARENT)
    if "records" in snapshot:
        names = {
            "workspace_programme_amendments": "recorded_amendments",
            "workspace_programme_successor_amendments": "recorded_successor_amendments",
            "workspace_programme_third_amendments": "recorded_third_amendments",
            "workspace_programme_capacity_amendments": "recorded_capacity_amendments",
            "workspace_d5_scopes": "historical_scopes",
            "workspace_d5_stage_authorizations": "historical_stage_grants",
            "workspace_d5_case_runs": "historical_case_runs",
            "workspace_d5_campaign_extensions": "recorded_campaign_extensions",
            "workspace_d5_campaign_revocations": "recorded_campaign_revocations",
            "workspace_d5_campaign_outcomes": "recorded_campaign_outcomes",
            "workspace_d5_campaign_successors": "recorded_campaign_successors",
            "workspace_d5_campaign_successor_revocations": "recorded_campaign_successor_revocations",
        }
        snapshot = {
            **snapshot,
            **{target: snapshot["records"].get(source, []) for source, target in names.items()},
            "profile": ProfileData().model_dump(mode="json"),
        }
    install(store, snapshot, fixture=True)
    packet = freeze(store, capture(store, snapshot["program_id"]))
    authorize_fixture(store, packet)
    return packet


def held_rows(store):
    with store.pool.connection() as conn:
        rows = conn.execute(
            "SELECT j.id,to_jsonb(j),to_jsonb(r) FROM workspace_generation_jobs j "
            "JOIN workspace_spend_reservations r ON r.job_id=j.id WHERE r.unknown>0 ORDER BY j.id"
        ).fetchall()
    return {row[0]: row for row in rows}


def retain(label, packet, reports, transports):
    root = Path(os.environ.get("D5_TEST_EVIDENCE_DIR", "build/d5-v15-test-evidence"))
    write(
        root / (label + "-" + uuid4().hex + ".json.gz"),
        {
            "packet": packet,
            "reports": reports,
            "transport_contacts": {key: value.contacts for key, value in transports.items()},
            "synthetic": True,
            "real_provider_contacts": 0,
            "real_count_contacts": 0,
        },
    )


def selected_case(packet, mode):
    return next(
        case["id"]
        for case in packet["cases"]
        if case["cohort"] == "development" and case["mode"] == mode
    )


class PartialBody(httpx.AsyncByteStream):
    def __init__(self, body, *, timeout):
        self.body, self.timeout = body, timeout

    async def __aiter__(self):
        # Separate chunks prove that more than one received portion is retained.
        yield self.body[:17]
        yield self.body[17:]
        if self.timeout:
            raise httpx.ReadTimeout("Synthetic timeout after received prefix")
        # The cap control must stop before this tail, not consume and accept it.
        yield b"UNREAD-TAIL"


class CorruptTransport(CapacityCampaignTransport):
    """Mutate received output only, retaining the production request and journal."""

    def __init__(self, key, failure, *, store=None, entry=None):
        checker_failures = {
            "missing_judgment",
            "wrong_digest",
            "checker_max_tokens",
            "truncated_checker",
        }
        scenarios = {"oversized", "provider_error", "uncertain", "reject"}
        super().__init__(
            key,
            repair_all=failure in checker_failures,
            scenario=failure if failure in scenarios else "normal",
        )
        self.failure, self.store, self.entry = failure, store, entry

    async def __call__(self, request):
        body = json.loads(request.content)
        if request.url.path.endswith("/messages/count_tokens"):
            return await super().__call__(request)
        context = json.loads(body["messages"][0]["content"])
        phase = context["phase"]
        if self.failure in {"partial_timeout", "partial_cap"} and phase == "draft":
            self.contacts.append((request.url.path, _digest(body)))
            if self.failure == "partial_timeout":
                prefix = b'{"content":[{"type":"text","text":"incomplete-' + bytes([0xFF, 0x80])
            else:
                cap = self.entry["input"]["settings"]["response_bytes"]
                prefix = b'{"partial":"' + b"x" * (cap + 1 - len(b'{"partial":"'))
            self.received_prefix = prefix
            return httpx.Response(
                200, stream=PartialBody(prefix, timeout=self.failure == "partial_timeout")
            )
        if self.failure in {"cancel", "restart"} and phase == "check":
            self.contacts.append((request.url.path, _digest(body)))
            with self.store.pool.connection() as conn:
                job_id = conn.execute(
                    "SELECT job_id FROM workspace_d5_case_runs WHERE scope_id=%s AND case_id=%s",
                    (self.entry["input"]["settings"]["d5_scope_id"], self.key),
                ).fetchone()[0]
            control = GenerationAdmission(self.store)
            if self.failure == "cancel":
                control.cancel(self.entry["owner"], job_id)
                raise asyncio.CancelledError("Synthetic cancellation after dispatched checker")
            control.recover(self.entry["owner"], job_id)
            raise TimeoutError("Synthetic restart before checker response")
        response = await super().__call__(request)
        value = response.json()
        if phase == "check" and self.checks == 2:
            if self.failure == "truncated_checker":
                value["content"] = [{"type": "text", "text": '{"revision":'}]
            elif self.failure == "checker_max_tokens":
                value["stop_reason"] = "max_tokens"
            elif self.failure in {"missing_judgment", "wrong_digest"}:
                text = next(block for block in value["content"] if block["type"] == "text")
                payload = json.loads(text["text"])
                if self.failure == "missing_judgment":
                    payload["claim_reviews"].pop()
                else:
                    payload["claim_reviews"][0]["input_digest"] = "sha256:" + "0" * 64
                text["text"] = json.dumps(payload)
        elif phase in {"draft", "repair"} and self.failure == "unselected_handle":
            payload = json.loads(value["content"][0]["text"])
            payload["response"]["claims"][0]["handles"] = ["not-selected-in-this-sealed-request"]
            value["content"][0]["text"] = json.dumps(payload)
        return httpx.Response(response.status_code, json=value)


async def execute(store, packet, target, failure):
    from src.workspace.d5_campaign_packet import compile_campaign

    compiled = compile_campaign(packet)
    transports = {}

    def factory(key):
        transports[key] = CorruptTransport(
            key, failure if key == target else "normal", store=store, entry=compiled[key]
        )
        return transports[key]

    count = packet["schedule"].index(target) + 1
    report = await run(
        store, packet, offline=True, transport_factory=factory, checkpoint_after=count
    )
    retain(failure + "-" + target, packet, [report], transports)
    return report, transports


def assert_original_holds(store, before):
    after = held_rows(store)
    assert len(before) == 2
    assert {key: after[key] for key in before} == before
    return after


def case_report(report, target):
    return next(case for case in report["cases"] if case["id"] == target)


async def assert_stopped_no_replay(store, packet, transports):
    contacts = {key: list(value.contacts) for key, value in transports.items()}
    calls = []
    with pytest.raises(AdmissionError):
        await run(store, packet, offline=True, transport_factory=lambda key: calls.append(key))
    assert calls == []
    assert {key: value.contacts for key, value in transports.items()} == contacts


@pytest.mark.parametrize("mode", ["learn", "research"])
@pytest.mark.parametrize(
    "failure", ["missing_judgment", "wrong_digest", "truncated_checker", "checker_max_tokens"]
)
async def test_checker_contract_failures_never_become_judgments_or_extra_repairs(
    store, mode, failure
):
    packet = await protected_packet(store)
    before = held_rows(store)
    target = selected_case(packet, mode)
    report, transports = await execute(store, packet, target, failure)
    assert report["stop"]["case_id"] == target
    assert report["stop"]["automatic_retries"] == 0
    assert list(transports) == packet["schedule"][: packet["schedule"].index(target) + 1]
    value = report["raw_results"][target]
    messages = [c for c in value["contacts"] if c["endpoint"] == "messages"]
    assert [contact["stage"] for contact in messages] == ["draft", "check", "repair", "check"]
    assert sum(c["stage"] == "repair" for c in messages) == 1
    assert [step["stage"] for step in value["steps"]] == ["draft", "check", "repair"]
    case = case_report(report, target)
    assert case["completion"] is False and case["human_qualified"] is False
    assert case["assessment_binding"]["status"] == "unavailable"
    assert case["whole_claim_support"] is case["machine_coverage"] is None
    assert_original_holds(store, before)
    if failure == "checker_max_tokens":
        last = messages[-1]["response"]
        assert last["stop_reason"] == "max_tokens"
        text = next(c["text"] for c in last["content"] if c["type"] == "text")
        assert isinstance(json.loads(text), dict)  # complete JSON still is not a complete response
    await assert_stopped_no_replay(store, packet, transports)


@pytest.mark.parametrize("mode", ["learn", "research"])
async def test_unselected_output_handle_is_rejected_without_checker_dispatch(store, mode):
    packet = await protected_packet(store)
    before = held_rows(store)
    target = selected_case(packet, mode)
    report, transports = await execute(store, packet, target, "unselected_handle")
    assert report["stop"]["case_id"] == target
    value = report["raw_results"][target]
    assert [c["stage"] for c in value["contacts"] if c["endpoint"] == "messages"] == ["draft"]
    assert case_report(report, target)["assessment_binding"]["status"] == "unavailable"
    assert_original_holds(store, before)
    await assert_stopped_no_replay(store, packet, transports)


@pytest.mark.parametrize("mode", ["learn", "research"])
async def test_changed_selected_quote_cannot_reuse_the_exact_grant(store, mode):
    from src.workspace.d5_adapter import D5Adapter
    from src.workspace.d5_campaign_packet import compile_campaign
    from src.workspace.d5_freeze import restore_input

    packet = await protected_packet(store)
    before = held_rows(store)
    target = selected_case(packet, mode)
    # The adapter receives a changed seal, while the scope still authorizes the
    # original exact input. Quote text cannot be smuggled through a valid handle.
    entry = deepcopy(compile_campaign(packet)[target])
    units = entry["input"]["settings"]["d5_request"]["units"]
    units[next(iter(units))]["quote"] = "Fabricated quotation absent from the selected material"
    transport = CapacityCampaignTransport(target)
    with pytest.raises(AdmissionError, match="^d5_selected_evidence_drift$"):
        adapter = D5Adapter(
            store,
            entry["owner"],
            restore_input(entry["input"]),
            transport=httpx.MockTransport(transport),
        )
        adapter.start(entry["input"]["settings"]["d5_request_id"])
    assert transport.contacts == []
    assert_original_holds(store, before)
    retain("changed-quote-" + mode, packet, [], {target: transport})


@pytest.mark.parametrize(
    "failure", ["oversized", "provider_error", "uncertain", "cancel", "restart"]
)
async def test_provider_or_interruption_failure_preserves_holds_and_no_replay(store, failure):
    packet = await protected_packet(store)
    before = held_rows(store)
    target = selected_case(packet, "learn")
    report, transports = await execute(store, packet, target, failure)
    assert report["stop"]["case_id"] == target and report["stop"]["automatic_retries"] == 0
    assert list(transports) == [target]
    value = report["raw_results"][target]
    case = case_report(report, target)
    assert case["completion"] is False
    assert case["assessment_binding"]["status"] == "unavailable"
    after = assert_original_holds(store, before)
    if failure == "oversized":
        assert len(transports[target].contacts) == 1
        assert value["contacts"][0]["endpoint"] == "messages/count_tokens"
        assert len(after) == 2 and value["unknown_usd"] == "0"
    else:
        assert len(after) == 3
        assert value["unknown_usd"] == "1.20"
        assert report["accounting"]["cumulative"]["unknown_usd"] == "2.075066"
        if failure == "provider_error":
            last = value["contacts"][-1]["response"]
            assert last["http_status"] == 400 and last["complete_body"] is True
            assert last["usage_validated"] is False
        else:
            assert value["contacts"][-1]["state"] == "dispatching"
    await assert_stopped_no_replay(store, packet, transports)


@pytest.mark.parametrize("mode", ["learn", "research"])
async def test_complete_negative_quality_remains_failed_after_one_repair(store, mode):
    from src.workspace.d5_adapter import D5Adapter
    from src.workspace.d5_campaign_packet import compile_campaign
    from src.workspace.d5_campaign_v15_policy import development_contract
    from src.workspace.d5_freeze import restore_input

    packet = await protected_packet(store)
    before = held_rows(store)
    target = selected_case(packet, mode)
    report, transports = await execute(store, packet, target, "reject")
    assert report["stop"] is None
    value = report["raw_results"][target]
    assert value["state"] == "failed"
    assert [s["stage"] for s in value["steps"]] == ["draft", "check", "repair", "check"]
    assert len(transports[target].contacts) == 8
    case = case_report(report, target)
    assert case["completion"] is False and case["human_qualified"] is False
    assert case["assessment_binding"]["status"] == "bound"
    assert case["whole_claim_support"]["unsupported"] == (8 if mode == "learn" else 12)
    with store.pool.connection() as conn:
        contract = development_contract(conn, "d5-" + packet["packet_digest"][:24], target)
    assert contract["contract_complete"] is True and contract["quality_accepted"] is False
    assert_original_holds(store, before)
    entry = compile_campaign(packet)[target]
    restarted = D5Adapter(
        store,
        entry["owner"],
        restore_input(entry["input"]),
        transport=httpx.MockTransport(transports[target]),
    )
    repeated = restarted.start(entry["input"]["settings"]["d5_request_id"])
    assert repeated["id"] == value["id"] and repeated["state"] == "failed"
    with pytest.raises(AdmissionError):
        await restarted.advance(repeated["id"])
    assert len(transports[target].contacts) == 8
    assert_original_holds(store, before)


@pytest.mark.parametrize("failure", ["partial_timeout", "partial_cap"])
async def test_partial_body_preserves_every_received_byte_and_unknown_hold(store, failure):
    packet = await protected_packet(store)
    before = held_rows(store)
    target = selected_case(packet, "learn")
    report, transports = await execute(store, packet, target, failure)
    assert report["stop"]["case_id"] == target and report["stop"]["automatic_retries"] == 0
    assert list(transports) == [target]
    value = report["raw_results"][target]
    assert value["state"] == "uncertain" and value["result"] is None
    assert len(value["contacts"]) == 2 and value["contacts"][-1]["state"] == "dispatching"
    contact = value["contacts"][-1]
    assert "response" not in contact
    partial = contact["partial_response"]
    expected = transports[target].received_prefix
    assert partial["complete_body"] is False and partial["usage_validated"] is False
    assert partial["acceptance"] == "unavailable" and partial["http_status"] == 200
    assert partial["received_bytes"] == len(expected)
    assert partial["received_sha256"] == hashlib.sha256(expected).hexdigest()
    assert base64.b64decode(partial["received_body_base64"], validate=True) == expected
    assert partial["credential_redacted"] is False
    events = [row["event"] for row in contact["timing"]["events"]]
    assert events == [
        "dispatch",
        "first_body_byte",
        "timeout" if failure == "partial_timeout" else "error",
    ]
    if failure == "partial_cap":
        assert report["stop"]["reason"] == "response_size_exceeded"
        assert len(expected) == 4194305
        assert not expected.endswith(b"UNREAD-TAIL")
    case = case_report(report, target)
    assert case["completion"] is False and case["assessment_binding"]["status"] == "unavailable"
    assert case["whole_claim_support"] is case["machine_coverage"] is None
    assert value["unknown_usd"] == "1.20"
    assert len(assert_original_holds(store, before)) == 3
    await assert_stopped_no_replay(store, packet, transports)
