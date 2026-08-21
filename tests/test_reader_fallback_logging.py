"""Abstract-only degradation is visible in the log stream (ADR 0052).

The reader silently produces two very different kinds of analysis:
one read from a paper's full text, one read from its 200-word
abstract. Both come back looking identical downstream, and a run where
four of five papers degraded scores lower on completeness and
faithfulness for a reason that has nothing to do with the prompts.

Before ADR 0052 the degradation was inferable at best — an HTTP
failure warned from `pdf_parser`, but an empty `pdf_url` produced no
record anywhere, because `parse_pdf("")` returns `""` before reaching
any code that could log. These tests pin the per-paper INFO line, the
run-level summary, and the WARNING that fires once the aggregate stops
looking like one paper's bad luck.

Mutation-checked. Removing the `_tallied` wrapper in `reader_agent`
(the ContextVar binding that has to happen *inside* the worker thread,
since a ThreadPoolExecutor inherits no context) leaves the tally empty
and fails `test_run_summary_counts_every_degraded_paper` and
`test_warning_fires_past_the_threshold`; dropping the `no_pdf_url`
branch fails `test_empty_pdf_url_is_named_not_silent`.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from src.agents import reader as reader_module
from src.config import Settings
from src.graph.state import PaperMetadata

pytestmark = pytest.mark.unit

_READER_LOGGER = "src.agents.reader"


def _mk_paper(paper_id: str = "p1", *, pdf_url: str = "https://arxiv.org/pdf/1") -> PaperMetadata:
    return PaperMetadata(
        id=paper_id,
        title="Some Paper",
        authors=["A"],
        abstract="An abstract.",
        url="https://arxiv.org/abs/1",
        pdf_url=pdf_url,
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


class TestPerPaperFallbackLine:
    """Each `[]` return from `_gather_ranked_chunks` names its stage."""

    def test_empty_pdf_url_is_named_not_silent(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The one path with no trace anywhere before ADR 0052.

        `parse_pdf("")` short-circuits on the empty string, so the
        download layer never saw the call and never logged. A paper
        arriving without a `pdf_url` (Semantic Scholar enrichment with
        no open-access link) was analysed from its abstract with
        nothing in the record to say so.
        """
        called = {"parse_pdf": 0}

        def _boom(_url: str) -> str:
            called["parse_pdf"] += 1
            return ""

        monkeypatch.setattr(reader_module, "parse_pdf", _boom)

        with caplog.at_level(logging.INFO, logger=_READER_LOGGER):
            ranked = reader_module._gather_ranked_chunks(
                _mk_paper(pdf_url=""), ["q"]
            )

        assert ranked == []
        # Short-circuited before the fetch layer — which is exactly why
        # nothing downstream could have logged it.
        assert called["parse_pdf"] == 0
        lines = [
            r
            for r in caplog.records
            if r.message == "reader_paper_abstract_only"
        ]
        assert len(lines) == 1
        assert lines[0].reason == "no_pdf_url"  # type: ignore[attr-defined]
        assert lines[0].paper_id == "p1"  # type: ignore[attr-defined]
        assert lines[0].pdf_url == ""  # type: ignore[attr-defined]
        # INFO, not WARNING: the noisy causes already warn from
        # `pdf_parser`, and the aggregate is where the volume lives.
        assert lines[0].levelno == logging.INFO

    def test_pdf_fetch_producing_no_text_is_named(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "")
        with caplog.at_level(logging.INFO, logger=_READER_LOGGER):
            assert reader_module._gather_ranked_chunks(_mk_paper(), ["q"]) == []
        reasons = [
            r.reason  # type: ignore[attr-defined]
            for r in caplog.records
            if r.message == "reader_paper_abstract_only"
        ]
        assert reasons == ["no_text"]

    def test_unchunkable_text_is_named(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "text")
        monkeypatch.setattr(reader_module, "chunk_paper", lambda _t: [])
        with caplog.at_level(logging.INFO, logger=_READER_LOGGER):
            assert reader_module._gather_ranked_chunks(_mk_paper(), ["q"]) == []
        reasons = [
            r.reason  # type: ignore[attr-defined]
            for r in caplog.records
            if r.message == "reader_paper_abstract_only"
        ]
        assert reasons == ["no_chunks"]

    def test_empty_ranking_is_named(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "text")
        monkeypatch.setattr(
            reader_module,
            "chunk_paper",
            lambda _t: [{"section": "method", "text": "m", "chunk_index": 0}],
        )
        monkeypatch.setattr(
            reader_module,
            "rank_chunks_by_relevance",
            lambda _c, _s, top_k, preferred_sections=None: [],
        )
        with caplog.at_level(logging.INFO, logger=_READER_LOGGER):
            assert reader_module._gather_ranked_chunks(_mk_paper(), ["q"]) == []
        reasons = [
            r.reason  # type: ignore[attr-defined]
            for r in caplog.records
            if r.message == "reader_paper_abstract_only"
        ]
        assert reasons == ["no_ranked_chunks"]

    def test_a_successful_read_records_no_fallback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        chunk = {"section": "method", "text": "m", "chunk_index": 0}
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "text")
        monkeypatch.setattr(reader_module, "chunk_paper", lambda _t: [chunk])
        monkeypatch.setattr(
            reader_module,
            "rank_chunks_by_relevance",
            lambda _c, _s, top_k, preferred_sections=None: [chunk],
        )
        with caplog.at_level(logging.INFO, logger=_READER_LOGGER):
            ranked = reader_module._gather_ranked_chunks(_mk_paper(), ["q"])

        assert ranked == [chunk]
        assert not [
            r
            for r in caplog.records
            if r.message == "reader_paper_abstract_only"
        ]


