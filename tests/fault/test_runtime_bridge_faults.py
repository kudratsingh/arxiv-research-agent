"""Fault injection for the runtime event bridge (P0-WO08, ADR 0083).

The bridge's whole claim is that a canonical event, once accepted, is a
durable fact that nothing downstream can take back. Four ways that claim
could be false are injected here — the sink write fails, a projection
fails, two branches append at once, and the worker dies between the
accept and the projection — and each asserts the tier's triple: the
canonical error code, the registered log event, and the metric point.

The triple is asserted through a local helper rather than
`TripleObserver.assert_triple`, and the reason is a boundary rather than
a preference. That method checks its instrument against `LIVE_INSTRUMENTS`
in this directory's `conftest.py`, which is an existing test module this
work order does not edit; `trajectory_faults_total` is new, so the three
legs are asserted here against the same three sources — `ERROR_CODES`,
`KNOWN_EVENTS`, and a real aggregated data point out of the shared
`InMemoryMetricReader`.
"""

from __future__ import annotations

import logging
import threading
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
    IdempotencyConflict,
    import_jsonl,
    verify_trajectory,
)
from src.errors import ERROR_CODES
from src.observability.logging import KNOWN_EVENTS

from .conftest import TripleObserver

pytestmark = [pytest.mark.fault, pytest.mark.integration]

FIXED_PIPELINE = ("planner", "search", "reader", "synthesizer", "critic")
SYNTHETIC_PRINCIPAL = "synthetic:research-eval"

#: The instrument this work order adds. Named here for the same reason
#: `LIVE_INSTRUMENTS` names the others: one place to change when it moves.
TRAJECTORY_FAULTS = "trajectory_faults_total"
TRAJECTORY_EVENTS = "trajectory_events_total"


# ---------------------------------------------------------------------------
# Harness
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


def _config(**overrides: Any) -> Settings:
    base = {
        "use_mock_data": True,
        "enable_tracing": False,
        "enable_metrics": True,
        "enable_semantic_scholar": False,
        "enable_checkpointing": False,
        "contract_shadow": "shadow",
        "contract_event_capture": "evaluation_only",
    }
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


def _episode(cfg: Settings, run_id: str = "episode-fault") -> Any:
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
        origin="research_eval",
        runtime_run_id=run_id,
        hitl_bypass=True,
        hitl_bypass_reason="unattended-evaluation",
    )


def _bridge(
    tmp_path: Path,
    *,
    sink: Any | None = None,
    projections: tuple[rb.NamedProjection, ...] = (),
    run_id: str = "episode-fault",
) -> rb.ResearchRuntimeBridge:
    cfg = _config()
    bridge = rb.ResearchRuntimeBridge(
        episode=_episode(cfg, run_id),
        runtime_run_id=run_id,
        principal_key_id=SYNTHETIC_PRINCIPAL,
        cost_ceiling_usd="2.000000",
        sink=sink if sink is not None else rb.JsonlTrajectorySink(tmp_path / "sink"),
        projections=projections,
    )
    bridge.open()
    return bridge


def assert_bridge_triple(
    observer: TripleObserver,
    *,
    code: str,
    event: str,
    stage: str,
    value: float = 1,
) -> logging.LogRecord:
    """Assert one bridge fault landed on all three contracts.

    Same three legs `TripleObserver.assert_triple` checks, against the
    same three sources: `ERROR_CODES` for the code, `KNOWN_EVENTS` for
    the log line, and one real aggregated point for the metric. The log
    line must also *agree* with the metric on the code, which is the
    property that stops the two from forking.
    """
    assert code in ERROR_CODES, f"{code!r} is not a registered error code"
    assert event in KNOWN_EVENTS, f"{event!r} is not a registered log event"

    records = observer.records(event)
    assert records, (
        f"expected a {event!r} record; captured "
        f"{sorted({r.message for r in observer.caplog.records})}"
    )
    record = records[0]
    assert getattr(record, "error_type", None) == code, (
        f"the {event!r} line says error_type={getattr(record, 'error_type', None)!r} "
        f"while the fault reports {code!r}; the log and the metric have forked"
    )

    point = observer.point(TRAJECTORY_FAULTS, stage=stage, error_type=code)
    assert point.value == value, (
        f"{TRAJECTORY_FAULTS}{{stage={stage}, error_type={code}}} = "
        f"{point.value}, expected {value}"
    )
    return record


