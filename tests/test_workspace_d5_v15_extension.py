"""Prospective receipt controls; real storage uses an explicit preserved snapshot.

All new authority is synthetic and restricted to disposable fixture storage.
Owner records in the snapshot are immutable history, never authority for a call.
"""

import gzip
import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from src.workspace import d5_campaign_v15_extension as extension
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign_v15_policy import LIMITS
from tests.test_workspace_d5_v14_extension_controls import MemoryConnection


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def receipt_for(proposal, *, fixture=True):
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_freeze import code_bindings

    now = datetime.now(UTC)
    return {
        "approved": True,
        "approved_by": "Synthetic test fixture",
        "approval_source": "Disposable-storage fixture; no owner authority",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=23)).isoformat(),
        "programme_expires_at": (now + timedelta(days=6)).isoformat(),
        "expiry_adjustment_approved": True,
        "budget_adjustment_approved": True,
        "capacity_amendment_approved": True,
        "historical_uncertainty_exception_approved": True,
        "transport_mode": "mock" if fixture else "provider",
        "authorization_kind": "offline_fixture" if fixture else "owner",
        "packet_digest": "a" * 64,
        "scope_id": "prospective-capacity-scope",
        "campaign_extension": deepcopy(proposal),
        "limits": deepcopy(LIMITS),
        "stages": ["B", "C", "D"],
        "case_order": [f"case-{i}" for i in range(14)],
        "code_bindings": code_bindings(),
        "adapter_binding": qualification_producer(),
        "source_bindings": {
            "versions": {"v": _digest({"v": 1})},
            "materials": {"m": _digest({"m": 1})},
        },
    }


@pytest.fixture
def validated(monkeypatch):
    parent = {
        "extension_id": "program-campaign-v6",
        "authorization_digest": "historical-v14",
        "packet_digest": "historical-packet",
        "scope_id": "historical-stopped",
        "programme_expires_at": extension.HISTORICAL_PROGRAMME_EXPIRY,
        "row_digest": "immutable-old-row",
        "stopped_scope_digest": "immutable-stopped-scope",
    }
    retained = [
        {
            "kind": "unknown_upstream_completion",
            "binding": {"job_id": "old", "hold_usd": "0.425066"},
        },
        {
            "kind": "received_http400_usage_unvalidated",
            "binding": {"job_id": "received", "hold_usd": "0.45"},
        },
    ]
    basis = {
        "contact_checkpoints": {"old": {}, "received": {}},
        "known_usd": "2.110597",
        "unknown_usd": "0.875066",
    }
    monkeypatch.setattr(extension, "parent", lambda *_: deepcopy(parent))
    monkeypatch.setattr(extension, "history", lambda *_: (["member"], deepcopy(basis)))
    monkeypatch.setattr(extension, "census", lambda *_a, **_k: deepcopy(basis))
    monkeypatch.setattr(
        "src.workspace.d5_campaign_v14_extension.retained_bindings", lambda *_: deepcopy(retained)
    )
    monkeypatch.setattr("src.workspace.d5_campaign_policy.audit_outcomes", lambda *_: None)
    proposal = extension.proposal(None, "program", "plan")
    receipt = receipt_for(proposal)
    routes = {
        "workspace_d5_fixture_marker": [(1,)],
        "workspace_versions": [("v", {"v": 1})],
        "workspace_material": [("m", {"m": 1})],
    }
    return receipt, parent, retained, basis, routes


