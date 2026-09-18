"""Every degradation reason reaches the trajectory (ADR 0097).

ADR 0081 put the degradation ladder on a counter and left the *reason* a
log field, deliberately. That was right for a metric and wrong for a
campaign: a campaign record keeps no log, so eight codes existed only as
log lines and `src/campaign/report.py` printed `not detected from
records` for the taxonomy classes whose only evidence they were.

This file is the proof that they no longer do, and it is written the way
the gap was found — from the sites outwards:

1. **Each of the eight sites records.** Driven with the harness's own
   fake client, one test per code, asserting the class, the code and the
   component the site names. The mock matrix cannot stand in for this:
   `use_mock_data` short-circuits ahead of the PDF fetch and returns a
   well-formed plan and a well-formed draft, so **no** degradation fires
   under mock. A 300-episode matrix proves the pipe is connected and the
   goldens did not move; only these tests prove anything goes down it.
2. **The bridge turns an observation into one event**, with the payload
   the contract registered and the `succeeded` status ADR 0081's
   argument requires.
3. **The report counts it**, into the class the payload names.
4. **The vocabularies are closed**, in both directions and against the
   two sets that already existed: `KNOWN_EVENTS` for the codes and
   `report.TAXONOMY` for the classes. A code that is not also a log
   event would mean an operator grepping a log and an analyst reading a
   campaign were naming different things. The reverse direction starts
   from degradation-shaped names in the log registry, so adding a ninth
   log-only code also fails this file until it has a trajectory emitter.
5. **Nothing happens when nobody is listening.** The default is an
   unbound `ContextVar`, which is what keeps a trajectory that fires no
   degradation byte-identical to the one it was before ADR 0097.

Mutation-check: deleting any `record_degradation_reason` call in
`src/agents/` fails the matching site test in class one; changing a
site's `taxonomy_class` to a class the report does not know fails
`test_every_class_a_site_names_is_a_taxonomy_class`; removing
`degradation.recorded` from the event registry fails class two.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from src.agents import planner as planner_module
from src.agents import reader as reader_module
from src.agents import search as search_module
from src.agents import synthesizer as synthesizer_module
from src.campaign.report import DEGRADATION_EVENT, TAXONOMY
from src.config import Settings
from src.contracts.trajectory import EVENT_TYPE_REGISTRY, EventStatus
from src.graph.state import PaperMetadata
from src.observability.degradation_events import (
    DEGRADATION_CODES,
    DEGRADATION_TAXONOMY_CLASSES,
    TAXONOMY_CITATION_PROVENANCE,
    TAXONOMY_PARSING_CHUNKING_RANKING,
    TAXONOMY_PLANNING_DECOMPOSITION,
    TAXONOMY_RETRIEVAL_MISS,
    TAXONOMY_SYNTHESIS_ORGANIZATION,
    DegradationObservation,
    bind_degradation_observer,
    record_degradation_reason,
    reset_degradation_observer,
)
from src.observability.logging import KNOWN_EVENTS

pytestmark = [pytest.mark.unit, pytest.mark.contract]

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"

# ADR 0097's eight log-only sites live in these four research components.
# Combining the component prefix with the degradation language used by ADR
# 0081 avoids treating unrelated API health and learning-session events as
# research degradations, while keeping the set open to a ninth code. This is
# deliberately a classifier over KNOWN_EVENTS rather than another eight-item
# fixture: adding (for example) ``planner_new_fallback`` to the registry must
# turn the reverse-direction assertion red before it has a trajectory site.
_DEGRADATION_LOG_COMPONENTS = frozenset(
    {"planner", "reader", "search", "synthesizer"}
)
_DEGRADATION_NAME_MARKERS = frozenset(
    {
        "abstract_only",
        "budget_exhausted",
        "citations_dropped",
        "degraded",
        "empty_keeping_prior",
        "fallback",
        "unparseable",
    }
)


def _registered_degradation_codes() -> set[str]:
    """Return ADR 0081/0097-shaped degradation names in the log registry."""
    return {
        event
        for event in KNOWN_EVENTS
        if event.partition("_")[0] in _DEGRADATION_LOG_COMPONENTS
        and any(marker in event for marker in _DEGRADATION_NAME_MARKERS)
    }


@pytest.fixture
def observed() -> Any:
    """Collect every degradation recorded inside the test, then unbind.

    A fixture rather than a `with` block at each site, because the
    binding is the thing under test as much as the sites are: a test
    that forgot to reset would leak its observer into the next one and
    the suite would stop proving isolation.
    """
    seen: list[DegradationObservation] = []
    token = bind_degradation_observer(seen.append)
    try:
        yield seen
    finally:
        reset_degradation_observer(token)


def _paper(pdf_url: str = "") -> PaperMetadata:
    return PaperMetadata(
        id="http://arxiv.org/abs/2311.09001",
        title="Paper 1",
        authors=["A"],
        abstract="Abstract 1.",
        url="http://arxiv.org/abs/2311.09001",
        pdf_url=pdf_url,
    )


def _degrading_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire `reader_agent` so every paper degrades through the real path.

    The fake `_analyze_paper` calls `_gather_ranked_chunks` itself
    rather than recording a fallback directly, so the worker-thread
    binding the tally depends on is exercised exactly as it is in a run.
    """
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


