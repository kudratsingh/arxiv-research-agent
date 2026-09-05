"""What a branch run leaves in the trajectory (ADR 0086, RFC 10 §6.3-§6.4).

CAP-03 does not build a selector. What it owes CAP-09 is the record a
selector will be evaluated against: one branch per sub-question, a
candidate id for each branch's evidence table, and a closing event that
says how the branch ended — including the branches that failed, because
"the selector never saw this candidate" and "this candidate lost" are
different facts and a run that dropped failed branches could not tell
them apart afterwards.

Everything here goes through `observe_node`, which is the only route the
graph has: `src/policies/orchestration.py` imports no contract module
(ADR 0078 keeps them off a flag-off deployment's import graph), so the
branch record travels out on the node's state update.

Zero network, zero provider, zero model. The graph is a stand-in that
answers `get_graph()`; the sink is a directory under `tmp_path`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts import runtime_bridge as rb
from src.contracts.research_binding import (
    classify_from_graph_shape,
    compile_research_intake,
    read_graph_shape,
    seal_research_episode,
)
from src.contracts.trajectory import (
    ArtifactRole,
    StoredTrajectoryEvent,
    import_jsonl,
    verify_trajectory,
)

pytestmark = [pytest.mark.unit, pytest.mark.contract]

#: The graph the sealed episode below is classified against. **Arm C's**,
#: not the branch tier's, and the reason is ADR 0086's principal known
#: gap: `run_manifest.PolicySnapshot.arm_id` is a required `A`-`E` and
#: arm E's validator demands a supervisor, `marginal_stop` and a
#: selection config, so the branch shape — which is honestly none of
#: those — cannot seal a manifest, and `start_research_job` declines it
#: the way it declines every other non-arm shape
#: (`src/contracts/runtime_bridge.py`, "Declining is the designed
#: outcome"). `tests/test_orchestration_controller.py` asserts that gap
#: directly. What is under test *here* is the recorder, which is the
#: same recorder either configuration reaches: it is driven by the branch
#: records on a node update and knows nothing about which shape sealed
#: the episode it is writing into.
SEALABLE_SHAPE = (
    "planner",
    "search",
    "reader",
    "synthesizer",
    "verify",
    "repair",
    "critic",
)
SYNTHETIC_PRINCIPAL = "synthetic:research-eval"


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
    """A compiled-graph stand-in exposing only `get_graph()`.

    Spelled out here rather than imported from
    `tests/test_contract_runtime_bridge.py` for the reason the e2e
    conftest gives about importing across test modules: it would rest on
    a sys.path entry pytest happens to insert, and a file whose whole job
    is to be trustworthy should not.
    """

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


def config(**overrides: Any) -> Settings:
    patched = shipped_settings.model_copy(
        update={
            "use_mock_data": True,
            "enable_tracing": False,
            "enable_metrics": False,
            "enable_semantic_scholar": False,
            "enable_checkpointing": False,
            "enable_evidence_store": True,
            "contract_shadow": "shadow",
            "contract_event_capture": "evaluation_only",
            **overrides,
        }
    )
    assert isinstance(patched, Settings)
    return patched


def branch_bridge(tmp_path: Path, nodes: tuple[str, ...] = SEALABLE_SHAPE) -> Any:
    cfg = config()
    shape = classify_from_graph_shape(cfg, read_graph_shape(_AppStub(nodes)))
    spec = compile_research_intake(
        cfg,
        task_id="research-eval:branching",
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
            runtime_run_id="branching-1",
            hitl_bypass=True,
            hitl_bypass_reason="unattended-evaluation",
        ),
        runtime_run_id="branching-1",
        principal_key_id=SYNTHETIC_PRINCIPAL,
        cost_ceiling_usd=2.0,
        sink_root=tmp_path / "sink",
    )


def planned(branch_id: str, question: str, index: int) -> dict[str, Any]:
    return {
        "branch_id": branch_id,
        "index": index,
        "sub_question": question,
        "search_queries": [question],
        "status": "planned",
        "reason": "",
        "max_papers": 4,
        "cost_share_usd": 0.8,
        "paper_ids": [],
        "analysis_count": 0,
        "evidence_count": 0,
        "llm_calls": 0,
        "cost_usd": 0.0,
        "papers": [],
        "paper_analyses": [],
        "evidence": [],
    }


def succeeded(branch: dict[str, Any], claims: int = 2) -> dict[str, Any]:
    paper = f"http://arxiv.org/abs/{branch['index']}"
    return {
        **branch,
        "status": "succeeded",
        "paper_ids": [paper],
        "analysis_count": 1,
        "evidence_count": claims,
        "llm_calls": 1,
        "cost_usd": 0.01,
        "evidence": [
            {
                "claim": f"claim {n} for {branch['sub_question']}",
                "paper_id": paper,
                "section": "results",
                "source_text": "the chunk",
                "relevance_score": 0.7,
                "supports_question": branch["sub_question"],
            }
            for n in range(claims)
        ],
    }


def settled(branch: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    return {**branch, "status": status, "reason": reason}


def of_type(bridge: Any, event_type: str) -> list[StoredTrajectoryEvent]:
    return [event for event in bridge.events() if event.event_type == event_type]


def three_branches() -> list[dict[str, Any]]:
    return [
        planned("branch_w00", "how does RAG ground answers?", 0),
        planned("branch_w01", "what does CoVe verify?", 1),
        planned("branch_w02", "where does Self-RAG differ?", 2),
    ]


class TestOneBranchPerSubQuestion:
    def test_the_lead_creates_a_branch_for_every_planned_sub_question(
        self, tmp_path: Path
    ) -> None:
        """Three sub-questions, three branches, forked off the main one.

        `diversity_dimension` says *why* these are siblings rather than
        retries. RFC 10 §8.6 makes it a required field precisely so a
        later analysis can tell a diversified branch set from N attempts
        at one plan.
        """
        bridge = branch_bridge(tmp_path)

        rb.observe_node(bridge, "lead", {"worker_branches": three_branches()})

        created = of_type(bridge, "branch.created")
        assert [event.payload["new_branch_id"] for event in created] == [
            "branch_w00",
            "branch_w01",
            "branch_w02",
        ]
        assert all(event.branch_id == rb.MAIN_BRANCH_ID for event in created)
        assert all(
            event.payload["parent_branch_id"] == rb.MAIN_BRANCH_ID
            for event in created
        )
        assert all(
            event.payload["diversity_dimension"] == "sub_question"
            for event in created
        )

    def test_a_settled_branch_closes_on_its_own_branch_id(
        self, tmp_path: Path
    ) -> None:
        """The envelope carries the branch, not just the payload.

        RFC 10 §6.3 requires both and requires them to agree, which is
        what lets a reader filter a branch's events without parsing
        payloads — and what a candidate comparison needs, since a
        candidate belongs to the branch that produced it.
        """
        bridge = branch_bridge(tmp_path)
        branches = three_branches()
        rb.observe_node(bridge, "lead", {"worker_branches": branches})

        rb.observe_node(
            bridge,
            "workers",
            {"worker_branches": [succeeded(branch) for branch in branches]},
        )

        completed = of_type(bridge, "branch.completed")
        assert [event.branch_id for event in completed] == [
            "branch_w00",
            "branch_w01",
            "branch_w02",
        ]
        assert all(
            event.payload["branch_id"] == event.branch_id for event in completed
        )
        assert all(
            event.payload["stop_reason_code"] == "completed" for event in completed
        )


class TestEachBranchsEvidenceTableIsACandidate:
    def test_every_succeeded_branch_records_a_candidate_the_selector_can_compare(
        self, tmp_path: Path
    ) -> None:
        """The lineage CAP-09 needs: distinct siblings, named on the close.

        Distinct ids are the load-bearing half. RFC 10 §6.4 says sibling
        candidates never share an id even when their bytes match, and
        three branches over one corpus can easily extract overlapping
        claims — so the branch and its question are part of what the id
        is derived from.
        """
        bridge = branch_bridge(tmp_path)
        branches = three_branches()
        rb.observe_node(bridge, "lead", {"worker_branches": branches})

        rb.observe_node(
            bridge,
            "workers",
            {"worker_branches": [succeeded(branch) for branch in branches]},
        )

        candidates = of_type(bridge, "candidate.created")
        assert len(candidates) == 3
        assert len({event.payload["candidate_id"] for event in candidates}) == 3
        assert all(
            event.payload["candidate_kind"] == "branch_evidence_table"
            for event in candidates
        )
        assert all(
            event.payload["generation_method"] == "orchestrated_worker"
            for event in candidates
        )
        assert all(
            event.artifact_refs[0].role is ArtifactRole.CANDIDATE_OUTLINE
            for event in candidates
        )
        # Each close names its own branch's candidate, and only that one.
        for closed in of_type(bridge, "branch.completed"):
            named = closed.payload["candidate_ids"]
            assert len(named) == 1
            assert closed.candidate_id == named[0]

    def test_two_branches_that_found_the_same_claims_are_still_two_candidates(
        self, tmp_path: Path
    ) -> None:
        """Identical evidence, distinct identity — §6.4's exact rule."""
        bridge = branch_bridge(tmp_path)
        first, second = three_branches()[:2]
        same = succeeded(first)["evidence"]
        branches = [
            {**succeeded(first), "evidence": same},
            {**succeeded(second), "evidence": same},
        ]
        rb.observe_node(bridge, "lead", {"worker_branches": [first, second]})

        rb.observe_node(bridge, "workers", {"worker_branches": branches})

        candidates = of_type(bridge, "candidate.created")
        assert len({event.payload["candidate_id"] for event in candidates}) == 2

    def test_a_branch_with_no_evidence_completes_without_a_candidate(
        self, tmp_path: Path
    ) -> None:
        """An empty table is not a candidate. Nothing selects nothing."""
        bridge = branch_bridge(tmp_path)
        branch = planned("branch_w00", "an unanswerable question", 0)
        rb.observe_node(bridge, "lead", {"worker_branches": [branch]})

        rb.observe_node(
            bridge,
            "workers",
            {"worker_branches": [{**branch, "status": "succeeded"}]},
        )

        assert of_type(bridge, "candidate.created") == []
        assert of_type(bridge, "branch.completed")[0].payload["candidate_ids"] == []


