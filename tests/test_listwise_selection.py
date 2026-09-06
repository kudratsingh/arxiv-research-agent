"""Listwise selection and the marginal stop (CAP-09, ADR 0091).

Arm E was `capability_missing` for two reasons and this module is the
evidence for both being gone. Five groups, each testing the property
where it can actually fail:

| Claim | How it is failed here |
|---|---|
| the ranking is deterministic | the same branches ranked twice, and under mock with a tripwire over the provider client |
| selection *decides* rather than reports | a narrowed ceiling; the rejected branch's evidence must not reach the merge, and its record must survive |
| the model path degrades rather than guesses | a ranking that names four of five candidates must not be repaired into five |
| the stop prevents spend | the executor is counted; a branch after the stop must never be called |
| arm E is earned, not declared | the capability gap, the classification and the sealed snapshot |

Zero network, zero provider, zero model: the selector's model path is
reached by substituting `call_llm_json`, and every other test runs under
`USE_MOCK_DATA` where the deterministic ranking is the only path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.config import settings as shipped_settings
from src.graph.state import (
    EvidenceClaim,
    PaperMetadata,
    ResearchState,
    WorkerBranch,
    initial_research_state,
)
from src.policies import orchestration as orch
from src.policies import selection as sel

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def config(**overrides: Any) -> Settings:
    patched = shipped_settings.model_copy(
        update={
            "use_mock_data": True,
            "enable_tracing": False,
            "enable_metrics": False,
            "enable_semantic_scholar": False,
            "enable_checkpointing": False,
            "enable_evidence_store": True,
            "research_policy": "orchestrated_workers",
            "candidate_selection": "listwise",
            "marginal_stop": "off",
            "max_cost_usd": 2.0,
            "orchestration_branch_cost_share": 0.5,
            **overrides,
        }
    )
    assert isinstance(patched, Settings)
    return patched


#: Arm C's compiled shape, as a stand-in: the bridge under test is
#: driven by state updates and knows nothing about which shape sealed
#: the episode it writes into, and arm C is the smallest shape that
#: seals one. Spelled out here rather than imported from a sibling test
#: module for the reason `tests/test_orchestration_lineage.py` gives: an
#: import across test modules rests on a sys.path entry pytest happens
#: to insert.
SEALABLE_SHAPE = (
    "planner",
    "search",
    "reader",
    "synthesizer",
    "verify",
    "repair",
    "critic",
)


class _Edge:
    def __init__(self, source: str, target: str, conditional: bool = False) -> None:
        self.source = source
        self.target = target
        self.conditional = conditional


class _Graph:
    def __init__(self, nodes: list[str], edges: list[_Edge]) -> None:
        self.nodes = {name: object() for name in nodes}
        self.edges = edges


class _AppStub:
    """A compiled-graph stand-in exposing only `get_graph()`."""

    def __init__(self, nodes: tuple[str, ...] = SEALABLE_SHAPE) -> None:
        self._graph = _Graph(
            [*nodes, "__start__", "__end__"],
            [
                _Edge("__start__", nodes[0]),
                *(
                    _Edge(left, right)
                    for left, right in zip(nodes, nodes[1:], strict=False)
                ),
                _Edge(nodes[-1], "__end__", conditional=True),
            ],
        )

    def get_graph(self) -> _Graph:
        return self._graph


def _paper(paper_id: str) -> PaperMetadata:
    return PaperMetadata(
        id=paper_id,
        title="T",
        authors=["A"],
        abstract="abstract",
        url=paper_id,
        pdf_url=paper_id,
    )


def _claim(paper_id: str, text: str) -> EvidenceClaim:
    return EvidenceClaim(
        claim=text,
        paper_id=paper_id,
        section="results",
        source_text="the chunk",
        relevance_score=0.5,
        supports_question="q",
    )


def branch(
    index: int, *, claims: int, papers: int = 1, offset: int = 0
) -> WorkerBranch:
    """One succeeded branch carrying `claims` claims over `papers` papers.

    `offset` shifts the paper ids so two branches can be made to overlap
    exactly (offset equal) or not at all (offset apart), which is what
    the marginal-gain tests turn on.
    """
    paper_ids = [f"http://arxiv.org/abs/24{offset + n:04d}" for n in range(papers)]
    evidence = [
        _claim(paper_ids[n % papers], f"claim {offset + n}") for n in range(claims)
    ]
    return WorkerBranch(
        branch_id=f"branch_w{index:02d}",
        index=index,
        sub_question=f"question {index}",
        search_queries=[f"query {index}"],
        status=orch.STATUS_SUCCEEDED,
        reason="",
        max_papers=4,
        cost_share_usd=1.0,
        paper_ids=paper_ids,
        analysis_count=papers,
        evidence_count=claims,
        llm_calls=papers,
        cost_usd=0.0,
        papers=[_paper(pid) for pid in paper_ids],
        paper_analyses=[],
        evidence=evidence,
    )


def state_with(branches: list[WorkerBranch]) -> ResearchState:
    state = initial_research_state("why do LLMs hallucinate?", "unit-run")
    state["worker_branches"] = branches
    return state


@pytest.fixture(autouse=True)
def selection_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind both policy modules to one known configuration."""
    cfg = config()
    monkeypatch.setattr(sel, "settings", cfg)
    monkeypatch.setattr(orch, "settings", cfg)


