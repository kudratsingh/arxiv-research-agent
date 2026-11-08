"""Offline ledger-only v8 refresh. Preserve the corpus/cohort and all predecessors.

Run via python - < this_file from the worktree root. No provider/approval writer.
The complete financial replay now contains private review proofs: local only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
from psycopg.types.json import Jsonb

from src.workspace.admission import _digest
from src.workspace.d5_adapter import D5Adapter, D5MeasurementAdapter
from src.workspace.d5_benchmark import database, read, write
from src.workspace.d5_fixture import FINANCIAL_TABLES, financial_rows, install, prepare_projects
from src.workspace.d5_freeze import compile_inputs, execution_owners, restore_input, verify
from src.workspace.d5_operations import ROUTES, reservation
from src.workspace.programme_amendments import effective_limits
from src.workspace.qualification_budget import census
from src.workspace.store import WorkspaceStore

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--private-out", type=Path, required=True)
parser.add_argument("--public-out", type=Path, required=True)
a = parser.parse_args()
assert os.environ.get("ANTHROPIC_API_KEY") == "local-preview-disabled"
assert os.environ.get("WORKSPACE_D5_OFFLINE") == "1"
assert not a.private_out.exists() and not a.public_out.exists(), "Choose new artifact revision"
a.private_out.mkdir(parents=True, mode=0o700)
a.public_out.mkdir(parents=True)
os.umask(0o077)
root = Path.cwd()
base = root / "planning/14-explore-and-research-modes/d5"
previous = read(base / "d5-system-validation-v8r2.json.gz")
verify(previous)
captured = read(base / "d5-replay-inputs-v8.json.gz")
original = Path("/private/tmp/arxiv-agent-eng-workspace-assistance")
calibration = Path(
    "/private/tmp/arxiv-agent-eng-calibration-preflight/outputs/d5/premise-calibration-live-20261108"
)
ptr = read(original / "outputs/d5/ACTIVE-QUALIFICATION-LEDGER.json")
cal = read(calibration / "CALIBRATION-RESULTS.json")
money = read(calibration / "ACCOUNTING.json")
assert ptr["active_database"] == "workspace_d5_prose_v6_validation"
assert (
    money["cumulative_programme_jobs"] == 20
    and money["cumulative_Messages"] == 35
    and money["cumulative_counts"] == 54
    and money["cumulative_estimated_usd"] == "0.904053"
)
assert (
    cal["status"] == "COMPLETED_FOUR_PROBE_DIAGNOSTIC_STOPPED_FOR_REVIEW"
    and cal["scope_state"] == "stopped"
    and not cal["qualification"]
)
program = "research-evaluation-20261105-v1"
amendment = previous["programme_amendment"]["proposal_digest"]
with database(
    "postgresql://workspace:workspace-local-only@127.0.0.1:15488/" + ptr["active_database"]
) as pool, pool.connection() as c:
    c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    members = sorted(
        r[0]
        for r in c.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program,)
        )
    )
    history = census(c, members[0], members=members)
    programme_base = c.execute(
        "SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s", (program,)
    ).fetchone()[0]
    jobs = len(set(history["generation_job_ids"]) - set(programme_base["generation_job_ids"]))
    assert (
        jobs == 20
        and history["messages"] == 35
        and history["counts"] == 54
        and Decimal(history["known_usd"]) == Decimal("0.904053")
    )
    assert (
        history["pending_usd"] == history["unknown_usd"] == "0"
        and not history["active_jobs"]
        and not history["uncertain_contacts"]
    )
    limits = effective_limits(c, program, required_proposal_digest=amendment)
    assert limits == {
        "new_jobs": 24,
        "messages": 80,
        "counts": 80,
        "usd": "10",
        "concurrency": 1,
    }
    assert (
        c.execute(
            "SELECT state FROM workspace_d5_scopes WHERE scope_id=%s",
            ("d5-cf6b9e4c1e49d0192467bd28",),
        ).fetchone()[0]
        == "stopped"
    )
    assert (
        c.execute(
            "SELECT state FROM workspace_d5_scopes WHERE scope_id=%s", (cal["scope_id"],)
        ).fetchone()[0]
        == "stopped"
    )
    assert not c.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone()
    for owner in execution_owners(previous):
        assert not c.execute(
            "SELECT 1 FROM workspace_generation_jobs WHERE owner=%s", (owner,)
        ).fetchone(), "Prospective principal already used"
    for name in FINANCIAL_TABLES:
        captured["tables"][name] = financial_rows(c, name)
    for table, key in [
        ("workspace_programme_amendments", "recorded_amendments"),
        ("workspace_programme_successor_amendments", "recorded_successor_amendments"),
        ("workspace_programme_third_amendments", "recorded_third_amendments"),
        ("workspace_d5_scopes", "historical_scopes"),
        ("workspace_d5_stage_authorizations", "historical_stage_grants"),
    ]:
        captured[key] = [r[0] for r in c.execute("SELECT to_jsonb(t) FROM " + table + " t")]
    all_counts = [
        {
            "job_id": i,
            "request_digest": _digest(contact["body"]),
            "model": contact["body"].get("model"),
            "state": contact["state"],
        }
        for i, d in c.execute(
            "SELECT id,data FROM workspace_generation_jobs WHERE owner=ANY(%s)", (members,)
        )
        for contact in d.get("adapter", {}).get("contacts", [])
        if contact["endpoint"] == "messages/count_tokens"
    ]
captured["history"] = history
captured["provenance"] = (
    "Original frozen public corpus/profile retained; current complete financial history includes private prereview proofs. PRIVATE LOCAL REPLAY ONLY; no operative policy/approval created."
)
write(a.private_out / "FINANCIAL-REPLAY-PRIVATE.json.gz", captured)
p = deepcopy(previous)
p.update(
    history=history,
    application_commit="d3a1d05297a7aa4c93f0f7ff6f492030bd06d36e",
    refreshed_at=datetime.now(UTC).isoformat(),
    predecessor_packet_digest=previous["packet_digest"],
    snapshot_digest=_digest(captured),
)
p["snapshot_location"] = {
    "visibility": "private local financial replay; not committed",
    "filename": "FINANCIAL-REPLAY-PRIVATE.json.gz",
    "public_corpus_predecessor": "d5-replay-inputs-v8.json.gz",
    "reason": "New financial records contain locked independent-review proofs; public artifacts expose hashes/aggregates only.",
}
p["historical_paid_baseline"] = {
    "programme_jobs": 20,
    "Messages": 35,
    "counts": 54,
    "estimated_usd": "0.904053",
    "workflow_estimated_usd": "0.285853",
    "checker_estimated_usd": "0.618200",
    "pending_usd": "0",
    "unknown_usd": "0",
}
p["historical_v7r2"] = {
    **previous["historical_v7r2"],
    "packet_digest": "cf6b9e4c1e49d0192467bd28d0bae00eb1d05cf85bb850f904902840937fc871",
    "record_sha256": hashlib.sha256(
        (original / "outputs/d5/stage-c-v7r2-20261108/STAGE-C-RESULTS.json").read_bytes()
    ).hexdigest(),
    "never_replay": True,
}
p["historical_premise_calibration"] = {
    "packet_digest": cal["packet_digest"],
    "application_commit": cal["application_commit"],
    "scope_id": cal["scope_id"],
    "scope_state": "stopped",
    "record_sha256": hashlib.sha256(
        (calibration / "CALIBRATION-RESULTS.json").read_bytes()
    ).hexdigest(),
    "accounting_sha256": hashlib.sha256((calibration / "ACCOUNTING.json").read_bytes()).hexdigest(),
    "completed_probes": 4,
    "false_pass": {"numerator": 0, "denominator": 2},
    "false_reject": {"numerator": 0, "denominator": 2},
    "abstentions": 0,
    "new_jobs": 4,
    "new_Messages": 4,
    "new_counts": 4,
    "new_estimated_usd": "0.078988",
    "unique_underlying_claims": 1,
    "qualified": False,
    "classification": "Separate small matched-set diagnostic. Not development evidence, fresh held-out completion, human whole-claim support or the 20-probe system minimum.",
}
p["required_separate_decisions"].update(
    full_schedule_job_cap=34,
    full_schedule_count_cap=99,
    Messages_cap=80,
    usd_cap="10",
    active_job_cap=24,
    active_count_cap=80,
    authorization_recorded=False,
    amendment_activated=False,
    policy_extension_required=True,
    dispatch="A/B fit current limits and need separate approvals. Full C/D schedule also needs separately reviewed job/count policy extension and amendment; no stopped scope is reopened.",
)
p["refresh_policy"] = (
    "Ledger/provenance metadata only. Frozen corpus,profile,clock,questions,rankings,selections,schemas,prompts,scoring and stop rules unchanged. No paid v8 output collected."
)
p["packet_digest"] = _digest({k: v for k, v in p.items() if k != "packet_digest"})
verify(p)
for field in (
    "corpus",
    "profile",
    "clock",
    "cases",
    "probes",
    "scoring",
    "human_rubric",
    "ranking_policy",
    "selection_policy",
    "checker_schema",
    "execution",
    "operation_routes",
    "dynamic_requests",
    "stop_rules",
):
    assert p[field] == previous[field], field
cal_versions = {ref["version_id"] for case in cal["cases"] for ref in case["source_refs"]}
heldout_versions = {
    ref["version_id"]
    for case in p["cases"]
    if case["cohort"] == "fresh_system"
    for ref in case["sealed"]["units"].values()
}
assert not cal_versions & heldout_versions
write(a.public_out / "packet.json.gz", p)
with database(os.environ["D5_POSTGRES_URL"]) as pool:
    store = WorkspaceStore(pool)
    install(store, captured, fixture=True)
    with pool.connection() as c:
        for row in captured["recorded_third_amendments"]:
            assert _digest(row["record"]) == row["authorization_digest"]
            c.execute(
                "INSERT INTO workspace_programme_third_amendments SELECT * FROM jsonb_populate_record(NULL::workspace_programme_third_amendments,%s)",
                (Jsonb(row),),
            )
    prepare_projects(store, p)
    compiled = compile_inputs(p)

    def deny(_):
        raise AssertionError("Offline export cannot contact HTTP")

    requests = {}
    bindings = {}
    for name in ("measure-1", "dev-learn", "dev-compare"):
        entry = compiled[name]
        cls = D5MeasurementAdapter if entry["stage"] == "A" else D5Adapter
        wire = cls(
            store,
            entry["owner"],
            restore_input(entry["input"]),
            transport=httpx.MockTransport(deny),
        ).request()
        body = (
            wire["body"]
            if entry["stage"] == "B"
            else {k: v for k, v in wire["body"].items() if k not in {"max_tokens", "temperature"}}
        )
        requests[name] = body
        write(a.public_out / (name + "-request.json"), body)
        bindings[name] = {
            "stage": entry["stage"],
            "owner": entry["owner"],
            "request_id": entry["input"]["settings"]["d5_request_id"],
            "input_digest": _digest(entry["input"]),
            "request_digest": _digest(body),
            "model": body["model"],
            "settings": entry["input"]["settings"],
            "source_refs": entry["input"]["sources"],
        }
    assert requests["measure-1"] == read(base / "evidence/procedural-v8r2/measure-1-request.json")
    reuse = {
        "candidate_measure_1_digest": _digest(requests["measure-1"]),
        "unchanged_from_unexecuted_v8r2_export": True,
        "completed_historical_count_contacts_compared": len(all_counts),
        "exact_matching_completed_receipts": [
            x
            for x in all_counts
            if x["state"] == "completed" and x["request_digest"] == _digest(requests["measure-1"])
        ],
        "reuse_authorized": False,
        "new_measurement_required": True,
        "reason": "No v8 measurement was executed. Prior v7 requests and four checker-only Opus measurements differ from this Sonnet Compare request; dynamic checks/repair/recheck still need exact paired measurements.",
    }
    assert not reuse["exact_matching_completed_receipts"]
    with pool.connection() as c:
        assert c.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone()
        assert c.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0
        assert not c.execute(
            "SELECT 1 FROM workspace_d5_scopes WHERE scope_id=%s",
            ("d5-" + p["packet_digest"][:24],),
        ).fetchone()
        assert census(c, members[0], members=members) == history
    write(a.private_out / "COMPILED-INPUTS.json.gz", compiled)
    write(a.public_out / "INITIAL-BINDINGS.json", bindings)
    write(a.public_out / "MEASUREMENT-REUSE-AUDIT.json", reuse)
    for case in p["cases"]:
        if case["cohort"] == "development":
            write(
                a.public_out / (case["id"] + "-response-schemas.json"),
                case["sealed"]["response_schemas"],
            )
budget = {
    "baseline": p["historical_paid_baseline"],
    "stages": {
        "A": {"funded_jobs": 0, "Messages": 0, "counts": 1, "reservation_usd": "0"},
        "B": {"funded_jobs": 2, "Messages": 8, "counts": 8, "reservation_usd": "0.90"},
        "C": {"funded_jobs": 8, "Messages": 32, "counts": 32, "reservation_usd": "3.60"},
        "D": {"funded_jobs": 4, "Messages": 4, "counts": 4, "reservation_usd": "0.60"},
    },
    "new_full_schedule": {
        "jobs": 14,
        "Messages": 44,
        "counts": 45,
        "reservation_usd": "5.10",
        "usage_bound_usd": str(reservation(ROUTES) * 10 + reservation(ROUTES, probe=True) * 4),
    },
    "cumulative_maximum": {
        "jobs": 34,
        "Messages": 79,
        "counts": 99,
        "known_plus_reservation_usd": "6.004053",
        "known_plus_reservation_plus_buffer_usd": "7.004053",
    },
    "A_then_B_cumulative_maximum": {
        "jobs": 22,
        "Messages": 43,
        "counts": 63,
        "known_plus_reservation_usd": "1.804053",
    },
    "amendment_required": {
        "jobs": {"current": 24, "proposed": 34, "increase": 10},
        "counts": {"current": 80, "proposed": 99, "increase": 19},
        "Messages_unchanged": 80,
        "usd_unchanged": "10",
        "concurrency_unchanged": 1,
        "expiry_unchanged": "2026-11-14T07:24:01Z",
        "active": False,
        "policy_implementation_required": True,
    },
    "authority_created": False,
    "provider_Messages": 0,
    "token_count_contacts": 0,
    "new_spend_usd": "0",
}
write(a.public_out / "BUDGET.json", budget)
proof = {
    "packet_digest": p["packet_digest"],
    "predecessor_packet_digest": previous["packet_digest"],
    "application_commit": p["application_commit"],
    "source_code_and_adapter_hashes_unchanged": p["code"] == previous["code"]
    and p["adapter"] == previous["adapter"],
    "all_frozen_input_and_scoring_fields_unchanged": True,
    "v7r2_preserved_separately": p["historical_v7r2"],
    "premise_calibration_preserved_separately": p["historical_premise_calibration"],
    "calibration_heldout_source_overlap": [],
    "snapshot_digest": p["snapshot_digest"],
    "private_snapshot_file_sha256": hashlib.sha256(
        (a.private_out / "FINANCIAL-REPLAY-PRIVATE.json.gz").read_bytes()
    ).hexdigest(),
    "snapshot_published": False,
    "fixture_database": os.environ["D5_POSTGRES_URL"].rsplit("/", 1)[1],
    "fixture_permanently_provider_disabled": True,
    "new_scope_authority_created": False,
    "provider_Messages": 0,
    "token_count_contacts": 0,
    "new_spend_usd": "0",
}
write(a.public_out / "REFRESH-RECEIPT.json", proof)
print(
    json.dumps(
        {
            "packet_digest": p["packet_digest"],
            "scope_id": "d5-" + p["packet_digest"][:24],
            "baseline_jobs": 20,
            "baseline_Messages": 35,
            "baseline_counts": 54,
            "baseline_usd": "0.904053",
            "A_count_request_digest": bindings["measure-1"]["request_digest"],
            "full_cumulative": budget["cumulative_maximum"],
            "provider_contacts": 0,
            "approved": False,
        }
    )
)
