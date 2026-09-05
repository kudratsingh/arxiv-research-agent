"""No-cost qualification for the research contract binding (P0-WO05).

Everything here runs against a *stand-in* graph rather than a compiled
one. That is not a shortcut: the claim the binding makes is that policy
identity is read from a graph's structure, so a test that hands it three
different structures and checks the three answers is testing exactly the
thing, and it does it without opening a checkpointer. The compiled
graph's real shape is asserted separately, in the e2e tier, where the
graph is actually built.

Nothing in this module touches the network, a provider, or a model. The
one thing it does read from disk is the repository's own source, which
is what a code-subtree digest is.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts.kernel import DataClass, sha256_digest
from src.contracts.research_binding import (
    ARM_POLICY_IDS,
    ARM_REQUIRED_CAPABILITIES,
    CAPABILITY_MISSING_POLICY_ID,
    HELD_OUT_FACTORS,
    LOCATOR_SETTINGS_FIELDS,
    BenchmarkBinding,
    ContractOutcome,
    LegacyOutcome,
    PolicyShape,
    ResearchBindingError,
    arm_capability_gap,
    classify_policy_shape,
    code_snapshot,
    compare_outcomes,
    compare_research_state,
    compile_eval_case,
    compile_research_intake,
    environment_snapshot,
    excluded_settings_fields,
    model_routes,
    policy_snapshot,
    prompt_digests,
    provider_snapshot,
    read_graph_shape,
    seal_research_episode,
    settings_schema_digest,
    settings_snapshot,
)
from src.contracts.run_manifest import RunManifestV1, build_policy_runtime_projection
from src.contracts.task_spec import ProductSurface, TaskKind

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# A graph stand-in, shaped like LangGraph's drawable projection
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
    """Everything `read_graph_shape` is allowed to touch, and nothing else."""

    def __init__(self, nodes: list[str], edges: list[_Edge]) -> None:
        self._graph = _Graph(nodes, edges)

    def get_graph(self) -> _Graph:
        return self._graph


FIXED_NODES = ["planner", "search", "reader", "synthesizer", "critic"]
FIXED_EDGES = [
    _Edge("__start__", "planner"),
    _Edge("planner", "search"),
    _Edge("search", "reader"),
    _Edge("reader", "synthesizer"),
    _Edge("synthesizer", "critic"),
    _Edge("critic", "__end__", conditional=True),
    _Edge("critic", "planner", conditional=True),
]


def fixed_app(*, extra_nodes: tuple[str, ...] = ()) -> _AppStub:
    return _AppStub(
        [*FIXED_NODES, *extra_nodes, "__start__", "__end__"], list(FIXED_EDGES)
    )


def verify_repair_app() -> _AppStub:
    """The fixed pipeline with CAP-02's verify-and-repair stage compiled in.

    A stand-in rather than a compiled graph because the classification is
    structural: what makes a run arm C is that a `verify` node and a
    `repair` node exist downstream of synthesis, and a test that says so
    is testing the rule rather than the wiring that happens to satisfy it
    this week.
    """
    nodes = [*FIXED_NODES, "verify", "repair", "__start__", "__end__"]
    edges = [
        *FIXED_EDGES,
        _Edge("critic", "verify"),
        _Edge("verify", "repair", conditional=True),
        _Edge("verify", "__end__", conditional=True),
        _Edge("repair", "verify"),
    ]
    return _AppStub(nodes, edges)


def supervisor_app(*, verifier: bool = True, refiner: bool = False) -> _AppStub:
    nodes = [*FIXED_NODES, "supervisor", "__start__", "__end__"]
    if verifier:
        nodes.append("verifier")
    if refiner:
        nodes.append("query_refiner")
    edges = [
        _Edge("__start__", "supervisor"),
        *(_Edge("supervisor", node, conditional=True) for node in FIXED_NODES),
        *(_Edge(node, "supervisor") for node in FIXED_NODES),
        _Edge("supervisor", "__end__", conditional=True),
    ]
    return _AppStub(nodes, edges)


def config(**overrides: Any) -> Settings:
    """The shipped settings with a mock, no-cost research surface on top."""
    base = {
        "use_mock_data": True,
        "enable_tracing": False,
        "enable_metrics": False,
        "enable_semantic_scholar": False,
        "enable_checkpointing": False,
        "contract_shadow": "shadow",
    }
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


def seal(cfg: Settings, app: _AppStub, *, query: str = "why do LLMs hallucinate?") -> Any:
    shape = classify_policy_shape(cfg, app)
    spec = compile_research_intake(
        cfg,
        task_id="research-api:job-1",
        query=query,
        hitl_plan_review=False,
        supervisor=shape.runtime_flags.enable_supervisor,
    )
    return seal_research_episode(
        cfg,
        shape=shape,
        spec=spec,
        origin="research_api",
        runtime_run_id="job-1",
        hitl_bypass=True,
        hitl_bypass_reason="client-requested-bypass",
    )


# ---------------------------------------------------------------------------
# Secrets and locators
# ---------------------------------------------------------------------------


class TestTheSnapshotCannotCarryASecret:
    def test_no_module_in_the_contracts_package_unwraps_a_secret(self) -> None:
        """`get_secret_value()` appears nowhere under `src/contracts/`.

        A grep rather than a behavioural assertion on purpose. The rule
        is "this package never unwraps a credential", and the only way
        to hold a package to that is to check that the one call which
        could is absent — a test that unwrapped a secret to prove it did
        not would be its own counterexample.
        """
        offenders: list[str] = []
        for path in sorted(Path("src/contracts").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if any(
                isinstance(node, ast.Attribute) and node.attr == "get_secret_value"
                for node in ast.walk(tree)
            ):
                offenders.append(path.name)
        assert offenders == []

    def test_secret_fields_are_excluded_by_type_and_locators_by_name(self) -> None:
        cfg = config()
        snapshot = settings_snapshot(cfg)
        excluded = excluded_settings_fields(cfg)

        # Every `SecretStr` field, whatever it is called.
        secrets = {
            name
            for name in type(cfg).model_fields
            if type(getattr(cfg, name)).__name__ == "SecretStr"
        }
        assert secrets, "the fixture is worthless if no field is a SecretStr"
        assert secrets <= set(excluded)
        assert secrets.isdisjoint(snapshot)
        assert set(excluded) >= LOCATOR_SETTINGS_FIELDS
        assert LOCATOR_SETTINGS_FIELDS.isdisjoint(snapshot)

        # The masked rendering must not have leaked in either.
        assert "**********" not in repr(snapshot)

    def test_a_field_the_manifest_rule_refuses_is_dropped_not_renamed(self) -> None:
        """`api_key_hourly_limit` holds a rate limit and no secret at all.

        It is excluded anyway, because the manifest's own forbidden-key
        rule reads `_api_key_` in the name — and the binding delegates to
        that rule instead of keeping a second copy that could disagree
        with it at seal time.
        """
        cfg = config()
        assert "api_key_hourly_limit" in excluded_settings_fields(cfg)
        assert "api_key_hourly_limit" not in settings_snapshot(cfg)

    def test_a_private_checkout_path_never_reaches_a_sealed_manifest(
        self, tmp_path: Path
    ) -> None:
        """A developer's checkpoint path is a locator, so it is excluded.

        Without the exclusion this seal would fail on a developer's
        machine and pass in CI, which is the worst shape a validation
        rule can have.
        """
        cfg = config(
            enable_checkpointing=True,
            checkpoint_backend="sqlite",
            checkpoint_db_path=str(tmp_path / "shadow.sqlite"),
        )
        episode = seal(cfg, fixed_app())
        encoded = episode.manifest.model_dump_json()
        assert str(tmp_path) not in encoded
        assert "checkpoint_db_path" not in encoded

    def test_the_schema_digest_moves_when_the_exclusion_set_moves(self) -> None:
        cfg = config()
        assert settings_schema_digest(cfg) == settings_schema_digest(config())
        # A value change moves the *value* digest, not the schema digest.
        louder = config(max_papers=cfg.max_papers + 1)
        assert settings_schema_digest(louder) == settings_schema_digest(cfg)
        assert settings_snapshot(louder) != settings_snapshot(cfg)


# ---------------------------------------------------------------------------
# Arm identity
# ---------------------------------------------------------------------------


class TestArmIdentityIsReadFromTheGraph:
    def test_a_b_and_d_are_three_manifests_with_three_policy_ids(self) -> None:
        """The acceptance criterion, stated as a test.

        Three configurations, no live model, three distinct sealed
        manifests and three distinct policy ids. A binding that read only
        the flags would still pass this; the impostor test below is the
        one that separates them.
        """
        arm_a = seal(config(), fixed_app())
        arm_b = seal(config(enable_evidence_store=True), fixed_app())
        arm_d = seal(
            config(
                enable_supervisor=True, enable_evidence_store=True, enable_verifier=True
            ),
            supervisor_app(),
        )

        assert [episode.shape.arm_id for episode in (arm_a, arm_b, arm_d)] == ["A", "B", "D"]
        assert [episode.shape.policy_id for episode in (arm_a, arm_b, arm_d)] == [
            ARM_POLICY_IDS["A"],
            ARM_POLICY_IDS["B"],
            ARM_POLICY_IDS["D"],
        ]
        digests = {episode.manifest_digest for episode in (arm_a, arm_b, arm_d)}
        assert len(digests) == 3
        policy_digests = {sha256_digest(episode.policy) for episode in (arm_a, arm_b, arm_d)}
        assert len(policy_digests) == 3

    def test_enable_verifier_under_the_fixed_graph_is_arm_a_not_arm_c(self) -> None:
        """`ENABLE_VERIFIER=true` on the fixed pipeline is a no-op.

        `_build_supervisor_loop` is the only place a `verifier` node is
        registered, so the flag adds nothing to the fixed graph — and a
        classification that believed the flag would mint an arm-C claim
        out of a configuration that cannot verify anything. The impostor
        must land on A.
        """
        impostor = classify_policy_shape(config(enable_verifier=True), fixed_app())
        assert impostor.arm_id == "A"
        assert impostor.policy_id == ARM_POLICY_IDS["A"]
        assert impostor.runtime_flags.enable_verifier is False

        honest = classify_policy_shape(config(), fixed_app())
        assert honest.policy_digest == impostor.policy_digest, (
            "a no-op flag must not even move the policy digest"
        )

    def test_a_compiled_verify_repair_stage_is_arm_c(self) -> None:
        """CAP-02's stage, once compiled, earns arm C — and only then.

        Arm C is the arm the work order is most careful about, because it
        is the one a flag could be mistaken for. The rule is that the
        graph must carry both halves of the stage *and* the evidence
        store must be on, which is exactly what the contract's own arm-C
        validator demands of the snapshot this produces.
        """
        shape = classify_policy_shape(
            config(enable_evidence_store=True), verify_repair_app()
        )
        assert shape.arm_id == "C"
        assert shape.selector == "fixed_verify_repair"
        assert shape.policy_id == ARM_POLICY_IDS["C"]
        assert arm_capability_gap("C", shape) == ()
        assert arm_capability_gap("E", shape) == ARM_REQUIRED_CAPABILITIES["E"]

        snapshot = policy_snapshot(shape)
        assert snapshot.arm_id == "C"
        assert snapshot.capabilities.fixed_post_synthesis_verifier is True
        assert snapshot.config.max_targeted_repairs == 1
        assert snapshot.config.reverify_repaired_subject is True
        assert snapshot.capabilities.adaptive_compute is False

    def test_the_verify_stage_without_the_evidence_store_is_not_arm_c(self) -> None:
        """The evidence store is arm C's other half, and it has no node.

        Compiling the stage while the store is off is a configuration
        nobody designed, so it is named rather than rounded to B.
        """
        shape = classify_policy_shape(config(), verify_repair_app())
        assert shape.arm_id is None
        assert shape.missing_capabilities == ("evidence_store",)
        assert arm_capability_gap("C", shape) == ()

    def test_a_declared_policy_without_the_stage_is_capability_missing(self) -> None:
        """Naming `fixed_verify_repair` in settings does not create it.

        This is the acceptance criterion in its sharpest form: a claim is
        not a capability, and the classification reads the graph.
        """

        class _Claiming:
            def __init__(self, base: Settings) -> None:
                self._base = base
                self.research_policy = "fixed_verify_repair"

            def __getattr__(self, name: str) -> Any:
                return getattr(self._base, name)

        claiming: Any = _Claiming(config(enable_evidence_store=True))
        shape = classify_policy_shape(claiming, fixed_app())
        assert shape.declared_research_policy == "fixed_verify_repair"
        assert shape.arm_id == "B", "the graph, not the claim, decides"
        assert arm_capability_gap("C", shape) == ARM_REQUIRED_CAPABILITIES["C"]

    def test_arms_c_and_e_name_what_this_repository_does_not_build(self) -> None:
        for shape in (
            classify_policy_shape(config(enable_verifier=True), fixed_app()),
            classify_policy_shape(
                config(
                    enable_supervisor=True,
                    enable_evidence_store=True,
                    enable_verifier=True,
                ),
                supervisor_app(),
            ),
        ):
            assert arm_capability_gap("C", shape) == ARM_REQUIRED_CAPABILITIES["C"]
            assert arm_capability_gap("E", shape) == ARM_REQUIRED_CAPABILITIES["E"]

    def test_a_policy_snapshot_never_claims_the_capabilities_c_and_e_need(self) -> None:
        for cfg, app in (
            (config(), fixed_app()),
            (config(enable_evidence_store=True), fixed_app()),
            (
                config(
                    enable_supervisor=True,
                    enable_evidence_store=True,
                    enable_verifier=True,
                ),
                supervisor_app(),
            ),
        ):
            snapshot = policy_snapshot(classify_policy_shape(cfg, app))
            assert snapshot.capabilities.fixed_post_synthesis_verifier is False
            assert snapshot.capabilities.adaptive_compute is False
            assert "fixed_post_synthesis_verifier" not in snapshot.graph_capabilities
            assert set(snapshot.graph_capabilities).isdisjoint(ARM_REQUIRED_CAPABILITIES["E"])

    def test_the_refiner_and_reader_recovery_flip_no_arm_id(self) -> None:
        """Both stay independent held-out factors, as RFC 09 §7.2 requires.

        They move the *policy digest*, because the refiner adds a node
        and both change how the run behaves — a manifest that hid that
        would be lying about the configuration. What they must not do is
        move the arm.
        """
        base = config(
            enable_supervisor=True, enable_evidence_store=True, enable_verifier=True
        )
        plain = classify_policy_shape(base, supervisor_app())
        refined = classify_policy_shape(
            base.model_copy(update={"enable_query_refiner": True}),
            supervisor_app(refiner=True),
        )
        recovered = classify_policy_shape(
            base.model_copy(update={"enable_reader_recovery": True}), supervisor_app()
        )

        assert plain.arm_id == refined.arm_id == recovered.arm_id == "D"
        assert plain.policy_id == refined.policy_id == recovered.policy_id
        assert len({plain.policy_digest, refined.policy_digest, recovered.policy_digest}) == 3
        assert set(plain.held_out_factors) == set(HELD_OUT_FACTORS)

    def test_a_configuration_nobody_designed_is_named_rather_than_rounded_down(
        self,
    ) -> None:
        """A supervisor with no evidence store and no verifier is not arm A.

        Rounding it down to the nearest arm would put a run nobody
        designed into a comparison as though it were one that was.
        """
        shape = classify_policy_shape(
            config(enable_supervisor=True), supervisor_app(verifier=False)
        )
        assert shape.arm_id is None
        assert shape.representable is False
        assert shape.policy_id == CAPABILITY_MISSING_POLICY_ID
        assert shape.missing_capabilities

        with pytest.raises(ResearchBindingError, match="not a representable arm"):
            policy_snapshot(shape)

    def test_a_declared_research_policy_is_read_when_one_exists(self) -> None:
        """The concurrent `research_policy` field, read without depending on it."""
        assert classify_policy_shape(config(), fixed_app()).declared_research_policy == "legacy"

        class _Declared:
            """A settings-shaped object that already has the field."""

            def __init__(self, base: Settings) -> None:
                self._base = base
                self.research_policy = "fixed_verify_repair"

            def __getattr__(self, name: str) -> Any:
                return getattr(self._base, name)

        declared: Any = _Declared(config())
        assert (
            classify_policy_shape(declared, fixed_app()).declared_research_policy
            == "fixed_verify_repair"
        )

    def test_an_unreadable_graph_refuses_rather_than_guessing(self) -> None:
        class _Broken:
            def get_graph(self) -> Any:
                raise RuntimeError("no graph here")

        with pytest.raises(ResearchBindingError, match="unreadable"):
            read_graph_shape(_Broken())


# ---------------------------------------------------------------------------
# Sealing
# ---------------------------------------------------------------------------


class TestSealingIsCompleteOrRefused:
    def test_a_sealed_manifest_binds_the_task_the_projection_and_the_code(self) -> None:
        episode = seal(config(), fixed_app())
        payload = episode.manifest.payload

        assert episode.manifest.integrity.payload_sha256 == sha256_digest(payload)
        assert payload.task.task_spec_id == episode.task_spec.task_spec_id
        assert payload.compilation.occurred_before_run_events is True
        assert payload.approval.required is False
        assert payload.budgets.episode.total_cost_usd_max == "0.000000"
        assert payload.providers.llm.metered is False
        assert payload.code.commit_sha == code_snapshot().commit_sha
        assert payload.prompts.raw_rendered_prompts_in_manifest is False

        # The candidate-safe projection derives and its digest is the one
        # the manifest claimed.
        projection = build_policy_runtime_projection(episode.manifest, episode.task_spec)
        assert (
            projection.integrity.payload_sha256
            == payload.policy_runtime_projection.artifact_ref.digest
        )
        encoded = projection.model_dump_json()
        for forbidden in ("registry_resolution", "approval", "pricing", "credential"):
            assert forbidden not in encoded

    def test_the_same_job_seals_to_the_same_digest_twice(self) -> None:
        cfg = config()
        first = seal(cfg, fixed_app())
        shape = classify_policy_shape(cfg, fixed_app())
        second = seal_research_episode(
            cfg,
            shape=shape,
            spec=first.task_spec,
            origin="research_api",
            runtime_run_id="job-1",
            hitl_bypass=True,
            hitl_bypass_reason="client-requested-bypass",
            sealed_at=first.manifest.payload.identity.created_at,
        )
        assert second.manifest_digest == first.manifest_digest
        assert second.run_id == first.run_id

    def test_a_metered_provider_fails_admission_closed(self) -> None:
        """Possessing a credential is not authority to spend.

        Off mock mode the provider is Anthropic and it bills per token,
        so the manifest says `metered=True`, admission demands an
        external approval this work order does not have, and the seal
        refuses. That refusal is the design: a shadow that sealed here
        would be a manifest claiming a metered provider was free.
        """
        with pytest.raises(ResearchBindingError, match="failed closed"):
            seal(config(use_mock_data=False), fixed_app())

        provider = provider_snapshot(config(use_mock_data=False)).llm
        assert provider.provider == "anthropic"
        assert provider.metered is True
        assert provider.credential.value_recorded is False
        assert provider.credential.fingerprint_recorded is False

    def test_a_tampered_manifest_no_longer_validates(self) -> None:
        episode = seal(config(), fixed_app())
        raw = episode.manifest.model_dump(mode="python")
        raw["payload"]["identity"]["created_by"] = "somebody-else"
        with pytest.raises(ValueError, match="digest mismatch"):
            RunManifestV1.model_validate(raw)

    def test_the_prompt_bundle_is_digests_and_never_text(self) -> None:
        digests = prompt_digests()
        assert len(digests) >= 9
        assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in digests.values())

        episode = seal(config(), fixed_app())
        encoded = episode.manifest.model_dump_json()
        from src.agents.planner import SYSTEM_PROMPT

        assert SYSTEM_PROMPT[:60] not in encoded

    def test_every_routed_model_is_named_including_the_inherited_ones(self) -> None:
        cfg = config(planner_model="claude-haiku-4-5")
        routes = model_routes(cfg)
        assert routes["planner"] == "claude-haiku-4-5"
        assert routes["critic"] == cfg.anthropic_model
        assert routes["default"] == cfg.anthropic_model
        assert "" not in routes.values()

    def test_the_environment_snapshot_survives_an_unreadable_locale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import locale as locale_module

        environment_snapshot.cache_clear()
        monkeypatch.setattr(
            locale_module,
            "getlocale",
            lambda *_a, **_k: (_ for _ in ()).throw(ValueError("no locale")),
        )
        snapshot = environment_snapshot("local-test")
        assert snapshot.locale == "unset"
        environment_snapshot.cache_clear()

    def test_the_sampling_snapshot_survives_a_renamed_signature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A `call_llm` that stops naming `max_tokens` leaves the default."""
        from src import llm as llm_module
        from src.contracts import research_binding

        monkeypatch.setattr(llm_module, "call_llm", lambda prompt: "")
        sampling = research_binding._sampling_snapshot()
        assert sampling.maximum_output_tokens == 4096


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


