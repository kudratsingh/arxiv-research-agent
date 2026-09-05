"""Plan, materialize, resume and report on a campaign.

The order here is the one RFC 09 §5.1 and RFC 11 §13 jointly require, and
each step exists because skipping it makes a later claim unprovable:

1. **Resolve the lock first.** W02's generator turns a suite ref, a split
   and an explicit case selection into exact revisions and digests. No
   alias, no "latest", no case that is not in the authorized development
   split.
2. **Freeze the protocol and derive the campaign id from it.** Raising a
   cap or changing the design moves the id, which is what makes "resume
   only on the same lock and cap" mechanical rather than procedural.
3. **Compile one TaskSpec per selected case, once.** Persisted into
   `task-set.json` and pinned by digest in the manifest, so a resume
   reuses the identical spec rather than recompiling one whose
   `compiled_at` would move every derived episode key.
4. **Compile the whole design matrix, then write the ledger.** Before any
   episode runs, every slot of `cases x repeats x arms` is on disk with
   a status.
5. **Only then seal and run episodes.** `plan` writes; `dry_run` writes
   nothing at all and initializes no provider.

`resume` re-derives the campaign id from what it was asked to run and
refuses if it does not equal the id on disk. That is the whole "same lock
and cap" rule: a raised cap is a different campaign, and the operator is
told to create one with lineage instead of being quietly allowed to spend
more inside the old one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from src.campaign.approval import LocalApprovalRecordBackend, assert_approval_covers
from src.campaign.arms import ArmId, CampaignArm, declare_arm
from src.campaign.episode import (
    SealedCampaignEpisode,
    assert_not_overwriting,
    compile_case_task,
    episode_directory,
    episode_is_complete,
    seal_campaign_episode,
)
from src.campaign.errors import CampaignError
from src.campaign.ledger import (
    DenominatorLedger,
    LedgerStatus,
    open_ledger,
    read_outcomes,
    reconcile,
)
from src.campaign.manifest import (
    CAMPAIGN_PLANNER_VERSION,
    CampaignLineage,
    CampaignManifestPayload,
    CampaignManifestStore,
    CampaignManifestV1,
    CampaignProtocol,
    CorpusModeChoice,
    DenominatorPolicy,
    derive_campaign_id,
    seal_campaign_manifest,
    write_json,
)
from src.campaign.matrix import PlannedEpisode, compile_matrix
from src.config import Settings
from src.contracts.kernel import (
    ImmutableObjectRef,
    Rfc3339Utc,
    StrictContractModel,
    sha256_digest,
)
from src.contracts.registry import (
    CampaignLock,
    IntendedUse,
    RegistryResolutionError,
    RegistryResolver,
    RegistryRole,
    SourceMode,
    TaskCase,
    generate_campaign_lock,
    validate_lock,
)
from src.contracts.research_binding import GraphShape, utc_timestamp
from src.contracts.run_manifest import (
    AttemptId,
    CampaignBudget,
    CampaignId,
    CheckpointCompatibility,
    CompletionReceipt,
    EpisodeBudget,
    ManifestFileStore,
    PolicyMember,
    RunManifestError,
    RunManifestV1,
    SafeLabel,
    manifest_compatibility,
    validate_resume,
)
from src.contracts.task_spec import TaskSpecRef, TaskSpecV1, build_task_spec_ref

#: Files the campaign root holds beside RFC 09 §5.3's sealed pair.
TASK_SET_FILENAME: Final[str] = "task-set.json"
LEDGER_FILENAME: Final[str] = "campaign-ledger.json"
ARM_CONFIG_DIRNAME: Final[str] = "arm-configs"

#: Where a research campaign writes by default. A separate root from
#: `outputs/eval/<timestamp>/`, which is the rollback the work order asks
#: for: the sequential runner keeps its own output layout untouched.
DEFAULT_OUTPUT_ROOT: Final[str] = "outputs/campaign/research-policy-v1"

#: A probe that hands the planner one compiled graph shape per arm. The
#: planner never compiles a graph itself — `build_workflow` reads the
#: process-global settings singleton, so a planner that tried to probe
#: five arms would have to mutate that singleton five times. Injecting
#: the probe keeps the planner pure and keeps arm capability a fact the
#: caller supplies evidence for.
GraphProbe = Callable[[ArmId], GraphShape]


class CampaignRequest(StrictContractModel):
    """What an operator asks for, before any of it is resolved.

    Separate from `CampaignProtocol` because a request names a *suite* and
    a *selection*; a protocol is what those resolved to. Keeping them
    apart is what lets `resume` re-derive a campaign id from a request and
    compare it with the one on disk.
    """

    protocol_id: SafeLabel
    stage: PolicyMember
    suite_ref: ImmutableObjectRef
    case_ids: tuple[str, ...]
    arms: tuple[ArmId, ...]
    repeats: Annotated[int, Field(ge=1)]
    corpus_mode: CorpusModeChoice
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)]
    provider: PolicyMember = "anthropic"
    resources: tuple[PolicyMember, ...] = ()
    approval_id: str | None = None
    episode_budget: EpisodeBudget
    campaign_budget: CampaignBudget
    output_root: Annotated[str, StringConstraints(min_length=1, max_length=200)] = (
        DEFAULT_OUTPUT_ROOT
    )
    lineage: CampaignLineage | None = None
    intended_use: IntendedUse = IntendedUse.DEVELOPMENT


class CampaignTaskSet(StrictContractModel):
    """RFC 09 §5.3's `task-set.json`: the specs the campaign compiled once.

    Persisted rather than recompiled on resume, and the reason is
    identity: `task_spec_id` is a digest over the whole spec *including*
    its compilation timestamp, so a recompiled spec would carry a
    different id, derive a different `replicate_group_id`, and land the
    resumed campaign in a different set of episode directories. Loading
    the stored specs and checking them against the refs the manifest
    sealed is what makes a resume land on the identical matrix.
    """

    schema_kind: Literal["campaign-task-set"] = "campaign-task-set"
    schema_version: Literal["1.0.0"] = "1.0.0"
    campaign_id: CampaignId
    task_specs: tuple[TaskSpecV1, ...]


class CampaignPlan(StrictContractModel):
    """Everything planning produced, before anything was written or run."""

    manifest: CampaignManifestV1
    episodes: tuple[PlannedEpisode, ...]
    ledger: DenominatorLedger
    task_specs: tuple[TaskSpecV1, ...]

    @property
    def campaign_id(self) -> CampaignId:
        return self.manifest.payload.campaign_id

    @property
    def runnable(self) -> tuple[PlannedEpisode, ...]:
        """Episodes an execution pass would attempt, in predeclared order."""
        return tuple(episode for episode in self.episodes if episode.runnable)

    def task_spec_for(self, case_id: str) -> TaskSpecV1:
        """The one TaskSpec compiled for `case_id`."""
        for spec in self.task_specs:
            origin = spec.benchmark_origin
            if origin is not None and origin.task_case_ref.id == case_id:
                return spec
        raise CampaignError(f"no TaskSpec was compiled for case {case_id}")


class DryRunEpisode(StrictContractModel):
    """One line of the dry-run plan: a slot and its zero-cost status."""

    design_index: Annotated[int, Field(ge=0)]
    case_id: str
    arm_id: ArmId
    repeat_index: Annotated[int, Field(ge=0)]
    order_in_block: Annotated[int, Field(ge=0)]
    episode_key: str
    run_id: str
    output_path: str
    status: Literal["planned", "excluded"]
    exclusion_reason: str | None = None
    cost_class: Literal["zero-cost-dry-run"] = "zero-cost-dry-run"
    projected_cost_usd: Literal["0.000000"] = "0.000000"


class DryRunPlan(StrictContractModel):
    """A whole campaign enumerated without touching a provider or the disk."""

    campaign_id: CampaignId
    protocol_digest: str
    lock_digest: str
    expected_episode_count: Annotated[int, Field(ge=1)]
    planned_episode_count: Annotated[int, Field(ge=0)]
    excluded_episode_count: Annotated[int, Field(ge=0)]
    chargeable: bool
    provider_initialized: Literal[False] = False
    network_calls: Literal[0] = 0
    episodes: tuple[DryRunEpisode, ...]

    @model_validator(mode="after")
    def enumerates_every_slot(self) -> DryRunPlan:
        if len(self.episodes) != self.expected_episode_count:
            raise ValueError("a dry run must enumerate every planned episode")
        return self


def plan_campaign(
    config: Settings,
    request: CampaignRequest,
    *,
    resolver: RegistryResolver,
    graph_probe: GraphProbe | None = None,
    now: datetime | None = None,
) -> CampaignPlan:
    """Resolve, freeze and enumerate a campaign. Writes nothing.

    Args:
        config: The campaign's base settings.
        request: What the operator asked for.
        resolver: W02's registry resolver.
        graph_probe: Optional source of one compiled graph shape per arm.
            Without it every implementable arm is `unverified` and its
            capability is proved at seal time instead.
        now: Resolution time; defaults to the wall clock.

    Returns:
        The plan, including the sealed campaign manifest and the ledger.

    Raises:
        CampaignError: The lock cannot be resolved, the protocol is
            incoherent, a case is missing an objective, or the approval
            does not cover a chargeable campaign.
    """
    moment = now or datetime.now(UTC)
    stamp = _stamp(moment)
    lock = _resolve_lock(request, resolver=resolver, now=moment)
    receipt = validate_lock(lock, validated_at=stamp, validator_ref=_validator_ref())
    protocol = _protocol(request)
    protocol_digest = sha256_digest(protocol)
    lock_digest = sha256_digest(lock)
    campaign_id = derive_campaign_id(
        protocol_digest=protocol_digest,
        lock_digest=lock_digest,
        lineage=request.lineage,
    )
    arms = tuple(
        declare_arm(arm_id, graph=graph_probe(arm_id) if graph_probe is not None else None)
        for arm_id in request.arms
    )
    objectives = _case_objectives(lock, resolver=resolver, request=request, now=moment)
    specs = tuple(
        compile_case_task(
            config,
            protocol=protocol,
            campaign_id=campaign_id,
            case_ref=case_ref,
            objective=objectives[case_ref.id],
            lock=lock,
            compiled_at=stamp,
        )
        for case_ref in lock.case_refs
    )
    task_refs = tuple(
        build_task_spec_ref(
            spec, artifact_locator=f"cas://sha256/{sha256_digest(spec).removeprefix('sha256:')}"
        )
        for spec in specs
    )
    by_case = {
        case_ref.id: ref for case_ref, ref in zip(lock.case_refs, task_refs, strict=True)
    }
    episodes = compile_matrix(
        campaign_id=campaign_id,
        arms=arms,
        case_refs=lock.case_refs,
        task_refs=by_case,
        repeats=request.repeats,
        seed=request.seed,
    )
    planned = sum(1 for episode in episodes if episode.runnable)
    try:
        payload = CampaignManifestPayload(
            campaign_id=campaign_id,
            created_at=stamp,
            created_by=f"campaign-planner/{CAMPAIGN_PLANNER_VERSION}",
            protocol=protocol,
            protocol_digest=protocol_digest,
            lock=lock,
            lock_digest=lock_digest,
            registry_validation_receipt=receipt,
            registry_validation_receipt_ref=ImmutableObjectRef(
                kind="registry_validation_receipt",
                id="campaign-lock-validation",
                revision="1.0.0",
                digest=sha256_digest(receipt),
            ),
            arms=arms,
            task_refs=task_refs,
            expected_episode_count=len(episodes),
            planned_episode_count=planned,
            excluded_episode_count=len(episodes) - planned,
            output_root=f"{request.output_root}/{campaign_id}",
            lineage=request.lineage,
        )
    except ValueError as exc:
        raise CampaignError(f"campaign manifest is incoherent: {exc}") from exc
    manifest = seal_campaign_manifest(payload)
    ledger = open_ledger(campaign_id=campaign_id, episodes=episodes, written_at=stamp)
    return CampaignPlan(
        manifest=manifest, episodes=episodes, ledger=ledger, task_specs=specs
    )


def dry_run(plan: CampaignPlan) -> DryRunPlan:
    """Enumerate every planned episode with its zero-cost status.

    A pure projection of an already-built plan. It initializes no
    provider, opens no socket and writes no file — and the campaign it
    describes has not been materialized either, so a dry run leaves the
    filesystem exactly as it found it.
    """
    payload = plan.manifest.payload
    return DryRunPlan(
        campaign_id=payload.campaign_id,
        protocol_digest=payload.protocol_digest,
        lock_digest=payload.lock_digest,
        expected_episode_count=payload.expected_episode_count,
        planned_episode_count=payload.planned_episode_count,
        excluded_episode_count=payload.excluded_episode_count,
        chargeable=payload.protocol.chargeable,
        episodes=tuple(
            DryRunEpisode(
                design_index=episode.design_index,
                case_id=episode.case_id,
                arm_id=episode.arm_id,
                repeat_index=episode.repeat_index,
                order_in_block=episode.order_in_block,
                episode_key=episode.episode_key,
                run_id=episode.run_id,
                output_path=episode.output_path,
                status="planned" if episode.runnable else "excluded",
                exclusion_reason=episode.exclusion_reason,
            )
            for episode in plan.episodes
        ),
    )


def write_campaign(root: Path, plan: CampaignPlan) -> Path:
    """Materialize the campaign directory. Refuses to touch an existing one.

    Writes, in order: the sealed manifest and lock with their digest
    sidecars, one arm config per declared arm, the compiled task set, and
    the ledger — which is therefore on disk before any episode could run.

    Args:
        root: Directory holding campaign roots.
        plan: The plan to materialize.

    Returns:
        The campaign root directory.

    Raises:
        CampaignError: The campaign directory already holds a sealed
            manifest.
    """
    payload = plan.manifest.payload
    directory = root / payload.campaign_id
    CampaignManifestStore().seal(directory, plan.manifest)
    for arm in payload.arms:
        write_json(
            directory / ARM_CONFIG_DIRNAME / f"{arm.arm_id}.json",
            arm.model_dump(mode="json"),
        )
    write_json(
        directory / TASK_SET_FILENAME,
        CampaignTaskSet(
            campaign_id=payload.campaign_id, task_specs=plan.task_specs
        ).model_dump(mode="json"),
    )
    write_ledger(directory, plan.ledger)
    return directory


def write_ledger(directory: Path, ledger: DenominatorLedger) -> None:
    """Write or rewrite the denominator ledger.

    Rewritten on every reconciliation, unlike the manifest and the lock:
    the ledger is a *derived* view of what the campaign directory holds,
    and rebuilding it from the receipts on disk is what stops an
    in-memory count from publishing itself as the campaign's record.
    """
    write_json(directory / LEDGER_FILENAME, ledger.model_dump(mode="json"))


def load_campaign(directory: Path) -> tuple[CampaignManifestV1, tuple[TaskSpecV1, ...]]:
    """Load a materialized campaign's sealed manifest and compiled task set.

    Raises:
        CampaignError: The manifest is missing or invalid, the task set is
            missing or unparseable, or a stored TaskSpec does not match
            the ref the manifest pinned. The last is substitution and is
            refused rather than repaired.
    """
    manifest = CampaignManifestStore().load(directory)
    path = directory / TASK_SET_FILENAME
    if not path.is_file():
        raise CampaignError("campaign directory has no compiled task set")
    try:
        specs = CampaignTaskSet.model_validate_json(
            path.read_text(encoding="utf-8")
        ).task_specs
    except (OSError, ValueError) as exc:
        raise CampaignError(f"campaign task set is invalid: {exc}") from exc
    recorded = manifest.payload.task_refs
    if len(specs) != len(recorded):
        raise CampaignError("campaign task set does not match the manifest's task refs")
    for spec, ref in zip(specs, recorded, strict=True):
        if build_task_spec_ref(spec, artifact_locator=ref.artifact_locator) != ref:
            raise CampaignError(
                f"stored TaskSpec {spec.task_spec_id} does not match its sealed ref"
            )
    return manifest, specs


def rebuild_plan(manifest: CampaignManifestV1, specs: tuple[TaskSpecV1, ...]) -> CampaignPlan:
    """Rebuild the matrix and ledger from a materialized campaign.

    Deterministic by construction: the arm declarations, the case order,
    the repeat count and the seed all come from the sealed manifest, and
    the TaskSpec refs come from it too — so the episode keys, run ids and
    output paths are byte-identical to the ones the original plan
    produced. That property is what makes resume safe.
    """
    payload = manifest.payload
    by_case = {
        case_ref.id: ref
        for case_ref, ref in zip(payload.lock.case_refs, payload.task_refs, strict=True)
    }
    episodes = compile_matrix(
        campaign_id=payload.campaign_id,
        arms=payload.arms,
        case_refs=payload.lock.case_refs,
        task_refs=by_case,
        repeats=payload.protocol.repeats,
        seed=payload.protocol.seed,
    )
    ledger = open_ledger(
        campaign_id=payload.campaign_id, episodes=episodes, written_at=payload.created_at
    )
    return CampaignPlan(
        manifest=manifest, episodes=episodes, ledger=ledger, task_specs=specs
    )


def resume_campaign(
    root: Path,
    *,
    campaign_id: CampaignId,
    request: CampaignRequest | None = None,
) -> tuple[CampaignPlan, tuple[PlannedEpisode, ...]]:
    """Reopen a campaign under the same lock and cap, or refuse.

    Args:
        root: Directory holding campaign roots.
        campaign_id: The campaign to resume.
        request: What the operator now wants to run. When given, its
            campaign id is re-derived and compared with the one on disk —
            a raised cap, a changed arm set, a different case selection or
            a new seed all move that id and all refuse here.

    Returns:
        The rebuilt plan and the episodes still to run, in predeclared
        order.

    Raises:
        CampaignError: The campaign is absent, or the request describes a
            different campaign. The message names the remedy: create a new
            campaign with lineage.
    """
    directory = root / campaign_id
    if not directory.is_dir():
        raise CampaignError(f"no campaign directory for {campaign_id}")
    manifest, specs = load_campaign(directory)
    if request is not None:
        _assert_same_campaign(manifest, request)
    plan = rebuild_plan(manifest, specs)
    pending = tuple(
        episode
        for episode in plan.runnable
        if not episode_is_complete(directory, episode)
    )
    return plan, pending


def campaign_status(root: Path, campaign_id: CampaignId) -> DenominatorLedger:
    """Reconcile a materialized campaign against what is on disk.

    Reads every terminal receipt the episode directories hold, folds them
    into the ledger and rewrites it. Reconciliation is idempotent and adds
    nothing: an episode that has not finished stays `not_started`.
    """
    directory = root / campaign_id
    manifest, specs = load_campaign(directory)
    plan = rebuild_plan(manifest, specs)
    outcomes = read_outcomes(directory, plan.ledger)
    reconciled = reconcile(plan.ledger, outcomes, reconciled_at=utc_timestamp())
    write_ledger(directory, reconciled)
    return reconciled


def seal_next_episode(
    config: Settings,
    *,
    root: Path,
    plan: CampaignPlan,
    episode: PlannedEpisode,
    graph: GraphShape,
    approval_backend: LocalApprovalRecordBackend,
    credential_probe: Any = None,
    sealed_at: Rfc3339Utc | None = None,
) -> SealedCampaignEpisode:
    """Seal one episode into its own directory, never over a completed one.

    Raises:
        CampaignError: The episode already completed, its directory
            already holds a sealed manifest, or admission failed.
    """
    directory = root / plan.manifest.payload.campaign_id
    assert_not_overwriting(directory, episode)
    sealed = seal_campaign_episode(
        config,
        campaign=plan.manifest,
        episode=episode,
        task_spec=plan.task_spec_for(episode.case_id),
        graph=graph,
        approval_backend=approval_backend,
        credential_probe=credential_probe,
        sealed_at=sealed_at,
    )
    try:
        ManifestFileStore().seal(episode_directory(directory, episode), sealed.manifest)
    except RunManifestError as exc:
        raise CampaignError(f"episode manifest is already sealed: {exc.detail}") from exc
    return sealed


def resume_episode(
    root: Path,
    *,
    campaign_id: CampaignId,
    episode: PlannedEpisode,
    accumulated_workflow_cost_usd: str = "0.000000",
    accumulated_judge_cost_usd: str = "0.000000",
    accumulated_campaign_cost_usd: str = "0.000000",
    approval_receipt: Any = None,
    checkpoint: CheckpointCompatibility | None = None,
) -> AttemptId:
    """Append a new attempt to an interrupted episode, or refuse.

    Delegates every precondition to W03's `validate_resume` — terminal
    receipt, digest compatibility, fresh approval, remaining headroom —
    and adds only the campaign's own reading: the run id does not change,
    a new attempt id is minted, and a repeat is never implemented this
    way.

    Raises:
        CampaignError: The episode has no sealed manifest, or resume is
            unsafe. Both are refusals; the caller creates a new run with
            lineage instead.
    """
    directory = root / campaign_id / episode.output_path
    try:
        manifest = ManifestFileStore().load(directory)
    except RunManifestError as exc:
        raise CampaignError(f"episode has no resumable manifest: {exc.detail}") from exc
    completion = _completion(directory)
    try:
        return validate_resume(
            manifest,
            checkpoint or manifest_compatibility(manifest),
            completion=completion,
            approval_receipt=approval_receipt,
            accumulated_workflow_cost_usd=accumulated_workflow_cost_usd,
            accumulated_judge_cost_usd=accumulated_judge_cost_usd,
            accumulated_campaign_cost_usd=accumulated_campaign_cost_usd,
        )
    except RunManifestError as exc:
        raise CampaignError(f"episode cannot resume: {exc.detail}") from exc


def preflight_approval(
    plan: CampaignPlan,
    backend: LocalApprovalRecordBackend,
    *,
    verified_at: Rfc3339Utc | None = None,
) -> Any:
    """Check the campaign's aggregate approval before episode one is sealed."""
    protocol = plan.manifest.payload.protocol
    return assert_approval_covers(
        backend,
        approval_id=protocol.approval_id,
        campaign_id=plan.manifest.payload.campaign_id,
        stage=protocol.stage,
        provider=protocol.provider,
        resources=protocol.resources,
        total_cost_usd_max=protocol.campaign_budget.total_cost_usd_max,
        episode_total_usd_max=protocol.episode_budget.total_cost_usd_max,
        workflow_usd_max=protocol.episode_budget.workflow_cost_usd_max,
        judge_usd_max=protocol.episode_budget.judge_cost_usd_max,
        verified_at=verified_at or utc_timestamp(),
    )


