"""Stage-0 contract qualification, as executable checks (P0-WO11).

`docs/agent-engineering/15-stage0-qualification-report.md` is the prose
half of this work order. This module is the half a build can fail on, and
the two are written to be read together: every numbered claim in the
report's sections 1–5 has a test here, and every test here is a sentence
in that report.

Four groups, in the order the report makes its argument.

1. **The three contract defects W07 found.** A cache key that could hand
   arm C the graph arm B compiled, an admission controller that admitted
   a metered provider against a TaskSpec forbidding chargeable work, and
   the campaign's own spend ceiling — which W05 deliberately pins at zero
   and W07 substitutes. Each is a regression test for a fix in this PR,
   except the third, which is a fix that was already correct and had no
   test saying so.
2. **The arm identities.** Four runnable arms sealed against the *real
   compiled graphs*, distinct in every identity field and identical in
   the task, case and registry refs that make them a paired comparison.
   Arm E is refused, and its descriptor is schema-valid and not runnable.
3. **The synthetic episodes.** Each runnable arm driven end to end
   through the real graph under mock mode, producing a trajectory in
   W08's durable sink whose hash chain verifies, whose artifacts are
   reachable, and whose parity report against the legacy record is empty.
4. **The candidate boundary.** The role that runs the episode cannot
   resolve labels, grader profiles, split membership or hidden rubric
   items, and no event it produces is training eligible.

Zero network, zero provider, zero model, asserted rather than assumed.
The dry-run test installs counting spies on `src.llm._get_client` and
`socket.socket.connect` rather than resting on the conftest guards,
because "the qualification made no external call" is the deliverable and
not an ambient property.

**One honest exception, and the report says so in its own words.** Arm
D's supervisor has no mock branch — CAP-07 (ADR 0080) gave one to the
planner, reader, synthesizer, critic, search and verifier, and not to the
router. Left alone under mock mode the supervisor's model call fails and
the node falls back to fixed pipeline order, so the trajectory would be a
*degraded* route recorded as a decided one. `_scripted_supervisor` below
supplies the routing decisions from a fixture instead, which is a canned
judge and is labelled as one.
"""

from __future__ import annotations

import contextlib
import re
import socket
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

import src.agents.assessment as m_assessment
import src.agents.critic as m_critic
import src.agents.planner as m_planner
import src.agents.reader as m_reader
import src.agents.search as m_search
import src.agents.supervisor as m_supervisor
import src.agents.synthesizer as m_synth
import src.agents.verifier as m_verifier
import src.graph.workflow as workflow_module
import src.llm as llm_module
from src.campaign.approval import LocalApprovalRecordBackend, NoCredentialProbe
from src.campaign.arms import (
    ARM_IDS,
    ARM_SETTINGS,
    COMMON_FROZEN_SETTINGS,
    ArmId,
    arm_settings,
    classify_arm,
    declare_arm,
)
from src.campaign.episode import seal_campaign_episode
from src.campaign.errors import CampaignError
from src.campaign.planner import (
    CampaignRequest,
    default_campaign_budget,
    default_episode_budget,
    dry_run,
    plan_campaign,
)
from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts import runtime_bridge as rb
from src.contracts import shadow_bridge as sb
from src.contracts.benchmark_adapters import suite_ref
from src.contracts.kernel import canonical_json, sha256_digest
from src.contracts.registry import (
    IntendedUse,
    LocalRegistry,
    RegistryAccessError,
    RegistryResolutionError,
    RegistryRole,
    SplitKind,
    TaskSet,
)
from src.contracts.research_binding import (
    ARM_REQUIRED_CAPABILITIES,
    GraphShape,
    LegacyOutcome,
    compile_research_intake,
    read_graph_shape,
    seal_research_episode,
)
from src.contracts.run_manifest import (
    AdmissionPlan,
    ApprovalStatus,
    FakeLocalApprovalBackend,
    RunManifestError,
    resolve_admission,
)
from src.contracts.trajectory import ArtifactRole, import_jsonl, verify_trajectory
from src.graph.state import initial_research_state
from src.observability.costs import start_cost_tracking

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_ROOT = REPO_ROOT / "eval_registry"
SUITE_ID = "research-policy-v1"

#: The whole development suite, at 07 §5's repetition rule. Spelled out
#: because 300/240/60 is the number the report quotes and a test that
#: read it off the plan would agree with any plan.
FULL_SUITE_CASES = 20
FULL_SUITE_REPEATS = 3
FULL_SUITE_ARMS = 5
EXPECTED_EPISODES = FULL_SUITE_CASES * FULL_SUITE_REPEATS * FULL_SUITE_ARMS
RUNNABLE_ARMS: tuple[ArmId, ...] = ("A", "B", "C", "D")
PLANNED_EPISODES = FULL_SUITE_CASES * FULL_SUITE_REPEATS * len(RUNNABLE_ARMS)
EXCLUDED_EPISODES = EXPECTED_EPISODES - PLANNED_EPISODES

#: A two-case slice for everything that is not the full-matrix claim.
#: The matrix arithmetic is proved once, at full size; repeating it in
#: every test would buy nothing and cost a graph compile per arm.
SLICE_CASES: tuple[str, ...] = ("hallucination-mitigation", "rag-multi-hop")

FIXED_PIPELINE = ("planner", "search", "reader", "synthesizer", "critic")
QUERY = "why do LLMs hallucinate?"

