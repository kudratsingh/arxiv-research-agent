"""Transactional manual projects, shared-record links and exact reading context.

No imports from model, qualification or job runners: a project is authored
organization, never authority to generate, acquire or execute anything.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from psycopg.types.json import Jsonb

from src.workspace.context_schemas import (
    ContextEntryWrite,
    ContextPreferencesData,
    ContextPreferencesWrite,
    ContextReadingWrite,
    LearningThreadWrite,
    ProjectArtifactWrite,
    ProjectEntryWrite,
    ProjectSourceWrite,
    ProjectUnlink,
    ProjectWrite,
    ResumeContext,
    SourceReference,
)
from src.workspace.material import _build
from src.workspace.store import ConflictError, WorkspaceStore, digest


class ContextNotFound(ValueError):
    """Unknown and unowned records deliberately share one public error."""


class WorkspaceContext:
    def __init__(self, store: WorkspaceStore):
        self.store = store

    @staticmethod
    def _project(conn: Any, owner: str, project_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT revision,data,created_at,updated_at,activity_sequence FROM workspace_projects WHERE owner=%s AND id=%s",
            (owner, project_id),
        ).fetchone()
        if not row:
            raise ContextNotFound("project_unavailable")
        return {
            "id": project_id,
            "revision": row[0],
            "data": row[1],
            "created_at": row[2].isoformat(),
            "updated_at": row[3].isoformat(),
            "activity_sequence": row[4],
        }

    @staticmethod
    def _thread(conn: Any, owner: str, thread_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT revision,data,bound_source,created_at,updated_at,activity_sequence FROM workspace_learning_threads WHERE owner=%s AND id=%s",
            (owner, thread_id),
        ).fetchone()
        if not row:
            raise ContextNotFound("learning_thread_unavailable")
        return {
            "id": thread_id,
            "revision": row[0],
            "data": row[1],
            "source": row[2],
            "created_at": row[3].isoformat(),
            "updated_at": row[4].isoformat(),
            "activity_sequence": row[5],
        }

    @classmethod
    def _check_context(cls, conn: Any, owner: str, context: ResumeContext) -> None:
        if context.project_id:
            cls._project(conn, owner, context.project_id)
        if context.thread_id:
            selected_thread = cls._thread(conn, owner, context.thread_id)
            if (
                context.project_id
                and selected_thread["data"]["origin"]["project_id"] != context.project_id
            ):
                raise ValueError("learning_thread_project_context_mismatch")
        params = parse_qs(urlsplit(context.return_to).query)
        return_path = urlsplit(context.return_to).path
        if (
            return_path.startswith("/workspace/threads/")
            and return_path.rsplit("/", 1)[1] != context.thread_id
        ):
            raise ValueError("return_context_thread_identity_mismatch")
        for key, expected in (
            ("mode", context.mode),
            ("project", context.project_id),
            ("thread", context.thread_id),
        ):
            if key in params and (len(params[key]) != 1 or params[key][0] != expected):
                raise ValueError("return_context_identity_mismatch")

    @staticmethod
    def _entry(conn: Any, owner: str, entry_id: str, revision: int) -> dict[str, Any]:
        row = conn.execute(
            "SELECT h.data,e.revision FROM workspace_history h JOIN workspace_entries e ON e.owner=h.owner AND e.id=h.id "
            "JOIN workspace_works w ON w.work_id=h.data->>'work_id' WHERE h.owner=%s AND h.entity='entry' AND h.id=%s AND h.revision=%s "
            "AND (w.visibility_owner IS NULL OR w.visibility_owner=%s)",
            (owner, entry_id, revision, owner),
        ).fetchone()
        if not row:
            raise ValueError("owned_entry_revision_unavailable")
        return {
            "entry_id": entry_id,
            "entry_revision": revision,
            "entry": {"id": entry_id, "revision": revision, **row[0]},
            "current_revision": row[1],
            "available": True,
        }

    @staticmethod
    def _bound(
        conn: Any, owner: str, reference: SourceReference, *, evidence: bool = False
    ) -> dict[str, Any]:
        WorkspaceStore._version(conn, reference.work_id, reference.version_id, owner)
        row = conn.execute(
            "SELECT data FROM workspace_versions WHERE work_id=%s AND version_id=%s",
            (reference.work_id, reference.version_id),
        ).fetchone()
        version = row[0]
        if reference.version_hash is not None and reference.version_hash != version.get(
            "content_hash", ""
        ):
            raise ValueError("source_version_hash_mismatch")
        bound = {
            **reference.model_dump(),
            "version_hash": version.get("content_hash", ""),
            "title": version["title"],
            "source_url": version["url"],
            "page": None,
            "start": None,
            "end": None,
            "quote": "",
            "offset_basis": "page-local Unicode code points; end exclusive",
            "available": True,
            "unavailable_reason": None,
        }
        if reference.anchor == "metadata:0":
            if evidence or any(
                value is not None
                for value in (
                    reference.material_id,
                    reference.material_hash,
                    reference.parser_revision,
                )
            ):
                raise ValueError("metadata_reference_has_no_retained_passage")
            if reference.source_scope not in {None, "metadata"}:
                raise ValueError("source_scope_mismatch")
            return {**bound, "source_scope": "metadata", "start": 0, "end": 0}
        material = None
        if reference.anchor.startswith("material:"):
            WorkspaceStore._anchor(
                conn, owner, reference.work_id, reference.version_id, reference.anchor
            )
            match = re.fullmatch(
                r"material:(mat-[a-f0-9]{32}):page:([1-9]\d{0,5}):(\d{1,8}):(\d{1,8})",
                reference.anchor,
            )
            assert match is not None  # _anchor validates the complete grammar
            material_id, page_raw, start_raw, end_raw = match.groups()
            if reference.material_id is not None and material_id != reference.material_id:
                raise ValueError("material_anchor_identity_mismatch")
            stored = conn.execute(
                "SELECT data,material_id,content_hash,source_scope FROM workspace_material WHERE material_id=%s AND version_id=%s",
                (material_id, reference.version_id),
            ).fetchone()
            material = stored[0]
            if not isinstance(material, dict) or (
                material.get("material_id"),
                material.get("content_hash"),
                material.get("scope"),
            ) != tuple(stored[1:]):
                raise ValueError("retained_material_storage_identity_mismatch")
            page, start, end = int(page_raw), int(start_raw), int(end_raw)
            mapping = material.get("page_numbers")
            index = mapping.index(page) if mapping is not None else page - 1
            text = material["pages"][index]
            bound.update(page=page)
        else:
            match = re.fullmatch(
                r"(abstract|excerpt|full_text):(\d{1,8})(?::(\d{1,8}))?", reference.anchor
            )
            if match is None:
                raise ValueError("a source link needs an exact retained-text anchor")
            scope, start_raw, end_raw = match.groups()
            start = int(start_raw)
            end = int(end_raw) if end_raw is not None else start
            # Plain source anchors address the exact immutable observation text.
            actual_scope = "excerpt" if version.get("access_state") == "excerpt" else "abstract"
            text = version.get("abstract", "")
            if scope != actual_scope and (evidence or text):
                raise ValueError("source_scope_anchor_mismatch")
            row = conn.execute(
                "SELECT data,material_id,content_hash,source_scope FROM workspace_material WHERE version_id=%s AND source_scope=%s AND data->>'page_count' IS NULL AND (%s::text IS NULL OR material_id=%s) ORDER BY material_id",
                (reference.version_id, actual_scope, reference.material_id, reference.material_id),
            ).fetchone()
            material = row[0] if row else None
            if row and (
                not isinstance(material, dict)
                or (
                    material.get("material_id"),
                    material.get("content_hash"),
                    material.get("scope"),
                )
                != tuple(row[1:])
            ):
                raise ValueError("retained_material_storage_identity_mismatch")
            if reference.material_id and (
                material is None or material["material_id"] != reference.material_id
            ):
                raise ValueError("retained_material_unavailable")
            bound["source_scope"] = actual_scope if text else "metadata"
        if not 0 <= start <= end <= len(text):
            raise ValueError("source_anchor_outside_retained_text")
        if material:
            rebuilt = _build(
                work_id=material["work_id"],
                version_id=material["version_id"],
                source_hash=material["source_hash"],
                scope=material["scope"],
                parser_revision=material["parser_revision"],
                pages=material["pages"],
                page_count=material["page_count"],
                quality=material["quality"],
                warnings=material["warnings"],
                complete=material["complete"],
                page_numbers=material.get("page_numbers"),
            )
            if (
                rebuilt.material_id != material["material_id"]
                or rebuilt.content_hash != material["content_hash"]
            ):
                raise ValueError("retained_material_integrity_failed")
            if (
                material["work_id"] != reference.work_id
                or material["version_id"] != reference.version_id
            ):
                raise ValueError("retained_material_version_mismatch")
            if (
                reference.material_hash is not None
                and reference.material_hash != material["content_hash"]
            ):
                raise ValueError("retained_material_hash_mismatch")
            if (
                reference.parser_revision is not None
                and reference.parser_revision != material["parser_revision"]
            ):
                raise ValueError("retained_parser_revision_mismatch")
            bound.update(
                material_id=material["material_id"],
                material_hash=material["content_hash"],
                parser_revision=material["parser_revision"],
                source_scope=material["scope"],
            )
            if reference.anchor.startswith("material:") and material.get("quality") in {
                "empty",
                "failed",
            }:
                raise ValueError("retained_material_extraction_unavailable")
            if not reference.anchor.startswith("material:") and material["pages"] != [text]:
                raise ValueError("retained_material_observation_mismatch")
        elif reference.material_hash is not None or reference.parser_revision is not None:
            raise ValueError("retained_material_unavailable")
        if reference.source_scope and reference.source_scope != bound["source_scope"]:
            raise ValueError("source_scope_mismatch")
        if evidence and (
            not material
            or material["scope"] == "metadata"
            or material["quality"] in {"empty", "failed"}
            or not text[start:end].strip()
        ):
            raise ValueError("evidence_requires_nonempty_retained_passage")
        bound.update(start=start, end=end, quote=text[start:end])
        return bound

    @classmethod
    def _available(
        cls, conn: Any, owner: str, reference: dict[str, Any], *, evidence: bool = False
    ) -> dict[str, Any]:
        try:
            source = SourceReference.model_validate(
                {key: reference.get(key) for key in SourceReference.model_fields}
            )
            current = cls._bound(conn, owner, source, evidence=evidence)
            if current["quote"] != reference["quote"]:
                raise ValueError("retained_passage_changed")
            return current
        except ValueError:
            # Never leak a no-longer-visible private quote or substitute latest.
            return {
                **reference,
                "quote": "",
                "title": "Unavailable pinned source",
                "source_url": "",
                "available": False,
                "unavailable_reason": "pinned_source_or_passage_unavailable",
            }

    @classmethod
    def _detail(cls, conn: Any, owner: str, project_id: str) -> dict[str, Any]:
        project = cls._project(conn, owner, project_id)
        sources = []
        for row in conn.execute(
            "SELECT data FROM workspace_project_sources WHERE owner=%s AND project_id=%s ORDER BY id",
            (owner, project_id),
        ).fetchall():
            link = row[0]
            sources.append(
                {
                    **link,
                    "reference": cls._available(
                        conn, owner, link["reference"], evidence=link["role"] == "evidence"
                    ),
                }
            )
        entries = []
        for entry_id, revision in conn.execute(
            "SELECT entry_id,entry_revision FROM workspace_project_entries WHERE owner=%s AND project_id=%s ORDER BY entry_id,entry_revision",
            (owner, project_id),
        ).fetchall():
            try:
                entries.append(cls._entry(conn, owner, entry_id, revision))
            except ValueError:
                entries.append(
                    {
                        "entry_id": entry_id,
                        "entry_revision": revision,
                        "entry": None,
                        "current_revision": None,
                        "available": False,
                    }
                )
        artifacts = [
            {
                "id": row[0],
                "revision": row[1],
                "data": row[2],
                "authorship": "manual",
                "verification": "unverified",
            }
            for row in conn.execute(
                "SELECT id,revision,data FROM workspace_project_artifacts WHERE owner=%s AND project_id=%s ORDER BY id",
                (owner, project_id),
            ).fetchall()
        ]
        threads = [
            cls._thread_visible(conn, owner, row[0])
            for row in conn.execute(
                "SELECT id FROM workspace_learning_threads WHERE owner=%s AND project_id=%s ORDER BY activity_sequence DESC",
                (owner, project_id),
            ).fetchall()
        ]
        return {
            **project,
            "sources": sources,
            "entries": entries,
            "artifacts": artifacts,
            "threads": threads,
        }

    @classmethod
    def _thread_visible(cls, conn: Any, owner: str, thread_id: str) -> dict[str, Any]:
        thread = cls._thread(conn, owner, thread_id)
        if thread["source"]:
            thread["source"] = cls._available(conn, owner, thread["source"])
        return thread

    def project(self, owner: str, project_id: str) -> dict[str, Any]:
        self.store._owner(owner)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            return self._detail(conn, owner, project_id)

    def thread(self, owner: str, thread_id: str) -> dict[str, Any]:
        self.store._owner(owner)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            return self._thread_visible(conn, owner, thread_id)

    def index(self, owner: str) -> dict[str, Any]:
        self.store._owner(owner)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            row = conn.execute(
                "SELECT revision,data FROM workspace_context_preferences WHERE owner=%s", (owner,)
            ).fetchone()
            preferences = (
                {"revision": row[0], "data": row[1]}
                if row
                else {"revision": 0, "data": ContextPreferencesData().model_dump()}
            )
            projects = [
                self._project(conn, owner, row[0])
                for row in conn.execute(
                    "SELECT id FROM workspace_projects WHERE owner=%s ORDER BY activity_sequence DESC",
                    (owner,),
                ).fetchall()
            ]
            threads = [
                self._thread_visible(conn, owner, row[0])
                for row in conn.execute(
                    "SELECT id FROM workspace_learning_threads WHERE owner=%s ORDER BY activity_sequence DESC",
                    (owner,),
                ).fetchall()
            ]
        return {
            "principal_key_id": owner,
            "preferences": preferences,
            "projects": projects,
            "threads": threads,
        }

    def preferences(self, owner: str, write: ContextPreferencesWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            row = conn.execute(
                "SELECT revision FROM workspace_context_preferences WHERE owner=%s", (owner,)
            ).fetchone()
            if (row[0] if row else 0) != write.revision:
                raise ConflictError("learning preferences changed; preserve your draft and reload")
            revision, data = write.revision + 1, write.data.model_dump()
            conn.execute(
                "INSERT INTO workspace_context_preferences VALUES (%s,%s,%s) ON CONFLICT(owner) DO UPDATE SET revision=EXCLUDED.revision,data=EXCLUDED.data",
                (owner, revision, Jsonb(data)),
            )
            self.store._history(conn, owner, "context_preferences", owner, revision, data)
            return {"revision": revision, "data": data}

        return self.store._mutate(
            owner,
            write.request_id,
            {"operation": "context.preferences", **write.model_dump()},
            action,
        )

    @classmethod
    def _guard(cls, conn: Any, owner: str, project_id: str, revision: int) -> dict[str, Any]:
        project = cls._project(conn, owner, project_id)
        if project["revision"] != revision:
            raise ConflictError("project changed; preserve your draft and reload")
        if project["data"]["status"] == "archived":
            raise ValueError("archived_project_is_read_only")
        return project

    @staticmethod
    def _bump(conn: Any, owner: str, project_id: str) -> None:
        conn.execute(
            "UPDATE workspace_projects SET revision=revision+1,updated_at=clock_timestamp(),activity_sequence=nextval('workspace_context_activity') WHERE owner=%s AND id=%s",
            (owner, project_id),
        )

    @classmethod
    def _link_source(
        cls,
        conn: Any,
        owner: str,
        project_id: str,
        reference: SourceReference,
        role: str,
        label: str = "",
    ) -> None:
        bound = cls._bound(conn, owner, reference, evidence=role == "evidence")
        id_ = (
            "link-" + digest([role, reference.work_id, reference.version_id, reference.anchor])[:32]
        )
        data = {"id": id_, "role": role, "status": "active", "label": label, "reference": bound}
        conn.execute(
            "INSERT INTO workspace_project_sources VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(owner,project_id,id) DO UPDATE SET data=EXCLUDED.data",
            (owner, project_id, id_, reference.work_id, reference.version_id, Jsonb(data)),
        )

    @classmethod
    def _link_entry(
        cls, conn: Any, owner: str, project_id: str, entry_id: str, revision: int
    ) -> None:
        cls._entry(conn, owner, entry_id, revision)
        conn.execute(
            "INSERT INTO workspace_project_entries VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (owner, project_id, entry_id, revision),
        )

    def write_project(self, owner: str, write: ProjectWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            row = conn.execute(
                "SELECT revision FROM workspace_projects WHERE owner=%s AND id=%s",
                (owner, write.id),
            ).fetchone()
            if (row[0] if row else 0) != write.revision:
                raise ConflictError("project changed; preserve your draft and reload")
            if row and (write.initial_source or write.origin_entry):
                raise ValueError("initial_source_and_entry_are_create_only")
            conn.execute(
                "INSERT INTO workspace_projects(owner,id,revision,data) VALUES (%s,%s,1,%s) ON CONFLICT(owner,id) DO UPDATE SET revision=workspace_projects.revision+1,data=EXCLUDED.data,updated_at=clock_timestamp(),activity_sequence=nextval('workspace_context_activity')",
                (owner, write.id, Jsonb(write.data.model_dump())),
            )
            if write.initial_source:
                self._link_source(conn, owner, write.id, write.initial_source, "source")
            if write.origin_entry:
                self._link_entry(
                    conn,
                    owner,
                    write.id,
                    write.origin_entry.entry_id,
                    write.origin_entry.entry_revision,
                )
            project = self._detail(conn, owner, write.id)
            self.store._history(
                conn, owner, "project", write.id, project["revision"], write.data.model_dump()
            )
            return project

        return self.store._mutate(
            owner, write.request_id, {"operation": "context.project", **write.model_dump()}, action
        )

    def source(self, owner: str, project_id: str, write: ProjectSourceWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            self._guard(conn, owner, project_id, write.revision)
            self._link_source(conn, owner, project_id, write.reference, write.role, write.label)
            self._bump(conn, owner, project_id)
            return self._detail(conn, owner, project_id)

        return self.store._mutate(
            owner,
            write.request_id,
            {"operation": "context.source", "project_id": project_id, **write.model_dump()},
            action,
        )

    def unlink(self, owner: str, project_id: str, write: ProjectUnlink) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            self._guard(conn, owner, project_id, write.revision)
            row = conn.execute(
                "SELECT data FROM workspace_project_sources WHERE owner=%s AND project_id=%s AND id=%s",
                (owner, project_id, write.link_id),
            ).fetchone()
            if not row:
                raise ValueError("project_source_unavailable")
            conn.execute(
                "UPDATE workspace_project_sources SET data=%s WHERE owner=%s AND project_id=%s AND id=%s",
                (Jsonb({**row[0], "status": "removed"}), owner, project_id, write.link_id),
            )
            self._bump(conn, owner, project_id)
            return self._detail(conn, owner, project_id)

        return self.store._mutate(
            owner,
            write.request_id,
            {"operation": "context.unlink", "project_id": project_id, **write.model_dump()},
            action,
        )

    def entry(self, owner: str, project_id: str, write: ProjectEntryWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            self._guard(conn, owner, project_id, write.revision)
            self._link_entry(conn, owner, project_id, write.entry_id, write.entry_revision)
            self._bump(conn, owner, project_id)
            return self._detail(conn, owner, project_id)

        return self.store._mutate(
            owner,
            write.request_id,
            {"operation": "context.entry_link", "project_id": project_id, **write.model_dump()},
            action,
        )

    def artifact(self, owner: str, project_id: str, write: ProjectArtifactWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            self._guard(conn, owner, project_id, write.revision)
            if write.data.entry:
                self._entry(conn, owner, write.data.entry.entry_id, write.data.entry.entry_revision)
            for link_id in write.data.evidence_link_ids:
                row = conn.execute(
                    "SELECT data FROM workspace_project_sources WHERE owner=%s AND project_id=%s AND id=%s",
                    (owner, project_id, link_id),
                ).fetchone()
                if (
                    not row
                    or row[0]["role"] != "evidence"
                    or row[0]["status"] != "active"
                    or not self._available(conn, owner, row[0]["reference"], evidence=True)[
                        "available"
                    ]
                ):
                    raise ValueError("artifact_evidence_must_be_an_available_project_passage")
            row = conn.execute(
                "SELECT revision FROM workspace_project_artifacts WHERE owner=%s AND project_id=%s AND id=%s",
                (owner, project_id, write.id),
            ).fetchone()
            if (row[0] if row else 0) != write.artifact_revision:
                raise ConflictError("authored record changed; preserve your draft and reload")
            conn.execute(
                "INSERT INTO workspace_project_artifacts VALUES (%s,%s,%s,%s,%s) ON CONFLICT(owner,project_id,id) DO UPDATE SET revision=EXCLUDED.revision,data=EXCLUDED.data",
                (
                    owner,
                    project_id,
                    write.id,
                    write.artifact_revision + 1,
                    Jsonb(write.data.model_dump()),
                ),
            )
            self._bump(conn, owner, project_id)
            return self._detail(conn, owner, project_id)

        return self.store._mutate(
            owner,
            write.request_id,
            {"operation": "context.artifact", "project_id": project_id, **write.model_dump()},
            action,
        )

    def write_thread(self, owner: str, write: LearningThreadWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            self._check_context(conn, owner, write.data.origin)
            bound = self._bound(conn, owner, write.data.source) if write.data.source else None
            if write.data.entry:
                entry = self._entry(
                    conn, owner, write.data.entry.entry_id, write.data.entry.entry_revision
                )["entry"]
                if bound and (
                    entry["work_id"] != bound["work_id"]
                    or entry["version_id"] != bound["version_id"]
                ):
                    raise ValueError("thread_entry_source_version_mismatch")
            row = conn.execute(
                "SELECT revision FROM workspace_learning_threads WHERE owner=%s AND id=%s",
                (owner, write.id),
            ).fetchone()
            if (row[0] if row else 0) != write.revision:
                raise ConflictError("learning thread changed; preserve your draft and reload")
            conn.execute(
                "INSERT INTO workspace_learning_threads(owner,id,revision,project_id,data,bound_source) VALUES (%s,%s,1,%s,%s,%s) ON CONFLICT(owner,id) DO UPDATE SET revision=workspace_learning_threads.revision+1,project_id=EXCLUDED.project_id,data=EXCLUDED.data,bound_source=EXCLUDED.bound_source,updated_at=clock_timestamp(),activity_sequence=nextval('workspace_context_activity')",
                (
                    owner,
                    write.id,
                    write.data.origin.project_id,
                    Jsonb(write.data.model_dump()),
                    Jsonb(bound) if bound else None,
                ),
            )
            thread = self._thread_visible(conn, owner, write.id)
            self.store._history(
                conn,
                owner,
                "learning_thread",
                write.id,
                thread["revision"],
                write.data.model_dump(),
            )
            return thread

        return self.store._mutate(
            owner, write.request_id, {"operation": "context.thread", **write.model_dump()}, action
        )

    def write_entry(self, owner: str, write: ContextEntryWrite) -> dict[str, Any]:
        """The legacy shared record and resume association commit in ONE transaction."""

        def action(conn: Any) -> dict[str, Any]:
            self._check_context(conn, owner, write.context)
            data = write.data.model_dump()
            self.store._version(conn, data["work_id"], data["version_id"], owner)
            self.store._anchor(conn, owner, data["work_id"], data["version_id"], data["anchor"])
            row = conn.execute(
                "SELECT revision FROM workspace_entries WHERE owner=%s AND id=%s", (owner, write.id)
            ).fetchone()
            if (row[0] if row else 0) != write.revision:
                raise ConflictError("note changed; preserve your draft and reload")
            revision = write.revision + 1
            conn.execute(
                "INSERT INTO workspace_entries VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(owner,id) DO UPDATE SET revision=EXCLUDED.revision,work_id=EXCLUDED.work_id,version_id=EXCLUDED.version_id,data=EXCLUDED.data",
                (owner, write.id, revision, data["work_id"], data["version_id"], Jsonb(data)),
            )
            activity = self.store._history(conn, owner, "entry", write.id, revision, data)
            context = write.context.model_dump()
            conn.execute(
                "INSERT INTO workspace_resume_context VALUES (%s,'entry',%s,%s,%s)",
                (owner, write.id, revision, Jsonb(context)),
            )
            return {"id": write.id, "revision": revision, **data, **activity, "context": context}

        return self.store._mutate(
            owner, write.request_id, {"operation": "context.entry", **write.model_dump()}, action
        )

    def write_reading(self, owner: str, write: ContextReadingWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            self._check_context(conn, owner, write.context)
            self.store._version(conn, write.work_id, write.data.version_id, owner)
            self.store._anchor(conn, owner, write.work_id, write.data.version_id, write.data.anchor)
            row = conn.execute(
                "SELECT revision FROM workspace_reading WHERE owner=%s AND work_id=%s",
                (owner, write.work_id),
            ).fetchone()
            if (row[0] if row else 0) != write.revision:
                raise ConflictError("reading state changed; preserve your draft and reload")
            revision, data = write.revision + 1, write.data.model_dump()
            conn.execute(
                "INSERT INTO workspace_reading VALUES (%s,%s,%s,%s) ON CONFLICT(owner,work_id) DO UPDATE SET revision=EXCLUDED.revision,data=EXCLUDED.data",
                (owner, write.work_id, revision, Jsonb(data)),
            )
            activity = self.store._history(conn, owner, "reading", write.work_id, revision, data)
            context = write.context.model_dump()
            conn.execute(
                "INSERT INTO workspace_resume_context VALUES (%s,'reading',%s,%s,%s)",
                (owner, write.work_id, revision, Jsonb(context)),
            )
            return {**data, "revision": revision, **activity, "context": context}

        return self.store._mutate(
            owner, write.request_id, {"operation": "context.reading", **write.model_dump()}, action
        )

    def decorate(self, owner: str, works: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.store._owner(owner)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            contexts = {
                (row[0], row[1], row[2]): row[3]
                for row in conn.execute(
                    "SELECT entity,id,revision,data FROM workspace_resume_context WHERE owner=%s",
                    (owner,),
                ).fetchall()
            }
        return [
            {
                **work,
                "entries": [
                    {**entry, "context": contexts.get(("entry", entry["id"], entry["revision"]))}
                    for entry in work["entries"]
                ],
                "reading": {
                    **work["reading"],
                    "context": contexts.get(
                        ("reading", work["work_id"], work["reading"]["revision"])
                    ),
                },
            }
            for work in works
        ]
