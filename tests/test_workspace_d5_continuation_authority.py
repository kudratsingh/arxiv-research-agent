"""v20 continuation authority over a pinned baseline mirrored to disposable Postgres."""

from __future__ import annotations

import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from src.workspace import d5_authorization
from src.workspace import d5_continuation_authority as authority
from src.workspace import d5_continuation_packet as continuation
from src.workspace import d5_continuation_policy as policy
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import D5Adapter
from src.workspace.d5_benchmark import read
from src.workspace.d5_fixture import install
from src.workspace.d5_freeze import restore_input
from src.workspace.qualification_budget import census
from src.workspace.store import WorkspaceStore

pytestmark = pytest.mark.integration

BASELINE = Path.home() / (
    "Machine-Learning-Projects/arxiv-evidence/d5-behavior-v20-20261117/READONLY-BASELINE.json.gz"
)
NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)


class FixtureClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@contextmanager
def disposable_ledger(snapshot):
    url = os.environ.get("WORKSPACE_TEST_POSTGRES_URL", "")
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path != "/workspace_d5_tests":
        pytest.skip("isolated workspace_d5_tests Postgres instance required")
    schema = "ws_test_v20_authority_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        with ConnectionPool(
            url, min_size=1, max_size=3, kwargs={"options": f"-c search_path={schema},public"}
        ) as pool:
            store = WorkspaceStore(pool)
            install(store, snapshot, fixture=True)
            yield store
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture(scope="module")
def frozen():
    if not BASELINE.is_file():
        pytest.skip("pinned owner-local baseline mirror unavailable")
    snapshot = read(BASELINE)
    assert _digest(snapshot) == authority.SNAPSHOT_DIGEST
    with pytest.MonkeyPatch.context() as env, disposable_ledger(snapshot) as store:
        env.setenv("WORKSPACE_D5_OFFLINE", "1")
        env.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
        env.setattr(authority, "datetime", FixtureClock)
        env.setattr(continuation, "datetime", FixtureClock)
        env.setattr(d5_authorization, "datetime", FixtureClock)
        packet = continuation.freeze(store, snapshot)
        yield store, packet, snapshot


def approved_receipt(packet):
    return {
        **continuation.template(packet),
        "approved": True,
        "approved_by": "Synthetic isolated authority test",
        "approved_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=4)).isoformat(),
        "approval_source": "Disposable Postgres test fixture",
        "authorization_kind": "offline_fixture",
        "transport_mode": "mock",
        "historical_uncertainty_exception_approved": True,
    }


def rehash(packet):
    core = packet["campaign_extension"]["core"]
    core["plan_digest"] = continuation.plan_digest(packet)
    packet["campaign_extension"]["proposal_digest"] = _digest(core)
    packet["packet_digest"] = _digest({k: v for k, v in packet.items() if k != "packet_digest"})