@pytest.mark.unit
def test_proposal_binds_relative_expiry_and_funded_envelope(validated):
    receipt, _, _, _, _ = validated
    core = receipt["campaign_extension"]["core"]
    assert core["expiry_policy"] == {
        "historical_programme_expiry": "2026-11-14T07:24:01+00:00",
        "programme_max_seconds_from_approval": 604800,
        "campaign_max_seconds_from_approval": 86400,
        "requires_explicit_extension": True,
    }
    assert "programme_expiry" not in core
    assert core["limits"] == {
        "new_jobs": 64,
        "messages": 160,
        "counts": 200,
        "usd": "20",
        "concurrency": 1,
    }
    assert core["campaign_limits"] == LIMITS
    assert core["dollar_adjustment"] == {"from": "12", "to": "20", "approved": False}
    assert receipt["campaign_extension"]["approved"] is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "field",
    [
        "approved",
        "expiry_adjustment_approved",
        "budget_adjustment_approved",
        "capacity_amendment_approved",
        "historical_uncertainty_exception_approved",
    ],
)
def test_each_explicit_decision_is_required(validated, field):
    receipt, _, _, _, routes = validated
    receipt[field] = False
    with pytest.raises(AdmissionError):
        extension._validate(MemoryConnection(routes), receipt, "program")


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    [
        "blank_owner",
        "blank_source",
        "future",
        "expired",
        "stale",
        "campaign25h",
        "programme8d",
        "scope_after_programme",
        "naive",
        "nonutc",
        "missing_programme",
        "synthetic_provider",
    ],
)
def test_owner_time_and_fixture_authority_are_bounded(validated, mutation):
    receipt, _, _, _, routes = validated
    start = datetime.fromisoformat(receipt["approved_at"])
    if mutation == "blank_owner":
        receipt["approved_by"] = "  "
    elif mutation == "blank_source":
        receipt["approval_source"] = "\n"
    elif mutation == "future":
        receipt["approved_at"] = (start + timedelta(hours=1)).isoformat()
    elif mutation == "expired":
        receipt["expires_at"] = (start - timedelta(seconds=1)).isoformat()
    elif mutation == "stale":
        receipt["approved_at"] = (start - timedelta(days=8)).isoformat()
    elif mutation == "campaign25h":
        receipt["expires_at"] = (start + timedelta(hours=25)).isoformat()
    elif mutation == "programme8d":
        receipt["programme_expires_at"] = (start + timedelta(days=8)).isoformat()
    elif mutation == "scope_after_programme":
        receipt["programme_expires_at"] = (start + timedelta(hours=1)).isoformat()
    elif mutation == "naive":
        receipt["approved_at"] = start.replace(tzinfo=None).isoformat()
    elif mutation == "nonutc":
        receipt["programme_expires_at"] = (
            (start + timedelta(days=1)).isoformat().replace("+00:00", "+01:00")
        )
    elif mutation == "missing_programme":
        receipt.pop("programme_expires_at")
    else:
        receipt.update(transport_mode="provider", authorization_kind="owner")
    with pytest.raises(AdmissionError, match="external_owner_authorization_required"):
        extension._validate(MemoryConnection(routes), receipt, "program")


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    [None, "parent", "retained", "limits", "expiry_policy", "source", "history", "duplicate_case"],
)
def test_receipt_reaudits_exact_seals_history_and_sources(validated, monkeypatch, mutation):
    receipt, parent, retained, basis, routes = validated
    if mutation == "parent":
        parent["row_digest"] = "changed"
    elif mutation == "retained":
        retained[0]["binding"]["hold_usd"] = "0"
    elif mutation == "limits":
        receipt["limits"]["new_usd"] = "15"
    elif mutation == "expiry_policy":
        receipt["campaign_extension"]["core"]["expiry_policy"]["historical_programme_expiry"] = (
            "changed"
        )
    elif mutation == "source":
        routes["workspace_material"] = [("m", {"m": 2})]
    elif mutation == "history":
        basis["known_usd"] = "2.110598"
    elif mutation == "duplicate_case":
        receipt["case_order"].append("case-0")
    if mutation:
        with pytest.raises(AdmissionError):
            extension._validate(MemoryConnection(routes), receipt, "program")
    else:
        assert (
            extension._validate(MemoryConnection(routes), receipt, "program")
            == receipt["campaign_extension"]["core"]
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    [None, "scope", "authorization", "unknown", "dispatching", "foreign", "failed", "current"],
)
def test_exception_retains_two_holds_and_fences_new_uncertainty(validated, monkeypatch, mutation):
    receipt, _, _, _, _ = validated
    core = receipt["campaign_extension"]["core"]
    policy = {
        "program_id": "program",
        "d5_scope_id": receipt["scope_id"],
        "d5_authorization_digest": _digest(receipt),
    }
    if mutation == "scope":
        policy["d5_scope_id"] = "other"
    elif mutation == "authorization":
        policy["d5_authorization_digest"] = "other"
    contacts = {
        "dispatching": [("new", "running", "dispatching")],
        "foreign": [("other", "running", "running")],
        "failed": [("new", "failed", "running")],
        "current": [("new", "running", "running")],
    }.get(mutation, [])
    conn = MemoryConnection(
        {"SELECT owner": [("member",)], "SELECT id": [("new",)], "CROSS JOIN": contacts}
    )
    monkeypatch.setattr(
        extension,
        "census",
        lambda *_a, **_k: {"unknown_usd": "0.001" if mutation == "unknown" else "0"},
    )
    if mutation not in {None, "current"}:
        with pytest.raises(AdmissionError):
            extension.guard_exception(conn, policy, (receipt, core), "new")
    else:
        assert (
            extension.guard_exception(conn, policy, (receipt, core), "new")[
                "retained_liability_usd"
            ]
            == "0.875066"
        )
        assert conn.calls[1][1][1] == ["old", "received"]


