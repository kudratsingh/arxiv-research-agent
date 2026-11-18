"""Offline report binding controls; synthetic judgments are not quality evidence."""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from src.workspace.admission import _digest
from src.workspace.d5_adapter import prepare_input
from src.workspace.d5_benchmark import read
from src.workspace.d5_comparison_transport import ComparisonCampaignTransport
from src.workspace.d5_compatibility_packet import materials
from src.workspace.d5_continuation_report import liabilities, probe_verdicts
from src.workspace.d5_report_binding import message_output

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def _receipt(raw):
    return {
        "received_bytes": len(raw),
        "http_status": 200,
        "complete_body": True,
        "credential_redacted": False,
        "body_gzip_base64": base64.b64encode(gzip.compress(raw, mtime=0)).decode(),
        "received_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _contact(index, endpoint, body, generation, response):
    raw = json.dumps(response, separators=(",", ":")).encode()
    return {
        "ordinal": index,
        "stage": "check",
        "state": "completed",
        "endpoint": endpoint,
        "body": body,
        "request_digest": _digest(body),
        "generation_request_digest": _digest(generation),
        "response": response,
        "http_body_receipt": _receipt(raw),
    }


@pytest.fixture(scope="module", params=range(4))
def probe_data(request):
    # Public frozen predecessor is always available in CI; no provider or credential.
    packet = read(
        ROOT / "planning/15-evaluation-audit-and-recovery/evidence/comparison-v19/packet.json.gz"
    )
    case = packet["probes"][request.param]
    body = case["wire"]
    count_body = {k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}}

    async def responses():
        transport = ComparisonCampaignTransport(case["id"])
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport), base_url="https://offline.invalid"
        ) as client:
            count = await client.post("/v1/messages/count_tokens", json=count_body)
            message = await client.post("/v1/messages", json=body)
        return count.json(), message.json()

    count_response, message_response = asyncio.run(responses())
    count = _contact(0, "messages/count_tokens", count_body, body, count_response)
    message = _contact(1, "messages", body, body, message_response)
    compact = prepare_input(
        case["sealed"],
        scope_id="report-only",
        packet_digest=packet["packet_digest"],
        case_id=case["id"],
        operation="probe",
        probe_wire=body,
        operation_routes=packet["operation_routes"],
        operation_deadlines=packet["operation_deadlines"],
        capacity_policy=packet["capacity_policy"],
    ).settings["d5_request"]
    snapshot = {
        "case_id": case["id"],
        "packet_digest": packet["packet_digest"],
        "operation": "probe",
        "state": "ready",
        "source_binding_intact": True,
        "request": compact,
        "contacts": [count, message],
        "steps": [
            {"stage": "check", "request_digest": _digest(body), "output": message_output(message)}
        ],
        "unknown_usd": "0",
        "workflow_usd": "0",
        "checker_usd": "0",
        "simulated": True,
    }
    return case, snapshot, packet, materials(packet)


def test_public_synthetic_probe_binds_frozen_wire_and_all_judgments(probe_data):
    result = probe_verdicts(*probe_data)
    assert result["binding"] == "bound", result
    assert len(result["verdicts"]) == 5
    assert result["request_digest"] == _digest(probe_data[0]["wire"])


