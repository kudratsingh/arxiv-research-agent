"""Pure unit gates for v14 receipts and retained liabilities.

All connection rows and grants are synthetic. In-memory INSERT observations are
not database writes, activation evidence, provider measurements or qualification.
"""

import hashlib
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.workspace import d5_campaign_v14_extension as extension
from src.workspace import d5_campaign_v14_policy as policy
from src.workspace.admission import AdmissionError, _digest
from src.workspace.assistance_coverage import QUALIFICATIONS
from src.workspace.material import SourceMaterial, SourceSpan

pytestmark = pytest.mark.unit


class Rows:
    def __init__(self, values):
        self.values = values

    def fetchone(self):
        return self.values[0] if self.values else None

    def fetchall(self):
        return self.values

    def __iter__(self):
        return iter(self.values)


class MemoryConnection:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def execute(self, query, params=None):
        text = str(query)
        self.calls.append((text, params))
        for fragment, values in self.routes.items():
            if fragment in text:
                return Rows(values)
        raise AssertionError("Unexpected in-memory query: " + text)


class MemoryStore:
    def __init__(self, conn):
        self.conn = conn
        self.migrations = 0
        self.pool = SimpleNamespace(connection=self.connection)

    def migrate(self):
        self.migrations += 1

    @contextmanager
    def connection(self):
        yield self.conn


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def set_path(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


def parent_rows():
    legacy = {"programme": "historical-hash", "capacity_revocations": []}
    core = {
        "revision": "programme-consolidated-campaign-v5",
        "limits": {"new_jobs": 47, "messages": 109, "counts": 134, "usd": "10", "concurrency": 1},
        "parent": {"predecessor_seal": deepcopy(legacy)},
    }
    record = {
        "campaign_extension": {"core": core},
        "packet_digest": "old-packet",
        "scope_id": "old-stopped",
        "expires_at": (datetime.now(UTC) + timedelta(hours=12)).isoformat(),
        "approved": True,
        "capacity_amendment_approved": True,
        "historical_uncertainty_exception_approved": True,
        "code_bindings": {"historical": "never-replace-this-old-producer"},
    }
    value = {
        "record": record,
        "scope_id": record["scope_id"],
        "packet_digest": record["packet_digest"],
        "extension_id": "program-campaign-v5",
        "authorization_digest": _digest(record),
        "proposal_digest": _digest(core),
        "expires_at": record["expires_at"],
    }
    stopped = {
        "state": "stopped",
        "packet_digest": record["packet_digest"],
        "authorization_digest": value["authorization_digest"],
        "data": {"authorization_record": record},
    }
    routes = {
        "FROM workspace_d5_campaign_extensions": [(value,)],
        "FROM workspace_d5_scopes": [(stopped,)],
        "FROM workspace_d5_campaign_revocations": [],
    }
    return value, stopped, legacy, routes


def test_parent_pins_original_receipt_scope_and_producer(monkeypatch):
    value, stopped, legacy, routes = parent_rows()
    before = deepcopy((value, stopped))
    monkeypatch.setattr("src.workspace.d5_campaign_extension.predecessor_seal", lambda *_: legacy)
    found = extension.parent(MemoryConnection(routes), "program")
    assert found["row_digest"] == _digest(value)
    assert found["stopped_scope_digest"] == _digest(stopped)
    assert found["predecessor_seal"] == legacy
    assert (value, stopped) == before
    assert value["record"]["code_bindings"] == {"historical": "never-replace-this-old-producer"}


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "auth",
        "proposal",
        "revision",
        "limits",
        "packet",
        "scope_missing",
        "scope_active",
        "scope_packet",
        "approved",
        "capacity",
        "exception",
        "scope_id",
        "scope_auth",
        "scope_record",
        "expiry",
        "legacy_revocation",
        "revoked",
    ],
)
def test_parent_refuses_missing_changed_revoked_or_reopened_history(monkeypatch, mutation):
    value, stopped, legacy, routes = parent_rows()
    if mutation == "missing":
        routes["FROM workspace_d5_campaign_extensions"] = []
    elif mutation == "auth":
        value["authorization_digest"] = "changed"
    elif mutation == "proposal":
        value["proposal_digest"] = "changed"
    elif mutation in {"revision", "limits"}:
        value["record"]["campaign_extension"]["core"][mutation] = "changed"
        value["proposal_digest"] = _digest(value["record"]["campaign_extension"]["core"])
        value["authorization_digest"] = _digest(value["record"])
    elif mutation == "packet":
        value["packet_digest"] = "changed"
    elif mutation == "scope_missing":
        routes["FROM workspace_d5_scopes"] = []
    elif mutation == "scope_active":
        stopped["state"] = "active"
    elif mutation == "scope_packet":
        stopped["packet_digest"] = "changed"
    elif mutation in {"approved", "capacity", "exception"}:
        key = {
            "approved": "approved",
            "capacity": "capacity_amendment_approved",
            "exception": "historical_uncertainty_exception_approved",
        }[mutation]
        value["record"][key] = False
        value["authorization_digest"] = _digest(value["record"])
        stopped["authorization_digest"] = value["authorization_digest"]
    elif mutation == "scope_id":
        value["record"]["scope_id"] = "changed"
    elif mutation == "scope_auth":
        stopped["authorization_digest"] = "changed"
    elif mutation == "scope_record":
        stopped["data"]["authorization_record"] = {}
    elif mutation == "expiry":
        value["expires_at"] = "2030-01-01T00:00:00+00:00"
    elif mutation == "legacy_revocation":
        legacy["capacity_revocations"] = ["revoked"]
    else:
        routes["FROM workspace_d5_campaign_revocations"] = [(1,)]
    if mutation not in {"auth", "proposal"}:
        value["proposal_digest"] = _digest(value["record"]["campaign_extension"]["core"])
        value["authorization_digest"] = _digest(value["record"])
        if mutation != "scope_auth":
            stopped["authorization_digest"] = value["authorization_digest"]
    monkeypatch.setattr("src.workspace.d5_campaign_extension.predecessor_seal", lambda *_: legacy)
    with pytest.raises(AdmissionError):
        extension.parent(MemoryConnection(routes), "program")


