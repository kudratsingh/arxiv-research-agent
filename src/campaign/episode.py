"""Seal one campaign episode: the campaign's half of RFC 09 §5.1.

W05 already seals a *shadow* episode. This module seals a *campaign*
one, and the difference is the four fields W05 could not fill in and
said so rather than inventing:

- the campaign id is the campaign's, not `camp_shadow-local`;
- `campaign_lock_ref` addresses a real W02 lock instead of an
  `unresolved` placeholder;
- `registry_resolution` carries the suite, task set, case, split, rubric,
  grader and label refs the lock actually resolved;
- the budgets are the campaign's approved caps, and the approval snapshot
  comes from an external record — which is what lets a metered provider
  be admitted at all. Under a metered provider with no approval, sealing
  fails closed exactly as it does today.

Everything else is deliberately W05's: the settings, prompt, tool,
source, code and environment snapshots, the runtime projection and the
admission controller all come from `src/contracts/research_binding.py`
and `src/contracts/run_manifest.py`, so a campaign manifest and a shadow
manifest describe the same run the same way.

The one thing this module refuses to take on faith is the arm. A planned
episode says "arm C"; `seal_campaign_episode` classifies the *compiled
graph* it was handed and refuses if the graph runs something else. A plan
can claim a capability; a seal cannot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal

from src.campaign.approval import LocalApprovalRecordBackend
from src.campaign.arms import ArmId, arm_settings, ceiling_settings, classify_arm
from src.campaign.errors import CampaignError
from src.campaign.manifest import CAMPAIGN_PLANNER_VERSION, CampaignManifestV1, CampaignProtocol
from src.campaign.matrix import PlannedEpisode
from src.config import Settings
from src.contracts.kernel import (
    DataClass,
    Digest,
    ImmutableObjectRef,
    Rfc3339Utc,
    StrictContractModel,
    sha256_digest,
)
from src.contracts.registry import CampaignLock
from src.contracts.research_binding import (
    ResearchBindingError,
    code_snapshot,
    compiler_ref,
    environment_snapshot,
    policy_snapshot,
    prompt_snapshot,
    provider_snapshot,
    requested_policy,
    retention_policy_ref,
    settings_schema_digest,
    settings_snapshot,
    source_scope,
    source_snapshot,
    tool_snapshot,
    utc_timestamp,
)
from src.contracts.run_manifest import (
    AdmissionPlan,
    BudgetSnapshot,
    CompilationSnapshot,
    DeterminismClass,
    EvaluationBudget,
    EvaluationSnapshot,
    InvocationSnapshot,
    PolicyProviderProjection,
    PolicyRuntimeProjection,
    PolicyRuntimeProjectionPayload,
    PolicyRuntimeProjectionRef,
    PolicySnapshot,
    PrivacySnapshot,
    RegistryResolution,
    RetrySnapshot,
    RunIdentity,
    RunLineage,
    RunManifestError,
    RunManifestPayload,
    RunManifestV1,
    RuntimeConfigSnapshot,
    SamplingSnapshot,
    build_policy_runtime_projection,
    resolve_admission,
    seal_manifest,
)
from src.contracts.task_spec import (
    BenchmarkOrigin,
    CorpusMode,
    PlatformPolicyCeiling,
    ProductSurface,
    TaskCompilationReceipt,
    TaskKind,
    TaskPolicyBundle,
    TaskSpecV1,
    WorkflowCostBoundary,
    build_task_spec_ref,
    compile_benchmark_case,
    persist_compiled_task,
)

#: Every control-plane class the candidate's runtime projection excludes.
#: The manifest model requires the complete set, so it is named once.
_ExcludedClass = Literal[
    "sealed-case-and-split-identity",
    "evaluator-and-label-refs",
    "approval-metadata",
    "private-object-locators",
    "hidden-rubric-content",
]
_EXCLUDED_PROJECTION_CLASSES: Final[tuple[_ExcludedClass, ...]] = (
    "sealed-case-and-split-identity",
    "evaluator-and-label-refs",
    "approval-metadata",
    "private-object-locators",
    "hidden-rubric-content",
)


class SealedCampaignEpisode(StrictContractModel):
    """One episode's sealed record, in the order sealing produced it."""

    episode: PlannedEpisode
    task_spec: TaskSpecV1
    receipt: TaskCompilationReceipt
    manifest: RunManifestV1
    projection: PolicyRuntimeProjection
    policy: PolicySnapshot
    chargeable: bool

    @property
    def manifest_digest(self) -> Digest:
        return self.manifest.integrity.payload_sha256


