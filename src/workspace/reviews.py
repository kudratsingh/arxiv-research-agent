"""Finite real-candidate packets and explicit personal usefulness judgments."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from src.workspace.intake import SOURCES
from src.workspace.ranking import POLICY_VERSION, rank_items
from src.workspace.schemas import (
    FeedbackWrite,
    ReviewCandidate,
    ReviewPacket,
    ReviewPrepare,
    SourceStatus,
    UsefulnessFeedback,
    WorkItem,
)
from src.workspace.store import ConflictError, WorkspaceStore


class WorkspaceReviews:
    def __init__(self, store: WorkspaceStore):
        self.store = store

    def get(self, owner: str, packet_id: str | None = None) -> dict[str, Any] | None:
        self.store._owner(owner)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            row = conn.execute(
                "SELECT data FROM workspace_review_packets WHERE owner=%s AND (%s::text IS NULL OR id=%s) ORDER BY created_at DESC,id DESC LIMIT 1",
                (owner, packet_id, packet_id),
            ).fetchone()
            if row is None:
                return None
            data = dict(row[0])
            feedback = {work: {**value, "revision": revision, "updated_at": updated.isoformat()} for work, value, revision, updated in conn.execute(
                "SELECT work_id,data,revision,updated_at FROM workspace_usefulness_feedback WHERE owner=%s AND packet_id=%s",
                (owner, data["id"]),
            ).fetchall()}
        for candidate in data["items"]:
            candidate["feedback"] = feedback.get(candidate["work"]["work_id"], UsefulnessFeedback().model_dump())
        data["labelled_count"] = sum(item["feedback"]["label"] is not None for item in data["items"])
        return ReviewPacket.model_validate(data).model_dump()

    def index(self, owner: str, packet_id: str | None = None) -> dict[str, Any]:
        packet = self.get(owner, packet_id)
        if packet_id and packet is None:
            raise KeyError("review_packet_not_found")
        with self.store.pool.connection() as conn:
            ids = [row[0] for row in conn.execute("SELECT id FROM workspace_review_packets WHERE owner=%s ORDER BY created_at DESC,id DESC LIMIT 20", (owner,)).fetchall()]
        return {"packet": packet, "packet_ids": ids}

    def prepare(self, owner: str, write: ReviewPrepare) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            profile = self.store.profile(owner)
            if profile["revision"] != write.profile_revision:
                raise ConflictError("interests changed; reload before preparing the review")
            cutoff = self.store.cutoff()
            ranked = rank_items([item for item in self.store.works(owner, as_of=cutoff) if item["source_id"] in SOURCES], profile["data"], now=datetime.fromisoformat(cutoff))[:10]
            candidates = []
            for item in ranked:
                # This packet contains source metadata; private notes/history
                # do not get copied into review/export artifacts.
                public = {key: value for key, value in item.items() if key not in {"entries", "reading"}}
                work = WorkItem.model_validate(public).model_dump()
                candidates.append({"work": work, "matching_reason": item["reasons"], "evidence_scope": item.get("source_scope", item.get("access_state", "metadata")), "estimated_minutes": 5, "feedback": UsefulnessFeedback().model_dump()})
            packet = ReviewPacket(id="review-" + uuid.uuid4().hex, created_at=cutoff, as_of=cutoff,
                profile_revision=profile["revision"], policy_version=POLICY_VERSION, items=[ReviewCandidate.model_validate(item) for item in candidates],
                coverage=[SourceStatus.model_validate(source) for source in self.store.sources()], selection="Up to ten highest-ranked stored feed candidates for the frozen interests and cutoff.",
                limitations=["A five-minute metadata-reading estimate per item, not measured reading time.", "Personal usefulness is unmeasured until the owner supplies labels; no precision or approval is inferred.", "Fewer than ten eligible real records produces a shorter packet; fictional filler is never added."])
            conn.execute("INSERT INTO workspace_review_packets(owner,id,data) VALUES (%s,%s,%s)", (owner, packet.id, Jsonb(packet.model_dump())))
            return {"packet_id": packet.id}
        result = self.store._mutate(owner, write.request_id, {"prepare_review": write.model_dump()}, action)
        packet = self.get(owner, result["packet_id"])
        if packet is None:
            raise RuntimeError("review preparation was not acknowledged")
        return packet

    def save_feedback(self, owner: str, write: FeedbackWrite) -> dict[str, Any]:
        def action(conn: Any) -> dict[str, Any]:
            row = conn.execute("SELECT data FROM workspace_review_packets WHERE owner=%s AND id=%s", (owner, write.packet_id)).fetchone()
            if row is None or not any(item["work"]["work_id"] == write.work_id and item["work"]["version_id"] == write.version_id for item in row[0]["items"]):
                raise ValueError("candidate does not belong to this account and frozen review version")
            self.store._version(conn, write.work_id, write.version_id, owner)
            previous = conn.execute("SELECT revision FROM workspace_usefulness_feedback WHERE owner=%s AND packet_id=%s AND work_id=%s", (owner, write.packet_id, write.work_id)).fetchone()
            if (previous[0] if previous else 0) != write.revision:
                raise ConflictError("feedback changed; keep your draft and reload the saved judgment")
            data = {"label": write.label, "reason": write.reason.strip()}
            updated = conn.execute(
                "INSERT INTO workspace_usefulness_feedback(owner,packet_id,work_id,version_id,revision,data) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(owner,packet_id,work_id) DO UPDATE SET revision=EXCLUDED.revision,data=EXCLUDED.data,updated_at=clock_timestamp() RETURNING updated_at",
                (owner, write.packet_id, write.work_id, write.version_id, write.revision + 1, Jsonb(data)),
            ).fetchone()
            if updated is None:
                raise RuntimeError("feedback save was not acknowledged")
            return {**data, "revision": write.revision + 1, "updated_at": updated[0].isoformat()}
        return self.store._mutate(owner, write.request_id, {"usefulness_feedback": write.model_dump()}, action)