def export_rows(store, name):
    root = os.environ.get("WORKSPACE_D5_CONTROL_EVIDENCE_ROOT")
    if not root:
        return
    target = Path(root) / (name + "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    records = {}
    with store.pool.connection() as conn:
        for table in (
            "workspace_evaluation_programs",
            "workspace_generation_jobs",
            "workspace_spend_reservations",
            "workspace_d5_scopes",
            "workspace_d5_campaign_extensions",
            "workspace_d5_campaign_successors",
            "workspace_d5_capacity_revisions",
            "workspace_d5_capacity_revision_revocations",
            "workspace_d5_stage_authorizations",
        ):
            records[table] = [
                r[0]
                for r in conn.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(table))
                )
            ]
    content = json.dumps(
        {
            "synthetic_new_authority": True,
            "real_provider_contacts": 0,
            "real_ledger_writes": 0,
            "rows": records,
        },
        indent=2,
        default=str,
    ).encode()
    target.write_bytes(content)
    target.with_suffix(".sha256").write_text(hashlib.sha256(content).hexdigest() + "\n")


@pytest.fixture
def copied_parent(request):
    """Install exact preserved historical rows in a new disposable test schema."""
    from src.workspace.d5_fixture import FINANCIAL_TABLES, PUBLIC_TABLES
    from tests.d5_campaign_gate import storage

    path = os.environ.get("WORKSPACE_D5_V15_PARENT_SNAPSHOT")
    if not path:
        pytest.skip("explicit preserved v15 parent snapshot required")
    captured = json.loads(gzip.decompress(Path(path).read_bytes()))
    with storage() as store:
        with store.pool.connection() as conn:
            for table in (*PUBLIC_TABLES, *FINANCIAL_TABLES):
                for row in captured["tables"][table]:
                    conn.execute(
                        sql.SQL(
                            "INSERT INTO {} SELECT * FROM jsonb_populate_record(NULL::{},%s)"
                        ).format(sql.Identifier(table), sql.Identifier(table)),
                        (Jsonb(row),),
                    )
            for table in (
                "workspace_programme_amendments",
                "workspace_programme_successor_amendments",
                "workspace_programme_third_amendments",
                "workspace_programme_capacity_amendments",
                "workspace_d5_scopes",
                "workspace_d5_stage_authorizations",
                "workspace_d5_case_runs",
                "workspace_d5_campaign_extensions",
                "workspace_d5_campaign_revocations",
                "workspace_d5_campaign_outcomes",
                "workspace_d5_campaign_successors",
                "workspace_d5_campaign_successor_revocations",
            ):
                for row in captured["records"].get(table, []):
                    conn.execute(
                        sql.SQL(
                            "INSERT INTO {} SELECT * FROM jsonb_populate_record(NULL::{},%s)"
                        ).format(sql.Identifier(table), sql.Identifier(table)),
                        (Jsonb(row),),
                    )
            conn.execute("INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only','{}')")
        try:
            yield store, captured["program_id"]
        finally:
            export_rows(store, request.node.name)


