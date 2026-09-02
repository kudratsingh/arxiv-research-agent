"""Tests for the recorded mock-session fixtures and their recorder.

The checked-in fixtures under `tests/fixtures/learning/recorded_mock_sessions/`
claim to be recordings of the session graph. Two properties make that
claim checkable rather than decorative, and this module asserts both:

  - **Determinism.** Recording the same scenario twice from the same
    code produces byte-identical files. Without it a fixture cannot be a
    baseline — every re-record would look like a change.
  - **Freshness.** The files in the repository are what the *current*
    graph produces, not what some earlier one did. Stamped with the
    provenance the checked-in files already carry, a fresh recording
    must reproduce them byte for byte.

The freshness test is deliberately strict, and when it fails the fix is
to re-record (`make record-learning-fixtures`), not to loosen it: a
change in tutor copy or plan shape *should* show up as a diff in the
files that claim to be recordings of it.

Zero spend: the session graph runs in mock mode with the disabled-key
sentinel, so nothing here constructs an Anthropic client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.eval import record_learning_fixtures as rec
from src.eval import simulate_learner as sim
from src.eval.learning_benchmark import LEARNING_SCENARIOS
from src.eval.learning_fixtures import (
    FIXTURE_ROOT,
    RECORDED_SET_NAME,
    RECORDED_UNGRADED,
    SIMULATOR_FILLER_INTENT,
    get_fixture_set,
    load_manifest,
    validate_fixtures,
)

pytestmark = pytest.mark.integration

FIXED_COMMIT = "0" * 40
FIXED_DATE = "2026-01-01"


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    """The canonical mock-mode configuration, per `test_simulate_learner`."""
    values: dict[str, object] = {
        "anthropic_api_key": "local-preview-disabled",
        "use_mock_data": True,
        "enable_api_auth": True,
        "api_keys": "alice:sk_alice",
        "enable_checkpointing": True,
        "checkpoint_backend": "sqlite",
        "checkpoint_db_path": str(tmp_path / "record.sqlite"),
        "enable_learner_profile": True,
        "enable_session_loop": True,
        "enable_prompt_isolation": True,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _patch_settings(monkeypatch: pytest.MonkeyPatch, configured: Settings) -> None:
    """Rebind `settings` on every module the recording path reads it from."""
    from src.agents import assessment as assessment_module
    from src.agents import tutor as tutor_module
    from src.graph import workflow as workflow_module
    from src.learning import memory as memory_module

    for module in (
        tutor_module,
        assessment_module,
        memory_module,
        workflow_module,
        sim,
        rec,
    ):
        monkeypatch.setattr(module, "settings", configured)


@pytest.fixture(autouse=True)
def _zero_spend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Pin the free path, and make any client construction fatal.

    `src.llm._get_client` is the choke point every paid call funnels
    through, so exploding there proves the recording costs nothing —
    the WO-W03 c5 assertion, applied to the recorder.
    """
    import src.llm as llm_module

    _patch_settings(monkeypatch, _settings(tmp_path))

    def _boom() -> Any:
        raise AssertionError("Anthropic client constructed while recording fixtures")

    monkeypatch.setattr(llm_module, "_get_client", _boom)


def _recorded_dir() -> Path:
    entry = get_fixture_set(load_manifest(), RECORDED_SET_NAME)
    assert entry is not None
    return FIXTURE_ROOT / entry["directory"]


def _seed_manifest(root: Path) -> None:
    """Seed a scratch fixture root with the recorded set's manifest entry.

    Only that entry: the hand-authored sets' files are not copied, and a
    `complete` set with no files is (correctly) a validation failure.
    """
    root.mkdir(parents=True, exist_ok=True)
    real = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    trimmed = {
        "schema_version": real["schema_version"],
        "fixture_sets": [
            entry
            for entry in real["fixture_sets"]
            if entry["name"] == RECORDED_SET_NAME
        ],
    }
    (root / "manifest.json").write_text(json.dumps(trimmed), encoding="utf-8")


def _record_into(root: Path, *, commit: str = FIXED_COMMIT) -> dict[str, str]:
    """Record the whole set into `root`; return `{filename: bytes-as-text}`."""
    _seed_manifest(root)
    written = rec.record_fixtures(root, commit=commit, created_at=FIXED_DATE)
    return {path.name: path.read_text(encoding="utf-8") for path in written}


class TestDeterminism:
    def test_two_recordings_of_the_same_code_are_byte_identical(
        self, tmp_path: Path
    ) -> None:
        first = _record_into(tmp_path / "one")
        second = _record_into(tmp_path / "two")
        assert set(first) == set(second)
        for name, text in first.items():
            assert text == second[name], name

    def test_the_commit_stamp_is_the_only_thing_a_re_record_may_move(
        self, tmp_path: Path
    ) -> None:
        # "Byte-identical apart from the commit stamp": the same
        # recording under a different commit differs in exactly that
        # field and nothing else.
        first = _record_into(tmp_path / "one", commit=FIXED_COMMIT)
        second = _record_into(tmp_path / "two", commit="1" * 40)
        for name, text in first.items():
            a = json.loads(text)
            b = json.loads(second[name])
            assert a["provenance"]["generated_by_commit"] != b["provenance"][
                "generated_by_commit"
            ]
            a["provenance"].pop("generated_by_commit")
            b["provenance"].pop("generated_by_commit")
            assert a == b, name

    def test_the_session_run_id_is_canonicalized(self, tmp_path: Path) -> None:
        # The graph mints a fresh run id per session and writes it into
        # every evidence ref; the recorder rewrites it to a stable one
        # derived from the scenario id, which is what makes the files
        # reproducible at all.
        recorded = _record_into(tmp_path / "one")
        for scenario in LEARNING_SCENARIOS:
            payload = json.loads(recorded[f"{scenario['scenario_id']}.json"])
            expected = rec.deterministic_run_id(scenario["scenario_id"])
            refs = [e["evidence_ref"] for e in payload["progress_events"]]
            assert refs, scenario["scenario_id"]
            for ref in refs:
                assert expected in ref, (scenario["scenario_id"], ref)

    def test_deterministic_run_ids_are_distinct_per_scenario(self) -> None:
        ids = {rec.deterministic_run_id(s["scenario_id"]) for s in LEARNING_SCENARIOS}
        assert len(ids) == len(LEARNING_SCENARIOS)


