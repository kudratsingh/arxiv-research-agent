"""The mechanism that stops a judge prompt moving under a stale version.

ADR 0070's second deliverable is rubric versioning, and a version
constant nobody checks is the honour system with extra steps. The lock
file `tests/fixtures/eval/rubric_lock.json` records, per rubric, the
history of `(version, sha256-of-prompt)` pairs this repository has
shipped. These tests hold the live registry against it:

  - the live text must match the newest locked entry, so an edit to a
    prompt fails until the lock is updated;
  - each rubric's history must carry distinct versions and distinct
    digests, so the only way to re-lock is to *append* an entry under a
    version that has never been used — which is exactly "bump the
    version when you change the text";
  - and every rubric the harness defines must be in the lock at all, so
    a new judge cannot arrive unversioned.

What this does **not** claim: a determined edit can overwrite the last
entry in place rather than appending. That is the standard bound on any
checked-in baseline — it defends against forgetting, not against
intent — and the overwrite is visible as an overwrite in the diff. See
ADR 0070.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from src.eval.learning_metrics import LEARNING_RUBRICS
from src.eval.metrics import RESEARCH_RUBRICS
from src.eval.provenance import Rubric

pytestmark = pytest.mark.unit

LOCK_PATH = Path(__file__).resolve().parent / "fixtures" / "eval" / "rubric_lock.json"

#: Every rubric the harness defines. Not the campaign subsets — a judge
#: prompt that only the calibration path calls is still a prompt whose
#: edit rebaselines something.
ALL_RUBRICS: tuple[Rubric, ...] = tuple(sorted(RESEARCH_RUBRICS + LEARNING_RUBRICS))


def _lock() -> dict[str, Any]:
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _history(name: str) -> list[dict[str, str]]:
    entries = _lock()["rubrics"][name]
    assert isinstance(entries, list) and entries
    return [dict(entry) for entry in entries]


class TestTheLockCoversEveryRubric:
    def test_the_lock_file_is_readable_and_versioned(self) -> None:
        assert _lock()["schema_version"] == 1

    def test_every_defined_rubric_appears_in_the_lock(self) -> None:
        locked = set(_lock()["rubrics"])
        defined = {rubric.name for rubric in ALL_RUBRICS}
        assert defined <= locked, f"unversioned rubric(s): {sorted(defined - locked)}"

    def test_the_lock_names_no_rubric_the_harness_dropped(self) -> None:
        # A stale entry is a rubric that was deleted without the lock
        # being tidied; it would let a future rubric silently reuse the
        # name and inherit somebody else's version history.
        locked = set(_lock()["rubrics"])
        defined = {rubric.name for rubric in ALL_RUBRICS}
        assert locked <= defined, f"stale lock entry: {sorted(locked - defined)}"

    def test_rubric_names_are_unique_across_both_registries(self) -> None:
        names = [rubric.name for rubric in ALL_RUBRICS]
        assert len(names) == len(set(names))


class TestTheLiveTextMatchesItsLockedVersion:
    @pytest.mark.parametrize("rubric", ALL_RUBRICS, ids=lambda r: r.name)
    def test_the_prompt_digest_matches_the_newest_locked_entry(
        self, rubric: Rubric
    ) -> None:
        newest = _history(rubric.name)[-1]
        assert rubric.digest == newest["sha256"], (
            f"{rubric.name}'s prompt text has changed. Bump "
            f"{rubric.name.upper()}_RUBRIC_VERSION and append a new "
            f"{{version, sha256}} entry to {LOCK_PATH.name}; scores from "
            "before and after this edit are not comparable."
        )

    @pytest.mark.parametrize("rubric", ALL_RUBRICS, ids=lambda r: r.name)
    def test_the_version_constant_matches_the_newest_locked_entry(
        self, rubric: Rubric
    ) -> None:
        assert rubric.version == _history(rubric.name)[-1]["version"]

    @pytest.mark.parametrize("rubric", ALL_RUBRICS, ids=lambda r: r.name)
    def test_a_version_is_never_reused_for_different_text(
        self, rubric: Rubric
    ) -> None:
        versions = [entry["version"] for entry in _history(rubric.name)]
        digests = [entry["sha256"] for entry in _history(rubric.name)]
        assert len(versions) == len(set(versions)), f"{rubric.name} reuses a version"
        assert len(digests) == len(set(digests)), f"{rubric.name} reuses a digest"


class TestTheMechanismActuallyFires:
    """The lock is only worth having if a prompt edit breaks it."""

    def test_an_edited_prompt_no_longer_matches_its_locked_digest(self) -> None:
        original = ALL_RUBRICS[0]
        edited = Rubric(
            name=original.name,
            version=original.version,
            prompt=original.prompt + "\nBe extra strict.\n",
        )
        assert edited.digest != _history(original.name)[-1]["sha256"]

    def test_the_digest_is_a_sha256_of_the_prompt_text(self) -> None:
        rubric = ALL_RUBRICS[0]
        assert rubric.digest == hashlib.sha256(rubric.prompt.encode("utf-8")).hexdigest()

    def test_two_rubrics_with_the_same_text_share_a_digest(self) -> None:
        left = Rubric(name="a", version="1.0.0", prompt="same text")
        right = Rubric(name="b", version="9.9.9", prompt="same text")
        assert left.digest == right.digest


class TestTheCampaignSubsetsAreHonest:
    def test_the_research_campaign_records_only_prompted_metrics(self) -> None:
        # `citation_accuracy` is pure regex; a rubric version for it
        # would be provenance theatre.
        assert {r.name for r in RESEARCH_RUBRICS} == {
            "completeness",
            "faithfulness",
            "retrieval_recall",
        }

    def test_the_simulation_subset_is_narrower_than_the_registry(self) -> None:
        from src.eval.learning_metrics import SIMULATION_RUBRICS

        assert set(SIMULATION_RUBRICS) < set(LEARNING_RUBRICS)
        assert "explain_back" not in {r.name for r in SIMULATION_RUBRICS}
