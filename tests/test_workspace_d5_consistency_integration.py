"""Protected v18 diagnostic: synthetic grants and HTTP, real disposable Postgres.

Complete archived generated text is immutable. Only explicitly synthetic responses
exercise the successor. Copied historical prices seed the checkpoint, not new usage.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from jsonschema import Draft202012Validator

from src.workspace import assistance_compact_encoding as compact
from src.workspace import assistance_consistency_contract as codec
from src.workspace import d5_compatibility as ctl
from src.workspace import d5_compatibility_packet as previous
from src.workspace import d5_consistency_packet as spec
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_fixture import install
from tests import test_workspace_consistency_contract as samples
from tests import test_workspace_d5_compatibility as old
from tests.d5_capacity_gate import export_rows

store = old.store
if hasattr(old, "workspace_pg"):
    workspace_pg_proc, workspace_pg = old.workspace_pg_proc, old.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.timeout(600)]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


_CACHE = None


class ArchivedTransport:
    """Original whole generated texts, synthetic envelopes/transport only."""

    def __init__(self, packet):
        self.packet = packet

    async def __call__(self, request):
        body = json.loads(request.content)
        count = request.url.path.endswith("count_tokens")
        case = next(
            c
            for c in self.packet["cases"]
            if c["count_digest" if count else "request_digest"] == _digest(body)
        )
        name = case["id"]
        if count:
            return httpx.Response(
                200,
                json={
                    "input_tokens": {
                        "learn-accepted-control": 6305,
                        "learn-list-control": 7813,
                        "learn-compact": 6021,
                        "checker-small": 8617,
                    }[name]
                },
            )
        if name == "learn-list-control":
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": ctl.GRAMMAR_ERROR},
                    "request_id": "synthetic-v17-stopped-list",
                },
            )
        value = samples.original(name)
        usage = {
            "learn-accepted-control": (6305, 130),
            "learn-compact": (6021, 1024),
            "checker-small": (8617, 2157),
        }[name]
        return httpx.Response(
            200,
            json={
                "id": "synthetic-archived-" + name,
                "type": "message",
                "model": body["model"],
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                "usage": dict(zip(("input_tokens", "output_tokens"), usage, strict=True)),
            },
        )


async def setup(store, authorize=True):
    global _CACHE
    if _CACHE is None:
        predecessor = await old.setup(store)
        result = await ctl.run(
            store, predecessor, transport=httpx.MockTransport(ArchivedTransport(predecessor))
        )
        assert result["stop"] is None, result
        rows = ctl.snapshots(store, predecessor)
        assert [r["state"] for r in rows] == [
            "ready",
            "uncertain",
            "failed",
            "unrun",
            "failed",
            "unrun",
        ]
        with store.pool.connection() as conn:
            # Reconstruct the recorded historical checkpoint in disposable storage.
            # These values are not synthetic provider measurements or new spending.
            for row, workflow, judge in [
                (rows[0], "0.013910", "0"),
                (rows[2], "0.022282", "0"),
                (rows[4], "0", "0.077608"),
            ]:
                conn.execute(
                    "UPDATE workspace_spend_reservations SET workflow=%s,judge=%s WHERE job_id=%s",
                    (workflow, judge, row["job_id"]),
                )
        snapshot = previous.capture(
            store, "evaluation", stopped_scope_id="compat-" + predecessor["packet_digest"][:24]
        )
        assert (
            snapshot["history"]["messages"],
            snapshot["history"]["counts"],
            snapshot["history"]["known_usd"],
            snapshot["history"]["unknown_usd"],
        ) == (76, 101, "2.252281", "2.275066")
        _CACHE = deepcopy((snapshot, predecessor))
    else:
        snapshot, predecessor = deepcopy(_CACHE)
        install(store, snapshot, fixture=True)
    packet = spec.freeze(snapshot, predecessor)
    if authorize:
        auth = ctl.template(packet)
        now = datetime.now(UTC)
        auth.update(
            approved=True,
            approved_by="Synthetic disposable fixture; not human or owner authority",
            approved_at=now.isoformat(),
            expires_at=min(
                now + timedelta(hours=1), datetime.fromisoformat(packet["programme_expiry"])
            ).isoformat(),
            approval_source="Synthetic test fixture only",
            authorization_kind="offline_fixture",
            transport_mode="mock",
            retained_liability_exception_approved=True,
        )
        assert auth["anticipated_received_rejection_continuation_approved"] is False
        ctl.record(store, packet, auth)
    return packet


class Transport:
    def __init__(self, packet, scenario=None, case="learn-compact"):
        self.packet, self.scenario, self.case = packet, scenario, case
        self.contacts = []

    async def __call__(self, request):
        body = json.loads(request.content)
        count = request.url.path.endswith("count_tokens")
        case = next(
            c
            for c in self.packet["cases"]
            if c["count_digest" if count else "request_digest"] == _digest(body)
        )
        name = case["id"]
        self.contacts.append((name, request.url.path, body))
        if count:
            return httpx.Response(
                200,
                json={
                    "input_tokens": 32001
                    if self.scenario == "oversized" and name == self.case
                    else 100
                },
            )
        if name == self.case and self.scenario == "grammar":
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": ctl.GRAMMAR_ERROR},
                    "request_id": "synthetic-v18-error",
                },
            )
        if name == self.case and self.scenario == "timeout":
            raise httpx.ReadTimeout(
                "Synthetic uncertain response; no external contact", request=request
            )
        if case["family"] == "checker":
            value = samples.synthetic_verdict(case["context"])
        else:
            legacy = deepcopy(case)
            legacy["policy"][codec.KEY] = compact.REVISION
            value = samples.synthetic_upgrade(old.draft(legacy, self.packet))
        if self.scenario == "archived_derivatives":
            if name == "learn-compact":
                value = samples.learn()[0]
            elif name == "checker-small":
                value = samples.synthetic_old_checker()[0]
        Draft202012Validator(case["schemas"]["wire"]).validate(value)
        if name == self.case and self.scenario == "invalid":
            value = {"response": {}}
        if name == self.case and self.scenario == "unsupported":
            value["claim_reviews"]["c1"]["decision"] = "unsupported"
        text = json.dumps(value, ensure_ascii=False)
        if name == self.case and self.scenario == "truncated":
            text = text[:-10]
        return httpx.Response(
            200,
            json={
                "id": "synthetic-v18-" + name,
                "type": "message",
                "model": body["model"],
                "stop_reason": "max_tokens"
                if self.scenario == "max_tokens" and name == self.case
                else "end_turn",
                "content": [{"type": "text", "text": text}],
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )


async def test_complete_four_request_path_and_no_replay(store):
    packet = await setup(store)
    handler = Transport(packet)
    try:
        result = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
        assert result["stop"] is None, result
        assert (
            len(handler.contacts) == 8
            and tuple(c["case_id"] for c in result["cases"]) == spec.ORDER
        )
        assert all(c["local_semantic_validity"] for c in result["cases"])
        assert not result["full_campaign_ready"] and not result["human_qualification"]
        rows = ctl.snapshots(store, packet)
        assert all(r["state"] == "ready" and not r["observation"]["content_accepted"] for r in rows)
        assert (
            rows[2]["observation"]["observed"]["derived_machine_summary"]["full_answer_credit"]
            is False
        )
        with store.pool.connection() as conn:
            from src.workspace.qualification_budget import census

            members = packet["basis_members"] + [
                c["owner"] for c in previous.compile_inputs(packet).values()
            ]
            current = census(conn, members[0], members=members)
        assert (
            current["messages"],
            current["counts"],
            current["known_usd"],
            current["unknown_usd"],
        ) == (80, 105, "2.252281", "2.275066")
        with pytest.raises(AdmissionError, match="no_replay"):
            await ctl.run(store, packet, transport=httpx.MockTransport(handler))
        assert len(handler.contacts) == 8
    finally:
        export_rows(store, "v18-four-request-offline")


@pytest.mark.parametrize("scenario", ["grammar", "timeout", "oversized"])
async def test_no_received_rejection_exception_or_retry(store, scenario):
    packet = await setup(store)
    handler = Transport(packet, scenario)
    try:
        result = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
        assert result["stop"] is not None, result
        assert len(handler.contacts) == (1 if scenario == "oversized" else 2)
        rows = ctl.snapshots(store, packet)
        assert all(r["state"] == "unrun" for r in rows[1:])
        if scenario == "grammar":
            assert rows[0]["state"] == "uncertain"
            assert rows[0]["observation"]["remote_compiler_acceptance"] is False
            assert rows[0]["observation"]["expected_received_grammar_rejection"] is False
        with pytest.raises(AdmissionError, match="no_replay"):
            await ctl.run(store, packet, transport=httpx.MockTransport(handler))
    finally:
        export_rows(store, "v18-stop-" + scenario)


@pytest.mark.parametrize("scenario", ["invalid", "truncated", "max_tokens"])
async def test_invalid_learn_skips_research_without_manufacturing_results(store, scenario):
    packet = await setup(store)
    handler = Transport(packet, scenario)
    result = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
    assert result["stop"] is None, result
    rows = ctl.snapshots(store, packet)
    assert rows[0]["state"] == "failed" and not rows[0]["observation"]["local_semantic_validity"]
    assert rows[1]["state"] == "unrun"
    assert len(handler.contacts) == 6
    assert not rows[0]["observation"]["content_accepted"]


async def test_valid_negative_checker_is_not_a_contract_failure_or_full_answer(store):
    packet = await setup(store)
    handler = Transport(packet, "unsupported", "checker-small")
    result = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
    assert result["stop"] is None
    obs = ctl.snapshots(store, packet)[2]["observation"]
    assert (
        obs["local_semantic_validity"]
        and obs["observed"]["derived_machine_summary"]["quality_gate"] == "FAIL"
    )
    assert not obs["content_accepted"] and len(handler.contacts) == 8


async def test_blank_authority_and_packet_drift_stop_before_contact(store):
    packet = await setup(store, authorize=False)
    handler = Transport(packet)
    result = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
    assert result["stop"] and not handler.contacts
    with pytest.raises(AdmissionError):
        ctl.record(store, packet, ctl.template(packet))
    for field in ["model", "max_tokens", "system"]:
        bad = deepcopy(packet)
        bad["cases"][0]["body"][field] = "drift"
        with pytest.raises(AdmissionError):
            previous.verify(bad)
    bad = deepcopy(packet)
    bad["cases"].append(deepcopy(bad["cases"][0]))
    with pytest.raises(AdmissionError):
        previous.verify(bad)


async def test_complete_original_derivatives_reach_remaining_production_validation(store):
    packet = await setup(store)
    handler = Transport(packet, "archived_derivatives")
    try:
        result = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
        assert result["stop"] is None and len(handler.contacts) == 8
        rows = ctl.snapshots(store, packet)
        learned = rows[0]["observation"]["observed"]
        assert rows[0]["observation"]["local_semantic_validity"]
        assert learned["reader_view"]["request_outcome"]["partial_parts"] == 3
        assert len(learned["draft"]["claims"]) == 5
        assert learned["provenance"]["support_ratio"] is None
        checked = rows[2]["observation"]["observed"]
        assert rows[2]["observation"]["local_semantic_validity"]
        assert checked["normalized"]["claim_quality"][0]["atomicity"] == "bundled"
        assert (
            checked["normalized"]["claim_quality"][1]["qualifications"]["comparator"] == "uncertain"
        )
        assert checked["derived_machine_summary"]["quality_gate"] == "FAIL"
        assert checked["derived_machine_summary"]["factual_prose_findings"] == 0
        assert checked["derived_machine_summary"]["coverage_critique_count"] == 1
        assert (
            not rows[0]["observation"]["content_accepted"]
            and not rows[2]["observation"]["content_accepted"]
        )
    finally:
        export_rows(store, "v18-complete-original-synthetic-derivatives")
