"""Synthetic amendment approvals and MockTransport in disposable Postgres only."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from psycopg.types.json import Jsonb

from src.workspace import programme_amendments as am
from src.workspace.admission import AdmissionError, GenerationAdmission, _digest
from src.workspace.qualification_budget import PROGRAM_LIMITS, census
from tests import test_workspace_evaluation_program as support
from tests.test_workspace_provider_adapter import Transport

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


def seed_failed(store, first, count):
    with store.pool.connection() as conn:
        data = deepcopy(
            conn.execute(
                "SELECT data FROM workspace_generation_jobs ORDER BY id LIMIT 1"
            ).fetchone()[0]
        )
        data.update(usage_events=[], receipts={}, result=None)
        data["adapter"] = {
            "mode": "mock",
            "contacts": [],
            "steps": [],
            "workflow_usd": "0",
            "checker_usd": "0",
        }
        for i in range(first, first + count):
            jid = "synthetic-failed-programme-" + str(i)
            conn.execute(
                "INSERT INTO workspace_generation_jobs VALUES(%s,'a','synthetic','failed',%s,%s)",
                (jid, _digest(data["sealed_input"]), Jsonb(data)),
            )
            conn.execute(
                "INSERT INTO workspace_spend_reservations VALUES(%s,'a',0.01,'2026-11-07','2026-11-01',0,0,0,'failed')",
                (jid,),
            )


def setup(store):
    support.program(store)
    with store.pool.connection() as conn:
        conn.execute("INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only','{}')")
    seed_failed(store, 0, 7)
    with store.pool.connection() as conn:
        return am.proposal(conn, "evaluation")


def approved(template):
    receipt = deepcopy(template)
    now = datetime.now(UTC)
    receipt.update(
        approved=True,
        approved_by="Synthetic operator fixture, not owner approval",
        approved_at=now.isoformat(),
        expires_at=(now + timedelta(days=1)).isoformat(),
        authorization_kind="offline_fixture",
        transport_mode="mock",
        authorization_reference="Explicit synthetic test authorization, confined to marked disposable storage",
    )
    return receipt


async def execute(store, name):
    adapter = support.adapter(store, request_id=name)
    transport = Transport(store, adapter.inputs)
    adapter.transport = httpx.MockTransport(transport)
    job = adapter.start(name, "0.25")
    await adapter.advance(job["id"])
    result = await adapter.advance(job["id"])
    assert result["state"] == "ready" and len(transport.calls) == 4
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("amended", [False, True])
async def test_original_admits_job20_stops21_and_explicit_amendment_admits21_stops22(
    store, amended
):
    template = setup(store)
    assert len(template["amendment"]["basis"]["generation_job_ids"]) - 1 == 7
    if amended:
        am.record_external(store, approved(template))
    seed_failed(store, 7, 12)  # 19 consumed programme jobs, parent separate.
    await execute(store, "job20")
    with store.pool.connection() as conn:
        assert (
            conn.execute("SELECT limits FROM workspace_evaluation_programs").fetchone()[0]
            == PROGRAM_LIMITS
        )
        assert am.effective_limits(conn, "evaluation")["new_jobs"] == (21 if amended else 20)
    if amended:
        await execute(store, "job21")
    denied = support.adapter(store, request_id="job22" if amended else "job21")
    with pytest.raises(AdmissionError, match="program_job_cap_exceeded"):
        denied.start("job22" if amended else "job21", "0.25")
    with store.pool.connection() as conn:
        history = census(conn, "a")
        assert len(history["generation_job_ids"]) - 1 == (21 if amended else 20)
        assert not history["active_jobs"] and history["unknown_usd"] == "0"


def test_amendment_only_changes_this_programme_job_cap_and_is_not_workflow_permission(store):
    template = setup(store)
    before = deepcopy(template["amendment"]["basis"])
    am.record_external(store, approved(template))
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_evaluation_programs SELECT 'other',parent_trial_id,limits,baseline,authorization_digest,created_at FROM workspace_evaluation_programs WHERE program_id='evaluation'"
        )
        assert am.effective_limits(conn, "other") == PROGRAM_LIMITS
        assert am.effective_limits(conn, "evaluation") == {**PROGRAM_LIMITS, "new_jobs": 21}
        assert census(conn, "a") == before
        assert conn.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0
    instance = support.adapter(store)
    with pytest.raises(AdmissionError):
        GenerationAdmission(store).reserve(
            "unapproved", "no-job-permission", instance.inputs, "0.25"
        )


@pytest.mark.parametrize(
    "change",
    [
        "unapproved",
        "wrong_programme",
        "wrong_authorization",
        "baseline",
        "parent",
        "revision",
        "old_limits",
        "22jobs",
        "money",
        "contacts",
        "concurrency",
        "actor",
        "reference",
        "expired",
        "naive",
        "future",
        "overlong",
        "fixture_kind",
        "transport",
        "proposal_digest",
    ],
)
def test_malformed_drifting_or_unapproved_amendments_cannot_activate(store, change):
    r = approved(setup(store))
    core = r["amendment"]
    if change == "unapproved":
        r["approved"] = False
    elif change == "wrong_programme":
        core["program_id"] = "other"
    elif change == "wrong_authorization":
        core["original_authorization_digest"] = "b" * 64
    elif change == "baseline":
        core["original_baseline_digest"] = "b" * 64
    elif change == "parent":
        core["parent_trial_id"] = "other"
    elif change == "revision":
        core["version"] = 2
    elif change == "old_limits":
        core["original_limits"]["new_jobs"] = 19
    elif change == "22jobs":
        core["amended_limits"]["new_jobs"] = 22
    elif change == "money":
        core["amended_limits"]["usd"] = "11"
    elif change == "contacts":
        core["amended_limits"]["counts"] = 81
    elif change == "concurrency":
        core["amended_limits"]["concurrency"] = 2
    elif change == "actor":
        r["approved_by"] = ""
    elif change == "reference":
        r["authorization_reference"] = ""
    elif change == "expired":
        r["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    elif change == "naive":
        r["approved_at"] = "2026-11-07T00:00:00"
    elif change == "future":
        r["approved_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    elif change == "overlong":
        r["expires_at"] = (datetime.now(UTC) + timedelta(days=8)).isoformat()
    elif change == "fixture_kind":
        r["authorization_kind"] = "owner"
    elif change == "transport":
        r["transport_mode"] = "provider"
    else:
        r["proposal_digest"] = "b" * 64
    if change != "proposal_digest":
        r["proposal_digest"] = _digest(core)
    with pytest.raises(AdmissionError):
        am.record_external(store, r)
    with store.pool.connection() as conn:
        assert (
            conn.execute("SELECT count(*) FROM workspace_programme_amendments").fetchone()[0] == 0
        )


@pytest.mark.parametrize("change", ["census", "members", "pending", "unknown"])
def test_activation_requires_exact_current_census_and_no_liabilities(store, change):
    template = setup(store)
    with store.pool.connection() as conn:
        if change == "members":
            conn.execute("INSERT INTO workspace_evaluation_members VALUES('other','evaluation')")
        elif change == "census":
            conn.execute(
                "UPDATE workspace_generation_jobs SET state='cancelled' WHERE id='synthetic-failed-programme-0'"
            )
        elif change == "pending":
            conn.execute(
                "UPDATE workspace_generation_jobs SET state='running' WHERE id='synthetic-failed-programme-0'"
            )
        else:
            conn.execute(
                "UPDATE workspace_spend_reservations SET unknown=0.01 WHERE job_id='synthetic-failed-programme-0'"
            )
        if change in {"pending", "unknown"}:
            template = am.proposal(conn, "evaluation")
    with pytest.raises(AdmissionError, match="census_drift|unresolved"):
        am.record_external(store, approved(template))


def test_idempotence_immutable_receipt_revocation_and_required_binding(store):
    r = approved(setup(store))
    first = am.record_external(store, r)
    assert am.record_external(store, r)["duplicate"]
    other = deepcopy(r)
    other["approved_by"] = "New synthetic actor"
    with pytest.raises(AdmissionError, match="immutable"):
        am.record_external(store, other)
    with (
        store.pool.connection() as conn,
        pytest.raises(AdmissionError, match="binding_or_revocation"),
    ):
        am.effective_limits(conn, "evaluation", required_proposal_digest="b" * 64)
    am.revoke(store, first["amendment_id"], actor="Synthetic operator")
    am.revoke(store, first["amendment_id"], actor="Synthetic operator")
    with store.pool.connection() as conn, pytest.raises(AdmissionError, match="revocation"):
        am.effective_limits(conn, "evaluation")
    with pytest.raises(AdmissionError):
        am.revoke(store, first["amendment_id"], actor="")
    with pytest.raises(AdmissionError):
        am.revoke(store, "missing", actor="Synthetic")


def test_required_amendment_absence_and_historical_receipt_tampering_refuse(store):
    r = approved(setup(store))
    with store.pool.connection() as conn, pytest.raises(AdmissionError, match="not_active"):
        am.effective_limits(conn, "evaluation", required_proposal_digest=r["proposal_digest"])
    am.record_external(store, r)
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_generation_jobs SET state='cancelled' WHERE id='synthetic-failed-programme-0'"
        )
    with (
        store.pool.connection() as conn,
        pytest.raises(AdmissionError, match="historical_receipts_changed"),
    ):
        am.effective_limits(conn, "evaluation")


def test_invalid_programme_and_receipt_shape_refuse(store):
    store.migrate()
    with store.pool.connection() as conn, pytest.raises(AdmissionError):
        am.proposal(conn, "missing")
    for receipt in [{}, {"approved": True, "amendment": None}, {"approved": True, "amendment": {}}]:
        with pytest.raises(AdmissionError):
            am.record_external(store, receipt)


@pytest.mark.parametrize("field", ["record", "digest", "expiry"])
def test_stored_amendment_corruption_refuses(store, field):
    r = approved(setup(store))
    am.record_external(store, r)
    with store.pool.connection() as conn:
        if field == "record":
            conn.execute(
                "UPDATE workspace_programme_amendments SET record=jsonb_set(record,'{approved_by}','\"tampered\"')"
            )
        elif field == "digest":
            conn.execute("UPDATE workspace_programme_amendments SET proposal_digest='wrong'")
        else:
            conn.execute(
                "UPDATE workspace_programme_amendments SET expires_at=expires_at+interval '1 second'"
            )
    with store.pool.connection() as conn, pytest.raises(AdmissionError):
        am.effective_limits(conn, "evaluation")


def test_expired_amendment_and_proposal_copy_cannot_renew_or_mutate_global_policy(
    store, monkeypatch
):
    template = setup(store)
    copy = deepcopy(template)
    copy["amendment"]["original_limits"]["new_jobs"] = 99
    assert PROGRAM_LIMITS["new_jobs"] == 20
    r = approved(template)
    am.record_external(store, r)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(r["expires_at"]) + timedelta(seconds=1)

    monkeypatch.setattr(am, "datetime", Later)
    with (
        store.pool.connection() as conn,
        pytest.raises(AdmissionError, match="authorization_required"),
    ):
        am.effective_limits(conn, "evaluation")


def test_operator_cli_exports_false_template_records_only_explicit_fixture_and_revokes(
    store, monkeypatch, tmp_path, capsys
):
    from contextlib import nullcontext

    from src.workspace import d5_benchmark as cli

    setup(store)
    monkeypatch.setenv("D5_POSTGRES_URL", "postgresql://localhost:15488/workspace_d5_tests")
    monkeypatch.setattr(cli, "database", lambda _: nullcontext(store.pool))
    path = tmp_path / "amendment.json"

    def invoke(verb, programme="evaluation"):
        monkeypatch.setattr(
            "sys.argv", ["amend", verb, "--program-id", programme, "--receipt", str(path)]
        )
        am.main()

    invoke("template")
    template = cli.read(path)
    assert template["approved"] is False
    with pytest.raises(AdmissionError):
        invoke("record")
    import json

    path.write_text(json.dumps(approved(template)))
    invoke("record")
    assert '"effective_jobs": 21' in capsys.readouterr().out
    for verb in ["record", "revoke"]:
        with pytest.raises(AdmissionError):
            invoke(verb, programme="other")
    invoke("revoke")
    with store.pool.connection() as conn, pytest.raises(AdmissionError):
        am.effective_limits(conn, "evaluation")