@pytest.mark.parametrize(
    ("path", "replacement", "error"),
    [
        (
            ("programme", "programme_expires_at"),
            "2030-01-01T00:00:00+00:00",
            "interpretation_or_ancestry",
        ),
        (("development_reuse", "old_checks_reused"), True, "interpretation_or_ancestry"),
        (
            ("continuation_lineage", "original_v19_report_quality"),
            "PASS",
            "interpretation_or_ancestry",
        ),
        (("stop_policy",), "Continue on provider errors.", "interpretation_or_ancestry"),
        (("limits", "jobs"), 11, "frozen_protocol"),
        (("operation_routes", "revision"), "replacement", "frozen_protocol"),
        (("human_qualification",), True, "frozen_protocol"),
        (("program_id",), "another-program", "continuation_"),
        (("scope_profile",), "another-profile", "continuation_"),
        (("profile_basis",), "Changed discovery provenance", "continuation_"),
        (("probe_evidence_exclusions",), [], "continuation_"),
        (("checker_normalization_revision",), "another-checker", "continuation_"),
        (("cases", 2, "predecessor_packet"), "another-packet", "case_lineage"),
        (("unknown_field",), "unverified metadata", "frozen_sources_ranking_references"),
        (("cases", 2, "unknown_field"), "unverified metadata", "case_lineage"),
        (("created_at",), "2026-11-18T12:00:00", "application_or_creation_identity"),
        (("campaign_extension", "core", "unknown_field"), "extra", "authority_binding_drift"),
        (("campaign_extension", "core", "limits", "usd"), "23", "authority_binding_drift"),
        (("campaign_extension", "core", "retained_exceptions"), [], "authority_binding_drift"),
        (("campaign_extension", "core", "basis_members"), [], "authority_binding_drift"),
        (("scoring", "generated_claims_min"), 19, "substantive_threshold"),
        (("scoring", "completion_min_ratio"), 0.89, "substantive_threshold"),
        (("source_bindings", "versions"), {}, "frozen_sources_ranking_references"),
        (("cases", 2, "reference_case_id"), "campaign-eval-learn-measurement", "case_lineage"),
        (("cases", 2, "ranking"), [], "question_or_selection"),
        (("cases", 2, "sealed", "units"), {}, "sealed_request_or_source"),
        (("cases", 2, "wire_digest"), "other", "actual_schema_or_wire"),
        (("probes", 0, "wire", "max_tokens"), 1, "question_or_selection|probe_body_or_reference"),
    ],
)
def test_rehashed_packet_changes_remain_inadmissible(frozen, path, replacement, error):
    _store, packet, _snapshot = frozen
    altered = deepcopy(packet)
    item = altered
    for field in path[:-1]:
        item = item[field]
    item[path[-1]] = replacement
    rehash(altered)
    with pytest.raises(AdmissionError, match=error):
        continuation.verify_packet(altered)


def test_rehashed_packet_and_proposal_cannot_coordinate_a_different_history(frozen):
    _store, packet, _snapshot = frozen
    altered = deepcopy(packet)
    history = {**altered["history"], "messages": altered["history"]["messages"] - 1}
    altered["history"] = history
    altered["campaign_extension"]["core"]["basis"] = deepcopy(history)
    rehash(altered)
    with pytest.raises(AdmissionError, match="continuation_plan_or_authority_binding_drift"):
        continuation.verify_packet(altered)


def test_rehashed_authority_proposal_cannot_be_rebound_to_another_plan(frozen):
    _store, packet, _snapshot = frozen
    altered = deepcopy(packet)
    core = altered["campaign_extension"]["core"]
    core["plan_digest"] = "1" * 64
    altered["campaign_extension"]["proposal_digest"] = _digest(core)
    altered["packet_digest"] = _digest({k: v for k, v in altered.items() if k != "packet_digest"})
    with pytest.raises(AdmissionError, match="continuation_plan_or_authority_binding_drift"):
        continuation.verify_packet(altered)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("approved", False),
        ("approved_by", "  "),
        ("approval_source", ""),
        ("approved_at", "not-an-approval-time"),
        ("approved_at", NOW.replace(tzinfo=None).isoformat()),
        ("approved_at", (NOW + timedelta(seconds=1)).isoformat()),
        ("expires_at", NOW.isoformat()),
        ("expires_at", (NOW + timedelta(hours=24, seconds=1)).isoformat()),
        ("expires_at", "2026-11-22T00:00:00+00:00"),
        ("historical_uncertainty_exception_approved", False),
    ],
)
def test_external_receipt_requires_explicit_bound_attributed_approval(frozen, field, value):
    store, packet, _snapshot = frozen
    receipt = approved_receipt(packet)
    receipt[field] = value
    with pytest.raises(AdmissionError, match="continuation_exact_external_authorization_required"):
        authority.record_external(store, receipt, packet=packet)
    with store.pool.connection() as conn:
        assert authority.active(conn, authority.PROGRAM_ID) is None


@pytest.mark.parametrize(
    "field", ["packet_digest", "case_bindings_digest", "case_order", "source_bindings"]
)
def test_receipt_binding_cannot_be_replaced_even_if_caller_requests_registration(frozen, field):
    store, packet, _snapshot = frozen
    receipt = approved_receipt(packet)
    receipt[field] = None
    with pytest.raises(AdmissionError, match="continuation_exact_owner_receipt_required"):
        continuation.record(store, packet, receipt)
    with pytest.raises(AdmissionError, match="continuation_exact_verified_packet_required"):
        authority.record_external(store, receipt, packet=packet)


