"""Synthetic accounting and A/B permissions in disposable Postgres; no provider I/O."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError
from src.workspace.d5_adapter import D5Adapter, D5MeasurementAdapter
from src.workspace.d5_authorization import grant_external, stage_template
from src.workspace.d5_benchmark import read, run
from src.workspace.d5_coverage_packet import CASE_IDS, freeze_controls, owners
from src.workspace.d5_coverage_replay import CoverageTransport, capture, fixture_A
from src.workspace.d5_fixture import prepare_projects
from src.workspace.d5_freeze import compile_inputs, restore_input
from src.workspace.programme_capacity import record_external as activate
from src.workspace.qualification_budget import census
from src.workspace.store import ConflictError
from tests import test_workspace_programme_amendments as am
from tests import test_workspace_programme_capacity as cap
from tests.test_workspace_store import ingest

store = cap.store
if hasattr(cap, "workspace_pg"):
    workspace_pg_proc, workspace_pg = cap.workspace_pg_proc, cap.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
ROOT = Path(__file__).resolve().parent.parent
MANIFEST = (
    ROOT / "planning/14-explore-and-research-modes/d5/evidence/request-coverage-v8/proposal.json.gz"
)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def setup(store, *, authorize=True):
    template, _ = cap.setup(store)
    activate(store, cap.approved(template))
    am.seed_failed(store, 7, 23)
    with store.pool.connection() as c:
        h = census(c, "a")
        row = c.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id='synthetic-failed-programme-29'"
        ).fetchone()[0]
        row["adapter"]["contacts"] = [
            {"endpoint": endpoint, "state": "completed", "ordinal": i}
            for i, endpoint in enumerate(
                ["messages"] * (61 - h["messages"]) + ["messages/count_tokens"] * (81 - h["counts"])
            )
        ]
        delta = Decimal("1.779493") - Decimal(h["known_usd"])
        row["adapter"]["workflow_usd"] = str(delta)
        c.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id='synthetic-failed-programme-29'",
            (Jsonb(row),),
        )
        c.execute(
            "UPDATE workspace_spend_reservations SET amount=%s,workflow=%s WHERE job_id='synthetic-failed-programme-29'",
            (delta, delta),
        )
    manifest = read(MANIFEST)
    import gzip
    import json

    archive = json.loads(
        gzip.decompress(
            (ROOT / "tests/fixtures/d5/stage-c-v8r4b/coverage-controls.json.gz").read_bytes()
        )
    )
    mids = {
        r["material_id"] for case in manifest["cases"] for r in case["sealed"]["units"].values()
    }
    for m in archive["materials"]:
        if m["material_id"] not in mids:
            continue
        ingest(
            store,
            work_id=m["work_id"],
            version_id=m["version_id"],
            source_record_id=m["work_id"],
            abstract=m["pages"][0],
            content_hash=m["source_hash"],
        )
        with store.pool.connection() as c:
            c.execute(
                "INSERT INTO workspace_material VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (m["material_id"], m["version_id"], m["content_hash"], m["scope"], Jsonb(m)),
            )
    snapshot = capture(store, store, "evaluation")
    p = freeze_controls(manifest, snapshot, snapshot["programme"])
    prepare_projects(store, p)
    if authorize:
        fixture_A(store, p)
    return p, snapshot


def grant_B(store, p):
    receipt = stage_template(store, "d5-" + p["packet_digest"][:24], ["B"])
    receipt.update(
        approved=True,
        approved_by="Separate synthetic fixture, not human approval",
        approved_at=datetime.now(UTC).isoformat(),
    )
    return grant_external(store, receipt["scope_id"], receipt)


def adapter(store, p, key):
    entry = compile_inputs(p)[key]
    inputs = restore_input(entry["input"])
    cls = D5MeasurementAdapter if entry["stage"] == "A" else D5Adapter
    return cls(store, entry["owner"], inputs, transport=httpx.MockTransport(CoverageTransport(key)))


async def test_A_then_B_requires_separate_grant_and_preserves_full_history(store):
    p, snapshot = setup(store)
    assert p["planned_development_cases"] == CASE_IDS and all(
        c["cohort"] == "development" for c in p["cases"]
    )
    assert len(compile_inputs(p)) == 6 and p["probes"] == []
    A = await run(store, p, "A", offline=True)
    assert (
        A["accounting"]["new_scope"]["counts"] == 3
        and A["accounting"]["new_scope"]["messages"] == 0
    )
    assert len(A["accounting"]["new_scope"]["generation_job_ids"]) == 0
    with pytest.raises(AdmissionError, match="d5_stage_not_authorized"):
        await run(store, p, "B", offline=True)
    with store.pool.connection() as c:
        assert census(c, owners(p)[0], members=list(owners(p)))["counts"] == 3
    grant_B(store, p)
    B = await run(store, p, "B", offline=True)
    assert [c["state"] for c in B["cases"]] == ["ready"] * 3
    assert B["accounting"]["cumulative_programme_jobs"] == 33
    assert B["accounting"]["actual_new_messages"] == B["accounting"]["actual_new_counts"] == 0
    assert B["accounting"]["new_scope"]["messages"] == 8
    assert B["accounting"]["new_scope"]["counts"] == 11
    assert len(B["accounting"]["new_scope"]["generation_job_ids"]) == 3
    assert B["accounting"]["cumulative"]["known_usd"] == "1.779493"
    first = B["raw_results"][CASE_IDS[0]]
    assert [s["stage"] for s in first["steps"]] == ["draft", "check", "repair", "check"]
    assert first["steps"][0]["output"] != first["steps"][2]["output"]
    assert all(c["human_review"] is None for c in B["cases"])
    assert B["checker_qualified"] is False
    # Same completed identity is an inspection, never a second contact or job.
    repeated = await run(store, p, "B", offline=True)
    assert repeated["accounting"]["new_scope"] == B["accounting"]["new_scope"]
    assert snapshot["history"]["messages"] == 61 and snapshot["history"]["counts"] == 81


async def test_complete_maximum_envelope_and_stage_contact_limits(store, monkeypatch):
    p, _ = setup(store)
    await run(store, p, "A", offline=True)
    grant_B(store, p)
    import src.workspace.d5_coverage_replay as r

    original = r.CoverageTransport
    monkeypatch.setattr(r, "CoverageTransport", lambda key: original(key, repair_all=True))
    result = await run(store, p, "B", offline=True)
    assert result["accounting"]["new_scope"]["messages"] == 12
    assert result["accounting"]["new_scope"]["counts"] == 15
    assert result["accounting"]["cumulative"]["messages"] == 73
    assert result["accounting"]["cumulative"]["counts"] == 96
    assert all(len(result["raw_results"][key]["steps"]) == 4 for key in CASE_IDS)
    for key, endpoint in [
        ("measure-1", "messages/count_tokens"),
        ("measure-1", "messages"),
        (CASE_IDS[0], "messages/count_tokens"),
        (CASE_IDS[0], "messages"),
    ]:
        a = adapter(store, p, key)
        jid = a.start(a.inputs.settings["d5_request_id"])["id"]
        with store.pool.connection() as c, pytest.raises(AdmissionError, match="cap_exceeded"):
            a._contact_scope(c, jid, endpoint)


async def test_B_cannot_skip_A_even_with_its_grant_and_C_D_are_out_of_scope(store):
    p, _ = setup(store)
    grant_B(store, p)
    a = adapter(store, p, CASE_IDS[0])
    with pytest.raises(AdmissionError, match="three_bound_measurements"):
        a.start(a.inputs.settings["d5_request_id"])
    for stage in ("C", "D"):
        with pytest.raises(AdmissionError, match="separate_B_only"):
            stage_template(store, "d5-" + p["packet_digest"][:24], [stage])
    with pytest.raises(AdmissionError, match="coverage_A_B_only"):
        await run(store, p, "C", offline=True)


@pytest.mark.parametrize("field", ["model", "settings", "case", "request"])
async def test_drift_or_extra_identity_refused_before_transport(store, field):
    p, _ = setup(store)
    await run(store, p, "A", offline=True)
    grant_B(store, p)
    a = adapter(store, p, CASE_IDS[0])
    from dataclasses import replace

    if field == "model":
        a.inputs = replace(a.inputs, model_id="unapproved-model")
    else:
        settings = deepcopy(a.inputs.settings)
        if field == "settings":
            settings["output_tokens"] = 4001
        elif field == "case":
            settings["d5_case_id"] = "extra-job"
        else:
            settings["d5_request_id"] = "alternate-request"
        a.inputs = replace(a.inputs, settings=settings)
    with pytest.raises((AdmissionError, ConflictError, ValueError)):
        a.start(a.inputs.settings["d5_request_id"])
    with store.pool.connection() as c:
        assert census(c, owners(p)[0], members=list(owners(p)))["messages"] == 0


async def test_parent_and_programme_expiry_and_revocation_are_enforced(store):
    p, _ = setup(store)
    expiry = datetime.fromisoformat(p["programme"]["expires_at"])
    with store.pool.connection() as c:
        assert (
            c.execute(
                "SELECT expires_at FROM workspace_d5_scopes WHERE scope_id=%s",
                ("d5-" + p["packet_digest"][:24],),
            ).fetchone()[0]
            <= expiry
        )
    a = adapter(store, p, "measure-1")
    with store.pool.connection() as c:
        c.execute(
            "UPDATE workspace_d5_scopes SET state='revoked' WHERE scope_id=%s",
            ("d5-" + p["packet_digest"][:24],),
        )
    with pytest.raises(AdmissionError, match="revoked_expired"):
        a.start(a.inputs.settings["d5_request_id"])


async def test_preparation_has_no_authority_and_parent_cannot_outlive_programme(
    store, tmp_path, monkeypatch
):
    import json
    from contextlib import nullcontext

    from src.workspace import d5_operator as operator
    from src.workspace.admission import _digest
    from src.workspace.d5_authorization import case_bindings, record_external

    p, _ = setup(store, authorize=False)
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(p))
    receipt = tmp_path / "prepared.json"
    monkeypatch.setenv("D5_POSTGRES_URL", "disposable-fixture")
    monkeypatch.setattr(operator, "database", lambda *_: nullcontext(store.pool))
    monkeypatch.setattr(
        "sys.argv", ["operator", "prepare", "--packet", str(path), "--receipt", str(receipt)]
    )
    operator.main()
    assert read(receipt)["approval_created"] is False
    with store.pool.connection() as c:
        assert c.execute("SELECT count(*) FROM workspace_d5_scopes").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0
    compiled = compile_inputs(p)
    now = datetime.now(UTC)
    bad = {
        "approved": True,
        "approved_by": "Synthetic test only",
        "approved_at": now.isoformat(),
        "expires_at": (
            datetime.fromisoformat(p["programme"]["expires_at"]) + timedelta(microseconds=1)
        ).isoformat(),
        "packet_digest": p["packet_digest"],
        "scope_id": "d5-" + p["packet_digest"][:24],
        "limits": p["limits"],
        "members": sorted({e["owner"] for e in compiled.values()}),
        "case_bindings_digest": _digest(case_bindings(compiled)),
        "transport_mode": "mock",
        "authorization_kind": "offline_fixture",
        "stages": ["A"],
    }
    with pytest.raises(AdmissionError, match="expiry_drift"):
        record_external(
            store,
            packet_digest=p["packet_digest"],
            scope_id=bad["scope_id"],
            program_id=p["program_id"],
            compiled=compiled,
            receipt=bad,
            expected_history=p["history"],
        )


async def test_global_programme_job_and_count_limits_remain_authoritative(store):
    from src.workspace.d5_scope import guard_scope

    p, _ = setup(store)
    await run(store, p, "A", offline=True)
    grant_B(store, p)
    am.seed_failed(store, 30, 4)
    a = adapter(store, p, CASE_IDS[0])
    with pytest.raises(AdmissionError, match="program_job_cap_exceeded"):
        a.start(a.inputs.settings["d5_request_id"])
    with store.pool.connection() as c:
        h = census(c, "a", members=["a", *owners(p)])
        row = c.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id='synthetic-failed-programme-33'"
        ).fetchone()[0]
        row["adapter"]["contacts"] = [
            {"endpoint": "messages/count_tokens", "state": "completed", "ordinal": i}
            for i in range(99 - h["counts"])
        ]
        c.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id='synthetic-failed-programme-33'",
            (Jsonb(row),),
        )
    with store.pool.connection() as c:
        row = c.execute(
            "SELECT data FROM workspace_budget_policies WHERE owner=%s", (owners(p)[0],)
        ).fetchone()[0]
        with pytest.raises(AdmissionError, match="program_contact_cap_exceeded"):
            guard_scope(c, owners(p)[0], a.inputs.snapshot(), row, endpoint="messages/count_tokens")


async def test_source_drift_or_revoked_capacity_stops_before_any_B_contact(store):
    from src.workspace.programme_capacity import revoke

    p, _ = setup(store)
    await run(store, p, "A", offline=True)
    grant_B(store, p)
    a = adapter(store, p, "measure-1")
    version = p["cases"][0]["sealed"]["assistance"]["version_id"]
    with store.pool.connection() as c:
        c.execute(
            "UPDATE workspace_versions SET data=jsonb_set(data,'{content_hash}','\"synthetic-drift\"') WHERE version_id=%s",
            (version,),
        )
    with pytest.raises(AdmissionError, match="frozen_source_changed"):
        await run(store, p, "B", offline=True)
    with store.pool.connection() as c:
        assert census(c, owners(p)[0], members=list(owners(p)))["messages"] == 0
        aid = c.execute(
            "SELECT amendment_id FROM workspace_programme_capacity_amendments"
        ).fetchone()[0]
    revoke(store, aid, actor="Synthetic fixture only")
    with store.pool.connection() as c, pytest.raises(AdmissionError):
        a._contact_scope(c, "not-a-live-contact", "messages/count_tokens")


@pytest.mark.parametrize("mutation", ["body", "result", "input"])
async def test_B_rejects_tampered_A_receipt_bindings(store, mutation):
    p, _ = setup(store)
    await run(store, p, "A", offline=True)
    grant_B(store, p)
    with store.pool.connection() as c:
        row = c.execute(
            "SELECT j.id,j.data FROM workspace_d5_case_runs r JOIN workspace_generation_jobs j ON j.id=r.job_id WHERE r.scope_id=%s AND r.case_id='measure-1'",
            ("d5-" + p["packet_digest"][:24],),
        ).fetchone()
        data = row[1]
        if mutation == "body":
            data["adapter"]["contacts"][0]["body"]["model"] = "wrong-model"
        elif mutation == "result":
            data["result"]["count_request_digest"] = "wrong-digest"
        else:
            data["sealed_input"]["settings"]["output_tokens"] = 4001
        c.execute("UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), row[0]))
    a = adapter(store, p, CASE_IDS[0])
    with pytest.raises(AdmissionError, match="measurement_receipt_binding"):
        a.start(a.inputs.settings["d5_request_id"])
    with store.pool.connection() as c:
        assert census(c, owners(p)[0], members=list(owners(p)))["messages"] == 0


async def test_invalid_completed_response_stops_scope_without_replay(store):
    p, _ = setup(store)
    await run(store, p, "A", offline=True)
    grant_B(store, p)
    transport = CoverageTransport(CASE_IDS[0])

    async def broken(request):
        response = await transport(request)
        if not request.url.path.endswith("count_tokens"):
            body = response.json()
            body["stop_reason"] = "max_tokens"
            body["content"][0]["text"] = '{"response":'
            return httpx.Response(200, json=body)
        return response

    a = adapter(store, p, CASE_IDS[0])
    a.transport = httpx.MockTransport(broken)
    job = a.start(a.inputs.settings["d5_request_id"])
    with pytest.raises((AdmissionError, ValueError)):
        await a.advance(job["id"])
    assert len(transport.contacts) == 2
    with store.pool.connection() as c:
        assert (
            c.execute(
                "SELECT state FROM workspace_d5_scopes WHERE scope_id=%s",
                ("d5-" + p["packet_digest"][:24],),
            ).fetchone()[0]
            == "stopped"
        )
    b = adapter(store, p, CASE_IDS[1])
    with pytest.raises(AdmissionError, match="revoked_expired"):
        b.start(b.inputs.settings["d5_request_id"])
    with store.pool.connection() as c:
        assert census(c, owners(p)[0], members=list(owners(p)))["messages"] == 1


@pytest.mark.parametrize(
    "module_name,table",
    [
        ("programme_successors", "workspace_programme_successor_amendments"),
        ("programme_third_amendment", "workspace_programme_third_amendments"),
        ("programme_capacity", "workspace_programme_capacity_amendments"),
    ],
)
async def test_validation_audits_predecessor_once_without_cross_operation_cache(
    store, monkeypatch, module_name, table
):
    import importlib

    template, _ = cap.setup(store)
    activate(store, cap.approved(template))
    module = importlib.import_module("src.workspace." + module_name)
    original = module._parent
    calls = []

    def parent(*args):
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(module, "_parent", parent)
    with store.pool.connection() as c:
        receipt = c.execute("SELECT record FROM " + table).fetchone()[0]
        first = module._validate(c, receipt, "evaluation")
        assert len(calls) == 1
        second = module._validate(c, receipt, "evaluation")
        assert len(calls) == 2 and first == second
