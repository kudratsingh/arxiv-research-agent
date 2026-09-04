"""The append-only progress ledger and the honest views over it (WO-W07).

`01-LEARNING-AGENT.md` §4.4 states the shape this module implements:
progress is an **event log**, and everything a surface says about a
learner is a *view* over that log — derived, recomputable, and
traceable to evidence. "No displayed claim without an event behind
it" is the web tier's state-machine honesty rule ("the machine never
invents a stage") pointed at learning.

Three invariants carry the weight, and each is enforced somewhere a
future edit cannot quietly undo:

**1. Append-only.** There is no update path and no per-event delete
path — not on the Protocol, not on either implementation, not on the
HTTP surface. In Postgres a trigger refuses `UPDATE` outright and
refuses `DELETE` unless the connection has explicitly opted into an
account-level erasure (`erase_principal`), which exists only because
WO-W02's privacy promise has to cover this table too. Correcting a
recorded event means *appending* a correcting event; the wrong one
stays, because a ledger that can be rewritten is not evidence.
Appends are idempotent on `event_id`, so a retried write re-reads the
stored row instead of double-counting it.

**2. Every event links its evidence.** `evidence_ref` points at the
thing that happened — a session transcript, an artifact/job id, a
plan version. For `assessment` events it is *required and non-blank*
at the write boundary (`KINDS_REQUIRING_EVIDENCE`), mirroring 01
§4.3's rule that a judge asserting a gap without quoting the learner
is malformed. The views carry the `event_id`s behind every number
they report, so a count can always be expanded into the events that
produced it.

**3. No mastery percentage exists here.** 01 §4.1 allows three
currencies of progress — assessment events, repetition history, and
artifacts — and bans one: "You are 87% through Transformers" is a
claim about a latent variable no LLM judge can measure. This module
therefore has no field, no view, and no label that can render a
knowledge scalar. What it *does* expose is `schedule_progress`:
arithmetic about sessions ("3 of 12 sessions"), named so the surface
cannot mistake it for knowledge. The ban is structural in three
places — `BANNED_SCALAR_TOKENS` rejects such a key at the write
boundary at any depth, the `progress_events_no_mastery_scalar` CHECK
in `SCHEMA_DDL` rejects it in the database, and
`_SCHEDULE_LABEL_PATTERN` bounds what a label is allowed to say —
plus a named test (`TestNoMasteryPercentage` in
`tests/test_progress_events.py`), which is the row Gate W1's honesty
inventory cites.

The full 01 §4.4 kind vocabulary is reserved now so Phase L needs no
migration, but a kind with no producer in Phase W is *refused* rather
than silently accepted: reserving a name is cheap, accepting writes
for a feature that does not exist is not (see `RESERVED_KINDS`).

Storage follows the `ConversationStore` pattern (ADR 0032): a
Protocol with an in-memory implementation for tests and single-worker
dev, and a Postgres implementation where the structural guarantees
actually bite. `settings.progress_event_store` selects.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, get_args

from src.errors import InvalidProgressEvent
from src.observability import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

ProgressEventKind = Literal[
    "session_completed",
    "assessment",
    "review_item",
    "artifact_produced",
    "plan_approved",
    "replan",
]
"""The full 01 §4.4 vocabulary. Reserved in Phase W, not all writable."""

ALL_EVENT_KINDS: tuple[str, ...] = tuple(str(k) for k in get_args(ProgressEventKind))

WRITABLE_KINDS: frozenset[str] = frozenset(
    {"session_completed", "assessment", "artifact_produced"}
)
"""Kinds Phase W has a producer for.

`session_completed` and `assessment` come out of the guided-read
session (WO-W03/WO-W04); `artifact_produced` from an existing
research job. Everything else in `ProgressEventKind` is reserved.
"""

RESERVED_KINDS: frozenset[str] = frozenset(ALL_EVENT_KINDS) - WRITABLE_KINDS
"""Named in the schema, refused at the write boundary until a producer exists.

`review_item` waits on spaced repetition (01 §4.2, Phase L3);
`plan_approved` / `replan` wait on the curriculum planner (01 §2,
Phase L). Reserving the names costs nothing and saves a migration;
*accepting* writes for them would let a half-built feature seed the
ledger with events no view knows how to read.
"""

KINDS_REQUIRING_EVIDENCE: frozenset[str] = frozenset({"assessment"})
"""Kinds whose `evidence_ref` may not be absent or blank.

