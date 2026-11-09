"""Actual sealed request, protected adapter and local renderer in disposable PG."""

import json
from copy import deepcopy
from dataclasses import replace

import httpx
import pytest
from jsonschema import validate
from psycopg.types.json import Jsonb

from src.workspace import assistance as a
from src.workspace.admission import AdmissionError
from src.workspace.assistance_policy import TASK_REVISION, ApplicationContext, TaskContext
from src.workspace.d5_adapter import D5Adapter
from src.workspace.d5_operations import ROUTES
from src.workspace.d5_results import QualificationResults
from tests import test_workspace_api as api_support
from tests import test_workspace_d5_adapter as support
from tests.test_workspace_store import ingest
from tests.test_workspace_task_policy import ARCHIVE, NORMAL, RETRIEVAL, SAFETY, response

store = support.store
client = api_support.client
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def archived_source(case_id):
    def setup(store):
        case = ARCHIVE["cases"][case_id]
        service, base = support.support.setup(store, case["mode"])
        refs = list(case["units"].values())
        for material in ARCHIVE["materials"]:
            if material["material_id"] not in {r["material_id"] for r in refs}:
                continue
            ingest(
                store,
                work_id=material["work_id"],
                version_id=material["version_id"],
                source_record_id=material["work_id"],
                abstract=material["pages"][0],
                content_hash=material["source_hash"],
            )
            with store.pool.connection() as conn:
                conn.execute(
                    "INSERT INTO workspace_material VALUES(%s,%s,%s,%s,%s) ON CONFLICT(material_id) DO UPDATE SET content_hash=EXCLUDED.content_hash,source_scope=EXCLUDED.source_scope,data=EXCLUDED.data",
                    (
                        material["material_id"],
                        material["version_id"],
                        material["content_hash"],
                        material["scope"],
                        Jsonb(material),
                    ),
                )
        value = base.model_copy(
            update={
                "work_id": refs[0]["work_id"],
                "version_id": refs[0]["version_id"],
                "material_ids": tuple(dict.fromkeys(r["material_id"] for r in refs)),
                "span_ids": tuple(dict.fromkeys(r["span_id"] for r in refs)),
                "unit_ids": tuple(case["units"]),
                "follow_up": case["question"],
                "task_context": TaskContext(
                    intent="application_assessment"
                    if case_id == SAFETY
                    else "comparison"
                    if case_id == RETRIEVAL
                    else "answer"
                ),
            }
        )
        return service, value

    return setup


class Transport:
    def __init__(self, case_id, *, bad=None, prose=False, unsupported=False):
        self.case_id, self.bad, self.prose, self.unsupported = case_id, bad, prose, unsupported
        self.calls = []

    async def __call__(self, req):
        body = json.loads(req.content)
        self.calls.append((req.url.path, body))
        if req.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        context = json.loads(body["messages"][0]["content"])
        if context["phase"] == "check":
            payload = {
                "checks": [
                    {
                        "claim_id": c["claim_id"],
                        "input_digest": c["input_digest"],
                        "decision": "unsupported" if self.unsupported else "supported",
                        "reason": "Synthetic software verdict, not a quality label.",
                    }
                    for c in context["claim_inputs"]
                ],
                "prose_review": "unscored_factual_content" if self.prose else "procedural_only",
                "prose_findings": [
                    {
                        "field": "proposal",
                        "index": None,
                        "reason": "Synthetic remaining-prose rejection.",
                    }
                ]
                if self.prose
                else [],
            }
        else:
            payload = deepcopy(self.bad) if self.bad is not None else response(self.case_id)
        if self.bad is None:
            validate(payload, body["output_config"]["format"]["schema"])
        return httpx.Response(
            200,
            json={
                "id": "synthetic-" + str(len(self.calls)),
                "model": body["model"],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 100},
                "content": [{"type": "text", "text": json.dumps(payload)}],
            },
        )


def adapter(store, case_id, transport):
    inputs = support.setup(
        store,
        mode=ARCHIVE["cases"][case_id]["mode"],
        routes=ROUTES,
        source_setup=archived_source(case_id),
        repair_located_prose=True,
    )
    return D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport)), inputs


@pytest.mark.parametrize("case_id,claims", [(SAFETY, 0), (RETRIEVAL, 6), (NORMAL, 6)])
async def test_actual_request_adapter_and_rendering(store, case_id, claims):
    transport = Transport(case_id)
    runtime, inputs = adapter(store, case_id, transport)
    wire = runtime.request()
    canonical_inputs = replace(
        inputs, settings=json.loads(json.dumps(inputs.settings, sort_keys=True))
    )
    restored = D5Adapter(
        store, "d5-run", canonical_inputs, transport=httpx.MockTransport(transport)
    )
    assert restored.request() == wire
    context = json.loads(wire["body"]["messages"][0]["content"])
    assert context["sealed_request"]["schema_revision"] == TASK_REVISION
    assert context["sealed_request"]["task_policy"] == inputs.settings["d5_request"]["task_policy"]
    assert "claims" not in response(SAFETY)["response"]
    job = runtime.start(inputs.settings["d5_request_id"])
    for _ in range(4):
        if job["state"] == "ready":
            break
        job = await runtime.advance(job["id"])
    assert job["state"] == "ready"
    assert len(job["result"]["draft"]["claims"]) == claims
    assert [path for path, _ in transport.calls] == [
        "/v1/messages/count_tokens",
        "/v1/messages",
        "/v1/messages/count_tokens",
        "/v1/messages",
    ]
    assert len(job["steps"]) == 2  # Full abstention still goes through mandatory checking.
    checker = json.loads(transport.calls[-1][1]["messages"][0]["content"])
    assert "claims" not in checker["unscored_prose"]
    assert "task_policy" in checker["sealed_request"]
    assert "Return the exact response envelope" in transport.calls[0][1]["system"]
    assert "Return the exact response envelope" not in transport.calls[-1][1]["system"]
    assert "Return only the checker verdict schema" in transport.calls[-1][1]["system"]
    assert job["workflow_usd"] == job["checker_usd"] == "0"
    persisted = QualificationResults(store).snapshot("d5-run", job["id"])
    assert persisted["source_binding_intact"]
    assert persisted["human_review"] is None
    assert (
        persisted["assistance_output"]["response_disposition"]
        == response(case_id)["response"]["disposition"]
    )
    assert len(persisted["assistance_output"]["claims"]) == claims
    if case_id == SAFETY:
        assert context["sealed_request"]["task_policy"]["allowed_dispositions"] == [
            "full_abstention"
        ]
        assert "vehicle" in job["result"]["draft"]["proposed_actions"][0]


