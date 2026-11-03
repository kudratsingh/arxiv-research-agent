"""Reading availability is derived for the visible exact version, never written back."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from src.workspace.availability import reading_availability
from src.workspace.material import extract_pdf, extract_text
from tests import test_workspace_api as api_support
from tests import test_workspace_store as support
from tests.test_workspace_material import twenty_page_pdf
from tests.test_workspace_material_api import retain

store = support.store
client = api_support.client
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_pdf_excerpt_is_discoverable_without_rewriting_metadata(client, store):
    original = support.ingest(store, access_state="metadata", abstract="", source_scope="metadata")
    with store.pool.connection() as conn:
        before = conn.execute(
            "SELECT data FROM workspace_versions WHERE version_id=%s", (original["version_id"],)
        ).fetchone()[0]
    material = retain(
        store,
        extract_pdf(
            twenty_page_pdf(),
            work_id=original["work_id"],
            version_id=original["version_id"],
            page_numbers=[2, 18],
        ),
    )
    state = (await client.get("/workspace/state")).json()
    work = state["works"][0]
    assert work["access_state"] == "metadata" and work["abstract"] == ""
    assert work["reading_access_state"] == "excerpt" and work["available_scopes"] == ["excerpt"]
    availability = work["retained_materials"][0]
    assert availability["material_id"] == material.material_id and availability["format"] == "pdf"
    assert availability["retained_pages"] == [2, 18] and not availability["complete"]
    assert availability["first_anchor"].startswith(f"material:{material.material_id}:page:2:")
    assert work["versions"][0]["retained_materials"] == work["retained_materials"]
    assert (await client.get("/workspace/items", params={"access_state": "excerpt"})).json()[
        "items"
    ][0]["work_id"] == original["work_id"]
    assert (await client.get("/workspace/items", params={"access_state": "metadata"})).json()[
        "items"
    ] == []
    with store.pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT data FROM workspace_versions WHERE version_id=%s", (original["version_id"],)
            ).fetchone()[0]
            == before
        )


async def test_material_does_not_leak_to_another_version_or_owner(client, store):
    first = support.ingest(store, access_state="metadata", abstract="")
    retain(
        store,
        extract_text(
            "Exact retained evidence", work_id=first["work_id"], version_id=first["version_id"]
        ),
    )
    latest = support.ingest(store, 2, access_state="metadata", abstract="")
    work = (await client.get("/workspace/state")).json()["works"][0]
    assert work["version_id"] == latest["version_id"] and work["reading_access_state"] == "metadata"
    assert work["retained_materials"] == []
    assert (
        next(v for v in work["versions"] if v["version_id"] == first["version_id"])[
            "reading_access_state"
        ]
        == "excerpt"
    )
    assert (await client.get("/workspace/items", params={"access_state": "excerpt"})).json()[
        "items"
    ] == []
    other = support.item(
        work_id="private-work",
        version_id="private-work:v1",
        visibility_owner="b",
        access_state="metadata",
        abstract="",
    )
    store.ingest("manual", [other], {"status": "success"}, {})
    retain(
        store,
        extract_text(
            "Private source text", work_id=other["work_id"], version_id=other["version_id"]
        ),
    )
    assert all(w["work_id"] != "private-work" for w in store.works("a"))
    assert any(
        w["work_id"] == "private-work" and w["reading_access_state"] == "excerpt"
        for w in store.works("b")
    )


async def test_empty_failed_wrong_version_material_is_not_an_available_excerpt(client, store):
    work = support.ingest(store, abstract="", access_state="metadata")
    empty = extract_text("", work_id=work["work_id"], version_id=work["version_id"])
    retain(store, empty)
    assert reading_availability(work, [asdict(empty)])["available_scopes"] == ["metadata"]
    valid = asdict(
        extract_text("Available text", work_id=work["work_id"], version_id=work["version_id"])
    )
    for changes in [
        {"version_id": "other"},
        {"work_id": "other"},
        {"quality": "failed"},
        {"quality": None},
        {"scope": "unknown"},
        {"spans": []},
    ]:
        assert reading_availability(work, [{**valid, **changes}])["retained_materials"] == []
    assert reading_availability(
        {**work, "abstract": "An observed abstract", "access_state": "abstract"}, []
    )["available_scopes"] == ["abstract"]
    assert reading_availability(
        {**work, "abstract": "A feed excerpt", "access_state": "excerpt"}, []
    )["available_scopes"] == ["excerpt"]
