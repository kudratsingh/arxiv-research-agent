"""Learner-lite profile model + store, with provenance on every claim.

The learner profile is the first *personal* record this repo keeps
(jobs and conversations are about papers; this is about a person), and
the honesty rules that govern it are the reason the module is shaped
the way it is. Three of them are structural rather than advisory:

1. **Provenance is non-nullable.** `SkillEntry.source` has no default
   and no `None` member — a claim that does not say where it came from
   cannot be constructed, cannot be deserialised, and cannot be stored
   (the `learner_profiles` CHECK constraints in
   `src/tools/postgres_pool.py::SCHEMA_DDL` refuse it at rest too).
2. **An inference can never overwrite a declaration.** Entries are
   keyed by `(skill, source)`, so a `declared` row and a contradicting
   `assessed` row coexist as two claims. `merge_skill_entries` cannot
   address the declared row from a non-declared write, and
   `replace_declared_skills` — the only path the HTTP surface reaches
   — cannot produce a non-declared entry.
3. **Confidence is bounded by provenance.** `declared` is exactly
   `1.0` and nothing else may reach `1.0`; `inferred` is capped at
   `INFERRED_MAX_CONFIDENCE`; `assessed` sits strictly between. Every
   non-declared claim must carry a non-empty `evidence_ref`, so an
   inference always has something reviewable attached to it.

Storage follows the conversation-store pattern (ADR 0032/0043): a
`ProfileStore` Protocol with an in-memory implementation for
single-worker/dev and a Postgres implementation on the shared pool,
selected by `settings.learner_profile_store`. Every Postgres `_run`
closure opens with `init_schema()` on the `asyncio.to_thread` worker so
the bootstrap DDL never executes on the event loop.

See ADR 0058 and `planning/07-learning-platform/01-LEARNING-AGENT.md`
§1.1-1.4.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Final, Literal, Protocol

from src.observability import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Controlled vocabularies. `Literal` rather than `str` for the same
# reason ADR 0046 gives for the config enums: a typo dies at the
# boundary instead of selecting a downstream fallback.
# ---------------------------------------------------------------------------

SkillSource = Literal["declared", "inferred", "assessed"]
SKILL_SOURCES: Final[tuple[SkillSource, ...]] = (
    "declared",
    "inferred",
    "assessed",
)

SkillLevel = Literal["none", "aware", "working", "solid"]
SKILL_LEVELS: Final[tuple[SkillLevel, ...]] = (
    "none",
    "aware",
    "working",
    "solid",
)

GoalStatus = Literal["active", "paused", "reached", "abandoned"]
GOAL_STATUSES: Final[tuple[GoalStatus, ...]] = (
    "active",
    "paused",
    "reached",
    "abandoned",
)

AcademicLevel = Literal[
    "", "self-taught", "undergrad", "grad", "postdoc", "industry"
]
ACADEMIC_LEVELS: Final[tuple[AcademicLevel, ...]] = (
    "",
    "self-taught",
    "undergrad",
    "grad",
    "postdoc",
    "industry",
)

# ---------------------------------------------------------------------------
# Bounds. Every one of these is also expressed in the DDL, and
# `tests/test_learner_profile_store.py` asserts the two agree — a cap
# that drifts between Python and Postgres is a cap that isn't enforced.
# ---------------------------------------------------------------------------

MAX_SKILL_ENTRIES: Final = 40
MAX_GOALS: Final = 8
MAX_SKILL_NAME_LEN: Final = 64
MAX_GOAL_STATEMENT_LEN: Final = 300
MAX_GOAL_ID_LEN: Final = 32
MAX_EVIDENCE_REF_LEN: Final = 128
MAX_PROFILE_NOTE_LEN: Final = 1_000
MAX_TIME_BUDGET_MIN_PER_DAY: Final = 1_440

# 01 §1.2: inference is capped so a guess can never present itself as
# near-certainty, and 1.0 is reserved for what the learner actually
# said. Both numbers are load-bearing — see the CHECK constraints.
INFERRED_MAX_CONFIDENCE: Final = 0.6
DECLARED_CONFIDENCE: Final = 1.0

# Skill names are a controlled vocabulary (01 §1.1) *and* a control-
# plane field: they are rendered into prompts and read back by the
# tutor. Restricting them to a slug shape means a skill name can never
# carry a sentence, a newline, or a tag — ADR 0020's lesson applied at
# the store boundary rather than in the prompt.
_SKILL_NAME_RE: Final = re.compile(r"^[a-z0-9][a-z0-9+./-]*(?: [a-z0-9+./-]+)*$")

# Evidence refs point at a session, assessment, or artifact id. Same
# reasoning: a short opaque token, never prose.
_EVIDENCE_REF_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]*$")

# Session summaries are lossy coaching memory, never primary evidence. Kept
# local rather than imported from ``learning.memory`` to avoid a store <-
# serializer <- store cycle; the exact prefix is pinned by WO-W05 tests.
_SUMMARY_EVIDENCE_PREFIX: Final = "summary:"

# ISO date, or "" for open-ended (01 §1.1's `LearnerGoal.target_date`).
_ISO_DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_GOAL_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ProvenanceError(ValueError):
    """A skill claim violates the declared/inferred/assessed rules.

    Raised at construction, at deserialisation, and at merge — the
    three doors into the store — so an offending claim never reaches
    a row, a prompt, or a response body.
    """


class AnonymousPrincipalError(ValueError):
    """A profile operation was attempted without a named principal.

    `enable_learner_profile` already refuses to load without
    `enable_api_auth` (see `src/config.py`), so this is the store's own
    belt-and-braces: 01 §1.3's "refuses to run against the anonymous
    principal", enforced where the write happens.
    """


def _require_principal_key_id(principal_key_id: str | None) -> str:
    """Return a non-empty principal key id or refuse the operation.

    Args:
        principal_key_id: Caller's `ApiKeyPrincipal.key_id`, or `None`
            under auth-off.

    Returns:
        The key id, guaranteed non-empty.

    Raises:
        AnonymousPrincipalError: When the caller has no named
            principal.
    """
    if not principal_key_id:
        raise AnonymousPrincipalError(
            "learner profiles are per-principal; the anonymous principal "
            "has none. Enable `enable_api_auth` and present an API key."
        )
    return principal_key_id


def utc_now_iso() -> str:
    """Current UTC instant as a second-precision ISO-8601 string.

    Second precision (not microsecond) because the value is rendered
    into prompts and compared in tests; sub-second noise buys nothing
    and makes fixtures unstable.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_skill_name(raw: str) -> str:
    """Fold a skill name to its controlled-vocabulary form.

    Lowercases, collapses runs of spaces and tabs, and strips the ends,
    so `" Back-Prop "` and `"back-prop"` are the same claim rather than
    two rows that quietly disagree.

    Interior newlines are deliberately *not* collapsed: a name with a
    line break is not a vocabulary term, and rewriting it into one
    would turn a rejection into a silent mutation. It survives here and
    fails `_SKILL_NAME_RE` in the next breath.
    """
    return re.sub(r"[ \t]+", " ", raw.strip().lower())


