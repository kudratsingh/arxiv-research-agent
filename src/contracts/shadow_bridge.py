"""The in-memory bridge from a live research run to a canonical trajectory.

This is the only module that both drives a contract store and is called
from the product's own runners. Everything it does obeys one rule, and
the rule is the whole reason the work order is called *shadow*:

    a research run must end exactly as it would have ended if this
    module were not imported.

That is enforced structurally rather than promised. Every public entry
point returns `None` or nothing, takes a `ShadowRun | None` so a caller
never has to branch, and runs inside `_contained`, which absorbs any
exception, logs it once under a stable event name, and degrades *that
run's* shadow for the rest of its life. A bridge that breaks stops
recording; it does not stop the job.

What it records, in the order a research episode produces it:

    run.admitted            the sealed manifest's digest, first, always
    attempt.started         one process attempt
    budget.established      the ceiling the run is actually enforced against
    action.started/completed one pair per graph node, off the astream chunks
    action.started/completed one pair per model call, off the cost accumulator
    budget.threshold_reached once, when spend crosses its warning line
    checkpoint.saved        at a declared recovery boundary (the HITL pause)
    hitl.requested/responded the plan review the runner already parks on
    candidate.created       the report, as a content-addressed artifact ref
    final.candidate_selected / final.artifact_produced
    run.completed | run.failed | run.cancelled | run.budget_stopped

Three things it deliberately does **not** do:

- **It stores no bodies.** A report becomes a digest, a byte length and a
  `cas://` locator; nothing writes those bytes anywhere. The
  content-addressed store is P0-WO08's.
- **It persists nothing.** The trajectory lives in a bounded in-process
  registry and dies with the worker. D8 blocks retained user trajectory
  capture, and an in-memory bridge is how this work order stays on the
  right side of that while still being executable evidence.
- **It never carries user text.** No query, no report, no prompt, no
  paper content, no learner writing reaches a payload — the task's
  objective is addressed by `task_spec_id` and its digest, which is
  exactly what RFC 10 §10 permits.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections import OrderedDict
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import RLock
from typing import Any, Final, Literal

from src.config import Settings
from src.config import settings as default_settings
from src.contracts.kernel import DataClass, ImmutableObjectRef
from src.contracts.research_binding import (
    BenchmarkBinding,
    ContractOutcome,
    EpisodeOrigin,
    GraphShape,
    LegacyOutcome,
    ParityMismatch,
    PolicyShape,
    ResearchBindingError,
    SealedEpisode,
    classify_from_graph_shape,
    compare_outcomes,
    compare_research_state,
    compile_eval_case,
    compile_research_intake,
    money,
    read_graph_shape,
    retention_policy_ref,
    seal_research_episode,
    utc_timestamp,
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
    TrustClass,
    UsageDelta,
    fold_trajectory,
    new_event_id,
)
from src.errors import ERROR_CODES
from src.observability.costs import LlmCallObservation, RunCosts
from src.observability.logging import get_logger

log = get_logger(__name__)

#: How many finished episodes the accessor keeps. The registry exists so
#: a test and the eval runner can read a run back after it ended; it is
#: not a store, and an unbounded dict in a long-lived worker would be a
#: slow leak wearing a diagnostic's clothes.
MAX_RETAINED_RUNS: Final[int] = 32

#: Fraction of the operative cost ceiling at which one
#: `budget.threshold_reached` is emitted. One event, once, because the
#: value of the signal is "this run is close" and a per-call stream of it
#: would be noise inside a 32 KiB-per-event budget.
BUDGET_WARNING_FRACTION: Final[Decimal] = Decimal("0.8")

#: The key the scripted campaign's record may carry, fixed by that
#: harness's own seam (`simulate_research.HOOK_WRITABLE_KEY`). Named here
#: rather than imported so this module keeps no import edge back into the
#: eval package.
CONTRACTS_RECORD_KEY: Final[str] = "contracts"

#: The key the funded research campaign's per-query record carries. A
#: different name from the scripted one on purpose: that lane's seam
#: chose `contracts`, this one is the runner's own additive field, and
#: conflating them would make one rename break two harnesses.
SHADOW_RECORD_KEY: Final[str] = "contract_shadow"

_LOCK: Final[RLock] = RLock()
_RUNS: Final[OrderedDict[str, ShadowRun]] = OrderedDict()
_SHAPES: Final[dict[tuple[str, bool, bool, bool, bool], GraphShape]] = {}


def shadow_enabled(config: Settings | None = None) -> bool:
    """Whether contract shadowing is switched on for this process.

    Read at call time, never cached: a test installs a modified
    `Settings` on the module under test, and a value captured at import
    would ignore it — the same reason `src.api.runner` reads `settings`
    inside its functions.
    """
    return (config or default_settings).contract_shadow == "shadow"


# ---------------------------------------------------------------------------
# Failure containment
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _contained(run: ShadowRun | None, hook: str) -> Iterator[None]:
    """Absorb anything a shadow hook raises, once, and keep going.

    The containment is deliberately broad and deliberately *not*
    `BaseException`. Broad, because the failure modes are a contract
    validator, a digest, a pydantic model and a store invariant — a
    catalogue nobody can enumerate in advance, and every one of them
    would otherwise reach a `run_job` handler and write a terminal job
    row. Not `BaseException`, because the test harness's network and
    spend guards are `BaseException` subclasses precisely so no
    `except Exception` in this repository can swallow them, and a shadow
    that hid a spend guard would be worse than no shadow at all.

    One log line per run, not per hook: a bridge that breaks on the first
    node would otherwise emit one warning per node for the rest of the
    job. `degraded` is the latch.
    """
    try:
        yield
    except Exception:
        if run is None:
            log.warning("contract_shadow_failed", extra={"hook": hook}, exc_info=True)
            return
        already = run.degraded
        run.degraded = True
        if not already:
            log.warning(
                "contract_shadow_failed",
                extra={"hook": hook, "manifest_digest": run.episode.manifest_digest},
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# One shadowed episode
# ---------------------------------------------------------------------------


class ShadowRun:
    """One research episode's sealed manifest and appended trajectory.

    Thread-safe by delegation: `InMemoryTrajectoryStore` owns its own
    lock, and the reader's per-paper fan-out records model calls from a
    thread pool while the event loop records node completions. The
    counters guarded here are only used to mint ids, so a coarse lock
    around them costs nothing measurable next to a graph node.
    """

    def __init__(
        self,
        *,
        episode: SealedEpisode,
        runtime_run_id: str,
        principal_key_id: str,
        cost_ceiling_usd: str,
        clock: Any = None,
        store: InMemoryTrajectoryStore | None = None,
    ) -> None:
        """
        Args:
            store: The ledger this run appends to. Defaults to a fresh
                in-memory adapter, which is W05's whole storage story.
                P0-WO08 passes a durable subclass that writes JSONL and
                fans projections out after each accept, so the two work
                orders share one recording path instead of forking the
                event vocabulary in two places (ADR 0083).
        """
        self.episode = episode
        self.runtime_run_id = runtime_run_id
        self.degraded = False
        self.cost_ceiling_usd = cost_ceiling_usd
        self._clock = clock or utc_timestamp
        self._lock = RLock()
        self._counter = 0
        self._budget_warned = False
        self._candidate_id: str | None = None
        self._final_artifact: ArtifactRef | None = None
        self._open_hitl: str | None = None
        self._terminal = False
        self._attempt_id = _deterministic_attempt_id(runtime_run_id)
        payload = episode.manifest.payload
        self._policy_ref = PolicyRef(
            policy_id=episode.shape.policy_id,
            policy_version=episode.shape.policy_version,
            policy_digest=episode.shape.policy_digest,
        )
        self._scope = RunScope(
            run_id=payload.identity.run_id,
            task_spec_id=episode.task_spec.task_spec_id,
            task_revision=episode.task_spec.task_revision,
            task_spec_full_digest=episode.task_ref.full_digest,
            manifest_digest=episode.manifest_digest,
            principal_key_id=principal_key_id,
            policy_ref=self._policy_ref,
            task_data_class=episode.task_spec.data_policy.data_class,
            retention_policy_ref=retention_policy_ref(),
            experiment_arm=episode.shape.arm_id,
        )
        self.store = store if store is not None else InMemoryTrajectoryStore(clock=self._clock)
        self.store.register_run(self._scope)

    # -- identity helpers ------------------------------------------------

    @property
    def run_id(self) -> str:
        return self._scope.run_id

    @property
    def attempt_id(self) -> str:
        return self._attempt_id

    @property
    def arm_id(self) -> str | None:
        return self.episode.shape.arm_id

    def _next(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def _event_id(self, key: str) -> str:
        """A stable event id derived from the run and the event's key.

        Derived rather than random so a replay of the same episode
        produces the same ids, which is what makes a trajectory
        comparable across two runs of the same canned fixture.
        """
        return new_event_id(entropy=uuid.uuid5(uuid.NAMESPACE_URL, f"{self.run_id}:{key}"))

    # -- the append primitive -------------------------------------------

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
        action_attempt_id: str | None = None,
        artifact_refs: tuple[ArtifactRef, ...] = (),
        usage_delta: UsageDelta | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> StoredTrajectoryEvent:
        """Propose one event; the store owns order, hashing and identity."""
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
            trace_ref=self._trace_ref(),
            candidate_id=candidate_id,
            action_attempt_id=action_attempt_id,
            status=status,
            reason_codes=reason_codes,
            payload=dict(payload),
            artifact_refs=artifact_refs,
            usage_delta=usage_delta,
            data_governance=self._governance(),
            replay=_replay_metadata(),
        )
        return self.store.append(event)

    def _trace_ref(self) -> TraceRef | None:
        """The active OTel span, or `None`.

        `None` here: W05 imports no telemetry, and a shadow that reached
        into the tracer would put an SDK on the import graph of a
        deployment that has the switch off. P0-WO08's runtime bridge
        overrides this to copy the live span (RFC 10 §16), which is the
        one place the join between a trace and a trajectory is wanted.
        """
        return None

    def _governance(self) -> DataGovernance:
        """The governance block every event of this run carries.

        `content_class` is `metadata` because that is literally all a
        payload here holds — ids, counts, digests and reason codes.
        `effective_data_class` inherits the task's, never below it, which
        is the rule the store re-checks on append.
        """
        eval_lane = self.episode.origin != "research_api"
        return DataGovernance(
            content_class=ContentClass.METADATA,
            effective_data_class=self._scope.task_data_class,
            consent_scope=(
                ConsentScope.EVALUATION_ONLY
                if eval_lane
                else ConsentScope.PRODUCT_OPERATION_ONLY
            ),
            redaction_status=RedactionStatus.NOT_APPLICABLE,
            contains_user_content=False,
        )

    def _actor(self, kind: ActorKind, name: str) -> Actor:
        return Actor(
            kind=kind,
            name=name,
            instance_id="contract-shadow",
            version_ref=f"contract-shadow/{self.episode.shape.policy_version}",
        )

    # -- lifecycle -------------------------------------------------------

    def open(self) -> None:
        """Append `run.admitted`, the attempt, and the budget it runs under.

        `run.admitted` is first by contract — the store refuses any other
        opening event — and it binds the manifest digest the episode was
        sealed with, which is the join between the frozen configuration
        and everything that follows.
        """
        payload = self.episode.manifest.payload
        receipt = payload.admission_resolution.receipt_ref
        self._append(
            "run.admitted",
            "run.admitted",
            {
                "admission_receipt_ref": receipt.id,
                "admission_receipt_digest": receipt.digest,
                "environment_class": payload.environment.execution_class,
                "product_lane": "research",
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "admission_controller"),
            with_attempt=False,
        )
        self._append(
            "attempt.started",
            "attempt.started",
            {
                "entrypoint": self.episode.origin,
                "main_branch_id": "branch_main",
                "effective_budget_ref": f"budget:{payload.identity.episode_key[:23]}",
                "resume_checkpoint_id": None,
            },
            status=EventStatus.STARTED,
            actor=self._actor(ActorKind.SYSTEM, "shadow_bridge"),
        )
        self._append(
            "budget.established",
            "budget.established",
            {
                "budget_id": "run_cost_ceiling",
                "currency": "USD",
                # The ceiling the run is *enforced* against, which is the
                # product's own `max_cost_usd`. The manifest's episode cap
                # is the spend this episode was *authorized* for, and that
                # is zero — a shadow authorizes nothing. Two different
                # questions, so two different numbers, and the trajectory
                # records the one that can actually stop a run.
                "episode_cap": self.cost_ceiling_usd,
                "campaign_cap_ref": f"manifest:{self.episode.manifest_digest[:23]}",
                "limit_dimensions": ["cost_usd", "model_calls", "wall_time_seconds"],
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "shadow_bridge"),
        )

    def node_completed(self, node: str, state_update: Mapping[str, Any]) -> None:
        """Record one graph node finishing, as an action pair.

        The runners observe *completions* — `astream` yields after a node
        returns — so the `action.started` that the store requires before
        an outcome is emitted at the same instant. That is stated here
        rather than papered over: the pair's ordering is real, its
        *timing* is not, and a durable bridge that wraps the node itself
        is P0-WO08's job.

        `state_update` is read for nothing but its key names, and not
        even those reach the payload. `action.completed` has a closed
        field set with no room for a state summary, which is the
        contract's way of saying a trajectory is not a state dump.
        """
        index = self._next()
        attempt = _action_attempt_id(f"node-{index}-{node}")
        actor = self._actor(ActorKind.AGENT, _actor_name(node))
        self._append(
            "action.started",
            f"action.started:{index}",
            {"action_id": node, "executor_kind": "graph_node"},
            status=EventStatus.STARTED,
            actor=actor,
            action_attempt_id=attempt,
        )
        self._append(
            "action.completed",
            f"action.completed:{index}",
            {
                "action_id": node,
                "observation_event_ids": [],
                "output_artifact_ids": [],
            },
            status=EventStatus.SUCCEEDED,
            actor=actor,
            action_attempt_id=attempt,
        )

    def model_call(self, call: LlmCallObservation, costs: RunCosts | None = None) -> None:
        """Record one completed model call, off the cost accumulator.

        The usage delta is the contract's own vocabulary for spend, and
        it rides on the `action.completed` for the request: RFC 10 puts
        usage on the event for the *completed work*, so a request that
        was issued and never returned records no usage and no call.
        """
        index = self._next()
        attempt = _action_attempt_id(f"model-{index}")
        provider = self.episode.manifest.payload.providers.llm.provider
        actor = self._actor(ActorKind.MODEL, provider.replace("_", "-"))
        cost = money(call.cost_usd)
        pricing_ref: ImmutableObjectRef | None = (
            self.episode.manifest.payload.providers.pricing.table_ref
            if Decimal(cost) > 0
            else None
        )
        self._append(
            "action.started",
            f"model.started:{index}",
            {"action_id": "model_request", "executor_kind": "model_request"},
            status=EventStatus.STARTED,
            actor=actor,
            action_attempt_id=attempt,
        )
        self._append(
            "action.completed",
            f"model.completed:{index}",
            {
                "action_id": "model_request",
                "observation_event_ids": [],
                "output_artifact_ids": [],
            },
            status=EventStatus.SUCCEEDED,
            actor=actor,
            action_attempt_id=attempt,
            usage_delta=UsageDelta(
                provider=provider,
                model_id=call.model,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                cache_read_input_tokens=call.cache_read_input_tokens,
                cache_creation_input_tokens=call.cache_creation_input_tokens,
                llm_calls=1,
                retries=call.retries,
                estimated_cost_usd=cost,
                price_table_ref=pricing_ref,
            ),
        )
        if costs is not None:
            self._maybe_warn_budget(costs)

    def _maybe_warn_budget(self, costs: RunCosts) -> None:
        """Emit one `budget.threshold_reached` when spend nears the ceiling.

        The latch is taken under the lock, and that is not defensive
        tidiness: the reader records model calls from a thread pool, so
        two workers can cross the line in the same instant, and the event
        carries a *fixed* idempotency key. Two appends under one key with
        different spend figures is an `IdempotencyConflict`, which the
        containment would absorb by degrading the shadow — a race would
        quietly cost the run its trajectory rather than duplicate a line.
        """
        ceiling = Decimal(self.cost_ceiling_usd)
        if ceiling <= 0:
            return
        spent = Decimal(money(costs.total_cost_usd))
        if spent < ceiling * BUDGET_WARNING_FRACTION:
            return
        with self._lock:
            if self._budget_warned:
                return
            self._budget_warned = True
        self._append(
            "budget.threshold_reached",
            "budget.threshold_reached",
            {
                "threshold": money(ceiling * BUDGET_WARNING_FRACTION),
                "spent": money(spent),
                "reserved": "0.000000",
                "remaining": money(max(Decimal("0"), ceiling - spent)),
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "cost_accumulator"),
        )

    def checkpoint_and_review_requested(
        self, *, pause_number: int, pending: Sequence[str], deadline_seconds: int
    ) -> None:
        """Record the runner's plan-review park: a checkpoint and a request.

        The checkpoint event is emitted here and only here, because this
        is the one place the runner treats a LangGraph write as a
        *declared recovery boundary* — it reads the state back, parks the
        job in a non-terminal status and waits for a human. RFC 10 says
        ordinary per-step checkpointer writes may stay in the
        checkpointer, and recording sixty of them would say nothing a
        node sequence does not.
        """
        request_id = f"plan-review-{pause_number}"
        self._append(
            "checkpoint.saved",
            f"checkpoint.saved:{pause_number}",
            {
                "checkpoint_id": f"{self.run_id}:pause:{pause_number}",
                "checkpoint_artifact_id": None,
                "graph_position": ",".join(str(node) for node in pending) or "unknown",
                "resumable": True,
                "state_schema_ref": "research-state/1.0.0",
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.SYSTEM, "checkpointer"),
        )
        deadline = datetime.now(UTC) + timedelta(seconds=max(1, deadline_seconds))
        self._append(
            "hitl.requested",
            f"hitl.requested:{pause_number}",
            {
                "request_id": request_id,
                "request_kind": "plan_review",
                "subject_ref": f"task_spec:{self._scope.task_spec_id}",
                "allowed_responses": ["approve", "revise", "cancel"],
                "deadline_at": utc_timestamp(deadline),
            },
            status=EventStatus.REQUESTED,
            actor=self._actor(ActorKind.SYSTEM, "shadow_bridge"),
        )
        self._open_hitl = request_id

    def review_answered(self, *, pause_number: int, action: str | None) -> None:
        """Record the reviewer's answer to an open plan review."""
        if self._open_hitl is None:
            return
        request_id = self._open_hitl
        self._open_hitl = None
        self._append(
            "hitl.responded",
            f"hitl.responded:{pause_number}",
            {
                "request_id": request_id,
                "response_kind": str(action or "approve"),
                # No artifact: an edited plan is user-authored text, and
                # storing it is P0-WO08's content-addressed adapter with
                # P0-WO09's consent decision behind it.
                "response_artifact_id": None,
                "responder_principal_ref": self._scope.principal_key_id,
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.HUMAN, "reviewer"),
        )

    # -- terminal --------------------------------------------------------

    def _report_artifact(self, report: str, role: ArtifactRole) -> ArtifactRef:
        """A content-addressed reference to a report, without its bytes."""
        body = report.encode("utf-8")
        digest = "sha256:" + hashlib.sha256(body).hexdigest()
        return ArtifactRef(
            artifact_id=f"artifact:{digest}",
            role=role,
            digest=digest,
            media_type="text/markdown",
            byte_length=len(body),
            schema_ref="research-report/1.0.0",
            storage_uri=f"cas://sha256/{digest.removeprefix('sha256:')}",
            trust_class=TrustClass.SYSTEM_GENERATED,
            data_class=self._scope.task_data_class,
            retention_policy_ref=self._scope.retention_policy_ref,
        )

    def _record_candidate(self, report: str) -> ArtifactRef:
        """Record the report the run produced as a candidate."""
        artifact = self._report_artifact(report, ArtifactRole.CANDIDATE_REPORT)
        candidate_id = "cand_" + artifact.digest.removeprefix("sha256:")[:24]
        self._candidate_id = candidate_id
        self._final_artifact = artifact
        self._append(
            "candidate.created",
            "candidate.created",
            {
                "candidate_id": candidate_id,
                "candidate_kind": "research_report",
                "artifact_id": artifact.artifact_id,
                "generation_method": "graph_synthesis",
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.AGENT, "synthesizer"),
            candidate_id=candidate_id,
            artifact_refs=(artifact,),
        )
        return artifact

    def complete(self, report: str) -> None:
        """Record a succeeded run: candidate, selection, artifact, terminal."""
        artifact = self._record_candidate(report)
        candidate_id = self._candidate_id
        assert candidate_id is not None
        self._append(
            "final.candidate_selected",
            "final.candidate_selected",
            {
                "candidate_id": candidate_id,
                "selection_basis": "single_candidate_fixed_policy",
                "verification_event_ids": [],
                "unresolved_issue_codes": [],
            },
            status=EventStatus.SUCCEEDED,
            actor=self._actor(ActorKind.POLICY, "shadow_bridge"),
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
                "partial": False,
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
            actor=self._actor(ActorKind.SYSTEM, "shadow_bridge"),
            candidate_id=candidate_id,
            artifact_refs=(final,),
            reason_codes=("completed",),
        )
        self._terminal = True

    def fail(self, *, error_code: str, stage: str, partial_report: str = "") -> None:
        """Record a failed run, keeping whatever artifact it had produced."""
        last_good = self._recovered_artifact_id(partial_report)
        code = error_code if error_code in ERROR_CODES else "internal_unexpected"
        self._append(
            "run.failed",
            "run.failed",
            {
                "failure_class": code,
                "failure_stage": stage,
                "last_good_artifact_id": last_good,
            },
            status=EventStatus.FAILED,
            actor=self._actor(ActorKind.SYSTEM, "shadow_bridge"),
            reason_codes=(code,) if code in ERROR_CODES else (),
        )
        self._terminal = True

    def cancel(self, *, reason_code: str, stage: str, partial_report: str = "") -> None:
        """Record a cancelled run, request first, as the contract orders it."""
        last_good = self._recovered_artifact_id(partial_report)
        code = reason_code if reason_code in ERROR_CODES else "user_requested"
        self._append(
            "run.cancel_requested",
            "run.cancel_requested",
            {"requested_by_kind": "system", "reason_code": code},
            status=EventStatus.REQUESTED,
            actor=self._actor(ActorKind.SYSTEM, "shadow_bridge"),
        )
        self._append(
            "run.cancelled",
            "run.cancelled",
            {
                "acknowledged_at_stage": stage,
                "last_good_artifact_id": last_good,
                "in_flight_action_attempt_ids": [],
            },
            status=EventStatus.CANCELLED,
            actor=self._actor(ActorKind.SYSTEM, "shadow_bridge"),
            reason_codes=(code,),
        )
        self._terminal = True

    def budget_stop(self, *, spent_usd: float, partial_report: str = "") -> None:
        """Record a cost-ceiling stop: exhaustion, then the terminal event."""
        last_good = self._recovered_artifact_id(partial_report)
        self._append(
            "budget.exhausted",
            "budget.exhausted",
            {
                "spent": money(spent_usd),
                "reserved": "0.000000",
                "attempt_blocked": True,
                "partial_candidate_id": self._candidate_id,
            },
            status=EventStatus.FAILED,
            actor=self._actor(ActorKind.SYSTEM, "cost_accumulator"),
            reason_codes=("episode_budget_exhausted",),
        )
        self._append(
            "run.budget_stopped",
            "run.budget_stopped",
            {
                "budget_id": "run_cost_ceiling",
                "last_good_artifact_id": last_good,
                "partial_candidate_id": self._candidate_id,
                "stop_reason_code": "budget_exhausted",
                "partial": bool(partial_report),
            },
            status=EventStatus.BUDGET_STOPPED,
            actor=self._actor(ActorKind.SYSTEM, "shadow_bridge"),
            reason_codes=("cost_budget_exceeded",),
        )
        self._terminal = True

    def _recovered_artifact_id(self, partial_report: str) -> str | None:
        """Record a recovered partial report, and return its artifact id.

        The report a budget-stopped or failed run had already paid for is
        an artifact like any other — ADR 0051 kept it on the job row for
        exactly that reason — so it gets a candidate and a content
        address rather than being dropped from the trajectory.
        """
        if partial_report.strip() and self._candidate_id is None:
            return self._record_candidate(partial_report).artifact_id
        return self._final_artifact.artifact_id if self._final_artifact is not None else None

    # -- readers ---------------------------------------------------------

    def events(self) -> tuple[StoredTrajectoryEvent, ...]:
        """Every event this run appended, in commit order."""
        return self.store.events(self.run_id)

    def export_jsonl(self) -> str:
        """The run's trajectory as canonical JSONL, one event per line."""
        return self.store.export_jsonl(self.run_id)

    def node_trajectory(self) -> tuple[str, ...]:
        """The node sequence, read back out of the recorded actions.

        Read from the events rather than from a list kept on the side,
        because that is the assertion worth making: if the trajectory the
        contract holds does not reproduce the node order the e2e test
        already pins, the bridge has lost something.
        """
        return tuple(
            str(event.payload["action_id"])
            for event in self.events()
            if event.event_type == "action.completed"
            and str(event.payload.get("action_id")) != "model_request"
        )

    def model_call_events(self) -> tuple[StoredTrajectoryEvent, ...]:
        """Every event carrying a completed model call's usage delta."""
        return tuple(
            event
            for event in self.events()
            if event.usage_delta is not None and event.usage_delta.llm_calls
        )

    def contract_outcome(self) -> ContractOutcome:
        """The contract's own view of this episode, for the parity check."""
        fold = fold_trajectory(self.events())
        return ContractOutcome(
            task_spec_id=self._scope.task_spec_id,
            task_full_digest=self._scope.task_spec_full_digest,
            objective=self.episode.task_spec.objective,
            manifest_digest=self.episode.manifest_digest,
            arm_id=self.episode.shape.arm_id,
            policy_id=self.episode.shape.policy_id,
            terminal_event_type=fold.terminal_event_type,
            llm_calls=fold.total_llm_calls,
            cost_usd=fold.total_estimated_cost_usd,
            final_artifact_digest=(
                self._final_artifact.digest if self._final_artifact is not None else None
            ),
        )

    def summary(self) -> dict[str, Any]:
        """The bounded block a record or a log line may carry.

        Ids, digests and counts. No objective, no report, no event
        payloads — a summary that carried those would reintroduce the
        exposure the trajectory contract spent its redaction rules
        avoiding.
        """
        fold = fold_trajectory(self.events())
        return {
            "binding": "P0-WO05",
            "run_id": self.run_id,
            "task_spec_id": self._scope.task_spec_id,
            "task_revision": self._scope.task_revision,
            "task_spec_full_digest": self._scope.task_spec_full_digest,
            "manifest_digest": self.episode.manifest_digest,
            "policy_runtime_projection_digest": (
                self.episode.projection.integrity.payload_sha256
            ),
            "arm_id": self.episode.shape.arm_id,
            "policy_id": self.episode.shape.policy_id,
            "policy_digest": self.episode.shape.policy_digest,
            "graph_digest": self.episode.shape.graph.digest,
            "held_out_factors": dict(self.episode.shape.held_out_factors),
            "event_count": fold.event_count,
            "head_event_hash": fold.head_event_hash,
            "terminal_event_type": fold.terminal_event_type,
            "total_llm_calls": fold.total_llm_calls,
            "total_estimated_cost_usd": fold.total_estimated_cost_usd,
            "degraded": self.degraded,
        }