def retained_rows():
    predecessor = {"scope_id": "old-stopped", "packet_digest": "old-packet"}
    body = {"model": "claude-sonnet-5-5", "max_tokens": 4000}
    raw = '{"type":"error","error":{"type":"invalid_request_error"}}'
    contact = {
        "state": "completed",
        "endpoint": "messages",
        "stage": "draft",
        "body": body,
        "request_digest": _digest(body),
        "response": {
            "http_status": 400,
            "complete_body": True,
            "usage_validated": False,
            "raw_body": raw,
            "body_digest": hashlib.sha256(raw.encode()).hexdigest(),
        },
    }
    count_body = {
        key: value for key, value in body.items() if key not in {"max_tokens", "temperature"}
    }
    count = {
        "state": "completed",
        "endpoint": "messages/count_tokens",
        "stage": "draft",
        "body": count_body,
        "request_digest": _digest(count_body),
        "response": {"input_tokens": 10766},
        "generation_request_digest": contact["request_digest"],
    }
    received = {
        "id": "received",
        "owner": "member",
        "state": "uncertain",
        "data": {
            "result": None,
            "adapter": {"contacts": [count, contact]},
            "sealed_input": {
                "settings": {
                    "d5_scope_id": predecessor["scope_id"],
                    "d5_packet_digest": predecessor["packet_digest"],
                    "d5_case_id": "campaign-dev-compare",
                }
            },
        },
    }
    hold = {"state": "uncertain", "unknown": "0.45", "amount": "0.45"}
    rows = [({"id": "old"}, {"unknown": "0.425066"}), (received, hold)]
    return predecessor, rows


def retained_connection(rows):
    return MemoryConnection(
        {
            "SELECT owner FROM workspace_evaluation_members": [("member",)],
            "JOIN workspace_spend_reservations": rows,
        }
    )


def bind_retained(monkeypatch, predecessor):
    monkeypatch.setattr(extension, "parent", lambda *_: predecessor)
    calls = []

    def uncertain(conn, job):
        calls.append(job)
        return {"job_id": job, "hold_usd": "0.425066", "settled": False}

    monkeypatch.setattr("src.workspace.d5_campaign_extension.uncertain_binding", uncertain)
    return calls


def test_both_distinct_holds_are_pinned_and_never_settled(monkeypatch):
    predecessor, rows = retained_rows()
    calls = bind_retained(monkeypatch, predecessor)
    before = deepcopy(rows)
    result = extension.retained_bindings(retained_connection(rows), "program")
    assert [r["kind"] for r in result] == [
        "received_http400_usage_unvalidated",
        "unknown_upstream_completion",
    ]
    received = result[0]["binding"]
    assert received["original_row_digest"] == _digest(
        {"job": rows[1][0], "reservation": rows[1][1]}
    )
    assert received["hold_usd"] == "0.45"
    assert received["http_status"] == 400 and received["complete_body"] is True
    assert (
        received["usage_validated"]
        is received["result_available"]
        is received["billing_established"]
        is received["settled"]
        is False
    )
    assert calls == ["old"] and rows == before


@pytest.mark.parametrize("count", [0, 1, 3])
def test_exactly_two_retained_reservations_required(monkeypatch, count):
    predecessor, rows = retained_rows()
    bind_retained(monkeypatch, predecessor)
    with pytest.raises(AdmissionError, match="exact_two_retained_holds_required"):
        extension.retained_bindings(retained_connection((rows * 2)[:count]), "program")


