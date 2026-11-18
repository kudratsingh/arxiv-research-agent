"""Exact v20 programme membership and post-baseline activity checks."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from psycopg.types.json import Jsonb

from src.workspace import d5_continuation_authority as authority
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import D5Adapter
from src.workspace.d5_continuation_policy import CASE_MAP, LIMITS
from src.workspace.d5_freeze import restore_input
from tests.d5_case_isolation_fixtures import fixture_campaign as fixture_campaign
from tests.d5_case_isolation_fixtures import prepared_campaign as prepared_campaign


class ReadOnlyProgramme:
    def __init__(self, scope, members, jobs):
        self.scope = scope
        self.members = members
        self.jobs = jobs

    def execute(self, query, params):
        if query.startswith("SELECT packet_digest,authorization_digest,data,expires_at"):
            return SimpleNamespace(fetchone=lambda: self.scope)
        if query.startswith("SELECT owner FROM workspace_evaluation_members"):
            assert params == (authority.PROGRAM_ID,)
            return [(owner,) for owner in self.members]
        if query.startswith("SELECT j.id,j.owner,j.input_digest"):
            expected_scope = (
                self.scope[2]["authorization_record"]["scope_id"] if self.scope else None
            )
            assert not expected_scope or params[0] == params[-1] == expected_scope
            return self.jobs
        raise AssertionError(query)


@pytest.fixture
def bound_activity():
    historical = ["one-prior-member", "another-prior-member"]
    actor = "d5-continuation-pinned-run"
    scope_id = "d5-frozen-scope"
    expires = datetime(2026, 11, 18, tzinfo=UTC)
    first = next(iter(CASE_MAP))
    inputs = {"settings": {"d5_scope_id": scope_id, "d5_case_id": first}}
    input_digest = _digest(inputs)
    cases = {
        key: {"owner": actor, "input_digest": input_digest, "operation": "workflow"}
        for key in CASE_MAP
    }
    core = {"basis_members": historical, "basis": {"contact_checkpoints": {"old-job": {}}}}
    receipt = {
        "scope_id": scope_id,
        "packet_digest": "frozen-packet",
        "members": [actor],
        "stages": ["B", "C", "D"],
        "limits": LIMITS,
        "expires_at": expires.isoformat(),
        "campaign_extension": {"proposal_digest": "frozen-proposal", "core": core},
        "case_bindings_digest": _digest(cases),
    }
    digest = _digest(receipt)
    scoped_data = {
        "program_id": authority.PROGRAM_ID,
        "authorization_record": receipt,
        "baseline": core["basis"],
        "members": receipt["members"],
        "stages": receipt["stages"],
        "limits": receipt["limits"],
        "program_amendment_proposal_digest": receipt["campaign_extension"]["proposal_digest"],
        "cases": cases,
    }
    scope = (receipt["packet_digest"], digest, scoped_data, expires)
    job = (
        "gen-" + _digest([actor, scope_id + "-" + first])[:40],
        actor,
        input_digest,
        inputs,
        first,
        receipt["packet_digest"],
        input_digest,
        actor,
        actor,
    )
    return receipt, core, scope, job


@pytest.mark.unit
def test_activity_allows_only_phase_appropriate_members_and_exact_job(bound_activity):
    receipt, core, scope, job = bound_activity
    historical = core["basis_members"]
    digest = _digest(receipt)
    authority._validate_activity(ReadOnlyProgramme(None, historical, []), receipt, core, digest)
    authority._validate_activity(
        ReadOnlyProgramme(scope, [*historical, *receipt["members"]], [job]), receipt, core, digest
    )
    with pytest.raises(AdmissionError, match="continuation_active_membership_drift"):
        authority._validate_activity(
            ReadOnlyProgramme(None, [*historical, *receipt["members"]], []), receipt, core, digest
        )
    with pytest.raises(AdmissionError, match="continuation_active_membership_drift"):
        authority._validate_activity(
            ReadOnlyProgramme(scope, [*historical, *receipt["members"], "foreign"], []),
            receipt,
            core,
            digest,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("index", "change"),
    [
        (0, "old-job"),
        (0, "unbound-job"),
        (1, "one-prior-member"),
        (2, "wrong-input"),
        (3, {"settings": {"d5_scope_id": "other"}}),
        (4, None),
        (5, "wrong-packet"),
        (6, "wrong-run-input"),
        (7, "foreign-actor"),
        (8, None),
    ],
)
def test_activity_rejects_job_or_reservation_drift(bound_activity, index, change):
    receipt, core, scope, original = bound_activity
    job = list(original)
    job[index] = change
    with pytest.raises(AdmissionError, match="continuation_post_baseline_activity_drift"):
        authority._validate_activity(
            ReadOnlyProgramme(scope, [*core["basis_members"], *receipt["members"]], [job]),
            receipt,
            core,
            _digest(receipt),
        )


@pytest.mark.unit
def test_activity_rejects_rehashed_scope_case_data(bound_activity):
    receipt, core, scope, job = deepcopy(bound_activity)
    scope[2]["cases"][job[4]]["input_digest"] = "replaced-input"
    with pytest.raises(AdmissionError, match="continuation_registered_scope_binding_drift"):
        authority._validate_activity(
            ReadOnlyProgramme(scope, [*core["basis_members"], *receipt["members"]], [job]),
            receipt,
            core,
            _digest(receipt),
        )


@pytest.mark.integration
def test_active_scope_refuses_additive_members_and_known_unbound_activity(fixture_campaign):
    store, packet, compiled = fixture_campaign
    proposal = packet["campaign_extension"]
    program = packet["program_id"]
    required = proposal["proposal_digest"]
    first = next(iter(compiled.values()))
    inputs = restore_input(first["input"])
    contacted = []
    adapter = D5Adapter(
        store,
        first["owner"],
        inputs,
        transport=httpx.MockTransport(lambda request: contacted.append(request)),
    )
    job = adapter.start(inputs.settings["d5_request_id"])
    with store.pool.connection() as conn:
        assert authority.active(conn, program, required) is not None

    with store.pool.connection() as conn, conn.transaction(force_rollback=True):
        conn.execute(
            "INSERT INTO workspace_evaluation_members VALUES(%s,%s)",
            ("synthetic-foreign-programme-member", program),
        )
        with pytest.raises(AdmissionError, match="continuation_active_membership_drift"):
            authority.active(conn, program, required)

    with store.pool.connection() as conn, conn.transaction(force_rollback=True):
        owner = proposal["core"]["basis_members"][0]
        job_id = "synthetic-known-outside-scope"
        data = {
            "sealed_input": {"model_id": "synthetic"},
            "adapter": {
                "contacts": [
                    {"endpoint": "messages/count_tokens", "state": "completed"},
                    {"endpoint": "messages", "state": "completed"},
                ]
            },
        }
        conn.execute(
            "INSERT INTO workspace_generation_jobs(id,owner,approval_id,state,input_digest,data) "
            "VALUES(%s,%s,'synthetic','ready',%s,%s)",
            (job_id, owner, _digest(data["sealed_input"]), Jsonb(data)),
        )
        conn.execute(
            "INSERT INTO workspace_spend_reservations(job_id,owner,amount,day,month,workflow,state) "
            "VALUES(%s,%s,0.10,CURRENT_DATE,CURRENT_DATE,0.07,'ready')",
            (job_id, owner),
        )
        with pytest.raises(AdmissionError, match="continuation_post_baseline_activity_drift"):
            authority.active(conn, program, required)

    with store.pool.connection() as conn, conn.transaction(force_rollback=True):
        conn.execute("DELETE FROM workspace_d5_case_runs WHERE job_id=%s", (job["id"],))
        with pytest.raises(AdmissionError, match="continuation_post_baseline_activity_drift"):
            authority.active(conn, program, required)

    with store.pool.connection() as conn:
        assert authority.active(conn, program, required) is not None
    assert not contacted