#: W11-F1. `src/contracts/artifact_store.py`'s `_PRIVATE_REASONING_PATTERNS`
#: refuses any text body matching `chain[ _-]of[ _-]thought`, which a
#: research report *about* chain-of-thought prompting says in the course
#: of doing its job. Restated here rather than imported, because a test
#: that asserted against the module's own private constant would agree
#: with any change to it, including the one that would fix this.
PRIVATE_REASONING_FALSE_POSITIVE = re.compile(r"(?i)\bchain[ _-]of[ _-]thought\b")

#: Every module that binds `src.config.settings` on a path the research
#: graph drives. The e2e tier's own list plus the supervisor and the
#: verifier, which only the supervisor and arm-C shapes reach. Spelled
#: out here rather than imported from `tests/e2e/conftest.py`, which the
#: root conftest notes would rest on a sys.path entry pytest happens to
#: insert.
SETTINGS_CONSUMERS: tuple[Any, ...] = (
    m_assessment,
    m_critic,
    m_planner,
    m_reader,
    m_search,
    m_supervisor,
    m_synth,
    m_verifier,
    workflow_module,
)

#: Arm D's routing decisions, as a fixture. One entry per supervisor
#: turn; the last repeats if the loop asks again. `verify` is in the list
#: because arm D is the arm whose verifier is an action the router picks,
#: and a synthetic arm-D episode that never picked it would not have
#: exercised the capability its manifest claims.
SCRIPTED_SUPERVISOR_ROUTE: tuple[str, ...] = (
    "plan",
    "search",
    "read",
    "synthesize",
    "verify",
    "critique",
    "stop",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def config(**overrides: Any) -> Settings:
    """The shipped settings on a mock, no-cost research surface."""
    base: dict[str, Any] = {
        "use_mock_data": True,
        "enable_tracing": False,
        "enable_metrics": False,
        "enable_checkpointing": False,
        "enable_semantic_scholar": False,
        "enable_hitl": False,
        "contract_shadow": "shadow",
        "contract_event_capture": "evaluation_only",
    }
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


def registry(root: Path | None = None) -> LocalRegistry:
    return LocalRegistry(root or REGISTRY_ROOT)


def suite_case_ids() -> tuple[str, ...]:
    """The suite's own case order, read from the registry as an evaluator."""
    resolved = registry().resolve(
        suite_ref(REGISTRY_ROOT, SUITE_ID),
        role=RegistryRole.EVALUATOR,
        intended_use=IntendedUse.DEVELOPMENT,
    ).payload
    task_set = registry().resolve(
        resolved.task_set_ref,
        role=RegistryRole.EVALUATOR,
        intended_use=IntendedUse.DEVELOPMENT,
    ).payload
    assert isinstance(task_set, TaskSet)
    return tuple(ref.id for ref in task_set.case_refs)


def request(
    cfg: Settings,
    *,
    cases: Sequence[str] | None = None,
    arms: tuple[ArmId, ...] = ARM_IDS,
    repeats: int = FULL_SUITE_REPEATS,
) -> CampaignRequest:
    return CampaignRequest(
        protocol_id="research-policy-v1-stage-0",
        stage="stage-0-qualification",
        suite_ref=suite_ref(REGISTRY_ROOT, SUITE_ID),
        case_ids=tuple(cases) if cases is not None else suite_case_ids(),
        arms=arms,
        repeats=repeats,
        corpus_mode="snapshot",
        seed=0,
        episode_budget=default_episode_budget(cfg, arms),
        campaign_budget=default_campaign_budget(),
    )


@contextlib.contextmanager
def compiled_under(cfg: Settings) -> Iterator[Any]:
    """Compile the real workflow under `cfg` and tear its checkpointer down.

    `build_workflow` dispatches on the module-global `settings`, so the
    binding is swapped for the duration of the compile and restored
    immediately. That ordering is the whole reason this is a context
    manager rather than a call: a graph compiled under the wrong binding
    would classify as the wrong arm and the classification is the thing
    under test.
    """
    original = workflow_module.settings
    workflow_module.settings = cfg  # type: ignore[misc]
    try:
        app = workflow_module.build_workflow(enable_hitl=False)
    finally:
        workflow_module.settings = original  # type: ignore[misc]
    try:
        yield app
    finally:
        stack = getattr(app, "_checkpointer_exit_stack", None)
        if stack is not None:
            with contextlib.suppress(Exception):
                stack.close()


def graph_shape_for(arm: ArmId, cfg: Settings) -> GraphShape:
    """The shape of the graph this checkout compiles for one arm."""
    with compiled_under(arm_settings(cfg, arm)) as app:
        return read_graph_shape(app)


@pytest.fixture(autouse=True)
def _clean_contract_registries() -> Iterator[None]:
    """The shadow registry and the graph-shape cache are process-global."""
    sb.reset_registry()
    yield
    sb.reset_registry()


# ---------------------------------------------------------------------------
# 1. The three contract defects W07 found
# ---------------------------------------------------------------------------


class TestTheContractDefectsW07Found:
    pytestmark = [pytest.mark.unit, pytest.mark.contract]

    def test_the_graph_shape_cache_cannot_hand_arm_c_the_graph_arm_b_compiled(
        self,
    ) -> None:
        """`research_policy` is part of the cache key, and has to be.

        The four flags W05 keyed on — supervisor, verifier, refiner,
        checkpointing — are byte-identical between arm B and arm C:
        CAP-02 made `research_policy` the first question
        `_build_graph_shape` asks, and arm C is the *only* thing that
        moves it. Warming the cache with B and then asking for C used to
        return B's shape, which is a manifest recording arm C against a
        graph with no verify or repair node in it.
        """
        cfg = config()
        legacy = arm_settings(cfg, "B")
        verify_repair = arm_settings(cfg, "C")
        assert legacy.research_policy == "legacy"
        assert verify_repair.research_policy == "fixed_verify_repair"
        for name in ("enable_supervisor", "enable_verifier", "enable_query_refiner", "enable_checkpointing"):
            assert getattr(legacy, name) == getattr(verify_repair, name), (
                f"{name} must be equal or this test proves nothing"
            )

        # Warm the cache under the legacy binding, then ask under the
        # other one. Both compile through the module global, so the
        # binding is installed for each call exactly as a campaign
        # process would install it.
        original = workflow_module.settings
        try:
            workflow_module.settings = legacy  # type: ignore[misc]
            warm = sb.graph_shape(legacy)
            assert sb.graph_shape(legacy) is warm, "the second ask still pays nothing"
            workflow_module.settings = verify_repair  # type: ignore[misc]
            cold = sb.graph_shape(verify_repair)
        finally:
            workflow_module.settings = original  # type: ignore[misc]

        assert cold is not warm
        assert cold.digest != warm.digest
        assert {"verify", "repair"} <= set(cold.nodes)
        assert not {"verify", "repair"} & set(warm.nodes)

    def test_a_task_that_forbids_chargeable_work_is_never_admitted(self) -> None:
        """An approval id covers an amount; it does not overrule a TaskSpec.

        The gap: `_validate_policy_narrowing` compares the effective
        policy against the task's and so catches a run that *widens* a
        forbidden boundary, but nothing asked whether a task declaring
        `chargeable_work="forbidden"` was being admitted onto a
        chargeable plan at all. With a metered provider and an approval
        id present, admission returned `chargeable=True` against a task
        that forbids chargeable work — invariant 10's exact failure
        shape.
        """
        cfg = config(use_mock_data=False)
        spec = compile_research_intake(
            cfg,
            task_id="research-eval:forbidden-spend",
            query=QUERY,
            hitl_plan_review=False,
            supervisor=False,
        )
        boundary = spec.execution_limits.workflow_cost
        assert boundary.chargeable_work == "forbidden"
        assert boundary.workflow_spend_ceiling_usd == "0.000000"

        bundle = _bundle_of(spec)
        plan = AdmissionPlan(
            campaign_id="camp_forbidden-spend-test",
            stage="stage-0-qualification",
            provider="anthropic",
            resources=("provider_call",),
            task_policy=bundle,
            effective_policy=bundle,
            platform_workflow_cost_usd="0.000000",
            campaign_workflow_allocation_usd="0.000000",
            provider_workflow_cost_usd="0.000000",
            episode_budget=_zero_budget(spec),
            provider_metered=True,
            approval_id="approval_stage-0",
        )
        probe_calls: list[str] = []
        with pytest.raises(RunManifestError, match="forbids chargeable work"):
            resolve_admission(
                plan,
                verified_at="2026-09-05T00:00:00Z",
                approval_backend=FakeLocalApprovalBackend(),
                credential_probe=lambda: probe_calls.append("credential"),
            )
        assert probe_calls == [], "a credential was read on a forbidden-spend task"

    def test_a_campaign_episode_carries_the_campaigns_ceiling_not_a_shadow_zero(
        self,
    ) -> None:
        """W05's zero is right for a shadow and wrong for a campaign.

        `research_binding._execution_limits` hardcodes a zero, forbidden
        ceiling and says why: a shadow observation is never authority to
        spend. `campaign.episode` substitutes its own boundary rather
        than editing that module, so this asserts both halves — the
        shadow seal's ceiling is still zero, and a campaign episode's is
        the campaign's approved cap, carried all the way into the sealed
        manifest's admission ceilings.
        """
        cfg = config(use_mock_data=False)
        shadow_spec = compile_research_intake(
            cfg,
            task_id="research-eval:shadow-ceiling",
            query=QUERY,
            hitl_plan_review=False,
            supervisor=False,
        )
        assert shadow_spec.execution_limits.workflow_cost.chargeable_work == "forbidden"
        assert shadow_spec.execution_limits.workflow_cost.workflow_spend_ceiling_usd == (
            "0.000000"
        )

        chargeable, backend = _chargeable_plan(cfg)
        episode = next(item for item in chargeable.runnable if item.arm_id == "A")
        sealed = seal_campaign_episode(
            cfg,
            campaign=chargeable.manifest,
            episode=episode,
            task_spec=chargeable.task_spec_for(episode.case_id),
            graph=graph_shape_for("A", cfg),
            approval_backend=backend,
            credential_probe=lambda: None,
        )
        cap = chargeable.manifest.payload.protocol.episode_budget.workflow_cost_usd_max
        assert cap == "1.500000"
        limits = sealed.task_spec.execution_limits.workflow_cost
        assert limits.chargeable_work == "requires_external_approval"
        assert limits.workflow_spend_ceiling_usd == cap
        ceilings = sealed.manifest.payload.admission_resolution.input_workflow_ceilings
        assert ceilings.task_workflow_cost_usd == cap
        assert ceilings.approval_workflow_allocation_usd == cap
        assert sealed.manifest.payload.admission_resolution.resolved_workflow_cost_usd == cap
        assert sealed.chargeable is True
        assert sealed.manifest.payload.approval.status_at_seal is ApprovalStatus.APPROVED


# ---------------------------------------------------------------------------
# 2. The dry-run lock and the arm identities
# ---------------------------------------------------------------------------


class TestTheDryRunLocksTheWholeDevelopmentSuite:
    pytestmark = [pytest.mark.unit, pytest.mark.contract]

    def test_the_matrix_is_three_hundred_slots_of_which_sixty_are_excluded(
        self,
    ) -> None:
        cfg = config()
        cases = suite_case_ids()
        assert len(cases) == FULL_SUITE_CASES
        plan = plan_campaign(cfg, request(cfg), resolver=registry())
        report = dry_run(plan)

        assert report.expected_episode_count == EXPECTED_EPISODES
        assert report.planned_episode_count == PLANNED_EPISODES
        assert report.excluded_episode_count == EXCLUDED_EPISODES
        assert report.chargeable is False
        assert len(report.episodes) == EXPECTED_EPISODES
        assert {item.projected_cost_usd for item in report.episodes} == {"0.000000"}
        excluded = [item for item in report.episodes if item.status == "excluded"]
        assert {item.arm_id for item in excluded} == {"E"}
        assert {item.exclusion_reason for item in excluded} == {"arm_capability_missing"}

    def test_every_input_is_pinned_by_an_exact_revision_and_digest(self) -> None:
        cfg = config()
        plan = plan_campaign(cfg, request(cfg), resolver=registry())
        lock = plan.manifest.payload.lock
        kinds = {ref.kind for ref in lock.resolved_refs}
        assert {"task_set", "split_assignment", "rubric_set", "grader_profile", "label_set"} <= kinds
        for ref in (lock.suite_ref, *lock.resolved_refs, *lock.case_refs):
            assert ref.digest.startswith("sha256:")
            assert len(ref.revision.split(".")) == 3, ref.revision
            assert ref.revision != "latest"
        assert plan.manifest.payload.lock_digest.startswith("sha256:")
        assert plan.manifest.payload.protocol_digest.startswith("sha256:")

    def test_the_dry_run_initializes_no_provider_and_opens_no_socket(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The attestation, measured rather than declared.

        `DryRunPlan.provider_initialized` and `.network_calls` are
        pydantic literals — true by construction, which is a schema
        claim and not evidence. These spies are the evidence, and they
        are installed *over* the conftest guards so a passing run says
        the code path was never taken rather than that a guard caught it.
        """
        touched: list[str] = []
        monkeypatch.setattr(llm_module, "_get_client", lambda: touched.append("client"))
        monkeypatch.setattr(
            socket.socket, "connect", lambda *_a, **_k: touched.append("connect")
        )
        costs = start_cost_tracking()

        cfg = config()
        plan = plan_campaign(cfg, request(cfg), resolver=registry())
        report = dry_run(plan)

        assert touched == []
        assert report.provider_initialized is False
        assert report.network_calls == 0
        assert costs.total_cost_usd == 0.0
        assert costs.call_count == 0


class TestTheFiveArmIdentities:
    pytestmark = [pytest.mark.unit, pytest.mark.contract]

    def test_the_four_runnable_arms_seal_distinct_manifests_over_one_task(
        self,
    ) -> None:
        """Four arms, one task, four identities — the paired design's floor.

        Every arm is classified against the graph *this checkout
        compiles* for it, not a stand-in, so an arm whose implementation
        regressed would fail here rather than at the first funded
        episode.
        """
        cfg = config()
        plan = plan_campaign(
            cfg, request(cfg, cases=SLICE_CASES, repeats=1), resolver=registry()
        )
        case = SLICE_CASES[0]
        sealed = {}
        for arm in RUNNABLE_ARMS:
            episode = next(
                item
                for item in plan.runnable
                if item.arm_id == arm and item.case_id == case
            )
            sealed[arm] = seal_campaign_episode(
                cfg,
                campaign=plan.manifest,
                episode=episode,
                task_spec=plan.task_spec_for(case),
                graph=graph_shape_for(arm, cfg),
                approval_backend=LocalApprovalRecordBackend(),
                credential_probe=NoCredentialProbe(),
            )

        # Distinct where the experiment says they must differ.
        assert len({item.manifest_digest for item in sealed.values()}) == 4
        assert len({sha256_digest(item.policy) for item in sealed.values()}) == 4
        assert {arm: item.policy.arm_id for arm, item in sealed.items()} == {
            "A": "A",
            "B": "B",
            "C": "C",
            "D": "D",
        }
        assert {arm: item.policy.selector for arm, item in sealed.items()} == {
            "A": "fixed",
            "B": "fixed_evidence",
            "C": "fixed_verify_repair",
            "D": "supervisor_verified",
        }

        # Equal where the pairing says they must not.
        assert len({item.manifest.payload.task for item in sealed.values()}) == 1
        assert (
            len({item.manifest.payload.registry_resolution for item in sealed.values()})
            == 1
        )
        assert (
            len({item.manifest.payload.campaign_lock_ref for item in sealed.values()})
            == 1
        )
        assert (
            len({item.manifest.payload.identity.replicate_group_id for item in sealed.values()})
            == 4
        ), "one replicate group per arm; a repeat shares a group, an arm never does"

        # No arm is chargeable, and none read a credential: the probe
        # raises if it is ever called.
        assert not any(item.chargeable for item in sealed.values())

    def test_arm_c_is_the_compiled_stage_and_not_the_supervisors_flag(self) -> None:
        """`ENABLE_VERIFIER=true` under the fixed graph is still arm A.

        07 §3 records this as the defect that would have made arm C
        unmeasurable, and the classifier reads structure rather than the
        flag, so the impostor configuration is checked here against a
        real compiled graph rather than a hand-built shape.
        """
        cfg = config()
        arm_c = graph_shape_for("C", cfg)
        assert {"verify", "repair"} <= set(arm_c.nodes)
        assert "supervisor" not in arm_c.nodes and "verifier" not in arm_c.nodes

        impostor = shipped_settings.model_copy(
            update={
                "use_mock_data": True,
                "enable_checkpointing": False,
                "enable_supervisor": False,
                "enable_verifier": True,
                "research_policy": "legacy",
            }
        )
        assert isinstance(impostor, Settings)
        with compiled_under(impostor) as app:
            shape = read_graph_shape(app)
        assert not {"verify", "repair", "verifier"} & set(shape.nodes)
        with pytest.raises(CampaignError, match="not the declared arm C"):
            classify_arm(cfg, "C", shape)

    def test_arm_e_is_schema_valid_capability_missing_and_not_runnable(self) -> None:
        cfg = config()
        declared = declare_arm("E", graph=graph_shape_for("D", cfg))
        assert declared.status == "capability_missing"
        assert declared.runnable is False
        assert declared.missing_capabilities == ARM_REQUIRED_CAPABILITIES["E"]
        assert set(declared.missing_capabilities) == {
            "adaptive_compute_router",
            "candidate_branching",
            "marginal_stop",
            "candidate_lineage_selector",
        }
        # Schema-valid: it round-trips through its own model.
        assert declared.model_validate(declared.model_dump()) == declared

        plan = plan_campaign(
            cfg, request(cfg, cases=SLICE_CASES, repeats=1), resolver=registry()
        )
        excluded = [item for item in plan.episodes if item.arm_id == "E"]
        assert excluded and all(not item.runnable for item in excluded)
        with pytest.raises(CampaignError, match="capability_missing"):
            seal_campaign_episode(
                cfg,
                campaign=plan.manifest,
                episode=excluded[0],
                task_spec=plan.task_spec_for(excluded[0].case_id),
                graph=graph_shape_for("D", cfg),
                approval_backend=LocalApprovalRecordBackend(),
                credential_probe=NoCredentialProbe(),
            )

    def test_the_common_settings_are_frozen_and_the_differences_are_the_arm_table(
        self,
    ) -> None:
        """07 §4's frozen table, read from `Settings` rather than restated."""
        cfg = config()
        per_arm = {arm: arm_settings(cfg, arm) for arm in ARM_IDS}
        for name, value in COMMON_FROZEN_SETTINGS.items():
            assert {getattr(settings, name) for settings in per_arm.values()} == {value}, (
                f"{name} is a common frozen setting and differs between arms"
            )
        # And every other setting an arm owns is exactly the arm table's.
        difference_keys = set(ARM_SETTINGS["A"])
        for arm, settings in per_arm.items():
            assert {
                key: getattr(settings, key) for key in difference_keys
            } == dict(ARM_SETTINGS[arm])
        # The held-out factors and the safety floor are not arm differences.
        assert per_arm["A"].enable_prompt_isolation is True
        assert per_arm["A"].enable_query_refiner is False
        assert per_arm["A"].enable_reader_recovery is False


# ---------------------------------------------------------------------------
# 3. The synthetic episodes, through the real graph
# ---------------------------------------------------------------------------


class TestTheSyntheticEpisodes:
    pytestmark = pytest.mark.e2e

    @pytest.mark.parametrize("arm", RUNNABLE_ARMS)
    def test_each_runnable_identity_runs_end_to_end_and_reconstructs(
        self, arm: ArmId, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One episode per arm: real graph in, verified ledger out.

        The four claims, in the order the report makes them: the
        compiled graph really ran and took this arm's node route; the
        episode sealed a manifest before the ledger opened; the durable
        JSONL on disk verifies as a hash chain and reconstructs to the
        decisions and artifacts the run made; and the contract's view of
        the outcome agrees with the legacy record in every compared
        field.
        """
        cfg = arm_settings(config(), arm)
        _install(monkeypatch, cfg)
        costs = start_cost_tracking()

        visited, final = _drive_graph(cfg, run_id=f"stage0-{arm}")
        assert visited, "the graph produced no node updates"
        assert final["draft_report"], "the graph produced no report"
        if arm in ("A", "B"):
            assert visited == list(FIXED_PIPELINE)
        if arm == "C":
            assert "verify" in visited, "arm C must reach its verification stage"
        if arm == "D":
            assert visited[0] == "supervisor"
            assert "verifier" in visited, "arm D's router must reach its verifier"

        with compiled_under(cfg) as app:
            shape = sb.policy_shape_for_app(cfg, app)
        assert shape.arm_id == arm
        assert shape.representable is True

        spec = compile_research_intake(
            cfg,
            task_id=f"stage0-qualification:{arm}",
            query=QUERY,
            hitl_plan_review=False,
            supervisor=shape.runtime_flags.enable_supervisor,
        )
        episode = seal_research_episode(
            cfg,
            shape=shape,
            spec=spec,
            origin="research_eval",
            runtime_run_id=f"stage0-{arm}",
            hitl_bypass=True,
            hitl_bypass_reason="unattended-evaluation",
        )
        bridge = rb.start_research_run(
            cfg,
            episode=episode,
            runtime_run_id=f"stage0-{arm}",
            principal_key_id="synthetic:stage0-qualification",
            cost_ceiling_usd=0.0,
            sink_root=tmp_path / "sink",
        )
        artifact = _record_episode(bridge, visited, final)

        # The ledger on disk, read back with nothing from the live run.
        path = (
            tmp_path
            / "sink"
            / rb.SINK_RUN_DIRECTORY
            / bridge.run_id
            / rb.SINK_EVENTS_FILE
        )
        jsonl = path.read_text(encoding="utf-8")
        imported = import_jsonl(jsonl)
        verify_trajectory(imported)
        assert imported[0].event_type == "run.admitted"
        assert imported[-1].event_type == "budget.reconciled"

        sink = bridge.durable_store.sink
        assert isinstance(sink, rb.JsonlTrajectorySink)
        head = sink.head(bridge.run_id)
        assert head is not None
        assert head["head_event_hash"] == imported[-1].event_hash
        assert head["event_count"] == len(imported)

        reconstruction = rb.reconstruct_episode(jsonl, lane="research")
        assert reconstruction.terminal_event_type == "run.completed"
        assert [
            decision
            for decision in reconstruction.decisions
            if decision.startswith("action.completed")
        ] == [f"action.completed:{node}" for node in visited]
        assert reconstruction.artifacts
        assert bridge.artifacts is not None
        # Every artifact the ledger names is either promoted bytes or an
        # honest digest-only reference, and a digest-only one happens for
        # exactly one reason in this checkout: the artifact store's
        # private-reasoning screen refused the body. That refusal is a
        # real finding rather than a tolerated flake — see W11-F1 in
        # `docs/agent-engineering/15-stage0-qualification-report.md` and
        # `test_a_briefing_about_chain_of_thought_is_refused_storage`.
        for artifact_id in reconstruction.artifacts:
            if not bridge.artifacts.contains(artifact_id):
                assert PRIVATE_REASONING_FALSE_POSITIVE.search(final["draft_report"]), (
                    f"{artifact_id} was not stored and the report does not trip "
                    "the private-reasoning screen; this is a new failure"
                )

        legacy = LegacyOutcome(
            surface="eval_record",
            query=QUERY,
            status="succeeded",
            llm_calls=0,
            cost_usd="0.000000",
            report_digest=artifact.digest,
            task_spec_id=spec.task_spec_id,
            task_full_digest=episode.manifest.payload.task.full_digest,
        )
        assert sb.parity_report(bridge, legacy, final) == ()

        assert costs.total_cost_usd == 0.0
        assert costs.call_count == 0

    def test_arm_e_has_no_episode_to_run(self) -> None:
        """The refusal is typed, and it is not a graph that failed."""
        cfg = config()
        with pytest.raises(CampaignError, match="capability_missing"):
            classify_arm(cfg, "E", graph_shape_for("D", cfg))
        assert declare_arm("E").missing_capabilities == ARM_REQUIRED_CAPABILITIES["E"]


# ---------------------------------------------------------------------------
# 4. The candidate boundary
# ---------------------------------------------------------------------------


class TestTheCandidateRoleCannotReachEvaluationMaterial:
    pytestmark = [pytest.mark.unit, pytest.mark.security]

    @pytest.mark.parametrize("kind", ["label_set", "grader_profile", "split_assignment", "task_set"])
    def test_a_candidate_cannot_resolve_evaluator_only_objects(self, kind: str) -> None:
        cfg = config()
        plan = plan_campaign(
            cfg, request(cfg, cases=SLICE_CASES, repeats=1), resolver=registry()
        )
        refs = [ref for ref in plan.manifest.payload.lock.resolved_refs if ref.kind == kind]
        assert refs, f"the lock resolved no {kind} to test against"
        for ref in refs:
            with pytest.raises(RegistryAccessError):
                registry().resolve(
                    ref,
                    role=RegistryRole.CANDIDATE,
                    intended_use=IntendedUse.DEVELOPMENT,
                )

    def test_the_development_suite_cannot_claim_promotion_evidence(self) -> None:
        """RFC 11 §20 criterion 9, and the split this checkout actually has.

        Two facts, and the second is a gap the report states rather than
        a property it celebrates. The public 20-query suite refuses
        `promotion` use for every role, so no campaign over it can be
        read as sealed generalization evidence. And the only split the
        shipped registry declares is `development`: the limited-access
        validation set and the sealed canary set 07 §5 asks for before
        promotion do not exist yet, so the fail-closed behaviour for a
        restricted split is proved by W02's own synthetic fixture
        (`tests/test_eval_registry.py::test_restricted_splits_fail_
        closed_without_a_broker`) and not by anything in this tree.
        """
        for role in (RegistryRole.CANDIDATE, RegistryRole.EVALUATOR):
            with pytest.raises(RegistryResolutionError, match="promotion"):
                registry().resolve(
                    suite_ref(REGISTRY_ROOT, SUITE_ID),
                    role=role,
                    intended_use=IntendedUse.PROMOTION,
                )

        cfg = config()
        plan = plan_campaign(
            cfg, request(cfg, cases=SLICE_CASES, repeats=1), resolver=registry()
        )
        split_ref = next(
            ref
            for ref in plan.manifest.payload.lock.resolved_refs
            if ref.kind == "split_assignment"
        )
        split = registry().resolve(
            split_ref, role=RegistryRole.EVALUATOR, intended_use=IntendedUse.DEVELOPMENT
        ).payload
        assert split.split is SplitKind.DEVELOPMENT
        assert split.membership_visible_to_candidate is False

    def test_the_runtime_projection_carries_no_evaluator_material(self) -> None:
        """The one manifest view candidate policy code receives."""
        cfg = config()
        plan = plan_campaign(
            cfg, request(cfg, cases=SLICE_CASES, repeats=1), resolver=registry()
        )
        episode = next(item for item in plan.runnable if item.arm_id == "A")
        sealed = seal_campaign_episode(
            cfg,
            campaign=plan.manifest,
            episode=episode,
            task_spec=plan.task_spec_for(episode.case_id),
            graph=graph_shape_for("A", cfg),
            approval_backend=LocalApprovalRecordBackend(),
            credential_probe=NoCredentialProbe(),
        )
        rendered = canonical_json(sealed.projection)
        for forbidden in (
            "label_set_refs",
            "grader_profile_refs",
            "split_assignment_ref",
            "registry_resolution",
            "approval",
            "campaign_lock_locator",
            "credential",
        ):
            assert forbidden not in rendered, f"{forbidden} reached the candidate"
        excluded = sealed.manifest.payload.policy_runtime_projection.excluded_classes
        assert set(excluded) == {
            "sealed-case-and-split-identity",
            "evaluator-and-label-refs",
            "approval-metadata",
            "private-object-locators",
            "hidden-rubric-content",
        }

    def test_a_briefing_about_chain_of_thought_is_refused_storage(
        self, tmp_path: Path
    ) -> None:
        """W11-F1, pinned as behaviour rather than left as a surprise.

        The artifact store screens text bodies for private reasoning with
        a substring rule, and `chain-of-thought` is one of its patterns.
        A research briefing whose subject *is* chain-of-thought prompting
        therefore has its bytes refused: the run continues, the candidate
        is recorded digest-only, and a WARNING says which rule fired.

        Graceful, and still a hole a funded campaign would notice —
        `research-policy-v1` is a suite of LLM-research questions, so the
        artifacts this loses are correlated with the benchmark's own
        subject matter rather than randomly distributed. Fixing the rule
        is outside this work order's fences; recording it here is what
        stops it being discovered from a gap in Stage 3's artifact set.
        """
        from src.contracts.artifact_store import ArtifactRefused, LocalArtifactStore
        from src.contracts.kernel import DataClass
        from src.contracts.research_binding import retention_policy_ref
        from src.contracts.trajectory import TrustClass

        store = LocalArtifactStore(
            tmp_path / "artifacts", scope_data_class=DataClass.INTERNAL
        )
        text = (
            "# Briefing\n\nGeneration-time mitigations include "
            "retrieval-augmented generation and chain-of-thought prompting.\n"
        )
        assert PRIVATE_REASONING_FALSE_POSITIVE.search(text)
        with pytest.raises(ArtifactRefused, match="private reasoning"):
            store.put(
                text.encode("utf-8"),
                role=ArtifactRole.CANDIDATE_REPORT,
                media_type="text/markdown",
                schema_ref="research-report/1.0.0",
                trust_class=TrustClass.SYSTEM_GENERATED,
                data_class=DataClass.INTERNAL,
                retention_policy_ref=retention_policy_ref(),
                principal_key_id="pk_stage0qualifica",
            )
        assert [path for path in store.root.rglob("*") if path.is_file()] == [], (
            "a refused body must not be persisted for debugging"
        )

    def test_no_event_a_synthetic_episode_produces_is_training_eligible(
        self, tmp_path: Path
    ) -> None:
        cfg = config()
        with compiled_under(arm_settings(cfg, "A")) as app:
            shape = sb.policy_shape_for_app(arm_settings(cfg, "A"), app)
        spec = compile_research_intake(
            cfg,
            task_id="stage0-qualification:governance",
            query=QUERY,
            hitl_plan_review=False,
            supervisor=False,
        )
        episode = seal_research_episode(
            cfg,
            shape=shape,
            spec=spec,
            origin="research_eval",
            runtime_run_id="stage0-governance",
            hitl_bypass=True,
            hitl_bypass_reason="unattended-evaluation",
        )
        bridge = rb.start_research_run(
            cfg,
            episode=episode,
            runtime_run_id="stage0-governance",
            principal_key_id="synthetic:stage0-qualification",
            cost_ceiling_usd=0.0,
            sink_root=tmp_path / "sink",
        )
        _record_episode(bridge, list(FIXED_PIPELINE), {"draft_report": "# Briefing\n"})
        events = bridge.events()
        assert events
        assert all(event.data_governance.training_eligible is False for event in events)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _bundle_of(spec: Any) -> Any:
    from src.contracts.task_spec import TaskPolicyBundle

    return TaskPolicyBundle(
        source_scope=spec.source_scope,
        freshness=spec.freshness,
        tool_policy=spec.tool_policy,
        execution_limits=spec.execution_limits,
        autonomy=spec.autonomy,
        data_policy=spec.data_policy,
    )


def _zero_budget(spec: Any) -> Any:
    from src.contracts.research_binding import episode_budget

    return episode_budget(spec)


def _chargeable_plan(cfg: Settings) -> tuple[Any, LocalApprovalRecordBackend]:
    """A campaign whose approval really does cover a metered episode."""
    from src.campaign.approval import campaign_approval_record
    from src.campaign.manifest import CampaignBudget, EpisodeBudget

    base = default_episode_budget(cfg, ARM_IDS)
    episode = base.model_copy(
        update={
            "workflow_cost_usd_max": "1.500000",
            "judge_cost_usd_max": "0.500000",
            "total_cost_usd_max": "2.000000",
        }
    )
    assert isinstance(episode, EpisodeBudget)
    campaign = default_campaign_budget("20.000000")
    assert isinstance(campaign, CampaignBudget)
    plan = plan_campaign(
        cfg,
        request(cfg, cases=SLICE_CASES, repeats=1).model_copy(
            update={
                "approval_id": "approval_stage-1-smoke",
                "episode_budget": episode,
                "campaign_budget": campaign,
                # A metered provider is a live-corpus run in this
                # checkout: `use_mock_data=False` is what makes the
                # provider Anthropic, and it is also what makes the
                # source scope live. Declaring `snapshot` here would be
                # a campaign whose own seal refuses it.
                "corpus_mode": "live",
            }
        ),
        resolver=registry(),
    )
    backend = LocalApprovalRecordBackend(
        [
            campaign_approval_record(
                approval_id="approval_stage-1-smoke",
                campaign_id=plan.campaign_id,
                stage="stage-0-qualification",
                provider="anthropic",
                resources=("provider_call",),
                total_cost_usd_max="20.000000",
                episode_allocation_usd_max="2.000000",
                workflow_allocation_usd_max="1.500000",
                judge_allocation_usd_max="0.500000",
                approved_by="stage-0-qualification-fixture",
                approved_at="2026-09-01T00:00:00Z",
                expires_at="2026-12-01T00:00:00Z",
            )
        ]
    )
    return plan, backend


def _install(monkeypatch: pytest.MonkeyPatch, cfg: Settings) -> None:
    """Bind one configuration across every module the graph reads.

    Settings are read per module, not per process, so a module left out
    keeps the shipped default — a silent half-override rather than an
    error. The ranker is pinned to identity for the reason every other
    tier pins it: it loads a local MiniLM checkpoint, not a model call,
    and the five fixture papers already fit under `max_papers`.
    """
    for module in SETTINGS_CONSUMERS:
        monkeypatch.setattr(module, "settings", cfg)
    monkeypatch.setattr(
        m_search, "rank_papers_by_relevance", lambda query, papers, top_k: list(papers)[:top_k]
    )
    if cfg.enable_supervisor:
        monkeypatch.setattr(m_supervisor, "call_llm_json", _scripted_supervisor())


def _scripted_supervisor() -> Callable[..., dict[str, Any]]:
    """Arm D's routing decisions, from a fixture rather than a model.

    CAP-07 gave every research agent a deterministic mock branch and did
    not give one to the supervisor, so under mock mode the router's call
    fails and `_fall_back` routes in fixed pipeline order. That run
    finishes, but its trajectory would record a *degraded* route as a
    decided one — which is exactly the misrepresentation this work order
    exists to prevent. Scripting the judge keeps arm D's episode an
    honest supervisor route and puts the gap in the report instead.
    """
    turns = {"n": 0}

    def _call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        index = min(turns["n"], len(SCRIPTED_SUPERVISOR_ROUTE) - 1)
        turns["n"] += 1
        action = SCRIPTED_SUPERVISOR_ROUTE[index]
        return {
            "next_action": action,
            "reason": "stage-0 qualification fixture",
            "stop_reason": "qualification_complete" if action == "stop" else "",
        }

    return _call


def _drive_graph(cfg: Settings, *, run_id: str) -> tuple[list[str], dict[str, Any]]:
    """Run the real compiled graph to completion, recording its route."""
    visited: list[str] = []
    final: dict[str, Any] = {}
    with compiled_under(cfg) as app:
        for mode, payload in app.stream(
            initial_research_state(QUERY, run_id), stream_mode=["updates", "values"]
        ):
            if mode == "values":
                final = dict(payload)
                continue
            visited.extend(node for node in payload if node != "__interrupt__")
    return visited, final


def _record_episode(
    bridge: rb.ResearchRuntimeBridge, visited: Sequence[str], final: dict[str, Any]
) -> Any:
    """Record the run the graph just took onto the contract ledger."""
    for index, node in enumerate(visited, start=1):
        bridge.node_step(node, step=index)
    artifact = bridge.record_candidate(str(final.get("draft_report") or "# Briefing\n"))
    candidate_id = bridge._candidate_id
    assert candidate_id is not None
    verification_ids: tuple[str, ...] = ()
    verdict = final.get("verification_verdict")
    if verdict:
        bridge.verification(
            check_id="stage0-verify",
            candidate_id=candidate_id,
            verdict="pass" if verdict == "pass" else "abstain",
        )
        verification_ids = tuple(
            event.event_id
            for event in bridge.events()
            if event.event_type == "verification.completed"
        )
    bridge.finalize(
        candidate_id=candidate_id,
        artifact=artifact.model_copy(update={"role": ArtifactRole.CANDIDATE_REPORT}),
        selection_basis="single_candidate",
        verification_event_ids=verification_ids,
    )
    bridge.reconcile(0.0)
    bridge.close()
    return artifact
