"""The runtime event bridge: durable trajectories, projections, reconciliation.

P0-WO05 proved a research run can be described by canonical events while
they live in memory and die with the worker.  This module is the next
step and only the next step: the same events, written through to a
**durable local sink**, extended to the whole RFC 10 §8 taxonomy, and
projected — never *emitted* — onto the surfaces the product already has.

Four rules shape everything below.

1. **The ledger is written first, and a projection can never unwrite
   it.**  RFC 10 §16: "Projection failures do not alter history."  So an
   accepted event is durable before any log line, span attribute or SSE
   comparison happens, and every projection runs inside a containment
   that degrades the *projection* and leaves the event alone.
2. **Nothing here decides a run's outcome.**  Same structural promise
   W05 made: every hook is `None`-tolerant, every failure is absorbed and
   latched once, and a broken bridge stops recording rather than
   stopping a job.
3. **Capture is evaluation-only, and that is enforced rather than
   documented.**  `contract_event_capture` gates the durable sink, and a
   run whose consent scope is `product_operation_only` is refused the
   sink whatever the flag says.  D8 (P0-WO09) has not ruled on retained
   user or learner content, and until it does, a durable file of a real
   learner's session is exactly the thing this work order must not
   create.
4. **A trajectory event is not a learner `ProgressEvent`.**  The guided
   learning bridge writes trajectory events and reads nothing from, and
   writes nothing to, `src.learning.progress_store`.  RFC 10 §22 item 10
   and the W08 work order both say so; the module keeps no import edge
   into that package so the rule is structural.

Storage is deliberately a local JSONL sink and not Postgres.  RFC 10
§14.1 recommends Postgres for envelopes and §20 slice 3 is the work order
that builds it; this slice's job is to prove the *contract* — ordering,
idempotency, the hash chain, artifact promotion, reconciliation — with a
backend that needs no infrastructure and no migration.  The interface is
the deliverable; the file format is an implementation detail behind it.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal, Protocol

from src.config import Settings
from src.contracts.artifact_store import (
    ArtifactStoreError,
    LocalArtifactStore,
)
from src.contracts.kernel import (
    DataClass,
    Digest,
    Rfc3339Utc,
    StrictContractModel,
    canonical_json,
    sha256_digest,
)
from src.contracts.research_binding import (
    BINDING_VERSION,
    SHADOW_CAMPAIGN_ID,
    ResearchBindingError,
    SealedEpisode,
    compiler_ref,
    deterministic_run_id,
    episode_budget,
    money,
    platform_ceiling,
    provider_snapshot,
    requested_policy,
    retention_policy_ref,
    utc_timestamp,
)
from src.contracts.run_manifest import (
    AdmissionPlan,
    AdmissionResolution,
    FakeLocalApprovalBackend,
    RunManifestError,
    resolve_admission,
)
from src.contracts.shadow_bridge import (
    ShadowRun,
    episode_block,
    observe_episode_terminal,
    observe_job_terminal,
    observe_model_call,
    observe_node,
    observe_review_answered,
    observe_review_requested,
    parity_report,
    shadow_enabled,
    shadow_run,
)
from src.contracts.task_spec import (
    GuidedSessionCompilerInput,
    ProductSurface,
    TaskDataPolicy,
    TaskSpecRef,
    TaskSpecV1,
    build_task_spec_ref,
    compile_guided_session,
    persist_compiled_task,
)
from src.contracts.trajectory import (
    Actor,
    ActorKind,
    ArtifactRef,
    ArtifactRole,
    ConsentScope,
    ContentClass,
    DataGovernance,
    EventStatus,
    IdempotencyConflict,
    InMemoryTrajectoryStore,
    ObservationStatus,
    PolicyRef,
    ProposedTrajectoryEvent,
    RedactionStatus,
    ReplayMetadata,
    ReplayOrigin,
    RunScope,
    StoredTrajectoryEvent,
    TraceRef,
    TrajectoryError,
    TrustClass,
    fold_trajectory,
    import_jsonl,
    new_event_id,
    verify_trajectory,
)
from src.observability.logging import get_logger
from src.observability.metrics import record_trajectory_event, record_trajectory_fault

log = get_logger(__name__)

#: One micro-dollar per recorded model call, plus one.  `money()`
#: quantizes every usage delta to six decimals before it is appended,
#: while `RunCosts` sums the provider's unrounded per-call figures, so
#: the two totals may legitimately disagree by up to half a unit in the
#: last place *per call*.  The constant term covers the single
#: float-to-`Decimal` conversion of the accumulator's own total.  Above
#: this the difference is not rounding, and the reconciliation fails
#: closed rather than shrugging.
RECONCILIATION_UNIT_USD: Final[Decimal] = Decimal("0.000001")

#: Directory layout of the durable sink, relative to its configured
#: root.  Documented as a constant because it is an operational fact —
#: an operator collecting a run's trajectory needs to know where it is —
#: and because a test that hard-codes the path would be pinning an
#: accident rather than a decision.
SINK_RUN_DIRECTORY: Final[str] = "runs"
SINK_EVENTS_FILE: Final[str] = "events.jsonl"
SINK_SCOPE_FILE: Final[str] = "run_scope.json"
SINK_HEAD_FILE: Final[str] = "head.json"

#: Consent scopes whose events may reach a durable local file before D8
#: rules.  Everything else — notably `product_operation_only`, which is
#: what a real API research job and a real learner session carry — is
#: recorded in memory and never written down.
CAPTURE_ELIGIBLE_CONSENT: Final[frozenset[ConsentScope]] = frozenset(
    {
        ConsentScope.EVALUATION_ONLY,
        ConsentScope.PUBLIC_SOURCE_EVALUATION,
        ConsentScope.SYNTHETIC_TEST,
    }
)

Lane = Literal["research", "guided_learning"]


class BridgeError(TrajectoryError):
    """A bridge-level refusal that is not itself a trajectory violation."""


# ---------------------------------------------------------------------------
# The durable sink
# ---------------------------------------------------------------------------


class TrajectorySink(Protocol):
    """Where an accepted event is written so it survives the worker.

    Three methods and no reader beyond `read_jsonl`, because that is the
    whole contract W08 needs: a Postgres adapter (RFC 10 §20 slice 3)
    implements the same three and the bridge above it does not change.
    """

    def open_run(self, scope: RunScope) -> None:
        """Record the immutable scope this run's events will carry."""

    def append(self, event: StoredTrajectoryEvent) -> None:
        """Durably record one accepted event, in commit order."""

    def close(self, run_id: str, *, head_event_hash: str, event_count: int) -> None:
        """Record the run's head hash so the chain can be re-verified."""

    def read_jsonl(self, run_id: str) -> str:
        """Everything written for this run, as canonical JSONL."""


