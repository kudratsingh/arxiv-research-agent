"""Actual authenticated HTTP/JSON bindings for the separate zero-dollar fake lane."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from src.workspace import executor as x
from src.workspace.schemas import EntryData, EntryWrite, ProfileData, ProfileWrite
from tests import test_workspace_api as api_support
from tests import test_workspace_store as support

store = support.store
client = api_support.client
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def retained(store):
    item = support.ingest(store)
    with store.pool.connection() as conn:
        material_id = conn.execute(
            "SELECT material_id FROM workspace_material WHERE version_id=%s", (item["version_id"],)
        ).fetchone()[0]
    return item, material_id


async def submit(client, material_id, *, kind="summary", request_id="http-job", question=""):
    selection = {"kind": kind, "material_ids": [material_id], "question": question}
    response = await client.post("/workspace/generation/preview", json=selection)
    assert response.status_code == 200, response.text
    preview = response.json()
    response = await client.post(
        "/workspace/generation/jobs",
        json={**selection, "request_id": request_id, "expected_digest": preview["request_digest"]},
    )
    assert response.status_code == 200, response.text
    return preview, response.json()


@pytest.mark.parametrize("kind", ["summary", "deep_dive"])
async def test_http_exact_preview_stage_steps_result_reload_and_cache(client, store, kind):
    item, material_id = retained(store)
    preview, job = await submit(client, material_id, kind=kind)
    assert preview["mode"] == job["mode"] == "fake"
    assert preview["request"] == job["request"]
    assert preview["request_digest"] == job["request_digest"]
    assert preview["actual_usd"] == "0.000000" and "not provider tokens" in preview["usage_basis"]
    assert job["state"] == "queued" and job["steps"] == []
    path = "/workspace/generation/jobs/" + job["id"]
    draft = await client.post(path + "/advance")
    assert draft.status_code == 200, draft.text
    checkpoint = draft.json()
    assert checkpoint["state"] == "checking" and checkpoint["draft"]["kind"] == kind
    assert checkpoint["lease_until"] is None and checkpoint["result"] is None
    assert checkpoint["usage"]["used_calls"] == 1
    reloaded = await client.get(path)
    assert reloaded.status_code == 200 and reloaded.json() == checkpoint
    final = await client.post(path + "/advance")
    assert final.status_code == 200, final.text
    result = final.json()
    assert result["state"] == "ready" and result["usage"]["used_calls"] == 2
    assert result["result"]["mode"] == "fake"
    assert result["result"]["draft"]["kind"] == kind
    assert "not a calibrated judge" in result["result"]["check_basis"]
    reference = result["result"]["draft"]["claims"][0]["evidence"][0]
    assert reference["material_id"] == material_id and reference["version_id"] == item["version_id"]
    assert result["usage"]["workflow"]["input_tokens"] > 0
    assert result["usage"]["checker"]["input_tokens"] > 0
    assert result["usage"]["unknown"] == {"input_tokens": 0, "output_tokens": 0}
    assert (await client.get(path)).json() == result
    assert (await client.get("/workspace/generation/jobs")).json() == [result]
    _, cached = await submit(client, material_id, kind=kind, request_id="same-input-new-key")
    assert cached["cached"] and cached["id"] == job["id"]
    with store.pool.connection() as conn:
        fake = conn.execute(
            "SELECT count(*),sum(actual_usd) FROM workspace_fake_generation_reservations"
        ).fetchone()
        assert fake == (1, 0)
        for table in (
            "workspace_budget_policies",
            "workspace_generation_jobs",
            "workspace_spend_reservations",
        ):
            assert conn.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0


async def test_http_confirmed_digest_is_required_and_private_context_is_excluded(client, store):
    item, material_id = retained(store)
    store.write_profile(
        "a",
        ProfileWrite(
            revision=0,
            request_id="private-profile",
            data=ProfileData(research_question="PRIVATE PROFILE NOT IN GENERATION"),
        ),
    )
    store.write_entry(
        "a",
        EntryWrite(
            id="private-note",
            revision=0,
            request_id="private-note",
            data=EntryData(
                work_id=item["work_id"],
                version_id=item["version_id"],
                kind="note",
                body="PRIVATE NOTE NOT IN GENERATION",
            ),
        ),
    )
    selection = {"kind": "summary", "material_ids": [material_id]}
    response = await client.post("/workspace/generation/preview", json=selection)
    assert response.status_code == 200
    preview = response.json()
    assert "PRIVATE" not in response.text
    assert preview["request"]["question"] == ""
    assert preview["request"]["private_context"] == {
        "notes": False,
        "reading_history": False,
        "profile": False,
    }
    missing = await client.post(
        "/workspace/generation/jobs", json={**selection, "request_id": "missing"}
    )
    assert missing.status_code == 422
    wrong = await client.post(
        "/workspace/generation/jobs",
        json={**selection, "request_id": "wrong", "expected_digest": "sha256:" + "0" * 64},
    )
    assert wrong.status_code == 409
    changed = await client.post(
        "/workspace/generation/jobs",
        json={
            **selection,
            "request_id": "changed",
            "expected_digest": preview["request_digest"],
            "question": "Changed after exact preview",
        },
    )
    assert changed.status_code == 409
    assert (await client.get("/workspace/generation/jobs")).json() == []
    assert (
        await client.post(
            "/workspace/generation/preview", json={**selection, "include_private_notes": True}
        )
    ).status_code == 422


async def test_http_cancel_queued_and_between_steps_keeps_durable_draft_and_usage(client, store):
    _, material_id = retained(store)
    _, queued = await submit(client, material_id, request_id="queued")
    queued_path = "/workspace/generation/jobs/" + queued["id"]
    stopped = await client.post(queued_path + "/cancel")
    assert stopped.status_code == 200 and stopped.json()["state"] == "cancelled"
    assert stopped.json()["usage"]["used_calls"] == 0
    assert (await client.post(queued_path + "/advance")).json() == stopped.json()
    _, active = await submit(
        client, material_id, request_id="between", question="Different checkpoint"
    )
    active_path = "/workspace/generation/jobs/" + active["id"]
    draft = (await client.post(active_path + "/advance")).json()
    cancelled = (await client.post(active_path + "/cancel")).json()
    assert cancelled["state"] == "cancelled" and cancelled["cancel_requested"]
    assert cancelled["draft"] == draft["draft"] and cancelled["usage"] == draft["usage"]
    assert cancelled["result"] is None
    assert (await client.get(active_path)).json() == cancelled


async def test_http_recovery_reports_unknown_completion_without_replaying(client, store):
    _, material_id = retained(store)
    _, job = await submit(client, material_id)

    class LostProcess(x.FakeProvider):
        def draft(self, request, *, cancelled):
            raise SystemExit("controlled local process loss")

    now = datetime.fromisoformat(store.cutoff())
    with pytest.raises(SystemExit):
        x.FakeExecutor(store).advance("a", job["id"], provider=LostProcess(), now=now)
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_fake_generation_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
            (job["id"],),
        )
    path = "/workspace/generation/jobs/" + job["id"]
    response = await client.post(path + "/recover")
    assert response.status_code == 200, response.text
    recovered = response.json()
    assert recovered["state"] == "interrupted" and recovered["steps"][0]["state"] == "interrupted"
    assert recovered["usage"]["unknown"]["input_tokens"] > 0
    assert recovered["usage"]["unknown"]["output_tokens"] > 0
    assert recovered["usage"]["actual_usd"] == "0.000000" and recovered["result"] is None
    assert (await client.post(path + "/advance")).json() == recovered
    assert (await client.get(path)).json() == recovered


async def test_http_ownership_and_disabled_key_guards_precede_any_sdk(client, store, monkeypatch):
    _, material_id = retained(store)
    _, job = await submit(client, material_id)
    path = "/workspace/generation/jobs/" + job["id"]
    foreign = {"X-API-Key": "key-b"}
    assert (await client.get(path, headers=foreign)).status_code == 404
    for action in ("advance", "cancel", "recover"):
        assert (await client.post(path + "/" + action, headers=foreign)).status_code == 404
    assert (await client.get("/workspace/generation/jobs", headers=foreign)).json() == []
    provider = Mock(side_effect=AssertionError("no SDK client may be constructed"))
    monkeypatch.setattr("src.llm._get_client", provider)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "another-invalid-test-key")
    assert (await client.post(path + "/advance")).status_code == 403
    response = await client.post(
        "/workspace/generation/jobs",
        json={
            "kind": "summary",
            "material_ids": [material_id],
            "request_id": "disabled",
            "expected_digest": job["request_digest"],
        },
    )
    assert response.status_code == 403
    paid = await client.post("/workspace/generate", json={"kind": "summary", "work_id": "any"})
    assert paid.status_code == 403
    provider.assert_not_called()
    assert (await client.get(path)).json()["usage"]["used_calls"] == 0


async def test_http_private_material_and_invalid_fake_selection_are_refused(client, store):
    item = support.item(work_id="private:a", version_id="private:a:v1", visibility_owner="a")
    store.ingest("arxiv-cs-ai", [item], {"status": "success"}, {})
    with store.pool.connection() as conn:
        material = conn.execute(
            "SELECT material_id FROM workspace_material WHERE version_id='private:a:v1'"
        ).fetchone()[0]
    assert (
        await client.post(
            "/workspace/generation/preview",
            json={"kind": "summary", "material_ids": [material]},
            headers={"X-API-Key": "key-b"},
        )
    ).status_code == 422
    assert (
        await client.post(
            "/workspace/generation/preview", json={"kind": "summary", "material_ids": []}
        )
    ).status_code == 422
    assert (
        await client.post(
            "/workspace/generation/preview", json={"kind": "paid", "material_ids": [material]}
        )
    ).status_code == 422
    assert (
        await client.post(
            "/workspace/generation/preview",
            json={"kind": "summary", "material_ids": [material], "span_ids": ["not-retained"]},
        )
    ).status_code == 422