@pytest.mark.parametrize(
    "path,value",
    [
        ((0, "state"), "failed"),
        ((0, "data", "result"), {"accepted": True}),
        ((1, "state"), "settled"),
        ((1, "unknown"), "0.44"),
        ((0, "data", "adapter", "contacts"), []),
        ((0, "data", "adapter", "contacts", 0, "state"), "running"),
        ((0, "data", "adapter", "contacts", 0, "endpoint"), "messages"),
        ((0, "data", "adapter", "contacts", 1, "endpoint"), "messages/count_tokens"),
        ((0, "data", "adapter", "contacts", 1, "stage"), "check"),
        ((0, "data", "adapter", "contacts", 1, "request_digest"), "changed"),
        ((0, "data", "adapter", "contacts", 0, "generation_request_digest"), "changed"),
        ((0, "data", "adapter", "contacts", 1, "body", "model"), "claude-opus-5-5"),
        ((0, "data", "adapter", "contacts", 1, "response", "http_status"), 500),
        ((0, "data", "adapter", "contacts", 1, "response", "complete_body"), False),
        ((0, "data", "adapter", "contacts", 1, "response", "usage_validated"), True),
        ((0, "data", "adapter", "contacts", 1, "response", "raw_body"), None),
        ((0, "data", "adapter", "contacts", 1, "response", "body_digest"), "changed"),
        ((0, "data", "sealed_input", "settings", "d5_scope_id"), "changed"),
        ((0, "data", "sealed_input", "settings", "d5_packet_digest"), "changed"),
        ((0, "data", "sealed_input", "settings", "d5_case_id"), "changed"),
    ],
)
def test_received_http400_classification_requires_exact_retained_receipt(monkeypatch, path, value):
    predecessor, rows = retained_rows()
    bind_retained(monkeypatch, predecessor)
    set_path(rows[1], path, value)
    with pytest.raises(AdmissionError, match="exact_received_http400_hold_required"):
        extension.retained_bindings(retained_connection(rows), "program")


def test_two_unknown_upstream_holds_cannot_replace_distinct_received_hold(monkeypatch):
    predecessor, rows = retained_rows()
    bind_retained(monkeypatch, predecessor)
    rows[1] = ({"id": "another-old"}, {"unknown": "0.425066"})
    with pytest.raises(AdmissionError, match="distinct_liability_evidence_required"):
        extension.retained_bindings(retained_connection(rows), "program")


def historical_census():
    return {
        "generation_job_ids": ["baseline"] + [f"new-{i}" for i in range(35)],
        "messages": 68,
        "counts": 93,
        "known_usd": "1.986755",
        "pending_usd": "0.875066",
        "unknown_usd": "0.875066",
        "active_jobs": [],
        "contact_checkpoints": {},
    }


@pytest.mark.parametrize(
    "field,value",
    [
        (None, None),
        ("generation_job_ids", ["baseline"]),
        ("messages", 67),
        ("counts", 92),
        ("known_usd", "0"),
        ("pending_usd", "0.425066"),
        ("unknown_usd", "0.45"),
        ("active_jobs", ["active"]),
    ],
)
def test_history_requires_exact_stopped_35_68_93_checkpoint(monkeypatch, field, value):
    report = historical_census()
    if field:
        report[field] = value
    monkeypatch.setattr(extension, "census", lambda *_a, **_k: report)
    conn = MemoryConnection(
        {
            "SELECT owner FROM workspace_evaluation_members": [("z",), ("a",)],
            "SELECT baseline": [({"generation_job_ids": ["baseline"]},)],
        }
    )
    if field:
        with pytest.raises(AdmissionError, match="sealed_35_68_93_baseline_required"):
            extension.history(conn, "program")
    else:
        assert extension.history(conn, "program") == (["a", "z"], report)


