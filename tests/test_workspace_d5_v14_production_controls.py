"""Production-adapter regressions on synthetic authority and disposable Postgres.

No provider or token-count service is contacted. Optional permanent exports retain
raw reports and financial rows before the per-test schema is dropped.
"""

import hashlib
import json
import os
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from psycopg import Rollback, sql
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign import CampaignTransport, run
from src.workspace.d5_campaign_v14_policy import development_contract
from tests import test_workspace_d5_v14_integration as baseline

store = baseline.store
if hasattr(baseline, "workspace_pg"):
    workspace_pg_proc, workspace_pg = baseline.workspace_pg_proc, baseline.workspace_pg
# Each control rebuilds both stopped predecessors through the adapter.
pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.timeout(240)]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


@pytest.fixture(autouse=True)
def preserve_disposable_rows(request, store):
    yield
    # This finalizer runs before store teardown, including assertion failures.
    retain(request.node.name + "-final", store, {}, [], {})


def financial_checkpoint(store):
    """Both stopped predecessors, including their raw contacts and reservations."""
    with store.pool.connection() as conn:
        return conn.execute(
            "SELECT j.id,to_jsonb(j),to_jsonb(r) FROM workspace_generation_jobs j "
            "JOIN workspace_spend_reservations r ON r.job_id=j.id "
            "WHERE r.unknown>0 ORDER BY j.id"
        ).fetchall()


def retain(name, store, packet, reports, transports):
    root = os.environ.get("WORKSPACE_D5_CONTROL_EVIDENCE_ROOT")
    if not root:
        return
    target = Path(root) / (name + "-" + uuid.uuid4().hex)
    target.mkdir(parents=True, exist_ok=False)
    tables = {}
    with store.pool.connection() as conn:
        for table in (
            "workspace_generation_jobs",
            "workspace_spend_reservations",
            "workspace_d5_scopes",
            "workspace_d5_stage_authorizations",
            "workspace_d5_case_runs",
            "workspace_d5_campaign_outcomes",
            "workspace_d5_campaign_extensions",
            "workspace_d5_campaign_revocations",
        ):
            tables[table] = [
                r[0]
                for r in conn.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(table))
                )
            ]
    artifacts = {
        "packet.json": packet,
        "reports.json": reports,
        "database-rows.json": tables,
        "transport-contacts.json": {k: v.contacts for k, v in transports.items()},
        "provenance.json": {
            "synthetic": True,
            "real_provider_contacts": 0,
            "real_count_contacts": 0,
            "real_ledger_writes": 0,
            "source_checkpoint": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "test_module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
    }
    manifest = {}
    for filename, value in artifacts.items():
        content = (json.dumps(value, indent=2, default=str) + "\n").encode()
        (target / filename).write_bytes(content)
        manifest[filename] = hashlib.sha256(content).hexdigest()
    (target / "SHA256.json").write_text(json.dumps(manifest, indent=2) + "\n")


def factory_for(transports, cls=CampaignTransport, **kwargs):
    def factory(key):
        transports[key] = cls(key, **kwargs)
        return transports[key]

    return factory


async def test_complete_negative_development_advances_to_evaluation_but_stays_failed(store):
    packet, old = await baseline.setup_successor(store)
    holds = financial_checkpoint(store)
    assert len(holds) == 2
    transports = {}
    report = await run(
        store,
        packet,
        offline=True,
        transport_factory=factory_for(transports, scenario="reject"),
        checkpoint_after=3,
    )
    retain("complete-negative", store, packet, [old, report], transports)
    assert report["stop"] is None
    assert list(transports) == packet["schedule"][:3]
    assert len(report["outcomes"]) == 3
    assert report["cases"][2]["state"] == "failed"  # Evaluation really dispatched.
    scope = "d5-" + packet["packet_digest"][:24]
    with store.pool.connection() as conn:
        contracts = [development_contract(conn, scope, key) for key in packet["schedule"][:2]]
        for key in packet["schedule"][:2]:
            data = conn.execute(
                "SELECT j.data FROM workspace_generation_jobs j JOIN workspace_d5_case_runs r "
                "ON r.job_id=j.id WHERE r.scope_id=%s AND r.case_id=%s",
                (scope, key),
            ).fetchone()[0]
            assert data["campaign_content_rejection"]["accepted"] is False
            assert data.get("result") is None
    for contract, case in zip(contracts, report["cases"][:2], strict=True):
        assert contract["contract_complete"] is True
        assert contract["quality_accepted"] is False
        assert contract["quality_is_human_qualified"] is False
        assert case["state"] == "failed" and case["completion"] is False
        assert case["assessment_binding"]["status"] == "bound"
        assert case["whole_claim_support"]["unsupported"] > 0
        assert case["human_qualified"] is False
    assert financial_checkpoint(store) == holds
    assert report["accounting"]["cumulative"]["unknown_usd"] == "0.875066"
    assert report["human_qualification"] is False


class CompleteJsonAtTokenLimit(CampaignTransport):
    async def __call__(self, request):
        response = await super().__call__(request)
        body = json.loads(request.content)
        phase = json.loads(body["messages"][0]["content"])["phase"]
        if request.url.path.endswith("/messages") and phase == "check" and self.checks == 2:
            value = response.json()
            assert isinstance(json.loads(value["content"][0]["text"]), dict)
            value["stop_reason"] = "max_tokens"
            return httpx.Response(200, json=value)
        return response


async def test_complete_json_at_final_checker_max_tokens_stops_with_unavailable_judgment(store):
    packet, old = await baseline.setup_successor(store)
    holds = financial_checkpoint(store)
    transports = {}
    report = await run(
        store,
        packet,
        offline=True,
        transport_factory=factory_for(transports, CompleteJsonAtTokenLimit),
    )
    retain("complete-json-max-tokens", store, packet, [old, report], transports)
    assert report["stop"]["reason"] == "campaign_development_contract_incomplete"
    assert list(transports) == packet["schedule"][:1]
    first = report["raw_results"][packet["schedule"][0]]
    messages = [c for c in first["contacts"] if c["endpoint"] == "messages"]
    assert [c["stage"] for c in messages] == ["draft", "check", "repair", "check"]
    final = messages[-1]["response"]
    assert final["stop_reason"] == "max_tokens"
    assert isinstance(json.loads(final["content"][0]["text"]), dict)
    case = report["cases"][0]
    assert case["state"] == "failed"
    assert case["assessment_binding"]["status"] == "unavailable"
    assert case["machine_coverage"] is case["whole_claim_support"] is None
    assert report["denominators"]["unrun_evaluation"] == 8
    assert financial_checkpoint(store) == holds


class CompleteHttp400(CampaignTransport):
    async def __call__(self, request):
        body = json.loads(request.content)
        phase = json.loads(body["messages"][0]["content"])["phase"]
        if request.url.path.endswith("/messages") and phase == "check":
            self.contacts.append((request.url.path, _digest(body)))
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Synthetic full HTTP 400; no provider contacted",
                    },
                    "request_id": "synthetic-full-400-v14",
                },
            )
        return await super().__call__(request)


