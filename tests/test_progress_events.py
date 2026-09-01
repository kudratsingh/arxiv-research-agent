"""The append-only progress ledger and its honest views (WO-W07).

Four claims are made about this store, and each has tests here that
would fail if a future edit quietly withdrew it:

1. **Append-only.** No update path, no per-event delete path — not on
   the Protocol, not in the module's SQL, not on the HTTP surface. In
   Postgres a trigger refuses `UPDATE` outright and `DELETE` unless the
   connection opted into an account-level erasure.
2. **Every event links its evidence.** `assessment` writes without a
   resolvable `evidence_ref` are refused at the write boundary and by
   a database CHECK.
3. **Views are recomputable from the log alone.** A raw event fixture
   is folded into a summary and compared field for field, and the
   result is asserted independent of arrival order.
4. **No mastery percentage exists here.** `TestNoMasteryPercentage` is
   the named test Gate W1's honesty inventory cites.

Postgres tests use `pytest-postgresql` and follow
`tests/test_paper_cache.py`'s skip pattern: they exercise the parts of
the contract that only a real database can prove — the trigger and the
CHECKs — and are skipped where no `postgres` server binary exists. The
in-memory tiers above them run everywhere, so the Python write
boundary is never only proven by an integration tier.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import random
import re
import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import httpx
import psycopg
import pytest
from asgi_lifespan import LifespanManager
from fastapi import HTTPException, Request
from pydantic import ValidationError

from src.api.app import create_app
from src.api.jobs import InMemoryJobStore
from src.api.schemas import (
    LearnerProgressSummary,
    ProgressDailySessions,
    ProgressEvidence,
    ProgressResourceObservation,
    ProgressSchedule,
)
from src.learning.progress_store import (
    ALL_EVENT_KINDS,
    BANNED_SCALAR_TOKENS,
    KINDS_REQUIRING_EVIDENCE,
    PUBLIC_STORE_METHODS,
    RESERVED_KINDS,
    WRITABLE_KINDS,
    DailySessionCount,
    EvidenceRecord,
    InMemoryProgressEventStore,
    PathScheduleProgress,
    PostgresProgressEventStore,
    ProgressEvent,
    ProgressEventRejected,
    ProgressEventStore,
    ProgressSummary,
    ResourceObservation,
    new_event,
    normalize_ts,
    summarize,
)
from src.tools import postgres_pool
from src.tools.postgres_pool import SCHEMA_DDL

pytestmark = pytest.mark.unit

FIXTURE = (
    Path(__file__).parent / "fixtures" / "learning" / "progress_events_raw.json"
)

_STORE_MODULE = (
    Path(__file__).parent.parent / "src" / "learning" / "progress_store.py"
)


def _store_source_without_comments() -> str:
    """The store's code with `#` comments dropped.

    The comments explain *why* there is no update path, so scanning
    them for the words "DO UPDATE" would catch the explanation instead
    of a regression. What matters is the executable text.
    """
    return "\n".join(
        line
        for line in _STORE_MODULE.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )


def _raw_events() -> list[dict[str, Any]]:
    """The committed raw log, straight off disk.

    Deliberately returns plain dicts: the recomputability claim is
    about rebuilding a view from *the log*, so the test must not be
    handed anything the store already digested.
    """
    document = json.loads(FIXTURE.read_text())
    events: list[dict[str, Any]] = document["events"]
    return events


def _fixture_events() -> list[ProgressEvent]:
    return [ProgressEvent.from_json_dict(raw) for raw in _raw_events()]


def _session(
    *,
    principal: str = "pilot-01",
    ts: str = "2026-08-24T09:00:00Z",
    path_id: str | None = "path-a",
    planned: int | None = None,
    event_id: str | None = None,
) -> ProgressEvent:
    payload: dict[str, Any] = {}
    if path_id is not None:
        payload["path_id"] = path_id
    if planned is not None:
        payload["sessions_planned"] = planned
    return new_event(
        principal_key_id=principal,
        kind="session_completed",
        ts=ts,
        payload=payload,
        evidence_ref=f"session:{event_id or 'seed'}",
        event_id=event_id,
    )


# ---------------------------------------------------------------------------
# 1. The kind vocabulary — reserved now, refused until a producer exists
# ---------------------------------------------------------------------------


class TestEventKindVocabulary:
    def test_the_full_01_44_vocabulary_is_reserved(self) -> None:
        # The six kinds `01-LEARNING-AGENT.md` §4.4 names, so Phase L
        # adds producers rather than a migration.
        assert set(ALL_EVENT_KINDS) == {
            "session_completed",
            "assessment",
            "review_item",
            "artifact_produced",
            "plan_approved",
            "replan",
        }

    def test_phase_w_writes_exactly_three_of_them(self) -> None:
        assert {
            "session_completed",
            "assessment",
            "artifact_produced",
        } == WRITABLE_KINDS
        assert {"review_item", "plan_approved", "replan"} == RESERVED_KINDS
        assert set(ALL_EVENT_KINDS) == WRITABLE_KINDS | RESERVED_KINDS

    @pytest.mark.parametrize("kind", sorted(RESERVED_KINDS))
    def test_a_reserved_kind_is_refused_until_a_producer_exists(
        self, kind: str
    ) -> None:
        # The card's own risk note: reserving a name is cheap, but
        # accepting writes for a feature nothing produces would seed the
        # ledger with rows no view can read.
        with pytest.raises(ProgressEventRejected, match="reserved"):
            new_event(
                principal_key_id="pilot-01",
                kind=kind,
                evidence_ref="whatever:1",
            )

    def test_an_unknown_kind_is_refused(self) -> None:
        with pytest.raises(ProgressEventRejected, match="unknown kind"):
            new_event(principal_key_id="pilot-01", kind="vibes")


# ---------------------------------------------------------------------------
# 2. Provenance at the write boundary
# ---------------------------------------------------------------------------


class TestEvidenceAtTheWriteBoundary:
    def test_assessment_is_the_kind_that_requires_evidence(self) -> None:
        assert {"assessment"} == KINDS_REQUIRING_EVIDENCE

    def test_an_assessment_without_evidence_is_refused(self) -> None:
        with pytest.raises(ProgressEventRejected, match="evidence_ref"):
            new_event(
                principal_key_id="pilot-01",
                kind="assessment",
                payload={"probe": "explain-back"},
            )

    def test_a_blank_evidence_ref_is_not_evidence(self) -> None:
        # Whitespace is the cheapest way to satisfy a "not null" check;
        # it must not satisfy this one.
        with pytest.raises(ProgressEventRejected, match="evidence_ref"):
            new_event(
                principal_key_id="pilot-01",
                kind="assessment",
                evidence_ref="   ",
            )

    def test_an_assessment_with_evidence_is_accepted(self) -> None:
        event = new_event(
            principal_key_id="pilot-01",
            kind="assessment",
            evidence_ref="  transcript:s-1#probe  ",
        )
        # Trimmed, so the stored ref resolves.
        assert event.evidence_ref == "transcript:s-1#probe"

    def test_the_ledger_has_no_anonymous_rows(self) -> None:
        # SR-02 keys the store on the API principal. A deployment with
        # auth off has no principal, so it must not be able to write.
        with pytest.raises(ProgressEventRejected, match="principal_key_id"):
            new_event(principal_key_id="  ", kind="session_completed")

    async def test_the_store_validates_and_does_not_trust_its_caller(
        self,
    ) -> None:
        # Constructing a `ProgressEvent` directly bypasses `new_event`;
        # `append` must refuse it anyway, or the boundary is advisory.
        store = InMemoryProgressEventStore()
        smuggled = ProgressEvent(
            event_id="evt-x",
            principal_key_id="pilot-01",
            ts="2026-08-24T09:00:00Z",
            kind="assessment",
            payload={},
            evidence_ref=None,
        )
        with pytest.raises(ProgressEventRejected):
            await store.append(smuggled)
        assert await store.list_events("pilot-01") == []

    def test_timestamps_are_normalized_to_utc(self) -> None:
        # Day bucketing is a string slice, so a ledger whose `ts` values
        # carried mixed offsets would bucket sessions into the wrong day.
        assert normalize_ts("2026-08-24T09:00:00Z") == (
            "2026-08-24T09:00:00.000000Z"
        )
        assert normalize_ts("2026-08-24T11:00:00+02:00") == (
            "2026-08-24T09:00:00.000000Z"
        )
        # A naive timestamp is read as UTC, not as the server's local
        # time — otherwise the log stops being reproducible off-box.
        assert normalize_ts("2026-08-24T09:00:00") == (
            "2026-08-24T09:00:00.000000Z"
        )

    def test_an_unparseable_timestamp_is_refused(self) -> None:
        with pytest.raises(ProgressEventRejected, match="ISO-8601"):
            normalize_ts("last tuesday")

    def test_an_oversized_payload_is_refused(self) -> None:
        with pytest.raises(ProgressEventRejected, match="exceeds"):
            new_event(
                principal_key_id="pilot-01",
                kind="session_completed",
                payload={"blob": "x" * 20_000},
            )

    def test_an_unserializable_payload_is_refused(self) -> None:
        with pytest.raises(ProgressEventRejected, match="JSON-serializable"):
            new_event(
                principal_key_id="pilot-01",
                kind="session_completed",
                payload={"when": object()},
            )


# ---------------------------------------------------------------------------
# 3. Append-only — the invariant with no escape hatch on an event
# ---------------------------------------------------------------------------


class TestAppendOnly:
    def test_the_store_surface_is_pinned_and_has_no_mutation_method(
        self,
    ) -> None:
        # Adding a method means editing `PUBLIC_STORE_METHODS`, which
        # means a reviewer sees it. `erase_principal` is account-level
        # erasure (WO-W02's deletion promise), not an edit: there is no
        # method that takes an `event_id` and changes anything.
        assert {
            "append",
            "list_events",
            "erase_principal",
        } == PUBLIC_STORE_METHODS
        for store_type in (
            ProgressEventStore,
            InMemoryProgressEventStore,
            PostgresProgressEventStore,
        ):
            public = {
                name
                for name in vars(store_type)
                if not name.startswith("_")
            }
            assert public == PUBLIC_STORE_METHODS, store_type.__name__

    def test_the_modules_sql_never_updates_an_event(self) -> None:
        source = _store_source_without_comments()
        assert re.search(r"UPDATE\s+progress_events", source, re.I) is None
        # Nor an upsert dressed as an insert.
        assert re.search(r"DO\s+UPDATE", source, re.I) is None

    def test_the_only_delete_is_the_account_level_erasure(self) -> None:
        source = _store_source_without_comments()
        deletes = re.findall(r"DELETE\s+FROM\s+progress_events", source, re.I)
        assert len(deletes) == 1
        # …and it is unreachable without the transaction-scoped opt-in
        # the DDL trigger looks for.
        erase_body = source.split("async def erase_principal", 2)[2]
        assert "SET LOCAL arxiv.progress_purge = 'on'" in erase_body

    async def test_a_repeated_append_re_reads_rather_than_overwrites(
        self,
    ) -> None:
        store = InMemoryProgressEventStore()
        first = await store.append(_session(event_id="evt-1", path_id="path-a"))
        # Same id, different content: a retry, not an edit. The stored
        # row wins and nothing is double-counted.
        second = await store.append(
            _session(event_id="evt-1", path_id="path-b")
        )
        assert second == first
        assert second.payload["path_id"] == "path-a"
        assert len(await store.list_events("pilot-01")) == 1

    async def test_a_correction_is_a_new_event_and_the_old_one_survives(
        self,
    ) -> None:
        store = InMemoryProgressEventStore()
        await store.append(_session(event_id="evt-1", ts="2026-08-24T09:00:00Z"))
        await store.append(_session(event_id="evt-2", ts="2026-08-24T10:00:00Z"))
        events = await store.list_events("pilot-01")
        assert [e.event_id for e in events] == ["evt-1", "evt-2"]

    def test_no_http_route_mutates_the_progress_ledger(self) -> None:
        # The card's criterion 1 is about the API surface: whatever the
        # store can do internally, nothing over HTTP may edit or delete
        # an event.
        paths = create_app().openapi()["paths"]
        progress_paths = {p: ops for p, ops in paths.items() if "progress" in p}
        assert progress_paths, "the progress endpoint disappeared"
        for path, operations in progress_paths.items():
            assert set(operations) == {"get"}, path

    async def test_erasure_is_account_level_not_event_level(self) -> None:
        store = InMemoryProgressEventStore()
        await store.append(_session(event_id="evt-1", principal="pilot-01"))
        await store.append(_session(event_id="evt-2", principal="pilot-02"))
        assert await store.erase_principal("pilot-01") == 1
        assert await store.list_events("pilot-01") == []
        # Erasing one person leaves everyone else's record intact.
        assert len(await store.list_events("pilot-02")) == 1


# ---------------------------------------------------------------------------
# 4. Views are recomputable from the log alone
# ---------------------------------------------------------------------------


EXPECTED_SUMMARY = ProgressSummary(
    principal_key_id="pilot-01",
    event_count=8,
    sessions_per_day=(
        DailySessionCount(
            day="2026-08-24", sessions=2, event_ids=("evt-0001", "evt-0003")
        ),
        DailySessionCount(
            day="2026-08-25", sessions=2, event_ids=("evt-0004", "evt-0006")
        ),
        DailySessionCount(day="2026-08-26", sessions=1, event_ids=("evt-0007",)),
    ),
    schedule_progress=(
        PathScheduleProgress(
            path_id="attention-is-all-you-need",
            sessions_completed=3,
            # The path was re-scoped from 4 to 3 at evt-0007; the latest
            # declaration wins, not the largest one ever seen.
            sessions_planned=3,
            schedule_label="3 of 3 sessions",
            assessments_recorded=1,
            event_ids=("evt-0001", "evt-0004", "evt-0007"),
        ),
        PathScheduleProgress(
            path_id="eval-harness-basics",
            sessions_completed=0,
            sessions_planned=None,
            schedule_label="0 sessions recorded",
            assessments_recorded=1,
            event_ids=(),
        ),
        PathScheduleProgress(
            path_id="rlhf-foundations",
            sessions_completed=1,
            sessions_planned=None,
            schedule_label="1 session recorded",
            assessments_recorded=0,
            event_ids=("evt-0006",),
        ),
    ),
    resource_observations=(
        ResourceObservation(
            path_id="attention-is-all-you-need",
            resource_id="arxiv:1706.03762",
            sessions_completed=1,
            last_observed_at="2026-08-24T09:15:00.000000Z",
            event_ids=("evt-0001",),
        ),
        ResourceObservation(
            path_id="attention-is-all-you-need",
            resource_id="arxiv:1810.04805",
            sessions_completed=1,
            last_observed_at="2026-08-25T08:05:00.000000Z",
            event_ids=("evt-0004",),
        ),
        ResourceObservation(
            path_id="attention-is-all-you-need",
            resource_id="arxiv:2305.18290",
            sessions_completed=1,
            last_observed_at="2026-08-26T07:45:00.000000Z",
            event_ids=("evt-0007",),
        ),
        ResourceObservation(
            path_id="rlhf-foundations",
            resource_id="arxiv:2203.02155",
            sessions_completed=1,
            last_observed_at="2026-08-25T19:30:00.000000Z",
            event_ids=("evt-0006",),
        ),
    ),
    assessments=(
        EvidenceRecord(
            event_id="evt-0002",
            ts="2026-08-24T09:40:00.000000Z",
            kind="assessment",
            evidence_ref="transcript:s-1001#explain-back",
            path_id="attention-is-all-you-need",
        ),
        EvidenceRecord(
            event_id="evt-0008",
            ts="2026-08-26T08:10:00.000000Z",
            kind="assessment",
            evidence_ref="transcript:s-1005#probe",
            path_id="eval-harness-basics",
        ),
    ),
    artifacts=(
        EvidenceRecord(
            event_id="evt-0005",
            ts="2026-08-25T08:50:00.000000Z",
            kind="artifact_produced",
            evidence_ref="job:9f2c1ab4d7e60351",
            path_id="attention-is-all-you-need",
        ),
    ),
)
"""What the committed fixture folds into. Written out rather than
computed, so a change in the view's arithmetic has to be restated here
by a human instead of silently agreeing with itself."""


class TestRecomputableViews:
    def test_the_summary_rebuilds_from_the_raw_log(self) -> None:
        # 01 §4.4: everything a surface says is a view over these
        # events. Rebuilding it from the log and getting the identical
        # object back is that sentence as a test.
        assert summarize("pilot-01", _fixture_events()) == EXPECTED_SUMMARY

    def test_the_summary_does_not_depend_on_arrival_order(self) -> None:
        events = _fixture_events()
        rng = random.Random(20260830)
        for _ in range(20):
            shuffled = events[:]
            rng.shuffle(shuffled)
            assert summarize("pilot-01", shuffled) == EXPECTED_SUMMARY

    def test_the_view_never_crosses_principals(self) -> None:
        # pilot-02's session sits in the same fixture and must not
        # appear anywhere in pilot-01's record.
        summary = summarize("pilot-01", _fixture_events())
        all_ids = {
            event_id
            for bucket in summary.sessions_per_day
            for event_id in bucket.event_ids
        }
        assert "evt-0009" not in all_ids
        assert summarize("pilot-02", _fixture_events()).event_count == 1

    def test_every_count_carries_exactly_the_events_behind_it(self) -> None:
        # "No displayed claim without an event behind it" as a property:
        # each number equals the length of its own provenance list.
        summary = summarize("pilot-01", _fixture_events())
        for day in summary.sessions_per_day:
            assert day.sessions == len(day.event_ids)
            assert len(set(day.event_ids)) == day.sessions
        for path in summary.schedule_progress:
            assert path.sessions_completed == len(path.event_ids)

    def test_every_evidence_row_points_at_something(self) -> None:
        summary = summarize("pilot-01", _fixture_events())
        for record in (*summary.assessments, *summary.artifacts):
            assert record.evidence_ref

    def test_a_path_that_never_declared_a_length_gets_no_denominator(
        self,
    ) -> None:
        # 00 §5.4: what was never established is not guessed at. An
        # unknown total is reported as unknown, not filled in.
        path = next(
            p
            for p in summarize("pilot-01", _fixture_events()).schedule_progress
            if p.path_id == "rlhf-foundations"
        )
        assert path.sessions_planned is None
        assert path.schedule_label == "1 session recorded"

    def test_an_assessed_but_never_sat_path_still_appears(self) -> None:
        # "0 of N" is a true state; omitting the path would hide it.
        path = next(
            p
            for p in summarize("pilot-01", _fixture_events()).schedule_progress
            if p.path_id == "eval-harness-basics"
        )
        assert path.sessions_completed == 0
        assert path.assessments_recorded == 1

    def test_summarize_reads_nothing_but_its_arguments(self) -> None:
        # Determinism has to survive the clock. Two folds of the same
        # log, at different wall times, are the same object.
        events = _fixture_events()
        first = summarize("pilot-01", events)
        second = summarize("pilot-01", events)
        assert first == second

    def test_an_empty_log_is_an_empty_record_not_a_zero_claim(self) -> None:
        summary = summarize("pilot-01", [])
        assert summary.event_count == 0
        assert summary.sessions_per_day == ()
        assert summary.schedule_progress == ()
        assert summary.assessments == ()
        assert summary.artifacts == ()

    async def test_the_store_round_trips_the_fixture_unchanged(self) -> None:
        # The stored form and the fixture form are the same thing, so
        # the recomputability property proven above holds for real
        # writes and not only for the file.
        store = InMemoryProgressEventStore()
        for event in _fixture_events():
            await store.append(event)
        stored = await store.list_events("pilot-01")
        assert summarize("pilot-01", stored) == EXPECTED_SUMMARY


# ---------------------------------------------------------------------------
# 5. The no-mastery-% rule. Gate W1's honesty inventory cites this class.
# ---------------------------------------------------------------------------


def _ddl_mastery_constraint() -> str:
    match = re.search(
        r"CONSTRAINT progress_events_no_mastery_scalar CHECK \((.*?)\n    \)",
        SCHEMA_DDL,
        re.S,
    )
    assert match is not None, "the no-mastery CHECK vanished from SCHEMA_DDL"
    return match.group(1)


def _view_field_names() -> set[str]:
    names: set[str] = set()
    for view in (
        ProgressSummary,
        DailySessionCount,
        PathScheduleProgress,
        ResourceObservation,
        EvidenceRecord,
    ):
        names.update(f.name for f in dataclasses.fields(view))
    for model in (
        LearnerProgressSummary,
        ProgressDailySessions,
        ProgressSchedule,
        ProgressResourceObservation,
        ProgressEvidence,
    ):
        names.update(model.model_fields)
    return names


class TestNoMasteryPercentage:
    """01 §4.1's ban, enforced at the source rather than at the surface.

    "You are 87% through Transformers" is a claim about a latent
    variable no LLM judge can measure. The store therefore has no field
    that could hold one, refuses a payload key that reads like one, and
    constrains its one rendered label to session arithmetic. WO-W14
    runs the matching forbidden-string gate over the UI; this is the
    same rule enforced where the data is born.
    """

    def test_no_view_field_reads_as_a_knowledge_scalar(self) -> None:
        for name in _view_field_names():
            lowered = name.lower()
            for token in BANNED_SCALAR_TOKENS:
                assert token not in lowered, f"{name} contains {token!r}"

    def test_the_only_progress_arithmetic_is_labeled_schedule(self) -> None:
        # 01 §4.1 permits plan progress *provided it is labeled as
        # schedule progress, not knowledge*. The field name is the
        # label.
        assert "schedule_progress" in {f.name for f in dataclasses.fields(ProgressSummary)}
        assert "schedule_progress" in LearnerProgressSummary.model_fields

    def test_a_schedule_label_can_only_say_sessions(self) -> None:
        # The one string this module renders. If a future edit widened
        # it to "87% complete", this fails.
        pattern = re.compile(r"^\d+ of \d+ sessions$|^\d+ sessions? recorded$")
        summary = summarize("pilot-01", _fixture_events())
        assert summary.schedule_progress
        for path in summary.schedule_progress:
            assert pattern.match(path.schedule_label), path.schedule_label
            assert "%" not in path.schedule_label

    @pytest.mark.parametrize(
        "key",
        [
            "mastery",
            "mastery_pct",
            "percent_complete",
            "knowledge_score",
            "proficiency",
            "competency_level",
            "skill_level",
            "MasteryPercent",
        ],
    )
    def test_a_payload_key_that_claims_a_scalar_is_refused(
        self, key: str
    ) -> None:
        with pytest.raises(ProgressEventRejected, match="knowledge scalar"):
            new_event(
                principal_key_id="pilot-01",
                kind="session_completed",
                payload={key: 87},
            )

    def test_the_ban_reaches_nested_payload_keys(self) -> None:
        # A scalar smuggled one level down is the same claim.
        with pytest.raises(ProgressEventRejected, match="knowledge scalar"):
            new_event(
                principal_key_id="pilot-01",
                kind="session_completed",
                payload={"summary": {"per_topic": [{"mastery": 0.87}]}},
            )

    def test_a_learner_may_still_say_the_word(self) -> None:
        # The ban is on fields, not on speech. An explain-back where
        # someone writes "I have not mastered this" must be storable —
        # otherwise the honesty rule censors the evidence it exists to
        # protect.
        event = new_event(
            principal_key_id="pilot-01",
            kind="assessment",
            evidence_ref="transcript:s-1#probe",
            payload={"quote": "I have not mastered the KL penalty yet"},
        )
        assert "mastered" in event.payload["quote"]

    def test_the_database_ban_and_the_python_ban_are_the_same_list(
        self,
    ) -> None:
        # Two enforcement points, one vocabulary. Without this the DDL
        # and the module drift and the weaker one becomes the real rule.
        constraint = _ddl_mastery_constraint()
        alternation = re.search(r"\(([a-z_|]+)\)", constraint)
        assert alternation is not None
        assert tuple(alternation.group(1).split("|")) == BANNED_SCALAR_TOKENS

    def test_the_ddl_matches_keys_and_not_free_text(self) -> None:
        # The CHECK anchors on `"<key>":` so a transcript quoting the
        # banned word stays storable — the same distinction the Python
        # walk makes.
        constraint = _ddl_mastery_constraint()
        assert '"[^"]*' in constraint
        assert '[[:space:]]*:' in constraint

    def test_the_published_api_schema_offers_no_mastery_property(
        self,
    ) -> None:
        # The contract is what clients build against; a field banned in
        # Python but published in OpenAPI would be a ban in name only.
        document = create_app().openapi()
        schemas = document["components"]["schemas"]
        for name in (
            "LearnerProgressSummary",
            "ProgressDailySessions",
            "ProgressSchedule",
            "ProgressEvidence",
        ):
            assert name in schemas
            for prop in schemas[name].get("properties", {}):
                for token in BANNED_SCALAR_TOKENS:
                    assert token not in prop.lower(), f"{name}.{prop}"


# ---------------------------------------------------------------------------
# 6. The shared DDL section
# ---------------------------------------------------------------------------


class TestSchemaDdlSection:
    def test_the_section_is_comment_fenced(self) -> None:
        # 05 §5.4: `SCHEMA_DDL` is append-only and each card owns a
        # fenced block. The fence style is WO-W02's, adopted on the
        # rebase so the shared region has one convention rather than
        # one per card.
        assert "=== BEGIN progress_events (WO-W07, ADR 0058) ===" in SCHEMA_DDL
        assert "=== END progress_events ===" in SCHEMA_DDL
        assert SCHEMA_DDL.index("=== BEGIN progress_events") < SCHEMA_DDL.index(
            "CREATE TABLE IF NOT EXISTS progress_events"
        )

    def test_the_section_is_appended_after_wo_w02s(self) -> None:
        # The §5.4 merge order, asserted rather than trusted: W02's
        # `learner_profiles` block comes first, and this card's block
        # begins after W02's END marker — so a future rebase that
        # interleaved them fails here.
        assert SCHEMA_DDL.index("=== END learner_profiles ===") < SCHEMA_DDL.index(
            "=== BEGIN progress_events"
        )

    def test_every_create_in_the_section_is_idempotent(self) -> None:
        section = SCHEMA_DDL.split("=== BEGIN progress_events")[1].split(
            "=== END progress_events"
        )[0]
        for statement in re.findall(r"CREATE (\w+)", section):
            assert statement in {"TABLE", "INDEX", "OR", "TRIGGER"}
        assert "CREATE TABLE IF NOT EXISTS progress_events" in section
        assert "CREATE INDEX IF NOT EXISTS progress_events_principal_ts_idx" in section
        assert "CREATE OR REPLACE FUNCTION progress_events_append_only" in section
        # The trigger has no IF NOT EXISTS form, so the drop carries it.
        assert (
            "DROP TRIGGER IF EXISTS progress_events_append_only_trg" in section
        )

    def test_the_structural_guarantees_live_in_the_ddl(self) -> None:
        assert "progress_events_kind_allowed" in SCHEMA_DDL
        assert "progress_events_assessment_needs_evidence" in SCHEMA_DDL
        assert "progress_events_no_mastery_scalar" in SCHEMA_DDL
        for kind in ALL_EVENT_KINDS:
            assert f"'{kind}'" in SCHEMA_DDL


# ---------------------------------------------------------------------------
# 7. `GET /learn/progress`
# ---------------------------------------------------------------------------


@pytest.fixture
async def learner_client() -> AsyncIterator[
    tuple[httpx.AsyncClient, ProgressEventStore]
]:
    """App with auth on, the learner flag on, and two principals.

    Mirrors `tests/test_per_principal_scoping.py`'s two-key fixture —
    the ledger's isolation claim is the same claim ADR 0036 makes, so
    it is tested the same way.
    """
    from src.api import app as app_module
    from src.api import auth as auth_module
    from src.api import routes as routes_module
    from src.config import Settings

    overridden = Settings(
        enable_api_auth=True,
        enable_learner_profile=True,
        api_keys="alice:sk_alice,bob:sk_bob",
    )
    mp = pytest.MonkeyPatch()
    mp.setattr(app_module, "settings", overridden)
    mp.setattr(auth_module, "settings", overridden)
    mp.setattr(routes_module, "settings", overridden)

    store = InMemoryProgressEventStore()
    app = create_app(
        build_workflow=lambda: MagicMock(),
        store=InMemoryJobStore(),
        progress_event_store=store,
    )
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client, store

    mp.undo()


class TestProgressEndpoint:
    async def test_flag_off_leaves_no_surface(self) -> None:
        # Default settings: the endpoint is registered (so the contract
        # snapshot describes one shape, not two) but the deployment
        # does not have it.
        app = create_app(
            build_workflow=lambda: MagicMock(), store=InMemoryJobStore()
        )
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get("/learn/progress")
        assert response.status_code == 404
        assert response.json()["detail"] == "learner_profile_disabled"

    def test_the_ledger_cannot_be_enabled_without_auth(self) -> None:
        """The unowned-read configuration is impossible, not merely refused.

        Before WO-W02 merged, this card carried its own runtime 503 for
        "flag on, auth off" — the only defence available while the flag
        was declared here. ADR 0058's `@model_validator` is strictly
        better: the pair now fails at *settings load*, so the operator
        sees it before traffic rather than as a per-request error, and
        the ledger inherits that protection for free.
        """
        from src.config import Settings

        with pytest.raises(ValidationError, match="enable_api_auth"):
            Settings(enable_learner_profile=True, enable_api_auth=False)

    async def test_the_route_still_refuses_an_unowned_read(self) -> None:
        """Defence in depth behind the validator.

        The guard above makes this branch unreachable through config,
        so it is exercised directly instead of through HTTP. Kept
        rather than deleted because the ledger has no anonymous rows:
        if the validator were ever loosened, the route must still
        refuse rather than fold someone else's events into a summary.
        """
        from src.api import routes as routes_module
        from src.config import Settings

        mp = pytest.MonkeyPatch()
        mp.setattr(
            routes_module,
            "settings",
            Settings(enable_learner_profile=True, enable_api_auth=True),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        with pytest.raises(HTTPException) as exc:
            await routes_module.get_learn_progress(
                cast(Request, request), principal=None
            )
        mp.undo()
        assert exc.value.status_code == 503
        assert exc.value.detail == "learner_progress_requires_auth"

    async def test_a_learner_reads_their_own_folded_ledger(
        self,
        learner_client: tuple[httpx.AsyncClient, ProgressEventStore],
    ) -> None:
        client, store = learner_client
        for raw in _raw_events():
            event = ProgressEvent.from_json_dict(raw)
            await store.append(
                dataclasses.replace(
                    event,
                    principal_key_id=(
                        "alice" if event.principal_key_id == "pilot-01" else "bob"
                    ),
                )
            )

        response = await client.get(
            "/learn/progress", headers={"X-API-Key": "sk_alice"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["principal_key_id"] == "alice"
        assert body["event_count"] == 8
        assert [p["schedule_label"] for p in body["schedule_progress"]] == [
            "3 of 3 sessions",
            "0 sessions recorded",
            "1 session recorded",
        ]
        assert [a["event_id"] for a in body["assessments"]] == [
            "evt-0002",
            "evt-0008",
        ]

    async def test_one_learner_never_sees_another(
        self,
        learner_client: tuple[httpx.AsyncClient, ProgressEventStore],
    ) -> None:
        client, store = learner_client
        await store.append(_session(event_id="evt-a", principal="alice"))
        await store.append(_session(event_id="evt-b", principal="bob"))

        response = await client.get(
            "/learn/progress", headers={"X-API-Key": "sk_bob"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["event_count"] == 1
        assert body["sessions_per_day"][0]["event_ids"] == ["evt-b"]

    async def test_an_unknown_key_is_rejected_before_the_ledger(
        self,
        learner_client: tuple[httpx.AsyncClient, ProgressEventStore],
    ) -> None:
        client, _ = learner_client
        response = await client.get(
            "/learn/progress", headers={"X-API-Key": "sk_nobody"}
        )
        assert response.status_code == 401

    async def test_the_response_carries_no_percentage(
        self,
        learner_client: tuple[httpx.AsyncClient, ProgressEventStore],
    ) -> None:
        client, store = learner_client
        await store.append(
            _session(event_id="evt-a", principal="alice", planned=10)
        )
        response = await client.get(
            "/learn/progress", headers={"X-API-Key": "sk_alice"}
        )
        serialized = response.text.lower()
        for token in BANNED_SCALAR_TOKENS:
            assert token not in serialized
        assert "%" not in serialized


# ---------------------------------------------------------------------------
# 8. The contract fixture, tied to the route that produced it
# ---------------------------------------------------------------------------

CONTRACT_FIXTURE = (
    Path(__file__).parent.parent
    / "web"
    / "contract"
    / "fixtures"
    / "learn.progress.json"
)


class TestContractFixture:
    """`web/contract/fixtures/learn.progress.json` is authored, not recorded.

    The recorder drives the seeded Compose stack and there is no seeded
    learner behind a default-off flag, so the envelope is hand-written
    — which is exactly the case `authored: true` exists for. The
    *body* is still not invented: it is the route's own output over the
    committed raw event log, and this test is what keeps that true. An
    authored fixture without this check would be the invented-contract
    failure the fixture rules are written against.
    """

    async def test_the_fixture_body_is_what_the_route_returns(self) -> None:
        from src.api import app as app_module
        from src.api import auth as auth_module
        from src.api import routes as routes_module
        from src.config import Settings

        overridden = Settings(
            enable_api_auth=True,
            enable_learner_profile=True,
            api_keys="pilot-01:sk_pilot",
        )
        mp = pytest.MonkeyPatch()
        mp.setattr(app_module, "settings", overridden)
        mp.setattr(auth_module, "settings", overridden)
        mp.setattr(routes_module, "settings", overridden)

        store = InMemoryProgressEventStore()
        for event in _fixture_events():
            if event.principal_key_id == "pilot-01":
                await store.append(event)

        app = create_app(
            build_workflow=lambda: MagicMock(),
            store=InMemoryJobStore(),
            progress_event_store=store,
        )
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get(
                    "/learn/progress", headers={"X-API-Key": "sk_pilot"}
                )
        mp.undo()

        recorded = json.loads(CONTRACT_FIXTURE.read_text())
        assert response.status_code == recorded["status"]
        assert response.json() == recorded["body"]

    def test_the_fixture_declares_that_it_was_authored(self) -> None:
        # The web-side inventory test asserts the same thing; asserting
        # it here too means the Python gate catches a fixture that
        # quietly starts claiming to be a recording.
        recording = json.loads(CONTRACT_FIXTURE.read_text())["x-recording"]
        assert recording["authored"] is True
        assert recording["authored_reason"]
        assert "ANTHROPIC_API_KEY=local-preview-disabled" in recording["stack"]


# ---------------------------------------------------------------------------
# 9. Postgres — where the structural guarantees actually bite
# ---------------------------------------------------------------------------

_postgres_available = shutil.which("postgres") is not None
pytestmark_postgres = pytest.mark.skipif(
    not _postgres_available,
    reason="postgres server binary not found; install `postgresql` locally to run",
)

if _postgres_available:
    from pytest_postgresql import factories

    postgresql_proc = factories.postgresql_proc(port=None, unixsocketdir="/tmp")
    postgresql_db = factories.postgresql("postgresql_proc")

    @pytest.fixture
    def pg_url(
        postgresql_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[str]:
        """Per-test database, with the shared pool reset around it.

        Same shape as `tests/test_paper_cache.py::pg_url` — the pool is
        process-wide, so a leaked one would cross-contaminate.
        """
        from src.config import Settings

        info = postgresql_db.info
        url = f"postgresql://{info.user}:@{info.host}:{info.port}/{info.dbname}"
        overridden = Settings(postgres_url=url, progress_event_store="postgres")
        monkeypatch.setattr(postgres_pool, "settings", overridden)
        postgres_pool._reset_for_test(None)
        yield url
        postgres_pool.close_pool()


def _insert_raw(url: str, **columns: Any) -> None:
    """Write straight to the table, bypassing every Python guard.

    The point of the DDL constraints is that they hold for a `psql`
    session too, so the tests that prove them must not go through the
    store.
    """
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO progress_events
                (event_id, principal_key_id, ts, kind, payload, evidence_ref)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s)
            """,
            (
                columns["event_id"],
                columns.get("principal_key_id", "pilot-01"),
                columns.get("ts", "2026-08-24T09:00:00Z"),
                columns["kind"],
                json.dumps(columns.get("payload", {})),
                columns.get("evidence_ref"),
            ),
        )
        conn.commit()