def historical_rows(store):
    with store.pool.connection() as conn:
        return [
            conn.execute(
                sql.SQL("SELECT to_jsonb(t) FROM {} t ORDER BY 1::text").format(
                    sql.Identifier(table)
                )
            ).fetchall()
            for table in (
                "workspace_generation_jobs",
                "workspace_spend_reservations",
                "workspace_d5_scopes",
                "workspace_d5_campaign_successors",
                "workspace_d5_stage_authorizations",
            )
        ]


def stored_receipt(store, pid):
    with store.pool.connection() as conn:
        receipt = receipt_for(extension.proposal(conn, pid, "prospective-plan"))
        receipt["source_bindings"] = {
            label: {
                row[0]: _digest(row[1])
                for row in conn.execute(
                    sql.SQL("SELECT {},data FROM {}").format(
                        sql.Identifier(key), sql.Identifier(table)
                    )
                )
            }
            for label, table, key in (
                ("versions", "workspace_versions", "version_id"),
                ("materials", "workspace_material", "material_id"),
            )
        }
        return receipt


@pytest.mark.integration
def test_real_storage_parent_is_stopped_exact_and_never_revalidates_old_producer(
    copied_parent, monkeypatch
):
    store, pid = copied_parent
    before = historical_rows(store)
    monkeypatch.setattr(
        "src.workspace.d5_campaign_v14_extension._validate",
        lambda *_: pytest.fail("historical producer must not be revalidated"),
    )
    with store.pool.connection() as conn:
        parent = extension.parent(conn, pid)
        members, basis = extension.history(conn, pid)
        plan = extension.proposal(conn, pid, "prospective-plan")
    assert (
        parent["authorization_digest"]
        == "60cafe94d2cd228e75010cc8d8b801c944e984e51ce67f88c7a45b77ee13749f"
    )
    assert (
        parent["packet_digest"]
        == "2ad47ade2db7f96d97ff11303b56cdd222b2980fadca37824ba2866f113accf4"
    )
    assert parent["programme_expires_at"] == extension.HISTORICAL_PROGRAMME_EXPIRY
    assert (
        basis["known_usd"] == "2.110597"
        and basis["unknown_usd"] == basis["pending_usd"] == "0.875066"
    )
    assert members and plan["approved"] is False
    assert historical_rows(store) == before


@pytest.mark.integration
def test_recording_successor_is_idempotent_append_only_and_revocable(copied_parent):
    store, pid = copied_parent
    receipt = stored_receipt(store, pid)
    before = historical_rows(store)
    result = extension.record_external(store, receipt)
    assert result["financial_rows_changed"] is False and result["provider_contacts"] == 0
    assert extension.record_external(store, receipt)["duplicate"] is True
    assert historical_rows(store) == before
    changed = deepcopy(receipt)
    changed["approval_source"] = "Different grant requires a separate versioned extension"
    with pytest.raises(AdmissionError, match="immutable_no_reapproval"):
        extension.record_external(store, changed)
    with store.pool.connection() as conn:
        assert (
            extension.active(conn, pid, receipt["campaign_extension"]["proposal_digest"])[0]
            == receipt
        )
        assert extension.active(conn, pid, "other-proposal") is None
        conn.execute(
            "INSERT INTO workspace_d5_capacity_revision_revocations(extension_id,record)VALUES(%s,%s)",
            (
                receipt["campaign_extension"]["core"]["extension_id"],
                Jsonb({"revoked": True, "synthetic": True}),
            ),
        )
    with (
        store.pool.connection() as conn,
        pytest.raises(AdmissionError, match="revoked_or_receipt_drift"),
    ):
        extension.active(conn, pid)
    with pytest.raises(AdmissionError, match="revoked_or_receipt_drift"):
        extension.record_external(store, receipt)

    assert historical_rows(store) == before