def budget_stop_reached(ledger: DenominatorLedger, cap: str) -> bool:
    """Whether accumulated campaign spend has reached the immutable cap.

    Enforcement is between episodes and can overshoot by the episode in
    flight — the same honest bound `--max-budget-usd` already documents,
    and the same string the manifest records. A stopped campaign may
    continue only under this cap; raising it is a new campaign.
    """
    from decimal import Decimal

    if Decimal(cap) <= 0:
        return False
    spent = sum(
        (
            Decimal(entry.workflow_cost_usd) + Decimal(entry.judge_cost_usd)
            for entry in ledger.entries
        ),
        Decimal("0"),
    )
    return spent >= Decimal(cap)


def default_episode_budget(
    config: Settings,
    arms: tuple[ArmId, ...],
    *,
    workflow_usd: str = "0.000000",
    judge_usd: str = "0.000000",
) -> EpisodeBudget:
    """The per-episode caps a campaign declares, counts derived from settings.

    The dollar caps default to zero — a Stage-0 campaign authorizes
    nothing — while the call and time bounds are the real ones the graph
    can reach under the campaign's ceiling configuration. A cap that is
    lower than what the graph can do would refuse a legitimate episode at
    admission; a cap invented larger would be a fiction.

    Args:
        config: The campaign's base settings.
        arms: The declared arm set, which fixes the ceiling configuration.
        workflow_usd: Approved workflow spend per episode.
        judge_usd: Approved judge spend per episode.

    Returns:
        The episode budget.

    Raises:
        CampaignError: The caps are not internally consistent.
    """
    from decimal import Decimal

    from src.campaign.arms import ceiling_settings as _ceiling
    from src.contracts.research_binding import requested_policy
    from src.contracts.task_spec import ProductSurface as _Surface

    limits = requested_policy(
        _ceiling(config, arms), _Surface.RESEARCH_EVAL, supervisor=True
    ).execution_limits
    judge_calls = 0
    if Decimal(judge_usd) > 0:
        from src.eval.metrics import RESEARCH_RUBRICS

        judge_calls = len(RESEARCH_RUBRICS)
    total = Decimal(workflow_usd) + Decimal(judge_usd)
    try:
        return EpisodeBudget(
            workflow_cost_usd_max=workflow_usd,
            judge_cost_usd_max=judge_usd,
            total_cost_usd_max=f"{total:.6f}",
            wall_time_seconds_max=limits.hard_timeout_seconds,
            workflow_model_calls_max=limits.max_model_calls,
            judge_model_calls_max=judge_calls,
            tool_calls_max=limits.max_tool_calls,
        )
    except ValueError as exc:
        raise CampaignError(f"episode budget is not coherent: {exc}") from exc


