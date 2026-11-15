"""Synthetic v16 multi-gap output survives the real persisted report path.

All grants, responses and judgments below are isolated mock controls; no
provider, source refresh, production credential or human label is involved.
"""
from __future__ import annotations

import json

import httpx
import pytest
from jsonschema import Draft202012Validator
from psycopg_pool import ConnectionPool

from src.workspace.assistance_coverage import GAP_TEXT
from src.workspace.d5_campaign import run
from src.workspace.d5_campaign_report import markdown, results
from src.workspace.d5_freeze import compile_inputs
from src.workspace.d5_keyed_transport import KeyedCampaignTransport
from src.workspace.d5_results import QualificationResults
from src.workspace.store import WorkspaceStore
from tests import test_workspace_d5_v16_integration as v16
from tests.d5_capacity_gate import export_rows

store = v16.store
if hasattr(v16, "workspace_pg"):
    workspace_pg_proc, workspace_pg = v16.workspace_pg_proc, v16.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio, pytest.mark.timeout(600)]
REASONS = ["methods", "metric_definition", "data_splits"]


class ThreeGaps(KeyedCampaignTransport):
    """Alter only freshly generated synthetic responses, never retained output."""

    def __init__(self, key: str):
        super().__init__(key, repair_all=True)
        self.validated_phases: list[str] = []
        self.original_answer_ids: list[list[str]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        response = await super().__call__(request)
        if request.url.path.endswith("count_tokens"):
            return response
        request_body = json.loads(request.content)
        phase = json.loads(request_body["messages"][0]["content"])["phase"]
        envelope = response.json()
        blocks = [block for block in envelope["content"] if block["type"] == "text"]
        assert len(blocks) == 1
        payload = json.loads(blocks[0]["text"])
        if phase in {"draft", "repair"}:
            row = payload["response"]["coverage"]["p3"]
            assert row["status"] == "answered"
            answers = row.pop("answer_claim_ids")
            self.original_answer_ids.append(answers)
            row.update(status="lacks_evidence", gap_reasons=REASONS,
                       context_claim_ids=list(dict.fromkeys(row["context_claim_ids"] + answers)))
        elif phase == "check":
            payload["coverage_checks"]["p3"]["decision"] = "lacks_evidence"
            if self.checks == 1:
                payload["coverage_checks"]["p1"]["decision"] = "omitted"
        else:
            raise AssertionError(f"unexpected synthetic phase {phase}")
        # Validate the altered output against the exact actual request schema,
        # not a separately invented approximation.
        Draft202012Validator(request_body["output_config"]["format"]["schema"]).validate(payload)
        self.validated_phases.append(phase)
        blocks[0]["text"] = json.dumps(payload, ensure_ascii=False)
        return httpx.Response(200, json=envelope)


async def test_three_gaps_survive_repair_restart_and_bound_report(store, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    transports: dict[str, ThreeGaps] = {}

    def transport(key: str) -> ThreeGaps:
        transports[key] = ThreeGaps(key)
        return transports[key]

    try:
        packet = await v16.setup_keyed(store)
        case_id = packet["schedule"][0]
        report = await run(store, packet, offline=True, transport_factory=transport, checkpoint_after=1)
        assert report["stop"] is None
        raw = report["raw_results"][case_id]
        assert [step["stage"] for step in raw["steps"]] == ["draft", "check", "repair", "check"]
        mock = transports[case_id]
        assert mock.validated_phases == ["draft", "check", "repair", "check"]
        assert len(mock.original_answer_ids) == 2 and all(mock.original_answer_ids)
        first_check = raw["steps"][1]["output"]["coverage_checks"]
        final_check = raw["steps"][3]["output"]["coverage_checks"]
        assert next(row for row in first_check if row["part_id"] == "p1")["decision"] == "omitted"
        assert next(row for row in final_check if row["part_id"] == "p1")["decision"] == "answered"
        for step in (raw["steps"][1], raw["steps"][3]):
            p3 = next(row for row in step["output"]["coverage_checks"] if row["part_id"] == "p3")
            assert p3["decision"] == "lacks_evidence"
        with store.pool.connection() as conn:
            schema = conn.execute("SELECT current_schema()").fetchone()[0]
        with ConnectionPool(store.pool.conninfo, min_size=1, max_size=2,
                            kwargs={"options": f"-c search_path={schema},public"}) as pool:
            restarted = WorkspaceStore(pool)
            case = compile_inputs(packet)[case_id]
            saved = QualificationResults(restarted).snapshot(case["owner"], raw["id"])
            refreshed = results(restarted, packet)
        row = next(part for part in saved["assistance_output"]["request_coverage"] if part["id"] == "p3")
        assert row["status"] == "lacks_evidence" and row["answer_claim_ids"] == []
        assert row["context_claim_ids"] == mock.original_answer_ids[-1]
        assert row["gap_reasons"] == REASONS
        assert row["gap_texts"] == [GAP_TEXT[reason] for reason in REASONS]
        reported = next(item for item in refreshed["cases"] if item["id"] == case_id)
        assert reported["assessment_binding"]["status"] == "bound"
        assert next(part for part in reported["declared_coverage"] if part["id"] == "p3") == row
        assert next(part for part in reported["machine_coverage"] if part["part_id"] == "p3")["decision"] == "lacks_evidence"
        rendered = markdown(refreshed)
        assert all(GAP_TEXT[reason] in rendered for reason in REASONS)
        assert refreshed["machine_quality"] == "HOLD" and refreshed["human_labels"] is None
        assert refreshed["human_qualification"] is False
    finally:
        export_rows(store, "v16-multigap-bound-report")
