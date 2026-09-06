"""The five conceptual policy arms, mapped onto settings this code has.

[`07-first-policy-experiment.md`](../../docs/agent-engineering/07-first-policy-experiment.md)
§4 names five arms by *conceptual selector* and says explicitly not to add
them as ad hoc boolean combinations. This module is the mapping from those
five names to the real `Settings` fields, and it holds three rules that the
rest of the package depends on:

- **Common values are frozen once.** `COMMON_FROZEN_SETTINGS` is applied to
  every arm, so the held-out factors (query refiner, reader recovery), the
  safety floor (prompt isolation) and the confounders (semantic scholar,
  prompt caching, HITL) cannot differ between two arms of one campaign.
  A difference that is not in `ARM_SETTINGS` is not an arm difference.
- **An arm is a claim until a compiled graph earns it.** `declare_arm`
  classifies an arm's settings against a `GraphShape` using W05's
  structural classifier, so `ENABLE_VERIFIER=true` on the fixed pipeline
  is still arm A and a `research_policy` that merely *names*
  verify-and-repair without the compiled stage is `capability_missing`.
- **E is earned, not refused.** It used to be refused outright, because
  nothing in this repository routed a compute tier, branched a candidate
  or decided a marginal stop. CAP-04, CAP-03 and CAP-09 built those in
  that order, so `UNRUNNABLE_ARMS` is now empty and arm E goes through
  the same probe as every other arm — a structural answer about this
  checkout rather than a standing refusal (ADR 0091). What makes the
  answer honest is that E's row turns on four settings a deployment must
  actually hold: the controller, the branch tier, the listwise selector
  and the marginal-stop rule.

The arm *declaration* — not the compiled policy snapshot — is what
identifies a replicate group, because a group has to be nameable before a
graph is compiled. The compiled graph is then checked against the
declaration at seal time (`src/campaign/episode.py`), which is the
stronger of the two orderings: a plan cannot claim a capability, and a
seal cannot proceed without one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal, TypeAlias

from pydantic import model_validator

from src.campaign.errors import CampaignError
from src.config import Settings
from src.contracts.kernel import Digest, StrictContractModel, sha256_digest
from src.contracts.research_binding import (
    ARM_REQUIRED_CAPABILITIES,
    GraphShape,
    PolicyShape,
    arm_capability_gap,
    classify_from_graph_shape,
)

ArmId: TypeAlias = Literal["A", "B", "C", "D", "E"]
ArmSelector: TypeAlias = Literal[
    "fixed",
    "fixed_evidence",
    "fixed_verify_repair",
    "supervisor_verified",
    "adaptive_verified",
]

#: Every arm, in the order 07 §4 declares them.
ARM_IDS: Final[tuple[ArmId, ...]] = ("A", "B", "C", "D", "E")

#: Conceptual selector per arm. The manifest's `PolicySnapshot` enforces
#: the same pairing, so a snapshot cannot disagree with this table.
ARM_SELECTORS: Final[Mapping[ArmId, ArmSelector]] = {
    "A": "fixed",
    "B": "fixed_evidence",
    "C": "fixed_verify_repair",
    "D": "supervisor_verified",
    "E": "adaptive_verified",
}

#: 07 §4's "common" column: identical in every arm of every campaign this
#: package plans. Two arms that differ here are not two arms of one
#: experiment, so these are applied *after* the per-arm overrides and a
#: caller cannot override them per arm.
COMMON_FROZEN_SETTINGS: Final[Mapping[str, bool]] = {
    "enable_query_refiner": False,
    "enable_reader_recovery": False,
    "enable_prompt_isolation": True,
    "enable_semantic_scholar": False,
    "enable_prompt_caching": False,
    "enable_hitl": False,
}

#: The settings that *make* each arm. Arm C needs CAP-02's selector; A,
#: B and D are the three flags 07 §4 already described.
#:
#: Arm E's row is the one that changed with CAP-09 (ADR 0091). It used
#: to be a copy of D's — a placeholder documenting that the closest
#: expressible configuration was still not arm E — and it is now the
#: real thing: the deterministic compute controller (ADR 0085) with the
#: branch tier available to it as T2 (ADR 0086), the listwise selector
#: and the marginal-stop rule (ADR 0091), over the evidence store.
#:
#: Two entries are worth stating because a reader will expect their
#: opposites. `research_policy` is **legacy**, not
#: `orchestrated_workers`: ADR 0085 refuses a controller beside a policy
#: that fixes the shape for the whole process, because two claimants for
#: the graph is one too many, and arm E's identity is the *router*.
#: `enable_supervisor` is **false**: ADR 0089 removed the supervisor
#: from arm E's definition, since the only implementation of adaptive
#: compute this repository has refuses to load beside one.
ARM_SETTINGS: Final[Mapping[ArmId, Mapping[str, bool | str]]] = {
    "A": {
        "enable_supervisor": False,
        "enable_evidence_store": False,
        "enable_verifier": False,
        "research_policy": "legacy",
    },
    "B": {
        "enable_supervisor": False,
        "enable_evidence_store": True,
        "enable_verifier": False,
        "research_policy": "legacy",
    },
    "C": {
        "enable_supervisor": False,
        "enable_evidence_store": True,
        "enable_verifier": False,
        "research_policy": "fixed_verify_repair",
    },
    "D": {
        "enable_supervisor": True,
        "enable_evidence_store": True,
        "enable_verifier": True,
        "research_policy": "legacy",
    },
    "E": {
        "enable_supervisor": False,
        "enable_evidence_store": True,
        "enable_verifier": False,
        "research_policy": "legacy",
        "compute_controller": "deterministic",
        "orchestration": "on",
        "candidate_selection": "listwise",
        "marginal_stop": "on",
    },
}

#: Arms no configuration of this repository can run, whatever a graph
#: looks like. Membership is a *structural* claim about missing
#: implementation, and it is now **empty**: CAP-09 built the last two of
#: arm E's four capabilities (ADR 0091), so every arm 07 §4 names has an
#: implementation and every refusal comes from a probed graph rather
#: than from this constant.
#:
#: Kept rather than deleted, and deliberately. It is the mechanism by
#: which a *future* arm can be declared before it is built — the campaign
#: denominator needs to account for such an arm's episodes as
#: excluded-with-reason rather than have them vanish — and deleting the
#: mechanism the moment its first member left would mean rebuilding it
#: for the next one.
UNRUNNABLE_ARMS: Final[frozenset[str]] = frozenset()

ArmStatus: TypeAlias = Literal["available", "unverified", "capability_missing"]


class CampaignArm(StrictContractModel):
    """One arm as the campaign manifest records it.

    Attributes:
        arm_id: `A`–`E`.
        selector: The conceptual selector from 07 §4.
        settings_overrides: Exactly the settings that make this arm,
            including the frozen common values, so a reader of the
            manifest can reproduce the environment without this module.
        status: `available` when a compiled graph earned the arm,
            `capability_missing` when it cannot, and `unverified` when no
            graph was probed at plan time — the honest third answer,
            because the planner runs in a process whose settings are not
            the arm's and cannot compile five graphs to find out.
        missing_capabilities: What `available` would need and this
            checkout lacks. Empty exactly when status is not
            `capability_missing`.
        graph_digest: The probed graph's digest, or `None` when
            unverified. Present digests are evidence; absence is not a
            claim.
        runnable: Whether the matrix compiler plans episodes for this
            arm. False for `capability_missing`, and those episodes enter
            the ledger as excluded-with-reason rather than vanishing.
    """

    arm_id: ArmId
    selector: ArmSelector
    settings_overrides: Mapping[str, bool | str]
    status: ArmStatus
    missing_capabilities: tuple[str, ...] = ()
    graph_digest: Digest | None = None
    runnable: bool

    @model_validator(mode="after")
    def status_and_runnability_agree(self) -> CampaignArm:
        if self.selector != ARM_SELECTORS[self.arm_id]:
            raise ValueError("arm id and selector do not match")
        if self.status == "capability_missing":
            if not self.missing_capabilities:
                raise ValueError("a capability_missing arm must name what is missing")
            if self.runnable:
                raise ValueError("a capability_missing arm cannot be runnable")
        else:
            if self.missing_capabilities:
                raise ValueError("only a capability_missing arm carries a gap")
            if not self.runnable:
                raise ValueError("an available or unverified arm is runnable")
        if self.arm_id in UNRUNNABLE_ARMS and self.runnable:
            raise ValueError(f"arm {self.arm_id} has no implementation in this repository")
        if self.status == "available" and self.graph_digest is None:
            raise ValueError("an available arm must cite the graph that earned it")
        return self

    @property
    def declaration_digest(self) -> Digest:
        """Identity of the *condition*, independent of any compiled graph.

        This is what `derive_replicate_group_id` groups repeats by. It has
        to be knowable before a graph exists — the plan is written first —
        and it has to be stable across checkouts whose graph digest moves
        for reasons unrelated to the arm. The compiled graph is checked
        against the declaration at seal time instead, which is where the
        evidence actually is.
        """
        return sha256_digest(
            {
                "arm_id": self.arm_id,
                "selector": self.selector,
                "settings_overrides": dict(self.settings_overrides),
            }
        )


def arm_settings(config: Settings, arm_id: ArmId) -> Settings:
    """The settings one arm runs under, validated rather than assumed.

    Re-validated through `Settings.model_validate` rather than copied
    with `model_copy`, because the copy path skips every model validator
    — including CAP-02's, which is the one thing standing between "arm C"
    and a supervisor run that calls itself arm C. A combination this
    repository refuses to boot must also be a combination this package
    refuses to plan.

    Args:
        config: The campaign's base settings.
        arm_id: The arm to project.

    Returns:
        A fresh `Settings` carrying the arm's overrides and the frozen
        common values.

    Raises:
        CampaignError: The arm's combination is one `Settings` refuses.
    """
    values: dict[str, object] = dict(config.model_dump())
    values.update(ARM_SETTINGS[arm_id])
    values.update(COMMON_FROZEN_SETTINGS)
    try:
        return Settings.model_validate(values)
    except ValueError as exc:
        raise CampaignError(f"arm {arm_id} settings are not loadable: {exc}") from exc


def ceiling_settings(config: Settings, arms: tuple[ArmId, ...]) -> Settings:
    """The most permissive configuration any arm in the set will run under.

    One `TaskSpec` is compiled per selected case and reused by every arm
    and repeat (work-order invariant 2), so that spec has to express the
    *maximum* permissions the campaign will use — the supervisor's loop
    bound if any arm has the supervisor, the evidence store's second
    reader question if any arm has the store. Each arm's own effective
    policy is then narrower or equal, which is exactly what the admission
    controller proves before an episode seals.

    Args:
        config: The campaign's base settings.
        arms: Every declared arm, runnable or not.

    Returns:
        The ceiling settings the campaign's TaskSpecs compile under.
    """
    values: dict[str, object] = dict(config.model_dump())
    values.update(
        {
            "enable_supervisor": any(ARM_SETTINGS[arm]["enable_supervisor"] for arm in arms),
            "enable_evidence_store": any(
                ARM_SETTINGS[arm]["enable_evidence_store"] for arm in arms
            ),
            "enable_verifier": any(ARM_SETTINGS[arm]["enable_verifier"] for arm in arms),
            # The ceiling is a permission envelope, not a runnable arm, so
            # it takes the legacy graph selector: `fixed_verify_repair`
            # would refuse the supervisor flag the envelope needs.
            "research_policy": "legacy",
        }
    )
    values.update(COMMON_FROZEN_SETTINGS)
    try:
        return Settings.model_validate(values)
    except ValueError as exc:
        raise CampaignError(f"campaign ceiling settings are not loadable: {exc}") from exc


def declare_arm(arm_id: ArmId, *, graph: GraphShape | None = None) -> CampaignArm:
    """Declare one arm, with a probed graph's verdict when one is available.

    Args:
        arm_id: The arm to declare.
        graph: The compiled graph shape to classify against, or `None` to
            declare the arm `unverified`.

    Returns:
        The arm as the campaign manifest will record it.
    """
    overrides: dict[str, bool | str] = {
        **ARM_SETTINGS[arm_id],
        **COMMON_FROZEN_SETTINGS,
    }
    selector = ARM_SELECTORS[arm_id]
    if arm_id in UNRUNNABLE_ARMS:
        # Read from the capability table rather than the graph: arm E's
        # gap is never empty, and probing a graph to discover that would
        # imply some graph could close it.
        return CampaignArm(
            arm_id=arm_id,
            selector=selector,
            settings_overrides=overrides,
            status="capability_missing",
            missing_capabilities=ARM_REQUIRED_CAPABILITIES[arm_id],
            graph_digest=graph.digest if graph is not None else None,
            runnable=False,
        )
    if graph is None:
        return CampaignArm(
            arm_id=arm_id,
            selector=selector,
            settings_overrides=overrides,
            status="unverified",
            graph_digest=None,
            runnable=True,
        )
    gap = _capability_gap(arm_id, graph, overrides)
    if gap:
        return CampaignArm(
            arm_id=arm_id,
            selector=selector,
            settings_overrides=overrides,
            status="capability_missing",
            missing_capabilities=gap,
            graph_digest=graph.digest,
            runnable=False,
        )
    return CampaignArm(
        arm_id=arm_id,
        selector=selector,
        settings_overrides=overrides,
        status="available",
        graph_digest=graph.digest,
        runnable=True,
    )


def classify_arm(config: Settings, arm_id: ArmId, graph: GraphShape) -> PolicyShape:
    """Classify a compiled graph under one arm's settings.

    The seal-time check: a graph that classifies as something other than
    `arm_id` cannot produce this arm's manifest, however the settings are
    labelled.

    Args:
        config: The campaign's base settings.
        arm_id: The arm the caller believes it is running.
        graph: The compiled graph's structure.

    Returns:
        W05's structural classification.

    Raises:
        CampaignError: The graph does not run this arm.
    """
    shape = classify_from_graph_shape(arm_settings(config, arm_id), graph)
    if arm_id in UNRUNNABLE_ARMS:
        raise CampaignError(
            f"arm {arm_id} is capability_missing: "
            f"{', '.join(ARM_REQUIRED_CAPABILITIES[arm_id])}"
        )
    if shape.arm_id != arm_id:
        missing = shape.missing_capabilities or arm_capability_gap(arm_id, shape)
        raise CampaignError(
            f"compiled graph runs arm {shape.arm_id or 'capability_missing'}, "
            f"not the declared arm {arm_id}: missing {', '.join(missing) or 'none'}"
        )
    return shape


def _capability_gap(
    arm_id: ArmId, graph: GraphShape, overrides: Mapping[str, bool | str]
) -> tuple[str, ...]:
    """What `arm_id` needs and this graph does not earn.

    The three non-node capabilities are read out of the arm's own
    overrides rather than out of the process settings, for the reason
    the whole module exists: the planner runs under settings that are
    nobody's arm, and asking the live configuration whether *this* arm
    has a compute router would answer about a different run.
    """
    from src.contracts.research_binding import graph_capabilities

    earned = set(
        graph_capabilities(
            graph,
            evidence=bool(overrides["enable_evidence_store"]),
            compute_controller=str(overrides.get("compute_controller", "off")),
            candidate_selection=str(overrides.get("candidate_selection", "off")),
            marginal_stop=str(overrides.get("marginal_stop", "off")),
        )
    )
    required = _REQUIRED_CAPABILITIES[arm_id]
    return tuple(capability for capability in required if capability not in earned)


#: What each runnable arm's graph must earn, in the vocabulary
#: `graph_capabilities` mints. A, B and D are structural facts about the
#: fixed pipeline and the supervisor loop; C's three and E's four come
#: from W05's own table, so the two modules cannot disagree about what
#: those arms are. E carries `evidence_store` for arm C's reason arrived
#: at from the other side: a branch tier whose reader emits no claims
#: merges empty tables (ADR 0089).
_REQUIRED_CAPABILITIES: Final[Mapping[ArmId, tuple[str, ...]]] = {
    "A": ("fixed_pipeline",),
    "B": ("fixed_pipeline", "evidence_store"),
    "C": ("fixed_pipeline", "evidence_store", *ARM_REQUIRED_CAPABILITIES["C"]),
    "D": ("supervisor_router", "supervisor_verifier", "evidence_store"),
    "E": ("evidence_store", *ARM_REQUIRED_CAPABILITIES["E"]),
}


__all__ = [
    "ARM_IDS",
    "ARM_SELECTORS",
    "ARM_SETTINGS",
    "COMMON_FROZEN_SETTINGS",
    "UNRUNNABLE_ARMS",
    "ArmId",
    "ArmSelector",
    "ArmStatus",
    "CampaignArm",
    "arm_settings",
    "ceiling_settings",
    "classify_arm",
    "declare_arm",
]