@dataclass(frozen=True, slots=True)
class SkillEntry:
    """One skill claim, with where it came from attached.

    `source` deliberately has no default: a caller that forgets it
    gets a `TypeError` from the dataclass rather than a silently
    unlabelled claim. Frozen because a claim is a record of something
    that happened, not a mutable opinion — a new opinion is a new
    entry (01 §1.2).

    Attributes:
        skill: Controlled-vocabulary name, normalised on construction.
        level: One of `SKILL_LEVELS`.
        source: One of `SKILL_SOURCES`. Non-nullable, no default.
        evidence_ref: Session / assessment / artifact id backing the
            claim. Empty for `declared` (a declaration cites only
            itself); required for `inferred` and `assessed`.
        confidence: `1.0` for `declared`; `(0, 0.6]` for `inferred`;
            `(0, 1.0)` for `assessed`.
        updated_at: ISO-8601 UTC timestamp of the claim.
    """

    skill: str
    level: SkillLevel
    source: SkillSource
    evidence_ref: str
    confidence: float
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        # Frozen dataclass: normalisation goes through `object` so the
        # stored value is the canonical one and downstream code never
        # has to re-normalise before comparing.
        object.__setattr__(self, "skill", normalize_skill_name(self.skill))
        _validate_skill_entry(self)

    @property
    def key(self) -> tuple[str, SkillSource]:
        """Identity of the claim: `(skill, source)`.

        This tuple is the whole "no silent overwrite" mechanism. Two
        claims about the same skill from different sources have
        different keys, so a contradicting inference lands *beside*
        the declaration instead of on top of it.
        """
        return (self.skill, self.source)

    def to_mapping(self) -> dict[str, Any]:
        """JSON-serialisable form, as stored in the `skills` JSONB."""
        return {
            "skill": self.skill,
            "level": self.level,
            "source": self.source,
            "evidence_ref": self.evidence_ref,
            "confidence": self.confidence,
            "updated_at": self.updated_at,
        }


