"""The shadow's hooks, exercised through the runners that carry them.

`tests/e2e/test_contract_shadow_research.py` proves the same claims
against the compiled graph and the real ASGI app. This module proves them
against stubs, and it exists for two reasons rather than one.

The first is the coverage gate, which runs `-m "not e2e"`: the hook
bodies in `src/api/runner.py` and `src/eval/runner.py` are the lines a
reviewer most wants covered — they are the ones that could change a job —
and a gate that never executed them would be measuring the wrong half of
the change.

The second is speed of failure. A stub workflow makes "the runner sealed
a manifest, recorded a node, and closed the trajectory with the job row"
a sub-second test, so the wiring breaks loudly long before the e2e tier
gets a chance to break slowly.
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
from src.contracts.trajectory import fold_trajectory
from src.eval import runner as eval_runner
from src.eval.benchmark_queries import BENCHMARK_QUERIES
from src.graph.state import initial_research_state
from src.observability.costs import (
    LlmCallObservation,
    bind_llm_call_observer,
    record_llm_call,
    reset_llm_call_observer,
    start_cost_tracking,
)

pytestmark = pytest.mark.integration

FIXED_PIPELINE = ("planner", "search", "reader", "synthesizer", "critic")


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _Edge:
    def __init__(self, source: str, target: str, conditional: bool = False) -> None:
        self.source = source
        self.target = target
        self.conditional = conditional


class _Graph:
    def __init__(self, names: list[str]) -> None:
        self.nodes = {name: object() for name in [*names, "__start__", "__end__"]}
        self.edges = [
            _Edge("__start__", names[0]),
            *(_Edge(a, b) for a, b in zip(names, names[1:], strict=False)),
            _Edge(names[-1], "__end__", conditional=True),
        ]


class _StubWorkflow:
    """A compiled app with the three surfaces `run_job` actually touches.

    `astream` yields one chunk per node, `aget_state` reports a finished
    run, and `get_graph` answers the classification. Nothing else about a
    compiled graph is used by the runner, so nothing else is stubbed.
    """

    def __init__(self, report: str = "# A report [Ji, 2023]\n") -> None:
        self._graph = _Graph(list(FIXED_PIPELINE))
        self._report = report
        self.final = dict(initial_research_state("seed", "stub-run"))
        self.final["draft_report"] = report
        self.final["iteration"] = 1
        self.final["quality_score"] = 0.88

    def get_graph(self) -> _Graph:
        return self._graph

    async def astream(self, _state: Any, config: Any = None) -> Any:
        for node in FIXED_PIPELINE:
            yield {node: {"stop_reason": "", "iteration": 1}}

    async def aget_state(self, _config: Any) -> Any:
        class _Snapshot:
            next: tuple[str, ...] = ()

            def __init__(self, values: dict[str, Any]) -> None:
                self.values = values

        return _Snapshot(dict(self.final))


class _FakeEvalApp:
    """A compiled-app stand-in for `_run_and_score`."""

    def __init__(self, report: str = "# A report [Ji, 2023]\n") -> None:
        self._graph = _Graph(list(FIXED_PIPELINE))
        self.state = dict(initial_research_state("seed", "eval-run"))
        self.state["draft_report"] = report

    def get_graph(self) -> _Graph:
        return self._graph

    def invoke(self, _initial: Any, config: Any = None) -> dict[str, Any]:
        return dict(self.state)


def config(**overrides: Any) -> Settings:
    base = {
        "use_mock_data": True,
        "enable_tracing": False,
        "enable_metrics": False,
        "enable_semantic_scholar": False,
        "enable_checkpointing": False,
        "enable_hitl": False,
        "job_store": "memory",
    }
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    bridge.reset_registry()
    yield
    bridge.reset_registry()


async def _drive(job: Job, workflow: _StubWorkflow) -> Job:
    store = InMemoryJobStore()
    await store.create(job)
    await runner_module.run_job(job, workflow, store, asyncio.Semaphore(1))
    return job


# ---------------------------------------------------------------------------
# The API runner
# ---------------------------------------------------------------------------


class TestTheRunnerHooks:
    async def test_a_job_run_with_the_switch_on_leaves_a_matching_trajectory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner_module, "settings", config(contract_shadow="shadow"))
        job = Job(job_id="stub-job-1", query="why do LLMs hallucinate?", hitl_bypass=True)

        await _drive(job, _StubWorkflow())

        # The product's outcome first, because that is the thing that
        # must not have moved.
        assert job.status is JobStatus.succeeded
        assert job.result is not None and job.result.startswith("# A report")
        assert job.iterations == 1

        run = bridge.shadow_run(job.job_id)
        assert run is not None
        assert run.degraded is False
        assert run.events()[0].event_type == "run.admitted"
        assert run.node_trajectory() == FIXED_PIPELINE
        fold = fold_trajectory(run.events())
        assert fold.terminal_event_type == "run.completed"
        assert fold.total_llm_calls == (job.llm_calls or 0)

    async def test_the_switch_off_records_nothing_and_binds_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The golden claim, at the runner's own boundary.

        Not merely "no events": the ContextVar is never set either, so
        `_persist_terminal` and `on_node` take their early return without
        ever reaching for a contract module.
        """
        monkeypatch.setattr(runner_module, "settings", config(contract_shadow="off"))
        job = Job(job_id="stub-job-off", query="why do LLMs hallucinate?", hitl_bypass=True)

        await _drive(job, _StubWorkflow())

        assert job.status is JobStatus.succeeded
        assert bridge.retained_run_ids() == ()
        assert runner_module._current_shadow.get() is None
        assert runner_module._shadow_bridge() is None

    async def test_a_failed_job_closes_its_trajectory_as_a_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner_module, "settings", config(contract_shadow="shadow"))

        class _Exploding(_StubWorkflow):
            async def astream(self, _state: Any, config: Any = None) -> Any:
                yield {"planner": {"iteration": 0}}
                raise RuntimeError("the graph broke")

        job = Job(job_id="stub-job-fail", query="a question", hitl_bypass=True)
        await _drive(job, _Exploding())

        assert job.status is JobStatus.failed
        assert job.error_type == "internal_unexpected"
        run = bridge.shadow_run(job.job_id)
        assert run is not None
        events = run.events()
        assert events[-1].event_type == "run.failed"
        assert events[-1].payload["failure_class"] == "internal_unexpected"
        assert run.node_trajectory() == ("planner",)

    async def test_a_broken_bridge_cannot_fail_the_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The containment claim, at the boundary that matters.

        Every hook is made to raise. The job must still succeed, with the
        same report, the same status and the same iteration count — which
        is the entire promise the word "shadow" is making.
        """
        monkeypatch.setattr(runner_module, "settings", config(contract_shadow="shadow"))

        def _boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("the bridge broke")

        class _BrokenBridge:
            start_research_job = staticmethod(_boom)
            observe_node = staticmethod(_boom)
            observe_job_terminal = staticmethod(_boom)

        monkeypatch.setattr(runner_module, "_shadow_bridge", lambda: _BrokenBridge())
        job = Job(job_id="stub-job-broken", query="a question", hitl_bypass=True)

        await _drive(job, _StubWorkflow())

        assert job.status is JobStatus.succeeded
        assert job.result is not None and job.result.startswith("# A report")
        assert job.iterations == 1
        assert bridge.retained_run_ids() == ()

    async def test_an_unimportable_bridge_degrades_to_no_shadow(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken contract package must not be able to fail a job."""
        import builtins

        monkeypatch.setattr(runner_module, "settings", config(contract_shadow="shadow"))
        real_import = builtins.__import__

        def _refuse(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "src.contracts" or name.startswith("src.contracts."):
                raise ImportError("contracts package is missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _refuse)
        assert runner_module._shadow_bridge() is None

    def test_the_review_hooks_no_op_without_a_shadow(self) -> None:
        """The two pause adapters read the ContextVar before anything else."""
        ctx = runner_module.PauseContext(
            app=None,
            config={},
            run_id="stub",
            workflow_state=None,
            job=None,
            store=None,
            pause_number=1,
        )
        assert runner_module._shadow_review_requested(ctx) is None
        assert runner_module._shadow_review_answered(ctx, "approve") is None

    def test_the_review_hooks_record_the_pause_when_a_shadow_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(runner_module, "settings", config(contract_shadow="shadow"))
        job = Job(job_id="stub-job-review", query="a question")
        run = bridge.start_research_job(
            job, _StubWorkflow(), config=runner_module.settings, cost_ceiling_usd=2.0
        )
        assert run is not None
        token = runner_module._current_shadow.set(run)

        class _Snapshot:
            next = ("search",)
            values: dict[str, Any] = {}

        ctx = runner_module.PauseContext(
            app=None,
            config={},
            run_id=job.job_id,
            workflow_state=_Snapshot(),
            job=job,
            store=None,
            pause_number=1,
        )
        try:
            runner_module._shadow_review_requested(ctx)
            runner_module._shadow_review_answered(ctx, "revise")
        finally:
            runner_module._current_shadow.reset(token)

        types = [event.event_type for event in run.events()]
        assert types[-3:] == ["checkpoint.saved", "hitl.requested", "hitl.responded"]
        assert run.events()[-3].payload["graph_position"] == "search"


# ---------------------------------------------------------------------------
# The eval runner
# ---------------------------------------------------------------------------


class TestTheEvalRunnerHooks:
    @staticmethod
    def _prepare(monkeypatch: pytest.MonkeyPatch, cfg: Settings) -> None:
        monkeypatch.setattr(eval_runner, "settings", cfg)
        monkeypatch.setattr(eval_runner, "build_workflow", lambda **_kw: _FakeEvalApp())
        monkeypatch.setattr(eval_runner, "_compute_metrics", lambda *_a, **_k: ({}, None))
        monkeypatch.setattr(eval_runner, "_claim_outcomes", lambda *_a, **_k: None)

    def test_the_record_gains_exactly_one_key_and_only_when_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._prepare(monkeypatch, config(contract_shadow="off"))
        record_off = eval_runner._run_and_score(BENCHMARK_QUERIES[0])

        self._prepare(monkeypatch, config(contract_shadow="shadow"))
        record_on = eval_runner._run_and_score(BENCHMARK_QUERIES[0])

        assert "contract_shadow" not in record_off
        assert set(record_on) - set(record_off) == {"contract_shadow"}
        block = record_on["contract_shadow"]
        assert block["arm_id"] == "A"
        assert block["terminal_event_type"] == "run.completed"
        assert len(block["trajectory_jsonl"].splitlines()) == block["event_count"]

    def test_an_errored_episode_still_carries_its_trajectory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed query is evidence, and its manifest is still sealed."""
        self._prepare(monkeypatch, config(contract_shadow="shadow"))

        class _Failing(_FakeEvalApp):
            def invoke(self, _initial: Any, config: Any = None) -> dict[str, Any]:
                raise RuntimeError("the graph broke")

        monkeypatch.setattr(eval_runner, "build_workflow", lambda **_kw: _Failing())
        record = eval_runner._run_and_score(BENCHMARK_QUERIES[0])

        assert record["error"] is not None
        block = record["contract_shadow"]
        assert block["terminal_event_type"] == "run.failed"

    def test_a_broken_bridge_leaves_the_record_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._prepare(monkeypatch, config(contract_shadow="shadow"))

        def _boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("the bridge broke")

        class _BrokenBridge:
            policy_shape_for_app = staticmethod(_boom)
            benchmark_binding_for = staticmethod(_boom)
            start_eval_episode = staticmethod(_boom)

        monkeypatch.setattr(eval_runner, "_shadow_bridge", lambda: _BrokenBridge())
        record = eval_runner._run_and_score(BENCHMARK_QUERIES[0])

        assert record["error"] is None
        assert "contract_shadow" not in record


# ---------------------------------------------------------------------------
# The cost seam
# ---------------------------------------------------------------------------


class TestTheModelCallObserver:
    def test_a_bound_observer_sees_the_call_the_accumulator_recorded(self) -> None:
        costs = start_cost_tracking()
        seen: list[LlmCallObservation] = []
        token = bind_llm_call_observer(seen.append)
        try:
            record_llm_call("claude-sonnet-4-6", 100, 20, latency_ms=12.0, retries=1)
        finally:
            reset_llm_call_observer(token)

        assert costs.call_count == 1
        assert len(seen) == 1
        assert seen[0].model == "claude-sonnet-4-6"
        assert seen[0].input_tokens == 100
        assert seen[0].output_tokens == 20
        assert seen[0].retries == 1
        assert seen[0].cost_usd > 0

    def test_an_observer_that_raises_costs_the_run_nothing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The call is already recorded; an observer is only a reader."""
        costs = start_cost_tracking()

        def _boom(_call: LlmCallObservation) -> None:
            raise RuntimeError("the recorder broke")

        token = bind_llm_call_observer(_boom)
        try:
            with caplog.at_level("WARNING", logger="src.observability.costs"):
                record_llm_call("claude-sonnet-4-6", 10, 5)
        finally:
            reset_llm_call_observer(token)

        assert costs.call_count == 1
        assert costs.total_cost_usd > 0
        assert [record.getMessage() for record in caplog.records] == [
            "llm_call_observer_failed"
        ]

    def test_unbinding_restores_the_previous_observer(self) -> None:
        start_cost_tracking()
        outer: list[LlmCallObservation] = []
        inner: list[LlmCallObservation] = []
        outer_token = bind_llm_call_observer(outer.append)
        try:
            inner_token = bind_llm_call_observer(inner.append)
            record_llm_call("claude-sonnet-4-6", 1, 1)
            reset_llm_call_observer(inner_token)
            record_llm_call("claude-sonnet-4-6", 1, 1)
        finally:
            reset_llm_call_observer(outer_token)

        assert len(inner) == 1
        assert len(outer) == 1


def test_the_runner_reaches_the_bridge_only_through_one_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`src/api/runner.py` names `src.contracts` in exactly one place.

    The golden test proves the module is not imported with the switch
    off; this proves there is only one place it *could* be, so a later
    edit cannot quietly add a second import that runs unconditionally.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path("src/api/runner.py").read_text(encoding="utf-8"))
    importers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("src.contracts")
    ]
    assert len(importers) == 1
    assert importers[0].col_offset > 0, "the one import must be inside a function"
