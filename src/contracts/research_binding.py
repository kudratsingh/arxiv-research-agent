"""Bind the P0 contracts to the current research runtime, in shadow only.

`kernel`, `task_spec`, `registry`, `run_manifest` and `trajectory` are
deliberately runtime-free: they import no settings, no provider, no agent
and no graph, and P0-WO00..W04 kept them that way so a trust-boundary
model can be reasoned about without booting the product. That property is
worth keeping, and it is also why *something* has to know both halves.

This module is that something, and it is the only place in the package
that reads `Settings` or a compiled LangGraph app. It answers four
questions and nothing else:

1. **What task is this run being asked to do?** `compile_research_intake`
   and `compile_eval_case` call W01's deterministic compilers with a
   policy bundle derived from the live settings. No model is consulted,
   the query is never rewritten, and compilation has no side effect.
2. **What shape is the policy actually running?** `classify_policy_shape`
   reads the *compiled graph* — its node set and its conditional edges —
   rather than believing a flag. That is the whole point: under the fixed
   pipeline `ENABLE_VERIFIER=true` adds no `verifier` node, so the run is
   arm A and the arm-C claim is structurally unavailable rather than
   merely discouraged.
3. **What configuration was frozen before the first node ran?**
   `seal_research_episode` builds a `RunManifestPayload` out of the
   settings snapshot, the prompt digests, the model routes, the tool
   registry, the code revision and the environment, resolves admission,
   and seals it. It seals or it fails; there is no degraded manifest.
4. **Do the contract projections agree with the legacy record?**
   `compare_outcomes` and `compare_research_state` are pure functions
   over two typed views, so the parity check can be run — and tested —
   without a runtime at all.

Three rules this module keeps, because breaking any of them turns a
measurement aid into a liability:

- **It never authorizes spend.** The compiled task always carries
  `chargeable_work="forbidden"` and a zero ceiling, and a metered
  provider therefore fails admission rather than sealing a manifest that
  implies permission. Under `USE_MOCK_DATA` the provider is declared
  `local_mock` and unmetered, which is the only configuration in which a
  shadow episode can seal today. See ADR 0078.
- **It never reads a secret.** `SecretStr`-typed settings are excluded by
  *type*, before any value is touched, and `get_secret_value()` is never
  called anywhere in this package. Deployment locators (URLs, paths,
  origins, CORS lists) are excluded by name, because the manifest's own
  safe-content validator rejects private absolute paths and a settings
  snapshot is exactly where one would arrive.
- **It invents no provenance.** Where P0 has not yet built the object a
  manifest field points at — the benchmark registry (W06) and the
  campaign lock (W07) — the reference says so in its id and takes its
  digest from that statement, rather than borrowing a plausible-looking
  one.
"""

from __future__ import annotations

import hashlib
import inspect
import locale as locale_module
import platform as platform_module
import re
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import Field, SecretStr, StringConstraints

from src.config import Settings
from src.contracts.kernel import (
    ContractError,
    ContractErrorCode,
    DataClass,
    Digest,
    ImmutableObjectRef,
    MoneyUsd,
    RetentionPolicyRef,
    StrictContractModel,
    sha256_digest,
)
from src.contracts.run_manifest import (
    AdmissionPlan,
    BudgetSnapshot,
    CampaignBudget,
    CodeSnapshot,
    CompilationSnapshot,
    CredentialBinding,
    DeterminismClass,
    EnvironmentSnapshot,
    EpisodeBudget,
    EvaluationBudget,
    EvaluationSnapshot,
    FakeLocalApprovalBackend,
    InvocationSnapshot,
    LlmProviderSnapshot,
    OutputSnapshot,
    PolicyCapabilities,
    PolicyConfig,
    PolicyProviderProjection,
    PolicyRuntimeProjection,
    PolicyRuntimeProjectionPayload,
    PolicyRuntimeProjectionRef,
    PolicySnapshot,
    PricingSnapshot,
    PrivacySnapshot,
    PromptSnapshot,
    ProviderSnapshot,
    RandomnessSnapshot,
    RegistryResolution,
    RetrySnapshot,
    RunIdentity,
    RunManifestError,
    RunManifestPayload,
    RunManifestV1,
    RuntimeConfigSnapshot,
    RuntimeFlags,
    SamplingSnapshot,
    SourceSnapshot,
    ToolSnapshot,
    build_policy_runtime_projection,
    derive_episode_key,
    derive_replicate_group_id,
    resolve_admission,
    seal_manifest,
    validate_manifest_safe_content,
)
from src.contracts.task_spec import (
    AutonomyPolicy,
    AutonomyTier,
    BenchmarkOrigin,
    CorpusMode,
    ExecutionLimits,
    FreshnessMode,
    FreshnessRequirement,
    PlatformPolicyCeiling,
    ProductSurface,
    ResearchCompilerInput,
    SourceScope,
    TaskCompilationReceipt,
    TaskDataPolicy,
    TaskKind,
    TaskPolicyBundle,
    TaskSpecRef,
    TaskSpecV1,
    ToolPolicy,
    WorkflowCostBoundary,
    build_task_spec_ref,
    compile_benchmark_case,
    compile_research_request,
    persist_compiled_task,
    shadow_research_state_compatibility,
)

#: Version of this binding, recorded as the policy version and folded
#: into every ref this module mints. It is not the contract schema
#: version — those live on the contract objects — it is "which edition
#: of the glue produced this manifest", which is the question a reader
#: of two manifests a month apart actually has.
BINDING_VERSION: Final[str] = "1.0.0"

#: The repository this binding describes. A label, not a locator: the
#: manifest's safe-content rule rejects an absolute path, and a checkout
#: directory is not a fact about the code anyway.
REPOSITORY_LABEL: Final[str] = "arxiv-research-agent"

#: Repository root, three parents up from `src/contracts/research_binding.py`.
#: Used only to *read* source files for subtree digests; no path derived
#: from it ever reaches a contract object.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The campaign a shadow episode belongs to. There is exactly one, it is
#: local, and it locks nothing — campaign locking is P0-WO07. Naming it
#: rather than leaving the field blank keeps the identity derivation
#: (`replicate_group_id`, `episode_key`) meaningful within a checkout.
SHADOW_CAMPAIGN_ID: Final[str] = "camp_shadow-local"

_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_UNKNOWN_COMMIT_SHA: Final[str] = "0" * 40


