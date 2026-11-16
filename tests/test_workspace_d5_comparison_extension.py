"""Offline v19 continuation binding and no-approval refusal tests."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from src.workspace import d5_campaign_v19_extension as extension
from src.workspace.admission import AdmissionError, _digest

pytestmark = pytest.mark.unit


@pytest.fixture
def snapshot(monkeypatch):
    members = ["d5-synthetic-v19-basis"]
    history = {
        "generation_job_ids": ["synthetic-" + str(i) for i in range(46)],
        "messages": 80,
        "counts": 105,
        "known_usd": "2.533843",
        "pending_usd": "2.275066",
        "unknown_usd": "2.275066",
        "active_jobs": [],
        "contact_checkpoints": {},
    }
    parent = {
        "extension_id": "synthetic-v15-parent",
        "authorization_digest": "synthetic-owner-receipt",
        "record": {
            "campaign_extension": {
                "core": {"parent": {"predecessor_seal": {"synthetic_ancestor": "unchanged"}}}
            }
        },
    }
    scope = {"scope_id": extension.SCOPE_ID, "state": "stopped", "synthetic": True}
    jobs, holds = [], []
    for i, amount in enumerate(("0.425066", "0.45", "1.20", "0.20")):
        data = {"synthetic": True, "case": i}
        jid = "synthetic-hold-" + str(i)
        jobs.append({"id": jid, "data": data})
        holds.append(
            {
                "job_id": jid,
                "owner": members[0],
                "state": "uncertain",
                "amount": amount,
                "unknown": amount,
                "data_digest": _digest(data),
            }
        )
    value = {
        "programme": parent,
        "historical_scopes": [scope],
        "history": history,
        "members": members,
        "programme_baseline": {"generation_job_ids": []},
        "retained_liabilities": holds,
        "tables": {"workspace_generation_jobs": jobs},
        "provenance": "SYNTHETIC unit stand-in, never live authority",
    }
    for name, data in (
        ("SNAPSHOT_DIGEST", value),
        ("PARENT_DIGEST", parent),
        ("SCOPE_DIGEST", scope),
        ("HISTORY_DIGEST", history),
        ("BASIS_MEMBERS_DIGEST", members),
        ("HOLDS_DIGEST", holds),
    ):
        monkeypatch.setattr(extension, name, _digest(data))
    monkeypatch.setattr(
        extension, "_predecessor_seal", lambda conn: {"synthetic_ancestor": "unchanged"}
    )
    monkeypatch.setattr(extension, "_audit_campaign_ancestors", lambda conn, parent: None)
    monkeypatch.setattr(
        extension,
        "_expected_receipt_bindings",
        lambda: {
            "code_bindings": {"synthetic_code": "unchanged"},
            "adapter_binding": {"synthetic_adapter": "unchanged"},
            "source_bindings": {"synthetic_source": "unchanged"},
            "case_order": ["synthetic-case-" + str(i) for i in range(14)],
        },
    )
    return value


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class ReadOnly:
    def __init__(self, data):
        self.data = data
        self.statements = []

    def execute(self, query, params=None):
        self.statements.append(query)
        assert query.startswith("SELECT ")
        if "to_regclass('workspace_d5_fixture_marker')" in query:
            return Rows([(None,)])
        if "workspace_d5_capacity_revisions t" in query:
            return Rows([(self.data["programme"],)])
        if "workspace_d5_scopes t" in query:
            return Rows(
                [
                    (
                        next(
                            x
                            for x in self.data["historical_scopes"]
                            if x["scope_id"] == extension.SCOPE_ID
                        ),
                    )
                ]
            )
        if "workspace_d5_capacity_revision_revocations" in query:
            return Rows([])
        if "SELECT owner FROM workspace_evaluation_members" in query:
            return Rows([(x,) for x in self.data["members"]])
        if "r.unknown>0" in query:
            jobs = {x["id"]: x for x in self.data["tables"]["workspace_generation_jobs"]}
            return Rows(
                [
                    (
                        h["job_id"],
                        h["owner"],
                        h["state"],
                        h["amount"],
                        h["unknown"],
                        jobs[h["job_id"]]["data"],
                    )
                    for h in self.data["retained_liabilities"]
                ]
            )
        raise AssertionError(query)


@pytest.fixture
def prepared(snapshot, monkeypatch):
    conn = ReadOnly(snapshot)
    monkeypatch.setattr(extension, "census", lambda *a, **kw: deepcopy(snapshot["history"]))
    value = extension.proposal(conn, extension.PROGRAM_ID, "sealed-plan", snapshot)
    return conn, value


def test_pinned_snapshot_creates_only_unapproved_proposal(prepared):
    conn, value = prepared
    assert value["approved"] is False
    assert value["proposal_digest"] == _digest(value["core"])
    assert value["core"]["limits"] == {
        "new_jobs": 64,
        "messages": 160,
        "counts": 200,
        "usd": "22",
        "concurrency": 1,
    }
    assert value["core"]["period_limits"] == {"day_usd": "22", "month_usd": "22"}
    assert len(value["core"]["retained_exceptions"]) == 4
    assert all(x.startswith("SELECT ") for x in conn.statements)


def test_unapproved_receipt_never_touches_store():
    with pytest.raises(AdmissionError, match="explicit_owner"):
        extension.record_external(None, {"approved": False})


@pytest.mark.parametrize(
    "field, replacement",
    [
        ("limits", {}),
        ("period_limits", {}),
        ("programme_expiry", "2030-01-01T00:00:00+00:00"),
        ("retained_exceptions", []),
    ],
)
def test_even_rehashed_policy_or_hold_drift_is_rejected(prepared, field, replacement):
    conn, value = prepared
    value["core"][field] = replacement
    value["proposal_digest"] = _digest(value["core"])
    with pytest.raises(AdmissionError, match="drift"):
        extension.validate_proposal(conn, value)


def test_snapshot_or_live_census_drift_is_rejected(snapshot, monkeypatch):
    conn = ReadOnly(snapshot)
    altered = deepcopy(snapshot)
    altered["history"]["counts"] += 1
    with pytest.raises(AdmissionError, match="drift"):
        extension.proposal(conn, extension.PROGRAM_ID, "sealed-plan", altered)
    changed = deepcopy(snapshot["history"])
    changed["messages"] += 1
    monkeypatch.setattr(extension, "census", lambda *a, **kw: changed)
    with pytest.raises(AdmissionError, match="drift"):
        extension.proposal(conn, extension.PROGRAM_ID, "sealed-plan", snapshot)


def valid_receipt(proposal):
    value = deepcopy(proposal)
    value["core"]["plan_digest"] = "a" * 64
    value["proposal_digest"] = _digest(value["core"])
    now = datetime.now(UTC)
    packet = "b" * 64
    return {
        "approved": True,
        "approved_by": "Synthetic unit fixture identity only",
        "approval_source": "Synthetic unit test, never recorded as real authority",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "programme_expires_at": extension.PROGRAMME_EXPIRY,
        "authorization_kind": "owner",
        "transport_mode": "provider",
        "budget_adjustment_approved": True,
        "historical_uncertainty_exception_approved": True,
        "campaign_extension": value,
        "limits": extension.CAMPAIGN_LIMITS,
        "programme_limits": extension.LIMITS,
        "period_limits": extension.PERIOD_LIMITS,
        "stages": ["B", "C", "D"],
        "packet_digest": packet,
        "scope_id": "d5-" + packet[:24],
        "members": ["d5-campaign-" + packet[:16] + "-run"],
        "case_bindings_digest": "c" * 64,
        **extension._expected_receipt_bindings(),
    }


@pytest.mark.parametrize(
    "field",
    [
        "scope_id",
        "packet_digest",
        "case_bindings_digest",
        "members",
        "code_bindings",
        "adapter_binding",
        "source_bindings",
        "case_order",
    ],
)
def test_primitive_rejects_missing_or_changed_packet_producer_source_and_case_bindings(
    prepared, field
):
    conn, value = prepared
    receipt = valid_receipt(value)
    extension._validate_receipt(conn, receipt, fresh=True)
    if field == "case_order":
        receipt[field] = list(reversed(receipt[field]))
    elif field in {"scope_id", "packet_digest", "case_bindings_digest"}:
        receipt[field] = "synthetic-changed"
    else:
        receipt.pop(field)
    with pytest.raises(AdmissionError, match="external_owner_authorization"):
        extension._validate_receipt(conn, receipt, fresh=True)
    assert all(q.startswith("SELECT ") for q in conn.statements)


def test_ancestor_revocation_rejects_unchanged_pinned_parent_row(prepared, monkeypatch):
    conn, value = prepared
    pinned = deepcopy(conn.data["programme"])
    monkeypatch.setattr(
        extension, "_predecessor_seal", lambda conn: {"synthetic_ancestor": "new revocation"}
    )
    with pytest.raises(AdmissionError, match="predecessor_or_revocation_drift"):
        extension.validate_proposal(conn, value)
    assert conn.data["programme"] == pinned


class Recording(ReadOnly):
    """In-memory primitive test double; never a live or fixture database grant."""

    def __init__(self, data):
        super().__init__(data)
        self.receipt = None
        self.inserts = 0
        self.revoked = False

    def execute(self, query, params=None):
        if "pg_advisory_xact_lock" in query:
            self.statements.append(query)
            return Rows([(None,)])
        if "to_regclass('workspace_d5_keyed_continuations')" in query:
            return Rows([(True,)])
        if "workspace_d5_keyed_continuation_revocations" in query:
            return Rows([(1,)] if self.revoked else [])
        if query.startswith("SELECT authorization_digest FROM workspace_d5_keyed_continuations"):
            return Rows([(_digest(self.receipt),)] if self.receipt else [])
        if query.startswith(
            "SELECT record,authorization_digest,proposal_digest,packet_digest,scope_id"
        ):
            if self.receipt is None:
                return Rows([])
            receipt = self.receipt
            core = receipt["campaign_extension"]["core"]
            return Rows(
                [
                    (
                        receipt,
                        _digest(receipt),
                        receipt["campaign_extension"]["proposal_digest"],
                        receipt["packet_digest"],
                        receipt["scope_id"],
                        datetime.fromisoformat(receipt["expires_at"]),
                        datetime.fromisoformat(extension.PROGRAMME_EXPIRY),
                        core["parent"]["extension_id"],
                        core["parent"]["authorization_digest"],
                    )
                ]
            )
        if query.startswith("INSERT INTO workspace_d5_keyed_continuations"):
            self.statements.append(query)
            self.inserts += 1
            self.receipt = deepcopy(params[8].obj)
            return Rows([])
        return super().execute(query, params)

    @contextmanager
    def connection(self):
        yield self

    @property
    def pool(self):
        return self


def test_primitive_exact_re_record_is_idempotent_after_progress_without_renewal(
    prepared, monkeypatch
):
    old, proposal = prepared
    conn = Recording(deepcopy(old.data))
    receipt = valid_receipt(proposal)
    from src.workspace import d5_campaign_operator

    packet = {"revision": "d5-comparison-machine-campaign-v19"}
    expected_template = deepcopy(receipt)
    monkeypatch.setattr(d5_campaign_operator, "template", lambda value: deepcopy(expected_template))
    original_expiry = receipt["expires_at"]
    extension.record_external(conn, receipt, packet=packet)
    baseline = deepcopy(conn.data["history"])
    conn.data["members"].append(receipt["members"][0])
    full = {**baseline, "messages": baseline["messages"] + 4}
    calls = []

    def census(*args, **kwargs):
        calls.append(kwargs.get("job_ids"))
        return deepcopy(baseline if kwargs.get("job_ids") is not None else full)

    monkeypatch.setattr(extension, "census", census)
    result = extension.record_external(conn, receipt, packet=packet)
    assert result["duplicate"] is True and conn.inserts == 1
    assert calls and all(ids is not None for ids in calls)
    assert conn.receipt["expires_at"] == original_expiry
    changed = {**receipt, "approved_at": datetime.now(UTC).isoformat()}
    with pytest.raises(AdmissionError, match="immutable_or_revoked"):
        extension.record_external(conn, changed, packet=packet)
    assert conn.inserts == 1


@pytest.mark.parametrize("stop", ["expired", "revoked"])
def test_existing_expired_or_revoked_grant_cannot_be_re_recorded(prepared, stop, monkeypatch):
    old, proposal = prepared
    conn = Recording(deepcopy(old.data))
    receipt = valid_receipt(proposal)
    from src.workspace import d5_campaign_operator

    packet = {"revision": "d5-comparison-machine-campaign-v19"}
    expected_template = deepcopy(receipt)
    monkeypatch.setattr(d5_campaign_operator, "template", lambda value: deepcopy(expected_template))
    if stop == "expired":
        now = datetime.now(UTC)
        receipt.update(
            approved_at=(now - timedelta(hours=2)).isoformat(),
            expires_at=(now - timedelta(hours=1)).isoformat(),
        )
    conn.receipt = deepcopy(receipt)
    conn.revoked = stop == "revoked"
    with pytest.raises(AdmissionError, match="external_owner_authorization|revoked"):
        extension.record_external(conn, receipt, packet=packet)
    assert conn.inserts == 0
    assert conn.receipt == receipt


def test_unmarked_storage_refuses_synthetic_fixture_identity(prepared, monkeypatch):
    conn, proposal = prepared
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    receipt = valid_receipt(proposal)
    receipt.update(authorization_kind="offline_fixture", transport_mode="mock")
    with pytest.raises(AdmissionError, match="external_owner_authorization"):
        extension._validate_receipt(conn, receipt, fresh=True)


def campaign_ancestor_fixture():
    """Synthetic immutable chain, built from oldest to newest without cycles."""
    scopes, rows = {}, {}
    prior = {"predecessor_seal": {"synthetic_base": "unchanged"}}
    for number, table in (
        (13, "workspace_d5_campaign_extensions"),
        (14, "workspace_d5_campaign_successors"),
        (15, "workspace_d5_capacity_revisions"),
    ):
        scope_id = "synthetic-scope-" + str(number)
        packet, authorization = (
            "synthetic-packet-" + str(number),
            "synthetic-authorization-" + str(number),
        )
        scope = {
            "scope_id": scope_id,
            "state": "stopped",
            "packet_digest": packet,
            "authorization_digest": authorization,
        }
        row = {
            "program_id": extension.PROGRAM_ID,
            "extension_id": "synthetic-extension-" + str(number),
            "scope_id": scope_id,
            "packet_digest": packet,
            "authorization_digest": authorization,
            "record": {"campaign_extension": {"core": {"parent": prior}}},
        }
        scopes[scope_id], rows[table] = scope, row
        prior = {
            "row_digest": _digest(row),
            "scope_id": scope_id,
            "stopped_scope_digest": _digest(scope),
        }
    return rows, scopes


class AncestorReads:
    def __init__(self, rows, scopes):
        self.rows, self.scopes = rows, scopes
        self.revoked = set()
        self.statements = []

    def execute(self, query, params=None):
        text = query if isinstance(query, str) else query.as_string()
        self.statements.append(text)
        assert text.startswith("SELECT ")
        if "workspace_d5_scopes t" in text:
            value = self.scopes.get(params[0])
            return Rows([(value,)] if value is not None else [])
        if "revocations" in text:
            return Rows([(1,)] if any(table in text for table in self.revoked) else [])
        for table, value in self.rows.items():
            if table in text:
                return Rows([(value,)])
        raise AssertionError(text)


def test_campaign_ancestor_audit_accepts_exact_closed_retained_chain(monkeypatch):
    rows, scopes = campaign_ancestor_fixture()
    monkeypatch.setattr(extension, "PARENT_SCOPE_DIGEST", _digest(scopes["synthetic-scope-15"]))
    conn = AncestorReads(rows, scopes)
    extension._audit_campaign_ancestors(conn, rows["workspace_d5_capacity_revisions"])
    assert len(conn.statements) == 7 and all(q.startswith("SELECT ") for q in conn.statements)


@pytest.mark.parametrize(
    "mutation",
    [
        "v15_scope",
        "v14_row",
        "v14_scope",
        "v14_revocation",
        "v13_row",
        "v13_scope",
        "v13_revocation",
    ],
)
def test_campaign_ancestor_rows_scopes_and_new_revocations_fail_closed(monkeypatch, mutation):
    rows, scopes = campaign_ancestor_fixture()
    monkeypatch.setattr(extension, "PARENT_SCOPE_DIGEST", _digest(scopes["synthetic-scope-15"]))
    conn = AncestorReads(rows, scopes)
    if mutation.endswith("scope"):
        number = mutation[1:3]
        scopes["synthetic-scope-" + number]["state"] = "active"
    elif mutation.endswith("row"):
        table = (
            "workspace_d5_campaign_successors"
            if mutation.startswith("v14")
            else "workspace_d5_campaign_extensions"
        )
        rows[table]["new_drift"] = True
    else:
        conn.revoked.add(
            "workspace_d5_campaign_successor_revocations"
            if mutation.startswith("v14")
            else "workspace_d5_campaign_revocations"
        )
    with pytest.raises(
        AdmissionError, match="campaign_v19_(parent_stopped_scope|campaign_ancestor)"
    ):
        extension._audit_campaign_ancestors(conn, rows["workspace_d5_capacity_revisions"])
    assert all(q.startswith("SELECT ") for q in conn.statements)


def test_direct_external_record_requires_verified_packet_before_storage():
    with pytest.raises(AdmissionError, match="verified_frozen_packet"):
        extension.record_external(None, {"approved": True})


@pytest.mark.parametrize("field", ["packet_digest", "case_bindings_digest", "campaign_extension"])
def test_coordinated_valid_hex_identity_drift_cannot_record_authority(monkeypatch, field):
    from src.workspace import d5_campaign_operator

    expected = {
        "packet_digest": "a" * 64,
        "scope_id": "d5-" + ("a" * 24),
        "case_bindings_digest": "b" * 64,
        "campaign_extension": {"core": {"plan_digest": "c" * 64}, "proposal_digest": "d" * 64},
        "approved": False,
        "approved_by": None,
    }
    packet = {"revision": "d5-comparison-machine-campaign-v19"}
    monkeypatch.setattr(d5_campaign_operator, "template", lambda value: deepcopy(expected))
    value = deepcopy(expected)
    value.update(approved=True, approved_by="Synthetic test, not owner")
    if field == "packet_digest":
        value.update(packet_digest="e" * 64, scope_id="d5-" + ("e" * 24))
    elif field == "case_bindings_digest":
        value[field] = "e" * 64
    else:
        value[field]["core"]["plan_digest"] = "e" * 64
        value[field]["proposal_digest"] = _digest(value[field]["core"])
    with pytest.raises(AdmissionError, match="exact_packet_receipt_binding"):
        extension.record_external(None, value, packet=packet)
