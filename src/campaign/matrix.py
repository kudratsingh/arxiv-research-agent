"""The task x arm x repeat matrix, enumerated once and predeclared.

Three properties matter here and each has a test.

**Every slot is enumerated, including the ones nothing will run.** The
matrix is `cases x repeats x arms` over *all* declared arms, and an arm
that this checkout cannot run contributes excluded slots rather than
absence. That is what makes the denominator honest: 07 §5's full v1
design is 20 x 3 x 5 = 300 episodes, and a campaign that quietly planned
240 because arm E is unimplemented would be reporting a different
experiment than the one it declared.

**Arm order inside a block is interleaved and predeclared.** 07 §6 Stage 3
asks for interleaving so that model-service or source drift over an
evening cannot align with one arm. The permutation is drawn from a
`random.Random` seeded by the campaign seed, the case id and the repeat
index, so it is fixed before the campaign starts, reproducible from the
manifest, and different in different blocks — no arm is systematically
first.

**Identity is derived, never assigned.** `replicate_group_id` groups the
repeats of one (case, arm) condition and deliberately excludes the repeat
index; `episode_key` adds it back; `run_id` is a function of the episode
key and the rerun generation. So a repeat is a new run in the same group,
a resume reuses a run id it can recompute without reading a file, and a
rerun lands on a different run id and a different directory.

Blocks are ordered repeat-major — every case's first repeat before any
case's second — matching `src/eval/runner.py`'s own choice, for its
reason: a campaign truncated by a budget stop is worth far more when it
covered the whole benchmark once than when it ran three repeats of the
first third.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, StringConstraints, model_validator

from src.campaign.arms import ArmId, CampaignArm
from src.campaign.errors import CampaignError
from src.contracts.kernel import (
    Digest,
    ImmutableObjectRef,
    StrictContractModel,
    sha256_digest,
)
from src.contracts.run_manifest import (
    CampaignId,
    RunId,
    derive_episode_key,
    derive_replicate_group_id,
)
from src.contracts.task_spec import TaskSpecRef

#: Why a declared slot is not planned. One value today — the arm has no
#: implementation — but typed as an enum-shaped literal so a later
#: exclusion (a retired case, an operator's predeclared drop) is an added
#: member rather than a free-text field nobody can count.
ExclusionReason: TypeAlias = Literal["arm_capability_missing"]


class PlannedEpisode(StrictContractModel):
    """One slot of the design matrix, with its identity already derived.

    Attributes:
        design_index: Position in the campaign's predeclared order over
            the full matrix, including excluded slots.
        block_index: Which (repeat, case) block, in execution order.
        order_in_block: Interleaved position of this arm within its
            block. Positions are over all declared arms, so the design
            order does not shift when an arm becomes runnable.
        case_id: The registry case.
        case_ref: That case pinned by revision and digest.
        arm_id: The arm.
        repeat_index: Zero-based, as `RunIdentity` requires.
        task_ref: The one TaskSpec compiled for this case, shared by
            every arm and repeat of it.
        replicate_group_id: All repeats of this (case, arm) condition.
        episode_key: This slot, uniquely within the campaign.
        run_id: The logical execution of this slot.
        rerun_index: Zero for the first run of the slot; a rerun after a
            terminal outcome takes the next integer, a new run id and a
            new directory.
        output_path: Episode directory, relative to the campaign root.
        runnable: Whether an episode will be attempted.
        exclusion_reason: Why not, when `runnable` is false.
    """

    design_index: Annotated[int, Field(ge=0)]
    block_index: Annotated[int, Field(ge=0)]
    order_in_block: Annotated[int, Field(ge=0)]
    case_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")]
    case_ref: ImmutableObjectRef
    arm_id: ArmId
    repeat_index: Annotated[int, Field(ge=0)]
    task_ref: TaskSpecRef
    replicate_group_id: Digest
    episode_key: Digest
    run_id: RunId
    rerun_index: Annotated[int, Field(ge=0)] = 0
    output_path: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    runnable: bool
    exclusion_reason: ExclusionReason | None = None

    @model_validator(mode="after")
    def exclusion_is_explained(self) -> PlannedEpisode:
        if self.runnable and self.exclusion_reason is not None:
            raise ValueError("a runnable episode cannot carry an exclusion reason")
        if not self.runnable and self.exclusion_reason is None:
            raise ValueError("an excluded episode must name its reason")
        if self.case_ref.kind != "task_case":
            raise ValueError("case_ref must reference a task case")
        return self


def derive_run_id(episode_key: Digest, *, rerun_index: int = 0) -> str:
    """Derive the run id for one episode slot and rerun generation.

    Derived rather than random so a resume can recompute the id it is
    resuming without trusting a filename, and so a rerun *cannot*
    accidentally reuse it. Both halves matter: RFC 09 §4 says a resume
    keeps the run id and a rerun takes a new one, and a random id makes
    the first hard and the second an accident waiting to happen.

    Args:
        episode_key: The slot's episode key.
        rerun_index: Zero for the original run.

    Returns:
        A `run_` id, 32 hex characters of SHA-256.

    Raises:
        CampaignError: `rerun_index` is negative.
    """
    if rerun_index < 0:
        raise CampaignError("rerun index must be non-negative")
    material = {"episode_key": episode_key, "rerun_index": rerun_index}
    return "run_" + sha256_digest(material).removeprefix("sha256:")[:32]


def episode_output_path(
    case_id: str, repeat_index: int, arm_id: ArmId, *, rerun_index: int = 0
) -> str:
    """The episode's directory, relative to the campaign root.

    RFC 09 §5.3's layout, with two deliberate details. The repeat is
    one-based and zero-padded so a directory listing sorts the way a
    human reads it, and a rerun gets its own suffixed directory because
    a rerun "does not overwrite the old output" — the layout has to make
    that structurally true, not merely intended.
    """
    leaf = f"arm-{arm_id}" if rerun_index == 0 else f"arm-{arm_id}__rerun-{rerun_index}"
    return f"episodes/{case_id}/repeat-{repeat_index + 1:02d}/{leaf}"


def block_arm_order(
    arms: tuple[ArmId, ...], *, seed: int, case_id: str, repeat_index: int
) -> tuple[ArmId, ...]:
    """The interleaved arm order for one (case, repeat) block.

    Seeded per block rather than once per campaign so the order depends
    only on the campaign seed and the block's own coordinates: a campaign
    replanned with a different case selection keeps the ordering of the
    blocks it still contains, and a reader can recompute any single
    block's order without replaying the whole matrix.

    Args:
        arms: Every declared arm, in declaration order.
        seed: The campaign's recorded root seed.
        case_id: The block's case.
        repeat_index: The block's zero-based repeat.

    Returns:
        The arms, permuted.
    """
    material = sha256_digest(
        {"seed": seed, "case_id": case_id, "repeat_index": repeat_index}
    )
    generator = random.Random(int(material.removeprefix("sha256:"), 16))
    ordered = list(arms)
    generator.shuffle(ordered)
    return tuple(ordered)


def compile_matrix(
    *,
    campaign_id: CampaignId,
    arms: tuple[CampaignArm, ...],
    case_refs: tuple[ImmutableObjectRef, ...],
    task_refs: Mapping[str, TaskSpecRef],
    repeats: int,
    seed: int,
) -> tuple[PlannedEpisode, ...]:
    """Enumerate the whole design matrix, in predeclared execution order.

    Args:
        campaign_id: The campaign these episodes belong to.
        arms: Every declared arm, runnable or not.
        case_refs: The locked, ordered case selection.
        task_refs: One TaskSpec ref per case id, compiled once at
            selection and reused across arms and repeats.
        repeats: Independent samples per (case, arm) condition.
        seed: The campaign's root seed, recorded in the manifest.

    Returns:
        Every slot of `cases x repeats x arms`, ordered repeat-major over
        blocks and interleaved within each block.

    Raises:
        CampaignError: A selected case has no compiled TaskSpec, or the
            inputs are empty.
    """
    if repeats < 1:
        raise CampaignError("repeats must be positive")
    if not arms or not case_refs:
        raise CampaignError("a matrix needs at least one arm and one case")
    missing = [ref.id for ref in case_refs if ref.id not in task_refs]
    if missing:
        raise CampaignError(f"cases without a compiled TaskSpec: {', '.join(missing)}")
    by_id = {arm.arm_id: arm for arm in arms}
    declared = tuple(arm.arm_id for arm in arms)

    episodes: list[PlannedEpisode] = []
    design_index = 0
    block_index = 0
    for repeat_index in range(repeats):
        for case_ref in case_refs:
            task_ref = task_refs[case_ref.id]
            order = block_arm_order(
                declared, seed=seed, case_id=case_ref.id, repeat_index=repeat_index
            )
            for order_in_block, arm_id in enumerate(order):
                arm = by_id[arm_id]
                group_id = derive_replicate_group_id(
                    campaign_id, task_ref, arm.declaration_digest
                )
                episode_key = derive_episode_key(group_id, repeat_index)
                episodes.append(
                    PlannedEpisode(
                        design_index=design_index,
                        block_index=block_index,
                        order_in_block=order_in_block,
                        case_id=case_ref.id,
                        case_ref=case_ref,
                        arm_id=arm_id,
                        repeat_index=repeat_index,
                        task_ref=task_ref,
                        replicate_group_id=group_id,
                        episode_key=episode_key,
                        run_id=derive_run_id(episode_key),
                        output_path=episode_output_path(
                            case_ref.id, repeat_index, arm_id
                        ),
                        runnable=arm.runnable,
                        exclusion_reason=(
                            None if arm.runnable else "arm_capability_missing"
                        ),
                    )
                )
                design_index += 1
            block_index += 1
    _assert_unique_keys(episodes)
    return tuple(episodes)


def rerun_of(episode: PlannedEpisode) -> PlannedEpisode:
    """The next rerun generation of one slot: new run id, new directory.

    The episode key and the replicate group are unchanged — a rerun is
    still the same slot of the same condition — and only the run identity
    and the output path move, which is what stops a rerun from
    overwriting the outcome it is rerunning.
    """
    if not episode.runnable:
        raise CampaignError("an excluded slot has nothing to rerun")
    rerun_index = episode.rerun_index + 1
    return episode.model_copy(
        update={
            "rerun_index": rerun_index,
            "run_id": derive_run_id(episode.episode_key, rerun_index=rerun_index),
            "output_path": episode_output_path(
                episode.case_id,
                episode.repeat_index,
                episode.arm_id,
                rerun_index=rerun_index,
            ),
        }
    )


def _assert_unique_keys(episodes: list[PlannedEpisode]) -> None:
    """Every slot is unique within the campaign, as RFC 09 §4 requires.

    Output paths are not checked separately: a path is a function of
    (case, repeat, arm), the same triple the enumeration walks exactly
    once, so two colliding paths would already be two colliding keys.
    """
    keys = [episode.episode_key for episode in episodes]
    if len(set(keys)) != len(keys):
        raise CampaignError(
            "episode keys collided: two slots resolved to the same task, arm "
            "and repeat"
        )


__all__ = [
    "ExclusionReason",
    "PlannedEpisode",
    "block_arm_order",
    "compile_matrix",
    "derive_run_id",
    "episode_output_path",
    "rerun_of",
]
