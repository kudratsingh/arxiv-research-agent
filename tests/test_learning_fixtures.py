"""Tests for the learning-benchmark fixtures and their loader.

Two jobs. First, the shipped fixture directory has to be honest: every
fixture carries a provenance header, nothing claims to be a real
learner's session, and the one fixture set that does not exist yet says
so in the manifest instead of being quietly absent.

Second — and this is the part that has to keep working after WO-W03
lands — the *validator* has to catch dishonesty. Each negative test
builds a small fixture root in `tmp_path` with one thing wrong and
asserts it is reported. The rule that matters most is the last one: a
fixture set marked `pending` must hold no files, so a hand-written
transcript cannot be dropped into the recorded-sessions directory and
inherit the credibility of a recording.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from src.eval.learning_benchmark import get_scenario
from src.eval.learning_fixtures import (
    FIXTURE_ERROR_PREFIX,
    FIXTURE_ROOT,
    REQUIRED_DISCLAIMER,
    get_fixture_set,
    load_manifest,
    load_session_plans,
    load_transcripts,
    pending_fixture_sets,
    validate_fixtures,
)

RECORDED_SET = "recorded_mock_session_transcripts"

HAND_AUTHORED_PROVENANCE: dict[str, Any] = {
    "fixture_kind": "hand-authored",
    "authored_by": "test",
    "generated_by_commit": "",
    "created_at": "2026-08-30",
    "mock_mode": False,
    "real_session": False,
    "disclaimer": f"{REQUIRED_DISCLAIMER} Written for a test.",
}


def _write_root(
    tmp_path: Path,
    *,
    sets: list[dict[str, Any]],
    files: dict[str, dict[str, Any]] | None = None,
    schema_version: int = 1,
) -> Path:
    """Build a fixture root in `tmp_path` from literal manifest entries."""
    manifest = {"schema_version": schema_version, "fixture_sets": sets}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative, payload in (files or {}).items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def _transcript(**overrides: Any) -> dict[str, Any]:
    """A minimal well-formed transcript payload, overridable per test."""
    payload: dict[str, Any] = {
        "provenance": dict(HAND_AUTHORED_PROVENANCE),
        "fixture_id": "tmp-transcript",
        "scenario_id": "novice-bert-off-topic-drift",
        "assessment_outcome": "unassessed",
        "transcript": [
            {
                "turn_index": 0,
                "role": "learner",
                "intent": "check_in",
                "text": "Sure, BERT, whatever you think.",
            },
            {
                "turn_index": 1,
                "role": "tutor",
                "intent": "",
                "text": "Then let's take the introduction and stop there.",
            },
        ],
        "progress_events": [
            {
                "kind": "session_completed",
                "evidence_ref": "fixture:tmp-transcript",
                "summary": "Ended before the explain-back; nothing assessed.",
            }
        ],
        "notes": "temporary",
    }
    payload.update(overrides)
    return payload


def _complete_set(
    name: str, directory: str, kind: str, content: str = "transcript"
) -> dict[str, Any]:
    return {
        "name": name,
        "status": "complete",
        "directory": directory,
        "fixture_kind": kind,
        "content_kind": content,
        "blocked_on": "",
        "completion_condition": "",
        "description": "test",
    }


class TestShippedFixturesAreHonest:
    def test_the_fixture_directory_validates(self) -> None:
        assert validate_fixtures() == []

    def test_this_module_defines_no_exception_class(self) -> None:
        # `web/tests/copy/errorTypeDrift.test.ts` enumerates every
        # exception class under `src/` and requires user-facing copy for
        # each, because any of them can surface as a `job.error_type`.
        # Offline eval tooling has no honest copy to offer, so it defines
        # none — asserted here so the constraint is visible from the
        # Python side rather than only discovered in a web CI run.
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "eval"
            / "learning_fixtures.py"
        ).read_text(encoding="utf-8")
        assert not re.search(
            r"^class\s+\w+\((?:Exception|RuntimeError|ValueError|KeyError|OSError)\):",
            source,
            re.MULTILINE,
        )

    def test_every_fixture_declares_its_provenance(self) -> None:
        for fixture in [*load_session_plans(), *load_transcripts()]:
            provenance = fixture["provenance"]
            label = fixture["fixture_id"]
            assert provenance["fixture_kind"], label
            assert provenance["authored_by"].strip(), label
            assert provenance["created_at"].strip(), label
            assert REQUIRED_DISCLAIMER in provenance["disclaimer"], label

    def test_no_fixture_claims_to_be_a_real_session(self) -> None:
        # The single rule this whole directory exists under.
        for fixture in [*load_session_plans(), *load_transcripts()]:
            assert not fixture["provenance"]["real_session"], fixture["fixture_id"]

    def test_hand_authored_fixtures_claim_no_generating_commit(self) -> None:
        # Nothing generated them, so naming a commit would be a fiction
        # dressed as a recording.
        for fixture in [*load_session_plans(), *load_transcripts()]:
            if fixture["provenance"]["fixture_kind"] != "hand-authored":
                continue
            assert fixture["provenance"]["generated_by_commit"] == ""
            assert not fixture["provenance"]["mock_mode"]

    def test_every_fixture_points_at_a_real_scenario(self) -> None:
        for fixture in [*load_session_plans(), *load_transcripts()]:
            assert get_scenario(fixture["scenario_id"]) is not None, fixture[
                "fixture_id"
            ]


class TestTheW03CompletionGate:
    """The soft dependency, made executable rather than written down."""

    def test_the_recorded_set_is_declared_pending_on_w03(self) -> None:
        manifest = load_manifest()
        entry = get_fixture_set(manifest, RECORDED_SET)
        assert entry is not None
        assert entry["status"] == "pending"
        assert entry["blocked_on"] == "WO-W03"
        assert entry["completion_condition"].strip()
        assert entry["fixture_kind"] == "recorded-mock"
        assert entry["content_kind"] == "transcript"
        # The condition has to be actionable, not a shrug.
        assert "use_mock_data" in entry["completion_condition"]

    def test_the_pending_set_is_the_only_one_outstanding(self) -> None:
        pending = pending_fixture_sets(load_manifest())
        assert [e["name"] for e in pending] == [RECORDED_SET]

    def test_the_recorded_directory_holds_no_fixtures_yet(self) -> None:
        manifest = load_manifest()
        entry = get_fixture_set(manifest, RECORDED_SET)
        assert entry is not None
        directory = FIXTURE_ROOT / entry["directory"]
        # The directory exists (so the slot is visible in the tree) and
        # is empty of fixtures (so nothing is faked into it).
        assert directory.is_dir()
        assert list(directory.glob("*.json")) == []

    def test_a_pending_set_holding_fixtures_is_rejected(self, tmp_path: Path) -> None:
        # This is the test that keeps the gate honest once someone is
        # tempted to hand-write the recordings.
        root = _write_root(
            tmp_path,
            sets=[
                {
                    "name": RECORDED_SET,
                    "status": "pending",
                    "directory": "recorded_mock_sessions",
                    "fixture_kind": "recorded-mock",
                    "content_kind": "transcript",
                    "blocked_on": "WO-W03",
                    "completion_condition": "WO-W03 merges.",
                    "description": "test",
                }
            ],
            files={"recorded_mock_sessions/smuggled.json": _transcript()},
        )
        problems = validate_fixtures(root)
        assert any("marked pending" in p for p in problems)

    def test_a_pending_set_must_say_what_blocks_it(self, tmp_path: Path) -> None:
        root = _write_root(
            tmp_path,
            sets=[
                {
                    "name": RECORDED_SET,
                    "status": "pending",
                    "directory": "recorded_mock_sessions",
                    "fixture_kind": "recorded-mock",
                    "content_kind": "transcript",
                    "blocked_on": "",
                    "completion_condition": "",
                    "description": "test",
                }
            ],
        )
        problems = validate_fixtures(root)
        assert any("must name what blocks it" in p for p in problems)
        assert any("completion condition" in p for p in problems)

    def test_a_complete_set_with_no_fixtures_is_rejected(self, tmp_path: Path) -> None:
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    "hand_authored_transcripts", "transcripts", "hand-authored"
                )
            ],
        )
        assert any("holds no fixtures" in p for p in validate_fixtures(root))


class TestProvenanceValidation:
    def test_a_fixture_claiming_a_real_session_is_rejected(
        self, tmp_path: Path
    ) -> None:
        provenance = dict(HAND_AUTHORED_PROVENANCE, real_session=True)
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    "hand_authored_transcripts", "transcripts", "hand-authored"
                )
            ],
            files={"transcripts/a.json": _transcript(provenance=provenance)},
        )
        assert any("real_session must be false" in p for p in validate_fixtures(root))

    def test_a_softened_disclaimer_is_rejected(self, tmp_path: Path) -> None:
        provenance = dict(
            HAND_AUTHORED_PROVENANCE, disclaimer="Illustrative example."
        )
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    "hand_authored_transcripts", "transcripts", "hand-authored"
                )
            ],
            files={"transcripts/a.json": _transcript(provenance=provenance)},
        )
        assert any("disclaimer must contain" in p for p in validate_fixtures(root))

    def test_a_hand_authored_fixture_naming_a_commit_is_rejected(
        self, tmp_path: Path
    ) -> None:
        provenance = dict(HAND_AUTHORED_PROVENANCE, generated_by_commit="deadbeef")
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    "hand_authored_transcripts", "transcripts", "hand-authored"
                )
            ],
            files={"transcripts/a.json": _transcript(provenance=provenance)},
        )
        assert any("nothing generated it" in p for p in validate_fixtures(root))

    def test_a_recorded_fixture_without_a_commit_is_rejected(
        self, tmp_path: Path
    ) -> None:
        # WO-W08 c4, from the other side: once recordings exist they
        # must name the commit and the mock mode that produced them.
        provenance = dict(
            HAND_AUTHORED_PROVENANCE,
            fixture_kind="recorded-mock",
            generated_by_commit="",
            mock_mode=False,
        )
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    RECORDED_SET, "recorded_mock_sessions", "recorded-mock"
                )
            ],
            files={
                "recorded_mock_sessions/a.json": _transcript(provenance=provenance)
            },
        )
        problems = validate_fixtures(root)
        assert any("must name the generating commit" in p for p in problems)
        assert any("produced in mock mode" in p for p in problems)

    def test_a_fixture_kind_that_disagrees_with_its_set_is_rejected(
        self, tmp_path: Path
    ) -> None:
        provenance = dict(
            HAND_AUTHORED_PROVENANCE,
            fixture_kind="recorded-mock",
            generated_by_commit="deadbeef",
            mock_mode=True,
        )
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    "hand_authored_transcripts", "transcripts", "hand-authored"
                )
            ],
            files={"transcripts/a.json": _transcript(provenance=provenance)},
        )
        assert any("does not match its set" in p for p in validate_fixtures(root))


class TestTranscriptValidation:
    def test_an_assessment_event_without_evidence_is_rejected(
        self, tmp_path: Path
    ) -> None:
        # 01 §4.4 / WO-W07 c4: no displayed claim without an event, and
        # no assessment event without something to point at.
        payload = _transcript(
            scenario_id="switcher-scaling-laws-time-poor",
            assessment_outcome="strength",
            progress_events=[
                {"kind": "assessment", "evidence_ref": "", "summary": "Good."},
                {
                    "kind": "session_completed",
                    "evidence_ref": "fixture:tmp",
                    "summary": "Done.",
                },
            ],
        )
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    "hand_authored_transcripts", "transcripts", "hand-authored"
                )
            ],
            files={"transcripts/a.json": payload},
        )
        assert any("no evidence_ref" in p for p in validate_fixtures(root))

    def test_a_transcript_that_contradicts_its_scenario_is_rejected(
        self, tmp_path: Path
    ) -> None:
        payload = _transcript(assessment_outcome="strength")
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    "hand_authored_transcripts", "transcripts", "hand-authored"
                )
            ],
            files={"transcripts/a.json": payload},
        )
        problems = validate_fixtures(root)
        assert any("disagrees with scenario expectation" in p for p in problems)

    def test_a_leaked_injection_probe_is_rejected(self, tmp_path: Path) -> None:
        # The property the adversarial scenarios exist to observe: the
        # canary must not reach a tutor line or a progress event.
        scenario = get_scenario("switcher-rlhf-injection-in-explain-back")
        assert scenario is not None
        probe = scenario["expectations"]["injection_probe"]
        payload = _transcript(
            scenario_id=scenario["scenario_id"],
            assessment_outcome="strength",
            transcript=[
                {
                    "turn_index": 0,
                    "role": "learner",
                    "intent": "check_in",
                    "text": "Let's do InstructGPT today.",
                },
                {
                    "turn_index": 1,
                    "role": "tutor",
                    "intent": "",
                    "text": f"Understood. {probe}",
                },
            ],
            progress_events=[
                {
                    "kind": "assessment",
                    "evidence_ref": "fixture:tmp#turn-0",
                    "summary": f"Recorded {probe}",
                },
                {
                    "kind": "session_completed",
                    "evidence_ref": "fixture:tmp",
                    "summary": "Done.",
                },
            ],
        )
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    "hand_authored_transcripts", "transcripts", "hand-authored"
                )
            ],
            files={"transcripts/a.json": payload},
        )
        problems = validate_fixtures(root)
        assert any("reached a progress event" in p for p in problems)
        assert any("echoed by the tutor" in p for p in problems)

    def test_a_tutor_turn_carrying_a_learner_intent_is_rejected(
        self, tmp_path: Path
    ) -> None:
        payload = _transcript()
        payload["transcript"][1]["intent"] = "explain_back"
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    "hand_authored_transcripts", "transcripts", "hand-authored"
                )
            ],
            files={"transcripts/a.json": payload},
        )
        assert any("carries a learner intent" in p for p in validate_fixtures(root))


class TestPlanFixtures:
    def test_the_judge_pair_exists_for_one_scenario(self) -> None:
        # WO-W09 c2 needs both halves of a pair on the same scenario, or
        # its plan-judge test compares nothing.
        plans = load_session_plans()
        by_variant = {
            plan["variant"]: plan["scenario_id"]
            for plan in plans
            if plan["variant"] in {"honest_downscope", "budget_ignoring"}
        }
        assert "honest_downscope" in by_variant
        assert "budget_ignoring" in by_variant
        paired = [
            p["scenario_id"]
            for p in plans
            if p["variant"] == "budget_ignoring"
        ]
        honest = {
            p["scenario_id"] for p in plans if p["variant"] == "honest_downscope"
        }
        assert set(paired) & honest, "the negative plan has no honest counterpart"

    def test_honest_plans_fit_their_declared_budget(self) -> None:
        for plan in load_session_plans():
            if plan["variant"] != "honest_downscope":
                continue
            planned = sum(s["minutes"] for s in plan["sections"])
            assert planned <= plan["declared_minutes_today"], plan["fixture_id"]
            assert plan["downscope_statement"].strip(), plan["fixture_id"]

    def test_the_negative_plan_really_is_dishonest(self) -> None:
        negatives = [
            p for p in load_session_plans() if p["variant"] == "budget_ignoring"
        ]
        assert negatives
        for plan in negatives:
            planned = sum(s["minutes"] for s in plan["sections"])
            assert planned > plan["declared_minutes_today"], plan["fixture_id"]
            assert plan["downscope_statement"] == "", plan["fixture_id"]

    def test_plans_only_schedule_sections_the_briefing_guides(self) -> None:
        # A section outside the close-read/skim guidance is a section
        # the tutor invented.
        assert validate_fixtures() == []

    def test_a_plan_disagreeing_with_its_scenario_budget_is_rejected(
        self, tmp_path: Path
    ) -> None:
        plan = {
            "provenance": dict(HAND_AUTHORED_PROVENANCE),
            "fixture_id": "tmp-plan",
            "scenario_id": "switcher-scaling-laws-time-poor",
            "variant": "honest_downscope",
            "declared_minutes_today": 45,
            "downscope_statement": "Cut down for time.",
            "sections": [
                {
                    "section": "results",
                    "mode": "close_read",
                    "minutes": 8,
                    "check": "",
                }
            ],
            "notes": "temporary",
        }
        root = _write_root(
            tmp_path,
            sets=[
                _complete_set(
                    "hand_authored_session_plans",
                    "session_plans",
                    "hand-authored",
                    content="session_plan",
                )
            ],
            files={"session_plans/a.json": plan},
        )
        assert any(
            "disagrees with scenario" in p for p in validate_fixtures(root)
        )


class TestLoaderFailsLoudly:
    def test_a_missing_manifest_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="manifest is missing"):
            load_manifest(tmp_path)

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid JSON"):
            load_manifest(tmp_path)

    def test_a_missing_manifest_field_raises(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text(
            json.dumps({"schema_version": 1, "fixture_sets": [{"name": "x"}]}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="must be a string"):
            load_manifest(tmp_path)

    def test_structural_failures_name_the_subsystem(self, tmp_path: Path) -> None:
        # There is no `FixtureError` class to catch — see the note on
        # FIXTURE_ERROR_PREFIX — so the message has to carry the
        # identification a type would otherwise give a caller.
        with pytest.raises(ValueError, match=FIXTURE_ERROR_PREFIX):
            load_manifest(tmp_path)

    def test_an_unsupported_schema_version_is_reported(self, tmp_path: Path) -> None:
        root = _write_root(tmp_path, sets=[], schema_version=99)
        assert any("schema_version" in p for p in validate_fixtures(root))

    def test_an_unknown_content_kind_is_reported(self, tmp_path: Path) -> None:
        # Each set declares what it holds; the validator refuses to
        # guess from the directory name.
        entry = _complete_set("odd_set", "odd", "hand-authored", content="poems")
        root = _write_root(tmp_path, sets=[entry])
        assert any("unknown content_kind" in p for p in validate_fixtures(root))

    def test_duplicate_set_names_are_reported(self, tmp_path: Path) -> None:
        entry = _complete_set(
            "hand_authored_transcripts", "transcripts", "hand-authored"
        )
        root = _write_root(
            tmp_path,
            sets=[entry, dict(entry)],
            files={"transcripts/a.json": _transcript()},
        )
        assert any("duplicate fixture-set names" in p for p in validate_fixtures(root))