class ResearchBindingError(ContractError):
    """The live configuration cannot be expressed as a sealed episode.

    Always a refusal, never a repair. Every raiser below names a
    structural fact — an unrepresentable policy shape, a metered provider
    with no approval — and the caller's only correct response is to leave
    the run alone, which is what `src.contracts.shadow_bridge` does.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(ContractErrorCode.SCHEMA_INVALID, detail)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def utc_timestamp(moment: datetime | None = None) -> str:
    """Return an RFC 3339 UTC string in the profile's exact shape."""
    stamp = (moment or datetime.now(UTC)).astimezone(UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "000Z"


def money(value: float | Decimal | str) -> str:
    """Render a USD amount as the profile's six-decimal fixed string."""
    return f"{Decimal(str(value)):.6f}"


def _ref(kind: str, object_id: str, material: Any, *, revision: str = "1.0.0") -> ImmutableObjectRef:
    """Mint a content-addressed immutable reference.

    The digest is always over `material`, never over a name we chose, so
    two checkouts that disagree about a prompt, a tool implementation or
    a settings snapshot mint different refs without anybody remembering
    to bump a version string.
    """
    return ImmutableObjectRef(
        kind=kind,
        id=object_id,
        revision=revision,
        digest=sha256_digest(material),
    )


def _unresolved_ref(kind: str, owner: str) -> ImmutableObjectRef:
    """A typed reference to an object P0 has not built yet.

    Invariant 12 of the work-order package forbids backfilling invented
    provenance, and a manifest section is required whether or not its
    subject exists. So the reference says what it is: an id that reads
    `shadow-unresolved-...`, revision `0.0.0`, and a digest taken over
    that statement rather than over content nobody has.
    """
    return ImmutableObjectRef(
        kind=kind,
        id=f"shadow-unresolved-{kind.replace('_', '-')}",
        revision="0.0.0",
        digest=sha256_digest({"kind": kind, "state": "unresolved", "owner": owner}),
    )


def _cas_locator(digest: str) -> str:
    """The logical content-addressed locator for a digest."""
    return f"cas://sha256/{digest.removeprefix('sha256:')}"


def retention_policy_ref() -> RetentionPolicyRef:
    """The retention policy a shadow episode runs under: none, in memory.

    Named as a policy rather than left implicit because every artifact
    ref and every event inherits it, and "we kept nothing" is a retention
    decision that a reader is entitled to see stated.
    """
    material = {
        "retention": "in-memory-only",
        "persisted": False,
        "training_use": "prohibited",
        "owner": "P0-WO05",
    }
    return RetentionPolicyRef(
        kind="retention_policy",
        id="shadow-in-memory",
        revision="1.0.0",
        digest=sha256_digest(material),
    )


# ---------------------------------------------------------------------------
# Policy shape: what the compiled graph actually exposes
# ---------------------------------------------------------------------------

#: Arm ids this binding can express, and the policy id each one emits.
#: The policy id is the trajectory's `policy_ref.policy_id`, so it obeys
#: that contract's `[a-z][a-z0-9_]*` shape and is stable across runs — a
#: dashboard can group by it.
ARM_POLICY_IDS: Final[Mapping[str, str]] = {
    "A": "research_fixed",
    "B": "research_fixed_evidence",
    "C": "research_fixed_verify_repair",
    "D": "research_supervisor_verified",
}

#: What a run is called when the live flags describe no arm at all —
#: `ENABLE_VERIFIER` on without the supervisor that dispatches it, say.
#: A named non-arm rather than a silent fallback to A: a configuration
#: nobody designed must not be recorded as one that was.
CAPABILITY_MISSING_POLICY_ID: Final[str] = "research_capability_missing"

#: Nodes CAP-02 adds for the fixed verify-and-repair policy (arm C).
#: Detected structurally, exactly like the supervisor and the supervisor
#: verifier: a `research_policy` setting that *claims* the policy without
#: these nodes in the compiled graph classifies as `capability_missing`,
#: not as arm C.
FIXED_VERIFY_NODE: Final[str] = "verify"
FIXED_REPAIR_NODE: Final[str] = "repair"

#: What each arm's capability claim requires of the compiled graph.
#: `arm_capability_gap` subtracts the graph's own capabilities from these,
#: so an empty gap means "this graph can run that arm" and a non-empty one
#: names precisely what is absent. Arm C's entry empties out once CAP-02's
#: verify/repair stage is compiled in; arm E's cannot, because nothing in
#: this repository routes compute tiers, branches candidates or decides a
#: marginal stop.
ARM_REQUIRED_CAPABILITIES: Final[Mapping[str, tuple[str, ...]]] = {
    "C": (
        "fixed_post_synthesis_verifier",
        "targeted_repair",
        "reverify_repaired_subject",
    ),
    "E": (
        "adaptive_compute_router",
        "candidate_branching",
        "marginal_stop",
        "candidate_lineage_selector",
    ),
}

#: Flags that are deliberately *not* part of arm identity. ADR 0078 and
#: RFC 09 §7.2 both hold the refiner and reader recovery out as
#: independent factors, so they move the policy digest (they change the
#: graph and the run) and never the arm id.
HELD_OUT_FACTORS: Final[tuple[str, ...]] = (
    "enable_query_refiner",
    "enable_reader_recovery",
)


class GraphShape(StrictContractModel):
    """The compiled graph's structure, read through its public API.

    `nodes` excludes LangGraph's `__start__` / `__end__` sentinels: they
    are always present and say nothing about the policy.
    `conditional_sources` is the set of nodes that own a router, which is
    what separates the fixed pipeline (one router, on the critic) from
    the supervisor loop (one router, on the supervisor).
    """

    nodes: tuple[str, ...]
    conditional_sources: tuple[str, ...]
    edges: tuple[str, ...]
    digest: Digest


_GRAPH_SENTINELS: Final[frozenset[str]] = frozenset({"__start__", "__end__"})


def read_graph_shape(app: Any) -> GraphShape:
    """Read a compiled LangGraph app's structure without executing it.

    Read-only and defensive: `get_graph()` is LangGraph's own drawable
    projection, and everything below tolerates it returning objects with
    slightly different attributes than this version happens to expose.
    A structural read that raises would turn a diagnostic into an
    outage, so the caller gets a `ResearchBindingError` and disables the
    shadow rather than a stray `AttributeError` inside a job.
    """
    try:
        graph = app.get_graph()
        nodes = sorted(str(name) for name in graph.nodes if name not in _GRAPH_SENTINELS)
        edges: list[str] = []
        conditional: set[str] = set()
        for edge in graph.edges:
            source = str(edge.source)
            target = str(edge.target)
            is_conditional = bool(getattr(edge, "conditional", False))
            edges.append(f"{source}->{target}{'?' if is_conditional else ''}")
            if is_conditional:
                conditional.add(source)
    except Exception as exc:  # noqa: BLE001 — a structural read must not fail a run
        raise ResearchBindingError(
            f"compiled graph structure is unreadable: {type(exc).__name__}"
        ) from exc
    ordered_edges = tuple(sorted(edges))
    return GraphShape(
        nodes=tuple(nodes),
        conditional_sources=tuple(sorted(conditional)),
        edges=ordered_edges,
        digest=sha256_digest(
            {
                "nodes": list(nodes),
                "edges": list(ordered_edges),
                "conditional_sources": sorted(conditional),
            }
        ),
    )


class PolicyShape(StrictContractModel):
    """How the live configuration and the compiled graph classify.

    `arm_id` is `None` exactly when `representable` is False, and then
    `missing_capabilities` says which structural capability the claimed
    combination would need. That pairing is the module's central honesty
    rule: a shape either names an arm the graph can actually run, or it
    names what is missing.
    """

    arm_id: Literal["A", "B", "C", "D"] | None
    selector: (
        Literal["fixed", "fixed_evidence", "fixed_verify_repair", "supervisor_verified"]
        | None
    )
    policy_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    policy_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    representable: bool
    missing_capabilities: tuple[str, ...]
    graph_capabilities: tuple[str, ...]
    declared_research_policy: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    held_out_factors: Mapping[str, bool]
    runtime_flags: RuntimeFlags
    graph: GraphShape

    @property
    def policy_digest(self) -> str:
        """Digest of the arm snapshot, or of the refusal that replaces it."""
        if self.representable:
            return sha256_digest(policy_snapshot(self))
        return sha256_digest(
            {
                "policy_id": self.policy_id,
                "missing_capabilities": list(self.missing_capabilities),
                "graph_digest": self.graph.digest,
            }
        )


def classify_policy_shape(config: Settings, app: Any) -> PolicyShape:
    """Classify one run as arm A, B, C or D, or as an unrepresentable shape.

    **Structure decides, not the flag.** Every capability that has a node
    is read from the compiled graph — is there a `supervisor`, is there a
    `verifier`, is there CAP-02's `verify`/`repair` pair — because that is
    the only reading that cannot be wrong. Two consequences, and both are
    the point of the work order:

    - `ENABLE_VERIFIER=true` under the fixed pipeline adds no node
      (`_build_supervisor_loop` is the only place `verifier` is
      registered), so such a run classifies as arm **A** and cannot claim
      arm C's capability however the flag is set; and
    - a `research_policy` setting that *names* `fixed_verify_repair`
      without the compiled verify/repair stage classifies as
      `capability_missing` rather than as arm C. A claim is not a
      capability.

    The evidence store has no node of its own — it is reader behaviour —
    so it is read from the flag, and that asymmetry is stated here rather
    than left to be rediscovered.

    `research_policy` is read with `getattr` because it arrived in a
    separate work order. Absent, the run is `legacy`, which is a fact
    about this checkout and not a fault.

    Args:
        config: The live settings.
        app: The compiled LangGraph app that will run, or has run.

    Returns:
        The classification. Never raises for an unexpected combination —
        that is what `representable=False` is for.
    """
    return classify_from_graph_shape(config, read_graph_shape(app))


def classify_from_graph_shape(config: Settings, graph: GraphShape) -> PolicyShape:
    """Classify against an already-read graph shape.

    Split out because one caller cannot hand over an app: the scripted
    research campaign's `before_episode` runs before its graph is built,
    so `src.contracts.shadow_bridge` reads the shape once per
    configuration and hands it here rather than compiling a second graph
    for every episode.
    """
    nodes = set(graph.nodes)
    supervisor = "supervisor" in nodes
    verifier = "verifier" in nodes
    fixed_verify = FIXED_VERIFY_NODE in nodes and FIXED_REPAIR_NODE in nodes
    evidence = bool(config.enable_evidence_store)

    flags = RuntimeFlags(
        enable_supervisor=supervisor,
        enable_evidence_store=evidence,
        enable_verifier=verifier,
        enable_query_refiner=bool(config.enable_query_refiner),
        enable_reader_recovery=bool(config.enable_reader_recovery),
    )
    declared = str(getattr(config, "research_policy", "") or "legacy")
    capabilities = graph_capabilities(graph, evidence=evidence)

    arm: Literal["A", "B", "C", "D"] | None
    selector: (
        Literal["fixed", "fixed_evidence", "fixed_verify_repair", "supervisor_verified"]
        | None
    )
    missing: tuple[str, ...] = ()
    if supervisor and verifier and evidence:
        arm, selector = "D", "supervisor_verified"
    elif not supervisor and not verifier and fixed_verify and evidence:
        arm, selector = "C", "fixed_verify_repair"
    elif not supervisor and not verifier and not fixed_verify and evidence:
        arm, selector = "B", "fixed_evidence"
    elif not supervisor and not verifier and not fixed_verify and not evidence:
        arm, selector = "A", "fixed"
    else:
        arm, selector = None, None
        missing = tuple(
            sorted(
                {
                    "supervisor_router" if verifier and not supervisor else "",
                    "supervisor_verifier" if supervisor and not verifier else "",
                    "evidence_store"
                    if (verifier or supervisor or fixed_verify) and not evidence
                    else "",
                    "fixed_pipeline" if fixed_verify and supervisor else "",
                }
                - {""}
            )
        )

    return PolicyShape(
        arm_id=arm,
        selector=selector,
        policy_id=ARM_POLICY_IDS[arm] if arm is not None else CAPABILITY_MISSING_POLICY_ID,
        policy_version=f"{BINDING_VERSION}-shadow",
        representable=arm is not None,
        missing_capabilities=missing,
        graph_capabilities=capabilities,
        declared_research_policy=declared,
        held_out_factors={name: bool(getattr(config, name)) for name in HELD_OUT_FACTORS},
        runtime_flags=flags,
        graph=graph,
    )


def graph_capabilities(graph: GraphShape, *, evidence: bool) -> tuple[str, ...]:
    """What the compiled graph can actually do, in the arm vocabulary.

    Every entry is earned by a node that exists (or, for the evidence
    store, by the reader behaviour its flag turns on). Nothing here is
    ever derived from a policy *name*, which is why a `research_policy`
    that claims verify-and-repair without the stage cannot produce the
    capability that would let the contract's own arm-C validator pass.
    """
    nodes = set(graph.nodes)
    earned: list[str] = ["supervisor_router" if "supervisor" in nodes else "fixed_pipeline"]
    if "verifier" in nodes:
        earned.append("supervisor_verifier")
    if FIXED_VERIFY_NODE in nodes and FIXED_REPAIR_NODE in nodes:
        earned += [
            "fixed_post_synthesis_verifier",
            "targeted_repair",
            "reverify_repaired_subject",
        ]
    if evidence:
        earned.append("evidence_store")
    return tuple(sorted(earned))


def arm_capability_gap(arm_id: str, shape: PolicyShape) -> tuple[str, ...]:
    """Return the capabilities `arm_id` needs and this graph lacks.

    Empty means the graph can run that arm. Arm C's gap empties out on a
    checkout whose fixed graph compiles CAP-02's verify-and-repair stage,
    and stays full on one whose graph does not — including a run with
    `ENABLE_VERIFIER=true`, which adds no node to the fixed pipeline at
    all. Arm E's gap is never empty here: nothing in this repository
    routes a compute tier, branches a candidate or decides a marginal
    stop, and no setting can conjure one.
    """
    if arm_id in ARM_REQUIRED_CAPABILITIES:
        earned = set(shape.graph_capabilities)
        return tuple(
            capability
            for capability in ARM_REQUIRED_CAPABILITIES[arm_id]
            if capability not in earned
        )
    if arm_id == shape.arm_id:
        return ()
    return ("policy_shape_mismatch",)


def policy_snapshot(shape: PolicyShape) -> PolicySnapshot:
    """Turn a representable shape into the manifest's arm snapshot.

    The snapshot's `graph_capabilities` are the graph's *earned* ones —
    the same tuple `arm_capability_gap` subtracts from — so the contract's
    own arm-C validator passes exactly when the verify/repair stage is
    compiled in and fails when it is not. None of the adaptive
    capabilities can ever appear, because no node earns one.
    """
    if shape.arm_id is None or shape.selector is None:
        raise ResearchBindingError(
            "policy shape is not a representable arm: "
            f"missing {list(shape.missing_capabilities)}"
        )
    config_block = (
        PolicyConfig(max_targeted_repairs=1, reverify_repaired_subject=True)
        if shape.arm_id == "C"
        else PolicyConfig()
    )
    capabilities = shape.graph_capabilities
    return PolicySnapshot(
        arm_id=shape.arm_id,
        selector=shape.selector,
        policy_version=shape.policy_version,
        graph_digest=shape.graph.digest,
        graph_capabilities=capabilities,
        config_schema=f"{shape.selector}/{BINDING_VERSION}",
        runtime_flags=shape.runtime_flags,
        config=config_block,
        capabilities=PolicyCapabilities(
            supervisor=shape.runtime_flags.enable_supervisor,
            evidence_store=shape.runtime_flags.enable_evidence_store,
            fixed_post_synthesis_verifier=(
                "fixed_post_synthesis_verifier" in shape.graph_capabilities
            ),
            # Never earned: no node in this repository routes compute
            # tiers, and a capability nothing implements must not be
            # declarable by configuration.
            adaptive_compute=False,
        ),
    )


# ---------------------------------------------------------------------------
# Settings, prompts, tools, code, environment
# ---------------------------------------------------------------------------

#: Settings that name *where* a deployment lives rather than *how* it
#: behaves. Excluded by name because the manifest's safe-content
#: validator rejects private absolute paths and credential-shaped
#: strings, and a settings dump is precisely where one arrives — a
#: developer's `CHECKPOINT_DB_PATH` under `/Users/...` would otherwise
#: fail every seal on that machine and nowhere else.
#:
#: Secrets are *not* on this list, and that is deliberate: they are
#: excluded by type (`SecretStr`) in `settings_snapshot`, before any
#: value is read, so a new credential field is covered the day it lands
#: rather than the day somebody remembers to add it here.
LOCATOR_SETTINGS_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "api_cors_allow_origins",
        "api_host",
        "api_keys_file",
        "checkpoint_db_path",
        "learn_content_root",
        "otel_exporter_endpoint",
        "postgres_url",
        "redis_url",
    }
)