def _validate_skill_entry(entry: SkillEntry) -> None:
    """Enforce every provenance rule on one claim.

    Raises:
        ProvenanceError: On any violation. The message names the rule
            so a failure in a batched inference write is diagnosable
            without a debugger.
    """
    if entry.source not in SKILL_SOURCES:
        raise ProvenanceError(
            f"skill {entry.skill!r}: source must be one of "
            f"{list(SKILL_SOURCES)}, got {entry.source!r}"
        )
    if entry.level not in SKILL_LEVELS:
        raise ProvenanceError(
            f"skill {entry.skill!r}: level must be one of "
            f"{list(SKILL_LEVELS)}, got {entry.level!r}"
        )
    if not entry.skill or len(entry.skill) > MAX_SKILL_NAME_LEN:
        raise ProvenanceError(
            f"skill name must be 1..{MAX_SKILL_NAME_LEN} characters, got "
            f"{len(entry.skill)}"
        )
    if not _SKILL_NAME_RE.match(entry.skill):
        raise ProvenanceError(
            f"skill {entry.skill!r} is not a controlled-vocabulary term "
            "(lowercase words of letters, digits, and + . / - only)"
        )
    if not isinstance(entry.confidence, (int, float)) or isinstance(
        entry.confidence, bool
    ):
        raise ProvenanceError(
            f"skill {entry.skill!r}: confidence must be a number"
        )
    if not math.isfinite(entry.confidence):
        raise ProvenanceError(
            f"skill {entry.skill!r}: confidence must be finite"
        )
    if entry.confidence <= 0.0 or entry.confidence > DECLARED_CONFIDENCE:
        raise ProvenanceError(
            f"skill {entry.skill!r}: confidence must be in (0.0, 1.0], got "
            f"{entry.confidence}"
        )

    if entry.source == "declared":
        # 1.0 is reserved for declarations, and a declaration is
        # nothing *but* 1.0 — the learner said it, so the record's
        # confidence in "they said it" is total. Anything else would
        # be the system quietly doubting the learner in a column.
        if entry.confidence != DECLARED_CONFIDENCE:
            raise ProvenanceError(
                f"skill {entry.skill!r}: declared claims carry "
                f"confidence {DECLARED_CONFIDENCE}, got {entry.confidence}"
            )
        if entry.evidence_ref:
            raise ProvenanceError(
                f"skill {entry.skill!r}: a declared claim cites only "
                "itself; evidence_ref must be empty"
            )
        return

    # Everything below applies to `inferred` and `assessed`.
    if entry.confidence >= DECLARED_CONFIDENCE:
        raise ProvenanceError(
            f"skill {entry.skill!r}: confidence {DECLARED_CONFIDENCE} is "
            f"reserved for declared claims, got {entry.confidence} on a "
            f"{entry.source} claim"
        )
    if entry.source == "inferred" and entry.confidence > INFERRED_MAX_CONFIDENCE:
        raise ProvenanceError(
            f"skill {entry.skill!r}: inferred claims are capped at "
            f"confidence {INFERRED_MAX_CONFIDENCE}, got {entry.confidence}"
        )
    if not entry.evidence_ref:
        raise ProvenanceError(
            f"skill {entry.skill!r}: a {entry.source} claim must carry an "
            "evidence_ref pointing at the session or assessment behind it"
        )
    if len(entry.evidence_ref) > MAX_EVIDENCE_REF_LEN:
        raise ProvenanceError(
            f"skill {entry.skill!r}: evidence_ref exceeds "
            f"{MAX_EVIDENCE_REF_LEN} characters"
        )
    if not _EVIDENCE_REF_RE.match(entry.evidence_ref):
        raise ProvenanceError(
            f"skill {entry.skill!r}: evidence_ref {entry.evidence_ref!r} is "
            "not an id-shaped token"
        )
    if entry.evidence_ref.startswith(_SUMMARY_EVIDENCE_PREFIX):
        raise ProvenanceError(
            f"skill {entry.skill!r}: a lossy session summary cannot be a "
            "skill-claim evidence_ref; cite the session or assessment event"
        )