class JsonlTrajectorySink:
    """A durable append-only JSONL sink under a run-scoped directory.

    Layout, for one run::

        <root>/runs/<run_id>/run_scope.json
        <root>/runs/<run_id>/events.jsonl
        <root>/runs/<run_id>/head.json

    Per run rather than one shared file, and that is the decision worth
    justifying: the logical API orders by `(run_id, run_seq)` (RFC 10
    §14.1), so a shared file would have to be filtered on read and
    fsync'd under contention from every concurrent run.  A directory per
    run makes "give me that episode" a path, makes retention deletion a
    directory removal when a policy eventually authorizes one, and makes
    two concurrent runs contend for nothing.

    Every line is flushed and fsync'd before the call returns.  That is
    slow by the standards of a log line and irrelevant by the standards
    of a graph node, and it is what makes "durable" true rather than
    aspirational: a worker killed between two nodes must leave the events
    it already accepted on disk.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    def run_directory(self, run_id: str) -> Path:
        """The directory this run's records live in."""
        if not run_id.startswith("run_") or not run_id[4:].isalnum():
            raise BridgeError(f"{run_id!r} is not a contract run id")
        return self._root / SINK_RUN_DIRECTORY / run_id

    def open_run(self, scope: RunScope) -> None:
        directory = self.run_directory(scope.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / SINK_SCOPE_FILE).write_text(
            canonical_json(scope) + "\n", encoding="utf-8"
        )
        (directory / SINK_EVENTS_FILE).touch()

    def append(self, event: StoredTrajectoryEvent) -> None:
        directory = self.run_directory(event.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        line = (canonical_json(event) + "\n").encode("utf-8")
        with self._lock:
            handle = os.open(
                directory / SINK_EVENTS_FILE,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            try:
                os.write(handle, line)
                os.fsync(handle)
            finally:
                os.close(handle)

    def close(self, run_id: str, *, head_event_hash: str, event_count: int) -> None:
        directory = self.run_directory(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / SINK_HEAD_FILE).write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "head_event_hash": head_event_hash,
                    "event_count": event_count,
                    "closed_at": utc_timestamp(),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def read_jsonl(self, run_id: str) -> str:
        path = self.run_directory(run_id) / SINK_EVENTS_FILE
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def head(self, run_id: str) -> dict[str, Any] | None:
        """The recorded head record, or `None` if the run never closed."""
        path = self.run_directory(run_id) / SINK_HEAD_FILE
        if not path.exists():
            return None
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)
        return loaded


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NamedProjection:
    """One safe projection of a canonical event onto an existing surface.

    Named because a projection failure has to say *which* surface broke:
    "the trajectory could not be projected" is not an operational
    statement, and the whole reason projections are separated from the
    accept is so one can fail without taking the others or the ledger
    with it.
    """

    name: str
    project: Callable[[StoredTrajectoryEvent], None]


def log_projection(event: StoredTrajectoryEvent) -> None:
    """Project one canonical event onto a registered structured log line.

    One event name for the whole taxonomy (`trajectory_event_recorded`)
    with the RFC 10 type in a field, rather than sixty registered log
    events.  The closed registry in `src.observability.logging` exists so
    a dashboard can be told when a name stops being emitted; sixty names
    that all mean "an event was recorded" would give that mechanism
    nothing to protect.
    """
    log.info(
        "trajectory_event_recorded",
        extra={
            "contract_run_id": event.run_id,
            "event_type": event.event_type,
            "event_seq": event.run_seq,
            "outcome": event.status.value,
        },
    )


def span_projection(event: StoredTrajectoryEvent) -> None:
    """Project one canonical event onto the currently active OTel span.

    A span *event*, not a new span: RFC 10 §16 says spans may be sampled
    without affecting the ledger, so a trace is a view of a trajectory
    and never its record.  Nothing here carries a payload — the
    attributes are the type, the sequence and the status, which is what
    lets somebody reading a trace jump to the right row of the ledger.
    """
    from opentelemetry import trace

    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.add_event(
        f"trajectory.{event.event_type}",
        attributes={
            "trajectory.run_id": event.run_id,
            "trajectory.run_seq": event.run_seq,
            "trajectory.status": event.status.value,
        },
    )


def verdict_projection(event: StoredTrajectoryEvent) -> None:
    """Emit ADR 0076's two follow-up log events off the canonical record.

    CAP-02 carried the verifier's verdict and the repair table's chosen
    action on graph state and in an SSE node delta, and could not give
    either a log event because the event registry is closed and lives in
    a package it did not own.  W08 owns that registry, so the names are
    registered — and the honest place to emit them from is the canonical
    event, because that is the record the names are supposed to describe.
    A one-line emit inside `src/agents/verifier.py` and
    `src/policies/repair.py` remains available and would say the same
    thing about the same run.
    """
    if event.event_type == "verification.completed":
        log.info(
            "verify_verdict_recorded",
            extra={
                "contract_run_id": event.run_id,
                "verdict": str(event.payload.get("verdict")),
                "event_seq": event.run_seq,
            },
        )
    elif event.event_type == "repair.requested":
        log.info(
            "repair_action_selected",
            extra={
                "contract_run_id": event.run_id,
                "repair_action": str(event.payload.get("repair_kind")),
                "event_seq": event.run_seq,
            },
        )


# ---------------------------------------------------------------------------
# The durable, projecting store
# ---------------------------------------------------------------------------


class DurableTrajectoryStore(InMemoryTrajectoryStore):
    """W04's adapter, plus a durable sink and a projection fan-out.

    Subclassing rather than wrapping, for one reason that decides it:
    `append_batch` is atomic and rolls the whole ledger back on failure,
    and a wrapper would have to reimplement that rollback to know which
    events actually landed.  Overriding `_append_locked` puts the sink
    write inside the same lock that allocates the sequence number, so the
    JSONL file's line order *is* `run_seq` order even when two branches
    append from two threads — which is the property the concurrency test
    asserts and the reason `import_jsonl` can verify the chain without
    sorting anything.

    Projections run outside that lock, after the accept has returned, and
    every one of them is contained.  An accepted event is never removed,
    never rewritten, and never withheld because something downstream
    failed.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], Rfc3339Utc],
        lane: Lane,
        sink: TrajectorySink | None = None,
        projections: Sequence[NamedProjection] = (),
    ) -> None:
        super().__init__(clock=clock)
        self._lane = lane
        self._sink = sink
        self._projections = tuple(projections)
        self._written: set[str] = set()
        self.durability_degraded = False
        self.projection_degraded = False

    @property
    def sink(self) -> TrajectorySink | None:
        return self._sink

    def register_run(self, scope: RunScope) -> None:
        super().register_run(scope)
        if self._sink is None:
            return
        try:
            self._sink.open_run(scope)
        except Exception:  # noqa: BLE001 — a sink is never allowed to fail a run
            self.durability_degraded = True
            self._sink_failed(scope.run_id, "open_run")

    def _append_locked(self, event: ProposedTrajectoryEvent) -> StoredTrajectoryEvent:
        try:
            stored = super()._append_locked(event)
        except IdempotencyConflict:
            record_trajectory_event(lane=self._lane, outcome="rejected")
            record_trajectory_fault(stage="projection", error_type="conflict")
            log.warning(
                "trajectory_append_conflict",
                extra={
                    "contract_run_id": event.run_id,
                    "event_type": event.event_type,
                    "error_type": "conflict",
                },
            )
            raise
        except TrajectoryError:
            record_trajectory_event(lane=self._lane, outcome="rejected")
            raise
        if stored.event_id in self._written:
            record_trajectory_event(lane=self._lane, outcome="deduplicated")
            return stored
        self._written.add(stored.event_id)
        record_trajectory_event(lane=self._lane, outcome="accepted")
        if self._sink is not None:
            try:
                self._sink.append(stored)
            except Exception:  # noqa: BLE001 — see the class docstring
                self.durability_degraded = True
                self._sink_failed(stored.run_id, stored.event_type)
        return stored

    def append(self, event: ProposedTrajectoryEvent) -> StoredTrajectoryEvent:
        stored = super().append(event)
        self._project(stored)
        return stored

    def append_batch(
        self, events: Sequence[ProposedTrajectoryEvent]
    ) -> tuple[StoredTrajectoryEvent, ...]:
        stored = super().append_batch(events)
        for one in stored:
            self._project(one)
        return stored

    def _project(self, event: StoredTrajectoryEvent) -> None:
        for projection in self._projections:
            try:
                projection.project(event)
            except Exception:  # noqa: BLE001 — a projection cannot unwrite history
                self.projection_degraded = True
                record_trajectory_fault(
                    stage="projection", error_type="internal_unexpected"
                )
                log.warning(
                    "trajectory_projection_failed",
                    extra={
                        "contract_run_id": event.run_id,
                        "event_type": event.event_type,
                        "stage": projection.name,
                        "error_type": "internal_unexpected",
                    },
                    exc_info=True,
                )

    @staticmethod
    def _sink_failed(run_id: str, stage: str) -> None:
        record_trajectory_fault(stage="sink_write", error_type="service_unavailable")
        log.warning(
            "trajectory_sink_write_failed",
            extra={
                "contract_run_id": run_id,
                "event_type": stage,
                "error_type": "service_unavailable",
            },
            exc_info=True,
        )

    def close_run(self, run_id: str) -> None:
        """Verify the chain and record the head hash the sink can be checked against."""
        events = self.events(run_id)
        if not events:
            return
        try:
            verify_trajectory(events)
        except TrajectoryError:
            record_trajectory_fault(
                stage="chain_verification", error_type="invalid_provenance"
            )
            log.error(
                "trajectory_chain_broken",
                extra={
                    "contract_run_id": run_id,
                    "event_count": len(events),
                    "error_type": "invalid_provenance",
                },
                exc_info=True,
            )
            return
        head = events[-1].event_hash
        if self._sink is not None:
            try:
                self._sink.close(run_id, head_event_hash=head, event_count=len(events))
            except Exception:  # noqa: BLE001
                self.durability_degraded = True
                self._sink_failed(run_id, "close")
        log.info(
            "trajectory_chain_verified",
            extra={
                "contract_run_id": run_id,
                "event_count": len(events),
                "head_event_hash": head,
            },
        )


# ---------------------------------------------------------------------------
# Cost reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CostReconciliation:
    """The comparison `budget.reconciled` records (RFC 10 §8.7)."""

    summed_event_cost: str
    run_cost_snapshot: str
    difference: str
    tolerance: str
    matched: bool
    llm_calls: int

    @property
    def result(self) -> str:
        return "match" if self.matched else "mismatch"


def reconcile_costs(
    events: Sequence[StoredTrajectoryEvent], run_cost_usd: float | Decimal | str
) -> CostReconciliation:
    """Compare the ledger's summed usage deltas with the `RunCosts` total.

    The two numbers are produced by different machinery on purpose.  The
    ledger sums the per-call `estimated_cost_usd` it appended, each
    already quantized to six decimals; `RunCosts` sums the provider's own
    unrounded figures.  Agreement within `RECONCILIATION_UNIT_USD` per
    call is arithmetic; disagreement beyond it means one side lost a
    call, double-counted one, or priced one differently — and every one
    of those is a fact about the run's accounting that a silent `round()`
    would erase.
    """
    fold = fold_trajectory(events)
    summed = Decimal(fold.total_estimated_cost_usd)
    snapshot = Decimal(str(run_cost_usd))
    difference = abs(summed - snapshot)
    tolerance = RECONCILIATION_UNIT_USD * (fold.total_llm_calls + 1)
    return CostReconciliation(
        summed_event_cost=money(summed),
        run_cost_snapshot=money(snapshot),
        difference=money(difference),
        tolerance=money(tolerance),
        matched=difference <= tolerance,
        llm_calls=fold.total_llm_calls,
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _replay_metadata() -> ReplayMetadata:
    return ReplayMetadata(
        origin=ReplayOrigin.LIVE, observation_status=ObservationStatus.OBSERVED
    )


def current_trace_ref() -> TraceRef | None:
    """The active OTel span, in the envelope's `trace_ref` shape.

    RFC 10 §16: "The OTel span id is copied into `trace_ref` when
    available."  Copied, not depended on — a sampled-out span leaves the
    field absent and changes nothing about the event.
    """
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
        if not context.is_valid:
            return None
        return TraceRef(
            trace_id=format(context.trace_id, "032x"),
            span_id=format(context.span_id, "016x"),
        )
    except Exception:  # noqa: BLE001 — telemetry never blocks a contract append
        return None


def action_attempt_id(label: str) -> str:
    """An action-attempt id in the contract's `aatt_` vocabulary."""
    cleaned = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in label.lower()
    )
    return f"aatt_{cleaned[:90] or 'action'}"


def _actor_name(raw: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in "_.-" else "_" for char in raw.lower()
    )
    return cleaned[:63] or "node"


def build_projections(
    config: Settings,
    *,
    include_verdicts: bool = True,
) -> tuple[NamedProjection, ...]:
    """The projections a bridge runs, per configuration.

    The log projection is off by default (`contract_event_log_projection`)
    because one INFO per canonical event roughly doubles a research job's
    log volume to answer a question nobody asks in production — the
    ledger is the record, and a log line about it is a debugging
    convenience.  The span and verdict projections are always on: both
    are bounded, both attach to something an operator is already reading,
    and the verdict one closes an ADR follow-up.
    """
    projections: list[NamedProjection] = [NamedProjection("otel_span", span_projection)]
    if include_verdicts:
        projections.append(NamedProjection("verdict_log", verdict_projection))
    if bool(getattr(config, "contract_event_log_projection", False)):
        projections.append(NamedProjection("event_log", log_projection))
    return tuple(projections)


def capture_permitted(config: Settings, consent: ConsentScope) -> bool:
    """Whether this run's events may be written to a durable local file.

    Two independent conditions, and the second is the D8 gate.  The
    configuration has to allow capture at all, *and* the run's consent
    scope has to be one that a purely evaluative lane can carry.  A
    production research job or a real learner session carries
    `product_operation_only`, is refused here whatever the flag says, and
    is recorded in memory exactly as W05 recorded it.
    """
    mode = str(getattr(config, "contract_event_capture", "off"))
    return mode == "evaluation_only" and consent in CAPTURE_ELIGIBLE_CONSENT


def build_sink(
    config: Settings, *, consent: ConsentScope, root: Path | str | None = None
) -> JsonlTrajectorySink | None:
    """The durable sink for this configuration, or `None` for memory only."""
    if not capture_permitted(config, consent):
        return None
    resolved = root if root is not None else getattr(config, "contract_event_sink_root", "")
    if not resolved:
        return None
    return JsonlTrajectorySink(resolved)


# ---------------------------------------------------------------------------
# The research runtime bridge
# ---------------------------------------------------------------------------


