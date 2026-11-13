"""Run from the worktree root via python - < this-file --arguments.

The same production campaign, admission and adapter are used. Only external
transport and authorization are synthetic, confined to disposable test storage.
"""

import argparse
import asyncio
import json
import os
from html import escape
from pathlib import Path

import src
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_benchmark import check_storage, read, write
from src.workspace.d5_campaign import CampaignTransport, run
from src.workspace.d5_campaign_operator import authorize_fixture
from src.workspace.d5_campaign_report import markdown
from src.workspace.d5_fixture import install
from src.workspace.d5_freeze import verify
from tests.d5_campaign_gate import storage

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--packet", type=Path, required=True)
parser.add_argument("--snapshot", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
if (
    Path.cwd() != Path(src.__file__).resolve().parents[1]
    or os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
    or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
    or not os.environ.get("WORKSPACE_TEST_POSTGRES_URL")
):
    raise AdmissionError("sealed_replay_worktree_disabled_key_disposable_database_required")
if args.out.exists():
    raise AdmissionError("sealed_replay_choose_new_evidence_directory")
packet, captured = read(args.packet), read(args.snapshot)
verify(packet)
if _digest(captured) != packet["snapshot_digest"]:
    raise AdmissionError("campaign_snapshot_binding_drift")
with storage() as store:
    install(store, captured, fixture=True)
    check_storage(store, packet)
    authorize_fixture(store, packet)
    def factory(key):
        return CampaignTransport(key, repair_all=True)
    report = asyncio.run(
        run(
            store,
            packet,
            offline=True,
            transport_factory=factory,
            progress=lambda row: print(
                json.dumps({"case": row["case_id"], "state": row["state"]}), flush=True
            ),
        )
    )
    write(args.out / "results.json", report)
    rendered = markdown(report)
    (args.out / "REPORT.md").write_text(rendered)
    (args.out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>D5 synthetic replay</title><pre>"
        + escape(rendered)
        + "</pre>"
    )
    assert report["stop"] is None and len(report["outcomes"]) == 14
    assert (
        report["accounting"]["new_scope"]["messages"]
        == report["accounting"]["new_scope"]["counts"]
        == 44
    )
    assert report["accounting"]["cumulative"]["funded_programme_jobs"] == 47
    assert report["accounting"]["cumulative"]["messages"] == 109
    assert report["accounting"]["cumulative"]["counts"] == 134
    assert (
        report["accounting"]["cumulative"]["unknown_usd"]
        == report["accounting"]["cumulative"]["pending_usd"]
        == "0.425066"
    )
    assert all(c["assessment_binding"]["status"] == "bound" for c in report["cases"])
    assert len(report["answerability"]["parts"]) == 24 and report["human_labels"] is None
    again = asyncio.run(run(store, packet, offline=True, transport_factory=factory))
    assert report["accounting"] == again["accounting"]
    write(
        args.out / "REPLAY-RECEIPT.json",
        {
            "packet_digest": packet["packet_digest"],
            "application": packet["application_commit"],
            "synthetic_jobs": 14,
            "synthetic_messages": 44,
            "synthetic_paired_counts": 44,
            "all_current_workflow_checks_bound": True,
            "answerability_rows": 24,
            "repeat_dispatches": 0,
            "retained_hold_usd": "0.425066",
            "real_provider_contacts": 0,
            "real_count_contacts": 0,
            "real_ledger_mutated": False,
            "report_digest": _digest(report),
            "human_qualification": False,
        },
    )
print(
    "PASS: exact sealed packet,14/44/44,all current checks bound; synthetic software evidence only"
)