@pytest.mark.integration
@pytest.mark.parametrize("mutation", ["baseline", "reopen", "received_hold", "expiry"])
def test_storage_drift_never_activates_successor_or_changes_other_history(copied_parent, mutation):
    store, pid = copied_parent
    receipt = stored_receipt(store, pid)
    with store.pool.connection() as conn:
        if mutation == "baseline":
            conn.execute(
                "UPDATE workspace_spend_reservations SET workflow=workflow+0.000001 WHERE job_id=(SELECT job_id FROM workspace_spend_reservations WHERE workflow>0 LIMIT 1)"
            )
        elif mutation == "reopen":
            conn.execute(
                "UPDATE workspace_d5_scopes SET state='active' WHERE scope_id=%s",
                (receipt["campaign_extension"]["core"]["parent"]["scope_id"],),
            )
        elif mutation == "received_hold":
            conn.execute("UPDATE workspace_spend_reservations SET unknown=0.44 WHERE unknown=0.45")
        else:
            conn.execute(
                "UPDATE workspace_d5_campaign_successors SET expires_at=expires_at+interval '1 second'"
            )
    with pytest.raises(AdmissionError):
        extension.record_external(store, receipt)
    with store.pool.connection() as conn:
        assert (
            conn.execute("SELECT count(*) FROM workspace_d5_capacity_revisions").fetchone()[0] == 0
        )


@pytest.mark.integration
def test_migration_permits_versioned_programme_rows_but_keeps_parent_foreign_keys(copied_parent):
    store, pid = copied_parent
    receipt = stored_receipt(store, pid)
    extension.record_external(store, receipt)
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_d5_capacity_revisions SELECT extension_id||'-future',program_id,revision,predecessor_extension_id,predecessor_authorization_digest,proposal_digest||'-future',authorization_digest||'-future',packet_digest,scope_id||'-future',record,expires_at,programme_expires_at,created_at FROM workspace_d5_capacity_revisions"
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM workspace_d5_capacity_revisions WHERE program_id=%s", (pid,)
            ).fetchone()[0]
            == 2
        )
        constraints = conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='workspace_d5_capacity_revisions'::regclass AND contype='f'"
        ).fetchall()
        assert sum("workspace_d5_campaign_successors" in row[0] for row in constraints) == 2


@pytest.mark.integration
def test_explicit_new_expiry_can_outlive_old_expiry_without_renewing_parent(
    copied_parent, monkeypatch
):
    store, pid = copied_parent
    receipt = stored_receipt(store, pid)
    old_expiry = datetime.fromisoformat(
        receipt["campaign_extension"]["core"]["expiry_policy"]["historical_programme_expiry"]
    )
    instant = max(datetime.now(UTC), old_expiry + timedelta(hours=1))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant

    monkeypatch.setattr(extension, "datetime", Clock)
    receipt["approved_at"] = instant.isoformat()
    receipt["expires_at"] = (instant + timedelta(hours=23)).isoformat()
    receipt["programme_expires_at"] = (instant + timedelta(days=6)).isoformat()
    before = historical_rows(store)
    extension.record_external(store, receipt)
    with store.pool.connection() as conn:
        assert (
            extension.active(conn, pid)[0]["programme_expires_at"]
            == receipt["programme_expires_at"]
        )
        assert (
            conn.execute(
                "SELECT state FROM workspace_d5_scopes WHERE scope_id=%s",
                (receipt["campaign_extension"]["core"]["parent"]["scope_id"],),
            ).fetchone()[0]
            == "stopped"
        )
    assert historical_rows(store) == before