def _deterministic_attempt_id(runtime_run_id: str) -> str:
    entropy = uuid.UUID(bytes=hashlib.sha256(f"attempt:{runtime_run_id}".encode()).digest()[:16])
    return f"att_{entropy.hex}"


def _action_attempt_id(label: str) -> str:
    """An action-attempt id in the contract's `aatt_` vocabulary."""
    cleaned = "".join(char if char.isalnum() or char in "-_" else "-" for char in label.lower())
    return f"aatt_{cleaned[:90] or 'action'}"


def _actor_name(node: str) -> str:
    """A graph node name in the actor vocabulary's shape."""
    cleaned = "".join(char if char.isalnum() or char in "_.-" else "_" for char in node.lower())
    return cleaned[:63] or "node"


def _replay_metadata() -> ReplayMetadata:
    """Every event this bridge writes is a live observation of a real run."""
    return ReplayMetadata(
        origin=ReplayOrigin.LIVE,
        observation_status=ObservationStatus.OBSERVED,
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def _remember(run: ShadowRun) -> None:
    with _LOCK:
        _RUNS[run.runtime_run_id] = run
        while len(_RUNS) > MAX_RETAINED_RUNS:
            _RUNS.popitem(last=False)


def shadow_run(runtime_run_id: str) -> ShadowRun | None:
    """The shadow for a runtime run id, while it is still retained."""
    with _LOCK:
        return _RUNS.get(runtime_run_id)


def retained_run_ids() -> tuple[str, ...]:
    """Every runtime run id the registry still holds, oldest first."""
    with _LOCK:
        return tuple(_RUNS)


def reset_registry() -> None:
    """Forget every retained run.

    A test seam, and the honest kind: the registry is process-global, so
    a suite that asserts on it needs a way back to a clean slate that
    does not reach into module internals.
    """
    with _LOCK:
        _RUNS.clear()
        _SHAPES.clear()


# ---------------------------------------------------------------------------
# Graph shape, cached per configuration
# ---------------------------------------------------------------------------


def policy_shape_for_app(config: Settings, app: Any) -> PolicyShape:
    """Classify the policy from a compiled app the caller already holds.

    The convenience the two runners want: both have an app in hand at
    the moment they need a shape, and neither should have to know that
    reading one and classifying it are two functions in a module below.
    """
    return classify_from_graph_shape(config, read_graph_shape(app))


def graph_shape(config: Settings) -> GraphShape:
    """The compiled research graph's shape for this configuration.

    Cached on every input that changes the node set, because one
    caller — the scripted campaign's `before_episode` — has to seal
    *before* its graph exists and would otherwise compile one per
    episode. Everywhere else an app is already in hand and
    `read_graph_shape` is called directly.

    **`research_policy` is part of the key, and has to be.** W05 wrote
    this cache when `_build_graph_shape` dispatched on
    `enable_supervisor` alone; CAP-02 (ADR 0076) then made
    `research_policy` the *first* question that dispatch asks, so a
    fixed verify-and-repair configuration and a legacy one differ in a
    dimension the old key could not see. With four flags only, arm B and
    arm C — identical in `enable_supervisor`, `enable_verifier`,
    `enable_query_refiner` and `enable_checkpointing` — collided, and the
    second of the two to ask received the first one's shape from a warm
    cache. That is the one failure mode a campaign cannot tolerate: a
    manifest that records arm C against the graph arm B compiled.

    Precondition, unchanged from W05 and stated here because the key now
    makes it visible: `build_workflow` dispatches on the *module-global*
    `src.graph.workflow.settings`, so `config` must already be the
    configuration this process compiles under. The key identifies which
    configuration was asked for; it cannot make the compiler read it.
    """
    key = (
        str(getattr(config, "research_policy", "legacy") or "legacy"),
        bool(config.enable_supervisor),
        bool(config.enable_verifier),
        bool(config.enable_query_refiner),
        bool(config.enable_checkpointing),
    )
    with _LOCK:
        cached = _SHAPES.get(key)
    if cached is not None:
        return cached
    from src.graph.workflow import build_workflow

    app = build_workflow(enable_hitl=False)
    try:
        shape = read_graph_shape(app)
    finally:
        stack = getattr(app, "_checkpointer_exit_stack", None)
        if stack is not None:
            with contextlib.suppress(Exception):
                stack.close()
    with _LOCK:
        _SHAPES[key] = shape
    return shape


# ---------------------------------------------------------------------------
# Episode starters
# ---------------------------------------------------------------------------


def _principal_id(raw: str | None, *, lane: str) -> str:
    """The principal a trajectory may name.

    Never the key id itself (ADR 0067) and never the empty string: an
    unauthenticated caller becomes a declared synthetic principal rather
    than the hash of nothing, which would make every anonymous run look
    like one identity.
    """
    from src.observability.context import hash_principal

    hashed = hash_principal(raw or "")
    return f"pk_{hashed}" if hashed else f"synthetic:{lane}"


def _start(
    config: Settings,
    *,
    shape: PolicyShape,
    spec: Any,
    origin: EpisodeOrigin,
    runtime_run_id: str,
    principal: str,
    cost_ceiling_usd: str,
    repeat_index: int = 0,
    hitl_bypass: bool,
    hitl_bypass_reason: str | None,
    benchmark: BenchmarkBinding | None = None,
) -> ShadowRun | None:
    """Seal one episode and open its trajectory, or decline cleanly."""
    try:
        episode = seal_research_episode(
            config,
            shape=shape,
            spec=spec,
            origin=origin,
            runtime_run_id=runtime_run_id,
            repeat_index=repeat_index,
            hitl_bypass=hitl_bypass,
            hitl_bypass_reason=hitl_bypass_reason,
            benchmark=benchmark,
        )
    except ResearchBindingError as exc:
        # The configuration cannot be expressed as a sealed episode — an
        # unrepresentable policy shape, or a metered provider with no
        # approval. Declining is the designed outcome, not a failure of
        # the run, so it is INFO and the job never learns about it.
        log.info("contract_shadow_unavailable", extra={"detail": exc.detail[:200]})
        return None
    run = ShadowRun(
        episode=episode,
        runtime_run_id=runtime_run_id,
        principal_key_id=principal,
        cost_ceiling_usd=cost_ceiling_usd,
    )
    run.open()
    _remember(run)
    log.info(
        "contract_shadow_sealed",
        extra={
            "task_spec_id": episode.task_spec.task_spec_id,
            "manifest_digest": episode.manifest_digest,
            "arm_id": episode.shape.arm_id,
            "policy_id": episode.shape.policy_id,
        },
    )
    return run


def start_research_job(
    job: Any,
    workflow: Any,
    *,
    config: Settings,
    cost_ceiling_usd: float,
) -> ShadowRun | None:
    """Open a shadow for one API research job, or return `None`.

    `None` covers every "not today": the switch is off, the job is not a
    research job, the policy shape is unrepresentable, or the provider is
    metered and nothing approved the spend. The caller branches on
    `None` once and never again.
    """
    if not shadow_enabled(config) or getattr(job, "kind", "research") != "research":
        return None
    run: ShadowRun | None = None
    with _contained(None, "start_research_job"):
        shape = classify_from_graph_shape(config, read_graph_shape(workflow))
        spec = compile_research_intake(
            config,
            task_id=f"research-api:{job.job_id}",
            query=job.query,
            hitl_plan_review=bool(config.enable_hitl) and not bool(job.hitl_bypass),
            supervisor=shape.runtime_flags.enable_supervisor,
        )
        run = _start(
            config,
            shape=shape,
            spec=spec,
            origin="research_api",
            runtime_run_id=job.job_id,
            principal=_principal_id(job.principal_key_id, lane="research-api"),
            cost_ceiling_usd=money(cost_ceiling_usd),
            hitl_bypass=bool(job.hitl_bypass),
            hitl_bypass_reason="client-requested-bypass" if job.hitl_bypass else None,
        )
    return run


def start_eval_episode(
    *,
    config: Settings,
    shape: PolicyShape,
    runtime_run_id: str,
    benchmark: BenchmarkBinding,
    objective: str,
    task_id: str,
    repeat: int,
    origin: EpisodeOrigin,
    cost_ceiling_usd: float,
) -> ShadowRun | None:
    """Open a shadow for one selected eval case, or return `None`.

    The benchmark facts arrive as a `BenchmarkBinding` rather than being
    read here: the benchmark modules belong to P0-WO06, and this package
    keeps no import edge into them.
    """
    if not shadow_enabled(config):
        return None
    run: ShadowRun | None = None
    with _contained(None, "start_eval_episode"):
        spec = compile_eval_case(
            config,
            benchmark,
            task_id=task_id,
            objective=objective,
            supervisor=shape.runtime_flags.enable_supervisor,
        )
        run = _start(
            config,
            shape=shape,
            spec=spec,
            origin=origin,
            runtime_run_id=runtime_run_id,
            principal=f"synthetic:{origin.replace('_', '-')}",
            cost_ceiling_usd=money(cost_ceiling_usd),
            repeat_index=max(0, repeat - 1),
            hitl_bypass=True,
            hitl_bypass_reason="unattended-evaluation",
            benchmark=benchmark,
        )
    return run


# ---------------------------------------------------------------------------
# Contained hook facade — every runner call site goes through these
# ---------------------------------------------------------------------------


def observe_node(run: ShadowRun | None, node: str, state_update: Mapping[str, Any]) -> None:
    """Record one node completion. No-op for a missing or degraded run."""
    if run is None or run.degraded:
        return
    with _contained(run, "observe_node"):
        run.node_completed(node, state_update)


def observe_model_call(
    run: ShadowRun | None, call: LlmCallObservation, costs: RunCosts | None = None
) -> None:
    """Record one completed model call."""
    if run is None or run.degraded:
        return
    with _contained(run, "observe_model_call"):
        run.model_call(call, costs)


def observe_review_requested(
    run: ShadowRun | None,
    *,
    pause_number: int,
    pending: Sequence[str],
    deadline_seconds: int,
) -> None:
    """Record the plan-review park the runner is about to block on."""
    if run is None or run.degraded:
        return
    with _contained(run, "observe_review_requested"):
        run.checkpoint_and_review_requested(
            pause_number=pause_number,
            pending=pending,
            deadline_seconds=deadline_seconds,
        )


def observe_review_answered(
    run: ShadowRun | None, *, pause_number: int, action: str | None
) -> None:
    """Record the reviewer's answer to an open plan review."""
    if run is None or run.degraded:
        return
    with _contained(run, "observe_review_answered"):
        run.review_answered(pause_number=pause_number, action=action)


#: Job statuses a research run can end in, mapped to the terminal
#: recorder each one needs. `failed` splits on the error code because a
#: cost-ceiling stop is a budget event in the contract's vocabulary and a
#: `failed` row in the product's.
_BUDGET_STOP_CODES: Final[frozenset[str]] = frozenset(
    {"cost_budget_exceeded", "budget_exceeded", "session_cost_cap_refused"}
)


def observe_job_terminal(run: ShadowRun | None, job: Any) -> None:
    """Close the trajectory from the job row that is about to be written.

    Called from the runner's single terminal choke point, so every one of
    its terminal branches is covered without a hook per branch — and a
    branch added later is covered the day it lands.
    """
    if run is None or run.degraded:
        return
    with _contained(run, "observe_job_terminal"):
        status = str(getattr(job.status, "value", job.status))
        report = str(job.result or "")
        error_code = str(job.error_type or "")
        if status == "succeeded":
            run.complete(report)
        elif status == "cancelled":
            run.cancel(reason_code="user_requested", stage="runner", partial_report=report)
        elif error_code in _BUDGET_STOP_CODES:
            run.budget_stop(spent_usd=float(job.cost_usd or 0.0), partial_report=report)
        else:
            run.fail(
                error_code=error_code or "internal_unexpected",
                stage="runner",
                partial_report=report,
            )


def observe_episode_terminal(
    run: ShadowRun | None,
    *,
    error: str | None,
    report: str,
    error_code: str = "internal_unexpected",
) -> None:
    """Close an eval episode's trajectory from its record."""
    if run is None or run.degraded:
        return
    with _contained(run, "observe_episode_terminal"):
        if error:
            run.fail(error_code=error_code, stage="eval_runner", partial_report=report)
        else:
            run.complete(report)


def episode_block(
    run: ShadowRun | None,
    *,
    include_trajectory: bool = True,
) -> dict[str, Any] | None:
    """The additive block an eval record may carry, or `None`.

    `None` when there is no shadow, so a caller writes the key only when
    it has something to say — which is what keeps a `contract_shadow=off`
    campaign byte-identical to one built before the switch existed.
    """
    if run is None:
        return None
    block: dict[str, Any] | None = None
    with _contained(run, "episode_block"):
        summary = run.summary()
        if include_trajectory:
            summary["trajectory_jsonl"] = run.export_jsonl()
        block = summary
    return block


def parity_report(
    run: ShadowRun | None,
    legacy: LegacyOutcome,
    state: Mapping[str, Any] | None = None,
) -> tuple[ParityMismatch, ...]:
    """Compare a legacy record with this run's contract projections.

    Returns an empty tuple when there is nothing to compare — no shadow,
    or a degraded one — because "we did not look" and "we looked and
    everything agreed" must not be the same answer to a caller that only
    counts mismatches. Callers that care about the distinction read
    `run is None` first.
    """
    if run is None or run.degraded:
        return ()
    mismatches: tuple[ParityMismatch, ...] = ()
    with _contained(run, "parity_report"):
        mismatches = compare_outcomes(legacy, run.contract_outcome())
        if state is not None:
            mismatches = (*mismatches, *compare_research_state(run.episode.task_spec, state))
    return mismatches


# ---------------------------------------------------------------------------
# The scripted research campaign's `EpisodeHooks` implementation
# ---------------------------------------------------------------------------


class ScriptedResearchHooks:
    """Observe the scripted research tier through its own seam.

    Structural conformance to `src.eval.simulate_research.EpisodeHooks`,
    with no import in either direction: that module declares a `Protocol`
    and this class simply has the three methods.

    The seam's two rules are honoured exactly. `after_episode` writes
    `record["contracts"]` and nothing else — the harness restores the
    record and fails the row if it writes anything more. And nothing here
    can spend: the hooks run inside the tier's own spend guard, and the
    only work they do is hashing.
    """

    lane: Final[str] = "research_scripted"

    def __init__(self, config: Settings | None = None) -> None:
        self._config = config or default_settings

    def before_episode(self, query: Mapping[str, Any], repeat: int) -> ShadowRun | None:
        """Seal the episode before the scripted graph is built."""
        run: ShadowRun | None = None
        with _contained(None, "scripted_before_episode"):
            config = self._config
            shape = classify_from_graph_shape(config, graph_shape(config))
            binding = benchmark_binding_for(query, config=config)
            run = start_eval_episode(
                config=config,
                shape=shape,
                runtime_run_id=f"scripted:{query['query_id']}:{repeat}",
                benchmark=binding,
                objective=str(query["query"]),
                task_id=f"research-scripted:{query['query_id']}",
                repeat=repeat,
                origin="research_scripted",
                cost_ceiling_usd=float(config.max_cost_usd),
            )
        return run

    def on_stream_event(
        self, ctx: ShadowRun | None, mode: str, payload: Mapping[str, Any]
    ) -> None:
        """Record each node the scripted driver's own stream reports.

        Only the `updates` mode carries node names; `values` is the whole
        state after a step and this bridge has no business reading it.
        The payload is the driver's live object — it is read for keys and
        never mutated, which is the contract that seam documents.
        """
        if ctx is None or ctx.degraded or mode != "updates":
            return
        for node, update in payload.items():
            if str(node) == "__interrupt__":
                continue
            observe_node(ctx, str(node), update if isinstance(update, Mapping) else {})

    def after_episode(
        self,
        ctx: ShadowRun | None,
        record: dict[str, Any],
        final_state: Mapping[str, Any],
    ) -> None:
        """Close the trajectory and attach the one key a hook may write."""
        if ctx is None:
            return
        observe_episode_terminal(
            ctx,
            error=record.get("error"),
            report=str(final_state.get("draft_report") or ""),
        )
        block = episode_block(ctx)
        if block is not None:
            record[CONTRACTS_RECORD_KEY] = block


def scripted_research_hooks(config: Settings | None = None) -> ScriptedResearchHooks | None:
    """The scripted campaign's hooks, or `None` when shadowing is off.

    `None` is the whole of the default path, and the campaign's own seam
    is written so that `hooks=None` executes not one line of hook code.
    """
    resolved = config or default_settings
    return ScriptedResearchHooks(resolved) if shadow_enabled(resolved) else None


def benchmark_binding_for(
    query: Mapping[str, Any],
    *,
    config: Settings,
    suite_id: str = "research-benchmark",
    task_set_id: str = "research-benchmark-queries",
    dataset_version: str = "",
    rubric_versions: Mapping[str, str] | None = None,
) -> BenchmarkBinding:
    """Describe one benchmark case for the manifest, from its own content.

    Every digest is taken over the case as this checkout holds it, so two
    checkouts whose benchmark text differs mint different refs without a
    hand-bumped version. The rubric versions and the dataset fingerprint
    are read from `src.eval` lazily, inside this one function, so that
    importing the bridge does not pull the eval package onto an API
    worker's import graph.
    """
    from src.eval.benchmark_queries import RESEARCH_DATASET_VERSION
    from src.eval.metrics import RESEARCH_RUBRICS
    from src.eval.provenance import rubric_versions as read_rubric_versions

    return BenchmarkBinding(
        suite_id=suite_id,
        task_set_id=task_set_id,
        case_id=str(query["query_id"]),
        dataset_version=dataset_version or RESEARCH_DATASET_VERSION,
        case_material={
            "query_id": str(query["query_id"]),
            "domain": str(query.get("domain", "")),
            "expected_topics": ",".join(sorted(map(str, query.get("expected_topics", ())))),
        },
        rubric_versions=(
            dict(rubric_versions)
            if rubric_versions is not None
            else read_rubric_versions(RESEARCH_RUBRICS)
        ),
        judge_model=str(config.eval_judge_model),
    )


def legacy_job_outcome(job: Any) -> LegacyOutcome:
    """Project a `Job` row onto the parity check's bounded legacy view."""
    raw_status = str(getattr(job.status, "value", job.status))
    status: Literal["succeeded", "failed", "cancelled"] = (
        "succeeded"
        if raw_status == "succeeded"
        else "cancelled"
        if raw_status == "cancelled"
        # A non-terminal row cannot reach this function through the
        # runner, and a row that somehow did is not a success.
        else "failed"
    )
    report = str(job.result or "")
    error_code = str(job.error_type or "")
    return LegacyOutcome(
        surface="job",
        query=str(job.query),
        status=status,
        budget_stopped=error_code in _BUDGET_STOP_CODES,
        llm_calls=int(job.llm_calls or 0),
        cost_usd=money(job.cost_usd or 0.0),
        report_digest=(
            "sha256:" + hashlib.sha256(report.encode("utf-8")).hexdigest() if report else None
        ),
        task_spec_id=(job.task_spec_ref or {}).get("task_spec_id"),
        task_full_digest=(job.task_spec_ref or {}).get("full_digest"),
    )


def legacy_eval_outcome(record: Mapping[str, Any]) -> LegacyOutcome:
    """Project an eval record onto the same bounded legacy view."""
    state = record.get("state") or {}
    report = str(state.get("draft_report") or "")
    costs = record.get("costs") or {}
    return LegacyOutcome(
        surface="eval_record",
        query=str(record.get("query", "")),
        status="failed" if record.get("error") else "succeeded",
        llm_calls=int(costs.get("call_count") or 0),
        cost_usd=money(costs.get("total_cost_usd") or 0.0),
        report_digest=(
            "sha256:" + hashlib.sha256(report.encode("utf-8")).hexdigest() if report else None
        ),
    )


DataClassAlias = DataClass
"""Re-exported so a consumer can name the class without a second import."""


__all__ = [
    "BUDGET_WARNING_FRACTION",
    "CONTRACTS_RECORD_KEY",
    "MAX_RETAINED_RUNS",
    "SHADOW_RECORD_KEY",
    "ScriptedResearchHooks",
    "ShadowRun",
    "benchmark_binding_for",
    "episode_block",
    "graph_shape",
    "legacy_eval_outcome",
    "legacy_job_outcome",
    "observe_episode_terminal",
    "observe_job_terminal",
    "observe_model_call",
    "observe_node",
    "observe_review_answered",
    "observe_review_requested",
    "parity_report",
    "policy_shape_for_app",
    "reset_registry",
    "retained_run_ids",
    "scripted_research_hooks",
    "shadow_enabled",
    "shadow_run",
    "start_eval_episode",
    "start_research_job",
]