@pytest.mark.parametrize(
    "mutation",
    [
        "case",
        "packet",
        "request",
        "source",
        "state",
        "missing_count",
        "ordinal",
        "count_body",
        "message_body",
        "receipt",
        "step",
        "count_response",
        "usage",
        "claims",
    ],
)
def test_probe_rejects_unbound_tampering(probe_data, mutation):
    case, original, packet, sources = probe_data
    snapshot = deepcopy(original)
    count, message = snapshot["contacts"]
    if mutation == "case":
        snapshot["case_id"] = "other"
    elif mutation == "packet":
        snapshot["packet_digest"] = "other"
    elif mutation == "request":
        snapshot["request"]["schema_revision"] = "other"
    elif mutation == "source":
        snapshot["source_binding_intact"] = False
    elif mutation == "state":
        message["state"] = "dispatching"
    elif mutation == "missing_count":
        snapshot["contacts"] = [message]
    elif mutation == "ordinal":
        count["ordinal"] = 1
    elif mutation == "count_body":
        count["body"]["model"] = "other"
        count["request_digest"] = _digest(count["body"])
    elif mutation == "message_body":
        message["body"]["model"] = "other"
        message["request_digest"] = _digest(message["body"])
    elif mutation == "receipt":
        message["http_body_receipt"]["received_sha256"] = "0" * 64
    elif mutation == "step":
        snapshot["steps"][0]["output"]["checks"][0]["decision"] = "abstain"
    elif mutation == "count_response":
        count["response"]["input_tokens"] = 32001
        count["http_body_receipt"] = _receipt(
            json.dumps(count["response"], separators=(",", ":")).encode()
        )
    elif mutation == "usage":
        message["response"]["usage"]["input_tokens"] = -1
        message["http_body_receipt"] = _receipt(
            json.dumps(message["response"], separators=(",", ":")).encode()
        )
    elif mutation == "claims":
        snapshot["steps"][0]["output"]["checks"][0]["claim_id"] = "substituted"
    result = probe_verdicts(case, snapshot, packet, sources)
    assert result["binding"] == "unavailable", mutation
    assert result["verdicts"] == {}


def test_unrun_probe_is_not_scored(probe_data):
    case, _, packet, sources = probe_data
    assert probe_verdicts(case, None, packet, sources)["verdicts"] == {}


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, args):
        if "workspace_evaluation_members" in query:
            return _Rows([("owner",)])
        assert "workspace_spend_reservations" in query
        return _Rows(self.rows)


@pytest.fixture
def financial(monkeypatch):
    from src.workspace import qualification_budget

    monkeypatch.setattr(
        qualification_budget,
        "census",
        lambda *a, **k: {"unknown_usd": "4.5", "pending_usd": "6.0", "known_usd": "2.0"},
    )
    rows = [
        (f"hold{i}", "owner", "failed", "1.0", "1.0", {"id": i}, Decimal("0"), Decimal("0"))
        for i in range(4)
    ]
    retained = [
        {
            "job_id": r[0],
            "owner": r[1],
            "state": r[2],
            "amount": r[3],
            "unknown": r[4],
            "data_digest": _digest(r[5]),
        }
        for r in rows
    ]
    return rows, retained


def test_financial_rows_reconcile_all_four_and_do_not_double_count(financial):
    rows, retained = financial
    rows += [
        ("unknown", "owner", "failed", "0.5", "0.5", {}, Decimal("0"), Decimal("0")),
        ("pending", "owner", "running", "2.0", "0", {}, Decimal("0.3"), Decimal("0.2")),
    ]
    result = liabilities(_Connection(rows), "synthetic", retained)
    assert result["financial_integrity"] == "PASS"
    assert len(result["validated_retained_components"]) == 4
    assert result["retained_liability_USD"] == "4.0"
    assert {r["classification"] for r in result["new_liabilities"]} == {
        "new_external_uncertainty",
        "new_pending_reservation",
    }
    assert (
        next(r for r in result["rows"] if r["job_id"] == "pending")["pending_exposure_USD"] == "1.5"
    )
    assert result["combined_exposure_USD"] == "8.0"
    assert result["unknown_is_subset_of_pending"] is True


@pytest.mark.parametrize("mutation", ["missing", "owner", "state", "amount", "unknown", "data"])
def test_missing_or_changed_historical_hold_is_explicit_failure(financial, mutation):
    rows, retained = financial
    if mutation == "missing":
        rows.pop(0)
    else:
        row = list(rows[0])
        index = {"owner": 1, "state": 2, "amount": 3, "unknown": 4, "data": 5}[mutation]
        row[index] = {"changed": True} if mutation == "data" else "different"
        if mutation in {"amount", "unknown"}:
            row[index] = "1.5"
        rows[0] = tuple(row)
    result = liabilities(_Connection(rows), "synthetic", retained)
    assert result["financial_integrity"] == "FAIL"
    assert len(result["validated_retained_components"]) == 3
    assert result["integrity_issues"][0]["reason"] == (
        "retained_hold_missing" if mutation == "missing" else "retained_hold_binding_drift"
    )


