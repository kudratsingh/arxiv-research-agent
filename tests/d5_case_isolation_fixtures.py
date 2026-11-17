"""Local marked storage and MockTransport controls for isolation tests."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psycopg
import pytest
from jsonschema import Draft202012Validator
from psycopg import sql
from psycopg_pool import ConnectionPool

from src.workspace.admission import AdmissionError
from src.workspace.d5_comparison_transport import ComparisonCampaignTransport
from src.workspace.store import WorkspaceStore


class FaultTransport(ComparisonCampaignTransport):
    def __init__(self, key, *, fault="", repair_all=False):
        super().__init__(key, repair_all=repair_all or fault == "negative_quality")
        self.fault = fault

    async def __call__(self, request):
        response = await super().__call__(request)
        if request.url.path.endswith("count_tokens"):
            if self.fault == "count_fit":
                return httpx.Response(200, json={"input_tokens": 32001})
            return response
        body = json.loads(request.content)
        phase = json.loads(body["messages"][0]["content"])["phase"]
        if self.fault == "missing_checker" and phase == "check":
            malformed = response.json()
            malformed["content"][-1]["text"] = "{}"
            return httpx.Response(200, json=malformed)
        if phase != "draft":
            return response
        wire = response.json()
        if self.fault in {"semantic", "wire_invalid"}:
            draft = json.loads(wire["content"][0]["text"])
            coverage = draft["response"]["coverage"]["p2"]
            coverage.update(
                status="answered",
                gap_reasons=["none"],
                context_claim_ids=coverage["answer_claim_ids"],
                answer_claim_ids=[],
            )
            validator = Draft202012Validator(body["output_config"]["format"]["schema"])
            validator.validate(draft)
            if self.fault == "wire_invalid":
                draft["response"].pop("questions")
                assert not validator.is_valid(draft)
            wire["content"][0]["text"] = json.dumps(draft)
        if self.fault == "max_tokens":
            wire["stop_reason"] = "max_tokens"
        if self.fault == "usage":
            wire["usage"]["cache_read_input_tokens"] = 10
        if self.fault == "model":
            wire["model"] = "synthetic-substituted-model"
        if self.fault == "transport":
            raise httpx.ReadTimeout("synthetic interruption", request=request)
        if self.fault == "http_400":
            return httpx.Response(400, json={"error": {"message": "synthetic grammar rejection"}})
        if self.fault == "cancel":
            raise asyncio.CancelledError
        return httpx.Response(200, json=wire)


@contextmanager
def storage():
    url = os.environ["WORKSPACE_TEST_POSTGRES_URL"]
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path != "/workspace_d5_tests":
        raise AdmissionError("case_isolation_disposable_test_database_required")
    schema = "ws_test_v20_isolation_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        with ConnectionPool(
            url, min_size=1, max_size=4, kwargs={"options": f"-c search_path={schema},public"}
        ) as pool:
            store = WorkspaceStore(pool)
            store.migrate()
            yield store
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def job_ledger(store, job_id):
    with store.pool.connection() as conn:
        data = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id=%s",
            (job_id,),
        ).fetchone()[0]
        reservation = conn.execute(
            "SELECT amount,workflow,judge,unknown,state FROM workspace_spend_reservations "
            "WHERE job_id=%s",
            (job_id,),
        ).fetchone()
    return data, reservation


CONTINUATION_SNAPSHOT = Path.home() / (
    "Machine-Learning-Projects/arxiv-evidence/d5-behavior-v20-20261117/READONLY-BASELINE.json.gz"
)


@pytest.fixture
def prepared_campaign(monkeypatch):
    from src.workspace.d5_benchmark import read
    from src.workspace.d5_continuation_packet import freeze
    from src.workspace.d5_fixture import install

    if not CONTINUATION_SNAPSHOT.exists() or not os.environ.get("WORKSPACE_TEST_POSTGRES_URL"):
        pytest.skip("preserved owner-local v20 snapshot and disposable test Postgres required")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    with storage() as store:
        snapshot = read(CONTINUATION_SNAPSHOT)
        install(store, snapshot, fixture=True)
        yield store, freeze(store, snapshot)


@pytest.fixture
def fixture_campaign(prepared_campaign):
    from src.workspace.d5_continuation_packet import authorize_fixture, compile_packet

    store, packet = prepared_campaign
    authorize_fixture(store, packet)
    yield store, packet, compile_packet(packet)


def continuation_factory(calls, bad_case="", fault="", *, repair_all=False):
    from src.workspace.d5_continuation_policy import CASE_MAP

    def factory(key):
        assert key not in calls
        calls[key] = FaultTransport(
            CASE_MAP[key],
            fault=fault if key == bad_case else "",
            repair_all=repair_all,
        )
        return calls[key]

    return factory