def _manifest_safe_field(name: str, value: str | int | bool | None) -> bool:
    """Ask the manifest's own rule whether this field may be recorded.

    Delegated rather than re-implemented, and that is the point. The
    contract already refuses a field whose *name* reads as a credential
    (`(?:^|_)api_?key(?:$|_)` catches `api_key_hourly_limit`, which holds
    a rate limit and no secret at all) and a *value* that carries a
    private absolute path (a developer's `CHECKPOINT_DB_PATH`). A second
    copy of those rules here would drift from the one that is enforced at
    seal time, and the drift would show up as a manifest that refuses to
    seal on one machine.
    """
    try:
        validate_manifest_safe_content({name: value})
    except RunManifestError:
        return False
    return True


def settings_projection(
    config: Settings,
) -> tuple[dict[str, str | int | bool | None], tuple[str, ...]]:
    """Split `Settings` into what a manifest may record and what it may not.

    Three conversions, each forced by the digest profile rather than
    chosen: a `bool` stays a `bool`, an `int` stays an `int`, a `float`
    becomes a six-decimal string because `agent-contract-json/v1` refuses
    binary floats outright, and anything else is rendered as its string
    form.

    Three exclusions, in the order they apply and each recorded by name
    in the second return value rather than replaced by a placeholder:

    1. **`SecretStr` by type.** The wrapper is recognised before any
       value is read, so `get_secret_value()` is never called and a new
       credential field is covered the day it lands rather than the day
       somebody remembers this list.
    2. **Deployment locators by name** (`LOCATOR_SETTINGS_FIELDS`), which
       say where a deployment lives rather than how it behaves.
    3. **Anything the manifest's own safe-content rule refuses**, which
       is the backstop that keeps this projection honest without
       duplicating the rule.

    Returns:
        The recordable values, and the sorted names of everything cut.
    """
    snapshot: dict[str, str | int | bool | None] = {}
    excluded: list[str] = []
    for name in sorted(type(config).model_fields):
        raw = getattr(config, name)
        if isinstance(raw, SecretStr) or name in LOCATOR_SETTINGS_FIELDS:
            excluded.append(name)
            continue
        value: str | int | bool | None
        # `bool` and `int` are both kept as they are; what matters is that
        # neither is stringified, so a flag stays a flag in the digest.
        if raw is None or isinstance(raw, (bool, int)):
            value = raw
        elif isinstance(raw, float):
            value = money(raw)
        else:
            value = str(raw)
        if not _manifest_safe_field(name, value):
            excluded.append(name)
            continue
        snapshot[name] = value
    return snapshot, tuple(excluded)


def settings_snapshot(config: Settings) -> dict[str, str | int | bool | None]:
    """The recordable half of `settings_projection`."""
    return settings_projection(config)[0]


def excluded_settings_fields(config: Settings) -> tuple[str, ...]:
    """The names `settings_snapshot` deliberately leaves out."""
    return settings_projection(config)[1]


def settings_schema_digest(config: Settings) -> str:
    """Digest the snapshot's *shape*: which fields exist, which are cut.

    Separate from the value digest on purpose. A field appearing or
    disappearing is a different event from a value changing, and the
    manifest carries both so a later reader can tell "this deployment was
    configured differently" from "this build had different knobs".
    """
    return sha256_digest(
        {
            "binding_version": BINDING_VERSION,
            "fields": sorted(type(config).model_fields),
            "excluded": list(excluded_settings_fields(config)),
            "excluded_secret_type": "pydantic.SecretStr",
        }
    )


