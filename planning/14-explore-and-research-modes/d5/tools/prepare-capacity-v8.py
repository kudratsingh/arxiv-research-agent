"""Prepare or replay a capacity-bound v8 successor. OFFLINE ONLY, no live writer.

Run from the worktree root using python - ... < this file. D5_POSTGRES_URL must
name NEW disposable fixture storage. Private financial replay is never published.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator
from psycopg.types.json import Jsonb

from src.workspace import d5_fixture
from src.workspace import programme_capacity as capacity
from src.workspace.admission import AdmissionError, _digest
from src.workspace.assistance_contract import response_purpose
from src.workspace.d5_adapter import D5Adapter, D5MeasurementAdapter, qualification_producer
from src.workspace.d5_authorization import grant_external, stage_template
from src.workspace.d5_benchmark import database, read, run, write
from src.workspace.d5_fixture import authorize_fixture, install, prepare_projects
from src.workspace.d5_freeze import code_bindings, compile_inputs, restore_input, verify
from src.workspace.programme_amendments import effective_limits
from src.workspace.qualification_budget import census, guard_program
from src.workspace.store import WorkspaceStore

PROGRAM = "research-evaluation-20261105-v1"
BASELINE = {"jobs": 20, "Messages": 35, "counts": 54, "usd": "0.904053"}


def install_private(store, captured):
    install(store, captured, fixture=True)
    with store.pool.connection() as conn:
        for row in captured["recorded_third_amendments"]:
            assert _digest(row["record"]) == row["authorization_digest"]
            conn.execute(
                "INSERT INTO workspace_programme_third_amendments SELECT * FROM jsonb_populate_record(NULL::workspace_programme_third_amendments,%s)",
                (Jsonb(row),),
            )


def verify_live(captured):
    """The only active-ledger operation is this repeatable, read-only audit."""
    with (
        database(
            "postgresql://workspace:workspace-local-only@127.0.0.1:15488/workspace_d5_prose_v6_validation"
        ) as pool,
        pool.connection() as conn,
    ):
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        members = sorted(
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (PROGRAM,)
            )
        )
        h = census(conn, members[0], members=members)
        assert h == captured["history"]
        baseline = conn.execute(
            "SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s", (PROGRAM,)
        ).fetchone()[0]
        assert (
            len(set(h["generation_job_ids"]) - set(baseline["generation_job_ids"]))
            == BASELINE["jobs"]
        )
        assert h["messages"] == 35 and h["counts"] == 54 and h["known_usd"] == BASELINE["usd"]
        assert (
            h["pending_usd"] == h["unknown_usd"] == "0"
            and not h["active_jobs"]
            and not h["uncertain_contacts"]
        )
        assert effective_limits(conn, PROGRAM) == {
            "new_jobs": 24,
            "messages": 80,
            "counts": 80,
            "usd": "10",
            "concurrency": 1,
        }
        table = conn.execute(
            "SELECT to_regclass('workspace_programme_capacity_amendments')"
        ).fetchone()[0]
        assert (
            not table
            or not conn.execute(
                "SELECT 1 FROM workspace_programme_capacity_amendments WHERE program_id=%s",
                (PROGRAM,),
            ).fetchone()
        )
        prospective = capacity.proposal(conn, PROGRAM)
        for scope in ("d5-cf6b9e4c1e49d0192467bd28", "d5-premise-a6056aa2237fce4385f0f531"):
            assert (
                conn.execute(
                    "SELECT state FROM workspace_d5_scopes WHERE scope_id=%s", (scope,)
                ).fetchone()[0]
                == "stopped"
            )
    return {
        "baseline": BASELINE,
        "read_only": True,
        "history_digest": h["history_digest"],
        "capacity_proposal_digest": prospective["proposal_digest"],
        "amendment_activated": False,
        "provider_contacts": 0,
    }


def prepare(store, captured, previous, out):
    audit = verify_live(captured)
    assert previous["packet_digest"] == _digest(
        {k: v for k, v in previous.items() if k != "packet_digest"}
    )
    assert captured["history"] == previous["history"]
    install_private(store, captured)
    with store.pool.connection() as conn:
        proposal = capacity.proposal(conn, PROGRAM)
    assert proposal["proposal_digest"] == audit["capacity_proposal_digest"]
    p = deepcopy(previous)
    p.update(
        predecessor_packet_digest=previous["packet_digest"],
        application_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        code=code_bindings(),
        adapter=qualification_producer(),
        programme_amendment=proposal,
        refreshed_at=datetime.now(UTC).isoformat(),
        offline_fixture_revision="capacity-envelope-v2-correct-v8-insufficient-id",
        refresh_policy="Prospective capacity-code binding only; no corpus, question, selection, schema, prompt, rubric, threshold or historical result changes.",
    )
    p["required_separate_decisions"].update(
        policy_extension_required=False,
        policy_extension_implemented=True,
        authorization_recorded=False,
        amendment_activated=False,
        dispatch="Capacity activation, A, B, C and D each require separate explicit approvals. No stopped scope is reopened.",
    )
    p["packet_digest"] = _digest({k: v for k, v in p.items() if k != "packet_digest"})
    verify(p)
    frozen = (
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
        "historical_v7r2",
        "historical_premise_calibration",
    )
    for name in frozen:
        assert p[name] == previous[name], name
    prepare_projects(store, p)
    compiled = compile_inputs(p)

    def deny(_):
        raise AssertionError("Offline export cannot contact HTTP")

    bindings = {}
    for name in ("measure-1", "dev-learn", "dev-compare"):
        e = compiled[name]
        cls = D5MeasurementAdapter if e["stage"] == "A" else D5Adapter
        wire = cls(
            store, e["owner"], restore_input(e["input"]), transport=httpx.MockTransport(deny)
        ).request()
        body = (
            wire["body"]
            if e["stage"] != "A"
            else {k: v for k, v in wire["body"].items() if k not in {"max_tokens", "temperature"}}
        )
        bindings[name] = {
            "input_digest": _digest(e["input"]),
            "request_digest": _digest(body),
            "model": body["model"],
            "stage": e["stage"],
            "request_id": e["input"]["settings"]["d5_request_id"],
        }
        write(out / (name + "-request.json"), body)
    for case in p["cases"]:
        if case["cohort"] == "development":
            write(out / (case["id"] + "-response-schemas.json"), case["sealed"]["response_schemas"])
    old_count = read(
        Path(
            "planning/14-explore-and-research-modes/d5/evidence/qualification-v8r3/measure-1-request.json"
        )
    )
    count = read(out / "measure-1-request.json")
    all_contacts = [
        c
        for row in captured["tables"]["workspace_generation_jobs"]
        for c in row["data"].get("adapter", {}).get("contacts", [])
        if c["endpoint"] == "messages/count_tokens"
    ]
    matches = [
        c
        for c in all_contacts
        if c["state"] == "completed" and _digest(c["body"]) == _digest(count)
    ]
    assert len(all_contacts) == 54 and not matches
    write(out / "packet.json.gz", p)
    write(out / "CAPACITY-PROPOSAL.json", proposal)
    write(out / "INITIAL-BINDINGS.json", bindings)
    write(out / "LEDGER-AUDIT.json", audit)
    write(
        out / "MEASUREMENT-AUDIT.json",
        {
            "historical_counts_compared": 54,
            "matching_receipts": 0,
            "identical_to_unexecuted_v8r3": count == old_count,
            "fresh_A_required": True,
            "request_digest": _digest(count),
            "reuse_authorized": False,
        },
    )
    write(
        out / "FREEZE-RECEIPT.json",
        {
            "packet_digest": p["packet_digest"],
            "application_commit": p["application_commit"],
            "capacity_proposal_digest": proposal["proposal_digest"],
            "unchanged_fields": list(frozen),
            "predecessor_packet_digest": previous["packet_digest"],
            "source_snapshot_digest": _digest(captured),
            "authority_created": False,
            "provider_contacts": 0,
            "new_spend_usd": "0",
        },
    )
    print(
        json.dumps(
            {
                "packet_digest": p["packet_digest"],
                "proposal_digest": proposal["proposal_digest"],
                "application_commit": p["application_commit"],
                "provider_contacts": 0,
            }
        )
    )


class CapacityTransport:
    """Wire-valid maximum-envelope fixtures, not semantic/model evidence."""

    instances = []

    def __init__(self, case_id, **_):
        self.case_id, self.contacts, self.checks = case_id, [], 0
        self.instances.append(self)

    async def __call__(self, request):
        assert request.headers["x-api-key"] == "local-preview-disabled"
        body = json.loads(request.content)
        self.contacts.append({"endpoint": request.url.path, "digest": _digest(body)})
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        ctx = json.loads(body["messages"][0]["content"])
        if ctx["phase"] == "check":
            self.checks += 1
            probe = self.case_id.startswith("probe-")
            first = self.checks == 1 and not probe
            claims = ctx["claim_inputs"]
            output = {
                "checks": [
                    {
                        "claim_id": c["claim_id"],
                        "input_digest": c["input_digest"],
                        "decision": "unsupported" if probe or first else "supported",
                        "reason": "Synthetic capacity stimulus, not a quality judgment.",
                    }
                    for c in claims
                ],
                "prose_review": "procedural_only",
                "prose_findings": [],
            }
            if first and not claims:
                output.update(
                    prose_review="unscored_factual_content",
                    prose_findings=[
                        {
                            "field": "questions",
                            "index": 0,
                            "reason": "Synthetic located repair stimulus; no provider quality evidence.",
                        }
                    ],
                )
        else:
            original = ctx["sealed_request"]
            chosen, works = [], set()
            for handle, ref in original["units"].items():
                if ref["work_id"] not in works:
                    works.add(ref["work_id"])
                    sentence = next(
                        (
                            m.group(0).strip()
                            for m in re.finditer(r".+?(?:[.!?](?=\s|$)|$)", ref["quote"], re.S)
                            if 20 <= len(m.group(0).strip()) <= 350
                        ),
                        "",
                    )
                    assert sentence, (
                        "Do not substitute evidence when the fixture cannot form a bounded claim"
                    )
                    chosen.append(
                        {
                            "claim_id": "c" + str(len(chosen) + 1),
                            "text": sentence,
                            "handles": [handle],
                            "required_scope": ref["scope"],
                        }
                    )
            research = (
                response_purpose(original["assistance"]["mode"], original["units"])
                == "research_comparison"
            )
            output = {
                "claims": chosen,
                "background_claims": [c["claim_id"] for c in chosen],
                "assumption_claims": [],
                "limitation_claims": [],
                "gaps": ["methods"],
                "questions": [{"intent": "measured_and_proposed", "claim_ids": []}],
                "proposal": "request_context",
                "abstention": None,
            }
            if research:
                output.update(
                    comparison_claims=[c["claim_id"] for c in chosen],
                    comparison_basis=[c["claim_id"] for c in chosen],
                )
            if self.case_id.endswith("research-insufficient"):
                output.update(
                    claims=[], background_claims=[], abstention="application_context_required"
                )
                if research:
                    output.update(comparison_claims=[], comparison_basis=[])
        Draft202012Validator(body["output_config"]["format"]["schema"]).validate(output)
        return httpx.Response(
            200,
            json={
                "id": "synthetic-capacity-" + self.case_id + "-" + str(len(self.contacts)),
                "model": body["model"],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 100},
                "content": [{"type": "text", "text": json.dumps(output)}],
            },
        )


def synthetic(receipt):
    value = deepcopy(receipt)
    value.update(
        approved=True,
        approved_by="Disposable synthetic capacity fixture, not owner approval",
        approved_at=datetime.now(UTC).isoformat(),
        authorization_kind="offline_fixture",
        transport_mode="mock",
        authorization_reference="Offline capacity simulation only; no live authority",
    )
    return value


async def replay(store, captured, packet, out):
    verify(packet)
    install_private(store, captured)
    prepare_projects(store, packet)
    with store.pool.connection() as conn:
        p = capacity.proposal(conn, PROGRAM)
        assert p["proposal_digest"] == packet["programme_amendment"]["proposal_digest"]
        before = census(
            conn, p["amendment"]["basis_members"][0], members=p["amendment"]["basis_members"]
        )
        assert before == packet["history"]
        assert effective_limits(conn, PROGRAM)["new_jobs"] == 24
    activation = capacity.record_external(store, synthetic(p))
    assert activation["workflow_permission_created"] is False
    compiled = compile_inputs(packet)
    e = compiled["measure-1"]
    adapter = D5MeasurementAdapter(
        store,
        e["owner"],
        restore_input(e["input"]),
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("Unauthorized HTTP"))
        ),
    )
    try:
        adapter.start(e["input"]["settings"]["d5_request_id"], "0")
    except AdmissionError as err:
        no_stage = str(err)
    else:
        raise AssertionError("Cap activation must not authorize A")
    authorize_fixture(store, packet, stages=("A",))
    old_transport = d5_fixture.ReplayTransport
    d5_fixture.ReplayTransport = CapacityTransport
    denials = {"A_without_stage_grant": no_stage}
    try:
        report = await run(store, packet, "A", offline=True)
        for stage in ("B", "C", "D"):
            try:
                await run(store, packet, stage, offline=True)
            except AdmissionError as err:
                assert "d5_stage_not_authorized" in str(err), str(err)
                denials[stage + "_without_stage_grant"] = str(err)
            else:
                raise AssertionError("Separate stage grant missing")
            scope = "d5-" + packet["packet_digest"][:24]
            grant = stage_template(store, scope, [stage])
            grant_external(store, scope, synthetic(grant))
            report = await run(store, packet, stage, offline=True)
    finally:
        d5_fixture.ReplayTransport = old_transport
    with store.pool.connection() as conn:
        members = sorted(
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (PROGRAM,)
            )
        )
        current = census(conn, members[0], members=members)
        original = conn.execute(
            "SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s", (PROGRAM,)
        ).fetchone()[0]
        jobs = len(set(current["generation_job_ids"]) - set(original["generation_job_ids"]))
        assert (jobs, current["messages"], current["counts"]) == (34, 79, 99)
        assert (
            current["known_usd"] == "0.904053"
            and current["pending_usd"] == current["unknown_usd"] == "0"
        )
        assert (
            census(
                conn,
                members[0],
                members=p["amendment"]["basis_members"],
                job_ids=sorted(before["contact_checkpoints"]),
            )
            == before
        )
        funded = next(e["owner"] for e in compiled.values() if e["stage"] == "B")
        policy = conn.execute(
            "SELECT data FROM workspace_budget_policies WHERE owner=%s", (funded,)
        ).fetchone()[0]
        for name, kwargs, expected in [
            (
                "job35",
                {
                    "reserve_usd": Decimal("0.15"),
                    "next_endpoint": None,
                    "reserve_operation": "probe",
                },
                "program_job_cap_exceeded",
            ),
            (
                "count100",
                {
                    "reserve_usd": None,
                    "next_endpoint": "messages/count_tokens",
                    "reserve_operation": "measurement",
                },
                "program_contact_cap_exceeded",
            ),
        ]:
            try:
                guard_program(conn, funded, policy, current_job=None, **kwargs)
            except AdmissionError as err:
                assert expected in str(err)
                denials[name] = str(err)
            else:
                raise AssertionError("Capacity overflow accepted")
    assert all(c["completion"] for c in report["cases"])
    insufficient = next(c for c in report["cases"] if c["id"].endswith("research-insufficient"))
    workflow = next(
        s["output"]
        for s in reversed(report["raw_results"][insufficient["id"]]["steps"])
        if s["stage"] in {"draft", "repair"}
    )
    assert workflow["claims"] == [] and workflow["abstention"] == "application_context_required"
    assert insufficient["abstention"], (
        "Completion without appropriate abstention is not this case's success"
    )
    assert not report["checker_qualified"] and report["human_labels"] is None
    write(out / "REPORT.json.gz", report)
    write(
        out / "REPLAY-RECEIPT.json",
        {
            "packet_digest": packet["packet_digest"],
            "application_commit": packet["application_commit"],
            "baseline": BASELINE,
            "final_synthetic_census": {
                "jobs": jobs,
                "Messages": current["messages"],
                "counts": current["counts"],
                "known_usd": current["known_usd"],
                "pending_usd": current["pending_usd"],
                "unknown_usd": current["unknown_usd"],
            },
            "new_mock_jobs": 14,
            "mock_Messages": 44,
            "mock_counts": 45,
            "real_provider_contacts": 0,
            "real_new_spend_usd": "0",
            "denials": denials,
            "historical_financial_rows_preserved": True,
            "human_labels": None,
            "checker_qualified": False,
            "synthetic_authority_confined_to_fixture": True,
        },
    )
    verify_live(captured)
    print(
        json.dumps(
            {
                "replay": "completed",
                "jobs": jobs,
                "Messages": current["messages"],
                "counts": current["counts"],
                "provider_contacts": 0,
                "acceptance": "HOLD; synthetic labels/counts are not quality evidence",
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["prepare", "replay"])
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    a = parser.parse_args()
    assert (
        os.environ.get("ANTHROPIC_API_KEY") == "local-preview-disabled"
        and os.environ.get("WORKSPACE_D5_OFFLINE") == "1"
    )
    assert not a.out.exists(), "New artifact revision required"
    a.out.mkdir(parents=True)
    captured = read(a.snapshot)
    with database(os.environ["D5_POSTGRES_URL"]) as pool:
        store = WorkspaceStore(pool)
        if a.verb == "prepare":
            prepare(store, captured, read(a.packet), a.out)
        else:
            asyncio.run(replay(store, captured, read(a.packet), a.out))


if __name__ == "__main__":
    main()
