"""Loader and validator for the learning-benchmark fixtures (WO-W08).

The scenarios in `src/eval/learning_benchmark.py` say what a learner
*does*. This module loads the fixtures that say what the system
*produced* — session plans and session transcripts — so the judges in
`src/eval/learning_metrics.py` (WO-W09) can be tested against fixed
inputs without a running session graph, and so WO-W10's simulator has
something to diff a live run against.

Two fixture kinds, and the difference is the point:

  - **hand-authored** — written by a person for a specific judge test.
    No graph ran; `mock_mode` is false and `generated_by_commit` is
    empty, because nothing generated them. The paired plan fixtures
    (an honest downscoped plan and a budget-ignoring one for the same
    scenario) are the WO-W09 c2 inputs and are hand-authored by design:
    the dishonest variant is a thing the system should never emit, so
    it could never be recorded.
  - **recorded-mock** — captured from WO-W03's session graph running
    under `use_mock_data=true` with the disabled-key sentinel. These
    now exist: `src/eval/record_learning_fixtures.py` replays every
    benchmark scenario through `build_session_workflow()` and writes one
    transcript per scenario. Each names the commit that produced it and
    sets `mock_mode: true`, and none is presentable as a real learner
    session.

The completion gate was executable, not a comment, and it has now
fired: WO-W03 merged, WO-W11 recorded the transcripts, and the manifest
entry flipped from `pending` to `complete` — at which point the same
validator that *forbade* files in that directory started *requiring*
them. A pending set still may not hold files, so the gate remains armed
for the next set that needs one.

Two vocabulary items belong to recordings alone, because they describe
what the graph actually did rather than what a scenario hoped for:

  - `RECORDED_UNGRADED` as an `assessment_outcome` — ADR 0060's honest
    record when an explain-back was taken but no calibrated judge
    scored it. A recording may carry it; a hand-authored fixture may
    not, and a recording carrying it is *not* checked against the
    scenario's `expected_assessment`, because that expectation
    describes a graded session and the mock graph grades nothing.
  - `SIMULATOR_FILLER_INTENT` as a learner turn's intent — the
    simulator's content-free line, delivered when the tutor asked more
    questions than the script anticipated. Labelling it honestly beats
    dressing it up as one of the scenario's own intents.

No LLM calls, no network, no graph — this module reads JSON and checks
it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

from src.eval.learning_benchmark import (
    ASSESSMENT_OUTCOMES,
    LEARNER_TURN_INTENTS,
    PHASE_W_PROGRESS_EVENT_KINDS,
    get_paper,
    get_scenario,
)

#: Repo-relative home of the fixtures. `src/eval/` is two levels below
#: the repo root; the fixtures live with the tests that assert on them,
#: per the WO-W08 card.
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "learning"

MANIFEST_NAME = "manifest.json"

#: How a fixture came to exist. See the module docstring — this is the
#: field that keeps a hand-written plan from ever being read as a
#: recording of something the system did.
FIXTURE_KINDS = frozenset({"hand-authored", "recorded-mock"})

#: A fixture set is either populated (`complete`) or explicitly waiting
#: on an unmerged work order (`pending`).
FIXTURE_SET_STATUSES = frozenset({"complete", "pending"})

#: What a fixture set holds. Declared per set in the manifest rather
#: than inferred from the directory name, so adding a set is a data
#: change and never a parser change.
FIXTURE_CONTENT_KINDS = frozenset({"session_plan", "transcript"})

#: Session-plan section modes, keyed to the briefing companion's
#: close-read-vs-skim guidance (02 §2.2).
PLAN_SECTION_MODES = frozenset({"close_read", "skim"})

#: Who speaks a transcript turn.
TRANSCRIPT_ROLES = frozenset({"tutor", "learner"})

#: Every fixture's disclaimer must contain this verbatim. Hard-coded
#: rather than described so a fixture cannot soften the wording: the
#: honesty rule is a string comparison.
REQUIRED_DISCLAIMER = "Not a real learner session."

#: Name of the recorded-mock fixture set in the manifest. Shared with
#: `src/eval/record_learning_fixtures.py` so the recorder and the
#: validator cannot drift onto different directories.
RECORDED_SET_NAME = "recorded_mock_session_transcripts"

#: The status the session graph records when an explain-back was taken
#: but no calibrated assessment judge scored it (ADR 0060). It is
#: deliberately *not* one of `ASSESSMENT_OUTCOMES`: it is not an
#: outcome, it is the refusal to invent one. Only a `recorded-mock`
#: transcript may carry it, because only a recording can honestly say
#: that is what happened.
RECORDED_UNGRADED = "recorded_ungraded"

#: Intent stamped on a learner turn the simulator filled in with its
#: content-free line rather than a scripted reply
#: (`simulate_learner.SCRIPT_EXHAUSTED_REPLY`). Only valid in a
#: recording: a hand-authored transcript has no simulator to blame.
SIMULATOR_FILLER_INTENT = "simulator_filler"


#: Prefix on every `ValueError` the loaders raise, so a failure names
#: the subsystem before it names the file.
#:
#: Structural failures raise; *semantic* problems (a plan that
#: contradicts its scenario) are returned as a list by the validators
#: instead, so a test can report all of them at once rather than making
#: a fixture author play whack-a-mole.
#:
#: Deliberately a plain `ValueError` rather than a `FixtureError`
#: subclass. `web/tests/copy/errorTypeDrift.test.ts` enumerates every
#: exception class defined anywhere under `src/` and asserts each one is
#: mapped to user-facing copy, because any of them can reach the API
#: runner's generic handler and become a `job.error_type` the web tier
#: renders. This module is offline eval tooling that never executes in
#: the API process, so mapping it would be fiction — and evading the
#: scan with a contrived base class would be worse. If a later card
#: teaches that guard which directories the runner can actually reach,
#: a typed exception becomes free; until then this costs callers only a
#: type name.
FIXTURE_ERROR_PREFIX = "learning fixture"


def _fixture_error(message: str) -> ValueError:
    """Build the loaders' structural-failure exception."""
    return ValueError(f"{FIXTURE_ERROR_PREFIX}: {message}")