def _decode_error() -> json.JSONDecodeError:
    return json.JSONDecodeError("Unterminated string", '{"draft', 7)


def _codes(seen: list[DegradationObservation]) -> list[str]:
    return [observation.code for observation in seen]


def _only(seen: list[DegradationObservation], code: str) -> DegradationObservation:
    matches = [observation for observation in seen if observation.code == code]
    assert matches, f"no degradation recorded for {code}; saw {_codes(seen)}"
    return matches[0]


# ---------------------------------------------------------------------------
# 1. The eight sites
# ---------------------------------------------------------------------------


class TestTheSitesRecord:
    """One test per code in `DEGRADATION_CODES`, driven at its own site."""

    def test_planner_unparseable_response_and_its_fallback_both_record(
        self, monkeypatch: pytest.MonkeyPatch, observed: list[DegradationObservation]
    ) -> None:
        """Two codes from one call, because they are two facts.

        The response was unusable *and* the raw query stood in for a
        plan. Collapsing them would lose the case where a parsed plan is
        merely empty, which degrades without ever being unparseable.
        """
        monkeypatch.setattr(planner_module, "settings", Settings())
        monkeypatch.setattr(
            planner_module,
            "call_llm_json",
            lambda **_kw: (_ for _ in ()).throw(_decode_error()),
        )

        planner_module.planner_agent({"query": "What is RAG?"})  # type: ignore[typeddict-item]

        assert _codes(observed) == [
            "planner_response_unparseable",
            "planner_plan_fallback_to_query",
        ]
        for observation in observed:
            assert observation.taxonomy_class == TAXONOMY_PLANNING_DECOMPOSITION
            assert observation.component == "planner"

    def test_a_well_shaped_plan_records_nothing(
        self, monkeypatch: pytest.MonkeyPatch, observed: list[DegradationObservation]
    ) -> None:
        monkeypatch.setattr(planner_module, "settings", Settings())
        monkeypatch.setattr(
            planner_module,
            "call_llm_json",
            lambda **_kw: {"sub_questions": ["a"], "search_queries": ["b"]},
        )

        planner_module.planner_agent({"query": "What is RAG?"})  # type: ignore[typeddict-item]

        assert observed == []

    def test_a_paper_with_no_pdf_records_the_per_paper_fallback(
        self, monkeypatch: pytest.MonkeyPatch, observed: list[DegradationObservation]
    ) -> None:
        """Driven through `reader_agent`, because the thread is the point.

        This used to call `_gather_ranked_chunks` directly, and it
        passed for a reason that had nothing to do with production: the
        site ran on the test's own thread, where the observer binding is
        visible. In a real run that site executes inside the reader's
        `ThreadPoolExecutor`, whose context starts empty and carries
        four named `ContextVar`s that do not include the degradation
        observer — so every per-paper record was dropped and no test
        could see it. LE-V moved the emission to the node, which runs in
        the caller's context; this test now goes through the fan-out so
        that a move back would fail.
        """
        monkeypatch.setattr(reader_module, "settings", Settings())
        _degrading_reader(monkeypatch)

        reader_module.reader_agent(
            {"papers": [_paper()], "query": "Q?", "sub_questions": ["a"]}  # type: ignore[typeddict-item]
        )

        observation = _only(observed, "reader_paper_abstract_only")
        assert observation.taxonomy_class == TAXONOMY_PARSING_CHUNKING_RANKING
        assert observation.component == "reader"

    def test_crossing_the_abstract_only_threshold_records_the_run_level_fact(
        self, observed: list[DegradationObservation]
    ) -> None:
        reader_module._log_reader_summary(
            n_papers=4,
            n_failed=0,
            n_claims=0,
            fallback_reasons=["no_pdf_url"] * (
                reader_module.ABSTRACT_ONLY_WARN_THRESHOLD + 1
            ),
        )

        observation = _only(observed, "reader_degraded_to_abstract_only")
        assert observation.taxonomy_class == TAXONOMY_PARSING_CHUNKING_RANKING

    def test_below_the_threshold_the_run_level_fact_is_not_recorded(
        self, observed: list[DegradationObservation]
    ) -> None:
        """The WARNING's own threshold, unchanged: this event is the aggregate.

        The per-paper events are the lower bound; a run that degraded one
        paper out of twenty is not a degraded run and must not say so.
        """
        reader_module._log_reader_summary(
            n_papers=4, n_failed=0, n_claims=0, fallback_reasons=["no_pdf_url"]
        )

        assert observed == []

    def test_an_empty_search_round_that_keeps_prior_papers_records(
        self, monkeypatch: pytest.MonkeyPatch, observed: list[DegradationObservation]
    ) -> None:
        monkeypatch.setattr(search_module, "settings", Settings())
        monkeypatch.setattr(
            search_module, "search_arxiv", lambda *_a, **_kw: []
        )

        update = search_module.search_agent(
            {  # type: ignore[typeddict-item]
                "query": "Q?",
                "search_queries": ["q1"],
                "papers": [_paper("http://example.invalid/1.pdf")],
            }
        )

        assert len(update["papers"]) == 1
        observation = _only(observed, "search_empty_keeping_prior_papers")
        assert observation.taxonomy_class == TAXONOMY_RETRIEVAL_MISS
        assert observation.component == "search"

    def test_each_unparseable_synthesizer_attempt_records(
        self, monkeypatch: pytest.MonkeyPatch, observed: list[DegradationObservation]
    ) -> None:
        """Per attempt, not per node: a rescued first attempt still degraded."""
        monkeypatch.setattr(synthesizer_module, "settings", Settings())
        responses: list[Any] = [
            _decode_error(),
            {"draft_report": "## Report", "citations": []},
        ]

        def fake_llm(**_kw: Any) -> dict[str, Any]:
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(synthesizer_module, "call_llm_json", fake_llm)

        synthesizer_module._call_with_one_retry("prompt", "system")

        observation = _only(observed, "synthesizer_response_unparseable")
        assert observation.taxonomy_class == TAXONOMY_SYNTHESIS_ORGANIZATION
        assert observation.component == "synthesizer"

    def test_a_retry_the_clock_refuses_records(
        self, monkeypatch: pytest.MonkeyPatch, observed: list[DegradationObservation]
    ) -> None:
        monkeypatch.setattr(
            synthesizer_module, "settings", Settings(api_job_timeout_sec=60)
        )

        assert synthesizer_module._second_attempt_fits(59.0) is False

        observation = _only(observed, "synthesizer_retry_budget_exhausted")
        assert observation.taxonomy_class == TAXONOMY_SYNTHESIS_ORGANIZATION

    def test_a_retry_that_fits_records_nothing(
        self, monkeypatch: pytest.MonkeyPatch, observed: list[DegradationObservation]
    ) -> None:
        monkeypatch.setattr(
            synthesizer_module, "settings", Settings(api_job_timeout_sec=3_600)
        )

        assert synthesizer_module._second_attempt_fits(0.1) is True
        assert observed == []

    def test_a_dropped_citation_records(
        self, observed: list[DegradationObservation]
    ) -> None:
        kept = synthesizer_module._parse_citations(
            [{"title": "Kept", "paper_id": "p1"}, {"paper_id": "p2"}]
        )

        assert len(kept) == 1
        observation = _only(observed, "synthesizer_citations_dropped")
        assert observation.taxonomy_class == TAXONOMY_CITATION_PROVENANCE
        assert observation.component == "synthesizer"

    def test_every_registered_code_has_a_test_above(self) -> None:
        """The reverse direction, so a ninth code cannot arrive untested."""
        covered = {
            "planner_plan_fallback_to_query",
            "planner_response_unparseable",
            "reader_degraded_to_abstract_only",
            "reader_paper_abstract_only",
            "search_empty_keeping_prior_papers",
            "synthesizer_citations_dropped",
            "synthesizer_response_unparseable",
            "synthesizer_retry_budget_exhausted",
        }
        assert covered == DEGRADATION_CODES


