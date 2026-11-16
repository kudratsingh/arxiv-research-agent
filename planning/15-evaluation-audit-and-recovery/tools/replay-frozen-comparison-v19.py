"""Replay exactly one frozen v19 packet in disposable Postgres, with mock HTTP only.

Run from the checkout root using python - < this-file --packet ... --snapshot ...
--out NEW_PERMANENT_DIRECTORY. This command cannot create provider authority.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import os
import subprocess
import traceback
from pathlib import Path

import src
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_benchmark import read, write
from src.workspace.d5_campaign_operator import authorize_fixture
from src.workspace.d5_campaign_report import markdown
from src.workspace.d5_fixture import install
from src.workspace.d5_freeze import verify
from tests.d5_campaign_gate import storage
from tests.d5_capacity_gate import export_rows
from tests.d5_comparison_gate import exercise, fixture_authority

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--packet", type=Path, required=True)
parser.add_argument("--snapshot", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
if (
    Path(src.__file__).resolve() != Path.cwd() / "src/__init__.py"
    or os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
    or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
    or not os.environ.get("WORKSPACE_TEST_POSTGRES_URL")
):
    raise AdmissionError("frozen_replay_worktree_disabled_key_disposable_storage_required")
if args.out.exists():
    raise AdmissionError("frozen_replay_output_exists_preserve_it_choose_new_path")
if any(
    str(args.out.resolve()).startswith(prefix)
    for prefix in ("/tmp/", "/private/tmp/", "/private/var/folders/")
):
    raise AdmissionError("frozen_replay_permanent_evidence_directory_required")
packet = read(args.packet)
verify(packet)
if packet["revision"] != "d5-comparison-machine-campaign-v19":
    raise AdmissionError("frozen_replay_v19_packet_required")
snapshot = read(args.snapshot)
if _digest(snapshot) != packet["snapshot_digest"]:
    raise AdmissionError("frozen_replay_snapshot_digest_mismatch")
subprocess.run(
    ["git", "merge-base", "--is-ancestor", packet["application_commit"], "HEAD"], check=True
)
args.out.mkdir(parents=True)
os.environ["D5_TEST_EVIDENCE_DIR"] = str(args.out / "fixture-journals")
write(args.out / "FROZEN-PACKET.json.gz", packet)
write(
    args.out / "REPLAY-INPUT-BINDINGS.json",
    {
        "packet_digest": packet["packet_digest"],
        "application_commit": packet["application_commit"],
        "observed_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "packet_file_sha256": hashlib.sha256(args.packet.read_bytes()).hexdigest(),
        "snapshot_digest": _digest(snapshot),
        "provider_contacts": 0,
        "provider_authorization": False,
        "transport": "MockTransport; counts, usage and judgments are synthetic, not measured provider evidence",
    },
)
with storage() as store:
    try:
        install(store, snapshot, fixture=True)
        authorize_fixture(store, packet)
        write(args.out / "SYNTHETIC-AUTHORIZATION.json.gz", fixture_authority(store, packet))
        report, gate = asyncio.run(exercise(store, packet, out=args.out))
        write(args.out / "GATE.json", gate)
        text = markdown(report)
        (args.out / "REPORT.md").write_text(text)
        (args.out / "REPORT.html").write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Synthetic frozen v19 replay</title><body><h1>Offline synthetic replay</h1>"
            "<p>No provider contacts, actual token measurements, new spend or human qualification.</p><pre>"
            + html.escape(text)
            + "</pre></body></html>"
        )
    except BaseException:
        (args.out / "FAILED.txt").write_text(traceback.format_exc())
        raise
    finally:
        export_rows(store, "frozen-v19-replay")
print(
    f"PASS frozen {packet['packet_digest']}: 14 synthetic jobs /44 Messages /44 exact counts; real contacts0; actual spendUSD0"
)
