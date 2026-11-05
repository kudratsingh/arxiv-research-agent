"""Context API uses real SQL, existing auth, stable snapshots and no providers."""
from __future__ import annotations

import base64
import json
from urllib.parse import urlencode

import pytest

from src.workspace.context_schemas import ProjectData, ProjectWrite
from src.workspace.context_store import WorkspaceContext
from src.workspace.schemas import ProfileData, ProfileWrite
from tests import test_workspace_api as support
from tests.test_workspace_context import PID, TID
from tests.test_workspace_store import ingest

client = support.client
store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def project_body():
    return {"id": PID, "revision": 0, "request_id": "project", "data": {"title": "Memory study", "question": "What improves agent memory?"}}


async def test_context_auth_owner_isolation_and_no_implicit_project(client, store):
    assert (await client.get("/workspace/context", headers={"X-API-Key": "bad"})).status_code == 401
    index = await client.get("/workspace/context")
    assert index.headers["cache-control"] == "private, no-store"
    assert index.json()["projects"] == []
    empty = (await client.get("/workspace/context/state?mode=research")).json()
    assert empty["context"]["unavailable_reason"] == "select_or_create_project" and empty["active_edition"] is None
    created = await client.post("/workspace/context/projects", json=project_body())
    assert created.status_code == 200, created.text
    assert (await client.get(f"/workspace/context/projects/{PID}")).json()["revision"] == 1
    assert (await client.get(f"/workspace/context/projects/{PID}", headers={"X-API-Key": "key-b"})).status_code == 404
    assert (await client.get("/workspace/context/projects/unknown")).status_code == 404
    assert (await client.post("/workspace/context/projects", json={**project_body(), "request_id": "stale"})).status_code == 409
    missing = (await client.get(f"/workspace/context/state?mode=research&project={PID}", headers={"X-API-Key": "key-b"})).json()
    assert missing["context"]["unavailable_reason"] == "project_unavailable"
    assert (await client.get(f"/workspace/context/items?mode=research&project={PID}", headers={"X-API-Key": "key-b"})).status_code == 422
    assert (await client.get("/workspace/context/state?mode=bogus")).status_code == 422
    assert (await client.get("/workspace/state")).json()["generation"] == "approval_required"


async def test_default_preferences_and_authoritative_context_edition(client, store):
    value = ingest(store)
    profile = ProfileData(topics=[], custom_topics=["agent"], research_question="Unrelated impossible phrase")
    store.write_profile("a", ProfileWrite(revision=0, request_id="p", data=profile))
    initial = await client.get("/workspace/context/state?mode=learn")
    assert initial.status_code == 200, initial.text
    learn = initial.json()
    assert learn["active_edition"]["work_ids"] == [value["work_id"]]
    assert learn["active_edition"]["context"]["mode"] == "learn"
    assert learn["works"][0]["mode_relevance"]["policy_version"] == "workspace-modes-lexical-v1"
    assert (await client.get("/workspace/context/state?mode=learn")).json()["active_edition"] == learn["active_edition"]
    assert (await client.post("/workspace/context/preferences", json={"revision": 0, "request_id": "prefs", "data": {"default_mode": "research"}})).status_code == 200
    assert (await client.get("/workspace/context/state")).json()["context"]["mode"] == "research"
    assert (await client.post("/workspace/context/preferences", json={"revision": 0, "request_id": "prefs-stale", "data": {}})).status_code == 409
    await client.post("/workspace/context/projects", json=project_body())
    research = (await client.get(f"/workspace/context/state?mode=research&project={PID}")).json()
    assert research["active_edition"]["work_ids"] == [value["work_id"]]
    assert research["active_edition"]["id"] != learn["active_edition"]["id"]
    assert (await client.get(f"/workspace/context/state?mode=learn&thread={TID}")).json()["context"]["unavailable_reason"] == "learning_thread_unavailable"