An assessment is a claim about a person. 01 §4.3 makes an
evidence-free claim malformed at the judge; this makes it
unstorable at the record.
"""

BANNED_SCALAR_TOKENS: tuple[str, ...] = (
    "master",
    "proficien",
    "competenc",
    "percent",
    "pct",
    "score",
    "knowledge_level",
    "skill_level",
)
"""Substrings that make a payload key read as a knowledge scalar (01 §4.1).

Matched case-insensitively against *keys* at any depth, never against
values — a learner who writes "I have not mastered this" in an
explain-back must still be storable; a field asserting they have 87%
of something must not be. The same list is mirrored into the
`progress_events_no_mastery_scalar` CHECK in
`src/tools/postgres_pool.py::SCHEMA_DDL`, and
`test_progress_events.py` asserts the two agree so the ban cannot
drift out of sync with the database.
"""

# Bounds on a single event. The payload is learner-derived data
# arriving over HTTP in Phase L; an unbounded JSONB blob is a storage
# and a read-amplification vector, and every view below walks it.
MAX_EVENT_ID_LEN = 64
MAX_EVIDENCE_REF_LEN = 256
MAX_PAYLOAD_BYTES = 16_384
MAX_PAYLOAD_DEPTH = 6

# Pagination contract, matching `ConversationStore` (ADR 0043): the
# route clamps, the store honors what it is handed.
DEFAULT_EVENT_LIMIT = 500
MAX_EVENT_LIMIT = 2_000

# A schedule label is arithmetic about sessions and nothing else. The
# pattern is asserted in the honesty test, so no future edit can widen
# the label into "87% complete" without failing a named check.
_SCHEDULE_LABEL_PATTERN = re.compile(r"^\d+ of \d+ sessions$|^\d+ sessions? recorded$")

_ISO_UTC_SUFFIX = "Z"


class ProgressEventRejected(InvalidProgressEvent, ValueError):
    """A write the ledger refuses.

    Raised at the write boundary — before anything reaches a store —
    so the in-memory and Postgres implementations refuse identically
    and the caller gets the same message either way.

    ADR 0064 gives it the code `invalid_progress_event` and keeps the
    `ValueError` mixin: `_parse_ts` below catches `ValueError` around
    `datetime.fromisoformat` and re-raises as this class, which stops
    working the moment this stops being a `ValueError`.
    """


# ---------------------------------------------------------------------------
# The event
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProgressEvent:
    """One recorded fact about a learner (01 §4.4).

    Frozen: an event that has been appended is history. `payload` is
    still a mutable dict at the type level, which is why `new_event`
    deep-copies what it is handed and the stores return rebuilt
    instances rather than shared references.

    `principal_key_id` rather than 01's `learner_id` — SR-02 keys the
    Phase W stores on the existing API principal (ADR 0036) and is
    honest that this is the single-human/pilot slice, not MT-01.
    """

    event_id: str
    principal_key_id: str
    ts: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    evidence_ref: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        """Plain-dict form, used by the fixtures and the API layer."""
        return {
            "event_id": self.event_id,
            "principal_key_id": self.principal_key_id,
            "ts": self.ts,
            "kind": self.kind,
            "payload": json.loads(json.dumps(self.payload)),
            "evidence_ref": self.evidence_ref,
        }

    @classmethod
    def from_json_dict(cls, raw: Mapping[str, Any]) -> ProgressEvent:
        """Rebuild an event from its plain-dict form.

        The recomputability test drives the views from a raw fixture
        through this constructor, so the fixture is the log and not a
        pre-digested view.
        """
        payload = raw.get("payload") or {}
        if not isinstance(payload, dict):
            raise ProgressEventRejected("payload must be a JSON object")
        evidence_ref = raw.get("evidence_ref")
        return cls(
            event_id=str(raw["event_id"]),
            principal_key_id=str(raw["principal_key_id"]),
            ts=str(raw["ts"]),
            kind=str(raw["kind"]),
            payload=dict(payload),
            evidence_ref=None if evidence_ref is None else str(evidence_ref),
        )


def new_event_id() -> str:
    return uuid.uuid4().hex[:16]


def utc_now_iso() -> str:
    """`ts` for an event happening now, in the ledger's canonical form."""
    return normalize_ts(datetime.now(UTC))


