"""Six-request compatibility diagnostic; all transport and grants synthetic.

The portable seed reconstructs the 38/72/97 checkpoint in disposable Postgres,
never reads the live ledger or a key, and cannot authorize a provider client.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from src.workspace import assistance_capacity_contract as capacity
from src.workspace import assistance_keyed_contract as keyed
from src.workspace import d5_compatibility as ctl
from src.workspace import d5_compatibility_packet as spec
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_benchmark import read
from src.workspace.d5_campaign import run as campaign
from src.workspace.d5_capacity_transport import draft_payload
from src.workspace.d5_fixture import install
from src.workspace.d5_freeze import restore_input
from src.workspace.d5_keyed_transport import checker_payload
from tests import test_workspace_d5_union_integration as old
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


class StopSeed:
    async def __call__(self, request):
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 10672})
        return httpx.Response(
            400,
            json={
                "type": "error",
                "error": {"type": "invalid_request_error", "message": ctl.GRAMMAR_ERROR},
                "request_id": "synthetic-stopped-v16r2",
            },
        )


async def setup(store, authorize=True):
    global _CACHE
    if _CACHE is None:
        previous = await old.setup(store)
        stopped = await campaign(
            store, previous, offline=True, transport_factory=lambda _: StopSeed()
        )
        assert stopped["stop"] and len(stopped["outcomes"]) == 0
        snap = spec.capture(
            store, "evaluation", stopped_scope_id="d5-" + previous["packet_digest"][:24]
        )
        assert snap["history"]["counts"] == 97 and snap["history"]["unknown_usd"] == "2.075066"
        _CACHE = deepcopy(snap)
    else:
        snap = deepcopy(_CACHE)
        install(store, snap, fixture=True)
    root = (
        Path(__file__).resolve().parents[1] / "planning/15-evaluation-audit-and-recovery/evidence"
    )
    previous = read(root / "keyed-contract-v16r2/packet.json.gz")
    accepted = read(root / "capacity-policy-v15r2/packet.json.gz")["cases"][0]["sealed"]
    packet = spec.freeze(
        snap, previous, accepted["candidate_initial_wire"], accepted["task_policy"]
    )
    if authorize:
        auth = ctl.template(packet)
        now = datetime.now(UTC)
        auth.update(
            approved=True,
            approved_by="Synthetic disposable fixture, not human/owner authority",
            approved_at=now.isoformat(),
            expires_at=min(
                now + timedelta(hours=1), datetime.fromisoformat(packet["programme_expiry"])
            ).isoformat(),
            approval_source="synthetic test only",
            authorization_kind="offline_fixture",
            transport_mode="mock",
            retained_liability_exception_approved=True,
            anticipated_received_rejection_continuation_approved=True,
        )
        ctl.record(store, packet, auth)
    return packet


def draft(case, packet):
    original = read(
        Path(__file__).resolve().parents[1]
        / "planning/15-evaluation-audit-and-recovery/evidence/keyed-contract-v16r2/packet.json.gz"
    )
    sealed = deepcopy(original["cases"][0 if case["family"] == "learn" else 1]["sealed"])
    sealed["schema_revision"] = capacity.REVISION
    pol = (
        case["policy"]
        if case["encoding"] == "accepted-v15r2"
        else keyed.prior_policy(case["policy"])
    )
    sealed["task_policy"] = pol
    value = draft_payload({"sealed_request": sealed}, long=True)
    if case["encoding"] != "accepted-v15r2":
        e, c = capacity.normalize(value, list(case["units"]), case["purpose"], pol)
        value = keyed.wire_payload(e, c, case["policy"])
    return value


class Transport:
    def __init__(self, packet, scenario=None, case="learn-list-control", callback=None):
        self.packet, self.scenario, self.case, self.callback = packet, scenario, case, callback
        self.contacts = []

    async def __call__(self, request):
        body = json.loads(request.content)
        count = request.url.path.endswith("count_tokens")
        case = next(
            c
            for c in self.packet["cases"]
            if (c["count_digest"] if count else c["request_digest"]) == _digest(body)
        )
        self.contacts.append((case["id"], request.url.path, body))
        if count:
            return httpx.Response(
                200,
                json={
                    "input_tokens": 32001
                    if self.scenario == "oversized" and case["id"] == self.case
                    else 100
                },
            )
        if self.callback:
            self.callback(case)
        if self.scenario == "timeout" and case["id"] == self.case:
            raise httpx.ReadTimeout("Synthetic timeout; no provider contact", request=request)
        if self.scenario in {"grammar", "other400"} and case["id"] == self.case:
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": ctl.GRAMMAR_ERROR
                        if self.scenario == "grammar"
                        else "Other provider error",
                    },
                    "request_id": "synthetic-diagnostic-rejection",
                },
            )
        value = (
            checker_payload(case["context"], long=True)
            if case["family"] == "checker"
            else draft(case, self.packet)
        )
        Draft202012Validator(case["schemas"]["wire"]).validate(value)
        if self.scenario == "invalid" and case["id"] == self.case:
            value = {"response": {}}
        text = json.dumps(value, ensure_ascii=False)
        if self.scenario == "truncated" and case["id"] == self.case:
            text = text[:-10]
        result = {
            "id": "synthetic-diagnostic-" + case["id"],
            "type": "message",
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 100, "output_tokens": 100},
        }
        if self.scenario == "max_tokens" and case["id"] == self.case:
            result["stop_reason"] = "max_tokens"
        if self.scenario == "wrong_model" and case["id"] == self.case:
            result["model"] = "not-approved"
        if self.scenario == "bad_usage" and case["id"] == self.case:
            result["usage"] = {}
        if self.scenario == "duplicate" and case["id"] == self.case:
            result["id"] = "synthetic-diagnostic-learn-accepted-control"
        return httpx.Response(200, json=result)


async def test_complete_six_identity_protected_offline_roundtrip(store):
    packet = await setup(store)
    handler = Transport(packet)
    try:
        report = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
        assert report["stop"] is None, report
        assert len(handler.contacts) == 12
        assert all(c["local_semantic_validity"] is True for c in report["cases"]), report
        assert not report["full_campaign_ready"] and not report["human_qualification"]
        rows = ctl.snapshots(store, packet)
        assert all(r["state"] == "ready" and not r["observation"]["content_accepted"] for r in rows)
        compiled = spec.compile_inputs(packet)
        with store.pool.connection() as conn:
            members = packet["basis_members"] + [v["owner"] for v in compiled.values()]
            from src.workspace.qualification_budget import census

            current = census(conn, members[0], members=members)
        assert (
            current["messages"],
            current["counts"],
            current["known_usd"],
            current["unknown_usd"],
        ) == (78, 103, "2.138481", "2.075066")
        with pytest.raises(AdmissionError, match="no_replay"):
            await ctl.run(store, packet, transport=httpx.MockTransport(handler))
        assert len(handler.contacts) == 12
    finally:
        export_rows(store, "v17-six-request-protected-replay")


@pytest.mark.parametrize(
    "scenario",
    [
        "grammar",
        "other400",
        "timeout",
        "oversized",
        "invalid",
        "truncated",
        "max_tokens",
        "wrong_model",
        "bad_usage",
        "duplicate",
    ],
)
async def test_received_errors_uncertainty_and_invalid_outputs_are_not_acceptance(store, scenario):
    packet = await setup(store)
    handler = Transport(packet, scenario)
    try:
        report = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
        rows = ctl.snapshots(store, packet)
        failed = rows[1]["observation"]
        assert failed and not failed["content_accepted"]
        if scenario == "grammar":
            assert report["stop"] is None, report
            assert failed["remote_compiler_acceptance"] is False
            assert rows[1]["state"] == "uncertain"
            assert len(handler.contacts) == 12
            with store.pool.connection() as conn:
                hold = conn.execute(
                    "SELECT unknown FROM workspace_spend_reservations WHERE job_id=%s",
                    (rows[1]["job_id"],),
                ).fetchone()[0]
            assert str(hold) == "0.20"
        elif scenario in {"invalid", "truncated", "max_tokens"}:
            assert report["stop"] is None, report
            assert failed["local_semantic_validity"] is False and rows[1]["state"] == "failed"
        else:
            assert report["stop"], report
            assert len(handler.contacts) <= 4
    finally:
        export_rows(store, "v17-" + scenario)


async def test_operator_authority_required_no_self_grant_and_order_enforced(store):
    packet = await setup(store, authorize=False)
    handler = Transport(packet)
    with pytest.raises(AdmissionError, match="explicit_owner_approval"):
        ctl.record(store, packet, ctl.template(packet))
    report = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
    assert report["stop"] and not handler.contacts
    # Runner neither creates nor renews authorization.
    with store.pool.connection() as conn:
        assert not conn.execute(
            "SELECT 1 FROM workspace_d5_scopes WHERE scope_id=%s",
            ("compat-" + packet["packet_digest"][:24],),
        ).fetchone()


@pytest.mark.parametrize(
    "mutation", ["source", "scope", "parent", "history", "budget", "code", "settings"]
)
async def test_drift_and_admission_refuse_without_http(store, mutation, monkeypatch):
    packet = await setup(store)
    if mutation == "code":
        monkeypatch.setattr(spec, "producer", lambda: {})
    elif mutation == "settings":
        packet["cases"][0]["body"]["max_tokens"] += 1
    else:
        with store.pool.connection() as conn:
            if mutation == "source":
                conn.execute(
                    "UPDATE workspace_material SET data=data||'{\"wrong\":true}'::jsonb WHERE material_id=%s",
                    (next(iter(packet["source_bindings"]["materials"])),),
                )
            elif mutation == "scope":
                conn.execute(
                    "UPDATE workspace_d5_scopes SET state='revoked' WHERE scope_id=%s",
                    ("compat-" + packet["packet_digest"][:24],),
                )
            elif mutation == "parent":
                conn.execute(
                    "UPDATE workspace_d5_capacity_revisions SET record=record||'{\"wrong\":true}'::jsonb"
                )
            elif mutation == "history":
                conn.execute("UPDATE workspace_spend_reservations SET unknown=0 WHERE unknown>0")
            else:
                conn.execute(
                    "UPDATE workspace_budget_policies SET data=jsonb_set(data,'{per_job_usd}','\"0.01\"') WHERE owner=%s",
                    (next(iter(spec.compile_inputs(packet).values()))["owner"],),
                )
    handler = Transport(packet)
    if mutation in {"code", "settings"}:
        with pytest.raises(AdmissionError):
            await ctl.run(store, packet, transport=httpx.MockTransport(handler))
    else:
        report = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
        assert report["stop"], report
    assert not handler.contacts


async def test_direct_out_of_order_wrong_ids_and_fixture_boundary(store):
    packet = await setup(store)
    entry = spec.compile_inputs(packet)["checker-maximum"]
    handler = Transport(packet)
    adapter = ctl.DiagnosticAdapter(
        store, entry["owner"], restore_input(entry["input"]), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(AdmissionError, match="named_job"):
        adapter.start("alternate-id")
    with pytest.raises(AdmissionError, match="order_required|prerequisite"):
        adapter.start(entry["request_id"])
    assert not handler.contacts
    with pytest.raises(AdmissionError, match="provider_disabled"):
        ctl.DiagnosticAdapter(store, entry["owner"], restore_input(entry["input"]))
    auth = ctl.template(packet)
    with pytest.raises(AdmissionError):
        ctl.record(store, packet, auth)


async def test_prototypes_local_wire_plain_json_and_frozen_payload_bindings(store):
    packet = await setup(store, authorize=False)
    before = deepcopy(packet)
    for case in packet["cases"]:
        payload = (
            checker_payload(case["context"], long=True)
            if case["family"] == "checker"
            else draft(case, packet)
        )
        schemas = case["schemas"]
        for schema in schemas.values():
            Draft202012Validator(schema).validate(payload)
        normalized = spec.observed(payload, case, packet)
        assert normalized["human_labels"] is None
        alternative = spec.plain_json_alternative(case)
        assert (
            not alternative["live_in_scope"]
            and "format" not in alternative["body"]["output_config"]
        )
        assert spec.strict_json(json.dumps(payload)) == payload
        if case["encoding"] != "accepted-v15r2" and case["family"] != "checker":
            assert schemas["wire"] == transform_schema(schemas["local"])
    for malformed in ['{"x":1,"x":2}', '{"x":NaN}', "[]", '{"x":', "```json\n{}\n```"]:
        with pytest.raises((ValueError, AdmissionError)):
            spec.strict_json(malformed)
    assert packet == before


async def test_cli_report_exports_and_exact_jsonb_binding(store, monkeypatch, tmp_path):
    from src.workspace.d5_benchmark import write

    packet = await setup(store)
    assert spec.compile_inputs(packet) == spec.compile_inputs(json.loads(json.dumps(packet)))
    source = tmp_path / "packet.json"
    write(source, packet)
    for verb in ["verify", "template"]:
        target = tmp_path / (verb + ".json")
        monkeypatch.setattr(
            "sys.argv", ["diagnostic", verb, "--packet", str(source), "--out", str(target)]
        )
        ctl.main()
        assert target.exists()
        with pytest.raises(AdmissionError, match="preserve_original"):
            ctl.main()
    target = tmp_path / "report.json"
    handler = Transport(packet)
    report = await ctl.run(store, packet, transport=httpx.MockTransport(handler))
    ctl.reports(target, report)
    assert read(target)["accounting"]["cumulative"]["funded_programme_jobs"] == 44
    assert "UNMEASURED" in target.with_suffix(".md").read_text()
    assert "Quarantined" in target.with_suffix(".html").read_text()
    with pytest.raises(AdmissionError, match="preserve_original"):
        ctl.reports(target, report)


@pytest.mark.parametrize(
    "field",
    [
        "approved",
        "retained_liability_exception_approved",
        "anticipated_received_rejection_continuation_approved",
        "expires_at",
        "authorization_kind",
        "transport_mode",
        "packet_digest",
        "scope_id",
    ],
)
async def test_bad_external_authority_refuses_before_record(store, field):
    packet = await setup(store, authorize=False)
    now = datetime.now(UTC)
    value = ctl.template(packet)
    value.update(
        approved=True,
        approved_by="synthetic fixture only",
        approved_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=30)).isoformat(),
        approval_source="synthetic test",
        authorization_kind="offline_fixture",
        transport_mode="mock",
        retained_liability_exception_approved=True,
        anticipated_received_rejection_continuation_approved=True,
    )
    value[field] = False if field.endswith("approved") else "not-bound"
    with pytest.raises(AdmissionError):
        ctl.record(store, packet, value)


@pytest.mark.parametrize(
    "mutation", ["request", "count", "model", "SDK", "order", "digest", "reservation"]
)
async def test_packet_binding_drift(store, mutation):
    packet = await setup(store, authorize=False)
    if mutation == "SDK":
        packet["SDK"] = {}
    elif mutation == "order":
        packet["cases"].reverse()
    elif mutation == "digest":
        packet["packet_digest"] = "0" * 64
    else:
        key = {
            "request": "request_digest",
            "count": "count_digest",
            "reservation": "reservation_USD",
        }.get(mutation)
        if key:
            packet["cases"][0][key] = "wrong"
        else:
            packet["cases"][0]["body"]["model"] = "wrong"
    if mutation != "digest":
        packet["packet_digest"] = _digest({k: v for k, v in packet.items() if k != "packet_digest"})
    with pytest.raises(AdmissionError):
        spec.verify(packet)


@pytest.mark.parametrize("mutation", ["handle", "version", "offset", "quote", "material_hash"])
async def test_exact_evidence_cannot_be_relaxed_for_diagnostic(store, mutation):
    packet = await setup(store, authorize=False)
    case = deepcopy(packet["cases"][2])
    value = draft(case, packet)
    if mutation == "handle":
        value["response"]["claims"][0]["handles"] = ["unselected"]
    else:
        u = next(iter(case["units"].values()))
        field = {
            "version": "version_id",
            "offset": "start",
            "quote": "quote",
            "material_hash": "source_hash",
        }[mutation]
        u[field] = u[field] + 1 if field == "start" else "wrong"
        # Force the fixture claim to use the exact mutated handle.
        value["response"]["claims"][0]["handles"] = [next(iter(case["units"]))]
    with pytest.raises((ValueError, AdmissionError)):
        spec.observed(value, case, packet)