def test_disposable_receipt_refuses_provider_mode_and_disabled_mock(frozen, monkeypatch):
    store, packet, _snapshot = frozen
    receipt = approved_receipt(packet)
    with pytest.raises(AdmissionError, match="continuation_exact_external_authorization_required"):
        authority.record_external(
            store,
            {**receipt, "transport_mode": "provider", "authorization_kind": "owner"},
            packet=packet,
        )
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "0")
    with pytest.raises(AdmissionError, match="continuation_exact_external_authorization_required"):
        authority.record_external(store, receipt, packet=packet)
    with pytest.raises(AdmissionError, match="continuation_fixture_mock_only"):
        continuation.authorize_fixture(store, packet)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("budget_change", True, "proposal_policy_or_digest"),
        ("parent_v19", {}, "parent_revoked_or_unbound"),
        ("capacity_ancestor", {}, "programme_ancestor"),
        ("retained_exceptions", [], "historical_prefix_or_holds"),
    ],
)
def test_rehashed_proposal_does_not_allow_programme_or_ancestor_drift(frozen, field, value, error):
    store, packet, _snapshot = frozen
    proposal = deepcopy(packet["campaign_extension"])
    proposal["core"][field] = value
    proposal["proposal_digest"] = _digest(proposal["core"])
    with store.pool.connection() as conn, pytest.raises(AdmissionError, match=error):
        authority.validate_proposal(conn, proposal, fresh=True)


@pytest.mark.parametrize(
    "kind", ["version", "material", "member", "history", "parent_scope", "parent_revoked"]
)
def test_real_mirrored_ledger_drift_refuses_authority(frozen, kind):
    store, packet, snapshot = frozen
    receipt = approved_receipt(packet)
    with store.pool.connection() as conn, conn.transaction(force_rollback=True):
        if kind in {"version", "material"}:
            label, table, key = (
                ("versions", "workspace_versions", "version_id")
                if kind == "version"
                else ("materials", "workspace_material", "material_id")
            )
            identifier = next(iter(receipt["source_bindings"][label]))
            conn.execute(
                sql.SQL("UPDATE {} SET data=data || %s WHERE {}=%s").format(
                    sql.Identifier(table), sql.Identifier(key)
                ),
                (Jsonb({"test_drift": True}), identifier),
            )
            error = "continuation_source_bindings_drift"
        elif kind == "member":
            conn.execute(
                "INSERT INTO workspace_evaluation_members VALUES(%s,%s)",
                ("d5-continuation-unapproved-test-member", authority.PROGRAM_ID),
            )
            error = "continuation_member_baseline_drift"
        elif kind == "history":
            parent = next(
                row
                for row in snapshot["recorded_keyed_continuations"]
                if row["scope_id"] == authority.PARENT_SCOPE
            )
            old = parent["record"]["campaign_extension"]["core"]["basis"]["contact_checkpoints"]
            new = set(packet["history"]["contact_checkpoints"]) - set(old)
            changed = conn.execute(
                "UPDATE workspace_spend_reservations SET workflow=workflow+0.01 "
                "WHERE job_id=ANY(%s) AND workflow>0 RETURNING job_id",
                (sorted(new),),
            ).fetchall()
            assert changed
            error = "continuation_historical_financial_drift"
        elif kind == "parent_scope":
            conn.execute(
                "UPDATE workspace_d5_scopes SET state='revoked' WHERE scope_id=%s",
                (authority.PARENT_SCOPE,),
            )
            error = "continuation_stopped_v19_receipt_drift"
        else:
            revoke_extension(conn, packet["programme"]["extension_id"])
            error = "continuation_parent_revoked_or_unbound"
        with pytest.raises(AdmissionError, match=error):
            authority._validate_receipt(conn, receipt, fresh=True)


@pytest.mark.parametrize("index", range(4))
def test_each_history_hold_is_required_at_its_frozen_amount(frozen, index):
    store, packet, snapshot = frozen
    receipt = approved_receipt(packet)
    hold = snapshot["retained_liabilities"][index]
    with store.pool.connection() as conn, conn.transaction(force_rollback=True):
        removed = conn.execute(
            "UPDATE workspace_spend_reservations SET unknown=0 WHERE job_id=%s RETURNING job_id",
            (hold["job_id"],),
        ).fetchone()
        assert removed == (hold["job_id"],)
        with pytest.raises(AdmissionError, match="campaign_v19|continuation"):
            authority._validate_receipt(conn, receipt, fresh=True)


