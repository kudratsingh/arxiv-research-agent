"""Bounded complete 14-job offline gate outside the 60-second unit-test tier.

Runs the production campaign, adapter, journal and admission. Only transport and
external authorization are synthetic, in an owned disposable Postgres schema.
No owner DB, provider credential or contact is permitted.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool


@contextmanager
def storage():
    from src.workspace.admission import AdmissionError
    from src.workspace.store import WorkspaceStore

    url = os.environ.get("WORKSPACE_TEST_POSTGRES_URL")
    with tempfile.TemporaryDirectory(prefix="d5-campaign-gate-") as temporary:
        root = Path(temporary)
        started = False
        try:
            if url:
                if (
                    urlsplit(url).hostname not in {"localhost", "127.0.0.1"}
                    or urlsplit(url).path != "/workspace_d5_tests"
                ):
                    raise AdmissionError("campaign_gate_disposable_test_database_required")
            else:
                if not shutil.which("initdb") or not shutil.which("pg_ctl"):
                    raise AdmissionError("campaign_gate_postgres_required")
                data = root / "pg"
                with socket.socket() as listener:
                    listener.bind(("127.0.0.1", 0))
                    port = listener.getsockname()[1]
                with (root / "postgres.log").open("ab") as log:
                    subprocess.run(
                        [
                            "initdb",
                            "-D",
                            str(data),
                            "-A",
                            "trust",
                            "-U",
                            "postgres",
                            "--no-locale",
                            "-E",
                            "UTF8",
                        ],
                        stdout=log,
                        stderr=log,
                        check=True,
                        timeout=30,
                    )
                    subprocess.run(
                        [
                            "pg_ctl",
                            "-D",
                            str(data),
                            "-l",
                            str(root / "server.log"),
                            "-o",
                            f"-F -h 127.0.0.1 -p {port} -k {root}",
                            "-w",
                            "start",
                        ],
                        stdout=log,
                        stderr=log,
                        check=True,
                        timeout=30,
                    )
                started = True
                with psycopg.connect(
                    f"postgresql://postgres@127.0.0.1:{port}/postgres", autocommit=True
                ) as c:
                    c.execute("CREATE DATABASE workspace_d5_tests")
                url = f"postgresql://postgres@127.0.0.1:{port}/workspace_d5_tests"
            schema = "ws_test_campaign_" + uuid.uuid4().hex
            with psycopg.connect(url, autocommit=True) as c:
                c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            try:
                with ConnectionPool(
                    url,
                    min_size=1,
                    max_size=4,
                    kwargs={"options": f"-c search_path={schema},public"},
                ) as pool:
                    store = WorkspaceStore(pool)
                    store.migrate()
                    yield store
            finally:
                with psycopg.connect(url, autocommit=True) as c:
                    c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        finally:
            if started:
                subprocess.run(
                    ["pg_ctl", "-D", str(root / "pg"), "-m", "fast", "-w", "stop"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    timeout=30,
                )


def main() -> None:
    from src.workspace.admission import AdmissionError
    from src.workspace.d5_benchmark import write
    from src.workspace.d5_campaign import CampaignTransport, run
    from src.workspace.d5_campaign_packet import compile_campaign
    from src.workspace.d5_campaign_report import markdown
    from src.workspace.qualification_budget import census
    from tests.test_workspace_d5_campaign import setup

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (
        os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
        or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
    ):
        raise AdmissionError("campaign_gate_offline_only")
    started = time.monotonic()
    with storage() as store:
        packet = setup(store)

        def factory(key):
            return CampaignTransport(key, repair_all=True)

        def progress(record):
            print(
                record["case_id"], record["state"], f"{time.monotonic() - started:.1f}s", flush=True
            )

        report = asyncio.run(
            run(store, packet, offline=True, transport_factory=factory, progress=progress)
        )
        write(args.out / "packet.json.gz", packet)
        write(args.out / "results.json", report)
        (args.out / "REPORT.md").write_text(markdown(report))
        assert report["stop"] is None, report["stop"]
        assert len(report["outcomes"]) == 14
        assert report["denominators"]["completed_evaluation"] == 8
        assert report["accounting"]["new_scope"]["messages"] == 44
        assert report["accounting"]["new_scope"]["counts"] == 44
        assert report["accounting"]["cumulative"]["messages"] == 109
        assert report["accounting"]["cumulative"]["counts"] == 134
        assert report["accounting"]["cumulative"]["funded_programme_jobs"] == 47
        assert (
            report["accounting"]["cumulative"]["pending_usd"]
            == report["accounting"]["cumulative"]["unknown_usd"]
            == "0.425066"
        )
        assert (
            report["probe_scores"]["false_pass"]["planned"]
            == report["probe_scores"]["false_reject"]["planned"]
            == 10
        )
        assert (
            report["probe_scores"]["false_pass"]["errors"]
            == report["probe_scores"]["false_reject"]["errors"]
            == 0
        )
        assert report["machine_quality"] == "HOLD" and report["human_labels"] is None
        actor = next(iter(compile_campaign(packet).values()))["owner"]
        with store.pool.connection() as c:
            before = census(c, actor)
        again = asyncio.run(run(store, packet, offline=True, transport_factory=factory))
        with store.pool.connection() as c:
            assert census(c, actor) == before
        assert len(again["outcomes"]) == 14
        write(
            args.out / "GATE.json",
            {
                "passed": True,
                "maximal_repair_envelope": True,
                "jobs": 14,
                "messages": 44,
                "paired_counts": 44,
                "cumulative_jobs": 47,
                "cumulative_messages": 109,
                "cumulative_counts": 134,
                "historical_hold_retained": "0.425066",
                "repeat_dispatches": 0,
                "real_provider_contacts": 0,
                "human_qualification": False,
                "elapsed_seconds": time.monotonic() - started,
            },
        )
    print(
        "PASS: 14 jobs,44 Messages,44 paired counts; cumulative47/109/134; original hold retained; duplicate run dispatched0; synthetic evidence only"
    )


if __name__ == "__main__":
    main()