class ResearchRuntimeBridge(ShadowRun):
    """W05's shadow run, extended to the whole RFC 10 §8 taxonomy.

    Everything W05 recorded — admission, attempt, node and model
    actions, the budget warning, the plan-review pause, the candidate,
    the terminal — is inherited unchanged, so a run observed through this
    class produces a superset of the events the shadow produced and the
    parity diagnostics keep working.  What is added here is the rest of
    the taxonomy: tools, sources, evidence, claims, verification, repair,
    candidate revision and selection, budget reservations, checkpoint
    resume, the HITL outcomes that are not a plain answer, and the
    terminal `budget.reconciled`.

    Two behavioural differences from the shadow, both deliberate:

    - the ledger underneath is a `DurableTrajectoryStore`, so accepted
      events reach a run-scoped JSONL file when capture is permitted; and
    - actions take a caller-supplied key.  W05 derived one from a
      monotonic counter, which is right for a single pass and wrong for a
      resume: replaying step three after a checkpoint would mint a fourth
      action rather than recognising the third.  A stable key makes the
      replay idempotent, which is what "checkpoint resume does not
      duplicate an action" means in practice.
    """

    def __init__(
        self,
        *,
        episode: SealedEpisode,
        runtime_run_id: str,
        principal_key_id: str,
        cost_ceiling_usd: str,
        clock: Any = None,
        sink: TrajectorySink | None = None,
        projections: Sequence[NamedProjection] = (),
        artifacts: LocalArtifactStore | None = None,
    ) -> None:
        store = DurableTrajectoryStore(
            clock=clock or utc_timestamp,
            lane="research",
            sink=sink,
            projections=projections,
        )
        super().__init__(
            episode=episode,
            runtime_run_id=runtime_run_id,
            principal_key_id=principal_key_id,
            cost_ceiling_usd=cost_ceiling_usd,
            clock=clock,
            store=store,
        )
        self.durable_store = store
        self.artifacts = artifacts
        self._attempt_number = 1
        self._reconciled = False
        self._replayed: set[str] = set()

    def _first_time(self, key: str) -> bool:
        """Whether this logical step has not been recorded on this run yet."""
        with self._lock:
            if key in self._replayed:
                return False
            self._replayed.add(key)
            return True

    # -- envelope enrichment ---------------------------------------------

    def _trace_ref(self) -> TraceRef | None:
        return current_trace_ref()

    @property
    def lane(self) -> Lane:
        return "research"

    # -- keyed actions ----------------------------------------------------

    def node_step(self, node: str, *, step: int) -> None:
        """Record one graph node at a *named* position in the run.

        `step` is the caller's own step counter — the runner's node
        index, the eval driver's chunk number — and it is what makes a
        replay recognisable.  A resumed run that re-executes step three
        records nothing the second time: `_replayed` holds the keys this
        run has already written, and the pair is skipped rather than
        re-proposed.

        The guard lives here rather than in the store, and the reason is
        worth stating because it looks at first like duplicated
        idempotency.  A resume takes a *new* process lease, so the
        replayed event's envelope carries a different `attempt_id` and
        therefore a different producer semantic digest — which the store
        is right to call an `IdempotencyConflict` (RFC 10 §11.2) rather
        than silently accept.  Only the bridge knows the second
        proposal is the same logical action rather than a second one, so
        only the bridge can decline to make it.
        """
        if not self._first_time(f"node:{step}:{node}"):
            return
        attempt = action_attempt_id(f"node-{step}-{node}")
        actor = self._actor(ActorKind.AGENT, _actor_name(node))
        self._append(
            "action.started",
            f"action.started:{step}:{node}",
            {"action_id": node, "executor_kind": "graph_node"},
            status=EventStatus.STARTED,
            actor=actor,
            action_attempt_id=attempt,
        )
        self._append(
            "action.completed",
            f"action.completed:{step}:{node}",
            {
                "action_id": node,
                "observation_event_ids": [],
                "output_artifact_ids": [],
            },
            status=EventStatus.SUCCEEDED,
            actor=actor,
            action_attempt_id=attempt,
        )

    # -- plans and policy --------------------------------------------------

    def plan_created(
        self, artifact: ArtifactRef, *, objectives: int, actions: int, kind: str
    ) -> None:
        self._append(
            "plan.created",
            "plan.created",
            {
                "plan_artifact_id": artifact.artifact_id,
                "objective_count": objectives,
                "action_count": actions,
                "plan_kind": kind,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "planner"),
            artifact_refs=(artifact,),
        )

    def policy_decision(
        self,
        *,
        key: str,
        decision_kind: str,
        eligible: Sequence[str],
        chosen: str,
        reason_codes: Sequence[str] = (),
    ) -> None:
        """Record a routing decision without its reasoning.

        RFC 10 §8.1 is explicit that `policy.decision` records the choice
        and not the private deliberation behind it, and RFC 10 §10.4 adds
        that an untrusted observation may be *cited* by a decision but
        may never build its executable fields.  `chosen` is therefore a
        registered action name and never a model's prose.
        """
        self._append(
            "policy.decision",
            f"policy.decision:{key}",
            {
                "decision_kind": decision_kind,
                "eligible_actions": list(eligible),
                "chosen_action": chosen,
                "reason_codes": list(reason_codes),
                "feature_snapshot_ref": None,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.POLICY, "router"),
        )

    def compute_tier_selected(
        self,
        *,
        tier: str,
        eligible_tiers: Sequence[str],
        reason_codes: Sequence[str],
        feature_snapshot_ref: str,
        tier_budget_ref: str,
    ) -> None:
        """Record how much compute this run was allocated, and why.

        RFC 10 §8.6's `compute.tier_selected`, which the event registry
        has carried since W05 with nothing in this repository able to
        emit it — CAP-04's controller is the first policy that allocates
        compute at all, and ADR 0085 is the decision it implements.

        The payload is closed to five registered fields, which is why
        the features arrive as a *reference* rather than inline:
        `feature_snapshot_ref` is the caller's digest over the snapshot
        the decision was taken on, so two runs that saw the same
        features carry the same ref and neither carries the query. That
        is the trade `policy.decision` already makes, and it is what
        keeps a `product_operation_only` run's trajectory free of
        retained content while D8 is open (ADR 0083).

        Args:
            tier: `T0` or `T1`. `T3` is refused by the contract itself.
            eligible_tiers: What the caller's controller could have
                chosen, so a decision is readable against its own option
                set rather than against a later, wider one.
            reason_codes: The rule ids that fired, in table order.
            feature_snapshot_ref: Digest over the feature snapshot.
            tier_budget_ref: What the selected tier authorises, as a
                stable reference string.
        """
        self._append(
            "compute.tier_selected",
            f"compute.tier_selected:{tier}",
            {
                "tier": tier,
                "eligible_tiers": list(eligible_tiers),
                "feature_snapshot_ref": feature_snapshot_ref,
                "tier_budget_ref": tier_budget_ref,
                "reason_codes": list(reason_codes),
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.POLICY, "compute_controller"),
        )

    # -- tools and sources -------------------------------------------------

    def tool_call(
        self,
        *,
        call_id: str,
        tool_id: str,
        tool_version: str,
        side_effect_class: str,
        network_scope: str,
        result_kind: str,
        result_count: int,
        exit_status: str = "ok",
        cache_status: str = "miss",
        artifact: ArtifactRef | None = None,
    ) -> None:
        """Record one settled tool call as its three-event contract."""
        attempt = action_attempt_id(f"tool-{call_id}")
        actor = self._actor(ActorKind.TOOL, _actor_name(tool_id))
        self._append(
            "tool.requested",
            f"tool.requested:{call_id}",
            {
                "tool_call_id": call_id,
                "tool_id": tool_id,
                "tool_version": tool_version,
                "argument_schema_ref": f"tool-arguments/{tool_id}/1.0.0",
                "side_effect_class": side_effect_class,
                "network_scope": network_scope,
            },
            status=EventStatus.REQUESTED,
            actor=actor,
        )
        self._append(
            "tool.started",
            f"tool.started:{call_id}",
            {"tool_call_id": call_id, "sandbox_ref": "in_process"},
            status=EventStatus.STARTED,
            actor=actor,
            action_attempt_id=attempt,
        )
        self._append(
            "tool.completed",
            f"tool.completed:{call_id}",
            {
                "tool_call_id": call_id,
                "result_kind": result_kind,
                "result_count": result_count,
                "exit_status": exit_status,
                "cache_status": cache_status,
            },
            status=EventStatus.SUCCEEDED,
            actor=actor,
            action_attempt_id=attempt,
            artifact_refs=(artifact,) if artifact is not None else (),
        )

    def tool_failed(
        self,
        *,
        call_id: str,
        tool_id: str,
        tool_version: str,
        error_class: str,
        retryable: bool,
        provider_status_class: str,
        side_effect_class: str = "read_only",
        network_scope: str = "allowlisted",
    ) -> None:
        """Record a tool call that reached the boundary and failed there."""
        attempt = action_attempt_id(f"tool-{call_id}")
        actor = self._actor(ActorKind.TOOL, _actor_name(tool_id))
        self._append(
            "tool.requested",
            f"tool.requested:{call_id}",
            {
                "tool_call_id": call_id,
                "tool_id": tool_id,
                "tool_version": tool_version,
                "argument_schema_ref": f"tool-arguments/{tool_id}/1.0.0",
                "side_effect_class": side_effect_class,
                "network_scope": network_scope,
            },
            status=EventStatus.REQUESTED,
            actor=actor,
        )
        self._append(
            "tool.started",
            f"tool.started:{call_id}",
            {"tool_call_id": call_id, "sandbox_ref": "in_process"},
            status=EventStatus.STARTED,
            actor=actor,
            action_attempt_id=attempt,
        )
        self._append(
            "tool.failed",
            f"tool.failed:{call_id}",
            {
                "tool_call_id": call_id,
                "error_class": error_class,
                "retryable": retryable,
                "provider_status_class": provider_status_class,
            },
            status=EventStatus.FAILED,
            actor=actor,
            action_attempt_id=attempt,
            reason_codes=(error_class,),
        )

    def source_discovered(
        self,
        *,
        source_id: str,
        source_kind: str,
        locator_hash: str,
        published_at: str | None,
        accessed_at: str,
        accepted: bool,
        codes: Sequence[str] = (),
    ) -> None:
        """Record retrieval provenance for one candidate-visible source.

        `locator_hash` and not the URL: RFC 10 §8.3 wants provenance that
        cannot be turned back into a fetch instruction, and a hash is the
        join key an analysis needs without being one.
        """
        self._append(
            "source.discovered",
            f"source.discovered:{source_id}",
            {
                "source_id": source_id,
                "source_kind": source_kind,
                "canonical_locator_hash": locator_hash,
                "published_at": published_at,
                "accessed_at": accessed_at,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.TOOL, "arxiv_search"),
        )
        if accepted:
            self._append(
                "source.accepted",
                f"source.accepted:{source_id}",
                {
                    "source_id": source_id,
                    "admissibility_codes": list(codes),
                    "quality_signals": {},
                },
                status=EventStatus.SUCCEEDED,
                actor=self._actor(ActorKind.POLICY, "source_policy"),
            )
        else:
            self._append(
                "source.rejected",
                f"source.rejected:{source_id}",
                {"source_id": source_id, "rejection_codes": list(codes)},
                status=EventStatus.REJECTED,
                actor=self._actor(ActorKind.POLICY, "source_policy"),
            )

    # -- evidence and claims ----------------------------------------------

    def evidence_extracted(
        self,
        *,
        evidence_id: str,
        source_id: str,
        span_artifact: ArtifactRef,
        method: str,
        supports: Sequence[str] = (),
    ) -> None:
        self._append(
            "evidence.extracted",
            f"evidence.extracted:{evidence_id}",
            {
                "evidence_id": evidence_id,
                "source_id": source_id,
                "source_span_artifact_id": span_artifact.artifact_id,
                "extraction_method": method,
                "supports_task_item_ids": list(supports),
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "reader"),
            artifact_refs=(span_artifact,),
        )

    def claim_created(
        self,
        *,
        claim_id: str,
        candidate_id: str,
        artifact: ArtifactRef,
        claim_kind: str,
        location: str,
    ) -> None:
        self._append(
            "claim.created",
            f"claim.created:{claim_id}",
            {
                "claim_id": claim_id,
                "claim_artifact_id": artifact.artifact_id,
                "candidate_id": candidate_id,
                "claim_kind": claim_kind,
                "report_location_ref": location,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "synthesizer"),
            candidate_id=candidate_id,
            artifact_refs=(artifact,),
        )

    def claim_evidence_linked(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        relationship: str,
        method: str,
    ) -> None:
        self._append(
            "claim.evidence_linked",
            f"claim.evidence_linked:{claim_id}:{evidence_id}",
            {
                "claim_id": claim_id,
                "evidence_id": evidence_id,
                "relationship": relationship,
                "link_method": method,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "synthesizer"),
        )

    def coverage_assessed(
        self,
        *,
        task_items: Sequence[str],
        covered: Sequence[str],
        missing: Sequence[str],
        method: str,
    ) -> None:
        self._append(
            "evidence.coverage_assessed",
            "evidence.coverage_assessed",
            {
                "task_item_ids": list(task_items),
                "covered_item_ids": list(covered),
                "missing_item_ids": list(missing),
                "coverage_method": method,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.POLICY, "coverage"),
        )

    # -- verification and repair ------------------------------------------

    def verification(
        self,
        *,
        check_id: str,
        candidate_id: str,
        verdict: Literal["pass", "fail", "abstain"],
        check_kind: str = "groundedness",
        confidence: str = "unavailable",
        failure_codes: Sequence[str] = (),
        suggested_repair_kind: str | None = None,
        report: ArtifactRef | None = None,
        claim_outcomes: Mapping[str, bool] | None = None,
    ) -> None:
        """Record one verification, request first, as the contract orders it.

        `verdict` is `pass`, `fail` or `abstain` and nothing else, and the
        envelope status is derived from it rather than supplied: RFC 10
        §8.5 makes the verdict independent of the status precisely so a
        malformed judge cannot be projected as a pass, and W04's
        validator enforces the pairing.
        """
        attempt = action_attempt_id(f"verify-{check_id}")
        actor = self._actor(ActorKind.AGENT, "verifier")
        self._append(
            "verification.requested",
            f"verification.requested:{check_id}",
            {
                "check_id": check_id,
                "check_kind": check_kind,
                "subject_ref": f"candidate:{candidate_id}",
                "verifier_ref": f"verifier/{BINDING_VERSION}",
                "acceptance_rule_ref": f"acceptance/{check_kind}/1.0.0",
            },
            status=EventStatus.REQUESTED,
            actor=actor,
            candidate_id=candidate_id,
            action_attempt_id=attempt,
        )
        status = {
            "pass": EventStatus.SUCCEEDED,
            "fail": EventStatus.FAILED,
            "abstain": EventStatus.ABSTAINED,
        }[verdict]
        payload: dict[str, Any] = {
            "check_id": check_id,
            "verdict": verdict,
            "confidence": confidence,
            "failure_codes": list(failure_codes),
            "suggested_repair_kind": suggested_repair_kind,
        }
        if claim_outcomes is not None:
            payload["claim_outcomes"] = dict(claim_outcomes)
        self._append(
            "verification.completed",
            f"verification.completed:{check_id}",
            payload,
            status=status,
            actor=actor,
            candidate_id=candidate_id,
            action_attempt_id=attempt,
            artifact_refs=(report,) if report is not None else (),
        )

    def verification_malformed(
        self,
        *,
        check_id: str,
        candidate_id: str,
        error_class: str,
        fallback_action: str,
        check_kind: str = "groundedness",
    ) -> None:
        """Record a judge output that could not be trusted at all."""
        attempt = action_attempt_id(f"verify-{check_id}")
        actor = self._actor(ActorKind.AGENT, "verifier")
        self._append(
            "verification.requested",
            f"verification.requested:{check_id}",
            {
                "check_id": check_id,
                "check_kind": check_kind,
                "subject_ref": f"candidate:{candidate_id}",
                "verifier_ref": f"verifier/{BINDING_VERSION}",
                "acceptance_rule_ref": f"acceptance/{check_kind}/1.0.0",
            },
            status=EventStatus.REQUESTED,
            actor=actor,
            candidate_id=candidate_id,
            action_attempt_id=attempt,
        )
        self._append(
            "verification.malformed",
            f"verification.malformed:{check_id}",
            {
                "check_id": check_id,
                "error_class": error_class,
                "fallback_action": fallback_action,
            },
            status=EventStatus.FAILED,
            actor=actor,
            candidate_id=candidate_id,
            action_attempt_id=attempt,
        )

    def repair(
        self,
        *,
        repair_id: str,
        repair_kind: str,
        subject_candidate_id: str,
        result_artifact: ArtifactRef | None = None,
        target_refs: Sequence[str] = (),
        changed_scope: str = "section",
        succeeded: bool = True,
        error_class: str = "internal_unexpected",
    ) -> str | None:
        """Record one bounded repair, producing a child candidate.

        Never an overwrite: RFC 10 §8.5 requires the repaired candidate
        to be a *new child*, so a failed repair leaves the subject
        readable and a successful one leaves both versions in the
        lineage.  Arm C's proof obligation — "the child candidate was
        re-verified before final selection" — is a query over these
        events, which is why they exist rather than a boolean on state.

        Returns:
            The child candidate id, or `None` when the repair failed.
        """
        self._append(
            "repair.requested",
            f"repair.requested:{repair_id}",
            {
                "repair_id": repair_id,
                "repair_kind": repair_kind,
                "subject_candidate_id": subject_candidate_id,
                "target_refs": list(target_refs),
                "repair_budget_ref": f"budget:{repair_id}",
            },
            status=EventStatus.REQUESTED,
            actor=self._actor(ActorKind.POLICY, "repair_policy"),
            candidate_id=subject_candidate_id,
        )
        if not succeeded or result_artifact is None:
            self._append(
                "repair.failed",
                f"repair.failed:{repair_id}",
                {
                    "repair_id": repair_id,
                    "error_class": error_class,
                    "candidate_unchanged": True,
                },
                status=EventStatus.FAILED,
                actor=self._actor(ActorKind.AGENT, "repair"),
                candidate_id=subject_candidate_id,
                reason_codes=(error_class,),
            )
            return None
        child = self.candidate_revised(
            parent_candidate_id=subject_candidate_id,
            artifact=result_artifact,
            change_scope=changed_scope,
            key=repair_id,
        )
        self._append(
            "repair.completed",
            f"repair.completed:{repair_id}",
            {
                "repair_id": repair_id,
                "result_candidate_id": child,
                "changed_scope": changed_scope,
                "verification_required": True,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "repair"),
            candidate_id=subject_candidate_id,
            artifact_refs=(result_artifact,),
        )
        return child

    def repair_exhausted(
        self, *, subject_candidate_id: str, attempted: Sequence[str], reason: str
    ) -> None:
        self._append(
            "repair.exhausted",
            f"repair.exhausted:{subject_candidate_id}",
            {
                "subject_candidate_id": subject_candidate_id,
                "attempted_repair_ids": list(attempted),
                "stop_reason_code": reason,
            },
            status=EventStatus.FAILED,
            actor=self._actor(ActorKind.POLICY, "repair_policy"),
            candidate_id=subject_candidate_id,
        )

    # -- finalization over an existing candidate ---------------------------

    def record_candidate(self, report: str) -> ArtifactRef:
        """Record the root candidate and its report artifact.

        The bytes go to the artifact store when one is configured, and
        become a digest-only reference when one is not — which is W05's
        behaviour and the behaviour a production job keeps until D8 rules.
        """
        stored = self.store_artifact(
            report.encode("utf-8"), role=ArtifactRole.CANDIDATE_REPORT
        )
        if stored is None:
            # Refused content. W05's digest-only path still records which
            # report the run produced, which is strictly better than a
            # candidate the ledger cannot name at all.
            return self._record_candidate(report)
        candidate_id = "cand_" + stored.digest.removeprefix("sha256:")[:24]
        self._candidate_id = candidate_id
        self._final_artifact = stored
        self._append(
            "candidate.created",
            "candidate.created",
            {
                "candidate_id": candidate_id,
                "candidate_kind": "research_report",
                "artifact_id": stored.artifact_id,
                "generation_method": "graph_synthesis",
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "synthesizer"),
            candidate_id=candidate_id,
            artifact_refs=(stored,),
        )
        return stored

    def finalize(
        self,
        *,
        candidate_id: str,
        artifact: ArtifactRef,
        selection_basis: str,
        verification_event_ids: Sequence[str] = (),
        unresolved_issue_codes: Sequence[str] = (),
        partial: bool = False,
    ) -> None:
        """Close a run on a candidate that already exists.

        W05's `complete()` creates the candidate and finalizes it in one
        call, which is right for a single-candidate policy and wrong the
        moment a repair produces a child: finalizing the *original*
        report after repairing it would record a deliverable the run did
        not actually choose.  Arm C's fifth proof obligation — the child
        candidate was re-verified before final selection — is only
        checkable if the final events name the child, so they take one.
        """
        self._final_artifact = artifact
        self._candidate_id = candidate_id
        self._append(
            "final.candidate_selected",
            "final.candidate_selected",
            {
                "candidate_id": candidate_id,
                "selection_basis": selection_basis,
                "verification_event_ids": list(verification_event_ids),
                "unresolved_issue_codes": list(unresolved_issue_codes),
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.POLICY, "runtime_bridge"),
            candidate_id=candidate_id,
        )
        final = artifact.model_copy(update={"role": ArtifactRole.FINAL_REPORT})
        self._append(
            "final.artifact_produced",
            "final.artifact_produced",
            {
                "candidate_id": candidate_id,
                "artifact_id": artifact.artifact_id,
                "deliverable_kind": "research_report",
                "partial": partial,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "synthesizer"),
            candidate_id=candidate_id,
            artifact_refs=(final,),
        )
        self._append(
            "run.completed",
            "run.completed",
            {
                "final_candidate_id": candidate_id,
                "final_artifact_id": artifact.artifact_id,
                "stop_reason_code": "completed",
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "runtime_bridge"),
            candidate_id=candidate_id,
            artifact_refs=(final,),
            reason_codes=("completed",),
        )
        self._terminal = True

    # -- candidates (stub lifecycle) ---------------------------------------

    def candidate_revised(
        self,
        *,
        parent_candidate_id: str,
        artifact: ArtifactRef,
        change_scope: str,
        key: str,
    ) -> str:
        """Record a revised candidate and return its new id.

        A *stub* in the work-order's sense: the shipped fixed policy
        produces one candidate per run, so nothing in the product calls
        this on the ordinary path.  It exists because Arm C's repair
        produces a child and Arm E's branching would produce several, and
        a lineage vocabulary invented at the moment it is first needed is
        a lineage vocabulary that disagrees with the RFC.
        """
        candidate_id = "cand_" + artifact.digest.removeprefix("sha256:")[:24]
        self._append(
            "candidate.revised",
            f"candidate.revised:{key}",
            {
                "candidate_id": candidate_id,
                "parent_candidate_id": parent_candidate_id,
                "artifact_id": artifact.artifact_id,
                "change_scope": change_scope,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "repair"),
            candidate_id=candidate_id,
            artifact_refs=(artifact,),
        )
        return candidate_id

    def candidate_selected(
        self,
        *,
        eligible: Sequence[str],
        selected: str,
        selector_kind: str,
        selection_artifact: ArtifactRef,
    ) -> None:
        self._append(
            "candidate.selected",
            f"candidate.selected:{selected}",
            {
                "eligible_candidate_ids": list(eligible),
                "selected_candidate_id": selected,
                "selector_kind": selector_kind,
                "selection_artifact_id": selection_artifact.artifact_id,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.POLICY, "selector"),
            candidate_id=selected,
            artifact_refs=(selection_artifact,),
        )

    # -- budget ------------------------------------------------------------

    def budget_reserved(
        self, *, reservation_id: str, action_id: str, maximum_cost: str, ttl_seconds: int
    ) -> None:
        """Record a pre-call reservation (RFC 10 §8.7).

        Reservations exist so concurrent workers cannot each pass a stale
        remaining-budget check.  This bridge records them; it does not
        *enforce* them — the enforcing authority is the cost accumulator
        in `src.observability.costs`, and a candidate policy that could
        write its own accepted budget event would be exactly the conflict
        of interest RFC 10 forbids.
        """
        expires = datetime.now(UTC) + timedelta(seconds=max(1, ttl_seconds))
        self._append(
            "budget.reserved",
            f"budget.reserved:{reservation_id}",
            {
                "reservation_id": reservation_id,
                "action_id": action_id,
                "maximum_cost": maximum_cost,
                "expires_at": utc_timestamp(expires),
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "budget_authority"),
        )

    def budget_reservation_released(
        self, *, reservation_id: str, actual_cost: str, reason: str
    ) -> None:
        self._append(
            "budget.reservation_released",
            f"budget.reservation_released:{reservation_id}",
            {
                "reservation_id": reservation_id,
                "actual_cost": actual_cost,
                "release_reason": reason,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "budget_authority"),
        )

    def reconcile(self, run_cost_usd: float | Decimal | str) -> CostReconciliation:
        """Append the terminal `budget.reconciled` fact and return it.

        Appended *after* the terminal run event, which W04's registry
        allows for exactly this type: the question "did the ledger and
        the accumulator agree" cannot be answered until the run is over,
        and answering it before the terminal would mean reconciling a
        number that was still moving.

        A difference beyond tolerance fails closed — status `failed`, an
        `integrity_failure` reason code, its own WARNING and its own
        metric point — rather than being logged and rounded away.
        """
        result = reconcile_costs(self.events(), run_cost_usd)
        if self._reconciled:
            return result
        self._reconciled = True
        self._append(
            "budget.reconciled",
            "budget.reconciled",
            {
                "summed_event_cost": result.summed_event_cost,
                "run_cost_snapshot": result.run_cost_snapshot,
                "difference": result.difference,
                "result": result.result,
            },
            status=EventStatus.SUCCEEDED if result.matched else EventStatus.FAILED,
            actor=self._actor(ActorKind.SYSTEM, "cost_accumulator"),
            reason_codes=() if result.matched else ("integrity_failure",),
        )
        _log_reconciliation(self.run_id, result)
        return result

    # -- attempts and checkpoints ------------------------------------------

    def interrupt_attempt(
        self, *, interruption_class: str, checkpoint_id: str | None
    ) -> None:
        """Record that this process stopped without declaring the run over.

        RFC 10 §8.1: a crash with no terminal run event is an interrupted
        attempt, not an implicit failure.  Recording it is what lets a
        later attempt resume the same logical run instead of a reader
        having to guess whether the silence meant success.
        """
        self._append(
            "attempt.interrupted",
            f"attempt.interrupted:{self._attempt_number}",
            {
                "attempt_id": self.attempt_id,
                "interruption_class": interruption_class,
                "last_checkpoint_id": checkpoint_id,
                "side_effect_reconciliation_required": True,
            },
            status=EventStatus.INTERRUPTED,
            actor=self._actor(ActorKind.SYSTEM, "runtime_bridge"),
        )

    def resume_from_checkpoint(
        self, *, checkpoint_id: str, reason: str, worker_id: str
    ) -> None:
        """Start a new process attempt on the same logical run.

        The new attempt gets a new id — a lease is a process, and two
        processes advancing one run must be distinguishable — while the
        action keys, the candidate ids and the cost fold carry over
        untouched.  That combination is the whole of "resume does not
        duplicate an action or reset cost": nothing is re-minted except
        the lease.
        """
        self._attempt_number += 1
        entropy = uuid.uuid5(
            uuid.NAMESPACE_URL, f"{self.run_id}:attempt:{self._attempt_number}"
        )
        self._attempt_id = f"att_{entropy.hex}"
        self._append(
            "attempt.started",
            f"attempt.started:{self._attempt_number}",
            {
                "entrypoint": self.episode.origin,
                "main_branch_id": "branch_main",
                "effective_budget_ref": f"budget:{self.run_id[:23]}",
                "resume_checkpoint_id": checkpoint_id,
            },
            status=EventStatus.STARTED,
            actor=self._actor(ActorKind.SYSTEM, "runtime_bridge"),
        )
        self._append(
            "checkpoint.resumed",
            f"checkpoint.resumed:{checkpoint_id}",
            {
                "checkpoint_id": checkpoint_id,
                "resume_reason": reason,
                "resuming_worker_id": worker_id,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "checkpointer"),
        )

    def checkpoint_saved(
        self,
        *,
        checkpoint_id: str,
        graph_position: str,
        artifact: ArtifactRef | None = None,
        resumable: bool = True,
    ) -> None:
        self._append(
            "checkpoint.saved",
            f"checkpoint.saved:{checkpoint_id}",
            {
                "checkpoint_id": checkpoint_id,
                "checkpoint_artifact_id": (
                    artifact.artifact_id if artifact is not None else None
                ),
                "graph_position": graph_position,
                "resumable": resumable,
                "state_schema_ref": "research-state/1.0.0",
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "checkpointer"),
            artifact_refs=(artifact,) if artifact is not None else (),
        )

    def checkpoint_invalid(
        self, *, checkpoint_id: str, failure_codes: Sequence[str], fallback: str
    ) -> None:
        self._append(
            "checkpoint.invalid",
            f"checkpoint.invalid:{checkpoint_id}",
            {
                "checkpoint_id": checkpoint_id,
                "failure_codes": list(failure_codes),
                "fallback": fallback,
            },
            status=EventStatus.REJECTED,
            actor=self._actor(ActorKind.SYSTEM, "checkpointer"),
        )

    # -- HITL outcomes beyond a plain answer --------------------------------

    def review_timed_out(self, *, pause_number: int, policy: str) -> None:
        self._append(
            "hitl.timed_out",
            f"hitl.timed_out:{pause_number}",
            {"request_id": f"plan-review-{pause_number}", "timeout_policy": policy},
            status=EventStatus.TIMED_OUT,
            actor=self._actor(ActorKind.SYSTEM, "runtime_bridge"),
        )
        self._open_hitl = None

    def review_cancelled(self, *, pause_number: int, reason: str) -> None:
        self._append(
            "hitl.cancelled",
            f"hitl.cancelled:{pause_number}",
            {"request_id": f"plan-review-{pause_number}", "reason_code": reason},
            status=EventStatus.CANCELLED,
            actor=self._actor(ActorKind.SYSTEM, "runtime_bridge"),
        )
        self._open_hitl = None

    def failure_recorded(
        self,
        *,
        failure_id: str,
        failure_class: str,
        stage: str,
        retryable: bool,
        safe_message: str,
    ) -> None:
        """Record a non-terminal diagnostic without leaking its detail."""
        self._append(
            "failure.recorded",
            f"failure.recorded:{failure_id}",
            {
                "failure_id": failure_id,
                "failure_class": failure_class,
                "stage": stage,
                "retryable": retryable,
                "safe_message": safe_message[:200],
            },
            status=EventStatus.FAILED,
            actor=self._actor(ActorKind.SYSTEM, "runtime_bridge"),
            reason_codes=(failure_class,),
        )

    # -- artifacts ----------------------------------------------------------

    def store_artifact(
        self,
        content: bytes,
        *,
        role: ArtifactRole,
        media_type: str = "text/markdown",
        schema_ref: str = "research-report/1.0.0",
        trust_class: TrustClass = TrustClass.SYSTEM_GENERATED,
        source_artifact_ids: Sequence[str] = (),
    ) -> ArtifactRef | None:
        """Promote bytes into the run's artifact store, or record a refusal.

        Three outcomes, and each is the honest answer to a different
        question.  With a store configured the bytes are promoted and the
        reference names real content.  With no store — a production job,
        or capture switched off — the reference is digest-only, which is
        W05's behaviour and the truthful way to say "this run produced
        exactly these bytes and nobody wrote them down".  A *refusal* is
        `None`, logged with the rule that refused it: a report that
        happened to quote a presigned URL must still finish the run, must
        not persist that URL, and must not be discovered by noticing an
        event that never appeared.
        """
        if self.artifacts is None:
            return _content_ref(
                content.decode("utf-8", errors="replace"),
                role=role,
                data_class=self._scope.task_data_class,
                retention=self._scope.retention_policy_ref,
                schema_ref=schema_ref,
            )
        try:
            ref = self.artifacts.put(
                content,
                role=role,
                media_type=media_type,
                schema_ref=schema_ref,
                trust_class=trust_class,
                data_class=self._scope.task_data_class,
                retention_policy_ref=self._scope.retention_policy_ref,
                principal_key_id=self._scope.principal_key_id,
                source_artifact_ids=source_artifact_ids,
            )
        except ArtifactStoreError as exc:
            record_trajectory_fault(
                stage="artifact_integrity", error_type=exc.app_error_code
            )
            log.warning(
                "trajectory_artifact_rejected",
                extra={
                    "contract_run_id": self.run_id,
                    "artifact_role": role.value,
                    "byte_length": len(content),
                    "error_type": exc.app_error_code,
                    "detail": exc.detail[:200],
                },
            )
            return None
        log.info(
            "trajectory_artifact_promoted",
            extra={
                "contract_run_id": self.run_id,
                "artifact_id": ref.artifact_id,
                "artifact_role": ref.role.value,
                "byte_length": ref.byte_length,
                "data_class": ref.data_class.value,
            },
        )
        return ref

    # -- closing ------------------------------------------------------------

    def note_model_capabilities(self, model_id: str) -> None:
        """Warn once per run when a model has no declared capability row.

        ADR 0077's second follow-up.  `unknown_model_pricing_fallback`
        covers the priced population; this covers the *capability* table,
        which is a different question — a model can be priced and still
        have no declared sampling or effort profile, so its request is
        built from a default rather than from a described one.
        """
        try:
            from src.llm_models import undescribed_models

            missing = undescribed_models([model_id])
        except Exception:  # noqa: BLE001 — a diagnostic never fails a run
            return
        if not missing:
            return
        log.warning(
            "unknown_model_capability_fallback",
            extra={"contract_run_id": self.run_id, "model": model_id},
        )

    def close(self) -> None:
        """Verify the chain and record the head hash the sink can be checked against."""
        self.durable_store.close_run(self.run_id)

    def durable_jsonl(self) -> str:
        """This run's trajectory as written to the durable sink, if any."""
        sink = self.durable_store.sink
        if sink is None:
            return ""
        return sink.read_jsonl(self.run_id)


