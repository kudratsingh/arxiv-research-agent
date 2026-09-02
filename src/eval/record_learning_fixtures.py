"""Record the mock-session transcript fixtures (WO-W08's completion gate).

`tests/fixtures/learning/manifest.json` carried a `pending` fixture set
— `recorded_mock_session_transcripts` — whose completion condition was
written down as an executable instruction rather than a promise: once
the session graph exists, replay every scenario in
`learning_benchmark.LEARNING_SCENARIOS` through `build_session_workflow()`
under `use_mock_data=true` with the disabled-key sentinel, stamp each
provenance header with the generating commit and `mock_mode=true`, and
flip the entry to `complete`. This module is that instruction, executed.

It is deliberately **not** a second driver. `simulate_learner.drive_session`
already knows how to replay a scenario against the graph and is the
thing under test everywhere else; this module calls it and shapes the
result into `learning_fixtures.SessionTranscriptFixture`. If the two ever
disagreed about how a scenario is replayed, the fixtures would stop being
recordings of the system and start being recordings of a second, private
simulator.

**Determinism, and the one substitution it needs.** The session graph
stamps its own run id into every progress event's `evidence_ref`, and
that id is a fresh UUID per run — as it must be, because the graph's
checkpointer keys durable state on it and re-using one would resume the
previous recording instead of starting a new session. A fixture whose
bytes changed on every recording would be useless as a regression
baseline, so the recorder substitutes the run id it actually used for a
stable one derived from the scenario id. Nothing else is rewritten: the
plan, the tutor copy, the learner turns and the progress-event kinds are
whatever the graph produced. `tests/test_record_learning_fixtures.py`
asserts that a re-recording reproduces the checked-in files byte for
byte apart from the commit stamp.

Zero spend, always: mock mode is a refusal, not a default. The recorder
will not run against `USE_MOCK_DATA=false`.

Usage:
    USE_MOCK_DATA=true ANTHROPIC_API_KEY=local-preview-disabled \\
    ENABLE_CHECKPOINTING=true \\
        python -m src.eval.record_learning_fixtures

Exit codes:
    0 — every scenario recorded and the set validates
    1 — configuration error (not mock mode, no checkpointer, no commit)
    2 — recorded, but the fixture set does not validate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.config import settings
from src.eval.learning_benchmark import (
    LEARNING_SCENARIOS,
    LearningScenario,
    get_paper,
    get_persona,
)
from src.eval.learning_fixtures import (
    FIXTURE_ROOT,
    RECORDED_SET_NAME,
    REQUIRED_DISCLAIMER,
    SIMULATOR_FILLER_INTENT,
    FixtureProvenance,
    SessionTranscriptFixture,
    TranscriptProgressEvent,
    TranscriptTurn,
    load_manifest,
    validate_fixtures,
)
from src.eval.simulate_learner import SimulatedReply, drive_session
from src.observability import get_logger

load_dotenv()

log = get_logger(__name__)

#: Directory the recordings land in, relative to the fixture root. Read
#: from the manifest at runtime; this is only the fallback used when the
#: manifest cannot be loaded.
DEFAULT_RECORDED_DIRNAME = "recorded_mock_sessions"

#: Work order that owns these files, written into every provenance
#: header so a reader knows which card to blame.
AUTHORED_BY = "WO-W11 (src/eval/record_learning_fixtures.py)"

#: The disclaimer stamped on every recording. Must contain
#: `REQUIRED_DISCLAIMER` verbatim — the validator compares strings.
DISCLAIMER = (
    f"{REQUIRED_DISCLAIMER} Recorded from the session graph running in mock "
    "mode with a deliberately disabled API key; no model was called and no "
    "person was involved."
)

#: Written into every recording's `notes`, so the substitution below is
#: visible in the fixture rather than only in this module.
NOTES = (
    "Recorded by replaying the scenario's scripted turns through "
    "build_session_workflow() under use_mock_data=true. The session's run id "
    "is substituted for a stable id derived from the scenario id so that "
    "re-recording is byte-identical; everything else is as the graph "
    "produced it."
)


def deterministic_run_id(scenario_id: str) -> str:
    """The stable session id a recording's evidence refs are rewritten to.

    Sixteen hex characters, the same shape the simulator's `uuid4().hex[:16]`
    run ids have, so a recorded `evidence_ref` still looks like the thing
    it is a recording of.

    Args:
        scenario_id: The scenario being recorded.

    Returns:
        A stable 16-character hex id.
    """
    return hashlib.blake2s(scenario_id.encode("utf-8"), digest_size=8).hexdigest()


def current_commit() -> str:
    """The generating commit for a recording, or `""` when git is unavailable.

    Returns:
        The full `HEAD` sha, or an empty string outside a git checkout.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[2],
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def _role_of(message: Any) -> str:
    """Whether a graph message was spoken by the tutor or the learner.

    The session graph names learner messages `learner`,
    `learner_explain_back` and `learner_follow_up`; everything else on
    the transcript is tutor copy.
    """
    name = str(getattr(message, "name", "") or "")
    return "learner" if name.startswith("learner") else "tutor"


