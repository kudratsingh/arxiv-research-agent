"""Retained source HTTP bindings: original pages, Unicode anchors and ownership.

All source bytes are synthetic and inserted into an isolated Postgres schema.
Reading retained material must not fetch remote text or move a private anchor.
"""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import Mock

import pytest
from psycopg.types.json import Jsonb

from src.workspace import fulltext, intake, routes
from src.workspace.material import extract_pdf, extract_text
from tests import test_workspace_api as api_support
from tests import test_workspace_store as support
from tests.test_workspace_material import twenty_page_pdf

store = support.store
client = api_support.client
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def retain(store, material):
    with store.pool.connection() as connection:
        connection.execute(
            "INSERT INTO workspace_material VALUES (%s,%s,%s,%s,%s)",
            (
                material.material_id,
                material.version_id,
                material.content_hash,
                material.scope,
                Jsonb(asdict(material)),
            ),
        )
    return material


def forbid_fetch(monkeypatch):
    fetch = Mock(side_effect=AssertionError("retained-material API must not fetch sources"))
    monkeypatch.setattr(routes, "fetch_source", fetch)
    monkeypatch.setattr(intake, "fetch_source", fetch)
    monkeypatch.setattr(fulltext, "_fetch", fetch)
    return fetch


def note_write(item, anchor, *, body="Keep this exact source context"):
    return {
        "id": "material-note",
        "revision": 0,
        "request_id": "material-note",
        "data": {
            "work_id": item["work_id"],
            "version_id": item["version_id"],
            "kind": "note",
            "body": body,
            "anchor": anchor,
        },
    }


def reading_write(item, anchor):
    return {
        "work_id": item["work_id"],
        "revision": 0,
        "request_id": "material-reading",
        "data": {"version_id": item["version_id"], "status": "saved", "anchor": anchor},
    }


async def test_material_http_rehydrates_selected_original_pages_without_fetch(
    client, store, monkeypatch
):
    item = support.ingest(store)
    material = retain(
        store,
        extract_pdf(
            twenty_page_pdf(),
            work_id=item["work_id"],
            version_id=item["version_id"],
            page_numbers=[2, 18],
        ),
    )
    fetch = forbid_fetch(monkeypatch)
    params = {"work_id": item["work_id"], "version_id": item["version_id"]}
    response = await client.get("/workspace/materials", params=params)
    assert response.status_code == 200, response.text
    listing = response.json()
    info = next(value for value in listing if value["material_id"] == material.material_id)
    assert info["page_numbers"] == [2, 18] and info["page_count"] == 20
    assert info["scope"] == "excerpt" and not info["complete"]
    assert info["quality"] == "partial" and "Unicode" in info["offset_basis"]
    assert "pages" not in info and "spans" not in info
    response = await client.get("/workspace/materials/" + material.material_id)
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["pages"] == list(material.pages)
    assert document["page_numbers"] == [2, 18] and document["page_count"] == 20
    assert [span["page"] for span in document["spans"]] == [2, 18]
    for index, span in enumerate(document["spans"]):
        assert f"Original PDF page {span['page']}:" in span["text"]
        assert span["text"] == document["pages"][index][span["start"] : span["end"]]
        assert span["version_id"] == item["version_id"]
        assert span["source_hash"] == document["source_hash"]
    assert document["provenance"] == {}
    assert (await client.get("/workspace/materials/" + material.material_id)).json() == document
    assert (
        await client.get("/workspace/materials", params={**params, "version_id": "absent:v1"})
    ).json() == []
    assert (await client.get("/workspace/materials")).status_code == 422
    assert (await client.get("/workspace/materials/absent")).status_code == 404
    fetch.assert_not_called()


async def test_unicode_codepoint_anchor_roundtrips_and_stays_on_original_version(client, store):
    item = support.ingest(store)
    text = "α 😀 café: naïve source claim.\nA later observation."
    material = retain(
        store,
        extract_text(text, work_id=item["work_id"], version_id=item["version_id"]),
    )
    start, end = text.index("naïve"), len(text)
    assert start != len(text[:start].encode("utf-8"))
    assert start != len(text[:start].encode("utf-16-le")) // 2
    anchor = f"material:{material.material_id}:page:1:{start}:{end}"
    note = note_write(item, anchor, body="My α 😀 question about naïve assumptions")
    saved = await client.post("/workspace/entries", json=note)
    assert saved.status_code == 200, saved.text
    assert saved.json()["anchor"] == anchor
    reading = await client.post("/workspace/reading", json=reading_write(item, anchor))
    assert reading.status_code == 200, reading.text
    assert reading.json()["anchor"] == anchor
    assert (await client.post("/workspace/entries", json=note)).json() == saved.json()
    document = (await client.get("/workspace/materials/" + material.material_id)).json()
    assert document["pages"][0] == text
    assert document["pages"][0][start:end] == "naïve source claim.\nA later observation."
    assert document["spans"][0]["end"] == len(text)
    byte_end = len(text.encode("utf-8"))
    byte_anchor = f"material:{material.material_id}:page:1:{start}:{byte_end}"
    bad_reading = reading_write(item, byte_anchor)
    bad_reading.update(revision=1, request_id="reject-byte-offsets")
    assert (await client.post("/workspace/reading", json=bad_reading)).status_code == 422
    support.ingest(store, 2, abstract="Revised source text must not retarget my annotation")
    state = (await client.get("/workspace/state")).json()
    work = next(value for value in state["works"] if value["work_id"] == item["work_id"])
    assert work["version_id"].endswith(":v2")
    assert work["reading"]["version_id"] == item["version_id"]
    assert work["reading"]["anchor"] == anchor
    assert work["entries"][0]["anchor"] == anchor
    assert work["entries"][0]["version_id"] == item["version_id"]
    assert work["entries"][0]["body"] == note["data"]["body"]
    assert (await client.get("/workspace/materials/" + material.material_id)).json() == document
    exported = await client.get("/workspace/export")
    assert exported.status_code == 200
    assert anchor in exported.text and item["version_id"] in exported.text
    assert note["data"]["body"] in exported.text


