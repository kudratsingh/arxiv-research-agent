"""Real PostgreSQL projects share source/note identities and fail closed."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from src.workspace.context_schemas import (
    ArtifactData,
    ContextEntryWrite,
    ContextPreferencesData,
    ContextPreferencesWrite,
    ContextReadingWrite,
    EntryReference,
    LearningThreadData,
    LearningThreadWrite,
    ProjectArtifactWrite,
    ProjectData,
    ProjectEntryWrite,
    ProjectSourceWrite,
    ProjectUnlink,
    ProjectWrite,
    ResumeContext,
    SourceReference,
)
from src.workspace.context_store import ContextNotFound, WorkspaceContext
from src.workspace.material import _build
from src.workspace.schemas import EntryData, ProfileData, ProfileWrite, ReadingData
from src.workspace.store import ConflictError, WorkspaceStore
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration
PID = "project-" + "a" * 32
TID = "thread-" + "b" * 32


def project(**extra):
    return ProjectWrite(
        id=PID,
        revision=0,
        request_id="create",
        data=ProjectData(title="Compare agents", question="How do agent memory methods differ?"),
        **extra,
    )


def ref(value, anchor="abstract:0:8", **extra):
    return SourceReference(
        work_id=value["work_id"], version_id=value["version_id"], anchor=anchor, **extra
    )


def test_context_index_reads_do_not_create_preferences_or_projects(store):
    repo = WorkspaceContext(store)
    assert repo.index("a")["projects"] == []
    assert repo.index("b")["preferences"]["revision"] == 0
    with store.pool.connection() as conn:
        for table in (
            "workspace_profiles",
            "workspace_context_preferences",
            "workspace_projects",
            "workspace_learning_threads",
        ):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    with pytest.raises(ValueError):
        repo.index("")


def test_preferences_are_independent_retry_safe_and_not_reset_by_legacy_writes(store):
    repo = WorkspaceContext(store)
    write = ContextPreferencesWrite(
        revision=0,
        request_id="prefs",
        data=ContextPreferencesData(
            default_mode="research",
            learning_background="Engineer",
            learning_goals=["Understand attention"],
        ),
    )
    assert repo.preferences("a", write) == repo.preferences("a", write)
    store.write_profile("a", ProfileWrite(revision=0, request_id="old-client", data=ProfileData()))
    assert repo.index("a")["preferences"]["data"]["learning_background"] == "Engineer"
    assert repo.index("b")["preferences"]["data"]["default_mode"] == "learn"
    with pytest.raises(ConflictError):
        repo.preferences("a", write.model_copy(update={"request_id": "stale"}))
    with pytest.raises(ConflictError):
        repo.preferences("a", write.model_copy(update={"data": ContextPreferencesData()}))


def test_project_create_from_question_is_atomic_exact_shared_and_owned(store):
    value = support.ingest(store)
    note = store.write_entry("a", support.entry(value))
    write = project(
        initial_source=ref(value),
        origin_entry=EntryReference(entry_id=note["id"], entry_revision=1),
    )
    repo = WorkspaceContext(store)
    first = repo.write_project("a", write)
    assert first == repo.write_project("a", write)
    assert first["entries"][0]["entry"]["body"] == note["body"]
    assert len(first["sources"]) == 1
    assert WorkspaceContext(WorkspaceStore(store.pool)).project("a", PID) == first
    assert repo.index("b")["projects"] == []
    with pytest.raises(ContextNotFound):
        repo.project("b", PID)
    with pytest.raises(ValueError, match="owned_entry"):
        repo.write_project("b", write)
    assert repo.index("b")["projects"] == []  # failed initial link rolls back project
    edited = support.entry(value).model_copy(
        update={
            "revision": 1,
            "request_id": "edit",
            "data": support.entry(value).data.model_copy(update={"body": "Later revision"}),
        }
    )
    store.write_entry("a", edited)
    entry = repo.project("a", PID)["entries"][0]
    assert entry["entry_revision"] == 1 and entry["current_revision"] == 2
    assert entry["entry"]["body"] == note["body"]
    with store.pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM workspace_entries").fetchone()[0] == 1


def test_project_concurrency_retry_fingerprints_and_archive_preserve_library(store):
    value = support.ingest(store)
    repo = WorkspaceContext(store)
    repo.write_project("a", project(initial_source=ref(value)))

    def edit(n):
        try:
            return repo.write_project(
                "a",
                ProjectWrite(
                    id=PID,
                    revision=1,
                    request_id=f"edit-{n}",
                    data=ProjectData(title=f"Project {n}", question="Compare methods"),
                ),
            )["revision"]
        except ConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(edit, (1, 2)), key=str) == [2, "conflict"]
    archived = repo.write_project(
        "a",
        ProjectWrite(
            id=PID,
            revision=2,
            request_id="archive",
            data=ProjectData(title="Archived", question="Compare methods", status="archived"),
        ),
    )
    assert archived["data"]["status"] == "archived" and len(store.works("a")) == 1
    with pytest.raises(ValueError, match="read_only"):
        repo.source(
            "a",
            PID,
            ProjectSourceWrite(revision=3, request_id="archived-link", reference=ref(value)),
        )
    with pytest.raises(ValueError, match="create_only"):
        repo.write_project(
            "a",
            ProjectWrite(
                id=PID,
                revision=3,
                request_id="bad-update",
                data=project().data,
                initial_source=ref(value),
            ),
        )


def test_exact_evidence_unicode_and_unlink_do_not_move_shared_material(store):
    text = "α🧪 First. Repeated. Repeated."
    value = support.ingest(store, abstract=text)
    repo = WorkspaceContext(store)
    repo.write_project("a", project())
    start = text.rindex("Repeated.")
    write = ProjectSourceWrite(
        revision=1,
        request_id="evidence",
        role="evidence",
        reference=ref(value, f"abstract:{start}:{len(text)}"),
    )
    attached = repo.source("a", PID, write)
    evidence = attached["sources"][0]
    assert evidence["reference"]["quote"] == "Repeated."
    assert evidence["reference"]["start"] == start and evidence["reference"]["end"] == len(text)
    assert repo.source("a", PID, write) == attached
    assert (
        len(
            repo.source(
                "a",
                PID,
                write.model_copy(update={"request_id": "same-link-new-request", "revision": 2}),
            )["sources"]
        )
        == 1
    )
    removed = repo.unlink(
        "a", PID, ProjectUnlink(revision=3, request_id="unlink", link_id=evidence["id"])
    )
    assert removed["sources"][0]["status"] == "removed"
    assert store.works("a")[0]["abstract"] == text
    with pytest.raises(ValueError, match="source_unavailable"):
        repo.unlink(
            "a",
            PID,
            ProjectUnlink(revision=4, request_id="unknown-link", link_id="link-" + "0" * 32),
        )


@pytest.mark.parametrize(
    "anchor,extra,error",
    [
        ("abstract:0:0", {}, "nonempty"),
        ("abstract:0:9999", {}, "outside"),
        ("abstract:5:2", {}, "outside"),
        ("source", {}, "exact"),
        ("full_text:0:5", {}, "scope_anchor"),
        ("abstract:0:5", {"version_hash": "wrong"}, "version_hash"),
        ("abstract:0:5", {"material_hash": "wrong"}, "material_hash"),
        ("abstract:0:5", {"material_hash": ""}, "material_hash"),
        ("abstract:0:5", {"parser_revision": "wrong"}, "parser_revision"),
        ("abstract:0:5", {"parser_revision": ""}, "parser_revision"),
        ("abstract:0:5", {"source_scope": "excerpt"}, "scope_mismatch"),
        ("abstract:0:5", {"material_id": "mat-" + "0" * 32}, "unavailable"),
    ],
)
def test_evidence_rejects_wrong_or_missing_provenance(store, anchor, extra, error):
    value = support.ingest(store)
    repo = WorkspaceContext(store)
    repo.write_project("a", project())
    with pytest.raises(ValueError, match=error):
        repo.source(
            "a",
            PID,
            ProjectSourceWrite(
                revision=1, request_id="bad", role="evidence", reference=ref(value, anchor, **extra)
            ),
        )
    assert repo.project("a", PID)["revision"] == 1
    assert repo.project("a", PID)["sources"] == []


def test_metadata_reference_cannot_be_promoted_to_evidence_and_private_versions_refused(store):
    value = support.ingest(store, abstract="", access_state="metadata", visibility_owner="a")
    repo = WorkspaceContext(store)
    assert (
        repo.write_project("a", project(initial_source=ref(value, "abstract:0")))["sources"][0][
            "reference"
        ]["source_scope"]
        == "metadata"
    )
    with pytest.raises(ValueError, match="nonempty"):
        repo.source(
            "a",
            PID,
            ProjectSourceWrite(
                revision=1,
                request_id="false-evidence",
                role="evidence",
                reference=ref(value, "abstract:0"),
            ),
        )
    with pytest.raises(ValueError, match="source version"):
        repo.write_project("b", project(initial_source=ref(value)))
    with pytest.raises(ValueError, match="source version"):
        repo.source(
            "a",
            PID,
            ProjectSourceWrite(
                revision=1,
                request_id="wrong-version",
                reference=ref({**value, "version_id": "other:v2"}),
            ),
        )


def test_reader_metadata_anchor_is_a_source_reference_never_substantive_evidence(store):
    value = support.ingest(store, abstract="", access_state="metadata")
    repo = WorkspaceContext(store)
    result = repo.write_project(
        "a", project(initial_source=ref(value, "metadata:0", source_scope="metadata"))
    )
    bound = result["sources"][0]["reference"]
    assert bound["available"] and bound["source_scope"] == "metadata" and bound["quote"] == ""
    assert repo.project("a", PID)["sources"][0]["reference"] == bound
    for extra in ({}, {"material_id": "mat-" + "0" * 32}):
        with pytest.raises(ValueError, match="no_retained_passage"):
            repo.source(
                "a",
                PID,
                ProjectSourceWrite(
                    revision=1,
                    request_id="false-metadata-evidence",
                    role="evidence",
                    reference=ref(value, "metadata:0", **extra),
                ),
            )
    with pytest.raises(ValueError, match="scope_mismatch"):
        repo.source(
            "a",
            PID,
            ProjectSourceWrite(
                revision=1,
                request_id="false-metadata-scope",
                reference=ref(value, "metadata:0", source_scope="full_text"),
            ),
        )


def test_nonempty_metadata_material_and_failed_extraction_are_not_support_passages(store):
    value = support.ingest(store)
    repo = WorkspaceContext(store)
    repo.write_project("a", project())
    for scope, quality in (("metadata", "text_extracted"), ("abstract", "failed")):
        material = _build(
            work_id=value["work_id"],
            version_id=value["version_id"],
            source_hash="test",
            scope=scope,
            parser_revision="test",
            pages=["Nonempty but not qualified as retained support text"],
            page_count=1,
            quality=quality,
            warnings=[],
            complete=False,
        )
        with store.pool.connection() as conn:
            conn.execute(
                "INSERT INTO workspace_material VALUES (%s,%s,%s,%s,%s)",
                (
                    material.material_id,
                    material.version_id,
                    material.content_hash,
                    material.scope,
                    Jsonb(asdict(material)),
                ),
            )
        with pytest.raises(ValueError, match="nonempty_retained_passage|extraction_unavailable"):
            repo.source(
                "a",
                PID,
                ProjectSourceWrite(
                    revision=1,
                    request_id=f"not-evidence-{scope}",
                    role="evidence",
                    reference=ref(value, f"material:{material.material_id}:page:1:0:8"),
                ),
            )


def test_material_page_mapping_and_mutation_are_strict(store):
    value = support.ingest(store)
    material = _build(
        work_id=value["work_id"],
        version_id=value["version_id"],
        source_hash="sha256:public-bytes",
        scope="excerpt",
        parser_revision="test-v1",
        pages=["Page three: β🧪 repeated repeated"],
        page_count=9,
        page_numbers=[3],
        quality="text",
        warnings=[],
        complete=False,
    )
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_material VALUES (%s,%s,%s,%s,%s)",
            (
                material.material_id,
                material.version_id,
                material.content_hash,
                material.scope,
                Jsonb(asdict(material)),
            ),
        )
    repo = WorkspaceContext(store)
    repo.write_project("a", project())
    reference = ref(
        value,
        f"material:{material.material_id}:page:3:12:15",
        material_id=material.material_id,
        material_hash=material.content_hash,
        parser_revision=material.parser_revision,
        source_scope="excerpt",
    )
    result = repo.source(
        "a",
        PID,
        ProjectSourceWrite(revision=1, request_id="pdf", role="evidence", reference=reference),
    )
    assert result["sources"][0]["reference"]["quote"] == material.pages[0][12:15]
    with pytest.raises(ValueError, match="not acquired"):
        repo.source(
            "a",
            PID,
            ProjectSourceWrite(
                revision=2,
                request_id="wrong-page",
                role="evidence",
                reference=reference.model_copy(
                    update={"anchor": f"material:{material.material_id}:page:1:0:4"}
                ),
            ),
        )
    with pytest.raises(ValueError, match="identity_mismatch"):
        repo.source(
            "a",
            PID,
            ProjectSourceWrite(
                revision=2,
                request_id="wrong-id",
                role="evidence",
                reference=reference.model_copy(update={"material_id": "mat-" + "0" * 32}),
            ),
        )
    with store.pool.connection() as conn:
        mutated = {**asdict(material), "pages": ["X" * len(material.pages[0])]}
        conn.execute(
            "UPDATE workspace_material SET data=%s WHERE material_id=%s",
            (Jsonb(mutated), material.material_id),
        )
    pinned = repo.project("a", PID)["sources"][0]["reference"]
    assert not pinned["available"] and pinned["quote"] == ""
    with pytest.raises(ValueError, match="integrity"):
        repo.source(
            "a",
            PID,
            ProjectSourceWrite(
                revision=2, request_id="mutated", role="evidence", reference=reference
            ),
        )


@pytest.mark.parametrize("pdf", [False, True])
def test_recomputed_payload_cannot_replace_material_behind_existing_storage_identity(store, pdf):
    value = support.ingest(store)
    repo = WorkspaceContext(store)
    repo.write_project("a", project())
    if pdf:
        original = _build(
            work_id=value["work_id"],
            version_id=value["version_id"],
            source_hash="public-source",
            scope="excerpt",
            parser_revision="test",
            pages=["Original retained text"],
            page_count=1,
            quality="text_extracted",
            warnings=[],
            complete=False,
        )
        with store.pool.connection() as conn:
            conn.execute(
                "INSERT INTO workspace_material VALUES (%s,%s,%s,%s,%s)",
                (
                    original.material_id,
                    original.version_id,
                    original.content_hash,
                    original.scope,
                    Jsonb(asdict(original)),
                ),
            )
        anchor = f"material:{original.material_id}:page:1:0:8"
        target_id = original.material_id
        scope = "excerpt"
    else:
        with store.pool.connection() as conn:
            target_id = conn.execute(
                "SELECT material_id FROM workspace_material WHERE version_id=%s",
                (value["version_id"],),
            ).fetchone()[0]
        anchor, scope = "abstract:0:8", "abstract"
    replacement = _build(
        work_id=value["work_id"],
        version_id=value["version_id"],
        source_hash="different-public-bytes",
        scope=scope,
        parser_revision="test",
        pages=["Altered retained text at the same old identity"],
        page_count=1 if pdf else None,
        quality="text_extracted",
        warnings=[],
        complete=False,
    )
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_material SET data=%s WHERE material_id=%s",
            (Jsonb(asdict(replacement)), target_id),
        )
    with pytest.raises(ValueError, match="storage_identity"):
        repo.source(
            "a",
            PID,
            ProjectSourceWrite(
                revision=1, request_id="replaced", role="evidence", reference=ref(value, anchor)
            ),
        )


def test_links_and_artifacts_preserve_types_and_validate_owned_passages(store):
    value = support.ingest(store)
    note = store.write_entry("a", support.entry(value))
    repo = WorkspaceContext(store)
    repo.write_project("a", project())
    linked = repo.entry(
        "a",
        PID,
        ProjectEntryWrite(
            revision=1, request_id="link-note", entry_id=note["id"], entry_revision=1
        ),
    )
    assert linked["entries"][0]["entry"]["body"] == note["body"]
    attached = repo.source(
        "a",
        PID,
        ProjectSourceWrite(revision=2, request_id="e", role="evidence", reference=ref(value)),
    )
    link_id = attached["sources"][0]["id"]
    for index, kind in enumerate(
        ("observation", "assumption", "hypothesis", "comparison", "proposed-experiment")
    ):
        write = ProjectArtifactWrite(
            id="artifact-" + f"{index:032x}",
            revision=3 + index,
            request_id=f"artifact-{index}",
            data=ArtifactData(kind=kind, body="Manual test proposal", evidence_link_ids=[link_id]),
        )
        saved = repo.artifact("a", PID, write)
        assert saved["artifacts"][-1]["data"]["kind"] == kind
        assert saved["artifacts"][-1]["verification"] == "unverified"
    write = ProjectArtifactWrite(
        id="artifact-" + "f" * 32,
        revision=8,
        request_id="entry-artifact",
        data=ArtifactData(
            kind="assumption", entry=EntryReference(entry_id=note["id"], entry_revision=1)
        ),
    )
    assert repo.artifact("a", PID, write)["revision"] == 9
    with pytest.raises(ConflictError, match="authored"):
        repo.artifact(
            "a", PID, write.model_copy(update={"revision": 9, "request_id": "stale-artifact"})
        )
    with pytest.raises(ValueError, match="available_project_passage"):
        repo.artifact(
            "a",
            PID,
            write.model_copy(
                update={
                    "revision": 9,
                    "request_id": "bad-evidence",
                    "data": ArtifactData(
                        kind="hypothesis", body="Unverified", evidence_link_ids=["missing"]
                    ),
                }
            ),
        )


def test_thread_origin_and_exact_passage_resume_survive_repository_restart(store):
    value = support.ingest(store)
    repo = WorkspaceContext(store)
    repo.write_project("a", project())
    origin = ResumeContext(
        mode="research",
        project_id=PID,
        return_to=f"/workspace/projects?mode=research&project={PID}#evidence",
    )
    write = LearningThreadWrite(
        id=TID,
        revision=0,
        request_id="thread",
        data=LearningThreadData(
            title="Learn prerequisite",
            goal="Understand the method",
            origin=origin,
            source=ref(value),
        ),
    )
    first = repo.write_thread("a", write)
    assert first == repo.write_thread("a", write)
    restarted = WorkspaceContext(WorkspaceStore(store.pool))
    assert restarted.thread("a", TID)["source"]["quote"] == value["abstract"][:8]
    assert restarted.project("a", PID)["threads"][0]["data"]["origin"]["return_to"].endswith(
        "#evidence"
    )
    with pytest.raises(ContextNotFound):
        restarted.thread("b", TID)
    with pytest.raises(ConflictError):
        restarted.write_thread("a", write.model_copy(update={"request_id": "stale-thread"}))
    assert (
        restarted.write_thread(
            "a", write.model_copy(update={"revision": 1, "request_id": "edit-thread"})
        )["revision"]
        == 2
    )
    with pytest.raises(ValueError, match="identity_mismatch"):
        restarted.write_thread(
            "a",
            write.model_copy(
                update={
                    "revision": 2,
                    "request_id": "bad-return",
                    "data": write.data.model_copy(
                        update={
                            "origin": ResumeContext(
                                mode="learn",
                                project_id=PID,
                                return_to=f"/workspace/projects?mode=research&project={PID}",
                            )
                        }
                    ),
                }
            ),
        )


def test_atomic_contextual_entries_reading_and_legacy_revision_do_not_inherit_stale_context(store):
    value = support.ingest(store)
    repo = WorkspaceContext(store)
    repo.write_project("a", project())
    context = ResumeContext(
        mode="research",
        project_id=PID,
        return_to=f"/workspace/projects?mode=research&project={PID}",
    )
    write = ContextEntryWrite(
        id="new-note",
        revision=0,
        request_id="context-note",
        data=EntryData(
            work_id=value["work_id"],
            version_id=value["version_id"],
            kind="question",
            body="A question",
            anchor="abstract:2",
        ),
        context=context,
    )
    saved = repo.write_entry("a", write)
    assert saved == repo.write_entry("a", write)
    read = ContextReadingWrite(
        work_id=value["work_id"],
        revision=0,
        request_id="context-reading",
        data=ReadingData(version_id=value["version_id"], anchor="abstract:2", status="saved"),
        context=context,
    )
    assert repo.write_reading("a", read) == repo.write_reading("a", read)
    decorated = repo.decorate("a", store.works("a"))[0]
    assert decorated["entries"][0]["context"]["project_id"] == PID
    assert decorated["reading"]["context"]["project_id"] == PID
    with pytest.raises(ConflictError):
        repo.write_entry("a", write.model_copy(update={"request_id": "stale-note"}))
    with pytest.raises(ConflictError):
        repo.write_reading("a", read.model_copy(update={"request_id": "stale-read"}))
    store.write_entry(
        "a",
        support.EntryWrite(id="new-note", revision=1, request_id="legacy-edit", data=write.data),
    )
    assert repo.decorate("a", store.works("a"))[0]["entries"][0]["context"] is None
    assert repo.decorate("b", store.works("b"))[0]["entries"] == []
    with pytest.raises(ContextNotFound):
        repo.write_reading("b", read)
    with store.pool.connection() as conn:
        assert (
            conn.execute("SELECT count(*) FROM workspace_reading WHERE owner='b'").fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ResumeContext(return_to="https://example.org"),
        lambda: ResumeContext(return_to="//example.org/workspace/today"),
        lambda: ResumeContext(return_to="/workspace/today\\evil"),
        lambda: ResumeContext(return_to="/workspace/today\n"),
        lambda: ResumeContext(return_to="/workspace/items/evil"),
        lambda: ContextPreferencesData(learning_goals=[" "]),
        lambda: ProjectData(title=" ", question="Question"),
        lambda: ProjectData(title="Title", question="Question", next_actions=[" "]),
        lambda: ArtifactData(kind="hypothesis"),
        lambda: ArtifactData(
            kind="hypothesis", body="Both", entry=EntryReference(entry_id="n", entry_revision=1)
        ),
        lambda: LearningThreadData(title="T", goal="G", origin=ResumeContext()),
        lambda: LearningThreadData(title=" ", goal="G", origin=ResumeContext(project_id=PID)),
    ],
)
def test_context_shapes_and_return_routes_refuse_invalid_input(factory):
    with pytest.raises(ValidationError):
        factory()


def test_safe_return_preserves_whitelisted_context_and_drops_other_parameters():
    context = ResumeContext(
        return_to=f"/workspace/threads/{TID}?mode=learn&thread={TID}&other=ignored#abstract%3A2"
    )
    assert "other" not in context.return_to and context.return_to.endswith("#abstract%3A2")


def test_009_to_010_upgrade_preserves_preferences_notes_and_accounting(store):
    """Construct a pre010 database inside the disposable per-test schema."""
    value = support.ingest(store)
    note = store.write_entry("a", support.entry(value))
    before = store.profile("a")
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_qualification_trials(trial_id,owner,limits,baseline_digest) VALUES ('historical','trial-owner',%s,'stopped-digest')",
            (
                Jsonb(
                    {"messages": 9, "counts": 15, "estimated_usd": "0.109967", "approval": "closed"}
                ),
            ),
        )
        conn.execute(
            "INSERT INTO workspace_evaluation_programs(program_id,parent_trial_id,limits,baseline,authorization_digest) VALUES ('program','historical',%s,%s,'old-authorization')",
            (
                Jsonb({"ceiling_usd": 10}),
                Jsonb(
                    {
                        "failed": ["q02", "q03", "q04"],
                        "unrun": ["q05", "q06", "q07", "q08", "q09", "q10"],
                    }
                ),
            ),
        )
        original = conn.execute(
            "SELECT row_to_json(t) FROM workspace_qualification_trials t"
        ).fetchone()[0]
        program = conn.execute(
            "SELECT row_to_json(t) FROM workspace_evaluation_programs t"
        ).fetchone()[0]
        old_checksums = conn.execute(
            "SELECT revision,checksum FROM workspace_schema WHERE revision<'010' ORDER BY revision"
        ).fetchall()
        for table in (
            "workspace_mode_editions",
            "workspace_resume_context",
            "workspace_learning_threads",
            "workspace_project_artifacts",
            "workspace_project_entries",
            "workspace_project_sources",
            "workspace_projects",
            "workspace_context_preferences",
        ):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("DROP SEQUENCE workspace_context_activity")
        conn.execute("DELETE FROM workspace_schema WHERE revision='010_product_context'")
    restarted = WorkspaceStore(store.pool)
    restarted.migrate()
    restarted.migrate()
    with store.pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT revision,checksum FROM workspace_schema WHERE revision<'010' ORDER BY revision"
            ).fetchall()
            == old_checksums
        )
        assert (
            conn.execute("SELECT row_to_json(t) FROM workspace_qualification_trials t").fetchone()[
                0
            ]
            == original
        )
        assert (
            conn.execute("SELECT row_to_json(t) FROM workspace_evaluation_programs t").fetchone()[0]
            == program
        )
    assert restarted.profile("a") == before
    assert restarted.works("a")[0]["entries"][0]["body"] == note["body"]
    assert WorkspaceContext(restarted).index("a")["projects"] == []


def test_thread_context_and_linked_entry_must_agree(store):
    value = support.ingest(store)
    repo = WorkspaceContext(store)
    repo.write_project("a", project())
    original = ResumeContext(
        mode="research",
        project_id=PID,
        return_to=f"/workspace/projects?mode=research&project={PID}",
    )
    repo.write_thread(
        "a",
        LearningThreadWrite(
            id=TID,
            revision=0,
            request_id="t",
            data=LearningThreadData(
                title="Prerequisite", goal="Learn", origin=original, source=ref(value)
            ),
        ),
    )
    second_id = "project-" + "c" * 32
    repo.write_project(
        "a", ProjectWrite(id=second_id, revision=0, request_id="p2", data=project().data)
    )
    mismatched = ResumeContext(mode="learn", project_id=second_id, thread_id=TID)
    with pytest.raises(ValueError, match="thread_project_context"):
        repo.write_reading(
            "a",
            ContextReadingWrite(
                work_id=value["work_id"],
                revision=0,
                request_id="wrong-context",
                data=ReadingData(version_id=value["version_id"]),
                context=mismatched,
            ),
        )
    # An owned thread alone is a valid learning context without manufacturing a project.
    assert (
        repo.write_reading(
            "a",
            ContextReadingWrite(
                work_id=value["work_id"],
                revision=0,
                request_id="thread-reading",
                data=ReadingData(version_id=value["version_id"]),
                context=ResumeContext(mode="learn", thread_id=TID),
            ),
        )["context"]["thread_id"]
        == TID
    )
    wrong_thread_path = ResumeContext(
        mode="learn", thread_id=TID, return_to="/workspace/threads/thread-" + "f" * 32
    )
    with pytest.raises(ValueError, match="return_context_thread_identity"):
        repo.write_reading(
            "a",
            ContextReadingWrite(
                work_id=value["work_id"],
                revision=1,
                request_id="wrong-thread-path",
                data=ReadingData(version_id=value["version_id"]),
                context=wrong_thread_path,
            ),
        )
    other = support.ingest(store, work_id="other", version_id="other:v1")
    note = store.write_entry("a", support.entry(other))
    with pytest.raises(ValueError, match="entry_source_version"):
        repo.write_thread(
            "a",
            LearningThreadWrite(
                id="thread-" + "d" * 32,
                revision=0,
                request_id="wrong-thread-entry",
                data=LearningThreadData(
                    title="Prerequisite",
                    goal="Learn",
                    origin=original,
                    source=ref(value),
                    entry=EntryReference(entry_id=note["id"], entry_revision=1),
                ),
            ),
        )