def _validate_timestamp(value: str, *, what: str) -> None:
    """Reject a non-ISO timestamp before it reaches a prompt."""
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProvenanceError(
            f"{what} must be an ISO-8601 timestamp, got {value!r}"
        ) from exc


def skill_entry_from_mapping(raw: Any) -> SkillEntry:
    """Rebuild a `SkillEntry` from stored JSON, refusing bad provenance.

    The deserialisation door. A legacy or hand-edited row missing
    `source` raises rather than defaulting to anything — there is no
    honest default for "where did this claim come from".

    Args:
        raw: One element of the `skills` JSONB array.

    Returns:
        The validated entry.

    Raises:
        ProvenanceError: On a non-mapping, a missing key, or any
            violated provenance rule.
    """
    if not isinstance(raw, dict):
        raise ProvenanceError(
            f"skill claim must be an object, got {type(raw).__name__}"
        )
    missing = [
        key
        for key in ("skill", "level", "source", "evidence_ref", "confidence")
        if key not in raw
    ]
    if missing:
        raise ProvenanceError(
            f"skill claim is missing required field(s): {missing}. "
            "Provenance is not nullable."
        )
    updated_at = raw.get("updated_at") or utc_now_iso()
    if not isinstance(updated_at, str):
        raise ProvenanceError("skill claim `updated_at` must be a string")
    _validate_timestamp(updated_at, what="skill claim `updated_at`")
    return SkillEntry(
        skill=str(raw["skill"]),
        level=raw["level"],
        source=raw["source"],
        evidence_ref=str(raw["evidence_ref"]),
        confidence=float(raw["confidence"]),
        updated_at=updated_at,
    )


def new_goal_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass(frozen=True, slots=True)
class LearnerGoal:
    """One thing the learner is trying to reach.

    Goals have no `source` column on purpose: in Phase W a goal is
    always something the learner stated. Nothing in this package
    writes a goal the learner did not author, so a provenance field
    would have exactly one value and would invite a second one later
    without the surrounding honesty rules a skill claim gets.
    """

    goal_id: str
    statement: str
    target_date: str = ""
    status: GoalStatus = "active"
    priority: int = 3

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement", " ".join(self.statement.split()))
        if not self.goal_id or len(self.goal_id) > MAX_GOAL_ID_LEN:
            raise ValueError(
                f"goal_id must be 1..{MAX_GOAL_ID_LEN} characters"
            )
        if not _GOAL_ID_RE.match(self.goal_id):
            raise ValueError(f"goal_id {self.goal_id!r} is not id-shaped")
        if not self.statement:
            raise ValueError("goal statement must not be empty")
        if len(self.statement) > MAX_GOAL_STATEMENT_LEN:
            raise ValueError(
                f"goal statement exceeds {MAX_GOAL_STATEMENT_LEN} characters"
            )
        if self.status not in GOAL_STATUSES:
            raise ValueError(
                f"goal status must be one of {list(GOAL_STATUSES)}, got "
                f"{self.status!r}"
            )
        if self.target_date and not _ISO_DATE_RE.match(self.target_date):
            raise ValueError(
                "goal target_date must be an ISO date (YYYY-MM-DD) or empty, "
                f"got {self.target_date!r}"
            )
        if not 1 <= self.priority <= 5:
            raise ValueError(
                f"goal priority must be 1..5, got {self.priority}"
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "statement": self.statement,
            "target_date": self.target_date,
            "status": self.status,
            "priority": self.priority,
        }