def test_preserved_synthetic_v20_probe_journals_when_available():
    archive = (
        Path.home()
        / "Machine-Learning-Projects/arxiv-evidence/d5-behavior-v20-20261117/debug-setup-02"
    )
    if not (archive / "RESULTS.json").exists() or not (archive / "DRAFT-PACKET.json.gz").exists():
        pytest.skip("owner-local synthetic debug fixture unavailable")
    packet = read(archive / "DRAFT-PACKET.json.gz")
    report = read(archive / "RESULTS.json")
    sources = materials(packet)
    for case in packet["probes"]:
        result = probe_verdicts(case, report["raw_results"].get(case["id"]), packet, sources)
        assert result["binding"] == "bound", (case["id"], result)
        assert len(result["verdicts"]) == 5


@pytest.mark.parametrize("mutation", ["sibling_span", "warnings", "page_mapping", "duplicate"])
def test_full_frozen_material_record_is_required_for_probe(probe_data, mutation):
    case, snapshot, packet, sources = probe_data
    changed = list(sources)
    source = changed[0]
    if mutation == "sibling_span":
        changed[0] = replace(
            source, spans=(*source.spans, replace(source.spans[0], span_id="extra"))
        )
    elif mutation == "warnings":
        changed[0] = replace(source, warnings=(*source.warnings, "changed extraction warning"))
    elif mutation == "page_mapping":
        changed[0] = replace(source, page_numbers=(999,))
    else:
        changed.append(source)
    observed = probe_verdicts(case, snapshot, packet, changed)
    assert observed == {
        "binding": "unavailable",
        "reason": "frozen_material_record_drift",
        "verdicts": {},
    }


class _ScopeConnection:
    def __init__(self, row):
        self.row = row

    def execute(self, query, args):
        assert query == "SELECT state,data FROM workspace_d5_scopes WHERE scope_id=%s"
        assert args == ("scope",)
        return self

    def fetchone(self):
        return self.row


@pytest.mark.parametrize("state", ["stopped", "revoked", "expired", "active"])
def test_later_report_recovers_persisted_terminal_stop(state):
    from src.workspace.d5_continuation_report import terminal_scope

    stop = {"case_id": "last", "stage": "outcome", "reason": "accounting failure"}
    result = terminal_scope(_ScopeConnection((state, {"campaign_stop": stop})), "scope", None)
    assert result["stop"] == stop
    assert result["terminal"] is True
    assert result["integrity"] is None


@pytest.mark.parametrize("state", ["stopped", "revoked", "expired"])
def test_terminal_scope_without_stop_does_not_become_active(state):
    from src.workspace.d5_continuation_report import terminal_scope

    result = terminal_scope(_ScopeConnection((state, {})), "scope", None)
    assert result["terminal"] is True


@pytest.mark.parametrize(
    "row, reason",
    [
        (None, "scope_missing"),
        (("stopped", {"campaign_stop": "invalid"}), "invalid_persisted_stop"),
        (("active", {}), "supplied_stop_differs_from_persisted"),
    ],
)
def test_stop_integrity_refuses_missing_or_contradictory_binding(row, reason):
    from src.workspace.d5_continuation_report import terminal_scope

    assert terminal_scope(_ScopeConnection(row), "scope", {"reason": "stop"})["integrity"] == reason


def test_case_census_distinguishes_attempted_jobs_without_outcomes():
    from src.workspace.d5_continuation_report import case_census

    ids = ["ready", "failed", "uncertain", "unrun", "recorded"]
    raw = {key: {"state": key} for key in ids[:3]}
    compiled = {key: {"stage": "C"} for key in ids}
    result = case_census(ids, compiled, raw, {"recorded": {"state": "failed"}})
    assert [result[key]["state"] for key in ids] == ids[:4] + ["failed"]
    assert all(result[key]["attempted"] for key in ids[:3])
    assert all(not result[key]["outcome_recorded"] for key in ids[:4])
    assert result["recorded"]["outcome_recorded"] is True


