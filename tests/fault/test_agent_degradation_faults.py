"""The three agent-side rungs of the ladder, on all three contracts (CAP-08).

Every other file in this tier watches a failure that *ended* a run. These
nine watch failures that did not end anything: a run that degraded, kept
going, and reported `succeeded`. That is what makes them the hardest
faults in the tier to see and the reason `docs/reliability.md` §5 writes
the rule it does — *every rung must emit a distinct marker, otherwise
degradation makes the dashboard look better while the product gets
worse.* For rungs 2, 3 and 5 there was no marker on a metric until
CAP-08, because every call site is in `src/agents/` and WO-D5's fence
(ADR 0081) did not cover it.

The triple is genuinely three-legged here only because
`research_degradations_total` exists. `research_jobs_total` cannot see
any of these — the job succeeded, and that is the *correct* answer —
and `research_job_duration_seconds` moves in the reassuring direction,
because every one of these paths is faster than the path it replaced.

| rung | site | fault forced | code | event | metric attributes |
|---|---|---|---|---|---|
| `reduced_tool` | `search.py` | `USE_MOCK_DATA` | *(none)* | `search_mock_data_served` | `{rung="reduced_tool", component="search"}` |
| `reduced_tool` | `search.py` | plan over `MAX_SEARCH_QUERIES_PER_RUN` | *(none)* | `search_query_cap_applied` | same |
| `reduced_tool` | `search.py` | a re-search round returns nothing | *(none)* | `search_empty_keeping_prior_papers` | same |
| `reduced_tool` | `search.py` | one of two queries hits an arXiv outage | `upstream_arxiv`, **not taken** | `search_partial_arxiv_failure` | same |
| `partial_results` | `reader.py` | the PDF yields no text | *(none)* | `reader_paper_abstract_only` | `{rung="partial_results", component="reader"}` |
| `model_fallback` | `planner.py` | the plan does not parse | *(none)* | `planner_plan_fallback_to_query` | `{rung="model_fallback", component="planner"}` |
| `model_fallback` | `supervisor.py` | the judge answers unusably | *(none)* | `supervisor_llm_failed_fallback_to_default` | `{..., component="supervisor"}` |
| `model_fallback` | `verifier.py` | the judge's body will not parse | `upstream_model_output` | `verifier_llm_failed_fallback` | `{..., component="verifier"}` |
| `model_fallback` | `synthesizer.py` | the first draft is unusable | *(none)* | `synthesizer_retrying_malformed_response` | `{..., component="synthesizer"}` |

**Most of these rows have no error code, and that is the contract.** A
degraded run acquires no `AppError` — if it did, it would be a failed
run and the tier's other files would already cover it. Row 4 and row 8
are the two that touch a code, and they touch it from opposite sides:
the search node *has* `upstream_arxiv` in reach and deliberately does
not take it, while `verify_node` writes `upstream_model_output` onto the
state as the abstention's reason, so the code is read off a surface
rather than asserted about an exception.

**The negative case is not decoration.** `TestTheHealthyPathIsSilent`
drives the same four nodes with everything working and asserts the
counter recorded *nothing at all*. A quality SLI whose numerator moves
on a healthy run is worse than no SLI, because it is wrong in the
direction that gets believed.

Mutation-check: deleting any one `record_degradation_rung` call in
`src/agents/` fails exactly one test here by name, plus
`tests/test_degradation_ladder.py`'s
`test_the_uninstrumented_rungs_are_exactly_the_declared_ones`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.agents import planner as planner_module
from src.agents import reader as reader_module
from src.agents import search as search_module
from src.agents import supervisor as supervisor_module
from src.agents import synthesizer as synth_module
from src.agents import verifier as verifier_module
from src.config import Settings
from src.errors import UpstreamArxiv, UpstreamModelOutput
from src.graph.state import PaperMetadata, ResearchState
from src.observability.metrics import (
    DEGRADATION_RUNG_MODEL_FALLBACK,
    DEGRADATION_RUNG_PARTIAL_RESULTS,
    DEGRADATION_RUNG_REDUCED_TOOL,
)
from src.tools.arxiv_search import ArxivUnavailableError

from .conftest import TripleObserver

pytestmark = [pytest.mark.unit, pytest.mark.fault]

_INSTRUMENT = "research_degradations_total"


# ---------------------------------------------------------------------------
# Fixtures shared by the four search scenarios
# ---------------------------------------------------------------------------


def _paper(arxiv_id: str = "2311.09000") -> PaperMetadata:
    return PaperMetadata(
        id=f"http://arxiv.org/abs/{arxiv_id}",
        title=f"Paper {arxiv_id}",
        authors=["A"],
        abstract="An abstract.",
        url=f"http://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"http://arxiv.org/pdf/{arxiv_id}",
    )


def _search_state(
    queries: list[str], papers: list[PaperMetadata] | None = None
) -> ResearchState:
    state: dict[str, Any] = {"query": "What is RAG?", "search_queries": queries}
    if papers is not None:
        state["papers"] = papers
    return state  # type: ignore[return-value]


def _live_search(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    """Point the search node at a live-shaped, network-free run.

    `use_mock_data=False` is the half that matters: with the fixture
    flag on, the node returns before any of the other three rungs can
    be reached, so a scenario that forgot it would pass while asserting
    the wrong rung. Semantic Scholar is off because its enrichment is a
    second network dependency with a rung of its own to come, and the
    pacing sleep is removed because three seconds per query is real
    time this tier would spend proving nothing.
    """
    monkeypatch.setattr(
        search_module,
        "settings",
        Settings(use_mock_data=False, enable_semantic_scholar=False, **overrides),
    )
    monkeypatch.setattr(search_module, "interruptible_sleep", lambda _s: None)
    monkeypatch.setattr(
        search_module,
        "rank_papers_by_relevance",
        lambda _query, papers, top_k: list(papers)[:top_k],
    )


class TestReducedTool:
    """Rung 2 — search proceeds on less than it asked for."""

    def test_the_fixture_set_is_a_reduced_tool_even_though_the_banner_says_so(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one rung on this ladder that the user is told about.

        Disclosure and measurement are different jobs. The demo banner
        answers "why are these papers odd?" for one reader of one run;
        the counter answers "what fraction of the fleet is being served
        from fixtures?", which no banner can. Counted for the same
        reason ADR 0081 gives for counting the reader: the run
        succeeds, so no other instrument can see it.
        """
        monkeypatch.setattr(
            search_module,
            "settings",
            Settings(use_mock_data=True, enable_semantic_scholar=False),
        )
        monkeypatch.setattr(
            search_module,
            "rank_papers_by_relevance",
            lambda _query, papers, top_k: list(papers)[:top_k],
        )

        update = search_module.search_agent(_search_state(["rag"]))

        assert update["papers"], "the fixture set is what the node served"
        triple.assert_triple(
            code=None,
            event="search_mock_data_served",
            instrument=_INSTRUMENT,
            attributes={"rung": DEGRADATION_RUNG_REDUCED_TOOL, "component": "search"},
        )

    def test_the_query_cap_is_counted_and_is_counted_before_the_slice(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rung with no failure anywhere in it.

        Nothing is down: the plan simply asked for more retrieval than
        one run is allowed to do, and the queries past the cap are
        dropped. After the slice there is no evidence in the state that
        anything was dropped at all, which is why the count has to
        happen on the line before it.
        """
        _live_search(monkeypatch)
        issued: list[str] = []

        def _fake_search(
            q: str, max_results: int, raise_on_unavailable: bool = False
        ) -> list[PaperMetadata]:
            issued.append(q)
            return [_paper(f"2311.0900{len(issued)}")]

        monkeypatch.setattr(search_module, "search_arxiv", _fake_search)
        cap = search_module.MAX_SEARCH_QUERIES_PER_RUN
        over_plan = [f"q{i}" for i in range(cap + 3)]

        update = search_module.search_agent(_search_state(over_plan))

        # The reduction is real: three queries were never issued.
        assert len(issued) == cap
        assert update["papers"]
        record = triple.assert_triple(
            code=None,
            event="search_query_cap_applied",
            instrument=_INSTRUMENT,
            attributes={"rung": DEGRADATION_RUNG_REDUCED_TOOL, "component": "search"},
        )
        assert record.requested == cap + 3  # type: ignore[attr-defined]
        assert record.cap == cap  # type: ignore[attr-defined]

    def test_a_round_that_returns_nothing_and_keeps_prior_papers_is_counted(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A supervisor re-search that found nothing, serving stale hits.

        The node is right to keep them — destroying a result set an
        earlier round paid for would be worse — but the run then
        synthesizes from retrieval that answers a *different* set of
        queries, and reports success either way.
        """
        _live_search(monkeypatch)
        monkeypatch.setattr(
            search_module,
            "search_arxiv",
            lambda q, max_results, raise_on_unavailable=False: [],
        )
        prior = [_paper("2311.09001")]

        update = search_module.search_agent(_search_state(["again"], papers=prior))

        assert update["papers"] == prior
        record = triple.assert_triple(
            code=None,
            event="search_empty_keeping_prior_papers",
            instrument=_INSTRUMENT,
            attributes={"rung": DEGRADATION_RUNG_REDUCED_TOOL, "component": "search"},
        )
        # Nothing failed at the transport level, so this is the empty
        # answer rather than the outage — the two rungs would otherwise
        # be indistinguishable on the metric.
        assert record.failed_queries == 0  # type: ignore[attr-defined]

    def test_a_partial_arxiv_outage_is_counted_and_no_error_code_is_taken(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Half the corpus is missing and the run has no way to say so.

        `ArxivUnavailableError` is raised, caught, and dropped: the
        remaining queries may succeed and a partial result set beats no
        result set. Correct, and it means `upstream_arxiv` — a code
        this run could legitimately have ended on — is deliberately not
        taken, so the *only* thing that can carry the degradation
        anywhere is this counter.
        """
        _live_search(monkeypatch)

        def _one_down(
            q: str, max_results: int, raise_on_unavailable: bool = False
        ) -> list[PaperMetadata]:
            if q == "down":
                raise ArxivUnavailableError("arXiv is refusing")
            return [_paper("2311.09002")]

        monkeypatch.setattr(search_module, "search_arxiv", _one_down)

        update = search_module.search_agent(_search_state(["down", "up"]))

        assert len(update["papers"]) == 1
        record = triple.assert_triple(
            code=None,
            event="search_partial_arxiv_failure",
            instrument=_INSTRUMENT,
            attributes={"rung": DEGRADATION_RUNG_REDUCED_TOOL, "component": "search"},
        )
        assert record.failed_queries == 1  # type: ignore[attr-defined]
        assert record.n_queries == 2  # type: ignore[attr-defined]
        # The code exists and is registered; this run did not take it,
        # which is the whole reason the rung needed a metric.
        assert UpstreamArxiv.code == "upstream_arxiv"
        triple.assert_not_recorded("research_jobs_total")


class TestPartialResults:
    """Rung 3 — `docs/reliability.md` §5 calls this its named failure."""

    def _degrade_every_paper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Wire the reader so each paper degrades through the real path.

        The fake `_analyze_paper` calls `_gather_ranked_chunks` itself
        rather than recording a fallback directly, because the tally
        and the counter both fire inside the fan-out's worker threads
        and a fake that skipped the real stack would not exercise that
        boundary — which is the one thing about this site that is not
        obvious.
        """
        monkeypatch.setattr(reader_module, "settings", Settings())
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "")

        def _fake_analyze(
            paper: PaperMetadata,
            _query: str,
            subquestions: list[str],
            _preferred: list[str] | None = None,
        ) -> tuple[dict[str, Any], list[Any], dict[str, Any]]:
            reader_module._gather_ranked_chunks(paper, subquestions)
            return (
                {
                    "paper_id": paper["id"],
                    "title": paper["title"],
                    "key_findings": [],
                    "methodology": "",
                    "results_summary": "",
                    "limitations": "",
                    "relevance": 0.0,
                },
                [],
                {
                    "analysis_complete": True,
                    "missing_context": "",
                    "request_more_sections": [],
                },
            )

        monkeypatch.setattr(reader_module, "_analyze_paper", _fake_analyze)

    def test_every_abstract_only_paper_is_counted_from_the_worker_thread(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three papers read from abstracts; three on the counter.

        Counted per paper, at the same granularity `paper_cache`
        already counts at, and *not* at the run-level WARNING: that
        WARNING fires only past `ABSTRACT_ONLY_WARN_THRESHOLD`, so a
        run where one paper of three degraded would have moved nothing
        at all. The rung has to see the quiet case; the WARNING exists
        to reach an operator who filters at that level, which is a
        different question.
        """
        self._degrade_every_paper(monkeypatch)
        papers = [_paper(f"2311.0900{i}") for i in range(3)]

        update = reader_module.reader_agent(
            _reader_state(papers)  # type: ignore[arg-type]
        )

        # The run produced a full set of analyses and will report
        # success — read from 200-word abstracts.
        assert len(update["paper_analyses"]) == 3
        # The run-level WARNING is the leg asserted here because it
        # fires exactly once; the per-paper INFO line fires three times
        # and is checked below, where three is the point.
        warned = triple.assert_triple(
            code=None,
            event="reader_degraded_to_abstract_only",
            instrument=_INSTRUMENT,
            attributes={
                "rung": DEGRADATION_RUNG_PARTIAL_RESULTS,
                "component": "reader",
            },
            value=3,
        )
        assert warned.n_abstract_only == 3  # type: ignore[attr-defined]
        assert warned.n_papers == 3  # type: ignore[attr-defined]
        # §5's other marker for this row still fires, unchanged.
        assert len(triple.records("reader_paper_abstract_only")) == 3

    def test_one_unlucky_paper_is_counted_even_though_nothing_warns(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case a run-level counter would have missed entirely.

        One dead PDF link is normal operation, not an incident, so no
        WARNING fires — and the analysis for that paper is still made
        from an abstract. Below the alerting threshold is exactly where
        an SLI is supposed to be doing its work.
        """
        self._degrade_every_paper(monkeypatch)

        reader_module.reader_agent(
            _reader_state([_paper("2311.09009")])  # type: ignore[arg-type]
        )

        assert not triple.records("reader_degraded_to_abstract_only")
        record = triple.assert_triple(
            code=None,
            event="reader_paper_abstract_only",
            instrument=_INSTRUMENT,
            attributes={
                "rung": DEGRADATION_RUNG_PARTIAL_RESULTS,
                "component": "reader",
            },
        )
        assert record.reason == "no_text"  # type: ignore[attr-defined]


def _reader_state(papers: list[PaperMetadata]) -> dict[str, Any]:
    return {"papers": papers, "query": "What is RAG?", "sub_questions": ["a"]}


class TestModelFallback:
    """Rung 5 — a node's output was unusable and a default stood in."""

    def test_the_planner_substituting_the_raw_query_is_counted(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every node downstream then works from a plan nobody made."""
        monkeypatch.setattr(planner_module, "settings", Settings())

        def _unparseable(**_kw: Any) -> dict[str, Any]:
            raise json.JSONDecodeError("Unterminated string", '{"sub', 5)

        monkeypatch.setattr(planner_module, "call_llm_json", _unparseable)

        update = planner_module.planner_agent(
            {"query": "What is RAG?"}  # type: ignore[typeddict-item]
        )

        assert update["sub_questions"] == ["What is RAG?"]
        assert update["search_queries"] == ["What is RAG?"]
        triple.assert_triple(
            code=None,
            event="planner_plan_fallback_to_query",
            instrument=_INSTRUMENT,
            attributes={
                "rung": DEGRADATION_RUNG_MODEL_FALLBACK,
                "component": "planner",
            },
        )
        # The parse failure has its own line and keeps it; §5's rule is
        # about distinct markers, and folding them would lose the why.
        assert triple.records("planner_response_unparseable")

    def test_the_supervisors_default_action_is_counted_once_per_substitution(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three log events, one substitution, one count.

        `_fall_back` is where the count lives because all three of the
        supervisor's fallback branches converge on it. Counting at each
        branch instead would be three numbers that can disagree about
        one event, which is the reason ADR 0081 gives for declining to
        double-instrument anything.
        """
        monkeypatch.setattr(
            supervisor_module, "settings", Settings(enable_supervisor=True)
        )

        def _garbage(**_kw: Any) -> dict[str, Any]:
            raise ValueError("the judge answered with prose")

        monkeypatch.setattr(supervisor_module, "call_llm_json", _garbage)

        update = supervisor_module.supervisor_agent(_routing_state())

        # It did get a route — refusing to route strands a run the
        # fixed pipeline could have finished.
        assert update["next_action"] == "plan"
        triple.assert_triple(
            code=None,
            event="supervisor_llm_failed_fallback_to_default",
            instrument=_INSTRUMENT,
            attributes={
                "rung": DEGRADATION_RUNG_MODEL_FALLBACK,
                "component": "supervisor",
            },
        )

    def test_an_invalid_action_takes_the_same_rung_under_its_own_event(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second branch into `_fall_back`, proving the site is shared.

        A judge that answered cleanly with an action outside the enum
        is a different diagnosis from a judge that raised, and keeps a
        different log event — but it is the same rung, taken once.
        """
        monkeypatch.setattr(
            supervisor_module, "settings", Settings(enable_supervisor=True)
        )
        monkeypatch.setattr(
            supervisor_module,
            "call_llm_json",
            lambda **_kw: {"next_action": "teleport", "reason": "why not"},
        )

        update = supervisor_module.supervisor_agent(_routing_state())

        assert update["next_action"] == "plan"
        triple.assert_triple(
            code=None,
            event="supervisor_invalid_action_fallback",
            instrument=_INSTRUMENT,
            attributes={
                "rung": DEGRADATION_RUNG_MODEL_FALLBACK,
                "component": "supervisor",
            },
        )

    def test_the_verifiers_abstention_is_counted_under_the_code_it_writes(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one row here where a code is read off a real surface.

        `verify_node` writes the abstention's reason onto the state, so
        `upstream_model_output` is a value a caller can read rather
        than a claim about an exception. The run continues with a
        verification nobody performed.
        """
        monkeypatch.setattr(verifier_module, "settings", Settings())

        def _unparseable(**_kw: Any) -> dict[str, Any]:
            raise json.JSONDecodeError("Unterminated string", '{"veri', 6)

        monkeypatch.setattr(verifier_module, "call_llm_json", _unparseable)

        update = verifier_module.verify_node(_verifiable_state())

        assert update["verification_verdict"] == "abstain"
        assert update["verification_reason"] == UpstreamModelOutput.code
        triple.assert_triple(
            code=update["verification_reason"],
            event="verifier_llm_failed_fallback",
            instrument=_INSTRUMENT,
            attributes={
                "rung": DEGRADATION_RUNG_MODEL_FALLBACK,
                "component": "verifier",
            },
        )
        # Conservative, and unchanged: an abstention routes to another
        # synthesis rather than letting an unverified draft through.
        assert update["verifier_recommendation"] == "revise_report"

    def test_the_synthesizers_corrective_retry_is_counted_when_it_succeeds(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Counted on the retry, not on the raise.

        Both attempts failing raises `SynthesizerOutputError` and the
        job ends with an honest code that `research_jobs_total` already
        carries. The case with no other witness is the one where the
        retry *worked*: a report shipped, the run reported success, and
        the first attempt's failure left no trace on any instrument.
        """
        calls: list[str] = []

        def _unusable_then_usable(**kwargs: Any) -> dict[str, Any]:
            calls.append(str(kwargs.get("prompt", "")))
            if len(calls) == 1:
                return {"draft_report": "   "}
            return {"draft_report": "A report.", "citations": []}

        monkeypatch.setattr(synth_module, "call_llm_json", _unusable_then_usable)
        monkeypatch.setattr(synth_module, "settings", Settings())

        parsed = synth_module._call_with_one_retry("prompt", "system")

        assert parsed["draft_report"] == "A report."
        assert len(calls) == 2
        assert calls[1] != calls[0], "the retry is a corrective re-prompt"
        record = triple.assert_triple(
            code=None,
            event="synthesizer_retrying_malformed_response",
            instrument=_INSTRUMENT,
            attributes={
                "rung": DEGRADATION_RUNG_MODEL_FALLBACK,
                "component": "synthesizer",
            },
        )
        assert record.attempt == 1  # type: ignore[attr-defined]


def _routing_state() -> ResearchState:
    """A state `_default_next_action` routes to `plan` from."""
    return {  # type: ignore[return-value]
        "query": "q?",
        "sub_questions": [],
        "papers": [],
        "paper_analyses": [],
        "draft_report": "",
        "critique": "",
        "iteration": 0,
        "loop_iterations": 0,
    }


def _verifiable_state() -> ResearchState:
    """A state with a draft and a citation, so the judge is actually called."""
    return {  # type: ignore[return-value]
        "run_id": "cap08",
        "query": "What is X?",
        "sub_questions": ["What is X?"],
        "search_queries": [],
        "papers": [
            {  # type: ignore[list-item]
                "id": "p1",
                "title": "T",
                "authors": ["Jane Smith"],
                "abstract": "Method works well in setting A.",
                "url": "",
                "pdf_url": "",
            }
        ],
        "paper_analyses": [],
        "draft_report": "The method works well [Smith, 2023].",
        "citations": [
            {  # type: ignore[list-item]
                "paper_id": "p1",
                "title": "T",
                "authors": ["Jane Smith"],
                "year": "2023",
                "url": "",
            }
        ],
        "critique": "",
        "quality_score": 0.0,
        "revision_needed": False,
        "revision_target": "",
        "iteration": 0,
        "next_action": "",
        "loop_iterations": 0,
        "stop_reason": "",
        "verified": False,
        "unsupported_claims": [],
        "missing_evidence": [],
        "verifier_recommendation": "",
        "evidence": [],
        "messages": [],
    }


class TestTheHealthyPathIsSilent:
    """The negative half, and the reason the SLI can be believed.

    An instrument that moves on a healthy run is worse than no
    instrument: it is wrong in the direction operators trust. Each of
    these drives the same node as a test above, with the fault removed,
    and asserts the counter recorded *nothing at all* — not "nothing on
    that rung", nothing.
    """

    def test_a_search_that_finds_papers_records_no_rung(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _live_search(monkeypatch)
        monkeypatch.setattr(
            search_module,
            "search_arxiv",
            lambda q, max_results, raise_on_unavailable=False: [_paper()],
        )

        update = search_module.search_agent(_search_state(["rag"]))

        assert update["papers"]
        triple.assert_not_recorded(_INSTRUMENT)

    def test_a_reader_that_reads_full_text_records_no_rung(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(reader_module, "settings", Settings())

        def _full_text_analyze(
            paper: PaperMetadata,
            _query: str,
            _subquestions: list[str],
            _preferred: list[str] | None = None,
        ) -> tuple[dict[str, Any], list[Any], dict[str, Any]]:
            return (
                {
                    "paper_id": paper["id"],
                    "title": paper["title"],
                    "key_findings": ["f"],
                    "methodology": "m",
                    "results_summary": "r",
                    "limitations": "l",
                    "relevance": 1.0,
                },
                [],
                {
                    "analysis_complete": True,
                    "missing_context": "",
                    "request_more_sections": [],
                },
            )

        monkeypatch.setattr(reader_module, "_analyze_paper", _full_text_analyze)

        update = reader_module.reader_agent(
            _reader_state([_paper("2311.09010")])  # type: ignore[arg-type]
        )

        assert len(update["paper_analyses"]) == 1
        assert not triple.records("reader_paper_abstract_only")
        triple.assert_not_recorded(_INSTRUMENT)

    def test_a_planner_that_returns_a_plan_records_no_rung(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(planner_module, "settings", Settings())
        monkeypatch.setattr(
            planner_module,
            "call_llm_json",
            lambda **_kw: {"sub_questions": ["a", "b"], "search_queries": ["x"]},
        )

        update = planner_module.planner_agent(
            {"query": "What is RAG?"}  # type: ignore[typeddict-item]
        )

        assert update["sub_questions"] == ["a", "b"]
        triple.assert_not_recorded(_INSTRUMENT)

    def test_a_judge_that_answers_records_no_rung(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(verifier_module, "settings", Settings())
        monkeypatch.setattr(
            verifier_module,
            "call_llm_json",
            lambda **_kw: {
                "verified": True,
                "unsupported_claims": [],
                "missing_evidence": [],
                "recommended_action": "",
                "reason": "all claims supported",
            },
        )

        update = verifier_module.verify_node(_verifiable_state())

        assert update["verified"] is True
        triple.assert_not_recorded(_INSTRUMENT)

    def test_a_synthesizer_that_answers_first_time_records_no_rung(
        self, triple: TripleObserver, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(synth_module, "settings", Settings())
        monkeypatch.setattr(
            synth_module,
            "call_llm_json",
            lambda **_kw: {"draft_report": "A report.", "citations": []},
        )

        parsed = synth_module._call_with_one_retry("prompt", "system")

        assert parsed["draft_report"] == "A report."
        triple.assert_not_recorded(_INSTRUMENT)