def test_proposal_stays_inactive_retains_both_holds_and_requires_new_expiry_decision(monkeypatch):
    parent = {"expires_at": (datetime.now(UTC) + timedelta(hours=12)).isoformat()}
    liabilities = [
        {"binding": {"job_id": "old", "hold_usd": "0.425066"}},
        {"binding": {"job_id": "received", "hold_usd": "0.45"}},
    ]
    monkeypatch.setattr(extension, "parent", lambda *_: parent)
    monkeypatch.setattr(extension, "history", lambda *_: (["member"], historical_census()))
    monkeypatch.setattr(extension, "retained_bindings", lambda *_: liabilities)
    proposal = extension.proposal(None, "program", "plan")
    assert proposal["approved"] is False
    assert proposal["core"]["dollar_adjustment"] == {"from": "10", "to": "12", "approved": False}
    assert proposal["core"]["limits"] == policy.PROGRAM_LIMITS
    assert proposal["core"]["retained_exceptions"] == liabilities
    assert proposal["proposal_digest"] == _digest(proposal["core"])
    parent["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with pytest.raises(AdmissionError, match="expired_new_decision_required"):
        extension.proposal(None, "program", "plan")


@pytest.fixture
def validated_receipt(monkeypatch):
    now = datetime.now(UTC)
    parent = {
        "expires_at": (now + timedelta(hours=12)).isoformat(),
        "authorization_digest": "old-authorization",
    }
    holds = [{"binding": {"job_id": "old"}}, {"binding": {"job_id": "received"}}]
    basis = historical_census()
    core = {
        "revision": extension.REVISION,
        "program_id": "program",
        "extension_id": "program-campaign-v6",
        "limits": deepcopy(policy.PROGRAM_LIMITS),
        "campaign_limits": deepcopy(policy.LIMITS),
        "programme_expiry": parent["expires_at"],
        "parent": deepcopy(parent),
        "retained_exceptions": deepcopy(holds),
        "dollar_adjustment": {"from": "10", "to": "12", "approved": False},
        "basis_members": ["member"],
        "basis": deepcopy(basis),
        "plan_digest": "plan",
    }
    sources = {
        "versions": {"v": _digest({"version": 1})},
        "materials": {"m": _digest({"material": 1})},
    }
    receipt = {
        "campaign_extension": {"core": core, "proposal_digest": _digest(core)},
        "budget_adjustment_approved": True,
        "capacity_amendment_approved": True,
        "historical_uncertainty_exception_approved": True,
        "code_bindings": {"current": "code"},
        "adapter_binding": {"current": "adapter"},
        "limits": deepcopy(policy.LIMITS),
        "stages": ["B", "C", "D"],
        "case_order": [str(i) for i in range(14)],
        "approved": True,
        "approved_by": "Synthetic unit attribution",
        "approval_source": "Pure unit control",
        "approved_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "transport_mode": "provider",
        "authorization_kind": "owner",
        "source_bindings": sources,
        "scope_id": "d5-pure",
        "packet_digest": "packet",
    }
    monkeypatch.setattr(extension, "parent", lambda *_: parent)
    monkeypatch.setattr(extension, "retained_bindings", lambda *_: holds)
    monkeypatch.setattr(extension, "census", lambda *_a, **_k: basis)
    monkeypatch.setattr("src.workspace.d5_freeze.code_bindings", lambda: {"current": "code"})
    monkeypatch.setattr(
        "src.workspace.d5_adapter.qualification_producer", lambda: {"current": "adapter"}
    )
    monkeypatch.setattr("src.workspace.d5_campaign_policy.audit_outcomes", lambda *_: {})
    routes = {
        "workspace_d5_fixture_marker": [],
        "workspace_versions": [("v", {"version": 1})],
        "workspace_material": [("m", {"material": 1})],
    }
    return receipt, core, basis, routes


def test_exact_external_budget_receipt_and_source_checks(validated_receipt):
    receipt, core, _, routes = validated_receipt
    assert extension._validate(MemoryConnection(routes), receipt, "program") == core
    assert receipt["limits"]["usd"] == core["limits"]["usd"] == "12"


@pytest.mark.parametrize(
    "field,value",
    [
        ("budget_adjustment_approved", False),
        ("budget_adjustment_approved", 1),
        ("capacity_amendment_approved", False),
        ("historical_uncertainty_exception_approved", False),
        ("code_bindings", {}),
        ("adapter_binding", {}),
        ("limits", {}),
        ("stages", ["B"]),
        ("case_order", []),
    ],
)
def test_receipt_requires_exact_flags_producer_limits_and_schedule(validated_receipt, field, value):
    receipt, _, _, routes = validated_receipt
    receipt[field] = value
    with pytest.raises(AdmissionError, match="receipt_or_parent_binding_drift"):
        extension._validate(MemoryConnection(routes), receipt, "program")


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", "legacy"),
        ("program_id", "other"),
        ("extension_id", "other"),
        ("limits", {"usd": "10"}),
        ("campaign_limits", {}),
        ("programme_expiry", "changed"),
        ("parent", {}),
        ("retained_exceptions", []),
        ("dollar_adjustment", {"from": "10", "to": "12", "approved": True}),
    ],
)
def test_receipt_core_cannot_rebind_parent_holds_or_old_budget(validated_receipt, field, value):
    receipt, core, _, routes = validated_receipt
    core[field] = value
    receipt["campaign_extension"]["proposal_digest"] = _digest(core)
    with pytest.raises(AdmissionError, match="receipt_or_parent_binding_drift"):
        extension._validate(MemoryConnection(routes), receipt, "program")