#: The agent system prompts that make up the research prompt bundle,
#: as `(name, module, constant)`. Hashed by *importing* the constant
#: rather than by copying its text: a prompt edit moves the bundle digest
#: without anybody updating a second copy, and no rendered prompt or
#: prompt text ever reaches the manifest (RFC 09 §8.2 forbids it).
PROMPT_CONSTANTS: Final[tuple[tuple[str, str, str], ...]] = (
    ("planner.system", "src.agents.planner", "SYSTEM_PROMPT"),
    ("reader.system", "src.agents.reader", "SYSTEM_PROMPT"),
    ("reader.evidence", "src.agents.reader", "EVIDENCE_SYSTEM_PROMPT"),
    ("synthesizer.system", "src.agents.synthesizer", "SYSTEM_PROMPT"),
    ("synthesizer.evidence", "src.agents.synthesizer", "EVIDENCE_SYSTEM_PROMPT"),
    ("critic.system", "src.agents.critic", "SYSTEM_PROMPT"),
    ("verifier.system", "src.agents.verifier", "VERIFIER_SYSTEM_PROMPT"),
    ("supervisor.system", "src.agents.supervisor", "SUPERVISOR_SYSTEM_PROMPT"),
    ("query_refiner.system", "src.agents.query_refiner", "QUERY_REFINER_SYSTEM_PROMPT"),
)


@lru_cache(maxsize=1)
def prompt_digests() -> Mapping[str, str]:
    """Digest every research system prompt, by name.

    Cached for the process: the constants are module-level literals and
    cannot change under a running worker, and the alternative is nine
    hashes per job.
    """
    digests: dict[str, str] = {}
    for name, module_name, constant in PROMPT_CONSTANTS:
        try:
            module = import_module(module_name)
            text = str(getattr(module, constant))
        except (ImportError, AttributeError) as exc:
            raise ResearchBindingError(
                f"prompt constant {module_name}.{constant} is unavailable"
            ) from exc
        digests[name] = sha256_digest(text)
    return digests


def prompt_snapshot() -> PromptSnapshot:
    """The manifest's prompt section: digests only, never text."""
    digests = prompt_digests()
    return PromptSnapshot(
        bundle_ref=_ref("prompt_bundle", "research-prompt-bundle", dict(digests)),
        renderer_digest=sha256_digest(
            {"renderer": "src.llm.call_llm_json", "binding": BINDING_VERSION}
        ),
    )