def _intent_of(reply: SimulatedReply) -> str:
    """The transcript intent for one simulated reply.

    Scripted replies carry the scenario's intent. A filler reply carries
    none — it is the simulator's content-free line, not something the
    scenario asked for — so it is labelled as such rather than being
    dressed up as an answer.
    """
    return reply.intent or SIMULATOR_FILLER_INTENT


def _event_summary(event: dict[str, Any]) -> str:
    """A one-line, deterministic summary of one progress event.

    Prefers the session summary the graph itself wrote, then an
    assessment note, then a plain statement of the kind. Never invents
    an outcome: everything here is text the graph already produced.
    """
    payload = event.get("payload")
    if isinstance(payload, dict):
        session_summary = payload.get("session_summary")
        if isinstance(session_summary, dict):
            text = session_summary.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
        note = payload.get("note")
        if isinstance(note, str) and note.strip():
            return note.strip()
    return f"{event.get('kind', 'event')} recorded by the mock session graph."


def _assessment_outcome(state: dict[str, Any]) -> str:
    """The recorded assessment outcome, in the fixture's vocabulary.

    Two honest values and no third. A session that never reached an
    assessment records `unassessed`; a session that recorded an
    explain-back with no calibrated judge behind it records
    `recorded_ungraded` (ADR 0060). The scenario's `expected_assessment`
    is what a *graded* session should reach and is deliberately not
    forced onto a recording — writing `strength` into a file the mock
    graph never graded would be exactly the fabrication the fixture
    provenance rules exist to prevent.
    """
    assessment = state.get("assessment") or {}
    status = assessment.get("status")
    if not isinstance(status, str) or not status or status == "none":
        return "unassessed"
    return status


def _canonicalize(text: str, actual: str, canonical: str) -> str:
    """Replace the recording's run id with the stable one."""
    return text.replace(actual, canonical)


def record_scenario(
    scenario: LearningScenario, *, commit: str, created_at: str
) -> SessionTranscriptFixture:
    """Replay one scenario and shape the result into a transcript fixture.

    Args:
        scenario: The scenario to replay.
        commit: Generating commit, stamped into the provenance header.
        created_at: ISO date stamped into the provenance header.

    Returns:
        The recorded fixture, with the run id canonicalized.

    Raises:
        ValueError: The scenario names a persona or paper that does not
            exist — a benchmark bug, not a recording one.
        Exception: Anything the session graph raises. A recording that
            failed must not be written, so this is not swallowed.
    """
    persona = get_persona(scenario["persona_id"])
    paper = get_paper(scenario["paper_id"])
    if persona is None or paper is None:
        raise ValueError(
            f"{scenario['scenario_id']}: unknown persona or paper "
            f"({scenario['persona_id']!r} / {scenario['paper_id']!r})"
        )

    actual_run_id = uuid.uuid4().hex[:16]
    canonical_run_id = deterministic_run_id(scenario["scenario_id"])
    run = drive_session(
        scenario,
        persona,
        paper,
        actual_run_id,
        tier="scripted",
        learner_model="",
        costs_snapshot=dict,
    )

    turns: list[TranscriptTurn] = []
    learner_index = 0
    for message in run.state.get("messages") or []:
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            continue
        role = _role_of(message)
        intent = ""
        if role == "learner":
            if learner_index < len(run.replies):
                intent = _intent_of(run.replies[learner_index])
            else:  # pragma: no cover - the graph cannot outpace its replies
                intent = SIMULATOR_FILLER_INTENT
            learner_index += 1
        turns.append(
            TranscriptTurn(
                turn_index=len(turns),
                role=role,
                intent=intent,
                text=_canonicalize(content, actual_run_id, canonical_run_id),
            )
        )

    events: list[TranscriptProgressEvent] = []
    for event in run.state.get("progress_events") or []:
        if not isinstance(event, dict):  # pragma: no cover - defensive
            continue
        events.append(
            TranscriptProgressEvent(
                kind=str(event.get("kind") or ""),
                evidence_ref=_canonicalize(
                    str(event.get("evidence_ref") or ""),
                    actual_run_id,
                    canonical_run_id,
                ),
                summary=_canonicalize(
                    _event_summary(event), actual_run_id, canonical_run_id
                ),
            )
        )

    return SessionTranscriptFixture(
        provenance=FixtureProvenance(
            fixture_kind="recorded-mock",
            authored_by=AUTHORED_BY,
            generated_by_commit=commit,
            created_at=created_at,
            mock_mode=True,
            real_session=False,
            disclaimer=DISCLAIMER,
        ),
        fixture_id=f"recorded-mock:{scenario['scenario_id']}",
        scenario_id=scenario["scenario_id"],
        assessment_outcome=_assessment_outcome(run.state),
        transcript=turns,
        progress_events=events,
        notes=NOTES,
    )