@pytest.mark.parametrize(
    "mutation",
    [
        "approved",
        "attribution",
        "source",
        "parse",
        "naive",
        "future_start",
        "expired",
        "long",
        "parent_expiry",
    ],
)
def test_owner_authority_and_time_window_required(validated_receipt, mutation):
    receipt, _, _, routes = validated_receipt
    now = datetime.now(UTC)
    if mutation == "approved":
        receipt["approved"] = False
    elif mutation == "attribution":
        receipt["approved_by"] = ""
    elif mutation == "source":
        receipt["approval_source"] = ""
    elif mutation == "parse":
        receipt["approved_at"] = "invalid"
    elif mutation == "naive":
        receipt["approved_at"] = datetime.now().isoformat()
    elif mutation == "future_start":
        receipt["approved_at"] = (now + timedelta(minutes=1)).isoformat()
    elif mutation == "expired":
        receipt["expires_at"] = (now - timedelta(seconds=1)).isoformat()
    elif mutation == "long":
        receipt["expires_at"] = (now + timedelta(hours=25)).isoformat()
    else:
        receipt["expires_at"] = (now + timedelta(hours=13)).isoformat()
    with pytest.raises(AdmissionError, match="external_owner_authorization_required"):
        extension._validate(MemoryConnection(routes), receipt, "program")


@pytest.mark.parametrize(
    "fixture,transport,kind,accepted",
    [
        (False, "provider", "owner", True),
        (True, "mock", "offline_fixture", True),
        (True, "provider", "owner", False),
        (False, "mock", "offline_fixture", False),
        (True, "mock", "owner", False),
        (False, "provider", "offline_fixture", False),
    ],
)
def test_fixture_grants_never_open_provider_authority(
    validated_receipt, fixture, transport, kind, accepted
):
    receipt, _, _, routes = validated_receipt
    routes["workspace_d5_fixture_marker"] = [(1,)] if fixture else []
    receipt.update(transport_mode=transport, authorization_kind=kind)
    if accepted:
        extension._validate(MemoryConnection(routes), receipt, "program")
    else:
        with pytest.raises(AdmissionError, match="external_owner_authorization_required"):
            extension._validate(MemoryConnection(routes), receipt, "program")


@pytest.mark.parametrize(
    "mutation",
    ["history", "missing_version", "changed_material", "empty_sources", "proposal_digest"],
)
def test_dispatch_reaudits_historical_and_source_bindings(validated_receipt, monkeypatch, mutation):
    receipt, _, basis, routes = validated_receipt
    if mutation == "history":
        monkeypatch.setattr(extension, "census", lambda *_a, **_k: {**basis, "counts": 94})
    elif mutation == "missing_version":
        routes["workspace_versions"] = []
    elif mutation == "changed_material":
        routes["workspace_material"] = [("m", {"material": 2})]
    elif mutation == "empty_sources":
        receipt["source_bindings"] = {}
    else:
        receipt["campaign_extension"]["proposal_digest"] = "changed"
    with pytest.raises(AdmissionError):
        extension._validate(MemoryConnection(routes), receipt, "program")


def active_routes(receipt):
    return {
        "to_regclass": [(True,)],
        "FROM workspace_d5_campaign_successors": [
            (
                receipt,
                _digest(receipt),
                receipt["campaign_extension"]["proposal_digest"],
                receipt["packet_digest"],
                receipt["scope_id"],
                datetime.fromisoformat(receipt["expires_at"]),
                "program-campaign-v6",
            )
        ],
        "FROM workspace_d5_campaign_successor_revocations": [],
    }


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "no_table",
        "no_record",
        "wrong_required",
        "auth",
        "proposal",
        "packet",
        "scope",
        "expiry",
        "revoked",
    ],
)
def test_active_requires_exact_unrevoked_matching_receipt(validated_receipt, monkeypatch, mutation):
    receipt, core, _, _ = validated_receipt
    monkeypatch.setattr(extension, "_validate", lambda *_: core)
    routes = active_routes(receipt)
    required = receipt["campaign_extension"]["proposal_digest"]
    if mutation == "no_table":
        routes["to_regclass"] = [(None,)]
    elif mutation == "no_record":
        routes["FROM workspace_d5_campaign_successors"] = []
    elif mutation == "wrong_required":
        required = "another-proposal"
    elif mutation == "revoked":
        routes["FROM workspace_d5_campaign_successor_revocations"] = [(1,)]
    elif mutation:
        row = list(routes["FROM workspace_d5_campaign_successors"][0])
        index = {"auth": 1, "proposal": 2, "packet": 3, "scope": 4, "expiry": 5}[mutation]
        row[index] = datetime.now(UTC) if mutation == "expiry" else "changed"
        routes["FROM workspace_d5_campaign_successors"] = [tuple(row)]
        if mutation == "proposal":
            required = None
    if mutation in {"no_table", "no_record", "wrong_required"}:
        assert extension.active(MemoryConnection(routes), "program", required) is None
    elif mutation:
        with pytest.raises(AdmissionError, match="revoked_or_receipt_drift"):
            extension.active(MemoryConnection(routes), "program", required)
    else:
        assert extension.active(MemoryConnection(routes), "program", required) == (receipt, core)