# ---------------------------------------------------------------------------
# 2. Nothing happens when nobody is listening
# ---------------------------------------------------------------------------


class TestTheUnobservedDefault:
    def test_an_unbound_context_records_nothing_and_raises_nothing(self) -> None:
        record_degradation_reason(
            taxonomy_class=TAXONOMY_RETRIEVAL_MISS,
            code="search_empty_keeping_prior_papers",
            component="search",
        )

    def test_a_broken_observer_cannot_reach_the_call_site(self) -> None:
        """ADR 0081's rule: an observability bug is not a job failure.

        The sites are on failure paths whose entire purpose is surviving
        something; a recorder that could raise there would convert the
        rung into the outage it was built to avoid.
        """

        def explode(_observation: DegradationObservation) -> None:
            raise RuntimeError("recorder is broken")

        token = bind_degradation_observer(explode)
        try:
            record_degradation_reason(
                taxonomy_class=TAXONOMY_RETRIEVAL_MISS,
                code="search_empty_keeping_prior_papers",
                component="search",
            )
        finally:
            reset_degradation_observer(token)

    def test_an_unregistered_class_or_code_is_contained_not_passed_through(
        self, observed: list[DegradationObservation]
    ) -> None:
        record_degradation_reason(
            taxonomy_class="invented_class", code="invented_code", component="search"
        )

        assert observed[0].taxonomy_class == "unregistered"
        assert observed[0].code == "unregistered"