class FixtureProvenance(TypedDict):
    """Where a fixture came from — the WO-W08 c4 header."""

    fixture_kind: str
    #: Free-text owner: the work order and branch that authored it.
    authored_by: str
    #: Git commit of the code that generated the fixture. Required for
    #: `recorded-mock`; empty for `hand-authored`, where nothing
    #: generated anything.
    generated_by_commit: str
    #: ISO date the fixture was written or recorded.
    created_at: str
    #: True only when a graph ran under `use_mock_data=true`.
    mock_mode: bool
    #: Always false. A fixture that claimed otherwise would be a lie the
    #: validator refuses to carry.
    real_session: bool
    disclaimer: str


class PlanSection(TypedDict):
    """One section of a session plan."""

    section: str
    mode: str
    minutes: int
    #: The comprehension check placed at this section boundary; empty
    #: when the plan places none here.
    check: str


class SessionPlanFixture(TypedDict):
    """A session plan as the `check_in` node would emit it."""

    provenance: FixtureProvenance
    fixture_id: str
    scenario_id: str
    #: `honest_downscope` and `budget_ignoring` are the WO-W09 c2 pair;
    #: `baseline` is an ordinary full-budget plan.
    variant: str
    declared_minutes_today: int
    #: The plan's own statement that it was cut down to fit. Empty when
    #: the plan makes no such claim — which is a *failure* for an
    #: `honest_downscope` variant and expected for `budget_ignoring`.
    downscope_statement: str
    sections: list[PlanSection]
    notes: str


class TranscriptTurn(TypedDict):
    """One turn of a recorded or hand-authored session transcript."""

    turn_index: int
    role: str
    #: For learner turns, the scenario intent this turn realises; for
    #: tutor turns, empty.
    intent: str
    text: str


class TranscriptProgressEvent(TypedDict):
    """A progress event the session wrote (01 §4.4 / WO-W07's store)."""

    kind: str
    evidence_ref: str
    summary: str


