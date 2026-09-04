"""Unit tests for run provenance — ADR 0070's third deliverable.

The block is what makes a summary row comparable to another run, so
these tests pin the two properties that matter: it is *complete* (every
field a comparison needs is there and non-empty), and it is *honest*
(an unresolvable commit says "unknown" rather than inventing one, a
`code_dirty` nobody could check is `None` rather than `False`).

Pure logic and one `git` subprocess, patched out where the answer
matters. No model calls, no network.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from typing import Any

import pytest

from src.config import Settings
from src.eval import provenance as prov
from src.eval.provenance import (
    PROVENANCE_KEY,
    PROVENANCE_PRESENT_FIELDS,
    PROVENANCE_REQUIRED_FIELDS,
    UNKNOWN_COMMIT,
    CodeRevision,
    Rubric,
    capture,
    check_provenance,
    dataset_fingerprint,
    judge_model,
    provenance_markdown,
    rubric_versions,
    seed_campaign,
)

pytestmark = pytest.mark.unit

#: The real `_git`, captured before the autouse fixture below replaces
#: it, so the subprocess wrapper can be tested on its own terms.
_REAL_GIT = prov._git

_RUBRICS = (
    Rubric(name="beta", version="2.1.0", prompt="second"),
    Rubric(name="alpha", version="1.0.0", prompt="first"),
)


def _fake_git(clean_sha: str) -> Any:
    """A `_git` stand-in reporting `clean_sha` on a clean worktree."""

    def _git(*args: str) -> str | None:
        return clean_sha if args[0] == "rev-parse" else ""

    return _git


@pytest.fixture(autouse=True)
def _stable_revision(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin the commit so a dirty worktree cannot move an assertion.

    Patched at `_git` rather than at `code_revision` so the resolution
    logic under test stays real, and `code_revision`'s process-wide
    `lru_cache` is cleared on both sides of every test so one patched
    answer never leaks into the next.
    """
    prov.code_revision.cache_clear()
    monkeypatch.setattr(prov, "_git", _fake_git("a" * 40))
    yield
    prov.code_revision.cache_clear()


def _settings(**overrides: Any) -> Settings:
    return Settings(**overrides)


class TestJudgeModel:
    def test_reads_the_pinned_judge_setting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prov, "settings", _settings(eval_judge_model="judge-x"))
        assert judge_model() == "judge-x"

    def test_does_not_follow_the_product_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The whole defect ADR 0070 closes: upgrading the product model
        # must not move the ruler it is measured with.
        monkeypatch.setattr(
            prov,
            "settings",
            _settings(anthropic_model="product-v2", eval_judge_model="judge-v1"),
        )
        assert judge_model() == "judge-v1"

    def test_an_empty_judge_model_is_refused_at_settings_load(self) -> None:
        # No silent fallback: an empty value used to mean "inherit the
        # product model", which is the behaviour being removed.
        with pytest.raises(ValueError):
            _settings(eval_judge_model="")


class TestRubricVersions:
    def test_maps_names_to_versions(self) -> None:
        assert rubric_versions(_RUBRICS) == {"alpha": "1.0.0", "beta": "2.1.0"}

    def test_is_sorted_so_two_rows_compare_byte_for_byte(self) -> None:
        assert list(rubric_versions(_RUBRICS)) == ["alpha", "beta"]

    def test_an_empty_registry_is_an_empty_map(self) -> None:
        assert rubric_versions(()) == {}


