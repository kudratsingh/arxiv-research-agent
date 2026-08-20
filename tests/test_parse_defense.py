"""Parse-defense tests for LLM-output handling across the agents (ADR 0041).

Each agent gets the degradation its position in the pipeline warrants:

- planner: falls back to the raw query (cheapest stage, honest shallow
  search beats a dead job).
- reader: one malformed response degrades one paper, never the node;
  the node raises `AllPaperAnalysesFailedError` only when every paper
  failed.
- synthesizer: retries once with a corrective nudge, then raises the
  typed `SynthesizerOutputError` (the report is the product — no
  honest fallback exists for it).
- critic: terminal node — never discards the finished report; scores
  coerce safely, unusable output means "approved, score 0.0".

Mutation-checked: these tests fail against the pre-fix code, which
indexed required keys bare (`KeyError` / `JSONDecodeError` /
`ValueError` propagated and killed the job).
"""

import json
from typing import Any

import pytest

from src.agents import critic as critic_module
from src.agents import planner as planner_module
from src.agents import reader as reader_module
from src.agents import synthesizer as synthesizer_module
from src.agents.critic import critic_agent
from src.agents.planner import planner_agent
from src.agents.reader import AllPaperAnalysesFailedError, reader_agent
from src.agents.synthesizer import SynthesizerOutputError, synthesizer_agent
from src.config import Settings
from src.graph.state import PaperMetadata

pytestmark = pytest.mark.unit


def _decode_error() -> json.JSONDecodeError:
    return json.JSONDecodeError("Unterminated string", '{"draft', 7)


def _paper(n: int = 1) -> PaperMetadata:
    return PaperMetadata(
        id=f"http://arxiv.org/abs/2311.0900{n}",
        title=f"Paper {n}",
        authors=["A"],
        abstract=f"Abstract {n}.",
        url=f"http://arxiv.org/abs/2311.0900{n}",
        pdf_url="",
    )


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class TestPlannerParseDefense:
    def _run(self, monkeypatch: pytest.MonkeyPatch, response: Any) -> dict[str, Any]:
        monkeypatch.setattr(planner_module, "settings", Settings())

        def fake_llm(**_kw: Any) -> dict[str, Any]:
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(planner_module, "call_llm_json", fake_llm)
        return planner_agent({"query": "What is RAG?"})  # type: ignore[typeddict-item]

    def test_unparseable_response_falls_back_to_raw_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update = self._run(monkeypatch, _decode_error())
        assert update["sub_questions"] == ["What is RAG?"]
        assert update["search_queries"] == ["What is RAG?"]

    def test_missing_keys_fall_back_to_raw_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update = self._run(monkeypatch, {"unexpected": "shape"})
        assert update["search_queries"] == ["What is RAG?"]

    def test_non_string_entries_filtered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update = self._run(
            monkeypatch,
            {
                "sub_questions": ["real question", 42, "  "],
                "search_queries": ["rag benchmarks", None],
            },
        )
        assert update["sub_questions"] == ["real question"]
        assert update["search_queries"] == ["rag benchmarks"]

    def test_well_formed_response_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update = self._run(
            monkeypatch,
            {"sub_questions": ["q1", "q2"], "search_queries": ["s1"]},
        )
        assert update["sub_questions"] == ["q1", "q2"]
        assert update["search_queries"] == ["s1"]


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


