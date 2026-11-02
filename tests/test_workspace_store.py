"""Real Postgres persistence, ownership, revision and replay invariants.

CI uses pytest-postgresql. Local isolated Compose verification sets
WORKSPACE_TEST_POSTGRES_URL; no fallback memory implementation exists.
"""
from __future__ import annotations

import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from src.workspace import scheduler
from src.workspace.schemas import (
    EntryData,
    EntryWrite,
    ImportRequest,
    PreviewRecord,
    ProfileData,
    ProfileWrite,
    ReadingData,
    ReadingWrite,
    ScheduleData,
    ScheduleWrite,
)
from src.workspace.store import ConflictError, WorkspaceStore, digest

pytestmark = pytest.mark.integration
if shutil.which("postgres"):
    from pytest_postgresql import factories
    workspace_pg_proc = factories.postgresql_proc(port=None, unixsocketdir="/tmp")
    workspace_pg = factories.postgresql("workspace_pg_proc")


@pytest.fixture
def store(request):
    url = os.environ.get("WORKSPACE_TEST_POSTGRES_URL")
    if not url:
        if not shutil.which("postgres"):
            pytest.skip("real Postgres unavailable; set WORKSPACE_TEST_POSTGRES_URL")
        pg = request.getfixturevalue("workspace_pg")
        info = pg.info
        url = f"postgresql://{info.user}:@{info.host}:{info.port}/{info.dbname}"
    schema = "ws_test_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(psycopg.sql.SQL("CREATE SCHEMA {}").format(psycopg.sql.Identifier(schema)))
    pool = ConnectionPool(url, min_size=1, max_size=4, kwargs={"options": f"-c search_path={schema},public"}, open=True)
    repository = WorkspaceStore(pool)
    repository.migrate()
    yield repository
    pool.close()
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(psycopg.sql.SQL("DROP SCHEMA {} CASCADE").format(psycopg.sql.Identifier(schema)))


def item(version=1, **extra):
    return {"work_id": "arxiv:2611.00001", "version_id": f"arxiv:2611.00001:v{version}", "source_id": "arxiv-cs-ai", "source_record_id": "2611.00001", "title": "Agent memory evaluation", "url": "https://arxiv.org/abs/2611.00001", "abstract": f"Abstract revision {version}", "access_state": "abstract", "version_label": f"v{version}", "first_seen_at": "2026-11-02T10:00:00+00:00", "fetched_at": f"2026-11-02T10:0{version}:00+00:00", "content_hash": str(version), **extra}


def ingest(store, version=1, **extra):
    value = item(version, **extra)
    store.ingest("arxiv-cs-ai", [value], {"status": "success", "fetched_at": value["fetched_at"], "successful_window": {"start": value["fetched_at"], "end": value["fetched_at"]}}, {"etag": str(version)})
    return value


def entry(value, **extra):
    return EntryWrite(id="note-1", revision=0, request_id="note-1-write", data=EntryData(work_id=value["work_id"], version_id=value["version_id"], kind="question", body="What falsifies this result?", anchor="abstract:12", **extra))


def preview(**extra):
    return PreviewRecord(revision=1, topics=["ml:agents-and-tool-use"], customTopics=["bounded agents"], configured=True, minutes=15, saved=["fixture-1"], entries=[{"id": "browser-note", "itemId": "fixture-1", "kind": "note", "body": "Keep my words", "anchor": "source"}], anchors={"fixture-1": "notes"}, done=False, researchQuestion="An editable question", streams=["core"], **extra)


def test_profile_revision_isolation_idempotence_and_restart(store):
    assert store.profile("a")["revision"] == 0
    write = ProfileWrite(revision=0, request_id="p1", data=ProfileData(custom_topics=["test"], research_question="My private question"))
    assert store.write_profile("a", write)["revision"] == 1
    assert store.write_profile("a", write)["revision"] == 1
    restarted = WorkspaceStore(store.pool)
    assert restarted.profile("a")["data"]["research_question"] == "My private question"
    assert restarted.profile("b")["revision"] == 0
    with pytest.raises(ConflictError):
        store.write_profile("a", write.model_copy(update={"request_id": "p2"}))
    with pytest.raises(ConflictError):
        store.write_profile("a", write.model_copy(update={"data": ProfileData(research_question="different")}))
    with pytest.raises(ValueError):
        store.profile("")


def test_concurrent_profile_edit_has_one_winner(store):
    def edit(n):
        try:
            return store.write_profile("a", ProfileWrite(revision=0, request_id=f"p{n}", data=ProfileData(research_question=str(n))))["revision"]
        except ConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(edit, [1, 2]), key=str) == [1, "conflict"]


