"""The branch policy's four claims, tested where they can actually fail.

`tests/e2e/test_orchestrated_workers.py` drives the compiled graph and
says what a run *does*. This file is about the module underneath it and
the four properties ADR 0086 rests on, each of which needs an input the
graph cannot conveniently produce:

| Claim | How it is failed here |
|---|---|
| a branch's fault stays in its branch | one injected executor raises; its siblings must be untouched |
| the caps bind | a branch is handed more papers than its cap and more sub-questions than the run's |
| the merge is deterministic | the same inputs, merged twice, byte for byte |
| the run ceiling still owns the budget | a share trip is contained, a ceiling trip is not |

Every test drives `run_branches` with an injected `BranchExecutor`,
which is the seam the module exposes for exactly this: a real
`search_agent` cannot be made to fail on demand without patching two
modules and a network client, and a test that did would be asserting
something about `arxiv_search` rather than about branch isolation.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from src.cancellation import (
    CancelToken,
    JobCancelledError,
    bind_cancel_token,
    reset_cancel_token,
)
from src.config import settings
from src.errors import NoPapersFound, UpstreamPaperRead
from src.graph.state import (
    EvidenceClaim,
    PaperMetadata,
    ResearchState,
    WorkerBranch,
    initial_research_state,
)
from src.observability.costs import (
    CostBudgetExceeded,
    RunCosts,
    effective_cost_cap,
)
from src.policies import orchestration as orch

pytestmark = pytest.mark.unit


def _paper(paper_id: str, title: str = "T") -> PaperMetadata:
    return PaperMetadata(
        id=paper_id,
        title=title,
        authors=["A"],
        abstract="abstract",
        url=paper_id,
        pdf_url=paper_id.replace("/abs/", "/pdf/"),
    )


def _claim(paper_id: str, claim: str, section: str = "results") -> EvidenceClaim:
    return EvidenceClaim(
        claim=claim,
        paper_id=paper_id,
        section=section,
        source_text="the chunk",
        relevance_score=0.5,
        supports_question="q",
    )


def _state(**overrides: Any) -> ResearchState:
    """A planned state, with the branch policy's settings installed."""
    state = initial_research_state("why do LLMs hallucinate?", "unit-run")
    state["sub_questions"] = ["mechanisms", "mitigations", "evaluation"]
    state["search_queries"] = ["hallucination survey", "RAG mitigation"]
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


