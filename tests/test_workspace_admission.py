"""Real Postgres generation admission; synthetic approvals and fake providers only.

These approvals exist only in per-test disposable schemas. No policy is written
in the real workspace and no model client or paid request is constructed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from psycopg.types.json import Jsonb

from src.workspace import admission as a
from src.workspace.store import ConflictError
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 2, 16, tzinfo=UTC)


def policy(store, owner="a", **changes):
    data = {
        "approved": True,
        "model_ids": ["synthetic-model"],
        "per_job_usd": "1",
        "day_usd": "2",
        "month_usd": "3",
        "source_scopes": ["abstract"],
        "valid_from": "2026-11-01T00:00:00+00:00",
        "expires_at": "2026-12-02T00:00:00+00:00",
        "approval_record": {
            "approval_id": "synthetic-only",
            "approved_by": "synthetic-test-owner",
            "approved_at": "2026-11-01T00:00:00+00:00",
        },
        **changes,
    }
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_budget_policies VALUES (%s,'synthetic-only',%s) ON CONFLICT(owner) DO UPDATE SET data=EXCLUDED.data",
            (owner, Jsonb(data)),
        )
    return data


def inputs(store, version=1):
    item = support.ingest(store, version)
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT material_id,content_hash,source_scope FROM workspace_material WHERE version_id=%s",
            (item["version_id"],),
        ).fetchone()
    return a.GenerationInput(
        "summary",
        "synthetic-model",
        "synthetic-prompt-v1",
        (a.SourceRef(item["work_id"], item["version_id"], row[0], row[1], row[2]),),
        {"temperature": 0, "max_tokens": 200},
    )


def begin(store, request_id="one", amount="1", owner="a", value=None, now=NOW):
    control = a.GenerationAdmission(store)
    value = value or inputs(store)
    job = control.reserve(owner, request_id, value, amount, now=now)
    control.construct_provider(owner, job["id"], value, lambda sealed: sealed, mode="fake", now=now)
    return control, value, job


def row(store, job_id):
    with store.pool.connection() as conn:
        return conn.execute(
            "SELECT j.state,r.amount,r.workflow,r.judge,r.unknown,r.state,j.data FROM workspace_generation_jobs j JOIN workspace_spend_reservations r ON r.job_id=j.id WHERE j.id=%s",
            (job_id,),
        ).fetchone()


def test_unapproved_and_sentinel_refuse_before_provider_construction(store, monkeypatch):
    control, factory, value = a.GenerationAdmission(store), Mock(), inputs(store)
    with pytest.raises(a.AdmissionError, match="owner_approval_required"):
        control.reserve("a", "one", value, "1", now=NOW)
    policy(store)
    job = control.reserve("a", "one", value, "1", now=NOW)
    for kwargs in (
        {},
        {"mode": "live"},
        {"mode": "fake", "api_key": "not-the-sentinel"},
        {"mode": "unknown"},
    ):
        with pytest.raises(a.AdmissionError, match="provider_disabled"):
            control.construct_provider("a", job["id"], value, factory, now=NOW, **kwargs)
    monkeypatch.setenv("ANTHROPIC_API_KEY", a.DISABLED_KEY)
    with pytest.raises(a.AdmissionError, match="provider_disabled"):
        control.construct_provider(
            "a",
            job["id"],
            value,
            factory,
            mode="live",
            api_key="still-disabled-by-environment",
            now=NOW,
        )
    factory.assert_not_called()
    assert row(store, job["id"])[0] == "reserved"
    assert control.cancel("a", job["id"])["unknown_usd"] == "0"


def test_atomic_racing_day_admission_and_owner_isolation(store):
    policy(store, day_usd="1", month_usd="2")
    policy(store, owner="b", day_usd="1", month_usd="2")
    value, control = inputs(store), a.GenerationAdmission(store)

    def reserve(number):
        try:
            return control.reserve("a", str(number), value, "0.75", now=NOW)["state"]
        except a.AdmissionError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(reserve, [1, 2])) == ["day_cap_exceeded", "reserved"]
    other = control.reserve("b", "1", value, "0.75", now=NOW)
    assert other["state"] == "reserved"
    with pytest.raises(a.AdmissionError, match="job_not_found"):
        control.cancel("a", other["id"])


def test_sealed_settings_policy_and_source_scope_rechecked(store):
    policy(store)
    value, control, factory = inputs(store), a.GenerationAdmission(store), Mock()
    job = control.reserve("a", "one", value, "1", now=NOW)
    drift = replace(value, settings={"temperature": 1})
    with pytest.raises(a.AdmissionError, match="sealed_execution_drift"):
        control.construct_provider("a", job["id"], drift, factory, mode="fake", now=NOW)
    policy(store, day_usd="2.5")
    with pytest.raises(a.AdmissionError, match="sealed_execution_drift"):
        control.construct_provider("a", job["id"], value, factory, mode="fake", now=NOW)
    policy(store)
    invalid = replace(value, sources=(replace(value.sources[0], content_hash="different"),))
    with pytest.raises(a.AdmissionError, match="source_material_changed_or_inaccessible"):
        control.reserve("a", "wrong", invalid, "1", now=NOW)
    invalid = replace(value, sources=(replace(value.sources[0], scope="full_text"),))
    with pytest.raises(a.AdmissionError, match="outside_approved_scope"):
        control.reserve("a", "scope", invalid, "1", now=NOW)
    factory.assert_not_called()


def test_idempotent_reserve_factory_single_start_and_no_db_lock_held(store):
    policy(store)
    value, control = inputs(store), a.GenerationAdmission(store)
    job = control.reserve("a", "one", value, "0.10", now=NOW)
    assert control.reserve("a", "one", value, Decimal("0.1"), now=NOW) == job
    with pytest.raises(ConflictError):
        control.reserve("a", "one", replace(value, prompt_revision="v2"), "0.1", now=NOW)
    with pytest.raises(ConflictError):
        control.reserve("a", "one", value, "0.2", now=NOW)

    def factory(sealed):
        assert sealed == value.snapshot()
        # A second transaction can acquire the owner lock inside the factory.
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert (
                executor.submit(control.reserve, "a", "two", value, "0.1", now=NOW).result(
                    timeout=3
                )["state"]
                == "reserved"
            )
        return "fake-client"

    assert (
        control.construct_provider("a", job["id"], value, factory, mode="fake", now=NOW)
        == "fake-client"
    )
    called = Mock()
    with pytest.raises(a.AdmissionError, match="already_started"):
        control.construct_provider("a", job["id"], value, called, mode="fake", now=NOW)
    called.assert_not_called()


def test_workflow_judge_unknown_receipts_cache_and_version_invalidation(store):
    policy(store)
    control, value, job = begin(store)
    result = {"claims": [{"text": "Synthetic output", "span": "test-only"}]}
    receipt = dict(
        receipt_id="receipt-1",
        workflow_usd="0.2",
        judge_usd="0.1",
        final=True,
        result=result,
        now=NOW,
    )
    assert control.reconcile("a", job["id"], **receipt)["state"] == "ready"
    assert control.reconcile("a", job["id"], **receipt)["state"] == "ready"
    saved = row(store, job["id"])
    assert saved[2:5] == (Decimal("0.2"), Decimal("0.1"), Decimal(0))
    assert len(saved[6]["usage_events"]) == 1
    with pytest.raises(ConflictError):
        control.reconcile("a", job["id"], **{**receipt, "workflow_usd": "0.3"})
    cached = control.reserve("a", "new-key", value, "1", now=NOW)
    assert cached["cached"] and cached["id"] == job["id"] and cached["result"] == result
    policy(store, owner="b")
    assert not control.reserve("b", "new-key", value, "1", now=NOW)["cached"]
    revised = inputs(store, 2)
    assert not control.reserve("a", "v2", revised, "1", now=NOW)["cached"]
    with pytest.raises(a.AdmissionError, match="invalid_usage_transition"):
        control.reconcile(
            "a", job["id"], receipt_id="regress", workflow_usd="0.1", judge_usd="0.1", final=True
        )
    with pytest.raises(a.AdmissionError, match="invalid_usage_transition"):
        control.reconcile("a", job["id"], receipt_id="restart", workflow_usd="0.2", judge_usd="0.1")


def test_recovery_and_cancel_preserve_unknown_and_block_blind_retry(store):
    policy(store)
    control, value, job = begin(store)
    assert (
        control.reconcile(
            "a", job["id"], receipt_id="partial", workflow_usd="0.1", judge_usd="0.05", now=NOW
        )["state"]
        == "running"
    )
    restarted = a.GenerationAdmission(store)
    recovered = restarted.recover("a", job["id"])
    assert recovered["state"] == "uncertain" and Decimal(recovered["unknown_usd"]) == Decimal(
        "0.85"
    )
    assert (
        control.reconcile(
            "a",
            job["id"],
            receipt_id="uncertain",
            workflow_usd="0.1",
            judge_usd="0.05",
            unknown_usd="0.85",
            now=NOW,
        )["state"]
        == "uncertain"
    )
    assert Decimal(control.cancel("a", job["id"])["unknown_usd"]) == Decimal("0.85")
    assert row(store, job["id"])[2:5] == (Decimal("0.1"), Decimal("0.05"), Decimal("0.85"))
    with pytest.raises(a.AdmissionError, match="already_started"):
        control.construct_provider("a", job["id"], value, Mock(), mode="fake", now=NOW)
    assert (
        control.reconcile(
            "a",
            job["id"],
            receipt_id="resolved",
            workflow_usd="0.2",
            judge_usd="0.1",
            final=True,
            now=NOW,
        )["state"]
        == "cancelled"
    )
    assert control.recover("a", job["id"])["state"] == "cancelled"


def test_factory_failure_becomes_uncertain_without_retry(store):
    policy(store)
    value, control = inputs(store), a.GenerationAdmission(store)
    job = control.reserve("a", "one", value, "1", now=NOW)
    factory = Mock(side_effect=RuntimeError("synthetic constructor failure"))
    with pytest.raises(RuntimeError):
        control.construct_provider("a", job["id"], value, factory, mode="fake", now=NOW)
    assert row(store, job["id"])[0] == "uncertain" and row(store, job["id"])[4] == 1
    with pytest.raises(a.AdmissionError, match="already_started"):
        control.construct_provider("a", job["id"], value, factory, mode="fake", now=NOW)
    assert factory.call_count == 1


def test_day_and_month_spend_and_pending_cross_periods(store):
    policy(store, day_usd="1", month_usd="1.5")
    control, value, job = begin(store)
    control.reconcile(
        "a", job["id"], receipt_id="spent", workflow_usd="0.8", judge_usd="0.2", final=True, now=NOW
    )
    changed = replace(value, prompt_revision="other")
    with pytest.raises(a.AdmissionError, match="day_cap_exceeded"):
        control.reserve("a", "today", changed, "0.1", now=NOW)
    with pytest.raises(a.AdmissionError, match="month_cap_exceeded"):
        control.reserve("a", "tomorrow", changed, "0.6", now=NOW + timedelta(days=1))
    # New month permits a new envelope, but its unresolved spend carries forward.
    later = datetime(2026, 12, 1, 16, tzinfo=UTC)
    _, _, second = begin(store, request_id="new-month", value=changed, now=later)
    control.recover("a", second["id"])
    with pytest.raises(a.AdmissionError, match="day_cap_exceeded"):
        control.reserve("a", "pending", changed, "0.1", now=later + timedelta(hours=1))
    control.cancel("a", second["id"])
    with pytest.raises(a.AdmissionError, match="day_cap_exceeded"):
        control.reserve("a", "cancelled-unknown", changed, "0.1", now=later + timedelta(hours=2))


def test_overshoot_is_recorded_and_stops_instead_of_erasing_cost(store):
    policy(store)
    control, _, job = begin(store, amount="0.5")
    result = control.reconcile(
        "a",
        job["id"],
        receipt_id="overshot",
        workflow_usd="0.6",
        judge_usd="0.1",
        final=True,
        now=NOW,
    )
    assert result["state"] == "budget_stopped"
    assert row(store, job["id"])[2:4] == (Decimal("0.6"), Decimal("0.1"))
    assert control.cancel("a", job["id"])["state"] == "budget_stopped"


@pytest.mark.parametrize(
    "value", ["-1", "NaN", "Infinity", "not-money", 0.1, True, None, "1000001"]
)
def test_bad_money_refused(value):
    with pytest.raises(a.AdmissionError, match="invalid_money"):
        a._money(value)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"approved": False}, "owner_approval_required"),
        ({"approval_record": {}}, "approval_provenance_required"),
        ({"valid_from": "bad"}, "invalid_approval_validity"),
        ({"valid_from": "2026-11-01T00:00:00"}, "invalid_approval_validity"),
        ({"expires_at": "2026-11-02T00:00:00+00:00"}, "approval_not_effective"),
        ({"model_ids": []}, "outside_approved_scope"),
        ({"day_usd": "0.5"}, "invalid_approved_caps"),
        ({"per_job_usd": "0"}, "invalid_approved_caps"),
    ],
)
def test_malformed_expired_or_out_of_scope_approval_refuses(store, changes, reason):
    policy(store, **changes)
    with pytest.raises(a.AdmissionError, match=reason):
        a.GenerationAdmission(store).reserve("a", "one", inputs(store), "0.1", now=NOW)


def test_invalid_input_private_context_and_bad_transitions(store):
    policy(store)
    value, control = inputs(store), a.GenerationAdmission(store)
    for invalid in (
        replace(value, sources=()),
        replace(value, sources=value.sources * 2),
        replace(value, kind="other"),
        replace(value, model_id=""),
        replace(value, private_question="x" * 4001),
        replace(value, settings={"bad": object()}),
        replace(value, settings={"large": "x" * 33000}),
    ):
        with pytest.raises(a.AdmissionError, match="invalid_sealed_input"):
            invalid.snapshot()
    with pytest.raises(a.AdmissionError, match="outside_approved_scope"):
        control.reserve(
            "a", "private", replace(value, private_question="My private question"), "1", now=NOW
        )
    for request in ("", "x" * 121):
        with pytest.raises(a.AdmissionError, match="invalid_request_id"):
            control.reserve("a", request, value, "1", now=NOW)
    with pytest.raises(a.AdmissionError, match="timezone_required"):
        control.reserve("a", "time", value, "1", now=NOW.replace(tzinfo=None))
    for amount in ("0", "1.01"):
        with pytest.raises(a.AdmissionError, match="job_cap_exceeded"):
            control.reserve("a", "cost" + amount, value, amount, now=NOW)
    job = control.reserve("a", "one", value, "1", now=NOW)
    assert control.recover("a", job["id"])["state"] == "reserved"
    with pytest.raises(a.AdmissionError, match="invalid_usage_transition"):
        control.reconcile("a", job["id"], receipt_id="unstarted", workflow_usd="0", judge_usd="0")
    with pytest.raises(a.AdmissionError, match="receipt_required"):
        control.reconcile("a", job["id"], receipt_id="", workflow_usd="0", judge_usd="0")
    with pytest.raises(a.AdmissionError, match="invalid_usage_transition"):
        control.reconcile(
            "a", job["id"], receipt_id="badfinal", workflow_usd="0", judge_usd="0", final="yes"
        )


def test_corrupt_or_oversized_ledger_fails_closed(store, monkeypatch):
    policy(store)
    control, value, job = begin(store)
    control.reconcile("a", job["id"], receipt_id="paid", workflow_usd="0.1", judge_usd="0", now=NOW)
    with store.pool.connection() as conn:
        data = row(store, job["id"])[6]
        data["usage_events"][0]["month"] = "2026-10-01"
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job["id"])
        )
    with pytest.raises(a.AdmissionError, match="ledger_reconciliation_required"):
        control.reserve("a", "new", value, "0.1", now=NOW)
    with store.pool.connection() as conn:
        data["usage_events"] = []
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job["id"])
        )
    with pytest.raises(a.AdmissionError, match="ledger_reconciliation_required"):
        control.reserve("a", "new", value, "0.1", now=NOW)
    monkeypatch.setattr(a, "MAX_LEDGER_JOBS", 0)
    with pytest.raises(a.AdmissionError, match="ledger_requires_rollup"):
        control.reserve("a", "new", value, "0.1", now=NOW)
    with store.pool.connection() as conn:
        conn.execute("DELETE FROM workspace_spend_reservations WHERE job_id=%s", (job["id"],))
    with pytest.raises(a.AdmissionError, match="reservation_missing"):
        control.cancel("a", job["id"])
    with pytest.raises(a.AdmissionError, match="reservation_missing"):
        control.reconcile("a", job["id"], receipt_id="lost", workflow_usd="0.1", judge_usd="0")


def test_other_owner_cannot_generate_from_private_material(store):
    support.ingest(store, visibility_owner="a")
    value = inputs(store)
    policy(store, owner="b")
    with pytest.raises(a.AdmissionError, match="source_material_changed_or_inaccessible"):
        a.GenerationAdmission(store).reserve("b", "private", value, "1", now=NOW)


def test_active_holds_and_unresolved_cancel_carry_across_utc_midnight(store):
    policy(store, day_usd="1", month_usd="2")
    control, value, job = begin(store)
    tomorrow = NOW + timedelta(days=1)
    changed = replace(value, prompt_revision="new")
    with pytest.raises(a.AdmissionError, match="day_cap_exceeded"):
        control.reserve("a", "tomorrow", changed, "0.1", now=tomorrow)
    control.cancel("a", job["id"])
    with pytest.raises(a.AdmissionError, match="day_cap_exceeded"):
        control.reserve("a", "tomorrow", changed, "0.1", now=tomorrow)
    # Only an explicit cumulative receipt resolves uncertain spend; its known
    # delta is charged on this UTC day, not hidden in yesterday's reservation.
    control.reconcile(
        "a",
        job["id"],
        receipt_id="late-final",
        workflow_usd="0.3",
        judge_usd="0.1",
        final=True,
        now=tomorrow,
    )
    assert control.reserve("a", "tomorrow", changed, "0.6", now=tomorrow)["state"] == "reserved"


def test_scope_and_expiry_at_construction_are_not_just_admission_checks(store):
    policy(store, allow_private_context=True)
    value = replace(inputs(store), private_question="Only synthetic private context")
    control = a.GenerationAdmission(store)
    job = control.reserve("a", "one", value, "1", now=NOW)
    factory = Mock()
    with pytest.raises(a.AdmissionError, match="approval_not_effective"):
        control.construct_provider(
            "a", job["id"], value, factory, mode="fake", now=NOW + timedelta(days=31)
        )
    factory.assert_not_called()
