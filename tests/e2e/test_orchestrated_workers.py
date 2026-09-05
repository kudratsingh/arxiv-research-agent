"""The branch tier's trajectories, driven through the compiled graph.

`tests/test_orchestration_policy.py` proves the policy module's four
properties on inputs the graph cannot conveniently produce.
`tests/test_orchestration_controller.py` proves the shape is selectable
and that a flag-off deployment sees none of it. What neither can say is
what a *run* does, so this module says it off `app.stream`, node by
node, with every model call canned — the same way
`tests/e2e/test_verify_repair.py` says it for arm C.

The six sequences below are the behavioural contract (ADR 0086):

| What happens | Nodes |
|---|---|
| three branches, verifier passes | planner, lead, workers, merge, synthesizer, verify, critic |
| verifier reports an overclaim | ... verify, repair, synthesizer, verify, critic |
| verifier reports a gap | ... verify, repair, lead, workers, merge, synthesizer, verify, critic |
| one branch's search fails | unchanged — the run reaches the synthesizer on the survivors |
| every branch fails | the existing `not_found_papers` outcome, not a crash |
| cancelled mid-workers | `JobCancelledError`, and the later branches never start |

Zero spend is the tier's autouse assertion and it is load-bearing here
rather than incidental: this shape multiplies the reader by the branch
count, so a branch that reached a real model would be the most expensive
mistake in this work order.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import pytest

from src.cancellation import CancelToken, JobCancelledError, bind_cancel_token
from src.errors import NoPapersFound
from src.graph.state import ResearchState, initial_research_state
from src.graph.workflow import build_workflow
from src.observability.costs import RunCosts
from src.policies import orchestration as orch

pytestmark = pytest.mark.e2e

#: Modules that bind `src.config.settings` on the path this policy
#: drives. The tier's own list plus the verifier and the branch policy,
#: neither of which any previous e2e module reached. Spelled out rather
#: than imported from the conftest for the reason that file gives about
#: resting on pytest's sys.path entry.
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
    "src.policies.orchestration",
)

#: Settings that make a run the branch tier. The three companion flags
#: are not a preference — `Settings` refuses `orchestrated_workers`
#: without exactly this combination (ADR 0086) — so this dict is also a
#: live check that the policy the tier drives is the one the ADR
#: describes. Three branches, three papers each, so the caps are visible
#: in the assertions rather than inherited from a default that may move.
BRANCH_TIER: dict[str, Any] = {
    "research_policy": "orchestrated_workers",
    "enable_supervisor": False,
    "enable_evidence_store": True,
    "enable_verifier": False,
    "enable_checkpointing": False,
    "orchestration_max_branches": 3,
    "orchestration_max_papers_per_branch": 3,
}

#: A plan with three sub-questions, which the shipped mock planner does
#: not produce (it returns one). Inline rather than in the tier's shared
#: fixture file for the reason `test_verify_repair.py` gives about its
#: verifier judgements: this is the *shape* `src/agents/planner.py`
#: parses, and it is only meaningful beside the branch assertions that
#: read it.
PLANNER_WITH_THREE_QUESTIONS: dict[str, Any] = {
    "sub_questions": [
        "What mechanisms produce hallucination?",
        "Which mitigations have measurable effect?",
        "How is hallucination measured?",
    ],
    "search_queries": [
        "hallucination survey",
        "retrieval augmented generation",
        "hallucination benchmark",
    ],
}

VERIFIER_PASSES: dict[str, Any] = {
    "verified": True,
    "unsupported_claims": [],
    "missing_evidence": [],
    "recommended_action": "",
    "reason": "every cited claim resolves against a listed source",
}

VERIFIER_REPORTS_AN_OVERCLAIM: dict[str, Any] = {
    "verified": False,
    "unsupported_claims": ["Retrieval eliminates hallucination entirely."],
    "missing_evidence": [],
    "recommended_action": "revise_report",
    "reason": "the report states more than the cited excerpt supports",
}

VERIFIER_REPORTS_A_GAP: dict[str, Any] = {
    "verified": False,
    "unsupported_claims": [],
    "missing_evidence": ["quantisation error rates under 4-bit inference"],
    "recommended_action": "search_more",
    "reason": "no cited source covers the third sub-question",
}

#: The nodes every run of this policy passes through before the first
#: verification.
LEAD_IN = ("planner", "lead", "workers", "merge", "synthesizer")

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
def branch_plan(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """Replace the tier's two-question planner with a three-question one.

    Installed *after* `research_llm_surface`, which the test calls in
    its body: this replaces that fixture's planner patch, the same way
    `test_verify_repair.py`'s prompt recorder replaces its synthesizer
    patch.
    """

    def _install() -> None:
        monkeypatch.setattr(
            "src.agents.planner.call_llm_json",
            lambda *_args, **_kwargs: dict(PLANNER_WITH_THREE_QUESTIONS),
        )

    return _install


@pytest.fixture
def verifier_script(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Sequence[dict[str, Any]]], dict[str, int]]:
    """Script the judge: the Nth verification gets the Nth response."""

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
def failing_search(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[str]]:
    """Make named branches' searches fail; record which branches ran.

    A fault injected at the *agent*, not at the policy's executor seam,
    because the claim under test is that a real search failure inside
    one branch does not reach another — and the seam would let the test
    pass with the branches sharing every object they have.
    """
    from src.agents.search import MOCK_PAPERS, NoPapersFoundError

    def _install(*, failing: set[str], papers: int = 2) -> list[str]:
        seen: list[str] = []
        real_papers = list(MOCK_PAPERS)[:papers]

        def _search(state: ResearchState) -> dict[str, Any]:
            seen.append(state["query"])
            if state["query"] in failing:
                raise NoPapersFoundError(
                    f"arXiv returned zero papers for {state['query']!r}"
                )
            return {"papers": real_papers}

        monkeypatch.setattr(orch, "search_agent", _search)
        return seen

    return _install


class TestTheBranchTierTrajectory:
    def test_three_sub_questions_become_three_branches_and_one_briefing(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        branch_plan: Callable[[], None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """The headline run: seven nodes, three branches, no dollars.

        The node sequence is the deliverable. `lead`, `workers` and
        `merge` sit exactly where the fixed pipeline's single
        `search -> reader` leg used to, and everything after `merge` is
        arm C unchanged — which is what lets an evaluation attribute a
        difference to the branching rather than to the verification.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        research_llm_surface()
        branch_plan()
        calls = verifier_script([VERIFIER_PASSES])

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("hallucination", "e2e-branch-pass")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == [*LEAD_IN, "verify", "critic"]
        assert calls["count"] == 1
        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

        branches = final["worker_branches"]
        assert [b["branch_id"] for b in branches] == [
            "branch_w00",
            "branch_w01",
            "branch_w02",
        ]
        assert [b["sub_question"] for b in branches] == (
            PLANNER_WITH_THREE_QUESTIONS["sub_questions"]
        )
        assert all(b["status"] == "succeeded" for b in branches)
        assert all(len(b["paper_ids"]) <= 3 for b in branches), "the paper cap"
        assert all(b["llm_calls"] == 0 for b in branches), "canned, so nothing billed"
        assert final["draft_report"].strip()
        assert final["verification_verdict"] == "pass"

    def test_the_merge_deduplicates_and_keeps_every_branchs_provenance(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        branch_plan: Callable[[], None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """Three branches over one fixture corpus: one paper list, three finders.

        The mock corpus is the same five papers whatever the query, so
        this is the maximal-overlap case — and the one that would expose
        a merge that concatenated instead of unioning.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        research_llm_surface()
        branch_plan()
        verifier_script([VERIFIER_PASSES])

        app = build_workflow(enable_hitl=False)
        try:
            _, final = _drive(
                app, initial_research_state("hallucination", "e2e-branch-merge")
            )
        finally:
            app._checkpointer_exit_stack.close()

        provenance = final["merged_evidence_provenance"]
        assert provenance, "the merge recorded where each paper came from"
        assert len(final["papers"]) == len(provenance)
        assert len({p["id"] for p in final["papers"]}) == len(final["papers"])
        shared = [row for row in provenance if len(row["branch_ids"]) > 1]
        assert shared, "the same corpus reached more than one branch"
        assert all(
            row["sub_questions"] and len(row["sub_questions"]) == len(row["branch_ids"])
            for row in provenance
        )

    def test_the_same_run_twice_merges_to_the_same_evidence(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        branch_plan: Callable[[], None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """Determinism through the whole graph, not only through the merge.

        A candidate comparison rests on this: two runs of one plan that
        produced two evidence orders would make an offline oracle-best
        computation meaningless.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        research_llm_surface()
        branch_plan()
        verifier_script([VERIFIER_PASSES])

        results = []
        for run in ("e2e-branch-det-1", "e2e-branch-det-2"):
            app = build_workflow(enable_hitl=False)
            try:
                _, final = _drive(app, initial_research_state("hallucination", run))
            finally:
                app._checkpointer_exit_stack.close()
            results.append(final)

        first, second = results
        assert first["evidence"] == second["evidence"]
        assert [p["id"] for p in first["papers"]] == [
            p["id"] for p in second["papers"]
        ]
        assert first["merged_evidence_provenance"] == (
            second["merged_evidence_provenance"]
        )

    def test_the_message_trajectory_agrees_with_the_node_trajectory(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        branch_plan: Callable[[], None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """Two independent records of one run, as WO-A15 argues.

        The branch nodes have to appear in both and the *branch's own*
        search and reader must appear in neither — a run that leaked
        three branches' agent messages into the transcript would give a
        trace reader and a transcript reader different runs.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        research_llm_surface()
        branch_plan()
        verifier_script([VERIFIER_PASSES])

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("agreement", "e2e-branch-messages")
            )
        finally:
            app._checkpointer_exit_stack.close()

        stamped = [
            str(getattr(message, "name", "") or "") for message in final["messages"]
        ]
        assert stamped == visited
        assert "search" not in stamped
        assert "reader" not in stamped


class TestTheVerificationStageIsArmCUnchanged:
    def test_an_overclaim_is_rewritten_by_the_synthesizer_and_verified_again(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        branch_plan: Callable[[], None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """The claim repair costs one node here, exactly as in arm C."""
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        research_llm_surface()
        branch_plan()
        calls = verifier_script([VERIFIER_REPORTS_AN_OVERCLAIM, VERIFIER_PASSES])

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("overclaim", "e2e-branch-claim")
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

    def test_a_reported_gap_becomes_a_new_branch_and_keeps_the_old_evidence(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        branch_plan: Callable[[], None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """The retrieval repair, in the shape a branch tier gives it.

        Under arm C the repair rewrites `search_queries` and re-enters
        `search`, which replaces the run's papers. Here it re-enters
        `lead`, which *adds* a branch for the named gap, and the merge
        unions it with what the run already had. That is the difference
        the ADR argues for: a repair that discarded three branches'
        evidence to keep one gap's would be a re-plan wearing a repair's
        name.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        research_llm_surface()
        branch_plan()
        calls = verifier_script([VERIFIER_REPORTS_A_GAP, VERIFIER_PASSES])

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("a gap", "e2e-branch-gap")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == [
            *LEAD_IN,
            "verify",
            "repair",
            "lead",
            "workers",
            "merge",
            "synthesizer",
            "verify",
            "critic",
        ]
        assert calls["count"] == 2
        assert final["repair_count"] == 1
        assert final["repair_action"] == "retrieve_missing_evidence"

        branches = final["worker_branches"]
        assert [b["branch_id"] for b in branches] == [
            "branch_w00",
            "branch_w01",
            "branch_w02",
            "branch_r03",
        ]
        assert branches[-1]["sub_question"] == (
            "quantisation error rates under 4-bit inference"
        )
        assert all(b["status"] == "succeeded" for b in branches)
        # The first pass's retrieval survived: the merge is incremental,
        # so every branch that ran is still named in the provenance the
        # repaired report was written from.
        contributors = {
            branch
            for row in final["merged_evidence_provenance"]
            for branch in row["branch_ids"]
        }
        assert {"branch_w00", "branch_w01", "branch_w02"} <= contributors

    def test_a_second_failure_reaches_the_critic_rather_than_a_second_repair(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        branch_plan: Callable[[], None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
    ) -> None:
        """The one-repair cap, on a graph that can now re-enter the tier.

        Without it the cycle is verify -> repair -> lead -> workers ->
        merge -> synthesizer -> verify, bounded only by LangGraph's
        recursion limit and by the branch caps — which is to say, by
        nothing an operator would recognise as a budget.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        research_llm_surface()
        branch_plan()
        calls = verifier_script([VERIFIER_REPORTS_AN_OVERCLAIM])

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("stubborn", "e2e-branch-cap")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited.count("repair") == 1
        assert visited.count("lead") == 1
        assert calls["count"] == 2
        assert final["repair_count"] == 1
        assert final["draft_report"].strip()


class TestAFaultInOneBranchStaysThere:
    def test_a_failed_search_costs_one_branch_and_not_the_run(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        branch_plan: Callable[[], None],
        verifier_script: Callable[[Sequence[dict[str, Any]]], dict[str, int]],
        failing_search: Callable[..., list[str]],
    ) -> None:
        """One branch dies of a real `NoPapersFoundError`; two survive.

        The node sequence is unchanged, which is the point: a branch
        failure is a smaller evidence base, not a different run.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        research_llm_surface()
        branch_plan()
        verifier_script([VERIFIER_PASSES])
        searched = failing_search(
            failing={"Which mitigations have measurable effect?"}
        )

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("a fault", "e2e-branch-fault")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == [*LEAD_IN, "verify", "critic"]
        assert len(searched) == 3, "the failure did not stop the later branches"

        statuses = [b["status"] for b in final["worker_branches"]]
        assert statuses == ["succeeded", "failed", "succeeded"]
        casualty = final["worker_branches"][1]
        assert casualty["reason"] == "not_found_papers"
        assert casualty["paper_ids"] == []
        assert casualty["evidence_count"] == 0

        # The survivors' retrieval is whole, and the merge names only them.
        assert final["papers"]
        assert final["merged_evidence_provenance"]
        assert all(
            row["branch_ids"] and "branch_w01" not in row["branch_ids"]
            for row in final["merged_evidence_provenance"]
        )
        assert final["draft_report"].strip()

    def test_no_surviving_branch_gives_the_existing_not_found_outcome(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        branch_plan: Callable[[], None],
        failing_search: Callable[..., list[str]],
    ) -> None:
        """Every branch fails: a typed error, not an empty briefing.

        A node that returned an empty evidence table instead would hand
        the synthesizer nothing and let a fluent, sourceless report ship
        — ADR 0041's finding, one tier up.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        research_llm_surface()
        branch_plan()
        failing_search(failing=set(PLANNER_WITH_THREE_QUESTIONS["sub_questions"]))

        app = build_workflow(enable_hitl=False)
        try:
            with pytest.raises(NoPapersFound):
                _drive(app, initial_research_state("nothing", "e2e-branch-empty"))
        finally:
            app._checkpointer_exit_stack.close()

    def test_a_cancelled_job_stops_between_branches(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        branch_plan: Callable[[], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancellation mid-workers is honoured (ADR 0047).

        The reader's own per-paper check cannot do this: it only fires
        once a branch has already been entered, so without the check
        between branches a cancelled three-branch run would pay for two
        more searches and up to six more analyses.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        research_llm_surface()
        branch_plan()

        from src.agents.search import MOCK_PAPERS

        token = CancelToken("e2e-branch-cancel")
        searched: list[str] = []

        def _search(state: ResearchState) -> dict[str, Any]:
            searched.append(state["query"])
            token.cancel("job_timeout")
            return {"papers": list(MOCK_PAPERS)[:1]}

        monkeypatch.setattr(orch, "search_agent", _search)

        app = build_workflow(enable_hitl=False)
        scope = bind_cancel_token(token)
        try:
            with pytest.raises(JobCancelledError):
                _drive(app, initial_research_state("stop", "e2e-branch-cancel"))
        finally:
            from src.cancellation import reset_cancel_token

            reset_cancel_token(scope)
            app._checkpointer_exit_stack.close()

        assert searched == ["What mechanisms produce hallucination?"]


class TestTheProductPathRunsWithoutAHarness:
    def test_mock_mode_alone_drives_the_branch_tier_end_to_end(
        self,
        install_settings: Callable[..., Any],
        monkeypatch: pytest.MonkeyPatch,
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """No canned agents at all: the keyless path reaches the branch tier.

        `research_llm_surface` is deliberately not used — it exists to
        can the agents *and* to turn their own mock branch off, so using
        it would make this a test of the fixture rather than of the
        product (ADR 0080, and `test_mock_mode_keyless.py`'s argument).
        The lead and the merge make no model call by design, so the
        whole shape runs on CAP-07's branches alone.
        """
        install_settings(modules=POLICY_SETTINGS_CONSUMERS, **BRANCH_TIER)
        monkeypatch.setattr(
            "src.agents.search.rank_papers_by_relevance",
            lambda query, papers, top_k: list(papers)[:top_k],
        )

        app = build_workflow(enable_hitl=False)
        try:
            visited, final = _drive(
                app, initial_research_state("why do LLMs hallucinate?", "e2e-branch-mock")
            )
        finally:
            app._checkpointer_exit_stack.close()

        assert visited == [*LEAD_IN, "verify", "critic"]
        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0
        assert final["worker_branches"], "the mock planner's plan became branches"
        assert final["draft_report"].strip()

        # The one place the *evidence* path is exercised end to end.
        # `research_llm_surface` reads abstracts with no chunker, so the
        # canned runs above carry analyses and no claims; CAP-07's mock
        # reader emits claims, which is what the merge and the
        # synthesizer's evidence path actually consume.
        assert final["evidence"], "the merge produced an evidence table"
        assert sum(
            row["claim_count"] for row in final["merged_evidence_provenance"]
        ) == len(final["evidence"])