def _log_reconciliation(run_id: str, result: CostReconciliation) -> None:
    fields = {
        "contract_run_id": run_id,
        "summed_event_cost": result.summed_event_cost,
        "run_cost_snapshot": result.run_cost_snapshot,
        "difference": result.difference,
        "tolerance": result.tolerance,
        "result": result.result,
    }
    if result.matched:
        log.info("trajectory_cost_reconciled", extra=fields)
        return
    record_trajectory_fault(
        stage="cost_reconciliation", error_type="invalid_provenance"
    )
    log.warning(
        "trajectory_cost_reconciliation_failed",
        extra={**fields, "error_type": "invalid_provenance"},
    )


# ---------------------------------------------------------------------------
# The guided-learning bridge
# ---------------------------------------------------------------------------


class GuidedSessionBinding(StrictContractModel):
    """What a guided-learning episode is sealed against, in place of a manifest.

    RFC 09's `RunManifestPayload` requires a `PolicySnapshot`, and that
    snapshot enumerates exactly the five research arms A–E.  A guided
    reading session is not one of them and pretending otherwise would put
    a false arm id on a sealed control-plane object — which is worse than
    having no manifest, because a false arm id is a claim an experiment
    would later read as evidence.

    So the learning lane seals *this* instead: the compiled TaskSpec's
    reference, the compilation receipt digest, the real admission
    resolution (which fails closed on a metered provider exactly as the
    research lane's does), and the session graph's digest.  Its own
    digest is what the trajectory's `manifest_digest` carries, and the
    honest reading of that field for this lane is "the sealed binding
    this run was admitted under".  Extending RFC 09's policy snapshot to
    express a non-arm policy is a contract change and belongs to whoever
    takes that RFC's next revision, not to a bridge.
    """

    schema_kind: Literal["guided-session-binding"] = "guided-session-binding"
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_ref: TaskSpecRef
    receipt_digest: Digest
    admission: AdmissionResolution
    graph_digest: Digest
    policy_id: Literal["guided_read_session"] = "guided_read_session"
    policy_version: str
    environment_class: str
    product_lane: Literal["guided_learning"] = "guided_learning"
    sealed_at: Rfc3339Utc