def _degrading_reader(
    monkeypatch: pytest.MonkeyPatch, *, reason_url: str = ""
) -> None:
    """Wire `reader_agent` so every paper degrades through the real path.

    The fake `_analyze_paper` calls `_gather_ranked_chunks` itself
    rather than recording a fallback directly: the ContextVar binding
    it depends on happens in the worker thread, and a fake that skipped
    the real call stack would not exercise that.
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
            _analysis(paper),
            [],
            {
                "analysis_complete": True,
                "missing_context": "",
                "request_more_sections": [],
            },
        )

    monkeypatch.setattr(reader_module, "_analyze_paper", _fake_analyze)


class TestRunSummary:
    def test_run_summary_counts_every_degraded_paper(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The tally has to survive the fan-out's thread boundary."""
        monkeypatch.setattr(reader_module, "settings", Settings())
        _degrading_reader(monkeypatch)
        papers = [_mk_paper(f"p{i}") for i in range(4)]

        with caplog.at_level(logging.INFO, logger=_READER_LOGGER):
            update = reader_module.reader_agent(
                {"papers": papers, "query": "Q?", "sub_questions": ["a"]}  # type: ignore[arg-type]
            )

        assert len(update["paper_analyses"]) == 4
        completed = [
            r for r in caplog.records if r.message == "reader_completed"
        ]
        assert len(completed) == 1
        assert completed[0].n_papers == 4  # type: ignore[attr-defined]
        assert completed[0].n_abstract_only == 4  # type: ignore[attr-defined]
        assert completed[0].n_failed == 0  # type: ignore[attr-defined]
        assert completed[0].fallback_reasons == {"no_text": 4}  # type: ignore[attr-defined]

    def test_warning_fires_past_the_threshold(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(reader_module, "settings", Settings())
        _degrading_reader(monkeypatch)
        papers = [
            _mk_paper(f"p{i}")
            for i in range(reader_module.ABSTRACT_ONLY_WARN_THRESHOLD + 1)
        ]

        with caplog.at_level(logging.INFO, logger=_READER_LOGGER):
            reader_module.reader_agent(
                {"papers": papers, "query": "Q?", "sub_questions": ["a"]}  # type: ignore[arg-type]
            )

        degraded = [
            r
            for r in caplog.records
            if r.message == "reader_degraded_to_abstract_only"
        ]
        assert len(degraded) == 1
        assert degraded[0].levelno == logging.WARNING
        assert degraded[0].n_abstract_only == len(papers)  # type: ignore[attr-defined]

    def test_one_unlucky_paper_stays_at_info(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One dead PDF link is normal operation, not an incident."""
        monkeypatch.setattr(reader_module, "settings", Settings())
        _degrading_reader(monkeypatch)
        papers = [_mk_paper("p0")]

        with caplog.at_level(logging.INFO, logger=_READER_LOGGER):
            reader_module.reader_agent(
                {"papers": papers, "query": "Q?", "sub_questions": ["a"]}  # type: ignore[arg-type]
            )

        assert not [
            r
            for r in caplog.records
            if r.message == "reader_degraded_to_abstract_only"
        ]
        completed = [
            r for r in caplog.records if r.message == "reader_completed"
        ]
        assert completed[0].n_abstract_only == 1  # type: ignore[attr-defined]

    def test_full_text_run_reports_zero_and_no_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setattr(reader_module, "settings", Settings())

        def _fake_analyze(
            paper: PaperMetadata,
            _query: str,
            _subquestions: list[str],
            _preferred: list[str] | None = None,
        ) -> tuple[dict[str, Any], list[Any], dict[str, Any]]:
            return (
                _analysis(paper),
                [],
                {
                    "analysis_complete": True,
                    "missing_context": "",
                    "request_more_sections": [],
                },
            )

        monkeypatch.setattr(reader_module, "_analyze_paper", _fake_analyze)

        with caplog.at_level(logging.INFO, logger=_READER_LOGGER):
            reader_module.reader_agent(
                {  # type: ignore[arg-type]
                    "papers": [_mk_paper("p0"), _mk_paper("p1")],
                    "query": "Q?",
                    "sub_questions": ["a"],
                }
            )

        completed = [
            r for r in caplog.records if r.message == "reader_completed"
        ]
        assert completed[0].n_abstract_only == 0  # type: ignore[attr-defined]
        assert completed[0].fallback_reasons == {}  # type: ignore[attr-defined]

    def test_tally_does_not_leak_between_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ContextVar is reset in the worker's `finally`.

        A module-global counter would interleave two concurrent API
        jobs' runs into one number; the reset is what keeps the second
        run's summary about the second run.
        """
        monkeypatch.setattr(reader_module, "settings", Settings())
        _degrading_reader(monkeypatch)
        reader_module.reader_agent(
            {"papers": [_mk_paper("p0")], "query": "Q?", "sub_questions": []}  # type: ignore[arg-type]
        )
        assert reader_module._fallback_reasons.get() is None