def _recorded_directory(root: Path) -> Path:
    """Where the recordings go, read from the manifest when possible."""
    try:
        manifest = load_manifest(root)
    except ValueError:  # pragma: no cover - a broken manifest fails later
        return root / DEFAULT_RECORDED_DIRNAME
    for entry in manifest["fixture_sets"]:
        if entry["name"] == RECORDED_SET_NAME:
            return root / entry["directory"]
    return root / DEFAULT_RECORDED_DIRNAME


def record_fixtures(
    root: Path | None = None, *, commit: str, created_at: str
) -> list[Path]:
    """Record one transcript per benchmark scenario into the fixture set.

    Existing recordings are overwritten, which is the point: re-running
    this after a graph change is how the fixtures stay recordings rather
    than becoming folklore.

    Args:
        root: Fixture root. Defaults to `learning_fixtures.FIXTURE_ROOT`.
        commit: Generating commit for the provenance headers.
        created_at: ISO date for the provenance headers.

    Returns:
        The written paths, in scenario order.

    Raises:
        ValueError: A scenario names inputs the benchmark does not have.
    """
    base = FIXTURE_ROOT if root is None else root
    directory = _recorded_directory(base)
    directory.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for scenario in LEARNING_SCENARIOS:
        fixture = record_scenario(scenario, commit=commit, created_at=created_at)
        path = directory / f"{scenario['scenario_id']}.json"
        path.write_text(
            json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        written.append(path)
        log.info(
            "learning_fixture_recorded",
            extra={
                "scenario_id": scenario["scenario_id"],
                "turns": len(fixture["transcript"]),
                "progress_events": len(fixture["progress_events"]),
            },
        )
    return written


def _config_problem() -> str | None:
    """Refuse to record against anything but the free mock path."""
    if not settings.use_mock_data:
        return (
            "Error: recording requires USE_MOCK_DATA=true. A recording made "
            "against real models would cost money and would not be "
            "reproducible, and the manifest's completion condition names mock "
            "mode explicitly."
        )
    if not settings.enable_checkpointing:
        return (
            "Error: the session graph pauses for every learner turn through "
            "LangGraph's durable interrupt, which needs a checkpointer. Set "
            "ENABLE_CHECKPOINTING=true."
        )
    return None


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Record one mock-session transcript fixture per learning "
            "benchmark scenario."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Fixture root. Default: tests/fixtures/learning/.",
    )
    parser.add_argument(
        "--commit",
        default="",
        help="Generating commit for the provenance headers. Default: git HEAD.",
    )
    parser.add_argument(
        "--created-at",
        default="",
        help="ISO date for the provenance headers. Default: today (UTC).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Record the fixture set and validate it. Returns a process exit code."""
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    problem = _config_problem()
    if problem:
        print(problem, file=sys.stderr)
        return 1

    commit = args.commit or current_commit()
    if not commit:
        print(
            "Error: no generating commit. A recorded fixture must name the "
            "commit that produced it (learning_fixtures.validate_provenance); "
            "pass --commit explicitly when git is unavailable.",
            file=sys.stderr,
        )
        return 1
    created_at = args.created_at or datetime.now(UTC).date().isoformat()

    written = record_fixtures(args.root, commit=commit, created_at=created_at)
    print(f"Recorded {len(written)} transcript(s) at commit {commit[:12]}.")

    problems = validate_fixtures(args.root)
    if problems:
        print("\nFixture validation failed:", file=sys.stderr)
        for entry in problems:
            print(f"  - {entry}", file=sys.stderr)
        return 2
    print("Fixture set validates.")
    return 0


__all__ = [
    "AUTHORED_BY",
    "DISCLAIMER",
    "NOTES",
    "current_commit",
    "deterministic_run_id",
    "main",
    "record_fixtures",
    "record_scenario",
]


if __name__ == "__main__":
    sys.exit(main())