def goal_from_mapping(raw: Any) -> LearnerGoal:
    """Rebuild a `LearnerGoal` from stored JSON."""
    if not isinstance(raw, dict):
        raise ValueError(f"goal must be an object, got {type(raw).__name__}")
    return LearnerGoal(
        goal_id=str(raw.get("goal_id") or new_goal_id()),
        statement=str(raw.get("statement", "")),
        target_date=str(raw.get("target_date", "")),
        status=raw.get("status", "active"),
        priority=int(raw.get("priority", 3)),
    )


@dataclass(frozen=True)
class LearnerProfile:
    """The whole per-principal record.

    Deliberately smaller than 01 §1.1's sketch: no `style_signals`
    (§7 of the Phase W plan defers it) and no `preferred_days`. Every
    field here is a field the deletion promise in ADR 0058 has to
    cover, which is the argument for keeping the set minimal.
    """

    principal_key_id: str
    academic_level: AcademicLevel = ""
    time_budget_min_per_day: int = 0
    goals: tuple[LearnerGoal, ...] = ()
    skills: tuple[SkillEntry, ...] = ()
    profile_note: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        _require_principal_key_id(self.principal_key_id)
        if self.academic_level not in ACADEMIC_LEVELS:
            raise ValueError(
                f"academic_level must be one of {list(ACADEMIC_LEVELS)}, got "
                f"{self.academic_level!r}"
            )
        if not 0 <= self.time_budget_min_per_day <= MAX_TIME_BUDGET_MIN_PER_DAY:
            raise ValueError(
                "time_budget_min_per_day must be "
                f"0..{MAX_TIME_BUDGET_MIN_PER_DAY}, got "
                f"{self.time_budget_min_per_day}"
            )
        if len(self.goals) > MAX_GOALS:
            raise ValueError(
                f"a profile holds at most {MAX_GOALS} goals, got "
                f"{len(self.goals)}"
            )
        if len(self.skills) > MAX_SKILL_ENTRIES:
            raise ValueError(
                f"a profile holds at most {MAX_SKILL_ENTRIES} skill claims, "
                f"got {len(self.skills)}"
            )
        if len(self.profile_note) > MAX_PROFILE_NOTE_LEN:
            raise ValueError(
                f"profile_note exceeds {MAX_PROFILE_NOTE_LEN} characters"
            )
        goal_ids = [g.goal_id for g in self.goals]
        if len(set(goal_ids)) != len(goal_ids):
            raise ValueError("goal_id values must be unique within a profile")
        keys = [entry.key for entry in self.skills]
        if len(set(keys)) != len(keys):
            # Two rows with the same `(skill, source)` would make
            # "which claim is current" ambiguous, which is the same
            # class of dishonesty as a missing source.
            raise ProvenanceError(
                "skill claims must be unique per (skill, source); "
                "duplicates found"
            )

    def skills_by_source(self, source: SkillSource) -> tuple[SkillEntry, ...]:
        """Every claim with the given provenance, name-ordered."""
        return tuple(
            sorted(
                (entry for entry in self.skills if entry.source == source),
                key=lambda entry: entry.skill,
            )
        )


def merge_skill_entries(
    existing: tuple[SkillEntry, ...],
    incoming: tuple[SkillEntry, ...],
) -> tuple[SkillEntry, ...]:
    """Fold new claims into an existing set without losing declarations.

    The rules, all of which have named tests:

    - Claims are keyed by `(skill, source)`. A same-key write replaces
      (a newer inference supersedes an older inference about the same
      skill); a different-source write is *added*, so an `assessed`
      contradiction of a `declared` claim is stored as a second entry
      and the tension is surfaced in conversation, never resolved by
      a silent downgrade in a database (01 §1.2).
    - Over `MAX_SKILL_ENTRIES`, the oldest `inferred` claims go first,
      then the oldest `assessed`. A `declared` claim is never evicted:
      what the learner said about themselves is the one thing the cap
      may not quietly delete. If the cap is still exceeded with
      declarations alone, the write is refused rather than trimmed.

    Args:
        existing: Current claims, already validated.
        incoming: Claims to fold in.

    Returns:
        The merged set, ordered by skill then source for stable
        serialisation.

    Raises:
        ProvenanceError: When the cap cannot be honoured without
            dropping a declaration.
    """
    merged: dict[tuple[str, SkillSource], SkillEntry] = {
        entry.key: entry for entry in existing
    }
    for entry in incoming:
        merged[entry.key] = entry

    if len(merged) > MAX_SKILL_ENTRIES:
        merged = _evict_to_cap(merged)

    return tuple(
        sorted(merged.values(), key=lambda entry: (entry.skill, entry.source))
    )


