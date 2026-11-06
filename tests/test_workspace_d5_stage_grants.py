"""Independent approvals after count-only execution; synthetic disposable scope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.workspace import d5_adapter as d
from src.workspace.admission import AdmissionError
from src.workspace.d5_authorization import grant_external, revoke, stage_template
from src.workspace.d5_results import QualificationResults
from tests import test_workspace_d5_adapter as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def approved_fixture(store):
    receipt = stage_template(store, "d5-test", ["B"])
    assert receipt["approved"] is False
    return {
        **receipt,
        "approved": True,
        "approved_by": "Synthetic fixture, not owner approval",
        "approved_at": datetime.now(UTC).isoformat(),
    }


async def test_measurement_only_base_requires_separate_funded_approval_without_rewriting_history(
    store, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    inputs = support.setup(store, stages=["A"])
    transport = support.Transport()
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    with pytest.raises(AdmissionError, match="stage_not_authorized"):
        adapter.start(inputs.settings["d5_request_id"])
    assert transport.calls == []
    with store.pool.connection() as conn:
        original = conn.execute(
            "SELECT authorization_digest,data FROM workspace_d5_scopes"
        ).fetchone()
    with pytest.raises(AdmissionError):
        grant_external(store, "d5-test", stage_template(store, "d5-test", ["B"]))
    receipt = approved_fixture(store)
    grant = grant_external(store, "d5-test", receipt)
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    result = await adapter.advance(job["id"])
    assert result["state"] == "ready" and len(transport.calls) == 4
    restored = QualificationResults(store).snapshot("d5-run", job["id"])
    assert restored["authorization_chain"] == [original[0], grant["authorization_digest"]]
    assert grant_external(store, "d5-test", receipt)["duplicate"] is True
    with store.pool.connection() as conn:
        current = conn.execute(
            "SELECT authorization_digest,data FROM workspace_d5_scopes"
        ).fetchone()
        assert current == original and current[1]["stages"] == ["A"]
        assert (
            conn.execute("SELECT count(*) FROM workspace_d5_stage_authorizations").fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("approved", False),
        ("approved_by", ""),
        ("stages", []),
        ("stages", ["A"]),
        ("stages", ["B", "B"]),
        ("packet_digest", "wrong"),
        ("parent_authorization_digest", "wrong"),
        ("limits", {}),
        ("members", ["different"]),
        ("case_bindings_digest", "wrong"),
        ("basis_history_digest", "wrong"),
        ("transport_mode", "provider"),
        ("grant_id", "wrong"),
        ("expires_at", "bad"),
    ],
)
async def test_stage_grants_cannot_broaden_or_reprice_the_frozen_scope(
    store, monkeypatch, field, value
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    support.setup(store, stages=["A"])
    receipt = approved_fixture(store)
    receipt[field] = value
    with pytest.raises(AdmissionError):
        grant_external(store, "d5-test", receipt)
    with store.pool.connection() as conn:
        assert (
            conn.execute("SELECT count(*) FROM workspace_d5_stage_authorizations").fetchone()[0]
            == 0
        )


async def test_stale_revoked_expired_tampered_and_unknown_stage_approvals_refuse(
    store, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    inputs = support.setup(store, stages=["A"])
    receipt = approved_fixture(store)
    grant_external(store, "d5-test", receipt)
    changed = {**receipt, "approved_by": "Another fixture"}
    with pytest.raises(AdmissionError, match="immutable"):
        grant_external(store, "d5-test", changed)
    overlap = {**receipt, "grant_id": "d5-grant-overlap"}
    with pytest.raises(AdmissionError, match="already_authorized"):
        grant_external(store, "d5-test", overlap)
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_d5_stage_authorizations SET record=jsonb_set(record,'{limits}', '{}')"
        )
    adapter = d.D5Adapter(
        store, "d5-run", inputs, transport=httpx.MockTransport(support.Transport())
    )
    with pytest.raises(AdmissionError, match="binding_drift"):
        adapter.start(inputs.settings["d5_request_id"])
    revoke(store, "d5-test")
    with pytest.raises(AdmissionError, match="inactive"):
        grant_external(store, "d5-test", receipt)


async def test_stage_grant_cannot_extend_expiry_or_hide_an_old_hold(store, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    support.setup(store, stages=["A"])
    receipt = approved_fixture(store)
    with pytest.raises(AdmissionError, match="expiry_extended"):
        grant_external(
            store,
            "d5-test",
            {
                **receipt,
                "expires_at": (
                    datetime.fromisoformat(receipt["expires_at"]) + timedelta(hours=1)
                ).isoformat(),
            },
        )
    with store.pool.connection() as conn:
        conn.execute("UPDATE workspace_spend_reservations SET unknown=0.1")
    receipt = approved_fixture(store)
    with pytest.raises(AdmissionError, match="unresolved_liability"):
        grant_external(store, "d5-test", receipt)