def default_campaign_budget(total_usd: str = "0.000000") -> CampaignBudget:
    """The aggregate cap, with the enforcement bound stated honestly.

    Enforcement happens between episodes, so the episode in flight when
    the ceiling is crossed overshoots by its own cost. That is what
    `--max-budget-usd` already does and what the manifest must say; a
    pre-call reservation would be a stronger claim and is not implemented.
    """
    return CampaignBudget(
        total_cost_usd_max=total_usd,
        enforcement="between-episodes-with-in-flight-overshoot-risk",
    )


def _assert_same_campaign(manifest: CampaignManifestV1, request: CampaignRequest) -> None:
    """Refuse a resume whose request is not the campaign on disk."""
    payload = manifest.payload
    derived = derive_campaign_id(
        protocol_digest=sha256_digest(_protocol(request)),
        lock_digest=payload.lock_digest,
        lineage=request.lineage,
    )
    if derived == payload.campaign_id:
        return
    stored = payload.protocol
    wanted = _protocol(request)
    changed = [
        name
        for name in type(stored).model_fields
        if getattr(stored, name) != getattr(wanted, name)
    ]
    raise CampaignError(
        "resume refused: this request is a different campaign "
        f"({', '.join(changed) or 'registry lock'} changed). Raising a cap or "
        "changing the protocol creates a new campaign with lineage to "
        f"{payload.campaign_id}; it never continues it."
    )