class _BrokenSink(rb.JsonlTrajectorySink):
    """A sink whose durable write fails from a chosen event onwards.

    Subclassing the real one rather than faking the protocol: the failure
    under test is "the durable write did not happen", and everything
    around it — the run directory, the scope file, the head record —
    should behave exactly as it does in production, or the test is about
    a different object.
    """

    def __init__(self, root: Path, *, fail_from: int = 0) -> None:
        super().__init__(root)
        self.fail_from = fail_from
        self.attempts = 0

    def append(self, event: Any) -> None:
        self.attempts += 1
        if self.attempts > self.fail_from:
            raise OSError("no space left on device")
        super().append(event)


# ---------------------------------------------------------------------------
# 1. The durable sink write fails
# ---------------------------------------------------------------------------


class TestTheSinkWriteFails:
    def test_the_fault_lands_on_all_three_contracts(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        bridge = _bridge(tmp_path, sink=_BrokenSink(tmp_path / "sink", fail_from=0))
        assert_bridge_triple(
            triple,
            code="service_unavailable",
            event="trajectory_sink_write_failed",
            stage="sink_write",
            value=3,  # run.admitted, attempt.started, budget.established
        )
        assert bridge.durable_store.durability_degraded is True

    def test_the_event_is_still_accepted_in_the_ledger(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        """A sink that cannot write must not cost the run its history."""
        bridge = _bridge(tmp_path, sink=_BrokenSink(tmp_path / "sink", fail_from=0))
        bridge.node_step("planner", step=1)
        types = [event.event_type for event in bridge.events()]
        assert types[0] == "run.admitted"
        assert "action.completed" in types
        verify_trajectory(bridge.events())

    def test_the_run_does_not_fail_because_its_sink_did(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        bridge = _bridge(tmp_path, sink=_BrokenSink(tmp_path / "sink", fail_from=0))
        bridge.record_candidate("# Briefing")
        candidate = bridge._candidate_id
        artifact = bridge._final_artifact
        assert candidate is not None and artifact is not None
        bridge.finalize(
            candidate_id=candidate, artifact=artifact, selection_basis="single"
        )
        assert bridge.events()[-1].event_type == "run.completed"

    def test_a_partial_sink_failure_keeps_the_events_that_did_land(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        sink = _BrokenSink(tmp_path / "sink", fail_from=3)
        bridge = _bridge(tmp_path, sink=sink)
        bridge.node_step("planner", step=1)
        written = import_jsonl(bridge.durable_jsonl())
        assert [event.event_type for event in written] == [
            "run.admitted",
            "attempt.started",
            "budget.established",
        ]
        verify_trajectory(written)

    def test_a_failure_opening_the_run_is_reported_not_raised(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        class _UnopenableSink(rb.JsonlTrajectorySink):
            def open_run(self, scope: Any) -> None:
                raise OSError("read-only filesystem")

        bridge = _bridge(tmp_path, sink=_UnopenableSink(tmp_path / "sink"))
        assert bridge.durable_store.durability_degraded is True
        assert_bridge_triple(
            triple,
            code="service_unavailable",
            event="trajectory_sink_write_failed",
            stage="sink_write",
            value=1,  # the open; `append` is the real one and still works
        )


# ---------------------------------------------------------------------------
# 2. A projection fails
# ---------------------------------------------------------------------------


class TestAProjectionFails:
    def test_the_fault_lands_on_all_three_contracts(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        def explode(event: Any) -> None:
            raise RuntimeError("the projection surface is down")

        _bridge(tmp_path, projections=(rb.NamedProjection("explodes", explode),))
        record = assert_bridge_triple(
            triple,
            code="internal_unexpected",
            event="trajectory_projection_failed",
            stage="projection",
            value=3,
        )
        assert record.stage == "explodes"

    def test_a_projection_failure_cannot_erase_an_accepted_event(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        """The acceptance criterion, asserted against the file on disk."""

        def explode(event: Any) -> None:
            raise RuntimeError("the projection surface is down")

        bridge = _bridge(
            tmp_path, projections=(rb.NamedProjection("explodes", explode),)
        )
        bridge.node_step("planner", step=1)
        written = import_jsonl(bridge.durable_jsonl())
        assert any(
            event.payload.get("action_id") == "planner" for event in written
        )
        verify_trajectory(written)

    def test_one_broken_projection_does_not_stop_the_others(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        seen: list[str] = []

        def explode(event: Any) -> None:
            raise RuntimeError("down")

        def works(event: Any) -> None:
            seen.append(event.event_type)

        _bridge(
            tmp_path,
            projections=(
                rb.NamedProjection("explodes", explode),
                rb.NamedProjection("works", works),
            ),
        )
        assert seen == ["run.admitted", "attempt.started", "budget.established"]

    def test_the_accepted_events_are_still_counted_as_accepted(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        def explode(event: Any) -> None:
            raise RuntimeError("down")

        _bridge(tmp_path, projections=(rb.NamedProjection("explodes", explode),))
        point = triple.point(TRAJECTORY_EVENTS, lane="research", outcome="accepted")
        assert point.value == 3


# ---------------------------------------------------------------------------
# 3. Concurrent appends from two branches
# ---------------------------------------------------------------------------


class TestConcurrentAppends:
    def test_two_branches_appending_at_once_produce_one_ordered_chain(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        bridge = _bridge(tmp_path)
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def worker(offset: int) -> None:
            try:
                barrier.wait()
                for index in range(offset, offset + 15):
                    bridge.node_step(f"node{index}", step=index)
            except BaseException as exc:  # noqa: BLE001 — reported, not swallowed
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(1,)),
            threading.Thread(target=worker, args=(200,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        written = import_jsonl(bridge.durable_jsonl())
        assert [event.run_seq for event in written] == list(
            range(1, len(written) + 1)
        )
        verify_trajectory(written)
        assert len(written) == 3 + 2 * 15 * 2

    def test_a_conflicting_retry_under_one_key_is_refused_and_counted(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        """RFC 10 §11.2: differing content under one key is a conflict."""
        bridge = _bridge(tmp_path)
        first = bridge.node_step("planner", step=1)
        del first
        proposed = _proposal(bridge, action_id="a-different-node", step=1)
        with pytest.raises(IdempotencyConflict):
            bridge.durable_store.append(proposed)

        assert triple.records("trajectory_append_conflict")
        point = triple.point(TRAJECTORY_EVENTS, lane="research", outcome="rejected")
        assert point.value == 1
        assert [
            event.payload["action_id"]
            for event in bridge.events()
            if event.event_type == "action.started"
        ] == ["planner"]

    def test_an_identical_retry_returns_the_stored_event(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        """The other half of §11.2: a matching retry is answered, not appended."""
        from src.contracts.trajectory import ProposedTrajectoryEvent

        bridge = _bridge(tmp_path)
        bridge.node_step("planner", step=1)
        original = next(
            event for event in bridge.events() if event.event_type == "action.started"
        )
        proposed = ProposedTrajectoryEvent.model_validate(
            {
                key: value
                for key, value in original.model_dump().items()
                if key not in {"run_seq", "recorded_at", "prev_event_hash", "event_hash"}
            }
        )
        before = len(bridge.events())
        stored = bridge.durable_store.append(proposed)
        assert stored.event_id == original.event_id
        assert len(bridge.events()) == before
        point = triple.point(
            TRAJECTORY_EVENTS, lane="research", outcome="deduplicated"
        )
        assert point.value == 1


def _proposal(bridge: rb.ResearchRuntimeBridge, *, action_id: str, step: int) -> Any:
    """A hand-built `action.started` under the key `node_step` would use."""
    from src.contracts.trajectory import (
        Actor,
        ActorKind,
        EventStatus,
        ProposedTrajectoryEvent,
    )

    scope = bridge._scope
    return ProposedTrajectoryEvent(
        event_type="action.started",
        event_id=bridge._event_id(f"conflicting:{action_id}:{step}"),
        idempotency_key=f"{bridge.run_id}:action.started:{step}:planner",
        run_id=bridge.run_id,
        attempt_id=bridge.attempt_id,
        task_spec_id=scope.task_spec_id,
        task_revision=scope.task_revision,
        task_spec_full_digest=scope.task_spec_full_digest,
        manifest_digest=scope.manifest_digest,
        principal_key_id=scope.principal_key_id,
        occurred_at=rb.utc_timestamp(),
        actor=Actor(
            kind=ActorKind.AGENT,
            name="planner",
            instance_id="contract-shadow",
            version_ref="contract-shadow/1.0.0-shadow",
        ),
        policy_ref=scope.policy_ref,
        action_attempt_id=rb.action_attempt_id(f"node-{step}-planner"),
        status=EventStatus.STARTED,
        payload={"action_id": action_id, "executor_kind": "graph_node"},
        data_governance=bridge._governance(),
        replay=bridge.events()[0].replay,
    )


# ---------------------------------------------------------------------------
# 4. A crash between the accept and the projection
# ---------------------------------------------------------------------------


class _WorkerDied(BaseException):
    """A crash the bridge's containment must not absorb.

    `BaseException`, deliberately: the containment catches `Exception` so
    the harness's own spend and network guards stay uncatchable, and a
    worker death is the same category of thing. Raising it from inside a
    projection is the closest a test can get to "the process stopped
    after the event was accepted".
    """


class TestACrashBetweenAcceptAndProjection:
    def test_the_accepted_event_survives_the_crash(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        crash_at = {"count": 0}

        def die_on_the_fourth(event: Any) -> None:
            crash_at["count"] += 1
            if crash_at["count"] == 4:
                raise _WorkerDied("the worker was killed")

        bridge = _bridge(
            tmp_path, projections=(rb.NamedProjection("dies", die_on_the_fourth),)
        )
        with pytest.raises(_WorkerDied):
            bridge.node_step("planner", step=1)

        # The process is gone; everything a later reader has is the file.
        sink = rb.JsonlTrajectorySink(tmp_path / "sink")
        written = import_jsonl(sink.read_jsonl(bridge.run_id))
        assert [event.event_type for event in written] == [
            "run.admitted",
            "attempt.started",
            "budget.established",
            "action.started",
        ]
        verify_trajectory(written)

    def test_the_crashed_run_has_no_terminal_event_rather_than_a_guessed_one(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        """RFC 10 §8.1: a crash with no terminal event is not a failure."""

        def die(event: Any) -> None:
            if event.event_type == "action.started":
                raise _WorkerDied("killed")

        bridge = _bridge(tmp_path, projections=(rb.NamedProjection("dies", die),))
        with pytest.raises(_WorkerDied):
            bridge.node_step("planner", step=1)
        written = import_jsonl(rb.JsonlTrajectorySink(tmp_path / "sink").read_jsonl(
            bridge.run_id
        ))
        assert not [
            event
            for event in written
            if event.event_type
            in {"run.completed", "run.failed", "run.cancelled", "run.budget_stopped"}
        ]

    def test_a_later_attempt_resumes_the_same_run(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        """The recovery half: the interrupted attempt is a fact, not a gap."""
        bridge = _bridge(tmp_path)
        bridge.node_step("planner", step=1)
        bridge.interrupt_attempt(
            interruption_class="worker_lost", checkpoint_id="ckpt-1"
        )
        bridge.resume_from_checkpoint(
            checkpoint_id="ckpt-1", reason="lease_expired", worker_id="worker-2"
        )
        bridge.node_step("search", step=2)
        written = import_jsonl(bridge.durable_jsonl())
        types = [event.event_type for event in written]
        assert "attempt.interrupted" in types
        assert "checkpoint.resumed" in types
        assert types.count("attempt.started") == 2
        assert {event.run_id for event in written} == {bridge.run_id}


# ---------------------------------------------------------------------------
# 5. The reconciliation fails closed
# ---------------------------------------------------------------------------


class TestTheReconciliationFailsClosed:
    def test_a_cost_discrepancy_lands_on_all_three_contracts(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        from src.observability.costs import LlmCallObservation

        bridge = _bridge(tmp_path)
        bridge.model_call(
            LlmCallObservation(
                model="claude-sonnet-4-6",
                input_tokens=1_000,
                output_tokens=200,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
                cost_usd=0.004,
                retries=0,
                latency_ms=10.0,
            )
        )
        result = bridge.reconcile(0.500)
        assert result.matched is False
        assert_bridge_triple(
            triple,
            code="invalid_provenance",
            event="trajectory_cost_reconciliation_failed",
            stage="cost_reconciliation",
        )

    def test_the_mismatch_is_itself_an_event_rather_than_only_a_log_line(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        bridge = _bridge(tmp_path)
        bridge.reconcile(0.500)
        reconciled = bridge.events()[-1]
        assert reconciled.event_type == "budget.reconciled"
        assert reconciled.status.value == "failed"
        assert reconciled.payload["result"] == "mismatch"


# ---------------------------------------------------------------------------
# 6. The chain itself is broken
# ---------------------------------------------------------------------------


class TestABrokenChain:
    def test_closing_a_tampered_run_reports_rather_than_pretends(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        """RFC 10 §12.2: corrupt rows are never silently skipped."""
        bridge = _bridge(tmp_path)
        bridge.node_step("planner", step=1)
        ledger = bridge.durable_store._runs[bridge.run_id]
        ledger.events[2] = ledger.events[2].model_copy(
            update={"event_hash": "sha256:" + "0" * 64}
        )
        bridge.close()

        records = triple.records("trajectory_chain_broken")
        assert records and records[0].error_type == "invalid_provenance"
        point = triple.point(
            TRAJECTORY_FAULTS,
            stage="chain_verification",
            error_type="invalid_provenance",
        )
        assert point.value == 1

    def test_an_intact_run_records_its_head_hash(
        self, tmp_path: Path, triple: TripleObserver
    ) -> None:
        bridge = _bridge(tmp_path)
        bridge.node_step("planner", step=1)
        bridge.close()
        assert triple.records("trajectory_chain_verified")
        sink = bridge.durable_store.sink
        assert isinstance(sink, rb.JsonlTrajectorySink)
        head = sink.head(bridge.run_id)
        assert head is not None
        assert head["head_event_hash"] == bridge.events()[-1].event_hash
