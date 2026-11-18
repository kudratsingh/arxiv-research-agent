"""Exercise the actual operator revocation route without financial/provider effects."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from src.workspace.admission import AdmissionError
from src.workspace.d5_adapter import D5Adapter
from src.workspace.d5_campaign_operator import revoke
from src.workspace.d5_continuation_authority import EXTENSION_ID, active
from src.workspace.d5_freeze import restore_input
from src.workspace.qualification_budget import census
from tests.d5_case_isolation_fixtures import fixture_campaign as fixture_campaign
from tests.d5_case_isolation_fixtures import prepared_campaign as prepared_campaign


class RecordingConnection:
    def __init__(self):
        self.queries = []

    def execute(self, query, params):
        self.queries.append((query, params))


class RecordingPool:
    def __init__(self):
        self.conn = RecordingConnection()

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
        "d5-behavior-continuation-v20",
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