class TestCompilationIsDeterministicAndVerbatim:
    def test_the_api_objective_is_the_submitted_query_unchanged(self) -> None:
        query = "Which retrieval strategies reduce hallucination, and by how much?"
        spec = compile_research_intake(
            config(),
            task_id="research-api:job-9",
            query=query,
            hitl_plan_review=True,
            supervisor=False,
        )
        assert spec.objective == query
        assert spec.product_surface is ProductSurface.RESEARCH_API
        assert spec.task_kind is TaskKind.RESEARCH_FOCUSED_EVIDENCE_REVIEW
        assert spec.benchmark_origin is None
        assert spec.data_policy.data_class is DataClass.USER_CONFIDENTIAL
        assert spec.execution_limits.workflow_cost.chargeable_work == "forbidden"
        assert [item.kind for item in spec.autonomy.human_checkpoints] == ["plan_review"]

    def test_the_same_intake_compiles_to_the_same_immutable_id(self) -> None:
        first = compile_research_intake(
            config(),
            task_id="research-api:stable",
            query="a stable question",
            hitl_plan_review=False,
            supervisor=False,
            compiled_at="2026-09-05T08:00:00.000000Z",
        )
        second = compile_research_intake(
            config(),
            task_id="research-api:stable",
            query="a stable question",
            hitl_plan_review=False,
            supervisor=False,
            compiled_at="2026-09-05T08:00:00.000000Z",
        )
        assert first.task_spec_id == second.task_spec_id

    def test_an_eval_case_carries_its_benchmark_origin(self) -> None:
        binding = BenchmarkBinding(
            suite_id="research-benchmark",
            task_set_id="research-benchmark-queries",
            case_id="hallucination-mitigation",
            dataset_version="research-benchmark@20:abcdef123456",
            case_material={"query_id": "hallucination-mitigation", "domain": "nlp"},
            rubric_versions={"groundedness": "1.0.0"},
            judge_model="claude-sonnet-4-6",
        )
        spec = compile_eval_case(
            config(),
            binding,
            task_id="research-eval:hallucination-mitigation",
            objective="What reduces hallucination?",
            supervisor=False,
        )
        assert spec.product_surface is ProductSurface.RESEARCH_EVAL
        assert spec.benchmark_origin is not None
        assert spec.benchmark_origin.task_case_ref.id == "hallucination-mitigation"
        assert spec.data_policy.data_class is DataClass.INTERNAL

        resolution = binding.resolution()
        assert resolution.split_assignment_ref.id.startswith("shadow-unresolved-")
        assert resolution.validation_receipt_ref.revision == "0.0.0"