class _NullTaskStore:
    """A task store that keeps nothing and admits it.

    `persist_compiled_task` wants a store; a campaign's TaskSpecs are
    already addressed by digest inside every episode manifest, and W07
    does not own a task-artifact backend. Storing nothing and saying so
    is better than a directory that pretends to be one.
    """

    def put(self, spec: TaskSpecV1) -> None:
        return None

    def get(self, task_spec_id: str) -> TaskSpecV1 | None:
        return None


def campaign_cost_boundary(protocol: CampaignProtocol) -> WorkflowCostBoundary:
    """The workflow spend boundary every TaskSpec in the campaign carries.

    Zero and `forbidden` for a Stage-0 campaign, which is what makes a
    metered provider fail admission. Positive and
    `requires_external_approval` only when the protocol names an approval
    id — and `CampaignProtocol` already refuses a positive cap without
    one, so a ceiling here can never outrun its authorization.
    """
    if not protocol.chargeable:
        return WorkflowCostBoundary(chargeable_work="forbidden", workflow_spend_ceiling_usd="0.000000")
    return WorkflowCostBoundary(
        chargeable_work="requires_external_approval",
        workflow_spend_ceiling_usd=protocol.episode_budget.workflow_cost_usd_max,
    )


def compile_case_task(
    config: Settings,
    *,
    protocol: CampaignProtocol,
    campaign_id: str,
    case_ref: ImmutableObjectRef,
    objective: str,
    lock: CampaignLock,
    compiled_at: Rfc3339Utc | None = None,
) -> TaskSpecV1:
    """Compile the one TaskSpec every arm and repeat of this case will use.

    Compiled under the campaign's *ceiling* settings, not one arm's: the
    spec owns maximum permissions (work-order invariant 1) and every arm's
    effective policy is then narrower or equal, which the admission
    controller proves at each seal. Compiling per arm would give two
    samples of the same case different task identities and silently break
    the pairing that the whole design rests on (RFC 09 §4).

    Args:
        config: The campaign's base settings.
        protocol: The frozen protocol.
        campaign_id: The campaign, folded into the task id.
        case_ref: The locked case.
        objective: The case's objective, read from the registry.
        lock: The campaign lock, for the benchmark origin's suite refs.
        compiled_at: Compilation time.

    Returns:
        The compiled, immutable TaskSpec.

    Raises:
        CampaignError: The case cannot be compiled under this protocol.
    """
    ceiling = ceiling_settings(config, protocol.arms)
    boundary = campaign_cost_boundary(protocol)
    requested = _with_workflow_cost(
        requested_policy(ceiling, ProductSurface.RESEARCH_EVAL, supervisor=True), boundary
    )
    platform = _platform_ceiling(ceiling, requested, boundary)
    origin = BenchmarkOrigin(
        suite_ref=lock.suite_ref,
        task_set_ref=_task_set_ref(lock),
        task_case_ref=case_ref,
    )
    try:
        return compile_benchmark_case(
            task_id=f"campaign/{campaign_id}/{case_ref.id}",
            task_kind=TaskKind.RESEARCH_FOCUSED_EVIDENCE_REVIEW,
            objective=objective,
            candidate_visible_refs=(),
            origin=origin,
            product_surface=ProductSurface.RESEARCH_EVAL,
            requested_policy=requested,
            platform_policy=platform,
            compiler_ref=compiler_ref(),
            compiled_at=compiled_at or utc_timestamp(),
        )
    except ValueError as exc:
        raise CampaignError(f"case {case_ref.id} does not compile: {exc}") from exc


