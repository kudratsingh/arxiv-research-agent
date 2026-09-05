"""Unit tests for the scripted research tier (WO-C1, ADR 0075).

Three groups, and the third is the one worth reading first.

**The script.** Each responder is a pure function and is tested as one:
the plan is derived from the benchmark query, the report cites exactly
the papers it was handed, and a report with no papers says so instead of
inventing a citation.

**The expectations.** `compute_outcomes` is the research lane's
counterpart of WO-W08's structural expectations, and every one of them
gets a mutation test — a case that breaks exactly one property of a
clean run and asserts the expectation notices.

**The committed baseline.** `tests/fixtures/eval/research-scripted/
baseline.jsonl` is a claim about the world, and the tests below are what
stop it becoming a silently authoritative one: it must carry the whole
benchmark, it must have cost nothing, it must pass the same check CI
runs, it must diff clean against itself — and, the assertion that
matters most, its `provenance.dataset_version` must equal the one this
checkout computes. That last one fails the moment a benchmark query or a
scripted response changes, and the failure names the command that fixes
it.

Nothing here drives the graph. `tests/e2e/test_scripted_research_tier.py`
does that, and it is where the zero-spend proof lives.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from src.config import settings as real_settings
from src.eval import regression_diff as diff
from src.eval import scripted_tier_check as check
from src.eval import simulate_research as sim
from src.eval.benchmark_queries import BENCHMARK_QUERIES, BenchmarkQuery
from src.eval.provenance import PROVENANCE_KEY, check_provenance

pytestmark = pytest.mark.unit


def _query(index: int = 0) -> BenchmarkQuery:
    return BENCHMARK_QUERIES[index]


def _paper(paper_id: str, title: str = "A Paper", authors: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": paper_id,
        "title": title,
        "authors": authors if authors is not None else ["Ada Lovelace", "Alan Turing"],
        "abstract": "An abstract.",
        "url": paper_id,
        "pdf_url": paper_id.replace("/abs/", "/pdf/"),
    }


def _clean_state(papers: int = 3) -> dict[str, Any]:
    """A finished run's state, as the graph would leave it."""
    corpus = [_paper(f"http://arxiv.org/abs/23{i:02d}.0100{i}") for i in range(papers)]
    return {
        "papers": corpus,
        "paper_analyses": [{"paper_id": p["id"]} for p in corpus],
        "citations": [{"paper_id": p["id"], "title": p["title"]} for p in corpus],
        "draft_report": "# A report\n\nWith words in it.",
        "iteration": 1,
        "revision_needed": False,
    }


