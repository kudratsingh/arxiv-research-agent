"""Replay one existing v20 packet using production guards and mock HTTP only.

Run from its checkout root: python - < this-file --packet ... --snapshot ...
--out NEW_PERMANENT_DIRECTORY. No freezer or provider authorization is used.
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
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg_pool import ConnectionPool

import src
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_benchmark import read, write
from src.workspace.d5_campaign import run
from src.workspace.d5_comparison_transport import (
    ComparisonCampaignTransport,
    assert_paired_contacts,
)
from src.workspace.d5_continuation_packet import authorize_fixture, compile_packet, verify_packet
from src.workspace.d5_continuation_policy import CASE_MAP
from src.workspace.d5_continuation_report import markdown
from src.workspace.d5_fixture import install
from src.workspace.store import WorkspaceStore

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--packet", type=Path, required=True)
parser.add_argument("--snapshot", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
url = os.environ.get("WORKSPACE_TEST_POSTGRES_URL", "")
parsed = urlsplit(url)
if (
    Path(src.__file__).resolve() != Path.cwd() / "src/__init__.py"
    or os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
    or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
    or parsed.hostname not in {"localhost", "127.0.0.1"}
    or parsed.port != 15488
    or parsed.path != "/workspace_d5_tests"
):
    raise AdmissionError("v20_replay_worktree_disabled_key_isolated_test_database_required")
if args.out.exists() or any(
    args.out.resolve().is_relative_to(Path(prefix))
    for prefix in ("/tmp", "/private/tmp", "/private/var/folders")
):
    raise AdmissionError("v20_replay_requires_new_permanent_evidence_directory")
packet, snapshot = read(args.packet), read(args.snapshot)
verify_packet(packet)
if _digest(snapshot) != packet["snapshot_digest"]:
    raise AdmissionError("v20_replay_snapshot_binding_drift")
subprocess.run(
    ["git", "merge-base", "--is-ancestor", packet["application_commit"], "HEAD"], check=True
)
args.out.mkdir(parents=True)
write(args.out / "FROZEN-PACKET.json.gz", packet)
write(
    args.out / "REPLAY-INPUT-BINDINGS.json",
    {
        "packet_digest": packet["packet_digest"],
        "packet_file_sha256": hashlib.sha256(args.packet.read_bytes()).hexdigest(),
        "snapshot_digest": _digest(snapshot),
        "application_commit": packet["application_commit"],
        "observed_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "synthetic_only": True,
        "provider_contacts": 0,
        "human_labels": None,
    },
)
schema = "ws_test_v20_frozen_" + uuid4().hex
with psycopg.connect(url, autocommit=True) as conn:
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
export_verified = False
with ConnectionPool(
    url, min_size=1, max_size=4, kwargs={"options": f"-c search_path={schema},public"}
) as pool:
    store = WorkspaceStore(pool)
    try:
        install(store, snapshot, fixture=True)
        authority = authorize_fixture(store, packet)
        write(args.out / "SYNTHETIC-FIXTURE-AUTHORITY.json.gz", authority)
        compiled = compile_packet(packet)
        calls = {}

        def factory(key):
            if key in calls:
                raise AssertionError("duplicate mock dispatch")
            calls[key] = ComparisonCampaignTransport(CASE_MAP[key], repair_all=True)
            return calls[key]

        report = asyncio.run(
            run(
                store,
                packet,
                offline=True,
                transport_factory=factory,
                progress=lambda item: print(item["case_id"], item["state"], flush=True),
            )
        )
        write(args.out / "RESULTS.json.gz", report)
        assert report["stop"] is None, report["stop"]
        assert len(report["outcomes"]) == 10
        assert (
            report["accounting"]["new_scope"]["counts"]
            == report["accounting"]["new_scope"]["messages"]
            == 28
        )
        with pool.connection() as conn:
            for key, handler in calls.items():
                data = conn.execute(
                    "SELECT data FROM workspace_generation_jobs WHERE id=%s",
                    (report["outcomes"][key]["job_id"],),
                ).fetchone()[0]
                assert_paired_contacts(
                    data["adapter"], handler, 1 if compiled[key]["stage"] == "D" else 4
                )
        before = {key: len(value.contacts) for key, value in calls.items()}
        again = asyncio.run(run(store, packet, offline=True, transport_factory=factory))
        assert again["outcomes"] == report["outcomes"]
        assert before == {key: len(value.contacts) for key, value in calls.items()}
        text = markdown(report)
        (args.out / "REPORT.md").write_text(text)
        (args.out / "REPORT.html").write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>v20 synthetic replay</title>'
            "<h1>Simulated software evidence; zero provider contacts</h1><pre>"
            + html.escape(text)
            + "</pre></html>"
        )
    except BaseException:
        (args.out / "FAILED.txt").write_text(traceback.format_exc())
        raise
    finally:
        try:
            scope = "d5-" + packet["packet_digest"][:24]
            with pool.connection() as conn:
                rows = conn.execute(
                    "SELECT r.case_id,to_jsonb(j),to_jsonb(s) FROM workspace_d5_case_runs r "
                    "JOIN workspace_generation_jobs j ON j.id=r.job_id "
                    "JOIN workspace_spend_reservations s ON s.job_id=r.job_id "
                    "WHERE r.scope_id=%s ORDER BY r.case_id",
                    (scope,),
                ).fetchall()
                scopes = [
                    r[0]
                    for r in conn.execute(
                        "SELECT to_jsonb(s) FROM workspace_d5_scopes s WHERE scope_id=%s", (scope,)
                    )
                ]
            artifact = args.out / "RAW-SYNTHETIC-JOURNALS.json.gz"
            write(
                artifact,
                {
                    "fixture_only": True,
                    "provider_contacts": 0,
                    "schema": schema,
                    "scope": scopes,
                    "new_jobs": rows,
                },
            )
            assert read(artifact)["schema"] == schema
            export_verified = True
        finally:
            write(
                args.out / "STORAGE-RETENTION.json",
                {
                    "schema": schema,
                    "raw_export_verified": export_verified,
                    "cleanup_permitted": export_verified,
                    "provider_contacts": 0,
                },
            )
if export_verified:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
    write(
        args.out / "SCHEMA-CLEANUP.json",
        {"schema": schema, "cleanup_completed": True, "raw_export_verified": True},
    )
print("PASS frozen v20:10 synthetic jobs/28 Messages/28 exact counts; real contacts0; spendUSD0")
