"""Postgres workspace repository. No in-memory fallback; private writes fail closed."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from src.workspace.schemas import (
    EntryWrite,
    ImportRequest,
    ProfileData,
    ProfileWrite,
    ReadingWrite,
)


class ConflictError(ValueError):
    """The record changed or a retry key was reused with a different payload."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _version_key(version: dict[str, Any]) -> tuple[int, str]:
    match = re.match(r"^v(\d+)", version["version_label"])
    return (int(match.group(1)) if match else 0, version["fetched_at"])


def initial_profile() -> dict[str, Any]:
    return ProfileData(
        topics=["ml:agents-and-tool-use", "ml:retrieval-and-memory", "ml:evaluation-and-responsible-ml", "ml:reasoning-and-inference-time-compute", "ml:ml-systems-and-efficiency", "ml:machine-learning-for-science", "study:22/control-systems", "ml:embodied-intelligence/model-based-reinforcement-learning", "ml:multimodal-and-perception/3d-perception", "ml:generative-models/controllable-generation", "ml:embodied-intelligence"],
        research_question="How can I build a personalized research agent that identifies useful developments, explains them against real sources, and turns them into small, reproducible experiments within a controlled compute budget?",
    ).model_dump()


class WorkspaceStore:
    """Uses the existing bounded pool; versioned SQL migrations have immutable checksums."""

    def __init__(self, pool: ConnectionPool):
        self.pool = pool
        self._ready = False
        self._lock = threading.Lock()

    def migrate(self) -> None:
        with self._lock:
            if self._ready:
                return
            with self.pool.connection() as conn:
                conn.execute("SELECT pg_advisory_xact_lock(801103)")
                conn.execute("CREATE TABLE IF NOT EXISTS workspace_schema (revision TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
                for path in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
                    sql = path.read_text()
                    checksum = hashlib.sha256(sql.encode()).hexdigest()
                    row = conn.execute("SELECT checksum FROM workspace_schema WHERE revision=%s", (path.stem,)).fetchone()
                    if row and row[0] != checksum:
                        raise RuntimeError("workspace migration checksum changed; restore original migration")
                    if not row:
                        conn.execute(sql)
                        conn.execute("INSERT INTO workspace_schema VALUES (%s,%s,now())", (path.stem, checksum))
            self._ready = True

    @staticmethod
    def _owner(owner: str) -> None:
        if not owner.strip():
            raise ValueError("a named authenticated owner is required")

    def _mutate(self, owner: str, request_id: str, body: Any, action: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        self._owner(owner)
        self.migrate()
        fingerprint = digest(body)
        with self.pool.connection() as conn:
            # Serialize private mutations per owner, including first insert races.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("workspace:" + owner,))
            row = conn.execute("SELECT digest,response FROM workspace_mutations WHERE owner=%s AND request_id=%s", (owner, request_id)).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise ConflictError("retry key was already used for different content")
                return dict(row[1])
            response = action(conn)
            conn.execute("INSERT INTO workspace_mutations VALUES (%s,%s,%s,%s)", (owner, request_id, fingerprint, Jsonb(response)))
            return response

    def profile(self, owner: str) -> dict[str, Any]:
        self._owner(owner)
        self.migrate()
        with self.pool.connection() as conn:
            row = conn.execute("SELECT revision,data FROM workspace_profiles WHERE owner=%s", (owner,)).fetchone()
        return {"revision": row[0], "data": row[1]} if row else {"revision": 0, "data": initial_profile()}

    def cutoff(self) -> str:
        """Database clock defines visibility; host/VM clock skew cannot move a cursor."""
        self.migrate()
        with self.pool.connection() as conn:
            row = conn.execute("SELECT clock_timestamp()").fetchone()
        stamp = row[0] if row else None
        if not isinstance(stamp, datetime):
            raise RuntimeError("database did not return an authoritative clock")
        return stamp.isoformat()

    def freeze_page(self, owner: str, query_hash: str, cutoff: str, items: list[dict[str, Any]]) -> str:
        """Freeze actual visible rows, including an in-flight ingestion's visibility.

        A timestamp predicate alone cannot freeze an uncommitted transaction.
        These short-lived private snapshots make subsequent pages exact.
        """
        self._owner(owner)
        self.migrate()
        if len(items) > 2000 or len(json.dumps(items).encode()) > 4 * 1024 * 1024:
            raise ValueError("result window is too large; narrow the filters")
        id_ = uuid.uuid4().hex
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM workspace_pages WHERE expires_at < clock_timestamp()")
            conn.execute("INSERT INTO workspace_pages(id,owner,query_hash,cutoff,items) VALUES (%s,%s,%s,%s,%s)", (id_, owner, query_hash, cutoff, Jsonb(items)))
        return id_

    def frozen_page(self, owner: str, id_: str, query_hash: str) -> tuple[str, list[dict[str, Any]]]:
        self._owner(owner)
        self.migrate()
        with self.pool.connection() as conn:
            row = conn.execute("SELECT cutoff,items FROM workspace_pages WHERE owner=%s AND id=%s AND query_hash=%s AND expires_at>=clock_timestamp()", (owner, id_, query_hash)).fetchone()
        if not row:
            raise ValueError("cursor expired or does not belong to these filters/account; reload results")
        return row[0], row[1]

    @staticmethod
    def _history(conn: Any, owner: str, entity: str, id_: str, revision: int, data: Any) -> None:
        conn.execute("INSERT INTO workspace_history(owner,entity,id,revision,data) VALUES (%s,%s,%s,%s,%s)", (owner, entity, id_, revision, Jsonb(data)))

    def write_profile(self, owner: str, write: ProfileWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            row = conn.execute("SELECT revision FROM workspace_profiles WHERE owner=%s", (owner,)).fetchone()
            current = row[0] if row else 0
            if current != write.revision:
                raise ConflictError("interests changed; reload before applying your edits")
            data = write.data.model_dump()
            revision = current + 1
            conn.execute("INSERT INTO workspace_profiles VALUES (%s,%s,%s) ON CONFLICT(owner) DO UPDATE SET revision=EXCLUDED.revision,data=EXCLUDED.data", (owner, revision, Jsonb(data)))
            self._history(conn, owner, "profile", owner, revision, data)
            return {"revision": revision, "data": data}
        return self._mutate(owner, write.request_id, write.model_dump(), action)

    @staticmethod
    def _version(conn: Any, work_id: str, version_id: str, owner: str) -> None:
        if not conn.execute("SELECT 1 FROM workspace_versions v JOIN workspace_works w USING(work_id) WHERE v.work_id=%s AND v.version_id=%s AND (w.visibility_owner IS NULL OR w.visibility_owner=%s)", (work_id, version_id, owner)).fetchone():
            raise ValueError("source version does not belong to this work")

    def write_reading(self, owner: str, write: ReadingWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            self._version(conn, write.work_id, write.data.version_id, owner)
            row = conn.execute("SELECT revision FROM workspace_reading WHERE owner=%s AND work_id=%s", (owner, write.work_id)).fetchone()
            current = row[0] if row else 0
            if current != write.revision:
                raise ConflictError("reading state changed; reload before retrying")
            data = write.data.model_dump()
            revision = current + 1
            conn.execute("INSERT INTO workspace_reading VALUES (%s,%s,%s,%s) ON CONFLICT(owner,work_id) DO UPDATE SET revision=EXCLUDED.revision,data=EXCLUDED.data", (owner, write.work_id, revision, Jsonb(data)))
            self._history(conn, owner, "reading", write.work_id, revision, data)
            return {**data, "revision": revision}
        return self._mutate(owner, write.request_id, write.model_dump(), action)

    def write_entry(self, owner: str, write: EntryWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            data = write.data.model_dump()
            self._version(conn, data["work_id"], data["version_id"], owner)
            row = conn.execute("SELECT revision FROM workspace_entries WHERE owner=%s AND id=%s", (owner, write.id)).fetchone()
            current = row[0] if row else 0
            if current != write.revision:
                raise ConflictError("note changed; keep your draft and reload the saved revision")
            revision = current + 1
            conn.execute("INSERT INTO workspace_entries VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(owner,id) DO UPDATE SET revision=EXCLUDED.revision,work_id=EXCLUDED.work_id,version_id=EXCLUDED.version_id,data=EXCLUDED.data", (owner, write.id, revision, data["work_id"], data["version_id"], Jsonb(data)))
            self._history(conn, owner, "entry", write.id, revision, data)
            return {"id": write.id, "revision": revision, **data}
        return self._mutate(owner, write.request_id, write.model_dump(), action)

    @staticmethod
    def _put_item(conn: Any, item: dict[str, Any]) -> None:
        from src.workspace.material import extract_abstract

        item = dict(item)
        previous = conn.execute("SELECT data->>'content_hash' FROM workspace_versions WHERE version_id=%s", (item["version_id"],)).fetchone()
        if previous and previous[0] != item.get("content_hash"):
            # Same provider version with revised metadata is another observed
            # material revision. Never replace text behind an existing note.
            item["version_id"] += ":metadata-" + digest(item.get("content_hash"))[:16]
            item["version_label"] += " (metadata revision)"
        conn.execute("INSERT INTO workspace_works(work_id,first_seen_at,visibility_owner) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (item["work_id"], item["first_seen_at"], item.get("visibility_owner")))
        conn.execute("INSERT INTO workspace_versions(version_id,work_id,source_id,data,observed_at) VALUES (%s,%s,%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING", (item["version_id"], item["work_id"], item["source_id"], Jsonb(item)))
        conn.execute("INSERT INTO workspace_observations VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (item["source_id"], item.get("source_record_id", item["work_id"]), item.get("content_hash", digest(item)), item["version_id"], item["fetched_at"]))
        material = extract_abstract(item)
        conn.execute("INSERT INTO workspace_material VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (material.material_id, item["version_id"], material.content_hash, material.scope, Jsonb(asdict(material))))

    def ingest(self, source_id: str, items: list[dict[str, Any]], receipt: dict[str, Any], validators: dict[str, str]) -> None:
        self.migrate()
        with self.pool.connection() as conn:
            # An entire bounded page + observation receipt + validators commits together.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("source:" + source_id,))
            for item in items:
                self._put_item(conn, item)
            successful = receipt["status"] in {"success", "not_modified", "ok", "empty"}
            checked_at = receipt.get("fetched_at", receipt.get("checked_at", utc_now()))
            conn.execute("INSERT INTO workspace_ingest_runs VALUES (%s,%s,%s,now())", (uuid.uuid4().hex, source_id, Jsonb(receipt)))
            conn.execute("INSERT INTO workspace_sources(source_id,status,last_success_at,validators,receipt) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(source_id) DO UPDATE SET status=EXCLUDED.status,last_success_at=COALESCE(EXCLUDED.last_success_at,workspace_sources.last_success_at),validators=CASE WHEN EXCLUDED.last_success_at IS NOT NULL THEN EXCLUDED.validators ELSE workspace_sources.validators END,receipt=EXCLUDED.receipt", (source_id, receipt["status"], checked_at if successful else None, Jsonb(validators if successful else {}), Jsonb(receipt)))

    def validators(self, source_id: str) -> dict[str, str]:
        self.migrate()
        with self.pool.connection() as conn:
            row = conn.execute("SELECT validators FROM workspace_sources WHERE source_id=%s", (source_id,)).fetchone()
        return dict(row[0]) if row else {}

    def sources(self) -> list[dict[str, Any]]:
        from src.workspace.intake import SOURCES
        self.migrate()
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT source_id,status,last_success_at,receipt FROM workspace_sources").fetchall()
        stored = {row[0]: dict(zip(("source_id", "status", "last_success_at", "receipt"), row, strict=True)) for row in rows}
        return [{"source_id": key, "name": source.name, **{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in stored.get(key, {}).items()}} for key, source in SOURCES.items()]

    def works(self, owner: str, *, as_of: str | None = None) -> list[dict[str, Any]]:
        self._owner(owner)
        self.migrate()
        cutoff = as_of or self.cutoff()
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT v.data,w.first_seen_at FROM workspace_versions v JOIN workspace_works w USING(work_id) WHERE v.observed_at <= %s AND (w.visibility_owner IS NULL OR w.visibility_owner=%s) ORDER BY v.observed_at DESC,v.version_id DESC", (cutoff, owner)).fetchall()
            reading_rows = conn.execute("SELECT DISTINCT ON (id) id,revision,data FROM workspace_history WHERE owner=%s AND entity='reading' AND created_at<=%s ORDER BY id,revision DESC", (owner, as_of)).fetchall() if as_of else conn.execute("SELECT work_id,revision,data FROM workspace_reading WHERE owner=%s", (owner,)).fetchall()
            readings = {r[0]: {**r[2], "revision": r[1]} for r in reading_rows}
            entries: dict[str, list[dict[str, Any]]] = {}
            for r in conn.execute("SELECT id,revision,work_id,data FROM workspace_entries WHERE owner=%s ORDER BY id", (owner,)).fetchall():
                entries.setdefault(r[2], []).append({**r[3], "id": r[0], "revision": r[1]})
        works: dict[str, dict[str, Any]] = {}
        for raw, first_seen in rows:
            item = dict(raw)
            work_id = item["work_id"]
            if work_id not in works:
                works[work_id] = {**item, "first_seen_at": first_seen.isoformat(), "versions": [], "reading": readings.get(work_id, {"revision": 0, "status": "unread", "anchor": "abstract:0", "version_id": item["version_id"]}), "entries": entries.get(work_id, [])}
            works[work_id]["versions"].append({**item, "source_scope": item.get("source_scope") or item.get("access_state", "metadata")})
        for work in works.values():
            versions = work["versions"]
            if all(re.match(r"^v\d+", version.get("version_label", "")) for version in versions):
                versions.sort(key=_version_key, reverse=True)
                latest = versions[0]
                work.update({key: value for key, value in latest.items() if key not in {"first_seen_at", "reading", "entries", "versions"}})
        return list(works.values())

    def import_preview(self, owner: str, request: ImportRequest, *, conn: Any = None) -> dict[str, Any]:
        self._owner(owner)
        self.migrate()
        if conn is None:
            with self.pool.connection() as connection:
                return self.import_preview(owner, request, conn=connection)
        record = request.record
        conflicts = []
        new = existing = 0
        for entry in record.entries:
            id_ = "preview:" + digest(entry.id)[:40]
            row = conn.execute("SELECT data FROM workspace_entries WHERE owner=%s AND id=%s", (owner, id_)).fetchone()
            if row:
                existing += 1
                work_id = "preview:" + digest([owner, entry.itemId])[:40]
                expected = {"body": entry.body, "kind": entry.kind, "work_id": work_id, "version_id": work_id + ":v1", "anchor": entry.anchor}
                if any(row[0].get(key) != value for key, value in expected.items()):
                    conflicts.append("Browser entry " + entry.id + " differs from the saved entry; neither will be overwritten")
            else:
                new += 1
        row = conn.execute("SELECT revision FROM workspace_profiles WHERE owner=%s", (owner,)).fetchone()
        revision = row[0] if row else 0
        if request.import_profile and revision != request.profile_revision:
            conflicts.append("Profile revision changed; preview again")
        return {"digest": digest(request.model_dump()), "entries_new": new, "entries_existing": existing, "conflicts": conflicts, "profile_will_change": request.import_profile, "original_retained": True}

    def import_apply(self, owner: str, request: ImportRequest, expected_digest: str) -> dict[str, Any]:
        fingerprint = digest(request.model_dump())
        if fingerprint != expected_digest:
            raise ConflictError("import changed since preview")
        def action(conn: Any) -> dict[str, Any]:
            preview = self.import_preview(owner, request, conn=conn)
            if preview["conflicts"]:
                raise ConflictError("import has conflicts; export both records and resolve explicitly")
            record = request.record
            item_ids = set(record.saved) | {entry.itemId for entry in record.entries}
            now = utc_now()
            for item_id in sorted(item_ids):
                work_id = "preview:" + digest([owner, item_id])[:40]
                item = {"work_id": work_id, "version_id": work_id + ":v1", "source_id": "preview-import", "source_record_id": item_id, "visibility_owner": owner, "title": "Imported fixture: " + item_id, "url": "", "abstract": "", "access_state": "metadata", "first_seen_at": now, "fetched_at": now, "version_label": "fixture-v1", "kind": "fixture", "content_hash": digest(item_id)}
                self._put_item(conn, item)
                if item_id in record.saved:
                    data = {"status": "saved", "version_id": item["version_id"], "anchor": record.anchors.get(item_id, "source")}
                    inserted = conn.execute("INSERT INTO workspace_reading VALUES (%s,%s,1,%s) ON CONFLICT DO NOTHING RETURNING work_id", (owner, work_id, Jsonb(data))).fetchone()
                    if inserted:
                        self._history(conn, owner, "reading", work_id, 1, data)
            for entry in record.entries:
                work_id = "preview:" + digest([owner, entry.itemId])[:40]
                data = {"work_id": work_id, "version_id": work_id + ":v1", "kind": entry.kind, "body": entry.body, "anchor": entry.anchor}
                entry_id = "preview:" + digest(entry.id)[:40]
                inserted = conn.execute("INSERT INTO workspace_entries VALUES (%s,%s,1,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id", (owner, entry_id, work_id, data["version_id"], Jsonb(data))).fetchone()
                if inserted:
                    self._history(conn, owner, "entry", entry_id, 1, data)
            if request.import_profile:
                data = ProfileData(topics=record.topics, custom_topics=record.customTopics, streams=record.streams, minutes=record.minutes, research_question=record.researchQuestion).model_dump()
                revision = request.profile_revision + 1
                conn.execute("INSERT INTO workspace_profiles VALUES (%s,%s,%s) ON CONFLICT(owner) DO UPDATE SET revision=EXCLUDED.revision,data=EXCLUDED.data", (owner, revision, Jsonb(data)))
                self._history(conn, owner, "profile", owner, revision, data)
            return preview
        return self._mutate(owner, "import:" + fingerprint, request.model_dump(), action)

    def edition(self, owner: str, work_ids: list[str], *, minutes: int, revision: int, persist: bool = True, work_versions: dict[str, str] | None = None, as_of: str | None = None) -> dict[str, Any]:
        self._owner(owner)
        self.migrate()
        data: dict[str, Any] = {"id": uuid.uuid4().hex, "created_at": as_of or self.cutoff(), "profile_revision": revision, "minutes": minutes, "work_ids": work_ids, "coverage": self.sources()}
        data["work_versions"] = work_versions if work_versions is not None else {item["work_id"]: item["version_id"] for item in self.works(owner, as_of=data["created_at"]) if item["work_id"] in work_ids}
        data["status"] = "ready" if all(s.get("status") in {"success", "not_modified", "ok", "empty"} for s in data["coverage"]) else "ready_partial"
        if persist:
            with self.pool.connection() as conn:
                conn.execute("INSERT INTO workspace_editions(owner,id,data) VALUES (%s,%s,%s)", (owner, data["id"], Jsonb(data)))
        return data

    def editions(self, owner: str) -> list[dict[str, Any]]:
        self._owner(owner)
        self.migrate()
        with self.pool.connection() as conn:
            return [row[0] for row in conn.execute("SELECT data FROM workspace_editions WHERE owner=%s ORDER BY created_at DESC,id DESC LIMIT 20", (owner,)).fetchall()]