def _source_digest(*relative: str) -> str:
    """Digest a set of repository files by relative path and content.

    Relative paths only: an absolute one would put a developer's home
    directory into a manifest, which the safe-content validator rejects
    and which is not a fact about the code in any case. A file that is
    missing hashes as absent rather than raising — a source tree pruned
    for a container image is a different build, and saying so is more
    useful than refusing to describe it.
    """
    material: dict[str, str] = {}
    for pattern in relative:
        for path in sorted(REPO_ROOT.glob(pattern)):
            try:
                material[path.relative_to(REPO_ROOT).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
            except OSError:
                material[path.relative_to(REPO_ROOT).as_posix()] = "unreadable"
    if not material:
        material = {"__absent__": "no matching source files"}
    return sha256_digest(material)


@lru_cache(maxsize=1)
def code_snapshot() -> CodeSnapshot:
    """Describe the checkout the run is executing from.

    `src.eval.provenance.code_revision` already answers "which commit,
    and was the tree dirty" with a five-second timeout and a cache, so it
    is reused rather than re-implemented — the import is deferred so that
    a settings-only import of this module pulls in no eval code.

    An unresolvable commit is recorded as forty zeros with a dirty tree
    and `promotion_eligible=False`, which is the honest reading: a build
    that cannot name its revision is not a build anything should be
    promoted from. A tree whose cleanliness could not be determined is
    treated as dirty for the same reason — `None` is "not checked", and
    "not checked" must not be recorded as "checked and clean".
    """
    from src.eval.provenance import code_revision

    revision = code_revision()
    policy_digest = _source_digest("src/graph/*.py", "src/agents/*.py")
    prompt_digest = sha256_digest(dict(prompt_digests()))
    tool_digest = _source_digest("src/tools/*.py")

    resolved = _COMMIT_RE.match(revision.commit) is not None
    dirty = (not resolved) or revision.dirty is not False
    return CodeSnapshot(
        repository=REPOSITORY_LABEL,
        commit_sha=revision.commit if resolved else _UNKNOWN_COMMIT_SHA,
        worktree_state="dirty" if dirty else "clean",
        patch_digest=(
            sha256_digest(
                {
                    "commit_resolved": resolved,
                    "policy": policy_digest,
                    "prompt": prompt_digest,
                    "tool": tool_digest,
                }
            )
            if dirty
            else None
        ),
        policy_subtree_digest=policy_digest,
        prompt_subtree_digest=prompt_digest,
        tool_subtree_digest=tool_digest,
        promotion_eligible=not dirty,
    )


@lru_cache(maxsize=4)
def environment_snapshot(
    execution_class: Literal["local-test", "local-eval", "ci", "production"],
) -> EnvironmentSnapshot:
    """Describe the interpreter and platform the run executed on."""
    try:
        process_locale = locale_module.getlocale(locale_module.LC_CTYPE)[0] or "unset"
    except (ValueError, TypeError):
        # A platform whose C locale is unset or unparsable answers here;
        # `unset` is a fact about the environment, not a failure.
        process_locale = "unset"
    timezone = (datetime.now().astimezone().tzname() or "").strip() or "unknown"
    lock = REPO_ROOT / "requirements-lock.txt"
    lock_material = (
        {"file": "requirements-lock.txt", "sha256": hashlib.sha256(lock.read_bytes()).hexdigest()}
        if lock.is_file()
        else {"file": "requirements-lock.txt", "sha256": "absent"}
    )
    return EnvironmentSnapshot(
        execution_class=execution_class,
        python_version=platform_module.python_version(),
        platform=f"{sys.platform}-{platform_module.machine() or 'unknown'}",
        dependency_lock_ref=_ref("dependency_lock", "requirements-lock", lock_material),
        locale=process_locale,
        timezone=timezone,
    )


# ---------------------------------------------------------------------------
# Tools and sources
# ---------------------------------------------------------------------------

#: The tools the research agent may invoke, in the TaskSpec vocabulary
#: RFC 09 §8.3 fixes for this experiment. The parser, chunker, ranker and
#: caches are *internal components*, not permissions: nothing the policy
#: decides can turn one on or off, so recording them as capabilities
#: would overstate what the agent is allowed to do.
AGENT_TOOLS: Final[tuple[str, ...]] = ("arxiv_search", "pdf_reader")
SEMANTIC_SCHOLAR_TOOL: Final[str] = "semantic_scholar"
INTERNAL_COMPONENTS: Final[tuple[str, ...]] = (
    "pdf_parser",
    "chunker",
    "chunk_ranker",
    "paper_cache",
    "embedding_cache",
    "http_session",
)
DENIED_ACTIONS: Final[tuple[str, ...]] = (
    "general_shell",
    "repository_write",
    "deploy",
    "send_message",
    "external_publish",
)


def agent_tools(config: Settings) -> tuple[str, ...]:
    """The agent-invocable tool ids this configuration exposes."""
    if config.enable_semantic_scholar:
        return (*AGENT_TOOLS, SEMANTIC_SCHOLAR_TOOL)
    return AGENT_TOOLS


def tool_snapshot(config: Settings) -> ToolSnapshot:
    """The manifest's tool section, with per-implementation digests."""
    tools = agent_tools(config)
    implementations = {
        "arxiv_search": "src/tools/arxiv_search.py",
        "pdf_reader": "src/tools/pdf_parser.py",
        SEMANTIC_SCHOLAR_TOOL: "src/tools/semantic_scholar.py",
    }
    implementation_refs = tuple(
        _ref(
            "tool_implementation",
            tool.replace("_", "-"),
            {"module": implementations[tool], "digest": _source_digest(implementations[tool])},
        )
        for tool in tools
    )
    return ToolSnapshot(
        registry_ref=_ref(
            "tool_registry",
            "research-tool-registry",
            {
                "agent_invocable": list(tools),
                "internal_components": list(INTERNAL_COMPONENTS),
                "denied": list(DENIED_ACTIONS),
            },
        ),
        implementation_refs=implementation_refs,
        agent_invocable=tools,
        internal_components=INTERNAL_COMPONENTS,
        denied=DENIED_ACTIONS,
        network_policy="none" if config.use_mock_data else "allowlisted",
        filesystem_policy="read-only",
        # No tool result is captured anywhere by this work order; W08 owns
        # the content-addressed adapter that would make capture possible.
        tool_result_capture="none",
    )


def _mock_corpus_ref() -> ImmutableObjectRef:
    """A content-addressed reference to the shipped mock paper fixture."""
    from src.agents.search import MOCK_PAPERS

    return _ref(
        "supplied_corpus",
        "mock-papers-fixture",
        [
            {"id": str(paper.get("id", "")), "title": str(paper.get("title", ""))}
            for paper in MOCK_PAPERS
        ],
    )


def source_scope(config: Settings) -> SourceScope:
    """The task's source boundary, derived from the live configuration.

    Two genuinely different corpora, and the distinction is the one
    RFC 09 §8.4 insists on: mock mode is a *supplied* corpus (a fixed
    fixture the run cannot leave), and everything else is *live* arXiv
    with allowlisted network access. Calling the first one "live with
    mock data" would let two incomparable runs share a manifest shape.
    """
    policy_ref = _ref(
        "source_policy",
        "research-mock-corpus" if config.use_mock_data else "research-arxiv-live",
        {
            "mode": "supplied" if config.use_mock_data else "live",
            "semantic_scholar": bool(config.enable_semantic_scholar),
        },
    )
    if config.use_mock_data:
        return SourceScope(
            policy_ref=policy_ref,
            corpus_mode=CorpusMode.SUPPLIED,
            allowed_providers=(),
            allowed_source_types=("paper", "paper_metadata"),
            supplied_corpus_refs=(_mock_corpus_ref(),),
            minimum_distinct_sources=1,
        )
    providers = ("arxiv", SEMANTIC_SCHOLAR_TOOL) if config.enable_semantic_scholar else ("arxiv",)
    return SourceScope(
        policy_ref=policy_ref,
        corpus_mode=CorpusMode.LIVE,
        allowed_providers=providers,
        allowed_source_types=("paper", "paper_metadata"),
        minimum_distinct_sources=1,
    )


def source_snapshot(config: Settings, scope: SourceScope) -> SourceSnapshot:
    """The manifest's mirror of the task's source boundary."""
    return SourceSnapshot(
        input_corpus_mode=scope.corpus_mode,
        observation_capture_mode="none",
        source_policy_ref=scope.policy_ref,
        live_access_allowed=scope.corpus_mode is CorpusMode.LIVE,
    )


# ---------------------------------------------------------------------------
# Task compilation
# ---------------------------------------------------------------------------


def compiler_ref() -> ImmutableObjectRef:
    """Identity of the deterministic compiler this binding calls."""
    return _ref(
        "task_compiler",
        "research-shadow-compiler",
        {
            "binding_version": BINDING_VERSION,
            "compilers": ["compile_research_request", "compile_benchmark_case"],
        },
    )


def _execution_limits(config: Settings, *, supervisor: bool) -> ExecutionLimits:
    """Structural upper bounds for one research episode.

    Derived from the settings that actually bound the graph rather than
    declared: the planner, synthesizer and critic are one model call each
    per pass, the reader is one per paper (two when the evidence store is
    on, which asks it a second question), and the loop is bounded by
    `max_loop_iterations` under the supervisor and `max_iterations`
    without it. These are *ceilings the task permits*, not predictions —
    a task that permits fewer calls than the graph can make would refuse
    a legitimate run at admission.
    """
    per_pass = 1 + config.max_papers * (2 if config.enable_evidence_store else 1) + 2
    passes = config.max_loop_iterations if supervisor else config.max_iterations
    return ExecutionLimits(
        hard_timeout_seconds=max(1, min(86_400, int(config.api_job_timeout_sec))),
        max_tool_calls=min(10_000, config.max_papers * 3 + config.results_per_query * 4 + 8),
        max_model_calls=min(10_000, per_pass * max(1, passes) + 4),
        workflow_cost=WorkflowCostBoundary(
            # Never anything else. A shadow episode is not authority to
            # spend, and a positive ceiling here would be exactly the
            # "declaring a ceiling authorizes work" mistake invariant 10
            # of the work-order package forbids.
            chargeable_work="forbidden",
            workflow_spend_ceiling_usd="0.000000",
        ),
    )


def _data_policy(surface: ProductSurface) -> TaskDataPolicy:
    """The task's data boundary: user text for the API, internal for eval."""
    is_api = surface is ProductSurface.RESEARCH_API
    return TaskDataPolicy(
        policy_ref=_ref(
            "data_policy",
            "research-no-training",
            {"training_use": "prohibited", "surface": surface.value},
        ),
        data_class=DataClass.USER_CONFIDENTIAL if is_api else DataClass.INTERNAL,
        processing_purposes=("product_operation",) if is_api else ("aggregate_analytics",),
        retention_policy_ref=retention_policy_ref(),
    )


def requested_policy(config: Settings, surface: ProductSurface, *, supervisor: bool) -> TaskPolicyBundle:
    """The policy a research episode requests, before the platform ceiling."""
    scope = source_scope(config)
    return TaskPolicyBundle(
        source_scope=scope,
        freshness=FreshnessRequirement(
            mode=(
                FreshnessMode.NO_REQUIREMENT
                if scope.corpus_mode is not CorpusMode.LIVE
                else FreshnessMode.LATEST_AVAILABLE
            )
        ),
        tool_policy=ToolPolicy(
            policy_ref=_ref(
                "tool_policy",
                "research-bounded-tools",
                {"allowed": list(agent_tools(config)), "denied": list(DENIED_ACTIONS)},
            ),
            allowed_agent_tools=agent_tools(config),
            denied_action_ids=DENIED_ACTIONS,
            network_access="none" if config.use_mock_data else "allowlisted",
        ),
        execution_limits=_execution_limits(config, supervisor=supervisor),
        autonomy=AutonomyPolicy(maximum_tier=AutonomyTier.A1_BOUNDED_TOOLS),
        data_policy=_data_policy(surface),
    )


def platform_ceiling(config: Settings, requested: TaskPolicyBundle) -> PlatformPolicyCeiling:
    """The platform's own ceiling, expressed so the intersection is a no-op.

    This binding is a *shadow*: it must describe the run that is actually
    happening, not narrow it. So the ceiling is set to exactly what the
    deployment permits — which makes `intersect_with_platform` an
    identity here — and the narrowing machinery stays wired for W07,
    which will supply a campaign ceiling that genuinely binds.
    """
    limits = requested.execution_limits
    return PlatformPolicyCeiling(
        allowed_corpus_modes=(requested.source_scope.corpus_mode,),
        allowed_providers=requested.source_scope.allowed_providers,
        allowed_source_types=requested.source_scope.allowed_source_types,
        allowed_agent_tools=agent_tools(config),
        denied_action_ids=DENIED_ACTIONS,
        network_access=requested.tool_policy.network_access,
        maximum_autonomy_tier=AutonomyTier.A1_BOUNDED_TOOLS,
        hard_timeout_seconds=limits.hard_timeout_seconds,
        max_tool_calls=limits.max_tool_calls,
        max_model_calls=limits.max_model_calls,
        chargeable_work="forbidden",
        workflow_spend_ceiling_usd="0.000000",
        minimum_data_class=DataClass.INTERNAL,
        allowed_processing_purposes=("product_operation", "aggregate_analytics"),
    )


def compile_research_intake(
    config: Settings,
    *,
    task_id: str,
    query: str,
    hitl_plan_review: bool,
    supervisor: bool,
    compiled_at: str | None = None,
) -> TaskSpecV1:
    """Compile one API research request into an immutable TaskSpec.

    Deterministic and side-effect free: the query becomes the objective
    verbatim (RFC 08 §10.1 forbids a model rewriting it), the deliverable
    set comes from `research.focused_evidence_review`, and nothing here
    can start, authorize or price a call.
    """
    requested = requested_policy(config, ProductSurface.RESEARCH_API, supervisor=supervisor)
    return compile_research_request(
        ResearchCompilerInput(
            task_id=task_id,
            query=query,
            hitl_plan_review=hitl_plan_review,
        ),
        requested_policy=requested,
        platform_policy=platform_ceiling(config, requested),
        compiler_ref=compiler_ref(),
        compiled_at=compiled_at or utc_timestamp(),
    )


class BenchmarkBinding(StrictContractModel):
    """The registry facts an eval episode supplies to the manifest.

    Passed in rather than read here, and that is a boundary decision: the
    benchmark modules belong to P0-WO06, so this module never imports
    them. The eval hook that *does* own that data builds one of these,
    and the digests are taken over the case's actual content, so two
    checkouts with different benchmark text mint different refs.
    """

    suite_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")]
    task_set_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")]
    case_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")]
    dataset_version: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    case_material: Mapping[str, str]
    rubric_versions: Mapping[str, str]
    judge_model: Annotated[str, StringConstraints(min_length=1, max_length=200)]

    def origin(self) -> BenchmarkOrigin:
        """The TaskSpec's benchmark origin, all three refs content-derived."""
        return BenchmarkOrigin(
            suite_ref=_ref(
                "benchmark_suite", self.suite_id, {"dataset_version": self.dataset_version}
            ),
            task_set_ref=_ref(
                "task_set", self.task_set_id, {"dataset_version": self.dataset_version}
            ),
            task_case_ref=_ref("task_case", self.case_id, dict(self.case_material)),
        )

    def resolution(self) -> RegistryResolution:
        """The manifest's registry section for this case.

        `split_assignment_ref` and `validation_receipt_ref` are
        *unresolved*: there is no split broker and no registry validation
        receipt in this checkout, and P0-WO06 owns building them. Saying
        so in the ref is the alternative to inventing one.
        """
        origin = self.origin()
        return RegistryResolution(
            suite_ref=origin.suite_ref,
            task_set_ref=origin.task_set_ref,
            task_case_ref=origin.task_case_ref,
            split_assignment_ref=_unresolved_ref("split_assignment", "P0-WO06"),
            rubric_set_refs=(
                _ref("rubric_set", "research-rubrics", dict(self.rubric_versions)),
            ),
            grader_profile_refs=(
                _ref(
                    "grader_profile",
                    "research-metrics",
                    {"judge_model": self.judge_model, "rubrics": dict(self.rubric_versions)},
                ),
            ),
            validation_receipt_ref=_unresolved_ref("registry_validation_receipt", "P0-WO06"),
        )


def compile_eval_case(
    config: Settings,
    binding: BenchmarkBinding,
    *,
    task_id: str,
    objective: str,
    supervisor: bool,
    compiled_at: str | None = None,
) -> TaskSpecV1:
    """Compile one selected eval case into an immutable TaskSpec.

    One spec per selected case revision, compiled at *selection* and
    reused for every repeat: RFC 08 §11 makes per-repeat recompilation
    invalid because it would give two samples of the same case different
    task identities and quietly break the pairing.
    """
    requested = requested_policy(config, ProductSurface.RESEARCH_EVAL, supervisor=supervisor)
    return compile_benchmark_case(
        task_id=task_id,
        task_kind=TaskKind.RESEARCH_FOCUSED_EVIDENCE_REVIEW,
        objective=objective,
        candidate_visible_refs=(),
        origin=binding.origin(),
        product_surface=ProductSurface.RESEARCH_EVAL,
        requested_policy=requested,
        platform_policy=platform_ceiling(config, requested),
        compiler_ref=compiler_ref(),
        compiled_at=compiled_at or utc_timestamp(),
    )


def _bundle_from_spec(spec: TaskSpecV1) -> TaskPolicyBundle:
    """Re-read the compiled spec's own policy as an admission bundle.

    Taken from the spec rather than rebuilt from settings so the
    admission controller's narrowing proof compares the task against
    itself: the compiler may add a human checkpoint after the platform
    intersection, and a bundle rebuilt from settings would be missing it
    and read as a *removed* checkpoint.
    """
    return TaskPolicyBundle(
        source_scope=spec.source_scope,
        freshness=spec.freshness,
        tool_policy=spec.tool_policy,
        execution_limits=spec.execution_limits,
        autonomy=spec.autonomy,
        data_policy=spec.data_policy,
    )


# ---------------------------------------------------------------------------
# Provider, evaluation and budget sections
# ---------------------------------------------------------------------------

#: Model routes RFC 09 §8.1 names for this experiment, mapped to the
#: per-agent settings that resolve them. `""` means "inherit
#: `anthropic_model`" throughout `Settings`, so the route is resolved
#: here rather than recorded as an empty string.
MODEL_ROUTE_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("planner", "planner_model"),
    ("reader", "reader_model"),
    ("synthesizer", "synthesizer_model"),
    ("critic", "critic_model"),
    ("verifier", "verifier_model"),
    ("supervisor", "supervisor_model"),
    ("query_refiner", "query_refiner_model"),
)


