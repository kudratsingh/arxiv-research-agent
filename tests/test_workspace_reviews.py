"""Frozen real-candidate review packets preserve blank and explicit judgments."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.workspace.reviews import WorkspaceReviews
from src.workspace.schemas import FeedbackWrite, ProfileData, ProfileWrite, ReviewPrepare
from src.workspace.store import ConflictError
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


def candidates(store, count=12):
    values = [support.item(work_id=f"arxiv:2611.{i:05}", version_id=f"arxiv:2611.{i:05}:v1", source_record_id=str(i), title=f"Retrieval agent evaluation {i}") for i in range(count)]
    store.ingest("arxiv-cs-ai", values, {"status": "partial", "limitations": ["bounded test page"]}, {})
    return values


def test_finite_packet_real_candidates_have_blank_labels_and_no_private_notes(store):
    values = candidates(store)
    store.write_entry("verification", support.entry(values[0]))
    reviews = WorkspaceReviews(store)
    assert reviews.index("verification") == {"packet": None, "packet_ids": []}
    packet = reviews.prepare("verification", ReviewPrepare(profile_revision=0, request_id="prepare"))
    assert len(packet["items"]) == 10 and packet["labelled_count"] == 0
    assert all(item["feedback"]["label"] is None and item["feedback"]["revision"] == 0 for item in packet["items"])
    assert all(item["matching_reason"] and item["estimated_minutes"] == 5 for item in packet["items"])
    assert "What falsifies this result?" not in json.dumps(packet)
    assert all(item["work"]["entries"] == [] for item in packet["items"])
    assert reviews.index("other") == {"packet": None, "packet_ids": []}
    with pytest.raises(KeyError):
        reviews.index("other", packet["id"])


def test_retry_feedback_conflict_and_source_revision_never_move_a_judgment(store):
    candidates(store)
    reviews = WorkspaceReviews(store)
    write = ReviewPrepare(profile_revision=0, request_id="packet")
    packet = reviews.prepare("verification", write)
    work = packet["items"][0]["work"]
    feedback = FeedbackWrite(packet_id=packet["id"], work_id=work["work_id"], version_id=work["version_id"], revision=0, request_id="label", label="maybe", reason="Need to inspect the baseline")
    saved = reviews.save_feedback("verification", feedback)
    assert reviews.save_feedback("verification", feedback) == saved
    current = reviews.prepare("verification", write)
    assert current["labelled_count"] == 1 and current["items"][0]["feedback"] == saved
    with pytest.raises(ConflictError):
        reviews.save_feedback("verification", feedback.model_copy(update={"request_id": "stale", "label": "useful"}))
    changed = {**work, "version_id": work["work_id"] + ":v2", "version_label": "v2", "content_hash": "new", "abstract": "Revised source text", "fetched_at": "2026-11-03T02:00:00Z"}
    store.ingest("arxiv-cs-ai", [changed], {"status": "success"}, {})
    assert reviews.get("verification", packet["id"])["items"][0]["work"]["version_id"] == work["version_id"]
    with pytest.raises(ValueError, match="frozen"):
        reviews.save_feedback("verification", feedback.model_copy(update={"version_id": changed["version_id"], "request_id": "wrong-version"}))
    with pytest.raises(ValueError):
        reviews.save_feedback("other", feedback)
    cleared = reviews.save_feedback("verification", feedback.model_copy(update={"revision": 1, "request_id": "clear", "label": None, "reason": ""}))
    assert cleared["label"] is None and reviews.get("verification", packet["id"])["labelled_count"] == 0


def test_sparse_empty_and_profile_conflicts_do_not_create_fake_candidates(store):
    candidates(store, 2)
    reviews = WorkspaceReviews(store)
    write = ReviewPrepare(profile_revision=0, request_id="prepare")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reviews.prepare("verification", write), range(2)))
    assert results[0]["id"] == results[1]["id"] and len(results[0]["items"]) == 2
    assert len(reviews.index("verification")["packet_ids"]) == 1
    store.write_profile("verification", ProfileWrite(revision=0, request_id="exclude", data=ProfileData(exclusions=["retrieval"])))
    with pytest.raises(ConflictError):
        reviews.prepare("verification", ReviewPrepare(profile_revision=0, request_id="stale"))
    empty = reviews.prepare("verification", ReviewPrepare(profile_revision=1, request_id="empty"))
    assert empty["items"] == [] and empty["labelled_count"] == 0
