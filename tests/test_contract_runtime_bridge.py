"""No-cost qualification for the runtime event bridge (P0-WO08, ADR 0083).

Two synthetic episodes carry most of the weight here — one research, one
guided-learning — and the assertion about both is the same: everything a
reader needs to know what the policy decided and what it produced can be
rebuilt from the durable JSONL *alone*, with its hash chain verified and
no access to the process that wrote it. That is what "reconstructs at the
decision/artifact level" means, and `DECISION_EVENT_TYPES` is the written
definition it is asserted against.

The rest is the boundary conditions that make the ledger worth trusting:
an accepted event survives a broken projection, a resume does not mint a
second copy of an action or reset the cost fold, a run whose consent is
`product_operation_only` never reaches a file, no v1 event is training
eligible, and the SSE frames the browser already consumes are unchanged
byte for byte.

Zero network, zero provider, zero model. The graph is a stand-in that
answers `get_graph()`; the store is a directory under `tmp_path`.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from opentelemetry import trace as ot_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from src.api.jobs import Job, JobStatus
from src.api.runner import terminal_event_data
from src.api.streaming import (
    CANONICAL_EVENT_PROJECTION,
    HITL_EVENT_PROJECTION,
    format_sse,
    sse_event_name_for,
)
from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts import runtime_bridge as rb
from src.contracts.artifact_store import ArtifactAccessDenied
from src.contracts.kernel import DataClass
from src.contracts.research_binding import (
    classify_from_graph_shape,
    compile_research_intake,
    read_graph_shape,
    seal_research_episode,
)
from src.contracts.trajectory import (
    ArtifactRole,
    ConsentScope,
    UsageDelta,
    fold_trajectory,
    import_jsonl,
    verify_trajectory,
)
from src.observability import tracing as tracing_module

pytestmark = [pytest.mark.unit, pytest.mark.contract]

FIXED_PIPELINE = ("planner", "search", "reader", "synthesizer", "critic")
SYNTHETIC_PRINCIPAL = "synthetic:research-eval"
LEARNER_PRINCIPAL = "synthetic:learning-eval"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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

    def __init__(self, nodes: tuple[str, ...] = FIXED_PIPELINE) -> None:
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
    base = {
        "use_mock_data": True,
        "enable_tracing": False,
        "enable_metrics": False,
        "enable_semantic_scholar": False,
        "enable_checkpointing": False,
        "contract_shadow": "shadow",
        "contract_event_capture": "evaluation_only",
    }
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


def sealed_episode(
    cfg: Settings, *, origin: str = "research_eval", run_id: str = "episode-1"
) -> Any:
    shape = classify_from_graph_shape(cfg, read_graph_shape(_AppStub()))
    spec = compile_research_intake(
        cfg,
        task_id=f"research-eval:{run_id}",
        query="why do LLMs hallucinate?",
        hitl_plan_review=False,
        supervisor=False,
    )
    return seal_research_episode(
        cfg,
        shape=shape,
        spec=spec,
        origin=origin,  # type: ignore[arg-type]
        runtime_run_id=run_id,
        hitl_bypass=True,
        hitl_bypass_reason="unattended-evaluation",
    )


def research_bridge(
    tmp_path: Path,
    cfg: Settings | None = None,
    *,
    origin: str = "research_eval",
    run_id: str = "episode-1",
) -> rb.ResearchRuntimeBridge:
    resolved = cfg or config()
    return rb.start_research_run(
        resolved,
        episode=sealed_episode(resolved, origin=origin, run_id=run_id),
        runtime_run_id=run_id,
        principal_key_id=(
            SYNTHETIC_PRINCIPAL if origin != "research_api" else "pk_abcdefghij"
        ),
        cost_ceiling_usd=2.0,
        sink_root=tmp_path / "sink",
    )


def learning_spec(cfg: Settings) -> Any:
    return rb.compile_guided_session_intake(
        cfg,
        task_id="guided-learn:session-1",
        path_id="transformers",
        resource_id="attention-is-all-you-need",
        title="Attention Is All You Need",
        available_minutes=30,
        content_entry_digest="sha256:" + "b" * 64,
        learner_profile_digest="sha256:" + "c" * 64,
    )


def learning_bridge(
    tmp_path: Path, cfg: Settings | None = None, *, synthetic: bool = True
) -> rb.GuidedLearningBridge:
    resolved = cfg or config()
    return rb.start_guided_session(
        resolved,
        spec=learning_spec(resolved),
        graph_digest="sha256:" + "d" * 64,
        runtime_run_id="session-1",
        principal_key_id=LEARNER_PRINCIPAL if synthetic else "pk_learnerlearner",
        cost_ceiling_usd=0.5,
        synthetic=synthetic,
        sink_root=tmp_path / "sink",
    )


def drive_research_episode(bridge: rb.ResearchRuntimeBridge) -> None:
    """One complete Arm-C-shaped episode: verify, repair, re-verify, finalize."""
    for index, node in enumerate(FIXED_PIPELINE, start=1):
        bridge.node_step(node, step=index)
    bridge.tool_call(
        call_id="t1",
        tool_id="arxiv_search",
        tool_version="1.0.0",
        side_effect_class="read_only",
        network_scope="allowlisted",
        result_kind="paper_list",
        result_count=5,
    )
    span = bridge.store_artifact(
        b"a bounded evidence span from the abstract",
        role=ArtifactRole.SOURCE_SPAN,
        media_type="text/plain",
        schema_ref="source-span/1.0.0",
    )
    assert span is not None
    bridge.source_discovered(
        source_id="src1",
        source_kind="preprint",
        locator_hash="sha256:" + "a" * 64,
        published_at=None,
        accessed_at=rb.utc_timestamp(),
        accepted=True,
        codes=["public_source"],
    )
    bridge.evidence_extracted(
        evidence_id="ev1",
        source_id="src1",
        span_artifact=span,
        method="abstract_span",
        supports=["item1"],
    )
    bridge.record_candidate("# Briefing\n\nfindings.")
    original = bridge._candidate_id
    assert original is not None
    bridge.verification(
        check_id="c1",
        candidate_id=original,
        verdict="fail",
        failure_codes=["ungrounded_claim"],
        suggested_repair_kind="qualify_or_remove_claims",
    )
    repaired = bridge.store_artifact(
        b"# Briefing v2\n\nqualified findings.", role=ArtifactRole.CANDIDATE_REPORT
    )
    assert repaired is not None
    child = bridge.repair(
        repair_id="r1",
        repair_kind="qualify_or_remove_claims",
        subject_candidate_id=original,
        result_artifact=repaired,
    )
    assert child is not None
    bridge.verification(check_id="c2", candidate_id=child, verdict="pass")
    verifications = tuple(
        event.event_id
        for event in bridge.events()
        if event.event_type == "verification.completed"
    )
    bridge.finalize(
        candidate_id=child,
        artifact=repaired,
        selection_basis="verified_repair",
        verification_event_ids=verifications,
    )
    bridge.reconcile(0.0)
    bridge.close()


def drive_learning_episode(bridge: rb.GuidedLearningBridge) -> None:
    bridge.node_step("check_in", step=1)
    bridge.node_step("passage", step=2)
    bridge.turn_paused(turn=1, graph_position="learner_input_1", deadline_seconds=600)
    bridge.turn_resumed(turn=1, response_kind="respond")
    bridge.node_step("tutor_1", step=3)
    bridge.turn_paused(turn=2, graph_position="learner_input_2", deadline_seconds=600)
    bridge.turn_resumed(turn=2, response_kind="respond")
    bridge.node_step("progress_update", step=4)
    bridge.complete("Covered self-attention; open gap on positional encoding.")
    bridge.reconcile(0.0)
    bridge.close()


# ---------------------------------------------------------------------------
# The two synthetic episodes
# ---------------------------------------------------------------------------


class TestTheSyntheticResearchEpisode:
    def test_it_reconstructs_from_the_durable_jsonl_alone(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        drive_research_episode(bridge)

        # Nothing from the live bridge: the file on disk, read back.
        path = (
            tmp_path
            / "sink"
            / rb.SINK_RUN_DIRECTORY
            / bridge.run_id
            / rb.SINK_EVENTS_FILE
        )
        reconstruction = rb.reconstruct_episode(
            path.read_text(encoding="utf-8"), lane="research"
        )

        assert reconstruction.terminal_event_type == "run.completed"
        assert reconstruction.verification_verdicts == ("fail", "pass")
        assert reconstruction.repair_ids == ("r1",)
        assert [
            decision
            for decision in reconstruction.decisions
            if decision.startswith("action.completed")
        ] == [f"action.completed:{node}" for node in FIXED_PIPELINE]
        assert "tool.completed:t1" in reconstruction.decisions
        assert "source.accepted:src1" in reconstruction.decisions

    def test_the_artifacts_it_produced_are_all_reachable_from_the_ledger(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        drive_research_episode(bridge)
        reconstruction = rb.reconstruct_episode(bridge.durable_jsonl(), lane="research")
        assert bridge.artifacts is not None
        for artifact_id in reconstruction.artifacts:
            assert bridge.artifacts.contains(artifact_id)

    def test_the_durable_file_round_trips_through_the_contract_importer(
        self, tmp_path: Path
    ) -> None:
        """W04's own importer, which re-derives every hash and refuses a gap."""
        bridge = research_bridge(tmp_path)
        drive_research_episode(bridge)
        imported = import_jsonl(bridge.durable_jsonl())
        verify_trajectory(imported)
        assert tuple(event.event_id for event in imported) == tuple(
            event.event_id for event in bridge.events()
        )

    def test_the_head_record_matches_the_chain_the_file_holds(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        drive_research_episode(bridge)
        sink = bridge.durable_store.sink
        assert isinstance(sink, rb.JsonlTrajectorySink)
        head = sink.head(bridge.run_id)
        assert head is not None
        imported = import_jsonl(bridge.durable_jsonl())
        assert head["head_event_hash"] == imported[-1].event_hash
        assert head["event_count"] == len(imported)

    def test_the_run_scope_is_written_beside_the_events(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        drive_research_episode(bridge)
        scope_path = (
            tmp_path
            / "sink"
            / rb.SINK_RUN_DIRECTORY
            / bridge.run_id
            / rb.SINK_SCOPE_FILE
        )
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        assert scope["run_id"] == bridge.run_id
        assert scope["manifest_digest"] == bridge.episode.manifest_digest

    def test_every_event_carries_the_span_it_was_recorded_under(
        self, tmp_path: Path, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        """RFC 10 §16's `trace_ref`, copied rather than depended on."""
        bridge = research_bridge(tmp_path)
        tracer = ot_trace.get_tracer("test")
        with tracer.start_as_current_span("episode"):
            bridge.node_step("planner", step=1)
        recorded = [
            event for event in bridge.events() if event.event_type == "action.started"
        ]
        assert recorded and recorded[0].trace_ref is not None

    def test_a_run_with_no_active_span_records_no_trace_ref(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        bridge.node_step("planner", step=1)
        assert all(event.trace_ref is None for event in bridge.events())


class TestTheSyntheticLearningEpisode:
    def test_it_reconstructs_from_the_durable_jsonl_alone(
        self, tmp_path: Path
    ) -> None:
        bridge = learning_bridge(tmp_path)
        drive_learning_episode(bridge)
        reconstruction = rb.reconstruct_episode(
            bridge.durable_jsonl(), lane="guided_learning"
        )
        assert reconstruction.terminal_event_type == "run.completed"
        assert reconstruction.human_pauses == ("learner_turn", "learner_turn")
        assert [
            decision
            for decision in reconstruction.decisions
            if decision.startswith("action.completed")
        ] == [
            "action.completed:check_in",
            "action.completed:passage",
            "action.completed:tutor_1",
            "action.completed:progress_update",
        ]

    def test_the_turns_it_parked_on_read_back_from_the_events(
        self, tmp_path: Path
    ) -> None:
        bridge = learning_bridge(tmp_path)
        drive_learning_episode(bridge)
        assert bridge.turn_trajectory() == (1, 2)

    def test_a_session_is_classified_learner_sensitive_throughout(
        self, tmp_path: Path
    ) -> None:
        """W09's acceptance rule: learner data receives the strictest default."""
        bridge = learning_bridge(tmp_path)
        drive_learning_episode(bridge)
        assert all(
            event.data_governance.effective_data_class is DataClass.LEARNER_SENSITIVE
            for event in bridge.events()
        )
        for event in bridge.events():
            for artifact in event.artifact_refs:
                assert artifact.data_class is DataClass.LEARNER_SENSITIVE

    def test_the_binding_replaces_a_manifest_and_says_so(self, tmp_path: Path) -> None:
        """RFC 09's PolicySnapshot names five research arms; a session is none."""
        bridge = learning_bridge(tmp_path)
        assert bridge.binding.product_lane == "guided_learning"
        assert bridge.summary()["session_binding_digest"] == bridge._scope.manifest_digest
        admitted = bridge.events()[0]
        assert admitted.event_type == "run.admitted"
        assert admitted.payload["product_lane"] == "guided_learning"

    def test_it_writes_no_learner_progress_event(self, tmp_path: Path) -> None:
        """The single most important negative in this work order.

        Structural, not behavioural: the bridge module has no import edge
        into `src.learning`, so a trajectory event cannot become a claim
        about a person's understanding by accident. RFC 10 §22 item 10.
        """
        source = Path("src/contracts/runtime_bridge.py").read_text(encoding="utf-8")
        imports = [
            line
            for line in source.splitlines()
            if line.lstrip().startswith(("import ", "from "))
        ]
        assert not [line for line in imports if "src.learning" in line]
        assert not [line for line in source.splitlines() if "ProgressEvent(" in line]
        bridge = learning_bridge(tmp_path)
        drive_learning_episode(bridge)
        assert not any(
            "progress" in str(event.payload.get("candidate_kind", ""))
            for event in bridge.events()
        )

    def test_a_learner_turn_records_the_decision_and_never_the_prose(
        self, tmp_path: Path
    ) -> None:
        bridge = learning_bridge(tmp_path)
        bridge.turn_paused(turn=1, graph_position="learner_input_1", deadline_seconds=60)
        bridge.turn_resumed(turn=1, response_kind="respond")
        responded = next(
            event for event in bridge.events() if event.event_type == "hitl.responded"
        )
        assert responded.payload["response_kind"] == "respond"
        assert responded.payload["response_artifact_id"] is None

    def test_a_turn_that_times_out_is_typed_rather_than_silent(
        self, tmp_path: Path
    ) -> None:
        bridge = learning_bridge(tmp_path)
        bridge.turn_paused(turn=1, graph_position="learner_input_1", deadline_seconds=1)
        bridge.turn_timed_out(turn=1, policy="session_turn_timeout")
        assert any(
            event.event_type == "hitl.timed_out" for event in bridge.events()
        )

    def test_a_cancelled_session_records_the_request_before_the_terminal(
        self, tmp_path: Path
    ) -> None:
        bridge = learning_bridge(tmp_path)
        bridge.cancel(reason_code="cancelled_by_reviewer", stage="session_runner")
        types = [event.event_type for event in bridge.events()]
        assert types[-2:] == ["run.cancel_requested", "run.cancelled"]

    def test_a_failed_session_carries_a_registered_error_code(
        self, tmp_path: Path
    ) -> None:
        bridge = learning_bridge(tmp_path)
        bridge.fail(error_code="not_a_real_code", stage="session_runner")
        failed = bridge.events()[-1]
        assert failed.payload["failure_class"] == "internal_unexpected"


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


class TestGovernance:
    def test_no_v1_event_is_training_eligible(self, tmp_path: Path) -> None:
        research = research_bridge(tmp_path)
        drive_research_episode(research)
        learning = learning_bridge(tmp_path)
        drive_learning_episode(learning)
        events = [*research.events(), *learning.events()]
        assert events
        assert all(
            event.data_governance.training_eligible is False for event in events
        )

    def test_a_product_operation_run_is_refused_the_durable_sink(
        self, tmp_path: Path
    ) -> None:
        """The D8 gate, enforced rather than documented."""
        bridge = research_bridge(tmp_path, origin="research_api", run_id="api-1")
        bridge.node_step("planner", step=1)
        assert bridge.durable_store.sink is None
        assert bridge.durable_jsonl() == ""
        assert not (tmp_path / "sink" / rb.SINK_RUN_DIRECTORY).exists()

    def test_a_product_operation_run_still_records_in_memory(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path, origin="research_api", run_id="api-1")
        bridge.node_step("planner", step=1)
        assert len(bridge.events()) > 3

    def test_a_real_learner_session_is_refused_the_durable_sink(
        self, tmp_path: Path
    ) -> None:
        bridge = learning_bridge(tmp_path, synthetic=False)
        assert bridge.consent_scope is ConsentScope.PRODUCT_OPERATION_ONLY
        assert bridge.durable_store.sink is None
        assert bridge.artifacts is None

    def test_capture_off_writes_nothing_at_all(self, tmp_path: Path) -> None:
        cfg = config(contract_event_capture="off")
        bridge = research_bridge(tmp_path, cfg)
        drive_research_episode(bridge)
        assert bridge.durable_store.sink is None
        assert not (tmp_path / "sink").exists()

    @pytest.mark.parametrize(
        ("consent", "permitted"),
        [
            (ConsentScope.EVALUATION_ONLY, True),
            (ConsentScope.PUBLIC_SOURCE_EVALUATION, True),
            (ConsentScope.SYNTHETIC_TEST, True),
            (ConsentScope.PRODUCT_OPERATION_ONLY, False),
            (ConsentScope.SUPPORT_ONLY, False),
            (ConsentScope.HUMAN_EVALUATION, False),
            (ConsentScope.AGGREGATE_ANALYTICS, False),
        ],
    )
    def test_the_capture_gate_admits_only_evaluative_consent(
        self, consent: ConsentScope, permitted: bool
    ) -> None:
        assert rb.capture_permitted(config(), consent) is permitted

    def test_the_gate_cannot_be_opened_by_configuration_alone(self) -> None:
        """There is no `production` member, and the check is two-sided."""
        assert (
            rb.capture_permitted(
                config(contract_event_capture="evaluation_only"),
                ConsentScope.PRODUCT_OPERATION_ONLY,
            )
            is False
        )
        with pytest.raises(ValidationError, match="contract_event_capture"):
            Settings(contract_event_capture="production")  # type: ignore[arg-type]

    def test_a_cross_principal_artifact_read_is_refused_through_the_bridge(
        self, tmp_path: Path
    ) -> None:
        """Zero tolerance, asserted where a caller would actually reach it."""
        bridge = learning_bridge(tmp_path)
        drive_learning_episode(bridge)
        assert bridge.artifacts is not None
        stored = [
            artifact.artifact_id
            for event in bridge.events()
            for artifact in event.artifact_refs
        ]
        assert stored
        with pytest.raises(ArtifactAccessDenied):
            bridge.artifacts.read(stored[0], principal_key_id="synthetic:someone-else")

    def test_a_report_containing_a_secret_is_refused_rather_than_stored(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        assert (
            bridge.store_artifact(
                b"the key is sk-abcdefghijklmnopqrstuvwx",
                role=ArtifactRole.CANDIDATE_REPORT,
            )
            is None
        )
        assert bridge.artifacts is not None
        assert bridge.artifacts.promoted_count == 0


# ---------------------------------------------------------------------------
# Resume, idempotency and concurrency
# ---------------------------------------------------------------------------


class TestResumeAndConcurrency:
    def test_a_resume_does_not_duplicate_an_action(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        for index, node in enumerate(FIXED_PIPELINE[:3], start=1):
            bridge.node_step(node, step=index)
        before = len(bridge.events())

        bridge.interrupt_attempt(
            interruption_class="worker_lost", checkpoint_id="ckpt-3"
        )
        bridge.resume_from_checkpoint(
            checkpoint_id="ckpt-3", reason="lease_expired", worker_id="worker-2"
        )
        resume_cost = len(bridge.events()) - before

        # The replay: the same three steps, proposed again.
        for index, node in enumerate(FIXED_PIPELINE[:3], start=1):
            bridge.node_step(node, step=index)

        assert len(bridge.events()) == before + resume_cost
        completed = [
            event.payload["action_id"]
            for event in bridge.events()
            if event.event_type == "action.completed"
        ]
        assert completed == list(FIXED_PIPELINE[:3])

    def test_a_resume_does_not_reset_the_cost_fold(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        bridge.node_step("planner", step=1)
        bridge.model_call(
            _observation(cost=0.004),
        )
        spent_before = fold_trajectory(bridge.events()).total_estimated_cost_usd
        bridge.interrupt_attempt(interruption_class="worker_lost", checkpoint_id="c1")
        bridge.resume_from_checkpoint(
            checkpoint_id="c1", reason="lease_expired", worker_id="worker-2"
        )
        after = fold_trajectory(bridge.events())
        assert after.total_estimated_cost_usd == spent_before
        assert after.total_llm_calls == 1

    def test_a_resume_takes_a_new_lease_and_keeps_the_run(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        first_attempt = bridge.attempt_id
        bridge.interrupt_attempt(interruption_class="worker_lost", checkpoint_id="c1")
        bridge.resume_from_checkpoint(
            checkpoint_id="c1", reason="lease_expired", worker_id="worker-2"
        )
        assert bridge.attempt_id != first_attempt
        assert {event.run_id for event in bridge.events()} == {bridge.run_id}

    def test_two_threads_appending_produce_a_file_in_sequence_order(
        self, tmp_path: Path
    ) -> None:
        """The concurrency property the JSONL sink exists to hold.

        The sink write happens inside the same lock that allocates
        `run_seq`, so the file's line order *is* sequence order however
        the threads interleave — which is what lets `import_jsonl` verify
        the chain without sorting anything first.
        """
        bridge = research_bridge(tmp_path)
        barrier = threading.Barrier(2)

        def worker(offset: int) -> None:
            barrier.wait()
            for index in range(offset, offset + 12):
                bridge.node_step(f"node{index}", step=index)

        threads = [
            threading.Thread(target=worker, args=(1,)),
            threading.Thread(target=worker, args=(100,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        imported = import_jsonl(bridge.durable_jsonl())
        assert [event.run_seq for event in imported] == list(
            range(1, len(imported) + 1)
        )
        verify_trajectory(imported)

    def test_a_replayed_step_records_nothing_the_second_time(
        self, tmp_path: Path
    ) -> None:
        """The guard, isolated from the resume that motivates it."""
        bridge = research_bridge(tmp_path)
        bridge.node_step("planner", step=1)
        before = len(bridge.events())
        bridge.node_step("planner", step=1)
        assert len(bridge.events()) == before


def _observation(*, cost: float = 0.0, model: str = "claude-sonnet-4-6") -> Any:
    from src.observability.costs import LlmCallObservation

    return LlmCallObservation(
        model=model,
        input_tokens=1_000,
        output_tokens=200,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        cost_usd=cost,
        retries=0,
        latency_ms=12.0,
    )


# ---------------------------------------------------------------------------
# Cost reconciliation
# ---------------------------------------------------------------------------


class TestCostReconciliation:
    def test_matching_totals_reconcile(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        bridge.model_call(_observation(cost=0.004))
        bridge.model_call(_observation(cost=0.006))
        result = bridge.reconcile(0.010)
        assert result.matched is True
        assert result.result == "match"
        event = bridge.events()[-1]
        assert event.event_type == "budget.reconciled"
        assert event.status.value == "succeeded"

    def test_a_discrepancy_beyond_tolerance_fails_closed(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        bridge.model_call(_observation(cost=0.004))
        result = bridge.reconcile(0.104)
        assert result.matched is False
        event = bridge.events()[-1]
        assert event.event_type == "budget.reconciled"
        assert event.status.value == "failed"
        assert event.payload["result"] == "mismatch"
        assert "integrity_failure" in event.reason_codes

    def test_per_call_rounding_stays_inside_the_tolerance(
        self, tmp_path: Path
    ) -> None:
        """Four calls whose unrounded sum differs from the rounded one."""
        bridge = research_bridge(tmp_path)
        for _ in range(4):
            bridge.model_call(_observation(cost=0.0000014))
        result = bridge.reconcile(4 * 0.0000014)
        assert result.matched is True

    def test_the_reconciliation_is_appended_after_the_terminal_event(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        bridge.record_candidate("# Briefing")
        candidate = bridge._candidate_id
        assert candidate is not None
        artifact = bridge._final_artifact
        assert artifact is not None
        bridge.finalize(
            candidate_id=candidate, artifact=artifact, selection_basis="single"
        )
        bridge.reconcile(0.0)
        types = [event.event_type for event in bridge.events()]
        assert types[-2:] == ["run.completed", "budget.reconciled"]

    def test_reconciling_twice_appends_once(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        bridge.reconcile(0.0)
        bridge.reconcile(0.0)
        assert (
            len([e for e in bridge.events() if e.event_type == "budget.reconciled"]) == 1
        )

    def test_the_tolerance_scales_with_the_calls_it_has_to_cover(self) -> None:
        assert rb.RECONCILIATION_UNIT_USD > 0
        empty = rb.reconcile_costs.__doc__
        assert empty is not None and "quantized" in empty


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


class TestProjections:
    def test_a_broken_projection_cannot_erase_an_accepted_event(
        self, tmp_path: Path
    ) -> None:
        def explode(event: Any) -> None:
            raise RuntimeError("the projection surface is down")

        bridge = rb.ResearchRuntimeBridge(
            episode=sealed_episode(config()),
            runtime_run_id="episode-1",
            principal_key_id=SYNTHETIC_PRINCIPAL,
            cost_ceiling_usd="2.000000",
            sink=rb.JsonlTrajectorySink(tmp_path / "sink"),
            projections=(rb.NamedProjection("explodes", explode),),
        )
        bridge.open()
        bridge.node_step("planner", step=1)

        assert bridge.durable_store.projection_degraded is True
        imported = import_jsonl(bridge.durable_jsonl())
        assert [event.event_type for event in imported][:2] == [
            "run.admitted",
            "attempt.started",
        ]
        assert any(event.payload.get("action_id") == "planner" for event in imported)

    def test_the_terminal_frame_projects_onto_the_name_the_runner_emits(
        self,
    ) -> None:
        """The SSE contract, asserted as a derivation rather than a promise."""
        job = Job(job_id="j1", query="q", status=JobStatus.succeeded)
        frame = format_sse("job_completed", terminal_event_data(job))
        projected = sse_event_name_for("run.completed")
        assert projected == "job_completed"
        assert format_sse(projected, terminal_event_data(job)) == frame

    @pytest.mark.parametrize(
        ("event_type", "name"),
        sorted(CANONICAL_EVENT_PROJECTION.items()),
    )
    def test_every_projection_target_is_a_frame_the_client_already_knows(
        self, event_type: str, name: str
    ) -> None:
        from tests.test_contract_sse_events import PINNED_EVENT_NAMES

        assert name in PINNED_EVENT_NAMES
        assert sse_event_name_for(event_type) == name

    def test_the_two_pause_frames_project_from_one_canonical_event(self) -> None:
        from tests.test_contract_sse_events import PINNED_EVENT_NAMES

        assert set(HITL_EVENT_PROJECTION.values()) == {"plan_ready", "turn_ready"}
        assert set(HITL_EVENT_PROJECTION.values()) <= PINNED_EVENT_NAMES
        assert sse_event_name_for("hitl.requested", request_kind="plan_review") == (
            "plan_ready"
        )
        assert sse_event_name_for("hitl.requested", request_kind="learner_turn") == (
            "turn_ready"
        )

    def test_an_event_with_no_safe_projection_projects_onto_nothing(self) -> None:
        assert sse_event_name_for("verification.completed") is None
        assert sse_event_name_for("hitl.requested", request_kind="unheard_of") is None

    def test_the_span_projection_attaches_to_the_live_span(
        self, tmp_path: Path, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        bridge = research_bridge(tmp_path)
        tracer = ot_trace.get_tracer("test")
        with tracer.start_as_current_span("episode"):
            bridge.node_step("planner", step=1)
        spans = in_memory_tracer.get_finished_spans()
        names = {
            event.name for span in spans for event in getattr(span, "events", ())
        }
        assert "trajectory.action.completed" in names

    def test_the_log_projection_is_off_unless_it_is_switched_on(
        self, tmp_path: Path
    ) -> None:
        names = {
            projection.name for projection in rb.build_projections(config())
        }
        assert "event_log" not in names
        switched = {
            projection.name
            for projection in rb.build_projections(
                config(contract_event_log_projection=True)
            )
        }
        assert "event_log" in switched

    def test_the_verdict_projection_closes_adr_0076s_follow_up(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        bridge = research_bridge(tmp_path)
        bridge.record_candidate("# Briefing")
        candidate = bridge._candidate_id
        assert candidate is not None
        with caplog.at_level("INFO"):
            bridge.verification(check_id="c1", candidate_id=candidate, verdict="pass")
            bridge.repair(
                repair_id="r1",
                repair_kind="qualify_or_remove_claims",
                subject_candidate_id=candidate,
                succeeded=False,
            )
        messages = {record.message for record in caplog.records}
        assert "verify_verdict_recorded" in messages
        assert "repair_action_selected" in messages

    def test_both_verdict_names_are_registered_log_events(self) -> None:
        from src.observability.logging import KNOWN_EVENTS

        assert {"verify_verdict_recorded", "repair_action_selected"} <= KNOWN_EVENTS

    def test_the_five_mock_mode_names_adr_0080_asked_for_are_registered(self) -> None:
        from src.observability.logging import KNOWN_EVENTS

        assert {
            "planner_mock_plan_served",
            "reader_mock_analysis_served",
            "reader_mock_claims_served",
            "synthesizer_mock_briefing_served",
            "critic_mock_critique_served",
        } <= KNOWN_EVENTS

    def test_the_undescribed_model_warning_adr_0077_asked_for_is_registered(
        self,
    ) -> None:
        from src.observability.logging import KNOWN_EVENTS

        assert "unknown_model_capability_fallback" in KNOWN_EVENTS

    def test_the_bridge_warns_once_for_a_model_with_no_capability_row(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        bridge = research_bridge(tmp_path)
        with caplog.at_level("WARNING"):
            bridge.note_model_capabilities("some-model-nobody-described")
            bridge.note_model_capabilities("claude-haiku-4-5")
        warnings = [
            record
            for record in caplog.records
            if record.message == "unknown_model_capability_fallback"
        ]
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# The span attribute CAP-01 could not fix
# ---------------------------------------------------------------------------


class TestTheTemperatureAttribute:
    def test_it_is_absent_when_no_temperature_was_sent(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        """ADR 0077 follow-up 1: truthful about the request, or absent."""
        with tracing_module.llm_span(
            model="claude-opus-5",
            max_tokens=1024,
            temperature=None,
            server_address="api.anthropic.com",
        ):
            pass
        span = in_memory_tracer.get_finished_spans()[0]
        assert span.attributes is not None
        assert "gen_ai.request.temperature" not in span.attributes

    def test_it_is_present_when_one_was(
        self, in_memory_tracer: InMemorySpanExporter
    ) -> None:
        with tracing_module.llm_span(
            model="claude-haiku-4-5",
            max_tokens=1024,
            temperature=0.3,
            server_address="api.anthropic.com",
        ):
            pass
        span = in_memory_tracer.get_finished_spans()[0]
        assert span.attributes is not None
        assert span.attributes["gen_ai.request.temperature"] == 0.3

    def test_the_gateway_passes_the_profile_through_unchanged(self) -> None:
        """`src/llm.py` now hands over `profile.temperature` verbatim."""
        source = Path("src/llm.py").read_text(encoding="utf-8")
        assert "temperature=profile.temperature," in source


# ---------------------------------------------------------------------------
# The rest of the taxonomy
# ---------------------------------------------------------------------------


class TestTheRestOfTheTaxonomy:
    """Every RFC 10 §8 type the two episodes above do not happen to use.

    Not padding: each of these exists because some arm, some failure or
    some policy the program has already designed needs it, and a
    vocabulary that is only exercised on the happy path is a vocabulary
    whose first real use discovers it does not validate.
    """

    def test_a_plan_and_a_routing_decision_record_without_their_reasoning(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        plan = bridge.store_artifact(
            b'{"objectives": 3}', role=ArtifactRole.PLAN, media_type="application/json",
            schema_ref="plan/1.0.0",
        )
        assert plan is not None
        bridge.plan_created(plan, objectives=3, actions=5, kind="fixed_pipeline")
        bridge.policy_decision(
            key="route-1",
            decision_kind="next_node",
            eligible=["search", "critic"],
            chosen="search",
            reason_codes=["completed"],
        )
        decision = next(
            event for event in bridge.events() if event.event_type == "policy.decision"
        )
        assert decision.payload["chosen_action"] == "search"
        assert set(decision.payload) == {
            "decision_kind",
            "eligible_actions",
            "chosen_action",
            "reason_codes",
            "feature_snapshot_ref",
        }

    def test_a_failed_tool_call_records_its_class_and_not_its_error(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        bridge.tool_failed(
            call_id="t9",
            tool_id="arxiv_search",
            tool_version="1.0.0",
            error_class="upstream_arxiv",
            retryable=True,
            provider_status_class="5xx",
        )
        failed = next(
            event for event in bridge.events() if event.event_type == "tool.failed"
        )
        assert failed.payload["error_class"] == "upstream_arxiv"
        assert "upstream_arxiv" in failed.reason_codes

    def test_a_rejected_source_does_not_disappear(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        bridge.source_discovered(
            source_id="src9",
            source_kind="preprint",
            locator_hash="sha256:" + "f" * 64,
            published_at=None,
            accessed_at=rb.utc_timestamp(),
            accepted=False,
            codes=["out_of_scope"],
        )
        types = [event.event_type for event in bridge.events()]
        assert "source.discovered" in types
        assert "source.rejected" in types

    def test_a_claim_links_to_its_evidence_and_its_coverage_is_assessed(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        bridge.record_candidate("# Briefing")
        candidate = bridge._candidate_id
        assert candidate is not None
        claim = bridge.store_artifact(
            b'{"claims": []}',
            role=ArtifactRole.CLAIM_SET,
            media_type="application/json",
            schema_ref="claim-set/1.0.0",
        )
        assert claim is not None
        bridge.claim_created(
            claim_id="claim1",
            candidate_id=candidate,
            artifact=claim,
            claim_kind="citation",
            location="section:2",
        )
        bridge.claim_evidence_linked(
            claim_id="claim1",
            evidence_id="ev1",
            relationship="supports",
            method="span_match",
        )
        bridge.coverage_assessed(
            task_items=["item1", "item2"],
            covered=["item1"],
            missing=["item2"],
            method="deterministic",
        )
        types = [event.event_type for event in bridge.events()]
        assert "claim.created" in types
        assert "claim.evidence_linked" in types
        assert "evidence.coverage_assessed" in types

    def test_a_malformed_verdict_is_not_a_pass(self, tmp_path: Path) -> None:
        """RFC 10 §8.5: `verification.malformed` cannot project as a pass."""
        bridge = research_bridge(tmp_path)
        bridge.record_candidate("# Briefing")
        candidate = bridge._candidate_id
        assert candidate is not None
        bridge.verification_malformed(
            check_id="c9",
            candidate_id=candidate,
            error_class="upstream_model_output",
            fallback_action="treat_as_unverified",
        )
        malformed = next(
            event
            for event in bridge.events()
            if event.event_type == "verification.malformed"
        )
        assert malformed.status.value == "failed"
        assert not [
            event for event in bridge.events()
            if event.event_type == "verification.completed"
        ]

    def test_a_failed_repair_leaves_its_subject_readable(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        bridge.record_candidate("# Briefing")
        candidate = bridge._candidate_id
        assert candidate is not None
        assert (
            bridge.repair(
                repair_id="r9",
                repair_kind="retrieve_missing_evidence",
                subject_candidate_id=candidate,
                succeeded=False,
                error_class="upstream_arxiv",
            )
            is None
        )
        bridge.repair_exhausted(
            subject_candidate_id=candidate,
            attempted=["r9"],
            reason="repair_budget_spent",
        )
        types = [event.event_type for event in bridge.events()]
        assert "repair.failed" in types
        assert "repair.exhausted" in types
        assert not [t for t in types if t == "candidate.revised"]

    def test_a_selection_over_several_candidates_records_the_eligible_set(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        bridge.record_candidate("# Briefing")
        original = bridge._candidate_id
        assert original is not None
        revised_artifact = bridge.store_artifact(
            b"# Briefing v2", role=ArtifactRole.CANDIDATE_REPORT
        )
        assert revised_artifact is not None
        child = bridge.candidate_revised(
            parent_candidate_id=original,
            artifact=revised_artifact,
            change_scope="section",
            key="rev1",
        )
        score = bridge.store_artifact(
            b'{"score": 0.9}',
            role=ArtifactRole.RUNTIME_SCORE_RECORD,
            media_type="application/json",
            schema_ref="runtime-score/1.0.0",
        )
        assert score is not None
        bridge.candidate_selected(
            eligible=[original, child],
            selected=child,
            selector_kind="deterministic",
            selection_artifact=score,
        )
        selected = next(
            event
            for event in bridge.events()
            if event.event_type == "candidate.selected"
        )
        assert selected.payload["selected_candidate_id"] == child
        assert original in selected.payload["eligible_candidate_ids"]

    def test_a_reservation_is_taken_and_released(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        bridge.budget_reserved(
            reservation_id="res1",
            action_id="model_request",
            maximum_cost="0.010000",
            ttl_seconds=60,
        )
        bridge.budget_reservation_released(
            reservation_id="res1", actual_cost="0.004000", reason="settled"
        )
        types = [event.event_type for event in bridge.events()]
        assert "budget.reserved" in types
        assert "budget.reservation_released" in types

    def test_a_refused_checkpoint_is_typed_rather_than_silent(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        bridge.checkpoint_saved(checkpoint_id="c1", graph_position="reader")
        bridge.checkpoint_invalid(
            checkpoint_id="c1",
            failure_codes=["schema_drift"],
            fallback="restart_from_scratch",
        )
        invalid = next(
            event
            for event in bridge.events()
            if event.event_type == "checkpoint.invalid"
        )
        assert invalid.status.value == "rejected"

    def test_a_review_can_time_out_or_be_cancelled(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        bridge.checkpoint_and_review_requested(
            pause_number=1, pending=["planner"], deadline_seconds=60
        )
        bridge.review_timed_out(pause_number=1, policy="hitl_timeout")
        bridge.checkpoint_and_review_requested(
            pause_number=2, pending=["planner"], deadline_seconds=60
        )
        bridge.review_cancelled(pause_number=2, reason="user_requested")
        types = [event.event_type for event in bridge.events()]
        assert "hitl.timed_out" in types
        assert "hitl.cancelled" in types

    def test_a_non_terminal_failure_is_recorded_with_a_bounded_message(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)
        bridge.failure_recorded(
            failure_id="f1",
            failure_class="upstream_paper_read",
            stage="reader",
            retryable=True,
            safe_message="x" * 500,
        )
        failure = next(
            event for event in bridge.events() if event.event_type == "failure.recorded"
        )
        assert len(str(failure.payload["safe_message"])) == 200

    def test_an_approval_free_run_still_reconstructs_every_kind_it_recorded(
        self, tmp_path: Path
    ) -> None:
        """One pass over everything above, through the file."""
        bridge = research_bridge(tmp_path)
        bridge.tool_failed(
            call_id="t9",
            tool_id="arxiv_search",
            tool_version="1.0.0",
            error_class="upstream_arxiv",
            retryable=True,
            provider_status_class="5xx",
        )
        bridge.node_step("planner", step=1)
        bridge.record_candidate("# Briefing")
        candidate = bridge._candidate_id
        artifact = bridge._final_artifact
        assert candidate is not None and artifact is not None
        bridge.finalize(
            candidate_id=candidate, artifact=artifact, selection_basis="single"
        )
        bridge.close()
        reconstruction = rb.reconstruct_episode(bridge.durable_jsonl(), lane="research")
        assert "tool.failed:t9" in reconstruction.decisions
        assert reconstruction.terminal_event_type == "run.completed"


class TestTheContainedFacade:
    def test_a_broken_bridge_degrades_itself_rather_than_raising(
        self, tmp_path: Path
    ) -> None:
        bridge = research_bridge(tmp_path)

        def explode(_cost: float) -> None:
            raise RuntimeError("down")

        bridge.reconcile = explode  # type: ignore[method-assign, assignment]
        assert rb.observe_reconciliation(bridge, 0.0) is None
        assert bridge.degraded is True

    def test_a_missing_bridge_is_a_no_op_on_every_facade(self) -> None:
        assert rb.observe_reconciliation(None, 0.0) is None
        assert rb.observe_close(None) is None

    def test_a_degraded_bridge_stops_reconciling(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        bridge.degraded = True
        assert rb.observe_reconciliation(bridge, 0.0) is None

    def test_the_close_facade_verifies_the_chain(self, tmp_path: Path) -> None:
        bridge = research_bridge(tmp_path)
        bridge.node_step("planner", step=1)
        rb.observe_close(bridge)
        sink = bridge.durable_store.sink
        assert isinstance(sink, rb.JsonlTrajectorySink)
        assert sink.head(bridge.run_id) is not None


class TestTheRunnerEntryPoint:
    def test_a_session_job_gets_no_research_trajectory(self, tmp_path: Path) -> None:
        job = Job(job_id="s1", query="q", kind="session")
        assert (
            rb.start_research_job(job, _AppStub(), config=config(), cost_ceiling_usd=1.0)
            is None
        )

    def test_the_switch_off_opens_nothing(self, tmp_path: Path) -> None:
        job = Job(job_id="j1", query="q", hitl_bypass=True)
        assert (
            rb.start_research_job(
                job,
                _AppStub(),
                config=config(contract_shadow="off"),
                cost_ceiling_usd=1.0,
            )
            is None
        )

    def test_an_api_job_opens_a_bridge_that_writes_no_file(
        self, tmp_path: Path
    ) -> None:
        """The D8 gate on the one path a real user reaches."""
        job = Job(job_id="j1", query="why do LLMs hallucinate?", hitl_bypass=True)
        bridge = rb.start_research_job(
            job,
            _AppStub(),
            config=config(contract_event_sink_root=str(tmp_path / "sink")),
            cost_ceiling_usd=1.0,
        )
        assert bridge is not None
        assert bridge.durable_store.sink is None
        assert bridge.artifacts is None
        assert not (tmp_path / "sink").exists()
        assert bridge.events()[0].event_type == "run.admitted"

    def test_the_opened_run_is_reachable_through_the_shared_registry(
        self, tmp_path: Path
    ) -> None:
        job = Job(job_id="j-registry", query="q", hitl_bypass=True)
        bridge = rb.start_research_job(
            job, _AppStub(), config=config(), cost_ceiling_usd=1.0
        )
        assert bridge is not None
        try:
            assert rb.shadow_run("j-registry") is bridge
        finally:
            from src.contracts.shadow_bridge import reset_registry

            reset_registry()


# ---------------------------------------------------------------------------
# The sink itself
# ---------------------------------------------------------------------------


class TestTheSink:
    def test_the_path_scheme_is_one_directory_per_run(self, tmp_path: Path) -> None:
        sink = rb.JsonlTrajectorySink(tmp_path / "sink")
        directory = sink.run_directory("run_" + "a" * 32)
        assert directory == tmp_path / "sink" / "runs" / ("run_" + "a" * 32)

    def test_a_path_shaped_run_id_is_refused(self, tmp_path: Path) -> None:
        sink = rb.JsonlTrajectorySink(tmp_path / "sink")
        with pytest.raises(rb.BridgeError, match="contract run id"):
            sink.run_directory("../../etc")

    def test_an_unwritten_run_reads_back_as_empty_rather_than_raising(
        self, tmp_path: Path
    ) -> None:
        sink = rb.JsonlTrajectorySink(tmp_path / "sink")
        assert sink.read_jsonl("run_" + "b" * 32) == ""
        assert sink.head("run_" + "b" * 32) is None


@pytest.fixture
def in_memory_tracer(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """A fresh in-memory tracer for one test.

    Same shape as `tests/test_tracing.py`'s fixture, and duplicated
    rather than imported for the reason that file gives: `tests/` is
    importable only through the path entry pytest happens to insert, and
    the suite declines to rest anything on it.
    """
    monkeypatch.setattr(
        tracing_module,
        "settings",
        shipped_settings.model_copy(update={"enable_tracing": True}),
    )
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(
        ot_trace,
        "_TRACER_PROVIDER_SET_ONCE",
        ot_trace._TRACER_PROVIDER_SET_ONCE.__class__(),
        raising=False,
    )
    monkeypatch.setattr(ot_trace, "_TRACER_PROVIDER", None, raising=False)
    ot_trace.set_tracer_provider(provider)
    monkeypatch.setattr(tracing_module, "_configured", True)
    return exporter


def test_usage_deltas_are_the_only_source_of_the_cost_fold() -> None:
    """A guard on the reconciliation's own arithmetic."""
    delta = UsageDelta(
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        input_tokens=10,
        llm_calls=1,
    )
    assert delta.estimated_cost_usd == "0.000000"