async def test_all_context_writes_and_exact_shared_resume_through_api(client, store):
    value = ingest(store)
    await client.post("/workspace/context/projects", json=project_body())
    base = f"/workspace/context/projects/{PID}"
    reference = {"work_id": value["work_id"], "version_id": value["version_id"], "anchor": "abstract:0:8"}
    linked = await client.post(base + "/sources", json={"revision": 1, "request_id": "source", "role": "evidence", "reference": reference})
    assert linked.status_code == 200, linked.text
    link = linked.json()["sources"][0]
    context = {"mode": "research", "project_id": PID, "return_to": f"/workspace/projects?mode=research&project={PID}#evidence"}
    entry = {"id": "saved-question", "revision": 0, "request_id": "entry", "data": {"work_id": value["work_id"], "version_id": value["version_id"], "anchor": "abstract:0:8", "kind": "question", "body": "What would falsify this?"}, "context": context}
    assert (await client.post("/workspace/context/entries", json=entry)).json()["context"]["project_id"] == PID
    assert (await client.post(base + "/entries", json={"revision": 2, "request_id": "link-entry", "entry_id": "saved-question", "entry_revision": 1})).status_code == 200
    artifact = await client.post(base + "/artifacts", json={"id": "artifact-" + "1" * 32, "revision": 3, "request_id": "artifact", "data": {"kind": "assumption", "body": "Manual, unverified assumption", "evidence_link_ids": [link["id"]]}})
    assert artifact.json()["artifacts"][0]["verification"] == "unverified"
    thread = {"id": TID, "revision": 0, "request_id": "thread", "data": {"title": "Learn memory", "goal": "Understand memory", "origin": context, "source": reference, "entry": {"entry_id": "saved-question", "entry_revision": 1}}}
    saved_thread = await client.post("/workspace/context/threads", json=thread)
    assert saved_thread.status_code == 200, saved_thread.text
    assert (await client.get(f"/workspace/context/threads/{TID}")).json()["source"]["anchor"] == "abstract:0:8"
    assert (await client.get(f"/workspace/context/threads/{TID}", headers={"X-API-Key": "key-b"})).status_code == 404
    second = "project-" + "c" * 32
    assert (await client.post("/workspace/context/projects", json={**project_body(), "id": second, "request_id": "project-second"})).status_code == 200
    mismatched = f"mode=research&project={second}&thread={TID}"
    invalid = (await client.get(f"/workspace/context/state?{mismatched}")).json()
    assert invalid["context"]["unavailable_reason"] == "learning_thread_project_context_mismatch"
    assert invalid["active_edition"] is None
    assert (await client.get(f"/workspace/context/items?{mismatched}")).status_code == 422
    reading = {"work_id": value["work_id"], "revision": 0, "request_id": "reading", "data": {"version_id": value["version_id"], "anchor": "abstract:0:8", "status": "saved"}, "context": context}
    assert (await client.post("/workspace/context/reading", json=reading)).json()["context"]["project_id"] == PID
    snapshot = (await client.get("/workspace/context/state?mode=learn")).json()
    assert snapshot["works"][0]["entries"][0]["context"]["project_id"] == PID
    assert snapshot["works"][0]["reading"]["context"]["project_id"] == PID
    removed = await client.post(base + "/unlink", json={"revision": 4, "request_id": "unlink", "link_id": link["id"]})
    assert removed.json()["sources"][0]["status"] == "removed"
    assert len((await client.get("/workspace/state")).json()["works"][0]["entries"]) == 1


async def test_research_question_outside_interests_and_cursor_bound_to_revisions(client, store):
    for index in range(5):
        ingest(store, work_id=f"paper:{index}", version_id=f"paper:{index}:v1", title=f"Attention architecture {index}", abstract="Attention replaces recurrent convolutional architecture.")
    store.write_profile("a", ProfileWrite(revision=0, request_id="profile", data=ProfileData(topics=[], custom_topics=["quantum", "unmatched"])))
    repo = WorkspaceContext(store)
    repo.write_project("a", ProjectWrite(id=PID, revision=0, request_id="p", data=ProjectData(title="Attention", question="How does attention replace recurrent architecture?")))
    path = f"/workspace/context/items?mode=research&project={PID}&limit=2&days=0"
    page = await client.get(path)
    assert page.status_code == 200, page.text
    first = page.json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    assert first["items"][0]["mode_relevance"]["profile_keyword_score"] == 0
    cursor = first["next_cursor"]
    def url(**params):
        return path + "&" + urlencode(params)
    second_response = await client.get(url(cursor=cursor))
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert first["as_of"] == second["as_of"]
    assert {work["work_id"] for work in first["items"]}.isdisjoint(work["work_id"] for work in second["items"])
    assert (await client.get(url(cursor=cursor, q="changed"))).status_code == 422
    assert (await client.get(url(cursor=cursor, as_of="2026-01-01T00:00:00Z"))).status_code == 422
    assert (await client.get(url(cursor="!bad!"))).status_code == 422
    payload = json.loads(base64.urlsafe_b64decode(cursor))
    payload["offset"] = -1
    assert (await client.get(url(cursor=base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()))).status_code == 422
    repo.write_project("a", ProjectWrite(id=PID, revision=1, request_id="edit", data=ProjectData(title="Attention", question="What are recurrent networks?")))
    assert (await client.get(url(cursor=cursor))).status_code == 422


@pytest.mark.parametrize("query,expected", [
    ("source_id=unknown", 0), ("access_state=full_text", 0), ("status=saved", 0),
    ("q=unmatched", 0), ("days=1", 0), ("days=0", 1),
])
async def test_shared_filters_and_unknown_dates_have_honest_denominators(client, store, query, expected):
    ingest(store)
    result = await client.get(f"/workspace/context/items?mode=learn&{query}")
    assert result.status_code == 200, result.text
    assert len(result.json()["items"]) == expected


async def test_bad_clock_archived_project_and_context_validation(client, store):
    ingest(store)
    for clock in ("invalid", "2026-11-05"):
        assert (await client.get("/workspace/context/items", params={"as_of": clock})).status_code == 422
    body = project_body()
    body["data"]["status"] = "archived"
    await client.post("/workspace/context/projects", json=body)
    result = (await client.get(f"/workspace/context/state?mode=research&project={PID}")).json()
    assert result["active_edition"] is None and result["context"]["unavailable_reason"] == "project_archived"
    assert (await client.post(f"/workspace/context/projects/{PID}/sources", json={"revision": 1, "request_id": "bad", "reference": {"work_id": "unknown", "version_id": "unknown"}})).status_code == 422
    assert (await client.get("/workspace/context/state?mode=learn")).json()["works"]
