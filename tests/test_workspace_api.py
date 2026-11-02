"""Real repository behind the existing principal/error boundary; no provider/network calls."""
from __future__ import annotations

import base64
import json

import httpx
import pytest
from asgi_lifespan import LifespanManager

from src.api.app import create_app
from src.api.auth import ApiKeyPrincipal
from src.config import Settings
from src.workspace import routes
from src.workspace.intake import FetchResult
from src.workspace.schemas import ProfileData
from tests import test_workspace_store as support
from tests.test_workspace_store import ingest, item, preview

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def client(store, monkeypatch):
    from src.api import auth
    config = Settings(enable_workspace=True, enable_api_auth=True, api_keys="a:key-a,b:key-b", postgres_url="postgresql://unused/workspace", use_mock_data=True)
    monkeypatch.setattr(routes, "settings", config)
    monkeypatch.setattr(auth, "settings", config)
    monkeypatch.setattr(routes, "_store", store)
    app = create_app(build_workflow=lambda: object())
    async with LifespanManager(app):
        app.state.api_keys = {"key-a": ApiKeyPrincipal("a"), "key-b": ApiKeyPrincipal("b")}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"X-API-Key": "key-a"}) as client:
            yield client


async def test_api_auth_flag_missing_storage_and_generation_guard(client, monkeypatch):
    assert (await client.get("/workspace/state", headers={"X-API-Key": "bad"})).status_code == 401
    assert (await client.post("/workspace/generate", json={"work_id": "x", "kind": "summary"})).status_code == 403
    assert (await client.get("/workspace/state")).json()["principal_key_id"] == "a"
    original = routes.settings
    monkeypatch.setattr(routes, "settings", original.model_copy(update={"enable_workspace": False}))
    assert (await client.get("/workspace/state")).status_code == 404
    monkeypatch.setattr(routes, "settings", original.model_copy(update={"postgres_url": ""}))
    assert (await client.get("/workspace/state")).status_code == 503
    monkeypatch.setattr(routes, "settings", original)
    from src.api import auth
    monkeypatch.setattr(auth, "settings", original.model_copy(update={"enable_api_auth": False}))
    assert (await client.get("/workspace/state")).status_code == 403


async def test_api_save_reading_notes_conflict_export_and_isolation(client, store):
    value = ingest(store)
    body = {"revision": 0, "request_id": "profile", "data": ProfileData(research_question="My scoped question").model_dump()}
    assert (await client.post("/workspace/profile", json=body)).json()["revision"] == 1
    assert (await client.post("/workspace/profile", json={**body, "request_id": "stale"})).status_code == 409
    read = {"work_id": value["work_id"], "revision": 0, "request_id": "r", "data": {"version_id": value["version_id"], "status": "saved", "anchor": "abstract:11"}}
    assert (await client.post("/workspace/reading", json=read)).json()["anchor"] == "abstract:11"
    note = {"id": "n", "revision": 0, "request_id": "n", "data": {"work_id": value["work_id"], "version_id": value["version_id"], "body": "Private note", "kind": "note", "anchor": "abstract:11"}}
    assert (await client.post("/workspace/entries", json=note)).status_code == 200
    assert (await client.post("/workspace/entries", json={**note, "request_id": "stale"})).status_code == 409
    assert "Private note" in (await client.get("/workspace/export")).text
    other = (await client.get("/workspace/state", headers={"X-API-Key": "key-b"})).json()
    assert other["works"][0]["entries"] == []
    assert "Private note" not in (await client.get("/workspace/export", headers={"X-API-Key": "key-b"})).text
    assert (await client.post("/workspace/entries", json={**note, "id": "bad", "request_id": "bad", "data": {**note["data"], "version_id": "wrong"}})).status_code == 422
    assert (await client.post("/workspace/edition")).json()["profile_revision"] == 1


async def test_api_refresh_partial_failure_and_manual_save(client, store, monkeypatch):
    def fetch(source_id, **kwargs):
        data = {**item(), "source_id": source_id}
        return FetchResult([data], {"status": "success", "fetched_at": data["fetched_at"]}, {}) if source_id == "arxiv-cs-ai" else FetchResult([], {"status": "failed", "error": "timeout"}, {})
    monkeypatch.setattr(routes, "fetch_source", fetch)
    response = await client.post("/workspace/refresh", json={"source_ids": ["arxiv-cs-ai", "google-research"]})
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["editions"][0]["status"] == "ready_partial"
    assert len(state["works"]) == 1
    assert (await client.post("/workspace/refresh", json={"source_ids": ["unapproved"]})).status_code == 422
    manual = await client.post("/workspace/manual", json={"value": "10.1000/a.b"})
    assert manual.status_code == 200, manual.text
    assert manual.json()["access_state"] == "metadata"
    assert (await client.post("/workspace/manual", json={"value": "10.1000/a.b"})).status_code == 200
    assert len(store.works("a")) == 2
    assert len(store.works("b")) == 1
    assert (await client.post("/workspace/manual", json={"value": "http://127.0.0.1/secret"})).status_code == 422
    canonical = await client.post("/workspace/manual", json={"value": "2611.00001"})
    assert canonical.json()["work_id"] == "arxiv:2611.00001"
    assert len(store.works("a")) == 2


async def test_manual_distinct_unacquired_arxiv_versions_resume_the_requested_link(client, store):
    first = await client.post("/workspace/manual", json={"value": "2611.99991v1"})
    assert first.status_code == 200
    second = await client.post("/workspace/manual", json={"value": "2611.99991v2"})
    assert second.status_code == 200
    result = second.json()
    assert result["url"].endswith("v2")
    assert result["reading"]["version_id"] == result["version_id"]
    assert result["reading"]["version_id"].endswith("v2")
    assert len(result["versions"]) == 2
    assert len(store.works("a")) == 1
    assert store.works("b") == []