def _learning_data_policy() -> TaskDataPolicy:
    """The strictest default, as W09's acceptance criteria require.

    "Learner data receives the strictest default" is not a preference
    here: `learner_sensitive` is the top of the `DataClass` lattice, so
    every event and artifact of a session inherits it, no artifact can be
    promoted below it, and every read of one is principal-scoped.
    """
    from src.contracts.research_binding import _ref  # noqa: PLC0415

    return TaskDataPolicy(
        policy_ref=_ref(
            "data_policy",
            "guided-learning-no-training",
            {"training_use": "prohibited", "surface": "guided_learning_api"},
        ),
        data_class=DataClass.LEARNER_SENSITIVE,
        processing_purposes=("product_operation",),
        retention_policy_ref=retention_policy_ref(),
    )


def compile_guided_session_intake(
    config: Settings,
    *,
    task_id: str,
    path_id: str,
    resource_id: str,
    title: str,
    available_minutes: int,
    content_entry_digest: str,
    learner_profile_digest: str,
    compiled_at: str | None = None,
) -> TaskSpecV1:
    """Compile one guided-reading session into an immutable TaskSpec.

    The learner's own text never reaches this function.  What it takes is
    the *access-checked metadata* the session is about — which path,
    which resource, its title, how long the learner has — plus content
    digests for the two context objects.  That is precisely RFC 08's
    guided-session compiler input, and it is why a session TaskSpec can
    be recorded at all under the strictest data class.
    """
    from src.contracts.research_binding import _ref  # noqa: PLC0415

    requested = requested_policy(
        config, ProductSurface.GUIDED_LEARNING_API, supervisor=False
    ).model_copy(update={"data_policy": _learning_data_policy()})
    ceiling = platform_ceiling(config, requested)
    return compile_guided_session(
        GuidedSessionCompilerInput(
            task_id=task_id,
            path_id=path_id,
            resource_id=resource_id,
            title=title,
            available_minutes=available_minutes,
            content_entry_ref=_ref(
                "content_entry",
                f"{path_id}-{resource_id}"[:127],
                {"digest": content_entry_digest},
            ),
            learner_profile_snapshot_ref=_ref(
                "learner_profile_snapshot",
                "learner-profile-snapshot",
                {"digest": learner_profile_digest},
            ),
        ),
        requested_policy=requested,
        platform_policy=ceiling,
        compiler_ref=compiler_ref(),
        compiled_at=compiled_at or utc_timestamp(),
    )