class TestTheScript:
    def test_the_plan_is_derived_from_the_benchmark_query(self) -> None:
        """Derived, not fixed — so a benchmark edit moves the campaign."""
        query = _query()
        plan = sim._scripted_planner(query)
        assert plan["search_queries"] == list(query["expected_topics"])
        assert len(plan["sub_questions"]) == len(query["expected_topics"])
        for topic, sub_question in zip(
            query["expected_topics"], plan["sub_questions"], strict=True
        ):
            assert topic in sub_question

    def test_the_planner_never_returns_an_empty_list(self) -> None:
        # `planner_agent` falls back to the raw query on an empty list
        # and logs a warning; a scripted tier that silently took that
        # path would be exercising the fallback, not the plan.
        for query in BENCHMARK_QUERIES:
            plan = sim._scripted_planner(query)
            assert plan["sub_questions"] and plan["search_queries"]

    def test_the_reader_response_carries_every_field_the_agent_unpacks(self) -> None:
        # `_analyze_paper` indexes these five directly and lets a
        # KeyError become a degraded placeholder for that paper.
        analysis = sim._scripted_reader()
        assert set(analysis) == {
            "key_findings",
            "methodology",
            "results_summary",
            "limitations",
            "relevance",
        }
        assert isinstance(analysis["relevance"], float)

    def test_the_report_cites_exactly_the_papers_it_was_handed(self) -> None:
        papers = [
            _paper("http://arxiv.org/abs/2311.09000", "A Survey"),
            _paper("http://arxiv.org/abs/2305.13269", "Retrieval"),
        ]
        response = sim._scripted_synthesizer(papers)
        assert [c["paper_id"] for c in response["citations"]] == [
            p["id"] for p in papers
        ]
        # Both surfaces the groundedness check reads: the citation list
        # above, and an inline reference in the body.
        for paper in papers:
            assert f"arXiv:{sim._arxiv_tail(paper['id'])}" in response["draft_report"]

    def test_a_run_that_retrieved_nothing_cites_nothing(self) -> None:
        """The honest degradation, and the one a fixed citation list hides.

        A scripted synthesizer with a hard-coded citation list would
        report five perfectly-grounded claims for a run in which search
        returned no papers at all.
        """
        response = sim._scripted_synthesizer([])
        assert response["citations"] == []
        assert "cites nothing" in response["draft_report"]

    def test_the_report_carries_no_quotable_span(self) -> None:
        # `extract_quotes` reads any six-word double-quoted span as a
        # claim, and with no full text every one would be undecidable.
        report = sim._scripted_synthesizer(
            [_paper("http://arxiv.org/abs/2311.09000")]
        )["draft_report"]
        assert '"' not in report

    def test_a_paper_with_no_title_still_produces_a_citation(self) -> None:
        # `_parse_citations` drops a titleless entry silently, which
        # would shrink the claim set without saying so.
        response = sim._scripted_synthesizer(
            [_paper("http://arxiv.org/abs/2311.09000", title="  ")]
        )
        assert response["citations"][0]["title"].strip()

    @pytest.mark.parametrize(
        ("paper_id", "expected"),
        [
            ("http://arxiv.org/abs/2311.09000", "2023"),
            ("2401.01313", "2024"),
            ("http://arxiv.org/abs/cs.CL/9901001", ""),
            ("", ""),
        ],
    )
    def test_the_citation_year_reads_an_arxiv_prefix(
        self, paper_id: str, expected: str
    ) -> None:
        assert sim._citation_year(paper_id) == expected

    @pytest.mark.parametrize(
        ("paper_id", "expected"),
        [
            ("http://arxiv.org/abs/2311.09000", "2311.09000"),
            ("2311.09000", "2311.09000"),
            ("", ""),
        ],
    )
    def test_the_arxiv_tail_is_the_bare_identifier(
        self, paper_id: str, expected: str
    ) -> None:
        assert sim._arxiv_tail(paper_id) == expected

    def test_the_critic_approves_in_one_pass(self) -> None:
        response = sim._scripted_critic()
        assert response["revision_needed"] is False
        assert response["average_score"] == sim.SCRIPTED_QUALITY_SCORE
        # Above `min_quality_score`, so the supervisor shape would also
        # stop if it were ever pointed at this tier.
        assert response["average_score"] > real_settings.min_quality_score


class TestTheScriptVersion:
    def test_the_digest_is_derived_from_the_responders_own_source(self) -> None:
        digest = sim.script_digest()
        assert len(digest) == 12
        assert all(char in "0123456789abcdef" for char in digest)

    def test_editing_a_responder_moves_the_digest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The property the whole staleness story rests on.

        Swapping one responder for a different function is the smallest
        stand-in for editing one, and it must move the version that
        decides whether two campaigns may be compared.
        """
        before = sim.script_digest()

        def _different_critic() -> dict[str, Any]:
            return {"average_score": 0.99}

        monkeypatch.setattr(
            sim,
            "_SCRIPT_SOURCES",
            (*sim._SCRIPT_SOURCES[:-1], _different_critic),
        )
        assert sim.script_digest() != before

    def test_an_unreadable_source_falls_back_to_the_declared_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A frozen or zipped install has no source to digest.

        `len` stands in for a callable `inspect.getsource` cannot read:
        it raises `TypeError` for a builtin exactly as it raises `OSError`
        for a module with no file. The fallback has to be a *declared*
        version rather than a crash, and a row that carries it says so —
        the digest it replaces is simply absent from the string.
        """
        monkeypatch.setattr(sim, "_SCRIPT_SOURCES", (len,))
        assert sim.script_digest() == sim.SCRIPT_VERSION

    def test_the_dataset_version_carries_the_benchmark_and_the_script(self) -> None:
        version = sim.scripted_dataset_version()
        assert version.startswith("research-benchmark@")
        assert f"+script:{sim.script_digest()}" in version
        # It is a comparability field, which is the whole point: a
        # campaign compared across a changed script exits 3.
        assert "dataset_version" in diff.COMPARABILITY_FIELDS


