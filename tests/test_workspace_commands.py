"""Local commands and immutable material replay use real isolated Postgres."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

import pytest

from src.workspace import __main__ as cli
from src.workspace import routes, scheduler
from src.workspace.intake import FetchResult
from src.workspace.schemas import ProfileData, ReadingData
from src.workspace.store import WorkspaceStore
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("verb", ["migrate", "initialize", "worker-once", "refresh", "export"])
def test_real_workspace_commands(store, monkeypatch, capsys, verb):
    monkeypatch.setattr(cli, "get_pool", lambda: store.pool)
    closed = []
    monkeypatch.setattr(cli, "close_pool", lambda: closed.append(True))
    monkeypatch.setattr(routes, "repository", lambda: store)
    monkeypatch.setattr(routes, "fetch_source", lambda source_id, **kw: FetchResult([support.item(source_id=source_id)], {"status": "success"}, {}))
    monkeypatch.setattr(sys, "argv", ["workspace", verb, "--owner", "a", "--sources", "arxiv-cs-ai"])
    cli.main()
    output = capsys.readouterr().out
    assert closed == [True]
    if verb == "migrate":
        assert "schema migrated" in output
    elif verb == "initialize":
        assert store.profile("a")["revision"] == 1
        original = store.profile("a")
        cli.main()
        assert store.profile("a") == original
        from src.workspace.schemas import ProfileWrite
        store.write_profile("a", ProfileWrite(revision=1, request_id="owner-edit", data=ProfileData(research_question="My edited question")))
        cli.main()
        assert store.profile("a")["data"]["research_question"] == "My edited question"
    elif verb == "worker-once":
        assert json.loads(output)["state"] == "idle"
    elif verb == "refresh":
        assert json.loads(output)["work_ids"]
        assert len(store.works("a")) == 1
    else:
        assert "profile" in json.loads(output)


def test_measured_material_revisions_and_migration_integrity(store):
    original = support.ingest(store)
    changed = {**original, "title": "Corrected same-version metadata", "abstract": "Different retained text", "content_hash": "newhash", "fetched_at": "2026-11-02T10:05:00+00:00"}
    store.ingest("arxiv-cs-ai", [changed], {"status": "success"}, {})
    store.ingest("arxiv-cs-ai", [changed], {"status": "success"}, {})
    versions = store.works("a")[0]["versions"]
    assert len(versions) == 2
    assert versions[0]["version_id"] != versions[1]["version_id"]
    assert "metadata revision" in versions[0]["version_label"]
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM workspace_material").fetchone()[0] == 2
        conn.execute("UPDATE workspace_schema SET checksum='changed' WHERE revision='001_workspace'")
    with pytest.raises(RuntimeError, match="checksum"):
        WorkspaceStore(store.pool).migrate()


def test_stored_retry_after_survives_restart_and_blocks_fetch(store, monkeypatch):
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    store.ingest("arxiv-cs-ai", [], {"status": "rate_limited", "retry_after": future}, {})
    restarted = WorkspaceStore(store.pool)
    monkeypatch.setattr(routes, "repository", lambda: restarted)
    def denied(*args, **kwargs):
        raise AssertionError("Retry-After must prevent network access")
    monkeypatch.setattr(routes, "fetch_source", denied)
    routes.refresh("a", ["arxiv-cs-ai"])
    assert restarted.sources()[1]["status"] == "rate_limited"


def test_final_expired_worker_lease_becomes_failed(store):
    now = datetime(2026, 11, 2, 16, tzinfo=UTC)
    from src.workspace.schemas import ScheduleData, ScheduleWrite
    scheduler.write_schedule(store, "a", ScheduleWrite(revision=0, request_id="s", data=ScheduleData(enabled=True)), approved=True, now=now - timedelta(days=1))
    scheduler.enqueue_due(store, now=now)
    for minute in [0, 6, 12]:
        assert scheduler.claim(store, "worker", now=now + timedelta(minutes=minute))
    assert scheduler.claim(store, "next", now=now + timedelta(minutes=18)) is None
    assert scheduler.tasks(store, "a")[0]["state"] == "failed"


@pytest.mark.parametrize("old_state", ["queued", "running"])
def test_queued_before_sleep_coalesces_to_one_bounded_catchup(store, old_state):
    from src.workspace.schemas import ScheduleData, ScheduleWrite
    before = datetime(2026, 11, 1, 16, tzinfo=UTC)
    scheduler.write_schedule(store, "a", ScheduleWrite(revision=0, request_id="s", data=ScheduleData(enabled=True)), approved=True, now=before - timedelta(days=1))
    assert scheduler.enqueue_due(store, now=before) == 1
    if old_state == "running":
        assert scheduler.claim(store, "dead-worker", now=before)
    after = before + timedelta(hours=72)
    def build(owner):
        return store.edition(owner, [], minutes=15, revision=0, persist=False)
    assert scheduler.run_once(store, build, now=after)["state"] == "ready"
    assert scheduler.run_once(store, build, now=after) is None
    assert len(store.editions("a")) == 1
    assert len([task for task in scheduler.tasks(store, "a") if task["state"] == "cancelled"]) == 1


def test_explicit_versions_order_numerically_and_read_state_cursor_stays_frozen(store):
    from src.workspace.schemas import ReadingWrite
    support.ingest(store, 9)
    support.ingest(store, 2)
    value = support.ingest(store, 10, fetched_at="2026-11-02T10:15:00+00:00")
    assert store.works("a")[0]["version_id"].endswith("v10")
    cutoff = store.cutoff()
    store.write_reading("a", ReadingWrite(work_id=value["work_id"], revision=0, request_id="r", data=ReadingData(status="saved", version_id=value["version_id"])))
    assert store.works("a")[0]["reading"]["status"] == "saved"
    assert store.works("a", as_of=cutoff)[0]["reading"]["status"] == "unread"


@pytest.mark.parametrize("data", [{"custom_topics": [""]}, {"custom_topics": ["x" * 501]}])
def test_profile_bounds(data):
    with pytest.raises(ValueError):
        ProfileData(**data)


def test_snooze_requires_instant_and_duplicate_import_ids_refused():
    with pytest.raises(ValueError):
        ReadingData(snoozed_until="2026-11-02T09:00:00")
    assert ReadingData(snoozed_until="2026-11-02T09:00:00+00:00").snoozed_until
    original = support.preview().model_dump()
    original["entries"] *= 2
    with pytest.raises(ValueError, match="unique"):
        type(support.preview())(**original)
    with pytest.raises(ValueError, match="no valid"):
        scheduler.local_occurrence(datetime(2011, 12, 30), "07:00", "Pacific/Apia")


def test_frozen_pages_bound_memory_owner_and_filters(store):
    with pytest.raises(ValueError, match="narrow"):
        store.freeze_page("a", "q", store.cutoff(), [{}] * 2001)
    with pytest.raises(ValueError, match="narrow"):
        store.freeze_page("a", "q", store.cutoff(), [{"abstract": "x" * (4 * 1024 * 1024)}])
    id_ = store.freeze_page("a", "q", store.cutoff(), [])
    assert store.frozen_page("a", id_, "q")[1] == []
    with pytest.raises(ValueError):
        store.frozen_page("b", id_, "q")
    with pytest.raises(ValueError):
        store.frozen_page("a", id_, "different")


def test_two_real_workers_publish_only_one_occurrence(store):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from src.workspace.schemas import ScheduleData, ScheduleWrite
    now = datetime(2026, 11, 2, 16, tzinfo=UTC)
    scheduler.write_schedule(store, "a", ScheduleWrite(revision=0, request_id="s", data=ScheduleData(enabled=True)), approved=True, now=now - timedelta(days=1))
    barrier = Barrier(2)
    def worker(number):
        barrier.wait(timeout=5)
        return scheduler.run_once(store, lambda owner: store.edition(owner, [], minutes=15, revision=0, persist=False), now=now, worker=f"worker-{number}")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, [1, 2]))
    assert len([result for result in results if result and result["state"] == "ready"]) == 1
    assert len(store.editions("a")) == 1
    assert len(scheduler.tasks(store, "a")) == 1
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM workspace_delivery_intents").fetchone()[0] == 1