@pytest.mark.parametrize("failure", ["http400", "uncertain"])
async def test_new_provider_failure_retains_both_old_holds_and_refuses_replay(store, failure):
    packet, old = await baseline.setup_successor(store)
    holds = financial_checkpoint(store)
    transports = {}
    factory = (
        factory_for(transports, CompleteHttp400)
        if failure == "http400"
        else factory_for(transports, scenario="uncertain")
    )
    report = await run(store, packet, offline=True, transport_factory=factory)
    retain(failure, store, packet, [old, report], transports)
    assert report["stop"]["automatic_retries"] == 0
    assert report["stop"]["case_id"] == packet["schedule"][0]
    assert list(transports) == packet["schedule"][:1]
    after = financial_checkpoint(store)
    assert len(after) == 3
    assert [r for r in after if r[0] in {h[0] for h in holds}] == holds
    assert report["accounting"]["cumulative"]["unknown_usd"] == "1.525066"
    assert report["accounting"]["cumulative"]["pending_usd"] == "1.525066"
    assert report["accounting"]["historical"]["known_usd"] == "1.986755"
    case = report["cases"][0]
    assert case["assessment_binding"]["status"] == "unavailable"
    assert case["machine_coverage"] is case["whole_claim_support"] is None
    assert report["denominators"]["unrun_evaluation"] == 8
    first = report["raw_results"][packet["schedule"][0]]
    messages = [c for c in first["contacts"] if c["endpoint"] == "messages"]
    assert len(messages) == 2
    if failure == "http400":
        response = messages[-1]["response"]
        assert response["http_status"] == 400 and response["complete_body"] is True
        assert response["usage_validated"] is False
        assert json.loads(response["raw_body"])["request_id"] == "synthetic-full-400-v14"
    else:
        assert messages[-1]["state"] == "dispatching"
    contacts_before = {k: list(t.contacts) for k, t in transports.items()}
    calls = []
    with pytest.raises(AdmissionError, match="active_external_authorization"):
        await run(store, packet, offline=True, transport_factory=lambda key: calls.append(key))
    assert calls == []
    assert {k: t.contacts for k, t in transports.items()} == contacts_before
    assert financial_checkpoint(store) == after


