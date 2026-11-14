"""Synthetic stopped-v14 baseline for the real prospective campaign controls.

No real ledger or provider. Historical recorded usage is seeded explicitly in
isolated test storage so the copied census is exact, never claimed as new spend.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from psycopg import sql

from src.workspace.d5_benchmark import write
from src.workspace.d5_campaign import CampaignTransport, run
from src.workspace.d5_campaign_operator import authorize_fixture
from src.workspace.d5_campaign_policy import job_binding
from src.workspace.d5_campaign_v15_packet import capture, freeze
from tests.test_workspace_d5_v14_integration import setup_successor


class StoppedV14Transport(CampaignTransport):
    async def __call__(self, request: httpx.Request) -> httpx.Response:
        response = await super().__call__(request)
        if request.url.path.endswith("count_tokens"):
            return response
        body = json.loads(request.content)
        if json.loads(body["messages"][0]["content"])["phase"] != "check":
            return response
        value = response.json()
        payload = json.loads(value["content"][0]["text"])
        payload["claim_reviews"][0]["reason"] = "S" * 104
        value["content"][0]["text"] = json.dumps(payload)
        return httpx.Response(200, json=value)


async def prepare(store: Any, *, authorize: bool = True) -> dict[str, Any]:
    previous, _ = await setup_successor(store)
    stopped = await run(store, previous, offline=True, transport_factory=StoppedV14Transport)
    assert stopped["stop"]["case_id"] == "campaign-dev-learn"
    assert stopped["stop"]["reason"] == "campaign_development_contract_incomplete"
    job = stopped["raw_results"]["campaign-dev-learn"]["id"]
    with store.pool.connection() as conn:
        conn.execute("UPDATE workspace_spend_reservations SET workflow=0.023830,judge=0.100012 WHERE job_id=%s", (job,))
        conn.execute("UPDATE workspace_d5_campaign_outcomes SET job_digest=%s WHERE job_id=%s", (job_binding(conn, job)[2], job))
    packet = freeze(store, capture(store, "evaluation"))
    if authorize:
        authorize_fixture(store, packet)
    return packet


def export_rows(store: Any, label: str) -> Path:
    base = Path(os.environ.get("D5_TEST_EVIDENCE_DIR", "build/d5-v15-test-evidence"))
    base.mkdir(parents=True, exist_ok=True)
    from uuid import uuid4
    target = base / (label + "-" + uuid4().hex + ".json.gz")
    with store.pool.connection() as conn:
        names = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND (tablename LIKE 'workspace_d5_%' OR tablename IN ('workspace_generation_jobs','workspace_spend_reservations','workspace_evaluation_members','workspace_evaluation_programs'))")]
        values = {name: [r[0] for r in conn.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(name)))] for name in names}
    write(target, {"basis": "Synthetic isolated regression evidence; no provider contacts", "tables": values})
    return target
