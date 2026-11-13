"""Complete protected campaign with synthetic grants in disposable real Postgres.

Retained public corpus is exposed. No provider/owner qualification evidence.
"""

from copy import deepcopy

import pytest
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign import CampaignTransport, run
from src.workspace.d5_campaign_operator import authorize_fixture, template
from src.workspace.d5_campaign_packet import freeze, predecessor
from src.workspace.d5_freeze import compile_inputs, verify
from src.workspace.d5_timeout_packet import capture
from tests import test_workspace_timeout_packet as prior

store = prior.store
if hasattr(prior, "workspace_pg"):
    workspace_pg_proc, workspace_pg = prior.workspace_pg_proc, prior.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def setup(store, *, authorize=True):
    prior.setup(store)
    base = predecessor()
    # Public retained input only; finance remains synthetic and hash-bound.
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id='synthetic-failed-programme-32'"
        ).fetchone()[0]
        body = {
            "model": "claude-opus-5-5",
            "messages": [{"role": "user", "content": "Synthetic fixture, no provider dispatch"}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "high"},
        }
        row["adapter"]["contacts"][1].update(body=body, request_digest=_digest(body), stage="check")
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id='synthetic-failed-programme-32'",
            (Jsonb(row),),
        )
        for item in base["corpus"]:
            conn.execute(
                "INSERT INTO workspace_works(work_id) VALUES(%s)ON CONFLICT DO NOTHING",
                (item["work_id"],),
            )
            conn.execute(
                "INSERT INTO workspace_versions(version_id,work_id,source_id,data)VALUES(%s,%s,%s,%s)ON CONFLICT(version_id)DO UPDATE SET data=excluded.data",
                (item["version_id"], item["work_id"], item["source_id"], Jsonb(item)),
            )
        for m in base["materials"]:
            conn.execute(
                "INSERT INTO workspace_material VALUES(%s,%s,%s,%s,%s)ON CONFLICT(material_id)DO UPDATE SET data=excluded.data",
                (m["material_id"], m["version_id"], m["content_hash"], m["scope"], Jsonb(m)),
            )
    snapshot = capture(store, "evaluation")
    packet = freeze(store, snapshot)
    verify(packet)
    if authorize:
        authorize_fixture(store, packet)
    return packet


async def test_protected_workflow_checkpoint_preserves_single_full_campaign_grant(store):
    packet = setup(store)
    compiled = compile_inputs(packet)
    assert len(compiled) == 14 and not any(e["stage"] == "A" for e in compiled.values())
    transport = {}

    def factory(key):
        transport[key] = CampaignTransport(key)
        return transport[key]

    report = await run(store, packet, offline=True, transport_factory=factory, checkpoint_after=1)
    assert report["stop"] is None
    assert len(report["outcomes"]) == 1
    assert report["denominators"]["completed_evaluation"] == 0
    assert report["probe_scores"]["false_pass"]["planned"] == 10
    assert report["probe_scores"]["false_reject"]["planned"] == 10
    assert report["probe_scores"]["false_pass"]["error_rate_conditional"] is None
    assert report["machine_quality"] == "HOLD" and report["human_qualification"] is False
    assert report["accounting"]["cumulative"]["unknown_usd"] == "0.425066"
    assert report["accounting"]["cumulative"]["pending_usd"] == "0.425066"
    calls = sum(len(t.contacts) for t in transport.values())
    import httpx

    from src.workspace.d5_adapter import D5Adapter
    from src.workspace.d5_freeze import restore_input

    first = compiled[next(iter(compiled))]
    cached = D5Adapter(
        store,
        first["owner"],
        restore_input(first["input"]),
        transport=httpx.MockTransport(transport[next(iter(compiled))]),
    )
    assert cached.start(first["input"]["settings"]["d5_request_id"])["state"] == "ready"
    assert len(transport[next(iter(compiled))].contacts) == calls


async def test_blank_or_partial_owner_grant_does_not_admit_campaign(store):
    from src.workspace.d5_campaign_operator import record

    packet = setup(store, authorize=False)
    with pytest.raises(AdmissionError, match="explicit_consolidated"):
        record(store, packet, template(packet))
    with pytest.raises(AdmissionError, match="active_external_authorization"):
        await run(store, packet, offline=True)