# ---------------------------------------------------------------------------
# 3. The vocabularies are closed, against the sets that already existed
# ---------------------------------------------------------------------------


def _literal_kwargs(function_name: str, keyword: str) -> set[str]:
    """Every string literal passed as `keyword=` to `function_name` in `src/`.

    A parse rather than a fixture, the distinction
    `tests/test_degradation_ladder.py` draws and the reason it draws it:
    a fixture only proves the fixture and the constant agree, while a
    parse proves the *call sites* do.

    Named constants are resolved through the module they are defined in,
    so `TAXONOMY_RETRIEVAL_MISS` counts as its value. An argument that
    resolves to neither is a failure rather than a skip — that is the
    shape an unbounded value arrives in.
    """
    from src.observability import degradation_events

    found: set[str] = set()
    unresolved: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            name = target.attr if isinstance(target, ast.Attribute) else getattr(
                target, "id", ""
            )
            if name != function_name:
                continue
            for arg in node.keywords:
                if arg.arg != keyword:
                    continue
                if isinstance(arg.value, ast.Constant) and isinstance(
                    arg.value.value, str
                ):
                    found.add(arg.value.value)
                elif isinstance(arg.value, ast.Name) and hasattr(
                    degradation_events, arg.value.id
                ):
                    found.add(getattr(degradation_events, arg.value.id))
                else:
                    unresolved.append(f"{path}:{node.lineno}")
    assert not unresolved, (
        f"these `{function_name}` call sites name their `{keyword}` in a form this "
        f"test cannot resolve, so nothing checks them: {unresolved}."
    )
    return found


class TestTheVocabulariesAreClosed:
    def test_every_code_a_site_names_is_registered(self) -> None:
        emitted = _literal_kwargs("record_degradation_reason", "code")
        assert emitted <= DEGRADATION_CODES, sorted(emitted - DEGRADATION_CODES)
        assert emitted == DEGRADATION_CODES, (
            "a registered code with no call site is dead vocabulary — a filter "
            f"that will never match: {sorted(DEGRADATION_CODES - emitted)}"
        )

    def test_every_class_a_site_names_is_a_taxonomy_class(self) -> None:
        emitted = _literal_kwargs("record_degradation_reason", "taxonomy_class")
        known = {entry.class_id for entry in TAXONOMY}
        assert emitted <= DEGRADATION_TAXONOMY_CLASSES
        assert known >= DEGRADATION_TAXONOMY_CLASSES, (
            "a class the producer can name that the report cannot is a "
            f"degradation counted into the catch-all: "
            f"{sorted(DEGRADATION_TAXONOMY_CLASSES - known)}"
        )

    def test_every_code_is_also_a_known_log_event(self) -> None:
        """Close log and trajectory vocabularies in both directions.

        The source parse is the authority for trajectory emission sites. The
        semantic scan of ``KNOWN_EVENTS`` is the authority for the log side;
        unlike an eight-code fixture, it notices a ninth log-only degradation.
        """
        emitted = _literal_kwargs("record_degradation_reason", "code")
        registered = _registered_degradation_codes()
        assert emitted <= KNOWN_EVENTS, sorted(emitted - KNOWN_EVENTS)
        assert registered <= emitted, (
            "degradation-shaped log codes without a trajectory emitter: "
            f"{sorted(registered - emitted)}"
        )

    def test_the_registered_event_is_a_success(self) -> None:
        """ADR 0081's finding, asserted on the contract that carries it.

        A degraded run succeeds. If this event were `failed` the campaign
        report would count a successful run's abstract-only fallback
        among its failures, and `run.failed`-shaped events would appear
        on runs that never failed.
        """
        definition = EVENT_TYPE_REGISTRY[DEGRADATION_EVENT]
        assert definition.allowed_statuses == (EventStatus.SUCCEEDED,)
        assert definition.required_payload_fields == (
            "degradation_id",
            "taxonomy_class",
            "error_code",
            "component",
        )
        # Not `error_class` / `failure_class`: the contract requires
        # those two field names to hold an `AppError` code, and a
        # degradation code is a log-event name.
        assert "error_class" not in definition.required_payload_fields