def normalize_ts(value: str | datetime) -> str:
    """Canonical `ts`: microsecond-precision UTC ISO-8601 with a `Z`.

    Every `ts` in the ledger goes through here, so the day bucketing
    in `summarize` is a pure string slice and the in-memory and
    Postgres stores round-trip to identical values. A naive datetime
    is read as UTC rather than as local time — a ledger whose day
    boundaries move with the server's timezone is not recomputable.

    Raises:
        ProgressEventRejected: When the value is not a parseable
            timestamp.
    """
    if isinstance(value, datetime):
        moment = value
    else:
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ProgressEventRejected(f"ts is not ISO-8601: {value!r}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (
        moment.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="microseconds")
        + _ISO_UTC_SUFFIX
    )


def _banned_token_in(key: str) -> str | None:
    lowered = key.lower()
    for token in BANNED_SCALAR_TOKENS:
        if token in lowered:
            return token
    return None


def _assert_no_mastery_scalar(payload: Mapping[str, Any], *, depth: int = 0) -> None:
    """Walk a payload and refuse any key that reads as a knowledge scalar.

    The DDL CHECK does the same job in the database; this exists so
    the in-memory store, the fixtures, and any future non-Postgres
    deployment refuse identically, and so the caller gets a message
    naming the offending key instead of a constraint violation.

    Raises:
        ProgressEventRejected: On a banned key, or on nesting past
            `MAX_PAYLOAD_DEPTH`.
    """
    if depth > MAX_PAYLOAD_DEPTH:
        raise ProgressEventRejected(
            f"payload nests deeper than {MAX_PAYLOAD_DEPTH} levels"
        )
    for key, value in payload.items():
        if not isinstance(key, str):
            raise ProgressEventRejected("payload keys must be strings")
        token = _banned_token_in(key)
        if token is not None:
            raise ProgressEventRejected(
                f"payload key {key!r} reads as a knowledge scalar "
                f"(contains {token!r}). 01 §4.1 bans mastery percentages: "
                "record the event and its evidence, and let the view do "
                "schedule arithmetic."
            )
        _assert_no_mastery_scalar_value(value, depth=depth + 1)


def _assert_no_mastery_scalar_value(value: Any, *, depth: int) -> None:
    if isinstance(value, Mapping):
        _assert_no_mastery_scalar(value, depth=depth)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_mastery_scalar_value(item, depth=depth)


