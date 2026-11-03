"""Bounded workspace wire contracts; all mutations are revision guarded."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileData(StrictModel):
    topics: list[str] = Field(default_factory=list, max_length=500)
    custom_topics: list[str] = Field(default_factory=list, max_length=100)
    exclusions: list[str] = Field(default_factory=list, max_length=100)
    streams: list[str] = Field(default_factory=lambda: ["core", "rocket-twin", "spatial"], max_length=20)
    minutes: Literal[5, 15, 45] = 15
    research_question: str = Field(default="", max_length=2000)
    exploration: float = Field(default=0.15, ge=0, le=0.3)
    pinned_entry_id: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("topics", "custom_topics", "exclusions", "streams")
    @classmethod
    def bounded_terms(cls, value: list[str]) -> list[str]:
        if any(not term.strip() or len(term) > 500 for term in value):
            raise ValueError("terms must contain 1–500 characters")
        return list(dict.fromkeys(term.strip() for term in value))


class ProfileRevision(StrictModel):
    revision: int = 0
    data: ProfileData = Field(default_factory=ProfileData)


class ProfileWrite(StrictModel):
    revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=120)
    data: ProfileData


class ReadingData(StrictModel):
    status: Literal["unread", "saved", "read", "archived", "dismissed", "snoozed"] = "unread"
    anchor: str = Field(default="abstract:0", max_length=500)
    version_id: str = Field(default="", max_length=300)
    snoozed_until: str | None = None

    @field_validator("snoozed_until")
    @classmethod
    def aware_snooze(cls, value: str | None) -> str | None:
        if value is not None and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("snooze date requires a timezone")
        return value


class ReadingRevision(ReadingData):
    revision: int = 0
    updated_at: str = ""
    activity_sequence: int = 0


class ReadingWrite(StrictModel):
    work_id: str = Field(min_length=1, max_length=300)
    revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=120)
    data: ReadingData


class EntryData(StrictModel):
    work_id: str = Field(min_length=1, max_length=300)
    version_id: str = Field(min_length=1, max_length=300)
    kind: Literal["question", "note", "next-action"]
    body: str = Field(min_length=1, max_length=10000)
    anchor: str = Field(default="abstract:0", max_length=500)


class EntryRevision(EntryData):
    id: str
    revision: int
    updated_at: str = ""
    activity_sequence: int = 0


class EntryWrite(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=120)
    data: EntryData


class MaterialVersion(BaseModel):
    version_id: str
    version_label: str
    abstract: str = ""
    access_state: str = "metadata"
    content_hash: str = ""
    fetched_at: str = ""
    source_scope: str = "abstract"
    title: str = ""
    url: str = ""
    authors: list[str] = Field(default_factory=list)


class WorkItem(BaseModel):
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
    reading: ReadingRevision = Field(default_factory=ReadingRevision)
    entries: list[EntryRevision] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class SourceStatus(BaseModel):
    source_id: str
    name: str
    status: str = "not_checked"
    last_success_at: str | None = None
    receipt: dict[str, Any] = Field(default_factory=dict)


class Edition(BaseModel):
    id: str
    created_at: str
    profile_revision: int
    minutes: int
    work_ids: list[str]
    work_versions: dict[str, str] = Field(default_factory=dict)
    coverage: list[SourceStatus]
    status: str
    allocation: dict[str, Any] = Field(default_factory=dict)


class Activity(BaseModel):
    sequence: int
    entry_id: str | None = None
    work_id: str
    version_id: str
    kind: Literal["entry", "reading"]
    entry_kind: Literal["question", "note", "next-action"] | None = None
    body: str = ""
    anchor: str
    revision: int
    updated_at: str


class InterestCoverage(BaseModel):
    topic_id: str
    label: str
    matching_mode: Literal["descendant_terms", "literal_terms", "browse_only"]
    terms: list[str]
    descendant_ids: list[str]
    source_ids: list[str]
    status: Literal["active", "limited", "unconnected"]
    limitations: list[str]


class ScheduleData(StrictModel):
    enabled: bool = False
    timezone: str = "America/Los_Angeles"
    local_time: str = "07:00"


class ScheduleRevision(ScheduleData):
    revision: int = 0
    next_check: str | None = None


class ScheduleWrite(StrictModel):
    revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=120)
    data: ScheduleData


class WorkspaceState(BaseModel):
    principal_key_id: str
    profile: ProfileRevision
    works: list[WorkItem]
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


class RefreshRequest(StrictModel):
    source_ids: list[str] = Field(default_factory=list, max_length=5)


class ManualRequest(StrictModel):
    value: str = Field(min_length=1, max_length=2048)


class PreviewEntry(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    itemId: str = Field(min_length=1, max_length=300)
    kind: Literal["question", "note", "next-action"]
    body: str = Field(min_length=1, max_length=4000)
    anchor: str = Field(max_length=500)


class PreviewRecord(StrictModel):
    revision: Literal[1]
    topics: list[str] = Field(max_length=500)
    customTopics: list[str] = Field(max_length=100)
    configured: bool
    minutes: Literal[5, 15, 45]
    saved: list[str] = Field(max_length=500)
    entries: list[PreviewEntry] = Field(max_length=200)
    anchors: dict[str, str]
    done: bool
    researchQuestion: str = Field(max_length=2000)
    streams: list[str] = Field(max_length=20)

    @field_validator("entries")
    @classmethod
    def unique_entries(cls, entries: list[PreviewEntry]) -> list[PreviewEntry]:
        if len({entry.id for entry in entries}) != len(entries):
            raise ValueError("browser entry IDs must be unique")
        return entries


class ImportRequest(StrictModel):
    record: PreviewRecord
    profile_revision: int = Field(ge=0)
    import_profile: bool = False


class ImportPreview(BaseModel):
    digest: str
    entries_new: int
    entries_existing: int
    conflicts: list[str]
    profile_will_change: bool
    original_retained: Literal[True] = True


class ImportApply(ImportRequest):
    digest: str


class GenerationRequest(StrictModel):
    work_id: str
    kind: Literal["summary", "deep-dive"]


class ItemPage(BaseModel):
    items: list[WorkItem]
    next_cursor: str | None
    as_of: str


class UsefulnessFeedback(BaseModel):
    revision: int = 0
    label: Literal["useful", "maybe", "irrelevant"] | None = None
    reason: str = ""
    updated_at: str = ""


class ReviewCandidate(BaseModel):
    work: WorkItem
    matching_reason: list[str]
    evidence_scope: str
    estimated_minutes: Literal[5] = 5
    feedback: UsefulnessFeedback = Field(default_factory=UsefulnessFeedback)


class ReviewPacket(BaseModel):
    id: str
    created_at: str
    as_of: str
    profile_revision: int
    policy_version: str
    items: list[ReviewCandidate]
    coverage: list[SourceStatus]
    selection: str
    limitations: list[str]
    labelled_count: int = 0


class ReviewIndex(BaseModel):
    packet: ReviewPacket | None = None
    packet_ids: list[str] = Field(default_factory=list)


class ReviewPrepare(StrictModel):
    profile_revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=120)


class FeedbackWrite(StrictModel):
    packet_id: str = Field(min_length=1, max_length=80)
    work_id: str = Field(min_length=1, max_length=300)
    version_id: str = Field(min_length=1, max_length=300)
    revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=120)
    label: Literal["useful", "maybe", "irrelevant"] | None
    reason: str = Field(default="", max_length=2000)


class RetainedSpan(BaseModel):
    span_id: str
    work_id: str
    version_id: str
    material_id: str
    source_hash: str
    scope: str
    parser_revision: str
    page: int | None = None
    section: str | None = None
    start: int
    end: int
    text: str


class MaterialInfo(BaseModel):
    material_id: str
    work_id: str
    version_id: str
    source_hash: str
    content_hash: str
    scope: str
    parser_revision: str
    quality: str
    warnings: list[str]
    complete: bool
    page_count: int | None = None
    page_numbers: list[int] | None = None
    offset_basis: str
    provenance: dict[str, Any] = Field(default_factory=dict)


class MaterialDocument(MaterialInfo):
    pages: list[str]
    spans: list[RetainedSpan]


class FakePreviewRequest(StrictModel):
    kind: Literal["summary", "deep_dive"]
    material_ids: list[str] = Field(min_length=1, max_length=3)
    span_ids: list[str] = Field(default_factory=list, max_length=8)
    question: str = Field(default="", max_length=4000)


class FakeSubmitRequest(FakePreviewRequest):
    request_id: str = Field(min_length=1, max_length=120)
    expected_digest: str = Field(min_length=1, max_length=80)