def seal_campaign_episode(
    config: Settings,
    *,
    campaign: CampaignManifestV1,
    episode: PlannedEpisode,
    task_spec: TaskSpecV1,
    graph: Any,
    approval_backend: LocalApprovalRecordBackend,
    credential_probe: Any = None,
    lineage: RunLineage | None = None,
    sealed_at: Rfc3339Utc | None = None,
) -> SealedCampaignEpisode:
    """Seal one episode's configuration before its first node runs.

    RFC 09 §5.1's order, unchanged: persist the compilation receipt,
    resolve the policy against the compiled graph, resolve admission —
    which is where a metered provider without approval fails closed —
    build and hash the candidate-safe projection, then hash and seal the
    control-plane payload.

    Args:
        config: The campaign's base settings.
        campaign: The sealed campaign manifest.
        episode: The planned slot being sealed.
        task_spec: The case's compiled TaskSpec.
        graph: The `GraphShape` of the compiled graph that will run.
        approval_backend: Where the external approval record is read.
        credential_probe: Called by the admission controller *after* the
            approval verifies, and never before.
        lineage: Set when this run supersedes an earlier one.
        sealed_at: Seal time.

    Returns:
        The sealed episode.

    Raises:
        CampaignError: The graph does not run the declared arm, the
            episode is excluded, or admission fails.
    """
    if not episode.runnable:
        raise CampaignError(
            f"episode {episode.case_id}/{episode.arm_id} is excluded: "
            f"{episode.exclusion_reason}"
        )
    payload = campaign.payload
    protocol = payload.protocol
    moment = sealed_at or utc_timestamp()
    arm_id: ArmId = episode.arm_id
    cfg = arm_settings(config, arm_id)

    try:
        shape = classify_arm(config, arm_id, graph)
        policy = policy_snapshot(shape)
    except ResearchBindingError as exc:
        raise CampaignError(f"arm {arm_id} cannot be expressed: {exc.detail}") from exc

    task_ref = build_task_spec_ref(task_spec, artifact_locator=_cas(sha256_digest(task_spec)))
    if task_ref != episode.task_ref:
        raise CampaignError(
            "the compiled TaskSpec is not the one this episode was planned against"
        )
    receipt = persist_compiled_task(
        task_spec, _NullTaskStore(), artifact_locator=task_ref.artifact_locator
    )

    sources = source_snapshot(cfg, source_scope(cfg))
    # Checked before admission, not after: a live-source run under a
    # snapshot campaign is a *design* failure, and letting the admission
    # controller report it as a policy-narrowing error would name the
    # wrong problem.
    _assert_corpus_mode(protocol, sources.input_corpus_mode)
    if sources.input_corpus_mode is not task_spec.source_scope.corpus_mode:
        raise CampaignError(
            "arm settings changed the corpus mode the TaskSpec compiled under"
        )

    boundary = campaign_cost_boundary(protocol)
    effective = _with_workflow_cost(
        requested_policy(
            cfg,
            ProductSurface.RESEARCH_EVAL,
            supervisor=shape.runtime_flags.enable_supervisor,
        ),
        boundary,
    )
    provider = provider_snapshot(cfg)
    cap = protocol.episode_budget.workflow_cost_usd_max
    try:
        decision = resolve_admission(
            AdmissionPlan(
                campaign_id=payload.campaign_id,
                stage=protocol.stage,
                provider=provider.llm.provider,
                resources=protocol.resources,
                task_policy=_bundle(task_spec),
                effective_policy=effective,
                platform_workflow_cost_usd=cap,
                campaign_workflow_allocation_usd=cap,
                provider_workflow_cost_usd=cap,
                episode_budget=protocol.episode_budget,
                provider_metered=provider.llm.metered,
                approval_id=protocol.approval_id,
            ),
            verified_at=moment,
            approval_backend=approval_backend,
            credential_probe=credential_probe,
        )
    except RunManifestError as exc:
        raise CampaignError(f"episode admission failed closed: {exc.detail}") from exc

    prompts = prompt_snapshot()
    tools = tool_snapshot(cfg)
    values = settings_snapshot(cfg)
    runtime_config = RuntimeConfigSnapshot(
        settings_schema_digest=settings_schema_digest(cfg),
        effective_values=values,
        effective_values_digest=sha256_digest(values),
    )
    invocation = InvocationSnapshot(
        enable_hitl=False,
        hitl_bypass=True,
        # 07 §4: a human plan edit would make two arms incomparable, so
        # an unattended campaign bypasses the pause and records why.
        hitl_bypass_reason="unattended-evaluation",
        checkpoint_mode="persistent" if cfg.enable_checkpointing else "disabled",
    )
    identity = RunIdentity(
        campaign_id=payload.campaign_id,
        episode_key=episode.episode_key,
        replicate_group_id=episode.replicate_group_id,
        run_id=episode.run_id,
        repeat_index=episode.repeat_index,
        created_at=moment,
        created_by=f"campaign-planner/{CAMPAIGN_PLANNER_VERSION}",
    )
    randomness = _randomness(protocol, episode, mock=bool(cfg.use_mock_data))
    evaluation = _evaluation_snapshot(cfg, protocol, payload.lock)

    projection_payload = PolicyRuntimeProjectionPayload(
        identity={
            "campaign_id": identity.campaign_id,
            "run_id": identity.run_id,
            "repeat_index": identity.repeat_index,
        },
        task=_agent_safe(task_spec),
        policy=policy,
        runtime_config=runtime_config,
        invocation=invocation,
        workflow_provider=PolicyProviderProjection(
            provider=provider.llm.provider,
            api_protocol_version=provider.llm.api_protocol_version,
            model_resolution=provider.llm.model_resolution,
            routes=provider.llm.routes,
            sampling=provider.llm.sampling,
            retry=provider.llm.retry,
            prompt_cache=provider.llm.prompt_cache,
        ),
        prompts=prompts,
        tools=tools,
        sources=sources,
        limits=decision.resolution.resolved_limits,
    )
    projection_digest = sha256_digest(projection_payload)
    receipt_digest = sha256_digest(receipt)
    lock_ref = campaign_lock_ref(payload.campaign_id, payload.lock_digest)

    try:
        manifest_payload = RunManifestPayload(
            identity=identity,
            lineage=lineage,
            compilation=CompilationSnapshot(
                receipt_ref=ImmutableObjectRef(
                    kind="compilation_receipt",
                    id=receipt.receipt_id.replace("_", "-"),
                    revision="1.0.0",
                    digest=receipt_digest,
                ),
                receipt_locator=_cas(receipt_digest),
            ),
            task=task_ref,
            campaign_lock_ref=lock_ref,
            campaign_lock_locator=f"{payload.output_root}/campaign-lock.json",
            registry_resolution=registry_resolution(payload.lock, episode.case_ref, sources),
            policy=policy,
            runtime_config=runtime_config,
            invocation=invocation,
            providers=provider,
            prompts=prompts,
            tools=tools,
            sources=sources,
            evaluation=evaluation,
            randomness=randomness,
            admission_resolution=decision.resolution,
            budgets=BudgetSnapshot(
                episode=protocol.episode_budget,
                campaign=protocol.campaign_budget,
            ),
            approval=decision.approval,
            code=code_snapshot(),
            environment=environment_snapshot("local-eval"),
            outputs=_outputs(payload.output_root, episode),
            privacy=PrivacySnapshot(
                task_data_class=task_spec.data_policy.data_class,
                registry_object_classification=DataClass.INTERNAL,
                retention_policy_ref=retention_policy_ref(),
                redaction_policy_version="1.0.0",
            ),
            policy_runtime_projection=PolicyRuntimeProjectionRef(
                artifact_ref=ImmutableObjectRef(
                    kind="policy_runtime_projection",
                    id=f"projection-{projection_digest.removeprefix('sha256:')[:24]}",
                    revision="1.0.0",
                    digest=projection_digest,
                ),
                artifact_locator=_cas(projection_digest),
                excluded_classes=_EXCLUDED_PROJECTION_CLASSES,
            ),
        )
        manifest = seal_manifest(manifest_payload)
        projection = build_policy_runtime_projection(manifest, task_spec)
    except (RunManifestError, ValueError) as exc:
        raise CampaignError(f"episode manifest does not seal: {exc}") from exc

    return SealedCampaignEpisode(
        episode=episode,
        task_spec=task_spec,
        receipt=receipt,
        manifest=manifest,
        projection=projection,
        policy=policy,
        chargeable=decision.chargeable,
    )