def revoke_extension(conn, extension_id):
    conn.execute(
        "INSERT INTO workspace_d5_keyed_continuation_revocations(extension_id,record) VALUES(%s,%s)",
        (extension_id, Jsonb({"reason": "Synthetic disposable revocation"})),
    )


def scope_rows(conn, receipt):
    return conn.execute(
        "SELECT state,authorization_digest,expires_at,data FROM workspace_d5_scopes WHERE scope_id=%s",
        (receipt["scope_id"],),
    ).fetchall()


def authority_row(conn):
    return conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_keyed_continuations t WHERE extension_id=%s",
        (authority.EXTENSION_ID,),
    ).fetchone()[0]


def assert_no_dispatch(conn, receipt, baseline):
    (member,) = receipt["members"]
    assert (
        conn.execute(
            "SELECT 1 FROM workspace_d5_case_runs WHERE scope_id=%s", (receipt["scope_id"],)
        ).fetchone()
        is None
    )
    assert (
        conn.execute("SELECT 1 FROM workspace_generation_jobs WHERE owner=%s", (member,)).fetchone()
        is None
    )
    assert census(conn, baseline["members"][0], members=baseline["members"]) == baseline["history"]


def test_second_phase_transaction_rolls_back_and_identical_receipt_resumes(frozen, monkeypatch):
    _store, packet, baseline = frozen
    receipt = approved_receipt(packet)
    with disposable_ledger(baseline) as store:
        with store.pool.connection() as conn:
            # The budget policy insert occurs after the active scope and member
            # are inserted. This forces the actual second transaction to abort.
            conn.execute(
                "CREATE FUNCTION stop_budget_policy() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN RAISE EXCEPTION 'synthetic phase two interruption'; END $$"
            )
            conn.execute(
                "CREATE TRIGGER stop_budget_policy BEFORE INSERT ON workspace_budget_policies "
                "FOR EACH ROW EXECUTE FUNCTION stop_budget_policy()"
            )
        with pytest.raises(psycopg.errors.RaiseException, match="synthetic phase two interruption"):
            continuation.record(store, packet, receipt)
        with store.pool.connection() as conn:
            retained = authority_row(conn)
            assert retained["record"] == receipt
            assert retained["authorization_digest"] == _digest(receipt)
            assert not scope_rows(conn, receipt)
            assert (
                conn.execute(
                    "SELECT 1 FROM workspace_evaluation_members WHERE owner=%s",
                    (receipt["members"][0],),
                ).fetchone()
                is None
            )
            assert (
                conn.execute(
                    "SELECT 1 FROM workspace_budget_policies WHERE owner=%s",
                    (receipt["members"][0],),
                ).fetchone()
                is None
            )
            assert_no_dispatch(conn, receipt, baseline)

        attempted_io = []

        def forbidden(request):
            attempted_io.append(request)
            raise AssertionError("an authority-only record cannot dispatch")

        first = next(iter(continuation.compile_packet(packet).values()))
        with pytest.raises(AdmissionError):
            inputs = restore_input(first["input"])
            adapter = D5Adapter(
                store, first["owner"], inputs, transport=httpx.MockTransport(forbidden)
            )
            adapter.start(inputs.settings["d5_request_id"])
        assert not attempted_io

        modified = {**receipt, "expires_at": (NOW + timedelta(hours=5)).isoformat()}
        with pytest.raises(AdmissionError, match="continuation_immutable_no_renewal"):
            continuation.record(store, packet, modified)
        with store.pool.connection() as conn:
            assert authority_row(conn) == retained
            assert not scope_rows(conn, receipt)
            assert_no_dispatch(conn, receipt, baseline)
            conn.execute("DROP TRIGGER stop_budget_policy ON workspace_budget_policies")

        resumed = continuation.record(store, packet, receipt)
        assert resumed["activation"] == {
            "authorization_digest": _digest(receipt),
            "duplicate": True,
            "provider_contacts": 0,
        }
        assert resumed["expires_at"] == receipt["expires_at"]
        repeated = continuation.record(store, packet, receipt)
        assert repeated["activation"]["duplicate"] and repeated["scope"]["duplicate"]
        with store.pool.connection() as conn:
            assert authority_row(conn) == retained
            (row,) = scope_rows(conn, receipt)
            assert row[:3] == (
                "active",
                _digest(receipt),
                datetime.fromisoformat(receipt["expires_at"]),
            )
            assert row[3]["authorization_record"] == receipt
            assert list(continuation.compile_packet(packet)) == list(policy.CASE_MAP)
            assert len(row[3]["cases"]) == 10
            assert_no_dispatch(conn, receipt, baseline)
            parent = conn.execute(
                "SELECT state,expires_at FROM workspace_d5_scopes WHERE scope_id=%s",
                (authority.PARENT_SCOPE,),
            ).fetchone()
            assert parent[0] == "stopped" and parent[1] < NOW
            assert authority.active(conn, authority.PROGRAM_ID, "other-proposal") is None
            assert authority.active(conn, "another-program") is None

            found = authority.active(conn, authority.PROGRAM_ID)
            assert found is not None
            actual_policy = conn.execute(
                "SELECT data FROM workspace_budget_policies WHERE owner=%s",
                (receipt["members"][0],),
            ).fetchone()[0]
            retained_holds = authority.guard_exception(conn, actual_policy, found, None)
            assert retained_holds == {
                "retained_exceptions": baseline["retained_liabilities"],
                "retained_liability_usd": "2.275066",
                "settled": False,
            }
            wrong_policy = {**actual_policy, "d5_authorization_digest": "other-authorization"}
            with pytest.raises(AdmissionError, match="campaign_v19_exception_scope_mismatch"):
                authority.guard_exception(conn, wrong_policy, found, None)

            compiled = continuation.compile_packet(packet)
            first_case, second_case, *_ = compiled
            compiled[first_case]["stage"] = "D"
            with pytest.raises(
                AdmissionError, match="continuation_exact_schedule_or_routes_required"
            ):
                policy.registration(conn, authority.PROGRAM_ID, compiled, receipt)
            scope = {"id": receipt["scope_id"], **row[3]}
            policy.guard_order(conn, scope, first_case)
            with pytest.raises(AdmissionError, match="campaign_previous_case_not_terminal"):
                policy.guard_order(conn, scope, second_case)
            with pytest.raises(AdmissionError, match="continuation_schedule_binding_drift"):
                policy.guard_order(conn, scope, "another-case")

        with store.pool.connection() as conn, conn.transaction(force_rollback=True):
            revoke_extension(conn, authority.EXTENSION_ID)
            with pytest.raises(AdmissionError, match="continuation_revoked_or_receipt_corrupt"):
                authority.active(conn, authority.PROGRAM_ID)
        with store.pool.connection() as conn, conn.transaction(force_rollback=True):
            conn.execute(
                "UPDATE workspace_d5_keyed_continuations SET expires_at=expires_at+interval '1 hour' "
                "WHERE extension_id=%s",
                (authority.EXTENSION_ID,),
            )
            with pytest.raises(AdmissionError, match="continuation_revoked_or_receipt_corrupt"):
                authority.active(conn, authority.PROGRAM_ID)

        class ExpiredClock(FixtureClock):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromisoformat(receipt["expires_at"])

        with monkeypatch.context() as clock:
            clock.setattr(authority, "datetime", ExpiredClock)
            with (
                store.pool.connection() as conn,
                pytest.raises(
                    AdmissionError, match="continuation_exact_external_authorization_required"
                ),
            ):
                authority.active(conn, authority.PROGRAM_ID)
        with store.pool.connection() as conn:
            assert authority_row(conn) == retained
            assert_no_dispatch(conn, receipt, baseline)


def test_freeze_refuses_unpinned_or_non_offline_source(frozen, monkeypatch):
    store, _packet, snapshot = frozen
    with pytest.raises(AdmissionError, match="continuation_exact_snapshot_required"):
        continuation.freeze(store, {**snapshot, "history": {}})
    with (
        store.pool.connection() as conn,
        pytest.raises(AdmissionError, match="continuation_exact_52_101_126_snapshot_required"),
    ):
        authority.proposal(conn, authority.PROGRAM_ID, "9" * 64, {})
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "0")
    with pytest.raises(AdmissionError, match="continuation_freeze_offline_only"):
        continuation.freeze(store, snapshot)