async def test_v14_reservation_and_consolidated_grant_refusals_use_production_admission(store):
    from src.workspace.d5_adapter import D5Adapter
    from src.workspace.d5_campaign_policy import guard
    from src.workspace.d5_freeze import compile_inputs, restore_input
    from src.workspace.qualification_budget import guard_program
    from tests.test_workspace_programme_amendments import seed_failed

    packet, old = await baseline.setup_successor(store)
    first = next(iter(compile_inputs(packet).values()))
    settings = first["input"]["settings"]
    transports = {}
    transport = CampaignTransport(packet["schedule"][0])
    adapter = D5Adapter(
        store,
        first["owner"],
        restore_input(first["input"]),
        transport=httpx.MockTransport(transport),
    )
    holds = financial_checkpoint(store)
    # Wrong full-workflow envelope must refuse before a generation/count contact.
    for amount, refusal in (
        ("0.45", "d5_complete_operation_reservation_required"),
        ("0.66", "job_cap_exceeded"),
    ):
        with pytest.raises(AdmissionError, match="^" + refusal + "$"):
            adapter.start(settings["d5_request_id"], amount_usd=amount)
    assert transport.contacts == []
    with store.pool.connection() as conn:
        scope = conn.execute(
            "SELECT data FROM workspace_d5_scopes WHERE scope_id=%s", (settings["d5_scope_id"],)
        ).fetchone()[0]
        conn.execute("SELECT 1")
        with conn.transaction():
            # Disposable adversary creates financial pressure without shrinking
            # or mutating the approved fourteen-case schedule or either hold.
            conn.execute(
                "UPDATE workspace_spend_reservations SET amount=4,workflow=4 WHERE job_id='synthetic-failed-programme-7'"
            )
            with pytest.raises(
                AdmissionError, match="remaining_batch_requires_consolidated_budget_adjustment"
            ):
                guard(
                    conn,
                    {**scope, "id": settings["d5_scope_id"]},
                    first["owner"],
                    settings,
                    amount=Decimal("0.65"),
                    endpoint=None,
                )
            raise Rollback()
    assert financial_checkpoint(store) == holds
    # The prospective programme admits its final slot and refuses the next one;
    # all added rows are synthetic terminal jobs with no provider contacts.
    seed_failed(store, 33, 13)
    with store.pool.connection() as conn:
        policy = conn.execute(
            "SELECT data FROM workspace_budget_policies WHERE owner=%s", (first["owner"],)
        ).fetchone()[0]
        report = guard_program(
            conn,
            first["owner"],
            policy,
            reserve_usd=Decimal("0.65"),
            current_job=None,
            next_endpoint=None,
        )
        assert report["new_jobs"] == 48
    seed_failed(store, 46, 1)
    with (
        store.pool.connection() as conn,
        pytest.raises(AdmissionError, match="program_job_cap_exceeded"),
    ):
        guard_program(
            conn,
            first["owner"],
            policy,
            reserve_usd=Decimal("0.65"),
            current_job=None,
            next_endpoint=None,
        )
    with store.pool.connection() as conn:
        data = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id='synthetic-failed-programme-46'"
        ).fetchone()[0]
        data["adapter"]["contacts"] = [
            {"endpoint": endpoint, "state": "completed"}
            for endpoint in ("messages", "messages/count_tokens")
            for _ in range(43)
        ]
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id='synthetic-failed-programme-46'",
            (Jsonb(data),),
        )
        # 111/136 permits exactly the 112th Message and 137th count.
        for endpoint in ("messages", "messages/count_tokens"):
            guard_program(
                conn,
                first["owner"],
                policy,
                reserve_usd=None,
                current_job=None,
                next_endpoint=endpoint,
            )
        data["adapter"]["contacts"] += [
            {"endpoint": "messages", "state": "completed"},
            {"endpoint": "messages/count_tokens", "state": "completed"},
        ]
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id='synthetic-failed-programme-46'",
            (Jsonb(data),),
        )
        for endpoint in ("messages", "messages/count_tokens"):
            with pytest.raises(AdmissionError, match="program_contact_cap_exceeded"):
                guard_program(
                    conn,
                    first["owner"],
                    policy,
                    reserve_usd=None,
                    current_job=None,
                    next_endpoint=endpoint,
                )
    assert financial_checkpoint(store) == holds
    assert transport.contacts == []
    retain("production-admission-refusals", store, packet, [old], transports)