async def test_api_explicit_import_and_disabled_schedule(client):
    body = {"record": preview().model_dump(), "profile_revision": 0, "import_profile": True}
    proposal = (await client.post("/workspace/import/preview", json=body)).json()
    assert proposal["entries_new"] == 1
    assert (await client.post("/workspace/import/apply", json={**body, "digest": proposal["digest"]})).status_code == 200
    assert (await client.post("/workspace/import/apply", json={**body, "digest": proposal["digest"]})).status_code == 200
    invalid = {**body, "record": {**body["record"], "revision": 2}}
    assert (await client.post("/workspace/import/preview", json=invalid)).status_code == 422
    schedule = {"revision": 0, "request_id": "sched", "data": {"enabled": False, "timezone": "America/Los_Angeles", "local_time": "07:00"}}
    assert (await client.post("/workspace/schedule", json=schedule)).json()["enabled"] is False
    enabled = {**schedule, "revision": 1, "request_id": "enable", "data": {**schedule["data"], "enabled": True}}
    assert (await client.post("/workspace/schedule", json=enabled)).status_code == 422
    invalid_zone = {**schedule, "data": {**schedule["data"], "timezone": "Mars/Tomorrow"}}
    assert (await client.post("/workspace/schedule", json=invalid_zone)).status_code == 422


async def test_api_items_stable_cursor_filters_and_new_observation_cutoff(client, store):
    ingest(store)
    value = item(work_id="arxiv:2611.00002", version_id="arxiv:2611.00002:v1", title="Second result", access_state="metadata")
    store.ingest("arxiv-cs-ai", [value], {"status": "success"}, {})
    response = (await client.get("/workspace/items?days=0&limit=1")).json()
    assert len(response["items"]) == 1 and response["next_cursor"]
    next_page = (await client.get("/workspace/items", params={"days": 0, "limit": 1, "cursor": response["next_cursor"]})).json()
    assert next_page["as_of"] == response["as_of"]
    assert next_page["items"][0]["work_id"] != response["items"][0]["work_id"]
    assert (await client.get("/workspace/items", params={"cursor": response["next_cursor"], "q": "changed"})).status_code == 422
    assert (await client.get("/workspace/items?cursor=invalid")).status_code == 422
    assert (await client.get("/workspace/items?as_of=not-a-time")).status_code == 422
    assert (await client.get("/workspace/items?as_of=2026-11-02T10:00:00")).status_code == 422
    for query in ["source_id=google-research", "access_state=full_text", "status=saved", "q=nope", "as_of=2026-11-01T00:00:00%2B00:00"]:
        assert (await client.get("/workspace/items?" + query)).json()["items"] == []
    matched = (await client.get("/workspace/items?q=Agent&access_state=abstract&source_id=arxiv-cs-ai&days=0")).json()
    assert len(matched["items"]) == 1
    negative = base64.urlsafe_b64encode(json.dumps({"as_of": response["as_of"], "offset": -1, "query": "wrong"}).encode()).decode()
    assert (await client.get("/workspace/items", params={"cursor": negative})).status_code == 422


async def test_api_library_keeps_excluded_dismissed_sources(client, store):
    value = ingest(store)
    await client.post("/workspace/profile", json={"revision": 0, "request_id": "exclusion", "data": ProfileData(exclusions=["agent"]).model_dump()})
    state = (await client.get("/workspace/state")).json()
    assert state["works"][0]["work_id"] == value["work_id"]
    assert (await client.post("/workspace/edition")).json()["work_ids"] == []


async def test_pagination_freezes_uncommitted_intake_and_private_state(client, store):
    for number in [1, 2, 3]:
        value = item(work_id=f"review:{number}", version_id=f"review:{number}:v1", source_record_id=f"review:{number}")
        store.ingest("arxiv-cs-ai", [value], {"status": "success"}, {})
    with store.pool.connection() as pending:
        store._put_item(pending, item(work_id="review:4", version_id="review:4:v1", source_record_id="review:4"))
        first = (await client.get("/workspace/items?days=0&limit=1")).json()
        assert first["items"][0]["work_id"] == "review:3"
        pending.commit()
    ids = [first["items"][0]["work_id"]]
    cursor = first["next_cursor"]
    while cursor:
        page = (await client.get("/workspace/items", params={"days": 0, "limit": 1, "cursor": cursor})).json()
        ids.extend(work["work_id"] for work in page["items"])
        cursor = page["next_cursor"]
    assert ids == ["review:3", "review:2", "review:1"]
    assert len(store.works("a")) == 4
    assert (await client.get("/workspace/items", params={"days": 0, "limit": 1, "cursor": first["next_cursor"]}, headers={"X-API-Key": "key-b"})).status_code == 422
    assert (await client.get("/workspace/items", params={"days": 0, "limit": 1, "cursor": first["next_cursor"], "as_of": "2000-01-01T00:00:00+00:00"})).status_code == 422
    malformed = base64.urlsafe_b64encode(json.dumps({"as_of": 123, "offset": 1, "query": "any"}).encode()).decode()
    assert (await client.get("/workspace/items", params={"cursor": malformed})).status_code == 422
    with store.pool.connection() as conn:
        conn.execute("UPDATE workspace_pages SET expires_at='2000-01-01T00:00:00Z'")
    assert (await client.get("/workspace/items", params={"days": 0, "limit": 1, "cursor": first["next_cursor"]})).status_code == 422