class TestDatasetFingerprint:
    def test_names_the_dataset_and_its_size(self) -> None:
        version = dataset_fingerprint("bench", [{"a": 1}, {"a": 2}])
        assert version.startswith("bench@2:")

    def test_is_stable_across_calls(self) -> None:
        items = [{"query_id": "q", "topics": ["x", "y"]}]
        assert dataset_fingerprint("b", items) == dataset_fingerprint("b", items)

    def test_moves_when_any_field_changes(self) -> None:
        before = dataset_fingerprint("b", [{"q": "why?"}])
        after = dataset_fingerprint("b", [{"q": "why not?"}])
        assert before != after

    def test_moves_when_an_item_is_added(self) -> None:
        before = dataset_fingerprint("b", [{"q": "a"}])
        after = dataset_fingerprint("b", [{"q": "a"}, {"q": "b"}])
        assert before != after

    def test_is_insensitive_to_key_order_within_an_item(self) -> None:
        left = dataset_fingerprint("b", [{"a": 1, "z": 2}])
        right = dataset_fingerprint("b", [{"z": 2, "a": 1}])
        assert left == right

    def test_is_sensitive_to_item_order(self) -> None:
        # The benchmark's order is part of the benchmark: `--queries`
        # subsets and the summary table both read it.
        left = dataset_fingerprint("b", [{"q": "a"}, {"q": "b"}])
        right = dataset_fingerprint("b", [{"q": "b"}, {"q": "a"}])
        assert left != right

    def test_a_non_serialisable_value_does_not_raise(self) -> None:
        assert dataset_fingerprint("b", [{"when": object()}])


class TestCodeRevision:
    def test_git_head_is_preferred_and_carries_dirtiness(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            prov, "_git", lambda *args: "b" * 40 if args[0] == "rev-parse" else " M x.py"
        )
        prov.code_revision.cache_clear()
        assert prov.code_revision() == CodeRevision(commit="b" * 40, dirty=True)

    def test_a_clean_tree_reports_dirty_false(self) -> None:
        assert prov.code_revision() == CodeRevision(commit="a" * 40, dirty=False)

    def test_an_unreadable_status_leaves_dirtiness_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            prov, "_git", lambda *args: "e" * 40 if args[0] == "rev-parse" else None
        )
        prov.code_revision.cache_clear()
        assert prov.code_revision().dirty is None

    def test_falls_back_to_the_ci_sha_with_unknown_dirtiness(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prov, "_git", lambda *args: None)
        monkeypatch.setenv("GITHUB_SHA", "d" * 40)
        prov.code_revision.cache_clear()
        revision = prov.code_revision()
        assert revision.commit == "d" * 40
        # Not False: nobody checked, and "not checked" is a different
        # claim from "checked and clean".
        assert revision.dirty is None

    def test_says_unknown_rather_than_inventing_a_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prov, "_git", lambda *args: None)
        monkeypatch.delenv("GITHUB_SHA", raising=False)
        prov.code_revision.cache_clear()
        assert prov.code_revision() == CodeRevision(UNKNOWN_COMMIT, None)

    def test_a_blank_ci_sha_is_not_a_revision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prov, "_git", lambda *args: None)
        monkeypatch.setenv("GITHUB_SHA", "   ")
        prov.code_revision.cache_clear()
        assert prov.code_revision().commit == UNKNOWN_COMMIT

    def test_the_answer_is_cached_for_the_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A campaign's revision cannot change under it, and the
        # alternative is two subprocesses per record.
        calls: list[str] = []

        def _counting(*args: str) -> str:
            calls.append(args[0])
            return "f" * 40 if args[0] == "rev-parse" else ""

        monkeypatch.setattr(prov, "_git", _counting)
        prov.code_revision.cache_clear()
        prov.code_revision()
        prov.code_revision()
        assert calls == ["rev-parse", "status"]


class TestGitQuery:
    """`_git` itself, with the real body restored under the fixture."""

    @pytest.fixture(autouse=True)
    def _real_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(prov, "_git", _REAL_GIT)

    def test_a_failing_git_is_reported_as_none_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise OSError("git is not installed")

        monkeypatch.setattr(subprocess, "run", _boom)
        assert prov._git("rev-parse", "HEAD") is None

    def test_a_non_zero_git_exit_is_reported_as_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Result:
            returncode = 128
            stdout = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
        assert prov._git("rev-parse", "HEAD") is None

    def test_a_git_timeout_is_reported_as_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _slow(*args: Any, **kwargs: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd="git", timeout=5.0)

        monkeypatch.setattr(subprocess, "run", _slow)
        assert prov._git("status", "--porcelain") is None

    def test_a_successful_git_call_returns_stripped_stdout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Result:
            returncode = 0
            stdout = "  deadbeef\n"

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
        assert prov._git("rev-parse", "HEAD") == "deadbeef"