def _protocol(request: CampaignRequest) -> CampaignProtocol:
    try:
        return CampaignProtocol(
            protocol_id=request.protocol_id,
            stage=request.stage,
            suite_ref=request.suite_ref,
            case_ids=request.case_ids,
            arms=request.arms,
            repeats=request.repeats,
            corpus_mode=request.corpus_mode,
            seed=request.seed,
            provider=request.provider,
            resources=request.resources,
            approval_id=request.approval_id,
            episode_budget=request.episode_budget,
            campaign_budget=request.campaign_budget,
            denominator_policy=DenominatorPolicy(),
        )
    except ValueError as exc:
        raise CampaignError(f"campaign protocol is not coherent: {exc}") from exc


def _resolve_lock(
    request: CampaignRequest, *, resolver: RegistryResolver, now: datetime
) -> CampaignLock:
    mode = SourceMode.LIVE if request.corpus_mode == "live" else SourceMode.SNAPSHOT
    try:
        return generate_campaign_lock(
            resolver,
            request.suite_ref,
            case_ids=request.case_ids,
            repeats=request.repeats,
            intended_use=request.intended_use,
            source_mode=mode,
            now=now,
        )
    except RegistryResolutionError as exc:
        raise CampaignError(f"campaign lock does not resolve: {exc.detail}") from exc