def model_routes(config: Settings) -> dict[str, str]:
    """Every model id this deployment can route a research call to."""
    routes = {"default": config.anthropic_model}
    for route, field in MODEL_ROUTE_FIELDS:
        routes[route] = str(getattr(config, field) or config.anthropic_model)
    return routes


def _sampling_snapshot() -> SamplingSnapshot:
    """Read the sampling parameters `src.llm` actually issues calls with.

    Introspected rather than copied. `_TEMPERATURE` is a module constant
    and `max_tokens` is a signature default, and both are read through
    `getattr`/`inspect` so an edit in `src/llm.py` moves the manifest
    digest instead of silently disagreeing with it.
    """
    from src import llm

    temperature = float(getattr(llm, "_TEMPERATURE", 0.3))
    max_tokens = 4096
    try:
        default = inspect.signature(llm.call_llm).parameters["max_tokens"].default
        if isinstance(default, int) and default > 0:
            max_tokens = default
    except (ValueError, KeyError, TypeError):
        # A `call_llm` whose signature stops naming `max_tokens` leaves
        # the documented 4096 standing rather than failing the seal.
        pass
    return SamplingSnapshot(temperature=money(temperature), maximum_output_tokens=max_tokens)


def provider_snapshot(config: Settings) -> ProviderSnapshot:
    """The manifest's provider section, with no credential material.

    **`metered` is the load-bearing field.** Under `USE_MOCK_DATA` the
    research surface is served from a fixture and the declared provider
    is `local_mock`, which bills nothing. Anywhere else the provider is
    Anthropic and it bills per token — so the manifest says so, and the
    admission controller then refuses to seal without an external
    approval this work order does not have. That refusal is the design:
    "possessing an API key never authorizes chargeable work" has to be
    enforced somewhere, and a manifest that quietly claimed a metered
    provider was free would be the place it stopped being true.
    """
    mock = bool(config.use_mock_data)
    return ProviderSnapshot(
        llm=LlmProviderSnapshot(
            provider="local_mock" if mock else "anthropic",
            api_protocol_version="anthropic-messages-2023-06-01",
            model_resolution="exact-id-required",
            routes=model_routes(config),
            sampling=_sampling_snapshot(),
            retry=RetrySnapshot(
                timeout_seconds=max(1, min(86_400, int(config.anthropic_timeout_sec))),
                max_retries=min(20, max(0, int(config.anthropic_max_retries))),
            ),
            prompt_cache="enabled" if config.enable_prompt_caching else "disabled",
            # Presence only, and a binding reference that names the
            # environment rather than the value. Hashing a credential is
            # explicitly not an escape hatch (RFC 09 §12.2).
            credential=CredentialBinding(present=False) if mock else CredentialBinding(
                present=True,
                binding_ref="credential-binding://anthropic/process-environment",
            ),
            metered=not mock,
        ),
        pricing=PricingSnapshot(
            table_ref=_ref(
                "pricing_table",
                "anthropic-list-prices",
                {"source": "src/observability/costs.py"},
            ),
            prices_last_verified=_prices_last_verified(),
        ),
    )


def _prices_last_verified() -> str:
    """The date the shipped price table was last checked (ADR 0044)."""
    from src.observability.costs import PRICES_LAST_VERIFIED

    return str(PRICES_LAST_VERIFIED)


def evaluation_snapshot(binding: BenchmarkBinding | None) -> EvaluationSnapshot:
    """The manifest's evaluation section.

    Zero budget in both configurations, and that is not a placeholder: a
    shadow manifest authorizes nothing, so the judge spend an eval
    campaign really does incur stays outside the sealed envelope until
    P0-WO07 gives a campaign a budget that means something. Declaring a
    positive cap here would flip `approval.required` and make every
    shadow episode fail admission — which is exactly the behaviour the
    contract wants from a manifest that claims chargeable resources.
    """
    if binding is None:
        return EvaluationSnapshot(
            grader_profile_refs=(),
            judge_routes={},
            judge_prompt_bundle_ref=_unresolved_ref("prompt_bundle", "P0-WO10"),
            blinding_policy="not-applicable-production-surface",
            ordering_policy="not-applicable-production-surface",
            sampling=SamplingSnapshot(temperature="0.000000", maximum_output_tokens=1),
            retry=RetrySnapshot(timeout_seconds=1, max_retries=0),
            null_score_policy="not-applicable-production-surface",
            budget=EvaluationBudget(cost_usd_max="0.000000", model_calls_max=0),
        )
    resolution = binding.resolution()
    return EvaluationSnapshot(
        grader_profile_refs=resolution.grader_profile_refs,
        judge_routes={name: binding.judge_model for name in sorted(binding.rubric_versions)},
        judge_prompt_bundle_ref=_ref(
            "prompt_bundle", "research-judge-rubrics", dict(binding.rubric_versions)
        ),
        blinding_policy="unblinded-shadow-observation",
        ordering_policy="benchmark-declared-order",
        sampling=_sampling_snapshot(),
        retry=RetrySnapshot(timeout_seconds=30, max_retries=0),
        null_score_policy="retain-and-report-denominator",
        budget=EvaluationBudget(cost_usd_max="0.000000", model_calls_max=0),
    )