@pytest.mark.parametrize(
    "stop_kind", ["none", "persisted", "terminal_without_detail", "mismatch", "version_drift"]
)
def test_complete_report_cannot_erase_a_terminal_stop(monkeypatch, stop_kind):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from src.workspace import (
        d5_benchmark,
        d5_campaign_report,
        d5_continuation_report,
        d5_freeze,
        executor,
    )
    from tests.test_workspace_d5_behavior_scoring import ideal_snapshots

    packet = read(
        ROOT / "planning/15-evaluation-audit-and-recovery/evidence/comparison-v19/packet.json.gz"
    )
    packet["continuation_lineage"] = {"basis": "Synthetic v20 report wrapper control"}
    packet["continuation_producer"] = {"basis": "Synthetic wrapper code identity"}
    sources = materials(packet)
    raw = ideal_snapshots(packet["cases"], packet, sources)
    compiled = {c["id"]: {"owner": "fixture", "stage": "C"} for c in packet["cases"]}
    compiled.update({p["id"]: {"owner": "fixture", "stage": "D"} for p in packet["probes"]})
    stop = {"case_id": packet["cases"][-1]["id"], "stage": "outcome", "reason": "settlement_drift"}
    persisted = stop if stop_kind in {"persisted", "mismatch"} else None
    state = "active" if stop_kind in {"none", "version_drift"} else "stopped"
    conn = _ScopeConnection((state, {"campaign_stop": persisted} if persisted else {}))

    @contextmanager
    def connection():
        yield conn

    store = SimpleNamespace(pool=SimpleNamespace(connection=connection))
    base = {
        "raw_results": raw,
        "outcomes": {k: {"state": "ready"} for k in raw},
        "accounting": {"new_scope": {"known_usd": "1.0"}},
    }

    def check_storage(*args):
        if stop_kind == "version_drift":
            from src.workspace.admission import AdmissionError

            raise AdmissionError("d5_frozen_source_changed")

    monkeypatch.setattr(d5_benchmark, "check_storage", check_storage)
    monkeypatch.setattr(d5_campaign_report, "_legacy_results", lambda *a, **k: base)
    monkeypatch.setattr(d5_freeze, "compile_inputs", lambda p: compiled)
    monkeypatch.setattr(
        d5_continuation_report,
        "terminal_scope",
        lambda c, scope, supplied: {
            "state": state,
            "stop": persisted,
            "terminal": state == "stopped",
            "integrity": "supplied_stop_differs_from_persisted"
            if stop_kind == "mismatch"
            else None,
        },
    )
    monkeypatch.setattr(
        d5_continuation_report,
        "liabilities",
        lambda *a: {
            "financial_integrity": "PASS",
            "retained_liability_USD": "2.275066",
            "validated_retained_components": [],
            "new_liabilities": [],
        },
    )
    monkeypatch.setattr(
        executor.FakeExecutor,
        "_sources",
        lambda self, c, o, ids: [m for m in sources if m.material_id in ids],
    )
    result = d5_continuation_report.results(store, packet)
    assert result["stop"] == persisted
    if state == "stopped" or stop_kind == "version_drift":
        assert result["behavioral_gate"] == result["machine_quality"] == "FAIL"
        assert result["machine_behaviorally_satisfactory_results"] == 0
        assert result["accounting"]["cost_per_behaviorally_satisfactory_result"] is None
        assert (
            "frozen_source_storage_drift"
            if stop_kind == "version_drift"
            else "durable_campaign_terminal_or_unbound"
        ) in result["gate_reasons"]
        if stop_kind == "version_drift":
            assert all(
                c["assessment_binding"]["status"] == "unavailable" for c in result["workflows"]
            )
            assert all(b["binding"] == "unavailable" for b in result["probe_bindings"].values())
            assert result["denominators"]["reviewed_claim_findings"] == 0
    else:
        assert result["machine_behaviorally_satisfactory_results"] > 0
    assert result["analysis_receipt"]["historical_records_modified"] is False