@pytest.mark.parametrize(
    "mutation", [None, "unapproved", "duplicate", "reapproval", "census_drift"]
)
def test_recording_is_append_only_without_financial_or_stage_grants(
    validated_receipt, monkeypatch, mutation
):
    receipt, core, _, _ = validated_receipt
    monkeypatch.setattr(extension, "_validate", lambda *_: core)
    monkeypatch.setattr(
        extension, "proposal", lambda *_: {"core": {} if mutation == "census_drift" else core}
    )
    prior = (
        [(_digest(receipt) if mutation == "duplicate" else "different",)]
        if mutation in {"duplicate", "reapproval"}
        else []
    )
    conn = MemoryConnection(
        {
            "pg_advisory_xact_lock": [],
            "SELECT authorization_digest": prior,
            "INSERT INTO workspace_d5_campaign_successors": [],
        }
    )
    store = MemoryStore(conn)
    if mutation == "unapproved":
        receipt["approved"] = False
    if mutation in {"unapproved", "reapproval", "census_drift"}:
        with pytest.raises(AdmissionError):
            extension.record_external(store, receipt)
    else:
        result = extension.record_external(store, receipt)
        assert result["authorization_digest"] == _digest(receipt)
        if mutation == "duplicate":
            assert result["duplicate"] is True
        else:
            assert (
                result["financial_rows_changed"] is False
                and result["retained_liability_usd"] == "0.875066"
            )
    inserts = [q for q, _ in conn.calls if q.startswith("INSERT")]
    assert len(inserts) == (mutation is None)
    assert all("workspace_d5_campaign_successors" in q for q in inserts)
    assert store.migrations == (mutation != "unapproved")


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "scope",
        "authorization",
        "unknown",
        "dispatching",
        "foreign_running",
        "failed_current",
        "own_running",
    ],
)
def test_exception_only_excludes_named_holds_and_stops_new_uncertainty(
    validated_receipt, monkeypatch, mutation
):
    receipt, core, _, _ = validated_receipt
    policy_data = {
        "d5_scope_id": receipt["scope_id"],
        "d5_authorization_digest": _digest(receipt),
        "program_id": "program",
    }
    if mutation == "scope":
        policy_data["d5_scope_id"] = "other"
    if mutation == "authorization":
        policy_data["d5_authorization_digest"] = "other"
    contacts = {
        "dispatching": [("new", "running", "dispatching")],
        "foreign_running": [("foreign", "running", "running")],
        "failed_current": [("new", "failed", "running")],
        "own_running": [("new", "running", "running")],
    }.get(mutation, [])
    conn = MemoryConnection(
        {
            "SELECT owner FROM workspace_evaluation_members": [("member",)],
            "SELECT id FROM workspace_generation_jobs": [("new",)],
            "CROSS JOIN LATERAL": contacts,
        }
    )
    census_calls = []

    def census(_conn, owner, **kwargs):
        census_calls.append(kwargs)
        return {"unknown_usd": "0.01" if mutation == "unknown" else "0"}

    monkeypatch.setattr(extension, "census", census)
    if mutation not in {None, "own_running"}:
        with pytest.raises(AdmissionError):
            extension.guard_exception(conn, policy_data, (receipt, core), "new")
    else:
        result = extension.guard_exception(conn, policy_data, (receipt, core), "new")
        assert result["settled"] is False and result["retained_liability_usd"] == "0.875066"
        assert census_calls[0]["job_ids"] == ["new"]
        assert conn.calls[1][1][1] == ["old", "received"]