# ---------------------------------------------------------------------------
# Parity diagnostics
# ---------------------------------------------------------------------------


def _outcome_pair() -> tuple[LegacyOutcome, ContractOutcome]:
    digest = "sha256:" + "b" * 64
    legacy = LegacyOutcome(
        surface="job",
        query="a question",
        status="succeeded",
        llm_calls=3,
        cost_usd="0.250000",
        report_digest=digest,
    )
    contract = ContractOutcome(
        task_spec_id="tsp_" + "1" * 20,
        task_full_digest="sha256:" + "c" * 64,
        objective="a question",
        manifest_digest="sha256:" + "d" * 64,
        arm_id="A",
        policy_id="research_fixed",
        terminal_event_type="run.completed",
        llm_calls=3,
        cost_usd="0.250000",
        final_artifact_digest=digest,
    )
    return legacy, contract


class TestParityDiagnostics:
    def test_agreeing_records_produce_no_mismatch(self) -> None:
        legacy, contract = _outcome_pair()
        assert compare_outcomes(legacy, contract) == ()

    @pytest.mark.parametrize(
        ("field", "update", "expected"),
        [
            ("objective", {"objective": "a different question"}, "objective"),
            ("terminal", {"terminal_event_type": "run.failed"}, "terminal_event_type"),
            ("calls", {"llm_calls": 4}, "llm_calls"),
            ("cost", {"cost_usd": "0.500000"}, "cost_usd"),
            (
                "artifact",
                {"final_artifact_digest": "sha256:" + "e" * 64},
                "final_artifact_digest",
            ),
        ],
    )
    def test_a_corrupted_projection_yields_a_named_mismatch(
        self, field: str, update: dict[str, Any], expected: str
    ) -> None:
        legacy, contract = _outcome_pair()
        mismatches = compare_outcomes(legacy, contract.model_copy(update=update))
        assert [item.field for item in mismatches] == [expected]
        assert mismatches[0].surface == "job"
        assert mismatches[0].detail

    def test_a_budget_stop_is_a_failed_row_and_a_budget_terminal_event(self) -> None:
        legacy, contract = _outcome_pair()
        stopped = legacy.model_copy(update={"status": "failed", "budget_stopped": True})
        assert (
            compare_outcomes(
                stopped, contract.model_copy(update={"terminal_event_type": "run.budget_stopped"})
            )
            == ()
        )
        assert compare_outcomes(
            stopped, contract.model_copy(update={"terminal_event_type": "run.failed"})
        )

    def test_a_bound_task_ref_must_address_the_compiled_spec(self) -> None:
        legacy, contract = _outcome_pair()
        bound = legacy.model_copy(
            update={
                "task_spec_id": "tsp_" + "9" * 20,
                "task_full_digest": "sha256:" + "f" * 64,
            }
        )
        assert {item.field for item in compare_outcomes(bound, contract)} == {
            "task_spec_id",
            "task_full_digest",
        }

    def test_a_state_whose_query_drifted_is_reported_not_raised(self) -> None:
        spec = compile_research_intake(
            config(),
            task_id="research-api:drift",
            query="the original question",
            hitl_plan_review=False,
            supervisor=False,
        )
        assert compare_research_state(spec, {"query": "the original question"}) == ()
        drifted = compare_research_state(spec, {"query": "something else"})
        assert [item.field for item in drifted] == ["query"]
        assert drifted[0].surface == "research_state"


