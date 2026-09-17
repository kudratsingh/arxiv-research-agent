"""The plan artifact: a campaign's design, checked in, at zero spend.

`plan` materializes a campaign under `outputs/`, which `.gitignore`
excludes, and `dry-run` prints to stdout and is gone when the shell
scrolls. Neither leaves anything a reviewer can read in a diff, so the
scope of
[`16-w12-approval-packet-draft.md`](../../docs/agent-engineering/16-w12-approval-packet-draft.md)
— arm A only, 60 episodes over `research-policy-v1` — existed as prose
in a document and nowhere a test could reach. This module is the missing
third output: a **published projection** of a planned campaign, written
to `campaigns/`, re-derived from the registry by
`tests/test_campaign_plan_artifact.py` and compared byte for byte.

Three properties are structural rather than promised.

**The artifact cannot describe a chargeable campaign.** `chargeable` is
`Literal[False]`, `approval_id` is `None`, and every cap in the budgets
is checked to be zero by a validator. Publishing a plan is not
publishing an authorization, and this type could not carry one if a
later caller wanted it to.

**The artifact carries no provider contact.** `provider_initialized` is
`Literal[False]` and `network_calls` is `Literal[0]`, for the same
reason `DryRunPlan` carries them: the claim is part of the record rather
than part of the commit message.

**What moves for reasons the registry does not fix is left out.** An
episode's `episode_key` and `run_id` derive from its TaskSpec ref, and a
`TaskSpec`'s id is a digest over the whole spec *including* its
`compiled_at` timestamp — so those two fields move on every plan of the
identical protocol against the identical registry. A byte-equality test
over an artifact carrying them would fail once a second. They are named
in `volatile_fields_omitted` rather than silently dropped, because "this
artifact does not pin the run ids" is a fact a reader needs and the
campaign directory is where those ids belong. Everything the registry
*does* fix — the campaign id, the protocol and lock digests, the arm
declarations, the case order, the repeats, the seed, the design slots
and their output paths — is here and is compared.

The scope helpers at the bottom (`W12_BASELINE_*`) name the one artifact
this repository publishes today. The model above them is general: any
zero-cost campaign request can be projected, and the CLI's
`dry-run --artifact` does exactly that.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import Field, model_validator

from src.campaign.arms import ARM_IDS, ArmId, ArmSelector, ArmStatus, CampaignArm
from src.campaign.errors import CampaignError
from src.campaign.manifest import CorpusModeChoice
from src.campaign.planner import (
    CampaignPlan,
    CampaignRequest,
    default_campaign_budget,
    default_episode_budget,
    dry_run,
    suite_case_ids,
)
from src.config import Settings
from src.contracts.kernel import (
    Digest,
    ImmutableObjectRef,
    StrictContractModel,
    sha256_digest,
)
from src.contracts.registry import RegistryResolver
from src.contracts.run_manifest import CampaignBudget, CampaignId, EpisodeBudget

#: Where published plan artifacts live. A sibling of `eval_registry/`
#: rather than a member of it: the registry holds the *authorized*
#: benchmark objects that `python -m src.contracts.registry parity`
#: counts, and a campaign plan is a projection over those objects rather
#: than one of them. Adding it under `eval_registry/` would either move
#: the parity census or need an exception carved into it, and both are
#: worse than a directory with a README.
ARTIFACT_ROOT: Final[str] = "campaigns"

#: The one artifact this repository publishes today: 16 §1's scope.
W12_BASELINE_ARTIFACT_PATH: Final[str] = f"{ARTIFACT_ROOT}/w12-arm-a-baseline.plan.json"

#: 16 §1's table as arguments. Arm A only and three repeats over the
#: whole development suite, which is 60 episodes; the caps are zero,
#: which is what makes the artifact publishable at all.
W12_BASELINE_SUITE: Final[str] = "research-policy-v1"
W12_BASELINE_ARMS: Final[tuple[ArmId, ...]] = ("A",)
W12_BASELINE_REPEATS: Final[int] = 3
W12_BASELINE_SEED: Final[int] = 0
W12_BASELINE_CORPUS_MODE: Final[CorpusModeChoice] = "snapshot"
W12_BASELINE_STAGE: Final[str] = "stage-0-qualification"
W12_BASELINE_PROTOCOL_ID: Final[str] = "research-policy-v1-stage-0"

#: The sentence prepended when the scope being published is the one 16
#: §1 describes, so a reader who opens the JSON alone learns which
#: document it belongs to without the README.
W12_BASELINE_PREFACE: Final[str] = (
    "The funded arm-A baseline of "
    "docs/agent-engineering/16-w12-approval-packet-draft.md §1 (P0-WO12)."
)


class ArtifactArm(StrictContractModel):
    """One arm as the artifact publishes it.

    The `declaration_digest` is `CampaignArm`'s own, recomputed here
    rather than restated, so an arm whose settings row changes moves this
    file and fails the byte-equality test instead of drifting quietly.
    """

    arm_id: ArmId
    selector: ArmSelector
    status: ArmStatus
    runnable: bool
    declaration_digest: Digest
    settings_overrides: Mapping[str, bool | str]


class ArtifactSlot(StrictContractModel):
    """One slot of the design matrix, without its volatile identities."""

    design_index: Annotated[int, Field(ge=0)]
    case_id: str
    arm_id: ArmId
    repeat_index: Annotated[int, Field(ge=0)]
    order_in_block: Annotated[int, Field(ge=0)]
    output_path: str
    status: Literal["planned", "excluded"]
    exclusion_reason: str | None = None


class CampaignPlanArtifact(StrictContractModel):
    """A planned zero-cost campaign, in a form a commit can hold.

    Attributes:
        describes: What the campaign is for, in one sentence.
        produced_by: The exact command that writes this file. Derived
            from the request rather than from `sys.argv`, so a copy of
            the line reproduces the artifact and not the operator's
            shell history.
        derived_from: The registry root the plan resolved against.
        volatile_fields_omitted: Fields a plan carries that this artifact
            deliberately does not, and why they move.
    """

    schema_kind: Literal["campaign-plan-artifact"] = "campaign-plan-artifact"
    schema_version: Literal["1.0.0"] = "1.0.0"
    describes: str
    produced_by: str
    derived_from: str
    campaign_id: CampaignId
    protocol_id: str
    stage: str
    suite_ref: ImmutableObjectRef
    protocol_digest: Digest
    lock_digest: Digest
    arms: tuple[ArtifactArm, ...]
    arm_declaration_digest: Digest
    case_ids: tuple[str, ...]
    repeats: Annotated[int, Field(ge=1)]
    seed: Annotated[int, Field(ge=0)]
    corpus_mode: CorpusModeChoice
    expected_episode_count: Annotated[int, Field(ge=1)]
    planned_episode_count: Annotated[int, Field(ge=0)]
    excluded_episode_count: Annotated[int, Field(ge=0)]
    chargeable: Literal[False] = False
    approval_id: None = None
    episode_budget: EpisodeBudget
    campaign_budget: CampaignBudget
    provider_initialized: Literal[False] = False
    network_calls: Literal[0] = 0
    volatile_fields_omitted: tuple[str, ...]
    design: tuple[ArtifactSlot, ...]

    @model_validator(mode="after")
    def every_cap_is_zero(self) -> CampaignPlanArtifact:
        """A published plan declares no spend, in every cap it carries.

        `chargeable: Literal[False]` already refuses the protocol-level
        claim. This refuses the arithmetic behind it: a plan whose
        campaign or episode caps are positive is a plan that would need
        an approval record, and an approval record is not a thing this
        repository publishes.
        """
        caps = {
            "campaign total": self.campaign_budget.total_cost_usd_max,
            "episode total": self.episode_budget.total_cost_usd_max,
            "episode workflow": self.episode_budget.workflow_cost_usd_max,
            "episode judge": self.episode_budget.judge_cost_usd_max,
        }
        positive = sorted(name for name, cap in caps.items() if Decimal(cap) > 0)
        if positive:
            raise ValueError(
                "a published plan artifact declares no spend; these caps are "
                f"positive: {', '.join(positive)}"
            )
        return self

    @model_validator(mode="after")
    def the_design_is_the_whole_matrix(self) -> CampaignPlanArtifact:
        if len(self.design) != self.expected_episode_count:
            raise ValueError("the artifact must publish every planned slot")
        return self


#: The two fields a plan derives from a TaskSpec id, which is a digest
#: over a spec that carries its own `compiled_at`. They move on every
#: plan of the identical protocol and cannot be published.
VOLATILE_FIELDS: Final[tuple[str, ...]] = (
    "episode_key: derived from the episode's TaskSpec ref, whose id digests "
    "the spec's own compiled_at timestamp",
    "run_id: derived from episode_key, and therefore equally volatile",
)


def baseline_request(
    config: Settings,
    *,
    registry_root: Path,
    suite: str = W12_BASELINE_SUITE,
    arms: tuple[ArmId, ...] = W12_BASELINE_ARMS,
    repeats: int = W12_BASELINE_REPEATS,
    seed: int = W12_BASELINE_SEED,
    corpus_mode: CorpusModeChoice = W12_BASELINE_CORPUS_MODE,
) -> CampaignRequest:
    """The request 16 §1's table describes, resolved against the registry.

    Every cap is zero and no approval id is named, which is what
    `plan_campaign` needs to seal without one.

    Args:
        config: The campaign's base settings.
        registry_root: The registry tree to resolve the suite from.
        suite: Benchmark suite id.
        arms: Declared arms, re-ordered into `ARM_IDS` order so two
            callers naming the same set derive the same protocol digest.
        repeats: Repeats per condition.
        seed: Interleaving seed.
        corpus_mode: Aggregation boundary.

    Returns:
        The request.

    Raises:
        CampaignError: The suite or its task set does not resolve, or an
            arm id is not one of the five.
    """
    from src.contracts.benchmark_adapters import suite_ref

    unknown = [arm for arm in arms if arm not in ARM_IDS]
    if unknown:
        raise CampaignError(f"unknown arms: {', '.join(unknown)}")
    ordered: tuple[ArmId, ...] = tuple(arm for arm in ARM_IDS if arm in arms)
    return CampaignRequest(
        protocol_id=W12_BASELINE_PROTOCOL_ID,
        stage=W12_BASELINE_STAGE,
        suite_ref=suite_ref(registry_root, suite),
        case_ids=suite_case_ids(registry_root, suite),
        arms=ordered,
        repeats=repeats,
        corpus_mode=corpus_mode,
        seed=seed,
        approval_id=None,
        episode_budget=default_episode_budget(config, ordered),
        campaign_budget=default_campaign_budget(),
    )


def repo_relative(path: Path) -> str:
    """A path as the repository names it, when it is inside the repository.

    The artifact records where it was derived from, and that record has
    to be the same string whether the caller typed `eval_registry` or an
    absolute path — otherwise the byte-equality test is a test of the
    caller's working directory. A path outside the tree is recorded as
    given, because there is nothing truer to say about it.
    """
    root = Path(__file__).resolve().parents[2]
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def is_w12_baseline(request: CampaignRequest) -> bool:
    """Whether `request` is exactly the scope 16 §1's table describes.

    Compared field by field rather than by campaign id: an id is derived
    from the budgets too, so a checkout whose ceiling settings moved
    would answer "no" to a request that is the same experiment.
    """
    return (
        request.suite_ref.id == W12_BASELINE_SUITE
        and request.arms == W12_BASELINE_ARMS
        and request.repeats == W12_BASELINE_REPEATS
        and request.seed == W12_BASELINE_SEED
        and request.corpus_mode == W12_BASELINE_CORPUS_MODE
        and request.protocol_id == W12_BASELINE_PROTOCOL_ID
        and request.stage == W12_BASELINE_STAGE
    )


def artifact_description(request: CampaignRequest) -> str:
    """What the artifact says it is, derived from the scope it publishes.

    Derived rather than passed in, because a description an operator
    types is a description that can disagree with the file it sits in.
    The only judgement here is the 16 §1 preface, and that is decided by
    comparing the request with the scope rather than by trusting a flag.
    """
    episodes = len(request.case_ids) * request.repeats * len(request.arms)
    body = (
        f"{len(request.case_ids)} cases x {request.repeats} repeats x arm"
        f"{'s' if len(request.arms) > 1 else ''} "
        f"{','.join(request.arms)} = {episodes} episodes over "
        f"{request.suite_ref.id}, planned at a zero cap and published "
        "unapproved. Planning it costs nothing and authorizes nothing."
    )
    if is_w12_baseline(request):
        return f"{W12_BASELINE_PREFACE} {body}"
    return body


def artifact_command(request: CampaignRequest, *, output: str) -> str:
    """The exact command line that writes `output` for `request`.

    Rebuilt from the resolved request rather than echoed from the
    operator's invocation: a recorded `sys.argv` would carry whatever
    else was typed, and the point of the line is that pasting it
    reproduces the file.
    """
    suite = request.suite_ref.id
    return (
        "python -m src.campaign dry-run"
        f" --suite {suite}"
        f" --arms {','.join(request.arms)}"
        f" --repeats {request.repeats}"
        f" --seed {request.seed}"
        f" --corpus-mode {request.corpus_mode}"
        f" --artifact {output}"
    )


def build_plan_artifact(
    plan: CampaignPlan,
    *,
    request: CampaignRequest,
    produced_by: str,
    derived_from: str,
) -> CampaignPlanArtifact:
    """Project an already-built plan into its publishable form.

    Args:
        plan: The plan to publish. Must be zero-cost and unapproved.
        request: The request the plan was built from, which is where the
            artifact's own description is derived.
        produced_by: The command that writes the file.
        derived_from: The registry root the plan resolved against.

    Returns:
        The artifact.

    Raises:
        CampaignError: The plan is chargeable, claims an approval, or
            does not project into a coherent artifact.
    """
    payload = plan.manifest.payload
    protocol = payload.protocol
    if protocol.approval_id is not None:
        raise CampaignError(
            "a published plan artifact cannot claim an approval; "
            f"this plan names {protocol.approval_id}"
        )
    projection = dry_run(plan)
    arms = tuple(
        ArtifactArm(
            arm_id=arm.arm_id,
            selector=arm.selector,
            status=arm.status,
            runnable=arm.runnable,
            declaration_digest=arm.declaration_digest,
            settings_overrides=dict(arm.settings_overrides),
        )
        for arm in payload.arms
    )
    try:
        return CampaignPlanArtifact(
            describes=artifact_description(request),
            produced_by=produced_by,
            derived_from=repo_relative(Path(derived_from)),
            campaign_id=payload.campaign_id,
            protocol_id=protocol.protocol_id,
            stage=protocol.stage,
            suite_ref=protocol.suite_ref,
            protocol_digest=payload.protocol_digest,
            lock_digest=payload.lock_digest,
            arms=arms,
            arm_declaration_digest=arm_declaration_digest(payload.arms),
            case_ids=protocol.case_ids,
            repeats=protocol.repeats,
            seed=protocol.seed,
            corpus_mode=protocol.corpus_mode,
            expected_episode_count=payload.expected_episode_count,
            planned_episode_count=payload.planned_episode_count,
            excluded_episode_count=payload.excluded_episode_count,
            approval_id=None,
            episode_budget=protocol.episode_budget,
            campaign_budget=protocol.campaign_budget,
            volatile_fields_omitted=VOLATILE_FIELDS,
            design=tuple(
                ArtifactSlot(
                    design_index=episode.design_index,
                    case_id=episode.case_id,
                    arm_id=episode.arm_id,
                    repeat_index=episode.repeat_index,
                    order_in_block=episode.order_in_block,
                    output_path=episode.output_path,
                    status=episode.status,
                    exclusion_reason=episode.exclusion_reason,
                )
                for episode in projection.episodes
            ),
        )
    except ValueError as exc:
        raise CampaignError(f"this plan cannot be published: {exc}") from exc


def arm_declaration_digest(arms: tuple[CampaignArm, ...]) -> Digest:
    """One digest over the declared arm set, in declaration order.

    Not a digest of the whole `CampaignArm` objects: `graph_digest` and
    `status` depend on whether a graph was probed, and a plan artifact is
    written by a verb that compiles no graph. This digests exactly what
    `derive_replicate_group_id` groups by, so the artifact's number is
    the one the campaign's identities are actually built on.
    """
    return sha256_digest([arm.declaration_digest for arm in arms])


def render_plan_artifact(artifact: CampaignPlanArtifact) -> str:
    """Serialize an artifact to the exact bytes the repository stores.

    Sorted keys and two-space indent, matching the CLI's own `_emit`, and
    a trailing newline so the file is a well-formed text file rather than
    one git reports as missing its last line. `ensure_ascii=False`
    because the artifact is read in a diff: an escaped `\\u00a7` in a
    section reference is a worse record than the character it stands for,
    and the bytes are just as stable either way.
    """
    body = json.dumps(
        artifact.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False
    )
    return f"{body}\n"


def write_plan_artifact(path: Path, artifact: CampaignPlanArtifact) -> Path:
    """Write the artifact to `path`, creating its directory.

    Overwrites rather than refusing: unlike a sealed campaign manifest,
    this file is *derived*, and regenerating it after a registry change
    is the intended workflow. The byte-equality test is what stops the
    two from disagreeing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_plan_artifact(artifact), encoding="utf-8")
    return path


