"""Runnable frozen D5 qualification. Provider mode never records approval.

``offline`` is confined to a disposable, fixture-marked database and invokes the
same admission/adapter as ``run``. No fallback switches a refused live run into
simulation. A request identity is never replaced after failure/uncertainty.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from psycopg_pool import ConnectionPool

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import D5Adapter, D5MeasurementAdapter, D5ProbeAdapter
from src.workspace.d5_freeze import RUN_OWNER, compile_inputs, freeze, restore_input, verify
from src.workspace.d5_scoring import markdown, score_case
from src.workspace.executor import FakeExecutor
from src.workspace.qualification_budget import census
from src.workspace.store import WorkspaceStore


def read(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)
    if not isinstance(value, dict):
        raise AdmissionError("d5_artifact_object_required")
    return value


def write(path: Path, value: Any) -> None:
    if path.exists():
        raise AdmissionError("d5_frozen_artifact_exists_choose_new_revision")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)


def database(url: str) -> ConnectionPool:
    parsed = urlsplit(url)
    if (
        parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.port != 15488
        or not parsed.path.startswith("/workspace_d5_")
    ):
        raise AdmissionError("d5_isolated_loopback_database_required")
    return ConnectionPool(url, min_size=1, max_size=3)


def check_storage(store: WorkspaceStore, packet: dict[str, Any]) -> None:
    control = FakeExecutor(store)
    with store.pool.connection() as conn:
        for frozen in packet["materials"]:
            material = control._sources(conn, RUN_OWNER, [frozen["material_id"]])[0]
            from dataclasses import asdict

            if _digest(asdict(material)) != _digest(frozen):
                raise AdmissionError("d5_frozen_material_changed")
        # Immutable source metadata is checked separately from material offsets.
        for item in packet["corpus"]:
            row = conn.execute(
                "SELECT data FROM workspace_versions WHERE version_id=%s", (item["version_id"],)
            ).fetchone()
            if not row or row[0].get("content_hash") != item.get("content_hash"):
                raise AdmissionError("d5_frozen_source_changed")


def results(store: WorkspaceStore, packet: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_results import QualificationResults

    service = QualificationResults(store)
    compiled = compile_inputs(packet)
    snapshots = {}
    with store.pool.connection() as conn:
        for case_id, entry in compiled.items():
            jid = (
                "gen-" + _digest([entry["owner"], entry["input"]["settings"]["d5_request_id"]])[:40]
            )
            row = conn.execute(
                "SELECT id FROM workspace_generation_jobs WHERE owner=%s AND id=%s",
                (entry["owner"], jid),
            ).fetchone()
            if row:
                snapshots[case_id] = service.snapshot(entry["owner"], row[0])
        members = [
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
                (packet["program_id"],),
            )
        ]
        accounting = census(conn, members[0], members=members)
        new = census(conn, RUN_OWNER, members=sorted({v["owner"] for v in compiled.values()}))
        materials = tuple(
            FakeExecutor(store)._sources(conn, RUN_OWNER, [m["material_id"]])[0]
            for m in packet["materials"]
        )
    scores = [score_case(case, snapshots.get(case["id"]), materials) for case in packet["cases"]]
    probes = []
    for probe in packet["probes"]:
        observed = snapshots.get(probe["id"], {})
        steps = observed.get("steps", [])
        probes.append(
            {
                "id": probe["id"],
                "raw_machine_checks": steps[-1]["output"].get("checks", []) if steps else [],
                "mechanical_grounding": (observed.get("result") or {}).get("grounding"),
                "proposed_negative_items": 5,
                "independent_human_labels": probe["human_labels"],
                "human_false_pass_rate": None,
                "human_false_fail_rate": None,
                "basis": "Proposed negative labels are not independent gold; raw machine opinions and scope overrides are distinct",
            }
        )
    return {
        "packet_digest": packet["packet_digest"],
        "basis": "Quarantined retained-data replay; synthetic transport/counts/usage in offline mode. Mechanical evidence is not semantic qualification or fresh intake.",
        "cases": scores,
        "probe_diagnostics": probes,
        "denominators": {
            "fresh_system_cases": 8,
            "fresh_completed": sum(
                c["completion"] for c in scores if c["cohort"] == "fresh_system"
            ),
            "human_supported_generated_claims": 0,
            "human_judged_adversarial_items": 0,
            "known_reference_judgments": 0,
            "accepted_results": 0,
            "cost_per_accepted_result": None,
        },
        "raw_results": snapshots,
        "accounting": {
            "cumulative": accounting,
            "new_scope": new,
            "historical": packet["history"],
            "actual_new_provider_contacts": 0
            if all(v.get("simulated") for v in snapshots.values())
            else None,
            "invoice_confirmed": False,
        },
        "acceptance": "HOLD: independent human quality and usefulness judgments absent; inspect transport and usage receipts separately",
        "checker_qualified": False,
        "everyday_generation": False,
        "human_labels": None,
    }


async def run(
    store: WorkspaceStore, packet: dict[str, Any], stage: str, *, offline: bool
) -> dict[str, Any]:
    verify(packet)
    check_storage(store, packet)
    compiled = compile_inputs(packet)
    with store.pool.connection() as conn:
        fixture = conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone()
    if bool(fixture) != offline:
        raise AdmissionError("d5_run_transport_database_mismatch")
    if offline and os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled":
        raise AdmissionError("d5_offline_disabled_key_required")
    stages = ["A", "B", "C", "D"] if stage == "all" and offline else [stage]
    if any(s not in {"A", "B", "C", "D"} for s in stages):
        raise AdmissionError("d5_named_stage_required")
    for current in stages:
        # Later stages cannot bypass the declared progression.
        previous = {"B": "A", "C": "B", "D": "C"}.get(current)
        if previous:
            with store.pool.connection() as conn:
                for _key, entry in compiled.items():
                    if entry["stage"] == previous:
                        jid = (
                            "gen-"
                            + _digest(
                                [entry["owner"], entry["input"]["settings"]["d5_request_id"]]
                            )[:40]
                        )
                        row = conn.execute(
                            "SELECT state,data->'result' FROM workspace_generation_jobs WHERE owner=%s AND id=%s",
                            (entry["owner"], jid),
                        ).fetchone()
                        if not row or row[0] != "ready":
                            raise AdmissionError("d5_previous_stage_not_complete")
                        if previous == "A" and (
                            not isinstance(row[1].get("input_tokens"), int)
                            or row[1]["input_tokens"] > 16000
                        ):
                            raise AdmissionError("d5_initial_measurements_do_not_fit")
        for key, entry in compiled.items():
            if entry["stage"] != current:
                continue
            inputs = restore_input(entry["input"])
            operation = inputs.settings["d5_operation"]
            kind = (
                D5MeasurementAdapter
                if operation == "measurement"
                else D5ProbeAdapter
                if operation == "probe"
                else D5Adapter
            )
            kwargs: dict[str, Any] = {}
            if offline:
                from src.workspace.d5_fixture import ReplayTransport

                kwargs["transport"] = httpx.MockTransport(ReplayTransport(key))
            else:
                # Only this explicit CLI branch reads the configured key. It is
                # never emitted, persisted or used for an unrelated smoke call.
                kwargs.update(
                    api_key=os.environ.get("ANTHROPIC_API_KEY", "local-preview-disabled"),
                    enabled=True,
                )
            adapter = kind(store, entry["owner"], inputs, **kwargs)
            started = time.monotonic()
            job = adapter.start(inputs.settings["d5_request_id"])
            # A completed identity may be inspected; failed/uncertain identities
            # cannot be silently replaced, repaired or dispatched again.
            if job["state"] not in {"running", "ready"}:
                raise AdmissionError("d5_stopped_case_no_replay")
            for _ in range(4):
                if job["state"] == "ready":
                    break
                job = await adapter.advance(job["id"])
            if job["state"] != "ready":
                raise AdmissionError("d5_incomplete_case_stop")
            with store.pool.connection() as conn:
                from psycopg.types.json import Jsonb

                conn.execute(
                    "UPDATE workspace_generation_jobs SET data=jsonb_set(data,'{d5_elapsed_seconds}',%s) WHERE id=%s AND NOT(data ? 'd5_elapsed_seconds')",
                    (Jsonb(time.monotonic() - started), job["id"]),
                )
    return results(store, packet)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["init", "freeze", "verify", "offline", "run", "report"])
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--offline-fixture", action="store_true")
    parser.add_argument("--stage", choices=["A", "B", "C", "D", "all"], default="all")
    args = parser.parse_args()
    if args.verb == "verify":
        packet = read(args.packet)
        verify(packet)
        print(json.dumps({"verified": packet["packet_digest"], "provider_contacts": 0}))
        return
    with database(os.environ["D5_POSTGRES_URL"]) as pool:
        store = WorkspaceStore(pool)
        if args.verb == "init":
            if args.snapshot is None:
                parser.error("init requires --snapshot")
            from src.workspace.d5_fixture import install, prepare_projects

            packet = read(args.packet)
            verify(packet)
            captured = read(args.snapshot)
            if packet.get("snapshot_digest") != _digest(captured):
                raise AdmissionError("d5_replay_snapshot_binding_changed")
            install(store, captured, fixture=args.offline_fixture)
            prepare_projects(store, packet)
            print(
                json.dumps(
                    {
                        "initialized": True,
                        "fixture": args.offline_fixture,
                        "approval_created": False,
                        "provider_contacts": 0,
                    }
                )
            )
            return
        if args.verb == "freeze":
            if args.snapshot is None:
                parser.error("freeze requires --snapshot")
            captured = read(args.snapshot)
            packet = freeze(store, captured["profile"], captured["history"])
            packet["program_id"] = captured["program_id"]
            packet["profile_authority"] = captured.get("profile_authority", {})
            packet["snapshot_digest"] = _digest(captured)
            packet["packet_digest"] = _digest(
                {k: v for k, v in packet.items() if k != "packet_digest"}
            )
            write(args.packet, packet)
            print(json.dumps({"packet_digest": packet["packet_digest"], "provider_contacts": 0}))
            return
        packet = read(args.packet)
        if args.verb == "offline":
            from src.workspace.d5_fixture import authorize_fixture

            authorize_fixture(store, packet)
        report = (
            asyncio.run(run(store, packet, args.stage, offline=args.verb == "offline"))
            if args.verb in {"offline", "run"}
            else results(store, packet)
        )
        if args.out is None:
            parser.error("reporting requires --out (new directory)")
        write(args.out / "results.json", report)
        (args.out / "REPORT.md").write_text(markdown(report))
        from html import escape

        (args.out / "index.html").write_text(
            "<!doctype html><meta charset=utf-8><title>D5 quarantined benchmark</title><pre>"
            + escape(markdown(report))
            + "</pre>"
        )
        print(
            json.dumps(
                {
                    "packet_digest": packet["packet_digest"],
                    "cases": len(report["cases"]),
                    "completed": sum(c["completion"] for c in report["cases"]),
                    "report": str(args.out),
                    "acceptance": report["acceptance"],
                }
            )
        )


if __name__ == "__main__":
    main()
