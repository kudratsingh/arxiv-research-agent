"""21->22 is separate approval; no edits to the existing21 receipt or limits."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from src.workspace import programme_amendments as parent
from src.workspace import programme_successors as successor
from src.workspace.admission import AdmissionError, _digest
from src.workspace.qualification_budget import PROGRAM_LIMITS, census
from tests import test_workspace_programme_amendments as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


def setup(store):
    old = support.setup(store)
    receipt = support.approved(old)
    parent.record_external(store, receipt)
    with store.pool.connection() as c:
        before = c.execute("SELECT to_jsonb(t) FROM workspace_programme_amendments t").fetchone()[0]
        proposal = successor.proposal(c, "evaluation")
    return before, proposal


def approved(proposal):
    receipt = support.approved(proposal)
    parent_end = datetime.fromisoformat(proposal["amendment"]["predecessor_expiry"])
    receipt["expires_at"] = min(datetime.now(UTC) + timedelta(hours=12), parent_end).isoformat()
    return receipt


def test_proposal_does_not_activate_and_preserves_predecessor(store):
    old, proposal = setup(store)
    with store.pool.connection() as c:
        assert (
            parent.effective_limits(c, "evaluation")["new_jobs"] == 21
            and proposal["approved"] is False
        )
        assert (
            c.execute("SELECT to_jsonb(t) FROM workspace_programme_amendments t").fetchone()[0]
            == old
        )
    with pytest.raises(AdmissionError):
        successor.record_external(store, proposal)


def test_explicit_successor_only_changes_job_cap_and_is_idempotent(store):
    old, proposal = setup(store)
    receipt = approved(proposal)
    result = successor.record_external(store, receipt)
    assert result["effective_jobs"] == 22 and result["workflow_permission_created"] is False
    assert successor.record_external(store, receipt)["duplicate"]
    with store.pool.connection() as c:
        assert parent.effective_limits(
            c, "evaluation", required_proposal_digest=proposal["proposal_digest"]
        ) == {**PROGRAM_LIMITS, "new_jobs": 22}
        assert (
            parent.effective_limits(
                c, "evaluation", required_proposal_digest=old["proposal_digest"]
            )["new_jobs"]
            == 21
        )
        assert (
            c.execute("SELECT to_jsonb(t) FROM workspace_programme_amendments t").fetchone()[0]
            == old
        )
        assert (
            c.execute("SELECT limits FROM workspace_evaluation_programs").fetchone()[0]
            == PROGRAM_LIMITS
        )
        assert c.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0


@pytest.mark.parametrize(
    "change",
    [
        "jobs",
        "usd",
        "counts",
        "messages",
        "predecessor",
        "expiry",
        "unapproved",
        "basis",
        "kind",
        "proposal_digest",
    ],
)
def test_successor_refuses_broadening_drift_or_expiry_extension(store, change):
    _, proposal = setup(store)
    r = approved(proposal)
    if change in {"jobs", "usd", "counts", "messages"}:
        r["amendment"]["amended_limits"][{"jobs": "new_jobs"}.get(change, change)] = (
            23 if change == "jobs" else "20" if change == "usd" else 81
        )
    elif change == "predecessor":
        r["amendment"]["predecessor_authorization_digest"] = "different"
    elif change == "expiry":
        r["expires_at"] = (
            datetime.fromisoformat(r["amendment"]["predecessor_expiry"]) + timedelta(seconds=1)
        ).isoformat()
    elif change == "unapproved":
        r["approved"] = False
    elif change == "basis":
        r["amendment"]["basis"]["counts"] += 1
    elif change == "kind":
        r["authorization_kind"] = "owner"
    else:
        r["proposal_digest"] = "wrong"
    if change != "proposal_digest":
        r["proposal_digest"] = _digest(r["amendment"])
    with pytest.raises(AdmissionError):
        successor.record_external(store, r)
    with store.pool.connection() as c:
        assert parent.effective_limits(c, "evaluation")["new_jobs"] == 21


@pytest.mark.asyncio
async def test_successor_admits_job22_and_refuses23_without_resetting_history(store):
    _, proposal = setup(store)
    successor.record_external(store, approved(proposal))
    support.seed_failed(store, 7, 14)
    await support.execute(store, "job22")
    adapter = support.support.adapter(store, request_id="job23")
    with pytest.raises(AdmissionError, match="program_job_cap_exceeded"):
        adapter.start("job23", "0.25")
    with store.pool.connection() as c:
        assert len(census(c, "a")["generation_job_ids"]) - 1 == 22


def test_predecessor_revocation_disables_successor_and_histories_are_checked(store):
    old, proposal = setup(store)
    r = approved(proposal)
    successor.record_external(store, r)
    parent.revoke(store, old["amendment_id"], actor="Synthetic revocation")
    with store.pool.connection() as c, pytest.raises(AdmissionError):
        parent.effective_limits(c, "evaluation")


@pytest.mark.parametrize("change", ["hash", "proposal", "expiry", "unknown_required", "history"])
def test_recorded_successor_integrity_and_required_binding(store, change):
    _, p = setup(store)
    r = approved(p)
    successor.record_external(store, r)
    with store.pool.connection() as c:
        if change == "hash":
            c.execute(
                "UPDATE workspace_programme_successor_amendments SET authorization_digest='changed'"
            )
        elif change == "proposal":
            c.execute(
                "UPDATE workspace_programme_successor_amendments SET proposal_digest='changed'"
            )
        elif change == "expiry":
            c.execute(
                "UPDATE workspace_programme_successor_amendments SET expires_at=expires_at+interval '1 second'"
            )
        elif change == "history":
            c.execute(
                "UPDATE workspace_spend_reservations SET amount=amount+0.01 WHERE job_id=%s",
                (p["amendment"]["basis"]["generation_job_ids"][0],),
            )
        with pytest.raises(AdmissionError):
            parent.effective_limits(
                c,
                "evaluation",
                required_proposal_digest="different"
                if change == "unknown_required"
                else p["proposal_digest"],
            )


def test_revocation_and_conflicting_reapproval_are_append_only(store):
    old, p = setup(store)
    r = approved(p)
    record = successor.record_external(store, r)
    different = deepcopy(r)
    different["approved_by"] = "Another synthetic actor"
    with pytest.raises(AdmissionError, match="immutable"):
        successor.record_external(store, different)
    with pytest.raises(AdmissionError):
        successor.revoke(store, record["amendment_id"], actor="")
    with pytest.raises(AdmissionError):
        successor.revoke(store, "missing", actor="test")
    successor.revoke(store, record["amendment_id"], actor="Synthetic revoke")
    successor.revoke(store, record["amendment_id"], actor="Synthetic repeat")
    with store.pool.connection() as c:
        assert (
            c.execute("SELECT count(*) FROM workspace_programme_successor_revocations").fetchone()[
                0
            ]
            == 1
        )
        with pytest.raises(AdmissionError):
            parent.effective_limits(c, "evaluation", required_proposal_digest=p["proposal_digest"])
        assert (
            parent.effective_limits(
                c, "evaluation", required_proposal_digest=old["proposal_digest"]
            )["new_jobs"]
            == 21
        )


@pytest.mark.parametrize(
    "mutation", ["missing_parent", "bad_parent_hash", "unapproved", "bad_time", "empty_basis"]
)
def test_malformed_parent_or_successor_never_creates_permission(store, mutation):
    _, p = setup(store)
    r = approved(p)
    with store.pool.connection() as c:
        if mutation == "missing_parent":
            c.execute("DELETE FROM workspace_programme_amendments")
        elif mutation == "bad_parent_hash":
            c.execute("UPDATE workspace_programme_amendments SET authorization_digest='wrong'")
    if mutation == "unapproved":
        r["approved"] = False
    elif mutation == "bad_time":
        r["approved_at"] = "invalid"
    elif mutation == "empty_basis":
        r["amendment"]["basis_members"] = []
        r["proposal_digest"] = _digest(r["amendment"])
    with pytest.raises(AdmissionError):
        successor.record_external(store, r)


def test_operator_template_record_and_revoke_are_separate_and_mock_only(
    store, monkeypatch, tmp_path
):
    import json
    import sys
    from contextlib import nullcontext

    from src.workspace import d5_benchmark

    _, proposal = setup(store)
    monkeypatch.setenv("D5_POSTGRES_URL", "postgresql://localhost:15488/workspace_d5_tests")
    monkeypatch.setattr(d5_benchmark, "database", lambda _: nullcontext(store.pool))
    f = tmp_path / "receipt.json"

    def invoke(verb, pid="evaluation"):
        monkeypatch.setattr(
            sys, "argv", ["successor", verb, "--program-id", pid, "--receipt", str(f)]
        )
        successor.main()

    invoke("template")
    assert json.loads(f.read_text())["approved"] is False
    with pytest.raises(AdmissionError):
        invoke("record")
    f.write_text(json.dumps(approved(proposal)))
    invoke("record")
    invoke("revoke")
    with pytest.raises(AdmissionError):
        invoke("record", "another")