class TestProvenance:
    def test_a_scripted_row_is_attributable(self) -> None:
        assert check_provenance(dict(sim.scripted_provenance())) == []

    def test_the_tier_is_neither_the_funded_lane_nor_the_learning_one(self) -> None:
        from src.eval.runner import RESEARCH_TIER

        block = sim.scripted_provenance()
        assert block["tier"] == sim.RESEARCH_SCRIPTED_TIER
        assert block["tier"] != RESEARCH_TIER
        assert block["tier"] != "scripted"
        # `tier` is a comparability field, so a scripted summary meeting
        # a funded one is refused rather than diffed.
        assert "tier" in diff.COMPARABILITY_FIELDS

    def test_the_check_module_agrees_on_the_tier_string(self) -> None:
        # `scripted_tier_check` restates the string rather than importing
        # it, to keep LangGraph out of a JSONL reader. This is the pin
        # that keeps the two copies equal.
        assert check.RESEARCH_SCRIPTED_TIER == sim.RESEARCH_SCRIPTED_TIER


class TestStructuralExpectations:
    def test_a_clean_run_has_none(self) -> None:
        outcomes = sim.compute_outcomes(sim.FIXED_PIPELINE, _clean_state())
        assert outcomes.expectation_failures == []
        assert outcomes.trajectory_expected is True
        assert (outcomes.papers, outcomes.analyses, outcomes.citations) == (3, 3, 3)

    def test_a_skipped_node_fails_the_trajectory(self) -> None:
        outcomes = sim.compute_outcomes(
            ("planner", "search", "synthesizer", "critic"), _clean_state()
        )
        assert outcomes.trajectory_expected is False
        assert any("trajectory was" in f for f in outcomes.expectation_failures)

    def test_an_extra_synthesizer_pass_fails_the_trajectory(self) -> None:
        outcomes = sim.compute_outcomes(
            (*sim.FIXED_PIPELINE, "synthesizer", "critic"), _clean_state()
        )
        assert outcomes.trajectory_expected is False

    def test_a_dropped_reader_analysis_is_caught(self) -> None:
        state = _clean_state()
        state["paper_analyses"] = state["paper_analyses"][:-1]
        failures = sim.compute_outcomes(sim.FIXED_PIPELINE, state).expectation_failures
        assert any("reader fan-out dropped one" in f for f in failures)

    def test_an_empty_corpus_is_caught(self) -> None:
        state = _clean_state()
        state["papers"] = []
        state["paper_analyses"] = []
        failures = sim.compute_outcomes(sim.FIXED_PIPELINE, state).expectation_failures
        assert any("no papers" in f for f in failures)

    def test_an_empty_report_is_caught(self) -> None:
        state = _clean_state()
        state["draft_report"] = "   "
        failures = sim.compute_outcomes(sim.FIXED_PIPELINE, state).expectation_failures
        assert any("no report" in f for f in failures)

    def test_a_rejected_citation_list_is_caught(self) -> None:
        """The defect a non-empty report hides completely."""
        state = _clean_state()
        state["citations"] = []
        failures = sim.compute_outcomes(sim.FIXED_PIPELINE, state).expectation_failures
        assert any("_parse_citations" in f for f in failures)

    def test_a_titleless_citation_is_caught(self) -> None:
        state = _clean_state()
        state["citations"][1]["title"] = ""
        failures = sim.compute_outcomes(sim.FIXED_PIPELINE, state).expectation_failures
        assert any("citation 1 has no title" in f for f in failures)

    def test_a_second_critic_pass_is_caught(self) -> None:
        state = _clean_state()
        state["iteration"] = 2
        failures = sim.compute_outcomes(sim.FIXED_PIPELINE, state).expectation_failures
        assert any("recorded 2 pass" in f for f in failures)

    def test_an_outstanding_revision_is_caught(self) -> None:
        state = _clean_state()
        state["revision_needed"] = True
        failures = sim.compute_outcomes(sim.FIXED_PIPELINE, state).expectation_failures
        assert any("revision still outstanding" in f for f in failures)