def development_control():
    settings = {
        "operation_routes": policy.ROUTES,
        "d5_scope_id": "scope",
        "d5_case_id": "case",
        "d5_request": {},
    }
    inputs = {"settings": settings, "sources": [{"material_id": "material"}]}
    digest = _digest(inputs)
    span = SourceSpan(
        "span",
        "work",
        "version",
        "material",
        "hash",
        "abstract",
        "synthetic",
        None,
        None,
        0,
        4,
        "text",
    )
    material = SourceMaterial(
        "material",
        "work",
        "version",
        "hash",
        "content",
        "abstract",
        "synthetic",
        "synthetic",
        (),
        True,
        None,
        ("text",),
        (span,),
    )
    claim = {
        "claim_id": "c1",
        "input_digest": "sha256:" + "a" * 64,
        "reason": "Synthetic unit control.",
    }
    verdict = {
        "checks": [{**claim, "decision": "unsupported"}],
        "claim_quality": [
            {
                **claim,
                "atomicity": "atomic",
                "qualifications": dict.fromkeys(QUALIFICATIONS, "retained"),
            }
        ],
        "coverage_checks": [
            {
                "part_id": "p1",
                "input_digest": "sha256:" + "b" * 64,
                "decision": "answered",
                "reason": "Synthetic unit control.",
            }
        ],
        "prose_review": "procedural_only",
        "prose_findings": [],
        "priority_review": "respected",
    }
    context = {
        "claim_inputs": [{"claim_id": "c1", "input_digest": claim["input_digest"]}],
        "coverage_inputs": [{"part_id": "p1", "input_digest": "sha256:" + "b" * 64}],
        "unscored_prose": {},
    }
    row = [digest, "job", "failed", digest, {"sealed_input": inputs, "adapter": {}}]
    binding = {"raw_verdict": verdict, "context": context, "binding": {"status": "bound"}}
    routes = {
        "FROM workspace_d5_case_runs": [tuple(row)],
        "SELECT data FROM workspace_material": [(asdict(material),)],
    }
    return row, binding, routes


@pytest.mark.parametrize("state", ["ready", "failed"])
def test_development_complete_negative_quality_is_not_broken_contract(monkeypatch, state):
    row, binding, routes = development_control()
    row[2] = state
    routes["FROM workspace_d5_case_runs"] = [tuple(row)]
    monkeypatch.setattr("src.workspace.d5_report_binding.current_check", lambda *_a, **_k: binding)
    result = policy.development_contract(MemoryConnection(routes), "scope", "case")
    assert result["contract_complete"] is True
    assert result["quality_accepted"] == (state == "ready")
    assert result["quality_is_human_qualified"] is False
    assert binding["raw_verdict"]["checks"][0]["decision"] == "unsupported"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "state",
        "job_digest",
        "sealed_digest",
        "legacy",
        "case",
        "scope",
        "missing_material",
        "missing_verdict",
        "quality_binding",
        "support_binding",
        "support_count",
        "prose_location",
    ],
)
def test_development_broken_bindings_cannot_open_evaluation(monkeypatch, mutation):
    row, binding, routes = development_control()
    if mutation == "missing":
        routes["FROM workspace_d5_case_runs"] = []
    elif mutation == "state":
        row[2] = "uncertain"
    elif mutation == "job_digest":
        row[3] = "changed"
    elif mutation == "sealed_digest":
        row[0] = row[3] = "changed"
    elif mutation in {"legacy", "case", "scope"}:
        settings = row[4]["sealed_input"]["settings"]
        settings[
            {"legacy": "operation_routes", "case": "d5_case_id", "scope": "d5_scope_id"}[mutation]
        ] = {"revision": "legacy"} if mutation == "legacy" else "other"
        row[0] = row[3] = _digest(row[4]["sealed_input"])
    elif mutation == "missing_material":
        routes["SELECT data FROM workspace_material"] = []
    elif mutation == "missing_verdict":
        binding.pop("raw_verdict")
    elif mutation == "quality_binding":
        binding["raw_verdict"]["claim_quality"][0]["input_digest"] = "changed"
    elif mutation == "support_binding":
        binding["raw_verdict"]["checks"][0]["input_digest"] = "changed"
    elif mutation == "support_count":
        binding["raw_verdict"]["checks"] = []
    else:
        binding["raw_verdict"].update(
            prose_review="abstain",
            prose_findings=[{"field": "background", "index": None, "reason": "Synthetic finding."}],
        )
    if mutation != "missing":
        routes["FROM workspace_d5_case_runs"] = [tuple(row)]
    monkeypatch.setattr("src.workspace.d5_report_binding.current_check", lambda *_a, **_k: binding)
    with pytest.raises(AdmissionError):
        policy.development_contract(MemoryConnection(routes), "scope", "case")


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_two_development_identities_required_before_evaluation(monkeypatch, count):
    monkeypatch.setattr(
        policy, "development_contract", lambda _conn, scope, key: {"scope": scope, "case": key}
    )
    bound = {
        "id": "scope",
        "cases": {**{f"dev{i}": {"stage": "B"} for i in range(count)}, "eval": {"stage": "C"}},
    }
    if count == 2:
        assert len(policy.require_development_contracts(None, bound)) == 2
    else:
        with pytest.raises(AdmissionError, match="two_development_contracts_required"):
            policy.require_development_contracts(None, bound)


