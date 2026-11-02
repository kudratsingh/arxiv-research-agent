"""Transparent ranking mechanics; these assertions do not claim owner usefulness."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from src.workspace.ranking import choose_edition, comparison_sample, rank_items

pytestmark = pytest.mark.unit
NOW = datetime(2026, 11, 2, 16, tzinfo=UTC)
PROFILE = {
    "topics": ["ml:agents-and-tool-use", "ml:retrieval-and-memory", "study:22/control-systems"],
    "streams": ["core", "rocket-twin"],
    "custom_topics": ["verification"],
    "research_question": "How can I evaluate retrieval changes with controlled compute?",
    "exclusions": ["advertisement"],
}


def item(
    work_id: str, title: str, date: str | None = "2026-11-02T10:00:00Z", **extra: Any
) -> dict[str, Any]:
    return {"work_id": work_id, "title": title, "abstract": "", "published_at": date, **extra}


def test_match_explanations_exclusions_and_question_terms() -> None:
    ranked = rank_items(
        [
            item("a", "A retrieval agent"),
            item("b", "Independent discovery"),
            item("c", "Retrieval advertisement"),
            item("d", "Verification methods"),
        ],
        PROFILE,
        now=NOW,
    )
    assert [record["work_id"] for record in ranked] == ["a", "d", "b"]
    assert ranked[0]["relevance"]["matched_terms"] == ["agent", "retrieval"]
    assert ranked[0]["relevance"]["question_terms"] == ["retrieval"]
    assert ranked[0]["reasons"][0] == "Matches agent, retrieval."
    assert ranked[1]["relevance"]["matched_topics"] == ["custom interest"]
    assert ranked[0]["stream"] == "core" and ranked[-1]["stream"] == "exploration"


def test_word_matching_and_broad_fields_do_not_invent_topic_coverage() -> None:
    profile = {"topics": ["oa-field:22", "ml:retrieval-and-memory"], "exclusions": ["ad"]}
    ranked = rank_items(
        [item("a", "Fragments are not retrieval"), item("b", "Numerical control")], profile, now=NOW
    )
    assert ranked[0]["relevance"]["matched_terms"] == ["retrieval"]
    assert ranked[1]["relevance"]["matched_terms"] == []
    assert "Exploration" in ranked[1]["reasons"][0]


def test_stream_disabling_custom_topics_and_taxonomy_slug() -> None:
    profile = {
        **PROFILE,
        "streams": ["core"],
        "topics": PROFILE["topics"] + ["ml:custom/deep-learning"],
    }
    ranked = rank_items(
        [item("a", "A controller"), item("b", "Deep learning verification")], profile, now=NOW
    )
    assert ranked[0]["work_id"] == "b"
    assert ranked[0]["relevance"]["matched_terms"] == ["deep learning", "verification"]
    assert ranked[1]["relevance"]["matched_terms"] == []
    # An intentionally empty source stream/topic set must not restore defaults.
    assert not rank_items([item("a", "An agent")], {"topics": [], "streams": []}, now=NOW)[0][
        "relevance"
    ]["matched_terms"]


def test_hidden_state_undo_and_snooze_expiry() -> None:
    candidates = [
        item("a", "Agent one"),
        item("b", "Agent two"),
        item("c", "Agent three"),
        item("d", "Agent four"),
        item("e", "Agent five"),
    ]
    states = {
        "a": {"status": "dismissed"},
        "b": {"status": "archived"},
        "c": {"status": "snoozed", "snoozed_until": "2026-11-03T10:00:00Z"},
        "d": {"status": "snoozed", "snoozed_until": "2026-11-01T10:00:00Z"},
        "e": {"status": "snoozed", "snoozed_until": "bad"},
    }
    assert [v["work_id"] for v in rank_items(candidates, PROFILE, states, now=NOW)] == ["d"]
    assert len(rank_items(candidates, PROFILE, states, now=NOW, include_hidden=True)) == 5
    states["a"] = {"status": "unread"}  # undo changes only this work's visibility
    assert {v["work_id"] for v in rank_items(candidates, PROFILE, states, now=NOW)} == {"a", "d"}


def test_embedded_read_state_is_respected_and_ranked_lower() -> None:
    ranked = rank_items(
        [item("a", "Retrieval agent", reading={"status": "read"}), item("b", "Retrieval agent")],
        PROFILE,
        now=NOW,
    )
    assert [v["work_id"] for v in ranked] == ["b", "a"]
    assert any("Already marked read" in r for r in ranked[-1]["reasons"])


def test_unknown_dates_stable_ties_duplicates_and_input_unchanged() -> None:
    candidates = [
        item("z", "Agent", None),
        item("a", "Agent", "not a date"),
        item("b", "Agent", "2026-11-02T10:00:00"),
        item("z", "duplicate", None),
    ]
    ranked = rank_items(candidates, PROFILE, now=NOW)
    assert [v["work_id"] for v in ranked] == ["a", "b", "z"]
    assert all("recency bonus" in v["reasons"][-1] for v in ranked)
    assert "reasons" not in candidates[0]
    assert rank_items(candidates, PROFILE, now=NOW) == ranked


def test_chronological_keyword_and_relevance_use_same_candidates() -> None:
    candidates = [
        item("a", "A retrieval planning agent", "2026-10-27T10:00:00Z"),
        item("b", "A new related item", "2026-11-02T11:00:00Z"),
        item("c", "Advertisement for agents", "2026-11-02T12:00:00Z"),
    ]
    chronological = rank_items(candidates, PROFILE, now=NOW, mode="chronological")
    keyword = rank_items(candidates, PROFILE, now=NOW, mode="keyword")
    assert [v["work_id"] for v in chronological] == ["b", "a"]
    assert [v["work_id"] for v in keyword] == ["a", "b"]
    sample = comparison_sample(candidates, PROFILE, now=NOW)
    assert sample["rankings"]["relevance"] == ["a", "b"]
    assert all(label["useful"] is None for label in sample["labels"])
    assert sample["status"] == "awaiting_owner_labels"


def test_finite_edition_time_exploration_and_empty_matching() -> None:
    candidates = [item(str(i), "Agent") for i in range(12)] + [item("x", "Adjacent field")]
    ranked = rank_items(candidates, PROFILE, now=NOW)
    for minutes, count in [(5, 1), (15, 3), (45, 9)]:
        edition = choose_edition(ranked, minutes)
        assert len(edition) == count
        assert sum(v["minutes"] for v in edition) <= minutes
    assert choose_edition(ranked, 15)[-1]["work_id"] == "x"
    assert choose_edition(ranked, 15, exploration=0)[-1]["work_id"] != "x"
    adjacent = rank_items([item("x", "Adjacent field")], PROFILE, now=NOW)
    assert choose_edition(adjacent, 5) == []
    assert len(choose_edition(adjacent, 15)) == 1
    assert choose_edition([], 45) == []


@pytest.mark.parametrize("minutes,exploration", [(0, 0.15), (20, 0.15), (15, -0.1), (15, 0.5)])
def test_invalid_edition_limits(minutes: int, exploration: float) -> None:
    with pytest.raises(ValueError, match="invalid_edition_bounds"):
        choose_edition([], minutes, exploration=exploration)


def test_bad_ranking_mode_and_clock_refused() -> None:
    with pytest.raises(ValueError, match="unknown_ranking_mode"):
        rank_items([], {}, mode="semantic")
    with pytest.raises(ValueError, match="timezone_required"):
        rank_items([], {}, now=datetime(2026, 11, 2))
