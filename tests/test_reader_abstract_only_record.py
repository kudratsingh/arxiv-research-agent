"""The abstract-only reason is a record, not a log line (LE-V, item 5).

ADR 0052 made the reader's abstract-only fallback *visible* — one INFO
line per paper naming the stage that produced nothing, plus a run-level
summary. It did not make it **readable back**, and LE-S found out what
that costs: `episode-state.json` wants the tally and its reasons, the
reasons exist nowhere but the log stream, so the campaign attached a
`logging.Handler` to `src.agents.reader` for the length of an episode.
Its own docstring records the consequence — "correct at concurrency 1",
because a handler is attached to a *logger*, which is process-wide, and
two episodes running at once would each have collected both episodes'
papers.

These tests pin the durable replacement:

1. a run that degrades nothing records nothing, so every golden, the
   scripted tier and the mock matrix are unmoved;
2. at concurrency 1 the sink holds one entry per degraded paper, with
   the stage;
3. at concurrency 2 each run's sink holds *only its own* papers — the
   property the log handler could not have, demonstrated here against
   the same two runs a shared handler would have merged;
4. the tally the campaign writes is derived by the module that knows
   what a reason is, rather than re-derived at the consumer.

The reader's own fan-out is inside each of these: `_record_fallback`
runs in a `ThreadPoolExecutor` worker, and a test that recorded from
the calling thread would prove nothing about the arrangement that
matters (see `test_degradation_trajectory.py`, where exactly that
mistake hid a dropped record for a whole ADR).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from src.agents import reader as reader_module
from src.agents.reader import (
    ABSTRACT_ONLY_REASONS,
    AbstractOnlyFallback,
    abstract_only_recorded,
    abstract_only_summary,
)
from src.config import Settings
from src.graph.state import PaperMetadata

pytestmark = pytest.mark.unit


def _paper(paper_id: str, *, pdf_url: str = "https://arxiv.org/pdf/1") -> PaperMetadata:
    return PaperMetadata(
        id=paper_id,
        title="Some Paper",
        authors=["A Author"],
        abstract="An abstract.",
        url="https://arxiv.org/abs/1",
        pdf_url=pdf_url,
        published=None,
    )


def _analysis(paper: PaperMetadata) -> dict[str, Any]:
    return {
        "paper_id": paper["id"],
        "title": paper["title"],
        "key_findings": [],
        "methodology": "",
        "results_summary": "",
        "limitations": "",
        "relevance": 0.0,
    }


def _signal() -> dict[str, Any]:
    return {
        "analysis_complete": True,
        "missing_context": "",
        "request_more_sections": [],
    }


def _reader_that_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every paper falls through `_gather_ranked_chunks` to its abstract.

    `parse_pdf` returning `""` is the `no_text` stage, and the fake
    analyzer calls the real `_gather_ranked_chunks` so the fallback is
    recorded from the worker thread exactly as it is in a run.
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
        return _analysis(paper), [], _signal()

    monkeypatch.setattr(reader_module, "_analyze_paper", _fake_analyze)


def _reader_that_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """No paper degrades: `_gather_ranked_chunks` is never reached."""
    monkeypatch.setattr(reader_module, "settings", Settings())

    def _fake_analyze(
        paper: PaperMetadata,
        _query: str,
        _subquestions: list[str],
        _preferred: list[str] | None = None,
    ) -> tuple[dict[str, Any], list[Any], dict[str, Any]]:
        return _analysis(paper), [], _signal()

    monkeypatch.setattr(reader_module, "_analyze_paper", _fake_analyze)


def _run(papers: list[PaperMetadata]) -> None:
    reader_module.reader_agent(
        {"papers": papers, "query": "Q?", "sub_questions": ["a"]}  # type: ignore[typeddict-item]
    )


class TestNothingIsBoundByDefault:
    """The property every golden rests on."""

    def test_an_unobserved_run_records_nothing_and_still_degrades(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _reader_that_degrades(monkeypatch)

        _run([_paper("p0")])

        assert reader_module._fallback_sink.get() is None

    def test_a_run_that_degrades_nothing_leaves_an_empty_sink(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _reader_that_reads(monkeypatch)

        with abstract_only_recorded() as fallbacks:
            _run([_paper("p0"), _paper("p1")])

        assert fallbacks == []

    def test_the_binding_is_released_on_the_way_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _reader_that_degrades(monkeypatch)

        with abstract_only_recorded():
            _run([_paper("p0")])

        assert reader_module._fallback_sink.get() is None


class TestConcurrencyOne:
    """One run, one sink — the case LE-S already had, now durable."""

    def test_every_degraded_paper_arrives_with_its_stage(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _reader_that_degrades(monkeypatch)

        with abstract_only_recorded() as fallbacks:
            _run([_paper("p0"), _paper("p1"), _paper("p2")])

        assert fallbacks == [
            AbstractOnlyFallback(paper_id="p0", reason="no_text"),
            AbstractOnlyFallback(paper_id="p1", reason="no_text"),
            AbstractOnlyFallback(paper_id="p2", reason="no_text"),
        ]

    def test_the_stage_distinguishes_a_dead_link_from_a_dead_parse(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole reason this is not read off the ADR 0097 observer.

        That record carries the *code* — `reader_paper_abstract_only` —
        for both of these papers. "The paper arrived with no PDF link"
        and "the PDF fetch produced no text" have different owners and
        different fixes, and a campaign that cannot separate them cannot
        act on either.
        """
        _reader_that_degrades(monkeypatch)

        with abstract_only_recorded() as fallbacks:
            _run([_paper("linkless", pdf_url=""), _paper("unparseable")])

        assert {f.paper_id: f.reason for f in fallbacks} == {
            "linkless": "no_pdf_url",
            "unparseable": "no_text",
        }

    def test_the_order_is_the_corpus_order_not_the_race_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A snapshot built from this is compared byte for byte.

        The tally is appended to from the fan-out's thread pool, so its
        own order is whatever the workers finished in. Here the first
        paper is made the slowest, so completion order is the reverse of
        the corpus order and an unsorted sink would say so.
        """
        monkeypatch.setattr(reader_module, "settings", Settings())
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "")
        delays = {"p0": 0.06, "p1": 0.03, "p2": 0.0}

        def _slow_analyze(
            paper: PaperMetadata,
            _query: str,
            subquestions: list[str],
            _preferred: list[str] | None = None,
        ) -> tuple[dict[str, Any], list[Any], dict[str, Any]]:
            time.sleep(delays[paper["id"]])
            reader_module._gather_ranked_chunks(paper, subquestions)
            return _analysis(paper), [], _signal()

        monkeypatch.setattr(reader_module, "_analyze_paper", _slow_analyze)

        with abstract_only_recorded() as fallbacks:
            _run([_paper("p0"), _paper("p1"), _paper("p2")])

        assert [f.paper_id for f in fallbacks] == ["p0", "p1", "p2"]

    def test_the_sink_is_readable_inside_the_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A campaign writes its snapshot before the run's scope closes."""
        _reader_that_degrades(monkeypatch)

        with abstract_only_recorded() as fallbacks:
            _run([_paper("p0")])
            assert len(fallbacks) == 1

    def test_two_sequential_runs_do_not_pool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _reader_that_degrades(monkeypatch)

        with abstract_only_recorded() as first:
            _run([_paper("p0")])
        with abstract_only_recorded() as second:
            _run([_paper("p1")])

        assert [f.paper_id for f in first] == ["p0"]
        assert [f.paper_id for f in second] == ["p1"]