def _evict_to_cap(
    merged: dict[tuple[str, SkillSource], SkillEntry],
) -> dict[tuple[str, SkillSource], SkillEntry]:
    """Trim to `MAX_SKILL_ENTRIES`, guesses first, declarations never.

    Evicted `assessed` claims are recoverable: the progress event that
    produced them is the durable record (01 §4.4), and this store is a
    derived view of it.
    """
    overflow = len(merged) - MAX_SKILL_ENTRIES
    # Oldest-first within each evictable tier, `inferred` before
    # `assessed` — a guess is the cheapest thing to lose.
    evictable = sorted(
        (e for e in merged.values() if e.source != "declared"),
        key=lambda e: (0 if e.source == "inferred" else 1, e.updated_at, e.skill),
    )
    if len(evictable) < overflow:
        raise ProvenanceError(
            f"profile holds more than {MAX_SKILL_ENTRIES} declared skill "
            "claims; refusing to evict what the learner said about "
            "themselves. Remove declarations first."
        )
    for entry in evictable[:overflow]:
        del merged[entry.key]
        log.info(
            "learner_profile_skill_evicted",
            extra={"skill": entry.skill, "source": entry.source},
        )
    return merged


def replace_declared_skills(
    existing: tuple[SkillEntry, ...],
    declared: tuple[SkillEntry, ...],
) -> tuple[SkillEntry, ...]:
    """Swap the declared set, leaving evidence-backed claims alone.

    The write path `PUT /learn/profile` reaches. It is the *only*
    profile write a client can make, and it can neither create nor
    destroy an `inferred` or `assessed` claim: the learner edits what
    they said about themselves, and the system's own observations
    stand or fall on their evidence.

    Args:
        existing: Current claims.
        declared: The learner's full declared set after the edit.

    Returns:
        The merged claims.

    Raises:
        ProvenanceError: If `declared` contains a non-declared claim —
            the HTTP surface trying to forge provenance.
    """
    forged = [entry for entry in declared if entry.source != "declared"]
    if forged:
        raise ProvenanceError(
            "the profile edit surface may only write declared claims; got "
            f"{[e.source for e in forged]}"
        )
    kept = tuple(entry for entry in existing if entry.source != "declared")
    return merge_skill_entries(kept, tuple(declared))


# ---------------------------------------------------------------------------
# Store — Protocol + two implementations, the ADR 0032 shape.
# ---------------------------------------------------------------------------


class ProfileStore(Protocol):
    """Structural type for learner-profile storage.

    Every method takes the principal key id explicitly; there is no
    "current user" ambient state and no id the client supplies, so a
    caller cannot address another principal's profile by construction.
    That is why no `_check_ownership` call appears in the route layer
    for these endpoints — the ADR 0036 semantics are satisfied by the
    shape of the API rather than by a check that could be forgotten.
    """

    async def get(self, principal_key_id: str | None) -> LearnerProfile | None:
        ...

    async def put(self, profile: LearnerProfile) -> LearnerProfile: ...

    async def record_skill_entries(
        self,
        principal_key_id: str | None,
        entries: tuple[SkillEntry, ...],
    ) -> LearnerProfile | None: ...

    async def delete(self, principal_key_id: str | None) -> bool: ...