class TestTheCheckedInSetIsFresh:
    def test_a_fresh_recording_reproduces_the_committed_files(
        self, tmp_path: Path
    ) -> None:
        directory = _recorded_dir()
        committed = {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(directory.glob("*.json"))
        }
        assert committed, "the recorded fixture set is empty"

        # Re-record with each file's own provenance stamp so only the
        # recorded *content* is under comparison.
        sample = json.loads(next(iter(committed.values())))
        provenance = sample["provenance"]
        _seed_manifest(tmp_path)
        written = rec.record_fixtures(
            tmp_path,
            commit=provenance["generated_by_commit"],
            created_at=provenance["created_at"],
        )
        fresh = {path.name: path.read_text(encoding="utf-8") for path in written}

        assert set(fresh) == set(committed)
        for name, text in committed.items():
            assert text == fresh[name], (
                f"{name} no longer matches what the session graph produces. "
                "Re-record with `make record-learning-fixtures` and commit "
                "the diff — do not relax this test."
            )

    def test_every_committed_recording_shares_one_provenance_stamp(self) -> None:
        # A set recorded in one pass; a file with a different commit is a
        # partial re-record someone forgot to finish.
        stamps = set()
        for path in _recorded_dir().glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            stamps.add(
                (
                    payload["provenance"]["generated_by_commit"],
                    payload["provenance"]["created_at"],
                )
            )
        assert len(stamps) == 1


class TestRecordedContent:
    def test_the_recorded_set_validates(self) -> None:
        assert validate_fixtures() == []

    def test_filler_turns_are_labelled_as_the_harness_speaking(self) -> None:
        # The graph offers more pauses than a 2-4 turn script fills. The
        # recording must say which turns the simulator wrote rather than
        # passing them off as scenario intents.
        seen = False
        for path in _recorded_dir().glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for turn in payload["transcript"]:
                if turn["intent"] == SIMULATOR_FILLER_INTENT:
                    seen = True
                    assert turn["role"] == "learner"
        assert seen, "no filler turn recorded — the fixtures cannot prove the label"

    def test_turn_indices_are_dense_and_roles_alternate(self) -> None:
        for path in _recorded_dir().glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            turns = payload["transcript"]
            assert turns, path.name
            assert [t["turn_index"] for t in turns] == list(range(len(turns)))
            for turn in turns:
                assert turn["role"] in ("tutor", "learner"), path.name
                assert turn["text"].strip(), path.name

    def test_an_injection_probe_never_reaches_a_recorded_control_field(self) -> None:
        # ADR 0020, observed in the artifact rather than asserted about
        # it: the adversarial scenarios' canaries appear in the learner's
        # own turns and nowhere else.
        probes = {
            s["scenario_id"]: s["expectations"]["injection_probe"]
            for s in LEARNING_SCENARIOS
            if s["expectations"]["injection_probe"]
        }
        assert probes, "no adversarial scenario to check"
        for scenario_id, probe in probes.items():
            payload = json.loads(
                (_recorded_dir() / f"{scenario_id}.json").read_text(encoding="utf-8")
            )
            for event in payload["progress_events"]:
                assert probe not in event["evidence_ref"], scenario_id
                assert probe not in event["summary"], scenario_id
            for turn in payload["transcript"]:
                if turn["role"] == "tutor":
                    assert probe not in turn["text"], scenario_id

    def test_no_recording_claims_an_outcome_the_graph_did_not_reach(self) -> None:
        for path in _recorded_dir().glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["assessment_outcome"] in (
                RECORDED_UNGRADED,
                "unassessed",
            ), path.name


class TestRecorderRefusals:
    def test_recording_outside_mock_mode_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path
    ) -> None:
        _patch_settings(monkeypatch, _settings(tmp_path, use_mock_data=False))
        assert rec.main([]) == 1
        assert "USE_MOCK_DATA=true" in capsys.readouterr().err

    def test_recording_without_a_checkpointer_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path
    ) -> None:
        _patch_settings(
            monkeypatch,
            _settings(
                tmp_path, enable_checkpointing=False, enable_session_loop=False
            ),
        )
        assert rec.main([]) == 1
        assert "ENABLE_CHECKPOINTING=true" in capsys.readouterr().err

    def test_recording_without_a_commit_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path
    ) -> None:
        # A recorded fixture that names no commit cannot be reproduced,
        # and `validate_provenance` rejects it — so the recorder stops
        # before writing rather than writing something invalid.
        monkeypatch.setattr(rec, "current_commit", lambda: "")
        assert rec.main(["--root", str(tmp_path)]) == 1
        assert "generating commit" in capsys.readouterr().err
        assert list(tmp_path.glob("**/*.json")) == []

    def test_the_cli_records_and_validates(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        _seed_manifest(tmp_path)
        code = rec.main(
            [
                "--root",
                str(tmp_path),
                "--commit",
                FIXED_COMMIT,
                "--created-at",
                FIXED_DATE,
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert f"Recorded {len(LEARNING_SCENARIOS)} transcript(s)" in out
        assert "Fixture set validates." in out