def campaign_lock_ref(campaign_id: str, lock_digest: Digest) -> ImmutableObjectRef:
    """The manifest's typed reference to this campaign's registry lock."""
    return ImmutableObjectRef(
        kind="campaign_lock",
        id=campaign_id.replace("_", "-"),
        revision="1.0.0",
        digest=lock_digest,
    )


def registry_resolution(
    lock: CampaignLock, case_ref: ImmutableObjectRef, sources: Any
) -> RegistryResolution:
    """The manifest's registry section, entirely from the lock.

    Every ref here was resolved by W02's generator against exact
    revisions and digests, which is what W05 could not do and recorded as
    `unresolved`. `source_snapshot_ref` mirrors the source snapshot rather
    than the lock, because the manifest's own cross-section invariant
    requires the two to agree and the source of truth for "is this a
    frozen corpus" is the run's source mode.
    """
    return RegistryResolution(
        suite_ref=lock.suite_ref,
        task_set_ref=_task_set_ref(lock),
        task_case_ref=case_ref,
        split_assignment_ref=_only(lock, "split_assignment"),
        rubric_set_refs=_all(lock, "rubric_set"),
        grader_profile_refs=_all(lock, "grader_profile"),
        label_set_refs=_all(lock, "label_set"),
        source_snapshot_ref=sources.source_snapshot_ref,
        validation_receipt_ref=_validation_receipt_ref(lock),
    )


