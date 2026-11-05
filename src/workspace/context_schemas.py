"""Owned manual research context. These contracts never authorize generation."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from src.workspace.schemas import (
    Activity,
    Edition,
    EntryRevision,
    EntryWrite,
    InterestCoverage,
    MaterialVersion,
    ProfileRevision,
    ReadingRevision,
    ReadingWrite,
    RetainedAvailability,
    ScheduleRevision,
    SourceStatus,
    StrictModel,
)

ProductMode = Literal["learn", "research"]


def safe_return(value: str) -> str:
    """Constrain durable navigation context; it is never an arbitrary redirect."""
    parts = urlsplit(value)
    allowed = {
        "/workspace/today",
        "/workspace/radar",
        "/workspace/library",
        "/workspace/review",
        "/workspace/projects",
    }
    thread_route = re.fullmatch(r"/workspace/threads/thread-[a-f0-9]{32}", parts.path)
    if (
        parts.scheme
        or parts.netloc
        or (parts.path not in allowed and not thread_route)
        or any(ord(c) < 32 or c == "\\" for c in value)
    ):
        raise ValueError("return context must be a local workspace list/project/thread route")
    keys = {
        "mode",
        "project",
        "thread",
        "focus",
        "view",
        "q",
        "source_id",
        "access_state",
        "status",
        "days",
        "cursor",
        "as_of",
        "packet",
        "entry",
        "version",
    }
    params = [
        (k, v)
        for k, v in parse_qsl(parts.query)
        if k in keys and len(v) <= (2048 if k == "cursor" else 500)
    ]
    fragment = parts.fragment if len(parts.fragment) <= 500 else ""
    return (
        parts.path
        + ("?" + urlencode(params) if params else "")
        + ("#" + fragment if fragment else "")
    )


class ResumeContext(StrictModel):
    mode: ProductMode = "learn"
    project_id: str | None = Field(default=None, pattern=r"^project-[a-f0-9]{32}$")
    thread_id: str | None = Field(default=None, pattern=r"^thread-[a-f0-9]{32}$")
    return_to: str = Field(default="/workspace/today", max_length=4000)

    _return = field_validator("return_to")(safe_return)


class ContextPreferencesData(StrictModel):
    default_mode: ProductMode = "learn"
    learning_background: str = Field(default="", max_length=3000)
    learning_goals: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("learning_goals")
    @classmethod
    def goals(cls, value: list[str]) -> list[str]:
        if any(not text.strip() or len(text) > 500 for text in value):
            raise ValueError("learning goals need 1–500 characters")
        return list(dict.fromkeys(text.strip() for text in value))


class ContextPreferences(StrictModel):
    revision: int = 0
    data: ContextPreferencesData = Field(default_factory=ContextPreferencesData)


class ContextPreferencesWrite(ContextPreferences):
    revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=120)


class SourceReference(StrictModel):
    work_id: str = Field(min_length=1, max_length=300)
    version_id: str = Field(min_length=1, max_length=300)
    anchor: str = Field(default="abstract:0", max_length=500)
    version_hash: str | None = Field(default=None, max_length=100)
    material_id: str | None = Field(default=None, pattern=r"^mat-[a-f0-9]{32}$")
    material_hash: str | None = Field(default=None, max_length=100)
    parser_revision: str | None = Field(default=None, max_length=120)
    source_scope: Literal["metadata", "abstract", "excerpt", "full_text"] | None = None


class BoundSource(SourceReference):
    title: str
    source_url: str
    page: int | None = None
    start: int | None = None
    end: int | None = None
    quote: str = ""
    offset_basis: str = "page-local Unicode code points; end exclusive"
    available: bool = True
    unavailable_reason: str | None = None


class EntryReference(StrictModel):
    entry_id: str = Field(min_length=1, max_length=120)
    entry_revision: int = Field(ge=1)


class ProjectData(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    question: str = Field(min_length=1, max_length=4000)
    scope: str = Field(default="", max_length=4000)
    constraints: str = Field(default="", max_length=4000)
    next_actions: list[str] = Field(default_factory=list, max_length=30)
    status: Literal["active", "archived"] = "active"

    @field_validator("title", "question")
    @classmethod
    def text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title and question cannot be blank")
        return value.strip()

    @field_validator("next_actions")
    @classmethod
    def actions(cls, value: list[str]) -> list[str]:
        if any(not text.strip() or len(text) > 2000 for text in value):
            raise ValueError("next actions need 1–2000 characters")
        return list(dict.fromkeys(text.strip() for text in value))


class ResearchProject(StrictModel):
    id: str
    revision: int
    data: ProjectData
    created_at: str
    updated_at: str
    activity_sequence: int


class ProjectWrite(StrictModel):
    id: str = Field(pattern=r"^project-[a-f0-9]{32}$")
    revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=120)
    data: ProjectData
    initial_source: SourceReference | None = None
    origin_entry: EntryReference | None = None


class ProjectSource(StrictModel):
    id: str
    role: Literal["source", "evidence"]
    label: str = ""
    status: Literal["active", "removed"] = "active"
    reference: BoundSource


class ProjectSourceWrite(StrictModel):
    revision: int = Field(ge=1)
    request_id: str = Field(min_length=1, max_length=120)
    role: Literal["source", "evidence"] = "source"
    label: str = Field(default="", max_length=2000)
    reference: SourceReference


class ProjectUnlink(StrictModel):
    revision: int = Field(ge=1)
    request_id: str = Field(min_length=1, max_length=120)
    link_id: str = Field(pattern=r"^link-[a-f0-9]{32}$")


class ProjectEntryWrite(EntryReference):
    revision: int = Field(ge=1)
    request_id: str = Field(min_length=1, max_length=120)


class LinkedEntry(EntryReference):
    entry: EntryRevision | None
    current_revision: int | None
    available: bool = True


class ArtifactData(StrictModel):
    kind: Literal["observation", "assumption", "hypothesis", "comparison", "proposed-experiment"]
    body: str = Field(default="", max_length=10000)
    entry: EntryReference | None = None
    evidence_link_ids: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def content(self) -> ArtifactData:
        if bool(self.body.strip()) == bool(self.entry):
            raise ValueError("provide manual text or an existing entry reference, not both")
        return self


class ProjectArtifact(StrictModel):
    id: str
    revision: int
    data: ArtifactData
    authorship: Literal["manual"] = "manual"
    verification: Literal["unverified"] = "unverified"


class ProjectArtifactWrite(StrictModel):
    id: str = Field(pattern=r"^artifact-[a-f0-9]{32}$")
    revision: int = Field(ge=1, description="Current project revision")
    artifact_revision: int = Field(default=0, ge=0)
    request_id: str = Field(min_length=1, max_length=120)
    data: ArtifactData


class LearningThreadData(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    goal: str = Field(min_length=1, max_length=4000)
    prerequisite: str = Field(default="", max_length=2000)
    status: Literal["active", "archived"] = "active"
    origin: ResumeContext
    source: SourceReference | None = None
    entry: EntryReference | None = None

    @model_validator(mode="after")
    def origin_present(self) -> LearningThreadData:
        if not self.title.strip() or not self.goal.strip():
            raise ValueError("a learning thread needs a title and goal")
        if not self.origin.project_id and not self.source:
            raise ValueError("a learning thread needs an originating project or source")
        return self


class LearningThread(StrictModel):
    id: str
    revision: int
    data: LearningThreadData
    source: BoundSource | None = None
    created_at: str
    updated_at: str
    activity_sequence: int


class LearningThreadWrite(StrictModel):
    id: str = Field(pattern=r"^thread-[a-f0-9]{32}$")
    revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=120)
    data: LearningThreadData


class ProjectDetail(ResearchProject):
    sources: list[ProjectSource] = Field(default_factory=list)
    entries: list[LinkedEntry] = Field(default_factory=list)
    artifacts: list[ProjectArtifact] = Field(default_factory=list)
    threads: list[LearningThread] = Field(default_factory=list)


class ContextIndex(StrictModel):
    principal_key_id: str
    preferences: ContextPreferences
    projects: list[ResearchProject]
    threads: list[LearningThread]


class ContextEntryWrite(EntryWrite):
    context: ResumeContext


class ContextReadingWrite(ReadingWrite):
    context: ResumeContext


class ContextEntryRevision(EntryRevision):
    context: ResumeContext | None = None


class ContextReadingRevision(ReadingRevision):
    context: ResumeContext | None = None


class ContextWorkItem(BaseModel):
    # A separate response contract keeps legacy endpoints byte-compatible.
    work_id: str
    version_id: str
    source_id: str
    source_record_id: str = ""
    title: str
    url: str
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    access_state: str = "metadata"
    categories: list[str] = Field(default_factory=list)
    published_at: str | None = None
    updated_at: str | None = None
    published_precision: str = "unknown"
    updated_precision: str = "unknown"
    first_seen_at: str
    fetched_at: str
    content_hash: str = ""
    version_label: str = "observed"
    kind: str = "paper"
    versions: list[MaterialVersion] = Field(default_factory=list)
    entries: list[ContextEntryRevision] = Field(default_factory=list)
    reading: ContextReadingRevision = Field(default_factory=ContextReadingRevision)
    reasons: list[str] = Field(default_factory=list)
    reading_access_state: str = "metadata"
    available_scopes: list[str] = Field(default_factory=list)
    retained_materials: list[RetainedAvailability] = Field(default_factory=list)
    mode_relevance: dict[str, Any] = Field(default_factory=dict)


class ResolvedContext(StrictModel):
    mode: ProductMode
    project_id: str | None = None
    thread_id: str | None = None
    project_revision: int | None = None
    policy_version: str
    unavailable_reason: str | None = None


class ContextEdition(Edition):
    context: ResolvedContext
    context_preferences_revision: int
    candidate_digest: str


class ContextWorkspaceState(BaseModel):
    principal_key_id: str
    profile: ProfileRevision
    works: list[ContextWorkItem]
    sources: list[SourceStatus]
    editions: list[Edition]
    schedule: ScheduleRevision
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    generation: Literal["approval_required"] = "approval_required"
    as_of: str
    activity: list[Activity] = Field(default_factory=list)
    latest_activity: Activity | None = None
    interest_coverage: list[InterestCoverage] = Field(default_factory=list)
    allocation_previews: list[dict[str, Any]] = Field(default_factory=list)
    context: ResolvedContext
    active_edition: ContextEdition | None = None


class ContextWorkPage(StrictModel):
    items: list[ContextWorkItem]
    next_cursor: str | None
    as_of: str
    context: ResolvedContext