async def test_invalid_material_anchors_refuse_without_changing_saved_note_or_reading(
    client, store
):
    item = support.ingest(store)
    material = retain(
        store,
        extract_pdf(
            twenty_page_pdf(),
            work_id=item["work_id"],
            version_id=item["version_id"],
            page_numbers=[2, 18],
        ),
    )
    anchor = f"material:{material.material_id}:page:18:0:8"
    note = note_write(item, anchor)
    assert (await client.post("/workspace/entries", json=note)).status_code == 200
    assert (
        await client.post("/workspace/reading", json=reading_write(item, anchor))
    ).status_code == 200
    newer = support.ingest(store, 2)
    another = support.ingest(
        store,
        work_id="arxiv:2611.99999",
        version_id="arxiv:2611.99999:v1",
        source_record_id="2611.99999",
    )
    before = (await client.get("/workspace/state")).json()
    before.pop("as_of")
    invalid = [
        ({}, "material:mat-" + "0" * 32 + ":page:2:0:1"),
        ({}, f"material:{material.material_id}:page:1:0:1"),
        ({}, f"material:{material.material_id}:page:2:0:{len(material.pages[0]) + 1}"),
        ({}, f"material:{material.material_id}:page:2:5:4"),
        ({}, f"material:{material.material_id}:page:2:not-an-offset:4"),
        ({"version_id": newer["version_id"]}, anchor),
        ({"work_id": another["work_id"], "version_id": another["version_id"]}, anchor),
    ]
    for index, (source, bad_anchor) in enumerate(invalid):
        changed = {
            **note,
            "revision": 1,
            "request_id": f"bad-note-{index}",
            "data": {**note["data"], **source, "body": "Must never be saved", "anchor": bad_anchor},
        }
        response = await client.post("/workspace/entries", json=changed)
        assert response.status_code == 422, response.text
        read = reading_write(item, bad_anchor)
        read.update(revision=1, request_id=f"bad-reading-{index}")
        read["data"].update(version_id=source.get("version_id", item["version_id"]))
        if "work_id" in source:
            read["work_id"] = source["work_id"]
        response = await client.post("/workspace/reading", json=read)
        assert response.status_code == 422, response.text
        after = (await client.get("/workspace/state")).json()
        after.pop("as_of")
        assert after == before


async def test_private_material_http_has_no_foreign_existence_or_text_leak(
    client, store, monkeypatch
):
    item = support.ingest(store, visibility_owner="a", abstract="PRIVATE α 😀 source")
    with store.pool.connection() as connection:
        material_id = connection.execute(
            "SELECT material_id FROM workspace_material WHERE version_id=%s", (item["version_id"],)
        ).fetchone()[0]
    fetch = forbid_fetch(monkeypatch)
    params = {"work_id": item["work_id"], "version_id": item["version_id"]}
    own = await client.get("/workspace/materials", params=params)
    assert own.status_code == 200 and len(own.json()) == 1
    assert own.json()[0]["material_id"] == material_id
    own_document = await client.get("/workspace/materials/" + material_id)
    assert own_document.status_code == 200 and own_document.json()["pages"] == [item["abstract"]]
    other = {"X-API-Key": "key-b"}
    assert (await client.get("/workspace/materials", params=params, headers=other)).json() == []
    foreign = await client.get("/workspace/materials/" + material_id, headers=other)
    absent = await client.get("/workspace/materials/mat-" + "f" * 32, headers=other)
    assert foreign.status_code == absent.status_code == 404
    foreign_error, absent_error = foreign.json(), absent.json()
    assert foreign_error["error"].pop("request_id")
    assert absent_error["error"].pop("request_id")
    assert foreign_error == absent_error and "PRIVATE" not in foreign.text
    anchor = f"material:{material_id}:page:1:0:1"
    assert (
        await client.post("/workspace/entries", json=note_write(item, anchor), headers=other)
    ).status_code == 422
    assert (await client.get("/workspace/state", headers=other)).json()["works"] == []
    fetch.assert_not_called()
