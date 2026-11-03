"""Real Postgres retained materials: scope, immutable provenance and public samples."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace

import pytest
from psycopg.types.json import Jsonb

from src.workspace import fulltext as f
from src.workspace.material import MaterialError, extract_text
from src.workspace.materials_repository import WorkspaceMaterials
from src.workspace.store import ConflictError
from tests import test_workspace_store as support
from tests.test_workspace_fulltext import NOW, transport

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


def sample():
    spec = f.SAMPLES["2210.03629v3"]
    result = f.acquire_sample(spec.arxiv_version, page_numbers=[2], transport=transport, now=NOW)
    assert result.material is not None
    return (
        spec,
        result.material,
        result.receipt,
        {**result.receipt, "status": "qualified_manual_reader_excerpt"},
    )


def test_known_sample_registration_is_atomic_retry_safe_and_metadata_only(store) -> None:
    spec, material, acquisition, qualification = sample()
    repo = WorkspaceMaterials(store)
    first = repo.register_sample(spec, material, acquisition, qualification)
    assert first["created"] and first["registered"]
    assert not repo.register_sample(spec, material, acquisition, qualification)["created"]
    work = store.works("owner-a")[0]
    assert work["source_id"] == "scientific-sample" and work["access_state"] == "metadata"
    assert work["abstract"] == "" and work["published_at"] is None and work["updated_at"] is None
    assert work["version_label"] == "v3"
    assert store.works("owner-b")[0]["work_id"] == spec.work_id
    assert repo.get("owner-b", material.material_id)["source_hash"] == material.source_hash
    metadata = repo.list("owner-a", spec.work_id, spec.version_id)
    assert len(metadata) == 1 and metadata[0]["page_numbers"] == [2]
    assert "pages" not in metadata[0] and "spans" not in metadata[0]
    assert metadata[0]["provenance"]["qualification"]["status"] == "qualified_manual_reader_excerpt"
    retained = repo.get("owner-a", material.material_id)
    assert retained["spans"][0]["page"] == 2
    assert "provenance" not in next(iter(_stored_material_rows(store)))[0]
    with store.pool.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM workspace_observations WHERE source_id='scientific-sample'"
            ).fetchone()[0]
            == 1
        )


def _stored_material_rows(store):
    with store.pool.connection() as connection:
        return connection.execute("SELECT data FROM workspace_material").fetchall()


def test_existing_abstract_version_dates_and_reading_notes_remain_untouched(store) -> None:
    spec, material, acquisition, qualification = sample()
    original = support.ingest(
        store,
        work_id=spec.work_id,
        version_id=spec.version_id,
        source_id="arxiv-cs-ai",
        version_label="v3",
        abstract="Original retained abstract",
        published_at="2022-10-06T01:00:32Z",
        updated_at="2023-03-10T01:00:17Z",
    )
    store.write_entry("owner-a", support.entry(original))
    before = store.works("owner-a")[0]
    WorkspaceMaterials(store).register_sample(spec, material, acquisition, qualification)
    after = store.works("owner-a")[0]
    assert before == after
    versions = WorkspaceMaterials(store).list("owner-a", spec.work_id, spec.version_id)
    assert [item["scope"] for item in versions] == ["excerpt", "abstract"]
    assert all("pages" not in item and "spans" not in item for item in versions)
    abstract = next(item for item in versions if item["scope"] == "abstract")
    assert abstract["provenance"] == {}


def test_private_visibility_is_enforced_for_every_material_read(store) -> None:
    private = support.ingest(store, visibility_owner="owner-a")
    repo = WorkspaceMaterials(store)
    metadata = repo.list("owner-a", private["work_id"], private["version_id"])
    assert len(metadata) == 1
    material_id = metadata[0]["material_id"]
    assert repo.get("owner-a", material_id) is not None
    assert repo.list("owner-b", private["work_id"], private["version_id"]) == []
    assert repo.get("owner-b", material_id) is None
    assert repo.get("owner-a", "missing") is None
    assert repo.list("owner-a", "different-work", private["version_id"]) == []
    for operation in (
        lambda: repo.get("", material_id),
        lambda: repo.list("", private["work_id"], private["version_id"]),
    ):
        with pytest.raises(ValueError, match="named authenticated owner"):
            operation()


def test_public_registration_refuses_private_canonical_identity_collision(store) -> None:
    spec, material, acquisition, qualification = sample()
    support.ingest(
        store, work_id=spec.work_id, version_id=spec.version_id, visibility_owner="owner-a"
    )
    with pytest.raises(ConflictError, match="collides with private"):
        WorkspaceMaterials(store).register_sample(spec, material, acquisition, qualification)
    assert WorkspaceMaterials(store).get("owner-b", material.material_id) is None


def test_source_version_and_provenance_drift_refuse_before_any_writes(store) -> None:
    spec, material, acquisition, qualification = sample()
    repo = WorkspaceMaterials(store)
    cases = [
        (
            replace(spec, title="Changed title"),
            material,
            acquisition,
            qualification,
            "sample_spec_drift",
        ),
        (
            spec,
            replace(material, version_id="v999"),
            acquisition,
            qualification,
            "source_version_drift",
        ),
        (
            spec,
            replace(material, scope="abstract"),
            acquisition,
            qualification,
            "requires_pdf_material",
        ),
        (
            spec,
            replace(material, material_id="forged"),
            acquisition,
            qualification,
            "material_identity_drift",
        ),
        (
            spec,
            material,
            {**acquisition, "source_hash": "wrong"},
            qualification,
            "provenance_source_drift",
        ),
        (
            spec,
            material,
            {**acquisition, "resolved_url": "https://example.com/"},
            qualification,
            "acquisition_scope_drift",
        ),
        (spec, material, {**acquisition, "bytes": 0}, qualification, "acquisition_bounds_invalid"),
        (
            spec,
            material,
            acquisition,
            {**qualification, "material_id": "wrong"},
            "material_reference_drift",
        ),
        (
            spec,
            material,
            acquisition,
            {**qualification, "retained_pages": [1]},
            "page_mapping_drift",
        ),
        (
            spec,
            material,
            acquisition,
            {**qualification, "source_scope": "full_text"},
            "qualification_scope_drift",
        ),
        (
            spec,
            material,
            {**acquisition, "fetched_at": "2026-11-02T16:00:00"},
            qualification,
            "acquisition_time_required",
        ),
    ]
    for changed_spec, changed_material, changed_acquisition, changed_qualification, reason in cases:
        with pytest.raises(MaterialError, match=reason):
            repo.register_sample(
                changed_spec, changed_material, changed_acquisition, changed_qualification
            )
    assert store.works("owner-a") == []


def test_immutable_provenance_and_material_conflicts_do_not_overwrite(store) -> None:
    spec, material, acquisition, qualification = sample()
    repo = WorkspaceMaterials(store)
    repo.register_sample(spec, material, acquisition, qualification)
    original = repo.get("owner-a", material.material_id)
    with pytest.raises(ConflictError, match="provenance differs"):
        repo.register_sample(spec, material, acquisition, {**qualification, "changed_review": True})
    assert repo.get("owner-a", material.material_id) == original
    with store.pool.connection() as connection:
        connection.execute(
            "UPDATE workspace_material SET data=%s WHERE material_id=%s",
            (Jsonb({"tampered": True}), material.material_id),
        )
    with pytest.raises(ConflictError, match="material differs"):
        repo.register_sample(spec, material, acquisition, qualification)


def test_registration_refuses_version_owned_by_another_work_and_rolls_back(store) -> None:
    spec, material, acquisition, qualification = sample()
    support.ingest(store, work_id="different-public-work", version_id=spec.version_id)
    with pytest.raises(ConflictError, match="different work"):
        WorkspaceMaterials(store).register_sample(spec, material, acquisition, qualification)
    assert all(work["work_id"] != spec.work_id for work in store.works("owner-a"))


def test_empty_material_sorts_after_available_abstract(store) -> None:
    original = support.ingest(store)
    empty = extract_text(
        "", work_id=original["work_id"], version_id=original["version_id"], scope="excerpt"
    )
    with store.pool.connection() as connection:
        connection.execute(
            "INSERT INTO workspace_material VALUES (%s,%s,%s,%s,%s)",
            (
                empty.material_id,
                empty.version_id,
                empty.content_hash,
                empty.scope,
                Jsonb(asdict(empty)),
            ),
        )
    metadata = WorkspaceMaterials(store).list(
        "owner-a", original["work_id"], original["version_id"]
    )
    assert [item["scope"] for item in metadata] == ["abstract", "excerpt"]


def test_provenance_cannot_change_license_or_certify_a_failed_download(store) -> None:
    spec, material, acquisition, qualification = sample()
    repo = WorkspaceMaterials(store)
    bad_license = {
        **qualification,
        "sample": {**qualification["sample"], "license_url": "https://example.com/unverified"},
    }
    with pytest.raises(MaterialError, match="provenance_sample_drift"):
        repo.register_sample(spec, material, acquisition, bad_license)
    with pytest.raises(MaterialError, match="acquisition_not_successful"):
        repo.register_sample(
            spec, material, {**acquisition, "status": "unavailable"}, qualification
        )
    assert store.works("owner-a") == []


def test_two_registration_attempts_publish_one_immutable_material(store) -> None:
    args = sample()
    repo = WorkspaceMaterials(store)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: repo.register_sample(*args), [1, 2]))
    assert sorted(result["created"] for result in results) == [False, True]
    assert len(repo.list("owner-a", args[0].work_id, args[0].version_id)) == 1
    with store.pool.connection() as connection:
        assert (
            connection.execute("SELECT count(*) FROM workspace_material_provenance").fetchone()[0]
            == 1
        )
