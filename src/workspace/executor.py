"""Executable local fake lane over retained evidence; never a paid adapter.

The exact request, stage schemas, selected source bytes, artifacts and simulated
usage are durable. A fake check exercises the grounding protocol; it is not a
calibrated factual judgment or evidence of real model quality. No private notes,
reading history, profile or approval records are read or written by this module.

Counters use UTF-8 byte lengths as explicitly synthetic token units. Every real
USD field is constrained to zero in a separate fake reservation table. A lost
in-flight step becomes interrupted/unknown and is never automatically replayed.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.workspace.grounding import (
    ClaimKind,
    GroundingReport,
    ResearchClaim,
    SupportCheck,
    claim_input_digest,
    evidence_ref,
    validate_claims,
)
from src.workspace.material import SourceMaterial, SourceSpan
from src.workspace.store import ConflictError, WorkspaceStore

MODEL_ID: Final = "fixture-workspace-v1"
FIXTURE_REVISION: Final = "workspace-executor-v1"
CHECKER_ID = "fixture-workspace-checker"
SCHEMA_REVISION = "workspace-fake-execution-v1"
FAKE_TITLE: Final = "Fake analysis of selected retained passages"
FAKE_LIMITATION: Final = "Local deterministic fixture; quotations and synthetic checks do not establish scientific truth or real model quality."
LEASE_SECONDS = 120
TERMINAL = {
    "ready",
    "ready_partial",
    "cancelled",
    "failed",
    "interrupted",
    "budget_stopped",
    "stale",
}
Kind = Literal["summary", "deep_dive"]
Phase = Literal["draft", "check", "repair"]


class ExecutorError(ValueError):
    """Stable refusal without private source/question text in its message."""


class FakeCancelled(Exception):
    """Cooperative local cancellation; no provider request was made."""


class FakeCompletedResponseError(ValueError):
    """A recorded complete local response failed content validation, not receipt."""

    def __init__(self, response: dict[str, Any]):
        super().__init__("completed_fake_response_invalid")
        self.response = response


class FakeJobState(StrEnum):
    QUEUED = "queued"
    DRAFTING = "drafting"
    CHECKING = "checking"
    REPAIRING = "repairing"
    READY = "ready"
    READY_PARTIAL = "ready_partial"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    BUDGET_STOPPED = "budget_stopped"
    STALE = "stale"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FakeDraft(_Model):
    kind: Kind
    title: str = Field(min_length=1, max_length=300)
    claims: tuple[ResearchClaim, ...] = Field(min_length=1, max_length=8)
    sections: dict[str, tuple[str, ...]]
    questions: tuple[str, ...] = Field(default=(), max_length=8)
    proposed_actions: tuple[str, ...] = Field(default=(), max_length=8)
    limitations: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def sections_reference_claims(self) -> FakeDraft:
        allowed = (
            {"overview"}
            if self.kind == "summary"
            else {"overview", "prerequisites", "method", "assumptions", "comparison", "experiment"}
        )
        ids = {claim.claim_id for claim in self.claims}
        if (
            not self.sections
            or set(self.sections) - allowed
            or any(id_ not in ids for refs in self.sections.values() for id_ in refs)
        ):
            raise ValueError("sections must reference emitted claim/inference ids")
        if len(ids) != len(self.claims) or any(
            not text.strip() or len(text) > 2000
            for text in (*self.questions, *self.proposed_actions, *self.limitations)
        ):
            raise ValueError("invalid bounded draft fields")
        return self


class FakeCheckBatch(_Model):
    checks: tuple[SupportCheck, ...] = Field(max_length=8)


class FakeLimits(_Model):
    max_calls: Literal[4] = 4
    max_repairs: Literal[1] = 1
    per_call_input_tokens: int
    per_call_output_tokens: int
    max_input_tokens: int
    max_output_tokens: int
    max_source_bytes: int
    max_spans: int


class FakeRequestPreview(_Model):
    mode: Literal["fake"] = "fake"
    model_id: Literal["fixture-workspace-v1"] = MODEL_ID
    fixture_revision: Literal["workspace-executor-v1"] = FIXTURE_REVISION
    kind: Kind
    request_digest: str
    request: dict[str, Any]
    limits: FakeLimits
    usage_basis: Literal["simulated UTF-8 byte counters; not provider tokens"] = (
        "simulated UTF-8 byte counters; not provider tokens"
    )
    actual_usd: Literal["0.000000"] = "0.000000"


class FakeCounter(_Model):
    input_tokens: int = 0
    output_tokens: int = 0


class FakeUsage(_Model):
    workflow: FakeCounter = Field(default_factory=FakeCounter)
    checker: FakeCounter = Field(default_factory=FakeCounter)
    unknown: FakeCounter = Field(default_factory=FakeCounter)
    used_calls: int = 0
    max_calls: int = 4
    usage_basis: str = "simulated UTF-8 byte counters; not provider tokens"
    actual_usd: Literal["0.000000"] = "0.000000"


class FakeStep(_Model):
    ordinal: int
    phase: Phase
    state: Literal["running", "completed", "failed", "interrupted"]
    request_digest: str
    request: dict[str, Any]
    response: dict[str, Any] | None = None
    input_tokens: int
    output_tokens: int = 0
    error: str | None = None
    unknown_recorded: bool = False


class FakeResult(_Model):
    mode: Literal["fake"] = "fake"
    model_id: Literal["fixture-workspace-v1"] = MODEL_ID
    fixture_revision: Literal["workspace-executor-v1"] = FIXTURE_REVISION
    check_basis: str = (
        "synthetic exact-quotation checks; not a calibrated judge or model-quality result"
    )
    request_digest: str
    draft: FakeDraft
    grounding: dict[str, Any]


class FakeJob(_Model):
    id: str
    kind: Kind
    state: FakeJobState
    revision: int
    mode: Literal["fake"] = "fake"
    model_id: Literal["fixture-workspace-v1"] = MODEL_ID
    fixture_revision: Literal["workspace-executor-v1"] = FIXTURE_REVISION
    request_digest: str
    request: dict[str, Any]
    draft: FakeDraft | None = None
    grounding: dict[str, Any] | None = None
    result: FakeResult | None = None
    steps: tuple[FakeStep, ...] = ()
    usage: FakeUsage
    cancel_requested: bool = False
    lease_until: str | None = None
    error: str | None = None
    cached: bool = False


def _json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ExecutorError("invalid_json_payload") from exc


def _copy(value: Any) -> Any:
    return json.loads(_json(value))


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode()).hexdigest()


def _size(value: Any) -> int:
    return len(_json(value).encode())


def _limits(kind: Kind) -> FakeLimits:
    multiplier = 1 if kind == "summary" else 2
    return FakeLimits(
        per_call_input_tokens=64_000 * multiplier,
        per_call_output_tokens=32_000 * multiplier,
        max_input_tokens=256_000 * multiplier,
        max_output_tokens=128_000 * multiplier,
        max_source_bytes=8_000 * multiplier,
        max_spans=4 * multiplier,
    )


def _fake_only() -> None:
    if os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled":
        raise ExecutorError("fake_lane_requires_disabled_key_sentinel")


def _clock(store: WorkspaceStore, now: datetime | None) -> datetime:
    instant = now or datetime.fromisoformat(store.cutoff())
    if instant.tzinfo is None:
        raise ExecutorError("aware_clock_required")
    return instant.astimezone(UTC)


def _material(data: dict[str, Any]) -> SourceMaterial:
    try:
        return SourceMaterial(
            **{
                **data,
                "warnings": tuple(data["warnings"]),
                "pages": tuple(data["pages"]),
                "page_numbers": tuple(data["page_numbers"])
                if data.get("page_numbers") is not None
                else None,
                "spans": tuple(SourceSpan(**span) for span in data["spans"]),
            }
        )
    except (TypeError, KeyError) as exc:
        raise ExecutorError("retained_material_invalid") from exc


class FakeProvider:
    """The only application adapter: local deterministic fixtures, without I/O.

    Tests may subclass this class to inject local failure/repair behavior. No
    provider name, SDK, factory or callable can be supplied by an HTTP caller.
    Every stage receives only its sealed JSON, plus cooperative cancellation.
    """

    model_id = MODEL_ID
    fixture_revision = FIXTURE_REVISION

    @staticmethod
    def _cancel(cancelled: Callable[[], bool]) -> None:
        if cancelled():
            raise FakeCancelled()

    def draft(self, request: dict[str, Any], *, cancelled: Callable[[], bool]) -> dict[str, Any]:
        self._cancel(cancelled)
        original = request["sealed_request"]
        claims: list[dict[str, Any]] = []
        for source in original["sources"]:
            for span in source["spans"]:
                ref = {
                    "material_id": source["material_id"],
                    "span_id": span["span_id"],
                    "work_id": source["work_id"],
                    "version_id": source["version_id"],
                    "source_hash": source["source_hash"],
                    "scope": source["scope"],
                    "parser_revision": source["parser_revision"],
                    "page": span["page"],
                    "start": span["start"],
                    "end": span["end"],
                    "quote": span["text"],
                }
                claims.append(
                    {
                        "claim_id": f"quote-{len(claims) + 1}",
                        "text": span["text"],
                        "kind": "factual",
                        "required_scope": source["scope"],
                        "evidence": [ref],
                    }
                )
        ids = tuple(claim["claim_id"] for claim in claims)
        sections = {"overview": ids}
        if original["kind"] == "deep_dive":
            sections.update(
                {
                    "prerequisites": (),
                    "method": (),
                    "assumptions": (),
                    "comparison": (),
                    "experiment": (),
                }
            )
        return {
            "kind": original["kind"],
            "title": FAKE_TITLE,
            "claims": claims,
            "sections": sections,
            "questions": ["What further source material would test these quoted claims?"],
            "proposed_actions": [
                "Proposed manual check: compare these passages with the original source."
            ],
            "limitations": [FAKE_LIMITATION],
        }

    def check(self, request: dict[str, Any], *, cancelled: Callable[[], bool]) -> dict[str, Any]:
        self._cancel(cancelled)
        digests = {entry["claim_id"]: entry["input_digest"] for entry in request["claim_inputs"]}
        return {
            "checks": [
                {
                    "claim_id": claim["claim_id"],
                    "input_digest": digests[claim["claim_id"]],
                    "decision": "supported"
                    if claim["evidence"] and claim["text"] == claim["evidence"][0]["quote"]
                    else "unsupported",
                    "checker_id": CHECKER_ID,
                    "checker_revision": FIXTURE_REVISION,
                    "reason": "Synthetic exact-quotation comparison only; not semantic verification.",
                }
                for claim in request["draft"]["claims"]
                if claim["kind"] == "factual"
            ]
        }

    def repair(self, request: dict[str, Any], *, cancelled: Callable[[], bool]) -> dict[str, Any]:
        return self.draft(request, cancelled=cancelled)


class FakeExecutor:
    """Durable owner-scoped, four-call fixture pipeline in separate fake tables."""

    def __init__(self, store: WorkspaceStore):
        self.store = store

    def _owner(self, owner: str) -> None:
        self.store._owner(owner)
        if len(owner) > 120:
            raise ExecutorError("invalid_owner")
        self.store.migrate()

    @staticmethod
    def _lock(conn: Any, owner: str) -> None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("fake-executor:" + owner,)
        )

    @staticmethod
    def _row(conn: Any, owner: str, job_id: str, *, lock: bool = False) -> tuple[Any, ...]:
        row = conn.execute(
            "SELECT id,kind,state,revision,request_digest,request,data,cancel_requested,lease_owner,lease_until FROM workspace_fake_generation_jobs WHERE owner=%s AND id=%s"
            + (" FOR UPDATE" if lock else ""),
            (owner, job_id),
        ).fetchone()
        if row is None:
            raise ExecutorError("fake_job_not_found")
        return tuple(row)

    def _sources(
        self, conn: Any, owner: str, material_ids: Sequence[str]
    ) -> tuple[SourceMaterial, ...]:
        if (
            not 1 <= len(material_ids) <= 3
            or len(set(material_ids)) != len(material_ids)
            or any(
                not isinstance(id_, str) or not id_.strip() or len(id_) > 300
                for id_ in material_ids
            )
        ):
            raise ExecutorError("invalid_material_selection")
        materials = []
        for id_ in sorted(material_ids):
            row = conn.execute(
                "SELECT m.data,m.content_hash,m.source_scope,v.version_id,v.work_id FROM workspace_material m JOIN workspace_versions v ON v.version_id=m.version_id JOIN workspace_works w ON w.work_id=v.work_id WHERE m.material_id=%s AND (w.visibility_owner IS NULL OR w.visibility_owner=%s)",
                (id_, owner),
            ).fetchone()
            if row is None:
                raise ExecutorError("source_material_missing_or_private")
            material = _material(row[0])
            if (
                material.content_hash,
                material.scope,
                material.version_id,
                material.work_id,
                material.material_id,
            ) != (row[1], row[2], row[3], row[4], id_):
                raise ExecutorError("retained_material_identity_drift")
            materials.append(material)
        validate_claims([], materials)
        return tuple(materials)

    def _preview(
        self,
        conn: Any,
        owner: str,
        kind: Kind,
        material_ids: Sequence[str],
        span_ids: Sequence[str],
        question: str,
    ) -> tuple[FakeRequestPreview, tuple[SourceMaterial, ...]]:
        if (
            kind not in {"summary", "deep_dive"}
            or not isinstance(question, str)
            or len(question) > 4000
        ):
            raise ExecutorError("invalid_fake_request")
        if len(set(span_ids)) != len(span_ids) or any(
            not isinstance(id_, str) or not id_.strip() for id_ in span_ids
        ):
            raise ExecutorError("invalid_span_selection")
        materials = self._sources(conn, owner, material_ids)
        selected = set(span_ids)
        available = {span.span_id for material in materials for span in material.spans}
        if selected - available:
            raise ExecutorError("span_not_in_selected_material")
        if not selected:
            selected = available
        limits = _limits(kind)
        if not selected:
            raise ExecutorError("retained_source_text_required")
        if len(selected) > limits.max_spans:
            raise ExecutorError("source_selection_too_large_choose_spans")
        sources = []
        source_bytes = 0
        for material in materials:
            spans = [span for span in material.spans if span.span_id in selected]
            if not spans:
                raise ExecutorError("selected_material_has_no_selected_span")
            for span in spans:
                probe = ResearchClaim(
                    "identity-probe",
                    "Retained quotation identity probe",
                    ClaimKind.FACTUAL,
                    (evidence_ref(material, span),),
                    required_scope=material.scope,
                )
                validate_claims([probe], materials)
            source_bytes += sum(len(span.text.encode()) for span in spans)
            sources.append(
                {
                    "material_id": material.material_id,
                    "work_id": material.work_id,
                    "version_id": material.version_id,
                    "content_hash": material.content_hash,
                    "source_hash": material.source_hash,
                    "scope": material.scope,
                    "parser_revision": material.parser_revision,
                    "complete": material.complete,
                    "quality": material.quality,
                    "offset_basis": material.offset_basis,
                    "page_count": material.page_count,
                    "page_numbers": list(material.page_numbers)
                    if material.page_numbers is not None
                    else None,
                    "warnings": list(material.warnings),
                    "spans": [asdict(span) for span in spans],
                }
            )
        if source_bytes > limits.max_source_bytes:
            raise ExecutorError("source_selection_too_large_choose_spans")
        request = {
            "schema_revision": SCHEMA_REVISION,
            "mode": "fake",
            "model_id": MODEL_ID,
            "fixture_revision": FIXTURE_REVISION,
            "kind": kind,
            "question": question,
            "selection": {"material_ids": sorted(material_ids), "span_ids": sorted(selected)},
            "private_context": {"notes": False, "reading_history": False, "profile": False},
            "sources": sources,
            "settings": {"temperature": 0, "structured_outputs": True, "max_repairs": 1},
            "stage_contracts": {
                "draft": {
                    "role": "workflow",
                    "prompt_revision": FIXTURE_REVISION + ":draft",
                    "output_schema": FakeDraft.model_json_schema(),
                },
                "check": {
                    "role": "checker",
                    "prompt_revision": FIXTURE_REVISION + ":check",
                    "output_schema": FakeCheckBatch.model_json_schema(),
                },
                "repair": {
                    "role": "workflow",
                    "prompt_revision": FIXTURE_REVISION + ":repair",
                    "output_schema": FakeDraft.model_json_schema(),
                },
            },
            "limits": limits.model_dump(),
        }
        if _size(request) > limits.per_call_input_tokens:
            raise ExecutorError("sealed_request_too_large")
        return FakeRequestPreview(
            kind=kind, request_digest=_hash(request), request=request, limits=limits
        ), materials

    def preview(
        self,
        owner: str,
        kind: Kind,
        material_ids: Sequence[str],
        *,
        span_ids: Sequence[str] = (),
        question: str = "",
    ) -> FakeRequestPreview:
        self._owner(owner)
        with self.store.pool.connection() as conn:
            return self._preview(conn, owner, kind, material_ids, span_ids, question)[0]

    def submit(
        self,
        owner: str,
        request_id: str,
        kind: Kind,
        material_ids: Sequence[str],
        *,
        expected_digest: str,
        span_ids: Sequence[str] = (),
        question: str = "",
    ) -> FakeJob:
        _fake_only()
        self._owner(owner)
        if not request_id.strip() or len(request_id) > 120:
            raise ExecutorError("invalid_request_id")
        with self.store.pool.connection() as conn:
            self._lock(conn, owner)
            preview, _ = self._preview(conn, owner, kind, material_ids, span_ids, question)
            if preview.request_digest != expected_digest:
                raise ConflictError("fake request changed since its exact preview")
            job_id = "fake-" + _hash([owner, request_id])[7:47]
            prior = conn.execute(
                "SELECT request_digest FROM workspace_fake_generation_jobs WHERE owner=%s AND id=%s",
                (owner, job_id),
            ).fetchone()
            if prior:
                if prior[0] != expected_digest:
                    raise ConflictError("fake retry key changed request")
            else:
                cache = conn.execute(
                    "SELECT id FROM workspace_fake_generation_jobs WHERE owner=%s AND request_digest=%s AND state IN ('ready','ready_partial') ORDER BY created_at DESC LIMIT 1",
                    (owner, expected_digest),
                ).fetchone()
                if cache:
                    return self._snapshot(conn, self._row(conn, owner, cache[0]), cached=True)
                limits = preview.limits
                conn.execute(
                    "INSERT INTO workspace_fake_generation_jobs(id,owner,request_id,kind,model_id,fixture_revision,state,request_digest,request,data) VALUES (%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s)",
                    (
                        job_id,
                        owner,
                        request_id,
                        kind,
                        MODEL_ID,
                        FIXTURE_REVISION,
                        expected_digest,
                        Jsonb(preview.request),
                        Jsonb({"next_phase": "draft", "steps": [], "repairs": 0}),
                    ),
                )
                conn.execute(
                    "INSERT INTO workspace_fake_generation_reservations(job_id,owner,max_calls,max_input_tokens,max_output_tokens,state) VALUES (%s,%s,%s,%s,%s,'held')",
                    (
                        job_id,
                        owner,
                        limits.max_calls,
                        limits.max_input_tokens,
                        limits.max_output_tokens,
                    ),
                )
            return self._snapshot(conn, self._row(conn, owner, job_id))

    @staticmethod
    def _snapshot(conn: Any, row: tuple[Any, ...], *, cached: bool = False) -> FakeJob:
        usage = conn.execute(
            "SELECT workflow_input,workflow_output,checker_input,checker_output,unknown_input,unknown_output,used_calls,max_calls,actual_usd FROM workspace_fake_generation_reservations WHERE job_id=%s",
            (row[0],),
        ).fetchone()
        if usage is None or usage[8] != 0:
            raise ExecutorError("invalid_fake_reservation")
        data = row[6]
        return FakeJob(
            id=row[0],
            kind=row[1],
            state=row[2],
            revision=row[3],
            request_digest=row[4],
            request=row[5],
            draft=data.get("draft"),
            grounding=data.get("report"),
            result=data.get("result") if row[2] in {"ready", "ready_partial"} else None,
            steps=tuple(data.get("steps", [])),
            usage=FakeUsage(
                workflow=FakeCounter(input_tokens=usage[0], output_tokens=usage[1]),
                checker=FakeCounter(input_tokens=usage[2], output_tokens=usage[3]),
                unknown=FakeCounter(input_tokens=usage[4], output_tokens=usage[5]),
                used_calls=usage[6],
                max_calls=usage[7],
            ),
            cancel_requested=row[7],
            lease_until=row[9].isoformat() if row[9] else None,
            error=data.get("error"),
            cached=cached,
        )

    def get(self, owner: str, job_id: str) -> FakeJob:
        self._owner(owner)
        with self.store.pool.connection() as conn:
            return self._snapshot(conn, self._row(conn, owner, job_id))

    def list(self, owner: str, limit: int = 20) -> list[FakeJob]:
        self._owner(owner)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ExecutorError("invalid_job_limit")
        with self.store.pool.connection() as conn:
            ids = conn.execute(
                "SELECT id FROM workspace_fake_generation_jobs WHERE owner=%s AND request->>'schema_revision'=%s ORDER BY created_at DESC,id DESC LIMIT %s",
                (owner, SCHEMA_REVISION, limit),
            ).fetchall()
            return [self._snapshot(conn, self._row(conn, owner, row[0])) for row in ids]

    @staticmethod
    def _save(
        conn: Any,
        row: tuple[Any, ...],
        state: str,
        data: dict[str, Any],
        *,
        lease_owner: str | None = None,
        lease_until: datetime | None = None,
    ) -> None:
        conn.execute(
            "UPDATE workspace_fake_generation_jobs SET state=%s,data=%s,revision=revision+1,lease_owner=%s,lease_until=%s,updated_at=clock_timestamp() WHERE id=%s",
            (state, Jsonb(data), lease_owner, lease_until, row[0]),
        )

    @staticmethod
    def _settle(conn: Any, job_id: str, state: str) -> None:
        conn.execute(
            "UPDATE workspace_fake_generation_reservations SET state=CASE WHEN unknown_input+unknown_output>0 THEN 'uncertain' ELSE %s END WHERE job_id=%s",
            ("cancelled" if state == "cancelled" else "settled", job_id),
        )

    def _intact(self, conn: Any, owner: str, row: tuple[Any, ...]) -> tuple[SourceMaterial, ...]:
        original = row[5]
        preview, materials = self._preview(
            conn,
            owner,
            original["kind"],
            original["selection"]["material_ids"],
            original["selection"]["span_ids"],
            original["question"],
        )
        if preview.request_digest != row[4] or _hash(original) != row[4]:
            raise ExecutorError("sealed_request_or_source_drift")
        return materials

    def _stage(self, row: tuple[Any, ...], materials: tuple[SourceMaterial, ...]) -> dict[str, Any]:
        data = row[6]
        phase = data["next_phase"]
        contract = row[5]["stage_contracts"][phase]
        request = {"phase": phase, **contract, "sealed_request": row[5]}
        if phase in {"check", "repair"}:
            draft = FakeDraft.model_validate(data["draft"])
            request["draft"] = draft.model_dump(mode="json")
            if phase == "check":
                request["claim_inputs"] = [
                    {
                        "claim_id": claim.claim_id,
                        "input_digest": claim_input_digest(claim, materials),
                    }
                    for claim in draft.claims
                    if claim.kind == ClaimKind.FACTUAL
                ]
            else:
                request["previous_grounding"] = data["report"]
        return dict(_copy(request))

    def _cancelled(self, owner: str, job_id: str) -> bool:
        with self.store.pool.connection() as conn:
            row = self._row(conn, owner, job_id)
            return bool(row[7] or row[2] in TERMINAL)

    def advance(
        self,
        owner: str,
        job_id: str,
        *,
        provider: FakeProvider | None = None,
        worker: str | None = None,
        now: datetime | None = None,
    ) -> FakeJob:
        _fake_only()
        self._owner(owner)
        adapter = provider if provider is not None else FakeProvider()
        if (
            not isinstance(adapter, FakeProvider)
            or adapter.model_id != MODEL_ID
            or adapter.fixture_revision != FIXTURE_REVISION
        ):
            raise ExecutorError("only_explicit_local_fake_provider_allowed")
        instant, worker_id = _clock(self.store, now), worker or uuid.uuid4().hex
        with self.store.pool.connection() as conn:
            self._lock(conn, owner)
            row = self._row(conn, owner, job_id, lock=True)
            if type(self) is FakeExecutor and row[5].get("schema_revision") != SCHEMA_REVISION:
                raise ExecutorError("use_the_versioned_assistance_endpoint")
            if row[2] in TERMINAL:
                return self._snapshot(conn, row)
            if row[9] is not None:
                if row[9] <= instant:
                    self._recover(conn, row)
                    return self._snapshot(conn, self._row(conn, owner, job_id))
                return self._snapshot(conn, row)
            data = _copy(row[6])
            try:
                materials = self._intact(conn, owner, row)
                stage = self._stage(row, materials)
            except (ValueError, KeyError):
                data["error"] = "sealed_request_or_source_drift"
                self._save(conn, row, "stale", data)
                self._settle(conn, job_id, "stale")
                return self._snapshot(conn, self._row(conn, owner, job_id))
            reservation = conn.execute(
                "SELECT used_calls,max_calls,workflow_input+checker_input+unknown_input,workflow_output+checker_output+unknown_output,max_input_tokens,max_output_tokens FROM workspace_fake_generation_reservations WHERE job_id=%s",
                (job_id,),
            ).fetchone()
            limits = row[5]["limits"]
            if (
                reservation is None
                or reservation[0] >= reservation[1]
                or _size(stage) > limits["per_call_input_tokens"]
                or reservation[2] + _size(stage) > reservation[4]
                or reservation[3] + limits["per_call_output_tokens"] > reservation[5]
            ):
                data["error"] = "fake_call_envelope_exceeded"
                self._save(conn, row, "budget_stopped", data)
                self._settle(conn, job_id, "budget_stopped")
                return self._snapshot(conn, self._row(conn, owner, job_id))
            phase: Phase = data["next_phase"]
            step = FakeStep(
                ordinal=len(data["steps"]),
                phase=phase,
                state="running",
                request_digest=_hash(stage),
                request=stage,
                input_tokens=_size(stage),
            )
            data["steps"].append(step.model_dump())
            if phase == "repair":
                data["repairs"] += 1
                if data["repairs"] > 1:
                    raise ExecutorError("repair_bound_exceeded")
            state = {"draft": "drafting", "check": "checking", "repair": "repairing"}[phase]
            self._save(
                conn,
                row,
                state,
                data,
                lease_owner=worker_id,
                lease_until=instant + timedelta(seconds=LEASE_SECONDS),
            )
            conn.execute(
                "UPDATE workspace_fake_generation_reservations SET used_calls=used_calls+1 WHERE job_id=%s",
                (job_id,),
            )
        # Provider work runs after commit, outside database/advisory locks.
        response: dict[str, Any] | None = None
        output_units = 0
        error: str | None = None
        try:
            actual = _copy(stage)
            raw = getattr(adapter, phase)(actual, cancelled=lambda: self._cancelled(owner, job_id))
            output_units = _size(raw)
            response = raw if isinstance(raw, dict) else None
            if _hash(actual) != step.request_digest:
                error = "fake_provider_mutated_sealed_request"
            elif response is None:
                error = "invalid_fake_response"
            elif output_units > limits["per_call_output_tokens"]:
                error = "fake_output_envelope_exceeded"
        except FakeCancelled:
            error = "cancelled"
        except FakeCompletedResponseError as exc:
            response = exc.response
            output_units = _size(response)
            error = "completed_fake_response_invalid"
        except Exception:
            response = None
            error = "fake_provider_error"
        return self._finish(
            owner,
            job_id,
            worker_id,
            phase,
            response,
            error,
            materials,
            finished=instant if now is not None else None,
            output_units=output_units,
        )

    @staticmethod
    def _draft(
        response: dict[str, Any], row: tuple[Any, ...], materials: tuple[SourceMaterial, ...]
    ) -> FakeDraft:
        draft = FakeDraft.model_validate_json(_json(response))
        if draft.kind != row[1]:
            raise ExecutorError("draft_kind_drift")
        allowed_limitations = {
            FAKE_LIMITATION,
            *(warning for source in row[5]["sources"] for warning in source["warnings"]),
        }
        if draft.title != FAKE_TITLE or any(
            text not in allowed_limitations for text in draft.limitations
        ):
            raise ExecutorError("unbound_factual_title_or_limitation")
        selected = set(row[5]["selection"]["span_ids"])
        if any(ref.span_id not in selected for claim in draft.claims for ref in claim.evidence):
            raise ExecutorError("draft_references_unselected_span")
        assessed = validate_claims(draft.claims, materials)
        if any(
            assessment.kind == ClaimKind.FACTUAL and not assessment.identity_resolved
            for assessment in assessed.assessments
        ):
            raise ExecutorError("draft_factual_evidence_missing")
        return draft

    def _finish(
        self,
        owner: str,
        job_id: str,
        worker: str,
        phase: Phase,
        response: dict[str, Any] | None,
        error: str | None,
        materials: tuple[SourceMaterial, ...],
        *,
        finished: datetime | None = None,
        output_units: int = 0,
    ) -> FakeJob:
        # Cancellation/source drift classify the job, not whether the missing
        # provider completion is known. Preserve that uncertainty independently.
        completion_unknown = error == "fake_provider_error"
        completion = _clock(self.store, finished)
        with self.store.pool.connection() as conn:
            self._lock(conn, owner)
            row = self._row(conn, owner, job_id, lock=True)
            # A recovered/expired worker cannot publish or count its late reply twice.
            if row[8] != worker or row[9] is None:
                return self._snapshot(conn, row)
            if row[9] <= completion:
                self._recover(conn, row)
                return self._snapshot(conn, self._row(conn, owner, job_id))
            data = _copy(row[6])
            step = data["steps"][-1]
            if step["phase"] != phase or step["state"] != "running":
                raise ExecutorError("fake_step_fence_lost")
            try:
                self._intact(conn, owner, row)
            except (ValueError, KeyError):
                error = "sealed_request_or_source_drift"
            output = output_units
            limits = row[5]["limits"]
            if step["unknown_recorded"]:
                conn.execute(
                    "UPDATE workspace_fake_generation_reservations SET unknown_input=unknown_input-%s,unknown_output=unknown_output-%s WHERE job_id=%s",
                    (step["input_tokens"], limits["per_call_output_tokens"], job_id),
                )
                step["unknown_recorded"] = False
            bucket = "checker" if phase == "check" else "workflow"
            conn.execute(
                "UPDATE workspace_fake_generation_reservations SET "
                + bucket
                + "_input="
                + bucket
                + "_input+%s,"
                + bucket
                + "_output="
                + bucket
                + "_output+%s WHERE job_id=%s",
                (step["input_tokens"], output, job_id),
            )
            step["output_tokens"] = output
            step["response"] = (
                response
                if isinstance(response, dict)
                and _size(response) <= limits["per_call_output_tokens"]
                else None
            )
            if row[7] or error == "cancelled":
                state, error = "cancelled", "cancelled"
            elif error:
                state = (
                    "budget_stopped"
                    if error == "fake_output_envelope_exceeded"
                    else "stale"
                    if error == "sealed_request_or_source_drift"
                    else "failed"
                )
            else:
                try:
                    state = self._apply(data, row, phase, response or {}, materials)
                except (ValueError, KeyError, TypeError):
                    state, error = "failed", "invalid_fake_draft_or_checks"
            if completion_unknown:
                # The missing local completion is unknown; never label it measured zero.
                conn.execute(
                    "UPDATE workspace_fake_generation_reservations SET unknown_output=unknown_output+%s WHERE job_id=%s",
                    (limits["per_call_output_tokens"], job_id),
                )
            step["state"] = "failed" if error else "completed"
            step["error"] = error
            data["error"] = error or data.get("error")
            self._save(conn, row, state, data)
            if state in TERMINAL:
                self._settle(conn, job_id, state)
            return self._snapshot(conn, self._row(conn, owner, job_id))

    @staticmethod
    def _apply(
        data: dict[str, Any],
        row: tuple[Any, ...],
        phase: Phase,
        response: dict[str, Any],
        materials: tuple[SourceMaterial, ...],
    ) -> str:
        if phase in {"draft", "repair"}:
            draft = FakeExecutor._draft(response, row, materials)
            data["draft"] = draft.model_dump(mode="json")
            data["next_phase"] = "check"
            return "checking"
        draft = FakeDraft.model_validate(data["draft"])
        batch = FakeCheckBatch.model_validate_json(_json(response))
        factual = {claim.claim_id for claim in draft.claims if claim.kind == ClaimKind.FACTUAL}
        if {check.claim_id for check in batch.checks} != factual or any(
            check.checker_id != CHECKER_ID or check.checker_revision != FIXTURE_REVISION
            for check in batch.checks
        ):
            raise ExecutorError("fake_checker_coverage_or_provenance_drift")
        report: GroundingReport = validate_claims(draft.claims, materials, batch.checks)
        data["report"] = _copy(asdict(report))
        if report.unsupported:
            if data["repairs"] < 1:
                data["next_phase"] = "repair"
                return "repairing"
            data["error"] = "unsupported_claims_after_bounded_repair"
            return "failed"
        result = FakeResult(request_digest=row[4], draft=draft, grounding=data["report"])
        data["result"] = result.model_dump(mode="json")
        return "ready_partial" if report.abstained or report.total_factual == 0 else "ready"

    def run_to_terminal(
        self,
        owner: str,
        job_id: str,
        *,
        provider: FakeProvider | None = None,
        worker: str | None = None,
        now: datetime | None = None,
    ) -> FakeJob:
        job = self.get(owner, job_id)
        for _ in range(4):
            if job.state.value in TERMINAL:
                break
            previous = job.revision
            job = self.advance(owner, job_id, provider=provider, worker=worker, now=now)
            if previous == job.revision:
                break
        return job

    @staticmethod
    def _unknown(conn: Any, row: tuple[Any, ...], data: dict[str, Any]) -> None:
        if data["steps"] and data["steps"][-1]["state"] == "running":
            step = data["steps"][-1]
            if not step["unknown_recorded"]:
                conn.execute(
                    "UPDATE workspace_fake_generation_reservations SET unknown_input=unknown_input+%s,unknown_output=unknown_output+%s,state='uncertain' WHERE job_id=%s",
                    (step["input_tokens"], row[5]["limits"]["per_call_output_tokens"], row[0]),
                )
                step["unknown_recorded"] = True

    def cancel(self, owner: str, job_id: str) -> FakeJob:
        self._owner(owner)
        with self.store.pool.connection() as conn:
            self._lock(conn, owner)
            row = self._row(conn, owner, job_id, lock=True)
            if row[2] in TERMINAL:
                return self._snapshot(conn, row)
            data = _copy(row[6])
            self._unknown(conn, row, data)
            conn.execute(
                "UPDATE workspace_fake_generation_jobs SET cancel_requested=TRUE WHERE id=%s",
                (job_id,),
            )
            self._save(conn, row, "cancelled", data, lease_owner=row[8], lease_until=row[9])
            self._settle(conn, job_id, "cancelled")
            return self._snapshot(conn, self._row(conn, owner, job_id))

    def _recover(self, conn: Any, row: tuple[Any, ...]) -> None:
        data = _copy(row[6])
        self._unknown(conn, row, data)
        if data["steps"] and data["steps"][-1]["state"] == "running":
            data["steps"][-1]["state"] = "interrupted"
            data["steps"][-1]["error"] = "worker_lost_inflight_completion"
        data["error"] = "worker_lost_inflight_completion"
        state = "cancelled" if row[7] else "interrupted"
        self._save(conn, row, state, data)
        self._settle(conn, row[0], state)

    def recover(self, owner: str, job_id: str, *, now: datetime | None = None) -> FakeJob:
        self._owner(owner)
        instant = _clock(self.store, now)
        with self.store.pool.connection() as conn:
            self._lock(conn, owner)
            row = self._row(conn, owner, job_id, lock=True)
            if row[9] is not None and row[9] <= instant:
                self._recover(conn, row)
            return self._snapshot(conn, self._row(conn, owner, job_id))