def episode_budget(spec: TaskSpecV1) -> EpisodeBudget:
    """Every cap a shadow episode declares: zero dollars, real counts."""
    limits = spec.execution_limits
    return EpisodeBudget(
        workflow_cost_usd_max="0.000000",
        judge_cost_usd_max="0.000000",
        total_cost_usd_max="0.000000",
        wall_time_seconds_max=limits.hard_timeout_seconds,
        workflow_model_calls_max=limits.max_model_calls,
        judge_model_calls_max=0,
        tool_calls_max=limits.max_tool_calls,
    )


# ---------------------------------------------------------------------------
# Sealing
# ---------------------------------------------------------------------------

EpisodeOrigin = Literal["research_api", "research_eval", "research_scripted"]

#: Execution class recorded per origin. The API surface reports
#: `production` unless it is running on the mock corpus, which is the
#: only honest reading: a run against live arXiv with a real credential
#: is production whatever process started it.
_EXECUTION_CLASSES: Final[Mapping[EpisodeOrigin, tuple[str, str]]] = {
    "research_api": ("local-test", "production"),
    "research_eval": ("local-eval", "local-eval"),
    "research_scripted": ("local-eval", "local-eval"),
}


class SealedEpisode(StrictContractModel):
    """Everything sealing produced, in the order it was produced.

    The runtime projection is built and verified here and then simply
    carried: nothing in this work order reads it. That is deliberate —
    W05 proves the candidate-safe projection can be derived and that its
    digest matches the manifest's claim, and W08 decides who is allowed
    to receive it.
    """

    origin: EpisodeOrigin
    task_spec: TaskSpecV1
    task_ref: TaskSpecRef
    receipt: TaskCompilationReceipt
    manifest: RunManifestV1
    projection: PolicyRuntimeProjection
    shape: PolicyShape
    policy: PolicySnapshot

    @property
    def manifest_digest(self) -> str:
        return self.manifest.integrity.payload_sha256

    @property
    def run_id(self) -> str:
        return self.manifest.payload.identity.run_id


def deterministic_run_id(runtime_run_id: str) -> str:
    """Derive the contract run id from the runtime's own id.

    Derived rather than random so that a manifest is reproducible from a
    job id: two seals of the same job produce the same identity, which is
    what lets a test assert a *stable* digest instead of merely a
    well-formed one.
    """
    entropy = uuid.UUID(bytes=hashlib.sha256(runtime_run_id.encode("utf-8")).digest()[:16])
    return f"run_{entropy.hex}"


