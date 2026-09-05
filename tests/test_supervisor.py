"""Unit tests for the supervisor agent.

Pure helpers (`_summarize_state`, `_default_next_action`, `_emit`,
`route_after_supervisor`) are tested directly. The full
`supervisor_agent` path is exercised with `call_llm_json` monkeypatched
so no real Claude calls happen. Also tests the budget/iteration
short-circuits that skip the LLM entirely.
"""

from pathlib import Path
from typing import Any

import pytest
from langgraph.graph import END

from src.agents import supervisor as sup
from src.agents.supervisor import (
    ACTION_TO_NODE,
    VALID_ACTIONS,
    _default_next_action,
    _summarize_state,
    route_after_supervisor,
    supervisor_agent,
)
from src.cancellation import JobCancelledError
from src.config import Settings
from src.errors import UpstreamModel
from src.graph.state import ResearchState
from src.observability import clear_context
from src.observability import costs as costs_module
from src.observability.costs import CostBudgetExceeded

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_observability_state() -> None:
    """Ensure `current_costs()` and the request context are clean."""
    yield
    costs_module._current_costs.set(None)
    clear_context()


def _empty_state(**overrides: Any) -> ResearchState:
    """A ResearchState with all fields present so TypedDict access is safe."""
    base: dict[str, Any] = {
        "run_id": "test-run",
        "query": "q?",
        "sub_questions": [],
        "search_queries": [],
        "papers": [],
        "paper_analyses": [],
        "draft_report": "",
        "citations": [],
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
        "tried_search_queries": [],
        "reader_analysis_complete": True,
        "reader_missing_context": "",
        "reader_requested_sections": [],
        "messages": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# _default_next_action — mirrors the fixed pipeline
# ---------------------------------------------------------------------------


class TestDefaultNextAction:
    def test_empty_state_goes_to_plan(self) -> None:
        assert _default_next_action(_empty_state()) == "plan"

    def test_sub_questions_but_no_papers_goes_to_search(self) -> None:
        state = _empty_state(sub_questions=["a", "b"])
        assert _default_next_action(state) == "search"

    def test_papers_but_no_analyses_goes_to_read(self) -> None:
        state = _empty_state(
            sub_questions=["a"], papers=[{"id": "x", "title": "t"}]  # type: ignore[list-item]
        )
        assert _default_next_action(state) == "read"

    def test_analyses_but_no_report_goes_to_synthesize(self) -> None:
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x", "title": "t"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
        )
        assert _default_next_action(state) == "synthesize"

    def test_report_but_no_critique_goes_to_critique(self) -> None:
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x", "title": "t"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
            draft_report="body",
        )
        assert _default_next_action(state) == "critique"

    def test_finished_state_goes_to_stop(self) -> None:
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x", "title": "t"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
            draft_report="body",
            critique="ok",
        )
        assert _default_next_action(state) == "stop"

    def test_critic_revision_routes_to_planner_target(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(max_iterations=3))
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x", "title": "t"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
            draft_report="body",
            critique="rewrite",
            revision_needed=True,
            revision_target="planner",
            iteration=1,
        )
        assert _default_next_action(state) == "plan"

    def test_revision_ignored_when_iteration_cap_hit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(max_iterations=3))
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x", "title": "t"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
            draft_report="body",
            critique="rewrite",
            revision_needed=True,
            revision_target="planner",
            iteration=3,
        )
        # iteration hit the cap; fall through to natural next step ("stop"
        # since everything downstream is populated).
        assert _default_next_action(state) == "stop"


# ---------------------------------------------------------------------------
# _summarize_state — prompt input
# ---------------------------------------------------------------------------


class TestSummarizeState:
    def test_includes_counts_and_query(self) -> None:
        state = _empty_state(
            query="what is X?",
            sub_questions=["a", "b"],
            papers=[{"id": "1"}] * 3,  # type: ignore[list-item]
        )
        summary = _summarize_state(state)
        assert "query: what is X?" in summary
        assert "sub_questions: 2" in summary
        assert "papers: 3" in summary

    def test_no_cost_context_when_no_accumulator(self) -> None:
        assert "$?" in _summarize_state(_empty_state())

    def test_critique_snippet_truncated_to_200_chars(self) -> None:
        state = _empty_state(critique="x" * 500)
        summary = _summarize_state(state)
        # Two hundred x's, no more.
        assert "x" * 200 in summary
        assert "x" * 201 not in summary


