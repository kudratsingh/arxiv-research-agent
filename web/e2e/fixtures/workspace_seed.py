"""Seed synthetic metadata for the isolated real-API browser tier, never intake.

Run from the repository/application root with ``python - < this_file``. This
explicit CI seed neither fetches a source nor constructs a model client. Its
records are visibly fictional; the owner's separate live-intake receipt is
the evidence for public-source access. Replays preserve existing private
preferences, notes and reading state, and reuse unchanged versions/editions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any

FIXTURE_REVISION = "workspace-browser-synthetic-v1"


def _guard() -> str:
    """Refuse before importing the database/runtime or looking up a pool."""
    truthy = {"1", "true", "yes", "on"}
    if os.environ.get("WORKSPACE_E2E_SEED") != "1":
        raise SystemExit("workspace browser seed requires WORKSPACE_E2E_SEED=1")
    if os.environ.get("ENABLE_WORKSPACE", "").lower() not in truthy:
        raise SystemExit("workspace browser seed requires ENABLE_WORKSPACE=true")
    if os.environ.get("USE_MOCK_DATA", "").lower() not in truthy:
        raise SystemExit("workspace browser seed requires USE_MOCK_DATA=true")
    if os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled":
        raise SystemExit("workspace browser seed requires the disabled-key sentinel")
    owner = os.environ.get("E2E_PRINCIPAL", "e2e")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", owner):
        raise SystemExit("workspace browser seed requires a short named E2E_PRINCIPAL")
    return owner


def _fixtures(now: datetime) -> list[dict[str, Any]]:
    """Three synthetic works, one with two immutable material versions."""
    definitions = [
        (
            "ci:workspace-agent-evaluation", "arxiv-cs-ai", "v1", "abstract",
            "CI fixture — Agent memory and retrieval evaluation, revision 1",
            "Synthetic abstract for offline browser testing. An agent memory and "
            "retrieval evaluation uses a fixed baseline and a bounded compute budget. "
            "This fixture reports no real experiment or scientific finding.",
        ),
        (
            "ci:workspace-agent-evaluation", "arxiv-cs-ai", "v2", "abstract",
            "CI fixture — Agent memory and retrieval evaluation, revision 2",
            "Synthetic revised abstract for offline browser testing. Agent memory, "
            "retrieval and verification are compared against a fixed evaluation baseline. "
            "The mathematical passage 🌠 prefix 𝛼 + 🚀 signal is synthetic source text, "
            "not a result. Earlier notes must stay attached to revision 1.",
        ),
        (
            "ci:workspace-retrieval-budget", "arxiv-cs-lg", "v1", "abstract",
            "CI fixture — Retrieval verification within a controlled compute budget",
            "Synthetic abstract for offline browser testing. Retrieval, reranking and "
            "claim verification are research interests in this fixture. Reproducible "
            "evaluation and quality/cost tradeoffs are proposed questions, not measured findings.",
        ),
        (
            "ci:workspace-feed-excerpt", "hugging-face-blog", "v1", "excerpt",
            "CI fixture — A feed excerpt about bounded research agents",
            "Synthetic feed excerpt for offline browser testing. This short excerpt "
            "mentions tool use, agent memory and retrieval. A full article was not acquired, "
            "and this fixture establishes no real source freshness or scientific claim.",
        ),
    ]
    items = []
    for work_id, source_id, version, scope, title, text in definitions:
        semantic = {
            "work_id": work_id,
            "version_id": f"{work_id}:{version}",
            "source_id": source_id,
            "source_record_id": f"{work_id}:{version}",
            "version_label": version,
            "title": title,
            "url": f"https://example.invalid/workspace-ci/{work_id.removeprefix('ci:')}/{version}",
            "authors": ["CI synthetic author"],
            "abstract": text,
            "access_state": scope,
            "source_scope": scope,
            "categories": ["agents", "retrieval", "evaluation"],
            "kind": "fixture",
            "fixture_provenance": FIXTURE_REVISION,
            "published_precision": "second",
            "updated_precision": "second",
        }
        content_hash = hashlib.sha256(json.dumps(semantic, sort_keys=True).encode()).hexdigest()
        items.append({
            **semantic,
            "content_hash": content_hash,
            "published_at": (now - timedelta(days=2)).isoformat(),
            "updated_at": (now - timedelta(hours=1 if version == "v2" else 24)).isoformat(),
            "first_seen_at": now.isoformat(),
            "fetched_at": now.isoformat(),
        })
    return items


def main() -> None:
    owner = _guard()
    # These imports are intentionally after all seed/cost guards. The normal
    # shared pool is used only inside the runner's disposable CI database.
    from src.tools.postgres_pool import close_pool, get_pool
    from src.workspace.intake import SOURCES
    from src.workspace.routes import prepare_edition
    from src.workspace.schemas import ProfileData, ProfileWrite
    from src.workspace.store import WorkspaceStore

    store = WorkspaceStore(get_pool())
    try:
        store.migrate()
        now = datetime.fromisoformat(store.cutoff())
        stored_works = store.works(owner)
        sources = {source["source_id"]: source for source in store.sources()}
        with store.pool.connection() as conn:
            non_fixture = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM workspace_versions WHERE data->>'fixture_provenance' IS DISTINCT FROM %s)",
                (FIXTURE_REVISION,),
            ).fetchone()
        # This inventory spans every owner, including private imported works
        # invisible to the CI principal. Do not contaminate another library.
        if non_fixture and non_fixture[0] or any(
            source.get("receipt") and source["receipt"].get("fixture_revision") != FIXTURE_REVISION
            for source in sources.values()
        ):
            raise SystemExit("workspace browser seed found non-fixture data; use a fresh isolated CI database")
        candidates = _fixtures(now)
        existing = {version["version_id"]: version for work in stored_works for version in work["versions"]}
        items = []
        for item in candidates:
            previous = existing.get(item["version_id"])
            if previous:
                if previous.get("content_hash") != item["content_hash"]:
                    raise SystemExit("workspace CI fixture identity changed; use a new fixture revision")
                if now - datetime.fromisoformat(previous["fetched_at"]) >= timedelta(days=7):
                    raise SystemExit("workspace CI fixture is stale; use a fresh isolated CI database")
                # Reuse observation timestamps; a replay is not a fresh fetch.
                items.append(previous)
            else:
                items.append(item)
        profile = store.profile(owner)
        if profile["revision"] == 0:
            store.write_profile(owner, ProfileWrite(
                revision=0,
                request_id=f"{FIXTURE_REVISION}:initial-profile",
                data=ProfileData(**profile["data"]),
            ))
        for source_id in SOURCES:
            source_items = [item for item in items if item["source_id"] == source_id]
            receipt = sources[source_id].get("receipt", {})
            already_seeded = (
                sources[source_id].get("status") == "not_checked"
                and receipt.get("fixture_revision") == FIXTURE_REVISION
                and all(item["version_id"] in existing for item in source_items)
            )
            if already_seeded:
                continue
            store.ingest(source_id, source_items, {
                "source_id": source_id,
                "status": "not_checked",
                "reason": "offline_fixture",
                "fixture_revision": FIXTURE_REVISION,
                "fixture_provenance": FIXTURE_REVISION,
                "request_count": 0,
                "item_count": 0,
                "fixture_item_count": len(source_items),
                "seeded_at": now.isoformat(),
                "requested_window": None,
                "successful_window": None,
                "limitations": ["Synthetic metadata only; no provider was contacted and no source coverage or freshness is established."],
            }, {})
        preview = prepare_edition(store, owner, persist=False)
        matching = next((edition for edition in store.editions(owner) if all(
            edition.get(field) == preview.get(field)
            for field in ("profile_revision", "minutes", "work_ids", "work_versions", "coverage", "status")
        )), None)
        edition = matching or prepare_edition(store, owner)
        print(json.dumps({
            "mode": "synthetic_metadata_real_api_postgres",
            "fixture_revision": FIXTURE_REVISION,
            "owner": owner,
            "work_ids": sorted({item["work_id"] for item in items}),
            "version_ids": [item["version_id"] for item in items],
            "source_count": len(SOURCES),
            "source_requests": 0,
            "model_calls": 0,
            "edition_id": edition["id"],
            "edition_reused": matching is not None,
        }, sort_keys=True))
    finally:
        close_pool()


if __name__ == "__main__":
    main()
