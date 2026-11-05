"""Owner-scoped $10 program, cumulative across models and isolated principals."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import httpx
import pytest
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.qualification_accounting import settle_failed_response
from src.workspace.qualification_budget import (
    PROGRAM_LIMITS,
    add_program_member,
    census,
    register_program,
    register_trial,
)
from tests import test_workspace_provider_adapter as support
from tests.test_workspace_qualification_accounting import restore_history

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration
AUTH = "a" * 64


def program(store):
    job, digest = restore_history(store)
    settle_failed_response(store, "a", job, receipt_id="historical", expected_contacts_digest=digest)
    with store.pool.connection() as conn:
        history = census(conn, "a")
    register_trial(store, "a", "historical-trial", history["history_digest"])
    return register_program(store, "a", "evaluation", "historical-trial", AUTH, history["history_digest"]), job


def adapter(store, owner="a", request_id="case1"):
    _, material, _ = support.support.source(store)
    inputs = support.p.prepare(store, owner, "summary", [material], question="What is supported by the selected source?")
    support.admission.policy(store, owner=owner, model_ids=[support.p.MODEL],
        request_digest=_digest(inputs.snapshot()), request_id=request_id,
        purpose="workspace-research-evaluation", transport_mode="mock",
        everyday_generation=False, program_id="evaluation", program_authorization_digest=AUTH,
        per_job_usd="0.25", day_usd="10", month_usd="10")
    return support.p.QualificationAdapter(store, owner, inputs, transport=httpx.MockTransport(lambda _: None))


def test_new_authorization_links_history_without_resetting_money_or_contacts(store):
    result, _ = program(store)
    assert result["limits"] == PROGRAM_LIMITS == {
        "new_jobs": 20, "messages": 80, "counts": 80, "usd": "10", "concurrency": 1}
    assert result["baseline"]["messages"] == 1 and result["baseline"]["counts"] == 5
    assert result["baseline"]["known_usd"] == "0.025329"
    assert Decimal(result["baseline"]["unknown_usd"]) == 0
    assert not result["approval_created"]
    a = adapter(store)
    job = a.start("case1", "0.25")
    assert job["state"] == "running"
    # New sealed question is visible; no owner profile/history is implicit.
    assert a.inputs.settings["research_task"] == "What is supported by the selected source?"


def test_second_principal_shares_capacity_and_one_at_a_time_guard(store):
    program(store)
    add_program_member(store, "evaluation", "b")
    adapter(store).start("case1", "0.25")
    with pytest.raises(AdmissionError, match="one_job_at_a_time"):
        adapter(store, owner="b", request_id="pilot1").start("pilot1", "0.25")


def test_budget_includes_historical_spend_even_if_prior_model_was_different(store):
    _, old = program(store)
    with store.pool.connection() as conn:
        data = conn.execute("SELECT data FROM workspace_generation_jobs WHERE id=%s", (old,)).fetchone()[0]
        data["usage_events"] = [{"day": "2026-10-01", "month": "2026-10-01", "workflow": "9.8", "judge": "0"}]
        conn.execute("UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), old))
        conn.execute("UPDATE workspace_spend_reservations SET workflow=9.8 WHERE job_id=%s", (old,))
    with pytest.raises(AdmissionError, match="cumulative_program_cost_cap"):
        adapter(store).start("case1", "0.25")


@pytest.mark.parametrize("endpoint", ["messages", "messages/count_tokens"])
def test_new_80_contact_limits_reserve_check_recheck_and_count_failed_attempts(store, endpoint):
    _, old = program(store)
    with store.pool.connection() as conn:
        data = conn.execute("SELECT data FROM workspace_generation_jobs WHERE id=%s", (old,)).fetchone()[0]
        # The immutable baseline remains1/5; total77 attempts leave only3
        # available contacts, irrespective of model, failure or request ID.
        prior = 1 if endpoint == "messages" else 5
        data["adapter"]["contacts"] += [{"endpoint": endpoint, "state": "completed", "ordinal": 100+i} for i in range(77-prior)]
        conn.execute("UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), old))
    with pytest.raises(AdmissionError, match="check_recheck_capacity"):
        adapter(store).start("case1", "0.25")


def test_twenty_new_jobs_limit_includes_failed_generation_reservations(store):
    _, old = program(store)
    with store.pool.connection() as conn:
        data = conn.execute("SELECT data FROM workspace_generation_jobs WHERE id=%s", (old,)).fetchone()[0]
        data["adapter"]["contacts"] = []
        data["usage_events"] = []
        data["receipts"] = {}
        for i in range(20):
            jid = "failed-new-" + str(i)
            conn.execute("INSERT INTO workspace_generation_jobs VALUES (%s,'a','synthetic','failed',%s,%s)", (jid, _digest(data["sealed_input"]), Jsonb(data)))
            conn.execute("INSERT INTO workspace_spend_reservations VALUES (%s,'a',0.25,'2026-11-04','2026-11-01',0,0,0,'failed')", (jid,))
    with pytest.raises(AdmissionError, match="program_job_cap"):
        adapter(store).start("case1", "0.25")


def test_new_ids_cannot_change_limits_authorization_or_detach_previous_program(store):
    result, _ = program(store)
    with store.pool.connection() as conn:
        history = census(conn, "a")
    with pytest.raises(AdmissionError, match="immutable"):
        register_program(store, "a", "evaluation", "historical-trial", "b" * 64, history["history_digest"])
    with pytest.raises(AdmissionError, match="already_bound"):
        register_program(store, "a", "replacement-id", "historical-trial", AUTH, history["history_digest"])
    assert result["limits"]["usd"] == "10"


def test_foreign_principal_or_wrong_authorization_refuses_before_transport(store):
    program(store)
    a = adapter(store)
    with store.pool.connection() as conn:
        data = conn.execute("SELECT data FROM workspace_budget_policies WHERE owner='a'").fetchone()[0]
        data["program_authorization_digest"] = "wrong"
        conn.execute("UPDATE workspace_budget_policies SET data=%s WHERE owner='a'", (Jsonb(data),))
    with pytest.raises(AdmissionError, match="cumulative_evaluation_program"):
        a.start("case1", "0.25")


@pytest.mark.parametrize("generic", [False, True])
def test_program_member_cannot_fall_back_to_legacy_trial_or_generic_approval(store, generic):
    program(store)
    add_program_member(store, "evaluation", "b")
    instance = adapter(store, owner="b", request_id="bound")
    support.admission.policy(store, owner="b", model_ids=[support.p.MODEL],
        purpose="workspace-qualification", transport_mode="mock", everyday_generation=False,
        request_id="legacy", request_digest=_digest(instance.inputs.snapshot()))
    with pytest.raises(AdmissionError, match="program_bound_principal"):
        if generic:
            support.p.GenerationAdmission(store).reserve("b", "legacy", instance.inputs, "0.25")
        else:
            instance.start("legacy", "0.25")


def test_two_principals_racing_admission_start_exactly_one_job(store):
    program(store)
    add_program_member(store, "evaluation", "b")
    instances = [adapter(store, owner="a", request_id="race-a"),
                 adapter(store, owner="b", request_id="race-b")]
    barrier = Barrier(2)

    def start(index):
        barrier.wait(timeout=5)
        try:
            return instances[index].start("race-a" if index == 0 else "race-b", "0.25")["state"]
        except AdmissionError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(start, range(2)))
    assert outcomes.count("running") == 1
    assert outcomes.count("program_one_job_at_a_time") == 1
    with store.pool.connection() as conn:
        report = census(conn, "a", members=["a", "b"])
    assert len(report["active_jobs"]) == 1