def _case_objectives(
    lock: CampaignLock,
    *,
    resolver: RegistryResolver,
    request: CampaignRequest,
    now: datetime,
) -> Mapping[str, str]:
    """Read each locked case's objective from the registry, by exact ref."""
    objectives: dict[str, str] = {}
    for ref in lock.case_refs:
        try:
            envelope = resolver.resolve(
                ref,
                role=RegistryRole.EVALUATOR,
                intended_use=request.intended_use,
                now=now,
            )
        except RegistryResolutionError as exc:
            raise CampaignError(f"case {ref.id} does not resolve: {exc.detail}") from exc
        payload = envelope.payload
        if not isinstance(payload, TaskCase):
            raise CampaignError(f"case {ref.id} did not resolve to a task case")
        objectives[ref.id] = payload.task_input.objective
    return objectives


def _completion(directory: Path) -> CompletionReceipt | None:
    path = directory / "completion.json"
    if not path.is_file():
        return None
    try:
        return CompletionReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CampaignError(f"completion receipt is invalid: {exc}") from exc


def _validator_ref() -> ImmutableObjectRef:
    return ImmutableObjectRef(
        kind="registry_validator",
        id="campaign-planner",
        revision="1.0.0",
        digest=sha256_digest(
            {"validator": "src.campaign.planner", "version": CAMPAIGN_PLANNER_VERSION}
        ),
    )


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def pending_summary(
    plan: CampaignPlan, pending: Sequence[PlannedEpisode]
) -> Mapping[str, int]:
    """Counts an operator sees before an execution pass starts."""
    return {
        "expected": plan.manifest.payload.expected_episode_count,
        "planned": plan.manifest.payload.planned_episode_count,
        "excluded": plan.manifest.payload.excluded_episode_count,
        "pending": len(pending),
        "already_complete": plan.manifest.payload.planned_episode_count - len(pending),
    }


def status_counts(ledger: DenominatorLedger) -> Mapping[str, int]:
    """Ledger counts keyed by status, with every status present."""
    return {status.value: ledger.report.counts.get(status.value, 0) for status in LedgerStatus}


__all__ = [
    "ARM_CONFIG_DIRNAME",
    "DEFAULT_OUTPUT_ROOT",
    "LEDGER_FILENAME",
    "TASK_SET_FILENAME",
    "CampaignArm",
    "CampaignPlan",
    "CampaignRequest",
    "CampaignTaskSet",
    "DryRunEpisode",
    "DryRunPlan",
    "GraphProbe",
    "RunManifestV1",
    "TaskSpecRef",
    "budget_stop_reached",
    "campaign_status",
    "default_campaign_budget",
    "default_episode_budget",
    "dry_run",
    "load_campaign",
    "pending_summary",
    "plan_campaign",
    "preflight_approval",
    "rebuild_plan",
    "resume_campaign",
    "resume_episode",
    "seal_next_episode",
    "status_counts",
    "write_campaign",
    "write_ledger",
]
