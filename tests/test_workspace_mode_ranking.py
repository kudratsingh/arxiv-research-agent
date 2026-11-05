"""Mode-policy mechanics, not scientific quality or owner-usefulness labels."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.workspace.mode_ranking import (
    MODE_POLICY_VERSION,
    known_mode_date,
    rank_mode_items,
    select_mode_edition,
)
from src.workspace.ranking import rank_items
from tools.workspace_mode_ranking_report import (
    _clock,
    _load,
    compare_modes,
    html_report,
    markdown_report,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
PROFILE = {"topics": ["ml:agents-and-tool-use"], "streams": ["core"],
           "custom_topics": [], "exclusions": [], "research_question": "orbital velocity"}


def item(id_: str, title: str, abstract: str = "", **extra: Any) -> dict[str, Any]:
    return {"work_id": id_, "version_id": f"{id_}:v1", "title": title,
            "abstract": abstract, "published_at": None, **extra}


def ids(values: list[dict[str, Any]]) -> list[str]:
    return [value["work_id"] for value in values]


def test_learning_ignores_both_organizing_question_spellings_and_project_without_mutation() -> None:
    candidates = [item("outside", "Orbital velocity"), item("agent", "Agent planning")]
    profile = {**PROFILE, "researchQuestion": "orbital velocity"}
    before = deepcopy((candidates, profile))
    result = rank_mode_items(candidates, profile, project={"question": "orbital velocity"}, now=NOW)
    assert ids(result) == ["agent", "outside"]
    assert all(not row["relevance"]["question_terms"] for row in result)
    assert all(row["mode_relevance"]["question_score"] == 0 for row in result)
    assert (candidates, profile) == before
    assert result == rank_mode_items(candidates, {**profile, "research_question": "", "researchQuestion": ""}, now=NOW)


def test_learning_reuses_authored_terms_read_penalty_and_legacy_score() -> None:
    candidates = [item("read", "Agent planning", published_at="2026-11-05T12:00:00Z", reading={"status": "read"}),
                  item("new", "Agent planning", published_at="2026-11-05T12:00:00Z")]
    result = rank_mode_items(candidates, PROFILE, now=NOW)
    expected = rank_items(candidates, {**PROFILE, "research_question": ""}, now=NOW)
    assert [row["relevance"] for row in result] == [row["relevance"] for row in expected]
    assert ids(result) == ["new", "read"]
    assert result[0]["relevance"]["score"] - result[1]["relevance"]["score"] == 2
    assert result[1]["mode_relevance"]["read_penalty"] == 2
    assert result[1]["mode_relevance"]["read_penalty_applied"] is True
    assert result[0]["mode_relevance"]["policy_version"] == MODE_POLICY_VERSION


@pytest.mark.parametrize("extra", [
    {}, {"announced_at": "2026-11-05T12:00:00Z"},
    {"fetched_at": "2026-11-05T12:00:00Z", "first_seen_at": "2026-11-05T12:00:00Z"},
    {"published_at": "not a date"}, {"published_at": "2026-11-05T12:00:00"},
    {"updated_at": "bad", "published_at": "2026-11-05T12:00:00Z"},
])
def test_missing_or_invalid_dates_never_infer_freshness(extra: dict[str, Any]) -> None:
    candidate = item("arxiv:2611.00001", "Agent", **extra)
    result = rank_mode_items([candidate], PROFILE, now=NOW)[0]
    assert result["mode_relevance"]["known_date"] is None
    assert result["mode_relevance"]["freshness"] == 0
    assert result.get("published_at") == candidate.get("published_at")
    assert result.get("announced_at") == candidate.get("announced_at")
    assert "Publication/update date unknown; no recency bonus." in result["reasons"]


def test_known_update_priority_timezone_and_future_clamp() -> None:
    candidate = item("a", "Agent", updated_at="2026-11-05T05:00:00-07:00", published_at="2020-01-01T00:00:00Z")
    row = rank_mode_items([candidate], PROFILE, now=NOW)[0]
    assert row["mode_relevance"]["known_date"] == NOW.isoformat()
    assert row["mode_relevance"]["date_basis"] == "updated_at"
    assert row["mode_relevance"]["freshness"] == 3
    assert known_mode_date({"published_at": 42}) is None
    assert rank_mode_items([item("b", "Agent", published_at="2030-01-01T00:00:00Z")], PROFILE, now=NOW)[0]["mode_relevance"]["freshness"] == 3


def test_research_matches_outside_interests_and_disabled_streams_and_keeps_contradiction() -> None:
    candidates = [item("direct", "Orbital velocity contradicts the proposed model"),
                  item("scope", "Combustion stability"), item("profile", "Agent planning")]
    result = rank_mode_items(candidates, {**PROFILE, "streams": []}, product_mode="research",
                             project={"question": "Orbital velocity", "scope": "combustion stability"}, now=NOW)
    assert ids(result) == ["direct", "scope"]
    assert all(row["relevance"]["matched_terms"] == [] for row in result)
    assert result[0]["mode_relevance"]["question_score"] == 6
    assert result[1]["mode_relevance"]["scope_score"] == 6
    assert "Research does not require profile overlap" in " ".join(result[0]["reasons"])


def test_title_and_abstract_distinct_token_weights_ignore_categories_for_project_overlap() -> None:
    result = rank_mode_items([item("a", "Memory memory naïve", "memory memory control", categories=["velocity"])], {},
        product_mode="research", project={"question": "memory naïve velocity", "scope": "control memory"}, now=NOW)[0]
    receipt = result["mode_relevance"]
    assert receipt["question_title_matches"] == ["memory", "naïve"]
    assert receipt["question_abstract_matches"] == ["memory"]
    assert receipt["question_score"] == 7 and receipt["scope_score"] == 5
    assert "velocity" not in receipt["question_title_matches"]


def test_research_lexicographic_question_then_scope_then_profile_then_freshness_then_id() -> None:
    project = {"question": "memory control", "scope": "stability"}
    candidates = [
        item("scope-only", "Stability stability"), item("abstract", "Other", "memory"),
        item("question", "Memory control"), item("scope", "Memory stability"),
        item("profile", "Memory agent"), item("fresh", "Memory", published_at="2026-11-05T12:00:00Z"),
        item("z", "Memory"), item("a", "Memory"),
    ]
    result = rank_mode_items(candidates, PROFILE, product_mode="research", project=project, now=NOW)
    assert ids(result) == ["question", "scope", "profile", "fresh", "a", "z", "abstract", "scope-only"]


def test_profile_component_is_bounded_and_research_has_no_read_penalty() -> None:
    terms = ["agent", "planning", "retrieval", "memory", "control", "verification", "compute"]
    candidates = [item("read", "Memory " + " ".join(terms), reading={"status": "read"}),
                  item("unread", "Memory " + " ".join(terms))]
    result = rank_mode_items(candidates, {"custom_topics": terms}, product_mode="research",
                             project={"question": "memory"}, now=NOW)
    assert ids(result) == ["read", "unread"]
    assert all(row["mode_relevance"]["profile_keyword_score"] == 24 for row in result)
    assert all(row["mode_relevance"]["bounded_profile_score"] == 1 for row in result)
    assert all(row["mode_relevance"]["read_penalty_applied"] is False for row in result)
    assert "Already marked read; ranked lower." not in result[0]["reasons"]
    assert "Research ordering does not apply a read penalty" in " ".join(result[0]["reasons"])


@pytest.mark.parametrize("product_mode", ["learn", "research"])
def test_exclusions_and_hidden_state_apply_to_both_modes(product_mode: str) -> None:
    values = [item("archived", "Memory", reading={"status": "archived"}),
              item("dismissed", "Memory", reading={"status": "dismissed"}),
              item("future", "Memory", reading={"status": "snoozed", "snoozed_until": "2027-01-01T00:00:00Z"}),
              item("malformed", "Memory", reading={"status": "snoozed", "snoozed_until": "bad"}),
              item("naive", "Memory", reading={"status": "snoozed", "snoozed_until": "2027-01-01"}),
              item("expired", "Memory", reading={"status": "snoozed", "snoozed_until": "2020-01-01T00:00:00Z"}),
              item("banned", "Memory advertisement"), item("visible", "Memory", reading=None)]
    profile = {"custom_topics": ["memory"], "exclusions": ["advertisement"]}
    result = rank_mode_items(values, profile, product_mode=product_mode, project={"question": "memory"}, now=NOW)
    assert set(ids(result)) == {"expired", "visible"}
    assert len(rank_mode_items(values, profile, product_mode=product_mode, project={"question": "memory"}, now=NOW, include_hidden=True)) == 7


def test_duplicate_work_keeps_first_version_and_stable_id_breaks_ties() -> None:
    result = rank_mode_items([item("z", "Memory"), item("a", "Memory"), item("a", "Memory memory", version_id="a:v2")], {},
                             product_mode="research", project={"question": "memory"}, now=NOW)
    assert ids(result) == ["a", "z"] and result[0]["version_id"] == "a:v1"


def test_learning_stream_round_robin_keeps_ranked_radar_and_within_stream_order() -> None:
    profile = {"topics": ["ml:agents-and-tool-use", "ml:retrieval-and-memory", "study:22/control-systems", "ml:multimodal-and-perception/3d-perception"],
               "streams": ["core", "rocket-twin", "spatial"]}
    ranked = rank_mode_items([item("c1", "Agent memory retrieval"), item("c2", "Agent memory"),
                             item("c3", "Agent planning"), item("r1", "Control"), item("s1", "3d")], profile, now=NOW)
    before = deepcopy(ranked)
    selected, allocation = select_mode_edition(ranked, 15, exploration=0)
    assert ids(ranked) == ["c1", "c2", "c3", "r1", "s1"]
    assert ids(selected) == ["c1", "r1", "s1"]
    assert allocation["direct_stream_order"] == ["core", "rocket-twin", "spatial"]
    assert ranked == before
    longer, _ = select_mode_edition(ranked, 45, exploration=0)
    assert ids(longer) == ["c1", "r1", "s1", "c2", "c3"]


def test_learning_final_count_cap_sparse_matches_and_empty_pool() -> None:
    ranked = rank_mode_items([*[item(f"d{i}", "Agent") for i in range(8)], item("x", "Unrelated")], PROFILE, now=NOW)
    short, small = select_mode_edition(ranked, 15, exploration=0.3)
    assert len(short) == 3 and small["actual_exploration_slots"] == 0
    long, large = select_mode_edition(ranked, 45, exploration=0.15)
    assert len(long) == 9 and large["actual_exploration_slots"] == 1
    sparse, receipt = select_mode_edition(rank_mode_items([item("a", "Agent"), item("x", "Other")], PROFILE, now=NOW), 45, exploration=0.3)
    assert ids(sparse) == ["a"] and receipt["unused_slots"] == 8
    assert select_mode_edition([], 15)[1]["actual_fraction"] is None
    no_matches = rank_mode_items([item("x", "Other")], {"topics": [], "streams": []}, now=NOW)
    assert select_mode_edition(no_matches, 45)[0] == []


def test_research_edition_has_no_profile_quota_or_fabricated_exploration_measurement() -> None:
    ranked = rank_mode_items([item(str(i), "Memory") for i in range(5)], {"streams": []},
                             product_mode="research", project={"question": "memory"}, now=NOW)
    selected, receipt = select_mode_edition(ranked, 15, product_mode="research", exploration=0)
    assert ids(selected) == ["0", "1", "2"]
    assert receipt["actual_items"] == 3 and receipt["unused_slots"] == 0
    assert receipt["actual_fraction"] is None and receipt["actual_exploration_slots"] is None
    assert select_mode_edition([], 15, product_mode="research")[0] == []
    with pytest.raises(ValueError, match="research_mode_ranking_required"):
        select_mode_edition([item("a", "Memory")], 15, product_mode="research")
    altered = deepcopy(ranked)
    altered[0]["mode_relevance"]["eligible"] = False
    assert ids(select_mode_edition(altered, 15, product_mode="research")[0]) == ["1", "2", "3"]


@pytest.mark.parametrize("project", [None, {}, {"question": ""}, {"question": "  "}, {"question": True}])
def test_research_requires_explicit_project_question(project: Any) -> None:
    with pytest.raises(ValueError, match="research_project_question_required"):
        rank_mode_items([], {}, product_mode="research", project=project, now=NOW)


def test_invalid_scope_timezone_modes_and_default_clock() -> None:
    with pytest.raises(ValueError, match="project_scope_must_be_text"):
        rank_mode_items([], {}, product_mode="research", project={"question": "memory", "scope": []})
    with pytest.raises(ValueError, match="timezone_required"):
        rank_mode_items([], {}, now=datetime(2026, 11, 5))
    with pytest.raises(ValueError, match="unknown_product_mode"):
        rank_mode_items([], {}, product_mode="unknown")
    with pytest.raises(ValueError, match="unknown_product_mode"):
        select_mode_edition([], 15, product_mode="unknown")
    assert rank_mode_items([], {}) == []


@pytest.mark.parametrize("minutes,exploration", [(0, .15), (10, .15), (45, -.1), (15, .31)])
@pytest.mark.parametrize("product_mode", ["learn", "research"])
def test_invalid_edition_bounds(minutes: int, exploration: float, product_mode: str) -> None:
    with pytest.raises(ValueError, match="invalid_edition_bounds"):
        select_mode_edition([], minutes, product_mode=product_mode, exploration=exploration)


def test_comparator_shares_research_eligible_pool_and_keeps_learning_and_labels_separate() -> None:
    values = [item("q", "Memory"), item("p", "Memory agent"), item("learn-only", "Agent planning")]
    report = compare_modes(values, {**PROFILE, "research_question": "private organizing text"}, {"question": "memory"}, now=NOW)
    assert report["counts"]["research_eligible_unique"] == 2
    assert all(set(ranking) == {"p", "q"} for ranking in report["rankings"].values())
    assert report["rankings"]["question_only"] == ["p", "q"]
    assert report["rankings"]["profile_only"] == ["p", "q"]
    assert report["counts"]["visible_after_exclusions_unique"] == 3
    assert "learn-only" in report["learn_ranking"]
    assert all(row["owner_usefulness"] is None and row["reference_relevance"] is None for row in report["items"])
    assert report["quality_metrics"]["precision"] is None
    assert "private organizing text" not in json.dumps(report)
    excluded = next(row for row in report["items"] if row["work_id"] == "learn-only")
    assert excluded["mode_relevance"]["question_tokens"] == ["memory"]
    assert all(value is None for value in excluded["ranks"].values())


def test_comparator_date_diagnostic_never_credits_missing_or_announcement_dates() -> None:
    report = compare_modes([item("a-unknown", "Memory", announced_at="2026-11-05T12:00:00Z"),
                            item("z-known", "Memory", published_at="2020-01-01T00:00:00Z")], {}, {"question": "memory"}, now=NOW)
    assert report["rankings"]["chronological_diagnostic"] == ["z-known", "a-unknown"]
    assert report["denominators"]["research_chronology"] == {"known": 1, "missing": 1, "total": 2}
    unknown = next(row for row in report["items"] if row["work_id"] == "a-unknown")
    assert unknown["chronological_known_date_rank"] is None
    assert unknown["announced_at"] == "2026-11-05T12:00:00Z"
    assert unknown["rank_changes_from_question_only"]["chronological_diagnostic"] == 1


def test_comparator_filters_once_explicit_window_requires_known_dates_and_duplicates_are_counted() -> None:
    base = {"source_id": "chosen", "available_scopes": ["excerpt"], "reading": {"status": "saved"}}
    values = [item("chosen", "Memory", published_at="2026-11-05T12:00:00Z", **base),
              item("chosen", "Memory", version_id="chosen:v2", published_at="2026-11-05T12:00:00Z", **base),
              item("source", "Memory", **{**base, "source_id": "other"}),
              item("access", "Memory", **{**base, "available_scopes": ["metadata"]}),
              item("status", "Memory", **{**base, "reading": {"status": "read"}}),
              item("old", "Memory", published_at="2020-01-01T00:00:00Z", **base),
              item("fresh", "Memory", published_at="2026-11-05T12:00:00Z", **base),
              item("unknown", "Memory", **base),
              item("banned", "Memory advertisement", published_at="2026-11-05T12:00:00Z", **base)]
    report = compare_modes(values, {"exclusions": ["advertisement"]}, {"question": "memory"}, now=NOW,
                           filters={"source_id": "chosen", "access_state": "excerpt", "status": "saved", "days": 7})
    assert all(set(ranking) == {"chosen", "fresh"} for ranking in report["rankings"].values())
    assert report["counts"]["duplicate_records"] == 1
    assert report["duplicate_work_ids"] == {"chosen": 2}
    assert next(row for row in report["items"] if row["work_id"] == "chosen")["version_id"] == "chosen:v1"
    assert report["denominators"]["research_chronology"]["missing"] == 0


@pytest.mark.parametrize("date_fields,eligible", [
    ({"published_at": "2026-11-05T12:00:00Z"}, True),
    ({"updated_at": "2026-11-05T05:00:00-07:00", "published_at": "2020-01-01T00:00:00Z"}, True),
    ({}, False),
    ({"announced_at": "2026-11-05T12:00:00Z", "fetched_at": "2026-11-05T12:00:00Z"}, False),
    ({"published_at": "invalid"}, False),
    ({"published_at": "2026-11-05T12:00:00"}, False),
    ({"updated_at": "invalid", "published_at": "2026-11-05T12:00:00Z"}, False),
    ({"published_at": "2020-01-01T00:00:00Z"}, False),
])
def test_comparator_date_window_matches_api_known_aware_date_eligibility(date_fields: dict[str, Any], eligible: bool) -> None:
    values = [item("a", "Memory", **date_fields)]
    all_dates = compare_modes(values, {}, {"question": "memory"}, now=NOW, filters={"days": 0})
    window = compare_modes(values, {}, {"question": "memory"}, now=NOW, filters={"days": 7})
    assert all_dates["rankings"]["combined_research"] == ["a"]
    assert window["rankings"]["combined_research"] == (["a"] if eligible else [])
    assert all(ranking == (["a"] if eligible else []) for ranking in window["rankings"].values())
    assert values[0].get("published_at") == date_fields.get("published_at")


def test_comparator_empty_denominators_and_escaped_reports() -> None:
    report = compare_modes([item("x", "<script>alert(1)</script> | Other")], {}, {"question": "memory"}, now=NOW)
    assert report["denominators"]["research_relevance"]["unjudged_fraction"] is None
    assert report["editions"]["research"]["allocation"]["actual_fraction"] is None
    assert report["quality_metrics"]["known_reference_recall"] is None
    assert "<script>" not in html_report(report)
    assert "<script>" not in markdown_report(report)
    assert "&#124;" in markdown_report(report)
    assert "unranked" in markdown_report(report)
    with pytest.raises(ValueError, match="timezone_required"):
        compare_modes([], {}, {"question": "memory"}, now=datetime(2026, 11, 5))
    for days in (-1, 366, True):
        with pytest.raises(ValueError, match="date_window"):
            compare_modes([], {}, {"question": "memory"}, now=NOW, filters={"days": days})
    with pytest.raises(ValueError, match="timezone_required"):
        _clock("2026-11-05")


def test_cli_replays_offline_without_db_provider_or_network_imports_and_refuses_overwrite(tmp_path: Path) -> None:
    files = {"items": {"items": [item("a", "Memory")]}, "profile": {"revision": 1, "data": PROFILE}, "project": {"question": "memory", "scope": ""}}
    for name, value in files.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    output = tmp_path / "report"
    arguments = ["--items", str(tmp_path / "items.json"), "--profile", str(tmp_path / "profile.json"), "--project", str(tmp_path / "project.json"), "--now", NOW.isoformat(), "--output", str(output)]
    program = '''import importlib.abc, runpy, socket, sys
class RefuseExternal(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'anthropic','httpx','psycopg','psycopg_pool','dotenv'} or fullname in {'src.workspace.store','src.api'}:
            raise AssertionError('external import forbidden: ' + fullname)
sys.meta_path.insert(0, RefuseExternal())
def no_network(*args, **kwargs):
    raise AssertionError('network forbidden')
socket.socket = no_network
sys.argv = ['workspace_mode_ranking_report', *sys.argv[1:]]
runpy.run_module('tools.workspace_mode_ranking_report', run_name='__main__')
'''
    command = [sys.executable, "-c", program, *arguments]
    environment = {"ANTHROPIC_API_KEY": "local-preview-disabled", "USE_MOCK_DATA": "true", "WORKSPACE_SCHEDULE_APPROVED": "false", "PYTHONUTF8": "1"}
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    raw = (output / "comparison.json").read_bytes()
    report = json.loads(raw)
    assert report["rankings"]["combined_research"] == ["a"]
    assert report["reproduction"]["inputs"]["profile"]["sha256"]
    assert (output / "REPORT.md").is_file() and (output / "index.html").is_file()
    repeated = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=environment, capture_output=True, text=True, check=False)
    assert repeated.returncode != 0 and (output / "comparison.json").read_bytes() == raw
    with pytest.raises(ValueError, match="explicit_bounded_json_file_required"):
        _load(tmp_path / "missing.json")
