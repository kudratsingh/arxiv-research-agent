"""Parent selections and exploration caps measured against actual finite items."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.workspace.interests import CATALOGUE, GROUP_ALIASES, coverage, descendants, topic_terms
from src.workspace.ranking import TOPIC_TERMS, rank_items, select_edition

pytestmark = pytest.mark.unit


def test_packaged_catalogue_matches_selectable_frontend_catalogue():
    root = Path(__file__).resolve().parents[1]
    assert json.loads((root / "src/workspace/topics.json").read_text()) == json.loads((root / "web/lib/daily/topics.json").read_text())


@pytest.mark.parametrize("parent", list(GROUP_ALIASES))
def test_each_previously_disconnected_authored_parent_matches_its_descendant(parent):
    children = descendants(parent)
    assert children and all(child in CATALOGUE for child in children)
    leaf = children[0]
    terms = topic_terms(leaf, TOPIC_TERMS)
    assert terms
    ranked = rank_items([{"work_id": "real-shape", "title": terms[0]}], {"topics": [parent]}, now=datetime(2026, 11, 3, tzinfo=UTC))
    assert terms[0] in ranked[0]["relevance"]["matched_terms"]
    assert parent in ranked[0]["relevance"]["matched_topics"]


def test_broad_navigation_coverage_gaps_and_disabled_streams_are_explicit():
    profile = {"topics": ["oa-field:17", "ml:neural-architectures", "ml:generative-models"], "streams": ["core"]}
    missing = coverage(profile, [], TOPIC_TERMS)
    assert [row["status"] for row in missing] == ["unconnected", "limited", "unconnected"]
    assert missing[0]["terms"] == [] and missing[0]["source_ids"] == []
    assert missing[1]["matching_mode"] == "descendant_terms" and missing[1]["descendant_ids"]
    now = datetime(2026, 11, 3, tzinfo=UTC)
    complete = [{"source_id": key, "status": "success", "last_success_at": now.isoformat()} for key in missing[1]["source_ids"]]
    assert coverage(profile, complete, TOPIC_TERMS, now=now)[1]["status"] == "active"
    assert coverage(profile, complete, TOPIC_TERMS, now=datetime(2026, 12, 3, tzinfo=UTC))[1]["status"] == "limited"
    complete[0]["status"] = "partial"
    assert coverage(profile, complete, TOPIC_TERMS)[1]["status"] == "limited"
    assert all(row["limitations"] for row in missing)
    assert coverage({"custom_topics": ["specific mechanism"]}, complete, TOPIC_TERMS)[0]["terms"] == ["specific mechanism"]


@pytest.mark.parametrize("minutes,fraction,expected", [(15, 0, 0), (15, .15, 0), (15, .3, 0), (45, 0, 0), (45, .15, 1), (45, .3, 2)])
def test_allocation_rounds_down_against_the_final_denominator(minutes, fraction, expected):
    candidates = [{"work_id": f"d{i}", "relevance": {"matched_terms": ["term"]}} for i in range(12)]
    candidates += [{"work_id": f"e{i}", "relevance": {"matched_terms": []}} for i in range(12)]
    items, allocation = select_edition(candidates, minutes, exploration=fraction)
    assert len(items) == minutes // 5
    assert allocation["actual_exploration_slots"] == expected
    assert allocation["actual_fraction"] <= fraction
    assert allocation["unused_slots"] == 0


@pytest.mark.parametrize("direct,fraction,total,exploratory", [(2, .3, 2, 0), (3, .3, 4, 1), (5, .15, 5, 0), (6, .15, 7, 1), (0, .3, 0, 0)])
def test_sparse_matches_shorten_the_edition_instead_of_overstating_exploration(direct, fraction, total, exploratory):
    candidates = [{"work_id": f"d{i}", "relevance": {"matched_terms": ["term"]}} for i in range(direct)]
    candidates += [{"work_id": f"e{i}", "relevance": {"matched_terms": []}} for i in range(10)]
    selected, allocation = select_edition(candidates, 45, exploration=fraction)
    assert len(selected) == total and allocation["actual_exploration_slots"] == exploratory
    assert allocation["unused_slots"] == 9 - total
    assert allocation["actual_fraction"] is None if total == 0 else allocation["actual_fraction"] <= fraction
