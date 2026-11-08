"""Freeze a prospective v8 cohort in NEW disposable storage; no authority/contact.

Run from worktree root with `python - --snapshot ... --packet ... --out ... < file`.
Never run this against the active historical ledger or an existing database.
"""

from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import httpx
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import D5MeasurementAdapter
from src.workspace.d5_benchmark import database, read, write
from src.workspace.d5_fixture import install, prepare_projects
from src.workspace.d5_freeze import compile_inputs, freeze, restore_input, verify
from src.workspace.d5_operations import OPUS_LIMITS, ROUTES, reservation, wire
from src.workspace.store import WorkspaceStore

parser = argparse.ArgumentParser(description=__doc__)
for name in ("snapshot", "packet", "out"):
    parser.add_argument("--" + name, type=Path, required=True)
a = parser.parse_args()
if (
    os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
    or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
):
    raise AdmissionError("offline_sentinel_required")
if a.packet.exists() or a.out.exists():
    raise AdmissionError("new_frozen_artifact_required")
snapshot = read(a.snapshot)
previous = read(Path("planning/14-explore-and-research-modes/d5/d5-system-validation-v7r2.json.gz"))
excluded = sorted(
    {
        ref["version_id"]
        for case in previous["cases"]
        for ref in (case.get("sealed") or {}).get("units", {}).values()
    }
)
with database(os.environ["D5_POSTGRES_URL"]) as pool:
    store = WorkspaceStore(pool)
    install(store, snapshot, fixture=True)
    with pool.connection() as conn:
        for receipt in snapshot["recorded_third_amendments"]:
            assert _digest(receipt["record"]) == receipt["authorization_digest"]
            conn.execute(
                "INSERT INTO workspace_programme_third_amendments SELECT * FROM jsonb_populate_record(NULL::workspace_programme_third_amendments,%s)",
                (Jsonb(receipt),),
            )
    p = freeze(
        store,
        snapshot["profile"],
        snapshot["history"],
        cohort_revision="procedural-v8",
        heldout_excluded_versions=excluded,
    )
    assert all(case.get("sealed") for case in p["cases"]), (
        "Upstream missing evidence: preserve, do not substitute"
    )
    assert (
        snapshot["history"]["messages"] == 31
        and snapshot["history"]["counts"] == 50
        and snapshot["history"]["known_usd"] == "0.825065"
    )
    p.update(
        program_id=snapshot["program_id"],
        snapshot_digest=_digest(snapshot),
        profile_authority=snapshot["profile_authority"],
        operation_routes=deepcopy(ROUTES),
        limits=deepcopy(OPUS_LIMITS),
        predecessor_packet_digest=previous["packet_digest"],
        programme_amendment=previous["programme_amendment"],
        planned_development_cases=["dev-learn", "dev-compare"],
        measurement_cases=["dev-compare"],
        measurement_reuse={},
        fresh_measurement_cases=["measure-1"],
        require_supported_development=True,
    )
    p["execution"].update(
        operation_routes=deepcopy(ROUTES),
        checker_model="claude-opus-5-5",
        checker_output_tokens=3200,
        checker_effort="high",
        checker_thinking={"type": "adaptive"},
    )
    p["historical_paid_baseline"] = {
        "programme_jobs": 16,
        "Messages": 31,
        "counts": 50,
        "estimated_usd": "0.825065",
        "pending_usd": "0",
        "unknown_usd": "0",
    }
    p["historical_v7r2"] = {
        "completion": 3,
        "denominator": 8,
        "failed": ["learn-results"],
        "unrun": [
            "research-memory",
            "research-retrieval",
            "research-evaluation",
            "research-insufficient",
        ],
        "classification": "diagnostic; never fresh held-out evidence",
    }
    p["required_separate_decisions"] = {
        "full_schedule_job_cap": 30,
        "full_schedule_count_cap": 95,
        "Messages_cap": 80,
        "usd_cap": "10",
        "active_job_cap": 24,
        "active_count_cap": 80,
        "authorization_recorded": False,
        "amendment_activated": False,
        "latest_expiry": "2026-11-14T07:24:01Z",
        "dispatch": "No scope grant; full schedule also needs separate cap policy implementation/approval. A/B alone fits current caps.",
    }
    for probe in p["probes"]:
        context = json.loads(probe["wire"]["messages"][0]["content"])
        probe["wire"] = wire({**context, "output_schema": p["checker_schema"]["wire"]}, ROUTES)
    p["packet_digest"] = _digest({k: v for k, v in p.items() if k != "packet_digest"})
    verify(p)
    prepare_projects(store, p)
    compiled = compile_inputs(p)

    # No network is possible in request export, even if a regression dispatches.
    def deny(_):
        raise AssertionError("Freeze/export cannot contact HTTP")

    e = compiled["measure-1"]
    adapter = D5MeasurementAdapter(
        store, e["owner"], restore_input(e["input"]), transport=httpx.MockTransport(deny)
    )
    req = adapter.request()["body"]
    count = {k: v for k, v in req.items() if k not in {"max_tokens", "temperature"}}
    old_body = read(
        Path(
            "planning/14-explore-and-research-modes/d5/evidence/gap-repair-v7r2/initial-requests.json.gz"
        )
    )["A"]["measure-1"]
    proof = {
        "measure-1": {
            "old_digest": _digest(old_body),
            "new_digest": _digest(count),
            "exact_match": old_body == count,
            "reusable": False,
        },
        "all_dynamic_counts": "Must measure each actual derived request; old digests cannot prove fit.",
    }
    assert not proof["measure-1"]["exact_match"]
    write(a.packet, p)
    write(a.out / "measure-1-request.json", count)
    write(a.out / "MEASUREMENT-NONREUSE.json", proof)
    budget = {
        "historical_usd": "0.825065",
        "new_jobs": 14,
        "new_Messages_max": 44,
        "new_paired_counts_max": 44,
        "preliminary_counts": 1,
        "cumulative_jobs": 30,
        "cumulative_Messages_max": 75,
        "cumulative_counts_max": 95,
        "active_job_cap": 24,
        "active_Messages_cap": 80,
        "active_count_cap": 80,
        "additional_job_capacity_needed": 6,
        "additional_count_capacity_needed": 15,
        "per_workflow_usage_bound": str(reservation(ROUTES)),
        "new_reservations_usd": "5.10",
        "uncertainty_buffer_usd": "1",
        "total_with_history_reservations_buffer": str(
            Decimal("0.825065") + Decimal("5.10") + Decimal("1")
        ),
        "approved": False,
    }
    write(a.out / "CONTINUATION-BUDGET.json", budget)
    write(
        a.out / "FREEZE-RECEIPT.json",
        {
            "packet_digest": p["packet_digest"],
            "application_commit": p["application_commit"],
            "snapshot_digest": p["snapshot_digest"],
            "scoring_policy_digest": _digest(p["scoring"]),
            "heldout_case_ids": [c["id"] for c in p["cases"] if c["cohort"] == "fresh_system"],
            "excluded_version_ids": excluded,
            "heldout_source_partition_overlap": False,
            "human_labels": None,
            "provider_contacts": 0,
            "new_spend": "0",
            "authority_created": False,
            "fixture_database_permanently_provider_disabled": True,
            "full_schedule_blocked_pending_separate_cap_review": True,
        },
    )
    print(
        json.dumps(
            {
                "packet_digest": p["packet_digest"],
                "cases": len(p["cases"]),
                "heldout": 8,
                "excluded_versions": len(excluded),
                "provider_contacts": 0,
                "new_spend": "0",
                "approved": False,
            }
        )
    )