class TestReaderParseDefense:
    def _wire(
        self,
        monkeypatch: pytest.MonkeyPatch,
        responses: dict[str, Any],
    ) -> None:
        """Stub the pipeline; `responses` maps paper title -> LLM response
        (an Exception instance raises)."""
        monkeypatch.setattr(
            reader_module,
            "settings",
            Settings(enable_evidence_store=False, enable_reader_recovery=False),
        )
        monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "")

        def fake_llm(*, prompt: str, **_kw: Any) -> dict[str, Any]:
            for title, response in responses.items():
                if title in prompt:
                    if isinstance(response, Exception):
                        raise response
                    return response
            raise AssertionError(f"no stub matched prompt: {prompt[:120]}")

        monkeypatch.setattr(reader_module, "call_llm_json", fake_llm)

    def _good_response(self) -> dict[str, Any]:
        return {
            "key_findings": ["f"],
            "methodology": "m",
            "results_summary": "r",
            "limitations": "l",
            "relevance": 0.7,
        }

    def test_one_malformed_response_degrades_only_that_paper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wire(
            monkeypatch,
            {"Paper 1": self._good_response(), "Paper 2": _decode_error()},
        )
        state = {"papers": [_paper(1), _paper(2)], "query": "Q?"}
        update = reader_agent(state)  # type: ignore[arg-type]

        analyses = update["paper_analyses"]
        assert len(analyses) == 2
        assert analyses[0]["key_findings"] == ["f"]
        # Paper 2 degraded, not dropped and not fatal.
        assert analyses[1]["key_findings"] == []
        assert analyses[1]["relevance"] == 0.0
        assert "analysis failed" in analyses[1]["limitations"].lower()
        assert "1 paper(s) degraded" in update["messages"][0].content

    def test_missing_required_key_degrades_that_paper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad = self._good_response()
        del bad["key_findings"]
        self._wire(monkeypatch, {"Paper 1": bad, "Paper 2": self._good_response()})
        state = {"papers": [_paper(1), _paper(2)], "query": "Q?"}
        update = reader_agent(state)  # type: ignore[arg-type]
        assert update["paper_analyses"][0]["relevance"] == 0.0
        assert update["paper_analyses"][1]["relevance"] == 0.7

    def test_all_papers_failing_raises_typed_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wire(
            monkeypatch,
            {"Paper 1": _decode_error(), "Paper 2": _decode_error()},
        )
        state = {"papers": [_paper(1), _paper(2)], "query": "Q?"}
        with pytest.raises(AllPaperAnalysesFailedError):
            reader_agent(state)  # type: ignore[arg-type]

    def test_recovery_signal_marks_failed_paper_incomplete(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wire(
            monkeypatch,
            {"Paper 1": self._good_response(), "Paper 2": _decode_error()},
        )
        monkeypatch.setattr(
            reader_module,
            "settings",
            Settings(enable_evidence_store=False, enable_reader_recovery=True),
        )
        state = {"papers": [_paper(1), _paper(2)], "query": "Q?"}
        update = reader_agent(state)  # type: ignore[arg-type]
        assert update["reader_analysis_complete"] is False
        assert "analysis failed" in update["reader_missing_context"]


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------


def _synth_state() -> Any:
    return {
        "query": "Q?",
        "papers": [_paper(1)],
        "paper_analyses": [
            {
                "paper_id": _paper(1)["id"],
                "title": "Paper 1",
                "key_findings": ["f"],
                "methodology": "m",
                "results_summary": "r",
                "limitations": "l",
                "relevance": 0.7,
            }
        ],
    }


class TestSynthesizerParseDefense:
    def _wire(
        self, monkeypatch: pytest.MonkeyPatch, responses: list[Any]
    ) -> list[str]:
        monkeypatch.setattr(synthesizer_module, "settings", Settings())
        prompts: list[str] = []

        def fake_llm(*, prompt: str, **_kw: Any) -> dict[str, Any]:
            prompts.append(prompt)
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(synthesizer_module, "call_llm_json", fake_llm)
        return prompts

    def test_malformed_first_attempt_rescued_by_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        good = {"draft_report": "## Report", "citations": []}
        prompts = self._wire(monkeypatch, [_decode_error(), good])
        update = synthesizer_agent(_synth_state())
        assert update["draft_report"] == "## Report"
        assert len(prompts) == 2
        # The retry carries the corrective nudge; the original didn't.
        assert "not valid JSON" in prompts[1]
        assert "not valid JSON" not in prompts[0]

    def test_empty_draft_report_also_triggers_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        good = {"draft_report": "## Report", "citations": []}
        prompts = self._wire(monkeypatch, [{"draft_report": ""}, good])
        update = synthesizer_agent(_synth_state())
        assert update["draft_report"] == "## Report"
        assert len(prompts) == 2

    def test_both_attempts_malformed_raises_typed_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wire(monkeypatch, [_decode_error(), _decode_error()])
        with pytest.raises(SynthesizerOutputError):
            synthesizer_agent(_synth_state())

    def test_malformed_citation_entries_dropped_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        response = {
            "draft_report": "## Report",
            "citations": [
                {
                    "paper_id": "p1",
                    "title": "Good",
                    "authors": ["A"],
                    "year": "2024",
                    "url": "u",
                },
                "not a dict",
                {"paper_id": "p2"},  # no title
                {"title": "Sparse but usable"},  # missing fields coerce
            ],
        }
        self._wire(monkeypatch, [response])
        update = synthesizer_agent(_synth_state())
        titles = [c["title"] for c in update["citations"]]
        assert titles == ["Good", "Sparse but usable"]
        assert update["citations"][1]["authors"] == []
        assert update["citations"][1]["year"] == ""


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------


class TestCriticParseDefense:
    def _run(self, monkeypatch: pytest.MonkeyPatch, response: Any) -> dict[str, Any]:
        monkeypatch.setattr(critic_module, "settings", Settings())

        def fake_llm(**_kw: Any) -> dict[str, Any]:
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(critic_module, "call_llm_json", fake_llm)
        state = {
            "query": "Q?",
            "paper_analyses": [{"title": "Paper 1"}],
            "draft_report": "## Report",
            "iteration": 0,
        }
        return critic_agent(state)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("raw_score", "expected"),
        [
            (0.85, 0.85),
            ("0.85", 0.85),  # crashed the AIMessage format spec pre-fix
            ("N/A", 0.0),
            (None, 0.0),
        ],
    )
    def test_score_coercion(
        self, monkeypatch: pytest.MonkeyPatch, raw_score: Any, expected: float
    ) -> None:
        update = self._run(
            monkeypatch,
            {
                "average_score": raw_score,
                "critique": "c",
                "revision_needed": False,
                "revision_target": "none",
            },
        )
        assert update["quality_score"] == expected
        assert f"{expected:.2f}" in update["messages"][0].content

    def test_unparseable_response_approves_with_zero_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update = self._run(monkeypatch, _decode_error())
        assert update["revision_needed"] is False
        assert update["quality_score"] == 0.0
        assert "approved" in update["messages"][0].content

    def test_string_true_is_not_revision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Same idiom as the verifier: only a literal JSON true revises.
        update = self._run(
            monkeypatch,
            {
                "average_score": 0.5,
                "critique": "c",
                "revision_needed": "true",
                "revision_target": "planner",
            },
        )
        assert update["revision_needed"] is False

    def test_invalid_revision_target_downgrades_to_approve(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update = self._run(
            monkeypatch,
            {
                "average_score": 0.4,
                "critique": "c",
                "revision_needed": True,
                "revision_target": "reader",  # not routable
            },
        )
        assert update["revision_needed"] is False
        assert update["revision_target"] == ""

    def test_valid_revision_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        update = self._run(
            monkeypatch,
            {
                "average_score": 0.4,
                "critique": "needs work",
                "revision_needed": True,
                "revision_target": "planner",
            },
        )
        assert update["revision_needed"] is True
        assert update["revision_target"] == "planner"
        assert update["critique"] == "needs work"