# ---------------------------------------------------------------------------
# supervisor_agent — behavior including short-circuits
# ---------------------------------------------------------------------------


class TestSupervisorShortCircuits:
    def test_iteration_cap_stops_without_llm_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = {"n": 0}

        def _no(**_: Any) -> dict[str, Any]:
            called["n"] += 1
            return {}

        monkeypatch.setattr(sup, "call_llm_json", _no)
        monkeypatch.setattr(sup, "settings", Settings(max_loop_iterations=5))

        state = _empty_state(loop_iterations=5)
        result = supervisor_agent(state)

        assert called["n"] == 0
        assert result["next_action"] == "stop"
        assert result["stop_reason"] == "max_iterations_reached"
        assert result["loop_iterations"] == 6

    def test_cost_cap_stops_without_llm_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = {"n": 0}

        def _no(**_: Any) -> dict[str, Any]:
            called["n"] += 1
            return {}

        monkeypatch.setattr(sup, "call_llm_json", _no)
        monkeypatch.setattr(sup, "settings", Settings(max_cost_usd=1.0))

        # Simulate an accumulator that's over budget.
        from src.observability import start_cost_tracking

        costs = start_cost_tracking()
        costs.record("claude-sonnet-4-6", 400_000, 0, 1.5)  # 1.5 USD

        result = supervisor_agent(_empty_state())

        assert called["n"] == 0
        assert result["next_action"] == "stop"
        assert result["stop_reason"] == "budget_reached"