def validate_event(event: ProgressEvent) -> ProgressEvent:
    """Check an event at the write boundary and return its canonical form.

    Every rule the ledger claims is checked here, in one place, before
    any store sees the event:

    - a resolvable owner (`principal_key_id`) — the ledger has no
      anonymous rows, so an auth-off deployment cannot write one;
    - a kind from the 01 §4.4 vocabulary that Phase W has a producer
      for (`RESERVED_KINDS` are refused, not silently accepted);
    - `evidence_ref` present and non-blank for the kinds that assert
      something about a person;
    - a JSON-serializable, bounded payload with no key that reads as
      a knowledge scalar;
    - a normalized `ts`.

    Raises:
        ProgressEventRejected: On any of the above.
    """
    if not event.event_id or len(event.event_id) > MAX_EVENT_ID_LEN:
        raise ProgressEventRejected(
            f"event_id must be 1..{MAX_EVENT_ID_LEN} characters"
        )
    if not event.principal_key_id.strip():
        raise ProgressEventRejected(
            "progress events are always owned: principal_key_id is required. "
            "The ledger has no anonymous rows (SR-02 / ADR 0036)."
        )
    if event.kind not in ALL_EVENT_KINDS:
        raise ProgressEventRejected(
            f"unknown kind {event.kind!r}; expected one of "
            f"{', '.join(sorted(ALL_EVENT_KINDS))}"
        )
    if event.kind in RESERVED_KINDS:
        raise ProgressEventRejected(
            f"kind {event.kind!r} is reserved in Phase W: the schema names it "
            "so Phase L needs no migration, but nothing produces it yet and a "
            "ledger row no view can read is not evidence."
        )
    evidence_ref = event.evidence_ref
    if evidence_ref is not None:
        evidence_ref = evidence_ref.strip() or None
        if evidence_ref is not None and len(evidence_ref) > MAX_EVIDENCE_REF_LEN:
            raise ProgressEventRejected(
                f"evidence_ref exceeds {MAX_EVIDENCE_REF_LEN} characters"
            )
    if event.kind in KINDS_REQUIRING_EVIDENCE and evidence_ref is None:
        raise ProgressEventRejected(
            f"kind {event.kind!r} requires a resolvable evidence_ref: an "
            "assessment without the transcript behind it is a claim, not a "
            "record (01 §4.3)."
        )

    try:
        encoded = json.dumps(event.payload, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ProgressEventRejected(f"payload is not JSON-serializable: {exc}") from exc
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ProgressEventRejected(
            f"payload exceeds {MAX_PAYLOAD_BYTES} bytes"
        )
    _assert_no_mastery_scalar(event.payload)

    return ProgressEvent(
        event_id=event.event_id,
        principal_key_id=event.principal_key_id,
        ts=normalize_ts(event.ts),
        kind=event.kind,
        payload=json.loads(encoded),
        evidence_ref=evidence_ref,
    )


def new_event(
    *,
    principal_key_id: str,
    kind: str,
    evidence_ref: str | None = None,
    payload: Mapping[str, Any] | None = None,
    ts: str | datetime | None = None,
    event_id: str | None = None,
) -> ProgressEvent:
    """Build a validated event. The only sanctioned way to make one.

    Args:
        principal_key_id: Owner (ADR 0036). Required — there are no
            anonymous rows.
        kind: One of `WRITABLE_KINDS`.
        evidence_ref: The session / artifact / plan this event points
            at. Required for `KINDS_REQUIRING_EVIDENCE`.
        payload: Kind-specific detail. Deep-copied; no key may read as
            a knowledge scalar.
        ts: Defaults to now, normalized to UTC.
        event_id: Supply one to make a retried append idempotent;
            defaults to a fresh id.

    Raises:
        ProgressEventRejected: See `validate_event`.
    """
    return validate_event(
        ProgressEvent(
            event_id=event_id or new_event_id(),
            principal_key_id=principal_key_id,
            kind=kind,
            ts=normalize_ts(ts) if ts is not None else utc_now_iso(),
            payload=dict(payload or {}),
            evidence_ref=evidence_ref,
        )
    )


# ---------------------------------------------------------------------------
# Views — pure functions of the log, and nothing else
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailySessionCount:
    """Sessions a learner completed on one UTC day, with the events behind it."""

    day: str
    sessions: int
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class PathScheduleProgress:
    """Schedule arithmetic for one path. **Not** a knowledge claim.

    `sessions_completed` counts `session_completed` events; the
    planned total is whatever the path last declared. `schedule_label`
    is the only rendered string in this module and is constrained to
    session arithmetic — 01 §4.1 permits "14 of 21 sessions in this
    milestone complete" precisely because it is arithmetic about
    sessions, and requires it be labeled as schedule progress rather
    than knowledge. The field name is `schedule_progress` on the
    summary for the same reason.

    `assessments_recorded` is a count of events, not a grade. An
    absent assessment means unobserved (`00` §5.4) — the view never
    fills the gap with a guess.
    """

    path_id: str
    sessions_completed: int
    sessions_planned: int | None
    schedule_label: str
    assessments_recorded: int
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResourceObservation:
    """Session events that name one concrete resource on a path.

    This is the only view a path surface may use to mark a paper as
    observed. A path-level session count cannot identify a paper and is
    therefore insufficient evidence for a paper-position claim.
    """

    path_id: str
    resource_id: str
    sessions_completed: int
    last_observed_at: str
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceRecord:
    """One event, reduced to the fact it records and what proves it.

    Deliberately carries no verdict field. 01 §4.3 keeps the judge's
    output as advice to the tutor rather than a score shown to the
    learner, so the ledger's public view of an assessment is *that it
    happened*, *when*, and *what transcript backs it*.
    """

    event_id: str
    ts: str
    kind: str
    evidence_ref: str | None
    path_id: str | None


@dataclass(frozen=True)
class ProgressSummary:
    """The whole displayable progress record, derived from events alone.

    Recomputable by construction: `summarize` is a pure function of
    the event list, independent of the order it arrives in, with no
    clock and no store access. Rebuilding this from a raw event log
    and getting the identical object back is the property test behind
    "no displayed claim without an event behind it" (01 §4.4).
    """

    principal_key_id: str
    event_count: int
    sessions_per_day: tuple[DailySessionCount, ...]
    schedule_progress: tuple[PathScheduleProgress, ...]
    resource_observations: tuple[ResourceObservation, ...]
    assessments: tuple[EvidenceRecord, ...]
    artifacts: tuple[EvidenceRecord, ...]


def _schedule_label(completed: int, planned: int | None) -> str:
    """Render the one string this module produces.

    Two forms and no third: session arithmetic when the path declared a
    length, a bare count when it did not. `_SCHEDULE_LABEL_PATTERN`
    pins both, so a percentage cannot be added here without failing a
    named test.
    """
    if planned is not None:
        return f"{completed} of {planned} sessions"
    noun = "session" if completed == 1 else "sessions"
    return f"{completed} {noun} recorded"


def _payload_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _payload_positive_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    # `bool` is an `int` subclass; a flag is not a session count.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def summarize(
    principal_key_id: str, events: Iterable[ProgressEvent]
) -> ProgressSummary:
    """Fold a principal's events into the displayable summary.

    Pure and order-independent: events are sorted internally, nothing
    consults the clock, and no field is populated from anywhere but
    the events themselves. Events belonging to another principal are
    dropped rather than counted — a view is never wider than its
    owner's log.

    Every number carries its provenance: `event_ids` on each bucket
    holds exactly the events that produced the count, so a surface can
    always expand "3 sessions" into the three events, and a test can
    assert the count equals the number of ids.
    """
    owned = sorted(
        (e for e in events if e.principal_key_id == principal_key_id),
        key=lambda e: (e.ts, e.event_id),
    )

    by_day: dict[str, list[str]] = {}
    path_sessions: dict[str, list[str]] = {}
    path_planned: dict[str, int] = {}
    path_assessments: dict[str, int] = {}
    resource_events: dict[tuple[str, str], list[ProgressEvent]] = {}
    assessments: list[EvidenceRecord] = []
    artifacts: list[EvidenceRecord] = []

    for event in owned:
        path_id = _payload_str(event.payload, "path_id")
        if event.kind == "session_completed":
            by_day.setdefault(event.ts[:10], []).append(event.event_id)
            if path_id is not None:
                path_sessions.setdefault(path_id, []).append(event.event_id)
                planned = _payload_positive_int(event.payload, "sessions_planned")
                if planned is not None:
                    # Last declaration wins, not the largest: a path
                    # that was re-scoped shorter must not keep
                    # advertising its old length.
                    path_planned[path_id] = planned
                resource_id = _payload_str(event.payload, "resource_id")
                if resource_id is not None:
                    resource_events.setdefault((path_id, resource_id), []).append(event)
        elif event.kind == "assessment":
            assessments.append(
                EvidenceRecord(
                    event_id=event.event_id,
                    ts=event.ts,
                    kind=event.kind,
                    evidence_ref=event.evidence_ref,
                    path_id=path_id,
                )
            )
            if path_id is not None:
                path_assessments[path_id] = path_assessments.get(path_id, 0) + 1
        elif event.kind == "artifact_produced":
            artifacts.append(
                EvidenceRecord(
                    event_id=event.event_id,
                    ts=event.ts,
                    kind=event.kind,
                    evidence_ref=event.evidence_ref,
                    path_id=path_id,
                )
            )

    # A path that has been assessed but never sat still gets a row:
    # "0 sessions recorded" with one assessment against it is a true
    # state, and dropping the row would hide it. The denominator stays
    # absent because only a session event ever declares one — the view
    # does not invent a length for a path nobody has started.
    for path_id in path_assessments:
        path_sessions.setdefault(path_id, [])

    sessions_per_day = tuple(
        DailySessionCount(day=day, sessions=len(ids), event_ids=tuple(ids))
        for day, ids in sorted(by_day.items())
    )
    schedule_progress = tuple(
        PathScheduleProgress(
            path_id=path_id,
            sessions_completed=len(ids),
            sessions_planned=path_planned.get(path_id),
            schedule_label=_schedule_label(len(ids), path_planned.get(path_id)),
            assessments_recorded=path_assessments.get(path_id, 0),
            event_ids=tuple(ids),
        )
        for path_id, ids in sorted(path_sessions.items())
    )
    resource_observations = tuple(
        ResourceObservation(
            path_id=path_id,
            resource_id=resource_id,
            sessions_completed=len(records),
            last_observed_at=records[-1].ts,
            event_ids=tuple(record.event_id for record in records),
        )
        for (path_id, resource_id), records in sorted(resource_events.items())
    )

    return ProgressSummary(
        principal_key_id=principal_key_id,
        event_count=len(owned),
        sessions_per_day=sessions_per_day,
        schedule_progress=schedule_progress,
        resource_observations=resource_observations,
        assessments=tuple(assessments),
        artifacts=tuple(artifacts),
    )