class TestSeedCampaign:
    def test_returns_the_configured_seed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prov, "settings", _settings(eval_seed=7))
        assert seed_campaign() == 7

    def test_an_explicit_seed_wins_over_the_setting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(prov, "settings", _settings(eval_seed=7))
        assert seed_campaign(11) == 11

    def test_seeding_makes_the_harness_draw_reproducibly(self) -> None:
        import random

        seed_campaign(3)
        first = [random.random() for _ in range(5)]
        seed_campaign(3)
        assert [random.random() for _ in range(5)] == first

    def test_numpy_being_absent_is_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # numpy arrives via torch on the embedding paths and may simply
        # not be loaded in a lean process; seeding must not require it.
        import sys

        monkeypatch.delitem(sys.modules, "numpy", raising=False)
        assert seed_campaign(4) == 4


class TestCapture:
    def test_records_every_field_a_comparison_needs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            prov,
            "settings",
            _settings(
                anthropic_model="product-v9",
                eval_judge_model="judge-v3",
                eval_seed=5,
                use_mock_data=True,
            ),
        )
        block = capture(tier="scripted", dataset_version="d@1:abc", rubrics=_RUBRICS)
        assert block["judge_model"] == "judge-v3"
        assert block["product_model"] == "product-v9"
        assert block["rubric_versions"] == {"alpha": "1.0.0", "beta": "2.1.0"}
        assert block["code_commit"] == "a" * 40
        assert block["code_dirty"] is False
        assert block["dataset_version"] == "d@1:abc"
        assert block["tier"] == "scripted"
        assert block["seed"] == 5
        assert block["mock_mode"] is True
        assert block["harness_version"] == prov.HARNESS_VERSION

    def test_the_captured_block_passes_its_own_check(self) -> None:
        block = capture(tier="research", dataset_version="d@1:abc", rubrics=_RUBRICS)
        assert check_provenance(dict(block)) == []

    def test_records_whether_the_run_was_against_mock_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The question that decides whether a research row means
        # anything at all.
        monkeypatch.setattr(prov, "settings", _settings(use_mock_data=False))
        assert capture(tier="research", dataset_version="d", rubrics=())["mock_mode"] is False

    def test_captured_at_is_an_iso_utc_instant(self) -> None:
        block = capture(tier="research", dataset_version="d", rubrics=())
        assert block["captured_at"].endswith("+00:00")

    def test_an_explicit_seed_is_recorded_without_reseeding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import random

        monkeypatch.setattr(prov, "settings", _settings(eval_seed=1))
        random.seed(99)
        drawn = random.random()
        random.seed(99)
        block = capture(tier="research", dataset_version="d", rubrics=(), seed=42)
        assert block["seed"] == 42
        # Capturing must not perturb a campaign's generator state.
        assert random.random() == drawn