def test_new_route_does_not_enable_legacy_or_mutate_legacy_caps():
    from src.workspace.d5_campaign_policy import LIMITS as legacy_limits
    from src.workspace.d5_operations import ROUTES as legacy_routes

    assert policy.enabled({"operation_routes": policy.ROUTES})
    assert not policy.enabled({}) and not policy.enabled({"operation_routes": legacy_routes})
    assert legacy_limits["usd"] == "10" and policy.LIMITS["usd"] == "12"
    assert legacy_routes["check_recheck_probe"]["output_tokens"] == 3200
    assert policy.ROUTES["check_recheck_probe"]["output_tokens"] == 8000
    assert policy.ROUTES["check_recheck_probe"]["effort"] == "high"


@pytest.mark.parametrize(
    "mutation",
    [
        "request_digest",
        "different_body",
        "missing_body",
        "missing_response",
        "missing_tokens",
        "float",
        "bool",
        "negative",
        "over_cap",
    ],
)
def test_retained_count_requires_exact_request_and_valid_bounded_integer_usage(
    monkeypatch, mutation
):
    predecessor, rows = retained_rows()
    bind_retained(monkeypatch, predecessor)
    count = rows[1][0]["data"]["adapter"]["contacts"][0]
    if mutation == "request_digest":
        count["request_digest"] = "changed"
    elif mutation == "different_body":
        count["body"] = {"model": "different"}
        count["request_digest"] = _digest(count["body"])
    elif mutation == "missing_body":
        count.pop("body")
    elif mutation == "missing_response":
        count.pop("response")
    elif mutation == "missing_tokens":
        count["response"] = {}
    else:
        count["response"]["input_tokens"] = {
            "float": 1.5,
            "bool": True,
            "negative": -1,
            "over_cap": 16001,
        }[mutation]
    with pytest.raises(AdmissionError, match="exact_received_http400_hold_required"):
        extension.retained_bindings(retained_connection(rows), "program")


@pytest.mark.parametrize("tokens", [0, 16000])
def test_retained_count_keeps_the_historical_integer_token_bound(monkeypatch, tokens):
    predecessor, rows = retained_rows()
    bind_retained(monkeypatch, predecessor)
    rows[1][0]["data"]["adapter"]["contacts"][0]["response"]["input_tokens"] = tokens
    assert len(extension.retained_bindings(retained_connection(rows), "program")) == 2


def freeze_cli_control(monkeypatch, verb, *, invalid=None):
    from argparse import Namespace
    from pathlib import Path

    from src.workspace import d5_campaign as campaign

    args = Namespace(
        verb=verb,
        packet=Path("synthetic-packet"),
        snapshot=Path("synthetic-snapshot"),
        out=None,
        fixture_repair_all=False,
    )
    if invalid == "snapshot":
        args.snapshot = None
    elif invalid == "offline":
        monkeypatch.delenv("WORKSPACE_D5_OFFLINE")
    elif invalid == "key":
        monkeypatch.setenv("ANTHROPIC_API_KEY", "invalid-unit-sentinel")
    calls = []
    store = MemoryStore(MemoryConnection({}))

    @contextmanager
    def database(_):
        yield store.pool

    monkeypatch.setattr("argparse.ArgumentParser.parse_args", lambda _: args)
    monkeypatch.setenv("D5_POSTGRES_URL", "pure-no-network")
    monkeypatch.setattr("src.workspace.d5_benchmark.database", database)
    monkeypatch.setattr("src.workspace.d5_benchmark.read", lambda _: {"synthetic": "snapshot"})
    monkeypatch.setattr(
        "src.workspace.d5_benchmark.write", lambda path, value: calls.append(("write", value))
    )
    monkeypatch.setattr(
        "src.workspace.d5_fixture.install", lambda *_a, **kw: calls.append(("install", kw))
    )
    monkeypatch.setattr("src.workspace.d5_campaign_packet.freeze", lambda *_: {"derived": "legacy"})
    monkeypatch.setattr(
        "src.workspace.d5_campaign_v14_packet.freeze", lambda *_: {"derived": "v14"}
    )
    if invalid:
        with pytest.raises(AdmissionError, match="freeze_offline_snapshot_required"):
            campaign.main()
        assert calls == []
    else:
        campaign.main()
        assert calls == [
            ("install", {"fixture": True}),
            ("write", {"derived": "v14" if verb == "freeze-v14" else "legacy"}),
        ]


@pytest.mark.parametrize("verb", ["freeze", "freeze-v14"])
def test_freeze_cli_preserves_explicit_legacy_and_successor_dispatch(monkeypatch, verb):
    freeze_cli_control(monkeypatch, verb)


@pytest.mark.parametrize("invalid", ["snapshot", "offline", "key"])
def test_successor_freeze_cli_requires_offline_disabled_key_snapshot(monkeypatch, invalid):
    freeze_cli_control(monkeypatch, "freeze-v14", invalid=invalid)