def build_w12_baseline_artifact(
    config: Settings,
    *,
    registry_root: Path,
    resolver: RegistryResolver | None = None,
    output: str = W12_BASELINE_ARTIFACT_PATH,
) -> CampaignPlanArtifact:
    """Re-derive 16 §1's baseline artifact from the registry.

    The whole of what the byte-equality test calls: nothing is read from
    the checked-in file, so a registry edit that moves a digest moves
    this object and the test reports the difference.

    Args:
        config: The campaign's base settings.
        registry_root: The registry tree to resolve the suite from.
        resolver: The registry resolver. Defaults to a `LocalRegistry`
            over `registry_root`.
        output: Path the produced command writes to.

    Returns:
        The artifact.

    Raises:
        CampaignError: The suite does not resolve or the plan is not
            publishable.
    """
    from src.campaign.planner import plan_campaign
    from src.contracts.registry import LocalRegistry

    request = baseline_request(config, registry_root=registry_root)
    plan = plan_campaign(
        config,
        request,
        resolver=resolver if resolver is not None else LocalRegistry(registry_root),
    )
    return build_plan_artifact(
        plan,
        request=request,
        produced_by=artifact_command(request, output=output),
        derived_from=str(registry_root),
    )


__all__ = [
    "ARTIFACT_ROOT",
    "VOLATILE_FIELDS",
    "W12_BASELINE_ARMS",
    "W12_BASELINE_ARTIFACT_PATH",
    "W12_BASELINE_CORPUS_MODE",
    "W12_BASELINE_PREFACE",
    "W12_BASELINE_PROTOCOL_ID",
    "W12_BASELINE_REPEATS",
    "W12_BASELINE_SEED",
    "W12_BASELINE_STAGE",
    "W12_BASELINE_SUITE",
    "ArtifactArm",
    "ArtifactSlot",
    "CampaignPlanArtifact",
    "arm_declaration_digest",
    "artifact_command",
    "artifact_description",
    "baseline_request",
    "build_plan_artifact",
    "build_w12_baseline_artifact",
    "is_w12_baseline",
    "render_plan_artifact",
    "repo_relative",
    "write_plan_artifact",
]