def _validation_receipt_ref(lock: CampaignLock) -> ImmutableObjectRef:
    """A typed ref to the receipt W02's `validate_lock` produces."""
    return ImmutableObjectRef(
        kind="registry_validation_receipt",
        id="campaign-lock-validation",
        revision="1.0.0",
        digest=sha256_digest(lock),
    )


def _task_set_ref(lock: CampaignLock) -> ImmutableObjectRef:
    return _only(lock, "task_set")


def _only(lock: CampaignLock, kind: str) -> ImmutableObjectRef:
    refs = _all(lock, kind)
    if len(refs) != 1:
        raise CampaignError(f"campaign lock resolves {len(refs)} {kind} refs, expected one")
    return refs[0]


def _all(lock: CampaignLock, kind: str) -> tuple[ImmutableObjectRef, ...]:
    return tuple(ref for ref in lock.resolved_refs if ref.kind == kind)


def _bundle(spec: TaskSpecV1) -> TaskPolicyBundle:
    """Re-read the compiled spec's own policy as the admission bundle."""
    return TaskPolicyBundle(
        source_scope=spec.source_scope,
        freshness=spec.freshness,
        tool_policy=spec.tool_policy,
        execution_limits=spec.execution_limits,
        autonomy=spec.autonomy,
        data_policy=spec.data_policy,
    )


def _with_workflow_cost(
    bundle: TaskPolicyBundle, boundary: WorkflowCostBoundary
) -> TaskPolicyBundle:
    """Replace a bundle's workflow cost boundary with the campaign's.

    W05's `requested_policy` hardcodes a zero, forbidden ceiling, and it
    is right to: a shadow observation is never authority to spend. A
    campaign is the object that *can* carry approved spend, so it
    substitutes its own boundary here rather than editing that module.
    """
    limits = bundle.execution_limits.model_copy(update={"workflow_cost": boundary})
    return bundle.model_copy(update={"execution_limits": limits})


def _platform_ceiling(
    config: Settings, requested: TaskPolicyBundle, boundary: WorkflowCostBoundary
) -> PlatformPolicyCeiling:
    """The deployment ceiling, widened only in the dimension the campaign owns.

    Every other dimension is exactly what the requested policy asks for,
    so `intersect_with_platform` is an identity there; only the spend
    boundary is the campaign's, and only up to the cap an external
    approval already covers.
    """
    from src.contracts.research_binding import platform_ceiling

    base = platform_ceiling(config, requested)
    return base.model_copy(
        update={
            "chargeable_work": boundary.chargeable_work,
            "workflow_spend_ceiling_usd": boundary.workflow_spend_ceiling_usd,
        }
    )


def _agent_safe(spec: TaskSpecV1) -> Mapping[str, Any]:
    from src.contracts.task_spec import agent_safe_task_projection

    return agent_safe_task_projection(spec)


def _cas(digest: str) -> str:
    return f"cas://sha256/{digest.removeprefix('sha256:')}"


def _outputs(output_root: str, episode: PlannedEpisode) -> Any:
    from src.contracts.run_manifest import OutputSnapshot

    return OutputSnapshot(
        root=f"{output_root}/{episode.output_path}",
        artifact_schema_version="1.0.0",
        trajectory_schema_version="1.0.0",
        verification_schema_version="1.0.0",
    )


def _randomness(protocol: CampaignProtocol, episode: PlannedEpisode, *, mock: bool) -> Any:
    """One root seed per episode, derived from the campaign's recorded seed.

    RFC 09 §9 asks for a root seed per repeat and component seeds derived
    from it by a documented function, and for the determinism class to be
    stated honestly rather than implied by the presence of a seed. The
    class here is the truthful one for this repository: deterministic
    only under the mock corpus, and `live-input-stochastic-model`
    otherwise, because the provider exposes no seed and retrieval varies.
    """
    from src.contracts.run_manifest import RandomnessSnapshot

    material = sha256_digest({"seed": protocol.seed, "episode_key": episode.episode_key})
    root_seed = int(material.removeprefix("sha256:")[:12], 16)
    return RandomnessSnapshot(
        repeat_index=episode.repeat_index,
        root_seed=root_seed,
        component_seeds_ref=ImmutableObjectRef(
            kind="seed_map",
            id="campaign-episode-seeds",
            revision="1.0.0",
            digest=sha256_digest(
                {"root_seed": root_seed, "components": ["harness", "interleaving"]}
            ),
        ),
        determinism_class=(
            DeterminismClass.DETERMINISTIC_LOCAL
            if mock
            else DeterminismClass.LIVE_INPUT_STOCHASTIC_MODEL
        ),
    )