def test_versioned_reading_and_private_entries(store):
    v1 = ingest(store)
    note = store.write_entry("a", entry(v1))
    assert store.write_entry("a", entry(v1)) == note
    store.write_reading("a", ReadingWrite(work_id=v1["work_id"], revision=0, request_id="read", data=ReadingData(status="saved", version_id=v1["version_id"], anchor="abstract:12")))
    ingest(store, 2)
    resumed = WorkspaceStore(store.pool).works("a")[0]
    assert resumed["version_id"].endswith("v2")
    assert resumed["entries"][0]["version_id"].endswith("v1")
    assert resumed["reading"]["anchor"] == "abstract:12"
    assert resumed["reading"]["version_id"].endswith("v1")
    assert store.works("b")[0]["entries"] == []
    assert store.works("b")[0]["reading"]["status"] == "unread"
    changed = entry(v1).model_copy(update={"revision": 1, "request_id": "edit", "data": entry(v1).data.model_copy(update={"body": "New question"})})
    assert store.write_entry("a", changed)["revision"] == 2
    with pytest.raises(ConflictError):
        store.write_entry("a", entry(v1).model_copy(update={"request_id": "stale"}))
    with pytest.raises(ConflictError):
        store.write_reading("a", ReadingWrite(work_id=v1["work_id"], revision=0, request_id="stale-read", data=ReadingData(version_id=v1["version_id"])))
    with pytest.raises(ValueError):
        store.write_entry("a", entry(v1).model_copy(update={"id": "new", "request_id": "badversion", "data": entry(v1).data.model_copy(update={"version_id": "wrong"})}))


def test_ingestion_duplicate_failed_page_and_rollback(store):
    value = ingest(store)
    ingest(store)
    assert len(store.works("a")) == 1
    assert len(store.works("a")[0]["versions"]) == 1
    store.ingest("arxiv-cs-ai", [], {"status": "failed", "error": "timeout"}, {"etag": "bad"})
    assert store.validators("arxiv-cs-ai") == {"etag": "1"}
    source = next(s for s in store.sources() if s["source_id"] == "arxiv-cs-ai")
    assert source["status"] == "failed" and source["last_success_at"]
    assert store.validators("not-checked") == {}
    bad = item(3, fetched_at="not-a-date")
    with pytest.raises(psycopg.Error):
        store.ingest("arxiv-cs-ai", [item(2), bad], {"status": "success"}, {"etag": "advanced"})
    assert len(store.works("a")[0]["versions"]) == 1
    assert store.validators("arxiv-cs-ai") == {"etag": "1"}
    assert value["work_id"] == store.works("a")[0]["work_id"]


def test_import_preview_retry_conflict_and_owner_isolation(store):
    request = ImportRequest(record=preview(), profile_revision=0, import_profile=True)
    inspected = store.import_preview("a", request)
    assert inspected["entries_new"] == 1 and inspected["profile_will_change"]
    assert store.works("a") == []
    with pytest.raises(ConflictError):
        store.import_apply("a", request, "not-the-preview")
    assert store.import_apply("a", request, inspected["digest"]) == inspected
    assert store.import_apply("a", request, inspected["digest"]) == inspected
    assert len(store.works("a")[0]["entries"]) == 1
    assert store.works("b") == []
    assert store.profile("a")["data"]["research_question"] == request.record.researchQuestion
    modified = request.model_copy(update={"profile_revision": 1, "record": request.record.model_copy(update={"entries": [request.record.entries[0].model_copy(update={"body": "Conflicting browser edit"})]})})
    report = store.import_preview("a", modified)
    assert report["entries_existing"] == 1 and report["conflicts"]
    with pytest.raises(ConflictError):
        store.import_apply("a", modified, report["digest"])
    assert store.works("a")[0]["entries"][0]["body"] == "Keep my words"
    conflict = ImportRequest(record=preview(), profile_revision=0, import_profile=True)
    assert store.import_preview("a", conflict)["conflicts"]
    moved_entry = request.record.entries[0].model_copy(update={"itemId": "another-source", "anchor": "source:12"})
    moved = request.model_copy(update={"import_profile": False, "record": request.record.model_copy(update={"entries": [moved_entry]})})
    moved_preview = store.import_preview("a", moved)
    assert moved_preview["conflicts"]
    with pytest.raises(ConflictError):
        store.import_apply("a", moved, moved_preview["digest"])


def test_import_private_version_cannot_be_annotated_by_other_owner(store):
    request = ImportRequest(record=preview(), profile_revision=0)
    store.import_apply("a", request, digest(request.model_dump()))
    private = store.works("a")[0]
    with pytest.raises(ValueError):
        store.write_entry("b", entry(private))


