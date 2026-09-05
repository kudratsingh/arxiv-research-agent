"""The protocol document's numbers are re-derived, not trusted.

`tests/test_documented_claims.py` established the technique this file
copies: **parse the number out of the sentence being checked and compare
it against a value re-derived from the artifact the sentence describes**,
so editing the sentence is the whole of the edit and a sentence that
stops being true fails a test that quotes it back.

Every claim below is one the document would be actively misleading if it
got wrong: an item count somebody sizes a campaign from, a cost somebody
approves, or the statement that no judge has been run.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from src.calibration.estimate import current_price_table, default_example
from src.calibration.fixtures import Family, load_cases, load_labelled_set, load_pairwise
from src.calibration.metrics import DEFAULT_THRESHOLDS, INTEGRITY_VIOLATION_CLASSES
from src.calibration.sampling import (
    FAILURE_CLASSES,
    TASK_SLICES,
    items_to_bound_below,
    noise_floor,
    standard_plan,
)
from src.calibration.suite import CALIBRATION_REGISTRY_ROOT, read_tree

pytestmark = pytest.mark.unit

_ROOT: Final = Path(__file__).resolve().parents[1]
_DOC: Final = _ROOT / "docs" / "agent-engineering" / "14-judge-calibration-protocol.md"
_INDEX: Final = _ROOT / "docs" / "agent-engineering" / "README.md"


@pytest.fixture(scope="module")
def doc() -> str:
    """The protocol document with its line wrapping flattened.

    A claim these tests check is a *sentence*, and a sentence in a
    hard-wrapped Markdown file is split across lines at a column that has
    nothing to do with its meaning. Flattening first means a reflow never
    fails a test and a changed number always does.
    """
    text = _DOC.read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", text.replace("\n> ", "\n"))


def _digits(text: str, pattern: str) -> int:
    match = re.search(pattern, text)
    assert match is not None, f"the document no longer contains {pattern!r}"
    return int(match.group(1).replace(",", ""))


class TestTheSamplingNumbers:
    def test_the_noise_floor_paragraph_matches_the_estimators(self, doc: str) -> None:
        floor = noise_floor()

        assert (
            f"reaches significance at all is **{floor.smallest_significant_delta:.0%}**"
            in doc
        )
        assert f"80% power is **{floor.smallest_detectable_delta:.0%}**" in doc
        assert f"needs **{floor.pairs_for_five_points} pairs**" in doc
        assert f"**{floor.powered_pairs_for_five_points}** to be detected" in doc
        assert f"**{floor.unpaired_for_five_points} items per arm**" in doc

    def test_the_per_slice_and_whole_set_counts_match_the_plan(self, doc: str) -> None:
        plan = standard_plan(pilot_items=30)

        assert _digits(doc, r"\| Per-slice diagnostic interval \| \*\*(\d+)\*\* per slice") == (
            plan.items_per_slice
        )
        assert _digits(doc, r"\| Whole-set interval \| \*\*(\d+)\*\*") == plan.whole_set_items
        assert _digits(
            doc, r"\| Pessimistic total if no case belonged to two slices \| (\d+) \|"
        ) == plan.upper_bound_items

    @pytest.mark.parametrize(
        ("observed", "label"),
        [(0.05, "5%"), (0.02, "2%"), (0.0, "0%")],
    )
    def test_the_bound_counts_match(self, doc: str, observed: float, label: str) -> None:
        expected = items_to_bound_below(observed_rate=observed, ceiling=0.10)

        assert (
            _digits(
                doc,
                rf"\| Whole-set bound at an observed {re.escape(label)} \| \*\*(\d+)\*\*",
            )
            == expected
        )

    def test_the_recommended_first_set_is_the_whole_set_target(self, doc: str) -> None:
        plan = standard_plan(pilot_items=30)

        assert f"recommended first set is {plan.whole_set_items} items" in doc

    def test_the_slice_and_taxonomy_counts_match_the_module(self, doc: str) -> None:
        assert "Ten task slices" in doc
        assert len(TASK_SLICES) == 10
        assert "thirteen classes" in doc
        assert len(FAILURE_CLASSES) == 13
        for spec in TASK_SLICES:
            assert f"`{spec.slice_id}`" in doc


class TestTheFixtureAndSuiteCounts:
    def test_the_corpus_sizes_match(self, doc: str) -> None:
        cases = load_cases()
        pairs = load_pairwise()

        assert f"{len(cases)} single-item cases" in doc
        assert f"{len(pairs)} pairwise pairs in both orders" in doc
        assert f"{len(load_labelled_set().items)}-item worked labelled set" in doc

    def test_every_family_appears_in_the_family_table(self, doc: str) -> None:
        for family in Family:
            assert f"`{family.value}`" in doc

    def test_the_predicted_cell_mix_matches_the_corpus(self, doc: str) -> None:
        from collections import Counter

        counts = Counter(case.expected_outcome.value for case in load_cases())

        assert (
            f"{counts['false_pass']} false passes, {counts['true_pass']} true passes, "
            f"{counts['true_fail']} true fails, {counts['false_fail']} false fails" in doc
        )

    def test_the_registered_case_count_matches_the_tree(self, doc: str) -> None:
        objects, _ = read_tree()
        cases = [
            envelope
            for envelope in objects
            if envelope.schema_kind.value == "task_case"
        ]

        assert f"{len(cases)} task cases" in doc
        assert f"{len(cases)} synthetic items" in doc

    def test_the_pilot_is_named_as_a_fraction_of_the_recommended_set(
        self, doc: str
    ) -> None:
        objects, _ = read_tree()
        cases = sum(1 for e in objects if e.schema_kind.value == "task_case")
        plan = standard_plan(pilot_items=cases)

        # 30 of 141 is between a fourth and a fifth; the document says
        # "one fifth", which must stay true as the corpus grows.
        assert "one fifth of the recommended set" in doc
        assert plan.whole_set_items / plan.pilot_items == pytest.approx(4.7, abs=0.5)


class TestTheCostExample:
    def test_the_priced_totals_match_the_template(self, doc: str) -> None:
        prices, verified = current_price_table()
        estimate = default_example(items=141, pairwise_items=40, priced_on="2026-09-05")

        assert f"`PRICES_LAST_VERIFIED` is **{verified}**" in doc
        assert f"**${estimate.model_cost_usd(prices):.2f}**" in doc
        assert f"**{estimate.expert_hours:.1f} h**" in doc

    def test_each_priced_line_matches(self, doc: str) -> None:
        prices, _ = current_price_table()
        estimate = default_example(items=141, pairwise_items=40, priced_on="2026-09-05")

        for line in estimate.judge_lines:
            assert f"| {line.label} | {line.calls} |" in doc
            assert f"${line.cost_usd(prices):.3f} |" in doc

    def test_each_expert_line_matches(self, doc: str) -> None:
        estimate = default_example(items=141, pairwise_items=40, priced_on="2026-09-05")

        for line in estimate.expert_lines:
            assert f"| {line.label} | {line.items} |" in doc
            assert f"| {line.hours:.1f} |" in doc

    def test_the_caps_match(self, doc: str) -> None:
        estimate = default_example(items=141, pairwise_items=40, priced_on="2026-09-05")

        assert (
            f"**${Decimal(estimate.per_episode_cap_usd):.2f} per episode, "
            f"${Decimal(estimate.campaign_cap_usd):.2f} per campaign**" in doc
        )

    def test_the_paid_call_total_in_section_12_matches(self, doc: str) -> None:
        prices, _ = current_price_table()
        estimate = default_example(items=141, pairwise_items=40, priced_on="2026-09-05")
        calls = sum(line.calls for line in estimate.judge_lines)

        assert f"| **total** | **{calls}** | **${estimate.model_cost_usd(prices):.2f}** |" in doc


class TestTheThresholdsAndVocabulary:
    def test_the_proposed_thresholds_match_the_module(self, doc: str) -> None:
        assert f"| {DEFAULT_THRESHOLDS.false_pass_ceiling:.2f} |" in doc
        assert f"| {DEFAULT_THRESHOLDS.phi_floor:.2f} |" in doc
        assert f"±{DEFAULT_THRESHOLDS.position_bias_tolerance:.2f} |" in doc
        assert f"| {DEFAULT_THRESHOLDS.minimum_resolved_items} |" in doc

    def test_every_integrity_class_is_named_in_the_gate_section(self, doc: str) -> None:
        for name in INTEGRITY_VIOLATION_CLASSES:
            assert f"`{name}`" in doc

    def test_the_hidden_field_set_is_listed(self, doc: str) -> None:
        from src.calibration.blinding import HIDDEN_FROM_JUDGE

        for field in HIDDEN_FROM_JUDGE:
            assert f"`{field}`" in doc


class TestTheDocumentSaysNothingHasStarted:
    def test_the_status_line_names_no_spend(self, doc: str) -> None:
        assert "NO JUDGING, NO LABELING CAMPAIGN, NO SPEND" in doc

    def test_it_states_that_no_judge_has_been_called(self, doc: str) -> None:
        assert "No judge, provider or grader call has been made" in doc

    def test_it_states_that_no_labeling_campaign_has_started(self, doc: str) -> None:
        assert "No human-labeling campaign has started" in doc

    def test_it_names_both_blocking_decisions(self, doc: str) -> None:
        assert "D9" in doc
        assert "D8.10" in doc

    def test_the_separate_registry_root_is_explained(self, doc: str) -> None:
        assert "Why a separate registry root" in doc
        assert CALIBRATION_REGISTRY_ROOT.name in doc


class TestTheIndex:
    def test_the_protocol_is_listed_in_the_documents_index(self) -> None:
        index = _INDEX.read_text(encoding="utf-8")

        assert "[`14-judge-calibration-protocol.md`](14-judge-calibration-protocol.md)" in index

    def test_the_numbered_list_has_no_gap(self) -> None:
        index = _INDEX.read_text(encoding="utf-8")
        numbered = [
            int(match.group(1))
            for match in re.finditer(r"^(\d+)\. \[`\d\d-", index, flags=re.MULTILINE)
        ]

        assert numbered == list(range(1, len(numbered) + 1))

    def test_the_status_table_records_the_work_order_as_landed(self) -> None:
        index = _INDEX.read_text(encoding="utf-8")
        row = next(
            line for line in index.splitlines() if line.startswith("| P0-WO10 |")
        )

        assert "Pending" not in row
        assert "14-judge-calibration-protocol.md" in row

    def test_the_test_count_it_claims_is_at_or_below_the_real_one(self) -> None:
        """A floor, in `test_documented_claims.py`'s sense.

        The document names a count so a reader can tell whether the
        package is tested at all; the assertion is a floor rather than an
        equality because adding a test should not be a documentation
        edit, and deleting the suite should be.
        """
        import subprocess
        import sys

        doc = _DOC.read_text(encoding="utf-8")
        claimed = _digits(re.sub(r"\s+", " ", doc), r"— (\d+) of them")
        collected = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--collect-only",
                str(_ROOT / "tests"),
                "-k",
                "calibration",
            ],
            capture_output=True,
            text=True,
            cwd=_ROOT,
        )
        actual = int(
            re.search(r"(\d+)(?:/\d+)? tests collected", collected.stdout).group(1)  # type: ignore[union-attr]
        )

        assert claimed <= actual