class TestAFailedBranchIsPreservedRatherThanDropped:
    @pytest.mark.parametrize(
        ("status", "reason", "event_type", "field"),
        [
            ("failed", "not_found_papers", "branch.failed", "failure_class"),
            ("budget_stopped", "cost_budget_exceeded", "branch.failed", "failure_class"),
            ("cancelled", "cancelled", "branch.cancelled", "reason_code"),
        ],
    )
    def test_each_way_a_branch_can_end_reaches_the_record_typed(
        self,
        tmp_path: Path,
        status: str,
        reason: str,
        event_type: str,
        field: str,
    ) -> None:
        """RFC 10 §6.3: closure never deletes a branch's artifacts.

        A run that recorded only its successes would make the selector's
        oracle gap uncomputable — you cannot ask "would a better choice
        have existed" against a record that dropped the alternatives.
        """
        bridge = branch_bridge(tmp_path)
        branch = planned("branch_w00", "a question that failed", 0)
        rb.observe_node(bridge, "lead", {"worker_branches": [branch]})

        rb.observe_node(
            bridge,
            "workers",
            {"worker_branches": [settled(branch, status, reason)]},
        )

        closed = of_type(bridge, event_type)
        assert len(closed) == 1
        assert closed[0].branch_id == "branch_w00"
        assert closed[0].payload[field] == reason
        assert of_type(bridge, "branch.created")[0].payload["new_branch_id"] == (
            "branch_w00"
        )

    def test_a_mixed_run_records_the_survivors_and_the_casualties(
        self, tmp_path: Path
    ) -> None:
        bridge = branch_bridge(tmp_path)
        branches = three_branches()
        rb.observe_node(bridge, "lead", {"worker_branches": branches})

        rb.observe_node(
            bridge,
            "workers",
            {
                "worker_branches": [
                    succeeded(branches[0]),
                    settled(branches[1], "failed", "upstream_arxiv"),
                    succeeded(branches[2]),
                ]
            },
        )

        assert len(of_type(bridge, "branch.completed")) == 2
        assert len(of_type(bridge, "branch.failed")) == 1
        assert len(of_type(bridge, "candidate.created")) == 2


