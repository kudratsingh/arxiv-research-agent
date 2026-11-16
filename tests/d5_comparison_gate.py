"""Full 14 identity v19 offline MockTransport replay in unique disposable storage.

All judgments, counts and usage are synthetic. The exact preserved checkpoint
is installed only in marked fixture storage. No key, provider, owner DB write or
external approval is involved. Draft packets are not final campaign authority.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

from src.workspace.admission import AdmissionError

SNAPSHOT = Path(
    "/Users/kudratsingh/Machine-Learning-Projects/arxiv-evidence/provider-compat-live-v18-20261116T072641Z/READONLY-POST-RUN.json.gz"
)


def setup(store, snapshot=None, *, authorize=True):
    from src.workspace.d5_benchmark import read
    from src.workspace.d5_campaign_operator import authorize_fixture
    from src.workspace.d5_campaign_v19_packet import freeze
    from src.workspace.d5_fixture import install

    snapshot = read(SNAPSHOT) if snapshot is None else snapshot
    install(store, snapshot, fixture=True)
    packet = freeze(store, snapshot)
    if authorize:
        authorize_fixture(store, packet)
    return packet


def fixture_authority(store, packet):
    """Export synthetic grants before disposable storage teardown."""
    with store.pool.connection() as conn:
        scope = [
            r[0]
            for r in conn.execute(
                "SELECT to_jsonb(t) FROM workspace_d5_scopes t WHERE scope_id=%s",
                ("d5-" + packet["packet_digest"][:24],),
            )
        ]
        continuation = [
            r[0]
            for r in conn.execute(
                "SELECT to_jsonb(t) FROM workspace_d5_keyed_continuations t WHERE packet_digest=%s",
                (packet["packet_digest"],),
            )
        ]
    return {
        "synthetic_only": True,
        "scope": scope,
        "continuation": continuation,
        "provider_authority": False,
    }


async def exercise(store, packet, *, out=None):
    from src.workspace.d5_campaign import run
    from src.workspace.d5_campaign_packet import compile_campaign
    from src.workspace.d5_comparison_transport import (
        ComparisonCampaignTransport,
        assert_paired_contacts,
    )
    from src.workspace.qualification_budget import census

    transports = {}

    def factory(key):
        transports[key] = ComparisonCampaignTransport(key, repair_all=True)
        return transports[key]

    report = await run(store, packet, offline=True, transport_factory=factory)
    if out is not None:
        from src.workspace.d5_benchmark import write

        write(out / "results.json", report)
        write(
            out / "TRANSPORT-CONTROLS.json.gz",
            {
                key: {
                    "contacts": handler.contacts,
                    "request_bodies": [body.decode("utf-8") for body in handler.request_bodies],
                    "schema_validations": handler.schema_validations,
                    "synthetic_outputs": handler.outputs,
                }
                for key, handler in transports.items()
            },
        )
    assert report["stop"] is None, report["stop"]
    assert len(report["outcomes"]) == len(transports) == 14
    assert report["denominators"]["completed_evaluation"] == 8
    assert (
        report["accounting"]["new_scope"]["messages"]
        == report["accounting"]["new_scope"]["counts"]
        == 44
    )
    cumulative = report["accounting"]["cumulative"]
    assert (cumulative["funded_programme_jobs"], cumulative["messages"], cumulative["counts"]) == (
        60,
        124,
        149,
    )
    assert cumulative["pending_usd"] == cumulative["unknown_usd"] == "2.275066"
    assert report["accounting"]["historical"]["known_usd"] == "2.533843"
    for case in report["cases"]:
        binding = case.get("assessment_binding", {})
        assert binding.get("status") == "bound", (case["id"], binding)
        assert binding["current_response_ordinal"] == 5
        assert binding["checker_ordinal"] == 7
        assert binding["completed_checker_after_current_response"] is True
    identities = {}
    for key, handler in transports.items():
        with store.pool.connection() as conn:
            row = conn.execute(
                "SELECT j.id,j.data FROM workspace_d5_case_runs r JOIN workspace_generation_jobs j ON j.id=r.job_id WHERE r.scope_id=%s AND r.case_id=%s",
                ("d5-" + packet["packet_digest"][:24], key),
            ).fetchone()
        assert row, key
        job_id, data = row
        messages = 1 if key in {p["id"] for p in packet["probes"]} else 4
        assert_paired_contacts(data["adapter"], handler, messages)
        assert len(handler.schema_validations) == messages
        assert all(not r["errors"] for r in handler.schema_validations)
        if messages == 4:
            assert handler.checks == 2
            assert [r["phase"] for r in handler.schema_validations] == [
                "draft",
                "check",
                "repair",
                "check",
            ]
        identities[key] = {
            "job_id": job_id,
            "messages": messages,
            "paired_counts": messages,
            "actual_request_schemas_validated": messages,
            "response_utf8_bytes": [v["response_utf8_bytes"] for v in handler.schema_validations],
        }
    for name in ("false_pass", "false_reject"):
        assert report["probe_scores"][name]["planned"] == 10
        assert report["probe_scores"][name]["errors"] == 0
    assert report["machine_quality"] == "HOLD" and report["human_labels"] is None
    actor = next(iter(compile_campaign(packet).values()))["owner"]
    with store.pool.connection() as conn:
        before = census(conn, actor)
    called = []

    def forbidden_factory(key):
        called.append(key)
        raise AssertionError("repeated_campaign_dispatched")

    repeated = await run(store, packet, offline=True, transport_factory=forbidden_factory)
    with store.pool.connection() as conn:
        assert census(conn, actor) == before
    assert not called and len(repeated["outcomes"]) == 14
    return report, {
        "passed": True,
        "jobs": 14,
        "messages": 44,
        "paired_counts": 44,
        "baseline": {
            "jobs": 46,
            "messages": 80,
            "counts": 105,
            "known_usd": "2.533843",
            "retained_overlapping_pending_unknown_usd": "2.275066",
        },
        "cumulative": {"jobs": 60, "messages": 124, "counts": 149},
        "identities": identities,
        "maximal_repair_envelope": True,
        "repeat_dispatches": 0,
        "real_provider_contacts": 0,
        "human_qualification": False,
        "semantic_quality": "UNMEASURED; synthetic responses and locked machine references",
    }


async def exercise_progress(store, packet, *, out, broken=False):
    """Run a real bounded checkpoint: failed quality advances; broken JSON stops."""
    from src.workspace.d5_benchmark import write
    from src.workspace.d5_campaign import run
    from src.workspace.d5_campaign_v19_policy import development_contract
    from src.workspace.d5_comparison_transport import (
        ComparisonCampaignTransport,
        assert_paired_contacts,
    )

    order = packet["schedule"]
    transports = {}

    def factory(key):
        scenario = (
            ("truncated_checker" if broken else "final_negative") if key == order[0] else "normal"
        )
        handler = ComparisonCampaignTransport(key, repair_all=True, scenario=scenario)
        transports[key] = handler
        return handler

    report = await run(store, packet, offline=True, transport_factory=factory, checkpoint_after=3)
    write(out / "results.json", report)
    write(
        out / "TRANSPORT-CONTROLS.json.gz",
        {
            key: {
                "contacts": h.contacts,
                "request_bodies": [b.decode("utf-8") for b in h.request_bodies],
                "schema_validations": h.schema_validations,
                "synthetic_outputs": h.outputs,
            }
            for key, h in transports.items()
        },
    )
    assert list(transports) == order[: 1 if broken else 3]
    scope = "d5-" + packet["packet_digest"][:24]
    contracts = []
    if broken:
        assert report["stop"] and report["stop"]["case_id"] == order[0]
        assert report["denominators"]["unrun_evaluation"] == 8
        assert len(report["raw_results"]) == 1
        assert (
            report["accounting"]["new_scope"]["messages"]
            == report["accounting"]["new_scope"]["counts"]
            == 2
        )
        assert report["outcome_diagnostics"][order[0]]["classification"] == "contract_failure"
        expected_messages = 2
    else:
        assert report["stop"] is None
        assert set(report["outcomes"]) == set(order[:3])
        assert [report["outcomes"][key]["state"] for key in order[:3]] == [
            "failed",
            "ready",
            "ready",
        ]
        assert report["denominators"]["completed_evaluation"] == 1
        assert report["denominators"]["unrun_evaluation"] == 7
        assert (
            report["accounting"]["new_scope"]["messages"]
            == report["accounting"]["new_scope"]["counts"]
            == 12
        )
        assert report["outcome_diagnostics"][order[0]]["classification"] == "negative_quality"
        with store.pool.connection() as conn:
            contracts = [development_contract(conn, scope, key) for key in order[:2]]
            assert (
                conn.execute(
                    "SELECT state FROM workspace_d5_scopes WHERE scope_id=%s", (scope,)
                ).fetchone()[0]
                == "active"
            )
        assert all(c["contract_complete"] for c in contracts)
        assert (
            contracts[0]["quality_accepted"] is False and contracts[1]["quality_accepted"] is True
        )
        first = next(c for c in report["cases"] if c["id"] == order[0])
        assert first["assessment_binding"]["status"] == "bound"
        assert first["machine_request_outcome"]["quality_gate"] == "FAIL"
        assert report["raw_results"][order[0]]["result"] is None
        expected_messages = 4
    for key, handler in transports.items():
        assert_paired_contacts(report["raw_results"][key], handler, expected_messages)
    return report, {
        "passed": True,
        "control": "broken_development_stops"
        if broken
        else "negative_quality_permits_unrelated_identity",
        "jobs": len(transports),
        "messages": 2 if broken else 12,
        "paired_counts": 2 if broken else 12,
        "development_contracts": contracts,
        "case_order": list(transports),
        "real_provider_contacts": 0,
        "human_qualification": False,
    }


def main():
    from src.workspace.d5_benchmark import read, write
    from src.workspace.d5_campaign_report import markdown
    from tests.d5_campaign_gate import storage

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--checkpoint-control", choices=("negative-progress", "broken-development"))
    args = parser.parse_args()
    if (
        os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
        or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
    ):
        raise AdmissionError("comparison_gate_offline_only")
    if args.out.exists() and any(args.out.iterdir()):
        raise AdmissionError("comparison_gate_new_evidence_directory_required")
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with storage() as store:
        packet = setup(store, read(args.snapshot), authorize=False)
        write(args.out / "DRAFT-MOCK-PACKET.json.gz", packet)
        try:
            from src.workspace.d5_campaign_operator import authorize_fixture

            authorize_fixture(store, packet)
            write(args.out / "SYNTHETIC-AUTHORIZATION.json.gz", fixture_authority(store, packet))
            if args.checkpoint_control:
                report, gate = asyncio.run(
                    exercise_progress(
                        store,
                        packet,
                        out=args.out,
                        broken=args.checkpoint_control == "broken-development",
                    )
                )
            else:
                report, gate = asyncio.run(exercise(store, packet, out=args.out))
        except BaseException as exc:
            import traceback

            from psycopg import sql

            write(
                args.out / "FAILURE.json",
                {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                    "real_provider_contacts": 0,
                },
            )
            with store.pool.connection() as conn:
                rows = [
                    r[0]
                    for r in conn.execute(
                        sql.SQL(
                            "SELECT to_jsonb(t) FROM workspace_generation_jobs t WHERE data->'sealed_input'->'settings'->>'d5_scope_id'=%s"
                        ),
                        ("d5-" + packet["packet_digest"][:24],),
                    )
                ]
            write(args.out / "FAILED-NEW-JOBS.json.gz", rows)
            write(
                args.out / "FAILED-SYNTHETIC-AUTHORIZATION.json.gz",
                fixture_authority(store, packet),
            )
            raise
        (args.out / "REPORT.md").write_text(markdown(report))
        gate["elapsed_seconds"] = time.monotonic() - started
        write(args.out / "GATE.json", gate)
    print(
        "PASS: synthetic "
        + (
            args.checkpoint_control
            or "14 jobs, 44 Messages, 44 exact paired counts; repeated dispatch 0"
        )
        + "; historical holds retained; human quality unmeasured"
    )


if __name__ == "__main__":
    main()