def seal_guided_session(
    config: Settings,
    *,
    spec: TaskSpecV1,
    graph_digest: str,
    sealed_at: str | None = None,
) -> GuidedSessionBinding:
    """Resolve admission for a session and seal its binding record.

    Uses the *same* admission controller as the research lane, which is
    the point: a metered provider with no approval fails closed here too,
    so a guided-learning trajectory cannot come into existence on a
    configuration that was never authorized to spend.
    """
    moment = sealed_at or utc_timestamp()
    task_ref = build_task_spec_ref(
        spec, artifact_locator=f"cas://sha256/{sha256_digest(spec).removeprefix('sha256:')}"
    )
    receipt = persist_compiled_task(
        spec, _NullTaskStore(), artifact_locator=task_ref.artifact_locator
    )
    from src.contracts.research_binding import _bundle_from_spec  # noqa: PLC0415

    bundle = _bundle_from_spec(spec)
    provider = provider_snapshot(config)
    try:
        decision = resolve_admission(
            AdmissionPlan(
                campaign_id=SHADOW_CAMPAIGN_ID,
                stage="shadow-stage-0",
                provider=provider.llm.provider,
                task_policy=bundle,
                effective_policy=bundle,
                platform_workflow_cost_usd="0.000000",
                campaign_workflow_allocation_usd="0.000000",
                provider_workflow_cost_usd="0.000000",
                episode_budget=episode_budget(spec),
                provider_metered=provider.llm.metered,
            ),
            verified_at=moment,
            approval_backend=FakeLocalApprovalBackend(),
        )
    except RunManifestError as exc:
        raise ResearchBindingError(
            f"guided-learning admission failed closed: {exc.detail}"
        ) from exc
    return GuidedSessionBinding(
        task_ref=task_ref,
        receipt_digest=sha256_digest(receipt),
        admission=decision.resolution,
        graph_digest=graph_digest,
        policy_version=f"{BINDING_VERSION}-learning",
        environment_class="local-eval" if config.use_mock_data else "production",
        sealed_at=moment,
    )


