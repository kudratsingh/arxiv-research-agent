"""New HTTP policy enforcement and explicit archived replay; disposable PG only."""

from copy import deepcopy

import pytest

from src.workspace import assistance as a
from src.workspace.assistance_coverage import AUTHORITATIVE_COVERAGE_REVISION
from src.workspace.assistance_policy import TASK_REVISION
from tests import test_workspace_api as api
from tests import test_workspace_assistance as support

store, client = support.store, api.client
if hasattr(support, "workspace_pg"):
    workspace_pg_proc, workspace_pg = support.workspace_pg_proc, support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


async def test_http_omission_default_null_rejection_and_binding(client, store):
    _, value = support.setup(store)
    body = value.model_dump(mode="json")
    body.pop("task_context")
    preview = (await client.post("/workspace/assistance/preview", json={"input": body})).json()
    assert preview["request"]["schema_revision"] == AUTHORITATIVE_COVERAGE_REVISION
    assert preview["request"]["task_policy"]["task_intent"] == "answer"
    for endpoint in ("preview", "jobs"):
        result = await client.post(
            "/workspace/assistance/" + endpoint,
            json={
                "input": {**body, "task_context": None},
                "request_id": "null",
                "expected_digest": preview["request_digest"],
            }
            if endpoint == "jobs"
            else {"input": {**body, "task_context": None}},
        )
        assert result.status_code == 422
        assert any(e["loc"] == ["body", "input", "task_context"] for e in result.json()["detail"])
    altered = {**body, "task_context": {"intent": "answer", "application_context": {}}}
    # Explicit equivalent context is the same default, not a second protocol.
    good = await client.post(
        "/workspace/assistance/jobs",
        json={
            "input": altered,
            "request_id": "bound",
            "expected_digest": preview["request_digest"],
        },
    )
    assert good.status_code == 200, good.text
    assert good.json()["wire_records"] == []
    changed = deepcopy(body)
    changed["task_context"] = {"intent": "comparison"}
    mismatch = await client.post(
        "/workspace/assistance/jobs",
        json={
            "input": changed,
            "request_id": "changed",
            "expected_digest": preview["request_digest"],
        },
    )
    assert mismatch.status_code in (409, 422)
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM workspace_assistance_wire").fetchone()[0] == 0
        assert (
            conn.execute("SELECT count(*) FROM workspace_fake_generation_jobs").fetchone()[0] == 1
        )


async def test_archived_null_input_replays_internally_but_never_at_http_boundary(client, store):
    service, value = support.setup(store)
    assert value.task_context is None
    encoded = value.model_dump_json()
    legacy = a.AssistanceInput.model_validate_json(encoded)
    preview = service.preview("a", legacy)
    assert preview.request["schema_revision"] != TASK_REVISION
    assert "task_policy" not in preview.request
    job = service.submit(
        "a",
        a.SubmitWrite(input=legacy, request_id="archive", expected_digest=preview.request_digest),
    )
    for _ in range(4):
        result = service.action("a", job.id, "advance")
        if result["state"] in {"ready", "ready_partial"}:
            break
    assert result["state"] in {"ready", "ready_partial"} and result["assistance_output"]
    rejected = await client.post(
        "/workspace/assistance/jobs",
        json={
            "input": legacy.model_dump(mode="json"),
            "request_id": "no-null-bypass",
            "expected_digest": preview.request_digest,
        },
    )
    assert rejected.status_code == 422


async def test_requested_parts_are_sealed_before_submit_and_edits_require_preview(client, store):
    _, value = support.setup(store)
    body = value.model_dump(mode="json")
    body["task_context"] = {
        "intent": "answer",
        "requested_parts": [
            {"id": "p1", "request": "Primary method"},
            {"id": "p2", "request": "Scope and conditions"},
        ],
    }
    response = await client.post("/workspace/assistance/preview", json={"input": body})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert [p["request"] for p in preview["request"]["task_policy"]["requested_parts"]] == [
        "Primary method",
        "Scope and conditions",
    ]
    modified = deepcopy(body)
    modified["task_context"]["requested_parts"].reverse()
    modified["task_context"]["requested_parts"][0]["id"] = "p1"
    modified["task_context"]["requested_parts"][1]["id"] = "p2"
    refused = await client.post(
        "/workspace/assistance/jobs",
        json={
            "input": modified,
            "request_id": "stale-parts",
            "expected_digest": preview["request_digest"],
        },
    )
    assert refused.status_code == 409
    with store.pool.connection() as conn:
        assert (
            conn.execute("SELECT count(*) FROM workspace_fake_generation_jobs").fetchone()[0] == 0
        )
    good = await client.post(
        "/workspace/assistance/jobs",
        json={
            "input": body,
            "request_id": "sealed-parts",
            "expected_digest": preview["request_digest"],
        },
    )
    assert good.status_code == 200, good.text
    for _ in range(2):
        step = await client.post("/workspace/assistance/jobs/" + good.json()["id"] + "/advance")
        assert step.status_code == 200, step.text
    result = (await client.get("/workspace/assistance/jobs/" + good.json()["id"])).json()
    assert result["assistance_output"]["coverage_complete"] is False
    assert len(result["assistance_output"]["request_coverage"]) == 2
