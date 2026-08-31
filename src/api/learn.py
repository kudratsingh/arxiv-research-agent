"""Read-only HTTP surface over the repo-shipped learning paths.

Two endpoints, no store, no writes:

- `GET /learn/paths` — the published paths.
- `GET /learn/paths/{path_id}` — one path with its entries and their
  briefing companions.

Both sit behind `settings.enable_learn_content`, default off. With the
flag off the routes still exist and answer `404 learn_content_disabled`:
the web tier deliberately has no runtime feature flags
(`docs/revamp/06-WORK-ORDERS.md` §7), so a surface learns that a
capability is off by asking and being told, not by reading a config it
cannot see.

**Why the response models live here and not in `src/api/schemas.py`.**
Phase W runs a concurrent fleet across one backend, and
`05-WEDGE-WORK-ORDERS.md` §5.4's mitigation for shared files is
new-files-only wherever a card can manage it. These models are used by
nothing else, so they cost nothing to keep local and save a three-way
merge in `schemas.py`.

**What this module will not serve.** Everything below `approved` — and
therefore everything unreviewed — is filtered out in
`src/content/loader.py`, not here, so there is exactly one gate. This
module's own contribution to that guarantee is negative: it has no code
path that reads `manifest.entries` directly.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.config import settings
from src.content.loader import LoadedPath, loaded_paths
from src.content.schema import ContentValidationError, Entry
from src.observability import get_logger

log = get_logger(__name__)

router = APIRouter()

#: `settings.enable_learn_content` is off. Not "not found" in the sense
#: of a bad id — this deployment publishes no learning content at all,
#: and the detail string says which of the two it is.
DISABLED_DETAIL = "learn_content_disabled"

#: A manifest on disk failed validation. A deployment defect, not a
#: client error: 503 so a probe and an operator both read it as "this
#: dependency is broken", per ADR 0041's honest-error-names rule.
INVALID_DETAIL = "learn_content_invalid"

PATH_NOT_FOUND_DETAIL = "learn_path_not_found"


class LearnAbstract(BaseModel):
    """A paper abstract with the attribution it may not be shown without."""

    text: str
    source: str
    url: str


class LearnEntry(BaseModel):
    """One item on a path, as a client sees it.

    There is no full text and no PDF link here, and there is no field
    that could carry one: `canonical_url` is the arXiv abs page, and the
    briefing is our own prose. `provenance` and `attribution` travel with
    every entry so the surface can label it at the point of display
    (`02` §3.2) without a second request.
    """

    position: int
    resource_id: str
    kind: str
    title: str
    authors: list[str]
    #: The paper's real author count. `authors` may be a short prefix of
    #: it, so a surface renders "et al." because it knows, not because
    #: someone hard-coded it.
    author_count: int
    year: int
    canonical_url: str
    license_note: str
    license_id: str | None = None
    license_url: str | None = None
    attribution: str
    provenance: str
    status: str
    rationale: str
    vocabulary: list[str]
    est_minutes: int
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    sequencing_note: str | None = None
    sequencing_evidence_url: str | None = None
    staleness_note: str | None = None
    abstract: LearnAbstract | None = None
    briefing_markdown: str | None = Field(
        default=None,
        description=(
            "Our briefing companion, markdown. Absent when the entry has "
            "no reviewed companion yet."
        ),
    )


class LearnLicensing(BaseModel):
    """The posture the path is published under, carried to the surface.

    Rendered, not merely recorded: a link-out-only posture that the page
    does not state is indistinguishable from no posture at all.

    The five posture fields are `Literal`s rather than `str` so the
    generated TypeScript types carry the exact values — a frontend
    branching on `full_text` gets a closed union, and a `full_text`
    field that could hold a paper never reaches `schema.d.ts`.
    """

    posture_id: Literal["W-OD-3"]
    full_text: Literal["link-out-only"]
    abstracts: Literal["displayed-with-attribution"]
    quotes: Literal["sparing-and-attributed"]
    s2_derived_facts: Literal["link-back-required"]
    commercial_use: Literal["none-through-phase-w"]
    counsel_confirmed: bool
    source: str


class LearnPathSummary(BaseModel):
    """A path in the list view."""

    path_id: str
    kind: str
    title: str
    goal: str
    version: int
    status: str
    updated_at: str
    fixture: bool
    banner: str | None = None
    entry_count: int
    est_minutes_total: int


class LearnPathDetail(LearnPathSummary):
    """A path with its servable entries and the posture they ship under."""

    licensing: LearnLicensing
    entries: list[LearnEntry]


class LearnPathList(BaseModel):
    """`GET /learn/paths` — published paths only, `path_id` order."""

    paths: list[LearnPathSummary]


def _summary(path: LoadedPath) -> LearnPathSummary:
    manifest = path.manifest
    servable = manifest.servable_entries
    return LearnPathSummary(
        path_id=manifest.path_id,
        kind=manifest.kind,
        title=manifest.title,
        goal=manifest.goal,
        version=manifest.version,
        status=manifest.status,
        updated_at=manifest.updated_at,
        fixture=manifest.fixture,
        banner=manifest.banner,
        entry_count=len(servable),
        est_minutes_total=sum(e.est_minutes for e in servable),
    )


def _entry(path: LoadedPath, entry: Entry) -> LearnEntry:
    briefing = path.servable_briefing(entry)
    abstract = (
        LearnAbstract(
            text=entry.abstract.text,
            source=entry.abstract.source,
            url=entry.abstract.url,
        )
        if entry.abstract is not None
        else None
    )
    return LearnEntry(
        position=entry.position,
        resource_id=entry.resource_id,
        kind=entry.kind,
        title=entry.title,
        authors=list(entry.authors),
        author_count=entry.author_count,
        year=entry.year,
        canonical_url=entry.canonical_url,
        license_note=entry.license_note,
        license_id=entry.license_id,
        license_url=entry.license_url,
        attribution=entry.attribution,
        provenance=entry.provenance,
        status=entry.status,
        rationale=entry.rationale,
        vocabulary=list(entry.vocabulary),
        est_minutes=entry.est_minutes,
        reviewed_by=entry.reviewed_by,
        reviewed_at=entry.reviewed_at,
        sequencing_note=entry.sequencing.note,
        sequencing_evidence_url=entry.sequencing.evidence_url,
        staleness_note=entry.staleness_note,
        abstract=abstract,
        briefing_markdown=briefing.body if briefing is not None else None,
    )


def _detail(path: LoadedPath) -> LearnPathDetail:
    posture = path.manifest.licensing
    return LearnPathDetail(
        **_summary(path).model_dump(),
        licensing=LearnLicensing(
            posture_id=posture.posture_id,
            full_text=posture.full_text,
            abstracts=posture.abstracts,
            quotes=posture.quotes,
            s2_derived_facts=posture.s2_derived_facts,
            commercial_use=posture.commercial_use,
            counsel_confirmed=posture.counsel_confirmed,
            source=posture.source,
        ),
        # `servable_entries` is the gate. Reading `manifest.entries`
        # here instead would serve `proposed` rows, which is the exact
        # failure WO-W15 c1 tests for.
        entries=[_entry(path, e) for e in path.manifest.servable_entries],
    )


def _require_enabled() -> None:
    if not settings.enable_learn_content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=DISABLED_DETAIL
        )


async def _published() -> list[LoadedPath]:
    """Load (once, then cached) and keep only `published` paths.

    Runs off the event loop: the first call reads the manifest tree from
    disk, and every later call is a cache hit.
    """
    try:
        paths = await asyncio.to_thread(loaded_paths)
    except ContentValidationError as exc:
        log.error(
            "learn_content_invalid",
            extra={"rule": exc.rule, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=INVALID_DETAIL
        ) from exc
    return [p for p in paths.values() if p.manifest.status == "published"]


@router.get(
    "/learn/paths",
    response_model=LearnPathList,
    summary="Published learning paths (repo-shipped manifests, read-only).",
)
async def list_learn_paths() -> LearnPathList:
    """List every published path.

    A path below `published` is absent rather than listed-and-locked. In
    Phase W that means an install with no reviewed content answers with
    an empty list, which is the truthful answer to "what can I read?".
    """
    _require_enabled()
    return LearnPathList(paths=[_summary(p) for p in await _published()])


@router.get(
    "/learn/paths/{path_id}",
    response_model=LearnPathDetail,
    summary="One published path: its entries, briefings, and licensing posture.",
)
async def get_learn_path(path_id: str) -> LearnPathDetail:
    """Return one published path.

    An unpublished path and an unknown path are the same 404 on purpose,
    the same reasoning `_check_ownership` uses in `routes.py`: the
    existence of unpublished draft content is not a client's business.
    """
    _require_enabled()
    for path in await _published():
        if path.path_id == path_id:
            return _detail(path)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=PATH_NOT_FOUND_DETAIL
    )