def test_edition_freezes_coverage_and_profile_inputs(store):
    value = ingest(store)
    edition = store.edition("a", [value["work_id"]], minutes=15, revision=3)
    assert edition["status"] == "ready_partial"
    assert edition["work_versions"] == {value["work_id"]: value["version_id"]}
    ingest(store, 2)
    assert store.editions("a")[0]["work_versions"] == edition["work_versions"]
    store.ingest("arxiv-cs-ai", [], {"status": "failed"}, {})
    assert store.editions("a")[0]["coverage"] == edition["coverage"]
    assert store.editions("b") == []
    ephemeral = store.edition("a", [], minutes=5, revision=4, persist=False)
    assert ephemeral["id"] not in {e["id"] for e in store.editions("a")}


@pytest.mark.parametrize(("instant", "expected"), [("2026-03-08T00:00:00+00:00", "2026-03-08T10:00:00+00:00"), ("2026-11-01T00:00:00+00:00", "2026-11-01T08:30:00+00:00")])
def test_dst_gap_and_fold(instant, expected):
    day = datetime.fromisoformat(instant)
    time = "02:30" if day.month == 3 else "01:30"
    assert scheduler.local_occurrence(day, time, "America/Los_Angeles").isoformat() == expected
    assert scheduler.next_occurrence(datetime.fromisoformat(expected) + timedelta(hours=2), time, "America/Los_Angeles") > datetime.fromisoformat(expected)
    with pytest.raises(ValueError):
        scheduler.local_occurrence(day, "26:40", "UTC")


def test_schedule_disabled_until_confirmation_and_72h_catchup(store):
    now = datetime(2026, 11, 2, 16, tzinfo=UTC)
    assert not scheduler.schedule(store, "a")["enabled"]
    write = ScheduleWrite(revision=0, request_id="sched", data=ScheduleData(enabled=True, local_time="07:00"))
    with pytest.raises(ValueError):
        scheduler.write_schedule(store, "a", write, now=now)
    result = scheduler.write_schedule(store, "a", write, approved=True, now=now)
    assert result["next_check"]
    with pytest.raises(ConflictError):
        scheduler.write_schedule(store, "a", write.model_copy(update={"request_id": "stale"}), approved=True, now=now)
    after_sleep = now + timedelta(hours=72)
    assert scheduler.enqueue_due(store, now=after_sleep) == 1
    assert scheduler.enqueue_due(store, now=after_sleep) == 0
    claimed = scheduler.claim(store, "one", now=after_sleep)
    assert claimed and scheduler.claim(store, "two", now=after_sleep) is None
    recovered = scheduler.claim(store, "two", now=after_sleep + timedelta(minutes=6))
    assert recovered and recovered["id"] == claimed["id"]
    assert len(scheduler.tasks(store, "a")) == 1
    assert "catch-up" in scheduler.tasks(store, "a")[0]["reason"]
    paused = ScheduleWrite(revision=1, request_id="pause", data=ScheduleData(enabled=False))
    assert not scheduler.write_schedule(store, "a", paused)["enabled"]
    assert scheduler.tasks(store, "a")[0]["state"] == "cancelled"
    assert scheduler.run_once(store, lambda _: {}, now=after_sleep) is None


def test_worker_publish_atomic_retry_and_pause_fence(store):
    now = datetime(2026, 11, 2, 16, tzinfo=UTC)
    scheduler.write_schedule(store, "a", ScheduleWrite(revision=0, request_id="sched", data=ScheduleData(enabled=True)), approved=True, now=now - timedelta(days=1))
    def build(owner):
        return store.edition(owner, [], minutes=15, revision=0, persist=False)
    assert scheduler.run_once(store, build, now=now)["state"] == "ready"
    assert scheduler.run_once(store, build, now=now) is None
    assert len(store.editions("a")) == 1
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM workspace_delivery_intents").fetchone()[0] == 1
    def paused(owner):
        scheduler.write_schedule(store, owner, ScheduleWrite(revision=1, request_id="pause", data=ScheduleData()))
        return build(owner)
    assert scheduler.run_once(store, paused, now=now + timedelta(days=1))["state"] == "lease_lost"
    assert len(store.editions("a")) == 1


def test_worker_bounded_failed_attempts(store):
    now = datetime(2026, 11, 2, 16, tzinfo=UTC)
    scheduler.write_schedule(store, "a", ScheduleWrite(revision=0, request_id="sched", data=ScheduleData(enabled=True)), approved=True, now=now - timedelta(days=1))
    def failure(_):
        raise RuntimeError("not logged private context")
    for minute in [0, 1, 3]:
        assert scheduler.run_once(store, failure, now=now + timedelta(minutes=minute))["state"] == "failed_attempt"
    assert scheduler.tasks(store, "a")[0]["state"] == "failed"
    assert scheduler.tasks(store, "a")[0]["reason"] == "RuntimeError"
    assert scheduler.run_once(store, failure, now=now + timedelta(minutes=10)) is None
