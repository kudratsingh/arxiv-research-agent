"""Arm C's trajectories, driven through the compiled graph (ADR 0076).

`tests/test_research_policy.py` proves the policy compiles to a graph
nothing else can produce. What it cannot say is what the graph *does*:
whether a failed verdict actually reaches the repair, whether the
repaired output is verified again before the critic sees it, and whether
the one-repair cap survives a verifier that fails twice. Those are
trajectory claims, so they are asserted the way
`tests/e2e/test_research_workflow.py` asserts the fixed pipeline's — off
`app.stream`, node by node, with every model call canned.

The five sequences below are the whole behavioural contract:

| Verifier says | Nodes after synthesizer |
|---|---|
| fail, missing evidence | verify, repair, search, reader, synthesizer, verify, critic |
| fail, unsupported claim | verify, repair, synthesizer, verify, critic |
| pass | verify, critic |
| abstain (judge unavailable) | verify, critic |
| fail twice | verify, repair, synthesizer, verify, critic — never a second repair |

Zero spend is the tier's autouse assertion (`zero_spend_ledger`), and it
is load-bearing here rather than incidental: the repair path adds a
second synthesis and a second verification, and a repair that reached a
real model would be the most expensive mistake in this work order.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import pytest

from src.graph.state import ResearchState, initial_research_state
from src.graph.workflow import build_workflow

pytestmark = pytest.mark.e2e

#: Modules that bind `src.config.settings` on the path this policy
#: drives. The tier's own `SETTINGS_CONSUMERS` plus the verifier, which
#: no previous e2e test reached: it is only wired into a graph under
#: this policy. Spelled out rather than imported from the conftest for
#: the reason that file gives about resting on pytest's sys.path entry.
POLICY_SETTINGS_CONSUMERS: tuple[str, ...] = (
    "src.agents.assessment",
    "src.agents.critic",
    "src.agents.planner",
    "src.agents.reader",
    "src.agents.search",
    "src.agents.synthesizer",
    "src.agents.tutor",
    "src.agents.verifier",
    "src.api.app",
    "src.api.routes",
    "src.api.runner",
    "src.graph.workflow",
    "src.learning.memory",
)

#: Settings that make a run arm C. The three companion flags are not a
#: preference — `Settings` refuses `fixed_verify_repair` without exactly
#: this combination (ADR 0076), so this dict is also a live check that
#: the policy the tier drives is the one the ADR describes.
ARM_C: dict[str, Any] = {
    "research_policy": "fixed_verify_repair",
    "enable_supervisor": False,
    "enable_evidence_store": True,
    "enable_verifier": False,
    "enable_checkpointing": False,
}

#: Canned verifier judgements. Inline rather than in the tier's shared
#: fixture file for the same reason `tests/test_api_smoke_e2e.py` keeps
#: its own: these are the *shapes* `src/agents/verifier.py` parses, and
#: they are only meaningful beside the assertions that read the verdicts
#: they produce. Every field is one the agent actually reads.
VERIFIER_PASSES: dict[str, Any] = {
    "verified": True,
    "unsupported_claims": [],
    "missing_evidence": [],
    "recommended_action": "",
    "reason": "every cited claim resolves against a listed source",
}

VERIFIER_REPORTS_A_GAP: dict[str, Any] = {
    "verified": False,
    "unsupported_claims": [],
    "missing_evidence": ["quantisation error rates under 4-bit inference"],
    "recommended_action": "search_more",
    "reason": "no cited source covers the second sub-question",
}

VERIFIER_REPORTS_AN_OVERCLAIM: dict[str, Any] = {
    "verified": False,
    "unsupported_claims": ["Retrieval eliminates hallucination entirely."],
    "missing_evidence": [],
    "recommended_action": "revise_report",
    "reason": "the report states more than the cited excerpt supports",
}

#: The nodes every run of this policy passes through before the first
#: verification. Named so the sequences below read as "the pipeline,
#: then what the verdict caused".
LEAD_IN = ("planner", "search", "reader", "synthesizer")

INTERRUPT_KEY = "__interrupt__"


def _drive(app: Any, state: ResearchState) -> tuple[list[str], dict[str, Any]]:
    """Run to completion, recording the node sequence and final state."""
    visited: list[str] = []
    final: dict[str, Any] = {}
    for mode, payload in app.stream(state, stream_mode=["updates", "values"]):
        if mode == "values":
            final = dict(payload)
            continue
        for node in payload:
            if node != INTERRUPT_KEY:
                visited.append(node)
    return visited, final


@pytest.fixture
def verifier_script(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Sequence[dict[str, Any]]], dict[str, int]]:
    """Script the judge: the Nth verification gets the Nth response.

    The last entry repeats once the script runs out, the same rule the
    tier's critic script uses, so a test says only as much as it means
    to. Returns the call counter, because "the verifier ran twice" is
    itself an assertion in three of the tests below — a graph that
    skipped re-verification would otherwise pass on the node sequence
    alone if it happened to route correctly for the wrong reason.
    """

    def _install(script: Sequence[dict[str, Any]]) -> dict[str, int]:
        calls = {"count": 0}
        responses = list(script)

        def _call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            index = min(calls["count"], len(responses) - 1)
            calls["count"] += 1
            return dict(responses[index])

        monkeypatch.setattr("src.agents.verifier.call_llm_json", _call)
        return calls

    return _install


@pytest.fixture
def record_synthesizer_prompts(
    monkeypatch: pytest.MonkeyPatch, e2e_fixtures: Callable[[str], dict[str, Any]]
) -> Callable[[], list[str]]:
    """Record every user prompt the synthesizer is called with.

    A factory rather than a plain fixture because it has to be installed
    *after* `research_llm_surface`, which the test calls in its body:
    this replaces that fixture's synthesizer patch with a recording one
    returning the same canned response. The repair instruction is a
    prompt-level change, so the prompt is the only place it can be
    observed.
    """
    responses = e2e_fixtures("research_llm_responses")

    def _install() -> list[str]:
        seen: list[str] = []

        def _call(*_args: Any, **kwargs: Any) -> dict[str, Any]:
            seen.append(str(kwargs.get("prompt", "")))
            return dict(responses["synthesizer"])

        monkeypatch.setattr("src.agents.synthesizer.call_llm_json", _call)
        return seen

    return _install


class TestTheVerifyAndRepairTrajectory:
    def test_a_reported_gap_is_retrieved_read_synthesised_and_verified_again(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """The retrieval repair, end to end.

        Eleven nodes for one query. That cost is the arm's hypothesis
        (H2): a second retrieval round targeted at a *named* gap is
        worth three extra nodes. The test's job is to prove the run
        actually spends them on the gap — the repair rewrote the search
        queries, and search ran again with them — rather than looping the
        synthesizer and calling it a repair.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **ARM_C)
        research_llm_surface()
        calls = verifier_script([VERIFIER_REPORTS_A_GAP, VERIFIER_PASSES])

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("4-bit inference", "e2e-armc-gap")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == [
            *LEAD_IN,
            "verify",
            "repair",
            "search",
            "reader",
            "synthesizer",
            "verify",
            "critic",
        ]
        assert calls["count"] == 2, "the repaired report must be verified again"

        # The repair is in the state, not only in the trajectory.
        assert final["repair_count"] == 1
        assert final["repair_action"] == "retrieve_missing_evidence"
        assert final["verification_verdict"] == "pass"
        assert final["verification_reason"] == "verified"

        # The gap became the search, and the queries it displaced became
        # history — which is what stops a later dedup from re-running
        # them.
        assert final["search_queries"] == [
            "quantisation error rates under 4-bit inference"
        ]
        assert final["tried_search_queries"]

    def test_an_overclaim_is_rewritten_by_the_synthesizer_and_verified_again(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        record_synthesizer_prompts: Callable[[], list[str]],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """The claim repair: one node, and the claim reaches the prompt.

        The node sequence alone would also be produced by a repair that
        re-ran the synthesizer with the identical prompt — which is
        "reflect again", the thing
        `docs/agent-engineering/02-target-architecture.md` §5 says is not
        a recovery policy. So the assertion that matters is the second
        prompt: it names the unsupported claim and asks for it to be
        qualified or removed.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **ARM_C)
        research_llm_surface()
        synthesizer_prompts = record_synthesizer_prompts()
        calls = verifier_script([VERIFIER_REPORTS_AN_OVERCLAIM, VERIFIER_PASSES])

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("hallucination", "e2e-armc-claim")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == [
            *LEAD_IN,
            "verify",
            "repair",
            "synthesizer",
            "verify",
            "critic",
        ]
        assert calls["count"] == 2
        assert final["repair_count"] == 1
        assert final["repair_action"] == "qualify_or_remove_claims"

        assert len(synthesizer_prompts) == 2
        first, repaired = synthesizer_prompts
        assert "Verification repair" not in first
        assert "Verification repair" in repaired
        assert "Retrieval eliminates hallucination entirely." in repaired
        assert "qualified to exactly what a listed source supports" in repaired

    def test_a_passing_verdict_goes_straight_to_the_critic(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """The common path costs one extra node and no repair."""
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **ARM_C)
        research_llm_surface()
        calls = verifier_script([VERIFIER_PASSES])

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("why do LLMs hallucinate?", "e2e-armc-pass")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == [*LEAD_IN, "verify", "critic"]
        assert calls["count"] == 1
        assert final["repair_count"] == 0
        assert final["repair_action"] == ""
        assert final["verification_verdict"] == "pass"
        assert final["draft_report"].strip()
        assert final["iteration"] == 1, "the critic loop is untouched by the policy"

    def test_an_abstention_is_not_a_failure_and_repairs_nothing(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The verdict the whole three-value design exists for.

        A judge that raised leaves `verified=False` on the state — the
        conservative default ADR 0015 chose for the supervisor, kept
        here unchanged. A policy that routed on that boolean would spend
        its repair on a report nobody found fault with. Routing on the
        verdict instead, the run abstains and moves on, and the reason
        code says which failure it was in `src/errors.py`'s own
        vocabulary.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **ARM_C)
        research_llm_surface()

        def _unavailable(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("provider outage")

        monkeypatch.setattr("src.agents.verifier.call_llm_json", _unavailable)

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("abstention", "e2e-armc-abstain")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == [*LEAD_IN, "verify", "critic"]
        assert final["verification_verdict"] == "abstain"
        assert final["verification_reason"] == "upstream_model"
        assert final["verified"] is False, "the ADR-0015 field is unchanged"
        assert final["repair_count"] == 0
        assert final["repair_action"] == ""

    def test_a_second_failure_reaches_the_critic_rather_than_a_second_repair(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """The cap, asserted where it can actually fail.

        The verifier rejects the report every time it is asked. Without
        the `repair_count` check the graph has a cycle here — verify,
        repair, synthesizer, verify — bounded only by LangGraph's
        recursion limit, which would surface as a crash on a real run
        rather than as a bounded, honest, unrepaired report.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **ARM_C)
        research_llm_surface()
        calls = verifier_script([VERIFIER_REPORTS_AN_OVERCLAIM])

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("stubborn", "e2e-armc-cap")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == [
            *LEAD_IN,
            "verify",
            "repair",
            "synthesizer",
            "verify",
            "critic",
        ]
        assert visited.count("repair") == 1
        assert calls["count"] == 2
        assert final["repair_count"] == 1
        assert final["verification_verdict"] == "fail"
        assert final["verification_reason"] == "unsupported_claims"
        # The run still finished, with a report and the failed verdict
        # attached rather than discarded.
        assert final["draft_report"].strip()

    def test_the_message_trajectory_agrees_with_the_node_trajectory(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """Two independent records of the same run, as WO-A15 argues.

        `stream` keys are LangGraph's account of which node produced
        which update; `messages[].name` is what each node stamped on its
        own output. The new nodes have to appear in both, or a trace
        reader and a transcript reader would see different runs.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **ARM_C)
        research_llm_surface()
        verifier_script([VERIFIER_REPORTS_AN_OVERCLAIM, VERIFIER_PASSES])

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("agreement", "e2e-armc-messages")
            )
        finally:
            app._checkpointer_exit_stack.close()

        stamped = [
            str(getattr(message, "name", "") or "") for message in final["messages"]
        ]
        assert stamped == visited
