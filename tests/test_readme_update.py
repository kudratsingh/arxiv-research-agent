"""Tests for the eval-summary → README block updater."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.eval.readme_update import (
    END_MARKER,
    START_MARKER,
    main,
    patch_readme,
    render_block,
)


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "query_id": "q",
        "elapsed_sec": 40.0,
        "error": None,
        "citation_accuracy": 1.0,
        "completeness": 0.8,
        "faithfulness": 0.9,
        "retrieval_recall": 0.75,
        "total_citations": 3,
        "critic_score": 0.85,
        "iterations": 1,
        "cost_usd": 0.05,
        "llm_calls": 8,
        "judge_cost_usd": 0.01,
        "judge_llm_calls": 3,
        "loop_iterations": None,
        "stop_reason": None,
    }
    base.update(overrides)
    return base


def _write_readme(tmp_path: Path, block_body: str = "") -> Path:
    """README with a live marker block for patching."""
    body = (
        "# arxiv-research-agent\n\n"
        "Prefix content stays untouched.\n\n"
        "## Latest eval results\n\n"
        f"{START_MARKER}\n{block_body}\n{END_MARKER}\n\n"
        "Suffix content stays untouched.\n"
    )
    p = tmp_path / "README.md"
    p.write_text(body, encoding="utf-8")
    return p


class TestRenderBlock:
    def test_all_success_rows_produce_aggregate_row(self) -> None:
        block = render_block(
            [
                _record(citation_accuracy=1.0, faithfulness=1.0),
                _record(citation_accuracy=0.5, faithfulness=0.5),
            ]
        )
        # Header + separator + aggregate row + preamble line.
        assert "| Queries |" in block
        assert "|---|---|" in block
        # Both metrics average to 0.75 → format 0.750.
        assert "| 0.750 " in block

    def test_errored_rows_dont_pull_the_mean(self) -> None:
        block = render_block(
            [
                _record(citation_accuracy=1.0),
                _record(citation_accuracy=None, error="RuntimeError: boom"),
            ]
        )
        # Only the successful row (1.0) contributes.
        assert "| 1.000 " in block
        # Success/total counter: 1 / 2.
        assert "| 1 / 2 " in block

    def test_none_scores_are_shown_as_dashes(self) -> None:
        block = render_block(
            [
                _record(citation_accuracy=None),
            ]
        )
        # Each metric column is `-` when no records contribute.
        # (One row, but citation_accuracy is None, so mean is None.)
        assert "| - |" in block

    def test_all_errored_run_still_emits_table(self) -> None:
        block = render_block(
            [_record(error="fail")],
        )
        # Should still be a well-formed table.
        assert "| Queries |" in block
        assert "0 / 0" in block or "1 / 0" in block

    def test_run_id_appears_in_the_preamble(self) -> None:
        block = render_block([_record()], run_id="20260712-run-1")
        assert "20260712-run-1" in block

    def test_empty_records_list_produces_zero_row(self) -> None:
        block = render_block([])
        assert "| 0 / 0 " in block


class TestUnscoredDenominator:
    """A mean over the runs a judge managed to score states how many.

    ADR 0050. Judge isolation leaves a failed metric `null` on the
    record instead of aborting the campaign, and `_mean_or_none` skips
    nulls — so `Mean faithfulness` can be an average of two runs inside
    a row headed `20 / 20`. Every test here is a mutation check on
    `_unscored_note`.
    """

    def test_note_names_the_metric_and_its_denominator(self) -> None:
        rows = [_record(faithfulness=None) for _ in range(18)]
        rows += [_record(faithfulness=0.9) for _ in range(2)]
        block = render_block(rows)
        assert "| 20 / 20 " in block
        assert "faithfulness over 2 of 20" in block

    def test_clean_run_gets_no_unscored_note(self) -> None:
        block = render_block([_record(), _record()])
        assert "went unscored" not in block

    def test_a_metric_nobody_scored_is_a_dash_not_a_denominator_note(
        self,
    ) -> None:
        # Nothing is claimed for a metric printed as `-`, so there is no
        # denominator to qualify.
        block = render_block([_record(faithfulness=None)])
        assert "faithfulness over" not in block

    def test_citation_accuracy_counts_against_its_own_eligible_rows(
        self,
    ) -> None:
        # One uncited row is excluded from the citation mean entirely;
        # of the two that remain, one went unscored. The note must say
        # "1 of 2", not "1 of 3".
        block = render_block(
            [
                _record(citation_accuracy=0.9, total_citations=4),
                _record(citation_accuracy=None, total_citations=4),
                _record(citation_accuracy=1.0, total_citations=0),
            ]
        )
        assert "citation accuracy over 1 of 2" in block

    def test_workflow_cost_caveat_is_always_stated(self) -> None:
        # It used to ride along inside the uncited-rows note, so a night
        # where every report cited something published cost and latency
        # with no word on whose spend they are.
        block = render_block([_record()])
        assert "excluding eval-judge calls" in block


class TestCitationAccuracyDenominator:
    """Rows whose report cited nothing are excluded from that one mean.

    ADR 0050. `measure_citation_accuracy` short-circuits a report with
    zero `[Author, Year]` tags to 1.0 — "the metric doesn't apply" —
    and averaging those into the published figure inflates it exactly
    when the agent cited least. Every test here is a mutation check:
    each one passes only with `_rows_with_citations` in the path.
    """

    def test_zero_citation_row_excluded_from_the_mean(self) -> None:
        block = render_block(
            [
                _record(citation_accuracy=0.5, total_citations=4),
                _record(citation_accuracy=1.0, total_citations=0),
            ]
        )
        # First metric column is citation accuracy. With the free 1.0
        # folded in it would read 0.750.
        assert "| 2 / 2 | 0.500 " in block

    def test_other_metrics_keep_the_full_denominator(self) -> None:
        block = render_block(
            [
                _record(
                    citation_accuracy=0.5, faithfulness=1.0, total_citations=4
                ),
                _record(
                    citation_accuracy=1.0, faithfulness=0.0, total_citations=0
                ),
            ]
        )
        # faithfulness still averages over both rows: (1.0 + 0.0) / 2.
        assert "| 0.500 | 0.500 " in block

    def test_exclusion_is_stated_under_the_table(self) -> None:
        block = render_block(
            [
                _record(citation_accuracy=0.5, total_citations=4),
                _record(citation_accuracy=1.0, total_citations=0),
            ]
        )
        assert "Citation accuracy is averaged over the 1 of 2 scored runs" in block
        assert "1 produced none" in block

    def test_no_note_when_every_row_cited_something(self) -> None:
        block = render_block([_record(total_citations=3)])
        assert "Citation accuracy is averaged over" not in block

    def test_all_rows_uncited_shows_a_dash_not_a_perfect_score(self) -> None:
        block = render_block(
            [
                _record(citation_accuracy=1.0, total_citations=0),
                _record(citation_accuracy=1.0, total_citations=0),
            ]
        )
        # Publishing 1.000 here would be the exact lie ADR 0050 closes.
        assert "| 1.000 " not in block
        assert "| 2 / 2 | - " in block

    def test_pre_adr_rows_without_the_count_are_kept(self) -> None:
        # Summaries written before ADR 0050 carry no `total_citations`
        # field; dropping them would empty the mean retroactively.
        rows = [_record(citation_accuracy=1.0)]
        for row in rows:
            row.pop("total_citations", None)
        block = render_block(rows)
        assert "| 1.000 " in block
        assert "Citation accuracy is averaged over" not in block


class TestPatchReadme:
    def test_replaces_content_between_markers(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, "old block content")
        changed = patch_readme(readme, "brand new block")
        assert changed is True
        text = readme.read_text()
        assert "old block content" not in text
        assert "brand new block" in text
        # Bookends outside the markers are preserved.
        assert "Prefix content stays untouched." in text
        assert "Suffix content stays untouched." in text

    def test_no_change_when_content_is_identical(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path, "unchanged block")
        # First patch installs the block wrapped in newlines.
        patch_readme(readme, "unchanged block")
        # Second patch with the same content shouldn't rewrite.
        changed = patch_readme(readme, "unchanged block")
        assert changed is False

    def test_missing_start_marker_raises(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text(f"no start marker here\n{END_MARKER}\n")
        with pytest.raises(ValueError, match="Missing/malformed markers"):
            patch_readme(readme, "block")

    def test_missing_end_marker_raises(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text(f"{START_MARKER}\nno end marker here\n")
        with pytest.raises(ValueError, match="Missing/malformed markers"):
            patch_readme(readme, "block")

    def test_swapped_markers_raise(self, tmp_path: Path) -> None:
        # End appears before start — invalid.
        readme = tmp_path / "README.md"
        readme.write_text(f"{END_MARKER}\nswapped\n{START_MARKER}\n")
        with pytest.raises(ValueError, match="Missing/malformed markers"):
            patch_readme(readme, "block")


class TestMainEntryPoint:
    def _write_summary(
        self, tmp_path: Path, records: list[dict[str, object]]
    ) -> Path:
        p = tmp_path / "summary.jsonl"
        p.write_text(
            "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
        )
        return p

    def test_happy_path_returns_zero(self, tmp_path: Path) -> None:
        summary = self._write_summary(
            tmp_path, [_record(), _record(citation_accuracy=0.5)]
        )
        readme = _write_readme(tmp_path)
        rc = main(
            [
                "--summary",
                str(summary),
                "--readme",
                str(readme),
                "--run-id",
                "test-run",
            ]
        )
        assert rc == 0
        text = readme.read_text()
        assert "test-run" in text
        assert "| Queries |" in text

    def test_missing_summary_file_returns_2(self, tmp_path: Path) -> None:
        readme = _write_readme(tmp_path)
        rc = main(
            [
                "--summary",
                str(tmp_path / "nope.jsonl"),
                "--readme",
                str(readme),
            ]
        )
        assert rc == 2

    def test_missing_readme_returns_2(self, tmp_path: Path) -> None:
        summary = self._write_summary(tmp_path, [_record()])
        rc = main(
            [
                "--summary",
                str(summary),
                "--readme",
                str(tmp_path / "nope-readme.md"),
            ]
        )
        assert rc == 2

    def test_readme_without_markers_returns_1(self, tmp_path: Path) -> None:
        summary = self._write_summary(tmp_path, [_record()])
        readme = tmp_path / "README.md"
        readme.write_text("# no markers here\n")
        rc = main(
            ["--summary", str(summary), "--readme", str(readme)]
        )
        assert rc == 1

    def test_malformed_summary_returns_2(self, tmp_path: Path) -> None:
        summary = tmp_path / "summary.jsonl"
        summary.write_text("not json\n{}\n")
        readme = _write_readme(tmp_path)
        rc = main(
            ["--summary", str(summary), "--readme", str(readme)]
        )
        assert rc == 2

    def test_ignores_blank_lines_in_summary(self, tmp_path: Path) -> None:
        summary = tmp_path / "summary.jsonl"
        summary.write_text(
            f"\n{json.dumps(_record())}\n\n{json.dumps(_record())}\n\n"
        )
        readme = _write_readme(tmp_path)
        rc = main(["--summary", str(summary), "--readme", str(readme)])
        assert rc == 0
        assert "| 2 / 2 " in readme.read_text()
