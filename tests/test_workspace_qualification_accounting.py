"""Historical metered failure and cumulative continuation; isolated SQL only."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.qualification_accounting import settle_failed_response
from src.workspace.qualification_budget import LIMITS, census, register_trial
from tests import test_workspace_provider_adapter as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parent / "fixtures" / "qualification_failures"


def restore_history(store):
    original = json.loads((FIXTURES / "original-stop-journal.json").read_text())
    reserves = {r["job_id"]: r for r in original["reservations"]}
    with store.pool.connection() as conn:
        for job in original["jobs"]:
            data = job["data"]
            conn.execute("INSERT INTO workspace_generation_jobs VALUES (%s,'a','historical-approval',%s,%s,%s)",
                (job["id"], job["state"], _digest(data["sealed_input"]), Jsonb(data)))
            reserve = reserves[job["id"]]
            conn.execute("INSERT INTO workspace_spend_reservations VALUES (%s,'a',%s,'2026-11-04','2026-11-01',%s,%s,%s,%s)",
                (job["id"], reserve["reserved"], reserve["workflow"], reserve["checker"],
                 reserve["unknown"], reserve["state"]))
    old = next(j for j in original["jobs"] if j["state"] == "uncertain")
    return old["id"], _digest(old["data"]["adapter"]["contacts"])


def register(store):
    with store.pool.connection() as conn:
        history = census(conn, "a")
    return register_trial(store, "a", "original-trial", history["history_digest"])


def funded(store, request_id="next", **changes):
    inputs = support.prepared(store)
    support.approve(store, inputs, request_id=request_id, trial_id="original-trial", **changes)
    return support.p.QualificationAdapter(store, "a", inputs, transport=httpx.MockTransport(lambda _: None))


def test_real_completed_usage_releases_only_unknown_hold_never_accepts_content(store):
    job, digest = restore_history(store)
    with store.pool.connection() as conn:
        before = census(conn, "a")
    assert (before["counts"], before["messages"], before["known_usd"], before["unknown_usd"]) == (5, 1, "0.025329", "0.224671")
    audit = settle_failed_response(store, "a", job, receipt_id="historical-completion", expected_contacts_digest=digest)
    assert audit["state"] == "failed" and audit["content_accepted"] is False
    assert audit["historical_rates"]["input"] == "3" and audit["historical_rates"]["output"] == "15"
    assert audit["workflow_usd"] == "0.025329" and audit["checker_usd"] == audit["unknown_usd"] == "0"
    assert audit["released_unused_usd"] == "0.224671"
    assert settle_failed_response(store, "a", job, receipt_id="historical-completion", expected_contacts_digest=digest) == audit
    with store.pool.connection() as conn:
        state, data = conn.execute("SELECT state,data FROM workspace_generation_jobs WHERE id=%s", (job,)).fetchone()
        report = census(conn, "a")
    assert state == "failed" and data["result"] is None
    assert report["counts"] == 5 and report["messages"] == 1
    assert report["known_usd"] == "0.025329" and Decimal(report["pending_usd"]) == 0
    assert data["adapter"]["contacts"] == next(j["data"]["adapter"]["contacts"] for j in json.loads((FIXTURES / "original-stop-journal.json").read_text())["jobs"] if j["id"] == job)
    # Generic settlement cannot promote failed content to a ready/cache entry.
    support.p.GenerationAdmission(store).reconcile("a", job, receipt_id="no-promotion", workflow_usd="0.025329", judge_usd="0", final=True, result={"invalid": "must not publish"})
    with store.pool.connection() as conn:
        assert conn.execute("SELECT state,data->'result' FROM workspace_generation_jobs WHERE id=%s", (job,)).fetchone() == ("failed", None)


@pytest.mark.parametrize("change", ["dispatching", "missing_response", "usage", "receipt_id", "journal_digest", "cache"])
def test_incomplete_or_unpriced_receipt_cannot_release_hold(store, change):
    job, digest = restore_history(store)
    if change != "journal_digest":
        with store.pool.connection() as conn:
            data = conn.execute("SELECT data FROM workspace_generation_jobs WHERE id=%s", (job,)).fetchone()[0]
            contact = data["adapter"]["contacts"][-1]
            if change == "dispatching":
                contact["state"] = "dispatching"
            elif change == "missing_response":
                contact.pop("response")
            elif change == "usage":
                contact["response"]["usage"]["input_tokens"] = True
            elif change == "cache":
                contact["response"]["usage"]["cache_read_input_tokens"] = 1
            else:
                contact["response"].pop("id")
            conn.execute("UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job))
            digest = _digest(data["adapter"]["contacts"])
    else:
        digest = "wrong"
    with pytest.raises(AdmissionError):
        settle_failed_response(store, "a", job, receipt_id="must-refuse", expected_contacts_digest=digest)
    assert support.admission.row(store, job)[4] == Decimal("0.224671")


def test_continuation_carries_original_counts_money_and_enforces_single_job(store):
    job, digest = restore_history(store)
    settle_failed_response(store, "a", job, receipt_id="close", expected_contacts_digest=digest)
    enrollment = register(store)
    assert enrollment["limits"] == LIMITS and not enrollment["approval_created"]
    assert LIMITS["counts"] - enrollment["baseline"]["counts"] == 15
    assert LIMITS["messages"] - enrollment["baseline"]["messages"] == 15
    first = funded(store)
    first.start("next", "0.25")
    second = funded(store, request_id="different-id")
    with pytest.raises(AdmissionError, match="one_job_at_a_time"):
        second.start("different-id", "0.25")
    # Changing model or job IDs cannot replace/reset the immutable ledger.
    with store.pool.connection() as conn:
        history = census(conn, "a")
    with pytest.raises(AdmissionError, match="immutable"):
        register_trial(store, "a", "fresh-id", history["history_digest"])


def test_unknown_completion_blocks_new_jobs_until_audited_reconciliation(store):
    restore_history(store)
    register(store)
    with pytest.raises(AdmissionError, match="completion_uncertain"):
        funded(store).start("next", "0.25")


@pytest.mark.parametrize("endpoint", ["messages", "messages/count_tokens"])
def test_mandatory_check_and_recheck_capacity_reserved_before_any_call(store, endpoint):
    job, digest = restore_history(store)
    settle_failed_response(store, "a", job, receipt_id="close", expected_contacts_digest=digest)
    # Conservatively journal prior attempts on another model/request ID; totals
    # leave only three slots of this endpoint, insufficient for a bounded job.
    with store.pool.connection() as conn:
        data = conn.execute("SELECT data FROM workspace_generation_jobs WHERE id=%s", (job,)).fetchone()[0]
        used = 1 if endpoint == "messages" else 5
        target = LIMITS["messages" if endpoint == "messages" else "counts"] - 3
        for i in range(target - used):
            data["adapter"]["contacts"].append({"endpoint": endpoint, "state": "completed", "ordinal": 100+i})
        conn.execute("UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job))
    register(store)
    with pytest.raises(AdmissionError, match="check_recheck_capacity"):
        funded(store).start("next", "0.25")


def test_trial_cost_cannot_reset_on_another_day_or_request_id(store):
    job, digest = restore_history(store)
    settle_failed_response(store, "a", job, receipt_id="close", expected_contacts_digest=digest)
    # Known cumulative spend in an older period still consumes trial capacity.
    with store.pool.connection() as conn:
        data = conn.execute("SELECT data FROM workspace_generation_jobs WHERE id=%s", (job,)).fetchone()[0]
        data["usage_events"] = [{"day": "2026-10-01", "month": "2026-10-01", "workflow": "1.10", "judge": "0"}]
        conn.execute("UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job))
        conn.execute("UPDATE workspace_spend_reservations SET workflow=1.10 WHERE job_id=%s", (job,))
    register(store)
    with pytest.raises(AdmissionError, match="cumulative_trial_cost_cap"):
        funded(store).start("next", "0.25", now=datetime(2026, 11, 5, tzinfo=UTC))