class SessionTranscriptFixture(TypedDict):
    """A full session: the plan it ran, what was said, what was recorded."""

    provenance: FixtureProvenance
    fixture_id: str
    scenario_id: str
    #: Outcome the assessment reached, from `ASSESSMENT_OUTCOMES`.
    assessment_outcome: str
    transcript: list[TranscriptTurn]
    progress_events: list[TranscriptProgressEvent]
    notes: str


class FixtureSet(TypedDict):
    """One directory of fixtures, and whether it is populated yet."""

    name: str
    status: str
    directory: str
    fixture_kind: str
    #: `session_plan` or `transcript` — what the files in it are.
    content_kind: str
    #: Work order this set waits on. Non-empty only when `pending`.
    blocked_on: str
    #: What must be true for `status` to become `complete`. Non-empty
    #: only when `pending`.
    completion_condition: str
    description: str


class FixtureManifest(TypedDict):
    """The fixture directory's index, including its unfilled slots."""

    schema_version: int
    fixture_sets: list[FixtureSet]


# --------------------------------------------------------------------------
# Typed JSON access
#
# `json.load` returns `Any`; these helpers turn that into typed values or
# a `ValueError` naming the file and key, so a malformed fixture fails
# with something an author can act on.
# --------------------------------------------------------------------------