class TestTheSurface:
    def _args(self, **overrides: Any) -> argparse.Namespace:
        return argparse.Namespace(**{"repeats": 1, **overrides})

    def test_it_installs_and_restores_every_patch(self) -> None:
        import src.agents.critic as critic_module
        import src.agents.planner as planner_module
        import src.agents.reader as reader_module
        import src.agents.synthesizer as synthesizer_module
        import src.llm as llm_module

        before = {
            "planner": planner_module.call_llm_json,
            "reader": reader_module.call_llm_json,
            "reader_pdf": reader_module.parse_pdf,
            "synthesizer": synthesizer_module.call_llm_json,
            "critic": critic_module.call_llm_json,
            "llm": llm_module.call_llm,
        }
        with sim.scripted_surface(_query()) as surface:
            # `==` rather than `is`: attribute access on a bound method
            # builds a fresh object every time, so identity would fail
            # against a patch that landed correctly.
            assert planner_module.call_llm_json == surface.planner
            assert synthesizer_module.call_llm_json == surface.synthesizer
            assert reader_module.parse_pdf("http://example.invalid/x.pdf") == ""
            assert llm_module.call_llm is not before["llm"]
        assert planner_module.call_llm_json is before["planner"]
        assert reader_module.call_llm_json is before["reader"]
        assert reader_module.parse_pdf is before["reader_pdf"]
        assert synthesizer_module.call_llm_json is before["synthesizer"]
        assert critic_module.call_llm_json is before["critic"]
        assert llm_module.call_llm is before["llm"]

    def test_it_restores_on_the_exception_path(self) -> None:
        """A campaign whose second query ran under the first query's
        surface would be measuring the harness."""
        import src.agents.planner as planner_module

        before = planner_module.call_llm_json
        with pytest.raises(RuntimeError, match="boom"), sim.scripted_surface(_query()):
            raise RuntimeError("boom")
        assert planner_module.call_llm_json is before

    def test_the_tripwire_refuses_any_uncovered_model_call(self) -> None:
        """Layer three of the zero-spend argument, on its own.

        The four agent patches are an enumeration and enumerations go
        stale. This one covers what they miss by construction.
        """
        import src.llm as llm_module

        with (
            sim.scripted_surface(_query()),
            pytest.raises(sim.ScriptedSurfaceBreach, match="zero spend"),
        ):
            llm_module.call_llm(prompt="anything")

    def test_it_counts_what_the_graph_asked_for(self) -> None:
        with sim.scripted_surface(_query()) as surface:
            surface.planner()
            surface.reader()
            surface.reader()
            surface.synthesizer()
            surface.critic()
        assert surface.calls == {
            "planner": 1,
            "search": 0,
            "reader": 2,
            "synthesizer": 1,
            "critic": 1,
        }
        assert surface.total_calls == 5

    def test_the_synthesizer_cites_the_papers_the_driver_observed(self) -> None:
        """The seam that keeps this tier's citations the product's.

        Without `observe`, the scripted report would cite a fixed list
        and a search regression would be invisible to it.
        """
        surface = sim.ScriptedSurface(_query())
        assert surface.synthesizer()["citations"] == []
        surface.observe("search", {"papers": [_paper("http://arxiv.org/abs/2311.09000")]})
        assert [c["paper_id"] for c in surface.synthesizer()["citations"]] == [
            "http://arxiv.org/abs/2311.09000"
        ]

    def test_observe_ignores_a_node_it_does_not_read(self) -> None:
        surface = sim.ScriptedSurface(_query())
        surface.observe("planner", {"papers": [_paper("http://arxiv.org/abs/1")]})
        surface.observe("search", "not a dict")
        surface.observe("search", {"papers": "not a list"})
        assert surface.papers == []