# ---------------------------------------------------------------------------
# Store Protocol — three methods, none of which edits an event
# ---------------------------------------------------------------------------

PUBLIC_STORE_METHODS: frozenset[str] = frozenset(
    {"append", "list_events", "erase_principal"}
)
"""The store's entire public surface, pinned so a test can guard it.

Adding a method means editing this set, which means a reviewer sees
it. There is deliberately no `update`, no `delete_event`, and no
`replace` — the honesty test asserts the implementations expose
exactly these three.
"""


class ProgressEventStore(Protocol):
    """Append-only storage for progress events. Safe under asyncio tasks."""

    async def append(self, event: ProgressEvent) -> ProgressEvent: ...

    async def list_events(
        self,
        principal_key_id: str,
        *,
        limit: int = DEFAULT_EVENT_LIMIT,
        offset: int = 0,
    ) -> list[ProgressEvent]: ...

    async def erase_principal(self, principal_key_id: str) -> int: ...


# ---------------------------------------------------------------------------
# InMemory implementation — default, single-worker, dies with the process.
# ---------------------------------------------------------------------------


class InMemoryProgressEventStore:
    """In-process ledger, mirroring `InMemoryConversationStore`'s shape.

    Same refusals as the Postgres store, enforced by the shared
    `validate_event`, so a test that passes here means the same thing
    it means against a real database — with the honest exception that
    the append-only *trigger* only exists in Postgres. Nothing here
    can be mutated through the public surface either way.
    """

    def __init__(self) -> None:
        self._events: dict[str, ProgressEvent] = {}
        self._lock = asyncio.Lock()

    async def append(self, event: ProgressEvent) -> ProgressEvent:
        validated = validate_event(event)
        async with self._lock:
            # Idempotent on `event_id`: a retried append re-reads the
            # stored row rather than overwriting it (which would be an
            # update) or double-counting it.
            existing = self._events.get(validated.event_id)
            if existing is not None:
                return existing
            self._events[validated.event_id] = validated
            return validated

    async def list_events(
        self,
        principal_key_id: str,
        *,
        limit: int = DEFAULT_EVENT_LIMIT,
        offset: int = 0,
    ) -> list[ProgressEvent]:
        async with self._lock:
            ordered = sorted(
                (
                    e
                    for e in self._events.values()
                    if e.principal_key_id == principal_key_id
                ),
                key=lambda e: (e.ts, e.event_id),
            )
            return ordered[offset : offset + limit]

    async def erase_principal(self, principal_key_id: str) -> int:
        """Account-level erasure — WO-W02's deletion promise, not an edit.

        Removes every event belonging to one principal. There is no
        way to remove *an* event; the unit of erasure is a person's
        whole record, which is the only deletion 01 §1.4 promises.
        """
        async with self._lock:
            doomed = [
                event_id
                for event_id, e in self._events.items()
                if e.principal_key_id == principal_key_id
            ]
            for event_id in doomed:
                del self._events[event_id]
            return len(doomed)