class TestTheRecordSurvivesTheGraphsRepetitions:
    def test_the_same_branch_seen_three_times_is_recorded_once(
        self, tmp_path: Path
    ) -> None:
        """`lead`, `workers` and `merge` all carry the branch records.

        Beyond tidiness: a closed branch rejects new work (§6.3), so a
        second `branch.completed` would be a *rejected* append, and the
        store would mark the bridge degraded for the rest of the run.
        """
        bridge = branch_bridge(tmp_path)
        branches = three_branches()
        done = [succeeded(branch) for branch in branches]
        trimmed = [{**branch, "evidence": []} for branch in done]

        rb.observe_node(bridge, "lead", {"worker_branches": branches})
        rb.observe_node(bridge, "workers", {"worker_branches": done})
        rb.observe_node(bridge, "merge", {"worker_branches": trimmed})

        assert len(of_type(bridge, "branch.created")) == 3
        assert len(of_type(bridge, "branch.completed")) == 3
        assert len(of_type(bridge, "candidate.created")) == 3
        assert bridge.degraded is False

    def test_a_repair_pass_adds_a_branch_beside_the_finished_ones(
        self, tmp_path: Path
    ) -> None:
        """The retrieval repair extends the branch set; ids stay unique."""
        bridge = branch_bridge(tmp_path)
        first = three_branches()[:1]
        done = [succeeded(first[0])]
        rb.observe_node(bridge, "lead", {"worker_branches": first})
        rb.observe_node(bridge, "workers", {"worker_branches": done})

        repair = planned("branch_r01", "quantisation error rates", 1)
        rb.observe_node(
            bridge, "lead", {"worker_branches": [*done, repair]}
        )
        rb.observe_node(
            bridge,
            "workers",
            {"worker_branches": [*done, succeeded(repair)]},
        )

        assert [
            event.payload["new_branch_id"] for event in of_type(bridge, "branch.created")
        ] == ["branch_w00", "branch_r01"]
        assert len(of_type(bridge, "branch.completed")) == 2
        assert bridge.degraded is False

    def test_the_chain_still_verifies_with_branches_in_it(
        self, tmp_path: Path
    ) -> None:
        """The integrity claim, over a trajectory that leaves the main branch."""
        bridge = branch_bridge(tmp_path)
        branches = three_branches()
        rb.observe_node(bridge, "lead", {"worker_branches": branches})
        rb.observe_node(
            bridge,
            "workers",
            {
                "worker_branches": [
                    succeeded(branches[0]),
                    settled(branches[1], "failed", "upstream_arxiv"),
                    succeeded(branches[2]),
                ]
            },
        )
        bridge.record_candidate("# Briefing\n\nmerged findings.")
        candidate = bridge._candidate_id
        artifact = bridge._final_artifact
        assert candidate is not None
        assert artifact is not None
        bridge.finalize(
            candidate_id=candidate, artifact=artifact, selection_basis="only_candidate"
        )
        bridge.close()

        verify_trajectory(import_jsonl(bridge.durable_jsonl()))
        assert bridge.degraded is False


