"""Real ordered research activity, exact source context, pinning and upgrades."""
from __future__ import annotations

import pytest

from src.workspace import routes
from src.workspace.schemas import (
    EntryData,
    EntryWrite,
    ProfileData,
    ProfileWrite,
    ReadingData,
    ReadingWrite,
)
from src.workspace.store import WorkspaceStore
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


def two_works(store):
    first = support.ingest(store)
    second = support.item(work_id="arxiv:2611.00002", version_id="arxiv:2611.00002:v1", source_record_id="2611.00002")
    store.ingest("arxiv-cs-ai", [second], {"status": "success"}, {})
    return first, second


def save(store, work, id_, body="Which baseline?", revision=0, request=None):
    write = EntryWrite(id=id_, revision=revision, request_id=request or id_, data=EntryData(
        work_id=work["work_id"], version_id=work["version_id"], kind="question", body=body, anchor="abstract:3:12"))
    return store.write_entry("verification", write)


def test_latest_question_uses_committed_sequence_and_edit_activity_across_papers(store, monkeypatch):
    first, second = two_works(store)
    a = save(store, first, "z-first-question")
    b = save(store, second, "a-second-question")
    assert b["activity_sequence"] > a["activity_sequence"] > 0
    assert store.activity("verification")[0]["entry_id"] == "a-second-question"
    assert save(store, second, "a-second-question") == b
    assert len(store.activity("verification")) == 2
    support.ingest(store, 2)
    edited = save(store, first, "z-first-question", "Edited earlier question", revision=1, request="edit-a")
    # Even clock ties cannot change event order, nor attach the old note to v2.
    with store.pool.connection() as conn:
        conn.execute("UPDATE workspace_activity SET updated_at='2026-01-01T00:00:00Z'")
    restarted = WorkspaceStore(store.pool)
    monkeypatch.setattr(routes, "repository", lambda: restarted)
    state = routes.snapshot("verification")
    latest = state["latest_activity"]
    assert latest["sequence"] == edited["activity_sequence"]
    assert latest["entry_id"] == "z-first-question" and latest["revision"] == 2
    assert latest["version_id"] == first["version_id"]
    assert latest["anchor"] == "abstract:3:12" and latest["body"] == "Edited earlier question"
    assert state["works"][0]["entries"] or state["works"][1]["entries"]
    assert restarted.activity("another-owner") == []


def test_reading_return_pin_and_unpin_preserve_the_exact_entry_and_anchor(store, monkeypatch):
    first, second = two_works(store)
    save(store, first, "question")
    result = store.write_reading("verification", ReadingWrite(work_id=second["work_id"], revision=0,
        request_id="return-from-reader", data=ReadingData(status="saved", version_id=second["version_id"], anchor="abstract:10:20")))
    monkeypatch.setattr(routes, "repository", lambda: WorkspaceStore(store.pool))
    activity = routes.snapshot("verification")["latest_activity"]
    assert activity["kind"] == "reading" and activity["entry_id"] is None
    assert activity["work_id"] == second["work_id"] and activity["anchor"] == "abstract:10:20"
    assert activity["sequence"] == result["activity_sequence"]
    store.write_profile("verification", ProfileWrite(revision=0, request_id="pin", data=ProfileData(pinned_entry_id="question")))
    pinned = routes.snapshot("verification")["latest_activity"]
    assert pinned["entry_id"] == "question" and pinned["version_id"] == first["version_id"]
    with pytest.raises(ValueError, match="belong"):
        store.write_profile("other", ProfileWrite(revision=0, request_id="foreign-pin", data=ProfileData(pinned_entry_id="question")))
    store.write_profile("verification", ProfileWrite(revision=1, request_id="unpin", data=ProfileData()))
    assert routes.snapshot("verification")["latest_activity"] == activity
    reading = next(work for work in store.works("verification") if work["work_id"] == second["work_id"])["reading"]
    assert reading == result


def test_activity_upgrade_backfills_live_history_without_resurrecting_deleted_entries(store):
    first, second = two_works(store)
    save(store, first, "kept")
    save(store, second, "removed-qa")
    before = store.profile("verification")
    with store.pool.connection() as conn:
        conn.execute("DELETE FROM workspace_entries WHERE id='removed-qa'")
        conn.execute("DELETE FROM workspace_activity")
        conn.execute("DELETE FROM workspace_schema WHERE revision='004_activity_and_review'")
    restarted = WorkspaceStore(store.pool)
    restarted.migrate()
    events = restarted.activity("verification")
    assert [event["entry_id"] for event in events] == ["kept"]
    assert restarted.profile("verification") == before
    assert len(restarted.works("verification")) == 2