def rebind(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> Settings:
    cfg = config(**overrides)
    monkeypatch.setattr(sel, "settings", cfg)
    monkeypatch.setattr(orch, "settings", cfg)
    return cfg


# ---------------------------------------------------------------------------
# 1. The ranking
# ---------------------------------------------------------------------------


class TestTheRankingIsDeterministic:
    def test_candidates_rank_by_evidence_then_papers_then_plan_order(self) -> None:
        branches = [
            branch(0, claims=2, papers=1),
            branch(1, claims=5, papers=1),
            branch(2, claims=2, papers=3),
        ]
        record = sel.select_candidates(state_with(branches), branches)

        assert record is not None
        # w01 has the most claims; w02 and w00 tie on claims and w02 read
        # more papers; a tie on both would fall back to plan order.
        assert [row["branch_id"] for row in record["scores"]] == [
            "branch_w01",
            "branch_w02",
            "branch_w00",
        ]
        assert [row["rank"] for row in record["scores"]] == [0, 1, 2]

    def test_an_exact_tie_falls_back_to_the_plan_order(self) -> None:
        """Which is fixture order under mock: every branch reads one corpus."""
        branches = [branch(index, claims=3, papers=1) for index in (2, 0, 1)]
        record = sel.select_candidates(state_with(branches), branches)

        assert record is not None
        assert [row["branch_id"] for row in record["scores"]] == [
            "branch_w00",
            "branch_w01",
            "branch_w02",
        ]

    def test_the_same_branches_rank_the_same_way_twice(self) -> None:
        branches = [
            branch(0, claims=4),
            branch(1, claims=7),
            branch(2, claims=1),
        ]
        first = sel.select_candidates(state_with(branches), branches)
        second = sel.select_candidates(state_with(branches), branches)

        assert first == second

    def test_mock_mode_makes_no_model_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The claim the campaign's zero-cost full matrix rests on."""
        import src.llm as llm_module

        def refuse() -> Any:  # pragma: no cover - the point is that it is not hit
            raise AssertionError("the mock selector constructed a provider client")

        monkeypatch.setattr(llm_module, "_get_client", refuse)
        branches = [branch(0, claims=3), branch(1, claims=5)]
        record = sel.select_candidates(state_with(branches), branches)

        assert record is not None
        assert record["selector_kind"] == sel.SELECTOR_DETERMINISTIC
        assert record["llm_calls"] == 0

    def test_a_branch_with_no_evidence_is_not_a_candidate(self) -> None:
        empty = {**branch(1, claims=1), "evidence": [], "evidence_count": 0}
        branches = [branch(0, claims=2), WorkerBranch(empty)]  # type: ignore[arg-type]
        record = sel.select_candidates(state_with(branches), branches)

        assert record is not None
        assert record["eligible_branch_ids"] == ["branch_w00"]

    def test_no_eligible_candidate_produces_no_record_at_all(self) -> None:
        """`None`, not an empty selection: the merge reads the record."""
        failed = {**branch(0, claims=0), "status": orch.STATUS_FAILED}
        assert sel.select_candidates(state_with([WorkerBranch(failed)]), [WorkerBranch(failed)]) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Selection decides what the merge sees
# ---------------------------------------------------------------------------


class TestSelectionNarrowsTheMerge:
    def test_a_rejected_branch_keeps_its_record_and_loses_its_evidence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rebind(monkeypatch, selection_max_candidates=1)
        branches = [
            branch(0, claims=2, papers=1, offset=0),
            branch(1, claims=5, papers=1, offset=100),
        ]
        record = sel.select_candidates(state_with(branches), branches)
        assert record is not None
        assert record["selected_branch_ids"] == ["branch_w01"]
        assert record["rejected_branch_ids"] == ["branch_w00"]

        merged = orch.merge_branches(
            branches, selected=frozenset(record["selected_branch_ids"])
        )
        assert [claim["claim"] for claim in merged.evidence] == [
            f"claim {100 + n}" for n in range(5)
        ]
        # The rejected branch is still on the record, with its status and
        # its counts: RFC 10 §6.4 — non-selection never deletes.
        assert {b["branch_id"] for b in merged.branches} == {
            "branch_w00",
            "branch_w01",
        }
        assert {row["selected"] for row in record["scores"]} == {True, False}

    def test_the_top_ranked_candidate_is_always_selected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ceiling of zero is refused, not obeyed: ADR 0041's floor."""
        rebind(monkeypatch, selection_max_candidates=1)
        branches = [branch(0, claims=1)]
        record = sel.select_candidates(state_with(branches), branches)

        assert record is not None
        assert record["selected_branch_ids"] == ["branch_w00"]
        assert record["rejected_branch_ids"] == []

    def test_no_selection_record_merges_every_succeeded_branch(self) -> None:
        """CAP-03's behaviour, which a deployment with no selector keeps."""
        branches = [
            branch(0, claims=2, offset=0),
            branch(1, claims=2, offset=100),
        ]
        assert len(orch.merge_branches(branches).evidence) == 4

    def test_selection_cannot_retract_what_an_earlier_pass_merged(self) -> None:
        """ADR 0086's incremental merge, holding against a later selector."""
        first = [branch(0, claims=3, offset=0)]
        base = orch.merge_branches(first, selected=frozenset({"branch_w00"}))
        assert len(base.evidence) == 3

        second = [*first, branch(1, claims=2, offset=100)]
        merged = orch.merge_branches(
            second, base=base, selected=frozenset({"branch_w01"})
        )
        assert len(merged.evidence) == 5

    def test_the_node_puts_the_record_on_the_state(self) -> None:
        branches = [branch(0, claims=2), branch(1, claims=4)]
        update = sel.select_node(state_with(branches))

        assert update["candidate_selection"]["selected_branch_ids"] == [
            "branch_w01",
            "branch_w00",
        ]
        assert update["messages"][0].name == "select"


# ---------------------------------------------------------------------------
# 3. The model path
# ---------------------------------------------------------------------------


class TestTheModelPathIsListwiseOrItIsNothing:
    def _live(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rebind(monkeypatch, use_mock_data=False)

    def test_one_call_ranks_the_whole_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._live(monkeypatch)
        calls: list[str] = []

        def fake(prompt: str, system: str = "", **kwargs: Any) -> dict[str, Any]:
            calls.append(prompt)
            assert kwargs["schema"] is sel.ListwiseRanking
            return {
                "ranking": [
                    {
                        "branch_id": "branch_w01",
                        "rank": 0,
                        "score": 0.9,
                        "reason": "broader grounding",
                    },
                    {
                        "branch_id": "branch_w00",
                        "rank": 1,
                        "score": 0.4,
                        "reason": "narrower",
                    },
                ]
            }

        import src.llm as llm_module

        monkeypatch.setattr(llm_module, "call_llm_json", fake)
        branches = [branch(0, claims=6), branch(1, claims=2)]
        record = sel.select_candidates(state_with(branches), branches)

        assert record is not None
        assert len(calls) == 1, "listwise means one call, not one per pair"
        assert record["selector_kind"] == sel.SELECTOR_MODEL
        assert record["llm_calls"] == 1
        # The model's order wins over the deterministic one, which would
        # have put w00 first on claim count.
        assert [row["branch_id"] for row in record["scores"]] == [
            "branch_w01",
            "branch_w00",
        ]
        assert record["scores"][0]["reason"] == "broader grounding"

    def test_a_ranking_that_misses_a_candidate_degrades_rather_than_guesses(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._live(monkeypatch)

        def partial(prompt: str, system: str = "", **kwargs: Any) -> dict[str, Any]:
            return {
                "ranking": [
                    {
                        "branch_id": "branch_w00",
                        "rank": 0,
                        "score": 1.0,
                        "reason": "only one named",
                    }
                ]
            }

        import src.llm as llm_module

        monkeypatch.setattr(llm_module, "call_llm_json", partial)
        branches = [branch(0, claims=2), branch(1, claims=9)]
        with caplog.at_level("WARNING"):
            record = sel.select_candidates(state_with(branches), branches)

        assert record is not None
        assert record["selector_kind"] == sel.SELECTOR_DETERMINISTIC
        assert record["llm_calls"] == 0
        assert [row["branch_id"] for row in record["scores"]] == [
            "branch_w01",
            "branch_w00",
        ]
        assert "candidate_selection_degraded" in caplog.text

    def test_a_provider_failure_degrades_rather_than_failing_the_run(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._live(monkeypatch)

        def boom(prompt: str, system: str = "", **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("provider refused")

        import src.llm as llm_module

        monkeypatch.setattr(llm_module, "call_llm_json", boom)
        branches = [branch(0, claims=2), branch(1, claims=4)]
        with caplog.at_level("WARNING"):
            record = sel.select_candidates(state_with(branches), branches)

        assert record is not None
        assert record["selector_kind"] == sel.SELECTOR_DETERMINISTIC
        assert "candidate_selection_degraded" in caplog.text

    def test_one_candidate_is_not_a_list_and_costs_no_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._live(monkeypatch)

        def refuse(*args: Any, **kwargs: Any) -> dict[str, Any]:
            raise AssertionError("a single candidate was sent to the model")

        import src.llm as llm_module

        monkeypatch.setattr(llm_module, "call_llm_json", refuse)
        branches = [branch(0, claims=3)]
        record = sel.select_candidates(state_with(branches), branches)

        assert record is not None
        assert record["llm_calls"] == 0

    def test_the_schema_forbids_extra_keys(self) -> None:
        """`additionalProperties: false`, which is what makes the schema
        a statement about the whole object rather than a floor under it."""
        schema = sel.ListwiseRanking.model_json_schema()
        assert schema["additionalProperties"] is False
        assert "description" not in schema


# ---------------------------------------------------------------------------
# 4. The marginal stop
# ---------------------------------------------------------------------------


class TestTheMarginalStopPreventsSpend:
    def _planned(self, count: int) -> list[WorkerBranch]:
        return [
            WorkerBranch(
                {
                    **branch(index, claims=0),
                    "status": orch.STATUS_PLANNED,
                    "paper_ids": [],
                    "papers": [],
                    "evidence": [],
                    "evidence_count": 0,
                    "analysis_count": 0,
                }
            )
            for index in range(count)
        ]

    def test_off_by_default_every_branch_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rebind(monkeypatch, marginal_stop="off")
        seen: list[str] = []

        def execute(state: ResearchState, item: WorkerBranch) -> orch.BranchOutcome:
            seen.append(item["branch_id"])
            return orch.BranchOutcome(papers=[_paper("http://arxiv.org/abs/240001")])

        state = state_with(self._planned(3))
        settled = orch.run_branches(state, execute=execute)

        assert seen == ["branch_w00", "branch_w01", "branch_w02"]
        assert {b["status"] for b in settled} == {orch.STATUS_SUCCEEDED}

    def test_a_branch_that_adds_nothing_new_stops_the_next_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The claim: the rule runs inside the loop, so it stops spend."""
        rebind(monkeypatch, marginal_stop="on", marginal_stop_threshold=1.0)
        seen: list[str] = []
        paper = _paper("http://arxiv.org/abs/240001")
        claim = _claim(paper["id"], "the one claim")

        def execute(state: ResearchState, item: WorkerBranch) -> orch.BranchOutcome:
            seen.append(item["branch_id"])
            # Every branch returns the *same* paper and the same claim, so
            # branch two's marginal contribution is exactly nothing.
            return orch.BranchOutcome(papers=[paper], evidence=[claim])

        state = state_with(self._planned(4))
        settled = orch.run_branches(state, execute=execute)

        assert seen == ["branch_w00", "branch_w01"], "branch three never ran"
        statuses = {b["branch_id"]: b["status"] for b in settled}
        assert statuses["branch_w00"] == orch.STATUS_SUCCEEDED
        assert statuses["branch_w01"] == orch.STATUS_SUCCEEDED
        assert statuses["branch_w02"] == orch.STATUS_STOPPED
        assert statuses["branch_w03"] == orch.STATUS_STOPPED
        assert {
            b["reason"] for b in settled if b["status"] == orch.STATUS_STOPPED
        } == {orch.REASON_MARGINAL_STOP}

    def test_the_record_carries_the_gain_the_threshold_and_the_method(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rebind(monkeypatch, marginal_stop="on", marginal_stop_threshold=1.0)
        paper = _paper("http://arxiv.org/abs/240001")
        claim = _claim(paper["id"], "the one claim")

        def execute(state: ResearchState, item: WorkerBranch) -> orch.BranchOutcome:
            return orch.BranchOutcome(papers=[paper], evidence=[claim])

        settled = orch.run_branches(state_with(self._planned(3)), execute=execute)
        record = orch.marginal_stop_record(settled)

        assert record["stopped"] is True
        assert record["stopped_after_branch_id"] == "branch_w01"
        assert record["stopped_before_branch_id"] == "branch_w02"
        assert record["branches_stopped"] == 1
        assert record["marginal_gain"] == 0.0
        assert record["threshold"] == 1.0
        assert record["incremental_cost_usd"] == 1.0
        assert record["gain_method"] == orch.MARGINAL_GAIN_METHOD

    def test_a_record_exists_even_when_the_rule_did_not_fire(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """"Measured and continued" and "never measured" are different."""
        rebind(monkeypatch, marginal_stop="on", marginal_stop_threshold=1.0)
        counter = {"n": 0}

        def execute(state: ResearchState, item: WorkerBranch) -> orch.BranchOutcome:
            counter["n"] += 1
            offset = counter["n"] * 100
            papers = [_paper(f"http://arxiv.org/abs/24{offset:04d}")]
            return orch.BranchOutcome(
                papers=papers,
                evidence=[_claim(papers[0]["id"], f"claim {offset}")],
            )

        settled = orch.run_branches(state_with(self._planned(3)), execute=execute)
        record = orch.marginal_stop_record(settled)

        assert counter["n"] == 3
        assert record["stopped"] is False
        assert record["stopped_after_branch_id"] == ""
        assert record["marginal_gain"] > record["threshold"]

    def test_a_failed_branch_never_triggers_a_stop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An upstream fault is not evidence that more retrieval is futile."""
        rebind(monkeypatch, marginal_stop="on", marginal_stop_threshold=1000.0)
        from src.errors import UpstreamPaperRead

        seen: list[str] = []

        def execute(state: ResearchState, item: WorkerBranch) -> orch.BranchOutcome:
            seen.append(item["branch_id"])
            if item["index"] == 0:
                raise UpstreamPaperRead(log_detail="pdf refused")
            papers = [_paper(f"http://arxiv.org/abs/24{item['index']:04d}")]
            return orch.BranchOutcome(papers=papers)

        settled = orch.run_branches(state_with(self._planned(3)), execute=execute)

        # The failure did not stop the loop; the *second* branch's own
        # gain did, against an unreachable threshold.
        assert seen == ["branch_w00", "branch_w01"]
        statuses = {b["branch_id"]: b["status"] for b in settled}
        assert statuses["branch_w00"] == orch.STATUS_FAILED
        assert statuses["branch_w02"] == orch.STATUS_STOPPED

    def test_the_gain_is_new_items_per_share_dollar(self) -> None:
        first = branch(0, claims=3, papers=1, offset=0)
        overlap = branch(1, claims=3, papers=1, offset=0)
        fresh = branch(2, claims=3, papers=1, offset=100)

        # One paper + three claims = four items, over a $1.00 share.
        assert orch.branch_marginal_gain([], first) == 4.0
        assert orch.branch_marginal_gain([first], overlap) == 0.0
        assert orch.branch_marginal_gain([first], fresh) == 4.0

    def test_the_workers_node_publishes_the_record_only_when_asked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def execute(state: ResearchState, item: WorkerBranch) -> orch.BranchOutcome:
            papers = [_paper(f"http://arxiv.org/abs/24{item['index']:04d}")]
            return orch.BranchOutcome(papers=papers)

        monkeypatch.setattr(orch, "run_branches", lambda state: [branch(0, claims=2)])
        rebind(monkeypatch, marginal_stop="off")
        assert "marginal_stop" not in orch.workers_node(state_with([]))

        rebind(monkeypatch, marginal_stop="on")
        assert "marginal_stop" in orch.workers_node(state_with([]))


# ---------------------------------------------------------------------------
# 5. Arm E is earned
# ---------------------------------------------------------------------------


class TestArmEIsEarnedRatherThanDeclared:
    pytestmark = [pytest.mark.unit, pytest.mark.contract]

    def test_the_branch_tier_without_a_selector_is_still_not_arm_e(self) -> None:
        """ADR 0086's classification, unchanged where nothing was built."""
        from src.campaign.execute import compiled_graph
        from src.contracts.research_binding import (
            arm_capability_gap,
            classify_from_graph_shape,
            read_deployment_shape,
        )

        cfg = config(
            research_policy="orchestrated_workers",
            candidate_selection="off",
            marginal_stop="off",
        )
        with compiled_graph(cfg) as app:
            shape = classify_from_graph_shape(cfg, read_deployment_shape(app))

        assert shape.arm_id is None
        assert shape.policy_kind == "research_shape"
        assert shape.policy_id == "research_orchestrated_workers"
        assert set(arm_capability_gap("E", shape)) == {
            "adaptive_compute_router",
            "marginal_stop",
            "candidate_lineage_selector",
        }

    def test_a_selector_alone_is_still_not_arm_e(self) -> None:
        """Three of four is not four: the router and the stop are missing."""
        from src.campaign.execute import compiled_graph
        from src.contracts.research_binding import (
            arm_capability_gap,
            classify_from_graph_shape,
            read_deployment_shape,
        )

        cfg = config(
            research_policy="orchestrated_workers",
            candidate_selection="listwise",
            marginal_stop="off",
        )
        with compiled_graph(cfg) as app:
            shape = classify_from_graph_shape(cfg, read_deployment_shape(app))

        assert shape.arm_id is None
        assert set(arm_capability_gap("E", shape)) == {
            "adaptive_compute_router",
            "marginal_stop",
        }

    def test_the_full_deployment_earns_arm_e_and_seals_it(self) -> None:
        from src.campaign.arms import ARM_SETTINGS, arm_settings, declare_arm
        from src.campaign.execute import arm_graph_probe
        from src.contracts.research_binding import policy_snapshot

        base = config()
        probe = arm_graph_probe(base)
        declaration = declare_arm("E", graph=probe("E"))

        assert declaration.status == "available"
        assert declaration.runnable is True
        assert declaration.missing_capabilities == ()
        # And the row that earns it is the real configuration, not D's.
        assert ARM_SETTINGS["E"]["enable_supervisor"] is False
        assert arm_settings(base, "E").compute_controller == "deterministic"

        from src.campaign.arms import classify_arm

        shape = classify_arm(base, "E", probe("E"))
        snapshot = policy_snapshot(shape)
        assert snapshot.arm_id == "E"
        assert snapshot.selector == "adaptive_verified"
        assert snapshot.capabilities.adaptive_compute is True
        assert snapshot.config.allowed_tiers == ("T0", "T1", "T2")
        assert snapshot.config.selection == "listwise"

    def test_no_arm_is_unrunnable_and_the_mechanism_survives(self) -> None:
        from src.campaign.arms import UNRUNNABLE_ARMS

        assert frozenset() == UNRUNNABLE_ARMS

    def test_the_selector_settings_are_refused_without_a_branch_tier(self) -> None:
        """`model_validate`, not `model_copy`: the copy path skips validators."""
        values = dict(config().model_dump())
        values.update(
            {
                "research_policy": "legacy",
                "compute_controller": "off",
                "orchestration": "off",
                "candidate_selection": "listwise",
                "marginal_stop": "on",
            }
        )
        with pytest.raises(ValueError, match="branch tier") as caught:
            Settings.model_validate(values)
        # Both offenders named, so one boot attempt fixes the whole file.
        assert "candidate_selection=listwise" in str(caught.value)
        assert "marginal_stop=on" in str(caught.value)

    def test_the_default_configuration_compiles_no_select_node(self) -> None:
        from src.campaign.execute import compiled_graph
        from src.contracts.research_binding import read_graph_shape

        cfg = config(candidate_selection="off", marginal_stop="off")
        with compiled_graph(cfg) as app:
            assert "select" not in read_graph_shape(app).nodes


# ---------------------------------------------------------------------------
# 6. The trajectory
# ---------------------------------------------------------------------------


class TestTheSelectionReachesTheTrajectory:
    pytestmark = [pytest.mark.unit, pytest.mark.contract]

    def _bridge(self, tmp_path: Path) -> Any:
        from src.contracts import runtime_bridge as rb
        from src.contracts.research_binding import (
            classify_from_graph_shape,
            compile_research_intake,
            read_graph_shape,
            seal_research_episode,
        )

        cfg = config(research_policy="fixed_verify_repair")
        shape = classify_from_graph_shape(cfg, read_graph_shape(_AppStub()))
        spec = compile_research_intake(
            cfg,
            task_id="research-eval:selection",
            query="compare RAG, CoVe and Self-RAG",
            hitl_plan_review=False,
            supervisor=False,
        )
        return rb.start_research_run(
            cfg,
            episode=seal_research_episode(
                cfg,
                shape=shape,
                spec=spec,
                origin="research_eval",
                runtime_run_id="selection-1",
                hitl_bypass=True,
                hitl_bypass_reason="unattended-evaluation",
            ),
            runtime_run_id="selection-1",
            principal_key_id="synthetic:research-eval",
            cost_ceiling_usd=2.0,
            sink_root=tmp_path / "sink",
        )

    def test_scores_and_a_selection_follow_the_branch_candidates(
        self, tmp_path: Path
    ) -> None:
        from src.contracts import runtime_bridge as rb
        from src.contracts.trajectory import verify_trajectory

        bridge = self._bridge(tmp_path)
        branches = [branch(0, claims=2, offset=0), branch(1, claims=4, offset=100)]
        rb.observe_node(bridge, "workers", {"worker_branches": branches})

        record = sel.select_candidates(state_with(branches), branches)
        assert record is not None
        rb.observe_node(bridge, "select", {"candidate_selection": record})

        assert bridge.degraded is False
        scored = [e for e in bridge.events() if e.event_type == "candidate.scored"]
        chosen = [e for e in bridge.events() if e.event_type == "candidate.selected"]
        created = [e for e in bridge.events() if e.event_type == "candidate.created"]

        assert len(created) == 2
        assert len(scored) == 2, "every eligible candidate is scored, not only winners"
        assert len(chosen) == 1
        payload = chosen[0].payload
        assert len(payload["eligible_candidate_ids"]) == 2
        assert payload["selected_candidate_id"] in payload["eligible_candidate_ids"]
        assert payload["selector_kind"] == sel.SELECTOR_DETERMINISTIC
        # And the ids the selection names are the ids the branches minted.
        assert set(payload["eligible_candidate_ids"]) == {
            e.payload["candidate_id"] for e in created
        }
        bridge.close()
        verify_trajectory(bridge.events())

    def test_the_marginal_stop_reaches_the_trajectory_either_way(
        self, tmp_path: Path
    ) -> None:
        from src.contracts import runtime_bridge as rb

        bridge = self._bridge(tmp_path)
        rb.observe_node(
            bridge,
            "workers",
            {
                "marginal_stop": {
                    "stopped": True,
                    "stopped_after_branch_id": "branch_w01",
                    "stopped_before_branch_id": "branch_w02",
                    "branches_stopped": 1,
                    "marginal_gain": 0.0,
                    "threshold": 1.0,
                    "incremental_cost_usd": 0.8,
                    "gain_method": orch.MARGINAL_GAIN_METHOD,
                }
            },
        )
        stops = [
            e for e in bridge.events() if e.event_type == "compute.stop_decided"
        ]
        assert len(stops) == 1
        assert stops[0].payload["reason_code"] == "marginal_gain_below_threshold"
        # Fixed-format strings: `agent-contract-json/v1` rejects a binary
        # float in a payload, so the record's numbers are formatted on
        # the way in rather than rounded on the way out.
        assert stops[0].payload["marginal_gain"] == "0.000000"
        assert stops[0].payload["incremental_cost_estimate"] == "0.800000"
        assert (
            stops[0].payload["expected_gain_method"] == orch.MARGINAL_GAIN_METHOD
        )
        assert bridge.degraded is False

    def test_a_repeated_state_update_records_the_selection_once(
        self, tmp_path: Path
    ) -> None:
        """The record rides on the state and passes `observe_node` twice."""
        from src.contracts import runtime_bridge as rb

        bridge = self._bridge(tmp_path)
        branches = [branch(0, claims=2, offset=0), branch(1, claims=4, offset=100)]
        rb.observe_node(bridge, "workers", {"worker_branches": branches})
        record = sel.select_candidates(state_with(branches), branches)
        assert record is not None
        for node in ("select", "merge"):
            rb.observe_node(bridge, node, {"candidate_selection": record})

        assert (
            len([e for e in bridge.events() if e.event_type == "candidate.selected"])
            == 1
        )

    def test_a_stopped_branch_settles_as_cancelled_with_its_own_reason(
        self, tmp_path: Path
    ) -> None:
        from src.contracts import runtime_bridge as rb

        bridge = self._bridge(tmp_path)
        stopped = {
            **branch(2, claims=0),
            "status": orch.STATUS_STOPPED,
            "reason": orch.REASON_MARGINAL_STOP,
            "evidence": [],
            "papers": [],
        }
        rb.observe_node(bridge, "workers", {"worker_branches": [stopped]})

        cancelled = [
            e for e in bridge.events() if e.event_type == "branch.cancelled"
        ]
        assert len(cancelled) == 1
        assert cancelled[0].payload["reason_code"] == orch.REASON_MARGINAL_STOP
        assert not [e for e in bridge.events() if e.event_type == "branch.failed"]


# ---------------------------------------------------------------------------
# 7. What the router actually does on this suite
# ---------------------------------------------------------------------------


class TestTheRouterOnTheShippedSuite:
    pytestmark = [pytest.mark.unit, pytest.mark.contract]

    def test_the_tier_each_benchmark_query_routes_to_is_recorded(self) -> None:
        """Evidence, not a caveat: arm E's router declines T2 on this suite.

        Arm E is adaptive compute, and what "adaptive" buys is decided by
        the difficulty features rather than by the arm's name. On
        `research-policy-v1`'s twenty queries the branch tier's two rules
        (a comparison over three or more entities, or a plan broader than
        the planner's own range) do not fire, so every episode routes to
        T0 or T1. That is a result the campaign should be able to read
        off the record rather than a gap in this work order, and it is
        pinned here so a later change to `TIER_RULES` — which belongs to
        CAP-04 and to ADR 0070's discipline about movable thresholds —
        shows up as a change to this number.
        """
        from collections import Counter

        from src.contracts.benchmark_adapters import suite_ref
        from src.contracts.registry import (
            IntendedUse,
            LocalRegistry,
            RegistryRole,
            TaskSet,
        )
        from src.policies.compute import BRANCH_TIER, decide_tier, extract_features

        root = Path(__file__).resolve().parents[1] / "eval_registry"
        registry = LocalRegistry(root)
        suite = registry.resolve(
            suite_ref(root, "research-policy-v1"),
            role=RegistryRole.EVALUATOR,
            intended_use=IntendedUse.DEVELOPMENT,
        ).payload
        task_set = registry.resolve(
            suite.task_set_ref,
            role=RegistryRole.EVALUATOR,
            intended_use=IntendedUse.DEVELOPMENT,
        ).payload
        assert isinstance(task_set, TaskSet)

        tiers: Counter[str] = Counter()
        for case_ref in task_set.case_refs:
            case = registry.resolve(
                case_ref,
                role=RegistryRole.EVALUATOR,
                intended_use=IntendedUse.DEVELOPMENT,
            ).payload
            objective = case.task_input.objective
            tiers[
                decide_tier(extract_features(objective), max_tier=BRANCH_TIER).tier
            ] += 1

        assert sum(tiers.values()) == 20
        assert tiers == Counter({"T0": 12, "T1": 8})


def test_the_selection_record_is_json_round_trippable() -> None:
    """The bridge stores it as an artifact, so it has to serialise."""
    branches = [branch(0, claims=2), branch(1, claims=3)]
    record = sel.select_candidates(state_with(branches), branches)
    assert record is not None
    assert json.loads(json.dumps(record, sort_keys=True)) == record
