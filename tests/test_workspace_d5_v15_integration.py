"""Protected production adapter; all prospective authority and responses synthetic."""
from __future__ import annotations

import json

import pytest

from src.workspace.d5_campaign import run
from src.workspace.d5_capacity_transport import CapacityCampaignTransport
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


async def test_full_prospective_campaign_accepts_long_complete_bound_responses(store):
    try:
        packet = await prepare(store)
        report = await run(store, packet, offline=True, transport_factory=lambda key: CapacityCampaignTransport(key, repair_all=True))
        assert report["stop"] is None, report["stop"]
        assert len(report["outcomes"]) == 14
        assert report["accounting"]["new_scope"]["messages"] == report["accounting"]["new_scope"]["counts"] == 44
        assert report["accounting"]["cumulative"]["funded_programme_jobs"] == 50
        assert report["accounting"]["cumulative"]["messages"] == 114
        assert report["accounting"]["cumulative"]["counts"] == 139
        assert report["accounting"]["cumulative"]["unknown_usd"] == "0.875066"
        assert report["accounting"]["retained_hold_usd"] == "0.875066"
        assert all(c["assessment_binding"]["status"] == "bound" for c in report["cases"])
        assert all(d["classification"] in {"success", "unknown_hold"} for d in report["outcome_diagnostics"].values())
        assert any(d["formatting_observations"] for d in report["outcome_diagnostics"].values())
        for value in report["raw_results"].values():
            if value["operation"] != "workflow":
                continue
            assert [s["stage"] for s in value["steps"]] == ["draft", "check", "repair", "check"]
            if value["assistance_output"]["claims"]:
                assert len(json.dumps(value["steps"][-1]["output"]).encode()) > 8000
                assert len(value["steps"][-1]["output"]["checks"][0]["reason"]) > 240
        again = await run(store, packet, offline=True, transport_factory=lambda key: pytest.fail("duplicate dispatch"))
        assert again["accounting"] == report["accounting"]
    finally:
        export_rows(store, "full-prospective-campaign")
