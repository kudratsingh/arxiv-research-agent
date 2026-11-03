"""Authored interests have literal terms; external taxonomy anchors only browse."""

from __future__ import annotations

from collections import Counter

import pytest

from src.workspace.interests import CATALOGUE, coverage, topic_terms
from src.workspace.ranking import TOPIC_TERMS, rank_items

pytestmark = pytest.mark.unit


def test_all_catalogue_node_types_keep_their_declared_matching_semantics():
    counts = Counter(node["kind"] for node in CATALOGUE.values())
    assert counts == {
        "authored_study_area": 243,
        "authored_ml_topic": 96,
        "authored_ml_group": 15,
        "external_field": 26,
        "external_domain": 4,
    }
    for key, node in CATALOGUE.items():
        terms = topic_terms(key, TOPIC_TERMS)
        if node["kind"].startswith("authored_"):
            assert terms, key
        else:
            assert terms == (), key
            assert topic_terms(key, {key: ("accidental broad alias",)}) == ()
    assert "machine learning" in topic_terms("study:17/machine-learning", TOPIC_TERMS)
    assert "control" in topic_terms("study:22/control-systems", TOPIC_TERMS)


def test_study_literal_matches_are_inspectable_without_expanding_external_fields():
    profile = {"topics": ["study:17/machine-learning", "oa-field:17"], "streams": ["core"]}
    rows = coverage(profile, [], TOPIC_TERMS)
    assert rows[0]["matching_mode"] == "literal_terms"
    assert "machine learning" in rows[0]["terms"] and rows[0]["status"] == "limited"
    assert rows[0]["descendant_ids"] == []
    assert rows[1]["matching_mode"] == "browse_only" and rows[1]["source_ids"] == []
    work = {
        "work_id": "literal",
        "title": "Machine learning with limited compute",
        "abstract": "",
        "source_id": "arxiv-cs-lg",
        "fetched_at": "2026-11-03T00:00:00Z",
    }
    ranked = rank_items([work], profile)
    assert "machine learning" in ranked[0]["relevance"]["matched_terms"]
    assert not rank_items([work], {**profile, "topics": ["oa-field:17"]})[0]["relevance"][
        "matched_terms"
    ]
