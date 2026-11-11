"""Protected v9 scope on disposable synthetic accounting; zero provider contacts."""

import json
from copy import deepcopy
from decimal import Decimal

import httpx
import pytest
from jsonschema import validate
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError
from src.workspace.d5_benchmark import run
from src.workspace.d5_coverage_authority_packet import CASE_ID, EXPECTED, freeze, verify_shapes
from src.workspace.d5_coverage_packet import owners
from src.workspace.d5_coverage_policy import SHAPED_LIMITS, SHAPED_PROFILE, profile_limits
from src.workspace.d5_coverage_replay import CoverageTransport, capture, fixture_A
from src.workspace.d5_fixture import prepare_projects
from src.workspace.d5_freeze import compile_inputs, verify
from src.workspace.qualification_budget import census
from tests import test_workspace_coverage_runner as old
from tests.test_workspace_coverage_authority import ARCHIVED
from tests.test_workspace_programme_amendments import seed_failed

store = old.store
if hasattr(old, "workspace_pg"):
    workspace_pg_proc, workspace_pg = old.workspace_pg_proc, old.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def setup(store):
    old.setup(store, authorize=False, canonical=True)
    seed_failed(store, 30, 2)
    with store.pool.connection() as c:
        h = census(c, "a")
        row = c.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id='synthetic-failed-programme-31'"
        ).fetchone()[0]
        row["adapter"]["contacts"] = [
            {"endpoint": e, "state": "completed", "ordinal": i}
            for i, e in enumerate(["messages"] * (EXPECTED[1] - h["messages"]) + ["messages/count_tokens"] * (EXPECTED[2] - h["counts"]))
        ]
        delta = Decimal(EXPECTED[3]) - Decimal(h["known_usd"])
        row["adapter"]["workflow_usd"] = str(delta)
        c.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id='synthetic-failed-programme-31'",
            (Jsonb(row),),
        )
        c.execute(
            "UPDATE workspace_spend_reservations SET amount=%s,workflow=%s WHERE job_id='synthetic-failed-programme-31'",
            (delta, delta),
        )
    snapshot = capture(store, store, "evaluation", expected=EXPECTED)
    packet = freeze(snapshot)
    verify(packet)
    prepare_projects(store, packet)
    fixture_A(store, packet)
    return packet


class ArchivedTransport(CoverageTransport):
    """Preserved failure or explicitly synthetic correction; never model evidence."""

    def __init__(self, case_id, *, corrected=False):
        super().__init__(case_id)
        self.corrected = corrected

    async def __call__(self, request):
        body = json.loads(request.content)
        response = await super().__call__(request)
        if request.url.path.endswith("count_tokens"):
            return response
        context = json.loads(body["messages"][0]["content"])
        if context["phase"] != "check":
            payload = json.loads(ARCHIVED["text"])
            if self.corrected:
                for claim in payload["response"]["claims"]:
                    del claim["part_ids"]
                validate(payload, body["output_config"]["format"]["schema"])
            raw = response.json()
            raw["content"][0]["text"] = json.dumps(payload)
            return httpx.Response(200, json=raw)
        return response


class MisclassifiedContext(ArchivedTransport):
    """Synthetic semantic error; valid associations must not imply coverage."""

    async def __call__(self, request):
        response = await super().__call__(request)
        if request.url.path.endswith("count_tokens"):
            return response
        body = json.loads(request.content)
        context = json.loads(body["messages"][0]["content"])
        value = response.json()
        payload = json.loads(value["content"][0]["text"])
        if context["phase"] == "check":
            assert context["claim_request_index"]["c5"]["answer"] == ["p2", "p3"]
            payload["coverage_checks"][2]["decision"] = "lacks_evidence"
            payload["coverage_checks"][2]["reason"] = "Synthetic: the reported result does not answer unspecified protocol details."
        else:
            payload["response"]["coverage"]["p3"] = {"status": "answered", "gap": "none", "answer_claim_ids": ["c5"], "context_claim_ids": []}
        validate(payload, body["output_config"]["format"]["schema"])
        value["content"][0]["text"] = json.dumps(payload)
        return httpx.Response(200, json=value)


async def test_context_cannot_become_answer_by_valid_mapping_or_repair(store, monkeypatch):
    p = setup(store)
    await run(store, p, "A", offline=True)
    old.grant_B(store, p)
    transport = MisclassifiedContext(CASE_ID, corrected=True)
    monkeypatch.setattr("src.workspace.d5_coverage_replay.CoverageTransport", lambda _: transport)
    with pytest.raises(AdmissionError, match="d5_request_or_claim_quality_unresolved"):
        await run(store, p, "B", offline=True)
    from src.workspace.d5_coverage_packet import report_controls

    result = report_controls(store, p)
    observed = result["raw_results"][CASE_ID]
    assert observed["state"] == "failed" and observed["result"] is None
    assert len([c for c in observed["contacts"] if c["endpoint"] == "messages"]) == 4
    assert [s["stage"] for s in observed["steps"]] == ["draft", "check", "repair"]
    assert observed["steps"][1]["output"]["coverage_checks"][2]["decision"] == "lacks_evidence"
    assert observed["human_review"] is None


