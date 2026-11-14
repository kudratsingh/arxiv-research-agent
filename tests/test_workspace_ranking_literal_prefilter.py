"""The literal fast path preserves the published lexical ranker exactly."""
from __future__ import annotations

import gzip
import json
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.workspace import ranking
from src.workspace.mode_ranking import rank_mode_items

pytestmark = pytest.mark.unit


def legacy_contains(text: str, term: str) -> bool:
    """Frozen prefilter-free matching rule; text is already lowercased by rank_items."""
    return bool(term.strip()) and re.search(
        r"(?<!\w)" + re.escape(term.lower()) + r"s?(?!\w)", text
    ) is not None


@pytest.mark.parametrize(
    ("text", "term", "expected"),
    [
        ("rag", "RAG", True), ("rag systems", "Rag", True),
        ("fragment", "Rag", False), ("a ragged edge", "rag", False),
        ("(agents) and agent", "agent", True), ("agents", "agent", True),
        ("agentss", "agent", False), ("x_agent", "agent", False),
        ("c++ and x.y", "C++", True), ("x.y", "x.y", True),
        ("xay", "x.y", False), ("hello [world]", "[world]", True),
        ("naïve café", "NAÏVE", True), ("λrag", "rag", False),
        ("rag雪", "rag", False), ("🙂rag🙂", "rag", True),
        ("a tool use case", "tool use", True), ("tool  use", "tool use", False),
        ("( tool use", " tool use", True), ("anything", "", False),
        ("   ", " ", False), ("\nrag\t", "rag", True),
    ],
)
def test_legacy_unicode_escaping_boundaries_and_plurals(text, term, expected):
    assert legacy_contains(text, term) is expected
    assert ranking._contains(text, term) is expected


def test_absence_skips_regex_but_present_wrong_boundary_still_checks():
    with patch.object(ranking.re, "search", wraps=re.search) as search:
        assert ranking._contains("alpha beta", "RAG") is False
        assert ranking._contains("alpha beta", "  ") is False
        search.assert_not_called()
        assert ranking._contains("fragment", "Rag") is False
        assert search.call_count == 1
        assert ranking._contains("(rag)", "rag") is True
        assert search.call_count == 2


def test_cross_product_matches_original_rule():
    texts = ["", "rag", "fragment", "agents", "_rag_", "λrag🙂", "c++", "x.y", "a  b", "a\nb", "İ i̇", "ßs"]
    terms = ["", " ", "Rag", "agent", "c++", "x.y", ".", "a  b", "a\nb", "İ", "ss", "ß"]
    for text in texts:
        for term in terms:
            assert ranking._contains(text, term) == legacy_contains(text, term), (text, term)


@pytest.fixture(scope="module")
def frozen_inputs():
    path = (Path(__file__).resolve().parents[1] /
            "planning/15-evaluation-audit-and-recovery/evidence/provider-contract-v14/packet.json.gz")
    with gzip.open(path, "rt", encoding="utf-8") as file:
        packet = json.load(file)
    assert packet["packet_digest"] == "2ad47ade2db7f96d97ff11303b56cdd222b2980fadca37824ba2866f113accf4"
    assert len(packet["corpus"]) == 40
    return packet["corpus"], packet["profile"], datetime.fromisoformat(packet["clock"])


@pytest.mark.parametrize("mode", ["relevance", "chronological", "keyword"])
@pytest.mark.parametrize("include_hidden", [False, True])
def test_frozen_public_corpus_rankings_and_filters_match_legacy(monkeypatch, frozen_inputs, mode, include_hidden):
    corpus, base_profile, now = deepcopy(frozen_inputs)
    profile = {**base_profile, "exclusions": ["retrieval", "unmatched [literal]"]}
    states = {
        corpus[0]["work_id"]: {"status": "archived"},
        corpus[1]["work_id"]: {"status": "snoozed", "snoozed_until": "2030-01-01T00:00:00+00:00"},
        corpus[2]["work_id"]: {"status": "read"},
    }
    before = deepcopy((corpus, profile, states))
    actual = ranking.rank_items(corpus, profile, states, now=now, mode=mode, include_hidden=include_hidden)
    monkeypatch.setattr(ranking, "_contains", legacy_contains)
    expected = ranking.rank_items(corpus, profile, states, now=now, mode=mode, include_hidden=include_hidden)
    assert actual == expected
    assert (corpus, profile, states) == before


@pytest.mark.parametrize("product_mode", ["learn", "research"])
@pytest.mark.parametrize("include_hidden", [False, True])
def test_frozen_learn_and_research_ordering_matches_legacy(monkeypatch, frozen_inputs, product_mode, include_hidden):
    corpus, profile, now = deepcopy(frozen_inputs)
    corpus[0]["reading"] = {"status": "archived"}
    project = {"question": "retrieval memory evaluation", "scope": "robust inference"}
    actual = rank_mode_items(corpus, profile, product_mode=product_mode, project=project, now=now, include_hidden=include_hidden)
    monkeypatch.setattr(ranking, "_contains", legacy_contains)
    expected = rank_mode_items(corpus, profile, product_mode=product_mode, project=project, now=now, include_hidden=include_hidden)
    assert actual == expected
