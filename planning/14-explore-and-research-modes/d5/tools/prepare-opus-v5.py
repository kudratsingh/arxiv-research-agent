"""Offline successor sealing/replay tool. Invoke with python - < this file.

An empty disposable database is mandatory. This tool never reads a key, creates
an HTTP client or accepts provider mode. Synthetic permission stays fixture-only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

import httpx

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import D5MeasurementAdapter
from src.workspace.d5_benchmark import database, read, run, write
from src.workspace.d5_fixture import authorize_fixture, install, prepare_projects
from src.workspace.d5_freeze import compile_inputs, freeze, restore_input, verify
from src.workspace.d5_measurements import assess_reuse, verify_reuse
from src.workspace.d5_operations import OPUS_LIMITS, ROUTES, wire
from src.workspace.d5_scoring import markdown
from src.workspace.programme_amendments import record_external
from src.workspace.store import WorkspaceStore

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("verb", choices=["seal", "replay"])
parser.add_argument("--packet", type=Path, required=True)
parser.add_argument("--snapshot", type=Path, required=True)
parser.add_argument("--amendment", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
a = parser.parse_args()
if (
    os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
    or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
):
    raise AdmissionError("offline_sentinel_environment_required")
if a.out.exists():
    raise AdmissionError("new_report_directory_required")
captured = read(a.snapshot)
amendment = read(a.amendment)
assert amendment["approved"] is False
assert amendment["amendment"]["basis"] == captured["history"]
a.out.mkdir(parents=True)
with database(os.environ["D5_POSTGRES_URL"]) as pool:
    store = WorkspaceStore(pool)
    install(store, captured, fixture=True)
    if a.verb == "seal":
        packet = freeze(store, captured["profile"], captured["history"])
        packet.update(
            program_id=captured["program_id"],
            snapshot_digest=_digest(captured),
            profile_authority=captured["profile_authority"],
            programme_amendment=amendment,
            operation_routes=deepcopy(ROUTES),
            limits=deepcopy(OPUS_LIMITS),
            predecessor_packet_digest="f21f4b66e1eb99ab75c7c242a9bfa46acb78ccabc13fb885477e8160425fd95a",
            continuation=captured["continuation"],
        )
        packet["execution"].update(
            operation_routes=deepcopy(ROUTES),
            checker_output_tokens=3200,
            checker_model="claude-opus-5-5",
            checker_thinking={"type": "adaptive"},
            checker_effort="high",
        )
        for probe in packet["probes"]:
            context = json.loads(probe["wire"]["messages"][0]["content"])
            probe["wire"] = wire(
                {**context, "output_schema": packet["checker_schema"]["wire"]}, ROUTES
            )
        packet["packet_digest"] = _digest({k: v for k, v in packet.items() if k != "packet_digest"})
        compiled = compile_inputs(packet)
        assessed = assess_reuse(store, captured["measurement_receipts"], compiled, offline=True)
        packet["measurement_reuse"] = assessed["measurement_reuse"]
        packet["fresh_measurement_cases"] = assessed["fresh_measurement_cases"]
        packet["packet_digest"] = _digest({k: v for k, v in packet.items() if k != "packet_digest"})
        verify(packet)
        write(a.packet, packet)
    else:
        packet = read(a.packet)
        verify(packet)
        prepare_projects(store, packet)
    compiled = compile_inputs(packet)
    proofs = {
        key: verify_reuse(
            store, link, compiled[key]["owner"], restore_input(compiled[key]["input"]), offline=True
        )
        for key, link in packet["measurement_reuse"].items()
    }
    write(a.out / "measurement-reuse.json", proofs)
    requests = {}

    def forbidden(_):
        raise AssertionError("Sealing must never dispatch")

    for key, entry in compiled.items():
        if entry["stage"] == "A":
            adapter = D5MeasurementAdapter(
                store,
                entry["owner"],
                restore_input(entry["input"]),
                transport=httpx.MockTransport(forbidden),
            )
            requests[key] = adapter.request()
    write(a.out / "initial-sonnet-requests.json", requests)
    write(a.out / "compiled-inputs.json", compiled)
    if a.verb == "replay":
        synthetic = deepcopy(amendment)
        now = datetime.now(UTC)
        synthetic.update(
            approved=True,
            approved_by="Synthetic disposable fixture, never owner approval",
            approved_at=now.isoformat(),
            expires_at=(now + timedelta(days=1)).isoformat(),
            authorization_kind="offline_fixture",
            transport_mode="mock",
            authorization_reference="synthetic-offline-boundary-proof",
        )
        receipt = record_external(store, synthetic)
        write(a.out / "SYNTHETIC-amendment-receipt.json", receipt)
        authorize_fixture(store, packet, stages=("B", "C", "D"))
        report = asyncio.run(run(store, packet, "all", offline=True))
        write(a.out / "results.json", report)
        (a.out / "REPORT.md").write_text(markdown(report))
        (a.out / "index.html").write_text(
            '<meta charset="utf-8"><title>Offline simulation only</title><pre>'
            + escape(markdown(report))
            + "</pre>"
        )
    write(
        a.out / "identity.json",
        {
            "packet_digest": packet["packet_digest"],
            "application_commit": packet["application_commit"],
            "amendment_proposal_digest": amendment["proposal_digest"],
            "amendment_active_in_real_ledger": False,
            "reused": list(proofs),
            "fresh_counts_required": packet["fresh_measurement_cases"],
            "actual_new_Messages": 0,
            "actual_new_counts": 0,
            "actual_new_spend_usd": "0",
        },
    )
    print(json.dumps(read(a.out / "identity.json")))
