"""Offline CI browser data uses real Postgres; replay never resets private work.

The seed must opt in before obtaining a pool. These tests run its actual script
entrypoint inside a fresh test schema; no fixture response replaces persistence.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.config import settings as shipped_settings
from src.tools import postgres_pool
from src.workspace import intake, routes, scheduler
from src.workspace.schemas import (
    EntryData,
    EntryWrite,
    ProfileData,
    ProfileWrite,
    ReadingData,
    ReadingWrite,
    WorkspaceState,
)
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg

pytestmark = pytest.mark.integration
SEED = Path(__file__).resolve().parents[1] / "web/e2e/fixtures/workspace_seed.py"
OWNER = "e2e"
WORK_IDS = {
    "ci:workspace-agent-evaluation",
    "ci:workspace-retrieval-budget",
    "ci:workspace-feed-excerpt",
}


def environment(monkeypatch):
    for key, value in {
        "WORKSPACE_E2E_SEED": "1",
        "ENABLE_WORKSPACE": "true",
        "USE_MOCK_DATA": "true",
        "ANTHROPIC_API_KEY": "local-preview-disabled",
        "E2E_PRINCIPAL": OWNER,
    }.items():
        monkeypatch.setenv(key, value)
    config = shipped_settings.model_copy(
        update={
            "enable_workspace": True,
            "use_mock_data": True,
            "enable_api_auth": True,
            "postgres_url": "postgresql://unused/offline-seed-test",
        }
    )
    monkeypatch.setattr("src.config.settings", config)
    monkeypatch.setattr(postgres_pool, "settings", config)
    monkeypatch.setattr(routes, "settings", config)


def run_seed(store, monkeypatch):
    environment(monkeypatch)
    get_pool, close_pool = Mock(return_value=store.pool), Mock()
    monkeypatch.setattr(postgres_pool, "get_pool", get_pool)
    monkeypatch.setattr(postgres_pool, "close_pool", close_pool)
    network = Mock(side_effect=AssertionError("offline seed must not fetch source metadata"))
    provider = Mock(side_effect=AssertionError("offline seed must not construct a provider"))
    monkeypatch.setattr(intake, "fetch_source", network)
    monkeypatch.setattr(routes, "fetch_source", network)
    monkeypatch.setattr("src.llm._get_client", provider)
    runpy.run_path(str(SEED), run_name="__main__")
    get_pool.assert_called_once_with()
    close_pool.assert_called_once_with()
    network.assert_not_called()
    provider.assert_not_called()


def counts(store):
    with store.pool.connection() as conn:
        return {
            table: conn.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in (
                "workspace_works",
                "workspace_versions",
                "workspace_material",
                "workspace_observations",
                "workspace_entries",
                "workspace_editions",
                "workspace_ingest_runs",
                "workspace_profiles",
                "workspace_history",
            )
        }


def test_real_seed_replay_has_exact_works_versions_and_no_duplicate_briefing_entries(
    store, monkeypatch
):
    run_seed(store, monkeypatch)
    first = store.works(OWNER)
    before = counts(store)
    assert {work["work_id"] for work in first} == WORK_IDS
    assert before["workspace_works"] == 3
    assert before["workspace_versions"] == 4
    assert before["workspace_material"] == 4
    assert before["workspace_observations"] == 4
    assert before["workspace_ingest_runs"] == 5
    assert len(store.editions(OWNER)) == 1
    run_seed(store, monkeypatch)
    assert counts(store) == before
    assert store.works(OWNER) == first
    assert len(store.editions(OWNER)) == 1


def test_replay_preserves_existing_personal_profile_notes_questions_and_version_anchor(
    store, monkeypatch
):
    run_seed(store, monkeypatch)
    profile = store.profile(OWNER)
    edited = store.write_profile(
        OWNER,
        ProfileWrite(
            revision=profile["revision"],
            request_id="owner-profile",
            data=ProfileData(
                research_question="My personal research question",
                custom_topics=["My precise custom interest"],
            ),
        ),
    )
    work = next(
        work for work in store.works(OWNER) if work["work_id"] == "ci:workspace-agent-evaluation"
    )
    original_version = next(
        version["version_id"] for version in work["versions"] if version["version_label"] == "v1"
    )
    for id_, kind, body in (
        ("private-note", "note", "Keep these exact private words."),
        ("private-question", "question", "Which baseline would falsify this?"),
    ):
        store.write_entry(
            OWNER,
            EntryWrite(
                id=id_,
                revision=0,
                request_id=id_,
                data=EntryData(
                    work_id=work["work_id"],
                    version_id=original_version,
                    kind=kind,
                    body=body,
                    anchor="abstract:12",
                ),
            ),
        )
    saved = store.write_reading(
        OWNER,
        ReadingWrite(
            work_id=work["work_id"],
            revision=work["reading"]["revision"],
            request_id="owner-reading",
            data=ReadingData(status="saved", version_id=original_version, anchor="abstract:12"),
        ),
    )
    before = counts(store)
    run_seed(store, monkeypatch)
    assert store.profile(OWNER) == edited
    after = counts(store)
    assert after == {**before, "workspace_editions": before["workspace_editions"] + 1}
    run_seed(store, monkeypatch)
    assert counts(store) == after
    restored = next(
        work for work in store.works(OWNER) if work["work_id"] == "ci:workspace-agent-evaluation"
    )
    assert restored["reading"] == saved
    assert restored["version_id"].endswith(":v2")
    assert {entry["body"] for entry in restored["entries"]} == {
        "Keep these exact private words.",
        "Which baseline would falsify this?",
    }
    assert all(
        entry["version_id"] == original_version and entry["anchor"] == "abstract:12"
        for entry in restored["entries"]
    )
    assert store.works("another-owner")[0]["entries"] == []


def test_receipts_are_explicit_offline_fixtures_and_all_browser_prerequisites_exist(
    store, monkeypatch
):
    run_seed(store, monkeypatch)
    sources = store.sources()
    assert len(sources) == 5 and {source["source_id"] for source in sources} == set(intake.SOURCES)
    for source in sources:
        assert source["status"] == "not_checked"
        assert source["last_success_at"] is None
        assert source["receipt"]["request_count"] == 0
        assert source["receipt"]["reason"] == "offline_fixture"
        assert source["receipt"]["fixture_provenance"] == "workspace-browser-synthetic-v1"
        assert source["receipt"]["successful_window"] is None
    monkeypatch.setattr(routes, "_store", store)
    state = WorkspaceState.model_validate(routes.snapshot(OWNER)).model_dump()
    assert state["principal_key_id"] == OWNER
    assert state["generation"] == "approval_required"
    assert state["profile"]["data"]["research_question"].strip()
    assert any(work["abstract"] and work["access_state"] == "abstract" for work in state["works"])
    assert any("retrieval" in (work["title"] + work["abstract"]).lower() for work in state["works"])
    assert all(
        work["kind"] == "fixture"
        and work["title"].startswith("CI fixture")
        and work["url"].startswith("https://example.invalid/")
        for work in store.works(OWNER)
    )
    assert all(
        work["fixture_provenance"] == "workspace-browser-synthetic-v1"
        for work in store.works(OWNER)
    )
    edition = store.editions(OWNER)[0]
    assert edition["work_ids"] and edition["status"] == "ready_partial"
    assert not scheduler.schedule(store, OWNER)["enabled"]
    assert scheduler.tasks(store, OWNER) == []
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM workspace_generation_jobs").fetchone()[0] == 0


@pytest.mark.parametrize(
    "key,value",
    [
        ("WORKSPACE_E2E_SEED", "0"),
        ("ENABLE_WORKSPACE", "false"),
        ("USE_MOCK_DATA", "false"),
        ("ANTHROPIC_API_KEY", "another-invalid-test-key"),
        ("E2E_PRINCIPAL", ""),
        ("E2E_PRINCIPAL", "../../owner"),
        ("E2E_PRINCIPAL", "x" * 65),
    ],
)
def test_seed_guards_refuse_before_obtaining_pool(monkeypatch, key, value):
    environment(monkeypatch)
    monkeypatch.setenv(key, value)
    get_pool, close_pool = Mock(), Mock()
    monkeypatch.setattr(postgres_pool, "get_pool", get_pool)
    monkeypatch.setattr(postgres_pool, "close_pool", close_pool)
    with pytest.raises(SystemExit):
        runpy.run_path(str(SEED), run_name="__main__")
    get_pool.assert_not_called()
    close_pool.assert_not_called()


def test_seed_refuses_a_database_with_real_records_before_changing_private_or_source_state(
    store, monkeypatch
):
    real = support.ingest(store)
    store.write_entry(
        OWNER,
        EntryWrite(
            id="real-note",
            revision=0,
            request_id="real-note",
            data=EntryData(
                work_id=real["work_id"],
                version_id=real["version_id"],
                kind="note",
                body="Preserve my real private note",
                anchor="abstract:4",
            ),
        ),
    )
    store.write_profile(
        OWNER,
        ProfileWrite(
            revision=0,
            request_id="private-profile",
            data=ProfileData(research_question="Do not overwrite my real research question"),
        ),
    )
    before_counts = counts(store)
    before_profile = store.profile(OWNER)
    before_sources = store.sources()
    before_works = store.works(OWNER)
    with pytest.raises(SystemExit, match="non-fixture"):
        run_seed(store, monkeypatch)
    assert counts(store) == before_counts
    assert store.profile(OWNER) == before_profile
    assert store.sources() == before_sources
    assert store.works(OWNER) == before_works


def test_seed_refuses_another_owners_private_import_even_without_source_receipts(
    store, monkeypatch
):
    from src.workspace.schemas import ImportRequest

    request = ImportRequest(record=support.preview(), profile_revision=0, import_profile=True)
    inspected = store.import_preview("private-other-owner", request)
    store.import_apply("private-other-owner", request, inspected["digest"])
    before_counts = counts(store)
    before_other = store.works("private-other-owner")
    before_other_profile = store.profile("private-other-owner")
    before_seed_profile = store.profile(OWNER)
    before_sources = store.sources()
    assert before_other and before_other[0]["entries"]
    assert store.works(OWNER) == []
    assert all(not source.get("receipt") for source in before_sources)
    with pytest.raises(SystemExit, match="non-fixture"):
        run_seed(store, monkeypatch)
    assert counts(store) == before_counts
    assert store.works("private-other-owner") == before_other
    assert store.profile("private-other-owner") == before_other_profile
    assert store.profile(OWNER) == before_seed_profile
    assert store.sources() == before_sources
    assert store.works(OWNER) == []