class TestSupervisorLLMPath:
    def _stub_llm(
        self, monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
    ) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        def fake(
            *,
            prompt: str,
            system_prompt: str,
            max_tokens: int,
            model_name: str | None = None,
            cache_system: bool = False,
        ) -> dict[str, Any]:
            captured["prompt"] = prompt
            captured["system_prompt"] = system_prompt
            captured["max_tokens"] = max_tokens
            captured["model_name"] = model_name
            return response

        monkeypatch.setattr(sup, "call_llm_json", fake)
        return captured

    def test_valid_action_returned_verbatim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_llm(
            monkeypatch,
            {"next_action": "search", "reason": "need papers", "stop_reason": ""},
        )
        result = supervisor_agent(_empty_state(sub_questions=["a"]))
        assert result["next_action"] == "search"
        assert result["stop_reason"] == ""
        assert result["loop_iterations"] == 1

    def test_stop_action_records_supervisor_stop_default_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_llm(
            monkeypatch,
            {"next_action": "stop", "reason": "quality reached", "stop_reason": ""},
        )
        result = supervisor_agent(_empty_state(quality_score=0.9))
        assert result["next_action"] == "stop"
        assert result["stop_reason"] == "supervisor_stop"

    def test_stop_reason_ignored_when_not_stopping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_llm(
            monkeypatch,
            {"next_action": "read", "reason": "extract findings", "stop_reason": "budget_reached"},
        )
        result = supervisor_agent(_empty_state(papers=[{"id": "x"}]))  # type: ignore[list-item]
        # Judge included a stop_reason but chose a non-stop action — we drop it.
        assert result["stop_reason"] == ""

    def test_invalid_action_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_llm(
            monkeypatch,
            {"next_action": "hallucinate", "reason": "why not", "stop_reason": ""},
        )
        result = supervisor_agent(_empty_state())  # empty -> default is "plan"
        assert result["next_action"] == "plan"

    def test_missing_action_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_llm(monkeypatch, {"reason": "no action field"})
        assert (
            supervisor_agent(_empty_state())["next_action"] == "plan"
        )

    def test_llm_exception_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The broad `except` is still broad, deliberately.

        WO-B3 narrowed what the handler *reports*, not what it
        tolerates: an exception nobody typed — a `RuntimeError` from a
        missing key, an `AttributeError` from a refactor — still leaves
        the loop with a route, because turning an unanticipated bug into
        a failed run makes nothing more visible and costs the user their
        run. What changed is that the line now says which class it was.
        """
        def _boom(**_: Any) -> dict[str, Any]:
            raise RuntimeError("api down")

        monkeypatch.setattr(sup, "call_llm_json", _boom)
        result = supervisor_agent(_empty_state())
        assert result["next_action"] == "plan"

    def test_prompt_includes_state_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._stub_llm(
            monkeypatch,
            {"next_action": "search", "reason": "", "stop_reason": ""},
        )
        supervisor_agent(_empty_state(query="hallu?", sub_questions=["a"]))
        assert "query: hallu?" in captured["prompt"]
        assert "sub_questions: 1" in captured["prompt"]


# ---------------------------------------------------------------------------
# What the routing call is not allowed to swallow (WO-B3)
#
# The observability half — the code, the event and the metric a provider
# outage moves — is asserted end to end in
# `tests/fault/test_supervisor_routing_faults.py`. What is left here is
# the routing *contract*: which exceptions leave this function, and what
# `stop_reason` a fallback writes.
# ---------------------------------------------------------------------------


def _finished_state() -> ResearchState:
    """A state with every pipeline field populated.

    `_default_next_action` returns `stop` from it, which is the only
    arrangement in which a fallback's `stop_reason` is observable at
    all — every other fallback writes `""`.
    """
    return _empty_state(
        sub_questions=["a"],
        papers=[{"id": "p"}],  # type: ignore[list-item]
        paper_analyses=[{"id": "p"}],  # type: ignore[list-item]
        draft_report="a report",
        critique="a critique",
    )


class TestTheFallbackSaysWhoChoseToStop:
    """`llm_failed` versus `supervisor_stop`.

    The two used to be one word. A run the provider ended, a run whose
    judge answered with garbage, and a run the judge decided was
    finished all wrote `supervisor_stop` — and `stop_reason` is the
    field `src/eval/runner.py` buckets runs by, so an eval campaign run
    during an outage could not be told apart afterwards from a clean
    one. The bucket is the one ADR 0014's module docstring has named
    since the beginning and nothing emitted.
    """

    def _raise(self, monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
        def _boom(**_: Any) -> dict[str, Any]:
            raise exc

        monkeypatch.setattr(sup, "call_llm_json", _boom)

    def test_a_provider_outage_that_stops_is_llm_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._raise(monkeypatch, UpstreamModel(log_detail="provider down"))
        result = supervisor_agent(_finished_state())
        assert result["next_action"] == "stop"
        assert result["stop_reason"] == "llm_failed"

    def test_a_malformed_judge_that_stops_is_llm_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._raise(monkeypatch, ValueError("not json"))
        result = supervisor_agent(_finished_state())
        assert result["stop_reason"] == "llm_failed"

    def test_an_invalid_action_that_stops_is_llm_failed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The judge answered; the answer was not an action.

        Same bucket, and for the same reason: the supervisor did not
        choose to stop, so recording that it did is a lie about the run
        whichever way the answer failed to arrive.
        """

        def fake(**_: Any) -> dict[str, Any]:
            return {"next_action": "hallucinate", "reason": "", "stop_reason": ""}

        monkeypatch.setattr(sup, "call_llm_json", fake)
        result = supervisor_agent(_finished_state())
        assert result["next_action"] == "stop"
        assert result["stop_reason"] == "llm_failed"

    def test_a_judge_that_chose_to_stop_keeps_supervisor_stop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The distinction the new bucket exists to make, from the other side."""

        def fake(**_: Any) -> dict[str, Any]:
            return {"next_action": "stop", "reason": "done", "stop_reason": ""}

        monkeypatch.setattr(sup, "call_llm_json", fake)
        assert supervisor_agent(_finished_state())["stop_reason"] == "supervisor_stop"

    def test_a_fallback_that_does_not_stop_writes_no_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`stop_reason` stays empty when the loop is still running.

        The prompt's own contract — "MUST be an empty string when
        `next_action` != stop" — and it has to hold for the routes the
        supervisor did not choose as much as for the ones it did.
        """
        self._raise(monkeypatch, UpstreamModel(log_detail="provider down"))
        result = supervisor_agent(_empty_state())
        assert result["next_action"] == "plan"
        assert result["stop_reason"] == ""