@pytest.mark.parametrize("kind", ["uncertain", "oversized"])
async def test_new_uncertainty_or_fit_refusal_stops_without_replay(store, kind):
    packet = setup(store)
    calls = {}

    def factory(key):
        calls[key] = CampaignTransport(key, scenario=kind)
        return calls[key]

    report = await run(store, packet, offline=True, transport_factory=factory)
    assert report["stop"] is not None and len(calls) == 1
    assert report["denominators"]["unrun_evaluation"] == 8
    assert report["accounting"]["historical"]["unknown_usd"] == "0.425066"
    if kind == "uncertain":
        assert report["accounting"]["cumulative"]["unknown_usd"] == "0.875066"
    else:
        assert not any(
            path.endswith("/messages") for path, _ in next(iter(calls.values())).contacts
        )
    with pytest.raises(AdmissionError, match="active_external_authorization"):
        await run(store, packet, offline=True, transport_factory=factory)


async def test_frozen_campaign_drift_rejected(store):
    packet = setup(store, authorize=False)
    for mutation in ("limits", "reference", "deadline", "cohort", "selection"):
        bad = deepcopy(packet)
        if mutation == "limits":
            bad["limits"]["messages"] = 45
        elif mutation == "reference":
            next(iter(bad["probe_references"].values()))["reference"] = "abstain"
        elif mutation == "deadline":
            bad["operation_deadlines"]["check_seconds"] = 121
        elif mutation == "cohort":
            bad["cases"][2]["cohort"] = "fresh_system"
        else:
            bad["cases"][2]["sealed"]["units"] = {}
        bad["packet_digest"] = _digest({k: v for k, v in bad.items() if k != "packet_digest"})
        with pytest.raises(AdmissionError):
            verify(bad)


async def test_capacity_changes_only_after_explicit_activation_and_keeps_legacy_caps(store):
    from src.workspace.d5_campaign_extension import effective
    from src.workspace.d5_campaign_policy import PROGRAM_LIMITS

    packet = setup(store, authorize=False)
    prior_limits = {**PROGRAM_LIMITS, "new_jobs": 34, "messages": 80, "counts": 99}
    proposal = packet["campaign_extension"]["proposal_digest"]
    with store.pool.connection() as conn:
        assert effective(conn, "evaluation", prior_limits, "legacy", None) == prior_limits
        with pytest.raises(AdmissionError, match="binding_or_revocation"):
            effective(conn, "evaluation", prior_limits, "legacy", proposal)
    authorize_fixture(store, packet)
    with store.pool.connection() as conn:
        assert effective(conn, "evaluation", prior_limits, "legacy", proposal) == PROGRAM_LIMITS
        assert effective(conn, "evaluation", prior_limits, "legacy", "legacy") == prior_limits


async def test_last_programme_job_and_contacts_admitted_then_next_refused(store):
    from decimal import Decimal

    from src.workspace.qualification_budget import guard_program
    from tests.test_workspace_programme_amendments import seed_failed

    packet = setup(store)
    actor = next(iter(compile_inputs(packet).values()))["owner"]
    seed_failed(store, 33, 13)  # 46 jobs including the immutable historical 33.
    with store.pool.connection() as conn:
        policy = conn.execute(
            "SELECT data FROM workspace_budget_policies WHERE owner=%s", (actor,)
        ).fetchone()[0]
        report = guard_program(
            conn,
            actor,
            policy,
            reserve_usd=Decimal("0.15"),
            current_job=None,
            next_endpoint=None,
            reserve_operation="probe",
        )
        assert report["new_jobs"] == 46  # Job 47 can reserve its complete envelope.
    seed_failed(store, 46, 1)
    with store.pool.connection() as conn:
        with pytest.raises(AdmissionError, match="program_job_cap_exceeded"):
            guard_program(
                conn,
                actor,
                policy,
                reserve_usd=Decimal("0.15"),
                current_job=None,
                next_endpoint=None,
                reserve_operation="probe",
            )
        # Add completed synthetic contacts on a NEW row, never edit old receipts.
        data = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id='synthetic-failed-programme-46'"
        ).fetchone()[0]
        data["adapter"]["contacts"] = [
            {"endpoint": endpoint, "state": "completed"}
            for endpoint, count in (("messages", 43), ("messages/count_tokens", 43))
            for _ in range(count)
        ]
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id='synthetic-failed-programme-46'",
            (Jsonb(data),),
        )
        # 108/133 admits the 109th Message and 134th count independently.
        for endpoint in ("messages", "messages/count_tokens"):
            guard_program(
                conn, actor, policy, reserve_usd=None, current_job=None, next_endpoint=endpoint
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
                    conn, actor, policy, reserve_usd=None, current_job=None, next_endpoint=endpoint
                )