def seal_research_episode(
    config: Settings,
    *,
    shape: PolicyShape,
    spec: TaskSpecV1,
    origin: EpisodeOrigin,
    runtime_run_id: str,
    repeat_index: int = 0,
    hitl_bypass: bool,
    hitl_bypass_reason: str | None,
    benchmark: BenchmarkBinding | None = None,
    task_store: Any = None,
    sealed_at: str | None = None,
) -> SealedEpisode:
    """Seal one episode's configuration before its first node runs.

    The order is RFC 09 §5.1's, and every step of it is load-bearing:
    compile and persist the task (already done by the caller), classify
    the policy against the compiled graph, resolve admission — which is
    where a metered provider or an over-broad effective policy fails
    closed — build and hash the candidate-safe projection, then hash and
    seal the control-plane payload. `run.admitted` is appended by the
    bridge afterwards, carrying the digest this function returns.

    Raises:
        ResearchBindingError: The configuration cannot be expressed as a
            sealed episode — an unrepresentable policy shape, or a
            chargeable provider with no approval. Never a partial seal.
    """
    moment = sealed_at or utc_timestamp()
    policy = policy_snapshot(shape)

    task_ref = build_task_spec_ref(spec, artifact_locator=_cas_locator(sha256_digest(spec)))
    receipt = persist_compiled_task(
        spec,
        task_store if task_store is not None else _NullTaskStore(),
        artifact_locator=task_ref.artifact_locator,
    )

    bundle = _bundle_from_spec(spec)
    budget = episode_budget(spec)
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
                episode_budget=budget,
                provider_metered=provider.llm.metered,
            ),
            verified_at=moment,
            approval_backend=FakeLocalApprovalBackend(),
        )
    except RunManifestError as exc:
        raise ResearchBindingError(
            f"shadow admission failed closed: {exc.detail}"
        ) from exc

    scope = spec.source_scope
    sources = source_snapshot(config, scope)
    prompts = prompt_snapshot()
    tools = tool_snapshot(config)
    values = settings_snapshot(config)
    runtime_config = RuntimeConfigSnapshot(
        settings_schema_digest=settings_schema_digest(config),
        effective_values=values,
        effective_values_digest=sha256_digest(values),
    )
    invocation = InvocationSnapshot(
        enable_hitl=bool(config.enable_hitl),
        hitl_bypass=hitl_bypass,
        hitl_bypass_reason=hitl_bypass_reason if hitl_bypass else None,
        checkpoint_mode="persistent" if config.enable_checkpointing else "disabled",
    )

    run_id = deterministic_run_id(runtime_run_id)
    group_id = derive_replicate_group_id(SHADOW_CAMPAIGN_ID, task_ref, sha256_digest(policy))
    identity = RunIdentity(
        campaign_id=SHADOW_CAMPAIGN_ID,
        episode_key=derive_episode_key(group_id, repeat_index),
        replicate_group_id=group_id,
        run_id=run_id,
        repeat_index=repeat_index,
        created_at=moment,
        created_by=f"contract-shadow/{BINDING_VERSION}",
    )
    randomness = RandomnessSnapshot(
        repeat_index=repeat_index,
        root_seed=int(config.eval_seed),
        component_seeds_ref=_ref(
            "seed_map",
            "shadow-episode-seeds",
            {"root_seed": int(config.eval_seed), "components": ["harness"]},
        ),
        determinism_class=(
            DeterminismClass.DETERMINISTIC_LOCAL
            if config.use_mock_data
            else DeterminismClass.LIVE_INPUT_STOCHASTIC_MODEL
        ),
    )

    projection_payload = PolicyRuntimeProjectionPayload(
        identity={
            "campaign_id": identity.campaign_id,
            "run_id": identity.run_id,
            "repeat_index": identity.repeat_index,
        },
        task=_agent_safe_projection(spec),
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

    mock_class, live_class = _EXECUTION_CLASSES[origin]
    execution_class = mock_class if config.use_mock_data else live_class
    receipt_digest = sha256_digest(receipt)
    payload = RunManifestPayload(
        identity=identity,
        lineage=None,
        compilation=CompilationSnapshot(
            receipt_ref=ImmutableObjectRef(
                kind="compilation_receipt",
                id=receipt.receipt_id.replace("_", "-"),
                revision="1.0.0",
                digest=receipt_digest,
            ),
            receipt_locator=_cas_locator(receipt_digest),
        ),
        task=task_ref,
        campaign_lock_ref=_unresolved_ref("campaign_lock", "P0-WO07"),
        campaign_lock_locator=_cas_locator(
            _unresolved_ref("campaign_lock", "P0-WO07").digest
        ),
        registry_resolution=(
            benchmark.resolution() if benchmark is not None else _unresolved_registry()
        ),
        policy=policy,
        runtime_config=runtime_config,
        invocation=invocation,
        providers=provider,
        prompts=prompts,
        tools=tools,
        sources=sources,
        evaluation=evaluation_snapshot(benchmark),
        randomness=randomness,
        admission_resolution=decision.resolution,
        budgets=BudgetSnapshot(
            episode=budget,
            campaign=CampaignBudget(
                total_cost_usd_max="0.000000",
                # The honest description of `--max-budget-usd`: it is
                # checked between queries, so the query in flight when the
                # ceiling is crossed overshoots by its own cost.
                enforcement="between-episodes-with-in-flight-overshoot-risk",
            ),
        ),
        approval=decision.approval,
        code=code_snapshot(),
        environment=environment_snapshot(execution_class),
        outputs=OutputSnapshot(
            root=f"outputs/contract-shadow/{run_id}",
            artifact_schema_version="1.0.0",
            trajectory_schema_version="1.0.0",
            verification_schema_version="1.0.0",
        ),
        privacy=PrivacySnapshot(
            task_data_class=spec.data_policy.data_class,
            registry_object_classification=DataClass.INTERNAL,
            retention_policy_ref=retention_policy_ref(),
            redaction_policy_version="1.0.0",
        ),
        policy_runtime_projection=PolicyRuntimeProjectionRef(
            artifact_ref=ImmutableObjectRef(
                kind="policy_runtime_projection",
                id=f"shadow-projection-{projection_digest.removeprefix('sha256:')[:24]}",
                revision="1.0.0",
                digest=projection_digest,
            ),
            artifact_locator=_cas_locator(projection_digest),
            excluded_classes=(
                "sealed-case-and-split-identity",
                "evaluator-and-label-refs",
                "approval-metadata",
                "private-object-locators",
                "hidden-rubric-content",
            ),
        ),
    )
    manifest = seal_manifest(payload)
    projection = build_policy_runtime_projection(manifest, spec)
    return SealedEpisode(
        origin=origin,
        task_spec=spec,
        task_ref=task_ref,
        receipt=receipt,
        manifest=manifest,
        projection=projection,
        shape=shape,
        policy=policy,
    )


def _agent_safe_projection(spec: TaskSpecV1) -> Mapping[str, Any]:
    """The candidate-visible task projection, as the contract defines it."""
    from src.contracts.task_spec import agent_safe_task_projection

    return agent_safe_task_projection(spec)


def _unresolved_registry() -> RegistryResolution:
    """The registry section for a run that came from no benchmark at all.

    A production API request has no case, no split and no rubric, and the
    manifest section is not optional. Every ref therefore says
    `shadow-unresolved-...` and carries the digest of that statement —
    the one shape that cannot be mistaken for a resolved case.
    """
    return RegistryResolution(
        suite_ref=_unresolved_ref("benchmark_suite", "P0-WO06"),
        task_set_ref=_unresolved_ref("task_set", "P0-WO06"),
        task_case_ref=_unresolved_ref("task_case", "P0-WO06"),
        split_assignment_ref=_unresolved_ref("split_assignment", "P0-WO06"),
        rubric_set_refs=(_unresolved_ref("rubric_set", "P0-WO06"),),
        grader_profile_refs=(_unresolved_ref("grader_profile", "P0-WO10"),),
        validation_receipt_ref=_unresolved_ref("registry_validation_receipt", "P0-WO06"),
    )


class _NullTaskStore:
    """A `TaskSpecStore` that keeps nothing, for a shadow with no store.

    `persist_compiled_task` is the function that mints the pre-run
    compilation receipt, and the receipt is a manifest input. A shadow
    episode has nowhere durable to put a spec — persistence is W08's —
    so the store is a sink and the receipt is still real.
    """

    def put(self, spec: TaskSpecV1) -> None:
        return None

    def get(self, task_spec_id: str) -> TaskSpecV1 | None:
        return None


# ---------------------------------------------------------------------------
# Parity diagnostics
# ---------------------------------------------------------------------------

#: The terminal trajectory event each legacy job status corresponds to.
#: A budget stop is a `failed` job row with one particular error code,
#: which is why the mapping takes the code as well as the status.
TERMINAL_EVENT_FOR_OUTCOME: Final[Mapping[tuple[str, bool], str]] = {
    ("succeeded", False): "run.completed",
    ("failed", False): "run.failed",
    ("failed", True): "run.budget_stopped",
    ("cancelled", False): "run.cancelled",
}


class ParityMismatch(StrictContractModel):
    """One disagreement between a legacy artifact and a contract view."""

    surface: Literal["job", "eval_record", "research_state"]
    field: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    legacy: str | int | bool | None
    contract: str | int | bool | None
    detail: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class LegacyOutcome(StrictContractModel):
    """The bounded projection of a legacy `Job` row or eval record.

    Bounded on purpose: the parity check compares identities, counts and
    digests, never bodies, so the diagnostic itself cannot become a
    second place a report or a query is copied to.
    """

    surface: Literal["job", "eval_record"]
    query: Annotated[str, StringConstraints(max_length=8_000)]
    status: Literal["succeeded", "failed", "cancelled"]
    budget_stopped: bool = False
    llm_calls: Annotated[int, Field(ge=0)]
    cost_usd: MoneyUsd
    report_digest: Digest | None = None
    task_spec_id: str | None = None
    task_full_digest: Digest | None = None


class ContractOutcome(StrictContractModel):
    """The same episode as the contracts describe it."""

    task_spec_id: str
    task_full_digest: Digest
    objective: Annotated[str, StringConstraints(max_length=8_000)]
    manifest_digest: Digest
    arm_id: Literal["A", "B", "C", "D"] | None
    policy_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    terminal_event_type: str | None
    llm_calls: Annotated[int, Field(ge=0)]
    cost_usd: MoneyUsd
    final_artifact_digest: Digest | None = None


def compare_outcomes(
    legacy: LegacyOutcome, contract: ContractOutcome
) -> tuple[ParityMismatch, ...]:
    """Compare a legacy record with the contract projection of the same run.

    Pure: no settings, no clock, no I/O, no graph. That is what makes it
    testable against a deliberately corrupted projection, and what lets a
    later work order run it over stored records rather than only live
    ones.

    Zero mismatches is the claim W05 makes about the canned runs. A
    non-empty result is not an error — it is the diagnostic, and each
    entry names the field, both readings, and why they had to agree.
    """
    mismatches: list[ParityMismatch] = []

    def add(field: str, left: str | int | bool | None, right: str | int | bool | None, detail: str) -> None:
        mismatches.append(
            ParityMismatch(
                surface=legacy.surface,
                field=field,
                legacy=left,
                contract=right,
                detail=detail,
            )
        )

    if legacy.query != contract.objective:
        add(
            "objective",
            legacy.query[:120],
            contract.objective[:120],
            "the compiled objective must be the submitted query, verbatim",
        )
    expected_terminal = TERMINAL_EVENT_FOR_OUTCOME.get((legacy.status, legacy.budget_stopped))
    if contract.terminal_event_type != expected_terminal:
        add(
            "terminal_event_type",
            expected_terminal,
            contract.terminal_event_type,
            "the trajectory's terminal event must match the recorded outcome",
        )
    if legacy.llm_calls != contract.llm_calls:
        add(
            "llm_calls",
            legacy.llm_calls,
            contract.llm_calls,
            "one model-call event is emitted per accumulator record point",
        )
    if Decimal(legacy.cost_usd) != Decimal(contract.cost_usd):
        add(
            "cost_usd",
            legacy.cost_usd,
            contract.cost_usd,
            "the folded usage cost must equal the run's own accumulator",
        )
    if legacy.report_digest != contract.final_artifact_digest:
        add(
            "final_artifact_digest",
            legacy.report_digest,
            contract.final_artifact_digest,
            "the final artifact ref must address the report the run returned",
        )
    if legacy.task_spec_id is not None and legacy.task_spec_id != contract.task_spec_id:
        add(
            "task_spec_id",
            legacy.task_spec_id,
            contract.task_spec_id,
            "a job bound to a task spec must name the spec this episode compiled",
        )
    if legacy.task_full_digest is not None and legacy.task_full_digest != contract.task_full_digest:
        add(
            "task_full_digest",
            legacy.task_full_digest,
            contract.task_full_digest,
            "a bound task ref must address the same immutable spec",
        )
    return tuple(mismatches)


def compare_research_state(
    spec: TaskSpecV1, state: Mapping[str, Any]
) -> tuple[ParityMismatch, ...]:
    """Check the final `ResearchState` against the immutable task.

    Delegates to W01's own `shadow_research_state_compatibility`, which
    raises when the state's query has diverged from the objective, and
    turns that into a diagnostic rather than an exception — a parity
    check that can fail a run is not a shadow.
    """
    try:
        shadow_research_state_compatibility(spec, state)
    except ContractError as exc:
        return (
            ParityMismatch(
                surface="research_state",
                field="query",
                legacy=str(state.get("query", ""))[:120],
                contract=spec.objective[:120],
                detail=exc.detail[:300],
            ),
        )
    return ()


__all__ = [
    "AGENT_TOOLS",
    "ARM_POLICY_IDS",
    "BINDING_VERSION",
    "CAPABILITY_MISSING_POLICY_ID",
    "DENIED_ACTIONS",
    "HELD_OUT_FACTORS",
    "LOCATOR_SETTINGS_FIELDS",
    "MODEL_ROUTE_FIELDS",
    "PROMPT_CONSTANTS",
    "REPOSITORY_LABEL",
    "SHADOW_CAMPAIGN_ID",
    "TERMINAL_EVENT_FOR_OUTCOME",
    "ARM_REQUIRED_CAPABILITIES",
    "BenchmarkBinding",
    "ContractOutcome",
    "EpisodeOrigin",
    "GraphShape",
    "LegacyOutcome",
    "ParityMismatch",
    "PolicyShape",
    "ResearchBindingError",
    "SealedEpisode",
    "agent_tools",
    "arm_capability_gap",
    "FIXED_REPAIR_NODE",
    "FIXED_VERIFY_NODE",
    "classify_from_graph_shape",
    "classify_policy_shape",
    "code_snapshot",
    "compare_outcomes",
    "compare_research_state",
    "compile_eval_case",
    "compile_research_intake",
    "compiler_ref",
    "deterministic_run_id",
    "environment_snapshot",
    "graph_capabilities",
    "episode_budget",
    "evaluation_snapshot",
    "excluded_settings_fields",
    "model_routes",
    "money",
    "platform_ceiling",
    "policy_snapshot",
    "prompt_digests",
    "prompt_snapshot",
    "provider_snapshot",
    "read_graph_shape",
    "requested_policy",
    "retention_policy_ref",
    "seal_research_episode",
    "settings_schema_digest",
    "settings_projection",
    "settings_snapshot",
    "source_scope",
    "source_snapshot",
    "tool_snapshot",
    "utc_timestamp",
]