class TestNothingElseMoved:
    def test_a_node_update_without_branches_records_no_branch_events(
        self, tmp_path: Path
    ) -> None:
        """The flag-off claim, at the hook rather than at the setting.

        Every shape but the orchestrated one carries no `worker_branches`
        key at all, so a run of the fixed pipeline pays one `.get` and
        appends exactly what W05 appended.
        """
        bridge = branch_bridge(tmp_path, nodes=("planner", "search", "critic"))
        before = len(bridge.events())

        rb.observe_node(bridge, "search", {"papers": [{"id": "p1"}]})

        assert of_type(bridge, "branch.created") == []
        assert len(bridge.events()) == before + 2, "the action pair, and nothing else"

    def test_a_model_call_stays_on_the_main_branch(self, tmp_path: Path) -> None:
        """The deliberate under-claim, asserted so it stays deliberate.

        The branch scope is a ContextVar and the reader records its
        model calls from fan-out threads, so a call cannot be stamped
        with a branch without risking the *wrong* branch. Each branch's
        own call count rides on its record instead — better a call
        attributed to the run than one attributed to a sibling.
        """
        bridge = branch_bridge(tmp_path)
        branches = three_branches()
        rb.observe_node(bridge, "lead", {"worker_branches": branches})
        rb.observe_node(
            bridge,
            "workers",
            {"worker_branches": [succeeded(branch) for branch in branches]},
        )

        assert all(
            event.branch_id == rb.MAIN_BRANCH_ID
            for event in bridge.events()
            if event.event_type.startswith(("action.", "model."))
        )
        assert succeeded(branches[0])["llm_calls"] == 1

    def test_a_malformed_branch_record_degrades_the_lineage_not_the_run(
        self, tmp_path: Path
    ) -> None:
        """State is state: a bad record must not fail the job it describes."""
        bridge = branch_bridge(tmp_path)

        rb.observe_node(
            bridge,
            "workers",
            {"worker_branches": [{"branch_id": "not a branch id", "status": "done"}]},
        )

        assert of_type(bridge, "branch.created") == []
        assert bridge.degraded is False

    def test_a_bridge_without_the_branch_vocabulary_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        """The eval lane's in-memory shadow predates branches (ADR 0078).

        It has no `record_branch`, so the hook looks the recorder up
        rather than calling it — a `ShadowRun` keeps recording exactly
        what W05 recorded and nothing raises.
        """

        class _ShadowOnly:
            degraded = False

            def node_completed(self, node: str, state_update: Any) -> None:
                self.seen = node

        shadow = _ShadowOnly()
        rb.observe_node(shadow, "workers", {"worker_branches": three_branches()})  # type: ignore[arg-type]

        assert shadow.seen == "workers"