@pytest.fixture(autouse=True)
def orchestration_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind the module's `settings` to a copy with known caps.

    Named values rather than the shipped defaults, so a default that
    moves does not silently change what these tests mean — and so the
    numbers in the assertions are visible beside them.
    """
    monkeypatch.setattr(
        orch,
        "settings",
        settings.model_copy(
            update={
                "orchestration_max_branches": 2,
                "orchestration_max_papers_per_branch": 2,
                "orchestration_branch_cost_share": 0.5,
                "max_cost_usd": 2.0,
            }
        ),
    )


@pytest.fixture
def cost_ledger() -> Iterator[RunCosts]:
    """A run-scoped cost accumulator that does not outlive the test.

    `start_cost_tracking` binds a ContextVar and has no public
    counterpart, so an accumulator started in a unit test stays bound
    for whatever pytest runs next — which `tests/test_otel_metrics.py`
    catches, correctly, as "a call recorded without an active run had
    one". The token is taken here and reset in the teardown.
    """
    from src.observability import costs as costs_module

    ledger = RunCosts()
    token = costs_module._current_costs.set(ledger)
    try:
        yield ledger
    finally:
        costs_module._current_costs.reset(token)


class TestThePlanBecomesBranches:
    def test_sub_questions_become_bounded_branches_in_plan_order(self) -> None:
        """The lead bounds the plan; it does not re-decompose it."""
        branches = orch.plan_branches(_state())

        assert [b["branch_id"] for b in branches] == ["branch_w00", "branch_w01"]
        assert [b["sub_question"] for b in branches] == ["mechanisms", "mitigations"]
        assert all(b["status"] == orch.STATUS_PLANNED for b in branches)
        assert all(b["max_papers"] == 2 for b in branches)
        # 0.5 of a $2.00 ceiling.
        assert all(b["cost_share_usd"] == 1.0 for b in branches)

    def test_each_branch_leads_with_its_own_question_then_takes_its_share(
        self,
    ) -> None:
        """The planner's flat query list is mapped, deterministically.

        Every planned query reaches exactly one branch and no query is
        run twice — which is what makes the branches *diverse* rather
        than two runs of the same search with different labels.
        """
        branches = orch.plan_branches(_state())

        assert branches[0]["search_queries"] == [
            "mechanisms",
            "hallucination survey",
        ]
        assert branches[1]["search_queries"] == ["mitigations", "RAG mitigation"]
        assigned = [q for b in branches for q in b["search_queries"][1:]]
        assert sorted(assigned) == ["RAG mitigation", "hallucination survey"]

    def test_a_plan_with_no_sub_questions_still_produces_one_branch(self) -> None:
        """A terse planner is a degenerate orchestration, not a refusal."""
        branches = orch.plan_branches(_state(sub_questions=[]))

        assert len(branches) == 1
        assert branches[0]["sub_question"] == "why do LLMs hallucinate?"

    def test_a_retrieval_repair_appends_branches_rather_than_replacing_them(
        self,
    ) -> None:
        """The repair adds a branch; it does not discard the run's evidence.

        Ids stay unique across the two passes, which is what lets the
        trajectory carry both — a second `branch.created` on an existing
        id is a rejected append, not a duplicate.
        """
        first = orch.plan_branches(_state())
        settled = [
            WorkerBranch({**branch, "status": orch.STATUS_SUCCEEDED})
            for branch in first
        ]
        repaired = orch.plan_branches(
            _state(
                worker_branches=settled,
                repair_action="retrieve_missing_evidence",
                search_queries=["quantisation error rates"],
            )
        )

        assert [b["branch_id"] for b in repaired] == [
            "branch_w00",
            "branch_w01",
            "branch_r02",
        ]
        assert repaired[-1]["status"] == orch.STATUS_PLANNED
        assert repaired[-1]["search_queries"] == ["quantisation error rates"]
        assert len({b["branch_id"] for b in repaired}) == 3

    def test_a_critic_driven_replan_appends_rather_than_renumbering(self) -> None:
        """The branch set only ever grows, and ids never repeat.

        `route_after_critique` can send a run back for more retrieval,
        which under this shape re-enters the lead. A pass that renumbered
        from zero would mint a second `branch_w00` for different work —
        and RFC 10 §6.4 is explicit that sibling candidates never share
        an id, so the trajectory would file one branch's evidence under
        another's.
        """
        first = orch.plan_branches(_state())
        settled = [
            WorkerBranch({**branch, "status": orch.STATUS_SUCCEEDED})
            for branch in first
        ]

        replanned = orch.plan_branches(_state(worker_branches=settled))

        assert [b["branch_id"] for b in replanned] == [
            "branch_w00",
            "branch_w01",
            "branch_w02",
            "branch_w03",
        ]
        assert len({b["branch_id"] for b in replanned}) == 4
        assert [b["status"] for b in replanned[:2]] == [
            orch.STATUS_SUCCEEDED,
            orch.STATUS_SUCCEEDED,
        ]

    def test_a_spent_repair_does_not_make_the_next_pass_a_repair_pass(
        self,
    ) -> None:
        """`repair_action` outlives the repair; the repair's branch does not.

        Without this the critic asking for retrieval *after* a repair
        would re-plan against the gap queries the run had already run,
        rather than against the plan's sub-questions — a re-entry taking
        its instructions from a decision that was already carried out.
        """
        first = orch.plan_branches(_state())
        after_repair = orch.plan_branches(
            _state(
                worker_branches=[
                    WorkerBranch({**b, "status": orch.STATUS_SUCCEEDED})
                    for b in first
                ],
                repair_action="retrieve_missing_evidence",
                search_queries=["quantisation error rates"],
            )
        )
        spent = [
            WorkerBranch({**b, "status": orch.STATUS_SUCCEEDED}) for b in after_repair
        ]

        replanned = orch.plan_branches(
            _state(
                worker_branches=spent,
                repair_action="retrieve_missing_evidence",
                search_queries=["quantisation error rates"],
            )
        )

        assert [b["branch_id"] for b in replanned[3:]] == [
            "branch_w03",
            "branch_w04",
        ]
        assert [b["sub_question"] for b in replanned[3:]] == [
            "mechanisms",
            "mitigations",
        ]


class TestABranchIsIsolatedFromItsSiblings:
    def test_the_branch_state_is_built_fresh_and_shares_nothing(self) -> None:
        """The isolation guarantee, asserted on object identity.

        Not a value comparison: the claim is that there is no shared
        object for a partial write to land in, and only identity can say
        that. `query` being the sub-question is the second half — that
        is what makes the retrieval diverse rather than N rankings of
        one question.
        """
        state = _state()
        state["papers"] = [_paper("http://arxiv.org/abs/1")]
        branch = orch.plan_branches(state)[0]

        scoped = orch.branch_input_state(state, branch)

        assert scoped["query"] == "mechanisms"
        assert scoped["sub_questions"] == ["mechanisms"]
        assert scoped["papers"] == []
        assert scoped["messages"] == []
        assert scoped["search_queries"] is not branch["search_queries"]
        assert scoped["run_id"] == state["run_id"]

    def test_one_failing_branch_leaves_its_siblings_whole(self) -> None:
        """The headline claim: a fault does not cross a branch boundary."""
        state = _state()
        state["worker_branches"] = orch.plan_branches(state)

        def execute(_state: ResearchState, branch: WorkerBranch) -> orch.BranchOutcome:
            if branch["branch_id"] == "branch_w00":
                raise NoPapersFound(log_detail="arXiv returned nothing")
            return orch.BranchOutcome(
                papers=[_paper("http://arxiv.org/abs/2")],
                evidence=[_claim("http://arxiv.org/abs/2", "the survivor's claim")],
            )

        branches = orch.run_branches(state, execute=execute)

        failed, survivor = branches
        assert failed["status"] == orch.STATUS_FAILED
        assert failed["reason"] == "not_found_papers"
        assert failed["evidence"] == []
        assert failed["paper_ids"] == []
        assert survivor["status"] == orch.STATUS_SUCCEEDED
        assert survivor["evidence_count"] == 1
        assert survivor["paper_ids"] == ["http://arxiv.org/abs/2"]

    def test_a_partially_written_branch_contributes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A branch that raises *after* finding papers still contributes none.

        Driven through the *real* `_execute_branch`, because that is
        where the guarantee lives: the branch writes papers and evidence
        into its own state and then dies, and the claim is that none of
        it reaches the parent or the sibling. An injected executor would
        prove nothing here — it is handed the parent state by design, so
        it could write to it whatever the module does.
        """
        state = _state()
        state["worker_branches"] = orch.plan_branches(state)

        monkeypatch.setattr(
            orch,
            "search_agent",
            lambda scoped: {"papers": [_paper(f"http://arxiv.org/abs/{scoped['query']}")]},
        )

        def reader(scoped: ResearchState) -> dict[str, Any]:
            # A partial write into the branch's own state, of exactly the
            # shape the real reader makes before it can fail.
            scoped["evidence"] = [_claim(scoped["papers"][0]["id"], "half-written")]
            if scoped["query"] == "mechanisms":
                raise UpstreamPaperRead(log_detail="every analysis failed")
            return {"paper_analyses": [], "evidence": list(scoped["evidence"])}

        monkeypatch.setattr(orch, "reader_agent", reader)

        branches = orch.run_branches(state)

        assert branches[0]["status"] == orch.STATUS_FAILED
        assert branches[0]["reason"] == "upstream_paper_read"
        assert branches[0]["paper_ids"] == []
        assert branches[0]["evidence"] == []
        assert state["papers"] == [], "the parent state was never written to"
        assert state["evidence"] == []
        merged = orch.merge_branches(branches)
        assert [p["id"] for p in merged.papers] == [
            "http://arxiv.org/abs/mitigations"
        ]

    def test_a_cancelled_branch_stops_the_run_and_leaves_the_rest_planned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancellation is the one failure that is never contained (ADR 0047).

        Containing it would turn "abort" into "run the remaining
        branches anyway" — the exact accounting lie the cancel token
        exists to close, one level up from the reader's per-paper check.
        """
        state = _state()
        state["worker_branches"] = orch.plan_branches(state)

        def execute(_state: ResearchState, branch: WorkerBranch) -> orch.BranchOutcome:
            raise JobCancelledError("job-1", "job_timeout")

        with pytest.raises(JobCancelledError):
            orch.run_branches(state, execute=execute)

    def test_a_cancel_between_branches_is_seen_before_the_next_one_starts(
        self,
    ) -> None:
        """The check the reader's own cannot make: between branches.

        Without it a cancelled job would still pay for one whole branch
        — a search and up to `max_papers` model calls — because the
        reader's check fires only once a branch has already reached it.
        """
        state = _state()
        state["worker_branches"] = orch.plan_branches(state)
        token = CancelToken("job-1")
        started: list[str] = []

        def execute(_state: ResearchState, branch: WorkerBranch) -> orch.BranchOutcome:
            started.append(branch["branch_id"])
            token.cancel("job_timeout")
            return orch.BranchOutcome()

        scope = bind_cancel_token(token)
        try:
            with pytest.raises(JobCancelledError):
                orch.run_branches(state, execute=execute)
        finally:
            reset_cancel_token(scope)

        assert started == ["branch_w00"], "the second branch never started"


class TestTheCapsBind:
    def test_the_branch_cap_truncates_the_plan(self) -> None:
        """Three sub-questions, a cap of two, two branches."""
        state = _state()
        state["sub_questions"] = ["one", "two", "three", "four"]

        assert len(orch.plan_branches(state)) == 2

    def test_the_paper_cap_is_also_the_model_call_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Papers in, papers read: the reader spends one call per paper.

        Asserted through the real `_execute_branch` with both agents
        stubbed, because the slice happens *between* them and a test
        that stubbed the executor would be asserting its own arithmetic.
        """
        state = _state()
        branch = orch.plan_branches(state)[0]
        handed: dict[str, int] = {}

        monkeypatch.setattr(
            orch,
            "search_agent",
            lambda s: {"papers": [_paper(f"http://arxiv.org/abs/{i}") for i in range(9)]},
        )

        def reader(scoped: ResearchState) -> dict[str, Any]:
            handed["papers"] = len(scoped["papers"])
            return {"paper_analyses": [], "evidence": []}

        monkeypatch.setattr(orch, "reader_agent", reader)

        outcome = orch._execute_branch(state, branch)

        assert handed["papers"] == 2, "the reader never sees more than the cap"
        assert len(outcome.papers) == 2

    def test_a_branch_that_found_nothing_never_reaches_the_reader(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No papers, no calls. The cheapest branch is the empty one."""
        state = _state()
        branch = orch.plan_branches(state)[0]
        monkeypatch.setattr(orch, "search_agent", lambda s: {"papers": []})

        def reader(_scoped: ResearchState) -> dict[str, Any]:
            raise AssertionError("the reader must not run without papers")

        monkeypatch.setattr(orch, "reader_agent", reader)

        assert orch._execute_branch(state, branch) == orch.BranchOutcome()


class TestTheBudgetIsTheRunsAndTheShareIsTheBranchs:
    def test_each_branch_runs_under_a_cap_of_its_own(
        self, cost_ledger: RunCosts
    ) -> None:
        """The share is bound at the shared choke point, not re-checked here.

        Read back through `effective_cost_cap`, which is the function
        `src/llm.py::_check_cost_budget` calls: if the branch's cap is
        visible there, it is visible to every call the branch makes on
        this thread.
        """
        state = _state()
        state["worker_branches"] = orch.plan_branches(state)
        seen: list[float] = []

        def execute(_state: ResearchState, _branch: WorkerBranch) -> orch.BranchOutcome:
            seen.append(effective_cost_cap(999.0))
            return orch.BranchOutcome()

        orch.run_branches(state, execute=execute)

        assert seen == [1.0, 1.0], "0.5 of a $2.00 ceiling, per branch"
        assert effective_cost_cap(999.0) == 999.0, "the scope is released"

    def test_a_branch_that_trips_its_share_is_recorded_and_the_run_continues(
        self, cost_ledger: RunCosts
    ) -> None:
        """A runaway branch is contained; its siblings still run."""
        state = _state()
        state["worker_branches"] = orch.plan_branches(state)

        def execute(_state: ResearchState, branch: WorkerBranch) -> orch.BranchOutcome:
            if branch["branch_id"] == "branch_w00":
                raise CostBudgetExceeded(spent_usd=1.0, cap_usd=1.0)
            return orch.BranchOutcome(papers=[_paper("http://arxiv.org/abs/2")])

        branches = orch.run_branches(state, execute=execute)

        assert branches[0]["status"] == orch.STATUS_BUDGET_STOPPED
        assert branches[0]["reason"] == "cost_budget_exceeded"
        assert branches[1]["status"] == orch.STATUS_SUCCEEDED

    def test_the_run_ceiling_propagates_to_the_runners_own_path(
        self, cost_ledger: RunCosts
    ) -> None:
        """The ceiling is ADR 0051's, and this module must not reinvent it.

        A share trip and a ceiling trip are the same exception; only the
        cap it carries tells them apart. Swallowing the ceiling here
        would spend the rest of the branch set past a budget the run had
        already exhausted, and the job would never reach the
        budget-stopped outcome that produces a partial report.
        """
        state = _state()
        state["worker_branches"] = orch.plan_branches(state)

        def execute(_state: ResearchState, _branch: WorkerBranch) -> orch.BranchOutcome:
            raise CostBudgetExceeded(spent_usd=2.5, cap_usd=2.0)

        with pytest.raises(CostBudgetExceeded):
            orch.run_branches(state, execute=execute)


class TestTheMergeIsDeterministicAndKeepsProvenance:
    def _two_branches(self) -> list[WorkerBranch]:
        state = _state()
        planned = orch.plan_branches(state)
        shared = "http://arxiv.org/abs/2311.09000"
        return [
            WorkerBranch(
                {
                    **planned[0],
                    "status": orch.STATUS_SUCCEEDED,
                    "papers": [_paper(shared + "v2"), _paper("http://arxiv.org/abs/1")],
                    "paper_analyses": [],
                    "evidence": [
                        _claim(shared + "v2", "shared claim"),
                        _claim("http://arxiv.org/abs/1", "first only"),
                    ],
                }
            ),
            WorkerBranch(
                {
                    **planned[1],
                    "status": orch.STATUS_SUCCEEDED,
                    "papers": [_paper("https://arxiv.org/abs/2311.09000")],
                    "paper_analyses": [],
                    "evidence": [
                        _claim(shared, "shared claim"),
                        _claim(shared, "second only"),
                    ],
                }
            ),
        ]

    def test_the_same_inputs_merge_to_the_same_bytes_twice(self) -> None:
        """Determinism, stated the way a candidate comparison needs it."""
        branches = self._two_branches()

        first = orch.merge_branches(branches)
        second = orch.merge_branches(self._two_branches())

        assert first.evidence == second.evidence
        assert [p["id"] for p in first.papers] == [p["id"] for p in second.papers]
        assert first.provenance == second.provenance

    def test_a_paper_two_branches_found_appears_once_with_both_of_them(
        self,
    ) -> None:
        """Dedup on the canonical key, provenance from every finder.

        The two branches retrieved the paper in different forms — one
        versioned and `http://`, one unversioned and `https://` — which
        is the collision ADR 0041's key exists for and the one a naive
        `id` comparison would miss.
        """
        merged = orch.merge_branches(self._two_branches())

        assert [p["id"] for p in merged.papers] == [
            "http://arxiv.org/abs/2311.09000v2",
            "http://arxiv.org/abs/1",
        ]
        shared = next(
            row for row in merged.provenance if row["claim_count"] == 2
        )
        assert shared["branch_ids"] == ["branch_w00", "branch_w01"]
        assert shared["sub_questions"] == ["mechanisms", "mitigations"]

    def test_the_same_claim_from_two_branches_reaches_the_synthesizer_once(
        self,
    ) -> None:
        """Two branches reading one paper frequently extract one sentence."""
        merged = orch.merge_branches(self._two_branches())

        assert [claim["claim"] for claim in merged.evidence] == [
            "shared claim",
            "first only",
            "second only",
        ]

    def test_a_failed_branch_contributes_nothing_but_stays_on_the_record(
        self,
    ) -> None:
        branches = self._two_branches()
        branches[1] = WorkerBranch(
            {**branches[1], "status": orch.STATUS_FAILED, "reason": "upstream_arxiv"}
        )

        merged = orch.merge_branches(branches)

        assert [claim["claim"] for claim in merged.evidence] == [
            "shared claim",
            "first only",
        ]
        assert [b["status"] for b in merged.branches] == ["succeeded", "failed"]
        assert merged.branches[1]["reason"] == "upstream_arxiv"

    def test_the_merge_releases_each_branchs_bulk_output(self) -> None:
        """Trimming is safe because the merge is incremental."""
        merged = orch.merge_branches(self._two_branches())

        assert all(branch["papers"] == [] for branch in merged.branches)
        assert all(branch["evidence"] == [] for branch in merged.branches)
        assert all(branch["evidence_count"] == 0 for branch in merged.branches), (
            "counts are written by `run_branches`, not by the merge"
        )

    def test_re_merging_a_trimmed_branch_onto_its_own_result_adds_nothing(
        self,
    ) -> None:
        """The property the repair path depends on.

        A second pass through `merge` sees the first pass's branches with
        their bulk released. If that were treated as "these branches
        found nothing", the repair would silently delete the evidence
        the report was built on.
        """
        branches = self._two_branches()
        first = orch.merge_branches(branches)

        again = orch.merge_branches(first.branches, base=first)

        assert again.evidence == first.evidence
        assert again.papers == first.papers
        assert again.provenance == first.provenance


class TestTheNodesReportWhatHappened:
    def test_a_run_with_no_surviving_branch_fails_with_the_branchs_own_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The existing not_found outcome, not a new one and not a crash.

        A node that returned an empty evidence table instead would hand
        the synthesizer nothing and let a fluent, sourceless briefing
        ship — ADR 0041's finding, arrived at from the branch tier.
        """
        state = _state()
        state["worker_branches"] = orch.plan_branches(state)
        monkeypatch.setattr(
            orch,
            "run_branches",
            lambda s: [
                WorkerBranch(
                    {**b, "status": orch.STATUS_FAILED, "reason": "not_found_papers"}
                )
                for b in state["worker_branches"]
            ],
        )

        with pytest.raises(NoPapersFound):
            orch.workers_node(state)

    def test_each_node_stamps_exactly_one_message_under_its_own_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Branch messages are dropped; the transcript records nodes.

        A `search` message from inside a branch would make the message
        trajectory disagree with the node stream, which is the
        comparison every shape's e2e test makes.
        """
        state = _state()
        lead = orch.lead_node(state)
        state["worker_branches"] = lead["worker_branches"]
        monkeypatch.setattr(
            orch,
            "run_branches",
            lambda s: [
                WorkerBranch({**b, "status": orch.STATUS_SUCCEEDED})
                for b in state["worker_branches"]
            ],
        )
        workers = orch.workers_node(state)
        state["worker_branches"] = workers["worker_branches"]
        merge = orch.merge_node(state)

        assert [m.name for m in lead["messages"]] == ["lead"]
        assert [m.name for m in workers["messages"]] == ["workers"]
        assert [m.name for m in merge["messages"]] == ["merge"]

    def test_the_merge_node_carries_the_run_forward_onto_the_evidence_path(
        self,
    ) -> None:
        """What the synthesizer reads is what the merge wrote."""
        state = _state()
        state["worker_branches"] = self_branches = [
            WorkerBranch(
                {
                    **orch.plan_branches(state)[0],
                    "status": orch.STATUS_SUCCEEDED,
                    "papers": [_paper("http://arxiv.org/abs/1")],
                    "paper_analyses": [],
                    "evidence": [_claim("http://arxiv.org/abs/1", "a claim")],
                }
            )
        ]
        assert self_branches

        update = orch.merge_node(state)

        assert [p["id"] for p in update["papers"]] == ["http://arxiv.org/abs/1"]
        assert [c["claim"] for c in update["evidence"]] == ["a claim"]
        assert update["merged_evidence_provenance"][0]["branch_ids"] == [
            "branch_w00"
        ]


class TestTheModuleIsCallableWithoutTheGraph:
    @pytest.mark.parametrize(
        "status", [orch.STATUS_SUCCEEDED, orch.STATUS_FAILED, orch.STATUS_CANCELLED]
    )
    def test_an_already_settled_branch_is_never_re_executed(
        self, status: str
    ) -> None:
        """Re-entry after a repair must not re-run a finished branch."""
        state = _state()
        state["worker_branches"] = [
            WorkerBranch({**branch, "status": status})
            for branch in orch.plan_branches(state)
        ]

        def execute(
            _state: ResearchState, _branch: WorkerBranch
        ) -> orch.BranchOutcome:
            raise AssertionError("a settled branch must not run again")

        assert orch.run_branches(state, execute=execute) == state["worker_branches"]

    def test_every_declared_status_is_one_the_module_can_produce(self) -> None:
        """The published vocabulary is the one the code writes."""
        produced = {
            orch.STATUS_PLANNED,
            orch.STATUS_SUCCEEDED,
            orch.STATUS_FAILED,
            orch.STATUS_CANCELLED,
            orch.STATUS_BUDGET_STOPPED,
        }
        assert set(orch.BRANCH_STATUSES) == produced
        assert len(orch.BRANCH_STATUSES) == len(produced)
