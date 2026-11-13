"""AUD-01 through production campaign/admission/adapter; synthetic transport only."""

import json

import httpx
import pytest

from src.workspace.d5_campaign import CampaignTransport, run
from tests import test_workspace_d5_campaign as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc, workspace_pg = support.workspace_pg_proc, support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_coverage_only_repair_then_uncertain_recheck_never_acquires_old_assessments(
    store, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    packet = support.setup(store)

    class CoverageRepair(CampaignTransport):
        async def __call__(self, request):
            body = json.loads(request.content)
            if not request.url.path.endswith("count_tokens"):
                context = json.loads(body["messages"][0]["content"])
                if context["phase"] == "check" and self.checks == 1:
                    raise httpx.ReadTimeout(
                        "Synthetic uncertain recheck; zero provider contact", request=request
                    )
                response = await super().__call__(request)
                if context["phase"] == "repair":
                    envelope = response.json()
                    payload = json.loads(envelope["content"][0]["text"])
                    payload["response"]["coverage"]["p1"] = {
                        "status": "answered",
                        "answer_claim_ids": ["c1"],
                        "context_claim_ids": [],
                        "gap": "none",
                    }
                    envelope["content"][0]["text"] = json.dumps(payload)
                    return httpx.Response(200, json=envelope)
                return response
            return await super().__call__(request)

    report = await run(store, packet, offline=True, transport_factory=CoverageRepair)
    assert report["stop"]["case_id"] == "campaign-dev-learn"
    current = report["cases"][0]
    assert not current["completion"] and current["state"] == "uncertain"
    assert current["mechanical_provenance"] is True
    assert current["declared_coverage"][0]["status"] == "answered"
    assert current["assessment_binding"]["status"] == "unavailable"
    assert all(
        current[key] is None
        for key in (
            "machine_coverage",
            "claim_quality",
            "prose_review",
            "prose_findings",
            "whole_claim_support",
        )
    )
    raw = report["raw_results"][current["id"]]
    assert [s["stage"] for s in raw["steps"]] == ["draft", "check", "repair"]
    assert (
        raw["steps"][0]["output"]["response"]["claims"]
        == raw["steps"][2]["output"]["response"]["claims"]
    )
    assert (
        raw["steps"][0]["output"]["response"]["coverage"]
        != raw["steps"][2]["output"]["response"]["coverage"]
    )
    assert len(raw["contacts"]) == 8 and raw["contacts"][-1]["state"] == "dispatching"
    assert raw["contacts"][-1]["timing"]["events"][-1]["event"] == "timeout"
    assert report["accounting"]["cumulative"]["unknown_usd"] == "0.875066"
    assert report["denominators"]["unrun_evaluation"] == 8
    assert report["analysis_receipt"]["historical_records_modified"] is False