async def test_exception_drift_or_revocation_blocks_before_transport(store):
    from psycopg import Rollback

    from src.workspace.d5_campaign import preflight
    from src.workspace.d5_campaign_extension import active

    packet = setup(store)
    # One fresh sealed baseline; each destructive adversary is rolled back.
    # This preserves every assertion without repeatedly rebuilding 14 schemas.
    with store.pool.connection() as conn:
        conn.execute("SELECT 1")
        for mutation in ("hold", "old_contact", "predecessor", "source", "revoked", "expired"):
            with conn.transaction():
                if mutation == "hold":
                    conn.execute(
                        "UPDATE workspace_spend_reservations SET unknown=0 WHERE job_id='synthetic-failed-programme-32'"
                    )
                elif mutation == "old_contact":
                    conn.execute(
                        "UPDATE workspace_generation_jobs SET data=jsonb_set(data,'{adapter,contacts,1,state}','\"completed\"') WHERE id='synthetic-failed-programme-32'"
                    )
                elif mutation == "predecessor":
                    conn.execute(
                        "UPDATE workspace_programme_capacity_amendments SET record=record||'{\"unapproved_change\":true}'::jsonb"
                    )
                elif mutation == "source":
                    vid = packet["corpus"][0]["version_id"]
                    conn.execute(
                        'UPDATE workspace_versions SET data=data||\'{"title":"Changed without replacing content_hash"}\'::jsonb WHERE version_id=%s',
                        (vid,),
                    )
                elif mutation == "revoked":
                    conn.execute(
                        "INSERT INTO workspace_d5_campaign_revocations VALUES(%s,'{}',clock_timestamp())",
                        (packet["campaign_extension"]["core"]["extension_id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE workspace_d5_campaign_extensions SET expires_at=clock_timestamp()-interval '1 second'"
                    )
                with pytest.raises(AdmissionError):
                    active(conn, "evaluation")
                assert not conn.execute(
                    "SELECT 1 FROM workspace_d5_case_runs WHERE scope_id=%s",
                    ("d5-" + packet["packet_digest"][:24],),
                ).fetchone()
                raise Rollback()
    preflight(store, packet)  # Original state restored; no transport dispatched.


async def test_exception_cannot_be_borrowed_by_another_scope(store):
    from src.workspace.d5_campaign_extension import guard_exception

    packet = setup(store)
    actor = next(iter(compile_inputs(packet).values()))["owner"]
    with store.pool.connection() as conn:
        policy = conn.execute(
            "SELECT data FROM workspace_budget_policies WHERE owner=%s", (actor,)
        ).fetchone()[0]
        policy["d5_scope_id"] = "not-the-approved-scope"
        with pytest.raises(AdmissionError, match="campaign_exception_scope_mismatch"):
            guard_exception(conn, policy)


@pytest.mark.parametrize("scenario", ["reject", "truncated"])
async def test_metered_content_failure_stays_failed_and_next_case_remains_authorized(
    store, scenario
):
    from src.workspace.d5_campaign_policy import audit_outcomes, guard_order

    packet = setup(store)
    transport = {}

    def factory(key):
        transport[key] = CampaignTransport(key, scenario=scenario)
        return transport[key]

    report = await run(store, packet, offline=True, transport_factory=factory, checkpoint_after=1)
    assert report["stop"] is None
    first = report["outcomes"][packet["schedule"][0]]
    assert first["state"] == "failed" and first["content_rejection"]["accepted"] is False
    assert first["quality_acceptance"] is None
    assert report["accounting"]["cumulative"]["unknown_usd"] == "0.425066"
    assert len(next(iter(transport.values())).contacts) == (8 if scenario == "reject" else 2)
    with store.pool.connection() as conn:
        scope = "d5-" + packet["packet_digest"][:24]
        bound = conn.execute(
            "SELECT data FROM workspace_d5_scopes WHERE scope_id=%s", (scope,)
        ).fetchone()[0]
        guard_order(conn, {**bound, "id": scope}, packet["schedule"][1])
        assert len(audit_outcomes(conn, scope)) == 1


async def test_completed_outcome_financial_mutation_is_detected(store):
    from src.workspace.d5_campaign_policy import audit_outcomes

    packet = setup(store)
    report = await run(store, packet, offline=True, checkpoint_after=1)
    job = next(iter(report["outcomes"].values()))["job_id"]
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_spend_reservations SET workflow=workflow+0.01 WHERE job_id=%s", (job,)
        )
        with pytest.raises(AdmissionError, match="campaign_accounting_or_outcome_corruption"):
            audit_outcomes(conn, "d5-" + packet["packet_digest"][:24])


async def test_operator_template_is_not_authorization_and_cannot_change_bound_limits(
    store, monkeypatch, tmp_path
):
    import sys
    from contextlib import contextmanager

    from src.workspace import d5_benchmark, d5_campaign, d5_campaign_operator
    from src.workspace.d5_campaign_extension import active, record_external
    from src.workspace.d5_campaign_operator import record

    packet = setup(store, authorize=False)
    receipt = template(packet)
    receipt["limits"]["messages"] += 1
    # Template must not alias the packet's immutable dictionaries.
    assert packet["limits"]["messages"] == 44
    with pytest.raises(AdmissionError, match="packet_binding_drift"):
        record(store, packet, receipt)
    path = tmp_path / "packet.json.gz"
    auth = tmp_path / "authorization.json"
    d5_benchmark.write(path, packet)
    monkeypatch.setattr(
        sys, "argv", ["operator", "template", "--packet", str(path), "--authorization", str(auth)]
    )
    d5_campaign_operator.main()
    assert d5_benchmark.read(auth)["approved"] is False
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "0")
    with pytest.raises(AdmissionError, match="offline_disabled_key"):
        authorize_fixture(store, packet)
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    authorize_fixture(store, packet)
    with store.pool.connection() as conn:
        approved = active(conn, "evaluation")[0]
    assert record_external(store, approved)["duplicate"] is True
    approved_path = tmp_path / "synthetic-approved.json"
    d5_benchmark.write(approved_path, approved)

    @contextmanager
    def database(_):
        yield store.pool

    monkeypatch.setattr(d5_benchmark, "database", database)
    monkeypatch.setenv("D5_POSTGRES_URL", "disposable-store-fixture")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "operator",
            "record",
            "--packet",
            str(path),
            "--authorization",
            str(approved_path),
            "--receipt",
            str(tmp_path / "duplicate.json"),
        ],
    )
    d5_campaign_operator.main()
    assert d5_benchmark.read(tmp_path / "duplicate.json")["scope"]["duplicate"] is True
    monkeypatch.setattr(sys, "argv", ["campaign", "verify", "--packet", str(path)])
    d5_campaign.main()
    monkeypatch.setattr(
        sys,
        "argv",
        ["campaign", "report", "--packet", str(path), "--out", str(tmp_path / "report")],
    )
    d5_campaign.main()
    assert (tmp_path / "report/index.html").exists()
    assert (
        d5_benchmark.read(tmp_path / "report/results.json")["denominators"]["unrun_evaluation"] == 8
    )
    monkeypatch.setattr(
        sys, "argv", ["campaign", "run", "--packet", str(path), "--fixture-repair-all"]
    )
    with pytest.raises(AdmissionError, match="fixture_option_offline_only"):
        d5_campaign.main()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "operator",
            "revoke",
            "--packet",
            str(path),
            "--authorization",
            str(approved_path),
            "--receipt",
            str(tmp_path / "revocation.json"),
        ],
    )
    d5_campaign_operator.main()
    with store.pool.connection() as conn, pytest.raises(AdmissionError, match="revocation_drift"):
        active(conn, "evaluation")