class TestConfigProblem:
    def _args(self, **overrides: Any) -> argparse.Namespace:
        return argparse.Namespace(**{"repeats": 1, **overrides})

    def test_a_mock_mode_campaign_starts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sim, "settings", real_settings.model_copy(update={"use_mock_data": True})
        )
        assert sim.config_problem(self._args()) is None

    def test_it_refuses_when_mock_mode_is_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The refusal that costs money if it is missing."""
        monkeypatch.setattr(
            sim, "settings", real_settings.model_copy(update={"use_mock_data": False})
        )
        problem = sim.config_problem(self._args())
        assert problem is not None
        assert "USE_MOCK_DATA" in problem
        assert "arxiv.org" in problem

    def test_it_refuses_zero_repeats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            sim, "settings", real_settings.model_copy(update={"use_mock_data": True})
        )
        assert sim.config_problem(self._args(repeats=0)) is not None

    def test_the_cli_returns_the_config_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            sim, "settings", real_settings.model_copy(update={"use_mock_data": False})
        )
        assert sim.main([]) == 1
        assert "USE_MOCK_DATA" in capsys.readouterr().err

    def test_there_is_no_tier_flag_to_fall_into_a_paid_run_with(self) -> None:
        """Layer one of the zero-spend argument, asserted rather than
        described: this module has no funded setting at all."""
        with pytest.raises(SystemExit):
            sim._parse_args(["--tier", "funded"])


class TestSummaryLine:
    def _record(self, **overrides: Any) -> dict[str, Any]:
        record: dict[str, Any] = {
            "record_id": "q1",
            "query_id": "q1",
            "repeat": 1,
            "tier": sim.RESEARCH_SCRIPTED_TIER,
            "elapsed_sec": 0.05,
            "scoring_sec": 0.001,
            "error": None,
            "metrics_error": None,
            "costs": {"total_cost_usd": 0.0, "call_count": 0},
            "judge_costs": {"total_cost_usd": 0.0, "call_count": 0},
            "scripted_calls": {"planner": 1, "reader": 5},
            "outcomes": {
                "trajectory": list(sim.FIXED_PIPELINE),
                "trajectory_expected": True,
                "papers": 5,
                "analyses": 5,
                "citations": 5,
                "report_chars": 900,
                "iterations": 1,
                "expectation_failures": [],
            },
            "groundedness": {
                "citation_resolution_rate": {
                    "value": 1.0,
                    "denominator": 10,
                    "reason": None,
                },
                "quote_verbatim_rate": {"value": None, "reason": "no_quotes"},
                "unsupported_claim_count": {"numerator": 0},
                "claims": [
                    {"claim_id": "citation:aaaa", "grounded": True},
                    {"claim_id": "citation:bbbb", "grounded": False},
                    {"claim_id": "citation:cccc", "grounded": None},
                ],
            },
            "metrics": {"citation_accuracy": {"score": 1.0}},
            PROVENANCE_KEY: dict(sim.scripted_provenance()),
        }
        record.update(overrides)
        return record

    def test_it_publishes_the_paired_outcomes_without_the_undecided_claim(
        self,
    ) -> None:
        row = sim.summary_line(self._record())
        assert row["paired_outcomes"] == {
            "citation:aaaa": True,
            "citation:bbbb": False,
        }
        assert row["claims_decided"] == 2

    def test_a_record_with_no_groundedness_says_so(self) -> None:
        row = sim.summary_line(self._record(groundedness=None))
        assert row["paired_outcomes"] == {}
        assert row["claims_decided"] is None

    def test_the_denominator_travels_with_the_rate(self) -> None:
        row = sim.summary_line(self._record())
        assert row["citation_resolution_rate"] == 1.0
        assert row["citations_checked"] == 10
        assert row["quote_verbatim_reason"] == "no_quotes"

    def test_the_row_carries_the_zero_cost_columns_the_check_asserts(self) -> None:
        row = sim.summary_line(self._record())
        for field in check.RESEARCH_COST_FIELDS + check.RESEARCH_CALL_FIELDS:
            assert row[field] == 0, field
        assert row[check.RESEARCH_PROFILE.proof_of_work_field or ""] == 6

    def test_the_row_carries_no_judged_metric(self) -> None:
        # Three of `runner.py`'s five metrics are paid judges. A column
        # that is null on every row of every campaign is noise.
        row = sim.summary_line(self._record())
        for field in ("completeness", "faithfulness", "retrieval_recall"):
            assert field not in row


class TestSummaryMarkdown:
    def test_it_names_the_tier_s_own_limitation(self) -> None:
        markdown = sim.summary_markdown([], "rs-test")
        assert "the harness's" in markdown
        assert "$0.0000" in markdown


class TestTheCommittedBaseline:
    """`tests/fixtures/eval/research-scripted/baseline.jsonl`.

    A committed baseline is an assertion about what the product does, and
    an unchecked one is worse than none: it goes on passing after the
    thing it describes has moved.
    """

    @staticmethod
    def _rows() -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in sim.BASELINE_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_the_baseline_is_committed_at_the_path_the_module_names(self) -> None:
        assert sim.BASELINE_PATH.is_file(), (
            f"{sim.BASELINE_PATH} is missing. Regenerate it with "
            f"`{sim.BASELINE_REGEN_COMMAND}`."
        )

    def test_it_covers_the_whole_benchmark(self) -> None:
        rows = self._rows()
        assert len(rows) == len(BENCHMARK_QUERIES)
        assert {row["query_id"] for row in rows} == {
            q["query_id"] for q in BENCHMARK_QUERIES
        }

    def test_it_is_not_stale(self) -> None:
        """The staleness check, and the reason the script versions itself.

        `dataset_version` folds the benchmark's fingerprint and the
        scripted responders' own source digest into one string, and it
        is a comparability field — so a baseline recorded before either
        moved would make the differ exit 3 rather than report a verdict.
        Failing here instead is the same finding, delivered before CI
        rather than during it, with the fix in the message.
        """
        expected = sim.scripted_dataset_version()
        for row in self._rows():
            assert row[PROVENANCE_KEY]["dataset_version"] == expected, (
                "the committed scripted-research baseline was recorded against "
                f"a different instrument ({row[PROVENANCE_KEY]['dataset_version']!r} "
                f"vs {expected!r}). The benchmark queries or the scripted "
                f"responses moved. Regenerate it: `{sim.BASELINE_REGEN_COMMAND}`."
            )

    def test_it_passes_the_check_ci_runs(self) -> None:
        problems = check.check_rows(
            self._rows(),
            expected_sessions=len(BENCHMARK_QUERIES),
            profile=check.RESEARCH_PROFILE,
        )
        assert problems == []

    def test_it_cost_nothing(self) -> None:
        assert check.total_spend(self._rows()) == 0.0

    def test_it_carries_the_paired_claims_the_gate_needs(self) -> None:
        rows = self._rows()
        claims = sum(len(row["paired_outcomes"]) for row in rows)
        # The mock corpus is five fixed papers, so a clean campaign
        # carries five claims per query. The number is asserted rather
        # than described because it is the denominator every power
        # statement in the report is computed from.
        assert claims == 5 * len(BENCHMARK_QUERIES)
        for row in rows:
            assert row["claims_decided"] == 5

    def test_it_diffs_clean_against_itself(self) -> None:
        rows = self._rows()
        aggregated = diff.aggregate_repeats(rows, lane=diff.SCRIPTED_RESEARCH_LANE)
        report = diff.diff_summaries(
            aggregated, aggregated, lane=diff.SCRIPTED_RESEARCH_LANE
        )
        assert report["decision"].verdict == "PROMOTE"
        assert report["claims"] is not None
        assert report["claims"].outcomes.matched == 5 * len(BENCHMARK_QUERIES)

    def test_one_flipped_claim_is_a_rollback(self, tmp_path: Path) -> None:
        """The demonstration the paired path exists for.

        A single claim losing its grounding moves
        `citation_resolution_rate` by `1 / 10` on that query — exactly
        the flat epsilon, which `_significant` requires a move to
        *exceed*. Every band stays green; the pairing does not.
        """
        rows = self._rows()
        candidate = [json.loads(json.dumps(row)) for row in rows]
        first = candidate[0]
        claim_id = sorted(first["paired_outcomes"])[0]
        first["paired_outcomes"][claim_id] = False
        first["citation_resolution_rate"] = 0.9

        lane = diff.SCRIPTED_RESEARCH_LANE
        report = diff.diff_summaries(
            diff.aggregate_repeats(rows, lane=lane),
            diff.aggregate_repeats(candidate, lane=lane),
            lane=lane,
        )
        assert report["has_regressions"] is False, (
            "the per-metric bands are expected to stay green here; that is "
            "the point of the test"
        )
        assert report["decision"].verdict == "ROLLBACK"
        assert report["claims"] is not None
        assert report["claims"].adverse == 1


class _FakeApp:
    """A compiled graph stand-in, so a failure path can be provoked.

    Driving the real graph into an error would mean breaking a node,
    which is a change to a module this work order does not own. The
    fake's only job is to reproduce the *shape* `drive_query` consumes —
    a `(mode, payload)` stream — including the two shapes it has to
    ignore.
    """

    def __init__(self, chunks: list[Any] | None = None, raises: Exception | None = None) -> None:
        self._chunks = chunks or []
        self._raises = raises

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        if self._raises is not None:
            raise self._raises
        return iter(self._chunks)


def _happy_chunks() -> list[Any]:
    papers = [_paper("http://arxiv.org/abs/2311.09000")]
    return [
        ("updates", {"planner": {"sub_questions": ["q"]}}),
        ("updates", {"search": {"papers": papers}}),
        # The two shapes `drive_query` must skip: LangGraph's interrupt
        # sentinel is not a node, and a non-dict payload is not an
        # update at all.
        ("updates", {"__interrupt__": object()}),
        ("updates", "not a mapping"),
        ("updates", {"reader": {}}),
        ("updates", {"synthesizer": {}}),
        ("updates", {"critic": {}}),
        (
            "values",
            {
                "papers": papers,
                "paper_analyses": [{"paper_id": papers[0]["id"]}],
                "citations": [{"paper_id": papers[0]["id"], "title": "A Paper"}],
                "draft_report": "# r\n\narXiv:2311.09000",
                "iteration": 1,
                "revision_needed": False,
            },
        ),
    ]


class TestRunQuery:
    def test_a_clean_run_records_its_trajectory_and_claims(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sim, "build_workflow", lambda **_k: _FakeApp(_happy_chunks()))
        record = sim.run_query(_query())
        assert record["error"] is None
        assert record["trajectory"] == list(sim.FIXED_PIPELINE)
        assert record["outcomes"]["expectation_failures"] == []
        row = sim.summary_line(record)
        assert row["claims_decided"] == 1
        assert row["total_cost_usd"] == 0.0

    def test_a_graph_failure_lands_on_the_record_rather_than_the_campaign(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR 0008: the outer loop keeps making progress."""
        monkeypatch.setattr(
            sim,
            "build_workflow",
            lambda **_k: _FakeApp(raises=RuntimeError("graph exploded")),
        )
        record = sim.run_query(_query())
        assert record["error"] == "RuntimeError: graph exploded"
        assert record["traceback"]
        assert sim.summary_line(record)["error"]

    def test_a_scoring_failure_does_not_discard_the_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sim, "build_workflow", lambda **_k: _FakeApp(_happy_chunks()))

        def _boom(*_a: Any, **_k: Any) -> Any:
            raise ValueError("scorer broke")

        monkeypatch.setattr(sim, "measure_groundedness", _boom)
        record = sim.run_query(_query())
        assert record["error"] is None
        assert record["metrics_error"] == "ValueError: scorer broke"
        assert record["trajectory"] == list(sim.FIXED_PIPELINE)

    def test_an_interrupt_carries_the_partial_record_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.eval.runner import EvalInterrupted

        monkeypatch.setattr(
            sim,
            "build_workflow",
            lambda **_k: _FakeApp(raises=KeyboardInterrupt("signal 15")),
        )
        with pytest.raises(EvalInterrupted) as excinfo:
            sim.run_query(_query())
        assert excinfo.value.record["error"].startswith("Interrupted:")
        assert excinfo.value.record["elapsed_sec"] >= 0.0