@pytest.mark.parametrize("switch", ["original", "comparison", "null", "unselected"])
async def test_refuse_captured_or_mutated_output_before_checker(store, switch):
    if switch == "unselected":
        case_id = RETRIEVAL
        payload = response(RETRIEVAL)
        payload["response"]["claims"][0]["handles"] = ["unselected"]
    else:
        case_id = SAFETY
        payload = deepcopy(ARCHIVE["cases"][SAFETY]["output"])
        if switch != "original":
            payload = {
                "response": {
                    **payload,
                    "disposition": "comparison_abstention" if switch == "comparison" else "answer",
                    "abstention": "comparison_evidence_required"
                    if switch == "comparison"
                    else None,
                }
            }
    transport = Transport(case_id, bad=payload)
    runtime, inputs = adapter(store, case_id, transport)
    job = runtime.start(inputs.settings["d5_request_id"])
    with pytest.raises((ValueError, AdmissionError)):
        await runtime.advance(job["id"])
    assert len(transport.calls) == 2
    assert all(
        json.loads(body["messages"][0]["content"])["phase"] == "draft"
        for _, body in transport.calls
    )
    assert runtime.snapshot(job["id"])["state"] == "failed"


@pytest.mark.parametrize("prose,unsupported", [(True, False), (False, True)])
async def test_remaining_prose_and_unsupported_claims_still_fail(store, prose, unsupported):
    transport = Transport(RETRIEVAL, prose=prose, unsupported=unsupported)
    runtime, inputs = adapter(store, RETRIEVAL, transport)
    job = runtime.start(inputs.settings["d5_request_id"])
    for _ in range(4):
        try:
            job = await runtime.advance(job["id"])
        except (ValueError, AdmissionError):
            break
    assert runtime.snapshot(job["id"])["state"] == "failed"
    assert len(transport.calls) <= 8


async def test_real_local_service_full_abstention_is_durable_and_missing_context_is_sealed(store):
    service, value = archived_source(SAFETY)(store)
    preview = service.preview("a", value)
    assert preview.request["task_policy"]["missing_context"] == list(
        ApplicationContext.model_fields
    )
    job = service.submit(
        "a",
        a.SubmitWrite(input=value, request_id="local-full", expected_digest=preview.request_digest),
    )
    for _ in range(4):
        current = service.action("a", job.id, "advance")
        if current["state"] in {"ready", "ready_partial"}:
            break
    rendered = a.AssistanceService(store).get("a", job.id)
    assert rendered["assistance_output"] is not None, {
        "state": rendered["state"],
        "error": rendered["error"],
        "steps": [(s["phase"], s["error"]) for s in rendered["steps"]],
        "wire": [
            (w["phase"], list(w["response"].keys()) if w["response"] else None)
            for w in rendered["wire_records"]
        ],
    }
    assert rendered["assistance_output"]["claims"] == []
    assert len(rendered["assistance_output"]["context_requests"]) == 4
    assert rendered["assistance_output"]["response_disposition"] == "full_abstention"
    assert [
        saved["id"]
        for saved in a.AssistanceService(store).jobs("a", value.work_id, value.version_id)
    ] == [job.id]
    changed = value.model_copy(
        update={
            "task_context": TaskContext(
                intent="application_assessment",
                application_context=ApplicationContext(vehicle_configuration="new configuration"),
            )
        }
    )
    with pytest.raises(ValueError):
        service.submit(
            "a",
            a.SubmitWrite(
                input=changed, request_id="drift", expected_digest=preview.request_digest
            ),
        )


async def test_http_full_abstention_request_and_reload(client, store):
    _, value = archived_source(SAFETY)(store)
    body = {"input": value.model_dump(mode="json")}
    preview = await client.post("/workspace/assistance/preview", json=body)
    assert preview.status_code == 200
    sealed = preview.json()
    assert sealed["request"]["task_policy"]["allowed_dispositions"] == ["full_abstention"]
    submitted = await client.post(
        "/workspace/assistance/jobs",
        json={**body, "request_id": "http-full", "expected_digest": sealed["request_digest"]},
    )
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["id"]
    for _ in range(2):
        result = await client.post(f"/workspace/assistance/jobs/{job_id}/advance")
        assert result.status_code == 200, result.text
    reloaded = (await client.get(f"/workspace/assistance/jobs/{job_id}")).json()
    assert reloaded["assistance_output"]["response_disposition"] == "full_abstention"
    assert reloaded["assistance_output"]["claims"] == []
    assert len(reloaded["assistance_output"]["context_requests"]) == 4
    assert (
        await client.get(f"/workspace/assistance/jobs/{job_id}", headers={"X-API-Key": "key-b"})
    ).status_code == 422