async def test_fresh_A_one_B_requires_grant_then_exact_four_stage_repair(store):
    p = setup(store)
    assert p["limits"] == SHAPED_LIMITS and p["scope_profile"] == SHAPED_PROFILE
    assert p["planned_development_cases"] == [CASE_ID] and len(compile_inputs(p)) == 2
    A = await run(store, p, "A", offline=True)
    assert A["accounting"]["new_scope"]["counts"] == 1
    assert A["accounting"]["new_scope"]["messages"] == 0
    with pytest.raises(AdmissionError, match="d5_stage_not_authorized"):
        await run(store, p, "B", offline=True)
    old.grant_B(store, p)
    result = await run(store, p, "B", offline=True)
    assert result["cases"][0]["state"] == "ready"
    assert result["accounting"]["new_scope"]["counts"] == 5
    assert result["accounting"]["new_scope"]["messages"] == 4
    assert result["accounting"]["cumulative_programme_jobs"] == 33
    assert result["accounting"]["cumulative"]["counts"] == 92
    assert result["accounting"]["cumulative"]["known_usd"] == EXPECTED[3]
    assert result["accounting"]["actual_new_messages"] == 0
    # Journal below proves mandatory check, single repair and recheck regardless of result wrapper.
    with store.pool.connection() as c:
        data = c.execute(
            "SELECT data FROM workspace_generation_jobs WHERE owner=%s",
            (owners(p)[0],),
        ).fetchone()[0]
    assert [s["stage"] for s in data["adapter"]["steps"]] == ["draft", "check", "repair", "check"]


@pytest.mark.parametrize("corrected", [False, True])
async def test_preserved_actual_draft_through_production_adapter(store, monkeypatch, corrected):
    p = setup(store)
    await run(store, p, "A", offline=True)
    old.grant_B(store, p)
    transport = ArchivedTransport(CASE_ID, corrected=corrected)
    monkeypatch.setattr("src.workspace.d5_coverage_replay.CoverageTransport", lambda _: transport)
    if corrected:
        result = await run(store, p, "B", offline=True)
    else:
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            await run(store, p, "B", offline=True)
        from src.workspace.d5_coverage_packet import report_controls

        result = report_controls(store, p)
    assert result["cases"][0]["state"] == ("ready" if corrected else "failed")
    message_bodies = [r for r in transport.contacts if r["endpoint"].endswith("/messages")]
    assert len(message_bodies) == (4 if corrected else 1)
    if corrected:
        row = result["cases"][0]["request_coverage"][2]
        assert row["answer_claim_ids"] == [] and row["context_claim_ids"] == ["c4", "c5"]
        assert row["status"] == "lacks_evidence"
    assert result["accounting"]["actual_new_messages"] == 0


@pytest.mark.parametrize(
    "mutation", ["schedule", "limits", "wire", "profile", "reuse", "expiry", "source"]
)
async def test_packet_drift_is_refused_before_dispatch(store, mutation):
    p = setup(store)
    bad = deepcopy(p)
    if mutation == "schedule":
        bad["planned_development_cases"].append("extra")
    elif mutation == "limits":
        bad["limits"]["messages"] = 5
    elif mutation == "wire":
        bad["cases"][0]["sealed"]["response_schemas"]["wire"] = {}
    elif mutation == "profile":
        bad["scope_profile"] = "other"
    elif mutation == "reuse":
        bad["measurement_reuse"] = ["measure-1"]
    elif mutation == "expiry":
        bad["programme"]["expires_at"] = "2026-11-14T07:24:01"
    else:
        bad["cases"][0]["sealed"]["units"][next(iter(bad["cases"][0]["sealed"]["units"]))][
            "quote"
        ] = "mutated"
    with pytest.raises((AdmissionError, ValueError)):
        verify_shapes(bad)
    with store.pool.connection() as c:
        assert census(c, owners(p)[0], members=list(owners(p)))["counts"] == 0


async def test_unknown_profile_refused():
    with pytest.raises(AdmissionError, match="not_supported"):
        profile_limits("invented")


async def test_successor_cli_requires_disabled_key_and_explicit_packet(monkeypatch, tmp_path):
    from src.workspace.d5_coverage_authority_packet import main

    monkeypatch.setattr("sys.argv", ["shapes", "freeze", "--snapshot", str(tmp_path / "s")])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-not-a-real-key")
    with pytest.raises(AdmissionError, match="disabled_key"):
        main()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    with pytest.raises(SystemExit):
        main()


async def test_successor_cli_round_trip_and_sealed_predecessor(monkeypatch, tmp_path, store):
    from contextlib import nullcontext

    from src.workspace import d5_coverage_authority_packet as m
    from src.workspace.d5_benchmark import read, write

    p = setup(store)
    # This separate CLI test uses captured fixture data, never the live ledger.
    snapshot = {"programme": p["programme"], "history": p["history"]}
    s = tmp_path / "snapshot.json.gz"
    write(s, snapshot)
    monkeypatch.setattr(m, "freeze", lambda value: p if value == snapshot else None)
    monkeypatch.setattr(
        "sys.argv",
        ["shapes", "freeze", "--snapshot", str(s), "--packet", str(tmp_path / "packet.json.gz")],
    )
    m.main()
    assert read(tmp_path / "packet.json.gz")["approved"] is False
    monkeypatch.setenv("D5_LEDGER_POSTGRES_URL", "ignored-disposable")
    monkeypatch.setattr("src.workspace.d5_benchmark.database", lambda _: nullcontext(object()))
    monkeypatch.setattr(
        "src.workspace.d5_coverage_replay.capture", lambda *args, **kwargs: snapshot
    )
    monkeypatch.setattr(
        "sys.argv", ["shapes", "capture", "--snapshot", str(tmp_path / "captured.json.gz")]
    )
    m.main()
    assert read(tmp_path / "captured.json.gz") == snapshot
    monkeypatch.setattr(m, "PREDECESSOR", "stale")
    with pytest.raises(AdmissionError, match="predecessor_changed"):
        m.predecessor()
