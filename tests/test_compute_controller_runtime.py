"""The runner's half of the controller: selection, binding, and the record.

`tests/test_compute_controller.py` proves the two graphs get compiled and
`tests/test_compute_policy.py` proves the tier gets chosen. What is left
is the join, and it lives in `src/api/runner.py`: the job picks one of
the compiled shapes *before* the contract shadow classifies it, binds its
tier for the length of the run, and records the allocation as the
trajectory's first policy event.

Stubs rather than a compiled graph, for the two reasons
`tests/test_contract_shadow_runtime.py` gives: the coverage gate runs
`-m "not e2e"` and these hook bodies are exactly the lines a reviewer
wants covered, and a stub makes "the runner selected the wrong graph" a
sub-second failure. The same claims are re-asserted against real graphs
and real agents in `tests/e2e/test_compute_controller.py`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.api import runner as runner_module
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts import shadow_bridge as bridge
from src.observability import costs as costs_module
from src.observability.costs import current_costs
from src.policies.compute import active_compute_tier

pytestmark = pytest.mark.integration

FIXED_PIPELINE = ("planner", "search", "reader", "synthesizer", "critic")

#: Arm C's node set. `repair` is in it because
#: `src/contracts/research_binding.py` earns the verify-and-repair
#: capability from *both* nodes — a stub carrying only `verify` would
#: classify as the fixed pipeline and quietly make this file agree with
#: itself for the wrong reason.
VERIFY_REPAIR = (
    "planner",
    "search",
    "reader",
    "synthesizer",
    "verify",
    "repair",
    "critic",
)

#: A query nothing escalates: short, one entity, no cue.
QUIET_QUERY = "how do transformers work"

#: A query the table escalates twice over — a comparison word and two
#: named systems — so a test that expects T1 is not resting on one rule.
LOUD_QUERY = "compare GPT-4 and BERT"


class _Edge:
    def __init__(self, source: str, target: str, conditional: bool = False) -> None:
        self.source = source
        self.target = target
        self.conditional = conditional


class _Graph:
    def __init__(self, names: tuple[str, ...]) -> None:
        self.nodes = {name: object() for name in [*names, "__start__", "__end__"]}
        self.edges = [
            _Edge("__start__", names[0]),
            *(_Edge(a, b) for a, b in zip(names, names[1:], strict=False)),
            _Edge(names[-1], "__end__", conditional=True),
        ]


class _StubGraph:
    """The three surfaces `run_job` touches, and a name for assertions.

    `spend` and `hang` exist so the two control paths every job shares —
    the cost ceiling and cancellation — can be driven on either tier
    without a second stub class per behaviour.
    """

    def __init__(
        self,
        tier: str,
        nodes: tuple[str, ...],
        *,
        spend: float = 0.0,
        hang: bool = False,
    ) -> None:
        self.tier = tier
        self.nodes = nodes
        self.visited: list[str] = []
        self._graph = _Graph(nodes)
        self._spend = spend
        self._hang = hang
        self.tier_at_first_node: str | None = None

    def get_graph(self) -> _Graph:
        return self._graph

    async def astream(self, _state: Any, config: Any = None) -> Any:
        if self._spend:
            costs = current_costs()
            assert costs is not None, "run_job must start cost tracking"
            costs.record(
                "claude-sonnet-4-6",
                input_tokens=1_000_000,
                output_tokens=0,
                cost_usd=self._spend,
            )
        for node in self.nodes:
            if not self.visited:
                # Read inside the run, which is the only place the
                # answer means anything: the tier has to be bound for
                # the graph's nodes, not merely around `run_job`.
                self.tier_at_first_node = active_compute_tier()
            self.visited.append(node)
            yield {node: {"stop_reason": "", "iteration": 1}}
            if self._hang:
                await asyncio.sleep(60)

    async def aget_state(self, _config: Any) -> Any:
        class _Snapshot:
            next: tuple[str, ...] = ()

            def __init__(self, values: dict[str, Any]) -> None:
                self.values = values

        from src.graph.state import initial_research_state

        values = dict(initial_research_state("seed", "stub-run"))
        values["draft_report"] = "# A report [Ji, 2023]\n"
        values["iteration"] = 1
        return _Snapshot(values)


def _tiered(**kwargs: Any) -> tuple[_StubGraph, dict[str, _StubGraph]]:
    """A primary graph carrying the mapping `build_workflow` attaches."""
    t0 = _StubGraph("T0", FIXED_PIPELINE, **kwargs)
    t1 = _StubGraph("T1", VERIFY_REPAIR, **kwargs)
    graphs = {"T0": t0, "T1": t1}
    t0._compute_tier_graphs = graphs  # type: ignore[attr-defined]
    return t0, graphs


def _drain(job: Job) -> list[dict[str, Any]]:
    """Every SSE frame the runner queued for this job, in order."""
    frames: list[dict[str, Any]] = []
    while not job.event_queue.empty():
        frames.append(job.event_queue.get_nowait())
    return frames


def config(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "use_mock_data": True,
        "enable_tracing": False,
        "enable_metrics": False,
        "enable_semantic_scholar": False,
        "enable_checkpointing": False,
        "enable_hitl": False,
        "job_store": "memory",
        # The controller's recommended configuration (ADR 0085): with
        # the evidence store on, T0 is arm B and T1 is arm C, which is
        # what makes the policy-id assertions below meaningful.
        "enable_evidence_store": True,
    }
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    bridge.reset_registry()
    yield
    bridge.reset_registry()


async def _drive(job: Job, workflow: Any) -> Job:
    store = InMemoryJobStore()
    await store.create(job)
    await runner_module.run_job(job, workflow, store, asyncio.Semaphore(1))
    return job


def _job(query: str, job_id: str = "cap04-job") -> Job:
    return Job(job_id=job_id, query=query, hitl_bypass=True)


class TestTheRunnerSelectsTheTiersGraph:
    async def test_with_the_controller_off_the_handed_graph_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default: the runner uses what the caller gave it.

        Asserted with a *loud* query, so a controller that had quietly
        stayed on would escalate and be caught.
        """
        monkeypatch.setattr(runner_module, "settings", config())
        primary, graphs = _tiered()

        await _drive(_job(LOUD_QUERY), primary)

        assert primary.visited == list(FIXED_PIPELINE)
        assert graphs["T1"].visited == []
        assert primary.tier_at_first_node is None

    async def test_a_quiet_query_runs_the_fixed_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module, "settings", config(compute_controller="deterministic")
        )
        primary, graphs = _tiered()

        job = await _drive(_job(QUIET_QUERY), primary)

        assert job.status is JobStatus.succeeded
        assert graphs["T0"].visited == list(FIXED_PIPELINE)
        assert graphs["T1"].visited == []
        assert "verify" not in graphs["T0"].visited

    async def test_an_escalated_query_runs_the_verify_and_repair_graph(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module, "settings", config(compute_controller="deterministic")
        )
        primary, graphs = _tiered()

        job = await _drive(_job(LOUD_QUERY), primary)

        assert job.status is JobStatus.succeeded
        assert graphs["T1"].visited == list(VERIFY_REPAIR)
        assert graphs["T0"].visited == []

    async def test_both_tiers_run_in_one_process_off_one_compiled_pair(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The deliverable, stated as one test.

        Two jobs, one compiled pair, two different shapes — which is the
        thing `research_policy` could not do, because it selects the
        shape once at settings load.
        """
        monkeypatch.setattr(
            runner_module, "settings", config(compute_controller="deterministic")
        )
        primary, graphs = _tiered()

        await _drive(_job(QUIET_QUERY, "quiet"), primary)
        await _drive(_job(LOUD_QUERY, "loud"), primary)

        assert graphs["T0"].visited == list(FIXED_PIPELINE)
        assert graphs["T1"].visited == list(VERIFY_REPAIR)

    async def test_a_session_job_is_never_tiered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A guided session drives its own graph, which has no tiers."""
        monkeypatch.setattr(
            runner_module, "settings", config(compute_controller="deterministic")
        )
        primary, graphs = _tiered()
        job = Job(job_id="session-1", query=LOUD_QUERY, kind="session")

        await _drive(job, primary)

        assert graphs["T1"].visited == []
        assert primary.tier_at_first_node is None


class TestTheTierIsBoundForTheRun:
    async def test_the_tier_is_visible_inside_the_graph_and_gone_after(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The binding has to outlive the call and not the job.

        Inside the run it is what lets `Settings.effort_for` raise one
        agent's effort; after it, a leaked tier would silently re-price
        the next unrelated run in the same context — the same failure
        ADR 0047 closed for the cancel token.
        """
        monkeypatch.setattr(
            runner_module, "settings", config(compute_controller="deterministic")
        )
        primary, graphs = _tiered()

        await _drive(_job(LOUD_QUERY), primary)

        assert graphs["T1"].tier_at_first_node == "T1"
        assert active_compute_tier() is None

    async def test_a_quiet_run_binds_t0(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module, "settings", config(compute_controller="deterministic")
        )
        primary, graphs = _tiered()

        await _drive(_job(QUIET_QUERY), primary)

        assert graphs["T0"].tier_at_first_node == "T0"


class TestTheTrajectoryCarriesTheDecision:
    async def test_the_allocation_is_the_first_policy_event_of_the_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module,
            "settings",
            config(compute_controller="deterministic", contract_shadow="shadow"),
        )
        primary, _ = _tiered()
        job = _job(LOUD_QUERY, "cap04-trajectory")

        await _drive(job, primary)

        run = bridge.shadow_run(job.job_id)
        assert run is not None and run.degraded is False
        events = [e for e in run.events() if e.event_type == "compute.tier_selected"]
        assert len(events) == 1
        payload = events[0].payload
        assert payload["tier"] == "T1"
        assert payload["eligible_tiers"] == ["T0", "T1"]
        assert payload["reason_codes"] == ["comparative_cue", "multi_entity"]
        assert str(payload["feature_snapshot_ref"]).startswith("sha256:")
        assert payload["tier_budget_ref"] == (
            "tier-budget:T1:verifications=2:repairs=1"
        )
        assert events[0].actor.kind.value == "policy"
        assert events[0].actor.name == "compute_controller"
        # Before the first node, so the record reads as a decision that
        # caused the run rather than one observed during it.
        types = [e.event_type for e in run.events()]
        assert types.index("compute.tier_selected") < types.index("action.started")

    async def test_the_snapshot_reference_carries_no_query_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RFC 10 §8.6's payload is a reference, and this is why.

        An API research job carries `product_operation_only` consent, so
        nothing about it may retain content while D8 is open (ADR 0083).
        A digest identifies the snapshot without being one.
        """
        monkeypatch.setattr(
            runner_module,
            "settings",
            config(compute_controller="deterministic", contract_shadow="shadow"),
        )
        primary, _ = _tiered()
        job = _job("compare GPT-4 and BERT on Napoleonic history", "cap04-noleak")

        await _drive(job, primary)

        run = bridge.shadow_run(job.job_id)
        assert run is not None
        exported = run.export_jsonl()
        assert "Napoleonic" not in exported

    async def test_the_manifest_policy_id_is_the_graph_the_job_ran(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The deliverable W05 depends on, asserted through the runner.

        The runner never names a policy id. It selects a graph, and the
        binding reads the shape it was handed — so an escalated job's
        sealed episode says arm C because arm C's graph is what ran.
        """
        monkeypatch.setattr(
            runner_module,
            "settings",
            config(compute_controller="deterministic", contract_shadow="shadow"),
        )
        primary, _ = _tiered()

        quiet = _job(QUIET_QUERY, "cap04-quiet")
        loud = _job(LOUD_QUERY, "cap04-loud")
        await _drive(quiet, primary)
        await _drive(loud, primary)

        quiet_run = bridge.shadow_run(quiet.job_id)
        loud_run = bridge.shadow_run(loud.job_id)
        assert quiet_run is not None and loud_run is not None
        assert quiet_run.events()[0].policy_ref.policy_id == "research_fixed_evidence"
        assert (
            loud_run.events()[0].policy_ref.policy_id == "research_fixed_verify_repair"
        )

    async def test_no_compute_event_is_recorded_with_the_controller_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The golden claim, on the trajectory rather than on the graph."""
        monkeypatch.setattr(
            runner_module, "settings", config(contract_shadow="shadow")
        )
        primary, _ = _tiered()
        job = _job(LOUD_QUERY, "cap04-off")

        await _drive(job, primary)

        run = bridge.shadow_run(job.job_id)
        assert run is not None
        assert all(
            event.event_type != "compute.tier_selected" for event in run.events()
        )

    async def test_a_broken_bridge_does_not_fail_the_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Containment, in the same shape as every other shadow hook.

        The decision is a diagnostic. A bridge that raises while
        recording it must cost the record and never the run — which is
        `observe_compute_tier`'s `contained(...)` block, exercised here
        by breaking the method underneath it.
        """
        from src.contracts.runtime_bridge import ResearchRuntimeBridge

        monkeypatch.setattr(
            runner_module,
            "settings",
            config(compute_controller="deterministic", contract_shadow="shadow"),
        )

        def _raise(*_a: Any, **_kw: Any) -> None:
            raise RuntimeError("bridge is unwell")

        monkeypatch.setattr(
            ResearchRuntimeBridge, "compute_tier_selected", _raise, raising=True
        )
        primary, graphs = _tiered()
        job = _job(LOUD_QUERY, "cap04-broken")

        await _drive(job, primary)

        assert job.status is JobStatus.succeeded
        assert graphs["T1"].visited == list(VERIFY_REPAIR)
        run = bridge.shadow_run(job.job_id)
        assert run is not None
        assert all(
            event.event_type != "compute.tier_selected" for event in run.events()
        )


class TestTheControlPathsAreTheSameOnBothTiers:
    """Cancellation and the cost ceiling are properties of the *runner*.

    That is the claim this section defends. Selecting a second graph
    could have moved either of them — a graph chosen after the cancel
    token was bound, or reached by a second driver, would have its own
    story about what happens when a job is stopped or runs out of money.
    Neither happens here because the selection is one reassignment at
    the top of `run_job` and everything downstream of it is unchanged,
    and the way to keep that true is to assert it on both tiers.
    """

    @pytest.fixture(autouse=True)
    def _no_leaked_accumulator(self) -> Any:
        """Leave the cost ContextVar unbound for the next test.

        Same reason `tests/test_runner_cost_cap.py` does it: an armed
        accumulator surviving a test changes `call_llm`'s behaviour
        everywhere after it.
        """
        token = costs_module._current_costs.set(None)
        try:
            yield
        finally:
            costs_module._current_costs.reset(token)

    @pytest.mark.parametrize(
        "query,tier", [(QUIET_QUERY, "T0"), (LOUD_QUERY, "T1")], ids=["T0", "T1"]
    )
    async def test_the_cost_ceiling_stops_a_run_on_either_tier(
        self, monkeypatch: pytest.MonkeyPatch, query: str, tier: str
    ) -> None:
        monkeypatch.setattr(
            runner_module,
            "settings",
            config(compute_controller="deterministic", max_cost_usd=2.0),
        )
        primary, graphs = _tiered(spend=3.0)

        job = await _drive(_job(query, f"cap04-cost-{tier}"), primary)

        assert job.status is JobStatus.failed
        assert job.error_type == "cost_budget_exceeded"
        assert job.cost_usd == pytest.approx(3.0)
        # The ceiling fired on the tier's own graph, not on the primary
        # by accident.
        assert graphs[tier].visited[:1] == [graphs[tier].nodes[0]]

    @pytest.mark.parametrize(
        "query,tier", [(QUIET_QUERY, "T0"), (LOUD_QUERY, "T1")], ids=["T0", "T1"]
    )
    async def test_a_cancelled_task_ends_a_run_on_either_tier(
        self, monkeypatch: pytest.MonkeyPatch, query: str, tier: str
    ) -> None:
        monkeypatch.setattr(
            runner_module, "settings", config(compute_controller="deterministic")
        )
        primary, _ = _tiered(hang=True)
        job = _job(query, f"cap04-cancel-{tier}")
        store = InMemoryJobStore()
        await store.create(job)

        task = asyncio.create_task(
            runner_module.run_job(job, primary, store, asyncio.Semaphore(1))
        )
        # One loop turn is enough for the first node to be yielded and
        # the stub to park on its sleep.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=10)

        assert job.status is JobStatus.cancelled

    @pytest.mark.parametrize(
        "query,tier", [(QUIET_QUERY, "T0"), (LOUD_QUERY, "T1")], ids=["T0", "T1"]
    )
    async def test_the_sse_frames_are_unchanged_on_either_tier(
        self, monkeypatch: pytest.MonkeyPatch, query: str, tier: str
    ) -> None:
        """Deliverable 5's other half: the decision is *not* in SSE.

        `node_completed`'s payload is two keys, and adding a third
        would change a frame shape `tests/test_contract_sse_events.py`
        pins byte-for-byte. So the allocation goes to the trajectory and
        nowhere else, and this asserts the frames stayed where they
        were — on the escalated tier as well as the quiet one, where the
        extra `verify` node makes one more frame and no new key.
        """
        monkeypatch.setattr(
            runner_module, "settings", config(compute_controller="deterministic")
        )
        primary, graphs = _tiered()

        job = await _drive(_job(query, f"cap04-sse-{tier}"), primary)

        frames = _drain(job)
        assert [frame["event"] for frame in frames] == [
            "job_started",
            *["node_completed"] * len(graphs[tier].nodes),
            "job_completed",
        ]
        node_frames = [f for f in frames if f["event"] == "node_completed"]
        assert all(set(f["data"]) == {"node", "state_delta"} for f in node_frames)
        assert [f["data"]["node"] for f in node_frames] == list(graphs[tier].nodes)
        assert all(
            "tier" not in f["data"]["state_delta"] for f in node_frames
        )
