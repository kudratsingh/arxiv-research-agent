"""Offline report binding controls; synthetic judgments are not quality evidence."""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import json
from copy import deepcopy
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