# ---------------------------------------------------------------------------
# 4. The report counts what the trajectory carries
# ---------------------------------------------------------------------------


class _RecordStub:
    """The four attributes `_taxonomy_rows` reads off an episode record.

    A stand-in rather than a real `EpisodeRecord`, because the thing
    under test is one branch of the counter and building a campaign to
    reach it would make the failure message describe a campaign.
    `tests/test_campaign_execution.py` owns the end-to-end direction.
    """

    reason = None
    ledger_status = None
    scores: dict[str, Any] = {}
    run_id = "run_01k000000000000000000000"


def _events_holding(*payloads: dict[str, Any]) -> Any:
    from src.campaign.report import _EpisodeEvents

    rows = tuple(
        (DEGRADATION_EVENT, "succeeded", (), payload) for payload in payloads
    )
    return {
        _RecordStub.run_id: _EpisodeEvents(
            run_id=_RecordStub.run_id, count=len(rows), rows=rows
        )
    }


class TestTheReportCounts:
    def test_a_degradation_lands_in_the_class_its_payload_names(self) -> None:
        from src.campaign.report import _taxonomy_rows

        rows = {
            row.class_id: row
            for row in _taxonomy_rows(
                [_RecordStub()],  # type: ignore[list-item]
                _events_holding(
                    {
                        "degradation_id": "deg-001",
                        "taxonomy_class": TAXONOMY_PLANNING_DECOMPOSITION,
                        "error_code": "planner_plan_fallback_to_query",
                        "component": "planner",
                    }
                ),
                judges_ran=False,
            )
        }

        planning = rows["planning_decomposition"]
        assert planning.counted is True
        assert planning.occurrences == 1 and planning.episodes == 1
        assert planning.codes == {"planner_plan_fallback_to_query": 1}

    def test_a_judge_class_with_a_record_signal_counts_without_judges(self) -> None:
        """The change ADR 0097 made to `counted`, and the honesty it owes.

        Retrieval miss is still mostly a rubric's business, so the row
        counts what the records carry and its note says the number is a
        floor rather than the class.
        """
        from src.campaign.report import _taxonomy_rows

        rows = {
            row.class_id: row
            for row in _taxonomy_rows(
                [_RecordStub()],  # type: ignore[list-item]
                _events_holding(
                    {
                        "degradation_id": "deg-001",
                        "taxonomy_class": TAXONOMY_RETRIEVAL_MISS,
                        "error_code": "search_empty_keeping_prior_papers",
                        "component": "search",
                    }
                ),
                judges_ran=False,
            )
        }

        retrieval = rows["retrieval_miss"]
        assert retrieval.counted is True
        assert retrieval.occurrences == 1
        assert "not the whole class" in (retrieval.note or "")

    def test_an_unrecognised_class_is_counted_rather_than_dropped(self) -> None:
        from src.campaign.report import _taxonomy_rows

        rows = {
            row.class_id: row
            for row in _taxonomy_rows(
                [_RecordStub()],  # type: ignore[list-item]
                _events_holding(
                    {
                        "degradation_id": "deg-001",
                        "taxonomy_class": "a_class_from_the_future",
                        "error_code": "some_new_code",
                        "component": "reader",
                    }
                ),
                judges_ran=False,
            )
        }

        assert rows["tool_runtime"].codes == {"some_new_code": 1}