class TestTheControlSignalsPropagate:
    """Cancellation and the cost ceiling are not routing failures.

    Both are raised by `call_llm` before it reaches the provider —
    `check_cancelled()` first, then `_check_cost_budget()` (ADR 0047,
    ADR 0051) — so both arrived at the old bare `except` and both were
    answered with a route. The runner owns the terminal state for
    either; a router that absorbs one is a router that keeps
    dispatching nodes for a job that is already over.

    The cancellation case is driven end to end through the real
    checkpoint in `tests/fault/test_supervisor_routing_faults.py`. The
    cost case is injected here rather than driven, and the reason is
    worth writing down: `_check_cost_budget` compares the same
    accumulator against `effective_cost_cap(settings.max_cost_usd)`,
    which for a research run is the same number the supervisor's own
    pre-LLM check uses — so today the pre-check always fires first and
    the guard is unreachable from this node. It stops being unreachable
    the moment the effective cap diverges from `max_cost_usd`, which is
    exactly what ADR 0062's session ceiling already does elsewhere. The
    re-raise is what keeps that divergence from silently becoming an
    overspend, so it is asserted at the seam it would arrive through.
    """

    def _raise(self, monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
        def _boom(**_: Any) -> dict[str, Any]:
            raise exc

        monkeypatch.setattr(sup, "call_llm_json", _boom)

    def test_a_cancellation_is_re_raised_not_routed_around(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._raise(monkeypatch, JobCancelledError("j", "job_timeout"))
        with pytest.raises(JobCancelledError):
            supervisor_agent(_empty_state())

    def test_the_cost_ceiling_is_re_raised_not_routed_around(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._raise(monkeypatch, CostBudgetExceeded(spent_usd=2.5, cap_usd=2.0))
        with pytest.raises(CostBudgetExceeded):
            supervisor_agent(_empty_state())

    def test_neither_is_caught_by_the_provider_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ordering, asserted rather than trusted.

        `except (JobCancelledError, CostBudgetExceeded)` sits above both
        other handlers. Moving it below `except UpstreamModel` would
        still pass every test above — neither class is an `UpstreamModel`
        — but moving it below the broad `except Exception` would silently
        restore the swallow, and nothing else here would notice.
        """
        source = (
            Path(sup.__file__).read_text(encoding="utf-8").split("try:")[-1]
        )
        control = source.index("except (JobCancelledError, CostBudgetExceeded)")
        assert control < source.index("except UpstreamModel")
        assert control < source.index("except Exception")


# ---------------------------------------------------------------------------
# route_after_supervisor
# ---------------------------------------------------------------------------


class TestRouteAfterSupervisor:
    @pytest.mark.parametrize(
        "action,expected",
        [
            ("plan", "planner"),
            ("search", "search"),
            ("read", "reader"),
            ("synthesize", "synthesizer"),
            ("critique", "critic"),
        ],
    )
    def test_valid_actions_map_to_nodes(self, action: str, expected: str) -> None:
        state = _empty_state(next_action=action)
        assert route_after_supervisor(state) == expected

    def test_stop_returns_end(self) -> None:
        assert route_after_supervisor(_empty_state(next_action="stop")) == END

    def test_missing_action_returns_end(self) -> None:
        assert route_after_supervisor(_empty_state()) == END

    def test_unknown_action_returns_end(self) -> None:
        state = _empty_state(next_action="dance")
        assert route_after_supervisor(state) == END


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


class TestActionEnumInvariants:
    def test_action_to_node_covers_every_action_except_stop(self) -> None:
        assert set(ACTION_TO_NODE.keys()) == VALID_ACTIONS - {"stop"}

    def test_action_to_node_values_all_distinct(self) -> None:
        values = list(ACTION_TO_NODE.values())
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# Verifier gating — `verify` is only usable when enable_verifier is true.
# ---------------------------------------------------------------------------


class TestVerifierGating:
    def test_available_actions_excludes_verify_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_verifier=False))
        assert "verify" not in sup._available_actions()

    def test_available_actions_includes_verify_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_verifier=True))
        assert "verify" in sup._available_actions()

    def test_verify_rejected_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Judge picks verify but the flag is off — should fall back to default.
        monkeypatch.setattr(sup, "settings", Settings(enable_verifier=False))
        captured: dict[str, Any] = {}

        def fake(
            *,
            prompt: str,
            system_prompt: str,
            max_tokens: int,
            model_name: str | None = None,
            cache_system: bool = False,
        ) -> dict[str, Any]:
            captured["system_prompt"] = system_prompt
            return {"next_action": "verify", "reason": "check draft", "stop_reason": ""}

        monkeypatch.setattr(sup, "call_llm_json", fake)
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
            draft_report="body",
        )
        result = supervisor_agent(state)
        # verify not available -> default fallback for a state with a
        # draft but no critique -> "critique".
        assert result["next_action"] == "critique"
        # Prompt shouldn't advertise `verify` either.
        assert "verify" not in captured["system_prompt"].lower().split()

    def test_verify_accepted_when_flag_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_verifier=True))

        def fake(**_: Any) -> dict[str, Any]:
            return {"next_action": "verify", "reason": "check draft", "stop_reason": ""}

        monkeypatch.setattr(sup, "call_llm_json", fake)
        state = _empty_state(draft_report="body")
        result = supervisor_agent(state)
        assert result["next_action"] == "verify"

    def test_route_verify_reaches_verifier_node_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_verifier=True))
        state = _empty_state(next_action="verify")
        assert route_after_supervisor(state) == "verifier"

    def test_route_verify_falls_to_end_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Defensive path: stale checkpoint carrying verify shouldn't wedge.
        monkeypatch.setattr(sup, "settings", Settings(enable_verifier=False))
        state = _empty_state(next_action="verify")
        assert route_after_supervisor(state) == END

    def test_summary_hides_verifier_fields_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_verifier=False))
        summary = _summarize_state(
            _empty_state(verified=True, verifier_recommendation="revise_report")
        )
        assert "verified:" not in summary
        assert "verifier_recommendation:" not in summary

    def test_summary_includes_verifier_fields_when_flag_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_verifier=True))
        summary = _summarize_state(
            _empty_state(
                verified=False,
                unsupported_claims=["c1", "c2"],
                missing_evidence=["m"],
                verifier_recommendation="search_more",
            )
        )
        assert "verified: False" in summary
        assert "unsupported_claims: 2" in summary
        assert "missing_evidence: 1" in summary
        assert "verifier_recommendation: search_more" in summary


# ---------------------------------------------------------------------------
# Query refiner gating — `refine_query` only usable when flag on.
# ---------------------------------------------------------------------------


class TestQueryRefinerGating:
    def test_available_actions_excludes_refine_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_query_refiner=False))
        assert "refine_query" not in sup._available_actions()

    def test_available_actions_includes_refine_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_query_refiner=True))
        assert "refine_query" in sup._available_actions()

    def test_refine_rejected_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_query_refiner=False))
        captured: dict[str, Any] = {}

        def fake(
            *,
            prompt: str,
            system_prompt: str,
            max_tokens: int,
            model_name: str | None = None,
            cache_system: bool = False,
        ) -> dict[str, Any]:
            captured["system_prompt"] = system_prompt
            return {"next_action": "refine_query", "reason": "gap", "stop_reason": ""}

        monkeypatch.setattr(sup, "call_llm_json", fake)
        state = _empty_state(
            sub_questions=["a"],
            papers=[{"id": "x"}],  # type: ignore[list-item]
            paper_analyses=[{"paper_id": "x"}],  # type: ignore[list-item]
            draft_report="body",
        )
        result = supervisor_agent(state)
        # refine_query not available → default fallback (state has draft
        # but no critique → "critique").
        assert result["next_action"] == "critique"
        # Prompt shouldn't advertise refine_query.
        assert "refine_query" not in captured["system_prompt"]

    def test_refine_accepted_when_flag_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_query_refiner=True))

        def fake(**_: Any) -> dict[str, Any]:
            return {"next_action": "refine_query", "reason": "gap", "stop_reason": ""}

        monkeypatch.setattr(sup, "call_llm_json", fake)
        result = supervisor_agent(_empty_state(papers=[{"id": "x"}]))  # type: ignore[list-item]
        assert result["next_action"] == "refine_query"

    def test_route_refine_reaches_query_refiner_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_query_refiner=True))
        state = _empty_state(next_action="refine_query")
        assert route_after_supervisor(state) == "query_refiner"

    def test_route_refine_falls_to_end_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_query_refiner=False))
        state = _empty_state(next_action="refine_query")
        assert route_after_supervisor(state) == END

    def test_summary_hides_refiner_field_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_query_refiner=False))
        summary = _summarize_state(
            _empty_state(tried_search_queries=["a", "b"])
        )
        assert "tried_search_queries:" not in summary

    def test_summary_includes_refiner_field_when_flag_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_query_refiner=True))
        summary = _summarize_state(
            _empty_state(tried_search_queries=["a", "b", "c"])
        )
        assert "tried_search_queries: 3" in summary


# ---------------------------------------------------------------------------
# Reader recovery surface — supervisor sees flag-gated fields + hint.
# ---------------------------------------------------------------------------


class TestReaderRecoverySurface:
    def test_summary_hides_recovery_fields_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_reader_recovery=False))
        summary = _summarize_state(
            _empty_state(
                reader_analysis_complete=False,
                reader_missing_context="need results section",
                reader_requested_sections=["results"],
            )
        )
        assert "reader_analysis_complete:" not in summary
        assert "reader_requested_sections:" not in summary
        assert "reader_missing_context:" not in summary

    def test_summary_includes_recovery_fields_when_flag_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_reader_recovery=True))
        summary = _summarize_state(
            _empty_state(
                reader_analysis_complete=False,
                reader_missing_context="need results section",
                reader_requested_sections=["results", "limitations"],
            )
        )
        assert "reader_analysis_complete: False" in summary
        assert "reader_requested_sections: results, limitations" in summary
        assert "reader_missing_context: need results section" in summary

    def test_summary_shows_none_placeholder_when_no_recovery_needed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_reader_recovery=True))
        summary = _summarize_state(_empty_state())
        assert "reader_analysis_complete: True" in summary
        assert "reader_requested_sections: (none)" in summary

    def test_prompt_includes_recovery_hint_when_flag_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_reader_recovery=True))
        captured: dict[str, Any] = {}

        def fake(
            *,
            prompt: str,
            system_prompt: str,
            max_tokens: int,
            model_name: str | None = None,
            cache_system: bool = False,
        ) -> dict[str, Any]:
            captured["system_prompt"] = system_prompt
            return {"next_action": "read", "reason": "recover", "stop_reason": ""}

        monkeypatch.setattr(sup, "call_llm_json", fake)
        supervisor_agent(_empty_state(reader_analysis_complete=False))
        assert "reader_analysis_complete is false" in captured["system_prompt"]

    def test_prompt_omits_recovery_hint_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sup, "settings", Settings(enable_reader_recovery=False))
        captured: dict[str, Any] = {}

        def fake(
            *,
            prompt: str,
            system_prompt: str,
            max_tokens: int,
            model_name: str | None = None,
            cache_system: bool = False,
        ) -> dict[str, Any]:
            captured["system_prompt"] = system_prompt
            return {"next_action": "read", "reason": "any", "stop_reason": ""}

        monkeypatch.setattr(sup, "call_llm_json", fake)
        supervisor_agent(_empty_state())
        assert "reader_analysis_complete" not in captured["system_prompt"]
