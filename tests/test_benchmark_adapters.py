"""No-cost contract tests for the registered research and learning benchmarks.

Every test here reads checked-in files and Python constants.  None of them
opens a socket, builds a provider client or spends anything —
`test_campaign_lock_dry_run_runs_with_both_guards_armed` proves the guards are
live while the lock is generated rather than asserting it in prose.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import ValidationError

import src.contracts.registry as registry_cli
from src.contracts.benchmark_adapters import (
    LEARNING_SUITE_ID,
    OBJECT_REVISION,
    REGISTRY_ROOT,
    RESEARCH_SUITE_ID,
    BenchmarkReader,
    ContentEnvelope,
    ContentKind,
    GraderLock,
    LearningExpectationsContent,
    LearningPaperContent,
    LearningPersonaContent,
    LearningScenarioInput,
    LearningScript,
    LearningTurnContent,
    LocalContentStore,
    ResearchExpectedTopics,
    build_parity_report,
    build_registry,
    learning_dataset_version,
    load_learning_benchmark,
    load_research_benchmark,
    main,
    read_registry,
    render_parity_report,
    seal_content_object,
    suite_ref,
    validate_content_safety,
)
from src.contracts.kernel import DataClass, ImmutableObjectRef, canonical_json, sha256_digest
from src.contracts.registry import (
    BenchmarkSuite,
    GraderProfile,
    IntendedUse,
    LabelSet,
    LifecycleStatus,
    ObjectVisibility,
    RegistryAccessError,
    RegistryResolutionError,
    RegistryRole,
    RubricSet,
    SourceMode,
    SplitAssignment,
    SplitKind,
    TaskCase,
    TaskSet,
    generate_campaign_lock,
    seal_registry_object,
    validate_lock,
    validate_registry_safety,
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
    SourceScope,
    TaskDataPolicy,
    TaskKind,
    TaskPolicyBundle,
    ToolPolicy,
    WorkflowCostBoundary,
    agent_safe_task_projection,
    compile_benchmark_case,
)
from src.eval.benchmark_queries import BENCHMARK_QUERIES
from src.eval.learning_benchmark import BENCHMARK_PAPERS, LEARNING_SCENARIOS, PERSONAS
from src.eval.learning_fixtures import FIXTURE_ROOT, load_manifest

pytestmark = pytest.mark.unit

VALIDATOR_REF = ImmutableObjectRef(
    kind="registry_validator",
    id="local-v1",
    revision="1.0.0",
    digest="sha256:" + "0" * 64,
)


def _ref(kind: str, object_id: str, digit: str = "1") -> ImmutableObjectRef:
    return ImmutableObjectRef(
        kind=kind,
        id=object_id,
        revision="1.0.0",
        digest="sha256:" + digit * 64,
    )


def _copy_tree(tmp_path: Path) -> Path:
    destination = tmp_path / "eval_registry"
    shutil.copytree(REGISTRY_ROOT, destination)
    return destination


def _content_path(root: Path, kind: ContentKind, content_id: str) -> Path:
    return root / "content" / kind.value / content_id / f"{OBJECT_REVISION}.json"


# ---------------------------------------------------------------------------
# Bijection: every old id, exactly one immutable case ref
# ---------------------------------------------------------------------------


def test_every_research_query_id_has_exactly_one_case_ref() -> None:
    reader = BenchmarkReader()
    refs = reader.case_refs(RESEARCH_SUITE_ID)
    registry_ids = [ref.id for ref in refs]
    module_ids = [query["query_id"] for query in BENCHMARK_QUERIES]

    assert len(registry_ids) == len(set(registry_ids)) == len(module_ids)
    assert set(registry_ids) == set(module_ids)
    assert all(ref.kind == "task_case" and ref.revision == OBJECT_REVISION for ref in refs)


def test_research_case_order_matches_the_module_byte_for_byte() -> None:
    # The scripted research tier's committed baseline is keyed by query id and
    # `regression_diff` pairs on id and order, so order is its own claim.
    registry_ids = [ref.id for ref in BenchmarkReader().case_refs(RESEARCH_SUITE_ID)]
    assert registry_ids == [query["query_id"] for query in BENCHMARK_QUERIES]


def test_every_learning_id_maps_one_to_one_into_the_registry() -> None:
    reader = BenchmarkReader()
    refs = reader.case_refs(LEARNING_SUITE_ID)
    assert [ref.id for ref in refs] == [item["scenario_id"] for item in LEARNING_SCENARIOS]

    bundle = read_registry()
    personas = {
        content.payload.persona_id
        for content in bundle.contents
        if isinstance(content.payload, LearningPersonaContent)
    }
    papers = {
        content.payload.paper_id
        for content in bundle.contents
        if isinstance(content.payload, LearningPaperContent)
    }
    scripts = {
        content.payload.scenario_id
        for content in bundle.contents
        if isinstance(content.payload, LearningScript)
    }
    expectations = {
        content.payload.scenario_id
        for content in bundle.contents
        if isinstance(content.payload, LearningExpectationsContent)
    }
    scenario_ids = {item["scenario_id"] for item in LEARNING_SCENARIOS}

    assert personas == {item["persona_id"] for item in PERSONAS}
    assert papers == {item["paper_id"] for item in BENCHMARK_PAPERS}
    assert scripts == scenario_ids
    assert expectations == scenario_ids


def test_the_registry_carries_no_case_the_modules_do_not_declare() -> None:
    bundle = read_registry()
    case_ids = [
        envelope.payload.case_id
        for envelope in bundle.objects
        if isinstance(envelope.payload, TaskCase)
    ]
    declared = {query["query_id"] for query in BENCHMARK_QUERIES} | {
        scenario["scenario_id"] for scenario in LEARNING_SCENARIOS
    }
    assert sorted(case_ids) == sorted(declared)
    assert len(case_ids) == len(set(case_ids))


# ---------------------------------------------------------------------------
# Projection: what each role can and cannot reach
# ---------------------------------------------------------------------------


def _projection(role: RegistryRole, suite_id: str, index: int = 0) -> dict[str, Any]:
    from src.contracts.benchmark_adapters import project_case

    evaluator = BenchmarkReader(role=RegistryRole.EVALUATOR)
    ref = evaluator.case_refs(suite_id)[index]
    return project_case(BenchmarkReader(role=role), ref)


def test_candidate_projection_shows_the_query_and_hides_the_expected_topics() -> None:
    projection = _projection(RegistryRole.CANDIDATE, RESEARCH_SUITE_ID)
    case = projection["case"]
    query = BENCHMARK_QUERIES[0]

    assert case["case_id"] == query["query_id"]
    assert case["task_input"]["objective"] == query["query"]
    assert case["task_input"]["task_kind"] == "research.focused_evidence_review"
    assert "evaluator_refs" not in case
    assert "slice_tags" not in case
    assert projection["content"] == []

    rendered = canonical_json(projection)
    for topic in query["expected_topics"]:
        assert topic not in rendered
    assert query["notes"] not in rendered


def test_evaluator_projection_resolves_the_expected_topics() -> None:
    projection = _projection(RegistryRole.EVALUATOR, RESEARCH_SUITE_ID)
    topics = [item for item in projection["content"] if item["kind"] == "research_expected_topics"]

    assert len(topics) == 1
    assert topics[0]["payload"]["expected_topics"] == BENCHMARK_QUERIES[0]["expected_topics"]
    assert projection["case"]["slice_tags"] == [BENCHMARK_QUERIES[0]["domain"]]


def test_candidate_projection_of_a_learning_case_hides_the_script() -> None:
    projection = _projection(RegistryRole.CANDIDATE, LEARNING_SUITE_ID)
    scenario = LEARNING_SCENARIOS[0]
    kinds = [item["kind"] for item in projection["content"]]

    assert kinds == ["learning_scenario_input", "learning_persona", "learning_paper"]
    rendered = canonical_json(projection)
    for turn in scenario["turns"]:
        assert turn["text"] not in rendered
    assert scenario["expectations"]["expected_assessment"] not in rendered
    assert scenario["notes"] not in rendered


def test_evaluator_projection_of_a_learning_case_resolves_script_and_expectations() -> None:
    projection = _projection(RegistryRole.EVALUATOR, LEARNING_SUITE_ID)
    kinds = [item["kind"] for item in projection["content"]]
    scenario = LEARNING_SCENARIOS[0]

    assert "learning_script" in kinds and "learning_expectations" in kinds
    script = next(item for item in projection["content"] if item["kind"] == "learning_script")
    assert [turn["text"] for turn in script["payload"]["turns"]] == [
        turn["text"] for turn in scenario["turns"]
    ]


@pytest.mark.parametrize(
    ("kind", "object_id"),
    [
        ("label_set", "research-policy-expected-topics"),
        ("grader_profile", "current-research-metrics"),
        ("split_assignment", "research-policy-splits"),
        ("task_set", "research-policy-tasks"),
        ("benchmark_suite", RESEARCH_SUITE_ID),
        ("label_set", "guided-learning-expectations"),
        ("grader_profile", "current-learning-metrics"),
    ],
)
def test_candidate_cannot_resolve_evaluator_only_registry_objects(
    kind: str, object_id: str
) -> None:
    bundle = read_registry()
    ref = next(
        envelope.object_ref()
        for envelope in bundle.objects
        if envelope.object_ref().kind == kind and envelope.object_ref().id == object_id
    )
    reader = BenchmarkReader(role=RegistryRole.CANDIDATE)
    with pytest.raises(RegistryAccessError):
        reader.registry.resolve(
            ref, role=RegistryRole.CANDIDATE, intended_use=IntendedUse.DEVELOPMENT
        )


def test_candidate_cannot_resolve_evaluator_content_even_with_its_exact_ref() -> None:
    bundle = read_registry()
    ref = next(
        content.object_ref()
        for content in bundle.contents
        if isinstance(content.payload, LearningScript)
    )
    reader = BenchmarkReader(role=RegistryRole.CANDIDATE)
    with pytest.raises(RegistryAccessError, match="candidate cannot resolve"):
        reader.content.resolve(ref, role=RegistryRole.CANDIDATE)
    assert reader.content.resolve(ref, role=RegistryRole.EVALUATOR).object_ref() == ref


# ---------------------------------------------------------------------------
# Identity and immutability
# ---------------------------------------------------------------------------


def test_digests_survive_key_order_and_a_process_restart() -> None:
    bundle = build_registry()
    suite = next(
        envelope for envelope in bundle.objects if isinstance(envelope.payload, BenchmarkSuite)
    )
    payload = suite.payload.model_dump(mode="json")
    reordered = dict(reversed(list(payload.items())))

    assert sha256_digest(reordered) == suite.integrity.payload_digest

    script = (
        "from src.contracts.benchmark_adapters import build_registry; "
        "print(build_registry().research_suite_ref.digest)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert completed.stdout.strip() == bundle.research_suite_ref.digest


def test_the_checked_in_tree_is_exactly_what_the_modules_build() -> None:
    built = build_registry()
    on_disk = read_registry()

    assert on_disk.research_suite_ref == built.research_suite_ref
    assert on_disk.learning_suite_ref == built.learning_suite_ref
    assert {envelope.object_ref() for envelope in on_disk.objects} == {
        envelope.object_ref() for envelope in built.objects
    }
    assert {content.object_ref() for content in on_disk.contents} == {
        content.object_ref() for content in built.contents
    }


def test_every_registered_object_passes_the_safety_scan() -> None:
    bundle = read_registry()
    for envelope in bundle.objects:
        validate_registry_safety(envelope)
    for content in bundle.contents:
        validate_content_safety(content)


def test_content_safety_refuses_a_secret_shaped_value() -> None:
    envelope = seal_content_object(
        ResearchExpectedTopics(case_id="synthetic", expected_topics=("api_key=sk-not-a-real-key",)),
        content_id="synthetic",
        visibility=ObjectVisibility.EVALUATOR,
        effective_data_class=DataClass.PUBLIC,
        source_module="tests/test_benchmark_adapters.py",
    )
    with pytest.raises(RegistryAccessError, match="secret-shaped"):
        validate_content_safety(envelope)


# ---------------------------------------------------------------------------
# Intended use and split
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suite_id", [RESEARCH_SUITE_ID, LEARNING_SUITE_ID])
@pytest.mark.parametrize(
    "use", [IntendedUse.PROMOTION, IntendedUse.CALIBRATION, IntendedUse.CAPABILITY_PROBE]
)
def test_public_suites_are_barred_from_promotion_and_undeclared_uses(
    suite_id: str, use: IntendedUse
) -> None:
    reader = BenchmarkReader(intended_use=use)
    with pytest.raises(RegistryResolutionError, match="does not declare|prohibits"):
        reader.suite(suite_id)


def test_promotion_use_cannot_produce_a_campaign_lock() -> None:
    with pytest.raises(RegistryResolutionError, match="does not declare promotion"):
        generate_campaign_lock(
            registry_cli.LocalRegistry(REGISTRY_ROOT),
            suite_ref(REGISTRY_ROOT, RESEARCH_SUITE_ID),
            case_ids=("scaling-laws",),
            repeats=1,
            intended_use=IntendedUse.PROMOTION,
            source_mode=SourceMode.LIVE,
        )


def test_a_sealed_split_over_these_cases_fails_closed(tmp_path: Path) -> None:
    # Renaming the split is exactly the move RFC 11 §11 forbids; the resolver
    # refuses it because no access broker exists, not because of a convention.
    bundle = read_registry()
    development = next(
        envelope.payload
        for envelope in bundle.objects
        if isinstance(envelope.payload, SplitAssignment)
        and envelope.payload.split_assignment_id == "research-policy-splits"
    )
    sealed = seal_registry_object(
        development.model_copy(update={"split": SplitKind.SEALED})
    )
    root = tmp_path / "sealed"
    (root / "split_assignment" / "research-policy-splits").mkdir(parents=True)
    (root / "split_assignment" / "research-policy-splits" / "1.0.0.json").write_text(
        canonical_json(sealed), encoding="utf-8"
    )
    resolver = registry_cli.LocalRegistry(root)
    with pytest.raises(registry_cli.RestrictedRegistryUnavailable, match="access broker"):
        resolver.resolve(
            sealed.object_ref(),
            role=RegistryRole.EVALUATOR,
            intended_use=IntendedUse.DEVELOPMENT,
        )


def test_research_and_learning_stay_separate_lanes() -> None:
    reader = BenchmarkReader()
    research = reader.suite(RESEARCH_SUITE_ID)
    learning = reader.suite(LEARNING_SUITE_ID)

    assert research.evaluation_lane.value == "research"
    assert learning.evaluation_lane.value == "guided_learning"
    assert research.task_set_ref != learning.task_set_ref
    assert research.rubric_set_ref != learning.rubric_set_ref
    assert research.grader_profile_refs != learning.grader_profile_refs
    assert research.split_assignment_ref != learning.split_assignment_ref
    assert not set(research.task_kinds) & set(learning.task_kinds)
    research_cases = {ref.id for ref in reader.case_refs(RESEARCH_SUITE_ID)}
    learning_cases = {ref.id for ref in reader.case_refs(LEARNING_SUITE_ID)}
    assert not research_cases & learning_cases
    assert learning.fixture_set_refs and not research.fixture_set_refs


# ---------------------------------------------------------------------------
# Adapters: the old runner shapes, rebuilt from registry content
# ---------------------------------------------------------------------------


def test_research_adapter_rebuilds_the_module_list_exactly() -> None:
    assert load_research_benchmark() == BENCHMARK_QUERIES


def test_learning_adapter_rebuilds_the_module_lists_exactly() -> None:
    view = load_learning_benchmark()
    assert view.scenarios == LEARNING_SCENARIOS
    assert view.personas == PERSONAS
    assert view.papers == BENCHMARK_PAPERS


def test_learning_dataset_fingerprint_matches_the_simulator_constant() -> None:
    from src.eval.simulate_learner import LEARNING_DATASET_NAME, LEARNING_DATASET_VERSION

    assert LEARNING_DATASET_NAME == "learning-benchmark"
    assert learning_dataset_version() == LEARNING_DATASET_VERSION


def test_dataset_fingerprints_are_recorded_on_the_task_sets() -> None:
    from src.eval.benchmark_queries import RESEARCH_DATASET_VERSION

    bundle = read_registry()
    records = {
        envelope.payload.task_set_id: envelope.payload.provenance.review_record
        for envelope in bundle.objects
        if isinstance(envelope.payload, TaskSet)
    }
    assert RESEARCH_DATASET_VERSION in records["research-policy-tasks"]
    assert learning_dataset_version() in records["guided-learning-tasks"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def test_fixture_sets_preserve_the_manifest_status_and_the_recorded_files() -> None:
    manifest = load_manifest(FIXTURE_ROOT)
    bundle = read_registry()
    fixture_sets = {
        envelope.payload.fixture_set_id: envelope.payload
        for envelope in bundle.objects
        if isinstance(envelope.payload, registry_cli.FixtureSet)
    }
    assert len(fixture_sets) == len(manifest["fixture_sets"])

    for entry in manifest["fixture_sets"]:
        slug = entry["name"].replace("_", "-")
        registered = fixture_sets[f"learning-{slug}"]
        expected_status = (
            LifecycleStatus.ACTIVE if entry["status"] == "complete" else LifecycleStatus.DRAFT
        )
        assert registered.status is expected_status
        files = sorted((FIXTURE_ROOT / entry["directory"]).glob("*.json"))
        assert len(registered.observations) == len(files)
        for observation, path in zip(registered.observations, files, strict=True):
            assert observation.observation_ref.id == path.stem
            assert observation.observation_ref.digest.startswith("sha256:")
            assert observation.sanitized is True


def test_every_scenario_with_a_recording_references_it_and_no_scenario_invents_one() -> None:
    reader = BenchmarkReader()
    recorded = {
        path.stem for path in (FIXTURE_ROOT / "recorded_mock_sessions").glob("*.json")
    }
    for ref in reader.case_refs(LEARNING_SUITE_ID):
        case = reader.case(ref)
        fixture_refs = [
            item for item in case.evaluator_refs if item.kind == "learning_fixture"
        ]
        assert len(fixture_refs) == (1 if case.case_id in recorded else 0)
        for item in fixture_refs:
            assert item.id == case.case_id


# ---------------------------------------------------------------------------
# Campaign lock dry run
# ---------------------------------------------------------------------------


def test_campaign_lock_dry_run_runs_with_both_guards_armed(
    guard_exceptions: tuple[type[BaseException], type[BaseException]],
) -> None:
    network_denied, spend_denied = guard_exceptions
    import src.llm as llm_module

    with socket.socket() as probe, pytest.raises(network_denied):
        probe.connect(("api.anthropic.com", 443))
    with pytest.raises(spend_denied):
        llm_module._get_client()

    resolver = registry_cli.LocalRegistry(REGISTRY_ROOT)
    reference = suite_ref(REGISTRY_ROOT, RESEARCH_SUITE_ID)
    lock = generate_campaign_lock(
        resolver,
        reference,
        case_ids=tuple(query["query_id"] for query in BENCHMARK_QUERIES),
        repeats=3,
        intended_use=IntendedUse.DEVELOPMENT,
        source_mode=SourceMode.LIVE,
    )

    assert lock.split == "development"
    assert [ref.id for ref in lock.case_refs] == [q["query_id"] for q in BENCHMARK_QUERIES]
    assert lock.exclusions == ()
    assert lock.expected_denominator == len(BENCHMARK_QUERIES) * 3
    for ref in (*lock.case_refs, *lock.resolved_refs):
        assert ref.digest.startswith("sha256:")
        resolved = resolver.resolve(
            ref, role=RegistryRole.EVALUATOR, intended_use=IntendedUse.DEVELOPMENT
        )
        assert resolved.object_ref() == ref

    receipt = validate_lock(lock, validated_at="2026-09-05T00:00:00Z", validator_ref=VALIDATOR_REF)
    assert receipt.resolved_object_count == len(lock.resolved_refs)
    assert receipt.lock_digest == sha256_digest(lock)


def test_two_lock_runs_resolve_the_same_order_and_digests() -> None:
    resolver = registry_cli.LocalRegistry(REGISTRY_ROOT)
    reference = suite_ref(REGISTRY_ROOT, RESEARCH_SUITE_ID)
    cases = tuple(query["query_id"] for query in BENCHMARK_QUERIES[:5])
    first = generate_campaign_lock(
        resolver,
        reference,
        case_ids=cases,
        repeats=1,
        intended_use=IntendedUse.DEVELOPMENT,
        source_mode=SourceMode.LIVE,
    )
    second = generate_campaign_lock(
        resolver,
        reference,
        case_ids=cases,
        repeats=1,
        intended_use=IntendedUse.DEVELOPMENT,
        source_mode=SourceMode.LIVE,
    )
    assert sha256_digest(first) == sha256_digest(second)
    assert len(first.exclusions) == len(BENCHMARK_QUERIES) - 5


# ---------------------------------------------------------------------------
# TaskSpec compilation from a registry case
# ---------------------------------------------------------------------------


def _requested_policy(corpus_mode: CorpusMode, data_class: DataClass) -> TaskPolicyBundle:
    return TaskPolicyBundle(
        source_scope=SourceScope(
            policy_ref=_ref("source_policy", "scholarly-default", "2"),
            corpus_mode=corpus_mode,
            allowed_providers=("arxiv",) if corpus_mode is CorpusMode.LIVE else (),
            allowed_source_types=("paper",),
        ),
        freshness=FreshnessRequirement(
            mode=FreshnessMode.LATEST_AVAILABLE
            if corpus_mode is CorpusMode.LIVE
            else FreshnessMode.NO_REQUIREMENT
        ),
        tool_policy=ToolPolicy(
            policy_ref=_ref("tool_policy", "research-readonly", "3"),
            allowed_agent_tools=("arxiv_search",),
            denied_action_ids=("repository_write",),
            network_access="allowlisted" if corpus_mode is CorpusMode.LIVE else "none",
        ),
        execution_limits=ExecutionLimits(
            hard_timeout_seconds=900,
            max_tool_calls=20,
            max_model_calls=20,
            workflow_cost=WorkflowCostBoundary(
                chargeable_work="forbidden", workflow_spend_ceiling_usd="0.000000"
            ),
        ),
        autonomy=AutonomyPolicy(maximum_tier=AutonomyTier.A1_BOUNDED_TOOLS),
        data_policy=TaskDataPolicy(
            policy_ref=_ref("data_policy", "eval-no-training", "4"),
            data_class=data_class,
            processing_purposes=("aggregate_analytics",),
            retention_policy_ref=registry_cli.RetentionPolicyRef(
                kind="retention_policy",
                id="repository-history",
                revision="1.0.0",
                digest="sha256:" + "5" * 64,
            ),
        ),
    )


def _platform(corpus_mode: CorpusMode) -> PlatformPolicyCeiling:
    return PlatformPolicyCeiling(
        allowed_corpus_modes=(corpus_mode,),
        allowed_providers=("arxiv",),
        allowed_source_types=("paper",),
        allowed_agent_tools=("arxiv_search",),
        denied_action_ids=("deploy",),
        network_access="allowlisted" if corpus_mode is CorpusMode.LIVE else "none",
        maximum_autonomy_tier=AutonomyTier.A1_BOUNDED_TOOLS,
        hard_timeout_seconds=900,
        max_tool_calls=20,
        max_model_calls=20,
        chargeable_work="forbidden",
        workflow_spend_ceiling_usd="0.000000",
        minimum_data_class=DataClass.PUBLIC,
        allowed_processing_purposes=("aggregate_analytics",),
    )


@pytest.mark.parametrize(
    ("suite_id", "task_kind", "surface", "corpus_mode", "data_class"),
    [
        (
            RESEARCH_SUITE_ID,
            TaskKind.RESEARCH_FOCUSED_EVIDENCE_REVIEW,
            ProductSurface.RESEARCH_EVAL,
            CorpusMode.LIVE,
            DataClass.PUBLIC,
        ),
        (
            LEARNING_SUITE_ID,
            TaskKind.LEARNING_GUIDED_READING,
            ProductSurface.LEARNING_EVAL,
            CorpusMode.CURATED,
            DataClass.LEARNER_SENSITIVE,
        ),
    ],
)
def test_one_case_from_each_lane_compiles_without_evaluator_material(
    suite_id: str,
    task_kind: TaskKind,
    surface: Literal[ProductSurface.RESEARCH_EVAL, ProductSurface.LEARNING_EVAL],
    corpus_mode: CorpusMode,
    data_class: DataClass,
) -> None:
    reader = BenchmarkReader()
    suite = reader.suite(suite_id)
    case_ref = reader.case_refs(suite_id)[0]
    case = reader.case(case_ref)
    spec = compile_benchmark_case(
        task_id=f"{suite_id}:{case.case_id}",
        task_kind=task_kind,
        objective=case.task_input.objective,
        # Empty on purpose: `ContextRef.kind_matches_ref` admits only
        # supplied_corpus/source_snapshot/content_entry/artifact reference
        # kinds, so a registry `learning_persona` ref cannot ride in a
        # candidate context yet (src/contracts/task_spec.py:346).
        candidate_visible_refs=(),
        origin=BenchmarkOrigin(
            suite_ref=suite_ref(REGISTRY_ROOT, suite_id),
            task_set_ref=suite.task_set_ref,
            task_case_ref=case_ref,
        ),
        product_surface=surface,
        requested_policy=_requested_policy(corpus_mode, data_class),
        platform_policy=_platform(corpus_mode),
        compiler_ref=_ref("task_compiler", "deterministic-v1", "6"),
        compiled_at="2026-09-05T00:00:00Z",
    )

    assert spec.objective == case.task_input.objective
    assert spec.benchmark_origin is not None
    assert spec.benchmark_origin.task_case_ref == case_ref

    agent_view = canonical_json(agent_safe_task_projection(spec))
    assert "benchmark_origin" not in agent_view
    for evaluator_ref in case.evaluator_refs:
        assert evaluator_ref.digest not in agent_view
    assert case.provenance.review_record not in agent_view


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------


def test_parity_is_clean_on_this_tree() -> None:
    report = build_parity_report()

    assert report.ok
    assert report.mismatches == ()
    assert report.research_case_count == len(BENCHMARK_QUERIES)
    assert report.learning_case_count == len(LEARNING_SCENARIOS)
    assert report.checked_object_count == len(read_registry().objects) + len(
        read_registry().contents
    )
    assert "every id, order, field and score semantic matches." in render_parity_report(report)


def test_an_edited_expected_topic_is_reported_as_a_named_mismatch(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    case_id = BENCHMARK_QUERIES[0]["query_id"]
    path = _content_path(root, ContentKind.RESEARCH_EXPECTED_TOPICS, case_id)
    original = ContentEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
    assert isinstance(original.payload, ResearchExpectedTopics)
    drifted = seal_content_object(
        original.payload.model_copy(
            update={"expected_topics": ("a topic nobody wrote", *original.payload.expected_topics)}
        ),
        content_id=original.content_id,
        visibility=original.visibility,
        effective_data_class=original.effective_data_class,
        source_module=original.source_module,
        created_at=original.created_at,
    )
    path.write_text(canonical_json(drifted) + "\n", encoding="utf-8")

    report = build_parity_report(root)

    assert not report.ok
    subjects = [mismatch.subject for mismatch in report.mismatches]
    assert any(case_id in subject for subject in subjects)
    content_mismatch = next(item for item in report.mismatches if item.scope == "content")
    assert case_id in content_mismatch.subject
    assert "expected_topics" in content_mismatch.detail
    assert "a topic nobody wrote" in content_mismatch.detail
    assert content_mismatch.lane == "research"
    assert "MISMATCH" in render_parity_report(report)


def test_a_reordered_task_set_is_reported_as_an_order_mismatch(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    path = root / "task_set" / "research-policy-tasks" / "1.0.0.json"
    envelope = registry_cli.RegistryEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
    assert isinstance(envelope.payload, TaskSet)
    swapped = (envelope.payload.case_refs[1], envelope.payload.case_refs[0])
    reordered = seal_registry_object(
        envelope.payload.model_copy(
            update={"case_refs": (*swapped, *envelope.payload.case_refs[2:])}
        )
    )
    path.write_text(canonical_json(reordered) + "\n", encoding="utf-8")

    report = build_parity_report(root)
    order = [item for item in report.mismatches if item.scope == "order"]

    assert len(order) == 1
    assert order[0].lane == "research"
    assert BENCHMARK_QUERIES[0]["query_id"] in order[0].detail


def _rewrite_learning_task_set(root: Path, case_refs: tuple[Any, ...]) -> None:
    path = root / "task_set" / "guided-learning-tasks" / "1.0.0.json"
    envelope = registry_cli.RegistryEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
    assert isinstance(envelope.payload, TaskSet)
    edited = seal_registry_object(envelope.payload.model_copy(update={"case_refs": case_refs}))
    path.write_text(canonical_json(edited) + "\n", encoding="utf-8")


def _learning_case_refs(root: Path) -> tuple[Any, ...]:
    path = root / "task_set" / "guided-learning-tasks" / "1.0.0.json"
    envelope = registry_cli.RegistryEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
    assert isinstance(envelope.payload, TaskSet)
    return envelope.payload.case_refs


def test_a_dropped_case_is_reported_as_membership_and_as_a_missing_record(
    tmp_path: Path,
) -> None:
    root = _copy_tree(tmp_path)
    _rewrite_learning_task_set(root, _learning_case_refs(root)[1:])

    report = build_parity_report(root)
    dropped = LEARNING_SCENARIOS[0]["scenario_id"]

    assert any(
        item.scope == "membership" and item.subject == dropped for item in report.mismatches
    )
    # Re-sealing the task set moved its digest, so the suite's pinned reference
    # no longer resolves: a child cannot be edited without its parent noticing.
    assert any(item.scope == "adapter" for item in report.mismatches)
    assert any(
        item.scope == "object_content" and "guided-learning-tasks" in item.subject
        for item in report.mismatches
    )


def test_a_record_the_adapter_cannot_rebuild_is_named() -> None:
    from src.contracts.benchmark_adapters import _compare_records

    mismatches = _compare_records(
        "research", "benchmark_query", BENCHMARK_QUERIES[:2], BENCHMARK_QUERIES[1:2], "query_id"
    )

    assert len(mismatches) == 1
    assert mismatches[0].subject == BENCHMARK_QUERIES[0]["query_id"]
    assert "rebuilt no record" in mismatches[0].detail


def test_an_invented_case_is_reported_as_membership(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    existing = _learning_case_refs(root)
    invented = existing[0].model_copy(update={"id": "a-scenario-nobody-wrote"})
    _rewrite_learning_task_set(root, (*existing, invented))

    report = build_parity_report(root)

    assert any(
        item.scope == "membership" and item.subject == "a-scenario-nobody-wrote"
        for item in report.mismatches
    )
    assert any(item.scope == "adapter" for item in report.mismatches)


def test_an_object_the_modules_do_not_produce_is_reported(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    source = _content_path(root, ContentKind.LEARNING_PAPER, "arxiv-1706-03762")
    envelope = ContentEnvelope.model_validate_json(source.read_text(encoding="utf-8"))
    invented = seal_content_object(
        envelope.payload,
        content_id="arxiv-0000-00000",
        visibility=envelope.visibility,
        effective_data_class=envelope.effective_data_class,
        source_module=envelope.source_module,
    )
    destination = _content_path(root, ContentKind.LEARNING_PAPER, "arxiv-0000-00000")
    destination.parent.mkdir(parents=True)
    destination.write_text(canonical_json(invented) + "\n", encoding="utf-8")

    report = build_parity_report(root)
    unregistered = [item for item in report.mismatches if item.scope == "unregistered_object"]

    assert len(unregistered) == 1
    assert "arxiv-0000-00000" in unregistered[0].subject


def test_a_mislocated_object_is_reported(tmp_path: Path) -> None:
    # A locator is not identity, but a locator that disagrees with identity
    # makes the object unresolvable: the resolver derives the path from the ref.
    root = _copy_tree(tmp_path)
    source = _content_path(root, ContentKind.LEARNING_PAPER, "arxiv-1706-03762")
    destination = _content_path(root, ContentKind.LEARNING_PAPER, "somewhere-else")
    destination.parent.mkdir(parents=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    report = build_parity_report(root)
    locators = [item for item in report.mismatches if item.scope == "locator"]

    assert len(locators) == 1
    assert "somewhere-else" in locators[0].subject


def test_a_tampered_file_is_reported_rather_than_raised(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    path = _content_path(root, ContentKind.LEARNING_SCRIPT, LEARNING_SCENARIOS[0]["scenario_id"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["payload"]["turns"][0]["text"] = "an utterance nobody scripted"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = build_parity_report(root)
    envelope_errors = [item for item in report.mismatches if item.scope == "envelope"]

    assert envelope_errors, "an unsealed edit must be named, not raised"
    assert "learning_script" in envelope_errors[0].detail
    with pytest.raises(RegistryResolutionError, match="invalid registry object"):
        read_registry(root)


def test_a_missing_object_is_reported(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    _content_path(root, ContentKind.LEARNING_EXPECTATIONS, LEARNING_SCENARIOS[2]["scenario_id"]).unlink()

    report = build_parity_report(root)

    assert any(item.scope == "missing_content" for item in report.mismatches)
    assert any(item.scope == "adapter" for item in report.mismatches)


def test_a_drifted_grader_lock_is_reported_as_a_score_semantic_mismatch(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    path = _content_path(root, ContentKind.GRADER_LOCK, "current-research-metrics")
    envelope = ContentEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
    lock = envelope.payload
    assert isinstance(lock, GraderLock)
    drifted = seal_content_object(
        lock.model_copy(update={"campaign_rubric_names": ("completeness",)}),
        content_id=envelope.content_id,
        visibility=envelope.visibility,
        effective_data_class=envelope.effective_data_class,
        source_module=envelope.source_module,
    )
    path.write_text(canonical_json(drifted) + "\n", encoding="utf-8")

    report = build_parity_report(root)
    semantics = [item for item in report.mismatches if item.scope == "score_semantics"]

    assert semantics and "campaign_rubric_names" in semantics[0].subject


# ---------------------------------------------------------------------------
# Command-line surfaces
# ---------------------------------------------------------------------------


def test_the_writer_regenerates_a_byte_identical_tree(tmp_path: Path) -> None:
    root = tmp_path / "eval_registry"
    assert main(["--root", str(root)]) == 0

    written = sorted(path.relative_to(root) for path in root.rglob("*.json"))
    committed = sorted(path.relative_to(REGISTRY_ROOT) for path in REGISTRY_ROOT.rglob("*.json"))
    assert written == committed
    for relative in written:
        assert (root / relative).read_bytes() == (REGISTRY_ROOT / relative).read_bytes()


def test_the_parity_cli_reports_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert registry_cli.main(["parity", str(REGISTRY_ROOT)]) == 0
    assert "mismatches       0" in capsys.readouterr().out


def test_the_parity_cli_exits_nonzero_on_a_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy_tree(tmp_path)
    (root / "task_case" / BENCHMARK_QUERIES[3]["query_id"] / "1.0.0.json").unlink()

    assert registry_cli.main(["parity", str(root)]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_the_resolve_cli_still_hides_evaluator_material(
    capsys: pytest.CaptureFixture[str],
) -> None:
    case_ref = BenchmarkReader().case_refs(RESEARCH_SUITE_ID)[0]
    assert (
        registry_cli.main(
            [
                "resolve",
                str(REGISTRY_ROOT),
                case_ref.kind,
                case_ref.id,
                case_ref.revision,
                case_ref.digest,
                "--use",
                "development",
                "--role",
                "candidate",
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert BENCHMARK_QUERIES[0]["query"] in printed
    for topic in BENCHMARK_QUERIES[0]["expected_topics"]:
        assert topic not in printed


# ---------------------------------------------------------------------------
# Store error paths
# ---------------------------------------------------------------------------


def test_content_store_rejects_an_unknown_object_and_an_escaping_locator() -> None:
    store = BenchmarkReader().content
    with pytest.raises(RegistryResolutionError, match="unavailable"):
        store.resolve(_ref("learning_script", "no-such-scenario"), role=RegistryRole.EVALUATOR)
    # `model_construct` skips validation on purpose: the kind pattern already
    # forbids a traversal, and this proves the store would still refuse one.
    escaping = ImmutableObjectRef.model_construct(
        kind="../../etc",
        id="passwd",
        revision="1.0.0",
        digest="sha256:" + "1" * 64,
    )
    with pytest.raises(RegistryResolutionError, match="escaped its root"):
        store.resolve(escaping, role=RegistryRole.EVALUATOR)


def test_content_store_rejects_a_digest_that_does_not_match_the_reference() -> None:
    reader = BenchmarkReader()
    ref = next(
        content.object_ref()
        for content in read_registry().contents
        if isinstance(content.payload, LearningScenarioInput)
    )
    with pytest.raises(RegistryResolutionError, match="does not match the exact reference"):
        reader.content.resolve(
            ref.model_copy(update={"digest": "sha256:" + "e" * 64}),
            role=RegistryRole.EVALUATOR,
        )


def test_suite_ref_refuses_an_unknown_suite() -> None:
    with pytest.raises(RegistryResolutionError, match="no suite"):
        suite_ref(REGISTRY_ROOT, "no-such-suite")


def test_the_registry_exposes_the_objects_a_run_manifest_needs() -> None:
    # RunManifest.RegistryResolution pins suite, task set, case, split, rubric,
    # grader and label refs; every one of them must exist by exact kind.
    reader = BenchmarkReader()
    suite = reader.suite(RESEARCH_SUITE_ID)
    bundle = read_registry()
    kinds = {envelope.object_ref().kind for envelope in bundle.objects}

    assert {
        "benchmark_suite",
        "task_set",
        "task_case",
        "rubric_set",
        "label_set",
        "split_assignment",
        "grader_profile",
        "retention_policy",
        "fixture_set",
    } <= kinds
    assert suite.rubric_set_ref.kind == "rubric_set"
    assert all(ref.kind == "grader_profile" for ref in suite.grader_profile_refs)
    assert all(ref.kind == "label_set" for ref in suite.label_set_refs)
    for envelope in bundle.objects:
        if isinstance(envelope.payload, RubricSet | GraderProfile | LabelSet):
            assert envelope.payload.visibility is ObjectVisibility.EVALUATOR


# ---------------------------------------------------------------------------
# Content-model rules
# ---------------------------------------------------------------------------


def test_a_grader_lock_cannot_run_a_rubric_it_does_not_pin() -> None:
    with pytest.raises(ValidationError, match="campaign rubrics are not locked"):
        GraderLock(
            grader_lock_id="synthetic",
            rubrics=(),
            campaign_rubric_names=("completeness",),
            judge_model_route="settings.eval_judge_model",
            judge_model_resolution="resolved in the RunManifest before an approved run",
        )


def test_a_research_case_cannot_register_an_empty_reference_answer() -> None:
    with pytest.raises(ValidationError, match="at least one expected topic"):
        ResearchExpectedTopics(case_id="synthetic", expected_topics=())


def test_a_script_cannot_skip_a_turn_index() -> None:
    with pytest.raises(ValidationError, match="contiguous from 0"):
        LearningScript(
            scenario_id="synthetic",
            turns=(
                LearningTurnContent(turn_index=0, intent="check_in", text="hello", note=""),
                LearningTurnContent(turn_index=2, intent="end_session", text="bye", note=""),
            ),
        )


def test_a_content_envelope_cannot_mislabel_its_payload() -> None:
    envelope = seal_content_object(
        ResearchExpectedTopics(case_id="synthetic", expected_topics=("a topic",)),
        content_id="synthetic",
        visibility=ObjectVisibility.EVALUATOR,
        effective_data_class=DataClass.PUBLIC,
        source_module="tests/test_benchmark_adapters.py",
    )
    payload = json.loads(canonical_json(envelope))
    payload["schema_kind"] = ContentKind.LEARNING_SCRIPT.value
    with pytest.raises(ValidationError):
        ContentEnvelope.model_validate(payload)


def test_content_safety_refuses_a_private_absolute_path() -> None:
    envelope = seal_content_object(
        ResearchExpectedTopics(case_id="synthetic", expected_topics=("/Users/someone/notes.md",)),
        content_id="synthetic",
        visibility=ObjectVisibility.EVALUATOR,
        effective_data_class=DataClass.PUBLIC,
        source_module="tests/test_benchmark_adapters.py",
    )
    with pytest.raises(RegistryAccessError, match="private absolute path"):
        validate_content_safety(envelope)


def test_no_role_below_owner_resolves_owner_only_content(tmp_path: Path) -> None:
    envelope = seal_content_object(
        ResearchExpectedTopics(case_id="synthetic", expected_topics=("a topic",)),
        content_id="synthetic",
        visibility=ObjectVisibility.OWNER,
        effective_data_class=DataClass.PUBLIC,
        source_module="tests/test_benchmark_adapters.py",
    )
    root = tmp_path / "eval_registry"
    ref = envelope.object_ref()
    path = root / "content" / ref.kind / ref.id / f"{ref.revision}.json"
    path.parent.mkdir(parents=True)
    path.write_text(canonical_json(envelope) + "\n", encoding="utf-8")
    store = LocalContentStore(root)

    with pytest.raises(RegistryAccessError, match="owner-only"):
        store.resolve(ref, role=RegistryRole.EVALUATOR)
    with pytest.raises(RegistryAccessError, match="candidate cannot resolve"):
        store.resolve(ref, role=RegistryRole.CANDIDATE)
    assert store.resolve(ref, role=RegistryRole.OWNER).object_ref() == ref


def test_reading_a_mislocated_tree_raises_rather_than_resolving_it(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    source = _content_path(root, ContentKind.LEARNING_PAPER, "arxiv-1706-03762")
    destination = _content_path(root, ContentKind.LEARNING_PAPER, "filed-wrong")
    destination.parent.mkdir(parents=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(RegistryResolutionError, match="mislocated registry object"):
        read_registry(root)
