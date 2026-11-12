"""Blocked proposal on synthetic unresolved accounting; never clear a live hold."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace

import pytest
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_benchmark import read, write
from src.workspace.d5_coverage_replay import fixture_A
from src.workspace.d5_deadlines import POLICY
from src.workspace.d5_freeze import compile_inputs, verify
from src.workspace.d5_measurements import verify_reuse
from src.workspace.d5_timeout_packet import CASE_ID, capture, freeze, main, verify_timeout
from tests import test_workspace_coverage_authority_runner as prior
from tests import test_workspace_d5_measurement_reuse as measurement
from tests.test_workspace_programme_amendments import seed_failed

store = prior.store
if hasattr(prior, "workspace_pg"):
    workspace_pg_proc, workspace_pg = prior.workspace_pg_proc, prior.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def setup(store):
    prior.setup(store)
    seed_failed(store, 32, 1)
    with store.pool.connection() as c:
        data = c.execute("SELECT data FROM workspace_generation_jobs WHERE id='synthetic-failed-programme-32'").fetchone()[0]
        data["adapter"].update(workflow_usd="0.024934", contacts=[{"endpoint": e, "state": "dispatching" if i == 1 else "completed", "ordinal": i} for i, e in enumerate(["messages", "messages", "messages/count_tokens", "messages/count_tokens", "messages/count_tokens"])])
        c.execute("UPDATE workspace_generation_jobs SET state='uncertain',data=%s WHERE id='synthetic-failed-programme-32'", (Jsonb(data),))
        c.execute("UPDATE workspace_spend_reservations SET state='uncertain',amount=0.45,workflow=0.024934,unknown=0.425066 WHERE job_id='synthetic-failed-programme-32'")
    return capture(store, "evaluation")


async def test_current_unknown_hold_is_preserved_and_external_authorization_refuses(store):
    snapshot = setup(store)
    packet = freeze(snapshot)
    verify(packet)
    assert packet["reconciliation_required"] is True and packet["approved"] is False
    assert packet["operation_deadlines"] == POLICY
    assert packet["planned_development_cases"] == [CASE_ID]
    assert packet["history"]["unknown_usd"] == "0.425066"
    assert packet["history"]["pending_usd"] == "0.425066"
    inputs = compile_inputs(packet)
    assert all(e["input"]["settings"]["operation_deadlines"] == POLICY for e in inputs.values())
    with pytest.raises(AdmissionError, match="historical_liability_requires_reconciliation"):
        fixture_A(store, packet)
    assert _digest(capture(store, "evaluation")) == _digest(snapshot)
    with store.pool.connection() as c:
        assert not c.execute("SELECT 1 FROM workspace_d5_scopes WHERE scope_id=%s", ("d5-" + packet["packet_digest"][:24],)).fetchone()


@pytest.mark.parametrize("mutation", ["deadline", "unblock", "case", "reuse", "schema", "limits", "checker_schema", "programme_limits", "programme_binding", "programme_id"])
async def test_frozen_proposal_drift_refused(store, mutation):
    packet = freeze(setup(store))
    if mutation == "deadline":
        packet["operation_deadlines"]["check_seconds"] = 121
    elif mutation == "unblock":
        packet["reconciliation_required"] = False
    elif mutation == "case":
        packet["planned_development_cases"] = ["stopped-v10"]
    elif mutation == "reuse":
        packet["measurement_reuse"] = {"measure-1": {}}
    elif mutation == "schema":
        packet["cases"][0]["sealed"]["response_schemas"]["wire"] = {}
    elif mutation == "limits":
        packet["limits"]["jobs"] = 2
    elif mutation == "checker_schema":
        packet["checker_schemas"]["wire"] = {}
    elif mutation == "programme_limits":
        packet["programme"]["limits"]["jobs"] = 35
    elif mutation == "programme_binding":
        packet["programme"]["capacity_proposal_digest"] = "wrong"
    else:
        packet["programme"]["program_id"] = "other"
    with pytest.raises(AdmissionError, match="proposal_binding_drift"):
        verify_timeout(packet)


async def test_programme_expiry_requires_timezone(store):
    packet = freeze(setup(store))
    packet["programme"]["expires_at"] = "2026-11-14T07:24:01"
    with pytest.raises(AdmissionError, match="programme_expiry_required"):
        verify_timeout(packet)


@pytest.mark.parametrize("mutation", ["history", "private"])
async def test_capture_requires_exact_public_uncertain_baseline(store, mutation):
    setup(store)
    with store.pool.connection() as c:
        if mutation == "history":
            c.execute("UPDATE workspace_spend_reservations SET unknown=0 WHERE job_id='synthetic-failed-programme-32'")
        else:
            c.execute("UPDATE workspace_works SET visibility_owner='synthetic-private' WHERE work_id=(SELECT work_id FROM workspace_works LIMIT 1)")
    with pytest.raises(AdmissionError, match="baseline_required|public_sources_only"):
        capture(store, "evaluation")


async def test_operator_preparation_refuses_before_context_write(store, monkeypatch, tmp_path):
    from src.workspace import d5_operator

    snapshot = setup(store)
    packet = freeze(snapshot)
    path = tmp_path / "packet.json.gz"
    write(path, packet)
    monkeypatch.setenv("D5_POSTGRES_URL", "disposable-only")
    monkeypatch.setattr(d5_operator, "database", lambda _: nullcontext(store.pool))
    monkeypatch.setattr("sys.argv", ["operator", "prepare", "--packet", str(path), "--receipt", str(tmp_path / "no-receipt.json")])
    with pytest.raises(AdmissionError, match="unresolved_liability_requires_reconciliation"):
        d5_operator.main()
    assert not (tmp_path / "no-receipt.json").exists()
    assert _digest(capture(store, "evaluation")) == _digest(snapshot)


async def test_count_exact_binding_remains_auditable_with_nonwire_deadlines(store):
    link, successor, transport = await measurement.measured(store)
    settings = {**successor.settings, "operation_deadlines": deepcopy(POLICY)}
    timed = replace(successor, settings=settings)
    proof = verify_reuse(store, link, "new-owner", timed, offline=True)
    assert proof["reused"] and proof["new_contacts"] == 0
    assert len(transport.calls) == 1
    assert timed.settings["timeout_seconds"] == 30
    changed = replace(timed, settings={**timed.settings, "output_tokens": 3999})
    with pytest.raises(AdmissionError):
        verify_reuse(store, link, "new-owner", changed, offline=True)


async def test_cli_freeze_and_capture_offline_guard(store, monkeypatch, tmp_path):
    from src.workspace import d5_timeout_packet as m

    snapshot = setup(store)
    source, target = tmp_path / "snapshot.json.gz", tmp_path / "packet.json.gz"
    write(source, snapshot)
    monkeypatch.setattr("sys.argv", ["deadlines", "--snapshot", str(source), "--packet", str(target)])
    main()
    assert read(target)["reconciliation_required"] is True
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-real-key")
    with pytest.raises(AdmissionError, match="offline_only"):
        main()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setattr("sys.argv", ["deadlines", "--snapshot", str(source)])
    with pytest.raises(SystemExit):
        main()
    monkeypatch.setenv("D5_LEDGER_POSTGRES_URL", "disposable-only")
    monkeypatch.setattr("src.workspace.d5_benchmark.database", lambda _: nullcontext(store.pool))
    original_capture = m.capture
    monkeypatch.setattr(m, "capture", lambda store, _: original_capture(store, "evaluation"))
    monkeypatch.setattr("sys.argv", ["deadlines", "--capture", "--snapshot", str(tmp_path / "captured.json.gz")])
    main()
    assert read(tmp_path / "captured.json.gz")["history"]["unknown_usd"] == "0.425066"