def _evaluation_snapshot(
    config: Settings, protocol: CampaignProtocol, lock: CampaignLock
) -> EvaluationSnapshot:
    """The evaluation section, with the campaign's own judge budget.

    W05's equivalent hardcodes a zero judge cap and says why: a shadow
    manifest authorizes nothing. A campaign's judge spend is real and is
    approved separately from workflow spend (ADR 0050's split), so it is
    carried here — and because the manifest's own cross-section invariant
    ties `approval.required` to any positive cap, a campaign that budgets
    for judges cannot seal without an approval that covers them.
    """
    from src.eval.metrics import RESEARCH_RUBRICS
    from src.eval.provenance import rubric_versions

    versions = rubric_versions(RESEARCH_RUBRICS)
    return EvaluationSnapshot(
        grader_profile_refs=_all(lock, "grader_profile"),
        judge_routes={name: str(config.eval_judge_model) for name in sorted(versions)},
        judge_prompt_bundle_ref=ImmutableObjectRef(
            kind="prompt_bundle",
            id="research-judge-rubrics",
            revision="1.0.0",
            digest=sha256_digest(dict(versions)),
        ),
        blinding_policy="unblinded-development-campaign",
        ordering_policy=protocol.interleaving,
        sampling=SamplingSnapshot(temperature="0.000000", maximum_output_tokens=4096),
        retry=RetrySnapshot(timeout_seconds=30, max_retries=0),
        null_score_policy="retain-and-report-denominator",
        budget=EvaluationBudget(
            cost_usd_max=protocol.episode_budget.judge_cost_usd_max,
            model_calls_max=protocol.episode_budget.judge_model_calls_max,
        ),
    )


def _assert_corpus_mode(protocol: CampaignProtocol, mode: CorpusMode) -> None:
    """A live campaign runs live sources; a snapshot campaign never does.

    The aggregation boundary 07 §6 Stage 4 draws has to be enforced where
    the episode is sealed, not only where the summary is written: a
    campaign declared `snapshot` whose episodes reached live arXiv would
    produce a controlled-looking aggregate over uncontrolled inputs.
    """
    live = mode is CorpusMode.LIVE
    if live != (protocol.corpus_mode == "live"):
        raise CampaignError(
            f"campaign declares corpus_mode={protocol.corpus_mode} but the "
            f"episode resolves to {mode.value}; a controlled and a live "
            "campaign are never the same experiment"
        )


def episode_directory(root: Path, episode: PlannedEpisode) -> Path:
    """The absolute directory for one episode's artifacts."""
    return root / episode.output_path


def episode_is_complete(root: Path, episode: PlannedEpisode) -> bool:
    """Whether a terminal completion receipt already exists for this slot."""
    return (episode_directory(root, episode) / "completion.json").is_file()


def assert_not_overwriting(root: Path, episode: PlannedEpisode) -> None:
    """Refuse to write into an episode directory that already finished.

    `ManifestFileStore.seal` already refuses to replace a sealed manifest;
    this is the campaign-level half of the same rule and it fires earlier
    and with a message about the *campaign*, because "completed episode
    artifacts are never overwritten" is a property an operator resuming a
    300-episode run needs stated in those words.
    """
    if episode_is_complete(root, episode):
        raise CampaignError(
            f"episode {episode.output_path} already has a terminal completion "
            "receipt; a completed episode is never overwritten. Rerun it as a "
            "new run with lineage instead."
        )


def campaign_spend(entries: Sequence[Any]) -> Decimal:
    """Accumulated workflow + judge dollars over reconciled ledger entries."""
    return sum(
        (Decimal(entry.workflow_cost_usd) + Decimal(entry.judge_cost_usd) for entry in entries),
        Decimal("0"),
    )


__all__ = [
    "SealedCampaignEpisode",
    "assert_not_overwriting",
    "campaign_cost_boundary",
    "campaign_lock_ref",
    "campaign_spend",
    "compile_case_task",
    "episode_directory",
    "episode_is_complete",
    "registry_resolution",
    "seal_campaign_episode",
]
