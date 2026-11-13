"""Prospective production-adapter replay; all grants, finance and transport synthetic.

The prior provider failures are immutable regressions, not successful results.
"""

import json
from copy import deepcopy

import httpx
import pytest

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign import CampaignTransport, run
from src.workspace.d5_campaign_operator import authorize_fixture, template
from src.workspace.d5_campaign_v14_packet import capture, freeze
from tests import test_workspace_d5_campaign as v13

store = v13.store
if hasattr(v13, "workspace_pg"):
    workspace_pg_proc, workspace_pg = v13.workspace_pg_proc, v13.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.timeout(240)]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


class StoppedV13Transport(CampaignTransport):
    """Synthetic reproduction of the observed contact/usage classes, not old jobs."""

    async def __call__(self, request):
        body = json.loads(request.content)
        phase = json.loads(body["messages"][0]["content"])["phase"]
        count = 10992 if phase == "check" else 7983 if self.key.endswith("dev-learn") else 10766
        if request.url.path.endswith("count_tokens"):
            self.contacts.append((request.url.path, _digest(body)))
            return httpx.Response(200, json={"input_tokens": count})
        if self.key.endswith("dev-compare"):
            self.contacts.append((request.url.path, _digest(body)))
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "The compiled grammar is too large, which would cause performance issues. Simplify your tool schemas or reduce the number of strict tools.",
                    },
                    "request_id": "synthetic-no-provider-grammar-rejection",
                },
            )
        response = (await super().__call__(request)).json()
        response["usage"] = {
            "input_tokens": count,
            "output_tokens": 3200 if phase == "check" else 901,
        }
        if phase == "check":
            # Even syntactically COMPLETE verdict JSON cannot override max_tokens.
            json.loads(response["content"][0]["text"])
            response["stop_reason"] = "max_tokens"
        return httpx.Response(200, json=response)


async def setup_successor(store, *, authorize=True):
    old = v13.setup(store)
    stopped = await run(store, old, offline=True, transport_factory=StoppedV13Transport)
    assert stopped["stop"]["case_id"] == "campaign-dev-compare"
    # Mock execution has zero financial spend by design. Explicitly seed the
    # copied post-stop accounting checkpoint in this disposable fixture only;
    # these values are not claimed as live usage or produced by fake counts.
    from src.workspace.d5_campaign_policy import job_binding
    from src.workspace.d5_campaign_report import results

    learn = stopped["raw_results"]["campaign-dev-learn"]["id"]
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_spend_reservations SET workflow=0.024976,judge=0.107968 WHERE job_id=%s",
            (learn,),
        )
        conn.execute(
            "UPDATE workspace_d5_campaign_outcomes SET job_digest=%s WHERE job_id=%s",
            (job_binding(conn, learn)[2], learn),
        )
    stopped = results(store, old, stop=stopped["stop"])
    cumulative = stopped["accounting"]["cumulative"]
    assert (cumulative["funded_programme_jobs"], cumulative["messages"], cumulative["counts"]) == (
        35,
        68,
        93,
    )
    assert cumulative["known_usd"] == "1.986755"
    assert cumulative["unknown_usd"] == cumulative["pending_usd"] == "0.875066"
    assert stopped["cases"][0]["assessment_binding"]["status"] == "unavailable"
    assert stopped["cases"][0]["machine_coverage"] is None
    assert stopped["cases"][0]["whole_claim_support"] is None
    snapshot = capture(store, "evaluation")
    packet = freeze(store, snapshot)
    if authorize:
        authorize_fixture(store, packet)
    return packet, stopped


async def test_v14_protected_successor_keeps_both_holds_and_binds_compact_check(store):
    packet, old = await setup_successor(store)
    transports = {}

    def factory(key):
        transports[key] = CampaignTransport(key)
        return transports[key]

    report = await run(store, packet, offline=True, transport_factory=factory, checkpoint_after=1)
    if report["stop"]:
        print(
            json.dumps(
                {
                    "stop": report["stop"],
                    "outcomes": report["outcomes"],
                    "raw": {
                        k: {
                            "state": s["state"],
                            "stages": [x["stage"] for x in s["steps"]],
                            "contacts": [
                                {
                                    "stage": c["stage"],
                                    "endpoint": c["endpoint"],
                                    "state": c["state"],
                                    "status": c.get("response", {}).get("http_status"),
                                }
                                for c in s["contacts"]
                            ],
                        }
                        for k, s in report["raw_results"].items()
                    },
                },
                indent=2,
            )
        )
        from src.workspace.d5_campaign_v14_policy import development_contract

        with store.pool.connection() as conn:
            development_contract(conn, "d5-" + packet["packet_digest"][:24], packet["schedule"][0])
    assert report["stop"] is None
    assert len(report["outcomes"]) == 1
    case = report["cases"][0]
    assert case["state"] == "ready"
    assert case["assessment_binding"]["status"] == "bound"
    assert case["assessment_binding"]["checker_normalization_revision"].endswith("v14")
    assert report["accounting"]["cumulative"]["unknown_usd"] == "0.875066"
    assert report["accounting"]["historical"]["known_usd"] == "1.986755"
    assert old["cases"][0]["state"] == "failed"
    assert report["human_qualification"] is False


async def test_v14_unapproved_budget_or_scope_refuses_before_transport(store):
    packet, _ = await setup_successor(store, authorize=False)
    calls = []
    with pytest.raises(AdmissionError):
        await run(store, packet, offline=True, transport_factory=lambda key: calls.append(key))
    assert calls == []
    receipt = template(packet)
    assert receipt["budget_adjustment_approved"] is False
    assert packet["campaign_extension"]["core"]["dollar_adjustment"]["approved"] is False


async def test_v14_bad_development_contract_stops_before_second_or_evaluation(store):
    packet, _ = await setup_successor(store)

    class TruncatedCheck(CampaignTransport):
        async def __call__(self, request):
            response = await super().__call__(request)
            body = json.loads(request.content)
            if (
                request.url.path.endswith("/messages")
                and json.loads(body["messages"][0]["content"])["phase"] == "check"
            ):
                value = response.json()
                json.loads(value["content"][0]["text"])
                value["stop_reason"] = "max_tokens"
                return httpx.Response(200, json=value)
            return response

    calls = []

    def factory(key):
        calls.append(key)
        return TruncatedCheck(key)

    report = await run(store, packet, offline=True, transport_factory=factory)
    assert report["stop"]["reason"] == "campaign_development_contract_incomplete"
    assert calls == [packet["schedule"][0]]
    assert report["cases"][0]["machine_coverage"] is None
    assert report["cases"][0]["whole_claim_support"] is None
    assert report["denominators"]["unrun_evaluation"] == 8


async def test_v14_exact_frozen_changes_refuse(store):
    from src.workspace.d5_freeze import verify

    packet, _ = await setup_successor(store, authorize=False)
    for field in ("limits", "progression", "operation_routes"):
        bad = deepcopy(packet)
        bad[field] = {}
        bad["packet_digest"] = _digest({k: v for k, v in bad.items() if k != "packet_digest"})
        with pytest.raises(AdmissionError):
            verify(bad)
