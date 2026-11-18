"""Exercise the actual operator revocation route without financial/provider effects."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from src.workspace import d5_continuation_authority as authority
from src.workspace import d5_continuation_packet as continuation
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import D5Adapter
from src.workspace.d5_campaign_operator import revoke
from src.workspace.d5_continuation_authority import EXTENSION_ID, active
from src.workspace.d5_freeze import restore_input
from src.workspace.qualification_budget import census
from tests.d5_case_isolation_fixtures import fixture_campaign as fixture_campaign
from tests.d5_case_isolation_fixtures import prepared_campaign as prepared_campaign


class RecordingConnection:
    def __init__(self, grant):
        self.queries = []
        self.grant = grant
        self.scope = None
        self.revocation = None

    def execute(self, query, params):
        self.queries.append((query, params))
        if query.startswith("SELECT program_id,record"):
            return SimpleNamespace(fetchone=lambda: self.grant)
        if query.startswith("SELECT packet_digest,authorization_digest,data"):
            return SimpleNamespace(fetchone=lambda: self.scope)
        if (
            query.startswith("INSERT INTO workspace_d5_keyed_continuation_revocations")
            and self.revocation is None
        ):
            self.revocation = params[1].obj
        return None


class RecordingPool:
    def __init__(self, grant=None):
        self.conn = RecordingConnection(grant)

    @contextmanager
    def connection(self):
        yield self.conn


def descriptor(revision):
    return {
        "revision": revision,
        "packet_digest": "a" * 64,
        "program_id": "synthetic",
        "campaign_extension": {"core": {"extension_id": "synthetic-extension"}},
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "revision",
    [
        "d5-keyed-machine-campaign-v16",
        "d5-comparison-machine-campaign-v19",
    ],
)
def test_actual_operator_targets_keyed_append_only_receipt(revision):
    store = SimpleNamespace(pool=RecordingPool())
    packet = descriptor(revision)
    result = revoke(
        store,
        packet,
        {
            "packet_digest": packet["packet_digest"],
            "scope_id": "d5-" + "a" * 24,
            "approved_by": "Synthetic operator",
        },
    )
    query, values = store.pool.conn.queries[-1]
    assert query.startswith("INSERT INTO workspace_d5_keyed_continuation_revocations ")
    assert values[0] == "synthetic-extension"
    assert values[1].obj["revoked_by"] == "Synthetic operator"
    assert result == {"revoked": True, "provider_contacts": 0}


def v20_revocation_fixture():
    core = {
        "extension_id": EXTENSION_ID,
        "program_id": authority.PROGRAM_ID,
        "revision": authority.AUTHORITY_REVISION,
        "capacity_ancestor": {"extension_id": "old-ancestor", "authorization_digest": "old-digest"},
    }
    extension = {"core": core, "proposal_digest": _digest(core), "approved": False}
    packet = {
        "revision": authority.REVISION,
        "program_id": authority.PROGRAM_ID,
        "campaign_extension": extension,
        "continuation_producer": {"archived": "different-from-current"},
    }
    packet["packet_digest"] = _digest(packet)
    digest = packet["packet_digest"]
    scope = "d5-" + digest[:24]
    until = datetime(2020, 1, 1, tzinfo=UTC)
    receipt = {
        "approved": True,
        "campaign_revision": authority.REVISION,
        "scope_id": scope,
        "packet_digest": digest,
        "campaign_extension": extension,
        "expires_at": until.isoformat(),
        "programme_expires_at": until.isoformat(),
        "case_bindings_digest": "bound-in-fixture",
    }
    row = (
        authority.PROGRAM_ID,
        receipt,
        _digest(receipt),
        extension["proposal_digest"],
        digest,
        scope,
        until,
        until,
        "old-ancestor",
        "old-digest",
    )
    request = {"approved_by": "  Synthetic operator  ", "packet_digest": digest, "scope_id": scope}
    return packet, request, row


@pytest.mark.unit
def test_v20_authority_only_revocation_uses_exact_stored_grant_even_after_drift():
    packet, request, row = v20_revocation_fixture()
    store = SimpleNamespace(pool=RecordingPool(row))
    assert revoke(store, packet, request) == {"revoked": True, "provider_contacts": 0}
    retained = store.pool.conn.revocation
    assert retained["revoked_by"] == "Synthetic operator"
    assert retained["packet_digest"] == packet["packet_digest"]
    assert retained["authorization_digest"] == row[2]
    assert retained["scope_id"] == request["scope_id"]
    assert retained["proposal_digest"] == row[3]
    assert store.pool.conn.queries[0][1] == ("d5:" + request["scope_id"],)
    assert store.pool.conn.queries[1][1] == ("evaluation:" + authority.PROGRAM_ID,)
    query, params = store.pool.conn.queries[-1]
    assert query.startswith("INSERT INTO workspace_d5_keyed_continuation_revocations ")
    assert params[0] == EXTENSION_ID
    revoke(store, packet, request)
    assert store.pool.conn.revocation == retained


@pytest.mark.unit
@pytest.mark.parametrize(
    ("variant", "reason"),
    [
        ("whitespace", "campaign_revocation_attribution_required"),
        ("self_digest", "continuation_revocation_packet_binding_drift"),
        ("other_extension", "continuation_revocation_packet_binding_drift"),
        ("missing_grant", "continuation_revocation_recorded_grant_required"),
        ("invalid_grant_record_digest", "continuation_revocation_recorded_grant_drift"),
        ("stored_grant_scope_mismatch", "continuation_revocation_recorded_grant_drift"),
        ("different_packet_same_slot", "continuation_revocation_recorded_grant_drift"),
    ],
)
def test_v20_revocation_refuses_unbound_packet_or_stored_grant(variant, reason):
    packet, request, row = v20_revocation_fixture()
    if variant == "whitespace":
        request["approved_by"] = "  "
    elif variant == "self_digest":
        packet["continuation_producer"] = {"changed": True}
    elif variant in {"other_extension", "different_packet_same_slot"}:
        if variant == "other_extension":
            core = packet["campaign_extension"]["core"]
            core["extension_id"] = authority.PROGRAM_ID + "-comparison-v19"
            packet["campaign_extension"]["proposal_digest"] = _digest(core)
        else:
            packet["continuation_producer"] = {"different": True}
        packet["packet_digest"] = _digest({k: v for k, v in packet.items() if k != "packet_digest"})
        request.update(
            packet_digest=packet["packet_digest"], scope_id="d5-" + packet["packet_digest"][:24]
        )
    elif variant == "missing_grant":
        row = None
    elif variant == "invalid_grant_record_digest":
        row = (*row[:2], "different-receipt-digest", *row[3:])
    elif variant == "stored_grant_scope_mismatch":
        row = (*row[:5], "d5-another-scope", *row[6:])
    store = SimpleNamespace(pool=RecordingPool(row))
    with pytest.raises(AdmissionError, match=reason):
        revoke(store, packet, request)
    assert store.pool.conn.revocation is None
    assert all(not query.startswith("INSERT") for query, _ in store.pool.conn.queries)


@pytest.mark.unit
def test_scope_mismatch_does_not_write_any_operator_record():
    store = SimpleNamespace(pool=RecordingPool())
    packet = descriptor("d5-behavior-continuation-v20")
    with pytest.raises(AdmissionError, match="revocation_scope_binding"):
        revoke(
            store,
            packet,
            {
                "packet_digest": packet["packet_digest"],
                "scope_id": "other",
                "approved_by": "Synthetic operator",
            },
        )
    assert store.pool.conn.queries == []


@pytest.mark.integration
def test_real_operator_revocation_stops_adapter_without_dispatch(fixture_campaign):
    store, packet, compiled = fixture_campaign
    entry = next(iter(compiled.values()))
    owner = entry["owner"]
    with store.pool.connection() as conn:
        before = census(conn, owner)
    authorization = {
        "packet_digest": packet["packet_digest"],
        "scope_id": "d5-" + packet["packet_digest"][:24],
        "approved_by": "Synthetic operator revocation regression",
    }
    assert revoke(store, packet, authorization)["provider_contacts"] == 0
    with store.pool.connection() as conn:
        record = conn.execute(
            "SELECT record FROM workspace_d5_keyed_continuation_revocations WHERE extension_id=%s",
            (EXTENSION_ID,),
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT 1 FROM workspace_d5_capacity_revision_revocations WHERE extension_id=%s",
            (EXTENSION_ID,),
        ).fetchone()
        with pytest.raises(AdmissionError, match="continuation_revoked_or_receipt_corrupt"):
            active(conn, packet["program_id"], packet["campaign_extension"]["proposal_digest"])
    original = deepcopy(record)
    revoke(store, packet, authorization)
    contacts = []
    adapter = D5Adapter(
        store,
        owner,
        restore_input(entry["input"]),
        transport=httpx.MockTransport(lambda request: contacts.append(request)),
    )
    with pytest.raises(AdmissionError, match="continuation_revoked_or_receipt_corrupt"):
        adapter.start(entry["input"]["settings"]["d5_request_id"])
    with store.pool.connection() as conn:
        assert census(conn, owner) == before
        assert (
            conn.execute(
                "SELECT record FROM workspace_d5_keyed_continuation_revocations WHERE extension_id=%s",
                (EXTENSION_ID,),
            ).fetchone()[0]
            == original
        )
    assert contacts == []


@pytest.mark.integration
def test_real_expired_authority_only_grant_can_be_revoked_during_producer_drift(
    prepared_campaign,
    monkeypatch,
):
    store, packet = prepared_campaign
    now = datetime.now(UTC)
    expiry = min(now + timedelta(hours=2), datetime.fromisoformat(authority.PROGRAMME_EXPIRY))
    receipt = continuation.template(packet)
    receipt.update(
        approved=True,
        approved_by="Synthetic authority-only fixture",
        approved_at=now.isoformat(),
        approval_source="Disposable Postgres test",
        expires_at=expiry.isoformat(),
        authorization_kind="offline_fixture",
        transport_mode="mock",
        historical_uncertainty_exception_approved=True,
    )
    authority.record_external(store, receipt, packet=packet)
    with store.pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM workspace_d5_scopes WHERE scope_id=%s", (receipt["scope_id"],)
            ).fetchone()
            is None
        )
        old = conn.execute(
            "SELECT record,authorization_digest,expires_at FROM workspace_d5_keyed_continuations "
            "WHERE extension_id=%s",
            (EXTENSION_ID,),
        ).fetchone()

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return expiry + timedelta(minutes=1)

    def changed_producer():
        raise AssertionError("revocation must use stored authority, not the current producer")

    monkeypatch.setattr(authority, "datetime", ExpiredClock)
    monkeypatch.setattr(continuation, "producer_bindings", changed_producer)
    request = {
        "approved_by": " Synthetic operator ",
        "packet_digest": receipt["packet_digest"],
        "scope_id": receipt["scope_id"],
    }
    assert revoke(store, packet, request) == {"revoked": True, "provider_contacts": 0}
    with store.pool.connection() as conn:
        revocation = conn.execute(
            "SELECT record FROM workspace_d5_keyed_continuation_revocations WHERE extension_id=%s",
            (EXTENSION_ID,),
        ).fetchone()[0]
        assert revocation["revoked_by"] == "Synthetic operator"
        assert revocation["authorization_digest"] == _digest(receipt)
    revoke(store, packet, request)
    with store.pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT record FROM workspace_d5_keyed_continuation_revocations WHERE extension_id=%s",
                (EXTENSION_ID,),
            ).fetchone()[0]
            == revocation
        )
        assert (
            conn.execute(
                "SELECT record,authorization_digest,expires_at FROM workspace_d5_keyed_continuations "
                "WHERE extension_id=%s",
                (EXTENSION_ID,),
            ).fetchone()
            == old
        )
        assert (
            conn.execute(
                "SELECT 1 FROM workspace_d5_case_runs WHERE scope_id=%s", (receipt["scope_id"],)
            ).fetchone()
            is None
        )
        assert (
            conn.execute(
                "SELECT 1 FROM workspace_d5_scopes WHERE scope_id=%s", (receipt["scope_id"],)
            ).fetchone()
            is None
        )


@pytest.mark.unit
def test_generic_plan_digest_uses_complete_continuation_projection(monkeypatch):
    from src.workspace import d5_campaign_packet, d5_continuation_packet

    packet = descriptor("d5-behavior-continuation-v20")
    seen = []

    def prospective(value):
        seen.append(value)
        return "synthetic-complete-plan-digest"

    monkeypatch.setattr(d5_continuation_packet, "plan_digest", prospective)
    assert d5_campaign_packet.plan_digest(packet) == "synthetic-complete-plan-digest"
    assert seen == [packet]