class InMemoryProfileStore:
    """Default store — single-worker, dies with the process."""

    def __init__(self) -> None:
        self._profiles: dict[str, LearnerProfile] = {}
        self._lock = asyncio.Lock()

    async def get(self, principal_key_id: str | None) -> LearnerProfile | None:
        key = _require_principal_key_id(principal_key_id)
        async with self._lock:
            return self._profiles.get(key)

    async def put(self, profile: LearnerProfile) -> LearnerProfile:
        key = _require_principal_key_id(profile.principal_key_id)
        async with self._lock:
            current = self._profiles.get(key)
            merged = replace_declared_skills(
                current.skills if current else (), profile.skills
            )
            stored = replace(
                profile,
                skills=merged,
                created_at=current.created_at if current else profile.created_at,
                updated_at=time.time(),
            )
            self._profiles[key] = stored
            return stored

    async def record_skill_entries(
        self,
        principal_key_id: str | None,
        entries: tuple[SkillEntry, ...],
    ) -> LearnerProfile | None:
        key = _require_principal_key_id(principal_key_id)
        async with self._lock:
            current = self._profiles.get(key)
            if current is None:
                return None
            stored = replace(
                current,
                skills=merge_skill_entries(current.skills, entries),
                updated_at=time.time(),
            )
            self._profiles[key] = stored
            return stored

    async def delete(self, principal_key_id: str | None) -> bool:
        key = _require_principal_key_id(principal_key_id)
        async with self._lock:
            return self._profiles.pop(key, None) is not None


class PostgresProfileStore:
    """`learner_profiles` on the shared pool from ADR 0028.

    Read/write under `asyncio.to_thread`, every closure opening with
    `init_schema()` so the DDL — pool open included — never runs on the
    event loop (the ADR 0043 lesson).
    """

    async def get(self, principal_key_id: str | None) -> LearnerProfile | None:
        key = _require_principal_key_id(principal_key_id)
        from src.tools.postgres_pool import _connection, init_schema

        def _run() -> LearnerProfile | None:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                cur.execute(_SELECT_SQL, (key,))
                row = cur.fetchone()
                return _profile_from_row(row) if row is not None else None

        return await asyncio.to_thread(_run)

    async def put(self, profile: LearnerProfile) -> LearnerProfile:
        key = _require_principal_key_id(profile.principal_key_id)
        from psycopg.types.json import Jsonb

        from src.tools.postgres_pool import _connection, init_schema

        def _run() -> LearnerProfile:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                # Lock the row for the rest of the transaction so two
                # concurrent edits cannot both read the same
                # evidence-backed set and write back divergent merges
                # (the `FOR UPDATE` pattern ADR 0043 uses for
                # conversation appends).
                cur.execute(
                    "SELECT skills, created_at FROM learner_profiles "
                    "WHERE principal_key_id = %s FOR UPDATE",
                    (key,),
                )
                existing_row = cur.fetchone()
                existing_skills: tuple[SkillEntry, ...] = ()
                if existing_row is not None:
                    existing_skills = tuple(
                        skill_entry_from_mapping(raw)
                        for raw in (existing_row[0] or [])
                    )
                merged = replace_declared_skills(existing_skills, profile.skills)
                cur.execute(
                    """
                    INSERT INTO learner_profiles
                        (principal_key_id, academic_level,
                         time_budget_min_per_day, goals, skills, profile_note)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (principal_key_id) DO UPDATE SET
                        academic_level = EXCLUDED.academic_level,
                        time_budget_min_per_day =
                            EXCLUDED.time_budget_min_per_day,
                        goals = EXCLUDED.goals,
                        skills = EXCLUDED.skills,
                        profile_note = EXCLUDED.profile_note,
                        updated_at = NOW()
                    RETURNING principal_key_id, academic_level,
                              time_budget_min_per_day, goals, skills,
                              profile_note, created_at, updated_at
                    """,
                    (
                        key,
                        profile.academic_level,
                        profile.time_budget_min_per_day,
                        Jsonb([goal.to_mapping() for goal in profile.goals]),
                        Jsonb([entry.to_mapping() for entry in merged]),
                        profile.profile_note,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                assert row is not None  # RETURNING on a completed upsert
                return _profile_from_row(row)

        return await asyncio.to_thread(_run)

    async def record_skill_entries(
        self,
        principal_key_id: str | None,
        entries: tuple[SkillEntry, ...],
    ) -> LearnerProfile | None:
        key = _require_principal_key_id(principal_key_id)
        from psycopg.types.json import Jsonb

        from src.tools.postgres_pool import _connection, init_schema

        def _run() -> LearnerProfile | None:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT skills FROM learner_profiles "
                    "WHERE principal_key_id = %s FOR UPDATE",
                    (key,),
                )
                row = cur.fetchone()
                if row is None:
                    # No profile means no learner to hold an opinion
                    # about. The caller (the end-of-session inference
                    # batch) treats `None` as "nothing to update".
                    return None
                current = tuple(
                    skill_entry_from_mapping(raw) for raw in (row[0] or [])
                )
                merged = merge_skill_entries(current, entries)
                cur.execute(
                    """
                    UPDATE learner_profiles
                    SET skills = %s, updated_at = NOW()
                    WHERE principal_key_id = %s
                    RETURNING principal_key_id, academic_level,
                              time_budget_min_per_day, goals, skills,
                              profile_note, created_at, updated_at
                    """,
                    (
                        Jsonb([entry.to_mapping() for entry in merged]),
                        key,
                    ),
                )
                updated = cur.fetchone()
                conn.commit()
                return _profile_from_row(updated) if updated else None

        return await asyncio.to_thread(_run)

    async def delete(self, principal_key_id: str | None) -> bool:
        key = _require_principal_key_id(principal_key_id)
        from src.tools.postgres_pool import _connection, init_schema

        def _run() -> bool:
            init_schema()
            with _connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM learner_profiles WHERE principal_key_id = %s",
                    (key,),
                )
                # `rowcount` on psycopg's cursor is typed loosely;
                # coerce to bool so mypy strict is happy.
                deleted: bool = bool(cur.rowcount and cur.rowcount > 0)
                conn.commit()
                return deleted

        return await asyncio.to_thread(_run)