@pytestmark_postgres
@pytest.mark.integration
class TestPostgresProgressEvents:
    def test_schema_init_creates_the_table(self, pg_url: str) -> None:
        postgres_pool.init_schema()
        with psycopg.connect(pg_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.progress_events')::text")
            row = cur.fetchone()
        assert row is not None and row[0] == "progress_events"

    def test_init_schema_is_idempotent(self, pg_url: str) -> None:
        # 05 §5.4's shared guard between WO-W02 and WO-W07: whichever
        # order the two DDL sections land in, running the whole thing
        # twice must be a no-op.
        postgres_pool.init_schema()
        postgres_pool._reset_for_test(postgres_pool.get_pool(pg_url))
        postgres_pool.init_schema()

    def test_append_then_read_round_trips(self, pg_url: str) -> None:
        store = PostgresProgressEventStore()
        event = _session(event_id="evt-1", planned=4)
        asyncio.run(store.append(event))
        stored = asyncio.run(store.list_events("pilot-01"))
        assert [e.event_id for e in stored] == ["evt-1"]
        assert stored[0].payload["sessions_planned"] == 4
        assert stored[0].ts == event.ts

    def test_a_repeated_append_does_not_overwrite(self, pg_url: str) -> None:
        store = PostgresProgressEventStore()
        asyncio.run(store.append(_session(event_id="evt-1", path_id="path-a")))
        second = asyncio.run(
            store.append(_session(event_id="evt-1", path_id="path-b"))
        )
        assert second.payload["path_id"] == "path-a"
        assert len(asyncio.run(store.list_events("pilot-01"))) == 1

    def test_the_database_refuses_an_update(self, pg_url: str) -> None:
        postgres_pool.init_schema()
        _insert_raw(pg_url, event_id="evt-1", kind="session_completed")
        with (
            psycopg.connect(pg_url) as conn,
            conn.cursor() as cur,
            pytest.raises(psycopg.errors.RestrictViolation),
        ):
            cur.execute(
                "UPDATE progress_events SET kind = 'assessment' "
                "WHERE event_id = 'evt-1'"
            )

    def test_the_database_refuses_a_casual_delete(self, pg_url: str) -> None:
        postgres_pool.init_schema()
        _insert_raw(pg_url, event_id="evt-1", kind="session_completed")
        with (
            psycopg.connect(pg_url) as conn,
            conn.cursor() as cur,
            pytest.raises(psycopg.errors.RestrictViolation),
        ):
            cur.execute("DELETE FROM progress_events WHERE event_id = 'evt-1'")

    def test_account_erasure_is_the_one_door_through(self, pg_url: str) -> None:
        # WO-W02 promises deletion; append-only must not make that a
        # lie. The opt-in is transaction-scoped, so it cannot leak into
        # an ordinary connection.
        store = PostgresProgressEventStore()
        asyncio.run(store.append(_session(event_id="evt-1", principal="pilot-01")))
        asyncio.run(store.append(_session(event_id="evt-2", principal="pilot-02")))
        assert asyncio.run(store.erase_principal("pilot-01")) == 1
        assert asyncio.run(store.list_events("pilot-01")) == []
        assert len(asyncio.run(store.list_events("pilot-02"))) == 1

    def test_the_database_refuses_an_assessment_without_evidence(
        self, pg_url: str
    ) -> None:
        postgres_pool.init_schema()
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_raw(pg_url, event_id="evt-1", kind="assessment")

    def test_the_database_refuses_a_blank_evidence_ref(
        self, pg_url: str
    ) -> None:
        postgres_pool.init_schema()
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_raw(
                pg_url, event_id="evt-1", kind="assessment", evidence_ref="  "
            )

    def test_the_database_refuses_an_unknown_kind(self, pg_url: str) -> None:
        postgres_pool.init_schema()
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_raw(pg_url, event_id="evt-1", kind="vibes")

    @pytest.mark.parametrize(
        "payload",
        [
            {"mastery_pct": 87},
            {"summary": {"proficiency": 0.4}},
            {"per_topic": [{"knowledge_score": 3}]},
        ],
    )
    def test_the_database_refuses_a_mastery_scalar(
        self, pg_url: str, payload: dict[str, Any]
    ) -> None:
        # The 01 §4.1 ban, proven where it cannot be bypassed by
        # importing a different module.
        postgres_pool.init_schema()
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert_raw(
                pg_url,
                event_id="evt-1",
                kind="session_completed",
                payload=payload,
            )

    def test_a_transcript_quoting_the_word_still_stores(
        self, pg_url: str
    ) -> None:
        postgres_pool.init_schema()
        _insert_raw(
            pg_url,
            event_id="evt-1",
            kind="assessment",
            evidence_ref="transcript:s-1#probe",
            payload={"quote": "I have not mastered this yet"},
        )
