"""Offline-only v6 packet and full replay. Never loads a key or contacts a provider.

Run with python - < this file from the worktree root and a new empty D5 database.
Historical recorded amendments are mirrored, not reapproved. Synthetic successor
and scope approvals are confined to permanently provider-disabled fixture data.
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

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_benchmark import database, read, run, write
from src.workspace.d5_fixture import authorize_fixture, install, prepare_projects
from src.workspace.d5_freeze import compile_inputs, freeze, verify
from src.workspace.d5_measurements import assess_reuse
from src.workspace.d5_operations import OPUS_LIMITS, ROUTES, wire
from src.workspace.d5_scoring import markdown
from src.workspace.programme_successors import record_external
from src.workspace.store import WorkspaceStore

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("verb", choices=["seal", "replay"])
parser.add_argument("--packet", type=Path, required=True)
parser.add_argument("--snapshot", type=Path, required=True)
parser.add_argument("--successor", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--development", choices=["both", "learn-only"], default="both")
a = parser.parse_args()
if (
    os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
    or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
):
    raise AdmissionError("offline_sentinel_environment_required")
if a.out.exists():
    raise AdmissionError("new_report_directory_required")
a.out.mkdir(parents=True)
captured = read(a.snapshot)
successor = read(a.successor)
assert successor["approved"] is False
with database(os.environ["D5_POSTGRES_URL"]) as pool:
    store = WorkspaceStore(pool)
    install(store, captured, fixture=True)
    if a.verb == "seal":
        p = freeze(store, captured["profile"], captured["history"])
        p.update(
            program_id=captured["program_id"],
            snapshot_digest=_digest(captured),
            profile_authority=captured["profile_authority"],
            operation_routes=deepcopy(ROUTES),
            limits=deepcopy(OPUS_LIMITS),
            predecessor_packet_digest="85afa214bd4634ca27e668470257b9ecb53b2dfe87fa018ec17856e46729b35b",
            continuation=captured["continuation"],
            programme_amendment=successor
            if a.development == "both"
            else captured["original_amendment_proposal"],
            proposed_successor_amendment=successor,
            planned_development_cases=["dev-learn", "dev-compare"]
            if a.development == "both"
            else ["dev-learn"],
            historical_paid_baseline={
                "programme_jobs": 8,
                "Messages": 12,
                "counts": 26,
                "estimated_usd": "0.196359",
                "pending_usd": "0",
                "unknown_usd": "0",
            },
            development_scope="Both distinct repairs"
            if a.development == "both"
            else "Only observed Learn prose repair; cross-source provider path untested",
        )
        p["execution"].update(
            operation_routes=deepcopy(ROUTES),
            checker_model="claude-opus-5-5",
            checker_output_tokens=3200,
            checker_effort="high",
            checker_thinking={"type": "adaptive"},
        )
        for probe in p["probes"]:
            ctx = json.loads(probe["wire"]["messages"][0]["content"])
            probe["wire"] = wire({**ctx, "output_schema": p["checker_schema"]["wire"]}, ROUTES)
        p["packet_digest"] = _digest({k: v for k, v in p.items() if k != "packet_digest"})
        compiled = compile_inputs(p)
        assessed = assess_reuse(store, captured["measurement_receipts"], compiled, offline=True)
        p.update(assessed)
        p["packet_digest"] = _digest({k: v for k, v in p.items() if k != "packet_digest"})
        verify(p)
        write(a.packet, p)
    else:
        p = read(a.packet)
        verify(p)
        prepare_projects(store, p)
    if a.verb == "replay":
        if len(p["planned_development_cases"]) == 2:
            fixture = deepcopy(successor)
            now = datetime.now(UTC)
            fixture.update(
                approved=True,
                approved_by="Synthetic offline successor only; no owner approval",
                approved_at=now.isoformat(),
                expires_at=min(
                    now + timedelta(days=1),
                    datetime.fromisoformat(successor["amendment"]["predecessor_expiry"]),
                ).isoformat(),
                authorization_kind="offline_fixture",
                transport_mode="mock",
                authorization_reference="Disposable v6 complete schedule replay only",
            )
            write(a.out / "SYNTHETIC-successor-receipt.json", record_external(store, fixture))
        authorize_fixture(store, p)
        r = asyncio.run(run(store, p, "all", offline=True))
        write(a.out / "results.json", r)
        (a.out / "REPORT.md").write_text(markdown(r))
        (a.out / "index.html").write_text(
            '<meta charset="utf-8"><title>Synthetic v6 replay</title><pre>'
            + escape(markdown(r))
            + "</pre>"
        )
    write(
        a.out / "identity.json",
        {
            "packet_digest": p["packet_digest"],
            "application_commit": p["application_commit"],
            "planned_development_cases": p["planned_development_cases"],
            "programme_amendment_digest": p["programme_amendment"]["proposal_digest"],
            "measurement_reuse": list(p["measurement_reuse"]),
            "fresh_measurement_cases": p["fresh_measurement_cases"],
            "actual_provider_contacts": 0,
            "new_spend_usd": "0",
        },
    )
    print(json.dumps(read(a.out / "identity.json")))