_SELECT_SQL = """
SELECT principal_key_id, academic_level, time_budget_min_per_day,
       goals, skills, profile_note, created_at, updated_at
FROM learner_profiles
WHERE principal_key_id = %s
"""


def _profile_from_row(row: Any) -> LearnerProfile:
    """Rebuild a profile from a `_SELECT_SQL`-shaped row.

    Deserialisation runs every claim through
    `skill_entry_from_mapping`, so a row hand-edited past the CHECK
    constraints still cannot become an unlabelled claim in a prompt.
    """
    return LearnerProfile(
        principal_key_id=str(row[0]),
        academic_level=row[1] or "",
        time_budget_min_per_day=int(row[2] or 0),
        goals=tuple(goal_from_mapping(raw) for raw in (row[3] or [])),
        skills=tuple(skill_entry_from_mapping(raw) for raw in (row[4] or [])),
        profile_note=row[5] or "",
        created_at=row[6].timestamp() if row[6] else time.time(),
        updated_at=row[7].timestamp() if row[7] else time.time(),
    )


def build_profile_store() -> ProfileStore:
    """Select and construct the store from `settings.learner_profile_store`.

    Lazy, like `build_conversation_store`: selecting the in-memory
    variant never touches the Postgres pool.
    """
    from src.config import settings

    if settings.learner_profile_store == "postgres":
        return PostgresProfileStore()
    return InMemoryProfileStore()


__all__ = [
    "ACADEMIC_LEVELS",
    "DECLARED_CONFIDENCE",
    "GOAL_STATUSES",
    "INFERRED_MAX_CONFIDENCE",
    "MAX_EVIDENCE_REF_LEN",
    "MAX_GOALS",
    "MAX_GOAL_STATEMENT_LEN",
    "MAX_PROFILE_NOTE_LEN",
    "MAX_SKILL_ENTRIES",
    "MAX_SKILL_NAME_LEN",
    "MAX_TIME_BUDGET_MIN_PER_DAY",
    "SKILL_LEVELS",
    "SKILL_SOURCES",
    "AcademicLevel",
    "AnonymousPrincipalError",
    "GoalStatus",
    "InMemoryProfileStore",
    "LearnerGoal",
    "LearnerProfile",
    "PostgresProfileStore",
    "ProfileStore",
    "ProvenanceError",
    "SkillEntry",
    "SkillLevel",
    "SkillSource",
    "build_profile_store",
    "goal_from_mapping",
    "merge_skill_entries",
    "new_goal_id",
    "normalize_skill_name",
    "replace_declared_skills",
    "skill_entry_from_mapping",
    "utc_now_iso",
]
