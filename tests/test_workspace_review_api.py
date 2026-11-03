"""Authenticated JSON review packets stay blank until an explicit owner judgment."""

from __future__ import annotations

import pytest

from src.workspace.schemas import EntryData, EntryWrite
from tests import test_workspace_api as api_support
from tests import test_workspace_reviews as review_support
from tests import test_workspace_store as support

store = support.store
client = api_support.client
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def counts(store):
    with store.pool.connection() as conn:
        return tuple(
            conn.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in (
                "workspace_review_packets",
                "workspace_usefulness_feedback",
                "workspace_mutations",
            )
        )


async def prepare(client, request_id="http-review"):
    response = await client.post(
        "/workspace/review/prepare", json={"profile_revision": 0, "request_id": request_id}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_get_is_read_only_and_prepare_freezes_ten_blank_actual_candidates(client, store):
    values = review_support.candidates(store, 10)
    store.write_entry(
        "a",
        EntryWrite(
            id="private-note",
            revision=0,
            request_id="private-note",
            data=EntryData(
                work_id=values[0]["work_id"],
                version_id=values[0]["version_id"],
                kind="note",
                body="PRIVATE NOTE MUST NOT ENTER REVIEW",
            ),
        ),
    )
    before = counts(store)
    for _ in range(2):
        response = await client.get("/workspace/review")
        assert response.status_code == 200 and response.json() == {"packet": None, "packet_ids": []}
    assert counts(store) == before
    packet = await prepare(client)
    assert len(packet["items"]) == 10 and packet["labelled_count"] == 0
    assert {item["work"]["work_id"] for item in packet["items"]} == {
        item["work_id"] for item in values
    }
    assert all(
        item["feedback"] == {"revision": 0, "label": None, "reason": "", "updated_at": ""}
        for item in packet["items"]
    )
    assert all(
        item["matching_reason"] and item["estimated_minutes"] == 5 for item in packet["items"]
    )
    assert all(item["work"]["entries"] == [] for item in packet["items"])
    assert "PRIVATE NOTE" not in str(packet)
    assert counts(store)[1] == 0
    retry = await prepare(client)
    assert retry == packet
    assert counts(store)[0] == 1
    before_get = counts(store)
    selected = await client.get("/workspace/review", params={"packet_id": packet["id"]})
    assert selected.status_code == 200 and selected.json()["packet"] == packet
    assert selected.json()["packet_ids"] == [packet["id"]]
    assert counts(store) == before_get


async def test_feedback_is_explicit_version_pinned_retry_safe_and_clearable(client, store):
    review_support.candidates(store, 10)
    packet = await prepare(client)
    work = packet["items"][0]["work"]
    body = {
        "packet_id": packet["id"],
        "work_id": work["work_id"],
        "version_id": work["version_id"],
        "revision": 0,
        "request_id": "feedback-one",
        "label": "useful",
        "reason": "Useful for my fixed-baseline question",
    }
    response = await client.post("/workspace/review/feedback", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["label"] == "useful" and saved["revision"] == 1 and saved["updated_at"]
    assert (await client.post("/workspace/review/feedback", json=body)).json() == saved
    current = (await client.get("/workspace/review")).json()["packet"]
    assert current["labelled_count"] == 1 and current["items"][0]["feedback"] == saved
    assert all(item["feedback"]["label"] is None for item in current["items"][1:])
    assert (await prepare(client))["id"] == packet["id"]
    newer = support.item(
        work_id=work["work_id"],
        version_id=work["work_id"] + ":v2",
        version_label="v2",
        content_hash="changed",
        abstract="A changed source version",
        fetched_at=store.cutoff(),
    )
    store.ingest("arxiv-cs-ai", [newer], {"status": "success"}, {})
    frozen = (await client.get("/workspace/review", params={"packet_id": packet["id"]})).json()[
        "packet"
    ]
    assert frozen["items"][0]["work"]["version_id"] == work["version_id"]
    wrong_version = await client.post(
        "/workspace/review/feedback",
        json={
            **body,
            "version_id": newer["version_id"],
            "revision": 1,
            "request_id": "wrong-version",
        },
    )
    assert wrong_version.status_code == 422
    assert (
        await client.post(
            "/workspace/review/feedback",
            json={**body, "label": "irrelevant", "request_id": "stale-revision"},
        )
    ).status_code == 409
    assert (
        await client.post(
            "/workspace/review/feedback", json={**body, "reason": "Changed retry body"}
        )
    ).status_code == 409
    cleared = await client.post(
        "/workspace/review/feedback",
        json={**body, "revision": 1, "request_id": "explicit-clear", "label": None, "reason": ""},
    )
    assert cleared.status_code == 200 and cleared.json()["label"] is None
    assert (await client.get("/workspace/review")).json()["packet"]["labelled_count"] == 0


async def test_review_ownership_and_typed_rejections_do_not_create_labels(client, store):
    review_support.candidates(store, 10)
    packet = await prepare(client)
    work = packet["items"][0]["work"]
    foreign = {"X-API-Key": "key-b"}
    assert (await client.get("/workspace/review", headers=foreign)).json() == {
        "packet": None,
        "packet_ids": [],
    }
    assert (
        await client.get("/workspace/review", params={"packet_id": packet["id"]}, headers=foreign)
    ).status_code == 404
    body = {
        "packet_id": packet["id"],
        "work_id": work["work_id"],
        "version_id": work["version_id"],
        "revision": 0,
        "request_id": "feedback",
        "label": "maybe",
        "reason": "Owner must label this",
    }
    assert (
        await client.post("/workspace/review/feedback", json=body, headers=foreign)
    ).status_code == 422
    assert (
        await client.post("/workspace/review/feedback", json={**body, "label": "fabricated-score"})
    ).status_code == 422
    assert (
        await client.post(
            "/workspace/review/prepare", json={"profile_revision": 9, "request_id": "stale-profile"}
        )
    ).status_code == 409
    assert (
        await client.post(
            "/workspace/review/prepare",
            json={"profile_revision": 0, "request_id": "extra", "label": "useful"},
        )
    ).status_code == 422
    assert counts(store)[1] == 0
    assert (await client.get("/workspace/review")).json()["packet"]["labelled_count"] == 0


async def test_empty_review_is_honest_without_fictional_filler(client, store):
    assert (await client.get("/workspace/review")).json()["packet"] is None
    packet = await prepare(client)
    assert packet["items"] == [] and packet["labelled_count"] == 0
    assert any("fictional filler" in note for note in packet["limitations"])
    assert counts(store)[1] == 0