class TestConcurrencyTwo:
    """The property a `logging.Handler` could not have.

    Two runs, overlapping in one process, each with its own recorder.
    A handler attached to `src.agents.reader` would have been on the
    logger both runs log to, so each collector would have seen six
    papers instead of three. A `ContextVar` is bound per context, and
    two threads are two contexts.
    """

    @staticmethod
    def _episode(
        papers: list[PaperMetadata],
        into: dict[str, list[AbstractOnlyFallback]],
        name: str,
        started: threading.Barrier,
    ) -> None:
        with abstract_only_recorded() as fallbacks:
            # Both runs are inside their own recorder before either
            # reaches the reader, which is the interleaving a shared
            # handler loses on.
            started.wait(timeout=10)
            _run(papers)
            into[name] = list(fallbacks)

    def test_each_runs_sink_holds_only_its_own_papers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _reader_that_degrades(monkeypatch)
        collected: dict[str, list[AbstractOnlyFallback]] = {}
        started = threading.Barrier(2)
        threads = [
            threading.Thread(
                target=self._episode,
                args=(
                    [_paper(f"{name}-{index}") for index in range(3)],
                    collected,
                    name,
                    started,
                ),
            )
            for name in ("alpha", "beta")
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert [f.paper_id for f in collected["alpha"]] == [
            "alpha-0",
            "alpha-1",
            "alpha-2",
        ]
        assert [f.paper_id for f in collected["beta"]] == [
            "beta-0",
            "beta-1",
            "beta-2",
        ]

    def test_an_unobserved_run_beside_an_observed_one_is_not_collected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Half the same property: binding one run must not capture another."""
        _reader_that_degrades(monkeypatch)
        collected: dict[str, list[AbstractOnlyFallback]] = {}
        started = threading.Barrier(2)

        def _unobserved() -> None:
            started.wait(timeout=10)
            _run([_paper("unwatched")])

        watched = threading.Thread(
            target=self._episode,
            args=([_paper("watched")], collected, "watched", started),
        )
        other = threading.Thread(target=_unobserved)
        watched.start()
        other.start()
        watched.join(timeout=30)
        other.join(timeout=30)

        assert [f.paper_id for f in collected["watched"]] == ["watched"]


class TestTheSummaryTheCampaignWrites:
    """`abstract_only_summary` — the shape, derived once, at the source."""

    def test_it_counts_and_groups_and_lists(self) -> None:
        summary = abstract_only_summary(
            [
                AbstractOnlyFallback(paper_id="p0", reason="no_text"),
                AbstractOnlyFallback(paper_id="p1", reason="no_pdf_url"),
                AbstractOnlyFallback(paper_id="p2", reason="no_text"),
            ]
        )

        assert summary == {
            "abstract_only_count": 3,
            "reasons": {"no_pdf_url": 1, "no_text": 2},
            "papers": [
                {"paper_id": "p0", "reason": "no_text"},
                {"paper_id": "p1", "reason": "no_pdf_url"},
                {"paper_id": "p2", "reason": "no_text"},
            ],
        }

    def test_the_reason_breakdown_is_ordered(self) -> None:
        """Two runs of one fixture must produce the same bytes."""
        summary = abstract_only_summary(
            [
                AbstractOnlyFallback(paper_id="p0", reason="no_text"),
                AbstractOnlyFallback(paper_id="p1", reason="no_chunks"),
                AbstractOnlyFallback(paper_id="p2", reason="no_pdf_url"),
            ]
        )

        assert list(summary["reasons"]) == ["no_chunks", "no_pdf_url", "no_text"]

    def test_nothing_degraded_is_a_zero_and_not_an_absence(self) -> None:
        assert abstract_only_summary([]) == {
            "abstract_only_count": 0,
            "reasons": {},
            "papers": [],
        }


class TestTheReasonVocabularyIsClosed:
    """A fifth stage is a change, not a long tail."""

    def test_every_stage_the_reader_can_lose_a_paper_at_is_registered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All four branches of `_gather_ranked_chunks`, driven.

        Closed in both directions: a branch that starts reporting a
        fifth reason fails the subset assertion, and a constant that
        grows an unreachable member fails the equality.
        """
        monkeypatch.setattr(reader_module, "settings", Settings())
        seen: set[str] = set()

        stages: list[tuple[str, PaperMetadata, Any, Any]] = [
            ("no_pdf_url", _paper("a", pdf_url=""), None, None),
            ("no_text", _paper("b"), "", None),
            ("no_chunks", _paper("c"), "text", []),
            ("no_ranked_chunks", _paper("d"), "text", ["chunk"]),
        ]
        for expected, paper, pdf_text, chunks in stages:
            if pdf_text is not None:
                monkeypatch.setattr(reader_module, "parse_pdf", lambda _u, _t=pdf_text: _t)
            if chunks is not None:
                monkeypatch.setattr(reader_module, "chunk_paper", lambda _t, _c=chunks: _c)
            monkeypatch.setattr(
                reader_module, "rank_chunks_by_relevance", lambda *_a, **_kw: []
            )

            token = reader_module._fallbacks.set([])
            try:
                reader_module._gather_ranked_chunks(paper, ["q"])
                tally = reader_module._fallbacks.get() or []
            finally:
                reader_module._fallbacks.reset(token)

            assert [f.reason for f in tally] == [expected]
            seen.add(expected)

        assert seen == ABSTRACT_ONLY_REASONS
