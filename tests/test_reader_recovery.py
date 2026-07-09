"""Unit tests for the reader-recovery path (ADR 0019).

Covers the recovery-signal parser, aggregation across papers, the
reader agent's state emission behind `enable_reader_recovery`, and
that the ranker's `preferred_sections` argument propagates from state
through `_analyze_paper` to `rank_chunks_by_relevance`.
"""

from typing import Any

import pytest

from src.agents import reader as reader_module
from src.agents.reader import (
    _aggregate_recovery,
    _analyze_paper,
    _parse_recovery_signal,
    reader_agent,
)
from src.config import Settings
from src.graph.state import PaperMetadata


def _paper(paper_id: str = "p1", title: str = "Paper P1") -> PaperMetadata:
    return PaperMetadata(  # type: ignore[typeddict-item]
        id=paper_id,
        title=title,
        authors=["Author"],
        abstract="An abstract.",
        url=f"http://example/{paper_id}",
        pdf_url=f"http://example/{paper_id}.pdf",
    )


def _signal(**overrides: Any) -> dict[str, Any]:
    base = {
        "analysis_complete": True,
        "missing_context": "",
        "request_more_sections": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _parse_recovery_signal — fail-open on missing / wrong-typed fields.
# ---------------------------------------------------------------------------


class TestParseRecoverySignal:
    def test_missing_analysis_complete_defaults_to_true(self) -> None:
        signal = _parse_recovery_signal({})
        assert signal["analysis_complete"] is True
        assert signal["missing_context"] == ""
        assert signal["request_more_sections"] == []

    def test_wrong_typed_analysis_complete_treated_as_incomplete(self) -> None:
        signal = _parse_recovery_signal(
            {"analysis_complete": "yes", "missing_context": "x"}
        )
        # anything not literally True or None -> False.
        assert signal["analysis_complete"] is False
        assert signal["missing_context"] == "x"

    def test_true_but_flagged_gap_downgrades_to_false(self) -> None:
        signal = _parse_recovery_signal(
            {
                "analysis_complete": True,
                "missing_context": "need results",
                "request_more_sections": ["results"],
            }
        )
        assert signal["analysis_complete"] is False
        assert signal["missing_context"] == "need results"
        assert signal["request_more_sections"] == ["results"]

    def test_true_wipes_stale_missing_and_sections(self) -> None:
        signal = _parse_recovery_signal(
            {
                "analysis_complete": True,
                "missing_context": "",
                "request_more_sections": [],
            }
        )
        assert signal["analysis_complete"] is True
        assert signal["missing_context"] == ""
        assert signal["request_more_sections"] == []

    def test_non_string_sections_dropped(self) -> None:
        signal = _parse_recovery_signal(
            {
                "analysis_complete": False,
                "request_more_sections": [42, None, "  results  ", "", "limits"],
            }
        )
        assert signal["request_more_sections"] == ["results", "limits"]


# ---------------------------------------------------------------------------
# _aggregate_recovery — AND across papers, deduped section union.
# ---------------------------------------------------------------------------


class TestAggregateRecovery:
    def test_all_complete_returns_true(self) -> None:
        complete, missing, sections = _aggregate_recovery(
            [_paper("p1"), _paper("p2")],
            [_signal(), _signal()],  # type: ignore[list-item]
        )
        assert complete is True
        assert missing == ""
        assert sections == []

    def test_any_incomplete_makes_workflow_incomplete(self) -> None:
        complete, missing, sections = _aggregate_recovery(
            [_paper("p1", "Alpha"), _paper("p2", "Beta")],
            [
                _signal(),  # type: ignore[list-item]
                _signal(
                    analysis_complete=False,
                    missing_context="need results",
                    request_more_sections=["results"],
                ),
            ],
        )
        assert complete is False
        assert "Beta: need results" in missing
        assert "Alpha" not in missing
        assert sections == ["results"]

    def test_deduped_section_union_case_insensitive(self) -> None:
        _, _, sections = _aggregate_recovery(
            [_paper("p1"), _paper("p2"), _paper("p3")],
            [
                _signal(
                    analysis_complete=False,
                    request_more_sections=["Results"],
                ),
                _signal(
                    analysis_complete=False,
                    request_more_sections=["results", "Limitations"],
                ),
                _signal(
                    analysis_complete=False,
                    request_more_sections=["  RESULTS  "],
                ),
            ],
        )
        # Case-insensitive dedup, but original casing (first seen) preserved.
        assert sections == ["Results", "Limitations"]

    def test_missing_context_semicolon_joined(self) -> None:
        _, missing, _ = _aggregate_recovery(
            [_paper("p1", "Alpha"), _paper("p2", "Beta")],
            [
                _signal(
                    analysis_complete=False,
                    missing_context="need A",
                ),
                _signal(
                    analysis_complete=False,
                    missing_context="need B",
                ),
            ],
        )
        assert "Alpha: need A" in missing
        assert "Beta: need B" in missing
        assert "; " in missing


# ---------------------------------------------------------------------------
# _analyze_paper — recovery emission gated by flag, chunk fallback wins.
# ---------------------------------------------------------------------------


def _stub_reader_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    parsed_response: dict[str, Any],
    ranked: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Wire pdf/chunk/rank stubs + call_llm_json; capture ranker kwargs."""
    monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "text")
    monkeypatch.setattr(
        reader_module,
        "chunk_paper",
        lambda _t: [{"section": "method", "text": "m", "chunk_index": 0}],
    )
    default_ranked = [
        {
            "section": "method",
            "text": "method body",
            "chunk_index": 0,
            "relevance_score": 0.9,
        },
    ]
    chunks = ranked if ranked is not None else default_ranked
    captured: dict[str, Any] = {}

    def fake_rank(
        _c: Any,
        _s: Any,
        top_k: int,
        preferred_sections: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        captured["top_k"] = top_k
        captured["preferred_sections"] = preferred_sections
        return chunks

    monkeypatch.setattr(reader_module, "rank_chunks_by_relevance", fake_rank)

    def fake_llm(**kw: Any) -> dict[str, Any]:
        captured["system_prompt"] = kw["system_prompt"]
        captured["max_tokens"] = kw["max_tokens"]
        return parsed_response

    monkeypatch.setattr(reader_module, "call_llm_json", fake_llm)
    return captured


def _base_response(**overrides: Any) -> dict[str, Any]:
    base = {
        "key_findings": ["a"],
        "methodology": "m",
        "results_summary": "r",
        "limitations": "L",
        "relevance": 0.7,
    }
    base.update(overrides)
    return base


class TestAnalyzePaperRecovery:
    def test_flag_off_returns_default_signal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_reader_recovery=False)
        )
        captured = _stub_reader_pipeline(monkeypatch, _base_response())
        _, _, signal = _analyze_paper(_paper(), "Q?", ["a"])
        assert signal["analysis_complete"] is True
        assert signal["request_more_sections"] == []
        # System prompt is not extended with the recovery addendum.
        assert "analysis_complete" not in captured["system_prompt"]

    def test_flag_on_parses_signal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_reader_recovery=True)
        )
        captured = _stub_reader_pipeline(
            monkeypatch,
            _base_response(
                analysis_complete=False,
                missing_context="need results",
                request_more_sections=["results"],
            ),
        )
        _, _, signal = _analyze_paper(_paper(), "Q?", ["a"])
        assert signal["analysis_complete"] is False
        assert signal["missing_context"] == "need results"
        assert signal["request_more_sections"] == ["results"]
        # System prompt was extended with the recovery addendum.
        assert "analysis_complete" in captured["system_prompt"]

    def test_flag_on_forces_incomplete_when_no_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_reader_recovery=True)
        )
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "")
        monkeypatch.setattr(
            reader_module,
            "call_llm_json",
            lambda **_kw: _base_response(
                analysis_complete=True,  # LLM says complete
                missing_context="",
                request_more_sections=[],
            ),
        )
        _, _, signal = _analyze_paper(_paper(), "Q?", ["a"])
        # Reader overrides the LLM: abstract-only means "not complete".
        assert signal["analysis_complete"] is False
        assert signal["missing_context"] == "full text unavailable"
        assert signal["request_more_sections"] == []

    def test_preferred_sections_propagate_to_ranker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_reader_recovery=True)
        )
        captured = _stub_reader_pipeline(monkeypatch, _base_response())
        _analyze_paper(_paper(), "Q?", ["a"], preferred_sections=["results"])
        assert captured["preferred_sections"] == ["results"]


# ---------------------------------------------------------------------------
# reader_agent — state emission behind the flag.
# ---------------------------------------------------------------------------


class TestReaderAgentRecovery:
    def _base_state(self, **overrides: Any) -> dict[str, Any]:
        base = {
            "papers": [_paper()],
            "query": "Q?",
            "sub_questions": ["a"],
            "reader_requested_sections": [],
        }
        base.update(overrides)
        return base

    def test_flag_off_omits_recovery_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_reader_recovery=False)
        )

        def fake_analyze(paper: Any, *_a: Any, **_kw: Any) -> Any:
            analysis = {
                "paper_id": paper["id"],
                "title": paper["title"],
                "key_findings": [],
                "methodology": "",
                "results_summary": "",
                "limitations": "",
                "relevance": 0.0,
            }
            signal = {
                "analysis_complete": True,
                "missing_context": "",
                "request_more_sections": [],
            }
            return analysis, [], signal

        monkeypatch.setattr(reader_module, "_analyze_paper", fake_analyze)
        update = reader_agent(self._base_state())  # type: ignore[arg-type]
        assert "reader_analysis_complete" not in update
        assert "reader_missing_context" not in update
        assert "reader_requested_sections" not in update

    def test_flag_on_aggregates_across_papers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_reader_recovery=True)
        )

        signals = iter(
            [
                {
                    "analysis_complete": True,
                    "missing_context": "",
                    "request_more_sections": [],
                },
                {
                    "analysis_complete": False,
                    "missing_context": "need results",
                    "request_more_sections": ["results"],
                },
            ]
        )

        def fake_analyze(paper: Any, *_a: Any, **_kw: Any) -> Any:
            analysis = {
                "paper_id": paper["id"],
                "title": paper["title"],
                "key_findings": [],
                "methodology": "",
                "results_summary": "",
                "limitations": "",
                "relevance": 0.0,
            }
            return analysis, [], next(signals)

        monkeypatch.setattr(reader_module, "_analyze_paper", fake_analyze)
        state = self._base_state(
            papers=[_paper("p1", "Alpha"), _paper("p2", "Beta")]
        )
        update = reader_agent(state)  # type: ignore[arg-type]
        assert update["reader_analysis_complete"] is False
        assert update["reader_requested_sections"] == ["results"]
        assert "Beta: need results" in update["reader_missing_context"]

    def test_flag_on_message_summary_lists_sections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_reader_recovery=True)
        )

        def fake_analyze(paper: Any, *_a: Any, **_kw: Any) -> Any:
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
                    "analysis_complete": False,
                    "missing_context": "gap",
                    "request_more_sections": ["results", "limits"],
                },
            )

        monkeypatch.setattr(reader_module, "_analyze_paper", fake_analyze)
        update = reader_agent(self._base_state())  # type: ignore[arg-type]
        content = update["messages"][0].content
        assert "Recovery: 2 section(s) requested" in content
        assert "results, limits" in content

    def test_state_requested_sections_flow_into_analyze(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_reader_recovery=True)
        )
        seen: dict[str, Any] = {}

        def fake_analyze(
            paper: Any,
            query: str,
            subquestions: list[str],
            preferred_sections: list[str] | None = None,
        ) -> Any:
            seen["preferred_sections"] = preferred_sections
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

        monkeypatch.setattr(reader_module, "_analyze_paper", fake_analyze)
        state = self._base_state(reader_requested_sections=["results"])
        reader_agent(state)  # type: ignore[arg-type]
        assert seen["preferred_sections"] == ["results"]

    def test_state_requested_sections_ignored_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reader_module, "settings", Settings(enable_reader_recovery=False)
        )
        seen: dict[str, Any] = {}

        def fake_analyze(
            paper: Any,
            query: str,
            subquestions: list[str],
            preferred_sections: list[str] | None = None,
        ) -> Any:
            seen["preferred_sections"] = preferred_sections
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

        monkeypatch.setattr(reader_module, "_analyze_paper", fake_analyze)
        state = self._base_state(reader_requested_sections=["results"])
        reader_agent(state)  # type: ignore[arg-type]
        # Flag off: even if state has requested sections, we don't
        # promote them (fixed pipeline stays byte-identical).
        assert seen["preferred_sections"] is None
