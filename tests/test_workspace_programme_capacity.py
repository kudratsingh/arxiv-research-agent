"""Append-only capacity approval in disposable Postgres; no provider contacts.

Synthetic receipts and contact records exercise production admission, never
human authorization, real measurements, or benchmark-quality evidence.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from psycopg.types.json import Jsonb

from src.workspace import programme_amendments as original
from src.workspace import programme_capacity as capacity
from src.workspace import programme_third_amendment as predecessor
from src.workspace.admission import AdmissionError, _digest
from src.workspace.qualification_budget import PROGRAM_LIMITS, census, guard_program
from tests import test_workspace_programme_amendments as support
from tests import test_workspace_programme_third_amendment as third

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


def setup(store):
    _, pending = third.setup(store)
    predecessor.record_external(store, third.approved(pending))
    with store.pool.connection() as conn:
        parents = {
            table: conn.execute("SELECT to_jsonb(t) FROM " + table + " t").fetchall()
            for table in (
                "workspace_evaluation_programs",
                "workspace_programme_amendments",
                "workspace_programme_successor_amendments",
                "workspace_programme_third_amendments",
            )
        }
        template = capacity.proposal(conn, "evaluation")
    return template, parents


def approved(template):
    receipt = support.approved(template)
    receipt["expires_at"] = template["amendment"]["predecessor_expiry"]
    return receipt


def test_template_is_capacity_only_and_never_activates(store):
    proposal, parents = setup(store)
    assert proposal["approved"] is False
    assert proposal["amendment"]["prior_limits"] == {**PROGRAM_LIMITS, "new_jobs": 24}
    assert proposal["amendment"]["amended_limits"] == {
        **PROGRAM_LIMITS,
        "new_jobs": 34,
        "counts": 99,
    }
    with pytest.raises(AdmissionError):
        capacity.record_external(store, proposal)
    with store.pool.connection() as c:
        assert original.effective_limits(c, "evaluation")["counts"] == 80
        assert original.effective_limits(c, "evaluation")["new_jobs"] == 24
        assert c.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0
        for table, rows in parents.items():
            assert c.execute("SELECT to_jsonb(t) FROM " + table + " t").fetchall() == rows


def test_activation_preserves_receipts_history_expiry_and_original_policy(store):
    p, parents = setup(store)
    r = approved(p)
    result = capacity.record_external(store, r)
    assert result["effective_jobs"] == 34 and result["effective_counts"] == 99
    assert result["workflow_permission_created"] is False and result["provider_contacts"] == 0
    assert capacity.record_external(store, r)["duplicate"]
    with store.pool.connection() as c:
        assert (
            original.effective_limits(
                c, "evaluation", required_proposal_digest=p["proposal_digest"]
            )
            == p["amendment"]["amended_limits"]
        )
        assert census(c, "a") == p["amendment"]["basis"]
        for table, rows in parents.items():
            assert c.execute("SELECT to_jsonb(t) FROM " + table + " t").fetchall() == rows
        assert c.execute(
            "SELECT expires_at FROM workspace_programme_capacity_amendments"
        ).fetchone()[0] == datetime.fromisoformat(p["amendment"]["predecessor_expiry"])
        assert c.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0
        c.execute(
            "INSERT INTO workspace_evaluation_programs SELECT 'other',parent_trial_id,limits,baseline,authorization_digest,created_at FROM workspace_evaluation_programs WHERE program_id='evaluation'"
        )
        assert original.effective_limits(c, "other") == PROGRAM_LIMITS


@pytest.mark.asyncio
@pytest.mark.parametrize("amended,last_allowed", [(False, 24), (True, 34)])
async def test_job_boundary_through_actual_adapter(store, amended, last_allowed):
    p, _ = setup(store)
    if amended:
        capacity.record_external(store, approved(p))
    support.seed_failed(store, 7, last_allowed - 8)
    await support.execute(store, "last-allowed")
    adapter = support.support.adapter(store, request_id="over-cap")
    with pytest.raises(AdmissionError, match="program_job_cap_exceeded"):
        adapter.start("over-cap", "0.25")
    with store.pool.connection() as c:
        assert len(census(c, "a")["generation_job_ids"]) - 1 == last_allowed


@pytest.mark.parametrize("amended,limit", [(False, 80), (True, 99)])
def test_count_boundary_uses_production_admission_without_messages_or_new_job(
    store, amended, limit
):
    p, _ = setup(store)
    if amended:
        capacity.record_external(store, approved(p))
    support.seed_failed(store, 7, 1)
    with store.pool.connection() as c:
        current = census(c, "a")["counts"]
        data = c.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id='synthetic-failed-programme-7'"
        ).fetchone()[0]
        data["adapter"]["contacts"] = [
            {"endpoint": "messages/count_tokens", "state": "completed", "ordinal": i}
            for i in range(limit - 1 - current)
        ]
        c.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id='synthetic-failed-programme-7'",
            (Jsonb(data),),
        )
        policy = {
            "purpose": "workspace-d5-qualification-only",
            "program_id": "evaluation",
            "program_authorization_digest": support.support.AUTH,
        }

        def guard():
            return guard_program(
                c,
                "a",
                policy,
                reserve_usd=Decimal(0),
                current_job=None,
                next_endpoint="messages/count_tokens",
                reserve_operation="measurement",
            )

        assert guard()["counts"] == limit - 1
        data["adapter"]["contacts"].append(
            {"endpoint": "messages/count_tokens", "state": "completed", "ordinal": limit}
        )
        c.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id='synthetic-failed-programme-7'",
            (Jsonb(data),),
        )
        with pytest.raises(AdmissionError, match="program_contact_cap_exceeded"):
            guard()


@pytest.mark.parametrize(
    "change",
    [
        "jobs",
        "counts",
        "messages",
        "usd",
        "concurrency",
        "program",
        "predecessor",
        "original_auth",
        "baseline",
        "revision",
        "basis",
        "members",
        "unapproved",
        "actor",
        "reference",
        "expiry",
        "shortened_expiry",
        "time",
        "kind",
        "transport",
        "digest",
    ],
)
def test_drift_or_broader_authority_cannot_activate(store, change):
    p, _ = setup(store)
    r = approved(p)
    core = r["amendment"]
    if change in {"jobs", "counts", "messages", "usd", "concurrency"}:
        key = "new_jobs" if change == "jobs" else change
        core["amended_limits"][key] = {
            "jobs": 35,
            "counts": 100,
            "messages": 81,
            "usd": "11",
            "concurrency": 2,
        }[change]
    elif change == "program":
        core["program_id"] = "other"
    elif change == "predecessor":
        core["predecessor_authorization_digest"] = "wrong"
    elif change == "original_auth":
        core["original_authorization_digest"] = "wrong"
    elif change == "baseline":
        core["original_baseline_digest"] = "wrong"
    elif change == "revision":
        core["version"] = 5
    elif change == "basis":
        core["basis"]["counts"] += 1
    elif change == "members":
        core["basis_members"] = [None]
    elif change == "unapproved":
        r["approved"] = False
    elif change == "actor":
        r["approved_by"] = " "
    elif change == "reference":
        r["authorization_reference"] = " "
    elif change in {"expiry", "shortened_expiry"}:
        r["expires_at"] = (
            datetime.fromisoformat(core["predecessor_expiry"])
            + timedelta(seconds=1 if change == "expiry" else -1)
        ).isoformat()
    elif change == "time":
        r["approved_at"] = "not a time"
    elif change == "kind":
        r["authorization_kind"] = "owner"
    elif change == "transport":
        r["transport_mode"] = "provider"
    else:
        r["proposal_digest"] = "wrong"
    if change != "digest":
        r["proposal_digest"] = _digest(core)
    with pytest.raises(AdmissionError):
        capacity.record_external(store, r)
    with store.pool.connection() as c:
        assert original.effective_limits(c, "evaluation")["counts"] == 80


@pytest.mark.parametrize("change", ["census", "members", "pending", "unknown"])
def test_activation_needs_exact_census_and_no_outstanding_liability(store, change):
    p, _ = setup(store)
    support.seed_failed(store, 7, 1)
    with store.pool.connection() as c:
        if change == "members":
            c.execute("INSERT INTO workspace_evaluation_members VALUES('new','evaluation')")
        elif change == "pending":
            c.execute(
                "UPDATE workspace_generation_jobs SET state='running' WHERE id='synthetic-failed-programme-7'"
            )
        elif change == "unknown":
            c.execute(
                "UPDATE workspace_spend_reservations SET unknown=0.01 WHERE job_id='synthetic-failed-programme-7'"
            )
        if change in {"pending", "unknown"}:
            p = capacity.proposal(c, "evaluation")
    with pytest.raises(AdmissionError, match="census_drift|unresolved"):
        capacity.record_external(store, approved(p))


@pytest.mark.parametrize("change", ["hash", "proposal", "expiry", "history", "unknown_required"])
def test_record_integrity_is_rechecked_on_admission(store, change):
    p, _ = setup(store)
    capacity.record_external(store, approved(p))
    with store.pool.connection() as c:
        if change == "hash":
            c.execute(
                "UPDATE workspace_programme_capacity_amendments SET authorization_digest='wrong'"
            )
        elif change == "proposal":
            c.execute("UPDATE workspace_programme_capacity_amendments SET proposal_digest='wrong'")
        elif change == "expiry":
            c.execute(
                "UPDATE workspace_programme_capacity_amendments SET expires_at=expires_at+interval '1 second'"
            )
        elif change == "history":
            c.execute(
                "UPDATE workspace_spend_reservations SET amount=amount+0.01 WHERE job_id=%s",
                (p["amendment"]["basis"]["generation_job_ids"][0],),
            )
        with pytest.raises(AdmissionError):
            original.effective_limits(
                c,
                "evaluation",
                required_proposal_digest="wrong"
                if change == "unknown_required"
                else p["proposal_digest"],
            )


def test_reapproval_and_revocation_are_append_only(store):
    p, _ = setup(store)
    r = approved(p)
    first = capacity.record_external(store, r)
    different = deepcopy(r)
    different["approved_by"] = "Different synthetic reviewer"
    with pytest.raises(AdmissionError, match="immutable"):
        capacity.record_external(store, different)
    for actor in ("", None):
        with pytest.raises(AdmissionError):
            capacity.revoke(store, first["amendment_id"], actor=actor)
    with pytest.raises(AdmissionError):
        capacity.revoke(store, "missing", actor="Synthetic test")
    capacity.revoke(store, first["amendment_id"], actor="Synthetic test")
    capacity.revoke(store, first["amendment_id"], actor="Synthetic test")
    with store.pool.connection() as c:
        assert (
            c.execute("SELECT count(*) FROM workspace_programme_capacity_revocations").fetchone()[0]
            == 1
        )
        with pytest.raises(AdmissionError):
            original.effective_limits(
                c, "evaluation", required_proposal_digest=p["proposal_digest"]
            )
        assert (
            original.effective_limits(
                c,
                "evaluation",
                required_proposal_digest=p["amendment"]["predecessor_proposal_digest"],
            )["counts"]
            == 80
        )


def test_predecessor_revocation_still_blocks_new_capacity(store):
    p, _ = setup(store)
    capacity.record_external(store, approved(p))
    predecessor.revoke(
        store,
        p["amendment"]["amendment_id"].replace("-capacity-v4", "-funded-jobs-v3"),
        actor="Synthetic test",
    )
    with store.pool.connection() as c, pytest.raises(AdmissionError):
        original.effective_limits(c, "evaluation")


@pytest.mark.parametrize(
    "receipt",
    [
        {},
        {"approved": True, "amendment": []},
        {"approved": True, "amendment": {"program_id": None}},
    ],
)
def test_malformed_receipts_refuse_before_permission(store, receipt):
    with pytest.raises(AdmissionError):
        capacity.record_external(store, receipt)


def test_missing_or_tampered_predecessor_refuses(store):
    p, _ = setup(store)
    with store.pool.connection() as c:
        c.execute("UPDATE workspace_programme_third_amendments SET authorization_digest='wrong'")
    with pytest.raises(AdmissionError):
        capacity.record_external(store, approved(p))
    with store.pool.connection() as c, pytest.raises(AdmissionError):
        capacity.proposal(c, "missing")


def test_operator_template_record_and_revoke_are_separate(store, monkeypatch, tmp_path):
    import json
    import sys
    from contextlib import nullcontext

    from src.workspace import d5_benchmark

    p, _ = setup(store)
    monkeypatch.setenv("D5_POSTGRES_URL", "postgresql://localhost:15488/workspace_d5_tests")
    monkeypatch.setattr(d5_benchmark, "database", lambda _: nullcontext(store.pool))
    path = tmp_path / "receipt.json"

    def invoke(verb, pid="evaluation"):
        monkeypatch.setattr(
            sys, "argv", ["capacity", verb, "--program-id", pid, "--receipt", str(path)]
        )
        capacity.main()

    invoke("template")
    assert json.loads(path.read_text())["approved"] is False
    with pytest.raises(AdmissionError):
        invoke("record")
    path.write_text(json.dumps(approved(p)))
    invoke("record")
    invoke("revoke")
    with pytest.raises(AdmissionError):
        invoke("record", "another")


def test_historical_owner_third_receipt_is_readable_only_when_snapshot_attests_its_hash(store):
    _, _parents = setup(store)
    with store.pool.connection() as c:
        row = c.execute("SELECT record FROM workspace_programme_third_amendments").fetchone()[0]
        row.update(authorization_kind="owner", transport_mode="provider")
        digest = _digest(row)
        c.execute(
            "UPDATE workspace_programme_third_amendments SET record=%s,authorization_digest=%s",
            (Jsonb(row), digest),
        )
        with pytest.raises(AdmissionError):
            original.effective_limits(c, "evaluation")
        c.execute(
            "UPDATE workspace_d5_fixture_marker SET data=%s",
            (Jsonb({"historical_third_authorizations": [digest]}),),
        )
        assert original.effective_limits(c, "evaluation")["counts"] == 80
        assert capacity.proposal(c, "evaluation")["approved"] is False
        assert c.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0


@pytest.mark.parametrize("constraint", ["money", "messages", "concurrency", "unknown"])
def test_amendment_does_not_relax_other_admission_constraints(store, constraint):
    p, _ = setup(store)
    capacity.record_external(store, approved(p))
    support.seed_failed(store, 7, 1)
    with store.pool.connection() as c:
        jid = "synthetic-failed-programme-7"
        if constraint == "money":
            c.execute("UPDATE workspace_spend_reservations SET workflow=10 WHERE job_id=%s", (jid,))
        elif constraint == "messages":
            current = census(c, "a")["messages"]
            data = c.execute(
                "SELECT data FROM workspace_generation_jobs WHERE id=%s", (jid,)
            ).fetchone()[0]
            data["adapter"]["contacts"] = [
                {"endpoint": "messages", "state": "completed", "ordinal": i}
                for i in range(80 - current)
            ]
            c.execute(
                "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), jid)
            )
        elif constraint == "concurrency":
            c.execute("UPDATE workspace_generation_jobs SET state='running' WHERE id=%s", (jid,))
        else:
            c.execute(
                "UPDATE workspace_spend_reservations SET unknown=0.01 WHERE job_id=%s", (jid,)
            )
        expected = {
            "money": "cumulative_program_cost_cap_exceeded",
            "messages": "program_contact_cap_exceeded",
            "concurrency": "program_one_job_at_a_time",
            "unknown": "program_external_completion_uncertain",
        }[constraint]
        with pytest.raises(AdmissionError, match=expected):
            guard_program(
                c,
                "a",
                {
                    "purpose": "workspace-d5-qualification-only",
                    "program_id": "evaluation",
                    "program_authorization_digest": support.support.AUTH,
                },
                reserve_usd=Decimal("0.15"),
                current_job=None,
                next_endpoint="messages" if constraint == "messages" else None,
                reserve_operation="probe",
            )


def test_migration_from_v3_preserves_predecessors_and_does_not_activate(store):
    from src.workspace.store import WorkspaceStore

    _, parents = setup(store)
    with store.pool.connection() as c:
        # Simulate the actual pre-017 schema, removing later children first.
        # Keep real FK constraints and recreate the whole upgrade sequence.
        c.execute("DROP TABLE workspace_d5_campaign_successor_revocations")
        c.execute("DROP TABLE workspace_d5_campaign_successors")
        c.execute("DELETE FROM workspace_schema WHERE revision='019_d5_campaign_successor'")
        c.execute("DROP TABLE workspace_d5_campaign_outcomes")
        c.execute("DROP TABLE workspace_d5_campaign_revocations")
        c.execute("DROP TABLE workspace_d5_campaign_extensions")
        c.execute("DELETE FROM workspace_schema WHERE revision='018_d5_campaign_extension'")
        c.execute("DROP TABLE workspace_programme_capacity_revocations")
        c.execute("DROP TABLE workspace_programme_capacity_amendments")
        c.execute("DELETE FROM workspace_schema WHERE revision='017_programme_capacity_amendments'")
        assert original.effective_limits(c, "evaluation") == {**PROGRAM_LIMITS, "new_jobs": 24}
        with pytest.raises(AdmissionError):
            original.effective_limits(c, "evaluation", required_proposal_digest="not-activated")
    upgraded = WorkspaceStore(store.pool)
    upgraded.migrate()
    with store.pool.connection() as c:
        for table, rows in parents.items():
            assert c.execute("SELECT to_jsonb(t) FROM " + table + " t").fetchall() == rows
        assert (
            c.execute("SELECT count(*) FROM workspace_programme_capacity_amendments").fetchone()[0]
            == 0
        )
        assert original.effective_limits(c, "evaluation")["counts"] == 80
        assert c.execute("SELECT count(*) FROM workspace_d5_campaign_extensions").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM workspace_d5_campaign_successors").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM workspace_d5_campaign_successor_revocations").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["new_jobs", "counts", "concurrency", "version"])
def test_noncanonical_numeric_types_cannot_change_a_sealed_amendment(store, field):
    p, _ = setup(store)
    r = approved(p)
    if field == "version":
        r["amendment"]["version"] = 4.0
    else:
        value = r["amendment"]["amended_limits"][field]
        r["amendment"]["amended_limits"][field] = True if field == "concurrency" else float(value)
    r["proposal_digest"] = _digest(r["amendment"])
    with pytest.raises(AdmissionError, match="binding_or_limits_drift"):
        capacity.record_external(store, r)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case_id,abstains", [("v8-research-insufficient", True), ("v8-research-memory", False)]
)
async def test_capacity_fixture_honors_the_real_frozen_case_identity(case_id, abstains):
    import importlib.util
    import json
    from pathlib import Path

    import httpx

    from src.workspace.d5_benchmark import read

    root = Path(__file__).resolve().parents[1]
    helper = root / "planning/14-explore-and-research-modes/d5/tools/prepare-capacity-v8.py"
    spec = importlib.util.spec_from_file_location("capacity_fixture_regression", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # This preserved, unexecuted predecessor has the same frozen questions,
    # selected evidence and wire schemas. No old authorization/output is reused.
    packet = read(
        root
        / "planning/14-explore-and-research-modes/d5/evidence/qualification-v8r3/packet.json.gz"
    )
    case = next(c for c in packet["cases"] if c["id"] == case_id)
    request = httpx.Request(
        "POST",
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": "local-preview-disabled"},
        json=case["sealed"]["candidate_initial_wire"],
    )
    response = await module.CapacityTransport(case_id)(request)
    output = json.loads(response.json()["content"][0]["text"])
    assert bool(output["claims"]) is not abstains
    assert (output["abstention"] == "application_context_required") is abstains