def test_the_policy_shape_model_is_closed_and_immutable() -> None:
    shape = classify_policy_shape(config(), fixed_app())
    assert isinstance(shape, PolicyShape)
    with pytest.raises(ValueError):
        shape.arm_id = "D"  # type: ignore[misc]


class TestTheEdgesOfTheBinding:
    """The paths a happy run never reaches, and what each one answers."""

    def test_an_unrepresentable_shape_still_has_a_stable_digest(self) -> None:
        """A refusal is a fact about a run and needs an identity too.

        Without one, two runs that were both `capability_missing` for
        different reasons would be indistinguishable in a trajectory's
        `policy_ref`, which is the one field a reader groups by.
        """
        broken = classify_policy_shape(
            config(enable_supervisor=True), supervisor_app(verifier=False)
        )
        other = classify_policy_shape(config(enable_verifier=True), supervisor_app())
        assert broken.representable is False
        assert broken.policy_digest == classify_policy_shape(
            config(enable_supervisor=True), supervisor_app(verifier=False)
        ).policy_digest
        assert broken.policy_digest != other.policy_digest

    def test_asking_for_an_arm_the_shape_is_not_names_the_mismatch(self) -> None:
        shape = classify_policy_shape(config(), fixed_app())
        assert arm_capability_gap("A", shape) == ()
        assert arm_capability_gap("D", shape) == ("policy_shape_mismatch",)

    def test_semantic_scholar_widens_the_tool_policy_and_the_manifest(self) -> None:
        """A second retrieval provider is a permission, not a detail."""
        from src.contracts.research_binding import (
            SEMANTIC_SCHOLAR_TOOL,
            agent_tools,
            source_scope,
        )

        cfg = config(use_mock_data=False, enable_semantic_scholar=True)
        assert SEMANTIC_SCHOLAR_TOOL in agent_tools(cfg)
        assert SEMANTIC_SCHOLAR_TOOL in source_scope(cfg).allowed_providers
        assert SEMANTIC_SCHOLAR_TOOL not in agent_tools(config())

    def test_a_missing_prompt_constant_refuses_rather_than_hashing_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A prompt bundle that silently skipped a prompt would be a lie.

        The digest's whole job is to say "these are the instructions this
        run was given", so an unreadable one has to stop the seal rather
        than shrink the bundle.
        """
        from src.contracts import research_binding

        prompt_digests.cache_clear()
        monkeypatch.setattr(
            research_binding,
            "PROMPT_CONSTANTS",
            (("planner.system", "src.agents.planner", "NO_SUCH_PROMPT"),),
        )
        with pytest.raises(ResearchBindingError, match="unavailable"):
            prompt_digests()
        prompt_digests.cache_clear()

    def test_a_subtree_with_no_files_hashes_as_absent(self) -> None:
        """A pruned source tree is a different build, and says so.

        Raising here would refuse to describe a container image that
        shipped without its sources; hashing an empty dict would make
        every such image agree with every other. Naming the absence does
        neither.
        """
        from src.contracts.research_binding import _source_digest

        absent = _source_digest("src/no_such_package/*.py")
        assert absent == _source_digest("src/also_missing/*.py")
        assert absent != _source_digest("src/graph/*.py")

    def test_an_unreadable_source_file_is_recorded_rather_than_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.contracts.research_binding import _source_digest

        readable = _source_digest("src/graph/*.py")

        def _refuse(self: Path) -> bytes:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_bytes", _refuse)
        assert _source_digest("src/graph/*.py") != readable

    def test_the_null_task_store_keeps_nothing_and_says_so(self) -> None:
        """The receipt is real; the storage is P0-WO08's."""
        from src.contracts.research_binding import _NullTaskStore

        store = _NullTaskStore()
        spec = compile_research_intake(
            config(),
            task_id="research-api:null-store",
            query="a question",
            hitl_plan_review=False,
            supervisor=False,
        )
        assert store.put(spec) is None
        assert store.get(spec.task_spec_id) is None