def _obj(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fixture_error(f"{where}: expected an object, got {type(value).__name__}")
    return value


def _str(payload: dict[str, Any], key: str, where: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise _fixture_error(f"{where}: {key!r} must be a string")
    return value


def _int(payload: dict[str, Any], key: str, where: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _fixture_error(f"{where}: {key!r} must be an integer")
    return value


def _bool(payload: dict[str, Any], key: str, where: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise _fixture_error(f"{where}: {key!r} must be a boolean")
    return value


def _list(payload: dict[str, Any], key: str, where: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise _fixture_error(f"{where}: {key!r} must be a list")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem failure
        raise _fixture_error(f"{path}: unreadable ({exc})") from exc
    try:
        return _obj(json.loads(raw), str(path))
    except json.JSONDecodeError as exc:
        raise _fixture_error(f"{path}: invalid JSON ({exc})") from exc


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def _parse_provenance(payload: dict[str, Any], where: str) -> FixtureProvenance:
    block = _obj(payload.get("provenance"), f"{where}.provenance")
    return FixtureProvenance(
        fixture_kind=_str(block, "fixture_kind", where),
        authored_by=_str(block, "authored_by", where),
        generated_by_commit=_str(block, "generated_by_commit", where),
        created_at=_str(block, "created_at", where),
        mock_mode=_bool(block, "mock_mode", where),
        real_session=_bool(block, "real_session", where),
        disclaimer=_str(block, "disclaimer", where),
    )


def _parse_plan(payload: dict[str, Any], where: str) -> SessionPlanFixture:
    sections: list[PlanSection] = []
    for index, entry in enumerate(_list(payload, "sections", where)):
        block = _obj(entry, f"{where}.sections[{index}]")
        sections.append(
            PlanSection(
                section=_str(block, "section", where),
                mode=_str(block, "mode", where),
                minutes=_int(block, "minutes", where),
                check=_str(block, "check", where),
            )
        )
    return SessionPlanFixture(
        provenance=_parse_provenance(payload, where),
        fixture_id=_str(payload, "fixture_id", where),
        scenario_id=_str(payload, "scenario_id", where),
        variant=_str(payload, "variant", where),
        declared_minutes_today=_int(payload, "declared_minutes_today", where),
        downscope_statement=_str(payload, "downscope_statement", where),
        sections=sections,
        notes=_str(payload, "notes", where),
    )


def _parse_transcript(payload: dict[str, Any], where: str) -> SessionTranscriptFixture:
    turns: list[TranscriptTurn] = []
    for index, entry in enumerate(_list(payload, "transcript", where)):
        block = _obj(entry, f"{where}.transcript[{index}]")
        turns.append(
            TranscriptTurn(
                turn_index=_int(block, "turn_index", where),
                role=_str(block, "role", where),
                intent=_str(block, "intent", where),
                text=_str(block, "text", where),
            )
        )
    events: list[TranscriptProgressEvent] = []
    for index, entry in enumerate(_list(payload, "progress_events", where)):
        block = _obj(entry, f"{where}.progress_events[{index}]")
        events.append(
            TranscriptProgressEvent(
                kind=_str(block, "kind", where),
                evidence_ref=_str(block, "evidence_ref", where),
                summary=_str(block, "summary", where),
            )
        )
    return SessionTranscriptFixture(
        provenance=_parse_provenance(payload, where),
        fixture_id=_str(payload, "fixture_id", where),
        scenario_id=_str(payload, "scenario_id", where),
        assessment_outcome=_str(payload, "assessment_outcome", where),
        transcript=turns,
        progress_events=events,
        notes=_str(payload, "notes", where),
    )


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_manifest(root: Path | None = None) -> FixtureManifest:
    """Read `manifest.json` from the fixture root.

    Args:
        root: Fixture directory. Defaults to `FIXTURE_ROOT`.

    Returns:
        The parsed manifest, including its `pending` sets — the pending
        entries are the point of the file, not an omission from it.

    Raises:
        ValueError: The manifest is missing or malformed. A missing
            manifest is fatal rather than an empty default: fixtures with
            no index are fixtures with no provenance policy.
    """
    base = FIXTURE_ROOT if root is None else root
    path = base / MANIFEST_NAME
    if not path.is_file():
        raise _fixture_error(f"{path}: fixture manifest is missing")
    payload = _read_json(path)
    where = str(path)

    sets: list[FixtureSet] = []
    for index, entry in enumerate(_list(payload, "fixture_sets", where)):
        block = _obj(entry, f"{where}.fixture_sets[{index}]")
        sets.append(
            FixtureSet(
                name=_str(block, "name", where),
                status=_str(block, "status", where),
                directory=_str(block, "directory", where),
                fixture_kind=_str(block, "fixture_kind", where),
                content_kind=_str(block, "content_kind", where),
                blocked_on=_str(block, "blocked_on", where),
                completion_condition=_str(block, "completion_condition", where),
                description=_str(block, "description", where),
            )
        )
    return FixtureManifest(
        schema_version=_int(payload, "schema_version", where),
        fixture_sets=sets,
    )


def get_fixture_set(manifest: FixtureManifest, name: str) -> FixtureSet | None:
    """Return the named fixture set, or `None` when the manifest has none."""
    for entry in manifest["fixture_sets"]:
        if entry["name"] == name:
            return entry
    return None


def pending_fixture_sets(manifest: FixtureManifest) -> list[FixtureSet]:
    """Return the sets still waiting on an unmerged work order.

    The honest inventory of what this benchmark cannot yet cover. Gate
    W1's evidence pack should be able to print this list.
    """
    return [e for e in manifest["fixture_sets"] if e["status"] == "pending"]


def _set_files(base: Path, entry: FixtureSet) -> list[Path]:
    directory = base / entry["directory"]
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def load_session_plans(root: Path | None = None) -> list[SessionPlanFixture]:
    """Load every session-plan fixture, in filename order.

    Raises:
        ValueError: Any file is unreadable or structurally wrong.
    """
    base = FIXTURE_ROOT if root is None else root
    manifest = load_manifest(base)
    plans: list[SessionPlanFixture] = []
    for entry in manifest["fixture_sets"]:
        if entry["content_kind"] != "session_plan":
            continue
        for path in _set_files(base, entry):
            plans.append(_parse_plan(_read_json(path), str(path)))
    return plans


def load_transcripts(root: Path | None = None) -> list[SessionTranscriptFixture]:
    """Load every session-transcript fixture, in filename order.

    Includes both hand-authored transcripts and — once WO-W03 lands and
    the manifest entry flips to `complete` — the recorded mock sessions.
    Callers that need to tell them apart read `provenance.fixture_kind`.

    Raises:
        ValueError: Any file is unreadable or structurally wrong.
    """
    base = FIXTURE_ROOT if root is None else root
    manifest = load_manifest(base)
    transcripts: list[SessionTranscriptFixture] = []
    for entry in manifest["fixture_sets"]:
        if entry["content_kind"] != "transcript":
            continue
        for path in _set_files(base, entry):
            transcripts.append(_parse_transcript(_read_json(path), str(path)))
    return transcripts


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate_provenance(
    provenance: FixtureProvenance, *, label: str, expected_kind: str
) -> list[str]:
    """Check a fixture's provenance header (WO-W08 c4).

    Returns a list of problems, empty when the header is honest.
    """
    problems: list[str] = []
    kind = provenance["fixture_kind"]
    if kind not in FIXTURE_KINDS:
        problems.append(f"{label}: unknown fixture_kind {kind!r}")
    elif kind != expected_kind:
        problems.append(
            f"{label}: fixture_kind {kind!r} does not match its set's {expected_kind!r}"
        )
    if not provenance["authored_by"].strip():
        problems.append(f"{label}: authored_by is empty")
    if not provenance["created_at"].strip():
        problems.append(f"{label}: created_at is empty")
    if provenance["real_session"]:
        problems.append(
            f"{label}: real_session must be false — no fixture in this repo is a "
            "recording of a real person's session"
        )
    if REQUIRED_DISCLAIMER not in provenance["disclaimer"]:
        problems.append(
            f"{label}: disclaimer must contain {REQUIRED_DISCLAIMER!r} verbatim"
        )
    if kind == "recorded-mock":
        if not provenance["generated_by_commit"].strip():
            problems.append(
                f"{label}: a recorded fixture must name the generating commit"
            )
        if not provenance["mock_mode"]:
            problems.append(
                f"{label}: a recorded fixture must have been produced in mock mode "
                "(use_mock_data=true, disabled-key sentinel)"
            )
    else:
        if provenance["generated_by_commit"].strip():
            problems.append(
                f"{label}: a hand-authored fixture names a generating commit — "
                "nothing generated it"
            )
        if provenance["mock_mode"]:
            problems.append(
                f"{label}: a hand-authored fixture claims mock_mode; no graph ran"
            )
    return problems


def validate_plan(plan: SessionPlanFixture, *, expected_kind: str) -> list[str]:
    """Check one session-plan fixture for internal and scenario coherence."""
    label = plan["fixture_id"]
    problems = validate_provenance(
        plan["provenance"], label=label, expected_kind=expected_kind
    )

    scenario = get_scenario(plan["scenario_id"])
    if scenario is None:
        problems.append(f"{label}: unknown scenario_id {plan['scenario_id']!r}")
    elif plan["declared_minutes_today"] != scenario["declared_minutes_today"]:
        problems.append(
            f"{label}: declared_minutes_today {plan['declared_minutes_today']} "
            f"disagrees with scenario {plan['scenario_id']!r} "
            f"({scenario['declared_minutes_today']})"
        )

    if not plan["sections"]:
        problems.append(f"{label}: a plan with no sections plans nothing")
    for section in plan["sections"]:
        if section["mode"] not in PLAN_SECTION_MODES:
            problems.append(f"{label}: unknown section mode {section['mode']!r}")
        if section["minutes"] <= 0:
            problems.append(
                f"{label}: section {section['section']!r} has non-positive minutes"
            )

    # A plan may only schedule sections the briefing companion has
    # guidance for; anything else is a section the tutor invented.
    if scenario is not None:
        paper = get_paper(scenario["paper_id"])
        if paper is not None:
            guided = set(paper["close_read_sections"]) | set(paper["skim_sections"])
            for section in plan["sections"]:
                if section["section"] not in guided:
                    problems.append(
                        f"{label}: section {section['section']!r} is not in the "
                        f"briefing guidance for {paper['paper_id']}"
                    )
        # The positive variants must respect the scenario's structural
        # bound; the negative variant exists to break it.
        if plan["variant"] != "budget_ignoring":
            cap = scenario["expectations"]["max_plan_sections"]
            if len(plan["sections"]) > cap:
                problems.append(
                    f"{label}: {len(plan['sections'])} sections exceeds the "
                    f"scenario's max_plan_sections ({cap})"
                )

    budget = plan["declared_minutes_today"]
    planned = sum(s["minutes"] for s in plan["sections"])

    if plan["variant"] == "honest_downscope":
        if not plan["downscope_statement"].strip():
            problems.append(
                f"{label}: an honest_downscope plan must state that it was cut down"
            )
        if planned > budget:
            problems.append(
                f"{label}: honest_downscope plans {planned} minutes of work into a "
                f"{budget}-minute budget"
            )
    elif plan["variant"] == "budget_ignoring":
        # The negative fixture. It must actually be dishonest, or the
        # judge test that expects a low score proves nothing.
        if planned <= budget:
            problems.append(
                f"{label}: budget_ignoring variant fits its budget "
                f"({planned} <= {budget}) — it is not the negative case it claims"
            )
    elif plan["variant"] != "baseline":
        problems.append(f"{label}: unknown variant {plan['variant']!r}")

    return problems


def validate_transcript(
    transcript: SessionTranscriptFixture, *, expected_kind: str
) -> list[str]:
    """Check one transcript fixture for internal and scenario coherence."""
    label = transcript["fixture_id"]
    problems = validate_provenance(
        transcript["provenance"], label=label, expected_kind=expected_kind
    )

    scenario = get_scenario(transcript["scenario_id"])
    if scenario is None:
        problems.append(f"{label}: unknown scenario_id {transcript['scenario_id']!r}")

    outcome = transcript["assessment_outcome"]
    if outcome == RECORDED_UNGRADED:
        # ADR 0060's ungraded record. Allowed only in a recording, and
        # never compared against the scenario's `expected_assessment`:
        # that expectation describes a session a calibrated judge
        # scored, and the mock graph scores nothing. Forcing `strength`
        # into a file the system never graded is the fabrication these
        # fixtures exist to make impossible.
        if expected_kind != "recorded-mock":
            problems.append(
                f"{label}: only a recorded fixture may carry the ungraded "
                f"assessment record {RECORDED_UNGRADED!r} — a hand-authored "
                "transcript has no session to have recorded it"
            )
    elif outcome not in ASSESSMENT_OUTCOMES:
        problems.append(
            f"{label}: unknown assessment_outcome "
            f"{transcript['assessment_outcome']!r}"
        )
    elif scenario is not None:
        expected = scenario["expectations"]["expected_assessment"]
        if transcript["assessment_outcome"] != expected:
            problems.append(
                f"{label}: assessment_outcome {transcript['assessment_outcome']!r} "
                f"disagrees with scenario expectation {expected!r}"
            )

    turns = transcript["transcript"]
    if not turns:
        problems.append(f"{label}: transcript is empty")
    for position, turn in enumerate(turns):
        if turn["turn_index"] != position:
            problems.append(
                f"{label}: turn_index {turn['turn_index']} out of order at {position}"
            )
        if turn["role"] not in TRANSCRIPT_ROLES:
            problems.append(f"{label}: unknown role {turn['role']!r}")
        if not turn["text"].strip():
            problems.append(f"{label}: turn {position} has empty text")
        if turn["role"] == "learner":
            # A recording may additionally carry the simulator's filler
            # marker: the graph offers more pauses than a 2-4 turn
            # script fills, and the honest label for those turns is
            # "the harness said something content-free here", not one
            # of the scenario's intents.
            allowed = set(LEARNER_TURN_INTENTS)
            if expected_kind == "recorded-mock":
                allowed.add(SIMULATOR_FILLER_INTENT)
            if turn["intent"] not in allowed:
                problems.append(
                    f"{label}: learner turn {position} has unknown intent "
                    f"{turn['intent']!r}"
                )
        elif turn["intent"]:
            problems.append(
                f"{label}: tutor turn {position} carries a learner intent "
                f"{turn['intent']!r}"
            )

    for event in transcript["progress_events"]:
        if event["kind"] not in PHASE_W_PROGRESS_EVENT_KINDS:
            problems.append(
                f"{label}: progress event {event['kind']!r} is not one Phase W writes"
            )
        # 01 §4.4 / WO-W07 c4: an assessment claim without a resolvable
        # reference is exactly the unbacked claim the store rejects.
        if event["kind"] == "assessment" and not event["evidence_ref"].strip():
            problems.append(f"{label}: assessment event has no evidence_ref")

    if scenario is not None:
        expected_kinds = set(scenario["expectations"]["expected_progress_events"])
        actual_kinds = {e["kind"] for e in transcript["progress_events"]}
        missing = expected_kinds - actual_kinds
        if missing:
            problems.append(
                f"{label}: scenario expects progress events {sorted(missing)} "
                "that the transcript does not contain"
            )
        extra = actual_kinds - expected_kinds
        if extra:
            problems.append(
                f"{label}: transcript records progress events {sorted(extra)} "
                "the scenario does not expect"
            )
        probe = scenario["expectations"]["injection_probe"]
        if probe:
            for event in transcript["progress_events"]:
                if probe in event["evidence_ref"] or probe in event["summary"]:
                    problems.append(
                        f"{label}: injection probe {probe!r} reached a progress event"
                    )
            for turn in turns:
                if turn["role"] == "tutor" and probe in turn["text"]:
                    problems.append(
                        f"{label}: injection probe {probe!r} was echoed by the tutor"
                    )

    return problems


def validate_fixtures(root: Path | None = None) -> list[str]:
    """Validate the whole fixture directory against its manifest.

    Enforces the manifest's own rules first — a `pending` set must name
    what blocks it and must hold no files; a `complete` set must hold at
    least one and must not claim to be blocked — then validates every
    fixture in every populated set.

    Returns a list of problems, empty when the directory is honest.

    Raises:
        ValueError: The manifest itself, or a fixture file, is
            unparseable. Structure is fatal; semantics are returned.
    """
    base = FIXTURE_ROOT if root is None else root
    manifest = load_manifest(base)
    problems: list[str] = []

    if manifest["schema_version"] != 1:
        problems.append(
            f"manifest schema_version {manifest['schema_version']} is not supported"
        )

    names = [e["name"] for e in manifest["fixture_sets"]]
    if len(names) != len(set(names)):
        problems.append("manifest has duplicate fixture-set names")

    for entry in manifest["fixture_sets"]:
        name = entry["name"]
        if entry["status"] not in FIXTURE_SET_STATUSES:
            problems.append(f"{name}: unknown status {entry['status']!r}")
            continue
        if entry["fixture_kind"] not in FIXTURE_KINDS:
            problems.append(f"{name}: unknown fixture_kind {entry['fixture_kind']!r}")
        if entry["content_kind"] not in FIXTURE_CONTENT_KINDS:
            problems.append(f"{name}: unknown content_kind {entry['content_kind']!r}")
            continue

        files = _set_files(base, entry)
        if entry["status"] == "pending":
            if not entry["blocked_on"].strip():
                problems.append(f"{name}: a pending set must name what blocks it")
            if not entry["completion_condition"].strip():
                problems.append(
                    f"{name}: a pending set must state its completion condition"
                )
            if files:
                problems.append(
                    f"{name}: marked pending on {entry['blocked_on'] or '?'} but holds "
                    f"{len(files)} fixture(s) — flip the manifest entry to 'complete' "
                    "rather than shipping fixtures under a pending marker"
                )
            continue

        if entry["blocked_on"].strip() or entry["completion_condition"].strip():
            problems.append(
                f"{name}: a complete set must not still name a blocker"
            )
        if not files:
            problems.append(f"{name}: marked complete but holds no fixtures")

        for path in files:
            payload = _read_json(path)
            if entry["content_kind"] == "session_plan":
                problems.extend(
                    validate_plan(
                        _parse_plan(payload, str(path)),
                        expected_kind=entry["fixture_kind"],
                    )
                )
            else:
                problems.extend(
                    validate_transcript(
                        _parse_transcript(payload, str(path)),
                        expected_kind=entry["fixture_kind"],
                    )
                )

    return problems