# ---------------------------------------------------------------------------
# Postgres implementation — durable, shared across workers.
# ---------------------------------------------------------------------------


class PostgresProgressEventStore:
    """The `progress_events` table via the ADR 0028 pool.

    Every `_run` closure opens with `init_schema()` so the bootstrap
    DDL runs on the `asyncio.to_thread` worker rather than the event
    loop — the ADR 0043 rule the conversation store follows.

    This is where the structural guarantees live: the append-only
    trigger, the assessment-needs-evidence CHECK, and the
    no-mastery-scalar CHECK are all in `SCHEMA_DDL`, so a `psql`
    session is held to the same rules this module is.
    """

    async def append(self, event: ProgressEvent) -> ProgressEvent:
        validated = validate_event(event)
        from src.tools.postgres_pool import _connection, init_schema

        payload_json = json.dumps(validated.payload, sort_keys=True)

        def _run() -> ProgressEvent:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                # `DO NOTHING` rather than `DO UPDATE`: a repeated
                # event_id is a retry, and the stored row wins. An
                # upsert here would be the update path this table
                # does not have.
                cur.execute(
                    """
                    INSERT INTO progress_events
                        (event_id, principal_key_id, ts, kind, payload,
                         evidence_ref)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (
                        validated.event_id,
                        validated.principal_key_id,
                        validated.ts,
                        validated.kind,
                        payload_json,
                        validated.evidence_ref,
                    ),
                )
                conn.commit()
                cur.execute(
                    """
                    SELECT event_id, principal_key_id, ts, kind, payload,
                           evidence_ref
                    FROM progress_events
                    WHERE event_id = %s
                    """,
                    (validated.event_id,),
                )
                row = cur.fetchone()
                if row is None:  # pragma: no cover - insert just succeeded
                    raise ProgressEventRejected(
                        f"append of {validated.event_id} did not persist"
                    )
                return _row_to_event(row)

        return await asyncio.to_thread(_run)

    async def list_events(
        self,
        principal_key_id: str,
        *,
        limit: int = DEFAULT_EVENT_LIMIT,
        offset: int = 0,
    ) -> list[ProgressEvent]:
        from src.tools.postgres_pool import _connection, init_schema

        def _run() -> list[ProgressEvent]:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                # Ascending, `event_id` tie-breaking equal timestamps:
                # the summary is order-independent, but a stable page
                # order keeps consecutive reads from skipping rows.
                cur.execute(
                    """
                    SELECT event_id, principal_key_id, ts, kind, payload,
                           evidence_ref
                    FROM progress_events
                    WHERE principal_key_id = %s
                    ORDER BY ts, event_id
                    LIMIT %s OFFSET %s
                    """,
                    (principal_key_id, limit, offset),
                )
                return [_row_to_event(row) for row in cur.fetchall()]

        return await asyncio.to_thread(_run)

    async def erase_principal(self, principal_key_id: str) -> int:
        """Account-level erasure — the one door through the append-only trigger.

        `SET LOCAL arxiv.progress_purge` is transaction-scoped, so the
        opt-in dies with this statement and an ordinary connection can
        still not delete a row. Nothing on the HTTP surface reaches
        here; it exists so WO-W02's deletion promise covers this table
        rather than stopping at the profile.
        """
        from src.tools.postgres_pool import _connection, init_schema

        def _run() -> int:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                cur.execute("SET LOCAL arxiv.progress_purge = 'on'")
                cur.execute(
                    "DELETE FROM progress_events WHERE principal_key_id = %s",
                    (principal_key_id,),
                )
                erased = int(cur.rowcount or 0)
                conn.commit()
                return erased

        erased = await asyncio.to_thread(_run)
        log.info(
            "progress_events_erased",
            extra={"erased_events": erased},
        )
        return erased


def _row_to_event(row: Sequence[Any]) -> ProgressEvent:
    payload = row[4]
    if isinstance(payload, str):  # pragma: no cover - psycopg returns dicts
        payload = json.loads(payload)
    return ProgressEvent(
        event_id=str(row[0]),
        principal_key_id=str(row[1]),
        ts=normalize_ts(row[2]),
        kind=str(row[3]),
        payload=dict(payload or {}),
        evidence_ref=None if row[5] is None else str(row[5]),
    )


# ---------------------------------------------------------------------------
# Factory — matches the ConversationStore pattern (ADR 0032).
# ---------------------------------------------------------------------------


def build_progress_event_store() -> ProgressEventStore:
    """Select the store from `settings.progress_event_store`.

    Lazy, so the Postgres pool is untouched when the in-memory
    variant is selected (which is the default, and what every
    flag-off deployment gets).
    """
    from src.config import settings

    if settings.progress_event_store == "postgres":
        return PostgresProgressEventStore()
    return InMemoryProgressEventStore()


__all__ = [
    "ALL_EVENT_KINDS",
    "BANNED_SCALAR_TOKENS",
    "DEFAULT_EVENT_LIMIT",
    "DailySessionCount",
    "EvidenceRecord",
    "InMemoryProgressEventStore",
    "KINDS_REQUIRING_EVIDENCE",
    "MAX_EVENT_LIMIT",
    "PUBLIC_STORE_METHODS",
    "PathScheduleProgress",
    "PostgresProgressEventStore",
    "ProgressEvent",
    "ProgressEventKind",
    "ProgressEventRejected",
    "ProgressEventStore",
    "ProgressSummary",
    "RESERVED_KINDS",
    "WRITABLE_KINDS",
    "build_progress_event_store",
    "new_event",
    "new_event_id",
    "normalize_ts",
    "summarize",
    "utc_now_iso",
]
