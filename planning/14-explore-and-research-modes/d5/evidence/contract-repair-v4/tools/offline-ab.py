"""Fresh disposable A/B replay; synthetic permission is confined to fixture DBs.

Run from worktree root using Python stdin, never this external path as sys.path[0].
This tool has no provider transport, credential reader or live approval path.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
from html import escape
from pathlib import Path

from src.workspace.d5_benchmark import database, read, run, write
from src.workspace.d5_fixture import authorize_fixture, install, prepare_projects
from src.workspace.d5_freeze import verify
from src.workspace.d5_scoring import markdown
from src.workspace.store import WorkspaceStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (
        os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
        or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
    ):
        raise RuntimeError("Offline fixture and disabled-key guards required")
    if (
        not args.database.startswith("workspace_d5_contract_v4_")
        or not args.database.replace("_", "").isalnum()
    ):
        raise RuntimeError("Fresh isolated v4 database required")
    if args.out.exists():
        raise RuntimeError("Choose a new output directory; never overwrite results")
    base = Path("planning/14-explore-and-research-modes/d5")
    packet = read(base / "d5-system-validation-v4.json.gz")
    captured = read(base / "d5-replay-inputs-v2.json.gz")
    verify(packet)
    with database(
        "postgresql://workspace:workspace-local-only@127.0.0.1:15488/" + args.database
    ) as pool:
        store = WorkspaceStore(pool)
        install(store, captured, fixture=True)  # Refuses nonempty DB, no live permission.
        prepare_projects(store, packet)
        authorize_fixture(store, packet, stages=("A", "B"))
        measurement = asyncio.run(run(store, packet, "A", offline=True))
        write(args.out / "measurement.json.gz", measurement)
        result = asyncio.run(run(store, packet, "B", offline=True))
        assert result["accounting"]["actual_new_provider_contacts"] == 0
        write(args.out / "results.json.gz", result)
        (args.out / "REPORT.md").write_text(markdown(result))
        (args.out / "index.html").write_text(
            '<!doctype html><meta charset="utf-8"><title>Offline D5 A/B simulation</title><pre>'
            + escape(markdown(result))
            + "</pre>"
        )
        write(
            args.out / "receipt.json",
            {
                "packet_digest": packet["packet_digest"],
                "application": packet["application_commit"],
                "tool_sha256": hashlib.sha256(
                    (base / "evidence/contract-repair-v4/tools/offline-ab.py").read_bytes()
                ).hexdigest(),
                "stages": ["A", "B"],
                "provider_contacts": 0,
                "measured_tokens": None,
                "human_labels": None,
                "paid_authorization": False,
            },
        )


if __name__ == "__main__":
    main()
