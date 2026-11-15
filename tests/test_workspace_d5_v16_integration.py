"""Portable keyed successor over marked Postgres and mock-only HTTP transport.

All parent permissions, recorded finance and new verdicts are synthetic controls.
No private archive, real credential, live ledger or provider contact is used.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.workspace import d5_campaign_v16_extension as extension
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign import run
from src.workspace.d5_campaign_operator import authorize_fixture, record, revoke, template
from src.workspace.d5_campaign_policy import job_binding
from src.workspace.d5_campaign_v16_packet import (
    capture,
    freeze,
    predecessor,
    upgrade,
    verify_packet,
)
from src.workspace.d5_campaign_v16_policy import development_contract, require_development_contracts
from src.workspace.d5_capacity_transport import CapacityCampaignTransport
from src.workspace.d5_freeze import verify
from src.workspace.d5_keyed_transport import KeyedCampaignTransport
from src.workspace.executor import ExecutorError
from tests import test_workspace_d5_campaign as base
from tests.d5_capacity_gate import export_rows, prepare

store = base.store
if hasattr(base, "workspace_pg"):
    workspace_pg_proc, workspace_pg = base.workspace_pg_proc, base.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.timeout(600)]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


class RejectedV15Draft(CapacityCampaignTransport):
    """A complete malformed first draft; no fictitious checker is manufactured."""

    async def __call__(self, request):
        response = await super().__call__(request)
        if request.url.path.endswith("count_tokens"):
            return response
        value = response.json()
        value["content"] = [{"type": "text", "text": '{"response":{}}'}]
        return httpx.Response(200, json=value)


_BASELINE = None


async def setup_keyed(store, *, authorize=True):
    global _BASELINE
    if _BASELINE is not None:
        from src.workspace.d5_fixture import install

        snapshot, packet = deepcopy(_BASELINE)
        install(store, snapshot, fixture=True)
        if authorize:
            authorize_fixture(store, packet)
            from src.workspace.programme_amendments import effective_limits
            with store.pool.connection() as conn:
                assert effective_limits(conn, packet["program_id"], required_proposal_digest=packet["campaign_extension"]["proposal_digest"])["new_jobs"] == 64
        return packet
    prior = await prepare(store)
    stopped = await run(store, prior, offline=True, transport_factory=RejectedV15Draft)
    assert stopped["stop"]["reason"] == "campaign_development_contract_incomplete"
    assert len(stopped["outcomes"]) == 1
    job = stopped["raw_results"]["campaign-dev-learn"]["id"]
    with store.pool.connection() as conn:
        # Explicit copied financial checkpoint in isolated synthetic storage;
        # mock transport has zero real usage and never claims this as spend.
        conn.execute(
            "UPDATE workspace_spend_reservations SET workflow=0.027884,judge=0 WHERE job_id=%s",
            (job,),
        )
        conn.execute(
            "UPDATE workspace_d5_campaign_outcomes SET job_digest=%s WHERE job_id=%s",
            (job_binding(conn, job)[2], job),
        )
    snapshot = capture(store, "evaluation")
    assert snapshot["history"]["known_usd"] == "2.138481"
    assert snapshot["history"]["messages"] == 71 and snapshot["history"]["counts"] == 96
    packet = freeze(store, snapshot)
    _BASELINE = deepcopy((snapshot, packet))
    if authorize:
        authorize_fixture(store, packet)
        from src.workspace.programme_amendments import effective_limits
        with store.pool.connection() as conn:
            assert effective_limits(conn, packet["program_id"], required_proposal_digest=packet["campaign_extension"]["proposal_digest"])["new_jobs"] == 64
    return packet


def reseal(value):
    value["packet_digest"] = _digest({k: v for k, v in value.items() if k != "packet_digest"})
    return value


def grants(store):
    with store.pool.connection() as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT record FROM (SELECT record,created_at,extension_id FROM workspace_d5_capacity_revisions UNION ALL SELECT record,created_at,extension_id FROM workspace_d5_keyed_continuations) t ORDER BY created_at,extension_id"
            )
        ]


def contacts(store):
    with store.pool.connection() as conn:
        return conn.execute(
            "SELECT count(*) FROM workspace_generation_jobs j CROSS JOIN LATERAL jsonb_array_elements(COALESCE(j.data->'adapter'->'contacts','[]')) c"
        ).fetchone()[0]


async def test_full_keyed_campaign_is_portable_bounded_and_restart_idempotent(store, monkeypatch):
    try:
        packet = await setup_keyed(store)
        original = predecessor()
        assert [c["ranking"] for c in packet["cases"]] == [c["ranking"] for c in original["cases"]]
        assert (
            packet["schedule"] == original["schedule"] and packet["scoring"] == original["scoring"]
        )
        assert packet["probe_references"] == original["probe_references"]
        assert packet["checker_schema_template_revision"] == "workspace-assistance-keyed-checks-v16"
        assert "checker_schemas" not in packet
        receipts = grants(store)
        assert receipts[0]["programme_expires_at"] == receipts[1]["programme_expires_at"]
        assert receipts[1]["campaign_extension"]["core"]["capacity_change"] is False
        assert (
            receipts[1]["campaign_extension"]["core"]["limits"]
            == receipts[0]["campaign_extension"]["core"]["limits"]
        )
        monkeypatch.setattr(
            "src.workspace.d5_campaign_packet.selection",
            lambda *_a, **_k: pytest.fail("re-retrieval after freeze"),
        )
        report = await run(
            store,
            packet,
            offline=True,
            transport_factory=lambda key: KeyedCampaignTransport(key, repair_all=True),
        )
        assert report["stop"] is None, report["stop"]
        assert len(report["outcomes"]) == 14
        assert (
            report["accounting"]["new_scope"]["messages"]
            == report["accounting"]["new_scope"]["counts"]
            == 44
        )
        cumulative = report["accounting"]["cumulative"]
        assert (
            cumulative["funded_programme_jobs"],
            cumulative["messages"],
            cumulative["counts"],
        ) == (51, 115, 140)
        assert (
            cumulative["unknown_usd"]
            == cumulative["pending_usd"]
            == report["accounting"]["retained_hold_usd"]
            == "0.875066"
        )
        assert report["accounting"]["historical"]["known_usd"] == "2.138481"
        assert report["human_qualification"] is False and report["human_labels"] is None
        assert all(c["assessment_binding"]["status"] == "bound" for c in report["cases"])
        for value in report["raw_results"].values():
            if value["operation"] == "workflow":
                assert [s["stage"] for s in value["steps"]] == ["draft", "check", "repair", "check"]
                emitted = value["assistance_output"]["claims"]
                if emitted:
                    cap = 8 if value["request"]["assistance"]["mode"] == "learn" else 12
                    assert len(emitted) == cap
                    assert emitted[-1]["claim_id"] == f"c{cap}"
                    assert len(value["steps"][-1]["output"]["checks"]) == cap
        before = contacts(store)
        again = await run(
            store,
            packet,
            offline=True,
            transport_factory=lambda _: pytest.fail("duplicate dispatch"),
        )
        assert again["accounting"] == report["accounting"] and contacts(store) == before
    finally:
        export_rows(store, "v16-full-portable")


async def test_invalid_grants_refuse_before_contacts_and_template_stays_unapproved(store):
    try:
        packet = await setup_keyed(store, authorize=False)
        receipt = template(packet)
        assert receipt["approved"] is False
        assert receipt["historical_uncertainty_exception_approved"] is False
        assert (
            "capacity_amendment_approved" not in receipt
            and "expiry_adjustment_approved" not in receipt
        )
        before = contacts(store)
        with pytest.raises(AdmissionError):
            await run(
                store,
                packet,
                offline=True,
                transport_factory=lambda _: pytest.fail("unapproved transport"),
            )
        for mutation in (
            "approved",
            "historical_uncertainty_exception_approved",
            "packet_digest",
            "programme_expires_at",
            "expires_at",
            "code_bindings",
            "scope_id",
            "source_bindings",
        ):
            bad = deepcopy(receipt)
            bad.update(
                approved=True,
                approved_by="Synthetic fixture",
                approved_at=datetime.now(UTC).isoformat(),
                approval_source="Synthetic test",
                authorization_kind="offline_fixture",
                transport_mode="mock",
                expires_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                historical_uncertainty_exception_approved=True,
            )
            if mutation in {"approved", "historical_uncertainty_exception_approved"}:
                bad[mutation] = False
            elif mutation in {"expires_at", "programme_expires_at"}:
                bad[mutation] = (datetime.now(UTC) + timedelta(days=20)).isoformat()
            else:
                bad[mutation] = {} if isinstance(bad[mutation], dict) else "changed"
            with pytest.raises((AdmissionError, ValueError)):
                record(store, packet, bad)
        assert contacts(store) == before and len(grants(store)) == 1
    finally:
        export_rows(store, "v16-invalid-grants")


@pytest.mark.parametrize(
    "scenario",
    ["missing_judgment", "wrong_digest", "unknown_key", "checker_max_tokens", "duplicate_json_key"],
)
async def test_invalid_current_checker_stops_before_second_identity(store, scenario):
    try:
        packet = await setup_keyed(store)
        calls = []

        def factory(key):
            calls.append(key)
            return KeyedCampaignTransport(key, scenario=scenario)

        report = await run(store, packet, offline=True, transport_factory=factory)
        assert report["stop"]["reason"] == "campaign_development_contract_incomplete"
        assert calls == [packet["schedule"][0]]
        assert report["denominators"]["unrun_evaluation"] == 8
        assert report["cases"][0]["whole_claim_support"] is None
        assert report["cases"][0]["machine_coverage"] is None
        assert report["accounting"]["cumulative"]["unknown_usd"] == "0.875066"
    finally:
        export_rows(store, "v16-invalid-check-" + scenario)


async def test_valid_negative_quality_remains_failed_and_allows_next_frozen_identity(store):
    try:
        packet = await setup_keyed(store)
        report = await run(
            store,
            packet,
            offline=True,
            transport_factory=lambda key: KeyedCampaignTransport(key, scenario="reject"),
            checkpoint_after=2,
        )
        assert report["stop"] is None and len(report["outcomes"]) == 2
        assert all(row["state"] == "failed" for row in report["outcomes"].values())
        assert all(row["assessment_binding"]["status"] == "bound" for row in report["cases"][:2])
        with store.pool.connection() as conn:
            scope = "d5-" + packet["packet_digest"][:24]
            assert (
                development_contract(conn, scope, packet["schedule"][0])["quality_accepted"]
                is False
            )
            with pytest.raises(AdmissionError):
                require_development_contracts(conn, {"cases": {}, "id": scope})
    finally:
        export_rows(store, "v16-negative-quality")


async def test_frozen_source_code_threshold_template_and_schedule_drift_refused(store):
    try:
        packet = await setup_keyed(store, authorize=False)
        for mutation in (
            "limits",
            "progression",
            "operation_routes",
            "operation_deadlines",
            "capacity_policy",
            "keyed_checker_finding_capacity",
            "expiry_policy",
            "checker_schema_template_revision",
            "checker_normalization_revision",
            "schedule",
            "scoring",
            "probe_references",
            "answerability",
            "code",
            "adapter",
            "case",
            "source",
            "check_template",
            "probe_wire",
            "probe_capacity",
            "case_capacity",
            "extension",
        ):
            bad = deepcopy(packet)
            if mutation == "probe_capacity":
                bad["probes"][0]["sealed"]["keyed_checker_finding_capacity"] = {}
            elif mutation == "case_capacity":
                bad["cases"][0]["sealed"]["keyed_checker_finding_capacity"] = {}
            elif mutation == "probe_wire":
                bad["probes"][0]["wire"] = {}
            elif mutation == "extension":
                bad["campaign_extension"]["core"]["plan_digest"] = "changed"
            elif mutation == "case":
                bad["cases"][0]["question"] += " changed"
            elif mutation == "source":
                first = next(iter(bad["cases"][0]["sealed"]["units"]))
                bad["cases"][0]["sealed"]["units"][first]["quote"] += " changed"
            elif mutation == "check_template":
                bad["cases"][0]["sealed"]["stage_contracts"]["check"]["output_schema"] = {}
            elif isinstance(bad[mutation], dict):
                bad[mutation] = {}
            elif isinstance(bad[mutation], list):
                bad[mutation] = []
            else:
                bad[mutation] = "changed"
            with pytest.raises((AdmissionError, ValueError, KeyError, IndexError)):
                verify(reseal(bad))
        assert verify_packet(packet) is None
        prior = predecessor()
        assert (
            upgrade(prior["cases"][0]["sealed"])["schema_revision"]
            == "workspace-assistance-keyed-v16"
        )
        before = contacts(store)
        with store.pool.connection() as conn:
            key = next(iter(packet["source_bindings"]["materials"]))
            conn.execute(
                "UPDATE workspace_material SET data=jsonb_set(data,'{content_hash}','\"changed\"') WHERE material_id=%s",
                (key,),
            )
        with pytest.raises((AdmissionError, ExecutorError)):
            authorize_fixture(store, packet)
        assert contacts(store) == before
    finally:
        export_rows(store, "v16-frozen-drift")


async def test_successor_receipt_idempotence_expiry_revocation_and_parent_tamper(store):
    try:
        packet = await setup_keyed(store)
        receipt = grants(store)[1]
        assert extension.record_external(store, receipt)["duplicate"] is True
        with store.pool.connection() as conn:
            assert extension.active(conn, "evaluation", "missing") is None
            assert extension.active(conn, "evaluation")[0] == receipt
        changed = deepcopy(receipt)
        changed["approval_source"] = "different synthetic grant"
        with pytest.raises(AdmissionError, match="immutable_no_reapproval"):
            extension.record_external(store, changed)
        with store.pool.connection() as conn:
            conn.execute("BEGIN")
            conn.execute(
                "UPDATE workspace_d5_scopes SET state='active' WHERE scope_id=%s",
                (receipt["campaign_extension"]["core"]["parent"]["scope_id"],),
            )
            with pytest.raises(AdmissionError, match="parent_or_stopped_scope_drift"):
                extension.parent(conn, "evaluation")
            conn.rollback()
        bad = deepcopy(receipt)
        bad["approved_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        bad["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        with (
            store.pool.connection() as conn,
            pytest.raises(AdmissionError, match="external_owner_authorization_required"),
        ):
            extension._validate(conn, bad, "evaluation")
        revoke(store, packet, receipt)
        with (
            store.pool.connection() as conn,
            pytest.raises(AdmissionError, match="revoked_or_receipt_drift"),
        ):
            extension.active(conn, "evaluation")
        with pytest.raises(AdmissionError, match="revoked_or_receipt_drift"):
            extension.record_external(store, receipt)
    finally:
        export_rows(store, "v16-successor-recorder")


@pytest.fixture
def validated(monkeypatch):
    """Synthetic receipt controls isolate validation branches without contacts."""
    from tests.test_workspace_d5_v15_extension import receipt_for

    now = datetime.now(UTC)
    parent = {
        "extension_id": "program-capacity-v15",
        "authorization_digest": "synthetic-parent",
        "programme_expires_at": (now + timedelta(days=6)).isoformat(),
        "limits": deepcopy(extension.PROGRAM_LIMITS),
    }
    retained = [
        {"binding": {"job_id": "old", "hold_usd": "0.425066"}},
        {"binding": {"job_id": "received", "hold_usd": "0.45"}},
    ]
    basis = {
        "contact_checkpoints": {"old": {}, "received": {}},
        "known_usd": "2.138481",
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
    for key in (
        "expiry_adjustment_approved",
        "budget_adjustment_approved",
        "capacity_amendment_approved",
    ):
        receipt.pop(key)
    receipt["programme_expires_at"] = parent["programme_expires_at"]
    routes = {
        "workspace_d5_fixture_marker": [(1,)],
        "workspace_versions": [("v", {"v": 1})],
        "workspace_material": [("m", {"m": 1})],
    }
    return receipt, parent, retained, basis, routes


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "parent",
        "retained",
        "limits",
        "expiry_policy",
        "source",
        "history",
        "duplicate_case",
        "renewal",
        "capacity",
        "no_owner",
        "no_source",
        "future",
        "expired",
        "campaign25h",
        "naive",
        "provider",
        "unapproved",
        "no_exception",
        "invalid_time",
    ],
)
async def test_exact_receipt_decisions_history_and_authority_are_independent(validated, mutation):
    from tests.test_workspace_d5_v14_extension_controls import MemoryConnection

    receipt, parent, retained, basis, routes = validated
    start = datetime.fromisoformat(receipt["approved_at"])
    if mutation == "parent":
        parent["authorization_digest"] = "changed"
    elif mutation == "retained":
        retained[0]["binding"]["hold_usd"] = "0"
    elif mutation == "limits":
        receipt["limits"]["new_usd"] = "15"
    elif mutation == "expiry_policy":
        receipt["campaign_extension"]["core"]["expiry_policy"] = {}
    elif mutation == "source":
        routes["workspace_material"] = [("m", {"m": 2})]
    elif mutation == "history":
        basis["known_usd"] = "2.138482"
    elif mutation == "duplicate_case":
        receipt["case_order"].append("case-0")
    elif mutation == "renewal":
        receipt["programme_expires_at"] = (start + timedelta(days=20)).isoformat()
    elif mutation == "capacity":
        receipt["campaign_extension"]["core"]["capacity_change"] = True
    elif mutation == "no_owner":
        receipt["approved_by"] = "  "
    elif mutation == "no_source":
        receipt["approval_source"] = "\n"
    elif mutation == "future":
        receipt["approved_at"] = (start + timedelta(hours=1)).isoformat()
    elif mutation == "expired":
        receipt["expires_at"] = (start - timedelta(hours=1)).isoformat()
    elif mutation == "campaign25h":
        receipt["expires_at"] = (start + timedelta(hours=25)).isoformat()
    elif mutation == "invalid_time":
        receipt["approved_at"] = {}
    elif mutation == "naive":
        receipt["approved_at"] = start.replace(tzinfo=None).isoformat()
    elif mutation == "provider":
        receipt.update(transport_mode="provider", authorization_kind="owner")
    elif mutation == "unapproved":
        receipt["approved"] = False
    elif mutation == "no_exception":
        receipt["historical_uncertainty_exception_approved"] = False
    if mutation:
        with pytest.raises(AdmissionError):
            extension._validate(MemoryConnection(routes), receipt, "program")
    else:
        assert (
            extension._validate(MemoryConnection(routes), receipt, "program")
            == receipt["campaign_extension"]["core"]
        )
        with pytest.raises(AdmissionError, match="plan_identity_required"):
            extension.proposal(None, "program", " ")
        with pytest.raises(AdmissionError, match="explicit_owner_approval_required"):
            extension.record_external(None, {"approved": False})


@pytest.mark.parametrize(
    "mutation",
    [None, "scope", "authorization", "unknown", "dispatching", "foreign", "failed", "current"],
)
async def test_retained_exception_does_not_hide_new_uncertainty(validated, monkeypatch, mutation):
    from tests.test_workspace_d5_v14_extension_controls import MemoryConnection

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
    inflight = {
        "dispatching": [("new", "running", "dispatching")],
        "foreign": [("other", "running", "running")],
        "failed": [("new", "failed", "running")],
        "current": [("new", "running", "running")],
    }.get(mutation, [])
    conn = MemoryConnection(
        {"SELECT owner": [("member",)], "SELECT id": [("new",)], "CROSS JOIN": inflight}
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


@pytest.mark.parametrize(
    "mutation", [None, "members", "baseline", "jobs", "counts", "hold", "active"]
)
async def test_capture_baseline_is_exact_and_never_synthesizes_missing_evidence(
    monkeypatch, mutation
):
    from tests.test_workspace_d5_v14_extension_controls import MemoryConnection

    value = {
        "generation_job_ids": [f"j{i}" for i in range(37)],
        "messages": 71,
        "counts": 96,
        "known_usd": "2.138481",
        "pending_usd": "0.875066",
        "unknown_usd": "0.875066",
        "active_jobs": [],
    }
    members = [] if mutation == "members" else [("member",)]
    baseline = [] if mutation == "baseline" else [({"generation_job_ids": []},)]
    if mutation == "jobs":
        value["generation_job_ids"].pop()
    elif mutation == "counts":
        value["counts"] = 97
    elif mutation == "hold":
        value["unknown_usd"] = "0"
    elif mutation == "active":
        value["active_jobs"] = ["new"]
    monkeypatch.setattr(extension, "census", lambda *_a, **_k: value)
    conn = MemoryConnection({"SELECT owner": members, "SELECT baseline": baseline})
    if mutation:
        with pytest.raises(AdmissionError):
            extension.history(conn, "program")
    else:
        assert extension.history(conn, "program") == (["member"], value)


async def test_unmigrated_readonly_capture_does_not_install_021(store, monkeypatch):
    try:
        await setup_keyed(store, authorize=False)
        with store.pool.connection() as conn:
            conn.execute("DROP TABLE workspace_d5_keyed_continuation_revocations")
            conn.execute("DROP TABLE workspace_d5_keyed_continuations")
        monkeypatch.setattr(
            store, "migrate", lambda: pytest.fail("read-only capture migrated storage")
        )
        snapshot = capture(store, "evaluation")
        assert (
            snapshot["recorded_keyed_continuations"]
            == snapshot["recorded_keyed_continuation_revocations"]
            == []
        )
        assert snapshot["history"]["known_usd"] == "2.138481"
        with store.pool.connection() as conn:
            assert (
                conn.execute("SELECT to_regclass('workspace_d5_keyed_continuations')").fetchone()[0]
                is None
            )
    finally:
        export_rows(store, "v16-unmigrated-readonly-capture")


async def test_synthetic_parent_requires_permanent_fixture_marker(store, monkeypatch):
    try:
        await setup_keyed(store, authorize=False)
        with store.pool.connection() as conn:
            assert extension.parent(conn, "evaluation")["authorization_digest"]
            monkeypatch.setattr(extension, "_fixture", lambda _: False)
            with pytest.raises(AdmissionError, match="parent_or_stopped_scope_drift"):
                extension.parent(conn, "evaluation")
    finally:
        export_rows(store, "v16-synthetic-authority-fence")


@pytest.mark.parametrize("mutation", ["missing_job", "binding", "material", "invalid_check"])
async def test_development_contract_cannot_infer_missing_bindings(monkeypatch, mutation):
    from src.workspace.d5_capacity_policy import POLICY
    from tests.test_workspace_d5_v14_extension_controls import MemoryConnection

    inputs = {
        "settings": {
            "d5_capacity_policy": deepcopy(POLICY),
            "d5_request": {"schema_revision": "workspace-assistance-keyed-v16"},
            "d5_case_id": "case",
            "d5_scope_id": "scope",
        },
        "sources": [],
    }
    if mutation == "material":
        inputs["sources"] = [{"material_id": "missing"}]
    fingerprint = _digest(inputs)
    row = (
        []
        if mutation == "missing_job"
        else [
            (
                fingerprint,
                "job",
                "running" if mutation == "binding" else "failed",
                fingerprint,
                {"sealed_input": inputs},
            )
        ]
    )
    conn = MemoryConnection({"workspace_d5_case_runs": row, "workspace_material": []})
    monkeypatch.setattr(
        "src.workspace.d5_report_binding.current_check",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("No fabricated checker")),
    )
    with pytest.raises(AdmissionError):
        development_contract(conn, "scope", "case")


async def test_frozen_packet_rejects_missing_fixture_and_archived_predecessor_change(monkeypatch):
    from tests.test_workspace_d5_v14_extension_controls import MemoryConnection, MemoryStore

    with pytest.raises(AdmissionError, match="freeze_disposable_fixture_required"):
        freeze(MemoryStore(MemoryConnection({"workspace_d5_fixture_marker": []})), {})
    original = predecessor()
    original["scoring"] = {}
    monkeypatch.setattr("src.workspace.d5_benchmark.read", lambda _: original)
    with pytest.raises(AdmissionError, match="archived_predecessor_changed"):
        predecessor()


async def test_missing_parent_and_unmigrated_active_scope_are_not_authority():
    from tests.test_workspace_d5_v14_extension_controls import MemoryConnection

    with pytest.raises(AdmissionError, match="parent_receipt_required"):
        extension.parent(MemoryConnection({"workspace_d5_capacity_revisions": []}), "program")
    assert extension.active(MemoryConnection({"to_regclass": [(None,)]}), "program") is None


@pytest.mark.parametrize("finding_count", [2, 17])
async def test_independent_same_location_findings_survive_repair_and_report(store, finding_count):
    class CompleteFindings(KeyedCampaignTransport):
        async def __call__(self, request):
            response = await super().__call__(request)
            if request.url.path.endswith("count_tokens"):
                return response
            body = response.json()
            text_blocks = [block for block in body["content"] if block["type"] == "text"]
            assert len(text_blocks) == 1
            payload = json.loads(text_blocks[0]["text"])
            if isinstance(payload.get("prose_findings"), dict):
                locations = payload["prose_findings"]
                first = next(iter(locations))
                locations[first] = [f"Independent factual premise {i}" for i in range(finding_count)]
                payload["prose_review"] = "unscored_factual_content"
                text_blocks[0]["text"] = json.dumps(payload)
                from jsonschema import Draft202012Validator
                request_body = json.loads(request.content)
                Draft202012Validator(request_body["output_config"]["format"]["schema"]).validate(payload)
                return httpx.Response(200, json=body)
            return response

    try:
        packet = await setup_keyed(store)
        report = await run(
            store,
            packet,
            offline=True,
            transport_factory=lambda key: CompleteFindings(
                key, scenario="same_location_findings"
            ),
            checkpoint_after=1,
        )
        assert report["stop"] is None and report["cases"][0]["state"] == "failed"
        raw = report["raw_results"][packet["schedule"][0]]
        assert [step["stage"] for step in raw["steps"]] == ["draft", "check", "repair", "check"]
        findings = raw["steps"][-1]["output"]["prose_findings"]
        assert len(findings) == finding_count
        assert (findings[0]["field"], findings[0]["index"]) == (
            findings[1]["field"],
            findings[1]["index"],
        )
        assert findings[0]["reason"] != findings[1]["reason"]
        assert report["cases"][0]["prose_findings"] == findings
        assert report["cases"][0]["assessment_binding"]["status"] == "bound"
    finally:
        export_rows(store, f"v16-independent-prose-findings-{finding_count}")
