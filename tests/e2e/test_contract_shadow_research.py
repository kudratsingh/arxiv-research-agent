"""The contract shadow, against the graph and the runner it shadows.

The unit tiers prove the binding classifies a *described* graph and that
the bridge records a *described* run. This tier answers the two questions
only a real run can:

1. **With the switch off, is the product untouched?** Asserted
   structurally — no contract module reaches the import graph of the API
   runner or the eval runner — and behaviourally, on the eval record's
   own key set.
2. **With the switch on, does the trajectory describe the run that
   actually happened?** The node sequence recorded by the bridge is
   compared against the same `FIXED_PIPELINE` `test_research_workflow.py`
   already pins, the manifest is sealed before the first node, and the
   whole export round-trips through the contract's importer with its hash
   chain verified.

Zero spend, by construction and by assertion: the graph runs under the
tier's canned agent surface and the autouse ledger fails the test if a
model call happens anyway.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.contracts import shadow_bridge as bridge
from src.contracts.research_binding import (
    ARM_POLICY_IDS,
    ARM_REQUIRED_CAPABILITIES,
    arm_capability_gap,
    classify_policy_shape,
)
from src.contracts.trajectory import fold_trajectory, import_jsonl, verify_trajectory
from src.graph.state import initial_research_state
from src.graph.workflow import build_workflow
from src.observability.costs import RunCosts

pytestmark = pytest.mark.e2e

#: The fixed pipeline's shape, spelled out exactly as
#: `tests/e2e/test_research_workflow.py` spells it. Two files asserting
#: the same tuple is the point: the contract trajectory must reproduce
#: the sequence that test already pins, not a sequence of its own.
FIXED_PIPELINE = ("planner", "search", "reader", "synthesizer", "critic")

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    bridge.reset_registry()
    yield
    bridge.reset_registry()


def _closed(app: Any) -> None:
    stack = getattr(app, "_checkpointer_exit_stack", None)
    if stack is not None:
        stack.close()


# ---------------------------------------------------------------------------
# Golden: the switch off changes nothing
# ---------------------------------------------------------------------------


class TestTheSwitchOffIsInvisible:
    def test_no_contract_module_reaches_the_runners_import_graph(self) -> None:
        """`import src.api.runner` must not drag in `src.contracts`.

        A subprocess, because `sys.modules` in this session already holds
        whatever earlier tests imported and an in-process check would be
        vacuous — the same reason `tests/test_api_lazy_imports.py` runs
        its probes out of process.

        This is the structural half of the golden claim: with the switch
        off the hooks are not merely inert, the code they would call is
        not loaded.
        """
        probe = (
            "import sys; import src.api.runner; import src.eval.runner; "
            "print(sorted(m for m in sys.modules if m.startswith('src.contracts')))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=REPO_ROOT,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": "/tmp",
                "ANTHROPIC_API_KEY": "local-preview-disabled",
                "CONTRACT_SHADOW": "off",
                "USE_MOCK_DATA": "true",
            },
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "[]", result.stdout

    def test_the_eval_record_gains_exactly_one_key_and_only_when_on(
        self, monkeypatch: pytest.MonkeyPatch, install_settings: Callable[..., Any]
    ) -> None:
        """The eval runner's record is byte-identical with the switch off.

        Run the same query twice — once off, once on — against the same
        canned workflow, and compare the record's key set. Off must add
        nothing at all; on must add exactly `contract_shadow`, which is
        what makes the field additive rather than a schema change every
        stored campaign has to be re-read for.
        """
        from src.eval import runner as eval_runner
        from src.eval.benchmark_queries import BENCHMARK_QUERIES

        real_app = build_workflow(enable_hitl=False)
        try:
            final_state = dict(initial_research_state("seed", "run-1"))
            final_state["draft_report"] = "# A report [Ji, 2023]\n"

            class _CannedApp:
                """A compiled-graph stand-in with a real graph to classify."""

                def get_graph(self) -> Any:
                    return real_app.get_graph()

                def invoke(self, _initial: Any, config: Any = None) -> Any:
                    return final_state

            monkeypatch.setattr(eval_runner, "build_workflow", lambda **_kw: _CannedApp())
            monkeypatch.setattr(
                eval_runner, "_compute_metrics", lambda *_a, **_k: ({}, None)
            )
            monkeypatch.setattr(eval_runner, "_claim_outcomes", lambda *_a, **_k: None)

            off = install_settings(modules=("src.eval.runner",), contract_shadow="off")
            assert off.contract_shadow == "off"
            record_off = eval_runner._run_and_score(BENCHMARK_QUERIES[0])

            install_settings(modules=("src.eval.runner",), contract_shadow="shadow")
            record_on = eval_runner._run_and_score(BENCHMARK_QUERIES[0])
        finally:
            _closed(real_app)

        assert "contract_shadow" not in record_off
        assert set(record_on) - set(record_off) == {"contract_shadow"}
        block = record_on["contract_shadow"]
        assert block["terminal_event_type"] == "run.completed"
        assert block["arm_id"] == "A"
        assert block["total_llm_calls"] == 0
        # The benchmark case reached the manifest as a resolved origin.
        run = bridge.shadow_run(record_on["run_id"])
        assert run is not None
        origin = run.episode.task_spec.benchmark_origin
        assert origin is not None
        assert origin.task_case_ref.id == BENCHMARK_QUERIES[0]["query_id"]


# ---------------------------------------------------------------------------
# A canned run through the real graph
# ---------------------------------------------------------------------------


class TestACannedRunThroughTheRealGraph:
    def test_one_spec_one_manifest_and_the_trajectory_the_e2e_test_pins(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        zero_spend_ledger: RunCosts,
    ) -> None:
        cfg = install_settings(
            enable_checkpointing=False,
            enable_supervisor=False,
            contract_shadow="shadow",
        )
        research_llm_surface()

        from src.api.jobs import Job, JobStatus

        job = Job(job_id="e2e-shadow-1", query="why do LLMs hallucinate?", hitl_bypass=True)
        app = build_workflow(enable_hitl=False)
        try:
            run = bridge.start_research_job(
                job, app, config=cfg, cost_ceiling_usd=cfg.max_cost_usd
            )
            assert run is not None

            # Sealed before the first node: the trajectory's first event
            # already exists and already binds the manifest digest.
            assert run.events()[0].event_type == "run.admitted"
            sealed_before = run.episode.manifest_digest
            assert run.events()[0].manifest_digest == sealed_before

            final: dict[str, Any] = {}
            for chunk in app.stream(
                initial_research_state(job.query, job.job_id), stream_mode="updates"
            ):
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        continue
                    bridge.observe_node(run, str(node), update)
                    final.update(update)
        finally:
            _closed(app)

        job.status = JobStatus.succeeded
        job.result = str(final.get("draft_report") or "")
        job.llm_calls = 0
        job.cost_usd = 0.0
        bridge.observe_job_terminal(run, job)

        # One TaskSpec, compiled once and named by every event.
        assert {event.task_spec_id for event in run.events()} == {
            run.episode.task_spec.task_spec_id
        }
        # One manifest, unchanged by the run it describes.
        assert run.episode.manifest_digest == sealed_before

        # The trajectory the workflow test already pins, read back out of
        # the contract events rather than out of a list kept on the side.
        assert run.node_trajectory() == FIXED_PIPELINE

        fold = fold_trajectory(run.events())
        assert fold.terminal_event_type == "run.completed"
        assert fold.total_llm_calls == job.llm_calls == 0
        assert fold.total_estimated_cost_usd == "0.000000"

        # The export round-trips through the contract's own importer and
        # its hash chain verifies.
        events = import_jsonl(run.export_jsonl())
        verify_trajectory(events)
        assert [event.event_hash for event in events] == [
            event.event_hash for event in run.events()
        ]

        # Zero parity mismatches on the canned run, against the job row
        # and the graph's own final state.
        legacy = bridge.legacy_job_outcome(job)
        assert bridge.parity_report(run, legacy, final | {"query": job.query}) == ()

        assert zero_spend_ledger.call_count == 0

    def test_the_report_is_addressed_by_digest_and_never_carried(
        self,
        install_settings: Callable[..., Any],
        research_llm_surface: Callable[..., None],
        zero_spend_ledger: RunCosts,
    ) -> None:
        cfg = install_settings(
            enable_checkpointing=False, enable_supervisor=False, contract_shadow="shadow"
        )
        research_llm_surface()

        from src.api.jobs import Job, JobStatus

        job = Job(job_id="e2e-shadow-2", query="why do LLMs hallucinate?", hitl_bypass=True)
        app = build_workflow(enable_hitl=False)
        try:
            run = bridge.start_research_job(
                job, app, config=cfg, cost_ceiling_usd=cfg.max_cost_usd
            )
            assert run is not None
            final: dict[str, Any] = {}
            for chunk in app.stream(
                initial_research_state(job.query, job.job_id), stream_mode="updates"
            ):
                for node, update in chunk.items():
                    if node != "__interrupt__":
                        final.update(update)
        finally:
            _closed(app)

        job.status = JobStatus.succeeded
        job.result = str(final.get("draft_report") or "")
        assert job.result.strip(), "the fixture must produce a report to address"
        bridge.observe_job_terminal(run, job)

        exported = run.export_jsonl()
        assert job.result[:40] not in exported
        assert job.query not in exported

        produced = [
            event for event in run.events() if event.event_type == "final.artifact_produced"
        ]
        assert len(produced) == 1
        artifact = produced[0].artifact_refs[0]
        assert artifact.storage_uri.startswith("cas://sha256/")
        assert artifact.byte_length == len(job.result.encode("utf-8"))
        assert zero_spend_ledger.call_count == 0


# ---------------------------------------------------------------------------
# Arm identity against the compiled graph
# ---------------------------------------------------------------------------


class TestArmIdentityAgainstTheCompiledGraph:
    def test_every_buildable_arm_compiles_to_its_own_manifest(
        self, install_settings: Callable[..., Any]
    ) -> None:
        """The acceptance criterion, against graphs that were really built.

        `build_workflow` reads `research_policy`, `enable_supervisor` and
        `enable_verifier` at compile time, so each configuration below
        produces a genuinely different node set — which is what the
        classification reads. Four arms, four node sets, four policy ids,
        four manifest digests, and no model call anywhere.
        """
        seals = {}
        for arm, overrides in (
            ("A", {}),
            ("B", {"enable_evidence_store": True}),
            (
                "C",
                {
                    "research_policy": "fixed_verify_repair",
                    "enable_evidence_store": True,
                },
            ),
            (
                "D",
                {
                    "enable_supervisor": True,
                    "enable_evidence_store": True,
                    "enable_verifier": True,
                },
            ),
        ):
            cfg = install_settings(
                enable_checkpointing=False, contract_shadow="shadow", **overrides
            )
            app = build_workflow(enable_hitl=False)
            try:
                from src.contracts.research_binding import (
                    compile_research_intake,
                    seal_research_episode,
                )

                shape = classify_policy_shape(cfg, app)
                spec = compile_research_intake(
                    cfg,
                    task_id=f"research-api:arm-{arm}",
                    query="a shared question",
                    hitl_plan_review=False,
                    supervisor=shape.runtime_flags.enable_supervisor,
                )
                seals[arm] = seal_research_episode(
                    cfg,
                    shape=shape,
                    spec=spec,
                    origin="research_api",
                    runtime_run_id=f"arm-{arm}",
                    hitl_bypass=True,
                    hitl_bypass_reason="unattended-evaluation",
                )
            finally:
                _closed(app)

        assert [seals[arm].shape.arm_id for arm in "ABCD"] == ["A", "B", "C", "D"]
        assert [seals[arm].shape.policy_id for arm in "ABCD"] == [
            ARM_POLICY_IDS[arm] for arm in "ABCD"
        ]
        assert len({seals[arm].manifest_digest for arm in "ABCD"}) == 4
        assert "verifier" in seals["D"].shape.graph.nodes
        assert "verifier" not in seals["A"].shape.graph.nodes

        # Arm C is earned by CAP-02's compiled stage, and by nothing else:
        # its graph carries both halves, and arm A's and B's carry neither.
        assert {"verify", "repair"} <= set(seals["C"].shape.graph.nodes)
        assert {"verify", "repair"}.isdisjoint(seals["B"].shape.graph.nodes)
        assert seals["C"].policy.capabilities.fixed_post_synthesis_verifier is True
        assert seals["B"].policy.capabilities.fixed_post_synthesis_verifier is False
        assert arm_capability_gap("C", seals["C"].shape) == ()
        assert arm_capability_gap("C", seals["B"].shape) == ARM_REQUIRED_CAPABILITIES["C"]

        # Arm E stays out of reach in every one of them: nothing here
        # routes a compute tier, branches a candidate, or decides a stop.
        for arm in "ABCD":
            assert arm_capability_gap("E", seals[arm].shape) == (
                ARM_REQUIRED_CAPABILITIES["E"]
            )
            assert seals[arm].policy.capabilities.adaptive_compute is False

    def test_the_verifier_flag_adds_no_node_to_the_fixed_graph(
        self, install_settings: Callable[..., Any]
    ) -> None:
        """The C impostor, proved against the graph rather than argued.

        `ENABLE_VERIFIER=true` under the fixed pipeline compiles the same
        five nodes it always did, so the run is arm A — and arm C stays
        out of reach because the graph has no fixed post-synthesis
        verifier to reach for.
        """
        cfg = install_settings(
            enable_checkpointing=False,
            enable_supervisor=False,
            enable_verifier=True,
            contract_shadow="shadow",
        )
        app = build_workflow(enable_hitl=False)
        try:
            shape = classify_policy_shape(cfg, app)
        finally:
            _closed(app)

        assert shape.graph.nodes == tuple(sorted(FIXED_PIPELINE))
        assert shape.arm_id == "A"
        assert shape.runtime_flags.enable_verifier is False
        assert shape.declared_research_policy == "legacy"
        # The whole point: the flag buys none of arm C's capabilities,
        # because none of them is a flag.
        assert arm_capability_gap("C", shape) == ARM_REQUIRED_CAPABILITIES["C"]
        assert arm_capability_gap("E", shape) == ARM_REQUIRED_CAPABILITIES["E"]

    def test_the_refiner_changes_the_graph_and_not_the_arm(
        self, install_settings: Callable[..., Any]
    ) -> None:
        shapes = []
        for refiner in (False, True):
            cfg = install_settings(
                enable_checkpointing=False,
                enable_supervisor=True,
                enable_evidence_store=True,
                enable_verifier=True,
                enable_query_refiner=refiner,
                contract_shadow="shadow",
            )
            app = build_workflow(enable_hitl=False)
            try:
                shapes.append(classify_policy_shape(cfg, app))
            finally:
                _closed(app)

        plain, refined = shapes
        assert plain.arm_id == refined.arm_id == "D"
        assert plain.policy_id == refined.policy_id
        assert "query_refiner" not in plain.graph.nodes
        assert "query_refiner" in refined.graph.nodes
        assert plain.graph.digest != refined.graph.digest
        assert plain.policy_digest != refined.policy_digest


# ---------------------------------------------------------------------------
# The API runner's own hooks
# ---------------------------------------------------------------------------

PLANNER_RESPONSE = {
    "sub_questions": ["What causes hallucination?"],
    "search_queries": ["LLM hallucination survey"],
}
READER_RESPONSE = {
    "key_findings": ["RAG grounds generations in retrieved text."],
    "methodology": "Survey.",
    "results_summary": "Retrieval reduces factual errors.",
    "limitations": "Abstract-only analysis.",
    "relevance": 0.9,
}
SYNTHESIZER_RESPONSE = {
    "draft_report": "# Hallucination\n\nGrounded output [Ji, 2023].\n",
    "citations": [
        {
            "paper_id": "http://arxiv.org/abs/2311.09000",
            "title": "A Survey on Hallucination",
            "authors": ["Ziwei Ji"],
            "year": 2023,
            "url": "http://arxiv.org/abs/2311.09000",
        }
    ],
}
CRITIC_RESPONSE = {
    "scores": {
        "completeness": 0.9,
        "accuracy": 0.9,
        "coherence": 0.9,
        "depth": 0.8,
        "balance": 0.9,
    },
    "average_score": 0.88,
    "critique": "Solid.",
    "revision_needed": False,
    "revision_target": "none",
}


class TestTheRunnerHooksFireOnARealJob:
    async def test_an_http_job_succeeds_and_leaves_a_matching_trajectory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The whole wiring: HTTP submit, real graph, real runner, shadow on.

        The job must succeed exactly as `tests/test_api_smoke_e2e.py`
        already asserts it does — same status, same quality score, same
        one iteration — *and* the runner's five hooks must have produced a
        trajectory whose terminal event matches the row.
        """
        from src.config import Settings
        from src.config import settings as shipped

        for module, response in (
            ("planner", PLANNER_RESPONSE),
            ("reader", READER_RESPONSE),
            ("synthesizer", SYNTHESIZER_RESPONSE),
            ("critic", CRITIC_RESPONSE),
        ):
            monkeypatch.setattr(
                f"src.agents.{module}.call_llm_json",
                lambda *_a, _payload=response, **_k: dict(_payload),
            )
        monkeypatch.setattr("src.agents.reader.parse_pdf", lambda url: "")
        monkeypatch.setattr(
            "src.agents.search.rank_papers_by_relevance",
            lambda query, papers, top_k: list(papers)[:top_k],
        )

        overrides = {
            "use_mock_data": True,
            "enable_checkpointing": True,
            "checkpoint_backend": "sqlite",
            "checkpoint_db_path": str(tmp_path / "shadow-checkpoints.sqlite"),
            "enable_hitl": True,
            "enable_semantic_scholar": False,
            "enable_tracing": False,
            "contract_shadow": "shadow",
        }
        patched = shipped.model_copy(update=overrides)
        assert isinstance(patched, Settings)
        for module in (
            "src.graph.workflow",
            "src.api.runner",
            "src.api.app",
            "src.api.routes",
            "src.agents.search",
            "src.agents.reader",
            "src.agents.planner",
            "src.agents.synthesizer",
            "src.agents.critic",
        ):
            monkeypatch.setattr(f"{module}.settings", patched)

        from src.api.app import create_app

        app = create_app()
        async with (
            LifespanManager(app, startup_timeout=30),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            submit = await client.post(
                "/research",
                json={"query": "why do LLMs hallucinate?", "hitl_bypass": True},
            )
            assert submit.status_code == 202, submit.text
            job_id = submit.json()["job_id"]

            deadline = asyncio.get_event_loop().time() + 30.0
            body: dict[str, Any] = {}
            while asyncio.get_event_loop().time() < deadline:
                response = await client.get(f"/research/{job_id}")
                assert response.status_code == 200
                body = response.json()
                if body["status"] in ("succeeded", "failed", "cancelled"):
                    break
                await asyncio.sleep(0.05)

        # The product's own outcome, unchanged by the shadow.
        assert body.get("status") == "succeeded", body
        assert body["result"]
        assert body["quality_score"] == pytest.approx(0.88)
        assert body["iterations"] == 1

        # And the shadow that ran beside it.
        run = bridge.shadow_run(job_id)
        assert run is not None
        assert run.degraded is False
        assert run.node_trajectory() == FIXED_PIPELINE
        fold = fold_trajectory(run.events())
        assert fold.terminal_event_type == "run.completed"
        assert fold.total_llm_calls == (body["llm_calls"] or 0)
        assert run.events()[0].event_type == "run.admitted"
        verify_trajectory(import_jsonl(run.export_jsonl()))