class TestCampaignReporting:
    def _errored(self) -> dict[str, Any]:
        return {
            "record_id": "q-bad",
            "query_id": "q-bad",
            "error": "RuntimeError: boom | with a pipe",
            "outcomes": None,
            "costs": {},
            "judge_costs": {},
            PROVENANCE_KEY: dict(sim.scripted_provenance()),
        }

    def _unmet(self) -> dict[str, Any]:
        return {
            "record_id": "q-unmet",
            "query_id": "q-unmet",
            "error": None,
            "costs": {"total_cost_usd": 0.0, "call_count": 0},
            "judge_costs": {"total_cost_usd": 0.0, "call_count": 0},
            "scripted_calls": {"planner": 1},
            "outcomes": {
                "trajectory": ["planner"],
                "trajectory_expected": False,
                "papers": 0,
                "analyses": 0,
                "citations": 0,
                "report_chars": 0,
                "iterations": 0,
                "expectation_failures": ["search put no papers on the state"],
            },
            PROVENANCE_KEY: dict(sim.scripted_provenance()),
        }

    def test_the_summary_names_every_error_and_every_unmet_expectation(self) -> None:
        markdown = sim.summary_markdown([self._errored(), self._unmet()], "rs-x")
        assert "## Errors" in markdown
        assert "## Unmet structural expectations" in markdown
        assert "search put no papers on the state" in markdown
        # An exception body carrying a pipe would corrupt the table from
        # that row down; `_fmt_cell_text` is what stops it.
        assert "boom \\| with a pipe" in markdown

    def test_the_stdout_line_reports_an_error_instead_of_a_table_row(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sim._print_result(self._errored())
        assert "ERROR: RuntimeError" in capsys.readouterr().out

    def test_the_stdout_line_names_each_unmet_expectation(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record = self._unmet()
        record["metrics_error"] = "ValueError: partial"
        sim._print_result(record)
        out = capsys.readouterr().out
        assert "traj=BROKEN" in out
        assert "UNMET: search put no papers" in out
        assert "PARTIAL SCORE" in out


class TestCampaignCLI:
    def test_an_unknown_query_id_is_refused(self) -> None:
        with pytest.raises(SystemExit, match="Unknown query IDs"):
            sim._select_queries(["no-such-query"])

    def test_no_ids_means_the_whole_benchmark(self) -> None:
        assert sim._select_queries(None) == list(BENCHMARK_QUERIES)

    def test_a_campaign_of_failing_queries_exits_non_zero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A non-zero exit and the counts in the last line.

        The scripted tier's whole claim is that a broken pipeline fails
        *here*; a campaign that swallowed a failing query and exited 0
        would be worse than no gate. Every attempted query errors in
        this case, which `runner._exit_code` reports as 4 rather than 3
        — the distinction exists so a wrapper can tell a quality problem
        from an outage without parsing stdout (ADR 0050).
        """
        from src.eval.runner import EXIT_ALL_FAILED

        monkeypatch.setattr(
            sim, "settings", real_settings.model_copy(update={"use_mock_data": True})
        )
        broken = _FakeApp(raises=RuntimeError("graph exploded"))
        monkeypatch.setattr(sim, "build_workflow", lambda **_k: broken)
        output_dir = tmp_path / "campaign"
        assert (
            sim.main(
                [
                    "--queries",
                    BENCHMARK_QUERIES[0]["query_id"],
                    "--output-dir",
                    str(output_dir),
                ]
            )
            == EXIT_ALL_FAILED
        )
        out = capsys.readouterr().out
        assert "0/1 succeeded, 1 errored" in out
        assert "total $0.0000" in out

    def test_a_campaign_counts_unmet_expectations_in_its_closing_line(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(
            sim, "settings", real_settings.model_copy(update={"use_mock_data": True})
        )
        # A run that reaches only the planner: every downstream
        # expectation is unmet and the campaign says how many queries
        # carried one.
        monkeypatch.setattr(
            sim,
            "build_workflow",
            lambda **_k: _FakeApp(
                [("updates", {"planner": {}}), ("values", {"iteration": 0})]
            ),
        )
        output_dir = tmp_path / "campaign"
        assert (
            sim.main(
                [
                    "--queries",
                    BENCHMARK_QUERIES[0]["query_id"],
                    "--output-dir",
                    str(output_dir),
                ]
            )
            == 0
        )
        assert "1 with unmet expectations" in capsys.readouterr().out

    def test_an_interrupted_campaign_flushes_and_exits_130(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A kill loses at most the in-flight query (ADR 0050)."""
        from src.eval.runner import EXIT_INTERRUPTED, EvalInterrupted

        monkeypatch.setattr(
            sim, "settings", real_settings.model_copy(update={"use_mock_data": True})
        )

        def _interrupt(query: BenchmarkQuery, *, repeat: int = 1) -> dict[str, Any]:
            raise EvalInterrupted(
                {
                    "record_id": query["query_id"],
                    "query_id": query["query_id"],
                    "error": "Interrupted: KeyboardInterrupt",
                    "costs": {"total_cost_usd": 0.0, "call_count": 0},
                    "judge_costs": {"total_cost_usd": 0.0, "call_count": 0},
                    "outcomes": None,
                    PROVENANCE_KEY: dict(sim.scripted_provenance()),
                }
            )

        monkeypatch.setattr(sim, "run_query", _interrupt)
        output_dir = tmp_path / "campaign"
        assert (
            sim.main(
                [
                    "--queries",
                    BENCHMARK_QUERIES[0]["query_id"],
                    "--output-dir",
                    str(output_dir),
                ]
            )
            == EXIT_INTERRUPTED
        )
        assert "Interrupted" in capsys.readouterr().out
        # The partial record is on disk, which is the whole point.
        assert (output_dir / "summary.jsonl").read_text().strip()