class _NullTaskStore:
    """A task store that stores nothing, for a lane that persists nothing."""

    def put(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def get(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class GuidedLearningBridge:
    """One guided-reading session, as a canonical trajectory.

    The session's lifecycle in RFC 10's vocabulary: `run.admitted` for
    the sealed binding, `attempt.started`, an action pair per session
    graph node, `checkpoint.saved` + `hitl.requested` at every learner
    turn, `hitl.responded` + `checkpoint.resumed` when the learner
    answers, `final.candidate_selected` / `final.artifact_produced` for
    the closing summary, and one terminal event.

    **It writes no `ProgressEvent` and derives none.**  That is the
    single most important sentence in this class.  A learner's progress
    ledger is a separately validated, principal-scoped, learner-owned
    record with its own provenance rules (`src.learning.progress_store`,
    ADR 0058); a trajectory is an operational record of what a policy
    did.  Deriving one from the other would launder an operational fact
    into a claim about a person's understanding, which is exactly what
    RFC 10 §22 item 10 and W08's work order forbid.  There is no import
    edge from this module into `src.learning`, so the rule is structural
    rather than remembered.
    """

    def __init__(
        self,
        *,
        binding: GuidedSessionBinding,
        spec: TaskSpecV1,
        runtime_run_id: str,
        principal_key_id: str,
        cost_ceiling_usd: str,
        synthetic: bool,
        clock: Callable[[], Rfc3339Utc] | None = None,
        sink: TrajectorySink | None = None,
        projections: Sequence[NamedProjection] = (),
        artifacts: LocalArtifactStore | None = None,
    ) -> None:
        self.binding = binding
        self.spec = spec
        self.runtime_run_id = runtime_run_id
        self.cost_ceiling_usd = cost_ceiling_usd
        self.degraded = False
        self.artifacts = artifacts
        self._synthetic = synthetic
        self._clock = clock or utc_timestamp
        self._terminal = False
        self._candidate_id: str | None = None
        self._final_artifact: ArtifactRef | None = None
        self._open_turn: int | None = None
        self._reconciled = False
        self._attempt_id = f"att_{uuid.uuid5(uuid.NAMESPACE_URL, runtime_run_id).hex}"
        self._policy_ref = PolicyRef(
            policy_id=binding.policy_id,
            policy_version=binding.policy_version,
            policy_digest=sha256_digest(binding),
        )
        self._scope = RunScope(
            run_id=deterministic_run_id(runtime_run_id),
            task_spec_id=spec.task_spec_id,
            task_revision=spec.task_revision,
            task_spec_full_digest=binding.task_ref.full_digest,
            manifest_digest=sha256_digest(binding),
            principal_key_id=principal_key_id,
            policy_ref=self._policy_ref,
            task_data_class=spec.data_policy.data_class,
            retention_policy_ref=retention_policy_ref(),
            experiment_arm=None,
        )
        self.durable_store = DurableTrajectoryStore(
            clock=self._clock,
            lane="guided_learning",
            sink=sink,
            projections=projections,
        )
        self.store = self.durable_store
        self.store.register_run(self._scope)

    # -- identity ---------------------------------------------------------

    @property
    def run_id(self) -> str:
        return self._scope.run_id

    @property
    def lane(self) -> Lane:
        return "guided_learning"

    @property
    def consent_scope(self) -> ConsentScope:
        return (
            ConsentScope.SYNTHETIC_TEST
            if self._synthetic
            else ConsentScope.PRODUCT_OPERATION_ONLY
        )

    def _event_id(self, key: str) -> str:
        return new_event_id(entropy=uuid.uuid5(uuid.NAMESPACE_URL, f"{self.run_id}:{key}"))

    def _actor(self, kind: ActorKind, name: str) -> Actor:
        return Actor(
            kind=kind,
            name=name,
            instance_id="guided-learning-bridge",
            version_ref=f"guided-learning-bridge/{self.binding.policy_version}",
        )

    def _governance(self) -> DataGovernance:
        return DataGovernance(
            content_class=ContentClass.METADATA,
            effective_data_class=self._scope.task_data_class,
            consent_scope=self.consent_scope,
            redaction_status=RedactionStatus.NOT_APPLICABLE,
            contains_user_content=False,
        )

    def _append(
        self,
        event_type: str,
        key: str,
        payload: Mapping[str, Any],
        *,
        status: EventStatus,
        actor: Actor,
        with_attempt: bool = True,
        candidate_id: str | None = None,
        action_attempt_id_: str | None = None,
        artifact_refs: tuple[ArtifactRef, ...] = (),
        reason_codes: tuple[str, ...] = (),
    ) -> StoredTrajectoryEvent:
        event = ProposedTrajectoryEvent(
            event_type=event_type,
            event_id=self._event_id(key),
            idempotency_key=f"{self.run_id}:{key}"[:256],
            run_id=self.run_id,
            attempt_id=self._attempt_id if with_attempt else None,
            task_spec_id=self._scope.task_spec_id,
            task_revision=self._scope.task_revision,
            task_spec_full_digest=self._scope.task_spec_full_digest,
            manifest_digest=self._scope.manifest_digest,
            principal_key_id=self._scope.principal_key_id,
            occurred_at=self._clock(),
            actor=actor,
            policy_ref=self._policy_ref,
            trace_ref=current_trace_ref(),
            candidate_id=candidate_id,
            action_attempt_id=action_attempt_id_,
            status=status,
            reason_codes=reason_codes,
            payload=dict(payload),
            artifact_refs=artifact_refs,
            data_governance=self._governance(),
            replay=_replay_metadata(),
        )
        return self.store.append(event)

    # -- lifecycle --------------------------------------------------------

    def open(self) -> None:
        """Record admission, the process attempt, and the session's ceiling."""
        receipt = self.binding.admission.receipt_ref
        self._append(
            "run.admitted",
            "run.admitted",
            {
                "admission_receipt_ref": receipt.id,
                "admission_receipt_digest": receipt.digest,
                "environment_class": self.binding.environment_class,
                "product_lane": "guided_learning",
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "admission_controller"),
            with_attempt=False,
        )
        self._append(
            "attempt.started",
            "attempt.started",
            {
                "entrypoint": "guided_learning_api",
                "main_branch_id": "branch_main",
                "effective_budget_ref": f"budget:{self.run_id[:23]}",
                "resume_checkpoint_id": None,
            },
            status=EventStatus.STARTED,
            actor=self._actor(ActorKind.SYSTEM, "guided_learning_bridge"),
        )
        self._append(
            "budget.established",
            "budget.established",
            {
                "budget_id": "session_cost_ceiling",
                "currency": "USD",
                "episode_cap": self.cost_ceiling_usd,
                "campaign_cap_ref": f"binding:{sha256_digest(self.binding)[:23]}",
                "limit_dimensions": ["cost_usd", "model_calls", "turns"],
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "guided_learning_bridge"),
        )
        log.info(
            "trajectory_run_opened",
            extra={"contract_run_id": self.run_id, "lane": self.lane},
        )

    def node_step(self, node: str, *, step: int) -> None:
        """Record one session graph node as a keyed action pair."""
        attempt = action_attempt_id(f"session-{step}-{node}")
        actor = self._actor(ActorKind.AGENT, _actor_name(node))
        self._append(
            "action.started",
            f"action.started:{step}:{node}",
            {"action_id": node, "executor_kind": "session_node"},
            status=EventStatus.STARTED,
            actor=actor,
            action_attempt_id_=attempt,
        )
        self._append(
            "action.completed",
            f"action.completed:{step}:{node}",
            {
                "action_id": node,
                "observation_event_ids": [],
                "output_artifact_ids": [],
            },
            status=EventStatus.SUCCEEDED,
            actor=actor,
            action_attempt_id_=attempt,
        )

    def turn_paused(self, *, turn: int, graph_position: str, deadline_seconds: int) -> None:
        """Record the checkpoint and the learner-turn pause the session parks on.

        The existing `turn_ready` SSE frame is a *projection* of this
        `hitl.requested` (RFC 10 §8.8 says so in as many words); the
        canonical write happens here and the frame the browser receives
        is unchanged.
        """
        self._append(
            "checkpoint.saved",
            f"checkpoint.saved:{turn}",
            {
                "checkpoint_id": f"{self.run_id}:turn:{turn}",
                "checkpoint_artifact_id": None,
                "graph_position": graph_position or "unknown",
                "resumable": True,
                "state_schema_ref": "session-state/1.0.0",
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "checkpointer"),
        )
        deadline = datetime.now(UTC) + timedelta(seconds=max(1, deadline_seconds))
        self._append(
            "hitl.requested",
            f"hitl.requested:{turn}",
            {
                "request_id": f"learner-turn-{turn}",
                "request_kind": "learner_turn",
                "subject_ref": f"task_spec:{self._scope.task_spec_id}",
                "allowed_responses": ["respond", "skip", "end_session"],
                "deadline_at": utc_timestamp(deadline),
            },
            status=EventStatus.REQUESTED,
            actor=self._actor(ActorKind.SYSTEM, "guided_learning_bridge"),
        )
        self._open_turn = turn

    def turn_resumed(self, *, turn: int, response_kind: str) -> None:
        """Record the learner's answer and the resume it unblocks.

        `response_kind` is a bounded enum member and never the learner's
        prose.  The prose is `human_input` content: it stays in the
        session's own store under the learner's consent, and it reaches
        the trajectory not at all until D8 says otherwise.
        """
        if self._open_turn is None:
            return
        self._append(
            "hitl.responded",
            f"hitl.responded:{turn}",
            {
                "request_id": f"learner-turn-{turn}",
                "response_kind": response_kind,
                "response_artifact_id": None,
                "responder_principal_ref": self._scope.principal_key_id,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.HUMAN, "learner"),
        )
        self._append(
            "checkpoint.resumed",
            f"checkpoint.resumed:{turn}",
            {
                "checkpoint_id": f"{self.run_id}:turn:{turn}",
                "resume_reason": "learner_responded",
                "resuming_worker_id": self.runtime_run_id[:64],
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "checkpointer"),
        )
        self._open_turn = None

    def turn_timed_out(self, *, turn: int, policy: str) -> None:
        self._append(
            "hitl.timed_out",
            f"hitl.timed_out:{turn}",
            {"request_id": f"learner-turn-{turn}", "timeout_policy": policy},
            status=EventStatus.TIMED_OUT,
            actor=self._actor(ActorKind.SYSTEM, "guided_learning_bridge"),
        )
        self._open_turn = None

    def _summary_artifact(self, summary: str) -> ArtifactRef | None:
        if self.artifacts is None:
            return None
        try:
            return self.artifacts.put(
                summary.encode("utf-8"),
                role=ArtifactRole.CANDIDATE_REPORT,
                media_type="text/markdown",
                schema_ref="session-summary/1.0.0",
                trust_class=TrustClass.SYSTEM_GENERATED,
                data_class=self._scope.task_data_class,
                retention_policy_ref=self._scope.retention_policy_ref,
                principal_key_id=self._scope.principal_key_id,
            )
        except ArtifactStoreError as exc:
            record_trajectory_fault(
                stage="artifact_integrity", error_type=exc.app_error_code
            )
            log.warning(
                "trajectory_artifact_rejected",
                extra={
                    "contract_run_id": self.run_id,
                    "artifact_role": ArtifactRole.CANDIDATE_REPORT.value,
                    "error_type": exc.app_error_code,
                    "detail": exc.detail[:200],
                },
            )
            return None

    def complete(self, summary: str) -> None:
        """Record a session that closed with a summary, then the terminal fact."""
        artifact = self._summary_artifact(summary)
        if artifact is None:
            artifact = _content_ref(
                summary,
                role=ArtifactRole.CANDIDATE_REPORT,
                data_class=self._scope.task_data_class,
                retention=self._scope.retention_policy_ref,
                schema_ref="session-summary/1.0.0",
            )
        candidate_id = "cand_" + artifact.digest.removeprefix("sha256:")[:24]
        self._candidate_id = candidate_id
        self._final_artifact = artifact
        self._append(
            "candidate.created",
            "candidate.created",
            {
                "candidate_id": candidate_id,
                "candidate_kind": "session_summary",
                "artifact_id": artifact.artifact_id,
                "generation_method": "session_graph",
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "progress_update"),
            candidate_id=candidate_id,
            artifact_refs=(artifact,),
        )
        self._append(
            "final.candidate_selected",
            "final.candidate_selected",
            {
                "candidate_id": candidate_id,
                "selection_basis": "single_session_summary",
                "verification_event_ids": [],
                "unresolved_issue_codes": [],
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.POLICY, "guided_learning_bridge"),
            candidate_id=candidate_id,
        )
        final = artifact.model_copy(update={"role": ArtifactRole.FINAL_REPORT})
        self._append(
            "final.artifact_produced",
            "final.artifact_produced",
            {
                "candidate_id": candidate_id,
                "artifact_id": artifact.artifact_id,
                "deliverable_kind": "session_summary",
                "partial": False,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "progress_update"),
            candidate_id=candidate_id,
            artifact_refs=(final,),
        )
        self._append(
            "run.completed",
            "run.completed",
            {
                "final_candidate_id": candidate_id,
                "final_artifact_id": artifact.artifact_id,
                "stop_reason_code": "completed",
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "guided_learning_bridge"),
            candidate_id=candidate_id,
            artifact_refs=(final,),
            reason_codes=("completed",),
        )
        self._terminal = True

    def fail(self, *, error_code: str, stage: str) -> None:
        from src.errors import ERROR_CODES  # noqa: PLC0415

        code = error_code if error_code in ERROR_CODES else "internal_unexpected"
        self._append(
            "run.failed",
            "run.failed",
            {
                "failure_class": code,
                "failure_stage": stage,
                "last_good_artifact_id": (
                    self._final_artifact.artifact_id
                    if self._final_artifact is not None
                    else None
                ),
            },
            status=EventStatus.FAILED,
            actor=self._actor(ActorKind.SYSTEM, "guided_learning_bridge"),
            reason_codes=(code,),
        )
        self._terminal = True

    def cancel(self, *, reason_code: str, stage: str) -> None:
        from src.errors import ERROR_CODES  # noqa: PLC0415

        code = reason_code if reason_code in ERROR_CODES else "user_requested"
        self._append(
            "run.cancel_requested",
            "run.cancel_requested",
            {"requested_by_kind": "human", "reason_code": code},
            status=EventStatus.REQUESTED,
            actor=self._actor(ActorKind.HUMAN, "learner"),
        )
        self._append(
            "run.cancelled",
            "run.cancelled",
            {
                "acknowledged_at_stage": stage,
                "last_good_artifact_id": (
                    self._final_artifact.artifact_id
                    if self._final_artifact is not None
                    else None
                ),
                "in_flight_action_attempt_ids": [],
            },
            status=EventStatus.CANCELLED,
            actor=self._actor(ActorKind.SYSTEM, "guided_learning_bridge"),
            reason_codes=(code,),
        )
        self._terminal = True

    def reconcile(self, run_cost_usd: float | Decimal | str) -> CostReconciliation:
        """Append the session's terminal `budget.reconciled` fact."""
        result = reconcile_costs(self.events(), run_cost_usd)
        if self._reconciled:
            return result
        self._reconciled = True
        self._append(
            "budget.reconciled",
            "budget.reconciled",
            {
                "summed_event_cost": result.summed_event_cost,
                "run_cost_snapshot": result.run_cost_snapshot,
                "difference": result.difference,
                "result": result.result,
            },
            status=EventStatus.SUCCEEDED if result.matched else EventStatus.FAILED,
            actor=self._actor(ActorKind.SYSTEM, "cost_accumulator"),
            reason_codes=() if result.matched else ("integrity_failure",),
        )
        _log_reconciliation(self.run_id, result)
        return result

    # -- readers ----------------------------------------------------------

    def events(self) -> tuple[StoredTrajectoryEvent, ...]:
        return self.store.events(self.run_id)

    def export_jsonl(self) -> str:
        return self.store.export_jsonl(self.run_id)

    def durable_jsonl(self) -> str:
        sink = self.durable_store.sink
        return sink.read_jsonl(self.run_id) if sink is not None else ""

    def close(self) -> None:
        self.durable_store.close_run(self.run_id)

    def turn_trajectory(self) -> tuple[int, ...]:
        """The learner turns this session actually parked on, read back."""
        return tuple(
            int(str(event.payload["request_id"]).rsplit("-", 1)[-1])
            for event in self.events()
            if event.event_type == "hitl.requested"
        )

    def summary(self) -> dict[str, Any]:
        """The bounded block a record or a log line may carry."""
        fold = fold_trajectory(self.events())
        return {
            "binding": "P0-WO08",
            "lane": self.lane,
            "run_id": self.run_id,
            "task_spec_id": self._scope.task_spec_id,
            "task_spec_full_digest": self._scope.task_spec_full_digest,
            "session_binding_digest": self._scope.manifest_digest,
            "graph_digest": self.binding.graph_digest,
            "event_count": fold.event_count,
            "head_event_hash": fold.head_event_hash,
            "terminal_event_type": fold.terminal_event_type,
            "total_llm_calls": fold.total_llm_calls,
            "total_estimated_cost_usd": fold.total_estimated_cost_usd,
            "degraded": self.degraded,
        }


def _content_ref(
    body: str,
    *,
    role: ArtifactRole,
    data_class: DataClass,
    retention: Any,
    schema_ref: str,
) -> ArtifactRef:
    """A content-addressed reference to text whose bytes are not stored.

    The fallback when no artifact store is configured: W05's behaviour,
    kept because a run without a store must still record *which* report
    it produced, and a digest with no bytes behind it is an honest way to
    say that.
    """
    import hashlib

    encoded = body.encode("utf-8")
    digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return ArtifactRef(
        artifact_id=f"artifact:{digest}",
        role=role,
        digest=digest,
        media_type="text/markdown",
        byte_length=len(encoded),
        schema_ref=schema_ref,
        storage_uri=f"cas://sha256/{digest.removeprefix('sha256:')}",
        trust_class=TrustClass.SYSTEM_GENERATED,
        data_class=data_class,
        retention_policy_ref=retention,
    )


# ---------------------------------------------------------------------------
# Reconstruction
# ---------------------------------------------------------------------------


class EpisodeReconstruction(StrictContractModel):
    """What one episode looks like when rebuilt from its JSONL alone.

    The acceptance criterion "one synthetic research and one synthetic
    guided-learning episode reconstruct at the decision/artifact level"
    needs a definition of *level*, and this model is it: the ordered
    decisions the policy took, the artifacts it produced, the human
    pauses it waited on, and the terminal fact — reconstructed from
    events with no access to the process that wrote them.
    """

    schema_kind: Literal["trajectory-episode-reconstruction"] = (
        "trajectory-episode-reconstruction"
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str
    lane: Lane
    event_count: int
    head_event_hash: Digest
    terminal_event_type: str | None
    decisions: tuple[str, ...]
    artifacts: tuple[str, ...]
    human_pauses: tuple[str, ...]
    verification_verdicts: tuple[str, ...]
    repair_ids: tuple[str, ...]
    total_estimated_cost_usd: str
    total_llm_calls: int


#: Event types that record a decision the policy took, as opposed to a
#: lifecycle fact about the process that took it. This is the list
#: "decision level" means, written down so a reconstruction test is
#: asserting a definition rather than whatever the code happened to do.
DECISION_EVENT_TYPES: Final[tuple[str, ...]] = (
    "policy.decision",
    "action.completed",
    "action.failed",
    "action.skipped",
    "tool.completed",
    "tool.failed",
    "source.accepted",
    "source.rejected",
    "verification.completed",
    "repair.requested",
    "candidate.selected",
    "final.candidate_selected",
    "compute.stop_decided",
)


def reconstruct_episode(jsonl: str, *, lane: Lane) -> EpisodeReconstruction:
    """Rebuild an episode from its durable JSONL and nothing else.

    Verification is not optional and not a separate step: `import_jsonl`
    re-derives every event hash and refuses a discontinuous chain, so a
    reconstruction that returns at all is a reconstruction of a
    trajectory that has not been edited since it was written.
    """
    events = import_jsonl(jsonl)
    fold = fold_trajectory(events)
    decisions: list[str] = []
    artifacts: list[str] = []
    pauses: list[str] = []
    verdicts: list[str] = []
    repairs: list[str] = []
    for event in events:
        if event.event_type in DECISION_EVENT_TYPES:
            action = (
                event.payload.get("action_id")
                or event.payload.get("chosen_action")
                or event.payload.get("tool_call_id")
                or event.payload.get("source_id")
                or event.payload.get("verdict")
                or event.payload.get("repair_kind")
                or event.payload.get("candidate_id")
                or event.payload.get("selected_candidate_id")
            )
            decisions.append(f"{event.event_type}:{action}")
        for artifact in event.artifact_refs:
            if artifact.artifact_id not in artifacts:
                artifacts.append(artifact.artifact_id)
        if event.event_type == "hitl.requested":
            pauses.append(str(event.payload["request_kind"]))
        elif event.event_type == "verification.completed":
            verdicts.append(str(event.payload["verdict"]))
        elif event.event_type == "repair.requested":
            repairs.append(str(event.payload["repair_id"]))
    return EpisodeReconstruction(
        run_id=events[0].run_id,
        lane=lane,
        event_count=fold.event_count,
        head_event_hash=fold.head_event_hash,
        terminal_event_type=fold.terminal_event_type,
        decisions=tuple(decisions),
        artifacts=tuple(artifacts),
        human_pauses=tuple(pauses),
        verification_verdicts=tuple(verdicts),
        repair_ids=tuple(repairs),
        total_estimated_cost_usd=fold.total_estimated_cost_usd,
        total_llm_calls=fold.total_llm_calls,
    )


# ---------------------------------------------------------------------------
# Contained facade, for runner call sites
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def contained(bridge: Any, hook: str) -> Iterator[None]:
    """Absorb anything a bridge hook raises, once, and keep going.

    Same shape and same reasoning as W05's containment: broad because the
    failure modes are a validator, a digest, a filesystem and a store
    invariant, and deliberately not `BaseException` because the test
    harness's spend and network guards are `BaseException` subclasses and
    a bridge that swallowed one would be worse than no bridge.
    """
    try:
        yield
    except Exception:
        if bridge is None:
            log.warning("contract_shadow_failed", extra={"hook": hook}, exc_info=True)
            return
        already = bool(getattr(bridge, "degraded", False))
        bridge.degraded = True
        if not already:
            log.warning(
                "contract_shadow_failed",
                extra={"hook": hook, "contract_run_id": getattr(bridge, "run_id", "")},
                exc_info=True,
            )


def _artifact_store(
    config: Settings,
    *,
    consent: ConsentScope,
    data_class: DataClass,
    root: Path | str | None = None,
) -> LocalArtifactStore | None:
    """The run's artifact store, under the same D8 gate as the sink.

    Bytes are content, and content is precisely what D8 has not ruled on.
    So an artifact store exists only where a durable sink is permitted —
    an evaluation, public-source or synthetic episode — and a real
    research job or learner session keeps W05's behaviour of recording a
    digest with no bytes behind it.
    """
    if not capture_permitted(config, consent):
        return None
    resolved = root if root is not None else getattr(config, "contract_event_sink_root", "")
    if not resolved:
        return None
    return LocalArtifactStore(
        Path(resolved) / "artifacts", scope_data_class=data_class
    )


def start_research_run(
    config: Settings,
    *,
    episode: SealedEpisode,
    runtime_run_id: str,
    principal_key_id: str,
    cost_ceiling_usd: float | str,
    sink_root: Path | str | None = None,
) -> ResearchRuntimeBridge:
    """Open a durable research trajectory for one already-sealed episode.

    Sealing stays where W05 put it (`seal_research_episode`), because the
    seal has to happen before the first side effect and this bridge is
    not the thing that decides when that is.  What this adds is the
    durable ledger, the artifact store and the projections — all three
    gated on the episode's own consent scope, so a `research_api` episode
    gets exactly the in-memory recording W05 gave it.
    """
    consent = (
        ConsentScope.PRODUCT_OPERATION_ONLY
        if episode.origin == "research_api"
        else ConsentScope.EVALUATION_ONLY
    )
    data_class = episode.task_spec.data_policy.data_class
    bridge = ResearchRuntimeBridge(
        episode=episode,
        runtime_run_id=runtime_run_id,
        principal_key_id=principal_key_id,
        cost_ceiling_usd=money(cost_ceiling_usd),
        sink=build_sink(config, consent=consent, root=sink_root),
        projections=build_projections(config),
        artifacts=_artifact_store(
            config, consent=consent, data_class=data_class, root=sink_root
        ),
    )
    bridge.open()
    _remember_run(bridge)
    log.info(
        "trajectory_run_opened",
        extra={"contract_run_id": bridge.run_id, "lane": bridge.lane},
    )
    return bridge


def _remember_run(bridge: ShadowRun) -> None:
    """Put the run in W05's bounded registry so an accessor can read it back.

    The same registry, not a second one: `shadow_run(job_id)` is what a
    test and the eval runner already use to reach a finished episode, and
    two registries would mean a caller had to know which work order
    opened its run.
    """
    from src.contracts.shadow_bridge import _remember

    _remember(bridge)


def start_research_job(
    job: Any,
    workflow: Any,
    *,
    config: Settings,
    cost_ceiling_usd: float,
) -> ResearchRuntimeBridge | None:
    """Open a durable research trajectory for one API job, or return `None`.

    The runner's entry point, and a drop-in for W05's function of the
    same name: the object it returns *is* a `ShadowRun`, so every one of
    `shadow_bridge`'s contained hooks keeps working on it unchanged.
    What the job gets in addition is the span projection, `trace_ref` on
    every envelope, and a terminal cost reconciliation.

    What it does **not** get is a file.  An API research job carries
    `product_operation_only` consent, so `capture_permitted` refuses it
    the durable sink and the artifact store whatever
    `contract_event_capture` says — the run is recorded exactly as W05
    recorded it, in memory, and dies with the worker.  That is the D8
    gate, and it is why this function is safe to put on the request path.

    `None` covers every "not today": the switch is off, the job is not a
    research job, the policy shape is unrepresentable, or the provider is
    metered with nothing approving the spend.
    """
    from src.contracts.shadow_bridge import shadow_enabled

    if not shadow_enabled(config) or getattr(job, "kind", "research") != "research":
        return None
    bridge: ResearchRuntimeBridge | None = None
    with contained(None, "start_research_job"):
        from src.contracts.research_binding import (
            classify_from_graph_shape,
            compile_research_intake,
            read_graph_shape,
            seal_research_episode,
        )
        from src.contracts.shadow_bridge import _principal_id

        shape = classify_from_graph_shape(config, read_graph_shape(workflow))
        spec = compile_research_intake(
            config,
            task_id=f"research-api:{job.job_id}",
            query=job.query,
            hitl_plan_review=bool(config.enable_hitl) and not bool(job.hitl_bypass),
            supervisor=shape.runtime_flags.enable_supervisor,
        )
        try:
            episode = seal_research_episode(
                config,
                shape=shape,
                spec=spec,
                origin="research_api",
                runtime_run_id=job.job_id,
                hitl_bypass=bool(job.hitl_bypass),
                hitl_bypass_reason=(
                    "client-requested-bypass" if job.hitl_bypass else None
                ),
            )
        except ResearchBindingError as exc:
            # The configuration cannot be expressed as a sealed episode.
            # Declining is the designed outcome, not a failure of the run.
            log.info("contract_shadow_unavailable", extra={"detail": exc.detail[:200]})
            return None
        bridge = start_research_run(
            config,
            episode=episode,
            runtime_run_id=job.job_id,
            principal_key_id=_principal_id(
                getattr(job, "principal_key_id", None), lane="research-api"
            ),
            cost_ceiling_usd=cost_ceiling_usd,
        )
        log.info(
            "contract_shadow_sealed",
            extra={
                "task_spec_id": episode.task_spec.task_spec_id,
                "manifest_digest": episode.manifest_digest,
                "arm_id": episode.shape.arm_id,
                "policy_id": episode.shape.policy_id,
            },
        )
    return bridge


def start_guided_session(
    config: Settings,
    *,
    spec: TaskSpecV1,
    graph_digest: str,
    runtime_run_id: str,
    principal_key_id: str,
    cost_ceiling_usd: float | str,
    synthetic: bool,
    sink_root: Path | str | None = None,
) -> GuidedLearningBridge:
    """Seal a guided session's binding and open its trajectory."""
    binding = seal_guided_session(config, spec=spec, graph_digest=graph_digest)
    consent = (
        ConsentScope.SYNTHETIC_TEST if synthetic else ConsentScope.PRODUCT_OPERATION_ONLY
    )
    bridge = GuidedLearningBridge(
        binding=binding,
        spec=spec,
        runtime_run_id=runtime_run_id,
        principal_key_id=principal_key_id,
        cost_ceiling_usd=money(cost_ceiling_usd),
        synthetic=synthetic,
        sink=build_sink(config, consent=consent, root=sink_root),
        projections=build_projections(config, include_verdicts=False),
        artifacts=_artifact_store(
            config,
            consent=consent,
            data_class=spec.data_policy.data_class,
            root=sink_root,
        ),
    )
    bridge.open()
    return bridge


def observe_compute_tier(
    bridge: Any,
    *,
    tier: str,
    eligible_tiers: Sequence[str],
    reason_codes: Sequence[str],
    feature_snapshot_ref: str,
    tier_budget_ref: str,
) -> None:
    """Record one compute-tier allocation, or do nothing.

    Primitives rather than a `ComputeDecision` on purpose: the contract
    package is the capability lane's *consumer* here, and typing this
    hook against `src.policies.compute` would make every import of the
    bridge pull in a policy module — a dependency in the direction
    nothing else in `src/contracts` has.
    """
    if bridge is None or getattr(bridge, "degraded", False):
        return
    with contained(bridge, "observe_compute_tier"):
        bridge.compute_tier_selected(
            tier=tier,
            eligible_tiers=eligible_tiers,
            reason_codes=reason_codes,
            feature_snapshot_ref=feature_snapshot_ref,
            tier_budget_ref=tier_budget_ref,
        )


def observe_reconciliation(bridge: Any, run_cost_usd: float) -> CostReconciliation | None:
    """Reconcile a finished run's costs, or do nothing."""
    if bridge is None or getattr(bridge, "degraded", False):
        return None
    result: CostReconciliation | None = None
    with contained(bridge, "observe_reconciliation"):
        result = bridge.reconcile(run_cost_usd)
    return result


def observe_close(bridge: Any) -> None:
    """Verify the chain and record the head hash, or do nothing."""
    if bridge is None:
        return
    with contained(bridge, "observe_close"):
        bridge.close()


__all__ = [
    "CAPTURE_ELIGIBLE_CONSENT",
    "DECISION_EVENT_TYPES",
    "RECONCILIATION_UNIT_USD",
    "SINK_EVENTS_FILE",
    "SINK_HEAD_FILE",
    "SINK_RUN_DIRECTORY",
    "SINK_SCOPE_FILE",
    "BridgeError",
    "CostReconciliation",
    "DurableTrajectoryStore",
    "EpisodeReconstruction",
    "GuidedLearningBridge",
    "GuidedSessionBinding",
    "JsonlTrajectorySink",
    "NamedProjection",
    "ResearchRuntimeBridge",
    "TrajectorySink",
    "action_attempt_id",
    "build_projections",
    "build_sink",
    "capture_permitted",
    "compile_guided_session_intake",
    "contained",
    "current_trace_ref",
    "episode_block",
    "log_projection",
    "observe_close",
    "observe_compute_tier",
    "observe_episode_terminal",
    "observe_job_terminal",
    "observe_model_call",
    "observe_node",
    "observe_reconciliation",
    "observe_review_answered",
    "observe_review_requested",
    "parity_report",
    "reconcile_costs",
    "reconstruct_episode",
    "seal_guided_session",
    "shadow_enabled",
    "shadow_run",
    "span_projection",
    "start_guided_session",
    "start_research_job",
    "start_research_run",
    "verdict_projection",
]