class TestCheckProvenance:
    def _block(self, **overrides: Any) -> dict[str, Any]:
        block = dict(capture(tier="scripted", dataset_version="d@1:x", rubrics=_RUBRICS))
        block.update(overrides)
        return block

    def test_a_complete_block_has_no_problems(self) -> None:
        assert check_provenance(self._block()) == []

    def test_a_missing_block_is_reported_not_ignored(self) -> None:
        assert check_provenance(None)

    def test_a_non_object_block_is_reported(self) -> None:
        assert check_provenance("provenance: yes")

    @pytest.mark.parametrize("field", PROVENANCE_REQUIRED_FIELDS)
    def test_every_required_field_must_be_present(self, field: str) -> None:
        block = self._block()
        del block[field]
        assert any(field in problem for problem in check_provenance(block))

    @pytest.mark.parametrize("field", PROVENANCE_REQUIRED_FIELDS)
    def test_every_required_field_must_be_non_empty(self, field: str) -> None:
        assert any(
            field in problem for problem in check_provenance(self._block(**{field: "  "}))
        )

    @pytest.mark.parametrize("field", PROVENANCE_REQUIRED_FIELDS)
    def test_a_non_string_required_field_is_reported(self, field: str) -> None:
        assert any(
            field in problem for problem in check_provenance(self._block(**{field: 3}))
        )

    @pytest.mark.parametrize("field", PROVENANCE_PRESENT_FIELDS)
    def test_present_fields_must_exist(self, field: str) -> None:
        block = self._block()
        del block[field]
        assert any(field in problem for problem in check_provenance(block))

    @pytest.mark.parametrize("field", PROVENANCE_PRESENT_FIELDS)
    def test_present_fields_may_be_falsy(self, field: str) -> None:
        # Seed 0 is a seed; `mock_mode=False` is a funded campaign's
        # answer; `code_dirty=None` means "could not tell".
        assert check_provenance(self._block(**{field: None})) == []

    def test_an_empty_rubric_map_is_reported(self) -> None:
        assert any(
            "rubric_versions" in problem
            for problem in check_provenance(self._block(rubric_versions={}))
        )

    def test_a_rubric_map_with_an_empty_version_is_reported(self) -> None:
        assert any(
            "rubric_versions" in problem
            for problem in check_provenance(self._block(rubric_versions={"a": ""}))
        )

    def test_a_rubric_map_that_is_not_a_map_is_reported(self) -> None:
        assert any(
            "rubric_versions" in problem
            for problem in check_provenance(self._block(rubric_versions=["a@1"]))
        )

    def test_every_problem_is_reported_not_just_the_first(self) -> None:
        block = self._block(judge_model="", code_commit="", dataset_version="")
        assert len(check_provenance(block)) >= 3


class TestProvenanceMarkdown:
    def _row(self, **overrides: Any) -> dict[str, Any]:
        block = dict(capture(tier="scripted", dataset_version="d@1:x", rubrics=_RUBRICS))
        block.update(overrides)
        return {"record_id": "s.r1", PROVENANCE_KEY: block}

    def test_no_blocks_renders_nothing(self) -> None:
        assert provenance_markdown([{"record_id": "s.r1"}]) == []

    def test_a_uniform_campaign_prints_each_field_once(self) -> None:
        rendered = "\n".join(provenance_markdown([self._row(), self._row()]))
        assert "## Provenance" in rendered
        assert "MIXED" not in rendered
        assert "judge_model" in rendered

    def test_rubric_versions_are_rendered_as_name_at_version(self) -> None:
        rendered = "\n".join(provenance_markdown([self._row()]))
        assert "alpha@1.0.0, beta@2.1.0" in rendered

    def test_a_campaign_that_changed_judges_mid_flight_is_called_out(self) -> None:
        rows = [self._row(judge_model="judge-a"), self._row(judge_model="judge-b")]
        rendered = "\n".join(provenance_markdown(rows))
        assert "MIXED" in rendered
        assert "not produced by one configuration" in rendered

    def test_a_campaign_with_differing_rubric_versions_is_called_out(self) -> None:
        rows = [self._row(), self._row(rubric_versions={"alpha": "9.9.9"})]
        assert "MIXED" in "\n".join(provenance_markdown(rows))

    def test_unattributable_rows_are_counted_rather_than_dropped(self) -> None:
        rows = [self._row(), {"record_id": "s.r2"}]
        rendered = "\n".join(provenance_markdown(rows))
        assert "1 of 2 row(s) carry no provenance block" in rendered
